from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jobtology_db.admin.app import create_app
from jobtology_db.admin.auth import COOKIE_NAME, SessionAuth
from jobtology_db.admin.config import AdminSettings


def settings(tmp_path: Path, **overrides: Any) -> AdminSettings:
    values: dict[str, Any] = {
        "username": "operator",
        "password": "local-test-password-only",
        "secret": "local-test-signing-secret-32-characters-long",
        "mode": "demo",
        "cookie_secure": False,
        "queue_path": tmp_path / "queue.sqlite3",
    }
    values.update(overrides)
    return AdminSettings(**values)


def login(client: Any) -> Any:
    return client.post(
        "/api/login", json={"username": "operator", "password": "local-test-password-only"}
    )


def test_auth_csrf_logout_and_no_demo_writes(tmp_path: Path):
    configuration = settings(tmp_path)
    application = create_app(configuration)
    with cast(Any, TestClient(application)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/dashboard").status_code == 401
        assert client.get("/api/session").json()["authenticated"] is False
        result = login(client)
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        csrf = result.json()["csrf_token"]
        data = client.get("/api/dashboard").json()
        assert data["mode"] == "demo"
        assert all(not action["enabled"] for action in data["actions"])
        assert any("synthetic" in notice["body"].lower() for notice in data["notices"])
        assert client.post("/api/logout").status_code == 403
        assert (
            client.post(
                "/api/jobs",
                json={"action_id": "refresh-due", "idempotency_key": "valid-key-1234567"},
                headers={"X-CSRF-Token": csrf},
            ).status_code
            == 403
        )
        assert client.post("/api/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/api/dashboard").status_code == 401
    assert not configuration.queue_path.exists()


def test_secure_cookie_and_invalid_token(tmp_path: Path):
    configuration = settings(tmp_path, cookie_secure=True)
    with cast(Any, TestClient(create_app(configuration), base_url="https://testserver")) as client:
        result = login(client)
        assert "Secure" in result.headers["set-cookie"]
        token = client.cookies[COOKIE_NAME]
        client.cookies.set(COOKIE_NAME, token + "x")
        assert client.get("/api/dashboard").status_code == 401


def test_origin_size_validation_and_login_rate_limits(tmp_path: Path):
    with cast(Any, TestClient(create_app(settings(tmp_path)))) as client:
        assert (
            client.post(
                "/api/login",
                json={"username": "operator", "password": "x"},
                headers={"Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )
        oversized = client.post("/api/login", content="x" * 20_000)
        assert oversized.status_code == 413
        streamed = client.post("/api/login", content=iter([b"x" * 9000, b"y" * 9000]))
        assert streamed.status_code == 413
        secret = "submitted-password-must-not-be-echoed"
        invalid = client.post(
            "/api/login", json={"username": "operator", "password": secret, "surprise": "bad"}
        )
        assert invalid.status_code == 422 and secret not in invalid.text
        for _ in range(5):
            assert (
                client.post(
                    "/api/login", json={"username": "operator", "password": "bad"}
                ).status_code
                == 401
            )
        assert login(client).status_code == 429


def test_signature_expiry_and_password_rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    auth = SessionAuth(settings(tmp_path))
    token, payload = auth.issue()
    assert auth.verify(token) is not None
    assert auth.verify("not-a-signed-cookie") is None
    other = SessionAuth(settings(tmp_path, password="another-password-with-required-length"))
    assert other.verify(token) is None
    monkeypatch.setattr("jobtology_db.admin.auth.time.time", lambda: payload["e"] + 1)
    assert auth.verify(token) is None


def test_credentials_are_explicit_and_bounded(tmp_path: Path):
    settings(tmp_path, password="12345678", secret="s" * 32)
    with pytest.raises(ValidationError, match="at least 8 characters") as error:
        settings(tmp_path, password="1234567")
    assert "local-test-signing-secret" not in str(error.value)
    assert "input_value" not in str(error.value)
    with pytest.raises(ValidationError, match="at least 32 characters"):
        settings(tmp_path, secret="s" * 31)
    with pytest.raises(ValidationError):
        settings(tmp_path, neo4j_uri="https://not-a-graph.invalid")


def test_eight_character_password_authenticates(tmp_path: Path):
    with cast(Any, TestClient(create_app(settings(tmp_path, password="12345678")))) as client:
        result = client.post(
            "/api/login", json={"username": "operator", "password": "12345678"}
        )
        assert result.status_code == 200
        assert client.get("/api/session").json()["authenticated"] is True


def test_startup_model_validation_never_prints_credentials(tmp_path: Path):
    password = "private"  # Triggers the model validator's minimum-length failure.
    secret = "supplied-signing-secret-that-must-never-appear-in-startup-logs"
    with pytest.raises(ValidationError) as error:
        settings(tmp_path, password=password, secret=secret)
    diagnostic = str(error.value)
    assert "at least 8 characters" in diagnostic
    assert password not in diagnostic and secret not in diagnostic
    assert "input_value" not in diagnostic


def test_live_jobs_are_gated_safe_and_idempotent(tmp_path: Path):
    profile_path = tmp_path / "actions.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": [
                    {
                        "id": "refresh-due",
                        "label": "Refresh due sources",
                        "kind": "refresh_due",
                        "parameters": {"runtime_env": "/protected/runtime.env"},
                    }
                ],
            }
        )
    )
    profile_path.chmod(0o600)
    configuration = settings(
        tmp_path, mode="live", actions_file=profile_path, controls_enabled=True
    )
    application = create_app(configuration)
    with cast(Any, TestClient(application)) as client:
        auth = login(client).json()
        headers = {"X-CSRF-Token": auth["csrf_token"]}
        request = {"action_id": "refresh-due", "idempotency_key": "operator-retry-key-123"}
        assert client.post("/api/jobs", json=request, headers=headers).status_code == 409
        application.state.runtime.store.heartbeat("unit-worker")
        assert client.post("/api/jobs", json=request).status_code == 403
        result = client.post("/api/jobs", json=request, headers=headers)
        assert result.status_code == 202
        assert "runtime" not in result.text and "profile_sha256" not in result.text
        job = application.state.runtime.store.claim("unit-worker")
        assert job["id"] == result.json()["job"]["id"]
        retry = client.post("/api/jobs", json=request, headers=headers)
        assert retry.status_code == 202 and retry.json()["job"]["id"] == job["id"]
        request["action_id"] = "../../bin/sh"
        assert client.post("/api/jobs", json=request, headers=headers).status_code == 422
