"""Offline coverage for permanently retired source history graph consumers."""

import xml.etree.ElementTree as E
from pathlib import Path
from typing import Any, cast

import pytest

from jobtology_db.pipeline.update import Schedule, SourceSchedule, update_sources
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings
from jobtology_db.storage.neo4j_staging import load_neo4j_staging

ROOT = Path(__file__).resolve().parents[2]


class NoIO:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Retired publisher attempted I/O through {name}")


def test_legacy_publisher_and_updater_fail_before_any_io() -> None:
    sentinel = cast(Any, NoIO())
    with pytest.raises(ProcessingError, match="LEGACY_NEO4J_PUBLISHER_RETIRED"):
        load_neo4j_staging(sentinel, sentinel, "old-run")
    schedule = Schedule(
        version=1,
        retry_seconds=3600,
        sources=[SourceSchedule(source_id="job_alio", interval_seconds=86400)],
    )
    with pytest.raises(ProcessingError, match="LEGACY_NEO4J_PUBLISHER_RETIRED"):
        update_sources(sentinel, cast(Settings, sentinel), schedule, neo4j=True)


def test_retention_workflow_uses_only_postgresql_archive_and_proof() -> None:
    root = E.parse(ROOT / "hop/retention/execute.hwf").getroot()
    pipelines = [
        node.findtext("filename") for node in root.findall("actions/action[type='PIPELINE']")
    ]
    assert "${PROJECT_HOME}/retention/verify_source_projections.hpl" in pipelines
    assert all("graph" not in str(path) for path in pipelines)
    for filename in pipelines:
        path = ROOT / "hop" / str(filename).removeprefix("${PROJECT_HOME}/")
        pipeline = E.parse(path).getroot()
        assert not pipeline.findall("transform[type='Neo4jCypherOutput']")
    deletion = E.parse(ROOT / "hop/retention/delete_files.hpl").getroot()
    assert "NOT r.source_projection_verified" in str(
        deletion.findtext("transform[type='DBJoin']/sql")
    )


def test_former_graph_retention_pipelines_abort_without_io() -> None:
    for name in (
        "graph_target",
        "archive_nodes",
        "archive_references",
        "verify_archive",
        "graph_constraints",
        "delete_graph",
        "verify_deleted_graph",
    ):
        root = E.parse(ROOT / f"hop/retention/{name}.hpl").getroot()
        assert {node.findtext("type") for node in root.findall("transform")} == {
            "GetVariable",
            "Abort",
        }
        assert "retired" in str(root.findtext("transform[type='Abort']/message"))


def test_batchfree_retention_keeps_durable_pg_evidence_and_jobkorea_cleanup_hold() -> None:
    sql = (ROOT / "hop/retention/sql/002_batchfree_retention.sql").read_text()
    assert "UNSUPPORTED_JOBKOREA_STORAGE_RETENTION" in sql
    assert "assert_source_graph_projection" in sql
    assert "NOT source_projection_verified" in sql
    assert "DELETE FROM ingestion.source_graph_" not in sql
    assert "INSERT INTO retention.archive_record" in sql


def test_focused_installer_replays_only_required_additive_contracts() -> None:
    root = E.parse(
        ROOT / "hop/ingestions/jobkorea/install_batchfree_graph_publication.hwf"
    ).getroot()
    assert (
        root.findtext("actions/action[type='WORKFLOW']/filename")
        == "${PROJECT_HOME}/graph/install.hwf"
    )
    files = [node.findtext("sqlfilename") for node in root.findall("actions/action[type='SQL']")]
    assert files == [
        "${PROJECT_HOME}/retention/sql/002_batchfree_retention.sql",
        "${PROJECT_HOME}/llm/sql/036_batchfree_graph_publication.sql",
    ]


def test_checkpoint_requires_batchfree_ready_proof_before_recording() -> None:
    canonical = (ROOT / "docs/hop-migration/operations.sql").read_text()
    assert canonical == (ROOT / "hop/retention/sql/000_operations.sql").read_text()
    function = canonical.split("FUNCTION ingestion.record_graph_export_v1", 1)[1].split(
        "END $$;", 1
    )[0]
    assert function.index("assert_source_graph_projection(id)") < function.index(
        "INSERT INTO ingestion.graph_export"
    )
    assert "'hop-graph-batchfree-v1'" in function


def test_nested_graph_installers_wait_for_sql_completion() -> None:
    for file in (
        "hop/retention/install.hwf",
        "hop/ingestions/jobkorea/install.hwf",
        "hop/ingestions/jobkorea/install_batchfree_graph_publication.hwf",
    ):
        root = E.parse(ROOT / file).getroot()
        actions = root.findall("actions/action[type='WORKFLOW']")
        assert actions
        assert all(node.findtext("wait_until_finished") == "Y" for node in actions)
