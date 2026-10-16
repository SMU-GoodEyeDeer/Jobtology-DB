BEGIN;

-- Adds linked_postings: one row per distinct (posting_source, posting_id) carrying
-- every requested-occupation competency code it links to. The BE derives a
-- per-role denominator (distinct linked postings) and per-unit numerators from it,
-- which summed per-code evidence counts cannot provide without double counting.
CREATE OR REPLACE FUNCTION catalog.product_role_inputs_v1(occupation_codes text[])
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ncs_run ingestion.run%ROWTYPE; qual_run ingestion.run%ROWTYPE;
 source_items jsonb; unit_items jsonb; qualification_items jsonb; evidence_items jsonb;
 posting_items jsonb;
BEGIN
 IF occupation_codes IS NULL OR cardinality(occupation_codes)=0 OR
  EXISTS(SELECT 1 FROM unnest(occupation_codes) code WHERE code IS NULL OR code !~ '^[0-9]{8}$')
 THEN RAISE EXCEPTION 'INVALID_PRODUCT_ROLE_INPUT'; END IF;
 SELECT * INTO ncs_run FROM ingestion.latest_ready_run WHERE source_id='ncs_competency';
 IF NOT FOUND THEN RAISE EXCEPTION 'LIVE_SOURCE_UNAVAILABLE'; END IF;
 SELECT * INTO qual_run FROM ingestion.latest_ready_run WHERE source_id='ncs_qualification';
 source_items:=jsonb_build_array(jsonb_build_object('source_id','ncs_competency',
  'run_id',ncs_run.run_id,'data_as_of',ncs_run.completed_at));
 IF qual_run.run_id IS NOT NULL THEN
  source_items:=source_items||jsonb_build_array(jsonb_build_object('source_id','ncs_qualification',
   'run_id',qual_run.run_id,'data_as_of',qual_run.completed_at));
 END IF;
  SELECT source_items||coalesce(jsonb_agg(jsonb_build_object('source_id','link_publication',
   'publication_id',p.publication_id,'created_at',p.created_at,
   'posting_source',p.posting_source,'run_id',p.run_id,
   'is_latest_publication',p.is_latest_publication)
   ORDER BY p.posting_source COLLATE "C"),'[]'::jsonb)
  INTO source_items FROM catalog._live_link_publications_with_provenance() p;

 WITH units AS MATERIALIZED (
  SELECT c.code,c.name,c.level,c.occupation_code,c.occupation_name
  FROM ingestion.competency c
  WHERE c.run_id=ncs_run.run_id AND c.occupation_code=ANY(occupation_codes)
 ), links AS MATERIALIZED (
  SELECT p.posting_source,p.publication_id,i.posting_id,
   l.value->>'competency_code' AS competency_code
  FROM catalog._live_link_publications_with_provenance() p
  JOIN enrichment.link_publication_item i ON i.publication_id=p.publication_id
   AND catalog._live_link_item_source(i.publication_id,i.payload,i.posting_identity)
    =p.posting_source
  CROSS JOIN LATERAL jsonb_array_elements(coalesce(i.payload->'links','[]'::jsonb)) l(value)
  WHERE left(l.value->>'competency_code',8)=ANY(occupation_codes)
 )
 SELECT
  (SELECT coalesce(jsonb_agg(jsonb_build_object('code',code,'base_code',left(code,10),
   'name',name,'level',level,'occupation_code',occupation_code,
   'occupation_name',occupation_name) ORDER BY code COLLATE "C"),'[]'::jsonb)
   FROM units),
  (SELECT coalesce(jsonb_agg(jsonb_build_object('competency_code',q.competency_code,
   'qualification_code',q.qualification_code,'qualification_name',q.qualification_name,
   'minimum_training_hours',q.minimum_training_hours,
   'total_training_hours',q.total_training_hours)
   ORDER BY q.competency_code COLLATE "C",q.qualification_code COLLATE "C",
    q.qualification_name COLLATE "C"),'[]'::jsonb)
   FROM ingestion.qualification_mapping q JOIN units u ON u.code=q.competency_code
   WHERE q.run_id=qual_run.run_id),
  (SELECT coalesce(jsonb_agg(jsonb_build_object('competency_code',e.competency_code,
   'postings',e.postings,'links',e.links,'publication_ids',e.publication_ids)
   ORDER BY e.competency_code COLLATE "C"),'[]'::jsonb)
   FROM (SELECT competency_code,
    count(DISTINCT (posting_source,posting_id)) AS postings,count(*) AS links,
    array_agg(DISTINCT publication_id COLLATE "C"
     ORDER BY publication_id COLLATE "C") AS publication_ids
    FROM links GROUP BY competency_code) e),
  (SELECT coalesce(jsonb_agg(jsonb_build_object('posting_key',k.posting_key,
   'competency_codes',k.competency_codes) ORDER BY k.posting_key COLLATE "C"),'[]'::jsonb)
   FROM (SELECT posting_source||':'||posting_id AS posting_key,
    array_agg(DISTINCT competency_code COLLATE "C"
     ORDER BY competency_code COLLATE "C") AS competency_codes
    FROM links GROUP BY posting_source,posting_id) k)
 INTO unit_items,qualification_items,evidence_items,posting_items;
 RETURN jsonb_build_object('contract_version','jobtology-product-role-inputs-v1',
  'sources',source_items,'units',unit_items,
  'qualifications',qualification_items,'evidence',evidence_items,
  'linked_postings',posting_items);
END $$;

REVOKE ALL ON FUNCTION catalog.product_role_inputs_v1(text[]) FROM PUBLIC;
COMMIT;
