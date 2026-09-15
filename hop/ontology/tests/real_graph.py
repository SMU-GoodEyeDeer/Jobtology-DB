"""Native Neo4j round-trip of the saved real-source/review projection fixture.

Uses fixed disposable containers and synthetic acceptance in ontologyrealtest.
It never accesses Goldship, real credentials, or an inference endpoint.
"""
import json
import os
import subprocess
import native
from graph import NEO, boot_neo, neo, clear_fixture_graph
from real_claims import sql

RELEASE='real-reviewed-projection-fixture'


def check():
    native.stage(database='ontologyrealtest',neo=NEO)
    native.run('install.hwf',{},'real-graph-installer')
    expected=json.loads(sql("SELECT manifest FROM ontology.corpus_release WHERE release_id='"+RELEASE+"'"))
    assert expected['nodes']>100000 and expected['edges']>500000,expected
    clear_fixture_graph()
    neo("CREATE (:Person {person_id:'real-fixture-private',name:'Untouched test value'})")
    native.run('load_release.hwf',dict(RELEASE_ID=RELEASE),'real-graph-native-load')
    # The native verifier checks every projected property, label, edge endpoint
    # and membership. These separately authored traversals verify source meaning.
    checks={
        'postings':"MATCH (r:corpusRelease {release_id:$release})-[m:INCLUDES {release_id:$release}]->(p:jobPostingRevision) RETURN count(p)",
        'claims':"MATCH (r:corpusRelease {release_id:$release})-[:INCLUDES {release_id:$release}]->(c:assertion) WHERE c:dutyClaim OR c:requirementClaim RETURN count(c)",
        'evidence':"MATCH (r:corpusRelease {release_id:$release})-[:INCLUDES {release_id:$release}]->(e:evidenceSpan) RETURN count(e)",
        'positions':"MATCH (r:corpusRelease {release_id:$release})-[:INCLUDES {release_id:$release}]->(p:positionClaim) RETURN count(p)",
        'unversioned_families':"MATCH (v:ncsCompetencyRevision)-[:VERSION_OF {release_id:$release}]->(f:ncsUnitFamily) WHERE v.code CONTAINS '_' AND NOT f.code CONTAINS '_' RETURN count(v)",
        'qualified_curriculum':"MATCH (q:qualificationRevision)-[e:CURRICULUM_REFERENCES {release_id:$release}]->(:ncsCompetency) RETURN count(e)",
        'typed_exam_dates':"MATCH (e:examSessionRevision) WHERE any(k IN keys(e) WHERE k STARTS WITH 'dates.' AND valueType(e[k])='DATE NOT NULL') RETURN count(e)",
        'lineage_key_escaping':"MATCH (e:sourceRecordEvidence {source_id:'qnet_schedule'}) WHERE any(k IN keys(e) WHERE k STARTS WITH 'field_lineage.dates~2') RETURN count(e)",
        'private_untouched':"MATCH (p:Person {person_id:'real-fixture-private',name:'Untouched test value'}) RETURN count(p)",
    }
    actual={name:int(neo(query.replace('$release',json.dumps(RELEASE))).splitlines()[-1]) for name,query in checks.items()}
    assert actual['postings']==513 and actual['claims']==1850 and actual['positions']==211 and actual['evidence']==2873,actual
    assert actual['unversioned_families']==15520 and actual['qualified_curriculum']>0,actual
    assert actual['typed_exam_dates']>0 and actual['lineage_key_escaping']>0 and actual['private_untouched']==1,actual
    assert sql("SELECT state='PREPARING' AND graph_verified_at IS NOT NULL FROM ontology.corpus_release WHERE release_id='"+RELEASE+"'")=='t'
    assert sql('SELECT count(*) FROM ontology.active_release')=='0'
    assert sql("SELECT count(*) FROM retention.writer WHERE kind='ONTOLOGY_GRAPH'")=='0'
    report=dict(release_id=RELEASE,manifest=expected,readback=actual,production_reviews_written=0,semantic_quality_evaluation=False)
    (native.WORK/'real-graph-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('REAL NATIVE GRAPH READBACK PASSED',native.WORK,json.dumps(actual),flush=True)


if __name__=='__main__':
    try:boot_neo();check()
    finally:
        if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):
            for container in [NEO,native.HOP]:subprocess.run(['docker','rm','-fv',container],capture_output=True)
