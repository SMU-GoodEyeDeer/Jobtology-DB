"""Untrusted extractor output and separately resolved/reviewed requirement claims."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from jobtology_db.contracts.documents import Identifier, NonEmpty, Sha256, SourceDocument
from jobtology_db.contracts.processing import Contract, digest

RequirementKind = Literal[
    "SKILL",
    "CREDENTIAL",
    "EDUCATION",
    "EXPERIENCE",
    "LANGUAGE",
    "PROJECT",
    "LOCATION",
    "ELIGIBILITY",
    "AVAILABILITY",
]
Necessity = Literal["REQUIRED", "PREFERRED", "OPTIONAL", "UNSPECIFIED"]
Polarity = Literal["POSITIVE", "NEGATED", "NO_CONSTRAINT"]


class SpanSelector(Contract):
    block_id: Identifier
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    excerpt: NonEmpty

    @model_validator(mode="after")
    def length_matches(self) -> Self:
        if self.end - self.start != len(self.excerpt):
            raise ValueError("INVALID_SPAN_LENGTH")
        return self

    def verify_document(self, document: SourceDocument) -> None:
        block = next((b for b in document.blocks if b.block_id == self.block_id), None)
        if (
            block is None
            or self.end > len(block.text)
            or block.text[self.start : self.end] != self.excerpt
        ):
            raise ValueError("EXTRACTED_SPAN_NOT_IN_DOCUMENT")


class RequirementCandidate(Contract):
    local_id: Identifier
    kind: RequirementKind
    mention: NonEmpty
    necessity: Necessity
    polarity: Polarity
    applicability_text: NonEmpty | None
    # No canonical IDs, confidence, or acceptance fields are entrusted to an extractor.
    evidence: Annotated[list[SpanSelector], Field(min_length=1)]


class RequirementGroup(Contract):
    local_id: Identifier
    operator: Literal["ALL_OF", "ANY_OF"]
    member_ids: Annotated[list[Identifier], Field(min_length=2)]
    evidence: Annotated[list[SpanSelector], Field(min_length=1)]


class ExtractionOutput(Contract):
    schema_version: Literal["requirement-extraction-v1"] = "requirement-extraction-v1"
    candidates: list[RequirementCandidate]
    groups: list[RequirementGroup]

    @model_validator(mode="after")
    def group_membership(self) -> Self:
        candidate_ids = {c.local_id for c in self.candidates}
        group_ids = {g.local_id for g in self.groups}
        if (
            len(candidate_ids) != len(self.candidates)
            or len(group_ids) != len(self.groups)
            or candidate_ids & group_ids
        ):
            raise ValueError("DUPLICATE_EXTRACTION_ID")
        # Forest of groups supports nested AND/OR without flattening alternatives.
        nodes = {g.local_id: g.member_ids for g in self.groups}
        members = [member for g in self.groups for member in g.member_ids]
        if len(set(members)) != len(members) or not set(members) <= candidate_ids | group_ids:
            raise ValueError("INVALID_REQUIREMENT_GROUP_MEMBERS")

        def visit(node: str, ancestors: set[str]) -> None:
            if node in ancestors:
                raise ValueError("CYCLIC_REQUIREMENT_GROUP")
            for child in nodes.get(node, []):
                visit(child, ancestors | {node})

        for node in nodes:
            visit(node, set())
        return self

    def verify_document(self, document: SourceDocument) -> None:
        for item in [*self.candidates, *self.groups]:
            for evidence in item.evidence:
                evidence.verify_document(document)


class ExtractorMetadata(Contract):
    method: Literal["STRUCTURED", "RULE", "LLM"]
    extractor_version: Identifier
    model_requested: str | None = None
    model_returned: str | None = None
    prompt_sha256: Sha256 | None = None
    response_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def model_metadata(self) -> Self:
        fields = (
            self.model_requested,
            self.model_returned,
            self.prompt_sha256,
            self.response_id,
            self.input_tokens,
            self.output_tokens,
        )
        if self.method == "LLM" and any(value is None for value in fields):
            raise ValueError("MISSING_MODEL_PROVENANCE")
        if self.method != "LLM" and any(value is not None for value in fields):
            raise ValueError("UNEXPECTED_MODEL_PROVENANCE")
        return self


class ExtractionRecord(Contract):
    extraction_id: Sha256
    document_id: Sha256
    metadata: ExtractorMetadata
    output: ExtractionOutput

    @model_validator(mode="after")
    def content_identity(self) -> Self:
        if self.extraction_id != digest(self.model_dump(mode="json", exclude={"extraction_id"})):
            raise ValueError("EXTRACTION_ID_MISMATCH")
        return self


class CapabilityCondition(Contract):
    kind: Literal["SKILL", "LANGUAGE"]
    target_id: Identifier
    target_kind: Literal["Skill", "NCSCompetencyUnit"]
    proficiency_scheme_id: Identifier | None = None
    minimum_proficiency: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def proficiency_pair(self) -> Self:
        if (self.proficiency_scheme_id is None) != (self.minimum_proficiency is None):
            raise ValueError("INCOMPLETE_PROFICIENCY")
        if self.kind == "LANGUAGE" and self.target_kind != "Skill":
            raise ValueError("LANGUAGE_TARGET_MUST_BE_SKILL")
        return self


class CredentialCondition(Contract):
    kind: Literal["CREDENTIAL"] = "CREDENTIAL"
    target_id: Identifier


class EducationCondition(Contract):
    kind: Literal["EDUCATION"] = "EDUCATION"
    minimum_degree: (
        Literal["NONE", "HIGH_SCHOOL", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE"] | None
    )
    accepted_major_groups: list[
        Literal[
            "COMPUTING",
            "ENGINEERING",
            "NATURAL_SCIENCE",
            "BUSINESS",
            "HUMANITIES_SOCIAL",
            "ARTS",
            "OTHER",
        ]
    ]
    accepts_expected_graduate: bool | None


class ExperienceCondition(Contract):
    kind: Literal["EXPERIENCE"] = "EXPERIENCE"
    context_id: Identifier | None
    minimum_months: int | None = Field(ge=0)
    maximum_months: int | None = Field(ge=0)

    @model_validator(mode="after")
    def range_order(self) -> Self:
        if (
            self.minimum_months is not None
            and self.maximum_months is not None
            and self.maximum_months < self.minimum_months
        ):
            raise ValueError("EXPERIENCE_RANGE_ORDER")
        return self


class ProjectCondition(Contract):
    kind: Literal["PROJECT"] = "PROJECT"
    minimum_count: int | None = Field(ge=0)
    portfolio_required: bool | None
    capability_ids: list[Identifier]


class LocationCondition(Contract):
    kind: Literal["LOCATION"] = "LOCATION"
    administrative_codes: list[Identifier]
    work_mode: Literal["ONSITE", "REMOTE", "HYBRID", "UNKNOWN"]


class EligibilityCondition(Contract):
    kind: Literal["ELIGIBILITY"] = "ELIGIBILITY"
    # Approved vocabulary code; unknown conditions stay unresolved, not invented codes.
    code: Identifier
    source_text: NonEmpty


class AvailabilityCondition(Contract):
    kind: Literal["AVAILABILITY"] = "AVAILABILITY"
    schedule_text: NonEmpty


class UnresolvedCondition(Contract):
    kind: Literal["UNRESOLVED"] = "UNRESOLVED"
    mention: NonEmpty
    reason: Literal["NO_MATCH", "AMBIGUOUS", "UNSUPPORTED_CONDITION"]


RequirementCondition = Annotated[
    CapabilityCondition
    | CredentialCondition
    | EducationCondition
    | ExperienceCondition
    | ProjectCondition
    | LocationCondition
    | EligibilityCondition
    | AvailabilityCondition
    | UnresolvedCondition,
    Field(discriminator="kind"),
]


class ReviewDecision(Contract):
    status: Literal["PENDING", "AUTO_ACCEPTED", "HUMAN_ACCEPTED", "REJECTED"]
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reviewer_id: Identifier | None = None
    reviewed_at: AwareDatetime | None = None
    # Automatic acceptance needs a versioned, evaluated policy, not model self-confidence.
    policy_version: Identifier | None = None

    @model_validator(mode="after")
    def acceptance_metadata(self) -> Self:
        if self.status in {"HUMAN_ACCEPTED", "REJECTED"} and (
            self.reviewer_id is None or self.reviewed_at is None
        ):
            raise ValueError("REVIEWER_REQUIRED")
        if self.status == "AUTO_ACCEPTED" and (
            self.policy_version is None or self.confidence is None or self.reviewed_at is None
        ):
            raise ValueError("ACCEPTANCE_POLICY_REQUIRED")
        return self


class RequirementClaim(Contract):
    schema_version: Literal["requirement-claim-v1"] = "requirement-claim-v1"
    claim_id: Sha256
    subject_revision_id: Sha256
    extraction_id: Sha256
    candidate_local_id: Identifier
    kind: RequirementKind
    necessity: Necessity
    polarity: Polarity
    applicability_text: NonEmpty | None
    condition: RequirementCondition
    evidence_ids: Annotated[list[Sha256], Field(min_length=1)]
    assertion_kind: Literal["SOURCE_EXPLICIT", "NORMALIZED", "MODEL_INFERRED"]
    resolver_version: Identifier
    vocabulary_version: Identifier
    review: ReviewDecision

    @property
    def scope(self) -> Literal["CAPABILITY", "POSTING_FILTER"]:
        return (
            "POSTING_FILTER"
            if self.kind in {"LOCATION", "ELIGIBILITY", "AVAILABILITY"}
            else "CAPABILITY"
        )

    @model_validator(mode="after")
    def resolved_and_reviewed(self) -> Self:
        if self.condition.kind not in {self.kind, "UNRESOLVED"}:
            raise ValueError("REQUIREMENT_KIND_MISMATCH")
        if self.review.status in {"AUTO_ACCEPTED", "HUMAN_ACCEPTED"} and (
            self.condition.kind == "UNRESOLVED" or self.necessity == "UNSPECIFIED"
        ):
            raise ValueError("INCOMPLETE_CLAIM_CANNOT_BE_ACCEPTED")
        if self.claim_id != digest(self.model_dump(mode="json", exclude={"claim_id"})):
            raise ValueError("CLAIM_ID_MISMATCH")
        return self
