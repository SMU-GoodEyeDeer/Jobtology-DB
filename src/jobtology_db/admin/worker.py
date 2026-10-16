"""Host-only dispatcher for the two fixed, operator-approved ingestion actions.

The HTTP process never imports this module. The durable queue and this worker's
exclusive lock must share one local filesystem; neither belongs on NFS.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import signal
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jobtology_db.admin.config import ActionProfile, load_profiles
from jobtology_db.admin.queue import JobStore

RESTART_SUMMARY = "Worker restarted; previous operation outcome requires operator review."
UNCONFIRMED_SUMMARY = (
    "Command outcome is uncertain; inspect protected host receipts before another operation."
)


class WorkerAlreadyRunning(RuntimeError):
    """Another host worker or its surviving child still holds the execution lock."""


class InvalidAction(ValueError):
    """An approved profile or its pinned local evidence is no longer valid."""


@contextmanager
def worker_lock(queue_path: Path):
    """Open a distinct lock description, including for starts in the same process."""
    lock_path = queue_path.with_suffix(queue_path.suffix + ".worker.lock")
    queue_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkerAlreadyRunning(
                "An existing host operation holds the worker lock."
            ) from error
        # Popen explicitly passes this FD to the child: a crashed worker must not
        # release exclusivity while its underlying ingestion operation survives.
        yield descriptor
    finally:
        # Closing only (no LOCK_UN): the child's inherited open description must
        # retain its lock if the worker exits before the underlying operation.
        os.close(descriptor)


def _private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o022:
        raise InvalidAction("The protected host input is unavailable or writable by others.")


def command_for(profile: ActionProfile, repo_root: Path) -> tuple[list[str], dict[str, str]]:
    """Build literal argv from trusted on-host configuration, never HTTP fields."""
    environment = dict(os.environ)
    if profile.kind == "refresh_due":
        runtime = Path(profile.parameters["runtime_env"])
        _private_file(runtime)
        script = repo_root / "hop/operations/refresh.sh"
        _private_file(script)
        environment["JOBTOLOGY_HOP_RUNTIME"] = str(runtime)
        return ["/bin/bash", str(script)], environment
    if profile.kind == "load_jobkorea":
        manifest = Path(profile.parameters["manifest"])
        _private_file(manifest)
        # Pin the approved manifest bytes as well as the immutable queued profile.
        if manifest.stat().st_size > 16 * 1024 * 1024:
            raise InvalidAction("The approved manifest exceeds the permitted bound.")
        actual = hashlib.sha256(manifest.read_bytes()).hexdigest()
        if actual != profile.parameters["manifest_sha256"]:
            raise InvalidAction("The approved manifest changed.")
        composition = Path(profile.parameters["composition_dir"])
        checkpoint = Path(profile.parameters["checkpoint_dir"])
        if composition.is_symlink() or not composition.is_dir():
            raise InvalidAction("The approved local composition is unavailable.")
        if checkpoint.is_symlink():
            raise InvalidAction("The private checkpoint may not be a symlink.")
        script = repo_root / "hop/operations/load_jobkorea_dataset.py"
        _private_file(script)
        return [
            sys.executable,
            str(script),
            "--manifest",
            str(manifest),
            "--composition-dir",
            str(composition),
            "--checkpoint-dir",
            str(checkpoint),
        ], environment
    raise InvalidAction("Unsupported host operation.")


class HostWorker:
    def __init__(
        self,
        store: JobStore,
        actions_file: Path,
        repo_root: Path,
        *,
        poll_seconds: float = 2,
        heartbeat_seconds: float = 5,
        log_dir: Path | None = None,
    ):
        self.store = store
        self.actions_file = actions_file
        self.repo_root = repo_root.resolve()
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.log_dir = log_dir or Path.home() / ".local/state/jobtology-admin/logs"
        self.worker_id = str(uuid.uuid4())
        self.stop = threading.Event()

    def _profile(self, job: dict[str, Any]) -> ActionProfile:
        profiles = load_profiles(self.actions_file)
        profile = next((item for item in profiles if item.id == job["action_id"]), None)
        if (
            profile is None
            or profile.kind != job["kind"]
            or profile.fingerprint() != job["profile_sha256"]
        ):
            raise InvalidAction("The queued operation no longer matches its approved profile.")
        return profile

    def _execute(self, job: dict[str, Any], lock_descriptor: int) -> None:
        job_id = job["id"]
        self.store.heartbeat(self.worker_id, job_id)
        try:
            profile = self._profile(job)
            command, environment = command_for(profile, self.repo_root)
        except (KeyError, OSError, ValueError):
            self.store.finish(
                job_id,
                "FAILED",
                "Approved host configuration is unavailable or changed; command not started.",
            )
            return
        try:
            self.log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if (
                self.log_dir.is_symlink()
                or self.log_dir.stat().st_mode & 0o077
                or self.log_dir.resolve().is_relative_to(self.store.path.parent.resolve())
            ):
                raise OSError("Operation logs must remain private and outside the web queue mount.")
            log_path = self.log_dir / f"{uuid.UUID(job_id)}.log"
            descriptor = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=self.repo_root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    pass_fds=(lock_descriptor,),
                    start_new_session=True,
                    shell=False,
                )
        except OSError:
            self.store.finish(
                job_id, "FAILED", "Host command could not start; inspect host configuration."
            )
            return
        try:
            while True:
                try:
                    code = process.wait(timeout=self.heartbeat_seconds)
                    break
                except subprocess.TimeoutExpired:
                    self.store.heartbeat(self.worker_id, job_id)
            if code == 0:
                summary = (
                    "Refresh command exited successfully; "
                    "it may have been idle, fenced or lock-busy. "
                    "Consult the ledger for actual source and graph changes."
                    if profile.kind == "refresh_due"
                    else "Local-load command exited successfully; "
                    "inspect the protected receipt and ledger "
                    "for verified ingestion and graph status."
                )
                self.store.finish(job_id, "SUCCEEDED", summary)
            elif code < 0:
                self.store.finish(job_id, "UNKNOWN", UNCONFIRMED_SUMMARY)
            else:
                self.store.finish(
                    job_id,
                    "FAILED",
                    "Host command exited with an error; partial work may exist. "
                    "Inspect protected receipts before resubmitting.",
                )
        except Exception:
            # Never replay, terminate or expose a subprocess exception/log. An
            # inherited lock keeps a surviving command exclusive after this exit.
            self.store.finish(job_id, "UNKNOWN", UNCONFIRMED_SUMMARY)
            raise RuntimeError(UNCONFIRMED_SUMMARY) from None
        finally:
            self.store.heartbeat(self.worker_id)

    def run(self, *, once: bool = False) -> None:
        with worker_lock(self.store.path) as descriptor:
            # All startup mutation is guarded, so duplicate starts cannot steal
            # a live job or change the original worker's heartbeat.
            load_profiles(self.actions_file)
            self.store.initialize()
            self.store.abandon_running(RESTART_SUMMARY)
            self.store.heartbeat(self.worker_id)
            try:
                while not self.stop.is_set():
                    self.store.heartbeat(self.worker_id)
                    job = self.store.claim(self.worker_id)
                    if job is not None:
                        self._execute(job, descriptor)
                    if once:
                        return
                    self.stop.wait(self.poll_seconds)
            finally:
                self.store.stop_worker(self.worker_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queue-path",
        type=Path,
        default=os.environ.get(
            "JOBTOLOGY_ADMIN_QUEUE_PATH", "/var/lib/jobtology-admin/queue.sqlite3"
        ),
    )
    parser.add_argument(
        "--actions-file", type=Path, default=os.environ.get("JOBTOLOGY_ADMIN_ACTIONS_FILE")
    )
    parser.add_argument(
        "--repo-root", type=Path, default=os.environ.get("JOBTOLOGY_ADMIN_REPO_ROOT")
    )
    parser.add_argument(
        "--log-dir", type=Path, default=os.environ.get("JOBTOLOGY_ADMIN_WORKER_LOG_DIR")
    )
    parser.add_argument("--once", action="store_true", help="Process at most one queued operation.")
    arguments = parser.parse_args()
    if arguments.actions_file is None or arguments.repo_root is None:
        parser.error(
            "--actions-file and --repo-root (or matching environment variables) are required"
        )
    os.umask(0o077)
    worker = HostWorker(
        JobStore(arguments.queue_path),
        arguments.actions_file,
        arguments.repo_root,
        log_dir=arguments.log_dir,
    )

    def request_stop(_signum: int, _frame: Any) -> None:
        # Drain the current operation; disconnecting/redeploying the web app has
        # no effect on this independent host service.
        worker.stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        worker.run(once=arguments.once)
    except WorkerAlreadyRunning:
        print("Another host worker or operation is active; no job was claimed.", file=sys.stderr)
        return 75
    except Exception:
        print(
            "Host worker stopped; inspect protected configuration and queued job status.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
