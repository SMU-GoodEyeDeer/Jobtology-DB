"""Owned network-none PG fixture for exact local NDJSON seal diagnostics.

Setup restores only schema from a hash-bound approved archive, then appends the
supplied immutable NDJSON through its normal bounded SQL interface. Baseline and
candidate samples clone the same LOADING checkpoint. Output stays in protected
local state; no production connection, source retrieval or model call exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "hop/operations"))
from profile_archived_postgres import Session, docker, quote, statistics, write_json  # noqa: E402

STATE = Path.home() / ".local/state/jobtology-hop"
LABEL = "jobtology.jobkorea-seal-profile"
PREFIX = "jobtology-seal-profile-"
SQL_FILES = (
    "docs/hop-migration/checks.sql",
    "docs/hop-migration/operations.sql",
    *(
        "hop/ingestions/jobkorea/sql/" + name + ".sql"
        for name in (
            "001_schema",
            "002_operations",
            "003_checks",
            "004_integration",
            "005_shared_checks",
            "006_ndjson",
            "007_dataset_provenance",
        )
    ),
    "hop/graph/sql/001_posting_ingestion_dates.sql",
    "hop/graph/sql/002_batchfree_source_graph.sql",
    "hop/graph/sql/003_source_query_sharing.sql",
)


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def append_input(session: Session, receipt: dict[str, Any], path: Path) -> None:
    sample = Path(receipt["sample"])
    created = json.loads(
        session.execute(
            "SELECT to_jsonb(t) FROM ingestion.begin_jobkorea_ndjson_import("
            + quote(receipt["sample_sha256"])
            + ","
            + str(sample.stat().st_size)
            + ","
            + quote("jobkorea/" + receipt["sample_sha256"] + "/source.ndjson")
            + ", '2026-10-08T00:00:00Z'::timestamptz) t"
        )
    )
    receipt["run_id"] = run = created["run_id"]
    offset, physical = 0, 1
    batch: list[bytes] = []
    receipt["append_samples"] = []

    def append() -> None:
        nonlocal offset, physical
        raw = b"".join(batch)
        tick = time.monotonic()
        result = json.loads(
            session.execute(
                "SELECT to_jsonb(t) FROM ingestion.append_jobkorea_ndjson_batch("
                + quote(run)
                + ","
                + str(offset)
                + ","
                + str(physical)
                + ","
                + quote(raw.decode("utf-8"))
                + ","
                + quote(hashlib.sha256(raw).hexdigest())
                + ")t"
            )
        )
        receipt["append_samples"].append(
            {
                "lines": len(batch),
                "bytes": len(raw),
                "wall_seconds": time.monotonic() - tick,
                "result": result,
            }
        )
        offset, physical = result["next_byte_offset"], result["next_line_number"]
        batch.clear()
        write_json(path, receipt)

    with sample.open("rb") as source:
        for raw in source:
            if not raw.endswith(b"\n"):
                raise ValueError("Complete input requires terminal LF")
            batch.append(raw)
            if len(batch) == 500:
                append()
    if batch:
        append()
    receipt["checkpoint"] = json.loads(
        session.execute(
            "SELECT jsonb_build_object('run',to_jsonb(u),'import',to_jsonb(i),"
            "'records',(SELECT count(*) FROM ingestion.record WHERE run_id=u.run_id),"
            "'lines',(SELECT count(*) FROM ingestion.jobkorea_ndjson_line WHERE run_id=u.run_id)) "
            "FROM ingestion.run u JOIN ingestion.jobkorea_import i USING(run_id) WHERE u.run_id="
            + quote(run)
        )
    )


def metadata(container: str) -> dict[str, Any]:
    return json.loads(subprocess.check_output(["docker", "inspect", container], timeout=30))[0]


def evidence_fingerprints(session: Session, run: str) -> dict[str, Any]:
    result = {}
    for table, ordering, removed in (
        ("record", "document_id,locator", "-'record_id'"),
        ("rejected_row", "document_id,locator", ""),
        ("jobkorea_issue", "locator,code,field", ""),
        ("jobkorea_ndjson_line", "line_number", ""),
        ("jobkorea_ndjson_chunk", "chunk_no", "-'committed_at'"),
    ):
        result[table] = json.loads(
            session.execute(
                "SELECT jsonb_build_object('count',count(*),'md5',"
                "md5(coalesce(string_agg(md5((to_jsonb(t)"
                + removed
                + ")::text),'|' ORDER BY "
                + ordering
                + "),''))) FROM ingestion."
                + table
                + " t WHERE run_id="
                + quote(run)
            )
        )
    return result


def load(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    if STATE not in path.parents or not path.parent.name.startswith("seal-checkpoint-"):
        raise ValueError("Require a protected owned checkpoint receipt")
    receipt = json.loads(path.read_text())
    container = receipt["container"]
    if not container.startswith(PREFIX):
        raise ValueError("Require an owned seal container")
    meta = metadata(container)
    if (
        meta["Config"]["Labels"].get(LABEL) != receipt["token"]
        or meta["HostConfig"]["NetworkMode"] != "none"
    ):
        raise ValueError("Container ownership or network isolation differs")
    return receipt


def setup(args: argparse.Namespace) -> Path:
    backup, sample = args.backup.resolve(strict=True), args.sample.resolve(strict=True)
    if digest(backup) != args.backup_sha256 or digest(sample) != args.sample_sha256:
        raise ValueError("Approved immutable input hash differs")
    token = uuid.uuid4().hex[:16]
    directory = STATE / ("seal-checkpoint-" + token)
    directory.mkdir(mode=0o700)
    path = directory / "receipt.json"
    container = PREFIX + token
    receipt: dict[str, Any] = {
        "status": "SETTING_UP",
        "created_at": now(),
        "container": container,
        "token": token,
        "backup": str(backup),
        "backup_sha256": args.backup_sha256,
        "sample": str(sample),
        "sample_sha256": args.sample_sha256,
        "sample_bytes": sample.stat().st_size,
        "source_requests": 0,
        "paid_requests": 0,
        "production_writes": 0,
        "samples": [],
        "sql_sha256": {},
        "limits": [
            "Schema-only archive restore; one exact fresh source import.",
            "Template-cloned checkpoint rows, not host-cold disk reads.",
            "Clone-only autovacuum disabled to isolate explicit statistics phases.",
        ],
    }
    write_json(path, receipt)
    session = None
    try:
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
                LABEL + "=" + token,
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
        meta = metadata(container)
        receipt.update(
            image_id=meta["Image"],
            owned_volumes=[m["Name"] for m in meta["Mounts"] if m["Type"] == "volume"],
            container_limits={
                key: meta["HostConfig"][key] for key in ("Memory", "NanoCpus", "NetworkMode")
            },
        )
        for _ in range(100):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Owned PostgreSQL did not become ready")
        tick = time.monotonic()
        with backup.open("rb") as source:
            docker(
                [
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "--schema-only",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-U",
                    "postgres",
                    "-d",
                    "jobtology",
                ],
                directory,
                "schema-restore",
                source=source,
                timeout=180,
            )
        receipt["schema_restore_seconds"] = time.monotonic() - tick
        session = Session(container, directory, 300)
        frozen = directory / "sql"
        frozen.mkdir(mode=0o700)
        for index, relative in enumerate(SQL_FILES):
            data = (ROOT / relative).read_bytes()
            target = frozen / (str(index) + "-" + Path(relative).name)
            target.write_bytes(data)
            receipt["sql_sha256"][relative] = hashlib.sha256(data).hexdigest()
            session.execute(data.decode())
        append_input(session, receipt, path)
        receipt["statistics"] = statistics(session)
        receipt.update(status="CHECKPOINT_READY", checkpoint_at=now())
    except BaseException as error:
        receipt.update(status="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            session.close()
        write_json(path, receipt)
        print(path, flush=True)
    return path


def sample(args: argparse.Namespace) -> Path:
    path = args.receipt.resolve(strict=True)
    receipt = load(path)
    directory = path.parent / args.label
    directory.mkdir(mode=0o700)
    database = "seal_" + uuid.uuid4().hex[:12]
    template = receipt.get("templates", {}).get(args.template, {}).get("database")
    if args.template == "baseline":
        template = "jobtology"
    if template is None:
        raise ValueError("Unknown owned checkpoint template")
    docker(
        ["exec", receipt["container"], "createdb", "-U", "postgres", "-T", template, database],
        directory,
        "clone",
        timeout=120,
    )
    session = None
    entry: dict[str, Any] = {
        "label": args.label,
        "database": database,
        "template": args.template,
        "started_at": now(),
        "instrumented": args.nested_plans,
        "result": "RUNNING",
    }
    receipt["samples"].append(entry)
    write_json(path, receipt)
    try:
        session = Session(receipt["container"], directory, args.timeout_seconds, database=database)
        if args.candidate:
            data = args.candidate.resolve(strict=True).read_bytes()
            entry["candidate_sha256"] = hashlib.sha256(data).hexdigest()
            session.execute(data.decode())
        if args.analyze or args.analyze_record:
            tick = time.monotonic()
            relations = (
                ("record",)
                if args.analyze_record
                else (
                    "run",
                    "jobkorea_import",
                    "partition",
                    "document",
                    "record",
                    "rejected_row",
                    "jobkorea_issue",
                    "jobkorea_ndjson_chunk",
                    "jobkorea_ndjson_line",
                )
            )
            entry["analyze_tables"] = list(relations)
            for table in relations:
                session.execute("ANALYZE ingestion." + table)
            entry["analyze_seconds"] = time.monotonic() - tick
        if args.nested_plans:
            session.execute(
                "LOAD 'auto_explain'; SET auto_explain.log_min_duration='50ms'; "
                "SET auto_explain.log_analyze=on; SET auto_explain.log_buffers=on; "
                "SET auto_explain.log_timing=off; SET auto_explain.log_format=json; "
                "SET auto_explain.log_nested_statements=on"
            )
        if args.verify:
            entry["evidence_before"] = evidence_fingerprints(session, receipt["run_id"])
        query = (
            "SELECT to_jsonb(t) FROM ingestion.seal_jobkorea_ndjson_import("
            + quote(receipt["run_id"])
            + ","
            + quote(receipt["sample_sha256"])
            + ","
            + str(receipt["sample_bytes"])
            + ")t"
        )
        tick = time.monotonic()
        try:
            entry["output"] = json.loads(session.execute(query, allow_timeout=True))
            entry["result"] = "PASSED"
        finally:
            entry["wall_seconds"] = time.monotonic() - tick
        entry["statistics_after"] = statistics(session)
        if args.verify:
            entry["evidence_after"] = evidence_fingerprints(session, receipt["run_id"])
            assert entry["evidence_before"] == entry["evidence_after"]
            entry["fresh_manifest_verified"] = (
                session.execute(
                    "SELECT i.row_manifest_sha256=ingestion.jobkorea_ndjson_row_manifest(i.run_id) "
                    "AND i.loaded AND u.state='READY' "
                    "FROM ingestion.jobkorea_import i JOIN ingestion.run u USING(run_id) "
                    "WHERE i.run_id="
                    + quote(receipt["run_id"])
                )
                == "t"
            )
            assert entry["fresh_manifest_verified"]
    except BaseException as error:
        entry.update(
            result="FAILED",
            failure_type=type(error).__name__,
            sqlstate=getattr(error, "sqlstate", None),
        )
        raise
    finally:
        if session is not None:
            session.close()
        docker(["logs", receipt["container"]], directory, "postgres-nested-plans", timeout=30)
        docker(
            ["exec", receipt["container"], "dropdb", "-U", "postgres", database],
            directory,
            "drop",
            timeout=60,
        )
        entry.update(finished_at=now(), database_removed=True)
        write_json(path, receipt)
        print(
            json.dumps(
                {
                    key: entry.get(key)
                    for key in (
                        "label",
                        "result",
                        "wall_seconds",
                        "output",
                        "sqlstate",
                        "analyze_seconds",
                    )
                }
            ),
            flush=True,
        )
    return path


def fresh(args: argparse.Namespace) -> None:
    path = args.receipt.resolve(strict=True)
    receipt = load(path)
    if args.template in receipt.get("templates", {}) or args.template == "baseline":
        raise ValueError("Require a new owned template label")
    directory = path.parent / ("fresh-" + args.template)
    directory.mkdir(mode=0o700)
    database = "seal_checkpoint_" + uuid.uuid4().hex[:12]
    entry = {key: receipt[key] for key in ("container", "sample", "sample_sha256")}
    entry.update(database=database, created_at=now(), status="SETTING_UP")
    entry_path = directory / "receipt.json"
    session = None
    docker(
        ["exec", receipt["container"], "createdb", "-U", "postgres", database], directory, "create"
    )
    try:
        with Path(receipt["backup"]).open("rb") as source:
            docker(
                [
                    "exec",
                    "-i",
                    receipt["container"],
                    "pg_restore",
                    "--schema-only",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-U",
                    "postgres",
                    "-d",
                    database,
                ],
                directory,
                "schema-restore",
                source=source,
                timeout=180,
            )
        session = Session(receipt["container"], directory, 300, database=database)
        for index, relative in enumerate(SQL_FILES):
            frozen = path.parent / "sql" / (str(index) + "-" + Path(relative).name)
            if digest(frozen) != receipt["sql_sha256"][relative]:
                raise ValueError("Frozen baseline SQL drifted")
            session.execute(frozen.read_text())
        entry["candidate_sha256"] = digest(args.candidate)
        session.execute(args.candidate.read_text())
        append_input(session, entry, entry_path)
        entry.update(statistics=statistics(session), status="CHECKPOINT_READY", finished_at=now())
        receipt.setdefault("templates", {})[args.template] = entry
        write_json(path, receipt)
    except BaseException as error:
        entry.update(status="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        if session is not None:
            session.close()
        write_json(entry_path, entry)
        print(
            json.dumps(
                {
                    "template": args.template,
                    "status": entry["status"],
                    "append_seconds": sum(
                        x["wall_seconds"] for x in entry.get("append_samples", [])
                    ),
                }
            )
        )


def cleanup(path: Path) -> None:
    receipt = load(path)
    docker(["rm", "-fv", receipt["container"]], path.parent, "cleanup", timeout=60)
    remaining = []
    for kind, names in (
        ("container", [receipt["container"]]),
        ("volume", receipt["owned_volumes"]),
    ):
        for name in names:
            result = subprocess.run(
                ["docker", kind, "inspect", name],
                capture_output=True,
                check=False,
                timeout=30,
            )
            if result.returncode == 0:
                remaining.append({"kind": kind, "name": name})
    receipt.update(cleanup_verified=not remaining, cleanup_remaining=remaining, finished_at=now())
    write_json(path, receipt)
    if remaining:
        raise RuntimeError("Owned resources remain after cleanup; inspect the protected receipt")


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    start = commands.add_parser("setup")
    for name in ("backup", "sample"):
        start.add_argument("--" + name, type=Path, required=True)
        start.add_argument("--" + name + "-sha256", required=True)
    measure = commands.add_parser("sample")
    measure.add_argument("--receipt", type=Path, required=True)
    measure.add_argument("--label", required=True)
    measure.add_argument("--timeout-seconds", type=int, default=300)
    measure.add_argument("--candidate", type=Path)
    measure.add_argument("--template", default="baseline")
    measure.add_argument("--analyze", action="store_true")
    measure.add_argument("--analyze-record", action="store_true")
    measure.add_argument("--nested-plans", action="store_true")
    measure.add_argument("--verify", action="store_true")
    finish = commands.add_parser("cleanup")
    finish.add_argument("--receipt", type=Path, required=True)
    rebuild = commands.add_parser("fresh")
    rebuild.add_argument("--receipt", type=Path, required=True)
    rebuild.add_argument("--candidate", type=Path, required=True)
    rebuild.add_argument("--template", required=True)
    args = parser.parse_args()
    if args.mode == "setup":
        setup(args)
    elif args.mode == "sample":
        if not args.label.replace("-", "").isalnum() or not 1 <= args.timeout_seconds <= 600:
            raise ValueError("Require safe unique label and bounded statement timeout")
        sample(args)
    elif args.mode == "fresh":
        if not args.template.replace("-", "").isalnum():
            raise ValueError("Require safe new template label")
        fresh(args)
    else:
        cleanup(args.receipt.resolve(strict=True))


if __name__ == "__main__":
    main()
