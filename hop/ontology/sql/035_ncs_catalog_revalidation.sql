BEGIN;

-- Exact full-input equivalence is recorded separately from original inference
-- pins and semantic review. No source input, model response or graph is rewritten.
CREATE TABLE IF NOT EXISTS catalog.ncs_catalog_revalidation (
 revalidation_id text PRIMARY KEY CHECK(revalidation_id ~ '^ncs-revalidation:[0-9a-f]{64}$'),
 original_pin text NOT NULL REFERENCES ingestion.run(run_id),
 current_pin text NOT NULL REFERENCES ingestion.run(run_id),
 policy text NOT NULL CHECK(policy='FULL_CONTEXT_EQUAL_V1'),
 catalog_hash text NOT NULL,
 context_hash text NOT NULL,
 unit_count bigint NOT NULL CHECK(unit_count>0),
 occupation_count bigint NOT NULL CHECK(occupation_count>0),
 occupation_catalog_hashes jsonb NOT NULL CHECK(jsonb_typeof(occupation_catalog_hashes)='object'),
 proof jsonb NOT NULL CHECK(jsonb_typeof(proof)='object'),
 verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(original_pin,current_pin,policy),
 CHECK(original_pin<>current_pin)
);
CREATE INDEX IF NOT EXISTS ncs_catalog_revalidation_pins
 ON catalog.ncs_catalog_revalidation(original_pin,current_pin);
CREATE OR REPLACE FUNCTION catalog._immutable_ncs_catalog_revalidation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_NCS_CATALOG_REVALIDATION'; END $$;
DROP TRIGGER IF EXISTS ncs_catalog_revalidation_immutable ON catalog.ncs_catalog_revalidation;
CREATE TRIGGER ncs_catalog_revalidation_immutable BEFORE UPDATE OR DELETE
 ON catalog.ncs_catalog_revalidation FOR EACH ROW EXECUTE FUNCTION catalog._immutable_ncs_catalog_revalidation();
DROP TRIGGER IF EXISTS ncs_catalog_revalidation_no_truncate ON catalog.ncs_catalog_revalidation;
CREATE TRIGGER ncs_catalog_revalidation_no_truncate BEFORE TRUNCATE
 ON catalog.ncs_catalog_revalidation FOR EACH STATEMENT EXECUTE FUNCTION catalog._immutable_ncs_catalog_revalidation();

-- Reconstruct exactly the SQL 032 catalogue fields, labels and v2 hierarchy
-- context using all selected archived READY units. No prepare function is called.
CREATE OR REPLACE FUNCTION catalog._ncs_catalog_full_snapshot(pin text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE answer jsonb;
BEGIN
 IF to_regclass('enrichment.metadata_occupation_catalog') IS NULL
  OR to_regclass('enrichment.metadata_occupation_catalog_context') IS NULL
  OR to_regprocedure('enrichment.hash(text)') IS NULL
 THEN RAISE EXCEPTION 'NCS_REVALIDATION_MATCHING_CATALOG_UNAVAILABLE'; END IF;
 EXECUTE $snapshot$
 WITH raw AS MATERIALIZED (
  SELECT r.normalized AS data FROM ingestion.ready_record r
  WHERE r.run_id=$1 AND r.source_id='ncs_competency'
 ), quality AS (
  SELECT count(*) AS units,count(DISTINCT data->>'code')=count(*) AND bool_and(
   coalesce(jsonb_typeof(data->'code')='string' AND length(btrim(data->>'code'))>0,false)) AS unique_unit_codes,
   bool_and(coalesce(jsonb_typeof(data->'occupation_code')='string'
    AND data->>'occupation_code' ~ '^[0-9]{8}$',false)) AS valid_occupation_codes,
   bool_or(data?'classification_names') AS hierarchical FROM raw
 ), units AS MATERIALIZED (
  SELECT r.*,data->>'occupation_code' AS code,data->>'occupation_name' AS name,
   CASE WHEN q.hierarchical THEN data->'classification_names'
    ELSE jsonb_build_array(data->>'classification_1',data->>'classification_2',data->>'classification_3') END AS classes,
   q.hierarchical FROM raw r CROSS JOIN quality q
 ), grouped AS MATERIALIZED (
  SELECT code,min(name) AS name,
   jsonb_build_array(min(data->>'classification_1'),min(data->>'classification_2'),min(data->>'classification_3')) AS legacy_classes,
   min(classes::text)::jsonb AS context_classes,
   count(DISTINCT classes)=1 AND bool_and(CASE WHEN jsonb_typeof(classes)='array' THEN
    jsonb_array_length(classes)=3 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(classes) p
     WHERE jsonb_typeof(p)<>'string' OR length(btrim(p#>>'{}'))=0) ELSE false END) AS valid_hierarchy,
   lower(string_agg(concat_ws(' ',name,data->>'name',data->>'definition'),' ' ORDER BY data->>'code')) AS search_text,
   enrichment.hash(jsonb_agg(data ORDER BY data->>'code')::text) AS catalog_hash,
   bool_or(hierarchical) AS hierarchical FROM units GROUP BY code
 ), labels AS (
  SELECT code,jsonb_agg(name ORDER BY obsolete,name) AS names FROM (
   SELECT DISTINCT code,left(data->>'name',100) AS name,
    CASE WHEN data->>'name' ~ '(구버전|폐지)' THEN 1 ELSE 0 END AS obsolete FROM units
  ) names GROUP BY code
 ), reconstructed AS MATERIALIZED (
  SELECT g.*,jsonb_build_object('occupation_code',g.code,'occupation_name',g.name,
   'classification_names',g.legacy_classes,
   'unit_names',(SELECT coalesce(jsonb_agg(value ORDER BY ordinal),'[]') FROM
    jsonb_array_elements(l.names) WITH ORDINALITY x(value,ordinal) WHERE ordinal<=8),
   'search_text',g.search_text,'catalog_hash',g.catalog_hash) AS catalog,
   enrichment.hash(jsonb_build_array('ncs-occupation-context-v2',g.catalog_hash,g.context_classes)::text) AS context_hash
  FROM grouped g JOIN labels l USING(code)
 ), manifest AS (
  SELECT count(*) AS occupation_count,bool_and(valid_hierarchy) AS valid_hierarchy,
   enrichment.hash(jsonb_agg(jsonb_build_array(code,context_hash) ORDER BY code)::text) AS context_hash,
   enrichment.hash(jsonb_agg(catalog ORDER BY code)::text) AS catalog_hash,
   jsonb_object_agg(code,catalog_hash) AS occupation_catalog_hashes FROM reconstructed
 ), contexts AS MATERIALIZED (
  SELECT r.*,jsonb_build_object('occupation_code',r.code,'classification_names',r.context_classes,
   'hierarchy_basis',CASE WHEN r.hierarchical THEN 'SOURCE_CLASSIFICATION_NAMES' ELSE 'LEGACY_FLAT_SOURCE' END,
   'context_version','ncs-occupation-context-v2','source_catalog_hash',r.catalog_hash,
   'context_hash',r.context_hash,'catalog_context_hash',m.context_hash) AS context
  FROM reconstructed r CROSS JOIN manifest m
 ), frozen_catalog AS MATERIALIZED (
  SELECT * FROM enrichment.metadata_occupation_catalog WHERE ncs_run_id=$1
 ), frozen_context AS MATERIALIZED (
  SELECT * FROM enrichment.metadata_occupation_catalog_context WHERE ncs_run_id=$1
 ) SELECT jsonb_build_object('run_id',$1,'unit_count',q.units,'unique_unit_codes',q.unique_unit_codes,
  'valid_occupation_codes',q.valid_occupation_codes,'valid_hierarchy',m.valid_hierarchy,
  'occupation_count',m.occupation_count,'catalog_hash',m.catalog_hash,'context_hash',m.context_hash,
  'occupation_catalog_hashes',m.occupation_catalog_hashes,
  'frozen_catalog_count',(SELECT count(*) FROM frozen_catalog),
  'frozen_context_count',(SELECT count(*) FROM frozen_context),
  'frozen_catalog_mismatches',(SELECT count(*) FROM contexts r FULL JOIN frozen_catalog c ON c.occupation_code=r.code
   WHERE r.catalog IS DISTINCT FROM to_jsonb(c)-'ncs_run_id'),
  'frozen_context_mismatches',(SELECT count(*) FROM contexts r FULL JOIN frozen_context c ON c.occupation_code=r.code
   WHERE r.context IS DISTINCT FROM to_jsonb(c)-'ncs_run_id'))
 FROM quality q CROSS JOIN manifest m
 $snapshot$ INTO answer USING pin;
 RETURN answer;
END $$;

CREATE OR REPLACE FUNCTION catalog.revalidate_ncs_catalog(original_pin text,current_pin text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE before_snapshot jsonb; after_snapshot jsonb; identity text; answer catalog.ncs_catalog_revalidation%ROWTYPE;
BEGIN
 IF original_pin IS NULL OR current_pin IS NULL OR original_pin=current_pin
  OR length(original_pin) NOT BETWEEN 1 AND 200 OR length(current_pin) NOT BETWEEN 1 AND 200
 THEN RAISE EXCEPTION 'INVALID_NCS_REVALIDATION_PINS'; END IF;
 IF (SELECT count(*) FROM ingestion.run r WHERE r.run_id IN(original_pin,current_pin)
  AND r.source_id='ncs_competency' AND r.state='READY' AND r.mode IN('FULL','REPLAY'))<>2
  OR current_pin IS DISTINCT FROM (SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency')
 THEN RAISE EXCEPTION 'NCS_REVALIDATION_REQUIRES_EXACT_READY_PINS'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ncs-full-context-revalidation:'||original_pin||':'||current_pin,0));
 before_snapshot:=catalog._ncs_catalog_full_snapshot(original_pin);
 after_snapshot:=catalog._ncs_catalog_full_snapshot(current_pin);
 IF coalesce((before_snapshot->>'unit_count')::bigint,0)=0
  OR coalesce((after_snapshot->>'unit_count')::bigint,0)=0
  OR before_snapshot->'unique_unit_codes' IS DISTINCT FROM 'true'::jsonb
  OR after_snapshot->'unique_unit_codes' IS DISTINCT FROM 'true'::jsonb
  OR before_snapshot->'valid_occupation_codes' IS DISTINCT FROM 'true'::jsonb
  OR after_snapshot->'valid_occupation_codes' IS DISTINCT FROM 'true'::jsonb
  OR before_snapshot->'valid_hierarchy' IS DISTINCT FROM 'true'::jsonb
  OR after_snapshot->'valid_hierarchy' IS DISTINCT FROM 'true'::jsonb
 THEN RAISE EXCEPTION 'NCS_REVALIDATION_ARCHIVE_UNVERIFIABLE'; END IF;
 IF before_snapshot->>'frozen_catalog_count' IS DISTINCT FROM before_snapshot->>'occupation_count'
  OR before_snapshot->>'frozen_context_count' IS DISTINCT FROM before_snapshot->>'occupation_count'
  OR (before_snapshot->>'frozen_catalog_mismatches')::bigint<>0
  OR (before_snapshot->>'frozen_context_mismatches')::bigint<>0
 THEN RAISE EXCEPTION 'NCS_REVALIDATION_FROZEN_CONTEXT_UNVERIFIABLE'; END IF;
 IF before_snapshot->>'unit_count' IS DISTINCT FROM after_snapshot->>'unit_count'
  OR before_snapshot->>'occupation_count' IS DISTINCT FROM after_snapshot->>'occupation_count'
  OR before_snapshot->>'catalog_hash' IS DISTINCT FROM after_snapshot->>'catalog_hash'
  OR before_snapshot->>'context_hash' IS DISTINCT FROM after_snapshot->>'context_hash'
  OR before_snapshot->'occupation_catalog_hashes' IS DISTINCT FROM after_snapshot->'occupation_catalog_hashes'
 THEN RAISE EXCEPTION 'NCS_REVALIDATION_FULL_CONTEXT_CHANGED'; END IF;
 IF current_pin IS DISTINCT FROM (SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency')
 THEN RAISE EXCEPTION 'NCS_REVALIDATION_CURRENT_PIN_CHANGED'; END IF;
 identity:='ncs-revalidation:'||encode(sha256(convert_to(jsonb_build_array('FULL_CONTEXT_EQUAL_V1',
  original_pin,current_pin,before_snapshot->>'catalog_hash',before_snapshot->>'context_hash')::text,'UTF8')),'hex');
 INSERT INTO catalog.ncs_catalog_revalidation(revalidation_id,original_pin,current_pin,policy,catalog_hash,
  context_hash,unit_count,occupation_count,occupation_catalog_hashes,proof)
 VALUES(identity,original_pin,current_pin,'FULL_CONTEXT_EQUAL_V1',before_snapshot->>'catalog_hash',
  before_snapshot->>'context_hash',(before_snapshot->>'unit_count')::bigint,
  (before_snapshot->>'occupation_count')::bigint,before_snapshot->'occupation_catalog_hashes',
  jsonb_build_object('original',before_snapshot-'occupation_catalog_hashes',
   'current',after_snapshot-'occupation_catalog_hashes','review_status_changed',false,'paid_calls',0))
 ON CONFLICT DO NOTHING;
 SELECT * INTO STRICT answer FROM catalog.ncs_catalog_revalidation r WHERE r.revalidation_id=identity;
 RETURN to_jsonb(answer)-'occupation_catalog_hashes';
END $$;

CREATE OR REPLACE FUNCTION catalog._ncs_catalog_revalidation(original text,code text,original_hash text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('original_pin',r.original_pin,'current_pin',r.current_pin,
  'policy',r.policy,'context_hash',r.context_hash,'verified_at',r.verified_at)
 FROM catalog.ncs_catalog_revalidation r JOIN ingestion.latest_ready_run n
  ON n.source_id='ncs_competency' AND n.run_id=r.current_pin
 WHERE r.original_pin=$1 AND r.policy='FULL_CONTEXT_EQUAL_V1'
  AND r.occupation_catalog_hashes->>$2=$3
$$;

CREATE OR REPLACE FUNCTION catalog.inferred_occupation_context_v1(
 occupation_codes text[] DEFAULT NULL,page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE answer jsonb;
BEGIN
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF occupation_codes IS NOT NULL AND (cardinality(occupation_codes)>100 OR EXISTS(
  SELECT 1 FROM unnest(occupation_codes) code
  WHERE code IS NULL OR code !~ '^([0-9]{8}|[0-9]{2}-[0-9]{4}\.[0-9]{2})$'))
 THEN RAISE EXCEPTION 'INVALID_OCCUPATION_CONTEXT_FILTER'; END IF;
 WITH inferred_rows AS MATERIALIZED (
  SELECT * FROM catalog._inferred_occupation_rows(occupation_codes)
  WHERE occupation_codes IS NULL OR occupation_code=ANY(occupation_codes)
 ), wanted_postings AS MATERIALIZED (
  SELECT source_id,posting_key,bool_or(occupation_scheme='NCS') AS needs_ncs,
   bool_or(occupation_scheme='ONET') AS needs_onet
  FROM inferred_rows GROUP BY source_id,posting_key
 ), current_observations AS MATERIALIZED (
  SELECT p.posting_id,p.source_id,p.run_id,p.data_as_of,p.normalized,
   CASE WHEN w.needs_ncs THEN encode(sha256(convert_to(p.normalized::text,'UTF8')),'hex') END AS normalized_hash,
   CASE WHEN w.needs_onet THEN catalog._live_source_fact_hash(p.source_id,p.normalized) END AS source_facts_sha256
  FROM catalog._live_source_observations() p
  JOIN wanted_postings w ON w.source_id=p.source_id AND w.posting_key=p.posting_id
 ), associations AS MATERIALIZED (
  SELECT r.*,p.normalized AS current_normalized,p.run_id AS current_run_id,
   p.data_as_of AS current_data_as_of,
   CASE WHEN p.posting_id IS NULL THEN 'STALE'
    WHEN r.occupation_scheme='NCS' AND r.normalized_hash IS NOT NULL THEN
     CASE WHEN r.normalized_hash=p.normalized_hash THEN 'CURRENT' ELSE 'STALE' END
    WHEN r.occupation_scheme='ONET' AND p.source_facts_sha256 IS NOT NULL THEN
     CASE WHEN r.source_facts_sha256=p.source_facts_sha256 THEN 'CURRENT' ELSE 'STALE' END
    ELSE 'UNKNOWN' END AS source_freshness
  FROM inferred_rows r LEFT JOIN current_observations p
   ON p.source_id=r.source_id AND p.posting_id=r.posting_key
 ), page AS (
  SELECT * FROM associations ORDER BY CASE source_id WHEN 'jobkorea' THEN 0 WHEN 'job_alio' THEN 1 ELSE 2 END,posting_key COLLATE "C",
   occupation_scheme COLLATE "C",occupation_code COLLATE "C",association_id COLLATE "C"
  LIMIT page_size OFFSET page_offset
 )
 SELECT jsonb_build_object('contract_version','jobtology-inferred-occupation-context-v1',
  'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
  'competency_evidence',false,'limit',page_size,'offset',page_offset,
  'filters',jsonb_build_object('occupation_codes',occupation_codes),
  'total',(SELECT count(*) FROM associations),
  'summary',jsonb_build_object('associations',(SELECT count(*) FROM associations),
   'postings',(SELECT count(DISTINCT (source_id,posting_key)) FROM associations),
   'source_current_associations',(SELECT count(*) FROM associations WHERE source_freshness='CURRENT'),
   'catalog_current_associations',(SELECT count(*) FROM associations WHERE catalog_freshness='CURRENT'),
   'stale_associations',(SELECT count(*) FROM associations WHERE source_freshness='STALE' OR catalog_freshness='STALE'),
   'unknown_associations',(SELECT count(*) FROM associations WHERE source_freshness='UNKNOWN'),
   'current_associations',(SELECT count(*) FROM associations WHERE source_freshness='CURRENT' AND catalog_freshness='CURRENT'),
   'by_source',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.source_id COLLATE "C"),'[]'::jsonb)
    FROM (SELECT source_id,count(*) AS associations,count(DISTINCT posting_key) AS postings,
     count(*) FILTER (WHERE source_freshness='CURRENT') AS source_current_associations,
     count(*) FILTER (WHERE catalog_freshness='CURRENT') AS catalog_current_associations,
     count(*) FILTER (WHERE source_freshness='CURRENT' AND catalog_freshness='CURRENT') AS current_associations
     FROM associations GROUP BY source_id) s),
   'by_occupation',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.occupation_scheme COLLATE "C",
     s.occupation_code COLLATE "C"),'[]'::jsonb)
    FROM (SELECT occupation_scheme,occupation_code,min(occupation_name) AS occupation_name,
     count(*) AS associations,count(DISTINCT (source_id,posting_key)) AS postings,
     count(*) FILTER (WHERE source_freshness='CURRENT') AS source_current_associations,
     count(*) FILTER (WHERE catalog_freshness='CURRENT') AS catalog_current_associations,
     count(*) FILTER (WHERE source_freshness='CURRENT' AND catalog_freshness='CURRENT') AS current_associations
     FROM associations GROUP BY occupation_scheme,occupation_code) s)),
  'items',(SELECT coalesce(jsonb_agg(jsonb_build_object(
   'posting_key',posting_key,'posting_identity',posting_identity,'source_id',source_id,
   'occupation_scheme',occupation_scheme,'occupation_code',occupation_code,'occupation_name',occupation_name,
   'association_id',association_id,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
   'review_status',review_status,'stage',stage,'confidence',NULL,'confidence_state',confidence_state,
   'source_freshness',source_freshness,'catalog_freshness',catalog_freshness,
   'catalog_revalidation',CASE WHEN occupation_scheme='NCS' THEN
    catalog._ncs_catalog_revalidation(catalog_pin,occupation_code,catalog_hash) END,
   'posting',CASE WHEN current_normalized IS NOT NULL THEN catalog._live_source_posting_item(
    current_normalized,posting_key,source_id,current_run_id,current_data_as_of) END,
   'source_pins',jsonb_build_object('run_id',source_run_id,'source_hash',source_hash,
    'normalized_hash',normalized_hash,'source_facts_sha256',source_facts_sha256),
   'catalog_pins',jsonb_build_object('pin',catalog_pin,'catalog_hash',catalog_hash))
   ORDER BY CASE source_id WHEN 'jobkorea' THEN 0 WHEN 'job_alio' THEN 1 ELSE 2 END,posting_key COLLATE "C",occupation_scheme COLLATE "C",
    occupation_code COLLATE "C",association_id COLLATE "C"),'[]'::jsonb) FROM page)) INTO answer;
 RETURN answer;
END $$;

REVOKE ALL ON catalog.ncs_catalog_revalidation FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog._immutable_ncs_catalog_revalidation(),catalog._ncs_catalog_full_snapshot(text),
 catalog.revalidate_ncs_catalog(text,text),catalog._ncs_catalog_revalidation(text,text,text),
 catalog.inferred_occupation_context_v1(text[],integer,integer) FROM PUBLIC;
COMMIT;
