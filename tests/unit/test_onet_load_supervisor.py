"""Independent catalogue-only deployment boundary and evidence integrity checks."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("onet_supervisor", OPS / "load_onet_catalogue.py")
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def frame(*values: str) -> str:
    return "".join(str(len(value)) + ":" + value for value in values)


def props(**values: str) -> str:
    return "".join(frame(key, "STRING NOT NULL", value) for key, value in sorted(values.items()))


def node(eid: str, identifier: str, owner: str | None = None, labels: str = "entity") -> list[str]:
    values = dict(id=identifier, title="한글\nquoted title")
    if owner is not None:
        values["managed_by"] = owner
        values["scheme_id"] = "ONET"
        values["release_id"] = "onet-fixture"
        values["kind"] = "conceptScheme" if identifier.endswith(":scheme") else "occupation"
        values["code"] = "ONET" if identifier.endswith(":scheme") else identifier.split(":")[-1]
        properties = props(**values) + frame("current", "BOOLEAN NOT NULL", "true")
        return [eid, frame(*labels.split("|")), properties]
    return [eid, frame(*labels.split("|")), props(**values)]


def archive(path: Path, rows: list[tuple[str, list[str]]]) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,"
                           "PRIMARY KEY(kind,eid))")
        connection.executemany("INSERT INTO snapshot VALUES(?,?,?)",
                               [(kind, row[0], frame(*row)) for kind, row in rows])
    return path


def legacy() -> list[tuple[str, list[str]]]:
    return [("NODE", node("legacy", "urn:jobtology:ncs:01"))]


def owned() -> list[tuple[str, list[str]]]:
    return [("NODE", node("scheme", ops.PREFIX + "scheme", ops.OWNER,
                          "entity|onetCatalogObject|conceptScheme")),
            ("NODE", node("occupation", ops.PREFIX + "occupation:11-1011.00", ops.OWNER,
                          "entity|onetCatalogObject|occupation")),
            ("REL", ["membership", "occupation", "scheme", "IN_SCHEME",
                     props(id=ops.PREFIX + "relationship:" + "a" * 64,
                           managed_by=ops.OWNER, scheme_id="ONET", release_id="onet-fixture")
                     + frame("current", "BOOLEAN NOT NULL", "true")])]


def test_legacy_graph_preservation_and_additive_catalogue(tmp_path):
    before = archive(tmp_path / "before.sqlite", legacy())
    after = archive(tmp_path / "after.sqlite", legacy() + owned())
    assert ops.require_graph_preserved(before, after) == dict(
        legacy_nodes=1, legacy_edges=0, onet_nodes=2, onet_edges=1)


@pytest.mark.parametrize("drift", ("labels", "typed-property", "removed"))
def test_complete_legacy_graph_values_are_strict(tmp_path, drift):
    before = archive(tmp_path / "before.sqlite", legacy())
    rows = legacy() + owned()
    if drift == "labels":
        rows[0][1][1] = frame("entity", "newLabel")
    elif drift == "typed-property":
        rows[0][1][-1] = frame("id", "STRING NOT NULL", "urn:jobtology:ncs:01",
                                  "title", "INTEGER NOT NULL", "1")
    else:
        rows.pop(0)
    with pytest.raises(RuntimeError, match="legacy graph object"):
        ops.require_graph_preserved(before, archive(tmp_path / "after.sqlite", rows))


@pytest.mark.parametrize("kind", ("foreign-owner", "external-link", "revision", "matching"))
def test_catalogue_cannot_escape_namespace_or_stop_boundary(tmp_path, kind):
    before = archive(tmp_path / "before.sqlite", legacy())
    rows = legacy() + owned()
    if kind == "foreign-owner":
        rows[1][1][-1] = props(id=ops.PREFIX + "scheme", managed_by="foreign")
    elif kind == "external-link":
        rows[-1][1][1] = "legacy"
    elif kind == "revision":
        rows[1][1][1] = frame("ontologyObject", "entityRevision")
    else:
        rows[1][1][-1] += frame("confidence", "FLOAT NOT NULL", "0.9")
    with pytest.raises(RuntimeError):
        ops.require_graph_preserved(before, archive(tmp_path / "after.sqlite", rows))


def test_reserved_foreign_identity_is_refused_even_when_it_preexisted(tmp_path):
    rows = [("NODE", node("foreign", ops.PREFIX + "scheme"))]
    with pytest.raises(RuntimeError, match="Foreign"):
        ops.require_graph_preserved(archive(tmp_path / "before.sqlite", rows),
                                   archive(tmp_path / "after.sqlite", rows))


def test_owned_rollover_can_change_only_owned_objects(tmp_path):
    rows = legacy() + owned()
    before = archive(tmp_path / "before.sqlite", rows)
    rows[2][1][-1] += frame("status", "STRING NOT NULL", "RETIRED")
    after = archive(tmp_path / "after.sqlite", rows)
    assert ops.require_graph_preserved(before, after)["legacy_nodes"] == 1


def bundle(folder: Path):
    (folder / "sources").mkdir()
    (folder / "sources/occupation_data.json").write_text("[]\n")
    (folder / "catalogue.json").write_text('{"release_id":"onet-test"}\n')
    descriptor = dict(contract_version="hop-onet-bundle-v1", release_id="onet-test",
                      catalogue_file="catalogue.json", sources=[])
    descriptor.update({"catalogue_" + key: value for key, value in
                       ops.identity(folder / "catalogue.json").items()})
    descriptor["sources"].append(dict(archive_path="sources/occupation_data.json",
                                      **ops.identity(folder / "sources/occupation_data.json")))
    (folder / "descriptor.json").write_text(json.dumps(descriptor))
    return descriptor


@pytest.mark.parametrize("tamper", ("catalogue", "extra-file", "symlink", "traversal"))
def test_archive_byte_identity_and_inventory_are_required(tmp_path, tamper):
    descriptor = bundle(tmp_path)
    ops.bundle_identity(tmp_path)
    if tamper == "catalogue":
        (tmp_path / "catalogue.json").write_text('{"release_id":"other"}')
    elif tamper == "extra-file":
        (tmp_path / "unexpected.txt").write_text("extra")
    elif tamper == "symlink":
        (tmp_path / "link").symlink_to("catalogue.json")
    else:
        descriptor["sources"][0]["archive_path"] = "sources/../catalogue.json"
        (tmp_path / "descriptor.json").write_text(json.dumps(descriptor))
    with pytest.raises(RuntimeError):
        ops.bundle_identity(tmp_path)


def test_native_proof_binds_exact_runtime_payload_and_cleanup(tmp_path):
    path = tmp_path / "receipt.json"
    value = dict(status="PASSED_ONET_NATIVE_CATALOGUE", isolated=True,
                 disposable_resources_removed=True, private_scratch_removed=True,
                 artifact_sha256={"install": "hash"}, official_catalogue_sha256="payload",
                 checks=["native"])
    path.write_text(json.dumps(value))
    descriptor = {"catalogue_sha256": "payload"}
    ops.qualification(path, {"install": "hash"}, descriptor)
    for key in ("disposable_resources_removed", "private_scratch_removed", "isolated"):
        path.write_text(json.dumps({**value, key: False}))
        with pytest.raises(RuntimeError):
            ops.qualification(path, {"install": "hash"}, descriptor)
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="exact public runtime"):
        ops.qualification(path, {"install": "new"}, descriptor)
    with pytest.raises(RuntimeError, match="exact official payload"):
        ops.qualification(path, {"install": "hash"}, {"catalogue_sha256": "new"})


@pytest.mark.parametrize("drift", (None, "property-type", "endpoint", "missing", "extra"))
def test_independent_complete_pg_inventory_matches_typed_graph(tmp_path, monkeypatch, drift):
    rows = owned()
    snapshot = archive(tmp_path / "graph.sqlite", rows)
    expected = {"graph_load_node": [], "graph_load_edge": []}
    for kind, row in rows:
        properties = {name: (value[1] == "true" if value[0] == "BOOLEAN NOT NULL" else value[1])
                      for name, value in ops.graph.properties(row[-1]).items()}
        if kind == "NODE":
            expected["graph_load_node"].append(dict(node_id=properties["id"],
                labels=ops.graph.unpack(row[1]), properties=properties))
        else:
            expected["graph_load_edge"].append(dict(edge_id=properties["id"],
                start_id=ops.PREFIX + "occupation:11-1011.00", end_id=ops.PREFIX + "scheme",
                edge_type="IN_SCHEME", properties=properties))
    if drift == "property-type":
        expected["graph_load_node"][0]["properties"]["current"] = "true"
    elif drift == "endpoint":
        expected["graph_load_edge"][0]["end_id"] = ops.PREFIX + "occupation:11-1011.00"
    elif drift == "missing":
        expected["graph_load_node"][0]["node_id"] = ops.PREFIX + "group:11-0000"
    elif drift == "extra":
        expected["graph_load_edge"].clear()

    def inventory(pg, query, output):
        assert pg == "fixture" and "'load-id'" in query
        return ((row, json.dumps(row)) for row in
                expected["graph_load_node" if "graph_load_node" in query else "graph_load_edge"])

    monkeypatch.setattr(ops.typed, "copy_inventory", inventory)
    if drift:
        with pytest.raises(RuntimeError):
            ops.verify_expected_graph("fixture", snapshot, "load-id", tmp_path)
    else:
        assert ops.verify_expected_graph("fixture", snapshot, "load-id", tmp_path) == dict(
            nodes=2, edges=1)


def test_private_scalar_grid_clears_inherited_unwind_and_restores_builder(tmp_path):
    original = ops.graph.dates.build_snapshot
    path = tmp_path / "snapshot.hpl"
    with pytest.raises(RuntimeError, match="scope"), ops.scalar_snapshot_adapter():
        ops.graph.dates.build_snapshot(path, "RETURN $bounds AS signature", "/tmp/private")
        ops.graph.configure_grid(path, "bounds", ["first", "second"])
        neo = ET.parse(path).getroot().find("transform[type='Neo4jCypherOutput']")
        assert neo is not None
        assert neo.findtext("unwind") == "N" and neo.findtext("read_only") == "Y"
        assert neo.findtext("batch_size") == "1" and neo.findtext("cypher_from_field") == "N"
        assert neo.findtext("mappings/mapping/parameter") == "bounds"
        assert neo.findtext("unwind_map") in (None, "")
        raise RuntimeError("scope")
    assert ops.graph.dates.build_snapshot is original


def prewrite_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "STATE", tmp_path)
    runtime = dict(hop="fixture-hop", pg="fixture-pg")
    descriptor, inventory, public, bound = {"release": "pin"}, {"raw": "sha"}, {"new": "sha"}, {
        "proof": "exact"}
    previous = dict(kind=ops.KIND, status="FAILED_FENCED", installed=[],
        scheduler_fence_removed=False, source_requests=0, provider_calls=0,
        posting_matching_calls=0, token="token", containers=runtime,
        before={"all157": "exact"}, legacy_runtime_before="frozen", bundle_descriptor=descriptor,
        bundle_inventory=inventory, artifact_sha256=public, isolated_proof=bound)
    folder = tmp_path / "failed"
    folder.mkdir()
    path = folder / "receipt.json"
    path.write_text(json.dumps(previous))
    fence = tmp_path / ops.performance.FENCE_NAME
    fence.write_text(json.dumps(dict(kind=ops.KIND, token="token", receipt=str(path))))
    monkeypatch.setattr(ops, "legacy_runtime", lambda hop: "frozen")
    monkeypatch.setattr(ops, "remote_bytes", lambda hop, name: None)
    monkeypatch.setattr(ops.deployment, "sql", lambda pg, statement: "t")
    return path, fence, previous, (runtime, descriptor, inventory, public, bound)


def test_prewrite_resume_preserves_failed_bytes_and_carries_baseline_once(tmp_path, monkeypatch):
    path, fence, previous, arguments = prewrite_state(tmp_path, monkeypatch)
    failed_bytes, fence_bytes = path.read_bytes(), fence.read_bytes()
    directory, output, receipt = ops.prewrite_resume(path, *arguments)
    assert path.read_bytes() == failed_bytes and receipt["before"] == previous["before"]
    assert (directory / "fence-before.json").read_bytes() == fence_bytes
    assert receipt["prewrite_resume"]["sha256"] == ops.identity(path)["sha256"]
    assert receipt["prewrite_resume"]["retained_postgres_baseline"] is True
    assert json.loads(fence.read_text()) == dict(kind=ops.KIND, token="token", receipt=str(output))


@pytest.mark.parametrize("mutation", ("installed", "backup", "archive", "snapshot", "schema",
    "runtime", "legacy", "fence", "bundle", "proof", "native-log", "paid", "released"))
def test_prewrite_resume_refuses_intervening_or_attempted_mutation(tmp_path, monkeypatch, mutation):
    path, fence, previous, arguments = prewrite_state(tmp_path, monkeypatch)
    if mutation == "installed":
        previous["installed"] = ["new"]
    elif mutation in ("backup", "archive", "snapshot"):
        previous[{"backup": "database_backup", "archive": "archive_root",
                  "snapshot": "graph_before"}[mutation]] = "attempted"
    elif mutation == "schema":
        monkeypatch.setattr(ops.deployment, "sql", lambda pg, statement: "f")
    elif mutation == "runtime":
        monkeypatch.setattr(ops, "remote_bytes", lambda hop, name: b"attempted")
    elif mutation == "legacy":
        monkeypatch.setattr(ops, "legacy_runtime", lambda hop: "changed")
    elif mutation == "fence":
        fence.write_text(json.dumps(dict(kind=ops.KIND, token="foreign", receipt=str(path))))
    elif mutation in ("bundle", "proof"):
        previous["bundle_inventory" if mutation == "bundle" else "isolated_proof"] = {"changed": 1}
    elif mutation == "native-log":
        (path.parent / "native-install.log").write_text("attempted")
    elif mutation == "paid":
        previous["provider_calls"] = 1
    else:
        previous["scheduler_fence_removed"] = True
    path.write_text(json.dumps(previous))
    failed_bytes, fence_bytes = path.read_bytes(), fence.read_bytes()
    with pytest.raises(RuntimeError):
        ops.prewrite_resume(path, *arguments)
    assert path.read_bytes() == failed_bytes and fence.read_bytes() == fence_bytes


def pregraph_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "STATE", tmp_path)
    folder = tmp_path / "failed"
    folder.mkdir()
    backup = folder / "database-before.dump"
    backup.write_bytes(b"retained backup")
    graph_path = archive(folder / "graph-before.sqlite", [])
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "catalogue.json").write_text(json.dumps({"release_id": "root-pin"}))
    runtime, descriptor = dict(hop="fixture-hop", pg="fixture-pg"), {"release_id": "root-pin"}
    inventory = {"descriptor.json": {"sha256": "descriptor-pin"}}
    old = dict.fromkeys([*ops.SUCCESSOR_PREFLIGHTS, "ingestions/onet/sql/001_catalog.sql"], "old")
    public = {name: "new" if name in ops.SUCCESSOR_PREFLIGHTS else value
              for name, value in old.items()}
    bound = {"path": "new-proof", "sha256": "new", "checks": sorted(ops.RECOVERY_CHECKS)}
    prior = {"path": "old-proof", "sha256": "old"}
    load = dict(state="FAILED", release_id="root-pin", previous_load_id=None,
                load_id="owned-load", manifest_hash="manifest", database_id="db-id")
    stopped_pg = dict(loads=[load], current=0, targets=0, writers=0, activations=0)
    stop = dict(runtime_idle=True, graph_counts=["0|0"], pg=stopped_pg)
    stopped = tmp_path / "stopped.json"
    stopped.write_text(json.dumps(stop))
    previous = dict(kind=ops.KIND, status="FAILED_FENCED", token="token", containers=runtime,
        installed=list(old), scheduler_fence_removed=False, source_requests=0,
        provider_calls=0, posting_matching_calls=0, bundle_descriptor=descriptor,
        bundle_inventory=inventory, artifact_sha256=old, isolated_proof=prior,
        before={"157-tables": "frozen"}, legacy_runtime_before="frozen-runtime",
        graph_before=dict(path=str(graph_path)),
        database_backup=dict(path=str(backup), listing_validated=True, **ops.identity(backup)),
        archive_root=ops.PROJECT + "/data/onet-raw/descriptor-pin", failure_type="old-error")
    path = folder / "receipt.json"
    path.write_text(json.dumps(previous))
    fence = tmp_path / ops.performance.FENCE_NAME
    fence.write_text(json.dumps(dict(kind=ops.KIND, token="token", receipt=str(path))))
    monkeypatch.setattr(ops, "qualification", lambda path, public, descriptor: prior)
    monkeypatch.setattr(ops, "legacy_runtime", lambda hop: "frozen-runtime")
    monkeypatch.setattr(ops, "remote_bytes", lambda hop, name: b"old-bytes")
    monkeypatch.setattr(ops.common, "digest", lambda data: "old")
    monkeypatch.setattr(ops.graph, "validate_archive", lambda metadata: graph_path)
    monkeypatch.setattr(ops.loader, "remote_inventory", lambda hop, folder: inventory)
    monkeypatch.setattr(ops.additive, "sql", lambda *args: json.dumps(
        {**stopped_pg, "release_matches": True}))
    monkeypatch.setattr(ops.graph, "native_rows", lambda *args, **kwargs: ["db-id|0|0"])
    arguments = (stopped, bundle_path, runtime, descriptor, inventory, public, bound)
    return path, fence, previous, stop, arguments


def test_pregraph_successor_retains_backup_baselines_and_failed_bytes(tmp_path, monkeypatch):
    path, fence, previous, stop, arguments = pregraph_state(tmp_path, monkeypatch)
    original = path.read_bytes()
    _, output, result = ops.pregraph_resume(path, *arguments)
    assert path.read_bytes() == original and "failure_type" not in result
    for key in ("before", "graph_before", "database_backup", "archive_root"):
        assert result[key] == previous[key]
    assert result["pregraph_resume"]["owned_failed_load"] == stop["pg"]["loads"][0]["load_id"]
    assert set(result["pregraph_resume"]["changed_artifacts"]) == ops.SUCCESSOR_PREFLIGHTS
    assert result["isolated_proof"] == arguments[-1]
    assert json.loads(fence.read_text())["receipt"] == str(output)


@pytest.mark.parametrize("missing", sorted(ops.RECOVERY_CHECKS))
def test_pregraph_proof_requires_exact_recovery_workflow_checks(tmp_path, monkeypatch, missing):
    path, fence, _previous, _stop, arguments = pregraph_state(tmp_path, monkeypatch)
    arguments[-1]["checks"].remove(missing)
    original, original_fence = path.read_bytes(), fence.read_bytes()
    with pytest.raises(RuntimeError, match="exact recovery replay and normalization"):
        ops.pregraph_resume(path, *arguments)
    assert path.read_bytes() == original and fence.read_bytes() == original_fence


@pytest.mark.parametrize("mutation", ("extra-public-change", "missing-change", "runtime", "backup",
    "archive", "legacy", "fence", "not-stopped", "writer", "current", "activation", "load",
    "database-id", "graph-object", "changed-release", "changed-load", "bundle"))
def test_pregraph_successor_refuses_drift_or_any_graph_mutation(tmp_path, monkeypatch, mutation):
    path, fence, previous, stop, arguments = pregraph_state(tmp_path, monkeypatch)
    if mutation == "extra-public-change":
        arguments[-2]["ingestions/onet/sql/001_catalog.sql"] = "changed"
    elif mutation == "missing-change":
        arguments[-2][next(iter(ops.SUCCESSOR_PREFLIGHTS))] = "old"
    elif mutation == "runtime":
        monkeypatch.setattr(ops.common, "digest", lambda data: "drift")
    elif mutation == "backup":
        Path(previous["database_backup"]["path"]).write_bytes(b"changed backup")
    elif mutation == "archive":
        monkeypatch.setattr(ops.loader, "remote_inventory", lambda *args: {})
    elif mutation == "legacy":
        monkeypatch.setattr(ops, "legacy_runtime", lambda hop: "drift")
    elif mutation == "fence":
        fence.write_text(json.dumps(dict(kind=ops.KIND, token="foreign", receipt=str(path))))
    elif mutation == "not-stopped":
        stop["runtime_idle"] = False
    elif mutation in ("writer", "current", "activation"):
        stop["pg"][{"writer": "writers", "current": "current", "activation": "activations"}[
            mutation]] = 1
    elif mutation == "load":
        stop["pg"]["loads"][0]["state"] = "RUNNING"
    elif mutation in ("database-id", "graph-object"):
        monkeypatch.setattr(ops.graph, "native_rows", lambda *args, **kwargs: [
            "other-db|0|0" if mutation == "database-id" else "db-id|1|0"])
    elif mutation in ("changed-release", "changed-load"):
        result = {**stop["pg"], "release_matches": mutation != "changed-release"}
        if mutation == "changed-load":
            result["loads"] = []
        monkeypatch.setattr(ops.additive, "sql", lambda *args: json.dumps(result))
    else:
        previous["bundle_inventory"] = {"other": "bytes"}
    path.write_text(json.dumps(previous))
    arguments[0].write_text(json.dumps(stop))
    original, original_fence = path.read_bytes(), fence.read_bytes()
    with pytest.raises(RuntimeError):
        ops.pregraph_resume(path, *arguments)
    assert path.read_bytes() == original and fence.read_bytes() == original_fence
