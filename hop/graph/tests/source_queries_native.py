"""SQL correctness oracle in a fresh database inside an owned network-none clone.

Copies schema only, creates supplied synthetic evidence locally, compares public
canonical queries with additive 003, and mutation-tests independently fresh calls.
Never connects to live PostgreSQL or retrieves source/model content. Private logs
and an aggregate receipt are retained; the owned temporary database is removed.
"""
# Exact fixture SQL and independent expectations are deliberately kept readable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def module(path: Path):
    spec = importlib.util.spec_from_file_location("source_query_fixture", path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Oracle:
    def __init__(self, container: str, directory: Path):
        self.container, self.directory = container, directory
        self.database = "source_query_oracle_" + uuid.uuid4().hex[:12]
        self.index = 0
        self.checks: list[str] = []

    def sql(
        self, statement: str, *, database: str | None = None, failure: str | None = None
    ) -> str:
        self.index += 1
        path = self.directory / f"statement-{self.index:04}"
        path.with_suffix(".sql").write_text(statement)
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
            input="SET statement_timeout='60s'; SET lock_timeout='5s';\n" + statement,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        path.with_suffix(".stdout").write_text(result.stdout)
        path.with_suffix(".stderr").write_text(result.stderr)
        if failure is not None:
            assert result.returncode and failure in result.stderr, path
            return result.stderr
        if result.returncode:
            raise RuntimeError("SQL oracle failed; inspect protected " + str(path))
        return result.stdout.strip()

    def check(self, label: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(label)
        self.checks.append(label)

    def install(self, candidate: bool) -> None:
        for name in ("001_posting_ingestion_dates.sql", "002_batchfree_source_graph.sql"):
            self.sql((ROOT / "hop/graph/sql" / name).read_text())
        if candidate:
            self.sql((ROOT / "hop/graph/sql/003_source_query_sharing.sql").read_text())
            self.sql((ROOT / "hop/graph/sql/004_verified_proof_replay.sql").read_text())
            self.sql((ROOT / "hop/graph/sql/005_validation_worksets.sql").read_text())
            self.sql((ROOT / "hop/graph/sql/006_jobalio_validation_worksets.sql").read_text())
            self.sql((ROOT / "hop/graph/sql/007_capture_guard_worksets.sql").read_text())
            self.sql((ROOT / "hop/graph/sql/008_reader_worksets.sql").read_text())

    def issues(self, run: str, scoped: bool) -> list[dict]:
        relation = (
            "ingestion.source_graph_validation_issue(" + quote(run) + ")"
            if scoped
            else "ingestion.validation_issue"
        )
        return json.loads(
            self.sql(
                "SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY issue,location),'[]') FROM "
                + relation
                + " v WHERE run_id="
                + quote(run)
            )
        )

    def snapshot(self, run: str) -> dict:
        result = {}
        for name, function in (
            ("entities", "graph_source_entities"),
            ("edges", "graph_source_edges"),
            ("owners", "graph_source_edge_owners"),
            ("manifest", "source_graph_manifest"),
        ):
            suffix = ",true" if name == "manifest" else ""
            result[name] = json.loads(
                self.sql(
                    "SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text),'[]') FROM ingestion."
                    + function
                    + "("
                    + quote(run)
                    + suffix
                    + ") v"
                )
            )
        return result

    def synthetic_ndjson(self) -> str:
        rows = [
            dict(
                product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(710001 + i),
                job_title="Local metadata fixture",
                company_name="Supplied fixture",
                job_position="Developer",
                required_education=None,
            )
            for i in range(2)
        ]
        body = (
            json.dumps(rows[0], ensure_ascii=False)
            + "\r\n"
            + json.dumps(rows[1], ensure_ascii=False)
            + "\n"
        )
        sha = hashlib.sha256(body.encode()).hexdigest()
        jobs = self.sql(
            "SELECT run_id FROM ingestion.begin_jobkorea_ndjson_import("
            + quote(sha)
            + ","
            + str(len(body.encode()))
            + ",'jobkorea/"
            + sha
            + "/source.ndjson',clock_timestamp())"
        )
        self.sql(
            "SELECT * FROM ingestion.append_jobkorea_ndjson_batch("
            + quote(jobs)
            + ",0,1,"
            + quote(body)
            + ","
            + quote(sha)
            + ")"
        )
        self.sql(
            "SELECT * FROM ingestion.seal_jobkorea_ndjson_import("
            + quote(jobs)
            + ","
            + quote(sha)
            + ","
            + str(len(body.encode()))
            + ")"
        )
        return jobs


CLONE = """
CREATE FUNCTION pg_temp.clone_source_run(original text, fresh text, at_time timestamptz) RETURNS void
LANGUAGE plpgsql AS $$ DECLARE tab text; columns text; projections text; BEGIN
 INSERT INTO ingestion.run(run_id,source_id,mode,parser_version,policy_revision,state,created_at,completed_at)
 SELECT fresh,source_id,mode,parser_version,policy_revision,state,at_time,at_time FROM ingestion.run WHERE run_id=original;
 FOREACH tab IN ARRAY ARRAY['partition','document','record','dependency'] LOOP
  SELECT string_agg(format('%I',attname),',' ORDER BY attnum),
   string_agg(format('changed.%I',attname),',' ORDER BY attnum) INTO columns,projections
  FROM pg_attribute WHERE attrelid=('ingestion.'||tab)::regclass AND attnum>0 AND NOT attisdropped
   AND attname<>'record_id' AND attgenerated='' AND attidentity='';
  EXECUTE format('INSERT INTO ingestion.%I(%s) SELECT %s FROM ingestion.%I prior
   CROSS JOIN LATERAL jsonb_populate_record(NULL::ingestion.%I,to_jsonb(prior)||jsonb_build_object(''run_id'',$1)) changed
   WHERE prior.run_id=$2',tab,columns,projections,tab,tab) USING fresh,original;
 END LOOP;
END $$;
SELECT pg_temp.clone_source_run('alio_organization','new-org','2026-10-03T00:00:00Z');
UPDATE ingestion.record SET source_record_id='org2',normalized=normalized||'{"code":"o2","name":"Employer two"}' WHERE run_id='new-org';
SELECT pg_temp.clone_source_run('job_alio','new-job','2026-10-04T00:00:00Z');
UPDATE ingestion.record SET normalized=normalized||'{"organization_code":"o2","title":null,"closing_date":null,"ongoing":false,"custom":["first",null,"last"]}' WHERE run_id='new-job';
SELECT pg_temp.clone_source_run('new-job','invalid-newest-job','2026-10-05T00:00:00Z');
UPDATE ingestion.record SET normalized=normalized||'{"organization_code":"invalid-target","title":"Invalid newest"}' WHERE run_id='invalid-newest-job';
UPDATE ingestion.document SET verified_at=NULL WHERE run_id='invalid-newest-job';
SELECT pg_temp.clone_source_run('ncs_qualification','new-qualification','2026-10-03T00:00:00Z');
UPDATE ingestion.record SET normalized=normalized||'{"qualification_code":"q2","qualification_name":"Authoritative Q2"}' WHERE run_id='new-qualification';
SELECT pg_temp.clone_source_run('qnet_schedule','new-session','2026-10-04T00:00:00Z');
UPDATE ingestion.record SET normalized=normalized||'{"qualification_code":"q2","qualification_name":"Referring Q2","name":"New session"}' WHERE run_id='new-session';
UPDATE ingestion.partition SET partition_id='year-2026-item-q2' WHERE run_id='new-session';
UPDATE ingestion.document SET partition_id='year-2026-item-q2' WHERE run_id='new-session';
"""


def run(container: str, directory: Path) -> Path:
    os.umask(0o077)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    inspected = json.loads(
        subprocess.run(
            ["docker", "inspect", container, "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    if inspected["HostConfig"]["NetworkMode"] != "none" or not container.startswith(
        "jobtology-routine-archive-"
    ):
        raise ValueError("Use only the coordinator-owned network-none archived clone")
    oracle = Oracle(container, directory)
    receipt = dict(
        status="RUNNING",
        container=container,
        database=oracle.database,
        production_writes=0,
        source_requests=0,
        paid_requests=0,
        checks=oracle.checks,
        created_at=datetime.now(UTC).isoformat(),
        artifact_sha256={
            relative: hashlib.sha256((ROOT / "hop" / relative).read_bytes()).hexdigest()
            for relative in (
                "graph/sql/001_posting_ingestion_dates.sql",
                "graph/sql/002_batchfree_source_graph.sql",
                "graph/sql/003_source_query_sharing.sql",
                "graph/sql/004_verified_proof_replay.sql",
                "graph/sql/005_validation_worksets.sql",
                "graph/sql/006_jobalio_validation_worksets.sql",
                "graph/sql/007_capture_guard_worksets.sql",
                "graph/sql/008_reader_worksets.sql",
                "graph/check_snapshot.hpl",
                "graph/install.hwf",
                "graph/tools/build_source_queries.py",
                "graph/tools/build_validation_worksets.py",
                "graph/tools/build_jobalio_validation_worksets.py",
                "graph/tools/build_capture_guard_worksets.py",
                "graph/tools/build_reader_worksets.py",
                "graph/tests/validation_worksets_adversity.py",
                "graph/tests/jobalio_validation_adversity.py",
                "graph/tests/capture_reader_adversity.py",
                "graph/tools/build_batchfree_graph.py",
            )
        },
    )
    created = False
    try:
        dump = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "pg_dump",
                "-s",
                "--no-owner",
                "--no-privileges",
                "-U",
                "postgres",
                "-d",
                "jobtology",
            ],
            capture_output=True,
            check=True,
        ).stdout
        (directory / "schema.sql").write_bytes(dump)
        oracle.sql('CREATE DATABASE "' + oracle.database + '"', database="postgres")
        created = True
        oracle.sql(dump.decode())
        # Empty operational state has no active fence/guard; fixture inserts stay
        # native and expose all immutable validation triggers as installed.
        oracle.install(False)
        fixture = module(ROOT / "hop/ingestions/jobkorea/tests/graph_compatibility.py")
        oracle.sql(fixture.FIXTURE)
        oracle.sql(
            "UPDATE ingestion.run SET created_at='2026-10-01T00:00:00Z',completed_at='2026-10-01T00:00:00Z';"
        )
        jk = oracle.synthetic_ndjson()
        oracle.sql(
            "SET session_replication_role=replica;" + CLONE + "SET session_replication_role=origin;"
        )
        runs = [
            "alio_organization",
            "job_alio",
            "nara_job",
            "ncs_competency",
            "ncs_career_path",
            "ncs_qualification",
            "qnet_schedule",
            jk,
        ]
        before = {run: oracle.snapshot(run) for run in runs}
        oracle.sql("SET session_replication_role=replica;INSERT INTO ingestion.graph_export(run_id,loader_version) SELECT run_id,'oracle-old-pins' FROM ingestion.run WHERE run_id IN(" + ",".join(quote(run) for run in runs) + ");SET session_replication_role=origin;")
        checkpointed_before = oracle.snapshot("ALL_CHECKPOINTED")
        missing_edges_before = oracle.sql("SELECT coalesce(jsonb_agg(to_jsonb(v)),'[]') FROM ingestion.graph_source_edges('absent-run') v")
        oracle.install(True)
        oracle.install(True)
        oracle.check("reader-old-pins-all-checkpointed-history", oracle.snapshot("ALL_CHECKPOINTED") == checkpointed_before)
        oracle.check("reader-absent-run-empty-edges", oracle.sql("SELECT coalesce(jsonb_agg(to_jsonb(v)),'[]') FROM ingestion.graph_source_edges('absent-run') v") == missing_edges_before == "[]")
        oracle.sql("SELECT * FROM ingestion.graph_source_entities('absent-run')", failure="SOURCE_GRAPH_REQUIRES_EXACT_READY_RUN")
        oracle.check("reader-absent-run-entities-refused", True)
        for run in runs:
            oracle.check("exact-typed-selection-" + run[:24], oracle.snapshot(run) == before[run])
            oracle.check(
                "exact-public-issues-" + run[:24],
                oracle.issues(run, True) == oracle.issues(run, False),
            )
        jobs = before["job_alio"]
        posting = next(
            row for row in jobs["entities"] if row["identity_id"] == "job-alio:posting:123"
        )
        facts = json.loads(posting["source_facts_json"])
        oracle.check(
            "whole-newest-facts-null-array-order",
            posting["source_run_id"] == "new-job"
            and facts["title"] is None
            and facts["closing_date"] is None
            and facts["custom"] == ["first", None, "last"],
        )
        oracle.check(
            "older-richer-name-current-facts",
            posting["entity_name"] == "Legacy" and posting["name_source_run_id"] == "job_alio",
        )
        oracle.check(
            "new-employer-endpoint-closure",
            any(row["to_id"] == "alio:organization:o2" for row in jobs["edges"])
            and any(
                row["identity_id"] == "alio:organization:o2"
                and row["entity_name"] == "Employer two"
                for row in jobs["entities"]
            ),
        )
        oracle.check(
            "invalid-newest-history-excluded",
            all(row["source_run_id"] != "invalid-newest-job" for row in jobs["entities"])
            and all(row["to_id"] != "alio:organization:invalid-target" for row in jobs["edges"]),
        )
        sessions = before["qnet_schedule"]
        oracle.check(
            "new-qualification-endpoint-authority",
            any(row["from_id"] == "qnet:qualification:q2" for row in sessions["edges"])
            and any(
                row["identity_id"] == "qnet:qualification:q2"
                and row["entity_name"] == "Authoritative Q2"
                for row in sessions["entities"]
            ),
        )
        # Exact-run issue equality before/negative/repair catches weakened gates.
        mutations = [
            (
                "normalization",
                'UPDATE ingestion.record SET normalized=normalized||\'{"title":"tamper"}\' WHERE run_id='
                + quote(jk),
            ),
            (
                "source-payload",
                'UPDATE ingestion.record SET source_payload=source_payload||\'{"extra":"tamper"}\' WHERE run_id='
                + quote(jk),
            ),
            (
                "document-hash",
                "UPDATE ingestion.document SET raw_sha256=repeat('b',64) WHERE run_id=" + quote(jk),
            ),
            (
                "physical-offset",
                "UPDATE ingestion.jobkorea_ndjson_line SET byte_offset=byte_offset+1 WHERE run_id="
                + quote(jk),
            ),
            (
                "chunk-checkpoint",
                "UPDATE ingestion.jobkorea_ndjson_chunk SET chain_sha256=repeat('b',64) WHERE run_id="
                + quote(jk),
            ),
            (
                "document-count",
                "UPDATE ingestion.document SET item_count=item_count+1 WHERE run_id='job_alio'",
            ),
            (
                "dependency-input",
                "UPDATE ingestion.dependency SET input_run_id='nara_job' WHERE run_id='job_alio'",
            ),
        ]
        for label, mutation in mutations:
            target = jk if label not in ("document-count", "dependency-input") else "job_alio"
            statement = "BEGIN; SET LOCAL session_replication_role=replica; " + mutation + "; "
            compare = (
                "SELECT (SELECT jsonb_agg(to_jsonb(v) ORDER BY issue,location) FROM ingestion.source_graph_validation_issue("
                + quote(target)
                + ") v) IS NOT DISTINCT FROM (SELECT jsonb_agg(to_jsonb(v) ORDER BY issue,location) FROM ingestion.validation_issue v WHERE run_id="
                + quote(target)
                + ");"
            )
            check = (
                "SELECT NOT ingestion.source_graph_run_is_valid(" + quote(target) + ");ROLLBACK;"
            )
            oracle.check(
                "tamper-oracle-and-refusal-" + label,
                oracle.sql(statement + compare + check).splitlines() == ["t", "t"],
            )
            oracle.check(
                "repaired-fresh-validation-" + label,
                oracle.sql("SELECT ingestion.source_graph_run_is_valid(" + quote(target) + ")")
                == "t",
            )
        for target in (jk, "job_alio"):
            oracle.sql(
                "SELECT ingestion.begin_source_graph_projection("
                + quote(target)
                + "); SELECT ingestion.finish_source_graph_projection("
                + quote(target)
                + ");"
            )
            oracle.sql("SELECT ingestion.assert_source_graph_projection(" + quote(target) + ");")
            oracle.check(
                "immutable-manifest-exact-" + target[:24],
                oracle.sql(
                    "SELECT to_jsonb(a)=to_jsonb(b) FROM ingestion.source_graph_manifest("
                    + quote(target)
                    + ",false) a CROSS JOIN ingestion.source_graph_manifest("
                    + quote(target)
                    + ",true) b"
                )
                == "t",
            )
            oracle.sql(
                "UPDATE ingestion.source_graph_record_evidence SET facts_sha256=repeat('b',64) WHERE run_id="
                + quote(target),
                failure="IMMUTABLE_SOURCE_GRAPH_EVIDENCE",
            )
            oracle.check("captured-proof-update-refused-" + target[:24], True)
        oracle.sql(
            "BEGIN; SET LOCAL session_replication_role=replica; UPDATE ingestion.record SET normalized=normalized||'{\"new_unproven_fact\":true}' WHERE run_id='job_alio'; SET LOCAL session_replication_role=origin; SELECT ingestion.assert_source_graph_projection('job_alio');",
            failure="SOURCE_GRAPH_LIVE_CONTENT_MISMATCH",
        )
        oracle.check("independent-live-content-tamper-refused", True)
        oracle.sql("SELECT ingestion.assert_source_graph_projection('job_alio');")
        oracle.sql(
            "BEGIN; SET LOCAL session_replication_role=replica; DELETE FROM ingestion.run WHERE run_id="
            + quote(jk)
            + ";SET LOCAL session_replication_role=origin; SELECT ingestion.assert_source_graph_projection("
            + quote(jk)
            + ");ROLLBACK;"
        )
        oracle.check("archived-proof-remains-valid-without-live-run", True)
        for name, source in (
            ("ingestion.graph_reference", "docs/hop-migration/schema.sql"),
            ("ingestion.ready_record", "docs/hop-migration/schema.sql"),
        ):
            source_text = (
                (ROOT / source)
                .read_text()
                .split("CREATE OR REPLACE VIEW " + name + " AS\n", 1)[1]
                .split(";", 1)[0]
            )
            drift = (
                source_text + " AND false"
                if name.endswith("ready_record")
                else source_text
                + " UNION ALL SELECT NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,NULL::text WHERE false"
            )
            oracle.sql(
                "BEGIN; CREATE OR REPLACE VIEW "
                + name
                + " AS "
                + drift
                + "; SELECT count(*) FROM ingestion.graph_source_entities('job_alio');",
                failure="SOURCE_GRAPH_QUERY_CONTRACT_CHANGED",
            )
            oracle.check("selection-definition-drift-refused-" + name, True)
        oracle.check(
            "selection-definition-repair-fresh", oracle.snapshot("job_alio") == before["job_alio"]
        )
        adversity = module(ROOT / "hop/graph/tests/validation_worksets_adversity.py")
        adversity.run(oracle)
        jobalio_adversity = module(ROOT / "hop/graph/tests/jobalio_validation_adversity.py")
        jobalio_adversity.run(oracle)
        capture_reader_adversity = module(ROOT / "hop/graph/tests/capture_reader_adversity.py")
        capture_reader_adversity.run(oracle)
        workset_sql = (ROOT / "hop/graph/sql/006_jobalio_validation_worksets.sql").read_text()
        for label, drift, failure in (
            ("missing-helper", "DROP FUNCTION ingestion.source_graph_scoped_validation_issue(text);",
             "does not exist"),
            ("parallel-safety", "ALTER FUNCTION ingestion.source_graph_scoped_validation_issue(text) PARALLEL SAFE;",
             "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT"),
            ("volatility", "ALTER FUNCTION ingestion.source_graph_scoped_validation_issue(text) VOLATILE;",
             "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT"),
            ("configuration", "ALTER FUNCTION ingestion.source_graph_scoped_validation_issue(text) SET search_path=ingestion;",
             "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT"),
            ("strictness", "ALTER FUNCTION ingestion.source_graph_scoped_validation_issue(text) STRICT;",
             "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT"),
            ("security-definer", "ALTER FUNCTION ingestion.source_graph_scoped_validation_issue(text) SECURITY DEFINER;",
             "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT"),
            ("leakproof", "ALTER FUNCTION ingestion.source_graph_scoped_validation_issue(text) LEAKPROOF;",
             "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT"),
        ):
            oracle.sql("BEGIN;" + drift + workset_sql, failure=failure)
            oracle.check("workset-baseline-drift-refused-" + label, True)
        generator = module(ROOT / "hop/graph/tools/build_jobalio_validation_worksets.py")
        renamed = generator.candidate(generator.SOURCE.read_text()).replace(
            "RETURNS TABLE(run_id text,issue text,location text)",
            "RETURNS TABLE(run_id text,issue text,renamed_location text)")
        oracle.sql("BEGIN;DROP FUNCTION ingestion.source_graph_scoped_validation_issue(text);"
                   + renamed + workset_sql,
                   failure="SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT")
        oracle.check("workset-return-signature-drift-refused", True)
        frozen_generator = module(ROOT / "hop/graph/tools/build_validation_worksets.py")
        oracle.sql("BEGIN;" + frozen_generator.definition(frozen_generator.SOURCE.read_text())
                   + workset_sql, failure="SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT")
        oracle.check("jobalio-workset-direct-sql003-refused", True)
        oracle.sql((ROOT / "hop/graph/sql/005_validation_worksets.sql").read_text(),
                   failure="SOURCE_GRAPH_VALIDATION_WORKSET_BASELINE_DRIFT")
        oracle.check("sealed-sql005-direct-downgrade-refused", True)
        # Every public hook/ruleset update gets fresh compatibility validation.
        oracle.sql(
            "CREATE OR REPLACE FUNCTION ingestion.local_file_validation_issue() RETURNS TABLE(run_id text,issue text,location text) LANGUAGE sql STABLE AS $$ SELECT 'job_alio'::text,'FUTURE_ADAPTER_RULE'::text,''::text $$;"
        )
        oracle.check(
            "unknown-local-hook-rule-fails-closed",
            oracle.sql("SELECT ingestion.source_graph_run_is_valid('job_alio')") != "t",
        )
        oracle.sql(
            "BEGIN; CREATE OR REPLACE VIEW ingestion.validation_issue AS SELECT run_id,'FUTURE_SHARED_RULE'::text issue,''::text location FROM ingestion.run;SELECT count(*) FROM ingestion.source_graph_validation_issue('job_alio');ROLLBACK;"
        )
        oracle.check(
            "shared-definition-change-fresh-oracle",
            oracle.sql(
                "BEGIN; CREATE OR REPLACE VIEW ingestion.validation_issue AS SELECT run_id,'FUTURE_SHARED_RULE'::text issue,''::text location FROM ingestion.run;SELECT issue FROM ingestion.source_graph_validation_issue('job_alio');ROLLBACK;"
            )
            == "FUTURE_SHARED_RULE",
        )
        receipt["status"] = "PASSED"
    except BaseException as exc:
        receipt["status"], receipt["failure_type"] = "FAILED", type(exc).__name__
        raise
    finally:
        if created:
            oracle.sql('DROP DATABASE "' + oracle.database + '" WITH (FORCE)', database="postgres")
            receipt["database_removed"] = True
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        path = directory / "receipt.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(path, flush=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"jobtology-routine-archive-(?:nara-)?[0-9a-f]+", args.container):
        parser.error("Use the exact coordinator-owned archived clone name")
    run(args.container, args.directory)
