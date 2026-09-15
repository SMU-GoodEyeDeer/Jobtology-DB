"""Deterministic lifecycle and health checks in fresh disposable containers.

Synthetic API-record fixtures only. No provider requests, models, attachments,
production reviews or existing test databases are changed.
"""
import json
import subprocess
import uuid
import run


def main():
    suffix=uuid.uuid4().hex[:10]
    run.PG='jobtology-observation-pg-'+suffix
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode
    hop='jobtology-observation-hop-'+suffix;network='jobtology-observation-'+suffix
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    try:
        run.boot()
        sources=run.fixture();base=sources['job_alio'];jobs=[]
        for posting in ['001','002','003','004']:
            for row in base:
                item=row|dict(posting_id=posting,title='공고 '+posting,ongoing=posting!='002',closing_date='2026-09-30')
                if posting in ['002','003']:item['closing_date']='2026-09-01'
                if posting=='004':item.update(ongoing=None,closing_date=None)
                jobs.append(item)
        sources['job_alio']=jobs;run.load_sources(sources)
        def snapshot(name,at,postings,mode='FULL',state='READY',rename=False):
            sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) VALUES({q(name)},'job_alio',{q(mode)},'fixture',{q(state)},{q(at)}::timestamptz,{q(at)}::timestamptz+interval '1 minute')")
            sql(f"INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(name)},'all','FILE',1)")
            sql(f"INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) VALUES({q(name)},'doc','all',1,'fixture.json',repeat('b',64),1,'UTF-8',200,{q(at)}::timestamptz+interval '30 seconds',true,now())")
            for index,row in enumerate(jobs):
                if row['posting_id'] not in postings:continue
                if rename and row['posting_id']=='001':row=row|dict(title='새 이름 공고 001')
                sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(name)},'doc',{q(str(index))},{q(row['posting_id']+':'+row['representation'])},{js(row)},{js(row)})")
        def release(name,snapshot,at):
            sql('SELECT ontology.prepare_release('+q(name)+','+js({'job_alio':snapshot})+'); SELECT ontology.assemble_sources('+q(name)+')')
            sql('SELECT ontology.freeze_observations_v1('+q(name)+','+q(at)+')')
            return rows(name)
        def rows(name):
            data=json.loads(sql('SELECT ontology.query_observations_v1('+q(name)+',true)'))
            assert data['read_mode']=='PREVIEW'
            return {r['posting_id']:r for r in data['postings']}
        def health(release,at):
            data=json.loads(sql('SELECT ontology.query_source_health_v1('+q(release)+',true,'+q(at)+')'))
            return data,{r['source_id']:r for r in data['sources']}
        sql("SELECT ontology.capture_posting_census_v1('fixture-job_alio')")
        assert sql("SELECT retention.protection('fixture-job_alio',0)")=='ONTOLOGY_OBSERVATION_HISTORY'
        first=release('before-midnight','fixture-job_alio','2026-09-01T14:59:59Z')
        assert first['001']['serving_state']=='ACTIVE' and first['002']['serving_state']=='CLOSED'
        assert first['003']['serving_state']=='ACTIVE' and first['003']['deadline_at']=='2026-09-01T15:00:00+00:00'
        assert first['004']['source_status']=='UNKNOWN' and first['004']['deadline_at'] is None
        after=release('at-midnight','fixture-job_alio','2026-09-01T15:00:00Z')
        assert after['003']['serving_state']=='EXPIRED' and after['002']['serving_state']=='CLOSED'
        assert first==rows('before-midnight'),'Elapsed time changed an old frozen release'
        snapshot('failed-detail','2026-09-01T06:00:00Z',['002','003'],state='FAILED')
        snapshot('first-absence','2026-09-02T00:00:00Z',['002','003'])
        snapshot('smoke','2026-09-02T06:00:00Z',['001','002','003','004'],mode='SMOKE')
        snapshot('replay','2026-09-02T12:00:00Z',['001','002','003','004'],mode='REPLAY')
        one=release('one-absence','first-absence','2026-09-02T01:00:00Z')
        assert len(one)==4
        for posting in ['001','004']:
            assert one[posting]['serving_state']=='ACTIVE' and one[posting]['consecutive_absence_count']==1
            assert one[posting]['membership_state']=='HISTORICAL_NOT_ASSEMBLED' and one[posting]['selected_revision_id'] is None
            assert one[posting]['content_run_id']=='fixture-job_alio'
        snapshot('second-absence','2026-09-03T00:00:00Z',['002','003'])
        two=release('two-absences','second-absence','2026-09-03T01:00:00Z')
        for posting in ['001','004']:
            assert two[posting]['serving_state']=='NOT_SEEN' and two[posting]['consecutive_absence_count']==2
            assert two[posting]['first_seen_at']==first[posting]['first_seen_at']==two[posting]['last_seen_at']
        assert two['002']['serving_state']=='CLOSED' and two['003']['serving_state']=='EXPIRED'
        assert sql("SELECT array_agg(run_id ORDER BY ordinal)::text FROM ontology.observation_history_member WHERE release_id='two-absences'")=='{fixture-job_alio,first-absence,second-absence}'
        snapshot('reappearance','2026-09-04T00:00:00Z',['001','002','003','004'],rename=True)
        reappeared=release('seen-again','reappearance','2026-09-04T01:00:00Z')
        assert reappeared['001']['consecutive_absence_count']==0 and reappeared['001']['serving_state']=='ACTIVE'
        assert reappeared['001']['first_seen_at']==first['001']['first_seen_at']
        assert reappeared['001']['last_seen_at']=='2026-09-04T00:00:30+00:00'
        assert reappeared['001']['selected_revision_id']!=first['001']['selected_revision_id']
        assert rows('two-absences')==two and rows('before-midnight')==first
        err("BEGIN; INSERT INTO ontology.observation_history_member VALUES('two-absences','reappearance',3); SELECT ontology.freeze_observations_v1('two-absences'); ROLLBACK;",'FROZEN_OBSERVATION_HISTORY_CHANGED')
        freeze_before=sql("SELECT ontology.hash(jsonb_agg(f ORDER BY release_id)) FROM ontology.observation_freeze f")
        sql("SELECT ontology.freeze_observations_v1('two-absences'); SELECT ontology.freeze_observations_v1('seen-again','2026-09-04T01:00:00Z')")
        assert freeze_before==sql("SELECT ontology.hash(jsonb_agg(f ORDER BY release_id)) FROM ontology.observation_freeze f")
        err("SELECT ontology.freeze_observations_v1('two-absences','2026-09-05T00:00:00Z')",'OBSERVATION_EVALUATION_IS_FROZEN')
        err("SELECT ontology.capture_posting_census_v1('failed-detail')",'LLM_REQUIRES_VALID_READY_SNAPSHOT')
        err("SELECT ontology.capture_posting_census_v1('smoke')",'LLM_REQUIRES_VALID_READY_SNAPSHOT')
        err("SELECT ontology.capture_posting_census_v1('replay')",'OBSERVATION_REQUIRES_COMPLETED_FULL_RUN')
        for table in ['observation_run','posting_seen','observation_freeze','observation_history_member','posting_observation']:
            err('DELETE FROM ontology.'+table,'IMMUTABLE_ONTOLOGY_RECORD')
        err("BEGIN; UPDATE ingestion.record SET normalized=normalized||'{\"title\":\"corrupted\"}' WHERE run_id='first-absence'; SELECT ontology.freeze_observations_v1('two-absences'); ROLLBACK;",'HISTORICAL_OBSERVATION_SOURCE_CHANGED')
        err("BEGIN; UPDATE ingestion.document SET verified_at=NULL WHERE run_id='fixture-job_alio'; SELECT ontology.capture_posting_census_v1('fixture-job_alio'); ROLLBACK;",'OBSERVATION_REQUIRES_VERIFIED_DOCUMENTS')
        err("SELECT ontology.posting_deadline_v1('{\"closing_date\":\"2026-02-30\"}')",'INVALID_OBSERVED_POSTING_DEADLINE')
        err("SELECT ontology.posting_deadline_v1('{\"closing_date\":\"next week\"}')",'INVALID_OBSERVED_POSTING_DEADLINE')
        # Failed refresh does not extend freshness or change frozen entity state.
        _,states=health('before-midnight','2026-09-01T07:00:00Z')
        assert states['job_alio']['source_health']=='ERROR' and states['job_alio']['selected_is_fresh']
        assert states['job_alio']['latest_success_run_id']=='fixture-job_alio'
        _,states=health('before-midnight','2026-09-02T06:00:30Z')
        assert states['job_alio']['selected_is_fresh'],'Exactly 30 hours must remain within the freshness window'
        _,states=health('before-midnight','2026-09-02T06:00:31Z')
        assert not states['job_alio']['selected_is_fresh'] and states['job_alio']['source_health']=='HEALTHY'
        snapshot('review-pending','2026-09-04T06:00:00Z',[],state='REVIEW_REQUIRED')
        snapshot('loading','2026-09-04T08:00:00Z',[],state='LOADING')
        _,states=health('seen-again','2026-09-04T09:00:00Z')
        assert states['job_alio']['source_health']=='REVIEW_REQUIRED' and states['job_alio']['refresh_in_progress']
        data,states=health('seen-again','2026-09-15T00:00:00Z')
        assert not data['all_selected_sources_fresh'] and states['ncs_competency']['source_health']=='STALE'
        assert states['alio_organization']['source_health']=='HEALTHY'
        assert rows('before-midnight')==first
        invalid=json.loads(sql("BEGIN; UPDATE ingestion.document SET verified_at=NULL WHERE run_id='reappearance'; SELECT ontology.query_source_health_v1('seen-again',true,'2026-09-04T01:00:00Z'); ROLLBACK;"))
        assert next(s for s in invalid['sources'] if s['source_id']=='job_alio')['source_health']=='ERROR'
        # An accepted empty snapshot advances absence without deleting the history.
        snapshot('empty-full','2026-09-05T00:00:00Z',[])
        empty=release('empty-current','empty-full','2026-09-05T01:00:00Z')
        assert len(empty)==4 and all(not row['present_in_selected_run'] for row in empty.values())
        # Native workflow entry points use the same frozen/replay semantics.
        import native
        native.HOP=hop;native.NET=network
        native.stage();native.run('install.hwf',{},'observation-installer')
        snapshot('native-census-only','2026-09-06T00:00:00Z',['001','002','003','004'])
        native.run('capture_posting_census.hwf',dict(RUN_ID='native-census-only'),'native-first-census')
        assert sql("SELECT posting_count FROM ontology.observation_run WHERE run_id='native-census-only'")=='4'
        native.run('prepare_release.hwf',dict(RELEASE_ID='native-observation-first',JOB_RUN_ID='reappearance'),'native-source-preparation')
        native.run('freeze_observations.hwf',dict(RELEASE_ID='native-observation-first',EVALUATED_AT='2026-09-04T01:00:00Z'),'native-first-freeze')
        observed=rows('native-observation-first')
        assert {p:(r['serving_state'],r['first_seen_at'],r['last_seen_at']) for p,r in observed.items()}=={p:(r['serving_state'],r['first_seen_at'],r['last_seen_at']) for p,r in reappeared.items()}
        native.run('capture_posting_census.hwf',dict(RUN_ID='first-absence'),'native-census-replay')
        native.run('freeze_observations.hwf',dict(RELEASE_ID='two-absences'),'native-observation-replay')
        native.run('read_observations.hwf',dict(RELEASE_ID='two-absences',PREVIEW='Y'),'native-observation-read')
        native.run('read_source_health.hwf',dict(RELEASE_ID='two-absences',PREVIEW='Y'),'native-source-health')
        native.run('../operations/record_graph_export.hpl',dict(RUN_ID='first-absence'),'native-refresh-census-hook')
        assert sql("SELECT count(*) FROM ingestion.graph_export WHERE run_id='first-absence'")=='1'
        native.run('../operations/record_graph_export.hpl',dict(RUN_ID='fixture-ncs_competency'),'native-reference-checkpoint')
        assert sql("SELECT count(*) FROM ontology.observation_run WHERE source_id<>'job_alio'")=='0'
        err("SELECT ingestion.record_graph_export_v1('failed-detail')",'GRAPH_EXPORT_REQUIRES_READY_SNAPSHOT')
        err("BEGIN; UPDATE ingestion.document SET verified_at=NULL WHERE run_id='second-absence'; SELECT ingestion.record_graph_export_v1('second-absence'); ROLLBACK;",'OBSERVATION_REQUIRES_VERIFIED_DOCUMENTS')
        assert sql("SELECT count(*) FROM ingestion.graph_export WHERE run_id='second-absence'")=='0'
        native.run('read_observations.hwf',dict(RELEASE_ID='two-absences'),'native-unpublished-rejection',False)
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        assert sql('SELECT count(*) FROM enrichment.attempt')=='0'
        print('OBSERVATION CHECKS PASSED: midnight/closure/absence, failed and partial runs, reappearance, history/replay, freshness boundaries, native workflows and retention protection.',flush=True)
        print('Native fixture:',native.WORK,flush=True)
    finally:
        for container in [hop,run.PG]:subprocess.run(['docker','rm','-fv',container],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__=='__main__':main()
