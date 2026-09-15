"""Offline JSON-LD/SHACL validation. Does not fetch source data or run ETL.

Use the exact local vocabulary package for this export contract. Remote contexts,
imports and linked data are never loaded. A passing structure report is not a
published-release or semantic-completeness certificate.
"""
import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from rdflib import Dataset, Graph, Namespace, RDF, URIRef, Literal, XSD
from rdflib.collection import Collection
from pyshacl import validate

if not __debug__:
    raise RuntimeError('Run export validation without Python -O; contract checks must be enabled.')

ROOT=Path(__file__).resolve().parents[1]
JT=Namespace('urn:jobtology:vocab:1:')


def jsonb_text(value):
    """Exact hop-ontology-jsonb-v1 text for finite native JSON values; not JCS."""
    if isinstance(value,dict):
        keys=sorted(value,key=lambda k:(len(k.encode('utf-8')),k.encode('utf-8')))
        return '{'+', '.join(json.dumps(k,ensure_ascii=False)+': '+jsonb_text(value[k]) for k in keys)+'}'
    if isinstance(value,list):return '['+', '.join(jsonb_text(v) for v in value)+']'
    if isinstance(value,Decimal):
        assert value.is_finite(),'Non-finite decimal'
        return format(value,'f')
    return json.dumps(value,ensure_ascii=False,allow_nan=False)


def native_hash(value):
    return hashlib.sha256(('hop-ontology-jsonb-v1:'+jsonb_text(value)).encode('utf-8')).hexdigest()


def rdf_value(graph,value):
    if value==RDF.nil or (value,RDF.first,None) in graph:
        return [rdf_value(graph,x) for x in Collection(graph,value)]
    assert not isinstance(value,URIRef),'Native property must be a literal or ordered list'
    if value.datatype==RDF.JSON:return json.loads(str(value),parse_float=Decimal)
    result=value.toPython()
    assert isinstance(result,(str,int,float,bool,Decimal)),('Unsupported RDF literal',value)
    return result


def native_properties(graph,owner,mapping):
    heads=list(graph.objects(owner,JT.nativePropertyKey));assert len(heads)==1,'Missing native property key list'
    keys=rdf_value(graph,heads[0]);assert isinstance(keys,list) and len(keys)==len(set(keys))
    result={}
    for key in keys:
        predicate=JT[mapping['properties'][key]] if key in mapping['properties'] else URIRef('urn:jobtology:field:1:'+key.encode().hex())
        values=list(graph.objects(owner,predicate));assert len(values)==1,('Property cardinality',owner,key)
        result[key]=rdf_value(graph,values[0])
    return result


def contract_package(version):
    assert version in ('hop-ontology-interchange-v1','hop-ontology-interchange-v2','hop-ontology-interchange-v3','hop-ontology-interchange-v4','hop-ontology-interchange-v5'),'Unknown interchange contract'
    suffix=version.rsplit('-',1)[-1]
    return (ROOT,'mappings/hop-v1.json') if suffix=='v1' else (ROOT/('versions/hop-'+suffix),'mappings/hop-'+suffix+'.json')


def load(path):
    document=json.loads(Path(path).read_text(encoding='utf-8'))
    assert isinstance(document,dict) and set(document)=={'@context','@id','@graph'},'Expected one named-graph document'
    versions=[row['exportContractVersion'] for row in document['@graph'] if isinstance(row,dict) and 'exportContractVersion' in row]
    assert len(versions)==1,'Expected exactly one export contract version'
    package_root,mapping_name=contract_package(versions[0])
    assert document['@context']==json.loads((package_root/'context.jsonld').read_text())['@context'],'Export context differs from the local contract'
    assert isinstance(document['@graph'],list),'Expected graph array'
    def inspect(value):
        if isinstance(value,dict):
            # @json literals are data, not executable contexts or nested graphs.
            if value.get('@type')=='@json':return
            assert not {'@context','@graph','@import'}&value.keys(),'Nested context/graph/import is forbidden'
            for child in value.values():inspect(child)
        elif isinstance(value,list):
            for child in value:inspect(child)
    inspect(document['@graph'])
    dataset=Dataset()
    dataset.parse(data=json.dumps(document,ensure_ascii=False),format='json-ld')
    expected=URIRef(document['@id'])
    populated=[g for g in dataset.graphs() if len(g)]
    assert len(populated)==1 and populated[0].identifier==expected,'Unexpected RDF graph scope'
    graph=populated[0]
    roots=list(graph.subjects(RDF.type,JT.CorpusRelease))
    assert len(roots)==1,'Expected exactly one release root'
    root=roots[0];release=str(graph.value(root,JT.selectedReleaseId))
    assert str(graph.value(root,JT.nativeNodeId))=='release/'+release,'Root native ID mismatch'
    assert str(expected)=='urn:jobtology:release:'+hashlib.sha256(release.encode()).hexdigest(),'Wrong named graph ID'
    manifest=json.loads(str(graph.value(root,JT.nativeGraphManifest)),parse_float=Decimal)
    assert manifest['release_id']==release,'Manifest release mismatch'
    assert len(set(graph.subjects(JT.nativeNodeId,None)))-1==manifest['nodes'],'Node count mismatch'
    assert len(set(graph.subjects(RDF.type,JT.Relation)))==manifest['edges'],'Relation count mismatch'
    assert native_hash(manifest)==str(graph.value(root,JT.nativeGraphManifestHash)),'Manifest hash mismatch'
    names=['context.jsonld','terms.yaml',mapping_name,'vocabulary.ttl',
           'structure-shapes.ttl','publication-shapes.ttl','shapes.ttl']
    if versions[0] in ('hop-ontology-interchange-v4','hop-ontology-interchange-v5'):names.append('schemas/product-occupations-v1.schema.json')
    if versions[0]=='hop-ontology-interchange-v5':names.append('schemas/product-occupation-proposal-v1.schema.json')
    package={name:(json.loads((package_root/name).read_text(),parse_float=Decimal) if name.endswith(('.json','.jsonld','.yaml'))
             else (package_root/name).read_text()) for name in names}
    assert native_hash(package)==str(graph.value(root,JT.exportContractHash)),'Local contract package hash mismatch'
    mapping=package[mapping_name]
    def expanded(term):
        prefix,local=term.split(':',1)
        return URIRef(mapping['prefixes'][prefix]+local)
    def node_iri(value):return URIRef('urn:jobtology:node:'+hashlib.sha256(value.encode()).hexdigest())
    for node in graph.subjects(JT.nativeNodeId,None):
        if node==root:continue
        node_id=str(graph.value(node,JT.nativeNodeId));label_heads=list(graph.objects(node,JT.nativeLabelOrder))
        assert len(label_heads)==1,'Missing ordered native labels'
        labels=rdf_value(graph,label_heads[0])
        assert set(labels)=={str(v) for v in graph.objects(node,JT.nativeLabel)},'Native label list/set mismatch'
        properties=native_properties(graph,node,mapping)
        assert native_hash([node_id,labels,properties])==str(graph.value(node,JT.nativeContentHash)),'Native node hash mismatch'
        expected_types={JT[mapping['node_labels'][label]] for label in labels}
        kind=properties.get('kind')
        if kind in mapping['schema_types']:expected_types.add(expanded(mapping['schema_types'][kind]))
        assert set(graph.objects(node,RDF.type))==expected_types,'Native/export type mismatch'
        for key,term in mapping['schema_literal_aliases'].items():
            value=properties.get(key);expected=set()
            if isinstance(value,str) and value:
                import re
                if key=='source_url':
                    if re.fullmatch(r'https?://[^\s]+',value):expected={URIRef(value)}
                elif key in ('date_posted','closing_date'):
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):expected={Literal(value,datatype=XSD.date)}
                    elif re.fullmatch(r'\d{4}-\d{2}-\d{2}T.*(Z|[+-]\d{2}:\d{2})',value):expected={Literal(value,datatype=XSD.dateTime)}
                else:expected={Literal(value)}
            assert set(graph.objects(node,expanded(term)))==expected,('Schema.org literal alias mismatch',node,key)
        for key,term in mapping.get('datetime_aliases',{}).items():
            value=properties.get(key)
            expected={Literal(value,datatype=XSD.dateTime)} if value is not None else set()
            assert set(graph.objects(node,JT[term]))==expected,('Observation datetime alias mismatch',node,key)
        for key,term in mapping.get('date_aliases',{}).items():
            value=properties.get(key)
            expected={Literal(value,datatype=XSD.date)} if value is not None else set()
            assert set(graph.objects(node,JT[term]))==expected,('Date alias mismatch',node,key)
    if 'entityObservationState' in mapping['node_labels']:
        states=[]
        for node in graph.subjects(RDF.type,JT.EntityObservationState):
            properties=native_properties(graph,node,mapping)
            state={k:v for k,v in properties.items() if k!='name'}
            assert native_hash({k:v for k,v in state.items() if k!='observation_state_id'})==state['observation_state_id'],'Observation state identity mismatch'
            assert state['release_id']==release,'Observation from another release'
            states.append(state)
        binding=manifest.get('observation_membership')
        if binding is not None:
            assert len(states)==binding['manifest']['state_count'],'Observation membership count mismatch'
            assert native_hash(sorted(states,key=lambda s:s['entity_id'].encode()))==binding['manifest']['state_hash'],'Observation membership hash mismatch'
        else:assert not states,'Observation states require a membership manifest'
    relations={}
    for edge in graph.subjects(RDF.type,JT.Relation):
        values=[str(graph.value(edge,key)) for key in [JT.nativeSubjectId,JT.nativePredicate,JT.nativeObjectId]]
        values.append(native_properties(graph,edge,mapping))
        assert native_hash(values)==str(graph.value(edge,JT.nativeContentHash)),'Native relation hash mismatch'
        assert native_hash([release,*values])==str(graph.value(edge,JT.nativeEdgeId)),'Native relation ID mismatch'
        subject,predicate,object_id,_=values
        mapped=JT[mapping['predicates'][predicate]]
        relations.setdefault((node_iri(subject),mapped),set()).add(node_iri(object_id))
        if predicate in mapping['schema_relation_aliases']:
            alias=expanded(mapping['schema_relation_aliases'][predicate])
            relations.setdefault((node_iri(subject),alias),set()).add(node_iri(object_id))
    for predicate in [JT[p] for p in mapping['predicates'].values()]+[expanded(p) for p in mapping['schema_relation_aliases'].values()]:
        subjects=set(graph.subjects(predicate,None))|{s for s,p in relations if p==predicate}
        for subject in subjects:
            assert set(graph.objects(subject,predicate))==relations.get((subject,predicate),set()),'Direct relation differs from native relation inventory'
    if mapping['contract_version'] in ('hop-ontology-interchange-v3','hop-ontology-interchange-v4','hop-ontology-interchange-v5'):
        import runpy
        verify=runpy.run_path(str(Path(__file__).with_name('validate_requirements.py')))['verify']
        verify(graph,release,manifest,mapping,native_properties,native_hash,JT,RDF)
    if mapping['contract_version'] in ('hop-ontology-interchange-v4','hop-ontology-interchange-v5'):
        import runpy
        verify=runpy.run_path(str(Path(__file__).with_name('validate_editorial.py')))['verify']
        verify(graph,release,manifest,mapping,native_properties,native_hash,JT,RDF,package['schemas/product-occupations-v1.schema.json'])
    if mapping['contract_version']=='hop-ontology-interchange-v5':
        import runpy
        verify=runpy.run_path(str(Path(__file__).with_name('validate_occupations.py')))['verify']
        verify(graph,release,manifest,mapping,native_properties,native_hash,JT,RDF,package['schemas/product-occupation-proposal-v1.schema.json'])
    return graph,release,manifest


def check(path,publication=False):
    graph,release,manifest=load(path)
    root=next(graph.subjects(RDF.type,JT.CorpusRelease))
    package_root,_=contract_package(str(graph.value(root,JT.exportContractVersion)))
    shapes=Graph().parse(package_root/('shapes.ttl' if publication else 'structure-shapes.ttl'),format='turtle')
    ontology=Graph().parse(package_root/'vocabulary.ttl',format='turtle')
    conforms,report,details=validate(graph,shacl_graph=shapes,ont_graph=ontology,
        inference='none',meta_shacl=True,do_owl_imports=False,advanced=False)
    return dict(release_id=release,profile='publication' if publication else 'structure',
                conforms=bool(conforms),nodes=manifest['nodes'],edges=manifest['edges'],triples=len(graph),
                meaning='Export validity only; database publication gates and semantic review remain mandatory.'),report,details


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('file',type=Path);p.add_argument('--publication',action='store_true')
    p.add_argument('--report',type=Path,help='Write the SHACL report as Turtle')
    args=p.parse_args();result,report,details=check(args.file,args.publication)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.report:report.serialize(args.report,format='turtle')
    if not result['conforms']:print(details)
    raise SystemExit(0 if result['conforms'] else 1)


if __name__=='__main__':main()
