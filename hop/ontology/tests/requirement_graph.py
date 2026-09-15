"""Nine Korean condition kinds through native Neo4j and JSON-LD v3; no paid calls."""
import importlib.util
import json
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path
import run
import requirements

def check(native):
    import claims
    import graph as neo_fixture
    from rdflib import RDF,Namespace
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    neo_name='jobtology-requirement-graph-neo-'+uuid.uuid4().hex[:10]
    neo_fixture.NEO=neo_name
    spec=importlib.util.spec_from_file_location('requirement_validator',run.ROOT/'ontology/tools/validate.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    JT=Namespace('urn:jobtology:vocab:1:')
    try:
        # Add one complete, separate synthetic source snapshot; never mutate the
        # already pinned snapshots exercised by the base review tests.
        job_run='requirements-nine-job';posting='010';release='requirements-nine-release'
        ncs=sql("SELECT entity_id FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id) WHERE m.release_id='review-after-link-rejection' AND kind='ncsCompetency' ORDER BY entity_id LIMIT 1")
        cases=[
            ('데이터베이스 설계 능력',dict(kind='SKILL',target_id=ncs,target_kind='NCSCompetencyUnit',proficiency_scheme_id=None,minimum_proficiency=None)),
            ('내과 전문의 자격',dict(kind='CREDENTIAL',target_id='urn:credential:internal-medicine')),
            ('컴퓨터 또는 공학 전공 학사 이상, 졸업예정자 가능',dict(kind='EDUCATION',minimum_degree='BACHELOR',accepted_major_groups=['COMPUTING','ENGINEERING'],accepts_expected_graduate=True)),
            ('경력 2년 이상',dict(kind='EXPERIENCE',context_id=None,minimum_months=24,maximum_months=None)),
            ('한국어로 업무 수행 가능',dict(kind='LANGUAGE',target_id='urn:skill:korean',target_kind='Skill',proficiency_scheme_id=None,minimum_proficiency=None)),
            ('프로젝트 2개 이상 및 포트폴리오 제출',dict(kind='PROJECT',minimum_count=2,portfolio_required=True,capability_ids=[ncs])),
            ('서울 또는 부산 근무, 하이브리드',dict(kind='LOCATION',administrative_codes=['11','26'],work_mode='HYBRID')),
            ('장애인 우대',dict(kind='ELIGIBILITY',vocabulary_id='urn:vocab:eligibility',code='DISABILITY',source_text='장애인 우대')),
            ('2026년 10월 1일부터 주 5일 근무 가능',dict(kind='AVAILABILITY',earliest_start='2026-10-01',schedule_text='주 5일'))]
        source=run.fixture()['job_alio'][1]|dict(posting_id=posting,title='조건 검증용 채용',eligibility_text='\n'.join(text for text,_ in cases),education='')
        sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) VALUES({q(job_run)},'job_alio','FULL','fixture','READY',now(),now()); INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(job_run)},'all','FILE',1)")
        sql(f"INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) VALUES({q(job_run)},'doc','all',1,'nine.json',repeat('b',64),1,'UTF-8',200,now(),true,now())")
        for representation in ['list','detail']:
            row=source|dict(representation=representation)
            sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(job_run)},'doc',{q(representation)},{q(posting+':'+representation)},{js(row)},{js(row)})")
        body=json.loads(sql(f"SELECT enrichment.source_fields(normalized) FROM ingestion.job_posting WHERE run_id={q(job_run)} AND posting_id={q(posting)}"))
        raw=dict(positions=[dict(id='p1',name=source['title'],evidence_ids=['title:1'])],duties=[],duties_status='not_stated',requirements=[])
        for i,(text,c) in enumerate(cases,1):
            raw['requirements'].append(dict(position_ids=['p1'],category='other',kind='preference' if c['kind']=='ELIGIBILITY' else 'eligibility',
                logic='single',evidence_ids=['eligibility_text:'+str(i)],text_parts=[text],expression=[]))
        assert sql('SELECT enrichment.schema_issues_v6('+js(raw)+",output_schema) FROM enrichment.prompt WHERE version='ko-v4' AND stage='extract'")=='[]'
        bid='requirements-nine-extraction'
        sql(f"INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state) VALUES({q(bid)},'ENRICH',{q(job_run)},'fixture-ncs_competency','fixture','{{\"prompt_version\":\"ko-v4\",\"acceptance_policy\":\"REVIEW\"}}','COMPLETE')")
        sql(f"INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,extraction_id) VALUES({q(bid)},{q(bid)},{q(posting)},{js(body)},enrichment.hash({js(body)}::text),1,{q(bid+'-attempt')})")
        sql(f"INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state,raw_output,parsed_output,issues) VALUES({q(bid+'-attempt')},{q(bid)},{q(bid)},'extract','fixture','{{}}','VALIDATED',{js(raw)},enrichment.hydrate_v4({js(raw)},{js(body)}),'[]')")
        revision=claims.capture(bid);claims.decide(revision)
        sql(f"SELECT ontology.prepare_release({q(release)},'{{\"ncs_competency\":\"fixture-ncs_competency\"}}'); SELECT ontology.assemble_sources({q(release)})")
        # Explicit synthetic editorial definitions, already used by target tests.
        sql(f"INSERT INTO ontology.release_revision SELECT {q(release)},m.entity_id,m.revision_id FROM ontology.release_revision m WHERE m.release_id='review-after-link-rejection' AND m.entity_id NOT LIKE 'urn:jobtology:%' ON CONFLICT DO NOTHING")
        assert sql(f"SELECT count(*) FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id) WHERE release_id={q(release)} AND e.kind='jobPosting'")=='1'
        claims.assemble(release)
        for index,(text,condition) in enumerate(cases):
            atom=json.loads(sql(f"SELECT to_jsonb(a) FROM ontology.requirement_atom a WHERE release_id={q(release)} AND source_text={q(text)}"))
            document=dict(schema_version='hop-requirement-normalization-v1',release_id=release,source_claim_id=atom['source_claim_id'],node_index=atom['node_index'],parent_id=None,
                actor='nine-fixture-author',reason='Synthetic source meaning matches this condition.',resolver_version='synthetic-manual-v1',
                necessity='PREFERRED' if condition['kind']=='ELIGIBILITY' else 'REQUIRED',polarity='POSITIVE',condition=condition)
            nid=sql('SELECT ontology.capture_requirement_v1('+js(document)+')')
            kind='human' if index%2==0 else 'assistant'
            sql('SELECT ontology.decide_requirement_v1('+q(nid)+",'ACCEPT','nine-fixture-reviewer',"+q(kind)+",'Synthetic semantics independently checked')")
        native.run('freeze_requirements.hwf',dict(RELEASE_ID=release),'nine-condition-native-freeze')
        requests=sql('SELECT count(*) FROM enrichment.attempt')
        assert sql(f"SELECT count(*) FROM ontology.typed_requirement WHERE release_id={q(release)}")=='9'
        neo_fixture.boot_neo()
        neo_fixture.neo("CREATE (:Person {id:'private-fixture-person',name:'Private test'})")
        config=dict(name='jobtology-neo4j',server=neo_name,databaseName='neo4j',boltPort='7687',username='neo4j',password='test-auth-disabled',
            automatic=False,routing=False,usingEncryption=False,manualUrls=['bolt://'+neo_name+':7687'],connectionTimeout='10000',maxTransactionRetryTime='0')
        connection=native.WORK/'project/metadata/neo4j-connection/jobtology-neo4j.json';connection.parent.mkdir(exist_ok=True);connection.write_text(json.dumps(config))
        run.cmd(['docker','exec','-u','root',native.HOP,'mkdir','-p',native.REMOTE+'/project/metadata/neo4j-connection'])
        run.cmd(['docker','cp',str(connection),native.HOP+':'+native.REMOTE+'/project/metadata/neo4j-connection/jobtology-neo4j.json'])
        native.run('load_release.hwf',dict(RELEASE_ID=release),'nine-condition-native-graph')
        assert neo_fixture.neo("MATCH (n:normalizedRequirementClaim) RETURN count(n)=9 AND count(DISTINCT n.requirement_kind)=9 AND all(x IN collect(n) WHERE x.confidence IS NULL AND x.confidence_state='UNASSESSED') AS verified").splitlines()[-1].lower()=='true'
        assert neo_fixture.neo("MATCH (n:typedCondition {kind:'AVAILABILITY'}) RETURN n.earliest_start=date('2026-10-01') AS verified").splitlines()[-1].lower()=='true'
        assert neo_fixture.neo("MATCH (n:normalizedRequirementClaim {requirement_kind:'LANGUAGE'})-[:TARGETS]->(s:skill), (n)-[:USES_TARGET_BINDING]->(b:requirementTargetBinding)-[:SELECTS_REVISION]->(v:skillRevision) RETURN b.target_subkind='LANGUAGE' AND b.entity_id=s.entity_id AND v.entity_id=s.entity_id AS verified").splitlines()[-1].lower()=='true'
        sealed=sql('SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='+q(release))
        native.run('load_release.hwf',dict(RELEASE_ID=release),'nine-condition-native-graph-replay')
        assert sealed==sql('SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='+q(release))
        # Both earlier contracts reject new classes rather than silently omit them.
        for version in [1,2]:err(f"SELECT ontology.interchange_check_v{version}({q(release)},true)",'INTERCHANGE_UNMAPPED_NODE_LABEL')
        native.run('export_jsonld_v3.hwf',dict(RELEASE_ID=release,PREVIEW='Y'),'nine-condition-native-v3-export')
        run.cmd(['docker','cp',native.HOP+':'+native.REMOTE+'/project/data/ontology-exports',str(native.WORK/'exports')])
        export=next((native.WORK/'exports').glob('*.jsonld'))
        rdf,_,manifest=validator.load(export)
        assert manifest==json.loads(sql('SELECT manifest FROM ontology.corpus_release WHERE release_id='+q(release)),parse_float=Decimal)
        mapping=json.loads((run.ROOT/'ontology/versions/hop-v3/mappings/hop-v3.json').read_text())
        for n in json.loads(sql('SELECT jsonb_agg(n ORDER BY node_id) FROM ontology.graph_node n WHERE release_id='+q(release)),parse_float=Decimal):
            owner=next(s for s in rdf.subjects(JT.nativeNodeId,None) if str(rdf.value(s,JT.nativeNodeId))==n['node_id'])
            assert validator.native_properties(rdf,owner,mapping)==n['properties']
        from rdflib import URIRef,Literal
        for e in json.loads(sql('SELECT jsonb_agg(e ORDER BY edge_id) FROM ontology.graph_edge e WHERE release_id='+q(release)),parse_float=Decimal):
            owner=URIRef('urn:jobtology:edge:'+e['edge_id'])
            assert validator.native_properties(rdf,owner,mapping)==e['properties']
            for term,key in [(JT.nativeSubjectId,'subject_id'),(JT.nativePredicate,'predicate'),(JT.nativeObjectId,'object_id')]:assert str(rdf.value(owner,term))==e[key]
        # Typed aliases are not native hash fields; validate them independently.
        bad=json.loads(export.read_text())
        row=next(r for r in bad['@graph'] if 'earliestStart' in r)
        row['earliestStart']['@value']='2027-01-01'
        bad_file=native.WORK/'wrong-date-alias.jsonld';bad_file.write_text(json.dumps(bad,ensure_ascii=False))
        try:validator.load(bad_file);raise RuntimeError('Invalid date alias was accepted')
        except AssertionError as e:assert 'Date alias mismatch' in str(e),str(e)
        # Exercise semantic key reconstruction separately from generic hash checks.
        import runpy
        verify=runpy.run_path(str(run.ROOT/'ontology/tools/validate_requirements.py'))['verify']
        proposal=next(rdf.subjects(RDF.type,JT.RequirementNormalization));old_key=rdf.value(proposal,JT.requirementKey)
        rdf.set((proposal,JT.requirementKey,Literal('f'*64)))
        try:verify(rdf,release,manifest,mapping,validator.native_properties,validator.native_hash,JT,RDF);raise RuntimeError('Wrong requirement key was accepted')
        except AssertionError as e:assert 'Canonical requirement key mismatch' in str(e),str(e)
        rdf.set((proposal,JT.requirementKey,old_key))
        structure,_,details=validator.check(export);assert structure['conforms'],details
        publication,_,_=validator.check(export,True);assert not publication['conforms']
        assert len(set(rdf.subjects(RDF.type,JT.RequirementClaim)))==9 and len(set(rdf.subjects(RDF.type,JT.SourceRequirementGroup)))==9
        # Original alternative/guarded groups and unresolved proposals also export.
        pending='review-after-link-rejection'
        native.run('load_release.hwf',dict(RELEASE_ID=pending),'mixed-outcome-native-graph')
        native.run('export_jsonld_v3.hwf',dict(RELEASE_ID=pending,PREVIEW='Y'),'mixed-outcome-native-v3-export')
        run.cmd(['docker','cp',native.HOP+':'+native.REMOTE+'/project/data/ontology-exports',str(native.WORK/'exports-after')])
        pending_file=next(p for p in (native.WORK/'exports-after').glob('*.jsonld') if p.name!=export.name)
        pending_rdf,_,pending_manifest=validator.load(pending_file)
        pending_report,_,details=validator.check(pending_file);assert pending_report['conforms'],details
        assert pending_manifest['requirement_projection']['atoms']==6 and pending_manifest['requirement_projection']['reviewed_claims']==2
        assert len(set(pending_rdf.subjects(RDF.type,JT.UnresolvedCondition)))==1
        # A target outside the selected release stays a reference with an explicit
        # mismatch outcome. It must not pull in a revision from another release.
        stale='review-new-ncs'
        sql('SELECT ontology.seal_graph('+q(stale)+')')
        assert sql("SELECT count(*) FROM ontology.graph_edge WHERE release_id="+q(stale)+" AND predicate='SELECTS_REVISION' AND subject_id LIKE 'requirement-binding/%'")=='0'
        stale_file=native.WORK/'target-mismatch-v3.jsonld'
        stale_file.write_text(sql('SELECT string_agg(line,E\'\\n\' ORDER BY line_no) FROM ontology.export_jsonld_v3('+q(stale)+',true)')+'\n')
        _,_,stale_manifest=validator.load(stale_file)
        stale_report,_,details=validator.check(stale_file);assert stale_report['conforms'],details
        assert stale_manifest['requirement_projection']['reviewed_claims']==0
        err("BEGIN; ALTER TABLE ontology.requirement_membership DISABLE TRIGGER USER; UPDATE ontology.requirement_membership SET manifest_hash=repeat('f',64) WHERE release_id="+q(release)+"; SELECT ontology.seal_graph("+q(release)+"); COMMIT;",'REQUIREMENT_MEMBERSHIP_CHANGED')
        assert neo_fixture.neo("MATCH (p:Person {id:'private-fixture-person'}) RETURN p.name='Private test' AS verified").splitlines()[-1].lower()=='true'
        assert sql('SELECT count(*) FROM enrichment.attempt')==requests
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        report=dict(nine_kind_fixture=structure,mixed_outcomes=pending_report,target_mismatch=stale_report,publication_conforms=False,provider_calls=0,private_person_preserved=True)
        (native.WORK/'requirement-graph-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print('TYPED REQUIREMENT GRAPH AND V3 CHECKS PASSED',native.WORK,flush=True)
    finally:subprocess.run(['docker','rm','-fv',neo_name],capture_output=True)

if __name__=='__main__':requirements.main(check)
