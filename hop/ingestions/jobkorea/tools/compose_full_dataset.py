#!/usr/bin/env python3
"""Compose one private snapshot from audited, unchanged local observations.

All supplied bytes are archived. Duplicate observations remain in the occurrence
manifest; scraper errors remain in the archived originals and quarantine list.
This performs no database writes, source requests or model requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from audit_full_dataset import (
    NARRATIVE,
    POSTING,
    SUPPORTED_TEXT,
    audit,
    canonical,
    date_kind,
    digest,
    scraper_error_envelope,
)

POLICY = "jobkorea-whole-observation-selection-2026-10-08-v1"
POLICY_RULES = [
    "Prefer explicit source CLOSED status.",
    "Prefer valid source-stated deadline over missing/NULL policy deadline.",
    "When fixed deadlines differ, prefer the earliest explicit deadline conservatively.",
    "Prefer more supplied nonempty supported fields, then benefits-tag count.",
    "Break remaining ties by ascending original filename and physical line.",
    "Select one complete original line unchanged; never merge field values.",
    "These rules do not establish collection chronology or authoritative current truth.",
]


def closed(row: dict[str, Any]) -> bool:
    status = row.get("source_status", row.get("status", ""))
    return (
        row.get("is_closed") is True
        or row.get("closed") is True
        or str(status).upper() in {"CLOSED", "마감", "채용마감", "접수마감"}
    )


def selection_rank(row: dict[str, Any], name: str, line: int) -> tuple[Any, ...]:
    kind = date_kind(row, "application_end_date")
    explicit = kind not in {"MISSING_KEY", "NULL"} and not kind.startswith("INVALID")
    earliest = float("inf")
    if kind in {"ISO_DATE", "MIDNIGHT_UTC_DATE_ENCODING"}:
        earliest = (
            datetime.fromisoformat(row["application_end_date"][:10]).replace(tzinfo=UTC).timestamp()
        )
    elif kind == "EXPLICIT_OFFSET_TIMESTAMP":
        earliest = datetime.fromisoformat(
            row["application_end_date"].replace("Z", "+00:00")
        ).timestamp()
    fields = (
        SUPPORTED_TEXT
        | NARRATIVE
        | {"job_title", "application_start_date", "application_end_date", "recruitment_count"}
    )
    richness = sum(
        row.get(key) is not None and row.get(key) != "" and row.get(key) != [] for key in fields
    )
    tags: list[Any] = row.get("company_benefits_tags", [])
    return (-int(closed(row)), -int(explicit), earliest, -richness, -len(tags), name, line)


def file_summary(path: Path) -> dict[str, Any]:
    hasher = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            hasher.update(block)
            length += len(block)
    return {"sha256": hasher.hexdigest(), "byte_length": length}


def protected_write(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        path.chmod(0o600)
        handle.write(raw)


def compose(source: Path, output: Path) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    repository = Path(__file__).resolve().parents[4]
    if source == output or source in output.parents:
        raise ValueError("OUTPUT_MUST_NOT_BE_IN_SOURCE_DIRECTORY")
    if repository == output or repository in output.parents:
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_REPOSITORY")
    result = audit(source)
    if result["source_or_framing_issues"]:
        raise ValueError("SOURCE_AUDIT_VALIDATION_ISSUES")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    originals = output / "originals"
    originals.mkdir(mode=0o700)
    inventory = cast(list[dict[str, Any]], result["files"])
    file_hashes = {item["file"]: item["sha256"] for item in inventory}
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in inventory:
        archived = originals / item["file"]
        shutil.copyfile(source / item["file"], archived)
        archived.chmod(0o600)
        expected = {"sha256": item["sha256"], "byte_length": item["bytes"]}
        if file_summary(archived) != expected:
            raise ValueError("SOURCE_ARCHIVE_CHANGED_DURING_COPY")
        if item["kind"] != "NDJSON":
            continue
        offset = 0
        with archived.open("rb") as handle:
            for line, raw in enumerate(handle, 1):
                row: dict[str, Any] = json.loads(raw)
                locator = {
                    "file": archived.name,
                    "file_sha256": file_hashes[archived.name],
                    "line": line,
                    "byte_offset": offset,
                    "byte_length": len(raw),
                    "line_sha256": digest(raw),
                }
                offset += len(raw)
                if scraper_error_envelope(row):
                    continue
                match = POSTING.fullmatch(row["product_page_url"])
                if match is None:
                    raise ValueError("ARCHIVED_POSTING_ID_INVALID")
                observations[match[1]].append(
                    {
                        "locator": locator,
                        "row": row,
                        "raw": raw,
                        "rank": selection_rank(row, archived.name, line),
                    }
                )
    snapshot = output / "snapshot.ndjson"
    occurrences = output / "occurrences.ndjson"
    selections: dict[str, dict[str, Any]] = {}
    selected_dates: Counter[str] = Counter()
    selected_starts: Counter[str] = Counter()
    selected_files: Counter[str] = Counter()
    selected_narrative_present = 0
    snapshot_offset = 0
    with snapshot.open("xb") as snap, occurrences.open("xb") as occurrence_file:
        snapshot.chmod(0o600)
        occurrences.chmod(0o600)
        for composed_line, posting_id in enumerate(sorted(observations, key=int), 1):
            alternatives = sorted(observations[posting_id], key=lambda obs: obs["rank"])
            chosen = alternatives[0]
            if any(
                isinstance(chosen["row"].get(key), str) and chosen["row"][key].strip()
                for key in NARRATIVE
            ):
                selected_narrative_present += 1
            raw: bytes = chosen["raw"]
            if digest(raw) != chosen["locator"]["line_sha256"]:
                raise ValueError("SELECTED_BYTES_HASH_CONFLICT")
            snap.write(raw)
            locator: dict[str, Any] = chosen["locator"]
            entry = {
                "composed_line": composed_line,
                "source_record_id": posting_id,
                "composed_byte_offset": snapshot_offset,
                "composed_byte_length": len(raw),
                "composed_line_sha256": digest(raw),
                "selected_original": locator,
                "alternative_occurrences": [obs["locator"] for obs in alternatives[1:]],
                "selection_policy": POLICY,
            }
            occurrence_file.write(canonical(entry) + b"\n")
            snapshot_offset += len(raw)
            selections[posting_id] = {
                "selected_original": locator,
                "selection_rank": [
                    None if value == float("inf") else value for value in chosen["rank"]
                ],
                "selected_deadline_kind": date_kind(chosen["row"], "application_end_date"),
                "selected_application_end_date": chosen["row"].get("application_end_date"),
            }
            selected_dates[date_kind(chosen["row"], "application_end_date")] += 1
            selected_starts[date_kind(chosen["row"], "application_start_date")] += 1
            selected_files[locator["file"]] += 1
    conflicts: list[dict[str, Any]] = []
    deadline_cases: list[dict[str, Any]] = []
    for group in result["duplicate_groups"]:
        if group["classification"] != "CONTENT_CONFLICT":
            continue
        case = {**group, **selections[group["posting_id"]]}
        conflicts.append(case)
        if "application_end_date" in group["changed_fields"]:
            case = {
                **case,
                "deadline_alternatives": [
                    {
                        "original": obs["locator"],
                        "application_end_date": obs["row"].get("application_end_date"),
                        "date_kind": date_kind(obs["row"], "application_end_date"),
                    }
                    for obs in observations[group["posting_id"]]
                ],
            }
            deadline_cases.append(case)
    quarantined = [
        {**loc, "file_sha256": file_hashes[loc["file"]]}
        for loc in result["quarantined_scraper_errors"]
    ]
    descriptor: dict[str, Any] = {
        "contract": "jobkorea-composed-dataset-v1",
        "selection_policy": POLICY,
        "selection_rules": POLICY_RULES,
        "actual_scrape_time": None,
        "scope": "SUPPLIED_FILES_ONLY",
        "provider_complete": False,
        "absence_is_closure": False,
        "source_requests": 0,
        "model_requests": 0,
        "database_writes": 0,
        "source_inventory": inventory,
        "snapshot": file_summary(snapshot),
        "occurrences": file_summary(occurrences),
        "row_key": "composed_line",
        "selected_count": len(observations),
        "listing_observation_count": result["totals"]["listing_rows"],
        "scraper_error_count": len(quarantined),
        "quarantined_scraper_errors": quarantined,
        "duplicate_posting_ids": result["duplicate_posting_ids"],
        "extra_observations": result["extra_observations"],
        "duplicate_classification_counts": result["duplicate_classification_counts"],
        "selected_dates": dict(selected_dates),
        "selected_starts": dict(selected_starts),
        "selected_files": dict(selected_files),
        "selected_narrative_present": selected_narrative_present,
        "content_conflicts": conflicts,
        "deadline_conflict_cases": deadline_cases,
    }
    protected_write(output / "composition.json", canonical(descriptor) + b"\n")
    receipt: dict[str, Any] = {
        "contract": "jobkorea-dataset-provenance-v1",
        "snapshot_sha256": descriptor["snapshot"]["sha256"],
        "snapshot_byte_length": descriptor["snapshot"]["byte_length"],
        "selected_count": len(observations),
        "occurrences_sha256": descriptor["occurrences"]["sha256"],
        "occurrences_byte_length": descriptor["occurrences"]["byte_length"],
        "descriptor_sha256": file_summary(output / "composition.json")["sha256"],
        "descriptor_byte_length": file_summary(output / "composition.json")["byte_length"],
        "archive_relative_root": "jobkorea/datasets/"
        + file_summary(output / "composition.json")["sha256"],
        "row_key": "composed_line",
    }
    protected_write(output / "provenance.json", canonical(receipt) + b"\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compose(args.source, args.output), indent=2))


if __name__ == "__main__":
    main()
