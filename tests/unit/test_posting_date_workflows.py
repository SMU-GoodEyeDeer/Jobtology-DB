"""Guard the native date workflow's scope, ordering and replayable generation."""

import importlib.util
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "hop/graph"


def xml(relative: str) -> ET.Element:
    return ET.parse(ROOT / "hop" / relative).getroot()


def test_date_only_workflow_keeps_source_graph_and_model_actions_out() -> None:
    workflow = xml("graph/update_posting_dates.hwf")
    references = [n.text for n in workflow.findall("actions/action/filename")]
    assert set(references) == {
        "${PROJECT_HOME}/graph/load_posting_dates.hpl",
        "${PROJECT_HOME}/graph/verify_posting_dates.hpl",
        "${PROJECT_HOME}/retention/enter_graph_writer.hpl",
        "${PROJECT_HOME}/retention/leave_graph_writer.hpl",
    }
    assert workflow.find("hops/hop[from='Verify posting ingestion dates'][to='Success']") is None
    assert (
        workflow.find(
            "hops/hop[from='Verify posting ingestion dates'][to='Leave retention writer guard']"
        )
        is not None
    )
    for source in ("Set posting ingestion dates", "Verify posting ingestion dates"):
        failure = workflow.find(
            f"hops/hop[from='{source}'][to='Release failed graph writer']/evaluation"
        )
        assert failure is not None and failure.text == "N"


def test_native_dates_use_bound_inputs_and_typed_values() -> None:
    load = xml("graph/load_posting_dates.hpl")
    verify = xml("graph/verify_posting_dates.hpl")
    capture = load.find("transform[name='Capture accepted posting events']")
    assert capture is not None
    assert capture.findtext("replace_vars") == "N"
    assert capture.findtext("parameter/field/name") == "run_id"
    assert capture.findtext("sql") == (
        "SELECT ingestion.record_posting_ingestion_observations(?) AS captured_observations"
    )
    write = load.find("transform[name='Set posting dates']")
    read = verify.find("transform[name='Verify posting dates']")
    assert write is not None and read is not None
    assert write.findtext("read_only") == "N" and read.findtext("read_only") == "Y"
    cypher = write.findtext("cypher") or ""
    assert "MATCH (i:entity:jobPosting" in cypher
    assert "datetime(row.first_ingested_at)" in cypher
    assert "date(row.ingestion_batch_date)" in cypher
    assert "CASE WHEN row.scraped_at IS NULL THEN NULL ELSE datetime(row.scraped_at) END" in cypher
    assert "i.name=" not in cypher and "facts_json" not in cypher and "DELETE" not in cypher
    assert "properties(i)['scraped_at'] IS NULL AND row.scraped_at IS NULL" in (
        read.findtext("cypher") or ""
    )
    expected_fields = {
        "identity_id", "first_ingested_at", "last_ingested_at", "latest_ingestion_run_id",
        "ingestion_batch_date", "ingestion_time_basis", "scraped_at", "scraped_at_basis",
        "scraped_at_evidence_reference",
    }
    for output in (write, read):
        assert output.findtext("unwind") == "Y"
        assert output.findtext("unwind_map") == "rows"
        assert output.findtext("batch_size") == "500"
        assert {f.text for f in output.findall("mappings/mapping/parameter")} == expected_fields
        assert "RETURN count(i)=size($rows) AS entity_matches" in output.findtext("cypher", "")


def test_future_snapshot_verifies_dates_before_acceptance() -> None:
    workflow = xml("graph/load_snapshot.hwf")
    assert (
        workflow.find(
            "hops/hop[from='Set readable entity names'][to='Set posting ingestion dates']"
        )
        is not None
    )
    assert (
        workflow.find("hops/hop[from='Verify entity names'][to='Verify posting ingestion dates']")
        is not None
    )
    assert (
        workflow.find(
            "hops/hop[from='Verify posting ingestion dates'][to='Verify graph membership']"
        )
        is not None
    )
    for installer in ("retention/install.hwf", "ingestions/jobkorea/install.hwf"):
        workflow = xml(installer)
        graph_installer = workflow.find(
            "actions/action[filename='${PROJECT_HOME}/graph/install.hwf']"
        )
        assert graph_installer is not None
        assert graph_installer.findtext("wait_until_finished") == "Y"
    assert [
        item.text for item in xml("graph/install.hwf").findall("actions/action/sqlfilename")
    ] == [
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
    installer = xml("graph/install.hwf")
    assert (
        installer.find(
            "hops/hop[from='Install permanent source business graph SQL']"
            "[to='Install query-local source validation and selection'][evaluation='Y']"
        )
        is not None
    )
    assert (
        installer.find(
            "hops/hop[from='Install query-local source validation and selection']"
            "[to='Install verified source proof replay'][evaluation='Y']"
        )
        is not None
    )
    assert (
        installer.find(
            "hops/hop[from='Install query-local source validation and selection']"
            "[to='Abort'][evaluation='N']"
        )
        is not None
    )


def test_generator_replay_preserves_single_guarded_action_paths(tmp_path: Path) -> None:
    generated = tmp_path / "hop/graph"
    generated.mkdir(parents=True)
    for name in ("load_entity_names.hpl", "load_snapshot.hwf"):
        shutil.copyfile(GRAPH / name, generated / name)
    retention = tmp_path / "hop/retention"
    retention.mkdir()
    shutil.copyfile(ROOT / "hop/retention/install.hwf", retention / "install.hwf")
    spec = importlib.util.spec_from_file_location(
        "posting_dates_generator", GRAPH / "tools/build_posting_dates.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__.update({"ROOT": tmp_path, "OUT": generated})
    module.build()
    before = {path.name: path.read_bytes() for path in generated.iterdir() if path.is_file()}
    module.build()
    assert before == {
        path.name: path.read_bytes() for path in generated.iterdir() if path.is_file()
    }
    workflow = ET.parse(generated / "load_snapshot.hwf").getroot()
    actions = [a.findtext("name") for a in workflow.findall("actions/action")]
    assert actions.count("Set posting ingestion dates") == 1
    assert actions.count("Verify posting ingestion dates") == 1
    assert actions.count("Enter retention writer guard") == 1
