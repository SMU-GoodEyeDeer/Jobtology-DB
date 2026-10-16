#!/usr/bin/env python3
"""Guarded JOB-ALIO workset rollout preserving all facts and schema identities."""

from __future__ import annotations

import contextlib
from collections.abc import Generator

import deploy_validation_runtime as validation

KIND = "ADDITIVE_JOBALIO_VALIDATION_WORKSETS_ONLY"
MIGRATIONS = ("graph/sql/006_jobalio_validation_worksets.sql",)
ALLOWLIST = (*MIGRATIONS, "graph/install.hwf", "graph/install_posting_dates.hwf")


@contextlib.contextmanager
def configured() -> Generator[None]:
    with validation.configured():
        additive = validation.routine.additive
        overrides = dict(KIND=KIND, MIGRATIONS=MIGRATIONS, ALLOWLIST=ALLOWLIST, __doc__=__doc__)
        previous = {key: getattr(additive, key) for key in overrides}
        try:
            for key, value in overrides.items():
                setattr(additive, key, value)
            yield
        finally:
            for key, value in previous.items():
                setattr(additive, key, value)


if __name__ == "__main__":
    with configured():
        validation.routine.additive.main()
