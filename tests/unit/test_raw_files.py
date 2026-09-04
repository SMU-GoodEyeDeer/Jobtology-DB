from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from jobtology_db.storage.raw_files import RawFileStore, RawObjectIntegrityError


def expected_relative_path(content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    return Path("raw") / "sha256" / digest[:2] / digest[2:4] / digest


def test_put_writes_exact_bytes_to_content_addressed_path(tmp_path: Path) -> None:
    content = "한글 raw response\n".encode()
    store = RawFileStore(tmp_path)

    stored = store.put(content)

    expected_path = expected_relative_path(content)
    assert stored.relative_path == expected_path
    assert stored.content_sha256 == hashlib.sha256(content).hexdigest()
    assert stored.byte_length == len(content)
    assert (tmp_path / expected_path).read_bytes() == content
    assert (tmp_path / expected_path).stat().st_mode & 0o777 == 0o600


def test_put_deduplicates_identical_content(tmp_path: Path) -> None:
    content = b'{"same":"response"}'
    store = RawFileStore(tmp_path)

    first = store.put(content)
    target = tmp_path / first.relative_path
    first_inode = target.stat().st_ino
    second = store.put(content)

    assert second == first
    assert target.stat().st_ino == first_inode
    assert list((tmp_path / "raw" / "sha256").rglob(first.content_sha256)) == [target]


def test_put_uses_distinct_objects_for_distinct_bytes(tmp_path: Path) -> None:
    store = RawFileStore(tmp_path)

    first = store.put(b"first")
    second = store.put(b"second")

    assert first.content_sha256 != second.content_sha256
    assert first.relative_path != second.relative_path
    assert (tmp_path / first.relative_path).read_bytes() == b"first"
    assert (tmp_path / second.relative_path).read_bytes() == b"second"


def test_concurrent_identical_puts_converge_on_one_object(tmp_path: Path) -> None:
    content = b"concurrent immutable payload" * 1_024
    store = RawFileStore(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        stored_objects = list(executor.map(store.put, [content] * 24))

    assert len({item.content_sha256 for item in stored_objects}) == 1
    assert len({item.relative_path for item in stored_objects}) == 1
    target = tmp_path / stored_objects[0].relative_path
    assert target.read_bytes() == content
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "corrupt_content",
    [
        b"short",
        b"x" * len(b"expected payload"),
    ],
)
def test_put_rejects_existing_object_with_invalid_content(
    tmp_path: Path, corrupt_content: bytes
) -> None:
    content = b"expected payload"
    relative_path = expected_relative_path(content)
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(corrupt_content)
    store = RawFileStore(tmp_path)

    with pytest.raises(RawObjectIntegrityError):
        store.put(content)

    assert target.read_bytes() == corrupt_content


def test_failed_link_removes_temporary_file_and_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"do not partially publish"
    store = RawFileStore(tmp_path)

    def fail_link(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        del source, destination
        raise OSError("simulated link failure")

    monkeypatch.setattr(os, "link", fail_link)

    with pytest.raises(OSError, match="simulated link failure"):
        store.put(content)

    target = tmp_path / expected_relative_path(content)
    assert not target.exists()
    assert not list(target.parent.glob("*.tmp"))
