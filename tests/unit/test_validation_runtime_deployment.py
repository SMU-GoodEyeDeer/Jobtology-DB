"""The narrow deployment mode keeps all facts and schema identities exact."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "deploy_validation_runtime", ROOT / "hop/operations/deploy_validation_runtime.py")
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def state():
    name = "ingestion.source_graph_scoped_validation_issue(text)"
    return dict(schema=dict(
        v3_prompt=dict(count=1, digest="frozen"), tables={}, views={}, triggers={},
        functions={name: "old"}, function_acl={name: [10, None]}),
        rows={"enrichment.metadata_occupation_candidate_decision": dict(count=4, digest="reviews")},
        queries={"source": "exact", "inference": "exact"}, catalog_context={"pin": "frozen"})


def test_existing_v3_reviews_allow_only_the_scoped_function_change():
    after = state()
    after["schema"]["functions"]["ingestion.source_graph_scoped_validation_issue(text)"] = "new"
    ops.require_preserved(state(), after, {"ingestion.source_graph_scoped_validation_issue"})
    after["rows"]["enrichment.metadata_occupation_candidate_decision"]["digest"] = "changed"
    with pytest.raises(RuntimeError, match="rows changed"):
        ops.require_preserved(state(), after, {"ingestion.source_graph_scoped_validation_issue"})


def test_even_prior_performance_helpers_cannot_be_added():
    after = state()
    name = "ingestion.begin_source_graph_projection_v3_compat(text)"
    after["schema"]["functions"][name] = "helper"
    after["schema"]["function_acl"][name] = [10, None]
    with pytest.raises(RuntimeError, match="function/ACL identities"):
        ops.require_preserved(state(), after, set())


def test_fixed_three_artifact_bundle_and_context_restore():
    original = ops.routine.additive.KIND, ops.routine.additive.ALLOWLIST
    with pytest.raises(RuntimeError, match="fixture"), ops.configured():
        assert ops.routine.additive.KIND == ops.KIND
        assert ops.routine.additive.MIGRATIONS == ops.MIGRATIONS
        assert len(ops.ALLOWLIST) == 3
        assert ops.routine.additive.selected(list(ops.ALLOWLIST)) == ops.ALLOWLIST
        with pytest.raises(ValueError, match="complete coherent"):
            ops.routine.additive.selected([ops.ALLOWLIST[0]])
        raise RuntimeError("fixture")
    assert original == (ops.routine.additive.KIND, ops.routine.additive.ALLOWLIST)
