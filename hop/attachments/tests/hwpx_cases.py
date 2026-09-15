"""Native archive success/failure isolation, layout and replay fixtures."""
import json,uuid,zipfile,hashlib
from checks import sql,q,js,bad
from hwpx_oracle import verify
HP='http://www.hancom.co.kr/hwpml/2011/paragraph';HS='http://www.hancom.co.kr/hwpml/2011/section';OPF='http://www.idpf.org/2007/opf/'

def check_cases(run_native,cmd,work,remote,hop):
 name='hwpx-cases-'+uuid.uuid4().hex[:10];jobs=name+'-source'
 p=lambda text:f'<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
 def cell(text,span=1):return f'<hp:tc header="1"><hp:subList>{text}</hp:subList><hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="{span}"/></hp:tc>'
 inner='<hp:tbl rowCnt="1" colCnt="1"><hp:tr>'+cell(p('내부 표'))+'</hp:tr></hp:tbl>'
 outer='<hp:tbl rowCnt="1" colCnt="2"><hp:tr>'+cell('<hp:p><hp:run><hp:t>표 앞</hp:t>'+inner+'<hp:t>표 뒤</hp:t></hp:run></hp:p>',2)+'</hp:tr></hp:tbl>'
 body='<hp:p><hp:run><hp:t>의사면허증 </hp:t></hp:run><hp:run><hp:t>및 전문의 자격증 😀 e&#x301;<hp:lineBreak/>줄< hp:tab/></hp:t></hp:run></hp:p>'.replace('< hp:','<hp:')
 body+=p('전< hp:fwSpace/>후< hp:nbSpace/>공백'.replace('< hp:','<hp:'))
 body+='<hp:p><hp:run><hp:t>본문 앞</hp:t>'+outer+'<hp:t>본문 뒤</hp:t></hp:run></hp:p>'
 body+='<hp:p><hp:run><hp:footNote>'+p('각주 조건')+'</hp:footNote><hp:header>'+p('머리말')+'</hp:header></hp:run></hp:p>'+p('   ')
 section=lambda b:f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}" xmlns:other="urn:other">{b}</hs:sec>'
 items='<opf:item id="header" href="Contents/header.xml"/><opf:item id="s2" href="Contents/section2.xml"/><opf:item id="s0" href="Contents/section0.xml"/>'
 spine='<opf:itemref idref="header"/><opf:itemref idref="s2"/><opf:itemref idref="s0"/>'
 manifest=lambda i=items,s=spine:f'<opf:package xmlns:opf="{OPF}"><opf:manifest>{i}</opf:manifest><opf:spine>{s}</opf:spine></opf:package>'
 base={'Contents/content.hpf':manifest(),'Contents/header.xml':'<header/>','Contents/section2.xml':section(body),'Contents/section0.xml':section(p('마지막 절'))}
 cases={
  'nested':(base,'VERIFIED',None),
  'foreign_control':(base|{'Contents/section0.xml':section(p('앞<other:lineBreak/>뒤'))},'REVIEW_REQUIRED','unrendered_text_controls'),
  'bad_geometry':(base|{'Contents/section2.xml':section(body.replace('colSpan="2"','colSpan="3"'))},'REVIEW_REQUIRED','invalid_table_geometry'),
  'unknown_spine':(base|{'Contents/content.hpf':manifest(s=spine+'<opf:itemref idref="missing"/>')},'FAILED','INVALID_HWPX_SPINE'),
  'duplicate_spine':(base|{'Contents/content.hpf':manifest(s=spine+'<opf:itemref idref="s0"/>')},'FAILED','INVALID_HWPX_SPINE'),
  'omitted_section':(base|{'Contents/content.hpf':manifest(s=spine.replace('<opf:itemref idref="s0"/>',''))},'FAILED','HWPX_SPINE_COVERAGE_MISMATCH'),
  'traversal':(base|{'Contents/content.hpf':manifest(i=items.replace('Contents/section0.xml','../../outside.xml'))},'FAILED','INVALID_HWPX_SPINE'),
  'duplicate_id':(base|{'Contents/content.hpf':manifest(i=items+ '<opf:item id="s0" href="Contents/section9.xml"/>')},'FAILED','INVALID_OR_DUPLICATE_HWPX_MANIFEST_ID'),
  'missing_member':({k:v for k,v in base.items() if k!='Contents/section0.xml'},'FAILED',None),
  'entity':(base|{'Contents/section0.xml':'<!DOCTYPE hs:sec [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+section(p('&x;'))},'FAILED','HWPX_XML_DECLARATION_NOT_ALLOWED'),
  'wrong_hash':(base,'FAILED','HWPX_ARCHIVE_CHANGED'),
  'final_valid':(base,'VERIFIED',None),
 }
 with zipfile.ZipFile('/tmp/jobtology-attachments/parsed-data/3073720.hwpx') as z:
  cases['real_notice']=({n:z.read(n) for n in z.namelist() if not n.endswith('/')},'VERIFIED',None)
 files=[];posting_cases={}
 for number,(label,(members,state,issue)) in enumerate(cases.items(),200):
  archive=work/(label+'.hwpx')
  with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
   for path,text in members.items():z.writestr(path,text)
  meta=dict(recrutAtchFileNo=number,atchFileNm=label+'.hwpx',atchFileType='A',url='https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='+str(number))
  files.append(meta);posting_cases[str(number)]=(label,archive,state,issue)
 sql(f"INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES({q(jobs)},'job_alio','FULL','fixture','READY');INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES({q(jobs)},'all','FILE',1);INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES({q(jobs)},'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,now(),true)")
 for meta in files:
  posting=str(meta['recrutAtchFileNo'])
  for rep in ['list','detail']:
   n=dict(posting_id=posting,representation=rep,title='시험 공고',organization_name='시험기관')
   sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(jobs)},'doc',{q(posting+rep)},{q(posting+':'+rep)},{js(dict(files=[meta]))},{js(n)})")
 rawroot=remote+'/raw';cmd(['docker','exec',hop,'mkdir','-p',rawroot])
 sql(f"SELECT attachment.prepare({q(name)},{q(jobs)},'',{q(rawroot)},20)")
 for posting,(label,archive,_,_) in posting_cases.items():
  doc=sql(f"SELECT document_id FROM attachment.document WHERE batch_id={q(name)} AND posting_id={q(posting)}")
  aid=sql(f'SELECT attachment.reserve({q(doc)})');path=sql(f'SELECT raw_path FROM attachment.attempt WHERE attempt_id={q(aid)}')
  cmd(['docker','cp',str(archive),hop+':'+path]);raw=archive.read_bytes();digest=hashlib.sha256(raw).hexdigest()
  if label=='wrong_hash':digest='0'*64
  sql(f"SELECT attachment.archive({q(aid)},200,NULL,{q(digest)},{len(raw)},NULL);SELECT attachment.finish_attempt({q(aid)},false,1)")
 sql(f'SELECT attachment.verify_batch({q(name)})')
 params=dict(BATCH_ID=name,JOB_RUN_ID=jobs,ATTACHMENT_BATCH_IDS=name,POSTING_IDS='',MAX_DOCUMENTS=20)
 run_native('structure_hwpx.hwf',params,'synthetic-hwpx-structures')
 result=json.loads(sql(f"SELECT jsonb_agg(to_jsonb(s)||jsonb_build_object('posting_id',d.posting_id) ORDER BY d.posting_id) FROM attachment.hwpx_structure s JOIN attachment.attempt a USING(attempt_id) JOIN attachment.document d USING(document_id) WHERE s.batch_id={q(name)}"))
 report=[];log=(work/'synthetic-hwpx-structures.log').read_text()
 for row in result:
  label,archive,state,issue=posting_cases[row['posting_id']];assert row['state']==state,(label,row)
  if state!='FAILED':
   checked=verify(row,archive)
   if state=='VERIFIED' and label!='real_notice':assert row['body_text'].endswith('마지막 절') and checked['counts']['tables']==2
   if issue:assert issue in [x['kind'] for x in row['issues']],row
  elif issue:assert issue in log,(label,issue)
  assert sql(f"SELECT count(*) FROM retention.writer WHERE writer_id={q(row['structure_id'])}")=='0'
  bad(f"UPDATE attachment.hwpx_structure SET body_text='changed' WHERE structure_id={q(row['structure_id'])}",'HWPX_STRUCTURE_IS_IMMUTABLE')
  report.append(dict(case=label,state=state,structure_id=row['structure_id'],posting_id=row['posting_id'],archive=str(archive)))
 before=sql(f"SELECT attachment.hash(jsonb_agg(s ORDER BY structure_id)::text) FROM attachment.hwpx_structure s WHERE batch_id={q(name)}")
 run_native('structure_hwpx.hwf',params,'synthetic-hwpx-replay')
 assert before==sql(f"SELECT attachment.hash(jsonb_agg(s ORDER BY structure_id)::text) FROM attachment.hwpx_structure s WHERE batch_id={q(name)}")
 assert 'Execution started for pipeline [process_hwpx]' not in (work/'synthetic-hwpx-replay.log').read_text()
 bad(f"SELECT attachment.prepare_hwpx({q(name)},{q(jobs)},{q(name)},'200',20)",'HWPX_BATCH_IS_IMMUTABLE')
 bad(f"SELECT attachment.prepare_hwpx({q(name+'-cap')},{q(jobs)},{q(name)},'',2)",'HWPX_CAP_EXCEEDED')
 for path,size in [('Contents/../secret',1),('Contents/section0.xml',16777217),('Contents/section0.xml',0)]:
  bad(f"SELECT attachment.hwpx_entry_limit('fixture',{q(path)},{size})",'HWPX_ENTRY_OUTSIDE_LIMIT')
 assert len(result)==len(cases)
 return dict(batch_id=name,job_run_id=jobs,cases=report)
