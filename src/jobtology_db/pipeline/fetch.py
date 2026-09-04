from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from pydantic import BaseModel, ConfigDict

from jobtology_db.connectors.base import Connector, ResponseContractError
from jobtology_db.contracts.fetch import (
    FetchAttempt,
    ObservationOutcome,
    PageMetadata,
    RequestSpec,
    RunMode,
    SourceSnapshot,
)
from jobtology_db.pipeline.request_security import (
    redacted_url,
    request_fingerprint,
    safe_response_headers,
    validate_endpoint,
)
from jobtology_db.storage.ledger import FetchLedger
from jobtology_db.storage.raw_files import (
    RawFileStore,
    RawObjectIntegrityError,
    RawStorageCapacityError,
)

RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ResponseTooLargeError(ValueError):
    pass


class FetchRunError(RuntimeError):
    """A deliberately redacted fetch error safe to print in the CLI."""

    def __init__(self, source_id: str, error_code: str, request_url: str | None = None) -> None:
        location = f" at {request_url}" if request_url else ""
        super().__init__(f"{source_id} fetch failed ({error_code}){location}")
        self.error_code = error_code


class FetchRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    connector_run_id: str
    source_id: str
    mode: RunMode
    stage: str = "FETCHED"
    planned_request_count: int
    successful_request_count: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    max_retry_after_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.max_retry_after_seconds < 0:
            raise ValueError("max_retry_after_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class _SuccessfulRequest:
    metadata: PageMetadata
    attempt_ids: tuple[str, ...]
    selected_observation_id: str


class FetchEngine:
    """Fetch and durably record source bytes without interpreting ontology entities."""

    def __init__(
        self,
        *,
        client: httpx.Client,
        raw_store: RawFileStore,
        ledger: FetchLedger,
        retry_policy: RetryPolicy | None = None,
        user_agent: str = "Jobtology/0.1",
        max_response_bytes: int = 64 * 1024 * 1024,
        raw_min_free_bytes: int = 1024 * 1024 * 1024,
        raw_max_used_fraction: float = 0.85,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self.raw_store = raw_store
        self.ledger = ledger
        self.retry_policy = retry_policy or RetryPolicy()
        self.user_agent = user_agent
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.max_response_bytes = max_response_bytes
        if raw_min_free_bytes < 0:
            raise ValueError("raw_min_free_bytes cannot be negative")
        if not 0 < raw_max_used_fraction < 1:
            raise ValueError("raw_max_used_fraction must be between zero and one")
        self.raw_min_free_bytes = raw_min_free_bytes
        self.raw_max_used_fraction = raw_max_used_fraction
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        connector: Connector,
        *,
        mode: RunMode,
        run_id: str | None = None,
        connector_run_id: str | None = None,
        max_pages: int | None = None,
    ) -> FetchRunSummary:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if mode is RunMode.SCHEDULED_FULL and max_pages is not None:
            raise ValueError("SCHEDULED_FULL runs cannot cap pagination")

        resolved_run_id = run_id or str(uuid.uuid4())
        resolved_connector_run_id = connector_run_id or str(uuid.uuid4())
        initial_requests = tuple(connector.initial_requests())
        if not initial_requests:
            raise ValueError(f"{connector.source_id} produced no initial requests")

        queue: deque[RequestSpec] = deque()
        known_fingerprints: set[str] = set()
        request_by_fingerprint: dict[str, RequestSpec] = {}

        def enqueue(request: RequestSpec) -> None:
            if request.source_id != connector.source_id:
                raise ValueError("Connector produced a request for a different source")
            validate_endpoint(request.url, connector.allowed_hosts)
            fingerprint = request_fingerprint(request)
            if fingerprint in known_fingerprints:
                return
            known_fingerprints.add(fingerprint)
            request_by_fingerprint[fingerprint] = request
            queue.append(request)

        for request in initial_requests:
            enqueue(request)

        started = False
        attempt_ids: list[str] = []
        selected_observation_ids: list[str] = []
        try:
            self.ledger.start_run(
                resolved_connector_run_id,
                resolved_run_id,
                connector.source_id,
                mode,
            )
            started = True

            while queue:
                request = queue.popleft()
                fingerprint = request_fingerprint(request)
                self.ledger.plan_request(
                    resolved_connector_run_id,
                    fingerprint,
                    request.partition_id,
                    request.page_number,
                    redacted_url(request),
                )
                fetched = self._fetch_request(
                    connector,
                    request,
                    fingerprint,
                    resolved_connector_run_id,
                )
                attempt_ids.extend(fetched.attempt_ids)
                selected_observation_ids.append(fetched.selected_observation_id)

                for discovered in connector.remaining_requests(
                    request, fetched.metadata, max_pages
                ):
                    enqueue(discovered)

            self.ledger.mark_fetch_complete(
                resolved_connector_run_id,
                planned_request_count=len(request_by_fingerprint),
                successful_request_count=len(selected_observation_ids),
                attempt_ids=attempt_ids,
                selected_observation_ids=selected_observation_ids,
            )
        except Exception as error:
            if started:
                try:
                    code = (
                        error.error_code
                        if isinstance(error, FetchRunError)
                        else type(error).__name__
                    )
                    self.ledger.fail_run(resolved_connector_run_id, code)
                except Exception:
                    pass
            if isinstance(error, (FetchRunError, ValueError)):
                raise
            raise FetchRunError(connector.source_id, type(error).__name__) from error

        return FetchRunSummary(
            run_id=resolved_run_id,
            connector_run_id=resolved_connector_run_id,
            source_id=connector.source_id,
            mode=mode,
            planned_request_count=len(request_by_fingerprint),
            successful_request_count=len(selected_observation_ids),
            attempt_count=len(attempt_ids),
        )

    def _fetch_request(
        self,
        connector: Connector,
        request: RequestSpec,
        fingerprint: str,
        connector_run_id: str,
    ) -> _SuccessfulRequest:
        request_url = redacted_url(request)
        attempt_ids: list[str] = []

        for attempt_no in range(1, self.retry_policy.max_attempts + 1):
            try:
                self.raw_store.ensure_capacity(
                    incoming_limit_bytes=self.max_response_bytes,
                    min_free_bytes=self.raw_min_free_bytes,
                    max_used_fraction=self.raw_max_used_fraction,
                )
            except RawStorageCapacityError as error:
                raise FetchRunError(connector.source_id, "RAW_CAPACITY", request_url) from error

            observation_id = str(uuid.uuid4())
            attempt_ids.append(observation_id)
            requested_at = self.clock()
            status: int | None = None
            headers: dict[str, str] = {}
            try:
                with self.client.stream(
                    request.method,
                    request.url,
                    # Passing an empty mapping makes HTTPX erase a query already present in
                    # the configured URL (used by official file-download links).
                    params=request.params or None,
                    headers={
                        "Accept": "application/json, application/xml;q=0.9, */*;q=0.8",
                        "Accept-Encoding": "identity",
                        "User-Agent": self.user_agent,
                    },
                ) as response:
                    status = response.status_code
                    headers = safe_response_headers(response.headers)
                    content_type = response.headers.get("content-type", "application/octet-stream")
                    content = (
                        self._read_limited(response) if 200 <= response.status_code < 300 else b""
                    )
            except ResponseTooLargeError as error:
                retrieved_at = self.clock()
                self._record_failure(
                    observation_id=observation_id,
                    connector_run_id=connector_run_id,
                    request=request,
                    fingerprint=fingerprint,
                    attempt_no=attempt_no,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                    status=status,
                    headers=headers,
                    outcome=ObservationOutcome.RESPONSE_INVALID,
                    error_code="RESPONSE_TOO_LARGE",
                )
                raise FetchRunError(
                    connector.source_id, "RESPONSE_TOO_LARGE", request_url
                ) from error
            except httpx.RequestError as error:
                retrieved_at = self.clock()
                self._record_failure(
                    observation_id=observation_id,
                    connector_run_id=connector_run_id,
                    request=request,
                    fingerprint=fingerprint,
                    attempt_no=attempt_no,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                    status=None,
                    headers={},
                    outcome=ObservationOutcome.TRANSPORT_ERROR,
                    error_code=type(error).__name__,
                )
                if attempt_no == self.retry_policy.max_attempts:
                    raise FetchRunError(
                        connector.source_id, type(error).__name__, request_url
                    ) from error
                self.sleeper(self._retry_delay(attempt_no, None, retrieved_at))
                continue

            retrieved_at = self.clock()
            if not 200 <= status < 300:
                error_code = f"HTTP_{status}"
                self._record_failure(
                    observation_id=observation_id,
                    connector_run_id=connector_run_id,
                    request=request,
                    fingerprint=fingerprint,
                    attempt_no=attempt_no,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                    status=status,
                    headers=headers,
                    outcome=ObservationOutcome.HTTP_ERROR,
                    error_code=error_code,
                )
                retryable = status in RETRYABLE_HTTP_STATUSES
                if not retryable or attempt_no == self.retry_policy.max_attempts:
                    raise FetchRunError(connector.source_id, error_code, request_url)
                self.sleeper(
                    self._retry_delay(attempt_no, headers.get("retry-after"), retrieved_at)
                )
                continue

            try:
                metadata = connector.validate_response(request, content, content_type)
            except (ResponseContractError, ValueError) as error:
                self._record_failure(
                    observation_id=observation_id,
                    connector_run_id=connector_run_id,
                    request=request,
                    fingerprint=fingerprint,
                    attempt_no=attempt_no,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                    status=status,
                    headers=headers,
                    outcome=ObservationOutcome.RESPONSE_INVALID,
                    error_code=type(error).__name__,
                )
                raise FetchRunError(connector.source_id, "RESPONSE_INVALID", request_url) from error

            try:
                stored = self.raw_store.put(content)
            except (OSError, RawObjectIntegrityError) as error:
                self._record_failure(
                    observation_id=observation_id,
                    connector_run_id=connector_run_id,
                    request=request,
                    fingerprint=fingerprint,
                    attempt_no=attempt_no,
                    requested_at=requested_at,
                    retrieved_at=retrieved_at,
                    status=status,
                    headers=headers,
                    outcome=ObservationOutcome.STORAGE_ERROR,
                    error_code=type(error).__name__,
                )
                raise FetchRunError(connector.source_id, "STORAGE_ERROR", request_url) from error

            snapshot_id = _snapshot_id(connector.source_id, stored.content_sha256)
            snapshot = SourceSnapshot(
                snapshot_id=snapshot_id,
                source_id=connector.source_id,
                content_sha256=stored.content_sha256,
                byte_length=stored.byte_length,
                mime_type=content_type.split(";", 1)[0].strip().casefold(),
                raw_object_path=stored.relative_path.as_posix(),
                first_observed_at=retrieved_at,
            )
            successful_attempt = FetchAttempt(
                observation_id=observation_id,
                connector_run_id=connector_run_id,
                source_id=connector.source_id,
                request_fingerprint=fingerprint,
                partition_id=request.partition_id,
                page_number=request.page_number,
                response_ordinal=request.response_ordinal,
                attempt_no=attempt_no,
                requested_at=requested_at,
                retrieved_at=retrieved_at,
                http_status=status,
                request_url_redacted=request_url,
                response_headers=headers,
                outcome=ObservationOutcome.SELECTED_SUCCESS,
                snapshot_id=snapshot_id,
                selected=True,
            )
            self.ledger.record_attempt(successful_attempt, snapshot)
            return _SuccessfulRequest(
                metadata=metadata,
                attempt_ids=tuple(attempt_ids),
                selected_observation_id=observation_id,
            )

        raise AssertionError("retry loop exhausted without returning or raising")

    def _read_limited(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared:
            try:
                declared_length = int(declared)
            except ValueError:
                declared_length = 0
            if declared_length > self.max_response_bytes:
                raise ResponseTooLargeError("Declared response length exceeds configured limit")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ResponseTooLargeError("Response body exceeds configured limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def _record_failure(
        self,
        *,
        observation_id: str,
        connector_run_id: str,
        request: RequestSpec,
        fingerprint: str,
        attempt_no: int,
        requested_at: datetime,
        retrieved_at: datetime,
        status: int | None,
        headers: dict[str, str],
        outcome: ObservationOutcome,
        error_code: str,
    ) -> None:
        self.ledger.record_attempt(
            FetchAttempt(
                observation_id=observation_id,
                connector_run_id=connector_run_id,
                source_id=request.source_id,
                request_fingerprint=fingerprint,
                partition_id=request.partition_id,
                page_number=request.page_number,
                response_ordinal=request.response_ordinal,
                attempt_no=attempt_no,
                requested_at=requested_at,
                retrieved_at=retrieved_at,
                http_status=status,
                request_url_redacted=redacted_url(request),
                response_headers=headers,
                outcome=outcome,
                error_code=error_code[:100],
                selected=False,
            ),
            None,
        )

    def _retry_delay(
        self, attempt_no: int, retry_after: str | None, observed_at: datetime
    ) -> float:
        cap = self.retry_policy.max_retry_after_seconds
        if retry_after:
            try:
                return min(cap, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    return min(cap, max(0.0, (retry_at - observed_at).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(cap, float(2 ** (attempt_no - 1)))


def _snapshot_id(source_id: str, content_sha256: str) -> str:
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "https://jobtology.dev/source-snapshot")
    return str(uuid.uuid5(namespace, f"{source_id}:{content_sha256}"))


def planned_requests(connector: Connector) -> Sequence[RequestSpec]:
    """Return only the first requests; later pages depend on provider-declared totals."""

    requests = tuple(connector.initial_requests())
    for request in requests:
        validate_endpoint(request.url, connector.allowed_hosts)
    return requests
