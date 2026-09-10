from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jobtology_db.contracts.processing import Competency, ExamSession, JobPosting, digest
from jobtology_db.pipeline.process import validate_completeness
from jobtology_db.pipeline.update import Schedule, due, read_schedule
from jobtology_db.processing.sources import (
    ProcessingError,
    normalize,
    normalized_text,
    parse_document,
)
from jobtology_db.storage.neo4j_staging import graph_record
from jobtology_db.storage.processing import SnapshotInput, read_raw


def competency(**overrides: Any) -> dict[str, Any]:
    return {
        "ncsClCd": "2001010506_19v3",
        "compeUnitName": "통계 기반 데이터 분석",
        "compeUnitLevel": "6",
        "compeUnitDef": "분석\r\n모델",
        "ncsSubdCdnm": "빅데이터분석",
        "ncsLclasCdnm": "정보통신",
        "ncsMclasCdnm": "정보기술",
        "ncsSclasCdnm": "정보기술전략·계획",
        **overrides,
    }


def posting(**overrides: Any) -> dict[str, Any]:
    return {
        "recrutPblntSn": 123,
        "recrutPbancTtl": "백엔드 개발자",
        "pblntInstCd": "C001",
        "instNm": "테스트기관",
        "pbancBgngYmd": "20260901",
        "pbancEndYmd": "20260930",
        "ongoingYn": "Y",
        "aplyQlfcCn": "대학교 재학생 및 휴학생은 응시 제외",
        "recrutSeNm": "신입+경력",
        "recrutNope": 1,
        **overrides,
    }


def input_ref(partition: str = "all", page: int | None = 1, ordinal: int = 0) -> SnapshotInput:
    return SnapshotInput(
        observation_id=f"o-{partition}-{page}-{ordinal}",
        snapshot_id="snapshot",
        partition_id=partition,
        page_number=page,
        response_ordinal=ordinal,
        retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
        raw_object_path="raw/file",
        content_sha256="a" * 64,
        byte_length=3,
        mime_type="application/json",
    )


def test_competency_preserves_evidence_and_nfc_lf_text() -> None:
    raw = competency(compeUnitDef="가\r\n분석\r방법")
    record = normalize("ncs_competency", raw, "all")
    assert isinstance(record.normalized, Competency)
    assert record.normalized.occupation_code == "20010105"
    artifact = record.texts["/compeUnitDef"]
    assert artifact.text == "가\n분석\n방법"
    assert artifact.sha256 == hashlib.sha256(artifact.text.encode()).hexdigest()
    assert record.source_payload["compeUnitDef"] == raw["compeUnitDef"]
    assert record.field_lineage["definition"] == ["/compeUnitDef"]
    assert normalized_text(artifact.text) == artifact.text


def test_source_zero_level_is_explicit_unknown_not_level_zero() -> None:
    record = normalize("ncs_competency", competency(compeUnitLevel="0"), "all")
    assert isinstance(record.normalized, Competency)
    assert record.normalized.level is None
    assert record.quality_flags == ["UNSPECIFIED_COMPETENCY_LEVEL"]
    assert record.source_payload["compeUnitLevel"] == "0"


def test_qualification_identity_includes_standard_version() -> None:
    row: dict[str, Any] = {
        "ncsClCd": "2001010506_19v3",
        "jmCd": "T5H0",
        "jmNm": "빅데이터분석",
        "organStdVerCd": "22V1",
        "abltUnitTypCd": "MAND",
        "minEduTrngTm": 40,
    }
    first = normalize("ncs_qualification", row, "ncs-2001010506_19v3")
    second = normalize("ncs_qualification", {**row, "organStdVerCd": "23V1"}, "ncs-2001010506_19v3")
    assert first.source_record_id != second.source_record_id
    with pytest.raises(ProcessingError, match="PARTITION_IDENTITY_MISMATCH"):
        normalize("ncs_qualification", row, "ncs-2001010507_19v2")


def test_exam_session_uses_partition_and_does_not_invent_fee_or_clock_time() -> None:
    row: dict[str, Any] = {
        "implYy": "2026",
        "implSeq": 3,
        "qualgbCd": "C",
        "description": "정기 3회",
        "docRegStartDt": "20260721",
        "docRegEndDt": "20260724",
    }
    result = normalize("qnet_schedule", row, "year-2026-item-C193")
    assert isinstance(result.normalized, ExamSession)
    assert result.normalized.qualification_code == "C193"
    assert result.field_lineage["qualification_code"] == ["request:partition_id"]
    assert result.normalized.dates["docPassDt"] is None
    end_date = result.normalized.dates["docRegEndDt"]
    assert end_date is not None and end_date.isoformat() == "2026-07-24"
    with pytest.raises(ProcessingError, match="PARTITION_IDENTITY_MISMATCH"):
        normalize("qnet_schedule", row, "year-2027-item-C193")
    with pytest.raises(ProcessingError, match="REVERSED_DATE_RANGE"):
        normalize("qnet_schedule", {**row, "docRegEndDt": "20260720"}, "year-2026-item-C193")


def test_posting_list_detail_remain_distinct_and_missing_status_is_unknown() -> None:
    listed = normalize("job_alio", posting(), "index")
    detail = normalize("job_alio", posting(ongoingYn=None), "detail-123")
    assert listed.source_record_id == "123:list"
    assert detail.source_record_id == "123:detail"
    assert isinstance(detail.normalized, JobPosting)
    assert detail.normalized.ongoing is None
    assert detail.normalized.eligibility_text == "대학교 재학생 및 휴학생은 응시 제외"
    with pytest.raises(ProcessingError, match="PARTITION_IDENTITY_MISMATCH"):
        normalize("job_alio", posting(), "detail-999")


@pytest.mark.parametrize("value", ["20260230", "2026-09-30", "", None])
def test_invalid_posting_dates_fail_closed(value: str | None) -> None:
    with pytest.raises(ProcessingError):
        normalize("job_alio", posting(pbancEndYmd=value), "index")


def test_invalid_row_quarantined_without_truncating_following_rows() -> None:
    body = json.dumps(
        {
            "root": {
                "info": {"pageNo": 1, "numOfRows": 3, "totalCount": 3},
                "items": [
                    competency(),
                    competency(ncsClCd="bad"),
                    competency(ncsClCd="2001010507_19v2"),
                ],
            }
        }
    ).encode()
    parsed = parse_document("ncs_competency", body, "all", 1)
    assert parsed.row_count == 3
    assert len(parsed.records) == 2
    assert parsed.rejected[0].locator == "/root/items/1"
    assert parsed.rejected[0].error_code == "INVALID_NCS_CODE"


def test_csv_cp949_and_logical_record_locations() -> None:
    header = (
        "대분류코드,중분류코드,소분류코드,직무코드,직무명,직무역량코드,"
        "직무역량수준(능력단위수준 이면서 세분류의 자식),직무역량명,수준(직급수준),직급명\r\n"
    )
    body = (
        header + '20,1,2,2,응용SW엔지니어링,14,3,"애플리케이션\r\n배포",3,프로그래머\r\n'
    ).encode("cp949")
    parsed = parse_document("ncs_career_path", body, "file", None)
    assert parsed.encoding == "cp949"
    assert parsed.records[0].locator == "csv:record:1"
    assert parsed.records[0].record.normalized.model_dump()["occupation_code"] == "20010202"
    with pytest.raises(ProcessingError, match="MISSING_CSV_COLUMNS"):
        parse_document("ncs_career_path", b"id,name\n1,test", "file", None)


def test_organization_keeps_official_identity_not_name_fuzzy_matching() -> None:
    record = normalize(
        "alio_organization",
        {"instCd": "C001", "instNm": "기관", "siteUrl": "www.example.org"},
        "institutions",
    )
    assert record.source_record_id == "C001"
    assert record.normalized.model_dump()["website"] == "www.example.org"


def page_meta(
    *, total: int = 2, size: int = 1, identities: list[str] | None = None, rows: int = 1
) -> dict[str, Any]:
    return {
        "total": total,
        "page_size": size,
        "row_count": rows,
        "identities": identities or [],
        "rejected_count": 0,
    }


def test_completeness_requires_all_pages_and_unique_identities() -> None:
    first = (input_ref(page=1), page_meta(identities=["one"]))
    second = (input_ref(page=2), page_meta(identities=["two"]))
    validate_completeness("ncs_competency", [first, second])
    with pytest.raises(ProcessingError, match="MISSING_OR_DUPLICATE_PAGES"):
        validate_completeness("ncs_competency", [first])
    with pytest.raises(ProcessingError, match="DUPLICATE_SOURCE_IDENTITY"):
        validate_completeness("ncs_competency", [first, (input_ref(page=2), first[1])])
    with pytest.raises(ProcessingError, match="UNSTABLE_PAGINATION"):
        validate_completeness("ncs_competency", [first, (input_ref(page=2), page_meta(total=3))])


def test_empty_partition_needs_two_observations() -> None:
    first = (input_ref(), page_meta(total=0, rows=0))
    with pytest.raises(ProcessingError, match="UNCONFIRMED_EMPTY_PARTITION"):
        validate_completeness("ncs_competency", [first])
    validate_completeness("ncs_competency", [first, (input_ref(ordinal=1), first[1])])


def test_job_completeness_requires_corresponding_details() -> None:
    index = (input_ref("index"), page_meta(total=1, identities=["123:list"]))
    with pytest.raises(ProcessingError, match="LIST_DETAIL_IDENTITY_MISMATCH"):
        validate_completeness("job_alio", [index])
    validate_completeness(
        "job_alio", [index, (input_ref("detail-123", None), page_meta(identities=["123:detail"]))]
    )


def test_raw_integrity_checked_even_when_document_is_cached(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_bytes(b"abc")
    ref = input_ref().model_copy(
        update={"raw_object_path": "file", "content_sha256": hashlib.sha256(b"abc").hexdigest()}
    )
    assert read_raw(tmp_path, ref) == b"abc"
    file.write_bytes(b"xyz")
    with pytest.raises(ProcessingError, match="RAW_INTEGRITY_FAILED"):
        read_raw(tmp_path, ref)
    with pytest.raises(ProcessingError, match="RAW_PATH_ESCAPE"):
        read_raw(tmp_path, ref.model_copy(update={"raw_object_path": "../outside"}))


def test_schedule_and_due_decisions() -> None:
    schedule = read_schedule(Path("config/pipeline.yaml"))
    intervals = {s.source_id: s.interval_seconds for s in schedule.sources}
    assert intervals["job_alio"] == 86400
    assert intervals["ncs_competency"] == 7 * 86400
    now = datetime(2026, 9, 6, tzinfo=UTC)
    future = now + timedelta(hours=1)
    assert due(None, now)
    state = {"state": "READY", "next_due_at": future, "configuration_hash": "a"}
    assert not due(state, now, "a")
    assert due(state, now, "b")
    assert not due({**state, "state": "FAILED"}, now, "b")
    assert due({**state, "state": "RUNNING"}, now, "a")
    with pytest.raises(ValidationError):
        Schedule.model_validate(
            {
                "version": 1,
                "retry_seconds": 3600,
                "sources": [{"source_id": "saramin", "interval_seconds": 86400}],
            }
        )


def test_graph_projection_is_staging_and_excludes_raw_free_text() -> None:
    record = normalize("job_alio", posting(aplyQlfcCn="contact@example.org"), "index")
    graph = graph_record("revision", "job_alio", record)
    assert "contact@example.org" not in json.dumps(graph)
    assert {ref["id"] for ref in graph["refs"]} == {
        "alio:organization:C001",
        "job-alio:posting:123",
    }
    assert "source_payload" not in graph
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
