"""Offline scheduler dispatch and generated workflow regression checks."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest

ROOT = Path(__file__).resolve().parents[3]
OPERATIONS = ROOT / "hop/operations"
RUN_ID = "f3b83d1a-5103-40e1-9a1a-976d75b32be6"
SOURCES = [
    "alio_organization", "job_alio", "ncs_competency", "ncs_qualification",
    "qnet_schedule", "ncs_career_path", "nara_job",
]
KEY = "offline+/key=fixture"

DOCKER = r'''#!/usr/bin/env python3
import json, os, re, sys
from urllib.parse import quote, quote_plus
args = sys.argv[1:]
def record(value):
    with open(os.environ['MOCK_AUDIT'], 'a') as out:
        out.write(json.dumps(value) + '\n')
if args[0] == 'ps':
    print('aaaaaaaaaaaa' if any(x.startswith('volume=') for x in args) else 'bbbbbbbbbbbb')
elif 'psql' in args:
    query = sys.stdin.read().strip()
    record({'sql': query})
    if query.startswith('SELECT operation'):
        source = re.search(r"source_id='([^']+)'", query).group(1)
        row = json.loads(os.environ['MOCK_QUEUE']).get(source)
        if row:
            print(row)
    elif query.startswith('INSERT INTO ingestion.refresh_execution'):
        print('123')
elif 'df' in args:
    print('Filesystem 1024-blocks Used Available Capacity Mounted on')
    print('fixture 999999999 100000 ' + os.environ.get('MOCK_DF', '200000000 10%') + ' /fixture')
elif 'cat' in args:
    print('service_key\noffline+/key=fixture')
elif 'hop-run.sh' in args:
    workflow = args[args.index('-f') + 1]
    params = args[args.index('-p') + 1]
    record({'workflow': workflow, 'parameters': params, 'arguments': args})
    key = 'offline+/key=fixture'
    print('Provider forms: ' + ' '.join([key, quote(key, safe=''), quote_plus(key)]))
    sys.exit(int(os.environ.get('MOCK_HOP_EXIT', '0')))
else:
    raise SystemExit('Unexpected mock Docker command: ' + repr(args))
'''


@pytest.fixture
def scheduler(tmp_path):
    executable = tmp_path / "docker"
    executable.write_text(DOCKER)
    executable.chmod(0o700)
    state = tmp_path / "state"
    audit = tmp_path / "audit.jsonl"
    config = tmp_path / "runtime.env"
    # These paths are synthetic; the Docker mock never accesses a container.
    config.write_text(
        "HOP_CONFIG_VOLUME=fixture\nPG_CONTAINER_NAME=fixture\n"
        "PG_USER=fixture\nPG_DATABASE=fixture\nHOP_ROOT=/fixture/hop\n"
        "PROJECT_HOME=/fixture/project\nAPI_KEY_FILE=/fixture/key.csv\n"
        f"STATE_DIR='{state}'\nREDACTOR='{OPERATIONS / 'redact_runner.py'}'\n"
        "MIN_FREE_KIB=104857600\nMAX_USED_PERCENT=85\n"
    )
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "JOBTOLOGY_HOP_RUNTIME": str(config),
        "MOCK_AUDIT": str(audit),
        "MOCK_QUEUE": "{}",
    }

    def run(queue, **overrides):
        result = subprocess.run(
            ["bash", str(OPERATIONS / "refresh.sh")],
            env={**env, "MOCK_QUEUE": json.dumps(queue), **overrides},
            text=True, capture_output=True, check=False,
        )
        rows = (
            [json.loads(line) for line in audit.read_text().splitlines()] if audit.exists() else []
        )
        return result, rows

    return run, state


@pytest.mark.parametrize("operation", ["FETCH", "GRAPH"])
def test_nara_dispatch_exact_run_and_redacted_log(scheduler, operation):
    run, state = scheduler
    result, audit = run({"nara_job": f"{operation}|{RUN_ID if operation == 'GRAPH' else ''}"})
    assert result.returncode == 0, result.stderr
    invocation, = [row for row in audit if "workflow" in row]
    if operation == "FETCH":
        assert invocation["workflow"] == "/fixture/project/operations/refresh_nara_job.hwf"
        assert invocation["parameters"] == "MODE=FULL"
    else:
        assert invocation["workflow"] == "/fixture/project/operations/export_pending.hwf"
        assert invocation["parameters"] == f"RUN_ID={RUN_ID}"
    assert invocation["arguments"][-2:] == ["-l", "Basic"]
    updates = [row["sql"] for row in audit if row.get("sql", "").startswith("UPDATE")]
    assert len(updates) == 1 and "exit_code=0" in updates[0]
    logfile, = state.glob("*.log")
    assert logfile.stat().st_mode & 0o777 == 0o600
    output = logfile.read_text()
    assert output.count("<redacted>") == 3
    for form in (KEY, quote(KEY, safe=""), quote_plus(KEY)):
        assert form not in output + result.stdout + result.stderr


def test_existing_dependency_order_and_nara_failure_accounting(scheduler):
    run, _ = scheduler
    result, audit = run(dict.fromkeys(SOURCES, "FETCH|"), MOCK_HOP_EXIT="7")
    assert result.returncode == 1
    dispatched = [Path(row["workflow"]).stem for row in audit if "workflow" in row]
    assert dispatched == ["refresh_" + source for source in SOURCES]
    updates = [row["sql"] for row in audit if row.get("sql", "").startswith("UPDATE")]
    assert len(updates) == len(SOURCES)
    assert all("exit_code=7" in query for query in updates)
    assert not any("graph_export" in row.get("sql", "") for row in audit)


@pytest.mark.parametrize("df", ["104857599 10%", "200000000 85%"])
def test_nara_disk_reserve_stops_before_execution(scheduler, df):
    run, _ = scheduler
    result, audit = run({"nara_job": "FETCH|"}, MOCK_DF=df)
    assert result.returncode == 1
    assert "raw-volume reserve or usage limit reached" in result.stderr
    assert not any("workflow" in row for row in audit)
    assert not any(row.get("sql", "").startswith("INSERT") for row in audit)


def test_existing_lock_excludes_second_scheduler(scheduler):
    run, state = scheduler
    state.mkdir()
    with (state / "refresh.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # No Docker command runs when flock exits early.
        result, audit = run({"nara_job": "FETCH|"})
        assert result.returncode == 0
        assert audit == []
        assert not list(state.glob("*.log"))


def test_nara_wrapper_pins_parent_run_and_checks_only_after_graph_success():
    root = ET.parse(OPERATIONS / "refresh_nara_job.hwf").getroot()
    actions = {action.findtext("name"): action for action in root.findall("./actions/action")}
    defaults = {
        param.findtext("name"): param.findtext("default_value")
        for param in root.findall("./parameters/parameter")
    }
    assert defaults == {
        "MAX_PAGES": "20", "MAX_REQUESTS": "5000", "BEGIN_DATE": "", "END_DATE": "",
        "RAW_ROOT": "${PROJECT_HOME}/data/nara-job-raw", "MODE": "FULL",
        "API_KEY_FILE": "${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv",
    }
    start = actions["Create run and pin date window"]
    assert start.findtext("type") == "PIPELINE"
    assert start.findtext("filename") == "${PROJECT_HOME}/ingestions/nara_job/start_run.hpl"
    setter = ET.parse(ROOT / "hop/ingestions/nara_job/start_run.hpl").find(
        "transform[name='Remember run ID']/fields/field"
    )
    assert setter.findtext("variable_name") == "NARA_JOB_RUN_ID"
    assert setter.findtext("variable_type") == "PARENT_WORKFLOW"
    for name in ("Load accepted snapshot to graph", "Save graph checkpoint"):
        assert actions[name].findtext("parameters/parameter/name") == "RUN_ID"
        assert actions[name].findtext("parameters/parameter/value") == "${NARA_JOB_RUN_ID}"
    incoming = [
        h for h in root.findall("./hops/hop") if h.findtext("to") == "Save graph checkpoint"
    ]
    assert len(incoming) == 1
    assert incoming[0].findtext("from") == "Load accepted snapshot to graph"
    assert incoming[0].findtext("evaluation") == "Y"
    assert incoming[0].findtext("unconditional") == "N"
    failures = {
        h.findtext("from"): h.findtext("to") for h in root.findall("./hops/hop")
        if h.findtext("evaluation") == "N"
    }
    assert failures["Load accepted snapshot to graph"] == "Abort"
    assert failures["Save graph checkpoint"] == "Abort"
    for name, action in actions.items():
        if name != "Record failure" and action.findtext("filename", "").startswith(
            "${PROJECT_HOME}/ingestions/nara_job/"
        ):
            assert failures[name] == "Record failure"


def test_generator_reproduces_checked_in_wrapper(tmp_path):
    # Run the generator on an isolated copy; it also regenerates source artifacts.
    (tmp_path / "hop/ingestions/nara_job/sql").mkdir(parents=True)
    for directory in ("hop/ingestions/job_alio", "hop/metadata/pipeline-run-configuration",
                      "hop/metadata/workflow-run-configuration"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    for name in ("docs/hop-migration/checks.sql", "hop/operations/export_pending.hwf",
                 "hop/ingestions/nara_job/tools/build.py"):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    subprocess.run(
        [sys.executable, str(tmp_path / "hop/ingestions/nara_job/tools/build.py")], check=True,
    )
    generated = tmp_path / "hop/operations/refresh_nara_job.hwf"
    assert generated.read_bytes() == (OPERATIONS / generated.name).read_bytes()
