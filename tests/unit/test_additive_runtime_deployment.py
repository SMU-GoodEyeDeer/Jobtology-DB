"""No-service tests for additive rollout preservation, ownership and failure guards."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "deploy_additive_runtime", ROOT / "hop/operations/deploy_additive_runtime.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def state():
    return {
        "schema": {
            "tables": {"ingestion.record": "rowschema"},
            "views": {"ingestion.ready_record": "view"},
            "triggers": {"ingestion.record:guard": "trigger"},
            "functions": {"ingestion.graph_source_manifest(text,boolean)": "oldbody"},
            "function_acl": {"ingestion.graph_source_manifest(text,boolean)": [10, None]},
            "v3_prompt": {"count": 0, "digest": "empty"},
        },
        "rows": {
            "ingestion.record": {"count": 8434, "digest": "immutable"},
            "enrichment.prompt": {"count": 4, "digest": "legacy"},
        },
        "queries": {
            "pins": {"job": "exact", "ncs": "ncs"},
            "source_entities": {"rows": 8434, "sha256": "typed"},
        },
        "catalog_context": {"release_id": "sealed"},
    }


def candidate():
    value = state()
    value["schema"]["functions"]["ingestion.graph_source_manifest(text,boolean)"] = "newbody"
    value["schema"]["functions"]["ingestion.new_helper(text)"] = "newhelper"
    value["schema"]["v3_prompt"] = {"count": 1, "digest": "exact-new-prompt"}
    value["rows"][ops.NEW_TABLE] = {"count": 0, "digest": "empty"}
    return value


def test_only_approved_body_and_empty_additions_allowed():
    ops.require_preserved(state(), candidate(), {"ingestion.graph_source_manifest"})


@pytest.mark.parametrize(
    "mutation",
    [
        "rows",
        "schema",
        "views",
        "trigger",
        "acl",
        "catalog",
        "query",
        "nonempty",
        "unexpected_table",
    ],
)
def test_unintended_change_fails(mutation):
    value = candidate()
    if mutation == "rows":
        value["rows"]["ingestion.record"]["digest"] = "changed"
    elif mutation == "schema":
        value["schema"]["tables"]["ingestion.record"] = "changed"
    elif mutation == "views":
        value["schema"]["views"]["ingestion.ready_record"] = "changed"
    elif mutation == "trigger":
        value["schema"]["triggers"]["ingestion.record:guard"] = "changed"
    elif mutation == "acl":
        value["schema"]["function_acl"]["ingestion.graph_source_manifest(text,boolean)"] = [
            10,
            ["public=X"],
        ]
    elif mutation == "catalog":
        value["catalog_context"]["release_id"] = "other"
    elif mutation == "query":
        value["queries"]["source_entities"]["sha256"] = "different output"
    elif mutation == "nonempty":
        value["rows"][ops.NEW_TABLE]["count"] = 1
    else:
        value["rows"]["enrichment.other"] = {"count": 0, "digest": "empty"}
    with pytest.raises(RuntimeError):
        ops.require_preserved(state(), value, {"ingestion.graph_source_manifest"})


def test_existing_v3_prompt_is_preserved():
    before = candidate()
    after = copy.deepcopy(before)
    after["schema"]["v3_prompt"]["digest"] = "changed"
    with pytest.raises(RuntimeError, match="prompt"):
        ops.require_preserved(before, after, {"ingestion.graph_source_manifest"})


def test_bundle_requires_every_coherent_artifact():
    assert ops.selected(list(ops.ALLOWLIST)) == ops.ALLOWLIST
    with pytest.raises(ValueError, match="complete"):
        ops.selected(list(ops.MIGRATIONS))


def test_outer_transaction_unwrapped_without_altering_function_body():
    body = (
        "-- Generated\nBEGIN;\nCREATE FUNCTION x() RETURNS void AS $$ "
        "BEGIN RETURN; END $$ LANGUAGE plpgsql;\nCOMMIT;\n"
    )
    assert "BEGIN RETURN; END" in ops.unwrap_sql(body)
    with pytest.raises(ValueError):
        ops.unwrap_sql("SELECT 1;")


def test_proofs_bind_full_bundle_and_cleanup_boolean(tmp_path):
    artifacts = {name: {"after": str(index)} for index, name in enumerate(ops.ALLOWLIST)}
    proof = {
        "status": "PASSED",
        "cleanup_confirmed": True,
        "artifact_sha256": {name: entry["after"] for name, entry in artifacts.items()},
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof))
    assert ops.bind_proofs([path], artifacts)[0]["sha256"] == ops.digest(path)
    proof["artifact_hashes"] = proof.pop("artifact_sha256")
    path.write_text(json.dumps(proof))
    assert ops.bind_proofs([path], artifacts)[0]["cleanup_scope"] == "DISPOSABLE_RESOURCES"
    proof["artifact_sha256"] = proof.pop("artifact_hashes")
    proof["cleanup_confirmed"] = "true"
    path.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match="cleanup"):
        ops.bind_proofs([path], artifacts)
    proof["cleanup_confirmed"] = True
    proof["artifact_sha256"].pop("graph/check_snapshot.hpl")
    path.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match="critical"):
        ops.bind_proofs([path], artifacts)


def test_fence_ownership_never_removed_by_foreign_token(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "STATE", tmp_path)
    path = tmp_path / "receipt.json"
    receipt = {"token": "owned"}
    ops.own_fence(receipt, path)
    with pytest.raises(RuntimeError, match="another"):
        ops.own_fence({"token": "foreign"}, path)
    assert json.loads((tmp_path / ops.performance.FENCE_NAME).read_text())["token"] == "owned"


def test_partial_runtime_failure_retains_sql_evidence_and_owned_fence(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "STATE", tmp_path)
    monkeypatch.setattr(ops.performance, "STATE", tmp_path)
    runtime = {"pg": "isolated-test-pg", "hop": "isolated-test-hop"}
    planned = tmp_path / "planned"
    planned.mkdir()
    public = {name: {"before": None, "after": "candidate"} for name in ops.ALLOWLIST}
    for name in ops.ALLOWLIST:
        dest = planned / "candidate" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("candidate")
    manifest = {
        "kind": ops.KIND,
        "version": 1,
        "containers": runtime,
        "artifacts": public,
        "isolated_proofs": [],
        "before": state(),
        "original_functions": [],
    }
    path = planned / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(ops, "digest", lambda path: "candidate")
    monkeypatch.setattr(ops, "bind_proofs", lambda *args: [])
    monkeypatch.setattr(ops.performance, "idle", lambda runtime: None)
    snapshots = iter([state(), candidate()])
    monkeypatch.setattr(ops, "snapshot_state", lambda *args: next(snapshots))
    monkeypatch.setattr(ops, "require_unused_v3", lambda *args: None)
    monkeypatch.setattr(ops.deployment, "remote_bytes", lambda *args: None)
    monkeypatch.setattr(ops, "backup_database", lambda *args: {"sha256": "backup"})
    monkeypatch.setattr(ops, "unwrap_sql", lambda text: "SELECT 1;")
    monkeypatch.setattr(
        ops, "function_names", lambda directory: {"ingestion.graph_source_manifest"}
    )
    monkeypatch.setattr(ops, "sql", lambda *args: json.dumps(candidate()["schema"]))

    def fail(*args):
        raise RuntimeError("injected atomic rename failure")

    monkeypatch.setattr(ops, "write_runtime", fail)
    with pytest.raises(RuntimeError, match="retain fence"):
        ops.apply(path, runtime)
    fence = json.loads((tmp_path / ops.performance.FENCE_NAME).read_text())
    receipt = json.loads(Path(fence["receipt"]).read_text())
    assert receipt["status"] == "FAILED_FENCED"
    assert receipt["candidate_schema"] == candidate()["schema"]
    assert receipt["attempted"] == [ops.ALLOWLIST[0]]
    assert receipt["installed"] == []
    assert receipt["scheduler_fence_removed"] is False


def test_historical_inference_pin_is_measured_even_when_latest_pin_is_empty(tmp_path, monkeypatch):
    seen = []

    def fake_sql(pg, query, directory, label):
        seen.append(query)
        if label.endswith("-pins"):
            return json.dumps({"job": "jobs", "ncs": "NEW_CURRENT_NCS"})
        if label.endswith("-frozen-pairs"):
            return json.dumps(
                [
                    {
                        "job": "jobs",
                        "ncs": "OLDER_FROZEN_NCS",
                        "bindings": 7,
                        "results": 7,
                        "candidates": 7,
                    }
                ]
            )
        return json.dumps({"rows": 7 if "OLDER_FROZEN_NCS" in query else 0, "sha256": "hash"})

    monkeypatch.setattr(ops, "sql", fake_sql)
    result = ops.query_state("fixture", tmp_path, "before")
    assert result["latest_source_pins"]["ncs"] == "NEW_CURRENT_NCS"
    assert result["protected_legacy_graph_rows"] == 7
    assert any("metadata_occupation_graph_rows('jobs','OLDER_FROZEN_NCS',true)" in q for q in seen)
    assert not any("metadata_occupation_graph_rows('jobs','NEW_CURRENT_NCS'" in q for q in seen)


def test_empty_historical_graph_cannot_masquerade_as_link_preservation(tmp_path, monkeypatch):
    def fake_sql(pg, query, directory, label):
        if label.endswith("-pins"):
            return json.dumps({"job": "jobs", "ncs": "new"})
        if label.endswith("-frozen-pairs"):
            return json.dumps(
                [{"job": "jobs", "ncs": "old", "bindings": 7, "results": 7, "candidates": 7}]
            )
        return json.dumps({"rows": 0, "sha256": "empty"})

    monkeypatch.setattr(ops, "sql", fake_sql)
    with pytest.raises(RuntimeError, match="unexpectedly empty"):
        ops.query_state("fixture", tmp_path, "before")


def test_rollback_retry_accepts_exact_restored_function_phase(tmp_path, monkeypatch):
    runtime = {"pg": "private-pg", "hop": "private-hop"}
    relative = ops.ALLOWLIST[0]
    old, new = b"old", b"new"
    backup = tmp_path / "before" / relative
    backup.parent.mkdir(parents=True)
    backup.write_bytes(old)
    receipt = {
        "before": state(),
        "candidate_schema": candidate()["schema"],
        "manifest": str(tmp_path / "manifest.json"),
        "token": "owned",
        "original_functions": [
            {
                "signature": "ingestion.graph_source_manifest(text,boolean)",
                "definition": "EXACT OLD FUNCTION",
            }
        ],
        "artifacts": {
            relative: {"before": ops.common.digest(old), "after": ops.common.digest(new)}
        },
        "sql_attempted": True,
    }
    current = candidate()
    remote = {relative: new}
    monkeypatch.setattr(ops, "load", lambda *args: receipt)
    monkeypatch.setattr(ops.performance, "idle", lambda *args: None)
    monkeypatch.setattr(ops, "require_unused_v3", lambda *args: None)
    monkeypatch.setattr(ops, "snapshot_state", lambda *args: copy.deepcopy(current))
    monkeypatch.setattr(ops, "function_names", lambda *args: {"ingestion.graph_source_manifest"})
    monkeypatch.setattr(ops, "own_fence", lambda *args: None)
    monkeypatch.setattr(ops.performance, "release_fence", lambda *args: None)
    monkeypatch.setattr(ops.deployment, "remote_bytes", lambda hop, key: remote[key])

    def restore_functions(*args):
        current["schema"] = ops.restored_schema(receipt)

    monkeypatch.setattr(ops, "sql", restore_functions)
    monkeypatch.setattr(
        ops,
        "write_runtime",
        lambda *args: (_ for _ in ()).throw(RuntimeError("injected runtime restore failure")),
    )
    path = tmp_path / "receipt.json"
    with pytest.raises(RuntimeError, match="injected"):
        ops.rollback(path, runtime)
    assert receipt["status"] == "ROLLBACK_FAILED_FENCED"
    monkeypatch.setattr(
        ops, "write_runtime", lambda hop, key, value, *args: remote.update({key: value})
    )
    ops.rollback(path, runtime)
    assert receipt["status"] == "ROLLED_BACK_BEHAVIOR"
    assert remote[relative] == old


def test_pre_sql_abort_needs_no_saved_artifact_files(tmp_path, monkeypatch):
    runtime = {"pg": "private-pg", "hop": "private-hop"}
    receipt = {
        "sql_attempted": False,
        "attempted": [],
        "before": state(),
        "preapply_observed": candidate(),
        "preapply_runtime": {"x": "old"},
        "artifacts": {"x": {"before": "reviewed"}},
    }
    monkeypatch.setattr(ops, "load", lambda *args: receipt)
    monkeypatch.setattr(ops.performance, "idle", lambda *args: None)
    monkeypatch.setattr(ops, "own_fence", lambda *args: None)
    monkeypatch.setattr(ops.performance, "release_fence", lambda *args: None)
    monkeypatch.setattr(ops, "snapshot_state", lambda *args: candidate())
    monkeypatch.setattr(ops.deployment, "remote_bytes", lambda *args: b"old")
    monkeypatch.setattr(ops.common, "digest", lambda value: value.decode())
    ops.rollback(tmp_path / "receipt.json", runtime)
    assert receipt["status"] == "ABORTED_UNCHANGED"
    assert receipt["scheduler_fence_removed"] is True
    monkeypatch.setattr(ops, "snapshot_state", lambda *args: state())
    with pytest.raises(RuntimeError, match="drift"):
        ops.abort_unchanged(tmp_path / "receipt.json", runtime)
