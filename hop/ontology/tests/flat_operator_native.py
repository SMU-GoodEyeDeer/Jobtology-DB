"""Actual guarded operator deletion, typed recovery and retry on synthetic native resources."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


def run(fixture: Any, previous: Path | None = None) -> dict[str, Any]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "operations"))
    import migrate_flat_ontology_graph as ops
    import native

    os.umask(0o077)
    work = fixture.work / ("operator-" + uuid.uuid4().hex[:12])
    work.mkdir(mode=0o700)
    ops.PG_DATABASE = "ontologytest"
    original_sql, original_native, original_state = (
        ops.deployment.sql,
        ops.dates.native,
        ops.common.STATE,
    )

    def sql(pg: str, query: str) -> str:
        assert pg == fixture.pg
        return fixture.sql(query)

    def native_run(
        hop: str, path: str, directory: Path, label: str, params: dict[str, str] | None = None
    ) -> Path:
        assert hop == fixture.hop
        log = directory / (label + ".log")
        command = [
            "docker",
            "exec",
            "-e",
            "HOP_CONFIG_FOLDER=" + native.REMOTE + "/config",
            "-e",
            "HOP_OPTIONS=-Xmx1024m",
            "-w",
            "/opt/hop",
            hop,
            "bash",
            "hop-run.sh",
            "-j",
            "ontology-test",
            "-r",
            "ontology-local",
            "-f",
            path,
            "-l",
            "Basic",
        ]
        if params:
            command += ["-p", ",".join(k + "=" + v for k, v in params.items())]
        with log.open("xb") as output:
            status = subprocess.run(command, stdout=output, stderr=output, check=False)
        if status.returncode:
            raise RuntimeError("Synthetic native operation failed: " + str(log))
        return log

    ops.deployment.sql, ops.dates.native, ops.common.STATE = sql, native_run, work
    runtime = {"pg": fixture.pg, "hop": fixture.hop}
    release = "flat-catalog-old"
    receipt: dict[str, Any] = {
        "status": "RUNNING",
        "production_writes": False,
        "source_requests": 0,
        "paid_calls": 0,
    }
    try:
        if previous:
            previous_manifest = json.loads((previous / "manifest.json").read_bytes())
            historical_names = set(
                json.loads((fixture.work / "baseline.json").read_bytes())["tables"]
            )
            previous_manifest["old_tables"] = {
                k: v for k, v in previous_manifest["old_tables"].items() if k in historical_names
            }
            manifest_path = work / "prestage-restore-manifest.json"
            ops.common.write_json(manifest_path, previous_manifest)
            previous_recovery_path = previous / "before/flat-recovery.cypher.ndjson"
            recovery = {
                "path": str(previous_recovery_path),
                "sha256": ops.checksum(previous_recovery_path),
                "statements": sum(1 for _ in previous_recovery_path.open()),
            }
            load = ops.flat_load(fixture.pg, release, fixture.database)
            preapply = work / "prestage-restore"
            preapply.mkdir(mode=0o700)
            application = {
                "kind": "FLAT_ONTOLOGY",
                "runtime": runtime,
                "token": uuid.uuid4().hex,
                "manifest": str(manifest_path),
                "recovery": recovery,
                "load": load,
            }
            ops.common.write_json(preapply / "receipt.json", application)
            ops.common.write_json(work / ops.FENCE_NAME, {"token": application["token"]})
            ops.recover(runtime, preapply / "receipt.json")
            (work / ops.FENCE_NAME).unlink()
        before_dir = work / "before"
        before_dir.mkdir(mode=0o700)
        baseline = ops.graph.graph_snapshot(fixture.hop, before_dir, "historical")
        inventory = ops.capture_legacy_inventory(fixture.pg, release, before_dir)
        backing = ops.prove_legacy_backing(Path(baseline["path"]), inventory)
        ops.baseline_preconditions(Path(baseline["path"]), inventory)
        recovery = ops.prepare_recovery(Path(baseline["path"]), before_dir)
        historical_names = set(json.loads((fixture.work / "baseline.json").read_bytes())["tables"])
        old_tables = {
            k: v for k, v in ops.all_old_tables(fixture.pg).items() if k in historical_names
        }
        schema = ops.dates.schema_preservation(fixture.pg)
        manifest = {
            "runtime": runtime,
            "release_id": release,
            "graph": baseline,
            "legacy_inventory": inventory,
            "old_tables": old_tables,
            "schema": schema,
            "catalogue": {"approval": {"database_id": fixture.database}},
        }
        manifest_path = work / "manifest.json"
        ops.common.write_json(manifest_path, manifest)
        fixture.workflow("stage_flat_release.hwf", {"RELEASE_ID": release}, "flat-operator-stage")
        stage_dir = work / "staged"
        stage_dir.mkdir(mode=0o700)
        projected = ops.graph.graph_snapshot(fixture.hop, stage_dir, "staged")
        flat = ops.capture_flat_inventory(fixture.pg, release, stage_dir)
        ops.require_flat_preserved(
            Path(baseline["path"]), Path(projected["path"]), flat, removed=False
        )
        load = ops.flat_load(fixture.pg, release, fixture.database)
        assert load and load["state"] == "STAGED"
        ops.require_staged_tables(fixture.pg, old_tables, load)
        first = next(iter(ops.revision_nodes(Path(projected["path"])).values()))
        first_id = ops.graph.text_property(ops.graph.properties(first[-1]), "id")
        fixture.cypher(
            "MATCH(n:ontologyObject {id:"
            + ops.graph.cypher_string(first_id)
            + "}) CREATE(n)-[:UNEXPECTED_OPERATOR_ATTACHMENT]->(n)"
        )
        refused = work / "refused"
        refused.mkdir(mode=0o700)
        try:
            ops.native_statement_stream(
                fixture.hop,
                iter([next(ops.deletion_queries(Path(projected["path"])))]),
                refused,
                "unknown-attachment",
            )
        except RuntimeError:
            receipt["unexpected_attachment_refused"] = True
        else:
            raise AssertionError("Unaccounted attachment was deleted")
        fixture.cypher("MATCH()-[r:UNEXPECTED_OPERATOR_ATTACHMENT]->() DELETE r")
        partial = work / "partial"
        partial.mkdir(mode=0o700)
        ops.native_statement_stream(
            fixture.hop,
            iter([next(ops.deletion_queries(Path(projected["path"])))]),
            partial,
            "interrupted-first-delete",
        )
        partial_graph = ops.graph.graph_snapshot(fixture.hop, partial, "partial")
        ops.require_flat_preserved(
            Path(baseline["path"]), Path(partial_graph["path"]), flat, removed=None
        )
        ops.remove_revisions(fixture.hop, Path(partial_graph["path"]), partial)
        removed = ops.graph.graph_snapshot(fixture.hop, partial, "removed")
        ops.require_flat_preserved(
            Path(baseline["path"]), Path(removed["path"]), flat, removed=True
        )
        apply = work / "apply"
        apply.mkdir(mode=0o700)
        application = {
            "version": 1,
            "kind": "FLAT_ONTOLOGY",
            "status": "FAILED",
            "runtime": runtime,
            "token": uuid.uuid4().hex,
            "manifest": str(manifest_path),
            "recovery": recovery,
            "flat_inventory": flat,
            "load": load,
        }
        receipt_path = apply / "receipt.json"
        ops.common.write_json(receipt_path, application)
        ops.common.write_json(
            work / ops.FENCE_NAME, {"token": application["token"], "receipt": str(receipt_path)}
        )
        ops.recover(runtime, receipt_path)
        recovered = json.loads(receipt_path.read_bytes())
        assert recovered["status"] == "RECOVERED_FENCED" and (work / ops.FENCE_NAME).exists()
        # Receipt state and typed graph rollback are both repeatable.
        ops.recover(runtime, receipt_path)
        fixture.workflow(
            "stage_flat_release.hwf",
            {"RELEASE_ID": release},
            "flat-operator-restage-after-recovery",
        )
        retry = work / "retry"
        retry.mkdir(mode=0o700)
        retry_graph = ops.graph.graph_snapshot(fixture.hop, retry, "restaged")
        ops.require_flat_preserved(
            Path(recovered["recovered_graph"]["path"]),
            Path(retry_graph["path"]),
            flat,
            removed=False,
        )
        ops.remove_revisions(fixture.hop, Path(retry_graph["path"]), retry)
        retry_load = ops.flat_load(fixture.pg, release, fixture.database)
        assert (
            retry_load
            and retry_load["state"] == "STAGED"
            and retry_load["load_id"] != load["load_id"]
        )
        fixture.workflow(
            "finalize_flat_release.hwf",
            {"LOAD_ID": retry_load["load_id"]},
            "flat-operator-finalize",
        )
        fixture.workflow(
            "load_release.hwf", {"RELEASE_ID": release}, "flat-operator-normal-historical-replay"
        )
        final = ops.graph.graph_snapshot(fixture.hop, retry, "final")
        preservation = ops.require_flat_preserved(
            Path(baseline["path"]), Path(final["path"]), flat, removed=True
        )
        ops.require_old_tables(old_tables, ops.all_old_tables(fixture.pg))
        ops.require_schema(schema, ops.dates.schema_preservation(fixture.pg))
        receipt.update(
            status="PASSED",
            backing=backing,
            preservation=preservation,
            partial_delete_retry=True,
            typed_recovery_replayed=True,
            normal_historical_replay=True,
            final_zero_revisions=True,
        )
        return receipt
    except BaseException as error:
        receipt.update(
            status="FAILED", failure_type=type(error).__name__, failure_message=str(error)
        )
        raise
    finally:
        ops.common.write_json(work / "receipt.json", receipt)
        ops.deployment.sql, ops.dates.native, ops.common.STATE = (
            original_sql,
            original_native,
            original_state,
        )


def check_shared_removal(fixture: Any) -> dict[str, Any]:
    """Actual shared-edge/self-loop primitive before an unapproved preview load."""
    import sqlite3

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "operations"))
    import migrate_flat_ontology_graph as ops
    import native

    os.umask(0o077)
    work = fixture.work / ("shared-removal-" + uuid.uuid4().hex[:12])
    work.mkdir(mode=0o700)
    original_native = ops.dates.native

    def native_run(
        hop: str, path: str, directory: Path, label: str, params: dict[str, str] | None = None
    ) -> Path:
        assert hop == fixture.hop
        log = directory / (label + ".log")
        args = [
            "docker",
            "exec",
            "-e",
            "HOP_CONFIG_FOLDER=" + native.REMOTE + "/config",
            "-e",
            "HOP_OPTIONS=-Xmx1024m",
            "-w",
            "/opt/hop",
            hop,
            "bash",
            "hop-run.sh",
            "-j",
            "ontology-test",
            "-r",
            "ontology-local",
            "-f",
            path,
            "-l",
            "Basic",
        ]
        if params:
            args += ["-p", ",".join(k + "=" + v for k, v in params.items())]
        with log.open("xb") as output:
            status = subprocess.run(args, stdout=output, stderr=output, check=False)
        if status.returncode:
            raise RuntimeError("Shared-removal native fixture refused; inspect " + str(log))
        return log

    ops.dates.native = native_run
    receipt: dict[str, Any] = {
        "status": "RUNNING",
        "production_writes": False,
        "pg_backing_claim": False,
        "scope": "ISOLATED_REMOVAL_PRIMITIVE",
    }
    try:
        fixture.cypher("""CREATE (a:ontologyObject:entityRevision:occupationRevision {
            id:'revision/operator-shared-a',date:date('2026-10-01'),flags:[false,true]}),
            (b:ontologyObject:entityRevision:occupationRevision {
                id:'revision/operator-shared-b',value:1.5}),
            (x:entity:jobPosting {id:'operator-shared-business-a',
                dates:[date('2026-10-01'),date('2026-10-02')]}),
            (y:organization {id:'operator-shared-business-b',
                created_at:datetime('2026-10-01T00:00:00.123456789Z')}),
            (a)-[:FIXTURE_SHARED_REVISION {id:'operator-shared-edge',count:0}]->(b),
            (a)-[:FIXTURE_REVISION_LOOP {id:'operator-self-loop',text:'서울'}]->(a),
            (x)-[:FIXTURE_UNTOUCHED {id:'operator-untouched-edge',weights:[1.25,2.5]}]->(y)""")
        before = ops.graph.graph_snapshot(fixture.hop, work, "before")
        count = ops.remove_revisions(fixture.hop, Path(before["path"]), work)
        assert count == 2
        after = ops.graph.graph_snapshot(fixture.hop, work, "after")
        revisions = ops.revision_nodes(Path(before["path"]))
        assert not ops.revision_nodes(Path(after["path"]))
        db = sqlite3.connect(after["path"])
        try:
            for kind in ("NODE", "REL"):
                for row in ops.graph.records(Path(before["path"]), kind):
                    if (kind == "NODE" and row[0] in revisions) or (
                        kind == "REL" and any(eid in revisions for eid in row[1:3])
                    ):
                        continue
                    actual = db.execute(
                        "SELECT payload FROM snapshot WHERE kind=? AND eid=?", (kind, row[0])
                    ).fetchone()
                    assert actual and ops.graph.unpack(actual[0]) == row
            assert after["counts"]["NODE"] == before["counts"]["NODE"] - 2
            assert after["counts"]["REL"] == before["counts"]["REL"] - 2
        finally:
            db.close()
        receipt.update(
            status="PASSED",
            shared_revision_edge_deleted_once=True,
            self_loop_deleted_once=True,
            untouched_typed_business_exact=True,
            zero_revisions=True,
            before=before,
            after=after,
        )
        return receipt
    except BaseException as error:
        receipt.update(
            status="FAILED", failure_type=type(error).__name__, failure_message=str(error)
        )
        raise
    finally:
        ops.common.write_json(work / "receipt.json", receipt)
        ops.dates.native = original_native


check = run


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import flat_projection

    work = Path(sys.argv[1])
    context = json.loads((work / "context.json").read_bytes())
    fixture = flat_projection.Fixture(work, context["suffix"])
    fixture.database = json.loads((work / "baseline.json").read_bytes())["database"]
    import native

    native.WORK, native.HOP, native.PG = work, fixture.hop, fixture.pg
    for name in ("028_flat_graph_projection.sql", "029_flat_catalog_compatibility.sql"):
        fixture.sql((flat_projection.run.ROOT / "hop/ontology/sql" / name).read_text())
    fixture.stage()
    print(json.dumps(run(fixture, Path(sys.argv[2]) if len(sys.argv) > 2 else None)), flush=True)
