from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool

from jobtology_db.partition_config import (
    MVP_NCS_SUBCATEGORY_ALLOWLIST,
    MVP_NCS_SUBCATEGORY_ALLOWLIST_VERSION,
    PartitionConfigError,
    derive_ncs_qualification_codes_from_engine,
    derive_qnet_item_codes_from_engine,
    write_partition_codes,
)
from jobtology_db.storage.raw_files import RawFileStore


def _manifest_engine() -> Engine:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS control")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS raw_manifest")
        connection.exec_driver_sql(
            """
            CREATE TABLE control.connector_run (
                connector_run_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                state TEXT NOT NULL,
                stage TEXT NOT NULL,
                fetch_completed_at TEXT,
                planned_request_count INTEGER,
                successful_request_count INTEGER
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE control.connector_request (
                connector_run_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                partition_id TEXT NOT NULL,
                page_number INTEGER,
                selected_observation_id TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE raw_manifest.source_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                raw_object_path TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                byte_length INTEGER NOT NULL,
                mime_type TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE raw_manifest.fetch_observation (
                observation_id TEXT PRIMARY KEY,
                connector_run_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                response_ordinal INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                snapshot_id TEXT,
                selected BOOLEAN NOT NULL
            )
            """
        )
    return engine


def _record_run(
    engine: Engine,
    raw_root: Path,
    *,
    source_id: str,
    documents: Sequence[object],
    connector_run_id: str = "fixture-run",
    mode: str = "SCHEDULED_FULL",
    state: str = "RUNNING",
    stage: str = "FETCHED",
    fetch_completed: bool = True,
    planned_count: int | None = None,
    successful_count: int | None = None,
    partition_ids: Sequence[str] | None = None,
) -> tuple[Path, ...]:
    planned = len(documents) if planned_count is None else planned_count
    successful = len(documents) if successful_count is None else successful_count
    resolved_partitions = partition_ids or ("all",) * len(documents)
    if len(resolved_partitions) != len(documents):
        raise ValueError("partition_ids must match documents")
    stored_paths: list[Path] = []
    stored_objects: list[tuple[str, str, int]] = []
    store = RawFileStore(raw_root)
    for document in documents:
        body = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
        stored = store.put(body)
        stored_paths.append(raw_root / stored.relative_path)
        stored_objects.append(
            (str(stored.relative_path), stored.content_sha256, stored.byte_length)
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO control.connector_run VALUES
                    (:run_id, :source_id, :mode, :state, :stage, :completed_at,
                     :planned, :successful)
                """
            ),
            {
                "run_id": connector_run_id,
                "source_id": source_id,
                "mode": mode,
                "state": state,
                "stage": stage,
                "completed_at": "2026-09-06T00:00:00Z" if fetch_completed else None,
                "planned": planned,
                "successful": successful,
            },
        )
        for index, (raw_path, digest, byte_length) in enumerate(stored_objects, start=1):
            request_fingerprint = f"request-{index}"
            observation_id = f"observation-{index}"
            snapshot_id = f"snapshot-{index}"
            connection.execute(
                text(
                    """
                    INSERT INTO control.connector_request VALUES
                        (:run_id, :fingerprint, :partition_id, :page_number, :observation_id)
                    """
                ),
                {
                    "run_id": connector_run_id,
                    "fingerprint": request_fingerprint,
                    "partition_id": resolved_partitions[index - 1],
                    "page_number": index,
                    "observation_id": observation_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO raw_manifest.source_snapshot VALUES
                        (:snapshot_id, :source_id, :raw_path, :digest, :byte_length,
                         'application/json')
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "source_id": source_id,
                    "raw_path": raw_path,
                    "digest": digest,
                    "byte_length": byte_length,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO raw_manifest.fetch_observation VALUES
                        (:observation_id, :run_id, :source_id, :fingerprint, 0,
                         'SELECTED_SUCCESS', :snapshot_id, TRUE)
                    """
                ),
                {
                    "observation_id": observation_id,
                    "run_id": connector_run_id,
                    "source_id": source_id,
                    "fingerprint": request_fingerprint,
                    "snapshot_id": snapshot_id,
                },
            )
    return tuple(stored_paths)


def test_checked_in_ncs_allowlist_is_explicit_and_versioned() -> None:
    assert MVP_NCS_SUBCATEGORY_ALLOWLIST_VERSION == "2026-09-06.1"
    assert {
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
    } == MVP_NCS_SUBCATEGORY_ALLOWLIST


def test_derives_sorted_unique_ncs_codes_and_writes_atomic_partition_file(
    tmp_path: Path,
) -> None:
    engine = _manifest_engine()
    _record_run(
        engine,
        tmp_path,
        source_id="ncs_competency",
        documents=(
            {
                "root": {
                    "info": {"pageNo": 1, "totalCount": 3, "numOfRows": 2},
                    "items": [
                        {
                            "ncsSubdCdnm": "응용SW엔지니어링",
                            "ncsClCd": "2001020202_23v6",
                        },
                        {
                            "ncsSubdCdnm": "MVP 외 분야",
                            "ncsClCd": "0101010101_20v1",
                        },
                    ],
                }
            },
            {
                "root": {
                    "info": {"pageNo": 2, "totalCount": 3, "numOfRows": 2},
                    "items": [
                        {
                            "ncsSubdCdnm": "DB엔지니어링",
                            "ncsClCd": "2001020101_20v1",
                        },
                    ],
                }
            },
        ),
    )

    codes = derive_ncs_qualification_codes_from_engine(
        engine,
        tmp_path,
        "fixture-run",
        allowed_subcategories=frozenset({"응용SW엔지니어링", "DB엔지니어링"}),
    )
    assert codes == ("2001020101_20v1", "2001020202_23v6")

    output = tmp_path / "config" / "ncs-codes.txt"
    write_partition_codes(output, reversed(codes))
    assert output.read_text(encoding="utf-8") == ("2001020101_20v1\n2001020202_23v6\n")
    assert not tuple(output.parent.glob(f".{output.name}.*.tmp"))


def test_ncs_derivation_fails_when_an_allowlisted_subcategory_is_absent(
    tmp_path: Path,
) -> None:
    engine = _manifest_engine()
    _record_run(
        engine,
        tmp_path,
        source_id="ncs_competency",
        documents=(
            {
                "root": {
                    "info": {"pageNo": 1, "totalCount": 1, "numOfRows": 1000},
                    "items": [
                        {
                            "ncsSubdCdnm": "응용SW엔지니어링",
                            "ncsClCd": "2001020202_23v6",
                        }
                    ],
                }
            },
        ),
    )

    with pytest.raises(PartitionConfigError, match="DB엔지니어링"):
        derive_ncs_qualification_codes_from_engine(
            engine,
            tmp_path,
            "fixture-run",
            allowed_subcategories=frozenset({"응용SW엔지니어링", "DB엔지니어링"}),
        )


def test_ncs_derivation_rejects_duplicate_unit_ids_across_pages(tmp_path: Path) -> None:
    engine = _manifest_engine()
    _record_run(
        engine,
        tmp_path,
        source_id="ncs_competency",
        documents=(
            {
                "root": {
                    "info": {"pageNo": 1, "totalCount": 2, "numOfRows": 1},
                    "items": [
                        {
                            "ncsSubdCdnm": "응용SW엔지니어링",
                            "ncsClCd": "2001020202_23v6",
                        }
                    ],
                }
            },
            {
                "root": {
                    "info": {"pageNo": 2, "totalCount": 2, "numOfRows": 1},
                    "items": [
                        {
                            "ncsSubdCdnm": "응용SW엔지니어링",
                            "ncsClCd": "2001020202_23v6",
                        }
                    ],
                }
            },
        ),
    )

    with pytest.raises(PartitionConfigError, match="duplicate ncsClCd"):
        derive_ncs_qualification_codes_from_engine(
            engine,
            tmp_path,
            "fixture-run",
            allowed_subcategories=frozenset({"응용SW엔지니어링"}),
        )


def test_derives_sorted_unique_qnet_codes_from_live_response_envelope(tmp_path: Path) -> None:
    engine = _manifest_engine()
    _record_run(
        engine,
        tmp_path,
        source_id="ncs_qualification",
        documents=(
            {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                "body": {
                    "items": [
                        {"ncsClCd": "2001020202_23v6", "jmCd": "AB12"},
                        {
                            "ncsClCd": "2001020202_23v6",
                            "jmCd": "1320",
                            "organStdVerCd": "v1.0",
                        },
                    ],
                    "numOfRows": 2,
                    "pageNo": 1,
                    "totalCount": 4,
                },
            },
            {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                "body": {
                    "items": [
                        {
                            "ncsClCd": "2001020202_23v6",
                            "jmCd": "1320",
                            "organStdVerCd": "v2.0",
                        },
                        {"ncsClCd": "2001020202_23v6", "jmCd": "2468"},
                    ],
                    "numOfRows": 2,
                    "pageNo": 2,
                    "totalCount": 4,
                },
            },
        ),
        partition_ids=("ncs-2001020202_23v6", "ncs-2001020202_23v6"),
    )

    assert derive_qnet_item_codes_from_engine(engine, tmp_path, "fixture-run") == (
        "1320",
        "2468",
        "AB12",
    )


@pytest.mark.parametrize(
    ("mode", "state", "stage", "fetch_completed", "planned", "successful", "message"),
    [
        ("BACKFILL", "RUNNING", "FETCHED", True, 1, 1, "SCHEDULED_FULL"),
        ("SCHEDULED_FULL", "RUNNING", "FETCHING", False, 1, 1, "FETCHED stage"),
        ("SCHEDULED_FULL", "RUNNING", "FETCHED", True, 2, 1, "every request"),
        ("SCHEDULED_FULL", "FAILED", "FETCH_FAILED", False, 1, 0, "non-failed"),
    ],
)
def test_derivation_rejects_runs_that_are_not_complete_full_successes(
    tmp_path: Path,
    mode: str,
    state: str,
    stage: str,
    fetch_completed: bool,
    planned: int,
    successful: int,
    message: str,
) -> None:
    engine = _manifest_engine()
    _record_run(
        engine,
        tmp_path,
        source_id="ncs_competency",
        documents=(
            {
                "root": {
                    "info": {"pageNo": 1, "totalCount": 1, "numOfRows": 1000},
                    "items": [
                        {
                            "ncsSubdCdnm": "응용SW엔지니어링",
                            "ncsClCd": "2001020202_23v6",
                        }
                    ],
                }
            },
        ),
        mode=mode,
        state=state,
        stage=stage,
        fetch_completed=fetch_completed,
        planned_count=planned,
        successful_count=successful,
    )

    with pytest.raises(PartitionConfigError, match=message):
        derive_ncs_qualification_codes_from_engine(
            engine,
            tmp_path,
            "fixture-run",
            allowed_subcategories=frozenset({"응용SW엔지니어링"}),
        )


def test_derivation_verifies_raw_snapshot_integrity(tmp_path: Path) -> None:
    engine = _manifest_engine()
    (raw_path,) = _record_run(
        engine,
        tmp_path,
        source_id="ncs_competency",
        documents=(
            {
                "root": {
                    "info": {"pageNo": 1, "totalCount": 1, "numOfRows": 1000},
                    "items": [
                        {
                            "ncsSubdCdnm": "응용SW엔지니어링",
                            "ncsClCd": "2001020202_23v6",
                        }
                    ],
                }
            },
        ),
    )
    raw_path.write_bytes(raw_path.read_bytes() + b" ")

    with pytest.raises(PartitionConfigError, match="wrong length"):
        derive_ncs_qualification_codes_from_engine(
            engine,
            tmp_path,
            "fixture-run",
            allowed_subcategories=frozenset({"응용SW엔지니어링"}),
        )
