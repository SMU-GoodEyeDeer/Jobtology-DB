from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sqlalchemy import Engine, create_engine, text

MVP_NCS_SUBCATEGORY_ALLOWLIST_VERSION = "2026-09-06.1"
MVP_NCS_SUBCATEGORY_ALLOWLIST = frozenset(
    {
        "DB엔지니어링",
        "UI/UX엔지니어링",
        "빅데이터기획",
        "빅데이터분석",
        "생성형AI엔지니어링",
        "시스템SW엔지니어링",
        "응용SW엔지니어링",
        "인공지능모델링",
        "인공지능서비스구현",
        "인공지능플랫폼구축",
        "인공지능학습데이터구축",
    }
)

_NCS_UNIT_CODE_PATTERN = re.compile(r"^\d{10}_\d{2}v\d+$")
_QNET_ITEM_CODE_PATTERN = re.compile(r"^[A-Z0-9]{4}$")


class PartitionConfigError(ValueError):
    """A fetched run cannot safely produce connector partition configuration."""


@dataclass(frozen=True, slots=True)
class RawSnapshotReference:
    partition_id: str
    page_number: int | None
    response_ordinal: int
    raw_object_path: str
    content_sha256: str
    byte_length: int
    mime_type: str


@dataclass(frozen=True, slots=True)
class SelectedSnapshotDocument:
    reference: RawSnapshotReference
    document: object


def derive_ncs_qualification_codes(
    database_url: str,
    raw_root: Path,
    connector_run_id: str,
    *,
    allowed_subcategories: frozenset[str] = MVP_NCS_SUBCATEGORY_ALLOWLIST,
) -> tuple[str, ...]:
    """Derive full NCS unit-code partitions from one complete competency fetch."""

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        return derive_ncs_qualification_codes_from_engine(
            engine,
            raw_root,
            connector_run_id,
            allowed_subcategories=allowed_subcategories,
        )
    finally:
        engine.dispose()


def derive_ncs_qualification_codes_from_engine(
    engine: Engine,
    raw_root: Path,
    connector_run_id: str,
    *,
    allowed_subcategories: frozenset[str] = MVP_NCS_SUBCATEGORY_ALLOWLIST,
) -> tuple[str, ...]:
    if not allowed_subcategories:
        raise PartitionConfigError("The NCS subcategory allowlist cannot be empty")

    documents = _selected_run_documents(
        engine,
        raw_root,
        connector_run_id,
        expected_source_id="ncs_competency",
    )
    records = _complete_ncs_records(documents)
    seen_subcategories: set[str] = set()
    codes: set[str] = set()
    for record in records:
        raw_subcategory = record.get("ncsSubdCdnm")
        if not isinstance(raw_subcategory, str):
            raise PartitionConfigError("An NCS competency record has an invalid ncsSubdCdnm")
        subcategory = raw_subcategory.strip()
        if subcategory not in allowed_subcategories:
            continue
        seen_subcategories.add(subcategory)
        codes.add(cast(str, record["ncsClCd"]).strip())

    missing = sorted(allowed_subcategories - seen_subcategories)
    if missing:
        raise PartitionConfigError(
            "The fetched run is missing allowlisted NCS subcategories: " + ", ".join(missing)
        )
    if not codes:
        raise PartitionConfigError("The fetched run produced no NCS qualification partitions")
    return tuple(sorted(codes))


def derive_qnet_item_codes(
    database_url: str,
    raw_root: Path,
    connector_run_id: str,
) -> tuple[str, ...]:
    """Derive Q-Net item-code partitions from one complete NCS mapping fetch."""

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        return derive_qnet_item_codes_from_engine(engine, raw_root, connector_run_id)
    finally:
        engine.dispose()


def derive_qnet_item_codes_from_engine(
    engine: Engine,
    raw_root: Path,
    connector_run_id: str,
) -> tuple[str, ...]:
    documents = _selected_run_documents(
        engine,
        raw_root,
        connector_run_id,
        expected_source_id="ncs_qualification",
    )
    codes: set[str] = set()
    for record in _complete_qualification_records(documents):
        raw_code = record.get("jmCd")
        if not isinstance(raw_code, (str, int)) or isinstance(raw_code, bool):
            raise PartitionConfigError("The fetched run contains an invalid jmCd")
        code = str(raw_code).strip().upper()
        if _QNET_ITEM_CODE_PATTERN.fullmatch(code) is None:
            raise PartitionConfigError(f"The fetched run contains an invalid jmCd: {code!r}")
        codes.add(code)

    if not codes:
        raise PartitionConfigError("The fetched run produced no Q-Net item-code partitions")
    return tuple(sorted(codes))


def write_partition_codes(output_path: Path, codes: Iterable[str]) -> None:
    """Atomically replace a connector partition file with sorted unique values."""

    normalized_codes = tuple(sorted(set(codes)))
    if not normalized_codes:
        raise PartitionConfigError("Refusing to write an empty connector partition file")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(normalized_codes) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
        directory_descriptor = os.open(output_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _selected_run_documents(
    engine: Engine,
    raw_root: Path,
    connector_run_id: str,
    *,
    expected_source_id: str,
) -> tuple[SelectedSnapshotDocument, ...]:
    snapshot_references = _selected_snapshot_references(
        engine,
        connector_run_id,
        expected_source_id=expected_source_id,
    )
    return tuple(
        SelectedSnapshotDocument(
            reference=reference,
            document=_read_snapshot(raw_root, reference),
        )
        for reference in snapshot_references
    )


def _selected_snapshot_references(
    engine: Engine,
    connector_run_id: str,
    *,
    expected_source_id: str,
) -> tuple[RawSnapshotReference, ...]:
    with engine.connect() as connection:
        run = (
            connection.execute(
                text(
                    """
                    SELECT source_id, mode, state, stage, fetch_completed_at,
                           planned_request_count, successful_request_count
                    FROM control.connector_run
                    WHERE connector_run_id = :connector_run_id
                    """
                ),
                {"connector_run_id": connector_run_id},
            )
            .mappings()
            .one_or_none()
        )
        if run is None:
            raise PartitionConfigError(f"Connector run {connector_run_id!r} does not exist")
        if run["source_id"] != expected_source_id:
            raise PartitionConfigError(
                f"Connector run {connector_run_id!r} belongs to {run['source_id']!r}, "
                f"not {expected_source_id!r}"
            )
        if run["mode"] != "SCHEDULED_FULL":
            raise PartitionConfigError("Partition derivation requires a SCHEDULED_FULL run")
        if run["state"] not in {"RUNNING", "SUCCEEDED"}:
            raise PartitionConfigError("Partition derivation requires a non-failed run")
        if run["state"] == "RUNNING" and run["stage"] != "FETCHED":
            raise PartitionConfigError("A running connector run must be at the FETCHED stage")

        planned = run["planned_request_count"]
        successful = run["successful_request_count"]
        if (
            run["fetch_completed_at"] is None
            or not isinstance(planned, int)
            or isinstance(planned, bool)
            or planned < 1
            or not isinstance(successful, int)
            or isinstance(successful, bool)
            or successful != planned
        ):
            raise PartitionConfigError(
                "Partition derivation requires every request in a completed fetch to succeed"
            )

        rows = (
            connection.execute(
                text(
                    """
                    SELECT request.partition_id, request.page_number,
                           observation.response_ordinal, snapshot.raw_object_path,
                           snapshot.content_sha256, snapshot.byte_length, snapshot.mime_type
                    FROM control.connector_request AS request
                    JOIN raw_manifest.fetch_observation AS observation
                      ON observation.connector_run_id = request.connector_run_id
                     AND observation.request_fingerprint = request.request_fingerprint
                     AND observation.observation_id = request.selected_observation_id
                    JOIN raw_manifest.source_snapshot AS snapshot
                      ON snapshot.snapshot_id = observation.snapshot_id
                    WHERE request.connector_run_id = :connector_run_id
                      AND observation.source_id = :source_id
                      AND snapshot.source_id = :source_id
                      AND observation.selected IS TRUE
                      AND observation.outcome = 'SELECTED_SUCCESS'
                    ORDER BY request.partition_id, request.page_number NULLS LAST,
                             observation.response_ordinal, observation.observation_id
                    """
                ),
                {"connector_run_id": connector_run_id, "source_id": expected_source_id},
            )
            .mappings()
            .all()
        )

    if len(rows) != successful:
        raise PartitionConfigError(
            "Selected successful snapshots do not match the connector run success count"
        )

    references: list[RawSnapshotReference] = []
    for row in rows:
        partition_id = row["partition_id"]
        page_number = row["page_number"]
        response_ordinal = row["response_ordinal"]
        raw_object_path = row["raw_object_path"]
        content_sha256 = row["content_sha256"]
        byte_length = row["byte_length"]
        mime_type = row["mime_type"]
        if (
            not isinstance(partition_id, str)
            or not partition_id
            or (page_number is not None and not isinstance(page_number, int))
            or isinstance(page_number, bool)
            or not isinstance(response_ordinal, int)
            or isinstance(response_ordinal, bool)
            or response_ordinal < 0
            or not isinstance(raw_object_path, str)
            or not isinstance(content_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
            or not isinstance(byte_length, int)
            or isinstance(byte_length, bool)
            or byte_length < 0
            or not isinstance(mime_type, str)
        ):
            raise PartitionConfigError("A selected snapshot has invalid manifest metadata")
        references.append(
            RawSnapshotReference(
                partition_id=partition_id,
                page_number=page_number,
                response_ordinal=response_ordinal,
                raw_object_path=raw_object_path,
                content_sha256=content_sha256,
                byte_length=byte_length,
                mime_type=mime_type,
            )
        )
    return tuple(references)


def _read_snapshot(raw_root: Path, reference: RawSnapshotReference) -> object:
    if reference.mime_type.casefold() != "application/json":
        raise PartitionConfigError("A selected API snapshot does not have application/json MIME")
    resolved_root = raw_root.resolve()
    resolved_path = (resolved_root / reference.raw_object_path).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise PartitionConfigError("A selected snapshot path escapes JOBTOLOGY_RAW_ROOT")
    try:
        body = resolved_path.read_bytes()
    except OSError as error:
        raise PartitionConfigError(
            f"A selected raw snapshot is unavailable: {reference.raw_object_path}"
        ) from error
    if len(body) != reference.byte_length:
        raise PartitionConfigError(
            f"A selected raw snapshot has the wrong length: {reference.raw_object_path}"
        )
    if hashlib.sha256(body).hexdigest() != reference.content_sha256:
        raise PartitionConfigError(
            f"A selected raw snapshot has the wrong digest: {reference.raw_object_path}"
        )
    try:
        document: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PartitionConfigError(
            f"A selected raw snapshot is not valid JSON: {reference.raw_object_path}"
        ) from error
    return document


def _complete_ncs_records(
    documents: Iterable[SelectedSnapshotDocument],
) -> tuple[Mapping[str, object], ...]:
    records_by_page: dict[int, tuple[Mapping[str, object], ...]] = {}
    declared_total: int | None = None
    declared_page_size: int | None = None
    for selected in documents:
        reference = selected.reference
        if (
            reference.partition_id != "all"
            or reference.response_ordinal != 0
            or reference.page_number is None
            or reference.page_number < 1
        ):
            raise PartitionConfigError("NCS snapshot has invalid request partition metadata")

        document_mapping = _mapping(selected.document, "NCS response")
        root = _mapping(document_mapping.get("root"), "NCS response root")
        info = _mapping(root.get("info"), "NCS response info")
        response_total = _nonnegative_integer(info.get("totalCount"), "NCS totalCount")
        response_page = _positive_integer(info.get("pageNo"), "NCS pageNo")
        response_page_size = _positive_integer(info.get("numOfRows"), "NCS numOfRows")
        if response_page != reference.page_number:
            raise PartitionConfigError("NCS response pageNo does not match its manifest request")
        if declared_total is None:
            declared_total = response_total
        elif response_total != declared_total:
            raise PartitionConfigError("NCS response pages disagree on totalCount")
        if declared_page_size is None:
            declared_page_size = response_page_size
        elif response_page_size != declared_page_size:
            raise PartitionConfigError("NCS response pages disagree on numOfRows")

        raw_items = root.get("items")
        if not isinstance(raw_items, list):
            raise PartitionConfigError("NCS response items must be an array")
        if response_page in records_by_page:
            raise PartitionConfigError("NCS response contains the same page more than once")
        records_by_page[response_page] = tuple(
            _mapping(item, "NCS competency record") for item in cast(list[object], raw_items)
        )

    if declared_total is None or declared_page_size is None:
        raise PartitionConfigError("The fetched run contains no NCS response pages")
    expected_page_count = max(1, math.ceil(declared_total / declared_page_size))
    if set(records_by_page) != set(range(1, expected_page_count + 1)):
        raise PartitionConfigError("NCS response pages are not complete and contiguous")

    records: list[Mapping[str, object]] = []
    for page_number in range(1, expected_page_count + 1):
        page_records = records_by_page[page_number]
        expected_row_count = min(
            declared_page_size,
            max(0, declared_total - (page_number - 1) * declared_page_size),
        )
        if len(page_records) != expected_row_count:
            raise PartitionConfigError("An NCS response page has an unexpected row count")
        records.extend(page_records)
    if len(records) != declared_total:
        raise PartitionConfigError(
            "NCS response row count does not match the provider-declared total"
        )

    record_codes: list[str] = []
    for record in records:
        raw_code = record.get("ncsClCd")
        if (
            not isinstance(raw_code, str)
            or _NCS_UNIT_CODE_PATTERN.fullmatch(raw_code.strip()) is None
        ):
            raise PartitionConfigError("An NCS competency record has an invalid ncsClCd")
        record_codes.append(raw_code.strip())
    if len(set(record_codes)) != declared_total:
        raise PartitionConfigError(
            "NCS response contains duplicate ncsClCd values and is not a complete stable snapshot"
        )
    return tuple(records)


def _complete_qualification_records(
    documents: Iterable[SelectedSnapshotDocument],
) -> tuple[Mapping[str, object], ...]:
    pages_by_partition: dict[str, list[tuple[int, int, int, tuple[Mapping[str, object], ...]]]] = {}
    for selected in documents:
        reference = selected.reference
        if (
            not reference.partition_id.startswith("ncs-")
            or reference.page_number is None
            or reference.page_number < 1
        ):
            raise PartitionConfigError(
                "NCS qualification snapshot has invalid request partition metadata"
            )
        requested_ncs_code = reference.partition_id.removeprefix("ncs-")
        if _NCS_UNIT_CODE_PATTERN.fullmatch(requested_ncs_code) is None:
            raise PartitionConfigError("NCS qualification partition has an invalid NCS code")

        document_mapping = _mapping(selected.document, "NCS qualification response")
        body = _mapping(document_mapping.get("body"), "NCS qualification response body")
        response_total = _nonnegative_integer(
            body.get("totalCount"), "NCS qualification totalCount"
        )
        response_page = _positive_integer(body.get("pageNo"), "NCS qualification pageNo")
        response_page_size = _positive_integer(body.get("numOfRows"), "NCS qualification numOfRows")
        if response_page != reference.page_number:
            raise PartitionConfigError(
                "NCS qualification response pageNo does not match its manifest request"
            )
        raw_items = body.get("items")
        if not isinstance(raw_items, list):
            raise PartitionConfigError("NCS qualification response items must be an array")
        page_records = tuple(
            _mapping(item, "NCS qualification record") for item in cast(list[object], raw_items)
        )
        for record in page_records:
            if record.get("ncsClCd") != requested_ncs_code:
                raise PartitionConfigError(
                    "NCS qualification record does not match its requested NCS partition"
                )
        pages_by_partition.setdefault(reference.partition_id, []).append(
            (response_page, response_total, response_page_size, page_records)
        )

    all_records: list[Mapping[str, object]] = []
    for pages in pages_by_partition.values():
        totals = {page[1] for page in pages}
        page_sizes = {page[2] for page in pages}
        if len(totals) != 1 or len(page_sizes) != 1:
            raise PartitionConfigError(
                "NCS qualification response pages disagree on pagination metadata"
            )
        total = next(iter(totals))
        page_size = next(iter(page_sizes))
        if total == 0:
            if any(page_number != 1 or records for page_number, _, _, records in pages):
                raise PartitionConfigError("A zero-result NCS qualification partition is invalid")
            continue

        page_records_by_number: dict[int, tuple[Mapping[str, object], ...]] = {}
        for page_number, _, _, records in pages:
            if page_number in page_records_by_number:
                raise PartitionConfigError(
                    "NCS qualification response contains the same non-empty page more than once"
                )
            page_records_by_number[page_number] = records
        expected_page_count = math.ceil(total / page_size)
        if set(page_records_by_number) != set(range(1, expected_page_count + 1)):
            raise PartitionConfigError(
                "NCS qualification response pages are not complete and contiguous"
            )

        partition_records: list[Mapping[str, object]] = []
        for page_number in range(1, expected_page_count + 1):
            records = page_records_by_number[page_number]
            expected_row_count = min(page_size, total - (page_number - 1) * page_size)
            if len(records) != expected_row_count:
                raise PartitionConfigError(
                    "An NCS qualification response page has an unexpected row count"
                )
            partition_records.extend(records)
        serialized_records = [
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for record in partition_records
        ]
        if len(set(serialized_records)) != total:
            raise PartitionConfigError(
                "NCS qualification response contains duplicate provider rows"
            )
        all_records.extend(partition_records)
    return tuple(all_records)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PartitionConfigError(f"{label} must be an object")
    mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise PartitionConfigError(f"{label} must use string keys")
    return cast(dict[str, object], value)


def _nonnegative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PartitionConfigError(f"{label} must be a non-negative integer")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result < 1:
        raise PartitionConfigError(f"{label} must be positive")
    return result
