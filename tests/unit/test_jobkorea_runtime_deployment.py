"""Verify deployment races and failure recovery without writing live containers."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    directory = Path(__file__).resolve().parents[2] / "hop/operations"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "jobkorea_runtime_deployment_test", directory / "deploy_jobkorea_runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    target = tmp_path / "target"
    state = tmp_path / "state"
    relative = "ingestions/jobkorea/install.hwf"
    for root, content in ((source, b"reviewed installer"), (target, b"previous installer")):
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    private = target / "metadata/rdbms/private.json"
    private.parent.mkdir(parents=True)
    private.write_bytes(b"private connection")
    state.mkdir()
    monkeypatch.setattr(module, "ROOT", source)
    monkeypatch.setattr(module, "STATE", state)
    monkeypatch.setattr(module, "ALLOWLIST", (relative,))
    monkeypatch.setattr(module, "dependencies", lambda: ())
    runtime = {"hop": "hop-test", "pg": "pg-test"}
    database = {"catalog_context": {"release_id": "approved"}}
    preserved = {"enrichment.attempt": {"count": 10, "digest": "unchanged"}}
    monkeypatch.setattr(module, "preservation_state", lambda _: preserved)
    monkeypatch.setattr(module, "full_preservation_state", lambda _: preserved)
    monkeypatch.setattr(module.common, "db_state", lambda _: database)
    monkeypatch.setattr(module.common, "idle_cli", lambda _: None)

    def remote_bytes(_: str, artifact: str) -> bytes | None:
        path = target / artifact
        return path.read_bytes() if path.exists() else None

    monkeypatch.setattr(module, "remote_bytes", remote_bytes)
    monkeypatch.setattr(
        module,
        "ensure_parent",
        lambda _, rel: (target / rel).parent.mkdir(parents=True, exist_ok=True),
    )
    calls: list[list[str]] = []

    def backup(_: str, destination: Path) -> dict[str, str]:
        calls.append(["backup"])
        path = destination / "database-before.dump"
        path.write_bytes(b"validated full backup")
        return {"path": str(path), "format": "POSTGRES_CUSTOM_FULL"}

    monkeypatch.setattr(module, "backup_database", backup)

    def local(absolute: str) -> Path:
        return target / absolute.removeprefix(module.PROJECT + "/")

    def command(args: list[str], **_: Any) -> bytes:
        calls.append(args)
        if args[:2] == ["docker", "cp"]:
            shutil.copyfile(args[2], local(args[3].split(":", 1)[1]))
        elif "sha256sum" in args:
            return module.common.digest(local(args[-1]).read_bytes()).encode() + b" staged\n"
        elif "mv" in args:
            assert args[:4] == ["docker", "exec", "-u", "root"]
            local(args[-2]).replace(local(args[-1]))
        elif "rm" in args:
            local(args[-1]).unlink(missing_ok=True)
        else:
            assert "chown" in args or "chmod" in args
            assert "-R" not in args
        return b""

    monkeypatch.setattr(module.common, "command", command)
    entries, _ = module.snapshot(runtime)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "containers": runtime,
                "catalog_context": database["catalog_context"],
                "artifacts": entries,
                "preservation_state": preserved,
                "full_preservation_state": preserved,
            }
        )
    )
    return module, runtime, database, manifest, target, calls


def test_stale_artifact_rejected_without_backup_or_mutation(deployment: tuple[Any, ...]) -> None:
    module, runtime, database, manifest, target, calls = deployment
    (target / module.ALLOWLIST[0]).write_bytes(b"user saved new runtime changes")
    with pytest.raises(RuntimeError, match="Artifacts changed since planning"):
        module.apply(manifest, runtime, database)
    assert calls == []
    assert list(module.STATE.iterdir()) == []


def test_backup_failure_prevents_file_replacement(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, runtime, database, manifest, target, calls = deployment

    def failure(*_: Any) -> Any:
        raise RuntimeError("backup failed")

    monkeypatch.setattr(module, "backup_database", failure)
    with pytest.raises(RuntimeError, match="inspect protected receipt"):
        module.apply(manifest, runtime, database)
    assert calls == []
    assert (target / module.ALLOWLIST[0]).read_bytes() == b"previous installer"
    receipt_path = next(module.STATE.glob("jobkorea-runtime-applied-*/receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
    assert receipt["installed"] == []
    assert (receipt_path.parent / "before" / module.ALLOWLIST[0]).read_bytes() == (
        b"previous installer"
    )


def test_staged_hash_failure_preserves_runtime_and_cleans_exact_temp(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, runtime, database, manifest, target, calls = deployment
    original = module.common.command

    def corrupted(args: list[str], **kwargs: Any) -> bytes:
        if "sha256sum" in args:
            calls.append(args)
            return b"incorrect staged\n"
        return original(args, **kwargs)

    monkeypatch.setattr(module.common, "command", corrupted)
    with pytest.raises(RuntimeError, match="inspect protected receipt"):
        module.apply(manifest, runtime, database)
    assert calls[0] == ["backup"]
    assert (target / module.ALLOWLIST[0]).read_bytes() == b"previous installer"
    assert not list(target.rglob("*.jobkorea-deploy-*"))
    assert (target / "metadata/rdbms/private.json").read_bytes() == b"private connection"


def test_success_is_idempotent_and_keeps_private_metadata(deployment: tuple[Any, ...]) -> None:
    module, runtime, database, manifest, target, calls = deployment
    path = module.apply(manifest, runtime, database)
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "VERIFIED"
    assert receipt["installed"] == list(module.ALLOWLIST)
    assert receipt["executed_sql"] is False and receipt["executed_jobs"] is False
    assert calls[0] == ["backup"]
    assert (target / "metadata/rdbms/private.json").read_bytes() == b"private connection"
    entries, _ = module.snapshot(runtime)
    assert all(not entry["change"] for entry in entries.values())


def test_native_dependency_path_rejects_private_traversal(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, *_ = deployment
    monkeypatch.undo()
    source = module.ROOT / "ingestions/jobkorea/install.hwf"
    original = source.read_bytes()
    # Use an isolated temporary root rather than editing the repository workflow.
    tmp_path = deployment[3].parent / "dependency-fixture"
    artifact = tmp_path / "ingestions/jobkorea/install.hwf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(
        b"<workflow><filename>${PROJECT_HOME}/llm/../metadata/private.sql</filename></workflow>"
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "ENTRYPOINTS", ("ingestions/jobkorea/install.hwf",))
    with pytest.raises(RuntimeError, match="Unexpected native runtime dependency"):
        module.dependencies()
    assert source.read_bytes() == original


def test_file_deployment_fingerprints_all_sources_and_inference_tables(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, *_ = deployment
    # Restore the real function hidden by the deployment fixture's injected baseline.
    monkeypatch.undo()
    queries: list[str] = []
    names = ["ingestion.record", "enrichment.input_bundle", "enrichment.metadata_occupation_result"]
    expected = {name: {"count": 1, "digest": "protected"} for name in names}

    def sql(_: str, query: str) -> str:
        queries.append(query)
        return json.dumps(names if len(queries) == 1 else expected)

    monkeypatch.setattr(module, "sql", sql)
    assert module.full_preservation_state("pg-test") == expected
    assert (
        "'attachment','catalog','cs','enrichment','ingestion','ontology','retention'" in queries[0]
    )
    assert all(f"FROM {name} x)" in queries[1] for name in names)
    assert "source_id<>" not in queries[1]
    assert "-'transport'" not in queries[1]
    assert "REPEATABLE READ READ ONLY" in queries[1]


def test_fingerprint_relation_names_cannot_inject_sql(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, *_ = deployment
    monkeypatch.undo()
    monkeypatch.setattr(module, "sql", lambda *_: json.dumps(["enrichment.result; DROP SCHEMA cs"]))
    with pytest.raises(RuntimeError, match="Unexpected protected relation"):
        module.full_preservation_state("pg-test")


def test_legacy_load_baseline_still_excludes_jobkorea(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, *_ = deployment
    monkeypatch.undo()
    queries: list[str] = []

    def sql(_: str, query: str) -> str:
        queries.append(query)
        return json.dumps(["enrichment.input_bundle"] if len(queries) == 1 else {})

    monkeypatch.setattr(module, "sql", sql)
    assert module.preservation_state("pg-test") == {}
    assert "WHERE x.source_id<>'jobkorea'" in queries[1]
    assert "WHERE r.source_id<>'jobkorea'" in queries[1]
    assert "to_jsonb(x)-'transport'" in queries[1]


def test_new_plan_is_accepted_by_existing_load_supervisor(
    deployment: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, runtime, database, manifest, *_ = deployment
    legacy = {"ingestion.record": {"count": 1, "digest": "legacy"}}
    full = {**legacy, "enrichment.metadata_occupation_result": {"count": 2, "digest": "new"}}
    monkeypatch.setattr(module, "preservation_state", lambda _: legacy)
    monkeypatch.setattr(module, "full_preservation_state", lambda _: full)
    entries, _ = module.snapshot(runtime)
    plan = module.plan_manifest(runtime, database, entries)
    assert plan["preservation_state"] == legacy
    assert plan["full_preservation_state"] == full
    manifest.write_text(json.dumps(plan))
    spec = importlib.util.spec_from_file_location(
        "jobkorea_loader_plan_interop_test",
        Path(__file__).resolve().parents[2] / "hop/operations/load_jobkorea_dataset.py",
    )
    assert spec is not None and spec.loader is not None
    loader: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    monkeypatch.setattr(loader, "deployment", module)
    monkeypatch.setattr(loader, "composition_identity", lambda _: ({}, {}))
    monkeypatch.setattr(loader.common, "containers", lambda: runtime)
    reached: list[str] = []

    def stop_at_deployment(*_: Any) -> Path:
        reached.append("accepted_legacy_plan_baseline")
        raise RuntimeError("intentional stop before mutation")

    monkeypatch.setattr(module, "apply", stop_at_deployment)
    with pytest.raises(RuntimeError, match="intentional stop before mutation"):
        loader.load(manifest, manifest.parent, manifest.parent)
    assert reached == ["accepted_legacy_plan_baseline"]


def test_file_deployment_rejects_missing_full_baseline_before_backup(
    deployment: tuple[Any, ...]
) -> None:
    module, runtime, database, manifest, _target, calls = deployment
    plan = json.loads(manifest.read_text())
    del plan["full_preservation_state"]
    manifest.write_text(json.dumps(plan))
    with pytest.raises(RuntimeError, match="Full file-deployment baseline changed or absent"):
        module.apply(manifest, runtime, database)
    assert calls == []
