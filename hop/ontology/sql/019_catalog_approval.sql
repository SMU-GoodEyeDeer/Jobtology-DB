-- Independent source-only read pointer. Never changes ontology.active_release.
BEGIN;
CREATE SCHEMA IF NOT EXISTS catalog;
REVOKE ALL ON SCHEMA catalog FROM PUBLIC;

CREATE TABLE IF NOT EXISTS catalog.catalog_approval (
 approval_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 database_id text NOT NULL,
 load_id text NOT NULL REFERENCES ontology.graph_load,
 manifest_hash text NOT NULL,
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS catalog.catalog_active_release (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 approval_id bigint NOT NULL REFERENCES catalog.catalog_approval
);
REVOKE ALL ON catalog.catalog_approval,catalog.catalog_active_release FROM PUBLIC;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='catalog.catalog_approval'::regclass
  AND tgname='catalog_approval_immutable') THEN
  CREATE TRIGGER catalog_approval_immutable BEFORE UPDATE OR DELETE ON catalog.catalog_approval
   FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION catalog._approved_release(release_choice text DEFAULT NULL)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE selected catalog.catalog_approval%ROWTYPE; r ontology.corpus_release%ROWTYPE;
 latest ontology.graph_load%ROWTYPE;
BEGIN
 SELECT a.* INTO selected FROM catalog.catalog_active_release p
 JOIN catalog.catalog_approval a USING(approval_id) WHERE p.singleton;
 IF NOT FOUND OR (nullif(btrim(release_choice),'') IS NOT NULL AND selected.release_id<>release_choice)
 THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_APPROVED'; END IF;
 SELECT * INTO r FROM ontology.corpus_release WHERE release_id=selected.release_id;
 IF r.state IN ('REVOKED','FAILED') THEN RAISE EXCEPTION 'CATALOG_RELEASE_UNAVAILABLE'; END IF;
 SELECT * INTO latest FROM ontology.graph_load WHERE database_id=selected.database_id
 ORDER BY started_at DESC,load_id DESC LIMIT 1;
 IF r.state<>'PREPARING' OR r.manifest IS NULL OR r.graph_verified_at IS NULL OR
  r.manifest_hash IS DISTINCT FROM selected.manifest_hash OR
  r.manifest_hash IS DISTINCT FROM ontology.hash(r.manifest) OR
  r.manifest IS DISTINCT FROM ontology.graph_inventory_manifest(r.release_id) OR
  latest.load_id IS DISTINCT FROM selected.load_id OR latest.release_id IS DISTINCT FROM r.release_id OR
  latest.manifest_hash IS DISTINCT FROM selected.manifest_hash OR latest.state IS DISTINCT FROM 'VERIFIED' OR
  latest.finished_at IS NULL OR latest.node_count IS DISTINCT FROM (r.manifest->>'nodes')::bigint OR
  latest.edge_count IS DISTINCT FROM (r.manifest->>'edges')::bigint
  THEN RAISE EXCEPTION 'CATALOG_APPROVAL_STALE'; END IF;
  PERFORM ontology.check_frozen_sources(r.release_id);
  PERFORM ontology.verify_catalog_source_v1(r.release_id);
 RETURN r.release_id;
END $$;

CREATE OR REPLACE FUNCTION catalog.approve_catalog_release(release_id text,database_id text,actor text,reason text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE r ontology.corpus_release%ROWTYPE; latest ontology.graph_load%ROWTYPE; approved bigint;
BEGIN
 IF nullif(btrim(release_id),'') IS NULL OR nullif(btrim(database_id),'') IS NULL OR
  nullif(btrim(actor),'') IS NULL OR nullif(btrim(reason),'') IS NULL
 THEN RAISE EXCEPTION 'CATALOG_APPROVAL_PROVENANCE_REQUIRED'; END IF;
 -- Serialize all approvals, including the first insertion of the singleton pointer.
 PERFORM pg_advisory_xact_lock(71243,19001);
 SELECT * INTO r FROM ontology.corpus_release WHERE corpus_release.release_id=approve_catalog_release.release_id FOR UPDATE;
 IF NOT FOUND OR r.state<>'PREPARING' OR r.manifest IS NULL OR r.graph_verified_at IS NULL OR
  r.manifest_hash IS DISTINCT FROM ontology.hash(r.manifest) OR
  r.manifest IS DISTINCT FROM ontology.graph_inventory_manifest(r.release_id)
 THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_VERIFIED'; END IF;
 SELECT * INTO latest FROM ontology.graph_load WHERE graph_load.database_id=approve_catalog_release.database_id
 ORDER BY started_at DESC,load_id DESC LIMIT 1;
 IF latest.release_id IS DISTINCT FROM r.release_id OR latest.state IS DISTINCT FROM 'VERIFIED' OR
  latest.manifest_hash IS DISTINCT FROM r.manifest_hash OR latest.finished_at IS NULL OR
  latest.node_count IS DISTINCT FROM (r.manifest->>'nodes')::bigint OR
  latest.edge_count IS DISTINCT FROM (r.manifest->>'edges')::bigint
  THEN RAISE EXCEPTION 'CATALOG_GRAPH_LOAD_NOT_VERIFIED'; END IF;
  PERFORM ontology.check_frozen_sources(r.release_id);
  PERFORM ontology.verify_catalog_source_v1(r.release_id);
 SELECT a.approval_id INTO approved FROM catalog.catalog_active_release p
 JOIN catalog.catalog_approval a USING(approval_id)
 WHERE p.singleton AND a.release_id=r.release_id AND a.load_id=latest.load_id;
 IF approved IS NULL THEN
  INSERT INTO catalog.catalog_approval(release_id,database_id,load_id,manifest_hash,actor,reason)
  VALUES(r.release_id,database_id,latest.load_id,r.manifest_hash,actor,reason) RETURNING approval_id INTO approved;
 END IF;
 INSERT INTO catalog.catalog_active_release(singleton,approval_id) VALUES(true,approved)
 ON CONFLICT(singleton) DO UPDATE SET approval_id=excluded.approval_id;
 RETURN approved;
END $$;

CREATE OR REPLACE FUNCTION catalog.catalog_context_v1(release_choice text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE id text;
BEGIN
 id:=catalog._approved_release(release_choice);
 RETURN (SELECT jsonb_build_object('contract_version','hop-catalog-source-v1','release_id',r.release_id,
  'data_as_of',r.data_as_of,'manifest_hash',r.manifest_hash,
  'source_profile',jsonb_build_object('kind','SOURCE_ONLY','analysis_available',false,
   'capabilities',jsonb_build_array('entities','source_relations')))
  FROM ontology.corpus_release r WHERE r.release_id=id);
END $$;

CREATE OR REPLACE FUNCTION catalog.catalog_entities_v1(release_choice text DEFAULT NULL,entity_kind text DEFAULT NULL,
 page_size integer DEFAULT 100,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE id text; items jsonb;
BEGIN
 id:=catalog._approved_release(release_choice);
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_CATALOG_PAGE'; END IF;
 IF entity_kind IS NOT NULL AND entity_kind NOT IN ('occupation','ncsCompetency','organization','jobPosting',
  'qualification','examSession','careerRank','ncsUnitFamily','ncsClass','conceptScheme')
 THEN RAISE EXCEPTION 'INVALID_CATALOG_ENTITY_KIND'; END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY entity_id COLLATE "C"),'[]'::jsonb) INTO items FROM (
  SELECT e.entity_id,e.kind,e.code,e.scheme_id,v.revision_id,v.name,v.payload_hash
  FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id)
  JOIN ontology.revision v USING(revision_id)
  WHERE m.release_id=id AND e.kind IN ('occupation','ncsCompetency','organization','jobPosting',
   'qualification','examSession','careerRank','ncsUnitFamily','ncsClass','conceptScheme')
   AND EXISTS(SELECT 1 FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
    JOIN ontology.release_source_run p USING(release_id,run_id) WHERE s.release_id=m.release_id AND s.entity_id=m.entity_id)
   AND (entity_kind IS NULL OR e.kind=entity_kind)
  ORDER BY e.entity_id COLLATE "C" LIMIT page_size OFFSET page_offset) x;
 RETURN catalog.catalog_context_v1(id)||jsonb_build_object('entity_kind',entity_kind,
  'limit',page_size,'offset',page_offset,'items',items);
END $$;

CREATE OR REPLACE FUNCTION catalog.catalog_entity_v1(release_choice text,entity_choice text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE id text; item jsonb;
BEGIN
 id:=catalog._approved_release(release_choice);
 SELECT jsonb_build_object('entity_id',e.entity_id,'kind',e.kind,'code',e.code,'scheme_id',e.scheme_id,
  'revision_id',v.revision_id,'name',v.name,'payload_hash',v.payload_hash,'schema_version',v.schema_version,
  'source_facts',coalesce((SELECT jsonb_object_agg(p.key,p.value) FROM jsonb_each(v.payload) p
   WHERE p.key = ANY(ARRAY['aliases','source_status','date_posted','closing_date','date_precision',
    'organization_id','occupation_id','qualification_id','parent_id','base_code','version',
    'rank_level','level','depth','taxonomy_version','edition_policy','label_status',
    'definition_status','version_selection','scheme_code','year','round','category_code','dates'])),
   '{}'::jsonb)) INTO item
 FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id)
 JOIN ontology.revision v USING(revision_id)
 WHERE m.release_id=id AND m.entity_id=entity_choice AND e.kind IN ('occupation','ncsCompetency',
  'organization','jobPosting','qualification','examSession','careerRank','ncsUnitFamily','ncsClass','conceptScheme')
  AND EXISTS(SELECT 1 FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
   JOIN ontology.release_source_run p USING(release_id,run_id) WHERE s.release_id=m.release_id AND s.entity_id=m.entity_id);
 IF item IS NULL THEN RAISE EXCEPTION 'CATALOG_ENTITY_NOT_IN_RELEASE'; END IF;
 RETURN catalog.catalog_context_v1(id)||jsonb_build_object('entity',item);
END $$;

CREATE OR REPLACE FUNCTION catalog.catalog_relations_v1(release_choice text,entity_choice text,
 page_size integer DEFAULT 100,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE id text; items jsonb;
BEGIN
 id:=catalog._approved_release(release_choice);
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_CATALOG_PAGE'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id)
  WHERE m.release_id=id AND m.entity_id=entity_choice AND e.kind IN ('occupation','ncsCompetency',
   'organization','jobPosting','qualification','examSession','careerRank','ncsUnitFamily','ncsClass','conceptScheme')
   AND EXISTS(SELECT 1 FROM ontology.revision_support rs JOIN ontology.input_record i USING(release_id,record_id)
    JOIN ontology.release_source_run p USING(release_id,run_id) WHERE rs.release_id=m.release_id AND rs.entity_id=m.entity_id))
 THEN RAISE EXCEPTION 'CATALOG_ENTITY_NOT_IN_RELEASE'; END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY relation_id COLLATE "C"),'[]'::jsonb) INTO items FROM (
  SELECT r.relation_id,r.subject_id,r.predicate,r.object_id,r.assertion_kind,r.acceptance_policy
  FROM ontology.source_relation r
  WHERE entity_choice IN (r.subject_id,r.object_id)
   AND EXISTS(SELECT 1 FROM ontology.release_relation m
    JOIN ontology.release_revision s ON s.release_id=m.release_id AND s.entity_id=r.subject_id
    JOIN ontology.release_revision o ON o.release_id=m.release_id AND o.entity_id=r.object_id
    JOIN ontology.input_record i ON i.release_id=m.release_id AND i.record_id=m.record_id
    JOIN ontology.release_source_run p ON p.release_id=i.release_id AND p.run_id=i.run_id
    WHERE m.release_id=id AND m.relation_id=r.relation_id)
  ORDER BY r.relation_id COLLATE "C" LIMIT page_size OFFSET page_offset) x;
 RETURN catalog.catalog_context_v1(id)||jsonb_build_object('entity_id',entity_choice,
  'limit',page_size,'offset',page_offset,'items',items);
END $$;

CREATE OR REPLACE FUNCTION catalog.catalog_summary_v1(release_choice text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE id text;
BEGIN
 id:=catalog._approved_release(release_choice);
 RETURN catalog.catalog_context_v1(id)||jsonb_build_object(
  'entity_counts',coalesce((SELECT jsonb_object_agg(kind,n) FROM (
   SELECT e.kind,count(*) n FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id)
   WHERE m.release_id=id AND e.kind IN ('occupation','ncsCompetency','organization','jobPosting',
    'qualification','examSession','careerRank','ncsUnitFamily','ncsClass','conceptScheme')
    AND EXISTS(SELECT 1 FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
     JOIN ontology.release_source_run p USING(release_id,run_id) WHERE s.release_id=m.release_id AND s.entity_id=m.entity_id)
    GROUP BY e.kind) x),'{}'::jsonb),
  'posting_selection_outcomes',coalesce((SELECT jsonb_object_agg(outcome,n) FROM (
   SELECT coalesce(p.outcome,'SELECTION_PENDING') outcome,count(*) n
   FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id)
   LEFT JOIN ontology.posting_selection p ON p.release_id=m.release_id AND p.entity_id=m.entity_id
   WHERE m.release_id=id AND e.kind='jobPosting'
    AND EXISTS(SELECT 1 FROM ontology.revision_support s JOIN ontology.input_record i USING(release_id,record_id)
     JOIN ontology.release_source_run sp USING(release_id,run_id) WHERE s.release_id=m.release_id AND s.entity_id=m.entity_id)
   GROUP BY coalesce(p.outcome,'SELECTION_PENDING')) x),'{}'::jsonb));
END $$;

-- PostgreSQL grants EXECUTE to PUBLIC by default; the grant script is opt-in.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA catalog FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA catalog FROM PUBLIC;
COMMIT;
