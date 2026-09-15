"""Generate the immutable cohort-profile proposal schema and SQL contract."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/cohorts'
def obj(fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def text(*values,nullable=False):
    x=dict(type=['string','null'] if nullable else 'string',minLength=1,maxLength=8000)
    if values:x['enum']=list(values)+([None] if nullable else [])
    return x
def array(items):return dict(type='array',maxItems=1000,items=items)
def ids():return array(text())
def months():return dict(type=['integer','null'],minimum=0,maximum=2147483647)
evidence=obj(dict(field=text(),start_offset=dict(type='integer',minimum=0),
    end_offset=dict(type='integer',minimum=1),excerpt=text()))
policies=('ENTRY','INTERNSHIP','UNRESTRICTED','MIXED','EXPERIENCED','UNKNOWN')
track=obj(dict(position_id=text(),country_scope=text('KR','NON_KR','MIXED','UNKNOWN'),country_evidence=array(evidence),
    experience_policy=text(*policies),policy_basis=text('EXPLICIT_LABEL','PARSED_RANGE','UNKNOWN'),
    minimum_months=months(),maximum_months=months(),experience_evidence=array(evidence),experience_requirement_ids=ids(),
    cohort_scope=text('POSITION','REVIEWED_SUBSET','UNRESOLVED'),scope_notes=text(),scope_evidence=array(evidence),
    entry_track_scoped=dict(type='boolean'),domestic_track_scoped=dict(type='boolean'),
    considered_atom_ids=ids(),included_requirement_ids=ids()))
schema=obj(dict(schema_version=text('hop-cohort-profile-proposal-v1'),release_id=text(),posting_entity_id=text(),
    parent_id=text(nullable=True),source_binding_hash=text(),actor=text(),actor_kind=text('human','assistant'),
    method=text('MANUAL','MODEL_INFERRED'),model_id=text(nullable=True),prompt_version=text(nullable=True),resolver_version=text(),reason=text(),
    disposition=text('PROFILE','UNRESOLVED'),unresolved_reason=text('EXTRACTION_NOT_ACCEPTED','NO_REVIEWED_POSITIONS','AMBIGUOUS_SCOPE','INSUFFICIENT_EVIDENCE',nullable=True),
    posting_experience_label=text(*policies),posting_label_evidence=array(evidence),tracks=array(track)))
(OUT/'schemas/cohort-profile-v1.schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n')
compact=json.dumps(schema,ensure_ascii=False,separators=(',',':'))
(OUT/'sql/003_profile_contract.sql').write_text('''BEGIN;
CREATE TABLE IF NOT EXISTS ontology.cohort_profile_contract(version text PRIMARY KEY,schema jsonb NOT NULL,content_hash text NOT NULL);
INSERT INTO ontology.cohort_profile_contract SELECT 'hop-cohort-profile-proposal-v1',s,ontology.hash(s)
FROM (SELECT $schema$'''+compact+'''$schema$::jsonb s) x ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.cohort_profile_contract WHERE version='hop-cohort-profile-proposal-v1'
  AND schema=$schema$'''+compact+'''$schema$::jsonb AND content_hash=ontology.hash(schema))
 THEN RAISE EXCEPTION 'COHORT_PROFILE_CONTRACT_CHANGED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='ontology.cohort_profile_contract'::regclass AND tgname='ontology_cohort_profile_contract_immutable') THEN
  CREATE TRIGGER ontology_cohort_profile_contract_immutable BEFORE UPDATE OR DELETE ON ontology.cohort_profile_contract
  FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;
COMMIT;
''')
