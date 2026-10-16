# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Exercise posting date runtime gates without source, paid or production calls."""

import argparse
import fcntl
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def operations(monkeypatch: pytest.MonkeyPatch) -> Any:
    directory = Path(__file__).resolve().parents[2] / "hop/operations"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "posting_dates_runtime_test", directory / "backfill_posting_dates.py"
    )
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_confirmed_kst_timestamp_is_an_explicit_instant(operations: Any) -> None:
    assert operations.timestamp("2026-10-08T02:48:14+09:00") == "2026-10-07T17:48:14+00:00"
    with pytest.raises(argparse.ArgumentTypeError, match="offset"):
        operations.timestamp("2026-10-08T02:48:14")
    with pytest.raises(ValueError, match="exact"):
        operations.exact_identity("LATEST")
    with pytest.raises(ValueError, match="exact"):
        operations.exact_identity("posting'; DELETE")


def test_scope_uses_every_checkpointed_ready_posting_run(
    operations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    queries: list[str] = []
    expected = {
        "job_run": {"run_id": "jobs", "state": "READY"},
        "runs": ["historical", "jobs"],
        "identities": ["source:posting:jobs:a"],
        "source_counts": {"jobkorea": 1},
    }

    def sql(_: str, query: str) -> str:
        queries.append(query)
        return json.dumps(expected)

    monkeypatch.setattr(operations.deployment, "sql", sql)
    assert operations.scope("pg", "jobs") == expected
    assert "JOIN ingestion.graph_export" in queries[0]
    assert "u.state='READY'" in queries[0]
    assert "latest_ready_run" not in queries[0]
    assert "ingestion.jobkorea_import i" in queries[0]
    expected["runs"] = ["historical"]
    with pytest.raises(RuntimeError, match="checkpoint"):
        operations.scope("pg", "jobs")


def test_existing_evidence_is_preserved_while_new_evidence_appends(operations: Any) -> None:
    before = {name: ['{"id":"old"}'] for name in operations.LEDGERS}
    after = {name: [*before[name], '{"id":"new"}'] for name in operations.LEDGERS}
    operations.require_append_only(before, after)
    after[operations.LEDGERS[0]][0] = '{"id":"old","changed":true}'
    with pytest.raises(RuntimeError, match="evidence changed"):
        operations.require_append_only(before, after)


def test_frozen_source_and_accounting_fingerprints_are_never_excluded(
    operations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {
        name: {"digest": "exact"}
        for name in (
            "ingestion.record",
            "ingestion.jobkorea_import",
            "enrichment.input_bundle",
            "enrichment.attempt",
            *operations.LEDGERS,
        )
    }
    monkeypatch.setattr(operations.deployment, "full_preservation_state", lambda _: dict(before))
    assert operations.preservation("pg") == {
        name: value for name, value in before.items() if name not in operations.LEDGERS
    }


def test_existing_function_and_trigger_changes_fail_the_schema_proof(operations: Any) -> None:
    before = {
        "functions": {"enrichment.existing(text)": "exact"},
        "triggers": {"ingestion.record:guard": "exact"},
    }
    after = {
        "functions": {**before["functions"], "ingestion.new(text)": "additive"},
        "triggers": dict(before["triggers"]),
    }
    operations.require_schema_preserved(before, after)
    after["triggers"]["ingestion.record:guard"] = "changed"
    with pytest.raises(RuntimeError, match="schema changed"):
        operations.require_schema_preserved(before, after)


def test_snapshot_preserves_ids_labels_and_every_attached_edge(operations: Any) -> None:
    query = operations.snapshot_query(["source:posting:jobkorea:abc"], True)
    assert "elementId(j)" in query
    assert "labels(j)" in query
    assert "elementId(r)" in query
    assert "elementId(startNode(r))" in query and "elementId(endNode(r))" in query
    assert "valueType(v)" in query and "reduce(s='',x IN v" in query
    assert "MATCH (j:entity:jobPosting {id:posting_id})-[r]-(other)" in query
    assert "TOTAL_NODES:" in query and "TOTAL_RELS:" in query
    assert "SET " not in query and "MERGE " not in query
    for name in operations.DATE_PROPERTIES:
        assert name in query
    assert "UNWIND [k IN keys(r) WHERE NOT k IN []]" in query


def test_native_snapshot_has_only_readonly_graph_output_and_private_csv(
    operations: Any, tmp_path: Path
) -> None:
    path = tmp_path / "snapshot.hpl"
    operations.build_snapshot(path, "RETURN 'fixture' AS signature", "/tmp/fixture")
    root = ET.parse(path).getroot()
    transforms = root.findall("transform")
    assert [t.findtext("type") for t in transforms] == [
        "GetVariable",
        "Neo4jCypherOutput",
        "TextFileOutput",
    ]
    assert transforms[1].findtext("read_only") == "Y"
    assert transforms[1].findtext("connection") == "jobtology-neo4j"
    assert transforms[2].findtext("file/name") == "/tmp/fixture"
    assert transforms[2].findtext("enclosure") == '"'
    assert transforms[2].findtext("enclosure_fix_disabled") == "N"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("native_fails", [False, True])
def test_private_temporary_pipeline_is_readable_by_production_nonroot_user(
    operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_fails: bool
) -> None:
    path = tmp_path / "snapshot.hpl"
    path.write_text("private pipeline")
    path.chmod(0o600)
    copied: dict[str, Any] = {}

    def command(args: list[str]) -> bytes:
        if args[:2] == ["docker", "cp"]:
            copied.update(owner="0:0", mode=path.stat().st_mode & 0o777, path=args[-1][4:])
        elif args[5] == "chown":
            copied["owner"] = args[6]
        elif args[5] == "chmod":
            copied["mode"] = int(args[6], 8)
        elif args[5] == "rm":
            copied["removed"] = True
        else:
            raise AssertionError("Unexpected temporary pipeline command")
        return b""

    def native(hop: str, remote: str, directory: Path, label: str) -> Path:
        assert hop == "hop" and directory == tmp_path and label == "snapshot"
        # A root-owned 0600 copy is unreadable to the actual deployed uid 501.
        assert copied["owner"] == "501:501" and copied["mode"] == 0o600
        assert remote == copied["path"]
        if native_fails:
            raise RuntimeError("native failed")
        return directory / "snapshot.log"

    monkeypatch.setattr(operations.common, "command", command)
    monkeypatch.setattr(operations, "native", native)
    if native_fails:
        with pytest.raises(RuntimeError, match="native failed"):
            operations.temporary_native("hop", path, tmp_path, "snapshot")
    else:
        assert operations.temporary_native("hop", path, tmp_path, "snapshot") == (
            tmp_path / "snapshot.log"
        )
    assert copied["removed"]


def test_native_creates_private_logs_and_csv_under_private_umask(
    operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Process:
        def wait(self, timeout: int) -> int:
            assert timeout == 30
            return 0

    def popen(args: list[str], stdout: Any, stderr: Any) -> Process:
        assert stdout.name >= 0
        assert (tmp_path / "snapshot.log").stat().st_mode & 0o777 == 0o600
        assert args[args.index("bash") + 1 : args.index("bash") + 4] == [
            "-c",
            'umask 077; exec bash hop-run.sh "$@"',
            "--",
        ]
        return Process()

    monkeypatch.setattr(operations.subprocess, "Popen", popen)
    assert operations.native("hop", "/tmp/private.hpl", tmp_path, "snapshot") == (
        tmp_path / "snapshot.log"
    )


def test_registration_quotes_input_and_reaches_only_the_supplemental_function(
    operations: Any, tmp_path: Path
) -> None:
    evidence = {
        "job_run": "jobs",
        "file_sha256": "a" * 64,
        "scraped_at": "2026-10-07T17:48:14+00:00",
        "evidence_source": "USER_REPORTED",
        "evidence_reference": "report'quoted",
        "reported_timezone": "Asia/Seoul",
    }
    path = tmp_path / "register.hwf"
    operations.build_registration(path, evidence)
    root = ET.parse(path).getroot()
    actions = root.findall("./actions/action")
    assert [a.findtext("type") for a in actions] == ["SPECIAL", "SQL"]
    assert actions[1].findtext("sqlfromfile") == "N"
    assert actions[1].findtext("useVariableSubstitution") == "N"
    sql = actions[1].findtext("sql")
    assert sql is not None and sql.startswith("SELECT ingestion.register_jobkorea_collection_time(")
    assert "report''quoted" in sql and "UPDATE " not in sql


@pytest.fixture
def runtime(operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(operations.common, "STATE", state)
    containers = {"hop": "hop-test", "pg": "pg-test"}
    monkeypatch.setattr(operations.common, "containers", lambda: containers)
    monkeypatch.setattr(operations.common, "idle_cli", lambda _: None)
    monkeypatch.setattr(operations, "require_idle", lambda _: None)
    source_scope = {
        "job_run": {
            "run_id": "jobs",
            "state": "READY",
            "file_sha256": "a" * 64,
            "imported_at": "2026-10-08T00:00:00+00:00",
        },
        "runs": ["historical", "jobs"],
        "identities": ["source:posting:jobs:a"],
        "source_counts": {"jobkorea": 1},
    }
    protected = {"enrichment.attempt": {"count": 8370, "digest": "exact"}}
    graph = {"posting_nodes": 1, "posting_payload_sha256": "exact", "incident_edges": 2}
    monkeypatch.setattr(operations, "scope", lambda *_: source_scope)
    monkeypatch.setattr(operations, "preservation", lambda _: protected)
    monkeypatch.setattr(
        operations, "schema_preservation", lambda _: {"functions": {}, "triggers": {}}
    )
    monkeypatch.setattr(
        operations, "ledger_rows", lambda _: {name: [] for name in operations.LEDGERS}
    )
    monkeypatch.setattr(operations, "artifacts", lambda _: {"sql": "reviewed"})
    monkeypatch.setattr(operations, "graph_snapshot", lambda *_: graph)
    calls: list[str] = []

    def backup(_: str, __: Path) -> dict[str, str]:
        calls.append("backup")
        return {"sha256": "validated", "format": "POSTGRES_CUSTOM_FULL"}

    def native(
        _: str, path: str, __: Path, label: str, params: dict[str, str] | None = None
    ) -> Path:
        calls.append(label + ":" + (params or {}).get("RUN_ID", ""))
        assert "full.hwf" not in path and "llm" not in path
        return tmp_path / label

    monkeypatch.setattr(operations.deployment, "backup_database", backup)
    monkeypatch.setattr(operations, "native", native)
    monkeypatch.setattr(operations, "temporary_native", lambda *_: calls.append("register"))
    plan_args = argparse.Namespace(
        mode="plan",
        manifest=None,
        job_run="jobs",
        scraped_at="2026-10-07T17:48:14+00:00",
        evidence_reference="user-report",
        reported_timezone="Asia/Seoul",
    )
    manifest = operations.execute(plan_args)
    args = argparse.Namespace(mode="apply", manifest=manifest, job_run=None, scraped_at=None)
    return operations, args, calls, protected, graph, source_scope


def test_stale_plan_blocks_backup_and_writes(runtime: tuple[Any, ...]) -> None:
    operations, args, calls, *_ = runtime
    manifest = json.loads(args.manifest.read_bytes())
    manifest["graph"]["posting_payload_sha256"] = "changed"
    args.manifest.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="plan changed: graph"):
        operations.execute(args)
    assert calls == []


def test_verified_apply_preserves_history_and_runs_only_date_workflows(
    runtime: tuple[Any, ...],
) -> None:
    operations, args, calls, *_ = runtime
    path = operations.execute(args)
    receipt = json.loads(path.read_bytes())
    assert receipt["status"] == "VERIFIED"
    assert calls == ["backup", "install:", "register", "update-1:historical", "update-2:jobs"]
    assert receipt["graph_after"] == receipt["graph_before"]
    assert receipt["protected_tables_after"] == receipt["protected_tables_before"]
    assert receipt["source_requests"] == receipt["paid_calls"] == 0


def test_backup_failure_prevents_native_date_writes(
    runtime: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    operations, args, calls, *_ = runtime

    def failure(*_: Any) -> Any:
        raise RuntimeError("backup failed")

    monkeypatch.setattr(operations.deployment, "backup_database", failure)
    with pytest.raises(RuntimeError, match="inspect protected receipt"):
        operations.execute(args)
    assert calls == []


def test_accounting_change_fails_final_proof(
    runtime: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    operations, args, calls, protected, *_ = runtime
    original = operations.native

    def mutate(*inputs: Any, **keywords: Any) -> Any:
        result = original(*inputs, **keywords)
        if inputs[3] == "update-2":
            protected["enrichment.attempt"]["digest"] = "unexpected"
        return result

    # Return copies so the captured before-state cannot mutate with the fixture.
    monkeypatch.setattr(operations, "preservation", lambda _: json.loads(json.dumps(protected)))
    monkeypatch.setattr(operations, "native", mutate)
    with pytest.raises(RuntimeError, match="inspect protected receipt"):
        operations.execute(args)
    assert calls[-1] == "update-2:jobs"
    receipt = json.loads(
        next(operations.common.STATE.glob("posting-dates-apply-*/receipt.json")).read_bytes()
    )
    assert receipt["status"] == "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"


def test_atomic_deploy_orders_native_install_after_files_and_restores_entrypoint_on_failure(
    operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = {"hop": "hop", "pg": "pg"}
    protected = {"enrichment.attempt": {"digest": "exact"}}
    monkeypatch.setattr(operations, "preservation", lambda _: protected)
    monkeypatch.setattr(
        operations, "schema_preservation", lambda _: {"functions": {}, "triggers": {}}
    )
    monkeypatch.setattr(operations, "require_idle", lambda _: None)
    monkeypatch.setattr(operations.common, "db_state", lambda _: {"catalog_context": "approved"})
    monkeypatch.setattr(operations.deployment, "remote_bytes", lambda *_: b"old source graph")
    monkeypatch.setattr(operations, "artifacts", lambda _: {"sql": "reviewed"})
    calls: list[str] = []
    monkeypatch.setattr(
        operations.deployment,
        "apply",
        lambda *_: calls.append("deploy") or tmp_path / "deploy.json",
    )

    def failure(*_: Any) -> Any:
        calls.append("native-install")
        raise RuntimeError("native failed")

    monkeypatch.setattr(operations, "native", failure)
    monkeypatch.setattr(operations, "restore_snapshot_workflow", lambda *_: calls.append("restore"))
    with pytest.raises(RuntimeError, match="inspect protected receipt"):
        operations.deploy_install(tmp_path / "manifest.json", runtime, tmp_path)
    assert calls == ["deploy", "native-install", "restore"]
    assert json.loads((tmp_path / "receipt.json").read_bytes())["scheduler_entry_point_restored"]


def test_deploy_install_holds_scheduler_lock_for_both_stages(
    runtime: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    operations, args, *_ = runtime
    args.mode = "deploy-install"

    def locked_install(_: Path, __: dict[str, str], directory: Path) -> Path:
        with (
            (operations.common.STATE / "refresh.lock").open("a") as competing,
            pytest.raises(BlockingIOError),
        ):
            fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return directory / "receipt.json"

    monkeypatch.setattr(operations, "deploy_install", locked_install)
    operations.execute(args)
    with (operations.common.STATE / "refresh.lock").open("a") as released:
        fcntl.flock(released, fcntl.LOCK_EX | fcntl.LOCK_NB)
