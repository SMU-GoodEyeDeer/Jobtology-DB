"""The tiny BYOK probe is opt-in, one-attempt, and keeps unknown costs reserved."""

import importlib.util
import io
import json
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest


@pytest.fixture
def probe(monkeypatch: Any) -> Any:
    tools = Path(__file__).resolve().parents[2] / "hop/llm/tools"
    monkeypatch.syspath_prepend(str(tools))
    spec = importlib.util.spec_from_file_location(
        "byok_probe_test", tools / "openrouter_byok_probe.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_probe_reads_no_key_or_http(probe: Any, monkeypatch: Any, capsys: Any) -> None:
    key = Mock(side_effect=AssertionError("dry mode read a key"))
    http = Mock(side_effect=AssertionError("dry mode requested HTTP"))
    monkeypatch.setattr(probe, "load_key", key)
    monkeypatch.setattr(probe, "send_once", http)
    monkeypatch.setattr(probe.os.sys, "argv", ["probe", "--container", "hop"])
    assert probe.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN"
    key.assert_not_called()
    http.assert_not_called()


def test_one_fixed_http_call_sums_byok_fees_and_redacts_echo(probe: Any, monkeypatch: Any) -> None:
    secret = "fake-secret-only-for-offline-probe-testing"
    envelope = {
        "model": "openai/gpt-5.6-luna", "echo": secret,
        "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}],
        "usage": {"is_byok": True, "cost": 0.00001,
                  "cost_details": {"upstream_inference_cost": 0.00002}},
    }
    response = Mock(status=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(envelope).encode()
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(probe.urllib.request, "build_opener", factory)
    report, archived = probe.send_once(secret)
    assert report["status"] == "COMPLETE" and report["is_byok"] is True
    assert report["reported_total_cost_usd"] == 0.00003
    assert secret not in archived.decode() and secret not in json.dumps(report)
    opener.open.assert_called_once()
    request = opener.open.call_args.args[0]
    assert request.get_method() == "POST" and request.full_url == probe.ENDPOINT
    assert json.loads(request.data) == probe.REQUEST
    assert factory.call_args.args[0].proxies == {}
    assert factory.call_args.args[1].redirect_request(
        None, None, 302, None, None, "https://other"
    ) is None
    envelope["model"] = secret
    response.read.return_value = json.dumps(envelope).encode()
    opener.reset_mock()
    echoed_model, archived_model = probe.send_once(secret)
    assert echoed_model["actual_model"] is None
    assert secret not in archived_model.decode() and secret not in json.dumps(echoed_model)
    opener.open.assert_called_once()


def test_http_error_and_incomplete_cost_keep_unknown_hold(probe: Any, monkeypatch: Any) -> None:
    secret = "fake-secret-only-for-offline-probe-testing"
    error = HTTPError(probe.ENDPOINT, 429, secret, Message(),
                      io.BytesIO(json.dumps({"error": {"message": secret}}).encode()))
    opener = Mock()
    opener.open.side_effect = error
    monkeypatch.setattr(probe.urllib.request, "build_opener", Mock(return_value=opener))
    report, archived = probe.send_once(secret)
    assert report["http_status"] == 429 and report["status"] == "HTTP_ERROR"
    assert report["unknown_cost"] and report["accounted_cost_usd"] == 0.005
    assert secret not in archived.decode() and secret not in json.dumps(report)
    opener.open.assert_called_once()
    for cost in (None, True, "0", -1, float("nan")):
        raw = json.dumps({"usage": {"is_byok": True, "cost": 0,
                                   "cost_details": {"upstream_inference_cost": cost}}}).encode()
        unknown = probe.accounting(200, raw)
        assert unknown["unknown_cost"] and unknown["accounted_cost_usd"] == 0.005
