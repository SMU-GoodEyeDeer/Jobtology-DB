#!/usr/bin/env python3
"""Qualify SQL009 entity readers on one explicitly leased, analyzed archive.

Baseline and candidate use one persistent backend each, exact typed result bags,
fixed statistics, sixty-second bounds and deployed SQL008 as the baseline. All
plans/results remain in protected local state. No restore or external requests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark_first_capture import statistic_identity
from benchmark_graph_readers import RUNS
from profile_archived_postgres import Session, plan_summary, quote, write_json

ROOT = Path(__file__).resolve().parents[2]
READERS = ("graph_source_entities", "graph_source_edge_owners")
SCHEMAS = "('attachment','catalog','cs','enrichment','ingestion','ontology','retention')"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_fixture(preflight: dict[str, Any]) -> dict[str, Any]:
    inspected = json.loads(
        subprocess.run(
            ["docker", "inspect", preflight["container_id"], "--format", "{{json .}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    )
    if (
        preflight["status"] != "READY"
        or inspected["Id"] != preflight["container_id"]
        or inspected["Name"].lstrip("/") != preflight["container"]
        or not re.fullmatch(r"jobtology-routine-archive-nara-[0-9a-f]+", preflight["container"])
        or inspected["HostConfig"]["NetworkMode"] != "none"
        or set(inspected["NetworkSettings"]["Networks"]) != {"none"}
        or inspected["HostConfig"]["NanoCpus"] != 4_000_000_000
        or inspected["HostConfig"]["Memory"] != 6_442_450_944
        or [m["Name"] for m in inspected["Mounts"] if m["Type"] == "volume"]
        != preflight["owned_volumes"]
    ):
        raise ValueError("Exact leased clone, volume, isolation and quotas are required")
    return inspected


def protected_tables(session: Session) -> dict[str, Any]:
    names = json.loads(
        session.execute(
            "SELECT jsonb_agg(n.nspname||'.'||c.relname ORDER BY n.nspname,c.relname) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relkind IN('r','p') AND n.nspname IN" + SCHEMAS
        )
    )
    if len(names) != 157:
        raise RuntimeError("Expected all 157 protected tables")
    clauses = []
    for name in names:
        if not re.fullmatch(r"[a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*", name):
            raise RuntimeError("Unexpected fingerprint relation")
        excludes = (
            "-'started_at'-'verified_at'"
            if name == "ingestion.source_graph_projection"
            else "-'exported_at'"
            if name == "ingestion.graph_export"
            else ""
        )
        clauses.append(
            "SELECT " + quote(name) + " name,count(*) n,"
            "md5(coalesce(string_agg(h,'' ORDER BY h),'')) digest FROM "
            "(SELECT md5((to_jsonb(t)" + excludes + ")::text) h FROM " + name + " t)q"
        )
    result = {}
    # The complete archive exceeds sixty seconds when all table hashes share
    # one statement. Each exact table bag retains the unchanged statement bound.
    for clause in clauses:
        row = json.loads(session.execute("SELECT to_jsonb(t) FROM (" + clause + ")t"))
        result[row.pop("name")] = row
    return result


def function_metadata(session: Session) -> dict[str, Any]:
    return json.loads(
        session.execute(
            "SELECT jsonb_object_agg(p.oid::regprocedure::text,"
            "CASE WHEN p.oid='ingestion.graph_source_entities(text)'::regprocedure "
            "THEN to_jsonb(p)-'prosrc' ELSE to_jsonb(p) END) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN"
            + SCHEMAS
        )
    )


def typed_query(reader: str, run: str) -> str:
    return (
        "SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text),'[]') "
        "FROM ingestion." + reader + "(" + quote(run) + ")v"
    )


def raw_query(definition: str) -> str:
    return definition.split("RETURN QUERY\n", 1)[1].rsplit(";\nEND", 1)[0]


def run(args: argparse.Namespace) -> Path:
    os.umask(0o077)
    preflight = json.loads(args.preflight.read_text())
    inspected = inspect_fixture(preflight)
    work = args.directory.resolve()
    work.mkdir(parents=True, mode=0o700, exist_ok=False)
    helper = work / "launched-helper.py"
    shutil.copyfile(Path(__file__), helper)
    helper.chmod(0o400)
    receipt: dict[str, Any] = dict(
        status="RUNNING",
        mode="candidate" if args.baseline_receipt else "baseline",
        created_at=datetime.now(UTC).isoformat(),
        container=preflight["container"],
        container_id=inspected["Id"],
        preflight_sha256=digest(args.preflight),
        statement_timeout_seconds=60,
        source_requests=0,
        paid_requests=0,
        production_queries=0,
        production_writes=0,
        samples=[],
        diagnostic_plans={},
        launched_helper_sha256=digest(helper),
        limits=[
            "Ordered complete typed reader comparison; SQL timings are diagnostic.",
            "Raw query EXPLAIN excludes PL/pgSQL preconditions; measurements overlap.",
            "All original historical eligibility and validity remain in scope.",
        ],
    )
    path = work / "receipt.json"
    write_json(path, receipt)
    session = Session(preflight["container"], work, 60)
    baseline = None
    try:
        session.execute(
            "SET jit=off; SET max_parallel_workers_per_gather=0; "
            "SET plan_cache_mode=force_generic_plan"
        )
        receipt["statistic_identity"] = statistic_identity(session)
        if receipt["statistic_identity"] != preflight["statistic_identity"]:
            raise RuntimeError("Original analyzed statistics changed")
        receipt["protected_tables"] = protected_tables(session)
        if receipt["protected_tables"] != preflight["protected_tables"]:
            raise RuntimeError("Original protected table rows changed")
        receipt["function_metadata"] = function_metadata(session)
        definition = session.execute(
            "SELECT pg_get_functiondef('ingestion.graph_source_entities(text)'::regprocedure)"
        )
        if args.baseline_receipt:
            baseline = json.loads(args.baseline_receipt.read_text())
            if (
                baseline["status"] != "PASSED"
                or baseline["mode"] != "baseline"
                or baseline["container_id"] != inspected["Id"]
                or baseline["statistic_identity"] != receipt["statistic_identity"]
                or baseline["protected_tables"] != receipt["protected_tables"]
                or baseline["function_metadata"] != receipt["function_metadata"]
            ):
                raise RuntimeError("Exact same-clone baseline receipt required")
            receipt["baseline_receipt"] = str(args.baseline_receipt.resolve())
            receipt["baseline_receipt_sha256"] = digest(args.baseline_receipt)
            generator_path = ROOT / "hop/graph/tools/build_reader_fact_worksets.py"
            spec = importlib.util.spec_from_file_location("entity_generator", generator_path)
            assert spec and spec.loader
            generator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(generator)
            expected = generator.build()
            if args.candidate_sql.read_text() != expected:
                raise RuntimeError("Candidate differs from deterministic sealed generation")
            for source, name in (
                (generator_path, "launched-generator.py"),
                (generator.SOURCE, "launched-source.sql"),
                (args.candidate_sql, "launched-candidate.sql"),
            ):
                target = work / name
                shutil.copyfile(source, target)
                target.chmod(0o400)
                receipt[name + "_sha256"] = digest(target)
            if definition != preflight["entity_baseline_definition"]:
                raise RuntimeError("Candidate launch requires exact installed SQL008 definition")
            session.execute((work / "launched-candidate.sql").read_text())
            definition = session.execute(
                "SELECT pg_get_functiondef('ingestion.graph_source_entities(text)'::regprocedure)"
            )
        elif definition != preflight["entity_baseline_definition"]:
            raise RuntimeError("Baseline must be the exact installed SQL008 entity body")
        frozen = work / "entity-definition.sql"
        frozen.write_text(definition + "\n")
        frozen.chmod(0o400)
        receipt["entity_definition_sha256"] = digest(frozen)
        for index, run_id in enumerate(RUNS):
            for reader in READERS:
                tick = time.monotonic()
                raw = session.execute(typed_query(reader, run_id))
                elapsed = time.monotonic() - tick
                output = work / f"{index}-{reader}.json"
                output.write_text(raw + "\n")
                output.chmod(0o400)
                sample = dict(
                    run_id=run_id,
                    reader=reader,
                    rows=len(json.loads(raw)),
                    wall_seconds=elapsed,
                    result_sha256=digest(output),
                    result_file=output.name,
                )
                receipt["samples"].append(sample)
                if baseline:
                    old = next(
                        s
                        for s in baseline["samples"]
                        if s["run_id"] == run_id and s["reader"] == reader
                    )
                    original = args.baseline_receipt.parent / old["result_file"]
                    if (
                        digest(original) != old["result_sha256"]
                        or output.read_bytes() != original.read_bytes()
                    ):
                        raise RuntimeError("Exact complete typed reader bag differs: " + reader)
                write_json(path, receipt)
                print(json.dumps(sample), flush=True)
        if args.plans:
            query = re.sub(r"\bjobs\b", "$1", raw_query(definition))
            session.execute("PREPARE entity_raw(text) AS " + query)
            for run_id in (RUNS[1], RUNS[3]):
                tick = time.monotonic()
                valid = session.execute(
                    "SELECT ingestion.source_graph_run_is_valid(" + quote(run_id) + ")"
                )
                validation_wall = time.monotonic() - tick
                if valid != "t":
                    raise RuntimeError("Selected archived run is invalid")
                plan = json.loads(
                    session.execute(
                        "EXPLAIN(ANALYZE,VERBOSE,BUFFERS,TIMING OFF,FORMAT JSON) "
                        "EXECUTE entity_raw(" + quote(run_id) + ")"
                    )
                )[0]
                name = "raw-entity-plan-" + str(RUNS.index(run_id)) + ".json"
                write_json(work / name, plan)
                receipt["diagnostic_plans"][run_id] = dict(
                    plan=plan_summary(plan),
                    plan_sha256=digest(work / name),
                    standalone_validation_wall_seconds=validation_wall,
                    excludes_plpgsql_precondition=True,
                )
                write_json(path, receipt)
                print(
                    json.dumps({"run_id": run_id, **receipt["diagnostic_plans"][run_id]}),
                    flush=True,
                )
        if (
            statistic_identity(session) != receipt["statistic_identity"]
            or protected_tables(session) != receipt["protected_tables"]
            or function_metadata(session) != receipt["function_metadata"]
        ):
            raise RuntimeError("Statistics, protected rows or function metadata changed")
        receipt.update(
            status="PASSED",
            fixed_statistics=True,
            protected_table_count=157,
            exact_typed_reader_bags=bool(baseline),
            functions_except_entity_body_exact=True,
        )
    except BaseException as error:
        receipt.update(status="FAILED", failure_type=type(error).__name__, failure=str(error))
        raise
    finally:
        session.close()
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(path, receipt)
        path.chmod(0o400)
        print(path, flush=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--baseline-receipt", type=Path)
    parser.add_argument("--candidate-sql", type=Path)
    parser.add_argument("--plans", action="store_true")
    args = parser.parse_args()
    if bool(args.baseline_receipt) != bool(args.candidate_sql):
        parser.error("Candidate continuation requires both candidate SQL and baseline receipt")
    run(args)
