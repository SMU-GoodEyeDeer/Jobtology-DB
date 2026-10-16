#!/usr/bin/env python3
"""Deploy and load a pinned local O*NET catalogue through native Hop.

The existing scheduler lock/fence protects one fresh backup and one before/after
legacy PostgreSQL and typed Neo4j preservation pair. Only the new O*NET runtime
bundle and its private archive may be published. No posting matching runs here.
Failures retain the fence, immutable logs and backup for operator recovery.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import deploy_capture_reader_runtime as capture
import load_jobkorea_dataset as loader
import migrate_batchfree_graph as graph
import migrate_flat_ontology_graph as typed

additive = capture.validation.routine.additive
common, deployment, performance = additive.common, additive.deployment, additive.performance
ROOT, STATE, PROJECT = common.ROOT, common.STATE, common.PROJECT
OWNER = "jobtology-onet-catalog-v1"
PREFIX = "urn:jobtology:onet:"
KIND = "ONET_CATALOGUE_ONLY_NATIVE_LOAD"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
SUCCESSOR_PREFLIGHTS = frozenset({"ingestions/onet/graph_preflight_nodes.hpl",
                                "ingestions/onet/graph_preflight_edges.hpl"})
RECOVERY_CHECKS = frozenset({"exact-replay-workflow-recovers-without-reimport",
                           "exact-read-only-normalization-matches-frozen-import",
                           "official-complete-graph-exact-replay"})
NODE_LABELS = {
    frozenset({"entity", "onetCatalogObject", "conceptScheme"}): "scheme",
    frozenset({"entity", "onetCatalogObject", "occupationGroup"}): "group",
    frozenset({"entity", "onetCatalogObject", "occupation"}): "occupation",
}


def utc() -> str:
    return datetime.now(UTC).isoformat()


def identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Expected a regular non-symlink evidence file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(sha256=digest, byte_length=path.stat().st_size)


def bundle_identity(folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if folder.is_symlink() or not folder.is_dir():
        raise RuntimeError("Expected a private regular bundle directory")
    descriptor = json.loads((folder / "descriptor.json").read_text())
    if descriptor.get("contract_version") != "hop-onet-bundle-v1":
        raise RuntimeError("Unexpected O*NET bundle contract")
    if not SAFE_ID.fullmatch(str(descriptor.get("release_id", ""))):
        raise RuntimeError("Invalid pinned release identity")
    expected = {"descriptor.json": identity(folder / "descriptor.json")}
    filename = descriptor.get("catalogue_file")
    if filename != "catalogue.json":
        raise RuntimeError("Unexpected prepared catalogue filename")
    expected[filename] = dict(sha256=descriptor["catalogue_sha256"],
                              byte_length=descriptor["catalogue_byte_length"])
    for source in [*descriptor["sources"], *descriptor.get("download_receipts", [])]:
        name = source["archive_path"]
        if not isinstance(name, str) or not re.fullmatch(r"sources/[A-Za-z0-9_.-]+", name):
            raise RuntimeError("Invalid evidence archive path")
        if name in expected:
            raise RuntimeError("Duplicate evidence archive path")
        expected[name] = dict(sha256=source["sha256"], byte_length=source["byte_length"])
    inventory = {}
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("Bundle evidence symlinks are forbidden")
        if path.is_file():
            inventory[str(path.relative_to(folder))] = identity(path)
        elif not path.is_dir():
            raise RuntimeError("Unexpected bundle evidence object")
    if inventory != expected:
        raise RuntimeError("Bundle file inventory, hashes or lengths changed")
    payload = json.loads((folder / filename).read_text())
    if payload.get("release_id") != descriptor["release_id"]:
        raise RuntimeError("Prepared release identity differs from descriptor")
    return descriptor, inventory


def artifacts() -> tuple[str, ...]:
    """The additive public runtime has one fixed subtree and two safe configs."""
    result = []
    folder = ROOT / "ingestions/onet"
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part in ("tests", "tools", "__pycache__") for part in relative.parts):
            continue
        if path.is_file() and path.suffix in (".hwf", ".hpl", ".sql"):
            if path.is_symlink():
                raise RuntimeError("Public O*NET artifacts must not be symlinks")
            result.append(str(path.relative_to(ROOT)))
    result += ["metadata/pipeline-run-configuration/onet-local.json",
               "metadata/workflow-run-configuration/onet-local.json"]
    if not result or "ingestions/onet/install.hwf" not in result:
        raise RuntimeError("Complete O*NET public runtime is required")
    for name in result:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("O*NET runtime file missing or symlink")
        if path.suffix in (".hpl", ".hwf"):
            document = ET.parse(path)
            for element in document.getroot().iter():
                if element.tag in ("filename", "sqlfilename"):
                    value = element.text or ""
                    if value.startswith("${PROJECT_HOME}/") and value[16:] not in result:
                        raise RuntimeError("O*NET workflow reaches outside its public bundle")
        elif path.suffix == ".json":
            json.loads(path.read_text())
    return tuple(result)


def remote_bytes(hop: str, relative: str) -> bytes | None:
    if relative not in artifacts():
        raise RuntimeError("Runtime path outside additive O*NET bundle")
    script = b'''set -eu
path="$1"; project="$2"; current="$path"
while :; do
 test ! -L "$current"
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
if test -e "$path"; then test -f "$path"; printf 'PRESENT\\n'; cat "$path"
else printf 'ABSENT\\n'; fi
'''
    output = common.command(["docker", "exec", "-i", hop, "sh", "-s", "--",
                             PROJECT + "/" + relative, PROJECT], data=script)
    marker, value = output.split(b"\n", 1)
    if marker == b"PRESENT":
        return value
    if marker == b"ABSENT":
        return None
    raise RuntimeError("Unexpected runtime byte response")


def legacy_runtime(hop: str) -> str:
    script = b'''set -eu
cd "$1"
find ontology graph llm ingestions attachments cs retention cohort editorial operations \\
 -type f \\( -name '*.hpl' -o -name '*.hwf' -o -name '*.sql' \\
 -o -name '*.psql' -o -name '*.txt' \\) \\
 ! -path 'ingestions/onet/*' ! -path '*/tests/*' ! -path '*/tools/*' \\
 -exec sha256sum {} + | LC_ALL=C sort
'''
    return common.command(["docker", "exec", "-i", hop, "sh", "-s", "--", PROJECT],
                          data=script).decode()


def archive(hop: str, folder: Path, inventory: dict[str, Any]) -> str:
    key = inventory["descriptor.json"]["sha256"]
    destination = PROJECT + "/data/onet-raw/" + key
    current = loader.remote_inventory(hop, destination)
    if current:
        if current != inventory:
            raise RuntimeError("Existing immutable O*NET archive differs")
        return destination
    relative = str(Path(destination).relative_to(PROJECT))
    script = b'''set -eu
project="$1"; relative="$2"; current="$project"; old_ifs="$IFS"; IFS=/
for part in $relative; do
 current="$current/$part"; test ! -L "$current"
 if test -e "$current"; then test -d "$current"; else
  mkdir "$current"; chown 501:501 "$current"; chmod 700 "$current"
 fi
done
IFS="$old_ifs"
'''
    common.command(["docker", "exec", "-u", "root", "-i", hop, "sh", "-s", "--",
                    PROJECT, relative], data=script)
    temporary = destination + ".stage-" + uuid.uuid4().hex
    try:
        common.command(["docker", "cp", str(folder) + "/.", hop + ":" + temporary])
        common.command(["docker", "exec", "-u", "root", hop, "chown", "-R", "501:501", temporary])
        common.command(["docker", "exec", "-u", "root", hop, "find", temporary,
                        "-type", "d", "-exec", "chmod", "700", "{}", "+"])
        common.command(["docker", "exec", "-u", "root", hop, "find", temporary,
                        "-type", "f", "-exec", "chmod", "400", "{}", "+"])
        if loader.remote_inventory(hop, temporary) != inventory:
            raise RuntimeError("Staged O*NET archive failed hash/length validation")
        # ensure_parent created only the empty destination; replace exactly it.
        if loader.remote_inventory(hop, destination):
            raise RuntimeError("Archive destination changed while staging")
        common.command(["docker", "exec", "-u", "root", hop, "rmdir", "--", destination])
        common.command(["docker", "exec", "-u", "root", hop, "mv", "-T", "--",
                        temporary, destination])
    finally:
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-rf", "--", temporary])
    if loader.remote_inventory(hop, destination) != inventory:
        raise RuntimeError("Installed O*NET archive failed validation")
    return destination


def graph_owned(row: list[str], kind: str) -> bool:
    props = graph.properties(row[-1])
    owner = props.get("managed_by")
    identity_value = props.get("id")
    reserved = bool(identity_value and identity_value[1].startswith(PREFIX))
    if not reserved and owner != ["STRING NOT NULL", OWNER]:
        return False
    if owner != ["STRING NOT NULL", OWNER] or not identity_value or not reserved:
        raise RuntimeError("Foreign or incomplete ownership in reserved O*NET namespace")
    if (props.get("scheme_id") != ["STRING NOT NULL", "ONET"]
        or props.get("current") not in (["BOOLEAN NOT NULL", "true"],
                                        ["BOOLEAN NOT NULL", "false"])
        or not props.get("release_id") or props["release_id"][0] != "STRING NOT NULL"
        or not SAFE_ID.fullmatch(props["release_id"][1])):
        raise RuntimeError("O*NET scheme/current/release metadata missing or malformed")
    if any(name in props for name in ("confidence", "review_status", "duty_evidence")):
        raise RuntimeError("Unexpected matching/evidence metadata on O*NET catalogue graph")
    if kind == "NODE":
        node_kind = NODE_LABELS.get(frozenset(graph.unpack(row[1])))
        if node_kind is None:
            raise RuntimeError("O*NET catalogue must contain exact flat node labels")
        pattern = {
            "scheme": re.compile(re.escape(PREFIX) + r"scheme\Z"),
            "group": re.compile(re.escape(PREFIX) + r"group:\d{2}-\d{4}\Z"),
            "occupation": re.compile(re.escape(PREFIX) + r"occupation:\d{2}-\d{4}\.\d{2}\Z"),
        }[node_kind]
        if not pattern.fullmatch(identity_value[1]):
            raise RuntimeError("O*NET flat node identity differs from its label/kind")
        expected_kind = {"scheme": "conceptScheme", "group": "occupationGroup",
                         "occupation": "occupation"}[node_kind]
        expected_code = "ONET" if node_kind == "scheme" else identity_value[1].split(":")[-1]
        if (props.get("kind") != ["STRING NOT NULL", expected_kind]
            or props.get("code") != ["STRING NOT NULL", expected_code]):
            raise RuntimeError("O*NET code/kind metadata differs from flat identity")
    elif row[3] not in {"IN_SCHEME", "BROADER"} or not re.fullmatch(
        re.escape(PREFIX) + r"relationship:[0-9a-f]{64}", identity_value[1]
    ):
        raise RuntimeError("Unexpected O*NET catalogue relationship identity/type")
    return True


def require_graph_preserved(before: Path, after: Path) -> dict[str, int]:
    """Exact legacy element IDs, labels, endpoints and all typed properties."""
    old_db = sqlite3.connect(f"file:{before}?mode=ro", uri=True)
    new_db = sqlite3.connect(f"file:{after}?mode=ro", uri=True)
    counts = dict(legacy_nodes=0, legacy_edges=0, onet_nodes=0, onet_edges=0)
    owned_nodes: dict[str, str] = {}
    try:
        for row in graph.records(after, "NODE"):
            if graph_owned(row, "NODE"):
                owned_nodes[row[0]] = NODE_LABELS[frozenset(graph.unpack(row[1]))]
        for kind in ("NODE", "REL"):
            for row in graph.records(before, kind):
                if graph_owned(row, kind):
                    continue
                found = new_db.execute("SELECT payload FROM snapshot WHERE kind=? AND eid=?",
                                       (kind, row[0])).fetchone()
                expected = old_db.execute("SELECT payload FROM snapshot WHERE kind=? AND eid=?",
                                          (kind, row[0])).fetchone()
                if found != expected:
                    raise RuntimeError("Existing legacy graph object changed or disappeared")
                counts["legacy_nodes" if kind == "NODE" else "legacy_edges"] += 1
            for row in graph.records(after, kind):
                owned = graph_owned(row, kind)
                exists = old_db.execute("SELECT 1 FROM snapshot WHERE kind=? AND eid=?",
                                        (kind, row[0])).fetchone()
                if not exists and not owned:
                    raise RuntimeError("Unexpected new object outside O*NET catalogue ownership")
                if owned:
                    if kind == "REL" and (row[1] not in owned_nodes or row[2] not in owned_nodes):
                        raise RuntimeError("O*NET catalogue relationship touches legacy graph")
                    if kind == "REL" and (
                        (row[3] == "IN_SCHEME" and (
                            owned_nodes[row[1]] == "scheme" or owned_nodes[row[2]] != "scheme"))
                        or (row[3] == "BROADER" and "scheme" in (
                            owned_nodes[row[1]], owned_nodes[row[2]]))
                    ):
                        raise RuntimeError("O*NET catalogue relationship endpoint kinds differ")
                    counts["onet_nodes" if kind == "NODE" else "onet_edges"] += 1
        return counts
    finally:
        old_db.close()
        new_db.close()


def qualification(path: Path, public: dict[str, str], descriptor: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("status") != "PASSED_ONET_NATIVE_CATALOGUE" or not value.get("isolated"):
        raise RuntimeError("Passed isolated native O*NET proof required")
    if not value.get("disposable_resources_removed") or not value.get("private_scratch_removed"):
        raise RuntimeError("Native qualification cleanup must be complete")
    if value.get("artifact_sha256") != public:
        raise RuntimeError("Native qualification does not bind exact public runtime")
    if value.get("official_catalogue_sha256") != descriptor["catalogue_sha256"]:
        raise RuntimeError("Native qualification does not prove this exact official payload")
    return dict(path=str(path.resolve()), **identity(path), checks=value["checks"])


def verify_expected_graph(pg: str, snapshot: Path, load_id: str,
                          directory: Path) -> dict[str, int]:
    """Compare every owned typed property and endpoint to the immutable PG plan."""
    nodes, edges = {}, {}
    for kind, target in (("NODE", nodes), ("REL", edges)):
        for row in graph.records(snapshot, kind):
            if not graph_owned(row, kind):
                continue
            value = graph.properties(row[-1])["id"][1]
            if value in target:
                raise RuntimeError("Duplicate O*NET graph identity")
            target[value] = row
    node_ids = {row[0]: value for value, row in nodes.items()}
    checked = dict(nodes=0, edges=0)
    for table, target, key in (("graph_load_node", nodes, "node_id"),
                               ("graph_load_edge", edges, "edge_id")):
        query = "SELECT to_jsonb(t)::text FROM classification." + table + " t WHERE load_id=" \
            + graph.dates.quote(load_id) + " ORDER BY " + key
        seen = set()
        for expected, _ in typed.copy_inventory(pg, query, directory / (table + ".csv")):
            identity_value = expected[key]
            actual = target.get(identity_value)
            if actual is None:
                raise RuntimeError("Expected O*NET graph identity missing")
            typed.require_properties(expected["properties"], actual[-1])
            if table == "graph_load_node":
                if set(expected["labels"]) != set(graph.unpack(actual[1])):
                    raise RuntimeError("Expected O*NET labels differ")
            elif (node_ids.get(actual[1]), node_ids.get(actual[2]), actual[3]) != (
                expected["start_id"], expected["end_id"], expected["edge_type"]
            ):
                raise RuntimeError("Expected O*NET endpoints/type differ")
            seen.add(identity_value)
        if set(target) != seen:
            raise RuntimeError("Graph contains O*NET objects outside immutable load plan")
        checked["nodes" if table == "graph_load_node" else "edges"] = len(seen)
    return checked


def legacy_state(runtime: dict[str, str], directory: Path, label: str) -> dict[str, Any]:
    with capture.configured():
        return additive.snapshot_state(runtime, directory, label)


def own_fence(receipt: dict[str, Any], path: Path) -> None:
    fence = STATE / performance.FENCE_NAME
    descriptor = os.open(fence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(dict(kind=KIND, token=receipt["token"], receipt=str(path)), stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextlib.contextmanager
def scalar_snapshot_adapter():
    """Private snapshots bind scalar grid parameters regardless of source templates."""
    original = graph.dates.build_snapshot

    def build(path: Path, query: str, output_base: str) -> None:
        original(path, query, output_base)
        document = ET.parse(path)
        neo = next(node for node in document.getroot().findall("transform")
                   if node.findtext("type") == "Neo4jCypherOutput")
        for key, value in (("unwind", "N"), ("unwind_map", ""), ("batch_size", "1"),
                           ("cypher_from_field", "N"), ("read_only", "Y")):
            node = neo.find(key)
            if node is None:
                node = ET.SubElement(neo, key)
            node.text = value
        document.write(path, encoding="utf-8", xml_declaration=True)
        path.chmod(0o600)

    graph.dates.build_snapshot = build
    try:
        yield
    finally:
        graph.dates.build_snapshot = original


def scalar_grid_probe(hop: str, directory: Path) -> dict[str, Any]:
    values = ["onet-scalar-bound-a", "onet-scalar-bound-b"]
    with scalar_snapshot_adapter():
        actual = graph.native_rows(hop, "RETURN $bounds AS signature", directory,
            "scalar-grid-probe", grid=("bounds", values, "String"))
    if actual != values:
        raise RuntimeError("Native scalar-grid snapshot binding differs")
    return dict(status="PASSED", expected=values, actual=actual,
                pipeline_sha256=identity(directory / "scalar-grid-probe.hpl")["sha256"])


def prewrite_resume(path: Path, runtime: dict[str, str], descriptor: dict[str, Any],
                    inventory: dict[str, Any], public: dict[str, str],
                    bound: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    """Only the first-load snapshot failure can carry its existing PG baseline."""
    previous = json.loads(path.read_text())
    if (path.is_symlink() or previous.get("kind") != KIND
        or previous.get("status") != "FAILED_FENCED" or previous.get("installed") != []
        or any(key in previous for key in ("database_backup", "archive_root", "graph_before"))
        or previous.get("scheduler_fence_removed") is not False
        or any(previous.get(key) != 0 for key in (
            "source_requests", "provider_calls", "posting_matching_calls"))
        or any((path.parent / name).exists() for name in (
            "database-before.dump", "candidate", "before-runtime", "native-install.log",
            "native-load.log", "native-replay.log"))
        or not previous.get("before") or not previous.get("legacy_runtime_before")
        or previous.get("containers") != runtime
        or previous.get("bundle_descriptor") != descriptor
        or previous.get("bundle_inventory") != inventory
        or previous.get("artifact_sha256") != public
        or previous.get("isolated_proof") != bound):
        raise RuntimeError("Resume requires the exact untouched pre-backup first-load failure")
    fence = STATE / performance.FENCE_NAME
    if fence.is_symlink():
        raise RuntimeError("Owned scheduler fence must not be a symlink")
    fence_bytes = fence.read_bytes()
    owner = json.loads(fence_bytes)
    if owner != dict(kind=KIND, token=previous["token"], receipt=str(path)):
        raise RuntimeError("Prewrite resume does not own this exact scheduler fence")
    if legacy_runtime(runtime["hop"]) != previous["legacy_runtime_before"]:
        raise RuntimeError("Frozen legacy runtime changed during fenced prewrite failure")
    if any(remote_bytes(runtime["hop"], name) is not None for name in public):
        raise RuntimeError("Prewrite first-load recovery requires absent new public runtime")
    if deployment.sql(runtime["pg"], "BEGIN READ ONLY; SELECT "
        "to_regnamespace('classification') IS NULL; COMMIT;") != "t":
        raise RuntimeError("Prewrite first-load recovery requires no classification schema")
    directory = path.parent / ("resume-prewrite-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    output = directory / "receipt.json"
    receipt = {**{key: value for key, value in previous.items()
                 if key not in ("failure_type", "recovery", "finished_at")},
        "status": "RESUMING_PREWRITE", "resumed_at": utc(),
        "launched_helper_sha256": identity(Path(__file__))["sha256"],
        "prewrite_resume": dict(failed_receipt=str(path), **identity(path),
                                retained_postgres_baseline=True,
                                untouched_namespace_and_runtime=True)}
    common.write_json(output, receipt)
    (directory / "fence-before.json").write_bytes(fence_bytes)
    if fence.read_bytes() != fence_bytes:
        raise RuntimeError("Scheduler fence changed before guarded resume publication")
    stage = STATE / (".onet-fence-" + uuid.uuid4().hex)
    try:
        common.write_json(stage, dict(kind=KIND, token=receipt["token"], receipt=str(output)))
        os.replace(stage, fence)
    finally:
        stage.unlink(missing_ok=True)
    path.chmod(0o400)
    return directory, output, receipt


def pregraph_resume(path: Path, stopped: Path, folder: Path, runtime: dict[str, str],
                    descriptor: dict[str, Any], inventory: dict[str, Any],
                    public: dict[str, str], bound: dict[str, Any]
                    ) -> tuple[Path, Path, dict[str, Any]]:
    """Retry one normally failed first-load preflight with a proven two-file successor."""
    previous = json.loads(path.read_text())
    stop = json.loads(stopped.read_text())
    old = previous.get("artifact_sha256", {})
    if not set(bound.get("checks", [])) >= RECOVERY_CHECKS:
        raise RuntimeError("Pregraph proof must qualify exact recovery replay and normalization")
    if (path.is_symlink() or stopped.is_symlink() or previous.get("kind") != KIND
        or previous.get("status") != "FAILED_FENCED"
        or len(previous.get("installed", [])) != len(old)
        or set(previous.get("installed", [])) != set(old)
        or previous.get("scheduler_fence_removed") is not False
        or previous.get("containers") != runtime
        or previous.get("bundle_descriptor") != descriptor
        or previous.get("bundle_inventory") != inventory
        or not previous.get("before") or not previous.get("graph_before")
        or not previous.get("database_backup") or not previous.get("archive_root")
        or any(previous.get(key) != 0 for key in (
            "source_requests", "provider_calls", "posting_matching_calls"))
        or set(old) != set(public)
        or {name for name in old if old[name] != public[name]} != SUCCESSOR_PREFLIGHTS):
        raise RuntimeError("Pregraph successor requires the exact normally failed first load")
    prior_proof = previous.get("isolated_proof", {})
    if qualification(Path(prior_proof["path"]), old, descriptor) != prior_proof:
        raise RuntimeError("Immutable predecessor qualification changed")
    if (stop.get("runtime_idle") is not True or stop.get("graph_counts") != ["0|0"]
        or any(stop.get("pg", {}).get(key) != 0 for key in (
            "current", "targets", "writers", "activations"))
        or len(stop.get("pg", {}).get("loads", [])) != 1
        or stop["pg"]["loads"][0].get("state") != "FAILED"
        or stop["pg"]["loads"][0].get("release_id") != descriptor["release_id"]
        or stop["pg"]["loads"][0].get("previous_load_id") is not None):
        raise RuntimeError("Stopped proof must establish failed first load and empty target")
    fence = STATE / performance.FENCE_NAME
    if fence.is_symlink():
        raise RuntimeError("Owned scheduler fence must not be a symlink")
    fence_bytes = fence.read_bytes()
    if json.loads(fence_bytes) != dict(kind=KIND, token=previous["token"], receipt=str(path)):
        raise RuntimeError("Pregraph successor does not own this exact scheduler fence")
    if legacy_runtime(runtime["hop"]) != previous["legacy_runtime_before"]:
        raise RuntimeError("Legacy runtime changed after stopped preflight")
    for name, digest in old.items():
        actual = remote_bytes(runtime["hop"], name)
        if actual is None or common.digest(actual) != digest:
            raise RuntimeError("Installed predecessor runtime changed before successor review")
    backup = previous["database_backup"]
    if (Path(backup["path"]) != path.parent / "database-before.dump"
        or identity(Path(backup["path"])) != {
            key: backup[key] for key in ("sha256", "byte_length")}
        or backup.get("listing_validated") is not True):
        raise RuntimeError("Original fresh backup identity/listing proof changed")
    if Path(previous["graph_before"]["path"]) != path.parent / "graph-before.sqlite":
        raise RuntimeError("Original typed graph baseline path changed")
    graph.validate_archive(previous["graph_before"])
    expected_archive = PROJECT + "/data/onet-raw/" + inventory["descriptor.json"]["sha256"]
    if previous["archive_root"] != expected_archive or loader.remote_inventory(
        runtime["hop"], expected_archive) != inventory:
        raise RuntimeError("Immutable installed O*NET archive changed")
    directory = path.parent / ("resume-pregraph-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    payload = json.loads((folder / "catalogue.json").read_text())
    token = stop["pg"]["loads"][0]["load_id"]
    query = "BEGIN READ ONLY; SET LOCAL timezone='UTC'; SELECT classification.assert_catalog(" \
        + graph.dates.quote(
        descriptor["release_id"]) + "); SELECT classification.assert_graph_plan(" \
        + graph.dates.quote(token) + "); " + normalized_payload_sql(payload) \
        + " SELECT jsonb_build_object('loads',"
    query += "(SELECT jsonb_agg(to_jsonb(l) ORDER BY load_id) FROM classification.graph_load l),"
    query += "'writers',(SELECT count(*) FROM retention.writer),"
    query += "'targets',(SELECT count(*) FROM classification.graph_target),"
    query += "'current',(SELECT count(*) FROM classification.catalog_current),"
    query += "'activations',(SELECT count(*) FROM classification.activation_event),"
    query += "'release_matches',(SELECT state='READY' AND normalized_input=" \
        + "(SELECT value FROM normalized) AND (SELECT count(*) " \
        + "FROM classification.catalog_release)=1 AND manifest_hash=" \
        + graph.dates.quote(stop["pg"]["loads"][0]["manifest_hash"]) \
        + " FROM classification.catalog_release WHERE release_id=" \
        + graph.dates.quote(descriptor["release_id"]) + ")); COMMIT;"
    live = json.loads(additive.sql(runtime["pg"], query, directory, "stopped-pg-readback"))
    if live.pop("release_matches", None) is not True or live != stop["pg"]:
        raise RuntimeError("Stopped owned load, writer absence or immutable release changed")
    scope = ("CALL db.info() YIELD id CALL () { MATCH(n) WHERE "
        "n.managed_by='jobtology-onet-catalog-v1' OR coalesce(n.id,'') STARTS WITH "
        "'urn:jobtology:onet:' RETURN count(n) AS nodes } CALL () { MATCH()-[r]->() WHERE "
        "r.managed_by='jobtology-onet-catalog-v1' OR coalesce(r.id,'') STARTS WITH "
        "'urn:jobtology:onet:' RETURN count(r) AS edges } "
        "RETURN id+'|'+toString(nodes)+'|'+toString(edges) AS signature")
    with scalar_snapshot_adapter():
        actual_scope = graph.native_rows(runtime["hop"], scope, directory, "stopped-graph-readback")
    if actual_scope != [stop["pg"]["loads"][0]["database_id"] + "|0|0"]:
        raise RuntimeError("Pregraph successor requires no owned or reserved graph objects")
    output = directory / "receipt.json"
    receipt = {**{key: value for key, value in previous.items()
                 if key not in ("failure_type", "recovery", "finished_at")},
        "status": "RESUMING_PREGRAPH", "resumed_at": utc(), "artifact_sha256": public,
        "isolated_proof": bound, "launched_helper_sha256": identity(Path(__file__))["sha256"],
        "pregraph_resume": dict(failed_receipt=str(path), **identity(path),
            stopped_proof=dict(path=str(stopped), **identity(stopped)),
            predecessor_artifact_sha256=old, predecessor_isolated_proof=prior_proof,
            changed_artifacts=sorted(SUCCESSOR_PREFLIGHTS), owned_failed_load=token,
            retained_postgres_and_graph_baselines=True, retained_original_backup=True,
            retained_original_archive=True, no_graph_mutations=True)}
    common.write_json(output, receipt)
    (directory / "fence-before.json").write_bytes(fence_bytes)
    if fence.read_bytes() != fence_bytes:
        raise RuntimeError("Scheduler fence changed before successor publication")
    stage = STATE / (".onet-fence-" + uuid.uuid4().hex)
    try:
        common.write_json(stage, dict(kind=KIND, token=receipt["token"], receipt=str(output)))
        os.replace(stage, fence)
    finally:
        stage.unlink(missing_ok=True)
    path.chmod(0o400)
    return directory, output, receipt


def normalized_payload_sql(payload: dict[str, Any]) -> str:
    """Read-only CTE mirrors the frozen SQL001 import normalization exactly."""
    return ("WITH supplied AS (SELECT " + graph.dates.quote(json.dumps(
        payload, ensure_ascii=False)) + "::jsonb AS value), source_normalized AS ("
        "SELECT jsonb_set(value,'{sources}',(SELECT jsonb_agg("
        "x||jsonb_build_object('downloaded_at',(x->>'downloaded_at')::timestamptz) "
        "ORDER BY x->>'file_id') FROM jsonb_array_elements(value->'sources') x)) AS value "
        "FROM supplied), term_normalized AS (SELECT jsonb_set(value,'{terms}',"
        "(SELECT jsonb_agg(x ORDER BY x->>'term_id') "
        "FROM jsonb_array_elements(value->'terms') x)) AS value FROM source_normalized), "
        "normalized AS (SELECT jsonb_set(value,'{hierarchy}',(SELECT jsonb_agg(x "
        "ORDER BY x->>'child_id',x->>'parent_id') FROM jsonb_array_elements(value->'hierarchy') "
        "x)) AS value FROM term_normalized)")


def execute(folder: Path, proof: Path, resume: Path | None = None,
            resume_graph: Path | None = None, stopped: Path | None = None) -> Path:
    descriptor, inventory = bundle_identity(folder)
    public = {name: identity(ROOT / name)["sha256"] for name in artifacts()}
    bound = qualification(proof, public, descriptor)
    runtime = common.containers()
    performance.idle(runtime)
    if resume_graph is not None and stopped is not None:
        directory, path, receipt = pregraph_resume(resume_graph, stopped, folder, runtime,
                                                 descriptor, inventory, public, bound)
    elif resume is not None:
        directory, path, receipt = prewrite_resume(resume, runtime, descriptor, inventory,
                                                  public, bound)
    elif (STATE / performance.FENCE_NAME).exists():
        raise RuntimeError("An existing fenced operation must be recovered first")
    else:
        directory = STATE / ("onet-catalogue-load-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        path = directory / "receipt.json"
        receipt = dict(kind=KIND, status="PREPARING", token=uuid.uuid4().hex,
                   created_at=utc(), containers=runtime, bundle_descriptor=descriptor,
                   launched_helper_sha256=identity(Path(__file__))["sha256"],
                   bundle_inventory=inventory, isolated_proof=bound, artifact_sha256=public,
                   source_requests=0, provider_calls=0, posting_matching_calls=0,
                   scheduler_fence_removed=False, installed=[])
        common.write_json(path, receipt)
        own_fence(receipt, path)
    try:
        if resume is None and resume_graph is None:
            receipt["before"] = legacy_state(runtime, directory, "before")
            receipt["legacy_runtime_before"] = legacy_runtime(runtime["hop"])
        if resume_graph is None:
            receipt["scalar_grid_probe"] = scalar_grid_probe(runtime["hop"], directory)
            with scalar_snapshot_adapter():
                receipt["graph_before"] = graph.graph_snapshot(
                    runtime["hop"], directory, "graph-before")
            receipt["database_backup"] = additive.backup_database(runtime["pg"], directory)
        common.write_json(path, receipt)
        for name in public:
            if resume_graph is not None and name not in SUCCESSOR_PREFLIGHTS:
                continue
            previous = remote_bytes(runtime["hop"], name)
            target = directory / "candidate" / name
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if identity(target)["sha256"] != public[name]:
                raise RuntimeError("Public O*NET candidate changed before deployment")
            if previous is not None:
                saved = directory / "before-runtime" / name
                saved.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                saved.write_bytes(previous)
            # Publication helper is reused with a narrowly scoped remote reader.
            original = deployment.remote_bytes
            try:
                deployment.remote_bytes = remote_bytes
                additive.write_runtime(runtime["hop"], name, target.read_bytes(),
                    None if previous is None else common.digest(previous), directory,
                    receipt["token"])
            finally:
                deployment.remote_bytes = original
            if resume_graph is None:
                receipt["installed"].append(name)
            else:
                receipt["pregraph_resume"].setdefault("successor_installed", []).append(name)
                common.write_json(path, receipt)
        evidence_root = (receipt["archive_root"] if resume_graph is not None
                         else archive(runtime["hop"], folder, inventory))
        receipt.update(status="NATIVE_INSTALL" if resume_graph is None else "NATIVE_GRAPH_RETRY",
                       archive_root=evidence_root)
        common.write_json(path, receipt)
        params = ("INPUT_FILE=" + evidence_root + "/catalogue.json,EVIDENCE_ROOT=" + evidence_root
                  + ",EXPECTED_INPUT_SHA256=" + descriptor["catalogue_sha256"]
                  + ",RELEASE_ID=" + descriptor["release_id"]
                  + ",NEO4J_CONNECTION=jobtology-neo4j")
        replay_params = "RELEASE_ID=" + descriptor["release_id"] \
            + ",NEO4J_CONNECTION=jobtology-neo4j"
        stages = (
            ("install.hwf", "native-install", ""),
            ("load_catalog.hwf", "native-load", params),
            ("load_catalog.hwf", "native-replay", params),
        ) if resume_graph is None else (
            ("replay_catalog.hwf", "native-load", replay_params),
            ("replay_catalog.hwf", "native-replay", replay_params),
        )
        for file, label, parameters in stages:
            loader.native(runtime["hop"], PROJECT + "/ingestions/onet/" + file,
                          directory, label, parameters, configuration="onet-local")
        receipt["after"] = legacy_state(runtime, directory, "after")
        if receipt["before"] != receipt["after"]:
            raise RuntimeError("Legacy PostgreSQL schema/data/query/matching/pins changed")
        if receipt["legacy_runtime_before"] != legacy_runtime(runtime["hop"]):
            raise RuntimeError("Existing frozen public runtime changed")
        for name, digest in public.items():
            current = remote_bytes(runtime["hop"], name)
            if current is None or common.digest(current) != digest:
                raise RuntimeError("O*NET deployed runtime readback differs")
        with scalar_snapshot_adapter():
            receipt["graph_after"] = graph.graph_snapshot(
                runtime["hop"], directory, "graph-after")
        receipt["graph_preservation"] = require_graph_preserved(
            graph.validate_archive(receipt["graph_before"]),
            graph.validate_archive(receipt["graph_after"]))
        receipt["catalogue_state"] = json.loads(additive.sql(runtime["pg"],
            "BEGIN READ ONLY; SELECT jsonb_build_object('current',to_jsonb(c),'release',"
            "to_jsonb(r)-'normalized_input','load',to_jsonb(l),'terms',"
            "(SELECT count(*) FROM classification.term WHERE release_id=r.release_id),"
            "'hierarchy',(SELECT count(*) FROM classification.hierarchy "
            "WHERE release_id=r.release_id)) FROM classification.catalog_current c "
            "JOIN classification.catalog_release r USING(release_id) "
            "JOIN classification.graph_load l USING(load_id) WHERE c.scheme_id='ONET' "
            "AND r.release_id=" + graph.dates.quote(descriptor["release_id"]) + "; COMMIT;",
            directory, "catalogue-state"))
        catalog = receipt["catalogue_state"]
        if (catalog["release"]["state"] != "READY" or catalog["load"]["state"] != "VERIFIED"
            or catalog["terms"] != descriptor["counts"]["terms"]
            or catalog["hierarchy"] != descriptor["counts"]["hierarchy"]):
            raise RuntimeError("Independent pinned catalogue state/count verification failed")
        receipt["independent_expected_graph"] = verify_expected_graph(runtime["pg"],
            graph.validate_archive(receipt["graph_after"]), catalog["load"]["load_id"], directory)
        if not receipt["graph_preservation"]["onet_nodes"]:
            raise RuntimeError("Actual O*NET graph creation is required")
        receipt.update(status="VERIFIED_ONET_CATALOGUE_ONLY", finished_at=utc())
        common.write_json(path, receipt)
        performance.release_fence(receipt, path)
        receipt["scheduler_fence_removed"] = True
    except BaseException as error:
        receipt.update(status="FAILED_FENCED", failure_type=type(error).__name__,
                       recovery="Retain evidence and fence; inspect owned state before retry.",
                       finished_at=utc())
        common.write_json(path, receipt)
        raise RuntimeError("O*NET load stopped; protected fenced receipt: " + str(path)) from error
    common.write_json(path, receipt)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--isolated-proof", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--resume-prewrite", type=Path,
                        help="Resume only an untouched first-load pre-backup snapshot failure.")
    modes.add_argument("--resume-pregraph", type=Path,
                       help="Retry a normally failed first-load preflight with two proven HPLs.")
    parser.add_argument("--stopped-proof", type=Path,
                        help="Required exact owned stop/readback evidence for --resume-pregraph.")
    args = parser.parse_args()
    if bool(args.resume_pregraph) != bool(args.stopped_proof):
        parser.error("--resume-pregraph and --stopped-proof are required together")
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(execute(args.bundle_dir.resolve(), args.isolated_proof.resolve(),
                      args.resume_prewrite.resolve() if args.resume_prewrite else None,
                      args.resume_pregraph.resolve() if args.resume_pregraph else None,
                      args.stopped_proof.resolve() if args.stopped_proof else None), flush=True)


if __name__ == "__main__":
    main()
