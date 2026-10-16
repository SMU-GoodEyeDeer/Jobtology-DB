from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from jobtology_db.admin.config import AdminSettings
from jobtology_db.admin.telemetry import (
    GRAPH_QUERIES,
    SOURCE_SQL,
    SUMMARY_SQL,
    DashboardCache,
    NativeTelemetry,
    dashboard_from_results,
    service,
)


def configuration(tmp_path: Path, **overrides: Any) -> AdminSettings:
    values: dict[str, Any] = {
        "username": "operator",
        "password": "local-test-password-only",
        "secret": "local-test-signing-secret-32-characters-long",
        "queue_path": tmp_path / "queue.sqlite3",
    }
    values.update(overrides)
    return AdminSettings(**values)


def test_partial_service_errors_keep_unknown_counts_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = configuration(tmp_path, postgres_dsn="postgresql://private:credential@private/db")
    monkeypatch.setattr(
        "psycopg.connect",
        MagicMock(
            side_effect=RuntimeError(
                "postgresql://private:credential@private/db secret SQL /protected/file"
            )
        ),
    )
    provider = NativeTelemetry(config)
    data = provider.collect()
    serialized = json.dumps(data)
    assert "credential" not in serialized and "/protected" not in serialized
    assert data["summary"]["source_postings"] is None
    assert data["summary"]["active_runs"] is None
    assert data["summary"]["total_nodes"] is None
    assert all(row["total"] is None for row in data["graph"]["inference"])
    assert all(row["records"] is None for row in data["sources"])
    assert data["services"][0]["status"] == "unavailable"
    assert data["services"][1]["status"] == "not_configured"


def test_real_count_mapping_preserves_namespaces_and_review_status():
    ledger: dict[str, Any] = {
        "service": service("postgres", "PostgreSQL", "healthy", "Available"),
        "sources": [
            {
                "source_id": "jobkorea",
                "enabled": None,
                "last_run_state": "FAILED",
                "last_run_id": "new-failed-run",
                "last_success_at": "2026-01-01T00:00:00+00:00",
                "records": 17,
                "graph_state": "READY",
            }
        ],
        "summary": {"active_runs": 1, "failed_runs_24h": 2},
    }
    graph: dict[str, Any] = {
        "service": service("neo4j", "Neo4j", "healthy", "Available"),
        "totals": [{"nodes": 120, "relationships": 210}],
        "node_counts": [{"label": "jobPosting", "count": 40}],
        "postings_by_source": [
            {"source_id": "jobkorea", "count": 17},
            {"source_id": "job_alio", "count": 3},
        ],
        "inference": [
            {"kind": "INFERRED_ONET_OCCUPATION", "total": 12, "reviewed": 2, "unreviewed": 10}
        ],
    }
    data = dashboard_from_results(ledger, graph)
    assert data["summary"]["source_postings"] == 20
    assert data["summary"]["source_postings"] != graph["node_counts"][0]["count"]
    jobkorea = next(source for source in data["sources"] if source["id"] == "jobkorea")
    assert jobkorea["state"] == "FAILED"
    assert jobkorea["last_success_at"] is not None
    assert jobkorea["mode"] == "LOCAL_ONLY" and jobkorea["postings"] == 17
    assert data["graph"]["inference"][1]["reviewed"] == 2
    assert data["graph"]["inference"][1]["confidence"] == "UNASSESSED"
    assert (
        "MATCH (n:entity:jobPosting) WHERE NOT n:ontologyEntity"
        in GRAPH_QUERIES["postings_by_source"]
    )
    assert "current=true" not in GRAPH_QUERIES["inference"]
    assert "WHERE NOT p:ontologyEntity" in GRAPH_QUERIES["inference"]
    assert "validation_issue" not in SOURCE_SQL
    assert "refresh_execution" not in SUMMARY_SQL


def test_ttl_serializes_refreshes_and_returns_copies(monkeypatch: pytest.MonkeyPatch):
    provider = MagicMock()
    provider.collect.return_value = {"value": [1]}
    clock = [100.0]
    monkeypatch.setattr("jobtology_db.admin.telemetry.time.monotonic", lambda: clock[0])
    cache = DashboardCache(provider, 30)

    def get_cached(_index: int) -> dict[str, Any]:
        return cache.get()

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(get_cached, range(8)))
    assert provider.collect.call_count == 1
    values[0]["value"].append(2)
    assert cache.get()["value"] == [1]
    cache.get(refresh=True)
    assert provider.collect.call_count == 1
    clock[0] += 5
    cache.get(refresh=True)
    assert provider.collect.call_count == 2
    clock[0] += 29
    cache.get()
    assert provider.collect.call_count == 2
    clock[0] += 1
    cache.get()
    assert provider.collect.call_count == 3


def test_postgres_uses_native_queries_read_only_and_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = {"active_runs": 0, "failed_runs_24h": 0}
    connection.execute.return_value = cursor
    context = MagicMock()
    context.__enter__.return_value = connection
    connect = MagicMock(return_value=context)
    monkeypatch.setattr("psycopg.connect", connect)
    data = NativeTelemetry(
        configuration(tmp_path, postgres_dsn="postgresql://localhost/disposable")
    ).ledger()
    assert data["service"]["status"] == "healthy"
    options = connect.call_args.kwargs["options"]
    assert "default_transaction_read_only=on" in options
    assert "statement_timeout=4000" in options
    assert connect.call_args.kwargs["connect_timeout"] == 4
    assert connection.execute.call_args_list[0].args[0] == "SET TRANSACTION READ ONLY"
    assert all("validation_issue" not in call.args[0] for call in connection.execute.call_args_list)


def test_neo4j_read_session_query_timeout_and_zero_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    session = MagicMock()
    session.run.return_value.data.return_value = []
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    factory = MagicMock(return_value=driver)
    monkeypatch.setattr("neo4j.GraphDatabase.driver", factory)
    data = NativeTelemetry(
        configuration(tmp_path, neo4j_uri="bolt://localhost:7687", neo4j_password="test-only")
    ).graph()
    assert data["service"]["status"] == "healthy"
    assert factory.call_args.kwargs["max_transaction_retry_time"] == 0
    assert driver.session.call_args.kwargs["default_access_mode"] == "READ"
    assert all(0 < call.args[0].timeout <= 4 for call in session.run.call_args_list)
    assert driver.close.call_count == 1
