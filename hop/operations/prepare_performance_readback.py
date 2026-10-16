#!/usr/bin/env python3
"""Build private read-only verifier copies for an exact current VERIFIED load.

Preparation does not query a database or execute Hop. Guarded execution runs only
the private read-only copies, validates preflight/native row counts, and binds the
exact VERIFIED artifact receipt. Public templates and load state never change.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import backfill_posting_dates as dates
import deploy_jobkorea_runtime as deployment
import deploy_performance_runtime as rollout
import reconcile_runtime as common

ROOT = common.ROOT
STATE = common.STATE
ONTOLOGY = tuple('ontology/verify_' + kind + '.hpl' for kind in
                 ('node_scalars', 'node_arrays', 'edge_scalars', 'edge_arrays'))
SOURCE = ('graph/verify_entity_names.hpl',)
SOURCE_ALIAS = 'graph/verify_records.hpl'
READ_TRANSFORMS = frozenset(('GetVariable', 'TableInput', 'DBJoin', 'Neo4jCypherOutput',
                             'FilterRows', 'Dummy', 'Abort'))
ACTIVE_PREDICATE = "l.state IN ('RUNNING','STAGED')"


def parameter(root: ET.Element, name: str, value: str) -> None:
    parameters = root.find('./info/parameters')
    if parameters is None:
        raise RuntimeError('Verifier parameter definitions are absent')
    existing = [p for p in parameters if p.findtext('name') == name]
    if existing:
        raise RuntimeError('Unexpected preexisting readback parameter')
    entry = ET.SubElement(parameters, 'parameter')
    ET.SubElement(entry, 'name').text = name
    ET.SubElement(entry, 'default_value').text = value
    ET.SubElement(entry, 'description').text = 'Exact protected readback pin.'


def build(relative: str, load: str, release: str, database: str,
          source_run: str) -> tuple[ET.Element, str, dict[str, str]]:
    data = (ROOT / relative).read_bytes()
    root = ET.fromstring(data)
    if any(t.findtext('type') not in READ_TRANSFORMS for t in root.findall('transform')):
        raise RuntimeError('Verifier contains a transform outside the read-only allowlist')
    cyphers = root.findall("transform[type='Neo4jCypherOutput']")
    if len(cyphers) != 1 or cyphers[0].findtext('read_only') != 'Y':
        raise RuntimeError('Verifier does not have exactly one read-only graph query')
    filters = root.findall("transform[type='FilterRows']")
    if len(filters) != 1 or cyphers[0].findtext('batch_size') != '500':
        raise RuntimeError('Verifier must have one result filter and the reviewed 500-row batch')
    if relative in ONTOLOGY:
        query = root.find("transform[type='TableInput']/sql")
        if query is None or query.text is None or query.text.count(ACTIVE_PREDICATE) != 1:
            raise RuntimeError('Unexpected ontology active-token predicate')
        guard = (
            "l.state='VERIFIED' AND l.release_id=" + dates.quote(release)
            + ' AND l.database_id=' + dates.quote(database)
            + ' AND EXISTS(SELECT 1 FROM ontology.flat_graph_current current_pin '
            'WHERE current_pin.load_id=l.load_id AND current_pin.release_id=l.release_id '
            'AND current_pin.database_id=l.database_id)'
        )
        query.text = query.text.replace(ACTIVE_PREDICATE, guard)
        variable = root.find("transform[type='GetVariable']/fields/field/variable")
        if variable is None or variable.text != '${ONTOLOGY_LOAD_ID}':
            raise RuntimeError('Unexpected ontology load variable')
        variable.text = '${PERFORMANCE_READBACK_LOAD_ID}'
        parameter(root, 'PERFORMANCE_READBACK_LOAD_ID', load)
        parameter(root, 'NEO4J_CONNECTION', 'jobtology-neo4j')
        sql = query.text
        if sql.count('?') != 1:
            raise RuntimeError('Verifier must have exactly one exact load parameter')
        sql = sql.replace('?', dates.quote(load))
        count_sql = ('SELECT count(*) AS expected_owner_groups,'
                     'coalesce(sum(property_rows),0) AS expected_property_rows FROM ('
                     + sql + ') expected')
    elif relative in SOURCE:
        query = root.find("transform[type='DBJoin']/sql")
        if query is None or query.text != 'SELECT * FROM ingestion.graph_source_entities(?)':
            raise RuntimeError('Unexpected source verifier query')
        parameter(root, 'RUN_ID', source_run)
        parameter(root, 'NEO4J_CONNECTION', 'jobtology-neo4j')
        count_sql = ('SELECT count(*) AS expected_entity_rows FROM '
                     'ingestion.graph_source_entities(' + dates.quote(source_run) + ')')
    else:
        raise ValueError('Unknown readback verifier')
    return root, count_sql, {
        'original_sha256': hashlib.sha256(data).hexdigest(),
        'cypher_sha256': hashlib.sha256(
            ET.tostring(cyphers[0], encoding='utf-8')).hexdigest(),
        'expected_reader_name': root.findtext(
            "transform[type='TableInput']/name" if relative in ONTOLOGY else
            "transform[type='DBJoin']/name", ''),
        'operation_name': cyphers[0].findtext('name', ''),
        'filter_name': filters[0].findtext('name', ''),
        'success_name': filters[0].findtext('send_true_to', ''),
        'batch_size': '500',
    }


def prepare(load: str, release: str, database: str, source_run: str | None) -> Path:
    for identity in (load, release, database):
        dates.exact_identity(identity)
    if source_run is not None:
        dates.exact_identity(source_run)
    os.umask(0o077)
    directory = STATE / ('performance-readback-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700, parents=True)
    manifest: dict[str, Any] = {
        'version': 1, 'kind': 'PRIVATE_READ_ONLY_PERFORMANCE_READBACK',
        'load_id': load, 'release_id': release, 'database_id': database,
        'source_run': source_run, 'pipelines': {}, 'executed_queries': False,
        'executed_jobs': False, 'production_writes': 0,
    }
    counts: list[str] = []
    for relative in (*ONTOLOGY, *(SOURCE if source_run is not None else ())):
        root, sql, evidence = build(relative, load, release, database,
                                    source_run or 'ALL_CHECKPOINTED')
        destination = directory / Path(relative).name
        ET.indent(root, space='  ')
        ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)
        destination.chmod(0o600)
        manifest['pipelines'][relative] = {
            **evidence, 'path': str(destination),
            'copy_sha256': common.digest(destination.read_bytes()),
            'count_sql': sql,
        }
        counts.append('SELECT ' + dates.quote(relative) + ' AS pipeline,to_jsonb(expected) '
                      'AS expected FROM (' + sql + ') expected;')
    if source_run is not None:
        primary, alias = (ET.parse(ROOT / relative).getroot()
                          for relative in (SOURCE[0], SOURCE_ALIAS))
        for path in ("transform[type='DBJoin']", "transform[type='Neo4jCypherOutput']"):
            first, second = primary.find(path), alias.find(path)
            if first is None or second is None or ET.tostring(first) != ET.tostring(second):
                raise RuntimeError('Source compatibility verifier is not byte-equivalent')
        manifest['source_compatibility_alias'] = {
            'artifact': SOURCE_ALIAS, 'equivalent_to': SOURCE[0],
            'sha256': common.digest((ROOT / SOURCE_ALIAS).read_bytes()),
            'attestation': 'Identical SQL-reader and Cypher transforms, including mappings; '
                           'duplicate historical query is omitted.',
        }
    # Context must be exact and current; a successful empty pipeline is not proof.
    context = (
        "SELECT count(*)=1 AS exact_current_verified_context "
        'FROM ontology.flat_graph_current c JOIN ontology.flat_graph_load l USING(load_id) '
        'JOIN ontology.flat_graph_projection p ON p.release_id=l.release_id '
        'WHERE l.load_id=' + dates.quote(load) + " AND l.state='VERIFIED' "
        'AND l.release_id=' + dates.quote(release) + ' AND l.database_id=' + dates.quote(database)
        + ' AND c.database_id=l.database_id AND c.release_id=l.release_id '
        'AND p.node_count>0 AND p.edge_count>0;'
    )
    sql_path = directory / 'expected-counts.sql'
    sql_path.write_text("BEGIN READ ONLY;\nSET LOCAL statement_timeout='180s';\n"
                        + 'SELECT ontology.require_flat_graph_projection('
                        + dates.quote(release) + ',' + dates.quote(database) + ');\n'
                        + context + '\n' + '\n'.join(counts) + '\nCOMMIT;\n')
    sql_path.chmod(0o600)
    manifest['preflight_sql'] = str(sql_path)
    manifest['required_review'] = (
        'Require true exact_current_verified_context; record expected counts before native '
        'verification and require each native SQL reader output row count to equal its '
        'expected owner/entity count. Require nonzero total groups/properties. Zero groups '
        'in an individual property kind are explicit absence, not a verified property pass. '
        'Cypher is unchanged and read_only=Y. Recheck exact current context afterward. '
        'Hold refresh.lock and require idle runtime during native verification; these copies '
        'never register, stage or finish a load. Do not run legacy verifiers after flattening.'
    )
    path = directory / 'manifest.json'
    common.write_json(path, manifest)
    return path


def transform_counters(log: str, name: str) -> dict[str, int]:
    matches = re.findall(re.escape(name) + r'\.\d+.*Finished processing \(([^)]*)\)', log)
    if len(matches) != 1:
        raise RuntimeError('Native transform summary is absent or ambiguous; inspect protected log')
    counters = {key: int(value) for key, value in
                re.findall(r'([IORWUE])\s*=\s*(\d+)', matches[0])}
    if set(counters) != set('IORWUE') or counters['E'] != 0:
        raise RuntimeError('Native transform reported errors or missing counters')
    return counters


def log_reader_rows(log: str, reader: str) -> int:
    counters = transform_counters(log, reader)
    for summary in re.findall(r'Finished processing \(([^)]*)\)', log):
        errors = re.search(r'E\s*=\s*(\d+)', summary)
        if errors is None or errors[1] != '0':
            raise RuntimeError('Native transform reported errors; inspect protected log')
    return counters['W']


def verifier_counters(log: str, evidence: dict[str, Any], expected: int) -> dict[str, Any]:
    batches = (expected + int(evidence['batch_size']) - 1) // int(evidence['batch_size'])
    operation = transform_counters(log, evidence['operation_name'])
    result = transform_counters(log, evidence['filter_name'])
    success = transform_counters(log, evidence['success_name'])
    if operation['R'] != expected or operation['W'] != batches or any(
        counter['R'] != batches or counter['W'] != batches for counter in (result, success)
    ):
        raise RuntimeError('Native verifier batch counts differ from preflight scope')
    return {'expected_batches': batches, 'operation': operation,
            'result_filter': result, 'success_sink': success}


def pipeline_duration(log: str, pipeline: str) -> float:
    matches = re.findall(re.escape(pipeline)
                         + r'\s*-\s*Pipeline duration\s*:\s*([0-9]+(?:\.[0-9]+)?) seconds', log)
    if len(matches) != 1:
        raise RuntimeError('Native pipeline duration is absent or ambiguous')
    return float(matches[0])


def current_context(pg: str, manifest: dict[str, Any]) -> dict[str, Any]:
    load, release, database = (dates.quote(manifest[k]) for k in
                               ('load_id', 'release_id', 'database_id'))
    value = json.loads(deployment.sql(pg, "BEGIN READ ONLY; SET LOCAL statement_timeout='30s'; "
        'SELECT to_jsonb(l) FROM ontology.flat_graph_current c JOIN ontology.flat_graph_load l '
        'USING(load_id) WHERE l.load_id=' + load + " AND l.state='VERIFIED' AND l.release_id="
        + release + ' AND l.database_id=' + database
        + ' AND c.database_id=l.database_id AND c.release_id=l.release_id; COMMIT;') or 'null')
    if value is None:
        raise RuntimeError('Exact current VERIFIED load context is absent')
    return value


def verified_inputs(manifest: dict[str, Any], artifact_receipt: dict[str, Any],
                    runtime: dict[str, str]) -> None:
    if artifact_receipt.get('kind') != 'PERFORMANCE_ARTIFACT_ONLY' or (
        artifact_receipt.get('status') != 'VERIFIED' or artifact_receipt['containers'] != runtime
    ):
        raise RuntimeError('Exact VERIFIED performance artifact receipt is required')
    selected = rollout.artifacts(list(artifact_receipt['artifacts']))
    for relative in selected:
        actual = common.digest(rollout.read_remote(runtime['hop'], relative))
        if actual != artifact_receipt['artifacts'][relative]['after']:
            raise RuntimeError('Deployed performance artifact drifted since its receipt')
    expected_files = (*ONTOLOGY, *(SOURCE if manifest['source_run'] is not None else ()))
    if set(manifest['pipelines']) != set(expected_files):
        raise RuntimeError('Unexpected private verifier selection')
    for relative in expected_files:
        evidence = manifest['pipelines'][relative]
        if relative not in artifact_receipt['artifacts'] or (
            evidence['original_sha256'] != artifact_receipt['artifacts'][relative]['after']
        ):
            raise RuntimeError('Readback source is not bound to the deployed artifact receipt')
        path = Path(evidence['path'])
        if path.is_symlink() or common.digest(path.read_bytes()) != evidence['copy_sha256']:
            raise RuntimeError('Private verifier copy hash changed')
        root, count_sql, original = build(relative, manifest['load_id'], manifest['release_id'],
            manifest['database_id'], manifest['source_run'] or 'ALL_CHECKPOINTED')
        ET.indent(root, space='  ')
        generated = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        if generated != path.read_bytes() or any(
            evidence.get(key) != value for key, value in original.items()
        ) or count_sql != evidence['count_sql']:
            raise RuntimeError('Private copy no longer matches the reviewed read-only builder')
    if manifest['source_run'] is not None:
        alias = manifest['source_compatibility_alias']
        if SOURCE_ALIAS not in artifact_receipt['artifacts'] or alias['sha256'] != (
            artifact_receipt['artifacts'][SOURCE_ALIAS]['after']
        ):
            raise RuntimeError('Source compatibility verifier receipt differs')


def execute(manifest_path: Path, artifact_receipt_path: Path,
            runtime: dict[str, str]) -> Path:
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get('kind') != 'PRIVATE_READ_ONLY_PERFORMANCE_READBACK' or (
        manifest.get('version') != 1
    ):
        raise RuntimeError('Unrecognized private readback manifest')
    for key in ('load_id', 'release_id', 'database_id'):
        dates.exact_identity(manifest[key])
    if manifest['source_run'] is not None:
        dates.exact_identity(manifest['source_run'])
    artifact_receipt = json.loads(artifact_receipt_path.read_bytes())
    rollout.idle(runtime)
    if (STATE / rollout.FENCE_NAME).exists():
        raise RuntimeError('Recover the existing fenced operation before readback')
    verified_inputs(manifest, artifact_receipt, runtime)
    directory = STATE / ('performance-readback-executed-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    receipt_path = directory / 'receipt.json'
    receipt: dict[str, Any] = {
        'kind': 'READ_ONLY_PERFORMANCE_READBACK', 'status': 'RUNNING',
        'manifest': str(manifest_path.resolve()), 'manifest_sha256':
            common.digest(manifest_path.read_bytes()),
        'artifact_receipt': str(artifact_receipt_path.resolve()),
        'artifact_receipt_sha256': common.digest(artifact_receipt_path.read_bytes()),
        'runtime': runtime, 'production_writes': 0, 'source_requests': 0, 'paid_calls': 0,
        'pipelines': [],
    }
    common.write_json(receipt_path, receipt)
    try:
        receipt['context_before'] = current_context(runtime['pg'], manifest)
        clauses = ["SELECT " + dates.quote(relative) + ' AS name,to_jsonb(expected) AS counts '
                   'FROM (' + evidence['count_sql'] + ') expected'
                   for relative, evidence in manifest['pipelines'].items()]
        started = time.monotonic()
        counts = json.loads(deployment.sql(runtime['pg'],
            "BEGIN READ ONLY; SET LOCAL statement_timeout='180s'; "
            'SELECT ontology.require_flat_graph_projection(' + dates.quote(manifest['release_id'])
            + ',' + dates.quote(manifest['database_id']) + '); '
            'SELECT jsonb_object_agg(name,counts) FROM (' + ' UNION ALL '.join(clauses)
            + ') expected; COMMIT;'))
        receipt['preflight_seconds'] = time.monotonic() - started
        receipt['expected_counts'] = counts
        if sum(int(counts[r]['expected_property_rows']) for r in ONTOLOGY) <= 0:
            raise RuntimeError('Empty ontology property scope is not verification evidence')
        common.write_json(receipt_path, receipt)
        for relative, evidence in manifest['pipelines'].items():
            key = 'expected_owner_groups' if relative in ONTOLOGY else 'expected_entity_rows'
            expected = int(counts[relative][key])
            if expected == 0 and relative in ONTOLOGY:
                receipt['pipelines'].append({'artifact': relative, 'result': 'EMPTY_PROPERTY_KIND',
                                             'expected_groups': 0, 'executed': False})
                continue
            if expected <= 0:
                raise RuntimeError('Empty source entity scope is not verification evidence')
            started = time.monotonic()
            log = dates.temporary_native(runtime['hop'], Path(evidence['path']), directory,
                                         Path(relative).stem)
            output = log.read_text()
            rows = log_reader_rows(output, evidence['expected_reader_name'])
            native_seconds = pipeline_duration(output, Path(relative).stem)
            if rows != expected:
                raise RuntimeError('Native verifier read count differs from preflight scope')
            counters = verifier_counters(output, evidence, expected)
            receipt['pipelines'].append({'artifact': relative, 'result': 'VERIFIED',
                                         'expected_groups': expected, 'actual_reader_rows': rows,
                                         'wall_seconds': time.monotonic() - started,
                                         'native_pipeline_seconds': native_seconds,
                                         'native_counters': counters,
                                         'log': str(log)})
            common.write_json(receipt_path, receipt)
        rollout.idle(runtime)
        receipt['context_after'] = current_context(runtime['pg'], manifest)
        if receipt['context_before'] != receipt['context_after']:
            raise RuntimeError('Current flat projection changed during read-only verification')
        verified_inputs(manifest, artifact_receipt, runtime)
        receipt['status'] = 'VERIFIED'
    except BaseException as error:
        receipt['status'] = 'FAILED'
        receipt['failure_type'] = type(error).__name__
        raise RuntimeError(
            f'Read-only verification failed; inspect protected {receipt_path}') from error
    finally:
        common.write_json(receipt_path, receipt)
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--load-id')
    parser.add_argument('--release-id')
    parser.add_argument('--database-id')
    parser.add_argument('--source-run', help='Optional exact source run or ALL_CHECKPOINTED')
    parser.add_argument('--execute-manifest', type=Path)
    parser.add_argument('--artifact-receipt', type=Path)
    args = parser.parse_args()
    if args.execute_manifest:
        if not args.artifact_receipt or any((args.load_id, args.release_id,
                                           args.database_id, args.source_run)):
            parser.error('Execution requires only --execute-manifest and --artifact-receipt')
        os.umask(0o077)
        descriptor = os.open(STATE / 'refresh.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Scheduler/native lock is busy') from None
            print(execute(args.execute_manifest, args.artifact_receipt, common.containers()))
    else:
        if args.artifact_receipt or not all((args.load_id, args.release_id, args.database_id)):
            parser.error('Preparation requires exact --load-id, --release-id, --database-id')
        print(prepare(args.load_id, args.release_id, args.database_id, args.source_run))


if __name__ == '__main__':
    main()
