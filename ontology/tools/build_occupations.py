"""Build immutable JSON-LD v5 for evidence-bound primary occupation decisions."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'versions/hop-v4';OUT=ROOT/'versions/hop-v5'
VERSION='hop-ontology-interchange-v5'
def main():
    names=['context.jsonld','terms.yaml','vocabulary.ttl','structure-shapes.ttl','publication-shapes.ttl','schemas/product-occupations-v1.schema.json']
    package={n:json.loads((BASE/n).read_text()) if n.endswith(('.json','.jsonld','.yaml')) else (BASE/n).read_text() for n in names}
    mapping=json.loads((BASE/'mappings/hop-v4.json').read_text());mapping['contract_version']=VERSION
    classes={name:name[0].upper()+name[1:] for name in ['occupationFreeze','occupationReviewSelection','occupationProposal','occupationReview',
             'occupationBinding','occupationBindingValue','primaryOccupationClaim','occupationContract']}
    predicates=dict(HAS_OCCUPATION_SELECTION='hasOccupationSelection',SELECTS_PROPOSAL='selectsProposal',REVIEWS_PROPOSAL='reviewsProposal',
        USES_SOURCE_BINDING='usesSourceBinding',USES_CATALOGUE_BINDING='usesCatalogueBinding',HAS_BINDING_VALUE='hasBindingValue',
        BINDING_MEMBER='bindingMember',FOR_OCCUPATION='forOccupation')
    fields='proposal_id proposal_no proposal_cutoff decision_cutoff policy_version posting_entity_id created_in_release occupation_id occupation_revision_id disposition source_binding_id catalogue_binding_id catalogue_binding_hash proposal_null_fields record_null_fields binding_id binding_kind binding_hash pointer value_kind member_count member_key member_index value source_assertion_ids method'.split()
    mapping['node_labels'].update(classes);mapping['predicates'].update(predicates)
    for key in fields:
        first,*rest=key.split('_');mapping['properties'][key]=first+''.join(p.title() for p in rest)
    context=package['context.jsonld']['@context']
    for term in mapping['properties'].values():context.setdefault(term,{'@id':'jt:'+term})
    for term in predicates.values():context[term]={'@id':'jt:'+term,'@type':'@id'}
    terms=package['terms.yaml'];terms['version']=VERSION
    for term in classes.values():terms['classes'][term]={'status':'EXPORTABLE'};terms['reserved_classes'].pop(term,None)
    terms['properties']={v:{'native_key':k} for k,v in mapping['properties'].items()}
    terms['predicates']={v:{'native_predicate':k} for k,v in mapping['predicates'].items()}
    for term in set(mapping['properties'].values())|set(mapping['predicates'].values()):terms['reserved_properties'].pop(term,None)
    package['mappings/hop-v5.json']=mapping
    name='schemas/product-occupation-proposal-v1.schema.json';package[name]=json.loads((ROOT.parent/'hop/editorial'/name).read_text())
    package['vocabulary.ttl']+='\n# V5: selected primary occupation assertions and immutable review inputs.\n'
    for term in sorted(classes.values()):package['vocabulary.ttl']+=f'jt:{term} a rdfs:Class .\n'
    for term in sorted(set(mapping['properties'].values())|set(predicates.values())):package['vocabulary.ttl']+=f'jt:{term} a rdf:Property .\n'
    for name in ['structure-shapes.ttl','publication-shapes.ttl']:package[name]=package[name].replace('hop-ontology-interchange-v4',VERSION)
    package['structure-shapes.ttl']+='''

jt:OccupationFreezeShape a sh:NodeShape ; sh:targetClass jt:OccupationFreeze ;
 sh:property [ sh:path jt:manifestHash ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:usesContract ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationContract ] .
jt:OccupationSelectionShape a sh:NodeShape ; sh:targetClass jt:OccupationReviewSelection ;
 sh:property [ sh:path jt:hasSubject ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:JobPostingRevision ] ;
 sh:property [ sh:path jt:selectsProposal ; sh:maxCount 1 ; sh:class jt:OccupationProposal ] ;
 sh:property [ sh:path jt:reviewedBy ; sh:maxCount 1 ; sh:class jt:OccupationReview ] ;
 sh:property [ sh:path jt:outcome ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("MATCHED" "OUT_OF_SCOPE" "UNRESOLVED" "NOT_PROPOSED" "PENDING" "REJECTED" "EXTRACTION_NOT_ACCEPTED" "SOURCE_CHANGED" "CATALOGUE_CHANGED") ] .
jt:OccupationProposalShape a sh:NodeShape ; sh:targetClass jt:OccupationProposal ;
 sh:property [ sh:path jt:usesSourceBinding ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationBinding ] ;
 sh:property [ sh:path jt:usesCatalogueBinding ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationBinding ] ;
 sh:property [ sh:path jt:usesContract ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationContract ] .
jt:OccupationBindingShape a sh:NodeShape ; sh:targetClass jt:OccupationBinding ;
 sh:property [ sh:path jt:bindingKind ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("SOURCE" "CATALOGUE") ] ;
 sh:property [ sh:path jt:hasBindingValue ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationBindingValue ] .
jt:OccupationBindingValueShape a sh:NodeShape ; sh:targetClass jt:OccupationBindingValue ;
 sh:property [ sh:path jt:valueKind ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("object" "array" "string" "number" "boolean" "null") ] ;
 sh:property [ sh:path jt:bindingMember ; sh:class jt:OccupationBindingValue ] .
jt:OccupationReviewShape a sh:NodeShape ; sh:targetClass jt:OccupationReview ;
 sh:property [ sh:path jt:decision ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("ACCEPT" "REJECT") ] ;
 sh:property [ sh:path jt:reviewerKind ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("human" "assistant") ] ;
 sh:property [ sh:path jt:reviewsProposal ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationProposal ] .
jt:PrimaryOccupationClaimShape a sh:NodeShape ; sh:targetClass jt:PrimaryOccupationClaim ; sh:class jt:Assertion ;
 sh:property [ sh:path jt:hasSubject ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:JobPostingRevision ] ;
 sh:property [ sh:path jt:targets ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:Occupation ] ;
 sh:property [ sh:path jt:selectsRevision ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationRevision ] ;
 sh:property [ sh:path jt:derivedFrom ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationProposal ] ;
 sh:property [ sh:path jt:reviewedBy ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:OccupationReview ;
   sh:node [ sh:property [ sh:path jt:decision ; sh:hasValue "ACCEPT" ] ] ] ;
 sh:property [ sh:path jt:evidencedBy ; sh:minCount 1 ; sh:class jt:EvidenceSpan ] .
'''
    package['publication-shapes.ttl']+='''

jt:PublishedOccupationFreezeShape a sh:NodeShape ; sh:targetClass jt:CorpusRelease ;
 sh:property [ sh:path jt:includes ; sh:qualifiedValueShape [ sh:class jt:OccupationFreeze ] ; sh:qualifiedMinCount 1 ; sh:qualifiedMaxCount 1 ] .
jt:PublishedOccupationSelectionShape a sh:NodeShape ; sh:targetClass jt:OccupationReviewSelection ;
 sh:property [ sh:path jt:outcome ; sh:hasValue "MATCHED" ] .
'''
    package['shapes.ttl']='# Combined v5 structural and publication profile.\n'+package['structure-shapes.ttl']+'\n'+package['publication-shapes.ttl']
    for name,value in package.items():
        path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n' if isinstance(value,dict) else value)
    raw=json.dumps(package,ensure_ascii=False,separators=(',',':'));assert '$contract$' not in raw
    install="""-- Generated immutable occupation interchange v5; prior versions remain installed.
BEGIN;
DO $install$ DECLARE package jsonb:=$contract$"""+raw+"""$contract$::jsonb; BEGIN
 IF EXISTS(SELECT 1 FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v5' AND artifacts IS DISTINCT FROM package)
 THEN RAISE EXCEPTION 'INTERCHANGE_CONTRACT_VERSION_CONFLICT'; END IF;
 INSERT INTO ontology.interchange_contract(version,artifacts,content_hash)
 VALUES('hop-ontology-interchange-v5',package,ontology.hash(package)) ON CONFLICT DO NOTHING;
END $install$;
COMMIT;
"""
    (ROOT.parent/'hop/editorial/sql/012_occupation_interchange_contract.sql').write_text(install)
    sql=(ROOT.parent/'hop/editorial/sql/006_interchange.sql').read_text()
    for old,new in [('interchange_check_v4','interchange_check_v5'),('export_jsonld_v4','export_jsonld_v5'),
        ('hop-ontology-interchange-v4',VERSION),('mappings/hop-v4.json','mappings/hop-v5.json')]:sql=sql.replace(old,new)
    sql=sql.replace(' PERFORM editorial.verify_graph_v1(id);',' PERFORM editorial.verify_graph_v1(id);\n PERFORM ontology.verify_occupation_graph_v1(id);',1)
    (ROOT.parent/'hop/editorial/sql/013_occupation_interchange.sql').write_text(sql.replace('Generated v4 serializer','Generated v5 serializer',1))
    print('Built product occupation interchange v5; v1-v4 packages unchanged.')

if __name__=='__main__':main()
