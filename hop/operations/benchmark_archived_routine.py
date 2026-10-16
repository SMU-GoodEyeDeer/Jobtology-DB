#!/usr/bin/env python3
"""Benchmark complete native source graph replay from a supplied local PG dump.

Local images only; uniquely owned PG/Neo4j/Hop containers on an INTERNAL network.
Prime once, then run baseline/candidate and candidate/baseline warm replays. All
SQL readers, immutable proof capture, native writers/verifiers and final checkpoint
run normally. Timings describe this supplied archive, not production throughput
or fresh fetching/import. Protected receipts retain failed samples and typed graph
snapshots. No source URL, provider call, production DB or global setting is used.
"""

# pyright: basic
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hop.ingestions.jobkorea.tests.native import Fixture  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from prepare_performance_readback import transform_counters  # noqa: E402
from profile_archived_postgres import quote, safe_runs, write_json  # noqa: E402

SQL_BASELINE = (
    "docs/hop-migration/checks.sql",
    "docs/hop-migration/operations.sql",
    "hop/graph/sql/001_posting_ingestion_dates.sql",
    "hop/graph/sql/002_batchfree_source_graph.sql",
)
STAGES = {
    "check_snapshot": "validation",
    "begin_batch": "capture",
    "load_entity_names": "write",
    "load_references": "write",
    "load_posting_dates": "write",
    "clear_source_edges": "write",
    "verify_entity_names": "verification",
    "verify_references": "verification",
    "verify_posting_dates": "verification",
    "verify_totals": "verification",
    "finish_batch": "checkpoint",
}


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def cypher_plain_true(output: str) -> bool:
    """Accept cypher-shell's case-insensitive final Boolean value only."""
    lines = output.strip().splitlines()
    return bool(lines) and lines[-1].strip().lower() == "true"


def cypher_value(value):
    """Fixed-key fixture maps; string values remain safely quoted literals."""
    if isinstance(value, dict):
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", k) for k in value):
            raise ValueError("Unsafe Cypher map key")
        return "{" + ",".join(k + ":" + cypher_value(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(cypher_value(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def parse_workflow(log: str) -> dict[str, Any]:
    durations: dict[str, float] = {}
    for name, seconds in re.findall(
        r"\s([A-Za-z_][A-Za-z0-9_]*)\s*-\s*Pipeline duration\s*:\s*([0-9.]+) seconds", log
    ):
        if name in durations:
            raise ValueError("Ambiguous native pipeline duration: " + name)
        durations[name] = float(seconds)
    missing = set(STAGES) - durations.keys()
    if missing:
        raise ValueError("Missing complete routine stages: " + ",".join(sorted(missing)))
    errors = re.findall(r"Finished processing \([^)]*E\s*=\s*(\d+)[^)]*\)", log)
    if not errors or any(int(value) for value in errors):
        raise ValueError("Missing native counters or transform errors")
    groups: dict[str, float] = {}
    for pipeline, seconds in durations.items():
        group = STAGES.get(
            pipeline,
            {
                "record_graph_export": "checkpoint",
                "import_local": "local_ingestion_and_ready_validation",
            }.get(pipeline, "guards_constraints_other"),
        )
        groups[group] = groups.get(group, 0.0) + seconds
    # Identical transform names recur across workflow pipelines. Split the Basic
    # log on each pipeline's launch before using the strict single-summary parser.
    counters = {}
    for name, reader in (
        ("load_entity_names", "Read entity names"),
        ("verify_entity_names", "Read entity names"),
        ("load_references", "Read entity names"),
        ("verify_references", "Read entity names"),
        ("load_posting_dates", "Read posting dates"),
        ("verify_posting_dates", "Read posting dates"),
    ):
        finish = re.search(r"\s" + name + r"\s*-\s*Pipeline duration\s*:", log)
        assert finish is not None
        previous = log.rfind("Pipeline duration", 0, finish.start())
        section = log[previous if previous >= 0 else 0 : finish.start()]
        counters[name] = transform_counters(section, reader)
    return {
        "pipeline_seconds": durations,
        "stage_seconds": groups,
        "native_pipeline_seconds": sum(durations.values()),
        "reader_counters": counters,
    }


class RoutineFixture(Fixture):
    receipt: dict[str, Any]

    def __init__(self, args: argparse.Namespace):
        # The fixture staging API takes a local file; no import consumes it in
        # this archive-only benchmark. It is explicitly described in the receipt.
        super().__init__(args.backup)
        self.args = args
        self.original_definitions: list[str] = []
        self.function_names: list[str] = []
        self.variant_definitions: dict[str, Any] = {}
        frozen = self.work / "candidate"
        self.candidate_directory = frozen
        frozen.mkdir(mode=0o700)
        sql_files = []
        for index, source in enumerate(args.candidate_sql):
            target = frozen / (str(index) + "-" + source.name)
            shutil.copyfile(source, target)
            sql_files.append(target)
        args.candidate_sql = sql_files
        shutil.copytree(
            ROOT / "hop/graph",
            frozen / "graph",
            ignore=shutil.ignore_patterns("tests", "tools", "__pycache__"),
        )
        if not getattr(args, "fresh_phase", False):
            self.database = "jobtology"
        self.receipt["candidate_artifact_sha256"] = {
            "graph/" + str(p.relative_to(frozen / "graph")): sha(p)
            for p in (frozen / "graph").rglob("*")
            if p.is_file() and p.suffix in (".hpl", ".hwf", ".sql")
        }
        self.receipt.update(
            {
                "kind": "ARCHIVED_COMPLETE_NATIVE_SOURCE_REPLAY",
                "backup_sha256": args.backup_sha256,
                "run_id": args.run_id,
                "instrumentation": "Basic native logs; no auto_explain during measurements",
                "order": (["baseline", "candidate"] if getattr(args, "pair_order", "abba") == 'ab'
                          else ["baseline", "candidate", "candidate", "baseline"]),
                "samples": [],
                "selection_samples": [],
                "limits": [
                    "Warm matched replay following candidate priming and SQL count reads.",
                    "Capture stages measure SQL and Hop guards; graph write/verify stages "
                    "measure SQL and Neo4j work together.",
                    "Replay SQL uses matched explicitly refreshed statistics and warmed caches; "
                    "no statistics causality or first-read slowdown cause is established.",
                    "Independent selection timings cannot be subtracted from stages.",
                    "Restore/startup, instrumentation, initial graph load and fresh file "
                    "ingestion are excluded from replay throughput.",
                    "Ontology catalogue workflow is outside this source replay scope.",
                ],
            }
        )

    def command(self, args, label, input_text=None, success=True, timeout=120):
        if args[:2] == ["docker", "run"]:
            if getattr(self.args, "stable_statistics", False) and "postgres:18-alpine" in args:
                args = [*args, "-c", "autovacuum=off"]
            args = [
                *args[:2],
                "--memory",
                "4g",
                "--cpus",
                "2",
                "--label",
                "jobtology.routine-benchmark",
                *args[2:],
            ]
        if args[:2] == ["docker", "exec"] and "psql" in args:
            input_text = (
                "SET statement_timeout='"
                + str(self.args.sql_timeout_seconds)
                + "s';\n"
                + (input_text or "")
            )
            timeout = max(timeout, self.args.sql_timeout_seconds + 30)
        return super().command(args, label, input_text, success, timeout)

    def close(self):
        failures = []
        volumes = set()
        # The importer makes raw evidence root-owned and mode 0700. Remove only
        # fixture scratch while the owned Hop container can still access it.
        try:
            cleaned = subprocess.run(
                ["docker", "exec", "-u", "root", self.hop, "rm", "-rf", "--",
                 *("/fixture/" + name for name in ("inputs", "raw", "project", "config"))],
                capture_output=True, timeout=30,
            )
            if cleaned.returncode and any(
                (self.work / name).exists() for name in ("inputs", "raw", "project", "config")
            ):
                failures.append("scratch_container_cleanup")
        except subprocess.TimeoutExpired:
            failures.append("scratch_container_cleanup_timeout")
        for container in (self.hop, self.neo, self.pg):
            try:
                inspected = subprocess.run(
                    ["docker", "inspect", container], capture_output=True, text=True, timeout=20
                )
                if inspected.returncode == 0:
                    volumes.update(
                        m["Name"]
                        for m in json.loads(inspected.stdout)[0]["Mounts"]
                        if m["Type"] == "volume"
                    )
                removed = subprocess.run(
                    ["docker", "rm", "-fv", container], capture_output=True, timeout=30
                )
                if inspected.returncode == 0 and removed.returncode:
                    failures.append("container_removal:" + container)
            except (subprocess.TimeoutExpired, ValueError, KeyError) as error:
                failures.append(type(error).__name__ + ":" + container)
        try:
            subprocess.run(
                ["docker", "network", "rm", self.network], capture_output=True, timeout=30
            )
            targets = [["inspect", c] for c in (self.hop, self.neo, self.pg)]
            targets += [["network", "inspect", self.network]]
            targets += [["volume", "inspect", v] for v in sorted(volumes)]
            checks = [
                subprocess.run(["docker", *target], capture_output=True, timeout=20).returncode != 0
                for target in targets
            ]
            self.receipt["disposable_resources_removed"] = all(checks)
        except subprocess.TimeoutExpired as error:
            self.receipt["disposable_resources_removed"] = False
            failures.append(type(error).__name__ + ":cleanup_readback")
        for folder in ("inputs", "raw", "project", "config"):
            try:
                shutil.rmtree(self.work / folder)
            except FileNotFoundError:
                pass
            except OSError as error:
                failures.append(type(error).__name__ + ":scratch_" + folder)
        self.receipt["private_scratch_removed"] = all(
            not (self.work / folder).exists() for folder in ("inputs", "raw", "project", "config")
        )
        self.receipt["owned_anonymous_volumes"] = sorted(volumes)
        self.receipt["cleanup_failures"] = failures
        if failures or not self.receipt["disposable_resources_removed"]:
            self.receipt["status"] = "FAILED"
            self.receipt.setdefault("failure_type", "CleanupFailed")

    def stage(self):
        if getattr(self.args, "fresh_phase", False):
            self.input = self.args.local_ndjson
            Fixture.stage(self)
            shutil.copytree(
                self.work / "candidate/graph", self.work / "project/graph", dirs_exist_ok=True
            )
            self.capture_source_artifacts()
            return None
        dummy = self.work / "archive-only-placeholder.json"
        dummy.write_text("{}")
        archive = self.input
        self.input = dummy
        try:
            super().stage()
        finally:
            self.input = archive
            dummy.unlink()
        # A database dump is not a source file. Avoid copying 759MB to the Hop
        # mount just to satisfy the shared fixture's unused staging interface.
        (self.work / "inputs/sample.json").unlink()
        self.receipt.pop("input_sha256", None)
        self.receipt.pop("input_bytes", None)
        self.capture_source_artifacts()

    def capture_source_artifacts(self):
        project = self.work / "project"
        self.receipt["candidate_artifact_sha256"].update(
            {
                str(p.relative_to(project)): sha(p)
                for p in (project / "ingestions/jobkorea").rglob("*")
                if p.is_file() and p.suffix in (".hpl", ".hwf", ".sql")
            }
        )

    def definitions(self, label: str) -> list[dict[str, Any]]:
        names = ",".join(map(quote, self.function_names))
        return json.loads(
            self.sql(
                "SELECT coalesce(jsonb_agg(jsonb_build_object("
                "'signature',p.oid::regprocedure::text,'definition',pg_get_functiondef(p.oid)) "
                "ORDER BY p.oid::regprocedure::text),'[]'::jsonb) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname||'.'||p.proname "
                "IN (" + names + ")",
                label,
            )
        )

    def capture_originals(self):
        names = set()
        for path in self.args.candidate_sql:
            names.update(
                re.findall(
                    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+"
                    r"([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)\s*\(",
                    path.read_text(),
                    re.I,
                )
            )
        self.function_names = sorted(names)
        values = self.definitions("baseline-originals")
        self.original_definitions = [row["definition"] for row in values]
        self.variant_definitions["baseline"] = values
        write_json(self.work / "original-functions.json", values)

    def apply_variant(self, name: str):
        source = self.args.baseline_dir
        artifacts = (source / "hop/graph" if name == "baseline"
                     else self.candidate_directory / "graph")
        if name == "candidate":
            shutil.copytree(artifacts / "sql", self.work / "project/graph/sql", dirs_exist_ok=True)
        for artifact in artifacts.glob("*.h*"):
            if artifact.suffix in (".hpl", ".hwf"):
                shutil.copyfile(artifact, self.work / "project/graph" / artifact.name)
        sql_baseline = SQL_BASELINE + (
            ("hop/graph/sql/003_source_query_sharing.sql",)
            if getattr(self.args, "baseline_source_sharing", False) else ())
        for index, relative in enumerate(sql_baseline):
            self.sql((source / relative).read_text(), f"{name}-baseline-{index}")
        if self.original_definitions:
            self.sql(";\n".join(self.original_definitions), name + "-original-functions")
        if name == "candidate":
            for index, path in enumerate(self.args.candidate_sql):
                self.sql(path.read_text(), f"{name}-candidate-{index}")
        if self.function_names:
            definitions = self.definitions(name + "-bound-definitions")
            # Candidate adds helper symbols; compare existing baseline symbols only.
            if name == "baseline":
                originals = {row["signature"] for row in self.variant_definitions[name]}
                definitions = [row for row in definitions if row["signature"] in originals]
            if name in self.variant_definitions and self.variant_definitions[name] != definitions:
                raise RuntimeError("Variant function definitions differ from bound originals")
            self.variant_definitions[name] = definitions
            write_json(self.work / (name + "-functions.json"), definitions)

    def fingerprint(self, label: str) -> Any:
        # Capture normalized source, raw history, immutable source graph membership
        # and all frozen/candidate/accounting/link rows. graph_export's mutable
        # successful-export time is expected to change in routine replay.
        names = (
            "run",
            "document",
            "record",
            "source_graph_membership",
            "source_graph_record_evidence",
            "source_graph_projection",
            "graph_export",
            "jobkorea_import",
            "jobkorea_ndjson_chunk",
            "jobkorea_ndjson_line",
            "posting_ingestion_observation",
        )
        tables = json.loads(
            self.sql(
                "SELECT jsonb_agg(table_schema||'.'||table_name) "
                "FROM information_schema.tables WHERE table_type='BASE TABLE' AND "
                "((table_schema='ingestion' AND table_name IN ("
                + ",".join(map(quote, names))
                + ")) "
                "OR table_schema='enrichment')",
                label + "-tables",
            )
        )
        clauses = [
            "SELECT " + quote(table) + " AS name,count(*) AS n,"
            "md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS fingerprint FROM "
            "(SELECT md5((to_jsonb(t)"
            + (
                "-'started_at'-'verified_at'"
                if table == "ingestion.source_graph_projection"
                else "-'exported_at'"
                if table == "ingestion.graph_export"
                else ""
            )
            + ")::text) h FROM "
            + table
            + " t) rows"
            for table in tables
        ]
        return json.loads(
            self.sql(
                "SELECT jsonb_object_agg(name,to_jsonb(t)-'name') FROM ("
                + " UNION ALL ".join(clauses)
                + ")t",
                label,
            )
        )

    def graph_snapshot(self, label: str) -> dict[str, Any]:
        values = {}
        for kind, query in {
            "nodes": "MATCH(n) CALL(n){ UNWIND labels(n) AS l WITH l ORDER BY l "
            "RETURN collect(l) AS ls } "
            "CALL(n){ UNWIND keys(n) AS k WITH n,k ORDER BY k "
            "RETURN collect([k,valueType(n[k]),n[k]]) AS ps } "
            "RETURN n.id,ls,ps ORDER BY n.id",
            "edges": "MATCH(a)-[r]->(b) CALL(r){ UNWIND keys(r) AS k WITH r,k ORDER BY k "
            "RETURN collect([k,valueType(r[k]),r[k]]) AS ps } "
            "RETURN a.id,type(r),b.id,ps ORDER BY a.id,type(r),b.id,ps",
            "inferred_element_ids": "MATCH(a)-[r:INFERRED_NCS_OCCUPATION]->(b) "
            "RETURN r.candidate_id,elementId(a),elementId(r),elementId(b) ORDER BY r.candidate_id",
        }.items():
            self.command(
                ["docker", "exec", self.neo, "cypher-shell", "--format", "plain", query],
                label + "-" + kind,
                timeout=180,
            )
            path = self.logs / (label + "-" + kind + ".log")
            values[kind] = {"sha256": sha(path), "bytes": path.stat().st_size}
        scaffold = self.command(
            [
                "docker",
                "exec",
                self.neo,
                "cypher-shell",
                "--format",
                "plain",
                "MATCH(n) WHERE n:ingestionBatch OR n:ingestionRecord OR n:archivedRecord "
                "RETURN count(n)",
            ],
            label + "-scaffold",
        )
        if scaffold.splitlines()[-1] != "0":
            raise RuntimeError("Routine graph recreated ingestion scaffold")
        return values

    def seed_archived_inferences(self):
        limit = getattr(self.args, "archived_inference_limit", 0)
        if not limit:
            return
        pair = json.loads(self.sql(
            "SELECT to_jsonb(p) FROM (SELECT x.job_run_id jobs,x.ncs_run_id ncs,count(*) n FROM "
            "enrichment.metadata_occupation_binding x JOIN enrichment.metadata_occupation_result "
            "r USING(item_id) JOIN enrichment.metadata_occupation_candidate c USING(result_id) "
            "WHERE x.job_run_id=" + quote(self.args.run_id) + " GROUP BY x.job_run_id,x.ncs_run_id "
            "ORDER BY count(*) DESC,x.ncs_run_id LIMIT 1)p", "archived-inference-pair"))
        if not pair or not pair["n"]:
            raise RuntimeError("Real archived inference pair is required")
        token = self.sql("SELECT writer_token FROM enrichment.metadata_occupation_graph_guard "
                         "WHERE job_run_id=" + quote(pair["jobs"]) + " AND ncs_run_id="
                         + quote(pair["ncs"]) + " AND state='READY' ORDER BY completed_at DESC "
                         "LIMIT 1", "archived-inference-token")
        if not token:
            raise RuntimeError("Real archived verified publication token is required")
        rows = json.loads(self.sql(
            "SELECT jsonb_agg(to_jsonb(s) ORDER BY candidate_id) FROM (SELECT *,payload::text "
            "payload_json,enrichment.hash(payload::text) payload_hash FROM "
            "enrichment.metadata_occupation_graph_rows(" + quote(pair["jobs"]) + ","
            + quote(pair["ncs"]) + ",true) ORDER BY candidate_id LIMIT " + str(limit) + ")s",
            "archived-inference-rows"))
        if not rows:
            raise RuntimeError("Archived real graph output unexpectedly empty")
        property_names = ("review_status", "confidence_state", "accepted", "result_id",
                          "bundle_id", "source_hash", "binding_hash", "catalog_hash",
                          "occupation_scheme", "match_rank", "rank_basis", "original_primary",
                          "current_primary")
        typed = []
        for row in rows:
            payload = row["payload"]
            properties = {name: payload.get(name) for name in property_names}
            properties.update(
                candidate_id=row["candidate_id"], managed_by="jobtology-metadata-occupation",
                payload_json=row["payload_json"], payload_hash=row["payload_hash"],
                job_run_id=pair["jobs"], ncs_run_id=pair["ncs"], projection_token=token,
                basis="METADATA_INFERRED", assertion_kind="MODEL_INFERRED", serving_scope="STAGING",
                stage="STAGING", projection_state="VERIFIED", current=True, confidence=None)
            typed.append(dict(posting_identity=row["posting_identity"],
                              occupation_identity=row["occupation_identity"],
                              occupation_code=payload["occupation_code"],
                              occupation_name=payload["occupation_name"], properties=properties))
        for index in range(0, len(typed), 500):
            query = "UNWIND " + cypher_value(typed[index:index + 500]) + " AS row "
            query += "MATCH(p:entity:jobPosting {id:row.posting_identity,kind:'JobPosting'}) "
            query += "MERGE(o:entity:occupation {id:row.occupation_identity}) "
            query += "SET o.kind='Occupation',o.code=row.occupation_code,"
            query += "o.name=row.occupation_name "
            query += "MERGE(p)-[r:INFERRED_NCS_OCCUPATION "
            query += "{candidate_id:row.properties.candidate_id}]->(o) "
            query += "SET r=row.properties RETURN count(r);"
            value = self.command(["docker", "exec", "-i", self.neo, "cypher-shell", "--format",
                                  "plain"], "seed-archived-inference-" + str(index),
                                 input_text=query, timeout=120)
            if value.splitlines()[-1] != str(len(typed[index:index + 500])):
                raise RuntimeError("Archived inference endpoint/edge count mismatch")
        self.receipt["archived_inference_scope"] = dict(
            pair=pair, publication_token=token, materialized_rows=len(typed),
            reviewed_rows=sum(bool(r["payload"]["accepted"]) for r in rows),
            limit=limit, payload_rows_sha256=hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            limitation="Actual archived SQL payloads materialized in the disposable graph with "
            "minimal occupation endpoint nodes. Fixture element IDs are preserved; original "
            "production element IDs/full occupation source properties are not reproduced.")

    def seed_inference_sentinel(self):
        self.command(
            [
                "docker",
                "exec",
                self.neo,
                "cypher-shell",
                "--format",
                "plain",
                "MATCH(p:jobPosting) WITH p ORDER BY p.id LIMIT 1 "
                "MERGE(o:entity:occupation {id:'fixture:routine:inference:occupation'}) "
                "SET o.kind='Occupation',o.code='fixture-routine',"
                "o.name='SYNTHETIC preservation sentinel' "
                "MERGE(p)-[r:INFERRED_NCS_OCCUPATION "
                "{candidate_id:'fixture:routine:inference:candidate'}]->(o) "
                "SET r.id='fixture:routine:inference',"
                "r.managed_by='jobtology-metadata-occupation',r.current=true,"
                "r.projection_state='READY',r.basis='METADATA_INFERRED',"
                "r.assertion_kind='MODEL_INFERRED',r.serving_scope='STAGING',r.stage='STAGING',"
                "r.accepted=false,r.match_rank=1,r.rank_basis='SOURCE_ANCHOR_DISPLAY_ORDER_V1',"
                "r.original_primary=true,r.current_primary=true,r.occupation_scheme='NCS', "
                "r.origin='SYNTHETIC_OFFLINE_FIXTURE',r.review_status='UNREVIEWED', "
                "r.confidence_state='UNASSESSED' RETURN count(r)",
            ],
            "seed-synthetic-inference",
        )
        self.receipt["inference_preservation_scope"] = (
            "One explicitly synthetic graph sentinel, plus actual archived inference payloads "
            "when archived_inference_scope is present. Archived payloads use minimal occupation "
            "endpoints; exact fixture edge/endpoint IDs and properties are preserved. Original "
            "production element IDs and the complete NCS ontology are not reproduced."
        )
        return self.inference_sentinel("sentinel-before")

    def inference_sentinel(self, label):
        return self.command(
            [
                "docker",
                "exec",
                self.neo,
                "cypher-shell",
                "--format",
                "plain",
                "MATCH(p)-[r:INFERRED_NCS_OCCUPATION {id:'fixture:routine:inference'}]->(o) "
                "RETURN elementId(p),elementId(r),elementId(o),properties(r),properties(o)",
            ],
            label,
        )

    def negative_guards(self, expected_graph):
        # Outside measured replay: an existing source node with a wrong kind
        # must fail the independent reader/verifier and pass after exact repair.
        self.command(
            [
                "docker",
                "exec",
                self.neo,
                "cypher-shell",
                "--format",
                "plain",
                "MATCH(n:jobPosting) WITH n ORDER BY n.id LIMIT 1 "
                "SET n.kind='BENCHMARK_NEGATIVE_TAMPER' RETURN n.id",
            ],
            "negative-kind-tamper",
        )
        self.run(
            "../../graph/verify_entity_names.hpl",
            "negative-kind-rejected",
            success=False,
            extra={"RUN_ID": self.args.run_id, "NEO4J_CONNECTION": "jobtology-neo4j"},
        )
        self.command(
            [
                "docker",
                "exec",
                self.neo,
                "cypher-shell",
                "--format",
                "plain",
                "MATCH(n:jobPosting) WHERE n.kind='BENCHMARK_NEGATIVE_TAMPER' "
                "SET n.kind='JobPosting' RETURN count(n)",
            ],
            "negative-kind-repair",
        )
        self.run(
            "../../graph/verify_entity_names.hpl",
            "negative-kind-repaired",
            extra={"RUN_ID": self.args.run_id, "NEO4J_CONNECTION": "jobtology-neo4j"},
        )
        if self.graph_snapshot("graph-after-negative") != expected_graph:
            raise RuntimeError("Negative guard repair changed the exact graph")
        self.receipt["negative_guard"] = "WRONG_KIND_REJECTED_THEN_EXACT_REPAIR_VERIFIED"

    def date_batch_guards(self, expected_graph):
        """Untimed real last-batch refusals and synthetic NULL removal transport."""
        last = self.sql("SELECT identity_id FROM ingestion.graph_posting_ingestion_dates("
                        + quote(self.args.run_id) + ") ORDER BY identity_id DESC LIMIT 1",
                        "last-date-identity")
        if not last:
            raise RuntimeError("A real final date batch is required")
        key = cypher_value(last)
        params = {"RUN_ID": self.args.run_id, "NEO4J_CONNECTION": "jobtology-neo4j"}
        checks = []
        for label, mutation, repair in (
            ("wrong-kind", "SET n.kind='DATE_BATCH_WRONG_KIND'", "SET n.kind='JobPosting'"),
            ("missing-identity", "SET n.id=n.id+'-date-fixture-hidden'",
             "SET n.id=" + key),
        ):
            self.command(["docker", "exec", self.neo, "cypher-shell", "--format", "plain",
                          "MATCH(n:jobPosting {id:" + key + "}) " + mutation + " RETURN count(n)"],
                         "date-negative-" + label)
            self.run("../../graph/verify_posting_dates.hpl", "date-refused-" + label,
                     success=False, extra=params)
            self.run("../../graph/load_posting_dates.hpl", "date-write-refused-" + label,
                     success=False, extra=params)
            match = (key if label == "wrong-kind" else cypher_value(last + '-date-fixture-hidden'))
            self.command(["docker", "exec", self.neo, "cypher-shell", "--format", "plain",
                          "MATCH(n:jobPosting {id:" + match + "}) " + repair + " RETURN count(n)"],
                         "date-repair-" + label)
            self.run("../../graph/verify_posting_dates.hpl", "date-repaired-" + label, extra=params)
            checks.append("last-partial-batch-" + label + "-read-and-write-refused")
        self.command(["docker", "exec", self.neo, "cypher-shell", "--format", "plain",
                      "MATCH(n:jobPosting {id:" + key + "}) "
                      "SET n.last_ingested_at=date('1999-01-01') RETURN count(n)"],
                     "date-wrong-type")
        self.run("../../graph/verify_posting_dates.hpl", "date-wrong-type-refused",
                 success=False, extra=params)
        self.run("../../graph/load_posting_dates.hpl", "date-typed-repair", extra=params)
        self.run("../../graph/verify_posting_dates.hpl", "date-typed-repaired", extra=params)
        checks.append("wrong-date-value-and-type-refused-then-typed-repair")
        self.date_null_transport(params, expected_graph)
        checks.append('synthetic-null-removal-typed-values-and-one-row-final-batch')
        self.receipt['date_batch_correctness'] = dict(
            checks=checks, real_rows=self.receipt['expected_rows']['dates'], batch_size=500,
            real_last_batch_rows=self.receipt['expected_rows']['dates'] % 500,
            last_real_identity=last, synthetic_fixture_removed=True)

    def date_null_transport(self, params, expected_graph):
        """Run synthetic temporal/NULL transport and restore the exact fixture graph."""
        # Explicitly synthetic one-row source tests a final partial batch of one
        # and NULL semantics without rewriting any real receipt or date ledger.
        fixture_id = 'fixture:date:null-transport'
        self.command(["docker", "exec", self.neo, "cypher-shell", "--format", "plain",
                      "CREATE(n:entity:jobPosting {id:" + cypher_value(fixture_id)
                      + ",kind:'JobPosting',scraped_at:datetime('2000-01-01T00:00:00Z'),"
                      "scraped_at_basis:'STALE',scraped_at_evidence_reference:'STALE'}) "
                      "RETURN count(n)"],
                     "date-null-fixture")
        values = dict(identity_id=fixture_id, first_ingested_at='2026-10-01T00:00:00Z',
                      last_ingested_at='2026-10-02T00:00:00Z',
                      latest_ingestion_run_id='fixture-date',
                      ingestion_batch_date='2026-10-02', ingestion_time_basis='READY_COMPLETED_AT',
                      scraped_at=None, scraped_at_basis=None, scraped_at_evidence_reference=None)
        for name in ('load_posting_dates', 'verify_posting_dates'):
            template = ET.parse(self.work / 'project/graph' / (name + '.hpl'))
            root = template.getroot()
            info_name = root.find('info/name')
            assert info_name is not None
            info_name.text = 'fixture_' + name
            query = root.find("transform[name='Read posting dates']/sql")
            assert query is not None
            query.text = 'SELECT ' + ','.join(
                ('NULL' if value is None else quote(value)) + '::text AS ' + field
                for field, value in values.items()) + ' WHERE ?::text IS NOT NULL'
            # The writer's normal capture is deliberately omitted for synthetic
            # transport-only data; the authoritative real tests above retain it.
            capture = root.find("transform[name='Capture accepted posting events']")
            if capture is not None:
                root.remove(capture)
                order = root.find('order')
                assert order is not None
                for edge in list(order):
                    if (edge.findtext('from') == 'Capture accepted posting events'
                            or edge.findtext('to') == 'Capture accepted posting events'):
                        order.remove(edge)
                edge = ET.SubElement(order, 'hop')
                for field, value in (('from', 'Snapshot'), ('to', 'Read posting dates'),
                                     ('enabled', 'Y')):
                    ET.SubElement(edge, field).text = value
            target = self.work / 'project/graph' / ('fixture_' + name + '.hpl')
            template.write(target, encoding='UTF-8', xml_declaration=True)
            self.run('../../graph/fixture_' + name + '.hpl', 'date-null-' + name, extra=params)
        result = self.command(["docker", "exec", self.neo, "cypher-shell", "--format", "plain",
            "MATCH(n {id:" + cypher_value(fixture_id) + "}) RETURN "
            "valueType(n.first_ingested_at)='ZONED DATETIME NOT NULL' AND "
            "valueType(n.last_ingested_at)='ZONED DATETIME NOT NULL' AND "
            "valueType(n.ingestion_batch_date)='DATE NOT NULL' AND n.scraped_at IS NULL AND "
            "n.scraped_at_basis IS NULL AND n.scraped_at_evidence_reference IS NULL"],
            'date-null-types-and-removal')
        if not cypher_plain_true(result):
            raise RuntimeError('Typed date transport or NULL stale-property removal differs')
        self.command(["docker", "exec", self.neo, "cypher-shell", "--format", "plain",
                      "MATCH(n {id:" + cypher_value(fixture_id) + "}) DELETE n RETURN count(n)"],
                     'date-null-fixture-cleanup')
        if self.graph_snapshot('graph-after-date-negatives') != expected_graph:
            raise RuntimeError('Date negative repair changed exact graph or inference element IDs')
        self.receipt['date_null_transport'] = dict(
            typed_temporal_values=True, stale_null_properties_removed=True,
            synthetic_fixture_removed=True, exact_graph_restored=True,
            final_boolean_output=result.splitlines()[-1].strip())

    def execute_workflow(self, name: str, label: str):
        sample: dict[str, Any] = {"variant": name, "label": label, "result": "RUNNING"}
        self.receipt["samples"].append(sample)
        tick = time.monotonic()
        try:
            self.run(
                "../../graph/load_snapshot.hwf",
                label,
                extra={"RUN_ID": self.args.run_id, "NEO4J_CONNECTION": "jobtology-neo4j"},
            )
            sample.update(parse_workflow((self.logs / (label + ".log")).read_text()))
            sample["wall_seconds"] = time.monotonic() - tick
            sample["startup_orchestration_seconds"] = (
                sample["wall_seconds"] - sample["native_pipeline_seconds"]
            )
            expected = self.receipt["expected_rows"]
            for pipeline, counters in sample["reader_counters"].items():
                scope = (
                    "entities"
                    if "entity_names" in pipeline
                    else "edges"
                    if "references" in pipeline
                    else "dates"
                )
                if counters["W"] != expected[scope]:
                    raise RuntimeError("Native reader scope differs from independent SQL count")
            sample["result"] = "PASSED"
        except BaseException as error:
            sample.update(
                result="FAILED",
                failure_type=type(error).__name__,
                wall_seconds=time.monotonic() - tick,
            )
            raise
        finally:
            write_json(self.work / "receipt.json", self.receipt)


def run(args: argparse.Namespace, *, fixture: RoutineFixture | None = None,
        restored: bool = False) -> Path:
    os.umask(0o077)
    safe_runs([args.run_id])
    if sha(args.backup) != args.backup_sha256:
        raise ValueError("Archive SHA256 differs")
    manifest = json.loads((args.baseline_dir / "manifest.json").read_text())
    for relative, expected in manifest.items():
        if sha(args.baseline_dir / relative) != expected:
            raise ValueError("Sealed baseline artifact differs")
    fixture = RoutineFixture(args) if fixture is None else fixture
    path = fixture.work / "receipt.json"
    try:
        if not restored:
            tick = time.monotonic()
            fixture.boot()
            fixture.receipt["fixture_boot_seconds"] = time.monotonic() - tick
            tick = time.monotonic()
            with (
                args.backup.open("rb") as source,
                (fixture.logs / "restore.stdout").open("wb") as out,
                (fixture.logs / "restore.stderr").open("wb") as err,
            ):
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        fixture.pg,
                        "pg_restore",
                        "--no-owner",
                        "--no-privileges",
                        "--exit-on-error",
                        "-U",
                        "postgres",
                        "-d",
                        "jobtology",
                    ],
                    stdin=source,
                    stdout=out,
                    stderr=err,
                    check=True,
                    timeout=300,
                )
            fixture.receipt["restore_seconds"] = time.monotonic() - tick
        fixture.sql(
            "ALTER DATABASE jobtology SET statement_timeout="
            + quote(str(args.sql_timeout_seconds) + "s"),
            "clone-statement-timeout",
        )
        fixture.receipt["baseline_sha256"] = manifest
        fixture.receipt["candidate_sql_sha256"] = {str(p): sha(p) for p in args.candidate_sql}
        fixture.apply_variant("baseline")
        fixture.capture_originals()
        relations = json.loads(
            fixture.sql(
                "SELECT jsonb_agg(format('%I.%I',n.nspname,c.relname)) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='ingestion' "
                "AND c.relkind='r'",
                "statistics-scope",
            )
        )
        tick = time.monotonic()
        for index, relation in enumerate(relations):
            fixture.sql("ANALYZE " + relation, f"fresh-statistics-{index}")
        fixture.receipt["statistics"] = {
            "phase": "EXPLICIT_INGESTION_ANALYZE_BEFORE_PRIME",
            "relations": relations,
            "wall_seconds": time.monotonic() - tick,
        }
        fixture.apply_variant("candidate")
        if getattr(args, "baseline_source_sharing", False):
            tick = time.monotonic()
            fixture.run("../../graph/install.hwf", "candidate-canonical-installer")
            fixture.run("../../graph/install_posting_dates.hwf", "candidate-focused-date-installer")
            fixture.receipt["untimed_installer_seconds"] = time.monotonic() - tick
        fixture.receipt["before"] = fixture.fingerprint("before")
        key = quote(args.run_id)
        fixture.receipt["expected_rows"] = json.loads(
            fixture.sql(
                "SELECT jsonb_build_object('entities',(SELECT count(*) FROM "
                "ingestion.graph_source_entities(" + key + ")),"
                "'edges',(SELECT count(*) FROM ingestion.graph_source_edges(" + key + ")),"
                "'dates',(SELECT count(*) FROM ingestion.graph_posting_ingestion_dates("
                + key
                + ")))",
                "expected-counts",
            )
        )
        fixture.execute_workflow("candidate", "prime-complete-routine")
        fixture.seed_archived_inferences()
        sentinel = fixture.seed_inference_sentinel()
        original = fixture.graph_snapshot("graph-prime")
        for index, name in enumerate(fixture.receipt['order']):
            fixture.apply_variant(name)
            for scope, function in (
                ("validation", "source_graph_run_is_valid"),
                ("entities", "graph_source_entities"),
                ("edges", "graph_source_edges"),
                ("dates", "graph_posting_ingestion_dates"),
            ):
                tick = time.monotonic()
                query = "SELECT " if scope == "validation" else "SELECT count(*) FROM "
                fixture.sql(
                    query + "ingestion." + function + "(" + key + ")", f"selection-{index}-{scope}"
                )
                fixture.receipt["selection_samples"].append(
                    {
                        "variant": name,
                        "scope": scope,
                        "wall_seconds": time.monotonic() - tick,
                        "pair_index": index,
                    }
                )
            fixture.execute_workflow(name, f"routine-{index}-{name}")
            if original != fixture.graph_snapshot(f"graph-{index}-{name}"):
                raise RuntimeError("Exact typed stable graph projection differs after replay")
            if sentinel != fixture.inference_sentinel(f"sentinel-{index}"):
                raise RuntimeError("Inferred occupation sentinel element IDs or values changed")
            if fixture.receipt["before"] != fixture.fingerprint(f"preserved-{index}"):
                raise RuntimeError("Immutable source/frozen evidence changed")
        fixture.apply_variant("candidate")
        fixture.negative_guards(original)
        if getattr(args, "baseline_source_sharing", False):
            fixture.date_batch_guards(original)
        fixture.receipt["status"] = (
            "PASSED_ARCHIVED_ROUTINE_AB" if len(fixture.receipt['order']) == 2
            else "PASSED_ARCHIVED_ROUTINE_AB_BA")
    except BaseException as error:
        fixture.receipt.update(status="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        fixture.close()
        write_json(path, fixture.receipt)
        print(path, flush=True)
    if (fixture.receipt["status"] == "FAILED"
            or not fixture.receipt.get("disposable_resources_removed")):
        raise RuntimeError("Owned disposable resource cleanup incomplete")
    return path


def fresh_ingestion(args: argparse.Namespace) -> Path:
    """Candidate-only entire local ingestion; empty history differs from replay archive."""
    os.umask(0o077)
    if sha(args.local_ndjson) != args.local_ndjson_sha256:
        raise ValueError("Supplied local NDJSON SHA256 differs")
    args.fresh_phase = True
    fixture = RoutineFixture(args)
    path = fixture.work / "receipt.json"
    fixture.receipt.update(
        kind="SUPPLIED_LOCAL_FRESH_INGESTION_AND_REPLAY",
        samples=[],
        selection_samples=[],
        order=["fresh", "replay"],
    )
    fixture.receipt["limits"] = [
        "Candidate only; no before/after ingestion speedup is established.",
        "Fresh empty database and archive replay have different source-history cardinality.",
        "Installer/database boot precede and are excluded from measured file workflow.",
        "Normal source full.hwf does not create frozen model inputs; no NCS catalogue is seeded.",
        "No HTTP source retrieval, ontology release, provider calls or paid matching are measured.",
    ]
    write_json(path, fixture.receipt)
    try:
        tick = time.monotonic()
        fixture.boot()
        fixture.receipt["fixture_boot_seconds"] = time.monotonic() - tick
        tick = time.monotonic()
        fixture.install()
        for index, file in enumerate(args.candidate_sql):
            fixture.sql(file.read_text(), f"fresh-candidate-install-{index}")
        fixture.receipt["installation_seconds"] = time.monotonic() - tick
        expected = int(args.local_ndjson_rows)
        for name in ("fresh", "replay"):
            sample: dict[str, Any] = {"variant": "candidate", "phase": name, "result": "RUNNING"}
            fixture.receipt["samples"].append(sample)
            write_json(path, fixture.receipt)
            tick = time.monotonic()
            try:
                fixture.run(
                    "full.hwf",
                    "local-full-" + name,
                    extra={
                        "INPUT_FORMAT": "NDJSON",
                        "MAX_FILE_BYTES": "1073741824",
                        "BATCH_ROWS": "500",
                    },
                )
                sample.update(
                    parse_workflow((fixture.logs / ("local-full-" + name + ".log")).read_text())
                )
                sample.update(result="PASSED", wall_seconds=time.monotonic() - tick)
                if not {"import_local", "record_graph_export"}.issubset(sample["pipeline_seconds"]):
                    raise RuntimeError("Complete local import/export checkpoint stages are missing")
                sample["startup_orchestration_seconds"] = (
                    sample["wall_seconds"] - sample["native_pipeline_seconds"]
                )
            except BaseException as error:
                sample.update(
                    result="FAILED",
                    failure_type=type(error).__name__,
                    wall_seconds=time.monotonic() - tick,
                )
                raise
            key = fixture.sql(
                "SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'",
                "local-run-" + name,
            )
            safe_runs([key])
            counts = json.loads(
                fixture.sql(
                    "SELECT jsonb_build_object('ready',"
                    "(SELECT count(*) FROM ingestion.ready_record WHERE run_id=" + quote(key) + "),"
                    "'source_requests',(SELECT count(*) FROM ingestion.request_attempt),"
                    "'checkpoint',(SELECT count(*) FROM ingestion.graph_export WHERE run_id="
                    + quote(key)
                    + "),"
                    "'validation_issues',(SELECT count(*) FROM "
                    "ingestion.source_graph_validation_issue(" + quote(key) + ")))",
                    "local-counts-" + name,
                )
            )
            if counts != {
                "ready": expected,
                "source_requests": 0,
                "checkpoint": 1,
                "validation_issues": 0,
            }:
                raise RuntimeError("Fresh local source workflow exact scope/checkpoint differs")
            fingerprint = fixture.fingerprint("local-evidence-" + name)
            if name == "fresh":
                fixture.receipt["synthetic_inference_before"] = fixture.seed_inference_sentinel()
            elif fixture.receipt["synthetic_inference_before"] != fixture.inference_sentinel(
                "local-synthetic-inference-after-replay"
            ):
                raise RuntimeError("Synthetic actual-type inferred edge IDs or properties changed")
            graph = fixture.graph_snapshot("local-graph-" + name)
            if name == "fresh":
                fixture.receipt.update(run_id=key, before=fingerprint, graph=graph, counts=counts)
            elif fixture.receipt["before"] != fingerprint or fixture.receipt["graph"] != graph:
                raise RuntimeError("Local READY replay changed immutable evidence or typed graph")
            write_json(path, fixture.receipt)
        fixture.receipt["status"] = "PASSED_LOCAL_FULL_INGESTION_AND_REPLAY"
    except BaseException as error:
        fixture.receipt.update(status="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        fixture.close()
        write_json(path, fixture.receipt)
        print(path, flush=True)
    if (fixture.receipt["status"] == "FAILED"
            or not fixture.receipt.get("disposable_resources_removed")):
        raise RuntimeError("Fresh ingestion cleanup incomplete")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--backup-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--candidate-sql", type=Path, action="append", required=True)
    parser.add_argument("--baseline-source-sharing", action="store_true",
                        help="Baseline includes already deployed003 from the sealed manifest")
    parser.add_argument("--archived-inference-limit", type=int, default=0)
    parser.add_argument("--pair-order", choices=('ab', 'abba'), default='abba')
    parser.add_argument("--sql-timeout-seconds", type=int, default=300)
    parser.add_argument("--fresh-ingestion-only", action="store_true")
    parser.add_argument("--local-ndjson", type=Path)
    parser.add_argument("--local-ndjson-sha256")
    parser.add_argument("--local-ndjson-rows", type=int)
    args = parser.parse_args()
    if not 1 <= args.sql_timeout_seconds <= 3600:
        parser.error("SQL statement bound must be 1..3600 seconds")
    if not 0 <= args.archived_inference_limit <= 10000:
        parser.error("Archived inference fixture bound must be 0..10000")
    if args.fresh_ingestion_only:
        if not args.local_ndjson or not args.local_ndjson_sha256 or not args.local_ndjson_rows:
            parser.error("Fresh ingestion requires exact local NDJSON path, SHA256 and row count")
        fresh_ingestion(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
