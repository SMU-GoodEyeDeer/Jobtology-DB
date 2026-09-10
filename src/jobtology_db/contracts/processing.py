from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

PROCESSOR_VERSION = "normalize-v1"
TEXT_VERSION = "nfc-lf-v1"
PROCESSABLE_SOURCES = (
    "ncs_career_path",
    "ncs_competency",
    "ncs_qualification",
    "qnet_schedule",
    "alio_organization",
    "job_alio",
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CareerPath(Contract):
    kind: Literal["CareerPath"] = "CareerPath"
    occupation_code: str
    occupation_name: str
    competency_code: str
    competency_name: str
    competency_level: int = Field(ge=1, le=8)
    rank_level: int = Field(ge=1, le=8)
    rank_name: str


class Competency(Contract):
    kind: Literal["Competency"] = "Competency"
    code: str
    name: str
    definition: str | None
    level: int | None = Field(ge=1, le=8)
    occupation_code: str
    occupation_name: str
    classification_names: list[str]


class QualificationMapping(Contract):
    kind: Literal["QualificationMapping"] = "QualificationMapping"
    competency_code: str
    qualification_code: str
    qualification_name: str
    standard_version: str
    unit_type: str
    minimum_training_hours: int | None = Field(ge=0)
    total_training_hours: int | None = Field(ge=0)
    examining_organization: str | None


class ExamSession(Contract):
    kind: Literal["ExamSession"] = "ExamSession"
    qualification_code: str
    year: int = Field(ge=1900, le=2200)
    round: int = Field(ge=1)
    category_code: str
    name: str
    dates: dict[str, date | None]


class Organization(Contract):
    kind: Literal["Organization"] = "Organization"
    code: str
    name: str
    government_code: str | None
    organization_type: str | None
    supervising_organization_code: str | None
    website: str | None
    address: str | None
    established_date: date | None


class JobPosting(Contract):
    kind: Literal["JobPosting"] = "JobPosting"
    posting_id: str
    representation: Literal["list", "detail"]
    title: str
    organization_code: str
    organization_name: str
    date_posted: date
    closing_date: date
    # Dates have DAY precision. Do not manufacture a 23:59 application deadline.
    ongoing: bool | None
    source_url: str | None
    recruitment_type: str | None
    education: str | None
    employment_type: str | None
    regions: str | None
    ncs_category_codes: str | None
    ncs_category_names: str | None
    headcount: int | None = Field(ge=0)
    eligibility_text: str | None
    disqualification_text: str | None
    preference_text: str | None
    selection_text: str | None


Normalized = Annotated[
    CareerPath | Competency | QualificationMapping | ExamSession | Organization | JobPosting,
    Field(discriminator="kind"),
]
NORMALIZED_ADAPTER: TypeAdapter[Normalized] = TypeAdapter(Normalized)


class TextArtifact(Contract):
    text: str
    sha256: str
    normalization_version: str = TEXT_VERSION


class Record(Contract):
    source_record_id: str
    source_payload: dict[str, JsonValue]
    normalized: Normalized
    # Relative JSON pointers into source_payload; request:partition denotes request context.
    field_lineage: dict[str, list[str]]
    texts: dict[str, TextArtifact]
    quality_flags: list[str] = Field(default_factory=list)


class RejectedRow(Contract):
    locator: str
    source_payload: JsonValue
    error_code: str


class LocatedRecord(Contract):
    locator: str
    record: Record


class ParsedDocument(Contract):
    records: list[LocatedRecord]
    rejected: list[RejectedRow]
    total: int | None
    page: int | None
    page_size: int | None
    row_count: int
    encoding: str


class ProcessingSummary(Contract):
    processing_run_id: str
    connector_run_id: str
    source_id: str
    processor_version: str = PROCESSOR_VERSION
    state: Literal["READY", "REVIEW_REQUIRED"]
    documents: int
    reused_documents: int
    records: int
    rejected: int
    new_revisions: int
    content_set_hash: str
    normalized_set_hash: str
