"""Generate native attachment workflows. Development only; runtime is Hop + SQL."""
from pathlib import Path
import ast,copy,json,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/attachments'
s=(ROOT/'hop/llm/tools/build.py').read_text()
templates={}
for path in (ROOT/'hop/ingestions').rglob('*.hpl'):
 for t in E.parse(path).findall('transform'):templates.setdefault(t.findtext('type'),t)
for d in ast.parse(s).body:
 if isinstance(d,(ast.FunctionDef,ast.ClassDef)) and d.name in {'put','child','node','Pipe','save','variables','db','execute','filt','abort','remove','log','executor','workflow'}:
  code=ast.get_source_segment(s,d).replace("'llm-local'","'attachment-local'").replace('/llm/','/attachments/').replace('LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.','Attachment workflow failed. Inspect attachment.report and attachment.attempt.')
  exec(compile(code,str(OUT/'tools/build.py'),'exec'),globals())

def hash_file(name,field,out):
 n=node('Calculator',name,failIfNoFile='Y');child(n,'calculation',dict(field_name=out,calc_type='SHA256',field_a=field,value_type='String',value_length=-1,value_precision=-1,remove='N'));return n

def remember(field,var):
 n=node('SetVariable','Remember attachment batch',use_formatting='Y');child(E.SubElement(n,'fields'),'field',dict(field_name=field,variable_name=var,variable_type='PARENT_WORKFLOW',default_value=''));return n

params=[('BATCH_ID','','Blank creates a new batch; exact same ID resumes its frozen plan.'),('JOB_RUN_ID','','Exact READY FULL JOB-ALIO run.'),('POSTING_IDS','','Optional numeric IDs separated by |; blank selects every posting.'),('RAW_ROOT','${PROJECT_HOME}/data/attachments','Absolute managed raw directory; original names never become paths.'),('MAX_FILES','20','Fail planning if eligible files exceed this count. No silent LIMIT.'),('EXECUTE_DOWNLOADS','N','Y downloads and parses. N plans only; no HTTP calls.')]
p=Pipe('prepare','Freeze attachment metadata for the selected postings.')
fields=[(k.lower(),'${'+k+'}','String') for k in ['BATCH_ID','JOB_RUN_ID','POSTING_IDS','RAW_ROOT','MAX_FILES']]
p.chain(variables('Attachment plan',fields),db('Pin source documents','SELECT attachment.prepare(?,?,?,?,?::integer) AS planned_batch_id',[(n,t) for n,_,t in fields]),remember('planned_batch_id','ATTACHMENT_BATCH_ID'),log('Plan saved',['planned_batch_id'],'Attachment metadata pinned; download execution is a separate choice.'));p.save()
p=Pipe('process_file','Download, archive and parse exactly one reserved attachment.',{'ATTEMPT_ID':''})
f=p.chain(variables('Reserved attempt',[('attempt_id','${ATTEMPT_ID}','String')]),db('Reserved file',"SELECT a.raw_path AS raw_filename,d.request_url,d.extension FROM attachment.attempt a JOIN attachment.document d USING(document_id) WHERE a.attempt_id=? AND a.state='RESERVED'",[('attempt_id','String')]))
r=copy.deepcopy(templates['Rest'])
for k,v in dict(name='Download official attachment',url='',urlInField='Y',urlField='request_url',method='GET',retryTimes=0,paginationEnabled='N',streamingEnabled='N',readTimeout=60000,connectionTimeout=10000).items():put(r,k,v)
for k in ('parameters','headers','matrixParameters'):r.find(k).clear()
r.find('result').clear()
for k,v in {'name':'response_bytes','code':'http_status','binary':'Y','response_header':'response_headers'}.items():put(r.find('result'),k,v)
f=p.chain(f,node('Delay','Space document requests',timeout=200,scaletime='milliseconds',scaletime_from_field='N'),r,db('Validate received body',"SELECT encode(sha256(?::bytea),'hex') AS received_hash,octet_length(?::bytea)::bigint AS received_size,attachment.body_issue(?::integer,?::bytea,?) AS body_issue",[('response_bytes','Binary'),('response_bytes','Binary'),('http_status','Integer'),('response_bytes','Binary'),('extension','String')]),node('BinaryFileOutput','Archive original response',binaryfield='response_bytes',filenamefield='raw_filename',createparentfolder='Y',overwritefile='N',addresultfilenames='N'),remove('Release received bytes',['response_bytes']),hash_file('Verify saved bytes','raw_filename','saved_hash'),db('Archive only identical bytes',"SELECT CASE WHEN lower(?)=? THEN 'Y' ELSE 'N' END AS hash_matches",[('saved_hash','String'),('received_hash','String')]),filt('Archive hash matches','hash_matches','String','Y','Register response','Archive mismatch'),execute('Register response','SELECT attachment.archive(?,?::integer,?,?,?::bigint,?)',['attempt_id','http_status','response_headers','received_hash','received_size','body_issue']),db('Parse eligibility',"SELECT state='ARCHIVED' AS can_parse FROM attachment.attempt WHERE attempt_id=?",[('attempt_id','String')]),filt('Document body','can_parse','Boolean','Y','Parse document with Tika','Recorded download outcome'),node('Tika','Parse document with Tika',**{'file-in-field':'Y','dynamic-filename-field':'raw_filename','output-format':'Xml','encoding':'UTF-8','content-field':'document_xml','metadata-field':'document_metadata','row-limit':0,'ignore-empty-file':'N','add-result-file':'N'}),hash_file('Recheck parser input','raw_filename','parsed_input_hash'),execute('Store document sections','SELECT attachment.save_parse(?,?,?,?)',['attempt_id','document_xml','document_metadata','parsed_input_hash']))
p.add(abort('Archive mismatch','Received bytes do not match the saved attachment.'));p.edges.append(('Archive hash matches','Archive mismatch'))
p.add(node('Dummy','Recorded download outcome'));p.edges.append(('Document body','Recorded download outcome'));p.save()
p=Pipe('run_batch','Process pending attachments sequentially; pair each child result with its input ordinal.')
f=p.chain(variables('Execution choice',[('batch_id','${ATTACHMENT_BATCH_ID}','String'),('execute_downloads','${EXECUTE_DOWNLOADS}','String')]),filt('Downloads enabled','execute_downloads','String','Y','Pending documents','Plan only'),db('Pending documents',"SELECT d.document_id,row_number() OVER(ORDER BY d.posting_id,d.file_ordinal) AS request_no FROM attachment.document d WHERE d.batch_id=? AND d.disposition='PLANNED' AND NOT EXISTS(SELECT 1 FROM attachment.attempt a WHERE a.document_id=d.document_id) ORDER BY d.posting_id,d.file_ordinal",[('batch_id','String')]),db('Reserve one attempt','SELECT attachment.reserve(?) AS attempt_id',[('document_id','String')]))
e=executor('Fetch and parse one file','process_file.hpl',[('ATTEMPT_ID','attempt_id')],'Number child results')
put(e,'executors_output_transform','Original request rows')
p.chain(f,e,node('Sequence','Number child results',valuename='result_no',use_database='N',use_counter='Y',counter_name='',start_at=1,increment_by=1,max_value=9223372036854775807))
p.chain('Fetch and parse one file',node('Dummy','Original request rows'))
j=node('MergeJoin','Pair child with request',join_type='INNER',transform1='Original request rows',transform2='Number child results')
put(E.SubElement(j,'keys_1'),'key','request_no');put(E.SubElement(j,'keys_2'),'key','result_no')
p.chain('Original request rows',j,execute('Record child outcome','SELECT attachment.finish_attempt(?,?,?::bigint)',['attempt_id','ExecutionResult','ExecutionNrErrors']))
p.edges.append(('Number child results','Pair child with request'))
p.add(node('Dummy','Plan only'));p.edges.append(('Downloads enabled','Plan only'));p.save()
p=Pipe('finish','Report every selected posting; fail if a download batch is unfinished.')
f=p.chain(variables('Batch completion',[('batch_id','${ATTACHMENT_BATCH_ID}','String'),('execute_downloads','${EXECUTE_DOWNLOADS}','String')]),execute('Verify terminal accounting',"SELECT CASE WHEN ?='Y' THEN attachment.verify_batch(?) END",['execute_downloads','batch_id']),db('Posting coverage','SELECT * FROM attachment.report WHERE batch_id=? ORDER BY posting_id',[('batch_id','String')]),log('Attachment outcomes',['posting_id','attachment_count','pending','running','parsed','other_outcomes'],'Parsed documents still require source review before LLM claims are accepted.'));p.save()
workflow('process_snapshot.hwf','Fetch and parse JOB-ALIO attachments',params,[('Freeze attachment plan','prepare.hpl'),('Process documents','run_batch.hpl'),('Verify and report','finish.hpl')],False)
p=Pipe('inspect','Inspect attachment content and explicit failures.',{'BATCH_ID':''})
p.chain(variables('Batch',[('batch_id','${BATCH_ID}','String')]),db('Document outcomes',"SELECT d.posting_id,d.file_ordinal,d.metadata,d.disposition,d.source_url,d.request_url,a.* FROM attachment.document d LEFT JOIN attachment.attempt a USING(document_id) WHERE d.batch_id=? ORDER BY d.posting_id,d.file_ordinal",[('batch_id','String')]),node('Dummy','Preview document outcomes'));p.save()
input_params=[('JOB_RUN_ID','','Exact READY JOB snapshot.'),('ATTACHMENT_BATCH_IDS','','Completed batches separated by |, later entries take precedence per file.'),
 ('POSTING_IDS','','Numeric IDs separated by |; blank selects the complete job snapshot.'),('POSTING_LIMIT','20','Fail if selection exceeds this cap; no silent LIMIT.'),
 ('DATASET_ID','','Optional new frozen EVAL dataset ID. Blank prepares ENRICH inputs only.'),('NCS_RUN_ID','LATEST','NCS snapshot for an optional EVAL dataset.')]
p=Pipe('prepare_inputs','Freeze attachment-aware model input and optional evaluation cases. No model calls.')
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in input_params]
p.chain(variables('Input selection',fields),db('Freeze source bundles',"SELECT attachment.prepare_inputs(?,?,?,?::integer,?,?)::text AS prepared_inputs",[(k,'String') for k,_,_ in fields]),log('Input bundles prepared',['prepared_inputs'],'Use DATASET_ID with llm/evaluate.hwf, or the exact bundle IDs with llm/enrich.hwf. Select ko-v6 and REVIEW.'));p.save()
workflow('prepare_inputs.hwf','Prepare attachment-aware LLM inputs',input_params,[('Freeze input bundles','prepare_inputs.hpl')],False)
structured_params=input_params[:2]+[('HWPX_BATCH_IDS','','Completed HWPX structure batches separated by |, with identical attachment parent selection.')]+input_params[2:]
p=Pipe('prepare_structured_inputs','Freeze v2 document inputs with verified HWPX paragraphs and tables. No model calls.')
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in structured_params]
p.chain(variables('Structured input selection',fields),db('Freeze structured bundles',"SELECT attachment.prepare_structured_inputs(?,?,?,?,?::integer,?,?)::text AS prepared_inputs",[(k,'String') for k,_,_ in fields]),log('Structured inputs prepared',['prepared_inputs'],'Use these new bundle IDs or the frozen dataset; earlier v1 inputs remain unchanged.'))
p.save()
workflow('prepare_structured_inputs.hwf','Prepare structured document LLM inputs',structured_params,[('Freeze structured input bundles','prepare_structured_inputs.hpl')],False)
# HWPX document structure: all reads use native VFS/Calculator and native SQL.
def checked_child(p,previous,name,filename,args):
    ok=name+' errors';result=name+' result';done=name+' done';failed=name+' failed'
    p.chain(previous,executor(name,filename,args,ok),
      filt(ok,'ExecutionNrErrors','Integer','0',result,failed),
      filt(result,'ExecutionResult','Boolean','Y',done,failed),node('Dummy',done))
    p.add(abort(failed,'A native HWPX child failed. Its saved archive and entry ledger remain available.'))
    p.edges.extend([(ok,failed),(result,failed)])
    return done

def file_names(name,field):
    n=copy.deepcopy(templates['GetFileNames'])
    for old in list(n):
        if old.tag in ('GUI','partitioning'):n.remove(old)
    for k,v in dict(name=name,filename_Field=field,wildcard_Field='',exclude_wildcard_Field='',filefield='Y',dynamic_include_subfolders='N',isaddresult='N',limit=0,doNotFailIfNoFile='N',raiseAnExceptionIfNoFile='Y').items():put(n,k,v)
    return n

p=Pipe('read_hwpx_entry','Read one bounded archive entry without unpacking paths to the host.',{'STRUCTURE_ID':'','ENTRY_NAME':''})
p.chain(variables('Entry identity',[('structure_id','${STRUCTURE_ID}','String'),('entry_name','${ENTRY_NAME}','String')]),
 execute('Validate archive member name','SELECT attachment.hwpx_entry_limit(?,?,1)',['structure_id','entry_name']),
 db('Pinned archive URI',"SELECT 'zip:file://'||attachment.uri_path(a.raw_path)||'!/'||? AS entry_uri FROM attachment.hwpx_structure s JOIN attachment.attempt a USING(attempt_id) WHERE s.structure_id=? AND s.state='READING'",[('entry_name','String'),('structure_id','String')]),
 file_names('Inspect member size','entry_uri'),execute('Bound member size','SELECT attachment.hwpx_entry_limit(?,?,?::bigint)',['structure_id','entry_name','size']))
c=node('Calculator','Read exact member bytes',failIfNoFile='Y');child(c,'calculation',dict(field_name='entry_bytes',calc_type='LOAD_FILE_CONTENT_BINARY',field_a='entry_uri',value_type='Binary',value_length=-1,value_precision=-1,remove='N'))
p.chain('Bound member size',c,execute('Retain original XML member','SELECT attachment.save_hwpx_entry(?,?,?::bytea,?::bigint)',['structure_id','entry_name','entry_bytes','size']),remove('Release XML buffer',['entry_bytes']));p.save()
p=Pipe('process_hwpx','Read package spine and XML members, then reconstruct ordered paragraph/table evidence.',{'STRUCTURE_ID':''})
f=p.chain(variables('Structure identity',[('structure_id','${STRUCTURE_ID}','String')]),db('Original archive',"SELECT a.raw_path AS archive_filename FROM attachment.hwpx_structure s JOIN attachment.attempt a USING(attempt_id) WHERE s.structure_id=? AND s.state='READING'",[('structure_id','String')]),hash_file('Hash original archive','archive_filename','archive_hash'),execute('Confirm pinned archive','SELECT attachment.hwpx_check_hash(?,?)',['structure_id','archive_hash']),db('Package entry',"SELECT 'Contents/content.hpf'::text AS entry_name"))
f=checked_child(p,f,'Read package manifest','read_hwpx_entry.hpl',[('STRUCTURE_ID','structure_id'),('ENTRY_NAME','entry_name')])
f=p.chain(f,variables('Body identity',[('structure_id','${STRUCTURE_ID}','String')]),db('Declared document members','SELECT entry_name FROM attachment.hwpx_entries(?) ORDER BY section_no',[('structure_id','String')]))
f=checked_child(p,f,'Read document members','read_hwpx_entry.hpl',[('STRUCTURE_ID','structure_id'),('ENTRY_NAME','entry_name')])
g=node('GroupBy','Wait for all document members',all_rows='N',give_back_row='Y',ignore_aggregate='N',add_linenr='N');E.SubElement(g,'group');child(E.SubElement(g,'fields'),'field',dict(aggregate='member_count',subject='ExecutionResult',type='COUNT_ANY'))
p.chain(f,g,variables('Final structure identity',[('structure_id','${STRUCTURE_ID}','String')]),db('Recheck original archive',"SELECT a.raw_path AS archive_filename FROM attachment.hwpx_structure s JOIN attachment.attempt a USING(attempt_id) WHERE s.structure_id=? AND s.state='READING'",[('structure_id','String')]),hash_file('Verify archive after reads','archive_filename','final_archive_hash'),execute('Reconstruct document structure','SELECT attachment.build_hwpx_structure(?,?)',['structure_id','final_archive_hash']));p.save()
p=Pipe('prepare_hwpx','Freeze selected archived HWPX documents; no download requests.')
fields=[(k.lower(),'${'+k+'}','String') for k in ['BATCH_ID','JOB_RUN_ID','ATTACHMENT_BATCH_IDS','POSTING_IDS','MAX_DOCUMENTS']]
f=p.chain(variables('HWPX plan',fields),db('Freeze HWPX plan','SELECT attachment.prepare_hwpx(?,?,?,?,?::integer) AS planned_batch_id',[(k,t) for k,_,t in fields]))
r=remember('planned_batch_id','HWPX_BATCH_ID');put(r.find('fields/field'),'variable_name','HWPX_BATCH_ID')
p.chain(f,r,log('HWPX plan saved',['planned_batch_id'],'Archived bytes are reused; original parser results remain intact.'));p.save()
p=Pipe('run_hwpx','Reconstruct selected HWPX files sequentially and account for each child.')
f=p.chain(variables('HWPX batch',[('batch_id','${HWPX_BATCH_ID}','String')]),db('Pending HWPX structures','SELECT structure_id,row_number() OVER(ORDER BY structure_id) AS request_no FROM attachment.hwpx_structure WHERE batch_id=? AND state=\'PLANNED\' ORDER BY structure_id',[('batch_id','String')]),execute('Reserve structure','SELECT attachment.reserve_hwpx(?)',['structure_id']))
e=executor('Reconstruct one HWPX','process_hwpx.hpl',[('STRUCTURE_ID','structure_id')],'Number structure results');put(e,'executors_output_transform','Original structure rows')
p.chain(f,e,node('Sequence','Number structure results',valuename='result_no',use_database='N',use_counter='Y',counter_name='',start_at=1,increment_by=1,max_value=9223372036854775807))
p.chain('Reconstruct one HWPX',node('Dummy','Original structure rows'))
j=node('MergeJoin','Pair structure result',join_type='INNER',transform1='Original structure rows',transform2='Number structure results');put(E.SubElement(j,'keys_1'),'key','request_no');put(E.SubElement(j,'keys_2'),'key','result_no')
p.chain('Original structure rows',j,execute('Finalize structure outcome','SELECT attachment.finish_hwpx(?,?,?::bigint)',['structure_id','ExecutionResult','ExecutionNrErrors']));p.edges.append(('Number structure results','Pair structure result'));p.save()
p=Pipe('finish_hwpx','Verify complete structure accounting and report outcomes.')
p.chain(variables('HWPX completion',[('batch_id','${HWPX_BATCH_ID}','String')]),execute('Verify HWPX terminal states','SELECT attachment.verify_hwpx_batch(?)',['batch_id']),db('HWPX outcomes','SELECT state,count(*) AS documents FROM attachment.hwpx_structure WHERE batch_id=? GROUP BY state ORDER BY state',[('batch_id','String')]),log('HWPX structures',['state','documents'],'Verified structure retains original text order and table relationships; semantic review remains separate.'));p.save()
workflow('structure_hwpx.hwf','Reconstruct HWPX paragraphs and tables',[
 ('BATCH_ID','','New ID for a new structure batch; same ID replays without reading completed files.'),('JOB_RUN_ID','','Exact pinned job snapshot.'),('ATTACHMENT_BATCH_IDS','','Completed attachment batch IDs separated by |; later entries take precedence.'),('POSTING_IDS','','Optional numeric IDs separated by |; blank selects the full snapshot.'),('MAX_DOCUMENTS','20','Fail if selected archived HWPX documents exceed this cap.')],
 [('Freeze HWPX plan','prepare_hwpx.hpl'),('Reconstruct archived documents','run_hwpx.hpl'),('Verify structure outcomes','finish_hwpx.hpl')],False)

policy=(OUT/'policy.json').read_text();literal="'"+policy.replace("'","''")+"'::jsonb"
(OUT/'sql/002_policy.sql').write_text("BEGIN;\nINSERT INTO attachment.policy SELECT 'job-alio-attachments-v1',v,attachment.hash(v::text) FROM (SELECT "+literal+" v) i ON CONFLICT DO NOTHING;\nDO $$ BEGIN IF (SELECT contract FROM attachment.policy WHERE policy_id='job-alio-attachments-v1') IS DISTINCT FROM "+literal+" THEN RAISE EXCEPTION 'ATTACHMENT_POLICY_IS_IMMUTABLE'; END IF; END $$;\nCOMMIT;\n")
ret=(ROOT/'hop/retention/sql/001_retention.sql').read_text();start=ret.index('CREATE OR REPLACE FUNCTION retention.protection(');end=ret.index('END $$;',start)+len('END $$;')
(OUT/'sql/003_retention.sql').write_text('BEGIN;\nSELECT retention.gate();\n'+ret[start:end]+'\nCOMMIT;\n')
workflow('install.hwf','Install attachment provenance',[],[],False)
w=E.parse(OUT/'install.hwf').getroot();actions=w.find('actions');hops=w.find('hops');hops.clear();previous='Start'
for i,path in enumerate(sorted((OUT/'sql').glob('*.sql')),1):
 name=path.stem
 child(actions,'action',dict(name=name,type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/attachments/sql/'+path.name,sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=80+i*240,yloc=240,draw='Y',parallel='N'))
 child(hops,'hop',{'from':previous,'to':name,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
 child(hops,'hop',{'from':name,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'});previous=name
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'});save(w,OUT/'install.hwf')
for kind in ['pipeline','workflow']:
 src=ROOT/f'hop/metadata/{kind}-run-configuration/llm-local.json';conf=json.loads(src.read_text());conf.update(name='attachment-local',description='Native attachment processing. No execution-data sampling.')
 (src.parent/'attachment-local.json').write_text(json.dumps(conf,indent=2)+'\n')
print('Generated native attachment workflows.')
