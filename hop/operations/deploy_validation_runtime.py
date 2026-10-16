#!/usr/bin/env python3
"""Guarded three-artifact scoped-validation rollout with exact fact preservation.

Reuse routine deployment's scheduler fence, backup, publication, readback and
rollback. Execute only SQL005 and publish its two canonical graph installers.
No new tables, views, triggers, functions or ACL identities are permitted.
"""
from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import Any

import deploy_routine_runtime as routine

KIND = "ADDITIVE_SCOPED_VALIDATION_WORKSETS_ONLY"
MIGRATIONS = ("graph/sql/005_validation_worksets.sql",)
ALLOWLIST = (*MIGRATIONS, "graph/install.hwf", "graph/install_posting_dates.hwf")


def require_preserved(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> None:
    routine.require_preserved(before, after, allowed)
    for category in ("functions", "function_acl"):
        if set(before["schema"][category]) != set(after["schema"][category]):
            raise RuntimeError("Validation rollout added or removed function/ACL identities")


@contextlib.contextmanager
def configured() -> Generator[None]:
    with routine.configured():
        overrides: dict[str, Any] = dict(
            KIND=KIND, MIGRATIONS=MIGRATIONS, ALLOWLIST=ALLOWLIST,
            require_preserved=require_preserved, __doc__=__doc__,
        )
        previous = {key: getattr(routine.additive, key) for key in overrides}
        try:
            for key, value in overrides.items():
                setattr(routine.additive, key, value)
            yield
        finally:
            for key, value in previous.items():
                setattr(routine.additive, key, value)


def main() -> None:
    with configured():
        routine.additive.main()


if __name__ == "__main__":
    main()
