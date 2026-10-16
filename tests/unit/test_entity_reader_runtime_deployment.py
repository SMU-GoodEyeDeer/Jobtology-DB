"""SQL009 deployment is one exact body and one coherent three-artifact bundle."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "entity_reader_deployment", ROOT / "hop/operations/deploy_entity_reader_runtime.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def state():
    signatures = ("ingestion.graph_source_entities(text)", "ingestion.graph_source_edges(text)",
                  "ingestion.source_graph_insert_guard()")
    return dict(
        schema=dict(
            v3_prompt=dict(count=1, digest="frozen"), tables={"ingestion.record": "indexes"},
            views={"ingestion.validation_issue": "rules"}, triggers={"source": "guard"},
            functions=dict.fromkeys(signatures, "original"),
            function_acl={name: [10, None] for name in signatures},
            function_metadata={name: dict(proparallel="u", proconfig=["jit=off"])
                               for name in signatures},
        ),
        rows={"ingestion.record": dict(count=13234, digest="exact"),
              "enrichment.metadata_occupation_candidate_decision": dict(count=4, digest="reviews")},
        queries={"source": "exact", "inference": "exact"}, catalog_context={"pin": "frozen"},
    )


def candidate():
    after = state()
    after["schema"]["functions"]["ingestion.graph_source_entities(text)"] = "candidate"
    return after


def test_only_existing_entity_body_is_allowed():
    ops.require_preserved(state(), candidate(), set(ops.ALLOWED_FUNCTIONS))
    for signature in ("ingestion.graph_source_edges(text)",
                      "ingestion.source_graph_insert_guard()"):
        after = candidate()
        after["schema"]["functions"][signature] = "drift"
        with pytest.raises(RuntimeError, match="outside approved function bodies"):
            ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))
    with pytest.raises(RuntimeError, match="only its approved function body"):
        ops.require_preserved(state(), candidate(), {"ingestion.graph_source_edges"})


@pytest.mark.parametrize("field", ("procost", "prorows", "proparallel", "provolatile", "prosupport",
                                  "prosecdef", "proisstrict", "proconfig", "proargtypes"))
def test_execution_metadata_cannot_change(field):
    after = candidate()
    after["schema"]["function_metadata"]["ingestion.graph_source_entities(text)"][field] = "drift"
    with pytest.raises(RuntimeError, match="execution metadata"):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))


@pytest.mark.parametrize("category", ("rows", "queries", "catalog_context", "v3_prompt", "tables",
                                     "views", "triggers", "function_acl", "functions"))
def test_all_existing_facts_and_schema_identity_remain_exact(category):
    after = candidate()
    if category in ("rows", "queries", "catalog_context"):
        after[category]["unexpected"] = "drift"
    else:
        after["schema"][category]["unexpected"] = "drift"
    with pytest.raises(RuntimeError):
        ops.require_preserved(state(), after, set(ops.ALLOWED_FUNCTIONS))


def test_three_artifact_bundle_and_nested_overrides_restore_after_failure():
    additive = ops.reader.validation.routine.additive
    keys = ("KIND", "MIGRATIONS", "ALLOWLIST", "function_names", "schema_query",
            "require_preserved", "__doc__")
    before = {key: getattr(additive, key) for key in keys}
    with pytest.raises(RuntimeError, match="fixture"), ops.configured():
        assert additive.ALLOWLIST == ops.ALLOWLIST and len(additive.ALLOWLIST) == 3
        assert additive.selected(list(reversed(ops.ALLOWLIST))) == ops.ALLOWLIST
        with pytest.raises(ValueError, match="complete coherent"):
            additive.selected([ops.MIGRATIONS[0]])
        with pytest.raises(ValueError):
            additive.selected([*ops.ALLOWLIST, "graph/sql/008_reader_worksets.sql"])
        assert "to_jsonb(p)-'prosrc'" in additive.schema_query()
        raise RuntimeError("fixture")
    assert before == {key: getattr(additive, key) for key in keys}


def test_migration_function_set_cannot_expand_or_omit_entity_body(tmp_path):
    path = tmp_path / ops.MIGRATIONS[0]
    path.parent.mkdir(parents=True)
    with ops.configured():
        path.write_text("CREATE OR REPLACE FUNCTION ingestion.graph_source_entities(jobs text)")
        assert ops.function_names(tmp_path) == ops.ALLOWED_FUNCTIONS
        for sql in ("", "CREATE OR REPLACE FUNCTION ingestion.graph_source_edges(jobs text)",
                    path.read_text() + "\nCREATE OR REPLACE FUNCTION ingestion.extra()"):
            path.write_text(sql)
            with pytest.raises(RuntimeError, match="exact approved function set"):
                ops.function_names(tmp_path)
