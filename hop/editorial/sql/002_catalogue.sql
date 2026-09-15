-- Native editorial source capture. No fetches, model requests or implicit reviews.
BEGIN;
CREATE TABLE IF NOT EXISTS editorial.snapshot (
 snapshot_id text PRIMARY KEY CHECK(snapshot_id ~ '^[0-9a-f]{64}$'),
 source_id text NOT NULL CHECK(source_id='INTERNAL_EDITORIAL'),
 catalogue_id text NOT NULL,
 catalogue_version integer NOT NULL CHECK(catalogue_version>0),
 raw_bytes bytea NOT NULL,
 byte_length integer NOT NULL,
 git_blob_sha1 text NOT NULL CHECK(git_blob_sha1 ~ '^[0-9a-f]{40}$'),
 document jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(catalogue_id,catalogue_version),
 CHECK(octet_length(raw_bytes)=byte_length),
 CHECK(encode(sha256(raw_bytes),'hex')=snapshot_id)
);
CREATE TABLE IF NOT EXISTS editorial.item (
 snapshot_id text NOT NULL REFERENCES editorial.snapshot,
 entity_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('conceptScheme','occupation')),
 code text NOT NULL,
 scheme_id text,
 name text NOT NULL,
 payload jsonb NOT NULL,
 payload_hash text NOT NULL,
 revision_id text NOT NULL,
 source_pointer text NOT NULL,
 PRIMARY KEY(snapshot_id,entity_id)
);
CREATE TABLE IF NOT EXISTS editorial.review (
 review_id uuid PRIMARY KEY,
 review_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 snapshot_id text NOT NULL REFERENCES editorial.snapshot,
 decision text NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
 reviewer text NOT NULL,
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN ('human','assistant')),
 notes text NOT NULL,
 git_commit text,
 merge_evidence text,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS editorial_latest_review ON editorial.review(snapshot_id,review_no DESC);
CREATE TABLE IF NOT EXISTS editorial.release_pin (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 snapshot_id text NOT NULL REFERENCES editorial.snapshot,
 review_id uuid NOT NULL REFERENCES editorial.review,
 manifest jsonb NOT NULL,
 manifest_hash text NOT NULL,
 pinned_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS editorial.revision_support (
 release_id text NOT NULL REFERENCES editorial.release_pin,
 entity_id text NOT NULL,
 snapshot_id text NOT NULL,
 revision_id text NOT NULL,
 source_pointer text NOT NULL,
 PRIMARY KEY(release_id,entity_id),
 FOREIGN KEY(snapshot_id,entity_id) REFERENCES editorial.item,
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.release_revision,
 FOREIGN KEY(entity_id,revision_id) REFERENCES ontology.revision(entity_id,revision_id)
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['snapshot','item','review','release_pin','revision_support'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='editorial_immutable_'||name AND tgrelid=('editorial.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON editorial.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'editorial_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION editorial.git_blob_v1(raw bytea) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(digest(convert_to('blob '||octet_length(raw)::text,'UTF8')||decode('00','hex')||raw,'sha1'),'hex')
$$;

CREATE OR REPLACE FUNCTION editorial.item_candidates_v1(doc jsonb, snapshot text)
RETURNS TABLE(entity_id text,kind text,code text,scheme_id text,name text,payload jsonb,source_pointer text)
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT ontology.iri('conceptScheme','product-occupations'),'conceptScheme','product-occupations',NULL::text,
  doc#>>'{scheme,name}',(doc->'scheme')||jsonb_build_object('scheme_code','product-occupations','kind','TAXONOMY',
    'source_id','INTERNAL_EDITORIAL','source_snapshot_id',snapshot,'catalogue_version',doc->'catalogue_version'),'/scheme'
 UNION ALL
 SELECT ontology.iri('occupation','product:'||(v->>'code')),'occupation','product:'||(v->>'code'),
  ontology.iri('conceptScheme','product-occupations'),v->>'name',v||jsonb_build_object(
   'occupation_code',v->>'code','scheme_id',ontology.iri('conceptScheme','product-occupations'),
   'source_id','INTERNAL_EDITORIAL','source_snapshot_id',snapshot,'catalogue_version',doc->'catalogue_version'),
   '/occupations/'||(n-1)::text
 FROM jsonb_array_elements(doc->'occupations') WITH ORDINALITY e(v,n)
$$;

CREATE OR REPLACE FUNCTION editorial.capture_v1(raw bytea, expected_sha256 text, expected_git_blob text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE id text; blob text; doc jsonb; errors jsonb; BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 IF raw IS NULL OR octet_length(raw) NOT BETWEEN 1 AND 1048576 THEN RAISE EXCEPTION 'EDITORIAL_FILE_SIZE'; END IF;
 id:=encode(sha256(raw),'hex'); blob:=editorial.git_blob_v1(raw);
 IF expected_sha256 IS DISTINCT FROM id OR expected_git_blob IS DISTINCT FROM blob
 THEN RAISE EXCEPTION 'EDITORIAL_FILE_HASH_MISMATCH'; END IF;
 -- Decode only after hashing exact bytes. Duplicate keys, invalid UTF-8 and
 -- non-JSON YAML are rejected rather than silently changing the supplied file.
 IF NOT (convert_from(raw,'UTF8') IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION 'EDITORIAL_JSON_OBJECT_REQUIRED'; END IF;
 doc:=convert_from(raw,'UTF8')::jsonb;
 errors:=enrichment.schema_issues_v6(doc,(SELECT schema FROM editorial.contract WHERE version='hop-product-occupations-v1'));
 IF errors<>'[]' THEN RAISE EXCEPTION 'INVALID_EDITORIAL_DOCUMENT: %',errors; END IF;
 IF (SELECT count(DISTINCT v->>'code') FROM jsonb_array_elements(doc->'occupations') v)<>4
 THEN RAISE EXCEPTION 'EDITORIAL_FOUR_DISTINCT_OCCUPATIONS_REQUIRED'; END IF;
 IF nullif(btrim(doc->>'actor'),'') IS NULL OR nullif(btrim(doc#>>'{scheme,name}'),'') IS NULL OR
  nullif(btrim(doc#>>'{scheme,description}'),'') IS NULL OR EXISTS(
   SELECT 1 FROM jsonb_array_elements(doc->'occupations') v WHERE nullif(btrim(v->>'name'),'') IS NULL OR
   nullif(btrim(v->>'description'),'') IS NULL OR EXISTS(
    SELECT 1 FROM jsonb_array_elements_text((v->'aliases')||(v->'boundary_notes')) s WHERE nullif(btrim(s),'') IS NULL))
 THEN RAISE EXCEPTION 'EDITORIAL_BLANK_TEXT'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('editorial:'||(doc->>'catalogue_id'),0));
 IF EXISTS(SELECT 1 FROM editorial.snapshot s WHERE s.snapshot_id=id) THEN RETURN id; END IF;
 IF EXISTS(SELECT 1 FROM editorial.snapshot s WHERE s.catalogue_id=doc->>'catalogue_id' AND s.catalogue_version=(doc->>'catalogue_version')::integer)
 THEN RAISE EXCEPTION 'EDITORIAL_VERSION_IS_IMMUTABLE'; END IF;
 INSERT INTO editorial.snapshot(snapshot_id,source_id,catalogue_id,catalogue_version,raw_bytes,byte_length,git_blob_sha1,document)
 VALUES(id,'INTERNAL_EDITORIAL',doc->>'catalogue_id',(doc->>'catalogue_version')::integer,raw,octet_length(raw),blob,doc);
 INSERT INTO editorial.item
 SELECT id,c.entity_id,c.kind,c.code,c.scheme_id,c.name,c.payload,ontology.hash(c.payload),
  ontology.hash(jsonb_build_array(c.entity_id,'hop-editorial-revision-v1',id,c.payload)),c.source_pointer
 FROM editorial.item_candidates_v1(doc,id) c;
 RETURN id;
END $$;

CREATE OR REPLACE VIEW editorial.catalogue_status AS
SELECT s.snapshot_id,s.catalogue_id,s.catalogue_version,s.byte_length,s.git_blob_sha1,s.imported_at,
 s.document->>'actor' AS actor,s.document->>'actor_kind' AS actor_kind,
 d.review_id,d.decision,d.reviewer,d.reviewer_kind,d.reviewed_at,d.git_commit,d.merge_evidence,
 s.catalogue_version=(SELECT max(x.catalogue_version) FROM editorial.snapshot x WHERE x.catalogue_id=s.catalogue_id) AS latest_version,
 CASE WHEN d.review_id IS NULL THEN 'PENDING'
  WHEN d.decision='REJECT' THEN 'REJECTED'
  WHEN d.reviewer_kind='assistant' THEN 'ASSISTANT_REVIEWED'
  ELSE 'HUMAN_ACCEPTED' END AS review_state,
 (SELECT count(*) FROM editorial.item i WHERE i.snapshot_id=s.snapshot_id) AS entity_count
FROM editorial.snapshot s LEFT JOIN LATERAL (
 SELECT * FROM editorial.review r WHERE r.snapshot_id=s.snapshot_id ORDER BY review_no DESC LIMIT 1
) d ON true;

CREATE OR REPLACE FUNCTION editorial.review_v1(id uuid,snapshot text,choice text,actor text,actor_kind text,
 rationale text,commit_id text,merge_reference text) RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE s editorial.snapshot%ROWTYPE; existing editorial.review%ROWTYPE; BEGIN
 PERFORM retention.gate();
 IF ingestion.maintenance_active() THEN RAISE EXCEPTION 'RETENTION_ACTIVE'; END IF;
 SELECT * INTO s FROM editorial.snapshot stored WHERE stored.snapshot_id=review_v1.snapshot;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_EDITORIAL_SNAPSHOT'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('editorial:'||s.catalogue_id,0));
 commit_id:=nullif(btrim(commit_id),''); merge_reference:=nullif(btrim(merge_reference),'');
 IF id IS NULL OR choice IS NULL OR choice NOT IN ('ACCEPT','REJECT') OR actor_kind IS NULL OR
  actor_kind NOT IN ('human','assistant') OR nullif(btrim(actor),'') IS NULL OR nullif(btrim(rationale),'') IS NULL
 THEN RAISE EXCEPTION 'EDITORIAL_REVIEW_FIELDS_REQUIRED'; END IF;
 IF btrim(actor)=btrim(s.document->>'actor') THEN RAISE EXCEPTION 'INDEPENDENT_EDITORIAL_REVIEW_REQUIRED'; END IF;
 IF choice='ACCEPT' AND actor_kind='human' AND
  (commit_id IS NULL OR commit_id !~ '^([0-9a-f]{40}|[0-9a-f]{64})$' OR merge_reference IS NULL)
 THEN RAISE EXCEPTION 'EDITORIAL_MERGE_ATTESTATION_REQUIRED'; END IF;
 SELECT * INTO existing FROM editorial.review WHERE review_id=id;
 IF FOUND THEN
  IF ROW(existing.snapshot_id,existing.decision,existing.reviewer,existing.reviewer_kind,existing.notes,existing.git_commit,existing.merge_evidence)
   IS DISTINCT FROM ROW(snapshot,choice,actor,actor_kind,rationale,commit_id,merge_reference)
  THEN RAISE EXCEPTION 'EDITORIAL_REVIEW_ID_CONFLICT'; END IF;
  RETURN id;
 END IF;
 INSERT INTO editorial.review(review_id,snapshot_id,decision,reviewer,reviewer_kind,notes,git_commit,merge_evidence)
 VALUES(id,snapshot,choice,actor,actor_kind,rationale,commit_id,merge_reference);
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION editorial.pin_manifest_v1(snapshot text,review uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('format','hop-editorial-membership-v1','source_id','INTERNAL_EDITORIAL',
  'snapshot_id',s.snapshot_id,'git_blob_sha1',s.git_blob_sha1,'byte_length',s.byte_length,
  'catalogue_id',s.catalogue_id,'catalogue_version',s.catalogue_version,
  'review',(SELECT to_jsonb(r) FROM editorial.review r WHERE review_id=review),
  'items',(SELECT jsonb_agg(to_jsonb(i) ORDER BY entity_id) FROM editorial.item i WHERE i.snapshot_id=s.snapshot_id))
 FROM editorial.snapshot s WHERE s.snapshot_id=snapshot
$$;

CREATE OR REPLACE FUNCTION editorial.verify_pin_v1(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p editorial.release_pin%ROWTYPE; s editorial.snapshot%ROWTYPE; BEGIN
 SELECT * INTO p FROM editorial.release_pin WHERE release_id=id;
 IF NOT FOUND THEN RAISE EXCEPTION 'EDITORIAL_PIN_REQUIRED'; END IF;
 SELECT * INTO s FROM editorial.snapshot WHERE snapshot_id=p.snapshot_id;
 IF encode(sha256(s.raw_bytes),'hex') IS DISTINCT FROM s.snapshot_id OR editorial.git_blob_v1(s.raw_bytes) IS DISTINCT FROM s.git_blob_sha1
  OR convert_from(s.raw_bytes,'UTF8')::jsonb IS DISTINCT FROM s.document
 THEN RAISE EXCEPTION 'EDITORIAL_SOURCE_CHANGED'; END IF;
 IF p.manifest IS DISTINCT FROM editorial.pin_manifest_v1(p.snapshot_id,p.review_id) OR p.manifest_hash IS DISTINCT FROM ontology.hash(p.manifest)
 THEN RAISE EXCEPTION 'EDITORIAL_MEMBERSHIP_CHANGED'; END IF;
 IF EXISTS(
  SELECT 1 FROM editorial.item_candidates_v1(s.document,s.snapshot_id) c
  FULL JOIN (SELECT * FROM editorial.item WHERE snapshot_id=s.snapshot_id) i USING(entity_id)
  WHERE ROW(c.kind,c.code,c.scheme_id,c.name,c.payload,c.source_pointer)
   IS DISTINCT FROM ROW(i.kind,i.code,i.scheme_id,i.name,i.payload,i.source_pointer)
   OR i.payload_hash IS DISTINCT FROM ontology.hash(c.payload)
   OR i.revision_id IS DISTINCT FROM ontology.hash(jsonb_build_array(c.entity_id,'hop-editorial-revision-v1',s.snapshot_id,c.payload)))
 THEN RAISE EXCEPTION 'EDITORIAL_ITEM_SOURCE_MISMATCH'; END IF;
 IF NOT EXISTS(SELECT 1 FROM editorial.review r WHERE r.review_id=p.review_id AND r.snapshot_id=p.snapshot_id
  AND r.decision='ACCEPT' AND r.reviewer_kind='human' AND r.git_commit IS NOT NULL AND r.merge_evidence IS NOT NULL)
 THEN RAISE EXCEPTION 'EDITORIAL_PIN_REVIEW_INVALID'; END IF;
 IF (SELECT count(*) FROM editorial.revision_support WHERE release_id=id)<>5 OR EXISTS(
  SELECT 1 FROM editorial.item i LEFT JOIN ontology.release_revision m ON m.release_id=id AND m.entity_id=i.entity_id
  LEFT JOIN ontology.revision v ON v.revision_id=m.revision_id
  LEFT JOIN editorial.revision_support r ON r.release_id=id AND r.entity_id=i.entity_id
  WHERE i.snapshot_id=p.snapshot_id AND (m.revision_id IS DISTINCT FROM i.revision_id OR
   v.payload IS DISTINCT FROM i.payload OR v.payload_hash IS DISTINCT FROM i.payload_hash OR
   r.snapshot_id IS DISTINCT FROM i.snapshot_id OR r.source_pointer IS DISTINCT FROM i.source_pointer OR r.revision_id IS DISTINCT FROM i.revision_id))
 THEN RAISE EXCEPTION 'EDITORIAL_REVISION_MEMBERSHIP_CHANGED'; END IF;
END $$;

CREATE OR REPLACE FUNCTION editorial.pin_v1(id text,snapshot text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s editorial.catalogue_status%ROWTYPE; manifest jsonb; BEGIN
 PERFORM ontology.require_preparing(id);
 IF EXISTS(SELECT 1 FROM editorial.release_pin WHERE release_id=id) THEN
  IF NOT EXISTS(SELECT 1 FROM editorial.release_pin WHERE release_id=id AND snapshot_id=snapshot)
  THEN RAISE EXCEPTION 'EDITORIAL_RELEASE_PIN_IS_IMMUTABLE'; END IF;
  PERFORM editorial.verify_pin_v1(id); RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM ontology.corpus_release WHERE release_id=id AND manifest_hash IS NOT NULL) OR
  EXISTS(SELECT 1 FROM ontology.requirement_freeze WHERE release_id=id)
 THEN RAISE EXCEPTION 'EDITORIAL_RELEASE_ALREADY_FROZEN'; END IF;
 PERFORM ontology.check_frozen_sources(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id)
 THEN RAISE EXCEPTION 'EDITORIAL_ASSEMBLED_RELEASE_REQUIRED'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('editorial:product-occupations',0));
 SELECT * INTO s FROM editorial.catalogue_status WHERE snapshot_id=snapshot;
 IF NOT FOUND THEN RAISE EXCEPTION 'UNKNOWN_EDITORIAL_SNAPSHOT'; END IF;
 IF NOT s.latest_version THEN RAISE EXCEPTION 'EDITORIAL_CURRENT_REVISION_REQUIRED'; END IF;
 IF s.review_state<>'HUMAN_ACCEPTED' THEN RAISE EXCEPTION 'EDITORIAL_HUMAN_REVIEW_REQUIRED'; END IF;
 IF EXISTS(SELECT 1 FROM editorial.item i JOIN ontology.entity e USING(entity_id) WHERE i.snapshot_id=snapshot
  AND ROW(e.kind,e.code,e.scheme_id) IS DISTINCT FROM ROW(i.kind,i.code,i.scheme_id))
 THEN RAISE EXCEPTION 'EDITORIAL_IDENTITY_CONFLICT'; END IF;
 INSERT INTO ontology.entity(entity_id,kind,code,scheme_id)
 SELECT entity_id,kind,code,scheme_id FROM editorial.item WHERE snapshot_id=snapshot ON CONFLICT DO NOTHING;
 INSERT INTO ontology.revision(revision_id,entity_id,kind,name,payload,payload_hash,schema_version)
 SELECT revision_id,entity_id,kind,name,payload,payload_hash,'hop-editorial-revision-v1' FROM editorial.item WHERE snapshot_id=snapshot ON CONFLICT DO NOTHING;
 IF EXISTS(SELECT 1 FROM editorial.item i JOIN ontology.revision v USING(revision_id) WHERE i.snapshot_id=snapshot AND
  ROW(v.entity_id,v.kind,v.name,v.payload,v.payload_hash,v.schema_version) IS DISTINCT FROM
  ROW(i.entity_id,i.kind,i.name,i.payload,i.payload_hash,'hop-editorial-revision-v1'::text))
 THEN RAISE EXCEPTION 'EDITORIAL_REVISION_CONFLICT'; END IF;
 IF EXISTS(SELECT 1 FROM editorial.item i JOIN ontology.release_revision m USING(entity_id) WHERE i.snapshot_id=snapshot
  AND m.release_id=id AND m.revision_id<>i.revision_id) THEN RAISE EXCEPTION 'EDITORIAL_RELEASE_REVISION_CONFLICT'; END IF;
 manifest:=editorial.pin_manifest_v1(snapshot,s.review_id);
 INSERT INTO editorial.release_pin(release_id,snapshot_id,review_id,manifest,manifest_hash)
 VALUES(id,snapshot,s.review_id,manifest,ontology.hash(manifest));
 INSERT INTO ontology.release_revision SELECT id,entity_id,revision_id FROM editorial.item WHERE snapshot_id=snapshot ON CONFLICT DO NOTHING;
 INSERT INTO editorial.revision_support SELECT id,entity_id,snapshot,revision_id,source_pointer FROM editorial.item WHERE snapshot_id=snapshot;
 PERFORM editorial.verify_pin_v1(id);
END $$;

-- Do not allow a legacy graph/export to silently omit an imported source.
-- The matching graph adapter must include this exact immutable membership.
CREATE OR REPLACE FUNCTION editorial.guard_release_manifest_v1() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p editorial.release_pin%ROWTYPE; BEGIN
 SELECT * INTO p FROM editorial.release_pin WHERE release_id=NEW.release_id;
 IF FOUND AND NEW.manifest IS NOT NULL THEN
  PERFORM editorial.verify_pin_v1(NEW.release_id);
  IF NEW.manifest->'editorial_membership' IS DISTINCT FROM p.manifest OR
    NEW.manifest->>'editorial_membership_hash' IS DISTINCT FROM p.manifest_hash
  THEN RAISE EXCEPTION 'EDITORIAL_GRAPH_INTEGRATION_REQUIRED'; END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='editorial_release_manifest_guard' AND tgrelid='ontology.corpus_release'::regclass) THEN
  CREATE TRIGGER editorial_release_manifest_guard BEFORE UPDATE OF manifest,manifest_hash ON ontology.corpus_release
   FOR EACH ROW EXECUTE FUNCTION editorial.guard_release_manifest_v1();
 END IF;
END $$;
COMMIT;
