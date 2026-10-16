#!/usr/bin/env python3
"""Plan/apply additive posting dates through existing private native Hop connections.

Deploy public artifacts with deploy_jobkorea_runtime.py first. Plan snapshots the
affected posting nodes and every incident edge in bounded native reads. Apply
checks that plan, takes a full database backup, installs only the date migration,
records supplied collection evidence and updates existing posting properties.
No source, attachment or model request workflow is reachable from this helper.
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
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import deploy_jobkorea_runtime as deployment
import reconcile_runtime as common

DATE_PROPERTIES = (
    "first_ingested_at",
    "last_ingested_at",
    "latest_ingestion_run_id",
    "ingestion_batch_date",
    "ingestion_time_basis",
    "scraped_at",
    "scraped_at_basis",
    "scraped_at_evidence_reference",
)
LEDGERS = (
    "ingestion.jobkorea_collection_time_evidence",
    "ingestion.posting_ingestion_observation",
)
ARTIFACTS = (
    "graph/sql/001_posting_ingestion_dates.sql",
    "graph/install_posting_dates.hwf",
    "graph/load_posting_dates.hpl",
    "graph/verify_posting_dates.hpl",
    "graph/update_posting_dates.hwf",
)
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")
CHUNK_SIZE = 500


def exact_identity(value: str) -> str:
    if not IDENTITY.fullmatch(value) or value == "LATEST":
        raise ValueError("Use an exact safe identity, never LATEST")
    return value


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected an ISO timestamp with timezone") from error
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("Collection time must include its UTC offset")
    return parsed.astimezone(UTC).isoformat()


def scope(pg: str, job_run: str) -> dict[str, Any]:
    exact_identity(job_run)
    query = f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='60s';
SELECT jsonb_build_object(
 'job_run',(SELECT jsonb_build_object('run_id',u.run_id,'state',u.state,
   'file_sha256',i.file_sha256,'imported_at',i.imported_at)
   FROM ingestion.run u JOIN ingestion.jobkorea_import i USING(run_id)
   WHERE u.run_id={quote(job_run)} AND u.source_id='jobkorea'),
 'runs',(SELECT jsonb_agg(run_id ORDER BY run_id) FROM (
   SELECT DISTINCT q.run_id FROM ingestion.graph_reference q
   JOIN ingestion.graph_export g USING(run_id)
   JOIN ingestion.run u USING(run_id)
   WHERE q.kind='JobPosting' AND u.state='READY' AND u.mode<>'SMOKE') t),
 'identities',(SELECT jsonb_agg(identity_id ORDER BY identity_id) FROM (
   SELECT DISTINCT q.identity_id FROM ingestion.graph_reference q
   JOIN ingestion.graph_export g USING(run_id)
   JOIN ingestion.run u USING(run_id)
   WHERE q.kind='JobPosting' AND u.state='READY' AND u.mode<>'SMOKE') t),
 'source_counts',(SELECT jsonb_object_agg(source_id,n) FROM (
   SELECT u.source_id,count(DISTINCT q.identity_id) n FROM ingestion.graph_reference q
   JOIN ingestion.graph_export g USING(run_id) JOIN ingestion.run u USING(run_id)
   WHERE q.kind='JobPosting' AND u.state='READY' AND u.mode<>'SMOKE'
   GROUP BY u.source_id) t));
COMMIT;"""
    value = json.loads(deployment.sql(pg, query))
    if not value.get("job_run") or value["job_run"]["state"] != "READY":
        raise RuntimeError("Exact READY JobKorea import receipt is required")
    if job_run not in (value.get("runs") or []):
        raise RuntimeError("Exact JobKorea source graph checkpoint is required")
    for name in ("runs", "identities"):
        if not value.get(name):
            raise RuntimeError("No accepted posting graph scope")
        for item in value[name]:
            exact_identity(item)
    return value


def preservation(pg: str) -> dict[str, Any]:
    """Existing application rows remain exact; two additive ledgers only append."""
    state: dict[str, Any] = deployment.full_preservation_state(pg)
    for ledger in LEDGERS:
        state.pop(ledger, None)
    return state


def require_idle(pg: str) -> None:
    common.db_state(pg)
    active = json.loads(
        deployment.sql(
            pg,
            """BEGIN READ ONLY;
SELECT jsonb_build_object(
 'running_batches',(SELECT count(*) FROM enrichment.batch
  WHERE state='RUNNING' AND created_at>clock_timestamp()-interval '24 hours'),
 'reserved_requests',(SELECT count(*) FROM enrichment.attempt
  WHERE state='RESERVED' AND reserved_at>clock_timestamp()-interval '24 hours'));
COMMIT;""",
        )
    )
    if any(active.values()):
        raise RuntimeError("LLM runtime is active; date backfill requires an idle runtime")


def schema_preservation(pg: str) -> dict[str, Any]:
    return json.loads(
        deployment.sql(
            pg,
            """BEGIN READ ONLY;
SELECT jsonb_build_object(
 'functions',(SELECT coalesce(jsonb_object_agg(p.oid::regprocedure::text,
  encode(sha256(convert_to(pg_get_functiondef(p.oid)||coalesce(p.proacl::text,''),'UTF8')),'hex')),'{}')
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname IN('attachment','catalog','cs','enrichment','ingestion','ontology','retention')
   AND p.prokind IN('f','p')),
 'triggers',(SELECT coalesce(jsonb_object_agg(n.nspname||'.'||c.relname||':'||t.tgname,
  encode(sha256(convert_to(pg_get_triggerdef(t.oid)||t.tgenabled::text,'UTF8')),'hex')),'{}')
  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE NOT t.tgisinternal
   AND n.nspname IN('attachment','catalog','cs','enrichment','ingestion','ontology','retention')));
COMMIT;""",
        )
    )


def require_schema_preserved(before: dict[str, Any], after: dict[str, Any]) -> None:
    for category in ("functions", "triggers"):
        for name, digest in before[category].items():
            if after[category].get(name) != digest:
                raise RuntimeError("Existing application schema changed: " + name)


def ledger_rows(pg: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name in LEDGERS:
        present = deployment.sql(
            pg, f"BEGIN READ ONLY; SELECT to_regclass({quote(name)}) IS NOT NULL; COMMIT;"
        )
        if present == "t":
            rows = deployment.sql(
                pg,
                f"""BEGIN READ ONLY;
SELECT coalesce(jsonb_agg(to_jsonb(t)::text ORDER BY to_jsonb(t)::text),'[]'::jsonb)
FROM {name} t; COMMIT;""",
            )
            result[name] = json.loads(rows)
        else:
            result[name] = []
    return result


def require_append_only(before: dict[str, list[str]], after: dict[str, list[str]]) -> None:
    for name in LEDGERS:
        if not set(before[name]).issubset(after[name]):
            raise RuntimeError("Previously recorded date evidence changed: " + name)


def artifacts(hop: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in ARTIFACTS:
        path = common.ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Missing public date artifact: " + relative)
        data = path.read_bytes()
        if deployment.remote_bytes(hop, relative) != data:
            raise RuntimeError("Deploy matching date artifacts before running: " + relative)
        result[relative] = common.digest(data)
    return result


def native(
    hop: str, path: str, directory: Path, label: str, params: dict[str, str] | None = None
) -> Path:
    log = directory / (label + ".log")
    args = [
        "docker",
        "exec",
        "-e",
        "HOP_OPTIONS=-Xmx1024m",
        "-w",
        "/usr/local/tomcat/webapps/ROOT",
        hop,
        "bash",
        "-c",
        'umask 077; exec bash hop-run.sh "$@"',
        "--",
        "-j",
        "default",
        "-r",
        "graph-local",
        "-f",
        path,
        "-l",
        "Basic",
    ]
    if params:
        for key, value in params.items():
            if not re.fullmatch(r"[A-Z_][A-Z_0-9]*", key) or any(c in value for c in ",\r\n"):
                raise RuntimeError("Unsafe native date parameter")
        args += ["-p", ",".join(key + "=" + value for key, value in params.items())]
    with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        process = subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT)
        while True:
            try:
                status = process.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                print("Native posting date operation active: " + label, flush=True)
    log.chmod(0o600)
    if status:
        raise RuntimeError("Native date operation failed; inspect private log " + str(log))
    return log


def temporary_native(hop: str, path: Path, directory: Path, label: str) -> Path:
    remote = "/tmp/posting-dates-" + uuid.uuid4().hex + path.suffix
    common.command(["docker", "cp", str(path), hop + ":" + remote])
    try:
        # docker cp preserves 0600 but assigns root ownership. The deployed Hop
        # runtime is uid/gid 501; keep the file private while making it readable.
        for program, argument in (("chown", "501:501"), ("chmod", "600")):
            common.command(["docker", "exec", "-u", "root", hop, program, argument, remote])
        return native(hop, remote, directory, label)
    finally:
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-f", "--", remote])


def signature_expression(entity: str, excluded: str) -> str:
    # Property types and lengths disambiguate scalar/list encodings. Neo4j
    # properties cannot contain nested lists or maps. Values stay private.
    return f"""CALL ({entity}) {{
 UNWIND [k IN keys({entity}) WHERE NOT k IN {excluded}] AS k
 WITH k,{entity}[k] AS v ORDER BY k
 WITH k,v,valueType(v) AS t
 WITH k,t,CASE WHEN t STARTS WITH 'LIST' THEN
  reduce(s='',x IN v | s+toString(size(toString(x)))+':'+toString(x))
 ELSE toString(v) END AS text
 RETURN collect([k,t,text]) AS props
}}
WITH *,reduce(s='',p IN props | s+reduce(z='',x IN p |
 z+toString(size(x))+':'+x)) AS property_signature"""


def snapshot_query(identities: list[str], totals: bool) -> str:
    for item in identities:
        exact_identity(item)
    ids = json.dumps(identities)
    excluded = json.dumps(DATE_PROPERTIES)
    node_props = signature_expression("j", excluded)
    rel_props = signature_expression("r", "[]")
    query = f"""UNWIND {ids} AS posting_id
MATCH (j:entity:jobPosting {{id:posting_id}})
CALL (j) {{ UNWIND labels(j) AS label WITH label ORDER BY label RETURN collect(label) AS labels }}
{node_props}
RETURN 'NODE:'+elementId(j)+':'+j.id+':'+
 reduce(s='',label IN labels | s+toString(size(label))+':'+label)+':'+
 property_signature AS signature
UNION ALL
UNWIND {ids} AS posting_id
MATCH (j:entity:jobPosting {{id:posting_id}})-[r]-(other)
{rel_props}
RETURN 'REL:'+elementId(r)+':'+elementId(startNode(r))+':'+elementId(endNode(r))+
 ':'+type(r)+':'+property_signature AS signature"""
    if totals:
        query += """
UNION ALL MATCH (n) RETURN 'TOTAL_NODES:'+toString(count(n)) AS signature
UNION ALL MATCH ()-[r]->() RETURN 'TOTAL_RELS:'+toString(count(r)) AS signature
UNION ALL MATCH (j:jobPosting) RETURN 'TOTAL_POSTINGS:'+toString(count(j)) AS signature"""
    return query


def build_snapshot(path: Path, query: str, output_base: str) -> None:
    template = ET.parse(common.ROOT / "graph/verify_totals.hpl").getroot()
    root = ET.Element("pipeline")
    info = copy.deepcopy(template.find("info"))
    assert info is not None
    info.find("name").text = "Read-only posting date preservation snapshot"  # type: ignore[union-attr]
    root.append(info)
    ET.SubElement(root, "notepads")
    order = ET.SubElement(root, "order")
    for source, target in (
        ("Snapshot", "Read graph snapshot"),
        ("Read graph snapshot", "Write private snapshot"),
    ):
        hop = ET.SubElement(order, "hop")
        for key, value in (("from", source), ("to", target), ("enabled", "Y")):
            ET.SubElement(hop, key).text = value
    seed = copy.deepcopy(
        next(t for t in template.findall("transform") if t.findtext("type") == "GetVariable")
    )
    seed.find("name").text = "Snapshot"  # type: ignore[union-attr]
    fields = seed.find("fields")
    assert fields is not None
    for field in list(fields):
        fields.remove(field)
    field = ET.SubElement(fields, "field")
    for key, value in (("name", "seed"), ("variable", "1"), ("type", "String")):
        ET.SubElement(field, key).text = value
    root.append(seed)
    neo = copy.deepcopy(
        next(t for t in template.findall("transform") if t.findtext("type") == "Neo4jCypherOutput")
    )
    for key, value in (
        ("name", "Read graph snapshot"),
        ("cypher", query),
        ("connection", "jobtology-neo4j"),
        ("read_only", "Y"),
    ):
        neo.find(key).text = value  # type: ignore[union-attr]
    for key in ("mappings", "returns"):
        node = neo.find(key)
        assert node is not None
        node.clear()
    ret = ET.SubElement(neo.find("returns"), "return")  # type: ignore[arg-type]
    for key, value in (("name", "signature"), ("type", "String"), ("source_type", "String")):
        ET.SubElement(ret, key).text = value
    root.append(neo)
    export = ET.parse(common.ROOT / "ontology/export_jsonld.hpl").getroot()
    writer = copy.deepcopy(
        next(t for t in export.findall("transform") if t.findtext("type") == "TextFileOutput")
    )
    for key, value in (
        ("name", "Write private snapshot"),
        ("separator", "\t"),
        ("enclosure", '"'),
        ("enclosure_forced", "Y"),
        ("enclosure_fix_disabled", "N"),
        ("file/name", output_base),
        ("file/extension", "csv"),
        ("fields/field/name", "signature"),
    ):
        writer.find(key).text = value  # type: ignore[union-attr]
    root.append(writer)
    ET.SubElement(root, "transform_error_handling")
    ET.SubElement(root, "attributes")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    path.chmod(0o600)


def graph_snapshot(hop: str, identities: list[str], directory: Path, label: str) -> dict[str, Any]:
    hashes: set[str] = set()
    node_count = 0
    edge_hashes: set[str] = set()
    totals: list[str] = []
    for number, offset in enumerate(range(0, len(identities), CHUNK_SIZE), 1):
        chunk = identities[offset : offset + CHUNK_SIZE]
        remote_base = "/tmp/posting-dates-snapshot-" + uuid.uuid4().hex
        pipeline = directory / f"{label}-{number}.hpl"
        output = directory / f"{label}-{number}.csv"
        build_snapshot(pipeline, snapshot_query(chunk, number == 1), remote_base)
        try:
            temporary_native(hop, pipeline, directory, f"{label}-{number}")
            common.command(["docker", "cp", hop + ":" + remote_base + ".csv", str(output)])
            output.chmod(0o600)
            with output.open(encoding="utf-8", newline="") as handle:
                for row in csv.reader(handle, delimiter="\t"):
                    if len(row) != 1:
                        raise RuntimeError("Invalid private graph snapshot framing")
                    value = row[0]
                    digest = hashlib.sha256(value.encode()).hexdigest()
                    if value.startswith("NODE:"):
                        node_count += 1
                        hashes.add(digest)
                    elif value.startswith("REL:"):
                        edge_hashes.add(digest)
                    elif value.startswith("TOTAL_"):
                        totals.append(value)
                    else:
                        raise RuntimeError("Unexpected private graph snapshot row")
        finally:
            common.command(
                ["docker", "exec", "-u", "root", hop, "rm", "-f", "--", remote_base + ".csv"]
            )
    if node_count != len(identities) or len(hashes) != len(identities):
        raise RuntimeError("Every affected posting must have exactly one existing graph identity")
    if len(totals) != 3:
        raise RuntimeError("Graph-wide count snapshot is incomplete")

    def fingerprint(values: set[str]) -> str:
        return hashlib.sha256("".join(sorted(values)).encode()).hexdigest()

    return {
        "posting_nodes": node_count,
        "posting_payload_sha256": fingerprint(hashes),
        "incident_edges": len(edge_hashes),
        "incident_payload_sha256": fingerprint(edge_hashes),
        "graph_totals": sorted(totals),
        "chunk_size": CHUNK_SIZE,
    }


def build_registration(path: Path, evidence: dict[str, str]) -> None:
    template = ET.parse(common.ROOT / "ingestions/jobkorea/install.hwf").getroot()
    root = ET.Element("workflow")
    for key, value in (
        ("name", "Record supplied JobKorea collection evidence"),
        ("description", "Only the immutable date evidence function executes"),
    ):
        ET.SubElement(root, key).text = value
    ET.SubElement(root, "parameters")
    actions = ET.SubElement(root, "actions")
    actions.append(
        copy.deepcopy(
            next(a for a in template.findall("./actions/action") if a.findtext("type") == "SPECIAL")
        )
    )
    action = copy.deepcopy(
        next(a for a in template.findall("./actions/action") if a.findtext("type") == "SQL")
    )
    action.find("name").text = "Register supplied evidence"  # type: ignore[union-attr]
    action.find("sqlfromfile").text = "N"  # type: ignore[union-attr]
    action.find("sqlfilename").text = ""  # type: ignore[union-attr]
    statement = (
        "SELECT ingestion.register_jobkorea_collection_time("
        + ",".join(
            quote(evidence[key])
            for key in (
                "job_run",
                "file_sha256",
                "scraped_at",
                "evidence_source",
                "evidence_reference",
                "reported_timezone",
            )
        )
        + ");"
    )
    ET.SubElement(action, "sql").text = statement
    actions.append(action)
    hops = ET.SubElement(root, "hops")
    hop = ET.SubElement(hops, "hop")
    for key, value in (
        ("from", "Start"),
        ("to", "Register supplied evidence"),
        ("enabled", "Y"),
        ("evaluation", "Y"),
        ("unconditional", "Y"),
    ):
        ET.SubElement(hop, key).text = value
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    path.chmod(0o600)


def restore_snapshot_workflow(hop: str, before: bytes, directory: Path) -> None:
    """Only the scheduler-facing entry point is restored after install failure."""
    relative = "graph/load_snapshot.hwf"
    current = deployment.remote_bytes(hop, relative)
    if current == before:
        return
    if current != (common.ROOT / relative).read_bytes():
        raise RuntimeError(
            "Graph entry point changed outside date deployment; review before restoring"
        )
    path = directory / "load_snapshot-before.hwf"
    path.write_bytes(before)
    path.chmod(0o600)
    remote = common.PROJECT + "/" + relative + ".date-rollback-" + uuid.uuid4().hex
    try:
        common.command(["docker", "cp", str(path), hop + ":" + remote])
        for program, argument in (("chown", "501:501"), ("chmod", "644")):
            common.command(["docker", "exec", "-u", "root", hop, program, argument, remote])
        digest = common.command(["docker", "exec", hop, "sha256sum", remote]).decode().split()[0]
        if digest != common.digest(before):
            raise RuntimeError("Graph date entry-point rollback staging failed")
        common.command(
            [
                "docker",
                "exec",
                "-u",
                "root",
                hop,
                "mv",
                "--",
                remote,
                common.PROJECT + "/" + relative,
            ]
        )
        if deployment.remote_bytes(hop, relative) != before:
            raise RuntimeError("Graph date entry-point rollback verification failed")
    finally:
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-f", "--", remote])


def deploy_install(manifest: Path, runtime: dict[str, str], directory: Path) -> Path:
    """Deploy and install without exposing a missing date function to cron."""
    path = directory / "receipt.json"
    before = preservation(runtime["pg"])
    schema_before = schema_preservation(runtime["pg"])
    workflow_before = deployment.remote_bytes(runtime["hop"], "graph/load_snapshot.hwf")
    if workflow_before is None:
        raise RuntimeError("An existing source graph entry point is required")
    receipt: dict[str, Any] = {
        "version": 1,
        "status": "DEPLOYING",
        "started_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest.resolve()),
        "runtime": runtime,
        "schema_before": schema_before,
        "source_requests": 0,
        "paid_calls": 0,
    }
    common.write_json(path, receipt)
    try:
        receipt["deployment_receipt"] = str(
            deployment.apply(manifest, runtime, common.db_state(runtime["pg"]))
        )
        receipt["status"] = "INSTALLING"
        receipt["artifacts"] = artifacts(runtime["hop"])
        common.write_json(path, receipt)
        native(
            runtime["hop"],
            common.PROJECT + "/graph/install_posting_dates.hwf",
            directory,
            "install",
        )
        if preservation(runtime["pg"]) != before:
            raise RuntimeError("Existing application rows changed during date installation")
        receipt["schema_after"] = schema_preservation(runtime["pg"])
        require_schema_preserved(schema_before, receipt["schema_after"])
        require_idle(runtime["pg"])
        receipt["status"] = "VERIFIED"
    except BaseException as error:
        receipt["status"] = "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
        receipt["failure_type"] = type(error).__name__
        try:
            restore_snapshot_workflow(runtime["hop"], workflow_before, directory)
            receipt["scheduler_entry_point_restored"] = True
        except RuntimeError:
            receipt["scheduler_entry_point_restored"] = False
        raise RuntimeError(
            "Date deployment/install stopped; inspect protected receipt " + str(path)
        ) from error
    finally:
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        common.write_json(path, receipt)
    return path


def execute(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    common.STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if common.STATE.is_symlink():
        raise RuntimeError("Runtime state directory must not be a symlink")
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
        require_idle(runtime["pg"])
        if args.mode == "deploy-install":
            directory = common.STATE / ("posting-dates-deploy-install-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            return deploy_install(args.manifest, runtime, directory)
        planned = None if args.mode == "plan" else json.loads(args.manifest.read_bytes())
        job_run = exact_identity(
            args.job_run if planned is None else planned["evidence"]["job_run"]
        )
        source_scope = scope(runtime["pg"], job_run)
        before = preservation(runtime["pg"])
        schema_before = schema_preservation(runtime["pg"])
        ledgers_before = ledger_rows(runtime["pg"])
        artifact_hashes = artifacts(runtime["hop"])
        directory = common.STATE / ("posting-dates-" + args.mode + "-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        path = directory / ("manifest.json" if planned is None else "receipt.json")
        graph_before = graph_snapshot(
            runtime["hop"], source_scope["identities"], directory, "graph-before"
        )
        if planned is None:
            evidence = {
                "job_run": job_run,
                "file_sha256": source_scope["job_run"]["file_sha256"],
                "scraped_at": args.scraped_at,
                "evidence_source": "USER_REPORTED",
                "evidence_reference": exact_identity(args.evidence_reference),
                "reported_timezone": args.reported_timezone,
            }
            if datetime.fromisoformat(evidence["scraped_at"]) > datetime.fromisoformat(
                source_scope["job_run"]["imported_at"]
            ):
                raise RuntimeError(
                    "Supplied collection time is later than the immutable import receipt"
                )
            manifest = {
                "version": 1,
                "status": "PLANNED",
                "created_at": datetime.now(UTC).isoformat(),
                "runtime": runtime,
                "scope": source_scope,
                "evidence": evidence,
                "artifacts": artifact_hashes,
                "protected_tables": before,
                "schema": schema_before,
                "ledgers": ledgers_before,
                "graph": graph_before,
                "source_requests": 0,
                "paid_calls": 0,
            }
            common.write_json(path, manifest)
            return path
        for key, actual in (
            ("version", 1),
            ("runtime", runtime),
            ("scope", source_scope),
            ("artifacts", artifact_hashes),
            ("protected_tables", before),
            ("schema", schema_before),
            ("ledgers", ledgers_before),
            ("graph", graph_before),
        ):
            if planned.get(key) != actual:
                raise RuntimeError("Posting date plan changed: " + key)
        receipt: dict[str, Any] = {
            "version": 1,
            "status": "BACKING_UP",
            "manifest": str(args.manifest.resolve()),
            "started_at": datetime.now(UTC).isoformat(),
            "runtime": runtime,
            "scope": source_scope,
            "evidence": planned["evidence"],
            "artifacts": artifact_hashes,
            "graph_before": graph_before,
            "protected_tables_before": before,
            "schema_before": schema_before,
            "ledgers_before": ledgers_before,
            "completed_runs": [],
            "source_requests": 0,
            "paid_calls": 0,
        }
        common.write_json(path, receipt)
        try:
            receipt["database_backup"] = deployment.backup_database(runtime["pg"], directory)
            common.write_json(path, receipt)
            common.idle_cli(runtime["hop"])
            require_idle(runtime["pg"])
            if (
                preservation(runtime["pg"]) != before
                or scope(runtime["pg"], job_run) != source_scope
            ):
                raise RuntimeError("Runtime changed during date backup")
            receipt["status"] = "INSTALLING"
            common.write_json(path, receipt)
            native(
                runtime["hop"],
                common.PROJECT + "/graph/install_posting_dates.hwf",
                directory,
                "install",
            )
            registration = directory / "register-evidence.hwf"
            build_registration(registration, planned["evidence"])
            temporary_native(runtime["hop"], registration, directory, "register-evidence")
            receipt["status"] = "UPDATING"
            common.write_json(path, receipt)
            for number, run in enumerate(source_scope["runs"], 1):
                native(
                    runtime["hop"],
                    common.PROJECT + "/graph/update_posting_dates.hwf",
                    directory,
                    f"update-{number}",
                    {"RUN_ID": run},
                )
                receipt["completed_runs"].append(run)
                common.write_json(path, receipt)
            receipt["graph_after"] = graph_snapshot(
                runtime["hop"], source_scope["identities"], directory, "graph-after"
            )
            receipt["protected_tables_after"] = preservation(runtime["pg"])
            receipt["schema_after"] = schema_preservation(runtime["pg"])
            require_schema_preserved(schema_before, receipt["schema_after"])
            receipt["ledgers_after"] = ledger_rows(runtime["pg"])
            require_append_only(ledgers_before, receipt["ledgers_after"])
            if (
                receipt["graph_after"] != graph_before
                or receipt["protected_tables_after"] != before
            ):
                raise RuntimeError("Posting date preservation verification failed")
            if (
                scope(runtime["pg"], job_run) != source_scope
                or artifacts(runtime["hop"]) != artifact_hashes
            ):
                raise RuntimeError("Posting date source scope or artifacts changed")
            require_idle(runtime["pg"])
            receipt["status"] = "VERIFIED"
        except BaseException as error:
            receipt["status"] = "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
            receipt["failure_type"] = type(error).__name__
            raise RuntimeError(
                "Date update stopped; inspect protected receipt " + str(path)
            ) from error
        finally:
            receipt["finished_at"] = datetime.now(UTC).isoformat()
            common.write_json(path, receipt)
        return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("deploy-install", "plan", "apply"))
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--job-run", type=exact_identity)
    parser.add_argument("--scraped-at", type=timestamp)
    parser.add_argument("--reported-timezone", choices=("Asia/Seoul",), default="Asia/Seoul")
    parser.add_argument(
        "--evidence-reference", default="user-reported-jobkorea-collection-20261011"
    )
    args = parser.parse_args()
    if args.mode == "plan" and (args.manifest or not args.job_run or not args.scraped_at):
        parser.error("plan requires --job-run and --scraped-at, without a manifest")
    if args.mode in ("apply", "deploy-install") and (
        not args.manifest or args.job_run or args.scraped_at
    ):
        parser.error("apply/deploy-install requires an exact manifest without replacement evidence")
    path = execute(args)
    print(
        json.dumps(
            {"status": "PLANNED" if args.mode == "plan" else "VERIFIED", "receipt": str(path)}
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
