BEGIN;

-- A crosswalk is retrieval context, never a requirement satisfaction rule.
-- Both proposals and review history are version pinned and append-only.
CREATE TABLE IF NOT EXISTS catalog.ncs_onet_mapping (
 mapping_id text PRIMARY KEY CHECK(mapping_id ~ '^crosswalk:[0-9a-f]{64}$'),
 version text NOT NULL CHECK(length(btrim(version)) BETWEEN 1 AND 100),
 source jsonb NOT NULL CHECK(jsonb_typeof(source)='object'),
 target jsonb NOT NULL CHECK(jsonb_typeof(target)='object'),
 relation text NOT NULL CHECK(relation IN('RELATED','PARTIAL','EXACT')),
 evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ncs_onet_mapping_source ON catalog.ncs_onet_mapping((source->>'id'));
CREATE INDEX IF NOT EXISTS ncs_onet_mapping_target ON catalog.ncs_onet_mapping((target->>'id'));
CREATE TABLE IF NOT EXISTS catalog.ncs_onet_review (
 review_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 mapping_id text NOT NULL REFERENCES catalog.ncs_onet_mapping,
 status text NOT NULL CHECK(status IN('APPROVED','REJECTED')),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN('ASSISTANT','HUMAN')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer)) BETWEEN 1 AND 200),
 note text NOT NULL CHECK(length(btrim(note)) BETWEEN 20 AND 3000),
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ncs_onet_review_latest ON catalog.ncs_onet_review(mapping_id,review_id DESC);
CREATE OR REPLACE FUNCTION catalog._immutable_crosswalk_record() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_CROSSWALK_RECORD'; END $$;
DROP TRIGGER IF EXISTS ncs_onet_mapping_immutable ON catalog.ncs_onet_mapping;
CREATE TRIGGER ncs_onet_mapping_immutable BEFORE UPDATE OR DELETE ON catalog.ncs_onet_mapping
 FOR EACH ROW EXECUTE FUNCTION catalog._immutable_crosswalk_record();
DROP TRIGGER IF EXISTS ncs_onet_review_immutable ON catalog.ncs_onet_review;
CREATE TRIGGER ncs_onet_review_immutable BEFORE UPDATE OR DELETE ON catalog.ncs_onet_review
 FOR EACH ROW EXECUTE FUNCTION catalog._immutable_crosswalk_record();

DROP TRIGGER IF EXISTS ncs_onet_mapping_no_truncate ON catalog.ncs_onet_mapping;
CREATE TRIGGER ncs_onet_mapping_no_truncate BEFORE TRUNCATE ON catalog.ncs_onet_mapping
 FOR EACH STATEMENT EXECUTE FUNCTION catalog._immutable_crosswalk_record();
DROP TRIGGER IF EXISTS ncs_onet_review_no_truncate ON catalog.ncs_onet_review;
CREATE TRIGGER ncs_onet_review_no_truncate BEFORE TRUNCATE ON catalog.ncs_onet_review
 FOR EACH STATEMENT EXECUTE FUNCTION catalog._immutable_crosswalk_record();

-- Resolve only real, READY local catalogue records. Optional O*NET installations
-- are discovered at execution time so the core ontology installer remains usable.
CREATE OR REPLACE FUNCTION catalog._crosswalk_node(node_id text,pin text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE answer jsonb; selected_pin text; code text; element_alias text;
BEGIN
 IF node_id LIKE 'urn:jobtology:ncs:%' THEN node_id:=substr(node_id,length('urn:jobtology:')+1); END IF;
 IF node_id LIKE 'onet:skill:%' THEN
  element_alias:=substr(node_id,length('onet:skill:')+1);
  node_id:='urn:jobtology:onet-detail:element:'||element_alias;
 END IF;
 IF node_id LIKE 'ncs:occupation:%' OR node_id LIKE 'ncs:unit:%' THEN
  SELECT coalesce(pin,(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency'))
   INTO selected_pin;
  IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=selected_pin
   AND source_id='ncs_competency' AND state='READY' AND mode<>'SMOKE') THEN RETURN NULL; END IF;
  IF node_id LIKE 'ncs:occupation:%' THEN
   code:=substr(node_id,length('ncs:occupation:')+1);
   SELECT jsonb_build_object('id',node_id,'scheme','NCS','kind','ncs_occupation',
    'code',code,'name',min(normalized->>'occupation_name'),'catalog_pin',selected_pin,
    'description',string_agg(normalized->>'name',' · ' ORDER BY normalized->>'code'),
    'content_hash',encode(sha256(convert_to(jsonb_agg(normalized ORDER BY normalized->>'code')::text,'UTF8')),'hex'))
   INTO answer FROM ingestion.ready_record WHERE run_id=selected_pin AND source_id='ncs_competency'
    AND normalized->>'occupation_code'=code HAVING count(*)>0;
  ELSE
   code:=substr(node_id,length('ncs:unit:')+1);
   SELECT jsonb_build_object('id','ncs:unit:'||(normalized->>'code'),'scheme','NCS','kind','ncs_competency',
    'code',normalized->>'code','name',normalized->>'name','catalog_pin',selected_pin,
    'description',normalized->>'definition','content_hash',encode(sha256(convert_to(normalized::text,'UTF8')),'hex'))
   INTO answer FROM ingestion.ready_record WHERE run_id=selected_pin AND source_id='ncs_competency'
    AND (normalized->>'code'=code OR (code ~ '^[0-9]{10}$' AND left(normalized->>'code',10)=code))
    AND normalized->>'name' NOT LIKE '%(구버전)%' ORDER BY normalized->>'code' COLLATE "C" DESC LIMIT 1;
  END IF;
 ELSIF node_id LIKE 'urn:jobtology:onet:occupation:%'
  AND to_regclass('classification.term') IS NOT NULL THEN
  EXECUTE $occupation$
   SELECT jsonb_build_object('id',t.term_id,'scheme','ONET','kind','onet_occupation',
    'code',t.code,'name',t.preferred_label,'description',t.description,'catalog_pin',t.release_id,
    'content_hash',encode(sha256(convert_to((to_jsonb(t)-'release_id')::text,'UTF8')),'hex'))
   FROM classification.term t JOIN classification.catalog_release r USING(release_id)
   WHERE t.term_id=$1 AND t.term_kind='OCCUPATION' AND r.state='READY'
    AND t.release_id=coalesce($2,(SELECT release_id FROM classification.catalog_current WHERE scheme_id='ONET'))
  $occupation$ INTO answer USING node_id,pin;
 ELSIF node_id LIKE 'urn:jobtology:onet-detail:%' AND to_regclass('onet_detail.node') IS NOT NULL THEN
  EXECUTE $detail$
   SELECT jsonb_build_object('id',n.id,'scheme','ONET',
    'kind',CASE WHEN n.type='TASK' THEN 'onet_task' WHEN n.type='SOFTWARE' THEN 'technology'
      WHEN n.properties->>'element_id' LIKE '2.C.%' THEN 'onet_knowledge'
      WHEN n.properties->>'element_id' LIKE '4.A.%' THEN 'onet_work_activity' ELSE 'onet_skill' END,
    'code',coalesce(n.properties->>'element_id',n.properties->>'task_id',n.id),
    'name',coalesce(n.properties->>'element_name',n.properties->>'name',n.properties->>'task',n.properties->>'workplace_example'),
    'description',coalesce(n.properties->>'description',n.properties->>'task',n.properties->>'name'),
    'catalog_pin',n.release_id,'content_hash',encode(sha256(convert_to(n.properties::text,'UTF8')),'hex'))
   FROM onet_detail.node n JOIN onet_detail.catalog_release r USING(release_id)
   WHERE n.id=$1 AND n.type IN('ELEMENT','TASK','SOFTWARE') AND r.state='READY'
    AND ($3 IS NULL OR (n.type='ELEMENT' AND n.properties->>'element_id'=$3))
    AND n.release_id=coalesce($2,(SELECT release_id FROM onet_detail.catalog_current WHERE scheme_id='ONET'))
  $detail$ INTO answer USING node_id,pin,element_alias;
 END IF;
 RETURN answer;
END $$;

CREATE OR REPLACE FUNCTION catalog.propose_ncs_onet_mapping(
 source_id text,target_id text,relation text,evidence jsonb,version text DEFAULT 'crosswalk-v1')
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE source_node jsonb; target_node jsonb; identity text;
BEGIN
 source_node:=catalog._crosswalk_node(source_id); target_node:=catalog._crosswalk_node(target_id);
 IF source_node IS NULL OR target_node IS NULL OR source_node->>'scheme'<>'NCS'
  OR target_node->>'scheme'<>'ONET' THEN RAISE EXCEPTION 'CROSSWALK_ENDPOINT_UNAVAILABLE'; END IF;
 IF relation IS NULL OR relation NOT IN('RELATED','PARTIAL','EXACT') OR version IS NULL
  OR length(btrim(version)) NOT BETWEEN 1 AND 100 OR evidence IS NULL OR jsonb_typeof(evidence)<>'object'
  OR jsonb_typeof(evidence->'summary') IS DISTINCT FROM 'string'
  OR length(btrim(evidence->>'summary')) NOT BETWEEN 20 AND 3000
  OR jsonb_typeof(evidence->'source_quote') IS DISTINCT FROM 'string'
  OR jsonb_typeof(evidence->'target_quote') IS DISTINCT FROM 'string'
  OR length(btrim(evidence->>'source_quote')) NOT BETWEEN 1 AND 2000
  OR length(btrim(evidence->>'target_quote')) NOT BETWEEN 1 AND 2000
 THEN RAISE EXCEPTION 'INVALID_CROSSWALK_PROPOSAL'; END IF;
 IF strpos(coalesce(source_node->>'description','')||' '||coalesce(source_node->>'name',''),evidence->>'source_quote')=0
  OR strpos(coalesce(target_node->>'description','')||' '||coalesce(target_node->>'name',''),evidence->>'target_quote')=0
 THEN RAISE EXCEPTION 'CROSSWALK_QUOTE_NOT_IN_CATALOG'; END IF;
 identity:='crosswalk:'||encode(sha256(convert_to(jsonb_build_array(
  version,source_node,target_node,relation,evidence)::text,'UTF8')),'hex');
 INSERT INTO catalog.ncs_onet_mapping(mapping_id,version,source,target,relation,evidence)
 VALUES(identity,version,source_node,target_node,relation,evidence) ON CONFLICT(mapping_id) DO NOTHING;
 RETURN identity;
END $$;

CREATE OR REPLACE FUNCTION catalog.review_ncs_onet_mapping(
 identity text,decision text,reviewer_kind text,reviewer text,note text,expected_review_id bigint DEFAULT 0)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE mapping catalog.ncs_onet_mapping; previous bigint; result bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(identity,0));
 SELECT * INTO mapping FROM catalog.ncs_onet_mapping WHERE mapping_id=identity;
 IF NOT FOUND THEN RAISE EXCEPTION 'CROSSWALK_MAPPING_NOT_FOUND'; END IF;
 SELECT coalesce(max(review_id),0) INTO previous FROM catalog.ncs_onet_review WHERE mapping_id=identity;
 IF expected_review_id IS NULL OR previous<>expected_review_id THEN RAISE EXCEPTION 'CROSSWALK_REVIEW_CONFLICT'; END IF;
 IF decision IS NULL OR decision NOT IN('APPROVED','REJECTED') OR reviewer_kind IS NULL
  OR reviewer_kind NOT IN('ASSISTANT','HUMAN') OR reviewer IS NULL OR note IS NULL
  OR length(btrim(reviewer)) NOT BETWEEN 1 AND 200 OR length(btrim(note)) NOT BETWEEN 20 AND 3000
 THEN RAISE EXCEPTION 'INVALID_CROSSWALK_REVIEW'; END IF;
 IF decision='APPROVED' AND (
  catalog._crosswalk_node(mapping.source->>'id') IS DISTINCT FROM mapping.source
  OR catalog._crosswalk_node(mapping.target->>'id') IS DISTINCT FROM mapping.target)
 THEN RAISE EXCEPTION 'STALE_CROSSWALK_ENDPOINT'; END IF;
 INSERT INTO catalog.ncs_onet_review(mapping_id,status,reviewer_kind,reviewer,note)
 VALUES(identity,decision,reviewer_kind,reviewer,note) RETURNING review_id INTO result;
 RETURN result;
END $$;

-- A live co-occurrence is a RELATED suggestion only. It is never automatically
-- approved, and preserves stale/unknown source and catalogue evidence.
CREATE OR REPLACE FUNCTION catalog._ncs_onet_shared_posting_proposals(node_id text)
RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH scope AS (
  SELECT CASE WHEN node_id LIKE 'ncs:occupation:%' THEN substr(node_id,length('ncs:occupation:')+1)
   WHEN node_id LIKE 'urn:jobtology:onet:occupation:%' THEN substr(node_id,length('urn:jobtology:onet:occupation:')+1) END AS code
 ), anchor AS MATERIALIZED (
  SELECT a.* FROM scope CROSS JOIN LATERAL catalog._inferred_occupation_rows(ARRAY[scope.code],NULL) a
  WHERE scope.code IS NOT NULL
 ), counterparts AS MATERIALIZED (
  SELECT a.* FROM catalog._inferred_occupation_rows(NULL,
   coalesce((SELECT array_agg(DISTINCT posting_key) FROM anchor),ARRAY[]::text[])) a
 ), inferred AS MATERIALIZED (
  SELECT * FROM anchor UNION SELECT * FROM counterparts
 ), wanted AS MATERIALIZED (
  SELECT r.source_id,r.posting_key,bool_or(r.occupation_scheme='NCS') AS needs_ncs,
   bool_or(r.occupation_scheme='ONET') AS needs_onet FROM inferred r GROUP BY r.source_id,r.posting_key
 ), observations AS MATERIALIZED (
  -- Source selection and each needed content hash run once for the combined
  -- bounded workset, rather than once for each side of the crosswalk.
  SELECT p.posting_id,p.source_id,
   CASE WHEN w.needs_ncs THEN encode(sha256(convert_to(p.normalized::text,'UTF8')),'hex') END AS normalized_hash,
   CASE WHEN w.needs_onet THEN catalog._live_source_fact_hash(p.source_id,p.normalized) END AS source_facts_sha256
  FROM catalog._live_source_observations() p JOIN wanted w
   ON w.source_id=p.source_id AND w.posting_key=p.posting_id
 ), associations AS MATERIALIZED (
  SELECT r.*,CASE WHEN p.posting_id IS NULL THEN 'STALE'
   WHEN r.occupation_scheme='NCS' AND r.normalized_hash IS NOT NULL THEN
    CASE WHEN r.normalized_hash=p.normalized_hash THEN 'CURRENT' ELSE 'STALE' END
   WHEN r.occupation_scheme='ONET' AND p.source_facts_sha256 IS NOT NULL THEN
    CASE WHEN r.source_facts_sha256=p.source_facts_sha256 THEN 'CURRENT' ELSE 'STALE' END
   ELSE 'UNKNOWN' END AS source_freshness,
   jsonb_build_object('association_id',r.association_id,'occupation_name',r.occupation_name,
    'review_status',r.review_status,'source_pins',jsonb_build_object('run_id',r.source_run_id,
     'source_hash',r.source_hash,'normalized_hash',r.normalized_hash,'source_facts_sha256',r.source_facts_sha256),
    'catalog_pins',jsonb_build_object('pin',r.catalog_pin,'catalog_hash',r.catalog_hash)) AS association
  FROM inferred r LEFT JOIN observations p ON p.source_id=r.source_id AND p.posting_id=r.posting_key
 ), pairs AS (
  SELECT n.occupation_code AS ncs_code,o.occupation_code AS onet_code,
   min(n.association->>'occupation_name') AS ncs_name,min(o.association->>'occupation_name') AS onet_name,
   n.association#>>'{catalog_pins,pin}' AS ncs_pin,o.association#>>'{catalog_pins,pin}' AS onet_pin,
   count(DISTINCT n.posting_key) AS shared_postings,
   bool_and(n.source_freshness='CURRENT' AND o.source_freshness='CURRENT') AS source_current,
   bool_or(n.source_freshness='STALE' OR o.source_freshness='STALE') AS source_stale,
   bool_and(n.catalog_freshness='CURRENT' AND o.catalog_freshness='CURRENT') AS catalog_current,
   array_agg(DISTINCT n.posting_key ORDER BY n.posting_key) AS posting_keys,
   jsonb_agg(DISTINCT jsonb_build_object('ncs_association_id',n.association->>'association_id',
    'onet_association_id',o.association->>'association_id','source_id',n.source_id,
    'ncs_source_pins',n.association->'source_pins','onet_source_pins',o.association->'source_pins',
    'ncs_catalog_pins',n.association->'catalog_pins','onet_catalog_pins',o.association->'catalog_pins',
    'ncs_review_status',n.association->>'review_status','onet_review_status',o.association->>'review_status')) AS associations
  FROM associations n JOIN associations o USING(posting_key,source_id)
  WHERE n.occupation_scheme='NCS' AND o.occupation_scheme='ONET'
   AND (node_id='ncs:occupation:'||n.occupation_code OR node_id='urn:jobtology:onet:occupation:'||o.occupation_code)
  GROUP BY n.occupation_code,o.occupation_code,n.association#>>'{catalog_pins,pin}',o.association#>>'{catalog_pins,pin}'
 ), nodes AS (
  SELECT p.*,catalog._crosswalk_node('ncs:occupation:'||ncs_code,ncs_pin) AS source,
   catalog._crosswalk_node('urn:jobtology:onet:occupation:'||onet_code,onet_pin) AS target
  FROM pairs p
 )
 SELECT jsonb_build_object('mapping_id','shared-postings:'||encode(sha256(convert_to(
  jsonb_build_array(ncs_code,onet_code,ncs_pin,onet_pin)::text,'UTF8')),'hex'),
  'version','shared-postings-v1','source',source,'target',target,'relation','RELATED','status','PROPOSED',
  'basis','SHARED_POSTINGS','evidence',jsonb_build_object('shared_postings',shared_postings,
   'posting_keys',to_jsonb(posting_keys[1:5]),'associations',(SELECT jsonb_agg(value) FROM
    (SELECT value FROM jsonb_array_elements(associations) ORDER BY value::text LIMIT 5) sample),
   'summary','같은 공고의 직무 추론이 함께 연결된 탐색 제안이며 역량 동등성을 뜻하지 않아요.'),
  'review',NULL,'source_freshness',CASE WHEN source_current THEN 'CURRENT' WHEN source_stale THEN 'STALE' ELSE 'UNKNOWN' END,
  'catalog_freshness',CASE WHEN catalog_current THEN 'CURRENT' ELSE 'STALE' END,
  'created_at',NULL,'competency_evidence',false)
 FROM nodes WHERE source IS NOT NULL AND target IS NOT NULL
$$;

-- Bilingual technical cues propose candidates with exact supporting substrings.
-- They do not establish semantic equivalence, proficiency or a reviewed mapping.
CREATE OR REPLACE FUNCTION catalog._ncs_onet_lexical_proposals(node_id text)
RETURNS SETOF jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE anchor jsonb;
BEGIN
 anchor:=catalog._crosswalk_node(node_id);
 IF anchor IS NULL OR anchor->>'kind' NOT IN('ncs_competency','onet_skill','onet_task','onet_knowledge','onet_work_activity','technology')
  OR to_regclass('onet_detail.node') IS NULL THEN RETURN; END IF;
 RETURN QUERY EXECUTE $lexical$
  WITH cues(cue,source_pattern,target_pattern) AS (VALUES
   ('database','(데이터베이스|database|\mSQL\M|\mDBMS\M)','(database|\mSQL\M|\mDBMS\M)'),
   ('programming','(프로그래밍|코딩|programming)','(programming|write computer programs)'),
   ('software_testing','(소프트웨어 테스트|애플리케이션 테스트|software testing)','(software testing|test software|testing software|test applications)'),
   ('computer_networks','(컴퓨터 네트워크|네트워크|computer networks)','(computer networks|computer networking)'),
   ('information_security','(정보보안|정보보호|information security)','(information security|computer security|cybersecurity)'),
   ('machine_learning','(머신러닝|기계학습|machine learning)','(machine learning)'),
   ('data_analysis','(데이터 분석|데이터분석|통계 분석|통계분석|data analysis)','(data analysis|statistical analysis)')
  ), latest_units AS (
   SELECT DISTINCT ON(left(r.normalized->>'code',10)) r.normalized,r.run_id
   FROM ingestion.ready_record r JOIN ingestion.latest_ready_run current USING(run_id,source_id)
   WHERE $1->>'scheme'='ONET' AND r.source_id='ncs_competency' AND r.normalized->>'name' NOT LIKE '%(구버전)%'
   ORDER BY left(r.normalized->>'code',10),r.normalized->>'code' COLLATE "C" DESC
  ), sources AS (
   SELECT $1 AS source WHERE $1->>'scheme'='NCS' UNION ALL
   SELECT jsonb_build_object('id','ncs:unit:'||(normalized->>'code'),'scheme','NCS','kind','ncs_competency',
    'code',normalized->>'code','name',normalized->>'name','catalog_pin',run_id,
    'description',normalized->>'definition','content_hash',encode(sha256(convert_to(normalized::text,'UTF8')),'hex'))
   FROM latest_units
  ), matches AS (
   SELECT n.*,s.source,c.cue,
    (regexp_match((s.source->>'name')||' '||coalesce(s.source->>'description',''),c.source_pattern,'i'))[1] AS source_quote,
    (regexp_match(coalesce(n.properties->>'element_name',n.properties->>'task',n.properties->>'workplace_example','')||' '||
     coalesce(n.properties->>'description',''),c.target_pattern,'i'))[1] AS target_quote
   FROM onet_detail.node n JOIN onet_detail.catalog_current current USING(release_id)
   JOIN onet_detail.catalog_release r USING(release_id)
   CROSS JOIN sources s CROSS JOIN cues c
   WHERE n.type IN('ELEMENT','TASK','SOFTWARE') AND r.state='READY'
    AND ($1->>'scheme'='NCS' OR n.id=$1->>'id')
    AND (s.source->>'name')||' '||coalesce(s.source->>'description','') ~* c.source_pattern
    AND coalesce(n.properties->>'element_name',n.properties->>'task',n.properties->>'workplace_example','')||' '||
     coalesce(n.properties->>'description','') ~* c.target_pattern
  ), targets AS (
   SELECT m.*,catalog._crosswalk_node(id,release_id) AS target FROM matches m
  )
  SELECT DISTINCT ON(source->>'id',id) jsonb_build_object('mapping_id','lexical:'||encode(sha256(convert_to(jsonb_build_array(
   source->>'id',source->>'catalog_pin',source->>'content_hash',id,release_id,target->>'content_hash',cue)::text,'UTF8')),'hex'),
   'version','bilingual-technical-cues-v1','source',source,'target',target,'relation','RELATED','status','PROPOSED',
   'basis','BILINGUAL_CUE','evidence',jsonb_build_object('cue',cue,'source_quote',source_quote,
    'target_quote',target_quote,'summary','국문·영문 기술 용어가 함께 나타나는 탐색 후보예요. 검토된 역량 동등성은 아니에요.'),
   'review',NULL,'source_freshness','CURRENT','catalog_freshness','CURRENT','created_at',NULL,'competency_evidence',false)
  FROM targets WHERE target IS NOT NULL ORDER BY source->>'id',id,cue
 $lexical$ USING anchor;
END $$;

CREATE OR REPLACE FUNCTION catalog.ncs_onet_crosswalk_v1(
 node_id text DEFAULT NULL,page_size integer DEFAULT 20,page_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE answer jsonb; requested_node text:=node_id;
BEGIN
 IF node_id LIKE 'urn:jobtology:ncs:%' THEN node_id:=substr(node_id,length('urn:jobtology:')+1); END IF;
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 100 OR page_offset IS NULL OR page_offset<0
 THEN RAISE EXCEPTION 'INVALID_LIVE_PAGE'; END IF;
 IF node_id IS NULL OR length(requested_node)>500 OR node_id !~ '^(ncs:(occupation|unit):|onet:skill:|urn:jobtology:onet:(occupation):|urn:jobtology:onet-detail:)'
 THEN RAISE EXCEPTION 'INVALID_CROSSWALK_FILTER'; END IF;
 WITH stored AS (
  SELECT jsonb_build_object('mapping_id',m.mapping_id,'version',m.version,'source',m.source,'target',m.target,
   'relation',m.relation,'status',coalesce(r.status,'PROPOSED'),'basis','CATALOG_COMPARISON','evidence',m.evidence,
   'review',CASE WHEN r.review_id IS NOT NULL THEN to_jsonb(r)-'mapping_id' END,
   'source_freshness',CASE WHEN current_source.node IS NULL THEN
    CASE WHEN EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency') THEN 'STALE' ELSE 'UNKNOWN' END
    WHEN current_source.node=m.source THEN 'CURRENT' ELSE 'STALE' END,
   'catalog_freshness',CASE WHEN current_target.node IS NULL THEN 'UNKNOWN'
    WHEN current_target.node=m.target THEN 'CURRENT' ELSE 'STALE' END,'created_at',m.created_at,'competency_evidence',false) AS item
  FROM catalog.ncs_onet_mapping m
  CROSS JOIN LATERAL (SELECT catalog._crosswalk_node(m.source->>'id') AS node) current_source
  CROSS JOIN LATERAL (SELECT catalog._crosswalk_node(m.target->>'id') AS node) current_target
  LEFT JOIN LATERAL (
   SELECT * FROM catalog.ncs_onet_review WHERE mapping_id=m.mapping_id ORDER BY review_id DESC LIMIT 1
  ) r ON true WHERE (m.source->>'id'=node_id OR m.target->>'id'=node_id
   OR m.source->>'id'=catalog._crosswalk_node(node_id)->>'id'
   OR m.target->>'id'=catalog._crosswalk_node(node_id)->>'id') AND r.status IS DISTINCT FROM 'REJECTED'
 ), automatic AS (
  SELECT * FROM catalog._ncs_onet_shared_posting_proposals(node_id)
  UNION ALL SELECT * FROM catalog._ncs_onet_lexical_proposals(node_id)
 ), candidates AS (
  SELECT item FROM stored UNION ALL SELECT a.item FROM automatic a(item)
  WHERE NOT EXISTS(SELECT 1 FROM catalog.ncs_onet_mapping m
   WHERE m.source=a.item->'source' AND m.target=a.item->'target'
    AND EXISTS(SELECT 1 FROM catalog.ncs_onet_review r WHERE r.mapping_id=m.mapping_id))
 ), page AS (
  SELECT item FROM candidates ORDER BY CASE item->>'status' WHEN 'APPROVED' THEN 0 ELSE 1 END,
   CASE item->>'catalog_freshness' WHEN 'CURRENT' THEN 0 ELSE 1 END,item->>'mapping_id'
  LIMIT page_size OFFSET page_offset
 )
 SELECT jsonb_build_object('contract_version','jobtology-ncs-onet-crosswalk-v1','basis','CATALOG_CROSSWALK',
  'competency_evidence',false,'node_id',requested_node,'limit',page_size,'offset',page_offset,
  'total',(SELECT count(*) FROM candidates),'items',(SELECT coalesce(jsonb_agg(item),'[]') FROM page)) INTO answer;
 RETURN answer;
END $$;

REVOKE ALL ON catalog.ncs_onet_mapping,catalog.ncs_onet_review FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog._immutable_crosswalk_record(),catalog._crosswalk_node(text,text),
 catalog.propose_ncs_onet_mapping(text,text,text,jsonb,text),
 catalog.review_ncs_onet_mapping(text,text,text,text,text,bigint),
 catalog._ncs_onet_shared_posting_proposals(text),catalog._ncs_onet_lexical_proposals(text),catalog.ncs_onet_crosswalk_v1(text,integer,integer) FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
  GRANT EXECUTE ON FUNCTION catalog.ncs_onet_crosswalk_v1(text,integer,integer) TO jobtology_catalog_reader;
 END IF;
END $$;
COMMIT;
