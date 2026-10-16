"""The combined owner rollout permits one existing helper and exact old facts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "jobalio_graph_deployment", ROOT / "hop/operations/deploy_jobalio_graph_runtime.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)

FUNCTION = "ingestion.source_graph_scoped_validation_issue(text)"
GUARD = "ingestion.source_graph_insert_guard()"


def state():
    return dict(
        schema=dict(
            v3_prompt=dict(count=1, digest="frozen"),
            tables={"ingestion.record": "exact table/index state"},
            views={"ingestion.validation_issue": "authoritative rules"},
            triggers={"ingestion.source_graph_membership:validate_source_graph_evidence": "guard"},
            functions={FUNCTION: "old", GUARD: "same guard"},
            function_acl={FUNCTION: [10, None], GUARD: [10, None]},
        ),
        rows={
            "ingestion.record": dict(count=1076, digest="original rows"),
            "enrichment.metadata_occupation_candidate_decision": dict(count=4, digest="reviews"),
        },
        queries={"source": "exact", "inference": "exact"},
        catalog_context={"pin": "frozen"},
    )


def candidate():
    after = state()
    after["schema"]["functions"][FUNCTION] = "new scoped body"
    return after


def test_only_existing_scoped_function_body_may_change():
    ops.require_preserved(state(), candidate(), set(ops.ALLOWED_FUNCTIONS))
    after = candidate()
    after["schema"]["functions"][GUARD] = "weakened guard"
    with pytest.raises(RuntimeError, match="outside approved function bodies"):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))
    with pytest.raises(RuntimeError, match="only the scoped validation function"):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS) | {GUARD.split("(")[0]})


@pytest.mark.parametrize("mutation", ("rows", "prompt", "queries", "acl", "extra-function"))
def test_protected_facts_and_execution_identities_cannot_change(mutation):
    after = candidate()
    if mutation == "rows":
        after["rows"]["enrichment.metadata_occupation_candidate_decision"]["digest"] = "changed"
    elif mutation == "prompt":
        after["schema"]["v3_prompt"]["digest"] = "changed"
    elif mutation == "queries":
        after["queries"]["source"] = "changed"
    elif mutation == "acl":
        after["schema"]["function_acl"][FUNCTION] = [10, "grant"]
    else:
        name = "ingestion.begin_source_graph_projection_v3_compat(text)"
        after["schema"]["functions"][name] = "unexpected helper"
        after["schema"]["function_acl"][name] = [10, None]
    with pytest.raises(RuntimeError):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))


def test_fixed_five_artifact_bundle_and_exception_restore():
    additive = ops.validation.routine.additive
    keys = ("KIND", "MIGRATIONS", "ALLOWLIST", "require_preserved", "__doc__")
    before = {key: getattr(additive, key) for key in keys}
    with pytest.raises(RuntimeError, match="fixture"), ops.configured():
        assert additive.KIND == ops.KIND
        assert additive.MIGRATIONS == ("graph/sql/006_jobalio_validation_worksets.sql",)
        assert additive.ALLOWLIST == ops.ALLOWLIST
        assert len(ops.ALLOWLIST) == 5
        assert additive.selected(list(reversed(ops.ALLOWLIST))) == ops.ALLOWLIST
        assert additive.require_preserved is ops.require_preserved
        with pytest.raises(ValueError, match="complete coherent"):
            additive.selected([ops.MIGRATIONS[0]])
        raise RuntimeError("fixture")
    assert before == {key: getattr(additive, key) for key in keys}
