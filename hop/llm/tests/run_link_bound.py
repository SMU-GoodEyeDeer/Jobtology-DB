"""Focused native linking request constraints; synthetic data, zero paid calls."""
import copy
import json
import os
import subprocess
import time
import run as f


def checks():
    source = dict(title='약무직 채용', eligibility_text='약무직',
                  description_text='약무직\n의약품 재고를 관리한다')
    base = json.loads(f.sql("SELECT output_schema FROM enrichment.prompt WHERE version='ko-link-v1' AND stage='extract'"))
    schema = json.loads(f.sql(f"SELECT enrichment.link_bound_extract_schema_v1({f.js(base)},{f.js(source)})"))

    def shape(output, response_schema=schema):
        return json.loads(f.sql(f"SELECT enrichment.schema_issues_request_v1({f.js(output)},{f.js(response_schema)})"))

    valid = dict(positions=[dict(id='p1', name='약무직', evidence_ids=['eligibility_text:1'])],
                 duties=[dict(position_ids=['p1'], text_parts=['의약품 재고를 관리한다'],
                              evidence_ids=['description_text:2'])], requirements=[], duties_status='explicit')
    assert shape(valid) == [], shape(valid)
    mixed = copy.deepcopy(valid)
    mixed['positions'][0]['evidence_ids'].append('description_text:1')
    assert any('ANY_OF' in x for x in shape(mixed)), shape(mixed)
    assert 'positions:MIXED_EVIDENCE_FIELDS' in json.loads(f.sql(
        f"SELECT enrichment.output_issues_link_v1({f.js(mixed)},{f.js(source)})"))
    unknown = copy.deepcopy(valid)
    unknown['duties'][0]['evidence_ids'] = ['description_text:999']
    assert any('ANY_OF' in x for x in shape(unknown)), shape(unknown)
    assert 'duties:UNKNOWN_EVIDENCE_ID' in json.loads(f.sql(
        f"SELECT enrichment.output_issues_link_v1({f.js(unknown)},{f.js(source)})"))
    non_duty = copy.deepcopy(valid)
    non_duty['duties'][0]['evidence_ids'] = ['title:1']
    assert any('ANY_OF' in x for x in shape(non_duty)), shape(non_duty)
    unsupported = copy.deepcopy(valid)
    unsupported['positions'][0]['name'] = '약무직원'
    assert shape(unsupported) == []  # Exact quotation still requires source validation.
    assert 'positions:UNSUPPORTED_TEXT' in json.loads(f.sql(
        f"SELECT enrichment.output_issues_link_v1({f.js(unsupported)},{f.js(source)})"))

    extraction = dict(duties=[{}, {}, {}])
    candidates = [dict(code='2001020101_24v1'), dict(code='2001020102_24v1')]
    base_cat = json.loads(f.sql("SELECT output_schema FROM enrichment.prompt WHERE version='ko-link-v1' AND stage='categorize'"))
    cat_schema = json.loads(f.sql(f"SELECT enrichment.link_bound_categorize_schema_v1({f.js(base_cat)},{f.js(extraction)},{f.js(candidates)},2)"))
    good = dict(matches=[dict(competency_code=candidates[0]['code'], duty_index=2, reason='실제 업무 중첩')], outcome='matched')
    assert shape(good, cat_schema) == []
    for field, value, expected in [('competency_code', 'outside-shortlist', 'ENUM'),
                                   ('duty_index', 3, 'NUMBER_RANGE')]:
        bad = copy.deepcopy(good)
        bad['matches'][0][field] = value
        assert any(expected in x for x in shape(bad, cat_schema)), (field, shape(bad, cat_schema))
    too_many = copy.deepcopy(good)
    too_many['matches'] = too_many['matches'] * 3
    assert any('TOO_MANY_ITEMS' in x for x in shape(too_many, cat_schema))
    rendered_source = dict(description_text='직무내용 | 자재의 운반,<br><br>교통통제, 작업준비')
    rendered = dict(positions=[], duties=[dict(position_ids=[],
                    text_parts=['자재의 운반, 교통통제, 작업준비'],
                    evidence_ids=['description_text:1'])], requirements=[], duties_status='explicit')
    proposed = json.loads(f.sql(f"SELECT enrichment.suggest_rendered_fragment_revision_v1({f.js(rendered)},{f.js(rendered_source)})"))
    assert proposed['duties'][0]['text_parts'] == ['자재의 운반,', '교통통제, 작업준비'], proposed
    assert f.sql(f"SELECT enrichment.output_issues_link_v1({f.js(proposed)},{f.js(rendered_source)})") == '[]'
    newline_source = dict(description_text='조직 내부<br><br>와 외부에서 요청하거나 필요한 업무를 지원하고 관리')
    newline_join = dict(positions=[], duties=[dict(position_ids=[],
                        text_parts=['조직 내부\n\n와 외부에서 요청하거나 필요한 업무를 지원하고 관리'],
                        evidence_ids=['description_text:1'])], requirements=[], duties_status='explicit')
    newline_proposal = json.loads(f.sql(f"SELECT enrichment.suggest_rendered_fragment_revision_v1("
                                        f"{f.js(newline_join)},{f.js(newline_source)})"))
    assert newline_proposal['duties'][0]['text_parts'] == [
        '조직 내부','와 외부에서 요청하거나 필요한 업무를 지원하고 관리'], newline_proposal
    assert f.sql(f"SELECT enrichment.output_issues_link_v1({f.js(newline_proposal)},{f.js(newline_source)})") == '[]'
    unrelated = dict(description_text='직무내용 | 자재의 운반,<br>다른 업무<br>교통통제, 작업준비')
    assert f.sql(f"SELECT enrichment.suggest_rendered_fragment_revision_v1({f.js(rendered)},{f.js(unrelated)})") == ''
    print('Synthetic extract/category constraints and retained source checks passed', flush=True)

    endpoint = f.stage()
    f.run_hop('install.hwf', {}, 'link-bound-native-installer')
    f.run_hop('install_link_bound.hwf', {}, 'link-bound-targeted-installer')
    params = dict(JOB_RUN_ID='test-jobs', NCS_RUN_ID='test-ncs', POSTING_LIMIT=2,
                  PROMPT_VERSION='ko-link-v1', EXECUTE_REQUESTS='Y',
                  ENDPOINT=endpoint, API_KEY_FILE=f.REMOTE+'/key.csv',
                  EXTRACT_MODEL='test/extractor', CATEGORIZE_MODEL='test/categorizer',
                  ACCEPTANCE_POLICY='REVIEW', REQUEST_DELAY_MS=1, READ_TIMEOUT_MS=5000)
    f.run_hop('enrich.hwf', params, 'link-bound-native-enrich')
    bodies = json.loads(f.sql("SELECT jsonb_agg(jsonb_build_object('stage',a.stage,'state',a.state,"
                              "'schema',a.request_body#>'{response_format,json_schema,schema}')) "
                              "FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) "
                              "WHERE b.settings->>'prompt_version'='ko-link-v1'"))
    assert bodies and all(x['schema']['description']=='jobtology:link-bound-v1' for x in bodies), bodies
    assert all(x['state'] in ('VALIDATED','SKIPPED') for x in bodies), bodies
    assert any(x['stage']=='categorize' and 'enum' in x['schema']['properties']['matches']['items']['properties']['competency_code']
               for x in bodies if x['state']=='VALIDATED'), bodies
    aid = f.sql("SELECT a.attempt_id FROM enrichment.attempt a WHERE a.stage='categorize' AND a.state='VALIDATED' "
                "AND a.request_body#>>'{response_format,json_schema,schema,description}'='jobtology:link-bound-v1' LIMIT 1")
    envelope = json.loads(f.sql(f"SELECT response_body FROM enrichment.attempt WHERE attempt_id={f.q(aid)}"))
    generated = json.loads(envelope['choices'][0]['message']['content'])
    assert generated['matches'], generated
    generated['matches'].append(copy.deepcopy(generated['matches'][0]))
    envelope['choices'][0]['message']['content'] = json.dumps(generated,ensure_ascii=False)
    f.sql(f"UPDATE enrichment.attempt SET state='RESERVED' WHERE attempt_id={f.q(aid)}; "
          f"SELECT enrichment.save_response({f.q(aid)},200,{f.q(json.dumps(envelope,ensure_ascii=False))},1000)")
    normalized = json.loads(f.sql(f"SELECT jsonb_build_object('state',state,'raw',jsonb_array_length(raw_output->'matches'),"
                                  f"'parsed',jsonb_array_length(parsed_output->'matches'),'note',normalization) "
                                  f"FROM enrichment.attempt WHERE attempt_id={f.q(aid)}"))
    assert normalized == dict(state='VALIDATED',raw=2,parsed=1,
                              note=dict(policy='exact-match-object-dedup-v1',removed=1)), normalized
    # A rejected link extraction can be retried with its exact prior diagnostics.
    # A later pending revision protects the same source from automatic re-extraction.
    old = json.loads(f.sql("SELECT jsonb_build_object('batch',i.batch_id,'item',i.item_id,"
                           "'posting',i.posting_id,'attempt',i.extraction_id) "
                           "FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) "
                           "WHERE b.settings->>'prompt_version'='ko-link-v1' ORDER BY i.ordinal LIMIT 1"))
    issues = ['duties:UNSUPPORTED_FRAGMENT']
    f.sql(f"UPDATE enrichment.attempt SET state='REJECTED',issues={f.js(issues)} "
          f"WHERE attempt_id={f.q(old['attempt'])}")
    assert json.loads(f.sql(f"SELECT enrichment.repair_reasons_v6({f.q(old['item'])})")) == issues
    opts = json.loads(f.sql(f"SELECT settings FROM enrichment.batch WHERE batch_id={f.q(old['batch'])}"))
    repair = 'link-bound-repair-'+os.urandom(8).hex()
    repair_opts = opts|dict(repair_batch_id=old['batch'],posting_ids=old['posting'],
                            execute_requests='Y',reuse_cache='N')
    f.sql(f"SELECT enrichment.plan_batch({f.q(repair)},'ENRICH',NULL,'test-jobs','test-ncs',"
          f"{f.js(repair_opts)}); "
          f"SELECT enrichment.plan_stage({f.q(repair)},'extract')")
    feedback = json.loads(f.sql(f"SELECT (a.request_body#>>'{{messages,1,content}}')::jsonb->'repair_context' "
                                f"FROM enrichment.attempt a WHERE a.batch_id={f.q(repair)} AND a.stage='extract'"))
    assert feedback['validator_issues'] == issues and feedback['previous_output'], feedback
    f.sql(f"INSERT INTO enrichment.extraction_revision(revision_id,item_id,raw_output,extraction,actor,reason) "
          f"VALUES({f.q('link-bound-pending-'+old['item'])},{f.q(old['item'])},'{{}}','{{}}',"
          f"'fixture','Pending source review')")
    assert f.sql(f"SELECT enrichment.repair_reasons_v6({f.q(old['item'])}) IS NULL") == 't'
    repair_attempt = f.sql(f"SELECT attempt_id FROM enrichment.attempt "
                           f"WHERE batch_id={f.q(repair)} AND stage='extract'")
    f.sql(f"SELECT enrichment.reserve_request({f.q(repair_attempt)})")
    blocked = json.loads(f.sql(f"SELECT jsonb_build_object('state',state,'issues',issues,'reserved',reserved_at IS NOT NULL) "
                               f"FROM enrichment.attempt WHERE attempt_id={f.q(repair_attempt)}"))
    assert blocked == dict(state='ERROR',issues=['NOT_SENT','REPAIR_INPUT_SUPERSEDED_OR_PROTECTED'],
                           reserved=False), blocked
    print('Native Hop saved request schemas and mock validation passed', flush=True)


def main():
    created=[]
    network=False
    try:
        assert subprocess.run(['docker','inspect',f.PG],capture_output=True).returncode
        assert subprocess.run(['docker','inspect',f.HOP],capture_output=True).returncode
        if subprocess.run(['docker','network','inspect',f.PREFIX],capture_output=True).returncode:
            f.cmd(['docker','network','create','--internal',f.PREFIX]); network=True
        for name,image,args in [(f.PG,'postgres:17-alpine',['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=hoptest']),
                                (f.HOP,'apache/hop:2.19.0',['--entrypoint','/bin/sleep'])]:
            f.cmd(['docker','run','-d','--name',name,'--network',f.PREFIX]+args+[image]+(['infinity'] if name==f.HOP else []))
            created.append(name)
        for _ in range(90):
            if subprocess.run(['docker','exec',f.PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1',
                               '-U','postgres','-d','hoptest','-c','SELECT 1'],
                              capture_output=True).returncode==0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Disposable PostgreSQL did not become ready')
        f.seed()
        checks()
        print('LINK-BOUND FOCUSED CHECKS PASSED',f.WORK,flush=True)
    finally:
        if not os.environ.get('KEEP_LLM_TEST_CONTAINERS'):
            if subprocess.run(['docker','inspect',f.MOCK],capture_output=True).returncode==0: created.append(f.MOCK)
            if created: subprocess.run(['docker','rm','-fv']+created,capture_output=True)
            if network: subprocess.run(['docker','network','rm',f.PREFIX],capture_output=True)


if __name__=='__main__': main()
