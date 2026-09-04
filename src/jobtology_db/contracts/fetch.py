from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class RunMode(StrEnum):
    SCHEDULED_FULL = "SCHEDULED_FULL"
    BACKFILL = "BACKFILL"


class RunState(StrEnum):
    RUNNING = "RUNNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ObservationOutcome(StrEnum):
    SELECTED_SUCCESS = "SELECTED_SUCCESS"
    HTTP_ERROR = "HTTP_ERROR"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    RESPONSE_INVALID = "RESPONSE_INVALID"
    STORAGE_ERROR = "STORAGE_ERROR"


class CompletenessMode(StrEnum):
    DECLARED_TOTAL = "DECLARED_TOTAL"
    SINGLE_FILE = "SINGLE_FILE"
    INDEX_TERMINAL = "INDEX_TERMINAL"


class SourceReadiness(StrEnum):
    READY = "READY"
    NEEDS_CREDENTIAL = "NEEDS_CREDENTIAL"
    NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
    SPEC_PENDING = "SPEC_PENDING"


class StoredRawObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_sha256: str
    byte_length: int
    relative_path: Path


class FetchAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    connector_run_id: str
    source_id: str
    request_fingerprint: str
    partition_id: str
    page_number: int | None
    response_ordinal: int = 0
    attempt_no: int
    requested_at: datetime
    retrieved_at: datetime
    http_status: int | None
    request_url_redacted: str
    response_headers: dict[str, str]
    outcome: ObservationOutcome
    error_code: str | None = None
    snapshot_id: str | None = None
    selected: bool = False


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    source_id: str
    content_sha256: str
    byte_length: int
    mime_type: str
    raw_object_path: str
    first_observed_at: datetime


@dataclass(frozen=True, slots=True)
class RequestSpec:
    source_id: str
    partition_id: str
    method: str
    url: str
    params: Mapping[str, str] = field(repr=False)
    secret_param_names: frozenset[str] = field(default_factory=frozenset[str])
    page_number: int | None = None
    response_ordinal: int = 0


@dataclass(frozen=True, slots=True)
class PageMetadata:
    total_count: int | None
    page_number: int | None
    page_size: int | None
    discovered_record_ids: tuple[str, ...] = ()
