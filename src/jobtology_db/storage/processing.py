from __future__ import annotations

import hashlib
import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, text

from jobtology_db.contracts.processing import ParsedDocument, Record, digest
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.storage.ledger import stable_id_set_hash

GLOBAL_UPDATE_LOCK = 74120260904


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    observation_id: str
    snapshot_id: str
    partition_id: str
    page_number: int | None
    response_ordinal: int
    retrieved_at: datetime
    raw_object_path: str
    content_sha256: str
    byte_length: int
    mime_type: str


def lock_key(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)


@contextmanager
def advisory_lock(engine: Engine, key: int) -> Generator[Connection]:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        if not acquired:
            raise ProcessingError("PIPELINE_BUSY")
        try:
            yield connection
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


def run_inputs(engine: Engine, run_id: str) -> tuple[dict[str, Any], list[SnapshotInput]]:
    with engine.connect() as c:
        row = (
            c.execute(
                text("SELECT * FROM control.connector_run WHERE connector_run_id=:id"),
                {"id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProcessingError("RUN_NOT_FOUND")
        run = dict(row)
        if (
            run["state"] not in {"RUNNING", "SUCCEEDED"}
            or run["fetch_completed_at"] is None
            or run["stage"] != "FETCHED"
            or not run["planned_request_count"]
            or run["planned_request_count"] != run["successful_request_count"]
        ):
            raise ProcessingError("FETCH_NOT_COMPLETE")
        inputs = [
            SnapshotInput.model_validate(dict(item))
            for item in c.execute(
                text("""
            SELECT r.partition_id, r.page_number, o.observation_id, o.response_ordinal,
                   o.retrieved_at, s.*
            FROM control.connector_request r
            JOIN raw_manifest.fetch_observation o
              ON o.observation_id=r.selected_observation_id
             AND o.connector_run_id=r.connector_run_id
             AND o.request_fingerprint=r.request_fingerprint
            JOIN raw_manifest.source_snapshot s ON s.snapshot_id=o.snapshot_id
            WHERE r.connector_run_id=:id AND o.selected IS TRUE
              AND o.outcome='SELECTED_SUCCESS' AND o.source_id=:source AND s.source_id=:source
            ORDER BY r.partition_id, r.page_number NULLS LAST, o.response_ordinal
        """),
                {"id": run_id, "source": run["source_id"]},
            ).mappings()
        ]
        attempts = list(
            c.execute(
                text("""
            SELECT observation_id FROM raw_manifest.fetch_observation WHERE connector_run_id=:id
        """),
                {"id": run_id},
            ).scalars()
        )
        request_count = c.scalar(
            text("""
            SELECT count(*) FROM control.connector_request WHERE connector_run_id=:id
        """),
            {"id": run_id},
        )
    if (
        len(inputs) != run["successful_request_count"]
        or request_count != len(inputs)
        or stable_id_set_hash([i.observation_id for i in inputs])
        != run["selected_success_observation_set_hash"]
        or stable_id_set_hash(attempts) != run["all_attempt_observation_set_hash"]
    ):
        raise ProcessingError("FETCH_MANIFEST_MISMATCH")
    return run, inputs


def read_raw(root: Path, item: SnapshotInput) -> bytes:
    root = root.resolve()
    path = (root / item.raw_object_path).resolve()
    if not path.is_relative_to(root):
        raise ProcessingError("RAW_PATH_ESCAPE")
    try:
        body = path.read_bytes()
    except OSError as error:
        raise ProcessingError("RAW_UNAVAILABLE") from error
    if len(body) != item.byte_length or hashlib.sha256(body).hexdigest() != item.content_sha256:
        raise ProcessingError("RAW_INTEGRITY_FAILED")
    return body


class StagingLoader:
    """One atomic checkpoint per document; revisions are immutable and content-deduplicated."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def cached(self, document_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            result = c.scalar(
                text("SELECT metadata FROM staging.document WHERE document_id=:id"),
                {"id": document_id},
            )
            return result

    def save(
        self,
        source: str,
        item: SnapshotInput,
        version: str,
        document_id: str,
        parsed: ParsedDocument,
    ) -> int:
        new_count = 0
        metadata = parsed.model_dump(mode="json", exclude={"records", "rejected"})
        metadata["rejected_count"] = len(parsed.rejected)
        metadata["identities"] = [row.record.source_record_id for row in parsed.records]
        with self.engine.begin() as c:
            c.execute(
                text("""
                INSERT INTO staging.document VALUES (:id,:source,:snapshot,:partition,:version,
                                                      CAST(:metadata AS jsonb))
            """),
                {
                    "id": document_id,
                    "source": source,
                    "snapshot": item.snapshot_id,
                    "partition": item.partition_id,
                    "version": version,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )
            batch: list[dict[str, Any]] = []
            for row in parsed.records:
                value = row.record.model_dump(mode="json")
                batch.append(
                    {
                        "id": digest([source, version, value]),
                        "identity": row.record.source_record_id,
                        "kind": row.record.normalized.kind,
                        "record": value,
                        "locator": row.locator,
                    }
                )
            if batch:
                encoded = json.dumps(batch, ensure_ascii=False)
                new_count = int(
                    c.scalar(
                        text("""
                    WITH inserted AS (
                        INSERT INTO staging.record_revision
                            (revision_id,source_id,source_record_id,kind,processor_version,record)
                        SELECT b.id,:source,b.identity,b.kind,:version,b.record
                        FROM jsonb_to_recordset(CAST(:batch AS jsonb))
                            AS b(id text, identity text, kind text, record jsonb)
                        ON CONFLICT (revision_id) DO NOTHING RETURNING revision_id
                    ) SELECT count(*) FROM inserted
                """),
                        {"source": source, "version": version, "batch": encoded},
                    )
                    or 0
                )
                c.execute(
                    text("""
                    INSERT INTO staging.document_record
                    SELECT :doc,b.locator,b.id FROM jsonb_to_recordset(CAST(:batch AS jsonb))
                        AS b(id text, locator text)
                """),
                    {"doc": document_id, "batch": encoded},
                )
            if parsed.rejected:
                c.execute(
                    text("""
                    INSERT INTO quality.rejected_row
                    VALUES (:doc,:loc,:code,CAST(:payload AS jsonb))
                """),
                    [
                        {
                            "doc": document_id,
                            "loc": row.locator,
                            "code": row.error_code,
                            "payload": json.dumps(row.source_payload, ensure_ascii=False),
                        }
                        for row in parsed.rejected
                    ],
                )
        return new_count

    def attach(self, run_id: str, observation_id: str, document_id: str) -> None:
        with self.engine.begin() as c:
            c.execute(
                text("""
                INSERT INTO control.processing_input VALUES (:run,:observation,:doc)
                ON CONFLICT DO NOTHING
            """),
                {"run": run_id, "observation": observation_id, "doc": document_id},
            )

    def records(self, processing_run_id: str) -> Iterator[tuple[str, Record]]:
        with self.engine.connect() as c:
            rows = c.execute(
                text("""
                SELECT DISTINCT r.revision_id, r.record, r.source_id, r.processor_version
                FROM control.processing_input i
                JOIN staging.document_record d ON d.document_id=i.document_id
                JOIN staging.record_revision r ON r.revision_id=d.revision_id
                WHERE i.processing_run_id=:id ORDER BY r.revision_id
            """),
                {"id": processing_run_id},
            ).mappings()
            for row in rows:
                record = Record.model_validate(row["record"])
                if (
                    digest(
                        [row["source_id"], row["processor_version"], record.model_dump(mode="json")]
                    )
                    != row["revision_id"]
                ):
                    raise ProcessingError("STAGING_REVISION_INTEGRITY_FAILED")
                yield row["revision_id"], record
