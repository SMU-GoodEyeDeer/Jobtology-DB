from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text

from jobtology_db.contracts.fetch import SourceReadiness

REQUIRED_FETCH_TABLES = frozenset(
    {
        ("control", "connector_run"),
        ("control", "connector_request"),
        ("raw_manifest", "source_snapshot"),
        ("raw_manifest", "fetch_observation"),
    }
)


@dataclass(frozen=True, slots=True)
class DatabaseLayout:
    expected_heads: frozenset[str]
    current_heads: frozenset[str]
    present_tables: frozenset[tuple[str, str]]

    @property
    def missing_tables(self) -> frozenset[tuple[str, str]]:
        return REQUIRED_FETCH_TABLES - self.present_tables

    @property
    def healthy(self) -> bool:
        return self.current_heads == self.expected_heads and not self.missing_tables

    def detail(self) -> str:
        if self.healthy:
            heads = ",".join(sorted(self.current_heads))
            return f"Alembic head={heads}; required fetch tables present"

        issues: list[str] = []
        if self.current_heads != self.expected_heads:
            current = ",".join(sorted(self.current_heads)) or "<none>"
            expected = ",".join(sorted(self.expected_heads)) or "<none>"
            issues.append(f"Alembic current={current}, expected={expected}")
        if self.missing_tables:
            missing = ",".join(f"{schema}.{table}" for schema, table in sorted(self.missing_tables))
            issues.append(f"missing tables={missing}")
        return "; ".join(issues)


def secret_file_issue(path: Path) -> str | None:
    """Return a safe diagnostic when a dotenv file is not a private regular file."""

    if not path.exists():
        return None

    file_stat = path.stat()
    if not stat.S_ISREG(file_stat.st_mode):
        return f"{path} is not a regular file"

    permissions = stat.S_IMODE(file_stat.st_mode)
    if permissions & (stat.S_IRWXG | stat.S_IRWXO):
        return f"{path} mode is {permissions:04o}; remove all group/other permissions"
    return None


def source_wait_is_failure(readiness: SourceReadiness, *, allow_incomplete_sources: bool) -> bool:
    return readiness is not SourceReadiness.READY and not allow_incomplete_sources


def repository_alembic_heads(config_path: Path) -> frozenset[str]:
    config = Config(str(config_path))
    scripts = ScriptDirectory.from_config(config)
    return frozenset(scripts.get_heads())


def inspect_pipeline_database(database_url: str, alembic_config_path: Path) -> DatabaseLayout:
    expected_heads = repository_alembic_heads(alembic_config_path)
    engine: Engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            current_heads = frozenset(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
            rows = connection.execute(
                text(
                    """
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE (table_schema = 'control'
                           AND table_name IN ('connector_run', 'connector_request'))
                       OR (table_schema = 'raw_manifest'
                           AND table_name IN ('source_snapshot', 'fetch_observation'))
                    """
                )
            )
            present_tables = frozenset((str(row[0]), str(row[1])) for row in rows)
    finally:
        engine.dispose()

    return DatabaseLayout(
        expected_heads=expected_heads,
        current_heads=current_heads,
        present_tables=present_tables,
    )
