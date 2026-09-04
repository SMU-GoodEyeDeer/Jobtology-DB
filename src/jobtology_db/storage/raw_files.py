from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from jobtology_db.contracts.fetch import StoredRawObject


class RawObjectIntegrityError(RuntimeError):
    pass


class RawStorageCapacityError(RuntimeError):
    pass


class RawFileStore:
    """Write-once, content-addressed storage for raw HTTP entity bytes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def ensure_capacity(
        self,
        *,
        incoming_limit_bytes: int,
        min_free_bytes: int,
        max_used_fraction: float,
    ) -> None:
        probe = self.root
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        usage = shutil.disk_usage(probe)
        used_fraction = usage.used / usage.total if usage.total else 1.0
        if used_fraction >= max_used_fraction:
            raise RawStorageCapacityError("Raw-store filesystem is above its usage threshold")
        if usage.free - incoming_limit_bytes < min_free_bytes:
            raise RawStorageCapacityError("Raw-store filesystem is below its free-space reserve")

    def put(self, content: bytes) -> StoredRawObject:
        digest = hashlib.sha256(content).hexdigest()
        relative = Path("raw") / "sha256" / digest[:2] / digest[2:4] / digest
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        if target.exists():
            self._verify_existing(target, digest, len(content))
            return StoredRawObject(
                content_sha256=digest,
                byte_length=len(content),
                relative_path=relative,
            )

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

            try:
                os.link(temporary, target)
            except FileExistsError:
                self._verify_existing(target, digest, len(content))
            finally:
                temporary.unlink(missing_ok=True)

            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        return StoredRawObject(
            content_sha256=digest,
            byte_length=len(content),
            relative_path=relative,
        )

    @staticmethod
    def _verify_existing(path: Path, expected_digest: str, expected_length: int) -> None:
        stat = path.stat()
        if stat.st_size != expected_length:
            raise RawObjectIntegrityError(f"Existing raw object has wrong length: {path}")
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise RawObjectIntegrityError(f"Existing raw object has wrong digest: {path}")
