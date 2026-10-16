"""Check flat projection guards against a restored, disposable native fixture.

Pass a local custom-format dump from tests/flat_projection.py. This test restores
it into a unique network-none container and never connects to the source database.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RELEASE = "flat-catalog-old"


def command(args: list[str], value: str | None = None) -> str:
    result = subprocess.run(args, input=value, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    return result.stdout.strip()


def check(container: str) -> None:
    def sql(value: str) -> str:
        return command(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "ontologytest",
            ],
            value,
        )

    def rejected(value: str, message: str) -> None:
        try:
            sql(value)
        except RuntimeError as error:
            assert message in str(error), str(error)
            return
        raise AssertionError("Expected rejection: " + message)

    def fingerprint() -> str:
        return sql("""SELECT ontology.hash(jsonb_build_object(
          'release',(SELECT jsonb_agg(r ORDER BY release_id) FROM ontology.corpus_release r),
          'revision',(SELECT jsonb_agg(r ORDER BY revision_id) FROM ontology.revision r),
          'selected',(SELECT jsonb_agg(r ORDER BY release_id,entity_id)
            FROM ontology.release_revision r),
          'nodes',(SELECT jsonb_agg(n ORDER BY release_id,node_id) FROM ontology.graph_node n),
          'edges',(SELECT jsonb_agg(e ORDER BY release_id,edge_id) FROM ontology.graph_edge e),
          'loads',(SELECT jsonb_agg(l ORDER BY load_id) FROM ontology.graph_load l),
          'approvals',(SELECT jsonb_agg(a ORDER BY approval_id) FROM catalog.catalog_approval a),
          'pointer',(SELECT jsonb_agg(p) FROM catalog.catalog_active_release p)))""")

    before = fingerprint()
    sql("""DO $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
        CREATE ROLE jobtology_catalog_reader;
      END IF;
    END $$; GRANT USAGE ON SCHEMA ontology TO jobtology_catalog_reader;""")
    sql((ROOT / "hop/ontology/sql/028_flat_graph_projection.sql").read_text())
    sql(f"SELECT ontology.seal_flat_graph_projection('{RELEASE}')")
    assert (
        sql(f"""SELECT count(DISTINCT r.kind) FROM ontology.flat_graph_revision_binding b
        JOIN ontology.revision r USING(revision_id) WHERE b.release_id='{RELEASE}'""")
        == "10"
    )
    assert (
        sql(f"""SELECT count(*)=0 FROM ontology.flat_graph_node
        WHERE release_id='{RELEASE}' AND ('entityRevision'=ANY(labels)
        OR EXISTS(SELECT 1 FROM unnest(labels) l WHERE l LIKE '%Revision'))""")
        == "t"
    )
    assert (
        sql(f"""SELECT count(*)=0 FROM ontology.flat_graph_edge e
        WHERE release_id='{RELEASE}' AND (subject_id LIKE 'revision/%'
        OR object_id LIKE 'revision/%'
        OR predicate IN ('HAS_REVISION','SELECTS_REVISION'))""")
        == "t"
    )
    assert (
        sql(f"""SELECT count(*)=0 FROM ontology.flat_graph_edge_disposition
        WHERE release_id='{RELEASE}' AND disposition IS NULL""")
        == "t"
    )
    owned = json.loads(
        sql("""SELECT ontology.flat_graph_owned_properties(
        '{"code":"ncs:123","entity_id":"stable","kind":"occupation","scheme_id":null}',
        '{"code":"123","entity_id":"stable","kind":"occupation","scheme_id":null,
          "revision_id":"r2","payload_hash":"h2","schema_version":"v2","blank":"",
          "removed":null,"empty":[],"ordered":[false,true]}')""")
    )
    assert owned == {
        "revision_code": "123",
        "selected_revision_id": "r2",
        "selected_revision_payload_hash": "h2",
        "selected_revision_schema_version": "v2",
        "blank": "",
        "empty": [],
        "ordered": [False, True],
    }
    for base, payload, error in [
        ('{"kind":"occupation"}', '{"kind":"jobPosting"}', "FLAT_IDENTITY_PROPERTY_CONFLICT"),
        ('{"name":"shell"}', '{"name":"revision"}', "FLAT_PROPERTY_COLLISION"),
        ("{}", '{"bad|key":"x"}', "FLAT_PROPERTY_COLLISION"),
        ("{}", '{"id":"x"}', "FLAT_PROPERTY_COLLISION"),
    ]:
        rejected(f"SELECT ontology.flat_graph_owned_properties('{base}','{payload}')", error)
    rejected(
        f"""INSERT INTO ontology.flat_graph_node
        SELECT release_id,node_id||'/late',labels,properties,identity_properties,owned_properties,
        content_hash,flat_content_hash FROM ontology.flat_graph_node
        WHERE release_id='{RELEASE}' LIMIT 1""",
        "FLAT_GRAPH_ALREADY_SEALED",
    )
    rejected(
        f"""INSERT INTO ontology.flat_graph_revision_binding
        SELECT release_id,revision_node_id||'/late',entity_node_id||'/late',revision_id,payload_hash
        FROM ontology.flat_graph_revision_binding WHERE release_id='{RELEASE}' LIMIT 1""",
        "FLAT_GRAPH_ALREADY_SEALED",
    )
    rejected(
        f"""INSERT INTO ontology.flat_graph_edge
        SELECT release_id,edge_id||'/late',origin_edge_id||'/late',subject_id,predicate,object_id,
        properties,content_hash,original_subject_id,original_predicate,original_object_id,
        original_properties,original_content_hash FROM ontology.flat_graph_edge
        WHERE release_id='{RELEASE}' LIMIT 1""",
        "FLAT_GRAPH_ALREADY_SEALED",
    )
    rejected(
        f"UPDATE ontology.flat_graph_projection SET manifest='{{}}' WHERE release_id='{RELEASE}'",
        "IMMUTABLE_ONTOLOGY_RECORD",
    )
    rejected("SELECT ontology.begin_graph_load('x','x','x')", "REVISION_GRAPH_WRITER_RETIRED")
    rejected(
        "SET ROLE jobtology_catalog_reader; SELECT ontology.begin_flat_graph_load('x','x','x')",
        "permission denied",
    )
    rejected(
        "SET ROLE jobtology_catalog_reader; SELECT * FROM ontology.flat_graph_projection",
        "permission denied",
    )
    database = sql("SELECT database_id FROM catalog.catalog_approval ORDER BY approval_id LIMIT 1")
    rejected(
        f"SELECT ontology.begin_flat_graph_load('review-fixture','{database}','wrong-initial')",
        "FLAT_INITIAL_REQUIRES_APPROVED_CATALOG",
    )
    sql(f"SELECT ontology.begin_flat_graph_load('{RELEASE}','sql-guard-db','sql-guard-token')")
    counts = sql(f"""SELECT node_count||','||edge_count FROM ontology.flat_graph_projection
        WHERE release_id='{RELEASE}'""")
    nodes, edges = counts.split(",")
    rejected(
        "SELECT ontology.stage_flat_graph_load('sql-guard-token',NULL,NULL,true)",
        "FLAT_STAGE_VERIFICATION_FAILED",
    )
    rejected(
        "SELECT ontology.finish_flat_graph_load('sql-guard-token',NULL,NULL,true)",
        "FLAT_LOAD_VERIFICATION_FAILED",
    )
    sql(f"SELECT ontology.stage_flat_graph_load('sql-guard-token',{nodes},{edges},true)")
    rejected(
        f"SELECT ontology.require_flat_graph_projection('{RELEASE}','sql-guard-db')",
        "FLAT_GRAPH_PROJECTION_NOT_READY",
    )
    assert sql("SELECT ontology.resume_flat_graph_load('sql-guard-token')") == "sql-guard-token"
    rejected("SELECT ontology.resume_flat_graph_load('missing-token')", "query returned no rows")
    sql(f"SELECT ontology.finish_flat_graph_load('sql-guard-token',{nodes},{edges},true)")
    sql(f"SELECT ontology.require_flat_graph_projection('{RELEASE}','sql-guard-db')")
    sql(f"SELECT ontology.begin_flat_graph_load('{RELEASE}','sql-guard-db','sql-recovery-token')")
    sql(f"SELECT ontology.stage_flat_graph_load('sql-recovery-token',{nodes},{edges},true)")
    sql("SELECT ontology.fail_flat_graph_load('sql-recovery-token')")
    rejected(
        f"SELECT ontology.require_flat_graph_projection('{RELEASE}','sql-guard-db')",
        "FLAT_GRAPH_PROJECTION_NOT_READY",
    )
    sql(f"SELECT ontology.begin_flat_graph_load('{RELEASE}','sql-guard-db','sql-recovery-retry')")
    rejected(
        f"SELECT ontology.finish_flat_graph_load('sql-guard-token',{nodes},{edges},true)",
        "FLAT_LOAD_VERIFICATION_FAILED",
    )
    sql(f"SELECT ontology.finish_flat_graph_load('sql-recovery-retry',{nodes},{edges},true)")
    assert fingerprint() == before, "Historical release, revision, inventory or approval changed"
    print(
        "FLAT PROJECTION SQL CHECKS PASSED: all 10 kinds, ownership/nulls, sealed proof, "
        "reader permissions, approved first target, staging/final tokens and recovery; "
        "history exact"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_dump", type=Path)
    options = parser.parse_args()
    assert options.fixture_dump.is_file()
    container = "jobtology-flat-core-sql-" + uuid.uuid4().hex[:12]
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                "none",
                "--name",
                container,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=ontologytest",
                "postgres:18-alpine",
            ]
        )
        for _ in range(100):
            if (
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        container,
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        "postgres",
                    ],
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(0.1)
        command(["docker", "cp", str(options.fixture_dump), container + ":/tmp/fixture.dump"])
        command(
            [
                "docker",
                "exec",
                container,
                "pg_restore",
                "--exit-on-error",
                "-U",
                "postgres",
                "-d",
                "ontologytest",
                "/tmp/fixture.dump",
            ]
        )
        check(container)
    finally:
        command(["docker", "rm", "-fv", container])


if __name__ == "__main__":
    main()
