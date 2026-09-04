from __future__ import annotations

import json
from dataclasses import replace

import pytest

from jobtology_db.connectors.base import ResponseContractError
from jobtology_db.connectors.sources import JobAlioConnector
from jobtology_db.pipeline.request_security import redacted_url, request_fingerprint


def index_body(*, total: int, page: int, identities: tuple[str, ...]) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "totalCount": total,
                    "pageNo": page,
                    "items": [{"recrutPblntSn": identity} for identity in identities],
                },
            }
        },
        separators=(",", ":"),
    ).encode()


def detail_body(identity: str) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"item": {"recrutPblntSn": identity, "title": "채용"}},
            }
        },
        separators=(",", ":"),
    ).encode()


def test_initial_request_is_active_only_and_secret_safe() -> None:
    secret = "job-alio-secret"
    request = JobAlioConnector(secret, ongoing_only=True).initial_requests()[0]

    assert request.url == "https://apis.data.go.kr/1051000/recruitment/list"
    assert request.partition_id == "index"
    assert request.page_number == 1
    assert request.params == {
        "serviceKey": secret,
        "resultType": "json",
        "ongoingYn": "Y",
        "pageNo": "1",
        "numOfRows": "100",
    }
    persisted_url = redacted_url(request)
    assert secret not in persisted_url
    assert "serviceKey=%3Credacted%3E" in persisted_url
    assert "ongoingYn=Y" in persisted_url


def test_disabling_active_filter_omits_ongoing_parameter() -> None:
    request = JobAlioConnector("secret", ongoing_only=False).initial_requests()[0]

    assert "ongoingYn" not in request.params


def test_first_list_page_expands_remaining_page_and_each_unique_detail() -> None:
    source = JobAlioConnector("secret")
    first = source.initial_requests()[0]
    metadata = source.validate_response(
        first,
        index_body(total=150, page=1, identities=("POST-002", "POST-001", "POST-001")),
        "application/json",
    )

    requests = source.remaining_requests(first, metadata, max_pages=None)

    assert metadata.discovered_record_ids == ("POST-001", "POST-002")
    assert [request.partition_id for request in requests] == [
        "index",
        "detail-POST-001",
        "detail-POST-002",
    ]
    second_page, first_detail, second_detail = requests
    assert second_page.page_number == 2
    assert second_page.params["pageNo"] == "2"
    assert second_page.params["ongoingYn"] == "Y"
    assert second_page.params["serviceKey"] == "secret"
    assert first_detail.params["sn"] == "POST-001"
    assert second_detail.params["sn"] == "POST-002"
    assert first_detail.url.endswith("/recruitment/detail")
    assert all("secret" not in redacted_url(request) for request in requests)


def test_later_list_page_expands_details_but_does_not_replan_pages() -> None:
    source = JobAlioConnector("secret")
    initial = source.initial_requests()[0]
    first_metadata = source.validate_response(
        initial,
        index_body(total=150, page=1, identities=("POST-001",)),
        "application/json",
    )
    second_page = source.remaining_requests(initial, first_metadata, max_pages=None)[0]
    second_metadata = source.validate_response(
        second_page,
        index_body(total=150, page=2, identities=("POST-150",)),
        "application/json",
    )

    requests = source.remaining_requests(second_page, second_metadata, max_pages=None)

    assert [request.partition_id for request in requests] == ["detail-POST-150"]


def test_detail_response_must_match_requested_posting_identity() -> None:
    source = JobAlioConnector("secret")
    initial = source.initial_requests()[0]
    index_metadata = source.validate_response(
        initial,
        index_body(total=1, page=1, identities=("POST-001",)),
        "application/json",
    )
    detail_request = source.remaining_requests(initial, index_metadata, max_pages=None)[0]

    accepted = source.validate_response(
        detail_request,
        detail_body("POST-001"),
        "application/json",
    )
    assert accepted.total_count == 1
    assert source.remaining_requests(detail_request, accepted, max_pages=None) == ()

    with pytest.raises(ResponseContractError, match="identity does not match"):
        source.validate_response(
            detail_request,
            detail_body("POST-WRONG"),
            "application/json",
        )


def test_positive_list_total_rejects_missing_or_blank_identities() -> None:
    source = JobAlioConnector("secret")
    request = source.initial_requests()[0]

    for identities in ((), ("", "   ")):
        with pytest.raises(ResponseContractError, match="no posting identities"):
            source.validate_response(
                request,
                index_body(total=1, page=1, identities=identities),
                "application/json",
            )


def test_active_zero_result_requires_second_independent_observation() -> None:
    source = JobAlioConnector("secret", ongoing_only=True)
    first = source.initial_requests()[0]
    first_metadata = source.validate_response(
        first,
        index_body(total=0, page=1, identities=()),
        "application/json",
    )

    confirmation_requests = source.remaining_requests(first, first_metadata, max_pages=None)

    assert len(confirmation_requests) == 1
    confirmation = confirmation_requests[0]
    assert confirmation.response_ordinal == 1
    assert confirmation.params["ongoingYn"] == "Y"
    assert confirmation.url == first.url
    assert request_fingerprint(confirmation) != request_fingerprint(first)

    confirmation_metadata = source.validate_response(
        confirmation,
        index_body(total=0, page=1, identities=()),
        "application/json",
    )
    assert source.remaining_requests(confirmation, confirmation_metadata, max_pages=None) == ()


def test_index_page_mismatch_is_rejected() -> None:
    source = JobAlioConnector("secret")
    requested_page_two = replace(
        source.initial_requests()[0],
        page_number=2,
        params={"serviceKey": "secret", "pageNo": "2", "numOfRows": "100"},
    )

    with pytest.raises(ResponseContractError, match="does not match request"):
        source.validate_response(
            requested_page_two,
            index_body(total=150, page=1, identities=("POST-001",)),
            "application/json",
        )
