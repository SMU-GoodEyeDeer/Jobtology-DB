"""Native export and independent RDF roundtrip in new disposable containers.

No live API/model calls; synthetic inline fixtures only. Existing fixture DBs
and all production/attachment data are untouched.
"""
import importlib.util
import json
import subprocess
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from rdflib import Graph, Namespace, RDF, URIRef
from rdflib.collection import Collection
from pyshacl import validate
import run

JT=Namespace('urn:jobtology:vocab:1:')
ROOT=run.ROOT
spec=importlib.util.spec_from_file_location('interchange_validator',ROOT/'ontology/tools/validate.py')
validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
MAPPING=json.loads((ROOT/'ontology/mappings/hop-v1.json').read_text())


def scalar(graph,value):
    if value==RDF.nil or (value,RDF.first,None) in graph:
        return [scalar(graph,x) for x in Collection(graph,value)]
    if value.datatype==RDF.JSON:return json.loads(str(value))
    return value.toPython()


def native_properties(graph,owner):
    keys=scalar(graph,graph.value(owner,JT.nativePropertyKey))
    assert len(keys)==len(set(keys))
    result={}
    for key in keys:
        predicate=JT[MAPPING['properties'][key]] if key in MAPPING['properties'] else URIRef('urn:jobtology:field:1:'+key.encode().hex())
        values=list(graph.objects(owner,predicate));assert len(values)==1,(owner,key,values)
        result[key]=scalar(graph,values[0])
    return result


def roundtrip(path,release):
    graph,_,manifest=validator.load(path)
    nodes=json.loads(run.sql('SELECT jsonb_agg(n ORDER BY node_id) FROM ontology.graph_node n WHERE release_id='+run.q(release)),parse_float=Decimal)
    edges=json.loads(run.sql('SELECT jsonb_agg(e ORDER BY edge_id) FROM ontology.graph_edge e WHERE release_id='+run.q(release)),parse_float=Decimal)
    for node in nodes:
        subjects=list(graph.subjects(JT.nativeNodeId,None))
        owner=next(s for s in subjects if str(graph.value(s,JT.nativeNodeId))==node['node_id'])
        assert native_properties(graph,owner)==node['properties'],node['node_id']
        assert scalar(graph,graph.value(owner,JT.nativeLabelOrder))==node['labels']
        assert str(graph.value(owner,JT.nativeContentHash))==node['content_hash']
    for edge in edges:
        owner=URIRef('urn:jobtology:edge:'+edge['edge_id'])
        assert native_properties(graph,owner)==edge['properties'],edge['edge_id']
        assert str(graph.value(owner,JT.nativePredicate))==edge['predicate']
        assert str(graph.value(owner,JT.nativeSubjectId))==edge['subject_id']
        assert str(graph.value(owner,JT.nativeObjectId))==edge['object_id']
        assert str(graph.value(owner,JT.nativeContentHash))==edge['content_hash']
        s,p,o=[graph.value(owner,t) for t in [RDF.subject,RDF.predicate,RDF.object]]
        assert (s,p,o) in graph
    assert not list(graph.triples((None,URIRef('http://www.w3.org/2004/02/skos/core#exactMatch'),None)))
    for evidence in graph.subjects(RDF.type,JT.EvidenceSpan):
        aid=str(graph.value(evidence,JT.artifactId));start=int(graph.value(evidence,JT.startOffset));end=int(graph.value(evidence,JT.endOffset))
        original=run.sql('SELECT normalized_text FROM ontology.text_artifact WHERE artifact_id='+run.q(aid))
        assert original[start:end]==str(graph.value(evidence,JT.excerpt))
    return graph,manifest


def main():
    suffix=uuid.uuid4().hex[:10];run.PG='jobtology-interchange-pg-'+suffix
    assert subprocess.run(['docker','inspect',run.PG],capture_output=True).returncode
    hop='jobtology-interchange-hop-'+suffix;network='jobtology-interchange-'+suffix
    work=Path(tempfile.mkdtemp(prefix='jobtology-interchange-'))
    print('Interchange test evidence:',work,flush=True)
    try:
        run.boot()
        import claims
        claims.check()
        release='review-fixture'
        run.expect_error("SELECT count(*) FROM ontology.export_jsonld_v1('review-fixture',true)",'SEAL_ONTOLOGY_GRAPH_FIRST')
        run.sql("SELECT ontology.seal_graph('review-fixture'); SELECT ontology.seal_graph('review-new-ncs')")
        baseline=run.sql('SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r')
        def export(name):
            text=run.sql('SELECT line FROM ontology.export_jsonld_v1('+run.q(name)+',true) ORDER BY line_no')+'\n'
            path=work/(name+'.jsonld');path.write_text(text);return path
        path=export(release);graph,manifest=roundtrip(path,release)
        report,_,details=validator.check(path)
        assert report['conforms'],details
        pub,_,details=validator.check(path,True)
        assert not pub['conforms']
        assert 'forOccupation' in details and 'confidence' in details and 'forEntity' in details,details
        (work/'publication-rejections.txt').write_text(details)
        other=export('review-new-ncs');other_graph,_=roundtrip(other,'review-new-ncs')
        assert graph.identifier!=other_graph.identifier
        # Identity may be shared, while revision values remain release-selected.
        assert run.sql('SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r')==baseline
        assert path.read_bytes()==export(release).read_bytes()
        tampered=json.loads(path.read_text())
        for row in tampered['@graph']:
            if 'schema:title' in row:
                row['schema:title']='변조된 제목';break
        else:raise AssertionError('No title alias in fixture')
        bad=work/'incorrect-schema-title.jsonld';bad.write_text(json.dumps(tampered,ensure_ascii=False))
        try:validator.load(bad);raise RuntimeError('Accepted an incorrect Schema.org title')
        except AssertionError as error:assert 'Schema.org literal alias mismatch' in str(error)
        # Native scalar/list encoding handles values JSON/RDF parsers can otherwise lose.
        value={'empty':'','number':9223372036854775807,'decimal':1.25,'truth':False,
               '순서.값':['가','가','나'],'list':[],'null':None,'flag':[True,False]}
        encoded=json.loads(run.sql('SELECT ontology.interchange_properties_v1('+run.js(value)+','+run.js(MAPPING)+')'))
        probe=Graph().parse(data=json.dumps({'@context':json.loads((ROOT/'ontology/context.jsonld').read_text())['@context'],
             '@id':'urn:test:values',**encoded},ensure_ascii=False),format='json-ld')
        assert native_properties(probe,URIRef('urn:test:values'))==value
        decimals=json.loads(run.sql("SELECT ontology.interchange_properties_v1('{\"scaled\":1.00,\"tiny\":0.00000000001,\"큰값\":9223372036854775807}',"+run.js(MAPPING)+")"))
        numeric=Graph().parse(data=json.dumps({'@context':json.loads((ROOT/'ontology/context.jsonld').read_text())['@context'],
            '@id':'urn:test:numeric',**decimals},ensure_ascii=False),format='json-ld')
        recovered=native_properties(numeric,URIRef('urn:test:numeric'))
        assert str(recovered['scaled'])=='1.00' and recovered['tiny']==Decimal('0.00000000001')
        expected=run.sql("SELECT ontology.hash('{\"scaled\":1.00,\"tiny\":0.00000000001,\"큰값\":9223372036854775807}')")
        assert validator.native_hash(recovered)==expected,'Independent PostgreSQL JSONB hash reconstruction failed'
        # Deliberately corrupt independent RDF values: structural validation must reject.
        shapes=Graph().parse(ROOT/'ontology/structure-shapes.ttl',format='turtle')
        evidence=next(graph.subjects(RDF.type,JT.EvidenceSpan));before=list(graph.objects(evidence,JT.excerpt))
        from rdflib import Literal
        graph.set((evidence,JT.excerpt,Literal('변조된 문장')))
        assert not validate(graph,shacl_graph=shapes)[0]
        graph.set((evidence,JT.excerpt,before[0]))
        edge=next(graph.subjects(RDF.type,JT.Relation));graph.remove((edge,RDF.object,None))
        assert not validate(graph,shacl_graph=shapes)[0]
        for preview in ['true','false']:
            run.expect_error("BEGIN; UPDATE ontology.corpus_release SET state='REVOKED' WHERE release_id='review-fixture'; SELECT count(*) FROM ontology.export_jsonld_v1('review-fixture',"+preview+"); ROLLBACK;",'CORPUS_RELEASE_REVOKED')
        run.expect_error("SELECT count(*) FROM ontology.export_jsonld_v1()",'NO_ACTIVE_ONTOLOGY_RELEASE')
        run.expect_error("SELECT count(*) FROM ontology.export_jsonld_v1('review-fixture')",'ONTOLOGY_RELEASE_NOT_PUBLISHED')
        run.expect_error("SELECT count(*) FROM ontology.export_jsonld_v1('review-fixture',NULL)",'INVALID_ONTOLOGY_READ_MODE')
        run.expect_error("UPDATE ontology.interchange_contract SET artifacts='{}'",'IMMUTABLE_ONTOLOGY_RECORD')
        import native
        native.HOP=hop;native.NET=network
        native.stage();native.run('install.hwf',{},'interchange-installer')
        native.run('export_jsonld.hwf',dict(RELEASE_ID=release,PREVIEW='Y'),'native-jsonld-export')
        native.run('export_jsonld.hwf',dict(RELEASE_ID=release,PREVIEW='Y'),'native-jsonld-repeat')
        destination=work/'native-exports'
        run.cmd(['docker','cp',hop+':'+native.REMOTE+'/project/data/ontology-exports',str(destination)])
        outputs=list(destination.glob('*.jsonld'));assert len(outputs)==2,outputs
        for output in outputs:
            assert str(uuid.UUID(output.stem))==output.stem,'Export must allocate a UUID filename'
            assert output.read_bytes()==path.read_bytes(),'Hop serialization changed the SQL output'
        native.run('export_jsonld.hwf',dict(RELEASE_ID=release),'native-unpublished-export',False)
        native.run('export_jsonld.hwf',dict(RELEASE_ID=release,PREVIEW='invalid'),'native-invalid-export-mode',False)
        assert run.sql('SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r')==baseline
        assert run.sql('SELECT count(*) FROM ontology.active_release')=='0'
        assert run.sql('SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL')=='0'
        print(json.dumps(report),flush=True)
        print('NATIVE INTERCHANGE CHECKS PASSED. Native fixture:',native.WORK,flush=True)
    finally:
        for container in [hop,run.PG]:subprocess.run(['docker','rm','-fv',container],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__=='__main__':main()
