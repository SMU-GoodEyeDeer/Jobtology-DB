"""Continuation authorization keeps current evidence and paid scopes disjoint."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
import onet_continuation as continuation  # noqa: E402


def test_physician_policy_replay_rejects_bypassed_candidates_before_prepare(monkeypatch, tmp_path):
    runner = continuation.runner
    decision = {"policy_version": "policy", "policy_sha256": "a" * 64,
                "physician_role_present": True, "physician_only": True,
                "eligible_occupation_codes": [], "evidence": [], "reason_code": "GENERIC"}
    code = SimpleNamespace(PHYSICIAN_ELIGIBILITY_VERSION="policy",
                           PHYSICIAN_ELIGIBILITY_HASH="a" * 64,
                           PHYSICIAN_OCCUPATION_CODES=["29-1216.00"],
                           physician_eligibility=lambda fields: decision)
    monkeypatch.setattr(runner, "frozen_module", lambda *args: code)
    monkeypatch.setattr(runner, "frozen_prompt", lambda *args: SimpleNamespace(
        admitted_fields=lambda facts: facts))
    row = {"source_facts": {"title": "의사"}, "source_fields": {"title": "의사"},
           "physician_eligibility_decision": copy.deepcopy(decision), "candidates": []}
    manifest = {"rows": [row], "settings": {
        "physician_eligibility_policy_sha256": "a" * 64,
        "physician_eligibility_policy_version": "policy"}}
    runner.verify_frozen_physician_eligibility(tmp_path, manifest)
    row["candidates"] = [{"occupation_code": "29-1216.00"}]
    writes = []
    monkeypatch.setattr(runner, "sql_json", lambda *args: writes.append(args))
    with pytest.raises(RuntimeError, match="bypasses"):
        runner.prepare_inputs({"pg": "unused"}, manifest, tmp_path, {}, tmp_path / "receipt")
    assert writes == []
    row["candidates"] = []
    row["physician_eligibility_decision"]["reason_code"] = "ALTERED"
    with pytest.raises(RuntimeError, match="decision differs"):
        runner.verify_frozen_physician_eligibility(tmp_path, manifest)
    decision["eligible_occupation_codes"] = ["29-1216.00"]
    row["physician_eligibility_decision"] = copy.deepcopy(decision)
    row["candidates"] = [{"occupation_code": "25-1071.00"}]
    with pytest.raises(RuntimeError, match="bypasses"):
        runner.verify_frozen_physician_eligibility(tmp_path, manifest)


def test_legacy_manifest_without_physician_policy_does_not_load_new_code(monkeypatch, tmp_path):
    def fail(*args):
        raise AssertionError("Legacy manifest imported a successor policy")

    monkeypatch.setattr(continuation.runner, "frozen_module", fail)
    continuation.runner.verify_frozen_physician_eligibility(tmp_path, {"rows": [{}]})


def source(identity, title="old", run="old-run"):
    return {"posting_id": identity, "source_id": "jobkorea", "source_run_id": run,
            "source_record_id": "1", "source_facts_sha256": title,
            "source_facts": {"title": title}}


def test_partition_uses_current_facts_and_never_repeats_completed_postings():
    original = [source("paid"), source("skipped"), source("remaining")]
    current = [source("paid"), source("skipped"), source("remaining", "new", "new-run")]
    continuation.verify_partition(original, current, [current[2]], ["paid", "skipped"])
    with pytest.raises(RuntimeError, match="current snapshot"):
        continuation.verify_partition(original, current, [original[2]], ["paid", "skipped"])
    with pytest.raises(RuntimeError, match="partition"):
        continuation.verify_partition(original, current, [current[0], current[2]],
                                      ["paid", "skipped"])
    with pytest.raises(RuntimeError, match="partition"):
        continuation.verify_partition(original, current, [source("later-arrival")],
                                      ["paid", "skipped"])


def test_self_declared_current_facts_cannot_replace_the_independent_snapshot():
    old = [source("original")]
    current = [source("original", "refreshed", "new-run")]
    arrivals = [source("new-arrival")]
    live = [*current, *arrivals]
    continuation.verify_current_snapshot(old, current, arrivals, live)
    with pytest.raises(RuntimeError, match="independent graph"):
        continuation.verify_current_snapshot(old, [source("original", "self-asserted")],
                                             arrivals, live)
    with pytest.raises(RuntimeError, match="independent graph"):
        continuation.verify_current_snapshot(old, current, [source("different-arrival")], live)


def terminal_fixture():
    return {"task": {"state": "STOPPED", "unknown_requests": 0}, "attempts": [
        {"posting_identity": "paid", "state": "VALIDATED", "reserved_at": "time",
         "cost_usd": "0.01", "is_byok": True},
        {"posting_identity": "rejected", "state": "REJECTED", "reserved_at": "time",
         "cost_usd": "0.01", "is_byok": True},
        {"posting_identity": "skipped", "state": "SKIPPED", "reserved_at": None,
         "cost_usd": None, "is_byok": None}]}


def test_terminal_gate_excludes_validated_rejected_and_skipped_without_retry():
    continuation.validate_terminal(terminal_fixture(), ["paid", "rejected", "skipped"])


@pytest.mark.parametrize("change", ["active", "planned", "unknown", "non-byok", "error",
                                   "extra", "missing"])
def test_terminal_gate_rejects_unsafe_or_incomplete_predecessor(change):
    value = terminal_fixture()
    if change == "active":
        value["task"]["state"] = "ACTIVE"
    elif change == "unknown":
        value["attempts"][0]["cost_usd"] = None
    elif change == "non-byok":
        value["attempts"][0]["is_byok"] = False
    elif change == "extra":
        value["attempts"].append(copy.deepcopy(value["attempts"][0]))
    elif change == "missing":
        value["attempts"].pop()
    else:
        value["attempts"][0]["state"] = change.upper()
    with pytest.raises(RuntimeError):
        continuation.validate_terminal(value, ["paid", "rejected", "skipped"])


@pytest.mark.parametrize("change", ["prompt", "routing", "code", "same-task", "release"])
def test_continuation_cannot_change_contract_or_reuse_predecessor_task(change):
    settings = {"prompt_hash": "v4", "provider_only": ["openai"], "max_output_tokens": 1024}
    code = {"code/prompt.py": {"sha256": "frozen", "byte_length": 10}}
    proof = {"task_predecessor": "old", "continuation_task_id": "new", "original_contract": {
        "settings": copy.deepcopy(settings), "code_artifacts": copy.deepcopy(code),
        "release_id": "release", "database_id": "database"}}
    continuation.verify_contract(proof, dict(settings, continuation_proof_sha256="pin",
                                            predecessor_task_id="old"),
                                 code, "new", "release", "database")
    task, release = "new", "release"
    if change == "prompt":
        settings["prompt_hash"] = "changed"
    elif change == "routing":
        settings["provider_only"] = ["another-provider"]
    elif change == "code":
        code["code/prompt.py"]["sha256"] = "changed"
    elif change == "same-task":
        task = "old"
    else:
        release = "new-release"
    with pytest.raises(RuntimeError, match="retained inference contract"):
        continuation.verify_contract(proof, settings, code, task, release, "database")


def test_qualified_semantic_successor_preserves_routing_schema_and_database(tmp_path):
    original = {"settings": {"prompt_hash": "old", "model": "lighter",
                             "schema_sha256": "fixed", "provider_only": ["openai"]},
                "code_artifacts": {}, "release_id": "release", "database_id": "database"}
    successor = copy.deepcopy(original)
    successor["settings"]["prompt_hash"] = "qualified"
    path = tmp_path / "qualification.json"

    def qualify():
        path.write_text(json.dumps({"status": "QUALIFIED_CONTINUATION_CONTRACT",
                                    "authorized_contract": successor}))
        return {"path": str(path), **continuation.runner.file_identity(path)}

    proof = {"task_predecessor": "old", "continuation_task_id": "new",
             "original_contract": original, "authorized_contract": successor,
             "contract_qualification": qualify()}
    continuation.verify_contract(proof, successor["settings"], {}, "new", "release", "database")
    with pytest.raises(RuntimeError, match="retained inference"):
        continuation.verify_contract(proof, successor["settings"], {},
                                     "arbitrary-new-task", "release", "database")
    successor["settings"]["provider_only"] = ["other"]
    proof["contract_qualification"] = qualify()
    with pytest.raises(RuntimeError, match="model/routing"):
        continuation.verify_contract(proof, successor["settings"], {},
                                     "new", "release", "database")
    successor["database_id"] = "other-database"
    proof["contract_qualification"] = qualify()
    with pytest.raises(RuntimeError, match="catalogue/database"):
        continuation.verify_contract(proof, successor["settings"], {},
                                     "new", "release", "other-database")
