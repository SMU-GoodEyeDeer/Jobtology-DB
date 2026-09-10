from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date
from typing import cast

from pydantic import JsonValue, ValidationError

from jobtology_db.contracts.processing import (
    CareerPath,
    Competency,
    ExamSession,
    JobPosting,
    LocatedRecord,
    Organization,
    ParsedDocument,
    QualificationMapping,
    Record,
    RejectedRow,
    TextArtifact,
    digest,
)


class ProcessingError(ValueError):
    """Safe error code; never include raw provider text or credentials."""


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def pointer(key: str) -> str:
    return "/" + key.replace("~", "~0").replace("/", "~1")


def mapping(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ProcessingError("EXPECTED_OBJECT")
    return cast(dict[str, JsonValue], value)


def integer(value: object) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ProcessingError("INVALID_NONNEGATIVE_INTEGER")
    return int(str(value))


class Fields:
    def __init__(self, row: dict[str, JsonValue]) -> None:
        self.row = row
        self.lineage: dict[str, list[str]] = {}

    def get(self, target: str, source: str) -> JsonValue:
        self.lineage[target] = [pointer(source)]
        return self.row.get(source)

    def string(self, target: str, source: str, *, required: bool = False) -> str | None:
        value = self.get(target, source)
        if value is None or value == "":
            if required:
                raise ProcessingError("MISSING_REQUIRED_FIELD")
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ProcessingError("INVALID_STRING")
        result = normalized_text(str(value)).strip()
        if required and not result:
            raise ProcessingError("MISSING_REQUIRED_FIELD")
        return result or None

    def required(self, target: str, source: str) -> str:
        return cast(str, self.string(target, source, required=True))

    def number(self, target: str, source: str) -> int | None:
        value = self.get(target, source)
        return None if value in (None, "") else integer(value)

    def day(self, target: str, source: str) -> date | None:
        value = self.string(target, source)
        if value is None:
            return None
        if not re.fullmatch(r"\d{8}", value):
            raise ProcessingError("INVALID_DATE")
        try:
            return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except ValueError as error:
            raise ProcessingError("INVALID_DATE") from error


def normalize(source_id: str, row: dict[str, JsonValue], partition: str) -> Record:
    f = Fields(row)
    flags: list[str] = []
    identity: str
    if source_id == "ncs_career_path":
        code_fields = ["대분류코드", "중분류코드", "소분류코드", "직무코드"]
        parts = [str(integer(row.get(key))).zfill(2) for key in code_fields]
        if any(len(part) != 2 for part in parts):
            raise ProcessingError("INVALID_NCS_CODE")
        code = "".join(parts)
        f.lineage["occupation_code"] = [pointer(key) for key in code_fields]
        f.lineage["competency_code"] = [*f.lineage["occupation_code"], pointer("직무역량코드")]
        unit = str(integer(row.get("직무역량코드"))).zfill(2)
        if len(unit) != 2:
            raise ProcessingError("INVALID_NCS_CODE")
        normalized = CareerPath(
            occupation_code=code,
            occupation_name=f.required("occupation_name", "직무명"),
            competency_code=code + unit,
            competency_name=f.required("competency_name", "직무역량명"),
            competency_level=integer(
                f.get("competency_level", "직무역량수준(능력단위수준 이면서 세분류의 자식)")
            ),
            rank_level=integer(f.get("rank_level", "수준(직급수준)")),
            rank_name=f.required("rank_name", "직급명"),
        )
        identity = digest(normalized.model_dump(mode="json"))
    elif source_id == "ncs_competency":
        code = f.required("code", "ncsClCd")
        if not re.fullmatch(r"\d{10}_\d{2}v\d+", code):
            raise ProcessingError("INVALID_NCS_CODE")
        f.lineage["occupation_code"] = ["/ncsClCd"]
        names = ["ncsLclasCdnm", "ncsMclasCdnm", "ncsSclasCdnm"]
        f.lineage["classification_names"] = [pointer(name) for name in names]
        level = integer(f.get("level", "compeUnitLevel"))
        if level == 0:
            flags.append("UNSPECIFIED_COMPETENCY_LEVEL")
        normalized = Competency(
            code=code,
            name=f.required("name", "compeUnitName"),
            definition=f.string("definition", "compeUnitDef"),
            level=level or None,
            occupation_code=code[:8],
            occupation_name=f.required("occupation_name", "ncsSubdCdnm"),
            classification_names=[str(row.get(name) or "") for name in names],
        )
        identity = code
    elif source_id == "ncs_qualification":
        code = f.required("competency_code", "ncsClCd")
        if partition != f"ncs-{code}" or not re.fullmatch(r"\d{10}_\d{2}v\d+", code):
            raise ProcessingError("PARTITION_IDENTITY_MISMATCH")
        normalized = QualificationMapping(
            competency_code=code,
            qualification_code=f.required("qualification_code", "jmCd"),
            qualification_name=f.required("qualification_name", "jmNm"),
            standard_version=f.required("standard_version", "organStdVerCd"),
            unit_type=f.required("unit_type", "abltUnitTypCd"),
            minimum_training_hours=f.number("minimum_training_hours", "minEduTrngTm"),
            total_training_hours=f.number("total_training_hours", "eduTrngStdTmSum"),
            examining_organization=f.string("examining_organization", "examInstiNm"),
        )
        identity = ":".join([code, normalized.qualification_code, normalized.standard_version])
    elif source_id == "qnet_schedule":
        match = re.fullmatch(r"year-(\d{4})-item-([A-Z0-9]{4})", partition)
        if match is None or str(row.get("implYy")) != match[1]:
            raise ProcessingError("PARTITION_IDENTITY_MISMATCH")
        if row.get("jmCd") not in (None, "", match[2]):
            raise ProcessingError("PARTITION_IDENTITY_MISMATCH")
        f.lineage["qualification_code"] = ["request:partition_id"]
        date_fields = [
            "docRegStartDt",
            "docRegEndDt",
            "docExamStartDt",
            "docExamEndDt",
            "docPassDt",
            "pracRegStartDt",
            "pracRegEndDt",
            "pracExamStartDt",
            "pracExamEndDt",
            "pracPassDt",
        ]
        dates = {key: f.day(f"dates.{key}", key) for key in date_fields}
        for start, end in zip(
            date_fields[0:4:2] + date_fields[5:9:2],
            date_fields[1:5:2] + date_fields[6:10:2],
            strict=True,
        ):
            start_date, end_date = dates[start], dates[end]
            if start_date is not None and end_date is not None and start_date > end_date:
                raise ProcessingError("REVERSED_DATE_RANGE")
        normalized = ExamSession(
            qualification_code=match[2],
            year=integer(f.get("year", "implYy")),
            round=integer(f.get("round", "implSeq")),
            category_code=f.required("category_code", "qualgbCd"),
            name=f.required("name", "description"),
            dates=dates,
        )
        identity = f"{match[2]}:{normalized.year}:{normalized.category_code}:{normalized.round}"
    elif source_id == "alio_organization":
        normalized = Organization(
            code=f.required("code", "instCd"),
            name=f.required("name", "instNm"),
            government_code=f.string("government_code", "pbadmsStdInstCd"),
            organization_type=f.string("organization_type", "instTypeNm"),
            supervising_organization_code=f.string("supervising_organization_code", "sprvsnInstCd"),
            website=f.string("website", "siteUrl"),
            address=f.string("address", "roadNmAddr"),
            established_date=f.day("established_date", "fndnYmd"),
        )
        identity = normalized.code
    elif source_id == "job_alio":
        identity = f.required("posting_id", "recrutPblntSn")
        representation = "detail" if partition.startswith("detail-") else "list"
        if representation == "detail" and partition != f"detail-{identity}":
            raise ProcessingError("PARTITION_IDENTITY_MISMATCH")
        f.lineage["representation"] = ["request:partition_id"]
        ongoing = f.get("ongoing", "ongoingYn")
        if ongoing not in ("Y", "N", None, ""):
            raise ProcessingError("INVALID_ONGOING_STATUS")
        posted, closing = f.day("date_posted", "pbancBgngYmd"), f.day("closing_date", "pbancEndYmd")
        if posted is None or closing is None or closing < posted:
            raise ProcessingError("INVALID_POSTING_DATE_RANGE")
        normalized = JobPosting(
            posting_id=identity,
            representation=representation,
            title=f.required("title", "recrutPbancTtl"),
            organization_code=f.required("organization_code", "pblntInstCd"),
            organization_name=f.required("organization_name", "instNm"),
            date_posted=posted,
            closing_date=closing,
            ongoing=None if ongoing in (None, "") else ongoing == "Y",
            source_url=f.string("source_url", "srcUrl"),
            recruitment_type=f.string("recruitment_type", "recrutSeNm"),
            education=f.string("education", "acbgCondNmLst"),
            employment_type=f.string("employment_type", "hireTypeNmLst"),
            regions=f.string("regions", "workRgnNmLst"),
            ncs_category_codes=f.string("ncs_category_codes", "ncsCdLst"),
            ncs_category_names=f.string("ncs_category_names", "ncsCdNmLst"),
            headcount=f.number("headcount", "recrutNope"),
            eligibility_text=f.string("eligibility_text", "aplyQlfcCn"),
            disqualification_text=f.string("disqualification_text", "disqlfcRsn"),
            preference_text=f.string("preference_text", "prefCn"),
            selection_text=f.string("selection_text", "scrnprcdrMthdExpln"),
        )
        identity = f"{identity}:{representation}"
    else:
        raise ProcessingError("UNSUPPORTED_SOURCE")
    texts: dict[str, TextArtifact] = {}
    for key, value in row.items():
        if isinstance(value, str) and value:
            text_value = normalized_text(value)
            texts[pointer(key)] = TextArtifact(
                text=text_value,
                sha256=hashlib.sha256(text_value.encode()).hexdigest(),
            )
    return Record(
        source_record_id=identity,
        source_payload=row,
        normalized=normalized,
        field_lineage=f.lineage,
        texts=texts,
        quality_flags=flags,
    )


def parse_document(source_id: str, body: bytes, partition: str, page: int | None) -> ParsedDocument:
    encoding = "utf-8"
    total = size = response_page = None
    if source_id == "ncs_career_path":
        try:
            decoded = body.decode("utf-8-sig")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            decoded, encoding = body.decode("cp949"), "cp949"
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ProcessingError("INVALID_CSV_HEADER")
        required = {
            "대분류코드",
            "중분류코드",
            "소분류코드",
            "직무코드",
            "직무명",
            "직무역량코드",
            "직무역량명",
            "직무역량수준(능력단위수준 이면서 세분류의 자식)",
            "수준(직급수준)",
            "직급명",
        }
        if not required.issubset(reader.fieldnames):
            raise ProcessingError("MISSING_CSV_COLUMNS")
        rows: list[tuple[str, JsonValue]] = []
        for number, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise ProcessingError("INVALID_CSV_ROW_WIDTH")
            rows.append((f"csv:record:{number}", cast(JsonValue, row)))
        if not rows:
            raise ProcessingError("EMPTY_CSV")
    else:
        try:
            document = mapping(json.loads(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProcessingError("INVALID_JSON") from error
        if source_id == "ncs_competency":
            root = mapping(document.get("root"))
            meta, items, prefix = mapping(root.get("info")), root.get("items"), "/root/items"
        elif source_id in {"ncs_qualification", "qnet_schedule"}:
            meta = mapping(document.get("body"))
            items, prefix = meta.get("items"), "/body/items"
        elif source_id in {"job_alio", "alio_organization"}:
            meta, items, prefix = document, document.get("result"), "/result"
            if document.get("resultCode") not in (200, "200"):
                raise ProcessingError("INVALID_PROVIDER_RESULT")
        else:
            raise ProcessingError("UNSUPPORTED_SOURCE")
        detail = source_id == "job_alio" and partition.startswith("detail-")
        if detail:
            rows = [(prefix, mapping(items))]
        else:
            if not isinstance(items, list):
                raise ProcessingError("EXPECTED_ITEM_ARRAY")
            rows = [(f"{prefix}/{i}", item) for i, item in enumerate(items)]
            total = integer(meta.get("totalCount"))
            response_page = integer(meta.get("pageNo", page))
            size = integer(meta.get("numOfRows", 100))
            if response_page != page or size < 1 or response_page < 1:
                raise ProcessingError("INVALID_PAGINATION")
    records: list[LocatedRecord] = []
    rejected: list[RejectedRow] = []
    for locator, raw_row in rows:
        try:
            record = normalize(source_id, mapping(raw_row), partition)
            records.append(LocatedRecord(locator=locator, record=record))
        except (ProcessingError, ValidationError) as error:
            code = str(error) if isinstance(error, ProcessingError) else "RECORD_CONTRACT_INVALID"
            rejected.append(RejectedRow(locator=locator, source_payload=raw_row, error_code=code))
    return ParsedDocument(
        records=records,
        rejected=rejected,
        total=total,
        page=response_page,
        page_size=size,
        row_count=len(rows),
        encoding=encoding,
    )
