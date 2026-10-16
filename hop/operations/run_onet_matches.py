#!/usr/bin/env python3
"""Freeze local posting evidence and supervise the separate native O*NET matcher.

The cohort and every prompt/shortlist are private immutable files. Pilot, full and
resume use one cumulative $40 accounting scope; neither a new batch nor a new
task resets that limit. Provider transport and graph publication run in Hop.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import types
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import reconcile_runtime as common

REPO = common.ROOT.parent
sys.path.insert(0, str(REPO))
CAP = Decimal("40")
MODEL = "openai/gpt-5.6-luna"
COUNTS = {"jobkorea": 8434, "nara_job": 12736, "job_alio": 1465}
COHORT_SHA256 = "15c59e5bc6361896393554563aca61a808d152fba2ae1db7e6b69ee61500d1dc"
CATALOGUE_SHA256 = "7d49867a5889a187bd200dfb08cf5ab6bef631db6d9e6f36753c34374dcc7285"
RELEASE = "onet-31.0-catalogue-20261014"
DATABASE = "46AFBAE6C4FDF4D40BEA13D8B3CD2011FA1BDF7618A986BDC0DE58B12CAA114B"
TASK = "onet-metadata-20261014"
SCOPE = "ALL_ONET_METADATA_MATCHES_V1"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
WORKFLOWS = {
    "install": "llm/onet/install.hwf",
    "install-reconciliation": "llm/onet/install_reconciliation.hwf",
    "install-route-incident": "llm/onet/install_route_incident.hwf",
    "execute": "llm/onet/execute_matches.hwf",
    "publish": "llm/onet/publish_matches.hwf",
}
STAGES = ("freeze", "prepare", "deploy", "install", "install-reconciliation",
          "install-route-incident", "dry", "pilot", "approve-scale", "full", "resume",
          "publish", "status")


def now() -> str:
    return datetime.now(UTC).isoformat()


def identity(value: str) -> str:
    if not SAFE_ID.fullmatch(value) or value == "LATEST":
        raise argparse.ArgumentTypeError("Use an exact safe identity, never LATEST")
    return value


def money(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("Expected a decimal USD amount") from exc
    if not amount.is_finite() or not Decimal("0.001") <= amount <= CAP:
        raise argparse.ArgumentTypeError("USD amount must be between 0.001 and 40")
    return amount


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def file_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Evidence must be a regular file without symlinks")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "byte_length": path.stat().st_size}


def write_json(path: Path, value: Any, *, immutable: bool = False) -> None:
    data = canonical(value) + b"\n"
    if immutable:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600), "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        write_json(temporary, value, immutable=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_private(path: Path) -> dict[str, Any]:
    if path.stat().st_mode & 0o077:
        raise RuntimeError("Frozen manifests and receipts must be private")
    file_identity(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise RuntimeError("Expected a JSON object")
    return value


def check_cohort(rows: Any, expected_counts: dict[str, int] = COUNTS) -> dict[str, int]:
    if not isinstance(rows, list):
        raise RuntimeError("The locally frozen cohort must be a JSON array")
    seen: set[str] = set()
    counts = dict.fromkeys(expected_counts, 0)
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Invalid cohort row")
        posting = str(row.get("posting_identity", row.get("posting_id", "")))
        source = row.get("source_id")
        facts = row.get("source_fields", row.get("source_facts"))
        if not SAFE_ID.fullmatch(posting) or posting in seen or source not in counts:
            raise RuntimeError("Foreign source, duplicate or invalid source posting identity")
        # Canonical ontology duplicates never enter this source-only cohort.
        if not posting.startswith({"jobkorea": "source:posting:jobkorea:",
                                   "job_alio": "job-alio:posting:",
                                   "nara_job": "source:posting:nara_job:"}[source]):
            raise RuntimeError("Posting identity does not belong to its source namespace")
        if not isinstance(facts, dict) or not SHA256.fullmatch(
            str(row.get("source_facts_sha256", ""))
        ):
            raise RuntimeError("Missing exact frozen source facts or source evidence hash")
        for key in ("source_run_id", "source_record_id"):
            if not SAFE_ID.fullmatch(str(row.get(key, ""))):
                raise RuntimeError("Missing or unsafe source provenance identity")
        seen.add(posting)
        counts[source] += 1
    if counts != expected_counts:
        raise RuntimeError("The supplied source-only cohort counts differ from the frozen snapshot")
    return counts


def sql(pg: str, query: str) -> str:
    # SQL travels on stdin. Error output may include source facts or provider
    # bodies, so only the command status reaches the public exception.
    command = ["docker", "exec", "-i", pg, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
               "-U", "postgres", "-d", "jobtology"]
    try:
        result = subprocess.run(command, input=query.encode(), capture_output=True,
                                check=False, timeout=180)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Bounded O*NET database operation reached its deadline") from exc
    if result.returncode:
        raise RuntimeError("O*NET database operation failed; status " + str(result.returncode))
    return result.stdout.decode().strip()


def sql_json(pg: str, expression: str) -> Any:
    return json.loads(sql(pg, "SET statement_timeout='120s'; SELECT (" + expression + ")::text;"))


def json_sql(value: Any) -> str:
    """A fresh dollar delimiter avoids treating supplied metadata as SQL code."""
    data = canonical(value).decode()
    delimiter = "$onet_" + uuid.uuid4().hex + "$"
    if delimiter in data:
        raise RuntimeError("Unexpected SQL delimiter collision")
    return delimiter + data + delimiter + "::jsonb"


def freeze(args: argparse.Namespace) -> Path:
    from hop.llm.onet import lexicon, prompt, retrieval
    from hop.llm.onet.prompt import admitted_fields, build_request
    from hop.llm.onet.retrieval import CatalogueIndex

    code = {name: (Path(module.__file__), Path(module.__file__).read_bytes())
            for name, module in (("prompt.py", prompt), ("retrieval.py", retrieval),
                                 ("lexicon.py", lexicon))}
    source_identity = file_identity(args.source_file)
    catalogue_identity = file_identity(args.catalogue_file)
    if source_identity["sha256"] != args.source_sha256:
        raise RuntimeError("Original frozen source export SHA256 differs")
    if catalogue_identity["sha256"] != args.catalogue_sha256:
        raise RuntimeError("Frozen official O*NET catalogue SHA256 differs")
    rows = json.loads(args.source_file.read_bytes())
    continuation = None
    settings_value = settings(args)
    continuation_path = getattr(args, "continuation_proof", None)
    if continuation_path is not None:
        import onet_continuation

        continuation = onet_continuation.load_proof(
            continuation_path, args.continuation_sha256)
        expected_export = continuation["continuation_source_export"]
        if source_identity["sha256"] != expected_export["sha256"]:
            raise RuntimeError("Continuation source export differs from the bound proof")
        code_hashes = {"code/" + name: {"sha256": common.digest(data), "byte_length": len(data)}
                       for name, (_, data) in code.items()}
        onet_continuation.verify_contract(continuation, settings_value, code_hashes,
                                         args.task_id, args.release_id, args.database_id)
        counts = check_cohort(rows, continuation["_counts"])
        settings_value.update({"continuation_proof_sha256": args.continuation_sha256,
                               "predecessor_task_id": continuation["task_predecessor"]})
    else:
        counts = check_cohort(rows)
    catalogue = json.loads(args.catalogue_file.read_bytes())
    if catalogue.get("release_id") != args.release_id:
        raise RuntimeError("Catalogue release differs from the exact requested pin")
    index = CatalogueIndex(catalogue)
    frozen = []
    for ordinal, source in enumerate(sorted(
        rows, key=lambda row: row.get("posting_id", row.get("posting_identity"))
    ), 1):
        facts = source.get("source_facts", source.get("source_fields"))
        fields = admitted_fields(facts)
        decision = retrieval.admission_decision(fields) if hasattr(
            retrieval, "admission_decision") else None
        candidates = index.shortlist(fields, limit=args.candidate_limit)
        request = build_request(fields, candidates, max_matches=args.max_matches,
                                max_output_tokens=args.max_output_tokens)
        frozen_row = {
            "posting_identity": source.get("posting_identity", source.get("posting_id")),
            **{key: source[key] for key in ("source_id", "source_run_id", "source_record_id",
                                          "source_facts_sha256")},
            "source_fields": fields, "source_facts": facts,
            "candidates": candidates, "request_body": request,
        }
        if decision is not None:
            frozen_row["admission_decision"] = decision
        if hasattr(retrieval, "physician_eligibility"):
            frozen_row["physician_eligibility_decision"] = retrieval.physician_eligibility(fields)
        frozen.append(frozen_row)
        if ordinal % 500 == 0:
            print(json.dumps({"status": "FREEZING_LOCAL", "rows": ordinal, "total": len(rows)}),
                  flush=True)
    manifest = {
        "contract_version": "onet-metadata-cohort-v1", "frozen_at": now(),
        "task_id": args.task_id, "release_id": args.release_id, "database_id": args.database_id,
        "source_export": {"path": str(args.source_file.resolve()), **source_identity},
        "catalogue_export": {"path": str(args.catalogue_file.resolve()), **catalogue_identity},
        "counts": counts, "task_cap_usd": str(CAP), "cost_scope": SCOPE,
        "settings": settings_value, "rows": frozen,
    }
    if continuation is not None:
        manifest["continuation_proof"] = {"path": str(continuation_path.resolve()),
                                          **file_identity(continuation_path)}
    manifest["frozen_inputs_sha256"] = common.digest(canonical(frozen))
    directory = new_directory("freeze")
    (directory / "code").mkdir(mode=0o700)
    manifest["code_artifacts"] = {}
    for name, (original, data) in code.items():
        if original.read_bytes() != data:
            raise RuntimeError("Retrieval/prompt code changed during local cohort freezing")
        snapshot = directory / "code" / name
        with os.fdopen(os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600), "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        manifest["code_artifacts"]["code/" + name] = file_identity(snapshot)
    path = directory / "manifest.json"
    verify_frozen_admission(path, manifest)
    verify_frozen_physician_eligibility(path, manifest)
    write_json(path, manifest, immutable=True)
    print(json.dumps({"status": "FROZEN_LOCAL", "manifest": str(path), "counts": counts,
                      "sha256": file_identity(path)["sha256"]}), flush=True)
    return path


def settings(args: argparse.Namespace) -> dict[str, Any]:
    from hop.llm.onet import lexicon, prompt, retrieval

    value = {
        "max_cost_usd": str(CAP), "request_reserve_usd": str(args.reserve),
        "max_output_tokens": args.max_output_tokens, "max_matches": args.max_matches,
        "model": MODEL, "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "provider_only": ["openai"], "reasoning_effort": "none",
        "read_timeout_ms": 180000, "request_delay_ms": 250,
        "prompt_hash": prompt.PROMPT_HASH,
        "request_hash": prompt.REQUEST_HASH,
        "prompt_file_sha256": file_identity(Path(prompt.__file__))["sha256"],
        "schema_sha256": common.digest(canonical(prompt.SCHEMA)),
        "retrieval_hash": file_identity(Path(retrieval.__file__))["sha256"],
        "lexicon_file_sha256": file_identity(Path(lexicon.__file__))["sha256"],
        "hint_hash": retrieval.canonical_hash({"version": lexicon.HINT_VERSION,
                                                "rules": lexicon.HINT_ROWS}),
        "request_contract": {"max_price": {"prompt": "0.20", "completion": "1.20"},
                             "response_format": "json_schema", "stream": False,
                             "require_parameters": True, "allow_fallbacks": False},
        "execute_requests": "Y",
    }
    if hasattr(retrieval, "admission_decision"):
        value["admission_policy_sha256"] = retrieval.ADMISSION_HASH
        value["admission_policy_version"] = retrieval.ADMISSION_VERSION
    if hasattr(retrieval, "physician_eligibility"):
        value["physician_eligibility_policy_sha256"] = retrieval.PHYSICIAN_ELIGIBILITY_HASH
        value["physician_eligibility_policy_version"] = retrieval.PHYSICIAN_ELIGIBILITY_VERSION
    return value


def manifest_inputs(path: Path) -> dict[str, Any]:
    value = load_private(path)
    if value.get("contract_version") != "onet-metadata-cohort-v1":
        raise RuntimeError("Unsupported frozen cohort manifest")
    if value.get("cost_scope") != SCOPE or Decimal(value["task_cap_usd"]) != CAP:
        raise RuntimeError("The immutable combined O*NET task cap must be $40")
    identity(value["task_id"])
    identity(value["release_id"])
    identity(value["database_id"])
    for name in ("source_export", "catalogue_export"):
        evidence = value[name]
        actual = file_identity(Path(evidence["path"]))
        if actual != {key: evidence[key] for key in ("sha256", "byte_length")}:
            raise RuntimeError("Original local evidence bytes changed after freezing")
    if common.digest(canonical(value["rows"])) != value["frozen_inputs_sha256"]:
        raise RuntimeError("Frozen shortlist/request input checksum differs")
    if set(value.get("code_artifacts", {})) != {"code/prompt.py", "code/retrieval.py",
                                                "code/lexicon.py"}:
        raise RuntimeError("Frozen manifest must retain exact prompt/retrieval/hint code")
    for relative, expected in value["code_artifacts"].items():
        if file_identity(path.parent / relative) != expected:
            raise RuntimeError("Retained frozen prompt/retrieval/hint code changed")
    if "continuation_proof" in value:
        import onet_continuation

        proof = onet_continuation.verify_manifest(value)
        check_cohort(value["rows"], proof["_counts"])
    else:
        check_cohort(value["rows"])
    verify_frozen_admission(path, value)
    verify_frozen_physician_eligibility(path, value)
    return value


def new_directory(stage: str) -> Path:
    parent = common.STATE / "onet-matches"
    if parent.is_symlink():
        raise RuntimeError("Protected state directory must not be a symlink")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = parent / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + stage + "-" +
                          uuid.uuid4().hex[:12])
    directory.mkdir(mode=0o700)
    return directory


@contextlib.contextmanager
def operation_lock():
    os.umask(0o077)
    common.STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if common.STATE.is_symlink():
        raise RuntimeError("Runtime state directory must not be a symlink")
    descriptor = os.open(common.STATE / "refresh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                         0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Scheduler/native lock is busy") from exc
        for name in ("batchfree-migration.pending", "flat-ontology-migration.pending"):
            if (common.STATE / name).exists():
                raise RuntimeError("An existing protected migration fence is active")
        yield


@contextlib.contextmanager
def termination_signals():
    def interrupted(number, _frame):
        raise InterruptedError("Host O*NET operation interrupted by signal " + str(number))

    previous = {number: signal.signal(number, interrupted)
                for number in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def runtime_state(pg: str, task_id: str, batch_id: str | None = None, *,
                  installed: bool = True) -> dict[str, Any]:
    task = "'" + identity(task_id) + "'"
    batch = "NULL" if batch_id is None else "'" + identity(batch_id) + "'"
    task_expression = "onet_matching.task_status(" + task + ")" if installed else "NULL"
    batch_expression = ("CASE WHEN " + batch + " IS NULL THEN NULL ELSE " +
                        "onet_matching.batch_status(" + batch + ") END") if installed else "NULL"
    query = f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
SELECT jsonb_build_object(
 'unfinished_refresh',(SELECT count(*) FROM ingestion.refresh_execution WHERE finished_at IS NULL),
 'loading_runs',(SELECT count(*) FROM ingestion.run WHERE state='LOADING'),
 'retention_writers',(SELECT count(*) FROM retention.writer),
 'maintenance',ingestion.maintenance_active(),
 'legacy_baseline',jsonb_build_object(
  'source_requests',(SELECT count(*) FROM ingestion.request_attempt),
  'source_records',(SELECT count(*) FROM ingestion.record),
  'source_references',(SELECT count(*) FROM ingestion.graph_reference),
  'old_llm_attempts',(SELECT count(*) FROM enrichment.attempt),
  'old_llm_links',(SELECT count(*) FROM enrichment.metadata_occupation_candidate),
  'legacy_function_hash',(SELECT md5(string_agg(p.oid::text||':'||p.prosrc,E'\\n' ORDER BY p.oid))
   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname IN ('ingestion','enrichment','classification','ontology','retention','catalog')),
  'active_release_hash',enrichment.hash((SELECT coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb)::text
    FROM ontology.active_release r))),
 'task',{task_expression},
 'batch',{batch_expression}
);
COMMIT;"""
    return json.loads(sql(pg, query))


def require_idle(state: dict[str, Any]) -> None:
    for name in ("unfinished_refresh", "loading_runs", "retention_writers", "maintenance"):
        if state.get(name):
            raise RuntimeError("Runtime is busy: " + name)


def require_accounting(state: dict[str, Any], reserve: Decimal) -> None:
    task = state.get("task") or {}
    if task.get("unknown_requests", task.get("unknown_holds", 0)) or task.get("state") in (
        "COST_HOLD", "UNKNOWN_CHARGE_HOLD"
    ):
        raise RuntimeError("Unknown provider charge requires reconciliation before any new call")
    total = Decimal(str(task.get("accounted_usd", task.get("accounting_usd", "0"))))
    if total + reserve > CAP:
        raise RuntimeError("Combined O*NET accounting cap exhausted")


def require_batch_complete(batch: dict[str, Any] | None) -> None:
    if not batch or batch.get("execution_state") != "COMPLETE":
        raise RuntimeError("Native batch stopped before complete processing; inspect its receipt")
    states = batch.get("states") or {}
    if any(states.get(name, 0) for name in ("PLANNED", "RESERVED", "BUDGET_BLOCKED", "ERROR")):
        raise RuntimeError("Native batch left unsent or failed requests; inspect before continuing")


def publication_state(pg: str, publication_id: str, task_id: str) -> dict[str, Any]:
    return sql_json(pg, "jsonb_build_object('guard',(SELECT to_jsonb(g) FROM " +
        "onet_matching.graph_guard g WHERE publication_id='" + identity(publication_id) + "')," +
        "'observed_at',clock_timestamp(),'guard_ids',(SELECT coalesce(" +
        "jsonb_agg(publication_id ORDER BY publication_id),'[]'::jsonb) " +
        "FROM onet_matching.graph_guard),'guard_started_at',(SELECT coalesce(" +
        "jsonb_object_agg(publication_id,started_at),'{}'::jsonb) " +
        "FROM onet_matching.graph_guard),'task_binding',(SELECT jsonb_build_object(" +
        "'task_id',t.task_id,'release_id',t.release_id,'database_id',t.database_id," +
        "'catalog_hash',t.catalog_hash,'settings',t.settings,'settings_hash',t.settings_hash," +
        "'frozen_input_count',f.input_count,'manifest_hash',f.manifest_hash) " +
        "FROM onet_matching.task t JOIN onet_matching.freeze f USING(task_id) " +
        "WHERE t.task_id='" + identity(task_id) + "')," +
        "'writer_count',(SELECT count(*) FROM retention.writer WHERE writer_id='" +
        identity(publication_id) + "')) || (SELECT jsonb_build_object(" +
        "'current_count',count(*),'current_rows_hash',encode(sha256(convert_to(coalesce(" +
        "string_agg(content_hash,E'\\n' ORDER BY edge_id),''),'UTF8')),'hex')) " +
        "FROM onet_matching.graph_rows('" + identity(task_id) + "'))")


def require_publication(state: dict[str, Any], publication_id: str, task_id: str,
                        database_id: str) -> None:
    guard = state.get("guard") or {}
    if (guard.get("publication_id"), guard.get("task_id"), guard.get("database_id"),
        guard.get("state")) != (publication_id, task_id, database_id, "VERIFIED"):
        raise RuntimeError("The exact owned graph publication is not VERIFIED")
    if guard.get("verified_count") != guard.get("expected_count") or (
        guard.get("expected_count") != state.get("current_count") or
        guard.get("rows_hash") != state.get("current_rows_hash") or state.get("writer_count")
    ):
        raise RuntimeError("Verified graph count/hash or owned writer state differs")


def native_publication_id(receipt: dict[str, Any]) -> str:
    """Read the native-generated token only from this successful owned launch."""
    identity(receipt["owned_process_marker"])
    log = Path(receipt["log"])
    if receipt.get("stage") != "publish" or receipt.get("native_exit_code") != 0 or (
        file_identity(log) != receipt["log_identity"]
    ):
        raise RuntimeError("Owned publication launch/log evidence differs")
    tokens = re.findall(
        r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} - Remember exact catalogue token\.0 - "
        r"Set variable ONET_PUBLICATION_ID to value "
        r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]$",
        log.read_text(), re.MULTILINE)
    if len(tokens) != 1:
        raise RuntimeError("Owned log must identify exactly one native publication token")
    return tokens[0]


def require_owned_publication(before: dict[str, Any], after: dict[str, Any],
                              publication_id: str, manifest: dict[str, Any],
                              manifest_identity: dict[str, Any], started_at: str,
                              finished_at: str) -> None:
    """Bind a fresh native guard to the immutable task, plan and launch window."""
    task_id = manifest["task_id"]
    require_publication(after, publication_id, task_id, manifest["database_id"])
    old_ids = before.get("guard_ids")
    new_ids = after.get("guard_ids")
    if not isinstance(old_ids, list) or not isinstance(new_ids, list) or (
        len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids) or
        not set(old_ids) <= set(new_ids) or set(new_ids) - set(old_ids) != {publication_id}
    ):
        raise RuntimeError("Publication guard is reused, missing or not uniquely new")
    binding = after.get("task_binding") or {}
    expected_settings = {**manifest["settings"],
                         "frozen_manifest_sha256": manifest_identity["sha256"],
                         "source_cohort_sha256": manifest["source_export"]["sha256"],
                         "frozen_input_count": sum(manifest["counts"].values())}
    if before.get("task_binding") != binding or (
        binding.get("task_id"), binding.get("release_id"), binding.get("database_id"),
        binding.get("frozen_input_count"), binding.get("settings")
    ) != (task_id, manifest["release_id"], manifest["database_id"],
          expected_settings["frozen_input_count"], expected_settings):
        raise RuntimeError("Publication task differs from the exact frozen manifest")
    if any(not isinstance(binding.get(key), str) or not SHA256.fullmatch(binding[key])
           for key in ("catalog_hash", "settings_hash", "manifest_hash")):
        raise RuntimeError("Publication task lacks immutable catalogue/settings/freeze pins")
    guard = after["guard"]
    if (before.get("current_count"), before.get("current_rows_hash")) != (
        guard["expected_count"], guard["rows_hash"]
    ):
        raise RuntimeError("Publication plan changed after the launch snapshot")
    try:
        times = [datetime.fromisoformat(value) for value in
                 (started_at, before["observed_at"], guard["started_at"],
                  guard["finished_at"], finished_at)]
        observed_after = datetime.fromisoformat(after["observed_at"])
        if any(value.tzinfo is None for value in [*times, observed_after]) or (
            times != sorted(times) or observed_after < times[3]
        ):
            raise ValueError("outside owned launch window")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Publication guard timestamps differ from the owned launch") from exc


def pilot_ids(rows: list[dict[str, Any]], eligible: list[str], per_source: int = 12) -> list[str]:
    available = set(eligible)
    result = []
    for source_id in sorted(COUNTS):
        members = [row["posting_identity"] for row in rows
                   if row["source_id"] == source_id and row["posting_identity"] in available]
        members.sort(key=lambda posting: (hashlib.sha256(
            ("onet-pilot-v1:" + posting).encode()).hexdigest(), posting))
        result.extend(members[:per_source])
    return result


def explicit_pilot_ids(path: Path, rows: list[dict[str, Any]], eligible: list[str]
                       ) -> tuple[list[str], dict[str, Any]]:
    evidence = file_identity(path)
    data = path.read_bytes()
    if (common.digest(data), len(data)) != (evidence["sha256"], evidence["byte_length"]):
        raise RuntimeError("Pilot posting-ID file changed while being read")
    try:
        selected = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Pilot posting-ID file must contain an exact JSON list") from exc
    if not isinstance(selected, list) or len(selected) != 36:
        raise RuntimeError("Explicit pilot requires a JSON list of exactly 36 posting IDs")
    if any(not isinstance(posting, str) or not SAFE_ID.fullmatch(posting)
           for posting in selected):
        raise RuntimeError("Explicit pilot posting IDs must be exact safe strings")
    if len(set(selected)) != 36:
        raise RuntimeError("Explicit pilot posting IDs must be unique")
    sources = {row["posting_identity"]: row["source_id"] for row in rows}
    if any(posting not in sources for posting in selected):
        raise RuntimeError("Explicit pilot contains an ID outside the frozen source cohort")
    available = set(eligible)
    if any(posting not in available for posting in selected):
        raise RuntimeError("Explicit pilot contains an already planned or sent posting")
    selected_sources = [sources[posting] for posting in selected]
    if {source: selected_sources.count(source) for source in COUNTS} != dict.fromkeys(COUNTS, 12):
        raise RuntimeError("Explicit pilot requires exactly 12 frozen postings per source")
    return selected, {"method": "EXPLICIT_POSTING_IDS_FILE", "path": str(path.resolve()),
                      "file_identity": evidence, "posting_ids": selected}


def balanced_ids(rows: list[dict[str, Any]], eligible: list[str], limit: int) -> list[str]:
    available = set(eligible)
    members = {source: iter(sorted(row["posting_identity"] for row in rows
                                  if row["source_id"] == source and
                                  row["posting_identity"] in available))
               for source in sorted(COUNTS)}
    selected = []
    while len(selected) < limit:
        progress = False
        for source in members:
            posting = next(members[source], None)
            if posting is not None:
                selected.append(posting)
                progress = True
                if len(selected) == limit:
                    break
        if not progress:
            break
    return selected


def dry(args: argparse.Namespace) -> None:
    """Inspect every frozen request without installing or reserving any request."""
    manifest = manifest_inputs(args.manifest)
    admitted_fields = frozen_prompt(args.manifest, manifest).admitted_fields
    reserve = Decimal(manifest["settings"]["request_reserve_usd"])
    maximum = Decimal("0")
    empty = 0
    for row in manifest["rows"]:
        if admitted_fields(row["source_facts"]) != row["source_fields"]:
            raise RuntimeError("Frozen admitted fields differ from original listing evidence")
        request = row["request_body"]
        if request["model"] != MODEL or request["provider"]["only"] != ["openai"]:
            raise RuntimeError("Frozen provider/model routing changed")
        # UTF-8 bytes upper-bound input tokens, with framing overhead. The router
        # price ceiling includes the higher cache-write input rate and BYOK fee.
        bound = Decimal("1.05") * (Decimal("0.25") * (len(canonical(request)) + 256) +
                Decimal("1.20") * request["max_tokens"]) / Decimal("1000000")
        maximum = max(maximum, bound)
        if bound > reserve:
            raise RuntimeError("Frozen request exceeds its conservative USD reservation")
        empty += not row["candidates"]
    ids = pilot_ids(manifest["rows"], [row["posting_identity"] for row in manifest["rows"]])
    print(json.dumps({"status": "PASSED_OFFLINE_DRY", "task_id": manifest["task_id"],
                      "counts": manifest["counts"], "no_candidate_inputs": empty,
                      "largest_request_reservation_bound_usd": str(maximum),
                      "request_reserve_usd": str(reserve), "pilot_posting_ids": ids,
                      "task_cap_usd": str(CAP)}), flush=True)


def frozen_module(path: Path, manifest: dict[str, Any], module_name: str):
    """Use retained prompt/retrieval/hint bytes even after later repo edits."""
    name = "onet_frozen_" + common.digest(canonical(manifest["code_artifacts"]))[:24]
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(path.parent / "code")]
        sys.modules[name] = package
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        return importlib.import_module(name + "." + module_name)
    finally:
        sys.dont_write_bytecode = previous


def frozen_prompt(path: Path, manifest: dict[str, Any]):
    return frozen_module(path, manifest, "prompt")


def verify_frozen_admission(path: Path, manifest: dict[str, Any]) -> None:
    settings_value = manifest.get("settings", {})
    policy_hash = settings_value.get("admission_policy_sha256")
    has_decisions = any("admission_decision" in row for row in manifest["rows"])
    if policy_hash is None and not has_decisions:
        return  # Retained pre-admission manifests keep their original contract.
    if not isinstance(policy_hash, str) or not SHA256.fullmatch(policy_hash):
        raise RuntimeError("Frozen admission decisions require an immutable policy hash")
    retrieval = frozen_module(path, manifest, "retrieval")
    prompt = frozen_prompt(path, manifest)
    if (policy_hash, settings_value.get("admission_policy_version")) != (
        getattr(retrieval, "ADMISSION_HASH", None), getattr(retrieval, "ADMISSION_VERSION", None)
    ) or not hasattr(retrieval, "admission_decision"):
        raise RuntimeError("Frozen admission policy differs from the retained retrieval code")
    for row in manifest["rows"]:
        fields = prompt.admitted_fields(row["source_facts"])
        if canonical(fields) != canonical(row["source_fields"]):
            raise RuntimeError("Admission source fields differ from original frozen source facts")
        expected = retrieval.admission_decision(fields)
        if (not isinstance(expected, dict) or expected.get("outcome") not in ("INCLUDE", "EXCLUDE")
            or expected.get("policy_sha256") != policy_hash
            or expected.get("policy_version") != retrieval.ADMISSION_VERSION
            or canonical(expected) != canonical(row.get("admission_decision"))):
            raise RuntimeError("Frozen admission decision differs from retained code/source facts")
        if expected["outcome"] == "EXCLUDE" and row["candidates"]:
            raise RuntimeError("Excluded non-vacancy input must have an empty candidate shortlist")


def verify_frozen_physician_eligibility(path: Path, manifest: dict[str, Any]) -> None:
    settings_value = manifest.get("settings", {})
    policy_hash = settings_value.get("physician_eligibility_policy_sha256")
    has_decisions = any("physician_eligibility_decision" in row for row in manifest["rows"])
    if policy_hash is None and not has_decisions:
        return  # Earlier frozen contracts remain byte-for-byte compatible.
    if not isinstance(policy_hash, str) or not SHA256.fullmatch(policy_hash):
        raise RuntimeError("Physician eligibility requires its immutable policy hash")
    retrieval = frozen_module(path, manifest, "retrieval")
    prompt = frozen_prompt(path, manifest)
    if (policy_hash, settings_value.get("physician_eligibility_policy_version")) != (
        getattr(retrieval, "PHYSICIAN_ELIGIBILITY_HASH", None),
        getattr(retrieval, "PHYSICIAN_ELIGIBILITY_VERSION", None)
    ) or not hasattr(retrieval, "physician_eligibility"):
        raise RuntimeError("Physician eligibility differs from retained retrieval code")
    guarded = set(retrieval.PHYSICIAN_OCCUPATION_CODES)
    for row in manifest["rows"]:
        fields = prompt.admitted_fields(row["source_facts"])
        expected = retrieval.physician_eligibility(fields)
        if (canonical(fields) != canonical(row["source_fields"]) or
            expected.get("policy_sha256") != policy_hash or
            expected.get("policy_version") != retrieval.PHYSICIAN_ELIGIBILITY_VERSION or
            canonical(expected) != canonical(row.get("physician_eligibility_decision"))):
            raise RuntimeError("Physician eligibility decision differs from retained code/source")
        eligible = set(expected["eligible_occupation_codes"])
        offered = {candidate["occupation_code"] for candidate in row["candidates"]}
        if (not eligible <= guarded or offered & (guarded - eligible) or
            (expected["physician_only"] and not offered <= eligible)):
            raise RuntimeError("Frozen shortlist bypasses the physician eligibility policy")


def prepare_inputs(runtime: dict[str, str], manifest: dict[str, Any], path: Path,
                   receipt: dict[str, Any], receipt_path: Path) -> None:
    verify_frozen_admission(path, manifest)
    verify_frozen_physician_eligibility(path, manifest)
    chunks = list(bounded_freeze_chunks(manifest["rows"]))
    receipt["freeze_plan"] = [{"start_ordinal": start, "rows": len(chunk),
                              "estimated_jsonb_bytes": size} for start, chunk, size in chunks]
    task_id = identity(manifest["task_id"])
    receipt["prompt_registration"] = register_prompt(runtime["pg"], path, manifest)
    opts = {**manifest["settings"], "frozen_manifest_sha256": file_identity(path)["sha256"],
            "source_cohort_sha256": manifest["source_export"]["sha256"],
            "frozen_input_count": len(manifest["rows"])}
    receipt["task_creation"] = sql_json(runtime["pg"],
        "onet_matching.create_task('" + task_id + "','" + identity(manifest["release_id"]) +
        "','" + identity(manifest["database_id"]) + "'," + json_sql(opts) + ")")
    receipt["freeze_chunks"] = []
    for start, chunk, _size in chunks:
        result = sql_json(runtime["pg"], "onet_matching.freeze_inputs('" + task_id + "'," +
                          json_sql(chunk) + "," + str(start) + ")")
        receipt["freeze_chunks"].append(result)
        receipt["heartbeat_at"] = now()
        write_json(receipt_path, receipt)
        print(json.dumps({"status": "FREEZING", "rows": start + len(chunk) - 1,
                          "total": len(manifest["rows"]), "receipt": str(receipt_path)}),
              flush=True)
    receipt["freeze_result"] = sql_json(runtime["pg"], "onet_matching.finalize_freeze('" +
                                        task_id + "'," + str(len(manifest["rows"])) + ")")


def jsonb_text_bytes(value: Any) -> int:
    """Byte length of PostgreSQL JSONB text for a JSON-decoded local value."""
    if value is None:
        return 4
    if isinstance(value, bool):
        return 4 if value else 5
    if isinstance(value, str):
        return len(json.dumps(value, ensure_ascii=False).encode())
    if isinstance(value, int):
        return len(str(value))
    if isinstance(value, float | Decimal):
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            raise RuntimeError("Frozen JSON contains a non-finite number")
        if decimal.is_zero():
            decimal = abs(decimal)
        return len(format(decimal, "f"))
    if isinstance(value, list):
        return 2 + sum(jsonb_text_bytes(child) for child in value) + max(0, len(value) - 1) * 2
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise RuntimeError("Frozen JSON object keys must be strings")
        return 2 + sum(jsonb_text_bytes(key) + 2 + jsonb_text_bytes(child)
                       for key, child in value.items()) + max(0, len(value) - 1) * 2
    raise RuntimeError("Frozen input contains a non-JSON value")


def bounded_freeze_chunks(rows: list[dict[str, Any]], max_rows: int = 500,
                          max_bytes: int = 16777216):
    if not 1 <= max_rows <= 500 or not 2 <= max_bytes <= 16777216:
        raise RuntimeError("Invalid bounded freeze policy")
    start = 1
    chunk = []
    size = 2
    for ordinal, row in enumerate(rows, 1):
        row_size = jsonb_text_bytes(row)
        if row_size + 2 > max_bytes:
            raise RuntimeError("Frozen row exceeds JSONB chunk bound at ordinal " + str(ordinal))
        addition = row_size + (2 if chunk else 0)
        if chunk and (len(chunk) == max_rows or size + addition > max_bytes):
            yield start, chunk, size
            chunk = []
            start = ordinal
            size = 2
            addition = row_size
        chunk.append(row)
        size += addition
    if chunk:
        yield start, chunk, size


def prompt_contract(module: Any, settings_value: dict[str, Any]) -> dict[str, Any]:
    version = identity(module.PROMPT_VERSION)
    value = {"version": version, "text": module.PROMPT_TEXT, "schema": module.SCHEMA}
    if not isinstance(value["text"], str) or not value["text"].strip():
        raise RuntimeError("Pinned prompt text is empty")
    digest = common.digest(canonical(value))
    if digest != module.PROMPT_HASH or digest != settings_value["prompt_hash"]:
        raise RuntimeError("Pinned prompt version/text/schema hash differs from task settings")
    if common.digest(canonical(value["schema"])) != settings_value["schema_sha256"]:
        raise RuntimeError("Pinned output schema differs from immutable task settings")
    return {**value, "prompt_hash": digest}


def prompt_registration_sql(contract: dict[str, Any]) -> str:
    data = json_sql(contract)
    return """BEGIN;
SET LOCAL statement_timeout='30s';
DO $register$ DECLARE pinned jsonb:=""" + data + """; BEGIN
 IF NOT EXISTS(SELECT 1 FROM onet_matching.prompt_contract
   WHERE version='ko-onet-metadata-occupation-v1' AND schema=pinned->'schema')
 THEN RAISE EXCEPTION 'ONET_PINNED_SCHEMA_CHANGED_OR_BASE_INSTALL_MISSING'; END IF;
 INSERT INTO onet_matching.prompt_contract(version,prompt_text,prompt_hash,schema)
 VALUES(pinned->>'version',pinned->>'text',pinned->>'prompt_hash',pinned->'schema')
 ON CONFLICT(version) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM onet_matching.prompt_contract
  WHERE version=pinned->>'version' AND prompt_text=pinned->>'text'
    AND prompt_hash=pinned->>'prompt_hash' AND schema=pinned->'schema')
 THEN RAISE EXCEPTION 'ONET_PINNED_PROMPT_VERSION_COLLISION'; END IF;
END $register$;
SELECT jsonb_build_object('version',""" + data + """->>'version',
 'prompt_hash',""" + data + """->>'prompt_hash','registration','INSERT_ONLY_EXACT_REPLAY')::text;
COMMIT;"""


def register_prompt(pg: str, path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    pinned = frozen_prompt(path, manifest)
    contract = prompt_contract(pinned, manifest["settings"])
    return json.loads(sql(pg, prompt_registration_sql(contract)))


def execute_batches(args: argparse.Namespace, runtime: dict[str, str], manifest: dict[str, Any],
                    directory: Path, receipt: dict[str, Any]) -> None:
    pilot_file = getattr(args, "pilot_posting_ids_file", None)
    if pilot_file is not None and args.stage != "pilot":
        raise RuntimeError("Explicit pilot posting-ID files apply only to the pilot stage")
    task_id = identity(manifest["task_id"])
    reserve = Decimal(manifest["settings"]["request_reserve_usd"])
    receipt["artifact_hashes"] = artifacts(runtime["hop"], "execute")
    receipt["batches"] = []
    started = time.monotonic()
    while True:
        live = runtime_state(runtime["pg"], task_id)
        require_idle(live)
        counts = manifest["counts"] if "continuation_proof" in manifest else COUNTS
        if (live.get("task") or {}).get("frozen_input_count") != sum(counts.values()):
            raise RuntimeError("Seal the exact authorized source cohort before execution")
        states = (live.get("task") or {}).get("states") or {}
        if states.get("PLANNED", 0) or states.get("RESERVED", 0):
            raise RuntimeError("Resume the existing incomplete batch before planning new requests")
        eligible = sql_json(runtime["pg"], "onet_matching.eligible_inputs('" + task_id + "')")
        if not eligible and pilot_file is None:
            return
        require_accounting(live, reserve)
        if pilot_file is not None:
            selected, receipt["pilot_selection"] = explicit_pilot_ids(
                pilot_file, manifest["rows"], eligible)
            write_json(directory / "receipt.json", receipt)
        else:
            selected = (pilot_ids(manifest["rows"], eligible) if args.stage == "pilot" else
                        balanced_ids(manifest["rows"], eligible, args.batch_size)
                        if args.balanced_sources else eligible[:args.batch_size])
        if args.stage == "pilot" and len(selected) != 36:
            raise RuntimeError("The balanced pilot requires 12 untouched rows per source")
        if args.stage == "full" and not (live.get("task") or {}).get("scale_approved"):
            raise RuntimeError("Measured pilot review is required before full-scale requests")
        batch_id = args.batch_id or "onet-" + args.stage + "-" + uuid.uuid4().hex
        batch = {"batch_id": batch_id, "stage": args.stage, "status": "RUNNING",
                 "task_id": task_id, "started_at": now(), "posting_count": len(selected)}
        receipt["batch_id"] = batch_id
        receipt["batches"].append(batch)
        batch["planned"] = sql_json(runtime["pg"], "onet_matching.plan_batch('" + task_id +
            "','" + identity(batch_id) + "'," + json_sql(selected) + ",'" + args.stage.upper() +
            "'," + str(len(selected)) + "," + ("0.25" if args.stage == "pilot" else "40") + ")")
        child = directory / ("batch-" + str(len(receipt["batches"])).zfill(4))
        child.mkdir(mode=0o700)
        remaining = args.deadline_seconds - int(time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("The complete O*NET operation reached its wall-clock deadline")
        run_native(runtime, "execute", {"ONET_BATCH_ID": batch_id,
                   "REQUEST_WORKERS": str(args.workers)}, child, batch, remaining)
        if artifacts(runtime["hop"], "execute") != receipt["artifact_hashes"]:
            raise RuntimeError("Native matcher artifact bytes changed during execution")
        batch["after"] = runtime_state(runtime["pg"], task_id, batch_id)
        require_accounting(batch["after"], Decimal("0"))
        require_batch_complete(batch["after"]["batch"])
        if batch["after"]["legacy_baseline"] != receipt["before"]["legacy_baseline"]:
            raise RuntimeError("Existing source or NCS matcher baseline changed")
        batch["status"] = "COMPLETE"
        batch["finished_at"] = now()
        write_json(child / "receipt.json", batch)
        write_json(directory / "receipt.json", receipt)
        print(json.dumps({"status": "BATCH_COMPLETE", "batch_id": batch_id,
                          "task": batch["after"]["task"]}), flush=True)
        if args.stage == "pilot" or args.batch_id:
            return


def artifacts(hop: str, stage: str) -> dict[str, str]:
    pending = [WORKFLOWS[stage]]
    hashes: dict[str, str] = {}
    while pending:
        relative = pending.pop()
        if relative in hashes:
            continue
        if not re.fullmatch(r"llm/onet/[a-zA-Z0-9_./-]+\.(hwf|hpl|sql)", relative):
            raise RuntimeError("Native matcher dependency escapes its additive namespace")
        if ".." in Path(relative).parts:
            raise RuntimeError("Unsafe native matcher dependency")
        path = common.ROOT / relative
        expected = file_identity(path)
        script = b'''set -eu
path="$1"; project="$2"; current="$path"
while :; do
 test ! -L "$current" || exit 1
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
test -f "$path"
cat "$path"
'''
        data = common.command(["docker", "exec", "-i", hop, "sh", "-s", "--",
                               common.PROJECT + "/" + relative, common.PROJECT], data=script)
        if common.digest(data) != expected["sha256"]:
            raise RuntimeError("Deploy exact matching native bytes before execution: " + relative)
        hashes[relative] = expected["sha256"]
        if path.suffix in (".hwf", ".hpl"):
            for node in ET.fromstring(data).iter():
                if node.tag in ("filename", "sqlfilename") and (node.text or "").startswith(
                    "${PROJECT_HOME}/"
                ):
                    pending.append((node.text or "").removeprefix("${PROJECT_HOME}/"))
    return dict(sorted(hashes.items()))


def runtime_artifacts() -> dict[str, str]:
    result = {}
    folder = common.ROOT / "llm/onet"
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part in ("tests", "tools", "__pycache__") for part in relative.parts):
            continue
        if path.suffix in (".hwf", ".hpl", ".sql"):
            result[str(path.relative_to(common.ROOT))] = file_identity(path)["sha256"]
    if not set(WORKFLOWS.values()) <= result.keys():
        raise RuntimeError("Complete additive native matcher runtime is required")
    return result


def remote_public_bytes(hop: str, relative: str) -> bytes | None:
    if relative not in runtime_artifacts():
        raise RuntimeError("Remote path is outside the additive native matcher runtime")
    script = b'''set -eu
path="$1"; project="$2"; current="$path"
while :; do
 test ! -L "$current" || exit 1
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
if test -e "$path"; then
 test -f "$path" || exit 1
 printf 'PRESENT\\n'; cat "$path"
else printf 'ABSENT\\n'; fi
'''
    output = common.command(["docker", "exec", "-i", hop, "sh", "-s", "--",
                             common.PROJECT + "/" + relative, common.PROJECT], data=script)
    marker, data = output.split(b"\n", 1)
    if marker == b"ABSENT":
        return None
    if marker != b"PRESENT":
        raise RuntimeError("Unexpected native artifact readback")
    return data


def qualification(path: Path, hashes: dict[str, str]) -> dict[str, Any]:
    proof = load_private(path)
    if proof.get("status") not in ("PASSED_ONET_MATCHING_NATIVE", "PASSED_ONET_NATIVE_MATCHING"):
        raise RuntimeError("Deployment requires passed isolated native matching qualification")
    if not proof.get("isolated") or not proof.get("disposable_resources_removed"):
        raise RuntimeError("Qualification must confirm isolation and complete resource cleanup")
    if proof.get("artifact_sha256", proof.get("artifact_hashes")) != hashes:
        raise RuntimeError("Qualification does not bind the exact additive native runtime bytes")
    return proof


def deploy(args: argparse.Namespace) -> None:
    with operation_lock():
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        hashes = runtime_artifacts()
        proof = qualification(args.isolated_proof, hashes)
        before = runtime_state(runtime["pg"], args.task_id, installed=False)
        require_idle(before)
        directory = new_directory("deploy")
        path = directory / "receipt.json"
        receipt = {"contract_version": "onet-operation-receipt-v1", "stage": "deploy",
                   "status": "RUNNING", "started_at": now(), "task_id": args.task_id,
                   "runtime": runtime, "artifact_hashes": hashes, "before": before,
                   "qualification": str(args.isolated_proof.resolve()),
                   "qualification_identity": file_identity(args.isolated_proof),
                   "qualification_status": proof["status"], "published": []}
        write_json(path, receipt)
        stage = common.PROJECT + "/llm/.onet-runtime-" + uuid.uuid4().hex
        try:
            previous = {name: remote_public_bytes(runtime["hop"], name) for name in hashes}
            for name, data in previous.items():
                if data is not None and common.digest(data) != hashes[name]:
                    raise RuntimeError("Existing unexpected matcher bytes require separate review")
            receipt["previous"] = {name: common.digest(data) if data is not None else None
                                   for name, data in previous.items()}
            write_json(path, receipt)
            common.command(["docker", "exec", "-u", "root", runtime["hop"], "mkdir", "-m",
                            "700", "--", stage])
            for name, data in previous.items():
                if data is not None:
                    continue  # Exact deployment replay has no file mutation.
                destination = stage + "/" + name.removeprefix("llm/onet/")
                common.command(["docker", "exec", "-u", "root", runtime["hop"], "mkdir", "-p",
                                "--", destination.rsplit("/", 1)[0]])
                common.command(["docker", "cp", str(common.ROOT / name),
                                runtime["hop"] + ":" + destination])
                script = b'''set -eu
source="$1"; target="$2"; project="$3"; current=$(dirname "$target")
while :; do
 test ! -L "$current" || exit 1
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
test -f "$source"; test ! -L "$source"; test ! -e "$target"; test ! -L "$target"
mkdir -p -- "$(dirname "$target")"
chown 501:501 "$(dirname "$target")"; chmod 755 "$(dirname "$target")"
chown 501:501 "$source"; chmod 644 "$source"
ln -- "$source" "$target"
rm -- "$source"
'''
                common.command(["docker", "exec", "-u", "root", "-i", runtime["hop"], "sh",
                                "-s", "--", destination, common.PROJECT + "/" + name,
                                common.PROJECT], data=script)
                receipt["published"].append(name)
                write_json(path, receipt)
            for name, digest in hashes.items():
                data = remote_public_bytes(runtime["hop"], name)
                if data is None or common.digest(data) != digest:
                    raise RuntimeError("Published additive native artifact SHA256 differs")
            after = runtime_state(runtime["pg"], args.task_id, installed=False)
            receipt["after"] = after
            if before != after:
                raise RuntimeError("Deployment changed the existing PostgreSQL baseline")
            if runtime_artifacts() != hashes:
                raise RuntimeError("Repository native matcher bytes changed during deployment")
            receipt["status"] = "COMPLETE"
        except BaseException as exc:
            receipt["status"] = "FAILED"
            receipt["error"] = str(exc)
            raise
        finally:
            common.command(["docker", "exec", "-u", "root", runtime["hop"], "rm", "-rf", "--",
                            stage])
            receipt["finished_at"] = now()
            write_json(path, receipt)
            print(json.dumps({"status": receipt["status"], "stage": "deploy",
                              "receipt": str(path)}),
                  flush=True)


def native_args(hop: str, stage: str, params: dict[str, str], marker: str) -> list[str]:
    identity(marker)
    for key, value in params.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or any(char in value for char in ",\r\n"):
            raise RuntimeError("Unsafe native parameter")
    control = "/tmp/jobtology-onet-" + marker + ".pid"
    wrapper = '''set -eu
control="$1"; shift
test ! -e "$control"
command -v setsid >/dev/null
umask 077
setsid "$@" &
child=$!
test -r "/proc/$child/stat"
stat=$(cat "/proc/$child/stat"); stat=${stat##*) }; set -- $stat
shift 19
printf '%s %s\\n' "$child" "$1" > "$control"
wait "$child"
'''
    invocation = ["bash", "hop-run.sh", "-j", "default", "-r", "onet-local", "-f",
                  common.PROJECT + "/" + WORKFLOWS[stage], "-l", "Basic"]
    if params:
        invocation += ["-p", ",".join(key + "=" + value for key, value in params.items())]
    return ["docker", "exec", "-e", "HOP_OPTIONS=-Xmx1024m", "-e",
            "JOBTOLOGY_ONET_OPERATION=" + marker, "-w", "/usr/local/tomcat/webapps/ROOT",
            hop, "bash", "-c", wrapper, "onet-owned-wrapper", control, *invocation]


def cancel_owned(hop: str, marker: str, signal: str = "TERM") -> None:
    identity(marker)
    if signal not in ("TERM", "KILL"):
        raise RuntimeError("Invalid owned cancellation signal")
    script = b'''set -eu
control="$1"; marker="$2"; signal="$3"
test ! -L "$control"
test -f "$control" || exit 0
read -r pid stamp < "$control"
case "$pid:$stamp" in *[!0-9:]*|:*) exit 1;; esac
test -r "/proc/$pid/stat" || exit 0
stat=$(cat "/proc/$pid/stat"); stat=${stat##*) }; set -- $stat; shift 19
test "$1" = "$stamp" || exit 1
tr '\\000' '\\n' < "/proc/$pid/environ" | grep -Fx "JOBTOLOGY_ONET_OPERATION=$marker" >/dev/null
kill -"$signal" -- "-$pid"
'''
    common.command(["docker", "exec", "-i", hop, "bash", "-s", "--",
                    "/tmp/jobtology-onet-" + marker + ".pid", marker, signal], data=script)


def run_native(runtime: dict[str, str], stage: str, params: dict[str, str], directory: Path,
               receipt: dict[str, Any], deadline_seconds: int) -> None:
    marker = "onet-" + uuid.uuid4().hex
    receipt["owned_process_marker"] = marker
    log = directory / "native-basic.log"
    receipt["log"] = str(log)
    path = directory / "receipt.json"
    write_json(path, receipt)
    started = time.monotonic()
    process = None
    try:
        with log.open("xb") as output:
            process = subprocess.Popen(native_args(runtime["hop"], stage, params, marker),
                                       stdout=output, stderr=subprocess.STDOUT)
            while True:
                try:
                    code = process.wait(timeout=min(30, max(1, deadline_seconds -
                                                           int(time.monotonic() - started))))
                    break
                except subprocess.TimeoutExpired:
                    receipt["heartbeat_at"] = now()
                    receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    receipt["log_bytes"] = log.stat().st_size
                    write_json(path, receipt)
                    print(json.dumps({key: receipt[key] for key in ("status", "stage",
                                     "heartbeat_at", "elapsed_seconds", "log_bytes")}), flush=True)
                    if time.monotonic() - started >= deadline_seconds:
                        raise TimeoutError(
                            "Owned native operation reached its wall-clock deadline"
                        ) from None
            receipt["native_exit_code"] = code
            if code:
                raise RuntimeError("Native Hop failed; inspect the protected Basic log")
    except BaseException:
        if process is not None and process.poll() is None:
            cancel_owned(runtime["hop"], marker)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                cancel_owned(runtime["hop"], marker, "KILL")
                process.wait(timeout=15)
            receipt["owned_process_cancelled"] = True
        raise
    finally:
        if log.exists():
            receipt["log_identity"] = file_identity(log)
        common.idle_cli(runtime["hop"])


def execute(args: argparse.Namespace) -> None:
    is_install = args.stage in ("install", "install-reconciliation", "install-route-incident")
    manifest = manifest_inputs(args.manifest) if not is_install else None
    task_id = manifest["task_id"] if manifest else args.task_id
    batch_id = args.batch_id
    with operation_lock():
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        directory = new_directory(args.stage)
        path = directory / "receipt.json"
        receipt: dict[str, Any] = {"contract_version": "onet-operation-receipt-v1",
                                  "stage": args.stage, "status": "RUNNING", "started_at": now(),
                                  "task_id": task_id, "batch_id": batch_id, "runtime": runtime,
                                  "task_cap_usd": str(CAP), "cost_scope": SCOPE}
        if manifest:
            receipt["manifest"] = str(args.manifest.resolve())
            receipt["manifest_identity"] = file_identity(args.manifest)
        write_json(path, receipt)
        print(json.dumps({"status": "RUNNING", "receipt": str(path), "stage": args.stage}),
              flush=True)
        try:
            if is_install:
                before = runtime_state(runtime["pg"], task_id, installed=False)
                receipt["before"] = before
                require_idle(before)
                receipt["artifact_hashes"] = artifacts(runtime["hop"], args.stage)
                run_native(runtime, args.stage, {}, directory, receipt, args.deadline_seconds)
                after = runtime_state(runtime["pg"], task_id)
                receipt["after"] = after
                if before["legacy_baseline"] != after["legacy_baseline"]:
                    raise RuntimeError("Existing source or NCS baseline changed during install")
                require_idle(after)
            else:
                before = runtime_state(runtime["pg"], task_id, batch_id)
                receipt["before"] = before
                require_idle(before)
                if "continuation_proof" in manifest:
                    import onet_continuation

                    receipt["terminal_predecessor"] = (
                        onet_continuation.require_terminal_predecessor(runtime["pg"], manifest))
                if args.stage == "prepare":
                    prepare_inputs(runtime, manifest, args.manifest, receipt, path)
                elif args.stage in ("pilot", "full"):
                    execute_batches(args, runtime, manifest, directory, receipt)
                    batch_id = receipt["batch_id"]
                elif args.stage == "approve-scale":
                    notes = args.review_notes_file.read_text(encoding="utf-8")
                    if not notes.strip():
                        raise RuntimeError("Pilot notes must record quality and measured cost")
                    receipt["scale_approval"] = sql_json(runtime["pg"],
                        "onet_matching.approve_scale('" + identity(task_id) + "'," +
                        json_sql(args.review_actor) + " #>> '{}'," + json_sql(notes) + " #>> '{}')")
                elif args.stage == "resume":
                    require_accounting(before, Decimal(manifest["settings"]["request_reserve_usd"]))
                    receipt["artifact_hashes"] = artifacts(runtime["hop"], "execute")
                    run_native(runtime, "execute", {"ONET_BATCH_ID": identity(batch_id),
                               "ONET_RESUME": "Y",
                               "REQUEST_WORKERS": str(args.workers)}, directory, receipt,
                               args.deadline_seconds)
                elif args.stage == "publish":
                    receipt["artifact_hashes"] = artifacts(runtime["hop"], "publish")
                    receipt["publication_launch_before"] = publication_state(
                        runtime["pg"], "host-snapshot-" + uuid.uuid4().hex, task_id)
                    write_json(path, receipt)
                    run_native(runtime, "publish", {"ONET_TASK_ID": task_id,
                               "NEO4J_CONNECTION": "jobtology-neo4j"}, directory, receipt,
                               args.deadline_seconds)
                    publication_id = native_publication_id(receipt)
                    receipt["publication_candidate_id"] = publication_id
                    receipt["publication"] = publication_state(runtime["pg"], publication_id,
                                                                task_id)
                    require_owned_publication(receipt["publication_launch_before"],
                                              receipt["publication"], publication_id, manifest,
                                              receipt["manifest_identity"],
                                              receipt["started_at"], now())
                    receipt["publication_id"] = publication_id
                after = runtime_state(runtime["pg"], task_id, batch_id)
                receipt["after"] = after
                if before["legacy_baseline"] != after["legacy_baseline"]:
                    raise RuntimeError("Existing source or NCS matcher baseline changed")
                require_idle(after)
                if args.stage in ("pilot", "full", "resume"):
                    require_accounting(after, Decimal("0"))
                if args.stage == "resume":
                    require_batch_complete(after["batch"])
            receipt["status"] = "COMPLETE"
            native_stage = {"pilot": "execute", "full": "execute", "resume": "execute",
                            "install": "install",
                            "install-reconciliation": "install-reconciliation",
                            "install-route-incident": "install-route-incident",
                            "publish": "publish"}.get(args.stage)
            if native_stage and (
                artifacts(runtime["hop"], native_stage) != receipt["artifact_hashes"]
            ):
                raise RuntimeError("Native matcher artifact bytes changed during execution")
        except BaseException as exc:
            receipt["status"] = "FAILED"
            receipt["error"] = type(exc).__name__ + ": " + str(exc)
            if receipt.get("publication_id"):
                try:
                    sql(runtime["pg"], "SET statement_timeout='30s'; " +
                        "SELECT onet_matching.fail_graph('" + identity(receipt["publication_id"]) +
                        "');")
                    receipt["publication_failure"] = publication_state(runtime["pg"],
                        receipt["publication_id"], task_id)
                except Exception as cleanup_error:
                    receipt["publication_cleanup_error"] = str(cleanup_error)
            batch_id = receipt.get("batch_id")
            if batch_id is not None:
                try:
                    failed = runtime_state(runtime["pg"], task_id, batch_id)
                    token = (failed.get("batch") or {}).get("execution_token")
                    if token:
                        sql(runtime["pg"], "SET statement_timeout='30s'; " +
                            "SELECT onet_matching.stop_execution('" + identity(token) +
                            "','HOST_SUPERVISOR_STOP');")
                        receipt["stopped_execution"] = token
                    receipt["failure_state"] = runtime_state(runtime["pg"], task_id, batch_id)
                except Exception as cleanup_error:
                    receipt["cleanup_error"] = str(cleanup_error)
            raise
        finally:
            receipt["finished_at"] = now()
            write_json(path, receipt)
            print(json.dumps({"status": receipt["status"], "stage": args.stage,
                              "receipt": str(path), "batch_id": receipt["batch_id"]}), flush=True)


def status(args: argparse.Namespace) -> None:
    receipt = load_private(args.receipt) if args.receipt else None
    task_id = receipt["task_id"] if receipt else args.task_id
    batch_id = receipt.get("batch_id") if receipt else args.batch_id
    runtime = common.containers()
    state = runtime_state(runtime["pg"], task_id, batch_id)
    print(json.dumps({"task_id": task_id, "batch_id": batch_id, "live": state,
                      "receipt_status": receipt.get("status") if receipt else None}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--source-sha256", default=COHORT_SHA256)
    parser.add_argument("--continuation-proof", type=Path,
                        help="Freeze only: explicitly qualified remainder-of-original-cohort proof")
    parser.add_argument("--continuation-sha256",
                        help="Exact SHA256 of the qualified continuation scope proof")
    parser.add_argument("--catalogue-file", type=Path)
    parser.add_argument("--catalogue-sha256", default=CATALOGUE_SHA256)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--task-id", type=identity, default=TASK)
    parser.add_argument("--release-id", type=identity, default=RELEASE)
    parser.add_argument("--database-id", type=identity, default=DATABASE)
    parser.add_argument("--batch-id", type=identity)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--balanced-sources", action="store_true",
                        help="Select full batches in deterministic source round-robin order")
    parser.add_argument("--pilot-posting-ids-file", type=Path,
                        help="Pilot only: exact JSON list of 36 unique frozen IDs, 12 per source")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--reserve", type=money, default=Decimal("0.05"))
    parser.add_argument("--candidate-limit", type=int, default=24)
    parser.add_argument("--max-matches", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=768)
    parser.add_argument("--deadline-seconds", type=int, default=43200)
    parser.add_argument("--review-actor", type=identity, default="COORDINATOR")
    parser.add_argument("--review-notes-file", type=Path)
    parser.add_argument("--isolated-proof", type=Path)
    args = parser.parse_args()
    if args.continuation_proof is not None and (
        args.stage != "freeze" or not SHA256.fullmatch(args.continuation_sha256 or "")
    ):
        parser.error("--continuation-proof requires freeze and its exact --continuation-sha256")
    if args.continuation_sha256 is not None and args.continuation_proof is None:
        parser.error("--continuation-sha256 requires --continuation-proof")
    if args.pilot_posting_ids_file is not None and args.stage != "pilot":
        parser.error("--pilot-posting-ids-file applies only to the pilot stage")
    if not 1 <= args.workers <= 16 or not 1 <= args.batch_size <= 1000:
        parser.error("Workers must be 1..16 and batch size 1..1000")
    if not 1 <= args.max_matches <= 3 or not 1 <= args.candidate_limit <= 40:
        parser.error("Match cap must be 1..3 and candidate limit 1..40")
    if not 256 <= args.max_output_tokens <= 2048 or not 60 <= args.deadline_seconds <= 86400:
        parser.error("Output tokens must be 256..2048 and deadline 60..86400 seconds")
    if args.stage == "freeze":
        if args.source_file is None or args.catalogue_file is None:
            parser.error("freeze requires the original local --source-file and --catalogue-file")
        freeze(args)
    elif args.stage == "status":
        status(args)
    elif args.stage == "dry":
        if args.manifest is None:
            parser.error("dry requires the exact frozen --manifest")
        dry(args)
    elif args.stage == "deploy":
        if args.isolated_proof is None:
            parser.error("deploy requires the exact --isolated-proof")
        deploy(args)
    else:
        if args.stage not in (
            "install", "install-reconciliation", "install-route-incident"
        ) and args.manifest is None:
            parser.error("This stage requires the exact frozen --manifest")
        if args.stage == "resume" and args.batch_id is None:
            parser.error("resume requires the exact --batch-id")
        if args.stage == "approve-scale" and args.review_notes_file is None:
            parser.error("approve-scale requires actual --review-notes-file")
        execute(args)


if __name__ == "__main__":
    with termination_signals():
        main()
