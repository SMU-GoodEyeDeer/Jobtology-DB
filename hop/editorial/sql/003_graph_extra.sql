-- Editorial source and review evidence layered over the native ontology graph.
BEGIN;
CREATE OR REPLACE FUNCTION editorial.graph_record_id_v1(i editorial.item) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT 'editorial-record/'||ontology.hash(jsonb_build_array(i.snapshot_id,i.entity_id,i.source_pointer,i.payload_hash))
$$;

CREATE OR REPLACE FUNCTION editorial.graph_nodes_v1(id text)
RETURNS TABLE(node_id text,labels text[],properties jsonb) LANGUAGE sql STABLE AS $$
WITH pin AS MATERIALIZED (SELECT * FROM editorial.release_pin WHERE release_id=id),
 snapshot AS MATERIALIZED (SELECT s.* FROM editorial.snapshot s JOIN pin USING(snapshot_id)),
 nodes AS (
 SELECT 'source/INTERNAL_EDITORIAL'::text,ARRAY['ontologySource'],
  jsonb_build_object('source_id','INTERNAL_EDITORIAL','name','Jobtology 내부 편집 자료')
 FROM pin
 UNION ALL
 SELECT 'snapshot/INTERNAL_EDITORIAL/'||s.snapshot_id,ARRAY['sourceSnapshot','editorialSourceSnapshot'],
  jsonb_build_object('source_id',s.source_id,'sha256',s.snapshot_id,'snapshot_id',s.snapshot_id,
   'byte_length',s.byte_length,'encoding','UTF-8','git_blob_sha1',s.git_blob_sha1,
   'catalogue_id',s.catalogue_id,'catalogue_version',s.catalogue_version,
   'schema_version',s.document->>'schema_version','source_text',convert_from(s.raw_bytes,'UTF8'),
   'actor',s.document->>'actor','actor_kind',s.document->>'actor_kind',
   'name','Jobtology 지원 직무 v'||s.catalogue_version::text)
 FROM snapshot s
 UNION ALL
 SELECT editorial.graph_record_id_v1(i),ARRAY['sourceRecordEvidence','editorialSourceRecord'],
  jsonb_build_object('source_id','INTERNAL_EDITORIAL','source_record_id',i.entity_id,'entity_id',i.entity_id,
   'snapshot_id',i.snapshot_id,'locator',i.source_pointer,'raw_sha256',i.snapshot_id,
   'normalized_hash',i.payload_hash,'revision_id',i.revision_id,'name',i.name||' — 편집 원문')
 FROM editorial.item i JOIN snapshot s USING(snapshot_id)
 UNION ALL
 SELECT 'editorial-review/'||r.review_id::text,ARRAY['editorialReview'],
  to_jsonb(r)||jsonb_build_object('name','직무 정의 검토 — '||r.reviewer,
   'attestation_kind','OPERATOR_REPORTED','repository_verification','NOT_AUTOMATICALLY_VERIFIED')
 FROM editorial.review r JOIN pin USING(review_id)
 UNION ALL
 SELECT 'editorial-selection/'||p.release_id,ARRAY['editorialReleaseSelection'],
  jsonb_build_object('release_id',p.release_id,'snapshot_id',p.snapshot_id,'review_id',p.review_id,
   'manifest_hash',p.manifest_hash,'created_at',p.pinned_at,'name','고정된 직무 정의 — '||p.release_id)
 FROM pin p
 UNION ALL
 SELECT 'editorial-contract/'||c.version,ARRAY['editorialContract'],
  jsonb_build_object('schema_version',c.version,'schema_hash',c.content_hash,'name','내부 직무 정의 형식 v1')
 FROM editorial.contract c JOIN snapshot s ON c.version=s.document->>'schema_version'
)
SELECT * FROM nodes
$$;

CREATE OR REPLACE FUNCTION editorial.graph_edges_v1(id text)
RETURNS TABLE(subject_id text,predicate text,object_id text,properties jsonb) LANGUAGE sql STABLE AS $$
WITH pin AS MATERIALIZED (SELECT * FROM editorial.release_pin WHERE release_id=id),
 items AS MATERIALIZED (SELECT i.* FROM editorial.item i JOIN pin USING(snapshot_id))
SELECT 'snapshot/INTERNAL_EDITORIAL/'||p.snapshot_id,'FROM_SOURCE','source/INTERNAL_EDITORIAL','{}'::jsonb FROM pin p
UNION ALL
SELECT 'editorial-selection/'||p.release_id,'SELECTS_SNAPSHOT','snapshot/INTERNAL_EDITORIAL/'||p.snapshot_id,'{}'::jsonb FROM pin p
UNION ALL
SELECT 'editorial-selection/'||p.release_id,'REVIEWED_BY','editorial-review/'||p.review_id::text,'{}'::jsonb FROM pin p
UNION ALL
SELECT 'editorial-review/'||p.review_id::text,'FOR_SNAPSHOT','snapshot/INTERNAL_EDITORIAL/'||p.snapshot_id,'{}'::jsonb FROM pin p
UNION ALL
SELECT 'snapshot/INTERNAL_EDITORIAL/'||p.snapshot_id,'USES_CONTRACT','editorial-contract/'||(s.document->>'schema_version'),'{}'::jsonb
FROM pin p JOIN editorial.snapshot s USING(snapshot_id)
UNION ALL
SELECT 'revision/'||i.revision_id,'DERIVED_FROM',editorial.graph_record_id_v1(i),'{}'::jsonb FROM items i
UNION ALL
SELECT editorial.graph_record_id_v1(i),'IN_SNAPSHOT','snapshot/INTERNAL_EDITORIAL/'||i.snapshot_id,'{}'::jsonb FROM items i
UNION ALL
SELECT 'editorial-selection/'||p.release_id,'SELECTS_REVISION','revision/'||i.revision_id,'{}'::jsonb FROM items i JOIN pin p USING(snapshot_id)
UNION ALL
SELECT 'revision/'||i.revision_id,'IN_SCHEME','entity/'||i.scheme_id,'{}'::jsonb FROM items i WHERE i.scheme_id IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION editorial.graph_manifest_v1(id text) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('editorial_membership',p.manifest,'editorial_membership_hash',p.manifest_hash,
  'editorial_contract_hash',c.content_hash)
 FROM editorial.release_pin p JOIN editorial.snapshot s USING(snapshot_id)
 JOIN editorial.contract c ON c.version=s.document->>'schema_version' WHERE p.release_id=id
$$;

CREATE OR REPLACE FUNCTION editorial.verify_graph_v1(id text) RETURNS void LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM editorial.release_pin WHERE release_id=id) THEN
  IF EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND n.labels &&
   ARRAY['editorialSourceSnapshot','editorialSourceRecord','editorialReview','editorialReleaseSelection','editorialContract'])
  THEN RAISE EXCEPTION 'EDITORIAL_GRAPH_WITHOUT_PIN'; END IF;
  RETURN;
 END IF;
 PERFORM editorial.verify_pin_v1(id);
 IF (SELECT manifest FROM ontology.corpus_release WHERE release_id=id) IS NULL THEN RETURN; END IF;
 IF NOT ((SELECT manifest FROM ontology.corpus_release WHERE release_id=id) @> editorial.graph_manifest_v1(id))
 THEN RAISE EXCEPTION 'EDITORIAL_GRAPH_MANIFEST_MISMATCH'; END IF;
 IF EXISTS(
  SELECT 1 FROM editorial.graph_nodes_v1(id) c LEFT JOIN ontology.graph_node n ON n.release_id=id AND n.node_id=c.node_id
  WHERE n.labels IS DISTINCT FROM c.labels OR n.properties IS DISTINCT FROM c.properties)
 OR (SELECT count(*) FROM ontology.graph_node n WHERE n.release_id=id AND n.labels &&
   ARRAY['editorialSourceSnapshot','editorialSourceRecord','editorialReview','editorialReleaseSelection','editorialContract'])<>9
 THEN RAISE EXCEPTION 'EDITORIAL_GRAPH_NODE_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM editorial.graph_edges_v1(id) c WHERE NOT EXISTS(
  SELECT 1 FROM ontology.graph_edge e WHERE e.release_id=id AND
   ROW(e.subject_id,e.predicate,e.object_id,e.properties)=ROW(c.subject_id,c.predicate,c.object_id,c.properties)))
 THEN RAISE EXCEPTION 'EDITORIAL_GRAPH_EDGE_MISMATCH'; END IF;
END $$;
COMMIT;
