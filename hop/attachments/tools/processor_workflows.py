"""Generate additive native Hop workflows for the existing parser service."""
from pathlib import Path
import ast, copy, xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/attachments'
source=(ROOT/'hop/llm/tools/build.py').read_text();templates={}
for path in (ROOT/'hop/ingestions').rglob('*.hpl'):
 for t in E.parse(path).findall('transform'):templates.setdefault(t.findtext('type'),t)
for d in ast.parse(source).body:
 if isinstance(d,(ast.FunctionDef,ast.ClassDef)) and d.name in {'put','child','node','Pipe','save','variables','db','execute','filt','abort','remove','log','executor','workflow'}:
  code=ast.get_source_segment(source,d).replace("'llm-local'","'attachment-local'").replace('/llm/','/attachments/')
  exec(compile(code,__file__,'exec'),globals())
params=[('BATCH_ID','','Blank creates a new immutable parser batch.'),('ATTACHMENT_BATCH_IDS','','Completed attachment batches separated by |.'),('PARSER_REVISION','','Exact revision returned by the parser service.'),('MAX_DOCUMENTS','20','Fail above this cap; never silently omit files.'),('PARSER_ENDPOINT','http://jobtology-document-parser:8080/parse','Private parser service; no public endpoint.'),('EXECUTE_PARSING','N','Y calls the parser. N prepares a plan only.'),('REUSE_SUCCESS_FROM_BATCH','','Explicit repair: reuse successful text from this completed parser batch, including its original revision.')]
p=Pipe('prepare_processor','Pin existing archived bytes and the document-processor revision.')
fields=[(k.lower(),'${'+k+'}','String') for k in ['BATCH_ID','ATTACHMENT_BATCH_IDS','PARSER_REVISION','MAX_DOCUMENTS']]
v=node('SetVariable','Remember processor batch',use_formatting='Y');child(E.SubElement(v,'fields'),'field',dict(field_name='planned_batch_id',variable_name='PROCESSOR_BATCH_ID',variable_type='PARENT_WORKFLOW',default_value=''))
p.chain(variables('Parser options',fields),db('Prepare immutable plan','SELECT attachment.prepare_processor(?,?,?,?::integer) AS planned_batch_id',[(k,t) for k,_,t in fields]),v,variables('Optional repair reuse',[('reuse_batch','${REUSE_SUCCESS_FROM_BATCH}','String')]),execute('Reuse successful prior text','SELECT attachment.reuse_processor_successes(?,?)',['planned_batch_id','reuse_batch']));p.save()
p=Pipe('process_document','Read one archived file through the existing document-processor service.',{'PARSE_ID':''})
f=p.chain(variables('Parse identity',[('parse_id','${PARSE_ID}','String'),('parser_endpoint','${PARSER_ENDPOINT}','String')]),db('Reserve parser request','SELECT attachment.reserve_processor(?) AS request_json',[('parse_id','String')]))
r=copy.deepcopy(templates['Rest'])
for k,v in dict(name='Call document processor',url='',urlInField='Y',urlField='parser_endpoint',method='POST',bodyField='request_json',applicationType='JSON',retryTimes=0,paginationEnabled='N',streamingEnabled='N',readTimeout=210000,connectionTimeout=10000).items():put(r,k,v)
for k in ('parameters','headers','matrixParameters'):r.find(k).clear()
r.find('result').clear()
for k,v in dict(name='response_body',code='http_status',binary='N',response_header='response_headers').items():put(r.find('result'),k,v)
p.chain(f,r,execute('Store Markdown and structural JSON','SELECT attachment.save_processor(?,?::integer,?)',['parse_id','http_status','response_body']));p.save()
p=Pipe('run_processor','Process only pending archived documents sequentially.')
f=p.chain(variables('Execution choice',[('batch_id','${PROCESSOR_BATCH_ID}','String'),('execute_parsing','${EXECUTE_PARSING}','String')]),filt('Parsing enabled','execute_parsing','String','Y','Pending parses','Plan only'),db('Pending parses',"SELECT parse_id,row_number() OVER(ORDER BY parse_id) AS request_no FROM attachment.processor_document WHERE batch_id=? AND state='PLANNED' ORDER BY parse_id",[('batch_id','String')]))
e=executor('Parse one archive','process_document.hpl',[('PARSE_ID','parse_id')],'Number parser results');put(e,'executors_output_transform','Original requests')
p.chain(f,e,node('Sequence','Number parser results',valuename='result_no',use_database='N',use_counter='Y',counter_name='',start_at=1,increment_by=1,max_value=9223372036854775807))
p.chain('Parse one archive',node('Dummy','Original requests'))
j=node('MergeJoin','Pair parser result',join_type='INNER',transform1='Original requests',transform2='Number parser results');put(E.SubElement(j,'keys_1'),'key','request_no');put(E.SubElement(j,'keys_2'),'key','result_no')
p.chain('Original requests',j,execute('Finalize parser outcome','SELECT attachment.finish_processor(?)',['parse_id']));p.edges.append(('Number parser results','Pair parser result'))
p.add(node('Dummy','Plan only'));p.edges.append(('Parsing enabled','Plan only'));p.save()
p=Pipe('finish_processor','Verify terminal parser outcomes and report failures explicitly.')
p.chain(variables('Batch',[('batch_id','${PROCESSOR_BATCH_ID}','String'),('execute_parsing','${EXECUTE_PARSING}','String')]),execute('Verify terminal state',"SELECT CASE WHEN ?='Y' THEN attachment.verify_processor(?) END",['execute_parsing','batch_id']),db('Parser outcomes','SELECT state,issue,count(*) AS documents FROM attachment.processor_document WHERE batch_id=? GROUP BY state,issue ORDER BY state,issue',[('batch_id','String')]),log('Parser summary',['state','issue','documents'],'Original files and earlier parser outputs remain available.'));p.save()
workflow('parse_documents.hwf','Parse archived attachments with document-processor',params,[('Freeze parser selection','prepare_processor.hpl'),('Parse original documents','run_processor.hpl'),('Verify parser outcomes','finish_processor.hpl')],False)
params=[('JOB_RUN_ID','','Exact job snapshot.'),('PROCESSOR_BATCH_ID','','Completed parser batch.'),('POSTING_IDS','','Numeric IDs separated by |; blank includes the whole snapshot.'),('POSTING_LIMIT','20','Fail if selection exceeds the cap.'),('DATASET_ID','','Optional frozen EVAL dataset; blank prepares ENRICH bundles.'),('NCS_RUN_ID','LATEST','NCS snapshot for EVAL.')]
p=Pipe('prepare_processor_inputs','Create frozen Markdown inputs with document and block provenance.')
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in params]
p.chain(variables('Input options',fields),db('Prepare parser-backed inputs','SELECT attachment.prepare_processor_inputs(?,?,?,?::integer,?,?)::text AS inputs',[(k,t) for k,_,t in fields]),log('Prepared input IDs',['inputs'],'Use the exact bundle IDs with enrichment or the frozen dataset with evaluation.'));p.save()
workflow('prepare_processor_inputs.hwf','Prepare document-processor LLM inputs',params,[('Freeze source bundles','prepare_processor_inputs.hpl')],False)
workflow('install_processor.hwf','Install document-processor input integration',[],[],False)
w=E.parse(OUT/'install_processor.hwf').getroot();actions=w.find('actions');hops=w.find('hops');hops.clear()
child(actions,'action',dict(name='Install parser ledger',type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/attachments/sql/007_document_processor.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=320,yloc=80,draw='Y',parallel='N'))
for a,b,success in [('Start','Install parser ledger',True),('Install parser ledger','Success',True),('Install parser ledger','Abort',False)]:child(hops,'hop',{'from':a,'to':b,'enabled':'Y','evaluation':'Y' if success else 'N','unconditional':'Y' if a=='Start' else 'N'})
save(w,OUT/'install_processor.hwf')

w=E.parse(OUT/'install_processor.hwf').getroot()
child(w.find('actions'),'action',dict(name='Install per-posting input verification',type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/attachments/sql/009_processor_inputs.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=560,yloc=80,draw='Y',parallel='N'))
for h in w.findall('hops/hop'):
 if h.findtext('from')=='Install parser ledger' and h.findtext('to')=='Success':put(h,'to','Install per-posting input verification')
for to,ok in [('Success','Y'),('Abort','N')]:child(w.find('hops'),'hop',{'from':'Install per-posting input verification','to':to,'enabled':'Y','evaluation':ok,'unconditional':'N'})
save(w,OUT/'install_processor.hwf')
