"""Focused refusal/type/recovery invariants for the guarded ontology operator."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def ops(monkeypatch: pytest.MonkeyPatch) -> Any:
    folder = Path(__file__).resolve().parents[2] / "hop/operations"
    monkeypatch.syspath_prepend(str(folder))  # type: ignore[reportUnknownMemberType]
    spec = importlib.util.spec_from_file_location(
        "flat_operations_test", folder / "migrate_flat_ontology_graph.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def frame(*values: str) -> str:
    return "".join(str(len(v)) + ":" + v for v in values)


def test_export_version_refusal_is_exact_and_latest_requires_success(
    ops: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def result(error: bytes, code: int = 3) -> None:
        def execute(*args: Any, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=code, stdout=b'{"rows":12,"digest":"preserved"}', stderr=error
            )

        monkeypatch.setattr(
            ops.subprocess,
            "run",
            execute,
        )

    result(b"ERROR:  P0001: INTERCHANGE_UNMAPPED_NODE_LABEL\nCONTEXT:  old contract\n")
    assert ops.export_fingerprint("fixture", "release", "export_jsonld_v1") == {
        "status": "CONTRACT_REFUSED",
        "sqlstate": "P0001",
        "reason": "INTERCHANGE_UNMAPPED_NODE_LABEL",
    }
    with pytest.raises(RuntimeError, match="Latest catalogue export must succeed"):
        ops.export_fingerprint("fixture", "release", "export_jsonld_v3")
    for error in (
        b"ERROR:  57014: canceling statement due to statement timeout\n",
        b"ERROR:  P0001: RELEASE_CORRUPT\n",
        b"ERROR:  XX000: INTERCHANGE_UNMAPPED_NODE_LABEL\n",
    ):
        result(error)
        with pytest.raises(RuntimeError, match="outside its known"):
            ops.export_fingerprint("fixture", "release", "export_jsonld_v1")
    result(b"", 0)
    assert ops.export_fingerprint("fixture", "release", "export_jsonld_v3") == {
        "status": "SUCCESS",
        "rows": 12,
        "digest": "preserved",
    }


def test_real_native_launcher_accepts_connection_identifier_and_rejects_unsafe_parameters(
    ops: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launches: list[list[str]] = []

    class Process:
        def wait(self, timeout: int) -> int:
            assert timeout == 30
            return 0

    def spawn(arguments: list[str], **kwargs: Any) -> Process:
        assert kwargs["stderr"] == ops.dates.subprocess.STDOUT
        assert kwargs["stdout"].fileno() >= 0
        launches.append(arguments)
        return Process()

    monkeypatch.setattr(ops.dates.subprocess, "Popen", spawn)
    parameters = {"RELEASE_ID": "catalogue-source", "NEO4J_CONNECTION": "jobtology-neo4j"}
    log = ops.dates.native(
        "fixture-hop",
        "/project/stage_flat_release.hwf",
        tmp_path,
        "real-native-validation",
        parameters,
    )
    assert len(launches) == 1
    assert launches[0][-2:] == [
        "-p",
        "RELEASE_ID=catalogue-source,NEO4J_CONNECTION=jobtology-neo4j",
    ]
    assert log.stat().st_mode & 0o777 == 0o600
    unsafe = (
        {"4NEO_CONNECTION": "connection"},
        {"NEO4J-CONNECTION": "connection"},
        {"neo4j_connection": "connection"},
        {"NEO4J_CONNECTION": "connection,RELEASE_ID=other"},
        {"NEO4J_CONNECTION": "connection\nother"},
    )
    for index, parameters in enumerate(unsafe):
        with pytest.raises(RuntimeError, match="Unsafe native date parameter"):
            ops.dates.native(
                "fixture-hop",
                "/project/stage_flat_release.hwf",
                tmp_path,
                "unsafe-native-validation-" + str(index),
                parameters,
            )
    assert len(launches) == 1


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


def revisions() -> list[tuple[str, list[str]]]:
    return [
        (
            "NODE",
            [
                key,
                frame("entityRevision", "jobPostingRevision", "ontologyObject"),
                props(id=("STRING NOT NULL", "revision/" + key)),
            ],
        )
        for key in ("a", "b")
    ]


@pytest.mark.parametrize(
    ("value_type", "value", "kind", "actual"),
    [
        ("date", "2026-10-01", "DATE NOT NULL", "2026-10-01"),
        ("datetime", "2026-10-01T00:00:00Z", "ZONED DATETIME NOT NULL", "2026-10-01T00:00:00Z"),
        ("datetime", "2026-10-01T00:00:00Z", "ZONED DATETIME NOT NULL", "2026-10-01T00:00Z"),
        ("string", "", "STRING NOT NULL", ""),
        ("number", "1.5", "FLOAT NOT NULL", "1.5"),
        ("integer", "2", "INTEGER NOT NULL", "2"),
        ("boolean", "true", "BOOLEAN NOT NULL", "true"),
    ],
)
def test_native_renderer_exact_types(
    ops: Any, value_type: str, value: str, kind: str, actual: str
) -> None:
    assert ops.native_value_matches({"value_type": value_type, "text_value": value}, [kind, actual])
    assert not ops.native_value_matches(
        {"value_type": value_type, "text_value": value},
        ["STRING NOT NULL" if kind != "STRING NOT NULL" else "DATE NOT NULL", actual],
    )


def test_dates_arrays_empty_and_null_shells(ops: Any) -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE legacy_property(owner_type TEXT,owner_id TEXT,payload TEXT)")
    fields = [
        {
            "key": "dates.end",
            "value_type": "date",
            "text_value": "2026-10-01",
            "is_array": True,
            "ordinal": 0,
            "array_size": 1,
        },
        {
            "key": "empty",
            "value_type": "empty_array",
            "text_value": None,
            "is_array": True,
            "ordinal": -1,
            "array_size": 0,
        },
        {
            "key": "missing",
            "value_type": "null",
            "text_value": None,
            "is_array": False,
            "ordinal": -1,
            "array_size": -1,
        },
    ]
    db.execute(
        "INSERT INTO legacy_property VALUES(?,?,?)", ("NODE", "r", json.dumps({"fields": fields}))
    )
    signature = props(
        **{
            "dates.end": ("LIST<DATE NOT NULL> NOT NULL", frame("2026-10-01")),
            "empty": ("LIST<NOTHING> NOT NULL", ""),
            "id": ("STRING NOT NULL", "r"),
        }
    )
    ops.require_native_properties(db, "NODE", "r", signature, {"id": "r"})
    with pytest.raises(RuntimeError, match="array value/type"):
        ops.require_native_properties(
            db,
            "NODE",
            "r",
            props(
                **{
                    "dates.end": ("LIST<STRING NOT NULL> NOT NULL", frame("2026-10-01")),
                    "empty": ("LIST<NOTHING> NOT NULL", ""),
                    "id": ("STRING NOT NULL", "r"),
                }
            ),
            {"id": "r"},
        )


def test_shared_revision_edges_consumed_once(ops: Any, tmp_path: Path) -> None:
    rows = [
        *revisions(),
        ("REL", ["edge", "a", "b", "DEPENDS_ON", props(id=("STRING NOT NULL", "edge"))]),
        ("REL", ["loop", "a", "a", "DERIVED_FROM", props(id=("STRING NOT NULL", "loop"))]),
    ]
    queries = list(ops.deletion_queries(archive(tmp_path / "before.sqlite", rows)))
    assert len(queries) == 2
    assert "WITH DISTINCT n,r" in queries[0]
    assert '"edge", "a", "b"' in queries[0]
    assert '"edge", "a", "b"' not in queries[1]
    assert "AND es=[]" in queries[1]
    assert all("DETACH" not in query for query in queries)


def test_rejects_mixed_revision_labels(ops: Any, tmp_path: Path) -> None:
    rows = revisions()
    rows[0][1][1] = frame("entityRevision", "jobPostingRevision", "ontologyObject", "entity")
    with pytest.raises(RuntimeError, match="Unexpected revision labels"):
        ops.revision_nodes(archive(tmp_path / "before.sqlite", rows))


def test_all_preexisting_tables_exact(ops: Any) -> None:
    baseline = {
        "ingestion.source_graph_projection": {"count": 86, "digest": "proof"},
        "catalog.catalog_approval": {"count": 1, "digest": "oldapproval"},
    }
    ops.require_old_tables(
        baseline, {**baseline, "ontology.flat_graph_projection": {"count": 1, "digest": "new"}}
    )
    with pytest.raises(RuntimeError, match="Pre-existing PostgreSQL"):
        ops.require_old_tables(
            baseline, {**baseline, "catalog.catalog_approval": {"count": 2, "digest": "changed"}}
        )


def test_recovery_restores_typed_before_maps(ops: Any, tmp_path: Path) -> None:
    path = archive(tmp_path / "before.sqlite", revisions())
    recovery = ops.prepare_recovery(path, tmp_path)
    assert recovery["statements"] == 2
    text = Path(recovery["path"]).read_text()
    assert "MERGE(n:ontologyObject" in text and "SET n=" in text
    assert "NEW_REVISION_ELEMENT_IDS" in recovery["mode"]
    assert oct(Path(recovery["path"]).stat().st_mode & 0o777) == "0o600"


def test_verified_recovery_refused_before_writes(
    ops: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(ops.common, "STATE", state)
    runtime = {"pg": "pg", "hop": "hop"}
    before = archive(tmp_path / "before.sqlite", revisions())
    manifest = {
        "graph": {"path": str(before)},
        "release_id": "r",
        "catalogue": {"approval": {"database_id": "db"}},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    receipt = {
        "kind": "FLAT_ONTOLOGY",
        "runtime": runtime,
        "token": "token",
        "manifest": str(manifest_path),
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    (state / ops.FENCE_NAME).write_text(json.dumps({"token": "token"}))

    def validated(value: Any) -> Path:
        return before

    def verified(*args: Any) -> dict[str, str]:
        return {"state": "VERIFIED", "load_id": "live"}

    def forbidden_read(*args: Any) -> Any:
        pytest.fail("Native reads/writes preceded VERIFIED recovery refusal")

    monkeypatch.setattr(ops.graph, "validate_archive", validated)
    monkeypatch.setattr(ops, "flat_load", verified)
    monkeypatch.setattr(ops.graph, "graph_snapshot", forbidden_read)
    with pytest.raises(RuntimeError, match="Recovery stopped"):
        ops.recover(runtime, path)
    result = json.loads(path.read_text())
    assert "Verified serving projection rollback" in result["failure_message"]
    assert (state / ops.FENCE_NAME).exists()


def test_focused_installer_and_deploy_scope(ops: Any, tmp_path: Path) -> None:
    path = tmp_path / "focused.hwf"
    ops.install_workflow(path)
    root = ET.parse(path).getroot()
    paths = [n.text for n in root.findall(".//sqlfilename")]
    assert paths == ["${PROJECT_HOME}/" + name for name in ops.MIGRATION_SQL]
    assert "ontology/load_release.hwf" in ops.deployment.ALLOWLIST
    assert "ontology/stage_flat_release.hwf" in ops.deployment.ALLOWLIST
    assert "ontology/finalize_flat_release.hwf" in ops.deployment.ALLOWLIST
    assert ops.FENCE_LINE in (ops.common.ROOT / "operations/refresh.sh").read_text()


def test_recovered_revision_new_internal_ids(ops: Any, tmp_path: Path) -> None:
    before = archive(tmp_path / "before.sqlite", revisions())
    recovered = revisions()
    recovered[0][1][0] = "new-a"
    recovered[1][1][0] = "new-b"
    after = archive(tmp_path / "after.sqlite", recovered)
    assert ops.require_recovered(before, after) == {"NODE": 2, "REL": 0}


def test_native_float_uses_binary64_without_rewriting_raw_decimal(ops: Any) -> None:
    field = {"value_type": "number", "text_value": "0.12345678901234567890123456789"}
    assert ops.native_value_matches(field, ["FLOAT NOT NULL", "0.12345678901234568"])
    assert not ops.native_value_matches(field, ["STRING NOT NULL", "0.12345678901234568"])
    assert field["text_value"] == "0.12345678901234567890123456789"


def test_run_holds_one_lock_across_fresh_plan_and_apply(
    ops: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    state = tmp_path / "state"
    reviewed = tmp_path / "reviewed.json"
    artifacts = {"ontology/sql/028_flat_graph_projection.sql": {"after": "frozen"}}
    reviewed.write_text(
        json.dumps(
            {
                "kind": "FLAT_ONTOLOGY",
                "release_id": "approved",
                "artifacts": artifacts,
                "catalogue": {"manifest_hash": "sealed"},
            }
        )
    )
    runtime = {"hop": "hop", "pg": "pg"}
    phases: list[str] = []

    def locked(fd: int, mode: int) -> None:
        assert mode == ops.fcntl.LOCK_EX | ops.fcntl.LOCK_NB
        phases.append("LOCK")

    def containers() -> dict[str, str]:
        return runtime

    def idle(*args: Any) -> None:
        pass

    def snapshot(*args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return artifacts, {}

    def plan(actual: dict[str, str], directory: Path, release: str, preflight: Path | None) -> Path:
        assert actual == runtime and release == "approved" and phases == ["LOCK"]
        phases.append("PLAN")
        path = directory / "manifest.json"
        path.write_text(json.dumps({"catalogue": {"manifest_hash": "sealed"}}))
        return path

    def apply(actual: dict[str, str], manifest: Path, directory: Path) -> Path:
        assert actual == runtime and phases == ["LOCK", "PLAN"] and manifest.parent.name == "plan"
        phases.append("APPLY")
        return directory / "receipt.json"

    monkeypatch.setattr(ops.common, "STATE", state)
    monkeypatch.setattr(ops.common, "containers", containers)
    monkeypatch.setattr(ops.common, "idle_cli", idle)
    monkeypatch.setattr(ops.dates, "require_idle", idle)
    monkeypatch.setattr(ops.deployment, "snapshot", snapshot)
    monkeypatch.setattr(ops.fcntl, "flock", locked)
    monkeypatch.setattr(ops, "make_plan", plan)
    monkeypatch.setattr(ops, "apply_plan", apply)
    result = ops.execute(
        argparse.Namespace(
            mode="run", reviewed_manifest=reviewed, release_id="approved", preflight=None
        )
    )
    assert phases == ["LOCK", "PLAN", "APPLY"] and result.parent.name == "apply"


def test_partial_property_proof_never_allows_wrong_present_types(ops: Any) -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE flat_property(owner_type TEXT,owner_id TEXT,payload TEXT)")
    fields = [
        {
            "key": "owned",
            "value_type": "integer",
            "text_value": "2",
            "is_array": False,
            "ordinal": -1,
            "array_size": -1,
        }
    ]
    db.execute(
        "INSERT INTO flat_property VALUES(?,?,?)", ("EDGE", "edge", json.dumps({"fields": fields}))
    )
    identity = props(id=("STRING NOT NULL", "edge"))
    ops.require_native_properties(
        db, "EDGE", "edge", identity, {"id": "edge"}, "flat_property", partial=True
    )
    with pytest.raises(RuntimeError, match="key inventory"):
        ops.require_native_properties(db, "EDGE", "edge", identity, {"id": "edge"}, "flat_property")
    wrong = props(id=("STRING NOT NULL", "edge"), owned=("STRING NOT NULL", "2"))
    with pytest.raises(RuntimeError, match="value/type"):
        ops.require_native_properties(
            db, "EDGE", "edge", wrong, {"id": "edge"}, "flat_property", partial=True
        )


def test_native_datetime_retains_nanoseconds(ops: Any) -> None:
    field = {"value_type": "datetime", "text_value": "2026-10-01T00:00:00.123456789Z"}
    assert ops.native_value_matches(
        field, ["ZONED DATETIME NOT NULL", "2026-10-01T00:00:00.123456789Z"]
    )
    assert not ops.native_value_matches(
        field, ["ZONED DATETIME NOT NULL", "2026-10-01T00:00:00.123456788Z"]
    )


def test_removed_legacy_edge_internal_id_reused_by_proven_flat_edge(
    ops: Any, tmp_path: Path
) -> None:
    baseline = archive(
        tmp_path / "before.sqlite",
        [
            (
                "NODE",
                [
                    "c",
                    frame("ontologyEntity", "ontologyObject"),
                    props(
                        id=("STRING NOT NULL", "entity/c"),
                        content_hash=("STRING NOT NULL", "old-hash"),
                    ),
                ],
            ),
            (
                "NODE",
                [
                    "r",
                    frame("entityRevision", "jobPostingRevision", "ontologyObject"),
                    props(id=("STRING NOT NULL", "revision/r")),
                ],
            ),
            ("REL", ["reused", "r", "c", "DERIVED_FROM", props(id=("STRING NOT NULL", "legacy"))]),
        ],
    )
    final = archive(
        tmp_path / "final.sqlite",
        [
            (
                "NODE",
                [
                    "c",
                    frame("ontologyEntity", "ontologyObject"),
                    props(
                        id=("STRING NOT NULL", "entity/c"),
                        content_hash=("STRING NOT NULL", "old-hash"),
                        flat_content_hash=("STRING NOT NULL", "flat-hash"),
                        flat_owned_keys=("LIST<NOTHING> NOT NULL", ""),
                    ),
                ],
            ),
            (
                "REL",
                [
                    "reused",
                    "c",
                    "c",
                    "DERIVED_FROM",
                    props(
                        id=("STRING NOT NULL", "new"),
                        content_hash=("STRING NOT NULL", "new-hash"),
                        release_id=("STRING NOT NULL", "release"),
                    ),
                ],
            ),
        ],
    )
    path = tmp_path / "proof.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE flat_graph_node(id TEXT PRIMARY KEY,payload TEXT)")
    db.execute("CREATE TABLE flat_graph_edge(id TEXT PRIMARY KEY,payload TEXT)")
    db.execute("CREATE TABLE flat_property(owner_type TEXT,owner_id TEXT,payload TEXT)")
    db.execute(
        "INSERT INTO flat_graph_node VALUES(?,?)",
        (
            "entity/c",
            json.dumps(
                {
                    "labels": ["ontologyEntity"],
                    "owned_properties": {},
                    "content_hash": "old-hash",
                    "flat_content_hash": "flat-hash",
                }
            ),
        ),
    )
    db.execute(
        "INSERT INTO flat_graph_edge VALUES(?,?)",
        (
            "new",
            json.dumps(
                {
                    "origin_edge_id": "legacy",
                    "predicate": "DERIVED_FROM",
                    "subject_id": "entity/c",
                    "object_id": "entity/c",
                    "content_hash": "new-hash",
                }
            ),
        ),
    )
    db.commit()
    db.close()
    path.chmod(0o600)
    result = ops.require_flat_preserved(
        baseline,
        final,
        {"path": str(path), "sha256": ops.checksum(path), "release_id": "release"},
        removed=True,
    )
    assert result["rerouted_edges"] == 1
