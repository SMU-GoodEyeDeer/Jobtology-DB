"""Bind SQL007 to its frozen input and the original evidence guard contract."""

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "capture_guard_worksets", ROOT / "hop/graph/tools/build_capture_guard_worksets.py"
)
assert spec and spec.loader
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


def test_generated_migration_is_exact_and_repeatable():
    assert ops.build() == (ROOT / "hop/graph/sql/007_capture_guard_worksets.sql").read_text()
    assert ops.build() == ops.build()


def test_changed_sealed_input_and_ambiguous_anchors_are_refused(tmp_path, monkeypatch):
    path = tmp_path / "source.sql"
    path.write_bytes(ops.SOURCE.read_bytes() + b"\n")
    monkeypatch.setattr(ops, "SOURCE", path)
    with pytest.raises(ValueError, match="Sealed SQL002 SHA256 changed"):
        ops.build()
    for value in ("missing", "anchor anchor"):
        with pytest.raises(ValueError, match="replacement contract changed"):
            ops.replace_once(value, "anchor", "changed")


def test_full_payload_grouping_retains_duplicate_and_null_rejection():
    sql = ops.build()
    assert sql.count("count(DISTINCT payload) AS payload_count") == 2
    assert sql.count("count(*) FILTER(WHERE NOT inserted) AS live_count") == 2
    assert sql.count("FROM evidence_groups WHERE has_inserted") == 2
    assert "run_id IS NULL OR record_id IS NULL OR identity_id IS NULL OR field IS NULL" in sql
    assert "to_jsonb(e) AS payload,true AS inserted" in sql
    assert "to_jsonb(l) AS payload,false AS inserted" in sql
    assert "UNION ALL" in sql


def test_guard_and_run_fences_are_unchanged():
    sql = ops.build()
    assert "FOR jobs IN SELECT DISTINCT run_id FROM new_evidence LOOP" in sql
    assert "IF invalid OR NOT ingestion.source_graph_run_is_valid(jobs)" in sql
    assert "THEN RAISE EXCEPTION 'INVALID_SOURCE_GRAPH_EVIDENCE'" in sql
    assert sql.count("CREATE OR REPLACE FUNCTION") == 1
    assert "p.provolatile='v' AND p.proparallel='u'" in sql
    assert "p.prorettype='trigger'::regtype" in sql
    assert "p.procost=100 AND p.prorows=0 AND p.prosupport=0 AND p.prokind='f'" in sql
    assert "p.probin IS NULL AND p.prosqlbody IS NULL AND p.provariadic=0" in sql
    assert "p.proconfig=ARRAY['jit=off']::text[]" in sql
    assert "SOURCE_GRAPH_CAPTURE_WORKSET_BASELINE_DRIFT" in sql
    assert "CREATE INDEX" not in sql
    assert "CREATE TABLE" not in sql


def test_exact_measured_hop_forms_are_whitelisted_without_normalization():
    old = ops.definition(ops.SOURCE.read_text())
    new = ops.candidate(ops.SOURCE.read_text())
    old_hop = ops.hop_body(old, ops.ORIGINAL_COMMENT_LINES)
    new_hop = ops.hop_body(new, ops.CANDIDATE_COMMENT_LINES)
    assert hashlib.md5(old_hop.encode()).hexdigest() == "6a7657e4685d2741814d77453466eeab"
    assert old_hop.count(" \n") == ops.body(old).count(" \n") + 4
    assert new_hop.count(" \n") == ops.body(new).count(" \n") + 4
    assert old_hop.replace(" \n", "\n") != old_hop
    hashes = re.search(r"md5\(p.prosrc\) IN \(([^)]*)\)", ops.build()).group(1)
    expected = [hashlib.md5(value.encode()).hexdigest() for value in
                (ops.body(old), ops.body(new), old_hop, new_hop)]
    assert expected[:2] == ["7bf7a02ce5d39bc3ae14e5617f5595a3",
                            "3dc06905ce059260c181d7f79c42f3c8"]
    assert hashes == ",".join("'" + value + "'" for value in expected)
    assert len(set(expected)) == 4
    assert "regexp_replace(p.prosrc" not in ops.build()
    for drift in (old_hop + "\n", old_hop.replace(" \n", "\n", 1),
                  new_hop.replace("RETURN NULL", "RETURN NEW")):
        assert hashlib.md5(drift.encode()).hexdigest() not in expected


def test_hop_form_refuses_unexpected_or_duplicated_comment_anchor():
    old = ops.definition(ops.SOURCE.read_text())
    for drift in (old.replace(ops.ORIGINAL_COMMENT_LINES[0], " -- unknown"),
                  old.replace(ops.ORIGINAL_COMMENT_LINES[0],
                              "\n".join([ops.ORIGINAL_COMMENT_LINES[0]] * 2))):
        with pytest.raises(ValueError, match="replacement contract changed"):
            ops.hop_body(drift, ops.ORIGINAL_COMMENT_LINES)
