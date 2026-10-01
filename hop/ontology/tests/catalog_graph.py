#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# 1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
# 2. Run: uv run hop/ontology/tests/catalog_graph.py
# 3. Uses uniquely named disposable containers; never a server database.
# ──────────────────
from __future__ import annotations

import json
import os
import subprocess
import uuid

fixture_id = uuid.uuid4().hex[:10]
os.environ['ONTOLOGY_TEST_PG'] = f'jobtology-catalog-{fixture_id}-pg'
os.environ['ONTOLOGY_TEST_HOP'] = f'jobtology-catalog-{fixture_id}-hop'
os.environ['ONTOLOGY_TEST_NEO'] = f'jobtology-catalog-{fixture_id}-neo'
os.environ['ONTOLOGY_TEST_NET'] = f'jobtology-catalog-{fixture_id}'

import claims  # noqa: E402
import graph  # noqa: E402
import native  # noqa: E402
from run import PG, boot, expect_error, fixture, load_sources, q, sql  # noqa: E402


def check() -> None:
    # Given: six selected source runs and an unreviewed, bound release.
    boot()
    sources = fixture()
    sources['job_alio'] = [row | {
        'title': '데이터 엔지니어 채용',
        'education': '학력무관,고졸',
        'eligibility_text': (
            '😀 참고: 데이터베이스 설계\r\n담당 업무: 데이터베이스\t설계 및 구축\n'
            '내과, 응급의학과 전문의 자격 소지자 및 경력 2년 이상'
        ),
        'preference_text': '장애인 우대(단, 필수지원자격 미충족 시 제외)\r\n연락처 안내',
    } for row in sources['job_alio']]
    load_sources(sources)
    sql(
        "INSERT INTO enrichment.ncs_catalog SELECT run_id,normalized->>'code',"
        "normalized->>'name',normalized->>'definition',normalized->>'occupation_code',"
        "normalized->>'occupation_name' FROM ingestion.ready_record "
        "WHERE source_id='ncs_competency'"
    )
    revision = claims.capture(claims.seed_item('001', raw=claims.fixture_output()))
    claims.decide(revision)
    sql("SELECT ontology.capture_posting_census_v1('fixture-job_alio')")
    graph.boot_neo()
    native.stage(neo=graph.NEO)
    native.run('install.hwf', {}, 'catalog-native-install')
    graph.clear_fixture_graph()
    release = 'catalog-native-fixture'
    native.run('prepare_release.hwf', {'RELEASE_ID': release}, 'catalog-native-prepare')
    native.run('bind_observations.hwf', {'RELEASE_ID': release}, 'catalog-native-observations')
    expect_error(f"SELECT ontology.seal_graph({q(release)})", 'FREEZE_REVIEWS_FIRST')
    sql(f"SELECT ontology.prepare_catalog_source_v1({q(release)})")
    expect_error(
        f"SELECT catalog.approve_catalog_release({q(release)},'neo4j','operator','source-only')",
        'CATALOG_RELEASE_NOT_VERIFIED',
    )

    # When: the native loader verifies exact release-owned nodes and edges.
    native.run('load_release.hwf', {'RELEASE_ID': release}, 'catalog-native-load')

    # Then: approval refers to its actual VERIFIED load, not a fabricated checkpoint.
    manifest = json.loads(sql(
        f"SELECT manifest FROM ontology.corpus_release WHERE release_id={q(release)}"
    ))
    assert manifest['mode'] == 'SOURCE_ONLY'
    assert manifest['nodes'] > 0 and manifest['edges'] > 0
    assert manifest['nodes'] == int(sql(
        f"SELECT count(*) FROM ontology.graph_node WHERE release_id={q(release)}"
    ))
    assert manifest['edges'] == int(sql(
        f"SELECT count(*) FROM ontology.graph_edge WHERE release_id={q(release)}"
    ))
    assert sql(
        'SELECT count(*) FROM ontology.graph_load '
        f"WHERE release_id={q(release)} AND state='VERIFIED'"
    ) == '1'
    database_id = sql(f"SELECT database_id FROM ontology.graph_load WHERE release_id={q(release)}")
    approval_sql = (
        f"SELECT catalog.approve_catalog_release({q(release)},{q(database_id)},"
        "'operator','source-only')"
    )
    approval = sql(approval_sql)
    assert approval == sql(approval_sql)
    assert sql("SELECT count(*) FROM catalog.catalog_approval") == '1'
    assert json.loads(sql("SELECT catalog.catalog_summary_v1()"))['release_id'] == release
    assert sql("SELECT count(*) FROM ontology.active_release") == '0'
    assert sql(
        f"SELECT count(*) FROM ontology.posting_selection WHERE release_id={q(release)}"
    ) == '0'
    assert sql(f"SELECT count(*) FROM ontology.release_claim WHERE release_id={q(release)}") == '0'
    assert sql(
        f"SELECT count(*) FROM ontology.release_mapping WHERE release_id={q(release)}"
    ) == '0'
    assert sql("SELECT count(*) FROM enrichment.extraction_decision WHERE decision='ACCEPT'") == '1'
    assert graph.neo(
        'MATCH (n:ontologyObject) WHERE n:requirementClaim OR '
        'n:competencyMappingClaim OR n:postingReviewSelection RETURN count(n)'
    ).splitlines()[-1] == '0'
    assert graph.neo(
        "MATCH (n:jobPostingRevision {posting_id:'001'}) "
        "RETURN n.name='데이터 엔지니어 채용' AND "
        "n.date_posted=date('2026-09-01') AND n.ongoing=true AS verified"
    ).splitlines()[-1].lower() == 'true'
    assert graph.neo(
        f'MATCH (n:corpusRelease {{release_id:{json.dumps(release)}}})'
        f'-[:INCLUDES {{release_id:{json.dumps(release)}}}]->'
        '(e:jobPostingRevision) RETURN count(e)'
    ).splitlines()[-1] == '1'
    posted_by = graph.neo(
        "MATCH (p:jobPostingRevision {posting_id:'001'})-"
        f'[r:POSTED_BY {{release_id:{json.dumps(release)}}}]->(o:organization) '
        'RETURN o.code,r.release_id'
    )
    assert 'C001' in posted_by and release in posted_by, posted_by
    expect_error("SELECT ontology.query_summary_v1()", 'NO_ACTIVE_ONTOLOGY_RELEASE')
    expect_error(
        f"SELECT ontology.activate_release({q(release)},'operator','not ready')",
        'RELEASE_NOT_READY_FOR_ACTIVATION',
    )
    expect_error(
        "BEGIN; UPDATE ingestion.record SET normalized='{}'::jsonb "
        "WHERE run_id='fixture-ncs_career_path'; SELECT catalog.catalog_context_v1(); ROLLBACK",
        'SEALED_CATALOG_WRITE_FENCE',
    )

    before = graph.neo(
        'MATCH (n:ontologyObject) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)'
    )
    native.run('load_release.hwf', {'RELEASE_ID': release}, 'catalog-native-replay')
    assert graph.neo(
        'MATCH (n:ontologyObject) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)'
    ) == before
    expect_error("SELECT catalog.catalog_context_v1()", 'CATALOG_APPROVAL_STALE')
    sql(approval_sql)
    assert sql("SELECT count(*) FROM catalog.catalog_approval") == '2'

    graph.neo("MATCH (n:jobPostingRevision {posting_id:'001'}) SET n.name='Fixture conflict'")
    native.run('load_release.hwf', {'RELEASE_ID': release}, 'catalog-native-conflict', False)
    assert sql(
        'SELECT state FROM ontology.graph_load ORDER BY started_at DESC,load_id DESC LIMIT 1'
    ) == 'FAILED'
    assert sql("SELECT count(*) FROM retention.writer WHERE kind='ONTOLOGY_GRAPH'") == '0'
    expect_error("SELECT catalog.catalog_context_v1()", 'CATALOG_APPROVAL_STALE')
    graph.neo("MATCH (n:jobPostingRevision {posting_id:'001'}) SET n.name='데이터 엔지니어 채용'")
    native.run('load_release.hwf', {'RELEASE_ID': release}, 'catalog-native-recovery')
    expect_error("SELECT catalog.catalog_context_v1()", 'CATALOG_APPROVAL_STALE')
    sql(approval_sql)
    assert json.loads(sql("SELECT catalog.catalog_context_v1()"))['release_id'] == release
    print(
        'NATIVE SOURCE-ONLY CATALOG CHECKS PASSED', native.WORK,
        json.dumps({'nodes': manifest['nodes'], 'edges': manifest['edges'], 'verified_loads': 3}),
        flush=True,
    )


if __name__ == '__main__':
    try:
        check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):
            for container in (graph.NEO, native.HOP, PG):
                subprocess.run(['docker', 'rm', '-fv', container], capture_output=True, check=False)
            subprocess.run(
                ['docker', 'network', 'rm', native.NET], capture_output=True, check=False
            )
