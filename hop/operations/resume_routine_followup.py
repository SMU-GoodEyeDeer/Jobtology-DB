#!/usr/bin/env python3
"""Resume a deliberately interrupted, exact owned fixture with a new frozen candidate.

Preserves the prior frozen artifact and read samples. Only new matched analyzed
SQL replay, correctness, first capture and native replay phases execute. No source
or model calls and no production resources are accepted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import benchmark_archived_routine as native
import profile_replay_reads as reads
from profile_archived_postgres import Session, docker, safe_runs, write_json


def run(args: argparse.Namespace) -> None:
    os.umask(0o077)
    prior = json.loads(args.prior_profile.read_text())
    work = Path(prior["owned_shared_fixture"])
    token = work.name.removeprefix("jobkorea-dry-run-")
    if not token.isalnum() or len(token) != 12 or work.parent != reads.STATE:
        raise ValueError("Exact owned private fixture required")
    prefix = "jobtology-jobkorea-test-" + token
    if prior["container"] != prefix + "-pg" or prior["status"] != "INTERRUPTED_CANDIDATE_REVIEW":
        raise ValueError("Fixture/profile interruption identity differs")
    if (
        native.sha(args.backup) != args.backup_sha256
        or args.backup_sha256 != prior["backup_sha256"]
    ):
        raise ValueError("Approved unchanged archive required")
    network = json.loads(
        subprocess.check_output(["docker", "network", "inspect", prefix + "-net"])
    )[0]
    if not network["Internal"]:
        raise ValueError("Owned internal network required")
    for suffix in ("pg", "neo", "hop"):
        info = json.loads(subprocess.check_output(["docker", "inspect", prefix + "-" + suffix]))[0]
        if prefix + "-net" not in info["NetworkSettings"]["Networks"]:
            raise ValueError("Owned container network identity differs")
    fixture = native.RoutineFixture.__new__(native.RoutineFixture)
    fixture.token, fixture.prefix, fixture.network = token, prefix, prefix + "-net"
    fixture.pg, fixture.neo, fixture.hop = (prefix + "-pg", prefix + "-neo", prefix + "-hop")
    fixture.database, fixture.work, fixture.logs = "jobtology", work, work / "logs"
    fixture.input, fixture.args = args.backup, args
    fixture.original_definitions, fixture.function_names, fixture.variant_definitions = [], [], {}
    fixture.candidate_directory = work / ("candidate-corrected-" + uuid.uuid4().hex[:8])
    fixture.candidate_directory.mkdir(mode=0o700)
    source = args.candidate_sql[0]
    target = fixture.candidate_directory / source.name
    shutil.copyfile(source, target)
    args.candidate_sql = [target]
    shutil.copytree(
        native.ROOT / "hop/graph",
        fixture.candidate_directory / "graph",
        ignore=shutil.ignore_patterns("tests", "tools", "__pycache__"),
    )
    fixture.receipt = dict(
        status="RUNNING",
        kind="ARCHIVED_COMPLETE_NATIVE_SOURCE_REPLAY",
        isolated=True,
        network_internal=True,
        no_source_requests=True,
        no_paid_calls=True,
        production_writes=False,
        checks=[],
        run_id=args.run_id,
        backup_sha256=args.backup_sha256,
        restore_seconds=prior["restore_seconds"],
        prior_profile=str(args.prior_profile),
        prior_profile_sha256=native.sha(args.prior_profile),
        samples=[],
        selection_samples=[],
        order=["baseline", "candidate"],
        candidate_artifact_sha256={
            "graph/" + str(p.relative_to(fixture.candidate_directory / "graph")): native.sha(p)
            for p in (fixture.candidate_directory / "graph").rglob("*")
            if p.is_file() and p.suffix in (".sql", ".hpl", ".hwf")
        },
        limits=[
            "One warm matched native AB pair; one sample per variant.",
            "Capture is SQL plus Hop time; writer/verifier includes SQL plus Neo4j.",
            "Prior first-backend and superseded candidate diagnostics remain separate.",
            "No host cold cache or historical initial-read root cause claim.",
        ],
    )
    directory = reads.STATE / ("replay-reads-corrected-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    path = directory / "receipt.json"
    receipt: dict[str, Any] = dict(
        status="RUNNING",
        created_at=datetime.now(UTC).isoformat(),
        samples=[],
        prior_profile=str(args.prior_profile),
        prior_profile_sha256=native.sha(args.prior_profile),
        candidate_sql_sha256={"graph/sql/004_verified_proof_replay.sql": native.sha(target)},
        source_requests=0,
        paid_requests=0,
        production_writes=0,
        scopes=prior["scopes"],
        statement_timeout_seconds=args.profile_timeout_seconds,
        limits=[
            "Matched explicitly analyzed, already-read archived states; no first-read repeats.",
            "One AB SQL sample per scope; no transaction-shape or statistics-causality claim.",
        ],
    )
    session = None
    try:
        part = directory / "matched-replay"
        part.mkdir(mode=0o700)
        session = Session(fixture.pg, part, args.profile_timeout_seconds, database="reads_analyzed")
        original = (args.prior_profile.parent / "sql/original-begin.sql").read_text()
        session.execute(original)
        runs = safe_runs([s["run_id"] for s in prior["scopes"]])
        before, proofs = reads.preserved(session, runs), reads.proof_state(session, runs)
        if before != prior["analyzed_input"] or proofs != prior["analyzed_proofs"]:
            raise RuntimeError("Interrupted template source/proof drift")
        receipt.update(
            input=before, proofs=proofs, statistic_identity=reads.statistic_identity(session)
        )
        for variant in ("baseline", "candidate"):
            session.execute(original if variant == "baseline" else target.read_text())
            for scope in prior["scopes"]:
                sample = dict(
                    statistics="analyzed",
                    operation="begin_rollback",
                    variant=variant,
                    run_id=scope["run_id"],
                    result="RUNNING",
                )
                receipt["samples"].append(sample)
                write_json(path, receipt)
                reads.direct_replay(session, scope["run_id"], sample)
                write_json(path, receipt)
        session.execute(target.read_text())
        small = next(s["run_id"] for s in prior["scopes"] if s["source_id"] == "alio_organization")
        receipt["replay_correctness_checks"] = reads.replay_oracle(session, small)
        receipt["replay_correctness_checks"] += reads.replay_install_and_lock_oracle(
            session, fixture.pg, directory, "reads_analyzed", small, target.read_text()
        )
        if reads.preserved(session, runs) != before or reads.proof_state(session, runs) != proofs:
            raise RuntimeError("Corrected replay/oracle changed preserved state")
        session.close()
        session = None
        write_json(path, receipt)
        capture_path = directory / "first-capture-four-scopes.json"
        try:
            reads.first_capture_clone(fixture.pg, directory, prior["scopes"])
        except RuntimeError:
            # Preserve the bounded sample; a timeout is not an evidence mismatch.
            # Every other correctness failure still aborts and cleans the fixture.
            failure = json.loads(capture_path.read_text())
            stderr = directory / "first-capture-four-scopes/session.stderr"
            if (
                failure.get("status") != "FAILED"
                or not stderr.exists()
                or "canceling statement due to statement timeout" not in stderr.read_text()
            ):
                raise
            receipt["first_capture_limit"] = "FAILED_BOUNDED_TIMEOUT_RETAINED"
        receipt["first_capture_receipt"] = str(capture_path)
        receipt["status"] = (
            "PASSED_BOUNDED_REPLAY_READS"
            if all(s["result"] == "PASSED" for s in receipt["samples"])
            else "PASSED_WITH_BOUNDED_TIMEOUTS"
        )
        if receipt.get("first_capture_limit"):
            receipt["status"] = "PARTIAL_CAPTURE_TIMED_OUT_REPLAY_ORACLE_PASSED"
        write_json(path, receipt)
        native.run(args, fixture=fixture, restored=True)
    except BaseException as error:
        receipt.update(status="FAILED", failure_type=type(error).__name__)
        fixture.receipt.update(status="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            session.close()
        for database in ("reads_restored", "reads_analyzed"):
            if fixture.receipt.get("disposable_resources_removed") is not True:
                docker(
                    [
                        "exec",
                        fixture.pg,
                        "psql",
                        "-X",
                        "-qAt",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-U",
                        "postgres",
                        "-d",
                        "postgres",
                        "-c",
                        "DROP DATABASE IF EXISTS " + database + " WITH (FORCE)",
                    ],
                    directory,
                    "drop-" + database,
                )
        if fixture.receipt.get("disposable_resources_removed") is not True:
            fixture.close()
            write_json(work / "receipt.json", fixture.receipt)
        receipt.update(
            cleanup_confirmed=fixture.receipt.get("disposable_resources_removed") is True
            and fixture.receipt.get("private_scratch_removed") is True
            and not fixture.receipt.get("cleanup_failures"),
            cleanup_evidence=str(work / "receipt.json"),
            cleanup_evidence_sha256=native.sha(work / "receipt.json"),
            finished_at=datetime.now(UTC).isoformat(),
        )
        write_json(path, receipt)
        # Append explicit cleanup evidence to the historical, interrupted receipt.
        prior.update(
            cleanup_confirmed=receipt["cleanup_confirmed"],
            cleanup_evidence=str(path),
            cleanup_evidence_sha256=native.sha(path),
        )
        write_json(args.prior_profile, prior)
        print(path, flush=True)
        print(work / "receipt.json", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-profile", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--backup-sha256", required=True)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--candidate-sql", required=True, type=Path, action="append")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile-timeout-seconds", type=int, default=60)
    parser.add_argument("--sql-timeout-seconds", type=int, default=180)
    parser.add_argument("--archived-inference-limit", type=int, default=10000)
    args = parser.parse_args()
    if (
        len(args.candidate_sql) != 1
        or args.candidate_sql[0].name != "004_verified_proof_replay.sql"
    ):
        parser.error("Exact corrected004 required")
    args.baseline_source_sharing = True
    args.pair_order = "ab"
    args.stable_statistics = True
    run(args)


if __name__ == "__main__":
    main()
