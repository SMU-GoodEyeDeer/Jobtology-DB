#!/usr/bin/env python3
"""Load additive frozen official O*NET details through native Hop under refresh.lock.

This coordinator never changes scheduler configuration, credentials, paid inputs
or old runtime. It requires an exact isolated native proof, takes a protected PG
backup, and compares every preexisting graph object after the owned load.
"""

from __future__ import annotations

# ruff: noqa: E501
import argparse
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import load_onet_catalogue as catalogue

ROOT, STATE, PROJECT = catalogue.ROOT, catalogue.STATE, catalogue.PROJECT
OWNER = "jobtology-onet-details-v1"
PREFIX = "urn:jobtology:onet-detail:"
identity = catalogue.identity
utc = catalogue.utc
NODE_TYPES = {"ELEMENT", "SOFTWARE", "TASK", "SCALE", "TASK_CATEGORY", "LEVEL_ANCHOR"}
EDGE_TYPES = {
    "ONET_DETAIL_PARENT",
    "ONET_SOFTWARE_EXAMPLE",
    "ONET_SOFTWARE_TYPE",
    "ONET_ESSENTIAL_SKILL",
    "ONET_TRANSFERABLE_SKILL",
    "ONET_KNOWLEDGE",
    "ONET_TASK",
    "ONET_TASK_RATING",
    "ONET_ANCHOR_ELEMENT",
    "ONET_ANCHOR_SCALE",
    "ONET_CATEGORY_SCALE",
}


def artifacts() -> tuple[str, ...]:
    return tuple(
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "ingestions/onet_details").rglob("*"))
        if p.is_file()
        and not p.is_symlink()
        and p.suffix in (".sql", ".hpl", ".hwf")
        and not {"tools", "tests", "__pycache__"}.intersection(p.relative_to(ROOT).parts)
    )


def bundle_identity(folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    # Parser owns the exact immutable descriptor contract; independent byte audit
    # rejects extra paths and symlinks before any runtime or database write.
    if folder.is_symlink() or not folder.is_dir():
        raise RuntimeError("Private regular bundle directory required")
    descriptor = json.loads((folder / "descriptor.json").read_text())
    filename = descriptor.get("details_file", "details.json")
    if filename != "details.json":
        raise RuntimeError("Unexpected prepared detail filename")
    payload = json.loads((folder / filename).read_text())
    if payload.get("contract_version") != "jobtology-onet-details-v1" or payload.get(
        "release_id"
    ) != descriptor.get("release_id"):
        raise RuntimeError("Detail release contract mismatch")
    if (
        descriptor.get("contract_version") != "hop-onet-details-bundle-v1"
        or descriptor.get("source_version") != "31.0"
        or descriptor.get("scheme_id") != "ONET"
        or any(
            descriptor.get(k) != payload.get(k)
            for k in (
                "base_release_id",
                "base_catalogue_sha256",
                "scope_codes",
                "source_version",
                "sources",
            )
        )
        or descriptor.get("node_count") != len(payload.get("nodes", []))
        or descriptor.get("edge_count") != len(payload.get("edges", []))
    ):
        raise RuntimeError("Descriptor semantics differ from prepared payload")
    inventory = {}
    for p in folder.rglob("*"):
        if p.is_symlink():
            raise RuntimeError("Evidence symlinks forbidden")
        if p.is_file():
            inventory[str(p.relative_to(folder))] = identity(p)
    expected = {
        "descriptor.json": identity(folder / "descriptor.json"),
        filename: dict(
            sha256=descriptor["details_sha256"], byte_length=descriptor["details_byte_length"]
        ),
    }
    expected["base_catalogue.json"] = dict(
        sha256=descriptor["base_catalogue_sha256"],
        byte_length=descriptor["base_catalogue_byte_length"],
    )
    for source in [*descriptor["sources"], *descriptor.get("download_receipts", [])]:
        name = source["archive_path"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"sources/[A-Za-z0-9_.-]+", name)
            or name in expected
        ):
            raise RuntimeError("Invalid evidence inventory path")
        expected[name] = dict(sha256=source["sha256"], byte_length=source["byte_length"])
    if inventory != expected:
        raise RuntimeError("Exact detail bundle inventory changed")
    return descriptor, inventory


def graph_owned(row: list[str], kind: str) -> bool:
    props = catalogue.graph.properties(row[-1])
    owner = props.get("managed_by")
    value = props.get("id")
    reserved = bool(value and value[1].startswith(PREFIX))
    if not reserved and owner != ["STRING NOT NULL", OWNER]:
        return False
    if owner != ["STRING NOT NULL", OWNER] or not reserved:
        raise RuntimeError("Foreign reserved detail identity")
    if props.get("scheme_id") != ["STRING NOT NULL", "ONET"]:
        raise RuntimeError("Detail scheme mismatch")
    if kind == "NODE":
        node_type = props.get("kind", ["", ""])[1]
        if node_type not in NODE_TYPES or set(catalogue.graph.unpack(row[1])) != {
            "entity",
            "onetDetail",
            node_type.lower(),
        }:
            raise RuntimeError("Unexpected detail node labels/type")
    elif row[3] not in EDGE_TYPES:
        raise RuntimeError("Unexpected detail relationship type")
    return True


def require_graph_preserved(before: Path, after: Path) -> dict[str, int]:
    counts = dict(legacy_nodes=0, legacy_edges=0, detail_nodes=0, detail_edges=0)
    with sqlite3.connect(before) as old, sqlite3.connect(after) as new:
        for kind in ("NODE", "REL"):
            for row in catalogue.graph.records(before, kind):
                if graph_owned(row, kind):
                    continue
                a = old.execute(
                    "SELECT payload FROM snapshot WHERE kind=? AND eid=?", (kind, row[0])
                ).fetchone()
                b = new.execute(
                    "SELECT payload FROM snapshot WHERE kind=? AND eid=?", (kind, row[0])
                ).fetchone()
                if a != b:
                    raise RuntimeError("Existing typed graph object changed")
                counts["legacy_nodes" if kind == "NODE" else "legacy_edges"] += 1
            for row in catalogue.graph.records(after, kind):
                owned = graph_owned(row, kind)
                exists = old.execute(
                    "SELECT 1 FROM snapshot WHERE kind=? AND eid=?", (kind, row[0])
                ).fetchone()
                if not exists and not owned:
                    raise RuntimeError("New graph object outside detail namespace")
                if owned:
                    counts["detail_nodes" if kind == "NODE" else "detail_edges"] += 1
    return counts


def verify_expected_graph(pg: str, snapshot: Path, load_id: str, directory: Path) -> dict[str, int]:
    nodes, edges = {}, {}
    all_node_ids = {}
    for row in catalogue.graph.records(snapshot, "NODE"):
        props = catalogue.graph.properties(row[-1])
        value = props.get("id")
        if value:
            all_node_ids[row[0]] = value[1]
        if graph_owned(row, "NODE"):
            if value[1] in nodes:
                raise RuntimeError("Duplicate owned node identity")
            nodes[value[1]] = row
    for row in catalogue.graph.records(snapshot, "REL"):
        if graph_owned(row, "REL"):
            value = catalogue.graph.properties(row[-1])["id"][1]
            if value in edges:
                raise RuntimeError("Duplicate owned edge identity")
            edges[value] = row
    checked = {}
    for table, target, key in (
        ("graph_load_node", nodes, "node_id"),
        ("graph_load_edge", edges, "edge_id"),
    ):
        query = (
            "SELECT to_jsonb(t)::text FROM onet_detail."
            + table
            + " t WHERE load_id="
            + catalogue.graph.dates.quote(load_id)
            + " ORDER BY "
            + key
        )
        seen = set()
        for expected, _ in catalogue.typed.copy_inventory(pg, query, directory / (table + ".csv")):
            value = expected[key]
            if value in seen:
                raise RuntimeError("Duplicate staged plan identity")
            actual = target.get(value)
            if actual is None:
                raise RuntimeError("Owned detail object missing")
            catalogue.typed.require_properties(expected["properties"], actual[-1])
            if table == "graph_load_node":
                if set(expected["labels"]) != set(catalogue.graph.unpack(actual[1])):
                    raise RuntimeError("Detail labels differ")
            elif (all_node_ids.get(actual[1]), all_node_ids.get(actual[2]), actual[3]) != (
                expected["start_id"],
                expected["end_id"],
                expected["edge_type"],
            ):
                raise RuntimeError("Detail edge endpoints/type differ")
            seen.add(value)
        if set(target) != seen:
            raise RuntimeError("Owned detail scope differs")
        checked["nodes" if table == "graph_load_node" else "edges"] = len(seen)
    return checked


PG_TABLES_SQL = "SELECT jsonb_agg(format('%I.%I',n.nspname,c.relname) ORDER BY 1) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN('r','p') AND n.nspname NOT IN('pg_catalog','information_schema','onet_detail') AND n.nspname NOT LIKE 'pg_%';"
PG_METADATA_SQL = "SELECT jsonb_build_object(\n      'functions',(SELECT jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,pg_get_functiondef(p.oid)) ORDER BY p.oid)\n       FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.prokind='f' AND n.nspname NOT IN('pg_catalog','information_schema','onet_detail') AND n.nspname NOT LIKE 'pg_%'),\n      'columns',(SELECT jsonb_agg(to_jsonb(c) ORDER BY table_schema,table_name,ordinal_position) FROM information_schema.columns c WHERE table_schema NOT IN('pg_catalog','information_schema','onet_detail')),\n      'indexes',(SELECT jsonb_agg(to_jsonb(i) ORDER BY schemaname,indexname) FROM pg_indexes i WHERE schemaname NOT IN('pg_catalog','information_schema','onet_detail')),\n      'triggers',(SELECT jsonb_agg(jsonb_build_array(t.oid,pg_get_triggerdef(t.oid)) ORDER BY t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname<>'onet_detail'));\n    "


def table_fingerprint_sql(name: str) -> str:
    return (
        "SELECT jsonb_build_object('table',"
        + catalogue.graph.dates.quote(name)
        + ",'value',jsonb_build_array(count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')))) "
        + "FROM (SELECT md5(to_jsonb(t)::text) h FROM "
        + name
        + " t) q;"
    )


def pg_state(pg: str, database: str = "jobtology", *, progress=None) -> dict[str, Any]:
    """Same exact table multiset hashes and metadata in one coherent snapshot.

    A persistent psql session issues one 180-second-bounded statement per table;
    metadata and table selection share its REPEATABLE READ READ ONLY transaction.
    No raw source rows leave PostgreSQL.
    """
    command = [
        "docker",
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-qAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        database,
    ]
    with tempfile.TemporaryFile(mode="w+t") as errors:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True
        )
        assert process.stdin is not None and process.stdout is not None

        def query(statement):
            process.stdin.write(statement + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                process.wait()
                errors.seek(0)
                raise RuntimeError(
                    "Bounded PostgreSQL preservation read failed: " + errors.read()[-4000:]
                )
            return json.loads(line)

        try:
            process.stdin.write(
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                "SET LOCAL statement_timeout='180s';\n"
            )
            names = query(PG_TABLES_SQL)
            if (
                not isinstance(names, list)
                or not all(isinstance(n, str) for n in names)
                or len(names) != len(set(names))
            ):
                raise RuntimeError("Invalid PostgreSQL table inventory")
            tables = {}
            for name in names:
                if progress is not None:
                    progress(dict(table=name, completed=len(tables), total=len(names)))
                row = query(table_fingerprint_sql(name))
                if (
                    row.get("table") != name
                    or not isinstance(row.get("value"), list)
                    or len(row["value"]) != 2
                ):
                    raise RuntimeError("Unexpected PostgreSQL fingerprint result")
                tables[name] = row["value"]
            metadata = query(PG_METADATA_SQL)
            process.stdin.write("COMMIT;\n")
            process.stdin.close()
            trailing = process.stdout.read()
            if process.wait() != 0 or trailing.strip():
                errors.seek(0)
                raise RuntimeError(
                    "PostgreSQL preservation transaction failed: " + errors.read()[-4000:]
                )
            if progress is not None:
                progress(dict(completed=len(tables), total=len(names), state="COMPLETE"))
            return dict(tables=tables, metadata=metadata)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()


def helper_identity() -> dict[str, str]:
    return {
        "loader": identity(Path(__file__))["sha256"],
        "parser": identity(ROOT / "ingestions/onet_details/prepare_details.py")["sha256"],
    }


def qualification(path: Path, public: dict[str, str], descriptor: dict[str, Any]) -> dict[str, Any]:
    if path.is_symlink():
        raise RuntimeError("Qualification symlink forbidden")
    value = json.loads(path.read_text())
    if (
        value.get("status") != "PASSED_ONET_DETAILS_NATIVE"
        or value.get("isolated") is not True
        or value.get("disposable_resources_removed") is not True
        or value.get("private_scratch_removed") is not True
        or value.get("artifact_sha256") != public
        or value.get("helper_sha256") != helper_identity()
        or value.get("official_details_sha256") != descriptor["details_sha256"]
        or not isinstance(value.get("checks"), list)
        or any(not isinstance(check, str) or not check for check in value.get("checks", []))
        or not {
            "all-typed-properties-and-endpoints",
            "exact-native-detail-replay",
            "all-existing-pg-preserved",
            "foreign-preflight-no-graph-mutation",
        }.issubset(value.get("checks", []))
    ):
        raise RuntimeError("Exact cleaned isolated native qualification required")
    return dict(path=str(path.resolve()), **identity(path), checks=value["checks"])


def legacy_runtime(hop: str) -> str:
    script = rb"""set -eu
cd "$1"
find ontology graph llm ingestions attachments cs retention cohort editorial operations \
 -type f \( -name '*.hpl' -o -name '*.hwf' -o -name '*.sql' -o -name '*.psql' -o -name '*.txt' \) \
 ! -path 'ingestions/onet_details/*' ! -path '*/tests/*' ! -path '*/tools/*' \
 -exec sha256sum {} + | LC_ALL=C sort
"""
    return catalogue.common.command(
        ["docker", "exec", "-i", hop, "sh", "-s", "--", PROJECT], data=script
    ).decode()


def own_fence(receipt: dict[str, Any], path: Path) -> None:
    fence = STATE / catalogue.performance.FENCE_NAME
    fd = os.open(fence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(dict(kind=receipt["kind"], token=receipt["token"], receipt=str(path)), output)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def execute(folder: Path, proof: Path) -> Path:
    descriptor, inventory = bundle_identity(folder)
    public = {name: identity(ROOT / name)["sha256"] for name in artifacts()}
    bound = qualification(proof, public, descriptor)
    runtime = catalogue.common.containers()
    catalogue.performance.idle(runtime)
    if (STATE / catalogue.performance.FENCE_NAME).exists():
        raise RuntimeError("Existing operation fence requires recovery")
    work = STATE / ("onet-details-load-" + uuid.uuid4().hex)
    work.mkdir(mode=0o700)
    receipt = dict(
        status="PREPARING",
        kind="OFFICIAL_ONET_DETAILS_NATIVE_LOAD",
        created_at=utc(),
        token=uuid.uuid4().hex,
        scheduler_fence_removed=False,
        helper_sha256=helper_identity(),
        containers=runtime,
        bundle_descriptor=descriptor,
        bundle_inventory=inventory,
        artifact_sha256=public,
        qualification=bound,
        source_requests=0,
        provider_calls=0,
        posting_matching_calls=0,
        installed=[],
    )
    path = work / "receipt.json"
    catalogue.common.write_json(path, receipt)
    own_fence(receipt, path)

    def phase(name):
        receipt["phase"] = name
        receipt["updated_at"] = utc()
        catalogue.common.write_json(path, receipt)
        print(json.dumps(dict(phase=name, receipt=str(path))), flush=True)

    def pg_progress(value):
        receipt["pg_snapshot_progress"] = value
        catalogue.common.write_json(path, receipt)
        print(json.dumps(dict(phase=receipt["phase"], **value)), flush=True)

    try:
        phase("CAPTURE_PREEXISTING_POSTGRESQL")
        receipt["legacy_runtime_before"] = legacy_runtime(runtime["hop"])
        receipt["before_pg"] = pg_state(runtime["pg"], progress=pg_progress)
        phase("BACKUP_DATABASE")
        receipt["database_backup"] = catalogue.additive.backup_database(runtime["pg"], work)
        phase("CAPTURE_PREEXISTING_TYPED_GRAPH")
        with catalogue.scalar_snapshot_adapter():
            receipt["graph_before"] = catalogue.graph.graph_snapshot(
                runtime["hop"], work, "graph-before"
            )
        catalogue.common.write_json(path, receipt)

        def remote(hop, relative):
            if relative not in public:
                raise RuntimeError("Runtime path outside details bundle")
            script = b'if test -f "$1" && test ! -L "$1"; then printf "PRESENT\\n"; cat "$1"; elif test ! -e "$1"; then printf "ABSENT\\n"; else exit 1; fi\n'
            data = catalogue.common.command(
                ["docker", "exec", "-i", hop, "sh", "-s", "--", PROJECT + "/" + relative],
                data=script,
            )
            marker, value = data.split(b"\n", 1)
            return value if marker == b"PRESENT" else None

        phase("INSTALL_ADDITIVE_RUNTIME")
        for name, digest in public.items():
            value = (ROOT / name).read_bytes()
            if catalogue.common.digest(value) != digest:
                raise RuntimeError("Candidate runtime changed")
            previous = remote(runtime["hop"], name)
            if previous is not None:
                saved = work / "before-runtime" / name
                saved.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                saved.write_bytes(previous)
            original = catalogue.deployment.remote_bytes
            try:
                catalogue.deployment.remote_bytes = remote
                catalogue.additive.write_runtime(
                    runtime["hop"],
                    name,
                    value,
                    None if previous is None else catalogue.common.digest(previous),
                    work,
                    uuid.uuid4().hex,
                )
            finally:
                catalogue.deployment.remote_bytes = original
            receipt["installed"].append(name)
            catalogue.common.write_json(path, receipt)
        # Existing immutable archive helper performs an exact byte/length audit;
        # its catalogue raw directory remains separate from old source exports.
        phase("ARCHIVE_FROZEN_EVIDENCE")
        archive = catalogue.archive(runtime["hop"], folder, inventory)
        receipt["archive_root"] = archive
        params = (
            "INPUT_FILE="
            + archive
            + "/details.json,EVIDENCE_ROOT="
            + archive
            + ",EXPECTED_INPUT_SHA256="
            + descriptor["details_sha256"]
            + ",RELEASE_ID="
            + descriptor["release_id"]
            + ",NEO4J_CONNECTION=jobtology-neo4j"
        )
        phase("NATIVE_READY")
        for file, label, p in [
            ("install.hwf", "native-install", ""),
            ("load_details.hwf", "native-load", params),
        ]:
            phase(label.upper())
            catalogue.loader.native(
                runtime["hop"],
                PROJECT + "/ingestions/onet_details/" + file,
                work,
                label,
                p,
                configuration="onet-local",
            )
        phase("VERIFY_PREEXISTING_POSTGRESQL")
        receipt["after_pg"] = pg_state(runtime["pg"], progress=pg_progress)
        if receipt["before_pg"] != receipt["after_pg"]:
            raise RuntimeError("Preexisting PostgreSQL data changed")
        phase("VERIFY_COMPLETE_TYPED_GRAPH")
        with catalogue.scalar_snapshot_adapter():
            receipt["graph_after"] = catalogue.graph.graph_snapshot(
                runtime["hop"], work, "graph-after"
            )
        actual = catalogue.graph.validate_archive(receipt["graph_after"])
        receipt["graph_preservation"] = require_graph_preserved(
            catalogue.graph.validate_archive(receipt["graph_before"]), actual
        )
        state = json.loads(
            catalogue.deployment.sql(
                runtime["pg"],
                "SELECT to_jsonb(l) FROM onet_detail.catalog_current c JOIN onet_detail.graph_load l USING(load_id) WHERE c.release_id="
                + catalogue.graph.dates.quote(descriptor["release_id"])
                + ";",
            )
        )
        if state["state"] != "VERIFIED":
            raise RuntimeError("Detail current graph not verified")
        receipt["load"] = state
        receipt["independent_expected_graph"] = verify_expected_graph(
            runtime["pg"], actual, state["load_id"], work
        )
        for name, digest in public.items():
            if catalogue.common.digest(remote(runtime["hop"], name)) != digest:
                raise RuntimeError("Runtime readback differs")
        if receipt["legacy_runtime_before"] != legacy_runtime(runtime["hop"]):
            raise RuntimeError("Existing runtime changed")
        receipt.update(status="VERIFIED_ONET_DETAILS", finished_at=utc())
        catalogue.common.write_json(path, receipt)
        catalogue.performance.release_fence(receipt, path)
        receipt["scheduler_fence_removed"] = True
    except BaseException as error:
        receipt.update(
            status="FAILED_FENCED",
            error_type=type(error).__name__,
            error=str(error),
            finished_at=utc(),
        )
        raise
    finally:
        catalogue.common.write_json(path, receipt)
    return path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle-dir", type=Path, required=True)
    p.add_argument("--qualification", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(execute(args.bundle_dir, args.qualification))


if __name__ == "__main__":
    main()
