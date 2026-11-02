"""Exact source ownership, deletion boundaries and fresh graph publication pins."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "cutover_jobkorea_graph", ROOT / "hop/operations/cutover_jobkorea_graph.py"
)
assert SPEC and SPEC.loader
cutover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover)


def framed(*items):
    return "".join(str(len(value)) + ":" + value for value in items)


def properties(**items):
    return framed(
        *(part for key, value in sorted(items.items()) for part in (key, "STRING NOT NULL", value))
    )


def node(eid, identity, *, labels=("entity", "jobPosting"), kind="JobPosting", **props):
    return [eid, framed(*labels), properties(id=identity, kind=kind, **props)]


def snapshot(tmp_path, nodes, edges=(), label="before"):
    path = tmp_path / (label + ".sqlite")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,PRIMARY KEY(kind,eid))")
    for kind, rows in (("NODE", nodes), ("REL", edges)):
        db.executemany(
            "INSERT INTO snapshot VALUES(?,?,?)", [(kind, row[0], framed(*row)) for row in rows]
        )
    db.commit()
    db.close()
    return path


def fixture():
    old, kept, new = (cutover.identity(value) for value in ("old", "kept", "new"))
    nodes = [
        node("1", old),
        node("2", kept),
        node("3", "ncs:occupation:123", labels=("entity", "occupation"), kind="Occupation"),
        node("4", "source:posting:nara_job:other", source_id="nara_job"),
    ]
    edges = [
        ["r1", "1", "3", "INFERRED_NCS_OCCUPATION", properties(candidate_id="old")],
        ["r2", "2", "3", "INFERRED_NCS_OCCUPATION", properties(candidate_id="stale")],
        ["r3", "4", "3", "INFERRED_NCS_OCCUPATION", properties(candidate_id="nara")],
    ]
    return old, kept, new, nodes, edges


def test_exact_source_scope_removes_all_old_mappings_and_absent_nodes(tmp_path):
    _, kept, new, nodes, edges = fixture()
    scope = cutover.classify(snapshot(tmp_path, nodes, edges), {kept, new})
    assert scope["retire_nodes"] == ["1"]
    assert scope["remove_edges"] == ["r1", "r2"]
    after = cutover.classify(snapshot(tmp_path, nodes[1:], edges[2:], "after"), {kept, new})
    cutover.protected_equal(scope, after)
    assert after["retire_nodes"] == after["remove_edges"] == []


def test_unknown_retired_attachments_stop_instead_of_detach_delete(tmp_path):
    _, kept, new, nodes, edges = fixture()
    edges.append(["user", "4", "1", "USER_SAVED", properties(owner="user")])
    with pytest.raises(RuntimeError, match="unexpected attachment"):
        cutover.classify(snapshot(tmp_path, nodes, edges), {kept, new})


def test_source_marker_cannot_authorize_arbitrary_catalogue_removal(tmp_path):
    bad = node("bad", "ncs:occupation:shared", source_id="jobkorea")
    with pytest.raises(RuntimeError, match="unexpected graph identity"):
        cutover.classify(snapshot(tmp_path, [bad]), set())


def test_duplicate_source_identity_is_rejected(tmp_path):
    identity = cutover.identity("one")
    with pytest.raises(RuntimeError, match="Duplicate"):
        cutover.classify(snapshot(tmp_path, [node("1", identity), node("2", identity)]), {identity})


def test_shared_catalogue_property_change_is_detected(tmp_path):
    _, kept, new, nodes, edges = fixture()
    before = cutover.classify(snapshot(tmp_path, nodes, edges), {kept, new})
    nodes[2] = node(
        "3",
        "ncs:occupation:123",
        labels=("entity", "occupation"),
        kind="Occupation",
        name="changed",
    )
    after = cutover.classify(snapshot(tmp_path, nodes, edges, "after"), {kept, new})
    with pytest.raises(RuntimeError, match="protected graph object"):
        cutover.protected_equal(before, after)


def test_delete_query_uses_only_bounded_exact_element_ids_and_never_detach():
    for kind in ("NODE", "REL"):
        query = cutover.delete_query(kind, ['eid"withquote', "other"])
        assert "DETACH" not in query
        assert cutover.PREFIX in query
        assert json.dumps(['eid"withquote', "other"]) in query
    assert "INFERRED_NCS_OCCUPATION" in cutover.delete_query("REL", ["one"])
    assert "INFERRED_ONET_OCCUPATION" in cutover.delete_query("REL", ["one"])
    for kind, ids in (("ALL", ["one"]), ("NODE", []), ("REL", ["x"] * 201)):
        with pytest.raises(ValueError):
            cutover.delete_query(kind, ids)


def test_immutable_manifest_cannot_be_overwritten(tmp_path):
    path = tmp_path / "manifest.json"
    cutover.immutable_json(path, {"cohort": ["one"]})
    with pytest.raises(FileExistsError):
        cutover.immutable_json(path, {"cohort": ["two"]})
    assert path.stat().st_mode & 0o777 == 0o600


def test_fresh_mapping_verification_rejects_old_publication_and_missing_edges(tmp_path):
    identity = cutover.identity("one")
    nodes = [
        node("1", identity, source_run_id="new"),
        node("3", "ncs:occupation:123", labels=("entity", "occupation"), kind="Occupation"),
    ]
    wanted = {
        "cohort": [identity],
        "ncs_token": "fresh-token",
        "onet_publication": "fresh-onet",
        "ncs": [
            {
                "posting_identity": identity,
                "occupation_identity": "ncs:occupation:123",
                "candidate_id": "fresh",
                "payload_json": "{}",
                "payload_hash": "hash",
            }
        ],
        "onet": [],
    }
    manifest = {"expected": wanted, "replacement": {"job_run_id": "new", "ncs_run_id": "ncs"}}
    props = dict(
        candidate_id="fresh",
        job_run_id="new",
        ncs_run_id="ncs",
        projection_token="old-token",
        payload_json="{}",
        payload_hash="hash",
    )
    edge = ["r1", "1", "3", "INFERRED_NCS_OCCUPATION", properties(**props)]
    with pytest.raises(RuntimeError, match="publication/source pin"):
        cutover.prove_fresh(snapshot(tmp_path, nodes, [edge]), manifest)
    with pytest.raises(RuntimeError, match="incomplete"):
        cutover.prove_fresh(snapshot(tmp_path, nodes, [], "missing"), manifest)
    props["projection_token"] = "fresh-token"
    edge[-1] = properties(**props)
    assert cutover.prove_fresh(snapshot(tmp_path, nodes, [edge], "fresh"), manifest) == {
        "posting_count": 1,
        "ncs_count": 1,
        "onet_count": 0,
    }


def test_publication_scalar_values_keep_types():
    assert cutover.scalar_equal(["BOOLEAN NOT NULL", "false"], False)
    assert not cutover.scalar_equal(["STRING NOT NULL", "false"], False)
    assert cutover.scalar_equal(["INTEGER NOT NULL", "3"], 3)
    assert not cutover.scalar_equal(["FLOAT NOT NULL", "3.0"], 3)
    assert cutover.scalar_equal(None, None)
    assert not cutover.scalar_equal(["STRING NOT NULL", "null"], None)


def test_sql_fence_filters_all_history_without_deleting_evidence():
    sql = (ROOT / "hop/graph/sql/009_reader_fact_worksets.sql").read_text()
    assert "JOBKOREA_GRAPH_REPLACEMENT_FENCED" in sql
    assert "AND ingestion.jobkorea_graph_allowed_run(u.run_id)" in sql
    assert "WHERE ingestion.jobkorea_graph_allowed_run(u.run_id)" in sql
    assert "current_plan->>'job_run_id'=jobs" in sql
    assert "DELETE FROM" not in sql
    assert "CREATE OR REPLACE FUNCTION ingestion.source_graph_run_is_valid" not in sql


def test_already_published_fresh_edges_survive_old_mapping_removal(tmp_path):
    _, kept, new, nodes, edges = fixture()
    fresh = [
        "fresh-edge",
        "2",
        "3",
        "INFERRED_NCS_OCCUPATION",
        properties(candidate_id="fresh", projection_token="new-token"),
    ]
    wanted = {
        "ncs_token": "new-token",
        "onet_publication": "onet-new",
        "onet": [],
        "ncs": [
            {
                "candidate_id": "fresh",
                "posting_identity": kept,
                "occupation_identity": "ncs:occupation:123",
            }
        ],
    }
    scope = cutover.classify(snapshot(tmp_path, nodes, [*edges, fresh]), {kept, new}, "run", wanted)
    assert scope["remove_edges"] == ["r1", "r2"]
    after = cutover.classify(
        snapshot(tmp_path, nodes[1:], [edges[2], fresh], "after"), {kept, new}, "run", wanted
    )
    assert after["retire_nodes"] == after["remove_edges"] == []
    cutover.protected_equal(scope, after)


def test_postgres_preservation_includes_onet_catalogue_and_userdata_without_detoasting_input(
    monkeypatch,
):
    queries = []

    def rows(pg, query):
        queries.append(query)
        if "FROM pg_class" in query:
            return [
                {"schema": schema, "name": name}
                for schema, name in (
                    ("classification", "term"),
                    ("onet_matching", "input"),
                    ("public", "users"),
                )
            ]
        return [{"row_count": 3, "sha256": "stable"}]

    monkeypatch.setattr(cutover.graph, "pg_rows", rows)
    state = cutover.postgres_state("synthetic")
    assert set(state) == {"classification.term", "onet_matching.input", "public.users"}
    assert state["public.users"]["basis"] == "FULL_ROW_SHA256"
    assert state["onet_matching.input"]["basis"] == "IMMUTABLE_INPUT_CONTENT_PINS_SHA256"
    compact = next(query for query in queries if 'FROM "onet_matching"."input"' in query)
    assert "to_jsonb(t)" not in compact
    for field in (
        "source_facts_sha256",
        "source_hash",
        "candidates_hash",
        "request_hash",
        "input_hash",
    ):
        assert field in compact
