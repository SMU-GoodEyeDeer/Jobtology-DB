BEGIN;
CREATE OR REPLACE FUNCTION ontology.cohort_read_gate_v1(choice text,key text,preview boolean) RETURNS text LANGUAGE plpgsql AS $$
DECLARE id text; BEGIN
 id:=ontology.read_release_v1(choice,preview);
 IF NOT EXISTS(SELECT 1 FROM ontology.posting_cohort WHERE cohort_id=key AND release_id=id) THEN RAISE EXCEPTION 'COHORT_NOT_IN_RELEASE'; END IF;
 PERFORM ontology.verify_posting_cohort_v1(key);RETURN id;
END $$;

CREATE OR REPLACE FUNCTION ontology.cohort_current_states_v1(key text,as_at timestamptz)
RETURNS TABLE(entity_id text,serving_state text,is_fresh boolean) LANGUAGE sql STABLE AS $$
 SELECT m.entity_id,CASE WHEN o.source_status='CLOSED' THEN 'CLOSED' WHEN o.deadline_at<=as_at THEN 'EXPIRED'
  WHEN o.consecutive_absence_count>=2 THEN 'NOT_SEEN' ELSE 'ACTIVE' END,
  o.last_seen_at<=as_at AND as_at-o.last_seen_at<=make_interval(secs=>ontology.source_freshness_seconds_v1(m.source_id))
  AND p.source_watermark_at<=as_at AND as_at-p.source_watermark_at<=make_interval(secs=>ontology.source_freshness_seconds_v1(m.source_id))
 FROM ontology.posting_cohort c JOIN ontology.posting_cohort_posting m USING(cohort_id)
 JOIN ontology.posting_observation o ON o.release_id=c.release_id AND o.entity_id=m.entity_id
 JOIN ontology.source_pin p ON p.release_id=c.release_id AND p.source_id=m.source_id WHERE c.cohort_id=key
$$;

CREATE OR REPLACE FUNCTION ontology.query_posting_cohort_v1(choice text,key text,preview boolean DEFAULT false,
 as_at timestamptz DEFAULT statement_timestamp()) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE id text; BEGIN
 id:=ontology.cohort_read_gate_v1(choice,key,preview);
 IF as_at IS NULL OR NOT isfinite(as_at) OR as_at<(SELECT created_at FROM ontology.corpus_release WHERE release_id=id)
 THEN RAISE EXCEPTION 'INVALID_COHORT_STATE_TIME'; END IF;
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('contract','posting-cohort-job-alio-v1',
  'cohort',(SELECT to_jsonb(c) FROM ontology.posting_cohort c WHERE cohort_id=key),
  'membership',(SELECT to_jsonb(m) FROM ontology.posting_cohort_manifest m WHERE cohort_id=key),
  'checked_at',as_at,'current_state_basis','FROZEN_RELEASE_WITH_DEADLINE_REEVALUATION',
  'active_fresh_count',(SELECT count(*) FROM ontology.cohort_current_states_v1(key,as_at) s
   JOIN ontology.posting_cohort_posting m ON m.cohort_id=key AND m.entity_id=s.entity_id
   WHERE m.outcome='INCLUDED' AND s.serving_state='ACTIVE' AND s.is_fresh),
  'current_included_states',coalesce((SELECT jsonb_object_agg(serving_state,n) FROM (
   SELECT s.serving_state,count(*) n FROM ontology.cohort_current_states_v1(key,as_at) s
   JOIN ontology.posting_cohort_posting m ON m.cohort_id=key AND m.entity_id=s.entity_id
   WHERE m.outcome='INCLUDED' GROUP BY s.serving_state) states),'{}'),
  'exclusion_counts',coalesce((SELECT jsonb_object_agg(reason,n) FROM (
   SELECT reason,count(*) n FROM ontology.posting_cohort_posting m CROSS JOIN LATERAL jsonb_array_elements_text(m.exclusion_reasons) reason
   WHERE m.cohort_id=key GROUP BY reason) reasons),'{}'),
  'publication_ready',false,'notice','Persisted cohort selection and source-scoped counts. Demand aggregates, calibrated publication and graph integration require their separate stages.');
END $$;

CREATE OR REPLACE FUNCTION ontology.query_cohort_members_v1(choice text,key text,preview boolean DEFAULT false,
 cursor_text text DEFAULT NULL,page_size integer DEFAULT 100) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE id text;after_id text;cursor_doc jsonb;membership_hash text;page jsonb;last_id text;more boolean; BEGIN
 id:=ontology.cohort_read_gate_v1(choice,key,preview);
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'INVALID_COHORT_PAGE_SIZE'; END IF;
 SELECT manifest_hash INTO membership_hash FROM ontology.posting_cohort_manifest WHERE cohort_id=key;
 IF nullif(cursor_text,'') IS NOT NULL THEN
  BEGIN
   cursor_text:=convert_from(decode(cursor_text,'hex'),'UTF8');
   IF NOT (cursor_text IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION 'invalid'; END IF;
   cursor_doc:=cursor_text::jsonb;
   IF (SELECT count(*) FROM jsonb_object_keys(cursor_doc))<>4 OR cursor_doc->>'contract' IS DISTINCT FROM 'cohort-members-cursor-v1'
    OR cursor_doc->>'cohort_id' IS DISTINCT FROM key OR cursor_doc->>'manifest_hash' IS DISTINCT FROM membership_hash
    OR jsonb_typeof(cursor_doc->'after_entity_id') IS DISTINCT FROM 'string'
    OR NOT EXISTS(SELECT 1 FROM ontology.posting_cohort_posting WHERE cohort_id=key AND entity_id=cursor_doc->>'after_entity_id')
   THEN RAISE EXCEPTION 'invalid'; END IF;
   after_id:=cursor_doc->>'after_entity_id';
  EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'INVALID_COHORT_CURSOR'; END;
 END IF;
 WITH chosen AS MATERIALIZED (
  SELECT m.* FROM ontology.posting_cohort_posting m WHERE m.cohort_id=key AND (after_id IS NULL OR m.entity_id COLLATE "C">after_id COLLATE "C")
  ORDER BY m.entity_id COLLATE "C" LIMIT page_size
 ) SELECT coalesce(jsonb_agg(to_jsonb(m)||jsonb_build_object('title',r.name,
  'tracks',coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY position_id COLLATE "C") FROM ontology.posting_cohort_track t
   WHERE t.cohort_id=key AND t.entity_id=m.entity_id),'[]'),
  'claim_support',coalesce((SELECT jsonb_agg(to_jsonb(s) ORDER BY position_id COLLATE "C",claim_id COLLATE "C") FROM ontology.posting_cohort_claim s
   WHERE s.cohort_id=key AND s.entity_id=m.entity_id),'[]')) ORDER BY m.entity_id COLLATE "C"),'[]'),max(m.entity_id COLLATE "C")
 INTO page,last_id FROM chosen m JOIN ontology.revision r ON r.revision_id=m.posting_revision_id;
 more:=last_id IS NOT NULL AND EXISTS(SELECT 1 FROM ontology.posting_cohort_posting WHERE cohort_id=key AND entity_id COLLATE "C">last_id COLLATE "C");
 RETURN ontology.read_context_v1(id,preview)||jsonb_build_object('contract','posting-cohort-members-v1','cohort_id',key,'manifest_hash',membership_hash,
  'members',page,'page_size',page_size,'next_cursor',CASE WHEN more THEN encode(convert_to(jsonb_build_object('contract','cohort-members-cursor-v1',
   'cohort_id',key,'manifest_hash',membership_hash,'after_entity_id',last_id)::text,'UTF8'),'hex') END,
  'total_members',(SELECT count(*) FROM ontology.posting_cohort_posting WHERE cohort_id=key),
  'notice','All original source identities remain present, including excluded postings and duplicate non-representatives.');
END $$;
COMMIT;
