"""Host detail boundaries and full typed graph verification without Docker."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_onet_detail_parser as parser_fixture

OPS = Path(__file__).resolve().parents[2] / "hop/operations"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location(
    "onet_detail_supervisor", OPS / "load_onet_details.py"
)
assert SPEC and SPEC.loader
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)


def frame(*values: str) -> str:
    return "".join(str(len(value)) + ":" + value for value in values)


def properties(values: dict[str, Any]) -> str:
    def encode(value: Any) -> tuple[str, str]:
        if isinstance(value, bool):
            return "BOOLEAN NOT NULL", str(value).lower()
        if isinstance(value, int):
            return "INTEGER NOT NULL", str(value)
        if isinstance(value, (float, Decimal)):
            return "FLOAT NOT NULL", str(value)
        assert isinstance(value, str)
        return "STRING NOT NULL", value

    return "".join(frame(key, *encode(value)) for key, value in sorted(values.items()))


def legacy() -> list[tuple[str, list[str]]]:
    return [
        (
            "NODE",
            [
                "occupation-eid",
                frame("entity", "onetCatalogObject", "occupation"),
                properties(
                    dict(
                        id="urn:jobtology:onet:occupation:15-1252.00",
                        managed_by="jobtology-onet-catalog-v1",
                        current=True,
                    )
                ),
            ],
        ),
        (
            "NODE",
            [
                "posting-eid",
                frame("entity", "jobPosting"),
                properties(dict(id="posting:1", title="한글\nquoted | % title")),
            ],
        ),
        (
            "REL",
            [
                "inference-eid",
                "posting-eid",
                "occupation-eid",
                "INFERRED_ONET_OCCUPATION",
                properties(dict(id="existing-link", current=False, lifecycle="STAGING")),
            ],
        ),
    ]


def owned() -> list[tuple[str, list[str]]]:
    shared = dict(managed_by=ops.OWNER, scheme_id="ONET", release_id="detail-fixture", current=True)
    return [
        (
            "NODE",
            [
                "element-eid",
                frame("entity", "onetDetail", "element"),
                properties(
                    dict(
                        **shared,
                        id=ops.PREFIX + "element:2.A.1.a",
                        kind="ELEMENT",
                        element_name="Reading",
                    )
                ),
            ],
        ),
        (
            "REL",
            [
                "rating-eid",
                "occupation-eid",
                "element-eid",
                "ONET_ESSENTIAL_SKILL",
                properties(
                    dict(
                        **shared,
                        id=ops.PREFIX + "edge:" + "a" * 64,
                        kind="ONET_ESSENTIAL_SKILL",
                        data_value=0.0,
                        n=8,
                        scale_id="IM",
                        not_relevant=False,
                    )
                ),
            ],
        ),
    ]


def archive(path: Path, rows: list[tuple[str, list[str]]]) -> Path:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE snapshot(kind TEXT,eid TEXT,payload TEXT,PRIMARY KEY(kind,eid))")
        db.executemany(
            "INSERT INTO snapshot VALUES(?,?,?)",
            [(kind, row[0], frame(*row)) for kind, row in rows],
        )
    return path


def bundle(folder: Path) -> dict[str, Any]:
    parser = parser_fixture.parser
    bodies, base = parser_fixture.sample()
    payload = parser_fixture.prepare(bodies, base)
    sources = payload["sources"]
    receipts = []
    (folder / "sources").mkdir()
    for source in sources:
        name = source["file_id"]
        (folder / source["archive_path"]).write_bytes(bodies[name])
        receipt = parser.canonical_bytes(
            dict(**source, http_status=200, response_url=source["source_uri"])
        )
        filename = f"sources/{name}.receipt.json"
        (folder / filename).write_bytes(receipt)
        receipts.append(
            dict(archive_path=filename, sha256=parser.sha256(receipt), byte_length=len(receipt))
        )
    body = parser.canonical_bytes(payload)
    (folder / "details.json").write_bytes(body)
    (folder / "base_catalogue.json").write_bytes(base)
    descriptor = dict(
        contract_version=parser.BUNDLE_CONTRACT,
        release_id=payload["release_id"],
        base_release_id=payload["base_release_id"],
        base_catalogue_sha256=parser.sha256(base),
        base_catalogue_byte_length=len(base),
        source_version="31.0",
        scheme_id="ONET",
        details_file="details.json",
        details_sha256=parser.sha256(body),
        details_byte_length=len(body),
        sources=sources,
        download_receipts=receipts,
        scope_codes=payload["scope_codes"],
        node_count=len(payload["nodes"]),
        edge_count=len(payload["edges"]),
        prepared_at="2026-10-15T10:00:00+00:00",
    )
    (folder / "descriptor.json").write_bytes(parser.canonical_bytes(descriptor))
    return descriptor


def test_complete_bundle_is_accepted(tmp_path: Path) -> None:
    descriptor = bundle(tmp_path)
    actual, inventory = ops.bundle_identity(tmp_path)
    assert actual == descriptor
    assert len(inventory) == 23


@pytest.mark.parametrize(
    "tamper", ["details", "base", "source", "receipt", "extra", "symlink", "path-traversal"]
)
def test_changed_bytes_or_inventory_are_rejected(tmp_path: Path, tamper: str) -> None:
    descriptor = bundle(tmp_path)
    if tamper == "details":
        (tmp_path / "details.json").write_text("{}\n")
    elif tamper == "base":
        (tmp_path / "base_catalogue.json").write_text("{}\n")
    elif tamper == "source":
        (tmp_path / descriptor["sources"][0]["archive_path"]).write_text("changed")
    elif tamper == "receipt":
        (tmp_path / descriptor["download_receipts"][0]["archive_path"]).write_text("changed")
    elif tamper == "extra":
        (tmp_path / "unexpected").write_text("extra")
    elif tamper == "symlink":
        (tmp_path / "link").symlink_to("details.json")
    else:
        descriptor["sources"][0]["archive_path"] = "sources/../details.json"
        (tmp_path / "descriptor.json").write_text(json.dumps(descriptor))
    with pytest.raises((RuntimeError, ValueError)):
        ops.bundle_identity(tmp_path)


@pytest.mark.parametrize(
    "field",
    [
        "contract_version",
        "base_release_id",
        "node_count",
        "edge_count",
        "scope_codes",
        "source_version",
    ],
)
def test_descriptor_semantics_are_bound_to_payload(tmp_path: Path, field: str) -> None:
    descriptor = bundle(tmp_path)
    descriptor[field] = (
        [] if field == "scope_codes" else 999 if field.endswith("count") else "wrong"
    )
    (tmp_path / "descriptor.json").write_text(json.dumps(descriptor))
    with pytest.raises((RuntimeError, ValueError)):
        ops.bundle_identity(tmp_path)


def test_bundle_directory_symlink_is_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "bundle"
    folder.mkdir()
    bundle(folder)
    link = tmp_path / "alias"
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises((RuntimeError, ValueError)):
        ops.bundle_identity(link)


def test_existing_typed_source_and_inferred_graph_are_preserved(tmp_path: Path) -> None:
    before = archive(tmp_path / "before.sqlite", legacy())
    after = archive(tmp_path / "after.sqlite", legacy() + owned())
    assert ops.require_graph_preserved(before, after) == dict(
        legacy_nodes=2, legacy_edges=1, detail_nodes=1, detail_edges=1
    )


@pytest.mark.parametrize(
    "mutation", ["labels", "type", "property", "edge-endpoint", "removed", "new-foreign"]
)
def test_legacy_mutations_and_new_foreign_objects_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    before = archive(tmp_path / "before.sqlite", legacy())
    rows = legacy() + owned()
    if mutation == "labels":
        rows[0][1][1] = frame("entity", "occupation")
    elif mutation == "type":
        rows[0][1][-1] = rows[0][1][-1].replace("BOOLEAN NOT NULL", "STRING NOT NULL")
    elif mutation == "property":
        rows[1][1][-1] = properties(dict(id="posting:1", title="changed"))
    elif mutation == "edge-endpoint":
        rows[2][1][2] = "element-eid"
    elif mutation == "removed":
        rows.pop(0)
    else:
        rows.append(("NODE", ["foreign", frame("entity"), properties(dict(id="foreign"))]))
    with pytest.raises(RuntimeError):
        ops.require_graph_preserved(before, archive(tmp_path / "after.sqlite", rows))


def expected(rows: list[tuple[str, list[str]]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"graph_load_node": [], "graph_load_edge": []}
    for kind, row in rows:
        values: dict[str, Any] = {}
        for name, (value_type, value) in ops.catalogue.graph.properties(row[-1]).items():
            values[name] = (
                value == "true"
                if value_type == "BOOLEAN NOT NULL"
                else int(value)
                if value_type == "INTEGER NOT NULL"
                else Decimal(value)
                if value_type == "FLOAT NOT NULL"
                else value
            )
        if kind == "NODE":
            result["graph_load_node"].append(
                dict(
                    node_id=values["id"],
                    labels=ops.catalogue.graph.unpack(row[1]),
                    properties=values,
                )
            )
        else:
            result["graph_load_edge"].append(
                dict(
                    edge_id=values["id"],
                    start_id="urn:jobtology:onet:occupation:15-1252.00",
                    end_id=ops.PREFIX + "element:2.A.1.a",
                    edge_type=row[3],
                    properties=values,
                )
            )
    return result


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "float-to-int",
        "boolean-to-string",
        "endpoint",
        "type",
        "missing",
        "extra",
        "duplicate-plan",
    ],
)
def test_full_typed_graph_matches_plan_including_zero_floats_and_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str | None
) -> None:
    rows = legacy() + owned()
    plan = expected(owned())
    snapshot = archive(tmp_path / "graph.sqlite", rows)
    rating = plan["graph_load_edge"][0]
    if mutation == "float-to-int":
        rating["properties"]["data_value"] = 0
    elif mutation == "boolean-to-string":
        rating["properties"]["not_relevant"] = "false"
    elif mutation == "endpoint":
        rating["start_id"] = "posting:1"
    elif mutation == "type":
        rating["edge_type"] = "ONET_KNOWLEDGE"
    elif mutation == "missing":
        rating["edge_id"] = ops.PREFIX + "edge:" + "b" * 64
    elif mutation == "extra":
        plan["graph_load_edge"] = []
    elif mutation == "duplicate-plan":
        plan["graph_load_edge"].append(rating)

    def inventory(pg: str, query: str, output: Path):
        assert pg == "fixture-pg" and "'owned-load'" in query
        return (
            (row, "unused")
            for row in plan["graph_load_node" if "graph_load_node" in query else "graph_load_edge"]
        )

    monkeypatch.setattr(ops.catalogue.typed, "copy_inventory", inventory)
    if mutation:
        with pytest.raises(RuntimeError):
            ops.verify_expected_graph("fixture-pg", snapshot, "owned-load", tmp_path)
    else:
        assert ops.verify_expected_graph("fixture-pg", snapshot, "owned-load", tmp_path) == dict(
            nodes=1, edges=1
        )


def proof_value() -> dict[str, Any]:
    return dict(
        status="PASSED_ONET_DETAILS_NATIVE",
        isolated=True,
        disposable_resources_removed=True,
        private_scratch_removed=True,
        artifact_sha256={"native": "public-hash"},
        helper_sha256=ops.helper_identity(),
        official_details_sha256="detail-hash",
        checks=[
            "all-typed-properties-and-endpoints",
            "exact-native-detail-replay",
            "all-existing-pg-preserved",
            "foreign-preflight-no-graph-mutation",
        ],
    )


def test_qualification_binds_public_parser_loader_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "proof.json"
    value = proof_value()
    path.write_text(json.dumps(value))
    result = ops.qualification(path, {"native": "public-hash"}, {"details_sha256": "detail-hash"})
    assert result["sha256"] == ops.identity(path)["sha256"]
    assert result["checks"] == value["checks"]


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "public",
        "parser",
        "loader",
        "payload",
        "isolated-false",
        "isolated-string",
        "cleanup-false",
        "scratch-string",
        "checks-empty",
        "checks-missing",
    ],
)
def test_malformed_or_stale_qualification_rejects(tmp_path: Path, mutation: str) -> None:
    value = proof_value()
    if mutation == "status":
        value["status"] = "FAILED"
    elif mutation == "public":
        value["artifact_sha256"] = {"native": "changed"}
    elif mutation in {"parser", "loader"}:
        value["helper_sha256"][mutation] = "changed"
    elif mutation == "payload":
        value["official_details_sha256"] = "changed"
    elif mutation == "isolated-false":
        value["isolated"] = False
    elif mutation == "isolated-string":
        value["isolated"] = "false"
    elif mutation == "cleanup-false":
        value["disposable_resources_removed"] = False
    elif mutation == "scratch-string":
        value["private_scratch_removed"] = "false"
    elif mutation == "checks-empty":
        value["checks"] = []
    else:
        value["checks"].pop()
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError):
        ops.qualification(path, {"native": "public-hash"}, {"details_sha256": "detail-hash"})


def test_qualification_symlink_rejects(tmp_path: Path) -> None:
    original = tmp_path / "proof.json"
    original.write_text(json.dumps(proof_value()))
    link = tmp_path / "link.json"
    link.symlink_to(original)
    with pytest.raises(RuntimeError):
        ops.qualification(link, {"native": "public-hash"}, {"details_sha256": "detail-hash"})


def test_fence_never_replaces_existing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ops, "STATE", tmp_path)
    fence = tmp_path / ops.catalogue.performance.FENCE_NAME
    fence.write_bytes(b"existing owner bytes\n")
    with pytest.raises(FileExistsError):
        ops.own_fence(dict(kind="new", token="new"), tmp_path / "receipt.json")
    assert fence.read_bytes() == b"existing owner bytes\n"


def mocked_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir()
    project = tmp_path / "project"
    candidate = project / "ingestions/onet_details/install.hwf"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate runtime")
    public_name = "ingestions/onet_details/install.hwf"
    descriptor = dict(details_sha256="detail-hash", release_id="detail-fixture")
    monkeypatch.setattr(ops, "ROOT", project)
    monkeypatch.setattr(ops, "STATE", state)
    monkeypatch.setattr(ops, "bundle_identity", lambda folder: (descriptor, {}))
    monkeypatch.setattr(ops, "artifacts", lambda: (public_name,))
    monkeypatch.setattr(ops, "helper_identity", lambda: {"parser": "p", "loader": "l"})
    monkeypatch.setattr(ops, "qualification", lambda *args: {"checks": ["qualified"]})
    monkeypatch.setattr(ops.catalogue.common, "containers", lambda: {"pg": "pg", "hop": "hop"})
    monkeypatch.setattr(ops.catalogue.performance, "idle", lambda runtime: None)
    monkeypatch.setattr(ops, "legacy_runtime", lambda hop: "old runtime definitions")
    monkeypatch.setattr(ops, "pg_state", lambda pg, **kwargs: {"table+functions+triggers": "exact"})
    monkeypatch.setattr(
        ops.catalogue.additive, "backup_database", lambda *args: {"backup": "retained"}
    )
    monkeypatch.setattr(ops.catalogue, "scalar_snapshot_adapter", contextlib.nullcontext)
    calls: list[Any] = []
    remote = {public_name: b"old runtime"}

    def command(argv, **kwargs):
        assert argv[:4] == ["docker", "exec", "-i", "hop"]
        return b"PRESENT\n" + remote[public_name]

    def write_runtime(hop, name, value, previous_sha, directory, token):
        assert (directory / "before-runtime" / name).read_bytes() == b"old runtime"
        assert previous_sha == ops.catalogue.common.digest(b"old runtime")
        remote[name] = value

    def snapshot(hop, work, label):
        path = work / (label + ".sqlite")
        archive(path, legacy() if label == "graph-before" else legacy() + owned())
        return {"path": str(path)}

    def native(*args, **kwargs):
        calls.append((args, kwargs))

    def inventory(pg, query, output):
        assert "'native-generated-load-id'" in query
        plan = expected(owned())
        return (
            (row, "unused")
            for row in plan["graph_load_node" if "graph_load_node" in query else "graph_load_edge"]
        )

    monkeypatch.setattr(ops.catalogue.common, "command", command)
    monkeypatch.setattr(ops.catalogue.additive, "write_runtime", write_runtime)
    monkeypatch.setattr(ops.catalogue.graph, "graph_snapshot", snapshot)
    monkeypatch.setattr(
        ops.catalogue.graph, "validate_archive", lambda metadata: Path(metadata["path"])
    )
    monkeypatch.setattr(ops.catalogue, "archive", lambda *args: "/immutable/details")
    monkeypatch.setattr(ops.catalogue.loader, "native", native)
    monkeypatch.setattr(ops.catalogue.typed, "copy_inventory", inventory)
    monkeypatch.setattr(
        ops.catalogue.deployment,
        "sql",
        lambda *args: json.dumps(
            dict(state="VERIFIED", load_id="native-generated-load-id", release_id="detail-fixture")
        ),
    )

    def release(receipt, path):
        fence = state / ops.catalogue.performance.FENCE_NAME
        data = json.loads(fence.read_text())
        assert data["token"] == receipt["token"] and data["receipt"] == str(path)
        fence.unlink()

    monkeypatch.setattr(ops.catalogue.performance, "release_fence", release)
    return state, calls


def test_complete_host_success_adopts_native_load_and_preserves_runtime_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, calls = mocked_execution(tmp_path, monkeypatch)
    path = ops.execute(tmp_path / "bundle", tmp_path / "proof")
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "VERIFIED_ONET_DETAILS"
    assert receipt["scheduler_fence_removed"] is True
    assert receipt["load"]["load_id"] == "native-generated-load-id"
    assert receipt["independent_expected_graph"] == dict(nodes=1, edges=1)
    assert (
        path.parent / "before-runtime/ingestions/onet_details/install.hwf"
    ).read_bytes() == b"old runtime"
    assert len(calls) == 2
    assert not (state / ops.catalogue.performance.FENCE_NAME).exists()


def test_after_native_verifier_failure_retains_fence_baseline_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, calls = mocked_execution(tmp_path, monkeypatch)

    def fail(*args):
        raise RuntimeError("deliberate after-native verifier failure")

    monkeypatch.setattr(ops, "verify_expected_graph", fail)
    with pytest.raises(RuntimeError, match="after-native"):
        ops.execute(tmp_path / "bundle", tmp_path / "proof")
    fence = json.loads((state / ops.catalogue.performance.FENCE_NAME).read_text())
    path = Path(fence["receipt"])
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "FAILED_FENCED"
    assert receipt["database_backup"] == {"backup": "retained"}
    assert receipt["before_pg"] == receipt["after_pg"]
    assert receipt["scheduler_fence_removed"] is False
    assert receipt["load"]["state"] == "VERIFIED"
    assert len(calls) == 2


class InputStream:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.closed = False
        self.flush_count = 0

    def write(self, value: str) -> None:
        assert not self.closed
        self.writes.append(value)

    def flush(self) -> None:
        self.flush_count += 1

    def close(self) -> None:
        self.closed = True


class PsqlProcess:
    def __init__(self, responses: list[Any], trailing: str = "", exit_code: int = 0) -> None:
        self.stdin = InputStream()
        self.stdout = io.StringIO("".join(json.dumps(row) + "\n" for row in responses) + trailing)
        self.exit_code = exit_code
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: int | None = None) -> int:
        self.returncode = self.exit_code
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def pg_responses() -> list[Any]:
    return [
        ["classification.term", '"Mixed Schema"."Odd Table"'],
        {"table": "classification.term", "value": [123, "a" * 32]},
        {"table": '"Mixed Schema"."Odd Table"', "value": [0, "d41d8cd98f00b204e9800998ecf8427e"]},
        {
            "functions": [["f()", "CREATE FUNCTION f() RETURNS text"]],
            "columns": [],
            "indexes": [],
            "triggers": [],
        },
    ]


def mock_psql(monkeypatch: pytest.MonkeyPatch, process: PsqlProcess) -> list[Any]:
    calls: list[Any] = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stderr"].write("fixture statement error")
        return process

    monkeypatch.setattr(ops.subprocess, "Popen", popen)
    return calls


def test_postgres_fingerprints_share_one_read_only_repeatable_read_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = pg_responses()
    process = PsqlProcess(responses)
    calls = mock_psql(monkeypatch, process)
    progress: list[Any] = []
    actual = ops.pg_state("fixture-pg", "fixture-database", progress=progress.append)
    assert actual == dict(
        tables={row["table"]: row["value"] for row in responses[1:3]}, metadata=responses[-1]
    )
    assert len(calls) == 1
    command = calls[0][0]
    assert command[:4] == ["docker", "exec", "-i", "fixture-pg"]
    assert command[-2:] == ["-d", "fixture-database"]
    assert command[command.index("-v") + 1] == "ON_ERROR_STOP=1"
    writes = process.stdin.writes
    assert writes[0] == (
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSET LOCAL statement_timeout='180s';\n"
    )
    assert writes[1].strip() == ops.PG_TABLES_SQL.strip()
    assert writes[2].strip() == ops.table_fingerprint_sql("classification.term").strip()
    assert writes[3].strip() == ops.table_fingerprint_sql('"Mixed Schema"."Odd Table"').strip()
    assert writes[4].strip() == ops.PG_METADATA_SQL.strip()
    assert writes[-1] == "COMMIT;\n"
    assert all("UNION ALL" not in statement for statement in writes)
    assert "md5(to_jsonb(t)::text)" in writes[2]
    assert "string_agg(h,'' ORDER BY h)" in writes[2]
    assert progress == [
        {"table": "classification.term", "completed": 0, "total": 2},
        {"table": '"Mixed Schema"."Odd Table"', "completed": 1, "total": 2},
        {"completed": 2, "total": 2, "state": "COMPLETE"},
    ]
    assert process.stdin.closed and process.stdout.closed and not process.terminated


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-table",
        "wrong-table",
        "malformed-fingerprint",
        "trailing-output",
        "failed-exit",
        "eof",
    ],
)
def test_postgres_preservation_reader_refuses_partial_or_malformed_evidence(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    responses = pg_responses()
    trailing = ""
    code = 0
    if mutation == "duplicate-table":
        responses[0] = ["classification.term", "classification.term"]
    elif mutation == "wrong-table":
        responses[1]["table"] = "wrong.table"
    elif mutation == "malformed-fingerprint":
        responses[1]["value"] = []
    elif mutation == "trailing-output":
        trailing = "unexpected output\n"
    elif mutation == "failed-exit":
        code = 1
    else:
        responses = responses[:1]
    process = PsqlProcess(responses, trailing, code)
    mock_psql(monkeypatch, process)
    with pytest.raises(RuntimeError):
        ops.pg_state("fixture-pg")
    assert process.stdin.closed and process.stdout.closed
    if mutation in {"duplicate-table", "wrong-table", "malformed-fingerprint"}:
        assert process.terminated
        assert not any(statement == "COMMIT;\n" for statement in process.stdin.writes)
