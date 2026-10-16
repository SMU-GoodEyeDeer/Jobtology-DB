#!/usr/bin/env python3
"""Attribute native graph costs on one explicitly released archived PG clone.

The source readers are measured intact, then in scratch-only SQL-to-Dummy Hop
pipelines. SQL nested plans and read-only Neo4j PROFILE evidence are collected
separately; their timings are diagnostic and are never subtracted from replay.
There is no restore, source request, live database access or paid call.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_archived_routine as native
import benchmark_nara_worksets as borrowed
from prepare_performance_readback import transform_counters
from profile_archived_postgres import quote, write_json

READERS = {
    "entities": ("load_entity_names", "Read entity names"),
    "edges": ("load_references", "Read entity names"),
    "owners": ("clear_source_edges", "Read entity names"),
    "dates": ("verify_posting_dates", "Read posting dates"),
}
JOBALIO_RUN = "18cb0086-5800-4a2b-870f-db8d74c62fbf"


def reader_only(source: Path, target: Path, reader_name: str) -> str:
    """Retain the exact JDBC reader and variable transform, with a plain sink."""
    root = ET.parse(source).getroot()
    keep = {"Snapshot", reader_name, "Complete"}
    for transform in list(root.findall("transform")):
        if transform.findtext("name") not in keep:
            root.remove(transform)
    if {t.findtext("name") for t in root.findall("transform")} != keep:
        raise ValueError("Source pipeline reader/snapshot/sink shape differs")
    sink = root.find("transform[name='Complete']")
    reader = root.find(f"transform[name='{reader_name}']")
    assert sink is not None and reader is not None
    if sink.findtext("type") != "Dummy" or reader.findtext("type") != "DBJoin":
        raise ValueError("Source reader/sink types differ")
    sql = reader.findtext("sql")
    if not sql or sql.count("?") != 1:
        raise ValueError("Expected exactly one immutable scope parameter")
    order = root.find("order")
    assert order is not None
    order.clear()
    for start, finish in (("Snapshot", reader_name), (reader_name, "Complete")):
        hop = ET.SubElement(order, "hop")
        for key, value in (("from", start), ("to", finish), ("enabled", "Y")):
            ET.SubElement(hop, key).text = value
    root.find("info/name").text = target.stem
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(target, encoding="UTF-8", xml_declaration=True)
    return sql


class GraphCostFixture(borrowed.BorrowedFixture):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.entity_reader_mode = bool(getattr(args, "entity_reader_sql_candidate", None))
        self.reader_sql_mode = (
            bool(getattr(args, "reader_sql_candidate", [])) or self.entity_reader_mode
        )
        if self.reader_sql_mode:
            canonical006 = native.ROOT / "hop/graph/sql/006_jobalio_validation_worksets.sql"
            args.source_sql = args.source_sql or canonical006
            if native.sha(args.source_sql) != (
                "728e103f4b0df3af12ae4b2cc6f52f5d2ebf6d320163ae6daa37b35e0c627c31"
            ):
                raise ValueError("Reader comparison requires canonical frozen SQL006")
        self.reader_candidates = []
        reader_sources = (
            [args.entity_reader_sql_candidate]
            if self.entity_reader_mode
            else getattr(args, "reader_sql_candidate", [])
        )
        for source in reader_sources:
            frozen = self.work / ("launched-reader-" + source.name)
            shutil.copyfile(source, frozen)
            frozen.chmod(0o400)
            self.reader_candidates.append(frozen)
        if self.reader_sql_mode:
            expected_names = (
                ["009_reader_fact_worksets.sql"]
                if self.entity_reader_mode
                else [
                    "007_capture_guard_worksets.sql",
                    "008_reader_worksets.sql",
                ]
            )
            if [
                path.name.removeprefix("launched-reader-") for path in self.reader_candidates
            ] != expected_names:
                raise ValueError("Reader mode requires exact ordered reviewed SQL candidates")
            self.receipt["reader_candidate_sha256"] = {
                path.name.removeprefix("launched-reader-"): native.sha(path)
                for path in self.reader_candidates
            }
            for relative in (
                "sql/007_capture_guard_worksets.sql",
                "sql/008_reader_worksets.sql",
                "install.hwf",
                "install_posting_dates.hwf",
            ):
                expected_sha = native.sha(native.ROOT / "hop/graph" / relative)
                if (
                    self.receipt["candidate_artifact_sha256"].get("graph/" + relative)
                    != expected_sha
                ):
                    raise ValueError("Reader mode requires exact SQL007/008 and installer hashes")
            sealed = native.ROOT / "hop/graph/sql/002_batchfree_source_graph.sql"
            if native.sha(sealed) != (
                "bc048ef806db9f32f9ce235b6818a4e62c096d48f4a7936eda97a244921b32d3"
            ):
                raise ValueError("Reader comparison requires sealed SQL002 insert guard")
            content = sealed.read_text()
            start = content.index(
                "CREATE OR REPLACE FUNCTION ingestion.source_graph_insert_guard()"
            )
            stop = content.index("END $$;", start) + len("END $$;")
            self.baseline_insert_guard = content[start:stop]
            (self.work / "baseline-insert-guard.sql").write_text(self.baseline_insert_guard)
            if self.entity_reader_mode:
                baseline = native.ROOT / "hop/graph/sql/008_reader_worksets.sql"
                if native.sha(baseline) != (
                    "f1b71d6bce9f2b59d61b9c3122a81954f24db312de77c7b830bb9aa55676a645"
                ):
                    raise ValueError("Entity comparison requires frozen SQL008 baseline")
                content = baseline.read_text()
                start = content.index("CREATE OR REPLACE FUNCTION ingestion.graph_source_entities(")
                stop = content.index("$$;", start) + 3
                self.baseline_entity_definition = content[start:stop]
                (self.work / "baseline-entity-definition.sql").write_text(
                    self.baseline_entity_definition
                )
        self.receipt.update(
            kind="BORROWED_NETWORK_NONE_NATIVE_GRAPH_COSTS",
            order=(
                ["candidate-prime", "candidate-replay"]
                if args.compatibility_only
                else ["prime", "baseline", "candidate", "candidate", "baseline"]
                if self.reader_sql_mode
                else ["prime", "baseline", "candidate", "candidate", "baseline"]
                if args.transport_candidate or args.await_transport_candidate
                else ["prime", "baseline"]
            ),
            profile_diagnostics=[],
            transport_samples=[],
            inference_sentinel="Synthetic typed edge; exact IDs and properties protected",
        )
        self.receipt["limits"] = [
            "Exact local archived scopes; warm replay, not production capacity.",
            "Separate SQL/Hop/Neo4j measurements overlap and cannot be subtracted.",
            "Nested auto_explain is diagnostic only, never enabled in replay timing.",
            "No source HTTP, provider call, whole-file fresh import or production graph writes.",
        ]
        if getattr(args, "installer_only", False):
            self.receipt.update(
                qualification="CANONICAL_NATIVE_INSTALLERS_ONLY",
                order=["native-source-installer", "native-date-installer"],
                limits=["Canonical Hop installer compatibility; no native replay timing."],
            )
        baseline = args.transport_baseline or native.ROOT / "hop/graph"
        self.baseline_pipelines = {}
        for name in ("clear_source_edges", "verify_totals"):
            source = baseline / (name + ".hpl")
            output = ET.parse(source).getroot().find("transform[type='Neo4jCypherOutput']")
            expected_batch = "500" if self.reader_sql_mode else "1"
            if output is None or output.findtext("batch_size") != expected_batch:
                raise ValueError("Exact batch-" + expected_batch + " owner baseline required")
            if self.reader_sql_mode and (
                output.findtext("unwind") != "Y" or output.findtext("unwind_map") != "rows"
            ):
                raise ValueError("Reader mode requires deployed owner500 UNWIND transport")
            target = self.work / ("baseline-" + name + ".hpl")
            shutil.copyfile(source, target)
            self.baseline_pipelines[name] = target.read_bytes()
        self.receipt["transport_baseline_sha256"] = {
            name: native.sha(self.work / ("baseline-" + name + ".hpl"))
            for name in self.baseline_pipelines
        }
        self.candidate_pipelines = {}
        if self.reader_sql_mode:
            self.candidate_pipelines = dict(self.baseline_pipelines)
            for name, data in self.candidate_pipelines.items():
                (self.work / ("transport-" + name + ".hpl")).write_bytes(data)
            self.receipt["reader_comparison"] = {
                "baseline": (
                    "Deployed SQL007/008 and owner500"
                    if self.entity_reader_mode
                    else "SQL003/004/005/006 and deployed owner500"
                ),
                "candidate": (
                    "Same deployed runtime with entity-only SQL009"
                    if self.entity_reader_mode
                    else "Same owner500 with additive SQL007/008"
                ),
                "owner_transport_exactly_equal": True,
                "diagnostic_plans": (
                    "Previous sealed baseline plans are reused; no concurrent profiling"
                ),
            }
        if args.source_sql:
            frozen_sql = self.work / "launched-source-candidate.sql"
            shutil.copyfile(args.source_sql, frozen_sql)
            args.source_sql = frozen_sql
            self.receipt["source_candidate_sha256"] = native.sha(frozen_sql)
        for path in args.transport_candidate:
            if path.name not in {name + ".hpl" for name in self.baseline_pipelines}:
                raise ValueError("Only cleanup and per-owner totals transport candidates accepted")
            target = self.work / ("transport-" + path.name)
            shutil.copyfile(path, target)
            self.candidate_pipelines[path.stem] = target.read_bytes()
        self.receipt["transport_candidate_sha256"] = {
            name: native.sha(self.work / ("transport-" + name + ".hpl"))
            for name in self.candidate_pipelines
        }
        self.receipt["candidate_artifact_sha256"].update(
            {
                "graph/" + name + ".hpl": value
                for name, value in self.receipt["transport_candidate_sha256"].items()
            }
        )

    def apply_variant(self, name: str) -> None:
        if getattr(self, "entity_reader_mode", False):
            # The clone is already qualified at deployed SQL008. Reset only the
            # entity body; source contracts, capture guard and owner transport
            # remain fixed across both variants.
            self.sql(self.baseline_entity_definition, name + "-sql008-entity-baseline")
            if name != "baseline":
                path = self.reader_candidates[0]
                staged = self.work / "project/graph/sql/009_reader_fact_worksets.sql"
                if native.sha(staged) != native.sha(path):
                    raise RuntimeError("Staged SQL009 differs from frozen reviewed candidate")
                self.sql(path.read_text(), name + "-sql009-entity-candidate")
            self.sql("SELECT ingestion.source_graph_assert_query_contract()", name + "-contracts")
            self.function_names = ["ingestion.graph_source_entities"]
            definitions = self.definitions(name + "-reader-definitions")
            self.variant_definitions[name] = definitions
            frozen = self.work / (name + "-reader-functions.json")
            write_json(frozen, definitions)
            self.receipt.setdefault("reader_variant_definition_sha256", {})[name] = native.sha(
                frozen
            )
            return
        # Both transport variants share the reviewed SQL005/006 installation.
        super().apply_variant("candidate")
        if self.reader_sql_mode:
            self.sql(self.baseline_insert_guard, name + "-baseline-insert-guard")
        if self.args.source_sql:
            staged_sql = self.work / "project/graph/sql/006_jobalio_validation_worksets.sql"
            if native.sha(staged_sql) != native.sha(self.args.source_sql):
                raise RuntimeError("Staged native SQL006 differs from frozen reviewed candidate")
            self.sql(self.args.source_sql.read_text(), name + "-source-sql")
        if self.reader_sql_mode and name != "baseline":
            for index, path in enumerate(self.reader_candidates):
                staged = (
                    self.work / "project/graph/sql" / path.name.removeprefix("launched-reader-")
                )
                if native.sha(staged) != native.sha(path):
                    raise RuntimeError("Staged reader SQL differs from frozen launch candidate")
                self.sql(path.read_text(), name + "-reader-" + str(index))
        self.sql("SELECT ingestion.source_graph_assert_query_contract()", name + "-contracts")
        if self.reader_sql_mode:
            self.function_names = [
                "ingestion.source_graph_insert_guard",
                "ingestion.graph_source_edges",
                "ingestion.graph_source_entities",
                "ingestion.source_graph_scoped_validation_issue",
            ]
            definitions = self.definitions(name + "-reader-definitions")
            self.variant_definitions[name] = definitions
            frozen = self.work / (name + "-reader-functions.json")
            write_json(frozen, definitions)
            self.receipt.setdefault("reader_variant_definition_sha256", {})[name] = native.sha(
                frozen
            )

    def transport(self, variant: str) -> None:
        if self.reader_sql_mode:
            self.apply_variant(variant)
        values = self.baseline_pipelines if variant == "baseline" else self.candidate_pipelines
        if variant == "candidate" and set(values) != set(self.baseline_pipelines):
            raise ValueError("Both owner transport candidate pipelines are required")
        for name, body in values.items():
            (self.work / "project/graph" / (name + ".hpl")).write_bytes(body)

    def all_rows(self, label: str) -> dict[str, Any]:
        if not self.entity_reader_mode:
            return super().all_rows(label)
        from benchmark_entity_readers import protected_tables

        fixture = self

        class BoundedTableSession:
            index = 0

            def execute(self, query: str) -> str:
                self.index += 1
                return fixture.sql(query, label + "-" + str(self.index))

        result = protected_tables(BoundedTableSession())
        write_json(self.logs / (label + ".log"), result)
        return result

    def await_transport_candidate(self, directory: Path) -> None:
        """Freeze two explicit hash-locked artifacts after immutable profiling."""
        if self.candidate_pipelines:
            raise ValueError("Choose launch-time candidates or bounded continuation")
        if not directory.is_dir() or any(directory.iterdir()):
            raise ValueError("Continuation directory must initially exist and be empty")
        self.receipt["continuation"] = {
            "directory": str(directory.resolve()),
            "wait_bound_seconds": 900,
            "status": "WAITING_AFTER_PROFILE",
        }
        phase = self.work / "profile-phase-receipt.json"
        write_json(phase, self.receipt)
        phase.chmod(0o400)
        self.receipt["immutable_profile_phase"] = {"path": str(phase), "sha256": native.sha(phase)}
        write_json(self.work / "receipt.json", self.receipt)
        print(
            json.dumps(
                {"phase": "PROFILED", "receipt": str(phase), "candidate_directory": str(directory)}
            ),
            flush=True,
        )
        deadline = time.monotonic() + 900
        manifest = directory / "ready.json"
        while not manifest.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit owner candidate did not arrive in fifteen minutes")
            time.sleep(0.25)
        values = json.loads(manifest.read_text())
        expected = {"clear_source_edges.hpl", "verify_totals.hpl"}
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError("Continuation requires exact two owner artifact hashes")
        for name, expected_sha in values.items():
            if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                raise ValueError("Continuation artifact hash must be a full SHA256")
            source = directory / name
            if native.sha(source) != expected_sha:
                raise RuntimeError("Continuation artifact differs from explicit hash lock")
            output = ET.parse(source).getroot().find("transform[type='Neo4jCypherOutput']")
            if (
                output is None
                or output.findtext("batch_size") != "500"
                or output.findtext("unwind") != "Y"
                or output.findtext("unwind_map") != "rows"
            ):
                raise ValueError("Continuation requires the approved 500-row owner transport")
            target = self.work / ("transport-" + name)
            shutil.copyfile(source, target)
            target.chmod(0o400)
            if native.sha(target) != expected_sha:
                raise RuntimeError("Continuation artifact changed during freezing")
            self.candidate_pipelines[Path(name).stem] = target.read_bytes()
            self.receipt["candidate_artifact_sha256"]["graph/" + name] = expected_sha
        frozen_manifest = self.work / "launched-transport-manifest.json"
        shutil.copyfile(manifest, frozen_manifest)
        frozen_manifest.chmod(0o400)
        if json.loads(frozen_manifest.read_text()) != values:
            raise RuntimeError("Continuation manifest changed during freezing")
        self.receipt["transport_candidate_sha256"] = values
        self.receipt["continuation"].update(
            status="FROZEN_HASH_LOCKED",
            manifest_sha256=native.sha(frozen_manifest),
            accepted_at=datetime.now(UTC).isoformat(),
        )
        write_json(self.work / "receipt.json", self.receipt)

    def execute_workflow(self, name: str, label: str) -> None:
        def cpu(phase: str) -> dict[str, int]:
            result = {}
            for role, container in (("postgres", self.pg), ("neo4j", self.neo), ("hop", self.hop)):
                output = self.command(
                    ["docker", "exec", container, "cat", "/sys/fs/cgroup/cpu.stat"],
                    label + "-" + phase + "-cpu-" + role,
                    timeout=10,
                )
                values = dict(line.split() for line in output.splitlines())
                result[role] = int(values["usage_usec"])
            return result

        before = cpu("before")
        super().execute_workflow(name, label)
        after = cpu("after")
        self.receipt["samples"][-1]["cgroup_cpu_seconds"] = {
            role: (after[role] - before[role]) / 1_000_000 for role in before
        }
        write_json(self.work / "receipt.json", self.receipt)

    def expected_counts(self) -> dict[str, int]:
        # Hop executes each reader as its own bounded statement. Do not combine
        # four full function scans under one cumulative preflight timeout.
        key = quote(self.args.run_id)
        return {
            kind: int(
                self.sql(
                    "SELECT count(*) FROM ingestion." + function + "(" + key + ")",
                    "expected-counts-" + kind,
                )
            )
            for kind, function in (
                ("entities", "graph_source_entities"),
                ("edges", "graph_source_edges"),
                ("owners", "graph_source_edge_owners"),
                ("dates", "graph_posting_ingestion_dates"),
            )
        }

    def statistic_identity(self, label: str) -> str:
        return self.sql(
            "SELECT encode(sha256(convert_to(coalesce(string_agg(to_jsonb(s)::text,'' "
            "ORDER BY to_jsonb(s)::text),''),'UTF8')),'hex') FROM pg_statistic s "
            "JOIN pg_class c ON c.oid=s.starelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='ingestion'",
            label,
        )

    def diagnostic_readers(self) -> None:
        for scope, (pipeline, reader) in READERS.items():
            name = "profile_reader_" + scope
            sql = reader_only(
                self.work / "project/graph" / (pipeline + ".hpl"),
                self.work / "project/graph" / (name + ".hpl"),
                reader,
            ).replace("?", quote(self.args.run_id))
            tick = time.monotonic()
            plan = json.loads(
                self.sql(
                    "SET max_parallel_workers_per_gather=0; "
                    "LOAD 'auto_explain'; SET auto_explain.log_min_duration=0; "
                    "SET auto_explain.log_analyze=on; SET auto_explain.log_buffers=on; "
                    "SET auto_explain.log_nested_statements=on; "
                    "SET auto_explain.log_format=json; SET auto_explain.log_level=notice; "
                    "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + sql,
                    "sql-plan-" + scope,
                )
            )
            elapsed = time.monotonic() - tick
            write_json(self.work / ("sql-plan-" + scope + ".json"), plan)
            tick = time.monotonic()
            self.run(
                "../../graph/" + name + ".hpl",
                "hop-reader-" + scope,
                extra={"RUN_ID": self.args.run_id},
            )
            log = (self.logs / ("hop-reader-" + scope + ".log")).read_text()
            durations = re.findall(r"Pipeline duration\s*:\s*([0-9.]+) seconds", log)
            counters = transform_counters(log, reader)
            if len(durations) != 1 or counters["W"] != self.receipt["expected_rows"][scope]:
                raise RuntimeError("Standalone JDBC reader did not preserve exact row count")
            self.receipt["profile_diagnostics"].append(
                {
                    "scope": scope,
                    "sql_instrumented_wall_seconds": elapsed,
                    "sql_execution_ms": plan[0]["Execution Time"],
                    "hop_wall_seconds": time.monotonic() - tick,
                    "hop_pipeline_seconds": float(durations[0]),
                    "reader_counters": counters,
                    "sql": sql,
                }
            )
            write_json(self.work / "receipt.json", self.receipt)

    def neo_read_profiles(self) -> None:
        for name, reader in (
            ("verify_entity_names", "Read entity names"),
            ("verify_posting_dates", "Read posting dates"),
        ):
            root = ET.parse(self.work / "project/graph" / (name + ".hpl")).getroot()
            sql = root.find(f"transform[name='{reader}']/sql").text
            sql = sql.replace("?", quote(self.args.run_id))
            rows = json.loads(
                self.sql(
                    "SELECT coalesce(jsonb_agg(to_jsonb(s)),'[]') FROM (" + sql + " LIMIT 500)s",
                    "neo-profile-input-" + name,
                )
            )
            cypher = root.find("transform[type='Neo4jCypherOutput']/cypher").text
            if not rows or re.search(r"\b(SET|CREATE|DELETE|MERGE)\b", cypher):
                raise RuntimeError("Neo4j profiling accepts nonempty read-only verifier only")
            output = self.command(
                ["docker", "exec", "-i", self.neo, "cypher-shell", "--format", "verbose"],
                "neo-profile-" + name,
                input_text=":param rows => "
                + native.cypher_value(rows)
                + "\nPROFILE "
                + cypher
                + ";\n",
                timeout=60,
            )
            if "DbHits" not in output and "DB Hits" not in output:
                raise RuntimeError("Neo4j PROFILE plan missing actual database-hit evidence")
            if not re.search(r"\|\s*true\s*\|", output, re.IGNORECASE):
                raise RuntimeError("Read-only Neo4j PROFILE did not verify its complete batch")
            self.receipt.setdefault("neo_profiles", []).append(
                {"pipeline": name, "rows": len(rows), "protected_log": "neo-profile-" + name}
            )


def run(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    for relative, expected in borrowed.FROZEN.items():
        if native.sha(native.ROOT / "hop" / relative) != expected:
            raise ValueError("Frozen source/replay/statistics SQL changed")
    if native.sha(args.backup) != args.backup_sha256:
        raise ValueError("Released clone archive/hash mismatch")
    fixture = GraphCostFixture(args)
    path = fixture.work / "receipt.json"
    shutil.copyfile(Path(__file__), fixture.work / "launched-helper.py")
    fixture.receipt["launched_helper_sha256"] = native.sha(Path(__file__))
    fixture.function_names = ["ingestion.source_graph_scoped_validation_issue"]
    write_json(path, fixture.receipt)
    print(path, flush=True)
    try:
        fixture.boot_borrowed()
        if fixture.reader_sql_mode:
            fixture.receipt["analyzed_statistics_before"] = fixture.statistic_identity(
                "reader-fixed-statistics-before"
            )
        fixture.apply_variant("source-candidate")
        rows = fixture.all_rows("all-before-native-installers")
        if args.recover_nara_proof:
            prior = json.loads(args.recover_nara_proof.read_text())
            if (
                prior["run_id"] != borrowed.NARA_RUN
                or prior["status"] != "FAILED"
                or rows != prior["protected_before"]
            ):
                raise RuntimeError("Exact prior Nara protected tables differ")
            selected = fixture.args.run_id
            try:
                fixture.args.run_id = borrowed.NARA_RUN
                recovered = fixture.assert_proof("recovered-nara-full-manifests")
            finally:
                fixture.args.run_id = selected
            if recovered != prior["proof_before"]:
                raise RuntimeError("Exact prior Nara full source proof differs")
            fixture.receipt["recovered_nara_preservation"] = dict(
                prior_receipt_path=str(args.recover_nara_proof),
                prior_receipt_sha256=native.sha(args.recover_nara_proof),
                all_protected_tables_equal=True,
                table_count=len(rows),
                complete_source_proof_equal=True,
                proof=recovered,
            )
        if args.reuse_native_installer_proof:
            previous = json.loads(args.reuse_native_installer_proof.read_text())
            previous_rows = (
                args.reuse_native_installer_proof.parent
                / "logs"
                / ("all-before-native-installers.log")
            )
            old_identity = json.loads(
                (
                    args.reuse_native_installer_proof.parent / "logs" / ("borrowed-pg-inspect.log")
                ).read_text()
            )["Id"]
            current_identity = json.loads((fixture.logs / "borrowed-pg-inspect.log").read_text())[
                "Id"
            ]
            if (
                not previous.get("native_installers_preserve_all_rows")
                or previous["candidate_artifact_sha256"]
                != fixture.receipt["candidate_artifact_sha256"]
                or previous["borrowed_postgres"] != fixture.pg
                or not previous.get("borrowed_container_id_preserved_and_none_restored")
                or old_identity != current_identity
                or rows != json.loads(previous_rows.read_text())
            ):
                raise RuntimeError("Exact same-clone native installer proof cannot be reused")
            fixture.receipt["reused_native_installer_proof"] = dict(
                path=str(args.reuse_native_installer_proof),
                sha256=native.sha(args.reuse_native_installer_proof),
                identical_actual_container_id=current_identity,
                unchanged_table_fingerprint_sha256=native.sha(previous_rows),
            )
        else:
            fixture.run("../../graph/install.hwf", "native-source-installer")
            fixture.run("../../graph/install_posting_dates.hwf", "native-date-installer")
            if rows != fixture.all_rows("all-after-native-installers"):
                raise RuntimeError("Native installers changed protected table rows")
        fixture.receipt["native_installers_preserve_all_rows"] = True
        fixture.receipt["proof_before"] = fixture.assert_proof("initial-full-manifests")
        if fixture.entity_reader_mode:
            identity = fixture.statistic_identity("installer-phase-fixed-statistics")
            if identity != fixture.receipt["analyzed_statistics_before"]:
                raise RuntimeError("Canonical installers changed fixed analyzed statistics")
            phase = fixture.work / "native-installer-phase.json"
            inspected = json.loads((fixture.logs / "borrowed-pg-inspect.log").read_text())
            phase_receipt = dict(fixture.receipt)
            phase_receipt.update(
                status="PASSED_CANONICAL_NATIVE_INSTALLER_PHASE",
                qualification="CANONICAL_NATIVE_INSTALLERS_ONLY",
                container_id=inspected["Id"],
                protected_table_count=len(rows),
                statistic_identity=identity,
                no_replay_started=True,
                finished_at=datetime.now(UTC).isoformat(),
            )
            write_json(phase, phase_receipt)
            phase.chmod(0o400)
            fixture.receipt["canonical_native_installer_phase"] = {
                "path": str(phase),
                "sha256": native.sha(phase),
            }
            write_json(path, fixture.receipt)
            print(
                json.dumps({"phase": "CANONICAL_NATIVE_INSTALLERS_PASSED", "receipt": str(phase)}),
                flush=True,
            )
        if getattr(args, "installer_only", False):
            fixture.receipt["analyzed_statistics_after"] = fixture.statistic_identity(
                "installer-fixed-statistics-after"
            )
            if (
                fixture.receipt["analyzed_statistics_before"]
                != fixture.receipt["analyzed_statistics_after"]
            ):
                raise RuntimeError("Canonical installers changed fixed analyzed statistics")
            fixture.receipt["status"] = "PASSED_NATIVE_INSTALLERS_PENDING_BORROWED_CLEANUP"
            return path
        fixture.receipt["expected_rows"] = fixture.expected_counts()
        installed_rows = rows
        prime_variant = "candidate" if args.compatibility_only else "baseline"
        fixture.transport(prime_variant)
        fixture.execute_workflow(prime_variant, "prime")
        fixture.seed_inference_sentinel()
        graph = fixture.graph_snapshot("graph-before")
        rows = fixture.all_rows("all-protected-before")
        fixture.receipt["protected_before"] = rows
        prime_changes = {
            name: {"before": installed_rows[name], "after": rows[name]}
            for name in installed_rows
            if installed_rows[name] != rows[name]
        }
        if set(prime_changes) - {"ingestion.posting_ingestion_observation"}:
            raise RuntimeError("Priming changed protected rows beyond date observations")
        fixture.receipt["prime_operational_changes"] = prime_changes
        fixture.execute_workflow(prime_variant, "warm-" + prime_variant)
        if not args.compatibility_only and not fixture.reader_sql_mode:
            fixture.diagnostic_readers()
            fixture.neo_read_profiles()
        if args.await_transport_candidate:
            fixture.await_transport_candidate(args.await_transport_candidate)
        if fixture.candidate_pipelines and not args.compatibility_only:
            for index, variant in enumerate(("candidate", "candidate", "baseline")):
                fixture.transport(variant)
                fixture.execute_workflow(variant, f"warm-{index}-{variant}")
        if fixture.candidate_pipelines and (
            args.owner_acceptance
            or (not args.compatibility_only and not fixture.entity_reader_mode)
        ):
            fixture.transport("candidate")
            source = native.ROOT / "hop/graph/tests/source_owner_batches_native.py"
            frozen = fixture.work / "launched-owner-batch-checks.py"
            shutil.copyfile(source, frozen)
            spec = importlib.util.spec_from_file_location("owner_batch_checks", frozen)
            if spec is None or spec.loader is None:
                raise RuntimeError("Frozen native owner checks could not be loaded")
            checks = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(checks)
            fixture.receipt["launched_owner_checks_sha256"] = native.sha(frozen)
            checks.run(fixture)
        if graph != fixture.graph_snapshot("graph-after"):
            raise RuntimeError("Typed graph or inferred sentinel identities/properties changed")
        if rows != fixture.all_rows("all-protected-after"):
            raise RuntimeError("Protected table rows changed across native replay")
        fixture.receipt["proof_after"] = fixture.assert_proof("final-full-manifests")
        if fixture.receipt["proof_before"] != fixture.receipt["proof_after"]:
            raise RuntimeError("Exact source proof changed")
        if args.local_ndjson:
            fixture.fresh_compatibility(args.local_ndjson)
            if rows != fixture.all_rows("all-after-fresh-compatibility"):
                raise RuntimeError("Fresh sibling changed borrowed archived database")
        if fixture.reader_sql_mode:
            fixture.receipt["analyzed_statistics_after"] = fixture.statistic_identity(
                "reader-fixed-statistics-after"
            )
            if (
                fixture.receipt["analyzed_statistics_before"]
                != fixture.receipt["analyzed_statistics_after"]
            ):
                raise RuntimeError("Fixed analyzed statistics changed across reader comparison")
        fixture.receipt["status"] = "PASSED_NATIVE_GRAPH_COSTS_PENDING_BORROWED_CLEANUP"
    except BaseException as exc:
        fixture.receipt.update(status="FAILED", failure_type=type(exc).__name__)
        raise
    finally:
        fixture.close()
        inspected = subprocess.run(
            ["docker", "inspect", fixture.pg, "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if inspected.returncode == 0:
            current = json.loads(inspected.stdout)
            original = json.loads((fixture.logs / "borrowed-pg-inspect.log").read_text())
            restored = current["Id"] == original["Id"] and set(
                current["NetworkSettings"]["Networks"]
            ) == {"none"}
            fixture.receipt["borrowed_container_id_preserved_and_none_restored"] = restored
            if not restored:
                fixture.receipt["status"] = "FAILED"
            if fixture.original_db_timeout is not None:
                setting = fixture.sql(
                    "SELECT coalesce((SELECT substring(setting FROM 19) FROM "
                    "pg_db_role_setting s,unnest(s.setconfig) setting WHERE "
                    "s.setdatabase=(SELECT oid FROM pg_database WHERE datname='jobtology') "
                    "AND s.setrole=0 AND setting LIKE 'statement_timeout=%'),'')",
                    "independent-restored-database-timeout",
                )
                fixture.receipt["borrowed_database_timeout_restored"] = (
                    setting == fixture.original_db_timeout
                )
                if not fixture.receipt["borrowed_database_timeout_restored"]:
                    fixture.receipt["status"] = "FAILED"
        else:
            fixture.receipt["status"] = "FAILED"
        fixture.receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(path, fixture.receipt)
        print(path, flush=True)
    return path


def seal_cleanup(path: Path) -> None:
    receipt = json.loads(path.read_text())
    if (
        receipt["kind"] != "BORROWED_NETWORK_NONE_NATIVE_GRAPH_COSTS"
        or receipt["status"]
        not in {
            "PASSED_NATIVE_GRAPH_COSTS_PENDING_BORROWED_CLEANUP",
            "PASSED_NATIVE_INSTALLERS_PENDING_BORROWED_CLEANUP",
        }
        or not receipt.get("owned_native_resources_removed")
        or not receipt.get("private_scratch_removed")
        or receipt.get("cleanup_failures")
    ):
        raise RuntimeError("Native proof and owned cleanup must pass before final sealing")
    targets = [["inspect", receipt["borrowed_postgres"]]] + [
        ["volume", "inspect", name] for name in receipt["borrowed_postgres_volumes"]
    ]
    for target in targets:
        if (
            subprocess.run(
                ["docker", *target], capture_output=True, timeout=10, check=False
            ).returncode
            == 0
        ):
            raise RuntimeError("Clone owner must remove PostgreSQL and exact volume first")
    receipt.update(
        native_receipt_sha256_before_cleanup_seal=native.sha(path),
        status=(
            "PASSED_NATIVE_INSTALLERS_COMPLETE_CLEANUP"
            if receipt["status"] == "PASSED_NATIVE_INSTALLERS_PENDING_BORROWED_CLEANUP"
            else "PASSED_NATIVE_GRAPH_COSTS_COMPLETE_CLEANUP"
        ),
        disposable_resources_removed=True,
        cleanup_deferred_to_clone_owner=False,
        cleanup_confirmed=True,
        cleanup_sealed_at=datetime.now(UTC).isoformat(),
    )
    write_json(path, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--backup-sha256")
    parser.add_argument("--source-sql", type=Path)
    parser.add_argument(
        "--reader-sql-candidate",
        type=Path,
        action="append",
        default=[],
        help="Compare additive SQL007/008 with owner500 fixed on both sides",
    )
    parser.add_argument(
        "--entity-reader-sql-candidate",
        type=Path,
        help="Compare entity-only SQL009 against deployed SQL008 with owner500 fixed",
    )
    parser.add_argument("--transport-candidate", type=Path, action="append", default=[])
    parser.add_argument("--transport-baseline", type=Path)
    parser.add_argument("--compatibility-only", action="store_true")
    parser.add_argument(
        "--installer-only",
        action="store_true",
        help="Qualify both canonical installers before starting entity replay measurements",
    )
    parser.add_argument(
        "--owner-acceptance",
        action="store_true",
        help="Run independent owner boundary acceptance after compatibility replay",
    )
    parser.add_argument(
        "--recover-nara-proof",
        type=Path,
        help="Bind failed Nara receipt to exact protected rows/full source proof",
    )
    parser.add_argument(
        "--reuse-native-installer-proof",
        type=Path,
        help="Reuse same-clone installer proof only with exact artifacts/rows",
    )
    parser.add_argument("--await-transport-candidate", type=Path)
    parser.add_argument("--local-ndjson", type=Path)
    parser.add_argument("--run-id", default=borrowed.NARA_RUN)
    parser.add_argument("--seal-cleanup", type=Path)
    args = parser.parse_args()
    if args.seal_cleanup:
        seal_cleanup(args.seal_cleanup)
        return
    if not all((args.container, args.backup, args.backup_sha256)):
        parser.error("Exact explicitly released clone and archive/hash are required")
    if args.run_id not in {borrowed.NARA_RUN, JOBALIO_RUN}:
        parser.error("Only the two exact approved archived source scopes are accepted")
    if args.reader_sql_candidate and args.entity_reader_sql_candidate:
        parser.error("Choose one reviewed reader comparison")
    if (args.reader_sql_candidate or args.entity_reader_sql_candidate) and (
        args.transport_candidate or args.await_transport_candidate or args.transport_baseline
    ):
        parser.error("Reader mode fixes owner500; transport comparison options cannot be combined")
    if (
        args.compatibility_only
        and len(args.transport_candidate) != 2
        and not args.reader_sql_candidate
        and not args.entity_reader_sql_candidate
    ):
        parser.error("Compatibility-only mode requires both final owner transport candidates")
    if args.owner_acceptance and not args.compatibility_only:
        parser.error("Owner acceptance continuation requires compatibility-only mode")
    if args.recover_nara_proof and not args.owner_acceptance:
        parser.error("Nara recovery requires explicit compatibility owner acceptance")
    if args.reuse_native_installer_proof and not (
        args.owner_acceptance or args.entity_reader_sql_candidate
    ):
        parser.error("Installer reuse requires explicit compatibility owner acceptance")
    if args.installer_only and not args.entity_reader_sql_candidate:
        parser.error("Installer-only qualification requires the entity comparison candidate")
    if args.await_transport_candidate and (args.transport_candidate or args.compatibility_only):
        parser.error("Continuation requires profiling without launch-time transport candidates")
    args.candidate_sql = [native.ROOT / "hop/graph/sql/005_validation_worksets.sql"]
    args.baseline_dir = native.ROOT
    args.pair_order = "abba"
    args.sql_timeout_seconds = 60
    args.archived_inference_limit = 0
    run(args)


if __name__ == "__main__":
    main()
