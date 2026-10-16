#!/usr/bin/env python3
"""Compare first exact source proof capture in identical disposable PG databases.

Restore one supplied old archive, install sealed SQL, ANALYZE once, then template
clone two untouched databases. Measure first backend validation before fingerprint
reads, then atomic and per-run captures on the same ordered real READY scopes.
No graph writes, production requests, source HTTP or nested instrumentation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from profile_archived_postgres import (
    STATE,
    Session,
    analyze_ingestion,
    docker,
    quote,
    safe_runs,
    statistics,
    write_json,
)

BASELINE = (
    "docs/hop-migration/checks.sql",
    "docs/hop-migration/operations.sql",
    "hop/graph/sql/001_posting_ingestion_dates.sql",
    "hop/graph/sql/002_batchfree_source_graph.sql",
)
PROOFS = ("source_graph_record_evidence", "source_graph_membership", "source_graph_projection")


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def proof_state(session: Session, runs: list[str]) -> dict[str, Any]:
    keys = ",".join(map(quote, runs))
    clauses: list[str] = []
    for table in PROOFS:
        row = "to_jsonb(t)"
        if table == "source_graph_projection":
            row += "-'started_at'-'verified_at'"
        clauses.append(
            "SELECT " + quote(table) + " name,count(*) n,encode(sha256(convert_to("
            "coalesce(string_agg(h,'' ORDER BY h),''),'UTF8')),'hex') sha256 FROM ("
            "SELECT encode(sha256(convert_to((" + row + ")::text,'UTF8')),'hex') h FROM "
            "ingestion." + table + " t WHERE run_id IN (" + keys + "))q"
        )
    return json.loads(
        session.execute(
            "SELECT jsonb_object_agg(name,to_jsonb(t)-'name') FROM ("
            + " UNION ALL ".join(clauses)
            + ")t"
        )
    )


def absent_proofs(session: Session, runs: list[str]) -> None:
    if any(row["n"] for row in proof_state(session, runs).values()):
        raise RuntimeError("First capture requires no selected proof or evidence rows")


def statistic_identity(session: Session) -> str:
    return session.execute(
        "SELECT encode(sha256(convert_to(coalesce(string_agg(to_jsonb(s)::text,'' "
        "ORDER BY to_jsonb(s)::text),''),'UTF8')),'hex') FROM pg_statistic s "
        "JOIN pg_class c ON c.oid=s.starelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='ingestion'"
    )


def preserved(session: Session, runs: list[str]) -> dict[str, Any]:
    keys = ",".join(map(quote, runs))
    tables = json.loads(
        session.execute(
            "SELECT jsonb_agg(format('%I.%I',n.nspname,c.relname) ORDER BY c.relname) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='enrichment' AND c.relkind='r'"
        )
    )
    clauses: list[str] = []
    for table in [
        "ingestion." + name for name in ("run", "document", "record", "graph_export")
    ] + tables:
        where = " WHERE run_id IN (" + keys + ")" if table.startswith("ingestion.") else ""
        clauses.append(
            "SELECT " + quote(table) + " name,count(*) n,"
            "md5(coalesce(string_agg(h,'' ORDER BY h),'')) fingerprint FROM "
            "(SELECT md5(to_jsonb(t)::text) h FROM " + table + " t" + where + ")q"
        )
    return json.loads(
        session.execute(
            "SELECT jsonb_object_agg(name,to_jsonb(t)-'name') FROM ("
            + " UNION ALL ".join(clauses)
            + ")t"
        )
    )


def capture(
    session: Session, runs: list[str], mode: str, result: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = {} if result is None else result
    result.update(mode=mode, operations=[], result="RUNNING")
    started = time.monotonic()
    if mode == "atomic":
        session.execute("BEGIN")
    # Per-run completes each run in its own transaction; atomic wraps all runs.
    for run in runs:
        if mode == "per-run":
            session.execute("BEGIN")
        for operation in ("begin", "finish"):
            tick = time.monotonic()
            sample: dict[str, Any] = {"run_id": run, "operation": operation, "result": "RUNNING"}
            result["operations"].append(sample)
            try:
                value = session.execute(
                    "SELECT ingestion." + operation + "_source_graph_projection(" + quote(run) + ")"
                )
                sample["result"] = "PASSED"
            except BaseException as error:
                sample.update(
                    result="FAILED",
                    failure_type=type(error).__name__,
                    sqlstate=getattr(error, "sqlstate", None),
                )
                raise
            finally:
                sample["wall_seconds"] = time.monotonic() - tick
            if value != "t":
                raise RuntimeError("Exact first capture operation returned false")
        if mode == "per-run":
            session.execute("COMMIT")
    if mode == "atomic":
        session.execute("COMMIT")
    result.update(wall_seconds=time.monotonic() - started, result="PASSED")
    return result


def run(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    backup = args.backup.resolve(strict=True)
    if digest(backup) != args.backup_sha256:
        raise ValueError("Supplied archive SHA256 differs")
    safe_runs([args.run_id])
    directory = STATE / ("first-capture-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    path = directory / "receipt.json"
    token = uuid.uuid4().hex[:16]
    container = "jobtology-first-capture-" + token
    receipt: dict[str, Any] = {
        "status": "RUNNING",
        "created_at": datetime.now(UTC).isoformat(),
        "container": container,
        "backup": str(backup),
        "backup_sha256": args.backup_sha256,
        "samples": [],
        "sql_sha256": {},
        "source_requests": 0,
        "paid_requests": 0,
        "production_writes": 0,
        "statement_timeout_seconds": args.timeout_seconds,
        "limits": [
            "Representative real scopes selected from this archive, not the historical86-run case.",
            "Distinct databases cloned from identical data and ANALYZE statistics.",
            "First backend validation reads follow restore/template creation; not host-cold.",
            "Atomic/per-run order is fixed and host caches can differ.",
            "Graph writes and verification are measured separately by routine benchmark.",
            "Projection timestamps excluded from equivalence; all evidence values retained.",
        ],
    }
    write_json(path, receipt)
    session = None
    created = False
    try:
        created = True
        docker(
            [
                "run",
                "--pull",
                "never",
                "-d",
                "--name",
                container,
                "--network",
                "none",
                "--label",
                "jobtology.first-capture=" + token,
                "--memory",
                "4g",
                "--cpus",
                "2",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=jobtology",
                "postgres:18-alpine",
                "-c",
                "autovacuum=off",
            ],
            directory,
            "boot",
        )
        metadata = json.loads(
            subprocess.check_output(["docker", "inspect", container], timeout=30)
        )[0]
        volumes = [m["Name"] for m in metadata["Mounts"] if m["Type"] == "volume"]
        receipt.update(
            image_id=metadata["Image"],
            owned_volumes=volumes,
            memory_bytes=metadata["HostConfig"]["Memory"],
        )
        for _ in range(60):
            check = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                capture_output=True,
                check=False,
                timeout=30,
            )
            if check.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Owned PostgreSQL failed to start")
        tick = time.monotonic()
        with backup.open("rb") as source:
            docker(
                [
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-U",
                    "postgres",
                    "-d",
                    "jobtology",
                ],
                directory,
                "restore",
                source=source,
                timeout=300,
            )
        receipt["restore_seconds"] = time.monotonic() - tick
        session = Session(container, directory, args.timeout_seconds)
        frozen = directory / "sql"
        frozen.mkdir(mode=0o700)
        manifest = json.loads((args.baseline_dir / "manifest.json").read_text())
        baseline = BASELINE + (("hop/graph/sql/003_source_query_sharing.sql",)
                               if getattr(args, "baseline_source_sharing", False) else ())
        for index, relative in enumerate(baseline):
            source = args.baseline_dir / relative
            if digest(source) != manifest[relative]:
                raise ValueError("Sealed baseline SQL changed")
            target = frozen / (str(index) + "-" + source.name)
            shutil.copyfile(source, target)
            receipt["sql_sha256"][relative] = digest(target)
            session.execute(target.read_text())
        target = frozen / args.candidate_sql.name
        shutil.copyfile(args.candidate_sql, target)
        receipt["sql_sha256"]["graph/sql/" + args.candidate_sql.name] = digest(target)
        session.execute(target.read_text())
        second = session.execute(
            "SELECT u.run_id FROM ingestion.run u WHERE source_id='alio_organization' "
            "AND state='READY' AND mode<>'SMOKE' AND u.run_id<>"
            + quote(args.run_id)
            + " AND EXISTS(SELECT 1 FROM ingestion.record r WHERE r.run_id=u.run_id)"
            + " ORDER BY (SELECT count(*) FROM ingestion.record r WHERE r.run_id=u.run_id),"
            "u.run_id LIMIT 1"
        )
        runs = [args.run_id, second]
        if getattr(args, "scope_count", 2) == 4:
            extra = json.loads(session.execute(
                "SELECT jsonb_agg(run_id ORDER BY source_id) FROM (SELECT DISTINCT ON(u.source_id) "
                "u.run_id,u.source_id,count(r.*) n FROM ingestion.run u JOIN ingestion.record r "
                "USING(run_id) WHERE u.state='READY' AND u.mode<>'SMOKE' "
                "AND u.source_id IN('nara_job','job_alio') GROUP BY u.run_id,u.source_id "
                "ORDER BY u.source_id,count(r.*) DESC,u.run_id)s"))
            if not isinstance(extra, list) or len(extra) != 2:
                raise RuntimeError("Four-scope comparison needs real Nara and JobAlio inputs")
            runs += extra
        runs = safe_runs(runs)
        receipt["run_ids"] = runs
        receipt["scope_counts"] = json.loads(
            session.execute(
                "SELECT jsonb_agg(jsonb_build_object('run_id',u.run_id,'source_id',u.source_id,"
                "'records',(SELECT count(*) FROM ingestion.record r WHERE r.run_id=u.run_id),"
                "'documents',(SELECT count(*) FROM ingestion.document d WHERE d.run_id=u.run_id)) "
                "ORDER BY u.run_id) FROM ingestion.run u WHERE run_id IN ("
                + ",".join(map(quote, runs))
                + ")"
            )
        )
        absent_proofs(session, runs)
        tick = time.monotonic()
        analyze_ingestion(session)
        receipt.update(
            analyze_seconds=time.monotonic() - tick,
            statistics=statistics(session),
            statistic_identity=statistic_identity(session),
        )
        # Close the template backend before CREATE DATABASE TEMPLATE.
        session.close()
        session = None
        docker(
            [
                "exec",
                container,
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
                "CREATE DATABASE capture_atomic TEMPLATE jobtology;",
            ],
            directory,
            "clone-atomic",
        )
        docker(
            [
                "exec",
                container,
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
                "CREATE DATABASE capture_per_run TEMPLATE jobtology;",
            ],
            directory,
            "clone-per-run",
        )
        first_before = first_after = None
        for mode, database in (("atomic", "capture_atomic"), ("per-run", "capture_per_run")):
            part = directory / mode
            part.mkdir(mode=0o700)
            session = Session(container, part, args.timeout_seconds, database=database)
            sample: dict[str, Any] = {"mode": mode, "first_reads": [], "result": "RUNNING"}
            receipt["samples"].append(sample)
            write_json(path, receipt)
            for run_id in runs:
                tick = time.monotonic()
                valid = session.execute(
                    "SELECT ingestion.source_graph_run_is_valid(" + quote(run_id) + ")"
                )
                sample["first_reads"].append(
                    {"run_id": run_id, "wall_seconds": time.monotonic() - tick, "valid": valid}
                )
                if valid != "t":
                    raise RuntimeError("Selected first-read scope failed READY validation")
            before = preserved(session, runs)
            sample["statistic_identity"] = statistic_identity(session)
            if sample["statistic_identity"] != receipt["statistic_identity"]:
                raise RuntimeError("Template ANALYZE statistics differ")
            absent_proofs(session, runs)
            if first_before is None:
                first_before = before
            elif before != first_before:
                raise RuntimeError("Template input fingerprints differ")
            capture(session, runs, mode, sample)
            after = proof_state(session, runs)
            if preserved(session, runs) != before:
                raise RuntimeError("Capture changed original source/frozen evidence")
            sample.update(before=before, after=after)
            if first_after is None:
                first_after = after
            elif after != first_after:
                raise RuntimeError("Atomic versus per-run captured evidence differs")
            session.close()
            session = None
            write_json(path, receipt)
        receipt["status"] = "PASSED_MATCHED_FIRST_CAPTURE"
    except BaseException as error:
        receipt.update(status="FAILED", failure_type=type(error).__name__)
        if receipt["samples"]:
            receipt["samples"][-1].update(result="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            session.close()
        if created:
            subprocess.run(
                ["docker", "rm", "-fv", container], capture_output=True, check=False, timeout=30
            )
            absent = (
                subprocess.run(
                    ["docker", "inspect", container], capture_output=True, check=False, timeout=30
                ).returncode
                != 0
            )
            volume_absent = all(
                subprocess.run(
                    ["docker", "volume", "inspect", v], capture_output=True, check=False, timeout=30
                ).returncode
                != 0
                for v in receipt.get("owned_volumes", [])
            )
            receipt["cleanup_confirmed"] = absent and volume_absent
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(path, receipt)
        print(path, flush=True)
    if not receipt.get("cleanup_confirmed"):
        raise RuntimeError("Owned capture container/volume cleanup incomplete")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--backup-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--candidate-sql", type=Path, required=True)
    parser.add_argument("--baseline-source-sharing", action="store_true")
    parser.add_argument("--scope-count", type=int, choices=(2, 4), default=2)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 3600:
        parser.error("Bound must be 1..3600 seconds")
    run(args)


if __name__ == "__main__":
    main()
