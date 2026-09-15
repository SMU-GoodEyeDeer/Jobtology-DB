"""Native document-to-claim-to-graph fixtures. No production data or inference.

Run against the initialized disposable ontologytest fixture. Adds unique fixtures;
does not reset databases or discard earlier saved-real-data tests.
"""
import hashlib
import json
import os
import unicodedata
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
import native
from graph import NEO, boot_neo, neo
from run import ROOT, cmd, sql, q, js, expect_error


def digest(release):
    return sql(f"SELECT ontology.hash(jsonb_build_object('inputs',s.manifest,'claims',"
        f"(SELECT jsonb_agg(p ORDER BY entity_id) FROM ontology.posting_selection p WHERE release_id={q(release)}),"
        f"'artifacts',(SELECT jsonb_agg(d ORDER BY artifact_id) FROM ontology.artifact_document d WHERE release_id={q(release)}),"
        f"'sections',(SELECT jsonb_agg(d ORDER BY artifact_id,section_index) FROM ontology.document_section d WHERE release_id={q(release)}))) "
        f"FROM ontology.document_input_set s WHERE release_id={q(release)}")


def main():
    version=os.environ.get('ONTOLOGY_DOCUMENT_PROMPT_VERSION','ko-v6')
    assert version in ['ko-v6','ko-v7']
    boot_neo()
    native.stage(neo=NEO)
    old_seals = sql("SELECT coalesce(jsonb_object_agg(release_id,manifest_hash),'{}') FROM ontology.corpus_release WHERE manifest IS NOT NULL")
    if version=='ko-v7':native.run('../llm/install.hwf', {}, 'document-v7-llm-install')
    native.run('install.hwf', {}, 'document-native-install')
    assert old_seals == sql("SELECT coalesce(jsonb_object_agg(release_id,manifest_hash),'{}') FROM ontology.corpus_release WHERE manifest IS NOT NULL")
    assert sql("SELECT count(*) FROM ontology.corpus_release r WHERE manifest IS NOT NULL AND manifest IS DISTINCT FROM ontology.graph_inventory_manifest(release_id)") == '0'
    name = 'document-claims-' + uuid.uuid4().hex[:10]
    jobs = name + '-jobs'
    release = name + '-release'
    sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES({q(jobs)},'job_alio','FULL','fixture','READY');"
        f"INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(jobs)},'all','FILE',1);"
        f"INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) "
        f"VALUES({q(jobs)},'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,now(),true,now())")
    # Two accepted document formats, then pending, rejected and EVAL-only inputs.
    for posting in ['901', '902', '903', '904', '905']:
        ext = 'hwpx' if posting == '902' else 'pdf'
        metadata = dict(recrutAtchFileNo=posting, atchFileNm='시험 공고.'+ext, atchFileType='A',
            url='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+posting)
        for representation in ['list', 'detail']:
            normalized = dict(posting_id=posting, representation=representation, title='개발자 채용', organization_name='문서 시험기관')
            sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES"
                f"({q(jobs)},'doc',{q(posting+representation)},{q(posting+':'+representation)},{js(dict(files=[metadata]))},{js(normalized)})")
    rawroot = native.REMOTE + '/document-fixture-raw/' + name
    cmd(['docker','exec',native.HOP,'mkdir','-p',rawroot])
    sql(f'SELECT attachment.prepare({q(name)},{q(jobs)},\'\',{q(rawroot)},10)')
    # Unicode normalization must preserve offsets after emoji and decomposed text.
    pdf_pages = ['😀 한 개발자\r\n데이터베이스 설계 및 구축', '의사면허증 소지자']
    xml = '<html xmlns="http://www.w3.org/1999/xhtml"><body>' + ''.join(
        '<div class="page"><p>'+escape(p).replace('\r','&#13;')+'</p></div>' for p in pdf_pages) + '</body></html>'
    hp='http://www.hancom.co.kr/hwpml/2011/paragraph'
    hs='http://www.hancom.co.kr/hwpml/2011/section'
    opf='http://www.idpf.org/2007/opf/'
    paragraph=lambda text:f'<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
    cell=lambda text:f'<hp:tc header="1"><hp:subList>{text}</hp:subList><hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="2"/></hp:tc>'
    inner='<hp:tbl rowCnt="1" colCnt="2"><hp:tr>'+cell(paragraph('데이터베이스 설계 및 구축'))+'</hp:tr></hp:tbl>'
    outer='<hp:tbl rowCnt="1" colCnt="2"><hp:tr>'+cell(paragraph('의사면허증 소지자')+'<hp:p><hp:run>'+inner+'</hp:run></hp:p>')+'</hp:tr></hp:tbl>'
    members={'Contents/content.hpf': f'<opf:package xmlns:opf="{opf}"><opf:manifest><opf:item id="s" href="Contents/section0.xml"/></opf:manifest><opf:spine><opf:itemref idref="s"/></opf:spine></opf:package>',
        'Contents/section0.xml':f'<hs:sec xmlns:hs="{hs}" xmlns:hp="{hp}"><hp:p><hp:run>{outer}</hp:run></hp:p></hs:sec>'}
    archive=native.WORK/'fixture.hwpx'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path,body in members.items(): z.writestr(path,body)
    for posting in ['901','902','903','904','905']:
        document=sql(f'SELECT document_id FROM attachment.document WHERE batch_id={q(name)} AND posting_id={q(posting)}')
        attempt=sql('SELECT attachment.reserve('+q(document)+')')
        if posting=='902':
            path=sql(f'SELECT raw_path FROM attachment.attempt WHERE attempt_id={q(attempt)}')
            cmd(['docker','cp',str(archive),native.HOP+':'+path])
            raw=archive.read_bytes()
            sql(f'SELECT attachment.archive({q(attempt)},200,NULL,{q(hashlib.sha256(raw).hexdigest())},{len(raw)},NULL);SELECT attachment.finish_attempt({q(attempt)},false,1)')
        else:
            sql(f"SELECT attachment.archive({q(attempt)},200,NULL,repeat('a',64),100,NULL);"
                f"SELECT attachment.save_parse({q(attempt)},{q(xml)},'{{\"Content-Type\":\"application/pdf\"}}',repeat('a',64));"
                f"SELECT attachment.finish_attempt({q(attempt)},true,0)")
    sql('SELECT attachment.verify_batch('+q(name)+')')
    native.run('../attachments/structure_hwpx.hwf',dict(BATCH_ID=name,JOB_RUN_ID=jobs,ATTACHMENT_BATCH_IDS=name,POSTING_IDS='',MAX_DOCUMENTS=10),'document-native-structure')
    assert sql(f"SELECT state FROM attachment.hwpx_structure WHERE batch_id={q(name)}")=='VERIFIED'
    bundles = {p:sql(f'SELECT attachment.prepare_structured_input({q(jobs)},{q(p)},ARRAY[{q(name)}],ARRAY[{q(name)}])') for p in ['901','902','903','904','905']}
    opts=dict(extract_model='fixture/model',categorize_model='fixture/model',prompt_version=version,extra_params={},limit=5,
        candidate_limit=40,max_matches=8,max_input_chars=200000,max_output_tokens=6000,max_requests=10,
        request_reserve_usd=.1,max_cost_usd=1,daily_budget_usd=20,request_delay_ms=0,read_timeout_ms=10000,
        execute_requests='N',reuse_cache='N',endpoint='https://fixture.invalid/chat/completions',acceptance_policy='REVIEW')
    def output(posting):
        source=json.loads(sql('SELECT source_data FROM enrichment.input_bundle WHERE bundle_id='+q(bundles[posting])))
        field='attachment_1_'+posting
        lines=json.loads(sql('SELECT enrichment.source_passages_v2('+js(source)+')'))
        evidence=lambda text:[p['id'] for p in lines if p['field']==field and text in p['text']]
        positions=[] if posting=='902' else [dict(id='p1',name='😀 한 개발자',evidence_ids=evidence('개발자'))]
        raw=dict(positions=positions,duties=[dict(position_ids=[],text_parts=['데이터베이스 설계 및 구축'],evidence_ids=evidence('데이터베이스'))],
            requirements=[dict(position_ids=[],category='qualification',kind='eligibility',logic='single',text_parts=['의사면허증 소지자'],evidence_ids=evidence('의사면허증'),condition=None)],
            duties_status='explicit',unhandled_passages=[])
        if version=='ko-v7':raw['unhandled_ranges']=raw.pop('unhandled_passages')
        assert json.loads(sql('SELECT enrichment.output_issues_'+version.replace('ko-','')+'('+js(raw)+','+js(source)+')'))==[],raw
        return raw,source
    def plan(suffix,postings,mode):
        batch=name+'-'+suffix
        dataset=batch+'-dataset'
        ids='ARRAY['+','.join(q(bundles[p]) for p in postings)+']'
        sql(f"SELECT enrichment.prepare_input_dataset({q(dataset)},'fixture-ncs_competency',{ids})")
        settings=opts|dict(input_bundle_ids='|'.join(bundles[p] for p in postings)) if mode=='ENRICH' else opts
        sql(f"SELECT enrichment.plan_batch({q(batch)},{q(mode)},{q(dataset)},{q(jobs)},'fixture-ncs_competency',{js(settings)});SELECT enrichment.plan_stage({q(batch)},'extract')")
        return batch
    batch=plan('enrich',['901','902','903','904'],'ENRICH')
    revisions={}
    for posting in ['901','902','903','904']:
        item=sql(f'SELECT item_id FROM enrichment.item WHERE batch_id={q(batch)} AND posting_id={q(posting)}')
        raw,_=output(posting)
        revisions[posting]=sql(f"SELECT enrichment.capture_extraction({q(item)},'synthetic fixture','Document evidence integration only',{js(raw)})")
        if posting!='903':
            decision='REJECT' if posting=='904' else 'ACCEPT'
            sql(f"SELECT enrichment.decide_extraction({q(revisions[posting])},{q(decision)},'synthetic fixture','assistant','Synthetic source evidence only')")
    eval_batch=plan('eval',['905'],'EVAL')
    item=sql('SELECT item_id FROM enrichment.item WHERE batch_id='+q(eval_batch))
    expect_error(f"SELECT enrichment.capture_extraction({q(item)},'fixture','Never accept EVAL',{js(output('905')[0])})",'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW')
    params=dict(RELEASE_ID=release,ALIO_RUN_ID='fixture-alio_organization',JOB_RUN_ID=jobs,NCS_RUN_ID='fixture-ncs_competency',
        QUALIFICATION_RUN_ID='fixture-ncs_qualification',QNET_RUN_ID='fixture-qnet_schedule',CAREER_RUN_ID='fixture-ncs_career_path')
    native.run('prepare_release.hwf',params,'document-native-prepare')
    ids='|'.join(bundles.values())
    expect_error(f'SELECT ontology.bind_document_inputs({q(release)},ARRAY[{q(bundles["901"])}])','COMPLETE_POSTING_INPUT_SET_REQUIRED')
    assert sql('SELECT count(*) FROM ontology.document_input_set WHERE release_id='+q(release))=='0'
    native.run('bind_document_inputs.hwf',dict(RELEASE_ID=release,INPUT_BUNDLE_IDS=ids),'document-native-bind')
    native.run('bind_document_inputs.hwf',dict(RELEASE_ID=release,INPUT_BUNDLE_IDS=ids),'document-native-bind-replay')
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID=release),'document-native-claims')
    outcomes=json.loads(sql(f"SELECT jsonb_object_agg(b.posting_id,p.outcome) FROM ontology.posting_selection p JOIN ontology.document_input d USING(release_id,entity_id) JOIN enrichment.input_bundle b USING(bundle_id) WHERE p.release_id={q(release)}"))
    assert outcomes==dict(zip(['901','902','903','904','905'],['ACCEPTED','ACCEPTED','REVIEW_REQUIRED','REJECTED','NOT_PROCESSED'])),outcomes
    before=digest(release)
    native.run('assemble_reviewed.hwf',dict(RELEASE_ID=release),'document-native-claim-replay')
    assert digest(release)==before
    artifacts=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('artifact_id',d.artifact_id,'descriptor',d.descriptor,'bundle',b.source_data,'text',a.normalized_text,'field',a.source_field,'entity',a.posting_id,'attempt',d.attempt_id)) FROM ontology.artifact_document d JOIN ontology.text_artifact a USING(artifact_id) JOIN enrichment.input_bundle b USING(bundle_id) WHERE d.release_id={q(release)}"))
    assert len(artifacts)==2
    for a in artifacts:
        original=a['bundle'][a['field']]
        normalize=lambda t:unicodedata.normalize('NFC',t.replace('\r\n','\n').replace('\r','\n'))
        assert a['text']==normalize(original)
        sections=json.loads(sql(f'SELECT jsonb_agg(s ORDER BY section_index) FROM ontology.document_section s WHERE release_id={q(release)} AND artifact_id={q(a["artifact_id"])}'))
        assert len(sections)==len(a['descriptor']['sections'])
        for s,expected in zip(sections,a['descriptor']['sections']):
            excerpt=original[expected['start']:expected['end']]
            assert s['source_locator']==expected and hashlib.sha256(excerpt.encode()).hexdigest()==expected['content_hash']
            assert a['text'][s['normalized_start']:s['normalized_end']]==normalize(excerpt)
        spans=json.loads(sql(f'SELECT jsonb_agg(e) FROM ontology.release_evidence r JOIN ontology.evidence_span e USING(evidence_id) WHERE r.release_id={q(release)} AND artifact_id={q(a["artifact_id"])}'))
        for e in spans:
            assert a['text'][e['start_offset']:e['end_offset']]==e['excerpt']
            assert hashlib.sha256(e['excerpt'].encode()).hexdigest()==e['excerpt_sha256']
    pdf=next(a for a in artifacts if a['field'].endswith('901'))
    assert '\r\n' in pdf['bundle'][pdf['field']] and '한' in pdf['bundle'][pdf['field']] and '😀 한' in pdf['text']
    # Fault injection is transactional, restricted to this disposable fixture.
    for table,assignment,error in [
        ('artifact_document',"file_ordinal=999",'ONTOLOGY_DOCUMENT_EVIDENCE_MISMATCH'),
        ('artifact_document',"entity_id=(SELECT entity_id FROM ontology.document_input WHERE release_id="+q(release)+" AND bundle_id="+q(bundles['903'])+")",'ONTOLOGY_DOCUMENT_EVIDENCE_MISMATCH'),
        ('document_section','normalized_start=normalized_start+1','ONTOLOGY_DOCUMENT_SECTION_MISMATCH')]:
        expect_error(f'BEGIN;ALTER TABLE ontology.{table} DISABLE TRIGGER USER;UPDATE ontology.{table} SET {assignment} WHERE release_id={q(release)} AND artifact_id={q(pdf["artifact_id"])};SELECT ontology.verify_claims({q(release)});ROLLBACK;',error)
    expect_error(f"UPDATE ontology.document_input SET bundle_id=bundle_id WHERE release_id={q(release)}",'IMMUTABLE_ONTOLOGY_DOCUMENT_INPUT')
    native.run('load_release.hwf',dict(RELEASE_ID=release),'document-native-graph')
    manifest=json.loads(sql('SELECT manifest FROM ontology.corpus_release WHERE release_id='+q(release)))
    assert len(manifest['document_input_set']['manifest'])==5
    # Independent graph traversal checks the actual source-response endpoints.
    query=f"MATCH (:corpusRelease {{release_id:{json.dumps(release)}}})-[:INCLUDES {{release_id:{json.dumps(release)}}}]->(c:requirementClaim)-[:EVIDENCED_BY {{release_id:{json.dumps(release)}}}]->(e:evidenceSpan)-[:IN_ARTIFACT {{release_id:{json.dumps(release)}}}]->(:textArtifact)-[:DERIVED_FROM {{release_id:{json.dumps(release)}}}]->(a:sourceAttachment)-[:DECLARED_IN {{release_id:{json.dumps(release)}}}]->(r:sourceRecordEvidence) RETURN count(*)=2 AND all(v IN collect(r.source_record_id) WHERE v IN ['901:detail','902:detail']) AS verified"
    assert neo(query).splitlines()[-1].lower()=='true'
    scoped=f"{{release_id:{json.dumps(release)}}}"
    assert neo(f"MATCH (:corpusRelease {scoped})-[:INCLUDES {scoped}]->(c:documentCell) RETURN count(*)=2 AND all(x IN collect(c.col_span) WHERE x=2) AS verified").splitlines()[-1].lower()=='true'
    assert neo(f"MATCH (:documentTable)-[e:NESTED_IN_CELL {scoped}]->(:documentCell) RETURN count(*)=1 AS verified").splitlines()[-1].lower()=='true'
    assert neo(f"MATCH (:evidenceSpan)-[e:OVERLAPS_SECTION {scoped}]->(:documentSection)-[:IN_CELL {scoped}]->(:documentCell) RETURN count(DISTINCT e)=2 AS verified").splitlines()[-1].lower()=='true'
    graph_before=neo(f"MATCH (:corpusRelease {scoped})-[e:INCLUDES]->(n) RETURN count(n),count(e)")
    native.run('load_release.hwf',dict(RELEASE_ID=release),'document-native-graph-replay')
    assert graph_before==neo(f"MATCH (:corpusRelease {scoped})-[e:INCLUDES]->(n) RETURN count(n),count(e)")
    assert manifest==json.loads(sql('SELECT manifest FROM ontology.corpus_release WHERE release_id='+q(release)))
    assert sql(f"SELECT state='PREPARING' AND graph_verified_at IS NOT NULL FROM ontology.corpus_release WHERE release_id={q(release)}")=='t'
    assert sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id IN ({q(batch)},{q(eval_batch)}) AND reserved_at IS NOT NULL")=='0'
    assert sql('SELECT count(*) FROM ontology.active_release')=='0'
    result=dict(release_id=release,job_run_id=jobs,bundle_ids=bundles,outcomes=outcomes,manifest=manifest)
    (native.WORK/'document-evidence-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('DOCUMENT EVIDENCE CHECKS PASSED',native.WORK,flush=True)


if __name__=='__main__':main()
