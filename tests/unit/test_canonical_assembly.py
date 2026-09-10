from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from jobtology_db.contracts.canonical import ExamDates, JobPosting, NCSCompetencyUnit
from jobtology_db.contracts.processing import digest
from jobtology_db.processing.assembly import StagedOccurrence, assemble, document_bindings
from jobtology_db.processing.sources import ProcessingError, normalize
from tests.unit.test_processing import competency, posting


def occurrence(source: str, row: dict[str, Any], partition: str) -> StagedOccurrence:
    record = normalize(source, row, partition)
    return StagedOccurrence(
        revision_id=digest([source, "normalize-v1", record.model_dump(mode="json")]),
        source_id=source,
        snapshot_id="snapshot:" + partition,
        locator="/result/0",
        parser_version="normalize-v1",
        record=record,
        observation_ids=("observation:" + partition,),
    )


def test_posting_pair_uses_list_status_and_detail_description_with_two_documents() -> None:
    items = [
        occurrence("job_alio", posting(), "index"),
        occurrence("job_alio", posting(ongoingYn=None), "detail-123"),
    ]
    bundle = assemble(items)
    assert len(bundle.revisions) == 1 and len(bundle.documents) == 2
    value = bundle.revisions[0].payload
    assert isinstance(value, JobPosting)
    assert value.source_status == "OPEN" and value.primary_occupation_id is None
    assert value.organization_id == "urn:jobtology:alio:organization:C001"
    assert value.description_document_id == bundle.documents[1].document_id
    support = next(s for s in bundle.revisions[0].field_support if s.field == "source_status")
    assert any(
        e.evidence_id in support.evidence_ids and e.document_id == bundle.documents[0].document_id
        for e in bundle.evidence
    )
    assert len(document_bindings(bundle, items)) == 2
    assert bundle.claims == []


def test_posting_missing_pair_or_conflict_fails() -> None:
    listed = occurrence("job_alio", posting(), "index")
    with pytest.raises(ProcessingError, match="LIST_DETAIL_IDENTITY_MISMATCH"):
        assemble([listed])
    with pytest.raises(ProcessingError, match="LIST_DETAIL_FACT_CONFLICT"):
        assemble(
            [listed, occurrence("job_alio", posting(instNm="기관", ongoingYn="N"), "detail-123")]
        )


def test_ncs_assembly_creates_versioned_unit_and_occupation_with_exact_evidence() -> None:
    item = occurrence("ncs_competency", competency(compeUnitLevel="0"), "all")
    bundle = assemble([item])
    assert {r.payload.kind for r in bundle.revisions} == {"Occupation", "NCSCompetencyUnit"}
    unit = next(r.payload for r in bundle.revisions if isinstance(r.payload, NCSCompetencyUnit))
    assert unit.level is None and unit.full_code.endswith("_19v3")
    assert all(span.document_id == bundle.documents[0].document_id for span in bundle.evidence)


def test_qualification_creates_credential_without_invented_attestation() -> None:
    item = occurrence(
        "ncs_qualification",
        {
            "ncsClCd": "2001010506_19v3",
            "jmCd": "T5H0",
            "jmNm": "빅데이터분석",
            "organStdVerCd": "22V1",
            "abltUnitTypCd": "MAND",
        },
        "ncs-2001010506_19v3",
    )
    bundle = assemble([item])
    assert bundle.revisions[0].payload.kind == "Credential"
    assert bundle.revisions[0].entity_id == "urn:jobtology:qnet:qualification:T5H0"
    assert bundle.claims == []


def test_exam_partition_identity_and_dates_remain_precise() -> None:
    item = occurrence(
        "qnet_schedule",
        {
            "implYy": "2026",
            "implSeq": 3,
            "qualgbCd": "C",
            "description": "정기 3회",
            "docRegStartDt": "20260721",
            "docRegEndDt": "20260724",
        },
        "year-2026-item-C193",
    )
    bundle = assemble([item])
    value = bundle.revisions[0].payload
    assert value.kind == "ExamSession"
    assert value.credential_id == "urn:jobtology:qnet:qualification:C193"
    assert value.dates.docRegEndDt == date(2026, 7, 24)
    assert bundle.revisions[0].entity_id.endswith("C193:2026:C:3")
    with pytest.raises(ValidationError, match="EXAM_DATE_ORDER"):
        ExamDates(docRegStartDt=date(2026, 7, 24), docRegEndDt=date(2026, 7, 21))
