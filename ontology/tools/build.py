"""Build versioned interchange artifacts. Never an ingestion/ETL runtime step.

terms.yaml deliberately uses JSON (a YAML subset), so building needs no YAML parser.
Native property values remain independently recoverable; Schema.org aliases are
additional alignments, never replacements for the evidence-bearing source fields.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
VERSION='hop-ontology-interchange-v1'
PREFIXES=dict(jt='urn:jobtology:vocab:1:',jtf='urn:jobtology:field:1:',
              schema='https://schema.org/',rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#',
              rdfs='http://www.w3.org/2000/01/rdf-schema#',xsd='http://www.w3.org/2001/XMLSchema#',
              skos='http://www.w3.org/2004/02/skos/core#',sh='http://www.w3.org/ns/shacl#')
KINDS=dict(organization='Organization',jobPosting='JobPosting',occupation='Occupation',ncsClass='NCSClass',
           ncsCompetency='NCSCompetencyUnit',ncsUnitFamily='NCSUnitFamily',qualification='Credential',
           examSession='ExamSession',careerRank='CareerRank',conceptScheme='ConceptScheme',skill='Skill',
           majorConcept='MajorConcept',course='Course',courseInstance='CourseInstance',actionTemplate='ActionTemplate',place='Place')
LABELS=KINDS|{k+'Revision':v+'Revision' for k,v in KINDS.items()}|dict(
    ontologyEntity='Entity',entityRevision='EntityRevision',ontologySource='Source',assertion='Assertion',
    sourceAssertion='SourceAssertion',sourceSnapshot='SourceSnapshot',sourceRecordEvidence='SourceRecordEvidence',
    positionClaim='PositionClaim',dutyClaim='DutyClaim',requirementClaim='RequirementClaim',
    competencyMappingClaim='CompetencyMappingClaim',conditionExpression='ConditionExpression',evidenceSpan='EvidenceSpan',
    textArtifact='TextArtifact',postingReviewSelection='PostingReviewSelection',linkReviewSelection='LinkReviewSelection',
    guardedRule='GuardedRule',rulePredicate='RulePredicate',ruleContract='RuleContract',ruleReviewSelection='RuleReviewSelection',
    postingInput='PostingInput',sourceAttachment='SourceAttachment',documentObservation='DocumentObservation',
    documentSection='DocumentSection',documentTable='DocumentTable',documentCell='DocumentCell')
PREDICATES='''HAS_REVISION DERIVED_FROM IN_SNAPSHOT FROM_SOURCE EVIDENCED_BY SUBJECT OBJECT POSTED_BY
BELONGS_TO_OCCUPATION VERSION_OF CLASSIFIED_AS BROADER_THAN HAS_MEMBER CURRICULUM_REFERENCES HAS_EXAM_SESSION
HAS_CAREER_RANK REFERENCES_UNIT_FAMILY HAS_POSITION HAS_DUTY HAS_REQUIREMENT APPLIES_TO HAS_EXPRESSION HAS_CHILD
HAS_RULE USES_CONTRACT REVIEWED_BY DISABLES LIMITS GUARDED_BY FOR_EXTRACTION IN_ARTIFACT USES_INPUT FOR_POSTING
IN_INPUT DECLARED_IN HAS_OBSERVATION OVERLAPS_SECTION IN_ATTACHMENT NESTED_IN_CELL HAS_CELL IN_CELL MAPS_DUTY
MAPS_TARGET SELECTS_REVISION INCLUDES'''.split()
FIELDS='''entity_id revision_id kind code scheme_id name title payload_hash schema_version source_id source_record_id
locator raw_sha256 normalized_hash sha256 byte_length encoding position_id posting_revision_id local_id claim_id
ordinal text category condition_kind logic applicability interpretation_state assertion_kind text_parts node_index
operator parts rule_id interpretation_id action statement_parts guard_kind position_ids node_path evidence_id
artifact_id start_offset end_offset excerpt excerpt_sha256 offset_unit locator_version input_sha256 text_sha256
normalization_version source_field mapping_id predicate reason duty_claim_id target_revision_id release_id outcome duties_status
source_hash extraction_revision_id decision_id candidate_id bundle_id posting_id job_run_id contract document_count
file_id file_ordinal role source_url raw_hash parsed_hash text_hash parser_version structure_layout_hash
structure_issue_count section_index source_content_hash original_start original_end normalized_start normalized_end
parent_table_no parent_cell_no section_no table_no cell_no row_no col_no row_span col_span entry_name
rows cols context_role paragraph_no block_no is_header version_selection version base_code full_code level depth
source_status date_precision date_posted closing_date established_date primary_occupation_id organization_id
year round category_code source_url acceptance_policy subject_id object_id assertion_id fields field part_index
requirement_index extraction_hash actor schema_hash description vocabulary_version'''.split()


def camel(value):
    first,*rest=value.lower().split('_')
    return first+''.join(s.title() for s in rest)


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def main():
    predicates={name:camel(name) for name in PREDICATES}
    properties={name:camel(name) for name in sorted(set(FIELDS))}
    # Structural terms have separate names from native fields/predicates. This
    # preserves provenance even when RDF collapses identical direct triples.
    structural=['nativeNodeId','nativeEdgeId','nativeLabel','nativeLabelOrder','nativePropertyKey','nativeContentHash',
                'nativePredicate','nativeSubjectId','nativeObjectId','nativeGraphManifestHash','exportReadMode',
                'exportContractHash','exportContractVersion','selectedReleaseId','dataAsOf','pipelineVersion',
                'methodologyVersion','releaseState','hasRelation','mappedPredicate','nativeGraphManifest']
    assert len(set(properties.values()))==len(properties)
    assert not set(structural)&set(properties.values())
    assert not set(PREFIXES)&(set(properties.values())|set(predicates.values())|set(structural))
    mappings=dict(contract_version=VERSION,prefixes=PREFIXES,node_labels=LABELS,
        predicates=predicates,properties=properties,unknown_property_encoding='jtf:UTF8-hex',
        node_iri_encoding='urn:jobtology:node: plus SHA-256 of the exact native node ID UTF-8 bytes',
        edge_iri_encoding='urn:jobtology:edge: plus the native edge ID',
        named_graph='urn:jobtology:release: plus SHA-256 of the exact release ID UTF-8 bytes',
        schema_types={k:'schema:'+v for k,v in dict(
            organization='Organization',jobPosting='JobPosting',occupation='Occupation',
            ncsClass='CategoryCode',ncsCompetency='DefinedTerm',ncsUnitFamily='DefinedTerm',
            qualification='EducationalOccupationalCredential',conceptScheme='DefinedTermSet',skill='DefinedTerm',
            majorConcept='DefinedTerm',course='Course',courseInstance='CourseInstance',place='Place').items()},
        schema_literal_aliases=dict(name='schema:name',title='schema:title',source_url='schema:url',
                                   date_posted='schema:datePosted',closing_date='schema:validThrough'),
        schema_relation_aliases=dict(POSTED_BY='schema:hiringOrganization'),
        notes=['Schema types apply to identity shells and their immutable revisions; changing values remain on revisions.',
               'Native labels, field keys, values, ordered arrays, edge identities and qualifiers remain recoverable.',
               'NCS competency units and unresolved unit families are distinct from generic skills.',
               'ALIGNS_WITH/curriculum references are never promoted into SKOS exactMatch or ATTESTS.',
               'No Person or private application node is an exportable native label.'])
    context={'@version':1.1,'@protected':True,**{k:{'@id':v,'@prefix':True} for k,v in PREFIXES.items()}}
    context.update({name:{'@id':'jt:'+name} for name in sorted(set(properties.values())|set(structural))})
    context.update({name:{'@id':'jt:'+name,'@type':'@id'} for name in predicates.values()})
    context['nativeLabel']={'@id':'jt:nativeLabel','@container':'@set'}
    context['hasRelation']={'@id':'jt:hasRelation','@type':'@id','@container':'@set'}
    context['mappedPredicate']={'@id':'jt:mappedPredicate','@type':'@id'}
    classes=sorted(set(LABELS.values())|{'CorpusRelease','Relation'})
    reserved=['EntityObservationState','ApplicationWindow','ApplicationWindowRevision','PostingCohort','TypedCondition',
              'AggregateObservation','LearningOutcomeClaim','SkillMappingClaim','Person']
    reserved_properties='forOccupation descriptionTextSha256 forEntity servingState firstSeenAt lastSeenAt evaluatedAt confidence reviewStatus requirementKind requirementScope necessity requirementKey targets normalizedCondition skillKind'.split()
    terms=dict(version=VERSION,namespaces=PREFIXES,classes={c:{'status':'EXPORTABLE'} for c in classes},
        reserved_classes={c:{'status':'NOT_IMPLEMENTED_IN_THIS_EXPORT'} for c in reserved},
        properties={v:{'native_key':k} for k,v in properties.items()},
        predicates={v:{'native_predicate':k} for k,v in predicates.items()},structural_terms=structural,
        reserved_properties={p:{'status':'PUBLICATION_REQUIREMENT_NOT_YET_ASSEMBLED'} for p in reserved_properties},
        references=['https://www.w3.org/TR/json-ld11/','https://www.w3.org/TR/shacl/',
                    'https://schema.org/JobPosting','https://schema.org/EducationalOccupationalCredential'])
    write(ROOT/'context.jsonld',{'@context':context})
    write(ROOT/'terms.yaml',terms)
    write(ROOT/'mappings/hop-v1.json',mappings)
    ttl=[f'@prefix {key}: <{value}> .' for key,value in PREFIXES.items()]
    ttl+=['','jt: a rdfs:Resource ; rdfs:label "Jobtology interchange vocabulary v1" .']
    ttl += [f'jt:{c} a rdfs:Class ; rdfs:label "{c}" .' for c in classes]
    ttl += [f'jt:{c} a rdfs:Class ; rdfs:comment "Reserved; not yet assembled by the Hop export." .' for c in reserved]
    ttl += [f'jt:{name} a rdf:Property .' for name in sorted(set(properties.values())|set(predicates.values())|set(structural))]
    ttl += [f'jt:{name} a rdf:Property ; rdfs:comment "Publication requirement; not yet assembled." .' for name in reserved_properties]
    ttl += ['jt:Relation rdfs:subClassOf rdf:Statement .']
    for native,kind in KINDS.items():
        if native in mappings['schema_types']:
            target=mappings['schema_types'][native]
            ttl += [f'jt:{kind} rdfs:subClassOf {target} .',f'jt:{kind}Revision rdfs:subClassOf jt:EntityRevision, {target} .']
    for claim in ['SourceAssertion','PositionClaim','DutyClaim','RequirementClaim','CompetencyMappingClaim','GuardedRule']:
        ttl.append(f'jt:{claim} rdfs:subClassOf jt:Assertion .')
    (ROOT/'vocabulary.ttl').write_text('\n'.join(ttl)+'\n')
    (ROOT/'shapes.ttl').write_text('# Combined structural and publication shapes. Generated by ontology/tools/build.py.\n'+
        (ROOT/'structure-shapes.ttl').read_text()+'\n'+(ROOT/'publication-shapes.ttl').read_text())
    artifacts=['context.jsonld','terms.yaml','mappings/hop-v1.json','vocabulary.ttl',
               'structure-shapes.ttl','publication-shapes.ttl','shapes.ttl']
    package={name:(json.loads((ROOT/name).read_text()) if name.endswith(('.json','.jsonld','.yaml'))
                   else (ROOT/name).read_text()) for name in artifacts}
    contract=json.dumps(package,ensure_ascii=False,separators=(',',':'))
    assert '$contract$' not in contract
    (ROOT.parent/'hop/ontology/sql/006_interchange_contract.sql').write_text('''-- Generated versioned public interchange artifacts. No source or review mutation.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.interchange_contract (
 version text PRIMARY KEY, artifacts jsonb NOT NULL, content_hash text NOT NULL,
 installed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK (content_hash=ontology.hash(artifacts))
);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_interchange_contract'
   AND tgrelid='ontology.interchange_contract'::regclass) THEN
  CREATE TRIGGER ontology_immutable_interchange_contract BEFORE UPDATE OR DELETE ON ontology.interchange_contract
   FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;
DO $install$ DECLARE package jsonb:=$contract$'''+contract+'''$contract$::jsonb; BEGIN
 IF EXISTS(SELECT 1 FROM ontology.interchange_contract WHERE version='''+"'"+VERSION+"'"+''' AND artifacts IS DISTINCT FROM package)
 THEN RAISE EXCEPTION 'INTERCHANGE_CONTRACT_VERSION_CONFLICT'; END IF;
 INSERT INTO ontology.interchange_contract(version,artifacts,content_hash)
 VALUES('''+"'"+VERSION+"'"+''',package,ontology.hash(package)) ON CONFLICT DO NOTHING;
END $install$;
COMMIT;
''')
    print('Generated JSON-LD context, versioned terms, Hop mappings and RDF vocabulary.')


if __name__=='__main__':main()
