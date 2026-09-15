"""Historical revision, claim, evidence and observation membership in native Hop.

Fresh synthetic PostgreSQL/Hop/Neo4j only; no source/model/attachment requests.
"""
import json
import subprocess
import uuid
import run


def main():
    suffix=uuid.uuid4().hex[:10]
    run.PG='jobtology-membership-pg-'+suffix
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode
    hop='jobtology-membership-hop-'+suffix;network='jobtology-membership-'+suffix;neo='jobtology-membership-neo-'+suffix
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    try:
        run.boot()
        import claims
        claims.check()
        original=claims.digest('review-fixture')
        old_revision=sql("SELECT revision_id FROM ontology.release_revision WHERE release_id='review-fixture' AND entity_id='urn:jobtology:jobPosting:job_alio:001'")
        requests=sql('SELECT count(*) FROM enrichment.attempt')

        def source(name,source,at,rows):
            sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) VALUES({q(name)},{q(source)},'FULL','fixture','READY',{q(at)},{q(at)}::timestamptz+interval '1 minute'); INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(name)},'all','FILE',1)")
            sql(f"INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) VALUES({q(name)},'doc','all',1,'fixture.json',encode(sha256(convert_to({q(name)},'UTF8')),'hex'),1,'UTF-8',200,{q(at)}::timestamptz+interval '30 seconds',true,now())")
            for idx,row in enumerate(rows):
                record=row.get('posting_id','record-'+str(idx))+(':'+row['representation'] if 'representation' in row else '')
                sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(name)},'doc',{q(str(idx))},{q(record)},{js(row)},{js(row)})")

        def prepare(name,job,at):
            sql('SELECT ontology.prepare_release('+q(name)+','+js({'job_alio':job,'alio_organization':'new-alio','ncs_competency':'fixture-ncs_competency'})+'); SELECT ontology.assemble_sources('+q(name)+')')
            sql('UPDATE ontology.corpus_release SET created_at='+q(at)+' WHERE release_id='+q(name))

        def states(name):
            report=json.loads(sql('SELECT ontology.query_posting_states_v1('+q(name)+',true)'))
            return {r['entity_id'].rsplit(':',1)[-1]:r for r in report['states']}

        # The current ALIO feed lacks C001; historical detail must keep the right
        # organization, rather than the stale list's C002 or an arbitrary name.
        source('new-alio','alio_organization','2026-09-02T00:00:00Z',[dict(kind='Organization',code='C002',name='현재 기관')])
        new_job=[r|dict(posting_id='007',organization_code='C003',organization_name='새 기관',title='새로운 채용') for r in run.fixture()['job_alio']]
        source('jobs-second','job_alio','2026-09-02T00:00:00Z',new_job)
        prepare('historical-first','jobs-second','2026-09-02T01:00:00Z')
        sql("SELECT ontology.bind_observations_v1('historical-first')")
        first=states('historical-first');assert len(first)==7
        assert first['001']['selected_revision_id']==old_revision and first['001']['serving_state']=='ACTIVE'
        assert first['001']['consecutive_absence_count']==1 and first['001']['content_run_id']=='fixture-job_alio'
        assert first['001']['connector_run_id']=='jobs-second' and first['001']['evaluated_at']=='2026-09-02T01:00:00+00:00'
        assert first['007']['consecutive_absence_count']==0
        assert sql("SELECT count(*) FROM ontology.input_record i JOIN ontology.release_source_run r USING(release_id,run_id) WHERE i.release_id='historical-first' AND r.role='HISTORICAL'")=='12'
        assert sql("SELECT name FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id='historical-first' AND m.entity_id='urn:jobtology:organization:alio:C001'")=='동일 기관명'
        assert sql("SELECT count(DISTINCT object_id)=1 AND min(object_id)='urn:jobtology:organization:alio:C001' FROM ontology.release_relation m JOIN ontology.source_relation r USING(relation_id) WHERE m.release_id='historical-first' AND r.subject_id='urn:jobtology:jobPosting:job_alio:001' AND predicate='POSTED_BY'")=='t'
        assert sql("SELECT bool_and(record_count=supported_records AND unaccounted_records=0) FROM ontology.source_coverage WHERE release_id='historical-first'")=='t'
        before=sql("SELECT manifest_hash FROM ontology.observation_membership WHERE release_id='historical-first'")
        sql("SELECT ontology.bind_observations_v1('historical-first'); SELECT ontology.assemble_sources('historical-first'); SELECT ontology.verify_observation_membership_v1('historical-first')")
        assert before==sql("SELECT manifest_hash FROM ontology.observation_membership WHERE release_id='historical-first'")
        claims.assemble('historical-first')
        # The exact previously reviewed inline extraction and NCS decision survive
        # absence. Validation alone and pending corrections remain unaccepted.
        assert sql("SELECT outcome FROM ontology.posting_selection WHERE release_id='historical-first' AND entity_id='urn:jobtology:jobPosting:job_alio:001'")=='ACCEPTED'
        assert sql("SELECT count(*) FROM ontology.release_claim WHERE release_id='historical-first'")=='4'
        assert sql("SELECT count(*) FROM ontology.release_mapping WHERE release_id='historical-first'")=='1'
        assert sql("SELECT count(*) FROM ontology.claim")=='4'
        assert sql("SELECT bool_and(i.run_id='fixture-job_alio') FROM ontology.artifact_source a JOIN ontology.input_record i USING(release_id,record_id) WHERE a.release_id='historical-first'")=='t'
        assert claims.digest('review-fixture')==original
        sql("SELECT ontology.seal_graph('historical-first')")
        assert sql("SELECT count(*) FROM ontology.graph_node WHERE release_id='historical-first' AND labels=ARRAY['entityObservationState']")=='7'
        assert sql("SELECT count(*) FROM ontology.graph_edge WHERE release_id='historical-first' AND predicate='FOR_ENTITY'")=='7'
        err("SELECT ontology.interchange_check_v1('historical-first',true)",'INTERCHANGE_UNMAPPED_NODE_LABEL')
        # v1 is immutable and must refuse the newly introduced class, not omit it.
        source('jobs-third','job_alio','2026-09-03T00:00:00Z',new_job)
        prepare('historical-second','jobs-third','2026-09-03T01:00:00Z')
        sql("SELECT ontology.bind_observations_v1('historical-second')")
        second=states('historical-second')
        assert second['001']['serving_state']=='NOT_SEEN' and second['001']['consecutive_absence_count']==2
        assert second['001']['selected_revision_id']==old_revision
        assert second['001']['observation_state_id']!=first['001']['observation_state_id']
        assert second['001']['first_seen_at']==first['001']['first_seen_at']==second['001']['last_seen_at']
        raw=json.loads(sql("SELECT jsonb_agg(normalized ORDER BY record_id) FROM ingestion.record WHERE run_id='fixture-job_alio' AND normalized->>'posting_id'='001'"))
        source('jobs-reappeared','job_alio','2026-09-04T00:00:00Z',new_job+[r|dict(title='변경된 채용 공고') for r in raw])
        prepare('historical-reappeared','jobs-reappeared','2026-09-04T01:00:00Z')
        sql("SELECT ontology.bind_observations_v1('historical-reappeared')")
        appeared=states('historical-reappeared')
        assert appeared['001']['consecutive_absence_count']==0 and appeared['001']['selected_revision_id']!=old_revision
        assert appeared['001']['first_seen_at']==first['001']['first_seen_at']
        claims.assemble('historical-reappeared')
        assert sql("SELECT outcome FROM ontology.posting_selection WHERE release_id='historical-reappeared' AND entity_id='urn:jobtology:jobPosting:job_alio:001'")=='NOT_PROCESSED'
        assert states('historical-first')==first and states('historical-second')==second
        # Raw-source tampering cannot survive the historical membership check.
        err("BEGIN; UPDATE ingestion.record SET normalized=normalized||'{\"title\":\"tampered\"}' WHERE run_id='fixture-job_alio'; SELECT ontology.check_frozen_sources('historical-second'); ROLLBACK;",'HISTORICAL_OBSERVATION_SOURCE_CHANGED')
        err("BEGIN; ALTER TABLE ontology.entity_observation_state DISABLE TRIGGER USER; UPDATE ontology.entity_observation_state SET selected_revision_id="+q(appeared['001']['selected_revision_id'])+" WHERE release_id='historical-second' AND entity_id='urn:jobtology:jobPosting:job_alio:001'; SELECT ontology.verify_observation_membership_v1('historical-second'); ROLLBACK;",'OBSERVATION_REVISION_BINDING_CHANGED')
        for table in ['entity_observation_state','observation_membership']:
            err('DELETE FROM ontology.'+table,'IMMUTABLE_ONTOLOGY_RECORD')
        err('DELETE FROM ontology.release_source_run','IMMUTABLE_RELEASE_SOURCE_RUN')
        prepare('late-binding','jobs-third','2026-09-03T01:00:00Z');claims.assemble('late-binding')
        err("SELECT ontology.bind_observations_v1('late-binding')",'BIND_OBSERVATIONS_BEFORE_INPUTS_OR_REVIEWS')
        prepare('different-cutoff','jobs-third','2026-09-03T01:00:00Z')
        sql("SELECT ontology.freeze_observations_v1('different-cutoff','2026-09-03T02:00:00Z')")
        err("SELECT ontology.freeze_reviews('different-cutoff')",'BIND_OBSERVATION_MEMBERSHIP_FIRST')
        err("SELECT ontology.bind_observations_v1('different-cutoff')",'OBSERVATION_EVALUATION_IS_FROZEN')
        # Real native execution and typed graph readback in isolated containers.
        import native
        native.HOP=hop;native.NET=network
        import graph
        graph.NEO=neo;graph.boot_neo();native.stage(neo=neo)
        native.run('install.hwf',{},'membership-native-installer')
        prepare('historical-native','jobs-third','2026-09-03T01:00:00.12Z')
        native.run('bind_observations.hwf',dict(RELEASE_ID='historical-native'),'native-bind-history')
        native.run('bind_observations.hwf',dict(RELEASE_ID='historical-native'),'native-history-replay')
        native.run('read_posting_states.hwf',dict(RELEASE_ID='historical-native',PREVIEW='Y'),'native-read-history')
        native.run('assemble_reviewed.hwf',dict(RELEASE_ID='historical-native'),'native-historical-claims')
        graph.neo("CREATE (p:Person {person_id:'keep-private'})")
        native.run('load_release.hwf',dict(RELEASE_ID='historical-native'),'native-historical-graph')
        assert graph.neo("MATCH (s:entityObservationState {release_id:'historical-native'})-[:FOR_ENTITY]->(p:jobPosting) RETURN count(s)").splitlines()[-1]=='7'
        checked=graph.neo("MATCH (s:entityObservationState {release_id:'historical-native',entity_id:'urn:jobtology:jobPosting:job_alio:001'})-[:SELECTS_REVISION]->(v:jobPostingRevision) RETURN s.serving_state='NOT_SEEN' AND s.last_seen_at=datetime('2026-09-01T00:00:30Z') AND s.evaluated_at=datetime('2026-09-03T01:00:00.12Z') AND v.revision_id="+json.dumps(old_revision)+" AS ok")
        assert checked.splitlines()[-1].lower()=='true',checked
        before_graph=graph.neo('MATCH (n) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)')
        native.run('load_release.hwf',dict(RELEASE_ID='historical-native'),'native-historical-graph-replay')
        assert before_graph==graph.neo('MATCH (n) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)')
        assert graph.neo("MATCH (p:Person {person_id:'keep-private'}) RETURN count(p)").splitlines()[-1]=='1'
        native.run('export_jsonld_v2.hwf',dict(RELEASE_ID='historical-native',PREVIEW='Y'),'native-observation-jsonld')
        run.cmd(['docker','cp',hop+':'+native.REMOTE+'/project/data/ontology-exports',str(native.WORK/'exports')])
        export=next((native.WORK/'exports').glob('*.jsonld'))
        import interchange
        interchange.MAPPING=json.loads((run.ROOT/'ontology/versions/hop-v2/mappings/hop-v2.json').read_text())
        rdf,manifest=interchange.roundtrip(export,'historical-native')
        result,_,details=interchange.validator.check(export)
        assert result['conforms'],details
        from rdflib import RDF,Namespace
        jt=interchange.JT;sh=Namespace('http://www.w3.org/ns/shacl#')
        assert len(set(rdf.subjects(RDF.type,jt.EntityObservationState)))==7
        pub,report,details=interchange.validator.check(export,True)
        assert not pub['conforms'],'Unfinished occupation/condition/review requirements must still reject publication'
        observation_nodes=set(rdf.subjects(RDF.type,jt.EntityObservationState))
        assert not observation_nodes&set(report.objects(None,sh.focusNode)),details
        tampered=json.loads(export.read_text())
        for row in tampered['@graph']:
            if 'evaluatedAt' in row:
                row['evaluatedAt']['@value']='2026-09-04T01:00:00Z';break
        bad=native.WORK/'incorrect-observation-time.jsonld';bad.write_text(json.dumps(tampered,ensure_ascii=False))
        try:interchange.validator.load(bad);raise RuntimeError('Accepted an altered observation date alias')
        except AssertionError as error:assert 'Observation datetime alias mismatch' in str(error),str(error)
        (native.WORK/'membership-report.json').write_text(json.dumps(dict(release_id='historical-native',nodes=manifest['nodes'],edges=manifest['edges'],postings=7,historical=6,rdf=result,publication_conforms=False,provider_calls=0),indent=2))
        assert sql('SELECT count(*) FROM enrichment.attempt')==requests
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        print('HISTORICAL MEMBERSHIP CHECKS PASSED: exact old revisions/claims/evidence, institution fallback, changed-content reappearance, frozen release time, immutable history, native Neo4j/replay and JSON-LD v2/SHACL.',flush=True)
        print('Native fixture:',native.WORK,flush=True)
    finally:
        for container in [hop,neo,run.PG]:subprocess.run(['docker','rm','-fv',container],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__=='__main__':main()
