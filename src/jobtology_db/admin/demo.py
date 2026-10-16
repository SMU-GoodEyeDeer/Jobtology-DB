"""Synthetic representative values; no databases or queue files are opened."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jobtology_db.admin.telemetry import SOURCES, dashboard_from_results, service


def demo_dashboard() -> dict[str, Any]:
    now = datetime.now(UTC)
    prior = (now - timedelta(hours=2)).isoformat()
    sources = [
        {
            "source_id": source_id,
            "enabled": source_id != "jobkorea",
            "last_run_id": f"demo-{source_id}",
            "last_run_state": "READY",
            "last_success_at": prior,
            "graph_state": "READY",
            "records": 1400 + index * 731,
            "next_due_at": None
            if source_id == "jobkorea"
            else (now + timedelta(hours=22)).isoformat(),
        }
        for index, source_id in enumerate(SOURCES)
    ]
    ledger = {
        "service": service("postgres", "PostgreSQL", "healthy", "Synthetic demo service."),
        "sources": sources,
        "summary": {"active_runs": 1, "failed_runs_24h": 1},
        "runs": [
            {
                "id": "demo-refresh-nara",
                "source_id": "nara_job",
                "operation": "FETCH",
                "state": "RUNNING",
                "started_at": (now - timedelta(minutes=3)).isoformat(),
                "finished_at": None,
                "duration_seconds": 180,
            },
            {
                "id": "demo-import",
                "source_id": "jobkorea",
                "operation": "INGEST",
                "state": "READY",
                "started_at": prior,
                "finished_at": prior,
                "duration_seconds": 144,
            },
        ],
    }
    graph = {
        "service": service("neo4j", "Neo4j", "healthy", "Synthetic demo service."),
        "totals": [{"nodes": 204800, "relationships": 780600}],
        "node_counts": [
            {"label": "entity", "count": 203600},
            {"label": "jobPosting", "count": 23500},
            {"label": "ontologyEntity", "count": 1200},
            {"label": "ncsCompetency", "count": 14700},
        ],
        "relationship_counts": [
            {"type": "CLASSIFIED_AS", "count": 22500},
            {"type": "INFERRED_NCS_OCCUPATION", "count": 5800},
            {"type": "INFERRED_ONET_OCCUPATION", "count": 12600},
        ],
        "postings_by_source": [
            {"source_id": "jobkorea", "count": 8400},
            {"source_id": "nara_job", "count": 12600},
            {"source_id": "job_alio", "count": 1500},
        ],
        "inference": [
            {"kind": "INFERRED_NCS_OCCUPATION", "total": 5800, "reviewed": 160, "unreviewed": 5640},
            {
                "kind": "INFERRED_ONET_OCCUPATION",
                "total": 12600,
                "reviewed": 1200,
                "unreviewed": 11400,
            },
        ],
    }
    dashboard = dashboard_from_results(ledger, graph)
    dashboard["mode"] = "demo"
    dashboard["notices"].insert(
        0,
        {
            "level": "warning",
            "title": "Synthetic demo",
            "body": "Every displayed count, service, source and run is synthetic. "
            "Actions are disabled.",
        },
    )
    dashboard["sources"][1]["progress"] = {
        "completed": 240,
        "total": 400,
        "unit": "pages",
        "percent": 60,
    }
    return dashboard
