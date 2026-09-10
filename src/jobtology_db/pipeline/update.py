from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, text

from jobtology_db.connectors.base import Connector
from jobtology_db.connectors.sources import build_connector, source_activation_check
from jobtology_db.contracts.fetch import RunMode
from jobtology_db.contracts.processing import PROCESSABLE_SOURCES, PROCESSOR_VERSION, digest
from jobtology_db.partition_config import (
    derive_ncs_qualification_codes_from_engine,
    derive_qnet_item_codes_from_engine,
    write_partition_codes,
)
from jobtology_db.pipeline.fetch import FetchEngine, RetryPolicy
from jobtology_db.pipeline.process import process_run
from jobtology_db.pipeline.request_security import request_fingerprint
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings
from jobtology_db.storage.ledger import PostgresFetchLedger
from jobtology_db.storage.neo4j_staging import load_neo4j_staging
from jobtology_db.storage.processing import GLOBAL_UPDATE_LOCK, advisory_lock
from jobtology_db.storage.raw_files import RawFileStore

DEPENDENCIES = {"ncs_qualification": "ncs_competency", "qnet_schedule": "ncs_qualification"}


class SourceSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    interval_seconds: int = Field(ge=3600)


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: int = Field(ge=1, le=1)
    retry_seconds: int = Field(ge=60)
    sources: list[SourceSchedule]

    @model_validator(mode="after")
    def check_order(self) -> Self:
        seen: set[str] = set()
        for source in self.sources:
            if source.source_id not in PROCESSABLE_SOURCES or source.source_id in seen:
                raise ValueError("Unsupported or duplicate processing source")
            dependency = DEPENDENCIES.get(source.source_id)
            if dependency and dependency not in seen:
                raise ValueError("Dependencies must precede their consumers")
            seen.add(source.source_id)
        if not seen:
            raise ValueError("Schedule requires at least one source")
        return self


def read_schedule(path: Path) -> Schedule:
    return Schedule.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def due(state: dict[str, Any] | None, now: datetime, configuration_hash: str | None = None) -> bool:
    if state is None:
        return True
    # Respect retry backoff even if configuration changed during an outage.
    if state["state"] == "FAILED" and state.get("next_due_at") and now < state["next_due_at"]:
        return False
    if state["state"] == "RUNNING":
        return True  # Caller owns the global lock: this is a crashed previous invocation.
    if configuration_hash is not None and state.get("configuration_hash") != configuration_hash:
        return True
    return state.get("next_due_at") is None or now >= state["next_due_at"]


def source_state(engine: Engine, source: str) -> dict[str, Any] | None:
    with engine.connect() as c:
        row = (
            c.execute(text("SELECT * FROM control.source_sync WHERE source_id=:s"), {"s": source})
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None


def dependency_settings(
    engine: Engine, settings: Settings, source: str, schedule: Schedule, now: datetime
) -> Settings:
    dependency = DEPENDENCIES.get(source)
    if dependency is None:
        return settings
    interval = next(s.interval_seconds for s in schedule.sources if s.source_id == dependency)
    with engine.connect() as c:
        row = (
            c.execute(
                text("""
            SELECT r.connector_run_id, r.fetch_completed_at
            FROM control.connector_run r JOIN control.processing_run p USING (connector_run_id)
            WHERE r.source_id=:source AND r.mode='SCHEDULED_FULL'
              AND p.state='READY' AND p.processor_version=:version
            ORDER BY r.fetch_completed_at DESC LIMIT 1
        """),
                {"source": dependency, "version": PROCESSOR_VERSION},
            )
            .mappings()
            .one_or_none()
        )
    if row is None or now - row["fetch_completed_at"] > timedelta(seconds=interval * 2):
        raise ProcessingError("DEPENDENCY_MISSING_OR_STALE")
    run_id = row["connector_run_id"]
    if source == "ncs_qualification":
        codes = derive_ncs_qualification_codes_from_engine(
            engine, settings.JOBTOLOGY_RAW_ROOT, run_id
        )
        name, setting = "ncs_qualification_codes.txt", "NCS_QUALIFICATION_CODES_FILE"
    else:
        codes = derive_qnet_item_codes_from_engine(engine, settings.JOBTOLOGY_RAW_ROOT, run_id)
        name, setting = "qnet_item_codes.txt", "QNET_ITEM_CODES_FILE"
    # Runtime partitions belong to the persistent volume, not the read-only image/config tree.
    path = settings.JOBTOLOGY_RAW_ROOT / "runtime" / name
    write_partition_codes(path, codes)
    return settings.model_copy(update={setting: path})


def fetch_source(settings: Settings, connector: Connector, run_id: str) -> str:
    database_url = settings.database_url()
    if database_url is None:
        raise ProcessingError("DATABASE_URL_REQUIRED")
    ledger = PostgresFetchLedger(
        database_url, rights_check=source_activation_check(connector.source_id, settings)
    )

    def before_request() -> None:
        with ledger.engine.connect() as c:
            used = c.scalar(
                text("""
                SELECT count(*) FROM raw_manifest.fetch_observation
                WHERE source_id=:source AND requested_at >= :since
            """),
                {"source": connector.source_id, "since": datetime.now(UTC) - timedelta(days=1)},
            )
        if used is None or used >= settings.JOBTOLOGY_UPDATE_REQUESTS_PER_24H:
            raise ProcessingError("ROLLING_REQUEST_BUDGET_EXHAUSTED")
        time.sleep(settings.JOBTOLOGY_UPDATE_REQUEST_INTERVAL_SECONDS)

    try:
        with httpx.Client(
            timeout=httpx.Timeout(
                connect=settings.JOBTOLOGY_HTTP_CONNECT_TIMEOUT_SECONDS,
                read=settings.JOBTOLOGY_HTTP_READ_TIMEOUT_SECONDS,
                write=settings.JOBTOLOGY_HTTP_READ_TIMEOUT_SECONDS,
                pool=settings.JOBTOLOGY_HTTP_CONNECT_TIMEOUT_SECONDS,
            ),
            follow_redirects=False,
        ) as client:
            fetcher = FetchEngine(
                client=client,
                ledger=ledger,
                raw_store=RawFileStore(settings.JOBTOLOGY_RAW_ROOT),
                retry_policy=RetryPolicy(
                    settings.JOBTOLOGY_HTTP_MAX_ATTEMPTS,
                    settings.JOBTOLOGY_HTTP_MAX_RETRY_AFTER_SECONDS,
                ),
                user_agent=settings.http_user_agent(),
                max_response_bytes=settings.JOBTOLOGY_HTTP_MAX_RESPONSE_BYTES,
                raw_min_free_bytes=settings.JOBTOLOGY_RAW_MIN_FREE_BYTES,
                raw_max_used_fraction=settings.JOBTOLOGY_RAW_MAX_USED_FRACTION,
                before_request=before_request,
            )
            return fetcher.run(
                connector, mode=RunMode.SCHEDULED_FULL, run_id=run_id
            ).connector_run_id
    finally:
        ledger.engine.dispose()


def update_sources(
    engine: Engine,
    settings: Settings,
    schedule: Schedule,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    fetch: Callable[[Settings, Connector, str], str] = fetch_source,
    emit: Callable[[dict[str, Any]], None] = lambda value: None,
    neo4j: bool = False,
) -> list[dict[str, Any]]:
    """One serial, lock-protected tick. This function owns no timer or daemon lifecycle."""
    outcomes: list[dict[str, Any]] = []
    if neo4j and (
        not settings.JOBTOLOGY_NEO4J_URI
        or not settings.secret_value(settings.JOBTOLOGY_NEO4J_PASSWORD)
    ):
        raise ProcessingError("NEO4J_CONFIGURATION_REQUIRED")
    failed: set[str] = set()
    parent_run_id = str(uuid.uuid4())
    with advisory_lock(engine, GLOBAL_UPDATE_LOCK) as lock_connection:
        for entry in schedule.sources:
            source, now = entry.source_id, clock()
            state = source_state(engine, source)
            outcome: dict[str, Any] = {"source_id": source}
            try:
                if state and state["state"] == "FAILED" and not due(state, now):
                    outcome["state"] = "RETRY_WAIT"
                    failed.add(source)
                    outcomes.append(outcome)
                    emit(outcome)
                    continue
                if DEPENDENCIES.get(source) in failed:
                    raise ProcessingError("DEPENDENCY_FAILED")
                effective = dependency_settings(engine, settings, source, schedule, now)
                connector = build_connector(source, effective)
                rights = source_activation_check(source, effective)
                config_hash = digest(
                    [
                        PROCESSOR_VERSION,
                        rights.policy_hash,
                        [request_fingerprint(r) for r in connector.initial_requests()],
                        entry.interval_seconds,
                        neo4j,
                        [settings.JOBTOLOGY_NEO4J_URI, settings.JOBTOLOGY_NEO4J_DATABASE]
                        if neo4j
                        else None,
                    ]
                )
                if not due(state, now, config_hash):
                    outcome["state"] = "NOT_DUE"
                    outcomes.append(outcome)
                    emit(outcome)
                    continue
                # Verify the lock connection is still alive before beginning each source.
                lock_connection.execute(text("SELECT 1"))
                resumable = (
                    state is not None
                    and state.get("configuration_hash") == config_hash
                    and (
                        state["state"] == "RUNNING"
                        or state.get("error_code")
                        in {
                            "OperationalError",
                            "InterfaceError",
                            "GRAPH_LOAD_FAILED",
                        }
                    )
                    and state.get("connector_run_id") is not None
                )
                with engine.begin() as c:
                    c.execute(
                        text("""
                        INSERT INTO control.source_sync
                            (source_id,state,last_attempt_at,configuration_hash)
                        VALUES (:s,'RUNNING',:now,:config)
                        ON CONFLICT (source_id) DO UPDATE SET state='RUNNING',last_attempt_at=:now,
                            configuration_hash=:config,error_code=NULL,
                            connector_run_id=CASE WHEN :resume
                                                 THEN control.source_sync.connector_run_id
                                                 ELSE NULL END
                    """),
                        {"s": source, "now": now, "config": config_hash, "resume": resumable},
                    )
                if resumable:
                    assert state is not None
                    connector_run_id = str(state["connector_run_id"])
                else:
                    connector_run_id = fetch(effective, connector, parent_run_id)
                    with engine.begin() as c:
                        c.execute(
                            text("""
                            UPDATE control.source_sync SET connector_run_id=:run WHERE source_id=:s
                        """),
                            {"run": connector_run_id, "s": source},
                        )
                summary = process_run(
                    engine, effective.JOBTOLOGY_RAW_ROOT, connector_run_id, effective
                )
                if summary.state != "READY":
                    raise ProcessingError("PROCESSING_REVIEW_REQUIRED")
                lock_connection.execute(text("SELECT 1"))
                if neo4j:
                    load_neo4j_staging(engine, effective, summary.processing_run_id)
                completed = clock()
                with engine.begin() as c:
                    c.execute(
                        text("""
                        UPDATE control.source_sync SET state='READY',last_success_at=:now,
                            next_due_at=:due,processing_run_id=:run,content_set_hash=:hash,
                            normalized_set_hash=:normalized_hash,
                            error_code=NULL WHERE source_id=:s
                    """),
                        {
                            "s": source,
                            "now": completed,
                            "due": completed + timedelta(seconds=entry.interval_seconds),
                            "run": summary.processing_run_id,
                            "hash": summary.content_set_hash,
                            "normalized_hash": summary.normalized_set_hash,
                        },
                    )
                outcome.update(
                    state="READY",
                    processing_run_id=summary.processing_run_id,
                    records=summary.records,
                    new_revisions=summary.new_revisions,
                    changed=state is None
                    or state.get("normalized_set_hash") != summary.normalized_set_hash,
                )
            except Exception as error:
                failed.add(source)
                # Never print raw exception messages from HTTP/DB drivers or source configuration.
                code = str(error) if isinstance(error, ProcessingError) else type(error).__name__
                retry_at = clock() + timedelta(seconds=schedule.retry_seconds)
                with engine.begin() as c:
                    c.execute(
                        text("""
                        INSERT INTO control.source_sync
                            (source_id,state,last_attempt_at,next_due_at,error_code)
                        VALUES (:s,'FAILED',:now,:due,:code)
                        ON CONFLICT (source_id) DO UPDATE SET state='FAILED',next_due_at=:due,
                            error_code=:code
                    """),
                        {"s": source, "now": now, "due": retry_at, "code": code[:100]},
                    )
                outcome.update(state="FAILED", error_code=code[:100])
            outcomes.append(outcome)
            emit(outcome)
    return outcomes


def json_event(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)
