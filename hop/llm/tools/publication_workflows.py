"""Generate native Hop publication of independently accepted NCS links."""
from pathlib import Path
import ast, copy, xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/llm';templates={}
source=(OUT/'tools/build.py').read_text()
for path in (ROOT/'hop/ingestions').rglob('*.hpl'):
 for t in E.parse(path).findall('transform'):templates.setdefault(t.findtext('type'),t)
for d in ast.parse(source).body:
 if isinstance(d,(ast.FunctionDef,ast.ClassDef)) and d.name in {'put','child','node','Pipe','save','variables','db','execute','filt','abort','log','remember','workflow','cypher'}:
  exec(compile(ast.get_source_segment(source,d),__file__,'exec'),globals())

def verify(p,previous):
 p.chain(previous,filt('Verified','verified','Boolean','Y','Done','Mismatch'),node('Dummy','Done'))
 p.add(abort('Mismatch','Reviewed-link projection differs from PostgreSQL. It has not been activated.'));p.edges.append(('Verified','Mismatch'))

def identity():return variables('Publication',[('publication_id','${LINK_PUBLICATION_ID}','String')])

p=Pipe('prepare_link_publication','Freeze independently accepted current extraction and link decisions.')
p.chain(variables('Publication choice',[('publication_id','${PUBLICATION_ID}','String')]),db('Freeze publication and acquire writer','SELECT enrichment.prepare_link_publication(?) AS prepared_id',[('publication_id','String')]),remember('prepared_id','LINK_PUBLICATION_ID'));p.save()
for suffix,label,constraint in [('enrichment','reviewedNcsEnrichment','jobtology_reviewed_ncs_id'),('publication','reviewedNcsPublication','jobtology_reviewed_ncs_publication')]:
 p=Pipe('link_constraint_'+suffix,'Inspect graph constraints before creating one; safe repeated execution.')
 p.chain(identity(),cypher('Inspect existing constraint',"SHOW CONSTRAINTS YIELD name,entityType,type,labelsOrTypes,properties RETURN count(CASE WHEN entityType='NODE' AND type IN ['UNIQUENESS','NODE_KEY','NODE_PROPERTY_UNIQUENESS'] AND labelsOrTypes=['"+label+"'] AND properties=['id'] THEN 1 END)>0 AS correct,count(CASE WHEN name='"+constraint+"' THEN 1 END) AS name_in_use",returns=[('correct','Boolean'),('name_in_use','Integer')],readonly=True),filt('Already installed','correct','Boolean','Y','Done','Name available'))
 p.chain(filt('Name available','name_in_use','Integer','0','Create constraint','Mismatch'),cypher('Create constraint','CREATE CONSTRAINT '+constraint+' FOR (n:'+label+') REQUIRE n.id IS UNIQUE'),node('Dummy','Done'))
 p.add(abort('Mismatch','Existing constraint name has a different definition.'))
 p.edges.extend([('Already installed','Done'),('Already installed','Name available'),('Name available','Mismatch')]);p.save()
p=Pipe('begin_link_publication','Keep the reviewed NCS projection unavailable until fully verified.')
p.chain(identity(),execute('Check frozen review state','SELECT enrichment.check_link_publication(?)',['publication_id']),
 cypher('Begin projection',"""MERGE (m:reviewedNcsPublication {id:'jobtology-reviewed-ncs'})
SET m.state='LOADING',m.publication_id=$publication_id
WITH m OPTIONAL MATCH (e:reviewedNcsEnrichment {managed_by:'jobtology-reviewed-ncs'})
SET e.current=false
WITH m OPTIONAL MATCH (:reviewedNcsEnrichment {managed_by:'jobtology-reviewed-ncs'})-[r:ALIGNS_WITH_NCS]->()
SET r.accepted=false
RETURN count(DISTINCT m)=1 AS verified""",[('publication_id','String')],[('verified','Boolean')]))
verify(p,'Begin projection');p.save()
p=Pipe('load_link_postings','Load accepted extraction revisions with model, source and review provenance.')
p.chain(identity(),db('Frozen postings','SELECT *,payload::text AS payload_json FROM enrichment.link_publication_item WHERE publication_id=? ORDER BY posting_id',[('publication_id','String')]),
 cypher('Merge reviewed extraction',"""MATCH (p:jobPosting {id:$posting_identity})
MERGE (e:reviewedNcsEnrichment {id:$enrichment_id}) SET e:jobEnrichment
SET e.managed_by='jobtology-reviewed-ncs',e.name=$name,e.posting_id=$posting_id,e.payload_json=$payload_json,
e.payload_hash=$payload_hash,e.publication_id=$publication_id,e.current=false
MERGE (p)-[:HAS_ENRICHMENT]->(e)
RETURN count(e)=1 AS verified""",[(x,'String') for x in ['publication_id','posting_id','enrichment_id','posting_identity','name','payload_json','payload_hash']],[('verified','Boolean')]))
verify(p,'Merge reviewed extraction');p.save()
link_query="""SELECT p.publication_id,p.enrichment_id,l->>'candidate_id' AS candidate_id,
'ncs:unit:'||(l->>'competency_code') AS competency_identity,l::text AS evidence_json,
l->>'reason' AS reason,l#>>'{duty,text}' AS duty,l->>'reviewer' AS reviewer,l->>'reviewer_kind' AS reviewer_kind,
(l->>'candidate_origin') AS candidate_origin,(l->>'candidate_actor') AS candidate_actor,
(l->>'decision_id')::bigint AS decision_id FROM enrichment.link_publication_item p
CROSS JOIN LATERAL jsonb_array_elements(p.payload->'links') l WHERE p.publication_id=? ORDER BY p.posting_id,l->>'candidate_id'"""
args=[(x,'String') for x in ['publication_id','enrichment_id','candidate_id','competency_identity','evidence_json','reason','duty','reviewer','reviewer_kind','candidate_origin','candidate_actor']]+[('decision_id','Integer')]
p=Pipe('load_reviewed_links','Merge only independently accepted links to existing versioned NCS units.')
p.chain(identity(),db('Accepted link evidence',link_query,[('publication_id','String')]),cypher('Merge reviewed NCS link',"""MATCH (e:reviewedNcsEnrichment {id:$enrichment_id,publication_id:$publication_id})
MATCH (c:ncsCompetency {id:$competency_identity})
MERGE (e)-[r:ALIGNS_WITH_NCS {candidate_id:$candidate_id}]->(c)
SET r.evidence_json=$evidence_json,r.reason=$reason,r.duty=$duty,r.reviewer=$reviewer,
r.reviewer_kind=$reviewer_kind,r.decision_id=$decision_id,r.accepted=true,
r.candidate_origin=$candidate_origin,r.candidate_actor=$candidate_actor,
r.origin=CASE $candidate_origin WHEN 'model' THEN 'LLM_INFERENCE' ELSE 'REVIEWER_INFERENCE' END,
r.publication_id=$publication_id
RETURN count(r)=1 AS verified""",args,[('verified','Boolean')]))
verify(p,'Merge reviewed NCS link');p.save()
p=Pipe('verify_reviewed_links','Read back every accepted NCS endpoint and evidence property.')
p.chain(identity(),db('Expected links',link_query,[('publication_id','String')]),cypher('Read back NCS evidence',"""MATCH (e:reviewedNcsEnrichment {id:$enrichment_id,publication_id:$publication_id})
-[r:ALIGNS_WITH_NCS {candidate_id:$candidate_id,accepted:true}]->(c:ncsCompetency {id:$competency_identity})
WHERE r.evidence_json=$evidence_json AND r.reason=$reason AND r.duty=$duty AND r.reviewer=$reviewer
AND r.reviewer_kind=$reviewer_kind AND r.decision_id=$decision_id
AND r.candidate_origin=$candidate_origin AND r.candidate_actor=$candidate_actor
AND r.origin=CASE $candidate_origin WHEN 'model' THEN 'LLM_INFERENCE' ELSE 'REVIEWER_INFERENCE' END
AND r.publication_id=$publication_id
RETURN count(r)=1 AS verified""",args,[('verified','Boolean')],True))
verify(p,'Read back NCS evidence');p.save()
p=Pipe('verify_link_postings','Read back each extraction payload and exact accepted link count.')
p.chain(identity(),db('Expected postings',"SELECT *,payload::text AS payload_json,jsonb_array_length(payload->'links')::bigint AS link_count FROM enrichment.link_publication_item WHERE publication_id=? ORDER BY posting_id",[('publication_id','String')]),cypher('Read back extraction',"""MATCH (p:jobPosting {id:$posting_identity})-[:HAS_ENRICHMENT]->(e:reviewedNcsEnrichment {id:$enrichment_id,publication_id:$publication_id})
WHERE e.name=$name AND e.posting_id=$posting_id AND e.payload_json=$payload_json AND e.payload_hash=$payload_hash
AND e.managed_by='jobtology-reviewed-ncs' AND e.current=false
OPTIONAL MATCH (e)-[r:ALIGNS_WITH_NCS {accepted:true}]->()
WITH e,count(r) AS links WHERE links=$link_count RETURN count(e)=1 AS verified""",[(x,'String') for x in ['publication_id','posting_id','enrichment_id','posting_identity','name','payload_json','payload_hash']]+[('link_count','Integer')],[('verified','Boolean')],True))
verify(p,'Read back extraction');p.save()
p=Pipe('finish_link_publication','Check current PostgreSQL decisions before activating the verified graph.')
p.chain(identity(),execute('Confirm source and decisions unchanged','SELECT enrichment.check_link_publication(?)',['publication_id']),db('Expected total','SELECT count(*)::bigint AS posting_count FROM enrichment.link_publication_item WHERE publication_id=?',[('publication_id','String')]),
 cypher('Activate verified projection',"""MATCH (m:reviewedNcsPublication {id:'jobtology-reviewed-ncs',publication_id:$publication_id,state:'LOADING'})
OPTIONAL MATCH (e:reviewedNcsEnrichment {managed_by:'jobtology-reviewed-ncs',publication_id:$publication_id})
WITH m,collect(e) AS nodes WHERE size(nodes)=$posting_count
FOREACH (e IN nodes | SET e.current=true)
SET m.state='READY',m.postings=$posting_count
RETURN count(m)=1 AS verified""",[('publication_id','String'),('posting_count','Integer')],[('verified','Boolean')]))
p.chain('Activate verified projection',filt('Verified','verified','Boolean','Y','Save checkpoint','Mismatch'),execute('Save checkpoint','SELECT enrichment.finish_link_publication(?,true)',['publication_id']))
p.add(abort('Mismatch','Graph totals differ; projection not activated.'));p.edges.append(('Verified','Mismatch'));p.save()
p=Pipe('fail_link_publication','Mark a failed publication unavailable and release its own writer lease.')
p.chain(identity(),cypher('Hide incomplete projection',"MATCH (m:reviewedNcsPublication {id:'jobtology-reviewed-ncs',publication_id:$publication_id}) SET m.state='FAILED'",[('publication_id','String')]),execute('Record failed publication','SELECT enrichment.finish_link_publication(?,false)',['publication_id']));p.save()
workflow('publish_links.hwf','Publish independently reviewed current NCS links',[
 ('PUBLICATION_ID','','Blank creates a fresh publication; replays require unchanged sources and decisions.'),
 ('NEO4J_CONNECTION','jobtology-neo4j','Existing private graph connection.')],[
 ('Freeze accepted links','prepare_link_publication.hpl'),('Ensure extraction uniqueness','link_constraint_enrichment.hpl'),('Ensure publication uniqueness','link_constraint_publication.hpl'),('Begin projection','begin_link_publication.hpl'),
 ('Load accepted extractions','load_link_postings.hpl'),('Load accepted NCS links','load_reviewed_links.hpl'),
 ('Verify link evidence','verify_reviewed_links.hpl'),('Verify extractions','verify_link_postings.hpl'),
 ('Activate verified results','finish_link_publication.hpl')],False)
w=E.parse(OUT/'publish_links.hwf').getroot()
a=copy.deepcopy(w.find("actions/action[type='PIPELINE']"));put(a,'name','Record publication failure');put(a,'filename','${PROJECT_HOME}/llm/fail_link_publication.hpl');w.find('actions').append(a)
for h in w.findall('hops/hop'):
 if h.findtext('to')=='Abort' and h.findtext('from')!='Freeze accepted links':put(h,'to','Record publication failure')
for value in ['Y','N']:child(w.find('hops'),'hop',{'from':'Record publication failure','to':'Abort','enabled':'Y','evaluation':value,'unconditional':'N'})
save(w,OUT/'publish_links.hwf')
workflow('install_link_publication.hwf','Install independent NCS-link publication',[],[],False)
w=E.parse(OUT/'install_link_publication.hwf').getroot();w.find('hops').clear()
child(w.find('actions'),'action',dict(name='Install publication SQL',type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/llm/sql/021_link_publication.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=320,yloc=80,draw='Y',parallel='N'))
for a,b,success in [('Start','Install publication SQL',True),('Install publication SQL','Success',True),('Install publication SQL','Abort',False)]:child(w.find('hops'),'hop',{'from':a,'to':b,'enabled':'Y','evaluation':'Y' if success else 'N','unconditional':'Y' if a=='Start' else 'N'})
save(w,OUT/'install_link_publication.hwf')
workflow('install_linking.hwf','Install duty-only enrichment and reviewed-link publication',[],[],False)
w=E.parse(OUT/'install_linking.hwf').getroot();w.find('hops').clear();previous='Start'
for i,name in enumerate(['003_planning.sql','004_validation.sql','010_independent_review.sql','013_revision_categorization.sql','021_link_publication.sql','022_duty_linking.sql'],1):
 action='Install '+name
 child(w.find('actions'),'action',dict(name=action,type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/llm/sql/'+name,sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=80+i*240,yloc=80,draw='Y',parallel='N'))
 child(w.find('hops'),'hop',{'from':previous,'to':action,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
 child(w.find('hops'),'hop',{'from':action,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'});previous=action
child(w.find('hops'),'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'});save(w,OUT/'install_linking.hwf')

# The smaller installer is maintained alongside the combined installer.
w=E.parse(OUT/'install_linking.hwf').getroot();put(w,'name','Install duty-only NCS linking')
removed='Install 021_link_publication.sql'
for a in list(w.findall('actions/action')):
 if a.findtext('name')==removed:w.find('actions').remove(a)
for h in list(w.findall('hops/hop')):
 if h.findtext('from')==removed:w.find('hops').remove(h)
 elif h.findtext('to')==removed:put(h,'to','Install 022_duty_linking.sql')
save(w,OUT/'install_duty_linking.hwf')
