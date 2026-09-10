"""Deterministic canonical draft assembly from verified source-record occurrences."""

from __future__ import annotations

from dataclasses import dataclass

from jobtology_db.contracts import canonical as canonical
from jobtology_db.contracts import processing as staging
from jobtology_db.contracts.bundle import CanonicalBundle
from jobtology_db.contracts.documents import EvidenceSpan, text_hash
from jobtology_db.processing.canonical import (
    competency_from_staging,
    document_from_staging,
    occupation_from_staging,
    organization_from_staging,
    posting_from_staging,
)
from jobtology_db.processing.sources import ProcessingError

ASSEMBLER_VERSION = "canonical-assembly-v1"


@dataclass(frozen=True)
class StagedOccurrence:
    revision_id: str
    source_id: str
    snapshot_id: str
    locator: str
    parser_version: str
    record: staging.Record
    observation_ids: tuple[str, ...]


def identity(kind: canonical.EntityKind, namespace: str, key: str) -> canonical.EntityIdentity:
    return canonical.EntityIdentity(
        entity_id=f"urn:jobtology:{namespace}:{key}",
        kind=kind,
        namespace=namespace,
        source_key=key,
    )


def assemble(occurrences: list[StagedOccurrence]) -> CanonicalBundle:
    """One non-posting occurrence, or a JOB-ALIO list/detail pair from the same complete run."""
    documents = [
        document_from_staging(
            item.record,
            source_id=item.source_id,
            snapshot_id=item.snapshot_id,
            record_locator=item.locator,
            parser_version=item.parser_version,
        )
        for item in occurrences
    ]
    if not documents or len({d.document_id for d in documents}) != len(documents):
        raise ProcessingError("INVALID_ASSEMBLY_OCCURRENCES")
    entities: dict[str, canonical.EntityIdentity] = {}
    evidence: dict[str, EvidenceSpan] = {}
    revisions: list[canonical.EntityRevision] = []

    def entity(kind: canonical.EntityKind, namespace: str, key: str) -> str:
        item = identity(kind, namespace, key)
        entities[item.entity_id] = item
        return item.entity_id

    def add_revision(
        entity_id: str,
        value: canonical.EntityPayload,
        origins: dict[str, tuple[int, str]],
    ) -> None:
        support: list[canonical.FieldSupport] = []
        for field, (index, staged_field) in sorted(origins.items()):
            if getattr(value, field) is None:
                continue
            document = documents[index]
            pointers = [
                pointer
                for name, locations in occurrences[index].record.field_lineage.items()
                if name == staged_field or name.startswith(staged_field + ".")
                for pointer in locations
            ]
            ids: list[str] = []
            for block in document.blocks:
                if block.locator not in pointers:
                    continue
                data = {
                    "document_id": document.document_id,
                    "block_id": block.block_id,
                    "artifact_sha256": block.sha256,
                    "start": 0,
                    "end": len(block.text),
                    "excerpt": block.text,
                    "excerpt_sha256": text_hash(block.text),
                }
                span = EvidenceSpan.model_validate({**data, "evidence_id": staging.digest(data)})
                evidence[span.evidence_id] = span
                ids.append(span.evidence_id)
            if ids:
                support.append(
                    canonical.FieldSupport(
                        field=field,
                        evidence_ids=sorted(set(ids)),
                        method="NORMALIZED",
                    )
                )
        payload = {
            "schema_version": "canonical-v1",
            "entity_id": entity_id,
            "document_ids": sorted(d.document_id for d in documents),
            "payload": value.model_dump(mode="json"),
            "field_support": [s.model_dump(mode="json") for s in support],
        }
        revisions.append(
            canonical.EntityRevision.model_validate(
                {
                    **payload,
                    "revision_id": staging.digest(payload),
                }
            )
        )

    def origin(mapping: dict[str, str]) -> dict[str, tuple[int, str]]:
        return {field: (0, source_field) for field, source_field in mapping.items()}

    value = occurrences[0].record.normalized
    if isinstance(value, staging.JobPosting):
        paired = {
            item.record.normalized.representation: (i, item.record.normalized)
            for i, item in enumerate(occurrences)
            if isinstance(item.record.normalized, staging.JobPosting)
        }
        if len(occurrences) != 2 or set(paired) != {"list", "detail"}:
            raise ProcessingError("LIST_DETAIL_IDENTITY_MISMATCH")
        listed_index, listed = paired["list"]
        detail_index, detail = paired["detail"]
        if any(
            getattr(listed, field) != getattr(detail, field)
            for field in (
                "posting_id",
                "organization_code",
                "title",
                "date_posted",
                "closing_date",
            )
        ) or (detail.ongoing is not None and detail.ongoing != listed.ongoing):
            raise ProcessingError("LIST_DETAIL_FACT_CONFLICT")
        if occurrences[0].source_id != "job_alio" or occurrences[1].source_id != "job_alio":
            raise ProcessingError("ASSEMBLY_SOURCE_MISMATCH")
        data = detail.model_dump()
        field_origins: dict[str, int] = {}
        for field in type(detail).model_fields:
            # Detail wins for supplied fields; explicit list status fills null detail status.
            index = detail_index if data[field] is not None else listed_index
            field_origins[field] = index
            if data[field] is None:
                data[field] = getattr(listed, field)
        merged = staging.JobPosting.model_validate(data)
        organization_id = entity("Organization", "alio:organization", merged.organization_code)
        posting_id = entity("JobPosting", "job-alio:posting", merged.posting_id)
        posting = posting_from_staging(
            merged,
            document_id=documents[detail_index].document_id,
            organization_id=organization_id,
        )
        mapping = {
            "title": "title",
            "canonical_url": "source_url",
            "organization_id": "organization_code",
            "organization_name_text": "organization_name",
            "date_posted": "date_posted",
            "valid_through": "closing_date",
            "source_status": "ongoing",
            "employment_type_text": "employment_type",
            "recruitment_type_text": "recruitment_type",
            "education_text": "education",
            "region_text": "regions",
            "ncs_categories_text": "ncs_category_names",
            "headcount": "headcount",
        }
        add_revision(
            posting_id,
            posting,
            {
                field: (field_origins[source_field], source_field)
                for field, source_field in mapping.items()
            },
        )
    else:
        if len(occurrences) != 1:
            raise ProcessingError("INVALID_ASSEMBLY_OCCURRENCES")
        if isinstance(value, (staging.CareerPath, staging.Competency)):
            scheme_id = entity("ConceptScheme", "scheme", "ncs")
            occupation_id = entity("Occupation", "ncs:occupation", value.occupation_code)
            add_revision(
                occupation_id,
                occupation_from_staging(value, scheme_id=scheme_id),
                origin(
                    {
                        "name_ko": "occupation_name",
                        "code": "occupation_code",
                    }
                ),
            )
            if isinstance(value, staging.Competency):
                unit_id = entity("NCSCompetencyUnit", "ncs:unit", value.code)
                add_revision(
                    unit_id,
                    competency_from_staging(value, occupation_id=occupation_id),
                    origin(
                        {
                            "name_ko": "name",
                            "full_code": "code",
                            "base_code": "code",
                            "version": "code",
                            "definition": "definition",
                            "level": "level",
                            "occupation_id": "occupation_code",
                        }
                    ),
                )
        elif isinstance(value, staging.Organization):
            org_id = entity("Organization", "alio:organization", value.code)
            add_revision(
                org_id,
                organization_from_staging(value),
                origin(
                    {
                        "name_ko": "name",
                        "identifiers": "code",
                        "organization_type_text": "organization_type",
                        "website": "website",
                        "address_text": "address",
                        "established_date": "established_date",
                    }
                ),
            )
        elif isinstance(value, staging.QualificationMapping):
            credential_id = entity("Credential", "qnet:qualification", value.qualification_code)
            credential = canonical.Credential(
                name_ko=value.qualification_name,
                identifiers=[
                    canonical.ExternalIdentifier(scheme="qnet:jmCd", value=value.qualification_code)
                ],
            )
            add_revision(
                credential_id,
                credential,
                origin(
                    {
                        "name_ko": "qualification_name",
                        "identifiers": "qualification_code",
                    }
                ),
            )
        else:
            credential_id = entity("Credential", "qnet:qualification", value.qualification_code)
            session_id = entity("ExamSession", "qnet:exam", occurrences[0].record.source_record_id)
            exam = canonical.ExamSession(
                name_ko=value.name,
                credential_id=credential_id,
                year=value.year,
                round=value.round,
                category_code=value.category_code,
                dates=canonical.ExamDates.model_validate(value.dates),
            )
            # Numeric/request-context fields remain grounded through the staging input manifest.
            add_revision(
                session_id,
                exam,
                origin(
                    {
                        "name_ko": "name",
                        "category_code": "category_code",
                        "year": "year",
                    "round": "round",
                    "dates": "dates",
                    }
                ),
            )
    return CanonicalBundle(
        documents=documents,
        identities=list(entities.values()),
        revisions=revisions,
        evidence=list(evidence.values()),
    )


def document_bindings(
    bundle: CanonicalBundle,
    occurrences: list[StagedOccurrence],
) -> dict[str, list[str]]:
    return {
        document.document_id: list(item.observation_ids)
        for document, item in zip(bundle.documents, occurrences, strict=True)
    }
