"""Frozen generation and guarded installer ordering for validation worksets."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validation_worksets", ROOT / "hop/graph/tools/build_validation_worksets.py")
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def test_generated_candidate_is_byte_exact_and_repeatable():
    expected = (ROOT / "hop/graph/sql/005_validation_worksets.sql").read_text()
    assert ops.build() == expected == ops.build()


def test_changed_frozen_rules_cannot_silently_regenerate(tmp_path, monkeypatch):
    source = tmp_path / "source.sql"
    source.write_text(ops.SOURCE.read_text().replace("'NARA_POSTING_CONFLICT'", "'NEW_RULE'"))
    monkeypatch.setattr(ops, "SOURCE", source)
    with pytest.raises(ValueError, match="Frozen SQL003 SHA256 changed"):
        ops.build()


def test_ambiguous_or_missing_rewrite_contract_is_refused():
    for value in ("unchanged", "anchor anchor"):
        with pytest.raises(ValueError, match="replacement contract changed"):
            ops.replace_once(value, "anchor", "replacement")
