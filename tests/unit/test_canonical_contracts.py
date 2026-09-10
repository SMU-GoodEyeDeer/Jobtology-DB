from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from jobtology_db.cli import app
from jobtology_db.contracts import processing as staging
from jobtology_db.contracts.bundle import CanonicalBundle
from jobtology_db.contracts.canonical import (
    DayValue,
    EntityIdentity,
    EntityRevision,
    JobPosting,
    NCSClass,
    NCSCompetencyUnit,
    Organization,
)
from jobtology_db.contracts.documents import EvidenceSpan, SourceDocument, TextBlock, text_hash
from jobtology_db.contracts.person import PersonProjection
from jobtology_db.contracts.processing import digest
from jobtology_db.contracts.requirements import (
    ExtractionOutput,
    ExtractionRecord,
    ExtractorMetadata,
    RequirementClaim,
    ReviewDecision,
)
from jobtology_db.processing.canonical import (
    competency_from_staging,
    document_from_staging,
    occupation_from_staging,
    organization_from_staging,
    posting_from_staging,
)
from jobtology_db.processing.sources import normalize
from jobtology_db.schema_cli import CONTRACTS
from jobtology_db.storage.ontology_schema import neo4j_constraints
from tests.unit.test_processing import competency, posting


def document_fixture(snapshot: str = "snapshot-1", source: str = "fixture") -> SourceDocument:
    text = "Python 또는 Java 경험 우대\n재학생 지원 불가"
    block = TextBlock(block_id="jd", locator="/description", text=text, sha256=text_hash(text))
    data = {
        "schema_version": "canonical-v1",
        "source_id": source,
        "source_record_id": "posting-1",
        "snapshot_id": snapshot,
        "parser_version": "fixture-v1",
        "record_locator": "/result/0",
        "blocks": [block.model_dump(mode="json")],
    }
    return SourceDocument.model_validate({**data, "document_id": digest(data)})


def evidence_fixture(document: SourceDocument) -> EvidenceSpan:
    block = document.blocks[0]
    data = {
        "document_id": document.document_id,
        "block_id": block.block_id,
        "artifact_sha256": block.sha256,
        "start": 0,
        "end": 6,
        "excerpt": "Python",
        "excerpt_sha256": text_hash("Python"),
    }
    return EvidenceSpan.model_validate({**data, "evidence_id": digest(data)})


def extraction_fixture(document: SourceDocument) -> ExtractionRecord:
    output = ExtractionOutput.model_validate(
        {
            "candidates": [
                {
                    "local_id": "python",
                    "kind": "SKILL",
                    "mention": "Python",
                    "necessity": "PREFERRED",
                    "polarity": "POSITIVE",
                    "applicability_text": None,
                    "evidence": [{"block_id": "jd", "start": 0, "end": 6, "excerpt": "Python"}],
                }
            ],
            "groups": [],
        }
    )
    data = {
        "document_id": document.document_id,
        "metadata": ExtractorMetadata(method="RULE", extractor_version="fixture-v1").model_dump(
            mode="json"
        ),
        "output": output.model_dump(mode="json"),
    }
    return ExtractionRecord.model_validate({**data, "extraction_id": digest(data)})


def bundle_fixture(snapshot: str = "snapshot-1", source: str = "fixture") -> CanonicalBundle:
    document = document_fixture(snapshot, source)
    evidence = evidence_fixture(document)
    entity = EntityIdentity(
        entity_id=f"urn:job:{snapshot}",
        kind="JobPosting",
        namespace="fixture:job",
        source_key=snapshot,
    )
    payload = JobPosting(description_document_id=document.document_id)
    data = {
        "schema_version": "canonical-v1",
        "entity_id": entity.entity_id,
        "document_ids": [document.document_id],
        "payload": payload.model_dump(mode="json"),
        "field_support": [],
    }
    revision = EntityRevision.model_validate({**data, "revision_id": digest(data)})
    extraction = extraction_fixture(document)
    claim_data = {
        "schema_version": "requirement-claim-v1",
        "subject_revision_id": revision.revision_id,
        "extraction_id": extraction.extraction_id,
        "candidate_local_id": "python",
        "kind": "SKILL",
        "necessity": "PREFERRED",
        "polarity": "POSITIVE",
        "applicability_text": None,
        "condition": {"kind": "UNRESOLVED", "mention": "Python", "reason": "NO_MATCH"},
        "evidence_ids": [evidence.evidence_id],
        "assertion_kind": "NORMALIZED",
        "resolver_version": "fixture-v1",
        "vocabulary_version": "fixture-v1",
        "review": ReviewDecision(status="PENDING").model_dump(mode="json"),
    }
    claim = RequirementClaim.model_validate({**claim_data, "claim_id": digest(claim_data)})
    return CanonicalBundle(
        documents=[document],
        identities=[entity],
        revisions=[revision],
        evidence=[evidence],
        extractions=[extraction],
        claims=[claim],
    )


@pytest.mark.parametrize("name", CONTRACTS)
def test_contract_exports_json_schema(name: str) -> None:
    result = CliRunner().invoke(app, ["schema", "show", name])
    assert result.exit_code == 0, result.output
    schema = json.loads(result.output)
    assert schema["additionalProperties"] is False


def test_source_neutral_jd_retains_unknowns() -> None:
    posting = JobPosting()
    assert posting.source_status == "UNKNOWN"
    assert "organization_id" in posting.missing_publication_fields()
    assert "date_posted" in posting.missing_publication_fields()
    assert "representation" not in JobPosting.model_fields
    with pytest.raises(ValidationError):
        JobPosting.model_validate({"invented_field": "not allowed"})


def test_date_precision_and_order() -> None:
    posting = JobPosting.model_validate(
        {
            "date_posted": {"precision": "DAY", "value": "2026-09-01"},
            "valid_through": {"precision": "DAY", "value": "2026-09-14"},
        }
    )
    assert isinstance(posting.valid_through, DayValue)
    assert posting.model_dump(mode="json")["valid_through"]["value"] == "2026-09-14"
    with pytest.raises(ValidationError, match="POSTING_DATE_ORDER"):
        JobPosting.model_validate(
            {
                "date_posted": {"precision": "DAY", "value": "2026-09-15"},
                "valid_through": {"precision": "DAY", "value": "2026-09-14"},
            }
        )
    with pytest.raises(ValidationError):
        JobPosting.model_validate(
            {
                "valid_through": {
                    "precision": "INSTANT",
                    "value": "2026-09-14T13:00:00",
                }
            }
        )


def test_ncs_preserves_full_version_and_class_depth() -> None:
    unit = NCSCompetencyUnit(
        name_ko="분석",
        full_code="2001010506_19v3",
        base_code="2001010506",
        version="19v3",
        occupation_id="ncs:20010105",
    )
    assert unit.level is None
    with pytest.raises(ValidationError, match="NCS_VERSION_MISMATCH"):
        NCSCompetencyUnit.model_validate({**unit.model_dump(), "version": "19v4"})
    with pytest.raises(ValidationError):
        NCSCompetencyUnit.model_validate({**unit.model_dump(), "full_code": "2001010506"})
    with pytest.raises(ValidationError, match="INVALID_NCS_CLASS_HIERARCHY"):
        NCSClass(
            name_ko="정보통신", code="20", taxonomy_version="2026", depth=2, parent_id="ncs:root"
        )


def test_organization_name_does_not_generate_identity_or_merge() -> None:
    organization = Organization(name_ko="동일한 이름")
    assert organization.identifiers == [] and organization.employer_type == "UNKNOWN"
    assert "entity_id" not in Organization.model_fields


def test_document_and_span_integrity() -> None:
    document = document_fixture()
    evidence_fixture(document).verify_document(document)
    changed = document.model_dump(mode="json")
    changed["blocks"][0]["text"] = "changed"
    with pytest.raises(ValidationError, match="TEXT_ARTIFACT_INTEGRITY_FAILED"):
        SourceDocument.model_validate(changed)
    # Correct excerpt hash/length is insufficient if offsets select another string.
    span_data = evidence_fixture(document).model_dump(mode="json", exclude={"evidence_id"})
    span_data.update(start=1, end=7)
    span = EvidenceSpan.model_validate({**span_data, "evidence_id": digest(span_data)})
    with pytest.raises(ValueError, match="EVIDENCE_SPAN_NOT_IN_DOCUMENT"):
        span.verify_document(document)


def test_unicode_codepoint_spans_not_bytes() -> None:
    document = document_fixture()
    text = document.blocks[0].text
    start = text.index("재학생")
    output = extraction_fixture(document).output.model_dump(mode="json")
    output["candidates"][0]["evidence"] = [
        {
            "block_id": "jd",
            "start": start,
            "end": start + 3,
            "excerpt": "재학생",
        }
    ]
    ExtractionOutput.model_validate(output).verify_document(document)


def test_extractor_cannot_self_accept_or_assign_canonical_ids() -> None:
    output = extraction_fixture(document_fixture()).output.model_dump(mode="json")
    output["candidates"][0]["confidence"] = 1
    output["candidates"][0]["target_id"] = "invented:python"
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(output)


def test_and_or_groups_keep_alternatives_and_reject_cycles() -> None:
    output = extraction_fixture(document_fixture()).output.model_dump(mode="json")
    second = {**output["candidates"][0], "local_id": "java", "mention": "Java"}
    output["candidates"].append(second)
    output["groups"] = [
        {
            "local_id": "alternative",
            "operator": "ANY_OF",
            "member_ids": ["python", "java"],
            "evidence": second["evidence"],
        }
    ]
    assert ExtractionOutput.model_validate(output).groups[0].operator == "ANY_OF"
    output["groups"][0]["member_ids"] = ["python", "alternative"]
    with pytest.raises(ValidationError, match="CYCLIC_REQUIREMENT_GROUP"):
        ExtractionOutput.model_validate(output)


def test_unresolved_cannot_be_accepted() -> None:
    claim_data = bundle_fixture().claims[0].model_dump(mode="json", exclude={"claim_id"})
    claim_data["review"] = ReviewDecision(
        status="HUMAN_ACCEPTED", reviewer_id="reviewer:1", reviewed_at=datetime.now(UTC)
    ).model_dump(mode="json")
    with pytest.raises(ValidationError, match="INCOMPLETE_CLAIM_CANNOT_BE_ACCEPTED"):
        RequirementClaim.model_validate({**claim_data, "claim_id": digest(claim_data)})


def test_acceptance_requires_policy_or_reviewer() -> None:
    with pytest.raises(ValidationError, match="ACCEPTANCE_POLICY_REQUIRED"):
        ReviewDecision(status="AUTO_ACCEPTED", confidence=1)
    with pytest.raises(ValidationError, match="REVIEWER_REQUIRED"):
        ReviewDecision(status="HUMAN_ACCEPTED")
    with pytest.raises(ValidationError, match="MISSING_MODEL_PROVENANCE"):
        ExtractorMetadata(method="LLM", extractor_version="v1")


def test_bundle_validates_relations_and_claim_meaning() -> None:
    bundle = bundle_fixture()
    assert CanonicalBundle.model_validate_json(bundle.model_dump_json()) == bundle
    invalid = bundle.model_dump(mode="json")
    invalid["identities"][0]["kind"] = "Organization"
    with pytest.raises(ValidationError, match="MISSING_OR_WRONG_ENTITY_TYPE"):
        CanonicalBundle.model_validate(invalid)
    invalid = bundle.model_dump(mode="json")
    claim = invalid["claims"][0]
    claim["necessity"] = "REQUIRED"
    claim["claim_id"] = digest({k: v for k, v in claim.items() if k != "claim_id"})
    with pytest.raises(ValidationError, match="CLAIM_CHANGED_EXTRACTED_MEANING"):
        CanonicalBundle.model_validate(invalid)


@pytest.mark.parametrize("private_field", ["name", "email", "school", "resume", "chat"])
def test_person_projection_excludes_private_profile_fields(private_field: str) -> None:
    data: dict[str, Any] = {"person_id": str(uuid4()), "projection_version": 1}
    assert PersonProjection.model_validate(data).target_occupation_id is None
    data[private_field] = "private"
    with pytest.raises(ValidationError):
        PersonProjection.model_validate(data)


def test_person_not_a_corpus_entity_and_uses_opaque_id() -> None:
    with pytest.raises(ValidationError):
        EntityIdentity.model_validate(
            {"entity_id": "person:1", "kind": "Person", "namespace": "person", "source_key": "1"}
        )
    with pytest.raises(ValidationError):
        PersonProjection.model_validate(
            {"person_id": "student@example.com", "projection_version": 1}
        )
    person = {
        "person_id": str(uuid4()),
        "projection_version": 1,
        "capabilities": [{"target_kind": "Skill", "target_id": "skill:python"}] * 2,
    }
    with pytest.raises(ValidationError, match="DUPLICATE_PERSON_CAPABILITY"):
        PersonProjection.model_validate(person)


def test_constraints_are_explicit_and_do_not_touch_staging() -> None:
    corpus = neo4j_constraints()
    private = neo4j_constraints(include_person=True)
    assert not any(":Person" in statement for statement in corpus)
    assert len(private) == len(corpus) + 1
    assert all("Ingest" not in statement for statement in private)
    result = CliRunner().invoke(app, ["schema", "neo4j-ddl", "--include-person"])
    assert result.exit_code == 0 and "n.person_id IS UNIQUE" in result.output


def test_posting_bridge_keeps_missing_mappings_and_source_provenance() -> None:
    record = normalize("job_alio", posting(ongoingYn=None), "detail-123")
    assert isinstance(record.normalized, staging.JobPosting)
    document = document_from_staging(
        record, source_id="job_alio", snapshot_id="snapshot-1", record_locator="/result"
    )
    draft = posting_from_staging(record.normalized, document_id=document.document_id)
    assert draft.organization_id is None and draft.primary_occupation_id is None
    assert draft.source_status == "UNKNOWN"
    assert document.source_record_id == "123:detail"
    assert any(b.locator == "/aplyQlfcCn" and "응시 제외" in b.text for b in document.blocks)
    assert "representation" not in draft.model_dump()


def test_ncs_bridge_does_not_make_unversioned_or_unspecified_level_claims() -> None:
    record = normalize("ncs_competency", competency(compeUnitLevel="0"), "all")
    assert isinstance(record.normalized, staging.Competency)
    unit = competency_from_staging(record.normalized, occupation_id="ncs:20010105")
    occupation = occupation_from_staging(record.normalized, scheme_id="scheme:ncs")
    assert unit.full_code == "2001010506_19v3" and unit.level is None
    assert occupation.scheme_id == "scheme:ncs" and occupation.code == "20010105"


def test_organization_bridge_does_not_infer_employer_type() -> None:
    record = normalize("alio_organization", {"instCd": "C001", "instNm": "기관"}, "all")
    assert isinstance(record.normalized, staging.Organization)
    organization = organization_from_staging(record.normalized)
    assert organization.employer_type == "UNKNOWN"
    assert organization.identifiers[0].scheme == "alio:instCd"
    assert organization.identifiers[0].value == "C001"


def test_ncs_canonical_identity_cannot_collapse_unit_versions() -> None:
    document = document_fixture()
    occupation = EntityIdentity(
        entity_id="ncs:20010105",
        kind="Occupation",
        namespace="ncs:occupation",
        source_key="20010105",
    )
    unit = EntityIdentity(
        entity_id="ncs:unit:2001010506_19v3",
        kind="NCSCompetencyUnit",
        namespace="ncs:unit",
        source_key="2001010506",
    )
    value = NCSCompetencyUnit(
        name_ko="분석",
        full_code="2001010506_19v3",
        base_code="2001010506",
        version="19v3",
        occupation_id=occupation.entity_id,
    )
    data = {
        "schema_version": "canonical-v1",
        "entity_id": unit.entity_id,
        "document_ids": [document.document_id],
        "payload": value.model_dump(mode="json"),
        "field_support": [],
    }
    revision = EntityRevision.model_validate({**data, "revision_id": digest(data)})
    with pytest.raises(ValidationError, match="NCS_IDENTITY_MUST_INCLUDE_VERSION"):
        CanonicalBundle(documents=[document], identities=[occupation, unit], revisions=[revision])
