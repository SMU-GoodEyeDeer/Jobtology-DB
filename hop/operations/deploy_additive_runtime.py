#!/usr/bin/env python3
"""Guarded additive source-performance/v3-matching SQL and public artifact rollout.

Plan, apply, readback and behavior rollback hold refresh.lock and use the existing
scheduler fence. The only executed migrations are graph003 and LLM037. No graph
writer, ingestion workflow, source URL or provider call is executed. All old rows,
table structures, views, triggers, ACLs and catalogue pins must remain exact.
A sole immutable v3 prompt and empty candidate-review table may be added. Rollback
refuses intervening facts/reviews/drift; unused additive objects remain, while exact
old public function definitions and runtime bytes restore prior behavior.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import backfill_posting_dates as dates
import deploy_jobkorea_runtime as deployment
import deploy_performance_runtime as performance
import reconcile_runtime as common

ROOT, STATE, PROJECT = common.ROOT, common.STATE, common.PROJECT
KIND = "ADDITIVE_SOURCE_PERFORMANCE_METADATA_V3"
MIGRATIONS = (
    "graph/sql/003_source_query_sharing.sql",
    "llm/sql/037_metadata_occupation_multimatch.sql",
)
ALLOWLIST = (
    *MIGRATIONS,
    "graph/check_snapshot.hpl",
    "graph/install.hwf",
    "graph/install_posting_dates.hwf",
    "ingestions/jobkorea/install.hwf",
    "ingestions/jobkorea/install_batchfree_graph_publication.hwf",
    "llm/prompts/categorize-ko-metadata-occupation-v3.txt",
    "llm/prompts/categorize-ko-metadata-occupation-v3.schema.json",
    "llm/install.hwf",
    "ingestions/jobkorea/install_inferred_occupations.hwf",
    "ingestions/jobkorea/load_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/verify_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/execute_inferred_occupations.hwf",
    "ingestions/jobkorea/execute_inferred_occupation_workers.hwf",
)
NEW_TABLE = "enrichment.metadata_occupation_candidate_decision"
SCHEMAS = "('attachment','catalog','cs','enrichment','ingestion','ontology','retention')"


def utc() -> str:
    return datetime.now(UTC).isoformat()


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def selected(values: list[str]) -> tuple[str, ...]:
    if not values or len(set(values)) != len(values) or any(v not in ALLOWLIST for v in values):
        raise ValueError("Select unique fixed allowlist artifacts")
    if set(values) != set(ALLOWLIST):
        raise ValueError("Select the complete coherent additive runtime bundle")
    return tuple(v for v in ALLOWLIST if v in values)


def unwrap_sql(text: str) -> str:
    match = re.fullmatch(r"(?:\s|--[^\n]*(?:\n|$))*BEGIN;([\s\S]*)COMMIT;\s*", text, re.I)
    if not match:
        raise ValueError("Reviewed migration must have one explicit outer BEGIN/COMMIT")
    return match[1]


def function_names(directory: Path) -> set[str]:
    return {
        name.lower()
        for relative in MIGRATIONS
        for name in re.findall(
            r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)\s*\(",
            (directory / relative).read_text(),
            re.I,
        )
    }


def sql(pg: str, statement: str, directory: Path, label: str) -> str:
    query = "SET statement_timeout='180s'; SET lock_timeout='10s';\n" + statement
    (directory / (label + ".sql")).write_text(query)
    out_path = directory / (label + ".stdout")
    with out_path.open("wb") as out, (directory / (label + ".stderr")).open("wb") as err:
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
                "-U",
                "postgres",
                "-d",
                "jobtology",
            ],
            input=query.encode(),
            stdout=out,
            stderr=err,
            timeout=240,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("Bounded SQL failed; inspect protected " + label + " logs")
    return out_path.read_text().strip()


def schema_query() -> str:
    return (
        """SELECT jsonb_build_object(
 'v3_prompt',(SELECT jsonb_build_object('count',count(*),'digest',
 encode(sha256(convert_to(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),''),
 'UTF8')),'hex')) FROM enrichment.prompt t
 WHERE version='ko-metadata-occupation-v3' AND stage='categorize'),
 'functions',(SELECT coalesce(jsonb_object_agg(p.oid::regprocedure::text,
  encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex')),'{}')
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname IN """
        + SCHEMAS
        + """ AND p.prokind IN('f','p')),
 'function_acl',(SELECT coalesce(jsonb_object_agg(p.oid::regprocedure::text,
  jsonb_build_array(p.proowner,p.proacl)),'{}') FROM pg_proc p
  JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN """
        + SCHEMAS
        + """
  AND p.prokind IN('f','p')),
 'triggers',(SELECT coalesce(jsonb_object_agg(n.nspname||'.'||c.relname||':'||t.tgname,
  encode(sha256(convert_to(pg_get_triggerdef(t.oid)||t.tgenabled::text,'UTF8')),'hex')),'{}')
  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal
  AND n.nspname IN """
        + SCHEMAS
        + """),
 'views',(SELECT coalesce(jsonb_object_agg(n.nspname||'.'||c.relname,
  encode(sha256(convert_to(pg_get_viewdef(c.oid)||c.relowner::text||coalesce(c.relacl::text,''),
  'UTF8')),'hex')),'{}') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE c.relkind IN('v','m') AND n.nspname IN """
        + SCHEMAS
        + """),
 'tables',(SELECT coalesce(jsonb_object_agg(n.nspname||'.'||c.relname,
  encode(sha256(convert_to(jsonb_build_object(
   'class',jsonb_build_array(c.relkind,c.relowner,c.relacl,c.relrowsecurity,c.relforcerowsecurity,
     c.relreplident,c.reloptions),
   'columns',(SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),
     a.attnotnull,a.attidentity,a.attgenerated,a.attcollation,a.attstorage,a.attcompression,
     a.attstattarget,pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)
     FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
     WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
   'constraints',(SELECT jsonb_agg(jsonb_build_array(k.conname,pg_get_constraintdef(k.oid),
     k.convalidated,k.condeferrable,k.condeferred) ORDER BY k.conname)
     FROM pg_constraint k WHERE k.conrelid=c.oid),
   'indexes',(SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY pg_get_indexdef(i.indexrelid))
     FROM pg_index i WHERE i.indrelid=c.oid))::text,'UTF8')),'hex')),'{}')
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE c.relkind IN('r','p') AND n.nspname IN """
        + SCHEMAS
        + """));"""
    )


def schema(pg: str, directory: Path, label: str) -> dict[str, Any]:
    return json.loads(sql(pg, "BEGIN READ ONLY; " + schema_query() + " COMMIT;", directory, label))


def rows(pg: str) -> dict[str, Any]:
    result = deployment.full_preservation_state(pg)
    result["enrichment.prompt"] = json.loads(
        deployment.sql(
            pg,
            "BEGIN READ ONLY; "
            "SET LOCAL statement_timeout='180s'; SELECT jsonb_build_object('count',count(*),"
            "'digest',md5(coalesce(string_agg(h,'' ORDER BY h),''))) FROM "
            "(SELECT md5(to_jsonb(t)::text) h FROM enrichment.prompt t "
            "WHERE NOT(version='ko-metadata-occupation-v3' AND stage='categorize'))r; COMMIT;",
        )
    )
    return result


def require_preserved(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> None:
    if before["schema"]["v3_prompt"]["count"] and (
        before["schema"]["v3_prompt"] != after["schema"]["v3_prompt"]
    ):
        raise RuntimeError("Existing v3 prompt identity changed")
    if after["schema"]["v3_prompt"]["count"] > 1:
        raise RuntimeError("Unexpected v3 prompt cardinality")
    for category in ("tables", "views", "triggers", "function_acl", "functions"):
        for name, value in before["schema"][category].items():
            if category == "functions" and name.split("(")[0].lower() in allowed:
                continue
            if after["schema"][category].get(name) != value:
                raise RuntimeError(
                    "Existing schema changed outside approved function bodies: " + name
                )
    for name, value in before["rows"].items():
        if after["rows"].get(name) != value:
            raise RuntimeError("Existing PostgreSQL rows changed: " + name)
    new = set(after["rows"]) - set(before["rows"])
    if new - {NEW_TABLE} or any(after["rows"][name]["count"] != 0 for name in new):
        raise RuntimeError("Unexpected added or nonempty table")
    if before.get("queries") != after.get("queries"):
        raise RuntimeError("Legacy matching or source projection query outputs changed")
    if before["catalog_context"] != after["catalog_context"]:
        raise RuntimeError("Approved catalogue pins changed")


def query_state(pg: str, directory: Path, label: str) -> dict[str, Any]:
    pins = json.loads(
        sql(
            pg,
            "BEGIN READ ONLY; SELECT jsonb_build_object('job',"
            "(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'),'ncs',"
            "(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency')); "
            "COMMIT;",
            directory,
            label + "-pins",
        )
    )
    if not pins["job"] or not pins["ncs"]:
        raise RuntimeError("Exact current JobKorea/NCS pins are required")
    pairs = json.loads(
        sql(
            pg,
            "BEGIN READ ONLY; SELECT coalesce(jsonb_agg(to_jsonb(p) "
            "ORDER BY p.job,p.ncs),'[]'::jsonb) FROM (SELECT x.job_run_id AS job,"
            "x.ncs_run_id AS ncs,"
            "count(DISTINCT x.item_id) AS bindings,count(DISTINCT r.result_id) AS results,"
            "count(DISTINCT c.candidate_id) AS candidates "
            "FROM enrichment.metadata_occupation_binding x "
            "LEFT JOIN enrichment.metadata_occupation_result r USING(item_id) "
            "LEFT JOIN enrichment.metadata_occupation_candidate c USING(result_id) "
            "GROUP BY x.job_run_id,x.ncs_run_id)p; COMMIT;",
            directory,
            label + "-frozen-pairs",
        )
    )
    job = dates.quote(pins["job"])
    queries = {
        "source_manifest": f"SELECT * FROM ingestion.source_graph_manifest({job},true)",
        "source_entities": f"SELECT * FROM ingestion.graph_source_entities({job})",
        "source_edges": f"SELECT * FROM ingestion.graph_source_edges({job})",
        "source_dates": f"SELECT * FROM ingestion.graph_posting_ingestion_dates({job})",
    }
    result: dict[str, Any] = {
        "latest_source_pins": pins,
        "frozen_metadata_pairs": pairs,
        "scope": "Current exact source run plus every historical frozen metadata JobKorea/NCS pair",
    }
    for index, pair in enumerate(pairs):
        job, ncs = map(dates.quote, (pair["job"], pair["ncs"]))
        queries[f"pair{index}_status"] = (
            f"SELECT * FROM enrichment.metadata_occupation_status({job},{ncs})"
        )
        for reviewed, flag in (("all", "true"), ("reviewed", "false")):
            queries[f"pair{index}_graph_{reviewed}"] = (
                f"SELECT * FROM enrichment.metadata_occupation_graph_rows({job},{ncs},{flag})"
            )
    for name, query in queries.items():
        evidence = sql(
            pg,
            "BEGIN READ ONLY; SELECT jsonb_build_object('rows',count(*),'sha256',"
            "encode(sha256(convert_to(coalesce(string_agg(h,'' ORDER BY h),''),'UTF8')),'hex')) "
            "FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') h "
            "FROM (" + query + ")t)r; COMMIT;",
            directory,
            label + "-" + name,
        )
        result[name] = json.loads(evidence)
    graph_rows = sum(result[f"pair{index}_graph_all"]["rows"] for index in range(len(pairs)))
    if sum(pair["candidates"] for pair in pairs) > 0 and graph_rows == 0:
        raise RuntimeError("Protected original inference graph scope unexpectedly empty")
    result["protected_legacy_graph_rows"] = graph_rows
    return result


def snapshot_state(runtime: dict[str, str], directory: Path, label: str) -> dict[str, Any]:
    return {
        "schema": schema(runtime["pg"], directory, label + "-schema"),
        "rows": rows(runtime["pg"]),
        "queries": query_state(runtime["pg"], directory, label),
        "catalog_context": common.db_state(runtime["pg"])["catalog_context"],
    }


def public_snapshot(runtime: dict[str, str], artifacts: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for relative in artifacts:
        source = ROOT / relative
        if not source.is_file() or any(p.is_symlink() for p in (source, *source.parents)):
            raise RuntimeError("Candidate source missing or symlink")
        data = source.read_bytes()
        if source.suffix in (".hpl", ".hwf"):
            ET.fromstring(data)
        elif source.suffix == ".json":
            json.loads(data)
        before = deployment.remote_bytes(runtime["hop"], relative)
        result[relative] = {
            "before": None if before is None else common.digest(before),
            "after": common.digest(data),
        }
    return result


def bind_proofs(paths: list[Path], artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    proofs: list[dict[str, Any]] = []
    covered: set[str] = set()
    for path in paths:
        proof = json.loads(path.read_text())
        database_only = (
            proof.get("database_removed") is True
            and isinstance(proof.get("database"), str)
            and bool(proof["database"])
            and isinstance(proof.get("container"), str)
            and bool(proof["container"])
        )
        if not (
            str(proof.get("status", "")).startswith(("PASSED", "VERIFIED"))
            and (
                proof.get("disposable_resources_removed") is True
                or proof.get("cleanup_verified") is True
                or proof.get("cleanup_confirmed") is True
                or database_only
            )
        ):
            raise RuntimeError("Require completed isolated proof with verified cleanup")
        hashes = {
            **proof.get("sql_sha256", {}),
            **proof.get("candidate_sql_sha256", {}),
            **proof.get("artifact_sha256", {}),
            **proof.get("artifact_hashes", {}),
            **proof.get("candidate_artifact_sha256", {}),
        }
        for relative in artifacts:
            if any(
                (key == relative or key.endswith("/" + relative))
                and value == artifacts[relative]["after"]
                for key, value in hashes.items()
            ):
                covered.add(relative)
        proofs.append(
            {
                "path": str(path.resolve()),
                "sha256": digest(path),
                "status": proof["status"],
                "cleanup_scope": "DATABASE_ONLY" if database_only else "DISPOSABLE_RESOURCES",
            }
        )
    if covered != set(artifacts):
        raise RuntimeError(
            "Isolated proofs do not bind every exact critical bundle artifact: "
            + ",".join(sorted(set(artifacts) - covered))
        )
    return proofs


def own_fence(receipt: dict[str, Any], path: Path) -> None:
    fence = STATE / performance.FENCE_NAME
    if fence.exists():
        if fence.is_symlink():
            raise RuntimeError("Scheduler fence is a symlink")
        value = json.loads(fence.read_text())
        if value.get("token") != receipt["token"] or value.get("receipt") != str(path):
            raise RuntimeError("Scheduler fence belongs to another operation")
        return
    descriptor = os.open(fence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump({"kind": KIND, "token": receipt["token"], "receipt": str(path)}, output)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def write_runtime(
    hop: str, relative: str, data: bytes | None, expected: str | None, directory: Path, token: str
) -> None:
    current = deployment.remote_bytes(hop, relative)
    if (None if current is None else common.digest(current)) != expected:
        raise RuntimeError("Intervening runtime byte drift")
    if data is None:
        common.command(["docker", "exec", "-u", "root", hop, "rm", "--", PROJECT + "/" + relative])
        return
    local = directory / ("stage-" + uuid.uuid4().hex)
    local.write_bytes(data)
    local.chmod(0o600)
    temporary = PROJECT + "/" + relative + ".additive-" + token
    deployment.ensure_parent(hop, relative)
    try:
        common.command(["docker", "cp", str(local), hop + ":" + temporary])
        common.command(["docker", "exec", "-u", "root", hop, "chown", "501:501", temporary])
        common.command(["docker", "exec", "-u", "root", hop, "chmod", "644", temporary])
        actual = common.command(["docker", "exec", hop, "sha256sum", temporary]).decode().split()[0]
        if actual != common.digest(data):
            raise RuntimeError("Staged public artifact hash differs")
        current = deployment.remote_bytes(hop, relative)
        if (None if current is None else common.digest(current)) != expected:
            raise RuntimeError("Runtime changed while staging")
        common.command(
            ["docker", "exec", "-u", "root", hop, "mv", "--", temporary, PROJECT + "/" + relative]
        )
    finally:
        local.unlink(missing_ok=True)
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-f", "--", temporary])


def plan(runtime: dict[str, str], artifacts: tuple[str, ...], proofs: list[Path]) -> Path:
    performance.idle(runtime)
    if (STATE / performance.FENCE_NAME).exists():
        raise RuntimeError("Existing fenced operation")
    directory = STATE / ("additive-runtime-plan-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    public = public_snapshot(runtime, artifacts)
    manifest = {
        "version": 1,
        "kind": KIND,
        "created_at": utc(),
        "containers": runtime,
        "artifacts": public,
        "isolated_proofs": bind_proofs(proofs, public),
        "before": snapshot_state(runtime, directory, "plan"),
        "production_graph_writes": 0,
        "source_requests": 0,
        "paid_requests": 0,
    }
    for relative in artifacts:
        target = directory / "candidate" / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
        target.chmod(0o600)
        if digest(target) != public[relative]["after"]:
            raise RuntimeError("Candidate changed during plan")
    names = function_names(directory / "candidate")
    literals = ",".join(dates.quote(name) for name in sorted(names)) or "NULL"
    manifest["original_views"] = json.loads(
        sql(
            runtime["pg"],
            "BEGIN READ ONLY; SELECT coalesce(jsonb_object_agg(n.nspname||'.'||c.relname,"
            "pg_get_viewdef(c.oid)),'{}'::jsonb) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN('v','m') "
            "AND n.nspname IN " + SCHEMAS + "; COMMIT;",
            directory,
            "original-views",
        )
    )
    manifest["original_functions"] = json.loads(
        sql(
            runtime["pg"],
            "BEGIN READ ONLY; SELECT "
            "coalesce(jsonb_agg(jsonb_build_object('signature',p.oid::regprocedure::text,"
            "'definition',pg_get_functiondef(p.oid)) "
            "ORDER BY p.oid::regprocedure::text),'[]'::jsonb) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE "
            "n.nspname||'.'||p.proname IN (" + literals + "); COMMIT;",
            directory,
            "original-functions",
        )
    )
    path = directory / "manifest.json"
    common.write_json(path, manifest)
    return path


def load(path: Path, runtime: dict[str, str]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("kind") != KIND or value.get("version") != 1 or value.get("containers") != runtime:
        raise RuntimeError("Wrong operation or runtime identity")
    selected(list(value["artifacts"]))
    return value


def require_unused_v3(pg: str, directory: Path) -> None:
    exists = (
        sql(
            pg,
            "SELECT to_regclass('" + NEW_TABLE + "') IS NOT NULL",
            directory,
            "review-table-present",
        )
        == "t"
    )
    query = (
        "SELECT count(*) FROM enrichment.batch "
        "WHERE settings->>'prompt_version'='ko-metadata-occupation-v3'"
    )
    if exists:
        query = "SELECT (" + query + ")+(SELECT count(*) FROM " + NEW_TABLE + ")"
    if sql(pg, query, directory, "v3-use") != "0":
        raise RuntimeError(
            "New v3 batch/request/result or candidate review prevents behavior rollback"
        )


def readback(path: Path, runtime: dict[str, str], *, release: bool = False) -> Path:
    receipt = load(path, runtime)
    performance.idle(runtime)
    fenced = (STATE / performance.FENCE_NAME).exists()
    if fenced:
        own_fence(receipt, path)
    elif not receipt.get("scheduler_fence_removed"):
        own_fence(receipt, path)
        fenced = True
    after = snapshot_state(runtime, path.parent, "readback")
    names = function_names(Path(receipt["manifest"]).parent / "candidate")
    require_preserved(receipt["before"], after, names)
    for relative, entry in receipt["artifacts"].items():
        current = deployment.remote_bytes(runtime["hop"], relative)
        if current is None or common.digest(current) != entry["after"]:
            raise RuntimeError("Additive runtime readback differs")
    if receipt.get("candidate_schema") != after["schema"]:
        raise RuntimeError("Installed SQL schema differs from transaction capture")
    receipt.update(after=after, status="VERIFIED_ADDITIVE_RUNTIME", readback_at=utc())
    common.write_json(path, receipt)
    if release and fenced:
        performance.release_fence(receipt, path)
        receipt["scheduler_fence_removed"] = True
        common.write_json(path, receipt)
    return path


def backup_database(pg: str, directory: Path) -> dict[str, Any]:
    path = directory / "database-before.dump"
    with path.open("xb") as out, (directory / "backup.stderr").open("wb") as err:
        result = subprocess.run(
            [
                "docker",
                "exec",
                pg,
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "jobtology",
                "--format=custom",
            ],
            stdout=out,
            stderr=err,
            timeout=300,
            check=False,
        )
    path.chmod(0o600)
    if result.returncode or not path.stat().st_size:
        raise RuntimeError("Bounded full database backup failed")
    with path.open("rb") as source, (directory / "backup-list.stderr").open("wb") as err:
        result = subprocess.run(
            ["docker", "exec", "-i", pg, "pg_restore", "--list"],
            stdin=source,
            stdout=subprocess.DEVNULL,
            stderr=err,
            timeout=60,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("Backup archive listing failed")
    return {
        "path": str(path),
        "byte_length": path.stat().st_size,
        "sha256": digest(path),
        "format": "POSTGRES_CUSTOM_FULL",
        "listing_validated": True,
        "limit": "Archive listing is not a native isolated restore proof.",
    }


def apply(manifest_path: Path, runtime: dict[str, str]) -> Path:
    manifest = load(manifest_path, runtime)
    performance.idle(runtime)
    if (STATE / performance.FENCE_NAME).exists():
        raise RuntimeError("Existing fenced operation")
    candidate = manifest_path.parent / "candidate"
    for relative, entry in manifest["artifacts"].items():
        if digest(candidate / relative) != entry["after"]:
            raise RuntimeError("Frozen candidate differs")
    bind_proofs([Path(p["path"]) for p in manifest["isolated_proofs"]], manifest["artifacts"])
    if any(digest(Path(p["path"])) != p["sha256"] for p in manifest["isolated_proofs"]):
        raise RuntimeError("Isolated proof changed after plan")
    directory = STATE / ("additive-runtime-applied-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    path = directory / "receipt.json"
    receipt: dict[str, Any] = {
        **manifest,
        "manifest": str(manifest_path.resolve()),
        "token": uuid.uuid4().hex,
        "status": "BACKING_UP",
        "attempted": [],
        "installed": [],
        "sql_attempted": False,
        "scheduler_fence_removed": False,
    }
    common.write_json(path, receipt)
    own_fence(receipt, path)
    try:
        before = snapshot_state(runtime, directory, "preapply")
        receipt["preapply_observed"] = before
        receipt["preapply_runtime"] = {
            relative: None
            if (value := deployment.remote_bytes(runtime["hop"], relative)) is None
            else common.digest(value)
            for relative in manifest["artifacts"]
        }
        common.write_json(path, receipt)
        if before != manifest["before"]:
            raise RuntimeError("Database changed since reviewed plan")
        require_unused_v3(runtime["pg"], directory)
        for relative, entry in manifest["artifacts"].items():
            old = deployment.remote_bytes(runtime["hop"], relative)
            if (None if old is None else common.digest(old)) != entry["before"]:
                raise RuntimeError("Runtime changed since plan")
            if old is not None:
                target = directory / "before" / relative
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(old)
                target.chmod(0o600)
        receipt["database_backup"] = backup_database(runtime["pg"], directory)
        receipt["status"] = "SQL_ATTEMPTED"
        receipt["sql_attempted"] = True
        common.write_json(path, receipt)
        statement = "BEGIN; SET LOCAL statement_timeout='180s'; SET LOCAL lock_timeout='10s';\n"
        statement += "\n".join(unwrap_sql((candidate / rel).read_text()) for rel in MIGRATIONS)
        statement += "\n" + schema_query() + "\nCOMMIT;"
        output = sql(runtime["pg"], statement, directory, "install-additive")
        receipt["candidate_schema"] = json.loads(output)
        receipt["status"] = "SQL_COMMITTED"
        common.write_json(path, receipt)
        require_preserved(
            manifest["before"],
            snapshot_state(runtime, directory, "postsql"),
            function_names(candidate),
        )
        for relative, entry in manifest["artifacts"].items():
            receipt["attempted"].append(relative)
            common.write_json(path, receipt)
            write_runtime(
                runtime["hop"],
                relative,
                (candidate / relative).read_bytes(),
                entry["before"],
                directory,
                receipt["token"],
            )
            receipt["installed"].append(relative)
            common.write_json(path, receipt)
        receipt["status"] = "INSTALLED_PENDING_READBACK"
        common.write_json(path, receipt)
        readback(path, runtime, release=True)
    except BaseException as error:
        receipt.update(status="FAILED_FENCED", failure_type=type(error).__name__)
        # SQL may have committed before a client disconnect. Never guess.
        if "candidate_schema" not in receipt and (directory / "install-additive.stdout").exists():
            with contextlib.suppress(ValueError):
                receipt["candidate_schema"] = json.loads(
                    (directory / "install-additive.stdout").read_text()
                )
        common.write_json(path, receipt)
        raise RuntimeError(
            "Additive rollout stopped; retain fence and inspect " + str(path)
        ) from error
    return path


def restored_schema(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Exact rollback phase, including unused additions, survives client failures."""
    candidate = receipt.get("candidate_schema")
    if candidate is None:
        return None
    result = json.loads(json.dumps(candidate))
    for row in receipt["original_functions"]:
        signature = row["signature"]
        result["functions"][signature] = receipt["before"]["schema"]["functions"][signature]
    return result


def abort_unchanged(path: Path, runtime: dict[str, str]) -> Path:
    receipt = load(path, runtime)
    performance.idle(runtime)
    if receipt.get("sql_attempted") is not False or receipt.get("attempted"):
        raise RuntimeError("SQL or runtime mutation was attempted; behavior rollback required")
    own_fence(receipt, path)
    expected = receipt.get("preapply_observed", receipt["before"])
    if snapshot_state(runtime, path.parent, "abort-readback") != expected:
        raise RuntimeError("Intervening database drift prevents unchanged abort")
    expected_runtime = receipt.get("preapply_runtime") or {
        key: value["before"] for key, value in receipt["artifacts"].items()
    }
    for relative, expected_hash in expected_runtime.items():
        value = deployment.remote_bytes(runtime["hop"], relative)
        if (None if value is None else common.digest(value)) != expected_hash:
            raise RuntimeError("Intervening runtime drift prevents unchanged abort")
    receipt.update(status="ABORTED_UNCHANGED", abort_readback_at=utc())
    common.write_json(path, receipt)
    performance.release_fence(receipt, path)
    receipt["scheduler_fence_removed"] = True
    common.write_json(path, receipt)
    return path


def rollback(path: Path, runtime: dict[str, str]) -> Path:
    receipt = load(path, runtime)
    if receipt.get("sql_attempted") is False:
        return abort_unchanged(path, runtime)
    performance.idle(runtime)
    directory = path.parent
    require_unused_v3(runtime["pg"], directory)
    current = snapshot_state(runtime, directory, "prerollback")
    allowed = function_names(Path(receipt["manifest"]).parent / "candidate")
    require_preserved(receipt["before"], current, allowed)
    before_schema = receipt["before"]["schema"]
    candidate = receipt.get("candidate_schema")
    if current["schema"] not in (before_schema, candidate, restored_schema(receipt)):
        raise RuntimeError("Intervening or unconfirmed schema drift prevents rollback")
    for relative, entry in receipt["artifacts"].items():
        old = directory / "before" / relative
        if entry["before"] is not None and digest(old) != entry["before"]:
            raise RuntimeError("Saved original artifact differs")
        value = deployment.remote_bytes(runtime["hop"], relative)
        if (None if value is None else common.digest(value)) not in (
            entry["before"],
            entry["after"],
        ):
            raise RuntimeError("Intervening runtime drift prevents rollback")
    own_fence(receipt, path)
    receipt["status"] = "ROLLING_BACK"
    common.write_json(path, receipt)
    try:
        definitions = ";\n".join(row["definition"] for row in receipt["original_functions"])
        sql(runtime["pg"], "BEGIN; " + (definitions + ";\n" if definitions else "") + "COMMIT;",
            directory, "rollback-functions")
        for relative, entry in reversed(list(receipt["artifacts"].items())):
            value = deployment.remote_bytes(runtime["hop"], relative)
            actual = None if value is None else common.digest(value)
            if actual == entry["before"]:
                continue
            old = (
                None if entry["before"] is None else (directory / "before" / relative).read_bytes()
            )
            write_runtime(runtime["hop"], relative, old, actual, directory, receipt["token"])
        final = snapshot_state(runtime, directory, "rollback-final")
        require_preserved(receipt["before"], final, set())
        receipt.update(
            status="ROLLED_BACK_BEHAVIOR",
            after=final,
            rollback_limit=(
                "Unused additive prompt, empty table, new helper functions remain; "
                "no DROP or evidence deletion."
            ),
        )
        common.write_json(path, receipt)
        performance.release_fence(receipt, path)
        receipt["scheduler_fence_removed"] = True
    except BaseException as error:
        receipt.update(status="ROLLBACK_FAILED_FENCED", failure_type=type(error).__name__)
        raise
    finally:
        common.write_json(path, receipt)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "readback", "rollback", "abort"))
    parser.add_argument("manifest_or_receipt", nargs="?", type=Path)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--isolated-proof", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.mode == "plan":
        if args.manifest_or_receipt or not args.artifact or not args.isolated_proof:
            parser.error("Plan requires explicit artifacts and isolated proofs, no manifest")
    elif not args.manifest_or_receipt or args.artifact or args.isolated_proof:
        parser.error("Apply/readback/rollback require only exact manifest/receipt")
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Scheduler lock is busy") from None
        runtime = common.containers()
        if args.mode == "plan":
            result = plan(runtime, selected(args.artifact), args.isolated_proof)
        elif args.mode == "apply":
            result = apply(args.manifest_or_receipt, runtime)
        elif args.mode == "readback":
            result = readback(args.manifest_or_receipt, runtime, release=True)
        elif args.mode == "abort":
            result = abort_unchanged(args.manifest_or_receipt, runtime)
        else:
            result = rollback(args.manifest_or_receipt, runtime)
        print(result)


if __name__ == "__main__":
    main()
