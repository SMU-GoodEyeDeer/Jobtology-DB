"""Native Neo4j + independently reconstructed JSON-LD v5 in private fixtures."""
from pathlib import Path
from decimal import Decimal
import importlib.util
import json
import runpy
import subprocess
import uuid
import occupations
import run

def check(native):
    spec=importlib.util.spec_from_file_location('occupation_neo_fixture',run.ROOT/'hop/ontology/tests/graph.py')
    neo=importlib.util.module_from_spec(spec);spec.loader.exec_module(neo)
    neo.NEO='jobtology-occupation-neo-'+uuid.uuid4().hex[:10]
    spec=importlib.util.spec_from_file_location('occupation_export_validator',run.ROOT/'ontology/tools/validate.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    from rdflib import Namespace,RDF,Literal,URIRef,BNode
    from rdflib.collection import Collection
    JT=Namespace('urn:jobtology:vocab:1:')
    sql,q,err=run.sql,run.q,run.expect_error
    try:
        neo.boot_neo();neo.neo("CREATE (:Person {id:'occupation-private-person',name:'Keep private data'})")
        connection=native.WORK/'project/metadata/neo4j-connection/jobtology-neo4j.json';connection.parent.mkdir(exist_ok=True)
        connection.write_text(json.dumps(dict(name='jobtology-neo4j',server=neo.NEO,databaseName='neo4j',boltPort='7687',username='neo4j',password='test-auth-disabled',
            automatic=False,routing=False,usingEncryption=False,manualUrls=['bolt://'+neo.NEO+':7687'],connectionTimeout='10000',maxTransactionRetryTime='0')))
        run.cmd(['docker','exec','-u','root',native.HOP,'mkdir','-p',native.REMOTE+'/project/metadata/neo4j-connection'])
        run.cmd(['docker','cp',str(connection),native.HOP+':'+native.REMOTE+'/project/metadata/neo4j-connection/jobtology-neo4j.json'])
        protected=sql("SELECT ontology.hash(jsonb_build_object('attempts',(SELECT jsonb_agg(a ORDER BY attempt_id) FROM enrichment.attempt a),"
            "'attachments',(SELECT count(*) FROM attachment.attempt),'proposals',(SELECT jsonb_agg(p ORDER BY proposal_id) FROM ontology.occupation_proposal p),"
            "'decisions',(SELECT jsonb_agg(d ORDER BY decision_id) FROM ontology.occupation_decision d)))")
        mapping=json.loads((run.ROOT/'ontology/versions/hop-v5/mappings/hop-v5.json').read_text())
        schema=json.loads((run.ROOT/'ontology/versions/hop-v5/schemas/product-occupation-proposal-v1.schema.json').read_text())
        reports=[];files=[]
        for index,release in enumerate(['roles-v1','roles-catalogue-changed']):
            sql('SELECT ontology.freeze_requirements_v1('+q(release)+')')
            native.run('load_release.hwf',dict(RELEASE_ID=release),'occupation-native-graph-'+str(index))
            assert sql('SELECT graph_verified_at IS NOT NULL FROM ontology.corpus_release WHERE release_id='+q(release))=='t'
            expected=4 if index==0 else 0
            assert sql('SELECT count(*) FROM ontology.graph_node WHERE release_id='+q(release)+" AND labels @> ARRAY['primaryOccupationClaim']")==str(expected)
            manifest=json.loads(sql('SELECT manifest FROM ontology.corpus_release WHERE release_id='+q(release)),parse_float=Decimal)
            assert manifest['occupation_membership']['selection_count']==8
            assert manifest['editorial_membership']['catalogue_version']==index+1
            for version in [1,2,3,4]:err(f'SELECT ontology.interchange_check_v{version}({q(release)},true)','INTERCHANGE_UNMAPPED_NODE_LABEL')
            native.run('../editorial/export_jsonld_v5.hwf',dict(RELEASE_ID=release,PREVIEW='Y'),'occupation-native-export-'+str(index))
            destination=native.WORK/('occupation-exports-'+str(index))
            run.cmd(['docker','cp',native.HOP+':'+native.REMOTE+'/project/data/ontology-exports',str(destination)])
            file=next(p for p in destination.glob('*.jsonld') if p.name not in {x.name for x in files});files.append(file)
            rdf,_,actual_manifest=validator.load(file);assert actual_manifest==manifest
            nodes={str(rdf.value(n,JT.nativeNodeId)):n for n in rdf.subjects(JT.nativeNodeId,None)}
            for row in json.loads(sql('SELECT jsonb_agg(n ORDER BY node_id) FROM ontology.graph_node n WHERE release_id='+q(release)),parse_float=Decimal):
                assert validator.native_properties(rdf,nodes[row['node_id']],mapping)==row['properties']
            for row in json.loads(sql('SELECT jsonb_agg(e ORDER BY edge_id) FROM ontology.graph_edge e WHERE release_id='+q(release)),parse_float=Decimal):
                edge=URIRef('urn:jobtology:edge:'+row['edge_id']);assert validator.native_properties(rdf,edge,mapping)==row['properties']
                assert [str(rdf.value(edge,k)) for k in [JT.nativeSubjectId,JT.nativePredicate,JT.nativeObjectId]]==[row[k] for k in ['subject_id','predicate','object_id']]
            structure,_,details=validator.check(file);assert structure['conforms'],details;reports.append(structure)
            publication,_,_=validator.check(file,True);assert not publication['conforms']
            result=neo.neo("MATCH (r:corpusRelease {id:"+json.dumps('release/'+release)+"})-[:INCLUDES]->(s:occupationReviewSelection) RETURN count(s)=8 AS verified")
            assert result.splitlines()[-1].lower()=='true'
            result=neo.neo("MATCH (p:jobPostingRevision)-[e:FOR_OCCUPATION]->(o:occupation) WHERE e.release_id="+json.dumps(release)+
                " RETURN count(e)="+str(expected)+" AND all(x IN collect(e) WHERE size(x.source_assertion_ids)=1) AND all(x IN collect(o) WHERE x.scheme_id='urn:jobtology:conceptScheme:product-occupations') AS verified")
            assert result.splitlines()[-1].lower()=='true'
        assert neo.neo("MATCH (a:primaryOccupationClaim) RETURN count(a)=4 AND all(x IN collect(a) WHERE x.confidence IS NULL AND x.confidence_state='UNASSESSED' AND x.name CONTAINS ' → ') AS verified").splitlines()[-1].lower()=='true'
        # Loading a newer release never rewrites existing assertions or their evidence.
        old=sql("SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='roles-v1'")
        before=neo.neo('MATCH (n:ontologyObject) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)')
        native.run('load_release.hwf',dict(RELEASE_ID='roles-v1'),'occupation-native-old-release-replay')
        assert sql("SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='roles-v1'")==old
        assert neo.neo('MATCH (n:ontologyObject) OPTIONAL MATCH (n)-[e]->() RETURN count(DISTINCT n),count(e)')==before
        # Semantic rejection checks bypass the generic content-hash verifier.
        verify=runpy.run_path(str(run.ROOT/'ontology/tools/validate_occupations.py'))['verify']
        rdf,_,manifest=validator.load(files[0])
        def verify_now():verify(rdf,'roles-v1',manifest,mapping,validator.native_properties,validator.native_hash,JT,RDF,schema)
        leaf=next(n for n in rdf.subjects(RDF.type,JT.OccupationBindingValue) if str(rdf.value(n,JT.valueKind))=='string' and str(rdf.value(n,JT.value))=='기계학습 모델 학습 및 모델 배포')
        old_value=rdf.value(leaf,JT.value);rdf.set((leaf,JT.value,Literal('근거에 없는 직무')))
        try:verify_now();raise RuntimeError('Changed bound duty accepted')
        except AssertionError as e:assert 'Binding content hash mismatch' in str(e),str(e)
        rdf.set((leaf,JT.value,old_value));verify_now()
        edge=next(e for e in rdf.subjects(RDF.type,JT.Relation) if str(rdf.value(e,JT.nativePredicate))=='FOR_OCCUPATION')
        old_ids=rdf.value(edge,JT.sourceAssertionIds);wrong=BNode();Collection(rdf,wrong,[Literal('wrong-claim')]);rdf.set((edge,JT.sourceAssertionIds,wrong))
        try:verify_now();raise RuntimeError('Unsupported shortcut accepted')
        except AssertionError as e:assert 'shortcut or assertion support mismatch' in str(e),str(e)
        rdf.set((edge,JT.sourceAssertionIds,old_ids));verify_now()
        err("BEGIN; ALTER TABLE ontology.graph_node DISABLE TRIGGER USER; UPDATE ontology.graph_node SET properties=jsonb_set(properties,'{name}','\"tampered\"') WHERE release_id='roles-v1' AND labels @> ARRAY['primaryOccupationClaim']; SELECT ontology.verify_occupation_graph_v1('roles-v1'); COMMIT",'OCCUPATION_GRAPH_NODE_MISMATCH')
        err("SELECT ontology.activate_release('roles-v1','fixture','Must remain a draft')",'RELEASE_NOT_READY_FOR_ACTIVATION')
        # Optional module: older inventories and immutable export packages still work.
        sha=sql("SELECT snapshot_id FROM editorial.release_pin WHERE release_id='roles-catalogue-changed'")
        occupations.prepare('roles-legacy-v4',sha);sql("SELECT ontology.seal_graph('roles-legacy-v4'); SELECT ontology.seal_graph('roles-not-assembled')")
        legacy=[]
        for release,version in [('roles-legacy-v4',4),('roles-not-assembled',1)]:
            file=native.WORK/(release+'.jsonld');file.write_text(sql(f"SELECT string_agg(line,E'\\n' ORDER BY line_no) FROM ontology.export_jsonld_v{version}({q(release)},true)")+'\n')
            report,_,details=validator.check(file);assert report['conforms'],details;legacy.append(report)
            assert sql('SELECT ontology.occupation_graph_manifest_v1('+q(release)+') IS NULL')=='t'
        assert protected==sql("SELECT ontology.hash(jsonb_build_object('attempts',(SELECT jsonb_agg(a ORDER BY attempt_id) FROM enrichment.attempt a),"
            "'attachments',(SELECT count(*) FROM attachment.attempt),'proposals',(SELECT jsonb_agg(p ORDER BY proposal_id) FROM ontology.occupation_proposal p),"
            "'decisions',(SELECT jsonb_agg(d ORDER BY decision_id) FROM ontology.occupation_decision d)))")
        assert neo.neo("MATCH (p:Person {id:'occupation-private-person'}) RETURN p.name='Keep private data' AS verified").splitlines()[-1].lower()=='true'
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        report=dict(result='PASS',releases=reports,legacy=legacy,private_person_preserved=True,provider_calls=0,production_changes=False,
            original_role_links=4,newer_role_links=0,semantic_tampering_rejected=True,publication_conforms=False,protected_fingerprint=protected)
        (native.WORK/'occupation-graph-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print('OCCUPATION GRAPH AND V5 CHECKS PASSED',native.WORK,flush=True)
    finally:subprocess.run(['docker','rm','-fv',neo.NEO],capture_output=True)

if __name__=='__main__':occupations.main(check)
