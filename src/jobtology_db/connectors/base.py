from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol, cast

from jobtology_db.contracts.fetch import CompletenessMode, PageMetadata, RequestSpec


class ResponseContractError(ValueError):
    pass


class Connector(Protocol):
    @property
    def source_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def completeness_mode(self) -> CompletenessMode: ...

    @property
    def allowed_hosts(self) -> frozenset[str]: ...

    def initial_requests(self) -> Sequence[RequestSpec]: ...

    def validate_response(
        self, request: RequestSpec, body: bytes, content_type: str
    ) -> PageMetadata: ...

    def remaining_requests(
        self, request: RequestSpec, metadata: PageMetadata, max_pages: int | None
    ) -> Sequence[RequestSpec]: ...


@dataclass(frozen=True, slots=True)
class Pagination:
    page_param: str
    size_param: str
    page_base: int
    page_size: int
    max_page_number: int | None = None


@dataclass(frozen=True, slots=True)
class DeclaredTotalConnector:
    source_id: str
    display_name: str
    endpoint: str
    allowed_hosts: frozenset[str]
    partitions: tuple[tuple[str, dict[str, str]], ...]
    secret_param_names: frozenset[str]
    pagination: Pagination
    completeness_mode: CompletenessMode = CompletenessMode.DECLARED_TOTAL

    def initial_requests(self) -> Sequence[RequestSpec]:
        return tuple(
            self._request(partition_id, params, self.pagination.page_base)
            for partition_id, params in self.partitions
        )

    def _request(
        self, partition_id: str, base_params: dict[str, str], page_number: int
    ) -> RequestSpec:
        params = dict(base_params)
        params[self.pagination.page_param] = str(page_number)
        params[self.pagination.size_param] = str(self.pagination.page_size)
        return RequestSpec(
            source_id=self.source_id,
            partition_id=partition_id,
            method="GET",
            url=self.endpoint,
            params=params,
            secret_param_names=self.secret_param_names,
            page_number=page_number,
        )

    def validate_response(
        self, request: RequestSpec, body: bytes, content_type: str
    ) -> PageMetadata:
        document = parse_response_document(body, content_type)
        validate_api_result(document)
        total = extract_first_int(document, ("totalCount", "total", "scn_cnt"))
        if total is None or total < 0:
            raise ResponseContractError("Response does not contain a valid declared total")
        page = extract_first_int(document, ("pageNo", "pageNum", "start"))
        size = extract_first_int(document, ("numOfRows", "pageSize", "count"))
        if page is not None and request.page_number is not None and page != request.page_number:
            raise ResponseContractError(
                f"Response page {page} does not match requested page {request.page_number}"
            )
        return PageMetadata(
            total_count=total,
            page_number=request.page_number if page is None else page,
            page_size=self.pagination.page_size if size is None else size,
        )

    def remaining_requests(
        self, request: RequestSpec, metadata: PageMetadata, max_pages: int | None
    ) -> Sequence[RequestSpec]:
        if request.page_number != self.pagination.page_base:
            return ()
        if metadata.total_count is None:
            raise ResponseContractError("Cannot paginate without total_count")
        if metadata.total_count == 0:
            if request.response_ordinal == 0:
                return (replace(request, response_ordinal=1),)
            return ()
        if metadata.page_size is None or metadata.page_size < 1:
            raise ResponseContractError("Response does not contain a valid page size")
        pages = max(1, math.ceil(metadata.total_count / metadata.page_size))
        if max_pages is not None:
            pages = min(pages, max_pages)
        final_page = self.pagination.page_base + pages - 1
        if (
            self.pagination.max_page_number is not None
            and final_page > self.pagination.max_page_number
        ):
            raise ResponseContractError(
                "Declared total exceeds the provider pagination ceiling; split the partition"
            )
        base_params = {
            key: value
            for key, value in request.params.items()
            if key not in {self.pagination.page_param, self.pagination.size_param}
        }
        return tuple(
            self._request(request.partition_id, base_params, page)
            for page in range(self.pagination.page_base + 1, self.pagination.page_base + pages)
        )


@dataclass(frozen=True, slots=True)
class SingleFileConnector:
    source_id: str
    display_name: str
    endpoint: str
    allowed_hosts: frozenset[str]
    completeness_mode: CompletenessMode = CompletenessMode.SINGLE_FILE

    def initial_requests(self) -> Sequence[RequestSpec]:
        return (
            RequestSpec(
                source_id=self.source_id,
                partition_id="file",
                method="GET",
                url=self.endpoint,
                params={},
            ),
        )

    def validate_response(
        self, request: RequestSpec, body: bytes, content_type: str
    ) -> PageMetadata:
        del request
        if not body:
            raise ResponseContractError("Downloaded file is empty")
        lowered = content_type.casefold()
        if "text/html" in lowered:
            raise ResponseContractError("Expected a data file but received HTML")
        return PageMetadata(total_count=1, page_number=None, page_size=None)

    def remaining_requests(
        self, request: RequestSpec, metadata: PageMetadata, max_pages: int | None
    ) -> Sequence[RequestSpec]:
        del request, metadata, max_pages
        return ()


def parse_response_document(body: bytes, content_type: str) -> object:
    stripped = body.lstrip()
    if "json" in content_type.casefold() or stripped.startswith((b"{", b"[")):
        try:
            return cast(object, json.loads(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResponseContractError("Invalid JSON response") from error
    try:
        return ET.fromstring(body)
    except ET.ParseError as error:
        raise ResponseContractError("Response is neither valid JSON nor XML") from error


def validate_api_result(document: object) -> None:
    result_codes = list(find_values(document, {"resultCode"}))
    for code in result_codes:
        if str(code).strip() not in {"00", "0", "SUCCESS"}:
            raise ResponseContractError(f"Provider returned resultCode={code!s}")

    mapping = cast(dict[object, object], document) if isinstance(document, dict) else {}
    if "code" in mapping and not any(key in mapping for key in ("jobs", "response", "HRDNet")):
        code = str(mapping["code"]).strip()
        if code not in {"00", "0", "SUCCESS"}:
            raise ResponseContractError(f"Provider returned code={code}")


def extract_first_int(document: object, names: Iterable[str]) -> int | None:
    for name in names:
        for value in find_values(document, {name}):
            try:
                return int(str(value).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
    return None


def find_values(document: object, names: set[str]) -> Iterable[object]:
    if isinstance(document, dict):
        mapping = cast(dict[object, object], document)
        for key, value in mapping.items():
            if key in names:
                yield value
            yield from find_values(value, names)
    elif isinstance(document, list):
        values = cast(list[object], document)
        for value in values:
            yield from find_values(value, names)
    elif isinstance(document, ET.Element):
        for element in document.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag in names and element.text is not None:
                yield element.text
