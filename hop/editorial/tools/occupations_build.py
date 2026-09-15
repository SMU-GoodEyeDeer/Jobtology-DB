"""Generate native contracts/workflows for reviewed product-role decisions."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[3]; OUT=ROOT/'hop/editorial'
def obj(fields):return dict(type='object',properties=fields,required=list(fields),additionalProperties=False)
def text(*values,nullable=False,maximum=8000):
    result=dict(type=['string','null'] if nullable else 'string',minLength=1,maxLength=maximum)
    if values:result['enum']=list(values)+([None] if nullable else [])
    return result
def ids():return dict(type='array',maxItems=1000,items=text(maximum=1000))
schema=obj(dict(schema_version=text('hop-product-occupation-proposal-v1'),release_id=text(),posting_entity_id=text(),
    parent_id=text(nullable=True),source_binding_hash=text(),catalogue_snapshot_id=text(),
    actor=text(),actor_kind=text('human','assistant'),method=text('MANUAL','MODEL_INFERRED'),
    model_id=text(nullable=True),prompt_version=text(nullable=True),resolver_version=text(),reason=text(),
    disposition=text('MATCH','OUT_OF_SCOPE','UNRESOLVED'),occupation_id=text(nullable=True),
    unresolved_reason=text('EXTRACTION_NOT_ACCEPTED','NO_REVIEWED_DUTIES','MIXED_ROLES','AMBIGUOUS_DUTIES','INSUFFICIENT_EVIDENCE',nullable=True),
    considered_duty_ids=ids(),considered_position_ids=ids(),evidence_ids=ids()))
(OUT/'schemas/product-occupation-proposal-v1.schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n')
compact=json.dumps(schema,ensure_ascii=False,separators=(',',':'))
(OUT/'sql/008_occupation_contract.sql').write_text('''-- Immutable proposal contract; scores and automatic acceptance are not input fields.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.occupation_contract(version text PRIMARY KEY,schema jsonb NOT NULL,content_hash text NOT NULL);
INSERT INTO ontology.occupation_contract SELECT 'hop-product-occupation-proposal-v1',s,ontology.hash(s)
FROM (SELECT $schema$'''+compact+'''$schema$::jsonb s) v ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.occupation_contract WHERE version='hop-product-occupation-proposal-v1'
  AND schema=$schema$'''+compact+'''$schema$::jsonb AND content_hash=ontology.hash(schema))
 THEN RAISE EXCEPTION 'OCCUPATION_CONTRACT_CHANGED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_occupation_contract_immutable' AND tgrelid='ontology.occupation_contract'::regclass) THEN
  CREATE TRIGGER ontology_occupation_contract_immutable BEFORE UPDATE OR DELETE ON ontology.occupation_contract
  FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;
COMMIT;
''')
