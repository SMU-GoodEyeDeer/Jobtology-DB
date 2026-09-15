BEGIN;
CREATE OR REPLACE FUNCTION ontology.object_candidates(id text)
RETURNS TABLE(record_id bigint,kind text,code text,name text,payload jsonb,priority integer,fields text[],entity_id text)
LANGUAGE sql STABLE AS $$
WITH input AS MATERIALIZED (
 SELECT i.* FROM ontology.input_record i JOIN ontology.source_pin p USING(release_id,run_id) WHERE i.release_id=id
), postings AS MATERIALIZED (
 SELECT l.record_id AS list_id,d.record_id AS detail_id,
  (l.normalized||jsonb_strip_nulls(d.normalized))-'representation' AS n
 FROM input l JOIN input d ON d.source_id='job_alio' AND d.normalized->>'representation'='detail'
  AND d.normalized->>'posting_id'=l.normalized->>'posting_id'
 WHERE l.source_id='job_alio' AND l.normalized->>'representation'='list'
), classes AS MATERIALIZED (
 SELECT i.record_id,left(i.normalized->>'code',p.depth::integer*2) AS code,p.label,p.depth::integer,
  CASE WHEN p.depth=4 THEN 'occupation_name' ELSE 'classification_names' END AS field
 FROM input i CROSS JOIN LATERAL jsonb_array_elements_text(
  (i.normalized->'classification_names')||jsonb_build_array(i.normalized->>'occupation_name')) WITH ORDINALITY p(label,depth)
 WHERE i.source_id='ncs_competency' AND p.depth<=4
), edition AS (
 SELECT 'ncs-observed:'||ontology.hash(jsonb_agg(jsonb_build_array(code,label) ORDER BY code,label)) AS version
 FROM (SELECT DISTINCT code,label FROM classes) c
), candidates AS (
 SELECT i.record_id,'organization'::text AS kind,'alio:'||(i.normalized->>'code') AS code,i.normalized->>'name' AS name,
  (i.normalized-'kind')||jsonb_build_object('employer_type','UNKNOWN') AS payload,0 AS priority,
  ARRAY['code','name','government_code','organization_type','supervising_organization_code','website','address','established_date'] AS fields
 FROM input i WHERE i.source_id='alio_organization'
 UNION ALL
 SELECT i.record_id,'organization','alio:'||(i.normalized->>'organization_code'),i.normalized->>'organization_name',
  jsonb_build_object('code',i.normalized->>'organization_code','name',i.normalized->>'organization_name','employer_type','UNKNOWN'),20,
  ARRAY['organization_code','organization_name'] FROM input i WHERE i.source_id='job_alio'
 UNION ALL
 SELECT p.detail_id,'jobPosting','job_alio:'||(p.n->>'posting_id'),p.n->>'title',
  (p.n-'kind')||jsonb_build_object('organization_id',ontology.iri('organization','alio:'||(p.n->>'organization_code')),
   'source_status',CASE p.n->>'ongoing' WHEN 'true' THEN 'OPEN' WHEN 'false' THEN 'CLOSED' ELSE 'UNKNOWN' END,
   'date_precision','DAY','primary_occupation_id',NULL),0,
  ARRAY(SELECT jsonb_object_keys(p.n)) FROM postings p
 UNION ALL
 SELECT p.list_id,'jobPosting','job_alio:'||(p.n->>'posting_id'),p.n->>'title',
  (p.n-'kind')||jsonb_build_object('organization_id',ontology.iri('organization','alio:'||(p.n->>'organization_code')),
   'source_status',CASE p.n->>'ongoing' WHEN 'true' THEN 'OPEN' WHEN 'false' THEN 'CLOSED' ELSE 'UNKNOWN' END,
   'date_precision','DAY','primary_occupation_id',NULL),0,
  ARRAY(SELECT jsonb_object_keys(p.n)) FROM postings p
 UNION ALL
 SELECT i.record_id,'ncsCompetency',i.normalized->>'code',i.normalized->>'name',
  (i.normalized-'kind')||jsonb_build_object('base_code',split_part(i.normalized->>'code','_',1),
    'version',split_part(i.normalized->>'code','_',2),'occupation_id',ontology.iri('occupation','ncs:'||(i.normalized->>'occupation_code'))),0,
  ARRAY['code','name','definition','level','occupation_code','occupation_name','classification_names']
 FROM input i WHERE i.source_id='ncs_competency'
 UNION ALL
 -- An official mapping may mention an old unit absent from the competency feed.
 -- Preserve its identity as a visibly incomplete reference, never invent its definition.
 SELECT i.record_id,'ncsCompetency',i.normalized->>'competency_code','NCS '||(i.normalized->>'competency_code'),
  jsonb_build_object('code',i.normalized->>'competency_code','base_code',split_part(i.normalized->>'competency_code','_',1),
   'version',split_part(i.normalized->>'competency_code','_',2),'label_status','identifier_only','definition_status','unavailable'),50,
  ARRAY['competency_code'] FROM input i WHERE i.source_id='ncs_qualification'
 UNION ALL
 SELECT i.record_id,'occupation','ncs:'||(i.normalized->>'occupation_code'),i.normalized->>'occupation_name',
  jsonb_build_object('code',i.normalized->>'occupation_code','scheme_id',ontology.iri('conceptScheme','ncs')),
  CASE WHEN i.source_id='ncs_competency' THEN 0 ELSE 10 END,ARRAY['occupation_code','occupation_name']
 FROM input i WHERE i.source_id IN ('ncs_competency','ncs_career_path')
 UNION ALL
 SELECT c.record_id,'ncsClass',c.code,c.label,
  jsonb_build_object('code',c.code,'depth',c.depth,'taxonomy_version',e.version,'official_taxonomy_version',NULL,
   'edition_policy','observed-classification-v1','parent_id',CASE WHEN c.depth>1 THEN ontology.iri('ncsClass',left(c.code,length(c.code)-2)) END),0,
  ARRAY['code',c.field] FROM classes c CROSS JOIN edition e WHERE nullif(btrim(c.label),'') IS NOT NULL
 UNION ALL
 SELECT i.record_id,'ncsUnitFamily',split_part(coalesce(i.normalized->>'code',i.normalized->>'competency_code'),'_',1),
  coalesce(i.normalized->>'competency_name',i.normalized->>'name','NCS '||split_part(i.normalized->>'competency_code','_',1)),
  jsonb_build_object('base_code',split_part(coalesce(i.normalized->>'code',i.normalized->>'competency_code'),'_',1),
   'version_selection','unresolved','label_is_display_hint',true),
  CASE i.source_id WHEN 'ncs_career_path' THEN 0 WHEN 'ncs_competency' THEN 10 ELSE 50 END,
  CASE i.source_id WHEN 'ncs_competency' THEN ARRAY['code','name'] ELSE ARRAY['competency_code','competency_name'] END
 FROM input i WHERE i.source_id IN ('ncs_competency','ncs_career_path','ncs_qualification')
 UNION ALL
 SELECT i.record_id,'qualification','qnet:'||(i.normalized->>'qualification_code'),i.normalized->>'qualification_name',
  jsonb_build_object('code',i.normalized->>'qualification_code','scheme_id',ontology.iri('conceptScheme','qnet')),0,
  ARRAY['qualification_code','qualification_name'] FROM input i WHERE i.source_id='ncs_qualification'
 UNION ALL
 SELECT i.record_id,'qualification','qnet:'||(i.normalized->>'qualification_code'),'Q-Net '||(i.normalized->>'qualification_code'),
  jsonb_build_object('code',i.normalized->>'qualification_code','label_status','identifier_only','scheme_id',ontology.iri('conceptScheme','qnet')),50,
  ARRAY['qualification_code'] FROM input i WHERE i.source_id='qnet_schedule'
 UNION ALL
 SELECT i.record_id,'examSession','qnet:'||concat_ws(':',i.normalized->>'qualification_code',i.normalized->>'year',i.normalized->>'category_code',i.normalized->>'round'),
  i.normalized->>'name',(i.normalized-'kind')||jsonb_build_object('qualification_id',ontology.iri('qualification','qnet:'||(i.normalized->>'qualification_code')),
   'date_precision','DAY','timezone','Asia/Seoul'),0,ARRAY['qualification_code','year','category_code','round','name','dates']
 FROM input i WHERE i.source_id='qnet_schedule'
 UNION ALL
 SELECT i.record_id,'careerRank','ncs:'||concat_ws(':',i.normalized->>'occupation_code',i.normalized->>'rank_level'),
  i.normalized->>'rank_name',jsonb_build_object('rank_level',i.normalized->'rank_level','occupation_id',ontology.iri('occupation','ncs:'||(i.normalized->>'occupation_code'))),0,
  ARRAY['occupation_code','rank_level','rank_name'] FROM input i WHERE i.source_id='ncs_career_path'
 UNION ALL
 SELECT i.record_id,'conceptScheme','ncs','국가직무능력표준 (NCS)',
  jsonb_build_object('scheme_code','ncs','publisher','한국산업인력공단','version',e.version,'official_version',NULL),0,ARRAY['code','occupation_code']
 FROM input i CROSS JOIN edition e WHERE i.source_id='ncs_competency'
 UNION ALL
 SELECT i.record_id,'conceptScheme','qnet','Q-Net 자격',jsonb_build_object('scheme_code','qnet','publisher','한국산업인력공단'),0,
  ARRAY['qualification_code'] FROM input i WHERE i.source_id IN ('ncs_qualification','qnet_schedule')
)
SELECT c.*,ontology.iri(c.kind,c.code) FROM candidates c
WHERE nullif(c.code,'') IS NOT NULL AND nullif(btrim(c.name),'') IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION ontology.relation_candidates(id text)
RETURNS TABLE(record_id bigint,subject_id text,predicate text,object_id text,qualifiers jsonb,fields text[])
LANGUAGE sql STABLE AS $$
WITH input AS MATERIALIZED (SELECT i.* FROM ontology.input_record i JOIN ontology.source_pin p USING(release_id,run_id) WHERE i.release_id=id), postings AS MATERIALIZED (
 SELECT (l.normalized||jsonb_strip_nulls(d.normalized))-'representation' AS n
 FROM input l JOIN input d ON d.source_id='job_alio' AND d.normalized->>'representation'='detail'
  AND d.normalized->>'posting_id'=l.normalized->>'posting_id'
 WHERE l.source_id='job_alio' AND l.normalized->>'representation'='list'
), relations AS (
 SELECT i.record_id,ontology.iri('jobPosting','job_alio:'||(i.normalized->>'posting_id')) AS subject_id,
  'POSTED_BY'::text AS predicate,ontology.iri('organization','alio:'||(i.normalized->>'organization_code')) AS object_id,
  '{}'::jsonb AS qualifiers,ARRAY['posting_id','organization_code'] AS fields
 FROM input i JOIN postings p ON p.n->>'posting_id'=i.normalized->>'posting_id'
 WHERE i.source_id='job_alio' AND i.normalized->>'organization_code'=p.n->>'organization_code'
 UNION ALL
 SELECT i.record_id,ontology.iri('ncsCompetency',i.normalized->>'code'),'BELONGS_TO_OCCUPATION',
  ontology.iri('occupation','ncs:'||(i.normalized->>'occupation_code')),'{}',ARRAY['code','occupation_code']
 FROM input i WHERE i.source_id='ncs_competency'
 UNION ALL
 SELECT i.record_id,ontology.iri('ncsCompetency',coalesce(i.normalized->>'code',i.normalized->>'competency_code')),'VERSION_OF',
  ontology.iri('ncsUnitFamily',split_part(coalesce(i.normalized->>'code',i.normalized->>'competency_code'),'_',1)),
  jsonb_build_object('version_selection','none'),CASE WHEN i.source_id='ncs_competency' THEN ARRAY['code'] ELSE ARRAY['competency_code'] END
 FROM input i WHERE i.source_id IN ('ncs_competency','ncs_qualification')
 UNION ALL
 SELECT i.record_id,ontology.iri('ncsCompetency',i.normalized->>'code'),'CLASSIFIED_AS',
  ontology.iri('ncsClass',left(i.normalized->>'code',8)),'{}',ARRAY['code','occupation_code']
 FROM input i WHERE i.source_id='ncs_competency'
 UNION ALL
 SELECT i.record_id,ontology.iri('occupation','ncs:'||(i.normalized->>'occupation_code')),'CLASSIFIED_AS',
  ontology.iri('ncsClass',i.normalized->>'occupation_code'),'{}',ARRAY['occupation_code','occupation_name']
 FROM input i WHERE i.source_id='ncs_competency'
 UNION ALL
 SELECT i.record_id,ontology.iri('ncsClass',left(i.normalized->>'code',depth*2-2)),'BROADER_THAN',
  ontology.iri('ncsClass',left(i.normalized->>'code',depth*2)),'{}',ARRAY['code','classification_names','occupation_name']
 FROM input i CROSS JOIN generate_series(2,4) depth WHERE i.source_id='ncs_competency'
 UNION ALL
 SELECT i.record_id,ontology.iri('conceptScheme','ncs'),'HAS_MEMBER',ontology.iri('occupation','ncs:'||(i.normalized->>'occupation_code')),
  '{}',ARRAY['occupation_code'] FROM input i WHERE i.source_id='ncs_competency'
 UNION ALL
 -- Curriculum association is deliberately not an ATTESTS capability assertion.
 SELECT i.record_id,ontology.iri('qualification','qnet:'||(i.normalized->>'qualification_code')),'CURRICULUM_REFERENCES',
  ontology.iri('ncsCompetency',i.normalized->>'competency_code'),i.normalized-ARRAY['kind','qualification_code','qualification_name','competency_code'],
  ARRAY['qualification_code','competency_code','standard_version','unit_type','minimum_training_hours','total_training_hours','examining_organization']
 FROM input i WHERE i.source_id='ncs_qualification'
 UNION ALL
 SELECT i.record_id,ontology.iri('qualification','qnet:'||(i.normalized->>'qualification_code')),'HAS_EXAM_SESSION',
  ontology.iri('examSession','qnet:'||concat_ws(':',i.normalized->>'qualification_code',i.normalized->>'year',i.normalized->>'category_code',i.normalized->>'round')),
  '{}',ARRAY['qualification_code','year','category_code','round'] FROM input i WHERE i.source_id='qnet_schedule'
 UNION ALL
 SELECT i.record_id,ontology.iri('occupation','ncs:'||(i.normalized->>'occupation_code')),'HAS_CAREER_RANK',
  ontology.iri('careerRank','ncs:'||concat_ws(':',i.normalized->>'occupation_code',i.normalized->>'rank_level')),
  '{}',ARRAY['occupation_code','rank_level','rank_name'] FROM input i WHERE i.source_id='ncs_career_path'
 UNION ALL
 SELECT i.record_id,ontology.iri('careerRank','ncs:'||concat_ws(':',i.normalized->>'occupation_code',i.normalized->>'rank_level')),'REFERENCES_UNIT_FAMILY',
  ontology.iri('ncsUnitFamily',i.normalized->>'competency_code'),jsonb_build_object('competency_level',i.normalized->'competency_level','version_selection','unresolved'),
  ARRAY['occupation_code','rank_level','competency_code','competency_level'] FROM input i WHERE i.source_id='ncs_career_path'
)
SELECT * FROM relations WHERE subject_id IS NOT NULL AND object_id IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION ontology.assemble_sources(id text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 PERFORM ontology.require_preparing(id);
 PERFORM ontology.check_frozen_sources(id);
 CREATE TEMP TABLE ontology_candidate ON COMMIT DROP AS SELECT * FROM ontology.object_candidates(id);
 CREATE INDEX ON ontology_candidate(entity_id);
 IF EXISTS(SELECT 1 FROM ontology_candidate WHERE kind='ncsCompetency' AND code!~'^[0-9]{10}_[0-9]{2}v[0-9]+$')
 THEN RAISE EXCEPTION 'INVALID_VERSIONED_NCS_ID'; END IF;
 IF EXISTS(SELECT 1 FROM ontology_candidate WHERE kind='ncsUnitFamily' AND code!~'^[0-9]{10}$')
 THEN RAISE EXCEPTION 'INVALID_NCS_FAMILY_ID'; END IF;
 IF EXISTS(SELECT 1 FROM ontology_candidate c JOIN ontology.entity e USING(entity_id) WHERE c.kind<>e.kind OR c.code<>e.code)
 THEN RAISE EXCEPTION 'ONTOLOGY_IDENTITY_CONFLICT'; END IF;
 INSERT INTO ontology.entity(entity_id,kind,code,scheme_id)
 SELECT DISTINCT entity_id,kind,code,CASE WHEN kind IN ('occupation','ncsClass','ncsCompetency','ncsUnitFamily','careerRank') THEN ontology.iri('conceptScheme','ncs')
  WHEN kind IN ('qualification','examSession') THEN ontology.iri('conceptScheme','qnet') END FROM ontology_candidate
 ON CONFLICT DO NOTHING;
 -- Preferred labels are deterministic display choices among observed names.
 -- All observed labels remain aliases; this does not infer an official rename.
 CREATE TEMP TABLE ontology_chosen ON COMMIT DROP AS
 WITH frequency AS (SELECT entity_id,priority,name,payload,count(*) frequency,min(record_id) first_record
  FROM ontology_candidate GROUP BY entity_id,priority,name,payload), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY entity_id ORDER BY priority,frequency DESC,name COLLATE "C",payload::text COLLATE "C",first_record) rn FROM frequency),
 aliases AS (SELECT entity_id,jsonb_agg(name ORDER BY name COLLATE "C") aliases FROM (SELECT DISTINCT entity_id,name FROM ontology_candidate WHERE priority<50) a GROUP BY entity_id)
 SELECT r.entity_id,e.kind,r.name,r.payload||jsonb_build_object('name',r.name,'aliases',coalesce(a.aliases,'[]'),
  'preferred_label_policy','source-priority-observed-frequency-v1') AS payload
 FROM ranked r JOIN ontology.entity e USING(entity_id) LEFT JOIN aliases a USING(entity_id) WHERE rn=1;
 INSERT INTO ontology.revision(revision_id,entity_id,kind,name,payload,payload_hash)
 SELECT ontology.hash(jsonb_build_array(entity_id,'hop-ontology-v1',payload)),entity_id,kind,name,payload,ontology.hash(payload)
 FROM ontology_chosen ON CONFLICT DO NOTHING;
 IF EXISTS(SELECT 1 FROM ontology_chosen c JOIN ontology.revision r
  ON r.revision_id=ontology.hash(jsonb_build_array(c.entity_id,'hop-ontology-v1',c.payload))
  WHERE r.entity_id<>c.entity_id OR r.kind<>c.kind OR r.name<>c.name OR r.payload<>c.payload OR r.payload_hash<>ontology.hash(c.payload))
 THEN RAISE EXCEPTION 'ONTOLOGY_REVISION_CONTENT_CONFLICT'; END IF;
 IF EXISTS(SELECT 1 FROM ontology_chosen c JOIN ontology.release_revision m ON m.release_id=id AND m.entity_id=c.entity_id
  WHERE m.revision_id<>ontology.hash(jsonb_build_array(c.entity_id,'hop-ontology-v1',c.payload)))
 THEN RAISE EXCEPTION 'RELEASE_REVISION_IS_IMMUTABLE'; END IF;
 INSERT INTO ontology.release_revision SELECT id,entity_id,ontology.hash(jsonb_build_array(entity_id,'hop-ontology-v1',payload)) FROM ontology_chosen ON CONFLICT DO NOTHING;
 INSERT INTO ontology.revision_support
 SELECT id,entity_id,record_id,array_agg(DISTINCT f ORDER BY f) FROM ontology_candidate CROSS JOIN LATERAL unnest(fields) f
 GROUP BY entity_id,record_id ON CONFLICT DO NOTHING;
 CREATE TEMP TABLE ontology_edges ON COMMIT DROP AS
 SELECT *,ontology.hash(jsonb_build_array(subject_id,predicate,object_id,qualifiers,'source-reference-v1')) AS relation_id FROM ontology.relation_candidates(id);
 IF EXISTS(SELECT 1 FROM ontology_edges c WHERE NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id AND entity_id=c.subject_id)
  OR NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id AND entity_id=c.object_id))
 THEN RAISE EXCEPTION 'ONTOLOGY_RELATION_TARGET_NOT_IN_RELEASE'; END IF;
 INSERT INTO ontology.source_relation(relation_id,subject_id,predicate,object_id,qualifiers)
 SELECT DISTINCT relation_id,subject_id,predicate,object_id,qualifiers FROM ontology_edges ON CONFLICT DO NOTHING;
 IF EXISTS(SELECT 1 FROM ontology_edges e JOIN ontology.source_relation r USING(relation_id)
  WHERE r.subject_id<>e.subject_id OR r.predicate<>e.predicate OR r.object_id<>e.object_id OR r.qualifiers<>e.qualifiers)
 THEN RAISE EXCEPTION 'ONTOLOGY_RELATION_CONTENT_CONFLICT'; END IF;
 INSERT INTO ontology.release_relation SELECT id,relation_id,record_id,fields FROM ontology_edges ON CONFLICT DO NOTHING;
 INSERT INTO ontology.quality_observation
 SELECT id,entity_id,'REFERENCE_WITHOUT_DEFINITION',jsonb_build_object('kind',kind,'label',name)
 FROM ontology_chosen WHERE payload->>'label_status'='identifier_only' ON CONFLICT DO NOTHING;
 PERFORM ontology.check_frozen_sources(id);
END $$;

CREATE OR REPLACE VIEW ontology.source_coverage AS
WITH coverage AS (
 SELECT i.release_id,i.source_id,count(*) AS records,
  count(*) FILTER(WHERE EXISTS(SELECT 1 FROM ontology.revision_support s
   WHERE s.release_id=i.release_id AND s.record_id=i.record_id)) AS supported
 FROM ontology.input_record i JOIN ontology.source_pin p USING(release_id,run_id) GROUP BY i.release_id,i.source_id
)
SELECT p.release_id,p.source_id,p.record_count,coalesce(c.supported,0) AS supported_records,
 coalesce(c.records-c.supported,0) AS unaccounted_records
FROM ontology.source_pin p LEFT JOIN coverage c USING(release_id,source_id);
COMMIT;
