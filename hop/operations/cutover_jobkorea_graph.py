#!/usr/bin/env python3
"""Plan, remove retired JobKorea graph objects, and verify fresh publication.

No source/model requests and no PostgreSQL row writes. The immutable manifest
contains exact cohort IDs, publication pins, typed graph snapshots and removal
IDs. `apply` only removes old associations and absent-cohort posting nodes;
normal native workflows first publish the new source and mapping graph. `verify`
then proves exact cohort/publications and preserves every other graph object.
Use this on the runtime host while the replacement ledger is BLOCKED. A failed
or interrupted replacement remains BLOCKED; this tool never enables serving.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import selectors
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import migrate_batchfree_graph as graph

PREFIX = "source:posting:jobkorea:"
ASSOCIATIONS = frozenset(("INFERRED_NCS_OCCUPATION", "INFERRED_ONET_OCCUPATION"))
BATCH_SIZE = 200


def string(props: dict[str, list[str]], key: str) -> str | None:
    item = props.get(key)
    return item[1] if item and item[0] == "STRING NOT NULL" else None


def identity(native_id: str) -> str:
    return PREFIX + hashlib.sha256(native_id.encode()).hexdigest()


def immutable_json(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def classify(
    path: Path,
    cohort: set[str],
    target_run: str | None = None,
    wanted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Only exact source identities/labels may be removed; unknown attachments stop."""
    source_nodes: dict[str, str] = {}
    all_ids: dict[str, str] = {}
    protected: dict[str, str] = {}
    for row in graph.records(path, "NODE"):
        props = graph.properties(row[-1])
        value = string(props, "id")
        if value:
            all_ids[row[0]] = value
        declared = string(props, "source_id") == "jobkorea"
        if value and value.startswith(PREFIX):
            labels = set(graph.unpack(row[1]))
            if not {"entity", "jobPosting"} <= labels or string(props, "kind") != "JobPosting":
                raise RuntimeError("JobKorea identity has unexpected graph labels/kind")
            if value in source_nodes.values():
                raise RuntimeError("Duplicate JobKorea graph identity")
            source_nodes[row[0]] = value
        elif (
            target_run
            and "metadataOccupationProjection" in graph.unpack(row[1])
            and string(props, "job_run_id") == target_run
            and string(props, "managed_by") == "jobtology-metadata-occupation"
        ):
            continue
        elif declared:
            raise RuntimeError("JobKorea source marker on an unexpected graph identity")
        else:
            protected["NODE:" + row[0]] = json.dumps(row, ensure_ascii=False)
    retired = {eid for eid, value in source_nodes.items() if value not in cohort}
    remove_edges: list[str] = []
    fresh_ncs = {row["candidate_id"]: row for row in wanted["ncs"]} if wanted else {}
    fresh_onet = {row["edge_id"]: row for row in wanted["onet"]} if wanted else {}
    for row in graph.records(path, "REL"):
        eid, start, end, kind, _ = row
        if start in source_nodes and kind in ASSOCIATIONS:
            props = graph.properties(row[-1])
            expected_row = (
                fresh_ncs.get(string(props, "candidate_id"))
                if kind == "INFERRED_NCS_OCCUPATION"
                else fresh_onet.get(string(props, "id"))
            )
            fresh = bool(
                expected_row
                and expected_row["posting_identity"] == source_nodes[start]
                and expected_row["occupation_identity"] == all_ids.get(end)
            )
            if kind == "INFERRED_NCS_OCCUPATION":
                fresh = fresh and string(props, "projection_token") == (wanted or {}).get(
                    "ncs_token"
                )
            elif fresh:
                fresh = all(
                    scalar_equal(props.get(key), value)
                    for key, value in expected_row["properties"].items()
                )
            if not fresh:
                remove_edges.append(eid)
        elif start in retired or end in retired:
            raise RuntimeError("Retired posting has an unexpected attachment; removal refused")
        else:
            protected["REL:" + eid] = json.dumps(row, ensure_ascii=False)
    digest = hashlib.sha256()
    for key, value in sorted(protected.items()):
        digest.update(json.dumps([key, value], ensure_ascii=False).encode())
    return {
        "source_nodes": source_nodes,
        "retire_nodes": sorted(retired),
        "remove_edges": sorted(remove_edges),
        "protected_count": len(protected),
        "protected_sha256": digest.hexdigest(),
    }


def current_plan(pg: str) -> dict[str, Any]:
    value = json.loads(graph.deployment.sql(pg, "SELECT ingestion.jobkorea_replacement_current();"))
    if not isinstance(value, dict) or value.get("phase") != "BLOCKED":
        raise RuntimeError("An exact BLOCKED JobKorea replacement ledger is required")
    return value


def expected(
    pg: str, plan: dict[str, Any], ncs_token: str, onet_publication: str
) -> dict[str, Any]:
    quote = graph.dates.quote
    jobs, ncs, task = (plan[key] for key in ("job_run_id", "ncs_run_id", "onet_task_id"))
    ids = graph.pg_rows(
        pg,
        "SELECT DISTINCT normalized->>'posting_id' AS native_id "
        "FROM ingestion.ready_record WHERE source_id='jobkorea' AND run_id=" + quote(jobs),
    )
    cohort = sorted(identity(row["native_id"]) for row in ids if row["native_id"])
    if len(cohort) != plan["expected_count"] or len(set(cohort)) != len(cohort):
        raise RuntimeError("Exact replacement cohort count/identity mismatch")
    guards = graph.pg_rows(
        pg,
        "SELECT writer_token FROM enrichment.metadata_occupation_graph_guard "
        "WHERE writer_token="
        + quote(ncs_token)
        + " AND job_run_id="
        + quote(jobs)
        + " AND ncs_run_id="
        + quote(ncs)
        + " AND include_unreviewed AND state='READY'",
    )
    if len(guards) != 1:
        raise RuntimeError("Exact new NCS graph publication token is required")
    ncs_rows = graph.pg_rows(
        pg,
        "SELECT posting_identity,occupation_identity,candidate_id,payload::text AS payload_json, "
        "enrichment.hash(payload::text) AS payload_hash FROM "
        "enrichment.metadata_occupation_graph_rows("
        + quote(jobs)
        + ","
        + quote(ncs)
        + ",true) ORDER BY candidate_id",
    )
    onet_guard = graph.pg_rows(
        pg,
        "SELECT publication_id FROM onet_matching.graph_guard "
        "WHERE publication_id="
        + quote(onet_publication)
        + " AND task_id="
        + quote(task)
        + " AND state='VERIFIED'",
    )
    if len(onet_guard) != 1:
        raise RuntimeError("Exact new O*NET graph publication is required")
    onet_rows = graph.pg_rows(
        pg,
        "SELECT posting_identity,occupation_identity,edge_id,properties, "
        "payload_json::jsonb->>'source_run_id' AS source_run_id "
        "FROM onet_matching.graph_edge WHERE publication_id="
        + quote(onet_publication)
        + " ORDER BY edge_id",
    )
    if any(row["posting_identity"] not in cohort for row in [*ncs_rows, *onet_rows]):
        raise RuntimeError("Fresh publication includes another source/cohort")
    if any(row["source_run_id"] != jobs for row in onet_rows):
        raise RuntimeError("O*NET publication has an old source pin")
    return {
        "cohort": cohort,
        "ncs_token": ncs_token,
        "onet_publication": onet_publication,
        "ncs": ncs_rows,
        "onet": onet_rows,
    }


def postgres_state(pg: str) -> dict[str, Any]:
    """All application rows; frozen O*NET input uses its immutable content pins."""
    tables = graph.pg_rows(
        pg,
        "SELECT n.nspname AS schema,c.relname AS name FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN('r','p') "
        "AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' "
        "ORDER BY n.nspname,c.relname",
    )
    result: dict[str, Any] = {}
    for table in tables:
        if any(not re.fullmatch(r"[a-z_][a-z_0-9]*", table[key]) for key in ("schema", "name")):
            raise RuntimeError("Unexpected application table identifier")
        name = table["schema"] + "." + table["name"]
        qualified = '"' + table["schema"] + '"."' + table["name"] + '"'
        payload = "to_jsonb(t)::text"
        basis = "FULL_ROW_SHA256"
        if name == "onet_matching.input":
            # Immutable triggers reject UPDATE/DELETE/TRUNCATE. These original
            # frozen pins bind the large source/candidate/request payloads.
            payload = (
                "jsonb_build_array(task_id,posting_identity,source_id,source_run_id,"
                "source_record_id,source_facts_sha256,source_hash,candidates_hash,"
                "request_hash,input_hash,ordinal)::text"
            )
            basis = "IMMUTABLE_INPUT_CONTENT_PINS_SHA256"
        rows = graph.pg_rows(
            pg,
            "SELECT count(*) AS row_count,encode(sha256(convert_to("
            "coalesce(string_agg(row_hash,'' ORDER BY row_hash),''),'UTF8')),'hex') AS sha256 "
            "FROM (SELECT encode(sha256(convert_to(" + payload + ",'UTF8')),'hex') AS row_hash "
            "FROM " + qualified + " t) hashes",
        )
        result[name] = {**rows[0], "basis": basis}
    return result


@contextmanager
def writer_gate(pg: str):
    """Hold the shared registration gate for the complete native mutation window."""
    process = subprocess.Popen(
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
            "-U",
            "postgres",
            "-d",
            "jobtology",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(
            "SET statement_timeout='10s'; DO $$ BEGIN IF NOT "
            "pg_try_advisory_lock(hashtextextended('jobtology-retention-gate-v1',0)) "
            "THEN RAISE EXCEPTION 'GRAPH_WRITER_GATE_BUSY'; END IF; "
            "IF EXISTS(SELECT 1 FROM retention.writer) THEN "
            "RAISE EXCEPTION 'GRAPH_WRITERS_ACTIVE'; END IF; END $$;\n"
            "\\echo JOBKOREA_GRAPH_GATE_HELD\n"
        )
        process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if (
                not selector.select(timeout=15)
                or process.stdout.readline().strip() != "JOBKOREA_GRAPH_GATE_HELD"
            ):
                raise RuntimeError("Could not acquire the PostgreSQL graph writer gate")
        if process.poll() is not None:
            raise RuntimeError("Graph writer gate session exited")
        yield process
        if process.poll() is not None:
            raise RuntimeError("Graph writer gate session was lost")
    finally:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def delete_query(kind: str, ids: list[str]) -> str:
    if kind not in ("NODE", "REL") or not 0 < len(ids) <= BATCH_SIZE:
        raise ValueError("Invalid bounded JobKorea graph deletion")
    literals = json.dumps(ids)
    if kind == "REL":
        return (
            "MATCH (a)-[r]->() WHERE elementId(r) IN "
            + literals
            + " AND a.id STARTS WITH "
            + json.dumps(PREFIX)
            + " AND type(r) IN "
            + json.dumps(sorted(ASSOCIATIONS))
            + " WITH collect(r) AS objects FOREACH(r IN objects | DELETE r) "
            + "RETURN toString(size(objects)) AS signature"
        )
    return (
        "MATCH (n:entity:jobPosting) WHERE elementId(n) IN "
        + literals
        + " AND n.id STARTS WITH "
        + json.dumps(PREFIX)
        + " AND n.kind='JobPosting' WITH collect(n) AS objects "
        + "FOREACH(n IN objects | DELETE n) RETURN toString(size(objects)) AS signature"
    )


def scalar_equal(actual: list[str] | None, expected: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return actual == ["STRING NOT NULL", expected]
    if isinstance(expected, bool):
        return actual == ["BOOLEAN NOT NULL", str(expected).lower()]
    if isinstance(expected, int):
        return actual == ["INTEGER NOT NULL", str(expected)]
    if isinstance(expected, float):
        return bool(actual and actual[0] == "FLOAT NOT NULL" and float(actual[1]) == expected)
    raise RuntimeError("Unsupported publication property type")


def prove_fresh(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    wanted = manifest["expected"]
    scope = classify(path, set(wanted["cohort"]), manifest["replacement"]["job_run_id"], wanted)
    if sorted(scope["source_nodes"].values()) != wanted["cohort"]:
        raise RuntimeError("Fresh graph is not the exact replacement cohort")
    expected_edges: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in wanted["ncs"]:
        expected_edges[
            (
                row["posting_identity"],
                row["occupation_identity"],
                "INFERRED_NCS_OCCUPATION",
                row["candidate_id"],
            )
        ] = {
            "job_run_id": manifest["replacement"]["job_run_id"],
            "ncs_run_id": manifest["replacement"]["ncs_run_id"],
            "projection_token": wanted["ncs_token"],
            "payload_json": row["payload_json"],
            "payload_hash": row["payload_hash"],
        }
    for row in wanted["onet"]:
        expected_edges[
            (
                row["posting_identity"],
                row["occupation_identity"],
                "INFERRED_ONET_OCCUPATION",
                row["edge_id"],
            )
        ] = row["properties"]
    nodes: dict[str, str] = {}
    for row in graph.records(path, "NODE"):
        value = string(graph.properties(row[-1]), "id")
        if value:
            nodes[row[0]] = value
        if (
            row[0] in scope["source_nodes"]
            and string(graph.properties(row[-1]), "source_run_id")
            != manifest["replacement"]["job_run_id"]
        ):
            raise RuntimeError("Replacement posting retains an old source run")
    found: set[tuple[str, str, str, str]] = set()
    for row in graph.records(path, "REL"):
        _, start, end, kind, payload = row
        if start not in scope["source_nodes"] or kind not in ASSOCIATIONS:
            continue
        props = graph.properties(payload)
        key = (
            nodes[start],
            nodes[end],
            kind,
            string(props, "candidate_id" if kind == "INFERRED_NCS_OCCUPATION" else "id"),
        )
        if key not in expected_edges or key in found:
            raise RuntimeError("Old, duplicate or unexpected JobKorea association remains")
        if any(
            not scalar_equal(props.get(name), value) for name, value in expected_edges[key].items()
        ):
            raise RuntimeError("Fresh association publication/source pin mismatch")
        found.add(key)
    if found != set(expected_edges):
        raise RuntimeError("Fresh JobKorea mappings are incomplete")
    return {
        "posting_count": len(scope["source_nodes"]),
        "ncs_count": len(wanted["ncs"]),
        "onet_count": len(wanted["onet"]),
    }


def protected_equal(before: dict[str, Any], after: dict[str, Any]) -> None:
    for key in ("protected_count", "protected_sha256"):
        if before[key] != after[key]:
            raise RuntimeError("Another source, shared catalogue or protected graph object changed")


def execute(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    common = graph.common
    common.STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = common.STATE / "refresh.lock"
    if args.lock_fd is None:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    else:
        held, target = os.fstat(args.lock_fd), lock_path.stat(follow_symlinks=False)
        if (held.st_dev, held.st_ino) != (target.st_dev, target.st_ino):
            raise RuntimeError("Inherited lock descriptor is not the exact host refresh.lock")
        descriptor = os.dup(args.lock_fd)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Scheduler/native refresh lock is busy") from error
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        directory = common.STATE / ("jobkorea-graph-" + args.mode + "-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        with writer_gate(runtime["pg"]) as gate:
            replacement = current_plan(runtime["pg"])
            if args.mode == "plan":
                if not args.ncs_token or not args.onet_publication:
                    raise ValueError("plan requires --ncs-token and --onet-publication")
                wanted = expected(runtime["pg"], replacement, args.ncs_token, args.onet_publication)
                snapshot = graph.graph_snapshot(runtime["hop"], directory, "before")
                scope = classify(
                    Path(snapshot["path"]), set(wanted["cohort"]), replacement["job_run_id"], wanted
                )
                manifest = {
                    "version": 1,
                    "runtime": runtime,
                    "replacement": replacement,
                    "expected": wanted,
                    "graph": snapshot,
                    "scope": scope,
                    "postgres": postgres_state(runtime["pg"]),
                    "source_requests": 0,
                    "paid_calls": 0,
                }
                path = directory / "manifest.json"
                immutable_json(path, manifest)
                immutable_json(
                    path.with_suffix(".sha256.json"),
                    {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                )
                return path
            recorded_hash = json.loads(args.path.with_suffix(".sha256.json").read_bytes())["sha256"]
            if hashlib.sha256(args.path.read_bytes()).hexdigest() != recorded_hash:
                raise RuntimeError("Immutable manifest checksum changed")
            manifest = json.loads(args.path.read_bytes())
            if (
                manifest.get("version") != 1
                or manifest["runtime"] != runtime
                or any(
                    manifest["replacement"].get(key) != replacement.get(key)
                    for key in (
                        "replacement_id",
                        "job_run_id",
                        "input_sha256",
                        "expected_count",
                        "ncs_run_id",
                        "onet_task_id",
                    )
                )
            ):
                raise RuntimeError("Replacement/runtime changed since the immutable plan")
            if (
                expected(
                    runtime["pg"],
                    replacement,
                    manifest["expected"]["ncs_token"],
                    manifest["expected"]["onet_publication"],
                )
                != manifest["expected"]
            ):
                raise RuntimeError("Publication inputs changed since plan")
            snapshot = graph.graph_snapshot(runtime["hop"], directory, "fresh")
            scope = classify(
                Path(snapshot["path"]),
                set(manifest["expected"]["cohort"]),
                replacement["job_run_id"],
                manifest["expected"],
            )
            if args.mode == "apply":
                if postgres_state(runtime["pg"]) != manifest["postgres"]:
                    raise RuntimeError("PostgreSQL history changed since plan; no writes performed")
                if snapshot["sha256"] != manifest["graph"]["sha256"]:
                    raise RuntimeError("Graph changed since plan; no writes performed")
                for kind, ids in (("REL", scope["remove_edges"]), ("NODE", scope["retire_nodes"])):
                    for offset in range(0, len(ids), BATCH_SIZE):
                        if gate.poll() is not None:
                            raise RuntimeError(
                                "Graph writer gate was lost; leave replacement BLOCKED"
                            )
                        batch = ids[offset : offset + BATCH_SIZE]
                        result = graph.native_rows(
                            runtime["hop"],
                            delete_query(kind, batch),
                            directory,
                            f"delete-{kind.lower()}-{offset}",
                            write=True,
                        )
                        if result != [str(len(batch))]:
                            raise RuntimeError(
                                "Bounded deletion count mismatch; leave replacement BLOCKED"
                            )
                snapshot = graph.graph_snapshot(runtime["hop"], directory, "removed")
                scope = classify(
                    Path(snapshot["path"]),
                    set(manifest["expected"]["cohort"]),
                    replacement["job_run_id"],
                    manifest["expected"],
                )
                if scope["retire_nodes"] or scope["remove_edges"]:
                    raise RuntimeError("Retired JobKorea graph objects remain")
                status, proof = (
                    "REMOVED_REPLACEMENT_BLOCKED",
                    prove_fresh(Path(snapshot["path"]), manifest),
                )
            else:
                status, proof = (
                    "VERIFIED",
                    prove_fresh(Path(snapshot["path"]), manifest),
                )
            protected_equal(manifest["scope"], scope)
            # Source publication/checkpoint ledgers may append between apply and verify.
            # Every graph-only command itself must preserve all PostgreSQL rows.
            if args.mode == "apply" and postgres_state(runtime["pg"]) != manifest["postgres"]:
                raise RuntimeError("PostgreSQL history changed during graph-only cutover")
            receipt = directory / "receipt.json"
            immutable_json(
                receipt,
                {
                    "status": status,
                    "job_run_id": replacement["job_run_id"],
                    "replacement_id": replacement["replacement_id"],
                    "ncs_writer_token": manifest["expected"]["ncs_token"],
                    "onet_publication_id": manifest["expected"]["onet_publication"],
                    "manifest": str(args.path.resolve()),
                    "manifest_sha256": hashlib.sha256(args.path.read_bytes()).hexdigest(),
                    "graph": snapshot,
                    "proof": proof,
                    "source_requests": 0,
                    "paid_calls": 0,
                },
            )
            return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "verify"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--lock-fd", type=int, help="Inherited descriptor of host refresh.lock")
    parser.add_argument("--ncs-token")
    parser.add_argument("--onet-publication")
    args = parser.parse_args()
    if (args.mode == "plan") != (args.path is None):
        parser.error("plan takes no path; apply/verify require the immutable manifest path")
    print(json.dumps({"receipt": str(execute(args))}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
