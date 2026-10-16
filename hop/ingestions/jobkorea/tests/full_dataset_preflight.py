# ruff: noqa: E501
"""Native import-only preflight for an exact composed private snapshot.

Uses disposable databases on an INTERNAL Docker network, existing local images
and the real Hop reader/PostgreSQL loader. No source or model URL is requested.
The optional Neo4j container created by the shared fixture is never loaded.
"""

import argparse
import hashlib
import json
from pathlib import Path

from native import Fixture


def verify_composition(directory):
    descriptor = json.loads((directory / "composition.json").read_text())
    provenance = json.loads((directory / "provenance.json").read_text())
    for name, hash_key, byte_key in (
        ("snapshot.ndjson", "snapshot_sha256", "snapshot_byte_length"),
        ("occurrences.ndjson", "occurrences_sha256", "occurrences_byte_length"),
        ("composition.json", "descriptor_sha256", "descriptor_byte_length"),
    ):
        raw = (directory / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == provenance[hash_key], name + " hash"
        assert len(raw) == provenance[byte_key], name + " bytes"
    originals = {}
    expected_listing_locators = set()
    expected_errors = set()
    for item in descriptor["source_inventory"]:
        path = directory / "originals" / item["file"]
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], "original hash"
        assert len(raw) == item["bytes"], "original bytes"
        if item["kind"] != "NDJSON":
            continue
        offset = 0
        for number, line in enumerate(raw.splitlines(keepends=True), 1):
            key = (item["file"], number)
            originals[key] = (offset, line)
            offset += len(line)
            row = json.loads(line)
            if {"error", "error_code"} & row.keys() and row.keys() <= {
                "input",
                "error",
                "error_code",
            }:
                expected_errors.add(key)
            else:
                expected_listing_locators.add(key)
    seen = set()
    posting_ids = set()
    snapshot_offset = 0
    count = 0
    with (
        (directory / "snapshot.ndjson").open("rb") as snapshot,
        (directory / "occurrences.ndjson").open("rb") as occurrences,
    ):
        for number, raw in enumerate(snapshot, 1):
            mapping = json.loads(occurrences.readline())
            assert mapping["composed_line"] == number
            assert mapping["composed_byte_offset"] == snapshot_offset
            assert mapping["composed_byte_length"] == len(raw)
            assert mapping["composed_line_sha256"] == hashlib.sha256(raw).hexdigest()
            selected = mapping["selected_original"]
            assert originals[(selected["file"], selected["line"])][1] == raw
            row = json.loads(raw)
            posting_id = mapping["source_record_id"]
            assert posting_id not in posting_ids
            assert (
                row["product_page_url"]
                .split("/GI_Read/")[1]
                .split("?")[0]
                .split("#")[0]
                .rstrip("/")
                == posting_id
            )
            posting_ids.add(posting_id)
            for locator in [selected, *mapping["alternative_occurrences"]]:
                key = (locator["file"], locator["line"])
                assert key not in seen
                seen.add(key)
                offset, line = originals[key]
                assert locator["byte_offset"] == offset
                assert locator["byte_length"] == len(line)
                assert locator["line_sha256"] == hashlib.sha256(line).hexdigest()
                assert locator["file_sha256"] == next(
                    item["sha256"]
                    for item in descriptor["source_inventory"]
                    if item["file"] == locator["file"]
                )
            snapshot_offset += len(raw)
            count += 1
        assert not occurrences.read(), "no extra mappings"
    assert seen == expected_listing_locators, "every source listing observation preserved"
    assert {
        (row["file"], row["line"]) for row in descriptor["quarantined_scraper_errors"]
    } == expected_errors
    assert count == descriptor["selected_count"] == provenance["selected_count"]
    assert count == 8434
    assert len(seen) == 12105 and len(expected_errors) == 8
    assert len(descriptor["content_conflicts"]) == 303
    assert len(descriptor["deadline_conflict_cases"]) == 7
    return descriptor, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    descriptor, provenance = verify_composition(args.directory)
    print(
        "All original archives, selected raw bytes, 12,105 occurrences and 8 error envelopes verified",
        flush=True,
    )
    fixture = Fixture(args.directory / "snapshot.ndjson")
    fixture.receipt["scope"] = "FULL_DATASET_IMPORT_ONLY_PREFLIGHT"
    fixture.receipt["dataset_provenance"] = provenance
    fixture.receipt["expected_record_count"] = descriptor["selected_count"]
    try:
        fixture.boot()
        fixture.install()
        fixture.run(
            "import_local.hpl",
            "full-dataset-native-import",
            extra={"INPUT_FORMAT": "NDJSON", "MAX_FILE_BYTES": "1073741824", "BATCH_ROWS": "500"},
        )
        run_id = fixture.sql(
            "SELECT run_id FROM ingestion.jobkorea_import WHERE file_sha256='"
            + provenance["snapshot_sha256"]
            + "'",
            "full-run-id",
        )
        fixture.receipt["run_id"] = run_id
        pin = "'" + run_id + "'"
        fixture.expect(
            fixture.sql("SELECT state FROM ingestion.run WHERE run_id=" + pin, "full-ready")
            == "READY",
            "full-ready",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.record WHERE run_id=" + pin, "full-record-count"
            )
            == "8434",
            "8434-native-records",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(DISTINCT source_record_id) FROM ingestion.record WHERE run_id=" + pin,
                "full-identity-count",
            )
            == "8434",
            "8434-native-distinct-identities",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.rejected_row WHERE run_id=" + pin,
                "full-rejected-count",
            )
            == "0",
            "zero-native-rejected",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.jobkorea_issue WHERE run_id="
                + pin
                + " AND severity='ERROR'",
                "full-error-count",
            )
            == "0",
            "zero-native-error-issues",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.request_attempt WHERE run_id=" + pin,
                "full-request-count",
            )
            == "0",
            "zero-native-source-requests",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.graph_export WHERE run_id=" + pin,
                "full-graph-count",
            )
            == "0",
            "import-only-zero-graph-checkpoints",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.jobkorea_import WHERE run_id="
                + pin
                + " AND scraped_at IS NULL",
                "full-scrape-time",
            )
            == "1",
            "actual-scrape-time-unknown",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.record WHERE run_id="
                + pin
                + " AND normalized->>'content_status'='MISSING' AND normalized->>'extraction_eligible'='false'",
                "full-content",
            )
            == "8434",
            "all-descriptions-missing",
        )
        fixture.receipt["deadline_counts"] = fixture.sql(
            "SELECT normalized->>'deadline_kind',normalized->>'deadline_basis',count(*) FROM ingestion.record WHERE run_id="
            + pin
            + " GROUP BY 1,2 ORDER BY 1,2",
            "full-deadlines",
        )
        fixture.receipt["source_integrity_verified"] = True
        fixture.receipt["status"] = "PASSED_FULL_DATASET_NATIVE_IMPORT_ONLY"
    except BaseException as error:
        fixture.receipt["status"] = "FAILED_FULL_DATASET_NATIVE_IMPORT_ONLY"
        fixture.receipt["failure_type"] = type(error).__name__
        raise
    finally:
        fixture.close()
        print("Protected receipt: " + str(fixture.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
