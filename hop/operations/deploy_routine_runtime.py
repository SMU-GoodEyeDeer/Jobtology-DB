#!/usr/bin/env python3
"""Guarded performance-only SQL/runtime rollout, preserving all legacy/v3 facts.

Reuses the reviewed scheduler fence, backup, exact-byte publication and recovery
coordinator under a distinct operation identity and a fixed performance bundle.
Matching SQL/prompts/tables and index exceptions are excluded. Behavior rollback
restores old function bodies and runtime bytes; an unused additive helper remains.
It refuses intervening source, inference, review, schema or runtime drift.
"""
from __future__ import annotations

import contextlib
from collections.abc import Generator
from pathlib import Path
from typing import Any

import deploy_additive_runtime as additive

KIND = 'ADDITIVE_ROUTINE_PERFORMANCE_ONLY'
MIGRATIONS = (
    'graph/sql/004_verified_proof_replay.sql',
    'ingestions/jobkorea/sql/008_ready_statistics.sql',
)
ALLOWLIST = (
    *MIGRATIONS, 'graph/load_posting_dates.hpl', 'graph/verify_posting_dates.hpl',
    'graph/install.hwf', 'graph/install_posting_dates.hwf', 'ingestions/jobkorea/install.hwf',
)
NEW_HELPERS = {'ingestion.begin_source_graph_projection_v3_compat'}
BASE_PRESERVED = additive.require_preserved
BASE_SCHEMA_QUERY = additive.schema_query


def schema_query() -> str:
    original = 'jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY pg_get_indexdef(i.indexrelid))'
    replacement = ('jsonb_agg(jsonb_build_array(pg_get_indexdef(i.indexrelid),'
                   'i.indisvalid,i.indisready,i.indislive) ORDER BY pg_get_indexdef(i.indexrelid))')
    query = BASE_SCHEMA_QUERY()
    if query.count(original) != 1:
        raise RuntimeError('Reviewed index fingerprint contract changed')
    return query.replace(original, replacement)


def require_preserved(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> None:
    BASE_PRESERVED(before, after, allowed)
    if before['schema']['v3_prompt'] != after['schema']['v3_prompt']:
        raise RuntimeError('Performance rollout changed immutable v3 prompt')
    if set(before['rows']) != set(after['rows']):
        raise RuntimeError('Performance rollout added or removed a table')
    for category in ('tables', 'views', 'triggers'):
        if set(before['schema'][category]) != set(after['schema'][category]):
            raise RuntimeError('Performance rollout added or removed schema objects: ' + category)
    for category in ('functions', 'function_acl'):
        extra = set(after['schema'][category]) - set(before['schema'][category])
        if any(name.split('(')[0].lower() not in NEW_HELPERS for name in extra):
            raise RuntimeError('Unexpected additive function/ACL')


def preserve_v3_use(_pg: str, _directory: Path) -> None:
    # This fixed bundle cannot change matching behavior. Existing v3 use is
    # accepted ONLY because every old table row and every frozen pair's status/
    # publication query must match before/after. Intervening facts refuse apply
    # or rollback. The prior003/037 coordinator keeps its unused-v3 requirement.
    return None


@contextlib.contextmanager
def configured() -> Generator[None]:
    overrides: dict[str, Any] = dict(
        KIND=KIND, MIGRATIONS=MIGRATIONS, ALLOWLIST=ALLOWLIST,
        require_preserved=require_preserved, require_unused_v3=preserve_v3_use, __doc__=__doc__,
        schema_query=schema_query,
    )
    previous = {key: getattr(additive, key) for key in overrides}
    try:
        for key, value in overrides.items():
            setattr(additive, key, value)
        yield
    finally:
        for key, value in previous.items():
            setattr(additive, key, value)


def main() -> None:
    with configured():
        additive.main()


if __name__ == '__main__':
    main()
