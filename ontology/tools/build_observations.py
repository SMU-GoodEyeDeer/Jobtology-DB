"""Derive immutable interchange v2 from v1 without rewriting the v1 package."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'versions/hop-v2'
VERSION='hop-ontology-interchange-v2'
FILES=['context.jsonld','terms.yaml','vocabulary.ttl','structure-shapes.ttl','publication-shapes.ttl','shapes.ttl']


def main():
    package={name:(json.loads((ROOT/name).read_text()) if name.endswith(('.jsonld','.yaml')) else (ROOT/name).read_text()) for name in FILES}
    for name in ['structure-shapes.ttl','publication-shapes.ttl']:
        package[name]=package[name].replace('hop-ontology-interchange-v1',VERSION)
    mapping=json.loads((ROOT/'mappings/hop-v1.json').read_text())
    mapping['contract_version']=VERSION
    mapping['node_labels']['entityObservationState']='EntityObservationState'
    mapping['predicates']['FOR_ENTITY']='forEntity'
    fields='observation_state_id selected_revision_id entity_type connector_run_id content_run_id consecutive_absence_count serving_state state_reason evaluated_at first_seen_at last_seen_at methodology_version'.split()
    for key in fields:
        first,*rest=key.split('_');mapping['properties'][key]=first+''.join(p.title() for p in rest)
    # Preserve exact native timestamp strings for hash readback while exposing
    # separately typed RDF time values for SHACL and consumers.
    mapping['datetime_aliases']={key:mapping['properties'][key] for key in ['first_seen_at','last_seen_at','evaluated_at']}
    for key,alias in mapping['datetime_aliases'].items():mapping['properties'][key]='native'+alias[0].upper()+alias[1:]
    context=package['context.jsonld']['@context']
    for term in mapping['properties'].values():context.setdefault(term,{'@id':'jt:'+term})
    context['forEntity']={'@id':'jt:forEntity','@type':'@id'}
    for term in mapping['datetime_aliases'].values():context[term]={'@id':'jt:'+term,'@type':'xsd:dateTime'}
    terms=package['terms.yaml'];terms['version']=VERSION
    terms['classes']['EntityObservationState']={'status':'EXPORTABLE'}
    del terms['reserved_classes']['EntityObservationState']
    for term in ['forEntity','servingState','firstSeenAt','lastSeenAt','evaluatedAt']:terms['reserved_properties'].pop(term,None)
    terms['properties']={value:{'native_key':key} for key,value in mapping['properties'].items()}
    terms['predicates']={value:{'native_predicate':key} for key,value in mapping['predicates'].items()}
    terms['datetime_aliases']=mapping['datetime_aliases']
    package['mappings/hop-v2.json']=mapping
    package['vocabulary.ttl']+='\n# Interchange v2: canonical posting observations are now exportable.\n'
    package['vocabulary.ttl']=package['vocabulary.ttl'].replace('jt:EntityObservationState a rdfs:Class ; rdfs:comment "Reserved; not yet assembled by the Hop export." .',
        'jt:EntityObservationState a rdfs:Class ; rdfs:label "EntityObservationState" .')
    for term in ['forEntity','servingState','firstSeenAt','lastSeenAt','evaluatedAt']:
        package['vocabulary.ttl']=package['vocabulary.ttl'].replace(f'jt:{term} a rdf:Property ; rdfs:comment "Publication requirement; not yet assembled." .',f'jt:{term} a rdf:Property .')
    # V2 is already immutable. Preserve its originally deployed declaration
    # order explicitly; Python set iteration must never change a contract hash.
    declaration_order=json.loads((OUT/'property-declaration-order.json').read_text())
    assert len(declaration_order)==len(set(declaration_order))
    assert set(declaration_order)==set(mapping['properties'].values())|set(mapping['datetime_aliases'].values())|{'forEntity'}
    for name in declaration_order:
        package['vocabulary.ttl']+=f'jt:{name} a rdf:Property .\n'
    package['structure-shapes.ttl']+='''

# Observations are bound to the same entity and exact revision in this release.
jt:ObservationShape a sh:NodeShape ; sh:targetClass jt:EntityObservationState ;
 sh:property [ sh:path jt:observationStateId ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ; sh:pattern "^[0-9a-f]{64}$" ] ;
 sh:property [ sh:path jt:forEntity ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:JobPosting ] ;
 sh:property [ sh:path jt:selectsRevision ; sh:minCount 1 ; sh:maxCount 1 ; sh:class jt:JobPostingRevision ] ;
 sh:property [ sh:path jt:consecutiveAbsenceCount ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 0 ] ;
 sh:property [ sh:path jt:servingState ; sh:minCount 1 ; sh:maxCount 1 ; sh:in ("ACTIVE" "EXPIRED" "CLOSED" "NOT_SEEN") ] ;
 sh:property [ sh:path jt:firstSeenAt ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ; sh:lessThanOrEquals jt:lastSeenAt ] ;
 sh:property [ sh:path jt:lastSeenAt ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ; sh:lessThanOrEquals jt:evaluatedAt ] ;
 sh:property [ sh:path jt:evaluatedAt ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:dateTime ] ;
 sh:sparql [ sh:message "Observation identity/revision/release must match its selected endpoints and release root." ; sh:select """
  PREFIX jt: <urn:jobtology:vocab:1:>
  SELECT $this WHERE {
   $this jt:forEntity ?entity ; jt:selectsRevision ?revision ; jt:entityId ?eid ; jt:selectedRevisionId ?rid ; jt:releaseId ?release .
   FILTER (NOT EXISTS { ?entity jt:entityId ?eid ; jt:hasRevision ?revision } ||
    NOT EXISTS { ?revision jt:revisionId ?rid ; jt:entityId ?eid } ||
    NOT EXISTS { ?root a jt:CorpusRelease ; jt:selectedReleaseId ?release ; jt:includes $this, ?entity, ?revision })
  }""" ] .
'''
    package['shapes.ttl']='# Combined structural and publication shapes, immutable interchange v2.\n'+package['structure-shapes.ttl']+'\n'+package['publication-shapes.ttl']
    for name,value in package.items():
        path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text((json.dumps(value,ensure_ascii=False,indent=2)+'\n') if isinstance(value,dict) else value)
    contract=json.dumps(package,ensure_ascii=False,separators=(',',':'));assert '$contract$' not in contract
    install="""-- Generated immutable observation interchange v2. The original v1 stays installed.
BEGIN;
DO $install$ DECLARE package jsonb:=$contract$"""+contract+"""$contract$::jsonb; BEGIN
 IF EXISTS(SELECT 1 FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v2' AND artifacts IS DISTINCT FROM package)
 THEN RAISE EXCEPTION 'INTERCHANGE_CONTRACT_VERSION_CONFLICT'; END IF;
 INSERT INTO ontology.interchange_contract(version,artifacts,content_hash)
 VALUES('hop-ontology-interchange-v2',package,ontology.hash(package)) ON CONFLICT DO NOTHING;
END $install$;
COMMIT;
"""
    (ROOT.parent/'hop/ontology/sql/011_observation_interchange_contract.sql').write_text(install)
    original=(ROOT.parent/'hop/ontology/sql/007_interchange.sql').read_text()
    sql=original[original.index('CREATE OR REPLACE FUNCTION ontology.interchange_check_v1'):]
    for before,after in [('ontology.interchange_check_v1','ontology.interchange_check_v2'),('ontology.export_jsonld_v1','ontology.export_jsonld_v2'),
                         ('hop-ontology-interchange-v1',VERSION),('mappings/hop-v1.json','mappings/hop-v2.json')]:sql=sql.replace(before,after)
    sql=sql.replace(' RETURN id;\nEND $$;', ' PERFORM ontology.verify_observation_membership_v1(id);\n RETURN id;\nEND $$;',1)
    marker="  seq:=seq+1;line_no:=seq;line:=result::text||',';RETURN NEXT;"
    sql=sql.replace(marker,"""  FOR alias IN SELECT * FROM jsonb_each_text(mapping->'datetime_aliases') LOOP
   value:=item.properties->>alias.key;
   IF value IS NOT NULL THEN
    PERFORM value::timestamptz;
    result:=result||jsonb_build_object(alias.value,jsonb_build_object('@value',value,'@type','xsd:dateTime'));
   END IF;
  END LOOP;
"""+marker,1)
    (ROOT.parent/'hop/ontology/sql/012_observation_interchange.sql').write_text('-- Generated v2 serializer; shared native value helpers retain v1 behavior.\nBEGIN;\n'+sql)
    print('Built immutable observation interchange v2; v1 files are unchanged.')


if __name__=='__main__':main()
