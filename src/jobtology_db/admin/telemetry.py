"""Bounded read-only telemetry from native Hop tables and the actual graph."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, LiteralString, cast

from jobtology_db.admin.config import AdminSettings

SOURCES = {
    "jobkorea": "JobKorea",
    "nara_job": "Nara",
    "job_alio": "JOB-ALIO",
    "alio_organization": "ALIO organizations",
    "ncs_competency": "NCS competencies",
    "ncs_qualification": "NCS qualifications",
    "ncs_career_path": "NCS career paths",
    "qnet_schedule": "Q-Net schedule",
}

# Physical tables only. The latest non-smoke run and latest accepted run have
# different meanings; a failed refresh must not hide the last accepted snapshot.
SOURCE_SQL = """
WITH source_ids AS (
 SELECT unnest(ARRAY['jobkorea','nara_job','job_alio','alio_organization',
 'ncs_competency','ncs_qualification','ncs_career_path','qnet_schedule']) AS source_id
)
SELECT s.source_id, p.enabled, p.interval_seconds,
 latest.run_id AS last_run_id, latest.state AS last_run_state,
 latest.created_at AS last_started_at, latest.completed_at AS last_finished_at,
 accepted.run_id AS ready_run_id, accepted.completed_at AS last_success_at,
 graph.state AS graph_state, graph.record_count AS records,
 CASE WHEN p.enabled AND accepted.run_id IS NOT NULL
 THEN accepted.created_at + make_interval(secs=>p.interval_seconds) END AS next_due_at
FROM source_ids s LEFT JOIN ingestion.refresh_policy p USING(source_id)
LEFT JOIN LATERAL (
 SELECT run_id,state,created_at,completed_at FROM ingestion.run
 WHERE source_id=s.source_id AND mode<>'SMOKE'
 ORDER BY created_at DESC,run_id DESC LIMIT 1
) latest ON true
LEFT JOIN LATERAL (
 SELECT run_id,created_at,completed_at FROM ingestion.run
 WHERE source_id=s.source_id AND mode<>'SMOKE' AND state='READY'
 ORDER BY created_at DESC,run_id DESC LIMIT 1
) accepted ON true
LEFT JOIN ingestion.source_graph_projection graph ON graph.run_id=accepted.run_id
ORDER BY s.source_id
"""

RUN_SQL = """
SELECT run_id AS id,source_id,'INGEST' AS operation,state,
 created_at AS started_at,completed_at AS finished_at,
 extract(epoch FROM (coalesce(completed_at,clock_timestamp())-created_at)) AS duration_seconds
FROM ingestion.run WHERE mode<>'SMOKE' ORDER BY created_at DESC,run_id DESC LIMIT 30
"""

EXECUTION_SQL = """
SELECT 'refresh-'||execution_id AS id,source_id,operation,
 CASE WHEN finished_at IS NULL THEN 'UNFINISHED'
 WHEN exit_code=0 THEN 'SUCCEEDED' ELSE 'FAILED' END AS state,
 started_at,finished_at,
 extract(epoch FROM(coalesce(finished_at,clock_timestamp())-started_at)) AS duration_seconds
FROM ingestion.refresh_execution ORDER BY started_at DESC,execution_id DESC LIMIT 30
"""

SUMMARY_SQL = """
SELECT (SELECT count(*) FROM ingestion.run WHERE state='LOADING' AND mode<>'SMOKE')
 AS active_runs,
 (SELECT count(*) FROM ingestion.run WHERE state='FAILED' AND mode<>'SMOKE'
 AND coalesce(completed_at,created_at)>clock_timestamp()-interval '24 hours')
 AS failed_runs_24h
"""

GRAPH_QUERIES: dict[str, LiteralString] = {
    "totals": "CALL () { MATCH (n) RETURN count(n) AS nodes } "
    "CALL () { MATCH ()-[r]->() RETURN count(r) AS relationships } RETURN nodes,relationships",
    "node_counts": "MATCH (n) UNWIND labels(n) AS label "
    "RETURN label,count(*) AS count ORDER BY count DESC,label LIMIT 100",
    "relationship_counts": "MATCH ()-[r]->() RETURN type(r) AS type,count(*) AS count "
    "ORDER BY count DESC,type LIMIT 100",
    "postings_by_source": "MATCH (n:entity:jobPosting) WHERE NOT n:ontologyEntity "
    "RETURN n.source_id AS source_id,count(n) AS count ORDER BY source_id LIMIT 20",
    "inference": "MATCH (p:entity:jobPosting)-[r:INFERRED_NCS_OCCUPATION|"
    "INFERRED_ONET_OCCUPATION]->() WHERE NOT p:ontologyEntity "
    "RETURN type(r) AS kind,count(r) AS total,"
    "sum(CASE WHEN r.review_status IN ['HUMAN_REVIEWED','ASSISTANT_REVIEWED'] "
    "THEN 1 ELSE 0 END) AS reviewed,"
    "sum(CASE WHEN r.review_status='UNREVIEWED' THEN 1 ELSE 0 END) AS unreviewed",
}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in cast(dict[str, Any], value).items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in cast(list[Any], value)]
    # PostgreSQL duration extraction returns Decimal, not a JSON primitive.
    if value is not None and type(value).__module__ == "decimal":
        return float(value)
    return value


def service(service_id: str, label: str, status: str, message: str) -> dict[str, Any]:
    return {
        "id": service_id,
        "label": label,
        "status": status,
        "message": message,
        "checked_at": timestamp(),
    }


def empty_source(source_id: str) -> dict[str, Any]:
    return {
        "id": source_id,
        "name": SOURCES[source_id],
        "mode": "LOCAL_ONLY" if source_id == "jobkorea" else "SCHEDULED",
        "state": "UNKNOWN",
        "last_success_at": None,
        "last_run_id": None,
        "last_run_state": None,
        "records": None,
        "postings": None,
        "graph_state": None,
        "next_due_at": None,
        "progress": None,
    }


class NativeTelemetry:
    def __init__(self, settings: AdminSettings):
        self.settings = settings

    def ledger(self) -> dict[str, Any]:
        if self.settings.postgres_dsn is None:
            return {
                "service": service(
                    "postgres",
                    "PostgreSQL",
                    "not_configured",
                    "Ledger connection is not configured.",
                )
            }
        try:
            import psycopg
            from psycopg.rows import dict_row

            timeout = max(1, int(self.settings.query_timeout_seconds))
            # Psycopg's overloaded connect stubs bind the default tuple row type.
            connect = cast(Callable[..., Any], psycopg.connect)
            with connect(
                self.settings.postgres_dsn.get_secret_value(),
                connect_timeout=timeout,
                options="-c default_transaction_read_only=on "
                f"-c statement_timeout={timeout * 1000} "
                f"-c transaction_timeout={timeout * 1000} "
                f"-c lock_timeout={timeout * 1000} -c idle_in_transaction_session_timeout=10000",
                row_factory=dict_row,
            ) as connection:
                # Explicitly enforce read-only even if a supplied DSN has options.
                connection.execute("SET TRANSACTION READ ONLY")
                sources = connection.execute(SOURCE_SQL).fetchall()
                runs = connection.execute(RUN_SQL).fetchall()
                executions = connection.execute(EXECUTION_SQL).fetchall()
                summary = connection.execute(SUMMARY_SQL).fetchone()
            return json_value(
                {
                    "service": service(
                        "postgres", "PostgreSQL", "healthy", "Native ingestion ledger available."
                    ),
                    "sources": sources,
                    "runs": runs + executions,
                    "summary": summary,
                }
            )
        except Exception:
            # Driver exception text may contain credentials, paths, SQL and hosts.
            return {
                "service": service(
                    "postgres",
                    "PostgreSQL",
                    "unavailable",
                    "Ledger unavailable or its query timed out.",
                )
            }

    def graph(self) -> dict[str, Any]:
        if not self.settings.neo4j_uri or not self.settings.neo4j_password:
            return {
                "service": service(
                    "neo4j", "Neo4j", "not_configured", "Graph connection is not configured."
                )
            }
        try:
            from neo4j import READ_ACCESS, GraphDatabase, Query

            timeout = self.settings.query_timeout_seconds
            deadline = time.monotonic() + timeout
            driver = GraphDatabase.driver(  # pyright: ignore[reportUnknownMemberType]
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password.get_secret_value()),
                connection_timeout=timeout,
                connection_acquisition_timeout=timeout,
                max_transaction_retry_time=0,
                max_connection_pool_size=2,
                connection_write_timeout=timeout,
            )
            data: dict[str, Any] = {}
            try:
                with driver.session(  # pyright: ignore[reportUnknownMemberType]
                    database=self.settings.neo4j_database, default_access_mode=READ_ACCESS
                ) as session:
                    # Auto-commit reads with query timeout, no retry or writes.
                    for key, cypher in GRAPH_QUERIES.items():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("graph telemetry deadline")
                        data[key] = session.run(Query(cypher, timeout=remaining)).data()
            finally:
                driver.close()
            data["service"] = service("neo4j", "Neo4j", "healthy", "Actual graph counts available.")
            return data
        except Exception:
            return {
                "service": service(
                    "neo4j", "Neo4j", "unavailable", "Graph unavailable or its query timed out."
                )
            }

    def collect(self) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            ledger_future, graph_future = executor.submit(self.ledger), executor.submit(self.graph)
            ledger, graph = ledger_future.result(), graph_future.result()
        return dashboard_from_results(ledger, graph)


def dashboard_from_results(ledger: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    sources = {source_id: empty_source(source_id) for source_id in SOURCES}
    configured = None
    if "sources" in ledger:
        configured = 0
        for row in ledger["sources"]:
            source_id = row["source_id"]
            if source_id not in sources:
                continue
            if row.get("enabled"):
                configured += 1
            sources[source_id].update(
                {
                    "state": row.get("last_run_state") or "NOT_LOADED",
                    "last_success_at": row.get("last_success_at"),
                    "last_run_id": row.get("last_run_id"),
                    "last_run_state": row.get("last_run_state"),
                    "records": row.get("records"),
                    "graph_state": row.get("graph_state"),
                    "next_due_at": row.get("next_due_at"),
                }
            )
    postings = graph.get("postings_by_source")
    if postings is not None:
        # A successful grouped count proves zero for absent source groups.
        for source_id in ("jobkorea", "nara_job", "job_alio"):
            sources[source_id]["postings"] = sum(
                row["count"] for row in postings if row["source_id"] == source_id
            )
    runs: list[dict[str, Any]] = []
    for row in ledger.get("runs", []):
        runs.append(
            {
                **row,
                "source_name": SOURCES.get(row["source_id"], row["source_id"]),
                "records": None,
                "progress": None,
                "message": None,
            }
        )
    runs.sort(key=lambda row: row.get("started_at") or "", reverse=True)
    totals_rows: list[dict[str, Any]] = graph.get("totals") or []
    totals: dict[str, Any] = {}
    if totals_rows:
        totals = totals_rows[0]
    inference = {row["kind"]: row for row in graph.get("inference", [])}
    kinds = ("INFERRED_NCS_OCCUPATION", "INFERRED_ONET_OCCUPATION")
    graph_ok = graph["service"]["status"] == "healthy"
    return {
        "generated_at": timestamp(),
        "mode": "live",
        "refresh_interval_seconds": 30,
        "services": [ledger["service"], graph["service"]],
        "summary": {
            "source_postings": sum(row["count"] for row in postings)
            if postings is not None
            else None,
            "total_nodes": totals.get("nodes"),
            "total_relationships": totals.get("relationships"),
            "active_runs": ledger.get("summary", {}).get("active_runs"),
            "failed_runs_24h": ledger.get("summary", {}).get("failed_runs_24h"),
            "ready_sources": sum(row["last_success_at"] is not None for row in sources.values())
            if "sources" in ledger
            else None,
            "configured_sources": configured,
        },
        "sources": list(sources.values()),
        "runs": runs[:30],
        "graph": {
            "status": graph["service"]["status"],
            "checked_at": graph["service"]["checked_at"],
            "node_counts": graph.get("node_counts", []),
            "relationship_counts": graph.get("relationship_counts", []),
            "postings_by_source": postings or [],
            "inference": [
                {
                    "kind": kind,
                    "confidence": "UNASSESSED",
                    **inference.get(
                        kind,
                        {
                            "total": 0 if graph_ok else None,
                            "reviewed": 0 if graph_ok else None,
                            "unreviewed": 0 if graph_ok else None,
                        },
                    ),
                }
                for kind in kinds
            ],
        },
        "actions": [],
        "jobs": [],
        "notices": [
            {
                "level": "info",
                "title": "Evidence boundaries",
                "body": "Posting counts use source entities and exclude ontology duplicates. "
                "Inferred occupations retain actual review status and unassessed confidence; "
                "they do not establish source-stated duties or competency evidence.",
            },
            {
                "level": "info",
                "title": "Ledger status",
                "body": "Active runs counts LOADING ingestion ledger entries, including possible "
                "interrupted runs; it does not prove a live process. Failure counts use ingestion "
                "runs only. Refresh execution rows are shown separately. Next due is an interval "
                "estimate; retry policy, graph recovery, dependencies and fences may "
                "change scheduling.",
            },
        ],
    }


class DashboardCache:
    """One bounded refresh at a time, including explicit refresh requests."""

    def __init__(self, provider: NativeTelemetry, ttl: float):
        self.provider, self.ttl = provider, ttl
        self._value: dict[str, Any] | None = None
        self._loaded_at = float("-inf")
        self._lock = threading.Lock()

    def get(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            age = time.monotonic() - self._loaded_at
            # Explicit refresh cannot force database calls faster than five seconds.
            if self._value is None or age >= (5 if refresh else self.ttl):
                self._value = self.provider.collect()
                self._loaded_at = time.monotonic()
            return copy.deepcopy(self._value)
