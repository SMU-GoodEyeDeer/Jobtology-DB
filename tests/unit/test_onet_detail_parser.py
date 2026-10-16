"""Offline detail scope, native identifiers and source rating semantics."""

import csv
import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "onet_detail_parser", ROOT / "hop/ingestions/onet_details/prepare_details.py"
)
assert SPEC is not None and SPEC.loader is not None
parser = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parser)


def csv_bytes(file_id: str, records: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, parser.HEADERS[file_id])
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode()


def sample() -> tuple[dict[str, bytes], bytes]:
    codes = [f"15-{1200 + index:04d}.00" for index in range(31)]
    catalogue = dict(
        contract_version="jobtology-onet-catalog-v1",
        source_version="31.0",
        release_id="frozen-base",
        scheme_id="ONET",
        terms=[
            dict(
                code=code,
                preferred_label="Role " + code,
                term_kind="OCCUPATION",
                term_id=parser.BASE_PREFIX + code,
            )
            for code in codes
        ],
    )
    occupation = {"O*NET-SOC Code": codes[0], "Title": "Role " + codes[0]}
    element = {"Element ID": "2.A.1.a", "Element Name": "Reading"}
    rating = {
        **occupation,
        **element,
        "Scale ID": "IM",
        "Scale Name": "Importance",
        "Data Value": "4.00",
        "N": "8",
        "Standard Error": "0.1250",
        "Lower CI Bound": "3.7500",
        "Upper CI Bound": "4.2500",
        "Recommend Suppress": "N",
        "Not Relevant": "",
        "Date": "08/2023",
        "Domain Source": "Analyst",
    }
    records = {
        "software_skills": [
            {
                **occupation,
                **element,
                "Workplace Example": "Python\nsoftware",
                "Hot Technology": "Y",
                "In Demand": "N",
            }
        ],
        "essential_skills": [
            rating,
            {**rating, "Scale ID": "LV", "Scale Name": "Level", "Not Relevant": "N"},
        ],
        "transferable_skills": [rating],
        "knowledge": [rating],
        "task_statements": [
            {
                **occupation,
                "Task ID": "123",
                "Task": "Develop software.",
                "Task Type": "Core",
                "Incumbents Responding": "",
                "Date": "08/2023",
                "Domain Source": "Incumbent",
            }
        ],
        "task_ratings": [
            {
                **occupation,
                "Task ID": "123",
                "Task": "Develop software.",
                "Scale ID": "FT",
                "Scale Name": "Frequency",
                "Category": "1",
                "Data Value": "0.00",
                "N": "",
                "Standard Error": "",
                "Lower CI Bound": "",
                "Upper CI Bound": "",
                "Recommend Suppress": "",
                "Date": "08/2023",
                "Domain Source": "Incumbent",
            }
        ],
        "content_model_reference": [
            dict(zip(parser.HEADERS["content_model_reference"], row, strict=True))
            for row in [
                ("2", "Worker Requirements", ""),
                ("2.A", "Essential Skills", ""),
                ("2.A.1", "Content", ""),
                ("2.A.1.a", "Reading", "Reading text."),
            ]
        ],
        "scales_reference": [
            dict(zip(parser.HEADERS["scales_reference"], row, strict=True))
            for row in [
                ("IM", "Importance", "1", "5"),
                ("LV", "Level", "0", "7"),
                ("FT", "Frequency", "0", "100"),
            ]
        ],
        "task_categories": [
            {
                "Scale ID": "FT",
                "Scale Name": "Frequency",
                "Category": "1",
                "Category Description": "Yearly or less",
            }
        ],
        "level_scale_anchors": [
            {
                **element,
                "Scale ID": "LV",
                "Scale Name": "Level",
                "Anchor Value": "2",
                "Anchor Description": "Read an email.",
            }
        ],
    }
    return {key: csv_bytes(key, value) for key, value in records.items()}, parser.canonical_bytes(
        catalogue
    )


def prepare(bodies: dict[str, bytes], catalogue_body: bytes) -> dict[str, Any]:
    sources = [
        dict(
            file_id=name,
            source_uri=f"https://www.onetcenter.org/dl_files/database/db_31_0_csv/{name}.csv",
            archive_path=f"sources/{name}.csv",
            byte_length=len(body),
            sha256=parser.sha256(body),
            encoding="UTF-8",
            downloaded_at="2026-10-15T10:00:00+00:00",
        )
        for name, body in bodies.items()
    ]
    return parser.prepare_payload(
        bodies, catalogue_body=catalogue_body, release_id="detail-fixture", sources=sources
    )


def replace_row(bodies: dict[str, bytes], file_id: str, **updates: str) -> None:
    records = list(csv.DictReader(io.StringIO(bodies[file_id].decode())))
    records[0].update(updates)
    bodies[file_id] = csv_bytes(file_id, records)


def test_direct_associations_preserve_null_flags_numeric_values_and_physical_lines() -> None:
    payload = prepare(*sample())
    assert payload["base_release_id"] == "frozen-base"
    assert len(payload["scope_codes"]) == 31
    assert payload["scope_coverage"][1]["status"] == "NO_SOURCE_ROWS"
    ratings = [edge for edge in payload["edges"] if edge["type"] == "ONET_ESSENTIAL_SKILL"]
    assert len(ratings) == 2
    importance = next(edge for edge in ratings if edge["properties"]["scale_id"] == "IM")
    assert importance["source_id"] == "urn:jobtology:onet:occupation:15-1200.00"
    assert importance["target_id"] == "urn:jobtology:onet-detail:element:2.A.1.a"
    assert importance["properties"]["data_value"] == 4.0
    assert importance["properties"]["not_relevant"] is None
    assert importance["properties"]["recommend_suppress"] is False
    assert json.loads(importance["properties"]["source_values_json"])["Data Value"] == "4.00"
    level = next(edge for edge in ratings if edge["properties"]["scale_id"] == "LV")
    assert level["properties"]["not_relevant"] is False
    task_rating = next(edge for edge in payload["edges"] if edge["type"] == "ONET_TASK_RATING")
    assert task_rating["properties"]["category"] == 1
    assert task_rating["properties"]["data_value"] == 0.0
    assert task_rating["properties"]["n"] is None
    assert task_rating["properties"]["recommend_suppress"] is None
    software = next(edge for edge in payload["edges"] if edge["type"] == "ONET_SOFTWARE_EXAMPLE")
    assert software["properties"]["source_locator"] == "csv:lines:2-3"
    assert software["properties"]["hot_technology"] is True
    assert software["properties"]["in_demand"] is False


@pytest.mark.parametrize(
    ("file_id", "updates", "message"),
    [
        ("knowledge", {"Element ID": "9.X"}, "ELEMENT_REFERENCE"),
        ("task_ratings", {"Task ID": "999"}, "TASK_REFERENCE"),
        ("task_ratings", {"Category": "8"}, "TASK_CATEGORY_REFERENCE"),
        ("essential_skills", {"Data Value": "NaN"}, "NUMBER_INVALID"),
        ("essential_skills", {"Data Value": "9"}, "RATING_RANGE"),
        ("software_skills", {"Hot Technology": "maybe"}, "FLAG_INVALID"),
        ("essential_skills", {"Not Relevant": "unknown"}, "FLAG_INVALID"),
    ],
)
def test_invalid_references_scales_and_flags_reject(
    file_id: str, updates: dict[str, str], message: str
) -> None:
    bodies, catalogue = sample()
    replace_row(bodies, file_id, **updates)
    with pytest.raises(parser.DetailInputError, match=message):
        prepare(bodies, catalogue)


def test_duplicate_rating_and_source_hash_changes_reject() -> None:
    bodies, catalogue = sample()
    records = list(csv.DictReader(io.StringIO(bodies["knowledge"].decode())))
    bodies["knowledge"] = csv_bytes("knowledge", records + records)
    with pytest.raises(parser.DetailInputError, match="SOURCE_ROW_DUPLICATE"):
        prepare(bodies, catalogue)
    bodies, catalogue = sample()
    with pytest.raises(parser.DetailInputError, match="SOURCE_PIN"):
        parser.prepare_payload(
            bodies,
            catalogue_body=catalogue,
            release_id="fixture",
            sources=[
                dict(
                    file_id=name,
                    source_uri=f"https://www.onetcenter.org/dl_files/database/"
                    f"db_31_0_csv/{name}.csv",
                    archive_path=f"sources/{name}.csv",
                    encoding="UTF-8",
                    byte_length=len(body),
                    sha256="0" * 64,
                )
                for name, body in bodies.items()
            ],
        )


@pytest.mark.parametrize("body", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'])
def test_duplicate_or_nonfinite_json_is_rejected(body: bytes) -> None:
    with pytest.raises(parser.DetailInputError, match=r"JSON_DUPLICATE_KEY|JSON_NONFINITE"):
        parser.parse_json(body)


def test_csv_framing_and_symlink_are_rejected(tmp_path: Path) -> None:
    bodies, _ = sample()
    with pytest.raises(parser.DetailInputError, match="CSV_FILE_BOUND_OR_LF"):
        parser.rows(bodies["knowledge"].rstrip(b"\r\n"), "knowledge")
    with pytest.raises(parser.DetailInputError, match="CSV_HEADER"):
        parser.rows(b"unexpected,header\n1,2\n", "knowledge")
    source = tmp_path / "source.csv"
    source.write_bytes(bodies["knowledge"])
    link = tmp_path / "link.csv"
    link.symlink_to(source)
    with pytest.raises(parser.DetailInputError, match="SYMLINK_FORBIDDEN"):
        parser.local_bytes(link)
