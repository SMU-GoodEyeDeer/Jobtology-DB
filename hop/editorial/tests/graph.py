"""Editorial revisions through native Neo4j and independent JSON-LD v4 readback."""
from pathlib import Path
import importlib.util
import json
import subprocess
import uuid
from decimal import Decimal
import catalogue
import run

def check(native):
    import claims
    # Load explicitly: this test's graph.py must not shadow the existing fixture helper.
    spec=importlib.util.spec_from_file_location('editorial_neo_fixture',run.ROOT/'hop/ontology/tests/graph.py')
    neo=importlib.util.module_from_spec(spec);spec.loader.exec_module(neo)
    neo.NEO='jobtology-editorial-neo-'+uuid.uuid4().hex[:10]
    sql,q,js,err=run.sql,run.q,run.js,run.expect_error
    spec=importlib.util.spec_from_file_location('editorial_validator',run.ROOT/'ontology/tools/validate.py')
    validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
    from rdflib import Namespace,RDF,Literal,URIRef
    JT=Namespace('urn:jobtology:vocab:1:')
    try:
        neo.boot_neo()
        neo.neo("CREATE (:Person {id:'editorial-private-person',name:'Preserve private data'})")
        metadata=dict(name='jobtology-neo4j',server=neo.NEO,databaseName='neo4j',boltPort='7687',username='neo4j',password='test-auth-disabled',
            automatic=False,routing=False,usingEncryption=False,manualUrls=['bolt://'+neo.NEO+':7687'],connectionTimeout='10000',maxTransactionRetryTime='0')
        connection=native.WORK/'project/metadata/neo4j-connection/jobtology-neo4j.json'
        connection.parent.mkdir(exist_ok=True);connection.write_text(json.dumps(metadata))
        run.cmd(['docker','exec','-u','root',native.HOP,'mkdir','-p',native.REMOTE+'/project/metadata/neo4j-connection'])
        run.cmd(['docker','cp',str(connection),native.HOP+':'+native.REMOTE+'/project/metadata/neo4j-connection/jobtology-neo4j.json'])
        original=catalogue.protected()
        reports=[];exports=[]
        for index,release in enumerate(['fixture-release','editorial-next']):
            claims.assemble(release)
            # Freeze source-only atom outcomes as well: v4 must preserve the
            # typed-requirement membership contract even without approved proposals.
            sql('SELECT ontology.freeze_requirements_v1('+q(release)+')')
            native.run('load_release.hwf',dict(RELEASE_ID=release),'editorial-native-graph-'+str(index))
            manifest=json.loads(sql('SELECT manifest FROM ontology.corpus_release WHERE release_id='+q(release)),parse_float=Decimal)
            assert manifest['editorial_membership']['catalogue_version']==index+1
            assert len(manifest['source_pins'])==6
            assert sql("SELECT count(*) FROM ontology.graph_node WHERE release_id="+q(release)+" AND labels @> ARRAY['ontologySource']")=='7'
            assert sql("SELECT count(*) FROM ontology.graph_node WHERE release_id="+q(release)+" AND labels @> ARRAY['editorialSourceRecord']")=='5'
            for version in [1,2,3]:
                err(f'SELECT ontology.interchange_check_v{version}({q(release)},true)','INTERCHANGE_UNMAPPED_NODE_LABEL')
            native.run('../editorial/export_jsonld_v4.hwf',dict(RELEASE_ID=release,PREVIEW='Y'),'editorial-native-v4-'+str(index))
            destination=native.WORK/('editorial-exports-'+str(index))
            run.cmd(['docker','cp',native.HOP+':'+native.REMOTE+'/project/data/ontology-exports',str(destination)])
            file=next(p for p in destination.glob('*.jsonld') if p.name not in {x.name for x in exports})
            exports.append(file)
            rdf,_,read_manifest=validator.load(file)
            assert read_manifest==manifest
            mapping=json.loads((run.ROOT/'ontology/versions/hop-v4/mappings/hop-v4.json').read_text())
            nodes={str(rdf.value(n,JT.nativeNodeId)):n for n in rdf.subjects(JT.nativeNodeId,None)}
            for row in json.loads(sql('SELECT jsonb_agg(n ORDER BY node_id) FROM ontology.graph_node n WHERE release_id='+q(release)),parse_float=Decimal):
                assert validator.native_properties(rdf,nodes[row['node_id']],mapping)==row['properties']
            for row in json.loads(sql('SELECT jsonb_agg(e ORDER BY edge_id) FROM ontology.graph_edge e WHERE release_id='+q(release)),parse_float=Decimal):
                edge=URIRef('urn:jobtology:edge:'+row['edge_id'])
                assert validator.native_properties(rdf,edge,mapping)==row['properties']
                for term,key in [(JT.nativeSubjectId,'subject_id'),(JT.nativePredicate,'predicate'),(JT.nativeObjectId,'object_id')]:
                    assert str(rdf.value(edge,term))==row[key]
            structure,_,details=validator.check(file);assert structure['conforms'],details
            published,_,_=validator.check(file,True);assert not published['conforms']
            reports.append(structure)
            assert neo.neo("MATCH (root:corpusRelease {id:"+json.dumps('release/'+release)+"})-[:INCLUDES]->(v:occupationRevision) WHERE v.source_id='INTERNAL_EDITORIAL' RETURN count(v)=4 AND all(x IN collect(v) WHERE x.name IN ['AI 엔지니어','백엔드 개발자','프론트엔드 개발자','데이터 분석가']) AS verified").splitlines()[-1].lower()=='true'
        # Both revisions coexist; the older graph/review still reproduces its release.
        old=sql("SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='fixture-release'")
        native.run('load_release.hwf',dict(RELEASE_ID='fixture-release'),'editorial-native-old-release-replay')
        assert sql("SELECT manifest_hash FROM ontology.corpus_release WHERE release_id='fixture-release'")==old
        assert neo.neo("MATCH (v:occupationRevision {occupation_code:'AI_ENGINEER'}) RETURN count(v)=2 AND count(DISTINCT v.entity_id)=1 AS verified").splitlines()[-1].lower()=='true'
        assert neo.neo("MATCH (s:editorialSourceSnapshot) RETURN count(s)=2 AND all(x IN collect(s) WHERE x.byte_length>0 AND x.catalogue_version IN [1,2]) AS verified").splitlines()[-1].lower()=='true'
        # Check source semantics independently of the generic native content hashes.
        rdf,_,manifest=validator.load(exports[0])
        import runpy
        verify=runpy.run_path(str(run.ROOT/'ontology/tools/validate_editorial.py'))['verify']
        schema=json.loads((run.ROOT/'ontology/versions/hop-v4/schemas/product-occupations-v1.schema.json').read_text())
        source=next(rdf.subjects(RDF.type,JT.EditorialSourceSnapshot));original_text=rdf.value(source,JT.sourceText)
        rdf.set((source,JT.sourceText,Literal(str(original_text)+'\n')))
        try:verify(rdf,'fixture-release',manifest,mapping,validator.native_properties,validator.native_hash,JT,RDF,schema);raise RuntimeError('Changed source bytes accepted')
        except AssertionError as e:assert 'Editorial source SHA-256 mismatch' in str(e),str(e)
        rdf.set((source,JT.sourceText,original_text))
        record=next(rdf.subjects(RDF.type,JT.EditorialSourceRecord));original_pointer=rdf.value(record,JT.locator)
        rdf.set((record,JT.locator,Literal('/occupations/99')))
        try:verify(rdf,'fixture-release',manifest,mapping,validator.native_properties,validator.native_hash,JT,RDF,schema);raise RuntimeError('Changed source pointer accepted')
        except AssertionError as e:assert 'Editorial source pointer mismatch' in str(e),str(e)
        rdf.set((record,JT.locator,original_pointer))
        err("BEGIN; ALTER TABLE editorial.release_pin DISABLE TRIGGER USER; UPDATE editorial.release_pin SET manifest_hash=repeat('f',64) WHERE release_id='fixture-release'; SELECT ontology.seal_graph('fixture-release'); COMMIT",'EDITORIAL_MEMBERSHIP_CHANGED')
        # A release without the optional draft pin retains its legacy inventory.
        sql("SELECT ontology.prepare_release('editorial-legacy'); SELECT ontology.assemble_sources('editorial-legacy')")
        claims.assemble('editorial-legacy');sql("SELECT ontology.seal_graph('editorial-legacy')")
        assert sql("SELECT ontology.graph_inventory_manifest('editorial-legacy')=ontology.graph_inventory_manifest_base_v1('editorial-legacy')")=='t'
        file=native.WORK/'editorial-legacy-v1.jsonld'
        file.write_text(sql("SELECT string_agg(line,E'\\n' ORDER BY line_no) FROM ontology.export_jsonld_v1('editorial-legacy',true)")+'\n')
        legacy,_,details=validator.check(file);assert legacy['conforms'],details
        assert catalogue.protected()==original
        assert neo.neo("MATCH (p:Person {id:'editorial-private-person'}) RETURN p.name='Preserve private data' AS verified").splitlines()[-1].lower()=='true'
        assert sql('SELECT count(*) FROM ontology.active_release')=='0'
        report=dict(result='PASS',editorial_releases=reports,legacy=legacy,publication_conforms=False,
                    provider_calls=0,private_person_preserved=True,production_changes=False)
        (native.WORK/'editorial-graph-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print('EDITORIAL GRAPH AND V4 CHECKS PASSED',native.WORK,flush=True)
    finally:
        subprocess.run(['docker','rm','-fv',neo.NEO],capture_output=True)

if __name__=='__main__':catalogue.main(check)
