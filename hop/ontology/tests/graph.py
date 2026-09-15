"""Native graph publication checks in disposable PostgreSQL/Hop/Neo4j only.

Publication gates deliberately remain closed while serving contracts are pending.
"""
import json
import os
import subprocess
import time
import uuid
import native
from run import ROOT,PG,cmd,sql,q,expect_error

NEO='jobtology-ontology-test-neo'
def neo(query):
    return cmd(['docker','exec',NEO,'cypher-shell','--format','plain',query])


def clear_fixture_graph():
    # Bounded cleanup matters when the previous fixture held the full corpus.
    # This helper can only address the fixed disposable NEO container above.
    # Remove edges first: one release root can have hundreds of thousands of
    # members, so even a one-node DETACH DELETE can exceed the test heap limit.
    neo('MATCH ()-[e]->() CALL (e) { DELETE e } IN TRANSACTIONS OF 1000 ROWS')
    neo('MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS')


def boot_neo():
    if subprocess.run(['docker','network','inspect',native.NET],capture_output=True).returncode:
        cmd(['docker','network','create','--internal',native.NET])
    if subprocess.run(['docker','inspect',NEO],capture_output=True).returncode:
        cmd(['docker','run','-d','--name',NEO,'--network',native.NET,'-e','NEO4J_AUTH=none',
            '-e','NEO4J_server_memory_heap_initial__size=512m','-e','NEO4J_server_memory_heap_max__size=512m',
            '-e','NEO4J_server_memory_pagecache_size=256m','neo4j:5.26-community'])
    for _ in range(90):
        try:neo('RETURN 1');break
        except RuntimeError:time.sleep(.5)
    else:raise AssertionError('Disposable Neo4j did not become ready')


def check():
    # claims.py already prepared source/review fixtures, with one accepted mapping
    # when the old NCS run is explicitly selected. No new model request is made.
    native.stage(neo=NEO)
    native.run('install.hwf',{},'graph-native-installer')
    clear_fixture_graph()
    neo("CREATE (p:Person {person_id:'fixture-private'}), (s:jobPosting {id:'fixture-staging',name:'Keep staging name'}), (p)-[:FIXTURE_PRIVATE_EDGE]->(s)")
    release='native-graph-fixture-'+uuid.uuid4().hex[:8]
    native.run('prepare_release.hwf',dict(RELEASE_ID=release,NCS_RUN_ID='fixture-ncs_competency'),'graph-source-assembly')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID=release),'graph-claim-assembly')
    native.run('load_release.hwf',dict(RELEASE_ID=release),'graph-native-load')
    report=json.loads(sql(f"SELECT manifest FROM ontology.corpus_release WHERE release_id={q(release)}"))
    assert report['nodes']>50 and report['edges']>report['nodes'],report
    assert sql(f"SELECT state='PREPARING' AND graph_verified_at IS NOT NULL FROM ontology.corpus_release WHERE release_id={q(release)}")=='t'
    assert sql("SELECT count(*) FROM ontology.active_release")=='0'
    assert sql("SELECT count(*) FROM retention.writer WHERE kind='ONTOLOGY_GRAPH'")=='0'
    assert neo("MATCH (p:Person {person_id:'fixture-private'})-[:FIXTURE_PRIVATE_EDGE]->(s:jobPosting {id:'fixture-staging'}) RETURN s.name='Keep staging name' AS kept").splitlines()[-1].lower()=='true'
    # Read the actual typed values with native Cypher, independently of generated
    # expected-property rows. Empty arrays and zero ordinals must survive.
    assert neo("MATCH (n:jobPostingRevision {posting_id:'001'}) RETURN n.name='데이터 엔지니어 채용' AND n.date_posted=date('2026-09-01') AND n.ongoing=true AS verified").splitlines()[-1].lower()=='true'
    assert neo("MATCH (n:conditionExpression {operator:'all_of'}) RETURN n.parts=[] AS verified").splitlines()[-1].lower()=='true'
    assert neo("MATCH (p:requirementClaim {category:'education'}) RETURN p.applicability='unresolved_positions' AND p.logic='unspecified' AS verified").splitlines()[-1].lower()=='true'
    assert neo("MATCH (m:competencyMappingClaim)-[e:MAPS_TARGET]->(v:ncsCompetencyRevision) RETURN m.assertion_kind='MODEL_INFERRED' AND v.code='2001020101_24v2' AND e.release_id="+json.dumps(release)+" AS verified").splitlines()[-1].lower()=='true'
    # Exact membership and content seal replay.
    before=neo("MATCH (n:ontologyObject) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)")
    digest=sql(f"SELECT manifest_hash FROM ontology.corpus_release WHERE release_id={q(release)}")
    native.run('load_release.hwf',dict(RELEASE_ID=release),'graph-native-replay')
    assert neo("MATCH (n:ontologyObject) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)")==before
    assert sql(f"SELECT manifest_hash FROM ontology.corpus_release WHERE release_id={q(release)}")==digest
    expect_error(f"SELECT ontology.assemble_sources({q(release)})",'ALREADY_SEALED')
    expect_error(f"SELECT ontology.activate_release({q(release)},'fixture','Must await serving contracts')",'RELEASE_NOT_READY_FOR_ACTIVATION')
    # A conflicting property causes failure and releases the writer. Source/old
    # graph objects are not overwritten to hide the mismatch.
    neo("MATCH (n:jobPostingRevision {posting_id:'001'}) SET n.name='Fixture conflict'")
    native.run('load_release.hwf',dict(RELEASE_ID=release),'reject-conflicting-graph-property',False)
    assert sql("SELECT count(*) FROM retention.writer WHERE kind='ONTOLOGY_GRAPH'")=='0'
    assert sql("SELECT state FROM ontology.graph_load ORDER BY started_at DESC LIMIT 1")=='FAILED'
    assert sql(f"SELECT graph_verified_at IS NULL FROM ontology.corpus_release WHERE release_id={q(release)}")=='t'
    assert neo("MATCH (n:jobPostingRevision {posting_id:'001'}) RETURN n.name='Fixture conflict'").splitlines()[-1].lower()=='true'
    neo("MATCH (n:jobPostingRevision {posting_id:'001'}) SET n.name='데이터 엔지니어 채용'")
    native.run('load_release.hwf',dict(RELEASE_ID=release),'graph-recovery-after-conflict')
    assert sql(f"SELECT graph_verified_at IS NOT NULL FROM ontology.corpus_release WHERE release_id={q(release)}")=='t'
    assert sql("SELECT count(*) FROM ontology.active_release")=='0'
    (native.WORK/'graph-fixture-report.json').write_text(json.dumps(report,indent=2))
    print('NATIVE ONTOLOGY GRAPH CHECKS PASSED',native.WORK,json.dumps(dict(nodes=report['nodes'],edges=report['edges'])),flush=True)


if __name__=='__main__':
    try:boot_neo();check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):
            for container in [NEO,native.HOP]:subprocess.run(['docker','rm','-fv',container],capture_output=True)
