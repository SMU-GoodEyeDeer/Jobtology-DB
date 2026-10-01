"""Source-only catalog graph end-to-end in disposable PostgreSQL/Hop/Neo4j."""

import json
import os
import subprocess
import uuid

import claims
import graph
import native
import run


def check() -> None:
    # Given: independent accepted extraction exists, but this release has only
    # immutable source and observation membership.
    claims.check()
    reviewed_digest = claims.digest('review-fixture')
    run.sql("SELECT ontology.seal_graph('review-fixture')")
    assert json.loads(run.sql("SELECT manifest FROM ontology.corpus_release WHERE release_id='review-fixture'"))['format'] == 'hop-ontology-graph-v1'
    run.expect_error("SELECT ontology.prepare_catalog_source_v1('review-fixture')", 'ALREADY_SEALED')
    run.sql("SELECT ontology.capture_posting_census_v1('fixture-job_alio')")
    release = 'source-catalog-' + uuid.uuid4().hex[:10]
    choices = run.js({source: 'fixture-' + source for source in run.fixture()})
    run.sql(f"SELECT ontology.prepare_release({run.q(release)},{choices}); "
            f"SELECT ontology.assemble_sources({run.q(release)}); "
            f"SELECT ontology.bind_observations_v1({run.q(release)})")
    assert run.sql("SELECT count(*) FROM enrichment.extraction_decision WHERE decision='ACCEPT'") != '0'
    run.expect_error(f"SELECT ontology.seal_graph({run.q(release)})", 'FREEZE_REVIEWS_FIRST')

    # When: explicitly prepare and load the catalog projection through native Hop.
    run.sql(f"SELECT ontology.prepare_catalog_source_v1({run.q(release)})")
    graph.boot_neo()
    native.stage(neo=graph.NEO)
    native.run('install.hwf', {}, 'source-catalog-installer')
    native.run('load_release.hwf', {'RELEASE_ID': release}, 'source-catalog-load')

    # Then: exact source membership loads, while accepted external derived data
    # and the independent analytics activation gate remain outside the release.
    manifest = json.loads(run.sql(f"SELECT manifest FROM ontology.corpus_release WHERE release_id={run.q(release)}"))
    assert manifest['mode'] == 'SOURCE_ONLY' and manifest['format'] == 'hop-ontology-graph-source-v1'
    assert manifest['nodes'] > 0 and manifest['edges'] > 0
    assert run.sql(f"SELECT count(*) FROM ontology.review_freeze WHERE release_id={run.q(release)}") == '0'
    assert run.sql(f"SELECT count(*) FROM ontology.release_claim WHERE release_id={run.q(release)}") == '0'
    assert claims.digest('review-fixture') == reviewed_digest
    assert run.sql(f"SELECT count(*) FROM ontology.graph_node WHERE release_id={run.q(release)} "
                   "AND (labels && ARRAY['requirementClaim','positionClaim','guardedRule',"
                   "'competencyMappingClaim','postingReviewSelection'])") == '0'
    assert graph.neo("MATCH (n:ontologyObject) WHERE n.id STARTS WITH 'claim/' RETURN count(n)").splitlines()[-1] == '0'
    database_id = graph.neo('CALL db.info() YIELD id RETURN id').splitlines()[-1].strip('"')
    run.sql("INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,state,finished_at,node_count,edge_count) "
            "SELECT 'fixture-full-only','review-fixture','fixture-full-db',manifest_hash,'VERIFIED',clock_timestamp(),"
            "(manifest->>'nodes')::bigint,(manifest->>'edges')::bigint FROM ontology.corpus_release "
            "WHERE release_id='review-fixture'; UPDATE ontology.corpus_release SET graph_verified_at=clock_timestamp() "
            "WHERE release_id='review-fixture'")
    run.expect_error("SELECT catalog.approve_catalog_release('review-fixture','fixture-full-db','fixture','not source')",
                     'CATALOG_SOURCE_MODE_REQUIRED')
    approval = run.sql(f"SELECT catalog.approve_catalog_release({run.q(release)},{run.q(database_id)},'fixture','source-only native load')")
    assert approval
    assert json.loads(run.sql('SELECT catalog.catalog_context_v1()'))['release_id'] == release
    assert json.loads(run.sql('SELECT catalog.catalog_summary_v1()'))['posting_selection_outcomes']['SELECTION_PENDING'] == 6
    run.expect_error(f"SELECT ontology.activate_release({run.q(release)},'fixture','analytics')", 'RELEASE_NOT_READY_FOR_ACTIVATION')
    digest = run.sql(f"SELECT manifest_hash FROM ontology.corpus_release WHERE release_id={run.q(release)}")
    native.run('load_release.hwf', {'RELEASE_ID': release}, 'source-catalog-replay')
    assert run.sql(f"SELECT manifest_hash FROM ontology.corpus_release WHERE release_id={run.q(release)}") == digest
    assert run.sql('SELECT count(*) FROM retention.writer WHERE kind=\'ONTOLOGY_GRAPH\'') == '0'
    run.expect_error(f"SELECT ontology.freeze_reviews({run.q(release)})", 'ALREADY_SEALED')
    run.expect_error(f"DELETE FROM ontology.catalog_source_mode WHERE release_id={run.q(release)}",
                     'IMMUTABLE_ONTOLOGY_RECORD')
    print('SOURCE-ONLY NATIVE CATALOG CHECKS PASSED', manifest['nodes'], manifest['edges'], flush=True)


if __name__ == '__main__':
    try:
        run.boot()
        check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):
            for container in (graph.NEO, native.HOP, run.PG):
                subprocess.run(['docker', 'rm', '-fv', container], capture_output=True, check=False)
