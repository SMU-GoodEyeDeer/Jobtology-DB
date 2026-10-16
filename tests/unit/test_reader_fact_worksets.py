"""The additive entity join retains the sealed selection and execution contracts."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def generator():
    spec = importlib.util.spec_from_file_location(
        "reader_fact_worksets", ROOT / "hop/graph/tools/build_reader_fact_worksets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_additive_entity_join_only() -> None:
    build = generator()
    current = (ROOT / "hop/graph/sql/009_reader_fact_worksets.sql").read_text()
    assert build.build() == current == build.build()
    assert current.count("CREATE OR REPLACE FUNCTION") == 1
    assert "CREATE OR REPLACE FUNCTION ingestion.graph_source_entities(jobs text)" in current
    for forbidden in ("CREATE TABLE", "CREATE INDEX", "PARALLEL SAFE", "SET max_parallel"):
        assert forbidden not in current


def test_complete_history_assessments_rankings_and_grouping_are_frozen() -> None:
    build = generator()
    old = build.definition(build.SOURCE.read_text(), "graph_source_entities")
    new = build.candidate(build.SOURCE.read_text(), "graph_source_entities")
    # Everything before winner selection includes full validity, candidate
    # history and reference bags. Posting text-key grouping remains byte-exact.
    assert old.split(" facts AS MATERIALIZED", 1)[0] == new.split(" facts AS MATERIALIZED", 1)[0]
    assert old.split(" posting_records AS", 1)[1].split(" job_facts AS", 1)[0] == new.split(
        " posting_records AS", 1
    )[1].split(" posting_facts AS", 1)[0]
    assert old.split(" SELECT f.identity_id", 1)[1].split(" FROM current_facts", 1)[0] == new.split(
        " SELECT f.identity_id", 1
    )[1].split(" FROM current_facts", 1)[0]
    assert old.split(" ORDER BY f.identity_id;", 1)[1] == new.split(
        " ORDER BY f.identity_id;", 1
    )[1]
    assert "FROM posting_sets p)" in new
    assert "END AS normalized" in new
    assert "p.run_id=f.run_id AND p.source_id=f.source_id" in new
    assert "AND p.posting_id=f.posting_id" in new
    assert new.count("coalesce(p.normalized,f.normalized)") == 2


def test_exact_source_form_eligibility_and_merge_order_are_retained() -> None:
    build = generator()
    old = build.definition(build.SOURCE.read_text(), "graph_source_entities")
    new = build.candidate(build.SOURCE.read_text(), "graph_source_entities")
    for marker in (
        "p.source_id='job_alio' AND p.forms ?& ARRAY['list','detail']",
        "p.source_id='nara_job' AND p.forms ?& ARRAY['list','detail','positions','files']",
        "AND coalesce((p.forms->'list'->>'ongoing')::boolean,false)",
        "((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail'))-'representation'",
        "((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail')||jsonb_strip_nulls(p.forms->'positions')||jsonb_strip_nulls(p.forms->'files'))-'representation'",
    ):
        assert old.count(marker) == new.count(marker) == 1


def test_only_exact_bodies_and_complete_execution_metadata_are_accepted() -> None:
    build = generator()
    source = build.SOURCE.read_text()
    name = "graph_source_entities"
    old, new = build.definition(source, name), build.candidate(source, name)
    guard = build.guard(source, name, new)
    hashes = [hashlib.md5(build.body(item).encode()).hexdigest() for item in (old, new)]
    assert "md5(p.prosrc) IN ('" + "','".join(hashes) + "')" in guard
    for field in (
        "provolatile", "proparallel", "proisstrict", "prosecdef", "proleakproof", "proretset",
        "prolang", "prokind", "procost", "prorows", "prosupport", "probin", "prosqlbody",
        "pronargs", "proargtypes", "provariadic", "proargdefaults", "prorettype",
        "pronargdefaults", "proallargtypes", "proargnames", "proargmodes", "proconfig",
    ):
        assert "p." + field in guard
    assert "regexp_replace" not in guard
    assert "replace(p.prosrc" not in guard
    assert old.split("RETURNS TABLE", 1)[1].split("AS $$", 1)[0] == new.split(
        "RETURNS TABLE", 1
    )[1].split("AS $$", 1)[0]


def test_distinct_winners_keep_both_independent_complete_orders() -> None:
    build = generator()
    old = build.definition(build.SOURCE.read_text(), "graph_source_entities")
    new = build.candidate(build.SOURCE.read_text(), "graph_source_entities")
    for start, end in ((" facts AS MATERIALIZED", " names AS"), (" names AS", " current_facts AS")):
        before = old.split(start, 1)[1].split(end, 1)[0]
        after = new.split(start, 1)[1].split(end, 1)[0]
        old_order = before.split("ORDER BY", 1)[1].split(") AS choice", 1)[0]
        new_order = after.split("ORDER BY c.identity_id,", 1)[1].rsplit("),", 1)[0]
        assert "".join(old_order.split()) == "".join(new_order.split())
    assert "row_number()" not in new
    assert "choice=1" not in new
    assert new.split(" facts AS MATERIALIZED", 1)[0] == old.split(" facts AS MATERIALIZED", 1)[0]


def test_sealed_source_drift_and_replacement_anchor_drift_are_refused(tmp_path: Path) -> None:
    build = generator()
    copied = tmp_path / "008.sql"
    copied.write_text(build.SOURCE.read_text() + "\n-- drift\n")
    build.SOURCE = copied
    with pytest.raises(ValueError, match="Sealed SQL008 SHA256 changed"):
        build.build()
    with pytest.raises(ValueError, match="replacement contract changed"):
        build.replace_once("needle needle", "needle", "new")
    with pytest.raises(ValueError, match="Unsupported reader fact workset"):
        build.candidate("", "graph_source_edges")
