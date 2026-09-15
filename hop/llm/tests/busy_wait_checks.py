"""Native regression for the PipelineExecutor failure-check CPU busy-wait."""
from pathlib import Path
import os
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET


def _put(parent, name, value):
    node = ET.SubElement(parent, name)
    node.text = str(value)
    return node


def _runtime_transform(kind, name, fields=()):
    transform = ET.Element('transform')
    _put(transform, 'type', kind)
    _put(transform, 'name', name)
    if fields:
        rows = ET.SubElement(transform, 'fields')
        for field_name, value, field_type in fields:
            field = ET.SubElement(rows, 'field')
            for key, item in (
                ('name', field_name), ('variable', value), ('type', field_type),
                ('length', -1), ('precision', -1), ('trim_type', 'none')):
                _put(field, key, item)
    _put(transform, 'copies', 1)
    _put(transform, 'distribute', 'Y')
    gui = ET.SubElement(transform, 'GUI')
    _put(gui, 'xloc', 320)
    _put(gui, 'yloc', 80)
    partitioning = ET.SubElement(transform, 'partitioning')
    _put(partitioning, 'method', 'none')
    _put(partitioning, 'schema_name', '')
    return transform


def _replace_transform(root, name, replacement):
    transforms = list(root.findall('transform'))
    old = next(node for node in transforms if node.findtext('name') == name)
    root.insert(list(root).index(old), replacement)
    root.remove(old)


def _write_xml(root, path):
    ET.indent(root, space='  ')
    ET.ElementTree(root).write(path, encoding='UTF-8', xml_declaration=True)


def _make_legacy_pipeline(source, target):
    root = ET.parse(source).getroot()
    for transform in root.findall("transform[type='FilterRows']"):
        if transform.findtext('name') in ('Check child errors', 'Check child result'):
            transform.find('send_false_to').text = 'Child failed'
    for hop in root.findall('order/hop'):
        if hop.findtext('to') in ('Child error count failed', 'Child result failed'):
            hop.find('to').text = 'Child failed'
    first = root.find("transform[name='Child error count failed']")
    first.find('name').text = 'Child failed'
    first.find('message').text = 'Legacy shared Abort fixture'
    root.remove(root.find("transform[name='Child result failed']"))
    _write_xml(root, target)


def _make_delayed_workflow(source, target, extraction_pipeline):
    root = ET.parse(source).getroot()
    root.find('name').text = 'Busy-wait delayed request fixture'
    action = next(action for action in root.findall('actions/action')
                  if action.findtext('filename', '').endswith('/run_extract.hpl'))
    action.find('filename').text = '${PROJECT_HOME}/llm/' + extraction_pipeline
    _write_xml(root, target)


def _make_branch_fixture(source, target, errors, result):
    root = ET.parse(source).getroot()
    root.find('info/name').text = target.stem
    _replace_transform(root, 'Pending requests', _runtime_transform('Dummy', 'Pending requests'))
    _replace_transform(root, 'Run sequential request', _runtime_transform('GetVariable', 'Run sequential request', (
        ('ExecutionNrErrors', errors, 'Integer'),
        ('ExecutionResult', result, 'Boolean'))))
    _write_xml(root, target)


def _hop_command(t, file, params=()):
    return ['docker', 'exec',
        '-e', 'HOP_CONFIG_FOLDER=' + t.REMOTE + '/config',
        '-e', 'HOP_OPTIONS=-Xmx768m -Djavax.net.ssl.trustStore=' + t.REMOTE + '/truststore -Djavax.net.ssl.trustStorePassword=test-only',
        '-w', '/opt/hop', t.HOP, 'bash', 'hop-run.sh', '-j', 'llm-test', '-r', 'llm-local',
        '-f', t.REMOTE + '/project/llm/' + file,
        '-p', ','.join(key + '=' + str(value) for key, value in params), '-l', 'Basic']


def _java_pid(t):
    script = """for f in /proc/[0-9]*/cmdline; do
      directory=${f%/cmdline}
      [ "$(cat "$directory/comm" 2>/dev/null)" = java ] || continue
      value=$(tr '\\000' ' ' < "$f")
      case "$value" in *org.apache.hop.run.HopRun*) basename "$directory";; esac
    done"""
    pids = t.cmd(['docker', 'exec', t.HOP, 'sh', '-c', script]).stdout.split()
    assert len(pids) == 1, ('Expected one HopRun JVM', pids)
    return pids[0]


def _cpu_seconds(t, pid):
    value = t.cmd(['docker', 'exec', t.HOP, 'cat', '/proc/' + pid + '/stat']).stdout
    fields = value.rsplit(')', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')


def _measure_waiting_cpu(t, workflow, model, marker):
    if marker.exists():
        marker.unlink()
    params = dict(DATASET_ID='test-ko', POSTING_LIMIT=1, PROMPT_VERSION='ko-v1',
        EXECUTE_REQUESTS='Y', ENDPOINT='https://' + t.MOCK + ':8443/chat/completions',
        API_KEY_FILE=t.REMOTE + '/key.csv', EXTRACT_MODEL=model,
        CATEGORIZE_MODEL='test/categorizer', REQUEST_DELAY_MS=1,
        READ_TIMEOUT_MS=15000, REUSE_CACHE='N')
    process = subprocess.Popen(_hop_command(t, workflow, params.items()), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 90
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(.1)
    assert marker.exists(), process.communicate(timeout=10)[0][-6000:]
    pid = _java_pid(t)
    started = time.monotonic()
    before = _cpu_seconds(t, pid)
    time.sleep(3)
    cpu = _cpu_seconds(t, pid) - before
    elapsed = time.monotonic() - started
    output = process.communicate(timeout=60)[0]
    assert process.returncode == 0, output[-6000:]
    return cpu, elapsed


def _assert_branch_aborts(t, file, expected, absent):
    process = subprocess.run(_hop_command(t, file, [('LLM_BATCH_ID', 'fixture')]),
        text=True, capture_output=True)
    output = process.stdout + process.stderr
    assert process.returncode != 0, output[-6000:]
    assert expected in output, output[-6000:]
    assert absent not in output, output[-6000:]


def check_busy_wait(t):
    source = t.ROOT / 'hop/llm/run_extract.hpl'
    work = t.WORK / 'busy-wait'
    work.mkdir()
    legacy_pipeline = work / 'run_extract_legacy_busywait.hpl'
    legacy_workflow = work / 'evaluate_legacy_busywait.hwf'
    _make_legacy_pipeline(source, legacy_pipeline)
    _make_delayed_workflow(t.ROOT / 'hop/llm/evaluate.hwf', legacy_workflow,
        legacy_pipeline.name)
    error_fixture = work / 'child_error_count_branch.hpl'
    result_fixture = work / 'child_result_branch.hpl'
    _make_branch_fixture(source, error_fixture, '1', 'Y')
    _make_branch_fixture(source, result_fixture, '0', 'N')
    for path in (legacy_pipeline, legacy_workflow, error_fixture, result_fixture):
        t.cmd(['docker', 'cp', str(path), t.HOP + ':' + t.REMOTE + '/project/llm/'])

    legacy_cpu, legacy_elapsed = _measure_waiting_cpu(t, legacy_workflow.name,
        'test/delayed-legacy', t.WORK / 'delay-legacy')
    fixed_cpu, fixed_elapsed = _measure_waiting_cpu(t, 'evaluate.hwf',
        'test/delayed-fixed', t.WORK / 'delay-fixed')
    legacy_ratio = legacy_cpu / legacy_elapsed
    fixed_ratio = fixed_cpu / fixed_elapsed
    assert legacy_ratio > .70, (legacy_cpu, legacy_elapsed, legacy_ratio)
    assert fixed_ratio < .20, (fixed_cpu, fixed_elapsed, fixed_ratio)
    assert fixed_ratio < legacy_ratio / 4, (legacy_ratio, fixed_ratio)

    _assert_branch_aborts(t, error_fixture.name,
        'LLM request pipeline reported errors',
        'LLM request pipeline returned an unsuccessful result')
    _assert_branch_aborts(t, result_fixture.name,
        'LLM request pipeline returned an unsuccessful result',
        'LLM request pipeline reported errors')
    print('Busy-wait CPU legacy %.3fs/%.3fs, fixed %.3fs/%.3fs; both Abort branches passed' %
        (legacy_cpu, legacy_elapsed, fixed_cpu, fixed_elapsed), flush=True)
