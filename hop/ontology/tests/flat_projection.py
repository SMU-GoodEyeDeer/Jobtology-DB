"""Native flat-ontology preservation/replay in unique, network-none containers.

The fixture seeds its historical graph from the exact sealed PostgreSQL inventory;
the supported Hop workflows perform the migration and every subsequent replay.
No source, attachment, model or production endpoint is used.
"""

# Native SQL/Cypher strings remain whole for direct receipt comparison.
# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import run

KINDS = {
    "organization",
    "jobPosting",
    "occupation",
    "ncsClass",
    "ncsCompetency",
    "qualification",
    "examSession",
    "careerRank",
    "ncsUnitFamily",
    "conceptScheme",
}
RELEASE = "flat-catalog-old"
MIGRATIONS = ("028_flat_graph_projection.sql", "029_flat_catalog_compatibility.sql")


def literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def typed_value(value: object, key: str) -> str:
    """Use the same documented temporal keys, with independent Cypher encoding."""
    encoded = literal(value)
    if isinstance(value, str):
        if (
            (
                key in {"date_posted", "closing_date", "established_date", "earliest_start"}
                or key.startswith("dates.")
            )
            and len(value) == 10
            and value[4] == "-"
            and value[7] == "-"
        ):
            return f"date({encoded})"
        if (
            key.rsplit(".", 1)[-1]
            in {
                "created_at",
                "reviewed_at",
                "first_seen_at",
                "last_seen_at",
                "evaluated_at",
            }
            and "T" in value
        ):
            return f"datetime({encoded})"
    return encoded


def property_map(properties: dict) -> str:
    return (
        "{"
        + ",".join(
            "`" + key.replace("`", "``") + "`:" + typed_value(value, key)
            for key, value in properties.items()
            if value is not None
        )
        + "}"
    )


class Fixture:
    def __init__(self, work: Path, suffix: str):
        self.work = work
        self.pg = "jobtology-flat-" + suffix + "-pg"
        self.neo = "jobtology-flat-" + suffix + "-neo"
        self.hop = "jobtology-flat-" + suffix + "-hop"
        self.suffix = suffix
        run.PG = self.pg
        self.sql = run.sql
        self.q = run.q

    def cypher(self, query: str) -> str:
        return run.cmd(
            [
                "docker",
                "exec",
                "-i",
                self.neo,
                "cypher-shell",
                "--format",
                "plain",
            ],
            input=query + ";\n",
        )

    def truth(self, query: str) -> None:
        answer = self.cypher(query).splitlines()[-1].lower()
        assert answer == "true", (query, answer)

    def boot(self) -> None:
        for name in (self.pg, self.neo, self.hop):
            assert subprocess.run(["docker", "inspect", name], capture_output=True).returncode != 0
        run.cmd(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--name",
                self.pg,
                "--network",
                "none",
                "--hostname",
                "localhost",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=ontologytest",
                "postgres:18-alpine",
            ]
        )
        original_sql = run.sql

        def historical_sql(text: str) -> str:
            if (
                "CREATE TABLE IF NOT EXISTS ontology.flat_graph_projection" in text
                or "CREATE TABLE IF NOT EXISTS catalog.flat_catalog_approval" in text
            ):
                return ""
            return original_sql(text)

        run.sql = historical_sql
        try:
            run.boot()
        finally:
            run.sql = original_sql
        run.cmd(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--name",
                self.neo,
                "--network",
                "container:" + self.pg,
                "-e",
                "NEO4J_AUTH=none",
                "-e",
                "NEO4J_server_memory_heap_initial__size=512m",
                "-e",
                "NEO4J_server_memory_heap_max__size=512m",
                "-e",
                "NEO4J_server_memory_pagecache_size=256m",
                "neo4j:2026.06.0",
            ]
        )
        run.cmd(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--name",
                self.hop,
                "--network",
                "container:" + self.pg,
                "--entrypoint",
                "/bin/sleep",
                "apache/hop:latest",
                "infinity",
            ]
        )
        for _ in range(120):
            try:
                self.cypher("RETURN 1")
                break
            except RuntimeError:
                time.sleep(0.5)
        else:
            raise AssertionError("Disposable Neo4j failed to start")

    def stage(self) -> None:
        import native

        native.HOP = self.hop
        native.PG = self.pg
        native.WORK = self.work
        project = self.work / "project"
        if project.exists():
            shutil.rmtree(project)
        shutil.copytree(run.ROOT / "hop", project)
        (project / "metadata/rdbms").mkdir(exist_ok=True)
        (project / "metadata/neo4j-connection").mkdir(exist_ok=True)
        connection = {
            "name": "jobtology-postgres",
            "rdbms": {
                "POSTGRESQL": {
                    "pluginId": "POSTGRESQL",
                    "pluginName": "PostgreSQL",
                    "accessType": 0,
                    "hostname": "",
                    "databaseName": "",
                    "port": "5432",
                    "manualUrl": "jdbc:postgresql://127.0.0.1:5432/ontologytest",
                    "username": "postgres",
                    "password": "",
                    "sshTunnelEnabled": False,
                    "attributes": {
                        "SUPPORTS_BOOLEAN_DATA_TYPE": "Y",
                        "SUPPORTS_TIMESTAMP_DATA_TYPE": "Y",
                    },
                }
            },
        }
        (project / "metadata/rdbms/jobtology-postgres.json").write_text(json.dumps(connection))
        (project / "metadata/neo4j-connection/jobtology-neo4j.json").write_text(
            json.dumps(
                {
                    "name": "jobtology-neo4j",
                    "server": "127.0.0.1",
                    "databaseName": "neo4j",
                    "boltPort": "7687",
                    "username": "neo4j",
                    "password": "test-auth-disabled",
                    "automatic": False,
                    "routing": False,
                    "usingEncryption": False,
                    "manualUrls": ["bolt://127.0.0.1:7687"],
                    "connectionTimeout": "10000",
                    "maxTransactionRetryTime": "0",
                }
            )
        )
        config = self.work / "config"
        config.mkdir(exist_ok=True)
        (config / "hop-config.json").write_text(
            json.dumps(
                {
                    "projectsConfig": {
                        "enabled": True,
                        "projectMandatory": True,
                        "defaultProject": "ontology-test",
                        "projectConfigurations": [
                            {
                                "projectName": "ontology-test",
                                "projectHome": native.REMOTE + "/project",
                                "configFilename": "project-config.json",
                                "readOnly": False,
                            }
                        ],
                        "lifecycleEnvironments": [],
                        "projectLifecycles": [],
                    }
                }
            )
        )
        run.cmd(["docker", "exec", "-u", "root", self.hop, "mkdir", "-p", native.REMOTE])
        for path in (project, config):
            run.cmd(["docker", "cp", str(path), self.hop + ":" + native.REMOTE + "/"])
        run.cmd(["docker", "exec", "-u", "root", self.hop, "chown", "-R", "hop:hop", native.REMOTE])

    def workflow(self, file: str, params: dict, label: str, success: bool = True) -> None:
        import native

        native.run(file, params, label, success)

    def tables(self) -> dict[str, list[str]]:
        names = json.loads(
            self.sql("""SELECT jsonb_agg(format('%I.%I',n.nspname,c.relname) ORDER BY n.nspname,c.relname)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('ingestion','enrichment','attachment','ontology','catalog','retention')
            AND c.relkind='r'""")
        )
        return {
            name: json.loads(
                self.sql(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t)::text ORDER BY to_jsonb(t)::text),'[]') FROM "
                    + name
                    + " t"
                )
            )
            for name in names
        }

    def preserve(self, snapshot: dict[str, list[str]], exact: bool = True) -> None:
        for name, before in snapshot.items():
            after = json.loads(
                self.sql(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t)::text ORDER BY to_jsonb(t)::text),'[]') FROM "
                    + name
                    + " t"
                )
            )
            assert after == before if exact else set(before).issubset(after), name

    def exports(self) -> dict[str, str]:
        result = {}
        for name in (RELEASE, "review-fixture"):
            for version in (1, 2, 3):
                if name == RELEASE and version == 1:
                    self.sql_error(
                        f"SELECT line FROM ontology.export_jsonld_v1({self.q(name)},true)",
                        "INTERCHANGE_UNMAPPED_NODE_LABEL",
                    )
                    result[f"{name}-v{version}"] = "REFUSED_UNMAPPED_NODE_LABEL"
                    continue
                value = (
                    self.sql(
                        f"SELECT line FROM ontology.export_jsonld_v{version}({self.q(name)},true) ORDER BY line_no"
                    )
                    + "\n"
                )
                result[f"{name}-v{version}"] = hashlib.sha256(value.encode()).hexdigest()
        return result

    def seed_graph(self, release: str) -> None:
        queries = []
        nodes = json.loads(
            self.sql(
                f"SELECT jsonb_agg(n ORDER BY node_id) FROM ontology.graph_node n WHERE release_id={self.q(release)}"
            )
        )
        for node in nodes:
            labels = ":".join("`" + x + "`" for x in ["ontologyObject", *node["labels"]])
            props = node["properties"] | {
                "id": node["node_id"],
                "content_hash": node["content_hash"],
            }
            queries.append(f"CREATE (:{labels} {property_map(props)})")
        metadata = json.loads(
            self.sql(
                f"SELECT jsonb_build_object('release_id',release_id,'manifest_hash',manifest_hash,'data_as_of',manifest->>'data_as_of','name',release_id) FROM ontology.corpus_release WHERE release_id={self.q(release)}"
            )
        )
        queries.append(
            f"CREATE (:ontologyObject:corpusRelease {property_map(metadata | {'id': 'release/' + release})})"
        )
        edges = json.loads(
            self.sql(
                f"SELECT jsonb_agg(e ORDER BY edge_id) FROM ontology.graph_edge e WHERE release_id={self.q(release)}"
            )
        )
        for edge in edges:
            props = edge["properties"] | {
                "id": edge["edge_id"],
                "content_hash": edge["content_hash"],
                "release_id": release,
            }
            queries.append(
                f"MATCH (a:ontologyObject {{id:{literal(edge['subject_id'])}}}),(b:ontologyObject {{id:{literal(edge['object_id'])}}}) CREATE (a)-[:`{edge['predicate']}` {property_map(props)}]->(b)"
            )
        # Reuse one native client per bounded group rather than launching a JVM
        # for every small object in the synthetic inventory.
        for start in range(0, len(queries), 100):
            self.cypher(";\n".join(queries[start : start + 100]))

    def prepare(self) -> None:
        import claims

        original = claims.fixture

        def source_fixture():
            data = original()
            data["job_alio"] = [
                row
                | {
                    "headcount": 0,
                    "probe_empty_text": "",
                    "probe_array": [False, True],
                    "probe_empty_array": [],
                    "probe_null": None,
                    "probe_delimiters": "| %7C %25 %% 한글 🧪\nsecond\tline",
                    "probe_escaped_array": ["", "|", "%7C", "%25", "한글\n🧪"],
                    "probe_long_array": list(range(1003)),
                    "probe_float_array": [0, 1.25],
                    "probe_integer": 9223372036854775807,
                    "probe_number": 1.25,
                    "probe_remove": "remove on new selected release",
                    "probe.literal": "dotted key",
                    "probe": {"nested": "nested key"},
                }
                for row in data["job_alio"]
            ]
            return data

        claims.fixture = source_fixture
        try:
            claims.check()
        finally:
            claims.fixture = original
        self.sql("SELECT ontology.seal_graph('review-fixture')")
        self.sql("SELECT ontology.capture_posting_census_v1('fixture-job_alio')")
        choices = run.js({source: "fixture-" + source for source in original()})
        self.sql(
            f"SELECT ontology.prepare_release({self.q(RELEASE)},{choices}); SELECT ontology.assemble_sources({self.q(RELEASE)}); SELECT ontology.bind_observations_v1({self.q(RELEASE)}); SELECT ontology.prepare_catalog_source_v1({self.q(RELEASE)}); SELECT ontology.seal_catalog_source_v1({self.q(RELEASE)})"
        )
        kinds = set(
            json.loads(
                self.sql(
                    f"SELECT jsonb_agg(DISTINCT kind) FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id) WHERE release_id={self.q(RELEASE)}"
                )
            )
        )
        assert kinds == KINDS, kinds
        self.seed_graph(RELEASE)
        self.cypher(
            "CREATE (:jobPosting {id:'fixture-newer-source',name:'Newer source name',ingested_at:datetime('2026-10-12T00:00:00Z')}),(:Person {person_id:'fixture-private'})"
        )
        self.database = self.cypher("CALL db.info() YIELD id RETURN id").splitlines()[-1].strip('"')
        self.sql(
            f"INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,state,finished_at,node_count,edge_count) SELECT 'historical-fixture-load',{self.q(RELEASE)},{self.q(self.database)},manifest_hash,'VERIFIED',clock_timestamp(),(manifest->>'nodes')::bigint,(manifest->>'edges')::bigint FROM ontology.corpus_release WHERE release_id={self.q(RELEASE)}; UPDATE ontology.corpus_release SET graph_verified_at=clock_timestamp() WHERE release_id={self.q(RELEASE)}"
        )
        self.approval = self.sql(
            f"SELECT catalog.approve_catalog_release({self.q(RELEASE)},{self.q(self.database)},'synthetic-operator','Verified exact sealed fixture graph')"
        )
        self.capture_baseline()

    def capture_baseline(self) -> None:
        self.database = self.cypher("CALL db.info() YIELD id RETURN id").splitlines()[-1].strip('"')
        self.approval = self.sql("SELECT approval_id FROM catalog.catalog_active_release")
        baseline = {
            "database": self.database,
            "approval": self.approval,
            "tables": self.tables(),
            "exports": self.exports(),
            "context": self.sql("SELECT catalog.catalog_context_v1()"),
            "summary": self.sql("SELECT catalog.catalog_summary_v1()"),
            "source": self.cypher(
                "MATCH (n:jobPosting {id:'fixture-newer-source'}) RETURN properties(n),valueType(n.ingested_at)"
            ),
        }
        (self.work / "baseline.json").write_text(json.dumps(baseline, ensure_ascii=False))
        (self.work / "context.json").write_text(
            json.dumps(
                {
                    "suffix": self.suffix,
                    "work": str(self.work),
                    "pg": self.pg,
                    "neo": self.neo,
                    "hop": self.hop,
                }
            )
        )
        print("HISTORICAL FLAT FIXTURE PREPARED", self.work, flush=True)

    def check(self) -> None:
        baseline = json.loads((self.work / "baseline.json").read_text())
        self.database = baseline["database"]
        for name in MIGRATIONS:
            self.sql((run.ROOT / "hop/ontology/sql" / name).read_text())
        self.stage()
        # Repeated focused SQL installation never changes a historical row.
        self.preserve(baseline["tables"])
        assert self.exports() == baseline["exports"]
        # Use the operator's exact typed backing, bounded deletion and recovery
        # implementation. The native hook owns only these disposable resources.
        import flat_operator_native

        operator_receipt = flat_operator_native.check(self)
        self.check_initial(baseline)
        self.check_evidence(baseline)
        self.check_installer(baseline)
        self.check_future_approval(baseline)
        self.check_owned_keys(baseline)
        self.check_reviewed_preview(baseline)
        receipt = {
            "status": "PASSED",
            "revision_kinds": sorted(KINDS),
            "historical_tables": len(baseline["tables"]),
            "historical_exports_unchanged": True,
            "source_properties_unchanged": True,
            "operator_recovery": operator_receipt,
            "future_approval_and_stale_replay": True,
            "forged_owned_keys_refused_without_graph_changes": True,
            "reviewed_revision_bindings": True,
            "full_installer_replay": True,
            "graph_sql_sha256": hashlib.sha256(
                (run.ROOT / "hop/ontology/sql" / MIGRATIONS[0]).read_bytes()
            ).hexdigest(),
            "catalogue_sql_sha256": hashlib.sha256(
                (run.ROOT / "hop/ontology/sql" / MIGRATIONS[1]).read_bytes()
            ).hexdigest(),
            "graph_nodes_sha256": hashlib.sha256(
                (run.ROOT / "hop/ontology/graph_nodes.hpl").read_bytes()
            ).hexdigest(),
            "source_requests": 0,
            "paid_calls": 0,
            "serving_promotions": 0,
        }
        (self.work / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("NATIVE FLAT PROJECTION CHECKS PASSED", self.work, flush=True)

    def check_initial(self, baseline: dict) -> None:
        self.truth(
            "MATCH (n) RETURN count(CASE WHEN n:entityRevision OR any(label IN labels(n) WHERE label ENDS WITH 'Revision') THEN 1 END)=0"
        )
        self.truth(
            "MATCH (n:jobPosting {id:'entity/urn:jobtology:jobPosting:job_alio:001'}) RETURN n.headcount=0 AND valueType(n.headcount)='INTEGER NOT NULL' AND n.probe_empty_text='' AND n.probe_array=[false,true] AND n.probe_empty_array=[] AND n.probe_integer=9223372036854775807 AND n.probe_number=1.25 AND n.`probe~2literal`='dotted key' AND n.`probe.nested`='nested key' AND valueType(n.date_posted)='DATE NOT NULL'"
        )
        self.truth(
            "MATCH (n:jobPosting {id:'entity/urn:jobtology:jobPosting:job_alio:001'}) RETURN "
            "NOT 'probe_null' IN keys(n) AND n.probe_delimiters="
            + literal("| %7C %25 %% 한글 🧪\nsecond\tline")
            + " AND n.probe_escaped_array="
            + literal(["", "|", "%7C", "%25", "한글\n🧪"])
            + " AND n.probe_long_array=range(0,1002) AND n.probe_float_array=[0.0,1.25] "
            "AND valueType(n.probe_float_array)='LIST<FLOAT NOT NULL> NOT NULL'"
        )
        self.truth(
            "MATCH (n:occupation {id:'entity/urn:jobtology:occupation:ncs:20010201'}) RETURN n.code='ncs:20010201'"
        )
        assert self.sql("SELECT catalog.catalog_context_v1()") == baseline["context"]
        assert self.sql("SELECT catalog.catalog_summary_v1()") == baseline["summary"]
        assert (
            self.sql(
                f"SELECT catalog.approve_catalog_release({self.q(RELEASE)},{self.q(self.database)},'synthetic-operator','Replay')"
            )
            == baseline["approval"]
        )
        assert self.sql("SELECT count(*) FROM catalog.flat_catalog_approval") == "0"
        assert (
            self.cypher(
                "MATCH (n:jobPosting {id:'fixture-newer-source'}) RETURN properties(n),valueType(n.ingested_at)"
            )
            == baseline["source"]
        )
        self.preserve(baseline["tables"])
        assert self.exports() == baseline["exports"]
        self.workflow("load_release.hwf", {"RELEASE_ID": RELEASE}, "flat-native-replay")
        self.preserve(baseline["tables"])
        assert self.sql("SELECT catalog.catalog_context_v1()") == baseline["context"]
        root_hash = self.sql(
            f"SELECT manifest_hash FROM ontology.corpus_release WHERE release_id={self.q(RELEASE)}"
        )
        self.cypher(
            f"MATCH(r:corpusRelease {{id:{literal('release/' + RELEASE)}}}) SET r.manifest_hash='fixture-invalid-root'"
        )
        self.workflow(
            "load_release.hwf", {"RELEASE_ID": RELEASE}, "flat-existing-root-conflict", False
        )
        self.truth(
            f"MATCH(r:corpusRelease {{id:{literal('release/' + RELEASE)}}}) RETURN r.manifest_hash='fixture-invalid-root'"
        )
        self.sql_error("SELECT catalog.catalog_context_v1()", "FLAT_GRAPH_PROJECTION_NOT_READY")
        self.cypher(
            f"MATCH(r:corpusRelease {{id:{literal('release/' + RELEASE)}}}) SET r.manifest_hash={literal(root_hash)}"
        )
        self.workflow("load_release.hwf", {"RELEASE_ID": RELEASE}, "flat-root-conflict-recovery")
        self.cypher("CREATE (:UnmanagedOrphanRevision {fixture_only:'global revision refusal'})")
        self.workflow(
            "load_release.hwf", {"RELEASE_ID": RELEASE}, "flat-orphan-revision-refused", False
        )
        self.sql_error("SELECT catalog.catalog_context_v1()", "FLAT_GRAPH_PROJECTION_NOT_READY")
        self.cypher(
            "MATCH(n:UnmanagedOrphanRevision {fixture_only:'global revision refusal'}) DELETE n"
        )
        self.workflow("load_release.hwf", {"RELEASE_ID": RELEASE}, "flat-orphan-recovery")
        assert self.sql("SELECT catalog.catalog_context_v1()") == baseline["context"]
        assert self.sql("SELECT count(*) FROM ontology.active_release") == "0"
        self.sql_error(
            "SELECT ontology.begin_graph_load('"
            + RELEASE
            + "','"
            + self.database
            + "','retired-fixture')"
        )
        self.preserve(baseline["tables"])

    def check_evidence(self, baseline: dict) -> None:
        # Administrative fault injection is transactional and restricted to the
        # disposable database. It must not leave a changed inventory behind.
        self.sql_error(
            f"BEGIN; ALTER TABLE ontology.flat_graph_edge DISABLE TRIGGER USER; UPDATE ontology.flat_graph_edge SET properties=properties||'{{\"fixture_tamper\":true}}'::jsonb WHERE release_id={self.q(RELEASE)}; SELECT ontology.assert_flat_graph_inventory({self.q(RELEASE)}); COMMIT",
            "FLAT_GRAPH_INVENTORY_CHANGED",
        )
        choices = {source: "fixture-" + source for source in run.fixture()}
        self.sql_error(
            f"BEGIN; SELECT ontology.prepare_release('flat-missing-observations',{run.js(choices)}); SELECT ontology.assemble_sources('flat-missing-observations'); SELECT ontology.prepare_catalog_source_v1('flat-missing-observations'); COMMIT",
            "BIND_OBSERVATION_MEMBERSHIP_FIRST",
        )
        assert (
            self.sql(
                "SELECT count(*) FROM ontology.corpus_release WHERE release_id='flat-missing-observations'"
            )
            == "0"
        )
        self.preserve(baseline["tables"])
        assert self.sql("SELECT catalog.catalog_context_v1()") == baseline["context"]
        print("TAMPERED PROOF AND MISSING OBSERVATION REFUSAL PASSED", flush=True)

    def check_installer(self, baseline: dict) -> None:
        # Canonical replay must end with the new reader/writer guards while
        # preserving the existing batch-free source and reviewed-link contracts.
        # Interrupted historical replay cannot restore an old graph writer or
        # an original-layout reader while the flat contract is installed.
        for name in ("004_graph_inventory.sql", "020_catalog_source_graph.sql"):
            self.sql((run.ROOT / "hop/ontology/sql" / name).read_text())
            self.sql_error(
                f"SELECT ontology.begin_graph_load({self.q(RELEASE)},{self.q(self.database)},'interrupted-legacy-load')",
                "REVISION_GRAPH_WRITER_RETIRED",
            )
            self.truth(
                "MATCH(n) RETURN count(CASE WHEN any(label IN labels(n) WHERE label ENDS WITH 'Revision') THEN 1 END)=0"
            )
        for name in ("019_catalog_approval.sql", "024_sealed_catalog.sql"):
            self.sql((run.ROOT / "hop/ontology/sql" / name).read_text())
            self.sql_error(
                "SELECT catalog.catalog_context_v1()", "CATALOG_FLAT_COMPATIBILITY_REQUIRED"
            )
        self.preserve(baseline["tables"])
        self.workflow("install.hwf", {}, "flat-full-installer-replay")
        self.preserve(baseline["tables"])
        assert self.exports() == baseline["exports"]
        assert self.sql("SELECT catalog.catalog_context_v1()") == baseline["context"]
        self.sql_error(
            f"SELECT ontology.begin_graph_load({self.q(RELEASE)},{self.q(self.database)},'retired-after-install')",
            "REVISION_GRAPH_WRITER_RETIRED",
        )
        definition = self.sql(
            "SELECT pg_get_functiondef('ingestion.record_graph_export_v1(text)'::regprocedure)"
        )
        assert (
            "assert_source_graph_projection" in definition
            and "hop-graph-batchfree-v1" in definition
        )
        assert "jit TO 'off'" in definition
        definition = self.sql(
            "SELECT pg_get_functiondef('retention.protection(text,integer)'::regprocedure)"
        )
        assert "UNSUPPORTED_JOBKOREA_STORAGE_RETENTION" in definition
        assert "REVIEWED_LINK_PUBLICATION" in definition
        self.sql(
            "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN CREATE ROLE jobtology_catalog_reader; END IF; END $$; GRANT USAGE ON SCHEMA catalog,ontology TO jobtology_catalog_reader"
        )
        for name in MIGRATIONS:
            self.sql((run.ROOT / "hop/ontology/sql" / name).read_text())
        self.sql_error(
            "SET ROLE jobtology_catalog_reader; SELECT catalog.approve_flat_catalog_release('x','x','x','x')",
            "permission denied",
        )
        self.sql_error(
            "SET ROLE jobtology_catalog_reader; SELECT ontology.begin_flat_graph_load('x','x','x')",
            "permission denied",
        )
        self.sql_error(
            "SET ROLE jobtology_catalog_reader; INSERT INTO catalog.flat_catalog_active_release VALUES(true,1)",
            "permission denied",
        )
        for statement in (
            "ontology.seal_flat_graph_projection('x')",
            "ontology.stage_flat_graph_load('x',0,0,true)",
            "ontology.finish_flat_graph_load('x',0,0,true)",
            "ontology.fail_flat_graph_load('x')",
            "ontology.resume_flat_graph_load('x')",
        ):
            self.sql_error(
                "SET ROLE jobtology_catalog_reader; SELECT " + statement, "permission denied"
            )
        self.sql("REVOKE ALL ON SCHEMA ontology FROM jobtology_catalog_reader")
        self.sql((run.ROOT / "hop/ontology/sql/catalog_reader_grants.psql").read_text())
        assert (
            self.sql("SET ROLE jobtology_catalog_reader; SELECT catalog.catalog_context_v1()")
            == baseline["context"]
        )
        self.preserve(baseline["tables"])
        print("CANONICAL INSTALLER AND READER MUTATION DENIAL PASSED", flush=True)

    def check_future_approval(self, baseline: dict) -> None:
        new_run = "flat-new-job-alio"
        # Append a genuine new local input snapshot. Both paired representations
        # remove old keys, so a NULL detail cannot resurrect the old list value.
        self.sql(f"""INSERT INTO ingestion.run SELECT (jsonb_populate_record(NULL::ingestion.run,
          to_jsonb(r)||jsonb_build_object('run_id',{self.q(new_run)},'created_at',clock_timestamp(),'completed_at',clock_timestamp()))).*
          FROM ingestion.run r WHERE run_id='fixture-job_alio';
        INSERT INTO ingestion.partition SELECT (jsonb_populate_record(NULL::ingestion.partition,to_jsonb(r)||jsonb_build_object('run_id',{self.q(new_run)}))).*
          FROM ingestion.partition r WHERE run_id='fixture-job_alio';
        INSERT INTO ingestion.document SELECT (jsonb_populate_record(NULL::ingestion.document,to_jsonb(r)||jsonb_build_object('run_id',{self.q(new_run)},'raw_sha256',repeat('b',64),'retrieved_at',clock_timestamp()))).*
          FROM ingestion.document r WHERE run_id='fixture-job_alio';
        INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags)
          SELECT {self.q(new_run)},document_id,locator,source_record_id,
          (source_payload-ARRAY['probe_remove','closing_date'])||'{{"title":"New selected title","closing_date":null,"probe_new":"new selected metadata"}}'::jsonb,
          (normalized-ARRAY['probe_remove','closing_date'])||'{{"title":"New selected title","closing_date":null,"probe_new":"new selected metadata"}}'::jsonb,
          field_lineage,quality_flags FROM ingestion.record WHERE run_id='fixture-job_alio';
        UPDATE ingestion.run SET completed_at=clock_timestamp() WHERE run_id={self.q(new_run)};
        SELECT ontology.capture_posting_census_v1({self.q(new_run)});""")
        self.check_future_load(baseline)

    def check_future_load(self, baseline: dict) -> None:
        new_run = "flat-new-job-alio"
        new_release = "flat-catalog-new"
        choices = {source: "fixture-" + source for source in run.fixture()}
        choices["job_alio"] = new_run
        self.sql(
            f"SELECT ontology.prepare_release({self.q(new_release)},{run.js(choices)}); SELECT ontology.assemble_sources({self.q(new_release)}); SELECT ontology.bind_observations_v1({self.q(new_release)}); SELECT ontology.prepare_catalog_source_v1({self.q(new_release)}); SELECT ontology.seal_catalog_source_v1({self.q(new_release)})"
        )
        self.cypher(
            "MATCH(n:jobPosting {id:'entity/urn:jobtology:jobPosting:job_alio:001'}) SET n.probe_new='unowned native value'"
        )
        self.workflow(
            "load_release.hwf",
            {"RELEASE_ID": new_release},
            "flat-unowned-property-collision",
            False,
        )
        self.sql_error("SELECT catalog.catalog_context_v1()", "FLAT_GRAPH_PROJECTION_NOT_READY")
        self.truth(
            "MATCH(n:jobPosting {id:'entity/urn:jobtology:jobPosting:job_alio:001'}) RETURN n.probe_new='unowned native value'"
        )
        self.cypher(
            "MATCH(n:jobPosting {id:'entity/urn:jobtology:jobPosting:job_alio:001'}) REMOVE n.probe_new"
        )
        self.workflow(
            "load_release.hwf", {"RELEASE_ID": new_release}, "flat-future-load-before-approval"
        )
        self.sql_error("SELECT catalog.catalog_context_v1()", "FLAT_GRAPH_PROJECTION_NOT_READY")
        self.truth(
            "MATCH (n:jobPosting {id:'entity/urn:jobtology:jobPosting:job_alio:001'}) RETURN n.title='New selected title' AND n.probe_remove IS NULL AND n.closing_date IS NULL"
        )
        approval = self.sql(
            f"SELECT catalog.approve_catalog_release({self.q(new_release)},{self.q(self.database)},'fixture','Future flat projection approval')"
        )
        assert approval != baseline["approval"]
        assert (
            json.loads(self.sql("SELECT catalog.catalog_context_v1()"))["release_id"] == new_release
        )
        assert self.sql("SELECT count(*) FROM catalog.catalog_approval") == "1"
        assert (
            self.sql("SELECT approval_id FROM catalog.catalog_active_release")
            == baseline["approval"]
        )
        assert self.sql("SELECT count(*) FROM catalog.flat_catalog_approval") == "1"
        assert (
            self.sql(
                f"SELECT graph_verified_at IS NULL FROM ontology.corpus_release WHERE release_id={self.q(new_release)}"
            )
            == "t"
        )
        flat_before = self.cypher(
            "MATCH (n:ontologyObject) RETURN n.id,labels(n),properties(n) ORDER BY n.id"
        )
        self.workflow(
            "load_release.hwf", {"RELEASE_ID": RELEASE}, "flat-stale-release-refused", False
        )
        assert (
            self.cypher(
                "MATCH (n:ontologyObject) RETURN n.id,labels(n),properties(n) ORDER BY n.id"
            )
            == flat_before
        )
        self.workflow("load_release.hwf", {"RELEASE_ID": new_release}, "flat-future-replay")
        assert (
            self.sql(
                f"SELECT catalog.approve_catalog_release({self.q(new_release)},{self.q(self.database)},'fixture','Replay')"
            )
            == approval
        )
        assert self.sql("SELECT count(*) FROM catalog.flat_catalog_approval") == "1"
        self.preserve(baseline["tables"], exact=False)
        assert self.exports() == baseline["exports"]
        assert self.sql("SELECT count(*) FROM ontology.active_release") == "0"
        print("FUTURE APPROVAL, NULL REMOVAL AND STALE REPLAY PASSED", flush=True)

    def check_owned_keys(self, baseline: dict) -> None:
        """Graph metadata alone cannot authorize deletion of an unowned fact."""
        release = json.loads(self.sql("SELECT catalog.catalog_context_v1()"))["release_id"]
        target = "entity/urn:jobtology:jobPosting:job_alio:001"
        key = "fixture_unowned_sentinel"
        queries = (
            "MATCH(n) RETURN elementId(n),labels(n) ORDER BY elementId(n)",
            "MATCH(n) UNWIND keys(n) AS k RETURN elementId(n),k,valueType(n[k]),n[k] ORDER BY elementId(n),k",
            "MATCH(a)-[r]->(b) RETURN elementId(r),type(r),elementId(a),elementId(b) ORDER BY elementId(r)",
            "MATCH()-[r]->() UNWIND keys(r) AS k RETURN elementId(r),k,valueType(r[k]),r[k] ORDER BY elementId(r),k",
        )

        def snapshot() -> list[str]:
            return [self.cypher(query) for query in queries]

        before = snapshot()
        owned = json.loads(
            self.cypher(
                f"MATCH(n:jobPosting {{id:{literal(target)}}}) RETURN n.flat_owned_keys"
            ).splitlines()[-1]
        )
        assert key not in owned
        self.cypher(
            f"MATCH(n:jobPosting {{id:{literal(target)}}}) SET n.{key}='unowned scalar sentinel',n.flat_owned_keys={literal([*owned, key])}"
        )
        forged = snapshot()
        self.workflow(
            "load_release.hwf",
            {"RELEASE_ID": release},
            "flat-forged-owned-keys-refused",
            False,
        )
        assert snapshot() == forged, "Forged ownership changed native graph data"
        self.sql_error("SELECT catalog.catalog_context_v1()", "FLAT_GRAPH_PROJECTION_NOT_READY")
        self.cypher(
            f"MATCH(n:jobPosting {{id:{literal(target)}}}) SET n.flat_owned_keys={literal(owned)} REMOVE n.{key}"
        )
        assert snapshot() == before
        self.workflow(
            "load_release.hwf", {"RELEASE_ID": release}, "flat-owned-keys-recovery-replay"
        )
        assert snapshot() == before
        self.preserve(baseline["tables"], exact=False)
        assert self.exports() == baseline["exports"]
        (self.work / "owned-keys-proof.json").write_text(
            json.dumps(
                {
                    "status": "PASSED",
                    "forged_ownership_refused": True,
                    "all_native_ids_labels_property_types_values_unchanged": True,
                    "normal_replay_after_test_metadata_restore": True,
                    "graph_nodes_sha256": hashlib.sha256(
                        (run.ROOT / "hop/ontology/graph_nodes.hpl").read_bytes()
                    ).hexdigest(),
                    "source_requests": 0,
                    "paid_calls": 0,
                },
                indent=2,
            )
            + "\n"
        )
        print("FORGED OWNERSHIP REFUSAL AND GENUINE REPLAY PASSED", flush=True)

    def check_reviewed_preview(self, baseline: dict) -> None:
        # A reviewed preview uses a genuinely different disposable database.
        # The original source-only catalogue target remains unchanged.
        import claims

        reviewed = "flat-reviewed-two-sided"
        choices = {source: "fixture-" + source for source in run.fixture()}
        original = self.sql(
            "SELECT pg_get_functiondef('ontology.graph_edge_candidates(text)'::regprocedure)"
        )
        # A new, grounded legacy inventory may already own the provenance keys
        # used by flattening. Refuse it rather than overwriting their meaning.
        self.sql_error(
            f"""BEGIN;
         SELECT ontology.prepare_release('flat-conflicting-edge',{run.js(choices)});
         SELECT ontology.assemble_sources('flat-conflicting-edge');
         SELECT ontology.freeze_reviews('flat-conflicting-edge');
         SELECT ontology.assemble_claims('flat-conflicting-edge');
         CREATE OR REPLACE FUNCTION ontology.graph_edge_candidates(id text)
         RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
          SELECT * FROM ontology.graph_edge_candidates_base_v1(id)
          UNION ALL SELECT * FROM ontology.requirement_graph_edges_v1(id)
          UNION ALL SELECT 'revision/'||s.revision_id,'FIXTURE_PROVENANCE_COLLISION','revision/'||o.revision_id,
           '{{"origin_edge_id":"existing source meaning"}}'::jsonb
          FROM ontology.release_revision s JOIN ontology.release_revision o USING(release_id)
          WHERE s.release_id=id AND id='flat-conflicting-edge'
           AND s.entity_id='urn:jobtology:jobPosting:job_alio:001'
           AND o.entity_id='urn:jobtology:organization:alio:C001'
         $$;
         SELECT ontology.seal_graph('flat-conflicting-edge');
         SELECT ontology.seal_flat_graph_projection('flat-conflicting-edge'); COMMIT;
         """,
            "FLAT_EDGE_PROVENANCE_COLLISION",
        )
        assert (
            self.sql(
                "SELECT pg_get_functiondef('ontology.graph_edge_candidates(text)'::regprocedure)"
            )
            == original
        )
        self.sql(
            f"SELECT ontology.prepare_release({self.q(reviewed)},{run.js(choices)}); SELECT ontology.assemble_sources({self.q(reviewed)})"
        )
        claims.assemble(reviewed)
        original = self.sql(
            "SELECT pg_get_functiondef('ontology.graph_edge_candidates(text)'::regprocedure)"
        )
        try:
            self.sql(f"""CREATE OR REPLACE FUNCTION ontology.graph_edge_candidates(id text)
            RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
             SELECT * FROM ontology.graph_edge_candidates_base_v1(id)
             UNION ALL SELECT * FROM ontology.requirement_graph_edges_v1(id)
             UNION ALL SELECT 'revision/'||s.revision_id,'FIXTURE_REVISION_PAIR','revision/'||o.revision_id,
              jsonb_build_object('fixture_basis','selected PG revisions','ordered_flags',jsonb_build_array(false,true))
             FROM ontology.release_revision s JOIN ontology.release_revision o USING(release_id)
             WHERE s.release_id=id AND id={self.q(reviewed)}
              AND s.entity_id='urn:jobtology:jobPosting:job_alio:001'
              AND o.entity_id='urn:jobtology:organization:alio:C001'
            $$; SELECT ontology.seal_graph({self.q(reviewed)});""")
        finally:
            self.sql(original)
        main_neo = self.neo
        preview_neo = "jobtology-flat-" + self.suffix + "-reviewed"
        run.cmd(["docker", "stop", main_neo])
        try:
            run.cmd(
                [
                    "docker",
                    "run",
                    "-d",
                    "--pull",
                    "never",
                    "--name",
                    preview_neo,
                    "--network",
                    "container:" + self.pg,
                    "-e",
                    "NEO4J_AUTH=none",
                    "-e",
                    "NEO4J_server_memory_heap_initial__size=512m",
                    "-e",
                    "NEO4J_server_memory_heap_max__size=512m",
                    "-e",
                    "NEO4J_server_memory_pagecache_size=256m",
                    "neo4j:2026.06.0",
                ]
            )
            self.neo = preview_neo
            for _ in range(120):
                try:
                    self.cypher("RETURN 1")
                    break
                except RuntimeError:
                    time.sleep(0.5)
            else:
                raise AssertionError("Reviewed preview failed to start")
            import flat_operator_native

            shared_removal = flat_operator_native.check_shared_removal(self)
            assert shared_removal["status"] == "PASSED"
            self.workflow("load_release.hwf", {"RELEASE_ID": reviewed}, "flat-reviewed-preview")
            self.truth(
                "MATCH (a:jobPosting)-[r:FIXTURE_REVISION_PAIR]->(b:organization) RETURN count(r)=1 AND count(CASE WHEN r.subject_revision_id=a.selected_revision_id AND r.object_revision_id=b.selected_revision_id AND r.original_subject_id='revision/'+a.selected_revision_id AND r.original_object_id='revision/'+b.selected_revision_id AND r.origin_edge_id IS NOT NULL AND r.ordered_flags=[false,true] THEN 1 END)=1"
            )
            self.truth(
                "MATCH (m:competencyMappingClaim)-[r:MAPS_TARGET]->(n:ncsCompetency) RETURN count(r)=1 AND count(CASE WHEN r.object_revision_id=m.target_revision_id AND r.object_revision_id=n.selected_revision_id THEN 1 END)=1"
            )
            self.truth(
                "MATCH (n:jobPosting)-[r:HAS_DUTY]->(:dutyClaim) RETURN count(r)=1 AND count(CASE WHEN r.subject_revision_id=n.selected_revision_id THEN 1 END)=1"
            )
            self.truth(
                "MATCH (n:evidenceSpan) RETURN count(n)>0 AND count(CASE WHEN n.end_offset>n.start_offset THEN 1 END)=count(n)"
            )
            self.truth(
                "MATCH (n) RETURN count(CASE WHEN any(label IN labels(n) WHERE label ENDS WITH 'Revision') THEN 1 END)=0"
            )
            self.preserve(baseline["tables"], exact=False)
            assert self.exports() == baseline["exports"]
            assert self.sql("SELECT count(*) FROM ontology.active_release") == "0"
            print(
                "REVIEWED TWO-SIDED ENDPOINTS, DUTIES, EVIDENCE AND NCS MAPPING PASSED", flush=True
            )
        finally:
            self.neo = main_neo
            subprocess.run(["docker", "rm", "-fv", preview_neo], capture_output=True, check=False)
            run.cmd(["docker", "start", main_neo])

    def sql_error(self, query: str, contains: str | None = None) -> None:
        try:
            self.sql(query)
        except RuntimeError as error:
            if contains:
                assert contains in str(error), str(error)
            return
        raise AssertionError("Query unexpectedly accepted: " + query)

    def cleanup(self) -> None:
        for name in (self.hop, self.neo, self.pg):
            subprocess.run(["docker", "rm", "-fv", name], capture_output=True, check=False)
        assert all(
            subprocess.run(["docker", "inspect", name], capture_output=True).returncode
            for name in (self.hop, self.neo, self.pg)
        )
        (self.work / "cleanup.json").write_text(
            json.dumps(
                {
                    "status": "VERIFIED",
                    "containers_removed": [self.pg, self.neo, self.hop],
                    "network": "none",
                },
                indent=2,
            )
            + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", type=Path)
    options = parser.parse_args()
    if options.resume:
        context = json.loads((options.resume / "context.json").read_text())
        fixture = Fixture(options.resume, context["suffix"])
    else:
        suffix = uuid.uuid4().hex[:12]
        work = Path.home() / ".local/state/jobtology-hop" / ("flat-native-" + suffix)
        work.mkdir(mode=0o700)
        fixture = Fixture(work, suffix)
    try:
        if not options.resume:
            fixture.boot()
            fixture.prepare()
        if not options.prepare_only:
            fixture.check()
    finally:
        if not options.prepare_only and not os.environ.get("KEEP_ONTOLOGY_FLAT_FIXTURE"):
            fixture.cleanup()


if __name__ == "__main__":
    main()
