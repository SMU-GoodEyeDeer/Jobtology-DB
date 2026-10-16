"""Accounting probes must not leak credentials or follow authenticated redirects."""

import importlib.util
import json
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest


@pytest.fixture
def probe() -> Any:
    path = Path(__file__).resolve().parents[2] / "hop/llm/tools/openrouter_balance.py"
    spec = importlib.util.spec_from_file_location("openrouter_balance_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_credentials_read_in_memory_without_secret_arguments(probe: Any, monkeypatch: Any) -> None:
    secret = "fake-secret-for-offline-testing-only"
    run = Mock(return_value=SimpleNamespace(stdout=f"api_key\n{secret}\n".encode()))
    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.load_key("hop-container") == secret
    assert secret not in repr(run.call_args)
    assert run.call_args.args[0][:3] == ["docker", "exec", "hop-container"]


def test_response_allowlist_omits_labels_and_account_identifiers(probe: Any) -> None:
    payload = {"data": {"label": "secret-fragment", "creator_user_id": "private-user",
                        "limit": None, "limit_remaining": None, "usage": 0.5,
                        "byok_usage": 0.1, "include_byok_in_limit": False}}
    result = probe.summarize("key", payload)
    assert result["limit_usd"] is None
    assert result["byok_usage_separately_reported"] is True
    assert "secret-fragment" not in json.dumps(result)
    assert "private-user" not in json.dumps(result)
    assert probe.summarize("credits", {"data": {"total_credits": 20, "total_usage": 0.1}})[
        "available_credits_usd"
    ] == 19.9


@pytest.mark.parametrize("value", ["secret-fragment", True, float("nan"), float("inf"), -1])
def test_untrusted_accounting_values_are_rejected(probe: Any, value: Any) -> None:
    with pytest.raises(probe.SafeFailure, match=r"^invalid_accounting_response$"):
        probe.money(value)


def test_http_errors_discard_payload_and_exception_text(probe: Any, monkeypatch: Any) -> None:
    error = HTTPError(probe.ENDPOINTS["credits"], 403, "secret-fragment", Message(), None)
    opener = Mock()
    opener.open.side_effect = error
    monkeypatch.setattr(probe.urllib.request, "build_opener", Mock(return_value=opener))
    assert probe.fetch("credits", "fake-secret") == {"status": "HTTP_ERROR", "http_status": 403}
    request = opener.open.call_args.args[0]
    assert request.get_method() == "GET"
    assert request.full_url == "https://openrouter.ai/api/v1/credits"


def test_redirect_and_transport_failure_cannot_leak_key(probe: Any, monkeypatch: Any) -> None:
    assert probe.NoRedirect().redirect_request(None, None, 302, None, None, "https://other") is None
    opener = Mock()
    opener.open.side_effect = RuntimeError("Bearer secret-fragment")
    monkeypatch.setattr(probe.urllib.request, "build_opener", Mock(return_value=opener))
    assert probe.fetch("key", "fake-secret") == {
        "status": "FAILED", "http_status": None, "error": "request_failed"
    }
