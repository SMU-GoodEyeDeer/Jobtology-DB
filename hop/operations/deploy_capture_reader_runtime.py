#!/usr/bin/env python3
"""Guarded capture and source-reader body rollout with exact fact preservation.

Publish only SQL007, SQL008 and both canonical graph installers. Reuse the
existing scheduler fence, backup, byte publication, readback and guarded
recovery coordinator. Preserve all schema identities, execution metadata,
source and inference facts; only the approved existing function bodies change.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from pathlib import Path
from typing import Any

import deploy_validation_runtime as validation

KIND = "ADDITIVE_CAPTURE_READER_WORKSETS_ONLY"
MIGRATIONS = (
    "graph/sql/007_capture_guard_worksets.sql",
    "graph/sql/008_reader_worksets.sql",
)
ALLOWLIST = (*MIGRATIONS, "graph/install.hwf", "graph/install_posting_dates.hwf")
ALLOWED_FUNCTIONS = frozenset({
    "ingestion.source_graph_insert_guard",
    "ingestion.graph_source_entities",
    "ingestion.graph_source_edges",
})
BASE_FUNCTION_NAMES = validation.routine.additive.function_names


def function_names(directory: Path) -> set[str]:
    names = BASE_FUNCTION_NAMES(directory)
    if names != ALLOWED_FUNCTIONS:
        raise RuntimeError("Capture/reader migrations must contain the exact approved function set")
    return names


def schema_query() -> str:
    query = validation.routine.schema_query()
    anchor = " 'function_acl',"
    if query.count(anchor) != 1:
        raise RuntimeError("Reviewed function fingerprint query changed")
    metadata = (
        " 'function_metadata',(SELECT coalesce(jsonb_object_agg(p.oid::regprocedure::text,"
        " to_jsonb(p)-'prosrc'),'{}') FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN "
        + validation.routine.additive.SCHEMAS
        + " AND p.prokind IN('f','p')),\n"
    )
    return query.replace(anchor, metadata + anchor)


def require_preserved(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> None:
    if allowed - ALLOWED_FUNCTIONS:
        raise RuntimeError("Capture/reader rollout permits only its approved function bodies")
    validation.require_preserved(before, after, allowed)
    if before["schema"]["function_metadata"] != after["schema"]["function_metadata"]:
        raise RuntimeError("Capture/reader rollout changed function execution metadata")


@contextlib.contextmanager
def configured() -> Generator[None]:
    with validation.configured():
        additive = validation.routine.additive
        overrides = dict(
            KIND=KIND,
            MIGRATIONS=MIGRATIONS,
            ALLOWLIST=ALLOWLIST,
            function_names=function_names,
            schema_query=schema_query,
            require_preserved=require_preserved,
            __doc__=__doc__,
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
        validation.routine.additive.main()


if __name__ == "__main__":
    main()
