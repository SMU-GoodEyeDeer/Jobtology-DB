"""Native selection + conditional execution using existing enrichment stages."""
from pathlib import Path
import ast,xml.etree.ElementTree as E,copy
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/llm'
source=(OUT/'tools/build.py').read_text()
for d in ast.parse(source).body:
 if isinstance(d,(ast.FunctionDef,ast.ClassDef)) and d.name in {'put','child','node','Pipe','save','variables','db','execute','log','workflow'}:exec(compile(ast.get_source_segment(source,d),__file__,'exec'),globals())
p=Pipe('select_changed_postings','Select pending current document inputs; successful unchanged outputs are skipped.')
p.chain(variables('Selection options',[('cap','${POSTING_LIMIT}','String'),('retry_failed','${RETRY_FAILED}','String')]),db('Choose changed inputs',"SELECT x->>'job_run_id' AS job_run_id,x->>'ncs_run_id' AS ncs_run_id,x->>'posting_ids' AS posting_ids,x->>'bundle_ids' AS bundle_ids,x->>'run_needed' AS run_needed,x->>'selected' AS selected,x->>'pending_or_failed_total' AS pending_total FROM (SELECT enrichment.changed_linking_inputs(?::integer,?='Y') x) q",[('cap','String'),('retry_failed','String')]))
v=node('SetVariable','Remember changed inputs',use_formatting='Y');fs=E.SubElement(v,'fields')
for field,var in [('job_run_id','CHANGED_JOB_RUN_ID'),('ncs_run_id','CHANGED_NCS_RUN_ID'),('posting_ids','CHANGED_POSTING_IDS'),('bundle_ids','CHANGED_BUNDLE_IDS'),('run_needed','CHANGED_RUN_NEEDED')]:child(fs,'field',dict(field_name=field,variable_name=var,variable_type='PARENT_WORKFLOW',default_value=''))
p.chain('Choose changed inputs',v,log('Selection result',['selected','pending_total'],'Pending inputs require document preparation; failed extractions retry only with RETRY_FAILED=Y.'));p.save()
w=E.parse(OUT/'start_batch.hpl').getroot();put(w.find('info'),'name','start_changed_batch')
for field in w.findall("transform[name='Workflow options']/fields/field"):
 key=field.findtext('name')
 if key in ['job_run_id','ncs_run_id','posting_ids','input_bundle_ids']:put(field,'variable','${'+{'job_run_id':'CHANGED_JOB_RUN_ID','ncs_run_id':'CHANGED_NCS_RUN_ID','posting_ids':'CHANGED_POSTING_IDS','input_bundle_ids':'CHANGED_BUNDLE_IDS'}[key]+'}')
 if key=='run_mode':put(field,'variable','ENRICH')
 if key in ['dataset_id','repair_batch_id']:put(field,'variable','')
save(w,OUT/'start_changed_batch.hpl')
w=E.parse(OUT/'enrich.hwf').getroot();put(w,'name','Enrich new or changed postings for NCS linking')
for p in list(w.findall('parameters/parameter')):
 name=p.findtext('name')
 if name in ['POSTING_IDS','INPUT_BUNDLE_IDS','REPAIR_BATCH_ID','JOB_RUN_ID','NCS_RUN_ID','DATASET_ID','RUN_MODE']:w.find('parameters').remove(p)
 elif name=='PROMPT_VERSION':put(p,'default_value','ko-link-v1')
 elif name in ['EXTRACT_MODEL','CATEGORIZE_MODEL']:put(p,'default_value','openai/gpt-5.6-luna')
 elif name=='MAX_INPUT_CHARS':put(p,'default_value','200000')
 elif name=='MAX_COST_USD':put(p,'default_value','1')
 elif name=='DAILY_BUDGET_USD':put(p,'default_value','1')
child(w.find('parameters'),'parameter',dict(name='RETRY_FAILED',default_value='N',description='Y explicitly retries failed extraction inputs; N processes new/changed inputs only.'))
for n in w.findall('actions/action/filename'):
 if n.text.endswith('/start_batch.hpl'):n.text=n.text.replace('/start_batch.hpl','/start_changed_batch.hpl')
a=copy.deepcopy(w.find("actions/action[type='PIPELINE']"));put(a,'name','Select changed inputs');put(a,'filename','${PROJECT_HOME}/llm/select_changed_postings.hpl');w.find('actions').append(a)
child(w.find('actions'),'action',dict(name='Changes need processing',type='SIMPLE_EVAL',valuetype='variable',fieldtype='string',variablename='${CHANGED_RUN_NEEDED}',comparevalue='Y',successcondition='equal',successwhenvarset='N',xloc=320,yloc=500,draw='Y',parallel='N'))
for h in w.findall('hops/hop'):
 if h.findtext('from')=='Start':put(h,'to','Select changed inputs')
for a,b,ok in [('Select changed inputs','Changes need processing',True),('Select changed inputs','Abort',False),('Changes need processing','Freeze inputs and options',True),('Changes need processing','Success',False)]:child(w.find('hops'),'hop',{'from':a,'to':b,'enabled':'Y','evaluation':'Y' if ok else 'N','unconditional':'N'})
save(w,OUT/'enrich_changed.hwf')
w=E.parse(OUT/'install_link_publication.hwf').getroot();put(w,'name','Install incremental NCS-linking selection');w.find("actions/action[type='SQL']/sqlfilename").text='${PROJECT_HOME}/llm/sql/023_incremental_linking.sql';save(w,OUT/'install_incremental_linking.hwf')

# Each child pipeline owns its request rows; PostgreSQL serializes spend reservations.
for stage in ['extract','categorize']:
 w=E.parse(OUT/('run_'+stage+'.hpl')).getroot();put(w.find('info'),'name','run_'+stage+'_workers')
 for t in w.findall("transform[type='PipelineExecutor']"):put(t,'copies','${REQUEST_WORKERS}')
 save(w,OUT/('run_'+stage+'_workers.hpl'))
w=E.parse(OUT/'enrich_changed.hwf').getroot()
child(w.find('parameters'),'parameter',dict(name='REQUEST_WORKERS',default_value='4',description='Concurrent independent requests, 1..4. Shared SQL budgets still apply.'))
for node in w.findall('actions/action/filename'):
 node.text=node.text.replace('/run_extract.hpl','/run_extract_workers.hpl').replace('/run_categorize.hpl','/run_categorize_workers.hpl')
save(w,OUT/'enrich_changed.hwf')
w=E.parse(OUT/'select_changed_postings.hpl').getroot()
child(w.find("transform[name='Selection options']/fields"),'field',dict(name='request_workers',variable='${REQUEST_WORKERS}',type='String',length=-1,precision=-1,trim_type='none'))
n=w.find("transform[name='Choose changed inputs']/sql");n.text=n.text.replace("enrichment.changed_linking_inputs(?::integer,?='Y')", "enrichment.changed_linking_inputs(?::integer,?='Y')").replace(' x) q', ' x WHERE enrichment.valid_request_workers(?::integer)) q')
child(w.find("transform[name='Choose changed inputs']/parameter"),'field',dict(name='request_workers',type='String'))
save(w,OUT/'select_changed_postings.hpl')
