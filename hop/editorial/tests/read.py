"""Native v2 corpus reads with exact editorial/source evidence; no live services."""
import base64
import hashlib
import json
from pathlib import Path
import catalogue
import run

def check(native):
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    read=lambda expression:json.loads(sql('SELECT '+expression))
    scheme='urn:jobtology:conceptScheme:product-occupations'
    ncs_scheme='urn:jobtology:conceptScheme:ncs'
    entity='urn:jobtology:occupation:product:AI_ENGINEER'
    sql("SELECT ontology.prepare_release('editorial-read-unpinned'); SELECT ontology.assemble_sources('editorial-read-unpinned')")
    def fingerprint():
        tables=['editorial.snapshot','editorial.item','editorial.review','editorial.release_pin','editorial.revision_support',
                'ontology.entity','ontology.revision','ontology.release_revision','ontology.revision_support',
                'ontology.source_pin','ontology.input_record','ontology.corpus_release',
                'enrichment.batch','enrichment.item','enrichment.attempt','attachment.attempt']
        parts=','.join(q(name)+', (SELECT ontology.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),\'[]\')) FROM '+name+' t)' for name in tables)
        return sql('SELECT ontology.hash(jsonb_build_object('+parts+'))')
    original=fingerprint()
    old=read('ontology.query_entity_v2(\'fixture-release\','+q(entity)+',true)')
    newer=read('ontology.query_entity_v2(\'editorial-next\','+q(entity)+',true)')
    assert old['contract_version']=='hop-ontology-read-v2' and old['read_mode']=='PREVIEW'
    assert old['entity']['entity_id']==newer['entity']['entity_id']
    assert old['entity']['revision_id']!=newer['entity']['revision_id']
    assert '인공지능 개발 엔지니어' not in old['entity']['payload']['aliases']
    assert '인공지능 개발 엔지니어' in newer['entity']['payload']['aliases']
    for name,detail in [('fixture-release',old),('editorial-next',newer)]:
        selected=detail['editorial_source'];support=detail['source_support']
        assert selected['selected_review']==read('(SELECT to_jsonb(r) FROM editorial.release_pin p JOIN editorial.review r USING(review_id) WHERE release_id='+q(name)+')')
        assert selected['attestation_kind']=='OPERATOR_REPORTED' and selected['repository_verification']=='NOT_AUTOMATICALLY_VERIFIED'
        assert len(support)==1 and support[0]['support_kind']=='EDITORIAL_ENTRY'
        assert support[0]['review_id']==selected['selected_review']['review_id']
        assert 'run_id' not in support[0] and 'record_id' not in support[0]
        record=read('ontology.query_source_record_v2('+q(name)+','+q(support[0]['support_id'])+',true)')['source_record']
        raw=record['source_text'].encode()
        assert hashlib.sha256(raw).hexdigest()==record['raw_sha256']==selected['snapshot_id']
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==record['git_blob_sha1']
        assert record['byte_length']==len(raw)
        assert record['source_entry']==json.loads(raw)['occupations'][0]
        assert record['normalized']==detail['entity']['payload']
        assert record['revision_id']==detail['entity']['revision_id']
        rel=detail['catalogue_relations'];assert len(rel)==1
        assert rel[0]['subject_revision_id']==detail['entity']['revision_id'] and rel[0]['object_id']==scheme
        assert rel[0]['support_id']==support[0]['support_id']
    # Pin keeps the original review even after subsequent decisions/version imports.
    assert old['editorial_source']['selected_review']['review_id']!=sql("SELECT review_id FROM editorial.review WHERE snapshot_id="+q(old['editorial_source']['snapshot_id'])+' ORDER BY review_no DESC LIMIT 1')
    summary=read("ontology.query_summary_v2('fixture-release',true)")
    assert len(summary['sources'])==7 and sum(s['source_kind']=='EDITORIAL_CATALOGUE' for s in summary['sources'])==1
    assert summary['editorial_coverage']==dict(source_id='INTERNAL_EDITORIAL',expected_entities=5,selected_entities=5,unaccounted_entities=0,status='VERIFIED_FROZEN_MEMBERSHIP')
    legacy_summary=read("ontology.query_summary_v1('fixture-release',true)")
    assert len(legacy_summary['sources'])==6
    for key in ['data_as_of','posting_review','accepted_claim_counts','accepted_mappings','source_coverage']:
        assert summary[key]==legacy_summary[key]
    unpinned=read("ontology.query_summary_v2('editorial-read-unpinned',true)")
    assert len(unpinned['sources'])==6 and unpinned['editorial_source'] is None and unpinned['editorial_coverage'] is None
    assert unpinned['editorial_selection_status']=='NOT_PINNED'
    err('SELECT ontology.query_entities_v2(\'editorial-read-unpinned\',\'occupation\','+q(scheme)+',2,NULL,true)','ONTOLOGY_SCHEME_NOT_IN_RELEASE')
    schema_detail=read('ontology.query_entity_v2(\'fixture-release\','+q(scheme)+',true)')
    assert len(schema_detail['catalogue_relations'])==4
    assert schema_detail['source_support'][0]['locator']=='/scheme'
    def page(release='fixture-release',kind='occupation',filter_scheme=scheme,size=2,cursor=None):
        return read('ontology.query_entities_v2('+q(release)+','+(q(kind) if kind is not None else 'NULL')+','+
                    (q(filter_scheme) if filter_scheme is not None else 'NULL')+','+str(size)+','+(q(cursor) if cursor else 'NULL')+',true)')
    first=page();rows=first['items'];cursor=first['next_cursor'];assert cursor
    second=page(cursor=cursor);rows+=second['items'];assert second['next_cursor'] is None
    assert len(rows)==len({r['entity_id'] for r in rows})==4
    assert all(r['scheme_id']==scheme and r['source_support_count']==1 for r in rows)
    assert {r['name'] for r in rows}=={'AI 엔지니어','백엔드 개발자','프론트엔드 개발자','데이터 분석가'}
    assert all('product:' not in r['entity_id'] for r in page(filter_scheme=ncs_scheme)['items'])
    for release,kind,filter_scheme in [('editorial-next','occupation',scheme),('fixture-release','ncsClass',scheme),('fixture-release','occupation',ncs_scheme)]:
        err('SELECT ontology.query_entities_v2('+q(release)+','+q(kind)+','+q(filter_scheme)+',2,'+q(cursor)+',true)','INVALID_ONTOLOGY_CURSOR')
    old_cursor=read("ontology.query_entities_v1('fixture-release','occupation',2,NULL,true)")['next_cursor']
    err('SELECT ontology.query_entities_v2(\'fixture-release\',\'occupation\','+q(scheme)+',2,'+q(old_cursor)+',true)','INVALID_ONTOLOGY_CURSOR')
    for bad in ['not-base64',base64.b64encode(b'{}').decode(),'a'*4100]:
        err('SELECT ontology.query_entities_v2(\'fixture-release\',NULL,NULL,2,'+q(bad)+',true)','INVALID_ONTOLOGY_CURSOR')
    err("SELECT ontology.query_entities_v2('fixture-release','Person',NULL,2,NULL,true)",'INVALID_ONTOLOGY_ENTITY_KIND')
    err("SELECT ontology.query_entities_v2('fixture-release',NULL,'urn:unknown:scheme',2,NULL,true)",'ONTOLOGY_SCHEME_NOT_IN_RELEASE')
    err("SELECT ontology.query_entities_v2('fixture-release',NULL,NULL,101,NULL,true)",'INVALID_ONTOLOGY_PAGE_SIZE')
    # A new editorial pin invalidates an earlier cursor even when the NCS rows
    # being paged did not change. Both writes are rolled back with the error.
    err("DO $$ DECLARE c text; BEGIN c:=ontology.query_entities_v2('editorial-read-unpinned','ncsCompetency',"+q(ncs_scheme)+",1,NULL,true)->>'next_cursor'; "
        "IF c IS NULL THEN RAISE EXCEPTION 'FIXTURE_CURSOR_REQUIRED'; END IF; "
        "PERFORM editorial.pin_v1('editorial-read-unpinned',"+q(newer['editorial_source']['snapshot_id'])+"); "
        "PERFORM ontology.query_entities_v2('editorial-read-unpinned','ncsCompetency',"+q(ncs_scheme)+",1,c,true); END $$",'INVALID_ONTOLOGY_CURSOR')
    err("BEGIN; INSERT INTO ontology.release_revision SELECT 'editorial-read-unpinned',entity_id,revision_id FROM editorial.item WHERE snapshot_id="+
        q(newer['editorial_source']['snapshot_id'])+"; SELECT ontology.query_summary_v2('editorial-read-unpinned',true); COMMIT",'EDITORIAL_RELEASE_MEMBERSHIP_REQUIRED')
    posting='urn:jobtology:jobPosting:job_alio:001'
    external=read('ontology.query_entity_v2(\'fixture-release\','+q(posting)+',true)')
    external_v1=read('ontology.query_entity_v1(\'fixture-release\','+q(posting)+',true)')
    for key in ['entity','relations','claims','positions','mappings','extraction']:assert external[key]==external_v1[key]
    assert len(external['source_support'])==len(external_v1['source_support'])>0
    for support in external['source_support']:
        assert support['support_kind']=='EXTERNAL_RECORD'
        source=read('ontology.query_source_record_v2(\'fixture-release\','+q(support['support_id'])+',true)')['source_record']
        expected=read('(SELECT normalized FROM ontology.input_record WHERE release_id=\'fixture-release\' AND record_id='+str(support['record_id'])+')')
        assert source['normalized']==expected and source['raw_sha256']==support['raw_sha256']
        assert any(x['record_id']==support['record_id'] for x in source['source_observations'])
        assert source['representation']=='FROZEN_NORMALIZED_RECORD_WITH_ORIGINAL_FILE_REFERENCE'
    err('SELECT ontology.query_source_record_v2(\'editorial-next\','+q(old['source_support'][0]['support_id'])+',true)','ONTOLOGY_SOURCE_RECORD_NOT_IN_RELEASE')
    for missing in ['', 'editorial-record/'+'f'*64, '../../secrets/openrouter.csv']:
        err('SELECT ontology.query_source_record_v2(\'fixture-release\','+q(missing)+',true)','ONTOLOGY_SOURCE_RECORD_NOT_IN_RELEASE')
    for query in ['ontology.query_summary_v2()',"ontology.query_entities_v2(NULL,NULL,NULL,2,NULL,true)"]:
        err('SELECT '+query,'NO_ACTIVE_ONTOLOGY_RELEASE')
    err('SELECT ontology.query_entity_v2(\'fixture-release\','+q(entity)+',false)','ONTOLOGY_RELEASE_NOT_PUBLISHED')
    err("SELECT ontology.query_summary_v2('fixture-release',NULL)",'INVALID_ONTOLOGY_READ_MODE')
    err("BEGIN; UPDATE ontology.corpus_release SET state='REVOKED' WHERE release_id='fixture-release'; SELECT ontology.query_summary_v2('fixture-release',true); COMMIT",'CORPUS_RELEASE_REVOKED')
    err("BEGIN; ALTER TABLE editorial.release_pin DISABLE TRIGGER USER; UPDATE editorial.release_pin SET manifest_hash=repeat('f',64) WHERE release_id='fixture-release'; SELECT ontology.query_summary_v2('fixture-release',true); COMMIT",'EDITORIAL_MEMBERSHIP_CHANGED')
    err("BEGIN; ALTER TABLE editorial.revision_support DISABLE TRIGGER USER; UPDATE editorial.revision_support SET source_pointer='/wrong' WHERE release_id='fixture-release'; SELECT ontology.query_entity_v2('fixture-release',"+q(entity)+",true); COMMIT",'EDITORIAL_REVISION_MEMBERSHIP_CHANGED')
    native.run('../editorial/read_summary_v2.hwf',dict(RELEASE_ID='fixture-release',PREVIEW='Y'),'native-editorial-summary-read')
    native.run('../editorial/read_entities_v2.hwf',dict(RELEASE_ID='fixture-release',PREVIEW='Y',ENTITY_KIND='occupation',SCHEME_ID=scheme,PAGE_SIZE=2),'native-editorial-role-list-read')
    native.run('../editorial/read_entity_v2.hwf',dict(RELEASE_ID='fixture-release',PREVIEW='Y',ENTITY_ID=entity),'native-editorial-entity-read')
    native.run('../editorial/read_source_record_v2.hwf',dict(RELEASE_ID='fixture-release',PREVIEW='Y',SUPPORT_ID=old['source_support'][0]['support_id']),'native-editorial-source-read')
    native.run('../editorial/read_summary_v2.hwf',dict(RELEASE_ID='fixture-release',PREVIEW='bad'),'native-editorial-invalid-read-mode',False)
    assert fingerprint()==original,'Read workflows changed source/review/release/provider data'
    report=dict(result='PASS',contract_version='hop-ontology-read-v2',catalogue_versions=2,product_occupations=4,
                source_kinds=['EXTERNAL_RECORD','EDITORIAL_ENTRY'],source_count=7,provider_calls=0,
                production_changes=False,read_fingerprint=original,native_log_directory=str(native.WORK))
    (native.WORK/'editorial-read-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('EDITORIAL V2 READ CHECKS PASSED',native.WORK,flush=True)

if __name__=='__main__':catalogue.main(check)
