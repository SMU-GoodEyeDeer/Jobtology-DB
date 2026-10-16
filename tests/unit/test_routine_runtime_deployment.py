"""Performance-only rollout preserves existing v3 use and all original schema."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hop/operations'))
SPEC = importlib.util.spec_from_file_location('deploy_routine_runtime',
                                             ROOT / 'hop/operations/deploy_routine_runtime.py')
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def before():
    return dict(schema=dict(
        v3_prompt=dict(count=1, digest='existing-v3-prompt'),
        tables={'ingestion.record': 'all-columns-constraints-old-indexes'}, views={}, triggers={},
        functions={'ingestion.begin_source_graph_projection(text)': 'old'},
        function_acl={'ingestion.begin_source_graph_projection(text)': [10, None]}),
        rows={'ingestion.record': dict(count=8434, digest='source'),
              'enrichment.metadata_occupation_result': dict(count=6000, digest='legacy-and-v3'),
              'enrichment.metadata_occupation_candidate_decision': dict(count=3, digest='reviews')},
        queries={'legacy-graph': 'legacy', 'v3-graph': 'v3'}, catalog_context={'pin': 'frozen'})


def after():
    state = before()
    state['schema']['functions']['ingestion.begin_source_graph_projection(text)'] = 'new'
    helper = 'ingestion.begin_source_graph_projection_v3_compat(text)'
    state['schema']['functions'][helper] = 'helper'
    state['schema']['function_acl'][helper] = [10, None]
    return state


def test_existing_v3_requests_and_reviews_are_preserved_not_rejected():
    ops.require_preserved(before(), after(), {'ingestion.begin_source_graph_projection'})


@pytest.mark.parametrize('category', ['tables', 'views', 'triggers'])
def test_schema_and_preexisting_indexes_are_still_fingerprinted(category):
    value = after()
    value['schema'][category]['unreviewed-object'] = 'added'
    with pytest.raises(RuntimeError, match='schema objects'):
        ops.require_preserved(before(), value, {'ingestion.begin_source_graph_projection'})


def test_index_addition_is_not_excepted_from_table_fingerprint():
    value = after()
    value['schema']['tables']['ingestion.record'] = 'old-schema-plus-new-index'
    with pytest.raises(RuntimeError, match='Existing schema changed'):
        ops.require_preserved(before(), value, {'ingestion.begin_source_graph_projection'})


def test_behavior_rollback_may_leave_only_reviewed_unused_helper():
    value = after()
    value['schema']['functions']['ingestion.begin_source_graph_projection(text)'] = 'old'
    ops.require_preserved(before(), value, set())
    value['schema']['functions']['enrichment.unreviewed_helper(text)'] = 'extra'
    with pytest.raises(RuntimeError, match='Unexpected additive function'):
        ops.require_preserved(before(), value, set())


def test_intervening_v3_review_prevents_rollback():
    value = after()
    value['rows']['enrichment.metadata_occupation_candidate_decision']['digest'] = 'new-review'
    with pytest.raises(RuntimeError, match='rows changed'):
        ops.require_preserved(before(), value, {'ingestion.begin_source_graph_projection'})


def test_prior_coordinator_restored_even_when_new_mode_fails():
    old_kind, old_unused = ops.additive.KIND, ops.additive.require_unused_v3
    with pytest.raises(RuntimeError, match='fixture failure'), ops.configured():
        assert ops.additive.KIND == ops.KIND
        assert ops.additive.require_unused_v3 is ops.preserve_v3_use
        raise RuntimeError('fixture failure')
    assert old_kind == ops.additive.KIND
    assert ops.additive.require_unused_v3 is old_unused
    assert 'llm/sql/037_metadata_occupation_multimatch.sql' in ops.additive.MIGRATIONS
    assert all(not name.startswith('llm/') for name in ops.ALLOWLIST)


def test_index_readiness_flags_are_bound_only_in_performance_mode():
    previous = ops.additive.schema_query
    assert 'i.indisvalid' not in previous()
    with ops.configured():
        query = ops.additive.schema_query()
        for flag in ('i.indisvalid', 'i.indisready', 'i.indislive'):
            assert flag in query
        assert 'pg_get_indexdef(i.indexrelid)' in query
    assert ops.additive.schema_query is previous
