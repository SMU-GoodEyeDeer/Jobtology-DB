"""Offline checks for frozen-cohort integrity and paid native supervision."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("onet_match_supervisor", OPS / "run_onet_matches.py")
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def source_row(number: int = 1, source: str = "jobkorea") -> dict:
    prefix = {"jobkorea": "source:posting:jobkorea:", "nara_job": "source:posting:nara_job:",
              "job_alio": "job-alio:posting:"}[source]
    return {"posting_identity": prefix + str(number), "source_id": source,
            "source_run_id": "frozen-run", "source_record_id": str(number) + ":detail",
            "source_facts_sha256": "a" * 64, "source_fields": {"title": "개발자"}}


@pytest.mark.parametrize("value", ["41", "45.90", "NaN", "Infinity", "0", "-1"])
def test_authorized_40_cap_cannot_be_raised_or_reset_by_balance(value):
    with pytest.raises(argparse.ArgumentTypeError):
        ops.money(value)
    assert Decimal("40") == ops.CAP


@pytest.mark.parametrize("change", ["duplicate", "ontology", "foreign", "provenance", "hash"])
def test_exact_source_cohort_rejects_drift(change):
    row = source_row()
    rows = [row]
    if change == "duplicate":
        rows.append(dict(row))
    elif change == "ontology":
        row["posting_identity"] = "ontology:posting:1234"
    elif change == "foreign":
        row["source_id"] = "job_board"
    elif change == "provenance":
        row["source_record_id"] = ""
    else:
        row["source_facts_sha256"] = "unknown"
    with pytest.raises(RuntimeError):
        ops.check_cohort(rows, {"jobkorea": 1})


def test_source_counts_are_exact_and_scrape_times_are_not_synthesized():
    row = source_row()
    assert ops.check_cohort([row], {"jobkorea": 1}) == {"jobkorea": 1}
    with pytest.raises(RuntimeError, match="counts"):
        ops.check_cohort([row], {"jobkorea": 2})
    assert "scraped_at" not in row


def test_pilot_is_balanced_deterministic_and_filters_already_planned_inputs():
    rows = [source_row(number, source) for source in ops.COUNTS for number in range(20)]
    ids = [row["posting_identity"] for row in rows]
    selected = ops.pilot_ids(rows, ids)
    assert selected == ops.pilot_ids(list(reversed(rows)), list(reversed(ids)))
    assert len(selected) == len(set(selected)) == 36
    selected_sources = [next(row["source_id"] for row in rows
                             if row["posting_identity"] == posting) for posting in selected]
    assert {source: selected_sources.count(source) for source in ops.COUNTS} == dict.fromkeys(
        ops.COUNTS, 12)
    assert selected[0] not in ops.pilot_ids(rows, [posting for posting in ids
                                                if posting != selected[0]])


def test_explicit_pilot_pins_file_bytes_and_preserves_preregistered_order(tmp_path):
    rows = [source_row(number, source) for source in ops.COUNTS for number in range(13)]
    ids = [row["posting_identity"] for row in rows]
    selected = list(reversed([row["posting_identity"] for row in rows
                              if not row["posting_identity"].endswith(":12")]))
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(selected) + "\n")
    result, evidence = ops.explicit_pilot_ids(path, rows, ids)
    assert result == selected
    assert evidence["posting_ids"] == selected
    assert evidence["file_identity"] == ops.file_identity(path)
    assert evidence["path"] == str(path.resolve())


@pytest.mark.parametrize("change", ["count", "shape", "duplicate", "unknown", "already-paid",
                                   "balance", "not-string", "malformed", "no-eligible"])
def test_invalid_explicit_pilot_fails_before_batch_planning(change, monkeypatch, tmp_path):
    rows = [source_row(number, source) for source in ops.COUNTS for number in range(13)]
    ids = [row["posting_identity"] for row in rows]
    selected = [row["posting_identity"] for row in rows
                if not row["posting_identity"].endswith(":12")]
    eligible = ids.copy()
    if change == "count":
        selected.pop()
    elif change == "shape":
        selected = {"posting_ids": selected}
    elif change == "duplicate":
        selected[-1] = selected[0]
    elif change == "unknown":
        selected[-1] = "unknown:posting"
    elif change == "already-paid":
        eligible.remove(selected[0])
    elif change == "balance":
        selected[-1] = "source:posting:jobkorea:12"
    elif change == "not-string":
        selected[-1] = 123
    elif change == "no-eligible":
        eligible = []
    path = tmp_path / "pilot.json"
    path.write_text("[" if change == "malformed" else json.dumps(selected))
    queries = []

    def sql(_pg, expression):
        queries.append(expression)
        if not expression.startswith("onet_matching.eligible_inputs("):
            raise AssertionError("Invalid pilot mutated a batch")
        return eligible

    monkeypatch.setattr(ops, "sql_json", sql)
    monkeypatch.setattr(ops, "artifacts", lambda *args: {})
    monkeypatch.setattr(ops, "require_idle", lambda *args: None)
    monkeypatch.setattr(ops, "runtime_state", lambda *args: {
        "task": {"frozen_input_count": sum(ops.COUNTS.values()), "accounting_usd": "0"}})
    args = SimpleNamespace(stage="pilot", pilot_posting_ids_file=path)
    manifest = {"task_id": "task-1", "rows": rows,
                "settings": {"request_reserve_usd": "0.02"}}
    with pytest.raises(RuntimeError):
        ops.execute_batches(args, {"hop": "hop", "pg": "pg"}, manifest, tmp_path, {})
    assert len(queries) == 1


def test_explicit_pilot_option_is_rejected_for_full_before_any_operation(monkeypatch):
    calls = []
    monkeypatch.setattr(ops.sys, "argv", ["run_onet_matches.py", "full", "--manifest", "fake",
                                        "--pilot-posting-ids-file", "pilot.json"])
    monkeypatch.setattr(ops, "execute", lambda *args: calls.append(args))
    with pytest.raises(SystemExit) as exc:
        ops.main()
    assert exc.value.code == 2 and calls == []


def test_explicit_pilot_evidence_is_saved_before_first_batch_mutation(monkeypatch, tmp_path):
    rows = [source_row(number, source) for source in ops.COUNTS for number in range(12)]
    ids = [row["posting_identity"] for row in rows]
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(ids))
    calls = []

    def sql(_pg, expression):
        if expression.startswith("onet_matching.eligible_inputs("):
            return ids
        saved = json.loads((tmp_path / "receipt.json").read_bytes())["pilot_selection"]
        assert saved["posting_ids"] == ids
        assert saved["file_identity"] == ops.file_identity(path)
        calls.append(expression)
        raise RuntimeError("Stop fixture before native execution")

    monkeypatch.setattr(ops, "sql_json", sql)
    monkeypatch.setattr(ops, "artifacts", lambda *args: {})
    monkeypatch.setattr(ops, "require_idle", lambda *args: None)
    monkeypatch.setattr(ops, "runtime_state", lambda *args: {
        "task": {"frozen_input_count": sum(ops.COUNTS.values()), "accounting_usd": "0"}})
    args = SimpleNamespace(stage="pilot", pilot_posting_ids_file=path, batch_id="pilot-1")
    manifest = {"task_id": "task-1", "rows": rows,
                "settings": {"request_reserve_usd": "0.02"}}
    with pytest.raises(RuntimeError, match="Stop fixture"):
        ops.execute_batches(args, {"hop": "hop", "pg": "pg"}, manifest, tmp_path, {})
    assert len(calls) == 1 and calls[0].startswith("onet_matching.plan_batch(")


@pytest.mark.parametrize("task", [
    {"unknown_holds": 1, "accounting_usd": "0.01"},
    {"unknown_requests": 1, "accounted_usd": "0.01"},
    {"state": "UNKNOWN_CHARGE_HOLD", "accounting_usd": "0.01"},
    {"accounting_usd": "39.98"},
    {"accounted_usd": "40.01"},
])
def test_unknown_costs_and_all_task_budget_are_fail_closed(task):
    with pytest.raises(RuntimeError):
        ops.require_accounting({"task": task}, Decimal("0.05"))
    ops.require_accounting({"task": {"accounting_usd": "0.10", "unknown_holds": 0}},
                           Decimal("0.05"))


def test_private_immutable_files_cannot_be_overwritten(tmp_path):
    path = tmp_path / "manifest.json"
    ops.write_json(path, {"value": "한글\n$x `x`"}, immutable=True)
    assert path.stat().st_mode & 0o077 == 0
    assert ops.load_private(path)["value"] == "한글\n$x `x`"
    with pytest.raises(FileExistsError):
        ops.write_json(path, {"value": "changed"}, immutable=True)
    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="private"):
        ops.load_private(path)


def test_json_sql_preserves_metadata_as_data():
    malicious = {"title": "quote'; SELECT secret; -- $$ $onet_bad$ `x` $(x)\n한글"}
    expression = ops.json_sql(malicious)
    delimiter = expression[:expression.index("$", 1) + 1]
    assert expression.startswith(delimiter) and expression.endswith(delimiter + "::jsonb")
    assert json.loads(expression[len(delimiter):-len(delimiter + "::jsonb")]) == malicious


def test_native_invocation_restricts_workflows_params_and_marks_only_owned_process():
    command = ops.native_args("hop", "execute", {"ONET_BATCH_ID": "batch-1"}, "owned-1")
    assert "JOBTOLOGY_ONET_OPERATION=owned-1" in command
    assert "Basic" in command
    assert "setsid" in command[command.index("-c") + 1]
    assert "llm/onet/execute_matches.hwf" in " ".join(command)
    assert "https://" not in " ".join(command)
    assert "-r" in command and command[command.index("-r") + 1] == "onet-local"
    with pytest.raises(RuntimeError, match="Unsafe"):
        ops.native_args("hop", "execute", {"ONET_BATCH_ID": "x,EXECUTE=Y"}, "owned-1")


def test_actual_publish_parameters_build_the_owned_native_invocation():
    params = {"ONET_TASK_ID": "onet-metadata-20261014-request-v4",
              "NEO4J_CONNECTION": "jobtology-neo4j"}
    command = ops.native_args("hop", "publish", params, "owned-publication-1")
    assert command[command.index("-f") + 1] == (
        ops.common.PROJECT + "/llm/onet/publish_matches.hwf")
    assert command[command.index("-p") + 1] == (
        "ONET_TASK_ID=onet-metadata-20261014-request-v4,"
        "NEO4J_CONNECTION=jobtology-neo4j")
    assert "JOBTOLOGY_ONET_OPERATION=owned-publication-1" in command


@pytest.mark.parametrize("key,value", [
    ("", "value"), ("4NEO_CONNECTION", "value"), ("neo4j_CONNECTION", "value"),
    ("NEO4J-CONNECTION", "value"), ("NEO4J CONNECTION", "value"),
    ("NEO4J_CONNECTION,OTHER", "value"), ("NEO4J_CONNECTION=OTHER", "value"),
    ("NEO4J_CONNECTION\r", "value"), ("NEO4J_CONNECTION\n", "value"),
    ("NEO4J_CONNECTION", "connection,ONET_TASK_ID=other"),
    ("NEO4J_CONNECTION", "connection\rnext"),
    ("NEO4J_CONNECTION", "connection\nnext"),
])
def test_native_publish_parameter_validation_still_rejects_unsafe_keys_and_values(key, value):
    with pytest.raises(RuntimeError, match="Unsafe native parameter"):
        ops.native_args("hop", "publish", {key: value}, "owned-publication-1")


def test_cancellation_requires_pid_starttime_marker_and_owned_group(monkeypatch):
    calls = []
    monkeypatch.setattr(ops.common, "command", lambda args, *, data: calls.append((args, data)))
    ops.cancel_owned("hop", "owned-1")
    args, script = calls[0]
    assert args[-3:] == ["/tmp/jobtology-onet-owned-1.pid", "owned-1", "TERM"]
    assert b"/proc/$pid/stat" in script and b'test "$1" = "$stamp"' in script
    assert b"JOBTOLOGY_ONET_OPERATION=$marker" in script
    assert b'kill -"$signal" -- "-$pid"' in script
    assert b"pkill" not in script and b"killall" not in script
    with pytest.raises(RuntimeError):
        ops.cancel_owned("hop", "owned-1", "USR1")


def test_timeout_cancels_only_owned_native_and_retains_private_receipt(monkeypatch, tmp_path):
    class Process:
        done = False
        calls = 0

        def wait(self, *, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("docker", timeout)
            self.done = True
            return 143

        def poll(self):
            return 143 if self.done else None

    process = Process()
    monkeypatch.setattr(ops.subprocess, "Popen", lambda *args, **kwargs: process)
    times = iter([0, 0, 61, 61])
    monkeypatch.setattr(ops.time, "monotonic", lambda: next(times))
    cancelled = []
    monkeypatch.setattr(ops, "cancel_owned", lambda hop, marker: cancelled.append((hop, marker)))
    monkeypatch.setattr(ops.common, "idle_cli", lambda hop: None)
    receipt = {"status": "RUNNING", "stage": "pilot"}
    previous = os.umask(0o077)
    try:
        with pytest.raises(TimeoutError):
            ops.run_native({"hop": "hop"}, "execute", {}, tmp_path, receipt, 60)
    finally:
        os.umask(previous)
    assert len(cancelled) == 1 and cancelled[0][0] == "hop"
    assert receipt["owned_process_cancelled"] is True
    assert (tmp_path / "receipt.json").stat().st_mode & 0o077 == 0
    assert (tmp_path / "native-basic.log").stat().st_mode & 0o077 == 0
    assert receipt["log_identity"]["sha256"]


def test_deployment_qualification_binds_exact_native_bytes_and_cleanup(tmp_path):
    path = tmp_path / "receipt.json"
    hashes = {"llm/onet/install.hwf": "a" * 64}
    proof = {"status": "PASSED_ONET_MATCHING_NATIVE", "isolated": True,
             "disposable_resources_removed": True, "artifact_sha256": hashes}
    ops.write_json(path, proof)
    assert ops.qualification(path, hashes) == proof
    with pytest.raises(RuntimeError, match="exact"):
        ops.qualification(path, {"llm/onet/install.hwf": "b" * 64})
    for key in ("isolated", "disposable_resources_removed"):
        ops.write_json(path, {**proof, key: False})
        with pytest.raises(RuntimeError, match="cleanup"):
            ops.qualification(path, hashes)
    ops.write_json(path, {**proof, "status": "RUNNING"})
    with pytest.raises(RuntimeError, match="passed"):
        ops.qualification(path, hashes)


def test_remote_deployment_cannot_read_or_copy_old_matchers(monkeypatch):
    monkeypatch.setattr(ops, "runtime_artifacts", lambda: {"llm/onet/install.hwf": "a" * 64})
    calls = []
    monkeypatch.setattr(ops.common, "command", lambda *args, **kwargs: calls.append(args))
    for path in ("llm/install.hwf", "llm/onet/../request.hpl", "metadata/database/private.json"):
        with pytest.raises(RuntimeError, match="outside"):
            ops.remote_public_bytes("hop", path)
    assert calls == []


def test_database_deadline_and_errors_do_not_echo_private_inputs(monkeypatch):
    calls = []

    def timeout(args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired("docker", kwargs["timeout"])

    monkeypatch.setattr(ops.subprocess, "run", timeout)
    with pytest.raises(TimeoutError, match="Bounded") as failure:
        ops.sql("pg", "SELECT 'private source';")
    assert "private source" not in str(failure.value)
    assert calls[0][1]["timeout"] == 180
    assert calls[0][1]["input"] == b"SELECT 'private source';"
    assert "private source" not in " ".join(calls[0][0])


@pytest.mark.parametrize("batch", [
    None,
    {"execution_state": "STOPPED", "states": {"VALIDATED": 15}},
    {"execution_state": "COMPLETE", "states": {"PLANNED": 1}},
    {"execution_state": "COMPLETE", "states": {"BUDGET_BLOCKED": 1}},
    {"execution_state": "COMPLETE", "states": {"RESERVED": 1}},
    {"execution_state": "COMPLETE", "states": {"ERROR": 1}},
])
def test_full_cannot_continue_after_incomplete_native_batch(batch):
    with pytest.raises(RuntimeError):
        ops.require_batch_complete(batch)
    ops.require_batch_complete({"execution_state": "COMPLETE",
                                "states": {"VALIDATED": 31, "REJECTED": 3, "SKIPPED": 2}})


def test_disconnect_signals_enter_owned_cleanup_and_restore_handlers(monkeypatch):
    original = object()
    handlers = dict.fromkeys((ops.signal.SIGTERM, ops.signal.SIGHUP), original)

    def install(number, handler):
        previous = handlers[number]
        handlers[number] = handler
        return previous

    monkeypatch.setattr(ops.signal, "signal", install)
    with pytest.raises(InterruptedError, match="signal"), ops.termination_signals():
        handlers[ops.signal.SIGHUP](ops.signal.SIGHUP, None)
    assert all(handler is original for handler in handlers.values())


def test_balanced_full_selection_preserves_frozen_ids_and_handles_exhausted_sources():
    rows = [source_row(number, source) for source in ops.COUNTS for number in range(200)]
    ids = [row["posting_identity"] for row in rows]
    selected = ops.balanced_ids(rows, ids, 500)
    assert selected == ops.balanced_ids(list(reversed(rows)), list(reversed(ids)), 500)
    assert len(selected) == len(set(selected)) == 500
    lookup = {row["posting_identity"]: row["source_id"] for row in rows}
    assert {source: sum(lookup[posting] == source for posting in selected)
            for source in sorted(ops.COUNTS)} == {"job_alio": 167, "jobkorea": 167, "nara_job": 166}
    remaining = [posting for posting in ids if lookup[posting] != "job_alio"]
    assert len(ops.balanced_ids(rows, remaining, 500)) == 400
    assert set(ops.balanced_ids(rows, remaining, 500)) <= set(remaining)


@pytest.mark.parametrize("change", ["state", "token", "task", "database", "count", "hash",
                                    "writer"])
def test_publication_requires_exact_verified_owned_plan(change):
    state = {"guard": {"publication_id": "publication", "task_id": "task", "database_id": "db",
                       "state": "VERIFIED", "expected_count": 31, "verified_count": 31,
                       "rows_hash": "hash"}, "current_count": 31, "current_rows_hash": "hash",
             "writer_count": 0}
    ops.require_publication(state, "publication", "task", "db")
    if change == "count":
        state["current_count"] = 30
    elif change == "hash":
        state["current_rows_hash"] = "changed"
    elif change == "writer":
        state["writer_count"] = 1
    else:
        key = {"state": "state", "token": "publication_id", "task": "task_id",
               "database": "database_id"}[change]
        state["guard"][key] = "changed"
    with pytest.raises(RuntimeError):
        ops.require_publication(state, "publication", "task", "db")


def test_publication_snapshot_aggregates_count_and_ordered_hash_from_one_plan(monkeypatch):
    captured = []
    expected = {"current_count": 310, "current_rows_hash": "f" * 64}
    monkeypatch.setattr(ops, "sql_json", lambda pg, expression:
                        captured.append((pg, expression)) or expected)
    assert ops.publication_state("pg", "publication", "task") == expected
    assert captured[0][0] == "pg"
    assert captured[0][1].count("onet_matching.graph_rows(") == 1
    assert "'current_count',count(*)" in captured[0][1]
    assert "string_agg(content_hash" in captured[0][1]
    assert "ORDER BY edge_id" in captured[0][1]


@pytest.mark.parametrize("change", [None, "missing", "duplicate", "wrong-transform",
                                   "invalid-token", "changed-log", "failed-native", "wrong-stage"])
def test_native_publication_token_is_exactly_one_from_the_owned_pinned_log(tmp_path, change):
    token = "5cac284c-10c9-4624-a963-f650b6bef147"
    line = ("2026/10/14 12:38:09 - Remember exact catalogue token.0 - "
            "Set variable ONET_PUBLICATION_ID to value [" + token + "]\n")
    log = tmp_path / "native-basic.log"
    content = line
    if change == "missing":
        content = "No publication was frozen\n"
    elif change == "duplicate":
        content += line
    elif change == "wrong-transform":
        content = line.replace("Remember exact catalogue token.0", "Other transform.0")
    elif change == "invalid-token":
        content = line.replace(token, "arbitrary-or-requested-token")
    log.write_text(content)
    receipt = {"stage": "publish", "owned_process_marker": "onet-" + "a" * 32,
               "native_exit_code": 0, "log": str(log), "log_identity": ops.file_identity(log)}
    if change == "changed-log":
        log.write_text(content + "changed\n")
    elif change == "failed-native":
        receipt["native_exit_code"] = 1
    elif change == "wrong-stage":
        receipt["stage"] = "execute"
    if change is None:
        assert ops.native_publication_id(receipt) == token
    else:
        with pytest.raises(RuntimeError):
            ops.native_publication_id(receipt)


def owned_publication_fixture():
    token = "5cac284c-10c9-4624-a963-f650b6bef147"
    manifest = {"task_id": "task", "release_id": "release", "database_id": "db",
                "settings": {"model": ops.MODEL, "task_cap_usd": "40"},
                "source_export": {"sha256": "a" * 64}, "counts": {"jobkorea": 36}}
    manifest_pin = {"sha256": "b" * 64, "byte_length": 123}
    binding = {"task_id": "task", "release_id": "release", "database_id": "db",
               "catalog_hash": "c" * 64, "settings_hash": "d" * 64,
               "manifest_hash": "e" * 64, "frozen_input_count": 36,
               "settings": {**manifest["settings"], "frozen_manifest_sha256": "b" * 64,
                            "source_cohort_sha256": "a" * 64, "frozen_input_count": 36}}
    before = {"guard_ids": ["earlier"], "task_binding": binding,
              "current_count": 310, "current_rows_hash": "f" * 64,
              "observed_at": "2026-10-14T12:38:08+00:00"}
    after = {"guard_ids": ["earlier", token], "task_binding": binding,
             "current_count": 310, "current_rows_hash": "f" * 64, "writer_count": 0,
             "observed_at": "2026-10-14T12:38:15+00:00",
             "guard": {"publication_id": token, "task_id": "task", "database_id": "db",
                       "state": "VERIFIED", "expected_count": 310, "verified_count": 310,
                       "rows_hash": "f" * 64, "started_at": "2026-10-14T12:38:09+00:00",
                       "finished_at": "2026-10-14T12:38:14+00:00"}}
    return token, manifest, manifest_pin, before, after


@pytest.mark.parametrize("change", [None, "reused", "ambiguous-new", "removed-old",
                                   "missing-snapshot", "manifest-pin", "settings", "task",
                                   "input-count", "catalogue-pin", "plan-count", "plan-hash",
                                   "started-before-launch", "finished-after-launch",
                                   "missing-timezone", "observation-before-finish"])
def test_native_guard_adoption_binds_fresh_unique_manifest_plan_and_launch_window(change):
    token, manifest, pin, before, after = owned_publication_fixture()
    if change == "reused":
        before["guard_ids"].append(token)
    elif change == "ambiguous-new":
        after["guard_ids"].append("foreign-publication")
    elif change == "removed-old":
        after["guard_ids"].remove("earlier")
    elif change == "missing-snapshot":
        before.pop("guard_ids")
    elif change == "manifest-pin":
        pin["sha256"] = "0" * 64
    elif change == "settings":
        manifest["settings"]["task_cap_usd"] = "50"
    elif change == "task":
        manifest["task_id"] = "foreign-task"
    elif change == "input-count":
        manifest["counts"]["jobkorea"] = 37
    elif change == "catalogue-pin":
        after["task_binding"]["catalog_hash"] = "unknown"
    elif change == "plan-count":
        before["current_count"] = 309
    elif change == "plan-hash":
        before["current_rows_hash"] = "0" * 64
    elif change == "started-before-launch":
        after["guard"]["started_at"] = "2026-10-14T12:38:01+00:00"
    elif change == "finished-after-launch":
        after["guard"]["finished_at"] = "2026-10-14T12:38:17+00:00"
    elif change == "missing-timezone":
        after["guard"]["started_at"] = "2026-10-14T12:38:09"
    elif change == "observation-before-finish":
        after["observed_at"] = "2026-10-14T12:38:13+00:00"
    args = (before, after, token, manifest, pin, "2026-10-14T12:38:02+00:00",
            "2026-10-14T12:38:16+00:00")
    if change is None:
        ops.require_owned_publication(*args)
        # A later read-only recovery observation still binds the original native time window.
        after["observed_at"] = "2026-10-14T12:48:00+00:00"
        ops.require_owned_publication(*args)
    else:
        with pytest.raises(RuntimeError):
            ops.require_owned_publication(*args)


@pytest.mark.parametrize("stage,workflow", [
    ("install-reconciliation", "install_reconciliation.hwf"),
    ("install-route-incident", "install_route_incident.hwf"),
])
def test_additive_incident_installer_needs_no_source_manifest(monkeypatch, stage, workflow):
    captured = []
    monkeypatch.setattr(ops.sys, "argv", ["run_onet_matches.py", stage])
    monkeypatch.setattr(ops, "execute", lambda args: captured.append(args))
    ops.main()
    assert captured[0].stage == stage
    assert captured[0].manifest is None
    command = ops.native_args("hop", stage, {}, "owned-1")
    assert "llm/onet/" + workflow in " ".join(command)
    assert "ONET_BATCH_ID" not in " ".join(command)
    assert "openrouter.ai" not in " ".join(command)


def test_pinned_prompt_registry_hashes_bind_version_text_and_schema():
    schema = {"type": "object", "additionalProperties": False}
    value = {"version": "prompt-v2", "text": "exact pinned text", "schema": schema}
    digest = ops.common.digest(ops.canonical(value))
    module = SimpleNamespace(PROMPT_VERSION=value["version"], PROMPT_TEXT=value["text"],
                             SCHEMA=schema, PROMPT_HASH=digest)
    settings = {"prompt_hash": digest, "schema_sha256": ops.common.digest(ops.canonical(schema))}
    contract = ops.prompt_contract(module, settings)
    assert contract["prompt_hash"] == digest
    module.PROMPT_VERSION = "prompt-v3"
    with pytest.raises(RuntimeError, match="hash"):
        ops.prompt_contract(module, settings)
    module.PROMPT_VERSION = "prompt-v2"
    settings["schema_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="schema"):
        ops.prompt_contract(module, settings)


def test_prompt_registration_is_insert_only_atomic_and_fails_on_collision():
    contract = {"version": "prompt-v2", "text": "' $register$ quoted text",
                "schema": {"type": "object"}, "prompt_hash": "a" * 64}
    query = ops.prompt_registration_sql(contract)
    assert query.startswith("BEGIN;") and query.endswith("COMMIT;")
    assert "ON CONFLICT(version) DO NOTHING" in query
    assert "ONET_PINNED_PROMPT_VERSION_COLLISION" in query
    assert "ONET_PINNED_SCHEMA_CHANGED_OR_BASE_INSTALL_MISSING" in query
    assert "prompt_text=pinned->>'text'" in query
    assert all(command not in query for command in ("UPDATE ", "DELETE ", "TRUNCATE "))


def test_jsonb_size_expands_numbers_and_preserves_unicode_escapes():
    value = {"x": [1e-7, -0.0, True, None, "한\n"]}
    expected = '{"x": [0.0000001, 0.0, true, null, "한\\n"]}'
    assert ops.jsonb_text_bytes(value) == len(expected.encode())
    with pytest.raises(RuntimeError, match="non-finite"):
        ops.jsonb_text_bytes(float("nan"))


def test_size_bounded_chunks_are_deterministic_contiguous_and_preserve_old_boundaries():
    rows = [{"text": "한" * count} for count in (1, 2, 12, 1, 8, 2)]
    chunks = list(ops.bounded_freeze_chunks(rows, max_rows=3, max_bytes=65))
    assert chunks == list(ops.bounded_freeze_chunks(rows, max_rows=3, max_bytes=65))
    assert [row for _, chunk, _ in chunks for row in chunk] == rows
    ordinal = 1
    for start, chunk, size in chunks:
        assert start == ordinal and len(chunk) <= 3 and size <= 65
        assert size == ops.jsonb_text_bytes(chunk)
        ordinal += len(chunk)
    old = list(ops.bounded_freeze_chunks([{"v": 1}] * 1001))
    assert [(start, len(chunk)) for start, chunk, _ in old] == [(1, 500), (501, 500), (1001, 1)]


def test_oversized_row_fails_before_prompt_registration_or_any_database_write(monkeypatch):
    original = ops.bounded_freeze_chunks
    monkeypatch.setattr(ops, "bounded_freeze_chunks", lambda rows: original(rows, max_bytes=30))
    writes = []
    monkeypatch.setattr(ops, "register_prompt", lambda *args: writes.append("prompt"))
    monkeypatch.setattr(ops, "sql_json", lambda *args: writes.append("database"))
    with pytest.raises(RuntimeError, match="ordinal 2"):
        ops.prepare_inputs({"pg": "pg"}, {"rows": [{"x": "ok"}, {"x": "a" * 40}]},
                           None, {}, None)
    assert writes == []


def admission_fixture(monkeypatch):
    policy_hash = "b" * 64

    def classify(fields):
        return {"outcome": "EXCLUDE", "policy_version": "admission-v1",
                "policy_sha256": policy_hash, "reason_code": "TRAINING",
                "reason": "Original title advertises enrollment.",
                "evidence": [{"field": "title", "quote": fields["title"]}]}

    module = SimpleNamespace(ADMISSION_HASH=policy_hash, ADMISSION_VERSION="admission-v1",
                             admission_decision=classify)
    monkeypatch.setattr(ops, "frozen_module", lambda *args: module)
    monkeypatch.setattr(ops, "frozen_prompt", lambda *args: SimpleNamespace(
        admitted_fields=lambda facts: {"title": facts["title"]}))
    fields = {"title": "training enrollment"}
    manifest = {"settings": {"admission_policy_sha256": policy_hash,
                              "admission_policy_version": "admission-v1"},
                "rows": [{"source_facts": dict(fields), "source_fields": dict(fields),
                          "candidates": [], "admission_decision": classify(fields)}]}
    return manifest, module


def test_exact_pinned_admission_decision_and_empty_shortlist_are_accepted(monkeypatch):
    manifest, _ = admission_fixture(monkeypatch)
    ops.verify_frozen_admission(Path("retained-manifest.json"), manifest)


@pytest.mark.parametrize("change", ["policy-hash", "policy-version", "decision", "source-fields",
                                   "source-facts", "missing-decision", "candidates", "code"])
def test_admission_drift_fails_before_prompt_registration_or_pg_mutation(change, monkeypatch):
    manifest, module = admission_fixture(monkeypatch)
    row = manifest["rows"][0]
    if change == "policy-hash":
        manifest["settings"]["admission_policy_sha256"] = "c" * 64
    elif change == "policy-version":
        manifest["settings"]["admission_policy_version"] = "different-policy"
    elif change == "decision":
        row["admission_decision"]["evidence"][0]["quote"] = "unfrozen quote"
    elif change == "source-fields":
        row["source_fields"]["title"] = "changed title"
    elif change == "source-facts":
        row["source_fields"]["title"] = row["source_facts"]["title"] = "changed title"
    elif change == "missing-decision":
        del row["admission_decision"]
    elif change == "candidates":
        row["candidates"] = [{"occupation_code": "15-1252.00"}]
    else:
        module.ADMISSION_HASH = "c" * 64
    writes = []
    monkeypatch.setattr(ops, "register_prompt", lambda *args: writes.append("prompt"))
    monkeypatch.setattr(ops, "sql_json", lambda *args: writes.append("database"))
    with pytest.raises(RuntimeError):
        ops.prepare_inputs({"pg": "pg"}, manifest, Path("retained-manifest.json"), {}, None)
    assert writes == []


def test_legacy_manifests_without_admission_keys_keep_their_exact_contract(monkeypatch):
    manifest = {"settings": {"prompt_hash": "original"}, "rows": [source_row()]}
    original = ops.canonical(manifest)
    monkeypatch.setattr(ops, "frozen_module", lambda *args: pytest.fail(
        "Legacy admission validation must not load successor code"))
    ops.verify_frozen_admission(Path("old-manifest.json"), manifest)
    assert ops.canonical(manifest) == original


def test_freeze_retains_admission_source_facts_and_archived_code(monkeypatch, tmp_path):
    from hop.llm.onet import retrieval

    rows = [source_row(1, source) for source in ops.COUNTS]
    for row in rows:
        row["source_fields"]["title"] = "수강생 모집"
    source = tmp_path / "source.json"
    catalogue = tmp_path / "catalogue.json"
    source.write_text(json.dumps(rows, ensure_ascii=False))
    catalogue.write_text(json.dumps({"release_id": ops.RELEASE}))
    directory = tmp_path / "freeze"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(ops, "new_directory", lambda stage: directory)
    monkeypatch.setattr(ops, "check_cohort", lambda rows: dict.fromkeys(ops.COUNTS, 1))
    monkeypatch.setattr(retrieval, "CatalogueIndex", lambda catalogue: SimpleNamespace(
        shortlist=lambda fields, limit: []))
    monkeypatch.setattr(ops, "sql_json", lambda *args: pytest.fail("Local freeze accessed PG"))
    args = SimpleNamespace(source_file=source, catalogue_file=catalogue,
        source_sha256=ops.file_identity(source)["sha256"],
        catalogue_sha256=ops.file_identity(catalogue)["sha256"], release_id=ops.RELEASE,
        database_id=ops.DATABASE, task_id="local-admission-freeze", candidate_limit=24,
        max_matches=3, max_output_tokens=1024, reserve=Decimal("0.02"))
    path = ops.freeze(args)
    manifest = ops.manifest_inputs(path)
    assert path.stat().st_mode & 0o077 == 0
    assert manifest["settings"]["admission_policy_sha256"] == retrieval.ADMISSION_HASH
    assert manifest["settings"]["admission_policy_version"] == retrieval.ADMISSION_VERSION
    expected_sources = {row["posting_identity"]: row["source_fields"] for row in rows}
    for row in manifest["rows"]:
        assert row["source_facts"] == expected_sources[row["posting_identity"]]
        assert row["admission_decision"]["outcome"] == "EXCLUDE"
        assert row["candidates"] == []
    assert manifest["code_artifacts"]["code/retrieval.py"] == ops.file_identity(
        directory / "code/retrieval.py")
