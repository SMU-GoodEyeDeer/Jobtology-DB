#!/usr/bin/env python3
"""Native snapshot/retention/failure oracle in a tiny owned fixture database.

The synthetic assertion deliberately probes coordination semantics. It is not a
source-proof semantic oracle or a production throughput measurement. Real source
assertion equivalence is measured separately on the one shared archived clone.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_source_proofs as coordinator
from profile_archived_postgres import Session as WriterSession
from validate_source_proofs import STATE, validate, write_json

FIXTURE = """
CREATE SCHEMA ingestion; CREATE SCHEMA retention;
CREATE TABLE retention.plan(state text); CREATE TABLE retention.writer(writer_id text);
CREATE FUNCTION retention.gate() RETURNS void LANGUAGE sql AS $$
 SELECT pg_advisory_xact_lock(hashtextextended('jobtology-retention-gate-v1',0));
$$;
CREATE TABLE ingestion.run(run_id text PRIMARY KEY,source_id text,state text,mode text);
CREATE TABLE ingestion.source_graph_projection(run_id text PRIMARY KEY,source_id text,
 state text,loader_version text,record_count bigint,reference_count bigint,content_sha256 text);
CREATE TABLE snapshot_probe(generation integer); INSERT INTO snapshot_probe VALUES(0);
CREATE TABLE guarded_probe(generation integer); INSERT INTO guarded_probe VALUES(0);
CREATE FUNCTION guard_write() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN PERFORM retention.gate(); RETURN NULL; END $$;
CREATE TRIGGER retention_guard BEFORE UPDATE ON guarded_probe
 FOR EACH STATEMENT EXECUTE FUNCTION guard_write();
CREATE TABLE assertion_config(run_id text,expected integer,delay double precision,
 fail boolean DEFAULT false,write_attempt boolean DEFAULT false);
INSERT INTO ingestion.run SELECT 'r'||i,'synthetic','READY','FULL' FROM generate_series(0,3)i;
INSERT INTO ingestion.source_graph_projection SELECT run_id,source_id,'READY','fixture',1,0,
 repeat('a',64) FROM ingestion.run;
INSERT INTO assertion_config SELECT run_id,0,.04,false,false FROM ingestion.run;
CREATE FUNCTION ingestion.source_graph_assert_query_contract() RETURNS void
 LANGUAGE sql AS $$SELECT NULL::void$$;
CREATE FUNCTION ingestion.assert_source_graph_content(id text) RETURNS void LANGUAGE plpgsql AS $$
 DECLARE config assertion_config;
 BEGIN
 SELECT * INTO STRICT config FROM assertion_config WHERE run_id=id;
 IF current_setting('transaction_read_only')<>'on'
  OR current_setting('transaction_isolation')<>'repeatable read'
  OR (SELECT generation FROM snapshot_probe)<>config.expected
 THEN RAISE EXCEPTION 'SNAPSHOT_OR_READONLY_CONTRACT_FAILED'; END IF;
 PERFORM pg_sleep(config.delay);
 IF (SELECT generation FROM snapshot_probe)<>config.expected
 THEN RAISE EXCEPTION 'SNAPSHOT_CHANGED_INSIDE_WORKER'; END IF;
 IF config.write_attempt THEN INSERT INTO snapshot_probe VALUES(999); END IF;
 IF config.fail THEN RAISE EXCEPTION 'SYNTHETIC_ASSERTION_FAILURE'; END IF;
 END $$;
"""


class Oracle:
    def __init__(self, container: str):
        self.container = container
        self.token = uuid.uuid4().hex
        self.database = "parallel_validation_oracle_" + self.token[:12]
        self.directory = STATE / ("parallel-validation-native-" + self.token)
        self.directory.mkdir(mode=0o700, parents=True)
        self.coordinator_bytes = Path(coordinator.__file__).read_bytes()
        self.native_bytes = Path(__file__).read_bytes()
        (self.directory / "coordinator-launched.py").write_bytes(self.coordinator_bytes)
        (self.directory / "native-launched.py").write_bytes(self.native_bytes)
        self.index = 0
        self.checks: list[str] = []

    def sql(self, sql: str, *, database: str | None = None) -> str:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self.container,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                database or self.database,
            ],
            input=sql,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            (self.directory / "native-failure.stderr").write_text(result.stderr)
            raise RuntimeError("Native fixture SQL failed; inspect protected evidence")
        return result.stdout.strip()

    def check(self, name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        self.checks.append(name)

    def validation(self, **options):
        self.index += 1
        return validate(
            self.container,
            ["r0", "r1", "r2", "r3"],
            database=self.database,
            directory=self.directory / ("validation-" + str(self.index)),
            statement_seconds=options.pop("statement_seconds", 10),
            lock_seconds=3,
            total_seconds=30,
            **options,
        )

    def wait_activity(self, event: str, count: int = 1) -> None:
        end = time.monotonic() + 10
        while time.monotonic() < end:
            number = int(
                self.sql(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname='"
                    + self.database
                    + "' AND application_name LIKE 'jtv-%' AND wait_event='"
                    + event
                    + "'"
                )
            )
            if number >= count:
                return
            time.sleep(0.04)
        raise AssertionError("Native expected backend activity absent: " + event)

    def run(self) -> dict:
        report = {
            "status": "FAILED",
            "checks": self.checks,
            "fixture": "SYNTHETIC_COORDINATION",
            "database": self.database,
            "container": self.container,
            "coordinator_sha256": hashlib.sha256(self.coordinator_bytes).hexdigest(),
            "native_sha256": hashlib.sha256(self.native_bytes).hexdigest(),
        }
        created = False
        try:
            network = subprocess.run(
                ["docker", "inspect", self.container, "--format", "{{.HostConfig.NetworkMode}}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            if network.strip() != "none" or not self.container.startswith("jobtology-"):
                raise ValueError("Native oracle requires the owned network-disabled clone")
            self.sql('CREATE DATABASE "' + self.database + '"', database="postgres")
            created = True
            self.sql(FIXTURE)
            values = [self.validation(workers=width) for width in (1, 2, 4)]
            self.check(
                "one-two-four-semantic-equivalence",
                all(v["status"] == "PASSED" for v in values)
                and len({v["result_sha256"] for v in values}) == 1,
            )
            report["fixture_samples"] = [
                {
                    "workers": v["actual_workers"],
                    "seconds": v["seconds"],
                    "result_sha256": v["result_sha256"],
                }
                for v in values
            ]
            self.sql("UPDATE assertion_config SET delay=.8")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(self.validation, workers=4)
                self.wait_activity("PgSleep", 4)
                self.sql("UPDATE snapshot_probe SET generation=1")
                result = future.result(timeout=15)
            self.check(
                "all-workers-same-snapshot-across-concurrent-change",
                result["status"] == "PASSED" and len(result["worker_identities"]) == 4,
            )
            self.sql("UPDATE snapshot_probe SET generation=0")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                validation = pool.submit(self.validation, workers=2)
                self.wait_activity("PgSleep", 2)
                writer = pool.submit(
                    self.sql,
                    "BEGIN; SELECT retention.gate(); "
                    "UPDATE guarded_probe SET generation=1; COMMIT;",
                )
                time.sleep(0.12)
                self.check(
                    "retention-writer-blocked-through-validation",
                    not writer.done() and self.sql("SELECT generation FROM guarded_probe") == "0",
                )
                self.check(
                    "retention-blocked-validation-passed",
                    validation.result(timeout=15)["status"] == "PASSED",
                )
                writer.result(timeout=10)
            self.check(
                "retention-writer-released-after-worker-cleanup",
                self.sql("SELECT generation FROM guarded_probe") == "1",
            )
            lock_dir = self.directory / "blocker"
            lock_dir.mkdir(mode=0o700)
            blocker = WriterSession(self.container, lock_dir, 10, database=self.database)
            try:
                blocker.execute("BEGIN; SELECT retention.gate()")
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self.validation, workers=2)
                    self.wait_activity("advisory")
                    blocker.execute(
                        "UPDATE snapshot_probe SET generation=2; "
                        "UPDATE assertion_config SET expected=2; COMMIT"
                    )
                    result = future.result(timeout=15)
                self.check(
                    "snapshot-created-after-retention-lock-wait", result["status"] == "PASSED"
                )
            finally:
                blocker.close()
            for label, setup, reset in (
                (
                    "active-retention-refused",
                    "INSERT INTO retention.plan VALUES('ACTIVE')",
                    "DELETE FROM retention.plan",
                ),
                (
                    "registered-writer-refused",
                    "INSERT INTO retention.writer VALUES('fixture-writer')",
                    "DELETE FROM retention.writer",
                ),
                (
                    "smoke-source-refused",
                    "UPDATE ingestion.run SET mode='SMOKE' WHERE run_id='r0'",
                    "UPDATE ingestion.run SET mode='FULL'",
                ),
                (
                    "incomplete-proof-refused",
                    "UPDATE ingestion.source_graph_projection SET state='LOADING' "
                    "WHERE run_id='r0'",
                    "UPDATE ingestion.source_graph_projection SET state='READY'",
                ),
                (
                    "archived-source-proof-refused",
                    "DELETE FROM ingestion.run WHERE run_id='r0'",
                    "INSERT INTO ingestion.run VALUES('r0','synthetic','READY','FULL')",
                ),
            ):
                self.sql(setup)
                result = self.validation(workers=2)
                self.check(label, result["status"] == "FAILED" and not result.get("result_sha256"))
                self.sql(reset)
            self.sql(
                "UPDATE assertion_config SET delay=CASE WHEN run_id='r0' THEN .05 ELSE 5 END, "
                "fail=(run_id='r0')"
            )
            result = self.validation(workers=2)
            self.check(
                "failure-cancels-peers-and-skips-queued-work",
                result["status"] == "FAILED"
                and result["seconds"] < 4
                and any(j["status"] == "SKIPPED" for j in result["jobs"])
                and result["worker_backend_cleanup_verified"]
                and not result["cleanup_errors"],
            )
            self.sql("UPDATE assertion_config SET delay=.01,fail=false,write_attempt=true")
            result = self.validation(workers=4)
            self.check(
                "worker-write-attempt-rejected-without-data-change",
                result["status"] == "FAILED"
                and self.sql("SELECT count(*) FROM snapshot_probe") == "1"
                and result["failure_sqlstate"] == "25006"
                and result["worker_backend_cleanup_verified"],
            )
            self.sql("UPDATE assertion_config SET write_attempt=false,delay=.01")
            self.sql("UPDATE assertion_config SET delay=2")
            result = self.validation(workers=2, statement_seconds=1)
            self.check(
                "server-statement-timeout-fails-closed",
                result["status"] == "FAILED"
                and result["failure_sqlstate"] == "57014"
                and result["worker_backend_cleanup_verified"],
            )
            self.sql("UPDATE assertion_config SET delay=.01")
            self.sql(
                "CREATE OR REPLACE FUNCTION retention.gate() RETURNS void LANGUAGE sql AS $$"
                " SELECT pg_advisory_xact_lock(hashtextextended('jobtology- retention-gate-v1',0));"
                " $$"
            )
            result = self.validation(workers=2)
            self.check(
                "changed-gate-key-with-interior-space-refused",
                result["status"] == "FAILED"
                and all(j["status"] == "SKIPPED" for j in result["jobs"]),
            )
            self.sql(
                "CREATE OR REPLACE FUNCTION retention.gate() RETURNS void LANGUAGE sql AS $$"
                "\n SELECT pg_advisory_xact_lock("
                "hashtextextended('jobtology-retention-gate-v1',0));"
                "\n$$"
            )
            real_execute = coordinator.Session.execute
            for label, prefix in (
                ("worker-bootstrap-failure-cleanup", "SET default_transaction_read_only=on"),
                ("worker-snapshot-import-failure-cleanup", "BEGIN ISOLATION LEVEL"),
            ):

                def injected_execute(session, sql, *, deadline=None, match_prefix=prefix):
                    if session.name.endswith("-0") and sql.startswith(match_prefix):
                        return real_execute(
                            session, "SELECT fixture_unknown_column", deadline=deadline
                        )
                    return real_execute(session, sql, deadline=deadline)

                coordinator.Session.execute = injected_execute
                try:
                    result = self.validation(workers=2)
                finally:
                    coordinator.Session.execute = real_execute
                self.check(
                    label,
                    result["status"] == "FAILED"
                    and result["all_operation_backend_cleanup_verified"],
                )

            def client_timeout_execute(session, sql, *, deadline=None):
                if session.name.endswith("-0") and sql.startswith("SET default_transaction"):
                    return real_execute(
                        session, "SELECT pg_sleep(20)", deadline=time.monotonic() + 0.05
                    )
                return real_execute(session, sql, deadline=deadline)

            coordinator.Session.execute = client_timeout_execute
            try:
                result = self.validation(workers=2)
            finally:
                coordinator.Session.execute = real_execute
            self.check(
                "bootstrap-client-timeout-cleans-unregistered-server-backend",
                result["status"] == "FAILED"
                and result["worker_backend_cleanup_verified"]
                and result["all_operation_backend_cleanup_verified"],
            )
            self.sql("UPDATE assertion_config SET delay=.8")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.validation, workers=4)
                self.wait_activity("PgSleep", 4)
                self.sql(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='"
                    + self.database
                    + "' AND application_name LIKE 'jtv-%-coordinator'"
                )
                result = future.result(timeout=15)
            self.check(
                "exporter-death-fails-closed-and-cleans-backends",
                result["status"] == "FAILED"
                and not result.get("result_sha256")
                and result["all_operation_backend_cleanup_verified"],
            )
            self.check(
                "all-owned-backends-absent",
                self.sql(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname='" + self.database + "' AND application_name LIKE 'jtv-%'"
                )
                == "0",
            )
            self.check(
                "executed-coordinator-and-native-bytes-unchanged",
                Path(coordinator.__file__).read_bytes() == self.coordinator_bytes
                and Path(__file__).read_bytes() == self.native_bytes,
            )
            report["status"] = "PASSED"
        except BaseException as exc:
            report["failure_type"] = type(exc).__name__
            raise
        finally:
            if created:
                self.sql('DROP DATABASE "' + self.database + '"', database="postgres")
                report["database_removed"] = True
            write_json(self.directory / "receipt.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    oracle = Oracle(args.container)
    result = oracle.run()
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks": len(result["checks"]),
                "receipt": str(oracle.directory / "receipt.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
