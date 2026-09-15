"""Disposable ontology ledger/source assembly checks. No external API or model calls."""
from pathlib import Path
import subprocess,json,os,time,uuid
ROOT=Path(__file__).resolve().parents[3]
PG='jobtology-ontology-test-pg'

def cmd(args,**kwargs):
 p=subprocess.run(args,text=True,capture_output=True,**kwargs)
 if p.returncode:raise RuntimeError(p.stderr[-5000:])
 return p.stdout.strip()
def sql(value):return cmd(['docker','exec','-i',PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','ontologytest'],input=value)
def q(value):return "'"+str(value).replace("'","''")+"'"
def js(value):return q(json.dumps(value,ensure_ascii=False))+'::jsonb'
def boot():
 if subprocess.run(['docker','inspect',PG],capture_output=True).returncode:
  cmd(['docker','run','-d','--name',PG,'-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=ontologytest','postgres:18-alpine'])
 for _ in range(60):
  # PostgreSQL's temporary init server accepts socket connections before the
  # requested database is created. TCP becomes ready only on the final server.
  if subprocess.run(['docker','exec',PG,'pg_isready','-h','127.0.0.1','-U','postgres','-d','ontologytest'],capture_output=True).returncode==0:break
  time.sleep(.2)
 sql('DROP SCHEMA IF EXISTS ontology CASCADE; DROP SCHEMA IF EXISTS retention CASCADE; DROP SCHEMA IF EXISTS enrichment CASCADE; DROP SCHEMA IF EXISTS ingestion CASCADE;')
 sql((ROOT/'docs/hop-migration/schema.sql').read_text())
 sql("CREATE VIEW ingestion.validation_issue AS SELECT NULL::text AS run_id,NULL::text AS issue WHERE false; CREATE VIEW ingestion.latest_ready_run AS SELECT DISTINCT ON(source_id) * FROM ingestion.run WHERE state='READY' AND mode<>'SMOKE' ORDER BY source_id,created_at DESC,run_id DESC;")
 for f in sorted((ROOT/'hop/llm/sql').glob('*.sql')):sql(f.read_text())
 sql((ROOT/'docs/hop-migration/operations.sql').read_text())
 sql((ROOT/'hop/retention/sql/001_retention.sql').read_text())
 for f in sorted((ROOT/'hop/attachments/sql').glob('*.sql')):sql(f.read_text())
 for f in sorted((ROOT/'hop/ontology/sql').glob('*.sql')):sql(f.read_text())

def load_sources(records):
 for sid,rows in records.items():
  run='fixture-'+sid
  sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at) VALUES({q(run)},{q(sid)},'FULL','fixture','READY','2026-09-01T00:00:00Z','2026-09-01T00:01:00Z'); INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(run)},'all','FILE',1); INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at) VALUES({q(run)},'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,'2026-09-01T00:00:30Z',true,now());")
  for idx,row in enumerate(rows):
   rid=row.get('posting_id','record-'+str(idx))+(':'+row['representation'] if 'representation' in row else '')
   sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(run)},'doc',{q(str(idx))},{q(rid)},{js(row)},{js(row)})")

def fixture():
 unit=lambda code,name:dict(kind='Competency',code=code,name=name,definition=name+'를 수행하는 능력',level=4,occupation_code='20010201',occupation_name='정보기술개발',classification_names=['정보통신','정보기술','정보기술개발'])
 qual=lambda code:dict(kind='QualificationMapping',competency_code=code,qualification_code='T5H0',qualification_name='정보기술 자격',standard_version='22V1',unit_type='MAND',minimum_training_hours=40,total_training_hours=410,examining_organization='한국산업인력공단')
 job=dict(kind='JobPosting',posting_id='001',organization_code='C001',organization_name='동일 기관명',title='이전 제목',ongoing=True,source_url='https://example.org/jobs/001',date_posted='2026-09-01',closing_date='2026-10-01',education='학력무관',eligibility_text='담당 업무: 데이터베이스 설계 및 구축')
 return {
  'alio_organization':[dict(kind='Organization',code=code,name='동일 기관명') for code in ['C001','C002']],
  'job_alio':[job|dict(representation='list',organization_code='C002'),job|dict(representation='detail',title='데이터 엔지니어 채용',ongoing=None)],
  'ncs_competency':[unit('2001020101_20v1','데이터베이스 설계'),unit('2001020101_24v2','데이터베이스 설계 개선'),unit('2001020102_24v1','데이터베이스 구축')],
  'ncs_qualification':[qual('2001020101_24v2'),qual('2001020199_19v1')],
  'qnet_schedule':[dict(kind='ExamSession',qualification_code='T5H0',year=2026,round=r,category_code='C',name='정기 자격 시험',dates={'docRegEndDt':'2026-10-01'}) for r in [1,2]],
  'ncs_career_path':[dict(kind='CareerPath',occupation_code='20010201',occupation_name='정보기술 개발자',competency_code='2001020101',competency_name='데이터베이스 설계',competency_level=level,rank_level=level,rank_name=name) for level,name in [(3,'실무자'),(5,'책임자')]]}

def expect_error(query,word):
 try:sql(query);raise AssertionError('Expected '+word)
 except RuntimeError as e:assert word in str(e),str(e)

def check():
 records=fixture();load_sources(records)
 sql("SELECT ontology.prepare_release('fixture-release'); SELECT ontology.assemble_sources('fixture-release')")
 coverage=json.loads(sql("SELECT jsonb_agg(to_jsonb(c)) FROM ontology.source_coverage c"))
 assert len(coverage)==6 and all(c['record_count']==len(records[c['source_id']]) and c['unaccounted_records']==0 for c in coverage),coverage
 assert sql("SELECT count(*) FROM ontology.entity WHERE kind='organization'")=='2','Merged names without official identity'
 payload=json.loads(sql("SELECT payload FROM ontology.revision WHERE entity_id='urn:jobtology:jobPosting:job_alio:001'"))
 assert payload['title']=='데이터 엔지니어 채용' and payload['source_status']=='OPEN',payload
 assert payload['date_precision']=='DAY' and payload['primary_occupation_id'] is None
 assert sql("SELECT count(*)=1 AND min(object_id)='urn:jobtology:organization:alio:C001' FROM ontology.source_relation WHERE predicate='POSTED_BY'")=='t','Published stale list employer over detail'
 assert sql("SELECT count(*) FROM ontology.source_relation WHERE predicate='VERSION_OF' AND object_id='urn:jobtology:ncsUnitFamily:2001020101'")=='2'
 assert sql("SELECT count(*) FROM ontology.entity WHERE kind='examSession'")=='2'
 assert sql("SELECT count(*) FROM ontology.entity WHERE kind='ncsClass'")=='4'
 assert sql("SELECT count(*) FROM ontology.quality_observation WHERE code='REFERENCE_WITHOUT_DEFINITION'")=='1'
 assert sql("SELECT count(*) FROM ontology.source_relation WHERE predicate='ATTESTS'")=='0'
 assert sql("SELECT min(record_count)>0 AND min(data_as_of)='2026-09-01T00:00:30Z' FROM ontology.source_pin JOIN ontology.corpus_release USING(release_id)")=='t'
 before=sql("SELECT ontology.hash(jsonb_build_object('entities',(SELECT jsonb_agg(e ORDER BY entity_id) FROM ontology.entity e),'revisions',(SELECT jsonb_agg(r ORDER BY revision_id) FROM ontology.revision r),'relations',(SELECT jsonb_agg(r ORDER BY relation_id) FROM ontology.source_relation r)))")
 sql("SELECT ontology.prepare_release('fixture-release'); SELECT ontology.assemble_sources('fixture-release')")
 after=sql("SELECT ontology.hash(jsonb_build_object('entities',(SELECT jsonb_agg(e ORDER BY entity_id) FROM ontology.entity e),'revisions',(SELECT jsonb_agg(r ORDER BY revision_id) FROM ontology.revision r),'relations',(SELECT jsonb_agg(r ORDER BY relation_id) FROM ontology.source_relation r)))")
 assert before==after,'Replay mutated ontology'
 assert sql("SELECT retention.protection('fixture-ncs_career_path',0)")=='ONTOLOGY_RELEASE'
 # Verification timestamps can advance without changing immutable source content.
 sql("UPDATE ingestion.document SET verified_at=now(); SELECT ontology.check_frozen_sources('fixture-release')")
 expect_error("UPDATE ontology.revision SET name='overwrite'",'IMMUTABLE_ONTOLOGY_RECORD')
 expect_error("SELECT ontology.prepare_release('fixture-release','{\"job_alio\":\"different\"}')",'RELEASE_SOURCE_SELECTION_IS_IMMUTABLE')
 expect_error("BEGIN; UPDATE ingestion.record SET normalized=jsonb_set(normalized,'{title}','\"changed\"') WHERE source_record_id='001:detail'; SELECT ontology.check_frozen_sources('fixture-release'); COMMIT;",'PINNED_SOURCE_CHANGED')
 assert sql("SELECT state FROM ontology.corpus_release WHERE release_id='fixture-release'")=='PREPARING','Source assembly activated an incomplete release'
 print('SOURCE LEDGER CHECKS PASSED: six-source accounting, paired postings, hierarchy, versions, qualifiers, names, replay, retention and immutable source evidence',flush=True)

if __name__=='__main__':
 try:boot();check()
 finally:
  if not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER'):subprocess.run(['docker','rm','-fv',PG],capture_output=True)
