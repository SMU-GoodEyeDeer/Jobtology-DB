"""Exercise deployment fail-closed guards and recovery evidence without live Docker."""

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

type Deployment = tuple[Any, dict[str, str], dict[str, Any], Path, Path, list[list[str]]]


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Deployment:
    path = Path(__file__).resolve().parents[2] / "hop/operations/reconcile_runtime.py"
    spec = importlib.util.spec_from_file_location("reconcile_runtime", path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    target = tmp_path / "mounted"
    state = tmp_path / "state"
    adapter = tmp_path / "host/refresh"
    migration = "ontology/sql/027_product_role_inputs.sql"
    installer = "ontology/install.hwf"
    dependency = "ontology/sql/000_retention_dependency.sql"
    xml = (
        "<workflow><actions>"
        + "".join(
            f"<action><type>SQL</type><sqlfilename>${{PROJECT_HOME}}/{p}</sqlfilename></action>"
            for p in (dependency, migration)
        )
        + "</actions></workflow>"
    )
    for root, files in (
        (
            source,
            {
                dependency: b"baseline",
                migration: b"new SQL",
                installer: xml.encode(),
                "operations/refresh.sh": b"new adapter",
            },
        ),
        (
            target,
            {
                dependency: b"baseline",
                installer: b"old installer",
                "metadata/private.json": b"private connection",
                "data/evidence": b"raw evidence",
            },
        ),
    ):
        for relative, content in files.items():
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
    state.mkdir()
    adapter.parent.mkdir()
    adapter.write_bytes(b"old adapter")
    for name, value in (
        ("ROOT", source),
        ("STATE", state),
        ("ADAPTER", adapter),
        ("ALLOWLIST", (migration, installer)),
    ):
        monkeypatch.setattr(module, name, value)
    runtime = {"hop": "test-hop", "pg": "test-pg"}
    db: dict[str, Any] = {"catalog_context": {"release_id": "approved"}}

    def db_state(_: str) -> dict[str, Any]:
        return db

    def idle_cli(_: str) -> None:
        pass

    monkeypatch.setattr(module, "db_state", db_state)
    monkeypatch.setattr(module, "idle_cli", idle_cli)

    def mounted(relative: str) -> bytes | None:
        file = target / relative
        return file.read_bytes() if file.exists() else None

    def remote_bytes(_: str, relative: str) -> bytes | None:
        return mounted(relative)

    monkeypatch.setattr(module, "remote_bytes", remote_bytes)
    calls: list[list[str]] = []

    def remote_path(absolute: str) -> Path:
        return target / absolute.removeprefix(module.PROJECT + "/")

    def command(args: list[str], *, data: bytes | None = None) -> bytes:
        calls.append(args)
        if "pg_dump" in args:
            return b"protected schema archive"
        if "pg_restore" in args:
            assert data == b"protected schema archive"
            return b"archive listing"
        if args[:2] == ["docker", "cp"]:
            shutil.copyfile(args[2], remote_path(args[3].split(":", 1)[1]))
        elif "sha256sum" in args:
            return module.digest(remote_path(args[-1]).read_bytes()).encode() + b" file\n"
        elif "mv" in args:
            assert args[:4] == ["docker", "exec", "-u", "root"]
            remote_path(args[-2]).replace(remote_path(args[-1]))
        elif "rm" in args:
            assert args[:4] == ["docker", "exec", "-u", "root"]
            remote_path(args[-1]).unlink(missing_ok=True)
        else:
            assert "chown" in args or "chmod" in args, args
            assert "-R" not in args
            assert "/metadata/" not in args[-1] and "/data/" not in args[-1]
        return b""

    monkeypatch.setattr(module, "command", command)
    manifest = tmp_path / "manifest.json"
    entries, _ = module.snapshot(runtime)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "containers": runtime,
                "catalog_context": db["catalog_context"],
                "artifacts": entries,
            }
        )
    )
    return module, runtime, db, manifest, target, calls


def test_installer_rejects_path_traversal(deployment: Deployment) -> None:
    module, *_ = deployment
    xml = (
        b"<workflow><actions><action><type>SQL</type><sqlfilename>"
        b"${PROJECT_HOME}/ontology/../metadata/private.sql"
        b"</sqlfilename></action></actions></workflow>"
    )
    with pytest.raises(RuntimeError, match="Unexpected ontology installer"):
        module.installer_dependencies(xml)


def test_existing_dependency_drift_cannot_be_overwritten(deployment: Deployment) -> None:
    module, runtime, _, _, target, calls = deployment
    (target / "ontology/sql/000_retention_dependency.sql").write_bytes(b"live user edit")
    with pytest.raises(RuntimeError, match="existing installer dependency drift"):
        module.snapshot(runtime)
    assert calls == []


def test_stale_plan_rejected_before_any_mutation_or_backup(deployment: Deployment) -> None:
    module, runtime, db, manifest, target, calls = deployment
    (target / "ontology/install.hwf").write_bytes(b"new live edit")
    with pytest.raises(RuntimeError, match="Artifacts changed since planning"):
        module.apply(manifest, runtime, db)
    assert list(module.STATE.iterdir()) == []
    assert calls == []


def test_success_preserves_private_artifacts_and_backups(deployment: Deployment) -> None:
    module, runtime, db, manifest, target, calls = deployment
    receipt_path: Path = module.apply(manifest, runtime, db)
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "VERIFIED"
    assert receipt["installed"] == [*module.ALLOWLIST, module.ADAPTER_KEY]
    assert (target / "metadata/private.json").read_bytes() == b"private connection"
    assert (target / "data/evidence").read_bytes() == b"raw evidence"
    assert (receipt_path.parent / "before/ontology/install.hwf").read_bytes() == b"old installer"
    assert (
        receipt_path.parent / "before/host/jobtology-hop-refresh"
    ).read_bytes() == b"old adapter"
    assert (receipt_path.parent / "database-schema.dump").stat().st_mode & 0o777 == 0o600
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert module.ADAPTER.read_bytes() == b"new adapter"
    assert not any("psql" in call for call in calls)


def test_partial_failure_retains_backup_and_receipt(
    deployment: Deployment, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, runtime, db, manifest, target, _ = deployment
    command = module.command

    def fail_installer_rename(args: list[str], **kwargs: Any) -> bytes:
        if "mv" in args and args[-1].endswith("/ontology/install.hwf"):
            raise RuntimeError("simulated rename failure")
        return command(args, **kwargs)

    monkeypatch.setattr(module, "command", fail_installer_rename)
    with pytest.raises(RuntimeError, match="inspect protected receipt"):
        module.apply(manifest, runtime, db)
    receipt_path: Path = next(module.STATE.glob("runtime-reconciliation-applied-*/receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
    assert receipt["failure"] == {
        "action": {
            "phase": "INSTALLING",
            "operation": "atomic-rename",
            "artifact": "ontology/install.hwf",
        },
        "error_type": "RuntimeError",
    }
    assert receipt["installed"] == [module.ALLOWLIST[0]]
    assert (target / "ontology/install.hwf").read_bytes() == b"old installer"
    assert module.ADAPTER.read_bytes() == b"old adapter"
    assert not list(target.rglob("*.reconcile-*"))
