from __future__ import annotations

from dataclasses import replace

import pytest

from jobtology_db.connectors.base import (
    DeclaredTotalConnector,
    Pagination,
    ResponseContractError,
    SingleFileConnector,
    extract_first_int,
    parse_response_document,
)


def connector(
    *,
    page_base: int = 1,
    page_size: int = 100,
    max_page_number: int | None = None,
) -> DeclaredTotalConnector:
    return DeclaredTotalConnector(
        source_id="fixture",
        display_name="Fixture source",
        endpoint="https://fixture.example/records",
        allowed_hosts=frozenset({"fixture.example"}),
        partitions=(("all", {"serviceKey": "secret", "type": "json"}),),
        secret_param_names=frozenset({"serviceKey"}),
        pagination=Pagination(
            page_param="pageNo",
            size_param="numOfRows",
            page_base=page_base,
            page_size=page_size,
            max_page_number=max_page_number,
        ),
    )


def test_json_response_validates_and_plans_all_remaining_pages() -> None:
    source = connector(page_size=100)
    initial = source.initial_requests()[0]
    body = (
        b'{"response":{"header":{"resultCode":"00"},"body":'
        b'{"totalCount":250,"pageNo":1,"numOfRows":100}}}'
    )

    metadata = source.validate_response(initial, body, "application/json; charset=utf-8")
    remaining = source.remaining_requests(initial, metadata, max_pages=None)

    assert metadata.total_count == 250
    assert metadata.page_number == 1
    assert metadata.page_size == 100
    assert [request.page_number for request in remaining] == [2, 3]
    assert [request.params["pageNo"] for request in remaining] == ["2", "3"]
    assert all(request.params["serviceKey"] == "secret" for request in remaining)


def test_xml_response_with_namespace_and_comma_total_is_supported() -> None:
    source = connector(page_base=0, page_size=110)
    initial = source.initial_requests()[0]
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
    <response xmlns="urn:fixture">
      <header><resultCode>0</resultCode></header>
      <body><totalCount>1,001</totalCount><pageNo>0</pageNo><numOfRows>110</numOfRows></body>
    </response>
    """

    metadata = source.validate_response(initial, body, "application/xml")
    remaining = source.remaining_requests(initial, metadata, max_pages=None)

    assert metadata.total_count == 1_001
    assert [request.page_number for request in remaining] == list(range(1, 10))


def test_content_sniffing_parses_json_when_content_type_is_generic() -> None:
    document = parse_response_document(b'  {"totalCount": "2"}', "text/plain")

    assert extract_first_int(document, ("totalCount",)) == 2


def test_max_pages_counts_the_initial_page() -> None:
    source = connector(page_size=10)
    initial = source.initial_requests()[0]
    metadata = source.validate_response(
        initial,
        b'{"response":{"body":{"totalCount":999,"pageNo":1,"numOfRows":10}}}',
        "application/json",
    )

    remaining = source.remaining_requests(initial, metadata, max_pages=3)

    assert [request.page_number for request in remaining] == [2, 3]


def test_uncapped_declared_total_above_provider_page_ceiling_is_rejected() -> None:
    source = connector(page_size=10, max_page_number=3)
    initial = source.initial_requests()[0]
    metadata = source.validate_response(
        initial,
        b'{"response":{"body":{"totalCount":31,"pageNo":1,"numOfRows":10}}}',
        "application/json",
    )

    with pytest.raises(ResponseContractError, match="pagination ceiling"):
        source.remaining_requests(initial, metadata, max_pages=None)


def test_bounded_backfill_within_provider_page_ceiling_is_allowed() -> None:
    source = connector(page_size=10, max_page_number=3)
    initial = source.initial_requests()[0]
    metadata = source.validate_response(
        initial,
        b'{"response":{"body":{"totalCount":31,"pageNo":1,"numOfRows":10}}}',
        "application/json",
    )

    remaining = source.remaining_requests(initial, metadata, max_pages=3)

    assert [request.page_number for request in remaining] == [2, 3]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"response":{"header":{"resultCode":"30"},"body":{"totalCount":1}}}', "resultCode"),
        (b'{"resultCode":200,"totalCount":1,"pageNo":1}', "resultCode"),
        (b'{"response":{"body":{"pageNo":1}}}', "declared total"),
        (b"{not-json", "Invalid JSON"),
    ],
)
def test_invalid_json_api_responses_are_rejected(body: bytes, message: str) -> None:
    source = connector()

    with pytest.raises(ResponseContractError, match=message):
        source.validate_response(source.initial_requests()[0], body, "application/json")


def test_page_mismatch_is_rejected() -> None:
    source = connector()
    initial = source.initial_requests()[0]

    with pytest.raises(ResponseContractError, match="does not match requested page"):
        source.validate_response(
            initial,
            b'{"response":{"body":{"totalCount":20,"pageNo":2,"numOfRows":100}}}',
            "application/json",
        )


def test_non_initial_page_does_not_expand_pagination_again() -> None:
    source = connector()
    initial = source.initial_requests()[0]
    second = replace(initial, page_number=2, params={**initial.params, "pageNo": "2"})
    metadata = source.validate_response(
        second,
        b'{"response":{"body":{"totalCount":500,"pageNo":2,"numOfRows":100}}}',
        "application/json",
    )

    assert source.remaining_requests(second, metadata, max_pages=None) == ()


def test_single_file_rejects_empty_or_html_error_body() -> None:
    source = SingleFileConnector(
        source_id="file",
        display_name="Fixture file",
        endpoint="https://fixture.example/export.xlsx",
        allowed_hosts=frozenset({"fixture.example"}),
    )
    request = source.initial_requests()[0]

    with pytest.raises(ResponseContractError, match="empty"):
        source.validate_response(request, b"", "application/octet-stream")
    with pytest.raises(ResponseContractError, match="received HTML"):
        source.validate_response(request, b"<html>error</html>", "text/html")


def test_single_file_accepts_nonempty_non_html_body() -> None:
    source = SingleFileConnector(
        source_id="file",
        display_name="Fixture file",
        endpoint="https://fixture.example/export.xlsx",
        allowed_hosts=frozenset({"fixture.example"}),
    )
    request = source.initial_requests()[0]

    metadata = source.validate_response(
        request,
        b"PK\x03\x04fixture",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert metadata.total_count == 1
    assert source.remaining_requests(request, metadata, max_pages=None) == ()
