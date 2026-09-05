from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import httpx
import typer

from jobtology_db.connectors.base import Connector
from jobtology_db.connectors.sources import (
    SOURCE_IDS,
    SourceConfigurationError,
    build_connector,
    readiness,
    source_activation_check,
)
from jobtology_db.contracts.fetch import RunMode, SourceReadiness
from jobtology_db.doctor import (
    inspect_pipeline_database,
    secret_file_issue,
    source_wait_is_failure,
)
from jobtology_db.partition_config import (
    MVP_NCS_SUBCATEGORY_ALLOWLIST_VERSION,
    PartitionConfigError,
    derive_ncs_qualification_codes,
    derive_qnet_item_codes,
    write_partition_codes,
)
from jobtology_db.pipeline.fetch import FetchEngine, FetchRunError, RetryPolicy, planned_requests
from jobtology_db.pipeline.request_security import redacted_url
from jobtology_db.settings import Settings
from jobtology_db.storage.ledger import PostgresFetchLedger
from jobtology_db.storage.raw_files import RawFileStore

app = typer.Typer(help="Jobtology source ingestion CLI", no_args_is_help=True)
sources_app = typer.Typer(help="Inspect connector configuration", no_args_is_help=True)
fetch_app = typer.Typer(help="Plan or execute raw source fetches", no_args_is_help=True)
derive_app = typer.Typer(help="Derive connector partitions from fetched runs", no_args_is_help=True)
app.add_typer(sources_app, name="sources")
app.add_typer(fetch_app, name="fetch")
app.add_typer(derive_app, name="derive")

_DEFAULT_NCS_QUALIFICATION_CODES_PATH = Path("config/ncs_qualification_codes.txt")
_DEFAULT_QNET_ITEM_CODES_PATH = Path("config/qnet_item_codes.txt")


@sources_app.command("list")
def list_sources() -> None:
    """List every checked-in MVP source and its local readiness."""
    settings = Settings()
    for source_id in SOURCE_IDS:
        status, detail = readiness(source_id, settings)
        typer.echo(f"{source_id:22} {status.value:20} {detail}")


@sources_app.command()
def doctor(
    check_database: bool = typer.Option(True, "--database/--no-database"),
    allow_incomplete_sources: bool = typer.Option(
        False,
        "--allow-incomplete-sources",
        help="Permit missing provider approvals/configuration during partial bootstrap",
    ),
) -> None:
    """Check credentials/configuration plus raw-store and PostgreSQL access."""
    settings = Settings()
    failed = False
    for source_id in SOURCE_IDS:
        status, detail = readiness(source_id, settings)
        marker = "OK" if status is SourceReadiness.READY else "WAIT"
        typer.echo(f"[{marker}] {source_id}: {status.value} ({detail})")
        failed = failed or source_wait_is_failure(
            status, allow_incomplete_sources=allow_incomplete_sources
        )

    dotenv_path = Path(".env")
    dotenv_issue = secret_file_issue(dotenv_path)
    if dotenv_issue is not None:
        typer.echo(f"[FAIL] secrets file: {dotenv_issue}")
        failed = True
    elif dotenv_path.exists():
        typer.echo(f"[OK] secrets file: {dotenv_path} is owner-only")
    else:
        typer.echo("[OK] secrets file: .env is absent")

    raw_root = settings.JOBTOLOGY_RAW_ROOT.resolve()
    raw_parent = raw_root if raw_root.exists() else raw_root.parent
    raw_ready = raw_parent.exists() and os.access(raw_parent, os.W_OK | os.X_OK)
    typer.echo(f"[{'OK' if raw_ready else 'FAIL'}] raw store: {raw_root}")
    failed = failed or not raw_ready

    database_url = settings.database_url()
    if not check_database:
        typer.echo("[SKIP] PostgreSQL schema and migration checks")
    elif database_url is None:
        typer.echo("[FAIL] PostgreSQL: JOBTOLOGY_PIPELINE_DATABASE_URL is not set")
        failed = True
    else:
        try:
            alembic_config = Path(__file__).resolve().parents[2] / "alembic.ini"
            layout = inspect_pipeline_database(database_url, alembic_config)
            marker = "OK" if layout.healthy else "FAIL"
            typer.echo(f"[{marker}] PostgreSQL: {layout.detail()}")
            failed = failed or not layout.healthy
        except Exception:
            typer.echo(
                "[FAIL] PostgreSQL schema/migration check failed (credentials are not printed)"
            )
            failed = True

    if failed:
        raise typer.Exit(code=1)


@fetch_app.command("plan")
def plan_fetch(source_id: str = typer.Argument(help="Source ID from `sources list`")) -> None:
    """Print redacted first requests without network or database access."""
    settings = Settings()
    connector = _connector(source_id, settings)
    typer.echo(f"source={connector.source_id} completeness={connector.completeness_mode.value}")
    for request in planned_requests(connector):
        typer.echo(f"{request.partition_id}: {request.method} {redacted_url(request)}")
    typer.echo("Further pages/details are planned from validated provider responses.")


@fetch_app.command("run")
def run_fetch(
    source_id: str = typer.Argument(help="Source ID from `sources list`"),
    mode: str = typer.Option("backfill", help="backfill or scheduled-full"),
    max_pages: int | None = typer.Option(
        None,
        min=1,
        help="Backfill safety cap per list partition; forbidden for scheduled-full",
    ),
    run_id: str | None = typer.Option(None, help="Optional parent orchestration run ID"),
) -> None:
    """Fetch validated raw responses into PostgreSQL and content-addressed storage."""
    settings = Settings()
    connector = _connector(source_id, settings)
    rights_check = source_activation_check(source_id, settings)
    database_url = settings.database_url()
    if database_url is None:
        typer.echo("Error: JOBTOLOGY_PIPELINE_DATABASE_URL is required", err=True)
        raise typer.Exit(code=2)
    resolved_mode = _run_mode(mode)

    timeout = httpx.Timeout(
        connect=settings.JOBTOLOGY_HTTP_CONNECT_TIMEOUT_SECONDS,
        read=settings.JOBTOLOGY_HTTP_READ_TIMEOUT_SECONDS,
        write=settings.JOBTOLOGY_HTTP_READ_TIMEOUT_SECONDS,
        pool=settings.JOBTOLOGY_HTTP_CONNECT_TIMEOUT_SECONDS,
    )
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            engine = FetchEngine(
                client=client,
                raw_store=RawFileStore(settings.JOBTOLOGY_RAW_ROOT),
                ledger=PostgresFetchLedger(database_url, rights_check=rights_check),
                retry_policy=RetryPolicy(
                    max_attempts=settings.JOBTOLOGY_HTTP_MAX_ATTEMPTS,
                    max_retry_after_seconds=settings.JOBTOLOGY_HTTP_MAX_RETRY_AFTER_SECONDS,
                ),
                user_agent=settings.http_user_agent(),
                max_response_bytes=settings.JOBTOLOGY_HTTP_MAX_RESPONSE_BYTES,
                raw_min_free_bytes=settings.JOBTOLOGY_RAW_MIN_FREE_BYTES,
                raw_max_used_fraction=settings.JOBTOLOGY_RAW_MAX_USED_FRACTION,
            )
            summary = engine.run(
                connector,
                mode=resolved_mode,
                run_id=run_id,
                max_pages=max_pages,
            )
    except (FetchRunError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except Exception as error:
        typer.echo("Error: fetch infrastructure failed; credentials were not printed", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
    typer.echo("Raw fetch completed. Run remains RUNNING at stage FETCHED for later processing.")


@derive_app.command("ncs-qualification-codes")
def derive_ncs_qualification_codes_command(
    connector_run_id: str = typer.Argument(help="Complete ncs_competency connector run ID"),
    output: Annotated[
        Path,
        typer.Option("--output", help="Destination connector partition file"),
    ] = _DEFAULT_NCS_QUALIFICATION_CODES_PATH,
) -> None:
    """Derive MVP NCS unit-code partitions from a complete competency fetch."""

    settings = Settings()
    database_url = settings.database_url()
    if database_url is None:
        typer.echo("Error: JOBTOLOGY_PIPELINE_DATABASE_URL is required", err=True)
        raise typer.Exit(code=2)
    try:
        codes = derive_ncs_qualification_codes(
            database_url,
            settings.JOBTOLOGY_RAW_ROOT,
            connector_run_id,
        )
        write_partition_codes(output, codes)
    except PartitionConfigError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except Exception as error:
        typer.echo(
            "Error: partition derivation infrastructure failed; credentials were not printed",
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(
        f"Wrote {len(codes)} NCS codes to {output} "
        f"(allowlist {MVP_NCS_SUBCATEGORY_ALLOWLIST_VERSION})."
    )


@derive_app.command("qnet-item-codes")
def derive_qnet_item_codes_command(
    connector_run_id: str = typer.Argument(help="Complete ncs_qualification connector run ID"),
    output: Annotated[
        Path,
        typer.Option("--output", help="Destination connector partition file"),
    ] = _DEFAULT_QNET_ITEM_CODES_PATH,
) -> None:
    """Derive Q-Net item-code partitions from a complete NCS mapping fetch."""

    settings = Settings()
    database_url = settings.database_url()
    if database_url is None:
        typer.echo("Error: JOBTOLOGY_PIPELINE_DATABASE_URL is required", err=True)
        raise typer.Exit(code=2)
    try:
        codes = derive_qnet_item_codes(
            database_url,
            settings.JOBTOLOGY_RAW_ROOT,
            connector_run_id,
        )
        write_partition_codes(output, codes)
    except PartitionConfigError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except Exception as error:
        typer.echo(
            "Error: partition derivation infrastructure failed; credentials were not printed",
            err=True,
        )
        raise typer.Exit(code=1) from error
    typer.echo(f"Wrote {len(codes)} Q-Net item codes to {output}.")


def _connector(source_id: str, settings: Settings) -> Connector:
    if source_id not in SOURCE_IDS:
        typer.echo(f"Error: unknown source {source_id!r}", err=True)
        raise typer.Exit(code=2)
    try:
        return build_connector(source_id, settings)
    except SourceConfigurationError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error


def _run_mode(value: str) -> RunMode:
    normalized = value.strip().replace("_", "-").casefold()
    if normalized == "backfill":
        return RunMode.BACKFILL
    if normalized == "scheduled-full":
        return RunMode.SCHEDULED_FULL
    typer.echo("Error: --mode must be backfill or scheduled-full", err=True)
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
