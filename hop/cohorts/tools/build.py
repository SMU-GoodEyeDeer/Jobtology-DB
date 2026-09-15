"""Generate native Hop duplicate-review artifacts; never a runtime ETL step."""
from pathlib import Path
import ast
import json
import runpy
import xml.etree.ElementTree as E

ROOT=Path(__file__).resolve().parents[3]; OUT=ROOT/'hop/cohorts'
def text(nullable=False, enum=None):
    result=dict(type=['string','null'] if nullable else 'string',minLength=1,maxLength=8000)
    if enum:result['enum']=enum+([None] if nullable else [])
    return result
fields=dict(schema_version=text(enum=['hop-duplicate-proposal-v1']),release_id=text(),cluster_id=text(),parent_id=text(True),
    member_ids=dict(type='array',minItems=2,maxItems=1000,items=text()),source_binding_hash=text(),
    actor=text(),actor_kind=text(enum=['human','assistant']),method=text(enum=['MANUAL','MODEL_INFERRED']),
    model_id=text(True),prompt_version=text(True),resolver_version=text(),reason=text())
schema=dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
(OUT/'schemas/duplicate-proposal-v1.schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n')
compact=json.dumps(schema,ensure_ascii=False,separators=(',',':'))
(OUT/'sql/001_duplicate_contract.sql').write_text('''BEGIN;
CREATE TABLE IF NOT EXISTS ontology.duplicate_contract(version text PRIMARY KEY,schema jsonb NOT NULL,content_hash text NOT NULL);
INSERT INTO ontology.duplicate_contract SELECT 'hop-duplicate-proposal-v1',s,ontology.hash(s)
FROM (SELECT $schema$'''+compact+'''$schema$::jsonb s) x ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.duplicate_contract WHERE version='hop-duplicate-proposal-v1'
  AND schema=$schema$'''+compact+'''$schema$::jsonb AND content_hash=ontology.hash(schema))
 THEN RAISE EXCEPTION 'DUPLICATE_CONTRACT_CHANGED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.duplicate_contract'::regclass AND tgname='ontology_duplicate_contract_immutable') THEN
  CREATE TRIGGER ontology_duplicate_contract_immutable BEFORE UPDATE OR DELETE ON ontology.duplicate_contract
  FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;
COMMIT;
''')
runpy.run_path(str(OUT/'tools/profile_contract.py'))

source=(ROOT/'hop/llm/tools/build.py').read_text()
for definition in ast.parse(source).body:
    if isinstance(definition,(ast.FunctionDef,ast.ClassDef)) and definition.name in {'put','child','node','Pipe','save','variables','db','execute','log','workflow'}:
        code=ast.get_source_segment(source,definition).replace("'llm-local'","'ontology-local'").replace('/llm/','/cohorts/').replace(
            'LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.',
            'Cohort preparation failed. Inspect the native execution log; no failed import is partially committed.')
        exec(compile(code,str(__file__),'exec'),globals())

params=[('PROPOSAL_FILE','${PROJECT_HOME}/duplicate-proposal.json','Exact UTF-8 JSON proposal from read_duplicate_input; no API key.')]
p=Pipe('import_duplicate','Import a source-bound duplicate proposal without accepting it.',{k:v for k,v,_ in params})
reader=node('LoadFileInput','Read exact proposal bytes',IsInFields='Y',DynamicFilenameField='proposal_file',
    IsIgnoreEmptyFile='N',IsIgnoreMissingPath='N',encoding='UTF-8',addresultfile='N',limit=0)
child(E.SubElement(reader,'fields'),'field',dict(name='proposal_bytes',element_type='content',type='Binary',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Proposal file',[('proposal_file','${PROPOSAL_FILE}','String')]),reader,
    db('Capture duplicate proposal','SELECT ontology.import_duplicate_v1(?::bytea) AS proposal_id',[('proposal_bytes','Binary')]),
    log('Proposal stored',['proposal_id'],'Proposal only. Independent review and release freezing remain separate.'))
p.save();workflow('import_duplicate.hwf','Import duplicate proposal',params,[('Import proposal','import_duplicate.hpl')],False)

params=[('REVIEW_ID','','New UUID; reuse only to retry the identical review.'),('PROPOSAL_ID','','Exact current proposal ID.'),
    ('DECISION','REJECT','ACCEPT or REJECT.'),('REVIEWER','','Actual independent reviewer identity.'),
    ('REVIEWER_KIND','human','human or assistant; record the actual kind.'),('NOTES','','Evidence-based explanation of the decision.')]
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in params]
p=Pipe('review_duplicate','Append an independent, idempotent duplicate decision.',{k:v for k,v,_ in params})
p.chain(variables('Review details',fields),db('Save independent review',
    'SELECT ontology.decide_duplicate_v1(?::uuid,?::text,?::text,?::text,?::text,?::text) AS decision_id',[(k,t) for k,_,t in fields]),
    log('Review saved',['decision_id'],'No source posting is merged or deleted. Existing releases retain their selected review.'))
p.save();workflow('review_duplicate.hwf','Review duplicate proposal',params,[('Record decision','review_duplicate.hpl')],False)

params=[('RELEASE_ID','','Exact assembled, unsealed draft release.')]
p=Pipe('freeze_duplicates','Freeze duplicate decisions and one group assignment per source posting.',{k:v for k,v,_ in params})
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
    execute('Freeze duplicate membership','SELECT ontology.freeze_duplicates_v1(?)',['release_id']),
    log('Duplicate membership frozen',['release_id'],'Source identities are preserved. Cohort selection and graph/publication integration remain separate.'))
p.save();workflow('freeze_duplicates.hwf','Freeze duplicate membership',params,[('Freeze selected groups','freeze_duplicates.hpl')],False)

for name,extra,args,sql_args in [
    ('duplicate_input',[('CLUSTER_ID','','Stable UUID for this group or correction family.'),
                        ('MEMBER_IDS','','Two or more exact posting identities separated by |; the template sorts them.')],
     [('cluster_id','${CLUSTER_ID}','String'),('member_ids','${MEMBER_IDS}','String')],
     ['?::uuid',"string_to_array(nullif(?::text,''),'|')"]),
    ('duplicates',[],[],[])]:
    params=[('RELEASE_ID','','Exact release; blank uses only the active published release.')]+extra+[
        ('PREVIEW','N','Y explicitly reads a draft. Failed/revoked releases remain unavailable.')]
    fields=[('release_id','${RELEASE_ID}','String')]+args+[('preview','${PREVIEW}','String')]
    p=Pipe('read_'+name,'Read duplicate source bindings or frozen membership.',{k:v for k,v,_ in params})
    p.chain(variables('Read choices',fields),db('Read duplicate JSON','SELECT ontology.query_'+name+'_v1('+','.join(
        ['?::text']+sql_args+["CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"])+')::text AS result_json',[(k,t) for k,_,t in fields]),
        node('Dummy','Preview JSON here'))
    p.save();workflow('read_'+name+'.hwf','Read '+name,params,[('Read '+name,'read_'+name+'.hpl')],False)

exec(compile((OUT/'tools/profile_workflows.py').read_text(),str(OUT/'tools/profile_workflows.py'),'exec'),globals())

w=E.Element('workflow');put(w,'name','Install cohort preparation ledger');actions=E.SubElement(w,'actions');hops=E.SubElement(w,'hops')
child(actions,'action',dict(name='Start',type='SPECIAL',start='Y',repeat='N',xloc=80,yloc=80,draw='Y'));previous='Start'
for i,path in enumerate(sorted((OUT/'sql').glob('*.sql')),1):
    name=path.stem
    child(actions,'action',dict(name=name,type='SQL',connection='jobtology-postgres',sql='',sqlfromfile='Y',
        sqlfilename='${PROJECT_HOME}/cohorts/sql/'+path.name,sqlfilename_encoding='UTF-8',useVariableSubstitution='N',
        sendOneStatement='Y',xloc=80+260*(i%5),yloc=80+180*(i//5),draw='Y'))
    child(hops,'hop',{'from':previous,'to':name,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
    child(hops,'hop',{'from':name,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'});previous=name
child(actions,'action',dict(name='Success',type='SUCCESS',xloc=80,yloc=80+180*((i+5)//5),draw='Y'))
child(actions,'action',dict(name='Abort',type='ABORT',message='Cohort preparation installation failed; inspect SQL action log.',xloc=1120,yloc=80+180*((i+5)//5),draw='Y'))
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'});save(w,OUT/'install.hwf')
exec(compile((OUT/'tools/cohort_workflows.py').read_text(),str(OUT/'tools/cohort_workflows.py'),'exec'),globals())
