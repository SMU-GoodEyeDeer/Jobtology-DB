"""Additive readers retain sealed history/selection contracts."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def generator():
    spec = importlib.util.spec_from_file_location(
        "reader_worksets", ROOT / "hop/graph/tools/build_reader_worksets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_generated_reader_sql() -> None:
    build = generator()
    current = (ROOT / "hop/graph/sql/008_reader_worksets.sql").read_text()
    assert build.build() == current == build.build()
    assert "CREATE TABLE" not in current and "CREATE INDEX" not in current
    assert "PARALLEL SAFE" not in current and "MEMOIZE" not in current


def test_historical_candidates_priorities_and_guards_stay_exact() -> None:
    build = generator()
    source = build.SOURCE.read_text()
    for name in build.NAMES:
        old, new = build.definition(source, name), build.candidate(source, name)
        for marker in (
            "PERFORM ingestion.source_graph_assert_query_contract();",
            "ready_runs AS MATERIALIZED",
            "needed_edge_runs AS MATERIALIZED",
            "edge_assessments AS MATERIALIZED",
            "ingestion.source_graph_run_is_valid(u.run_id)",
            "ORDER BY q.identity_id,r.source_id,r.created_at DESC,r.run_id DESC",
            "jobs='ALL_CHECKPOINTED'",
            "WHERE d.selected",
        ):
            assert old.count(marker) == new.count(marker)
        assert (
            old.split("RETURNS TABLE", 1)[1].split("AS $$", 1)[0]
            == new.split("RETURNS TABLE", 1)[1].split("AS $$", 1)[0]
        )
    entity = build.candidate(source, "graph_source_entities")
    old_entity = build.definition(source, "graph_source_entities")
    for name in ("facts", "names"):
        before = old_entity.split(name + " AS", 1)[1].split("current_facts", 1)[0]
        assert before in entity
    assert "f.posting_id=r.posting_id" in entity
    assert "k.posting_id=f.posting_id" in entity
    assert "JOIN candidate_assessments a ON a.run_id=r.run_id AND a.valid" in entity


def test_all_canonical_reference_branches_and_null_gates_are_retained() -> None:
    build = generator()
    branches = build.reference_scans()
    assert branches.count("UNION ALL") == 10
    assert branches.count("IS NOT NULL") == 10
    for namespace, kind, key, field, predicate, digest in build.BRANCHES:
        assert namespace + ":" in branches
        assert "'" + kind + "'::text" in branches
        assert predicate in branches
        assert "'" + field + "'::text AS field" in branches
        assert "r.normalized->>'" + key + "' IS NOT NULL" in branches
        if digest:
            assert "sha256(convert_to(r.normalized->>'" + key + "','UTF8'))" in branches
    assert "'ExamSession',r.source_record_id,'source_record_id'" in branches


def test_source_drift_is_refused(tmp_path: Path) -> None:
    build = generator()
    copied = tmp_path / "003.sql"
    copied.write_text(build.SOURCE.read_text() + "\n-- drift\n")
    build.SOURCE = copied
    with pytest.raises(ValueError, match="Sealed SQL003 SHA256 changed"):
        build.build()
