from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from jobtology_db.admin.config import load_profiles
from jobtology_db.admin.queue import JobStore, QueueConflict


def enqueue(store: JobStore, key: str = "local-request-123456") -> dict[str, Any]:
    return store.enqueue(
        "refresh-due", "operator", key, kind="refresh_due", profile_sha256="a" * 64
    )


def test_queue_concurrency_idempotency_and_restart(tmp_path: Path):
    store = JobStore(tmp_path / "queue.sqlite3")
    store.initialize()

    def queue_request(_index: int) -> dict[str, Any]:
        return enqueue(store)

    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = list(executor.map(queue_request, range(8)))
    assert len({job["id"] for job in jobs}) == 1
    assert store.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(QueueConflict):
        store.enqueue(
            "refresh-due",
            "another-actor",
            "local-request-123456",
            kind="refresh_due",
            profile_sha256="a" * 64,
        )
    with pytest.raises(QueueConflict):
        store.enqueue(
            "refresh-due",
            "operator",
            "local-request-123456",
            kind="load_jobkorea",
            profile_sha256="a" * 64,
        )

    def claim_job(index: int) -> dict[str, Any] | None:
        return store.claim(f"worker-{index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        claimed = list(executor.map(claim_job, range(8)))
    assert sum(job is not None for job in claimed) == 1
    restarted = JobStore(store.path)
    restarted.initialize()
    assert restarted.abandon_running() == 1
    assert restarted.claim("new-worker") is None
    assert restarted.list_jobs()[0]["state"] == "UNKNOWN"
    with pytest.raises(QueueConflict):
        enqueue(restarted, "another-request-12345")


def test_finish_heartbeat_and_fifo(tmp_path: Path):
    store = JobStore(tmp_path / "queue.sqlite3")
    store.initialize()
    first = enqueue(store)
    with pytest.raises(QueueConflict):
        enqueue(store, "second-request-12345")
    store.heartbeat("worker")
    worker = store.worker_status()
    assert worker is not None and worker["worker_id"] == "worker"
    claimed = store.claim("worker")
    assert claimed is not None and claimed["id"] == first["id"]
    store.finish(first["id"], "SUCCEEDED", "Refresh completed.")
    second = enqueue(store, "second-request-12345")
    claimed = store.claim("worker")
    assert claimed is not None and claimed["id"] == second["id"]
    with pytest.raises(QueueConflict):
        store.finish(first["id"], "FAILED", "Cannot overwrite a result.")
    store.stop_worker("someone-else")
    assert store.worker_status() is not None
    store.stop_worker("worker")
    assert store.worker_status() is None


def test_distinct_requests_cannot_queue_duplicate_work(tmp_path: Path):
    store = JobStore(tmp_path / "queue.sqlite3")
    store.initialize()

    def request(index: int):
        try:
            return enqueue(store, f"different-request-{index:03d}")
        except QueueConflict:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(request, range(8)))
    assert sum(result is not None for result in results) == 1
    assert len(store.list_jobs()) == 1


@pytest.mark.parametrize(
    "parameters",
    [
        {"runtime_env": "relative.env"},
        {"runtime_env": "/safe/../private.env"},
        {"runtime_env": "/safe/env\nsecret"},
        {"runtime_env": "/safe/env", "command": "sh"},
    ],
)
def test_profiles_reject_path_and_argument_injection(tmp_path: Path, parameters: dict[str, str]):
    path = tmp_path / "actions.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": [
                    {
                        "id": "refresh-due",
                        "label": "Refresh",
                        "kind": "refresh_due",
                        "parameters": parameters,
                    }
                ],
            }
        )
    )
    path.chmod(0o600)
    with pytest.raises(ValueError) as error:
        load_profiles(path)
    assert "input_value" not in str(error.value)
    assert parameters["runtime_env"] not in str(error.value)


def test_profile_permissions_symlinks_and_hash_pinning(tmp_path: Path):
    path = tmp_path / "actions.json"
    payload: dict[str, Any] = {
        "version": 1,
        "actions": [
            {
                "id": "refresh-due",
                "label": "Refresh",
                "kind": "refresh_due",
                "parameters": {"runtime_env": "/safe/runtime.env"},
            }
        ],
    }
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    before = load_profiles(path)[0].fingerprint()
    payload["actions"][0]["parameters"]["runtime_env"] = "/other/runtime.env"
    path.write_text(json.dumps(payload))
    assert load_profiles(path)[0].fingerprint() != before
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        load_profiles(link)
    path.chmod(0o666)
    with pytest.raises(ValueError):
        load_profiles(path)
