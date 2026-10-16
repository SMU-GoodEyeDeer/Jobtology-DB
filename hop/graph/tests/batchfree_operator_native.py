"""Operator removal/typed rollback proof inside the all-source native fixture."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def run(fixture: Any) -> None:
    sys.path.insert(0, str(ROOT / "hop/operations"))
    import migrate_batchfree_graph as ops

    directory = fixture.work / "operator-proof"
    directory.mkdir(mode=0o700)
    for relative in ops.MIGRATION_SQL:
        target = fixture.work / "project" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "hop" / relative, target)
    ops.install_workflow(fixture.work / "project/focused-installer.hwf")
    fixture.run("../../focused-installer.hwf", "native-operator-focused-install")
    shutil.copyfile(
        ROOT / "hop/graph/verify_totals.hpl", fixture.work / "project/graph/verify_totals.hpl"
    )
    fixture.run(
        "../../graph/verify_totals.hpl",
        "native-grouped-current-edge-totals",
        extra={"RUN_ID": "ALL_CHECKPOINTED", "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    old_native, old_sql = ops.dates.native, ops.deployment.sql
    sequence = 0

    def native(hop: str, path: str, target: Path, label: str, params: Any = None) -> Path:
        fixture.command(
            [
                "docker",
                "exec",
                "-e",
                "HOP_CONFIG_FOLDER=/fixture/config",
                "-e",
                "HOP_OPTIONS=-Xmx1024m",
                "-w",
                "/opt/hop",
                hop,
                "bash",
                "hop-run.sh",
                "-j",
                "jobkorea-test",
                "-r",
                "jobkorea-local",
                "-f",
                path,
                "-l",
                "Basic",
            ],
            "operator-" + label,
            timeout=1800,
        )
        return fixture.logs / ("operator-" + label + ".log")

    def sql(_: str, statement: str) -> str:
        nonlocal sequence
        sequence += 1
        return fixture.sql(statement, "operator-pg-" + str(sequence))

    def neo(statement: str, label: str) -> str:
        return (
            fixture.command(
                ["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain", statement],
                "operator-neo-" + label,
            )
            .splitlines()[-1]
            .lower()
        )

    ops.dates.native, ops.deployment.sql = native, sql
    try:
        runs = ops.pg_rows(
            fixture.pg, "SELECT run_id,source_id FROM ingestion.run WHERE run_id='nara_job'"
        )
        fixture.expect(len(runs) == 1, "operator-legacy-run-backed")
        records = ops.pg_rows(
            fixture.pg, "SELECT * FROM ingestion.graph_record WHERE run_id='nara_job'"
        )
        refs = ops.pg_rows(
            fixture.pg, "SELECT * FROM ingestion.graph_reference WHERE run_id='nara_job'"
        )
        fixture.expect(bool(records) and bool(refs), "operator-legacy-records-backed")
        batch = (
            "MERGE (b:ingestionBatch {id:'nara_job'}) SET b.source_id='nara_job',"
            "b.state='READY',b.serving_scope='STAGING',b.batch_date=date('2026-10-11'),"
            "b.source_created_at=datetime('2026-10-11T00:00:00Z') RETURN true"
        )
        neo(batch, "create-batch")
        for number, row in enumerate(records):
            props = {
                key: value
                for key, value in row.items()
                if key in {"id", "source_id", "source_record_id", "kind", "name", "facts_json"}
                and value is not None
            }
            literal = (
                "{"
                + ",".join(
                    "`" + key + "`:" + ops.cypher_string(value) for key, value in props.items()
                )
                + "}"
            )
            neo(
                "MATCH(b:ingestionBatch {id:'nara_job'}) MERGE(r:ingestionRecord {id:"
                + ops.cypher_string(row["id"])
                + "}) SET r="
                + literal
                + " MERGE(b)-[:HAS_RECORD]->(r) RETURN true",
                "create-record-" + str(number),
            )
        for number, row in enumerate(refs):
            neo(
                "MATCH(r:ingestionRecord {id:"
                + ops.cypher_string(row["record_id"])
                + "}),(i:entity {id:"
                + ops.cypher_string(row["identity_id"])
                + "}) MERGE(r)-[:REFERS_TO {field:"
                + ops.cypher_string(row["field"])
                + "}]->(i) RETURN true",
                "create-reference-" + str(number),
            )
        neo(
            "MATCH(j:entity:jobPosting) WITH j LIMIT 1 SET "
            "j.operator_array=['서울','quoted\"value'],"
            "j.operator_dates=[date('2026-10-08'),date('2026-10-11')] RETURN true",
            "typed-business-array",
        )
        before = ops.graph_snapshot(fixture.hop, directory, "before")
        source = directory / "pg-evidence.sqlite"
        db = sqlite3.connect(source)
        db.execute("CREATE TABLE records(id TEXT,run_id TEXT,payload TEXT,PRIMARY KEY(id,run_id))")
        db.execute(
            "CREATE TABLE refs(record_id TEXT,identity_id TEXT,field TEXT,run_id TEXT,"
            "PRIMARY KEY(record_id,identity_id,field,run_id))"
        )
        db.executemany(
            "INSERT INTO records VALUES(?,?,?)",
            [(r["id"], r["run_id"], json.dumps(r)) for r in records],
        )
        db.executemany(
            "INSERT INTO refs VALUES(?,?,?,?)",
            [(r["record_id"], r["identity_id"], r["field"], r["run_id"]) for r in refs],
        )
        db.commit()
        db.close()
        backing = ops.prove_backing(fixture.pg, Path(before["path"]), source)
        fixture.expect(
            backing["record_nodes"] == len(records), "operator-all-history-exactly-pg-backed"
        )
        recovery = ops.prepare_recovery(Path(before["path"]), directory)
        scaffolds = ops.scaffold_nodes(Path(before["path"]))
        record_eid = next(
            eid for eid, n in scaffolds.items() if ops.unpack(n[1]) == ["ingestionRecord"]
        )
        neo(
            "MATCH(r:ingestionRecord),(i:entity) WITH r,i LIMIT 1 "
            "MERGE(r)-[:UNEXPECTED]->(i) RETURN true",
            "unexpected-attachment",
        )
        try:
            ops.native_rows(
                fixture.hop,
                ops.deletion_query([record_eid]),
                directory,
                "unexpected-delete-refused",
                write=True,
            )
        except RuntimeError:
            fixture.expect(
                neo("MATCH(r:ingestionRecord) RETURN count(r)>0", "history-still-present")
                == "true",
                "operator-unexpected-attachment-refused",
            )
        else:
            raise AssertionError("Unexpected scaffold attachment was deleted")
        neo("MATCH()-[r:UNEXPECTED]->() DELETE r RETURN true", "remove-fixture-attachment")
        ops.native_rows(
            fixture.hop, ops.deletion_query([record_eid]), directory, "partial-delete", write=True
        )
        partial = ops.graph_snapshot(fixture.hop, directory, "partial")
        remaining = directory / "remaining"
        remaining.mkdir(mode=0o700)
        ops.remove_scaffolding(fixture.hop, Path(partial["path"]), remaining)
        removed = ops.graph_snapshot(fixture.hop, directory, "removed")
        ops.require_business_preserved(Path(before["path"]), Path(removed["path"]))
        fixture.expect(
            not ops.scaffold_nodes(Path(removed["path"])),
            "operator-partial-delete-fresh-retry-complete",
        )
        restore = directory / "restore"
        restore.mkdir(mode=0o700)
        ops.recover_scaffolding(fixture.hop, recovery, restore)
        restored = ops.graph_snapshot(fixture.hop, directory, "restored")
        ops.prove_backing(fixture.pg, Path(restored["path"]), source)

        def typed_stable_nodes(path: str) -> dict[str, list[str]]:
            return {
                ops.text_property(ops.properties(n[-1]), "id"): n[1:]
                for n in ops.scaffold_nodes(Path(path)).values()
            }

        fixture.expect(
            typed_stable_nodes(before["path"]) == typed_stable_nodes(restored["path"]),
            "operator-typed-scaffold-rollback-exact",
        )
        replay = directory / "restore-replay"
        replay.mkdir(mode=0o700)
        ops.recover_scaffolding(fixture.hop, recovery, replay)
        fixture.expect(
            neo(
                "MATCH(n:ingestionRecord) RETURN count(n)=" + str(len(records)),
                "restore-idempotent",
            )
            == "true",
            "operator-rollback-replay-idempotent",
        )
        final_delete = directory / "final-delete"
        final_delete.mkdir(mode=0o700)
        ops.remove_scaffolding(fixture.hop, Path(restored["path"]), final_delete)
        final = ops.graph_snapshot(fixture.hop, directory, "final")
        proof = ops.require_business_preserved(Path(before["path"]), Path(final["path"]))
        fixture.expect(
            not ops.scaffold_nodes(Path(final["path"]))
            and proof["business_nodes"] > 0
            and proof["business_edges"] > 0,
            "operator-all-business-types-ids-links-and-dates-preserved",
        )
        fixture.receipt["operator"] = {
            "status": "PASSED",
            "backing": backing,
            "recovery": recovery,
            "business_preservation": proof,
        }
    finally:
        ops.dates.native, ops.deployment.sql = old_native, old_sql
