"""Position-level scope and NCS link checks on disposable PostgreSQL."""
from pathlib import Path
import json
import subprocess
import time

import common_postings as fixture

ROOT=Path(__file__).resolve().parents[3]
NAME=fixture.NAME
sql=fixture.sql
run=fixture.run

EXTRA=r"""
UPDATE enrichment.extraction_review_state SET extraction=
'{"positions":[{"id":"p1","name":"데이터 엔지니어","evidence_ids":["title:1"]},{"id":"p2","name":"행정 직원","evidence_ids":["notice:4"]}],"duties":[{"position_ids":["p1"],"text":"DB 구축"},{"position_ids":["p2"],"text":"회계 행정"}],"duties_status":"explicit"}'::jsonb
WHERE revision_id='legacy-revision';
INSERT INTO enrichment.ncs_catalog VALUES
 ('ncs-snapshot','2001010501_test','20010105'),
 ('ncs-snapshot','0101010101_test','01010101'),
 ('ncs-snapshot','1703060302_test','17030603');
INSERT INTO enrichment.linking_status(posting_id,source_hash,ncs_run_id,ncs_links,extraction,outcome,revision_id)
SELECT '123','prepared-content-hash-for-alio-snapshot-123',
'ncs-snapshot',
'[{"candidate_id":"data-link","competency_code":"2001010501_test","duty_index":0,"reason":"DB 구축","duty":{"position_ids":["p1"],"text":"DB 구축"}},
  {"candidate_id":"admin-link","competency_code":"0101010101_test","duty_index":1,"reason":"회계 행정","duty":{"position_ids":["p2"],"text":"회계 행정"}}]'::jsonb,
 extraction,'ACCEPTED_LINKS','legacy-revision'
FROM enrichment.extraction_review_state WHERE revision_id='legacy-revision';
"""

THIRD_ROLE=r"""
UPDATE enrichment.extraction_review_state SET extraction=
'{"positions":[{"id":"p1","name":"데이터 엔지니어","evidence_ids":["title:1"]},{"id":"p2","name":"행정 직원","evidence_ids":["notice:4"]},{"id":"p3","name":"AI 개발 연구원 (신약)","evidence_ids":["notice:6"]}],"duties":[{"position_ids":["p1"],"text":"DB 구축"},{"position_ids":["p2"],"text":"회계 행정"},{"position_ids":["p3"],"text":"후보 화합물 설계"}],"duties_status":"explicit"}'::jsonb
WHERE revision_id='legacy-revision';
UPDATE enrichment.linking_status SET
 extraction=(SELECT extraction FROM enrichment.extraction_review_state WHERE revision_id='legacy-revision'),
 ncs_links=ncs_links||'[{"candidate_id":"drug-link","competency_code":"1703060302_test","duty_index":2,"reason":"후보 화합물 설계","duty":{"position_ids":["p3"],"text":"후보 화합물 설계"}}]'::jsonb
WHERE posting_id='123';
"""

def main():
    try:
        run(['docker','run','-d','--name',NAME,'-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:17-alpine'])
        for _ in range(50):
            try:
                if 'PostgreSQL init process complete' in run(['docker','logs',NAME]) and sql('SELECT 1')=='1':
                    break
            except RuntimeError:
                pass
            time.sleep(0.2)
        else: raise RuntimeError('PostgreSQL fixture did not start')
        sql(fixture.SETUP)
        sql((ROOT/'hop/cs/sql/001_common_postings.sql').read_text())
        sql(EXTRA)
        sql(THIRD_ROLE)
        sql((ROOT/'hop/cs/sql/002_scope.sql').read_text())
        sql((ROOT/'hop/cs/sql/003_completion_report.sql').read_text())
        assert sql("SELECT cs.scope_title_families_v1('전산<br>개발')::text")=='{SOFTWARE}'
        assert 'IT_SYSTEMS' in sql("SELECT cs.scope_duty_families_v1('Kubernetes 컨테이너 플랫폼 아키텍처 설계와 CI/CD')::text")
        assert 'SECURITY' in sql("SELECT cs.scope_duty_families_v1('사이버 위협정보와 랜섬웨어 분석')::text")
        assert 'DATA' in sql("SELECT cs.scope_duty_families_v1('메타데이터와 데이터 정제 및 품질검증')::text")
        assert sql("SELECT cs.scope_title_families_v1('정보통신 행정')::text")=='{}'
        roles=json.loads(sql("SELECT jsonb_agg(jsonb_build_object('id',role_id,'name',role_name,'status',screen_status,'binding',binding_hash) ORDER BY role_id) FROM cs.scope_screen"))
        assert [(r['id'],r['status']) for r in roles]==[
            ('p1','IN_SCOPE_CANDIDATE'),('p2','OUT_OF_SCOPE_CANDIDATE'),
            ('p3','IN_SCOPE_CANDIDATE')],roles
        p1=roles[0]['binding'];p2=roles[1]['binding'];p3=roles[2]['binding']
        first=sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p1','{p1}','IN_SCOPE','DATA','fixture reviewer','assistant','DB build is technical data work')")
        again=sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p1','{p1}','IN_SCOPE','DATA','fixture reviewer','assistant','DB build is technical data work')")
        assert first==again
        sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p2','{p2}','OUT_OF_SCOPE',NULL,'fixture reviewer','assistant','Accounting administration is outside technical scope')")
        sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p3','{p3}','IN_SCOPE','AI','fixture reviewer','assistant','Drug-design work uses AI')")
        completion=json.loads(sql("SELECT jsonb_agg(jsonb_build_object('role',role_id,'scope',scope_status,'links',accepted_role_links,'technical',technical_role_links,'domain',domain_role_links,'action',next_action) ORDER BY role_id) FROM cs.role_completion"))
        assert completion==[
            {'role':'p1','scope':'IN_SCOPE','links':1,'technical':1,'domain':0,'action':'PUBLISHED_NCS_LINK'},
            {'role':'p2','scope':'OUT_OF_SCOPE','links':0,'technical':0,'domain':0,'action':'SCOPE_REVIEW_OR_EXCLUSION'},
            {'role':'p3','scope':'IN_SCOPE','links':1,'technical':0,'domain':1,'action':'PUBLISHED_DOMAIN_NCS_LINK'}],completion
        # The posting-level LINK_REVIEW is caused by pending matches to p2/p3.
        # It must not tell p1 to review candidates for another position.
        sql("""
UPDATE enrichment.linking_status SET ncs_links='[]'::jsonb,outcome='LINK_REVIEW' WHERE posting_id='123';
INSERT INTO enrichment.link_candidate VALUES
 ('admin-pending','legacy-revision','ncs-snapshot','0101010101_test',1),
 ('drug-pending','legacy-revision','ncs-snapshot','1703060302_test',2),
 ('data-old-snapshot','legacy-revision','older-ncs-snapshot','2001010501_test',0);
""")
        pending=json.loads(sql("SELECT jsonb_agg(jsonb_build_object('role',role_id,'pending',pending_role_candidates,'action',next_action) ORDER BY role_id) FROM cs.role_completion"))
        assert pending==[
            {'role':'p1','pending':0,'action':'INVESTIGATE_ROLE_LINK_GAP'},
            {'role':'p2','pending':0,'action':'SCOPE_REVIEW_OR_EXCLUSION'},
            {'role':'p3','pending':1,'action':'REVIEW_SAVED_LINKS'}],pending
        sql("INSERT INTO enrichment.link_candidate VALUES ('data-pending','legacy-revision','ncs-snapshot','2001010501_test',0)")
        assert sql("SELECT pending_role_candidates||':'||next_action FROM cs.role_completion WHERE role_id='p1'")=='1:REVIEW_SAVED_LINKS'
        sql("INSERT INTO enrichment.link_decision(candidate_id,decision) VALUES ('drug-pending','REJECT')")
        assert sql("SELECT pending_role_candidates||':'||next_action FROM cs.role_completion WHERE role_id='p3'")=='0:INVESTIGATE_ROLE_LINK_GAP'
        sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p1','{p1}','NEEDS_REVIEW',NULL,'fixture reviewer','assistant','Rechecking mixed-role duty')")
        restored=sql(f"SELECT cs.decide_scope_v1('job-alio:posting:123','p1','{p1}','IN_SCOPE','DATA','fixture reviewer','assistant','DB build is technical data work')")
        assert restored!=first and sql("SELECT scope_status FROM cs.current_scope WHERE role_id='p1'")=='IN_SCOPE'
        # A corrected position changes the role binding even when its posting ID
        # stays the same; the old decision must disappear instead of leaking.
        sql("UPDATE enrichment.extraction_review_state SET extraction=jsonb_set(extraction,'{positions,0,name}',to_jsonb('데이터 분석가'::text)) WHERE revision_id='legacy-revision'")
        assert sql("SELECT scope_status FROM cs.current_scope WHERE role_id='p1'")=='NEEDS_REVIEW'
        stale=subprocess.run(['docker','exec','-i',NAME,'psql','-X','-v','ON_ERROR_STOP=1','-A','-t','-U','postgres','-d','postgres'],
            input=f"SELECT cs.decide_scope_v1('job-alio:posting:123','p1','{p1}','IN_SCOPE','DATA','fixture reviewer','assistant','stale')",text=True,capture_output=True)
        assert stale.returncode!=0 and 'STALE_SCOPE_BINDING' in stale.stderr,stale.stderr
        # A pending or rejected correction must not replace an accepted roster
        # in the selected scope. Only an accepted child revision can do so.
        sql("""
INSERT INTO enrichment.extraction_review_state VALUES
 ('child-revision','legacy-item',NULL,
  '{"positions":[{"id":"p4","name":"새 데이터 개발 직무","evidence_ids":["notice:8"]}],
    "duties":[{"position_ids":["p4"],"text":"DB 구축"}]}',2,'assistant');
""")
        assert sql("SELECT string_agg(role_id,',' ORDER BY role_id) FROM cs.current_scope")=='p1,p2,p3'
        sql("UPDATE enrichment.extraction_review_state SET decision='REJECT' WHERE revision_id='child-revision'")
        assert sql("SELECT string_agg(role_id,',' ORDER BY role_id) FROM cs.current_scope")=='p1,p2,p3'
        sql("UPDATE enrichment.extraction_review_state SET decision='ACCEPT' WHERE revision_id='child-revision'")
        assert sql("SELECT string_agg(role_id,',' ORDER BY role_id) FROM cs.current_scope")=='p4'
        print('scope completion: mixed roles, bounded decisions, replay and stale binding passed')
    finally:
        subprocess.run(['docker','rm','-f',NAME],capture_output=True)

if __name__=='__main__':main()
