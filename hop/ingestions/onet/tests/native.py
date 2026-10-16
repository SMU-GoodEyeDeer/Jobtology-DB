#!/usr/bin/env python3
"""Qualify catalogue-only native Hop in one local-image internal-network fixture.

Small source-backed fixtures prove replay, rollover/soft retirement, malformed
input, immutable evidence and namespace collision handling. The final native
load proves the complete pinned official catalogue supplied as a private bundle.
No production, source URL, HTTP or provider access occurs.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "hop/operations"))
import load_onet_catalogue as supervisor  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "onet_isolated_resources", ROOT / "hop/ingestions/jobkorea/tests/native.py")
assert SPEC and SPEC.loader
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)
REMOTE = resources.REMOTE


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def cypher_map(properties: dict[str, Any]) -> str:
    return "{" + ",".join("`" + key.replace("`", "``") + "`:" + json.dumps(value,
        ensure_ascii=False) for key, value in properties.items()) + "}"


class Fixture(resources.Fixture):
    def __init__(self, bundle: Path):
        self.bundle = bundle.resolve(strict=True)
        self.descriptor, self.inventory = supervisor.bundle_identity(self.bundle)
        super().__init__(self.bundle / "catalogue.json")
        new_work = self.work.with_name("onet-native-" + self.token)
        self.work.rename(new_work)
        self.work = new_work
        self.logs = self.work / "logs"
        self.prefix = "jobtology-onet-test-" + self.token
        self.network, self.pg, self.neo, self.hop = (
            self.prefix + suffix for suffix in ("-net", "-pg", "-neo", "-hop"))
        self.receipt.update(kind="ISOLATED_ONET_NATIVE_CATALOGUE", source_requests=0,
            provider_calls=0, posting_matching_calls=0,
            official_catalogue_sha256=self.descriptor["catalogue_sha256"],
            official_counts=self.descriptor["counts"],
            artifact_sha256={name: supervisor.identity(ROOT / "hop" / name)["sha256"]
                             for name in supervisor.artifacts()})

    def stage(self):
        super().stage()
        project = self.work / "project"
        shutil.copytree(ROOT / "hop/ingestions/onet", project / "ingestions/onet",
                        ignore=shutil.ignore_patterns("tools", "tests", "__pycache__", "*.pyc"))
        for kind in ("pipeline", "workflow"):
            relative = "metadata/" + kind + "-run-configuration/onet-local.json"
            shutil.copyfile(ROOT / "hop" / relative, project / relative)
        shutil.copytree(self.bundle, self.work / "inputs/official")

    def install(self):
        files = [ROOT / "docs/hop-migration/schema.sql",
                 ROOT / "docs/hop-migration/checks.sql",
                 ROOT / "docs/hop-migration/operations.sql"]
        files += sorted((ROOT / "hop/llm/sql").glob("*.sql"))
        files += [ROOT / "hop/retention/sql/001_retention.sql"]
        for index, file in enumerate(files):
            self.sql(file.read_text(), "dependency-install-" + str(index))
        self.run("install.hwf", "native-onet-install")
        self.run("install.hwf", "native-onet-install-replay")

    def run(self, filename: str, label: str, *, input_name: str = "official/catalogue.json",
            release_id: str | None = None, success: bool = True,
            expected_sha256: str | None = None, load_id: str | None = None):
        file = self.work / "inputs" / input_name
        if not file.exists() and not input_name.startswith("official/"):
            input_name = "official/" + input_name
            file = self.work / "inputs" / input_name
        parameters = dict(INPUT_FILE=REMOTE + "/inputs/" + input_name,
            EVIDENCE_ROOT=REMOTE + "/inputs/official",
            EXPECTED_INPUT_SHA256=expected_sha256 or supervisor.identity(file)["sha256"],
            RELEASE_ID=release_id or self.descriptor["release_id"],
            NEO4J_CONNECTION="jobtology-neo4j")
        if load_id is not None:
            parameters["ONET_LOAD_ID"] = load_id
        if filename == "replay_catalog.hwf":
            parameters = {key: parameters[key] for key in ("RELEASE_ID", "NEO4J_CONNECTION")}
        self.command(["docker", "exec", "-e", "HOP_CONFIG_FOLDER=" + REMOTE + "/config",
            "-e", "HOP_OPTIONS=-Xmx1024m", "-w", "/opt/hop", self.hop,
            "bash", "hop-run.sh", "-j", "jobkorea-test", "-r", "onet-local",
            "-f", REMOTE + "/project/ingestions/onet/" + filename,
            "-p", ",".join(key + "=" + str(value) for key, value in parameters.items()),
            "-l", "Basic"], label, success=success, timeout=1800)
        self.expect(True, label)

    def cypher(self, statement: str, label: str) -> str:
        return self.command(["docker", "exec", "-i", self.neo, "cypher-shell", "--format",
                             "plain"], label, statement)

    def graph_state(self, label: str, *, legacy_only: bool = False) -> str:
        outputs = []
        for kind in ("NODE", "REL"):
            query = supervisor.graph.snapshot_query(kind, "")
            entity = "n" if kind == "NODE" else "r"
            if legacy_only:
                query = query.replace("WHERE elementId(" + entity + ")>",
                    "WHERE NOT coalesce(" + entity + ".managed_by,'')="
                    "'jobtology-onet-catalog-v1' AND elementId(" + entity + ")>")
            outputs.append(self.cypher(query, label + "-" + kind.lower()))
        return "\n".join(outputs)

    def graph_archive(self, label: str) -> Path:
        path = self.work / (label + ".sqlite")
        with sqlite3.connect(path) as database:
            database.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,"
                             "PRIMARY KEY(kind,eid))")
            for kind in ("NODE", "REL"):
                raw = self.cypher(supervisor.graph.snapshot_query(kind, ""),
                                  label + "-" + kind.lower())
                for line in raw.splitlines()[1:]:
                    value = json.loads(line)
                    parts = supervisor.graph.unpack(value)
                    database.execute("INSERT INTO snapshot VALUES(?,?,?)", (kind, parts[0], value))
        return path

    def legacy_pg(self, label: str) -> str:
        names = json.loads(self.sql("SELECT coalesce(jsonb_agg(n.nspname||'.'||c.relname "
            "ORDER BY 1),'[]') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relkind IN('r','p') AND n.nspname IN('ingestion','enrichment','retention');",
            label + "-names"))
        table_hashes = ["SELECT " + quoted(name) + " name,count(*) count,"
            "md5(coalesce(string_agg(h,'' ORDER BY h),'')) digest FROM "
            "(SELECT md5(to_jsonb(t)::text) h FROM " + name + " t) q" for name in names]
        return self.sql("SELECT jsonb_build_object('rows',(SELECT jsonb_object_agg(name,"
            "jsonb_build_array(count,digest)) FROM (" + " UNION ALL ".join(table_hashes) +
            ") q),'functions',(SELECT jsonb_object_agg(p.oid::regprocedure::text,"
            "jsonb_build_array(to_jsonb(p),pg_get_functiondef(p.oid))) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN "
            "('ingestion','enrichment','retention') AND p.prokind='f'));", label)

    def subset(self, official: dict[str, Any], release_id: str) -> dict[str, Any]:
        terms = {term["term_id"]: term for term in official["terms"]}
        occupations = [term["term_id"] for term in official["terms"]
                       if term["term_kind"] == "OCCUPATION" and term["code"].endswith(".00")][:2]
        parents = {edge["child_id"]: edge["parent_id"] for edge in official["hierarchy"]}
        selected = set(occupations)
        for identity in occupations:
            while identity in parents:
                identity = parents[identity]
                selected.add(identity)
        payload = copy.deepcopy(official)
        payload["release_id"] = release_id
        payload["terms"] = [terms[key] for key in sorted(selected)]
        payload["hierarchy"] = [edge for edge in official["hierarchy"]
                                if edge["child_id"] in selected]
        return payload

    def payload_file(self, name: str, payload: dict[str, Any]) -> None:
        (self.work / "inputs/official" / name).write_text(encoded(payload))

    def checks(self):
        official = json.loads(self.input.read_text())
        self.expect(self.descriptor["counts"] == dict(terms=1596, hierarchy=1573,
            occupations=1016, groups=580), "official-full-counts")
        self.cypher("CREATE (a:entity:occupation {id:'urn:jobtology:ncs:legacy',name:'기존 직업',"
            "codes:['01','02'],flag:true})-[:LEGACY {id:'legacy-rel',weight:1}]->"
            "(b:entity:jobPosting {id:'urn:jobtology:jobkorea:legacy',title:'한글'});",
            "seed-legacy")
        old_pg = self.legacy_pg("legacy-pg-before")
        old_graph = self.graph_state("legacy-graph-before", legacy_only=True)
        small = self.subset(official, "onet-native-a")
        self.payload_file("small-a.json", small)
        self.run("load_catalog.hwf", "native-small-load", input_name="small-a.json",
                 release_id=small["release_id"])
        self.run("verify_catalog.hwf", "reject-missing-native-verify-token",
                 load_id="nonexistent-token", success=False)
        graph_a = self.graph_state("small-graph-before-replay")
        history_a = self.sql("SELECT to_jsonb(r) FROM classification.catalog_release r "
                            "WHERE release_id='onet-native-a';", "small-release-before-replay")
        self.run("load_catalog.hwf", "native-small-replay", input_name="small-a.json",
                 release_id=small["release_id"])
        self.expect(graph_a == self.graph_state("small-graph-after-replay"), "exact-graph-replay")
        self.expect(history_a == self.sql("SELECT to_jsonb(r) "
            "FROM classification.catalog_release r "
            "WHERE release_id='onet-native-a';", "small-release-after-replay"),
            "immutable-release-replay")
        bad = copy.deepcopy(small)
        bad["terms"][0]["preferred_label"] = "altered after pin"
        self.payload_file("changed-pin.json", bad)
        self.run("load_catalog.hwf", "reject-changed-release-pin", input_name="changed-pin.json",
                 release_id=small["release_id"], success=False)
        self.expect(graph_a == self.graph_state("changed-pin-graph-after"),
                    "changed-pin-failure-no-graph-write")
        bad = copy.deepcopy(small)
        bad["release_id"] = "onet-native-malformed"
        bad["terms"][0]["term_id"] = "urn:jobtology:ncs:forged"
        self.payload_file("malformed.json", bad)
        self.run("load_catalog.hwf", "reject-foreign-term-namespace", input_name="malformed.json",
                 release_id=bad["release_id"], success=False)
        self.expect(graph_a == self.graph_state("malformed-graph-after"),
                    "malformed-failure-no-graph-write")
        self.run("load_catalog.hwf", "reject-wrong-input-hash", input_name="small-a.json",
                 release_id=small["release_id"], expected_sha256="0" * 64, success=False)
        self.expect(graph_a == self.graph_state("wrong-hash-graph-after"),
                    "wrong-hash-failure-no-graph-write")
        evidence = self.work / "inputs/official" / official["sources"][0]["archive_path"]
        original_bytes = evidence.read_bytes()
        original_mode = evidence.stat().st_mode & 0o777
        evidence.chmod(0o600)
        try:
            evidence.write_bytes(original_bytes + b" ")
            self.run("load_catalog.hwf", "reject-tampered-source-evidence",
                     input_name="small-a.json", release_id=small["release_id"], success=False)
            self.expect(graph_a == self.graph_state("evidence-tamper-graph-after"),
                        "evidence-tamper-failure-no-graph-write")
        finally:
            evidence.write_bytes(original_bytes)
            evidence.chmod(original_mode)
        removed = next(term["term_id"] for term in reversed(small["terms"])
                       if term["term_kind"] == "OCCUPATION")
        second = copy.deepcopy(small)
        second["release_id"] = "onet-native-b"
        second["terms"] = [term for term in second["terms"] if term["term_id"] != removed]
        second["hierarchy"] = [edge for edge in second["hierarchy"] if edge["child_id"] != removed]
        self.payload_file("small-b.json", second)
        self.run("load_catalog.hwf", "native-rollover", input_name="small-b.json",
                 release_id=second["release_id"])
        retired = self.cypher("MATCH(n {id:" + json.dumps(removed) + "}) RETURN n.current;",
                              "retired-node")
        self.expect(len(retired.splitlines()) == 2 and retired.splitlines()[1].lower() == "false",
                    "removed-term-soft-retired")
        self.expect(history_a == self.sql("SELECT to_jsonb(r) "
            "FROM classification.catalog_release r "
            "WHERE release_id='onet-native-a';", "old-release-after-rollover"),
            "rollover-preserves-old-evidence")
        foreign = next(term["term_id"] for term in official["terms"]
                       if term["term_id"] not in {term["term_id"] for term in small["terms"]})
        self.cypher("CREATE(n:foreignSentinel {id:" + json.dumps(foreign) +
                    ",managed_by:'foreign',value:'preserve'});", "seed-foreign-reserved-id")
        collision_before = self.graph_state("collision-before")
        self.run("load_catalog.hwf", "reject-foreign-reserved-identity", success=False)
        self.expect(collision_before == self.graph_state("collision-after"),
                    "collision-preflight-before-all-graph-mutations")
        self.cypher("MATCH(n:foreignSentinel {id:" + json.dumps(foreign) +
                    "}) DELETE n;", "remove-owned-test-sentinel")
        planned_node = json.loads(self.sql("SELECT to_jsonb(n) FROM classification.graph_nodes(" +
            quoted(self.descriptor["release_id"]) + ") n WHERE node_id=" + quoted(foreign) + ";",
            "adversarial-planned-node"))
        self.cypher("CREATE(n" + ":".join(["", *planned_node["labels"]]) + ") SET n=" +
                    cypher_map(planned_node["properties"]) + ";", "seed-owned-planned-node")
        for case, change, restore in (
            ("extra-label", "SET n:InjectedFixtureLabel", "REMOVE n:InjectedFixtureLabel"),
            ("wrong-hash", "SET n.content_hash='" + "0" * 64 + "'",
             "SET n=" + cypher_map(planned_node["properties"])),
        ):
            match = "MATCH(n:entity {id:" + json.dumps(foreign) + "}) "
            self.cypher(match + change + ";", "seed-indexed-node-" + case)
            malformed_before = self.graph_state("indexed-node-before-" + case)
            self.run("load_catalog.hwf", "reject-indexed-owned-node-" + case, success=False)
            self.expect(malformed_before == self.graph_state("indexed-node-after-" + case),
                        "indexed-node-" + case + "-failure-before-mutation")
            self.cypher(match + restore + ";", "restore-indexed-node-" + case)
        planned_edge = json.loads(self.sql("SELECT to_jsonb(e) FROM classification.graph_edges(" +
            quoted(self.descriptor["release_id"]) + ") e WHERE edge_type='IN_SCHEME' AND start_id="
            + quoted(foreign) + ";", "adversarial-planned-edge"))
        alternate_end = next(term["term_id"] for term in small["terms"]
                             if term["term_kind"] == "OCCUPATION")
        for case in ("wrong-endpoint", "wrong-allowed-type", "wrong-scalar-type", "duplicate-id"):
            properties = copy.deepcopy(planned_edge["properties"])
            if case == "wrong-scalar-type":
                properties["source_version"] = 31
            target = alternate_end if case == "wrong-endpoint" else planned_edge["end_id"]
            edge_type = "BROADER" if case == "wrong-allowed-type" else "IN_SCHEME"
            created = []
            for index in range(2 if case == "duplicate-id" else 1):
                raw = self.cypher("MATCH(a:entity {id:" + json.dumps(planned_edge["start_id"]) +
                    "}),(b:entity {id:" + json.dumps(target) + "}) CREATE(a)-[r:" + edge_type +
                    "]->(b) SET r=" + cypher_map(properties) + " RETURN elementId(r);",
                    "seed-global-edge-" + case + "-" + str(index))
                created.append(json.loads(raw.splitlines()[1]))
            malformed_before = self.graph_state("global-edge-before-" + case)
            self.run("load_catalog.hwf", "reject-global-owned-edge-" + case, success=False)
            self.expect(malformed_before == self.graph_state("global-edge-after-" + case),
                        "global-edge-" + case + "-failure-before-mutation")
            for index, eid in enumerate(created):
                self.cypher("MATCH()-[r]->() WHERE elementId(r)=" + json.dumps(eid) + " DELETE r;",
                            "remove-own-global-edge-" + case + "-" + str(index))
        self.cypher("MATCH(n:entity {id:" + json.dumps(foreign) + "}) "
            "WHERE NOT EXISTS { MATCH(n)--() } DELETE n;", "remove-owned-planned-node")
        release_before = self.sql("SELECT to_jsonb(r) FROM classification.catalog_release r "
            "WHERE release_id=" + quoted(self.descriptor["release_id"]) + ";",
            "official-release-before-recovery")
        self.run("replay_catalog.hwf", "native-official-full-load")
        self.expect(release_before == self.sql("SELECT to_jsonb(r) "
            "FROM classification.catalog_release r WHERE release_id=" + quoted(
                self.descriptor["release_id"]) + ";", "official-release-after-recovery"),
            "exact-replay-workflow-recovers-without-reimport")
        official_graph = self.graph_state("official-graph-before-replay")
        self.run("replay_catalog.hwf", "native-official-full-replay")
        self.expect(official_graph == self.graph_state("official-graph-after-replay"),
                    "official-complete-graph-exact-replay")
        report = json.loads(self.sql("SELECT jsonb_build_object('release_id',c.release_id,"
            "'state',l.state,'current_nodes',l.current_nodes,'current_edges',l.current_edges,"
            "'expected_nodes',l.expected_nodes,'expected_edges',l.expected_edges) "
            "FROM classification.catalog_current c "
            "JOIN classification.graph_load l USING(load_id);",
            "official-current-state"))
        self.expect(report["release_id"] == self.descriptor["release_id"] and
            report["state"] == "VERIFIED" and report["current_nodes"] == 1597 and
            report["current_edges"] == 3169 and report["expected_nodes"] == 1597 and
            report["expected_edges"] == 3169, "official-pinned-verified-node-edge-counts")
        self.receipt["official_state"] = report
        normalized = supervisor.normalized_payload_sql(official)
        matches = self.sql("BEGIN READ ONLY; SET LOCAL timezone='UTC'; " + normalized +
            " SELECT value=(SELECT normalized_input FROM classification.catalog_release "
            "WHERE release_id=" + quoted(self.descriptor["release_id"]) + ") "
            "FROM normalized; COMMIT;", "normalized-input-recovery-guard")
        self.expect(matches == "t", "exact-read-only-normalization-matches-frozen-import")
        actual = self.graph_archive("official-typed-graph")
        load_id = self.sql("SELECT load_id FROM classification.catalog_current;",
                           "official-load-id")
        self.run("verify_catalog.hwf", "native-official-read-only-verification", load_id=load_id)
        self.expect(official_graph == self.graph_state("official-graph-after-read-only-verify"),
                    "read-only-native-verifier-preserves-complete-graph")
        original_database = supervisor.typed.PG_DATABASE
        try:
            supervisor.typed.PG_DATABASE = self.database
            self.receipt["independent_typed_graph"] = supervisor.verify_expected_graph(
                self.pg, actual, load_id, self.work)
        finally:
            supervisor.typed.PG_DATABASE = original_database
        self.expect(self.receipt["independent_typed_graph"] == dict(nodes=1597, edges=3169),
                    "independent-exact-typed-pg-graph-projection")
        self.expect(old_pg == self.legacy_pg("legacy-pg-after"), "legacy-pg-exact-preservation")
        self.expect(old_graph == self.graph_state("legacy-graph-after", legacy_only=True),
                    "legacy-typed-graph-exact-preservation")
        self.expect(self.sql("SELECT count(*) FROM retention.writer;", "writers-final") == "0",
                    "writer-lifecycle-cleanup")

    def close(self):
        super().close()
        (self.work / "receipt.json").chmod(0o400)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    fixture = Fixture(args.bundle_dir)
    try:
        fixture.boot()
        fixture.install()
        fixture.checks()
        fixture.receipt["status"] = "PASSED_ONET_NATIVE_CATALOGUE"
    except BaseException as error:
        fixture.receipt.update(status="FAILED", error_type=type(error).__name__,
                               error_message=str(error))
        raise
    finally:
        fixture.close()
        print(fixture.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
