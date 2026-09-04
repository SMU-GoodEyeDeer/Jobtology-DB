from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import pytest

from jobtology_db.contracts.fetch import RequestSpec
from jobtology_db.pipeline.request_security import (
    DisallowedEndpointError,
    redacted_url,
    request_fingerprint,
    safe_response_headers,
    validate_endpoint,
)


def request_with_key(key: str, *, params_in_reverse_order: bool = False) -> RequestSpec:
    params = {
        "serviceKey": key,
        "pageNo": "1",
        "keyword": "AI 엔지니어",
    }
    if params_in_reverse_order:
        params = dict(reversed(tuple(params.items())))
    return RequestSpec(
        source_id="ncs",
        partition_id="all",
        method="get",
        url="https://apis.data.go.kr/example?fixed=yes&token=url-secret",
        params=params,
        secret_param_names=frozenset({"serviceKey"}),
        page_number=1,
    )


def test_redacted_url_removes_secrets_from_url_and_params() -> None:
    request = request_with_key("parameter-secret")

    result = redacted_url(request)
    query = dict(parse_qsl(urlsplit(result).query))

    assert query == {
        "fixed": "yes",
        "keyword": "AI 엔지니어",
        "pageNo": "1",
        "serviceKey": "<redacted>",
        "token": "<redacted>",
    }
    assert "parameter-secret" not in result
    assert "url-secret" not in result


def test_request_fingerprint_is_stable_across_key_rotation_and_param_order() -> None:
    first = request_with_key("first-secret")
    rotated = request_with_key("second-secret", params_in_reverse_order=True)

    first_fingerprint = request_fingerprint(first)
    rotated_fingerprint = request_fingerprint(rotated)

    assert first_fingerprint == rotated_fingerprint
    assert "first-secret" not in first_fingerprint
    assert "second-secret" not in rotated_fingerprint
    assert len(first_fingerprint) == 64


def test_request_fingerprint_changes_for_non_secret_request_semantics() -> None:
    original = request_with_key("secret")
    changed = RequestSpec(
        source_id=original.source_id,
        partition_id=original.partition_id,
        method=original.method,
        url=original.url,
        params={**original.params, "pageNo": "2"},
        secret_param_names=original.secret_param_names,
        page_number=2,
    )

    assert request_fingerprint(original) != request_fingerprint(changed)


def test_safe_response_headers_is_case_insensitive_and_allowlist_only() -> None:
    result = safe_response_headers(
        {
            "Content-Type": "application/json",
            "ETag": '"abc"',
            "Retry-After": "30",
            "Set-Cookie": "session=super-secret",
            "Authorization": "Bearer super-secret",
            "X-Provider-Debug": "internal",
        }
    )

    assert result == {
        "content-type": "application/json",
        "etag": '"abc"',
        "retry-after": "30",
    }
    assert "super-secret" not in repr(result)


@pytest.mark.parametrize(
    "url",
    [
        "http://apis.data.go.kr/path",
        "https://evil.example/path",
        "https://user:password@apis.data.go.kr/path",
        "https://apis.data.go.kr/path#fragment",
    ],
)
def test_validate_endpoint_rejects_unsafe_endpoint(url: str) -> None:
    with pytest.raises(DisallowedEndpointError):
        validate_endpoint(url, {"apis.data.go.kr"})


def test_validate_endpoint_accepts_https_host_case_insensitively() -> None:
    validate_endpoint("https://APIS.DATA.GO.KR/path", {"apis.data.go.kr"})
