"""Regenerate checked-in Hop XML and prompt bootstrap. Development only; no ETL runs here."""
from pathlib import Path
import copy
import hashlib
import json
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'hop/llm'
templates = {}
for path in sorted((ROOT / 'hop').rglob('*.hpl')):
    if OUT in path.parents:
        continue
    for t in E.parse(path).findall('transform'):
        templates.setdefault(t.findtext('type'), t)

def put(e, key, value):
    n = e.find(key)
    if n is None:
        n = E.SubElement(e, key)
    n.text = str(value)
    return n

def child(e, key, values):
    n = E.SubElement(e, key)
    for k, v in values.items():
        put(n, k, v)
    return n

def node(kind, name, **attrs):
    n = E.Element('transform')
    put(n, 'type', kind)
    put(n, 'name', name)
    for k, v in attrs.items():
        put(n, k, v)
    return n

class Pipe:
    def __init__(self, name, description, params=None):
        self.name, self.nodes, self.edges, self.errors = name, [], [], []
        self.root = E.Element('pipeline')
        info = child(self.root, 'info', dict(name=name, description=description, pipeline_type='Normal', size_rowset=100))
        ps = E.SubElement(info, 'parameters')
        for k, v in (params or {}).items():
            child(ps, 'parameter', dict(name=k, default_value=v, description=k))
        E.SubElement(self.root, 'notepads')
        self.order = E.SubElement(self.root, 'order')

    def add(self, n):
        i = len(self.nodes)
        put(n, 'copies', '1'); put(n, 'distribute', 'Y')
        child(n, 'GUI', dict(xloc=80 + (i % 5) * 240, yloc=80 + (i // 5) * 160))
        child(n, 'partitioning', dict(method='none', schema_name=''))
        self.nodes.append(n)
        return n.findtext('name')

    def chain(self, *nodes):
        names = [self.add(n) if isinstance(n, E.Element) else n for n in nodes]
        self.edges.extend(zip(names, names[1:]))
        return names[-1]

    def save(self):
        assert len({n.findtext('name') for n in self.nodes}) == len(self.nodes)
        for n in self.nodes:
            if n.findtext('type')=='FilterRows':
                for target in ('send_true_to','send_false_to'):
                    assert (n.findtext('name'),n.findtext(target)) in self.edges,(self.name,n.findtext('name'),target)
        assert len(self.edges)==len(set(self.edges)),(self.name,'duplicate hops')
        for a, b in self.edges:
            child(self.order, 'hop', {'from': a, 'to': b, 'enabled': 'Y'})
        self.root.extend(self.nodes)
        eh = E.SubElement(self.root, 'transform_error_handling')
        for err in self.errors:
            child(eh, 'error', err)
        E.SubElement(self.root, 'attributes')
        save(self.root, OUT / (self.name + '.hpl'))

def save(root, path):
    E.indent(root, space='  ')
    E.ElementTree(root).write(path, encoding='UTF-8', xml_declaration=True)

def variables(name, fields):
    n = node('GetVariable', name); fs = E.SubElement(n, 'fields')
    for f, v, t in fields:
        child(fs, 'field', dict(name=f, variable=v, type=t, length=-1, precision=-1, trim_type='none'))
    return n

def db(name, sql, args=()):
    n = node('DBJoin', name, connection='jobtology-postgres', sql=sql, cache='N', cache_size=0, rowlimit=0, outer_join='N', replace_vars='N')
    fs = E.SubElement(n, 'parameter')
    for f, t in args: child(fs, 'field', dict(name=f, type=t))
    return n

def execute(name, sql, args=()):
    n = node('ExecSql', name, connection='jobtology-postgres', sql=sql, execute_each_row='Y', single_statement='Y', set_params='Y', replace_variables='N', quoteString='N')
    fs = E.SubElement(n, 'arguments')
    for f in args: child(fs, 'argument', dict(name=f))
    return n

def filt(name, field, kind, value, yes, no):
    n = node('FilterRows', name, send_true_to=yes, send_false_to=no)
    c = child(E.SubElement(n, 'compare'), 'condition', dict(negated='N', operator='-', leftvalue=field, function='='))
    child(c, 'value', dict(name='constant', type=kind, text=value, length=-1, precision=-1, isnull='N'))
    return n

def abort(name, message):
    return node('Abort', name, message=message, always_log_rows='N', abort_option='ABORT_WITH_ERROR', row_threshold=0)

def remove(name, fields):
    n = node('SelectValues', name); fs = E.SubElement(n, 'fields'); put(fs, 'select_unspecified', 'Y')
    for f in fields: child(fs, 'remove', dict(name=f))
    return n

def log(name, fields, message):
    n = node('WriteToLog', name, loglevel='Basic', displayHeader='Y', logmessage=message)
    fs = E.SubElement(n, 'fields')
    for f in fields: child(fs, 'field', dict(name=f))
    return n

def remember(field, variable):
    n = node('SetVariable', 'Remember batch ID', use_formatting='Y')
    child(E.SubElement(n, 'fields'), 'field', dict(field_name=field, variable_name=variable, variable_type='PARENT_WORKFLOW', default_value=''))
    return n

def executor(name, filename, args, target):
    n = copy.deepcopy(templates['PipelineExecutor'])
    for k in ('GUI', 'partitioning'):
        old = n.find(k)
        if old is not None: n.remove(old)
    for k, v in dict(name=name, filename='${PROJECT_HOME}/llm/' + filename, run_configuration='llm-local',
                     inherit_all_vars='Y', group_size=1, execution_result_target_transform=target,
                     executors_output_transform='',execution_log_text_field='').items():
        put(n, k, v)
    n.find('parameters').clear()
    for param, field in args: child(n.find('parameters'), 'variable_mapping', dict(variable=param, field=field, input=''))
    return n

def child_checks(p, previous, filename, args):
    p.chain(previous, executor('Run sequential request', filename, args, 'Check child errors'),
            filt('Check child errors', 'ExecutionNrErrors', 'Integer', '0', 'Check child result', 'Child error count failed'),
            filt('Check child result', 'ExecutionResult', 'Boolean', 'Y', 'Done', 'Child result failed'), node('Dummy', 'Done'))
    # Hop's Abort transform polls all input rowsets. Feeding both failure filters
    # into one Abort makes that polling loop spin while both inputs are empty and
    # the child request is still running. Each terminal branch therefore owns a
    # single-input Abort transform.
    p.add(abort('Child error count failed', 'LLM request pipeline reported errors. Inspect enrichment.attempt before retrying.'))
    p.add(abort('Child result failed', 'LLM request pipeline returned an unsuccessful result. Inspect enrichment.attempt before retrying.'))
    p.edges += [('Check child errors', 'Child error count failed'), ('Check child result', 'Child result failed')]

def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)

def string(maximum=8000): return dict(type='string', minLength=1, maxLength=maximum)
def enum(*choices): return dict(type='string', enum=list(choices))
def array(items, maximum): return dict(type='array', items=items, maxItems=maximum)

evidence = obj(dict(field=enum('title','organization_name','education','recruitment_type','employment_type','regions',
    'ncs_category_codes','ncs_category_names','eligibility_text','preference_text','selection_text','disqualification_text','duties_text','description_text'), quote=string()))
position = dict(type=['string','null'], minLength=1, maxLength=1000)
extraction = obj(dict(
    positions=array(obj(dict(name=string(1000), evidence=evidence)), 40),
    duties=array(obj(dict(position=position, text=string(), evidence=evidence)), 60),
    requirements=array(obj(dict(position=position, category=enum('education','experience','qualification','skill','other'),
       importance=enum('required','preferred','unspecified'), logic=enum('single','all_of','any_of','unspecified'), text=string(), evidence=evidence)), 100),
    duties_status=enum('explicit','not_stated','attachment_required')))
categorization = obj(dict(matches=array(obj(dict(competency_code=string(40), duty_index=dict(type='integer', minimum=0, maximum=59), reason=string(1500))),20), outcome=enum('matched','no_supported_match')))
refs = array(string(100), 100)
position_ids = array(string(40), 40)
expression = array(obj(dict(op=enum('atom','all_of','any_of','if_then','except'),
    text=dict(type='string', maxLength=8000), children=array(dict(type='integer', minimum=0, maximum=59),60))),60)
extraction_v2 = obj(dict(
    positions=array(obj(dict(id=string(40),name=string(1000),evidence_ids=refs)),40),
    duties=array(obj(dict(position_ids=position_ids,text=string(),evidence_ids=refs)),60),
    requirements=array(obj(dict(position_ids=position_ids,category=enum('education','experience','qualification','skill','other'),
        kind=enum('eligibility','preference','exclusion','unrestricted'),
        logic=enum('single','all_of','any_of','conditional','unspecified'),text=string(),evidence_ids=refs,expression=expression)),100),
    duties_status=enum('explicit','not_stated','attachment_required')))
extraction_v3 = copy.deepcopy(extraction_v2)
for section in ('duties','requirements'):
    item = extraction_v3['properties'][section]['items']
    del item['properties']['text'];item['properties']['text_parts']=array(string(),40)
    item['required']=[k if k!='text' else 'text_parts' for k in item['required']]
atom_v3=extraction_v3['properties']['requirements']['items']['properties']['expression']['items']
del atom_v3['properties']['text'];atom_v3['properties']['parts']=array(string(),20)
atom_v3['required']=[k if k!='text' else 'parts' for k in atom_v3['required']]
extraction_v6 = copy.deepcopy(extraction_v3)
req_v6 = extraction_v6['properties']['requirements']['items']
del req_v6['properties']['expression']
req_v6['properties']['condition'] = {'anyOf':[{'$ref':'#/$defs/condition'}, {'type':'null'}]}
req_v6['required'] = [k if k!='expression' else 'condition' for k in req_v6['required']]
extraction_v6['$defs'] = {'condition': obj(dict(op=enum('atom','all_of','any_of','if_then','except'),
    parts=array(string(),20), children=array({'$ref':'#/$defs/condition'},60)))}
extraction_v6['properties']['unhandled_passages'] = array(obj(dict(evidence_id=string(100),
    disposition=enum('heading','procedure','attachment_reference','no_condition','duplicate','unresolved'),
    reason=string(1000), duplicate_of=dict(type=['string','null'],minLength=1,maxLength=100))),1000)
extraction_v6['required'].append('unhandled_passages')
extraction_v7 = copy.deepcopy(extraction_v6)
del extraction_v7['properties']['unhandled_passages']
extraction_v7['required'] = ['unhandled_ranges' if k=='unhandled_passages' else k for k in extraction_v7['required']]
extraction_v7['properties']['unhandled_ranges'] = array(obj(dict(first_id=string(100),last_id=string(100),
    disposition=enum('heading','procedure','attachment_reference','no_condition','duplicate','document_context','unresolved'),
    context_kind=dict(type=['string','null'],enum=[None,'employment_terms','application_form','institution_background','job_profile','document_structure','privacy_notice']),
    reason=string(1000),duplicate_of=dict(type=['string','null'],minLength=1,maxLength=100))),500)
# Enforce the advertised logic/condition relationship in the provider schema.
# A single condition cannot acquire a redundant or contradictory group tree.
branches=[]
for logic,operator in [(None,None),('all_of','all_of'),('any_of','any_of'),('conditional',None)]:
    branch=copy.deepcopy(req_v6)
    branch['properties']['logic']=enum('single','unspecified') if logic is None else enum(logic)
    if logic is None:branch['properties']['condition']={'type':'null'}
    else:
        root_condition=copy.deepcopy(extraction_v6['$defs']['condition'])
        root_condition['properties']['op']=enum('if_then','except') if logic=='conditional' else enum(operator)
        root_condition['properties']['parts']=array(string(),0)
        root_condition['properties']['children']['minItems']=2
        if logic=='conditional':root_condition['properties']['children']['maxItems']=2
        branch['properties']['condition']=root_condition
    branches.append(branch)
extraction_v7['properties']['requirements']['items']={'anyOf':branches}
rule_schema=json.loads((OUT/'schemas/guarded-rules-v1.json').read_text())
rule_schema_json=json.dumps(rule_schema,ensure_ascii=False,separators=(',',':'))
rule_schema_hash=hashlib.sha256(rule_schema_json.encode()).hexdigest()
(OUT/'sql/015_rule_contract.sql').write_text(f"""-- Generated immutable interpretation contract; no model prompt is changed.
BEGIN;
CREATE TABLE IF NOT EXISTS enrichment.rule_contract (
 schema_version text PRIMARY KEY, output_schema jsonb NOT NULL, content_hash text NOT NULL
);
INSERT INTO enrichment.rule_contract VALUES('guarded-rules-v1',$schema${rule_schema_json}$schema$::jsonb,'{rule_schema_hash}') ON CONFLICT DO NOTHING;
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM enrichment.rule_contract WHERE schema_version='guarded-rules-v1' AND content_hash='{rule_schema_hash}')
 THEN RAISE EXCEPTION 'RULE_CONTRACT_IS_IMMUTABLE'; END IF; END $$;
COMMIT;
""")
prompt_sql = ['BEGIN;']
for version, stage, schema in [('ko-v1','extract',extraction),('ko-v1','categorize',categorization),
                               ('ko-v2','extract',extraction_v2),('ko-v2','categorize',categorization),
                               ('ko-v3','extract',extraction_v3),('ko-v3','categorize',categorization),
                               ('ko-v4','extract',extraction_v3),('ko-v4','categorize',categorization),
                               ('ko-v5','extract',extraction_v3),('ko-v5','categorize',categorization),
                               ('ko-v6','extract',extraction_v6),('ko-v6','categorize',categorization),
                               ('ko-v7','extract',extraction_v7),('ko-v7','categorize',categorization)]:
    text = (OUT / 'prompts' / (stage + '-' + version + '.txt')).read_text()
    raw_schema = json.dumps(schema, ensure_ascii=False, separators=(',',':'))
    content_hash = hashlib.sha256((text + '\n' + raw_schema).encode()).hexdigest()
    (OUT / 'prompts' / (stage + '-' + version + '.schema.json')).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n')
    prompt_sql.append(f"""INSERT INTO enrichment.prompt(version,stage,system_prompt,output_schema,content_hash)
VALUES('{version}','{stage}',$prompt${text}$prompt$,$schema${raw_schema}$schema$::jsonb,'{content_hash}') ON CONFLICT DO NOTHING;
DO $check$ BEGIN IF NOT EXISTS(SELECT 1 FROM enrichment.prompt WHERE version='{version}' AND stage='{stage}' AND content_hash='{content_hash}')
THEN RAISE EXCEPTION 'PROMPT_VERSION_IS_IMMUTABLE'; END IF; END $check$;""")
prompt_sql.append('COMMIT;')
(OUT / 'sql/002_prompts.sql').write_text('\n'.join(prompt_sql) + '\n')

PARAMS = [
 ('JOB_RUN_ID','LATEST','Pin one accepted JOB-ALIO snapshot.'), ('NCS_RUN_ID','LATEST','Pin one accepted NCS snapshot.'),
 ('DATASET_ID','korean-jd-v1','Prepared frozen evaluation dataset; ignored for ENRICH.'),
 ('EXTRACT_MODEL','google/gemini-3.8-flash','OpenRouter model ID for evidence extraction.'),
 ('CATEGORIZE_MODEL','google/gemini-3.8-flash','OpenRouter model ID for NCS matching.'),
 ('PROVIDER_ONLY','','Optional OpenRouter provider slug, e.g. deepinfra. Blank allows compatible-provider routing.'),
 ('PROMPT_VERSION','ko-v3','Installed immutable prompt/schema version; older versions remain available for replay.'),
 ('TEMPERATURE','','Optional 0..2; blank omits the parameter for models that do not support it.'),
 ('REASONING_EFFORT','','Optional none/minimal/low/medium/high/xhigh/max; blank uses provider default.'),
 ('EXTRA_PARAMS_JSON','{}','Optional numeric top_p, seed, frequency_penalty, presence_penalty JSON object.'),
 ('POSTING_IDS','','Optional exact posting IDs separated by |; missing/ineligible IDs fail planning.'),
 ('INPUT_BUNDLE_IDS','','Optional exact attachment input bundle IDs separated by | for ENRICH. EVAL uses its frozen dataset bindings.'),
 ('REPAIR_BATCH_ID','','Optional terminal batch whose failed extractions should be retried. Original attempts remain unchanged.'),
 ('POSTING_LIMIT','20','Maximum postings in this batch. Raise explicitly for a complete source snapshot.'),
 ('CANDIDATE_LIMIT','40','NCS shortlist size per posting, 1..100.'), ('MAX_MATCHES','8','Maximum duty-to-NCS matches per posting.'),
 ('MAX_INPUT_CHARS','60000','Reject oversized complete requests; never silently truncate source text.'),
 ('MAX_OUTPUT_TOKENS','6000','Maximum billed output tokens per request, including reasoning.'),
 ('MAX_REQUESTS','40','Maximum charged/uncertain HTTP requests in this batch; no automatic retries.'),
 ('REQUEST_RESERVE_USD','0.10','Conservative reservation per request; set for chosen models. Not a provider-enforced price cap.'),
 ('MAX_COST_USD','5','Batch accounting cap using the greater of reservation and reported cost.'),
 ('DAILY_BUDGET_USD','20','Rolling 24-hour accounting cap shared by these workflows.'),
 ('EXECUTE_REQUESTS','N','N plans requests without reading a key or making model calls; Y executes.'),
 ('REUSE_CACHE','N','Y reuses valid outputs with identical content/prompt/model/options; N repeats an evaluation.'),
 ('ACCEPTANCE_POLICY','REVIEW','REVIEW waits for a review; VALIDATED automatically accepts checked ENRICH items. EVAL remains isolated.'),
 ('ENDPOINT','https://openrouter.ai/api/v1/chat/completions','HTTPS OpenRouter-compatible chat completion endpoint.'),
 ('API_KEY_FILE','${HOP_CONFIG_FOLDER}/secrets/openrouter.csv','Protected UTF-8 CSV with api_key header and exactly one key row.'),
 ('REQUEST_DELAY_MS','250','Delay before each sequential model request.'),
 ('READ_TIMEOUT_MS','180000','Finite HTTP read timeout in milliseconds.'),
]

p = Pipe('start_batch','Freeze inputs and settings. A planned run makes no paid calls.')
fields = [('run_mode','${RUN_MODE}','String')] + [(k.lower(),'${'+k+'}','String') for k,_,_ in PARAMS]
p.chain(variables('Workflow options', fields), db('Build immutable settings', """SELECT gen_random_uuid()::text AS batch_id,
jsonb_strip_nulls(jsonb_build_object('extract_model',?::text,'categorize_model',?::text,'provider_only',nullif(?::text,''),'prompt_version',?::text,
'temperature',nullif(?::text,''),'reasoning_effort',nullif(?::text,''),'extra_params',?::jsonb,
'limit',?::integer,'candidate_limit',?::integer,'max_matches',?::integer,'max_input_chars',?::integer,
'max_output_tokens',?::integer,'max_requests',?::integer,'request_reserve_usd',?::numeric,'max_cost_usd',?::numeric,
'daily_budget_usd',?::numeric,'execute_requests',?::text,'reuse_cache',?::text,'endpoint',?::text,
'request_delay_ms',?::integer,'read_timeout_ms',?::integer,'acceptance_policy',?::text,'posting_ids',nullif(?::text,''),'repair_batch_id',nullif(?::text,''),'input_bundle_ids',nullif(?::text,'')))::text AS settings_json""",
[(x,'String') for x in ['extract_model','categorize_model','provider_only','prompt_version','temperature','reasoning_effort','extra_params_json',
 'posting_limit','candidate_limit','max_matches','max_input_chars','max_output_tokens','max_requests','request_reserve_usd',
 'max_cost_usd','daily_budget_usd','execute_requests','reuse_cache','endpoint','request_delay_ms','read_timeout_ms','acceptance_policy','posting_ids','repair_batch_id','input_bundle_ids']]), remember('batch_id','LLM_BATCH_ID'),
 execute('Plan batch','SELECT enrichment.plan_batch(?,?,?, ?,?,?::jsonb)', ['batch_id','run_mode','dataset_id','job_run_id','ncs_run_id','settings_json']),
 log('Batch created',['batch_id','run_mode','execute_requests'],'LLM batch created; inspect enrichment.batch_report'))
p.save()

# Reuse the exact options builder; the new planner binds reviewed revisions and
# creates no extraction attempts. Older workflow parameter contracts stay intact.
revision_start = copy.deepcopy(p.root)
put(revision_start.find('info'),'name','start_revision_batch')
put(revision_start.find('info'),'description','Pin accepted extraction revisions for NCS-only requests.')
for transform in revision_start.findall('transform'):
    if transform.findtext('name')=='Workflow options':
        for field in transform.find('fields').findall('field'):
            if field.findtext('name')=='run_mode': put(field,'variable','ENRICH')
            if field.findtext('name')=='extract_model': put(field,'variable','unused/reviewed-extraction')
            if field.findtext('name') in ('dataset_id','posting_ids','repair_batch_id'): put(field,'variable','')
        child(transform.find('fields'),'field',dict(name='revision_ids',variable='${REVISION_IDS}',type='String',length=-1,precision=-1,trim_type='none'))
        child(transform.find('fields'),'field',dict(name='actor',variable='${ACTOR}',type='String',length=-1,precision=-1,trim_type='none'))
    if transform.findtext('name')=='Plan batch':
        put(transform,'sql',"SELECT enrichment.plan_revision_batch(?,?,?,?::jsonb||jsonb_build_object('actor',?::text),?)")
        args=transform.find('arguments'); args.clear()
        for f in ('batch_id','job_run_id','ncs_run_id','settings_json','actor','revision_ids'): child(args,'argument',dict(name=f))
save(revision_start,OUT/'start_revision_batch.hpl')

for step in ('extract','categorize'):
    p = Pipe('plan_'+step,'Build '+step+' requests and resolve reusable outputs.')
    p.chain(variables('Batch',[('batch_id','${LLM_BATCH_ID}','String')]),execute('Plan '+step, f"SELECT enrichment.plan_stage(?,'{step}')",['batch_id']))
    p.save()
    p = Pipe('run_'+step,'Execute planned '+step+' requests sequentially; a dry run has no request rows.')
    p.chain(variables('Batch',[('batch_id','${LLM_BATCH_ID}','String')]),db('Pending requests',
      "SELECT a.attempt_id FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) JOIN enrichment.item i ON i.item_id=a.item_id WHERE a.batch_id=? AND a.stage='"+step+"' AND a.state='PLANNED' AND b.state='RUNNING' AND b.settings->>'execute_requests'='Y' ORDER BY i.ordinal", [('batch_id','String')]))
    child_checks(p,'Pending requests','request.hpl',[('ATTEMPT_ID','attempt_id')]);p.save()

p = Pipe('request','Load one protected key, reserve one request, send HTTPS JSON, and persist validated output.',{'ATTEMPT_ID':''})
csv = node('CsvInput','Read protected key',filename='${API_KEY_FILE}',include_filename='N',header='Y',separator=',',enclosure='"',
           buffer_size=50000,lazy_conversion='N',add_filename_result='N',parallel='N',encoding='UTF-8',newline_possible='N',ignoreFields='N')
child(E.SubElement(csv,'fields'),'field',dict(name='api_key',type='String',length=-1,precision=-1,trim_type='both'))
group = node('GroupBy','Require exactly one key row',all_rows='N',give_back_row='Y',ignore_aggregate='N',add_linenr='N')
E.SubElement(group,'group');fs=E.SubElement(group,'fields')
child(fs,'field',dict(aggregate='key_count',subject='api_key',type='COUNT_ANY'))
child(fs,'field',dict(aggregate='api_key',subject='api_key',type='FIRST'))
child(fs,'field',dict(aggregate='nonempty_keys',subject='api_key',type='COUNT_ALL'))
p.chain(csv,group,filt('One key row','key_count','Integer','1','Nonempty key','Invalid key file'),
 filt('Nonempty key','nonempty_keys','Integer','1','Request identity','Invalid key file'))
p.chain(variables('Request identity',[('attempt_id','${ATTEMPT_ID}','String'),('bearer_prefix','Bearer ','String')]),
 execute('Reserve request','SELECT enrichment.reserve_request(?)',['attempt_id']),
 db('Read reserved request',"SELECT a.request_body::text AS request_json,b.settings->>'endpoint' AS request_url FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) WHERE a.attempt_id=? AND a.state='RESERVED'",[('attempt_id','String')]))
p.edges.append(('Nonempty key','Request identity'))
p.edges.append(('Nonempty key','Invalid key file'))
concat=node('ConcatFields','Authorization header',separator='',enclosure='',force_enclosure='N',skip_value_empty='N')
child(concat,'ConcatFields',dict(targetFieldName='authorization',targetFieldLength=-1,removeSelectedFields='Y'))
fs=E.SubElement(concat,'fields')
for f in ('bearer_prefix','api_key'):child(fs,'field',dict(name=f,type='String',length=-1,precision=-1,trim_type='none'))
p.chain('Read reserved request',concat,node('Delay','Request spacing',timeout='${REQUEST_DELAY_MS}',scaletime='milliseconds'))
rest=node('Rest','Call model',applicationType='JSON',connection_name='',urlInField='Y',urlField='request_url',httpLogin='',httpPassword='',
 non_preemptive_basic_auth='N',method='POST',dynamicMethod='N',bodyField='request_json',connectionTimeout=10000,readTimeout='${READ_TIMEOUT_MS}',
 ignoreSsl='N',retryTimes=0,paginationEnabled='N',streamingEnabled='N')
child(E.SubElement(rest,'headers'),'header',dict(field='authorization',name='Authorization'))
E.SubElement(rest,'parameters');E.SubElement(rest,'matrixParameters')
child(rest,'result',dict(name='response_body',code='http_status',response_time='latency_ms',binary='N'))
p.chain('Request spacing',rest,remove('Remove authorization',['authorization','key_count','nonempty_keys']),
 execute('Save response and validate','SELECT enrichment.save_response(?,?::integer,?,?::bigint)', ['attempt_id','http_status','response_body','latency_ms']))
p.chain(remove('Remove transport error details',['authorization','key_count','nonempty_keys','rest_error_count','rest_error_description','rest_error_fields','rest_error_code']),
 execute('Record uncertain transport result',"SELECT enrichment.save_response(?,0,NULL,NULL)",['attempt_id']))
p.edges.append(('Call model','Remove transport error details'))
p.errors.append(dict(source_transform='Call model',target_transform='Remove transport error details',is_enabled='Y',nr_valuename='rest_error_count',
 descriptions_valuename='rest_error_description',fields_valuename='rest_error_fields',codes_valuename='rest_error_code',max_errors='0',max_pct_errors='0',min_pct_rows='0'))
p.chain(remove('Invalid key file',['api_key','key_count','nonempty_keys']),abort('Stop invalid key','API_KEY_FILE must contain exactly one nonempty key row.'))
p.edges.append(('One key row','Invalid key file'));p.save()

for name, failed in [('finish_batch',False),('mark_failed',True)]:
    p=Pipe(name,'Finalize batch without changing source ingestion records.')
    p.chain(variables('Batch',[('batch_id','${LLM_BATCH_ID}','String')]),
     execute('Finish batch',f"SELECT enrichment.finish_batch(?,{'true' if failed else 'false'})",['batch_id']),
     db('Read batch report',"SELECT state,postings,validated,rejected,requests,reported_cost_usd,unknown_cost_requests,labeled_postings FROM enrichment.batch_report WHERE batch_id=?",[('batch_id','String')]),
     log('Batch report',['batch_id','state','postings','validated','rejected','requests','reported_cost_usd','unknown_cost_requests','labeled_postings'],
         'LLM result; COMPLETE means structural/evidence checks passed, not a measured quality score.'))
    p.save()

p=Pipe('prepare_dataset','Freeze a stratified, repeatable sample of real Korean postings for model comparisons.')
p.chain(variables('Dataset options',[(k.lower(),'${'+k+'}','String') for k in ('DATASET_ID','JOB_RUN_ID','NCS_RUN_ID','DATASET_SIZE','SAMPLE_SEED')]),
 execute('Prepare frozen dataset','SELECT enrichment.prepare_dataset(?,?,?,?::integer,?)',['dataset_id','job_run_id','ncs_run_id','dataset_size','sample_seed']),
 db('Dataset counts','SELECT job_run_id AS pinned_jobs,ncs_run_id AS pinned_ncs,(SELECT count(*) FROM enrichment.test_case c WHERE c.dataset_id=d.dataset_id) AS case_count FROM enrichment.dataset d WHERE dataset_id=?',[('dataset_id','String')]),
 log('Dataset ready',['dataset_id','pinned_jobs','pinned_ncs','case_count'],'Dataset frozen. Use the same DATASET_ID for every model comparison.'))
p.save()

def workflow(filename,name,params,steps, failure=True):
    w=E.Element('workflow');put(w,'name',name);put(w,'description',name);put(w,'workflow_version','1');put(w,'workflow_status','0')
    ps=E.SubElement(w,'parameters')
    for k,v,d in params:child(ps,'parameter',dict(name=k,default_value=v,description=d))
    actions=E.SubElement(w,'actions');hops=E.SubElement(w,'hops')
    def action(name,kind,i,file=None):
        a=child(actions,'action',dict(name=name,type=kind,xloc=80+(i%5)*240,yloc=80+(i//5)*160,draw='Y',parallel='N'))
        E.SubElement(a,'attributes')
        if kind=='SPECIAL':
            for k,v in dict(start='Y',repeat='N',schedulerType=0,intervalSeconds=0,intervalMinutes=60,DayOfMonth=1,weekDay=1,minutes=0,hour=12).items():put(a,k,v)
        if kind=='PIPELINE':
            for k,v in dict(filename='${PROJECT_HOME}/llm/'+file,params_from_previous='N',exec_per_row='N',clear_rows='N',clear_files='N',
                            set_logfile='N',loglevel='Basic',wait_until_finished='Y',run_configuration='llm-local').items():put(a,k,v)
            child(a,'parameters',dict(pass_all_parameters='Y'))
        if kind=='ABORT':put(a,'message','LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.')
    def hop(a,b,success=True):child(hops,'hop',{'from':a,'to':b,'enabled':'Y','evaluation':'Y' if success else 'N','unconditional':'Y' if a=='Start' else 'N'})
    action('Start','SPECIAL',0);previous='Start'
    for i,(name,file) in enumerate(steps,1):
        action(name,'PIPELINE',i,file);hop(previous,name);hop(name,'Record failure' if failure else 'Abort',False);previous=name
    action('Success','SUCCESS',len(steps)+1);hop(previous,'Success')
    if failure:
        action('Record failure','PIPELINE',len(steps)+2,'mark_failed.hpl');hop('Record failure','Abort');hop('Record failure','Abort',False)
    action('Abort','ABORT',len(steps)+3)
    E.SubElement(w,'notepads');E.SubElement(w,'attributes');save(w,OUT/filename)

for filename,function,description,with_actor in [
 ('audit_batch','audit_extractions','Audit terminal v4/v5 extraction results without model calls.',False),
 ('capture_audited','capture_clean_audit','Prepare clean audited outputs for independent review; no acceptance.',True)]:
 audit_params=[('BATCH_ID','','Exact terminal batch ID.'),('VALIDATOR_VERSION','ko-v5','Installed compatible audit policy.')]
 if with_actor:audit_params += [('ACTOR','validation:clause-scope-v5','Actor recording revalidation; not a human acceptance decision.'),
  ('REASON','Revalidated saved provider output; prepared for independent review.','Reason for the append-only extraction revision.')]
 p=Pipe(filename,description)
 args=[(k.lower(),'${'+k+'}','String') for k,_,_ in audit_params]
 order=['batch_id','actor','reason','validator_version'] if with_actor else ['batch_id','validator_version']
 p.chain(variables('Audit options',args),db('Record audit' if not with_actor else 'Capture review candidates',
  'SELECT enrichment.'+function+'('+','.join('?' for _ in order)+') AS recorded',[(k,'String') for k in order]),
  log('Audit result',['batch_id','validator_version','recorded'],description))
 p.save();workflow(filename+'.hwf',description,audit_params,[('Record results',filename+'.hpl')],False)
p=Pipe('inspect_audit','Preview audit outcomes and whether each output needs a model repair.',{'BATCH_ID':'','VALIDATOR_VERSION':'ko-v5'})
p.chain(variables('Audit options',[('batch_id','${BATCH_ID}','String'),('version','${VALIDATOR_VERSION}','String')]),
 db('Audit report',"SELECT i.posting_id,a.state AS original_state,d.issues AS audit_issues,d.checked_at,"
 "EXISTS(SELECT 1 FROM enrichment.extraction_revision r WHERE r.item_id=i.item_id) AS has_review_revision "
 "FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.extraction_id "
 "LEFT JOIN enrichment.extraction_audit d ON d.attempt_id=a.attempt_id AND d.validator_version=? "
 "WHERE i.batch_id=? ORDER BY i.ordinal",[('version','String'),('batch_id','String')]),node('Dummy','Preview audited results'))
p.save()

for mode,filename in [('EVAL','evaluate.hwf'),('ENRICH','enrich.hwf')]:
    params=[('RUN_MODE',mode,'EVAL stays separate from publishable enrichment.')] + [(k,('Y' if mode=='ENRICH' and k=='REUSE_CACHE' else v),d) for k,v,d in PARAMS]
    workflow(filename,'Evaluate Korean postings' if mode=='EVAL' else 'Enrich Korean postings and categorize NCS',params,
      [('Freeze inputs and options','start_batch.hpl'),('Plan extraction','plan_extract.hpl'),('Extract supported facts','run_extract.hpl'),
       ('Retrieve NCS and plan matches','plan_categorize.hpl'),('Categorize explicit duties','run_categorize.hpl'),('Validate and report','finish_batch.hpl')])

p=Pipe('import_revision_links','Append model candidates and explicit no-match outcomes for the exact reviewed revision.')
p.chain(variables('Import options',[('batch_id','${LLM_BATCH_ID}','String'),('actor','${ACTOR}','String')]),
 db('Completed revision results',"SELECT i.item_id FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) "
    "JOIN enrichment.attempt a ON a.attempt_id=i.categorization_id WHERE i.batch_id=? "
    "AND b.settings->>'execute_requests'='Y' AND a.state IN ('VALIDATED','SKIPPED') ORDER BY i.ordinal",[('batch_id','String')]),
 db('Append revision candidates','SELECT enrichment.import_revision_links(?,?) AS candidate_count',[('item_id','String'),('actor','String')]),
 log('Candidates imported',['item_id','candidate_count'],'Candidates require independent review; existing decisions are unchanged.'))
p.save()
revision_params=[(k,('ko-v6' if k=='PROMPT_VERSION' else v),d) for k,v,d in PARAMS
 if k not in ('EXTRACT_MODEL','DATASET_ID','POSTING_IDS','REPAIR_BATCH_ID','ACCEPTANCE_POLICY')]
workflow('categorize_reviewed.hwf','Categorize accepted extraction revisions without re-extraction',revision_params+[
 ('ACCEPTANCE_POLICY','REVIEW','Independent per-link decisions remain required.'),
 ('REVISION_IDS','','Exact accepted extraction revision IDs separated by |. Missing, superseded or changed revisions fail.'),
 ('ACTOR','','Named actor importing candidates and no-match outcomes.')],
 [('Freeze reviewed inputs','start_revision_batch.hpl'),('Retrieve NCS and plan matches','plan_categorize.hpl'),
  ('Categorize reviewed duties','run_categorize.hpl'),('Capture candidate outcomes','import_revision_links.hpl'),('Validate and report','finish_batch.hpl')])

p=Pipe('inspect_revision_links','Inspect revision-pinned categorization, source context, candidates and independent decisions.',{'BATCH_ID':''})
p.chain(variables('Batch',[('batch_id','${BATCH_ID}','String')]),
 db('Revision link details',"""SELECT i.posting_id,i.item_id,ri.revision_id,ri.decision_id AS extraction_decision_id,
 b.ncs_run_id,a.attempt_id,a.state,a.issues::text AS issues,r.extraction::text AS extraction_json,
 a.candidates::text AS shortlist_json,a.parsed_output::text AS response_json,result.outcome,
 c.candidate_id,c.competency_code,c.duty_index,s.reason AS latest_proposal_reason,d.decision AS link_decision
 FROM enrichment.item i JOIN enrichment.batch b USING(batch_id) JOIN enrichment.revision_input ri USING(item_id)
 JOIN enrichment.extraction_revision r USING(revision_id) LEFT JOIN enrichment.attempt a ON a.attempt_id=i.categorization_id
 LEFT JOIN enrichment.revision_link_result result ON result.item_id=i.item_id
 LEFT JOIN enrichment.link_support s ON s.item_id=i.item_id LEFT JOIN enrichment.link_candidate c USING(candidate_id)
 LEFT JOIN enrichment.latest_link_decision d USING(candidate_id) WHERE i.batch_id=? ORDER BY i.ordinal,c.duty_index,c.competency_code""",[('batch_id','String')]),
 node('Dummy','Preview revision matches here'))
p.save()
workflow('prepare_evaluation.hwf','Prepare a frozen Korean evaluation dataset',
 [(k,v,d) for k,v,d in PARAMS if k in ('DATASET_ID','JOB_RUN_ID','NCS_RUN_ID')] + [('DATASET_SIZE','20','Sample size, stratified by Korean posting characteristics.'),('SAMPLE_SEED','ko-v1','Stable sampling seed.')],
 [('Freeze evaluation cases','prepare_dataset.hpl')],False)

for kind in ('pipeline','workflow'):
    path=ROOT/f'hop/metadata/{kind}-run-configuration/llm-local.json'
    conf=json.loads((ROOT/f'hop/metadata/{kind}-run-configuration/reference-local.json').read_text())
    conf['name']='llm-local';conf['description']='Native LLM workflows. Basic logging; no row sampling or execution-data capture.'
    path.write_text(json.dumps(conf,indent=2)+'\n')

# SQL installation is a workflow action: these files contain DDL, not result rows.
workflow('install.hwf','Install additive enrichment tables and functions',[],[],False)
w=E.parse(OUT/'install.hwf').getroot();acts=w.find('actions');hops=w.find('hops');hops.clear()
previous='Start'
for i,path in enumerate(sorted((OUT/'sql').glob('*.sql')),1):
    name=path.stem
    child(acts,'action',dict(name=name,type='SQL',connection='jobtology-postgres',sqlfromfile='Y',
      sqlfilename='${PROJECT_HOME}/llm/sql/'+path.name,sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',
      xloc=80+(i%5)*240,yloc=80+(i//5)*160,draw='Y',parallel='N'))
    child(hops,'hop',{'from':previous,'to':name,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
    child(hops,'hop',{'from':name,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'})
    previous=name
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'})
save(w,OUT/'install.hwf')

workflow('prepare_regression_v2.hwf','Freeze the 22 existing regression cases and import provisional source assertions',[
 ('GOLD_FILE','${PROJECT_HOME}/llm/evaluation/korean-regression-v2-22.assertions.json','Assistant-authored provisional assertions; not human gold.')],
 [('Import provisional assertions','import_gold.hpl')],False)
w=E.parse(OUT/'prepare_regression_v2.hwf').getroot()
child(w.find('actions'),'action',dict(name='Freeze exact regression inputs',type='SQL',connection='jobtology-postgres',sqlfromfile='Y',
 sqlfilename='${PROJECT_HOME}/llm/evaluation/prepare-korean-regression-v2.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',
 xloc=320,yloc=240,draw='Y',parallel='N'))
for edge in w.find('hops').findall('hop'):
    if edge.findtext('from')=='Start':put(edge,'to','Freeze exact regression inputs')
child(w.find('hops'),'hop',{'from':'Freeze exact regression inputs','to':'Import provisional assertions','enabled':'Y','evaluation':'Y','unconditional':'N'})
child(w.find('hops'),'hop',{'from':'Freeze exact regression inputs','to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'})
save(w,OUT/'prepare_regression_v2.hwf')

p=Pipe('inspect_results','Preview the last transform to inspect source text, extraction, NCS candidates and validation issues.',{'BATCH_ID':''})
p.chain(variables('Batch',[('batch_id','${BATCH_ID}','String')]),db('Review rows',"""SELECT item_id,posting_id,source_data->>'title' AS title,state,
source_data::text AS source_json,extraction::text AS extraction_json,categorization::text AS categorization_json,candidates::text AS candidate_json,
extraction_issues::text AS extraction_issues,categorization_issues::text AS categorization_issues,decision
FROM enrichment.result WHERE batch_id=? ORDER BY ordinal""",[('batch_id','String')]),node('Dummy','Preview results here'));p.save()
p=Pipe('inspect_comparison','Preview reports for one frozen dataset; unlabelled quality metrics remain empty.',{'DATASET_ID':'korean-jd-v1'})
p.chain(variables('Dataset',[('dataset_id','${DATASET_ID}','String')]),db('Model comparison',"""SELECT batch_id,created_at,state,settings->>'extract_model' AS extract_model,
settings->>'categorize_model' AS categorize_model,postings,validated,rejected,requests,reported_cost_usd,unknown_cost_requests,labeled_postings,
requirement_precision,requirement_recall,duty_precision,duty_recall,ncs_precision,ncs_recall,retrieval_recall,no_match_cases,correct_abstentions
FROM enrichment.batch_report WHERE dataset_id=? ORDER BY created_at DESC""",[('dataset_id','String')]),node('Dummy','Preview comparison here'));p.save()
p=Pipe('review_item','Record a named human review. EVAL results cannot be accepted for publication.')
p.chain(variables('Review',[(k.lower(),'${'+k+'}','String') for k in ('ITEM_ID','DECISION','REVIEWER','NOTES')]),
 execute('Save review','SELECT enrichment.review_item(?,?,?,?)',['item_id','decision','reviewer','notes']),log('Review recorded',['item_id','decision','reviewer'],'Review recorded. Run publish_reviewed.hwf to synchronize Neo4j.'));p.save()
workflow('review_item.hwf','Accept or reject one enrichment',[
 ('ITEM_ID','','Copy the item_id from inspect_results.hpl.'),('DECISION','REJECT','ACCEPT or REJECT. Acceptance requires a validated ENRICH result.'),
 ('REVIEWER','','Your name or stable reviewer ID.'),('NOTES','','Review notes.')],[('Record review','review_item.hpl')],False)
# Independent extraction revisions and per-link decisions. No publication side effect.
p=Pipe('capture_extraction','Capture validated extraction independently of categorization.')
p.chain(variables('Capture options',[(k.lower(),'${'+k+'}','String') for k in ('ITEM_ID','ACTOR','REASON')]),
 db('Append extraction revision','SELECT enrichment.capture_extraction(?,?,?) AS revision_id',[(k,'String') for k in ('item_id','actor','reason')]),
 log('Revision saved',['item_id','revision_id'],'Review extraction and NCS candidates separately.'))
p.save()
workflow('capture_extraction.hwf','Capture an extraction revision',[
 ('ITEM_ID','','ENRICH item ID.'),('ACTOR','','Named person or automation identity.'),('REASON','','Why this revision is being captured.')],
 [('Capture revision','capture_extraction.hpl')],False)

p=Pipe('import_correction','Append a source-validated correction from a UTF-8 JSON file.')
reader=node('JsonInput','Read correction JSON',IsInFields='Y',IsAFile='Y',valueField='correction_filename',removeSourceField='N',ignoreMissingPath='N',defaultPathLeafToNull='Y',doNotFailIfNoFile='N')
child(E.SubElement(reader,'fields'),'field',dict(name='correction_json',path='$',type='String',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Correction file',[('correction_filename','${CORRECTION_FILE}','String')]),reader,
 db('Append corrected revision',"""SELECT enrichment.capture_extraction(v->>'item_id',v->>'actor',v->>'reason',v->'output',v->>'parent_revision_id') AS revision_id FROM (SELECT ?::jsonb v) input""",[('correction_json','String')]),
 log('Correction saved',['revision_id'],'Original attempts and earlier revisions remain unchanged.'))
p.save()
workflow('import_correction.hwf','Import a corrected extraction',[
 ('CORRECTION_FILE','${PROJECT_HOME}/data/llm/correction.json','Object: item_id, parent_revision_id, actor, reason, output in the pinned raw schema.')],
 [('Append correction','import_correction.hpl')],False)

p=Pipe('import_rule_interpretation','Append source-grounded conditional meaning separately from the provider response.')
reader=node('JsonInput','Read rule interpretation',IsInFields='Y',IsAFile='Y',valueField='interpretation_filename',removeSourceField='N',ignoreMissingPath='N',defaultPathLeafToNull='Y',doNotFailIfNoFile='N')
child(E.SubElement(reader,'fields'),'field',dict(name='interpretation_json',path='$',type='String',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Interpretation file',[('interpretation_filename','${INTERPRETATION_FILE}','String')]),reader,
 db('Append source interpretation',"""SELECT enrichment.capture_rule_interpretation(v->>'revision_id',(v->>'requirement_index')::integer,
 v->>'actor',v->>'reason',v->'document',v->>'parent_id') AS interpretation_id FROM (SELECT ?::jsonb v) input""",[('interpretation_json','String')]),
 log('Interpretation saved',['interpretation_id'],'Conditional interpretation remains pending independent review.'))
p.save()
workflow('import_rule_interpretation.hwf','Import a conditional interpretation',[
 ('INTERPRETATION_FILE','${PROJECT_HOME}/data/llm/rule-interpretation.json','Object: revision_id, requirement_index, parent_id, actor, reason and guarded-rules-v1 document.')],
 [('Append source-grounded interpretation','import_rule_interpretation.hpl')],False)

p=Pipe('review_rule_interpretation','Append a separate decision about the interpretation of a requirement.')
fields=('INTERPRETATION_ID','DECISION','REVIEWER','REVIEWER_KIND','NOTES')
p.chain(variables('Interpretation decision',[(k.lower(),'${'+k+'}','String') for k in fields]),
 execute('Append interpretation decision','SELECT enrichment.decide_rule_interpretation(?,?,?,?,?)',[k.lower() for k in fields]),
 log('Interpretation reviewed',['interpretation_id','decision','reviewer_kind'],'Source extraction and individual NCS decisions remain separate.'))
p.save()
workflow('review_rule_interpretation.hwf','Review conditional meaning',[
 ('INTERPRETATION_ID','','Exact interpretation hash.'),('DECISION','REJECT','ACCEPT or REJECT.'),
 ('REVIEWER','','Stable reviewer identity.'),('REVIEWER_KIND','human','human, assistant or policy; never impersonate a human review.'),
 ('NOTES','','Evidence-based rationale.')],[('Record independent interpretation review','review_rule_interpretation.hpl')],False)

p=Pipe('inspect_rule_interpretation','Inspect source text and separately reviewed conditional meaning.',{'REVISION_ID':''})
p.chain(variables('Revision',[('revision_id','${REVISION_ID}','String')]),
 db('Rule interpretation detail',"""SELECT r.revision_id,ri.requirement_index,r.extraction->'requirements'->ri.requirement_index AS original_requirement,
 ri.interpretation_id,ri.parent_id,ri.document::text AS rule_document,ri.decision,ri.reviewer,ri.reviewer_kind,ri.notes
 FROM enrichment.extraction_revision r JOIN enrichment.current_rule_interpretation ri USING(revision_id)
 WHERE r.revision_id=? ORDER BY ri.requirement_index""",[('revision_id','String')]),node('Dummy','Preview source and meaning'))
p.save()
p=Pipe('preview_rule_activation','Evaluate a reviewed interpretation under supplied hypothetical Boolean observations.',{'INTERPRETATION_ID':'','OBSERVATIONS_JSON':'{}'})
p.chain(variables('Activation preview',[('interpretation_id','${INTERPRETATION_ID}','String'),('observations','${OBSERVATIONS_JSON}','String')]),
 db('Rule activity','SELECT enrichment.rule_activation_preview(?,?::jsonb)::text AS activity_json',[('interpretation_id','String'),('observations','String')]),
 node('Dummy','Preview activation only'))
p.save()

for stage,id_param,func in [('extraction','REVISION_ID','decide_extraction'),('link','CANDIDATE_ID','decide_link')]:
 name='review_'+stage
 p=Pipe(name,'Append an independent semantic decision. No graph publication.')
 fields=(id_param,'DECISION','REVIEWER','REVIEWER_KIND','NOTES')
 p.chain(variables('Decision',[(k.lower(),'${'+k+'}','String') for k in fields]),
  execute('Append decision','SELECT enrichment.'+func+'(?,?,?,?,?)',[k.lower() for k in fields]),
  log('Decision recorded',[id_param.lower(),'decision','reviewer','reviewer_kind'],'Decision recorded with explicit reviewer provenance.'))
 p.save()
 workflow(name+'.hwf','Review one '+stage,[
  (id_param,'','Exact immutable revision/candidate ID.'),('DECISION','REJECT','ACCEPT or REJECT.'),
  ('REVIEWER','','Stable reviewer identity.'),('REVIEWER_KIND','human','human, assistant or policy; automation must identify itself accurately.'),
  ('NOTES','','Required evidence-based rationale.')],[('Record independent review',name+'.hpl')],False)

p=Pipe('import_model_links','Import reviewed-output candidates without accepting any link.')
p.chain(variables('Candidate options',[('revision_id','${REVISION_ID}','String'),('actor','${ACTOR}','String')]),
 db('Import candidates','SELECT enrichment.import_model_links(?,?) AS candidate_count',[('revision_id','String'),('actor','String')]),
 log('Candidates ready',['revision_id','candidate_count'],'Each candidate needs a separate decision.'))
p.save()
workflow('import_model_links.hwf','Import model NCS candidates',[
 ('REVISION_ID','','Captured extraction revision.'),('ACTOR','','Named operator or automation.')],
 [('Import independent candidates','import_model_links.hpl')],False)

p=Pipe('inspect_independent_reviews','Preview extracted revisions and independently reviewed NCS links.',{'ITEM_ID':''})
p.chain(variables('Item',[('item_id','${ITEM_ID}','String')]),
 db('Review detail',"""SELECT r.revision_id,r.parent_revision_id,r.extraction::text AS extraction_json,r.decision AS extraction_decision,
 r.reviewer_kind AS extraction_reviewer_kind,c.candidate_id,c.competency_code,c.duty_index,c.reason,
 n.name AS competency_name,n.definition,n.occupation_name,d.decision AS link_decision,d.reviewer_kind AS link_reviewer_kind
 FROM enrichment.extraction_review_state r LEFT JOIN enrichment.link_candidate c USING(revision_id)
 LEFT JOIN enrichment.ncs_catalog n ON n.run_id=c.ncs_run_id AND n.code=c.competency_code
 LEFT JOIN enrichment.latest_link_decision d USING(candidate_id)
 WHERE r.item_id=? ORDER BY r.revision_no,c.duty_index,c.competency_code""",[('item_id','String')]),node('Dummy','Preview review detail here'))
p.save()

p=Pipe('import_gold','Import human labels from one JSON document; gold labels never enter model prompts.')
reader=node('JsonInput','Read gold JSON',IsInFields='Y',IsAFile='Y',valueField='gold_filename',removeSourceField='N',ignoreMissingPath='N',defaultPathLeafToNull='Y',doNotFailIfNoFile='N')
child(E.SubElement(reader,'fields'),'field',dict(name='gold_json',path='$',type='String',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Gold file',[('gold_filename','${GOLD_FILE}','String')]),reader,execute('Save gold revision','SELECT enrichment.import_gold(?::jsonb)',['gold_json']));p.save()
workflow('import_gold.hwf','Import reviewed evaluation labels',[('GOLD_FILE','${PROJECT_HOME}/data/llm/gold.json','UTF-8 JSON containing dataset_id, reviewer and cases.')],[('Import human labels','import_gold.hpl')],False)
p=Pipe('export_review_file','Write a human-readable frozen-case review document; refuse to overwrite an existing file.')
p.chain(variables('Review file options',[('dataset_id','${DATASET_ID}','String'),('review_filename','${REVIEW_FILE}','String')]),
 db('Build review document',"""SELECT convert_to(jsonb_pretty(jsonb_build_object('dataset_id',d.dataset_id,'reviewer','',
 'cases',(SELECT jsonb_agg(jsonb_build_object('posting_id',c.posting_id,'source_data',c.source_data,
 'labels',coalesce((SELECT g.labels FROM enrichment.gold g WHERE g.dataset_id=c.dataset_id AND g.posting_id=c.posting_id ORDER BY gold_id DESC LIMIT 1),
 jsonb_build_object('requirements','[]'::jsonb,'duties','[]'::jsonb,'ncs_codes','[]'::jsonb,
 'requirements_complete',false,'duties_complete',false,'ncs_complete',false))) ORDER BY c.ordinal)
 FROM enrichment.test_case c WHERE c.dataset_id=d.dataset_id))),'UTF8') AS review_bytes
 FROM enrichment.dataset d WHERE d.dataset_id=?""",[('dataset_id','String')]),
 node('BinaryFileOutput','Save review JSON',binaryfield='review_bytes',filenamefield='review_filename',createparentfolder='Y',overwritefile='N',addresultfilenames='N'),
 log('Review file saved',['dataset_id','review_filename'],'Fill reviewer and labels, remove unlabelled cases, then run import_gold.hwf.'))
p.save()
workflow('export_review_file.hwf','Export frozen cases for human quality review',[
 ('DATASET_ID','korean-jd-v1','Prepared dataset.'),('REVIEW_FILE','${PROJECT_HOME}/data/llm/korean-jd-v1-review.json','New UTF-8 JSON output file; existing files are not overwritten.')],
 [('Export source text and label template','export_review_file.hpl')],False)

def cypher(name,query,args=(),returns=(),readonly=False):
    n=node('Neo4jCypherOutput',name,connection='${NEO4J_CONNECTION}',cypher=query,batch_size=1,read_only='Y' if readonly else 'N',
       retry='N',nr_retries_on_error=0,cypher_from_field='N',unwind='N',returning_graph='N')
    ms=E.SubElement(n,'mappings')
    for f,t in args:child(ms,'mapping',dict(parameter=f,field=f,type=t))
    rs=E.SubElement(n,'returns')
    for f,t in returns:child(rs,'return',dict(name=f,type=t,source_type=t))
    return n

def check(p,previous,field='verified'):
    p.chain(previous,filt('Check graph result',field,'Boolean','Y','Verified','Graph mismatch'),node('Dummy','Verified'))
    p.add(abort('Graph mismatch','Enrichment graph is missing, conflicting, or the human review changed. Re-run the same BATCH_ID after correction.'))
    p.edges.append(('Check graph result','Graph mismatch'))

p=Pipe('graph_constraint','Create a uniqueness constraint for enrichment nodes after inspecting existing constraints.')
p.chain(variables('Start',[('batch_id','${BATCH_ID}','String')]),db('Require enrichment batch',
 "SELECT EXISTS(SELECT 1 FROM enrichment.batch WHERE batch_id=? AND mode='ENRICH') AS valid_batch",[('batch_id','String')]),
 filt('ENRICH only','valid_batch','Boolean','Y','Inspect constraint','Invalid batch'))
p.chain(cypher('Inspect constraint',"""SHOW CONSTRAINTS YIELD name,entityType,type,labelsOrTypes,properties
RETURN count(CASE WHEN entityType='NODE' AND type IN ['UNIQUENESS','NODE_KEY','NODE_PROPERTY_UNIQUENESS'] AND labelsOrTypes=['jobEnrichment'] AND properties=['id'] THEN 1 END)>0 AS correct,
count(CASE WHEN name='jobtology_enrichment_id' THEN 1 END) AS name_in_use""",returns=[('correct','Boolean'),('name_in_use','Integer')],readonly=True),
 filt('Constraint exists','correct','Boolean','Y','Done','Name available'))
p.chain(filt('Name available','name_in_use','Integer','0','Create constraint','Invalid batch'),
 cypher('Create constraint','CREATE CONSTRAINT jobtology_enrichment_id FOR (n:jobEnrichment) REQUIRE n.id IS UNIQUE'),node('Dummy','Done'))
p.edges += [('Constraint exists','Done'),('Constraint exists','Name available'),('Name available','Invalid batch')]
p.add(abort('Invalid batch','A valid ENRICH BATCH_ID is required and the graph constraint name must be compatible.'));p.edges += [('ENRICH only','Invalid batch'),('ENRICH only','Inspect constraint')];p.save()

item_fields=['item_id','batch_id','posting_id','posting_identity','name','source_hash','job_run_id','ncs_run_id','extraction_json','categorization_json','extraction_model','categorization_model','prompt_version','decision']
args=[(f,'String') for f in item_fields]+[('review_id','Integer'),('match_count','Integer')]
p=Pipe('graph_begin','Project reviewed enrichment records; keep partial graph items outside READY.')
p.chain(variables('Batch',[('batch_id_filter','${BATCH_ID}','String')]),db('Reviewed items','SELECT * FROM enrichment.graph_item WHERE batch_id=? ORDER BY item_id',[('batch_id_filter','String')]),
 cypher('Begin enrichment',"""MATCH (p:jobPosting {id:$posting_identity})
MERGE (e:jobEnrichment {id:$item_id})
SET e.name=$name,e.posting_id=$posting_id,e.batch_id=$batch_id,e.source_hash=$source_hash,
 e.job_run_id=$job_run_id,e.ncs_run_id=$ncs_run_id,e.extraction_json=$extraction_json,e.categorization_json=$categorization_json,
 e.extraction_model=$extraction_model,e.categorization_model=$categorization_model,e.prompt_version=$prompt_version,
 e.decision=$decision,e.review_id=$review_id,e.state='LOADING'
MERGE (p)-[:HAS_ENRICHMENT]->(e)
WITH e OPTIONAL MATCH (e)-[r:ALIGNS_WITH_NCS]->()
SET r.accepted=false
RETURN count(DISTINCT e)=1 AS verified""",args,[('verified','Boolean')]))
check(p,'Begin enrichment');p.save()

match_fields=['item_id','competency_identity','competency_code','reason','duty','evidence_field','evidence_quote']
match_args=[(f,'String') for f in match_fields]+[('review_id','Integer'),('duty_index','Integer')]
p=Pipe('graph_matches','Publish evidence-backed duty alignments; these are LLM inferences, not official required competencies.')
p.chain(variables('Batch',[('batch_id','${BATCH_ID}','String')]),db('Accepted matches','SELECT * FROM enrichment.graph_match WHERE batch_id=? ORDER BY item_id,duty_index,competency_code',[('batch_id','String')]),
 cypher('Merge alignment',"""MATCH (e:jobEnrichment {id:$item_id,state:'LOADING',decision:'ACCEPT',review_id:$review_id})
MATCH (c:ncsCompetency {id:$competency_identity})
MERGE (e)-[r:ALIGNS_WITH_NCS {duty_index:$duty_index}]->(c)
SET r.competency_code=$competency_code,r.reason=$reason,r.duty=$duty,r.evidence_field=$evidence_field,
 r.evidence_quote=$evidence_quote,r.accepted=true,r.origin='LLM_INFERENCE',r.review_id=$review_id
RETURN count(r)=1 AS verified""",match_args,[('verified','Boolean')]))
check(p,'Merge alignment');p.save()

p=Pipe('graph_verify_matches','Independently verify every expected competency and evidence property.')
p.chain(variables('Batch',[('batch_id','${BATCH_ID}','String')]),db('Expected matches','SELECT * FROM enrichment.graph_match WHERE batch_id=? ORDER BY item_id,duty_index,competency_code',[('batch_id','String')]),
 cypher('Verify alignment',"""MATCH (e:jobEnrichment {id:$item_id,state:'LOADING',decision:'ACCEPT',review_id:$review_id})
-[r:ALIGNS_WITH_NCS {duty_index:$duty_index,accepted:true}]->(c:ncsCompetency {id:$competency_identity})
WHERE r.competency_code=$competency_code AND r.reason=$reason AND r.duty=$duty AND r.evidence_field=$evidence_field
AND r.evidence_quote=$evidence_quote AND r.origin='LLM_INFERENCE' AND r.review_id=$review_id
RETURN count(r)=1 AS verified""",match_args,[('verified','Boolean')],True))
check(p,'Verify alignment');p.save()

p=Pipe('graph_finish','Verify graph totals and provenance, then checkpoint each reviewed item.')
p.chain(variables('Batch',[('batch_id_filter','${BATCH_ID}','String')]),db('Expected items','SELECT * FROM enrichment.graph_item WHERE batch_id=? ORDER BY item_id',[('batch_id_filter','String')]),
 cypher('Verify and finish enrichment',"""MATCH (p:jobPosting {id:$posting_identity})-[:HAS_ENRICHMENT]->(e:jobEnrichment {id:$item_id,state:'LOADING'})
WHERE e.name=$name AND e.batch_id=$batch_id AND e.posting_id=$posting_id AND e.source_hash=$source_hash
 AND e.job_run_id=$job_run_id AND e.ncs_run_id=$ncs_run_id AND e.extraction_json=$extraction_json
 AND e.categorization_json=$categorization_json AND e.extraction_model=$extraction_model AND e.categorization_model=$categorization_model
 AND e.prompt_version=$prompt_version AND e.review_id=$review_id AND e.decision=$decision
OPTIONAL MATCH (e)-[r:ALIGNS_WITH_NCS {accepted:true}]->()
WITH e,count(r) AS matches WHERE matches=$match_count
SET e.state='READY'
RETURN count(e)=1 AS verified""",args,[('verified','Boolean')]))
p.chain('Verify and finish enrichment',filt('Verified item','verified','Boolean','Y','Save graph checkpoint','Graph mismatch'),
 execute('Save graph checkpoint',"""INSERT INTO enrichment.graph_export(item_id,review_id)
SELECT item_id,review_id FROM enrichment.latest_review WHERE item_id=? AND review_id=?
ON CONFLICT(item_id) DO UPDATE SET review_id=excluded.review_id,exported_at=clock_timestamp()""",['item_id','review_id']),
 db('Check review still current',"SELECT EXISTS(SELECT 1 FROM enrichment.latest_review r JOIN enrichment.graph_export g USING(item_id,review_id) WHERE r.item_id=? AND r.review_id=?) AS review_current",[('item_id','String'),('review_id','Integer')]))
check(p,'Check review still current','review_current');p.edges.append(('Verified item','Graph mismatch'));p.save()
workflow('publish_reviewed.hwf','Publish reviewed job enrichment and NCS alignments',[
 ('BATCH_ID','','Exact ENRICH batch ID. EVAL batches cannot be published.'),('NEO4J_CONNECTION','jobtology-neo4j','Private Hop Neo4j metadata connection.')],
 [('Check batch and constraint','graph_constraint.hpl'),('Load reviewed records','graph_begin.hpl'),('Load accepted NCS alignments','graph_matches.hpl'),
  ('Verify alignment evidence','graph_verify_matches.hpl'),('Verify totals and checkpoint','graph_finish.hpl')],False)

print('Generated native Hop LLM workflows, pipelines, schemas and prompt SQL.')

# Preserve the optional manual-retention writer guard when regenerating publication XML.
if (ROOT / 'hop/retention/tools/build.py').exists():
    import subprocess
    import sys
    subprocess.run([sys.executable, str(ROOT / 'hop/retention/tools/build.py')], check=True)
