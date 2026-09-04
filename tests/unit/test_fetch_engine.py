from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from jobtology_db.connectors.base import DeclaredTotalConnector, Pagination, SingleFileConnector
from jobtology_db.contracts.fetch import ObservationOutcome, RunMode, RunState
from jobtology_db.pipeline.fetch import FetchEngine, FetchRunError, RetryPolicy
from jobtology_db.storage.ledger import MemoryFetchLedger
from jobtology_db.storage.raw_files import RawFileStore


def connector(secret: str = "provider-secret", *, page_size: int = 100) -> DeclaredTotalConnector:
    return DeclaredTotalConnector(
        source_id="fixture",
        display_name="Fixture source",
        endpoint="https://fixture.example/records",
        allowed_hosts=frozenset({"fixture.example"}),
        partitions=(("all", {"serviceKey": secret, "format": "json"}),),
        secret_param_names=frozenset({"serviceKey"}),
        pagination=Pagination("pageNo", "numOfRows", 1, page_size),
    )


def response_body(*, total: int = 1, page: int = 1, size: int = 100) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"totalCount": total, "pageNo": page, "numOfRows": size},
            }
        },
        separators=(",", ":"),
    ).encode()


def build_engine(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    retry_policy: RetryPolicy | None = None,
    sleeps: list[float] | None = None,
    max_response_bytes: int = 64 * 1024 * 1024,
) -> tuple[FetchEngine, MemoryFetchLedger, httpx.Client]:
    ledger = MemoryFetchLedger()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    engine = FetchEngine(
        client=client,
        raw_store=RawFileStore(tmp_path),
        ledger=ledger,
        retry_policy=retry_policy,
        max_response_bytes=max_response_bytes,
        raw_min_free_bytes=0,
        sleeper=(sleeps if sleeps is not None else []).append,
    )
    return engine, ledger, client


def test_success_records_selected_observation_snapshot_and_redacted_metadata(
    tmp_path: Path,
) -> None:
    secret = "unique-provider-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["serviceKey"] == secret
        return httpx.Response(
            200,
            content=response_body(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "ETag": '"revision-1"',
                "Set-Cookie": "session=must-not-persist",
            },
            request=request,
        )

    engine, ledger, client = build_engine(tmp_path, handler)
    with client:
        summary = engine.run(
            connector(secret),
            mode=RunMode.BACKFILL,
            run_id="run-1",
            connector_run_id="connector-run-1",
        )

    assert summary.planned_request_count == 1
    assert summary.successful_request_count == 1
    assert summary.attempt_count == 1
    assert ledger.runs["connector-run-1"]["stage"] == "FETCHED"
    assert len(ledger.attempts) == 1
    attempt = ledger.attempts[0]
    assert attempt.outcome is ObservationOutcome.SELECTED_SUCCESS
    assert attempt.selected is True
    assert attempt.snapshot_id in ledger.snapshots
    assert attempt.response_headers == {
        "content-type": "application/json; charset=utf-8",
        "content-length": str(len(response_body())),
        "etag": '"revision-1"',
    }
    assert secret not in attempt.request_url_redacted
    assert "must-not-persist" not in repr(ledger.__dict__)
    snapshot = ledger.snapshots[attempt.snapshot_id]
    assert (tmp_path / snapshot.raw_object_path).read_bytes() == response_body()


def test_retryable_http_and_transport_errors_append_attempts_then_select_success(
    tmp_path: Path,
) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": "999", "Set-Cookie": "secret-cookie"},
                request=request,
            )
        if calls == 2:
            raise httpx.ConnectTimeout("simulated timeout", request=request)
        return httpx.Response(
            200,
            content=response_body(),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    engine, ledger, client = build_engine(
        tmp_path,
        handler,
        retry_policy=RetryPolicy(max_attempts=3, max_retry_after_seconds=7),
        sleeps=sleeps,
    )
    with client:
        summary = engine.run(
            connector(),
            mode=RunMode.BACKFILL,
            run_id="run-retry",
            connector_run_id="connector-run-retry",
        )

    assert calls == 3
    assert sleeps == [7, 2]
    assert summary.attempt_count == 3
    assert [attempt.attempt_no for attempt in ledger.attempts] == [1, 2, 3]
    assert [attempt.outcome for attempt in ledger.attempts] == [
        ObservationOutcome.HTTP_ERROR,
        ObservationOutcome.TRANSPORT_ERROR,
        ObservationOutcome.SELECTED_SUCCESS,
    ]
    assert [attempt.selected for attempt in ledger.attempts] == [False, False, True]
    assert [attempt.snapshot_id is not None for attempt in ledger.attempts] == [
        False,
        False,
        True,
    ]
    assert ledger.attempts[0].response_headers == {"retry-after": "999"}


def test_non_retryable_http_failure_is_redacted_and_marks_run_failed(tmp_path: Path) -> None:
    secret = "never-leak-this-key"
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            headers={"Content-Type": "application/json", "Set-Cookie": secret},
            request=request,
        )

    engine, ledger, client = build_engine(tmp_path, handler, sleeps=sleeps)
    with client, pytest.raises(FetchRunError) as captured:
        engine.run(
            connector(secret),
            mode=RunMode.BACKFILL,
            run_id="run-fail",
            connector_run_id="connector-run-fail",
        )

    assert calls == 1
    assert sleeps == []
    assert captured.value.error_code == "HTTP_401"
    assert secret not in str(captured.value)
    assert secret not in repr(ledger.__dict__)
    assert ledger.runs["connector-run-fail"] == {
        "run_id": "run-fail",
        "source_id": "fixture",
        "mode": RunMode.BACKFILL,
        "state": RunState.FAILED,
        "stage": "FETCH_FAILED",
        "error_code": "HTTP_401",
    }
    assert len(ledger.attempts) == 1
    assert ledger.attempts[0].outcome is ObservationOutcome.HTTP_ERROR
    assert ledger.attempts[0].snapshot_id is None


def test_exhausted_retryable_failure_records_every_attempt(tmp_path: Path) -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3"}, request=request)

    engine, ledger, client = build_engine(
        tmp_path,
        handler,
        retry_policy=RetryPolicy(max_attempts=3, max_retry_after_seconds=60),
        sleeps=sleeps,
    )
    with client, pytest.raises(FetchRunError, match="HTTP_429"):
        engine.run(
            connector(),
            mode=RunMode.BACKFILL,
            run_id="run-exhausted",
            connector_run_id="connector-run-exhausted",
        )

    assert sleeps == [3, 3]
    assert [attempt.attempt_no for attempt in ledger.attempts] == [1, 2, 3]
    assert all(attempt.outcome is ObservationOutcome.HTTP_ERROR for attempt in ledger.attempts)
    assert ledger.runs["connector-run-exhausted"]["state"] is RunState.FAILED


def test_invalid_success_response_is_not_retried_or_written(tmp_path: Path) -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"response":{"header":{"resultCode":"30"}}}',
            headers={"Content-Type": "application/json"},
            request=request,
        )

    engine, ledger, client = build_engine(tmp_path, handler, sleeps=sleeps)
    with client, pytest.raises(FetchRunError) as captured:
        engine.run(
            connector(),
            mode=RunMode.BACKFILL,
            run_id="run-invalid",
            connector_run_id="connector-run-invalid",
        )

    assert captured.value.error_code == "RESPONSE_INVALID"
    assert sleeps == []
    assert len(ledger.attempts) == 1
    assert ledger.attempts[0].outcome is ObservationOutcome.RESPONSE_INVALID
    assert ledger.snapshots == {}
    assert not (tmp_path / "raw").exists()


def test_backfill_page_cap_fetches_only_the_requested_number_of_pages(tmp_path: Path) -> None:
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["pageNo"])
        requested_pages.append(page)
        return httpx.Response(
            200,
            content=response_body(total=250, page=page, size=100),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    engine, ledger, client = build_engine(tmp_path, handler)
    with client:
        summary = engine.run(
            connector(),
            mode=RunMode.BACKFILL,
            run_id="run-capped",
            connector_run_id="connector-run-capped",
            max_pages=2,
        )

    assert requested_pages == [1, 2]
    assert summary.planned_request_count == 2
    assert summary.successful_request_count == 2
    assert [request["page_number"] for request in ledger.requests] == [1, 2]


def test_scheduled_full_rejects_page_cap_before_run_or_network_activity(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=response_body(), request=request)

    engine, ledger, client = build_engine(tmp_path, handler)
    with client, pytest.raises(ValueError, match="SCHEDULED_FULL runs cannot cap pagination"):
        engine.run(
            connector(),
            mode=RunMode.SCHEDULED_FULL,
            run_id="run-full",
            connector_run_id="connector-run-full",
            max_pages=1,
        )

    assert calls == 0
    assert ledger.runs == {}
    assert ledger.requests == []
    assert ledger.attempts == []
    assert not (tmp_path / "raw").exists()


def test_declared_zero_is_confirmed_by_a_second_complete_request(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=response_body(total=0),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    engine, ledger, client = build_engine(tmp_path, handler)
    with client:
        summary = engine.run(
            connector(),
            mode=RunMode.BACKFILL,
            run_id="run-zero",
            connector_run_id="connector-run-zero",
        )

    assert calls == 2
    assert summary.planned_request_count == 2
    assert summary.successful_request_count == 2
    assert [attempt.response_ordinal for attempt in ledger.attempts] == [0, 1]


def test_single_file_preserves_query_parameters_embedded_in_url(tmp_path: Path) -> None:
    observed_query = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_query
        observed_query = request.url.query.decode()
        return httpx.Response(
            200,
            content=b"source,row\nNCS,1\n",
            headers={"Content-Type": "application/octet-stream"},
            request=request,
        )

    file_connector = SingleFileConnector(
        source_id="fixture",
        display_name="File fixture",
        endpoint="https://fixture.example/download?fileId=123&revision=4",
        allowed_hosts=frozenset({"fixture.example"}),
    )
    engine, _, client = build_engine(tmp_path, handler)
    with client:
        engine.run(file_connector, mode=RunMode.BACKFILL)

    assert observed_query == "fileId=123&revision=4"


def test_oversized_response_is_rejected_before_raw_publish(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=response_body(),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    engine, ledger, client = build_engine(tmp_path, handler, max_response_bytes=32)
    with client, pytest.raises(FetchRunError) as captured:
        engine.run(connector(), mode=RunMode.BACKFILL)

    assert captured.value.error_code == "RESPONSE_TOO_LARGE"
    assert ledger.attempts[0].outcome is ObservationOutcome.RESPONSE_INVALID
    assert ledger.attempts[0].error_code == "RESPONSE_TOO_LARGE"
    assert ledger.snapshots == {}
    assert not (tmp_path / "raw").exists()
