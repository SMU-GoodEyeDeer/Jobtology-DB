"""One opt-in tiny OpenRouter request to verify the actual BYOK routing flag.

Default dry mode reads no credential and sends no request. --execute reads the
existing protected CSV in memory and performs exactly one fixed HTTPS POST.
No production database, source fetch or account/provider setting is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from openrouter_balance import MAX_BYTES, NoRedirect, SafeFailure, load_key, money

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-5.6-luna"
UNKNOWN_RESERVE_USD = Decimal("0.005")
REQUEST = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Reply OK."}],
    "provider": {
        "only": ["openai"], "allow_fallbacks": False, "require_parameters": True,
        "max_price": {"prompt": 0.20, "completion": 1.20},
    },
    "reasoning": {"effort": "none", "exclude": True},
    "max_tokens": 32,
    "stream": False,
}


def accounting(status: int, raw: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "HTTP_ERROR" if status != 200 else "UNKNOWN_ACCOUNTING",
        "http_status": status, "actual_model": None, "is_byok": None,
        "router_cost_usd": None, "upstream_inference_cost_usd": None,
        "reported_total_cost_usd": None,
        "accounted_cost_usd": float(UNKNOWN_RESERVE_USD),
        "unknown_cost": True,
    }
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return result
        envelope = cast(dict[str, Any], payload)
        model = envelope.get("model")
        if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,127}", model):
            result["actual_model"] = model
        usage = envelope.get("usage")
        if not isinstance(usage, dict):
            return result
        usage = cast(dict[str, Any], usage)
        byok = usage.get("is_byok")
        if not isinstance(byok, bool):
            return result
        result["is_byok"] = byok
        router = money(usage.get("cost"))
        result["router_cost_usd"] = router
        total = Decimal(str(router))
        if byok:
            details = usage.get("cost_details")
            if not isinstance(details, dict):
                return result
            upstream = money(cast(dict[str, Any], details).get("upstream_inference_cost"))
            result["upstream_inference_cost_usd"] = upstream
            total += Decimal(str(upstream))
        else:
            details = usage.get("cost_details")
            if isinstance(details, dict) and "upstream_inference_cost" in details:
                result["upstream_inference_cost_usd"] = money(details["upstream_inference_cost"])
        result.update(reported_total_cost_usd=float(total), accounted_cost_usd=float(total),
                      unknown_cost=False)
        if status == 200:
            choices = envelope.get("choices")
            entries = cast(list[Any], choices) if isinstance(choices, list) else []
            choice = entries[0] if len(entries) == 1 else None
            chosen = cast(dict[str, Any], choice) if isinstance(choice, dict) else {}
            if (chosen.get("finish_reason") == "stop"
                    and result["actual_model"] is not None):
                result["status"] = "COMPLETE"
            else:
                result["status"] = "INCOMPLETE_RESPONSE"
        return result
    except Exception:
        return result


def send_once(key: str) -> tuple[dict[str, Any], bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        ENDPOINT, method="POST", data=json.dumps(REQUEST, separators=(",", ":")).encode(),
        headers={"Authorization": "Bearer " + key, "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    status = 0
    raw = b""
    try:
        with opener.open(request, timeout=60) as response:
            status = response.status
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            raw = error.read(MAX_BYTES + 1)
        finally:
            error.close()
    except Exception:
        result = accounting(0, b"")
        result.update(status="TRANSPORT_UNKNOWN", error="request_failed")
        return result, b""
    if len(raw) > MAX_BYTES:
        result = accounting(status, b"")
        result.update(status="RESPONSE_TOO_LARGE", error="response_too_large")
        return result, b""
    # Request headers are never archived. Also remove an unexpected response echo.
    redacted = raw.replace(key.encode("ascii"), b"[REDACTED]")
    return accounting(status, redacted), redacted


def protected_write(folder: Path, name: str, content: bytes) -> None:
    fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    (folder / name).chmod(0o400)


def private_folder(requested: Path | None) -> Path:
    folder = requested or (
        Path.home() / ".local/state/jobtology-hop" / ("byok-probe-" + uuid.uuid4().hex)
    )
    folder = folder.absolute()
    for component in (folder, *folder.parents):
        if component.is_symlink():
            raise SafeFailure("receipt_symlink_forbidden")
    folder.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        raise SafeFailure("receipt_directory_exists") from None
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True, help="Current Hop container name or ID")
    parser.add_argument("--execute", action="store_true",
                        help="Enable exactly one tiny paid model request")
    parser.add_argument("--receipt-dir", type=Path, help="New protected receipt directory")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "DRY_RUN", "execute": False, "model": MODEL,
                          "max_tokens": 32, "maximum_requests": 1,
                          "unknown_cost_reservation_usd": float(UNKNOWN_RESERVE_USD)}))
        return 0
    try:
        key = load_key(args.container)
        folder = private_folder(args.receipt_dir)
        started = datetime.now(UTC).isoformat()
        request = json.dumps({"endpoint": ENDPOINT, "body": REQUEST}, indent=2).encode()
        protected_write(folder, "request.json", request)
        protected_write(folder, "reservation.json", json.dumps({
            "state": "ONE_REQUEST_AUTHORIZED_UNKNOWN_UNTIL_RECEIPT", "started_at_utc": started,
            "maximum_requests": 1, "accounted_cost_usd": float(UNKNOWN_RESERVE_USD),
        }, indent=2).encode())
        report, raw = send_once(key)
        del key
        protected_write(folder, "response.bin", raw)
        receipt = {"started_at_utc": started, "finished_at_utc": datetime.now(UTC).isoformat(),
                   "maximum_requests": 1, "request_sha256": hashlib.sha256(request).hexdigest(),
                   "response_sha256": hashlib.sha256(raw).hexdigest(), **report}
        protected_write(folder, "receipt.json",
                        json.dumps(receipt, indent=2, allow_nan=False).encode())
        print(json.dumps({**report, "receipt": str(folder / "receipt.json")}, allow_nan=False))
        return 0 if report["status"] == "COMPLETE" else 1
    except SafeFailure as error:
        print(json.dumps({"status": "FAILED_BEFORE_REQUEST", "error": str(error),
                          "accounted_cost_usd": 0}))
        return 1
    except Exception:
        # The reservation sidecar remains if a post-request receipt write failed.
        print(json.dumps({"status": "FAILED", "error": "probe_failed",
                          "accounted_cost_usd": float(UNKNOWN_RESERVE_USD)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
