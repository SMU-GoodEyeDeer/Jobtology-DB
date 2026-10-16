"""Read OpenRouter accounting only; never print keys or raw provider responses.

Run on the Docker host with --container naming the current Hop container. The
protected CSV is read into this process's memory, never an argument or temp file.
This does not make model requests or change account/key/provider configuration.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

KEY_FILE = "/usr/local/tomcat/webapps/ROOT/config/secrets/openrouter.csv"
MAX_BYTES = 65536
ENDPOINTS = {
    "credits": "https://openrouter.ai/api/v1/credits",
    "key": "https://openrouter.ai/api/v1/key",
}
MONEY_FIELDS = (
    "limit", "limit_remaining", "usage", "usage_daily", "usage_weekly", "usage_monthly",
    "byok_usage", "byok_usage_daily", "byok_usage_weekly", "byok_usage_monthly",
)


class SafeFailure(Exception):
    """Fixed error codes only; never wrap credential or HTTP exception text."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: Any, msg: Any,
                         headers: Any, newurl: Any) -> None:
        return None


def load_key(container: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise SafeFailure("invalid_container")
    try:
        result = subprocess.run(
            ["docker", "exec", container, "head", "-c", str(MAX_BYTES + 1), KEY_FILE],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True,
        )
        if len(result.stdout) > MAX_BYTES:
            raise SafeFailure("invalid_credential_file")
        rows = list(csv.reader(io.StringIO(result.stdout.decode("utf-8")), strict=True))
        if len(rows) != 2 or rows[0] != ["api_key"] or len(rows[1]) != 1:
            raise SafeFailure("invalid_credential_file")
        key = rows[1][0]
        # ASCII token shape excludes header injection and accidental multiline CSV.
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,512}", key):
            raise SafeFailure("invalid_credential_file")
        return key
    except SafeFailure:
        raise
    except Exception:
        raise SafeFailure("credential_read_failed") from None


def money(value: Any, nullable: bool = False) -> int | float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SafeFailure("invalid_accounting_response")
    if not math.isfinite(value) or value < 0:
        raise SafeFailure("invalid_accounting_response")
    return value


def summarize(kind: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SafeFailure("invalid_accounting_response")
    raw_data = cast(dict[str, Any], payload).get("data")
    if not isinstance(raw_data, dict):
        raise SafeFailure("invalid_accounting_response")
    data = cast(dict[str, Any], raw_data)
    if kind == "credits":
        credits = money(data.get("total_credits"))
        usage = money(data.get("total_usage"))
        return {
            "total_credits_usd": credits, "total_usage_usd": usage,
            "available_credits_usd": float(Decimal(str(credits)) - Decimal(str(usage))),
        }
    result: dict[str, Any] = {}
    for name in MONEY_FIELDS:
        if name in data:
            result[name + "_usd"] = money(data[name], nullable=name in {"limit", "limit_remaining"})
    if "usage_usd" not in result or "limit_usd" not in result:
        raise SafeFailure("invalid_accounting_response")
    for name in ("include_byok_in_limit", "is_free_tier"):
        if name in data:
            if not isinstance(data[name], bool):
                raise SafeFailure("invalid_accounting_response")
            result[name] = data[name]
    if "limit_reset" in data:
        if data["limit_reset"] not in (None, "daily", "weekly", "monthly"):
            raise SafeFailure("invalid_accounting_response")
        result["limit_reset"] = data["limit_reset"]
    result["byok_usage_separately_reported"] = "byok_usage" in data
    return result


def fetch(kind: str, key: str) -> dict[str, Any]:
    # No endpoint/host input and no redirects: credentials remain at this origin.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        ENDPOINTS[kind], method="GET",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    status: int | None = None
    try:
        with opener.open(request, timeout=30) as response:
            status = response.status
            raw = response.read(MAX_BYTES + 1)
        if status != 200:
            return {"status": "HTTP_ERROR", "http_status": status}
        if len(raw) > MAX_BYTES:
            raise SafeFailure("response_too_large")
        return {"status": "OK", "http_status": status, **summarize(kind, json.loads(raw))}
    except urllib.error.HTTPError as error:
        # Do not read error bodies or stringify errors: labels may contain key fragments.
        error.close()
        return {"status": "HTTP_ERROR", "http_status": error.code}
    except SafeFailure as error:
        return {"status": "INVALID_RESPONSE", "http_status": status, "error": str(error)}
    except Exception:
        return {"status": "FAILED", "http_status": status, "error": "request_failed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True, help="Current Hop container name or ID")
    args = parser.parse_args()
    try:
        key = load_key(args.container)
        result = {kind: fetch(kind, key) for kind in ENDPOINTS}
        del key
    except SafeFailure as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}))
        return 1
    print(json.dumps({"checked_at_utc": datetime.now(UTC).isoformat(), **result}, allow_nan=False))
    return 0 if all(item["status"] == "OK" for item in result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
