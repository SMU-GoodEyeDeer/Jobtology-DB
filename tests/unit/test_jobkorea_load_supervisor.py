"""Verify immutable archives and graph-check scope before native production work."""

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def supervisor(monkeypatch: pytest.MonkeyPatch) -> Any:
    directory = Path(__file__).resolve().parents[2] / "hop/operations"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "jobkorea_load_supervisor_test", directory / "load_jobkorea_dataset.py"
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def archive(supervisor: Any, tmp_path: Path) -> Path:
    (tmp_path / "originals").mkdir()
    original = tmp_path / "originals/first.ndjson"
    original.write_bytes(b'{"observation":1}\n')
    (tmp_path / "snapshot.ndjson").write_bytes(original.read_bytes())
    (tmp_path / "occurrences.ndjson").write_bytes(b'{"composed_line":1}\n')
    identity = supervisor.file_identity(original)
    descriptor = {
        "selected_count": 1,
        "source_inventory": [
            {
                "file": "first.ndjson",
                "sha256": identity["sha256"],
                "bytes": identity["byte_length"],
            }
        ],
    }
    (tmp_path / "composition.json").write_text(json.dumps(descriptor) + "\n")
    provenance = {"contract": "jobkorea-dataset-provenance-v1", "selected_count": 1}
    for name, prefix in (
        ("snapshot.ndjson", "snapshot"),
        ("occurrences.ndjson", "occurrences"),
        ("composition.json", "descriptor"),
    ):
        identity = supervisor.file_identity(tmp_path / name)
        provenance[prefix + "_sha256"] = identity["sha256"]
        provenance[prefix + "_byte_length"] = identity["byte_length"]
    provenance["archive_relative_root"] = "jobkorea/datasets/" + provenance["descriptor_sha256"]
    (tmp_path / "provenance.json").write_text(json.dumps(provenance) + "\n")
    return tmp_path


def test_archive_original_changes_rejected_before_runtime_access(
    supervisor: Any, archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (archive / "originals/first.ndjson").write_bytes(b"altered evidence\n")
    accesses = []
    monkeypatch.setattr(supervisor.common, "containers", lambda: accesses.append("runtime"))
    with pytest.raises(RuntimeError, match="Archived original file changed"):
        supervisor.load(Path("unused-manifest"), archive, archive / "unused-work")
    assert accesses == []


def test_archive_symlinks_and_extra_files_are_rejected(supervisor: Any, archive: Path) -> None:
    (archive / "unreviewed.json").write_bytes(b"extra bytes")
    with pytest.raises(RuntimeError, match="file inventory changed"):
        supervisor.composition_identity(archive)
    (archive / "unreviewed.json").unlink()
    (archive / "leaked-link").symlink_to(archive / "snapshot.ndjson")
    with pytest.raises(RuntimeError, match="symlinks are forbidden"):
        supervisor.composition_identity(archive)


def test_existing_archive_drift_is_not_overwritten(
    supervisor: Any, archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provenance, inventory = supervisor.composition_identity(archive)
    altered = {**inventory, "snapshot.ndjson": {"sha256": "changed", "byte_length": 18}}
    monkeypatch.setattr(supervisor, "remote_inventory", lambda *_: altered)
    calls = []
    monkeypatch.setattr(supervisor.common, "command", lambda args, **_: calls.append(args))
    with pytest.raises(RuntimeError, match="immutable composition archive differs"):
        supervisor.archive_composition("hop", archive, provenance, inventory)
    assert calls == []


def test_graph_wrapper_runs_only_existing_read_only_verifier_and_cleans_temp(
    supervisor: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(supervisor.common, "command", lambda args, **_: calls.append(args))
    native_calls = []

    def native(*args: Any, **kwargs: Any) -> Path:
        native_calls.append((args, kwargs))
        return tmp_path / "read-graph.log"

    monkeypatch.setattr(supervisor, "native", native)
    supervisor.verify_graph("hop", ["exact-run-one", "exact-run-two"], tmp_path, "read-graph")
    root = ET.parse(tmp_path / "read-graph.hwf").getroot()
    pipelines = root.findall("./actions/action[type='PIPELINE']")
    assert len(pipelines) == 2
    assert all(
        node.findtext("filename") == "${PROJECT_HOME}/graph/verify_totals.hpl" for node in pipelines
    )
    assert [node.findtext("./parameters/parameter/value") for node in pipelines] == [
        "exact-run-one",
        "exact-run-two",
    ]
    assert native_calls[0][1]["configuration"] == "graph-local"
    assert calls[-1][:2] == ["docker", "exec"] and "rm" in calls[-1]
    assert calls[-1][-1].startswith("/tmp/jobkorea-read-graph-")
    verifier = ET.parse(supervisor.deployment.ROOT / "graph/verify_totals.hpl")
    assert verifier.findtext(".//transform[type='Neo4jCypherOutput']/read_only") == "Y"
