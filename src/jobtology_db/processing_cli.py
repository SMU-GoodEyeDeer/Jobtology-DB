from __future__ import annotations

import json
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from types import FrameType
from typing import Any

import typer
from sqlalchemy import Engine, create_engine, text

from jobtology_db.contracts.processing import PROCESSABLE_SOURCES
from jobtology_db.pipeline.canonical import assemble_run, latest_processing_runs
from jobtology_db.pipeline.process import process_run
from jobtology_db.pipeline.update import (
    due,
    json_event,
    read_schedule,
    source_state,
    update_sources,
)
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings
from jobtology_db.storage.neo4j_staging import load_neo4j_staging

process_app = typer.Typer(
    help="Replay saved inputs into typed PostgreSQL staging", no_args_is_help=True
)
load_app = typer.Typer(
    help="Explicit downstream staging loads (not corpus publication)", no_args_is_help=True
)
pipeline_app = typer.Typer(help="Scheduled fetch -> process -> load updater", no_args_is_help=True)


def _execute(action: Callable[[Engine, Settings], None]) -> None:
    engine: Engine | None = None
    try:
        settings = Settings()
        url = settings.database_url()
        if url is None:
            raise ProcessingError("DATABASE_URL_REQUIRED")
        engine = create_engine(url, pool_pre_ping=True)
        action(engine, settings)
    except ProcessingError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=75 if str(error) == "PIPELINE_BUSY" else 1) from error
    except typer.Exit:
        raise
    except Exception as error:
        typer.echo(
            f"Error: {type(error).__name__}; credentials/raw data were not printed", err=True
        )
        raise typer.Exit(code=1) from error
    finally:
        if engine is not None:
            engine.dispose()


@process_app.command("run")
def process_command(connector_run_id: str) -> None:
    """Offline replay of one complete fetch. No provider requests or Neo4j writes."""

    def action(engine: Engine, settings: Settings) -> None:
        summary = process_run(engine, settings.JOBTOLOGY_RAW_ROOT, connector_run_id, settings)
        typer.echo(summary.model_dump_json(indent=2))
        if summary.state != "READY":
            raise typer.Exit(code=1)

    _execute(action)


@process_app.command("latest")
def process_latest() -> None:
    """Process the latest FETCHED SCHEDULED_FULL run per supported source; never merge runs."""

    def action(engine: Engine, settings: Settings) -> None:
        failed = False
        for source in PROCESSABLE_SOURCES:
            with engine.connect() as c:
                run_id = c.scalar(
                    text("""
                    SELECT connector_run_id FROM control.connector_run
                    WHERE source_id=:source AND mode='SCHEDULED_FULL' AND stage='FETCHED'
                      AND state='RUNNING' ORDER BY fetch_completed_at DESC LIMIT 1
                """),
                    {"source": source},
                )
            if run_id is None:
                json_event({"source_id": source, "state": "MISSING_FETCH"})
                failed = True
                continue
            try:
                summary = process_run(engine, settings.JOBTOLOGY_RAW_ROOT, run_id, settings)
                json_event(summary.model_dump(mode="json"))
                failed |= summary.state != "READY"
            except Exception as error:
                code = str(error) if isinstance(error, ProcessingError) else type(error).__name__
                json_event({"source_id": source, "state": "FAILED", "error_code": code})
                failed = True
        if failed:
            raise typer.Exit(code=1)

    _execute(action)


@load_app.command("neo4j")
def load_graph(processing_run_id: str) -> None:
    """Load an isolated, provenance-linked IngestBatch. Does not activate a corpus release."""

    def action(engine: Engine, settings: Settings) -> None:
        json_event(load_neo4j_staging(engine, settings, processing_run_id))

    _execute(action)


@load_app.command("canonical")
def load_canonical(processing_run_id: str) -> None:
    """Offline canonical PostgreSQL assembly of one READY processing run; no Neo4j writes."""

    def action(engine: Engine, settings: Settings) -> None:
        json_event(assemble_run(engine, settings, processing_run_id, emit=json_event))

    _execute(action)


@load_app.command("canonical-latest")
def load_canonical_latest() -> None:
    """Assemble the latest READY full processing run for each of the six supported sources."""

    def action(engine: Engine, settings: Settings) -> None:
        for run_id in latest_processing_runs(engine):
            json_event(assemble_run(engine, settings, run_id, emit=json_event))

    _execute(action)


@pipeline_app.command("status")
def status() -> None:
    """Read persisted cadence/status. No fetch, file writes, or upstream probes."""

    def action(engine: Engine, settings: Settings) -> None:
        schedule = read_schedule(settings.JOBTOLOGY_PIPELINE_SCHEDULE)
        for entry in schedule.sources:
            state = source_state(engine, entry.source_id)
            json_event(
                {
                    "source_id": entry.source_id,
                    "interval_seconds": entry.interval_seconds,
                    "time_due": due(state, datetime.now(UTC)),
                    "sync": state,
                }
            )

    _execute(action)


@pipeline_app.command("update")
def update(
    neo4j: bool = typer.Option(False, "--neo4j", help="Also load Neo4j STAGING batches"),
) -> None:
    """Run one due-source tick. Suitable for cron/Coolify; overlapping invocations exit 75."""

    def action(engine: Engine, settings: Settings) -> None:
        results = update_sources(
            engine,
            settings,
            read_schedule(settings.JOBTOLOGY_PIPELINE_SCHEDULE),
            emit=json_event,
            neo4j=neo4j,
        )
        if any(row["state"] in {"FAILED", "RETRY_WAIT"} for row in results):
            raise typer.Exit(code=1)

    _execute(action)


@pipeline_app.command("worker")
def worker(
    poll_seconds: int = typer.Option(60, min=15, max=3600),
    neo4j: bool = typer.Option(False, "--neo4j"),
) -> None:
    """Optional foreground polling process. SIGTERM/SIGINT stop after the current source tick."""
    stop = threading.Event()

    def stop_worker(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous: dict[signal.Signals, Any] = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, stop_worker)
    try:
        while not stop.is_set():
            try:
                update(neo4j=neo4j)
            except typer.Exit as error:
                typer.echo(
                    json.dumps({"event": "tick_failed", "exit_code": error.exit_code}), err=True
                )
            # Event.wait wakes immediately on shutdown. It is not a scheduler-state store.
            remaining = poll_seconds
            while remaining > 0 and not stop.is_set():
                stop.wait(min(remaining, 60))
                remaining -= 60
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
