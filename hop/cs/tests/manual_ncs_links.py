"""Disposable PostgreSQL check for atomic, source-bound manual NCS packets."""
from pathlib import Path
import json
import subprocess
import time

import common_postings as fixture

ROOT=Path(__file__).resolve().parents[3]
NAME=fixture.NAME
sql=fixture.sql
run=fixture.run


def quoted(value):
    return "$packet$"+json.dumps(value,ensure_ascii=False,separators=(',',':'))+"$packet$::jsonb"


def reject(statement, marker):
    result=subprocess.run(
        ['docker','exec','-i',NAME,'psql','-X','-v','ON_ERROR_STOP=1',
         '-A','-t','-U','postgres','-d','postgres'],
        input=statement,text=True,capture_output=True)
    assert result.returncode!=0 and marker in result.stderr,(marker,result.stderr)


def decide(packet):
    packet['reviewer']='Synthetic NCS semantic reviewer'
    packet['reviewer_kind']='assistant'
    for case in packet['cases']:
        case['decision']='ACCEPT' if case['competency_code']=='data-unit' else 'REJECT'
        case['reason']='Source duty DB 구축 directly matches database implementation' \
            if case['decision']=='ACCEPT' else 'The explicit DB duty does not support finance accounting'
        case['notes']='Reviewed the exact source duty and full current NCS definition'
    return packet


def main():
    try:
        run(['docker','run','-d','--name',NAME,'-e',
             'POSTGRES_HOST_AUTH_METHOD=trust','postgres:17-alpine'])
        for _ in range(50):
            try:
                if 'PostgreSQL init process complete' in run(['docker','logs',NAME]) \
                   and sql('SELECT 1')=='1': break
            except RuntimeError: pass
            time.sleep(0.2)
        else: raise RuntimeError('PostgreSQL fixture did not become ready')
        sql(fixture.SETUP)
        sql((ROOT/'hop/cs/sql/001_common_postings.sql').read_text())
        sql(r"""
CREATE SCHEMA retention;
CREATE FUNCTION retention.gate() RETURNS void LANGUAGE plpgsql AS $$ BEGIN RETURN; END $$;
ALTER TABLE enrichment.batch ADD COLUMN ncs_run_id text;
ALTER TABLE enrichment.item ADD COLUMN source_data jsonb;
UPDATE enrichment.batch SET ncs_run_id='ncs-1' WHERE batch_id='legacy-batch';
UPDATE enrichment.item SET source_data='{"title":"데이터 엔지니어","duties_text":"DB 구축"}'::jsonb
 WHERE item_id='legacy-item';
INSERT INTO ingestion.run VALUES('ncs-1','ncs_competency','READY','FULL');
ALTER TABLE enrichment.ncs_catalog ADD COLUMN name text;
ALTER TABLE enrichment.ncs_catalog ADD COLUMN definition text;
ALTER TABLE enrichment.ncs_catalog ADD COLUMN occupation_name text;
INSERT INTO enrichment.ncs_catalog
 (run_id,code,name,definition,occupation_code,occupation_name) VALUES
 ('ncs-1','data-unit','데이터베이스 구축','요구 분석 후 데이터베이스를 설계하고 구현한다','200102','정보기술개발'),
 ('ncs-1','finance-unit','회계 원장 작성','재무 회계 장부와 결산을 처리한다','020302','회계');
UPDATE enrichment.extraction_review_state SET extraction=
 '{"positions":[{"id":"p1","name":"데이터 엔지니어","evidence_ids":["title:1"]},
                {"id":"p2","name":"행정 직원","evidence_ids":["notice:4"]}],
   "duties":[{"position_ids":["p1"],"text":"DB 구축","evidence_ids":["notice:2"]},
             {"position_ids":["p2"],"text":"회계 행정","evidence_ids":["notice:5"]}],
   "duties_status":"explicit"}'::jsonb WHERE revision_id='legacy-revision';
CREATE TABLE enrichment.extraction_revision
 (revision_id text PRIMARY KEY,item_id text,extraction jsonb);
INSERT INTO enrichment.extraction_revision SELECT revision_id,item_id,extraction
 FROM enrichment.extraction_review_state;
CREATE TABLE enrichment.extraction_decision
 (decision_id bigint GENERATED ALWAYS AS IDENTITY,revision_id text,
  decision text,reviewer text,reviewer_kind text,notes text);
INSERT INTO enrichment.extraction_decision(revision_id,decision,reviewer,reviewer_kind,notes)
 VALUES('legacy-revision','ACCEPT','Fixture','assistant','Accepted role extraction');
CREATE VIEW enrichment.latest_extraction_decision AS
 SELECT DISTINCT ON(revision_id) * FROM enrichment.extraction_decision
 ORDER BY revision_id,decision_id DESC;
ALTER TABLE enrichment.link_candidate ADD COLUMN reason text;
ALTER TABLE enrichment.link_candidate ADD COLUMN origin text;
ALTER TABLE enrichment.link_candidate ADD COLUMN actor text;
ALTER TABLE enrichment.link_decision ADD COLUMN reviewer text;
ALTER TABLE enrichment.link_decision ADD COLUMN reviewer_kind text;
ALTER TABLE enrichment.link_decision ADD COLUMN notes text;
CREATE VIEW enrichment.latest_link_decision AS
 SELECT DISTINCT ON(candidate_id) * FROM enrichment.link_decision
 ORDER BY candidate_id,decision_id DESC;
CREATE FUNCTION enrichment.verify_item_input(id text) RETURNS void LANGUAGE plpgsql AS $$
 BEGIN IF NOT EXISTS(SELECT 1 FROM enrichment.item WHERE item_id=id AND source_data IS NOT NULL)
 THEN RAISE EXCEPTION 'ITEM_INPUT_MISSING'; END IF; END $$;
CREATE FUNCTION enrichment.propose_link(revision text,code text,duty integer,
 explanation text,who text,provenance text DEFAULT 'reviewer') RETURNS text
 LANGUAGE plpgsql AS $$
 DECLARE key text:=enrichment.hash(jsonb_build_array(revision,code,duty)::text);
 existing enrichment.link_candidate%ROWTYPE; BEGIN
 SELECT * INTO existing FROM enrichment.link_candidate WHERE candidate_id=key;
 IF existing.candidate_id IS NOT NULL THEN
  IF existing.reason<>explanation OR existing.origin<>provenance
  THEN RAISE EXCEPTION 'LINK_CANDIDATE_IS_IMMUTABLE'; END IF;
  RETURN key;
 END IF;
 INSERT INTO enrichment.link_candidate VALUES
 (key,revision,(SELECT b.ncs_run_id FROM enrichment.extraction_revision r
 JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
 WHERE r.revision_id=revision),code,duty,explanation,provenance,who);
 RETURN key; END $$;
CREATE FUNCTION enrichment.decide_link(candidate text,choice text,who text,
 kind text,explanation text) RETURNS void LANGUAGE sql AS $$
 INSERT INTO enrichment.link_decision(candidate_id,decision,reviewer,reviewer_kind,notes)
 VALUES(candidate,choice,who,kind,explanation) $$;
""")
        sql((ROOT/'hop/cs/sql/002_scope.sql').read_text())
        binding=sql("SELECT binding_hash FROM cs.scope_screen WHERE role_id='p1'")
        sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p1','{binding}',"
            "'IN_SCOPE','DATA','Fixture','assistant','DB implementation is technical data work')")
        sql((ROOT/'hop/cs/sql/005_manual_ncs_links.sql').read_text())
        assert sql("SELECT scope_status FROM cs.current_scope WHERE role_id='p1'")=='IN_SCOPE'
        assert sql("SELECT count(*) FROM enrichment.extraction_revision r JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id) JOIN ingestion.latest_ready_run n ON n.source_id='ncs_competency' AND n.run_id=b.ncs_run_id WHERE r.revision_id='legacy-revision' AND i.source_hash='prepared-content-hash-for-alio-snapshot-123'")=='1'
        assert sql("SELECT count(*) FROM cs.current_scope s JOIN enrichment.extraction_revision r ON r.revision_id=s.revision_id JOIN enrichment.item i ON i.item_id=r.item_id JOIN enrichment.batch b ON b.batch_id=i.batch_id JOIN enrichment.latest_extraction_decision ed ON ed.revision_id=r.revision_id AND ed.decision='ACCEPT' JOIN ingestion.latest_ready_run n ON n.source_id='ncs_competency' JOIN enrichment.ncs_catalog c ON c.run_id=n.run_id AND c.code='data-unit' WHERE s.posting_identity='job-alio:posting:123' AND s.role_id='p1' AND s.source_id='job_alio' AND s.scope_status='IN_SCOPE' AND s.content_hash=i.source_hash AND b.mode='ENRICH' AND b.ncs_run_id=n.run_id AND coalesce(r.extraction->'duties'->0->'position_ids','[]'::jsonb) ? 'p1'")=='1'
        selections=[{'posting_identity':'job-alio:posting:123','role_id':'p1',
                     'duty_index':0,'competency_code':code}
                    for code in ('data-unit','finance-unit')]
        packet=json.loads(sql("SELECT cs.prepare_manual_ncs_link_review_v1("
                            +quoted(selections)+",'Fixture exporter')"))
        assert len(packet['cases'])==2
        assert packet['cases'][0]['context']['source_data']['duties_text']=='DB 구축'
        assert packet['cases'][0]['context']['ncs_definition']=='요구 분석 후 데이터베이스를 설계하고 구현한다'
        assert packet['cases'][0]['context']['duty']['position_ids']==['p1']
        reject("SELECT cs.prepare_manual_ncs_link_review_v1("
               +quoted([dict(selections[0],duty_index=1)])+",'Fixture exporter')",
               'MANUAL_NCS_LINK_CONTEXT_NOT_CURRENT_OR_DUTY_NOT_ROLE_BOUND')
        reject("SELECT cs.prepare_manual_ncs_link_review_v1("
               +quoted([selections[0],selections[0]])+",'Fixture exporter')",
               'INVALID_OR_DUPLICATE_MANUAL_NCS_LINK_SELECTION')
        decide(packet)
        tampered=json.loads(json.dumps(packet))
        tampered['cases'][1]['context']['ncs_definition']='altered definition'
        reject('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(tampered)+')',
               'MANUAL_NCS_LINK_CONTEXT_OR_DEFINITION_CHANGED')
        assert sql('SELECT count(*) FROM enrichment.link_candidate')=='0'
        assert sql('SELECT count(*) FROM enrichment.link_decision')=='0'
        first=json.loads(sql('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(packet)+')'))
        assert (first['new_candidates'],first['new_decisions'],first['unchanged_decisions'])==(2,2,0),first
        assert sql('SELECT count(*) FROM enrichment.link_candidate')=='2'
        assert sql('SELECT count(*) FROM enrichment.link_decision')=='2'
        assert sql("SELECT count(*) FROM enrichment.latest_link_decision WHERE decision='ACCEPT'")=='1'
        replay=json.loads(sql('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(packet)+')'))
        assert replay['replayed'] and replay['import_id']==first['import_id']
        fresh=decide(json.loads(sql("SELECT cs.prepare_manual_ncs_link_review_v1("
                                  +quoted(selections)+",'Fixture exporter')")))
        unchanged=json.loads(sql('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(fresh)+')'))
        assert (unchanged['new_candidates'],unchanged['new_decisions'],
                unchanged['unchanged_decisions'])==(0,0,2),unchanged
        assert sql('SELECT count(*) FROM enrichment.link_decision')=='2'
        reject("UPDATE cs.manual_ncs_link_import SET reviewer='altered'",
               'MANUAL_NCS_LINK_RECEIPT_IS_IMMUTABLE')
        # A changed accepted revision or NCS definition invalidates an exported
        # packet and cannot leave a partial link decision behind.
        sql("UPDATE enrichment.extraction_review_state SET extraction="
            "jsonb_set(extraction,'{positions,0,name}',to_jsonb('데이터 분석가'::text)) "
            "WHERE revision_id='legacy-revision'")
        # Use a *new* choice to avoid the exact replay receipt shortcut.
        stale=json.loads(json.dumps(fresh))
        stale['cases'][0]['notes']='Changed note after revised role'
        reject('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(stale)+')',
               'MANUAL_NCS_LINK_CONTEXT_NOT_CURRENT_OR_DUTY_NOT_ROLE_BOUND')
        assert sql('SELECT count(*) FROM enrichment.link_decision')=='2'
        sql("UPDATE enrichment.extraction_review_state SET extraction="
            "jsonb_set(extraction,'{positions,0,name}',to_jsonb('데이터 엔지니어'::text)) "
            "WHERE revision_id='legacy-revision'")
        sql("UPDATE enrichment.ncs_catalog SET definition='Changed current definition' "
            "WHERE run_id='ncs-1' AND code='data-unit'")
        reject('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(stale)+')',
               'MANUAL_NCS_LINK_CONTEXT_OR_DEFINITION_CHANGED')
        sql("UPDATE enrichment.ncs_catalog SET definition='요구 분석 후 데이터베이스를 설계하고 구현한다' "
            "WHERE run_id='ncs-1' AND code='data-unit'")
        sql("UPDATE ingestion.run SET state='ARCHIVED' WHERE run_id='ncs-1'; "
            "INSERT INTO ingestion.run VALUES('ncs-2','ncs_competency','READY','FULL')")
        reject('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(stale)+')',
               'MANUAL_NCS_LINK_CONTEXT_NOT_CURRENT_OR_DUTY_NOT_ROLE_BOUND')
        sql("DELETE FROM ingestion.run WHERE run_id='ncs-2'; "
            "UPDATE ingestion.run SET state='READY' WHERE run_id='ncs-1'")
        sql("UPDATE enrichment.item SET source_hash='superseded-input' WHERE item_id='legacy-item'")
        reject('SELECT cs.apply_manual_ncs_link_review_v1('+quoted(stale)+')',
               'MANUAL_NCS_LINK_CONTEXT_NOT_CURRENT_OR_DUTY_NOT_ROLE_BOUND')
        assert sql('SELECT count(*) FROM enrichment.link_decision')=='2'
        print('manual NCS packets: role-bound duty, full definition, atomic tamper rejection, named decisions, replay, stale role/catalog/run/source passed')
    finally:
        subprocess.run(['docker','rm','-f',NAME],capture_output=True)


if __name__=='__main__': main()
