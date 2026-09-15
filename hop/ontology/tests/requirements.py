"""Typed requirement semantics in fresh PostgreSQL/native Hop. No provider calls."""
import copy
import hashlib
import json
import subprocess
import uuid
import run


def main(after=None):
    suffix=uuid.uuid4().hex[:10]
    run.PG='jobtology-requirements-pg-'+suffix
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode
    hop='jobtology-requirements-hop-'+suffix; network='jobtology-requirements-'+suffix
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    try:
        run.boot()
        import claims
        claims.check()
        import native
        native.HOP=hop;native.NET=network
        before=claims.digest('review-fixture')
        attempts=sql('SELECT count(*) FROM enrichment.attempt')
        schema=json.loads((run.ROOT/'hop/ontology/schemas/requirement-normalization-v1.schema.json').read_text())
        atom=json.loads(sql("SELECT to_jsonb(a) FROM ontology.requirement_atom a WHERE release_id='review-fixture' AND source_text='경력 2년 이상'"))
        claim=atom['source_claim_id']
        doc=dict(schema_version='hop-requirement-normalization-v1',release_id='review-fixture',source_claim_id=claim,
            node_index=4,parent_id=None,actor='synthetic-author',reason='The cited atom states at least two years; preserve its parent AND/OR tree.',
            resolver_version='synthetic-manual-v1',necessity='REQUIRED',polarity='POSITIVE',
            condition=dict(kind='EXPERIENCE',context_id=None,minimum_months=24,maximum_months=None))
        capture=lambda d:sql('SELECT ontology.capture_requirement_v1('+js(d)+')')
        proposal=capture(doc)
        assert capture(doc)==proposal
        n=json.loads(sql('SELECT to_jsonb(n) FROM ontology.requirement_normalization n WHERE normalization_id='+q(proposal)))
        canonical=json.dumps(doc['condition'],sort_keys=True,ensure_ascii=False,separators=(',',':'))
        assert n['requirement_key']==hashlib.sha256(canonical.encode()).hexdigest()
        assert n['source_binding']['expression_edges']==[
            dict(claim_id=claim,parent_index=0,ordinal=0,child_index=1),dict(claim_id=claim,parent_index=0,ordinal=1,child_index=4),
            dict(claim_id=claim,parent_index=1,ordinal=0,child_index=2),dict(claim_id=claim,parent_index=1,ordinal=1,child_index=3)]
        assert n['source_binding']['applicability']=='explicit_positions' and len(n['source_binding']['positions'])==1
        assert [e['span']['excerpt'] for e in n['source_binding']['evidence']]==['경력 2년 이상']
        err('SELECT ontology.capture_requirement_v1('+js(doc|dict(confidence=1.0))+')','INVALID_REQUIREMENT_DOCUMENT')
        err('SELECT ontology.capture_requirement_v1('+js(doc|dict(node_index=0))+')','UNKNOWN_RELEASE_REQUIREMENT_ATOM')
        err('SELECT ontology.capture_requirement_v1('+js(doc|dict(condition=doc['condition']|dict(maximum_months=12)))+')','EXPERIENCE_RANGE_ORDER')
        err('SELECT ontology.capture_requirement_v1('+js(doc|dict(condition=doc['condition']|dict(minimum_months=None)))+')','EMPTY_TYPED_CONDITION')
        err('SELECT ontology.capture_requirement_v1('+js(doc|dict(condition=doc['condition']|dict(minimum_months=-1)))+')','INVALID_REQUIREMENT_DOCUMENT')
        err('SELECT ontology.decide_requirement_v1('+q(proposal)+",'ACCEPT','synthetic-author','assistant','Self review')",'INDEPENDENT_REQUIREMENT_REVIEW_REQUIRED')
        sql('SELECT ontology.decide_requirement_v1('+q(proposal)+",'ACCEPT','synthetic-reviewer','human','Synthetic human review of explicit two-year atom')")
        sql("SELECT ontology.freeze_requirements_v1('review-fixture')")
        report=json.loads(sql("SELECT ontology.query_requirements_v1('review-fixture',true)"))
        assert len(report['atoms'])==6 and sum(a['selection']['outcome']=='REVIEWED' for a in report['atoms'])==1
        assert any(i['issue']=='REQUIREMENT_SCOPE_UNRESOLVED' for i in report['issues'])
        assert any(i['issue']=='REQUIREMENT_GUARD_NORMALIZATION_PENDING' for i in report['issues'])
        reviewed=next(a for a in report['atoms'] if a['selection']['outcome']=='REVIEWED')
        assert reviewed['requirement_scope']=='CAPABILITY' and reviewed['confidence'] is None
        assert reviewed['review']['reviewer_kind']=='human'
        frozen=sql("SELECT manifest_hash FROM ontology.requirement_membership WHERE release_id='review-fixture'")
        sql("SELECT ontology.freeze_requirements_v1('review-fixture')")
        assert frozen==sql("SELECT manifest_hash FROM ontology.requirement_membership WHERE release_id='review-fixture'")
        corrected=doc|dict(parent_id=proposal,reason='New pending interpretation must not fall back to an older approval.')
        newer=capture(corrected)
        err('SELECT ontology.decide_requirement_v1('+q(proposal)+",'ACCEPT','synthetic-reviewer','human','Old proposal')",'REQUIREMENT_NORMALIZATION_SUPERSEDED')
        err('SELECT ontology.capture_requirement_v1('+js(doc|dict(reason='Stale competing correction'))+')','STALE_REQUIREMENT_PARENT')
        sql("SELECT ontology.verify_requirements_v1('review-fixture')")
        assert frozen==sql("SELECT manifest_hash FROM ontology.requirement_membership WHERE release_id='review-fixture'")
        sql("SELECT ontology.freeze_requirements_v1('review-pinned-old-ncs')")
        assert sql('SELECT outcome FROM ontology.requirement_selection WHERE release_id=\'review-pinned-old-ncs\' AND source_claim_id='+q(claim)+' AND node_index=4')=='PENDING'
        err("UPDATE ontology.requirement_normalization SET requirement_key=repeat('f',64)",'IMMUTABLE_ONTOLOGY_RECORD')
        err("BEGIN; ALTER TABLE ontology.requirement_normalization DISABLE TRIGGER USER; UPDATE ontology.requirement_normalization SET requirement_key=repeat('f',64) WHERE normalization_id="+q(proposal)+"; SELECT ontology.verify_requirements_v1('review-fixture'); COMMIT;",'REQUIREMENT_NORMALIZATION_CHANGED')
        err("BEGIN; ALTER TABLE ontology.requirement_selection DISABLE TRIGGER USER; DELETE FROM ontology.requirement_selection WHERE release_id='review-fixture'; SELECT ontology.verify_requirements_v1('review-fixture'); COMMIT;",'REQUIREMENT_SELECTION_MISMATCH')

        # All nine condition shapes and JCS key payloads are exercised independently
        # of capture, so these examples never claim to interpret unrelated source text.
        cases=[dict(kind='SKILL',target_id='urn:skill:python',target_kind='Skill',proficiency_scheme_id=None,minimum_proficiency=None),
            dict(kind='LANGUAGE',target_id='urn:skill:korean',target_kind='Skill',proficiency_scheme_id=None,minimum_proficiency=None),
            dict(kind='CREDENTIAL',target_id='urn:credential:test'),
            dict(kind='EDUCATION',minimum_degree='BACHELOR',accepted_major_groups=['ENGINEERING','COMPUTING','ENGINEERING'],accepts_expected_graduate=True),
            doc['condition'],dict(kind='PROJECT',minimum_count=2,portfolio_required=True,capability_ids=['urn:skill:b','urn:skill:a','urn:skill:b']),
            dict(kind='LOCATION',administrative_codes=['26','11','11'],work_mode='HYBRID'),
            dict(kind='ELIGIBILITY',vocabulary_id='urn:vocab:eligibility',code='DISABILITY',source_text='장애인 우대'),
            dict(kind='AVAILABILITY',earliest_start='2026-10-01',schedule_text='주 5일\t근무 😀')]
        for condition in cases:
            assert sql('SELECT enrichment.schema_issues_v6('+js(doc|dict(condition=condition))+','+js(schema)+')')=='[]'
            expected=copy.deepcopy(condition)
            for key in ['accepted_major_groups','capability_ids','administrative_codes']:
                if key in expected:expected[key]=sorted(set(expected[key]))
            if expected['kind'] in ['SKILL','LANGUAGE']:expected.pop('target_kind')
            actual=json.loads(sql('SELECT ontology.requirement_key_payload_v1(ontology.normalize_condition_v1('+js(condition)+'))'))
            assert actual==expected
            jcs=sql('SELECT ontology.requirement_jcs_v1('+js(actual)+')')
            assert jcs==json.dumps(expected,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        err("SELECT ontology.requirement_jcs_v1('{\"x\":1.2}')",'REQUIREMENT_JCS_UNSUPPORTED_NUMBER')
        err("SELECT ontology.requirement_jcs_v1('{\"한글\":1}')",'REQUIREMENT_JCS_NON_ASCII_KEY')

        def reference(entity,kind,payload):
            sql('INSERT INTO ontology.entity(entity_id,kind,code) VALUES('+','.join(q(v) for v in [entity,kind,entity])+')')
            rid=sql('SELECT ontology.hash('+js([entity,payload])+')')
            sql('INSERT INTO ontology.revision(revision_id,entity_id,kind,name,payload,payload_hash) VALUES('+','.join(q(v) for v in [rid,entity,kind,entity])+','+js(payload)+',ontology.hash('+js(payload)+'))')
            sql('INSERT INTO ontology.release_revision VALUES(\'review-after-link-rejection\','+q(entity)+','+q(rid)+')')
            return rid
        reference('urn:skill:python','skill',dict(kind='TECHNICAL'))
        reference('urn:skill:korean','skill',dict(kind='LANGUAGE'))
        reference('urn:credential:test','qualification',dict(code='TEST'))
        reference('urn:vocab:eligibility','conceptScheme',dict(kind='ELIGIBILITY',review_state='HUMAN_ACCEPTED',codes={'DISABILITY':'Synthetic reviewed fixture definition'}))
        reference('urn:vocab:proficiency','conceptScheme',dict(kind='PROFICIENCY',ordered_values=[1,2,3]))
        reference('urn:place:11','place',dict(administrative_code='11'))
        reference('urn:place:26','place',dict(administrative_code='26'))
        target=lambda c:sql("SELECT ontology.requirement_targets_v1('review-after-link-rejection',"+js(c)+')')
        for condition in cases[:3]+[cases[6],cases[7]]:assert json.loads(target(condition))
        assert len(json.loads(target(cases[0]|dict(proficiency_scheme_id='urn:vocab:proficiency',minimum_proficiency=2))))==2
        err("SELECT ontology.requirement_targets_v1('review-after-link-rejection',"+js(cases[1]|dict(target_id='urn:skill:python'))+')','REQUIREMENT_TARGET_TYPE_MISMATCH')
        err("SELECT ontology.requirement_targets_v1('review-after-link-rejection',"+js(cases[0]|dict(proficiency_scheme_id='urn:vocab:proficiency',minimum_proficiency=4))+')','UNKNOWN_PROFICIENCY_LEVEL')
        err("SELECT ontology.requirement_targets_v1('review-after-link-rejection',"+js(cases[7]|dict(code='MADE_UP'))+')','ELIGIBILITY_CODE_NOT_REVIEWED')
        err("SELECT ontology.requirement_targets_v1('review-fixture',"+js(cases[0])+')','REQUIREMENT_TARGET_NOT_IN_RELEASE')
        ncs=sql("SELECT entity_id FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id) WHERE m.release_id='review-after-link-rejection' AND kind='ncsCompetency' ORDER BY entity_id LIMIT 1")
        assert json.loads(target(cases[0]|dict(target_id=ncs,target_kind='NCSCompetencyUnit')))[0]['entity_id']==ncs
        err("SELECT ontology.requirement_targets_v1('review-after-link-rejection',"+js(cases[0]|dict(target_id=ncs))+')','REQUIREMENT_TARGET_TYPE_MISMATCH')

        # A reviewed reference is never carried into a release without that exact
        # canonical target revision. Unknown codes stay explicit unresolved work.
        reference('urn:credential:internal-medicine','qualification',dict(name='내과 전문의',code='SYNTHETIC-INTERNAL-MEDICINE'))
        credential_doc=doc|dict(release_id='review-after-link-rejection',node_index=2,
            condition=dict(kind='CREDENTIAL',target_id='urn:credential:internal-medicine'))
        credential_id=capture(credential_doc)
        sql('SELECT ontology.decide_requirement_v1('+q(credential_id)+",'ACCEPT','fixture-credential-reviewer','human','Synthetic specialty credential target verified')")
        sql("SELECT ontology.freeze_requirements_v1('review-new-ncs')")
        assert sql('SELECT outcome FROM ontology.requirement_selection WHERE release_id=\'review-new-ncs\' AND source_claim_id='+q(claim)+' AND node_index=2')=='TARGET_REVISION_MISMATCH'
        unresolved=doc|dict(release_id='review-after-link-rejection',node_index=3,
            condition=dict(kind='UNRESOLVED',mention='응급의학과 전문의 자격 소지자',reason='NO_MATCH'))
        unknown=capture(unresolved)
        assert sql('SELECT requirement_key IS NULL FROM ontology.requirement_normalization WHERE normalization_id='+q(unknown))=='t'
        err('SELECT ontology.decide_requirement_v1('+q(unknown)+",'ACCEPT','fixture-reviewer','assistant','Cannot accept unresolved')",'UNRESOLVED_REQUIREMENT_CANNOT_BE_ACCEPTED')
        bad_quote=unresolved|dict(condition=unresolved['condition']|dict(mention='invented quote'))
        err('SELECT ontology.capture_requirement_v1('+js(bad_quote)+')','REQUIREMENT_EXACT_SOURCE_TEXT_REQUIRED')

        # Native file reader, prepared SQL, review, freeze, and read must execute.
        native.stage()
        native.run('install.hwf',{},'requirements-native-install')
        native_doc=corrected|dict(parent_id=newer,release_id='review-after-link-rejection',reason='Native synthetic review path')
        path=native.WORK/'requirement.json';path.write_text(json.dumps(native_doc,ensure_ascii=False))
        run.cmd(['docker','cp',str(path),hop+':'+native.REMOTE+'/project/requirement.json'])
        native.run('import_requirement.hwf',dict(NORMALIZATION_FILE=native.REMOTE+'/project/requirement.json'),'requirements-native-import')
        latest=sql('SELECT normalization_id FROM ontology.requirement_normalization ORDER BY normalization_no DESC LIMIT 1')
        native.run('review_requirement.hwf',dict(NORMALIZATION_ID=latest,DECISION='ACCEPT',REVIEWER='native-fixture-reviewer',REVIEWER_KIND='assistant',NOTES='Synthetic evidence reviewed'),'requirements-native-review')
        native.run('inspect_requirements.hpl',dict(RELEASE_ID='review-after-link-rejection'),'requirements-native-inspect')
        native.run('freeze_requirements.hwf',dict(RELEASE_ID='review-after-link-rejection'),'requirements-native-freeze')
        native.run('freeze_requirements.hwf',dict(RELEASE_ID='review-after-link-rejection'),'requirements-native-replay')
        native.run('read_requirements.hwf',dict(RELEASE_ID='review-after-link-rejection',PREVIEW='Y'),'requirements-native-read')
        native.run('read_requirements.hwf',dict(RELEASE_ID='review-after-link-rejection',PREVIEW='N'),'requirements-native-reject-public-draft',False)
        assert claims.digest('review-fixture')==before
        assert sql('SELECT count(*) FROM enrichment.attempt')==attempts
        assert sql("SELECT count(*) FROM ontology.corpus_release WHERE state='ACTIVE'")=='0'
        result=dict(condition_kinds=9,source_atoms=6,provider_calls=0,source_claims_unchanged=True,native_workflows=True,
            original_requirement_manifest_hash=frozen,publication_ready=False)
        (native.WORK/'requirements-report.json').write_text(json.dumps(result,indent=2)+'\n')
        if after is not None:after(native)
        print('TYPED REQUIREMENT CHECKS PASSED',native.WORK,flush=True)
    finally:
        subprocess.run(['docker','rm','-fv',hop,run.PG],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__=='__main__':main()
