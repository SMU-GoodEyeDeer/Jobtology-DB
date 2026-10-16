"""Scratch profiling must preserve the canonical JDBC reader and isolation guard."""

from __future__ import annotations

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "native_graph_costs", ROOT / "hop/operations/profile_native_graph_costs.py"
)
assert SPEC and SPEC.loader
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


@pytest.mark.parametrize("scope", profile.READERS)
def test_profile_reader_preserves_exact_jdbc_and_removes_graph_or_capture_writes(tmp_path, scope):
    pipeline, reader = profile.READERS[scope]
    source = ROOT / "hop/graph" / (pipeline + ".hpl")
    target = tmp_path / ("profile_" + scope + ".hpl")
    before = ET.parse(source).getroot()
    sql = profile.reader_only(source, target, reader)
    after = ET.parse(target).getroot()
    assert sql == before.find(f"transform[name='{reader}']/sql").text
    for name in ("Snapshot", reader):
        assert ET.tostring(before.find(f"transform[name='{name}']")) == ET.tostring(
            after.find(f"transform[name='{name}']")
        )
    assert {t.findtext("type") for t in after.findall("transform")} == {
        "GetVariable",
        "DBJoin",
        "Dummy",
    }
    assert [(hop.findtext("from"), hop.findtext("to")) for hop in after.findall("order/hop")] == [
        ("Snapshot", reader),
        (reader, "Complete"),
    ]


def test_profile_refuses_a_reader_without_exact_parameter_contract(tmp_path):
    source = tmp_path / "source.hpl"
    root = ET.parse(ROOT / "hop/graph/load_entity_names.hpl").getroot()
    root.find("transform[name='Read entity names']/sql").text = "SELECT 1"
    ET.ElementTree(root).write(source)
    with pytest.raises(ValueError, match="scope parameter"):
        profile.reader_only(source, tmp_path / "profile.hpl", "Read entity names")


def test_reader_comparison_freezes_sql_and_keeps_deployed_owner500(tmp_path, monkeypatch):
    def initialize(fixture, args):
        fixture.work = tmp_path / "work"
        fixture.work.mkdir()
        fixture.receipt = {
            "candidate_artifact_sha256": {
                "graph/" + relative: profile.native.sha(ROOT / "hop/graph" / relative)
                for relative in (
                    "sql/007_capture_guard_worksets.sql",
                    "sql/008_reader_worksets.sql",
                    "install.hwf",
                    "install_posting_dates.hwf",
                )
            }
        }
        fixture.args = args

    monkeypatch.setattr(profile.borrowed.BorrowedFixture, "__init__", initialize)
    candidates = []
    for name in ("007_capture_guard_worksets.sql", "008_reader_worksets.sql"):
        path = tmp_path / name
        path.write_text("-- exact launch " + name)
        candidates.append(path)
    args = SimpleNamespace(
        reader_sql_candidate=candidates,
        compatibility_only=False,
        transport_candidate=[],
        await_transport_candidate=None,
        transport_baseline=None,
        source_sql=None,
    )
    fixture = profile.GraphCostFixture(args)
    assert profile.native.sha(args.source_sql) == (
        "728e103f4b0df3af12ae4b2cc6f52f5d2ebf6d320163ae6daa37b35e0c627c31"
    )
    assert fixture.baseline_pipelines == fixture.candidate_pipelines
    assert fixture.receipt["reader_comparison"]["owner_transport_exactly_equal"]
    for original, frozen in zip(candidates, fixture.reader_candidates, strict=True):
        assert original.read_bytes() == frozen.read_bytes()
        assert frozen.stat().st_mode & 0o222 == 0
        original.write_text("-- later edit")
        assert original.read_bytes() != frozen.read_bytes()
    project = fixture.work / "project/graph"
    project.mkdir(parents=True)
    applied = []
    monkeypatch.setattr(fixture, "apply_variant", applied.append)
    fixture.transport("baseline")
    before = {name: (project / (name + ".hpl")).read_bytes() for name in fixture.baseline_pipelines}
    fixture.transport("candidate")
    assert applied == ["baseline", "candidate"]
    assert before == {
        name: (project / (name + ".hpl")).read_bytes() for name in fixture.baseline_pipelines
    }


def test_reader_comparison_refuses_noncanonical_sql006(tmp_path, monkeypatch):
    def initialize(fixture, args):
        fixture.work = tmp_path
        fixture.receipt = {}
        fixture.args = args

    monkeypatch.setattr(profile.borrowed.BorrowedFixture, "__init__", initialize)
    changed = tmp_path / "006.sql"
    changed.write_text("-- changed baseline")
    args = SimpleNamespace(reader_sql_candidate=[tmp_path / "008.sql"], source_sql=changed)
    with pytest.raises(ValueError, match="canonical frozen SQL006"):
        profile.GraphCostFixture(args)


@pytest.mark.parametrize("variant", ["baseline", "candidate"])
def test_reader_variant_restores_original_guard_and_applies_only_candidate_addons(
    tmp_path, monkeypatch, variant
):
    fixture = object.__new__(profile.GraphCostFixture)
    fixture.work = tmp_path
    fixture.reader_sql_mode = True
    fixture.receipt = {}
    fixture.variant_definitions = {}
    fixture.baseline_insert_guard = "-- original guard"
    staged = tmp_path / "project/graph/sql"
    staged.mkdir(parents=True)
    source006 = ROOT / "hop/graph/sql/006_jobalio_validation_worksets.sql"
    (staged / source006.name).write_bytes(source006.read_bytes())
    fixture.args = SimpleNamespace(source_sql=source006)
    fixture.reader_candidates = []
    for name in ("007_capture_guard_worksets.sql", "008_reader_worksets.sql"):
        frozen = tmp_path / ("launched-reader-" + name)
        frozen.write_text("-- exact " + name)
        (staged / name).write_bytes(frozen.read_bytes())
        fixture.reader_candidates.append(frozen)
    calls = []
    monkeypatch.setattr(
        profile.borrowed.BorrowedFixture,
        "apply_variant",
        lambda fixture, name: calls.append(("super", name)),
    )
    monkeypatch.setattr(fixture, "sql", lambda query, label: calls.append((query, label)))
    monkeypatch.setattr(fixture, "definitions", lambda label: [{"definition": variant}])
    fixture.apply_variant(variant)
    assert calls[0] == ("super", "candidate")
    assert calls[1][0] == "-- original guard"
    addon_calls = [query for query, _ in calls if query.startswith("-- exact ")]
    assert addon_calls == (
        []
        if variant == "baseline"
        else ["-- exact 007_capture_guard_worksets.sql", "-- exact 008_reader_worksets.sql"]
    )
    definitions = tmp_path / (variant + "-reader-functions.json")
    assert fixture.receipt["reader_variant_definition_sha256"][variant] == profile.native.sha(
        definitions
    )


@pytest.mark.parametrize("tamper", [False, True])
def test_continuation_freezes_explicit_hash_lock_and_immutable_profile(
    tmp_path, monkeypatch, tamper
):
    directory = tmp_path / "continuation"
    directory.mkdir()
    fixture = object.__new__(profile.GraphCostFixture)
    fixture.work = tmp_path / "private"
    fixture.work.mkdir()
    fixture.receipt = {"candidate_artifact_sha256": {}, "samples": [{"variant": "baseline"}]}
    fixture.candidate_pipelines = {}

    def supply(_seconds):
        hashes = {}
        for name in ("clear_source_edges", "verify_totals"):
            root = ET.parse(ROOT / "hop/graph" / (name + ".hpl")).getroot()
            output = root.find("transform[type='Neo4jCypherOutput']")
            output.find("batch_size").text = "500"
            output.find("unwind").text = "Y"
            ET.SubElement(output, "unwind_map").text = "rows"
            path = directory / (name + ".hpl")
            ET.ElementTree(root).write(path)
            hashes[path.name] = profile.native.sha(path)
            if tamper:
                path.write_bytes(path.read_bytes() + b"\n<!-- changed -->")
        (directory / "ready.json").write_text(json.dumps(hashes))

    monkeypatch.setattr(profile.time, "sleep", supply)
    if tamper:
        with pytest.raises(RuntimeError, match="hash lock"):
            fixture.await_transport_candidate(directory)
    else:
        fixture.await_transport_candidate(directory)
        assert set(fixture.candidate_pipelines) == {"clear_source_edges", "verify_totals"}
        fixture.receipt["samples"].append({"variant": "candidate"})
        assert (
            len(json.loads((fixture.work / "profile-phase-receipt.json").read_text())["samples"])
            == 1
        )
        assert (fixture.work / "launched-transport-manifest.json").stat().st_mode & 0o222 == 0
        assert fixture.receipt["continuation"]["status"] == "FROZEN_HASH_LOCKED"
    assert (fixture.work / "profile-phase-receipt.json").stat().st_mode & 0o222 == 0


def test_entity_comparison_preserves_sql008_and_freezes_only_sql009(tmp_path, monkeypatch):
    def initialize(fixture, args):
        fixture.work = tmp_path / "work"
        fixture.work.mkdir()
        fixture.receipt = {
            "candidate_artifact_sha256": {
                "graph/" + relative: profile.native.sha(ROOT / "hop/graph" / relative)
                for relative in (
                    "sql/007_capture_guard_worksets.sql",
                    "sql/008_reader_worksets.sql",
                    "install.hwf",
                    "install_posting_dates.hwf",
                )
            }
        }
        fixture.args = args
        fixture.variant_definitions = {}

    monkeypatch.setattr(profile.borrowed.BorrowedFixture, "__init__", initialize)
    candidate = tmp_path / "009_reader_fact_worksets.sql"
    candidate.write_text("-- frozen additive entity candidate")
    args = SimpleNamespace(
        entity_reader_sql_candidate=candidate,
        reader_sql_candidate=[],
        source_sql=None,
        compatibility_only=False,
        transport_candidate=[],
        await_transport_candidate=None,
        transport_baseline=None,
    )
    fixture = profile.GraphCostFixture(args)
    assert fixture.baseline_pipelines == fixture.candidate_pipelines
    assert fixture.receipt["reader_comparison"]["baseline"] == "Deployed SQL007/008 and owner500"
    assert "posting_facts" not in fixture.baseline_entity_definition
    assert "nara_facts AS MATERIALIZED" in fixture.baseline_entity_definition
    staged = fixture.work / "project/graph/sql"
    staged.mkdir(parents=True)
    (staged / candidate.name).write_bytes(candidate.read_bytes())
    candidate.write_text("-- edited after launch")
    calls = []
    monkeypatch.setattr(fixture, "sql", lambda query, label: calls.append((query, label)))
    monkeypatch.setattr(fixture, "definitions", lambda label: [{"definition": label}])
    fixture.apply_variant("baseline")
    assert calls[0][0] == fixture.baseline_entity_definition
    assert len(calls) == 2
    calls.clear()
    fixture.apply_variant("candidate")
    assert calls[0][0] == fixture.baseline_entity_definition
    assert calls[1][0] == "-- frozen additive entity candidate"
    assert len(calls) == 3
    (staged / candidate.name).write_text("-- changed staged candidate")
    with pytest.raises(RuntimeError, match="Staged SQL009 differs"):
        fixture.apply_variant("candidate")
