from __future__ import annotations

import json
from typing import Any

from neo4j import GraphDatabase, ManagedTransaction
from sqlalchemy import Engine, text

from jobtology_db.contracts.processing import (
    CareerPath,
    Competency,
    ExamSession,
    JobPosting,
    Organization,
    QualificationMapping,
    Record,
    digest,
)
from jobtology_db.pipeline.process import process_run
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings
from jobtology_db.storage.processing import StagingLoader, advisory_lock, lock_key

LOADER_VERSION = "neo4j-staging-v1"


def graph_record(revision_id: str, source: str, record: Record) -> dict[str, Any]:
    """Only typed structured fields. Free text, raw JSON, and contact data remain in PostgreSQL."""
    value = record.normalized
    refs: list[dict[str, str]] = []

    def ref(kind: str, namespace: str, code: str, field: str) -> None:
        refs.append({"id": f"{namespace}:{code}", "kind": kind, "code": code, "field": field})

    if isinstance(value, CareerPath):
        name = value.occupation_name
        ref("Occupation", "ncs:occupation", value.occupation_code, "occupation_code")
        # An unversioned CSV unit is not silently merged with a versioned NCS API unit.
        ref("Competency", "ncs:unversioned-unit", value.competency_code, "competency_code")
    elif isinstance(value, Competency):
        name = value.name
        ref("Competency", "ncs:unit", value.code, "code")
        ref("Occupation", "ncs:occupation", value.occupation_code, "occupation_code")
    elif isinstance(value, QualificationMapping):
        name = value.qualification_name
        ref("Qualification", "qnet:qualification", value.qualification_code, "qualification_code")
        ref("Competency", "ncs:unit", value.competency_code, "competency_code")
    elif isinstance(value, ExamSession):
        name = value.name
        ref("Qualification", "qnet:qualification", value.qualification_code, "qualification_code")
    elif isinstance(value, Organization):
        name = value.name
        ref("Organization", "alio:organization", value.code, "code")
    else:
        assert isinstance(value, JobPosting)
        name = value.title
        ref("Organization", "alio:organization", value.organization_code, "organization_code")
        ref("JobPosting", "job-alio:posting", value.posting_id, "posting_id")
    facts = value.model_dump(mode="json")
    for field in (
        "definition",
        "eligibility_text",
        "disqualification_text",
        "preference_text",
        "selection_text",
        "address",
        "website",
        "source_url",
    ):
        facts.pop(field, None)
    return {
        "id": revision_id,
        "source_id": source,
        "source_record_id": record.source_record_id,
        "kind": value.kind,
        "name": name,
        "facts_json": json.dumps(facts, ensure_ascii=False),
        "lineage_json": json.dumps(record.field_lineage, ensure_ascii=False),
        "refs": refs,
    }


def _write_batch(tx: ManagedTransaction, batch_id: str, rows: list[dict[str, Any]]) -> None:
    tx.run(
        """
        MATCH (b:IngestBatch {id:$batch})
        UNWIND $rows AS row
        MERGE (r:IngestRecord {id:row.id})
        ON CREATE SET r.source_id=row.source_id, r.source_record_id=row.source_record_id,
                      r.kind=row.kind, r.name=row.name, r.facts_json=row.facts_json,
                      r.lineage_json=row.lineage_json
        MERGE (b)-[:HAS_RECORD]->(r)
        WITH r,row
        UNWIND row.refs AS ref
        MERGE (i:IngestIdentity {id:ref.id})
        ON CREATE SET i.kind=ref.kind, i.code=ref.code
        MERGE (r)-[:REFERS_TO {field:ref.field}]->(i)
    """,
        batch=batch_id,
        rows=rows,
    ).consume()


def load_neo4j_staging(
    engine: Engine, settings: Settings, processing_run_id: str
) -> dict[str, Any]:
    uri, password = (
        settings.JOBTOLOGY_NEO4J_URI,
        settings.secret_value(settings.JOBTOLOGY_NEO4J_PASSWORD),
    )
    if not uri or not password:
        raise ProcessingError("NEO4J_CONFIGURATION_REQUIRED")
    with engine.connect() as c:
        row = (
            c.execute(
                text("""
            SELECT connector_run_id,state FROM control.processing_run WHERE processing_run_id=:id
        """),
                {"id": processing_run_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None or row["state"] != "READY":
        raise ProcessingError("PROCESSING_NOT_READY")
    # Re-check bytes, current rights, and completeness immediately before an external load.
    summary = process_run(engine, settings.JOBTOLOGY_RAW_ROOT, row["connector_run_id"], settings)
    if summary.state != "READY" or summary.processing_run_id != processing_run_id:
        raise ProcessingError("PROCESSING_NOT_READY")
    target = digest([uri, settings.JOBTOLOGY_NEO4J_DATABASE])
    batch_id = digest([processing_run_id, LOADER_VERSION])
    params = {"id": processing_run_id, "target": target, "version": LOADER_VERSION}
    with advisory_lock(engine, lock_key(f"graph:{target}:{batch_id}")):
        with engine.begin() as c:
            c.execute(
                text("""
                INSERT INTO control.graph_load VALUES (:id,:target,:version,'RUNNING',NULL)
                ON CONFLICT (processing_run_id,target_hash,loader_version)
                DO UPDATE SET state='RUNNING', completed_at=NULL
            """),
                params,
            )
        try:
            with GraphDatabase.driver(  # pyright: ignore[reportUnknownMemberType]
                uri,
                auth=(settings.JOBTOLOGY_NEO4J_USERNAME, password),
                connection_timeout=10,
                max_transaction_retry_time=30,
            ) as driver:
                driver.verify_connectivity()  # pyright: ignore[reportUnknownMemberType]
                with driver.session(  # pyright: ignore[reportUnknownMemberType]
                    database=settings.JOBTOLOGY_NEO4J_DATABASE
                ) as session:
                    for label in ("IngestBatch", "IngestRecord", "IngestIdentity"):
                        session.run(
                            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                            "REQUIRE n.id IS UNIQUE"
                        ).consume()
                    session.run(
                        """
                        MERGE (b:IngestBatch {id:$id})
                        ON CREATE SET b.processing_run_id=$run, b.source_id=$source,
                                      b.content_set_hash=$hash
                        SET b.state='LOADING', b.serving_scope='STAGING'
                    """,
                        id=batch_id,
                        run=processing_run_id,
                        source=summary.source_id,
                        hash=summary.content_set_hash,
                    ).consume()
                    batch: list[dict[str, Any]] = []
                    for revision, record in StagingLoader(engine).records(processing_run_id):
                        batch.append(graph_record(revision, summary.source_id, record))
                        if len(batch) >= 250:
                            session.execute_write(_write_batch, batch_id, batch)
                            batch = []
                    if batch:
                        session.execute_write(_write_batch, batch_id, batch)
                    actual = [
                        str(r["id"])
                        for r in session.run(
                            """
                        MATCH (:IngestBatch {id:$id})-[:HAS_RECORD]->(r:IngestRecord)
                        RETURN r.id AS id ORDER BY id
                    """,
                            id=batch_id,
                        )
                    ]
                    if len(actual) != summary.records or digest(actual) != summary.content_set_hash:
                        raise ProcessingError("GRAPH_MANIFEST_MISMATCH")
                    session.run(
                        "MATCH (b:IngestBatch {id:$id}) SET b.state='READY'", id=batch_id
                    ).consume()
            with engine.begin() as c:
                c.execute(
                    text("""
                    UPDATE control.graph_load SET state='READY',completed_at=CURRENT_TIMESTAMP
                    WHERE processing_run_id=:id AND target_hash=:target AND loader_version=:version
                """),
                    params,
                )
        except Exception as error:
            with engine.begin() as c:
                c.execute(
                    text("""
                    UPDATE control.graph_load SET state='FAILED'
                    WHERE processing_run_id=:id AND target_hash=:target AND loader_version=:version
                """),
                    params,
                )
            raise ProcessingError("GRAPH_LOAD_FAILED") from error
    return {
        "batch_id": batch_id,
        "state": "READY",
        "serving_scope": "STAGING",
        "records": summary.records,
    }
