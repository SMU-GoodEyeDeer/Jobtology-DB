"""Build immutable JSON-LD v4 for reviewed editorial source membership."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'versions/hop-v3'; OUT=ROOT/'versions/hop-v4'
VERSION='hop-ontology-interchange-v4'

def main():
    names=['context.jsonld','terms.yaml','vocabulary.ttl','structure-shapes.ttl','publication-shapes.ttl']
    package={name:(json.loads((BASE/name).read_text()) if name.endswith(('.jsonld','.yaml')) else (BASE/name).read_text()) for name in names}
    mapping=json.loads((BASE/'mappings/hop-v3.json').read_text());mapping['contract_version']=VERSION
    classes=dict(editorialSourceSnapshot='EditorialSourceSnapshot',editorialSourceRecord='EditorialSourceRecord',
                 editorialReview='EditorialReview',editorialReleaseSelection='EditorialReleaseSelection',editorialContract='EditorialContract')
    mapping['node_labels'].update(classes)
    predicates=dict(SELECTS_SNAPSHOT='selectsSnapshot',FOR_SNAPSHOT='forSnapshot',IN_SCHEME='inScheme')
    mapping['predicates'].update(predicates)
    fields='snapshot_id review_id review_no catalogue_id catalogue_version git_blob_sha1 source_snapshot_id actor_kind boundary_notes occupation_code manifest_hash decision reviewer reviewer_kind notes git_commit merge_evidence attestation_kind repository_verification schema_hash scheme_code release_id'.split()
    for key in fields:
        first,*rest=key.split('_');mapping['properties'][key]=first+''.join(p.title() for p in rest)
    context=package['context.jsonld']['@context']
    for term in mapping['properties'].values():context.setdefault(term,{'@id':'jt:'+term})
    for term in predicates.values():context[term]={'@id':'jt:'+term,'@type':'@id'}
    terms=package['terms.yaml'];terms['version']=VERSION
    for term in sorted(classes.values()):
        terms['classes'][term]={'status':'EXPORTABLE'};terms['reserved_classes'].pop(term,None)
    terms['properties']={v:{'native_key':k} for k,v in mapping['properties'].items()}
    terms['predicates']={v:{'native_predicate':k} for k,v in mapping['predicates'].items()}
    for term in set(mapping['properties'].values())|set(mapping['predicates'].values()):terms['reserved_properties'].pop(term,None)
    package['mappings/hop-v4.json']=mapping
    schema_name='schemas/product-occupations-v1.schema.json'
    package[schema_name]=json.loads((ROOT.parent/'hop/editorial'/schema_name).read_text())
    package['vocabulary.ttl']+='\n# V4 preserves exact internal editorial bytes and selected review provenance.\n'
    for term in sorted(classes.values()):package['vocabulary.ttl']+=f'jt:{term} a rdfs:Class .\n'
    for term in sorted(set(mapping['properties'].values())|set(predicates.values())):
        package['vocabulary.ttl']+=f'jt:{term} a rdf:Property .\n'
    for name in ['structure-shapes.ttl','publication-shapes.ttl']:
        package[name]=package[name].replace('hop-ontology-interchange-v3',VERSION)
    package['structure-shapes.ttl']+='''

jt:EditorialSnapshotShape a sh:NodeShape ; sh:targetClass jt:EditorialSourceSnapshot ;
 sh:class jt:SourceSnapshot ;
 sh:property [ sh:path jt:sourceId ; sh:hasValue "INTERNAL_EDITORIAL" ] ;
 sh:property [ sh:path jt:sourceText ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path jt:snapshotId ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:gitBlobSha1 ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{40}$" ] ;
 sh:property [ sh:path jt:fromSource ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:Source ] ;
 sh:property [ sh:path jt:usesContract ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:EditorialContract ] .
jt:EditorialRecordShape a sh:NodeShape ; sh:targetClass jt:EditorialSourceRecord ;
 sh:class jt:SourceRecordEvidence ;
 sh:property [ sh:path jt:inSnapshot ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:EditorialSourceSnapshot ] ;
 sh:property [ sh:path [ sh:inversePath jt:derivedFrom ] ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:EntityRevision ] .
jt:EditorialSelectionShape a sh:NodeShape ; sh:targetClass jt:EditorialReleaseSelection ;
 sh:property [ sh:path jt:selectsSnapshot ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:EditorialSourceSnapshot ] ;
 sh:property [ sh:path jt:reviewedBy ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:EditorialReview ] ;
 sh:property [ sh:path jt:selectsRevision ; sh:minCount 5 ; sh:maxCount 5 ; sh:class jt:EntityRevision ] .
jt:EditorialReviewShape a sh:NodeShape ; sh:targetClass jt:EditorialReview ;
 sh:property [ sh:path jt:decision ; sh:hasValue "ACCEPT" ] ;
 sh:property [ sh:path jt:reviewerKind ; sh:hasValue "human" ] ;
 sh:property [ sh:path jt:reviewedAt ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ] ;
 sh:property [ sh:path jt:gitCommit ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^([0-9a-f]{40}|[0-9a-f]{64})$" ] ;
 sh:property [ sh:path jt:mergeEvidence ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ; sh:minLength 1 ] ;
 sh:property [ sh:path jt:attestationKind ; sh:hasValue "OPERATOR_REPORTED" ] ;
 sh:property [ sh:path jt:repositoryVerification ; sh:hasValue "NOT_AUTOMATICALLY_VERIFIED" ] ;
 sh:property [ sh:path jt:forSnapshot ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:EditorialSourceSnapshot ] .
jt:EditorialContractShape a sh:NodeShape ; sh:targetClass jt:EditorialContract ;
 sh:property [ sh:path jt:schemaHash ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] .
'''
    old='sh:qualifiedMinCount 6 ; sh:qualifiedMaxCount 6'
    assert package['publication-shapes.ttl'].count(old)==1
    package['publication-shapes.ttl']=package['publication-shapes.ttl'].replace(old,'sh:qualifiedMinCount 7 ; sh:qualifiedMaxCount 7')
    package['publication-shapes.ttl']+='''

jt:PublishedEditorialSourceShape a sh:NodeShape ; sh:targetClass jt:CorpusRelease ;
 sh:property [ sh:path jt:includes ; sh:qualifiedValueShape [ sh:class jt:EditorialReleaseSelection ] ; sh:qualifiedMinCount 1 ; sh:qualifiedMaxCount 1 ] .
'''
    package['shapes.ttl']='# Combined v4 structural and publication profile.\n'+package['structure-shapes.ttl']+'\n'+package['publication-shapes.ttl']
    for name,value in package.items():
        path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n' if isinstance(value,dict) else value)
    raw=json.dumps(package,ensure_ascii=False,separators=(',',':'));assert '$contract$' not in raw
    install='''-- Generated immutable editorial interchange v4, installed after ontology v3.
BEGIN;
DO $install$ DECLARE package jsonb:=$contract$'''+raw+'''$contract$::jsonb; BEGIN
 IF EXISTS(SELECT 1 FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v4' AND artifacts IS DISTINCT FROM package)
 THEN RAISE EXCEPTION 'INTERCHANGE_CONTRACT_VERSION_CONFLICT'; END IF;
 INSERT INTO ontology.interchange_contract(version,artifacts,content_hash)
 VALUES('hop-ontology-interchange-v4',package,ontology.hash(package)) ON CONFLICT DO NOTHING;
END $install$;
COMMIT;
'''
    (ROOT.parent/'hop/editorial/sql/005_interchange_contract.sql').write_text(install)
    sql=(ROOT.parent/'hop/ontology/sql/018_requirement_interchange.sql').read_text()
    for old,new in [('interchange_check_v3','interchange_check_v4'),('export_jsonld_v3','export_jsonld_v4'),
                    ('hop-ontology-interchange-v3',VERSION),('mappings/hop-v3.json','mappings/hop-v4.json')]:sql=sql.replace(old,new)
    sql=sql.replace(' PERFORM ontology.verify_requirements_v1(id);',' PERFORM ontology.verify_requirements_v1(id);\n PERFORM editorial.verify_graph_v1(id);',1)
    (ROOT.parent/'hop/editorial/sql/006_interchange.sql').write_text(sql.replace('Generated v3 serializer','Generated v4 serializer',1))
    print('Built editorial interchange v4; v1-v3 packages unchanged.')

if __name__=='__main__':main()
