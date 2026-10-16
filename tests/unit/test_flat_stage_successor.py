"""Restricted successor bytes, typed partial proof and interrupted deployment."""

from __future__ import annotations

import importlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def frame(*values: str) -> str:
    return "".join(str(len(v)) + ":" + v for v in values)


def props(**values: tuple[str, str]) -> str:
    return "".join(frame(k, *v) for k, v in sorted(values.items()))


def archive(path: Path, rows: list[tuple[str, list[str]]]) -> Path:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,PRIMARY KEY(kind,eid))")
    for kind, row in rows:
        db.execute("INSERT INTO snapshot VALUES(?,?,?)", (kind, row[0], frame(*row)))
    db.commit()
    db.close()
    return path


@pytest.fixture
def modules(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    folder = Path(__file__).resolve().parents[2] / "hop/operations"
    monkeypatch.syspath_prepend(str(folder))  # type: ignore[reportUnknownMemberType]
    return (
        importlib.import_module("migrate_flat_ontology_graph"),
        importlib.import_module("amend_flat_ontology_stage"),
    )


def private(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def constant(value: Any) -> Callable[..., Any]:
    def call(*args: Any, **kwargs: Any) -> Any:
        return value

    return call


def candidate_pair(amend: Any) -> tuple[bytes, bytes]:
    old = (
        "<pipeline><transform><type>Neo4jCypherOutput</type><batch_size>500</batch_size>"
        "<cypher>" + amend.OLD_MATCH + " WHERE n.release_id=row.release_id "
        "RETURN count(n)=size($rows) AS verified</cypher></transform></pipeline>"
    ).encode()
    return old, old.replace(amend.OLD_MATCH.encode(), amend.NEW_MATCH.encode())


def test_only_exact_seek_rewrite_is_allowed(modules: tuple[Any, Any]) -> None:
    _, amend = modules
    old, new = candidate_pair(amend)
    amend.validate_candidate(old, new)
    bad = (
        new.replace(b"batch_size>500", b"batch_size>1000"),
        new.replace(b"n.release_id=row.release_id", b"true"),
        new.replace(b"RETURN count", b"SET n.bad=true RETURN count"),
        new.replace(b"USING INDEX SEEK", b"USING INDEX"),
    )
    for data in bad:
        with pytest.raises(RuntimeError):
            amend.validate_candidate(old, data)


def test_new_flat_array_prefix_is_exact_and_business_proof_stays_strict(
    modules: tuple[Any, Any],
) -> None:
    ops, _ = modules
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE flat_property(owner_type TEXT,owner_id TEXT,payload TEXT)")
    fields = [
        {
            "key": "nums",
            "ordinal": i,
            "array_size": 3,
            "is_array": True,
            "value_type": "integer",
            "text_value": str(i + 1),
        }
        for i in range(3)
    ]
    db.execute(
        "INSERT INTO flat_property VALUES('EDGE','new',?)", (json.dumps({"fields": fields}),)
    )
    prefix = props(
        id=("STRING NOT NULL", "new"), nums=("LIST<INTEGER NOT NULL> NOT NULL", frame("1", "2"))
    )
    ops.require_native_properties(
        db, "EDGE", "new", prefix, {"id": "new"}, "flat_property", partial=True, array_prefix=True
    )
    with pytest.raises(RuntimeError, match="cardinality"):
        ops.require_native_properties(
            db, "EDGE", "new", prefix, {"id": "new"}, "flat_property", partial=True
        )
    for kind, values in (
        ("LIST<INTEGER NOT NULL> NOT NULL", frame("1", "9")),
        ("LIST<FLOAT NOT NULL> NOT NULL", frame("1", "2")),
        ("LIST<INTEGER NOT NULL> NOT NULL", frame("1", "2", "3", "4")),
    ):
        with pytest.raises(RuntimeError):
            ops.require_native_properties(
                db,
                "EDGE",
                "new",
                props(id=("STRING NOT NULL", "new"), nums=(kind, values)),
                {"id": "new"},
                "flat_property",
                partial=True,
                array_prefix=True,
            )
    with pytest.raises(ValueError, match="restricted"):
        ops.require_native_properties(
            db,
            "NODE",
            "new",
            prefix,
            {"id": "new"},
            "flat_property",
            partial=True,
            array_prefix=True,
        )


def partial_fixture(ops: Any, folder: Path) -> tuple[Path, Path, dict[str, Any], list[Any]]:
    baseline_rows = [
        (
            "NODE",
            [
                "c",
                frame("ontologyEntity", "ontologyObject"),
                props(id=("STRING NOT NULL", "entity/c"), content_hash=("STRING NOT NULL", "old")),
            ],
        ),
        (
            "NODE",
            [
                "r",
                frame("entityRevision", "occupationRevision", "ontologyObject"),
                props(id=("STRING NOT NULL", "revision/r")),
            ],
        ),
        (
            "NODE",
            [
                "business",
                frame("entity", "jobPosting"),
                props(
                    id=("STRING NOT NULL", "posting"),
                    dates=("LIST<DATE NOT NULL> NOT NULL", frame("2026-10-01", "2026-10-02")),
                ),
            ],
        ),
        ("REL", ["legacy", "r", "c", "DERIVED_FROM", props(id=("STRING NOT NULL", "old-edge"))]),
    ]
    current_rows = list(baseline_rows)
    current_rows[0] = (
        "NODE",
        [
            "c",
            baseline_rows[0][1][1],
            props(
                id=("STRING NOT NULL", "entity/c"),
                content_hash=("STRING NOT NULL", "old"),
                flat_content_hash=("STRING NOT NULL", "flat"),
                flat_owned_keys=("LIST<NOTHING> NOT NULL", ""),
            ),
        ],
    )
    current_rows.append(
        (
            "REL",
            [
                "new-eid",
                "c",
                "c",
                "DERIVED_FROM",
                props(
                    id=("STRING NOT NULL", "new-edge"),
                    content_hash=("STRING NOT NULL", "edge-hash"),
                    release_id=("STRING NOT NULL", "release"),
                    nums=("LIST<INTEGER NOT NULL> NOT NULL", frame("1", "2")),
                ),
            ],
        )
    )
    baseline = archive(folder / "before.sqlite", baseline_rows)
    current = archive(folder / "partial.sqlite", current_rows)
    proof = folder / "proof.sqlite"
    db = sqlite3.connect(proof)
    db.executescript(
        "CREATE TABLE flat_graph_node(id TEXT,payload TEXT);"
        "CREATE TABLE flat_graph_edge(id TEXT,payload TEXT);"
        "CREATE TABLE flat_property(owner_type TEXT,owner_id TEXT,payload TEXT)"
    )
    db.execute(
        "INSERT INTO flat_graph_node VALUES(?,?)",
        (
            "entity/c",
            json.dumps(
                {
                    "labels": ["ontologyEntity"],
                    "owned_properties": {},
                    "content_hash": "old",
                    "flat_content_hash": "flat",
                }
            ),
        ),
    )
    db.execute(
        "INSERT INTO flat_graph_edge VALUES(?,?)",
        (
            "new-edge",
            json.dumps(
                {
                    "origin_edge_id": "old-edge",
                    "predicate": "DERIVED_FROM",
                    "subject_id": "entity/c",
                    "object_id": "entity/c",
                    "content_hash": "edge-hash",
                }
            ),
        ),
    )
    fields = [
        {
            "key": "nums",
            "ordinal": i,
            "array_size": 3,
            "is_array": True,
            "value_type": "integer",
            "text_value": str(i + 1),
        }
        for i in range(3)
    ]
    db.execute(
        "INSERT INTO flat_property VALUES('EDGE','new-edge',?)", (json.dumps({"fields": fields}),)
    )
    db.commit()
    db.close()
    proof.chmod(0o600)
    return (
        baseline,
        current,
        {"path": str(proof), "sha256": ops.checksum(proof), "release_id": "release"},
        current_rows,
    )


def test_partial_stage_requires_all_original_legacy_and_exact_unaffected_arrays(
    modules: tuple[Any, Any], tmp_path: Path
) -> None:
    ops, _ = modules
    before, after, flat, rows = partial_fixture(ops, tmp_path)
    result = ops.require_flat_preserved(
        before, after, flat, removed=False, partial_new_edge_properties=True
    )
    assert result["revision_nodes"] == 1 and result["legacy_edges"] == 1
    for index, changed in enumerate((rows[:1] + rows[2:], rows[:3] + rows[4:])):
        path = archive(tmp_path / ("missing-" + str(index) + ".sqlite"), changed)
        with pytest.raises(RuntimeError):
            ops.require_flat_preserved(
                before, path, flat, removed=False, partial_new_edge_properties=True
            )
    changed = list(rows)
    changed[2] = (
        "NODE",
        [
            "business",
            rows[2][1][1],
            props(
                id=("STRING NOT NULL", "posting"),
                dates=("LIST<DATE NOT NULL> NOT NULL", frame("2026-10-01")),
            ),
        ],
    )
    with pytest.raises(RuntimeError, match="Unaffected"):
        ops.require_flat_preserved(
            before,
            archive(tmp_path / "bad-business.sqlite", changed),
            flat,
            removed=False,
            partial_new_edge_properties=True,
        )
    changed = list(rows)
    changed[-1] = ("REL", ["new-eid", "c", "r", *rows[-1][1][3:]])
    with pytest.raises(RuntimeError, match="endpoints"):
        ops.require_flat_preserved(
            before,
            archive(tmp_path / "bad-endpoint.sqlite", changed),
            flat,
            removed=False,
            partial_new_edge_properties=True,
        )


def sealed_fixture(amend: Any, folder: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    old, new = candidate_pair(amend)
    files: dict[str, Any] = {}
    artifacts = {name: {"after": amend.sha(old)} for name in amend.FILES}
    artifacts["ontology/sql/028_flat_graph_projection.sql"] = {"after": "sql-unchanged"}
    for index, name in enumerate(amend.FILES):
        original = folder / (str(index) + "-original.hpl")
        original.write_bytes(old)
        original.chmod(0o600)
        candidate = folder / (str(index) + "-new.hpl")
        candidate.write_bytes(new)
        candidate.chmod(0o600)
        files[name] = {
            "before": amend.sha(old),
            "after": amend.sha(new),
            "candidate": str(candidate),
            "predecessor": str(original),
        }
    manifest = {
        "artifacts": artifacts,
        "graph": {"sha256": "graph"},
        "catalogue": {"approval": {"database_id": "database"}},
        "release_id": "release",
        "old_tables": {"ingestion.record": {"digest": "old"}},
        "backing": {"revision_nodes": 1, "revision_edges": 1},
    }
    original = private(folder / "original.json", manifest)
    native = private(
        folder / "native.json",
        {"status": "PASSED", "candidate_hpl_sha256": {k: v["after"] for k, v in files.items()}},
    )
    amendment: dict[str, Any] = {
        "kind": "FLAT_STAGE_SIX_FILE_SUCCESSOR",
        "original_manifest": str(original.resolve()),
        "original_manifest_sha256": amend.sha(original.read_bytes()),
        "original_graph_sha256": "graph",
        "database_backup_sha256": "backup",
        "migration_token": "token",
        "files": files,
        "flat_inventory": {"sha256": "flat"},
        "original_artifacts": {k: v["after"] for k, v in artifacts.items()},
        "native_proof": str(native),
        "native_proof_sha256": amend.sha(native.read_bytes()),
        "old_load": {"load_id": "old-token", "database_id": "database", "state": "RUNNING"},
        "partial_proof": {"schema": {"functions": {}, "triggers": {}}},
    }
    path = private(folder / "amendment.json", amendment)
    receipt = {
        "kind": "FLAT_ONTOLOGY",
        "manifest": str(original),
        "token": "token",
        "runtime": {"pg": "pg", "hop": "hop"},
        "database_backup": {"sha256": "backup"},
        "flat_inventory": {"sha256": "flat"},
        "successor_amendment_complete": True,
        "successor_amendment_intent": {
            "manifest": str(path),
            "sha256": amend.sha(path.read_bytes()),
        },
        "status": "FAILED",
    }
    receipt_path = private(folder / "receipt.json", receipt)
    return manifest, receipt, receipt_path


def test_successor_hashes_never_accept_incomplete_or_tampered_original(
    modules: tuple[Any, Any], tmp_path: Path
) -> None:
    _, amend = modules
    manifest, receipt, _ = sealed_fixture(amend, tmp_path)
    hashes = amend.successor_hashes(manifest, receipt)
    assert hashes["ontology/sql/028_flat_graph_projection.sql"] == "sql-unchanged"
    receipt["successor_amendment_complete"] = False
    with pytest.raises(RuntimeError, match="Incomplete"):
        amend.successor_hashes(manifest, receipt)
    receipt["successor_amendment_complete"] = True
    original = Path(receipt["manifest"])
    original.write_bytes(original.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="binding"):
        amend.successor_hashes(manifest, receipt)


def test_partial_deploy_then_fail_token_crash_retries_without_rollback(
    modules: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ops, amend = modules
    manifest, receipt, path = sealed_fixture(amend, tmp_path)
    receipt["successor_amendment_complete"] = False
    private(path, receipt)
    private(tmp_path / ops.FENCE_NAME, {"token": "token"})
    load = {"load_id": "old-token", "database_id": "database", "state": "RUNNING"}
    phases: list[str] = []
    installed: list[str] = []
    failure = {"file": True, "token": True}
    sql_calls: list[str] = []

    def event(directory: Path, data: dict[str, Any], phase: str, **values: Any) -> None:
        phases.append(phase)
        data.update(values)
        private(directory / "receipt.json", data)

    def install(*args: Any) -> None:
        installed.append(args[2])
        if len(installed) == 2 and failure["file"]:
            failure["file"] = False
            raise RuntimeError("simulated file switch failure")

    def sql(*args: Any) -> str:
        sql_calls.append(args[1])
        load["state"] = "FAILED"
        if failure["token"]:
            failure["token"] = False
            raise RuntimeError("simulated crash after fail-token commit")
        return ""

    fake = SimpleNamespace(
        common=SimpleNamespace(STATE=tmp_path),
        FENCE_NAME=ops.FENCE_NAME,
        flat_load=constant(load),
        graph=SimpleNamespace(event=event),
        deployment=SimpleNamespace(sql=sql),
        require_old_tables=constant(None),
        all_old_tables=constant(manifest["old_tables"]),
        dates=SimpleNamespace(
            quote=ops.dates.quote,
            schema_preservation=constant({"functions": {}, "triggers": {}}),
        ),
    )
    monkeypatch.setattr(amend, "prove_partial", constant({"complete_original_scope": True}))
    monkeypatch.setattr(amend, "quiescent", constant(None))
    monkeypatch.setattr(amend, "reader_closed", constant(None))
    monkeypatch.setattr(amend, "install_one", install)
    amendment = amend.private_json(Path(receipt["successor_amendment_intent"]["manifest"]))
    monkeypatch.setattr(
        amend,
        "artifact_state",
        constant({k: v["after"] for k, v in amendment["files"].items()}),
    )
    original_bytes = Path(receipt["manifest"]).read_bytes()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Successor stopped"):
            amend.amend(fake, receipt["runtime"], path, None, None)
        failed = amend.private_json(path)
        assert not failed["successor_amendment_complete"]
        with pytest.raises(RuntimeError, match="Incomplete"):
            amend.successor_hashes(manifest, failed)
    assert len(sql_calls) == 1 and load["state"] == "FAILED"
    amend.amend(fake, receipt["runtime"], path, None, None)
    done = amend.private_json(path)
    assert done["successor_amendment_complete"] is True
    assert done["status"] == "FAILED_RETRY_READY_FENCED"
    assert (tmp_path / ops.FENCE_NAME).exists()
    assert phases.index("SUCCESSOR_FILE_SWITCH_INTENT") < phases.index(
        "SUCCESSOR_OLD_TOKEN_FAILURE_INTENT"
    )
    assert Path(receipt["manifest"]).read_bytes() == original_bytes


def test_quiescence_does_not_enter_catalogue_reader_or_zero_writer_gate(
    modules: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ops, amend = modules
    calls: list[str] = []
    state = {
        "refresh": 0,
        "loading": 0,
        "old_ontology": 0,
        "maintenance": False,
        "llm_batches": 0,
        "llm_reserved": 0,
        "writers": 0,
    }

    def fenced_reader(*args: Any) -> None:
        raise RuntimeError("FLAT_GRAPH_PROJECTION_NOT_READY")

    def sql(*args: Any) -> str:
        query = args[1]
        calls.append(query)
        assert "catalog_context_v1" not in query
        assert "writer_id<>'owned-token'" in query
        assert "ingestion.maintenance_active()" in query
        return json.dumps(state)

    monkeypatch.setattr(ops.common, "db_state", fenced_reader)
    monkeypatch.setattr(ops.dates, "require_idle", fenced_reader)
    monkeypatch.setattr(ops.common, "idle_cli", constant(None))
    monkeypatch.setattr(ops.deployment, "sql", sql)
    monkeypatch.setattr(ops.graph, "native_rows", constant(["1"]))
    amend.quiescent(ops, {"pg": "pg", "hop": "hop"}, {"load_id": "owned-token"}, tmp_path)
    assert len(calls) == 1
    for key in state:
        state[key] = 1
        with pytest.raises(RuntimeError, match="Unaccounted"):
            amend.quiescent(ops, {"pg": "pg", "hop": "hop"}, {"load_id": "owned-token"}, tmp_path)
        state[key] = 0
    monkeypatch.setattr(ops.graph, "native_rows", constant(["2"]))
    with pytest.raises(RuntimeError, match="Neo4j transaction"):
        amend.quiescent(ops, {"pg": "pg", "hop": "hop"}, {"load_id": "owned-token"}, tmp_path)


def test_complete_successor_requires_repo_and_deployed_hashes_together(
    modules: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ops, amend = modules
    manifest, receipt, _ = sealed_fixture(amend, tmp_path)
    successor = amend.successor_hashes(manifest, receipt)
    entries = {name: {"before": value, "after": value} for name, value in successor.items()}
    monkeypatch.setattr(ops.deployment, "snapshot", constant((entries, {})))
    ops.require_artifact_binding({}, manifest, receipt, deployed=True)
    name = amend.FILES[0]
    entries[name]["after"] = manifest["artifacts"][name]["after"]
    with pytest.raises(RuntimeError, match="Deployed public"):
        ops.require_artifact_binding({}, manifest, receipt, deployed=True)
    entries[name]["after"] = successor[name]
    entries["ontology/sql/028_flat_graph_projection.sql"]["before"] = "unexpected"
    with pytest.raises(RuntimeError, match="Deployed public"):
        ops.require_artifact_binding({}, manifest, receipt, deployed=True)
    with pytest.raises(RuntimeError, match="Unrelated"):
        amend.artifact_state(ops, {}, amend.sealed_amendment(manifest, receipt))


def test_native_proof_and_owned_checkpoint_cannot_drift_before_file_switch(
    modules: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ops, amend = modules
    manifest, receipt, path = sealed_fixture(amend, tmp_path)
    amendment = amend.sealed_amendment(manifest, receipt)
    native = Path(amendment["native_proof"])
    raw = native.read_bytes()
    private(native, {"status": "FAILED"})
    with pytest.raises(RuntimeError, match="native successor"):
        amend.successor_hashes(manifest, receipt)
    native.write_bytes(raw)
    receipt["successor_amendment_complete"] = False
    private(path, receipt)
    private(tmp_path / ops.FENCE_NAME, {"token": "token"})
    fake = SimpleNamespace(
        common=SimpleNamespace(STATE=tmp_path),
        FENCE_NAME=ops.FENCE_NAME,
        flat_load=constant(
            {
                "load_id": "unexpected-token",
                "state": "RUNNING",
                "database_id": "database",
            }
        ),
    )
    switched: list[str] = []

    def install(*args: Any) -> None:
        switched.append("unsafe")

    monkeypatch.setattr(amend, "install_one", install)
    with pytest.raises(RuntimeError, match="token changed"):
        amend.amend(fake, receipt["runtime"], path, None, None)
    assert switched == []


def test_reader_fence_rejects_unexpected_failure_and_success(
    modules: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ops, amend = modules
    outcome = SimpleNamespace(
        returncode=3, stderr=b"ERROR:  P0001: FLAT_GRAPH_PROJECTION_NOT_READY\n"
    )

    def command(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return outcome

    monkeypatch.setattr(amend.subprocess, "run", command)
    amend.reader_closed(ops, "pg", "release")
    for result in (
        SimpleNamespace(returncode=0, stderr=b""),
        SimpleNamespace(returncode=3, stderr=b"ERROR:  57014: statement timeout\n"),
        SimpleNamespace(returncode=3, stderr=b"ERROR:  P0001: other refusal\n"),
    ):
        outcome = result
        with pytest.raises(RuntimeError, match="reader fence"):
            amend.reader_closed(ops, "pg", "release")


def test_fresh_stage_intent_durably_replaces_failed_predecessor_before_launch(
    modules: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ops, _ = modules
    manifest = {
        "release_id": "release",
        "catalogue": {
            "approval": {"database_id": "database"},
            "release": {"manifest_hash": "source"},
        },
    }
    old = {
        "load_id": "old-failed",
        "state": "FAILED",
        "manifest_hash": "projection",
    }
    receipt: dict[str, Any] = {"load": old, "token": "migration", "status": "FAILED"}
    monkeypatch.setattr(ops.deployment, "sql", constant("2026-10-12 05:58:00+00"))
    ops.starting_flat_stage("pg", tmp_path, receipt, manifest, "database", old)
    durable = json.loads((tmp_path / "receipt.json").read_bytes())
    assert durable["load"] is None
    assert durable["previous_failed_load"] == old
    assert durable["fresh_stage_intent"]["previous_failed_load_id"] == "old-failed"
    new = {
        "load_id": "new-owned",
        "state": "STAGED",
        "release_id": "release",
        "database_id": "database",
        "source_manifest_hash": "source",
        "manifest_hash": "projection",
        "started_at": "2026-10-12T05:58:01+00:00",
    }
    for state in ("RUNNING", "STAGED"):
        new["state"] = state
        ops.require_load_ownership(manifest, durable, new)
    for key, value in (
        ("release_id", "other"),
        ("database_id", "other"),
        ("source_manifest_hash", "other"),
        ("manifest_hash", "other"),
        ("started_at", "2026-10-12T05:57:59+00:00"),
        ("load_id", "old-failed"),
    ):
        unexpected = {**new, key: value}
        with pytest.raises(RuntimeError, match="durable fresh-stage"):
            ops.require_load_ownership(manifest, durable, unexpected)
    with pytest.raises(RuntimeError, match="durable fresh-stage"):
        ops.require_load_ownership(manifest, {"load": None}, new)
    with pytest.raises(RuntimeError, match="retained migration token"):
        ops.require_load_ownership(manifest, {"load": {"load_id": "different"}}, new)
    # The existing final/replay flow owns its separate full-flat preservation
    # gates; its normal reload creates a new FAILED/VERIFIED token by design.
    replay_receipt = {
        "load": {"load_id": "old-staged", "state": "STAGED"},
        "post_removal_graph_verified": True,
    }
    for state in ("FAILED", "VERIFIED"):
        ops.require_load_ownership(manifest, replay_receipt, {**new, "state": state})
    with pytest.raises(RuntimeError, match="retained migration token"):
        ops.require_load_ownership(manifest, replay_receipt, {**new, "state": "STAGED"})
