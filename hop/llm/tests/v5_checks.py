"""Clause-scope regressions and append-only repair/revalidation; no paid calls."""
import copy
import json
import uuid


def atom(text):
    return dict(op='atom', parts=[text], children=[])


def output(text, field='disqualification_text', kind='eligibility', logic='single', expression=None, ids=None):
    return dict(positions=[], duties=[], duties_status='not_stated', requirements=[dict(
        position_ids=[], category='other', kind=kind, logic=logic, text_parts=[text],
        evidence_ids=ids or [field+':1'], expression=expression or [])])


def fixtures():
    positive = '병역의무를 기피한 사실이 없는 자'
    bar = '징계를 받은 사람은 지원할 수 없음'
    law = '다음 중 하나에 해당하는 자:\n「지원 및 보훈에 관한 법률」 대상자\n장애인'
    parent = '다음 각 목의 어느 하나에 해당하는 죄로 100만원 이상의 벌금형을 선고받은 후 3년이 지나지 아니한 사람'
    children = ['성폭력범죄', '스토킹범죄']
    law_output = output(law, 'eligibility_text', logic='any_of', expression=[
        dict(op='any_of', parts=[], children=[1, 2]), atom('「지원 및 보훈에 관한 법률」 대상자'), atom('장애인')])
    law_output['requirements'][0].update(text_parts=['「지원 및 보훈에 관한 법률」 대상자', '장애인'],
        evidence_ids=['eligibility_text:1', 'eligibility_text:2', 'eligibility_text:3'])
    missing = output('성폭력범죄 스토킹범죄', kind='exclusion', logic='any_of', ids=['disqualification_text:2', 'disqualification_text:3'], expression=[
        dict(op='any_of', parts=[], children=[1, 2]), *map(atom, children)])
    missing['requirements'][0]['text_parts'] = children
    nested_source = dict(disqualification_text='10) '+parent+'\n가. '+children[0]+'\n나. '+children[1])
    return {
        'positive': (dict(disqualification_text=positive), output(positive)),
        'bar': (dict(disqualification_text=bar), output(bar)),
        'law': (dict(eligibility_text=law), law_output),
        'parent': (nested_source, missing),
    }


def check_v5_text(sql, js):
    def issues(o, s, version=5):
        return json.loads(sql(f'SELECT enrichment.output_issues_v{version}({js(o)},{js(s)})'))
    cases = fixtures()
    for name in ('positive', 'law'):
        source, value = cases[name]
        assert issues(value, source, 4), name+' did not reproduce the old guard'
        assert issues(value, source) == [], (name, issues(value, source))
        assert issues(value, source, 4), 'Old validator changed'
    source, value = cases['bar']
    assert 'requirements:EXCLUSION_AS_ELIGIBILITY' in issues(value, source)
    fixed = copy.deepcopy(value); fixed['requirements'][0]['kind'] = 'exclusion'
    assert issues(fixed, source) == [], issues(fixed, source)
    source, value = cases['positive']
    bad = copy.deepcopy(value); bad['requirements'][0]['kind'] = 'exclusion'
    assert 'requirements:ABSENCE_AS_EXCLUSION' in issues(bad, source)
    mixed = '결격사유가 없는 자도 징계를 받은 사람은 지원할 수 없음'
    assert 'requirements:MIXED_POLARITY_REVIEW_REQUIRED' in issues(output(mixed), dict(disqualification_text=mixed))
    conjunction = '자격증 및 경력을 모두 보유한 자'
    wrong_or = output(conjunction, 'eligibility_text', logic='any_of', expression=[
        dict(op='any_of', parts=[], children=[1, 2]), atom('자격증'), atom('경력')])
    assert 'requirements:OR_FOR_AND_ONLY' in issues(wrong_or, dict(eligibility_text=conjunction))
    source, missing = cases['parent']
    assert issues(missing, source, 4) == [], issues(missing, source, 4)
    found = issues(missing, source)
    assert 'requirements:PARENT_CONTEXT_NOT_CITED' in found and 'requirements:PARENT_CONDITION_OMITTED' in found, found
    cited = copy.deepcopy(missing); req = cited['requirements'][0]
    req['evidence_ids'].insert(0, 'disqualification_text:1')
    assert 'requirements:PARENT_CONDITION_OMITTED' in issues(cited, source)
    parent = source['disqualification_text'].splitlines()[0][4:]
    req['text_parts'].insert(0, parent)
    assert 'requirements:SHARED_CONDITION_SCOPE_REVIEW_REQUIRED' in issues(cited, source)
    req.update(logic='all_of', expression=[dict(op='all_of', parts=[], children=[1, 2]), atom(parent),
        dict(op='any_of', parts=[], children=[3, 4]), atom('성폭력범죄'), atom('스토킹범죄')])
    assert issues(cited, source) == [], issues(cited, source)
    # A different numbered heading breaks the parent-child association.
    separated = dict(disqualification_text=source['disqualification_text'].replace('\n가.', '\n11) 다른 독립 조건\n가.'))
    detached = copy.deepcopy(missing); detached['requirements'][0]['evidence_ids'] = ['disqualification_text:3', 'disqualification_text:4']
    assert not any('PARENT_' in e for e in issues(detached, separated))
    bad = copy.deepcopy(cited); bad['requirements'][0]['expression'][3]['parts'] = ['존재하지 않는 경력']
    assert 'expression:UNSUPPORTED_FRAGMENT' in issues(bad, source)
    hydrated = json.loads(sql(f'SELECT enrichment.hydrate_v5({js(cited)},{js(source)})'))
    assert hydrated['schema_version'] == 'ko-v5' and hydrated['validation_policy'] == 'clause-scope-v5'
    assert hydrated['requirements'][0]['expression'][1]['text'] == parent
    print('V5 polarity, quoted titles, actual AND, shared parent evidence/conditions and legacy isolation passed', flush=True)


def check_v5(sql, js, q, run_hop, params, request_count):
    check_v5_text(sql, js)
    def fails(query, expected):
        try:
            sql(query)
            raise AssertionError('Expected '+expected)
        except RuntimeError as e:
            assert expected in str(e), str(e)
    run_hop('evaluate.hwf', params | dict(PROMPT_VERSION='ko-v5'), 'v5-native-two-stage')
    report = json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert report['validated'] == 2 and report['requests'] == 3, report
    opts = report['settings'] | dict(prompt_version='ko-v4', reuse_cache='N', limit=6)
    fails(f"SELECT enrichment.plan_batch('v5-unsafe','ENRICH',NULL,'LATEST','LATEST',{js(opts | dict(prompt_version='ko-v5', acceptance_policy='VALIDATED'))})", 'V5_REQUIRES_INDEPENDENT_SEMANTIC_REVIEW')
    # Dedicated source fixtures are separate from the native two-posting dataset.
    jobs = 'v5-jobs-'+uuid.uuid4().hex; bid = 'v5-audit-'+uuid.uuid4().hex
    sql(f"""INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES({q(jobs)},'job_alio','FULL','test','READY');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(jobs)},'test','FILE',1);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected)
VALUES({q(jobs)},'test','test',1,'v5-synthetic.json',repeat('0',64),1,'UTF-8',200,now(),true);""")
    cases = fixtures() | {'missing': (dict(title='행정 채용', eligibility_text='직무는 첨부파일 참조.'), None),
        'unknown': (dict(title='회계 채용', eligibility_text='직무는 첨부파일 참조.'), None)}
    for name, (source, _) in cases.items():
        for representation in ('list', 'detail'):
            data = source | dict(posting_id=name, representation=representation)
            sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(jobs)},'test',{q(name+representation)},{q(name+':'+representation)},'{{}}',{js(data)})")
    sql(f"SELECT enrichment.plan_batch({q(bid)},'ENRICH',NULL,{q(jobs)},'test-ncs',{js(opts)}); SELECT enrichment.plan_stage({q(bid)},'extract')")
    fails(f"SELECT enrichment.audit_extractions({q(bid)})", 'AUDIT_REQUIRES_TERMINAL_BATCH')
    ids = {}
    for name, (_, raw) in cases.items():
        ids[name] = json.loads(sql(f"SELECT jsonb_build_object('item',item_id,'attempt',extraction_id) FROM enrichment.item WHERE batch_id={q(bid)} AND posting_id={q(name)}"))
        aid = q(ids[name]['attempt'])
        sql(f'SELECT enrichment.reserve_request({aid})')
        if name == 'unknown':
            continue
        body = dict(id='synthetic-'+name, choices=[dict(finish_reason='stop', message=dict(content=json.dumps(raw, ensure_ascii=False)))], usage=dict(cost=.001))
        sql(f'SELECT enrichment.save_response({aid},{0 if raw is None else 200},{q(json.dumps(body, ensure_ascii=False))},1)')
    sql(f'SELECT enrichment.finish_batch({q(bid)},true)')
    assert sql(f"SELECT state FROM enrichment.attempt WHERE attempt_id={q(ids['parent']['attempt'])}") == 'VALIDATED'
    def snapshot():
        return sql(f"SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_id) FROM enrichment.attempt a WHERE batch_id={q(bid)}")
    before = snapshot(); http_before = request_count()
    run_hop('audit_batch.hwf', dict(BATCH_ID=bid), 'v5-audit-saved-responses')
    audits = json.loads(sql(f"SELECT jsonb_object_agg(i.posting_id,a.issues) FROM enrichment.item i JOIN enrichment.extraction_audit a ON a.attempt_id=i.extraction_id WHERE i.batch_id={q(bid)}"))
    assert set(audits) == set(cases)-{'unknown'}, audits
    assert audits['positive'] == [] and audits['law'] == [] and audits['bar'] and audits['parent'], audits
    assert audits['missing'] == ['MISSING_PROVIDER_OUTPUT']
    assert sql(f"SELECT enrichment.audit_extractions({q(bid)})") == '0'
    fails(f"SELECT enrichment.audit_extractions({q(bid)},NULL)", 'UNSUPPORTED_AUDIT_CONTRACT')
    bad_item = q(ids['bar']['item']); good_item = q(ids['positive']['item'])
    fails(f"SELECT enrichment.capture_revalidated({bad_item},'fixture','test')", 'REVALIDATION_NOT_CLEAN_OR_CHANGED')
    fails(f"SELECT enrichment.capture_clean_audit({q(bid)},'','test')", 'REVIEW_PROVENANCE_REQUIRED')
    fails(f"BEGIN; INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason) "
        f"VALUES('v5-existing-manual',{good_item},'{{}}','{{}}','fixture','Existing revision must survive'); "
        f"SELECT enrichment.capture_revalidated({good_item},'tester','Must not displace it'); ROLLBACK",
        'EXISTING_REVISION_REQUIRES_EXPLICIT_CORRECTION')
    run_hop('capture_audited.hwf', dict(BATCH_ID=bid, ACTOR='synthetic-auditor', REASON='Fixture revalidation only'), 'v5-capture-clean-audit')
    assert sql(f"SELECT enrichment.capture_clean_audit({q(bid)},'tester','Replay')") == '0'
    rows = json.loads(sql(f"SELECT jsonb_agg(to_jsonb(r)) FROM enrichment.extraction_revision r JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(bid)}"))
    assert len(rows) == 2
    for row in rows:
        assert row['extraction']['provider_prompt_version'] == 'ko-v4'
        assert row['extraction']['schema_version'] == 'ko-v5'
        assert row['extraction']['revalidation']['original_state'] == 'REJECTED'
    rid = sql(f"SELECT enrichment.capture_revalidated({good_item},'tester','Replay')")
    assert rid in {row['revision_id'] for row in rows}
    assert sql(f"SELECT count(*) FROM enrichment.extraction_decision d JOIN enrichment.extraction_revision r USING(revision_id) JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(bid)}") == '0'
    assert sql(f"SELECT count(*) FROM enrichment.review r JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(bid)}") == '0'
    fails(f"UPDATE enrichment.extraction_audit SET issues='[]' WHERE attempt_id={q(ids['bar']['attempt'])}", 'APPEND_ONLY_REVIEW_HISTORY')
    fails(f"BEGIN; UPDATE enrichment.item SET source_data=source_data||'{{\"title\":\"changed\"}}' WHERE item_id={good_item}; SELECT enrichment.capture_revalidated({good_item},'tester','Changed source'); ROLLBACK", 'REVALIDATION_NOT_CLEAN_OR_CHANGED')
    fails(f"BEGIN; UPDATE enrichment.attempt SET raw_output='{{}}' WHERE attempt_id={q(ids['bar']['attempt'])}; SELECT enrichment.audit_extractions({q(bid)}); ROLLBACK", 'AUDIT_INPUT_CHANGED')
    # Repair picks genuine old failures and old VALIDATED results newly caught by v5.
    repair_opts = opts | dict(prompt_version='ko-v5', repair_batch_id=bid, execute_requests='N')
    def plan(options, mode='ENRICH', source=jobs, dataset=None):
        new = 'v5-repair-'+uuid.uuid4().hex
        sql(f"SELECT enrichment.plan_batch({q(new)},{q(mode)},{q(dataset) if dataset else 'NULL'},{q(source)},'test-ncs',{js(options)})")
        return new
    repair = plan(repair_opts)
    picked = json.loads(sql(f"SELECT jsonb_agg(posting_id ORDER BY posting_id) FROM enrichment.item WHERE batch_id={q(repair)}"))
    assert picked == ['bar', 'missing', 'parent'], picked
    assert sql(f"SELECT count(*) FROM enrichment.repair_item r JOIN enrichment.item i USING(item_id) WHERE i.batch_id={q(repair)}") == '3'
    for selection, expected in [('bar|bar', 'INVALID_POSTING_SELECTION'), ('bar|absent', 'SELECTED_POSTING_MISSING_OR_NOT_REPAIRABLE'),
        ('bar|positive', 'SELECTED_POSTING_MISSING_OR_NOT_REPAIRABLE'), ('positive', 'NO_POSTINGS_FOR_LLM_BATCH'), ('unknown', 'NO_POSTINGS_FOR_LLM_BATCH')]:
        try: plan(repair_opts | dict(posting_ids=selection)); raise AssertionError('Accepted '+selection)
        except RuntimeError as e: assert expected in str(e), str(e)
    try: plan(repair_opts, source='test-jobs'); raise AssertionError('Changed repair source')
    except RuntimeError as e: assert 'REPAIR_SOURCE_PIN_MISMATCH' in str(e), str(e)
    try: plan(repair_opts, mode='EVAL', dataset='test-ko'); raise AssertionError('Cross-mode repair')
    except RuntimeError as e: assert 'REPAIR_MODE_OR_DATASET_MISMATCH' in str(e), str(e)
    sql(f"SELECT enrichment.plan_stage({q(repair)},'extract')")
    feedback = json.loads(sql(f"SELECT (a.request_body#>>'{{messages,1,content}}')::jsonb->'repair_context' FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id WHERE i.batch_id={q(repair)} AND i.posting_id='bar'"))
    assert feedback['previous_output'] == cases['bar'][1] and feedback['validator_issues'] == audits['bar']
    small = plan(repair_opts | dict(posting_ids='bar', max_input_chars=1000))
    sql(f"SELECT enrichment.plan_stage({q(small)},'extract')")
    assert sql(f"SELECT state='REJECTED' AND issues ? 'INPUT_TOO_LARGE' AND request_body#>>'{{messages,1,content}}' LIKE '%previous_output%' FROM enrichment.attempt WHERE batch_id={q(small)}") == 't'
    assert snapshot() == before and request_count() == http_before, 'Audit/revalidation/planning mutated attempts or made HTTP calls'
    # Native targeted repair executes just the selected missing-output item.
    run_hop('enrich.hwf', params | dict(JOB_RUN_ID=jobs, NCS_RUN_ID='test-ncs', PROMPT_VERSION='ko-v5',
        POSTING_IDS='missing', REPAIR_BATCH_ID=bid, POSTING_LIMIT=1), 'v5-native-targeted-repair')
    latest = json.loads(sql('SELECT to_jsonb(r) FROM enrichment.batch_report r ORDER BY created_at DESC LIMIT 1'))
    assert latest['postings'] == 1 and latest['validated'] == 1 and latest['requests'] == 1, latest
    assert request_count() == http_before+1 and snapshot() == before
    eval_item = sql(f"SELECT item_id FROM enrichment.item WHERE batch_id={q(report['batch_id'])} ORDER BY ordinal LIMIT 1")
    fails(f"SELECT enrichment.capture_revalidated({q(eval_item)},'tester','EVAL isolation')", 'EVAL_CANNOT_ENTER_PRODUCTION_REVIEW')
    print('V5 native audit, revalidation, source hashes, append-only history, selected repairs, paid-call isolation and EVAL safety passed', flush=True)
