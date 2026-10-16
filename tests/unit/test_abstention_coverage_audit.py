from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "abstention_coverage_audit",
    ROOT / "hop/ingestions/jobkorea/tools/audit_abstention_coverage.py",
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def row(title: str, original: list[str], current: list[str] | None) -> dict:
    return {
        "source_record_id": "local-example",
        "posting_id": "frozen-example",
        "source_hash": "source-a",
        "binding_source_hash": "source-a",
        "fields": {"title": title},
        "output": {"outcome": "abstained"},
        "frozen_candidates": [{"occupation_code": c} for c in original],
        "v3_candidates": None if current is None else [{"occupation_code": c} for c in current],
        "original_candidate_limit": "12",
    }


def test_export_uses_exact_selected_binding_and_read_only_snapshot() -> None:
    sql = audit.export_sql(audit.JOBS, audit.NCS)
    assert sql.startswith("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;")
    assert "JOIN enrichment.input_bundle ib ON ib.bundle_id=b.bundle_id" in sql
    assert "b.source_hash AS binding_source_hash" in sql
    assert "DISTINCT ON(posting_id) ib.*" not in sql
    assert "prepare_metadata_occupation" not in sql
    assert "plan_metadata_occupation" not in sql
    assert "source_data->'url'" not in sql
    assert audit.NCS in sql
    assert "statement_timeout='1800s'" in sql


def test_untrusted_snapshot_identifier_is_rejected() -> None:
    with pytest.raises(ValueError):
        audit.export_sql("snapshot'; SELECT secret; --", audit.NCS)


def test_export_rejects_repository_destination_before_database_access() -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        audit.export("abcdef123456", ROOT / "accidental-raw.json", audit.JOBS, audit.NCS)


def test_private_receipt_modes_and_symlink_rejection(tmp_path: Path) -> None:
    target = tmp_path / "private" / "receipt.json"
    audit.private_write(target, b"{}")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    victim = tmp_path / "other.json"
    victim.write_text("preserve")
    link = target.parent / "link.json"
    link.symlink_to(victim)
    with pytest.raises(OSError):
        audit.private_write(link, b"replace")
    assert victim.read_text() == "preserve"


def test_export_validation_rejects_source_binding_mismatch() -> None:
    r = row("ML Engineer", [], [])
    r["binding_source_hash"] = "different"
    with pytest.raises(ValueError, match="selected result binding"):
        audit.validate_export(
            {
                "contract": audit.CONTRACT,
                "read_only": "on",
                "summary": {"abstained": 1},
                "rows": [r],
            }
        )


def test_original_and_counterfactual_candidates_remain_distinct() -> None:
    r = row("Machine Learning Engineer", ["15090305"], ["20010703"])
    catalogue = [
        {"occupation_code": code, "occupation_name": code, "unit_names": [], "context_hash": code}
        for code in {code for _, codes in audit.FAMILY_RULES.values() for code in codes}
    ]
    result = audit.candidate_families(
        {"rows": [r], "catalogue": catalogue, "counterfactual_recomputed": True}
    )
    family = result["english_machine_learning_role"]
    assert family["frozen_missing"] == 1 and family["v3_missing"] == 0
    assert family["rows"][0]["review_status"] == "HEURISTIC_CANDIDATE_PLAUSIBILITY_UNREVIEWED"
    assert family["rows"][0]["field_evidence"] == [
        {"field": "title", "text": "Machine Learning Engineer"}
    ]


def test_baseline_does_not_claim_counterfactual_change() -> None:
    sql = audit.export_sql(audit.JOBS, audit.NCS, counterfactual=False)
    assert "NULL::jsonb AS v3_candidates" in sql
    assert "'counterfactual_recomputed',false" in sql
    assert "v3_shortlist_changed" not in audit.diagnostic_flags(row("ML Engineer", [], None))


def test_course_and_product_boundaries_do_not_become_reviewed_matches() -> None:
    flags = audit.diagnostic_flags(row("국비 교육생 Machine Learning Engineer 과정", [], []))
    assert audit.primary_group(flags) == "course_or_employment_support_terms"
    product = audit.diagnostic_flags(row("AI Product Manager (PM)", [], []))
    assert audit.primary_group(product) == "product_management_terms"
    assert "research_data_ai_terms" not in audit.diagnostic_flags(
        row("Blockchain Engineer", [], [])
    )
    for title in ("Retail Operations", "Chain planner", "email support"):
        assert "research_data_ai_terms" not in audit.diagnostic_flags(row(title, [], []))


def test_bound_projection_verification_allows_only_counterfactual_candidate_changes() -> None:
    r = row("ML Engineer", [], None)
    r.update(
        {
            "bundle_id": "selected-bundle",
            "raw_allowed_fields": r["fields"],
            "item_id": "selected-item",
            "result_id": "selected-result",
            "binding_hash": "binding-a",
        }
    )
    baseline = {
        "contract": audit.CONTRACT,
        "read_only": "on",
        "jobs": "exact-job",
        "ncs": "exact-ncs",
        "catalogue_context_hash": "frozen-catalogue",
        "summary": {"abstained": 1},
        "rows": [r],
    }
    comparison = {**baseline, "rows": [{**r, "v3_candidates": [{"occupation_code": "20010703"}]}]}
    assert audit.verify_bound_projection(baseline, comparison)["verified"] is True
    comparison["rows"][0]["fields"] = {"title": "Unbound substituted evidence"}
    with pytest.raises(ValueError, match="evidence differs"):
        audit.verify_bound_projection(baseline, comparison)
