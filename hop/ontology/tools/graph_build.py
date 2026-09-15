"""Executed by build.py with the shared native XML helpers. Development only."""
GRAPH_PARAMS=[('RELEASE_ID','','Exact release with assembled and frozen independent reviews.'),
 ('NEO4J_CONNECTION','jobtology-neo4j','Private native Hop Neo4j connection.')]

def result_check(p,previous,name='Verify result'):
 p.chain(previous,filt(name,'verified','Boolean','Y','Verified','Graph mismatch'),node('Dummy','Verified'))
 p.add(abort('Graph mismatch','Ontology graph verification failed. The PostgreSQL active release was not changed. Inspect the log and retry the same release.'))
 p.edges.append((name,'Graph mismatch'))

def remember_load():
 n=node('SetVariable','Remember load',use_formatting='Y')
 child(E.SubElement(n,'fields'),'field',dict(field_name='load_id',variable_name='ONTOLOGY_LOAD_ID',variable_type='PARENT_WORKFLOW',default_value=''))
 return n

def load_input():
 return variables('Load token',[('load_token','${ONTOLOGY_LOAD_ID}','String')])

def load_query(name,extra='',joins='',where=''):
 # Database Join buffers a complete result per input row, even with cache=N.
 # Table Input consumes its ResultSet incrementally. Its sole input field is
 # the load token, passed as a JDBC prepared parameter; no SQL interpolation.
 return node('TableInput',name,connection='jobtology-postgres',sql="SELECT l.load_id,l.release_id,l.database_id,l.manifest_hash,r.manifest->>'data_as_of' AS data_as_of,"
  "(r.manifest->>'nodes')::bigint AS expected_nodes,(r.manifest->>'edges')::bigint AS expected_edges"+extra+
  " FROM ontology.graph_load l JOIN ontology.corpus_release r USING(release_id) "+joins+
  " WHERE l.load_id=? AND l.state='RUNNING' "+where,limit=0,lookup='Load token',execute_each_row='Y',variables_active='N')

def batch_cypher(name,query,args,readonly=False):
 n=cypher(name,query,args,[('verified','Boolean')],readonly)
 put(n,'batch_size',500);put(n,'unwind','Y');put(n,'unwind_map','rows')
 return n

PREFIX="CALL db.info() YIELD id AS actual_database_id\nUNWIND $rows AS row\nWITH row,actual_database_id WHERE row.database_id=actual_database_id\n"

p=Pipe('graph_start','Register one writer for the exact Neo4j database and freeze the graph inventory.')
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 cypher('Read graph database','CALL db.info() YIELD id RETURN id AS database_id',returns=[('database_id','String')],readonly=True),
 db('Create load token','SELECT gen_random_uuid()::text AS load_id'),remember_load(),
 execute('Register graph writer','SELECT ontology.begin_graph_load(?,?,?)',['release_id','database_id','load_id']))
p.save()

p=Pipe('graph_constraint','Inspect and create the ontology object uniqueness constraint.')
p.chain(load_input(),cypher('Inspect constraint',"""SHOW CONSTRAINTS YIELD name,entityType,type,labelsOrTypes,properties
RETURN count(CASE WHEN entityType='NODE' AND type IN ['UNIQUENESS','NODE_KEY','NODE_PROPERTY_UNIQUENESS'] AND labelsOrTypes=['ontologyObject'] AND properties=['id'] THEN 1 END)>0 AS correct,
count(CASE WHEN name='jobtology_ontology_object_id' THEN 1 END) AS name_in_use""",returns=[('correct','Boolean'),('name_in_use','Integer')],readonly=True),
 filt('Constraint exists','correct','Boolean','Y','Done','Name available'))
p.chain(filt('Name available','name_in_use','Integer','0','Create constraint','Conflict'),
 cypher('Create constraint','CREATE CONSTRAINT jobtology_ontology_object_id FOR (n:ontologyObject) REQUIRE n.id IS UNIQUE'),node('Dummy','Done'))
p.add(abort('Conflict','The ontology constraint name is already used by an incompatible constraint.'))
p.edges += [('Constraint exists','Done'),('Constraint exists','Name available'),('Name available','Conflict')]
p.save()

p=Pipe('graph_root','Begin an immutable-manifest graph candidate; retain the authoritative PostgreSQL publication state.')
p.chain(load_input(),load_query('Sealed release'),cypher('Begin graph candidate',"""CALL db.info() YIELD id AS actual_database_id
WITH actual_database_id WHERE actual_database_id=$database_id
MERGE (r:ontologyObject:corpusRelease {id:'release/'+$release_id})
ON CREATE SET r.release_id=$release_id,r.manifest_hash=$manifest_hash,r.data_as_of=$data_as_of,r.name=$release_id
WITH r WHERE r.release_id=$release_id AND r.manifest_hash=$manifest_hash AND r.data_as_of=$data_as_of
SET r.projection_state='LOADING',r.load_id=$load_id,r.database_id=$database_id
RETURN count(r)=1 AS verified""",[(f,'String') for f in ['database_id','release_id','manifest_hash','data_as_of','load_id']],[('verified','Boolean')]))
result_check(p,'Begin graph candidate');p.save()

p=Pipe('graph_nodes','Merge typed ontology object identities and labels in native UNWIND batches.')
p.chain(load_input(),load_query('Expected graph nodes',",n.node_id,n.content_hash,array_to_string(n.labels,'|') AS labels",
 'JOIN ontology.graph_node n ON n.release_id=l.release_id','ORDER BY n.node_id'),
 batch_cypher('Merge graph objects',PREFIX+"""MERGE (n:ontologyObject {id:row.node_id})
ON CREATE SET n.content_hash=row.content_hash
WITH row,n WHERE n.content_hash=row.content_hash
SET n:$(split(row.labels,'|'))
RETURN count(n)=size($rows) AS verified""",[(f,'String') for f in ['database_id','node_id','content_hash','labels']]))
result_check(p,'Merge graph objects');p.save()

p=Pipe('graph_edges','Merge semantic and evidence relationships with explicit release membership.')
p.chain(load_input(),load_query('Expected graph edges',',e.edge_id,e.subject_id,e.predicate,e.object_id,e.content_hash',
 'JOIN ontology.graph_edge e ON e.release_id=l.release_id','ORDER BY e.edge_id'),
 batch_cypher('Merge graph relationships',PREFIX+"""MATCH (a:ontologyObject {id:row.subject_id}),(b:ontologyObject {id:row.object_id})
MERGE (a)-[e:$(row.predicate) {id:row.edge_id}]->(b)
ON CREATE SET e.release_id=row.release_id,e.content_hash=row.content_hash
WITH row,e WHERE e.release_id=row.release_id AND e.content_hash=row.content_hash
RETURN count(e)=size($rows) AS verified""",[(f,'String') for f in ['database_id','release_id','edge_id','subject_id','predicate','object_id','content_hash']]))
result_check(p,'Merge graph relationships');p.save()

# Hop's Neo4j parameter conversion treats an empty String as null. The explicit
# source type lets the native query recover that value without inventing text for
# null/empty-array rows, which have a different value_type.
VALUE="CASE row.value_type WHEN 'integer' THEN toInteger(row.text_value) WHEN 'number' THEN toFloat(row.text_value) WHEN 'boolean' THEN toBoolean(row.text_value) WHEN 'date' THEN date(row.text_value) WHEN 'datetime' THEN datetime(row.text_value) WHEN 'string' THEN coalesce(row.text_value,'') ELSE row.text_value END"
prop_args=[(f,'String') for f in ['database_id','release_id','owner_id','content_hash','key','text_value','value_type','subject_id','predicate','object_id']]+[('ordinal','Integer'),('array_size','Integer')]
for owner in ['NODE','EDGE']:
 for array in [False,True]:
  label=owner.lower()+('_arrays' if array else '_scalars')
  match="MATCH (n:ontologyObject {id:row.owner_id})" if owner=='NODE' else "MATCH (a:ontologyObject {id:row.subject_id})-[n:$(row.predicate) {id:row.owner_id}]->(b:ontologyObject {id:row.object_id}) WHERE n.release_id=row.release_id"
  for reading in [False,True]:
   filename=('verify_' if reading else 'write_')+label
   p=Pipe(filename,('Verify' if reading else 'Write')+' typed ontology '+label+' properties.')
   query=load_query('Expected properties',',p.owner_id,p.content_hash,p.key,p.ordinal,p.array_size,p.text_value,p.value_type,e.subject_id,e.predicate,e.object_id',
    "JOIN ontology.graph_property p ON p.release_id=l.release_id LEFT JOIN ontology.graph_edge e ON e.release_id=p.release_id AND e.edge_id=p.owner_id AND p.owner_type='EDGE'",
    "AND p.owner_type='"+owner+"' AND p.is_array="+str(array).lower()+" ORDER BY p.owner_id,p.key,p.ordinal")
   cy=PREFIX+match+'\nWITH row,n,'+VALUE+' AS expected WHERE n.content_hash=row.content_hash'
   if array:cy+=" AND (n[row.key] IS NULL OR valueType(n[row.key]) STARTS WITH 'LIST<')"
   cy+=' ORDER BY row.owner_id,row.key,row.ordinal\n'
   if not reading:
    if not array:
     cy+="FOREACH (_ IN CASE WHEN n[row.key] IS NULL THEN [1] ELSE [] END | SET n[row.key]=expected)\n"
    else:
     cy+="""FOREACH (_ IN CASE WHEN n[row.key] IS NULL THEN [1] ELSE [] END | SET n[row.key]=[])
FOREACH (_ IN CASE WHEN row.ordinal>=0 AND size(n[row.key])=row.ordinal THEN [1] ELSE [] END | SET n[row.key]=n[row.key]+expected)
"""
   valid="n.content_hash=row.content_hash AND "+(
    "CASE WHEN row.ordinal<0 THEN n[row.key]=[] ELSE n[row.key][row.ordinal]=expected END" if array else "n[row.key]=expected")
   if array and reading:valid+=' AND size(n[row.key])=row.array_size'
   cy+='RETURN count(n)=size($rows) AND all(ok IN collect(coalesce('+valid+',false)) WHERE ok) AS verified'
   p.chain(load_input(),query,batch_cypher('Property operation',cy,prop_args,reading))
   result_check(p,'Property operation');p.save()

p=Pipe('graph_verify_nodes','Verify node identities, exact labels and property cardinality; values are independently checked by property pipelines.')
p.chain(load_input(),load_query('Expected nodes',",n.node_id,n.content_hash,array_to_string(n.labels,'|') AS labels,(SELECT count(*) FROM jsonb_object_keys(n.properties))::bigint AS property_count",
 'JOIN ontology.graph_node n ON n.release_id=l.release_id','ORDER BY n.node_id'),batch_cypher('Verify nodes',PREFIX+"""OPTIONAL MATCH (n:ontologyObject {id:row.node_id})
RETURN count(n)=size($rows) AND all(ok IN collect(coalesce(n.content_hash=row.content_hash AND size(keys(n))=row.property_count+2
 AND size(labels(n))=size(split(row.labels,'|'))+1 AND all(label IN split(row.labels,'|') WHERE label IN labels(n)),false)) WHERE ok) AS verified""",
 [(f,'String') for f in ['database_id','node_id','content_hash','labels']]+[('property_count','Integer')],True))
result_check(p,'Verify nodes');p.save()

p=Pipe('graph_verify_edges','Verify relationship endpoints, predicate, ownership and property cardinality.')
p.chain(load_input(),load_query('Expected relationships',',e.edge_id,e.subject_id,e.predicate,e.object_id,e.content_hash,(SELECT count(*) FROM jsonb_object_keys(e.properties))::bigint AS property_count',
 'JOIN ontology.graph_edge e ON e.release_id=l.release_id','ORDER BY e.edge_id'),batch_cypher('Verify edges',PREFIX+"""OPTIONAL MATCH (a:ontologyObject {id:row.subject_id})-[e:$(row.predicate) {id:row.edge_id}]->(b:ontologyObject {id:row.object_id})
RETURN count(e)=size($rows) AND all(ok IN collect(coalesce(e.release_id=row.release_id AND e.content_hash=row.content_hash
 AND size(keys(e))=row.property_count+3,false)) WHERE ok) AS verified""",
 [(f,'String') for f in ['database_id','release_id','edge_id','subject_id','predicate','object_id','content_hash']]+[('property_count','Integer')],True))
result_check(p,'Verify edges');p.save()

p=Pipe('graph_finish','Verify total membership and checkpoint the graph candidate without activating a serving release.')
p.chain(load_input(),load_query('Expected totals'),cypher('Verify graph scope',"""CALL db.info() YIELD id AS actual_database_id
WITH actual_database_id WHERE actual_database_id=$database_id
MATCH (r:ontologyObject:corpusRelease {id:'release/'+$release_id,manifest_hash:$manifest_hash,load_id:$load_id})
OPTIONAL MATCH (r)-[member:INCLUDES {release_id:$release_id}]->(n)
WITH r,count(member) AS member_count,count(DISTINCT n) AS node_count
OPTIONAL MATCH ()-[edge]->() WHERE edge.release_id=$release_id
WITH r,member_count,node_count,count(edge) AS edge_count
WHERE member_count=$expected_nodes AND node_count=$expected_nodes AND edge_count=$expected_edges
SET r.projection_state='VERIFIED',r.verified_at=datetime()
RETURN count(r)=1 AS verified""",[(f,'String') for f in ['database_id','release_id','manifest_hash','load_id']]+[(f,'Integer') for f in ['expected_nodes','expected_edges']],[('verified','Boolean')]),
 filt('All totals verified','verified','Boolean','Y','Checkpoint graph load','Graph mismatch'),
 execute('Checkpoint graph load','SELECT ontology.finish_graph_load(?,?,?,?)',['load_id','expected_nodes','expected_edges','verified']),
 log('Verified graph candidate',['release_id','load_id','expected_nodes','expected_edges','manifest_hash'],
  'All graph values and memberships verified. Serving activation remains a separate release gate.'))
p.add(abort('Graph mismatch','Ontology membership totals differ; no PostgreSQL graph checkpoint was written.'));p.edges.append(('All totals verified','Graph mismatch'));p.save()
p=Pipe('graph_fail','Release the writer after a caught workflow failure; preserve its failed execution record.')
p.chain(load_input(),execute('Fail this load','SELECT ontology.fail_graph_load(?)',['load_token']));p.save()

steps=[('Register graph candidate','graph_start.hpl'),('Check uniqueness constraint','graph_constraint.hpl'),('Begin graph root','graph_root.hpl'),
 ('Load graph objects','graph_nodes.hpl'),('Load graph relationships','graph_edges.hpl')]
steps += [('Write '+part,'write_'+part+'.hpl') for part in ['node_scalars','node_arrays','edge_scalars','edge_arrays']]
steps += [('Verify '+part,'verify_'+part+'.hpl') for part in ['node_scalars','node_arrays','edge_scalars','edge_arrays']]
steps += [('Verify graph objects','graph_verify_nodes.hpl'),('Verify graph relationships','graph_verify_edges.hpl'),('Verify total membership','graph_finish.hpl')]
workflow('load_release.hwf','Load and verify a sealed ontology graph candidate',GRAPH_PARAMS,steps,False)
w=E.parse(OUT/'load_release.hwf').getroot();actions=w.find('actions');hops=w.find('hops')
sample=next(a for a in actions if a.findtext('type')=='PIPELINE');cleanup=copy.deepcopy(sample)
put(cleanup,'name','Record failed load');put(cleanup,'filename','${PROJECT_HOME}/ontology/graph_fail.hpl');put(cleanup,'xloc',80);put(cleanup,'yloc',720);actions.append(cleanup)
for h in hops:
 if h.findtext('to')=='Abort':put(h,'to','Record failed load')
child(hops,'hop',{'from':'Record failed load','to':'Abort','enabled':'Y','evaluation':'Y','unconditional':'Y'})
save(w,OUT/'load_release.hwf')
