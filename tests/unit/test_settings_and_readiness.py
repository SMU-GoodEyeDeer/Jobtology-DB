from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from jobtology_db.connectors import sources as source_module
from jobtology_db.connectors.sources import (
    SourceConfigurationError,
    build_connector,
    readiness,
)
from jobtology_db.contracts.fetch import SourceReadiness
from jobtology_db.rights import SourceActivationCheck
from jobtology_db.settings import Settings


@pytest.fixture(autouse=True)
def isolate_settings_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep developer/server environment files from influencing unit tests."""
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def allow_pending_source_rights(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permit connector-contract tests without weakening the checked-in production registry."""

    original = source_module.source_activation_check

    def allow(source_id: str, settings: Settings) -> SourceActivationCheck:
        check = original(source_id, settings)
        if source_id not in {"saramin", "work24_training"}:
            return check
        return SourceActivationCheck(
            source_id=check.source_id,
            status="ALLOWED",
            allowed=True,
            policy_version=check.policy_version,
            registry_revision=check.registry_revision,
            policy_hash=check.policy_hash,
            requested_content=check.requested_content,
            out_of_scope_content=(),
            blocking_permissions=(),
            reason=None,
        )

    monkeypatch.setattr(source_module, "source_activation_check", allow)


def test_settings_decode_data_go_key_once_and_keep_all_secrets_out_of_rendering() -> None:
    encoded_key = "portal%2Bkey%2Fvalue%3D"
    database_url = "postgresql+psycopg://ledger:database-secret@localhost/pipeline"
    settings = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr(f"  {encoded_key}  "),
        SARAMIN_ACCESS_KEY=SecretStr("saramin-secret"),
        WORK24_AUTH_KEY=SecretStr("work24-secret"),
        JOBTOLOGY_PIPELINE_DATABASE_URL=SecretStr(database_url),
    )

    assert settings.data_go_key() == "portal+key/value="
    assert settings.database_url() == database_url
    rendered = "\n".join(
        (
            repr(settings),
            str(settings),
            repr(settings.model_dump()),
            repr(settings.model_dump(mode="json")),
        )
    )
    for secret in (encoded_key, "saramin-secret", "work24-secret", "database-secret"):
        assert secret not in rendered


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("JOBTOLOGY_HTTP_CONNECT_TIMEOUT_SECONDS", 0),
        ("JOBTOLOGY_HTTP_READ_TIMEOUT_SECONDS", 301),
        ("JOBTOLOGY_HTTP_MAX_ATTEMPTS", 0),
        ("JOBTOLOGY_HTTP_MAX_ATTEMPTS", 9),
        ("JOBTOLOGY_HTTP_MAX_RETRY_AFTER_SECONDS", -1),
    ],
)
def test_settings_reject_invalid_http_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_data_go_sources_require_shared_credential_and_source_specific_config(
    tmp_path: Path,
) -> None:
    without_key = Settings(
        DATA_GO_KR_SERVICE_KEY=None,
        NCS_QUALIFICATION_CODES_FILE=None,
    )
    for source_id in (
        "ncs_competency",
        "ncs_qualification",
        "qnet_schedule",
        "job_alio",
        "alio_organization",
    ):
        assert readiness(source_id, without_key) == (
            SourceReadiness.NEEDS_CREDENTIAL,
            "DATA_GO_KR_SERVICE_KEY",
        )

    with_key = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key"),
        NCS_QUALIFICATION_CODES_FILE=None,
    )
    assert readiness("ncs_qualification", with_key) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "NCS_QUALIFICATION_CODES_FILE",
    )
    assert readiness("qnet_schedule", with_key) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "QNET_ITEM_CODES_FILE",
    )
    for source_id in ("ncs_competency", "job_alio", "alio_organization"):
        assert readiness(source_id, with_key) == (SourceReadiness.READY, "ready")

    codes = tmp_path / "codes.txt"
    codes.write_text(
        "# relevant NCS unit codes\n1501020207_14v2\n\n2001010101_01v1\n",
        encoding="utf-8",
    )
    fully_configured = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key"),
        NCS_QUALIFICATION_CODES_FILE=codes,
    )
    assert readiness("ncs_qualification", fully_configured) == (
        SourceReadiness.READY,
        "ready",
    )


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "# comments only\n",
        "200101\n",
        "1501020207-14v2\n",
        "1501020207_14\n",
        "1501020207_14v2\ninvalid\n",
    ],
)
def test_ncs_qualification_requires_only_full_versioned_unit_codes(
    tmp_path: Path,
    contents: str,
) -> None:
    codes = tmp_path / "codes.txt"
    codes.write_text(contents, encoding="utf-8")
    settings = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key"),
        NCS_QUALIFICATION_CODES_FILE=codes,
    )

    assert readiness("ncs_qualification", settings) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "NCS_QUALIFICATION_CODES_FILE",
    )
    with pytest.raises(SourceConfigurationError, match="NCS_QUALIFICATION_CODES_FILE"):
        build_connector("ncs_qualification", settings)


def test_ncs_qualification_deduplicates_full_versioned_codes_in_input_order(
    tmp_path: Path,
) -> None:
    codes = tmp_path / "codes.txt"
    codes.write_text(
        "1501020207_14v2\n2001010101_01v1\n1501020207_14v2\n",
        encoding="utf-8",
    )
    settings = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key"),
        NCS_QUALIFICATION_CODES_FILE=codes,
    )

    connector = build_connector("ncs_qualification", settings)
    requests = connector.initial_requests()

    assert [request.partition_id for request in requests] == [
        "ncs-1501020207_14v2",
        "ncs-2001010101_01v1",
    ]
    assert [request.params["ncsClCd"] for request in requests] == [
        "1501020207_14v2",
        "2001010101_01v1",
    ]


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "# comments only\n",
        "123\n",
        "ABCDE\n",
        "12-3\n",
        "1320\ninvalid\n",
    ],
)
def test_qnet_schedule_requires_four_character_item_codes(
    tmp_path: Path,
    contents: str,
) -> None:
    codes = tmp_path / "qnet-codes.txt"
    codes.write_text(contents, encoding="utf-8")
    settings = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key"),
        QNET_ITEM_CODES_FILE=codes,
    )

    assert readiness("qnet_schedule", settings) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "QNET_ITEM_CODES_FILE",
    )
    with pytest.raises(SourceConfigurationError, match="QNET_ITEM_CODES_FILE"):
        build_connector("qnet_schedule", settings)


def test_qnet_schedule_deduplicates_items_and_crosses_them_with_years(
    tmp_path: Path,
) -> None:
    codes = tmp_path / "qnet-codes.txt"
    codes.write_text("1320\nab12\n1320\n", encoding="utf-8")
    settings = Settings(
        DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key"),
        QNET_ITEM_CODES_FILE=codes,
        QNET_YEARS="2026,2027",
    )

    connector = build_connector("qnet_schedule", settings)
    requests = connector.initial_requests()

    assert [request.partition_id for request in requests] == [
        "year-2026-item-1320",
        "year-2026-item-AB12",
        "year-2027-item-1320",
        "year-2027-item-AB12",
    ]
    assert [request.params["jmCd"] for request in requests] == [
        "1320",
        "AB12",
        "1320",
        "AB12",
    ]


def test_ncs_career_file_uses_nonsecret_pinned_url() -> None:
    missing = Settings(
        DATA_GO_KR_SERVICE_KEY=None,
        NCS_CAREER_PATH_DOWNLOAD_URL=None,
    )
    configured = Settings(
        DATA_GO_KR_SERVICE_KEY=None,
        NCS_CAREER_PATH_DOWNLOAD_URL="https://www.data.go.kr/file-download?id=fixture",
    )

    assert readiness("ncs_career_path", missing) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "NCS_CAREER_PATH_DOWNLOAD_URL",
    )
    assert readiness("ncs_career_path", configured) == (SourceReadiness.READY, "ready")


@pytest.mark.parametrize(
    "url",
    [
        "https://data.go.kr/file-download?id=fixture",
        "https://www.data.go.kr.evil.example/file-download?id=fixture",
        "https://evil.example/file-download?id=fixture",
    ],
)
def test_ncs_career_file_rejects_noncanonical_host(url: str) -> None:
    settings = Settings(NCS_CAREER_PATH_DOWNLOAD_URL=url)

    with pytest.raises(SourceConfigurationError, match=r"official www\.data\.go\.kr host"):
        build_connector("ncs_career_path", settings)


def test_saramin_rights_gate_blocks_connector_even_when_key_exists() -> None:
    secret = "saramin-key-must-stay-secret"
    blocked = Settings(
        SARAMIN_ACCESS_KEY=SecretStr(secret),
        SARAMIN_KEYWORDS="AI 엔지니어",
    )

    assert readiness("saramin", blocked) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "RIGHTS_BLOCKED (2026-09-05.1)",
    )
    with pytest.raises(SourceConfigurationError) as captured:
        build_connector("saramin", blocked)
    assert "RIGHTS_BLOCKED" in str(captured.value)
    assert secret not in str(captured.value)


def test_saramin_configuration_after_rights_approval(
    allow_pending_source_rights: None,
) -> None:
    del allow_pending_source_rights
    empty_scope = Settings(
        SARAMIN_ACCESS_KEY=SecretStr("secret"),
        SARAMIN_KEYWORDS=" , ",
    )
    assert readiness("saramin", empty_scope) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "SARAMIN_KEYWORDS",
    )

    approved = Settings(
        SARAMIN_ACCESS_KEY=SecretStr("secret"),
        SARAMIN_KEYWORDS="AI 엔지니어",
    )
    assert readiness("saramin", approved) == (SourceReadiness.READY, "ready")


def test_work24_rights_gate_blocks_connector_even_when_key_exists() -> None:
    secret = "work24-key-must-stay-secret"
    blocked = Settings(
        WORK24_AUTH_KEY=SecretStr(secret),
    )

    assert readiness("work24_training", blocked) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "RIGHTS_BLOCKED (2026-09-05.1)",
    )
    with pytest.raises(SourceConfigurationError) as captured:
        build_connector("work24_training", blocked)
    assert "RIGHTS_BLOCKED" in str(captured.value)
    assert secret not in str(captured.value)


def test_work24_configuration_after_rights_approval(
    allow_pending_source_rights: None,
) -> None:
    del allow_pending_source_rights
    approved = Settings(
        WORK24_AUTH_KEY=SecretStr("secret"),
        WORK24_START_DATE="20260905",
        WORK24_END_DATE="20270305",
    )
    assert readiness("work24_training", approved) == (SourceReadiness.READY, "ready")


def test_work24_requires_at_least_one_course_type(
    allow_pending_source_rights: None,
) -> None:
    del allow_pending_source_rights
    settings = Settings(
        WORK24_AUTH_KEY=SecretStr("secret"),
        WORK24_COURSE_TYPES=" , ",
    )

    assert readiness("work24_training", settings) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "WORK24_COURSE_TYPES",
    )
    with pytest.raises(SourceConfigurationError, match="WORK24_COURSE_TYPES"):
        build_connector("work24_training", settings)


@pytest.mark.parametrize(
    "course_types",
    [
        "C9999",
        "C0104,C9999",
        "c0104",
        "C010",
    ],
)
def test_work24_rejects_course_types_outside_fixed_mvp_allowlist(
    course_types: str,
    allow_pending_source_rights: None,
) -> None:
    del allow_pending_source_rights
    settings = Settings(
        WORK24_AUTH_KEY=SecretStr("secret"),
        WORK24_COURSE_TYPES=course_types,
    )

    assert readiness("work24_training", settings) == (
        SourceReadiness.NEEDS_CONFIGURATION,
        "WORK24_COURSE_TYPES",
    )
    with pytest.raises(SourceConfigurationError, match="WORK24_COURSE_TYPES"):
        build_connector("work24_training", settings)


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("20260230", "20260301", "WORK24_START_DATE must use YYYYMMDD"),
        ("20260101", "20261301", "WORK24_END_DATE must use YYYYMMDD"),
        ("2026010", "20260301", "WORK24_START_DATE must use YYYYMMDD"),
        ("20261001", "20260901", "WORK24_START_DATE cannot be after WORK24_END_DATE"),
    ],
)
def test_work24_rejects_invalid_or_reversed_date_window(
    start: str,
    end: str,
    message: str,
    allow_pending_source_rights: None,
) -> None:
    del allow_pending_source_rights
    settings = Settings(
        WORK24_AUTH_KEY=SecretStr("secret"),
        WORK24_COURSE_TYPES="C0104",
        WORK24_START_DATE=start,
        WORK24_END_DATE=end,
    )

    with pytest.raises(SourceConfigurationError, match=message):
        build_connector("work24_training", settings)


def test_work24_valid_dates_and_course_types_create_fixed_partitions(
    allow_pending_source_rights: None,
) -> None:
    del allow_pending_source_rights
    settings = Settings(
        WORK24_AUTH_KEY=SecretStr("secret"),
        WORK24_COURSE_TYPES="C0104, C0105,C0104,C0061",
        WORK24_START_DATE="20260905",
        WORK24_END_DATE="20270305",
    )

    connector = build_connector("work24_training", settings)
    requests = connector.initial_requests()

    assert [request.partition_id for request in requests] == [
        "course-type-C0104",
        "course-type-C0105",
        "course-type-C0061",
    ]
    assert [request.params["crseTracseSe"] for request in requests] == [
        "C0104",
        "C0105",
        "C0061",
    ]
    assert all(request.params["srchTraStDt"] == "20260905" for request in requests)
    assert all(request.params["srchTraEndDt"] == "20270305" for request in requests)


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(SourceConfigurationError, match="Unknown source"):
        readiness("not-a-source", Settings())
