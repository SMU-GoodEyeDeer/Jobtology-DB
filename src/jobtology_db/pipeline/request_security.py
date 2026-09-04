from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobtology_db.contracts.fetch import RequestSpec

DEFAULT_SECRET_QUERY_NAMES = frozenset(
    {
        "servicekey",
        "authkey",
        "access-key",
        "api_key",
        "apikey",
        "key",
        "token",
    }
)

SAFE_RESPONSE_HEADERS = frozenset(
    {"content-type", "content-length", "etag", "last-modified", "retry-after"}
)


class DisallowedEndpointError(ValueError):
    pass


def validate_endpoint(url: str, allowed_hosts: Iterable[str]) -> None:
    parsed = urlsplit(url)
    allowed = {host.casefold() for host in allowed_hosts}
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in allowed
    ):
        raise DisallowedEndpointError(
            f"Endpoint must use HTTPS and one of the configured source hosts: {sorted(allowed)}"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise DisallowedEndpointError("Endpoint credentials and fragments are forbidden")


def redacted_url(request: RequestSpec) -> str:
    parsed = urlsplit(request.url)
    secret_names = DEFAULT_SECRET_QUERY_NAMES | {
        name.casefold() for name in request.secret_param_names
    }
    pairs = list(parse_qsl(parsed.query, keep_blank_values=True))
    pairs.extend((str(key), str(value)) for key, value in request.params.items())
    safe_pairs = [
        (key, "<redacted>" if key.casefold() in secret_names else value) for key, value in pairs
    ]
    query = urlencode(sorted(safe_pairs), doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def request_fingerprint(request: RequestSpec) -> str:
    canonical = {
        "method": request.method.upper(),
        "url": redacted_url(request),
        "response_ordinal": request.response_ordinal,
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def safe_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key.casefold(): value
        for key, value in headers.items()
        if key.casefold() in SAFE_RESPONSE_HEADERS
    }
