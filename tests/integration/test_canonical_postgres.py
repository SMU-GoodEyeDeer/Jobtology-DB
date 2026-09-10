"""Canonical storage tests use only the explicitly configured disposable test databases."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import uuid4

import pytest
from neo4j import GraphDatabase
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from jobtology_db.contracts.bundle import CanonicalBundle
from jobtology_db.contracts.canonical import EntityIdentity
from jobtology_db.pipeline.canonical import assemble_run
from jobtology_db.pipeline.process import process_run
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.storage.canonical import CanonicalStore
from jobtology_db.storage.ontology_schema import neo4j_constraints
from jobtology_db.storage.processing import run_inputs
from tests.integration.test_processing_postgres import (
    engine as engine,  # Shared opt-in *_test database safety check and migration fixture.
)
from tests.integration.test_processing_postgres import (
    fetch_fixture,
    organization_document,
    settings_for,
)
from tests.unit.test_canonical_contracts import bundle_fixture, document_fixture


def saved_bundle(engine: Engine, tmp_path: Path) -> tuple[CanonicalBundle, dict[str, list[str]]]:
    payload = organization_document(str(uuid4()), description=document_fixture().blocks[0].text)
    run = fetch_fixture(engine, settings_for(engine, tmp_path), payload)
    _, inputs = run_inputs(engine, run)
    bundle = bundle_fixture(inputs[0].snapshot_id, "alio_organization")
    return bundle, {bundle.documents[0].document_id: [inputs[0].observation_id]}


def test_canonical_store_roundtrip_search_and_replay(engine: Engine, tmp_path: Path) -> None:
    bundle, observations = saved_bundle(engine, tmp_path)
    store = CanonicalStore(engine)
    store.save(bundle, observations)
    store.save(bundle, observations)
    revision = bundle.revisions[0]
    with engine.connect() as connection:
        stored = connection.execute(
            text("""
            SELECT record FROM canonical.revision WHERE revision_id=:id
        """),
            {"id": revision.revision_id},
        ).scalar_one()
        assert stored == revision.model_dump(mode="json")
        assert (
            connection.execute(
                text("""
            SELECT count(*) FROM grounding.requirement_claim WHERE subject_revision_id=:id
        """),
                {"id": revision.revision_id},
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("""
            SELECT count(*) FROM grounding.text_block WHERE document_id=:id
              AND to_tsvector('simple',text) @@ plainto_tsquery('simple','Python')
        """),
                {"id": bundle.documents[0].document_id},
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("""
            SELECT count(*) FROM grounding.claim_evidence ce
            JOIN grounding.evidence_span e USING(evidence_id)
            JOIN grounding.document_observation d USING(document_id)
            JOIN raw_manifest.fetch_observation o USING(observation_id)
            WHERE ce.claim_id=:id AND o.snapshot_id=:snapshot
        """),
                {"id": bundle.claims[0].claim_id, "snapshot": bundle.documents[0].snapshot_id},
            ).scalar_one()
            == 1
        )


def test_canonical_store_rejects_wrong_observation_atomically(
    engine: Engine, tmp_path: Path
) -> None:
    bundle, _ = saved_bundle(engine, tmp_path)
    _, other = saved_bundle(engine, tmp_path)
    wrong = {bundle.documents[0].document_id: next(iter(other.values()))}
    with pytest.raises(ValueError, match="OBSERVATION_SOURCE_SNAPSHOT_MISMATCH"):
        CanonicalStore(engine).save(bundle, wrong)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("""
            SELECT count(*) FROM grounding.document WHERE document_id=:id
        """),
                {"id": bundle.documents[0].document_id},
            ).scalar_one()
            == 0
        )


def test_identity_conflict_rolls_back_whole_bundle(engine: Engine, tmp_path: Path) -> None:
    first, observations = saved_bundle(engine, tmp_path)
    CanonicalStore(engine).save(first, observations)
    second, later_observations = saved_bundle(engine, tmp_path)
    existing = first.identities[0]
    conflict = EntityIdentity(
        entity_id=existing.entity_id,
        kind="JobPosting",
        namespace=existing.namespace,
        source_key="conflict",
    )
    # An extra identity collides after a new document was inserted in the transaction.
    second = CanonicalBundle.model_validate(
        {
            **second.model_dump(),
            "identities": [*second.identities, conflict],
        }
    )
    with pytest.raises(ValueError, match="IMMUTABLE_CANONICAL_RECORD_CONFLICT"):
        CanonicalStore(engine).save(second, later_observations)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("""
            SELECT count(*) FROM grounding.document WHERE document_id=:id
        """),
                {"id": second.documents[0].document_id},
            ).scalar_one()
            == 0
        )


def test_database_rejects_person_in_public_corpus(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO canonical.entity VALUES (:id,'Person','private',:id,'{}'::jsonb)
        """),
            {"id": str(uuid4())},
        )


def test_neo4j_canonical_constraints_are_idempotent() -> None:
    uri = os.environ.get("JOBTOLOGY_TEST_NEO4J_URI")
    password = os.environ.get("JOBTOLOGY_TEST_NEO4J_PASSWORD")
    if not uri or not password:
        pytest.skip("Explicit disposable Neo4j test credentials required")
    with (
        GraphDatabase.driver(uri, auth=("neo4j", password)) as driver,  # pyright: ignore[reportUnknownMemberType]
        driver.session() as session,  # pyright: ignore[reportUnknownMemberType]
    ):
        for _ in range(2):
            for statement in neo4j_constraints(include_person=True):
                session.run(cast(LiteralString, statement)).consume()
        names = {str(row["name"]) for row in session.run("SHOW CONSTRAINTS YIELD name RETURN name")}
        assert "jt_person_id" in names and "jt_corpusentity_id" in names


def test_assembly_end_to_end_replay_and_raw_integrity(engine: Engine, tmp_path: Path) -> None:
    settings = settings_for(engine, tmp_path)
    run = fetch_fixture(engine, settings, organization_document(str(uuid4())))
    processed = process_run(engine, tmp_path, run, settings)
    first = assemble_run(engine, settings, processed.processing_run_id)
    replay = assemble_run(engine, settings, processed.processing_run_id)
    assert first["revision_counts"] == {"Organization": 1}
    assert first["input_records"] == 1 and first["serving_scope"] == "DRAFT"
    assert replay["reused_items"] == 1 and replay["revision_set_hash"] == first["revision_set_hash"]
    _, inputs = run_inputs(engine, run)
    (tmp_path / inputs[0].raw_object_path).write_bytes(b"corrupt")
    with pytest.raises(ProcessingError, match="RAW_INTEGRITY_FAILED"):
        assemble_run(engine, settings, processed.processing_run_id)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("""
            SELECT state FROM control.canonical_run WHERE assembly_run_id=:id
        """),
                {"id": first["assembly_run_id"]},
            )
            == "FAILED"
        )


def test_assembly_resumes_atomic_items_after_interruption(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_for(engine, tmp_path)
    payload = {
        "resultCode": 200,
        "totalCount": 2,
        "result": [
            {"instCd": str(uuid4()), "instNm": "기관1"},
            {"instCd": str(uuid4()), "instNm": "기관2"},
        ],
    }
    run = fetch_fixture(engine, settings, payload)
    processed = process_run(engine, tmp_path, run, settings)
    original = CanonicalStore.save
    calls = 0

    def interrupted(self: CanonicalStore, *args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        original(self, *args, **kwargs)
        if calls == 2:
            raise RuntimeError("simulated interruption after save but before checkpoint")

    with monkeypatch.context() as scoped:
        scoped.setattr(CanonicalStore, "save", interrupted)
        with pytest.raises(RuntimeError, match="simulated interruption"):
            assemble_run(engine, settings, processed.processing_run_id)
    resumed = assemble_run(engine, settings, processed.processing_run_id)
    assert resumed["state"] == "READY" and resumed["reused_items"] == 1
    assert resumed["revisions"] == 2 and resumed["input_records"] == 2
