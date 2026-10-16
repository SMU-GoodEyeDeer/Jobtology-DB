"""Assert failure routing and additive installer order before native execution."""

import xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "hop"


def test_canonical_installer_preserves_new_dispatcher_order() -> None:
    root = E.parse(ROOT / "llm/install.hwf").getroot()
    actions = root.findall("actions/action[type='SQL']")
    expected = sorted(path.name for path in (ROOT / "llm/sql").glob("*.sql"))
    assert [Path(str(action.findtext("sqlfilename"))).name for action in actions] == expected
    edges = {
        (hop.findtext("from"), hop.findtext("to"), hop.findtext("evaluation"))
        for hop in root.findall("hops/hop")
    }
    assert ("028_jobkorea_linking", "029_metadata_occupation_links", "Y") in edges
    assert ("029_metadata_occupation_links", "030_metadata_occupation_native", "Y") in edges
    assert ("030_metadata_occupation_native", "031_metadata_occupation_workers", "Y") in edges
    assert ("031_metadata_occupation_workers", "032_metadata_occupation_context", "Y") in edges
    assert ("032_metadata_occupation_context", "033_metadata_occupation_roles", "Y") in edges
    assert ("033_metadata_occupation_roles", "034_metadata_occupation_pm", "Y") in edges
    assert ("034_metadata_occupation_pm", "035_metadata_occupation_terminal_status", "Y") in edges
    assert (
        "035_metadata_occupation_terminal_status",
        "036_batchfree_graph_publication",
        "Y",
    ) in edges
    assert ("036_batchfree_graph_publication", "037_metadata_occupation_multimatch", "Y") in edges
    assert ("037_metadata_occupation_multimatch", "Success", "Y") in edges
    assert ("037_metadata_occupation_multimatch", "Abort", "N") in edges
    assert ("036_batchfree_graph_publication", "Abort", "N") in edges
    assert ("035_metadata_occupation_terminal_status", "Abort", "N") in edges
    assert ("034_metadata_occupation_pm", "Abort", "N") in edges
    assert ("033_metadata_occupation_roles", "Abort", "N") in edges
    assert ("031_metadata_occupation_workers", "Abort", "N") in edges
    assert ("032_metadata_occupation_context", "Abort", "N") in edges
    assert ("029_metadata_occupation_links", "Abort", "N") in edges
    assert ("030_metadata_occupation_native", "Abort", "N") in edges


def test_graph_failure_routes_own_cleanup_after_acquisition() -> None:
    root = E.parse(ROOT / "ingestions/jobkorea/publish_inferred_occupations.hwf").getroot()
    defaults = {
        node.findtext("name"): node.findtext("default_value")
        for node in root.findall("parameters/parameter")
    }
    assert defaults["INCLUDE_UNREVIEWED"] == "N"
    assert defaults["JOB_RUN_ID"] in (None, "")
    assert defaults["NCS_RUN_ID"] in (None, "")
    failures = {
        hop.findtext("from"): hop.findtext("to")
        for hop in root.findall("hops/hop")
        if hop.findtext("evaluation") == "N"
    }
    assert failures["Acquire exact graph writer"] == "Abort"
    assert failures["Load separate inferred occupations"] == "Fail own inference projection"
    assert failures["Verify totals and release writer"] == "Fail own inference projection"
    assert failures["Fail own inference projection"] == "Abort"


def test_finish_checks_second_graph_result_before_lease_release() -> None:
    root = E.parse(ROOT / "ingestions/jobkorea/finish_inferred_occupation_graph.hpl").getroot()
    transforms = {node.findtext("name"): node for node in root.findall("transform")}
    readonly = transforms["Read only exact totals"]
    assert readonly.findtext("read_only") == "Y"
    final = transforms["Finish verified staging projection"]
    assert final.findtext("returns/return/name") == "finished"
    check = transforms["Finish Require exact graph result"]
    assert check.findtext("compare/condition/leftvalue") == "finished"
    edges = {(node.findtext("from"), node.findtext("to")) for node in root.findall("order/hop")}
    assert ("Finish Verified", "Release only own writer") in edges
    assert ("Finish Require exact graph result", "Finish Graph mismatch") in edges


def test_prompt_version_reaches_sequential_and_worker_planner() -> None:
    for name in ("execute_inferred_occupations", "execute_inferred_occupation_workers"):
        root = E.parse(ROOT / ("ingestions/jobkorea/" + name + ".hwf")).getroot()
        defaults = {
            node.findtext("name"): node.findtext("default_value")
            for node in root.findall("parameters/parameter")
        }
        assert defaults["PROMPT_VERSION"] == "ko-metadata-occupation-v1"
        assert defaults["RETRIEVAL_REVISION"] in (None, "")
    root = E.parse(ROOT / "ingestions/jobkorea/prepare_inferred_occupations.hpl").getroot()
    planner = root.find("transform[type='DBJoin']")
    assert planner is not None
    fields = [node.findtext("name") for node in planner.findall("parameter/field")]
    sql = str(planner.findtext("sql"))
    assert len(fields) == sql.count("?")
    assert fields[fields.index("categorize_model") + 1] == "prompt_version"
    assert (
        "'categorize_model',?::text,'prompt_version',?::text,'retrieval_revision',nullif(?,''),'endpoint',?::text"
        in sql
    )


def test_retrieval_revision_is_optional_native_installer_dependency() -> None:
    root = E.parse(ROOT / "ingestions/jobkorea/prepare_inferred_occupations.hpl").getroot()
    planner = root.find("transform[type='DBJoin']")
    assert planner is not None
    fields = [node.findtext("name") for node in planner.findall("parameter/field")]
    assert fields[fields.index("prompt_version") + 1] == "retrieval_revision"
    sql = str(planner.findtext("sql"))
    assert "jsonb_strip_nulls" in sql and "'retrieval_revision',nullif(?,'')" in sql
    installer = E.parse(ROOT / "ingestions/jobkorea/install_inferred_occupations.hwf").getroot()
    files = [
        node.findtext("sqlfilename") for node in installer.findall("actions/action[type='SQL']")
    ]
    assert str(files[-1]).endswith("/037_metadata_occupation_multimatch.sql")


def test_focused_batchfree_installer_preserves_opt_in_dispatch() -> None:
    root = E.parse(
        ROOT / "ingestions/jobkorea/install_batchfree_graph_publication.hwf"
    ).getroot()
    files = [
        node.findtext("sqlfilename") for node in root.findall("actions/action[type='SQL']")
    ]
    assert [Path(str(filename)).name for filename in files] == [
        "002_batchfree_retention.sql",
        "036_batchfree_graph_publication.sql",
        "037_metadata_occupation_multimatch.sql",
    ]
    edges = {
        (hop.findtext("from"), hop.findtext("to"), hop.findtext("evaluation"))
        for hop in root.findall("hops/hop")
    }
    assert (
        "Install batch-free inference publication", "Preserve opt-in multi-match dispatch", "Y"
    ) in edges
    assert ("Preserve opt-in multi-match dispatch", "Success", "Y") in edges
    assert ("Preserve opt-in multi-match dispatch", "Abort", "N") in edges


def test_inferred_graph_uses_pg_pins_and_business_entities_only() -> None:
    for name in ("begin", "load", "verify"):
        root = E.parse(ROOT / f"ingestions/jobkorea/{name}_inferred_occupation_graph.hpl").getroot()
        queries = "\n".join(node.findtext("cypher") or "" for node in root.findall("transform"))
        assert all(
            label not in queries
            for label in ("ingestionBatch", "ingestionRecord", "archivedRecord")
        )
        sql = "\n".join(node.findtext("sql") or "" for node in root.findall("transform"))
        assert "check_metadata_occupation_graph(?)" in sql
    sql = (ROOT / "llm/sql/036_batchfree_graph_publication.sql").read_text()
    assert "latest_ready_run" not in sql
    assert "assert_source_graph_projection(jobs)" in sql
    assert "assert_source_graph_projection(ncs)" in sql
    assert "verify_item_input" in sql
    assert "source_graph_membership" in sql
    assert "SOURCE_OR_REVIEW_CHANGED" in sql
