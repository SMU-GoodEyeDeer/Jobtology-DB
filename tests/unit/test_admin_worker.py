"""Offline host worker checks: subprocesses are always replaced with test doubles."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from jobtology_db.admin.config import ActionProfile
from jobtology_db.admin.queue import JobStore, QueueConflict
from jobtology_db.admin.worker import (
    HostWorker,
    InvalidAction,
    WorkerAlreadyRunning,
    command_for,
    worker_lock,
)

WorkerSetup = tuple[HostWorker, ActionProfile]


@pytest.fixture
def worker_setup(tmp_path: Path) -> WorkerSetup:
    repository = tmp_path / "repository"
    operations = repository / "hop/operations"
    operations.mkdir(parents=True)
    for name in ("refresh.sh", "load_jobkorea_dataset.py"):
        (operations / name).write_text("# offline placeholder\n")
        (operations / name).chmod(0o644)
    runtime = tmp_path / "runtime.env"
    runtime.write_text("# protected runtime\n")
    runtime.chmod(0o600)
    profile = ActionProfile(
        id="refresh-due",
        label="Refresh due sources",
        kind="refresh_due",
        parameters={"runtime_env": str(runtime)},
    )
    profiles = tmp_path / "actions.json"
    profiles.write_text(json.dumps({"version": 1, "actions": [profile.model_dump()]}))
    profiles.chmod(0o640)
    store = JobStore(tmp_path / "queue/queue.sqlite3")
    store.initialize()
    worker = HostWorker(
        store, profiles, repository, heartbeat_seconds=0.01, log_dir=tmp_path / "host-only-logs"
    )
    return worker, profile


def enqueue(worker: HostWorker, profile: ActionProfile, suffix: str = "") -> dict[str, Any]:
    return worker.store.enqueue(
        profile.id,
        "operator",
        "offline-request-0001" + suffix,
        kind=profile.kind,
        profile_sha256=profile.fingerprint(),
    )


def test_fixed_refresh_argv_and_public_outcome(
    worker_setup: WorkerSetup, monkeypatch: pytest.MonkeyPatch
):
    worker, profile = worker_setup
    enqueue(worker, profile)

    def launch_command(*_args: Any, **kwargs: Any) -> Mock:
        kwargs["stdout"].write(b"protected-diagnostic-credential\n")
        return Mock(wait=Mock(return_value=0))

    launch = Mock(side_effect=launch_command)
    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.run(once=True)
    arguments, options = launch.call_args
    assert arguments[0] == ["/bin/bash", str(worker.repo_root / "hop/operations/refresh.sh")]
    assert options["shell"] is False
    assert options["env"]["JOBTOLOGY_HOP_RUNTIME"] == profile.parameters["runtime_env"]
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.STDOUT
    assert len(options["pass_fds"]) == 1
    job = worker.store.list_jobs()[0]
    assert job["state"] == "SUCCEEDED"
    assert "idle, fenced or lock-busy" in job["summary"]
    assert "ledger" in job["summary"]
    assert str(worker.repo_root) not in job["summary"]
    assert "protected-diagnostic-credential" not in job["summary"]
    log = worker.log_dir / f"{job['id']}.log"
    assert log.read_text() == "protected-diagnostic-credential\n"
    assert log.stat().st_mode & 0o777 == 0o600
    assert worker.log_dir.stat().st_mode & 0o777 == 0o700
    assert worker.store.worker_status() is None


def test_changed_profile_never_launches(worker_setup: WorkerSetup, monkeypatch: pytest.MonkeyPatch):
    worker, profile = worker_setup
    enqueue(worker, profile)
    modified = profile.model_copy(update={"description": "new approval required"})
    worker.actions_file.write_text(json.dumps({"version": 1, "actions": [modified.model_dump()]}))
    launch = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.run(once=True)
    launch.assert_not_called()
    assert worker.store.list_jobs()[0]["state"] == "FAILED"


def test_operation_logs_cannot_use_the_web_queue_mount(
    worker_setup: WorkerSetup,
    monkeypatch: pytest.MonkeyPatch,
):
    worker, profile = worker_setup
    worker.log_dir = worker.store.path.parent / "logs"
    enqueue(worker, profile)
    launch = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.run(once=True)
    launch.assert_not_called()
    assert worker.store.list_jobs()[0]["state"] == "FAILED"


def test_duplicate_worker_cannot_recover_or_claim_running_job(
    worker_setup: WorkerSetup,
    monkeypatch: pytest.MonkeyPatch,
):
    worker, profile = worker_setup
    queued = enqueue(worker, profile)
    worker.store.claim("original-worker")
    worker.store.heartbeat("original-worker", queued["id"])
    launch = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)
    with worker_lock(worker.store.path), pytest.raises(WorkerAlreadyRunning):
        worker.run(once=True)
    assert worker.store.list_jobs()[0]["state"] == "RUNNING"
    status = worker.store.worker_status()
    assert status is not None
    assert status["worker_id"] == "original-worker"
    launch.assert_not_called()


def test_restart_marks_orphan_unknown_and_blocks_further_work(
    worker_setup: WorkerSetup,
    monkeypatch: pytest.MonkeyPatch,
):
    worker, profile = worker_setup
    enqueue(worker, profile)
    worker.store.claim("crashed-worker")
    launch = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.run(once=True)
    assert worker.store.list_jobs()[0]["state"] == "UNKNOWN"
    launch.assert_not_called()
    with pytest.raises(QueueConflict):
        enqueue(worker, profile, "-third")


def test_heartbeat_during_long_operation_and_stop_drains_current_job(
    worker_setup: WorkerSetup,
    monkeypatch: pytest.MonkeyPatch,
):
    worker, profile = worker_setup
    first = enqueue(worker, profile)
    observations: list[dict[str, Any]] = []

    def wait(*, timeout: float) -> int:
        status = worker.store.worker_status()
        assert status is not None
        observations.append(status)
        worker.stop.set()
        if len(observations) == 1:
            raise subprocess.TimeoutExpired("private-host-command", timeout)
        return 0

    launch = Mock(return_value=Mock(wait=wait))
    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.run()
    assert len(observations) == 2
    assert all(item["job_id"] == first["id"] for item in observations)
    assert worker.store.list_jobs()[0]["state"] == "SUCCEEDED"
    launch.assert_called_once()


@pytest.mark.parametrize("outcome, expected", [(3, "FAILED"), (-9, "UNKNOWN")])
def test_nonzero_operation_is_not_reported_as_verified(
    worker_setup: WorkerSetup,
    monkeypatch: pytest.MonkeyPatch,
    outcome: int,
    expected: str,
):
    worker, profile = worker_setup
    enqueue(worker, profile)
    monkeypatch.setattr(
        subprocess, "Popen", Mock(return_value=Mock(wait=Mock(return_value=outcome)))
    )
    worker.run(once=True)
    job = worker.store.list_jobs()[0]
    assert job["state"] == expected
    assert "receipts" in job["summary"]


def test_subprocess_exception_is_unknown_without_public_exception_text(
    worker_setup: WorkerSetup,
    monkeypatch: pytest.MonkeyPatch,
):
    worker, profile = worker_setup
    enqueue(worker, profile)
    process = Mock(wait=Mock(side_effect=RuntimeError("secret-key /protected/raw/path")))
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(RuntimeError, match="uncertain"):
        worker.run(once=True)
    job = worker.store.list_jobs()[0]
    assert job["state"] == "UNKNOWN"
    assert "secret-key" not in job["summary"]
    assert "raw/path" not in job["summary"]
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_load_manifest_content_is_pinned(worker_setup: WorkerSetup, tmp_path: Path):
    worker, _ = worker_setup
    manifest = tmp_path / "approved-manifest.json"
    manifest.write_text('{"reviewed": true}\n')
    manifest.chmod(0o600)
    composition = tmp_path / "composition"
    composition.mkdir()
    profile = ActionProfile(
        id="load-local",
        label="Load approved snapshot",
        kind="load_jobkorea",
        parameters={
            "manifest": str(manifest),
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "composition_dir": str(composition),
            "checkpoint_dir": str(tmp_path / "private-checkpoints"),
        },
    )
    argv, _environment = command_for(profile, worker.repo_root)
    assert argv[1:] == [
        str(worker.repo_root / "hop/operations/load_jobkorea_dataset.py"),
        "--manifest",
        str(manifest),
        "--composition-dir",
        str(composition),
        "--checkpoint-dir",
        str(tmp_path / "private-checkpoints"),
    ]
    manifest.write_text('{"reviewed": false}\n')
    with pytest.raises(InvalidAction, match="manifest changed"):
        command_for(profile, worker.repo_root)


def test_worker_lock_is_not_released_while_inherited_descriptor_survives(tmp_path: Path):
    queue_path = tmp_path / "queue.sqlite3"
    with worker_lock(queue_path) as descriptor:
        inherited = os.dup(descriptor)
    try:
        with pytest.raises(WorkerAlreadyRunning), worker_lock(queue_path):
            pytest.fail("surviving operation must retain exclusivity")
    finally:
        os.close(inherited)
    with worker_lock(queue_path):
        pass
