"""Transactional, append-only-by-API canonical storage. Does not publish a corpus release."""

from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any

from sqlalchemy import Connection, Engine, text

from jobtology_db.contracts.bundle import CanonicalBundle
from jobtology_db.contracts.canonical import JobPosting


def _immutable(connection: Connection, table: str, key: str, row: dict[str, Any]) -> None:
    # Table/column names come exclusively from the fixed calls below, never from input records.
    columns = ",".join(row)
    values = ",".join("CAST(:record AS jsonb)" if c == "record" else f":{c}" for c in row)
    params = {**row, "record": json.dumps(row["record"], ensure_ascii=False)}
    inserted = connection.execute(
        text(
            f"INSERT INTO {table} ({columns}) VALUES ({values}) "
            f"ON CONFLICT DO NOTHING RETURNING {key}"
        ),
        params,
    ).scalar_one_or_none()
    if inserted is None:
        existing = connection.execute(
            text(f"SELECT record FROM {table} WHERE {key}=:key"),
            {"key": row[key]},
        ).scalar_one_or_none()
        if existing != row["record"]:
            raise ValueError("IMMUTABLE_CANONICAL_RECORD_CONFLICT")


class CanonicalStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(
        self,
        bundle: CanonicalBundle,
        observations: dict[str, list[str]],
        *,
        transaction: Connection | None = None,
    ) -> None:
        # Frozen Pydantic models still contain lists; revalidate at the persistence boundary.
        bundle = CanonicalBundle.model_validate_json(bundle.model_dump_json())
        if set(observations) != {d.document_id for d in bundle.documents}:
            raise ValueError("DOCUMENT_OBSERVATION_BINDINGS_REQUIRED")
        with self.engine.begin() if transaction is None else nullcontext(transaction) as connection:
            for document in bundle.documents:
                ids = observations[document.document_id]
                if not ids or len(set(ids)) != len(ids):
                    raise ValueError("DOCUMENT_OBSERVATION_BINDINGS_REQUIRED")
                matches = connection.execute(
                    text("""
                    SELECT o.observation_id FROM raw_manifest.fetch_observation o
                    JOIN raw_manifest.source_snapshot s ON s.snapshot_id=o.snapshot_id
                    WHERE o.observation_id=ANY(:ids) AND s.snapshot_id=:snapshot
                      AND s.source_id=:source AND o.source_id=:source
                      AND o.outcome='SELECTED_SUCCESS'
                """),
                    {"ids": ids, "snapshot": document.snapshot_id, "source": document.source_id},
                )
                if set(matches.scalars()) != set(ids):
                    raise ValueError("OBSERVATION_SOURCE_SNAPSHOT_MISMATCH")
                _immutable(
                    connection,
                    "grounding.document",
                    "document_id",
                    {
                        "document_id": document.document_id,
                        "snapshot_id": document.snapshot_id,
                        "source_id": document.source_id,
                        "source_record_id": document.source_record_id,
                        "parser_version": document.parser_version,
                        "record": document.model_dump(mode="json"),
                    },
                )
                for observation_id in ids:
                    connection.execute(
                        text("""
                        INSERT INTO grounding.document_observation VALUES (:document,:observation)
                        ON CONFLICT DO NOTHING
                    """),
                        {"document": document.document_id, "observation": observation_id},
                    )
                for block in document.blocks:
                    connection.execute(
                        text("""
                        INSERT INTO grounding.text_block
                        VALUES (:document,:block,:locator,:text,:sha)
                        ON CONFLICT DO NOTHING
                    """),
                        {
                            "document": document.document_id,
                            "block": block.block_id,
                            "locator": block.locator,
                            "text": block.text,
                            "sha": block.sha256,
                        },
                    )
            for entity in bundle.identities:
                _immutable(
                    connection,
                    "canonical.entity",
                    "entity_id",
                    {
                        **entity.model_dump(mode="json"),
                        "record": entity.model_dump(mode="json"),
                    },
                )
            for span in bundle.evidence:
                _immutable(
                    connection,
                    "grounding.evidence_span",
                    "evidence_id",
                    {
                        "evidence_id": span.evidence_id,
                        "document_id": span.document_id,
                        "block_id": span.block_id,
                        "start_offset": span.start,
                        "end_offset": span.end,
                        "excerpt": span.excerpt,
                        "record": span.model_dump(mode="json"),
                    },
                )
            for revision in bundle.revisions:
                value = revision.payload
                name = value.title if isinstance(value, JobPosting) else value.name_ko
                _immutable(
                    connection,
                    "canonical.revision",
                    "revision_id",
                    {
                        "revision_id": revision.revision_id,
                        "entity_id": revision.entity_id,
                        "kind": value.kind,
                        "display_name": name,
                        "record": revision.model_dump(mode="json"),
                    },
                )
                for document_id in revision.document_ids:
                    connection.execute(
                        text("""
                        INSERT INTO canonical.revision_document VALUES (:revision,:document)
                        ON CONFLICT DO NOTHING
                    """),
                        {"revision": revision.revision_id, "document": document_id},
                    )
                for support in revision.field_support:
                    for evidence_id in support.evidence_ids:
                        connection.execute(
                            text("""
                            INSERT INTO canonical.field_evidence VALUES (:revision,:field,:evidence)
                            ON CONFLICT DO NOTHING
                        """),
                            {
                                "revision": revision.revision_id,
                                "field": support.field,
                                "evidence": evidence_id,
                            },
                        )
            for extraction in bundle.extractions:
                _immutable(
                    connection,
                    "grounding.extraction",
                    "extraction_id",
                    {
                        "extraction_id": extraction.extraction_id,
                        "document_id": extraction.document_id,
                        "record": extraction.model_dump(mode="json"),
                    },
                )
            for claim in bundle.claims:
                _immutable(
                    connection,
                    "grounding.requirement_claim",
                    "claim_id",
                    {
                        "claim_id": claim.claim_id,
                        "subject_revision_id": claim.subject_revision_id,
                        "extraction_id": claim.extraction_id,
                        "kind": claim.kind,
                        "review_status": claim.review.status,
                        "record": claim.model_dump(mode="json"),
                    },
                )
                for evidence_id in claim.evidence_ids:
                    connection.execute(
                        text("""
                        INSERT INTO grounding.claim_evidence VALUES (:claim,:evidence)
                        ON CONFLICT DO NOTHING
                    """),
                        {"claim": claim.claim_id, "evidence": evidence_id},
                    )
