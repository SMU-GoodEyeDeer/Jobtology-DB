"""Pure bridges from validated staging to canonical drafts. No writes or inference."""

from jobtology_db.contracts import processing as staging
from jobtology_db.contracts.canonical import (
    DayValue,
    ExternalIdentifier,
    JobPosting,
    NCSCompetencyUnit,
    Occupation,
    Organization,
)
from jobtology_db.contracts.documents import SourceDocument, TextBlock


def document_from_staging(
    record: staging.Record,
    *,
    source_id: str,
    snapshot_id: str,
    record_locator: str,
    parser_version: str = staging.PROCESSOR_VERSION,
) -> SourceDocument:
    if any(artifact.normalization_version != "nfc-lf-v1" for artifact in record.texts.values()):
        raise ValueError("UNSUPPORTED_TEXT_NORMALIZATION_VERSION")
    blocks = [
        TextBlock(
            block_id=staging.digest(pointer),
            locator=pointer,
            text=artifact.text,
            sha256=artifact.sha256,
            normalization_version="nfc-lf-v1",
        )
        for pointer, artifact in sorted(record.texts.items())
    ]
    data = {
        "schema_version": "canonical-v1",
        "source_id": source_id,
        "source_record_id": record.source_record_id,
        "snapshot_id": snapshot_id,
        "parser_version": parser_version,
        "record_locator": record_locator,
        "blocks": [block.model_dump(mode="json") for block in blocks],
    }
    return SourceDocument.model_validate({**data, "document_id": staging.digest(data)})


def posting_from_staging(
    value: staging.JobPosting,
    *,
    document_id: str,
    organization_id: str | None = None,
) -> JobPosting:
    return JobPosting(
        title=value.title,
        canonical_url=value.source_url,
        description_document_id=document_id,
        organization_id=organization_id,
        organization_name_text=value.organization_name,
        date_posted=DayValue(value=value.date_posted),
        valid_through=DayValue(value=value.closing_date),
        source_status="UNKNOWN" if value.ongoing is None else "OPEN" if value.ongoing else "CLOSED",
        employment_type_text=value.employment_type,
        recruitment_type_text=value.recruitment_type,
        education_text=value.education,
        region_text=value.regions,
        ncs_categories_text=value.ncs_category_names,
        headcount=value.headcount,
    )


def organization_from_staging(value: staging.Organization) -> Organization:
    return Organization(
        name_ko=value.name,
        identifiers=[ExternalIdentifier(scheme="alio:instCd", value=value.code)],
        organization_type_text=value.organization_type,
        website=value.website,
        address_text=value.address,
        established_date=value.established_date,
    )


def occupation_from_staging(
    value: staging.CareerPath | staging.Competency,
    *,
    scheme_id: str,
) -> Occupation:
    return Occupation(
        name_ko=value.occupation_name, code=value.occupation_code, scheme_id=scheme_id
    )


def competency_from_staging(
    value: staging.Competency,
    *,
    occupation_id: str,
) -> NCSCompetencyUnit:
    base, version = value.code.split("_", maxsplit=1)
    return NCSCompetencyUnit(
        name_ko=value.name,
        full_code=value.code,
        base_code=base,
        version=version,
        level=value.level,
        definition=value.definition,
        occupation_id=occupation_id,
    )
