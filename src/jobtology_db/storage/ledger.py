from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, create_engine, text

from jobtology_db.contracts.fetch import (
    FetchAttempt,
    RunMode,
    RunState,
    SourceSnapshot,
)
from jobtology_db.rights import SourceActivationCheck


class FetchLedger(Protocol):
    def start_run(
        self, connector_run_id: str, run_id: str, source_id: str, mode: RunMode
    ) -> None: ...

    def plan_request(
        self,
        connector_run_id: str,
        request_fingerprint: str,
        partition_id: str,
        page_number: int | None,
        request_url_redacted: str,
    ) -> None: ...

    def record_attempt(self, attempt: FetchAttempt, snapshot: SourceSnapshot | None) -> None: ...

    def mark_fetch_complete(
        self,
        connector_run_id: str,
        planned_request_count: int,
        successful_request_count: int,
        attempt_ids: Sequence[str],
        selected_observation_ids: Sequence[str],
    ) -> None: ...

    def fail_run(self, connector_run_id: str, error_code: str) -> None: ...


def stable_id_set_hash(values: Sequence[str]) -> str:
    material = "\n".join(sorted(values)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


class PostgresFetchLedger:
    def __init__(self, database_url: str, *, rights_check: SourceActivationCheck) -> None:
        if not rights_check.allowed:
            raise ValueError("PostgreSQL fetch runs require an allowed rights policy")
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self.rights_check = rights_check

    def start_run(self, connector_run_id: str, run_id: str, source_id: str, mode: RunMode) -> None:
        if source_id != self.rights_check.source_id:
            raise ValueError("Rights policy source does not match the connector source")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO control.connector_run
                        (connector_run_id, run_id, source_id, connector_version, mode, state, stage,
                         started_at, rights_registry_revision, rights_policy_version,
                         rights_policy_hash)
                    VALUES
                        (:connector_run_id, :run_id, :source_id, :connector_version, :mode,
                         'RUNNING', 'FETCHING', :started_at, :rights_registry_revision,
                         :rights_policy_version, :rights_policy_hash)
                    """
                ),
                {
                    "connector_run_id": connector_run_id,
                    "run_id": run_id,
                    "source_id": source_id,
                    "connector_version": "fetch-v1",
                    "mode": mode.value,
                    "started_at": datetime.now(UTC),
                    "rights_registry_revision": self.rights_check.registry_revision,
                    "rights_policy_version": self.rights_check.policy_version,
                    "rights_policy_hash": self.rights_check.policy_hash,
                },
            )

    def plan_request(
        self,
        connector_run_id: str,
        request_fingerprint: str,
        partition_id: str,
        page_number: int | None,
        request_url_redacted: str,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO control.connector_request
                        (connector_run_id, request_fingerprint, partition_id, page_number,
                         request_url_redacted)
                    VALUES
                        (:connector_run_id, :request_fingerprint, :partition_id, :page_number,
                         :request_url_redacted)
                    ON CONFLICT (connector_run_id, request_fingerprint) DO NOTHING
                    """
                ),
                {
                    "connector_run_id": connector_run_id,
                    "request_fingerprint": request_fingerprint,
                    "partition_id": partition_id,
                    "page_number": page_number,
                    "request_url_redacted": request_url_redacted,
                },
            )

    def record_attempt(self, attempt: FetchAttempt, snapshot: SourceSnapshot | None) -> None:
        with self.engine.begin() as connection:
            if snapshot is not None:
                connection.execute(
                    text(
                        """
                        INSERT INTO raw_manifest.source_snapshot
                            (snapshot_id, source_id, content_sha256, byte_length, mime_type,
                             raw_object_path, first_observed_at)
                        VALUES
                            (:snapshot_id, :source_id, :content_sha256, :byte_length, :mime_type,
                             :raw_object_path, :first_observed_at)
                        ON CONFLICT (source_id, content_sha256) DO NOTHING
                        """
                    ),
                    snapshot.model_dump(),
                )
            connection.execute(
                text(
                    """
                    INSERT INTO raw_manifest.fetch_observation
                        (observation_id, connector_run_id, source_id, request_fingerprint,
                         response_ordinal, attempt_no, requested_at, retrieved_at, http_status,
                         request_url_redacted, response_headers, outcome, error_code, snapshot_id,
                         selected)
                    VALUES
                        (:observation_id, :connector_run_id, :source_id, :request_fingerprint,
                         :response_ordinal, :attempt_no, :requested_at, :retrieved_at, :http_status,
                         :request_url_redacted, CAST(:response_headers AS jsonb), :outcome,
                         :error_code, :snapshot_id, :selected)
                    """
                ),
                {
                    **attempt.model_dump(exclude={"partition_id", "page_number"}),
                    "response_headers": __import__("json").dumps(attempt.response_headers),
                    "outcome": attempt.outcome.value,
                },
            )
            if attempt.selected:
                connection.execute(
                    text(
                        """
                        UPDATE control.connector_request
                        SET selected_observation_id = :observation_id
                        WHERE connector_run_id = :connector_run_id
                          AND request_fingerprint = :request_fingerprint
                        """
                    ),
                    {
                        "observation_id": attempt.observation_id,
                        "connector_run_id": attempt.connector_run_id,
                        "request_fingerprint": attempt.request_fingerprint,
                    },
                )

    def mark_fetch_complete(
        self,
        connector_run_id: str,
        planned_request_count: int,
        successful_request_count: int,
        attempt_ids: Sequence[str],
        selected_observation_ids: Sequence[str],
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE control.connector_run
                    SET stage = 'FETCHED', fetch_completed_at = :completed_at,
                        planned_request_count = :planned,
                        successful_request_count = :successful,
                        all_attempt_observation_set_hash = :attempt_hash,
                        selected_success_observation_set_hash = :selected_hash
                    WHERE connector_run_id = :connector_run_id AND state = 'RUNNING'
                    """
                ),
                {
                    "connector_run_id": connector_run_id,
                    "completed_at": datetime.now(UTC),
                    "planned": planned_request_count,
                    "successful": successful_request_count,
                    "attempt_hash": stable_id_set_hash(attempt_ids),
                    "selected_hash": stable_id_set_hash(selected_observation_ids),
                },
            )

    def fail_run(self, connector_run_id: str, error_code: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE control.connector_run
                    SET state = 'FAILED', stage = 'FETCH_FAILED', completed_at = :completed_at,
                        error_code = :error_code
                    WHERE connector_run_id = :connector_run_id AND state = 'RUNNING'
                    """
                ),
                {
                    "connector_run_id": connector_run_id,
                    "completed_at": datetime.now(UTC),
                    "error_code": error_code[:100],
                },
            )


class MemoryFetchLedger:
    """Offline test adapter; production collection uses PostgresFetchLedger."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, object]] = {}
        self.requests: list[dict[str, object]] = []
        self.attempts: list[FetchAttempt] = []
        self.snapshots: dict[str, SourceSnapshot] = {}

    def start_run(self, connector_run_id: str, run_id: str, source_id: str, mode: RunMode) -> None:
        self.runs[connector_run_id] = {
            "run_id": run_id,
            "source_id": source_id,
            "mode": mode,
            "state": RunState.RUNNING,
            "stage": "FETCHING",
        }

    def plan_request(
        self,
        connector_run_id: str,
        request_fingerprint: str,
        partition_id: str,
        page_number: int | None,
        request_url_redacted: str,
    ) -> None:
        self.requests.append(
            {
                "connector_run_id": connector_run_id,
                "request_fingerprint": request_fingerprint,
                "partition_id": partition_id,
                "page_number": page_number,
                "request_url_redacted": request_url_redacted,
            }
        )

    def record_attempt(self, attempt: FetchAttempt, snapshot: SourceSnapshot | None) -> None:
        self.attempts.append(attempt)
        if snapshot is not None:
            self.snapshots.setdefault(snapshot.snapshot_id, snapshot)

    def mark_fetch_complete(
        self,
        connector_run_id: str,
        planned_request_count: int,
        successful_request_count: int,
        attempt_ids: Sequence[str],
        selected_observation_ids: Sequence[str],
    ) -> None:
        self.runs[connector_run_id].update(
            {
                "stage": "FETCHED",
                "planned_request_count": planned_request_count,
                "successful_request_count": successful_request_count,
                "attempt_hash": stable_id_set_hash(attempt_ids),
                "selected_hash": stable_id_set_hash(selected_observation_ids),
            }
        )

    def fail_run(self, connector_run_id: str, error_code: str) -> None:
        self.runs[connector_run_id].update(
            {"state": RunState.FAILED, "stage": "FETCH_FAILED", "error_code": error_code}
        )
