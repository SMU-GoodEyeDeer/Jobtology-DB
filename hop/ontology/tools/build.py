"""Generate native ontology Hop artifacts; this script is never an ETL runtime step."""
from pathlib import Path
import ast,copy,json,runpy,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'hop/ontology'
runpy.run_path(str(OUT/'tools/requirements_build.py'))
runpy.run_path(str(OUT/'tools/requirements_graph_build.py'))
# Share the existing public XML conventions without executing the LLM generator.
text=(ROOT/'hop/llm/tools/build.py').read_text()
wanted={'put','child','node','Pipe','save','variables','db','execute','log','workflow','filt','abort','cypher'}
for definition in ast.parse(text).body:
 if isinstance(definition,(ast.FunctionDef,ast.ClassDef)) and definition.name in wanted:
  code=ast.get_source_segment(text,definition).replace("'llm-local'","'ontology-local'").replace('/llm/','/ontology/').replace(
   'LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.',
   'Ontology workflow failed. Inspect this execution log and the release or graph-load report.')
  exec(compile(code,str(OUT/'tools/build.py'),'exec'),globals())

def remember_release():
 n=node('SetVariable','Remember release',use_formatting='Y')
 child(E.SubElement(n,'fields'),'field',dict(field_name='pinned_release_id',variable_name='ONTOLOGY_RELEASE_ID',variable_type='PARENT_WORKFLOW',default_value=''))
 return n

PARAMS=[('RELEASE_ID','','Blank creates a new release; repeat with the returned ID to resume the same immutable inputs.')]
SOURCES=[('ALIO_RUN_ID','alio_organization'),('JOB_RUN_ID','job_alio'),('NCS_RUN_ID','ncs_competency'),
 ('QUALIFICATION_RUN_ID','ncs_qualification'),('QNET_RUN_ID','qnet_schedule'),('CAREER_RUN_ID','ncs_career_path')]
PARAMS += [(key,'LATEST','Exact READY FULL source run or LATEST.') for key,_ in SOURCES]
p=Pipe('prepare_release','Freeze six source snapshots and their original record lineage.')
args=[('release_choice','${RELEASE_ID}','String')]+[(key.lower(),'${'+key+'}','String') for key,_ in SOURCES]
choices=','.join("'"+source+"',?::text" for _,source in SOURCES)
p.chain(variables('Release choices',args),db('Freeze source inputs',
 "WITH input AS MATERIALIZED (SELECT coalesce(nullif(?::text,''),gen_random_uuid()::text) AS id,jsonb_build_object("+choices+") AS choices) SELECT id AS pinned_release_id,ontology.prepare_release(id,choices)::text AS prepared FROM input",[(name,kind) for name,_,kind in args]),
 remember_release(),log('Release pinned',['pinned_release_id'],'Pinned source snapshots. PREPARING does not mean published.'))
p.save()
p=Pipe('assemble_sources','Assemble canonical source entities, revisions and grounded relationships.')
p.chain(variables('Release',[('release_id','${ONTOLOGY_RELEASE_ID}','String')]),
 execute('Assemble source backbone','SELECT ontology.assemble_sources(?)',['release_id']),
 db('Read completeness',"SELECT source_id,record_count,supported_records,unaccounted_records FROM ontology.source_coverage WHERE release_id=? ORDER BY source_id",[('release_id','String')]),
 log('Source coverage',['release_id','source_id','record_count','supported_records','unaccounted_records'],'Source assembly complete; enrichment and publication checks remain separate.'))
p.save()
workflow('prepare_release.hwf','Prepare ontology source backbone',PARAMS,
 [('Freeze source inputs','prepare_release.hpl'),('Assemble source entities','assemble_sources.hpl')],False)
p=Pipe('inspect_release','Preview release state and entity counts.',{'RELEASE_ID':''})
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 db('Release report',"SELECT r.release_id,r.state,r.data_as_of,e.kind,count(*) AS entities FROM ontology.corpus_release r JOIN ontology.release_revision m USING(release_id) JOIN ontology.entity e USING(entity_id) WHERE r.release_id=? GROUP BY r.release_id,e.kind ORDER BY e.kind",[('release_id','String')]),node('Dummy','Preview release here'))
p.save()
params=[('RELEASE_ID','','Exact PREPARING release; bind before freezing reviews.'),
 ('INPUT_BUNDLE_IDS','','Pipe-separated immutable bundle IDs, exactly one for every posting in the pinned JOB snapshot.')]
p=Pipe('bind_document_inputs','Select the exact attachment-aware inputs used by this release.')
p.chain(variables('Input choices',[('release_id','${RELEASE_ID}','String'),('bundle_ids','${INPUT_BUNDLE_IDS}','String')]),
 execute('Bind complete posting inputs',"SELECT ontology.bind_document_inputs(?,string_to_array(?,'|'))",['release_id','bundle_ids']),
 log('Inputs bound',['release_id'],'Document input selection is immutable. Review decisions are still separate.'))
p.save()
workflow('bind_document_inputs.hwf','Bind ontology document inputs',params,
 [('Bind selected input bundles','bind_document_inputs.hpl')],False)
for filename,function,description in [
 ('freeze_reviews','freeze_reviews','Freeze extraction and per-link decisions for this release.'),
 ('assemble_claims','assemble_claims','Build reviewed positions, duties, requirements, expression trees, evidence and NCS mappings.'),
 ('verify_claims','verify_claims','Verify reviewed claim membership, source evidence, expressions and NCS targets.')]:
 p=Pipe(filename,description)
 p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
  execute(description,'SELECT ontology.'+function+'(?)',['release_id']),
  log('Completed',['release_id'],description))
 p.save()
workflow('assemble_reviewed.hwf','Assemble independently reviewed ontology claims',
 [('RELEASE_ID','','Existing PREPARING release. Review selection freezes on first execution; later reviews require a new release.')],
 [('Freeze review decisions','freeze_reviews.hpl'),('Assemble reviewed claims','assemble_claims.hpl'),('Verify reviewed projection','verify_claims.hpl')],False)
p=Pipe('inspect_claims','Preview posting outcomes and accepted claim counts.',{'RELEASE_ID':''})
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 db('Claim report','SELECT * FROM ontology.posting_coverage WHERE release_id=? ORDER BY entity_id',[('release_id','String')]),
 node('Dummy','Preview claims here'))
p.save()
exec(compile((OUT/'tools/graph_build.py').read_text(),str(OUT/'tools/graph_build.py'),'exec'),globals())
# Read-only database contracts. Preview is deliberate; no implicit latest draft.
for kind,extra,arguments in [
 ('summary',[],[]),
 ('entities',[('ENTITY_KIND','','Optional entity kind; blank lists all public corpus kinds.'),
              ('PAGE_SIZE','100','1 to 100 entities per page.'),('CURSOR','','Exact next_cursor from the same release and kind.')],
             [('entity_kind','${ENTITY_KIND}','String'),('page_size','${PAGE_SIZE}','Integer'),('cursor_value','${CURSOR}','String')]),
 ('entity',[('ENTITY_ID','','Exact stable entity URI in the selected release.')],[('entity_id','${ENTITY_ID}','String')]),
 ('evidence',[('EVIDENCE_ID','','Exact evidence ID referenced by an accepted claim in this release.')],[('evidence_id','${EVIDENCE_ID}','String')])]:
 params=[('RELEASE_ID','','Exact release ID; blank uses the active published pointer, never the latest draft.')]+extra+[
  ('PREVIEW','N','Y explicitly reads a draft for inspection. N requires a published, non-revoked release.')]
 fields=[('release_id','${RELEASE_ID}','String')]+arguments+[('preview','${PREVIEW}','String')]
 placeholders=['?::text']+[('?::integer' if typ=='Integer' else "nullif(?::text,'')") for _,_,typ in arguments]+[
  "CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"]
 p=Pipe('read_'+kind,'Read a release-scoped JSON contract without changing data.',{key:value for key,value,_ in params})
 p.chain(variables('Read choices',fields),db('Read release JSON',
  'SELECT ontology.query_'+kind+'_v1('+','.join(placeholders)+')::text AS result_json',[(key,typ) for key,_,typ in fields]),
  node('Dummy','Preview JSON here'))
 p.save()
 workflow('read_'+kind+'.hwf','Read ontology '+kind,params,[('Read '+kind,'read_'+kind+'.hpl')],False)
# Export to a fresh managed filename; no caller-controlled shell or filesystem path.
p=Pipe('export_prepare','Allocate a unique export filename. This does not seal or publish a release.')
n=node('SetVariable','Remember export',use_formatting='Y')
child(E.SubElement(n,'fields'),'field',dict(field_name='export_id',variable_name='ONTOLOGY_EXPORT_ID',variable_type='PARENT_WORKFLOW',default_value=''))
p.chain(variables('Export request',[('release_id','${RELEASE_ID}','String')]),
 db('New export ID','SELECT gen_random_uuid()::text AS export_id'),n,
 log('Export destination',['export_id'],'Output: ${PROJECT_HOME}/data/ontology-exports/${ONTOLOGY_EXPORT_ID}.jsonld. Consume only after workflow success and validation.'))
p.save()
p=Pipe('export_jsonld','Serialize the exact sealed inventory as one JSON-LD named graph.')
t=node('TextFileOutput','Write JSON-LD',separator='',enclosure='',enclosure_forced='N',enclosure_fix_disabled='Y',
 header='N',footer='N',format='UNIX',encoding='UTF-8',compression='None',create_parent_folder='Y',
 fileNameInField='N',fileNameField='',endedLine='',ignore_fields='N')
child(t,'file',dict(name='${PROJECT_HOME}/data/ontology-exports/${ONTOLOGY_EXPORT_ID}',extension='jsonld',
 do_not_open_new_file_init='Y',append='N',split='N',haspartno='N',add_date='N',add_time='N',
 add_to_result_filenames='Y',pad='N',fast_dump='N',splitevery=0))
child(E.SubElement(t,'fields'),'field',dict(name='line',type='String',format='',length=-1,precision=-1,trim_type='none'))
p.chain(variables('Export choices',[('release_id','${RELEASE_ID}','String'),('preview','${PREVIEW}','String')]),
 node('TableInput','Read JSON-LD lines',connection='jobtology-postgres',
  sql="SELECT line FROM ontology.export_jsonld_v1(?::text,CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END) ORDER BY line_no",
  limit=0,lookup='Export choices',execute_each_row='Y',variables_active='N'),t)
p.save()
workflow('export_jsonld.hwf','Export a sealed ontology release as JSON-LD',
 [('RELEASE_ID','','Exact sealed release; blank selects only the active published release.'),
  ('PREVIEW','N','Y allows a sealed draft. N requires a published release. Neither mode accepts an unsealed graph.')],
 [('Allocate export filename','export_prepare.hpl'),('Write release JSON-LD','export_jsonld.hpl')],False)
p2=E.parse(OUT/'export_jsonld.hpl').getroot()
put(p2.find('info'),'name','export_jsonld_v2')
for transform in p2.findall('transform'):
 if transform.findtext('type')=='TableInput':put(transform,'sql',transform.findtext('sql').replace('ontology.export_jsonld_v1','ontology.export_jsonld_v2'))
save(p2,OUT/'export_jsonld_v2.hpl')
workflow('export_jsonld_v2.hwf','Export ontology including canonical posting observations',
 [('RELEASE_ID','','Exact sealed release; blank selects only the active published release.'),
  ('PREVIEW','N','Y allows a sealed draft. V2 includes canonical posting states and historical source evidence.')],
 [('Allocate export filename','export_prepare.hpl'),('Write observation-aware JSON-LD','export_jsonld_v2.hpl')],False)
p3=E.parse(OUT/'export_jsonld_v2.hpl').getroot()
put(p3.find('info'),'name','export_jsonld_v3')
for transform in p3.findall('transform'):
 if transform.findtext('type')=='TableInput':put(transform,'sql',transform.findtext('sql').replace('ontology.export_jsonld_v2','ontology.export_jsonld_v3'))
save(p3,OUT/'export_jsonld_v3.hpl')
workflow('export_jsonld_v3.hwf','Export ontology including typed requirements',
 [('RELEASE_ID','','Exact sealed release; blank selects only the active published release.'),
  ('PREVIEW','N','Y allows a sealed draft. V3 distinguishes source groups, normalization proposals and reviewed typed claims.')],
 [('Allocate export filename','export_prepare.hpl'),('Write typed requirement JSON-LD','export_jsonld_v3.hpl')],False)
# Lifecycle capture is source-only. Historical postings remain explicit until
# their canonical revision/claim carry-forward is assembled in a later phase.
p=Pipe('capture_posting_census','Preserve an accepted full posting census without provider or model requests.',{'RUN_ID':''})
p.chain(variables('Snapshot',[('run_id','${RUN_ID}','String')]),
 execute('Capture complete census','SELECT ontology.capture_posting_census_v1(?)',['run_id']),
 log('Census captured',['run_id'],'Accepted full snapshot preserved for observation history.'))
p.save()
workflow('capture_posting_census.hwf','Capture completed posting census',[('RUN_ID','','Exact READY FULL JOB-ALIO snapshot.')],
 [('Capture source census','capture_posting_census.hpl')],False)
p=Pipe('freeze_observations','Freeze lifecycle candidates using the release snapshot and available full observation history.')
p.chain(variables('Observation choices',[('release_id','${RELEASE_ID}','String'),('evaluated_at','${EVALUATED_AT}','String')]),
 execute('Freeze observation history',"SELECT ontology.freeze_observations_v1(?,nullif(?,'')::timestamptz)",['release_id','evaluated_at']),
 log('Observation history frozen',['release_id'],'Inspect current and historical posting outcomes. This does not publish or carry claims into a graph.'))
p.save()
workflow('freeze_observations.hwf','Freeze posting observation states',
 [('RELEASE_ID','','Exact assembled PREPARING and unsealed release.'),('EVALUATED_AT','','Blank freezes the current time; otherwise use an ISO timestamp with explicit UTC offset.')],
 [('Freeze lifecycle candidates','freeze_observations.hpl')],False)
p=Pipe('bind_observations','Bind all observed postings to exact revisions and source evidence before review selection.')
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 execute('Bind canonical observation states','SELECT ontology.bind_observations_v1(?)',['release_id']),
 log('Observations bound',['release_id'],'Historical posting content retained. Review acceptance and release publication remain separate.'))
p.save()
workflow('bind_observations.hwf','Bind canonical posting observations',
 [('RELEASE_ID','','Exact source-assembled PREPARING release; before document input binding or review freeze. Observation time is release creation time.')],
 [('Bind posting history','bind_observations.hpl')],False)
for kind,function in [('observations','query_observations_v1'),('source_health','query_source_health_v1'),('posting_states','query_posting_states_v1')]:
 params=[('RELEASE_ID','','Exact release; blank selects only the active published release.'),('PREVIEW','N','Y explicitly inspects a draft; N requires a published release.')]
 p=Pipe('read_'+kind,'Read lifecycle or operational freshness metadata without changing it.',{k:v for k,v,_ in params})
 p.chain(variables('Read choices',[('release_id','${RELEASE_ID}','String'),('preview','${PREVIEW}','String')]),
  db('Read JSON',"SELECT ontology."+function+"(?::text,CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END)::text AS result_json",[('release_id','String'),('preview','String')]),
  node('Dummy','Preview JSON here'))
 p.save()
 workflow('read_'+kind+'.hwf','Read '+kind,params,[('Read metadata','read_'+kind+'.hpl')],False)
retention=(ROOT/'hop/retention/sql/001_retention.sql').read_text()
start=retention.index('CREATE OR REPLACE FUNCTION retention.protection(')
end=retention.index('END $$;',start)+len('END $$;')
(OUT/'sql/000_retention_dependency.sql').write_text(
 '-- Generated from retention/sql/001_retention.sql. Requires installed manual retention.\n'
 'BEGIN;\nSELECT retention.gate();\n'
 "DO $$ BEGIN IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF; END $$;\n"
 +retention[start:end]+'\nCOMMIT;\n')
operations=(ROOT/'docs/hop-migration/operations.sql').read_text()
start=operations.index('CREATE OR REPLACE FUNCTION ingestion.record_graph_export_v1(')
end=operations.index('END $$;',start)+len('END $$;')
(OUT/'sql/009_refresh_observation_hook.sql').write_text(
 '-- Generated from docs/hop-migration/operations.sql. The source checkpoint extension is optional.\nBEGIN;\n'
 +operations[start:end]+'\nCOMMIT;\n')
checkpoint=E.parse(ROOT/'hop/operations/record_graph_export.hpl').getroot()
for transform in checkpoint.findall('transform'):
 if transform.findtext('type')=='ExecSql':put(transform,'sql','SELECT ingestion.record_graph_export_v1(?)')
save(checkpoint,ROOT/'hop/operations/record_graph_export.hpl')
exec(compile((OUT/'tools/requirements_hop_build.py').read_text(),str(OUT/'tools/requirements_hop_build.py'),'exec'),globals())
workflow('install.hwf','Install ontology ledger and source assembly',[],[],False)
w=E.parse(OUT/'install.hwf').getroot();actions=w.find('actions');hops=w.find('hops');hops.clear();previous='Start'
files=sorted((OUT/'sql').glob('*.sql'))
for i,path in enumerate(files,1):
 name=path.parent.parent.name+' '+path.stem
 child(actions,'action',dict(name=name,type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/'+str(path.relative_to(ROOT/'hop')),sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=80+(i%5)*240,yloc=80+(i//5)*160,draw='Y',parallel='N'))
 child(hops,'hop',{'from':previous,'to':name,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
 child(hops,'hop',{'from':name,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'});previous=name
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'});save(w,OUT/'install.hwf')
for kind in ['pipeline','workflow']:
 source=ROOT/f'hop/metadata/{kind}-run-configuration/llm-local.json'
 conf=json.loads(source.read_text());conf.update(name='ontology-local',description='Native ontology assembly and publication. No execution-data sampling.')
 (source.parent/'ontology-local.json').write_text(json.dumps(conf,indent=2)+'\n')
print('Generated native ontology workflows and run configurations.')
