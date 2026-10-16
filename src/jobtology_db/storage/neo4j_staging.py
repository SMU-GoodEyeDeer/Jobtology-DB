from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine

from jobtology_db.contracts.processing import (
    CareerPath,
    Competency,
    ExamSession,
    JobPosting,
    Organization,
    QualificationMapping,
    Record,
)
from jobtology_db.processing.sources import ProcessingError
from jobtology_db.settings import Settings

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


def require_native_graph_publisher() -> None:
    """Fail before I/O: legacy processing evidence cannot prove the Hop contract."""
    raise ProcessingError("LEGACY_NEO4J_PUBLISHER_RETIRED")


def load_neo4j_staging(
    engine: Engine, settings: Settings, processing_run_id: str
) -> dict[str, Any]:
    """Retired. Publish accepted ingestion runs through hop/graph/load_snapshot.hwf.

    The Python control.processing_run ledger has a different source contract and
    cannot establish batch-free PostgreSQL source projection evidence. Keep this
    callable fail-closed for existing CLI and API callers; it performs no I/O.
    """
    require_native_graph_publisher()
    raise AssertionError("unreachable")
