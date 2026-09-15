"""Generate the strict native normalization contract; never an ETL runtime."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'hop/ontology'

def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)

def string(*values, nullable=False, maximum=1000):
    result = dict(type=['string', 'null'] if nullable else 'string', minLength=1, maxLength=maximum)
    if values:
        result['enum'] = list(values) + ([None] if nullable else [])
    return result

def integer(nullable=True):
    return dict(type=['integer', 'null'] if nullable else 'integer', minimum=0, maximum=2147483647)

def array(items, maximum=200):
    return dict(type='array', items=items, maxItems=maximum)

boolean = dict(type=['boolean', 'null'])
conditions = []
for kind in ['SKILL', 'LANGUAGE']:
    conditions.append(obj(dict(kind=string(kind), target_id=string(),
        target_kind=string('Skill', 'NCSCompetencyUnit'),
        proficiency_scheme_id=string(nullable=True), minimum_proficiency=integer())))
conditions += [
    obj(dict(kind=string('CREDENTIAL'), target_id=string())),
    obj(dict(kind=string('EDUCATION'), minimum_degree=string('NONE', 'HIGH_SCHOOL', 'ASSOCIATE', 'BACHELOR', 'MASTER', 'DOCTORATE', nullable=True),
        accepted_major_groups=array(string('COMPUTING', 'ENGINEERING', 'NATURAL_SCIENCE', 'BUSINESS', 'HUMANITIES_SOCIAL', 'ARTS', 'OTHER')),
        accepts_expected_graduate=boolean)),
    obj(dict(kind=string('EXPERIENCE'), context_id=string(nullable=True), minimum_months=integer(), maximum_months=integer())),
    obj(dict(kind=string('PROJECT'), minimum_count=integer(), portfolio_required=boolean, capability_ids=array(string()))),
    obj(dict(kind=string('LOCATION'), administrative_codes=array(string(maximum=40)), work_mode=string('ONSITE', 'REMOTE', 'HYBRID', 'UNKNOWN'))),
    obj(dict(kind=string('ELIGIBILITY'), vocabulary_id=string(), code=string(maximum=100), source_text=string(maximum=8000))),
    obj(dict(kind=string('AVAILABILITY'), earliest_start=string(nullable=True, maximum=10), schedule_text=string(nullable=True, maximum=8000))),
    obj(dict(kind=string('UNRESOLVED'), mention=string(maximum=8000), reason=string('NO_MATCH', 'AMBIGUOUS', 'UNSUPPORTED_CONDITION'))),
]
schema = obj(dict(schema_version=string('hop-requirement-normalization-v1'), release_id=string(),
    source_claim_id=string(), node_index=dict(type='integer', minimum=-1, maximum=10000),
    parent_id=string(nullable=True), actor=string(), reason=string(maximum=8000), resolver_version=string(),
    necessity=string('REQUIRED', 'PREFERRED', 'OPTIONAL', 'UNSPECIFIED'),
    polarity=string('POSITIVE', 'NEGATED', 'NO_CONSTRAINT'), condition=dict(anyOf=conditions)))
directory = OUT / 'schemas'
directory.mkdir(exist_ok=True)
(directory / 'requirement-normalization-v1.schema.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n')
compact = json.dumps(schema, ensure_ascii=False, separators=(',', ':'))
(OUT / 'sql/013_requirement_contract.sql').write_text('''-- Generated strict input contract. No model confidence or acceptance is accepted.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.requirement_contract (
 version text PRIMARY KEY, schema jsonb NOT NULL, content_hash text NOT NULL
);
INSERT INTO ontology.requirement_contract
SELECT 'hop-requirement-normalization-v1',s,ontology.hash(s) FROM (SELECT $schema$'''+compact+'''$schema$::jsonb s) v
ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.requirement_contract WHERE version='hop-requirement-normalization-v1'
  AND schema=$schema$'''+compact+'''$schema$::jsonb AND content_hash=ontology.hash(schema))
 THEN RAISE EXCEPTION 'REQUIREMENT_CONTRACT_IMMUTABLE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_requirement_contract' AND tgrelid='ontology.requirement_contract'::regclass) THEN
  CREATE TRIGGER ontology_immutable_requirement_contract BEFORE UPDATE OR DELETE ON ontology.requirement_contract
   FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;
COMMIT;
''')
