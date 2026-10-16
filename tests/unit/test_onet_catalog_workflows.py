"""Native O*NET ownership, phase ordering and complete typed proof contracts."""

import re
import xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "hop/ingestions/onet"


def query(name: str, transform_type: str) -> list[E.Element]:
    return E.parse(OUT / name).findall(f"transform[type='{transform_type}']")


def test_complete_collision_preflight_precedes_first_graph_mutation() -> None:
    root = E.parse(OUT / "load_catalog.hwf").getroot()
    hops = {
        hop.findtext("from"): hop.findtext("to")
        for hop in root.findall("hops/hop")
        if hop.findtext("evaluation") == "Y"
    }
    label = "Start"
    ordered: list[str] = []
    while label != "Success":
        label = str(hops[label])
        ordered.append(label)
    assert ordered.index("Preflight entire O*NET namespace") < ordered.index(
        "Require entity identity uniqueness"
    )
    assert ordered.index("Preflight all catalogue nodes") < ordered.index(
        "Write owned catalogue nodes"
    )
    assert ordered.index("Preflight all catalogue relationships") < ordered.index(
        "Write owned catalogue nodes"
    )
    assert ordered.index("Verify every typed relationship") < ordered.index(
        "Checkpoint actual complete graph"
    )
    assert ordered.index("Checkpoint actual complete graph") < ordered.index(
        "Select verified catalogue"
    )
    for name in (
        "graph_preflight_scope.hpl",
        "graph_preflight_nodes.hpl",
        "graph_preflight_edges.hpl",
    ):
        assert all(node.findtext("read_only") == "Y" for node in query(name, "Neo4jCypherOutput"))


def test_preflight_uses_indexed_nodes_after_global_namespace_label_guard() -> None:
    node_query = str(query("graph_preflight_nodes.hpl", "Neo4jCypherOutput")[0].findtext("cypher"))
    scope_query = str(query("graph_preflight_scope.hpl", "Neo4jCypherOutput")[0].findtext("cypher"))
    assert "OPTIONAL MATCH (object:entity {id:row.node_id})" in node_query
    assert "OPTIONAL MATCH (n) WHERE n.id STARTS WITH 'urn:jobtology:onet:'" in scope_query
    assert "'entity' IN labels(n) AND 'onetCatalogObject' IN labels(n)" in scope_query
    assert "count(object)<=1" in node_query


def test_relationship_candidate_scan_precedes_batch_unwind_and_keeps_global_collisions() -> None:
    cypher = str(query("graph_preflight_edges.hpl", "Neo4jCypherOutput")[0].findtext("cypher"))
    assert cypher.count("OPTIONAL MATCH (a)-[object]->(b)") == 1
    assert cypher.index("OPTIONAL MATCH (a)-[object]->(b)") < cypher.index("UNWIND $rows AS row")
    assert "object.id STARTS WITH 'urn:jobtology:onet:' OR object.managed_by=" in cypher
    assert "[candidate IN candidates WHERE candidate.object.id=row.edge_id] AS matches" in cypher
    assert "count(object)<=1" in cypher
    assert "actual_edge_type=row.edge_type" in cypher
    assert "actual_start_id=row.start_id AND actual_end_id=row.end_id" in cypher
    assert "valueType(object[p.key])=valueType(p.value)" in cypher
    assert "object.content_hash=row.previous_content_hash" in cypher
    assert "CALL (row,candidates,expected_properties,previous_properties)" in cypher
    assert "WITH row,candidates,split(coalesce(row.property_data,''),'|')" in cypher


def test_load_failure_marks_only_acquired_catalogue_attempt_failed() -> None:
    root = E.parse(OUT / "load_catalog.hwf").getroot()
    failures = {
        hop.findtext("from"): hop.findtext("to")
        for hop in root.findall("hops/hop")
        if hop.findtext("evaluation") == "N"
    }
    assert failures["Import exact local catalogue"] == "Abort"
    assert failures["Acquire exact catalogue writer"] == "Abort"
    assert failures["Preflight entire O*NET namespace"] == "Fail own graph attempt"
    assert failures["Checkpoint actual complete graph"] == "Fail own graph attempt"
    assert failures["Select verified catalogue"] == "Fail own graph attempt"
    node = query("graph_fail.hpl", "ExecSql")[0]
    assert node.findtext("sql") == "SELECT classification.fail_graph_load(?)"
    assert [field.findtext("name") for field in node.findall("arguments/argument")] == ["load_id"]


def test_every_writable_and_preflight_phase_requires_own_running_writer() -> None:
    for name in (
        "graph_preflight_scope",
        "graph_preflight_nodes",
        "graph_preflight_edges",
        "graph_constraint",
        "graph_nodes",
        "graph_edges",
        "graph_finish",
    ):
        sql = [node.findtext("sql") for node in query(name + ".hpl", "DBJoin")]
        assert "SELECT classification.assert_running_graph_load(?) AS checked_token" in sql
    verified = query("graph_require_verified.hpl", "DBJoin")[0]
    assert "assert_verified_graph_load(?)" in str(verified.findtext("sql"))
    root = E.parse(OUT / "verify_catalog.hwf").getroot()
    assert root.findtext("hops/hop[from='Start']/to") == "Require exact verified target"


def test_all_planned_rows_preserve_native_scalar_types_and_exact_match_counts() -> None:
    for name in ("graph_nodes", "graph_edges", "graph_verify_nodes", "graph_verify_edges"):
        node = query(name + ".hpl", "Neo4jCypherOutput")[0]
        cypher = str(node.findtext("cypher"))
        assert node.findtext("batch_size") == "500"
        assert node.findtext("unwind") == "Y"
        assert "size(fields)=row.property_count*3" in cypher
        assert "toInteger(p.text)" in cypher
        assert "toFloat(p.text)" in cypher
        assert "toBoolean(p.text)" in cypher
        assert "replace(replace(fields[i],'%7C','|'),'%25','%')" in cypher
        assert "count(object)=size($rows)" in cypher
        assert "count(DISTINCT row." in cypher
        if name.startswith("graph_verify"):
            assert "valueType(object[p.key])=valueType(p.value)" in cypher
            assert "size(keys(object))=row.property_count" in cypher
    scope = str(query("graph_verify_scope.hpl", "Neo4jCypherOutput")[0].findtext("cypher"))
    assert "size(nodes)=$expected_nodes" in scope
    assert "size(edges)=$expected_edges" in scope
    assert "size([n IN nodes WHERE n.current=true])=$current_nodes" in scope


def test_local_import_binds_three_source_files_and_actual_acquisition_receipts() -> None:
    source = str(
        query("import_local.hpl", "UserDefinedJavaClass")[0].findtext(
            "definitions/definition/class_source"
        )
    )
    assert "STRICT_DUPLICATE_DETECTION" in source
    assert "FAIL_ON_TRAILING_TOKENS" in source
    assert "INPUT_HASH_MISMATCH" in source
    assert 'payload.path("sources").size()==3' in source
    assert "SOURCE_ARCHIVE_HASH_MISMATCH" in source
    assert "DOWNLOAD_RECEIPT_MISMATCH" in source
    assert "INPUT_CHANGED_BEFORE_IMPORT" in source
    assert "SELECT classification.import_onet_catalog(?::jsonb)" in source
    assert "java.net" not in source


def test_new_installer_and_workflows_never_dispatch_existing_matching_contracts() -> None:
    installer = E.parse(OUT / "install.hwf").getroot()
    assert [
        Path(str(node.findtext("sqlfilename"))).name
        for node in installer.findall("actions/action[type='SQL']")
    ] == ["001_catalog.sql", "002_graph.sql"]
    for path in sorted(OUT.glob("*.hpl")) + sorted(OUT.glob("*.hwf")):
        body = path.read_text()
        assert all(
            label not in body
            for label in (
                "ingestionBatch",
                "ingestionRecord",
                "archivedRecord",
                "entityRevision",
                "request_inferred_occupation",
                "openrouter",
                "enrichment.",
                "ncs:",
            )
        )
    for path in OUT.glob("*.hpl"):
        root = E.parse(path).getroot()
        for node in root.findall("transform[type='DBJoin']"):
            sql = str(node.findtext("sql"))
            outside_literals = re.sub(r"'(?:[^']|'')*'", "", sql)
            assert outside_literals.count("?") == len(node.findall("parameter/field"))
            assert sql.count('"') % 2 == 0
