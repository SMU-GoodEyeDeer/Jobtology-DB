"""A durable, serialized queue. Only the host worker may execute queued profiles."""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobtology_db.admin.config import ACTION_ID, private_parent

STATES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN"}
PUBLIC_FIELDS = (
    "id",
    "action_id",
    "kind",
    "state",
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
    "requested_by",
    "summary",
)


class QueueConflict(ValueError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job.get(key) for key in PUBLIC_FIELDS}


class JobStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            with connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA busy_timeout=5000")
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        private_parent(self.path)
        with self.connection() as connection:
            # DELETE journaling works on a local bind mount; do not place this DB on NFS.
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, action_id TEXT NOT NULL, kind TEXT NOT NULL,
                  state TEXT NOT NULL CHECK(state IN
                    ('QUEUED','RUNNING','SUCCEEDED','FAILED','UNKNOWN')),
                  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                  updated_at TEXT NOT NULL, requested_by TEXT NOT NULL,
                  summary TEXT, idempotency_key TEXT NOT NULL UNIQUE,
                  profile_sha256 TEXT NOT NULL, worker_id TEXT
                );
                CREATE TABLE IF NOT EXISTS worker (
                  singleton INTEGER PRIMARY KEY CHECK(singleton=1), worker_id TEXT NOT NULL,
                  heartbeat_at TEXT NOT NULL, job_id TEXT
                );
                CREATE INDEX IF NOT EXISTS queue_order ON jobs(state,created_at,id);
            """)
        private_parent(self.path)

    def enqueue(
        self,
        action_id: str,
        actor: str,
        idempotency_key: str,
        *,
        kind: str,
        profile_sha256: str,
    ) -> dict[str, Any]:
        if not ACTION_ID.fullmatch(action_id) or kind not in {"refresh_due", "load_jobkorea"}:
            raise ValueError("invalid action")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", idempotency_key):
            raise ValueError("invalid idempotency key")
        if not actor or len(actor) > 128 or not re.fullmatch(r"[0-9a-f]{64}", profile_sha256):
            raise ValueError("invalid job metadata")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing:
                if (
                    existing["action_id"],
                    existing["kind"],
                    existing["requested_by"],
                    existing["profile_sha256"],
                ) != (
                    action_id,
                    kind,
                    actor,
                    profile_sha256,
                ):
                    raise QueueConflict("idempotency key already used for another request")
                return dict(existing)
            if connection.execute(
                "SELECT 1 FROM jobs WHERE state IN ('QUEUED','RUNNING','UNKNOWN') LIMIT 1"
            ).fetchone():
                raise QueueConflict("a pending or uncertain job requires operator attention")
            timestamp, job_id = now(), str(uuid.uuid4())
            connection.execute(
                "INSERT INTO jobs(id,action_id,kind,state,created_at,updated_at,requested_by,"
                "idempotency_key,profile_sha256) VALUES(?,?,?,'QUEUED',?,?,?,?,?)",
                (
                    job_id,
                    action_id,
                    kind,
                    timestamp,
                    timestamp,
                    actor,
                    idempotency_key,
                    profile_sha256,
                ),
            )
            connection.commit()
            return dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list_jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC,id DESC LIMIT ?",
                    (max(1, min(limit, 100)),),
                )
            ]

    def get_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            return dict(row) if row else None

    def has_pending(self) -> bool:
        with self.connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM jobs WHERE state IN ('QUEUED','RUNNING','UNKNOWN') LIMIT 1"
                ).fetchone()
                is not None
            )

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM jobs WHERE state IN ('RUNNING','UNKNOWN') LIMIT 1"
            ).fetchone():
                return None
            row = connection.execute(
                "SELECT * FROM jobs WHERE state='QUEUED' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            timestamp = now()
            connection.execute(
                "UPDATE jobs SET state='RUNNING',worker_id=?,started_at=?,updated_at=? WHERE id=?",
                (worker_id, timestamp, timestamp, row["id"]),
            )
            connection.commit()
            return dict(
                connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            )

    def heartbeat(self, worker_id: str, job_id: str | None = None) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO worker VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET "
                "worker_id=excluded.worker_id,heartbeat_at=excluded.heartbeat_at,job_id=excluded.job_id",
                (worker_id, now(), job_id),
            )

    def worker_status(self) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT worker_id,heartbeat_at,job_id FROM worker").fetchone()
            return dict(row) if row else None

    def stop_worker(self, worker_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM worker WHERE worker_id=?", (worker_id,))

    def finish(self, job_id: str, state: str, summary: str) -> None:
        if state not in {"SUCCEEDED", "FAILED", "UNKNOWN"} or len(summary) > 500:
            raise ValueError("invalid terminal result")
        with self.connection() as connection:
            timestamp = now()
            result = connection.execute(
                "UPDATE jobs SET state=?,summary=?,finished_at=?,updated_at=? "
                "WHERE id=? AND state='RUNNING'",
                (state, summary, timestamp, timestamp, job_id),
            )
            if result.rowcount != 1:
                raise QueueConflict("job is not running")

    def abandon_running(
        self, summary: str = "Worker restarted; outcome requires operator review."
    ) -> int:
        """Call only while holding the exclusive host worker lock. Never retry orphans."""
        with self.connection() as connection:
            timestamp = now()
            result = connection.execute(
                "UPDATE jobs SET state='UNKNOWN',summary=?,finished_at=?,updated_at=? "
                "WHERE state='RUNNING'",
                (summary[:500], timestamp, timestamp),
            )
            return result.rowcount
