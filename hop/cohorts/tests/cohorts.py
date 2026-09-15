"""Persisted cohort policy in disposable PG18/native Hop, using synthetic sources."""
from pathlib import Path
import copy
import hashlib
import json
import subprocess
import uuid
from datetime import date,timedelta

import profiles as fixture
run,native,claims=fixture.run,fixture.native,fixture.claims
sql,q,js,err,read=fixture.sql,fixture.q,fixture.js,fixture.err,fixture.read
ROOT=fixture.ROOT;BASE=fixture.BASE;POSTING=fixture.POSTING
ROLE='urn:jobtology:occupation:product:';AS_OF=date(2026,9,1);AT='2026-09-01T01:00:00Z'

def capture_catalogue():
    doc=json.loads((ROOT/'hop/editorial/catalogues/product-occupations.v1.yaml').read_text())
    doc.update(actor='fixture-catalogue-author',actor_kind='human')
    raw=(json.dumps(doc,ensure_ascii=False)+'\n').encode();sha=hashlib.sha256(raw).hexdigest()
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    sql('SELECT editorial.capture_v1(decode('+q(raw.hex())+",'hex'),"+q(sha)+','+q(blob)+')')
    sql('SELECT editorial.review_v1('+q(str(uuid.uuid4()))+','+q(sha)+",'ACCEPT','fixture-catalogue-reviewer','human',"
        "'Synthetic fixture only; no actual catalogue review or Git merge',"+q('1'*40)+",'fixture-only:main')")
    return sha

def prepare(name,sha):
    sql('SELECT ontology.prepare_release('+q(name)+'); UPDATE ontology.corpus_release SET created_at='+q(AT)+
        ' WHERE release_id='+q(name)+'; SELECT ontology.assemble_sources('+q(name)+'); SELECT ontology.bind_observations_v1('+q(name)+'); '
        'SELECT editorial.pin_v1('+q(name)+','+q(sha)+'); SELECT ontology.freeze_reviews('+q(name)+'); SELECT ontology.assemble_claims('+q(name)+')')

def source_fixtures():
    sources,raws=fixture.source_fixtures();base=[copy.deepcopy(r) for r in sources['job_alio'] if r['posting_id']=='001']
    body='채용 공고의 근무 조건과 지원 절차를 안내합니다. 자세한 사항을 확인하고 정해진 방법으로 지원해 주세요. '*5
    for r in sources['job_alio']:r['description_text']=body
    for number in range(10,30):
        posting=f'{number:03}';raws[posting]=copy.deepcopy(raws['001'])
        for original in base:
            row=original|dict(posting_id=posting,description_text=body,source_url='https://example.org/jobs/'+posting)
            if posting=='010':row.update(date_posted=str(AS_OF-timedelta(days=179)),closing_date='2026-03-10')
            if posting=='011':row['date_posted']=str(AS_OF-timedelta(days=180))
            if posting in ['013','022']:row['date_posted']=str(AS_OF+timedelta(days=1))
            if posting=='014':row['date_posted']=None
            if posting=='015':row['date_posted']=str(AS_OF+timedelta(days=2))
            if posting in ['016','018','019']:row['description_text']=''
            if posting=='017':row['description_text']='가'*100+'a'*900
            if posting=='018':row['locale']='ko-KR'
            if posting=='019':row['locale']='en-US'
            if posting in ['020','021']:row['source_modified_at']='2026-09-01T00:00:'+('31' if posting=='020' else '32')+'Z'
            if posting=='024':row.update(ongoing=False,closing_date='2026-08-31')
            if posting=='028':row['source_modified_at']='yesterday'
            if posting=='029':row['source_published_at']='2026-09-01T00:00:29Z'
            sources['job_alio'].append(row)
    return sources,raws

def occupation(posting,role='BACKEND_DEVELOPER'):
    ctx=read('ontology.query_occupation_input_v1('+q(BASE)+','+q(POSTING+posting)+',true)')
    doc=ctx['proposal_template']|dict(actor='fixture-occupation-author',resolver_version='fixture-manual-v1',
        reason='Synthetic fixture assignment against the four-role catalogue.',disposition='MATCH',occupation_id=ROLE+role,unresolved_reason=None)
    doc['evidence_ids']=sorted({e['evidence_id'] for duty in ctx['source_binding']['duties'] for e in duty['evidence']})
    pid=sql('SELECT ontology.capture_occupation_v1('+js(doc)+')')
    sql('SELECT ontology.decide_occupation_v1('+','.join(q(v) for v in [str(uuid.uuid4()),pid,'ACCEPT','fixture-role-independent','human','Synthetic source/role fixture review.'])+')')

def profile(posting):
    if int(posting)<10:return fixture.proposal(posting,BASE)
    ctx=fixture.context(posting,BASE);doc=ctx['proposal_template']|dict(actor='fixture-profile-author',resolver_version='fixture-manual-v1',
        reason='Synthetic explicit new-graduate label and Seoul work location.',posting_experience_label='ENTRY',
        posting_label_evidence=[fixture.citation(ctx,'recruitment_type','신입')])
    for track in doc['tracks']:track.update(country_scope='KR',country_evidence=[fixture.citation(ctx,'regions','서울')],
        cohort_scope='POSITION',scope_notes='The one reviewed position has no stated requirements; absent experience stays null.')
    return doc

def duplicate(members):
    family=str(uuid.uuid4());ctx=read('ontology.query_duplicate_input_v1('+q(BASE)+','+q(family)+','+q('{'+','.join(POSTING+p for p in members)+'}')+'::text[],true)')
    doc=ctx['proposal_template']|dict(actor='fixture-duplicate-author',resolver_version='fixture-manual-v1',reason='Synthetic versions of one recruitment notice.')
    pid=sql('SELECT ontology.capture_duplicate_v1('+js(doc)+')')
    sql('SELECT ontology.decide_duplicate_v1('+','.join(q(v) for v in [str(uuid.uuid4()),pid,'ACCEPT','fixture-duplicate-independent','human','Synthetic complete-source comparison.'])+')')
    return family

def build(name=BASE,role='BACKEND_DEVELOPER',as_of=AS_OF):
    return sql('SELECT ontology.build_posting_cohort_v1('+q(name)+','+q(ROLE+role)+','+q(as_of)+'::date)')
def report(key,name=BASE,at=AT):return read('ontology.query_posting_cohort_v1('+q(name)+','+q(key)+',true,'+q(at)+'::timestamptz)')
def rows(key):return read("coalesce((SELECT jsonb_object_agg(posting_id,to_jsonb(m)) FROM ontology.posting_cohort_posting m WHERE cohort_id="+q(key)+"),'{}')")
def fingerprint():
    tables=sql("SELECT quote_ident(schemaname)||'.'||quote_ident(tablename) FROM pg_tables WHERE schemaname IN ('ontology','editorial','ingestion','enrichment','attachment') ORDER BY 1").splitlines()
    union=' UNION ALL '.join('SELECT '+q(t)+" name,ontology.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')) h FROM "+t+' t' for t in tables)
    return sql('SELECT ontology.hash(jsonb_object_agg(name,h)) FROM ('+union+') t')

def main():
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode!=0
    try:
        run.boot();sources,raws=source_fixtures();run.load_sources(sources)
        for posting,raw in raws.items():
            rev=claims.capture(claims.seed_item(posting,raw=raw))
            if posting!='004':claims.decide(rev)
        native.stage();native.run('../cohorts/install_builder.hwf',{},'cohort-native-missing-prerequisites',False)
        assert 'INSTALL_EDITORIAL_AND_COHORT_PREPARATION_FIRST' in (native.WORK/'cohort-native-missing-prerequisites.log').read_text()
        native.run('../editorial/install.hwf',{},'cohort-native-editorial-install')
        native.run('../cohorts/install.hwf',{},'cohort-native-preparation-install')
        native.run('../cohorts/install_builder.hwf',{},'cohort-native-builder-install')
        sha=capture_catalogue();prepare(BASE,sha)
        err('SELECT ontology.build_posting_cohort_v1('+q(BASE)+','+q(ROLE+'BACKEND_DEVELOPER')+','+q(AS_OF)+')','COHORT_FROZEN_INPUTS_REQUIRED')
        fixture.normalize()
        for posting in raws:
            if posting not in ['004','005','026']:occupation(posting,'FRONTEND_DEVELOPER' if posting=='025' else 'BACKEND_DEVELOPER')
            if posting=='027':continue
            doc=profile(posting);pid=fixture.capture(doc)
            if doc['disposition']=='PROFILE':sql(fixture.decide(pid))
        families=[duplicate(['001','020','021','022']),duplicate(['012','023'])]
        sql('SELECT ontology.freeze_occupations_v1('+q(BASE)+'); SELECT ontology.freeze_cohort_profiles_v1('+q(BASE)+'); SELECT ontology.freeze_duplicates_v1('+q(BASE)+')')

        # Independently specified character thresholds, including non-Latin
        # letters and decomposed Hangul. Digits/emoji/punctuation are not letters.
        for payload,hangul,letters,eligible in [
            ({'description_text':'가'*99},99,99,False),({'description_text':'가'*100},100,100,True),
            ({'description_text':'가'*102+'A'*238},102,340,True),({'description_text':'가'*102+'A'*239},102,341,False),
            ({'title':'한글ABCéΩα中文😀123'},2,10,False),({'description_text':'가'*100},100,100,True),
            ({'locale':'ko-KR','title':'hi'},0,2,True),({'locale':'en-US','title':'hi'},0,2,False)]:
            got=read('ontology.cohort_language_v1('+js(payload)+')')
            assert (got['hangul_syllables'],got['letter_count'],got['eligible'])==(hangul,letters,eligible),got
        for payload,field,precision in [
            ({'date_posted':'2026-09-01','source_modified_at':'2026-09-01T09:00:00+09:00','source_published_at':'2026-08-31T23:00:00Z'},'source_modified_at','INSTANT'),
            ({'date_posted':'2026-09-01','source_published_at':'2026-09-01T00:00:00Z'},'source_published_at','INSTANT'),
            ({'date_posted':'2026-09-01'},'date_posted','DAY'),({},'retrieved_at','INSTANT')]:
            got=read('ontology.cohort_temporal_v1('+js(payload)+','+q(AT)+')')
            assert (got['ordering_field'],got['effective_precision'])==(field,precision),got
            if precision=='DAY':assert got['effective_timestamp_at'] is None and got['ordering_at']=='2026-08-31T15:00:00.000000Z'
        assert read('ontology.cohort_temporal_v1('+js({'date_posted':'2026-02-30'})+','+q(AT)+')')['date_issue']=='POSTING_DATE_INVALID'
        err('SELECT ontology.build_posting_cohort_v1('+q(BASE)+",'foreign','2026-09-01')",'COHORT_ONE_PRODUCT_OCCUPATION_REQUIRED')
        err('SELECT ontology.build_posting_cohort_v1('+q(BASE)+','+q(ROLE+'BACKEND_DEVELOPER')+",'2026-09-02')",'INVALID_COHORT_AS_OF_DATE')
        native.run('../cohorts/build_cohort.hwf',dict(RELEASE_ID=BASE,OCCUPATION_ID=ROLE+'BACKEND_DEVELOPER',AS_OF=str(AS_OF)),'cohort-native-build')
        key=build();first=report(key);members=rows(key)
        expected_included={'002','009','010','012','018','021','024','029'}
        assert {p for p,m in members.items() if m['outcome']=='INCLUDED'}==expected_included,{p:m['exclusion_reasons'] for p,m in members.items()}
        assert {p for p,m in members.items() if m['outcome']=='DUPLICATE'}=={'001','020','023'}
        assert len(members)==29 and first['membership']['manifest']['counts']['included']==8
        for posting,reason in [('011','BEFORE_WINDOW'),('013','AFTER_AS_OF'),('014','POSTING_DATE_UNKNOWN'),('015','AFTER_AS_OF'),
            ('016','KOREAN_CONTENT_NOT_ESTABLISHED'),('017','KOREAN_CONTENT_NOT_ESTABLISHED'),('019','KOREAN_CONTENT_NOT_ESTABLISHED'),
            ('025','OTHER_OCCUPATION'),('026','OCCUPATION_NOT_PROPOSED'),('027','PROFILE_NOT_PROPOSED'),('028','ORDERING_TIMESTAMP_INVALID')]:
            assert reason in members[posting]['exclusion_reasons'],members[posting]
        assert members['022']['outcome']=='EXCLUDED' and members['022']['representative_id']==POSTING+'021'
        assert members['021']['temporal_basis']['ordering_field']=='source_modified_at'
        assert members['023']['representative_id']==POSTING+'012'
        assert first['cohort']['window_start']==str(AS_OF-timedelta(days=179)) and first['cohort']['window_end']==str(AS_OF)
        assert first['active_fresh_count']==6 and first['current_included_states']=={'ACTIVE':6,'EXPIRED':1,'CLOSED':1},first
        assert report(key,at='2026-09-02T06:00:30Z')['active_fresh_count']==6
        stale=report(key,at='2026-09-02T06:00:31Z');assert stale['active_fresh_count']==0 and stale['membership']==first['membership']
        support=read("coalesce((SELECT jsonb_agg(to_jsonb(s)) FROM ontology.posting_cohort_claim s WHERE cohort_id="+q(key)+"),'[]')")
        assert len(support)==2 and {s['entity_id'] for s in support}=={POSTING+'002'}
        assert {s['claim_id'] for s in support}==set(next(t for t in profile('002')['tracks'] if t['experience_policy']=='ENTRY')['included_requirement_ids'])
        assert len({s['position_id'] for s in support})==1
        native.run('../cohorts/build_cohort.hwf',dict(RELEASE_ID=BASE,OCCUPATION_ID=ROLE+'BACKEND_DEVELOPER',AS_OF=str(AS_OF)),'cohort-native-build-replay')
        assert build()==key and report(key)==first
        frontend=build(role='FRONTEND_DEVELOPER');assert report(frontend)['membership']['manifest']['counts']['included']==1
        empty=build(role='AI_ENGINEER');assert report(empty)['membership']['manifest']['counts']['included']==0

        # All rows are paginated once; cursor is bound to immutable membership.
        cursor=None;seen=[]
        while True:
            page=read('ontology.query_cohort_members_v1('+q(BASE)+','+q(key)+',true,'+('NULL' if cursor is None else q(cursor))+',7)')
            seen.extend(m['posting_id'] for m in page['members']);cursor=page['next_cursor']
            if not cursor:break
        assert seen==sorted(raws) and len(set(seen))==29
        page=read('ontology.query_cohort_members_v1('+q(BASE)+','+q(key)+',true,NULL,2)');cursor=page['next_cursor']
        err('SELECT ontology.query_cohort_members_v1('+q(BASE)+','+q(frontend)+',true,'+q(cursor)+',2)','INVALID_COHORT_CURSOR')
        err('SELECT ontology.query_cohort_members_v1('+q(BASE)+','+q(key)+',true,NULL,101)','INVALID_COHORT_PAGE_SIZE')
        err('SELECT ontology.query_posting_cohort_v1('+q(BASE)+','+q(key)+',true,'+q('2026-08-31T00:00:00Z')+')','INVALID_COHORT_STATE_TIME')
        err('SELECT ontology.query_posting_cohort_v1('+q(BASE)+','+q(key)+',false)','ONTOLOGY_RELEASE_NOT_PUBLISHED')
        for table,error in [('posting_cohort_posting','POSTING_COHORT_MEMBERS_CHANGED'),('posting_cohort_track','POSTING_COHORT_TRACKS_CHANGED'),('posting_cohort_claim','POSTING_COHORT_SUPPORT_CHANGED')]:
            # Replace a value without breaking FKs, to reach the semantic verifier.
            column,value={'posting_cohort_posting':('outcome',"'EXCLUDED'"),'posting_cohort_track':('included_in_cohort','false'),
                          'posting_cohort_claim':('necessity',"'OPTIONAL'")}[table]
            err('BEGIN; ALTER TABLE ontology.'+table+' DISABLE TRIGGER USER; UPDATE ontology.'+table+' SET '+column+'='+value+
                ' WHERE cohort_id='+q(key)+'; SELECT ontology.verify_posting_cohort_v1('+q(key)+'); COMMIT',error)
        err('UPDATE ontology.posting_cohort SET as_of=as_of-1','IMMUTABLE_ONTOLOGY_RECORD')
        err('BEGIN; ALTER TABLE ontology.posting_cohort_manifest DISABLE TRIGGER USER; DELETE FROM ontology.posting_cohort_manifest WHERE cohort_id='+q(key)+
            '; SELECT ontology.verify_posting_cohort_v1('+q(key)+'); COMMIT','POSTING_COHORT_MANIFEST_CHANGED')
        # The test supplies prerequisite blocks only inside a transaction that
        # must fail; this never seals a graph or bypasses a production guard.
        err('UPDATE ontology.corpus_release SET manifest=ontology.graph_inventory_manifest('+q(BASE)+
            ")||jsonb_build_object('cohort_profile_membership',(SELECT to_jsonb(m) FROM ontology.cohort_profile_membership m WHERE release_id="+q(BASE)+
            "),'duplicate_membership',(SELECT to_jsonb(m) FROM ontology.duplicate_membership m WHERE release_id="+q(BASE)+')) WHERE release_id='+q(BASE),
            'POSTING_COHORT_GRAPH_INTEGRATION_REQUIRED')
        protected=fingerprint()
        native.run('../cohorts/read_posting_cohort.hwf',dict(RELEASE_ID=BASE,COHORT_ID=key,PREVIEW='Y',AS_AT=AT),'cohort-native-summary-read')
        native.run('../cohorts/read_cohort_members.hwf',dict(RELEASE_ID=BASE,COHORT_ID=key,PREVIEW='Y',PAGE_SIZE=2),'cohort-native-members-read')
        native.run('../cohorts/read_cohort_members.hwf',dict(RELEASE_ID=BASE,COHORT_ID=key,PREVIEW='Y',PAGE_SIZE=2,CURSOR=cursor),'cohort-native-next-page')
        native.run('../cohorts/read_posting_cohort.hwf',dict(RELEASE_ID=BASE,COHORT_ID=key,PREVIEW='invalid',AS_AT=AT),'cohort-native-invalid-preview',False)
        native.run('../cohorts/install_builder.hwf',{},'cohort-native-install-replay')
        assert fingerprint()==protected and report(key)==first
        assert sql('SELECT count(*) FROM attachment.attempt')=='0'
        assert sql("SELECT count(*) FROM ontology.corpus_release WHERE state='ACTIVE'")=='0'
        result=dict(result='PASS',source_postings=29,included=8,duplicates=3,excluded=18,active_fresh=6,stale_active_fresh=0,
            scoped_claim_support=2,window_dates=180,empty_cohort=True,native_workflows=True,read_fingerprint=protected,
            provider_calls=0,attachment_attempts=0,production_changes=False,graph_publication=False,demand_statistics=False,
            cohort_id=key,native_log_directory=str(native.WORK))
        (native.WORK/'cohort-report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    finally:
        subprocess.run(['docker','rm','-fv',native.HOP,run.PG],capture_output=True)
        subprocess.run(['docker','network','rm',native.NET],capture_output=True)

if __name__=='__main__':main()
