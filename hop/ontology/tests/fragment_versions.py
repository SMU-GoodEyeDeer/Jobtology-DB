"""Native canonical assembly/readback of reviewed v5/v6 fragments, no inference."""
import copy
import json
from run import boot, fixture, load_sources, sql, js, q, expect_error
import native
import graph


def check():
    boot()
    records=fixture(); jobs=[]
    for version in ('ko-v5','ko-v6'):
        for src in records['job_alio']:
            jobs.append(src|dict(posting_id=version,title='데이터 엔지니어 채용',education='학력무관',
                eligibility_text='담당 업무: 데이터베이스 설계 및 구축\n필수: SQL 자격증 또는 데이터 자격증 중 하나',
                preference_text='장애인 우대(단, 필수지원자격 미충족 시 제외)'))
    records['job_alio']=jobs;load_sources(records)
    raw=dict(positions=[dict(id='p1',name='데이터 엔지니어',evidence_ids=['title:1'])],
        duties=[dict(position_ids=['p1'],text_parts=['데이터베이스 설계 및 구축'],evidence_ids=['eligibility_text:1'])],
        requirements=[dict(position_ids=['p1'],category='qualification',kind='eligibility',logic='any_of',
            text_parts=['SQL 자격증 또는 데이터 자격증 중 하나'],evidence_ids=['eligibility_text:2'],expression=[
                dict(op='any_of',parts=[],children=[1,2]),dict(op='atom',parts=['SQL 자격증'],children=[]),dict(op='atom',parts=['데이터 자격증'],children=[])]),
            dict(position_ids=['p1'],category='other',kind='preference',logic='conditional',
            text_parts=['장애인 우대(단, 필수지원자격 미충족 시 제외)'],evidence_ids=['preference_text:1'],expression=[
                dict(op='except',parts=[],children=[1,2]),dict(op='atom',parts=['장애인 우대'],children=[]),dict(op='atom',parts=['필수지원자격 미충족 시 제외'],children=[])])],
        duties_status='explicit')
    expected={}
    for version in ('ko-v5','ko-v6'):
        output=copy.deepcopy(raw)
        if version=='ko-v6':
            for r in output['requirements']:
                nodes=r.pop('expression')
                def nested(index):
                    return dict(op=nodes[index]['op'],parts=nodes[index]['parts'],children=[nested(c) for c in nodes[index]['children']])
                r['condition']=nested(0)
            output['unhandled_passages']=[]
        source=json.loads(sql(f"SELECT enrichment.source_fields(normalized) FROM ingestion.job_posting WHERE posting_id={q(version)}"))
        validator='v5' if version=='ko-v5' else 'v6'
        assert sql(f'SELECT enrichment.output_issues_{validator}({js(output)},{js(source)})')=='[]'
        sql(f"""INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state)
VALUES({q(version)},'ENRICH','fixture-job_alio','fixture-ncs_competency','fixture',jsonb_build_object('prompt_version',{q(version)},'acceptance_policy','REVIEW'),'COMPLETE');
INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,extraction_id)
VALUES({q(version)},{q(version)},{q(version)},{js(source)},enrichment.hash({js(source)}::text),1,{q(version+'-extract')});
INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state,raw_output,parsed_output)
VALUES({q(version+'-extract')},{q(version)},{q(version)},'extract','fixture','{{}}','VALIDATED',{js(output)},enrichment.hydrate_{validator}({js(output)},{js(source)}));""")
        rid=sql(f"SELECT enrichment.capture_extraction({q(version)},'fixture','Source-verified synthetic fixture')")
        sql(f"SELECT enrichment.decide_extraction({q(rid)},'ACCEPT','fixture','assistant','Synthetic source and expression reviewed')")
        expected[version]=json.loads(sql(f'SELECT extraction FROM enrichment.extraction_revision WHERE revision_id={q(rid)}'))
    graph.boot_neo();native.stage(neo=graph.NEO);graph.clear_fixture_graph()
    native.run('install.hwf',{},'fragment-version-native-installer')
    native.run('prepare_release.hwf',dict(RELEASE_ID='fragment-versions'),'fragment-version-source-assembly')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='fragment-versions'),'fragment-version-reviewed-assembly')
    before=sql("SELECT jsonb_agg(c.payload ORDER BY c.posting_revision_id,c.kind,c.ordinal) FROM ontology.claim c")
    for version,extraction in expected.items():
        for section,kind in [('duties','DUTY'),('requirements','REQUIREMENT')]:
            stored=json.loads(sql(f"SELECT jsonb_agg(c.payload ORDER BY ordinal) FROM ontology.claim c JOIN ontology.revision v ON v.revision_id=c.posting_revision_id WHERE v.payload->>'posting_id'={q(version)} AND c.kind={q(kind)}"))
            assert stored==extraction[section],(version,section)
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID='fragment-versions'),'fragment-version-reviewed-replay')
    assert before==sql("SELECT jsonb_agg(c.payload ORDER BY c.posting_revision_id,c.kind,c.ordinal) FROM ontology.claim c")
    native.run('load_release.hwf',dict(RELEASE_ID='fragment-versions'),'fragment-version-graph-load')
    assert graph.neo("MATCH (r:jobPostingRevision) WHERE r.posting_id IN ['ko-v5','ko-v6'] RETURN count(r)").splitlines()[-1]=='2'
    assert graph.neo("MATCH (n:conditionExpression) RETURN count(n)").splitlines()[-1]=='12'
    assert sql("SELECT state='PREPARING' AND graph_verified_at IS NOT NULL FROM ontology.corpus_release WHERE release_id='fragment-versions'")=='t'
    print('NATIVE V5/V6 ONTOLOGY FRAGMENT CHECKS PASSED',native.WORK,flush=True)


if __name__=='__main__': check()
