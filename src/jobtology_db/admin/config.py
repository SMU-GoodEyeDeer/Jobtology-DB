"""Configuration is operator supplied; request data never becomes a command or path."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ACTION_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ActionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    id: str = Field(pattern=ACTION_ID.pattern)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    kind: Literal["refresh_due", "load_jobkorea"]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def bounded_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > 16_384:
            raise ValueError("action parameters too large")
        return value

    def fingerprint(self) -> str:
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    @model_validator(mode="after")
    def validate_parameters(self) -> ActionProfile:
        paths = (
            {"runtime_env"}
            if self.kind == "refresh_due"
            else {
                "manifest",
                "composition_dir",
                "checkpoint_dir",
            }
        )
        expected = paths if self.kind == "refresh_due" else paths | {"manifest_sha256"}
        if set(self.parameters) != expected:
            raise ValueError("invalid action parameter names")
        for key in paths:
            value = self.parameters[key]
            if (
                not isinstance(value, str)
                or len(value) > 4096
                or any(char in value for char in ("\x00", "\n", "\r"))
                or not Path(value).is_absolute()
                or ".." in Path(value).parts
            ):
                raise ValueError("action paths must be absolute and canonical")
        if self.kind == "load_jobkorea" and not re.fullmatch(
            r"[0-9a-f]{64}", str(self.parameters["manifest_sha256"])
        ):
            raise ValueError("manifest hash is required")
        return self


class ActionProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: Literal[1]
    actions: list[ActionProfile] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_ids(self) -> ActionProfiles:
        if len({item.id for item in self.actions}) != len(self.actions):
            raise ValueError("duplicate action id")
        return self


def load_profiles(path: Path | None) -> list[ActionProfile]:
    if path is None:
        return []
    # The path is operator configuration, never an HTTP argument. Reject symlinks
    # and broadly writable profiles; the web process needs read access only.
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid action configuration")
    if path.stat().st_size > 65_536 or path.stat().st_mode & 0o022:
        raise ValueError("unsafe action configuration")
    return ActionProfiles.model_validate_json(path.read_bytes()).actions


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBTOLOGY_ADMIN_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr
    secret: SecretStr
    mode: Literal["live", "demo"] = "live"
    cookie_secure: bool = True
    session_seconds: int = Field(default=28_800, ge=300, le=86_400)
    allowed_origins: str = ""
    postgres_dsn: SecretStr | None = None
    neo4j_uri: str | None = None
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr | None = None
    neo4j_database: str = "neo4j"
    query_timeout_seconds: float = Field(default=4.0, ge=0.2, le=15)
    cache_seconds: int = Field(default=30, ge=5, le=300)
    queue_path: Path = Path("/var/lib/jobtology-admin/queue.sqlite3")
    actions_file: Path | None = None
    controls_enabled: bool = False
    worker_stale_seconds: int = Field(default=45, ge=15, le=300)

    @model_validator(mode="after")
    def require_secrets(self) -> AdminSettings:
        if len(self.password.get_secret_value()) < 8:
            raise ValueError("admin password must contain at least 8 characters")
        if len(self.secret.get_secret_value()) < 32:
            raise ValueError("admin secret must contain at least 32 characters")
        if self.neo4j_uri and not self.neo4j_uri.startswith(
            ("bolt://", "bolt+s://", "bolt+ssc://", "neo4j://", "neo4j+s://", "neo4j+ssc://")
        ):
            raise ValueError("invalid Neo4j URI scheme")
        return self

    def origins(self) -> set[str]:
        return {
            item.strip().rstrip("/") for item in self.allowed_origins.split(",") if item.strip()
        }


def private_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("queue may not be a symlink")
    if path.exists():
        os.chmod(path, 0o600)
