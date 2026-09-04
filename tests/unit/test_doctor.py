from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from jobtology_db import cli
from jobtology_db.contracts.fetch import SourceReadiness
from jobtology_db.doctor import (
    REQUIRED_FETCH_TABLES,
    DatabaseLayout,
    repository_alembic_heads,
    secret_file_issue,
    source_wait_is_failure,
)

runner = CliRunner()


class _DoctorSettings:
    def __init__(self, raw_root: Path, database_url: str | None = None) -> None:
        self.JOBTOLOGY_RAW_ROOT = raw_root
        self._database_url = database_url

    def database_url(self) -> str | None:
        return self._database_url


def test_absent_secret_file_is_acceptable(tmp_path: Path) -> None:
    assert secret_file_issue(tmp_path / ".env") is None


def test_secret_file_must_have_no_group_or_other_permissions(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("EXAMPLE=value\n", encoding="utf-8")

    dotenv.chmod(0o600)
    assert secret_file_issue(dotenv) is None

    dotenv.chmod(0o640)
    issue = secret_file_issue(dotenv)
    assert issue is not None
    assert "0640" in issue


def test_secret_file_must_be_regular(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.mkdir(mode=0o700)

    assert secret_file_issue(dotenv) == f"{dotenv} is not a regular file"


def test_source_wait_fails_unless_partial_bootstrap_is_explicit() -> None:
    assert source_wait_is_failure(SourceReadiness.NEEDS_CREDENTIAL, allow_incomplete_sources=False)
    assert not source_wait_is_failure(
        SourceReadiness.NEEDS_CREDENTIAL, allow_incomplete_sources=True
    )
    assert not source_wait_is_failure(SourceReadiness.READY, allow_incomplete_sources=False)


def test_database_layout_requires_exact_head_and_every_fetch_table() -> None:
    healthy = DatabaseLayout(
        expected_heads=frozenset({"0002_storage_error_outcome"}),
        current_heads=frozenset({"0002_storage_error_outcome"}),
        present_tables=REQUIRED_FETCH_TABLES,
    )
    assert healthy.healthy
    assert "required fetch tables present" in healthy.detail()

    incomplete = DatabaseLayout(
        expected_heads=frozenset({"0002_storage_error_outcome"}),
        current_heads=frozenset({"0001_fetch_ledger"}),
        present_tables=REQUIRED_FETCH_TABLES - {("raw_manifest", "fetch_observation")},
    )
    assert not incomplete.healthy
    assert "current=0001_fetch_ledger, expected=0002_storage_error_outcome" in incomplete.detail()
    assert "raw_manifest.fetch_observation" in incomplete.detail()


def test_repository_alembic_head_is_discoverable() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    assert repository_alembic_heads(repository_root / "alembic.ini") == frozenset(
        {"0003_rights_policy_binding"}
    )


def test_doctor_requires_explicit_partial_source_bootstrap(
    tmp_path: Path, monkeypatch: Any
) -> None:
    def waiting_readiness(source_id: str, settings: object) -> tuple[SourceReadiness, str]:
        del source_id, settings
        return SourceReadiness.NEEDS_CREDENTIAL, "FIXTURE_KEY"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "SOURCE_IDS", ("fixture",))
    monkeypatch.setattr(cli, "readiness", waiting_readiness)
    monkeypatch.setattr(cli, "Settings", lambda: _DoctorSettings(tmp_path))

    strict = runner.invoke(cli.app, ["sources", "doctor", "--no-database"])
    partial = runner.invoke(
        cli.app,
        [
            "sources",
            "doctor",
            "--no-database",
            "--allow-incomplete-sources",
        ],
    )

    assert strict.exit_code == 1
    assert "[WAIT] fixture" in strict.output
    assert partial.exit_code == 0
    assert "[WAIT] fixture" in partial.output
    assert "[SKIP] PostgreSQL schema and migration checks" in partial.output
