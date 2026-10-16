#!/usr/bin/env python3
"""Run one inferred-occupation native stage under the scheduler lock.

Deploy plan/apply acquire their own lock; invoke them separately. This helper
never reads credentials. Native Basic output stays in a private log, with a
private receipt and a public-safe heartbeat every 30 seconds. Each plan/execute
uses a fresh immutable batch: a dry batch cannot be switched to paid execution.
"""

from __future__ import annotations

import argparse
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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import deploy_jobkorea_runtime as deployment
import reconcile_runtime as common

JOBS = "jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c"
NCS = "ba32f673-255c-4990-80d4-8dbef6008e2f"
SCOPE = "NCS_OCCUPATION_INFERENCE_V1"
TASK_COST_SCOPE = "ALL_METADATA_INFERENCE_BATCHES_V1"
DEFAULT_TASK_CAP = Decimal("4.75")
MAX_TASK_CAP = Decimal("50")
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")
WORKFLOWS = {
    "install": "ingestions/jobkorea/install_inferred_occupations.hwf",
    "plan": "ingestions/jobkorea/execute_inferred_occupations.hwf",
    "execute": "ingestions/jobkorea/execute_inferred_occupations.hwf",
    "publish": "ingestions/jobkorea/publish_inferred_occupations.hwf",
}
PROMPT_VERSIONS = (
    "ko-metadata-occupation-v1",
    "ko-metadata-occupation-v2",
    "ko-metadata-occupation-v3",
)
RETRIEVAL_V3 = "metadata-occupation-lexical-v3"
RETRIEVAL_REVISIONS = ("legacy", RETRIEVAL_V3)
WORKER_WORKFLOW = "ingestions/jobkorea/execute_inferred_occupation_workers.hwf"


def now() -> str:
    return datetime.now(UTC).isoformat()


def identity(value: str) -> str:
    if not IDENTITY.fullmatch(value) or value == "LATEST":
        raise argparse.ArgumentTypeError("Use an exact safe identity, never LATEST")
    return value


def money(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("Expected a decimal USD amount") from exc
    if not amount.is_finite() or not Decimal("0.001") <= amount <= MAX_TASK_CAP:
        raise argparse.ArgumentTypeError("USD amount must be between 0.001 and 50")
    return amount


def write_receipt(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def db_state(pg: str, jobs: str, ncs: str, batch: str | None = None) -> dict[str, Any]:
    # All interpolated identities passed the restrictive CLI grammar. No private
    # connection settings, responses or request bodies are selected.
    requested_batch = "NULL" if batch is None else "'" + identity(batch) + "'"
    query = f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
WITH metadata_accounting AS MATERIALIZED (
 SELECT b.job_run_id,b.ncs_run_id,a.state,a.cost_usd,a.reserved_usd,a.reserved_at
 FROM enrichment.batch b LEFT JOIN enrichment.attempt a USING(batch_id)
 WHERE b.settings->>'metadata_scope'='{SCOPE}'
)
SELECT jsonb_build_object(
 'pins',(SELECT jsonb_object_agg(source_id,run_id) FROM ingestion.latest_ready_run
   WHERE source_id IN ('jobkorea','ncs_competency')),
 'source_graphs',(SELECT count(*) FROM ingestion.graph_export WHERE run_id IN ('{jobs}','{ncs}')),
 'unfinished_refresh',(SELECT count(*) FROM ingestion.refresh_execution WHERE finished_at IS NULL),
 'loading_runs',(SELECT count(*) FROM ingestion.run WHERE state='LOADING'),
 'retention_writers',(SELECT count(*) FROM retention.writer),
 'maintenance',ingestion.maintenance_active(),
 'recent_running_batches',(SELECT count(*) FROM enrichment.batch
   WHERE state='RUNNING' AND created_at>clock_timestamp()-interval '24 hours'),
 'recent_reserved_requests',(SELECT count(*) FROM enrichment.attempt
   WHERE state='RESERVED' AND reserved_at>clock_timestamp()-interval '24 hours'),
 'retrieval_v3_installed',to_regprocedure(
   'enrichment.metadata_occupation_candidates_v3(text,jsonb,integer)') IS NOT NULL,
 'multimatch_v3_installed',to_regprocedure(
   'enrichment.metadata_occupation_output_issues_v3(jsonb,jsonb,jsonb,integer)') IS NOT NULL,
 'terminal_status_installed',coalesce((SELECT
   position('VALIDATION_FAILED' IN p.prosrc)>0 AND position('REQUEST_FAILED' IN p.prosrc)>0
   AND position('a.attempt_id=b.categorization_id' IN p.prosrc)>0
   FROM pg_proc p WHERE p.oid=to_regprocedure(
    'enrichment.metadata_occupation_status(text,text)')),false),
  'inference_installed',to_regprocedure(
   'enrichment.plan_metadata_occupation_batch(text,text,text,jsonb)') IS NOT NULL,
 'batch_exists',EXISTS(SELECT 1 FROM enrichment.batch WHERE batch_id={requested_batch}),
 'legacy_baseline',jsonb_build_object(
   'source_requests',(SELECT count(*) FROM ingestion.request_attempt),
   'frozen_job_inputs',(SELECT count(*) FROM enrichment.input_bundle WHERE job_run_id='{jobs}'),
   'duty_batches',(SELECT count(*) FROM enrichment.batch
     WHERE settings->>'prompt_version'='ko-link-v1'),
   'duty_attempts',(SELECT count(*) FROM enrichment.attempt a
     JOIN enrichment.batch b USING(batch_id)
     WHERE b.settings->>'prompt_version'='ko-link-v1'),
   'active_release_hash',enrichment.hash((SELECT coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb)::text
     FROM ontology.active_release r))),
 'task_cost_scope','{TASK_COST_SCOPE}',
 'task_cost',(SELECT jsonb_build_object(
   'requests',count(*) FILTER(WHERE a.reserved_at IS NOT NULL),
   'reported_usd',coalesce(sum(a.cost_usd) FILTER(WHERE a.reserved_at IS NOT NULL),0)::text,
   'accounted_usd',coalesce(sum(enrichment.accounted_cost(a.state,a.cost_usd,a.reserved_usd))
      FILTER(WHERE a.reserved_at IS NOT NULL),0)::text,
   'unknown_requests',count(*) FILTER(WHERE a.reserved_at IS NOT NULL AND a.cost_usd IS NULL))
   FROM metadata_accounting a),
 'current_pin_cost',(SELECT jsonb_build_object(
   'requests',count(*) FILTER(WHERE a.reserved_at IS NOT NULL),
   'reported_usd',coalesce(sum(a.cost_usd) FILTER(WHERE a.reserved_at IS NOT NULL),0)::text,
   'accounted_usd',coalesce(sum(enrichment.accounted_cost(a.state,a.cost_usd,a.reserved_usd))
      FILTER(WHERE a.reserved_at IS NOT NULL),0)::text,
   'unknown_requests',count(*) FILTER(WHERE a.reserved_at IS NOT NULL AND a.cost_usd IS NULL))
   FROM metadata_accounting a WHERE a.job_run_id='{jobs}' AND a.ncs_run_id='{ncs}'),
 'batch',(SELECT jsonb_build_object('batch_id',b.batch_id,'state',b.state,
   'postings',(SELECT count(*) FROM enrichment.item i WHERE i.batch_id=b.batch_id),
   'validated',(SELECT count(*) FROM enrichment.item i
     WHERE i.batch_id=b.batch_id AND i.state='VALIDATED'),
   'attempt_states',(SELECT jsonb_object_agg(state,n) FROM
     (SELECT state,count(*) AS n FROM enrichment.attempt a
       WHERE a.batch_id=b.batch_id GROUP BY state) q),
   'reported_usd',(SELECT coalesce(sum(cost_usd),0)::text FROM enrichment.attempt a
      WHERE a.batch_id=b.batch_id AND a.reserved_at IS NOT NULL),
   'accounted_usd',(SELECT coalesce(sum(
      enrichment.accounted_cost(state,cost_usd,reserved_usd)),0)::text
      FROM enrichment.attempt a WHERE a.batch_id=b.batch_id AND a.reserved_at IS NOT NULL))
   FROM enrichment.batch b WHERE batch_id={requested_batch})
);
COMMIT;"""
    return json.loads(deployment.sql(pg, query))


def require_idle(state: dict[str, Any], jobs: str, ncs: str) -> None:
    if state["pins"] != {"jobkorea": jobs, "ncs_competency": ncs}:
        raise RuntimeError("Exact current JobKorea/NCS READY pins changed")
    if state["source_graphs"] != 2:
        raise RuntimeError("Both exact source graph checkpoints are required")
    for name in (
        "unfinished_refresh",
        "loading_runs",
        "retention_writers",
        "maintenance",
        "recent_running_batches",
        "recent_reserved_requests",
    ):
        if state[name]:
            raise RuntimeError("Runtime is busy: " + name)
    # PLANNED batches and reservations older than 24h are historical evidence.
    # The independent native-process check still rejects any live CLI.


def bounded_budget(requested: Decimal, task_cap: Decimal, state: dict[str, Any]) -> Decimal:
    if state.get("task_cost_scope") != TASK_COST_SCOPE:
        raise RuntimeError(
            "Cumulative task accounting requires all metadata batches across source pins"
        )
    remaining = task_cap - Decimal(str(state["task_cost"]["accounted_usd"]))
    budget = min(requested, remaining)
    if budget < Decimal("0.001"):
        raise RuntimeError("Cumulative task accounting cap exhausted; recharge does not reset it")
    return budget


def workflow(stage: str, workers: int = 1) -> str:
    return WORKER_WORKFLOW if stage == "execute" and workers > 1 else WORKFLOWS[stage]


def artifacts(
    hop: str,
    stage: str,
    workers: int = 1,
    prompt_version: str = PROMPT_VERSIONS[0],
    retrieval_revision: str = RETRIEVAL_V3,
) -> dict[str, str]:
    if prompt_version not in PROMPT_VERSIONS:
        raise RuntimeError("Unsupported immutable metadata prompt version")
    if retrieval_revision not in RETRIEVAL_REVISIONS:
        raise RuntimeError("Unsupported metadata retrieval revision")
    # Both prompts are immutable canonical installer dependencies. Keep the
    # selected version explicit even when planning with the historical v1.
    pending = [
        workflow(stage, workers),
        "llm/sql/029_metadata_occupation_links.sql",
        "llm/sql/030_metadata_occupation_native.sql",
        "llm/sql/031_metadata_occupation_workers.sql",
        "llm/sql/032_metadata_occupation_context.sql",
        "llm/sql/033_metadata_occupation_roles.sql",
        "llm/sql/034_metadata_occupation_pm.sql",
        "llm/sql/035_metadata_occupation_terminal_status.sql",
        "llm/sql/037_metadata_occupation_multimatch.sql",
        "llm/prompts/categorize-ko-metadata-occupation-v1.txt",
        "llm/prompts/categorize-ko-metadata-occupation-v1.schema.json",
        "llm/prompts/categorize-ko-metadata-occupation-v2.txt",
        "llm/prompts/categorize-ko-metadata-occupation-v2.schema.json",
        "llm/prompts/categorize-ko-metadata-occupation-v3.txt",
        "llm/prompts/categorize-ko-metadata-occupation-v3.schema.json",
    ]
    hashes: dict[str, str] = {}
    while pending:
        relative = pending.pop()
        if relative in hashes:
            continue
        if relative not in deployment.ALLOWLIST:
            raise RuntimeError("Unexpected native dependency outside deployment allowlist")
        path = common.ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Invalid public native artifact: " + relative)
        data = path.read_bytes()
        if deployment.remote_bytes(hop, relative) != data:
            raise RuntimeError("Deploy matching native artifact bytes before running: " + relative)
        hashes[relative] = common.digest(data)
        if path.suffix in (".hpl", ".hwf"):
            for node in ET.fromstring(data).iter():
                if node.tag in ("filename", "sqlfilename") and (node.text or "").startswith(
                    "${PROJECT_HOME}/"
                ):
                    pending.append((node.text or "").removeprefix("${PROJECT_HOME}/"))
    return dict(sorted(hashes.items()))


def native_args(hop: str, stage: str, params: dict[str, str], workers: int = 1) -> list[str]:
    for key, value in params.items():
        if not re.fullmatch(r"[A-Z_]+", key) or any(c in value for c in ",\r\n"):
            raise RuntimeError("Unsafe native parameter")
    args = [
        "docker",
        "exec",
        "-e",
        "HOP_OPTIONS=-Xmx1024m",
        "-w",
        "/usr/local/tomcat/webapps/ROOT",
        hop,
        "bash",
        "hop-run.sh",
        "-j",
        "default",
        "-r",
        "jobkorea-local",
        "-f",
        common.PROJECT + "/" + workflow(stage, workers),
        "-l",
        "Basic",
    ]
    if params:
        args += ["-p", ",".join(key + "=" + value for key, value in params.items())]
    return args


def parameters(args: argparse.Namespace, batch: str, budget: Decimal) -> dict[str, str]:
    pins = {"JOB_RUN_ID": args.jobs, "NCS_RUN_ID": args.ncs}
    if args.stage == "install":
        return {}
    if args.stage == "publish":
        return {**pins, "INCLUDE_UNREVIEWED": "Y" if args.include_unreviewed else "N"}
    return {
        **pins,
        "BATCH_ID": batch,
        "POSTING_LIMIT": str(args.limit),
        "POSTING_IDS": args.posting_ids,
        "EXECUTE_REQUESTS": "Y" if args.stage == "execute" else "N",
        "MAX_COST_USD": str(budget),
        "DAILY_BUDGET_USD": str(args.task_cap),
        "MAX_REQUESTS": str(args.max_requests or args.limit),
        "REQUEST_RESERVE_USD": str(args.reserve),
        "REUSE_CACHE": "Y",
        "CATEGORIZE_MODEL": "openai/gpt-5.6-luna",
        "PROMPT_VERSION": args.prompt_version,
        "RETRIEVAL_REVISION": ""
        if args.retrieval_revision == "legacy"
        else args.retrieval_revision,
        "PROVIDER_ONLY": "openai",
        "REASONING_EFFORT": "none",
        "MAX_OUTPUT_TOKENS": str(
            getattr(args, "max_output_tokens", None)
            or (1536 if args.prompt_version == "ko-metadata-occupation-v3" else 768)
        ),
        "CANDIDATE_LIMIT": "12",
        "MAX_MATCHES": str(
            getattr(args, "max_matches", None)
            or (3 if args.prompt_version == "ko-metadata-occupation-v3" else 1)
        ),
        "MAX_INPUT_CHARS": "16000",
        "REQUEST_DELAY_MS": "250",
        "READ_TIMEOUT_MS": "180000",
        **(
            {"REQUEST_WORKERS": str(args.workers)}
            if args.stage == "execute" and args.workers > 1
            else {}
        ),
    }


def execute(args: argparse.Namespace) -> None:
    os.umask(0o077)
    common.STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if common.STATE.is_symlink():
        raise RuntimeError("Runtime state directory must not be a symlink")
    descriptor = os.open(
        common.STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Scheduler/native lock is busy; retry after the active operation finishes"
            ) from exc
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        batch = args.batch_id or "metadata-" + args.stage + "-" + uuid.uuid4().hex
        before = db_state(runtime["pg"], args.jobs, args.ncs, batch)
        require_idle(before, args.jobs, args.ncs)
        if before["batch_exists"] and args.stage in ("plan", "execute"):
            raise RuntimeError(
                "Use a fresh batch ID; existing immutable batches are not replayed here"
            )
        if args.stage != "install" and not before["inference_installed"]:
            raise RuntimeError("Install the inferred-occupation SQL first")
        if (
            args.stage in ("plan", "execute")
            and args.prompt_version == "ko-metadata-occupation-v3"
            and not before.get("multimatch_v3_installed", False)
        ):
            raise RuntimeError("Install opt-in multi-occupation SQL 037 before planning v3 batches")
        budget = (
            bounded_budget(args.max_cost, args.task_cap, before)
            if args.stage == "execute"
            else args.max_cost
        )
        if args.stage == "execute" and budget < args.reserve:
            raise RuntimeError(
                "Remaining batch budget is below one conservative request reservation"
            )
        if (
            args.stage in ("plan", "execute")
            and args.retrieval_revision == RETRIEVAL_V3
            and not before["retrieval_v3_installed"]
        ):
            raise RuntimeError(
                "Install corrected metadata retrieval SQL before planning new v3 batches"
            )
        hashes = artifacts(
            runtime["hop"], args.stage, args.workers, args.prompt_version, args.retrieval_revision
        )
        params = parameters(args, batch, budget)
        parent = common.STATE / "inferred-occupations"
        if parent.is_symlink():
            raise RuntimeError("Receipt directory must not be a symlink")
        parent.mkdir(mode=0o700, exist_ok=True)
        directory = parent / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + args.stage + "-" + uuid.uuid4().hex[:12]
        )
        directory.mkdir(mode=0o700)
        path = directory / "receipt.json"
        log = directory / "native-basic.log"
        receipt: dict[str, Any] = {
            "version": 1,
            "stage": args.stage,
            "status": "RUNNING",
            "started_at": now(),
            "batch_id": batch if args.stage in ("plan", "execute") else None,
            "job_run_id": args.jobs,
            "ncs_run_id": args.ncs,
            "runtime": runtime,
            "workflow": workflow(args.stage, args.workers),
            "workers": args.workers if args.stage == "execute" else 1,
            "artifact_hashes": hashes,
            "prompt_version": args.prompt_version,
            "retrieval_revision": args.retrieval_revision
            if args.stage in ("plan", "execute")
            else None,
            "parameters": params,
            "task_cap_usd": str(args.task_cap),
            "before": before,
            "log": str(log),
        }
        write_receipt(path, receipt)
        print(
            json.dumps(
                {
                    "status": "RUNNING",
                    "stage": args.stage,
                    "batch_id": receipt["batch_id"],
                    "receipt": str(path),
                    "log": str(log),
                }
            ),
            flush=True,
        )
        try:
            with log.open("xb") as output:
                process = subprocess.Popen(
                    native_args(runtime["hop"], args.stage, params, args.workers),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                while True:
                    try:
                        code = process.wait(timeout=30)
                        break
                    except subprocess.TimeoutExpired:
                        receipt["heartbeat_at"] = now()
                        receipt["log_bytes"] = log.stat().st_size
                        write_receipt(path, receipt)
                        print(
                            json.dumps(
                                {
                                    "status": "RUNNING",
                                    "stage": args.stage,
                                    "receipt": str(path),
                                    "log_bytes": receipt["log_bytes"],
                                }
                            ),
                            flush=True,
                        )
            receipt["native_exit_code"] = code
            receipt["after"] = db_state(runtime["pg"], args.jobs, args.ncs, batch)
            if code:
                raise RuntimeError("Native Hop failed; inspect the protected Basic log")
            after = receipt["after"]
            if (
                after["pins"] != before["pins"]
                or after["legacy_baseline"] != before["legacy_baseline"]
            ):
                raise RuntimeError(
                    "Source pins or narrow legacy baseline changed during native stage"
                )
            if after["retention_writers"]:
                raise RuntimeError("Native stage left an active retention writer")
            if (
                artifacts(
                    runtime["hop"],
                    args.stage,
                    args.workers,
                    args.prompt_version,
                    args.retrieval_revision,
                )
                != hashes
            ):
                raise RuntimeError("Native artifact bytes changed during execution")
            if args.stage == "install" and not after["inference_installed"]:
                raise RuntimeError("Native installer did not install the inference planner")
            if args.stage == "install" and not after["retrieval_v3_installed"]:
                raise RuntimeError(
                    "Native installer did not install corrected metadata retrieval v3"
                )
            if args.stage == "install" and not after["terminal_status_installed"]:
                raise RuntimeError(
                    "Native installer did not install terminal inference failure statuses"
                )
            if args.stage == "execute" and (
                after["batch"] is None
                or after["batch"]["state"] not in ("COMPLETE", "PARTIAL", "FAILED")
            ):
                raise RuntimeError("Paid native execution did not finish its immutable batch")
            receipt["status"] = "COMPLETE"
        except Exception as exc:
            receipt["status"] = "FAILED"
            receipt["error"] = str(exc)
            raise
        finally:
            receipt["finished_at"] = now()
            if log.exists():
                with log.open("rb") as content:
                    receipt["log_sha256"] = hashlib.file_digest(content, "sha256").hexdigest()
                receipt["log_bytes"] = log.stat().st_size
            write_receipt(path, receipt)
            print(
                json.dumps(
                    {
                        "status": receipt["status"],
                        "stage": args.stage,
                        "receipt": str(path),
                        "batch_id": receipt["batch_id"],
                        "task_cost": receipt.get("after", {}).get("task_cost"),
                    }
                ),
                flush=True,
            )


def status(path: Path) -> None:
    root = common.STATE / "inferred-occupations"
    if (
        path.is_symlink()
        or not path.resolve().is_relative_to(root.resolve())
        or path.name != "receipt.json"
    ):
        raise RuntimeError("Status requires an existing protected inferred-occupation receipt")
    if path.stat().st_mode & 0o077:
        raise RuntimeError("Receipt permissions must be private")
    receipt = json.loads(path.read_text())
    runtime = common.containers()
    live = db_state(
        runtime["pg"],
        identity(receipt["job_run_id"]),
        identity(receipt["ncs_run_id"]),
        receipt["batch_id"],
    )
    print(
        json.dumps(
            {
                "receipt": str(path),
                "status": receipt["status"],
                "stage": receipt["stage"],
                "started_at": receipt["started_at"],
                "finished_at": receipt.get("finished_at"),
                "batch_id": receipt["batch_id"],
                "pins": live["pins"],
                "batch": live["batch"],
                "task_cost": live["task_cost"],
                "log_bytes": receipt.get("log_bytes"),
            }
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=(*WORKFLOWS, "status"))
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--jobs", type=identity, default=JOBS)
    parser.add_argument("--ncs", type=identity, default=NCS)
    parser.add_argument("--batch-id", type=identity)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--posting-ids", default="", help="Optional exact pipe-separated posting IDs"
    )
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--max-cost", type=money, default=Decimal("0.05"))
    parser.add_argument("--task-cap", type=money, default=DEFAULT_TASK_CAP)
    parser.add_argument("--reserve", type=money, default=Decimal("0.005"))
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument("--prompt-version", choices=PROMPT_VERSIONS, default=PROMPT_VERSIONS[0])
    parser.add_argument(
        "--max-matches",
        type=int,
        help="Immutable match cap: v1/v2 1..2 (default 1); opt-in v3 1..3 (default 3)",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        help="Bounded output 256..2048; v1/v2 default 768, opt-in v3 default 1536",
    )
    parser.add_argument(
        "--retrieval-revision",
        choices=RETRIEVAL_REVISIONS,
        default=RETRIEVAL_V3,
        help="Corrected retrieval for fresh batches; legacy preserves old request identity",
    )
    parser.add_argument("--workers", type=int, default=1, help="Native paid request workers (1..8)")
    args = parser.parse_args()
    if args.max_matches is not None and not 1 <= args.max_matches <= (
        3 if args.prompt_version == "ko-metadata-occupation-v3" else 2
    ):
        parser.error("Match cap exceeds the selected immutable prompt contract")
    if args.max_output_tokens is not None and not 256 <= args.max_output_tokens <= 2048:
        parser.error("Output tokens must be between 256 and 2048")
    if not 1 <= args.workers <= 8:
        parser.error("Native request workers must be between 1 and 8")
    if not 1 <= args.limit <= 10000 or (
        args.max_requests is not None and not 1 <= args.max_requests <= 10000
    ):
        parser.error("Posting/request limits must be between 1 and 10000")
    selected: list[str] = str(args.posting_ids).split("|") if args.posting_ids else []
    if (
        len(selected) > args.limit
        or len(selected) != len(set(selected))
        or any(not IDENTITY.fullmatch(value) for value in selected)
    ):
        parser.error("Posting IDs must be unique safe identities within the posting limit")
    if args.stage == "status":
        if args.receipt is None:
            parser.error("status requires --receipt")
        status(args.receipt)
    else:
        if args.receipt is not None:
            parser.error("--receipt is only used by status")
        execute(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
