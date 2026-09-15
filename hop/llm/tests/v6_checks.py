"""Nested-tree round trips and source-accounting checks, independent of paid inference."""
import copy
import json
import uuid
from itertools import product


def atom(text): return dict(op='atom', parts=[text], children=[])
def group(op, *children): return dict(op=op, parts=[], children=list(children))
def record(text, tree=None, field='eligibility_text', kind='eligibility', ids=None):
    logic = 'single' if tree is None else 'conditional' if tree['op'] in ('if_then','except') else tree['op']
    return dict(position_ids=[], category='other', kind=kind, logic=logic, text_parts=[text],
        evidence_ids=ids or [field+':1'], condition=tree)
def output(*requirements, unhandled=None):
    return dict(positions=[], duties=[], requirements=list(requirements), duties_status='not_stated', unhandled_passages=unhandled or [])
def disposition(id, kind='procedure', target=None):
    return dict(evidence_id=id, disposition=kind, reason='Synthetic source disposition', duplicate_of=target)


def check_v6_text(sql, js):
    schema=json.loads(sql("SELECT output_schema FROM enrichment.prompt WHERE version='ko-v6' AND stage='extract'"))
    def shape(o): return json.loads(sql(f'SELECT enrichment.schema_issues_v6({js(o)},{js(schema)})'))
    def issues(o,s):
        assert shape(o)==[],shape(o)
        return json.loads(sql(f'SELECT enrichment.output_issues_v6({js(o)},{js(s)})'))
    text='자격증 소지 및 (경력 7년 또는 관련업무 15년)'
    source=dict(eligibility_text=text)
    tree=group('all_of',atom('자격증 소지'),group('any_of',atom('경력 7년'),atom('관련업무 15년')))
    good=output(record(text,tree))
    assert issues(good,source)==[],issues(good,source)
    flat=json.loads(sql(f'SELECT enrichment.flatten_tree_v6({js(tree)})'))
    assert [r['children'] for r in flat]==[[1,2],[],[3,4],[],[]],flat
    def decode(index):
        n=flat[index]
        return dict(op=n['op'],parts=n['parts'],children=[decode(i) for i in n['children']])
    assert decode(0)==tree,'Canonical traversal changed a branch'
    # Truth-table oracle for the pilot's shared-condition/three-alternative failure.
    shared='100만원 이상의 벌금형이 확정된 후 3년이 지나지 아니한 사람'
    parent='다음 각 목의 어느 하나에 해당하는 죄를 범한 사람으로서 '+shared
    alternatives=['가. 범죄 A','나. 범죄 B','다. 범죄 C']
    source_list=dict(disqualification_text=parent+'\n'+'\n'.join(alternatives))
    correct_tree=group('all_of',atom(shared),group('any_of',*map(atom,alternatives)))
    req=record(parent,correct_tree,field='disqualification_text',kind='exclusion',
        ids=['disqualification_text:'+str(i) for i in range(1,5)])
    req['text_parts']=[parent]+alternatives
    assert issues(output(req),source_list)==[],issues(output(req),source_list)
    nodes=json.loads(sql(f'SELECT enrichment.flatten_tree_v6({js(correct_tree)})'))
    def evaluate(index,values):
        n=nodes[index]
        if n['op']=='atom':return values[n['parts'][0]]
        children=[evaluate(c,values) for c in n['children']]
        return all(children) if n['op']=='all_of' else any(children)
    for penalty,a,b,c in product((False,True),repeat=4):
        values=dict(zip([shared]+alternatives,[penalty,a,b,c]))
        assert evaluate(0,values)==(penalty and (a or b or c)),values
    assert json.loads(sql('SELECT enrichment.flatten_tree_v6(\'null\'::jsonb)'))==[]
    hydrated=json.loads(sql(f'SELECT enrichment.hydrate_v6({js(good)},{js(source)})'))
    assert hydrated['schema_version']=='ko-v6' and hydrated['condition_encoding']=='nested-to-preorder-v1'
    assert hydrated['requirements'][0]['expression'][2]['children']==[3,4]
    assert hydrated['source_coverage'][0]['disposition']=='cited'
    assert hydrated['normalization']['provider_output_hash']==hydrated['provider_output_hash']
    old=copy.deepcopy(good);old.pop('unhandled_passages');old['requirements'][0].pop('condition');old['requirements'][0]['expression']=flat
    prior=json.loads(sql(f'SELECT enrichment.hydrate_v5({js(old)},{js(source)})'))
    assert hydrated['requirements']==prior['requirements'],'Nested adapter changed canonical claims'
    assert sql("SELECT enrichment.schema_issues_v6('{}','{}')")!='[]','Untyped schema silently accepted'
    for edit in [lambda x:x['requirements'][0]['condition']['children'].append(2),
                 lambda x:x['requirements'][0]['condition'].update(extra='bad'),
                 lambda x:x['requirements'][0]['condition']['children'][0].update(parts=None),
                 lambda x:x.pop('unhandled_passages')]:
        bad=copy.deepcopy(good);edit(bad);assert shape(bad)
    # External references never fetch data. Cyclic schema definitions are bounded.
    for schema_bad, expected in [({'$ref':'https://example.org/schema'},'UNSUPPORTED_SCHEMA_REFERENCE'),
      ({'$ref':'#/$defs/missing','$defs':{}},'UNSUPPORTED_SCHEMA_REFERENCE')]:
        assert expected in sql(f'SELECT enrichment.schema_issues_v6(\'{{}}\'::jsonb,{js(schema_bad)})')
    nested=atom('자격증 소지')
    for _ in range(13): nested=group('all_of',atom('자격증 소지'),nested)
    assert json.loads(sql(f'SELECT enrichment.tree_size_v6({js(nested)})'))['depth']==13
    assert 'NESTED_TREE_LIMIT' in sql(f'SELECT enrichment.output_issues_v6({js(output(record(text,nested)))},{js(source)})')
    too_wide=group('all_of',*[atom('자격증 소지') for _ in range(60)])
    assert 'NESTED_TREE_LIMIT' in sql(f'SELECT enrichment.output_issues_v6({js(output(record(text,too_wide)))},{js(source)})')
    # Every narrative passage must be cited or explicitly accounted for.
    extra=source|dict(preference_text='장애인 가점\n만점의 3%를 가산한다\n다만 점수가 40% 미만이면 가점하지 않는다')
    found=issues(good,extra)
    assert sum('UNACCOUNTED_PASSAGE' in e for e in found)==3,found
    bad=copy.deepcopy(good);bad['unhandled_passages']=[disposition('preference_text:'+str(i)) for i in (1,2,3)]
    assert any('POSSIBLE_OMITTED_CONDITION' in e for e in issues(bad,extra))
    bad=copy.deepcopy(good);bad['unhandled_passages']=[disposition('eligibility_text:1')]
    assert any('CONFLICTING_DISPOSITION' in e for e in issues(bad,source))
    bad=copy.deepcopy(good);bad['unhandled_passages']=[disposition('missing:9')]
    assert 'coverage:UNKNOWN_PASSAGE' in issues(bad,source)
    numeric=dict(eligibility_text='지원자는 경력 3년 이상이어야 함')
    assert any('NUMERIC_QUALIFIER_OMITTED' in e for e in issues(output(record('지원자는')),numeric))
    # Source accounting cannot call an unrelated line a grounded duplicate.
    duplicate=source|dict(description_text=text)
    accounted=good|dict(unhandled_passages=[disposition('description_text:1','duplicate','eligibility_text:1')])
    assert issues(accounted,duplicate)==[],issues(accounted,duplicate)
    assert any('DUPLICATE_NOT_GROUNDED' in e for e in issues(accounted,duplicate|dict(description_text='다른 내용')))
    none=source|dict(preference_text='없음')
    accounted=good|dict(unhandled_passages=[disposition('preference_text:1','no_condition')])
    assert issues(accounted,none)==[],issues(accounted,none)
    assert any('UNPROVEN_NO_CONDITION' in e for e in issues(accounted,none|dict(preference_text='석사 우대')))
    pending=good|dict(unhandled_passages=[disposition('preference_text:1','unresolved')])
    assert any('SOURCE_REVIEW_REQUIRED' in e for e in issues(pending,none))
    # The pilot reversed this scope by treating it as an exemption.
    scope='색각검사 결과 정상 판정이 아닌 사람(통신 및 전기분야로 한정한다)'
    base=atom('색각검사 결과 정상 판정이 아닌 사람');applies=atom('통신 및 전기분야로 한정한다')
    scoped_source=dict(disqualification_text=scope)
    wrong=output(record(scope,group('except',base,applies),field='disqualification_text',kind='exclusion'))
    assert 'expression:APPLICABILITY_AS_EXEMPTION_REVIEW_REQUIRED' in issues(wrong,scoped_source)
    right=output(record(scope,group('all_of',base,applies),field='disqualification_text',kind='exclusion'))
    assert issues(right,scoped_source)==[],issues(right,scoped_source)
    print('V6 nested round-trip, schema bounds, source accounting, numeric qualifiers and applicability checks passed',flush=True)


def check_v6_native(sql,js,q,run_hop,params,request_count):
    params=params|dict(JOB_RUN_ID='test-jobs',NCS_RUN_ID='test-ncs')
    check_v6_text(sql,js)
    before=request_count()
    run_hop('evaluate.hwf',params|dict(PROMPT_VERSION='ko-v6'),'v6-native-two-stage')
    report=json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated']==2 and report['requests']==3,report
    assert request_count()==before+3
    bid=report['batch_id']
    request=json.loads(sql(f"SELECT request_body FROM enrichment.attempt WHERE batch_id={q(bid)} AND stage='categorize' AND state='VALIDATED'"))
    context=json.loads(request['messages'][1]['content'])['source_context']
    assert any(p['field']=='title' and p['text']=='데이터 엔지니어 채용' for p in context['source_passages'])
    attempt=json.loads(sql(f"SELECT to_jsonb(a) FROM enrichment.attempt a WHERE batch_id={q(bid)} AND stage='extract' AND parsed_output->>'duties_status'='explicit'"))
    assert attempt['raw_output']['requirements'][0]['condition']['children'][0]['op']=='atom'
    assert attempt['parsed_output']['requirements'][0]['expression'][0]['children']==[1,2]
    assert all(c['disposition']!='unaccounted' for c in attempt['parsed_output']['source_coverage'])
    run_hop('evaluate.hwf',params|dict(PROMPT_VERSION='ko-v6',REUSE_CACHE='Y'),'v6-cache-repeat')
    assert request_count()==before+3,'Nested extraction cache was charged again'
    run_hop('enrich.hwf',params|dict(PROMPT_VERSION='ko-v6',REUSE_CACHE='N'),'v6-production-review-fixture')
    assert request_count()==before+6,'EVAL cache crossed into production'
    item=sql("SELECT i.item_id FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) WHERE b.mode='ENRICH' AND i.posting_id='001' ORDER BY b.created_at DESC LIMIT 1")
    run_hop('capture_extraction.hwf',dict(ITEM_ID=item,ACTOR='v6-fixture',REASON='Nested source review fixture'),'v6-capture-nested-extraction')
    revision=json.loads(sql(f"SELECT to_jsonb(r) FROM enrichment.extraction_revision r WHERE item_id={q(item)}"))
    assert revision['extraction']['schema_version']=='ko-v6' and revision['extraction']['source_coverage']
    corrected=copy.deepcopy(revision['raw_output']);corrected['requirements'][0]['condition']['children'].reverse()
    newer=sql(f"SELECT enrichment.capture_extraction({q(item)},'v6-fixture','Equivalent alternative order fixture',{js(corrected)},{q(revision['revision_id'])})")
    assert newer!=revision['revision_id']
    assert sql(f"SELECT count(*) FROM enrichment.extraction_decision d JOIN enrichment.extraction_revision r USING(revision_id) WHERE r.item_id={q(item)}")=='0'
    # Explicit independent rejection is repairable; pending and accepted revisions are protected.
    opts=report['settings']|dict(execute_requests='N',reuse_cache='N')
    original='v6-reviewed-'+uuid.uuid4().hex
    sql(f"SELECT enrichment.plan_batch({q(original)},'ENRICH',NULL,'test-jobs','test-ncs',{js(opts|dict(prompt_version='ko-v5'))}); SELECT enrichment.plan_stage({q(original)},'extract')")
    rows=json.loads(sql(f"SELECT jsonb_agg(to_jsonb(i) ORDER BY ordinal) FROM enrichment.item i WHERE batch_id={q(original)}"))
    sql(f"UPDATE enrichment.batch SET state='PARTIAL' WHERE batch_id={q(original)}")
    for i in rows:
        sql(f"UPDATE enrichment.attempt SET state='VALIDATED' WHERE attempt_id={q(i['extraction_id'])}")
        sql(f"INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason) VALUES({q('v6-rev-'+i['item_id'])},{q(i['item_id'])},'{{}}','{{}}','fixture','Test selection only')")
    rejected,pending=rows
    sql(f"SELECT enrichment.decide_extraction({q('v6-rev-'+rejected['item_id'])},'REJECT','fixture','assistant','Shared condition attached to wrong alternative')")
    assert sql(f"SELECT enrichment.repair_reasons_v6({q(pending['item_id'])}) IS NULL")=='t'
    reasons=json.loads(sql(f"SELECT enrichment.repair_reasons_v6({q(rejected['item_id'])})"))
    assert reasons==['INDEPENDENT_EXTRACTION_REJECTED','Shared condition attached to wrong alternative']
    target='v6-repair-'+uuid.uuid4().hex
    sql(f"SELECT enrichment.plan_batch({q(target)},'ENRICH',NULL,'test-jobs','test-ncs',{js(opts|dict(repair_batch_id=original))}); SELECT enrichment.plan_stage({q(target)},'extract')")
    assert sql(f"SELECT count(*) FROM enrichment.item WHERE batch_id={q(target)}")=='1'
    feedback=json.loads(sql(f"SELECT (request_body#>>'{{messages,1,content}}')::jsonb->'repair_context' FROM enrichment.attempt WHERE batch_id={q(target)}"))
    assert feedback['validator_issues']==reasons
    print('V6 native two-stage context, cache, raw/canonical separation and independently rejected repair selection passed',flush=True)
