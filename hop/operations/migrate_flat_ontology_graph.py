#!/usr/bin/env python3
"""Guarded reversible flattening of the approved ontology's Neo4j projection.

PostgreSQL sealed revisions, source histories, catalogue approvals, frozen inputs
and cost/review rows remain authoritative and unchanged. Only exactly backed
revision nodes/attachments and PG-owned canonical fields may change in Neo4j.
Reusable functions do not take refresh.lock; the CLI acquires it once.
"""

from __future__ import annotations

import argparse
import copy
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import migrate_batchfree_graph as graph

common, deployment, dates = graph.common, graph.deployment, graph.dates
MIGRATION_SQL = (
    "ontology/sql/028_flat_graph_projection.sql",
    "ontology/sql/029_flat_catalog_compatibility.sql",
)
FENCE_NAME = "flat-ontology-migration.pending"
FENCE_COMMENT = "# Failed/interrupted ontology flattening leaves this protected operator fence.\n"
FENCE_LINE = '[[ ! -e "$STATE_DIR/flat-ontology-migration.pending" ]] || exit 0\n'
IDENTITY_KEYS = frozenset(("id", "entity_id", "kind", "code", "scheme_id", "content_hash"))
DEFAULT_RELEASE = "ontology-catalog-source-20261001"
PG_DATABASE = "jobtology"


def revision_nodes(snapshot: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in graph.records(snapshot, "NODE"):
        labels = set(graph.unpack(node[1]))
        specific = {
            label for label in labels if label.endswith("Revision") and label != "entityRevision"
        }
        if "entityRevision" in labels or specific:
            if len(specific) != 1 or labels != {"ontologyObject", "entityRevision", *specific}:
                raise RuntimeError("Unexpected revision labels; removal refused")
            result[node[0]] = node
    return result


def typed_json_matches(expected: Any, actual: list[str]) -> bool:
    """Compare immutable PG JSON values without coercing Neo4j property types."""
    kind, value = actual
    if isinstance(expected, bool):
        return kind == "BOOLEAN NOT NULL" and value == str(expected).lower()
    if isinstance(expected, str):
        return kind == "STRING NOT NULL" and value == expected
    if isinstance(expected, int):
        return kind == "INTEGER NOT NULL" and value == str(expected)
    if isinstance(expected, (float, Decimal)):
        return kind == "FLOAT NOT NULL" and Decimal(value) == Decimal(str(expected))
    if isinstance(expected, list):
        if not kind.startswith("LIST<") or not kind.endswith("> NOT NULL"):
            return False
        expected_items = cast(list[Any], expected)
        values = graph.unpack(value)
        subtype = kind.removeprefix("LIST<").removesuffix("> NOT NULL")
        return len(values) == len(expected_items) and all(
            typed_json_matches(item, [subtype, encoded])
            for item, encoded in zip(expected_items, values, strict=True)
        )
    return False


def require_properties(expected: dict[str, Any], signature: str) -> None:
    values = graph.properties(signature)
    present = {key: value for key, value in expected.items() if value is not None}
    if set(present) != set(values) or any(
        not typed_json_matches(value, values[key]) for key, value in present.items()
    ):
        raise RuntimeError("Graph typed properties differ from immutable PostgreSQL inventory")


def copy_inventory(pg: str, query: str, output: Path) -> Iterator[tuple[dict[str, Any], str]]:
    """One bounded-memory COPY per inventory, never repeated global scans."""
    log = output.with_suffix(".stderr")
    with output.open("xb") as rows, log.open("xb") as errors:
        status = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                pg,
                "psql",
                "-X",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                PG_DATABASE,
            ],
            input=(
                "BEGIN READ ONLY; SET LOCAL statement_timeout='300s'; COPY ("
                + query
                + ") TO STDOUT WITH(FORMAT CSV); COMMIT;"
            ).encode(),
            stdout=rows,
            stderr=errors,
            check=False,
        )
    output.chmod(0o600)
    log.chmod(0o600)
    if status.returncode:
        raise RuntimeError("PostgreSQL flat inventory export failed; inspect protected log")
    with output.open(encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) != 1:
                raise RuntimeError("Invalid protected PostgreSQL inventory framing")
            yield json.loads(row[0], parse_float=Decimal), row[0]


def capture_legacy_inventory(pg: str, release: str, directory: Path) -> dict[str, Any]:
    dates.exact_identity(release)
    path = directory / "legacy-inventory.sqlite"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    db = sqlite3.connect(path)
    counts: dict[str, int] = {}
    try:
        for table, key in (("graph_node", "node_id"), ("graph_edge", "edge_id")):
            db.execute(f"CREATE TABLE {table}(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            count = 0
            query = f"SELECT to_jsonb(q)::text FROM ontology.{table} q WHERE release_id={dates.quote(release)}"  # noqa: E501
            # Retain exact JSON text, including numeric precision, on disk.
            output = directory / (table + ".csv")
            for row, encoded in copy_inventory(pg, query, output):
                db.execute(f"INSERT INTO {table} VALUES(?,?)", (row[key], encoded))
                count += 1
                if count % graph.PAGE_SIZE == 0:
                    db.commit()
            db.commit()
            counts[table] = count
        db.execute(
            "CREATE TABLE legacy_property(owner_type TEXT,owner_id TEXT,payload TEXT,"
            "PRIMARY KEY(owner_type,owner_id))"
        )
        property_query = (
            "SELECT jsonb_build_object('owner_type',p.owner_type,'owner_id',p.owner_id,"
            "'fields',jsonb_agg(to_jsonb(p) ORDER BY p.key,p.ordinal))::text "
            "FROM ontology.graph_property p WHERE p.release_id="
            + dates.quote(release)
            + " AND ((p.owner_type='NODE' AND (p.owner_id LIKE 'revision/%' OR p.owner_id LIKE 'entity/%')) OR "  # noqa: E501
            "(p.owner_type='EDGE' AND EXISTS(SELECT 1 FROM ontology.graph_edge e "
            "WHERE e.release_id=p.release_id AND e.edge_id=p.owner_id AND "
            "(e.subject_id LIKE 'revision/%' OR e.object_id LIKE 'revision/%')))) "
            "GROUP BY p.owner_type,p.owner_id"
        )
        property_count = 0
        for row, encoded in copy_inventory(pg, property_query, directory / "legacy_property.csv"):
            db.execute(
                "INSERT INTO legacy_property VALUES(?,?,?)",
                (row["owner_type"], row["owner_id"], encoded),
            )
            property_count += 1
            if property_count % graph.PAGE_SIZE == 0:
                db.commit()
        db.commit()
        counts["legacy_property"] = property_count
        if not all(counts.values()):
            raise RuntimeError("Sealed legacy ontology inventory is empty")
    finally:
        db.close()
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest, "counts": counts, "release_id": release}


def inventory_row(db: sqlite3.Connection, table: str, identity: str) -> dict[str, Any]:
    if table not in ("graph_node", "graph_edge", "flat_graph_node", "flat_graph_edge"):
        raise ValueError("Unexpected inventory table")
    row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise RuntimeError("Graph object has no immutable PostgreSQL inventory backing")
    return json.loads(row[0], parse_float=Decimal)


def native_value_matches(field: dict[str, Any], actual: list[str]) -> bool:
    """The established ontology.graph_property/native CASE rendering contract."""
    kind, value = actual
    source_type, expected = field["value_type"], field["text_value"]
    if source_type == "integer":
        return kind == "INTEGER NOT NULL" and Decimal(value) == Decimal(expected)
    if source_type == "number":
        # Hop's established renderer explicitly calls toFloat: retain raw PG
        # decimals in the archive, compare the exact native binary64 value.
        return (
            kind == "FLOAT NOT NULL"
            and math.isfinite(float(expected))
            and float(value) == float(expected)
        )
    if source_type == "boolean":
        return kind == "BOOLEAN NOT NULL" and value == expected
    if source_type == "string":
        return kind == "STRING NOT NULL" and value == (expected or "")
    if source_type == "date":
        return kind == "DATE NOT NULL" and value == expected
    if source_type == "datetime":
        if kind != "ZONED DATETIME NOT NULL" or "[" in value or "[" in expected:
            return kind == "ZONED DATETIME NOT NULL" and value == expected

        def nanoseconds(text: str) -> str:
            match = re.search(r"T\d{2}:\d{2}(?::\d{2})?(?:\.(\d+))?", text)
            if match is None:
                raise RuntimeError("Invalid native ontology datetime text")
            return (match.group(1) or "").ljust(9, "0")

        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            == datetime.fromisoformat(expected.replace("Z", "+00:00"))
            and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset()
            == datetime.fromisoformat(expected.replace("Z", "+00:00")).utcoffset()
            and nanoseconds(value) == nanoseconds(expected)
        )
    raise RuntimeError("Unsupported native ontology property rendering type")


def require_native_properties(
    db: sqlite3.Connection,
    owner_type: str,
    owner_id: str,
    signature: str,
    extra: dict[str, Any],
    table: str = "legacy_property",
    *,
    partial: bool = False,
    array_prefix: bool = False,
) -> None:
    if array_prefix and (not partial or table != "flat_property" or owner_type != "EDGE"):
        raise ValueError("Partial arrays are restricted to new flat edge proof")
    if table not in ("legacy_property", "flat_property"):
        raise ValueError("Unexpected property proof table")
    row = db.execute(
        f"SELECT payload FROM {table} WHERE owner_type=? AND owner_id=?", (owner_type, owner_id)
    ).fetchone()
    fields: dict[str, list[dict[str, Any]]] = {}
    if row is not None:
        for field in json.loads(row[0], parse_float=Decimal)["fields"]:
            if field["value_type"] != "null":
                fields.setdefault(field["key"], []).append(field)
    actual = graph.properties(signature)
    expected_keys = set(fields) | set(extra)
    if (not partial and set(actual) != expected_keys) or not set(actual) <= expected_keys:
        raise RuntimeError("Native ontology property key inventory differs")
    if any(not typed_json_matches(value, actual[key]) for key, value in extra.items()):
        raise RuntimeError("Native ontology identity property differs")
    for key, values in fields.items():
        if partial and key not in actual:
            continue
        kind, value = actual[key]
        if values[0]["is_array"]:
            if not kind.startswith("LIST<") or not kind.endswith("> NOT NULL"):
                raise RuntimeError("Native ontology array type differs")
            parts = graph.unpack(value)
            expected_size = values[0]["array_size"]
            if len(parts) > expected_size or (not array_prefix and len(parts) != expected_size):
                raise RuntimeError("Native ontology array cardinality differs")
            if expected_size == 0:
                continue
            subtype = kind.removeprefix("LIST<").removesuffix("> NOT NULL")
            if len(values) != expected_size or any(
                field["ordinal"] != ordinal or not native_value_matches(field, [subtype, part])
                for ordinal, (field, part) in enumerate(
                    zip(values[: len(parts)] if array_prefix else values, parts, strict=True)
                )
            ):
                raise RuntimeError("Native ontology array value/type differs")
        elif len(values) != 1 or not native_value_matches(values[0], actual[key]):
            raise RuntimeError("Native ontology scalar value/type differs")


def prove_legacy_backing(snapshot: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    path = Path(evidence["path"])
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != evidence["sha256"]:
            raise RuntimeError("Legacy inventory archive checksum changed")
    nodes = revision_nodes(snapshot)
    if not nodes:
        raise RuntimeError("Fresh migration baseline contains no revisions")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    graph_db = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    count = 0
    edge_ids: set[str] = set()
    try:
        for node in nodes.values():
            props = graph.properties(node[-1])
            identity = graph.text_property(props, "id")
            expected = inventory_row(db, "graph_node", identity)
            if set(graph.unpack(node[1])) != set(expected["labels"]) | {"ontologyObject"}:
                raise RuntimeError("Revision labels differ from sealed inventory")
            require_native_properties(
                db,
                "NODE",
                identity,
                node[-1],
                {"id": identity, "content_hash": expected["content_hash"]},
            )
        for edge in graph.records(snapshot, "REL"):
            if edge[1] not in nodes and edge[2] not in nodes:
                continue
            props = graph.properties(edge[-1])
            identity = graph.text_property(props, "id")
            if identity in edge_ids:
                raise RuntimeError("Duplicate revision relationship stable ID")
            edge_ids.add(identity)
            expected = inventory_row(db, "graph_edge", identity)
            if expected["release_id"] != evidence["release_id"] or edge[3] != expected["predicate"]:
                raise RuntimeError("Unexpected revision relationship release or type")
            for eid, field in ((edge[1], "subject_id"), (edge[2], "object_id")):
                row = graph_db.execute(
                    "SELECT payload FROM snapshot WHERE kind='NODE' AND eid=?", (eid,)
                ).fetchone()
                if (
                    row is None
                    or graph.text_property(graph.properties(graph.unpack(row[0])[-1]), "id")
                    != expected[field]
                ):
                    raise RuntimeError(
                        "Revision relationship endpoint differs from sealed inventory"
                    )
            require_native_properties(
                db,
                "EDGE",
                identity,
                edge[-1],
                {
                    "id": identity,
                    "release_id": expected["release_id"],
                    "content_hash": expected["content_hash"],
                },
            )
            count += 1
        expected_nodes = {
            row[0] for row in db.execute("SELECT id FROM graph_node WHERE id LIKE 'revision/%'")
        }
        actual_nodes = {
            graph.text_property(graph.properties(node[-1]), "id") for node in nodes.values()
        }
        if actual_nodes != expected_nodes:
            raise RuntimeError("Legacy revision graph scope differs from sealed inventory")
        expected_edges = {
            row[0]
            for row in db.execute(
                "SELECT id FROM graph_edge WHERE json_extract(payload,'$.subject_id') LIKE 'revision/%' OR json_extract(payload,'$.object_id') LIKE 'revision/%'"  # noqa: E501
            )
        }
        if edge_ids != expected_edges:
            raise RuntimeError("Legacy revision attachments are missing or unaccounted")
        return {
            "revision_nodes": len(nodes),
            "revision_edges": count,
            "release_id": evidence["release_id"],
        }
    finally:
        db.close()
        graph_db.close()


def baseline_preconditions(snapshot: Path, inventory: dict[str, Any]) -> None:
    proof = checked_inventory(inventory)
    db = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    db.execute("CREATE TEMP TABLE identities(kind TEXT,id TEXT,PRIMARY KEY(kind,id))")
    try:
        for kind in ("NODE", "REL"):
            for row in graph.records(snapshot, kind):
                props = graph.properties(row[-1])
                if "id" not in props:
                    continue
                identity = graph.text_property(props, "id")
                try:
                    db.execute("INSERT INTO identities VALUES(?,?)", (kind, identity))
                except sqlite3.IntegrityError as error:
                    raise RuntimeError("Baseline graph stable IDs are not unique") from error
                if kind == "NODE" and "ontologyEntity" in graph.unpack(row[1]):
                    expected = inventory_row(proof, "graph_node", identity)
                    if set(graph.unpack(row[1])) != set(expected["labels"]) | {"ontologyObject"}:
                        raise RuntimeError("Baseline canonical labels differ from sealed catalogue")
                    require_native_properties(
                        proof,
                        "NODE",
                        identity,
                        row[-1],
                        {
                            "id": identity,
                            "content_hash": expected["content_hash"],
                        },
                    )
    finally:
        proof.close()
        db.close()


def all_old_tables(pg: str) -> dict[str, Any]:
    return deployment.full_preservation_state(pg)


def require_old_tables(before: dict[str, Any], after: dict[str, Any]) -> None:
    if any(after.get(name) != fingerprint for name, fingerprint in before.items()):
        raise RuntimeError("Pre-existing PostgreSQL table rows changed during ontology flattening")


def export_fingerprint(pg: str, release: str, name: str) -> dict[str, Any]:
    """Preserve old serializer success or its narrowly known version refusal."""
    if name not in ("export_jsonld", "export_jsonld_v1", "export_jsonld_v2", "export_jsonld_v3"):
        raise RuntimeError("Unexpected catalogue export serializer")
    query = (
        "BEGIN READ ONLY; SET LOCAL statement_timeout='300s'; SELECT "
        "jsonb_build_object('rows',count(*),'digest',md5(coalesce("
        "string_agg(md5(line::text),'' ORDER BY line_no),''))) FROM ontology."
        + name
        + "("
        + dates.quote(release)
        + ",true); COMMIT;"
    )
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "VERBOSITY=verbose",
            "-U",
            "postgres",
            "-d",
            PG_DATABASE,
        ],
        input=query.encode(),
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        value: dict[str, Any] = json.loads(result.stdout.decode().strip())
        return {"status": "SUCCESS", **value}
    errors = re.findall(
        r"^ERROR:\s+([A-Z0-9]{5}):\s+([A-Z_]+)\s*$",
        result.stderr.decode(errors="replace"),
        re.MULTILINE,
    )
    allowed = {"INTERCHANGE_UNMAPPED_NODE_LABEL", "INTERCHANGE_UNMAPPED_PREDICATE"}
    if len(errors) == 1 and errors[0][0] == "P0001" and errors[0][1] in allowed:
        if name == "export_jsonld_v3":
            raise RuntimeError("Latest catalogue export must succeed")
        return {"status": "CONTRACT_REFUSED", "sqlstate": errors[0][0], "reason": errors[0][1]}
    raise RuntimeError("Catalogue export failed outside its known historical version contract")


def catalogue_baseline(pg: str, release: str) -> dict[str, Any]:
    dates.exact_identity(release)
    row = json.loads(
        deployment.sql(
            pg,
            "BEGIN READ ONLY; SELECT jsonb_build_object("
            "'context',catalog.catalog_context_v1(" + dates.quote(release) + "),"
            "'summary',catalog.catalog_summary_v1(" + dates.quote(release) + "),"
            "'approval',(SELECT to_jsonb(a) FROM "
            "catalog.catalog_active_release p JOIN catalog.catalog_approval a "
            "USING(approval_id) WHERE p.singleton),"
            "'legacy_load',(SELECT to_jsonb(l) FROM ontology.graph_load l JOIN catalog.catalog_approval a USING(load_id) JOIN catalog.catalog_active_release p USING(approval_id) WHERE p.singleton),"  # noqa: E501
            "'release',(SELECT to_jsonb(r) FROM ontology.corpus_release r WHERE release_id="
            + dates.quote(release)
            + ")); COMMIT;",
        )
    )
    if row["approval"]["release_id"] != release or row["release"]["manifest"] is None:
        raise RuntimeError("Exact approved sealed source-only catalogue required")
    if row["release"]["manifest"].get("mode") != "SOURCE_ONLY":
        # Source-only mode may be nested in the immutable catalogue attestation;
        # do not infer it merely from a release name or empty serving pointer.
        mode = deployment.sql(
            pg,
            "BEGIN READ ONLY; SELECT mode FROM catalog.integrity_attestation WHERE release_id="
            + dates.quote(release)
            + "; COMMIT;",
        )
        if mode != "SOURCE_ONLY":
            raise RuntimeError("Approved catalogue is not exactly SOURCE_ONLY")
    exports: dict[str, Any] = {}
    for name in ("export_jsonld", "export_jsonld_v1", "export_jsonld_v2", "export_jsonld_v3"):
        present = deployment.sql(
            pg, f"SELECT to_regprocedure('ontology.{name}(text,boolean)') IS NOT NULL"
        )
        if present == "t":
            exports[name] = export_fingerprint(pg, release, name)
    if exports.get("export_jsonld_v3", {}).get("status") != "SUCCESS":
        raise RuntimeError("Latest catalogue export must exist and succeed")
    row["exports"] = exports
    return row


def install_workflow(path: Path) -> None:
    """Generate the focused SQL installer without replaying legacy migrations."""
    original = graph.MIGRATION_SQL
    try:
        graph.MIGRATION_SQL = MIGRATION_SQL
        graph.install_workflow(path)
    finally:
        graph.MIGRATION_SQL = original


def install_adapter(directory: Path, planned_hash: str) -> dict[str, Any]:
    before = common.host_bytes()
    desired = (common.ROOT / "operations/refresh.sh").read_bytes()
    prior = desired.replace(FENCE_COMMENT.encode(), b"").replace(FENCE_LINE.encode(), b"")
    if before not in (desired, prior) or desired.count(FENCE_LINE.encode()) != 1:
        raise RuntimeError("Host scheduler adapter differs beyond the exact ontology guard")
    if common.digest(before) not in (planned_hash, common.digest(desired)):
        raise RuntimeError("Host scheduler adapter changed since reviewed plan")
    backup = directory / "host-refresh-before.sh"
    backup.write_bytes(before)
    backup.chmod(0o600)
    if before != desired:
        target = common.ADAPTER
        temp = target.parent / (".flat-ontology-refresh-" + uuid.uuid4().hex)
        try:
            with temp.open("xb") as handle:
                handle.write(desired)
            temp.chmod(target.stat().st_mode & 0o777)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    if common.host_bytes() != desired:
        raise RuntimeError("Flat ontology scheduler fence deployment failed")
    return {
        "before_sha256": common.digest(before),
        "after_sha256": common.digest(desired),
        "backup": str(backup),
    }


def execute_statements(hop: str, recovery: dict[str, Any], directory: Path, prefix: str) -> int:
    path = Path(recovery["path"])
    if checksum(path) != recovery["sha256"]:
        raise RuntimeError("Typed ontology recovery checksum changed")

    def statements() -> Iterator[str]:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.endswith("\n"):
                    raise RuntimeError("Truncated typed ontology recovery export")
                yield json.loads(line)["cypher"]

    count = native_statement_stream(hop, statements(), directory, prefix)
    if count != recovery["statements"]:
        raise RuntimeError("Typed recovery statement count changed")
    return count


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture_flat_inventory(pg: str, release: str, directory: Path) -> dict[str, Any]:
    path = directory / "flat-inventory.sqlite"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    db = sqlite3.connect(path)
    counts: dict[str, int] = {}
    try:
        for table, key in (("flat_graph_node", "node_id"), ("flat_graph_edge", "edge_id")):
            db.execute(f"CREATE TABLE {table}(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            count = 0
            query = f"SELECT to_jsonb(q)::text FROM ontology.{table} q WHERE release_id={dates.quote(release)}"  # noqa: E501
            for row, encoded in copy_inventory(pg, query, directory / (table + ".csv")):
                db.execute(f"INSERT INTO {table} VALUES(?,?)", (row[key], encoded))
                count += 1
                if count % graph.PAGE_SIZE == 0:
                    db.commit()
            db.commit()
            counts[table] = count
        db.execute(
            "CREATE TABLE flat_property(owner_type TEXT,owner_id TEXT,payload TEXT,PRIMARY KEY(owner_type,owner_id))"  # noqa: E501
        )
        query = (
            "SELECT jsonb_build_object('owner_type',p.owner_type,'owner_id',p.owner_id,"
            "'fields',jsonb_agg(to_jsonb(p) ORDER BY p.key,p.ordinal))::text "
            "FROM ontology.flat_graph_property p WHERE p.release_id="
            + dates.quote(release)
            + " GROUP BY p.owner_type,p.owner_id"
        )
        for row, encoded in copy_inventory(pg, query, directory / "flat_property.csv"):
            db.execute(
                "INSERT INTO flat_property VALUES(?,?,?)",
                (row["owner_type"], row["owner_id"], encoded),
            )
        db.commit()
        if not all(counts.values()):
            raise RuntimeError("Sealed flat projection inventory is empty")
    finally:
        db.close()
    return {"path": str(path), "sha256": checksum(path), "counts": counts, "release_id": release}


def checked_inventory(evidence: dict[str, Any]) -> sqlite3.Connection:
    path = Path(evidence["path"])
    if path.is_symlink() or path.stat().st_mode & 0o077 or checksum(path) != evidence["sha256"]:
        raise RuntimeError("Protected projection inventory checksum or permissions changed")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def require_flat_preserved(
    before: Path,
    after: Path,
    flat: dict[str, Any],
    *,
    removed: bool | None,
    partial_new_edge_properties: bool = False,
) -> dict[str, int]:
    """Every permitted delta is grounded in the sealed flat inventory, by stable ID.

    Unaffected node/edge element IDs and complete typed signatures stay exact.
    Canonical shell identity fields stay exact; their complete resulting property
    set must match PG typed rendering, including the owned-field proof metadata.
    """
    if partial_new_edge_properties and removed is not False:
        raise ValueError("Partial flat edge proof requires every original revision intact")
    legacy = revision_nodes(before)
    current = sqlite3.connect(f"file:{after}?mode=ro", uri=True)
    proof = checked_inventory(flat)
    current.execute("CREATE TEMP TABLE seen(kind TEXT,eid TEXT,PRIMARY KEY(kind,eid))")
    current.execute("CREATE TEMP TABLE stable(id TEXT PRIMARY KEY,eid TEXT)")
    current.execute("CREATE TEMP TABLE edge_stable(id TEXT PRIMARY KEY,payload TEXT)")
    canonical_count = 0
    new_edges = 0
    legacy_edges = 0

    def stable_id(identity: str) -> str | None:
        row = current.execute("SELECT eid FROM stable WHERE id=?", (identity,)).fetchone()
        return row[0] if row else None

    try:
        for node in graph.records(after, "NODE"):
            props = graph.properties(node[-1])
            if "id" in props:
                identity = graph.text_property(props, "id")
                try:
                    current.execute("INSERT INTO stable VALUES(?,?)", (identity, node[0]))
                except sqlite3.IntegrityError as error:
                    raise RuntimeError("Duplicate stable graph node ID") from error
        for node in graph.records(before, "NODE"):
            row = current.execute(
                "SELECT payload FROM snapshot WHERE kind='NODE' AND eid=?", (node[0],)
            ).fetchone()
            if node[0] in legacy:
                if removed:
                    if row is not None:
                        raise RuntimeError("Revision remains after removal")
                elif (row is None and removed is False) or (
                    row is not None and graph.unpack(row[0]) != node
                ):
                    raise RuntimeError("Accounted legacy revision changed before removal")
                if row:
                    current.execute("INSERT INTO seen VALUES('NODE',?)", (node[0],))
                continue
            if row is None:
                raise RuntimeError("Pre-existing nonrevision node element ID disappeared")
            actual = graph.unpack(row[0])
            current.execute("INSERT INTO seen VALUES('NODE',?)", (node[0],))
            if actual[1] != node[1]:
                raise RuntimeError("Pre-existing nonrevision labels changed")
            if "ontologyEntity" not in graph.unpack(node[1]):
                if actual != node:
                    raise RuntimeError("Unaffected noncanonical node changed")
                continue
            baseline_props = graph.properties(node[-1])
            identity = graph.text_property(baseline_props, "id")
            expected = inventory_row(proof, "flat_graph_node", identity)
            if set(expected["labels"]) | {"ontologyObject"} != set(graph.unpack(node[1])):
                raise RuntimeError("Canonical labels differ from flat proof")
            actual_props = graph.properties(actual[-1])
            if any(
                actual_props.get(k) != v for k, v in baseline_props.items() if k in IDENTITY_KEYS
            ):
                raise RuntimeError("Canonical shell identity changed")
            require_native_properties(
                proof,
                "NODE",
                identity,
                actual[-1],
                {
                    "id": identity,
                    "content_hash": expected["content_hash"],
                    "flat_content_hash": expected["flat_content_hash"],
                    "flat_owned_keys": sorted(expected["owned_properties"]),
                },
                "flat_property",
            )
            canonical_count += 1
        for edge in graph.records(before, "REL"):
            incident = edge[1] in legacy or edge[2] in legacy
            row = current.execute(
                "SELECT payload FROM snapshot WHERE kind='REL' AND eid=?", (edge[0],)
            ).fetchone()
            if incident:
                legacy_edges += 1
                if removed:
                    if row is not None:
                        actual_edge = graph.unpack(row[0])
                        if graph.properties(actual_edge[-1]).get("id") == graph.properties(
                            edge[-1]
                        ).get("id"):
                            raise RuntimeError(
                                "Accounted legacy relationship remains after removal"
                            )
                        # Neo4j may reuse a deleted relationship's internal ID.
                        # This replacement remains unseen so the sealed flat
                        # addition proof below must independently account for it.
                elif row is not None and graph.unpack(row[0]) != edge:
                    raise RuntimeError("Accounted legacy relationship changed before removal")
                elif row is None and (
                    removed is False
                    or all(
                        current.execute(
                            "SELECT 1 FROM snapshot WHERE kind='NODE' AND eid=?", (eid,)
                        ).fetchone()
                        for eid in edge[1:3]
                    )
                ):
                    raise RuntimeError("Legacy edge disappeared while both endpoints remain")
            elif row is None or graph.unpack(row[0]) != edge:
                raise RuntimeError("Pre-existing unaffected relationship changed")
            if row and (not incident or not removed):
                current.execute("INSERT INTO seen VALUES('REL',?)", (edge[0],))
        for kind, payload in current.execute(
            "SELECT s.kind,s.payload FROM snapshot s LEFT JOIN seen x USING(kind,eid) WHERE x.eid IS NULL"  # noqa: E501
        ):
            row = graph.unpack(payload)
            if kind != "REL":
                raise RuntimeError("Flat migration added an unaccounted graph node")
            props = graph.properties(row[-1])
            identity = graph.text_property(props, "id")
            expected = inventory_row(proof, "flat_graph_edge", identity)
            if expected["origin_edge_id"] == identity or row[3] != expected["predicate"]:
                raise RuntimeError("Added edge is not an accounted rerouted ontology relationship")
            if (
                stable_id(expected["subject_id"]) != row[1]
                or stable_id(expected["object_id"]) != row[2]
            ):
                raise RuntimeError("Rerouted relationship endpoints differ from sealed proof")
            require_native_properties(
                proof,
                "EDGE",
                identity,
                row[-1],
                {
                    "id": identity,
                    "release_id": flat["release_id"],
                    "content_hash": expected["content_hash"],
                },
                "flat_property",
                partial=partial_new_edge_properties,
                array_prefix=partial_new_edge_properties,
            )
            new_edges += 1
        # Presence and exact typed rendering of every expected flat edge is
        # independently checked; merely permitting expected additions is weaker.
        for edge in graph.records(after, "REL"):
            props = graph.properties(edge[-1])
            if "id" in props:
                identity = graph.text_property(props, "id")
                try:
                    current.execute(
                        "INSERT INTO edge_stable VALUES(?,?)",
                        (identity, "".join(str(len(v)) + ":" + v for v in edge)),
                    )
                except sqlite3.IntegrityError as error:
                    raise RuntimeError("Duplicate stable graph relationship ID") from error
        for identity, encoded in proof.execute("SELECT id,payload FROM flat_graph_edge"):
            expected = json.loads(encoded, parse_float=Decimal)
            actual_row = current.execute(
                "SELECT payload FROM edge_stable WHERE id=?", (identity,)
            ).fetchone()
            edge = graph.unpack(actual_row[0]) if actual_row else None
            if (
                edge is None
                or edge[3] != expected["predicate"]
                or edge[1:3]
                != [stable_id(expected["subject_id"]), stable_id(expected["object_id"])]
            ):
                raise RuntimeError(
                    "Expected flat relationship is missing or has wrong endpoints/type"
                )
            require_native_properties(
                proof,
                "EDGE",
                identity,
                edge[-1],
                {
                    "id": identity,
                    "release_id": flat["release_id"],
                    "content_hash": expected["content_hash"],
                },
                "flat_property",
                partial=partial_new_edge_properties and expected["origin_edge_id"] != identity,
                array_prefix=partial_new_edge_properties and expected["origin_edge_id"] != identity,
            )
        if removed and revision_nodes(after):
            raise RuntimeError("Unaccounted revision nodes remain")
        return {
            "canonical_nodes": canonical_count,
            "revision_nodes": len(legacy),
            "legacy_edges": legacy_edges,
            "rerouted_edges": new_edges,
        }
    finally:
        current.close()
        proof.close()


def prepare_recovery(snapshot: Path, directory: Path) -> dict[str, Any]:
    nodes = revision_nodes(snapshot)
    output = directory / "flat-recovery.cypher.ndjson"
    count = 0
    with output.open("x", encoding="utf-8") as stream:

        def emit(query: str) -> None:
            nonlocal count
            stream.write(json.dumps({"cypher": query}, ensure_ascii=False) + "\n")
            count += 1

        for node in graph.records(snapshot, "NODE"):
            if node[0] in nodes:
                identity = graph.text_property(graph.properties(node[-1]), "id")
                labels = "".join(":" + label for label in graph.unpack(node[1]))
                emit(
                    f"MERGE(n:ontologyObject {{id:{graph.cypher_string(identity)}}}) SET n{labels} SET n={graph.property_map(node[-1])} RETURN 'OK' AS signature"  # noqa: E501
                )
            elif "ontologyEntity" in graph.unpack(node[1]):
                emit(
                    f"MATCH(n) WHERE elementId(n)={graph.cypher_string(node[0])} SET n={graph.property_map(node[-1])} RETURN 'OK' AS signature"  # noqa: E501
                )
        for edge in graph.records(snapshot, "REL"):
            if edge[1] not in nodes and edge[2] not in nodes:
                continue
            matches: list[str] = []
            for variable, eid in (("a", edge[1]), ("b", edge[2])):
                if eid in nodes:
                    identity = graph.text_property(graph.properties(nodes[eid][-1]), "id")
                    matches.append(
                        f"MATCH({variable}:ontologyObject {{id:{graph.cypher_string(identity)}}})"
                    )
                else:
                    matches.append(
                        f"MATCH({variable}) WHERE elementId({variable})={graph.cypher_string(eid)}"
                    )
            if not re.fullmatch("[A-Za-z_][A-Za-z_0-9]*", edge[3]):
                raise RuntimeError("Unsafe recovery relationship type")
            identity = graph.text_property(graph.properties(edge[-1]), "id")
            emit(
                " ".join(matches)
                + f" MERGE(a)-[r:{edge[3]} {{id:{graph.cypher_string(identity)}}}]->(b) SET r={graph.property_map(edge[-1])} RETURN 'OK' AS signature"  # noqa: E501
            )
    output.chmod(0o600)
    return {
        "path": str(output),
        "sha256": checksum(output),
        "statements": count,
        "mode": "IN_PLACE_TYPED_RECOVERY_NEW_REVISION_ELEMENT_IDS",
    }


def deletion_queries(snapshot: Path) -> Iterator[str]:
    """Explicit incident-edge removal with exact same-transaction drift guards."""
    nodes = revision_nodes(snapshot)
    db = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    db.execute("CREATE TEMP TABLE incident(eid TEXT,start TEXT,end TEXT,payload TEXT)")
    for edge in graph.records(snapshot, "REL"):
        if edge[1] in nodes or edge[2] in nodes:
            db.execute(
                "INSERT INTO incident VALUES(?,?,?,?)",
                (edge[0], edge[1], edge[2], "".join(str(len(v)) + ":" + v for v in edge)),
            )
    db.execute("CREATE INDEX incident_start ON incident(start)")
    db.execute("CREATE INDEX incident_end ON incident(end)")
    try:
        for node in nodes.values():
            edges = [
                graph.unpack(row[0])
                for row in db.execute(
                    "SELECT payload FROM incident WHERE start=? OR end=? ORDER BY eid",
                    (node[0], node[0]),
                )
            ]
            if len(edges) > 25000:
                raise RuntimeError("A revision exceeds bounded incident-edge removal scope")
            expected = [[edge[0], edge[1], edge[2], edge[3], edge[-1]] for edge in edges]
            nsignature = dates.signature_expression("n", "[]")
            rsignature = dates.signature_expression("r", "[]")
            yield (
                f"MATCH(n) WHERE elementId(n)={graph.cypher_string(node[0])}\n"
                + nsignature
                + "\nWITH n,property_signature AS ns\n"
                "CALL(n) { OPTIONAL MATCH(n)-[r]-(x) WITH DISTINCT n,r WHERE r IS NOT NULL\n"
                + rsignature
                + "\nWITH r,property_signature ORDER BY elementId(r)\n"
                "RETURN collect(r) AS rels,collect([elementId(r),elementId(startNode(r)),elementId(endNode(r)),type(r),property_signature]) AS es }\n"  # noqa: E501
                + f"WITH n,rels,ns={graph.cypher_string(node[-1])} AND "
                + f"size(labels(n))={len(graph.unpack(node[1]))} AND all(l IN labels(n) WHERE l IN {json.dumps(graph.unpack(node[1]))}) "  # noqa: E501
                + f"AND es={json.dumps(expected, ensure_ascii=False)} AS safe\n"
                "FOREACH(r IN CASE WHEN safe THEN rels ELSE [] END | DELETE r)\n"
                "FOREACH(x IN CASE WHEN safe THEN [n] ELSE [] END | DELETE x)\n"
                "RETURN CASE WHEN safe THEN 'OK' ELSE 'BLOCKED' END AS signature"
            )
            db.execute("DELETE FROM incident WHERE start=? OR end=?", (node[0], node[0]))
    finally:
        db.close()


def remove_revisions(hop: str, snapshot: Path, directory: Path) -> int:
    return native_statement_stream(hop, deletion_queries(snapshot), directory, "revision-delete")


def native_statement_stream(
    hop: str, statements: Iterator[str], directory: Path, prefix: str
) -> int:
    """Stream private query CSV in one native process, one bounded transaction/query.

    A query removes one exact revision plus at most 25,000 proven attachments,
    or restores one object. Partial completion is replayable from a fresh typed
    remaining-scope snapshot; the immutable intent and output remain on disk.
    """
    remote = "/tmp/flat-ontology-" + uuid.uuid4().hex
    csv_path = directory / (prefix + "-queries.csv")
    count = 0
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["query"])
        for query in statements:
            writer.writerow([query])
            count += 1
    csv_path.chmod(0o600)
    if not count:
        return 0
    common.write_json(
        directory / (prefix + "-intent.json"),
        {
            "statements": count,
            "query_csv_sha256": checksum(csv_path),
            "transaction_statements": 1,
        },
    )
    pipeline = directory / (prefix + ".hpl")
    dates.build_snapshot(pipeline, "", remote)
    root = ET.parse(pipeline).getroot()
    seed = next(t for t in root.findall("transform") if t.findtext("type") == "GetVariable")
    csv_template = ET.parse(common.ROOT / "ingestions/ncs_career_path/load_csv.hpl").getroot()
    reader = copy.deepcopy(
        next(t for t in csv_template.findall("transform") if t.findtext("type") == "CsvInput")
    )
    root.remove(seed)
    for key, value in (
        ("name", "Snapshot"),
        ("filename", remote + "-queries.csv"),
        ("encoding", "UTF-8"),
        ("newline_possible", "Y"),
        ("rownum_field", ""),
    ):
        node = reader.find(key)
        assert node is not None
        node.text = value
    fields = reader.find("fields")
    assert fields is not None
    field = copy.deepcopy(fields[0])
    fields.clear()
    field.find("name").text = "query"  # type: ignore[union-attr]
    fields.append(field)
    root.append(reader)
    neo = next(t for t in root.findall("transform") if t.findtext("type") == "Neo4jCypherOutput")
    for key, value in (("read_only", "N"), ("cypher_from_field", "Y"), ("batch_size", "1")):
        neo.find(key).text = value  # type: ignore[union-attr]
    ET.SubElement(neo, "cypher_field").text = "query"
    template = ET.parse(common.ROOT / "graph/verify_records.hpl").getroot()
    check = copy.deepcopy(
        next(t for t in template.findall("transform") if t.findtext("type") == "FilterRows")
    )
    check.find("compare/condition/leftvalue").text = "signature"  # type: ignore[union-attr]
    check.find("compare/condition/value/type").text = "String"  # type: ignore[union-attr]
    check.find("compare/condition/value/text").text = "OK"  # type: ignore[union-attr]
    check.find("send_true_to").text = "Write private snapshot"  # type: ignore[union-attr]
    check.find("send_false_to").text = "Check failed"  # type: ignore[union-attr]
    root.append(check)
    abort = copy.deepcopy(
        next(t for t in template.findall("transform") if t.findtext("type") == "Abort")
    )
    abort.find("message").text = "Flat ontology operation refused; inspect protected receipt."  # type: ignore[union-attr]
    root.append(abort)
    order = root.find("order")
    assert order is not None
    for edge in order.findall("hop"):
        if edge.findtext("from") == "Read graph snapshot":
            edge.find("to").text = "Check result"  # type: ignore[union-attr]
    for target in ("Check failed", "Write private snapshot"):
        edge = ET.SubElement(order, "hop")
        for key, value in (("from", "Check result"), ("to", target), ("enabled", "Y")):
            ET.SubElement(edge, key).text = value
    ET.ElementTree(root).write(pipeline, encoding="utf-8", xml_declaration=True)
    pipeline.chmod(0o600)
    output = directory / (prefix + "-result.csv")
    try:
        common.command(["docker", "cp", str(csv_path), hop + ":" + remote + "-queries.csv"])
        for tool, argument in (("chown", "501:501"), ("chmod", "600")):
            common.command(
                ["docker", "exec", "-u", "root", hop, tool, argument, remote + "-queries.csv"]
            )
        dates.temporary_native(hop, pipeline, directory, prefix)
        common.command(["docker", "cp", hop + ":" + remote + ".csv", str(output)])
        output.chmod(0o600)
        actual = 0
        for result in graph.output_rows(output):
            if result != "OK":
                raise RuntimeError("Native typed operation gate refused")
            actual += 1
        if actual != count:
            raise RuntimeError("Native typed operation did not cover every intended object")
        common.write_json(
            directory / (prefix + "-applied.json"), {"statements": actual, "status": "APPLIED"}
        )
        return actual
    finally:
        if not output.exists():
            try:
                common.command(["docker", "cp", hop + ":" + remote + ".csv", str(output)])
                output.chmod(0o600)
                observed = sum(1 for row in graph.output_rows(output) if row == "OK")
                common.write_json(
                    directory / (prefix + "-partial-observed.json"),
                    {
                        "status": "FRESH_TYPED_SNAPSHOT_REQUIRED",
                        "observed_success_rows": observed,
                        "intended_statements": count,
                    },
                )
            except RuntimeError:
                if output.exists():
                    output.chmod(0o600)
        common.command(
            [
                "docker",
                "exec",
                "-u",
                "root",
                hop,
                "rm",
                "-f",
                "--",
                remote + "-queries.csv",
                remote + ".csv",
            ]
        )


def require_schema(before: dict[str, Any], after: dict[str, Any]) -> None:
    allowed = {
        name.lower()
        for relative in MIGRATION_SQL
        for name in re.findall(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)\s*\(",
            (common.ROOT / relative).read_text(),
            flags=re.IGNORECASE,
        )
    }
    for category in ("functions", "triggers"):
        for name, digest in before[category].items():
            if after[category].get(name) != digest and not (
                category == "functions" and name.split("(")[0].lower() in allowed
            ):
                raise RuntimeError("Unexpected existing schema change: " + name)


def definition_shape(pg: str) -> dict[str, Any]:
    # Restore omits original ACL/ownership in an isolated clone. Compare exact
    # executable definitions there; live ACL-bearing hashes remain in the plan.
    query = """BEGIN READ ONLY;
SELECT jsonb_build_object(
 'functions',(SELECT coalesce(jsonb_object_agg(p.oid::regprocedure::text,
 encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex')),'{}')
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN('attachment','catalog','cs','enrichment','ingestion','ontology','retention')
 AND p.prokind IN('f','p')),
 'triggers',(SELECT coalesce(jsonb_object_agg(n.nspname||'.'||c.relname||':'||t.tgname,
 encode(sha256(convert_to(pg_get_triggerdef(t.oid)||t.tgenabled::text,'UTF8')),'hex')),'{}')
 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE NOT t.tgisinternal
 AND n.nspname IN('attachment','catalog','cs','enrichment','ingestion','ontology','retention')));
COMMIT;"""
    return json.loads(deployment.sql(pg, query))


def restore_backup(
    runtime: dict[str, str],
    backup: dict[str, Any],
    before: dict[str, Any],
    shape: dict[str, Any],
    directory: Path,
) -> Path:
    """Actual exact-dump restore and every-old-table/definition comparison."""
    import time

    if checksum(Path(backup["path"])) != backup["sha256"]:
        raise RuntimeError("Full PostgreSQL backup checksum changed")
    clone = "jobtology-flat-restore-" + uuid.uuid4().hex[:12]
    receipt: dict[str, Any] = {
        "status": "RUNNING",
        "database_backup_sha256": backup["sha256"],
        "network": "none",
        "production_writes": False,
        "source_requests": 0,
        "paid_calls": 0,
        "container": clone,
    }
    path = directory / "receipt.json"
    common.write_json(path, receipt)
    volumes: list[str] = []
    try:
        common.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                "none",
                "--name",
                clone,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=jobtology",
                "postgres:18-alpine",
            ]
        )
        mounts = json.loads(
            common.command(["docker", "inspect", clone, "--format", "{{json .Mounts}}"])
        )
        volumes = [m["Name"] for m in mounts if m["Type"] == "volume"]
        for _ in range(120):
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    clone,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    "jobtology",
                ],
                capture_output=True,
            )
            if not ready.returncode:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Isolated PostgreSQL restore did not become ready")
        deployment.sql(clone, "CREATE ROLE jobtology_catalog_reader NOLOGIN NOINHERIT;")
        with (
            Path(backup["path"]).open("rb") as source,
            (directory / "restore.log").open("xb") as log,
        ):
            process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-i",
                    clone,
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "-U",
                    "postgres",
                    "-d",
                    "jobtology",
                ],
                stdin=source,
                stdout=log,
                stderr=log,
            )
            while True:
                try:
                    code = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    print("Isolated exact PostgreSQL restore remains active", flush=True)
        if code or all_old_tables(clone) != before or definition_shape(clone) != shape:
            raise RuntimeError(
                "Exact isolated restore differs from locked table/definition baseline"
            )
        receipt.update(
            status="VERIFIED",
            old_tables=before,
            definition_shape=shape,
            restore_options=["--no-owner", "--no-privileges"],
        )
    except BaseException as error:
        receipt.update(
            status="FAILED", failure_type=type(error).__name__, failure_message=str(error)
        )
        raise
    finally:
        subprocess.run(["docker", "rm", "-fv", clone], capture_output=True)
        absent = subprocess.run(["docker", "inspect", clone], capture_output=True).returncode != 0
        removed_volumes = all(
            subprocess.run(["docker", "volume", "inspect", name], capture_output=True).returncode
            != 0
            for name in volumes
        )
        receipt["cleanup_verified"] = absent and removed_volumes
        common.write_json(path, receipt)
        if not receipt["cleanup_verified"]:
            raise RuntimeError(
                "Isolated restore resources require cleanup; stop before live writes"
            )
    return path


def make_plan(
    runtime: dict[str, str],
    directory: Path,
    release: str = DEFAULT_RELEASE,
    preflight: Path | None = None,
) -> Path:
    dates.exact_identity(release)
    prior: dict[str, Any] = json.loads(preflight.read_bytes()) if preflight else {}
    if prior and (
        prior.get("status") != "VERIFIED_FLAT_PREFLIGHT"
        or prior.get("runtime") != runtime
        or prior.get("release_id") != release
    ):
        raise RuntimeError("Exact verified flat preflight/runtime/release required")
    old_tables = all_old_tables(runtime["pg"])
    schema = dates.schema_preservation(runtime["pg"])
    catalogue = catalogue_baseline(runtime["pg"], release)
    if prior and (
        prior["old_tables"] != old_tables
        or prior["schema"] != schema
        or prior["catalogue"] != catalogue
    ):
        raise RuntimeError("Runtime changed since flat preflight")
    before = prior.get("graph") or graph.graph_snapshot(runtime["hop"], directory, "graph-before")
    snapshot = graph.validate_archive(before)
    inventory = prior.get("legacy_inventory") or capture_legacy_inventory(
        runtime["pg"], release, directory
    )
    backing = prove_legacy_backing(snapshot, inventory)
    baseline_preconditions(snapshot, inventory)
    entries, _ = deployment.snapshot(runtime)
    manifest = {
        "version": 1,
        "kind": "FLAT_ONTOLOGY",
        "status": "PLANNED",
        "runtime": runtime,
        "created_at": datetime.now(UTC).isoformat(),
        "release_id": release,
        "old_tables": old_tables,
        "schema": schema,
        "definition_shape": definition_shape(runtime["pg"]),
        "catalogue": catalogue,
        "graph": before,
        "legacy_inventory": inventory,
        "backing": backing,
        "artifacts": entries,
        "host_adapter_sha256": common.digest(common.host_bytes() or b""),
        "database_backup": prior.get("database_backup"),
        "source_requests": 0,
        "paid_calls": 0,
    }
    path = directory / "manifest.json"
    common.write_json(path, manifest)
    return path


def flat_load(pg: str, release: str, database: str) -> dict[str, Any] | None:
    value = deployment.sql(
        pg,
        "SELECT to_jsonb(l) FROM ontology.flat_graph_current c "
        "JOIN ontology.flat_graph_load l USING(load_id) WHERE c.release_id="
        + dates.quote(release)
        + " AND c.database_id="
        + dates.quote(database),
    )
    return json.loads(value) if value else None


def require_load_ownership(
    manifest: dict[str, Any], receipt: dict[str, Any], load: dict[str, Any] | None
) -> None:
    if not load or load["state"] not in ("RUNNING", "STAGED"):
        return
    retained = receipt.get("load")
    if retained:
        if load["load_id"] != retained["load_id"]:
            raise RuntimeError("Current flat checkpoint differs from the retained migration token")
        return
    intent = receipt.get("fresh_stage_intent")
    if (
        not intent
        or intent["release_id"] != manifest["release_id"]
        or intent["database_id"] != manifest["catalogue"]["approval"]["database_id"]
        or load["release_id"] != intent["release_id"]
        or load["database_id"] != intent["database_id"]
        or load["source_manifest_hash"] != intent["source_manifest_hash"]
        or datetime.fromisoformat(load["started_at"]) < datetime.fromisoformat(intent["started_at"])
        or load["load_id"] == intent.get("previous_failed_load_id")
        or (
            intent.get("projection_manifest_hash") is not None
            and load["manifest_hash"] != intent["projection_manifest_hash"]
        )
    ):
        raise RuntimeError("Uncaptured flat token lacks an exact durable fresh-stage intent")


def starting_flat_stage(
    pg: str,
    directory: Path,
    receipt: dict[str, Any],
    manifest: dict[str, Any],
    database: str,
    previous: dict[str, Any] | None,
) -> None:
    if previous and previous["state"] != "FAILED":
        raise RuntimeError("Fresh stage cannot replace a nonfailed flat token")
    intent = {
        "release_id": manifest["release_id"],
        "database_id": database,
        "source_manifest_hash": manifest["catalogue"]["release"]["manifest_hash"],
        "projection_manifest_hash": previous["manifest_hash"] if previous else None,
        "previous_failed_load_id": previous["load_id"] if previous else None,
        "started_at": deployment.sql(pg, "SELECT clock_timestamp()::text"),
    }
    graph.event(
        directory,
        receipt,
        "FLAT_STAGING_STARTING",
        stage_release_id=manifest["release_id"],
        stage_database_id=database,
        fresh_stage_intent=intent,
        previous_failed_load=previous,
        load=None,
    )


def final_checks(
    runtime: dict[str, str],
    manifest: dict[str, Any],
    flat: dict[str, Any],
    directory: Path,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    after = graph.graph_snapshot(runtime["hop"], directory, "graph-final")
    preservation = require_flat_preserved(
        graph.validate_archive(manifest["graph"]), Path(after["path"]), flat, removed=True
    )
    require_old_tables(manifest["old_tables"], all_old_tables(runtime["pg"]))
    require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
    if catalogue_baseline(runtime["pg"], manifest["release_id"]) != manifest["catalogue"]:
        raise RuntimeError("Historical approved catalogue/readers/preview exports changed")
    require_reader_isolation(runtime["pg"])
    require_artifact_binding(runtime, manifest, receipt, deployed=True)
    return {
        "graph_after": after,
        "graph_preservation": preservation,
        "old_table_count": len(manifest["old_tables"]),
        "catalogue_readers_preserved": True,
    }


def require_artifact_binding(
    runtime: dict[str, str],
    manifest: dict[str, Any],
    receipt: dict[str, Any] | None,
    *,
    deployed: bool = False,
) -> None:
    import amend_flat_ontology_stage as successor

    expected = successor.successor_hashes(manifest, receipt or {})
    entries, _ = deployment.snapshot(runtime)
    if set(entries) != set(expected):
        raise RuntimeError("Reviewed runtime artifact closure changed")
    for name, entry in entries.items():
        original = manifest["artifacts"][name]["after"]
        if entry["after"] not in {original, expected[name]}:
            raise RuntimeError("Reviewed desired runtime artifacts changed")
        if deployed and (entry["before"] != expected[name] or entry["after"] != expected[name]):
            raise RuntimeError("Deployed public writer artifacts changed")


def require_reader_isolation(pg: str) -> None:
    names = sorted(
        {
            name.lower()
            for relative in MIGRATION_SQL
            for name in re.findall(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)\s*\(",
                (common.ROOT / relative).read_text(),
                flags=re.IGNORECASE,
            )
        }
    )
    query = "SELECT jsonb_build_object('functions',(SELECT count(*) FROM pg_proc p "
    query += "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname||'.'||p.proname IN ("
    query += ",".join(dates.quote(name) for name in names)
    query += ") AND has_function_privilege('jobtology_catalog_reader',p.oid,'EXECUTE')),"
    query += (
        "'tables',(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
    )
    query += "WHERE n.nspname IN ('ontology','catalog') AND c.relname LIKE 'flat_%' "
    query += "AND c.relkind IN ('r','p') AND has_table_privilege('jobtology_catalog_reader',c.oid,"
    query += "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')))"
    if any(json.loads(deployment.sql(pg, query)).values()):
        raise RuntimeError("Catalogue reader gained flat mutation/function/table access")


def require_staged_tables(pg: str, baseline: dict[str, Any], load: dict[str, Any]) -> None:
    actual = all_old_tables(pg)
    writer = json.loads(
        deployment.sql(
            pg,
            "SELECT to_jsonb(w) FROM retention.writer w WHERE writer_id="
            + dates.quote(load["load_id"]),
        )
    )
    if writer["kind"] != "ONTOLOGY_GRAPH" or writer["target_id"] != load["release_id"]:
        raise RuntimeError("Flat load writer lease differs from exact staged token")
    actual["retention.writer"] = json.loads(
        deployment.sql(
            pg,
            "SELECT jsonb_build_object('count',count(*),'digest',md5(coalesce(string_agg(h,'' ORDER BY h),''))) "  # noqa: E501
            "FROM(SELECT md5(to_jsonb(w)::text) h FROM retention.writer w WHERE writer_id<>"
            + dates.quote(load["load_id"])
            + ") q",
        )
    )
    require_old_tables(baseline, actual)


def apply_plan(
    runtime: dict[str, str],
    manifest_path: Path,
    directory: Path,
    resumed: dict[str, Any] | None = None,
    backup_restore_proof: Path | None = None,
) -> Path:
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("version") != 1
        or manifest.get("kind") != "FLAT_ONTOLOGY"
        or manifest["runtime"] != runtime
    ):
        raise RuntimeError("Flat migration manifest/runtime changed")
    before = graph.validate_archive(manifest["graph"])
    require_artifact_binding(runtime, manifest, resumed)
    receipt = resumed or {
        "version": 1,
        "kind": "FLAT_ONTOLOGY",
        "status": "RUNNING",
        "manifest": str(manifest_path.resolve()),
        "runtime": runtime,
        "token": uuid.uuid4().hex,
        "source_requests": 0,
        "paid_calls": 0,
        "started_at": datetime.now(UTC).isoformat(),
    }
    attempt = directory / ("attempt-" + uuid.uuid4().hex)
    attempt.mkdir(mode=0o700)
    fence = common.STATE / FENCE_NAME
    if fence.exists() and json.loads(fence.read_bytes()).get("token") != receipt["token"]:
        raise RuntimeError("Another migration owns the durable ontology fence")
    try:
        fresh = graph.graph_snapshot(runtime["hop"], attempt, "graph-fresh")
        if not resumed and fresh["sha256"] != manifest["graph"]["sha256"]:
            raise RuntimeError("Graph changed since reviewed flat plan; no live writes")
        if not receipt.get("load") or receipt.get("status") == "RECOVERED_FENCED":
            require_old_tables(manifest["old_tables"], all_old_tables(runtime["pg"]))
        require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
        graph.event(directory, receipt, "FRESHNESS_VERIFIED", fresh_graph=fresh)
        if "database_backup" not in receipt:
            backup = manifest.get("database_backup") or deployment.backup_database(
                runtime["pg"], attempt
            )
            if checksum(Path(backup["path"])) != backup["sha256"]:
                raise RuntimeError("Full PostgreSQL backup checksum changed")
            graph.event(directory, receipt, "DATABASE_BACKUP_VALIDATED", database_backup=backup)
        if "recovery" not in receipt:
            graph.event(
                directory,
                receipt,
                "TYPED_RECOVERY_EXPORTED",
                recovery=prepare_recovery(before, attempt),
            )
        proof_path = backup_restore_proof or (
            Path(receipt["backup_restore_proof"]) if receipt.get("backup_restore_proof") else None
        )
        if proof_path is None:
            restore = attempt / "isolated-restore"
            restore.mkdir(mode=0o700)
            proof_path = restore_backup(
                runtime,
                receipt["database_backup"],
                manifest["old_tables"],
                manifest["definition_shape"],
                restore,
            )
        proof = json.loads(proof_path.read_bytes())
        if (
            proof.get("status") != "VERIFIED"
            or proof.get("database_backup_sha256") != receipt["database_backup"]["sha256"]
            or proof.get("old_tables") != manifest["old_tables"]
            or proof.get("definition_shape") != manifest["definition_shape"]
            or proof.get("cleanup_verified") is not True
        ):
            raise RuntimeError(
                "Exact locked dump/all-old-table/schema isolated restore proof required"
            )
        graph.event(
            directory, receipt, "RESTORE_PROVEN", backup_restore_proof=str(proof_path.resolve())
        )
        if not receipt.get("host_adapter"):
            graph.event(
                directory,
                receipt,
                "SCHEDULER_GUARD_DEPLOYED",
                host_adapter=install_adapter(attempt, manifest["host_adapter_sha256"]),
            )
        if not fence.exists():
            common.write_json(
                fence, {"token": receipt["token"], "receipt": str(directory / "receipt.json")}
            )
        graph.event(directory, receipt, "WRITERS_FENCED")
        if not receipt.get("deployment_receipt"):
            entries, _ = deployment.snapshot(runtime)
            state = common.db_state(runtime["pg"])
            deploy_manifest = attempt / "deployment-manifest.json"
            common.write_json(deploy_manifest, deployment.plan_manifest(runtime, state, entries))
            deployed = deployment.apply(deploy_manifest, runtime, state)
            graph.event(
                directory, receipt, "PUBLIC_WRITERS_DEPLOYED", deployment_receipt=str(deployed)
            )
        else:
            require_artifact_binding(runtime, manifest, receipt, deployed=True)
        if not receipt.get("sql_installed"):
            installer = attempt / "install-focused.hwf"
            install_workflow(installer)
            dates.temporary_native(runtime["hop"], installer, attempt, "install-focused")
            require_old_tables(manifest["old_tables"], all_old_tables(runtime["pg"]))
            require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
            graph.event(directory, receipt, "FOCUSED_SQL_INSTALLED", sql_installed=True)
        database = manifest["catalogue"]["approval"]["database_id"]
        load = flat_load(runtime["pg"], manifest["release_id"], database)
        require_load_ownership(manifest, receipt, load)
        if load and load["state"] == "RUNNING":
            # A failed native stage is never inferred safe from missing receipt.
            raise RuntimeError(
                "Incomplete RUNNING flat load requires protected recovery before retry"
            )
        if load and load["state"] == "VERIFIED" and not receipt.get("post_removal_graph_verified"):
            raise RuntimeError(
                "Verified checkpoint lacks this migration's pre-READY preservation receipt"
            )
        if load and load["state"] == "FAILED":
            require_old_tables(manifest["old_tables"], all_old_tables(runtime["pg"]))
        if load and load["state"] == "FAILED" and not revision_nodes(Path(fresh["path"])):
            if not receipt.get("flat_inventory"):
                raise RuntimeError(
                    "Failed flat reload without exact prior flat proof requires recovery review"
                )
            require_flat_preserved(
                before, Path(fresh["path"]), receipt["flat_inventory"], removed=True
            )
            graph.event(
                directory,
                receipt,
                "FAILED_RELOAD_FLAT_STATE_PROVEN",
                post_removal_graph_verified=True,
                post_removal_graph=fresh,
            )
            dates.native(
                runtime["hop"],
                common.PROJECT + "/ontology/load_release.hwf",
                attempt,
                "retry-strict-flat-reload",
                {"RELEASE_ID": manifest["release_id"], "NEO4J_CONNECTION": "jobtology-neo4j"},
            )
            load = flat_load(runtime["pg"], manifest["release_id"], database)
        if not load or load["state"] == "FAILED":
            starting_flat_stage(runtime["pg"], directory, receipt, manifest, database, load)
            dates.native(
                runtime["hop"],
                common.PROJECT + "/ontology/stage_flat_release.hwf",
                attempt,
                "stage-flat-release",
                {"RELEASE_ID": manifest["release_id"], "NEO4J_CONNECTION": "jobtology-neo4j"},
            )
            load = flat_load(runtime["pg"], manifest["release_id"], database)
        if load is None or load["state"] not in ("STAGED", "VERIFIED"):
            raise RuntimeError("Exact approved projection did not reach a guarded stage")
        graph.event(directory, receipt, "STAGED_TOKEN_CAPTURED", load=load)
        if not receipt.get("flat_inventory"):
            graph.event(
                directory,
                receipt,
                "SEALED_FLAT_INVENTORY_CAPTURED",
                flat_inventory=capture_flat_inventory(
                    runtime["pg"], manifest["release_id"], attempt
                ),
            )
        flat = receipt["flat_inventory"]
        projected = graph.graph_snapshot(runtime["hop"], attempt, "graph-staged")
        remaining = revision_nodes(Path(projected["path"]))
        preservation_before = (
            graph.validate_archive(receipt["recovered_graph"])
            if receipt.get("recovered_graph")
            else before
        )
        require_flat_preserved(
            preservation_before,
            Path(projected["path"]),
            flat,
            removed=True if load["state"] == "VERIFIED" else (False if not resumed else None),
        )
        if load["state"] == "STAGED":
            require_staged_tables(runtime["pg"], manifest["old_tables"], load)
            graph.event(directory, receipt, "ACCOUNTED_REMOVAL_STARTING", staged_graph=projected)
            deletion = attempt / "deletion"
            deletion.mkdir(mode=0o700)
            deleted = remove_revisions(runtime["hop"], Path(projected["path"]), deletion)
            graph.event(
                directory,
                receipt,
                "REVISION_REMOVAL_COMPLETED",
                removed_revision_nodes=deleted,
                attempted_revision_nodes=len(remaining),
            )
            removed_graph = graph.graph_snapshot(
                runtime["hop"], attempt, "graph-removed-before-ready"
            )
            preserved = require_flat_preserved(
                before, Path(removed_graph["path"]), flat, removed=True
            )
            require_staged_tables(runtime["pg"], manifest["old_tables"], load)
            require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
            graph.event(
                directory,
                receipt,
                "POST_REMOVAL_INDEPENDENT_PRESERVATION_VERIFIED",
                post_removal_graph_verified=True,
                post_removal_graph=removed_graph,
                post_removal_preservation=preserved,
            )
            dates.native(
                runtime["hop"],
                common.PROJECT + "/ontology/finalize_flat_release.hwf",
                attempt,
                "finalize-flat-release",
                {"LOAD_ID": load["load_id"], "NEO4J_CONNECTION": "jobtology-neo4j"},
            )
        elif remaining:
            raise RuntimeError("Verified flat checkpoint has unexpected revision remnants")
        graph.event(directory, receipt, "STRICT_FLAT_PROJECTION_VERIFIED")
        # The ordinary exact historical entrypoint now writes the flat contract.
        dates.native(
            runtime["hop"],
            common.PROJECT + "/ontology/load_release.hwf",
            attempt,
            "normal-historical-flat-replay",
            {"RELEASE_ID": manifest["release_id"], "NEO4J_CONNECTION": "jobtology-neo4j"},
        )
        final = final_checks(runtime, manifest, flat, attempt, receipt)
        graph.event(
            directory,
            receipt,
            "VERIFIED",
            status="VERIFIED",
            finished_at=datetime.now(UTC).isoformat(),
            **final,
        )
        if json.loads(fence.read_bytes()).get("token") != receipt["token"]:
            raise RuntimeError("Durable ontology fence ownership changed")
        fence.unlink()
        graph.event(directory, receipt, "SCHEDULER_RESUMED", scheduler_fence_removed=True)
        return directory / "receipt.json"
    except BaseException as error:
        graph.event(
            directory,
            receipt,
            "FAILED_REVIEW_RECEIPT_BEFORE_RETRY",
            status="FAILED",
            failure_type=type(error).__name__,
            failure_message=str(error),
            failure_phase=receipt.get("phase", "FRESHNESS_CHECKING"),
            scheduler_fenced=fence.exists(),
        )
        raise RuntimeError(
            "Flat migration stopped; inspect protected receipt " + str(directory / "receipt.json")
        ) from error


def require_recovered(before: Path, after: Path) -> dict[str, int]:
    """Rollback preserves nonrevision element IDs; restored revisions use stable IDs."""
    revision = revision_nodes(before)
    db = sqlite3.connect(f"file:{after}?mode=ro", uri=True)
    db.execute("CREATE TEMP TABLE actual(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id))")
    try:
        for kind in ("NODE", "REL"):
            for row in graph.records(after, kind):
                props = graph.properties(row[-1])
                if "id" in props:
                    identity = graph.text_property(props, "id")
                    db.execute(
                        "INSERT INTO actual VALUES(?,?,?)",
                        (kind, identity, "".join(str(len(v)) + ":" + v for v in row)),
                    )
        expected_counts: dict[str, int] = {}
        for kind in ("NODE", "REL"):
            count = 0
            for row in graph.records(before, kind):
                count += 1
                if kind == "NODE" and row[0] in revision:
                    identity = graph.text_property(graph.properties(row[-1]), "id")
                    actual = db.execute(
                        "SELECT payload FROM actual WHERE kind='NODE' AND id=?", (identity,)
                    ).fetchone()
                    if actual is None or graph.unpack(actual[0])[1:] != row[1:]:
                        raise RuntimeError(
                            "Typed revision recovery differs from original stable inventory"
                        )
                elif kind == "REL" and (row[1] in revision or row[2] in revision):
                    identity = graph.text_property(graph.properties(row[-1]), "id")
                    actual = db.execute(
                        "SELECT payload FROM actual WHERE kind='REL' AND id=?", (identity,)
                    ).fetchone()
                    if actual is None:
                        raise RuntimeError("Original revision relationship was not recovered")
                    edge = graph.unpack(actual[0])
                    if edge[3:] != row[3:]:
                        raise RuntimeError("Recovered revision edge type/properties differ")
                    for old_eid, new_eid in zip(row[1:3], edge[1:3], strict=True):
                        if old_eid in revision:
                            stable = graph.text_property(
                                graph.properties(revision[old_eid][-1]), "id"
                            )
                            recovered = db.execute(
                                "SELECT payload FROM actual WHERE kind='NODE' AND id=?", (stable,)
                            ).fetchone()
                            if recovered is None or graph.unpack(recovered[0])[0] != new_eid:
                                raise RuntimeError(
                                    "Recovered revision edge stable endpoints differ"
                                )
                        elif old_eid != new_eid:
                            raise RuntimeError("Recovery moved a nonrevision edge endpoint")
                else:
                    actual = db.execute(
                        "SELECT payload FROM snapshot WHERE kind=? AND eid=?", (kind, row[0])
                    ).fetchone()
                    if actual is None or graph.unpack(actual[0]) != row:
                        raise RuntimeError(
                            "Recovery changed an original business node/edge element ID or typed values"  # noqa: E501
                        )
            expected_counts[kind] = count
            if (
                db.execute("SELECT count(*) FROM snapshot WHERE kind=?", (kind,)).fetchone()[0]
                != count
            ):
                raise RuntimeError("Recovery leaves extra or missing graph objects")
        return expected_counts
    finally:
        db.close()


def cleanup_flat_edges(
    snapshot: Path, flat: dict[str, Any], *, partial: bool = False
) -> Iterator[str]:
    proof = checked_inventory(flat)
    archive = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    try:
        for edge in graph.records(snapshot, "REL"):
            props = graph.properties(edge[-1])
            if "id" not in props:
                continue
            identity = graph.text_property(props, "id")
            found = proof.execute(
                "SELECT payload FROM flat_graph_edge WHERE id=?", (identity,)
            ).fetchone()
            if found is None:
                continue
            expected = json.loads(found[0], parse_float=Decimal)
            if expected["origin_edge_id"] == identity:
                continue
            if edge[3] != expected["predicate"]:
                raise RuntimeError("Recovery rerouted edge type differs from sealed proof")
            for eid, field in ((edge[1], "subject_id"), (edge[2], "object_id")):
                endpoint = archive.execute(
                    "SELECT payload FROM snapshot WHERE kind='NODE' AND eid=?", (eid,)
                ).fetchone()
                if (
                    endpoint is None
                    or graph.text_property(graph.properties(graph.unpack(endpoint[0])[-1]), "id")
                    != expected[field]
                ):
                    raise RuntimeError("Recovery rerouted edge endpoints differ from sealed proof")
            require_native_properties(
                proof,
                "EDGE",
                identity,
                edge[-1],
                {
                    "id": identity,
                    "release_id": flat["release_id"],
                    "content_hash": expected["content_hash"],
                },
                "flat_property",
                partial=partial,
            )
            yield (
                f"MATCH(a)-[r]->(b) WHERE elementId(r)={graph.cypher_string(edge[0])}\n"
                + dates.signature_expression("r", "[]")
                + "\nWITH r,a,b,property_signature\n"
                + f"WITH r,property_signature={graph.cypher_string(edge[-1])} "
                + f"AND type(r)={graph.cypher_string(edge[3])} "
                + f"AND elementId(a)={graph.cypher_string(edge[1])} AND elementId(b)={graph.cypher_string(edge[2])} AS safe\n"  # noqa: E501
                + "FOREACH(x IN CASE WHEN safe THEN [r] ELSE [] END | DELETE x) RETURN CASE WHEN safe THEN 'OK' ELSE 'BLOCKED' END AS signature"  # noqa: E501
            )
    finally:
        proof.close()
        archive.close()


def require_rollback_scope(before: Path, current: Path, flat: dict[str, Any]) -> None:
    """Refuse rollback drift before overwriting any owned property or attachment."""
    legacy = revision_nodes(before)
    old = sqlite3.connect(f"file:{before}?mode=ro", uri=True)
    actual = sqlite3.connect(f"file:{current}?mode=ro", uri=True)
    proof = checked_inventory(flat)
    old.execute("CREATE TEMP TABLE legacy(id TEXT PRIMARY KEY,payload TEXT)")
    actual.execute("CREATE TEMP TABLE mapped(eid TEXT PRIMARY KEY,old_eid TEXT)")
    try:
        for node in legacy.values():
            identity = graph.text_property(graph.properties(node[-1]), "id")
            old.execute("INSERT INTO legacy VALUES(?,?)", (identity, json.dumps(node)))
        for node in graph.records(current, "NODE"):
            original = old.execute(
                "SELECT payload FROM snapshot WHERE kind='NODE' AND eid=?", (node[0],)
            ).fetchone()
            if "entityRevision" in graph.unpack(node[1]):
                identity = graph.text_property(graph.properties(node[-1]), "id")
                original_revision = old.execute(
                    "SELECT payload FROM legacy WHERE id=?", (identity,)
                ).fetchone()
                expected = json.loads(original_revision[0]) if original_revision else None
                if expected is None or node[1:] != expected[1:]:
                    raise RuntimeError("Rollback revision scope/typed values drifted")
                actual.execute("INSERT INTO mapped VALUES(?,?)", (node[0], expected[0]))
                continue
            if original is None:
                raise RuntimeError("Rollback encountered an unaccounted node")
            expected_node = graph.unpack(original[0])
            if node[1] != expected_node[1]:
                raise RuntimeError("Rollback nonrevision labels drifted")
            if "ontologyEntity" not in graph.unpack(node[1]):
                if node != expected_node:
                    raise RuntimeError("Rollback business node changed")
                continue
            current_props = graph.properties(node[-1])
            original_props = graph.properties(expected_node[-1])
            if any(current_props.get(k) != v for k, v in original_props.items()):
                raise RuntimeError("Rollback canonical original properties changed")
            identity = graph.text_property(original_props, "id")
            expected = inventory_row(proof, "flat_graph_node", identity)
            extra = {"id": identity, "content_hash": expected["content_hash"]}
            if "flat_content_hash" in current_props:
                extra["flat_content_hash"] = expected["flat_content_hash"]
            if "flat_owned_keys" in current_props:
                extra["flat_owned_keys"] = sorted(expected["owned_properties"])
            require_native_properties(
                proof, "NODE", identity, node[-1], extra, "flat_property", partial=True
            )
        for node in graph.records(before, "NODE"):
            if (
                node[0] not in legacy
                and not actual.execute(
                    "SELECT 1 FROM snapshot WHERE kind='NODE' AND eid=?", (node[0],)
                ).fetchone()
            ):
                raise RuntimeError("Rollback business node disappeared")
        old.execute("CREATE TEMP TABLE legacy_edge(id TEXT PRIMARY KEY,payload TEXT)")
        for edge in graph.records(before, "REL"):
            if edge[1] in legacy or edge[2] in legacy:
                identity = graph.text_property(graph.properties(edge[-1]), "id")
                old.execute("INSERT INTO legacy_edge VALUES(?,?)", (identity, json.dumps(edge)))
            else:
                found = actual.execute(
                    "SELECT payload FROM snapshot WHERE kind='REL' AND eid=?", (edge[0],)
                ).fetchone()
                if found is None or graph.unpack(found[0]) != edge:
                    raise RuntimeError("Rollback unaffected relationship changed")
        for edge in graph.records(current, "REL"):
            original = old.execute(
                "SELECT payload FROM snapshot WHERE kind='REL' AND eid=?", (edge[0],)
            ).fetchone()
            if original is not None and graph.unpack(original[0]) == edge:
                continue
            props = graph.properties(edge[-1])
            identity = graph.text_property(props, "id")
            legacy_edge = old.execute(
                "SELECT payload FROM legacy_edge WHERE id=?", (identity,)
            ).fetchone()
            if legacy_edge:
                expected_edge = json.loads(legacy_edge[0])
                endpoints = [
                    actual.execute("SELECT old_eid FROM mapped WHERE eid=?", (eid,)).fetchone()
                    for eid in edge[1:3]
                ]
                mapped = [
                    row[0] if row else eid for row, eid in zip(endpoints, edge[1:3], strict=True)
                ]
                if mapped != expected_edge[1:3] or edge[3:] != expected_edge[3:]:
                    raise RuntimeError("Rollback legacy attachment drifted")
                continue
            expected = inventory_row(proof, "flat_graph_edge", identity)
            if expected["origin_edge_id"] == identity:
                raise RuntimeError("Rollback found an unaccounted replacement edge")
            # Full native type/endpoints proof for these new edges is performed
            # while generating cleanup CSV, before its one native execution.
    finally:
        old.close()
        actual.close()
        proof.close()


def recover(runtime: dict[str, str], receipt_path: Path) -> Path:
    directory = receipt_path.resolve().parent
    receipt = json.loads(receipt_path.read_bytes())
    if receipt.get("runtime") != runtime or receipt.get("kind") != "FLAT_ONTOLOGY":
        raise RuntimeError("Recovery receipt/runtime identity changed")
    fence = common.STATE / FENCE_NAME
    if not fence.exists() or json.loads(fence.read_bytes()).get("token") != receipt["token"]:
        raise RuntimeError("Recovery requires original durable ontology fence")
    manifest = json.loads(Path(receipt["manifest"]).read_bytes())
    before = graph.validate_archive(manifest["graph"])
    attempt = directory / ("recovery-" + uuid.uuid4().hex)
    attempt.mkdir(mode=0o700)
    try:
        load = flat_load(
            runtime["pg"], manifest["release_id"], manifest["catalogue"]["approval"]["database_id"]
        )
        if load and load["state"] == "VERIFIED":
            raise RuntimeError(
                "Verified serving projection rollback requires reviewed recovery plan"
            )
        require_load_ownership(manifest, receipt, load)
        # Repeated recovery may see old canonical properties or already restored
        # revisions. Exact final comparison is mandatory before checkpoint fail.
        fresh = graph.graph_snapshot(runtime["hop"], attempt, "graph-recovery-start")
        flat = receipt.get("flat_inventory") or capture_flat_inventory(
            runtime["pg"], manifest["release_id"], attempt
        )
        require_rollback_scope(before, Path(fresh["path"]), flat)
        graph.event(directory, receipt, "RECOVERY_STARTING", flat_inventory=flat)
        native_statement_stream(
            runtime["hop"],
            cleanup_flat_edges(
                Path(fresh["path"]),
                flat,
                partial=bool(load and load["state"] in ("RUNNING", "FAILED")),
            ),
            attempt,
            "cleanup-rerouted-edges",
        )
        execute_statements(runtime["hop"], receipt["recovery"], attempt, "restore-typed-legacy")
        restored = graph.graph_snapshot(runtime["hop"], attempt, "graph-restored")
        proof = require_recovered(before, Path(restored["path"]))
        prove_legacy_backing(Path(restored["path"]), manifest["legacy_inventory"])
        load = flat_load(
            runtime["pg"], manifest["release_id"], manifest["catalogue"]["approval"]["database_id"]
        )
        if load and load["state"] in ("STAGED", "RUNNING", "VERIFIED"):
            # A verified migration is intentionally not rolled back through this
            # path: changing an already serving graph requires a reviewed fence.
            if load["state"] == "VERIFIED":
                raise RuntimeError(
                    "Verified serving projection rollback requires reviewed recovery plan"
                )
            deployment.sql(
                runtime["pg"],
                "SELECT ontology.fail_flat_graph_load(" + dates.quote(load["load_id"]) + ")",
            )
        require_old_tables(manifest["old_tables"], all_old_tables(runtime["pg"]))
        require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
        try:
            deployment.sql(
                runtime["pg"],
                "SELECT catalog.catalog_context_v1(" + dates.quote(manifest["release_id"]) + ")",
            )
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "Recovered legacy graph must retain the fail-closed flat reader gate"
            )
        graph.event(
            directory,
            receipt,
            "RECOVERED_GRAPH_WRITERS_REMAIN_FENCED",
            status="RECOVERED_FENCED",
            recovered_graph=restored,
            recovery_preservation=proof,
            load=load,
            scheduler_fence_removed=False,
            retry_requires_fresh_staged_token=True,
        )
        return receipt_path
    except BaseException as error:
        graph.event(
            directory,
            receipt,
            "RECOVERY_FAILED_FENCE_RETAINED",
            status="FAILED",
            failure_type=type(error).__name__,
            failure_message=str(error),
            scheduler_fenced=True,
        )
        raise RuntimeError(
            "Recovery stopped; inspect protected receipt " + str(receipt_path)
        ) from error


def execute(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    common.STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if common.STATE.is_symlink():
        raise RuntimeError("Runtime state must not be a symlink")
    fd = os.open(common.STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Scheduler/native lock is busy") from error
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        if args.mode in ("amend", "amend-resume"):
            import amend_flat_ontology_stage as successor

            return successor.amend(
                sys.modules[__name__],
                runtime,
                args.path,
                args.candidate_dir,
                args.validation_proof,
            )
        if args.mode == "run":
            # One lock covers the fresh baseline, exact dump restore and all
            # migration gates. A prior reviewed manifest binds desired public
            # bytes while its old runtime baseline may legitimately be stale.
            dates.require_idle(runtime["pg"])
            if (common.STATE / FENCE_NAME).exists():
                raise RuntimeError("Resume or recover the existing fenced ontology migration")
            reviewed = json.loads(args.reviewed_manifest.read_bytes())
            if (
                reviewed.get("kind") != "FLAT_ONTOLOGY"
                or reviewed.get("release_id") != args.release_id
            ):
                raise RuntimeError("Reviewed flat artifact manifest/release required")
            desired = deployment.snapshot(runtime)[0]
            if {k: v["after"] for k, v in desired.items()} != {
                k: v["after"] for k, v in reviewed["artifacts"].items()
            }:
                raise RuntimeError("Reviewed flat runtime artifact hashes changed")
            directory = common.STATE / ("flat-ontology-locked-execution-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            plan_directory, apply_directory = directory / "plan", directory / "apply"
            plan_directory.mkdir(mode=0o700)
            apply_directory.mkdir(mode=0o700)
            manifest = make_plan(runtime, plan_directory, args.release_id, args.preflight)
            if json.loads(manifest.read_bytes())["catalogue"] != reviewed.get("catalogue"):
                raise RuntimeError("Reviewed approved catalogue/load/reader baseline changed")
            return apply_plan(runtime, manifest, apply_directory)
        if args.mode == "plan":
            dates.require_idle(runtime["pg"])
            if (common.STATE / FENCE_NAME).exists():
                raise RuntimeError("Resume or recover the existing fenced ontology migration")
            directory = common.STATE / ("flat-ontology-plan-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            return make_plan(runtime, directory, args.release_id, args.preflight)
        if args.mode == "apply":
            dates.require_idle(runtime["pg"])
            directory = common.STATE / ("flat-ontology-apply-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            return apply_plan(
                runtime, args.path, directory, backup_restore_proof=args.backup_restore_proof
            )
        if args.mode == "recover":
            return recover(runtime, args.path)
        receipt = json.loads(args.path.read_bytes())
        return apply_plan(
            runtime,
            Path(receipt["manifest"]),
            args.path.resolve().parent,
            receipt,
            args.backup_restore_proof,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("plan", "run", "apply", "resume", "recover", "amend", "amend-resume")
    )
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--release-id", default=DEFAULT_RELEASE)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--backup-restore-proof", type=Path)
    parser.add_argument("--reviewed-manifest", type=Path)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--validation-proof", type=Path)
    args = parser.parse_args()
    if args.mode not in ("plan", "run") and args.path is None:
        parser.error("Manifest/receipt path is required for this mode")
    if args.mode == "run" and args.reviewed_manifest is None:
        parser.error("--reviewed-manifest is required to bind the reviewed artifact hashes")
    try:
        path = execute(args)
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps({"receipt": str(path)}))


if __name__ == "__main__":
    main()
