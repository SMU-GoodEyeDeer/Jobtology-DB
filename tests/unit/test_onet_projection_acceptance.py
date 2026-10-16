"""Exact scoped graph acceptance without provider calls or graph mutations."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("onet_projection_acceptance",
                                            OPS / "verify_onet_projection.py")
assert SPEC and SPEC.loader
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
DATABASE_ID = "frozen-neo4j-database-id"


def frame(*values: str) -> str:
    return "".join(str(len(value)) + ":" + value for value in values)


def fixture():
    source = {"posting_id": "source:posting:jobkorea:1", "source_id": "jobkorea",
              "source_run_id": "run", "source_record_id": "1", "source_facts_sha256": "hash",
              "source_facts": {"title": "채용", "ongoing": True}}
    source_row = "SOURCE" + frame(source["posting_id"], "jobkorea", "run", "1", "hash",
                                 json.dumps(source["source_facts"]))
    edge_id = verify.EDGE_PREFIX + "one"
    properties = {"id": edge_id, "managed_by": verify.OWNER, "match_rank": 1,
                  "current": False, "stage": "STAGING", "confidence_state": "UNASSESSED",
                  "review_status": "UNREVIEWED"}
    plan = {"edge_id": edge_id, "posting_identity": source["posting_id"],
            "occupation_identity": "urn:jobtology:onet:occupation:15-1252.00",
            "properties": properties}
    signature = "".join(frame(key, *verify.typed_property(value))
                        for key, value in sorted(properties.items()))
    edge = "EDGE" + frame(edge_id, "INFERRED_ONET_OCCUPATION", source["posting_id"],
                          plan["occupation_identity"], "true", signature)
    counts = "COUNT" + frame(str(verify.BASE_NODES), str(verify.BASE_EDGES + 1),
                             str(verify.NCS_EDGES), DATABASE_ID)
    return source, plan, [counts, source_row, edge]


def test_exact_typed_edges_accept_staging_current_false_and_unassessed_confidence():
    source, plan, rows = fixture()
    result = verify.verify_rows(rows, [source], [plan], False, DATABASE_ID)
    assert result["owned_onet_edges"] == 1 and result["review_states"] == {"UNREVIEWED": 1}


@pytest.mark.parametrize("change", ["typed-rank", "endpoints", "duplicate", "baseline",
                                   "database"])
def test_owned_edge_or_legacy_baseline_drift_fails(change):
    source, plan, rows = fixture()
    if change == "typed-rank":
        rows[-1] = rows[-1].replace(frame("match_rank", "INTEGER NOT NULL", "1"),
                                  frame("match_rank", "FLOAT NOT NULL", "1.0"))
    elif change == "endpoints":
        rows[-1] = rows[-1].replace(frame("true"), frame("false"), 1)
    elif change == "duplicate":
        rows.append(rows[-1])
    elif change == "baseline":
        rows[0] = "COUNT" + frame(str(verify.BASE_NODES), str(verify.BASE_EDGES + 2),
                                  str(verify.NCS_EDGES), DATABASE_ID)
    else:
        rows[0] = rows[0].replace(frame(DATABASE_ID), frame("foreign-database-id"))
    with pytest.raises(RuntimeError):
        verify.verify_rows(rows, [source], [plan], False, DATABASE_ID)


def test_unpublished_quality_hold_accepts_zero_edges_and_rejects_any_publication():
    source, plan, rows = fixture()
    rows[0] = "COUNT" + frame(str(verify.BASE_NODES), str(verify.BASE_EDGES),
                              str(verify.NCS_EDGES), DATABASE_ID)
    result = verify.verify_rows(rows[:2], [source], [plan], True, DATABASE_ID)
    assert result["owned_onet_edges"] == 0
    with pytest.raises(RuntimeError):
        verify.verify_rows(rows, [source], [plan], True, DATABASE_ID)


def test_frozen_source_json_boolean_type_changes_fail_even_with_unchanged_hash():
    source, plan, rows = fixture()
    tampered = dict(source["source_facts"], ongoing=1)
    rows[1] = "SOURCE" + frame(source["posting_id"], "jobkorea", "run", "1", "hash",
                              json.dumps(tampered))
    with pytest.raises(RuntimeError, match="source posting"):
        verify.verify_rows(rows, [source], [plan], False, DATABASE_ID)


def test_native_query_has_no_write_or_staging_current_filter():
    query = verify.query()
    assert all(command not in query for command in ("MERGE ", "CREATE ", "DELETE ", "SET "))
    assert "r.current=true" not in query
    assert "b.current=true" in query
    assert "source_facts_json IS NOT NULL" in query
    assert "a.kind='JobPosting'" in query
    assert "r.source_facts_sha256=a.source_facts_sha256" in query
    assert "MATCH(n:entity:jobPosting) WHERE n.kind='JobPosting'" in query
    assert "CALL db.info() YIELD id AS database_id" in query


def test_bound_current_baseline_keeps_exact_source_facts_and_edge_checks():
    source, plan, rows = fixture()
    rows[0] = "COUNT" + frame(str(verify.BASE_NODES + 94), str(verify.BASE_EDGES + 1),
                             str(verify.NCS_EDGES), DATABASE_ID)
    with pytest.raises(RuntimeError, match="baseline"):
        verify.verify_rows(rows, [source], [plan], False, DATABASE_ID)
    result = verify.verify_rows(rows, [source], [plan], False, DATABASE_ID,
                                [verify.BASE_NODES + 94, verify.BASE_EDGES, verify.NCS_EDGES])
    assert result["nodes"] == verify.BASE_NODES + 94
    rows[1] = rows[1].replace(frame("hash"), frame("changed-hash"))
    with pytest.raises(RuntimeError, match="source posting"):
        verify.verify_rows(rows, [source], [plan], False, DATABASE_ID,
                           [verify.BASE_NODES + 94, verify.BASE_EDGES, verify.NCS_EDGES])


def test_combined_completed_coverage_counts_rejected_and_skipped_without_retries():
    attempts = [{"posting_identity": str(n), "state": state,
                 "reserved_at": None if state == "SKIPPED" else "time",
                 "cost_usd": None if state == "SKIPPED" else "0.01",
                 "is_byok": None if state == "SKIPPED" else True}
                for n, state in enumerate(("VALIDATED", "REJECTED", "SKIPPED"))]
    result = verify.completed_coverage(attempts, {"0", "1", "2"}, complete=True)
    assert result["scope_complete"] and result["completed_source_postings"] == 3
    with pytest.raises(RuntimeError, match="repeat"):
        verify.completed_coverage([*attempts, attempts[0]], {"0", "1", "2"}, complete=True)
    with pytest.raises(RuntimeError, match="cover"):
        verify.completed_coverage(attempts[:2], {"0", "1", "2"}, complete=True)
    with pytest.raises(RuntimeError, match="later arrival"):
        verify.completed_coverage(attempts, {"0", "1"}, complete=True)
