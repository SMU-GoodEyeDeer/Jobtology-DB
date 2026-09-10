"""Cross-record validation before persistence; schema shape alone is insufficient."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from jobtology_db.contracts.canonical import (
    Credential,
    EntityIdentity,
    EntityRevision,
    ExamSession,
    JobPosting,
    NCSClass,
    NCSCompetencyUnit,
    Occupation,
    Organization,
    Skill,
)
from jobtology_db.contracts.documents import EvidenceSpan, SourceDocument
from jobtology_db.contracts.processing import Contract
from jobtology_db.contracts.requirements import (
    CapabilityCondition,
    CredentialCondition,
    ExtractionRecord,
    RequirementClaim,
)


class CanonicalBundle(Contract):
    documents: list[SourceDocument]
    identities: list[EntityIdentity]
    revisions: list[EntityRevision]
    evidence: list[EvidenceSpan] = Field(default_factory=list[EvidenceSpan])
    extractions: list[ExtractionRecord] = Field(default_factory=list[ExtractionRecord])
    claims: list[RequirementClaim] = Field(default_factory=list[RequirementClaim])

    @model_validator(mode="after")
    def references_and_evidence(self) -> Self:
        documents = {d.document_id: d for d in self.documents}
        identities = {e.entity_id: e for e in self.identities}
        revisions = {r.revision_id: r for r in self.revisions}
        evidence = {e.evidence_id: e for e in self.evidence}
        extractions = {e.extraction_id: e for e in self.extractions}
        pairs = (
            (documents, self.documents),
            (identities, self.identities),
            (revisions, self.revisions),
            (evidence, self.evidence),
            (extractions, self.extractions),
            ({c.claim_id: c for c in self.claims}, self.claims),
        )
        if any(len(index) != len(values) for index, values in pairs):
            raise ValueError("DUPLICATE_BUNDLE_ID")

        def require_entity(entity_id: str | None, expected: str) -> None:
            if entity_id is not None:
                entity = identities.get(entity_id)
                if entity is None or entity.kind != expected:
                    raise ValueError("MISSING_OR_WRONG_ENTITY_TYPE")

        for span in self.evidence:
            if span.document_id not in documents:
                raise ValueError("MISSING_EVIDENCE_DOCUMENT")
            span.verify_document(documents[span.document_id])
        for revision in self.revisions:
            value = revision.payload
            require_entity(revision.entity_id, value.kind)
            if not set(revision.document_ids) <= documents.keys():
                raise ValueError("MISSING_REVISION_DOCUMENT")
            for support in revision.field_support:
                for evidence_id in support.evidence_ids:
                    span = evidence.get(evidence_id)
                    if span is None or span.document_id not in revision.document_ids:
                        raise ValueError("INVALID_FIELD_EVIDENCE")
            if isinstance(value, (Occupation, Skill)):
                require_entity(value.scheme_id, "ConceptScheme")
            if isinstance(value, Occupation):
                for entity_id in value.ncs_class_ids:
                    require_entity(entity_id, "NCSClass")
            elif isinstance(value, NCSClass):
                require_entity(value.parent_id, "NCSClass")
            elif isinstance(value, NCSCompetencyUnit):
                require_entity(value.occupation_id, "Occupation")
                if identities[revision.entity_id].source_key != value.full_code:
                    raise ValueError("NCS_IDENTITY_MUST_INCLUDE_VERSION")
            elif isinstance(value, Organization):
                require_entity(value.supervising_organization_id, "Organization")
            elif isinstance(value, Credential):
                require_entity(value.issuing_organization_id, "Organization")
            elif isinstance(value, ExamSession):
                require_entity(value.credential_id, "Credential")
            elif isinstance(value, JobPosting):
                require_entity(value.organization_id, "Organization")
                require_entity(value.primary_occupation_id, "Occupation")
        for extraction in self.extractions:
            if extraction.document_id not in documents:
                raise ValueError("MISSING_EXTRACTION_DOCUMENT")
            extraction.output.verify_document(documents[extraction.document_id])
        for claim in self.claims:
            revision = revisions.get(claim.subject_revision_id)
            extraction = extractions.get(claim.extraction_id)
            if (
                revision is None
                or not isinstance(revision.payload, JobPosting)
                or extraction is None
                or extraction.document_id not in revision.document_ids
            ):
                raise ValueError("INVALID_CLAIM_SUBJECT")
            candidate = next(
                (c for c in extraction.output.candidates if c.local_id == claim.candidate_local_id),
                None,
            )
            if candidate is None or (
                candidate.kind,
                candidate.necessity,
                candidate.polarity,
                candidate.applicability_text,
            ) != (claim.kind, claim.necessity, claim.polarity, claim.applicability_text):
                raise ValueError("CLAIM_CHANGED_EXTRACTED_MEANING")
            spans: list[EvidenceSpan] = []
            for evidence_id in claim.evidence_ids:
                span = evidence.get(evidence_id)
                if span is None or span.document_id != extraction.document_id:
                    raise ValueError("INVALID_CLAIM_EVIDENCE")
                spans.append(span)
            actual = {(s.block_id, s.start, s.end, s.excerpt) for s in spans}
            expected = {(s.block_id, s.start, s.end, s.excerpt) for s in candidate.evidence}
            if not expected <= actual:
                raise ValueError("CLAIM_OMITTED_CANDIDATE_EVIDENCE")
            condition = claim.condition
            if isinstance(condition, CapabilityCondition):
                require_entity(condition.target_id, condition.target_kind)
                if condition.kind == "LANGUAGE":
                    payloads = [
                        r.payload for r in self.revisions if r.entity_id == condition.target_id
                    ]
                    if not payloads or any(
                        not isinstance(p, Skill) or p.skill_kind != "LANGUAGE" for p in payloads
                    ):
                        raise ValueError("LANGUAGE_VOCABULARY_REQUIRED")
            elif isinstance(condition, CredentialCondition):
                require_entity(condition.target_id, "Credential")
        return self
