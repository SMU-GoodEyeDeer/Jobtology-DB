from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from jobtology_db.connectors.base import (
    DEFAULT_API_SUCCESS_CODES,
    Connector,
    DeclaredTotalConnector,
    Pagination,
    ResponseContractError,
    SingleFileConnector,
    extract_first_int,
    find_values,
    parse_response_document,
    validate_api_result,
)
from jobtology_db.contracts.fetch import (
    CompletenessMode,
    PageMetadata,
    RequestSpec,
    SourceReadiness,
)
from jobtology_db.rights import (
    ContentKind,
    RightsRegistryLoadError,
    SourceActivationCheck,
    load_source_rights_registry,
)
from jobtology_db.settings import Settings

SOURCE_IDS = (
    "ncs_competency",
    "ncs_qualification",
    "qnet_schedule",
    "ncs_career_path",
    "job_alio",
    "alio_organization",
    "saramin",
    "work24_training",
)

NCS_UNIT_CODE_PATTERN = re.compile(r"^\d{10}_\d{2}v\d+$")
QNET_ITEM_CODE_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
WORK24_MVP_COURSE_TYPES = frozenset({"C0061", "C0104", "C0105"})
ALIO_API_SUCCESS_CODES = DEFAULT_API_SUCCESS_CODES | {"200"}
SOURCE_REQUIRED_CONTENT: dict[str, tuple[ContentKind, ...]] = {
    "ncs_competency": ("api_json_body",),
    "ncs_qualification": ("api_json_body",),
    "qnet_schedule": ("api_json_body",),
    "ncs_career_path": ("file_body",),
    "job_alio": ("api_json_body", "attachment_metadata"),
    "alio_organization": ("api_json_body",),
    "saramin": ("api_json_body",),
    "work24_training": ("api_json_body",),
}


class SourceConfigurationError(ValueError):
    pass


def readiness(source_id: str, settings: Settings) -> tuple[SourceReadiness, str]:
    if source_id not in SOURCE_IDS:
        raise SourceConfigurationError(f"Unknown source: {source_id}")

    try:
        rights = source_activation_check(source_id, settings)
    except RightsRegistryLoadError:
        return SourceReadiness.NEEDS_CONFIGURATION, "JOBTOLOGY_SOURCE_RIGHTS_FILE"
    if not rights.allowed:
        return (
            SourceReadiness.NEEDS_CONFIGURATION,
            f"RIGHTS_BLOCKED ({rights.registry_revision})",
        )

    if source_id in {
        "ncs_competency",
        "ncs_qualification",
        "qnet_schedule",
        "job_alio",
        "alio_organization",
    }:
        if not settings.data_go_key():
            return SourceReadiness.NEEDS_CREDENTIAL, "DATA_GO_KR_SERVICE_KEY"
        if source_id == "ncs_qualification" and not _has_valid_ncs_unit_codes(
            settings.NCS_QUALIFICATION_CODES_FILE
        ):
            return SourceReadiness.NEEDS_CONFIGURATION, "NCS_QUALIFICATION_CODES_FILE"
        if source_id == "qnet_schedule" and not _has_valid_qnet_item_codes(
            settings.QNET_ITEM_CODES_FILE
        ):
            return SourceReadiness.NEEDS_CONFIGURATION, "QNET_ITEM_CODES_FILE"
        if source_id == "qnet_schedule" and not _has_valid_qnet_years(settings.QNET_YEARS):
            return SourceReadiness.NEEDS_CONFIGURATION, "QNET_YEARS"
        return SourceReadiness.READY, "ready"
    if source_id == "saramin":
        if not settings.secret_value(settings.SARAMIN_ACCESS_KEY):
            return SourceReadiness.NEEDS_CREDENTIAL, "SARAMIN_ACCESS_KEY"
        if not settings.csv(settings.SARAMIN_KEYWORDS):
            return SourceReadiness.NEEDS_CONFIGURATION, "SARAMIN_KEYWORDS"
        return SourceReadiness.READY, "ready"
    if source_id == "work24_training":
        if not settings.secret_value(settings.WORK24_AUTH_KEY):
            return SourceReadiness.NEEDS_CREDENTIAL, "WORK24_AUTH_KEY"
        if not _has_valid_work24_course_types(settings.WORK24_COURSE_TYPES):
            return SourceReadiness.NEEDS_CONFIGURATION, "WORK24_COURSE_TYPES"
        date_issue = _work24_date_window_issue(settings.WORK24_START_DATE, settings.WORK24_END_DATE)
        if date_issue is not None:
            return SourceReadiness.NEEDS_CONFIGURATION, date_issue
        return SourceReadiness.READY, "ready"
    if source_id == "ncs_career_path":
        if not settings.NCS_CAREER_PATH_DOWNLOAD_URL:
            return SourceReadiness.NEEDS_CONFIGURATION, "NCS_CAREER_PATH_DOWNLOAD_URL"
        if urlsplit(settings.NCS_CAREER_PATH_DOWNLOAD_URL).hostname != "www.data.go.kr":
            return (
                SourceReadiness.NEEDS_CONFIGURATION,
                "NCS_CAREER_PATH_DOWNLOAD_URL must use the official www.data.go.kr host",
            )
        return SourceReadiness.READY, "ready"
    raise AssertionError(f"Readiness is not implemented for known source: {source_id}")


def source_activation_check(source_id: str, settings: Settings) -> SourceActivationCheck:
    """Load and evaluate the exact rights policy required by a connector."""

    registry = load_source_rights_registry(settings.JOBTOLOGY_SOURCE_RIGHTS_FILE)
    return registry.check_activation(
        source_id,
        required_content=SOURCE_REQUIRED_CONTENT[source_id],
    )


def build_connector(source_id: str, settings: Settings) -> Connector:
    status, detail = readiness(source_id, settings)
    if status is not SourceReadiness.READY:
        raise SourceConfigurationError(f"{source_id} is not ready: {status.value} ({detail})")

    if source_id == "ncs_competency":
        key = _required(settings.data_go_key(), "DATA_GO_KR_SERVICE_KEY")
        return DeclaredTotalConnector(
            source_id=source_id,
            display_name="HRDKorea NCS competency API",
            endpoint="https://c.q-net.or.kr/openapi/Ncs1info/ncsinfo.do",
            allowed_hosts=frozenset({"c.q-net.or.kr"}),
            # CQ-Net's live endpoint treats this parameter name as case-sensitive.
            # Despite the public catalog displaying ``ServiceKey``, only the lowercase
            # spelling is accepted by the provider as of 2026-09-06.
            partitions=(("all", {"serviceKey": key, "type": "json"}),),
            secret_param_names=frozenset({"serviceKey"}),
            pagination=Pagination("pageNo", "numOfRows", 1, 1000),
        )

    if source_id == "ncs_qualification":
        key = _required(settings.data_go_key(), "DATA_GO_KR_SERVICE_KEY")
        codes_file = settings.NCS_QUALIFICATION_CODES_FILE
        if codes_file is None:
            raise SourceConfigurationError("NCS_QUALIFICATION_CODES_FILE is required")
        codes = _read_ncs_unit_codes(codes_file)
        partitions = tuple(
            (
                f"ncs-{code}",
                {"serviceKey": key, "dataFormat": "json", "ncsClCd": code},
            )
            for code in codes
        )
        return DeclaredTotalConnector(
            source_id=source_id,
            display_name="NCS competency-to-qualification API",
            endpoint="https://apis.data.go.kr/B490007/ncsClCdJm/getNcsClCdJmList",
            allowed_hosts=frozenset({"apis.data.go.kr"}),
            partitions=partitions,
            secret_param_names=frozenset({"serviceKey"}),
            # The live HRDKorea endpoint rejects page sizes above 50 with
            # resultCode=930, even though the portal metadata does not expose
            # that ceiling in the request-variable table.
            pagination=Pagination("pageNo", "numOfRows", 1, 50),
        )

    if source_id == "qnet_schedule":
        key = _required(settings.data_go_key(), "DATA_GO_KR_SERVICE_KEY")
        years = settings.csv(settings.QNET_YEARS)
        if not _has_valid_qnet_years(settings.QNET_YEARS):
            raise SourceConfigurationError("QNET_YEARS must be comma-separated four-digit years")
        item_codes_file = settings.QNET_ITEM_CODES_FILE
        if item_codes_file is None:
            raise SourceConfigurationError("QNET_ITEM_CODES_FILE is required")
        item_codes = _read_qnet_item_codes(item_codes_file)
        return DeclaredTotalConnector(
            source_id=source_id,
            display_name="Q-Net qualification schedule API",
            endpoint="https://apis.data.go.kr/B490007/qualExamSchd/getQualExamSchdList",
            allowed_hosts=frozenset({"apis.data.go.kr"}),
            partitions=tuple(
                (
                    f"year-{year}-item-{item_code}",
                    {
                        "serviceKey": key,
                        "dataFormat": "json",
                        "implYy": year,
                        "jmCd": item_code,
                    },
                )
                for year in years
                for item_code in item_codes
            ),
            secret_param_names=frozenset({"serviceKey"}),
            # This sibling HRDKorea endpoint enforces the same live 50-row cap.
            pagination=Pagination("pageNo", "numOfRows", 1, 50),
        )

    if source_id == "job_alio":
        key = _required(settings.data_go_key(), "DATA_GO_KR_SERVICE_KEY")
        return JobAlioConnector(
            service_key=key,
            ongoing_only=settings.JOB_ALIO_ONGOING_ONLY,
        )

    if source_id == "alio_organization":
        key = _required(settings.data_go_key(), "DATA_GO_KR_SERVICE_KEY")
        return DeclaredTotalConnector(
            source_id=source_id,
            display_name="ALIO public-institution API",
            endpoint="https://apis.data.go.kr/1051000/public_inst/list",
            allowed_hosts=frozenset({"apis.data.go.kr"}),
            partitions=(("institutions", {"serviceKey": key, "resultType": "json"}),),
            secret_param_names=frozenset({"serviceKey"}),
            pagination=Pagination("pageNo", "numOfRows", 1, 100),
            accepted_success_codes=ALIO_API_SUCCESS_CODES,
        )

    if source_id == "saramin":
        key = _required(settings.secret_value(settings.SARAMIN_ACCESS_KEY), "SARAMIN_ACCESS_KEY")
        keywords = settings.csv(settings.SARAMIN_KEYWORDS)
        return DeclaredTotalConnector(
            source_id=source_id,
            display_name="Saramin Job Search API",
            endpoint="https://oapi.saramin.co.kr/job-search",
            allowed_hosts=frozenset({"oapi.saramin.co.kr"}),
            partitions=tuple(
                (
                    f"keyword-{index}",
                    {
                        "access-key": key,
                        "keywords": keyword,
                        "fields": "posting-date expiration-date keyword-code",
                        "sort": "ud",
                    },
                )
                for index, keyword in enumerate(keywords, start=1)
            ),
            secret_param_names=frozenset({"access-key"}),
            pagination=Pagination("start", "count", 0, 110),
        )

    if source_id == "work24_training":
        key = _required(settings.secret_value(settings.WORK24_AUTH_KEY), "WORK24_AUTH_KEY")
        _validate_compact_date(settings.WORK24_START_DATE, "WORK24_START_DATE")
        _validate_compact_date(settings.WORK24_END_DATE, "WORK24_END_DATE")
        if settings.WORK24_START_DATE > settings.WORK24_END_DATE:
            raise SourceConfigurationError("WORK24_START_DATE cannot be after WORK24_END_DATE")
        course_types = _work24_course_types(settings.WORK24_COURSE_TYPES)
        return DeclaredTotalConnector(
            source_id=source_id,
            display_name="Work24 training API",
            endpoint="https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do",
            allowed_hosts=frozenset({"www.work24.go.kr"}),
            partitions=tuple(
                (
                    f"course-type-{course_type}",
                    {
                        "authKey": key,
                        "returnType": "JSON",
                        "outType": "1",
                        "srchTraStDt": settings.WORK24_START_DATE,
                        "srchTraEndDt": settings.WORK24_END_DATE,
                        "srchNcs1": settings.WORK24_NCS1,
                        "crseTracseSe": course_type,
                        "sort": "ASC",
                        "sortCol": "2",
                    },
                )
                for course_type in course_types
            ),
            secret_param_names=frozenset({"authKey"}),
            pagination=Pagination("pageNum", "pageSize", 1, 100, max_page_number=1000),
        )

    if source_id == "ncs_career_path":
        return _single_file(
            source_id,
            "NCS career-path file",
            _required(settings.NCS_CAREER_PATH_DOWNLOAD_URL, "NCS_CAREER_PATH_DOWNLOAD_URL"),
        )

    raise SourceConfigurationError(f"Connector not implemented: {source_id}")


class JobAlioConnector:
    """Enumerate active JOB-ALIO postings, then fetch every posting detail."""

    source_id = "job_alio"
    display_name = "JOB-ALIO recruitment API"
    allowed_hosts = frozenset({"apis.data.go.kr"})
    secret_param_names = frozenset({"serviceKey"})
    completeness_mode = CompletenessMode.DECLARED_TOTAL

    def __init__(self, service_key: str, ongoing_only: bool = True) -> None:
        self.service_key = service_key
        self.ongoing_only = ongoing_only
        self._pagination = Pagination("pageNo", "numOfRows", 1, 100)

    def initial_requests(self) -> tuple[RequestSpec, ...]:
        params = {"serviceKey": self.service_key, "resultType": "json"}
        if self.ongoing_only:
            params["ongoingYn"] = "Y"
        return (self._index_request(params, 1),)

    def validate_response(
        self, request: RequestSpec, body: bytes, content_type: str
    ) -> PageMetadata:
        document = parse_response_document(body, content_type)
        validate_api_result(document, accepted_success_codes=ALIO_API_SUCCESS_CODES)
        if request.partition_id.startswith("detail-"):
            expected_identity = request.params.get("sn", "").strip()
            identities = {
                str(value).strip()
                for value in find_values(document, {"recrutPblntSn"})
                if str(value).strip()
            }
            if not expected_identity or identities != {expected_identity}:
                raise ResponseContractError(
                    "JOB-ALIO detail identity does not match the requested posting"
                )
            return PageMetadata(total_count=1, page_number=None, page_size=None)

        total = extract_first_int(document, ("totalCount",))
        if total is None or total < 0:
            raise ResponseContractError("JOB-ALIO index response has no valid totalCount")
        page = extract_first_int(document, ("pageNo",))
        if page is not None and page != request.page_number:
            raise ResponseContractError(
                f"JOB-ALIO response page {page} does not match request {request.page_number}"
            )
        identities = tuple(
            sorted(
                {
                    str(value).strip()
                    for value in find_values(document, {"recrutPblntSn"})
                    if str(value).strip()
                }
            )
        )
        if total > 0 and not identities:
            raise ResponseContractError("JOB-ALIO index page contains no posting identities")
        return PageMetadata(
            total_count=total,
            page_number=request.page_number,
            page_size=self._pagination.page_size,
            discovered_record_ids=identities,
        )

    def remaining_requests(
        self, request: RequestSpec, metadata: PageMetadata, max_pages: int | None
    ) -> tuple[RequestSpec, ...]:
        if request.partition_id.startswith("detail-"):
            return ()
        if metadata.total_count == 0:
            if request.response_ordinal == 0:
                return (replace(request, response_ordinal=1),)
            return ()

        requests: list[RequestSpec] = []
        if request.page_number == self._pagination.page_base:
            total = metadata.total_count or 0
            pages = max(1, (total + self._pagination.page_size - 1) // self._pagination.page_size)
            if max_pages is not None:
                pages = min(pages, max_pages)
            base_params = {
                key: value
                for key, value in request.params.items()
                if key not in {self._pagination.page_param, self._pagination.size_param}
            }
            requests.extend(
                self._index_request(base_params, page)
                for page in range(
                    self._pagination.page_base + 1, self._pagination.page_base + pages
                )
            )

        requests.extend(
            self._detail_request(identity) for identity in metadata.discovered_record_ids
        )
        return tuple(requests)

    def _index_request(self, base_params: dict[str, str], page_number: int) -> RequestSpec:
        params = dict(base_params)
        params.update({"pageNo": str(page_number), "numOfRows": "100"})
        return RequestSpec(
            source_id=self.source_id,
            partition_id="index",
            method="GET",
            url="https://apis.data.go.kr/1051000/recruitment/list",
            params=params,
            secret_param_names=self.secret_param_names,
            page_number=page_number,
        )

    def _detail_request(self, identity: str) -> RequestSpec:
        return RequestSpec(
            source_id=self.source_id,
            partition_id=f"detail-{identity}",
            method="GET",
            url="https://apis.data.go.kr/1051000/recruitment/detail",
            params={
                "serviceKey": self.service_key,
                "resultType": "json",
                "sn": identity,
            },
            secret_param_names=self.secret_param_names,
        )


def _single_file(source_id: str, name: str, endpoint: str) -> SingleFileConnector:
    host = urlsplit(endpoint).hostname
    if source_id == "ncs_career_path" and host != "www.data.go.kr":
        raise SourceConfigurationError(
            "NCS_CAREER_PATH_DOWNLOAD_URL must use the official www.data.go.kr host"
        )
    if host is None:
        raise SourceConfigurationError(f"Invalid download URL for {source_id}")
    return SingleFileConnector(
        source_id=source_id,
        display_name=name,
        endpoint=endpoint,
        allowed_hosts=frozenset({host}),
    )


def _required(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise SourceConfigurationError(f"{name} is required")
    return value.strip()


def _has_valid_ncs_unit_codes(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    codes = _read_lines(path)
    return bool(codes) and all(NCS_UNIT_CODE_PATTERN.fullmatch(code) for code in codes)


def _read_ncs_unit_codes(path: Path) -> tuple[str, ...]:
    codes = tuple(dict.fromkeys(_read_lines(path)))
    if not codes or any(NCS_UNIT_CODE_PATTERN.fullmatch(code) is None for code in codes):
        raise SourceConfigurationError(
            "NCS_QUALIFICATION_CODES_FILE must contain full versioned NCS competency-unit "
            "codes such as 1501020207_14v2"
        )
    return codes


def _has_valid_qnet_item_codes(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    codes = [code.upper() for code in _read_lines(path)]
    return bool(codes) and all(QNET_ITEM_CODE_PATTERN.fullmatch(code) for code in codes)


def _read_qnet_item_codes(path: Path) -> tuple[str, ...]:
    codes = tuple(dict.fromkeys(code.upper() for code in _read_lines(path)))
    if not codes or any(QNET_ITEM_CODE_PATTERN.fullmatch(code) is None for code in codes):
        raise SourceConfigurationError(
            "QNET_ITEM_CODES_FILE must contain one four-character qualification item code per line"
        )
    return codes


def _has_valid_work24_course_types(value: str) -> bool:
    configured = Settings.csv(value)
    return bool(configured) and all(code in WORK24_MVP_COURSE_TYPES for code in configured)


def _has_valid_qnet_years(value: str) -> bool:
    years = Settings.csv(value)
    return bool(years) and all(len(year) == 4 and year.isdigit() for year in years)


def _work24_date_window_issue(start: str, end: str) -> str | None:
    try:
        _validate_compact_date(start, "WORK24_START_DATE")
    except SourceConfigurationError as error:
        return str(error)
    try:
        _validate_compact_date(end, "WORK24_END_DATE")
    except SourceConfigurationError as error:
        return str(error)
    if start > end:
        return "WORK24_START_DATE cannot be after WORK24_END_DATE"
    return None


def _work24_course_types(value: str) -> tuple[str, ...]:
    configured = tuple(dict.fromkeys(Settings.csv(value)))
    if not configured or any(code not in WORK24_MVP_COURSE_TYPES for code in configured):
        supported = ",".join(sorted(WORK24_MVP_COURSE_TYPES))
        raise SourceConfigurationError(f"WORK24_COURSE_TYPES must use only: {supported}")
    return configured


def _read_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _validate_compact_date(value: str, name: str) -> None:
    if len(value) != 8 or not value.isdigit():
        raise SourceConfigurationError(f"{name} must use YYYYMMDD")
    try:
        date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except (ValueError, IndexError) as error:
        raise SourceConfigurationError(f"{name} must use YYYYMMDD") from error
