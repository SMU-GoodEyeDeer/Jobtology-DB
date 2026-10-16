"""Permanent source business-graph workflow contracts and reproducible generation."""

import importlib.util
import shutil
import xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "hop/graph"
SQL = (GRAPH / "sql/002_batchfree_source_graph.sql").read_text()


def pipeline(name: str) -> E.Element:
    return E.parse(GRAPH / (name + ".hpl")).getroot()


def test_every_source_writer_has_retired_graph_record_creation() -> None:
    for name in (
        "begin_batch",
        "finish_batch",
        "mark_failed",
        "load_records",
        "load_entity_names",
        "load_references",
        "constraints",
        "upgrade_labels",
    ):
        node = pipeline(name)
        for cypher in node.findall("transform/cypher"):
            text = cypher.text or ""
            assert "ingestionBatch" not in text, name
            assert "ingestionRecord" not in text, name
            assert "archivedRecord" not in text, name
            assert "HAS_RECORD" not in text, name
            assert "REFERS_TO" not in text, name
    for name in ("begin_batch", "finish_batch", "mark_failed"):
        assert pipeline(name).find("transform[type='Neo4jCypherOutput']") is None


def test_snapshot_loading_keeps_pg_acceptance_failure_and_date_checks() -> None:
    workflow = E.parse(GRAPH / "load_snapshot.hwf").getroot()
    edges = {
        (h.findtext("from"), h.findtext("to"), h.findtext("evaluation"))
        for h in workflow.findall("hops/hop")
    }
    for before, after in (
        ("Validate PostgreSQL snapshot", "Ensure graph constraints"),
        ("Begin graph batch", "Set readable entity names"),
        ("Set readable entity names", "Set posting ingestion dates"),
        ("Set posting ingestion dates", "Clear current source relationships"),
        ("Verify entity names", "Verify posting ingestion dates"),
        ("Verify posting ingestion dates", "Verify graph membership"),
        ("Verify graph membership", "Accept graph snapshot"),
    ):
        assert (before, after, "Y") in edges
    for name in (
        "Set readable entity names",
        "Load identity references",
        "Verify graph membership",
    ):
        assert (name, "Record graph failure", "N") in edges
    references = [n.text for n in workflow.findall("actions/action/filename")]
    assert "${PROJECT_HOME}/graph/load_records.hpl" not in references
    assert "${PROJECT_HOME}/graph/verify_records.hpl" not in references


def test_bulk_migration_projects_each_current_entity_once_and_preserves_dates() -> None:
    workflow = E.parse(GRAPH / "migrate_source_graph.hwf").getroot()
    assert workflow.findtext("parameters/parameter[name='RUN_ID']/default_value") == (
        "ALL_CHECKPOINTED"
    )
    references = [n.text for n in workflow.findall("actions/action/filename")]
    assert references.count("${PROJECT_HOME}/graph/load_entity_names.hpl") == 1
    assert "${PROJECT_HOME}/graph/load_posting_dates.hpl" not in references
    assert "${PROJECT_HOME}/graph/load_records.hpl" not in references
    assert "begin_source_graph_migration()" in pipeline("begin_batch").findtext(
        "transform[name='Read entity names']/sql", ""
    )


def test_historical_membership_proof_is_separate_from_current_entity_facts() -> None:
    assert "CREATE TABLE IF NOT EXISTS ingestion.source_graph_record_evidence" in SQL
    assert "CREATE TABLE IF NOT EXISTS ingestion.source_graph_membership" in SQL
    assert "IMMUTABLE_SOURCE_GRAPH_EVIDENCE" in SQL
    assert "IMMUTABLE_SOURCE_GRAPH_SNAPSHOT_PROOF" in SQL
    assert "SOURCE_GRAPH_LIVE_CONTENT_MISMATCH" in SQL
    assert "SOURCE_GRAPH_MEMBER_MISSING" in SQL
    assert "REFERENCES ingestion.run" not in SQL
    assert "REFERENCES ingestion.record" not in SQL
    assert "normalized_sha256" in SQL and "document_sha256" in SQL
    assert "source_payload" in SQL and "field_lineage" in SQL and "quality_flags" in SQL
    assert "loader_version='hop-graph-batchfree-v1'" in SQL
    assert "PERFORM ingestion.assert_source_graph_projection(id)" in SQL
    cypher = pipeline("verify_entity_names").findtext(
        "transform[name='Set entity names']/cypher", ""
    )
    assert "source_run_id=row.source_run_id" in cypher
    assert "$run_id" not in cypher


def test_entities_use_bounded_all_row_batches_and_independent_authoritative_reads() -> None:
    for name in ("load_records", "load_entity_names", "verify_records", "verify_entity_names"):
        node = pipeline(name)
        writer = node.find("transform[name='Set entity names']")
        assert writer is not None
        assert writer.findtext("batch_size") == "500"
        assert writer.findtext("unwind") == "Y"
        assert writer.findtext("unwind_map") == "rows"
        assert writer.findtext("retry") == "N"
        assert writer.findtext("nr_retries_on_error") == "0"
        cypher = writer.findtext("cypher", "")
        assert cypher.startswith("UNWIND $rows AS row\n")
        assert "RETURN count(i)=size($rows) AS entity_matches" in cypher
        assert "i.kind=row.kind AND i.code=row.code" in cypher
        assert "source_created_at=datetime(row.source_created_at)" in cypher
        assert node.findtext("transform[name='Read entity names']/sql") == (
            "SELECT * FROM ingestion.graph_source_entities(?)"
        )
        if name.startswith("load"):
            assert "WITH row,i WHERE" in cypher
            assert writer.findtext("read_only") == "N"
        else:
            assert "row.entity_title IS NULL" in cypher
            assert "row.source_facts_sha256 IS NULL" in cypher
            assert writer.findtext("read_only") == "Y"


def test_current_fact_selection_uses_whole_observations_and_subject_ownership() -> None:
    assert "created_at DESC,c.run_id DESC" in SQL
    assert "entity_kind='Organization' AND source<>'alio_organization'" in SQL
    assert "entity_kind='Occupation'" in SQL
    assert "entity_kind='Qualification'" in SQL
    assert "jsonb_build_object('kind','Qualification','code',n->'qualification_code'" in SQL
    assert "posting_records AS MATERIALIZED" in SQL
    assert "JOIN current_facts f ON f.run_id=r.run_id AND f.source_id=r.source_id" in SQL
    assert "jsonb_object_agg(p.representation,p.normalized) AS forms" in SQL
    assert "p.forms ?& ARRAY['list','detail','positions','files']" in SQL
    assert "coalesce((p.forms->'list'->>'ongoing')::boolean,false)" in SQL
    assert "eligible_runs AS MATERIALIZED" in SQL
    assert "ingestion.source_graph_run_is_valid(u.run_id)" in SQL
    assert "RETURN NOT EXISTS(SELECT 1 FROM ingestion.validation_issue WHERE run_id=jobs)" in SQL
    assert "FROM owners o JOIN refs self" in SQL
    assert "r.record_id=self.numeric_record_id" in SQL
    assert (
        "current_edges AS MATERIALIZED(SELECT from_id,to_id "
        "FROM ingestion.graph_source_edges(jobs))"
        in SQL
    )
    assert "UNION SELECT to_id FROM current_edges" in SQL
    assert "r.source_id='job_alio' AND target.kind='Organization'" in SQL
    assert "source_id='jobkorea' AND target.kind='Organization'" not in SQL
    assert (
        "CASE WHEN source_id IN('job_alio','ncs_competency') THEN '' ELSE source_record_id END"
        in SQL
    )


def test_pruning_is_anchored_and_preserves_current_relationship_identity() -> None:
    node = pipeline("clear_source_edges")
    cypher = node.findtext("transform[name='Set entity names']/cypher", "")
    assert "OPTIONAL MATCH (i)-[r]-()" in cypher
    assert "NOT r.edge_key IN split(row.expected_edge_keys," in cypher
    assert "r.source_graph=true" in cypher and "r.source_id=row.source_id" in cypher
    assert "OPTIONAL MATCH ()-[r]->()" not in cypher
    totals = pipeline("verify_totals").findtext("transform[name='Set entity names']/cypher", "")
    assert "OPTIONAL MATCH (i)-[r]-()" in totals
    assert "actual_edges=row.expected_edges" in totals
    writer = pipeline("load_references").findtext("transform[name='Set entity names']/cypher", "")
    assert "MATCH (a:entity {id:$from_id}) WITH a MATCH (b:entity {id:$to_id})" in writer
    assert "INFERRED_OCCUPATION" not in writer


def test_owner_batches_keep_per_input_boolean_checks_and_existing_field_types() -> None:
    for name in ("clear_source_edges", "verify_totals"):
        node = pipeline(name).find("transform[type='Neo4jCypherOutput']")
        assert node is not None
        assert node.findtext("batch_size") == "500"
        assert node.findtext("unwind") == "Y" and node.findtext("unwind_map") == "rows"
        cypher = node.findtext("cypher", "")
        assert "UNWIND $rows AS row\nCALL (row) {" in cypher
        assert "RETURN count(i)=1 AS row_matches" in cypher
        assert "size($rows)>0 AND count(*)=size($rows)" in cypher
        assert "all(matched IN collect(row_matches) WHERE matched)" in cypher
        assert "kind" not in cypher
        assert node.findtext("read_only") == ("Y" if name == "verify_totals" else "N")
        types = {
            m.findtext("parameter"): m.findtext("type") for m in node.findall("mappings/mapping")
        }
        assert types == {
            "owner_id": "String", "source_id": "String",
            ("expected_edges" if name == "verify_totals" else "expected_edge_keys"):
            ("Integer" if name == "verify_totals" else "String"),
        }


def test_source_installer_preserves_date_sql_and_orders_additive_contract() -> None:
    installer = E.parse(GRAPH / "install.hwf").getroot()
    sql_files = [n.text for n in installer.findall("actions/action/sqlfilename")]
    assert sql_files == [
        "${PROJECT_HOME}/graph/sql/001_posting_ingestion_dates.sql",
        "${PROJECT_HOME}/graph/sql/002_batchfree_source_graph.sql",
        "${PROJECT_HOME}/graph/sql/003_source_query_sharing.sql",
        "${PROJECT_HOME}/graph/sql/004_verified_proof_replay.sql",
        "${PROJECT_HOME}/graph/sql/005_validation_worksets.sql",
        "${PROJECT_HOME}/graph/sql/006_jobalio_validation_worksets.sql",
        "${PROJECT_HOME}/graph/sql/007_capture_guard_worksets.sql",
        "${PROJECT_HOME}/graph/sql/008_reader_worksets.sql",
        "${PROJECT_HOME}/graph/sql/009_reader_fact_worksets.sql",
    ]


def test_generator_replay_is_byte_stable(tmp_path: Path) -> None:
    target = tmp_path / "hop/graph"
    shutil.copytree(GRAPH, target, ignore=shutil.ignore_patterns("tests", "tools", "__pycache__"))
    spec = importlib.util.spec_from_file_location(
        "batchfree_generator", GRAPH / "tools/build_batchfree_graph.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__.update({"ROOT": tmp_path, "OUT": target})
    module.build()
    before = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
    module.build()
    assert before == {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
