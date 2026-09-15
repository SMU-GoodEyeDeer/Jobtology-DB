"""Frozen derived-claim reads in isolated PostgreSQL and native Hop.

Run separately with `occupations` and `requirements`; each driver owns fresh
container names before importing native helpers. Synthetic inline evidence only.
"""
from pathlib import Path
import base64
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'hop/ontology/tests'))
import run


def combined_source(sources, outputs):
    """Add a literal experience condition to one synthetic AI posting only."""
    text = '경력 2년 이상 및 Python 사용 경험'
    for row in sources['job_alio']:
        if row['posting_id'] == '001':
            row['eligibility_text'] += '\n'+text
    outputs['001']['requirements'] = [dict(position_ids=['p1'], category='qualification',
        kind='eligibility', logic='all_of', evidence_ids=['eligibility_text:2'], text_parts=[text],
        expression=[dict(op='all_of', parts=[], children=[1,2]),
                    dict(op='atom', parts=['경력 2년 이상'], children=[]),
                    dict(op='atom', parts=['Python 사용 경험'], children=[])])]


def check(native, mode):
    sql, q, err = run.sql, run.q, run.expect_error
    read = lambda expression: json.loads(sql('SELECT '+expression))
    release = 'roles-v1' if mode == 'occupations' else 'review-after-link-rejection'
    if mode == 'requirements':
        native.run('../editorial/install.hwf', {}, 'derived-read-native-install')
    entity = 'urn:jobtology:jobPosting:job_alio:001'
    def page(name=release, subject=None, kind=None, size=1, cursor=None):
        args = [q(name), q(subject) if subject else 'NULL', q(kind) if kind else 'NULL', str(size), q(cursor) if cursor else 'NULL', 'true']
        return read('ontology.query_derived_claims_v1('+','.join(args)+')')
    def detail(cid, name=release):
        return read('ontology.query_derived_claim_v1('+q(name)+','+q(cid)+',true)')['claim']
    # A new freeze changes release scope and invalidates old cursors. The mixed
    # fixture also proves both kinds can be returned for the same posting.
    if mode == 'occupations':
        before_freeze = page()
        assert before_freeze['next_cursor'] and before_freeze['derived_memberships']['requirements']['status'] == 'NOT_FROZEN'
        empty = json.loads(sql("BEGIN; SELECT ontology.freeze_requirements_v1('roles-v1'); "
            "SELECT ontology.query_summary_v3('roles-v1',true); ROLLBACK").strip())
        assert empty['derived_memberships']['requirements']['status'] == 'FROZEN'
        assert 'NORMALIZED_REQUIREMENT' not in empty['derived_claim_counts']
        atom = read("(SELECT to_jsonb(a) FROM ontology.requirement_atom a WHERE release_id='roles-v1' AND source_text='경력 2년 이상')")
        document = dict(schema_version='hop-requirement-normalization-v1',release_id='roles-v1',
            source_claim_id=atom['source_claim_id'],node_index=atom['node_index'],parent_id=None,
            actor='fixture-normalization-author',reason='Synthetic literal minimum experience condition.',
            resolver_version='fixture-read-v1',necessity='REQUIRED',polarity='POSITIVE',
            condition=dict(kind='EXPERIENCE',context_id=None,minimum_months=24,maximum_months=None))
        normalization = sql('SELECT ontology.capture_requirement_v1('+run.js(document)+')')
        sql('SELECT ontology.decide_requirement_v1('+q(normalization)+",'ACCEPT','fixture-normalization-reviewer','human','Synthetic independent condition review')")
        sql("SELECT ontology.freeze_requirements_v1('roles-v1')")
        err("SELECT ontology.query_derived_claims_v1('roles-v1',NULL,NULL,1,"+q(before_freeze['next_cursor'])+",true)", 'INVALID_ONTOLOGY_CURSOR')
        assert page()['derived_memberships']['requirements']['status'] == 'FROZEN'
    # Seal one fixture to exercise the manifest-bound read path without Neo4j or activation.
    sealed_release = release if mode == 'occupations' else 'review-fixture'
    sql('SELECT ontology.seal_graph('+q(sealed_release)+')')
    legacy = 'derived-read-legacy'
    sql('SELECT ontology.prepare_release('+q(legacy)+'); SELECT ontology.assemble_sources('+q(legacy)+')')

    tables = sql("SELECT quote_ident(schemaname)||'.'||quote_ident(tablename) FROM pg_tables "
                 "WHERE schemaname IN ('ontology','editorial','ingestion','enrichment','attachment') ORDER BY 1").splitlines()
    def fingerprint():
        union = ' UNION ALL '.join('SELECT '+q(t)+" AS name,ontology.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')) AS h FROM "+t+' t' for t in tables)
        return sql('SELECT ontology.hash(jsonb_object_agg(name,h)) FROM ('+union+') t')
    original = fingerprint()
    first = page(); rows = first['items']; cursor = first['next_cursor']
    while cursor:
        next_page = page(cursor=cursor)
        rows += next_page['items']; cursor = next_page['next_cursor']
    assert len(rows) == len({r['claim_id'] for r in rows}) == first['total']
    expected_counts = {'PRIMARY_OCCUPATION':4,'NORMALIZED_REQUIREMENT':1} if mode == 'occupations' else {'NORMALIZED_REQUIREMENT':2}
    assert len(rows) == sum(expected_counts.values())
    assert first['contract_version'] == 'hop-ontology-read-v3'
    assert first['read_mode'] == 'PREVIEW'
    expected_kind = 'PRIMARY_OCCUPATION' if mode == 'occupations' else 'NORMALIZED_REQUIREMENT'
    assert {r['claim_kind'] for r in rows} == set(expected_counts)
    for kind in ['NORMALIZED_REQUIREMENT', 'PRIMARY_OCCUPATION']:
        assert len(page(kind=kind, size=100)['items']) == expected_counts.get(kind,0)
    assert len(page(subject=entity, size=100)['items']) == 2
    for r in rows:
        d = detail(r['claim_id'])
        assert all(d[k] == v for k, v in r.items())
        assert d['confidence'] is None and d['confidence_state'] == 'UNASSESSED'
        assert d['review']['decision'] == 'ACCEPT'
        assert d['review_status'] == ('HUMAN_ACCEPTED' if d['review']['reviewer_kind'] == 'human' else 'ASSISTANT_REVIEWED')
        assert d['source_binding_hash'] == sql('SELECT ontology.hash('+run.js(d['source_binding'])+')')
        assert d['evidence'], 'An accepted derived claim lost its exact source evidence'
        for e in d['evidence']:
            span = e['evidence']
            text = sql('SELECT normalized_text FROM ontology.text_artifact WHERE artifact_id='+q(span['artifact_id']))
            assert text[span['start_offset']:span['end_offset']] == span['excerpt']
            assert e['artifact']['posting_entity_id'] == r['entity_id']
            assert e['source_records'] and e['document'] is None, 'Only synthetic inline fixture input is permitted'
        for target in d['targets']:
            actual = read('(SELECT to_jsonb(r)-\'created_at\' FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id) WHERE m.release_id='+q(release)+' AND m.entity_id='+q(target['entity_id'])+')')
            assert target['revision'] == actual
            assert actual['revision_id'] == target['revision_id'] and actual['payload_hash'] == target['payload_hash']
        if r['claim_kind'] == 'PRIMARY_OCCUPATION':
            assert len(d['targets']) == 1 and len(d['catalogue_binding']['definitions']) == 5
            assert d['catalogue_binding_hash'] == sql('SELECT ontology.hash('+run.js(d['catalogue_binding'])+')')
            assert len(d['source_binding']['duties']) == 1 and d['source_binding']['positions']
            assert d['targets'][0]['source_support'][0]['support_kind'] == 'EDITORIAL_ENTRY'
            assert d['targets'][0]['revision']['name'] == r['occupation']['name']
            assert d['proposal'] == read('(SELECT document FROM ontology.occupation_proposal WHERE proposal_id='+q(d['proposal_id'])+')')
            if r['entity_id'].endswith(':004'):
                assert d['proposal']['model_id'] == 'fixture/not-a-live-model'
                assert d['assertion_kind'] == 'MODEL_INFERRED' and d['review_status'] == 'ASSISTANT_REVIEWED'
        else:
            n = read('(SELECT to_jsonb(n) FROM ontology.requirement_normalization n WHERE normalization_id='+q(d['normalization_id'])+')')
            assert d['source_binding'] == n['source_binding'] and d['proposal'] == n['document']
            assert d['target_bindings_hash'] == sql('SELECT ontology.hash('+run.js(n['target_bindings'])+')')
            assert len(d['source_binding']['positions']) == 1
            assert len(d['source_binding']['expression_edges']) == (4 if mode == 'requirements' else 2)
            assert {x['operator'] for x in d['source_binding']['expression_nodes']} == ({'all_of','any_of','atom'} if mode == 'requirements' else {'all_of','atom'})
            assert d['necessity'] == 'REQUIRED' and d['polarity'] == 'POSITIVE'
            assert [e['evidence']['excerpt'] for e in d['evidence']] == [e['span']['excerpt'] for e in n['source_binding']['evidence']]
        graph = read('(SELECT properties FROM ontology.graph_node WHERE release_id='+q(sealed_release)+' AND node_id='+q(r['graph_node_id'])+')') if release == sealed_release else None
        if graph is not None:
            assert graph['claim_id'] == r['claim_id'] and graph['review_status'] == r['review_status']

    old = read('ontology.query_entity_v2('+q(release)+','+q(entity)+',true)')
    new = read('ontology.query_entity_v3('+q(release)+','+q(entity)+',true)')
    for key in old:
        if key != 'contract_version':
            assert new[key] == old[key], 'Changed original v2 field '+key
    assert new['entity']['payload'] == old['entity']['payload']
    assert new['derived_claims']['total'] == 2
    assert (new['primary_occupation'] is not None) == (mode == 'occupations')
    assert new['derived_memberships']['occupations']['status'] == ('FROZEN' if mode == 'occupations' else 'NOT_FROZEN')
    summary = read('ontology.query_summary_v3('+q(release)+',true)')
    assert summary['derived_claim_counts'] == expected_counts
    assert summary['publication_issues'], 'These fixtures must never be considered publication-ready'
    empty = page(name=legacy)
    assert empty['items'] == [] and empty['total'] == 0 and empty['next_cursor'] is None
    assert all(m['status'] == 'NOT_FROZEN' and m['membership_hash'] is None for m in empty['derived_memberships'].values())
    # Pending/rejected/stale choices do not fall back to an older accepted claim.
    if mode == 'occupations':
        old_claim = new['primary_occupation']['claim_id']
        for name in ['roles-pending', 'roles-rejected', 'roles-source-changed', 'roles-duties-changed', 'roles-catalogue-changed']:
            state = read('ontology.query_entity_v3('+q(name)+','+q(entity)+',true)')
            assert state['primary_occupation'] is None
            err('SELECT ontology.query_derived_claim_v1('+q(name)+','+q(old_claim)+',true)', 'ONTOLOGY_DERIVED_CLAIM_NOT_IN_RELEASE')
        assert page(name='roles-catalogue-changed')['total'] == 0
    else:
        assert page(name='review-pinned-old-ncs')['total'] == 0
        assert page(name='review-new-ncs')['total'] == 0
        prior = page(name='review-fixture')['items'][0]
        assert detail(prior['claim_id'], 'review-fixture')['condition']['minimum_months'] == 24
        err('SELECT ontology.query_derived_claim_v1(\'review-pinned-old-ncs\','+q(prior['claim_id'])+',true)', 'ONTOLOGY_DERIVED_CLAIM_NOT_IN_RELEASE')
    saved_cursor = first['next_cursor']; assert saved_cursor
    for name, subject, kind in [(legacy, None, None), (release, entity, None), (release, None, expected_kind)]:
        args = [q(name), q(subject) if subject else 'NULL', q(kind) if kind else 'NULL', '1', q(saved_cursor), 'true']
        err('SELECT ontology.query_derived_claims_v1('+','.join(args)+')', 'INVALID_ONTOLOGY_CURSOR')
    for bad in ['not-base64', base64.b64encode(b'{}').decode(), 'a'*4100]:
        err('SELECT ontology.query_derived_claims_v1('+q(release)+',NULL,NULL,1,'+q(bad)+',true)', 'INVALID_ONTOLOGY_CURSOR')
    for size in ['0', '101', 'NULL']:
        err('SELECT ontology.query_derived_claims_v1('+q(release)+',NULL,NULL,'+size+',NULL,true)', 'INVALID_ONTOLOGY_PAGE_SIZE')
    err('SELECT ontology.query_derived_claims_v1('+q(release)+",NULL,'DUTY',1,NULL,true)", 'INVALID_ONTOLOGY_DERIVED_CLAIM_KIND')
    err('SELECT ontology.query_derived_claims_v1('+q(release)+",'missing',NULL,1,NULL,true)", 'ONTOLOGY_ENTITY_NOT_IN_RELEASE')
    err('SELECT ontology.query_derived_claim_v1('+q(release)+",'missing',true)", 'ONTOLOGY_DERIVED_CLAIM_NOT_IN_RELEASE')
    err('SELECT ontology.query_summary_v3('+q(release)+',false)', 'ONTOLOGY_RELEASE_NOT_PUBLISHED')
    err('SELECT ontology.query_summary_v3('+q(release)+',NULL)', 'INVALID_ONTOLOGY_READ_MODE')
    err('SELECT ontology.query_summary_v3(NULL,true)', 'NO_ACTIVE_ONTOLOGY_RELEASE')
    for state, error in [('FAILED', 'ONTOLOGY_RELEASE_FAILED'), ('REVOKED', 'CORPUS_RELEASE_REVOKED')]:
        err('BEGIN; UPDATE ontology.corpus_release SET state='+q(state)+' WHERE release_id='+q(release)+'; SELECT ontology.query_summary_v3('+q(release)+',true); COMMIT', error)
    membership = 'occupation_membership' if mode == 'occupations' else 'requirement_membership'
    expected_error = 'OCCUPATION_MEMBERSHIP_CHANGED' if mode == 'occupations' else 'REQUIREMENT_MEMBERSHIP_CHANGED'
    err('BEGIN; ALTER TABLE ontology.'+membership+' DISABLE TRIGGER USER; DELETE FROM ontology.'+membership+' WHERE release_id='+q(release)+'; SELECT ontology.query_summary_v3('+q(release)+',true); COMMIT', expected_error)
    # Native workflow parameters execute the same reads through DBJoin bindings.
    for name, extra in [('summary_v3', {}), ('entity_v3', {'ENTITY_ID':entity}),
                        ('derived_claim_v1', {'CLAIM_ID':rows[0]['claim_id']}),
                        ('derived_claims_v1', {'PAGE_SIZE':1,'CLAIM_KIND':expected_kind})]:
        native.run('../editorial/read_'+name+'.hwf', dict(RELEASE_ID=release,PREVIEW='Y')|extra, 'native-derived-'+mode+'-'+name)
    native.run('../editorial/read_summary_v3.hwf', dict(RELEASE_ID=release,PREVIEW='invalid'), 'native-derived-'+mode+'-invalid-preview', False)
    native.run('../editorial/read_derived_claims_v1.hwf', dict(RELEASE_ID=release,PREVIEW='Y',PAGE_SIZE=101), 'native-derived-'+mode+'-invalid-size', False)
    assert fingerprint() == original, 'Read paths mutated source/review/provider/attachment/release/graph data'
    report = dict(result='PASS', fixture=mode, contract_version='hop-ontology-read-v3', derived_claims=len(rows),
                  claim_kinds=sorted(expected_counts), read_fingerprint=original, read_tables=len(tables), native_workflows=4,
                  sealed_preview=True, production_changes=False, provider_calls=0, native_log_directory=str(native.WORK))
    (native.WORK/'derived-read-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) == 2 else None
    if mode == 'occupations':
        import occupations
        occupations.main(lambda native: check(native, mode), configure=combined_source)
    elif mode == 'requirements':
        import requirements
        requirements.main(lambda native: check(native, mode))
    else:
        raise SystemExit('Usage: derived_reads.py occupations|requirements')
