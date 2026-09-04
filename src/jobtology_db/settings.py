from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _today_compact() -> str:
    return date.today().strftime("%Y%m%d")


def _next_year_compact() -> str:
    return (date.today() + timedelta(days=365)).strftime("%Y%m%d")


class Settings(BaseSettings):
    """Runtime settings. Secret values are never included in representations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    JOBTOLOGY_PIPELINE_DATABASE_URL: SecretStr | None = None
    JOBTOLOGY_RAW_ROOT: Path = Path("./data")
    JOBTOLOGY_HTTP_USER_AGENT: str = "Jobtology/0.1 (set JOBTOLOGY_CONTACT_EMAIL)"
    JOBTOLOGY_CONTACT_EMAIL: str = ""
    JOBTOLOGY_HTTP_CONNECT_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    JOBTOLOGY_HTTP_READ_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0, le=300)
    JOBTOLOGY_HTTP_MAX_ATTEMPTS: int = Field(default=4, ge=1, le=8)
    JOBTOLOGY_HTTP_MAX_RETRY_AFTER_SECONDS: int = Field(default=60, ge=0, le=300)
    JOBTOLOGY_HTTP_MAX_RESPONSE_BYTES: int = Field(
        default=64 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024
    )
    JOBTOLOGY_RAW_MIN_FREE_BYTES: int = Field(default=1024 * 1024 * 1024, ge=0)
    JOBTOLOGY_RAW_MAX_USED_FRACTION: float = Field(default=0.85, gt=0, lt=1)
    JOBTOLOGY_SOURCE_RIGHTS_FILE: Path = (
        Path(__file__).resolve().parents[2] / "config" / "source_rights.yaml"
    )

    DATA_GO_KR_SERVICE_KEY: SecretStr | None = None
    SARAMIN_ACCESS_KEY: SecretStr | None = None
    SARAMIN_KEYWORDS: str = "AI 엔지니어,백엔드 개발자,프론트엔드 개발자,데이터 분석가"
    WORK24_AUTH_KEY: SecretStr | None = None
    WORK24_START_DATE: str = Field(default_factory=_today_compact)
    WORK24_END_DATE: str = Field(default_factory=_next_year_compact)
    WORK24_NCS1: str = "20"
    WORK24_COURSE_TYPES: str = "C0104,C0105,C0061"
    QNET_YEARS: str = Field(default_factory=lambda: f"{date.today().year},{date.today().year + 1}")
    QNET_ITEM_CODES_FILE: Path | None = None
    NCS_QUALIFICATION_CODES_FILE: Path | None = None
    NCS_CAREER_PATH_DOWNLOAD_URL: str | None = None
    JOB_ALIO_ONGOING_ONLY: bool = True

    def database_url(self) -> str | None:
        return (
            self.JOBTOLOGY_PIPELINE_DATABASE_URL.get_secret_value()
            if self.JOBTOLOGY_PIPELINE_DATABASE_URL
            else None
        )

    def http_user_agent(self) -> str:
        user_agent = self.JOBTOLOGY_HTTP_USER_AGENT.strip()
        contact = self.JOBTOLOGY_CONTACT_EMAIL.strip()
        if not user_agent:
            raise ValueError("JOBTOLOGY_HTTP_USER_AGENT cannot be empty")
        if any(character in user_agent or character in contact for character in ("\r", "\n")):
            raise ValueError("HTTP user-agent settings cannot contain newlines")
        if contact and "set JOBTOLOGY_CONTACT_EMAIL" in user_agent:
            return user_agent.replace("set JOBTOLOGY_CONTACT_EMAIL", f"+mailto:{contact}")
        return user_agent

    def data_go_key(self) -> str | None:
        """Accept either portal representation; HTTPX performs the final URL encoding."""
        if self.DATA_GO_KR_SERVICE_KEY is None:
            return None
        return unquote(self.DATA_GO_KR_SERVICE_KEY.get_secret_value().strip())

    @staticmethod
    def secret_value(value: SecretStr | None) -> str | None:
        if value is None:
            return None
        unwrapped = value.get_secret_value().strip()
        return unwrapped or None

    @staticmethod
    def csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]
