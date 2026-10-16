"""Bounds and backend ownership for the real read-only operational entry point."""

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "hop/operations/validate_source_proofs.py"
SPEC = importlib.util.spec_from_file_location("parallel_source_validation", PATH)
assert SPEC and SPEC.loader
coordinator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coordinator)


@pytest.mark.parametrize(
    "runs",
    [
        [],
        ["r"] * 2,
        ["r"] * 17,
        ["LATEST"],
        ["ALL"],
        ["ALL_CHECKPOINTED"],
        ["x\nSELECT 1"],
        ["x'"],
        ["x" * 201],
    ],
)
def test_exact_bounded_scopes(runs: list[str]) -> None:
    with pytest.raises(ValueError):
        coordinator.validate_options("local-container", "jobtology", runs, 2, 60, 5, 300)


@pytest.mark.parametrize(
    "workers,statement,lock,total",
    [
        (3, 60, 5, 300),
        (8, 60, 5, 300),
        (2, 181, 5, 300),
        (2, 60, 0, 300),
        (2, 60, 31, 300),
        (2, 60, 5, 60),
        (2, 60, 5, 901),
    ],
)
def test_resource_bounds(workers: int, statement: int, lock: int, total: int) -> None:
    with pytest.raises(ValueError):
        coordinator.validate_options(
            "local-container", "jobtology", ["r"], workers, statement, lock, total
        )


def test_safe_ndjson_scope_and_four_worker_cap() -> None:
    coordinator.validate_options(
        "local-container",
        "jobtology",
        ["jobkorea-ndjson-" + "a" * 64, "exact-run:2"],
        4,
        60,
        5,
        300,
    )


def test_cancellation_binds_full_backend_identity() -> None:
    identity = {
        "pid": 1234,
        "backend_start": "2026-10-13T12:34:56+00:00",
        "application_name": "jtv-private-token-0",
    }
    sql = coordinator.owned_backends_query([identity], cancel=True)
    assert "pg_cancel_backend(pid)" in sql
    assert "pid=1234" in sql
    assert "backend_start='2026-10-13T12:34:56+00:00'::timestamptz" in sql
    assert "application_name='jtv-private-token-0'" in sql
    assert coordinator.owned_backends_query([]) == "SELECT 0"
    assert "pg_terminate_backend(pid)" in coordinator.owned_backends_query(
        [identity], terminate=True
    )


def test_archived_or_incomplete_proof_cannot_be_live_validation() -> None:
    sql = coordinator.proof_query(["exact-run"])
    assert "JOIN ingestion.run r" in sql
    assert "p.state='READY' AND r.state='READY' AND r.mode<>'SMOKE'" in sql
    assert "r.source_id=p.source_id" in sql


def test_bootstrap_cleanup_uses_exact_operation_and_database_names() -> None:
    sql = coordinator.owned_names_query("fixture_db", ["jtv-random-token-0"], terminate=True)
    assert "pg_terminate_backend(pid)" in sql
    assert "datname='fixture_db'" in sql
    assert "application_name IN ('jtv-random-token-0')" in sql
    assert "LIKE" not in sql
