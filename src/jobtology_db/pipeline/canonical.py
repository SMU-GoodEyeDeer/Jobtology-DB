"""Offline, checkpointed staging -> canonical PostgreSQL assembly. No graph publication."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sqlalchemy import Engine, text

from jobtology_db.contracts.processing import (
    PROCESSABLE_SOURCES,
    PROCESSOR_VERSION,
    JobPosting,
    Record,
    digest,
)
from jobtology_db.pipeline.process import process_run
from jobtology_db.processing.assembly import (
    ASSEMBLER_VERSION,
    StagedOccurrence,
    assemble,
    document_bindings,
)
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings
from jobtology_db.storage.canonical import CanonicalStore
from jobtology_db.storage.processing import advisory_lock, lock_key


def _failed(engine: Engine, run_id: str, error: Exception) -> None:
    code = str(error) if isinstance(error, ProcessingError) else type(error).__name__
    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE control.canonical_run SET state='FAILED',error_code=:code,
                completed_at=CURRENT_TIMESTAMP WHERE assembly_run_id=:id
        """),
            {"id": run_id, "code": code[:100]},
        )


def latest_processing_runs(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
            SELECT DISTINCT ON (c.source_id) c.source_id,p.processing_run_id
            FROM control.processing_run p JOIN control.connector_run c USING(connector_run_id)
            WHERE p.state='READY' AND p.processor_version=:version AND c.mode='SCHEDULED_FULL'
            ORDER BY c.source_id,c.fetch_completed_at DESC,p.processing_run_id
        """),
            {"version": PROCESSOR_VERSION},
        ).mappings()
        selected = {row["source_id"]: row["processing_run_id"] for row in rows}
    if not set(PROCESSABLE_SOURCES) <= selected.keys():
        raise ProcessingError("MISSING_READY_PROCESSING_RUN")
    return [selected[source] for source in PROCESSABLE_SOURCES]


def staged_occurrences(engine: Engine, processing_run_id: str) -> list[StagedOccurrence]:
    occurrences: dict[tuple[str, str, str], StagedOccurrence] = {}
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
            SELECT r.revision_id,r.record,r.source_id,r.processor_version,
                   d.snapshot_id,dr.locator,i.observation_id
            FROM control.processing_input i
            JOIN staging.document d ON d.document_id=i.document_id
            JOIN staging.document_record dr ON dr.document_id=d.document_id
            JOIN staging.record_revision r ON r.revision_id=dr.revision_id
            WHERE i.processing_run_id=:id
            ORDER BY r.revision_id,d.snapshot_id,dr.locator,i.observation_id
        """),
            {"id": processing_run_id},
        ).mappings()
        for row in rows:
            record = Record.model_validate(row["record"])
            if row["revision_id"] != digest(
                [
                    row["source_id"],
                    row["processor_version"],
                    record.model_dump(mode="json"),
                ]
            ):
                raise ProcessingError("STAGING_REVISION_INTEGRITY_FAILED")
            key = (row["revision_id"], row["snapshot_id"], row["locator"])
            existing = occurrences.get(key)
            if existing is None:
                occurrences[key] = StagedOccurrence(
                    revision_id=row["revision_id"],
                    source_id=row["source_id"],
                    snapshot_id=row["snapshot_id"],
                    locator=row["locator"],
                    parser_version=row["processor_version"],
                    record=record,
                    observation_ids=(row["observation_id"],),
                )
            else:
                occurrences[key] = replace(
                    existing,
                    observation_ids=(
                        *existing.observation_ids,
                        row["observation_id"],
                    ),
                )
    return list(occurrences.values())


def assemble_run(
    engine: Engine,
    settings: Settings,
    processing_run_id: str,
    *,
    emit: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    run_id = digest([processing_run_id, ASSEMBLER_VERSION])
    with advisory_lock(engine, lock_key(f"canonical:{run_id}")):
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text("""
                SELECT connector_run_id,state FROM control.processing_run
                WHERE processing_run_id=:id
            """),
                    {"id": processing_run_id},
                )
                .mappings()
                .one_or_none()
            )
        try:
            if row is None or row["state"] != "READY":
                raise ProcessingError("PROCESSING_NOT_READY")
            # Reuse source rights, raw hash, completeness and pairing checks. No upstream requests.
            verified = process_run(
                engine, settings.JOBTOLOGY_RAW_ROOT, row["connector_run_id"], settings
            )
            if verified.state != "READY" or verified.processing_run_id != processing_run_id:
                raise ProcessingError("PROCESSING_NOT_READY")
            inputs = staged_occurrences(engine, processing_run_id)
            input_ids = sorted({item.revision_id for item in inputs})
            if len(input_ids) != verified.records or digest(input_ids) != verified.content_set_hash:
                raise ProcessingError("CANONICAL_INPUT_MANIFEST_MISMATCH")
        except Exception as error:
            _failed(engine, run_id, error)
            raise
        groups: dict[str, list[StagedOccurrence]] = defaultdict(list)
        for item in inputs:
            value = item.record.normalized
            key = (
                value.posting_id
                if isinstance(value, JobPosting)
                else digest(
                    [
                        item.revision_id,
                        item.snapshot_id,
                        item.locator,
                    ]
                )
            )
            groups[key].append(item)
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO control.canonical_run
                    (assembly_run_id,processing_run_id,assembler_version,state)
                VALUES (:id,:processing,:version,'RUNNING')
                ON CONFLICT (assembly_run_id) DO UPDATE
                    SET state='RUNNING',completed_at=NULL,error_code=NULL
            """),
                {"id": run_id, "processing": processing_run_id, "version": ASSEMBLER_VERSION},
            )
        store = CanonicalStore(engine)
        reused = 0
        try:
            for number, (item_key, items) in enumerate(sorted(groups.items()), start=1):
                bundle = assemble(items)
                bundle_hash = digest(bundle.model_dump(mode="json"))
                with engine.begin() as connection:
                    previous = connection.scalar(
                        text("""
                        SELECT bundle_hash FROM canonical.assembly_item
                        WHERE assembly_run_id=:id AND item_id=:item
                    """),
                        {"id": run_id, "item": item_key},
                    )
                    if previous is not None:
                        if previous != bundle_hash:
                            raise ProcessingError("ASSEMBLER_VERSION_CONTENT_CONFLICT")
                        reused += 1
                    else:
                        store.save(bundle, document_bindings(bundle, items), transaction=connection)
                        for document, item in zip(bundle.documents, items, strict=True):
                            connection.execute(
                                text("""
                                INSERT INTO canonical.assembly_input VALUES (:id,:staging,:document)
                                ON CONFLICT DO NOTHING
                            """),
                                {
                                    "id": run_id,
                                    "staging": item.revision_id,
                                    "document": document.document_id,
                                },
                            )
                        for revision in bundle.revisions:
                            connection.execute(
                                text("""
                                INSERT INTO canonical.assembly_revision VALUES (:id,:revision)
                                ON CONFLICT DO NOTHING
                            """),
                                {"id": run_id, "revision": revision.revision_id},
                            )
                        connection.execute(
                            text("""
                            INSERT INTO canonical.assembly_item VALUES (:id,:item,:hash)
                        """),
                            {"id": run_id, "item": item_key, "hash": bundle_hash},
                        )
                if emit and (number % 500 == 0 or number == len(groups)):
                    emit(
                        {
                            "event": "canonical_progress",
                            "source_id": verified.source_id,
                            "items": number,
                            "total_items": len(groups),
                            "reused_items": reused,
                        }
                    )
            with engine.begin() as connection:
                actual_inputs = list(
                    connection.execute(
                        text("""
                    SELECT DISTINCT staging_revision_id FROM canonical.assembly_input
                    WHERE assembly_run_id=:id ORDER BY staging_revision_id
                """),
                        {"id": run_id},
                    ).scalars()
                )
                if actual_inputs != input_ids:
                    raise ProcessingError("CANONICAL_OUTPUT_MANIFEST_MISMATCH")
                revision_ids = list(
                    connection.execute(
                        text("""
                    SELECT revision_id FROM canonical.assembly_revision
                    WHERE assembly_run_id=:id ORDER BY revision_id
                """),
                        {"id": run_id},
                    ).scalars()
                )
                counts = connection.execute(
                    text("""
                    SELECT r.kind,count(*) FROM canonical.assembly_revision a
                    JOIN canonical.revision r USING(revision_id)
                    WHERE a.assembly_run_id=:id GROUP BY r.kind ORDER BY r.kind
                """),
                    {"id": run_id},
                ).all()
                summary = {
                    "assembly_run_id": run_id,
                    "processing_run_id": processing_run_id,
                    "source_id": verified.source_id,
                    "assembler_version": ASSEMBLER_VERSION,
                    "state": "READY",
                    "serving_scope": "DRAFT",
                    "input_records": len(input_ids),
                    "items": len(groups),
                    "reused_items": reused,
                    "revisions": len(revision_ids),
                    "revision_counts": {str(row[0]): int(row[1]) for row in counts},
                    "revision_set_hash": digest(revision_ids),
                    "input_set_hash": digest(input_ids),
                }
                connection.execute(
                    text("""
                    UPDATE control.canonical_run SET state='READY',completed_at=CURRENT_TIMESTAMP,
                        summary=CAST(:summary AS jsonb) WHERE assembly_run_id=:id
                """),
                    {"id": run_id, "summary": json.dumps(summary)},
                )
            return summary
        except Exception as error:
            _failed(engine, run_id, error)
            raise
