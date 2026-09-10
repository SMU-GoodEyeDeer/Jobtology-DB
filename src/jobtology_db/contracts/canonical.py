"""Fixed, provider-independent canonical identity and revision contracts.

These are storage contracts, not an automatic publication/acceptance decision.
Source adapters continue to validate their stricter provider staging records.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from jobtology_db.contracts.documents import Identifier, NonEmpty, Sha256
from jobtology_db.contracts.processing import Contract, digest

EntityKind = Literal[
    "ConceptScheme",
    "Occupation",
    "NCSClass",
    "NCSCompetencyUnit",
    "Skill",
    "Credential",
    "Organization",
    "JobPosting",
    "ExamSession",
]


class EntityReference(Contract):
    kind: EntityKind
    entity_id: Identifier


class ExternalIdentifier(Contract):
    scheme: Identifier
    value: NonEmpty
    # An identifier claim does not itself authorize a cross-source merge.


class EntityIdentity(Contract):
    entity_id: Identifier
    kind: EntityKind
    # Source-scoped identities are retained, including potentially duplicate postings.
    namespace: Identifier
    source_key: Identifier


class ConceptScheme(Contract):
    kind: Literal["ConceptScheme"] = "ConceptScheme"
    name_ko: NonEmpty
    publisher: NonEmpty
    version: NonEmpty


class Occupation(Contract):
    kind: Literal["Occupation"] = "Occupation"
    name_ko: NonEmpty
    code: Identifier
    scheme_id: Identifier
    definition: str | None = None
    aliases: list[NonEmpty] = Field(default_factory=list)
    ncs_class_ids: list[Identifier] = Field(default_factory=list)


class NCSClass(Contract):
    kind: Literal["NCSClass"] = "NCSClass"
    name_ko: NonEmpty
    code: Annotated[str, Field(pattern=r"^(?:\d{2}){1,4}$")]
    taxonomy_version: NonEmpty
    depth: int = Field(ge=1, le=4)
    parent_id: Identifier | None = None

    @model_validator(mode="after")
    def hierarchy(self) -> Self:
        if len(self.code) != self.depth * 2 or (self.depth == 1) != (self.parent_id is None):
            raise ValueError("INVALID_NCS_CLASS_HIERARCHY")
        return self


class NCSCompetencyUnit(Contract):
    kind: Literal["NCSCompetencyUnit"] = "NCSCompetencyUnit"
    name_ko: NonEmpty
    full_code: Annotated[str, Field(pattern=r"^\d{10}_\d{2}v\d+$")]
    base_code: Annotated[str, Field(pattern=r"^\d{10}$")]
    version: Annotated[str, Field(pattern=r"^\d{2}v\d+$")]
    level: int | None = Field(default=None, ge=1, le=8)
    definition: str | None = None
    occupation_id: Identifier

    @model_validator(mode="after")
    def versioned_code(self) -> Self:
        if self.full_code != f"{self.base_code}_{self.version}":
            raise ValueError("NCS_VERSION_MISMATCH")
        return self


class Skill(Contract):
    kind: Literal["Skill"] = "Skill"
    name_ko: NonEmpty
    code: Identifier
    scheme_id: Identifier
    skill_kind: Literal["SKILL", "TOOL", "LANGUAGE"]
    aliases: list[NonEmpty] = Field(default_factory=list)
    definition: str | None = None


class Credential(Contract):
    kind: Literal["Credential"] = "Credential"
    name_ko: NonEmpty
    identifiers: Annotated[list[ExternalIdentifier], Field(min_length=1)]
    issuing_organization_id: Identifier | None = None
    credential_type: str | None = None


class ExamDates(Contract):
    docRegStartDt: date | None = None
    docRegEndDt: date | None = None
    docExamStartDt: date | None = None
    docExamEndDt: date | None = None
    docPassDt: date | None = None
    pracRegStartDt: date | None = None
    pracRegEndDt: date | None = None
    pracExamStartDt: date | None = None
    pracExamEndDt: date | None = None
    pracPassDt: date | None = None

    @model_validator(mode="after")
    def date_ranges(self) -> Self:
        for start, end in (
            (self.docRegStartDt, self.docRegEndDt),
            (self.docExamStartDt, self.docExamEndDt),
            (self.pracRegStartDt, self.pracRegEndDt),
            (self.pracExamStartDt, self.pracExamEndDt),
        ):
            if start is not None and end is not None and end < start:
                raise ValueError("EXAM_DATE_ORDER")
        return self


class ExamSession(Contract):
    kind: Literal["ExamSession"] = "ExamSession"
    name_ko: NonEmpty
    credential_id: Identifier
    year: int = Field(ge=1900, le=2200)
    round: int = Field(ge=1)
    category_code: Identifier
    # The source's written/practical date labels retain DAY precision.
    dates: ExamDates


class Organization(Contract):
    kind: Literal["Organization"] = "Organization"
    name_ko: NonEmpty
    identifiers: list[ExternalIdentifier] = Field(default_factory=list[ExternalIdentifier])
    name_en: str | None = None
    employer_type: Literal["LARGE_ENTERPRISE", "STARTUP", "OTHER", "UNKNOWN"] = "UNKNOWN"
    organization_type_text: str | None = None
    supervising_organization_id: Identifier | None = None
    website: str | None = None
    address_text: str | None = None
    established_date: date | None = None
    active: bool | None = None


class DayValue(Contract):
    precision: Literal["DAY"] = "DAY"
    value: date


class InstantValue(Contract):
    precision: Literal["INSTANT"] = "INSTANT"
    value: AwareDatetime


TemporalValue = Annotated[DayValue | InstantValue, Field(discriminator="precision")]


class JobPosting(Contract):
    kind: Literal["JobPosting"] = "JobPosting"
    # A text-only JD is valid input; missing facts remain explicit nulls.
    title: NonEmpty | None = None
    canonical_url: str | None = None
    description_document_id: Sha256 | None = None
    organization_id: Identifier | None = None
    organization_name_text: str | None = None
    primary_occupation_id: Identifier | None = None
    date_posted: TemporalValue | None = None
    valid_through: TemporalValue | None = None
    source_status: Literal["OPEN", "CLOSED", "UNKNOWN"] = "UNKNOWN"
    employment_type_text: str | None = None
    recruitment_type_text: str | None = None
    education_text: str | None = None
    region_text: str | None = None
    ncs_categories_text: str | None = None
    headcount: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def date_order(self) -> Self:
        if (
            isinstance(self.date_posted, DayValue)
            and isinstance(self.valid_through, DayValue)
            and self.valid_through.value < self.date_posted.value
        ):
            raise ValueError("POSTING_DATE_ORDER")
        if (
            isinstance(self.date_posted, InstantValue)
            and isinstance(self.valid_through, InstantValue)
            and self.valid_through.value < self.date_posted.value
        ):
            raise ValueError("POSTING_DATE_ORDER")
        return self

    def missing_publication_fields(self) -> list[str]:
        return [
            name
            for name in (
                "title",
                "canonical_url",
                "description_document_id",
                "organization_id",
                "primary_occupation_id",
                "date_posted",
                "valid_through",
            )
            if getattr(self, name) is None
        ]


EntityPayload = Annotated[
    ConceptScheme
    | Occupation
    | NCSClass
    | NCSCompetencyUnit
    | Skill
    | Credential
    | Organization
    | JobPosting
    | ExamSession,
    Field(discriminator="kind"),
]
ENTITY_ADAPTER: TypeAdapter[EntityPayload] = TypeAdapter(EntityPayload)


class FieldSupport(Contract):
    field: NonEmpty
    evidence_ids: Annotated[list[Sha256], Field(min_length=1)]
    method: Literal["DIRECT", "NORMALIZED", "REVIEWED_MAPPING"]


class EntityRevision(Contract):
    schema_version: Literal["canonical-v1"] = "canonical-v1"
    revision_id: Sha256
    entity_id: Identifier
    document_ids: Annotated[list[Sha256], Field(min_length=1)]
    payload: EntityPayload
    # No inference is accepted simply because it fits this schema.
    field_support: list[FieldSupport] = Field(default_factory=list[FieldSupport])

    @model_validator(mode="after")
    def content_identity(self) -> Self:
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("DUPLICATE_DOCUMENT_REFERENCE")
        fields = {s.field for s in self.field_support}
        if len(fields) != len(self.field_support) or not fields <= set(
            type(self.payload).model_fields
        ):
            raise ValueError("INVALID_FIELD_SUPPORT")
        if isinstance(self.payload, JobPosting):
            document_id = self.payload.description_document_id
            if document_id is not None and document_id not in self.document_ids:
                raise ValueError("UNBOUND_DESCRIPTION_DOCUMENT")
        if self.revision_id != digest(self.model_dump(mode="json", exclude={"revision_id"})):
            raise ValueError("REVISION_ID_MISMATCH")
        return self
