#!/usr/bin/env python3
"""Guarded JOBALIO validation and source-owner transport rollout.

Publish exactly SQL006, its two canonical installers and the two qualified owner
pipelines. Preserve every existing fact and schema/ACL identity; only the scoped
validation function body may change. Reuse the existing backup, scheduler fence,
byte publication, independent readback and guarded recovery coordinator.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import Any

import deploy_validation_runtime as validation

KIND = "ADDITIVE_JOBALIO_VALIDATION_OWNER_TRANSPORT_ONLY"
MIGRATIONS = ("graph/sql/006_jobalio_validation_worksets.sql",)
ALLOWLIST = (
    *MIGRATIONS,
    "graph/install.hwf",
    "graph/install_posting_dates.hwf",
    "graph/clear_source_edges.hpl",
    "graph/verify_totals.hpl",
)
ALLOWED_FUNCTIONS = frozenset({"ingestion.source_graph_scoped_validation_issue"})


def require_preserved(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> None:
    if allowed - ALLOWED_FUNCTIONS:
        raise RuntimeError("Owner transport rollout permits only the scoped validation function")
    validation.require_preserved(before, after, allowed)


@contextlib.contextmanager
def configured() -> Generator[None]:
    with validation.configured():
        additive = validation.routine.additive
        overrides = dict(
            KIND=KIND,
            MIGRATIONS=MIGRATIONS,
            ALLOWLIST=ALLOWLIST,
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
