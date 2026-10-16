"""Executed by build.py with shared native XML helpers; development only."""
GRAPH_PARAMS=[('RELEASE_ID','','Exact sealed release; older current projection replay is refused.'),
 ('NEO4J_CONNECTION','jobtology-neo4j','Private native Hop Neo4j connection.')]

def result_check(p,previous,name='Verify result'):
 p.chain(previous,filt(name,'verified','Boolean','Y','Verified','Graph mismatch'),node('Dummy','Verified'))
 p.add(abort('Graph mismatch','Flat ontology verification failed; PostgreSQL history is unchanged.'))
 p.edges.append((name,'Graph mismatch'))

def remember_load():
 n=node('SetVariable','Remember load',use_formatting='Y')
 child(E.SubElement(n,'fields'),'field',dict(field_name='load_id',variable_name='ONTOLOGY_LOAD_ID',variable_type='PARENT_WORKFLOW',default_value=''))
 return n

def load_input():
 return variables('Load token',[('load_token','${ONTOLOGY_LOAD_ID}','String')])

def load_query(name,extra='',joins='',where=''):
 return node('TableInput',name,connection='jobtology-postgres',sql="SELECT l.load_id,l.release_id,l.database_id,l.manifest_hash,l.source_manifest_hash,r.manifest->>'data_as_of' AS data_as_of,"
  "projection.node_count AS expected_nodes,projection.edge_count AS expected_edges,"
  "(projection.manifest->>'bindings')::bigint AS legacy_nodes,"
  "(projection.manifest->>'legacy_edges')::bigint AS legacy_edges"+extra+
  " FROM ontology.flat_graph_load l JOIN ontology.flat_graph_projection projection USING(release_id) JOIN ontology.corpus_release r USING(release_id) "+joins+
  " WHERE l.load_id=? AND l.state IN ('RUNNING','STAGED') "+where,limit=0,lookup='Load token',execute_each_row='Y',variables_active='N')

def batch_cypher(name,query,args,readonly=False):
 n=cypher(name,query,args,[('verified','Boolean')],readonly)
 put(n,'batch_size',500);put(n,'unwind','Y');put(n,'unwind_map','rows')
 return n

PREFIX="CALL db.info() YIELD id AS actual_database_id\nUNWIND $rows AS row\nWITH row,actual_database_id WHERE row.database_id=actual_database_id\n"
p=Pipe('graph_start','Register the exact flat projection writer without changing original release history.')
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 cypher('Read graph database','CALL db.info() YIELD id RETURN id AS database_id',returns=[('database_id','String')],readonly=True),
 db('Create load token','SELECT gen_random_uuid()::text AS load_id'),remember_load(),
 execute('Register graph writer','SELECT ontology.begin_flat_graph_load(?,?,?)',['release_id','database_id','load_id']))
p.save()
p=Pipe('graph_resume','Resume final verification of the exact staged token.')
p.chain(variables('Staged token',[('load_id','${LOAD_ID}','String')]),
 db('Require staged token',"SELECT ontology.resume_flat_graph_load(?) AS load_id",[('load_id','String')]),remember_load())
p.save()
p=Pipe('graph_constraint','Inspect and create ontology object uniqueness.')
p.chain(load_input(),cypher('Inspect constraint',"""SHOW CONSTRAINTS YIELD name,entityType,type,labelsOrTypes,properties
RETURN count(CASE WHEN entityType='NODE' AND type IN ['UNIQUENESS','NODE_KEY','NODE_PROPERTY_UNIQUENESS'] AND labelsOrTypes=['ontologyObject'] AND properties=['id'] THEN 1 END)>0 AS correct,
count(CASE WHEN name='jobtology_ontology_object_id' THEN 1 END) AS name_in_use""",returns=[('correct','Boolean'),('name_in_use','Integer')],readonly=True),
 filt('Constraint exists','correct','Boolean','Y','Done','Name available'))
p.chain(filt('Name available','name_in_use','Integer','0','Create constraint','Conflict'),
 cypher('Create constraint','CREATE CONSTRAINT jobtology_ontology_object_id FOR (n:ontologyObject) REQUIRE n.id IS UNIQUE'),node('Dummy','Done'))
p.add(abort('Conflict','Incompatible ontology constraint.'))
p.edges += [('Constraint exists','Done'),('Constraint exists','Name available'),('Name available','Conflict')];p.save()
p=Pipe('graph_root','Preserve the original release root; current flat proof lives separately in PostgreSQL.')
p.chain(load_input(),load_query('Sealed release'),cypher('Check graph root',"""CALL db.info() YIELD id AS actual_database_id
WITH actual_database_id WHERE actual_database_id=$database_id
MERGE (r:ontologyObject:corpusRelease {id:'release/'+$release_id})
ON CREATE SET r.release_id=$release_id,r.manifest_hash=$source_manifest_hash,r.data_as_of=$data_as_of,r.name=$release_id
RETURN count(r)=1 AND all(ok IN collect(coalesce(r.release_id=$release_id AND
 r.manifest_hash=$source_manifest_hash AND r.data_as_of=$data_as_of,false)) WHERE ok) AS verified""",[(f,'String') for f in ['database_id','release_id','source_manifest_hash','data_as_of']],[('verified','Boolean')]))
result_check(p,'Check graph root');p.save()
p=Pipe('graph_nodes','Merge canonical identities, retain their baseline fields, and remove only stale flat-owned keys.')
p.chain(load_input(),load_query('Expected graph nodes',",n.node_id,n.content_hash,n.flat_content_hash,array_to_string(n.labels,'|') AS labels,"
 "array_to_string(ARRAY(SELECT jsonb_object_keys(n.owned_properties) ORDER BY 1),'|') AS owned_keys,'ontologyEntity'=ANY(n.labels) AS managed,"
 "previous_node.node_id IS NOT NULL AS has_previous,previous_node.flat_content_hash AS previous_flat_content_hash,"
 "array_to_string(ARRAY(SELECT jsonb_object_keys(previous_node.owned_properties) ORDER BY 1),'|') AS previous_owned_keys",
 "JOIN ontology.flat_graph_node n ON n.release_id=l.release_id LEFT JOIN LATERAL ("
 " SELECT old.release_id FROM ontology.flat_graph_load old WHERE old.database_id=l.database_id AND old.state='VERIFIED'"
 " ORDER BY old.finished_at DESC,old.load_id DESC LIMIT 1) previous_load ON true"
 " LEFT JOIN ontology.flat_graph_node previous_node ON previous_node.release_id=previous_load.release_id AND previous_node.node_id=n.node_id",'ORDER BY n.node_id'),
 batch_cypher('Merge graph objects',PREFIX+"""MERGE (n:ontologyObject {id:row.node_id})
ON CREATE SET n.content_hash=row.content_hash
WITH row,n,CASE WHEN coalesce(row.owned_keys,'')='' THEN [] ELSE split(row.owned_keys,'|') END AS owned,
 CASE WHEN coalesce(row.previous_owned_keys,'')='' THEN [] ELSE split(row.previous_owned_keys,'|') END AS previous_owned
WHERE n.content_hash=row.content_hash AND
 (NOT row.managed OR (((NOT row.has_previous AND n.flat_content_hash IS NULL AND n.flat_owned_keys IS NULL) OR
  (n.flat_content_hash=row.flat_content_hash AND n.flat_owned_keys=owned) OR
  (row.has_previous AND n.flat_content_hash=row.previous_flat_content_hash AND n.flat_owned_keys=previous_owned)) AND
 all(k IN coalesce(n.flat_owned_keys,[]) WHERE NOT k IN ['id','content_hash','entity_id','kind','code','scheme_id','flat_content_hash','flat_owned_keys']) AND
 all(k IN owned WHERE n[k] IS NULL OR k IN coalesce(n.flat_owned_keys,[]))))
FOREACH (k IN CASE WHEN row.managed THEN [k IN coalesce(n.flat_owned_keys,[]) WHERE NOT k IN owned] ELSE [] END | SET n[k]=null)
FOREACH (_ IN CASE WHEN row.managed THEN [1] ELSE [] END | SET n.flat_content_hash=row.flat_content_hash,n.flat_owned_keys=owned)
SET n:$(split(row.labels,'|'))
RETURN count(n)=size($rows) AS verified""",[(f,'String') for f in ['database_id','node_id','content_hash','flat_content_hash','labels','owned_keys','previous_flat_content_hash','previous_owned_keys']]+[('managed','Boolean'),('has_previous','Boolean')]))
result_check(p,'Merge graph objects');p.save()
p=Pipe('graph_edges','Merge flat semantic/evidence edges; unaffected edges retain their original statement IDs.')
p.chain(load_input(),load_query('Expected graph edges',',e.edge_id,e.subject_id,e.predicate,e.object_id,e.content_hash',
 'JOIN ontology.flat_graph_edge e ON e.release_id=l.release_id','ORDER BY e.edge_id'),
 batch_cypher('Merge graph relationships',PREFIX+"""MATCH (a:ontologyObject {id:row.subject_id})
WITH row,a MATCH (b:ontologyObject {id:row.object_id})
MERGE (a)-[e:$(row.predicate) {id:row.edge_id}]->(b)
ON CREATE SET e.release_id=row.release_id,e.content_hash=row.content_hash
WITH row,e WHERE e.release_id=row.release_id AND e.content_hash=row.content_hash
RETURN count(e)=size($rows) AS verified""",[(f,'String') for f in ['database_id','release_id','edge_id','subject_id','predicate','object_id','content_hash']]))
result_check(p,'Merge graph relationships');p.save()
VALUE="CASE property.value_type WHEN 'integer' THEN toInteger(property.text_value) WHEN 'number' THEN toFloat(property.text_value) WHEN 'boolean' THEN toBoolean(property.text_value) WHEN 'date' THEN date(property.text_value) WHEN 'datetime' THEN datetime(property.text_value) WHEN 'string' THEN property.text_value ELSE null END"
prop_args=[(f,'String') for f in ['database_id','release_id','owner_id','content_hash','property_data','subject_id','predicate','object_id']]+[('property_rows','Integer')]

def grouped_property_query(query):
 # Hop 2.19's native Cypher mapping supports primitives, not nested maps. Keep
 # the established PostgreSQL type renderer, transport complete owners using a
 # six-field tuple, then decode inside Cypher. Escape percent first and decode it
 # last: even literal "%7C"/"%25" and arbitrary Unicode round-trip exactly.
 sql=query.findtext('sql')
 encode=lambda field:"replace(replace(coalesce("+field+",''),'%','%25'),'|','%7C')"
 tuple_sql="||'|'||".join([encode('key'),'value_type','is_owned::text','ordinal::text','array_size::text',encode('text_value')])
 columns='database_id,release_id,owner_id,content_hash,subject_id,predicate,object_id'
 put(query,'sql','SELECT '+columns+',count(*)::bigint AS property_rows, string_agg('+tuple_sql+",'|' ORDER BY key,ordinal) AS property_data FROM ("+sql+') expected GROUP BY '+columns+' ORDER BY owner_id')
 return query

PROPERTY_DECODE="""WITH row,split(row.property_data,'|') AS fields
WHERE row.property_rows>0 AND size(fields)=row.property_rows*6
WITH row,[i IN range(0,size(fields)-1,6) | {
 key:replace(replace(fields[i],'%7C','|'),'%25','%'),value_type:fields[i+1],
 is_owned:fields[i+2]='true',ownership_valid:fields[i+2] IN ['true','false'],
 ordinal:toInteger(fields[i+3]),array_size:toInteger(fields[i+4]),
 text_value:replace(replace(fields[i+5],'%7C','|'),'%25','%')}] AS properties
WHERE all(property IN properties WHERE property.ownership_valid AND property.ordinal IS NOT NULL AND property.array_size IS NOT NULL
 AND property.value_type IN ['integer','number','boolean','date','datetime','string','null','empty_array'])
"""
PROPERTY_EQUAL="CASE WHEN property.expected IS NULL THEN n[property.key] IS NULL WHEN property.is_empty THEN n[property.key]=[] AND valueType(n[property.key]) STARTS WITH 'LIST<' ELSE n[property.key]=property.expected AND valueType(n[property.key])=valueType(property.expected) END"
ARRAY_PREFIX="size(n[property.key])<size(property.expected) AND all(i IN range(0,size(n[property.key])-1) WHERE n[property.key][i]=property.expected[i] AND valueType(n[property.key][i])=valueType(property.expected[i]))"
for legacy in [False,True]:
 for owner in ['NODE','EDGE']:
  for array in [False,True]:
   label=owner.lower()+('_arrays' if array else '_scalars')
   for reading in ([True] if legacy else [False,True]):
    filename=('verify_legacy_' if legacy else ('verify_' if reading else 'write_'))+label
    p=Pipe(filename,('Verify' if reading else 'Write')+' typed flat ontology '+label+'.')
    table='flat_graph_legacy_property' if legacy else 'flat_graph_property'
    edges='flat_graph_legacy_edge' if legacy else 'flat_graph_edge'
    owned='false' if legacy else "coalesce(jsonb_exists(n.owned_properties,p.key),false)"
    query=load_query('Expected properties',',p.owner_id,p.content_hash,p.key,p.ordinal,p.array_size,p.text_value,p.value_type,e.subject_id,e.predicate,e.object_id,'+owned+' AS is_owned',
     "JOIN ontology."+table+" p ON p.release_id=l.release_id LEFT JOIN ontology."+edges+" e ON e.release_id=p.release_id AND e.edge_id=p.owner_id AND p.owner_type='EDGE'"+
     (" LEFT JOIN ontology.flat_graph_node n ON n.release_id=p.release_id AND n.node_id=p.owner_id AND p.owner_type='NODE'" if not legacy else ''),
     "AND p.owner_type='"+owner+"' AND p.is_array="+str(array).lower()+" ORDER BY p.owner_id,p.key,p.ordinal")
    query=grouped_property_query(query)
    match="MATCH (n:ontologyObject {id:row.owner_id})" if owner=='NODE' else "MATCH (a:ontologyObject {id:row.subject_id}) USING INDEX SEEK a:ontologyObject(id) WITH row,properties,a MATCH (b:ontologyObject {id:row.object_id}) USING INDEX SEEK b:ontologyObject(id) WITH row,properties,a,b MATCH (a)-[n:$(row.predicate) {id:row.owner_id}]->(b) WHERE n.release_id=row.release_id"
    cy=PREFIX+PROPERTY_DECODE+match+'\nWITH row,n,properties WHERE n.content_hash=row.content_hash\nUNWIND properties AS property\n'
    if array:
     cy+='WITH row,n,property,'+VALUE+''' AS expected ORDER BY row.owner_id,property.key,property.ordinal
WITH row,n,property.key AS key,property.is_owned AS is_owned,property.array_size AS array_size,
 collect({ordinal:property.ordinal,value_type:property.value_type,expected:expected}) AS elements
WITH row,n,{key:key,is_owned:is_owned,is_empty:array_size=0,
 expected:[element IN elements WHERE element.ordinal>=0 | element.expected],
 valid_shape:CASE WHEN array_size=0 THEN size(elements)=1 AND elements[0].ordinal=-1 AND elements[0].value_type='empty_array'
 ELSE array_size>0 AND size(elements)=array_size AND all(i IN range(0,size(elements)-1) WHERE elements[i].ordinal=i AND elements[i].expected IS NOT NULL) END} AS property
WITH row,n,collect(property) AS expected_properties
WHERE all(property IN expected_properties WHERE property.valid_shape AND (n[property.key] IS NULL OR valueType(n[property.key]) STARTS WITH 'LIST<'))
'''
    else:
     cy+='WITH row,n,property,'+VALUE+''' AS expected
WITH row,n,collect({key:property.key,is_owned:property.is_owned,is_empty:false,expected:expected,
 valid_shape:property.ordinal=-1 AND property.array_size=-1 AND property.value_type<>'empty_array' AND (property.value_type='null' OR expected IS NOT NULL)}) AS expected_properties
WHERE all(property IN expected_properties WHERE property.valid_shape)
'''
    if not reading:
     # An unchanged write is avoided only after full typed target comparison;
     # source hashes alone never authorize skipping an independent verifier.
     # Older element-at-a-time writers may have committed a correct immutable
     # prefix. Preserve their safe resume path, checking every existing element
     # and its actual type before replacing that prefix with the complete list.
     can_write="property.is_owned OR n[property.key] IS NULL"+(' OR ('+ARRAY_PREFIX+')' if array else '')
     cy+="FOREACH (property IN [property IN expected_properties WHERE ("+can_write+") AND NOT coalesce("+PROPERTY_EQUAL+",false)] | SET n[property.key]=property.expected)\n"
    cy+='RETURN count(n)=size($rows) AND count(DISTINCT row.owner_id)=size($rows) AND all(ok IN collect(coalesce(n.content_hash=row.content_hash AND all(property IN expected_properties WHERE '+PROPERTY_EQUAL+'),false)) WHERE ok) AS verified'
    p.chain(load_input(),query,batch_cypher('Property operation',cy,prop_args,reading));result_check(p,'Property operation');p.save()
for legacy in [False,True]:
 table='flat_graph_legacy_node' if legacy else 'flat_graph_node'
 name='graph_verify_legacy_nodes' if legacy else 'graph_verify_nodes'
 extra="n.node_id,n.content_hash,array_to_string(n.labels,'|') AS labels,(SELECT count(*) FROM jsonb_object_keys(n.properties))::bigint AS property_count"
 extra+=(",false AS managed,''::text AS flat_content_hash,''::text AS owned_keys" if legacy else
 ", 'ontologyEntity'=ANY(n.labels) AS managed,n.flat_content_hash,array_to_string(ARRAY(SELECT jsonb_object_keys(n.owned_properties) ORDER BY 1),'|') AS owned_keys")
 p=Pipe(name,'Verify exact native node labels, typed property ownership and content proof.')
 p.chain(load_input(),load_query('Expected nodes',','+extra,'JOIN ontology.'+table+' n ON n.release_id=l.release_id','ORDER BY n.node_id'),
 batch_cypher('Verify nodes',PREFIX+"""OPTIONAL MATCH (n:ontologyObject {id:row.node_id})
RETURN count(n)=size($rows) AND all(ok IN collect(coalesce(n.content_hash=row.content_hash AND
 size(keys(n))=row.property_count+CASE WHEN row.managed THEN 4 ELSE 2 END AND
 (NOT row.managed OR (n.flat_content_hash=row.flat_content_hash AND n.flat_owned_keys=CASE WHEN coalesce(row.owned_keys,'')='' THEN [] ELSE split(row.owned_keys,'|') END)) AND
 size(labels(n))=size(split(row.labels,'|'))+1 AND all(label IN split(row.labels,'|') WHERE label IN labels(n)),false)) WHERE ok) AS verified""",
 [(f,'String') for f in ['database_id','node_id','content_hash','flat_content_hash','labels','owned_keys']]+[('property_count','Integer'),('managed','Boolean')],True))
 result_check(p,'Verify nodes');p.save()
 table='flat_graph_legacy_edge' if legacy else 'flat_graph_edge'
 name='graph_verify_legacy_edges' if legacy else 'graph_verify_edges'
 p=Pipe(name,'Verify exact native relationships and properties.')
 p.chain(load_input(),load_query('Expected relationships',',e.edge_id,e.subject_id,e.predicate,e.object_id,e.content_hash,(SELECT count(*) FROM jsonb_object_keys(e.properties))::bigint AS property_count',
 'JOIN ontology.'+table+' e ON e.release_id=l.release_id','ORDER BY e.edge_id'),batch_cypher('Verify edges',PREFIX+"""OPTIONAL MATCH (a:ontologyObject {id:row.subject_id})-[e:$(row.predicate) {id:row.edge_id}]->(b:ontologyObject {id:row.object_id})
RETURN count(e)=size($rows) AND all(ok IN collect(coalesce(e.release_id=row.release_id AND e.content_hash=row.content_hash AND size(keys(e))=row.property_count+3,false)) WHERE ok) AS verified""",
 [(f,'String') for f in ['database_id','release_id','edge_id','subject_id','predicate','object_id','content_hash']]+[('property_count','Integer')],True))
 result_check(p,'Verify edges');p.save()
for staged in [False,True]:
 name='graph_stage' if staged else 'graph_finish'
 p=Pipe(name,'Stage exact flat and legacy inventories.' if staged else 'Verify full flat scope and zero revision nodes.')
 legacy_scope="""OPTIONAL MATCH (legacy) WHERE 'entityRevision' IN labels(legacy) OR any(label IN labels(legacy) WHERE label ENDS WITH 'Revision')
WITH r,member_count,node_count,edge_count,count(legacy) AS revision_count
WHERE revision_count=$legacy_nodes AND member_count=$expected_nodes+$legacy_nodes AND node_count=$expected_nodes+$legacy_nodes AND edge_count=$expected_edges+$legacy_edges
""" if staged else """OPTIONAL MATCH (legacy) WHERE 'entityRevision' IN labels(legacy) OR any(label IN labels(legacy) WHERE label ENDS WITH 'Revision')
WITH r,member_count,node_count,edge_count,count(legacy) AS revision_count
WHERE revision_count=0 AND member_count=$expected_nodes AND node_count=$expected_nodes AND edge_count=$expected_edges
"""
 p.chain(load_input(),load_query('Expected totals'),cypher('Verify graph scope',"""CALL db.info() YIELD id AS actual_database_id
WITH actual_database_id WHERE actual_database_id=$database_id
MATCH (r:ontologyObject:corpusRelease {id:'release/'+$release_id})
OPTIONAL MATCH (r)-[member:INCLUDES {release_id:$release_id}]->(n)
WITH r,count(member) AS member_count,count(DISTINCT n) AS node_count
OPTIONAL MATCH ()-[edge]->() WHERE edge.release_id=$release_id
WITH r,member_count,node_count,count(edge) AS edge_count
"""+legacy_scope+"RETURN count(r)=1 AS verified",[(f,'String') for f in ['database_id','release_id']]+[(f,'Integer') for f in ['expected_nodes','expected_edges','legacy_nodes','legacy_edges']],[('verified','Boolean')]),
 filt('All totals verified','verified','Boolean','Y','Checkpoint graph load','Graph mismatch'),
 execute('Checkpoint graph load','SELECT ontology.'+('stage' if staged else 'finish')+'_flat_graph_load(?,?,?,?)',['load_id','expected_nodes','expected_edges','verified']),
 log('Verified flat projection',['release_id','load_id','expected_nodes','expected_edges','manifest_hash'],'Flat projection '+('STAGED; legacy removal and final verification remain required.' if staged else 'VERIFIED; PostgreSQL releases and history are unchanged.')))
 p.add(abort('Graph mismatch','Flat projection totals or revision-node checks failed.'));p.edges.append(('All totals verified','Graph mismatch'));p.save()
p=Pipe('graph_fail','Fail only the exact flat load and release its writer.')
p.chain(load_input(),execute('Fail this load','SELECT ontology.fail_flat_graph_load(?)',['load_token']));p.save()
writing=[('Register graph candidate','graph_start.hpl'),('Check uniqueness constraint','graph_constraint.hpl'),('Check release root','graph_root.hpl'),('Load graph objects','graph_nodes.hpl'),('Load graph relationships','graph_edges.hpl')]
writing += [('Write '+part,'write_'+part+'.hpl') for part in ['node_scalars','node_arrays','edge_scalars','edge_arrays']]
checking=[('Verify '+part,'verify_'+part+'.hpl') for part in ['node_scalars','node_arrays','edge_scalars','edge_arrays']]
checking += [('Verify graph objects','graph_verify_nodes.hpl'),('Verify graph relationships','graph_verify_edges.hpl')]
legacy_check=[('Verify legacy '+part,'verify_legacy_'+part+'.hpl') for part in ['node_scalars','node_arrays','edge_scalars','edge_arrays']]
legacy_check += [('Verify legacy revision objects','graph_verify_legacy_nodes.hpl'),('Verify legacy relationships','graph_verify_legacy_edges.hpl')]
for filename,params,steps in [
 ('load_release.hwf',GRAPH_PARAMS,writing+checking+[('Verify total membership','graph_finish.hpl')]),
 ('stage_flat_release.hwf',GRAPH_PARAMS,writing+checking+legacy_check+[('Verify staging totals','graph_stage.hpl')]),
 ('finalize_flat_release.hwf',[('LOAD_ID','','Exact STAGED load token.'),GRAPH_PARAMS[1]],[('Resume staged token','graph_resume.hpl')]+checking+[('Verify final membership','graph_finish.hpl')])]:
 workflow(filename,'Native flat ontology '+filename.removesuffix('.hwf'),params,steps,False)
 w=E.parse(OUT/filename).getroot();actions=w.find('actions');hops=w.find('hops')
 sample=next(a for a in actions if a.findtext('type')=='PIPELINE');cleanup=copy.deepcopy(sample)
 put(cleanup,'name','Record failed load');put(cleanup,'filename','${PROJECT_HOME}/ontology/graph_fail.hpl');put(cleanup,'xloc',80);put(cleanup,'yloc',880);actions.append(cleanup)
 for h in hops:
  if h.findtext('to')=='Abort':put(h,'to','Record failed load')
 child(hops,'hop',{'from':'Record failed load','to':'Abort','enabled':'Y','evaluation':'Y','unconditional':'Y'})
 save(w,OUT/filename)
workflow('install_flat_graph.hwf','Install additive flat ontology projection',[],[],False)
w=E.parse(OUT/'install_flat_graph.hwf').getroot();actions=w.find('actions');hops=w.find('hops');hops.clear();previous='Start'
for stem in ['028_flat_graph_projection','029_flat_catalog_compatibility']:
 child(actions,'action',dict(name=stem,type='SQL',connection='jobtology-postgres',sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/ontology/sql/'+stem+'.sql',sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',xloc=320,yloc=80,draw='Y',parallel='N'))
 child(hops,'hop',{'from':previous,'to':stem,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
 child(hops,'hop',{'from':stem,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'});previous=stem
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'});save(w,OUT/'install_flat_graph.hwf')
