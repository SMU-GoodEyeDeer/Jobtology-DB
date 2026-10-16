"""Retention lock ordering and exact deployed fallback are generator contracts."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'build_replay_queries', ROOT / 'hop/graph/tools/build_replay_queries.py')
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def test_replay_serializes_retention_before_live_read_or_projection_lock():
    body = ops.BODY
    gate = body.index('PERFORM retention.gate()')
    assert gate < body.index('SELECT * INTO u') < body.index('FOR UPDATE')


def test_partial_capture_fallback_is_exact_frozen_sql003():
    source = (ROOT / 'hop/graph/sql/003_source_query_sharing.sql').read_text()
    original = re.search(
        r'FUNCTION ingestion\.begin_source_graph_projection\(jobs text\) RETURNS boolean\n'
        r'LANGUAGE plpgsql SET jit=off AS \$\$([\s\S]*?)\$\$;', source)
    assert original
    generated = ops.build()
    assert 'AS $$' + original[1] + '$$;' in generated
    assert 'RETURN ingestion.begin_source_graph_projection_v3_compat(jobs)' in generated
    assert generated == ops.OUTPUT.read_text()
