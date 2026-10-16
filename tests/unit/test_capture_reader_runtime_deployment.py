"""The fixed capture/reader rollout cannot change facts or execution metadata."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "capture_reader_deployment", ROOT / "hop/operations/deploy_capture_reader_runtime.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)

SIGNATURES = {
    "ingestion.source_graph_insert_guard()",
    "ingestion.graph_source_entities(text)",
    "ingestion.graph_source_edges(text)",
    "ingestion.source_graph_scoped_validation_issue(text)",
}


def state():
    return dict(
        schema=dict(
            v3_prompt=dict(count=1, digest="frozen"),
            tables={"ingestion.record": "exact table/index state"},
            views={"ingestion.validation_issue": "authoritative rules"},
            triggers={"ingestion.source_graph_membership:validate_source_graph_evidence": "guard"},
            functions={name: "original body" for name in SIGNATURES},
            function_acl={name: [10, None] for name in SIGNATURES},
            function_metadata={name: dict(proparallel="u", proconfig=["jit=off"])
                               for name in SIGNATURES},
        ),
        rows={
            "ingestion.record": dict(count=13234, digest="original rows"),
            "enrichment.metadata_occupation_candidate_decision": dict(count=4, digest="reviews"),
        },
        queries={"source": "exact", "inference": "exact"},
        catalog_context={"pin": "frozen"},
    )


def candidate():
    after = state()
    for name in SIGNATURES:
        if name.split("(")[0] in ops.ALLOWED_FUNCTIONS:
            after["schema"]["functions"][name] = "candidate body"
    return after


def test_only_approved_existing_bodies_may_change():
    ops.require_preserved(state(), candidate(), set(ops.ALLOWED_FUNCTIONS))
    after = candidate()
    after["schema"]["functions"]["ingestion.source_graph_scoped_validation_issue(text)"] = "drift"
    with pytest.raises(RuntimeError, match="outside approved function bodies"):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))
    with pytest.raises(RuntimeError, match="only its approved function bodies"):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS) | {"ingestion.other"})
    ops.require_preserved(state(), state(), set())


@pytest.mark.parametrize("field", ("proparallel", "provolatile", "prosecdef", "proisstrict",
                                  "proconfig", "procost", "prorettype", "proargtypes"))
def test_approved_body_permission_never_exempts_execution_metadata(field):
    after = candidate()
    after["schema"]["function_metadata"]["ingestion.source_graph_insert_guard()"][field] = "drift"
    with pytest.raises(RuntimeError, match="execution metadata"):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))


@pytest.mark.parametrize("mutation", ("rows", "prompt", "queries", "acl", "new-function",
                                      "removed-function", "index", "trigger", "catalog"))
def test_all_existing_facts_and_schema_identity_remain_exact(mutation):
    after = candidate()
    if mutation == "rows":
        after["rows"]["enrichment.metadata_occupation_candidate_decision"]["digest"] = "drift"
    elif mutation == "prompt":
        after["schema"]["v3_prompt"]["digest"] = "drift"
    elif mutation == "queries":
        after["queries"]["source"] = "drift"
    elif mutation == "acl":
        after["schema"]["function_acl"]["ingestion.graph_source_entities(text)"] = [10, "grant"]
    elif mutation == "new-function":
        name = "ingestion.begin_source_graph_projection_v3_compat(text)"
        for category in ("functions", "function_acl"):
            after["schema"][category][name] = "extra"
    elif mutation == "removed-function":
        after["schema"]["functions"].pop("ingestion.graph_source_entities(text)")
    elif mutation == "index":
        after["schema"]["tables"]["ingestion.record"] = "changed index"
    elif mutation == "trigger":
        name = "ingestion.source_graph_membership:validate_source_graph_evidence"
        after["schema"]["triggers"][name] = "drift"
    else:
        after["catalog_context"]["pin"] = "drift"
    with pytest.raises(RuntimeError):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))


def test_fixed_four_artifact_bundle_restores_overrides_on_failure():
    additive = ops.validation.routine.additive
    keys = ("KIND", "MIGRATIONS", "ALLOWLIST", "function_names", "schema_query",
            "require_preserved", "__doc__")
    before = {key: getattr(additive, key) for key in keys}
    with pytest.raises(RuntimeError, match="fixture"), ops.configured():
        assert len(additive.ALLOWLIST) == 4
        assert additive.MIGRATIONS == ops.MIGRATIONS
        assert additive.selected(list(reversed(ops.ALLOWLIST))) == ops.ALLOWLIST
        with pytest.raises(ValueError, match="complete coherent"):
            additive.selected([ops.MIGRATIONS[0]])
        with pytest.raises(ValueError):
            additive.selected([*ops.ALLOWLIST, "graph/clear_source_edges.hpl"])
        raise RuntimeError("fixture")
    assert before == {key: getattr(additive, key) for key in keys}


def test_migration_function_set_cannot_expand_or_omit_a_body(tmp_path):
    for relative in ops.MIGRATIONS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    path = tmp_path / ops.MIGRATIONS[0]
    complete = "\n".join(
        "CREATE OR REPLACE FUNCTION " + name + "()" for name in ops.ALLOWED_FUNCTIONS
    )
    with ops.configured():
        path.write_text(complete)
        assert ops.function_names(tmp_path) == ops.ALLOWED_FUNCTIONS
        for changed in (complete + "\nCREATE OR REPLACE FUNCTION ingestion.extra()", ""):
            path.write_text(changed)
            with pytest.raises(RuntimeError, match="exact approved function set"):
                ops.function_names(tmp_path)


def test_metadata_query_excludes_only_body_and_retains_index_health():
    query = ops.schema_query()
    assert "to_jsonb(p)-'prosrc'" in query
    assert "'function_metadata'" in query
    assert "i.indisvalid,i.indisready,i.indislive" in query
    assert query.count("'function_acl'") == 1


@pytest.mark.parametrize("filename", ("install.hwf", "install_posting_dates.hwf"))
def test_canonical_installers_require_every_migration_and_abort_each_failure(filename):
    installer = ET.parse(ROOT / "hop/graph" / filename).getroot()
    actions = installer.findall("actions/action[type='SQL']")
    expected = (
        "001_posting_ingestion_dates.sql", "002_batchfree_source_graph.sql",
        "003_source_query_sharing.sql", "004_verified_proof_replay.sql",
        "005_validation_worksets.sql", "006_jobalio_validation_worksets.sql",
        "007_capture_guard_worksets.sql", "008_reader_worksets.sql",
        "009_reader_fact_worksets.sql",
    )
    assert [action.findtext("sqlfilename").split("/")[-1] for action in actions] == list(expected)
    names = [action.findtext("name") for action in actions]
    hops = installer.findall("hops/hop")
    forward = {(hop.findtext("from"), hop.findtext("to")) for hop in hops
               if hop.findtext("evaluation") == "Y"}
    assert forward == set(zip(["Start", *names], [*names, "Success"], strict=True))
    failures = {(hop.findtext("from"), hop.findtext("to")) for hop in hops
                if hop.findtext("evaluation") == "N"}
    assert failures == {(name, "Abort") for name in names}
    assert all(action.findtext("connection") == "jobtology-postgres" for action in actions)
