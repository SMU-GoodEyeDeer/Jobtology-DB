from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from jobtology_db.connectors.sources import source_activation_check
from jobtology_db.contracts.processing import (
    PROCESSABLE_SOURCES,
    PROCESSOR_VERSION,
    JobPosting,
    ProcessingSummary,
    digest,
)
from jobtology_db.processing.sources import ProcessingError, parse_document
from jobtology_db.settings import Settings
from jobtology_db.storage.processing import (
    SnapshotInput,
    StagingLoader,
    advisory_lock,
    lock_key,
    read_raw,
    run_inputs,
)


def validate_completeness(
    source: str, documents: list[tuple[SnapshotInput, dict[str, Any]]]
) -> None:
    groups: dict[str, list[tuple[SnapshotInput, dict[str, Any]]]] = defaultdict(list)
    for item, meta in documents:
        groups[item.partition_id].append((item, meta))
    if source == "ncs_career_path" and (len(documents) != 1 or documents[0][1]["row_count"] < 1):
        raise ProcessingError("INVALID_SINGLE_FILE_RUN")
    for partition, pages in groups.items():
        identities = [identity for _, meta in pages for identity in meta["identities"]]
        if len(identities) != len(set(identities)):
            raise ProcessingError("DUPLICATE_SOURCE_IDENTITY")
        if source == "ncs_career_path":
            continue
        if source == "job_alio" and partition.startswith("detail-"):
            if len(pages) != 1 or pages[0][1]["row_count"] != 1:
                raise ProcessingError("INVALID_DETAIL_COUNT")
            continue
        totals = {meta["total"] for _, meta in pages}
        sizes = {meta["page_size"] for _, meta in pages}
        if len(totals) != 1 or len(sizes) != 1:
            raise ProcessingError("UNSTABLE_PAGINATION")
        total, size = next(iter(totals)), next(iter(sizes))
        if total == 0:
            if (
                len(pages) != 2
                or {i.response_ordinal for i, _ in pages} != {0, 1}
                or any(i.page_number != 1 or m["row_count"] != 0 for i, m in pages)
            ):
                raise ProcessingError("UNCONFIRMED_EMPTY_PARTITION")
            continue
        expected_pages = math.ceil(total / size)
        if len(pages) != expected_pages or {i.page_number for i, _ in pages} != set(
            range(1, expected_pages + 1)
        ):
            raise ProcessingError("MISSING_OR_DUPLICATE_PAGES")
        for item, meta in pages:
            if item.response_ordinal != 0 or meta["row_count"] != min(
                size, total - ((item.page_number or 1) - 1) * size
            ):
                raise ProcessingError("PAGE_ROW_COUNT_MISMATCH")
    if source == "job_alio":
        listed = {
            identity.removesuffix(":list")
            for partition, pages in groups.items()
            if not partition.startswith("detail-")
            for _, meta in pages
            for identity in meta["identities"]
        }
        detailed = {
            partition.removeprefix("detail-")
            for partition in groups
            if partition.startswith("detail-")
        }
        # Quarantined identities cannot prove completeness, so the run must not become READY.
        if not any(meta["rejected_count"] for _, meta in documents) and listed != detailed:
            raise ProcessingError("LIST_DETAIL_IDENTITY_MISMATCH")


def validate_posting_pairs(loader: StagingLoader, run_id: str) -> None:
    postings: dict[str, dict[str, JobPosting]] = defaultdict(dict)
    for _, record in loader.records(run_id):
        if isinstance(record.normalized, JobPosting):
            p = record.normalized
            postings[p.posting_id][p.representation] = p
    for pair in postings.values():
        if set(pair) != {"list", "detail"}:
            raise ProcessingError("LIST_DETAIL_IDENTITY_MISMATCH")
        left, right = pair["list"], pair["detail"]
        for field in ("title", "organization_code", "date_posted", "closing_date"):
            if getattr(left, field) != getattr(right, field):
                raise ProcessingError("LIST_DETAIL_FACT_CONFLICT")
        if right.ongoing is not None and left.ongoing != right.ongoing:
            raise ProcessingError("LIST_DETAIL_STATUS_CONFLICT")


def process_run(
    engine: Engine, raw_root: Path, connector_run_id: str, settings: Settings
) -> ProcessingSummary:
    run_id = digest([connector_run_id, PROCESSOR_VERSION])
    with advisory_lock(engine, lock_key(f"processing:{run_id}")):
        run, inputs = run_inputs(engine, connector_run_id)
        source = run["source_id"]
        if source not in PROCESSABLE_SOURCES:
            raise ProcessingError("UNSUPPORTED_SOURCE")
        rights = source_activation_check(source, settings)
        if not rights.allowed or rights.policy_hash != run["rights_policy_hash"]:
            raise ProcessingError("RIGHTS_POLICY_BLOCKED_OR_CHANGED")
        with engine.begin() as c:
            c.execute(
                text("""
                INSERT INTO control.processing_run
                    (processing_run_id,connector_run_id,processor_version,state)
                VALUES (:id,:connector,:version,'RUNNING')
                ON CONFLICT (processing_run_id) DO UPDATE
                    SET state='RUNNING', attempts=control.processing_run.attempts+1,
                        completed_at=NULL, error_code=NULL
            """),
                {"id": run_id, "connector": connector_run_id, "version": PROCESSOR_VERSION},
            )
        loader = StagingLoader(engine)
        documents: list[tuple[SnapshotInput, dict[str, Any]]] = []
        reused = new = 0
        try:
            for item in inputs:
                if (
                    source != "ncs_career_path"
                    and item.mime_type.split(";", 1)[0].strip().lower() != "application/json"
                ):
                    raise ProcessingError("UNSUPPORTED_SOURCE_MIME")
                # Verify even cache hits: missing/purged/corrupt bytes must not pass silently.
                body = read_raw(raw_root, item)
                doc_id = digest([source, item.snapshot_id, item.partition_id, PROCESSOR_VERSION])
                meta = loader.cached(doc_id)
                if meta is None:
                    parsed = parse_document(source, body, item.partition_id, item.page_number)
                    new += loader.save(source, item, PROCESSOR_VERSION, doc_id, parsed)
                    meta = loader.cached(doc_id)
                    assert meta is not None
                else:
                    reused += 1
                if meta["page"] is not None and meta["page"] != item.page_number:
                    raise ProcessingError("CACHED_PAGE_MISMATCH")
                loader.attach(run_id, item.observation_id, doc_id)
                documents.append((item, meta))
            validate_completeness(source, documents)
            rejected = sum(meta["rejected_count"] for _, meta in documents)
            if source == "job_alio" and not rejected:
                validate_posting_pairs(loader, run_id)
            saved_records = list(loader.records(run_id))
            revision_ids = sorted(identity for identity, _ in saved_records)
            normalized_hashes = sorted(
                digest(
                    [
                        source,
                        record.source_record_id,
                        record.normalized.model_dump(mode="json"),
                    ]
                )
                for _, record in saved_records
            )
            summary = ProcessingSummary(
                processing_run_id=run_id,
                connector_run_id=connector_run_id,
                source_id=source,
                state="REVIEW_REQUIRED" if rejected else "READY",
                documents=len(documents),
                reused_documents=reused,
                records=len(revision_ids),
                rejected=rejected,
                new_revisions=new,
                content_set_hash=digest(revision_ids),
                normalized_set_hash=digest(normalized_hashes),
            )
            with engine.begin() as c:
                c.execute(
                    text("""
                    UPDATE control.processing_run SET state=:state, completed_at=CURRENT_TIMESTAMP,
                        summary=CAST(:summary AS jsonb) WHERE processing_run_id=:id
                """),
                    {
                        "id": run_id,
                        "state": summary.state,
                        "summary": json.dumps(summary.model_dump(mode="json")),
                    },
                )
            return summary
        except Exception as error:
            code = str(error) if isinstance(error, ProcessingError) else type(error).__name__
            with engine.begin() as c:
                c.execute(
                    text("""
                    UPDATE control.processing_run SET state='FAILED', error_code=:code,
                        completed_at=CURRENT_TIMESTAMP WHERE processing_run_id=:id
                """),
                    {"id": run_id, "code": code[:100]},
                )
            raise
