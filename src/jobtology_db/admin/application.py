"""Fixed, bounded management API client. Its bearer token never reaches the browser."""

from __future__ import annotations

import io
import time
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jobtology_db.admin.config import AdminSettings


class ManagementModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True, allow_inf_nan=False
    )


class InvitationFields(ManagementModel):
    label: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None
    access_hours: float | None = Field(default=None, gt=0, le=876000)
    max_uses: int | None = Field(default=None, ge=1, le=1000000, strict=True)

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value


class InvitationPatch(InvitationFields):
    label: str = Field(default="", min_length=1, max_length=100)


class UserPatch(ManagementModel):
    status: Literal["ACTIVE", "DEACTIVATED"] | None = None
    access_expires_at: datetime | None = None

    @field_validator("access_expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        return InvitationFields.timezone_required(value)


# Responses are projected onto documented fields. No upstream session tokens,
# password hashes or operational diagnostics may pass through a generic proxy.
FIELDS = {
    "invitations": {
        "id",
        "label",
        "code_hint",
        "created_at",
        "expires_at",
        "access_hours",
        "max_uses",
        "use_count",
        "revoked_at",
    },
    "users": {
        "id",
        "display_name",
        "status",
        "created_at",
        "access_source",
        "access_expires_at",
        "invitation_label",
        "active_sessions",
    },
    "sessions": {"id", "user_id", "display_name", "created_at", "expires_at", "revoked_at"},
}


def public_item(value: Any, resource: str) -> dict[str, Any]:
    if not isinstance(value, dict) or "id" not in value:
        raise ValueError("invalid item")
    result = {
        key: item for key, item in cast(dict[str, Any], value).items() if key in FIELDS[resource]
    }
    # Contract fields are scalar metadata. Nested additions must not become an
    # accidental route for session credentials or internal account records.
    for item in result.values():
        if item is not None and type(item) not in {str, int, float}:
            raise ValueError("invalid metadata field")
        if isinstance(item, str) and len(item) > 4096:
            raise ValueError("metadata field too long")
    UUID(result["id"])
    return result


class ApplicationAPI:
    def __init__(self, settings: AdminSettings, transport: httpx.BaseTransport | None = None):
        self.settings, self.transport = settings, transport

    def request(
        self,
        method: str,
        resource: str,
        *,
        identifier: UUID | None = None,
        action: str | None = None,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = self.settings
        if settings.mode == "demo":
            raise HTTPException(503, "Application management is unavailable in demo mode.")
        if not settings.application_api_url or not settings.application_api_token:
            raise HTTPException(
                503,
                "Application management is not configured. "
                "Configure the private application API URL and token.",
            )
        if resource not in FIELDS or action not in (None, "revoke", "revoke-sessions"):
            raise ValueError("unsupported management request")
        path = "/internal/admin/" + resource
        if identifier is not None:
            path += "/" + str(identifier)
        if action:
            path += "/" + action
        try:
            deadline = time.monotonic() + 8.0
            with (
                httpx.Client(
                    timeout=httpx.Timeout(8.0, connect=3.0),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client,
                client.stream(
                    method,
                    settings.application_api_url.rstrip("/") + path,
                    headers={
                        "Authorization": "Bearer "
                        + settings.application_api_token.get_secret_value(),
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    params=params,
                    json=body,
                ) as response,
            ):
                if response.status_code in (400, 404, 409, 422):
                    raise HTTPException(
                        response.status_code,
                        "The application rejected this request. "
                        "Refresh and check the submitted values.",
                    )
                if response.status_code >= 300:
                    raise HTTPException(
                        503,
                        "Application management is unavailable. "
                        "Check server connectivity and management credentials.",
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("compressed management response refused")
                if int(response.headers.get("content-length", "0")) > 524288:
                    raise ValueError("response too large")
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if time.monotonic() > deadline:
                        raise TimeoutError("management response deadline")
                    raw.extend(chunk)
                    if len(raw) > 524288:
                        raise ValueError("response too large")
            import json

            data: Any = json.loads(raw)
            if method == "GET":
                if not isinstance(data, dict):
                    raise ValueError("invalid page")
                data = cast(dict[str, Any], data)
                if not isinstance(data.get("items"), list):
                    raise ValueError("invalid page")
                if (
                    len(data["items"]) > 100
                    or type(data.get("total")) is not int
                    or data["total"] < 0
                ):
                    raise ValueError("invalid pagination")
                return {
                    "items": [
                        public_item(item, resource) for item in cast(list[Any], data["items"])
                    ],
                    "total": data["total"],
                }
            if method == "POST" and resource == "invitations" and not action:
                code, url = data["code"], data["invite_url"]
                if not isinstance(code, str) or not 8 <= len(code) <= 512:
                    raise ValueError("invalid code")
                parsed = httpx.URL(url)
                if parsed.scheme not in ("http", "https") or not parsed.host or len(url) > 4096:
                    raise ValueError("invalid invitation URL")
                import qrcode
                import qrcode.image.svg

                image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathFillImage)
                output = io.BytesIO()
                image.save(output)
                return {
                    "invitation": public_item(data["invitation"], resource),
                    "code": code,
                    "invite_url": url,
                    "qr_svg": output.getvalue().decode(),
                }
            if method == "PATCH" and resource == "invitations":
                return public_item(data, resource)
            if data.get("ok") is not True:
                raise ValueError("invalid result")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                503, "Application management returned an unavailable or invalid response."
            ) from None
