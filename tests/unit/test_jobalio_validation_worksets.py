"""SQL006 must derive exactly from sealed SQL005 and keep a narrow rollout."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))


def module(relative):
    spec = importlib.util.spec_from_file_location(relative, ROOT / relative)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ops = module("hop/graph/tools/build_jobalio_validation_worksets.py")
deployment = module("hop/operations/deploy_jobalio_validation_runtime.py")


def test_candidate_generation_is_byte_exact_and_repeatable():
    assert ops.build() == (ROOT / "hop/graph/sql/006_jobalio_validation_worksets.sql").read_text()
    assert ops.build() == ops.build()


def test_sealed_source_mutation_is_refused(tmp_path, monkeypatch):
    source = tmp_path / "source.sql"
    source.write_text(ops.SOURCE.read_text().replace("'POSTING_PAIR_CONFLICT'", "'NEW_RULE'"))
    monkeypatch.setattr(ops, "SOURCE", source)
    with pytest.raises(ValueError, match="Sealed SQL005 SHA256 changed"):
        ops.build()


def test_ambiguous_rewrite_is_refused():
    for value in ("unchanged", "anchor anchor"):
        with pytest.raises(ValueError, match="replacement contract changed"):
            ops.replace_once(value, "anchor", "replacement")


def test_five_arrays_are_zipped_with_detail_gate_and_no_boolean_cast():
    after = ops.CONFLICT_AFTER
    assert "unnest(g.list_titles,g.list_organizations,g.list_dates," in after
    assert "g.detail_ongoing,g.detail_ongoing_present)" in after
    assert "d.ongoing_present AND l.ongoing IS DISTINCT FROM d.ongoing" in after
    assert "::boolean" not in ops.WORKSETS + after
    assert "WHERE posting_id IS NOT NULL" in ops.WORKSETS


def test_narrow_bundle_and_configuration_restore():
    additive = deployment.validation.routine.additive
    original = additive.KIND, additive.MIGRATIONS, additive.ALLOWLIST
    with deployment.configured():
        assert additive.KIND == deployment.KIND
        assert additive.MIGRATIONS == ("graph/sql/006_jobalio_validation_worksets.sql",)
        assert len(additive.ALLOWLIST) == 3
        assert additive.require_preserved is deployment.validation.require_preserved
        with pytest.raises(ValueError, match="complete coherent"):
            additive.selected([deployment.MIGRATIONS[0]])
    assert original == (additive.KIND, additive.MIGRATIONS, additive.ALLOWLIST)
