"""Offline checks for the protected native-stage supervisor; no Docker/HTTP."""

from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

OPERATIONS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPERATIONS))
supervisor: Any = importlib.import_module("run_inferred_occupations")


def idle() -> dict[str, Any]:
    return {
        "pins": {"jobkorea": supervisor.JOBS, "ncs_competency": supervisor.NCS},
        "source_graphs": 2,
        "unfinished_refresh": 0,
        "loading_runs": 0,
        "retention_writers": 0,
        "maintenance": False,
        "recent_running_batches": 0,
        "recent_reserved_requests": 0,
        "inference_installed": True,
        "retrieval_v3_installed": True,
        "batch_exists": False,
        "legacy_baseline": {"source_requests": 28145, "duty_attempts": 3},
        "task_cost_scope": supervisor.TASK_COST_SCOPE,
        "task_cost": {"requests": 5, "reported_usd": "0.05", "accounted_usd": "0.05"},
        "batch": None,
    }


def test_idle_and_cumulative_budget() -> None:
    state = idle()
    supervisor.require_idle(state, supervisor.JOBS, supervisor.NCS)
    # Existing dry PLANNED batches never enter the running/reserved gate.
    assert supervisor.bounded_budget(Decimal("4.75"), Decimal("4.745"), state) == Decimal("4.695")
    assert supervisor.bounded_budget(Decimal("15"), Decimal("15"), state) == Decimal("14.95")
    assert supervisor.money("50") == Decimal("50")
    with pytest.raises(argparse.ArgumentTypeError, match=r"between 0\.001 and 50"):
        supervisor.money("50.000001")
    state["recent_reserved_requests"] = 1
    with pytest.raises(RuntimeError, match="busy"):
        supervisor.require_idle(state, supervisor.JOBS, supervisor.NCS)
    state["recent_reserved_requests"] = 0
    state["pins"]["ncs_competency"] = "different-pin"
    with pytest.raises(RuntimeError, match="pins changed"):
        supervisor.require_idle(state, supervisor.JOBS, supervisor.NCS)
    state["task_cost"]["accounted_usd"] = "4.75"
    with pytest.raises(RuntimeError, match="does not reset"):
        supervisor.bounded_budget(Decimal("0.05"), Decimal("4.75"), state)
    with pytest.raises(RuntimeError, match="Unsafe native parameter"):
        supervisor.native_args("fixture", "execute", {"POSTING_IDS": "x,API_KEY_FILE=evil"})
    assert supervisor.workflow("execute", 4) == supervisor.WORKER_WORKFLOW
    assert supervisor.workflow("execute", 1) == supervisor.WORKFLOWS["execute"]
    assert supervisor.workflow("plan", 4) == supervisor.WORKFLOWS["plan"]


def test_cli_default_task_cap_stays_small(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> None:
        captured.append(args)

    monkeypatch.setattr(supervisor, "execute", capture)
    monkeypatch.setattr(sys, "argv", ["run_inferred_occupations.py", "plan"])
    supervisor.main()
    assert captured[0].task_cap == Decimal("4.75")
    assert captured[0].max_cost == Decimal("0.05")
    assert captured[0].workers == 1
    assert captured[0].prompt_version == "ko-metadata-occupation-v1"
    assert captured[0].retrieval_revision == supervisor.RETRIEVAL_V3
    assert (
        supervisor.parameters(captured[0], "new-retrieval-fixture", Decimal("0.05"))[
            "RETRIEVAL_REVISION"
        ]
        == supervisor.RETRIEVAL_V3
    )
    assert (
        supervisor.parameters(captured[0], "v1-fixture", Decimal("0.05"))["PROMPT_VERSION"]
        == "ko-metadata-occupation-v1"
    )
    monkeypatch.setattr(sys, "argv", ["run_inferred_occupations.py", "execute", "--workers", "4"])
    supervisor.main()
    worker_params = supervisor.parameters(captured[-1], "workers-fixture", Decimal("0.05"))
    assert worker_params["REQUEST_WORKERS"] == "4"
    worker_args = supervisor.native_args("fixture", "execute", worker_params, captured[-1].workers)
    assert worker_args[worker_args.index("-f") + 1].endswith(supervisor.WORKER_WORKFLOW)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_inferred_occupations.py", "plan", "--prompt-version", "ko-metadata-occupation-v2"],
    )
    supervisor.main()
    assert (
        supervisor.parameters(captured[-1], "v2-fixture", Decimal("0.05"))["PROMPT_VERSION"]
        == "ko-metadata-occupation-v2"
    )


def test_source_rollover_cannot_reset_task_or_unknown_reservation_accounting() -> None:
    state = idle()
    state["pins"]["ncs_competency"] = "fresh-ncs"
    state["current_pin_cost"] = {"requests": 0, "accounted_usd": "0"}
    state["task_cost"] = {
        "requests": 8370,
        "reported_usd": "4.08154925",
        "accounted_usd": "4.08154925",
        "unknown_requests": 0,
    }
    assert supervisor.bounded_budget(Decimal("1"), Decimal("4.9999922"), state) == Decimal(
        "0.91844295"
    )
    assert supervisor.bounded_budget(Decimal("0.15"), Decimal("4.9999922"), state) == Decimal(
        "0.15"
    )
    # A historical unknown or still-reserved request consumes its conservative hold.
    state["task_cost"]["reported_usd"] = "4.99"
    state["task_cost"]["accounted_usd"] = "5.01"
    state["task_cost"]["unknown_requests"] = 1
    with pytest.raises(RuntimeError, match="cap exhausted"):
        supervisor.bounded_budget(Decimal("0.15"), Decimal("4.9999922"), state)
    del state["task_cost_scope"]
    with pytest.raises(RuntimeError, match="all metadata batches"):
        supervisor.bounded_budget(Decimal("0.15"), Decimal("4.9999922"), state)


def test_db_accounting_query_is_global_and_keeps_current_pin_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def capture_sql(_: str, query: str) -> str:
        captured.append(query)
        return "{}"

    monkeypatch.setattr(supervisor.deployment, "sql", capture_sql)
    supervisor.db_state("fixture", "fresh-jobs", "fresh-ncs")
    query = captured[0]
    accounting = query.split("WITH metadata_accounting AS MATERIALIZED (", 1)[1].split(
        ")\nSELECT", 1
    )[0]
    assert "metadata_scope'='NCS_OCCUPATION_INFERENCE_V1'" in accounting
    assert "fresh-jobs" not in accounting and "fresh-ncs" not in accounting
    assert "prompt_version" not in accounting
    assert "'task_cost_scope','ALL_METADATA_INFERENCE_BATCHES_V1'" in query
    assert "FROM metadata_accounting a)," in query
    assert "FROM metadata_accounting a WHERE a.job_run_id='fresh-jobs'" in query
    assert "a.ncs_run_id='fresh-ncs'" in query
    assert "enrichment.accounted_cost(a.state,a.cost_usd,a.reserved_usd)" in query
    assert "BEGIN READ ONLY" in query and "statement_timeout='30s'" in query


def test_multimatch_requires_explicit_version_and_bounded_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[argparse.Namespace] = []
    monkeypatch.setattr(supervisor, "execute", captured.append)
    for version, expected_cap, expected_tokens in (
        ("ko-metadata-occupation-v1", "1", "768"),
        ("ko-metadata-occupation-v2", "1", "768"),
        ("ko-metadata-occupation-v3", "3", "1536"),
    ):
        monkeypatch.setattr(
            sys, "argv", ["run_inferred_occupations.py", "plan", "--prompt-version", version]
        )
        supervisor.main()
        params = supervisor.parameters(captured[-1], "immutable-fixture", Decimal("0.05"))
        assert (
            params["MAX_MATCHES"] == expected_cap and params["MAX_OUTPUT_TOKENS"] == expected_tokens
        )
        assert params["EXECUTE_REQUESTS"] == "N" and params["REQUEST_RESERVE_USD"] == "0.005"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_inferred_occupations.py",
            "plan",
            "--prompt-version",
            "ko-metadata-occupation-v3",
            "--max-matches",
            "2",
            "--max-output-tokens",
            "2048",
        ],
    )
    supervisor.main()
    params = supervisor.parameters(captured[-1], "explicit-fixture", Decimal("0.05"))
    assert params["MAX_MATCHES"] == "2" and params["MAX_OUTPUT_TOKENS"] == "2048"
    for args in (
        ["--max-matches", "3"],
        ["--prompt-version", "ko-metadata-occupation-v3", "--max-matches", "4"],
        ["--max-output-tokens", "2049"],
    ):
        monkeypatch.setattr(sys, "argv", ["run_inferred_occupations.py", "plan", *args])
        with pytest.raises(SystemExit):
            supervisor.main()
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_inferred_occupations.py", "plan", "--prompt-version", "arbitrary-version"],
    )
    with pytest.raises(SystemExit):
        supervisor.main()
    monkeypatch.setattr(sys, "argv", ["run_inferred_occupations.py", "execute", "--workers", "9"])
    with pytest.raises(SystemExit):
        supervisor.main()


def test_native_stage_holds_lock_and_protects_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = idle()
    after = deepcopy(before)
    after["batch"] = {"batch_id": "pilot-fixture", "state": "PARTIAL"}
    after["task_cost"]["accounted_usd"] = "0.0503"
    states = iter([before, after])
    monkeypatch.setattr(supervisor.common, "STATE", tmp_path)
    monkeypatch.setattr(
        supervisor.common, "containers", lambda: {"hop": "fixture", "pg": "fixture"}
    )

    def fake_idle(_: str) -> None:
        pass

    def fake_state(*_: Any) -> dict[str, Any]:
        return next(states)

    def fake_artifacts(*_: Any) -> dict[str, str]:
        return {"native-artifact": "bytes-hash"}

    monkeypatch.setattr(supervisor.common, "idle_cli", fake_idle)
    monkeypatch.setattr(supervisor, "db_state", fake_state)
    monkeypatch.setattr(supervisor, "artifacts", fake_artifacts)
    invocations: list[list[str]] = []

    class NativeFixture:
        def __init__(self, argv: list[str], *, stdout: Any, stderr: Any) -> None:
            assert stderr is supervisor.subprocess.STDOUT
            invocations.append(argv)
            with (tmp_path / "refresh.lock").open("a") as competing, pytest.raises(BlockingIOError):
                fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stdout.write(b"Native fixture Basic output\n")

        def wait(self, *, timeout: int) -> int:
            assert timeout == 30
            return 0

    monkeypatch.setattr(supervisor.subprocess, "Popen", NativeFixture)
    args = argparse.Namespace(
        stage="execute",
        jobs=supervisor.JOBS,
        ncs=supervisor.NCS,
        batch_id="pilot-fixture",
        limit=5,
        posting_ids="p1|p2",
        max_requests=5,
        max_cost=Decimal("4.75"),
        task_cap=Decimal("4.745"),
        reserve=Decimal("0.005"),
        include_unreviewed=False,
        workers=1,
        prompt_version="ko-metadata-occupation-v1",
        retrieval_revision=supervisor.RETRIEVAL_V3,
    )
    supervisor.execute(args)
    receipt_path = next((tmp_path / "inferred-occupations").glob("*/receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert Path(receipt["log"]).stat().st_mode & 0o777 == 0o600
    assert receipt["status"] == "COMPLETE"
    assert receipt["after"]["batch"]["state"] == "PARTIAL"
    assert receipt["parameters"]["MAX_COST_USD"] == "4.695"
    assert receipt["parameters"]["EXECUTE_REQUESTS"] == "Y"
    assert receipt["log_sha256"] and receipt["finished_at"]
    assert len(invocations) == 1 and "-l" in invocations[0] and "Basic" in invocations[0]
    assert "API_KEY_FILE" not in " ".join(invocations[0])
    assert "Native fixture Basic output" not in capsys.readouterr().out
    # The scheduler can reacquire only after the native stage and receipt finish.
    with (tmp_path / "refresh.lock").open("a") as scheduler:
        fcntl.flock(scheduler, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_selected_prompt_dependencies_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[str] = []

    def deployed_bytes(_: str, relative: str) -> bytes:
        reads.append(relative)
        return (supervisor.common.ROOT / relative).read_bytes()

    monkeypatch.setattr(supervisor.deployment, "remote_bytes", deployed_bytes)
    for version in supervisor.PROMPT_VERSIONS:
        hashes = supervisor.artifacts("fixture", "execute", 4, version)
        assert "llm/sql/033_metadata_occupation_roles.sql" in hashes
        assert "llm/sql/034_metadata_occupation_pm.sql" in hashes
        assert "llm/prompts/categorize-" + version + ".txt" in hashes
        assert "llm/prompts/categorize-" + version + ".schema.json" in hashes
    assert reads
    with pytest.raises(RuntimeError, match="Unsupported immutable"):
        supervisor.artifacts("fixture", "execute", 4, "arbitrary-version")

    def drift(_: str, relative: str) -> bytes:
        if relative == "llm/prompts/categorize-ko-metadata-occupation-v2.txt":
            return b"stale deployed prompt"
        return (supervisor.common.ROOT / relative).read_bytes()

    monkeypatch.setattr(supervisor.deployment, "remote_bytes", drift)
    with pytest.raises(RuntimeError, match="Deploy matching native artifact"):
        supervisor.artifacts("fixture", "execute", 4, "ko-metadata-occupation-v2")


def test_retrieval_selection_preserves_legacy_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> None:
        captured.append(args)

    monkeypatch.setattr(supervisor, "execute", capture)
    monkeypatch.setattr(
        sys, "argv", ["run_inferred_occupations.py", "plan", "--retrieval-revision", "legacy"]
    )
    supervisor.main()
    params = supervisor.parameters(captured[-1], "legacy-fixture", Decimal("0.05"))
    assert params["RETRIEVAL_REVISION"] == ""
    assert params["EXECUTE_REQUESTS"] == "N"
    assert params["PROMPT_VERSION"] == "ko-metadata-occupation-v1"
    assert params["CATEGORIZE_MODEL"] == "openai/gpt-5.6-luna"
    assert params["PROVIDER_ONLY"] == "openai"
    assert "API_KEY_FILE" not in params
    monkeypatch.setattr(
        sys, "argv", ["run_inferred_occupations.py", "plan", "--retrieval-revision", "unknown"]
    )
    with pytest.raises(SystemExit):
        supervisor.main()
    with pytest.raises(RuntimeError, match="Unsupported metadata retrieval"):
        supervisor.artifacts("fixture", "plan", 1, "ko-metadata-occupation-v2", "unknown")


def test_existing_batches_and_missing_v3_fail_before_artifacts_or_native(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor.common, "STATE", tmp_path)
    monkeypatch.setattr(
        supervisor.common, "containers", lambda: {"hop": "fixture", "pg": "fixture"}
    )

    def fake_idle(_: str) -> None:
        pass

    monkeypatch.setattr(supervisor.common, "idle_cli", fake_idle)
    state = idle()

    def fake_state(*_: Any) -> dict[str, Any]:
        return state

    monkeypatch.setattr(supervisor, "db_state", fake_state)
    calls: list[str] = []

    def fake_artifacts(*_: Any) -> dict[str, str]:
        calls.append("artifacts")
        return {}

    monkeypatch.setattr(supervisor, "artifacts", fake_artifacts)
    args = argparse.Namespace(
        stage="plan",
        jobs=supervisor.JOBS,
        ncs=supervisor.NCS,
        batch_id="old-batch",
        limit=5,
        posting_ids="",
        max_requests=5,
        max_cost=Decimal("0.05"),
        task_cap=Decimal("4.75"),
        reserve=Decimal("0.005"),
        include_unreviewed=False,
        workers=1,
        prompt_version="ko-metadata-occupation-v2",
        retrieval_revision=supervisor.RETRIEVAL_V3,
    )
    state["batch_exists"] = True
    with pytest.raises(RuntimeError, match="fresh batch ID"):
        supervisor.execute(args)
    assert calls == [] and not (tmp_path / "inferred-occupations").exists()
    state["batch_exists"] = False
    state["retrieval_v3_installed"] = False
    with pytest.raises(RuntimeError, match="Install corrected metadata retrieval SQL"):
        supervisor.execute(args)
    assert calls == [] and not (tmp_path / "inferred-occupations").exists()
