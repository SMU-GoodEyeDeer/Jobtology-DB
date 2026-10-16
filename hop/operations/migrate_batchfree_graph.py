#!/usr/bin/env python3
"""Protected, bounded evidence and removal tools for the batch-free migration.

The CLI owns refresh.lock once around deployment/install/projection/removal.
Its reusable bounded primitives do not acquire the lock again. They use only
the existing native Hop connection, never read credentials or call providers.
Only the two named scaffolding labels are eligible for deletion. PostgreSQL
history and every business property, type, label and existing edge are protected.
"""

from __future__ import annotations

import argparse
import copy
import csv
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import backfill_posting_dates as dates
import deploy_jobkorea_runtime as deployment
import reconcile_runtime as common

SCAFFOLD_LABELS = frozenset(("ingestionBatch", "ingestionRecord"))
csv.field_size_limit(32 * 1024 * 1024)
NEW_LEDGERS = frozenset(
    (
        "ingestion.source_graph_projection",
        "ingestion.source_graph_record_evidence",
        "ingestion.source_graph_membership",
    )
)
PAGE_SIZE = 5000
MAX_SNAPSHOT_OBJECTS = 2_000_000
DELETE_SIZE = 200
BACKING_SIZE = 1000
SAFE_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
DIRECT_PROPERTIES = frozenset(
    (
        "source_id",
        "source_run_id",
        "source_record_id",
        "source_created_at",
        "source_facts_json",
        "source_facts_sha256",
    )
)
DIRECT_EDGES = frozenset(
    (
        "EMPLOYER",
        "CLASSIFIED_AS",
        "HAS_CAREER_COMPETENCY",
        "QUALIFICATION_MAPPING",
        "HAS_EXAM_SESSION",
    )
)


def framed(expression: str) -> str:
    return f"toString(size({expression}))+':'+{expression}"


def unpack(value: str) -> list[str]:
    """Decode exact UTF-8 text framing, including quotes/newlines/Korean text."""
    result: list[str] = []
    position = 0
    while position < len(value):
        end = value.find(":", position)
        if end < 0 or not value[position:end].isdigit():
            raise RuntimeError("Invalid typed graph snapshot framing")
        length = int(value[position:end])
        start = end + 1
        if length > len(value) - start:
            raise RuntimeError("Truncated typed graph snapshot")
        result.append(value[start : start + length])
        position = start + length
    return result


def properties(signature: str) -> dict[str, list[str]]:
    items = unpack(signature)
    if len(items) % 3:
        raise RuntimeError("Incomplete typed property triple")
    result: dict[str, list[str]] = {}
    for offset in range(0, len(items), 3):
        key, kind, value = items[offset : offset + 3]
        if key in result:
            raise RuntimeError("Repeated graph property key")
        result[key] = [kind, value]
    return result


def snapshot_query(kind: str, cursor: str, limit: int = PAGE_SIZE) -> str:
    if kind not in ("NODE", "REL") or not 1 <= limit <= PAGE_SIZE:
        raise ValueError("Invalid snapshot page")
    entity = "n" if kind == "NODE" else "r"
    match = "MATCH (n)" if kind == "NODE" else "MATCH (a)-[r]->(b)"
    signature = dates.signature_expression(entity, "[]")
    prefix = (
        f"{framed('elementId(n)')}+{framed('label_signature')}"
        if kind == "NODE"
        else "+".join(
            framed(x) for x in ("elementId(r)", "elementId(a)", "elementId(b)", "type(r)")
        )
    )
    labels = (
        """CALL (n) {
 UNWIND labels(n) AS label WITH label ORDER BY label RETURN collect(label) AS labels
}
WITH *,reduce(s='',label IN labels | s+toString(size(label))+':'+label) AS label_signature
"""
        if kind == "NODE"
        else ""
    )
    return f"""{match}
WHERE elementId({entity})>{json.dumps(cursor)}
WITH * ORDER BY elementId({entity}) LIMIT {limit}
{labels}{signature}
RETURN {prefix}+{framed("property_signature")} AS signature
ORDER BY elementId({entity})"""


def configure_grid(path: Path, field: str, values: list[str], kind: str = "String") -> None:
    """Bounded transactions in one JVM; each grid row is one query batch."""
    root = ET.parse(path).getroot()
    seed = next(t for t in root.findall("transform") if t.findtext("type") == "GetVariable")
    seed.clear()
    ET.SubElement(seed, "type").text = "DataGrid"
    ET.SubElement(seed, "name").text = "Snapshot"
    fields = ET.SubElement(seed, "fields")
    item = ET.SubElement(fields, "field")
    for key, value in (("name", field), ("type", kind), ("length", "-1"), ("precision", "-1")):
        ET.SubElement(item, key).text = value
    data = ET.SubElement(seed, "data")
    for value in values:
        ET.SubElement(ET.SubElement(data, "line"), "item").text = value
    neo = next(t for t in root.findall("transform") if t.findtext("type") == "Neo4jCypherOutput")
    mappings = neo.find("mappings")
    assert mappings is not None
    mapping = ET.SubElement(mappings, "mapping")
    for key, value in (("parameter", field), ("field", field), ("type", kind)):
        ET.SubElement(mapping, key).text = value
    neo.find("batch_size").text = "1"  # type: ignore[union-attr]
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    path.chmod(0o600)


def native_output(
    hop: str,
    query: str,
    directory: Path,
    label: str,
    *,
    write: bool = False,
    grid: tuple[str, list[str], str] | None = None,
    cypher_field: str | None = None,
    transaction_rows: int = 1,
) -> Path:
    """A single bounded native operation; files stay 0600 and uid/gid 501."""
    remote = "/tmp/batchfree-" + uuid.uuid4().hex
    pipeline, output = directory / (label + ".hpl"), directory / (label + ".csv")
    dates.build_snapshot(pipeline, query, remote)
    if grid:
        configure_grid(pipeline, *grid)
    if cypher_field:
        if not SAFE_NAME.fullmatch(cypher_field) or not 1 <= transaction_rows <= DELETE_SIZE:
            raise ValueError("Unsafe dynamic query field/transaction bound")
        document = ET.parse(pipeline)
        neo = next(
            t
            for t in document.getroot().findall("transform")
            if t.findtext("type") == "Neo4jCypherOutput"
        )
        neo.find("cypher_from_field").text = "Y"  # type: ignore[union-attr]
        ET.SubElement(neo, "cypher_field").text = cypher_field
        neo.find("batch_size").text = str(transaction_rows)  # type: ignore[union-attr]
        document.write(pipeline, encoding="utf-8", xml_declaration=True)
    if write:
        root = ET.parse(pipeline).getroot()
        next(
            t for t in root.findall("transform") if t.findtext("type") == "Neo4jCypherOutput"
        ).find("read_only").text = "N"  # type: ignore[union-attr]
        # Every write query returns BLOCKED on a refused gate; stop immediately.
        template = ET.parse(common.ROOT / "graph/verify_records.hpl").getroot()
        check = copy.deepcopy(
            next(t for t in template.findall("transform") if t.findtext("type") == "FilterRows")
        )
        check.find("compare/condition/leftvalue").text = "signature"  # type: ignore[union-attr]
        check.find("compare/condition/value/type").text = "String"  # type: ignore[union-attr]
        check.find("compare/condition/value/text").text = "BLOCKED"  # type: ignore[union-attr]
        check.find("send_true_to").text = "Check failed"  # type: ignore[union-attr]
        check.find("send_false_to").text = "Write private snapshot"  # type: ignore[union-attr]
        root.append(check)
        abort = copy.deepcopy(
            next(t for t in template.findall("transform") if t.findtext("type") == "Abort")
        )
        abort.find(
            "message"
        ).text = "Batch-free operation gate refused; inspect protected evidence."  # type: ignore[union-attr]
        root.append(abort)
        order = root.find("order")
        assert order is not None
        for hop_node in order.findall("hop"):
            if hop_node.findtext("from") == "Read graph snapshot":
                hop_node.find("to").text = "Check result"  # type: ignore[union-attr]
        for target in ("Check failed", "Write private snapshot"):
            h = ET.SubElement(order, "hop")
            for key, value in (("from", "Check result"), ("to", target), ("enabled", "Y")):
                ET.SubElement(h, key).text = value
        ET.ElementTree(root).write(pipeline, encoding="utf-8", xml_declaration=True)
        pipeline.chmod(0o600)
    try:
        dates.temporary_native(hop, pipeline, directory, label)
        common.command(["docker", "cp", hop + ":" + remote + ".csv", str(output)])
        output.chmod(0o600)
        return output
    finally:
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-f", "--", remote + ".csv"])


def output_rows(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 1:
                raise RuntimeError("Invalid private graph CSV framing")
            yield row[0]


def native_rows(hop: str, query: str, directory: Path, label: str, **kwargs: Any) -> list[str]:
    return list(output_rows(native_output(hop, query, directory, label, **kwargs)))


def graph_snapshot(hop: str, directory: Path, label: str) -> dict[str, Any]:
    """Capture all nodes/edges once, in bounded native pages, on protected disk."""
    path = directory / (label + ".sqlite")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT, PRIMARY KEY(kind,eid))")
    counts = {}
    digest = hashlib.sha256()
    try:
        total_rows = native_rows(
            hop,
            "MATCH(n) RETURN 'NODE:'+toString(count(n)) AS signature "
            "UNION ALL MATCH()-[r]->() RETURN 'REL:'+toString(count(r)) AS signature",
            directory,
            label + "-counts",
        )
        totals = {row.split(":")[0]: int(row.split(":")[1]) for row in total_rows}
        if set(totals) != {"NODE", "REL"}:
            raise RuntimeError("Graph snapshot count framing incomplete")
        for kind in ("NODE", "REL"):
            cursor, count = "", 0
            query = snapshot_query(kind, "")
            entity = "n" if kind == "NODE" else "r"
            if totals[kind] > MAX_SNAPSHOT_OBJECTS:
                raise RuntimeError("Graph snapshot cardinality exceeds reviewed bound")
            query = query.replace(
                f'WHERE elementId({entity})>""',
                f"WHERE elementId({entity})>split($bounds,',')[0] "
                f"AND elementId({entity})<=split($bounds,',')[1]",
            )
            match = "MATCH(n)" if kind == "NODE" else "MATCH()-[r]->()"
            boundary_query = (
                f"{match} WITH elementId({entity}) AS eid ORDER BY eid "
                "WITH collect(eid) AS ids "
                f"UNWIND range(0,size(ids)-1,{PAGE_SIZE}) AS offset "
                "WITH ids,offset,CASE WHEN offset=0 THEN '' ELSE ids[offset-1] END AS lower,"
                f"ids[CASE WHEN offset+{PAGE_SIZE}-1<size(ids) THEN offset+{PAGE_SIZE}-1 "
                "ELSE size(ids)-1 END] AS upper "
                "RETURN lower+','+upper AS signature ORDER BY offset"
            )
            boundaries = (
                native_rows(hop, boundary_query, directory, f"{label}-{kind.lower()}-bounds")
                if totals[kind]
                else []
            )
            if boundaries:
                output = native_output(
                    hop,
                    query,
                    directory,
                    f"{label}-{kind.lower()}",
                    grid=("bounds", boundaries, "String"),
                )
                for value in output_rows(output):
                    parts = unpack(value)
                    expected = 3 if kind == "NODE" else 5
                    if len(parts) != expected or parts[0] <= cursor:
                        raise RuntimeError("Invalid graph page order/framing")
                    properties(parts[-1])
                    db.execute("INSERT INTO snapshot VALUES(?,?,?)", (kind, parts[0], value))
                    digest.update((kind + value).encode("utf-8"))
                    cursor = parts[0]
                    count += 1
                    if count % PAGE_SIZE == 0:
                        db.commit()
            db.commit()
            if count != totals[kind]:
                raise RuntimeError("Graph changed during bounded snapshot")
            counts[kind] = count
        return {
            "path": str(path),
            "sha256": digest.hexdigest(),
            "counts": counts,
            "page_size": PAGE_SIZE,
        }
    finally:
        db.close()


def records(path: Path, kind: str) -> Iterator[list[str]]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for (value,) in db.execute(
            "SELECT payload FROM snapshot WHERE kind=? ORDER BY eid", (kind,)
        ):
            yield unpack(value)
    finally:
        db.close()


def scaffold_nodes(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in records(path, "NODE"):
        labels = set(unpack(node[1]))
        suspicious = {x for x in labels if x.startswith("HopMigration") or x == "archivedRecord"}
        if suspicious:
            raise RuntimeError("Unexpected legacy/archive graph labels; review separately")
        if labels & SCAFFOLD_LABELS:
            if len(labels) != 1:
                raise RuntimeError("Scaffolding carries unexpected labels; removal refused")
            result[node[0]] = node
    return result


def text_property(props: dict[str, list[str]], name: str) -> str:
    value = props.get(name)
    if value is None or value[0] != "STRING NOT NULL":
        raise RuntimeError("Required scaffolding string property missing: " + name)
    return value[1]


def pg_rows(pg: str, query: str) -> list[dict[str, Any]]:
    return json.loads(
        deployment.sql(
            pg,
            "BEGIN READ ONLY; SET LOCAL statement_timeout='60s'; "
            "SELECT coalesce(jsonb_agg(to_jsonb(q)),'[]'::jsonb) FROM (" + query + ") q; COMMIT;",
        )
    )


def pg_evidence(pg: str, runs: list[str], directory: Path) -> Path:
    """Read each source projection once to protected indexed disk, never argv."""
    values = ",".join(dates.quote(run) for run in runs)
    target = directory / "postgres-graph-evidence.sqlite"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    db = sqlite3.connect(target)
    db.execute("CREATE TABLE records(id TEXT,run_id TEXT,payload TEXT,PRIMARY KEY(id,run_id))")
    db.execute(
        "CREATE TABLE refs(record_id TEXT,identity_id TEXT,field TEXT,run_id TEXT,"
        "PRIMARY KEY(record_id,identity_id,field,run_id))"
    )
    try:
        for label, projection in (("records", "graph_record"), ("refs", "graph_reference")):
            query = (
                "BEGIN READ ONLY; SET LOCAL statement_timeout='180s'; COPY ("
                f"SELECT to_jsonb(q)::text FROM ingestion.{projection} q "
                f"WHERE q.run_id IN({values})) TO STDOUT WITH(FORMAT csv); COMMIT;"
            )
            output = directory / ("postgres-" + label + ".csv")
            log = directory / ("postgres-" + label + ".log")
            with output.open("xb") as handle, log.open("xb") as errors:
                result = subprocess.run(
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
                        "jobtology",
                    ],
                    input=query.encode(),
                    stdout=handle,
                    stderr=errors,
                    check=False,
                )
            output.chmod(0o600)
            log.chmod(0o600)
            if result.returncode:
                raise RuntimeError("PostgreSQL evidence export failed; inspect protected log")
            # COPY CSV is comma-delimited, one quoted JSON object per record.
            with output.open(encoding="utf-8", newline="") as stream:
                for number, rowtext in enumerate(csv.reader(stream), 1):
                    if len(rowtext) != 1:
                        raise RuntimeError("Invalid PostgreSQL evidence framing")
                    text = rowtext[0]
                    row = json.loads(text)
                    if label == "records":
                        db.execute(
                            "INSERT INTO records VALUES(?,?,?)", (row["id"], row["run_id"], text)
                        )
                    else:
                        db.execute(
                            "INSERT INTO refs VALUES(?,?,?,?)",
                            (row["record_id"], row["identity_id"], row["field"], row["run_id"]),
                        )
                    if number % PAGE_SIZE == 0:
                        db.commit()
            db.commit()
        return target
    finally:
        db.close()


def prove_backing(pg: str, path: Path, evidence: Path | None = None) -> dict[str, Any]:
    """Every removable node/edge must resolve to immutable PostgreSQL evidence."""
    nodes = scaffold_nodes(path)
    batches: dict[str, tuple[str, dict[str, list[str]]]] = {}
    raw: dict[str, str] = {}
    for eid, node in nodes.items():
        props = properties(node[-1])
        identity = text_property(props, "id")
        if identity in batches or identity in raw:
            raise RuntimeError("Duplicate scaffolding identity")
        if unpack(node[1]) == ["ingestionBatch"]:
            batches[identity] = (eid, props)
        else:
            raw[identity] = eid
    for start in range(0, len(batches), BACKING_SIZE):
        ids = list(batches)[start : start + BACKING_SIZE]
        values = ",".join(dates.quote(x) for x in ids)
        found = pg_rows(
            pg,
            "SELECT run_id,source_id,state,EXISTS(SELECT 1 FROM ingestion.graph_export g "
            "WHERE g.run_id=r.run_id) AS checkpoint FROM ingestion.run r "
            f"WHERE run_id IN({values})",
        )
        if {row["run_id"] for row in found} != set(ids):
            raise RuntimeError("Graph batch has no PostgreSQL run; removal refused")
        for row in found:
            props = batches[row["run_id"]][1]
            if (
                text_property(props, "source_id") != row["source_id"]
                or row["state"] != "READY"
                or not row["checkpoint"]
            ):
                raise RuntimeError(
                    "Graph batch does not match a checkpointed immutable READY source run"
                )
    if evidence is None:
        evidence = pg_evidence(pg, sorted(batches), path.parent)
    pg_db = sqlite3.connect(f"file:{evidence}?mode=ro", uri=True)
    try:
        for identity, eid in raw.items():
            found = pg_db.execute("SELECT payload FROM records WHERE id=?", (identity,)).fetchall()
            if not found:
                raise RuntimeError(
                    "Graph record has no accepted PostgreSQL evidence; removal refused"
                )
            props = properties(nodes[eid][-1])
            for (text,) in found:
                row = json.loads(text)
                allowed = {"id", "source_id", "source_record_id", "kind", "name", "facts_json"}
                if set(props) != {name for name in allowed if row[name] is not None}:
                    raise RuntimeError("Record property keys differ from PostgreSQL evidence")
                for name in props:
                    if text_property(props, name) != row[name]:
                        raise RuntimeError("Graph record differs from PostgreSQL evidence: " + name)
        business = {
            n[0]: properties(n[-1]).get("id") for n in records(path, "NODE") if n[0] not in nodes
        }
        edge_count = 0
        for edge in records(path, "REL"):
            _, start, end, rel_type, payload = edge
            if start not in nodes and end not in nodes:
                continue
            edge_count += 1
            props = properties(payload)
            if rel_type == "HAS_RECORD" and start in nodes and end in nodes and not props:
                batch, record = properties(nodes[start][-1]), properties(nodes[end][-1])
                if unpack(nodes[start][1]) != ["ingestionBatch"] or unpack(nodes[end][1]) != [
                    "ingestionRecord"
                ]:
                    raise RuntimeError("Unexpected HAS_RECORD endpoints")
                if not pg_db.execute(
                    "SELECT 1 FROM records WHERE id=? AND run_id=?",
                    (text_property(record, "id"), text_property(batch, "id")),
                ).fetchone():
                    raise RuntimeError("HAS_RECORD has no PostgreSQL membership")
            elif rel_type == "REFERS_TO" and start in nodes and end in business:
                if unpack(nodes[start][1]) != ["ingestionRecord"] or set(props) != {"field"}:
                    raise RuntimeError("Unexpected REFERS_TO endpoints/properties")
                identity = business[end]
                if identity is None or identity[0] != "STRING NOT NULL":
                    raise RuntimeError("Reference endpoint lacks stable identity")
                key = (
                    text_property(properties(nodes[start][-1]), "id"),
                    identity[1],
                    text_property(props, "field"),
                )
                if not pg_db.execute(
                    "SELECT 1 FROM refs WHERE record_id=? AND identity_id=? AND field=?", key
                ).fetchone():
                    raise RuntimeError("REFERS_TO lacks PostgreSQL evidence")
            else:
                raise RuntimeError("Unexpected scaffolding relationship; removal refused")
        return {
            "batch_nodes": len(batches),
            "record_nodes": len(raw),
            "scaffold_edges": edge_count,
            "runs": sorted(batches),
            "backing": "IMMUTABLE_POSTGRESQL_RECORDS_AND_REFERENCES",
            "postgres_evidence": str(evidence),
        }
    finally:
        pg_db.close()


def require_business_preserved(before: Path, after: Path) -> dict[str, int]:
    removed = scaffold_nodes(before)
    restored = scaffold_nodes(after)
    db = sqlite3.connect(f"file:{after}?mode=ro", uri=True)
    counts = {"business_nodes": 0, "business_edges": 0}
    try:
        for kind in ("NODE", "REL"):
            for old in records(before, kind):
                if (kind == "NODE" and old[0] in removed) or (
                    kind == "REL" and (old[1] in removed or old[2] in removed)
                ):
                    continue
                row = db.execute(
                    "SELECT payload FROM snapshot WHERE kind=? AND eid=?", (kind, old[0])
                ).fetchone()
                if row is None:
                    raise RuntimeError("Existing business identity/edge was removed")
                new = unpack(row[0])
                if kind == "NODE":
                    if not set(unpack(old[1])).issubset(unpack(new[1])):
                        raise RuntimeError("Existing business label changed")
                elif old[1:4] != new[1:4]:
                    raise RuntimeError("Existing business relationship endpoints/type changed")
                old_props, new_props = properties(old[-1]), properties(new[-1])
                if any(new_props.get(k) != v for k, v in old_props.items()):
                    raise RuntimeError("Existing business property value/type changed")
                added = set(new_props) - set(old_props)
                if (kind == "REL" and added) or (
                    kind == "NODE" and not added.issubset(DIRECT_PROPERTIES)
                ):
                    raise RuntimeError("Unexpected new property on existing business object")
                counts["business_nodes" if kind == "NODE" else "business_edges"] += 1
        before_db = sqlite3.connect(f"file:{before}?mode=ro", uri=True)
        try:
            for new in records(after, "NODE"):
                if new[0] in restored:
                    continue
                if before_db.execute(
                    "SELECT 1 FROM snapshot WHERE kind='NODE' AND eid=?", (new[0],)
                ).fetchone():
                    continue
                if set(unpack(new[1])) != {"entity", "examSession"}:
                    raise RuntimeError("Unexpected new business node labels")
            for new in records(after, "REL"):
                if new[1] in restored or new[2] in restored:
                    continue
                if before_db.execute(
                    "SELECT 1 FROM snapshot WHERE kind='REL' AND eid=?", (new[0],)
                ).fetchone():
                    continue
                props = properties(new[-1])
                if new[3] not in DIRECT_EDGES or props.get("source_graph") != [
                    "BOOLEAN NOT NULL",
                    "true",
                ]:
                    raise RuntimeError("Unexpected new business relationship")
        finally:
            before_db.close()
        return counts
    finally:
        db.close()


def preservation(pg: str) -> dict[str, Any]:
    result = {
        k: v for k, v in deployment.full_preservation_state(pg).items() if k not in NEW_LEDGERS
    }
    if "retention.plan_run" in result:
        row = deployment.sql(
            pg,
            "BEGIN READ ONLY; SELECT jsonb_build_object('count',count(*),"
            "'digest',md5(coalesce(string_agg(h,'' ORDER BY h),''))) FROM "
            "(SELECT md5((to_jsonb(t)-'source_projection_verified')::text) h "
            "FROM retention.plan_run t) q; COMMIT;",
        )
        result["retention.plan_run"] = json.loads(row)
        present = deployment.sql(
            pg,
            "BEGIN READ ONLY; SELECT EXISTS(SELECT 1 FROM "
            "information_schema.columns WHERE table_schema='retention' AND table_name='plan_run' "
            "AND column_name='source_projection_verified'); COMMIT;",
        )
        if (
            present == "t"
            and deployment.sql(
                pg,
                "BEGIN READ ONLY; SELECT count(*) FROM "
                "retention.plan_run WHERE source_projection_verified "
                "IS DISTINCT FROM false; COMMIT;",
            )
            != "0"
        ):
            raise RuntimeError("Historical retention projection flags changed")
    return result


def cypher_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def property_literal(kind: str, value: str) -> str:
    bare = kind.removesuffix(" NOT NULL")
    if bare.startswith("LIST<"):
        subtype = bare[5:-1]
        return "[" + ",".join(property_literal(subtype, x) for x in unpack(value)) + "]"
    if bare == "STRING":
        return cypher_string(value)
    if bare == "INTEGER" and re.fullmatch(r"-?[0-9]+", value):
        return value
    if bare == "FLOAT":
        float(value)
        return "toFloat(" + cypher_string(value) + ")"
    if bare == "BOOLEAN" and value in ("true", "false"):
        return value
    constructors = {
        "DATE": "date",
        "ZONED DATETIME": "datetime",
        "LOCAL DATETIME": "localdatetime",
        "ZONED TIME": "time",
        "LOCAL TIME": "localtime",
        "DURATION": "duration",
    }
    if bare in constructors:
        return constructors[bare] + "(" + cypher_string(value) + ")"
    raise RuntimeError("Scaffolding property type cannot be restored safely: " + kind)


def property_map(payload: str) -> str:
    return (
        "{"
        + ",".join(
            "`" + key.replace("`", "``") + "`:" + property_literal(kind, value)
            for key, (kind, value) in properties(payload).items()
        )
        + "}"
    )


def recovery_queries(path: Path) -> Iterator[str]:
    """Recreate removed scaffolding exactly; business element IDs remain intact.

    Neo4j allocates new element IDs for recreated scaffold nodes/relationships.
    Their stable id properties, labels, typed values, memberships and references
    are restored. This is an in-place recovery, not a full database replacement.
    """
    nodes = scaffold_nodes(path)
    for node in nodes.values():
        label = unpack(node[1])[0]
        identity = text_property(properties(node[-1]), "id")
        yield (
            f"MERGE (n:{label} {{id:{cypher_string(identity)}}}) "
            f"SET n={property_map(node[-1])} RETURN 'OK' AS signature"
        )
    for edge in records(path, "REL"):
        _, start, end, rel_type, payload = edge
        if start not in nodes and end not in nodes:
            continue
        matches: list[str] = []
        for variable, eid in (("a", start), ("b", end)):
            if eid in nodes:
                node = nodes[eid]
                identity = text_property(properties(node[-1]), "id")
                matches.append(
                    f"MATCH ({variable}:{unpack(node[1])[0]} {{id:{cypher_string(identity)}}})"
                )
            else:
                matches.append(
                    f"MATCH ({variable}) WHERE elementId({variable})={cypher_string(eid)}"
                )
        if rel_type not in ("HAS_RECORD", "REFERS_TO"):
            raise RuntimeError("Unexpected recovery relationship")
        yield (
            " ".join(matches)
            + f" MERGE (a)-[r:{rel_type} {property_map(payload)}]->(b) RETURN 'OK' AS signature"
        )


def prepare_recovery(path: Path, directory: Path) -> dict[str, Any]:
    output = directory / "scaffold-recovery.cypher.ndjson"
    count = 0
    with output.open("x", encoding="utf-8") as handle:
        for query in recovery_queries(path):
            handle.write(json.dumps({"cypher": query}, ensure_ascii=False) + "\n")
            count += 1
    output.chmod(0o600)
    with output.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "path": str(output),
        "sha256": digest,
        "statements": count,
        "mode": "IN_PLACE_TYPED_SCAFFOLD_RECOVERY_NEW_SCAFFOLD_ELEMENT_IDS",
    }


def deletion_query(ids: list[str]) -> str:
    if not ids or len(ids) > DELETE_SIZE:
        raise ValueError("Removal batch exceeds bound")
    # No DETACH DELETE: every incident edge is explicitly allowlisted and
    # verified again in the same transaction; unknown edges fail closed.
    return f"""UNWIND {json.dumps(ids)} AS eid
MATCH (n) WHERE elementId(n)=eid AND size(labels(n))=1
 AND (n:ingestionBatch OR n:ingestionRecord)
OPTIONAL MATCH (n)-[r]-(other)
WITH collect(DISTINCT n) AS nodes,collect(DISTINCT r) AS rels
WITH nodes,rels,size(nodes)={len(ids)} AND all(r IN rels WHERE
 (type(r)='HAS_RECORD' AND startNode(r):ingestionBatch
   AND endNode(r):ingestionRecord AND size(keys(r))=0)
 OR (type(r)='REFERS_TO' AND startNode(r):ingestionRecord
   AND endNode(r):entity AND keys(r)=['field'])) AS safe
FOREACH(r IN CASE WHEN safe THEN rels ELSE [] END | DELETE r)
FOREACH(n IN CASE WHEN safe THEN nodes ELSE [] END | DELETE n)
RETURN CASE WHEN safe THEN toString(size(nodes)) ELSE 'BLOCKED' END AS signature"""


def remove_scaffolding(hop: str, snapshot: Path, directory: Path) -> list[dict[str, Any]]:
    """Caller must prove PG backing/direct projection and persist recovery first."""
    nodes = scaffold_nodes(snapshot)
    # Delete records first, then batches. Each immutable event records exact IDs.
    ordered = sorted(nodes, key=lambda eid: (unpack(nodes[eid][1]) == ["ingestionBatch"], eid))
    result: list[dict[str, Any]] = []
    chunks: list[list[str]] = []
    for offset in range(0, len(ordered), DELETE_SIZE):
        ids = ordered[offset : offset + DELETE_SIZE]
        label = f"delete-{offset // DELETE_SIZE + 1}"
        event = directory / (label + ".json")
        # Write intent before executing; failure preserves inspectable exact scope.
        intent = {"status": "INTENT", "element_ids": ids, "count": len(ids)}
        common.write_json(event, intent)
        chunks.append(ids)
    if not chunks:
        return []
    if any(not re.fullmatch(r"[A-Za-z0-9:-]+", eid) for ids in chunks for eid in ids):
        raise RuntimeError("Unsafe graph element ID")
    query = deletion_query(chunks[0]).replace(json.dumps(chunks[0]), "split($ids,',')")
    query = query.replace(f"size(nodes)={len(chunks[0])}", "size(nodes)=size(split($ids,','))")
    rows = native_rows(
        hop,
        query,
        directory,
        "delete-bounded-scaffolding",
        write=True,
        grid=("ids", [",".join(ids) for ids in chunks], "String"),
    )
    if rows != [str(len(ids)) for ids in chunks]:
        raise RuntimeError("Bounded removal gate rejected graph drift; inspect receipt")
    for number, ids in enumerate(chunks, 1):
        done = {"status": "APPLIED", "element_ids": ids, "count": len(ids)}
        common.write_json(directory / (f"delete-{number}-applied.json"), done)
        result.append(done)
    return result


def recover_scaffolding(hop: str, recovery: dict[str, Any], directory: Path) -> int:
    """Bounded native restore from a checksum-verified private export.

    One JVM handles up to 5,000 restore statements, committing at most 200
    statements per transaction. A partial restore can be replayed idempotently.
    The coordinator must first fence writers and preserve/verify business state.
    """
    path = Path(recovery["path"])
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != recovery["sha256"]:
            raise RuntimeError("Scaffolding recovery export checksum changed")
    completed, number = 0, 0
    batch: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.endswith("\n"):
                raise RuntimeError("Truncated scaffolding recovery export")
            batch.append(json.loads(line)["cypher"])
            if len(batch) == PAGE_SIZE:
                number += 1
                rows = native_rows(
                    hop,
                    "",
                    directory,
                    f"restore-{number}",
                    write=True,
                    grid=("query", batch, "String"),
                    cypher_field="query",
                    transaction_rows=DELETE_SIZE,
                )
                if rows != ["OK"] * len(batch):
                    raise RuntimeError("Scaffolding recovery target absent; stop for review")
                completed += len(batch)
                common.write_json(
                    directory / (f"restore-{number}-applied.json"),
                    {"status": "APPLIED", "statements": len(batch), "completed": completed},
                )
                batch = []
        if batch:
            number += 1
            rows = native_rows(
                hop,
                "",
                directory,
                f"restore-{number}",
                write=True,
                grid=("query", batch, "String"),
                cypher_field="query",
                transaction_rows=DELETE_SIZE,
            )
            if rows != ["OK"] * len(batch):
                raise RuntimeError("Scaffolding recovery target absent; stop for review")
            completed += len(batch)
            common.write_json(
                directory / (f"restore-{number}-applied.json"),
                {"status": "APPLIED", "statements": len(batch), "completed": completed},
            )
    if completed != recovery["statements"]:
        raise RuntimeError("Scaffolding recovery statement count changed")
    return completed


MIGRATION_SQL = (
    "graph/sql/002_batchfree_source_graph.sql",
    "llm/sql/036_batchfree_graph_publication.sql",
    "retention/sql/002_batchfree_retention.sql",
)
FENCE_LINE = '[[ ! -e "$STATE_DIR/batchfree-migration.pending" ]] || exit 0\n'


def require_schema(before: dict[str, Any], after: dict[str, Any]) -> None:
    allowed = {
        name
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
                category == "functions" and name.split("(")[0] in allowed
            ):
                raise RuntimeError("Unexpected existing schema change: " + name)


def source_scope(pg: str) -> list[str]:
    rows = pg_rows(
        pg,
        "SELECT r.run_id FROM ingestion.run r JOIN ingestion.graph_export g "
        "USING(run_id) WHERE r.state='READY' AND r.mode<>'SMOKE' ORDER BY r.run_id",
    )
    result = [dates.exact_identity(row["run_id"]) for row in rows]
    if not result:
        raise RuntimeError("No checkpointed READY source runs")
    return result


def validate_archive(snapshot: dict[str, Any]) -> Path:
    path = Path(snapshot["path"])
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("Graph archive must be a protected regular file")
    digest, counts = hashlib.sha256(), {}
    for kind in ("NODE", "REL"):
        count = 0
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for (value,) in db.execute(
                "SELECT payload FROM snapshot WHERE kind=? ORDER BY eid", (kind,)
            ):
                unpack(value)
                digest.update((kind + value).encode())
                count += 1
        finally:
            db.close()
        counts[kind] = count
    if digest.hexdigest() != snapshot["sha256"] or counts != snapshot["counts"]:
        raise RuntimeError("Protected graph archive checksum/count changed")
    return path


def install_workflow(path: Path) -> None:
    """Only three reviewed additive migrations execute; no broad installers."""
    template = ET.parse(common.ROOT / "graph/install.hwf").getroot()
    root = ET.Element("workflow")
    ET.SubElement(root, "name").text = "Focused permanent batch-free migration SQL"
    ET.SubElement(root, "parameters")
    actions, hops = ET.SubElement(root, "actions"), ET.SubElement(root, "hops")
    actions.append(
        copy.deepcopy(
            next(a for a in template.findall("actions/action") if a.findtext("type") == "SPECIAL")
        )
    )
    success = copy.deepcopy(
        next(a for a in template.findall("actions/action") if a.findtext("type") == "SUCCESS")
    )
    abort = copy.deepcopy(
        next(a for a in template.findall("actions/action") if a.findtext("type") == "ABORT")
    )
    actions.extend((success, abort))
    previous = "Start"
    for number, relative in enumerate(MIGRATION_SQL, 1):
        action = copy.deepcopy(
            next(a for a in template.findall("actions/action") if a.findtext("type") == "SQL")
        )
        name = "Focused SQL " + str(number)
        action.find("name").text = name  # type: ignore[union-attr]
        action.find("sqlfilename").text = "${PROJECT_HOME}/" + relative  # type: ignore[union-attr]
        actions.append(action)
        hop = ET.SubElement(hops, "hop")
        for key, value in (
            ("from", previous),
            ("to", name),
            ("enabled", "Y"),
            ("evaluation", "Y"),
            ("unconditional", "Y" if number == 1 else "N"),
        ):
            ET.SubElement(hop, key).text = value
        failed = ET.SubElement(hops, "hop")
        for key, value in (
            ("from", name),
            ("to", "Abort"),
            ("enabled", "Y"),
            ("evaluation", "N"),
            ("unconditional", "N"),
        ):
            ET.SubElement(failed, key).text = value
        previous = name
    final = ET.SubElement(hops, "hop")
    for key, value in (
        ("from", previous),
        ("to", "Success"),
        ("enabled", "Y"),
        ("evaluation", "Y"),
        ("unconditional", "N"),
    ):
        ET.SubElement(final, key).text = value
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    path.chmod(0o600)


def install_adapter(directory: Path, planned_hash: str | None = None) -> dict[str, Any]:
    before = common.host_bytes()
    desired = (common.ROOT / "operations/refresh.sh").read_bytes()
    if before is None or desired.count(FENCE_LINE.encode()) != 1:
        raise RuntimeError("Existing host adapter and exact pending-fence guard required")
    unguarded = desired.replace(FENCE_LINE.encode(), b"").replace(
        b"# Failed/interrupted batch-free migrations leave this protected operator fence.\n", b""
    )
    if before not in (desired, unguarded):
        raise RuntimeError("Host adapter differs beyond the reviewed migration guard")
    if planned_hash is not None and common.digest(before) not in (
        planned_hash,
        common.digest(desired),
    ):
        raise RuntimeError("Host adapter changed since planning")
    backup = directory / "host-refresh-before.sh"
    backup.write_bytes(before)
    backup.chmod(0o600)
    if before != desired:
        target = common.ADAPTER
        temporary = target.parent / (".batchfree-refresh-" + uuid.uuid4().hex)
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, target.stat().st_mode & 0o777
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(desired)
            temporary.chmod(target.stat().st_mode & 0o777)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    if common.host_bytes() != desired:
        raise RuntimeError("Host scheduler guard verification failed")
    return {
        "before_sha256": common.digest(before),
        "after_sha256": common.digest(desired),
        "backup": str(backup),
    }


def event(directory: Path, receipt: dict[str, Any], phase: str, **values: Any) -> None:
    record = {"phase": phase, "recorded_at": datetime.now(UTC).isoformat(), **values}
    events = receipt.setdefault("events", [])
    destination = directory / (f"event-{len(events) + 1:04d}-{phase.lower()}.json")
    if destination.exists():
        raise RuntimeError("Append-only migration event already exists")
    common.write_json(destination, record)
    events.append(str(destination))
    receipt.update(values)
    receipt["phase"] = phase
    common.write_json(directory / "receipt.json", receipt)


def final_checks(
    runtime: dict[str, str], manifest: dict[str, Any], directory: Path
) -> dict[str, Any]:
    before = validate_archive(manifest["graph"])
    after = graph_snapshot(runtime["hop"], directory, "graph-final")
    business = require_business_preserved(before, Path(after["path"]))
    if scaffold_nodes(Path(after["path"])):
        raise RuntimeError("Old graph scaffolding remains")
    if preservation(runtime["pg"]) != manifest["protected_tables"]:
        raise RuntimeError("PostgreSQL source/frozen/accounting/date history changed")
    require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
    if source_scope(runtime["pg"]) != manifest["runs"]:
        raise RuntimeError("Source checkpoint scope changed")
    projection = pg_rows(
        runtime["pg"],
        "SELECT run_id,state FROM ingestion.source_graph_projection "
        "WHERE run_id IN(" + ",".join(dates.quote(x) for x in manifest["runs"]) + ")",
    )
    if {row["run_id"] for row in projection if row["state"] == "READY"} != set(manifest["runs"]):
        raise RuntimeError("Every historical run must have verified direct source evidence")
    rows = native_rows(
        runtime["hop"],
        "MATCH(n:entity:jobPosting) RETURN CASE WHEN count(n)>0 "
        "AND all(n IN collect(n) WHERE valueType(n.first_ingested_at)='ZONED DATETIME NOT NULL' "
        "AND valueType(n.last_ingested_at)='ZONED DATETIME NOT NULL' "
        "AND valueType(n.ingestion_batch_date)='DATE NOT NULL' "
        "AND n.first_ingested_at<=n.last_ingested_at) "
        "THEN 'VERIFIED' ELSE 'FAILED' END AS signature",
        directory,
        "independent-typed-posting-dates",
    )
    if rows != ["VERIFIED"]:
        raise RuntimeError("Independent typed posting-date verification failed")
    return {
        "graph_after": after,
        "business_preservation": business,
        "verified_source_runs": len(projection),
    }


def make_plan(runtime: dict[str, str], directory: Path, preflight: Path | None = None) -> Path:
    prior: dict[str, Any] = {}
    if preflight:
        prior = json.loads(preflight.read_bytes())
        if (
            prior.get("status") not in ("VERIFIED", "VERIFIED_READ_ONLY_PREFLIGHT")
            or prior.get("runtime") != runtime
        ):
            raise RuntimeError("Verified read-only preflight for this exact runtime required")
        graph = prior["graph"]
        validate_archive(graph)
        backing = prior["backing"]
        protected, schema = preservation(runtime["pg"]), dates.schema_preservation(runtime["pg"])
        if protected != prior["protected_tables"] or schema != prior["schema"]:
            raise RuntimeError("Runtime changed since preflight")
    else:
        protected, schema = preservation(runtime["pg"]), dates.schema_preservation(runtime["pg"])
        graph = graph_snapshot(runtime["hop"], directory, "graph-before")
        backing = prove_backing(runtime["pg"], Path(graph["path"]))
    entries, _ = deployment.snapshot(runtime)
    manifest = {
        "version": 1,
        "status": "PLANNED",
        "created_at": datetime.now(UTC).isoformat(),
        "runtime": runtime,
        "graph": graph,
        "backing": backing,
        "runs": source_scope(runtime["pg"]),
        "protected_tables": protected,
        "schema": schema,
        "artifacts": entries,
        "host_adapter_sha256": common.digest(common.host_bytes() or b""),
        "source_requests": 0,
        "paid_calls": 0,
        "preflight": str(preflight) if preflight else None,
        "database_backup": prior.get("database_backup") if preflight else None,
    }
    if sorted(backing["runs"]) != manifest["runs"]:
        raise RuntimeError("Every accepted checkpoint must have a proven removable graph batch")
    path = directory / "manifest.json"
    common.write_json(path, manifest)
    return path


def apply_plan(
    runtime: dict[str, str],
    manifest_path: Path,
    directory: Path,
    resumed: dict[str, Any] | None = None,
    backup_restore_proof: Path | None = None,
) -> Path:
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("version") != 1 or manifest.get("runtime") != runtime:
        raise RuntimeError("Migration manifest/runtime changed")
    before = validate_archive(manifest["graph"])
    entries, _ = deployment.snapshot(runtime)
    if {k: v["after"] for k, v in entries.items()} != {
        k: v["after"] for k, v in manifest["artifacts"].items()
    }:
        raise RuntimeError("Reviewed desired artifacts changed")
    if (
        preservation(runtime["pg"]) != manifest["protected_tables"]
        or source_scope(runtime["pg"]) != manifest["runs"]
    ):
        raise RuntimeError("Protected source/history changed since migration plan")
    require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
    receipt = resumed or {
        "version": 1,
        "status": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "runtime": runtime,
        "token": uuid.uuid4().hex,
        "source_requests": 0,
        "paid_calls": 0,
    }
    attempt = directory / ("attempt-" + uuid.uuid4().hex)
    attempt.mkdir(mode=0o700)
    fence = common.STATE / "batchfree-migration.pending"
    if fence.exists() and json.loads(fence.read_bytes()).get("token") != receipt["token"]:
        raise RuntimeError("Another migration owns the durable scheduler fence")
    try:
        fresh = graph_snapshot(runtime["hop"], attempt, "graph-fresh")
        if resumed:
            require_business_preserved(before, Path(fresh["path"]))
        elif fresh["sha256"] != manifest["graph"]["sha256"]:
            raise RuntimeError("Graph changed since reviewed plan; no migration writes")
        event(directory, receipt, "FRESHNESS_VERIFIED", fresh_graph=fresh)
        if "database_backup" not in receipt:
            event(directory, receipt, "BACKING_UP")
            backup = manifest.get("database_backup") or deployment.backup_database(
                runtime["pg"], attempt
            )
            with Path(backup["path"]).open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != backup["sha256"]:
                    raise RuntimeError("Protected full database backup checksum changed")
            event(
                directory,
                receipt,
                "BACKUP_VALIDATED",
                database_backup=backup,
            )
        if "recovery" not in receipt:
            event(
                directory, receipt, "RECOVERY_EXPORTED", recovery=prepare_recovery(before, attempt)
            )
        proof_path = backup_restore_proof or (
            Path(receipt["backup_restore_proof"]) if receipt.get("backup_restore_proof") else None
        )
        if proof_path is None:
            raise RuntimeError(
                "Actual isolated PostgreSQL backup-restore proof required before migration writes"
            )
        proof: dict[str, Any] = json.loads(proof_path.read_bytes())
        backup_evidence: dict[str, Any] = proof.get("database_backup") or proof.get("backup") or {}
        digest = (
            proof.get("database_backup_sha256")
            or proof.get("backup_sha256")
            or backup_evidence.get("sha256")
        )
        if (
            proof.get("status") not in ("VERIFIED", "PASSED")
            or digest != receipt["database_backup"]["sha256"]
        ):
            raise RuntimeError(
                "Verified isolated restore proof must match the exact full PostgreSQL backup"
            )
        event(
            directory,
            receipt,
            "BACKUP_RESTORE_PROVEN",
            backup_restore_proof=str(proof_path.resolve()),
        )
        adapter = install_adapter(attempt, manifest["host_adapter_sha256"])
        event(directory, receipt, "SCHEDULER_GUARD_DEPLOYED", host_adapter=adapter)
        if not fence.exists():
            common.write_json(
                fence, {"token": receipt["token"], "receipt": str(directory / "receipt.json")}
            )
        event(directory, receipt, "WRITERS_FENCED")
        entries, _ = deployment.snapshot(runtime)
        deploy_manifest = attempt / "deployment-manifest.json"
        state = common.db_state(runtime["pg"])
        common.write_json(deploy_manifest, deployment.plan_manifest(runtime, state, entries))
        deployment_receipt = deployment.apply(deploy_manifest, runtime, state)
        event(
            directory,
            receipt,
            "PUBLIC_WRITERS_DEPLOYED",
            deployment_receipt=str(deployment_receipt),
        )
        install = attempt / "install-focused.hwf"
        install_workflow(install)
        dates.temporary_native(runtime["hop"], install, attempt, "install-focused")
        require_schema(manifest["schema"], dates.schema_preservation(runtime["pg"]))
        if preservation(runtime["pg"]) != manifest["protected_tables"]:
            raise RuntimeError("Focused SQL installation changed protected rows")
        event(directory, receipt, "FOCUSED_SQL_INSTALLED")
        if not receipt.get("projection_verified"):
            dates.native(
                runtime["hop"],
                common.PROJECT + "/graph/migrate_source_graph.hwf",
                attempt,
                "project-all-checkpointed",
                {"RUN_ID": "ALL_CHECKPOINTED"},
            )
            projected = graph_snapshot(runtime["hop"], attempt, "graph-projected")
            business = require_business_preserved(before, Path(projected["path"]))
            prove_backing(
                runtime["pg"],
                Path(projected["path"]),
                Path(manifest["backing"]["postgres_evidence"]),
            )
            if preservation(runtime["pg"]) != manifest["protected_tables"]:
                raise RuntimeError("Direct projection changed protected PostgreSQL rows")
            event(
                directory,
                receipt,
                "DIRECT_PROJECTION_VERIFIED",
                projection_verified=True,
                projected_graph=projected,
                business_preservation=business,
            )
        else:
            projected = fresh
        event(directory, receipt, "REMOVAL_STARTING")
        deletion = attempt / "deletion"
        deletion.mkdir(mode=0o700)
        prove_backing(
            runtime["pg"], Path(projected["path"]), Path(manifest["backing"]["postgres_evidence"])
        )
        result = remove_scaffolding(runtime["hop"], Path(projected["path"]), deletion)
        event(directory, receipt, "SCAFFOLD_REMOVED", removal_batches=len(result))
        replay = pg_rows(
            runtime["pg"],
            "SELECT r.run_id FROM ingestion.run r "
            "JOIN ingestion.graph_export g USING(run_id) WHERE r.state='READY' AND r.mode<>'SMOKE' "
            "AND r.source_id='qnet_schedule' ORDER BY r.created_at,r.run_id LIMIT 1",
        )
        if not replay:
            raise RuntimeError(
                "Small exact historical source run required for production writer replay proof"
            )
        dates.native(
            runtime["hop"],
            common.PROJECT + "/graph/load_snapshot.hwf",
            attempt,
            "historical-source-replay",
            {"RUN_ID": replay[0]["run_id"]},
        )
        event(
            directory,
            receipt,
            "BATCHFREE_FUTURE_REPLAY_VERIFIED",
            replay_run_id=replay[0]["run_id"],
        )
        final = final_checks(runtime, manifest, attempt)
        if any(entry["change"] for entry in deployment.snapshot(runtime)[0].values()):
            raise RuntimeError("Public writer artifacts drifted during migration")
        dates.require_idle(runtime["pg"])
        event(
            directory,
            receipt,
            "VERIFIED",
            status="VERIFIED",
            finished_at=datetime.now(UTC).isoformat(),
            **final,
        )
        if json.loads(fence.read_bytes()).get("token") != receipt["token"]:
            raise RuntimeError("Scheduler fence ownership changed")
        fence.unlink()
        event(directory, receipt, "SCHEDULER_RESUMED", scheduler_fence_removed=True)
        return directory / "receipt.json"
    except BaseException as error:
        event(
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
            "Migration stopped; inspect protected receipt " + str(directory / "receipt.json")
        ) from error


def execute(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    common.STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if common.STATE.is_symlink():
        raise RuntimeError("Runtime state must not be a symlink")
    descriptor = os.open(
        common.STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Scheduler/native lock is busy") from error
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        dates.require_idle(runtime["pg"])
        if args.mode == "plan":
            if (common.STATE / "batchfree-migration.pending").exists():
                raise RuntimeError("Resume/recover the existing fenced migration")
            directory = common.STATE / ("batchfree-plan-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            return make_plan(runtime, directory, args.preflight)
        if args.mode == "apply":
            directory = common.STATE / ("batchfree-apply-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            return apply_plan(
                runtime, args.path, directory, backup_restore_proof=args.backup_restore_proof
            )
        receipt = json.loads(args.path.read_bytes())
        if receipt.get("runtime") != runtime:
            raise RuntimeError("Recovery runtime identity changed")
        directory = args.path.resolve().parent
        manifest_path = Path(receipt["manifest"])
        if args.mode == "resume":
            return apply_plan(runtime, manifest_path, directory, receipt, args.backup_restore_proof)
        fence = common.STATE / "batchfree-migration.pending"
        if not fence.exists() or json.loads(fence.read_bytes()).get("token") != receipt["token"]:
            raise RuntimeError("Recovery requires the original durable writer fence")
        attempt = directory / ("recovery-" + uuid.uuid4().hex)
        attempt.mkdir(mode=0o700)
        count = recover_scaffolding(runtime["hop"], receipt["recovery"], attempt)
        graph = graph_snapshot(runtime["hop"], attempt, "restored-scaffolding")
        prove_backing(runtime["pg"], Path(graph["path"]))
        manifest = json.loads(manifest_path.read_bytes())
        require_business_preserved(validate_archive(manifest["graph"]), Path(graph["path"]))
        if preservation(runtime["pg"]) != manifest["protected_tables"]:
            raise RuntimeError("Protected PostgreSQL history changed during scaffold recovery")
        event(
            directory,
            receipt,
            "SCAFFOLD_RECOVERED_MIGRATION_PENDING",
            status="RECOVERED_FENCED",
            recovery_statements=count,
            recovered_graph=graph,
        )
        return args.path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "resume", "recover"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--backup-restore-proof", type=Path)
    args = parser.parse_args()
    if (args.mode == "plan") != (args.path is None) or (args.preflight and args.mode != "plan"):
        parser.error(
            "plan accepts optional --preflight; apply/resume/recover require a protected path"
        )
    if args.backup_restore_proof and args.mode not in ("apply", "resume"):
        parser.error("--backup-restore-proof is only used by apply/resume")
    print(json.dumps({"receipt": str(execute(args))}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
