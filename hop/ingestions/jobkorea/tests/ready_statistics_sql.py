"""Paired source-only SQL006/008 admission and tamper oracle in an owned fixture.

Requires a receipt from seal_profile.py; creates and removes only uniquely named
databases inside that already owned network-none container. Private SQL output
and immutable input remain under its protected state directory.
"""

# Exact SQL fixtures keep the independently mutated guard checks auditable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import traceback
import uuid
from pathlib import Path

from seal_profile import ROOT, SQL_FILES, Session, docker, load, now, write_json


def run(path: Path) -> None:
    parent = load(path)
    directory = path.parent / ("ready-statistics-oracle-" + uuid.uuid4().hex[:12])
    directory.mkdir(mode=0o700)
    receipt = {
        "status": "RUNNING",
        "started_at": now(),
        "container": parent["container"],
        "databases": [],
        "source_requests": 0,
        "paid_requests": 0,
        "production_writes": 0,
        "candidate_sha256": hashlib.sha256(
            (ROOT / "hop/ingestions/jobkorea/sql/008_ready_statistics.sql").read_bytes()
        ).hexdigest(),
        "variants": {},
    }
    proof_path = directory / "receipt.json"
    write_json(proof_path, receipt)
    try:
        for variant in ("baseline", "candidate"):
            work = directory / variant
            work.mkdir(mode=0o700)
            database = "seal_oracle_" + uuid.uuid4().hex[:12]
            receipt["databases"].append({"name": database, "removed": False})
            docker(
                ["exec", parent["container"], "createdb", "-U", "postgres", database],
                work,
                "create",
            )
            with Path(parent["backup"]).open("rb") as source:
                docker(
                    [
                        "exec",
                        "-i",
                        parent["container"],
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
                    work,
                    "schema-restore",
                    source=source,
                    timeout=180,
                )
            index = 0

            def sql(statement: str, *, db: str = database, output: Path = work) -> str:
                nonlocal index
                index += 1
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        "-e",
                        "PGOPTIONS=-c statement_timeout=120000 -c lock_timeout=2000",
                        parent["container"],
                        "psql",
                        "-X",
                        "-qAt",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-U",
                        "postgres",
                        "-d",
                        db,
                    ],
                    input=statement.replace("seal_oracle_caller", "seal_caller_" + db[-12:]),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=135,
                )
                stem = output / ("statement-" + str(index).zfill(4))
                stem.with_suffix(".stdout").write_text(result.stdout)
                stem.with_suffix(".stderr").write_text(result.stderr)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                return result.stdout.strip()

            source_root = work / "source"
            sql_dir = source_root / "hop/ingestions/jobkorea/sql"
            sql_dir.mkdir(parents=True)
            for position, relative in enumerate(SQL_FILES):
                if relative.startswith("hop/graph/"):
                    continue
                frozen = path.parent / "sql" / (str(position) + "-" + Path(relative).name)
                assert (
                    hashlib.sha256(frozen.read_bytes()).hexdigest()
                    == parent["sql_sha256"][relative]
                )
                sql(frozen.read_text())
                if relative.startswith("hop/ingestions/jobkorea/sql/"):
                    shutil.copyfile(frozen, sql_dir / Path(relative).name)
            candidate = ROOT / "hop/ingestions/jobkorea/sql/008_ready_statistics.sql"
            if variant == "candidate":
                sql(candidate.read_text())
                shutil.copyfile(candidate, sql_dir / candidate.name)
            sql((ROOT / "hop/llm/sql/027_jobkorea_inputs.sql").read_text())
            assert (
                sql(
                    "SELECT to_regprocedure('ingestion.source_graph_validation_issue(text)') IS NULL"
                )
                == "t"
            )

            spec = importlib.util.spec_from_file_location(
                "ndjson_contract", Path(__file__).with_name("ndjson_sql.py")
            )
            assert spec and spec.loader
            contract = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(contract)
            contract.ROOT = source_root
            contract.sql = sql
            contract.checks()
            fingerprints = json.loads(
                sql("""SELECT jsonb_build_object(
             'record', (SELECT md5(coalesce(jsonb_agg(to_jsonb(r)-'record_id' ORDER BY run_id,document_id,locator),'[]')::text) FROM ingestion.record r),
             'rejected', (SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY run_id,document_id,locator),'[]')::text) FROM ingestion.rejected_row r),
             'issue', (SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY run_id,locator,code,field),'[]')::text) FROM ingestion.jobkorea_issue r),
             'line', (SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY run_id,line_number),'[]')::text) FROM ingestion.jobkorea_ndjson_line r),
             'chunk', (SELECT md5(coalesce(jsonb_agg(to_jsonb(r)-'committed_at' ORDER BY run_id,chunk_no),'[]')::text) FROM ingestion.jobkorea_ndjson_chunk r))""")
            )
            if variant == "candidate":
                assert fingerprints == receipt["variants"]["baseline"]["semantic_fingerprints"]

            # Privileged corruption models damaged persisted evidence; normal
            # writes were already refused by the immutable-evidence contracts.
            body = contract.line(contract.row(770001))
            damaged, damaged_sha = contract.begin(body)
            contract.append(damaged, body)
            for table, assignment in (
                ("record", "source_payload=source_payload||'{\"tamper\":true}'::jsonb"),
                ("record", "normalized=normalized||'{\"tamper\":true}'::jsonb"),
                ("jobkorea_ndjson_line", "byte_offset=byte_offset+1"),
                ("jobkorea_ndjson_line", "row_sha256=repeat('0',64)"),
                ("jobkorea_ndjson_chunk", "raw_text=replace(raw_text,'Fixture','Changed')"),
                ("jobkorea_ndjson_chunk", "chain_sha256=repeat('0',64)"),
            ):
                contract.reject(
                    "BEGIN; ALTER TABLE ingestion." + table + " DISABLE TRIGGER USER; "
                    "UPDATE ingestion."
                    + table
                    + " SET "
                    + assignment
                    + " WHERE run_id="
                    + contract.quote(damaged)
                    + "; ALTER TABLE ingestion."
                    + table
                    + " ENABLE TRIGGER USER; DO $oracle$ BEGIN IF "
                    "ingestion.jobkorea_ndjson_row_manifest("
                    + contract.quote(damaged)
                    + ") IS NOT NULL THEN RAISE EXCEPTION 'ORACLE_CORRUPTION_WAS_MISSED'; "
                    "END IF; END $oracle$; SELECT * FROM ingestion.seal_jobkorea_ndjson_import("
                    + contract.quote(damaged)
                    + ","
                    + contract.quote(damaged_sha)
                    + ","
                    + str(len(body.encode()))
                    + "); COMMIT;",
                    "JOBKOREA_NDJSON_CHAIN_CONFLICT",
                )
                assert contract.receipt(damaged)["loaded"] is False

            # A competing transaction retains the same run/retention fences.
            lock_directory = work / "lock-probe"
            lock_directory.mkdir(mode=0o700)
            lock = Session(parent["container"], lock_directory, 10, database=database)
            try:
                lock.execute(
                    "BEGIN; SELECT pg_advisory_xact_lock(hashtextextended("
                    + contract.quote(damaged)
                    + ",0))"
                )
                contract.reject(
                    "SELECT * FROM ingestion.seal_jobkorea_ndjson_import("
                    + contract.quote(damaged)
                    + ","
                    + contract.quote(damaged_sha)
                    + ","
                    + str(len(body.encode()))
                    + ")",
                    "lock timeout",
                )
                lock.execute("COMMIT")
            finally:
                lock.close()
            assert contract.seal(damaged, damaged_sha, body) == dict(
                state="READY", record_count=1, issue_count=0
            )

            # The direct READY trigger must still see future local-file rules.
            hook = sql(
                "SELECT pg_get_functiondef('ingestion.local_file_validation_issue()'::regprocedure)"
            )
            body = contract.line(contract.row(750001))
            run_id, sha = contract.begin(body)
            contract.append(run_id, body)
            sql(
                "CREATE OR REPLACE FUNCTION ingestion.local_file_validation_issue() RETURNS TABLE(run_id text,issue text,location text) LANGUAGE sql STABLE AS $$ SELECT "
                + contract.quote(run_id)
                + "::text,'FUTURE_ADAPTER_RULE'::text,'fixture'::text $$"
            )
            refused = contract.seal(run_id, sha, body)
            assert refused["state"] == "REVIEW_REQUIRED" and refused["issue_count"] > 0
            contract.reject(
                "SET jobtology.already_validated='true'; UPDATE ingestion.run SET state='READY' WHERE run_id="
                + contract.quote(run_id),
                "JOBKOREA_READY_VALIDATION_FAILED",
            )
            sql(hook)

            if variant == "candidate":
                # Compatible replay and canonical006 reinstall both succeed;
                # unexpected body/security/configuration changes fail closed.
                sql(candidate.read_text())
                canonical = (sql_dir / "006_ndjson.sql").read_text()
                for mutation in (
                    "ALTER FUNCTION ingestion.seal_jobkorea_ndjson_import(text,text,bigint) SECURITY DEFINER",
                    "ALTER FUNCTION ingestion.seal_jobkorea_ndjson_import(text,text,bigint) SET jit=off",
                    sql(
                        "SELECT pg_get_functiondef('ingestion.seal_jobkorea_ndjson_import(text,text,bigint)'::regprocedure)"
                    ).replace("DECLARE meta", "-- oracle drift\nDECLARE meta"),
                ):
                    sql(mutation)
                    contract.reject(candidate.read_text(), "JOBKOREA_SEAL_CANONICAL_DRIFT")
                    sql(canonical)
                    sql(candidate.read_text())

                # READY replay bypasses ANALYZE even after counters are reset.
                ready = sql(
                    "SELECT u.run_id FROM ingestion.run u JOIN ingestion.jobkorea_import i USING(run_id) WHERE u.source_id='jobkorea' AND u.state='READY' AND i.file_format='NDJSON' ORDER BY u.run_id LIMIT 1"
                )
                meta = json.loads(
                    sql(
                        "SELECT to_jsonb(i) FROM ingestion.jobkorea_import i WHERE run_id="
                        + contract.quote(ready)
                    )
                )
                before = sql(
                    "SELECT analyze_count FROM pg_stat_all_tables WHERE relid='ingestion.record'::regclass"
                )
                sql(
                    "SELECT * FROM ingestion.seal_jobkorea_ndjson_import("
                    + contract.quote(ready)
                    + ","
                    + contract.quote(meta["file_sha256"])
                    + ","
                    + str(meta["byte_length"])
                    + ")"
                )
                assert before == sql(
                    "SELECT analyze_count FROM pg_stat_all_tables WHERE relid='ingestion.record'::regclass"
                )

                # A caller without MAINTAIN keeps the previous admission behavior.
                receipt["databases"][-1]["role"] = "seal_caller_" + database[-12:]
                sql(
                    "CREATE ROLE seal_oracle_caller; GRANT USAGE ON SCHEMA ingestion,retention,enrichment,cs,ontology TO seal_oracle_caller; GRANT SELECT ON ALL TABLES IN SCHEMA cs,ontology TO seal_oracle_caller; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA ingestion,retention,enrichment TO seal_oracle_caller; GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA ingestion,retention,enrichment TO seal_oracle_caller"
                )
                assert (
                    sql(
                        "SELECT has_table_privilege('seal_oracle_caller','ingestion.record','MAINTAIN')"
                    )
                    == "f"
                )
                payload = contract.line(contract.row(760001))
                unprivileged, unprivileged_sha = contract.begin(payload)
                contract.append(unprivileged, payload)
                result = json.loads(
                    sql(
                        "SET ROLE seal_oracle_caller; SELECT to_jsonb(x) FROM ingestion.seal_jobkorea_ndjson_import("
                        + contract.quote(unprivileged)
                        + ","
                        + contract.quote(unprivileged_sha)
                        + ","
                        + str(len(payload.encode()))
                        + ")x"
                    )
                )
                assert result == dict(state="READY", record_count=1, issue_count=0)
            summary = json.loads(
                sql(
                    "SELECT jsonb_build_object('record_count',(SELECT count(*) FROM ingestion.record),'rejected_count',(SELECT count(*) FROM ingestion.rejected_row),'source_only',to_regprocedure('ingestion.source_graph_validation_issue(text)') IS NULL,'writer_count',(SELECT count(*) FROM retention.writer),'request_count',(SELECT count(*) FROM ingestion.request_attempt WHERE source_id='jobkorea'))"
                )
            )
            assert (
                summary["source_only"] and summary["writer_count"] == summary["request_count"] == 0
            )
            receipt["variants"][variant] = {
                "status": "PASSED",
                "summary": summary,
                "semantic_fingerprints": fingerprints,
            }
            write_json(proof_path, receipt)
        receipt["status"] = "PASSED"
    except BaseException as error:
        receipt.update(status="FAILED", failure_type=type(error).__name__)
        (directory / "failure.txt").write_text(traceback.format_exc())
    finally:
        for entry in receipt["databases"]:
            docker(
                ["exec", parent["container"], "dropdb", "-U", "postgres", entry["name"]],
                directory,
                "drop-" + entry["name"],
                timeout=60,
            )
            entry["removed"] = True
            if entry.get("role"):
                docker(
                    [
                        "exec",
                        parent["container"],
                        "dropuser",
                        "-U",
                        "postgres",
                        "--if-exists",
                        entry["role"],
                    ],
                    directory,
                    "drop-" + entry["role"],
                    timeout=30,
                )
                entry["role_removed"] = True
        receipt.update(
            finished_at=now(), cleanup_verified=all(x["removed"] for x in receipt["databases"])
        )
        write_json(proof_path, receipt)
        print(
            json.dumps(
                {
                    "receipt": str(proof_path),
                    "status": receipt["status"],
                    "cleanup_verified": receipt["cleanup_verified"],
                }
            ),
            flush=True,
        )
    if receipt["status"] != "PASSED":
        raise SystemExit(1)


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    run(parser.parse_args().receipt.resolve(strict=True))
