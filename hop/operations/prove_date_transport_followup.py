#!/usr/bin/env python3
"""Close temporal/NULL transport postconditions in a tiny isolated native fixture.

No archive restore, source HTTP, provider calls or production actions. Retains the
failed parent unchanged; exact deployed date blocks run with synthetic SQL input.
"""
# pyright: basic
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from benchmark_archived_routine import ROOT, RoutineFixture, sha
from profile_archived_postgres import write_json

from hop.ingestions.jobkorea.tests.native import Fixture


def seal_combined(parent_path: Path, focused_path: Path) -> Path:
    """Seal completed parent obligations plus the isolated missing postconditions."""
    parent = json.loads(parent_path.read_text())
    focused = json.loads(focused_path.read_text())
    if (parent['status'] != 'FAILED'
            or focused['status'] != 'PASSED_TINY_NATIVE_DATE_TRANSPORT_CORRECTION'
            or focused['failed_parent_sha256'] != sha(parent_path)
            or focused['failed_parent_unchanged'] is not True):
        raise RuntimeError('Parent/focused evidence does not match')
    for receipt in (parent, focused):
        if (receipt['disposable_resources_removed'] is not True
                or receipt['private_scratch_removed'] is not True
                or receipt['cleanup_failures'] != []):
            raise RuntimeError('Every evidence fixture must have exact verified cleanup')
    obligations = {
        'candidate-canonical-installer', 'candidate-focused-date-installer',
        'prime-complete-routine', 'routine-0-baseline', 'routine-1-candidate',
        'negative-kind-rejected', 'negative-kind-repaired',
        'date-refused-wrong-kind', 'date-write-refused-wrong-kind',
        'date-repaired-wrong-kind', 'date-refused-missing-identity',
        'date-write-refused-missing-identity', 'date-repaired-missing-identity',
        'date-wrong-type-refused', 'date-typed-repair', 'date-typed-repaired',
        'date-null-load_posting_dates', 'date-null-verify_posting_dates',
    }
    if not obligations <= set(parent['checks']):
        raise RuntimeError('A required native parent obligation is missing')
    if (len(parent['samples']) != 3
            or any(s['result'] != 'PASSED' for s in parent['samples'])
            or any(value is not True for key, value in focused['date_null_transport'].items()
                   if key != 'final_boolean_output')):
        raise RuntimeError('Incomplete replay or focused temporal/cleanup proof')
    log_dir = parent_path.parent / 'logs'
    log_hashes = {}
    for kind in ('nodes', 'edges', 'inferred_element_ids'):
        original = sha(log_dir / ('graph-prime-' + kind + '.log'))
        for label in ('graph-0-baseline', 'graph-1-candidate', 'graph-after-negative'):
            path = log_dir / (label + '-' + kind + '.log')
            if sha(path) != original:
                raise RuntimeError('Parent typed graph/inferred IDs differ')
            log_hashes[path.name] = sha(path)
    for check in obligations:
        path = log_dir / (check + '.log')
        log_hashes[path.name] = sha(path)
    for key, value in focused['artifact_hashes'].items():
        if parent['candidate_artifact_sha256'][key] != value:
            raise RuntimeError('Focused/native date artifact binding mismatch')
    result = dict(
        status='PASSED_COMBINED_ARCHIVED_REPLAY_AND_FOCUSED_DATE_PROOF',
        isolated=True, no_source_requests=True, no_paid_calls=True, production_writes=False,
        failed_parent=str(parent_path), failed_parent_sha256=sha(parent_path),
        focused_receipt=str(focused_path), focused_receipt_sha256=sha(focused_path),
        artifact_hashes=parent['candidate_artifact_sha256'],
        candidate_sql_sha256=parent['candidate_sql_sha256'], samples=parent['samples'],
        expected_rows=parent['expected_rows'], statistics=parent['statistics'],
        archived_inference_scope=parent['archived_inference_scope'],
        inference_preservation_scope='5878 actual archived inference payloads including21 reviewed '
            'materialized on minimal occupation endpoints, plus a separate synthetic sentinel. '
            'Exact fixture graph properties and edge/endpoint element IDs survive both replays. '
            'Original production IDs/full NCS ontology are not reproduced.',
        completed_parent_checks=sorted(obligations), protected_log_sha256=log_hashes,
        parser_failure='Parent final predicate was uppercase TRUE, rejected by lowercase-only '
            'harness. Original FAILED receipt bytes remain intact.',
        focused_postconditions=focused['date_null_transport'],
        limitation='Parent final synthetic-node DELETE and final post-date graph snapshot were '
            'not executed. Their postconditions passed separately in the tiny synthetic fixture. '
            'The archive graph snapshot was exact after both full replays and the generic '
            'negative repair; real date negative repairs passed authoritative verifiers. '
            'No claim of a final whole-archive post-date snapshot is made.',
        disposable_resources_removed=True, private_scratch_removed=True,
        cleanup_confirmed=True, cleanup_failures=[],
    )
    target = parent_path.parent / 'combined-native-proof.json'
    if target.exists():
        raise RuntimeError('Refuse to overwrite a sealed combined proof')
    write_json(target, result)
    return target


class TinyDateFixture(RoutineFixture):
    stage = Fixture.stage

    def __init__(self):
        Fixture.__init__(self, ROOT / 'AGENTS.md')
        self.args = argparse.Namespace(sql_timeout_seconds=30, stable_statistics=False)

    def command(self, args, label, input_text=None, success=True, timeout=120):
        if 'hop-run.sh' in args:
            timeout = 180
        return RoutineFixture.command(self, args, label, input_text, success, timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-parent', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    parent_hash = sha(args.failed_parent)
    parent = json.loads(args.failed_parent.read_text())
    if (parent['status'] != 'FAILED' or parent['failure_type'] != 'RuntimeError'
            or parent.get('disposable_resources_removed') is not True
            or parent.get('private_scratch_removed') is not True
            or parent.get('cleanup_failures') != []):
        raise RuntimeError('Unexpected failed parent or unverified cleanup')
    log = args.failed_parent.parent / 'logs/date-null-types-and-removal.log'
    if log.read_text().strip().splitlines()[-1] != 'TRUE':
        raise RuntimeError('Require exact parser-only uppercase TRUE parent observation')
    fixture = TinyDateFixture()
    date_hashes = {relative: sha(ROOT / 'hop' / relative) for relative in
                   ('graph/load_posting_dates.hpl', 'graph/verify_posting_dates.hpl')}
    if any(parent['candidate_artifact_sha256'][k] != v for k, v in date_hashes.items()):
        raise RuntimeError('Date artifacts differ from completed parent native trials')
    fixture.receipt.update(
        kind='TINY_NATIVE_DATE_TRANSPORT_CORRECTION',
        failed_parent=str(args.failed_parent.resolve()), failed_parent_sha256=parent_hash,
        failed_parent_boolean_log_sha256=sha(log),
        artifact_hashes=date_hashes,
        harness_sha256=sha(Path(__file__).parent / 'benchmark_archived_routine.py'),
        scope='Exact date transport/check blocks; synthetic SQL input and no proof capture. '
              'No archive replay, real source data or production element IDs reproduced.')
    try:
        fixture.boot()
        fixture.command(['docker', 'exec', fixture.neo, 'cypher-shell', '--format', 'plain',
            "CREATE(a:entity:jobPosting {id:'fixture:preserved:job',kind:'JobPosting'}),"
            "(b:entity:occupation {id:'fixture:preserved:ncs',kind:'Occupation'}),"
            "(a)-[:INFERRED_NCS_OCCUPATION {candidate_id:'fixture:preserved:candidate',"
            "basis:'METADATA_INFERRED',review_status:'UNREVIEWED'}]->(b) RETURN count(a)"],
            'seed-unrelated-preservation')
        original = fixture.graph_snapshot('graph-before-null-transport')
        fixture.date_null_transport(
            {'RUN_ID': 'fixture-date', 'NEO4J_CONNECTION': 'jobtology-neo4j'}, original)
        fixture.receipt['graph_before_and_after'] = original
        if any(date_hashes[k] != sha(ROOT / 'hop' / k) for k in date_hashes):
            raise RuntimeError('Runtime artifact changed during focused proof')
        fixture.receipt['status'] = 'PASSED_TINY_NATIVE_DATE_TRANSPORT_CORRECTION'
    except BaseException as error:
        fixture.receipt.update(status='FAILED', failure_type=type(error).__name__)
        raise
    finally:
        fixture.close()
        fixture.receipt['failed_parent_unchanged'] = sha(args.failed_parent) == parent_hash
        write_json(fixture.work / 'receipt.json', fixture.receipt)
        print(fixture.work / 'receipt.json', flush=True)
    print(seal_combined(args.failed_parent, fixture.work / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
