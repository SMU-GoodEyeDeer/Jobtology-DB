"""Source-bound request grammar: native checks plus independent regex readback."""
import copy
import json
import re
from v7_checks import output, range_row


def check_source_bound(sql, js):
    base = json.loads(sql("SELECT output_schema FROM enrichment.prompt WHERE version='ko-v7' AND stage='extract'"))
    frozen = sql("SELECT md5(jsonb_agg(p ORDER BY version,stage)::text) FROM enrichment.prompt p")

    def schema(source):
        return json.loads(sql(f'SELECT enrichment.source_bound_schema_v1({js(base)},{js(source)})'))

    def issues(raw, generated):
        return json.loads(sql(f'SELECT enrichment.schema_issues_request_v1({js(raw)},{js(generated)})'))

    source = dict(title='개발자 채용', description_text='보수\n\n연봉 5000만원\r\n주 40시간 근무',
                  selection_text='온라인 접수')
    generated = schema(source)
    good = output(ranges=[range_row('description_text:1','description_text:4','document_context','employment_terms'),
                          range_row('selection_text:1')])
    assert issues(good,generated)==[]
    assert json.loads(sql(f'SELECT enrichment.output_issues_v7({js(good)},{js(source)})'))==[]
    for change in [dict(first_id='title:1',last_id='title:1'),
                   dict(first_id='description_text:2'), dict(last_id='description_text:5'),
                   dict(last_id='selection_text:1'), dict(duplicate_of='selection_text:1'),
                   dict(context_kind=None)]:
        bad=copy.deepcopy(good);bad['unhandled_ranges'][0].update(change)
        assert issues(bad,generated),change
    bad=copy.deepcopy(good);bad['unhandled_ranges'][1]['context_kind']='employment_terms'
    assert issues(bad,generated)
    # Ordering and duplicate equality still need relational source validation.
    reversed_range=copy.deepcopy(good)
    reversed_range['unhandled_ranges'][0].update(first_id='description_text:4',last_id='description_text:1')
    assert issues(reversed_range,generated)==[]
    assert 'coverage:INVALID_RANGE_ORDER_OR_FIELD' in json.loads(sql(f'SELECT enrichment.output_issues_v7({js(reversed_range)},{js(source)})'))
    positioned=copy.deepcopy(good)
    positioned['positions']=[dict(id='p1',name='개발자',evidence_ids=['title:1'])]
    assert issues(positioned,generated)==[]
    positioned['positions'][0]['evidence_ids']=['title:100']
    assert any('PATTERN' in x for x in issues(positioned,generated))
    assert issues(output(),schema({}))==[]
    assert issues(good,schema(dict(title='개발자')))
    # More than 1,000 source lines uses exact finite regex alternatives, not enums.
    many=dict(description_text='\n'.join('항목 '+str(i) if i%11 else '' for i in range(1,1601)))
    long_schema=schema(many)
    pattern=long_schema['$defs']['range_id_description_text']['pattern']
    for n in range(0,1603):
        expected=1<=n<=1600 and n%11!=0
        assert bool(re.fullmatch(pattern,'description_text:'+str(n)))==expected,n
    assert not re.fullmatch(pattern,'other_text:1')
    assert not re.fullmatch(pattern,'description_text:01')
    assert long_schema['$defs']['source_evidence_id']['pattern']==pattern
    long_output=output(ranges=[range_row('description_text:1','description_text:1600')])
    assert issues(long_output,long_schema)==[]
    # Only declared attachment fields participate; source text cannot inject schema.
    attached=dict(_input=dict(contract='attachment-input-v2',fields={'attachment_1_9':{}}),
                  attachment_1_9='첫째\n\n둘째',attachment_2_10='undeclared',other_field='ignored')
    a_schema=schema(attached)
    assert 'range_id_attachment_1_9' in a_schema['$defs']
    assert 'attachment_2_10' not in json.dumps(a_schema)
    context=json.loads(sql(f'SELECT enrichment.source_accounting_context_v1({js(source)})'))
    assert context['narrative_fields']==['description_text','selection_text']
    assert context['metadata_fields']==['title']
    assert frozen==sql("SELECT md5(jsonb_agg(p ORDER BY version,stage)::text) FROM enrichment.prompt p")
    print('Source-bound grammar, exact original IDs, metadata isolation and long-document checks passed',flush=True)


def check_source_bound_native(sql,js,q,run_hop,params,request_count,item):
    check_source_bound(sql,js)
    from document_packet_checks import check_packet_sql, assert_packet
    check_packet_sql(sql,js)
    attempts=json.loads(sql("SELECT jsonb_agg(a) FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) "
        "WHERE b.settings->>'prompt_version'='ko-v7' AND a.stage='extract' AND a.state='VALIDATED'"))
    assert attempts
    for a in attempts:
        schema=a['request_body']['response_format']['json_schema']['schema']
        assert schema['description']=='jobtology:source-bound-ranges-v1'
        assert json.loads(sql(f'SELECT enrichment.schema_issues_request_v1({js(a["raw_output"])},{js(schema)})'))==[]
        context=json.loads(a['request_body']['messages'][1]['content'])['source_accounting']
        assert context['policy']=='source-bound-ranges-v1'
        source=json.loads(sql(f'SELECT source_data FROM enrichment.item WHERE item_id={q(a["item_id"])}'))
        passages=json.loads(sql(f'SELECT enrichment.source_passages_v2({js(source)})'))
        assert_packet(source,json.loads(a['request_body']['messages'][1]['content']),passages)
    categories=json.loads(sql("SELECT jsonb_agg(a.request_body->'messages'->1->>'content') FROM enrichment.attempt a "
        "JOIN enrichment.batch b USING(batch_id) WHERE b.settings->>'prompt_version'='ko-v7' AND a.stage='categorize' AND a.state='VALIDATED'"))
    assert categories
    for content in categories:
        user=json.loads(content)
        assert user['source_encoding']=='field-lines-and-tables-v1'
        assert isinstance(user['source_context']['source_passages'],dict) and 'source_passages' not in user
    before=request_count()
    run_hop('evaluate.hwf',params|dict(EXTRACT_MODEL='test/source-bound-invalid',REUSE_CACHE='N'),
            'source-bound-invalid-response')
    report=json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated']==0 and report['rejected']==2 and report['requests']==2,report
    assert request_count()==before+2
    rejected=json.loads(sql(f"SELECT jsonb_agg(a) FROM enrichment.attempt a WHERE batch_id={q(report['batch_id'])}"))
    # requirements.items is a union: a failed nested ID pattern is reported at
    # that union, while direct position ID failures retain their PATTERN path.
    assert all(a['state']=='REJECTED' and a['issues']==['$.requirements[0]:ANY_OF'] for a in rejected),rejected
    assert all(a['raw_output']['requirements'][0]['evidence_ids']==['eligibility_text:9999'] for a in rejected)
    assert all(a['raw_output'] and a['parsed_output']==a['raw_output'] for a in rejected)
    # Bad reviewer-supplied ranges fail before integer parsing/hydration and cannot
    # create a revision or disturb the previously captured revision.
    latest=json.loads(sql(f"SELECT to_jsonb(r) FROM enrichment.extraction_revision r WHERE item_id={q(item)} ORDER BY revision_no DESC LIMIT 1"))
    bad=copy.deepcopy(latest['raw_output'])
    bad['unhandled_ranges'].append(range_row('eligibility_text:bad-integer'))
    count=sql(f'SELECT count(*) FROM enrichment.extraction_revision WHERE item_id={q(item)}')
    try:
        sql(f"SELECT enrichment.capture_extraction({q(item)},'fixture','Invalid correction must fail',{js(bad)},{q(latest['revision_id'])})")
        raise AssertionError('Invalid correction captured')
    except RuntimeError as e:
        assert 'CORRECTION_NOT_VALIDATED' in str(e) and 'UNKNOWN_RANGE_BOUNDARY' in str(e),str(e)
    assert count==sql(f'SELECT count(*) FROM enrichment.extraction_revision WHERE item_id={q(item)}')
    print('Native source-bound response rejection and invalid-correction history preservation passed',flush=True)
