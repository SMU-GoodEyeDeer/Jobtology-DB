"""Generate native Hop retention XML. Development only; never deployed as runtime code."""
from pathlib import Path
import ast
import copy
import json
import xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'hop/retention'
# Reuse only XML helper definitions, without executing the LLM generator.
source=(ROOT/'hop/llm/tools/build.py').read_text()
tree=ast.parse(source)
names={'put','child','node','Pipe','save','variables','db','execute','filt','abort','remove','log','remember','workflow','cypher'}
helper=ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names],type_ignores=[])
helper_source=ast.unparse(helper).replace('${PROJECT_HOME}/llm/','${PROJECT_HOME}/retention/').replace('llm-local','retention-local').replace('LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.','Retention stopped. Inspect the log and retention.plan_report; resume the same PLAN_ID after correction.')
exec(compile(helper_source,'native_helpers','exec'),globals())

def vars_for(*names):return variables('Options',[(n.lower(),'${'+n+'}','String') for n in names])
def remember_as(field,variable):
 n=remember(field,variable);put(n,'name','Remember '+variable);return n

def assertion(p,previous,field='verified',name='Verify',done='Done'):
 p.chain(previous,filt(name,field,'Boolean','Y',done,'Abort'),node('Dummy',done))
 p.add(abort('Abort','Retention verification failed. Source rows are retained; inspect the log and resume the same PLAN_ID.'))
 p.edges.append((name,'Abort'))

def entry(filename,title,params,steps):workflow(filename,title,params,steps,False)
base=[('RAW_BASE','${PROJECT_HOME}/data','Must equal the preview root. Only standard source/run manifest files under this data folder are supported.')]
plan_params=[('SOURCE_ID','job_alio','One source ID, e.g. job_alio or qnet_schedule.'),
 ('SELECTION_MODE','OLDEST_COUNT','OLDEST_COUNT or OLDER_THAN_DAYS.'),('AMOUNT','1','Number of eligible oldest snapshots, or age in whole 24-hour days.'),
 ('KEEP_LATEST','2','Keep at least this many newest accepted snapshots for this source; minimum 1.')]+base
p=Pipe('preview','Save an immutable candidate list; no source rows, raw files or graph data are deleted.')
p.chain(vars_for('SOURCE_ID','SELECTION_MODE','AMOUNT','KEEP_LATEST','RAW_BASE'),db('New plan ID','SELECT gen_random_uuid()::text AS plan_id'),remember_as('plan_id','PLAN_ID'),
 execute('Save deletion preview','SELECT retention.preview(?,?,?,?::integer,?::integer,?)',['plan_id','source_id','selection_mode','amount','keep_latest','raw_base']),
 db('Preview totals','SELECT state,selected_runs,skipped_runs,source_records_to_prune,raw_files_to_delete,raw_bytes_to_delete FROM retention.plan_report WHERE plan_id=?',[('plan_id','String')]),
 log('Plan summary',['plan_id','state','selected_runs','skipped_runs','source_records_to_prune','raw_files_to_delete','raw_bytes_to_delete'],'PREVIEW ONLY. Inspect this PLAN_ID before running execute.hwf.'))
p.save()
entry('preview.hwf','Preview manual snapshot retention',plan_params,[('Create immutable preview','preview.hpl'),('List selected and protected runs','inspect_plan.hpl')])
p=Pipe('inspect_plan','Preview the last transform for selected snapshots and protection reasons.',{'PLAN_ID':''})
p.chain(vars_for('PLAN_ID'),db('Snapshot decisions','SELECT run_id,source_id,created_at,selected,reason,record_count,document_count,raw_bytes,graph_deleted FROM retention.plan_run WHERE plan_id=? ORDER BY created_at,run_id',[('plan_id','String')]),
 log('Snapshot decision',['run_id','created_at','selected','reason','record_count','raw_bytes'],'Retention plan decision'),node('Dummy','Preview decisions here'));p.save()

p=Pipe('begin_execution','Acquire the maintenance fence and revalidate the exact preview. Concurrent writers or stale plans stop here.')
p.chain(vars_for('PLAN_ID','RAW_BASE'),db('New executor ID','SELECT gen_random_uuid()::text AS owner_id'),remember_as('owner_id','RETENTION_OWNER_ID'),
 execute('Recheck and acquire fence','SELECT retention.begin_execution(?,?,?)',['plan_id','owner_id','raw_base']))
p.save()
for filename,function in [('archive','archive'),('finish','finish'),('release_executor','release_executor')]:
 p=Pipe(filename,'Retention '+function+' checkpoint.')
 p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),execute('Apply '+function,'SELECT retention.'+function+'(?,?)',['plan_id','retention_owner_id']));p.save()
# archive() is not called for a completed plan, so repeating execute.hwf is a clean no-op.
p=E.parse(OUT/'archive.hpl').getroot()
for t in p.findall('transform'):
 if t.findtext('type')=='ExecSql':put(t,'sql',"SELECT retention.archive(?,?) WHERE EXISTS(SELECT 1 FROM retention.plan WHERE plan_id=? AND state='ACTIVE')");child(t.find('arguments'),'argument',dict(name='plan_id'))
save(p,OUT/'archive.hpl')

p=Pipe('graph_target','Verify a retained source batch in the configured graph and pin the physical database identity.')
p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Expected retained graph batch',"SELECT graph_anchor_run_id,source_id FROM retention.plan WHERE plan_id=? AND owner_id=? AND state='ACTIVE'",[('plan_id','String'),('retention_owner_id','String')]),
 cypher('Verify graph database',"""OPTIONAL MATCH (b:ingestionBatch {id:$graph_anchor_run_id})
WITH count(CASE WHEN b.source_id=$source_id AND b.state='READY' AND b.serving_scope='STAGING' THEN 1 END)=1 AS anchor_valid
CALL db.info() YIELD id RETURN anchor_valid,id AS graph_database_id""",[('graph_anchor_run_id','String'),('source_id','String')],[('anchor_valid','Boolean'),('graph_database_id','String')],True),
 filt('Expected graph only','anchor_valid','Boolean','Y','Pin graph database','Abort'),
 execute('Pin graph database','SELECT retention.bind_graph(?,?,?)',['plan_id','retention_owner_id','graph_database_id']))
p.add(abort('Abort','The configured Neo4j database does not contain the retained source batch. No snapshots may be deleted.'))
p.edges.append(('Expected graph only','Abort'));p.save()

archive_read="""SELECT a.archive_id,a.source_id,a.source_record_id,a.run_id,a.archive_hash,
 a.graph_payload->>'kind' AS kind,a.graph_payload->>'name' AS name,a.graph_payload->>'facts_json' AS facts_json,
 a.source_created_at::text AS source_created_at,jsonb_array_length(a.graph_references)::bigint AS expected_refs
FROM retention.archive_record a JOIN retention.plan p USING(plan_id)
WHERE a.plan_id=? AND p.state='ACTIVE' AND p.owner_id=? ORDER BY archive_id"""
fields=['archive_id','source_id','source_record_id','run_id','archive_hash','kind','name','facts_json','source_created_at']
args=[(f,'String') for f in fields]+[('expected_refs','Integer')]
for kind in ('archive_nodes','verify_archive'):
 p=Pipe(kind,'Preserve and verify last-known graph source facts before removing historical batches.')
 p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Archived facts',archive_read,[('plan_id','String'),('retention_owner_id','String')]))
 if kind=='archive_nodes':
  query="""MERGE (a:archivedRecord {id:$archive_id})
SET a.source_id=$source_id,a.source_record_id=$source_record_id,a.source_run_id=$run_id,a.archive_hash=$archive_hash,
 a.kind=$kind,a.name=$name,a.facts_json=$facts_json,a.source_created_at=$source_created_at,a.state='LOADING'
WITH a OPTIONAL MATCH (a)-[r:REFERS_TO]->() DELETE r
RETURN count(DISTINCT a)=1 AS verified"""
 else:
  query="""MATCH (a:archivedRecord {id:$archive_id}) WHERE a.source_id=$source_id AND a.source_record_id=$source_record_id
AND a.source_run_id=$run_id AND a.archive_hash=$archive_hash AND a.facts_json=$facts_json
AND coalesce(a.name,'')=coalesce($name,'') AND coalesce(a.kind,'')=coalesce($kind,'') AND a.source_created_at=$source_created_at
OPTIONAL MATCH (a)-[r:REFERS_TO]->() WITH a,count(r) AS refs WHERE refs=$expected_refs
SET a.state='READY' RETURN count(a)=1 AS verified"""
 p.chain('Archived facts',cypher('Archive graph facts',query,args,[('verified','Boolean')]))
 assertion(p,'Archive graph facts');p.save()
p=Pipe('archive_references','Preserve last-known facts references; shared business identities must already exist.')
p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Archived references',"""SELECT archive_id,x->>'identity_id' AS identity_id,x->>'field' AS field
FROM retention.archive_record a JOIN retention.plan p USING(plan_id)
CROSS JOIN LATERAL jsonb_array_elements(graph_references) x
WHERE a.plan_id=? AND p.state='ACTIVE' AND p.owner_id=? ORDER BY archive_id,field,identity_id""",[('plan_id','String'),('retention_owner_id','String')]),
 cypher('Preserve identity reference',"""MATCH (a:archivedRecord {id:$archive_id,state:'LOADING'}) WITH a MATCH (e:entity {id:$identity_id})
MERGE (a)-[r:REFERS_TO {field:$field}]->(e) RETURN count(r)=1 AS verified""",[(x,'String') for x in ('archive_id','identity_id','field')],[('verified','Boolean')]))
assertion(p,'Preserve identity reference');p.save()

p=Pipe('graph_constraints','Inspect before creating the archive identity constraint.')
p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Active execution',"SELECT plan_id AS active_plan FROM retention.plan WHERE plan_id=? AND owner_id=? AND state='ACTIVE'",[('plan_id','String'),('retention_owner_id','String')]),
 cypher('Inspect archive constraint',"""SHOW CONSTRAINTS YIELD name,entityType,type,labelsOrTypes,properties
RETURN count(CASE WHEN entityType='NODE' AND type IN ['UNIQUENESS','NODE_KEY','NODE_PROPERTY_UNIQUENESS'] AND labelsOrTypes=['archivedRecord'] AND properties=['id'] THEN 1 END)>0 AS correct,
count(CASE WHEN name='jobtology_archive_id' THEN 1 END) AS name_in_use""",returns=[('correct','Boolean'),('name_in_use','Integer')],readonly=True),
 filt('Constraint exists','correct','Boolean','Y','Done','Name available'))
p.chain(filt('Name available','name_in_use','Integer','0','Create constraint','Abort'),cypher('Create constraint','CREATE CONSTRAINT jobtology_archive_id FOR (n:archivedRecord) REQUIRE n.id IS UNIQUE'),node('Dummy','Done'))
p.add(abort('Abort','Archive constraint name is already in use with a different definition.'))
p.edges += [('Constraint exists','Done'),('Constraint exists','Name available'),('Name available','Abort')];p.save()

p=Pipe('delete_graph','Delete only selected ingestionBatch and ingestionRecord nodes. Keep shared entities, enrichment and archives.')
p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Selected graph batches',"""SELECT r.run_id,r.source_id,r.record_count FROM retention.plan_run r JOIN retention.plan p USING(plan_id)
WHERE r.plan_id=? AND p.owner_id=? AND p.state='ACTIVE' AND r.selected AND NOT r.graph_deleted ORDER BY r.created_at,r.run_id""",[('plan_id','String'),('retention_owner_id','String')]),
 cypher('Check deletion ownership',"""OPTIONAL MATCH (b:ingestionBatch {id:$run_id})
OPTIONAL MATCH (b)-[:HAS_RECORD]->(r:ingestionRecord)
WITH b,collect(r) AS records
RETURN (b IS NULL OR (b.source_id=$source_id AND b.state='READY' AND b.serving_scope='STAGING' AND size(records)=$record_count
AND all(r IN records WHERE r.id STARTS WITH 'hop:'+$run_id+':' AND NOT r:entity AND NOT r:jobEnrichment
AND NOT EXISTS { MATCH (other:ingestionBatch)-[:HAS_RECORD]->(r) WHERE other<>b }))) AS verified""",[('run_id','String'),('source_id','String'),('record_count','Integer')],[('verified','Boolean')],True),
 filt('Owned snapshot only','verified','Boolean','Y','Delete historical graph batch','Abort'))
p.chain(cypher('Delete historical graph batch',"""OPTIONAL MATCH (b:ingestionBatch {id:$run_id})
OPTIONAL MATCH (b)-[:HAS_RECORD]->(r:ingestionRecord)
WITH b,collect(r) AS records FOREACH (r IN records | DETACH DELETE r)
DETACH DELETE b RETURN true AS deleted""",[('run_id','String')],[('deleted','Boolean')]),node('Dummy','Deletion submitted'))
p.edges += [('Owned snapshot only','Delete historical graph batch'),('Owned snapshot only','Abort')]
p.add(abort('Abort','Graph ownership/count verification failed; nothing outside the selected source batch may be deleted.'));p.save()

# A workflow boundary is required here. Neo4j Cypher emits output rows from inside
# its transaction callback; a downstream transform could read before commit.
p=Pipe('verify_deleted_graph','Verify graph deletion after the preceding pipeline has completed and committed.')
p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Selected graph batches',"""SELECT r.run_id FROM retention.plan_run r JOIN retention.plan p USING(plan_id)
WHERE r.plan_id=? AND p.owner_id=? AND p.state='ACTIVE' AND r.selected AND NOT r.graph_deleted ORDER BY r.created_at,r.run_id""",[('plan_id','String'),('retention_owner_id','String')]),
 cypher('Verify removed graph batch',"""OPTIONAL MATCH (b:ingestionBatch {id:$run_id})
WITH count(b) AS batches OPTIONAL MATCH (r:ingestionRecord) WHERE r.id STARTS WITH 'hop:'+$run_id+':'
WITH batches,count(r) AS records RETURN batches=0 AND records=0 AS graph_absent""",[('run_id','String')],[('graph_absent','Boolean')],True),
 filt('Graph absent','graph_absent','Boolean','Y','Save graph checkpoint','Abort'),
 execute('Save graph checkpoint','SELECT retention.mark_graph(?,?,?)',['plan_id','retention_owner_id','run_id']))
p.edges.append(('Graph absent','Abort'))
p.add(abort('Abort','Graph deletion was not verified after commit; resume this exact PLAN_ID.'));p.save()

p=Pipe('delete_files','Remove exact manifest files only. Missing files are safe on retry; empty directories are retained.')
p.chain(vars_for('PLAN_ID','RETENTION_OWNER_ID'),db('Approved manifest files',"""SELECT f.run_id,f.document_id,f.raw_path,f.raw_sha256 FROM retention.plan_file f JOIN retention.plan p USING(plan_id)
WHERE f.plan_id=? AND p.owner_id=? AND p.state='ACTIVE' AND f.deleted_at IS NULL
AND NOT EXISTS(SELECT 1 FROM retention.plan_run r WHERE r.plan_id=p.plan_id AND r.selected AND NOT r.graph_deleted)
ORDER BY f.run_id,f.document_id""",[('plan_id','String'),('retention_owner_id','String')]),
 node('FileExists','Inspect exact file',filenamefield='raw_path',resultfieldname='file_exists',includefiletype='Y',filetypefieldname='file_type',addresultfilenames='N'),
 filt('File present','file_exists','Boolean','Y','Regular file only','Deletion checkpoint fields'))
hash_node=node('Calculator','Rehash exact file',failIfNoFile='Y')
child(hash_node,'calculation',dict(field_name='actual_hash',calc_type='SHA256',field_a='raw_path',value_type='String',value_length=-1,value_precision=-1,remove='N'))
p.chain(filt('Regular file only','file_type','String','file','Rehash exact file','Abort'),hash_node,
 db('Compare raw hash','SELECT lower(?::text)=?::text AS same_hash',[('actual_hash','String'),('raw_sha256','String')]),
 filt('Original file only','same_hash','Boolean','Y','Delete exact file','Abort'),
 node('ProcessFiles','Delete exact file',operation_type='delete',sourcefilenamefield='raw_path',targetfilenamefield='',simulate='N',createparentfolder='N',overwritetargetfile='N',addresultfilenames='N'))
keep=node('SelectValues','Deletion checkpoint fields');fs=E.SubElement(keep,'fields');put(fs,'select_unspecified','N')
for f in ('plan_id','retention_owner_id','run_id','document_id','raw_path'):child(fs,'field',dict(name=f))
p.chain('Delete exact file',keep,
 node('FileExists','Check file removed',filenamefield='raw_path',resultfieldname='still_exists',includefiletype='N',addresultfilenames='N'),
 filt('File absent','still_exists','Boolean','N','Save file checkpoint','Abort'))
p.chain(execute('Save file checkpoint','SELECT retention.mark_file(?,?,?,?)',['plan_id','retention_owner_id','run_id','document_id']))
p.add(abort('Abort','Expected an unchanged regular local snapshot file; hash or deletion verification failed.'))
p.edges += [('File present','Regular file only'),('File present','Deletion checkpoint fields'),('Regular file only','Abort'),('Original file only','Abort'),('File absent','Save file checkpoint'),('File absent','Abort')];p.save()

entry('execute.hwf','Execute or resume a reviewed retention plan',[('PLAN_ID','','Exact saved preview ID; no candidate selection happens during execution.')]+base+[('NEO4J_CONNECTION','jobtology-neo4j','Existing private graph connection.')],
 [('Revalidate plan and fence writers','begin_execution.hpl'),('Verify Neo4j database','graph_target.hpl'),('Archive last-known source records','archive.hpl'),('Check archive constraint','graph_constraints.hpl'),
 ('Archive graph records','archive_nodes.hpl'),('Archive graph references','archive_references.hpl'),('Verify graph archive','verify_archive.hpl'),
 ('Delete selected graph snapshots','delete_graph.hpl'),('Verify committed graph deletions','verify_deleted_graph.hpl'),('Delete selected raw files','delete_files.hpl'),('Commit PostgreSQL cleanup','finish.hpl'),('Report result','report.hpl')])
w=E.parse(OUT/'execute.hwf').getroot()
for h in w.findall('hops/hop'):
 if h.findtext('to')=='Abort':put(h,'to','Release failed executor')
a=copy.deepcopy(w.find('actions/action[type="PIPELINE"]'));put(a,'name','Release failed executor');put(a,'filename','${PROJECT_HOME}/retention/release_executor.hpl');put(a,'yloc',560)
w.find('actions').append(a)
for outcome in ('Y','N'):child(w.find('hops'),'hop',{'from':'Release failed executor','to':'Abort','enabled':'Y','evaluation':outcome,'unconditional':'N'})
save(w,OUT/'execute.hwf')
p=Pipe('report','Log the durable retention result.')
p.chain(vars_for('PLAN_ID'),db('Result','SELECT state,phase,owner_id,last_error,selected_runs,raw_files_to_delete,raw_bytes_to_delete FROM retention.plan_report WHERE plan_id=?',[('plan_id','String')]),
 log('Retention result',['plan_id','state','phase','owner_id','last_error','selected_runs','raw_files_to_delete','raw_bytes_to_delete'],'Source snapshot retention result. Last-known records are in retention.last_known_record.'));p.save()

p=Pipe('cancel_plan','Cancel only an unexecuted preview.')
p.chain(vars_for('PLAN_ID'),execute('Cancel preview','SELECT retention.cancel(?)',['plan_id']));p.save()
entry('cancel_plan.hwf','Cancel an unexecuted retention plan',[('PLAN_ID','','Saved PLANNED preview ID.')],[('Cancel preview','cancel_plan.hpl')])
p=Pipe('recover_stopped_run','Release a stale executor or writer only after confirming its workflow has stopped.')
p.chain(vars_for('PLAN_ID','OWNER_ID','RECOVERY_KIND','CONFIRM_STOPPED'),execute('Release stopped process','SELECT retention.recover(?,?,?,?)',['plan_id','owner_id','recovery_kind','confirm_stopped']));p.save()
entry('recover_stopped_run.hwf','Recover a stopped retention or graph workflow',[
 ('PLAN_ID','','Active retention plan; ignored for WRITER recovery.'),('OWNER_ID','','Exact stale owner_id or writer_id from PostgreSQL.'),
 ('RECOVERY_KIND','EXECUTOR','EXECUTOR releases ownership but keeps maintenance active; WRITER removes a stale graph lease.'),
 ('CONFIRM_STOPPED','','Enter STOPPED only after checking the old process cannot still run.')],[('Release stopped process','recover_stopped_run.hpl')])

# Shared leases guard manual and scheduled source-graph entry points.
p=Pipe('enter_graph_writer','Register an active graph writer before it reads or mutates any graph batch.')
p.chain(variables('Writer options',[('target','${RUN_ID}','String')]),db('Writer identity','SELECT gen_random_uuid()::text AS writer_id'),remember_as('writer_id','RETENTION_WRITER_ID'),
 execute('Enter graph writer',"SELECT retention.enter_writer(?,'SOURCE_GRAPH',?)",['writer_id','target']));p.save()
p=Pipe('enter_llm_graph_writer','Register the exact enrichment batch before publishing derived graph records.')
p.chain(variables('Writer options',[('target','${BATCH_ID}','String')]),db('Writer identity','SELECT gen_random_uuid()::text AS writer_id'),remember_as('writer_id','RETENTION_WRITER_ID'),
 execute('Enter graph writer',"SELECT retention.enter_writer(?,'LLM_GRAPH',?)",['writer_id','target']));p.save()
p=Pipe('leave_graph_writer','Release only this workflow writer lease on success or handled failure.')
p.chain(vars_for('RETENTION_WRITER_ID'),execute('Leave graph writer','SELECT retention.leave_writer(?)',['retention_writer_id']));p.save()

def guard_workflow(path):
 w=E.parse(path).getroot()
 if any(a.findtext('name')=='Enter retention writer guard' for a in w.findall('actions/action')):
  if path.name=='publish_reviewed.hwf':
   put(w.find('actions/action[name="Enter retention writer guard"]'),'filename','${PROJECT_HOME}/retention/enter_llm_graph_writer.hpl');save(w,path)
  return
 actions=w.find('actions');hops=w.find('hops');start=next(a.findtext('name') for a in actions if a.findtext('start')=='Y')
 success=next(a.findtext('name') for a in actions if a.findtext('type')=='SUCCESS')
 stop=next(a.findtext('name') for a in actions if a.findtext('type')=='ABORT')
 original=next(h.findtext('to') for h in hops if h.findtext('from')==start)
 for h in hops:
  if h.findtext('from')==start:put(h,'to','Enter retention writer guard')
  if h.findtext('to')==success:put(h,'to','Leave retention writer guard')
  if h.findtext('to')==stop:put(h,'to','Release failed graph writer')
 for name,file in [('Enter retention writer guard','enter_graph_writer.hpl'),('Leave retention writer guard','leave_graph_writer.hpl'),('Release failed graph writer','leave_graph_writer.hpl')]:
  a=copy.deepcopy(actions.find('action[type="PIPELINE"]'));put(a,'name',name);put(a,'filename','${PROJECT_HOME}/retention/'+('enter_llm_graph_writer.hpl' if name=='Enter retention writer guard' and path.name=='publish_reviewed.hwf' else file));put(a,'run_configuration','retention-local');put(a,'yloc',650);actions.append(a)
 for a,b,yes in [('Enter retention writer guard',original,True),('Enter retention writer guard','Release failed graph writer',False),('Leave retention writer guard',success,True),('Leave retention writer guard',stop,False),('Release failed graph writer',stop,True),('Release failed graph writer',stop,False)]:
  child(hops,'hop',{'from':a,'to':b,'enabled':'Y','evaluation':'Y' if yes else 'N','unconditional':'N'})
 save(w,path)
guard_workflow(ROOT/'hop/graph/load_snapshot.hwf')
# Publishing enrichment never deletes entities, but also participates in the writer fence.
guard_workflow(ROOT/'hop/llm/publish_reviewed.hwf')

for kind in ('pipeline','workflow'):
 path=ROOT/f'hop/metadata/{kind}-run-configuration/retention-local.json'
 conf=json.loads((ROOT/f'hop/metadata/{kind}-run-configuration/llm-local.json').read_text())
 conf['name']='retention-local';conf['description']='Manual retention; local native Hop, no sampling. Basic logging.'
 path.write_text(json.dumps(conf,indent=2)+'\n')
# Native SQL action runs DDL as a script, never as a Table Input query.
(OUT/'sql/000_operations.sql').write_text((ROOT/'docs/hop-migration/operations.sql').read_text())
w=E.parse(ROOT/'hop/llm/install.hwf').getroot();put(w,'name','Install manual retention support')
for a in list(w.find('actions')):
 if a.findtext('type')=='SQL':w.find('actions').remove(a)
hops=w.find('hops');hops.clear()
a=child(w.find('actions'),'action',dict(name='Install retention SQL',type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/retention/sql/001_retention.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=320,yloc=80,draw='Y',parallel='N'))
child(w.find('actions'),'action',dict(name='Install scheduler maintenance hook',type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/retention/sql/000_operations.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=80,yloc=240,draw='Y',parallel='N'))
for a,b,e in [('Start','Install scheduler maintenance hook','Y'),('Install scheduler maintenance hook','Install retention SQL','Y'),('Install scheduler maintenance hook','Abort','N'),('Install retention SQL','Success','Y'),('Install retention SQL','Abort','N')]:child(hops,'hop',{'from':a,'to':b,'enabled':'Y','evaluation':e,'unconditional':'Y' if a=='Start' else 'N'})
save(w,OUT/'install.hwf')
print('Generated manual native Hop retention workflows and writer guards.')
