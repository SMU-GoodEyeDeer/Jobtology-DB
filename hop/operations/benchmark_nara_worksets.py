#!/usr/bin/env python3
"""Bounded complete native Nara replay using an already restored owned clone.

Neo4j and Hop use one owned internal network temporarily joined by the clone.
There is no second archive restore, source request, provider call or live access.
The clone owner must seal final borrowed-container cleanup after this operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import benchmark_archived_routine as native
from profile_archived_postgres import quote, write_json

FROZEN = {
    "graph/sql/003_source_query_sharing.sql": (
        "761ecb278d4db00396128e00fa2290973928a4c1be3cd0c3796a456cf441beff"
    ),
    "graph/sql/004_verified_proof_replay.sql": (
        "bc4c0f3ef9f72012a0a0cff2844a9ec72b890c4a7710fe9b4ba16718f733e5a1"
    ),
    "ingestions/jobkorea/sql/008_ready_statistics.sql": (
        "6cecd227a2bba25e8c0ce20d8ca3cdc80f00f681d2bf1bd8dfb07dba7dad4fec"
    ),
}
NARA_RUN = "9419ffbf-0102-4a44-8c3b-ee28685f1a35"
LOCAL_SHA = "6a1d853aaca446a8c9a6081a8bfe3347ad24e496b5915e1ba2e50571b1d33d72"
SCHEMAS = "('attachment','catalog','cs','enrichment','ingestion','ontology','retention')"


class BorrowedFixture(native.RoutineFixture):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.pg = args.container
        self.database = "jobtology"
        self.receipt.update(
            kind="BORROWED_NETWORK_NONE_COMPLETE_NARA_REPLAY",
            borrowed_postgres=self.pg,
            started_at=datetime.now(UTC).isoformat(),
            samples=[],
            order=["candidate-prime", "baseline-bounded", "candidate"],
            network_topology="OWNED_INTERNAL_NETWORK_NO_PUBLISHED_PORTS",
            statement_timeout_seconds=60,
            cleanup_deferred_to_clone_owner=True,
        )
        self.receipt["limits"] = [
            "Exact supplied archived Nara scope; warm candidate replay after priming.",
            "Baseline may be statement-timeout censored; no numeric whole-workflow speedup ratio.",
            "SQL capture and Hop processing are combined; graph stages combine SQL and Neo4j.",
            "No source fetching, whole-file fresh throughput, ontology release or production gain.",
            "Synthetic inferred-edge sentinel preserves fixture IDs/properties; "
            "live graph IDs are outside scope.",
        ]
        self.original_db_timeout: str | None = None
        self.fresh_database: str | None = None
        self.owned_volumes: set[str] = set()
        self.network_created = False
        self.borrowed_network_attached = False
        self.none_network_detached = False

    def apply_variant(self, name: str) -> None:
        for index, relative in enumerate(FROZEN):
            self.sql((native.ROOT / "hop" / relative).read_text(), f"{name}-frozen-{index}")
        if name == "candidate":
            self.sql(self.args.candidate_sql[0].read_text(), "candidate-worksets")
        self.sql("SELECT ingestion.source_graph_assert_query_contract()", name + "-query-guard")
        definitions = self.definitions(name + "-definitions")
        self.variant_definitions[name] = definitions
        write_json(self.work / (name + "-functions.json"), definitions)

    def boot_borrowed(self) -> None:
        inspect = json.loads(
            self.command(
                ["docker", "inspect", self.pg, "--format", "{{json .}}"], "borrowed-pg-inspect"
            )
        )
        if (
            not re.fullmatch(r"jobtology-routine-archive-nara-[0-9a-f]+", self.pg)
            or inspect["HostConfig"]["NetworkMode"] != "none"
            or set(inspect["NetworkSettings"]["Networks"]) - {"none"}
        ):
            raise ValueError("Use only the explicitly released network-none Nara clone")
        self.receipt["borrowed_postgres_volumes"] = [
            mount["Name"] for mount in inspect["Mounts"] if mount["Type"] == "volume"
        ]
        self.stage()
        self.command(["docker", "network", "create", "--internal", self.network], "create-network")
        self.network_created = True
        self.command(["docker", "network", "disconnect", "none", self.pg], "detach-private-none")
        self.none_network_detached = True
        self.command(["docker", "network", "connect", self.network, self.pg], "attach-borrowed-pg")
        self.borrowed_network_attached = True
        images = {}
        for kind, image in (("neo", "neo4j:2026.06.0"), ("hop", "apache/hop:latest")):
            images[kind] = self.command(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"], "image-" + kind
            )
        self.receipt["images"] = images
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                self.network,
                "--name",
                self.neo,
                "-e",
                "NEO4J_AUTH=none",
                "-e",
                "NEO4J_server_memory_heap_initial__size=256m",
                "-e",
                "NEO4J_server_memory_heap_max__size=512m",
                "-e",
                "NEO4J_server_memory_pagecache_size=256m",
                images["neo"],
            ],
            "boot-neo",
        )
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                self.network,
                "--name",
                self.hop,
                "--user",
                "root",
                "-v",
                str(self.work) + ":/fixture",
                "--entrypoint",
                "/bin/sleep",
                images["hop"],
                "infinity",
            ],
            "boot-hop",
        )
        for container in (self.neo, self.hop):
            data = json.loads(
                self.command(
                    ["docker", "inspect", container, "--format", "{{json .}}"],
                    "inspect-" + container,
                )
            )
            if set(data["NetworkSettings"]["Networks"]) != {self.network}:
                raise RuntimeError("Native container differs from owned internal network")
            if data["HostConfig"]["PortBindings"]:
                raise RuntimeError("Native fixture unexpectedly publishes ports")
        for _ in range(150):
            state = json.loads(
                self.command(
                    ["docker", "inspect", self.neo, "--format", "{{json .State}}"],
                    "neo-ready-state",
                )
            )
            if not state["Running"]:
                self.command(["docker", "logs", self.neo], "neo-startup-logs")
                raise RuntimeError("Owned Neo4j exited during startup")
            result = subprocess.run(
                ["docker", "exec", self.neo, "cypher-shell", "RETURN 1"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Owned Neo4j did not become ready")
        self.original_db_timeout = self.sql(
            "SELECT coalesce((SELECT substring(setting FROM 19) FROM pg_db_role_setting s,"
            "unnest(s.setconfig) setting WHERE s.setdatabase=(SELECT oid FROM pg_database "
            "WHERE datname='jobtology') AND s.setrole=0 "
            "AND setting LIKE 'statement_timeout=%'),'')",
            "original-database-timeout",
        )
        self.sql("ALTER DATABASE jobtology SET statement_timeout='60s'", "set-native-server-bound")
        bound = json.loads(
            native.Fixture.command(
                self,
                [
                    "docker",
                    "exec",
                    "-i",
                    self.pg,
                    "psql",
                    "-X",
                    "-qAt",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    "postgres",
                    "-d",
                    "jobtology",
                ],
                "new-connection-bound",
                input_text="SELECT jsonb_build_object('setting',setting,'unit',unit,"
                "'source',source) "
                "FROM pg_settings WHERE name='statement_timeout'",
                timeout=10,
            )
        )
        if bound != {"setting": "60000", "unit": "ms", "source": "database"}:
            raise RuntimeError(
                "Fresh JDBC-equivalent connection does not inherit sixty-second bound"
            )
        self.receipt["server_connection_bound_verified"] = bound
        self.receipt["statistics"] = json.loads(
            self.sql(
                "SELECT jsonb_build_object('column_statistics',count(*),'relations',count(DISTINCT "
                "schemaname||'.'||tablename)) FROM pg_stats WHERE schemaname='ingestion'",
                "record-existing-statistics",
            )
        )
        if self.receipt["statistics"]["column_statistics"] == 0:
            raise RuntimeError("Explicit analyzed clone statistics are required before timing")

    def all_rows(self, label: str) -> dict[str, Any]:
        names = json.loads(
            self.sql(
                "SELECT jsonb_agg(n.nspname||'.'||c.relname ORDER BY n.nspname,c.relname) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.relkind IN('r','p') AND n.nspname IN" + SCHEMAS,
                label + "-tables",
            )
        )
        clauses = []
        for name in names:
            if not re.fullmatch(r"[a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*", name):
                raise RuntimeError("Unexpected fingerprint relation")
            exclusions = (
                "-'started_at'-'verified_at'"
                if name == "ingestion.source_graph_projection"
                else "-'exported_at'"
                if name == "ingestion.graph_export"
                else ""
            )
            clauses.append(
                "SELECT " + quote(name) + " AS name,count(*) AS count,"
                "md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS digest FROM "
                "(SELECT md5((to_jsonb(t)" + exclusions + ")::text) h FROM " + name + " t) rows"
            )
        return json.loads(
            self.sql(
                "SELECT jsonb_object_agg(name,to_jsonb(t)-'name') FROM ("
                + " UNION ALL ".join(clauses)
                + ") t",
                label,
            )
        )

    def assert_proof(self, label: str) -> dict[str, Any]:
        key = quote(self.args.run_id)
        result = json.loads(
            self.sql(
                "SELECT jsonb_build_object('captured',to_jsonb(c),'live',to_jsonb(l),"
                "'equal',to_jsonb(c)=to_jsonb(l)) FROM ingestion.source_graph_manifest("
                + key
                + ",false)c CROSS JOIN ingestion.source_graph_manifest("
                + key
                + ",true)l",
                label,
            )
        )
        if not result["equal"]:
            raise RuntimeError("Complete captured and live source manifests differ")
        return result

    def fresh_compatibility(self, supplied: Path) -> None:
        if supplied.stat().st_size != 21951764 or native.sha(supplied) != LOCAL_SHA:
            raise ValueError("Exact supplied composed NDJSON file is required")
        body = bytearray()
        provenance = []
        with supplied.open("rb") as source:
            for line_no in range(1, 4):
                offset = source.tell()
                line = source.readline()
                if not line.endswith(b"\n"):
                    raise ValueError("Supplied complete physical line requires LF")
                json.loads(line)
                provenance.append(
                    {
                        "physical_line": line_no,
                        "byte_offset": offset,
                        "byte_length": len(line),
                        "sha256": hashlib.sha256(line).hexdigest(),
                    }
                )
                body.extend(line)
        target = self.work / "inputs/sample.ndjson"
        target.write_bytes(body)
        target.chmod(0o400)
        self.fresh_database = "jobkorea_dryrun_" + self.token
        self.sql('CREATE DATABASE "' + self.fresh_database + '"', "create-fresh-database")
        schema = subprocess.run(
            [
                "docker",
                "exec",
                self.pg,
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
            timeout=30,
        )
        (self.work / "fresh-schema.sql").write_bytes(schema.stdout)
        old_database = self.database
        self.database = self.fresh_database
        metadata = self.work / "project/metadata/rdbms/jobtology-postgres.json"
        previous_metadata = metadata.read_bytes()
        db = json.loads(previous_metadata)
        settings = db["rdbms"]["POSTGRESQL"]
        settings["databaseName"] = self.fresh_database
        settings["manualUrl"] = "jdbc:postgresql://" + self.pg + ":5432/" + self.fresh_database
        metadata.write_text(json.dumps(db))
        try:
            self.sql(schema.stdout.decode(), "install-fresh-schema")
            self.sql(
                'ALTER DATABASE "'
                + self.fresh_database
                + "\" SET statement_timeout='60s'; ALTER DATABASE \""
                + self.fresh_database
                + '" SET jobtology.isolated_fixture='
                + quote(self.token),
                "fresh-server-bound-and-isolation",
            )
            self.apply_variant("candidate")
            samples = []
            for phase in ("fresh", "replay"):
                tick = time.monotonic()
                self.run(
                    "full.hwf",
                    "three-line-" + phase,
                    input_name="sample.ndjson",
                    extra={"INPUT_FORMAT": "NDJSON", "BATCH_ROWS": "2"},
                )
                parsed = native.parse_workflow(
                    (self.logs / ("three-line-" + phase + ".log")).read_text()
                )
                if not {"import_local", "record_graph_export"}.issubset(parsed["pipeline_seconds"]):
                    raise RuntimeError("Fresh compatibility omits native import/export stages")
                samples.append({"phase": phase, "wall_seconds": time.monotonic() - tick, **parsed})
            run_id = self.sql(
                "SELECT run_id FROM ingestion.run WHERE source_id='jobkorea'", "fresh-run-id"
            )
            counts = json.loads(
                self.sql(
                    "SELECT jsonb_build_object('ready',(SELECT state FROM ingestion.run),"
                    "'records',(SELECT count(*) FROM ingestion.record),"
                    "'issues',(SELECT count(*) FROM ingestion.validation_issue),"
                    "'requests',(SELECT count(*) FROM ingestion.request_attempt),"
                    "'proof_equal',(SELECT to_jsonb(a)=to_jsonb(b) FROM "
                    "ingestion.source_graph_manifest(" + quote(run_id) + ",false)a CROSS JOIN "
                    "ingestion.source_graph_manifest(" + quote(run_id) + ",true)b))",
                    "fresh-complete-counts",
                )
            )
            if counts != {
                "ready": "READY",
                "records": 3,
                "issues": 0,
                "requests": 0,
                "proof_equal": True,
            }:
                raise RuntimeError("Three-line native compatibility proof failed")
            self.receipt["fresh_compatibility"] = {
                "supplied_file_sha256": LOCAL_SHA,
                "supplied_file_bytes": 21951764,
                "subset_sha256": hashlib.sha256(body).hexdigest(),
                "subset_bytes": len(body),
                "physical_line_provenance": provenance,
                "run_id": run_id,
                "counts": counts,
                "samples": samples,
                "limitation": "Three exact supplied lines in an empty schema-only database; "
                "functional regression, not whole-file throughput or speedup.",
            }
        finally:
            self.database = old_database
            metadata.write_bytes(previous_metadata)

    def close(self) -> None:
        errors = []
        if self.fresh_database:
            try:
                self.sql('DROP DATABASE "' + self.fresh_database + '" WITH(FORCE)', "drop-fresh-db")
                self.receipt["fresh_database_removed"] = True
            except BaseException as exc:
                errors.append(type(exc).__name__ + ":fresh_database")
        if self.original_db_timeout is not None:
            try:
                statement = (
                    "ALTER DATABASE jobtology SET statement_timeout="
                    + quote(self.original_db_timeout)
                    if self.original_db_timeout
                    else "ALTER DATABASE jobtology RESET statement_timeout"
                )
                self.sql(statement, "restore-native-server-bound")
            except BaseException as exc:
                errors.append(type(exc).__name__ + ":database_timeout")
        try:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-u",
                    "root",
                    self.hop,
                    "rm",
                    "-rf",
                    "--",
                    "/fixture/inputs",
                    "/fixture/raw",
                    "/fixture/project",
                    "/fixture/config",
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except BaseException as exc:
            errors.append(type(exc).__name__ + ":scratch")
        for container in (self.hop, self.neo):
            inspected = subprocess.run(
                ["docker", "inspect", container],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if inspected.returncode == 0:
                self.owned_volumes.update(
                    m["Name"]
                    for m in json.loads(inspected.stdout)[0]["Mounts"]
                    if m["Type"] == "volume"
                )
            subprocess.run(
                ["docker", "rm", "-fv", container], capture_output=True, timeout=20, check=False
            )
        if self.borrowed_network_attached:
            result = subprocess.run(
                ["docker", "network", "disconnect", self.network, self.pg],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode:
                errors.append("borrowed_network_disconnect")
        if self.none_network_detached:
            result = subprocess.run(
                ["docker", "network", "connect", "none", self.pg],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode:
                errors.append("borrowed_none_network_restore")
        if self.network_created:
            subprocess.run(
                ["docker", "network", "rm", self.network],
                capture_output=True,
                timeout=10,
                check=False,
            )
        targets = [["inspect", self.hop], ["inspect", self.neo]]
        if self.network_created:
            targets.append(["network", "inspect", self.network])
        targets.extend(["volume", "inspect", volume] for volume in sorted(self.owned_volumes))
        self.receipt["owned_native_resources_removed"] = all(
            subprocess.run(
                ["docker", *target], capture_output=True, timeout=10, check=False
            ).returncode
            != 0
            for target in targets
        )
        for name in ("inputs", "raw", "project", "config"):
            try:
                shutil.rmtree(self.work / name)
            except FileNotFoundError:
                pass
            except OSError as exc:
                errors.append(type(exc).__name__ + ":scratch-" + name)
        self.receipt["private_scratch_removed"] = all(
            not (self.work / name).exists() for name in ("inputs", "raw", "project", "config")
        )
        self.receipt["owned_anonymous_volumes"] = sorted(self.owned_volumes)
        self.receipt["cleanup_failures"] = errors
        self.receipt["disposable_resources_removed"] = False
        if errors or not self.receipt["owned_native_resources_removed"]:
            self.receipt["status"] = "FAILED"


def run(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    for relative, expected in FROZEN.items():
        if native.sha(native.ROOT / "hop" / relative) != expected:
            raise ValueError("Frozen source/replay/statistics SQL changed")
    if native.sha(args.backup) != args.backup_sha256:
        raise ValueError("Supplied clone archive differs")
    if args.candidate_sql[0].resolve() != native.ROOT / "hop/graph/sql/005_validation_worksets.sql":
        raise ValueError("Only canonical additive validation SQL005 is accepted")
    fixture = BorrowedFixture(args)
    path = fixture.work / "receipt.json"
    fixture.function_names = ["ingestion.source_graph_scoped_validation_issue"]
    fixture.receipt["frozen_sql_sha256"] = FROZEN
    fixture.receipt["launched_helper_sha256"] = native.sha(Path(__file__))
    shutil.copyfile(Path(__file__), fixture.work / "launched-helper.py")
    write_json(path, fixture.receipt)
    print(path, flush=True)
    try:
        fixture.boot_borrowed()
        fixture.apply_variant("candidate")
        installed_before = fixture.all_rows("all-before-native-installers")
        fixture.run("../../graph/install.hwf", "native-canonical-installer")
        fixture.run("../../graph/install_posting_dates.hwf", "native-posting-date-installer")
        if installed_before != fixture.all_rows("all-after-native-installers"):
            raise RuntimeError("Native installer replay changed protected table rows")
        fixture.receipt["native_installers_preserve_all_rows"] = True
        fixture.receipt["proof_before"] = fixture.assert_proof("initial-full-manifests")
        key = quote(args.run_id)
        fixture.receipt["expected_rows"] = json.loads(
            fixture.sql(
                "SELECT jsonb_build_object('entities',(SELECT count(*) "
                "FROM ingestion.graph_source_entities("
                + key
                + ")),'edges',(SELECT count(*) FROM ingestion.graph_source_edges("
                + key
                + ")),'dates',(SELECT count(*) FROM ingestion.graph_posting_ingestion_dates("
                + key
                + ")))",
                "expected-counts",
            )
        )
        fixture.execute_workflow("candidate", "candidate-prime")
        fixture.seed_inference_sentinel()
        graph = fixture.graph_snapshot("graph-prime")
        rows = fixture.all_rows("all-protected-before")
        fixture.receipt["protected_before"] = rows
        prime_changes = {
            name: {"before": installed_before[name], "after": rows[name]}
            for name in installed_before
            if installed_before[name] != rows[name]
        }
        if set(prime_changes) - {"ingestion.posting_ingestion_observation"}:
            raise RuntimeError("Native priming changed protected rows outside date observations")
        fixture.receipt["prime_operational_changes"] = prime_changes
        fixture.receipt["table_count"] = len(rows)
        fixture.apply_variant("baseline")
        try:
            fixture.execute_workflow("baseline", "baseline-bounded")
            fixture.receipt["baseline_status"] = "PASSED"
        except RuntimeError:
            log = (fixture.logs / "baseline-bounded.log").read_text()
            if "canceling statement due to statement timeout" not in log:
                raise
            fixture.receipt["baseline_status"] = "STATEMENT_TIMEOUT_CENSORED"
        fixture.apply_variant("candidate")
        fixture.execute_workflow("candidate", "candidate-warm")
        if graph != fixture.graph_snapshot("graph-final"):
            raise RuntimeError("Typed graph or inferred sentinel identity changed")
        if rows != fixture.all_rows("all-protected-after"):
            raise RuntimeError("Protected PostgreSQL rows changed outside replay timestamps")
        fixture.receipt["proof_after"] = fixture.assert_proof("final-full-manifests")
        if fixture.receipt["proof_before"] != fixture.receipt["proof_after"]:
            raise RuntimeError("Source proof values changed across native replay")
        if args.local_ndjson:
            fixture.fresh_compatibility(args.local_ndjson)
            if rows != fixture.all_rows("all-protected-after-fresh-sibling"):
                raise RuntimeError("Fresh sibling compatibility changed archived PostgreSQL rows")
        fixture.receipt["status"] = "PASSED_NATIVE_NARA_PENDING_BORROWED_CLEANUP"
    except BaseException as exc:
        fixture.receipt.update(status="FAILED", failure_type=type(exc).__name__)
        raise
    finally:
        fixture.close()
        fixture.receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(path, fixture.receipt)
        print(path, flush=True)
    return path


def seal_cleanup(path: Path) -> None:
    receipt = json.loads(path.read_text())
    if (
        receipt["kind"] != "BORROWED_NETWORK_NONE_COMPLETE_NARA_REPLAY"
        or not receipt["status"].startswith("PASSED_NATIVE_NARA")
        or not receipt.get("owned_native_resources_removed")
        or not receipt.get("private_scratch_removed")
        or receipt.get("cleanup_failures")
    ):
        raise RuntimeError("Measured native proof or owned cleanup did not pass")
    if (
        subprocess.run(
            ["docker", "inspect", receipt["borrowed_postgres"]],
            capture_output=True,
            timeout=10,
            check=False,
        ).returncode
        == 0
    ):
        raise RuntimeError("Clone owner has not yet removed borrowed PostgreSQL")
    for volume in receipt["borrowed_postgres_volumes"]:
        if (
            subprocess.run(
                ["docker", "volume", "inspect", volume],
                capture_output=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        ):
            raise RuntimeError("Clone owner has not yet removed borrowed PostgreSQL volume")
    receipt.update(
        status="PASSED_NATIVE_NARA_COMPLETE_CLEANUP",
        disposable_resources_removed=True,
        cleanup_deferred_to_clone_owner=False,
        borrowed_postgres_removed=True,
        cleanup_confirmed=True,
        cleanup_sealed_at=datetime.now(UTC).isoformat(),
    )
    write_json(path, receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--backup-sha256")
    parser.add_argument("--candidate-sql", type=Path)
    parser.add_argument("--seal-cleanup", type=Path)
    parser.add_argument("--local-ndjson", type=Path)
    args = parser.parse_args()
    if args.seal_cleanup:
        seal_cleanup(args.seal_cleanup)
        return
    if not all((args.container, args.backup, args.backup_sha256, args.candidate_sql)):
        parser.error("Exact borrowed container, archive/hash and candidate SQL required")
    args.candidate_sql = [args.candidate_sql]
    args.run_id = NARA_RUN
    args.baseline_dir = native.ROOT
    args.pair_order = "ab"
    args.sql_timeout_seconds = 60
    args.archived_inference_limit = 0
    run(args)


if __name__ == "__main__":
    main()
