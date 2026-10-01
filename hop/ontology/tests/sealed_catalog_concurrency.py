# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# Run: uv run hop/ontology/tests/sealed_catalog_concurrency.py (disposable Docker PostgreSQL only).
"""Exercise the publication fence with independent PostgreSQL connections."""

import os
import subprocess
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import run


@contextmanager
def connection() -> Generator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        ['docker', 'exec', '-i', run.PG, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
         '-U', 'postgres', '-d', 'ontologytest'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        yield process
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.wait(timeout=10)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def execute(process: subprocess.Popen[str], statement: str) -> None:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(statement + "; SELECT 'statement-complete';\n")
    process.stdin.flush()
    assert process.stdout.readline().strip() == 'statement-complete'


def check() -> None:
    run.load_sources(run.fixture())
    run.sql("SELECT ontology.capture_posting_census_v1('fixture-job_alio')")
    run.sql("SELECT ontology.prepare_release('race-a'); SELECT ontology.assemble_sources('race-a')")
    run.sql("SELECT ontology.bind_observations_v1('race-a'); "
            "SELECT ontology.prepare_catalog_source_v1('race-a')")

    # Given a pinned writer with an uncommitted content change, the seal cannot
    # validate a snapshot until that writer has finished.
    with connection() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        execute(writer, "BEGIN; SET LOCAL statement_timeout='20s'; UPDATE ingestion.record "
                "SET normalized=normalized||'{\"test_marker\":true}'::jsonb "
                "WHERE run_id='fixture-ncs_career_path'")
        run.expect_error("SET lock_timeout='100ms'; SELECT catalog._lock_release('race-a')",
                         'lock timeout')
        sealing = pool.submit(run.sql, "SET statement_timeout='20s'; "
                              "SELECT ontology.seal_catalog_source_v1('race-a')")
        execute(writer, 'COMMIT')
        try:
            sealing.result(timeout=25)
        except RuntimeError as error:
            assert 'PINNED_SOURCE_CHANGED' in str(error), str(error)
        else:
            raise AssertionError('Seal accepted a committed source mutation')

    # Restore the fixture before the first successful seal; the committed
    # mutation was deliberately observed by the verifier rather than hidden.
    run.sql("UPDATE ingestion.record SET normalized=normalized-'test_marker' "
            "WHERE run_id='fixture-ncs_career_path'")
    with connection() as sealer, ThreadPoolExecutor(max_workers=1) as pool:
        execute(sealer, "BEGIN; DO $$ BEGIN "
                "PERFORM ontology.seal_catalog_source_v1('race-a'); END $$")
        blocked_writer = pool.submit(
            run.expect_error,
            "SET statement_timeout='20s'; UPDATE ingestion.record SET normalized='{}'::jsonb "
            "WHERE run_id='fixture-ncs_career_path'",
            'SEALED_CATALOG_WRITE_FENCE',
        )
        execute(sealer, 'COMMIT')
        blocked_writer.result(timeout=25)
    run.expect_error("BEGIN ISOLATION LEVEL REPEATABLE READ; UPDATE ingestion.record "
                     "SET normalized=normalized WHERE run_id='fixture-ncs_career_path'; COMMIT",
                     'CATALOG_WRITES_REQUIRE_READ_COMMITTED')
    run.expect_error('BEGIN ISOLATION LEVEL REPEATABLE READ; '
                     'SELECT count(*) FROM ontology.corpus_release; '
                     'TRUNCATE ingestion.record CASCADE; COMMIT',
                     'SEALED_CATALOG_TRUNCATE_FENCE')
    run.expect_error("UPDATE ontology.release_source_run SET release_id='race-b' "
                     "WHERE release_id='race-a'", 'SEALED_CATALOG_WRITE_FENCE')
    run.sql("INSERT INTO ontology.graph_node SELECT * FROM ontology.graph_node "
            "WHERE release_id='race-a' ON CONFLICT DO NOTHING")
    run.sql("INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,"
            "created_at,completed_at) "
            "VALUES('race-unrelated','job_alio','FULL','fixture','READY',now(),now())")
    choices = '{' + ','.join('"' + source + '":"fixture-' + source + '"'
                           for source in run.fixture()) + '}'
    run.sql("SELECT ontology.prepare_release('race-b','" + choices + "'::jsonb); "
            "SELECT ontology.assemble_sources('race-b')")
    assert run.sql("SELECT count(*) FROM ontology.release_revision "
                   "WHERE release_id='race-b'") != '0'
    assert run.sql("SELECT manifest_hash IS NOT NULL FROM ontology.corpus_release "
                   "WHERE release_id='race-a'") == 't'
    # A SQL-only VERIFIED marker tests pointer serialization, not a native graph load.
    run.sql("INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,"
            "state,finished_at,node_count,edge_count) SELECT 'race-load','race-a','race-graph',"
            "manifest_hash,'VERIFIED',clock_timestamp(),(manifest->>'nodes')::bigint,"
            "(manifest->>'edges')::bigint FROM ontology.corpus_release WHERE release_id='race-a'; "
            "UPDATE ontology.corpus_release SET graph_verified_at=clock_timestamp() "
            "WHERE release_id='race-a'")
    start = Barrier(2)

    def approve() -> str:
        start.wait(timeout=10)
        return run.sql("SET statement_timeout='20s'; SELECT catalog.approve_catalog_release("
                       "'race-a','race-graph','fixture','race')")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(approve)
        second = pool.submit(approve)
        assert first.result(timeout=25) == second.result(timeout=25)
    assert run.sql('SELECT count(*) FROM catalog.catalog_approval') == '1'
    print('SEALED CATALOG TWO-CONNECTION CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run.PG = 'jobtology-sealed-race-' + uuid.uuid4().hex[:12] + '-pg'
    try:
        run.boot()
        check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):
            subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
