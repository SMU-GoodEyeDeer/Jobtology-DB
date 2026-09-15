"""Read contracts in fresh disposable databases; no model or attachment processing.

Synthetic source/review fixtures exercise real assembly. No existing fixture or
production database is reset. Native runs execute only installers/read workflows.
"""
import base64
import json
import subprocess
import uuid
from pathlib import Path
import run


def main():
    suffix=uuid.uuid4().hex[:10]
    run.PG='jobtology-query-test-pg-'+suffix
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode
    hop='jobtology-query-test-hop-'+suffix
    network='jobtology-query-test-'+suffix
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    try:
        run.boot()
        import claims
        claims.check()
        baseline=sql("SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r")
        release='review-fixture'; entity='urn:jobtology:jobPosting:job_alio:001'
        read=lambda expr:json.loads(sql('SELECT '+expr))
        summary=read(f'ontology.query_summary_v1({q(release)},true)')
        review=summary['posting_review']
        assert review['denominator']==6 and review['accepted_numerator']==1
        assert review['outcomes']=={'ACCEPTED':1,'REVIEW_REQUIRED':2,'PROCESSING_FAILED':1,'NOT_PROCESSED':2}
        assert abs(review['accepted_fraction']-1/6)<1e-12
        assert summary['accepted_claim_counts']=={'DUTY':1,'REQUIREMENT':3}
        assert summary['accepted_mappings']==1 and summary['read_mode']=='PREVIEW'
        assert len(summary['sources'])==6 and all(s['unaccounted_records']==0 for s in summary['source_coverage'])

        def page(name=release,kind='jobPosting',size=2,cursor=None):
            return read(f'ontology.query_entities_v1({q(name)},{q(kind)},{size},{q(cursor) if cursor else "NULL"},true)')
        first=page(); rows=[];current=first
        while True:
            assert current['release_id']==release and current['read_mode']=='PREVIEW'
            rows+=current['items']
            if current['next_cursor'] is None:break
            current=page(cursor=current['next_cursor'])
        expected=read("(SELECT jsonb_agg(jsonb_build_object('entity_id',m.entity_id,'revision_id',m.revision_id,'name',r.name) ORDER BY m.entity_id COLLATE \"C\") "
                      f"FROM ontology.release_revision m JOIN ontology.revision r USING(revision_id) WHERE m.release_id={q(release)} AND r.kind='jobPosting')")
        assert [{k:r[k] for k in ['entity_id','revision_id','name']} for r in rows]==expected
        assert len({r['entity_id'] for r in rows})==6
        cursor=first['next_cursor'];assert cursor
        for changed_release,changed_kind in [('review-new-ncs','jobPosting'),(release,'organization')]:
            err(f'SELECT ontology.query_entities_v1({q(changed_release)},{q(changed_kind)},2,{q(cursor)},true)', 'INVALID_ONTOLOGY_CURSOR')
        for bad in ['not base64',base64.b64encode(b'{}').decode(),base64.b64encode(b'null').decode(),'a'*4100]:
            err(f'SELECT ontology.query_entities_v1({q(release)},NULL,2,{q(bad)},true)','INVALID_ONTOLOGY_CURSOR')
        for bad in [0,101]:err(f'SELECT ontology.query_entities_v1({q(release)},NULL,{bad},NULL,true)','INVALID_ONTOLOGY_PAGE_SIZE')
        err(f'SELECT ontology.query_entities_v1({q(release)},\'Person\',10,NULL,true)','INVALID_ONTOLOGY_ENTITY_KIND')

        detail=read(f'ontology.query_entity_v1({q(release)},{q(entity)},true)')
        assert detail['entity']['name']=='데이터 엔지니어 채용'
        assert detail['extraction']['outcome']=='ACCEPTED' and detail['extraction']['input_scope']=='inline-fields'
        assert len(detail['positions'])==1 and len(detail['claims'])==4 and len(detail['mappings'])==1
        assert {d['outcome'] for d in detail['link_decisions']}=={'ACCEPTED','REJECTED'}
        assert detail['mappings'][0]['target_payload']['code']=='2001020101_24v2'
        assert len(detail['source_support'])==2
        relation=next(r for r in detail['relations'] if r['predicate']=='POSTED_BY')
        assert relation['object_id']=='urn:jobtology:organization:alio:C001'
        evidence_ids={detail['positions'][0]['evidence_id']}
        for c in detail['claims']:
            evidence_ids.update(e['evidence_id'] for e in c['evidence'])
            for n in c['conditions']:evidence_ids.update(e['evidence_id'] for e in n['evidence'])
            # Compare ordered child indices with the original reviewed expression.
            expression=c['payload'].get('expression') or []
            assert [(n['operator'],n['children']) for n in c['conditions']]==[(n['op'],n['children']) for n in expression]
        for eid in evidence_ids:
            ev=read(f'ontology.query_evidence_v1({q(release)},{q(eid)},true)')
            text=sql('SELECT normalized_text FROM ontology.text_artifact WHERE artifact_id='+q(ev['artifact']['artifact_id']))
            span=ev['evidence']
            assert text[span['start_offset']:span['end_offset']]==span['excerpt']
            assert ev['document'] is None and ev['source_records']
            assert all(r['run_id']=='fixture-job_alio' for r in ev['source_records'])
            assert 'raw_object_path' not in json.dumps(ev)
        after_reject=read(f"ontology.query_entity_v1('review-after-link-rejection',{q(entity)},true)")
        assert len(after_reject['claims'])==4 and after_reject['mappings']==[]
        after_reject=read(f"ontology.query_entity_v1('review-after-extraction-rejection',{q(entity)},true)")
        assert after_reject['extraction']['outcome']=='REJECTED' and after_reject['claims']==[] and after_reject['positions']==[]
        err(f"SELECT ontology.query_evidence_v1('review-after-extraction-rejection',{q(next(iter(evidence_ids)))},true)", 'ONTOLOGY_EVIDENCE_NOT_IN_RELEASE')
        err(f"SELECT ontology.query_entity_v1({q(release)},'urn:jobtology:jobPosting:job_alio:unknown',true)",'ONTOLOGY_ENTITY_NOT_IN_RELEASE')
        for posting in ['002','003','004','005','006']:
            row=read(f"ontology.query_entity_v1({q(release)},{q(entity[:-3]+posting)},true)")
            assert row['extraction']['outcome']!='ACCEPTED' and row['claims']==[] and row['mappings']==[]
        assert baseline==sql("SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r")

        # A second real source snapshot changes names; historical reads keep both
        # the posting and related employer revision from their selected release.
        for source,source_run,new_run in [('job_alio','fixture-job_alio','renamed-jobs'),('alio_organization','fixture-alio_organization','renamed-orgs')]:
            for table in ['run','partition','document']:
                sql(f"INSERT INTO ingestion.{table} SELECT (jsonb_populate_record(NULL::ingestion.{table},to_jsonb(r)||"
                    f"jsonb_build_object('run_id',{q(new_run)}))).* FROM ingestion.{table} r WHERE run_id={q(source_run)}")
            change="jsonb_build_object('title','새 공고 제목')" if source=='job_alio' else "jsonb_build_object('name','새 기관명')"
            sql("INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized,field_lineage,quality_flags) "
                f"SELECT {q(new_run)},document_id,locator,source_record_id,source_payload||{change},normalized||{change},field_lineage,quality_flags FROM ingestion.record WHERE run_id={q(source_run)}")
        sql("SELECT ontology.prepare_release('renamed-release','{\"job_alio\":\"renamed-jobs\",\"alio_organization\":\"renamed-orgs\",\"ncs_competency\":\"fixture-ncs_competency\"}'); SELECT ontology.assemble_sources('renamed-release')")
        renamed=read(f"ontology.query_entity_v1('renamed-release',{q(entity)},true)")
        assert renamed['entity']['name']=='새 공고 제목'
        assert next(r for r in renamed['relations'] if r['predicate']=='POSTED_BY')['object_name']=='새 기관명'
        assert renamed['extraction']['outcome']=='SELECTION_PENDING'
        assert read(f'ontology.query_entity_v1({q(release)},{q(entity)},true)')==detail
        err(f"SELECT ontology.query_entities_v1('renamed-release','jobPosting',2,{q(cursor)},true)",'INVALID_ONTOLOGY_CURSOR')

        sql("INSERT INTO ontology.corpus_release(release_id) VALUES('empty-read-fixture')")
        empty=read("ontology.query_summary_v1('empty-read-fixture',true)")
        assert empty['posting_review']['denominator']==0 and empty['posting_review']['accepted_fraction'] is None
        assert page('empty-read-fixture')['items']==[] and page('empty-read-fixture')['next_cursor'] is None
        for fun in ["query_summary_v1(NULL)",f'query_entity_v1(NULL,{q(entity)})',"query_entities_v1(NULL)"]:
            err('SELECT ontology.'+fun,'NO_ACTIVE_ONTOLOGY_RELEASE')
        err(f'SELECT ontology.query_summary_v1({q(release)})','ONTOLOGY_RELEASE_NOT_PUBLISHED')
        err(f'SELECT ontology.query_summary_v1({q(release)},NULL)','INVALID_ONTOLOGY_READ_MODE')
        for state,code in [('REVOKED','CORPUS_RELEASE_REVOKED'),('FAILED','ONTOLOGY_RELEASE_FAILED')]:
            for preview in ['true','false']:
                err(f"BEGIN; UPDATE ontology.corpus_release SET state='{state}' WHERE release_id={q(release)}; "
                    f'SELECT ontology.query_summary_v1({q(release)},{preview}); ROLLBACK;',code)

        # Simulate a future published lifecycle only in a rolled-back local
        # transaction. No test bypass survives; production gate remains closed.
        published_setup=f"""UPDATE ontology.corpus_release SET state='ACTIVE',manifest='{{}}',manifest_hash=ontology.hash('{{}}'),graph_verified_at=now() WHERE release_id={q(release)};
INSERT INTO ontology.activation_event(release_id,actor,reason) VALUES({q(release)},'synthetic fixture','Read gate only');
INSERT INTO ontology.active_release SELECT true,release_id,event_id FROM ontology.activation_event ORDER BY event_id DESC LIMIT 1;
"""
        err('BEGIN;'+published_setup+'SELECT ontology.query_summary_v1();ROLLBACK;','ONTOLOGY_RELEASE_NOT_PUBLISHED')
        query='BEGIN;'+published_setup+"CREATE OR REPLACE VIEW ontology.publication_issue AS SELECT NULL::text AS release_id,NULL::text AS issue WHERE false; SELECT ontology.query_summary_v1(); ROLLBACK;"
        live=json.loads(sql(query))
        assert live['release_id']==release and live['read_mode']=='PUBLISHED' and live['posting_review']==review
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        assert sql(f"SELECT count(*) FROM ontology.publication_issue WHERE release_id={q(release)} AND issue='SERVING_CONTRACT_INTEGRATION_PENDING'")=='1'

        import native
        native.HOP=hop;native.NET=network
        native.stage()
        native.run('install.hwf',{},'read-native-installer')
        choices=dict(RELEASE_ID=release,PREVIEW='Y')
        native.run('read_summary.hwf',choices,'read-native-summary')
        native.run('read_entities.hwf',choices|dict(ENTITY_KIND='jobPosting',PAGE_SIZE=2),'read-native-entities')
        native.run('read_entity.hwf',choices|dict(ENTITY_ID=entity),'read-native-entity')
        native.run('read_evidence.hwf',choices|dict(EVIDENCE_ID=next(iter(evidence_ids))),'read-native-evidence')
        native.run('read_summary.hwf',dict(RELEASE_ID=release),'read-native-unpublished-rejection',False)
        native.run('read_summary.hwf',choices|dict(PREVIEW='invalid'),'read-native-invalid-mode',False)
        assert sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL")=='0'
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        print('READ CONTRACT CHECKS PASSED: frozen source names/relations, every posting outcome, pagination, cursor isolation, Unicode evidence, independent reviews, default/preview/revocation gates and native reads.',flush=True)
        print('Native fixture:',native.WORK,flush=True)
    finally:
        for container in [hop,run.PG]:subprocess.run(['docker','rm','-fv',container],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__=='__main__':main()
