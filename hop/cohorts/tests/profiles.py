"""Reviewed Korean country/experience profiles in disposable PG18/native Hop.

All source text, extraction results and review identities are synthetic. This
driver never fetches attachments, calls a model or connects to a remote host.
"""
from pathlib import Path
import copy
import json
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'hop/ontology/tests'))
import run
suffix=uuid.uuid4().hex[:10]
run.PG='jobtology-profiles-pg-'+suffix
import native
import claims
native.PG=run.PG;native.HOP='jobtology-profiles-hop-'+suffix;native.NET='jobtology-profiles-'+suffix
sql,q,js,err=run.sql,run.q,run.js,run.expect_error
POSTING='urn:jobtology:jobPosting:job_alio:'
BASE='profiles-v1'

def read(expression):return json.loads(sql('SELECT '+expression))
def prepare(name,requirements=True):
    sql('SELECT ontology.prepare_release('+q(name)+'); SELECT ontology.assemble_sources('+q(name)+'); '
        'SELECT ontology.freeze_reviews('+q(name)+'); SELECT ontology.assemble_claims('+q(name)+')')
    if requirements:sql('SELECT ontology.freeze_requirements_v1('+q(name)+')')
def context(posting,name=BASE):return read('ontology.query_cohort_profile_input_v1('+q(name)+','+q(POSTING+posting)+',true)')
def report(name=BASE):return read('ontology.query_cohort_profiles_v1('+q(name)+',true)')
def capture(doc):return sql('SELECT ontology.capture_cohort_profile_v1('+js(doc)+')')
def decide(pid,choice='ACCEPT',who='fixture-independent',kind='human',rid=None):
    return 'SELECT ontology.decide_cohort_profile_v1('+','.join(q(v) for v in [rid or str(uuid.uuid4()),pid,choice,who,kind,
        'Synthetic independent field and position-scope review.'])+')'
def freeze(name):sql('SELECT ontology.freeze_cohort_profiles_v1('+q(name)+')')
def outcomes(name=BASE):return {s['selection']['entity_id'][-3:]:s['selection']['outcome'] for s in report(name)['selections']}
def fingerprint():
    tables=sql("SELECT quote_ident(schemaname)||'.'||quote_ident(tablename) FROM pg_tables WHERE schemaname IN ('ontology','ingestion','enrichment','attachment') ORDER BY 1").splitlines()
    union=' UNION ALL '.join('SELECT '+q(t)+" AS name,ontology.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')) AS h FROM "+t+' t' for t in tables)
    return sql('SELECT ontology.hash(jsonb_object_agg(name,h)) FROM ('+union+') t')
def citation(ctx,field,excerpt):
    text=ctx['source_binding']['fields'][field];start=text.index(excerpt)
    return dict(field=field,start_offset=start,end_offset=start+len(excerpt),excerpt=excerpt)
def edit_track(doc,index=0,**changes):
    result=copy.deepcopy(doc);result['tracks'][index].update(changes);return result

def source_fixtures():
    # Two source representations per identity. Decomposed Hangul, emoji and CRLF
    # in the first posting distinguish code points from bytes/UTF-16 offsets.
    specs={
        '001':('신입 백엔드 개발자','신입','😀 서울\r\n대한민국',['백엔드 개발자'],['서버 개발'],[[]]),
        '002':('신입 개발자 / 경력 개발자','신입·경력','신입: 서울 / 경력: 해외',['신입 개발자','경력 개발자'],
               ['서버 개발','서버 운영'],[['경력 0개월 이상','경력 24개월 이하'],['경력 60개월 이상']]),
        '003':('연구원','','',['연구원'],['연구 수행'],[[]]),
        '004':('인턴 개발자','인턴','서울',['인턴 개발자'],['개발 지원'],[[]]),
        '005':('상세 공고 참조','','',[],[],[]),
        '006':('해외 개발자','경력','일본 도쿄',['해외 개발자'],['시스템 개발'],[['경력 12개월 이상','경력 24개월 이하']]),
        '007':('선임 개발자','경력','서울 또는 도쿄',['선임 개발자'],['시스템 설계'],[['경력 60개월 이상']]),
        '008':('분석가','신입','서울',['분석가'],['자료 분석'],[['경력 12개월 이상']]),
        '009':('운영 담당자','경력무관','서울',['운영 담당자'],['서비스 운영'],[[]]),
    }
    sources=run.fixture();jobs=[];raws={}
    for posting,(title,label,regions,names,duties,requirements) in specs.items():
        lines=[name+': '+(' 및 '.join(reqs)+' / ' if reqs else '')+duty for name,duty,reqs in zip(names,duties,requirements)]
        jobs.extend(r|dict(posting_id=posting,title=title,organization_code='C001',recruitment_type=label,regions=regions,
            eligibility_text='\n'.join(lines),education='',preference_text='',source_url='https://example.org/jobs/'+posting) for r in sources['job_alio'])
        raw=dict(positions=[],duties=[],requirements=[],duties_status='explicit' if names else 'not_stated')
        for i,(name,duty,reqs) in enumerate(zip(names,duties,requirements),1):
            pos='p'+str(i);evidence=['eligibility_text:'+str(i)]
            raw['positions'].append(dict(id=pos,name=name,evidence_ids=['title:1']))
            raw['duties'].append(dict(position_ids=[pos],evidence_ids=evidence,text_parts=[duty]))
            if reqs:
                expression=[] if len(reqs)==1 else [dict(op='all_of',parts=[],children=list(range(1,len(reqs)+1)))]+[
                    dict(op='atom',parts=[s],children=[]) for s in reqs]
                raw['requirements'].append(dict(position_ids=[] if posting=='008' else [pos],category='qualification',kind='eligibility',
                    logic='single' if len(reqs)==1 else 'all_of',evidence_ids=evidence,text_parts=[' 및 '.join(reqs)],expression=expression))
        raws[posting]=raw
    sources['job_alio']=jobs
    return sources,raws

def normalize():
    atoms=read("coalesce((SELECT jsonb_agg(to_jsonb(a)) FROM ontology.requirement_atom a WHERE release_id='profiles-v1'),'[]')")
    documents={}
    for atom in atoms:
        text=atom['source_text'];months=int(text.split()[1].replace('개월',''))
        doc=dict(schema_version='hop-requirement-normalization-v1',release_id=BASE,source_claim_id=atom['source_claim_id'],
            node_index=atom['node_index'],parent_id=None,actor='fixture-typed-author',reason='Synthetic exact explicit month bound.',
            resolver_version='fixture-manual-v1',necessity='REQUIRED',polarity='POSITIVE',condition=dict(kind='EXPERIENCE',context_id=None,
                minimum_months=months if text.endswith('이상') else None,maximum_months=months if text.endswith('이하') else None))
        pid=sql('SELECT ontology.capture_requirement_v1('+js(doc)+')')
        sql('SELECT ontology.decide_requirement_v1('+q(pid)+",'ACCEPT','fixture-typed-independent','human','Synthetic explicit months checked')")
        documents[pid]=doc
    sql('SELECT ontology.freeze_requirements_v1('+q(BASE)+')')
    return documents

def proposal(posting,name=BASE):
    ctx=context(posting,name);doc=ctx['proposal_template']|dict(actor='fixture-author',resolver_version='fixture-manual-v1',
        reason='Synthetic source-grounded country and experience review for every selected position.')
    if doc['disposition']=='UNRESOLVED':return doc
    labels={'001':'ENTRY','002':'MIXED','004':'INTERNSHIP','006':'EXPERIENCED','007':'EXPERIENCED','008':'ENTRY','009':'UNRESTRICTED'}
    if posting in labels:
        doc.update(posting_experience_label=labels[posting],posting_label_evidence=[citation(ctx,'recruitment_type',ctx['source_binding']['fields']['recruitment_type'])])
    for t in doc['tracks']:
        pos=next(p for p in ctx['source_binding']['positions'] if p['position_id']==t['position_id'])
        atoms=[a for a in ctx['source_binding']['atoms'] if a['atom_id'] in t['considered_atom_ids']]
        known=[a for a in atoms if a['applicability'] in ['all_positions','posting_metadata'] or t['position_id'] in a['source_binding']['positions']]
        included=sorted(a['typed_requirement']['claim_id'] for a in known if a['typed_requirement'])
        t.update(cohort_scope='POSITION',scope_notes='All reviewed requirements apply to this position.',included_requirement_ids=included)
        if posting!='003':
            t.update(country_scope='KR',country_evidence=[citation(ctx,'regions','서울')]) if posting not in ['006','002'] else None
        if posting=='002':
            junior=pos['local_id']=='p1'
            t.update(country_scope='KR' if junior else 'NON_KR',country_evidence=[citation(ctx,'regions','신입: 서울' if junior else '경력: 해외')],
                experience_policy='ENTRY' if junior else 'EXPERIENCED',policy_basis='EXPLICIT_LABEL' if junior else 'PARSED_RANGE',
                minimum_months=0 if junior else 60,maximum_months=24 if junior else None,experience_requirement_ids=included,
                experience_evidence=[citation(ctx,'eligibility_text',next(line for line in ctx['source_binding']['fields']['eligibility_text'].splitlines() if line.startswith(pos['name'])))])
            if junior:t.update(cohort_scope='REVIEWED_SUBSET',scope_notes='Only the explicitly separated new-graduate position; no senior requirements.',
                scope_evidence=[citation(ctx,'title','신입 개발자')],entry_track_scoped=True)
        if posting in ['006','007']:
            t.update(country_scope='NON_KR' if posting=='006' else 'MIXED',country_evidence=[citation(ctx,'regions',ctx['source_binding']['fields']['regions'])],
                experience_policy='EXPERIENCED',policy_basis='PARSED_RANGE',minimum_months=12 if posting=='006' else 60,
                maximum_months=24 if posting=='006' else None,experience_requirement_ids=included,
                experience_evidence=[citation(ctx,'eligibility_text',ctx['source_binding']['fields']['eligibility_text'])])
        if posting=='008':t.update(cohort_scope='UNRESOLVED',scope_notes='Requirement does not identify its applicable position.')
        if posting=='009':t.update(experience_policy='UNRESTRICTED',policy_basis='EXPLICIT_LABEL',experience_evidence=[citation(ctx,'recruitment_type','경력무관')])
    return doc

def main():
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode!=0
    try:
        run.boot();sources,raws=source_fixtures();run.load_sources(sources);extractions={}
        for posting,raw in raws.items():
            item=claims.seed_item(posting,raw=raw);revision=claims.capture(item)
            if posting!='004':claims.decide(revision)
            extractions[posting]=revision
        prepare(BASE,False);native.stage();native.run('../cohorts/install.hwf',{},'profiles-native-install')
        err('SELECT ontology.query_cohort_profile_input_v1('+q(BASE)+','+q(POSTING+'001')+',true)','FREEZE_REQUIREMENTS_BEFORE_COHORT_PROFILE')
        norms=normalize();ctx=context('001');docs={p:proposal(p) for p in raws}
        assert ctx['source_binding']['fields']['regions']=='😀 서울\n대한민국'
        assert citation(ctx,'regions','서울')['start_offset']==2
        assert len(ctx['source_support'])==2
        assert docs['004']['unresolved_reason']=='EXTRACTION_NOT_ACCEPTED'
        assert docs['005']['unresolved_reason']=='NO_REVIEWED_POSITIONS'
        assert report()['selection_status']=='NOT_FROZEN' and report()['tracks']==[]
        prepare('profiles-before-proposals');freeze('profiles-before-proposals')
        assert outcomes('profiles-before-proposals')=={p:'EXTRACTION_NOT_ACCEPTED' if p=='004' else 'NOT_PROPOSED' for p in raws}
        a=docs['001'];mixed=docs['002'];junior=next(i for i,t in enumerate(mixed['tracks']) if t['experience_policy']=='ENTRY')
        senior=1-junior;range_doc=docs['006'];t=range_doc['tracks'][0]
        checks=[(a|dict(source_binding_hash='0'*64),'COHORT_PROFILE_SOURCE_BINDING_MISMATCH'),
            (a|dict(actor=' '),'COHORT_PROFILE_PROVENANCE_REQUIRED'),
            (a|dict(actor_kind='assistant'),'COHORT_PROFILE_METHOD_PROVENANCE_MISMATCH'),
            (a|dict(method='MODEL_INFERRED',actor_kind='assistant'),'COHORT_PROFILE_METHOD_PROVENANCE_MISMATCH'),
            (a|dict(confidence=.99),'INVALID_COHORT_PROFILE_PROPOSAL'),
            (a|dict(tracks=[]),'COHORT_PROFILE_ALL_POSITIONS_REQUIRED'),
            (edit_track(a,position_id='foreign'),'COHORT_PROFILE_ALL_POSITIONS_REQUIRED'),
            (a|dict(posting_label_evidence=[]),'COHORT_PROFILE_LABEL_EVIDENCE_REQUIRED'),
            (edit_track(a,country_evidence=[]),'COHORT_PROFILE_COUNTRY_EVIDENCE_REQUIRED'),
            (edit_track(a,scope_notes=' '),'COHORT_PROFILE_SCOPE_NOTES_REQUIRED'),
            (edit_track(a,minimum_months=0),'COHORT_PROFILE_UNKNOWN_EXPERIENCE_FIELDS'),
            (edit_track(range_doc,experience_evidence=[]),'COHORT_PROFILE_EXPERIENCE_EVIDENCE_REQUIRED'),
            (edit_track(range_doc,minimum_months=30),'COHORT_PROFILE_EXPERIENCE_RANGE_ORDER'),
            (edit_track(range_doc,minimum_months=None,maximum_months=None),'COHORT_PROFILE_RANGE_REQUIRED'),
            (edit_track(range_doc,maximum_months=23),'COHORT_PROFILE_MONTHS_NOT_IN_REVIEWED_CONDITION'),
            (edit_track(range_doc,considered_atom_ids=[]),'COHORT_PROFILE_ALL_ATOMS_REQUIRED'),
            (edit_track(range_doc,included_requirement_ids=[]),'COHORT_PROFILE_POSITION_CLAIMS_INCOMPLETE'),
            (edit_track(range_doc,experience_requirement_ids=['foreign']),'COHORT_PROFILE_EXPERIENCE_REFERENCE_REQUIRED'),
            (edit_track(range_doc,included_requirement_ids=t['included_requirement_ids']*2),'COHORT_PROFILE_REFERENCE_SET_NOT_CANONICAL'),
            (edit_track(mixed,junior,included_requirement_ids=mixed['tracks'][senior]['included_requirement_ids']),'COHORT_PROFILE_REQUIREMENT_OUTSIDE_POSITION'),
            (edit_track(mixed,junior,scope_evidence=[]),'COHORT_PROFILE_SUBSET_EVIDENCE_REQUIRED'),
            (edit_track(mixed,junior,included_requirement_ids=[]),'COHORT_PROFILE_SUBSET_EXPERIENCE_NOT_INCLUDED'),
            (edit_track(mixed,junior,cohort_scope='POSITION'),'COHORT_PROFILE_TRACK_SCOPE_REQUIRED'),
            (edit_track(docs['008'],cohort_scope='POSITION'),'COHORT_PROFILE_REQUIREMENTS_UNRESOLVED'),
            (edit_track(docs['009'],minimum_months=12),'COHORT_PROFILE_EXPLICIT_POLICY_REQUIRED'),
            (docs['005']|dict(posting_experience_label='ENTRY'),'COHORT_PROFILE_UNRESOLVED_FIELDS')]
        ev=a['tracks'][0]['country_evidence'][0]
        for change in [dict(start_offset=1),dict(end_offset=5),dict(excerpt='부산'),dict(field='invented')]:
            checks.append((edit_track(a,country_evidence=[ev|change]),'COHORT_PROFILE_EVIDENCE_MISMATCH'))
        for doc,error in checks:err('SELECT ontology.capture_cohort_profile_v1('+js(doc)+')',error)
        # The eligibility bound cannot come from a preferred, negated, non-total
        # or non-experience condition. Test the validation boundary directly;
        # these deliberately altered bindings are never stored as source data.
        range_source=context('006')['source_binding']
        for changes in [dict(necessity='PREFERRED'),dict(polarity='NEGATED'),dict(requirement_kind='LOCATION'),
                        dict(condition=dict(kind='EXPERIENCE',context_id='urn:skill:example',minimum_months=12,maximum_months=24))]:
            invalid_source=copy.deepcopy(range_source)
            for atom in invalid_source['atoms']:atom['typed_requirement'].update(changes)
            err('SELECT ontology.validate_cohort_profile_v1('+js(invalid_source)+','+js(range_doc)+')','COHORT_PROFILE_EXPERIENCE_REFERENCE_REQUIRED')
        # Boundary truth table is independent of fixture interpretations and
        # prevents SQL NULL from accidentally making unknown policies eligible.
        for maximum,expected in [(None,False),(0,True),(24,True),(25,False),(60,False)]:
            probe=edit_track(range_doc,country_scope='KR',maximum_months=maximum)
            reasons=read('ontology.cohort_track_reasons_v1('+js(probe)+','+js(probe['tracks'][0])+')')
            assert ('EXPERIENCE_NOT_ENTRY_ELIGIBLE' not in reasons)==expected,(maximum,reasons)
        err("SELECT ontology.import_cohort_profile_v1(convert_to('{\"x\":1,\"x\":2}','UTF8'))",'COHORT_PROFILE_JSON_OBJECT_REQUIRED')
        err("SELECT ontology.import_cohort_profile_v1(''::bytea)",'COHORT_PROFILE_FILE_SIZE')
        assert sql('SELECT count(*) FROM ontology.cohort_profile_proposal')=='0'
        file=native.WORK/'profile.json';file.write_text(json.dumps(a,ensure_ascii=False))
        run.cmd(['docker','cp',str(file),native.HOP+':'+native.REMOTE+'/profile.json'])
        for label in ['import','import-replay']:
            native.run('../cohorts/import_cohort_profile.hwf',dict(PROPOSAL_FILE=native.REMOTE+'/profile.json'),'profiles-native-'+label)
        ids={'001':capture(a)}
        assert sql('SELECT count(*) FROM ontology.cohort_profile_proposal')=='1'
        err(decide(ids['001'],who='fixture-author'),'INDEPENDENT_COHORT_PROFILE_REVIEW_REQUIRED')
        review_id=str(uuid.uuid4());review=dict(REVIEW_ID=review_id,PROPOSAL_ID=ids['001'],DECISION='ACCEPT',REVIEWER='fixture-independent',
            REVIEWER_KIND='human',NOTES='Synthetic independent field and position-scope review.')
        for label in ['review','review-replay']:native.run('../cohorts/review_cohort_profile.hwf',review,'profiles-native-'+label)
        err(decide(ids['001'],choice='REJECT',rid=review_id),'COHORT_PROFILE_REVIEW_ID_CONFLICT')
        for p in raws:
            if p=='001':continue
            ids[p]=capture(docs[p])
            if p in ['004','005']:err(decide(ids[p]),'UNRESOLVED_COHORT_PROFILE_CANNOT_BE_ACCEPTED')
            else:sql(decide(ids[p]))
        native.run('../cohorts/freeze_cohort_profiles.hwf',dict(RELEASE_ID=BASE),'profiles-native-freeze')
        first=report();assert outcomes()=={p:('EXTRACTION_NOT_ACCEPTED' if p=='004' else 'UNRESOLVED' if p=='005' else 'REVIEWED') for p in raws}
        tracks=first['tracks'];eligible=[t for t in tracks if t['country_experience_scope_eligible']]
        assert sorted(t['entity_id'][-3:] for t in eligible)==['001','002','009'],eligible
        unknown=next(t for t in tracks if t['entity_id']==POSTING+'003')
        assert unknown['exclusion_reasons']==['COUNTRY_UNKNOWN','EXPERIENCE_NOT_ENTRY_ELIGIBLE'],unknown
        assert next(t for t in tracks if t['entity_id']==POSTING+'006')['exclusion_reasons']==['OUTSIDE_KR']
        assert next(t for t in tracks if t['entity_id']==POSTING+'008')['exclusion_reasons']==['REQUIREMENT_SCOPE_UNRESOLVED']
        assert all(t['confidence'] is None and t['confidence_state']=='UNASSESSED' for t in tracks)
        assert eligible[next(i for i,t in enumerate(eligible) if t['entity_id']==POSTING+'001')]['profile']['minimum_months'] is None
        junior_ids=mixed['tracks'][junior]['included_requirement_ids'];senior_ids=mixed['tracks'][senior]['included_requirement_ids']
        assert set(junior_ids).isdisjoint(senior_ids)
        assert next(t for t in eligible if t['entity_id']==POSTING+'002')['profile']['included_requirement_ids']==junior_ids
        native.run('../cohorts/freeze_cohort_profiles.hwf',dict(RELEASE_ID=BASE),'profiles-native-freeze-replay');assert report()==first
        err("UPDATE ontology.corpus_release SET manifest=ontology.graph_inventory_manifest('profiles-v1') WHERE release_id='profiles-v1'",'COHORT_PROFILE_GRAPH_INTEGRATION_REQUIRED')

        # Same evidence/review permits reuse; a new proposal never falls back.
        prepare('profiles-same');assert capture(a|dict(release_id='profiles-same'))==ids['001'];freeze('profiles-same')
        assert outcomes('profiles-same')==outcomes()
        newer=proposal('001','profiles-same')|dict(reason='Synthetic pending correction.')
        newer_id=capture(newer);prepare('profiles-pending');freeze('profiles-pending')
        assert outcomes('profiles-pending')['001']=='PENDING'
        assert sql(decide(ids['001'],rid=review_id))==sql('SELECT decision_id FROM ontology.cohort_profile_decision WHERE review_id='+q(review_id))
        err(decide(ids['001']),'COHORT_PROFILE_PROPOSAL_SUPERSEDED')
        err('SELECT ontology.capture_cohort_profile_v1('+js(newer|dict(parent_id=None,reason='Stale edit'))+')','STALE_COHORT_PROFILE_PARENT')
        sql(decide(newer_id,choice='REJECT'));prepare('profiles-rejected');freeze('profiles-rejected')
        assert outcomes('profiles-rejected')['001']=='REJECTED'

        # A reviewed domestic subset cannot turn 60-month experience into entry.
        domestic=edit_track(proposal('007'),cohort_scope='REVIEWED_SUBSET',domestic_track_scoped=True,
            scope_notes='Only Seoul work location; senior experience still applies.',scope_evidence=[citation(context('007'),'regions','서울')])
        err('SELECT ontology.capture_cohort_profile_v1('+js(edit_track(domestic,entry_track_scoped=True))+')','COHORT_PROFILE_ENTRY_TRACK_POLICY_MISMATCH')
        err('SELECT ontology.capture_cohort_profile_v1('+js(edit_track(domestic,experience_policy='MIXED',entry_track_scoped=True))+')','COHORT_PROFILE_ENTRY_TRACK_POLICY_MISMATCH')
        domestic_id=capture(domestic);sql(decide(domestic_id,kind='assistant'));prepare('profiles-domestic');freeze('profiles-domestic')
        chosen=next(t for t in report('profiles-domestic')['tracks'] if t['entity_id']==POSTING+'007')
        assert chosen['exclusion_reasons']==['EXPERIENCE_NOT_ENTRY_ELIGIBLE'] and chosen['review_status']=='ASSISTANT_REVIEWED'
        modeled=proposal('003')|dict(actor='fixture-model',actor_kind='assistant',method='MODEL_INFERRED',
            model_id='fixture/not-a-live-model',prompt_version='fixture-prompt-v1')
        modeled_id=capture(modeled);sql(decide(modeled_id,kind='assistant'));prepare('profiles-modeled');freeze('profiles-modeled')
        modeled_selection=next(s for s in report('profiles-modeled')['selections'] if s['selection']['entity_id']==POSTING+'003')
        assert modeled_selection['proposal']['document']['model_id']=='fixture/not-a-live-model'
        assert next(t for t in report('profiles-modeled')['tracks'] if t['entity_id']==POSTING+'003')['exclusion_reasons']==unknown['exclusion_reasons']

        # Re-reviewing either source extraction or typed condition invalidates a
        # profile in new releases even if the literal source text is unchanged.
        claims.decide(extractions['002']);prepare('profiles-extraction-changed');freeze('profiles-extraction-changed')
        assert outcomes('profiles-extraction-changed')['002']=='SOURCE_CHANGED'
        norm=next(pid for pid,doc in norms.items() if doc['source_claim_id']==context('006')['source_binding']['atoms'][0]['source_claim_id'])
        sql('SELECT ontology.decide_requirement_v1('+q(norm)+",'ACCEPT','fixture-typed-independent','human','Synthetic new independent decision')")
        prepare('profiles-normalization-changed');freeze('profiles-normalization-changed')
        assert outcomes('profiles-normalization-changed')['006']=='SOURCE_CHANGED'
        assert report()==first
        prepare('profiles-legacy',False);sql("SELECT ontology.seal_graph('profiles-legacy')")
        assert report('profiles-legacy')['selection_status']=='NOT_FROZEN'
        err("SELECT ontology.freeze_cohort_profiles_v1('profiles-legacy')",'ONTOLOGY_RELEASE_NOT_PREPARING_OR_ALREADY_SEALED')

        # Corruption checks roll back their deliberate test-only mutations.
        err('DELETE FROM ontology.cohort_profile_selection','IMMUTABLE_ONTOLOGY_RECORD')
        err("BEGIN; ALTER TABLE ontology.cohort_profile_selection DISABLE TRIGGER USER; DELETE FROM ontology.cohort_profile_selection WHERE release_id='profiles-v1'; SELECT ontology.verify_cohort_profiles_v1('profiles-v1'); COMMIT",'COHORT_PROFILE_SELECTION_CHANGED')
        err("BEGIN; ALTER TABLE ontology.cohort_profile_proposal DISABLE TRIGGER USER; UPDATE ontology.cohort_profile_proposal SET evidence_bindings='[]' WHERE proposal_id="+q(ids['001'])+"; SELECT ontology.verify_cohort_profiles_v1('profiles-v1'); COMMIT",'COHORT_PROFILE_EVIDENCE_CHANGED')
        err("BEGIN; ALTER TABLE ontology.cohort_profile_membership DISABLE TRIGGER USER; DELETE FROM ontology.cohort_profile_membership WHERE release_id='profiles-v1'; SELECT ontology.verify_cohort_profiles_v1('profiles-v1'); COMMIT",'COHORT_PROFILE_MEMBERSHIP_CHANGED')
        err("SELECT ontology.query_cohort_profiles_v1('profiles-v1',false)",'ONTOLOGY_RELEASE_NOT_PUBLISHED')
        err("SELECT ontology.query_cohort_profiles_v1(NULL,true)",'NO_ACTIVE_ONTOLOGY_RELEASE')
        err("SELECT ontology.query_cohort_profiles_v1('profiles-v1',NULL)",'INVALID_ONTOLOGY_READ_MODE')
        for state,error in [('FAILED','ONTOLOGY_RELEASE_FAILED'),('REVOKED','CORPUS_RELEASE_REVOKED')]:
            err("BEGIN; UPDATE ontology.corpus_release SET state="+q(state)+" WHERE release_id='profiles-v1'; SELECT ontology.query_cohort_profiles_v1('profiles-v1',true); COMMIT",error)
        assert sql('SELECT count(*) FROM attachment.attempt')=='0'
        assert sql("SELECT count(*) FROM ontology.corpus_release WHERE state='ACTIVE'")=='0'
        protected=fingerprint()
        native.run('../cohorts/read_cohort_profile_input.hwf',dict(RELEASE_ID=BASE,ENTITY_ID=POSTING+'002',PREVIEW='Y'),'profiles-native-input-read')
        native.run('../cohorts/read_cohort_profiles.hwf',dict(RELEASE_ID=BASE,PREVIEW='Y'),'profiles-native-read')
        native.run('../cohorts/read_cohort_profiles.hwf',dict(RELEASE_ID=BASE,PREVIEW='invalid'),'profiles-native-invalid-preview',False)
        native.run('../cohorts/install.hwf',{},'profiles-native-install-replay')
        assert fingerprint()==protected and report()==first
        result=dict(result='PASS',postings=9,reviewed_profiles=7,qualifying_tracks=3,
            mixed_posting='ONLY_JUNIOR_CLAIMS',unknown_experience='EXCLUDED_WITHOUT_EXPLICIT_ENTRY_LABEL',
            domestic_subset='CANNOT_BYPASS_SENIOR_EXPERIENCE',source_review_change='SOURCE_CHANGED',typed_review_change='SOURCE_CHANGED',
            native_workflows=True,read_fingerprint=protected,provider_calls=0,attachment_attempts=0,production_changes=False,
            actual_cohorts=False,graph_publication=False,native_log_directory=str(native.WORK))
        (native.WORK/'profile-report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    finally:
        subprocess.run(['docker','rm','-fv',native.HOP,run.PG],capture_output=True)
        subprocess.run(['docker','network','rm',native.NET],capture_output=True)

if __name__=='__main__':main()
