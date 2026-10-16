#!/usr/bin/env python3
"""Guarded entity-reader fact rollout with exact fact and metadata preservation.

Publish only SQL009 and both canonical graph installers. The existing scheduler
fence, backup, byte publication, independent readback and guarded recovery remain
in force. Only the existing graph_source_entities(text) body may change.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from pathlib import Path
from typing import Any

import deploy_capture_reader_runtime as reader

KIND = "ADDITIVE_ENTITY_READER_FACT_WORKSETS_ONLY"
MIGRATIONS = ("graph/sql/009_reader_fact_worksets.sql",)
ALLOWLIST = (*MIGRATIONS, "graph/install.hwf", "graph/install_posting_dates.hwf")
ALLOWED_FUNCTIONS = frozenset({"ingestion.graph_source_entities"})


def function_names(directory: Path) -> set[str]:
    names = reader.BASE_FUNCTION_NAMES(directory)
    if names != ALLOWED_FUNCTIONS:
        raise RuntimeError("Entity-reader migration must contain the exact approved function set")
    return names


def require_preserved(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> None:
    if allowed - ALLOWED_FUNCTIONS:
        raise RuntimeError("Entity-reader rollout permits only its approved function body")
    reader.require_preserved(before, after, allowed)


@contextlib.contextmanager
def configured() -> Generator[None]:
    with reader.configured():
        additive = reader.validation.routine.additive
        overrides = dict(
            KIND=KIND,
            MIGRATIONS=MIGRATIONS,
            ALLOWLIST=ALLOWLIST,
            function_names=function_names,
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
        reader.validation.routine.additive.main()


if __name__ == "__main__":
    main()
