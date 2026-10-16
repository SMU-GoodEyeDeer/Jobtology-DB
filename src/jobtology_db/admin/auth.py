"""Signed expiring cookies, constant-time credential checks and bounded login attempts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import OrderedDict
from typing import Any

from jobtology_db.admin.config import AdminSettings

COOKIE_NAME = "jobtology_admin_session"


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class SessionAuth:
    def __init__(self, settings: AdminSettings):
        self.settings = settings
        self.secret = settings.secret.get_secret_value().encode()
        self.password_hash = hashlib.sha256(settings.password.get_secret_value().encode()).digest()
        self.version = encode(hmac.digest(self.secret, self.password_hash, "sha256"))

    def credentials_valid(self, username: str, password: str) -> bool:
        expected = hashlib.sha256(self.settings.username.encode()).digest()
        user_valid = hmac.compare_digest(hashlib.sha256(username.encode()).digest(), expected)
        password_valid = hmac.compare_digest(
            hashlib.sha256(password.encode()).digest(), self.password_hash
        )
        return user_valid and password_valid

    def issue(self) -> tuple[str, dict[str, Any]]:
        payload = {
            "u": self.settings.username,
            "e": int(time.time()) + self.settings.session_seconds,
            "c": secrets.token_urlsafe(32),
            "p": self.version,
        }
        encoded = encode(json.dumps(payload, separators=(",", ":")).encode())
        signature = encode(hmac.digest(self.secret, encoded.encode(), "sha256"))
        return f"{encoded}.{signature}", payload

    def verify(self, token: str | None) -> dict[str, Any] | None:
        if not token or len(token) > 2048:
            return None
        try:
            encoded, signature = token.split(".")
            expected = encode(hmac.digest(self.secret, encoded.encode(), "sha256"))
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if (
                payload["u"] != self.settings.username
                or type(payload["e"]) is not int
                or payload["e"] <= time.time()
                or not hmac.compare_digest(payload["p"], self.version)
                or not isinstance(payload["c"], str)
                or len(payload["c"]) != 43
            ):
                return None
            return payload
        except (ValueError, KeyError, TypeError):
            return None


class LoginLimiter:
    def __init__(self):
        self._entries: OrderedDict[str, list[float]] = OrderedDict()
        self._global: list[float] = []
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        with self._lock:
            cutoff = time.monotonic() - 300
            self._global = [entry for entry in self._global if entry > cutoff]
            attempts = [entry for entry in self._entries.get(client, []) if entry > cutoff]
            self._entries[client] = attempts
            self._entries.move_to_end(client)
            while len(self._entries) > 1024:
                self._entries.popitem(last=False)
            if len(attempts) >= 5 or len(self._global) >= 30:
                return False
            current = time.monotonic()
            attempts.append(current)
            self._global.append(current)
            return True
