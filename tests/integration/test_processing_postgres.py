"""Opt-in integration tests against an explicitly named disposable *_test database."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from jobtology_db.connectors.base import Connector
from jobtology_db.connectors.sources import build_connector, source_activation_check
from jobtology_db.contracts.fetch import RunMode
from jobtology_db.pipeline.fetch import FetchEngine
from jobtology_db.pipeline.process import process_run
from jobtology_db.pipeline.request_security import DEFAULT_SECRET_QUERY_NAMES
from jobtology_db.pipeline.update import (
    Schedule,
    SourceSchedule,
    fetch_source,
    read_schedule,
    update_sources,
)
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings
from jobtology_db.storage.ledger import PostgresFetchLedger
from jobtology_db.storage.neo4j_staging import load_neo4j_staging
from jobtology_db.storage.processing import (
    GLOBAL_UPDATE_LOCK,
    StagingLoader,
    advisory_lock,
    read_raw,
    run_inputs,
)
from jobtology_db.storage.raw_files import RawFileStore


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get("JOBTOLOGY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set JOBTOLOGY_TEST_DATABASE_URL to a disposable PostgreSQL *_test database")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Integration database must have a name ending in _test")
    environment = {**os.environ, "JOBTOLOGY_PIPELINE_DATABASE_URL": url}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=environment,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        pytest.fail("Test database migration failed; connection details suppressed")
    db = create_engine(url, pool_pre_ping=True)
    yield db
    db.dispose()


def settings_for(engine: Engine, raw_root: Path) -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] BaseSettings runtime-only parameter
        JOBTOLOGY_RAW_ROOT=raw_root,
        JOBTOLOGY_PIPELINE_DATABASE_URL=SecretStr(engine.url.render_as_string(hide_password=False)),
        DATA_GO_KR_SERVICE_KEY=SecretStr("offline-fixture-key"),
    )


def fetch_fixture(
    engine: Engine,
    settings: Settings,
    payload: dict[str, Any],
    *,
    mode: RunMode = RunMode.SCHEDULED_FULL,
    max_pages: int | None = None,
) -> str:
    connector = build_connector("alio_organization", settings)
    ledger = PostgresFetchLedger(
        engine.url.render_as_string(hide_password=False),
        rights_check=source_activation_check("alio_organization", settings),
    )
    try:
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ) as client:
            return (
                FetchEngine(
                    client=client,
                    raw_store=RawFileStore(settings.JOBTOLOGY_RAW_ROOT),
                    ledger=ledger,
                    raw_min_free_bytes=0,
                )
                .run(connector, mode=mode, max_pages=max_pages)
                .connector_run_id
            )
    finally:
        ledger.engine.dispose()


def organization_document(code: str, **fields: Any) -> dict[str, Any]:
    return {
        "resultCode": 200,
        "totalCount": 1,
        "result": [{"instCd": code, "instNm": "테스트 기관", **fields}],
    }


def test_replay_and_new_observation_reuse_revisions(engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(engine, tmp_path)
    payload = organization_document(str(uuid.uuid4()))
    run = fetch_fixture(engine, settings, payload)
    first = process_run(engine, tmp_path, run, settings)
    replay = process_run(engine, tmp_path, run, settings)
    assert first.state == "READY" and first.records == 1 and first.new_revisions == 1
    assert replay.reused_documents == 1 and replay.new_revisions == 0
    assert replay.processing_run_id == first.processing_run_id
    later_run = fetch_fixture(engine, settings, payload)
    later = process_run(engine, tmp_path, later_run, settings)
    assert later.reused_documents == 1 and later.new_revisions == 0
    assert later.normalized_set_hash == first.normalized_set_hash
    assert later.processing_run_id != first.processing_run_id
    _, refs = run_inputs(engine, run)
    (tmp_path / refs[0].raw_object_path).write_bytes(b"corrupt")
    with pytest.raises(ProcessingError, match="RAW_INTEGRITY_FAILED"):
        process_run(engine, tmp_path, run, settings)


def test_changed_source_payload_but_unchanged_semantic_facts(
    engine: Engine, tmp_path: Path
) -> None:
    settings = settings_for(engine, tmp_path)
    code = str(uuid.uuid4())
    first = process_run(
        engine,
        tmp_path,
        fetch_fixture(engine, settings, organization_document(code, providerCounter=1)),
        settings,
    )
    later = process_run(
        engine,
        tmp_path,
        fetch_fixture(engine, settings, organization_document(code, providerCounter=2)),
        settings,
    )
    assert later.new_revisions == 1
    assert first.content_set_hash != later.content_set_hash
    assert first.normalized_set_hash == later.normalized_set_hash


def test_quarantine_is_accounted_and_never_ready(engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(engine, tmp_path)
    run = fetch_fixture(
        engine, settings, organization_document(str(uuid.uuid4()), fndnYmd="20260230")
    )
    summary = process_run(engine, tmp_path, run, settings)
    assert summary.state == "REVIEW_REQUIRED" and summary.rejected == 1 and summary.records == 0
    with engine.connect() as c:
        assert (
            c.scalar(
                text("SELECT count(*) FROM quality.rejected_row WHERE error_code='INVALID_DATE'")
            )
            >= 1
        )


def test_capped_backfill_cannot_be_marked_complete(engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(engine, tmp_path)
    payload = organization_document(str(uuid.uuid4()))
    payload["totalCount"] = 101
    run = fetch_fixture(engine, settings, payload, mode=RunMode.BACKFILL, max_pages=1)
    with pytest.raises(ProcessingError, match="MISSING_OR_DUPLICATE_PAGES"):
        process_run(engine, tmp_path, run, settings)


def test_document_checkpoint_survives_interruption(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(engine, tmp_path)
    run = fetch_fixture(engine, settings, organization_document(str(uuid.uuid4())))
    original = StagingLoader.attach

    def interrupted(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated interruption after document commit")

    monkeypatch.setattr(StagingLoader, "attach", interrupted)
    with pytest.raises(RuntimeError):
        process_run(engine, tmp_path, run, settings)
    monkeypatch.setattr(StagingLoader, "attach", original)
    resumed = process_run(engine, tmp_path, run, settings)
    assert resumed.state == "READY" and resumed.reused_documents == 1 and resumed.new_revisions == 0


def test_overlapping_updaters_cannot_acquire_lock(engine: Engine) -> None:
    with (
        advisory_lock(engine, GLOBAL_UPDATE_LOCK),
        pytest.raises(ProcessingError, match="PIPELINE_BUSY"),
        advisory_lock(engine, GLOBAL_UPDATE_LOCK),
    ):
        pytest.fail("Second session acquired the lock")


def test_updater_cadence_and_recovery_without_upstream_requests(
    engine: Engine, tmp_path: Path
) -> None:
    settings = settings_for(engine, tmp_path)
    # This is the dedicated *_test database; no production scheduler rows are touched.
    with engine.begin() as c:
        c.execute(text("DELETE FROM control.source_sync WHERE source_id='alio_organization'"))
    schedule = Schedule(
        version=1,
        retry_seconds=60,
        sources=[SourceSchedule(source_id="alio_organization", interval_seconds=86400)],
    )
    now = datetime.now(UTC)
    calls = 0
    code = str(uuid.uuid4())

    def fetch(effective: Settings, connector: Connector, parent: str) -> str:
        nonlocal calls
        calls += 1
        return fetch_fixture(engine, effective, organization_document(code))

    first = update_sources(engine, settings, schedule, clock=lambda: now, fetch=fetch)
    second = update_sources(engine, settings, schedule, clock=lambda: now, fetch=fetch)
    assert first[0]["state"] == "READY" and first[0]["changed"] is True
    assert second[0]["state"] == "NOT_DUE" and calls == 1
    third = update_sources(
        engine, settings, schedule, clock=lambda: now + timedelta(days=1), fetch=fetch
    )
    assert third[0]["state"] == "READY" and third[0]["changed"] is False and calls == 2
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE control.source_sync SET state='RUNNING' WHERE source_id='alio_organization'"
            )
        )
    resumed = update_sources(
        engine, settings, schedule, clock=lambda: now + timedelta(days=1), fetch=fetch
    )
    assert resumed[0]["state"] == "READY" and calls == 2


def test_updater_records_failures_and_backs_off(engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(engine, tmp_path)
    with engine.begin() as c:
        c.execute(text("DELETE FROM control.source_sync WHERE source_id='alio_organization'"))
    schedule = Schedule(
        version=1,
        retry_seconds=3600,
        sources=[SourceSchedule(source_id="alio_organization", interval_seconds=86400)],
    )
    now = datetime.now(UTC)

    def failed_fetch(effective: Settings, connector: Connector, parent: str) -> str:
        raise RuntimeError("fake secret should not enter scheduler error columns")

    failed = update_sources(engine, settings, schedule, clock=lambda: now, fetch=failed_fetch)
    waiting = update_sources(engine, settings, schedule, clock=lambda: now, fetch=failed_fetch)
    assert failed[0] == {
        "source_id": "alio_organization",
        "state": "FAILED",
        "error_code": "RuntimeError",
    }
    assert waiting[0]["state"] == "RETRY_WAIT"


def test_optional_neo4j_staging_load_is_idempotent(engine: Engine, tmp_path: Path) -> None:
    uri = os.environ.get("JOBTOLOGY_TEST_NEO4J_URI")
    password = os.environ.get("JOBTOLOGY_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.skip("Set JOBTOLOGY_TEST_NEO4J_URI/PASSWORD for a disposable Neo4j instance")
    settings = settings_for(engine, tmp_path).model_copy(
        update={
            "JOBTOLOGY_NEO4J_URI": uri,
            "JOBTOLOGY_NEO4J_PASSWORD": SecretStr(password),
        }
    )
    run = fetch_fixture(engine, settings, organization_document(str(uuid.uuid4())))
    summary = process_run(engine, tmp_path, run, settings)
    first = load_neo4j_staging(engine, settings, summary.processing_run_id)
    second = load_neo4j_staging(engine, settings, summary.processing_run_id)
    assert first == second
    assert first["records"] == 1 and first["serving_scope"] == "STAGING"


def test_production_fetch_wrapper_stops_before_http_at_budget_limit(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_for(engine, tmp_path).model_copy(
        update={
            "JOBTOLOGY_UPDATE_REQUESTS_PER_24H": 1,
            "JOBTOLOGY_UPDATE_REQUEST_INTERVAL_SECONDS": 0,
        }
    )
    fetch_fixture(engine, settings, organization_document(str(uuid.uuid4())))
    actual_client = httpx.Client
    calls = 0

    def forbidden_request(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("Request escaped the budget guard")

    def offline_client(*args: Any, **kwargs: Any) -> httpx.Client:
        return actual_client(*args, transport=httpx.MockTransport(forbidden_request), **kwargs)

    monkeypatch.setattr(httpx, "Client", offline_client)
    with pytest.raises(ProcessingError, match="ROLLING_REQUEST_BUDGET_EXHAUSTED"):
        fetch_source(settings, build_connector("alio_organization", settings), str(uuid.uuid4()))
    assert calls == 0


def test_saved_six_source_corpus_end_to_end(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit opt-in: READ local saved inputs; write only the disposable test DB/raw directory.

    All HTTP is handled by MockTransport. There is no network fallback on a missing fixture.
    Exercises the production fetch_source wrapper, dependency regeneration, processing and graph
    staging at full corpus scale, then an unchanged tick and a changed JOB-ALIO list/detail pair.
    """
    if os.environ.get("JOBTOLOGY_TEST_REPLAY_SAVED_CORPUS") != "1":
        pytest.skip(
            "Set JOBTOLOGY_TEST_REPLAY_SAVED_CORPUS=1 to use the local saved six-source corpus"
        )
    uri = os.environ.get("JOBTOLOGY_TEST_NEO4J_URI")
    password = os.environ.get("JOBTOLOGY_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.skip("The full-corpus replay requires a disposable Neo4j test instance")
    original = Settings()
    original_url = original.database_url()
    assert original_url is not None
    assert make_url(original_url) != engine.url, "Input and disposable output databases must differ"
    runs = {
        "ncs_career_path": "c19960d8-71b6-45d9-a282-8085bb9f05a0",
        "ncs_competency": "de3d746a-4b2f-43ae-95d3-ea0bf0d30c2e",
        "ncs_qualification": "f506c795-fcba-4109-b6e0-54d4f38b4e14",
        "qnet_schedule": "1095603e-8120-41a7-afdb-f46c27ac9504",
        "alio_organization": "7af03ee3-a191-4a0b-8b85-06223e0fa548",
        "job_alio": "35dfb121-83c9-417d-8e54-fbd66eb6c563",
    }
    expected = {
        "ncs_career_path": 12864,
        "ncs_competency": 15520,
        "ncs_qualification": 87,
        "qnet_schedule": 56,
        "alio_organization": 355,
        "job_alio": 1020,
    }

    # Normalize only secrets/query ordering; every other request parameter must match a saved URL.
    def key(url: str) -> str:
        parsed = urlsplit(url)
        return json.dumps(
            [
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                sorted(
                    (k, v)
                    for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                    if k.casefold() not in DEFAULT_SECRET_QUERY_NAMES
                ),
            ]
        )

    responses: dict[str, tuple[bytes, str]] = {}
    input_db = create_engine(original_url)
    try:
        for source, run_id in runs.items():
            run, inputs = run_inputs(input_db, run_id)
            assert run["source_id"] == source
            with input_db.connect() as c:
                urls = dict(
                    c.execute(
                        text("""
                    SELECT selected_observation_id,request_url_redacted
                    FROM control.connector_request WHERE connector_run_id=:id
                """),
                        {"id": run_id},
                    )
                    .tuples()
                    .all()
                )
            for item in inputs:
                value = (read_raw(original.JOBTOLOGY_RAW_ROOT, item), item.mime_type)
                request_key = key(urls[item.observation_id])
                assert request_key not in responses or responses[request_key] == value
                responses[request_key] = value
    finally:
        input_db.dispose()

    calls = 0
    modify_job = False

    def response(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        request_key = key(str(request.url))
        assert request_key in responses, "Request did not match any pinned saved response"
        body, mime = responses[request_key]
        if modify_job and request.url.path.startswith("/1051000/recruitment/"):
            document = json.loads(body)
            items = document["result"]
            records = cast(list[dict[str, Any]], items if isinstance(items, list) else [items])
            for row in records:
                if row["recrutPblntSn"] == 304534:
                    row["recrutPbancTtl"] += " (업데이트 테스트)"
            body = json.dumps(document, ensure_ascii=False).encode()
        return httpx.Response(200, content=body, headers={"content-type": mime})

    actual_client = httpx.Client

    def offline_client(*args: Any, **kwargs: Any) -> httpx.Client:
        return actual_client(*args, transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(httpx, "Client", offline_client)
    settings = settings_for(engine, tmp_path).model_copy(
        update={
            "JOBTOLOGY_NEO4J_URI": uri,
            "JOBTOLOGY_NEO4J_PASSWORD": SecretStr(password),
            "JOBTOLOGY_UPDATE_REQUEST_INTERVAL_SECONDS": 0,
            "JOBTOLOGY_UPDATE_REQUESTS_PER_24H": 2000,  # simulated initial and changed daily fetch
            "NCS_CAREER_PATH_DOWNLOAD_URL": original.NCS_CAREER_PATH_DOWNLOAD_URL,
            "QNET_YEARS": "2026,2027",
            "JOB_ALIO_ONGOING_ONLY": True,
        }
    )
    # Only the explicitly guarded disposable *_test database is modified.
    with engine.begin() as c:
        c.execute(text("DELETE FROM control.source_sync"))
    schedule = read_schedule(Path("config/pipeline.yaml"))
    now = datetime.now(UTC)

    def emit(outcome: dict[str, Any]) -> None:
        print(json.dumps(outcome, ensure_ascii=False), flush=True)

    first = update_sources(engine, settings, schedule, clock=lambda: now, emit=emit, neo4j=True)
    assert all(result["state"] == "READY" for result in first), first
    assert {row["source_id"]: row["records"] for row in first} == expected
    assert calls == 878
    immediate = update_sources(engine, settings, schedule, clock=lambda: now, neo4j=True)
    assert all(result["state"] == "NOT_DUE" for result in immediate)
    assert calls == 878, "Not-due tick performed an HTTP request"

    for result in first:
        with engine.connect() as c:
            fetch_id = c.scalar(
                text("""
                SELECT connector_run_id FROM control.processing_run WHERE processing_run_id=:id
            """),
                {"id": result["processing_run_id"]},
            )
        replay = process_run(engine, tmp_path, fetch_id, settings)
        assert replay.new_revisions == 0 and replay.reused_documents == replay.documents
        loaded = load_neo4j_staging(engine, settings, replay.processing_run_id)
        assert loaded["records"] == expected[result["source_id"]]

    modify_job = True
    with engine.begin() as c:
        c.execute(
            text("""
            UPDATE control.source_sync SET next_due_at=:now WHERE source_id='job_alio'
        """),
            {"now": now},
        )
    changed = update_sources(engine, settings, schedule, clock=lambda: now, emit=emit, neo4j=True)
    job = next(row for row in changed if row["source_id"] == "job_alio")
    assert job["state"] == "READY" and job["changed"] is True
    assert job["records"] == 1020 and job["new_revisions"] == 2
    assert all(row["state"] == "NOT_DUE" for row in changed if row["source_id"] != "job_alio")
    assert calls == 1394
    print(
        json.dumps(
            {
                "event": "saved_corpus_verified",
                "records": sum(expected.values()),
                "replayed_http_requests": calls,
                "live_upstream_requests": 0,
            }
        ),
        flush=True,
    )
