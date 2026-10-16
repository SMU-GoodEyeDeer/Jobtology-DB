#!/usr/bin/env python3
"""Reuse one owned archive fixture for bounded SQL profiles and native replay.

Only local supplied archives/images, one internal network, no source or model
calls. First-read profiles use untouched sibling databases; native trials then
use the original restored database with matched explicit ANALYZE. Cleanup closes
both phase receipts after all exact named containers/network/volumes are absent.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import benchmark_archived_routine as native
import profile_replay_reads as reads
from profile_archived_postgres import write_json


def run(args: argparse.Namespace) -> None:
    os.umask(0o077)
    args.baseline_source_sharing = True
    args.stable_statistics = True
    fixture = native.RoutineFixture(args)
    profile_path = None
    try:
        tick = time.monotonic()
        fixture.boot()
        fixture.receipt['fixture_boot_seconds'] = time.monotonic() - tick
        profile_args = argparse.Namespace(
            backup=args.backup, backup_sha256=args.backup_sha256,
            baseline_dir=args.baseline_dir, candidate_sql=args.candidate_sql[0],
            timeout_seconds=args.profile_timeout_seconds)
        profile_path = reads.run(profile_args, existing_fixture=fixture)
        native.run(args, fixture=fixture, restored=True)
    except BaseException as error:
        fixture.receipt.update(status='FAILED', failure_type=type(error).__name__)
        raise
    finally:
        if fixture.receipt.get('disposable_resources_removed') is not True:
            fixture.close()
            write_json(fixture.work / 'receipt.json', fixture.receipt)
        if profile_path is None:
            # The SQL helper records its path before beginning restore/queries.
            value = fixture.receipt.get('first_read_receipt')
            profile_path = Path(value) if value else None
        if profile_path is not None:
            receipt = json.loads(profile_path.read_text())
            receipt['cleanup_confirmed'] = (
                fixture.receipt.get('disposable_resources_removed') is True
                and fixture.receipt.get('private_scratch_removed') is True
                and not fixture.receipt.get('cleanup_failures'))
            receipt['cleanup_evidence'] = str(fixture.work / 'receipt.json')
            receipt['cleanup_evidence_sha256'] = native.sha(fixture.work / 'receipt.json')
            receipt['cleanup_deferred_to_owned_fixture'] = False
            write_json(profile_path, receipt)
        print(fixture.work / 'receipt.json', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--baseline-dir', required=True, type=Path)
    parser.add_argument('--candidate-sql', required=True, type=Path, action='append')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--archived-inference-limit', type=int, default=10000)
    parser.add_argument('--pair-order', choices=('ab', 'abba'), default='ab')
    parser.add_argument('--profile-timeout-seconds', type=int, default=60)
    parser.add_argument('--sql-timeout-seconds', type=int, default=180)
    args = parser.parse_args()
    if (len(args.candidate_sql) != 1
            or args.candidate_sql[0].name != '004_verified_proof_replay.sql'):
        parser.error('This paired replay requires the exact graph004 candidate only')
    if not 1 <= args.profile_timeout_seconds <= 180 or not 1 <= args.sql_timeout_seconds <= 300:
        parser.error('Use bounded focused/native statements')
    run(args)


if __name__ == '__main__':
    main()
