#!/usr/bin/env python3
"""Validate exact retained source proofs with bounded read-only snapshot workers.

Connect through the existing local Docker/psql operational path. This performs
one authoritative content assertion per run; it never captures or writes proof.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import queue
import re
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE = Path.home() / ".local/state/jobtology-hop"
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")
GATE = "hashtextextended('jobtology-retention-gate-v1',0)"
GATE_BODY = "SELECT pg_advisory_xact_lock(" + GATE + ");"


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_options(
    container: str,
    database: str,
    runs: list[str],
    workers: int,
    statement_seconds: int,
    lock_seconds: int,
    total_seconds: int,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise ValueError("Use one exact local container identity")
    if not IDENTITY.fullmatch(database):
        raise ValueError("Use one exact database identity")
    if not 1 <= len(runs) <= 16 or len(set(runs)) != len(runs):
        raise ValueError("Supply between one and sixteen unique exact run IDs")
    if any(
        not IDENTITY.fullmatch(run) or run in ("LATEST", "ALL_CHECKPOINTED", "ALL") for run in runs
    ):
        raise ValueError("Use exact bounded run IDs, never latest/all selectors")
    if workers not in (1, 2, 4):
        raise ValueError("Workers must be one, two or four")
    if not (
        1 <= statement_seconds <= 180
        and 1 <= lock_seconds <= 30
        and statement_seconds + 10 <= total_seconds <= 900
    ):
        raise ValueError("Invalid bounded statement, lock or total timeout")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


class SqlFailure(RuntimeError):
    def __init__(self, state: str):
        self.sqlstate = state
        super().__init__("Read-only validation SQL failed: " + state)


class Session:
    """One bounded psql backend; drain stdout independently of query execution."""

    def __init__(
        self,
        container: str,
        database: str,
        directory: Path,
        name: str,
        statement_seconds: int,
        lock_seconds: int,
        total_seconds: int,
        *,
        deadline: float | None = None,
    ):
        self.name = name
        self.timeout = statement_seconds + 5
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stderr_path = directory / (name + ".stderr")
        self.stderr = self.stderr_path.open("w")
        self.process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "PGAPPNAME=" + name,
                container,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                "VERBOSITY=sqlstate",
                "-U",
                "postgres",
                "-d",
                database,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.execute(
                "SET default_transaction_read_only=on; SET application_name="
                + quote(name)
                + "; SET statement_timeout="
                + quote(str(statement_seconds) + "s")
                + "; SET lock_timeout="
                + quote(str(lock_seconds) + "s")
                + "; SET idle_in_transaction_session_timeout="
                + quote(str(total_seconds + 10) + "s")
                + "; SET max_parallel_workers_per_gather=0; SET jit=off",
                deadline=deadline,
            )
        except BaseException:
            self.close()
            raise

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def execute(self, sql: str, *, deadline: float | None = None) -> str:
        marker = "validation_" + uuid.uuid4().hex
        assert self.process.stdin is not None
        self.process.stdin.write(
            sql.rstrip(";\n") + ";\n\\echo " + marker + "_state :SQLSTATE\n\\echo " + marker + "\n"
        )
        self.process.stdin.flush()
        end = time.monotonic() + self.timeout
        if deadline is not None:
            end = min(end, deadline)
        result: list[str] = []
        state = None
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Read-only validation client deadline exceeded")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("Read-only validation client deadline exceeded") from exc
            if line is None:
                states = re.findall(
                    r"(?:ERROR|FATAL):\s+([A-Z0-9]{5})", self.stderr_path.read_text()
                )
                raise SqlFailure(states[-1] if states else "TRANSPORT_CLOSED")
            if line.startswith(marker + "_state "):
                state = line.split()[1]
            elif line.strip() == marker:
                if state != "00000":
                    raise SqlFailure(state or "UNKNOWN")
                return "".join(result).strip()
            else:
                result.append(line)

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.write("\\q\n")
                self.process.stdin.flush()
                self.process.stdin.close()
                self.process.wait(timeout=3)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        if self.process.stdout is not None and not self.reader.is_alive():
            self.process.stdout.close()
        self.stderr.close()


def proof_query(runs: list[str]) -> str:
    return (
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
      'run_id',p.run_id,'source_id',p.source_id,'state',p.state,
      'loader_version',p.loader_version,'record_count',p.record_count,
      'reference_count',p.reference_count,'content_sha256',p.content_sha256)
      ORDER BY p.run_id),'[]') FROM ingestion.source_graph_projection p
      JOIN ingestion.run r ON r.run_id=p.run_id AND r.source_id=p.source_id
      WHERE p.state='READY' AND r.state='READY' AND r.mode<>'SMOKE'
      AND p.run_id IN ("""
        + ",".join(quote(run) for run in runs)
        + ")"
    )


def owned_backends_query(
    identities: list[dict[str, Any]], *, cancel: bool = False, terminate: bool = False
) -> str:
    if not identities:
        return "SELECT 0"
    predicates = []
    for identity in identities:
        predicates.append(
            "(pid="
            + str(int(identity["pid"]))
            + " AND backend_start="
            + quote(identity["backend_start"])
            + "::timestamptz AND application_name="
            + quote(identity["application_name"])
            + ")"
        )
    expression = (
        "pg_terminate_backend(pid)" if terminate else "pg_cancel_backend(pid)" if cancel else "pid"
    )
    return "SELECT " + expression + " FROM pg_stat_activity WHERE " + " OR ".join(predicates)


def owned_names_query(database: str, names: list[str], *, terminate: bool = False) -> str:
    """Fallback for a transport that fails before its identity query completes.

    Exact 128-bit operation-token names are supplied to libpq at connection start,
    not merely after BEGIN. Never inspect/cancel another operation's connections.
    """
    expression = "pg_terminate_backend(pid)" if terminate else "pid"
    return (
        "SELECT "
        + expression
        + " FROM pg_stat_activity WHERE datname="
        + quote(database)
        + " AND application_name IN ("
        + ",".join(quote(name) for name in names)
        + ")"
    )


def validate(
    container: str,
    runs: list[str],
    *,
    database: str = "jobtology",
    workers: int = 2,
    statement_seconds: int = 60,
    lock_seconds: int = 5,
    total_seconds: int = 300,
    directory: Path | None = None,
) -> dict[str, Any]:
    validate_options(
        container, database, runs, workers, statement_seconds, lock_seconds, total_seconds
    )
    token = uuid.uuid4().hex
    if directory is None:
        directory = STATE / ("source-proof-validation-" + token)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    directory.chmod(0o700)
    started = time.monotonic()
    deadline = started + total_seconds
    receipt: dict[str, Any] = {
        "status": "FAILED",
        "operation": "READ_ONLY_SOURCE_PROOF_VALIDATION",
        "started_at": datetime.now(UTC).isoformat(),
        "container": container,
        "database": database,
        "run_ids": runs,
        "requested_workers": workers,
        "actual_workers": min(workers, len(runs)),
        "statement_seconds": statement_seconds,
        "lock_seconds": lock_seconds,
        "total_seconds": total_seconds,
        "sql_parallel_workers_per_gather": 0,
        "coordinator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "jobs": [],
        "cleanup_errors": [],
        "receipt_directory": str(directory),
    }
    exporter: Session | None = None
    sessions: list[Session] = []
    identities: list[dict[str, Any]] = []
    coordinator_name = "jtv-" + token + "-coordinator"
    worker_names = ["jtv-" + token + "-" + str(index) for index in range(receipt["actual_workers"])]
    failed = threading.Event()
    try:
        exporter = Session(
            container,
            database,
            directory,
            coordinator_name,
            statement_seconds,
            lock_seconds,
            total_seconds,
            deadline=deadline,
        )
        # A session lock in autocommit precedes the first RR snapshot. Acquiring
        # retention.gate() inside RR can freeze a stale pre-lock-wait snapshot.
        exporter.execute("SELECT pg_advisory_lock(" + GATE + ")", deadline=deadline)
        exporter.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY", deadline=deadline)
        gate_ok = exporter.execute(
            "SELECT count(*) FROM pg_proc p JOIN pg_language l "
            "ON l.oid=p.prolang WHERE p.oid='retention.gate()'::regprocedure "
            "AND l.lanname='sql' AND NOT p.prosecdef AND p.provolatile='v' "
            "AND p.prorettype='void'::regtype AND p.proconfig IS NULL "
            "AND btrim(p.prosrc,E' \\n\\r\\t')=" + quote(GATE_BODY),
            deadline=deadline,
        )
        if gate_ok != "1":
            raise RuntimeError("Canonical retention gate contract changed")
        maintenance = exporter.execute(
            "SELECT EXISTS(SELECT 1 FROM retention.plan "
            "WHERE state='ACTIVE') OR EXISTS(SELECT 1 FROM retention.writer)",
            deadline=deadline,
        )
        if maintenance != "f":
            raise RuntimeError("Active retention or registered writer prevents validation")
        exporter.execute("SELECT ingestion.source_graph_assert_query_contract()", deadline=deadline)
        proofs = json.loads(exporter.execute(proof_query(runs), deadline=deadline))
        if {row["run_id"] for row in proofs} != set(runs):
            raise RuntimeError("Every run requires retained READY non-SMOKE source and READY proof")
        receipt["proofs"] = proofs
        receipt["assertion_definition_sha256"] = exporter.execute(
            "SELECT encode(sha256(convert_to(pg_get_functiondef("
            "'ingestion.assert_source_graph_content(text)'::regprocedure),'UTF8')),'hex')",
            deadline=deadline,
        )
        snapshot = exporter.execute("SELECT pg_export_snapshot()", deadline=deadline)
        if not re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+", snapshot):
            raise RuntimeError("Invalid exported snapshot identity")
        receipt["snapshot"] = snapshot
        receipt["transaction_snapshot"] = exporter.execute(
            "SELECT pg_current_snapshot()::text", deadline=deadline
        )
        for index in range(receipt["actual_workers"]):
            session = Session(
                container,
                database,
                directory,
                worker_names[index],
                statement_seconds,
                lock_seconds,
                total_seconds,
                deadline=deadline,
            )
            sessions.append(session)
            identity = json.loads(
                session.execute(
                    "SELECT jsonb_build_object('pid',pid,"
                    "'backend_start',backend_start,'application_name',application_name) "
                    "FROM pg_stat_activity WHERE pid=pg_backend_pid()",
                    deadline=deadline,
                )
            )
            identities.append(identity)
            session.execute(
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; "
                "SET TRANSACTION SNAPSHOT " + quote(snapshot),
                deadline=deadline,
            )
            actual = session.execute(
                "SELECT current_setting('transaction_read_only')||':'||"
                "current_setting('transaction_isolation')||':'||"
                "pg_current_snapshot()::text",
                deadline=deadline,
            )
            if actual != "on:repeatable read:" + receipt["transaction_snapshot"]:
                raise RuntimeError("Worker transaction or snapshot contract mismatch")
        receipt["worker_identities"] = identities

        jobs_lock = threading.Lock()

        def run_partition(index: int) -> None:
            for run in runs[index :: len(sessions)]:
                if failed.is_set():
                    with jobs_lock:
                        receipt["jobs"].append({"run_id": run, "status": "SKIPPED"})
                    continue
                at = time.monotonic()
                job: dict[str, Any] = {"run_id": run, "status": "FAILED"}
                try:
                    sessions[index].execute(
                        "SELECT ingestion.assert_source_graph_content(" + quote(run) + ")",
                        deadline=deadline,
                    )
                    job["status"] = "PASSED"
                except BaseException as exc:
                    job["status"] = "CANCELLED" if failed.is_set() else "FAILED"
                    job["failure_type"] = type(exc).__name__
                    job["failure_sqlstate"] = getattr(exc, "sqlstate", None)
                    failed.set()
                    raise
                finally:
                    job["seconds"] = time.monotonic() - at
                    with jobs_lock:
                        receipt["jobs"].append(job)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sessions)) as pool:
            futures = [pool.submit(run_partition, index) for index in range(len(sessions))]
            error: BaseException | None = None
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except BaseException as exc:
                    failed.set()
                    if error is None:
                        error = exc
                        # PID alone is unsafe if a failed backend has exited.
                        exporter.execute(
                            owned_backends_query(identities, cancel=True),
                            deadline=time.monotonic() + 5,
                        )
            if error is not None:
                raise error
        if {job["run_id"] for job in receipt["jobs"]} != set(runs) or any(
            job["status"] != "PASSED" for job in receipt["jobs"]
        ):
            raise RuntimeError("Incomplete source proof validation")
        exporter.execute("SELECT 1", deadline=deadline)
        receipt["results"] = [
            {
                "run_id": run,
                "status": "PASSED",
                "proof": next(row for row in proofs if row["run_id"] == run),
            }
            for run in runs
        ]
        encoded = json.dumps(
            receipt["results"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        receipt["result_sha256"] = hashlib.sha256(encoded).hexdigest()
        receipt["status"] = "PASSED"
    except BaseException as exc:
        failed.set()
        receipt["failure_type"] = type(exc).__name__
        receipt["failure_sqlstate"] = getattr(exc, "sqlstate", None)
        # No arbitrary server error text enters the public receipt/stdout.
        if exporter is not None and identities:
            try:
                exporter.execute(
                    owned_backends_query(identities, cancel=True), deadline=time.monotonic() + 5
                )
            except BaseException:
                receipt["cleanup_errors"].append("CANCEL_FAILED")
    finally:
        for session in sessions:
            try:
                session.close()
            except BaseException:
                receipt["cleanup_errors"].append("WORKER_TRANSPORT_CLOSE_FAILED")
        if exporter is not None:
            try:
                cleanup_end = time.monotonic() + 10
                exporter.execute("SELECT pg_stat_clear_snapshot()", deadline=cleanup_end)
                remaining = exporter.execute(
                    owned_names_query(database, worker_names), deadline=cleanup_end
                )
                if remaining not in ("", "0"):
                    exporter.execute(
                        owned_names_query(database, worker_names, terminate=True),
                        deadline=cleanup_end,
                    )
                    while remaining not in ("", "0") and time.monotonic() < cleanup_end:
                        time.sleep(0.05)
                        exporter.execute("SELECT pg_stat_clear_snapshot()", deadline=cleanup_end)
                        remaining = exporter.execute(
                            owned_names_query(database, worker_names), deadline=cleanup_end
                        )
                    if remaining not in ("", "0"):
                        receipt["cleanup_errors"].append("OWNED_BACKEND_REMAINS")
                receipt["worker_backend_cleanup_verified"] = remaining in ("", "0")
            except BaseException:
                receipt["cleanup_errors"].append("BACKEND_CLEANUP_UNVERIFIED")
            try:
                exporter.close()  # releases snapshot and session retention lock last
            except BaseException:
                receipt["cleanup_errors"].append("EXPORTER_CLOSE_FAILED")
        # Verify server-side exporter absence after transport closure: that is
        # the evidence its snapshot and session advisory lock were released.
        control: Session | None = None
        try:
            cleanup_end = time.monotonic() + 10
            control = Session(
                container,
                database,
                directory,
                "jtv-" + token + "-cleanup",
                3,
                2,
                10,
                deadline=cleanup_end,
            )
            names = [*worker_names, coordinator_name]
            remaining = control.execute(owned_names_query(database, names), deadline=cleanup_end)
            if remaining not in ("", "0"):
                control.execute(
                    owned_names_query(database, names, terminate=True), deadline=cleanup_end
                )
                while remaining not in ("", "0") and time.monotonic() < cleanup_end:
                    time.sleep(0.05)
                    control.execute("SELECT pg_stat_clear_snapshot()", deadline=cleanup_end)
                    remaining = control.execute(
                        owned_names_query(database, names), deadline=cleanup_end
                    )
            receipt["all_operation_backend_cleanup_verified"] = remaining in ("", "0")
            if remaining not in ("", "0"):
                receipt["cleanup_errors"].append("OPERATION_BACKEND_REMAINS")
        except BaseException:
            receipt["cleanup_errors"].append("OPERATION_BACKEND_CLEANUP_UNVERIFIED")
        finally:
            if control is not None:
                try:
                    control.close()
                except BaseException:
                    receipt["cleanup_errors"].append("CLEANUP_TRANSPORT_CLOSE_FAILED")
        if receipt["cleanup_errors"]:
            receipt["status"] = "FAILED"
            receipt.pop("result_sha256", None)
        attempted = {job["run_id"] for job in receipt["jobs"]}
        receipt["jobs"].extend(
            {"run_id": run, "status": "SKIPPED"} for run in runs if run not in attempted
        )
        receipt["jobs"].sort(key=lambda job: runs.index(job["run_id"]))
        receipt["seconds"] = time.monotonic() - started
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(directory / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--database", default="jobtology")
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=2)
    parser.add_argument("--statement-seconds", type=int, default=60)
    parser.add_argument("--lock-seconds", type=int, default=5)
    parser.add_argument("--total-seconds", type=int, default=300)
    args = parser.parse_args()
    result = validate(
        args.container,
        args.run_id,
        database=args.database,
        workers=args.workers,
        statement_seconds=args.statement_seconds,
        lock_seconds=args.lock_seconds,
        total_seconds=args.total_seconds,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "receipt": result["receipt_directory"],
                "seconds": result["seconds"],
                "result_sha256": result.get("result_sha256"),
            }
        )
    )
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
