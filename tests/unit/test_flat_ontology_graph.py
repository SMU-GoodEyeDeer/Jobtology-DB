"""Public native workflow contracts for the permanent flat ontology projection."""

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "hop/ontology"


def pipeline(name: str) -> ET.Element:
    return ET.parse(ONTOLOGY / (name + ".hpl")).getroot()


def actions(name: str) -> list[str]:
    return [
        item.findtext("filename", "")
        for item in ET.parse(ONTOLOGY / name).findall("actions/action")
        if item.findtext("type") == "PIPELINE"
    ]


def test_normal_writer_and_replay_only_use_flat_inventory() -> None:
    for name in ("graph_nodes", "graph_edges", "write_node_scalars", "write_node_arrays"):
        sql = "\n".join(item.text or "" for item in pipeline(name).findall("transform/sql"))
        assert "ontology.flat_graph_" in sql
        assert "ontology.graph_node " not in sql
        assert "ontology.graph_edge " not in sql
        assert "ontology.graph_property " not in sql
    sql = pipeline("graph_start").findtext("transform[name='Register graph writer']/sql", "")
    assert "ontology.begin_flat_graph_load" in sql
    writer = pipeline("graph_nodes").findtext("transform[name='Merge graph objects']/cypher", "")
    assert "n.content_hash=row.content_hash" in writer
    assert "n.flat_owned_keys" in writer
    assert "WHERE NOT k IN owned" in writer


def test_staging_and_finalization_have_separate_nonoptional_verifiers() -> None:
    stage = actions("stage_flat_release.hwf")
    final = actions("finalize_flat_release.hwf")
    normal = actions("load_release.hwf")
    assert "${PROJECT_HOME}/ontology/graph_stage.hpl" in stage
    assert "${PROJECT_HOME}/ontology/graph_finish.hpl" not in stage
    assert "${PROJECT_HOME}/ontology/graph_verify_legacy_nodes.hpl" in stage
    assert "${PROJECT_HOME}/ontology/graph_verify_legacy_edges.hpl" in stage
    assert final[0] == "${PROJECT_HOME}/ontology/graph_resume.hpl"
    assert "${PROJECT_HOME}/ontology/graph_nodes.hpl" not in final
    assert "${PROJECT_HOME}/ontology/graph_finish.hpl" in final
    assert "${PROJECT_HOME}/ontology/graph_finish.hpl" in normal
    assert "${PROJECT_HOME}/ontology/graph_stage.hpl" not in normal
    for name in ("load_release.hwf", "stage_flat_release.hwf", "finalize_flat_release.hwf"):
        tree = ET.parse(ONTOLOGY / name)
        names = {item.findtext("name") for item in tree.findall("parameters/parameter")}
        assert not any("ALLOW" in (item or "") or "SKIP" in (item or "") for item in names)


def test_final_zero_revision_check_includes_orphans_and_verifies_database() -> None:
    cypher = pipeline("graph_finish").findtext("transform[name='Verify graph scope']/cypher", "")
    assert "actual_database_id=$database_id" in cypher
    assert "OPTIONAL MATCH (legacy)" in cypher
    assert "entityRevision" in cypher and "ENDS WITH 'Revision'" in cypher
    assert "revision_count=0" in cypher
    assert "member_count=$expected_nodes" in cypher
    assert "edge_count=$expected_edges" in cypher
    resume = pipeline("graph_resume").findtext("transform[name='Require staged token']/sql", "")
    assert "ontology.resume_flat_graph_load(?)" in resume


def test_failure_cleanup_uses_only_exact_new_load_checkpoint() -> None:
    for name in ("load_release.hwf", "stage_flat_release.hwf", "finalize_flat_release.hwf"):
        tree = ET.parse(ONTOLOGY / name)
        failure_hops = [
            item for item in tree.findall("hops/hop") if item.findtext("evaluation") == "N"
        ]
        assert failure_hops
        assert all(item.findtext("to") == "Record failed load" for item in failure_hops)
    fail = pipeline("graph_fail")
    assert not fail.findall("transform[type='Neo4jCypherOutput']")
    assert "ontology.fail_flat_graph_load(?)" in fail.findtext(
        "transform[name='Fail this load']/sql", ""
    )
    root_cypher = pipeline("graph_root").findtext("transform[name='Check graph root']/cypher", "")
    assert "r.load_id" not in root_cypher
    assert "r.projection_state" not in root_cypher
    assert "r.database_id" not in root_cypher


def test_streamed_property_queries_have_one_jdbc_load_token_parameter() -> None:
    for prefix in ("write_", "verify_", "verify_legacy_"):
        for kind in ("node_scalars", "node_arrays", "edge_scalars", "edge_arrays"):
            sql = pipeline(prefix + kind).findtext(
                "transform[name='Expected properties']/sql", ""
            )
            assert sql.count("?") == 1
            assert "flat_graph_projection projection " in sql


def test_focused_and_canonical_installers_end_with_the_same_contract() -> None:
    flat_migrations = ["028_flat_graph_projection.sql", "029_flat_catalog_compatibility.sql"]
    for name in ("install_flat_graph.hwf", "install.hwf"):
        tree = ET.parse(ONTOLOGY / name)
        sql_actions = [
            item
            for item in tree.findall("actions/action")
            if item.findtext("type") == "SQL"
        ]
        expected = sorted(path.name for path in (ONTOLOGY / "sql").glob("*.sql"))
        if name == "install_flat_graph.hwf":
            expected = flat_migrations
        else:
            assert expected[-4:] == [
                flat_migrations[0],
                "028_product_role_demand_base.sql",
                flat_migrations[1],
                "030_live_ncs_unit.sql",
            ]
        assert [item.findtext("sqlfilename") for item in sql_actions] == [
            "${PROJECT_HOME}/ontology/sql/" + filename for filename in expected
        ]
        names = [item.findtext("name") for item in sql_actions]
        assert len(names) == len(set(names))
        expected_hops = [("Start", names[0], "Y", "Y")]
        for index, action_name in enumerate(names):
            successor = names[index + 1] if index + 1 < len(names) else "Success"
            expected_hops.extend(
                [(action_name, "Abort", "N", "N"), (action_name, successor, "Y", "N")]
            )
        actual_hops = []
        for hop in tree.findall("hops/hop"):
            assert hop.findtext("enabled") == "Y"
            actual_hops.append(
                tuple(
                    hop.findtext(field) for field in ("from", "to", "evaluation", "unconditional")
                )
            )
        assert sorted(actual_hops) == sorted(expected_hops)


def test_grouped_properties_keep_independent_typed_verifiers_and_endpoint_seeks() -> None:
    for prefix in ("write_", "verify_", "verify_legacy_"):
        for part in ("node_scalars", "node_arrays", "edge_scalars", "edge_arrays"):
            root = pipeline(prefix + part)
            sql = root.findtext("transform[name='Expected properties']/sql", "")
            operation = root.find("transform[name='Property operation']")
            cypher = operation.findtext("cypher", "")
            assert "count(*)::bigint AS property_rows" in sql
            assert "GROUP BY database_id,release_id,owner_id,content_hash" in sql
            assert "ORDER BY key,ordinal" in sql
            assert "size(fields)=row.property_rows*6" in cypher
            assert "count(n)=size($rows)" in cypher
            assert "count(DISTINCT row.owner_id)=size($rows)" in cypher
            assert "valueType(n[property.key])=valueType(property.expected)" in cypher
            assert operation.findtext("read_only") == ("N" if prefix == "write_" else "Y")
            if part.startswith("edge_"):
                assert "USING INDEX SEEK a:ontologyObject(id)" in cypher
                assert "USING INDEX SEEK b:ontologyObject(id)" in cypher
            if part.endswith("arrays"):
                assert "size(elements)=array_size" in cypher
                assert "elements[i].ordinal=i" in cypher
                assert "elements[0].ordinal=-1" in cypher
                assert "n[property.key]+" not in cypher
                if prefix == "write_":
                    assert "size(n[property.key])<size(property.expected)" in cypher
                    assert "valueType(n[property.key][i])=valueType(property.expected[i])" in cypher
