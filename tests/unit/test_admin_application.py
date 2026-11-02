from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jobtology_db.admin.app import create_app
from jobtology_db.admin.application import ApplicationAPI
from jobtology_db.admin.config import AdminSettings

IDENTIFIER = UUID("74163956-6d3c-4b54-901a-043f1c79eacb")
TOKEN = "test-management-bearer-that-must-remain-server-only"


def configuration(tmp_path: Path, **overrides: Any) -> AdminSettings:
    values: dict[str, Any] = dict(
        username="operator",
        password="test-password",
        secret="s" * 32,
        cookie_secure=False,
        queue_path=tmp_path / "queue.sqlite3",
        application_api_url="http://private-backend:8000",
        application_api_token=TOKEN,
    )
    values.update(overrides)
    return AdminSettings(**values)


def test_management_auth_csrf_origin_and_bounded_routes(tmp_path: Path):
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": str(IDENTIFIER),
                            "display_name": "Tester",
                            "token": "do-not-expose",
                            "password_hash": "private",
                        }
                    ],
                    "total": 1,
                },
            )
        return httpx.Response(200, json={"ok": True, "token": "do-not-expose"})

    settings = configuration(tmp_path)
    api = ApplicationAPI(settings, httpx.MockTransport(upstream))
    with cast(Any, TestClient(create_app(settings, application_api=api))) as client:
        assert client.get("/api/application/users").status_code == 401
        auth = client.post(
            "/api/login", json={"username": "operator", "password": "test-password"}
        ).json()
        headers = {"X-CSRF-Token": auth["csrf_token"]}
        route = f"/api/application/users/{IDENTIFIER}"
        assert client.patch(route, json={"status": "DEACTIVATED"}).status_code == 403
        assert (
            client.patch(
                route,
                json={"status": "DEACTIVATED"},
                headers={**headers, "Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )
        assert not seen
        result = client.get("/api/application/users?limit=20&offset=40")
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
        assert "do-not-expose" not in result.text and TOKEN not in result.text
        assert seen[-1].url.path == "/internal/admin/users"
        assert dict(seen[-1].url.params) == {"limit": "20", "offset": "40"}
        assert client.patch(route, json={"status": "DEACTIVATED"}, headers=headers).json() == {
            "ok": True
        }
        assert json.loads(seen[-1].content) == {"status": "DEACTIVATED"}
        assert client.post(route + "/revoke-sessions", headers=headers).status_code == 200
        assert client.get("/api/application/users?limit=101").status_code == 422
        assert client.patch(route, json={"status": None}, headers=headers).status_code == 422
        assert (
            client.patch(
                route, json={"access_expires_at": "2026-11-10T00:00:00"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post("/api/application/users/not-a-uuid/revoke", headers=headers).status_code
            == 422
        )
        assert client.post(route + "/unexpected", headers=headers).status_code == 404
        assert client.get("/api/application/secrets").status_code == 404


def test_create_qr_and_edit_independent_expiries(tmp_path: Path):
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        invitation = {"id": str(IDENTIFIER), "label": "Pilot", "code_hint": "…abcd"}
        if request.method == "GET":
            return httpx.Response(200, json={"items": [invitation], "total": 1})
        if request.method == "PATCH":
            return httpx.Response(200, json=invitation)
        return httpx.Response(
            201,
            json={
                "invitation": invitation,
                "code": "new-test-code-once",
                "invite_url": "https://app.example/invite?code=new-test-code-once",
            },
        )

    settings = configuration(tmp_path)
    with cast(
        Any,
        TestClient(
            create_app(
                settings, application_api=ApplicationAPI(settings, httpx.MockTransport(upstream))
            )
        ),
    ) as client:
        auth = client.post(
            "/api/login", json={"username": "operator", "password": "test-password"}
        ).json()
        headers = {"X-CSRF-Token": auth["csrf_token"]}
        result = client.post(
            "/api/application/invitations",
            headers=headers,
            json={"label": "Pilot", "expires_at": None, "access_hours": 0.5, "max_uses": None},
        )
        assert result.status_code == 201
        assert result.json()["code"] == "new-test-code-once"
        assert "<svg" in result.json()["qr_svg"]
        assert json.loads(seen[-1].content)["access_hours"] == 0.5
        listing = client.get("/api/application/invitations")
        assert "new-test-code-once" not in listing.text and "qr_svg" not in listing.text
        result = client.patch(
            f"/api/application/invitations/{IDENTIFIER}", headers=headers, json={"expires_at": None}
        )
        assert result.status_code == 200 and json.loads(seen[-1].content) == {"expires_at": None}
        for bad in (
            {"label": "x", "max_uses": 0},
            {"label": "x", "access_hours": 0},
            {"label": "x", "expires_at": "2026-11-01T10:00:00"},
        ):
            assert (
                client.post("/api/application/invitations", headers=headers, json=bad).status_code
                == 422
            )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://attacker.invalid"}),
        httpx.Response(401, text=TOKEN),
        httpx.Response(500, text=TOKEN),
        httpx.Response(200, content=b"x" * 524289),
        httpx.Response(200, json={"items": [], "total": -1}),
        httpx.Response(200, json={"items": [{"token": TOKEN}], "total": 1}),
        httpx.Response(
            200,
            json={"items": [{"id": str(IDENTIFIER), "display_name": {"token": TOKEN}}], "total": 1},
        ),
    ],
)
def test_unavailable_invalid_and_redirect_responses_never_leak(
    tmp_path: Path, response: httpx.Response
):
    count = 0

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return response

    with pytest.raises(HTTPException) as error:
        ApplicationAPI(configuration(tmp_path), httpx.MockTransport(upstream)).request(
            "GET", "sessions"
        )
    assert error.value.status_code == 503 and TOKEN not in error.value.detail
    assert count == 1


def test_missing_configuration_and_secret_validation(tmp_path: Path):
    settings = configuration(tmp_path, application_api_token=None)
    with pytest.raises(HTTPException, match="503") as error:
        ApplicationAPI(settings).request("GET", "invitations")
    assert "not configured" in error.value.detail
    for overrides in (
        {"application_api_url": "http://private/backend"},
        {"application_api_url": "http://user:secret@private"},
        {"application_api_token": "short-secret"},
    ):
        with pytest.raises(ValidationError) as error:
            configuration(tmp_path, **overrides)
        assert "input_value" not in str(error.value) and "short-secret" not in str(error.value)
