"""Native owner-grouped property correctness and controlled archived-input A/B.

Uses only three uniquely named network-none fixture containers. The flat
fixture first proves relevant workflows, source hashes, ownership, preservation
and replay. The separate benchmark schema then isolates property passes on
locally archived inventories; its token is never a production graph attestation.
"""

# Keep native SQL/Cypher statements intact for direct receipt comparison.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import itertools
import json
import random
import re
import time
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

import flat_projection
import native
import run

PARTS = ("node_scalars", "node_arrays", "edge_scalars", "edge_arrays")
SCHEMA = "owner_property_fixture"


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def literal(value: object) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                "`" + key.replace("`", "``") + "`:" + literal(item) for key, item in value.items()
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(literal(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def typed_properties(properties: dict) -> str:
    """Independent oracle, including temporal arrays and numeric promotion."""

    def encode(value: object, key: str) -> str:
        if isinstance(value, list):
            floating = any(isinstance(x, float) and not x.is_integer() for x in value)
            return (
                "["
                + ",".join(
                    str(float(x))
                    if floating and isinstance(x, (int, float))
                    else flat_projection.typed_value(x, key)
                    for x in value
                )
                + "]"
            )
        return flat_projection.typed_value(value, key)

    return (
        "{"
        + ",".join(
            "`" + key.replace("`", "``") + "`:" + encode(value, key)
            for key, value in properties.items()
            if value is not None
        )
        + "}"
    )


class PropertyFixture:
    def __init__(
        self, fixture: flat_projection.Fixture, baseline: Path, release: str | None = None
    ):
        self.fixture, self.work, self.baseline = fixture, fixture.work, baseline
        self.release = release or fixture.sql(
            "SELECT release_id FROM ontology.flat_graph_current WHERE database_id="
            + run.q(fixture.database)
        )
        self.token = "owner-property-fixture-" + uuid.uuid4().hex
        fixture.sql(
            "SELECT ontology.begin_flat_graph_load("
            + ",".join(run.q(x) for x in (self.release, fixture.database, self.token))
            + ")"
        )
        self.receipt: dict = {"cases": [], "timings": []}

    def install(self, nodes: list[dict], edges: list[dict]) -> None:
        f = self.fixture
        f.sql(
            "CREATE SCHEMA "
            + SCHEMA
            + "; CREATE TABLE "
            + SCHEMA
            + ".flat_graph_node (LIKE ontology.flat_graph_node INCLUDING DEFAULTS); "
            "CREATE TABLE "
            + SCHEMA
            + ".flat_graph_edge (LIKE ontology.flat_graph_edge INCLUDING DEFAULTS); "
            "CREATE UNIQUE INDEX ON " + SCHEMA + ".flat_graph_node(release_id,node_id); "
            "CREATE UNIQUE INDEX ON " + SCHEMA + ".flat_graph_edge(release_id,edge_id)"
        )
        migration = (run.ROOT / "hop/ontology/sql/028_flat_graph_projection.sql").read_text()
        definition = migration.split("CREATE OR REPLACE VIEW ontology.flat_graph_property AS", 1)[1]
        definition = definition.split(
            "CREATE OR REPLACE VIEW ontology.flat_graph_legacy_property AS", 1
        )[0]
        f.sql(
            "CREATE VIEW "
            + SCHEMA
            + ".flat_graph_property AS"
            + definition.replace("ontology.flat_graph_node", SCHEMA + ".flat_graph_node").replace(
                "ontology.flat_graph_edge", SCHEMA + ".flat_graph_edge"
            )
        )
        for kind, objects in (("node", nodes), ("edge", edges)):
            rows = [item | {"release_id": self.release} for item in objects]
            # COPY contains source data only in stdin/private receipts.
            import io

            data = io.StringIO()
            writer = csv.writer(data, lineterminator="\n")
            for item in rows:
                writer.writerow([json.dumps(item, ensure_ascii=False)])
            f.sql(
                "CREATE TEMP TABLE fixture_seed(payload jsonb); COPY fixture_seed FROM STDIN WITH CSV;\n"
                + data.getvalue()
                + "\\.\nINSERT INTO "
                + SCHEMA
                + ".flat_graph_"
                + kind
                + " SELECT (jsonb_populate_record(NULL::"
                + SCHEMA
                + ".flat_graph_"
                + kind
                + ",payload)).* FROM fixture_seed; ANALYZE "
                + SCHEMA
                + ".flat_graph_"
                + kind
            )
        self.nodes, self.edges = nodes, edges
        # The earlier complete preservation fixture has finished. Only this
        # disposable graph is reset for the independent property benchmark.
        f.cypher("MATCH(n) DETACH DELETE n")
        # Standalone property replay must retain the production workflow's
        # uniqueness/index precondition, including both endpoint index seeks.
        f.cypher(
            "CREATE CONSTRAINT jobtology_ontology_object_id IF NOT EXISTS "
            "FOR(n:ontologyObject) REQUIRE n.id IS UNIQUE; CALL db.awaitIndexes()"
        )
        statements = []
        for start in range(0, len(nodes), 500):
            items = nodes[start : start + 500]
            statements.append(
                "UNWIND ["
                + ",".join(
                    "{id:"
                    + literal(n["node_id"])
                    + ",hash:"
                    + literal(n["content_hash"])
                    + ",props:"
                    + typed_properties(n["properties"])
                    + "}"
                    for n in items
                )
                + "] AS row CREATE(n:ontologyObject {id:row.id,content_hash:row.hash}) SET n+=row.props"
            )
        endpoints = {e[key] for e in edges for key in ("subject_id", "object_id")}
        missing = sorted(endpoints - {n["node_id"] for n in nodes})
        if missing:
            statements.append(
                "UNWIND " + literal(missing) + " AS id MERGE(:ontologyObject {id:id})"
            )
        for start in range(0, len(edges), 500):
            items = edges[start : start + 500]
            statements.append(
                "UNWIND ["
                + ",".join(
                    "{id:"
                    + literal(e["edge_id"])
                    + ",hash:"
                    + literal(e["content_hash"])
                    + ",subject:"
                    + literal(e["subject_id"])
                    + ",object:"
                    + literal(e["object_id"])
                    + ",predicate:"
                    + literal(e["predicate"])
                    + ",props:"
                    + typed_properties(e["properties"])
                    + "}"
                    for e in items
                )
                + "] AS row MATCH(a:ontologyObject {id:row.subject}) MATCH(b:ontologyObject {id:row.object}) "
                "CREATE(a)-[e:$(row.predicate) {id:row.id,content_hash:row.hash,release_id:"
                + literal(self.release)
                + "}]->(b) SET e+=row.props"
            )
        for start in range(0, len(statements), 10):
            f.cypher(";\n".join(statements[start : start + 10]))
        self.expected = self.snapshot()
        (self.work / "property-oracle-sha256.json").write_text(
            json.dumps(self.expected, indent=2) + "\n"
        )
        for variant, base in (("baseline", self.baseline), ("candidate", run.ROOT)):
            for prefix in ("write_", "verify_"):
                for part in PARTS:
                    original = base / "hop/ontology" / (prefix + part + ".hpl")
                    tree = E.parse(original)
                    self.patch_sql(tree)
                    tree.find(
                        "transform[name='Load token']/fields/field/variable"
                    ).text = self.token
                    tree.find(
                        "transform[type='Neo4jCypherOutput']/connection"
                    ).text = "jobtology-neo4j"
                    path = self.work / "project/ontology" / (variant + "_" + prefix + part + ".hpl")
                    tree.write(path, encoding="UTF-8", xml_declaration=True)
            self.workflow(variant)
        run.cmd(
            [
                "docker",
                "cp",
                str(self.work / "project/ontology"),
                f.hop + ":" + native.REMOTE + "/project/",
            ]
        )
        run.cmd(
            [
                "docker",
                "exec",
                "-u",
                "root",
                f.hop,
                "chown",
                "-R",
                "hop:hop",
                native.REMOTE + "/project/ontology",
            ]
        )
        self.receipt["inventory"] = json.loads(
            f.sql(
                "SELECT jsonb_build_object('nodes',(SELECT count(*) FROM "
                + SCHEMA
                + ".flat_graph_node),"
                "'edges',(SELECT count(*) FROM " + SCHEMA + ".flat_graph_edge),"
                "'property_rows',(SELECT count(*) FROM " + SCHEMA + ".flat_graph_property),"
                "'owner_pass_rows',(SELECT count(*) FROM (SELECT DISTINCT owner_type,owner_id,is_array FROM "
                + SCHEMA
                + ".flat_graph_property) x))"
            )
        )

    @staticmethod
    def patch_sql(tree: E.ElementTree) -> None:
        for sql in tree.findall("transform/sql"):
            sql.text = (
                sql.text.replace("ontology.flat_graph_property", SCHEMA + ".flat_graph_property")
                .replace("ontology.flat_graph_node", SCHEMA + ".flat_graph_node")
                .replace("ontology.flat_graph_edge", SCHEMA + ".flat_graph_edge")
            )

    def workflow(self, variant: str) -> None:
        tree = E.parse(run.ROOT / "hop/ontology/load_release.hwf")
        root = tree.getroot()
        actions, hops = root.find("actions"), root.find("hops")
        steps = []
        for action in list(actions):
            if action.findtext("type") == "PIPELINE":
                name = Path(action.findtext("filename", "")).name
                if (
                    name.startswith(("write_", "verify_"))
                    and name.removesuffix(".hpl").removeprefix("write_").removeprefix("verify_")
                    in PARTS
                ):
                    action.find("filename").text = (
                        "${PROJECT_HOME}/ontology/" + variant + "_" + name
                    )
                    steps.append(action.findtext("name"))
                else:
                    actions.remove(action)
        hops.clear()
        for previous, following in zip(["Start", *steps], [*steps, "Success"], strict=True):
            hop = E.SubElement(hops, "hop")
            for key, value in {
                "from": previous,
                "to": following,
                "enabled": "Y",
                "evaluation": "Y",
                "unconditional": "Y" if previous == "Start" else "N",
            }.items():
                E.SubElement(hop, key).text = value
        for step in steps:
            hop = E.SubElement(hops, "hop")
            for key, value in {
                "from": step,
                "to": "Abort",
                "enabled": "Y",
                "evaluation": "N",
                "unconditional": "N",
            }.items():
                E.SubElement(hop, key).text = value
        tree.write(
            self.work / "project/ontology" / (variant + "_properties.hwf"),
            encoding="UTF-8",
            xml_declaration=True,
        )

    def snapshot(self) -> dict:
        f = self.fixture
        result = {}
        for name, query in (
            (
                "nodes",
                "MATCH(n:ontologyObject) UNWIND keys(n) AS k RETURN n.id,k,valueType(n[k]),n[k] ORDER BY n.id,k",
            ),
            (
                "edges",
                "MATCH(a)-[e]->(b) UNWIND keys(e) AS k RETURN e.id,a.id,type(e),b.id,k,valueType(e[k]),e[k] ORDER BY e.id,k",
            ),
        ):
            value = f.cypher(query)
            result[name] = hashlib.sha256(value.encode()).hexdigest()
        return result

    def operation(self, part: str, reading: bool = True, mutate=None) -> bool:
        path = (
            self.work
            / "project/ontology"
            / ("candidate_" + ("verify_" if reading else "write_") + part + ".hpl")
        )
        tree = E.parse(path)
        sql = tree.findtext("transform[name='Expected properties']/sql").replace(
            "?", run.q(self.token)
        )
        sql = (
            "SELECT coalesce(jsonb_agg(t),'[]') FROM ("
            + sql
            + ") t WHERE owner_id LIKE 'owner-group-fixture%'"
        )
        rows = json.loads(self.fixture.sql(sql))
        if mutate:
            rows = mutate(copy.deepcopy(rows))
        cypher = tree.findtext("transform[name='Property operation']/cypher")
        result = self.fixture.cypher(":param rows => " + literal(rows) + "\n" + cypher)
        answer = result.splitlines()[-1].lower()
        assert answer in {"true", "false"}, result
        return answer == "true"

    def cases(self) -> None:
        f = self.fixture
        target = "owner-group-fixture-node"
        for part in PARTS:
            assert self.operation(part), part
        self.receipt["cases"].append(
            "all scalar/array node/edge values and types match independent oracle"
        )
        probes = [
            (
                "node_arrays",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.long_array=[0,1,2]",
                False,
                True,
                "typed immutable array prefix completes",
            ),
            (
                "node_arrays",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.long_array=[0,99]",
                False,
                False,
                "conflicting immutable array prefix refused",
            ),
            (
                "node_arrays",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.long_array=[0.0,1.0]",
                False,
                False,
                "numeric-equal wrong-type immutable prefix refused",
            ),
            (
                "node_arrays",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.long_array=range(0,1003)",
                False,
                False,
                "longer immutable array refused",
            ),
            (
                "node_arrays",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.long_array='wrong scalar'",
                False,
                False,
                "array/scalar type collision refused",
            ),
            (
                "node_scalars",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.integer=0.0",
                True,
                False,
                "numeric-equal wrong-type scalar verifier refused",
            ),
            (
                "node_arrays",
                f"MATCH(n:ontologyObject {{id:{literal(target)}}}) SET n.strings=reverse(n.strings)",
                True,
                False,
                "array-order tamper refused",
            ),
            (
                "edge_scalars",
                "MATCH()-[e:OWNER_GROUP_FIXTURE]->() SET e.integer=0.0",
                True,
                False,
                "edge scalar type tamper refused",
            ),
            (
                "edge_arrays",
                "MATCH()-[e:OWNER_GROUP_FIXTURE]->() SET e.strings=['tampered']",
                True,
                False,
                "edge array length/value tamper refused",
            ),
        ]
        for part, change, reading, expected, name in probes:
            f.cypher(change)
            before = self.snapshot()
            assert self.operation(part, reading) == expected, name
            if not expected:
                assert self.snapshot() == before, name
            self.restore_probes()
            assert self.snapshot() == self.expected, name
            self.receipt["cases"].append(name)
        for name, mutate in (
            (
                "truncated tuple payload refused",
                lambda rows: (
                    rows[:1] and [rows[0] | {"property_data": rows[0]["property_data"] + "|"}]
                ),
            ),
            (
                "owner expected-row count mismatch refused",
                lambda rows: [rows[0] | {"property_rows": rows[0]["property_rows"] + 1}],
            ),
            (
                "missing owner refused",
                lambda rows: [rows[0] | {"owner_id": "missing-owner-group-fixture"}],
            ),
            ("wrong database refused", lambda rows: [rows[0] | {"database_id": "wrong-database"}]),
            (
                "content hash tamper refused",
                lambda rows: [rows[0] | {"content_hash": "wrong-content-hash"}],
            ),
        ):
            before = self.snapshot()
            assert not self.operation("node_scalars", True, mutate), name
            assert self.snapshot() == before, name
            self.receipt["cases"].append(name)

        self.decoder_cases()
        self.duplicate_owner_case()

    def decoder_cases(self) -> None:
        """Malformed transport must not become an absent/null expected value."""

        f = self.fixture
        rows = json.loads(
            f.sql(
                "SELECT coalesce(jsonb_agg(t),'[]') FROM ("
                + E.parse(self.work / "project/ontology/candidate_verify_node_scalars.hpl")
                .findtext("transform[name='Expected properties']/sql")
                .replace("?", run.q(self.token))
                + ") t WHERE owner_id='owner-group-fixture-node'"
            )
        )
        assert len(rows) == 1

        def payload(text: str, count: int = 1):
            return lambda _: [rows[0] | {"property_rows": count, "property_data": text}]

        for part, data, count, expected, name in (
            (
                "node_scalars",
                "decoder_absent|null|false|-1|-1|",
                1,
                True,
                "explicit null verifies absence",
            ),
            (
                "node_scalars",
                "integer|null|false|-1|-1|",
                1,
                False,
                "explicit null refuses present scalar",
            ),
            (
                "node_scalars",
                "decoder_absent|integer|false|-1|-1|invalid",
                1,
                False,
                "invalid integer conversion refused",
            ),
            (
                "node_scalars",
                "decoder_absent|boolean|false|-1|-1|invalid",
                1,
                False,
                "invalid boolean conversion refused",
            ),
            (
                "node_scalars",
                "decoder_absent|string|invalid|-1|-1|",
                1,
                False,
                "invalid ownership marker refused",
            ),
            (
                "node_scalars",
                "decoder_absent|string|false|invalid|-1|",
                1,
                False,
                "invalid ordinal conversion refused",
            ),
            (
                "node_arrays",
                "empty_array|empty_array|false|0|0|",
                1,
                False,
                "empty array nonnegative marker refused",
            ),
            (
                "node_arrays",
                "empty_array|empty_array|false|-2|0|",
                1,
                False,
                "empty array wrong negative marker refused",
            ),
            (
                "node_arrays",
                "empty_array|empty_array|false|-1|0||empty_array|empty_array|false|-1|0|",
                2,
                False,
                "duplicate empty array markers refused",
            ),
            (
                "node_arrays",
                "decoder_absent|integer|false|0|2|0|decoder_absent|integer|false|0|2|1",
                2,
                False,
                "duplicate array ordinal refused",
            ),
        ):
            before = self.snapshot()
            assert self.operation(part, True, payload(data, count)) == expected, name
            assert self.snapshot() == before, name
            self.receipt["cases"].append(name)

    def restore_probes(self) -> None:
        node = next(n for n in self.nodes if n["node_id"] == "owner-group-fixture-node")
        edge = next(e for e in self.edges if e["edge_id"] == "owner-group-fixture-edge")
        self.fixture.cypher(
            "MATCH(n:ontologyObject {id:'owner-group-fixture-node'}) SET n="
            + typed_properties(
                node["properties"] | {"id": node["node_id"], "content_hash": node["content_hash"]}
            )
            + "; MATCH()-[e:OWNER_GROUP_FIXTURE]->() SET e="
            + typed_properties(
                edge["properties"]
                | {
                    "id": edge["edge_id"],
                    "content_hash": edge["content_hash"],
                    "release_id": self.release,
                }
            )
        )

    def duplicate_owner_case(self) -> None:
        """Duplicate relationship matches cannot offset an absent other owner."""
        f = self.fixture
        missing = "owner-group-fixture-edge-missing"
        for part in ("edge_scalars", "edge_arrays"):
            assert self.operation(part), part
        f.sql(
            "INSERT INTO "
            + SCHEMA
            + ".flat_graph_edge SELECT (jsonb_populate_record(NULL::"
            + SCHEMA
            + ".flat_graph_edge,to_jsonb(e)||jsonb_build_object('edge_id',"
            + run.q(missing)
            + ",'origin_edge_id',"
            + run.q(missing)
            + "))).* FROM "
            + SCHEMA
            + ".flat_graph_edge e WHERE edge_id='owner-group-fixture-edge'"
        )
        duplicate = json.loads(
            f.cypher(
                "MATCH(a)-[e:OWNER_GROUP_FIXTURE {id:'owner-group-fixture-edge'}]->(b) "
                "CREATE(a)-[extra:OWNER_GROUP_FIXTURE]->(b) SET extra=properties(e) RETURN elementId(extra)"
            ).splitlines()[-1]
        )
        before = self.snapshot()
        for part in ("edge_scalars", "edge_arrays"):
            assert not self.operation(part), part
        assert self.snapshot() == before
        f.cypher("MATCH()-[e]->() WHERE elementId(e)=" + literal(duplicate) + " DELETE e")
        f.sql("DELETE FROM " + SCHEMA + ".flat_graph_edge WHERE edge_id=" + run.q(missing))
        assert self.snapshot() == self.expected
        for part in ("edge_scalars", "edge_arrays"):
            assert self.operation(part), part
        self.receipt["cases"].append(
            "duplicate relationship cannot offset missing scalar/array owner"
        )

    def benchmark(self, phases=None) -> None:
        # AB for initialization, then BA/AB for unchanged warmed replay. Every
        # run includes native Hop startup; per-pipeline timing comes from logs.
        for phase, variant in phases or (
            ("initial", "baseline"),
            ("initial", "candidate"),
            ("replay-1", "candidate"),
            ("replay-1", "baseline"),
            ("replay-2", "baseline"),
            ("replay-2", "candidate"),
        ):
            if phase == "initial":
                self.fixture.cypher(
                    "MATCH(n:ontologyObject) SET n={id:n.id,content_hash:n.content_hash}; "
                    "MATCH()-[e]->() SET e={id:e.id,content_hash:e.content_hash,release_id:e.release_id}"
                )
            label = variant + "-properties-" + phase
            started = time.monotonic()
            self.fixture.workflow(variant + "_properties.hwf", {}, label)
            wall = time.monotonic() - started
            assert self.snapshot() == self.expected, label
            log = (self.work / (label + ".log")).read_text()
            durations = re.findall(r"Pipeline duration : ([0-9.]+) seconds", log)
            assert len(durations) == 8, (label, durations)
            workflow_seconds = float(re.findall(r"Workflow duration : ([0-9.]+) seconds", log)[-1])
            self.receipt["timings"].append(
                {
                    "phase": phase,
                    "variant": variant,
                    "wall_seconds": round(wall, 6),
                    "pipeline_seconds": [float(x) for x in durations],
                    "workflow_seconds": workflow_seconds,
                    "native_startup_and_exit_seconds": round(wall - workflow_seconds, 6),
                    "exact_typed_oracle_equal": True,
                    "log": str(self.work / (label + ".log")),
                }
            )
            (self.work / "property-benchmark-progress.json").write_text(
                json.dumps(self.receipt, indent=2) + "\n"
            )


def archive(path: Path):
    with path.open() as source:
        for row in csv.reader(source):
            yield json.loads(row[0])


def check_workflows(fixture: flat_projection.Fixture) -> None:
    """Relevant flat workflow proof; the unchanged operator is not retested."""
    baseline = json.loads((fixture.work / "baseline.json").read_text())
    for name in flat_projection.MIGRATIONS:
        fixture.sql((run.ROOT / "hop/ontology/sql" / name).read_text())
    fixture.stage()
    fixture.preserve(baseline["tables"])
    fixture.workflow(
        "stage_flat_release.hwf",
        {"RELEASE_ID": flat_projection.RELEASE},
        "owner-properties-native-stage",
    )
    # Synthetic fixture transition only. PostgreSQL supplies the exact IDs;
    # native staging just verified every historical property and attachment.
    revisions = json.loads(
        fixture.sql(
            "SELECT jsonb_agg(revision_node_id) FROM ontology.flat_graph_revision_binding "
            "WHERE release_id=" + run.q(flat_projection.RELEASE)
        )
    )
    fixture.cypher(
        "UNWIND "
        + literal(revisions)
        + " AS id MATCH(n:ontologyObject:entityRevision {id:id}) DETACH DELETE n"
    )
    load = fixture.sql(
        "SELECT load_id FROM ontology.flat_graph_load WHERE release_id="
        + run.q(flat_projection.RELEASE)
        + " AND state='STAGED'"
    )
    fixture.workflow(
        "finalize_flat_release.hwf", {"LOAD_ID": load}, "owner-properties-native-finalize"
    )
    fixture.check_initial(baseline)
    fixture.check_evidence(baseline)
    fixture.check_future_approval(baseline)
    fixture.check_owned_keys(baseline)
    fixture.preserve(baseline["tables"], exact=False)
    assert fixture.exports() == baseline["exports"]
    (fixture.work / "receipt.json").write_text(
        json.dumps(
            {
                "status": "PASSED",
                "scope": "RELEVANT_NATIVE_FLAT_PROPERTY_WORKFLOWS",
                "stage_and_all_legacy_typed_verifiers": True,
                "finalization_and_normal_replay": True,
                "source_hash_tamper_refused": True,
                "future_approval_stale_replay_null_stale_owned_removal": True,
                "forged_ownership_refusal_and_recovery": True,
                "historical_tables_and_exports_preserved": True,
                "source_requests": 0,
                "paid_calls": 0,
                "production_writes": 0,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--archive-nodes", type=Path, required=True)
    parser.add_argument("--archive-edges", type=Path, required=True)
    parser.add_argument("--node-limit", type=int, default=2000)
    parser.add_argument("--edge-limit", type=int, default=5000)
    options = parser.parse_args()
    assert 1 <= options.node_limit <= 10000 and 1 <= options.edge_limit <= 20000
    suffix = uuid.uuid4().hex[:12]
    work = Path.home() / ".local/state/jobtology-hop" / ("owner-property-native-" + suffix)
    work.mkdir(mode=0o700)
    fixture = flat_projection.Fixture(work, suffix)
    token = None
    try:
        fixture.boot()
        fixture.prepare()
        check_workflows(fixture)
        edges = list(itertools.islice(archive(options.archive_edges), options.edge_limit))
        endpoints = {e[key] for e in edges for key in ("subject_id", "object_id")}
        nodes = [
            n
            for i, n in enumerate(archive(options.archive_nodes))
            if i < options.node_limit or n["node_id"] in endpoints
        ]
        properties = {
            "integer": 0,
            "minimum": -9223372036854775808,
            "maximum": 9223372036854775807,
            "number": 1.25,
            "boolean": False,
            "empty_text": "",
            "key|%7C%25": "| %7C %25 %% 한글 🧪\n\t",
            "date_posted": "2026-10-12",
            "created_at": "2026-10-12T00:00:00Z",
            "strings": ["", "|", "%7C", "%25", "한글 🧪\n\t"],
            "empty_array": [],
            "booleans": [False, True],
            "numbers": [0, 1.25],
            "long_array": list(range(1003)),
            "dates.fixture": ["2026-10-11", "2026-10-12"],
        }
        rng = random.Random(20261012)
        alphabet = ["%", "|", "%7C", "%25", "한글", "🧪", "\n", "\t", "a"]
        properties["escaped_fuzz"] = [
            "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 30))) for _ in range(128)
        ]
        nodes.append(
            {
                "release_id": "fixture",
                "node_id": "owner-group-fixture-node",
                "labels": ["fixture"],
                "properties": properties,
                "identity_properties": properties,
                "owned_properties": {},
                "content_hash": "fixture-owner-node-hash",
                "flat_content_hash": "fixture-owner-flat-hash",
            }
        )
        edges.append(
            {
                "release_id": "fixture",
                "edge_id": "owner-group-fixture-edge",
                "origin_edge_id": "owner-group-fixture-edge",
                "subject_id": "owner-group-fixture-node",
                "object_id": "owner-group-fixture-node",
                "predicate": "OWNER_GROUP_FIXTURE",
                "properties": properties,
                "content_hash": "fixture-owner-edge-hash",
                "original_subject_id": "owner-group-fixture-node",
                "original_predicate": "OWNER_GROUP_FIXTURE",
                "original_object_id": "owner-group-fixture-node",
                "original_properties": properties,
                "original_content_hash": "fixture-owner-edge-hash",
            }
        )
        test = PropertyFixture(fixture, options.baseline_dir)
        token = test.token
        test.install(nodes, edges)
        test.cases()
        test.benchmark()
        fixture.sql("SELECT ontology.fail_flat_graph_load(" + run.q(token) + ")")
        token = None
        test.receipt.update(
            {
                "status": "PASSED",
                "scope": "PROPERTY_PASSES_ON_LOCAL_ARCHIVE_SUBSET",
                "full_native_preservation_receipt": str(work / "receipt.json"),
                "inputs": {
                    str(p): checksum(p) for p in (options.archive_nodes, options.archive_edges)
                },
                "source_requests": 0,
                "paid_calls": 0,
                "production_writes": 0,
                "network": "none",
                "cache_state": "SHARED_WARMED_FIXTURE_NOT_A_COLD_RUN",
                "baseline_artifacts": str(options.baseline_dir),
                "candidate_artifacts": {
                    prefix + part: checksum(run.ROOT / "hop/ontology" / (prefix + part + ".hpl"))
                    for prefix in ("write_", "verify_")
                    for part in PARTS
                },
            }
        )
        (work / "property-benchmark-receipt.json").write_text(
            json.dumps(test.receipt, indent=2) + "\n"
        )
        print("OWNER PROPERTY NATIVE AND ARCHIVE BENCHMARK PASSED", work, flush=True)
    finally:
        if token:
            fixture.sql("SELECT ontology.fail_flat_graph_load(" + run.q(token) + ")")
        fixture.cleanup()


if __name__ == "__main__":
    main()
