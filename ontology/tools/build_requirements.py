"""Immutable JSON-LD v3 package for typed requirements; preserve v1 and v2."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'versions/hop-v2';OUT=ROOT/'versions/hop-v3'
VERSION='hop-ontology-interchange-v3'

def main():
    names=['context.jsonld','terms.yaml','vocabulary.ttl','structure-shapes.ttl','publication-shapes.ttl']
    package={name:(json.loads((BASE/name).read_text()) if name.endswith(('.jsonld','.yaml')) else (BASE/name).read_text()) for name in names}
    mapping=json.loads((BASE/'mappings/hop-v2.json').read_text());mapping['contract_version']=VERSION
    mapping['node_labels'].update(requirementClaim='SourceRequirementGroup',normalizedRequirementClaim='RequirementClaim',
        requirementNormalization='RequirementNormalization',requirementReviewSelection='RequirementReviewSelection',
        typedCondition='TypedCondition',unresolvedCondition='UnresolvedCondition',requirementTargetBinding='RequirementTargetBinding',requirementContract='RequirementContract')
    predicates=dict(FOR_SOURCE_ATOM='forSourceAtom',SELECTS_NORMALIZATION='selectsNormalization',HAS_PROPOSED_CONDITION='hasProposedCondition',
        FOR_SOURCE_GROUP='forSourceGroup',NORMALIZED_CONDITION='normalizedCondition',TARGETS='targets',USES_TARGET_BINDING='usesTargetBinding',HAS_SUBJECT='hasSubject',
        HAS_REQUIREMENT='hasSourceRequirement',HAS_TYPED_REQUIREMENT='hasRequirement')
    mapping['predicates'].update(predicates)
    fields='normalization_id source_claim_id source_node_index typed_claim_id condition_id condition_fields null_fields requirement_kind requirement_scope necessity polarity requirement_key key_algorithm confidence_state review_status actor resolver_version source_binding_hash target_bindings_hash target_subkind valid_time_basis target_id target_kind proficiency_scheme_id minimum_proficiency minimum_degree accepted_major_groups accepts_expected_graduate context_id minimum_months maximum_months minimum_count portfolio_required capability_ids administrative_codes work_mode vocabulary_id source_text earliest_start schedule_text mention'.split()
    for key in fields:
        first,*rest=key.split('_');mapping['properties'][key]=first+''.join(p.title() for p in rest)
    for key,term in [('created_at','createdAt'),('reviewed_at','reviewedAt')]:
        mapping['datetime_aliases'][key]=term;mapping['properties'][key]='native'+term[0].upper()+term[1:]
    mapping['date_aliases']={'earliest_start':'earliestStart'};mapping['properties']['earliest_start']='nativeEarliestStart'
    context=package['context.jsonld']['@context']
    for term in mapping['properties'].values():context.setdefault(term,{'@id':'jt:'+term})
    for term in mapping['predicates'].values():context[term]={'@id':'jt:'+term,'@type':'@id'}
    for term in mapping['datetime_aliases'].values():context[term]={'@id':'jt:'+term,'@type':'xsd:dateTime'}
    for term in mapping['date_aliases'].values():context[term]={'@id':'jt:'+term,'@type':'xsd:date'}
    terms=package['terms.yaml'];terms['version']=VERSION
    for term in sorted(set(mapping['node_labels'].values())):
        terms['classes'][term]={'status':'EXPORTABLE'};terms['reserved_classes'].pop(term,None)
    terms['classes']['SourceRequirementGroup']['description']='Reviewed source text/expression; typed RequirementClaim is a separately reviewed interpretation of a leaf.'
    terms['properties']={v:{'native_key':k} for k,v in mapping['properties'].items()}
    terms['predicates']={v:{'native_predicate':k} for k,v in mapping['predicates'].items()}
    terms['datetime_aliases']=mapping['datetime_aliases'];terms['date_aliases']=mapping['date_aliases']
    for term in set(mapping['properties'].values())|set(mapping['predicates'].values()):terms['reserved_properties'].pop(term,None)
    package['mappings/hop-v3.json']=mapping
    package['vocabulary.ttl']+='\n# V3 distinguishes source groups, proposals, frozen decisions and typed claims.\n'
    for term in sorted(set(mapping['node_labels'].values())):
        package['vocabulary.ttl']=package['vocabulary.ttl'].replace(f'jt:{term} a rdfs:Class ; rdfs:comment "Reserved; not yet assembled by the Hop export." .',f'jt:{term} a rdfs:Class .')
        package['vocabulary.ttl']+=f'jt:{term} a rdfs:Class .\n'
    for term in sorted(set(mapping['properties'].values())|set(mapping['predicates'].values())|set(mapping['datetime_aliases'].values())|set(mapping['date_aliases'].values())):
        package['vocabulary.ttl']=package['vocabulary.ttl'].replace(f'jt:{term} a rdf:Property ; rdfs:comment "Publication requirement; not yet assembled." .',f'jt:{term} a rdf:Property .')
        package['vocabulary.ttl']+=f'jt:{term} a rdf:Property .\n'
    for name in ['structure-shapes.ttl','publication-shapes.ttl']:
        package[name]=package[name].replace('hop-ontology-interchange-v2',VERSION)
    package['structure-shapes.ttl']=package['structure-shapes.ttl'].replace('sh:targetClass jt:DutyClaim, jt:RequirementClaim','sh:targetClass jt:DutyClaim, jt:SourceRequirementGroup')
    package['structure-shapes.ttl']+='''

jt:TypedClaimStructureShape a sh:NodeShape ; sh:targetClass jt:RequirementClaim ;
 sh:property [ sh:path jt:claimId ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:postingRevisionId ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:evidencedBy ; sh:minCount 1 ; sh:class jt:EvidenceSpan ] ;
 sh:property [ sh:path jt:reviewedBy ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:RequirementReviewSelection ] ;
 sh:property [ sh:path jt:derivedFrom ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:RequirementNormalization ] ;
 sh:property [ sh:path jt:forSourceGroup ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:SourceRequirementGroup ] ;
 sh:property [ sh:path jt:forSourceAtom ; sh:minCount 1 ; sh:maxCount 1 ; sh:or ([sh:class jt:ConditionExpression] [sh:class jt:SourceRequirementGroup]) ] ;
 sh:property [ sh:path jt:hasSubject ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:JobPostingRevision ] ;
 sh:property [ sh:path [ sh:inversePath jt:hasRequirement ] ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:JobPostingRevision ] ;
 sh:property [ sh:path jt:polarity ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("POSITIVE" "NEGATED" "NO_CONSTRAINT") ] ;
 sh:property [ sh:path jt:confidenceState ; sh:hasValue "UNASSESSED" ] .
jt:RequirementSelectionShape a sh:NodeShape ; sh:targetClass jt:RequirementReviewSelection ;
 sh:property [ sh:path jt:forSourceAtom ; sh:minCount 1 ; sh:maxCount 1 ; sh:or ([sh:class jt:ConditionExpression] [sh:class jt:SourceRequirementGroup]) ] ;
 sh:property [ sh:path jt:outcome ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("NOT_PROPOSED" "PENDING" "UNRESOLVED" "REJECTED" "TARGET_REVISION_MISMATCH" "REVIEWED") ] ;
 sh:property [ sh:path jt:selectsNormalization ; sh:maxCount 1 ; sh:class jt:RequirementNormalization ] .
jt:RequirementProposalShape a sh:NodeShape ; sh:targetClass jt:RequirementNormalization ;
 sh:property [ sh:path jt:normalizationId ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:hasProposedCondition ; sh:minCount 1 ; sh:maxCount 1 ; sh:or ([sh:class jt:TypedCondition] [sh:class jt:UnresolvedCondition]) ] ;
 sh:property [ sh:path jt:forSourceAtom ; sh:minCount 1 ; sh:maxCount 1 ] ;
 sh:property [ sh:path jt:usesContract ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:RequirementContract ] .
jt:TypedConditionShape a sh:NodeShape ; sh:targetClass jt:TypedCondition ;
 sh:property [ sh:path jt:conditionId ; sh:minCount 1 ; sh:maxCount 1 ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:kind ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("SKILL" "LANGUAGE" "CREDENTIAL" "EDUCATION" "EXPERIENCE" "PROJECT" "LOCATION" "ELIGIBILITY" "AVAILABILITY") ] .
'''
    # Language kind belongs to the bound revision's definition, not to the stable
    # identity shell. The binding records it without changing old revision nodes.
    package['publication-shapes.ttl']=package['publication-shapes.ttl'].replace(
        '?target a jt:Skill ; jt:skillKind "LANGUAGE"',
        '?target a jt:Skill ; jt:hasRevision ?v . $this jt:usesTargetBinding ?b . ?b jt:role "target" ; jt:targetSubkind "LANGUAGE" ; jt:selectsRevision ?v')
    structural=package['publication-shapes.ttl'].split('jt:PublishedRequirementShape',1)[1].split('# Detailed condition',1)[0]
    package['structure-shapes.ttl']+='\njt:TypedRequirementConditionShape'+structural
    package['publication-shapes.ttl']+='''

jt:PublishedRequirementSelectionShape a sh:NodeShape ; sh:targetClass jt:RequirementReviewSelection ;
 sh:property [ sh:path jt:outcome ; sh:hasValue "REVIEWED" ] .
'''
    package['shapes.ttl']='# Combined v3 structural and publication profile.\n'+package['structure-shapes.ttl']+'\n'+package['publication-shapes.ttl']
    for name,value in package.items():
        p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n' if isinstance(value,dict) else value)
    contract=json.dumps(package,ensure_ascii=False,separators=(',',':'));assert '$contract$' not in contract
    install="""-- Generated immutable typed requirement interchange v3.
BEGIN;
DO $install$ DECLARE package jsonb:=$contract$"""+contract+"""$contract$::jsonb; BEGIN
 IF EXISTS(SELECT 1 FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v3' AND artifacts IS DISTINCT FROM package)
 THEN RAISE EXCEPTION 'INTERCHANGE_CONTRACT_VERSION_CONFLICT'; END IF;
 INSERT INTO ontology.interchange_contract(version,artifacts,content_hash)
 VALUES('hop-ontology-interchange-v3',package,ontology.hash(package)) ON CONFLICT DO NOTHING;
END $install$;
COMMIT;
"""
    (ROOT.parent/'hop/ontology/sql/017_requirement_interchange_contract.sql').write_text(install)
    sql=(ROOT.parent/'hop/ontology/sql/012_observation_interchange.sql').read_text()
    for old,new in [('interchange_check_v2','interchange_check_v3'),('export_jsonld_v2','export_jsonld_v3'),('hop-ontology-interchange-v2',VERSION),('mappings/hop-v2.json','mappings/hop-v3.json')]:sql=sql.replace(old,new)
    sql=sql.replace(' PERFORM ontology.verify_observation_membership_v1(id);',' PERFORM ontology.verify_observation_membership_v1(id);\n PERFORM ontology.verify_requirements_v1(id);',1)
    marker="  seq:=seq+1;line_no:=seq;line:=result::text||',';RETURN NEXT;"
    sql=sql.replace(marker,"""  FOR alias IN SELECT * FROM jsonb_each_text(mapping->'date_aliases') LOOP
   value:=item.properties->>alias.key;
   IF value IS NOT NULL THEN
    PERFORM value::date;
    result:=result||jsonb_build_object(alias.value,jsonb_build_object('@value',value,'@type','xsd:date'));
   END IF;
  END LOOP;
"""+marker,1)
    (ROOT.parent/'hop/ontology/sql/018_requirement_interchange.sql').write_text(sql.replace('Generated v2 serializer','Generated v3 serializer',1))
    print('Built typed requirement interchange v3; v1/v2 packages unchanged.')

if __name__=='__main__':main()
