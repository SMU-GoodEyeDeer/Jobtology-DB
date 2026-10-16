"""An archived reader qualification must keep scope, exact IDs and bounded isolation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hop/operations"))
SPEC = importlib.util.spec_from_file_location(
    "entity_reader_benchmark", ROOT / "hop/operations/benchmark_entity_readers.py"
)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.mark.parametrize("delimiter", ["$$", "$function$"])
def test_raw_diagnostic_preserves_complete_return_query(delimiter):
    definition = (
        "CREATE FUNCTION f() RETURNS SETOF text LANGUAGE plpgsql AS "
        + delimiter
        + "\nBEGIN\nPERFORM guard();\nRETURN QUERY\nSELECT 'jobs';\nEND "
        + delimiter
        + ";"
    )
    assert benchmark.raw_query(definition) == "SELECT 'jobs'"


def test_complete_result_query_keeps_duplicates_types_and_order():
    query = benchmark.typed_query("graph_source_entities", "exact'run")
    assert "jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text)" in query
    assert "DISTINCT" not in query
    assert "ingestion.graph_source_entities('exact''run')" in query
    assert benchmark.READERS == ("graph_source_entities", "graph_source_edge_owners")


@pytest.mark.parametrize("change", ["id", "volume", "network", "cpus", "memory"])
def test_fixture_guard_refuses_changed_actual_resource(monkeypatch, change):
    preflight = dict(
        status="READY",
        container_id="sealed-id",
        owned_volumes=["sealed-volume"],
        container="jobtology-routine-archive-nara-abcd",
    )
    actual = dict(
        Id="sealed-id",
        Name="/" + preflight["container"],
        HostConfig=dict(NetworkMode="none", NanoCpus=4_000_000_000, Memory=6_442_450_944),
        NetworkSettings=dict(Networks={"none": {}}),
        Mounts=[dict(Type="volume", Name="sealed-volume")],
    )
    if change == "id":
        actual["Id"] = "replacement-id"
    elif change == "volume":
        actual["Mounts"][0]["Name"] = "replacement-volume"
    elif change == "network":
        actual["NetworkSettings"]["Networks"] = {"default": {}}
    elif change == "cpus":
        actual["HostConfig"]["NanoCpus"] = 0
    else:
        actual["HostConfig"]["Memory"] = 0
    monkeypatch.setattr(
        benchmark.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(actual)),
    )
    with pytest.raises(ValueError, match="Exact leased clone"):
        benchmark.inspect_fixture(preflight)
