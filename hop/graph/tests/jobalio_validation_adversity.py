"""Independent JOBALIO conflict bags in the owned schema-only SQL oracle.

Each synthetic mutation rolls back. Explicit expected conflict rows supplement
the frozen public-view comparison, including JSONB type and missing-field rules.
The fixture uses the oracle's existing two selected JOBALIO documents only.
"""

from __future__ import annotations

import json
from typing import Any

MISSING = object()
FIELDS = ("title", "organization_code", "date_posted", "closing_date")


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def posting(representation: Any, **fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        kind="JobPosting",
        posting_id="123",
        representation=representation,
        title="Legacy",
        organization_code="o",
        date_posted="2026-10-01",
        closing_date="2026-10-31",
    )
    result.update(fields)
    return {name: value for name, value in result.items() if value is not MISSING}


def replace_rows(rows: list[dict[str, Any]]) -> str:
    payload = [dict(name="row" + str(index), normalized=value) for index, value in enumerate(rows)]
    return (
        "DELETE FROM ingestion.record WHERE run_id='job_alio';"
        "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,"
        "source_payload,normalized) SELECT 'job_alio',"
        "CASE WHEN v.normalized->>'representation'='list' THEN 'index' ELSE 'detail-123' END,"
        "v.name,v.name,'{}',v.normalized FROM jsonb_to_recordset("
        + literal(json.dumps(payload, ensure_ascii=False))
        + "::jsonb) v(name text,normalized jsonb)"
    )


def compare(
    oracle: Any,
    label: str,
    rows: list[dict[str, Any]],
    expected_locations: list[str],
    *,
    suffix: str = "",
) -> None:
    statement = (
        "BEGIN; SET LOCAL session_replication_role=replica;"
        + replace_rows(rows)
        + ";"
        + suffix
        + ";"
        "WITH scoped AS MATERIALIZED ("
        "SELECT * FROM ingestion.source_graph_validation_issue('job_alio')),"
        "canonical AS MATERIALIZED ("
        "SELECT * FROM ingestion.validation_issue WHERE run_id='job_alio')"
        "SELECT jsonb_build_object('bag_equal',"
        "(SELECT jsonb_agg(to_jsonb(v) ORDER BY issue,location) FROM scoped v)"
        " IS NOT DISTINCT FROM "
        "(SELECT jsonb_agg(to_jsonb(v) ORDER BY issue,location) FROM canonical v),"
        "'conflicts',(SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY location),'[]') "
        "FROM scoped v WHERE issue='POSTING_PAIR_CONFLICT'));ROLLBACK;"
    )
    value = json.loads(oracle.sql(statement))
    expected = [
        dict(run_id="job_alio", issue="POSTING_PAIR_CONFLICT", location=location)
        for location in sorted(expected_locations)
    ]
    oracle.check("jobalio-public-issue-bag-" + label, value["bag_equal"])
    oracle.check("jobalio-independent-conflict-bag-" + label, value["conflicts"] == expected)
    oracle.check(
        "jobalio-rollback-fresh-validation-" + label,
        oracle.sql("SELECT ingestion.source_graph_run_is_valid('job_alio')") == "t",
    )


def run(oracle: Any) -> None:
    # Ordinary JSONB fields distinguish SQL NULL (missing) from JSON null and
    # retain types. JSONB number scale and object-key order are irrelevant.
    values = (
        ("both-missing", MISSING, MISSING, 0),
        ("missing-json-null", MISSING, None, 1),
        ("json-null-missing", None, MISSING, 1),
        ("both-json-null", None, None, 0),
        ("numeric-text", 7, "7", 1),
        ("numeric-scale", 7, 7.0, 0),
        ("boolean-text", False, "false", 1),
        ("empty-text-null", "", None, 1),
        ("equal-object-key-order", {"a": 1, "b": None}, {"b": None, "a": 1}, 0),
        ("array-order", ["A", None, "B"], ["B", None, "A"], 1),
    )
    for field in FIELDS:
        for label, left, right, conflicts in values:
            compare(
                oracle,
                field + "-" + label,
                [posting("list", **{field: left}), posting("detail", **{field: right})],
                ["123"] * conflicts,
            )

    # Only detail ->>ongoing IS NOT NULL enables this JSONB comparison. It is
    # not a Boolean cast: arbitrary non-null JSON and strings remain comparable.
    ongoing = (
        ("detail-missing", True, MISSING, 0),
        ("detail-json-null", True, None, 0),
        ("list-missing-detail-false", MISSING, False, 1),
        ("list-json-null-detail-false", None, False, 1),
        ("false-true", False, True, 1),
        ("numeric-text", 7, "7", 1),
        ("malformed-text-equal", "malformed", "malformed", 0),
        ("empty-text-enabled", MISSING, "", 1),
        ("object-equal", {"v": False}, {"v": False}, 0),
        ("array-different", [], [None], 1),
    )
    for label, left, right, conflicts in ongoing:
        compare(
            oracle,
            "ongoing-" + label,
            [posting("list", ongoing=left), posting("detail", ongoing=right)],
            ["123"] * conflicts,
        )

    compare(
        oracle,
        "duplicate-two-by-two",
        [
            posting("list", title="A"),
            posting("list", title="A"),
            posting("detail", title="B"),
            posting("detail", title="B"),
        ],
        ["123"] * 4,
    )
    compare(
        oracle,
        "duplicates-partially-conflict",
        [
            posting("list", title="A"),
            posting("list", title="B"),
            posting("detail", title="A"),
            posting("detail", title="C"),
        ],
        ["123"] * 3,
    )
    compare(
        oracle,
        "field-array-correspondence",
        [
            posting("list", title="A", organization_code="B"),
            posting("list", title="B", organization_code="A"),
            posting("detail", title="A", organization_code="A"),
            posting("detail", title="B", organization_code="B"),
        ],
        ["123"] * 4,
    )
    compare(
        oracle,
        "gate-array-correspondence",
        [
            posting("list", title="A", ongoing=True),
            posting("list", title="B", ongoing=False),
            posting("detail", title="A", ongoing=None),
            posting("detail", title="B", ongoing=False),
        ],
        ["123"] * 2,
    )
    compare(
        oracle,
        "multiple-field-conflict-emits-once",
        [
            posting("list", title="A", organization_code="one", ongoing=False),
            posting("detail", title="B", organization_code="two", ongoing=True),
        ],
        ["123"],
    )

    for label, left, right, locations in (
        ("missing-ids-do-not-join", MISSING, MISSING, []),
        ("null-ids-do-not-join", None, None, []),
        ("empty-ids-join", "", "", [""]),
        ("numeric-text-ids-join", 123, "123", ["123"]),
        ("object-text-ids-join", {"a": 1}, '{"a": 1}', ['{"a": 1}']),
        ("different-ids-do-not-join", "left", "right", []),
    ):
        compare(
            oracle,
            label,
            [
                posting("list", posting_id=left, title="A"),
                posting("detail", posting_id=right, title="B"),
            ],
            locations,
        )

    compare(oracle, "list-only", [posting("list", title="A"), posting("list", title="B")], [])
    compare(oracle, "detail-only", [posting("detail", title="A"), posting("detail", title="B")], [])
    compare(
        oracle,
        "unrecognized-representation-excluded",
        [posting("list"), posting("detail"), posting("unknown", title="conflict")],
        [],
    )
    compare(
        oracle,
        "nontext-representation-excluded",
        [posting("list"), posting("detail"), posting(["list"], title="conflict")],
        [],
    )
    compare(
        oracle,
        "unselected-list-document-excluded",
        [posting("list", title="A"), posting("detail", title="B")],
        [],
        suffix=(
            "UPDATE ingestion.document SET selected=false WHERE run_id='job_alio' "
            "AND document_id='index'"
        ),
    )
    compare(
        oracle,
        "unselected-detail-document-excluded",
        [posting("list", title="A"), posting("detail", title="B")],
        [],
        suffix=(
            "UPDATE ingestion.document SET selected=false WHERE run_id='job_alio' "
            "AND document_id='detail-123'"
        ),
    )
