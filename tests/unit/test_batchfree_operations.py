"""Exercise operator preservation/refusal/recovery without production writes."""

import hashlib
import importlib.util
import json
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def operations(monkeypatch: pytest.MonkeyPatch) -> Any:
    directory = Path(__file__).resolve().parents[2] / "hop/operations"
    monkeypatch.syspath_prepend(str(directory))  # type: ignore[reportUnknownMemberType]
    spec = importlib.util.spec_from_file_location(
        "batchfree_operations_test", directory / "migrate_batchfree_graph.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def constant(value: Any) -> Callable[..., Any]:
    def stub(*args: Any, **kwargs: Any) -> Any:
        return value

    return stub


def forbidden(message: str) -> Callable[..., Any]:
    def stub(*args: Any, **kwargs: Any) -> Any:
        pytest.fail(message)

    return stub


def frame(*items: str) -> str:
    return "".join(str(len(x)) + ":" + x for x in items)


def prop(**values: tuple[str, str]) -> str:
    return "".join(frame(name, *value) for name, value in sorted(values.items()))


def snapshot(path: Path, rows: list[tuple[str, str]]) -> Path:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,PRIMARY KEY(kind,eid))")
    for kind, value in rows:
        colon = value.index(":")
        eid = value[colon + 1 : colon + 1 + int(value[:colon])]
        db.execute("INSERT INTO snapshot VALUES(?,?,?)", (kind, eid, value))
    db.commit()
    db.close()
    return path


def fixtures() -> list[tuple[str, str]]:
    return [
        (
            "NODE",
            frame(
                "b",
                frame("ingestionBatch"),
                prop(id=("STRING NOT NULL", "run"), source_id=("STRING NOT NULL", "jobkorea")),
            ),
        ),
        (
            "NODE",
            frame(
                "r",
                frame("ingestionRecord"),
                prop(
                    id=("STRING NOT NULL", "record"),
                    facts_json=("STRING NOT NULL", '{"text":"서울\\nquote\\""}'),
                ),
            ),
        ),
        (
            "NODE",
            frame(
                "j",
                frame("entity", "jobPosting"),
                prop(
                    id=("STRING NOT NULL", "posting"),
                    dates=("LIST<DATE NOT NULL> NOT NULL", frame("2026-10-08", "2026-10-11")),
                    name=("STRING NOT NULL", '서울\n"자료"'),
                ),
            ),
        ),
        (
            "NODE",
            frame("o", frame("entity", "occupation"), prop(id=("STRING NOT NULL", "occupation"))),
        ),
        ("REL", frame("h", "b", "r", "HAS_RECORD", "")),
        ("REL", frame("f", "r", "j", "REFERS_TO", prop(field=("STRING NOT NULL", "posting_id")))),
        (
            "REL",
            frame(
                "n", "j", "o", "RELATED_TO_NCS", prop(review_status=("STRING NOT NULL", "REVIEWED"))
            ),
        ),
    ]


def test_unicode_newline_and_quote_framing(operations: Any) -> None:
    value = frame('서울\n"quote"', "", "🙂")
    assert operations.unpack(value) == ['서울\n"quote"', "", "🙂"]
    for broken in ("2:a", "x:a", "3abc", "-1:"):
        with pytest.raises(RuntimeError):
            operations.unpack(broken)


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("STRING NOT NULL", '서울\n"quote"', '"서울\\n\\"quote\\""'),
        ("DATE NOT NULL", "2026-10-08", 'date("2026-10-08")'),
        (
            "ZONED DATETIME NOT NULL",
            "2026-10-08T02:48:14+09:00",
            'datetime("2026-10-08T02:48:14+09:00")',
        ),
        ("LIST<INTEGER NOT NULL> NOT NULL", frame("-4", "7"), "[-4,7]"),
        ("BOOLEAN NOT NULL", "false", "false"),
    ],
)
def test_recovery_retains_scalar_and_list_types(
    operations: Any, kind: str, value: str, expected: str
) -> None:
    assert operations.property_literal(kind, value) == expected


def test_unsupported_restore_type_fails_before_deletion(operations: Any) -> None:
    with pytest.raises(RuntimeError, match="restored safely"):
        operations.property_literal("POINT NOT NULL", "point(1,2)")


def test_business_values_and_ncs_edges_survive_scaffold_removal(
    operations: Any, tmp_path: Path
) -> None:
    before = snapshot(tmp_path / "before.sqlite", fixtures())
    remaining = [
        x
        for x in fixtures()
        if (x[0] == "NODE" and operations.unpack(x[1])[0] in ("j", "o"))
        or (x[0] == "REL" and operations.unpack(x[1])[0] == "n")
    ]
    after = snapshot(tmp_path / "after.sqlite", remaining)
    assert operations.require_business_preserved(before, after) == {
        "business_nodes": 2,
        "business_edges": 1,
    }
    queries = list(operations.recovery_queries(before))
    assert len(queries) == 4
    assert "MERGE (n:ingestionBatch" in queries[0]
    assert any('elementId(b)="j"' in q for q in queries)
    assert all("DELETE" not in q for q in queries)


def test_business_date_type_change_is_rejected(operations: Any, tmp_path: Path) -> None:
    before = snapshot(tmp_path / "before.sqlite", fixtures())
    after = snapshot(
        tmp_path / "after.sqlite",
        [(k, x.replace("LIST<DATE NOT NULL>", "LIST<STRING NOT NULL>")) for k, x in fixtures()],
    )
    # Changing a framed type also changes its length, so malformed evidence is rejected.
    with pytest.raises(RuntimeError):
        operations.require_business_preserved(before, after)


@pytest.mark.parametrize("label", ["HopMigrationRecord", "archivedRecord"])
def test_unexpected_graph_history_is_not_deleted(
    operations: Any, tmp_path: Path, label: str
) -> None:
    path = snapshot(tmp_path / "graph.sqlite", [("NODE", frame("x", frame(label), ""))])
    with pytest.raises(RuntimeError, match="Unexpected"):
        operations.scaffold_nodes(path)


def test_deletion_allowlists_labels_edges_and_transaction_bound(operations: Any) -> None:
    query = operations.deletion_query(["r"])
    assert "DETACH" not in query and "archivedRecord" not in query
    assert "size(labels(n))=1" in query and "size(nodes)=1" in query
    assert "HAS_RECORD" in query and "REFERS_TO" in query and "BLOCKED" in query
    with pytest.raises(ValueError):
        operations.deletion_query(["r"] * (operations.DELETE_SIZE + 1))


def test_native_grid_uses_one_query_batch_per_transaction(operations: Any, tmp_path: Path) -> None:
    path = tmp_path / "grid.hpl"
    operations.dates.build_snapshot(path, "RETURN $offset AS signature", "/tmp/fixture")
    operations.configure_grid(path, "offset", ["0", "5000"], "Integer")
    root = ET.parse(path).getroot()
    grid = next(t for t in root.findall("transform") if t.findtext("type") == "DataGrid")
    assert [x.findtext("item") for x in grid.findall("data/line")] == ["0", "5000"]
    neo = next(t for t in root.findall("transform") if t.findtext("type") == "Neo4jCypherOutput")
    assert (
        neo.findtext("batch_size") == "1" and neo.findtext("mappings/mapping/parameter") == "offset"
    )


def test_frozen_history_and_date_ledgers_are_protected(
    operations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {
        name: {"count": 1, "digest": "exact"}
        for name in (
            *operations.NEW_LEDGERS,
            "enrichment.attempt",
            "enrichment.input_bundle",
            "ingestion.record",
            "ingestion.posting_ingestion_observation",
            "ingestion.jobkorea_collection_time_evidence",
        )
    }
    monkeypatch.setattr(operations.deployment, "full_preservation_state", constant(state))
    assert set(operations.preservation("pg")) == set(state) - operations.NEW_LEDGERS


def test_schema_whitelist_includes_exact_v1_function_names(operations: Any) -> None:
    before = {
        "functions": {
            "ingestion.record_graph_export_v1(text)": "old",
            "enrichment.reserve(text)": "frozen",
        },
        "triggers": {},
    }
    after = {
        "functions": {
            "ingestion.record_graph_export_v1(text)": "new",
            "enrichment.reserve(text)": "frozen",
        },
        "triggers": {},
    }
    operations.require_schema(before, after)
    after["functions"]["enrichment.reserve(text)"] = "changed"
    with pytest.raises(RuntimeError, match="Unexpected"):
        operations.require_schema(before, after)


def test_readonly_root_preflight_status_is_accepted(
    operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = {"hop": "hop", "pg": "pg"}
    schema: dict[str, Any] = {"functions": {}, "triggers": {}}
    prior: dict[str, Any] = {
        "status": "VERIFIED_READ_ONLY_PREFLIGHT",
        "runtime": runtime,
        "graph": {"path": "/protected/snapshot"},
        "backing": {"runs": ["source-run"]},
        "protected_tables": {"enrichment.attempt": "frozen"},
        "schema": schema,
    }
    source = tmp_path / "preflight.json"
    source.write_text(json.dumps(prior))
    monkeypatch.setattr(operations, "validate_archive", constant(Path("/protected/snapshot")))
    monkeypatch.setattr(operations, "preservation", constant(prior["protected_tables"]))
    monkeypatch.setattr(operations.dates, "schema_preservation", constant(schema))
    monkeypatch.setattr(operations.deployment, "snapshot", constant(({}, {})))
    monkeypatch.setattr(operations.common, "host_bytes", constant(b"guarded-adapter"))
    monkeypatch.setattr(operations, "source_scope", constant(["source-run"]))
    path = operations.make_plan(runtime, tmp_path, source)
    assert json.loads(path.read_bytes())["status"] == "PLANNED"


def test_retention_column_normalization_preserves_every_old_field(
    operations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operations.deployment,
        "full_preservation_state",
        constant({"retention.plan_run": {"digest": "raw-json-new-shape", "count": 13}}),
    )
    queries: list[str] = []

    def sql(_: str, query: str) -> str:
        queries.append(query)
        if "jsonb_build_object" in query:
            return '{"count":13,"digest":"old-fields-exact"}'
        if "information_schema" in query:
            return "t"
        return "0"

    monkeypatch.setattr(operations.deployment, "sql", sql)
    assert operations.preservation("pg") == {
        "retention.plan_run": {"count": 13, "digest": "old-fields-exact"}
    }
    assert "to_jsonb(t)-'source_projection_verified'" in queries[0]
    def changed_historical_flag(pg: str, query: str) -> str:
        return sql(pg, query) if "count(*) FROM retention.plan_run" not in query else "1"

    monkeypatch.setattr(operations.deployment, "sql", changed_historical_flag)
    with pytest.raises(RuntimeError, match="Historical"):
        operations.preservation("pg")


def test_graph_drift_refuses_before_any_deployment_or_removal(
    operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": {"hop": "hop", "pg": "pg"},
                "graph": {"path": "before", "sha256": "reviewed"},
                "artifacts": {},
                "protected_tables": {},
                "runs": ["run"],
                "schema": {"functions": {}, "triggers": {}},
            }
        )
    )
    monkeypatch.setattr(operations, "validate_archive", constant(Path("before")))
    monkeypatch.setattr(operations.deployment, "snapshot", constant(({}, {})))
    monkeypatch.setattr(operations, "preservation", constant({}))
    monkeypatch.setattr(operations, "source_scope", constant(["run"]))
    monkeypatch.setattr(
        operations.dates, "schema_preservation", constant({"functions": {}, "triggers": {}})
    )
    monkeypatch.setattr(operations, "graph_snapshot", constant({"sha256": "changed"}))
    monkeypatch.setattr(
        operations.deployment,
        "backup_database",
        forbidden("Graph drift reached backup"),
    )
    monkeypatch.setattr(
        operations, "remove_scaffolding", forbidden("Graph drift reached deletion")
    )
    monkeypatch.setattr(operations.common, "STATE", tmp_path)
    with pytest.raises(RuntimeError, match="Migration stopped") as stopped:
        operations.apply_plan({"hop": "hop", "pg": "pg"}, path, tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["status"] == "FAILED" and not receipt["scheduler_fenced"]
    assert receipt["failure_message"] == "Graph changed since reviewed plan; no migration writes"
    assert receipt["failure_phase"] == "FRESHNESS_CHECKING"
    failure_event = Path(receipt["events"][-1])
    assert json.loads(failure_event.read_bytes())["failure_message"] == receipt["failure_message"]
    assert receipt_path.stat().st_mode & 0o777 == failure_event.stat().st_mode & 0o777 == 0o600
    assert receipt["failure_message"] not in str(stopped.value)
    assert str(receipt_path) in str(stopped.value)


def test_failed_business_projection_keeps_scheduler_fenced_and_skips_deletion(
    operations: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = snapshot(
        tmp_path / "before.sqlite",
        [
            (
                "NODE",
                frame(
                    "j", frame("entity", "jobPosting"), prop(name=("STRING NOT NULL", "original"))
                ),
            )
        ],
    )
    changed = snapshot(
        tmp_path / "changed.sqlite",
        [
            (
                "NODE",
                frame(
                    "j", frame("entity", "jobPosting"), prop(name=("STRING NOT NULL", "changed"))
                ),
            )
        ],
    )
    backup = tmp_path / "full.dump"
    backup.write_bytes(b"verified fixture full dump")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    proof = tmp_path / "restore-proof.json"
    proof.write_text(json.dumps({"status": "VERIFIED", "database_backup_sha256": digest}))
    manifest: dict[str, Any] = {
        "version": 1,
        "runtime": {"hop": "hop", "pg": "pg"},
        "graph": {"path": str(original), "sha256": "reviewed"},
        "artifacts": {},
        "protected_tables": {},
        "runs": ["run"],
        "schema": {"functions": {}, "triggers": {}},
        "database_backup": {"path": str(backup), "sha256": digest},
        "host_adapter_sha256": "host",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(operations, "validate_archive", constant(original))
    monkeypatch.setattr(operations.deployment, "snapshot", constant(({}, {})))
    monkeypatch.setattr(operations, "preservation", constant({}))
    monkeypatch.setattr(operations, "source_scope", constant(["run"]))
    monkeypatch.setattr(
        operations.dates, "schema_preservation", constant({"functions": {}, "triggers": {}})
    )
    def projected_snapshot(hop: str, directory: Path, label: str) -> dict[str, str]:
        return {
            "path": str(changed if label == "graph-projected" else original),
            "sha256": "reviewed",
        }

    monkeypatch.setattr(operations, "graph_snapshot", projected_snapshot)
    monkeypatch.setattr(operations, "prepare_recovery", constant({"path": "reversible-export"}))
    monkeypatch.setattr(operations, "install_adapter", constant({"status": "VERIFIED"}))
    monkeypatch.setattr(operations.common, "STATE", tmp_path)
    monkeypatch.setattr(operations.common, "db_state", constant({}))
    monkeypatch.setattr(operations.deployment, "plan_manifest", constant({}))
    monkeypatch.setattr(
        operations.deployment, "apply", constant(tmp_path / "deployment-receipt")
    )
    monkeypatch.setattr(operations, "install_workflow", constant(None))
    monkeypatch.setattr(operations.dates, "temporary_native", constant(None))
    monkeypatch.setattr(operations.dates, "native", constant(None))
    monkeypatch.setattr(
        operations,
        "remove_scaffolding",
        forbidden("Failed preservation reached deletion"),
    )
    with pytest.raises(RuntimeError, match="Migration stopped"):
        operations.apply_plan(
            {"hop": "hop", "pg": "pg"}, path, tmp_path, backup_restore_proof=proof
        )
    receipt = json.loads((tmp_path / "receipt.json").read_bytes())
    assert receipt["status"] == "FAILED" and receipt["scheduler_fenced"]
    assert receipt["failure_message"] == "Existing business property value/type changed"
    assert receipt["failure_phase"] == "FOCUSED_SQL_INSTALLED"
    assert (tmp_path / "batchfree-migration.pending").is_file()
