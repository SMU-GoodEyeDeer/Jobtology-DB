"""Generate native archive-only fetching for the document-processor path."""
from pathlib import Path
import json,xml.etree.ElementTree as E,copy,runpy
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/attachments'
policy=json.loads((OUT/'policy.json').read_text());policy.update(policy_id='job-alio-documents-v3',revision='2026-09-14.2',formats=['pdf','hwp','hwpx','doc','docx','zip'],parser_version='document-processor-v1')
policy['other_roles']['named_notice_or_jd']='Include non-B files named 직무기술/직무설명/직무수행/공고문 or Job Description; preserve the provider role in metadata.'
(OUT/'processor-policy.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2)+'\n')
source=(OUT/'sql/001_documents.sql').read_text();begin=source.index('CREATE OR REPLACE FUNCTION attachment.prepare(');end=source.index('CREATE OR REPLACE FUNCTION attachment.reserve(',begin)
prepare=source[begin:end].replace('attachment.prepare(', 'attachment.prepare_downloads(').replace('prepare.run','prepare_downloads.run').replace("'job-alio-attachments-v1'","'job-alio-documents-v3'").replace("('pdf','hwp','hwpx')","('pdf','hwp','hwpx','doc','docx','zip')")
prepare=prepare.replace("WHEN coalesce(f.value->>'atchFileType','') NOT IN ('A','C') THEN 'ROLE_REVIEW'", "WHEN coalesce(f.value->>'atchFileType','') NOT IN ('A','C') AND coalesce(f.value->>'atchFileNm','') !~* '(직무(기술|설명|수행)|공고문|job[ _-]*description)' THEN 'ROLE_REVIEW'")
literal="'"+json.dumps(policy,ensure_ascii=False).replace("'","''")+"'::jsonb"
extra='''
-- Reused attempts reference one immutable archive instead of copying its bytes.
ALTER TABLE attachment.attempt DROP CONSTRAINT IF EXISTS attempt_raw_path_key;
ALTER TABLE attachment.attempt DROP CONSTRAINT IF EXISTS attempt_state_check;
ALTER TABLE attachment.attempt ADD CONSTRAINT attempt_state_check CHECK(state IN
 ('RESERVED','ARCHIVED','ARCHIVED_ONLY','PARSED','HTTP_ERROR','UNEXPECTED_CONTENT','EMPTY_DOCUMENT','TOO_LARGE','PARSE_ERROR','NEEDS_REVIEW','NO_TEXT','TRANSPORT_ERROR'));
CREATE TABLE IF NOT EXISTS attachment.archive_reuse (
 attempt_id text PRIMARY KEY REFERENCES attachment.attempt,
 previous_attempt_id text NOT NULL REFERENCES attachment.attempt,
 reused_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE OR REPLACE FUNCTION attachment.finish_download(id text,child_ok boolean,errors bigint) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 UPDATE attachment.attempt SET state='ARCHIVED_ONLY',issue=NULL,finished_at=clock_timestamp()
 WHERE attempt_id=id AND state='ARCHIVED' AND child_ok IS TRUE AND errors=0;
 UPDATE attachment.attempt SET state='TRANSPORT_ERROR',issue='DOWNLOAD_CHILD_FAILED',finished_at=clock_timestamp()
 WHERE attempt_id=id AND state IN ('RESERVED','ARCHIVED');
 IF NOT EXISTS(SELECT 1 FROM attachment.attempt WHERE attempt_id=id AND finished_at IS NOT NULL) THEN RAISE EXCEPTION 'DOWNLOAD_NOT_TERMINAL'; END IF;
 PERFORM retention.leave_writer(id);
END $$;
CREATE OR REPLACE FUNCTION attachment.record_reuse(id text,previous text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN
 IF previous IS NULL THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM attachment.attempt a JOIN attachment.attempt old ON old.attempt_id=previous
 JOIN attachment.document d ON d.document_id=a.document_id JOIN attachment.document od ON od.document_id=old.document_id
 WHERE a.attempt_id=id AND a.raw_hash=old.raw_hash AND a.byte_length=old.byte_length AND d.metadata=od.metadata AND a.state='ARCHIVED')
 THEN RAISE EXCEPTION 'REUSED_ARCHIVE_MISMATCH'; END IF;
 UPDATE attachment.attempt SET raw_path=(SELECT raw_path FROM attachment.attempt WHERE attempt_id=previous) WHERE attempt_id=id;
 INSERT INTO attachment.archive_reuse VALUES(id,previous,clock_timestamp());
END $$;
'''
(OUT/'sql/008_processor_downloads.sql').write_text('BEGIN;\nSELECT retention.gate();\nINSERT INTO attachment.policy SELECT \'job-alio-documents-v3\',v,attachment.hash(v::text) FROM (SELECT '+literal+' v) q ON CONFLICT DO NOTHING;\n'+prepare+extra+'\nCOMMIT;\n')

def put(e,key,value):
 n=e.find(key)
 if n is None:n=E.SubElement(e,key)
 n.text=str(value);return n

def save(w,path):E.indent(w,space='  ');E.ElementTree(w).write(path,encoding='UTF-8',xml_declaration=True)
# Preserve the original native download body/signature/hash checks, omit Tika.
w=E.parse(OUT/'process_file.hpl').getroot();put(w.find('info'),'name','download_file')
remove={'Parse eligibility','Document body','Parse document with Tika','Recorded download outcome','Recheck parser input','Store document sections'}
for node in list(w.findall('transform')):
 if node.findtext('name') in remove:w.remove(node)
for hop in list(w.findall('order/hop')):
 if hop.findtext('from') in remove or hop.findtext('to') in remove:w.find('order').remove(hop)
sql=w.find("transform[name='Reserved file']/sql")
sql.text="""SELECT coalesce(old.raw_path,a.raw_path) AS raw_filename,d.request_url,d.extension,old.raw_path AS reused_filename,old.attempt_id AS previous_attempt_id
FROM attachment.attempt a JOIN attachment.document d USING(document_id)
LEFT JOIN LATERAL (SELECT oa.* FROM attachment.attempt oa JOIN attachment.document od USING(document_id)
 WHERE od.metadata=d.metadata AND od.request_url=d.request_url AND oa.attempt_id<>a.attempt_id
 AND oa.http_status=200 AND oa.raw_hash IS NOT NULL AND oa.state IN ('ARCHIVED_ONLY','PARSED','PARSE_ERROR','NO_TEXT','NEEDS_REVIEW')
 ORDER BY oa.finished_at DESC LIMIT 1) old ON true WHERE a.attempt_id=? AND a.state='RESERVED'"""
node=w.find("transform[name='Validate received body']/sql");node.text=node.text.replace('attachment.body_issue(?::integer,?::bytea,?)',"attachment.body_issue(?::integer,?::bytea,CASE ? WHEN 'doc' THEN 'hwp' WHEN 'docx' THEN 'hwpx' WHEN 'zip' THEN 'hwpx' ELSE ? END)")
parameters=w.find("transform[name='Validate received body']/parameter");parameters.append(copy.deepcopy(parameters.findall('field')[-1]))
# Add a cache branch using the same native Calculator + archive verification path.
ns=runpy.run_path(str(OUT/'tools/processor_workflows.py'));new=ns['node'];child=ns['child'];db=ns['db'];filt=ns['filt'];execute=ns['execute']
cache=db('Reuse decision',"SELECT ? IS NOT NULL AS reuse_archive",[('reused_filename','String')]);choice=filt('Archived bytes available','reuse_archive','Boolean','Y','Read archived original','Space document requests')
read=new('Calculator','Read archived original',failIfNoFile='Y');child(read,'calculation',dict(field_name='response_bytes',calc_type='LOAD_FILE_CONTENT_BINARY',field_a='reused_filename',value_type='Binary',value_length=-1,value_precision=-1,remove='N'))
meta=db('Cached response provenance',"SELECT 200::bigint AS http_status,jsonb_build_object('archive_reuse',?::text)::text AS response_headers",[('previous_attempt_id','String')])
skip=filt('Existing archive needs no copy','reuse_archive','Boolean','Y','Release received bytes','Archive original response')
record=execute('Record archive reuse','SELECT attachment.record_reuse(?,?)',['attempt_id','previous_attempt_id'])
for i,node in enumerate([cache,choice,read,meta,skip,record]):
 child(node,'GUI',dict(xloc=80+i*240,yloc=650));put(node,'copies',1);put(node,'distribute','Y');w.append(node)
for hop in list(w.findall('order/hop')):
 if (hop.findtext('from'),hop.findtext('to')) in [('Reserved file','Space document requests'),('Validate received body','Archive original response')]:w.find('order').remove(hop)
for a,b in [('Reserved file','Reuse decision'),('Reuse decision','Archived bytes available'),('Archived bytes available','Read archived original'),('Archived bytes available','Space document requests'),('Read archived original','Cached response provenance'),('Cached response provenance','Validate received body'),('Register response','Record archive reuse'),('Validate received body','Existing archive needs no copy'),('Existing archive needs no copy','Release received bytes'),('Existing archive needs no copy','Archive original response')]:child(w.find('order'),'hop',{'from':a,'to':b,'enabled':'Y'})
save(w,OUT/'download_file.hpl')
w=E.parse(OUT/'prepare.hpl').getroot();put(w.find('info'),'name','prepare_downloads');n=w.find("transform[name='Pin source documents']/sql");n.text=n.text.replace('attachment.prepare(','attachment.prepare_downloads(');save(w,OUT/'prepare_downloads.hpl')
w=E.parse(OUT/'run_batch.hpl').getroot();put(w.find('info'),'name','download_batch');n=w.find("transform[type='PipelineExecutor']/filename");n.text=n.text.replace('process_file.hpl','download_file.hpl');n=w.find("transform[name='Record child outcome']/sql");n.text=n.text.replace('attachment.finish_attempt(','attachment.finish_download(');save(w,OUT/'download_batch.hpl')
w=E.parse(OUT/'process_snapshot.hwf').getroot();put(w,'name','Archive JOB-ALIO notices and JDs for document-processor')
for node in w.findall('actions/action/filename'):
 node.text=node.text.replace('/prepare.hpl','/prepare_downloads.hpl').replace('/run_batch.hpl','/download_batch.hpl')
save(w,OUT/'download_snapshot.hwf')
w=E.parse(OUT/'install_processor.hwf').getroot();put(w,'name','Install archive-only document fetching');
for a in list(w.findall('actions/action')):
 if a.findtext('name')=='Install per-posting input verification':w.find('actions').remove(a)
for h in list(w.findall('hops/hop')):
 if h.findtext('from')=='Install per-posting input verification':w.find('hops').remove(h)
 elif h.findtext('to')=='Install per-posting input verification':put(h,'to','Success')
n=w.find("actions/action[type='SQL']/sqlfilename");n.text=n.text.replace('007_document_processor.sql','008_processor_downloads.sql');save(w,OUT/'install_downloads.hwf')
