#!/usr/bin/env python3
"""Actual native detail workflow qualification, solely in disposable local images."""

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
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "hop/operations"))
import load_onet_details as details  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "onet_native_fixture", ROOT / "hop/ingestions/onet/tests/native.py"
)
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
REMOTE = base.REMOTE


class Fixture(base.Fixture):
    def __init__(self, bundle: Path, base_bundle: Path):
        self.detail_bundle = bundle.resolve(strict=True)
        self.detail_descriptor, self.detail_inventory = details.bundle_identity(self.detail_bundle)
        super().__init__(base_bundle)
        self.receipt.update(
            kind="ISOLATED_ONET_DETAILS_NATIVE",
            helper_sha256=details.helper_identity(),
            official_details_sha256=self.detail_descriptor["details_sha256"],
            artifact_sha256={
                name: details.identity(ROOT / "hop" / name)["sha256"]
                for name in details.artifacts()
            },
        )

    def stage(self):
        super().stage()
        shutil.copytree(
            ROOT / "hop/ingestions/onet_details",
            self.work / "project/ingestions/onet_details",
            ignore=shutil.ignore_patterns("tests", "tools", "__pycache__", "*.py"),
        )
        shutil.copytree(self.detail_bundle, self.work / "inputs/details")

    def install(self):
        super().install()
        self.run("load_catalog.hwf", "native-base-catalogue")
        self.detail_run("install.hwf", "native-detail-install")
        self.detail_run("install.hwf", "native-detail-install-replay")

    def detail_run(
        self,
        file,
        label,
        input_name="details.json",
        success=True,
        release_id=None,
        sha=None,
        load_id=None,
    ):
        local = self.work / "inputs/details" / input_name
        params = dict(
            INPUT_FILE=REMOTE + "/inputs/details/" + input_name,
            EVIDENCE_ROOT=REMOTE + "/inputs/details",
            EXPECTED_INPUT_SHA256=sha or details.identity(local)["sha256"],
            RELEASE_ID=release_id or self.detail_descriptor["release_id"],
            NEO4J_CONNECTION="jobtology-neo4j",
        )
        if load_id is not None:
            params["ONET_LOAD_ID"] = load_id
        self.command(
            [
                "docker",
                "exec",
                "-e",
                "HOP_CONFIG_FOLDER=" + REMOTE + "/config",
                "-e",
                "HOP_OPTIONS=-Xmx1024m",
                "-w",
                "/opt/hop",
                self.hop,
                "bash",
                "hop-run.sh",
                "-j",
                "jobkorea-test",
                "-r",
                "onet-local",
                "-f",
                REMOTE + "/project/ingestions/onet_details/" + file,
                "-p",
                ",".join(k + "=" + v for k, v in params.items()),
                "-l",
                "Basic",
            ],
            label,
            success=success,
            timeout=1800,
        )
        self.expect(True, label)

    def graph_pages(self, kind, label):
        cursor = ""
        page = 0
        while True:
            query = details.catalogue.graph.snapshot_query(kind, cursor)
            body, tail = query.rsplit("\nRETURN ", 1)
            expression, order = tail.split(" AS signature\n", 1)
            # cypher-shell plain output fails to escape existing backslashes.
            # Encode only the transport alphabet before its outer string printer.
            for original, encoded in [
                ("%", "%25"),
                ("\\", "%5C"),
                ('"', "%22"),
                ("\n", "%0A"),
                ("\r", "%0D"),
                ("\t", "%09"),
            ]:
                expression = (
                    "replace("
                    + expression
                    + ","
                    + json.dumps(original)
                    + ","
                    + json.dumps(encoded)
                    + ")"
                )
            raw = self.cypher(
                body + "\nRETURN " + expression + " AS signature\n" + order, label + "-" + str(page)
            )
            rows = [unquote(json.loads(line)) for line in raw.splitlines()[1:]]
            yield from rows
            if len(rows) < details.catalogue.graph.PAGE_SIZE:
                break
            cursor = details.catalogue.graph.unpack(rows[-1])[0]
            page += 1

    def graph_state(self, label, **unused):
        return "\n".join(
            kind + value
            for kind in ("NODE", "REL")
            for value in self.graph_pages(kind, label + "-" + kind.lower())
        )

    def graph_archive(self, label):
        path = self.work / (label + ".sqlite")
        with sqlite3.connect(path) as database:
            database.execute(
                "CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,PRIMARY KEY(kind,eid))"
            )
            for kind in ("NODE", "REL"):
                for value in self.graph_pages(kind, label + "-" + kind.lower()):
                    database.execute(
                        "INSERT INTO snapshot VALUES(?,?,?)",
                        (kind, details.catalogue.graph.unpack(value)[0], value),
                    )
        return path

    def import_sql(self, payload):
        raw = (self.detail_bundle / "base_catalogue.json").read_text()
        return (
            "SELECT onet_detail.import_onet_catalog("
            + base.quoted(json.dumps(payload, ensure_ascii=False))
            + "::jsonb,"
            + base.quoted(raw)
            + ");"
        )

    def rejects_sql(self, payload, code, label):
        self.command(
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
                self.database,
            ],
            label,
            self.import_sql(payload),
            success=False,
        )
        log = (self.logs / (label + ".log")).read_text()
        self.expect(code in log, label + "-expected-error")

    def checks(self):
        official = json.loads((self.detail_bundle / "details.json").read_text())
        self.cypher(
            "MATCH(o:entity:occupation {id:'urn:jobtology:onet:occupation:15-1252.00'}) "
            "CREATE(p:entity:jobPosting {id:'fixture-posting',title:'한글',"
            "dates:['2026-10-01'],flag:true}),"
            "(n:entity:occupation {id:'fixture-ncs',code:'0201'}) "
            "CREATE(p)-[:INFERRED_ONET_OCCUPATION {id:'fixture-onet-match',current:false,"
            "lifecycle:'STAGING',review_status:'UNREVIEWED'}]->(o) "
            "CREATE(p)-[:INFERRED_NCS_OCCUPATION {id:'fixture-ncs-match',current:false,"
            "lifecycle:'STAGING',confidence_status:'UNASSESSED'}]->(n);",
            "seed-source-and-existing-matches",
        )
        before_pg = details.pg_state(self.pg, self.database)
        before_graph = self.graph_archive("pre-detail-graph")
        # A valid source pin with one wrong endpoint fails after staging inserts;
        # the whole function statement rolls all evidence back atomically.
        bad = copy.deepcopy(official)
        bad["release_id"] = "onet-detail-invalid-endpoint"
        bad["edges"][0]["target_id"] = "urn:jobtology:onet-detail:element:absent"
        self.rejects_sql(bad, "ONET_DETAILS_INVALID_ENDPOINT", "reject-invalid-endpoint")
        self.expect(
            self.sql("SELECT count(*) FROM onet_detail.catalog_release;", "atomic-release-count")
            == "0",
            "atomic-import-no-release",
        )
        self.expect(
            self.sql("SELECT count(*) FROM onet_detail.node;", "atomic-node-count") == "0",
            "atomic-import-no-node",
        )
        bad = copy.deepcopy(official)
        bad["nodes"][0]["id"] = "urn:jobtology:ncs:foreign"
        self.rejects_sql(bad, "ONET_DETAILS_INVALID_NODE", "reject-foreign-pg-node")
        self.detail_run("load_details.hwf", "reject-wrong-input-sha", sha="0" * 64, success=False)
        self.expect(
            self.sql("SELECT count(*) FROM onet_detail.catalog_release;", "wrong-sha-count") == "0",
            "wrong-sha-before-import",
        )
        # Whole-namespace foreign collision must reject before every graph write.
        collision = official["nodes"][0]["id"]
        self.cypher(
            "CREATE(:foreignSentinel {id:"
            + json.dumps(collision)
            + ',managed_by:"foreign",value:"preserve"});',
            "seed-foreign-detail",
        )
        collision_before = self.graph_state("collision-before")
        self.detail_run("load_details.hwf", "reject-foreign-graph-node", success=False)
        self.expect(
            collision_before == self.graph_state("collision-after"),
            "foreign-preflight-no-graph-mutation",
        )
        self.cypher(
            "MATCH(n:foreignSentinel {id:" + json.dumps(collision) + "}) DELETE n;",
            "remove-own-sentinel",
        )
        self.detail_run("load_details.hwf", "native-official-details-load")
        first = self.graph_state("details-before-replay")
        history = self.sql(
            "SELECT to_jsonb(r) FROM onet_detail.catalog_release r;", "release-before-replay"
        )
        self.detail_run("load_details.hwf", "native-official-details-replay")
        self.expect(first == self.graph_state("details-after-replay"), "exact-native-detail-replay")
        self.expect(
            history
            == self.sql(
                "SELECT to_jsonb(r) FROM onet_detail.catalog_release r;", "release-after-replay"
            ),
            "immutable-evidence-replay",
        )
        bad = copy.deepcopy(official)
        bad["nodes"][0]["properties"]["name"] = "changed after freeze"
        file = self.work / "inputs/details/changed.json"
        file.write_text(json.dumps(bad))
        self.detail_run(
            "load_details.hwf",
            "reject-changed-release-pin",
            input_name="changed.json",
            success=False,
        )
        self.expect(
            first == self.graph_state("after-rejected-changed-release"),
            "changed-release-no-graph-mutation",
        )
        # Native verifier detects exact endpoint mutations without rewriting them.
        occupation = next(
            e["source_id"]
            for e in official["edges"]
            if e["source_id"].startswith("urn:jobtology:onet:occupation:")
        )
        self.cypher(
            "MATCH(n:entity {id:" + json.dumps(occupation) + '}) SET n.fixture_extra="injected";',
            "mutate-own-fixture-occupation",
        )
        verified_load = self.sql(
            "SELECT load_id FROM onet_detail.catalog_current;", "verified-detail-token"
        )
        mutated = self.graph_state("mutated-occupation-before")
        self.detail_run(
            "verify_details.hwf",
            "read-only-reject-mutated-occupation",
            success=False,
            load_id=verified_load,
        )
        self.detail_run("replay_details.hwf", "reject-mutated-existing-occupation", success=False)
        self.expect(
            mutated == self.graph_state("mutated-occupation-after"),
            "occupation-failure-no-graph-mutation",
        )
        self.cypher(
            "MATCH(n:entity {id:" + json.dumps(occupation) + "}) REMOVE n.fixture_extra;",
            "restore-own-fixture-occupation",
        )
        base_load = self.sql(
            "SELECT load_id FROM classification.catalog_current;", "base-current-token"
        )
        self.run("verify_catalog.hwf", "catalogue-read-only-compatibility", load_id=base_load)
        planned = json.loads(
            self.sql(
                "SELECT to_jsonb(e) FROM onet_detail.graph_load_edge e "
                "WHERE load_id=(SELECT load_id FROM onet_detail.catalog_current) "
                "ORDER BY edge_id LIMIT 1;",
                "collision-planned-edge",
            )
        )
        alternate = next(
            n["id"]
            for n in official["nodes"]
            if n["type"] == "ELEMENT" and n["id"] != planned["end_id"]
        )

        def recreate(edge_type, target, properties, count=1):
            self.cypher(
                "MATCH()-[r]->() WHERE r.id=" + json.dumps(planned["edge_id"]) + " DELETE r;",
                "remove-own-collision-edge",
            )
            for index in range(count):
                self.cypher(
                    "MATCH(a:entity {id:" + json.dumps(planned["start_id"]) + "}),"
                    "(b:entity {id:"
                    + json.dumps(target)
                    + "}) CREATE(a)-[r:"
                    + edge_type
                    + "]->(b) SET r="
                    + base.cypher_map(properties)
                    + ";",
                    "seed-owned-collision-" + str(index),
                )

        for case in (
            "wrong-allowed-type",
            "wrong-endpoint",
            "extra-property",
            "wrong-scalar-type",
            "duplicate-id",
        ):
            properties = copy.deepcopy(planned["properties"])
            if case == "extra-property":
                properties["fixture_extra"] = "preserve this failure"
            if case == "wrong-scalar-type":
                properties["data_value"] = str(properties["data_value"])
            recreate(
                "ONET_TRANSFERABLE_SKILL" if case == "wrong-allowed-type" else planned["edge_type"],
                alternate if case == "wrong-endpoint" else planned["end_id"],
                properties,
                2 if case == "duplicate-id" else 1,
            )
            before = self.graph_state("owned-" + case + "-before")
            self.detail_run("replay_details.hwf", "reject-owned-" + case, success=False)
            self.expect(
                before == self.graph_state("owned-" + case + "-after"),
                case + "-rejected-before-graph-mutation",
            )
            recreate(planned["edge_type"], planned["end_id"], planned["properties"])
        after_graph = self.graph_archive("post-detail-graph")
        self.receipt["graph_preservation"] = details.require_graph_preserved(
            before_graph, after_graph
        )
        self.expect(
            before_pg == details.pg_state(self.pg, self.database), "all-existing-pg-preserved"
        )
        load_id = self.sql(
            "SELECT load_id FROM onet_detail.catalog_current;", "detail-current-load"
        )
        original = details.catalogue.typed.PG_DATABASE
        try:
            details.catalogue.typed.PG_DATABASE = self.database
            self.receipt["independent_expected_graph"] = details.verify_expected_graph(
                self.pg, after_graph, load_id, self.work
            )
        finally:
            details.catalogue.typed.PG_DATABASE = original
        self.expect(
            self.receipt["independent_expected_graph"]
            == dict(
                nodes=self.detail_descriptor["node_count"],
                edges=self.detail_descriptor["edge_count"],
            ),
            "all-typed-properties-and-endpoints",
        )
        self.expect(
            self.sql("SELECT count(*) FROM retention.writer;", "final-writers") == "0",
            "writer-cleanup",
        )
        self.command(
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
                self.database,
            ],
            "reject-evidence-update",
            "UPDATE onet_detail.node SET type='SOFTWARE';",
            success=False,
        )
        self.expect(
            "IMMUTABLE" in (self.logs / "reject-evidence-update.log").read_text(),
            "immutable-pg-evidence",
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle-dir", type=Path, required=True)
    p.add_argument("--base-bundle-dir", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    f = Fixture(args.bundle_dir, args.base_bundle_dir)
    try:
        f.boot()
        f.install()
        f.checks()
        f.receipt["status"] = "PASSED_ONET_DETAILS_NATIVE"
    except BaseException as error:
        f.receipt.update(status="FAILED", error_type=type(error).__name__, error_message=str(error))
        raise
    finally:
        f.close()
        print(f.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
