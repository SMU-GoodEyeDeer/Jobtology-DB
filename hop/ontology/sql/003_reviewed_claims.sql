-- Freeze review decisions before building a release. This never accepts model output.
BEGIN;
CREATE TABLE IF NOT EXISTS ontology.review_freeze (
 release_id text PRIMARY KEY REFERENCES ontology.corpus_release,
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 revision_cutoff bigint NOT NULL, extraction_decision_cutoff bigint NOT NULL,
 link_decision_cutoff bigint NOT NULL,
 policy_version text NOT NULL DEFAULT 'independent-review-v1'
);
CREATE TABLE IF NOT EXISTS ontology.posting_selection (
 release_id text NOT NULL REFERENCES ontology.review_freeze,
 entity_id text NOT NULL,
 posting_revision_id text NOT NULL REFERENCES ontology.revision,
 source_hash text NOT NULL,
 source_data jsonb NOT NULL,
 extraction_revision_id text REFERENCES enrichment.extraction_revision,
 decision_id bigint REFERENCES enrichment.extraction_decision,
 outcome text NOT NULL CHECK(outcome IN ('ACCEPTED','REJECTED','REVIEW_REQUIRED','NOT_PROCESSED','PROCESSING','PROCESSING_FAILED')),
 extraction jsonb,
 provenance jsonb NOT NULL,
 PRIMARY KEY(release_id,entity_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.release_revision,
 CHECK((outcome='ACCEPTED')=(extraction IS NOT NULL)),
 CHECK(outcome<>'ACCEPTED' OR (extraction_revision_id IS NOT NULL AND decision_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS ontology.link_selection (
 release_id text NOT NULL,
 entity_id text NOT NULL,
 candidate_id text NOT NULL REFERENCES enrichment.link_candidate,
 decision_id bigint REFERENCES enrichment.link_decision,
 outcome text NOT NULL CHECK(outcome IN ('ACCEPTED','REJECTED','REVIEW_REQUIRED','NCS_SNAPSHOT_MISMATCH','EXTRACTION_NOT_ACCEPTED')),
 candidate jsonb NOT NULL,
 review jsonb,
 PRIMARY KEY(release_id,candidate_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.posting_selection
);
CREATE TABLE IF NOT EXISTS ontology.text_artifact (
 artifact_id text PRIMARY KEY,
 posting_id text NOT NULL REFERENCES ontology.entity,
 source_field text NOT NULL,
 input_sha256 text NOT NULL,
 normalized_text text NOT NULL,
 text_sha256 text NOT NULL,
 normalization_version text NOT NULL DEFAULT 'nfc-lf-v1'
);
CREATE TABLE IF NOT EXISTS ontology.artifact_source (
 release_id text NOT NULL,
 artifact_id text NOT NULL REFERENCES ontology.text_artifact,
 record_id bigint NOT NULL,
 source_field text NOT NULL,
 PRIMARY KEY(release_id,artifact_id,record_id),
 FOREIGN KEY(release_id,record_id) REFERENCES ontology.input_record
);
CREATE TABLE IF NOT EXISTS ontology.evidence_span (
 evidence_id text PRIMARY KEY,
 artifact_id text NOT NULL REFERENCES ontology.text_artifact,
 start_offset integer NOT NULL CHECK(start_offset>=0),
 end_offset integer NOT NULL CHECK(end_offset>start_offset),
 excerpt text NOT NULL CHECK(length(excerpt)>0),
 excerpt_sha256 text NOT NULL,
 offset_unit text NOT NULL DEFAULT 'UNICODE_CODE_POINT' CHECK(offset_unit='UNICODE_CODE_POINT'),
 locator_version text NOT NULL DEFAULT 'half-open-nfc-lf-v1',
 UNIQUE(artifact_id,start_offset,end_offset)
);
CREATE TABLE IF NOT EXISTS ontology.position_claim (
 position_id text PRIMARY KEY,
 posting_revision_id text NOT NULL REFERENCES ontology.revision,
 local_id text NOT NULL,
 name text NOT NULL,
 content_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS ontology.release_position (
 release_id text NOT NULL,
 entity_id text NOT NULL,
 position_id text NOT NULL REFERENCES ontology.position_claim,
 PRIMARY KEY(release_id,position_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.posting_selection
);
CREATE TABLE IF NOT EXISTS ontology.claim (
 claim_id text PRIMARY KEY,
 posting_revision_id text NOT NULL REFERENCES ontology.revision,
 kind text NOT NULL CHECK(kind IN ('DUTY','REQUIREMENT')),
 ordinal integer NOT NULL CHECK(ordinal>=0),
 text text NOT NULL,
 category text,
 condition_kind text,
 logic text,
 applicability text NOT NULL,
 interpretation_state text NOT NULL CHECK(interpretation_state IN ('SOURCE_TEXT','SOURCE_EXPRESSION')),
 assertion_kind text NOT NULL DEFAULT 'REVIEWED_EXTRACTION' CHECK(assertion_kind='REVIEWED_EXTRACTION'),
 payload jsonb NOT NULL,
 content_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS ontology.release_claim (
 release_id text NOT NULL,
 entity_id text NOT NULL,
 claim_id text NOT NULL REFERENCES ontology.claim,
 PRIMARY KEY(release_id,claim_id),
 FOREIGN KEY(release_id,entity_id) REFERENCES ontology.posting_selection
);
CREATE TABLE IF NOT EXISTS ontology.claim_position (
 claim_id text NOT NULL REFERENCES ontology.claim,
 position_id text NOT NULL REFERENCES ontology.position_claim,
 PRIMARY KEY(claim_id,position_id)
);
CREATE TABLE IF NOT EXISTS ontology.claim_evidence (
 claim_id text NOT NULL REFERENCES ontology.claim,
 part_index integer NOT NULL CHECK(part_index>=0),
 evidence_id text NOT NULL REFERENCES ontology.evidence_span,
 PRIMARY KEY(claim_id,part_index)
);
CREATE TABLE IF NOT EXISTS ontology.position_evidence (
 position_id text PRIMARY KEY REFERENCES ontology.position_claim,
 evidence_id text NOT NULL REFERENCES ontology.evidence_span
);
CREATE TABLE IF NOT EXISTS ontology.condition_node (
 claim_id text NOT NULL REFERENCES ontology.claim,
 node_index integer NOT NULL CHECK(node_index>=0),
 operator text NOT NULL CHECK(operator IN ('atom','all_of','any_of','if_then','except')),
 text text NOT NULL,
 parts jsonb NOT NULL,
 PRIMARY KEY(claim_id,node_index)
);
CREATE TABLE IF NOT EXISTS ontology.condition_child (
 claim_id text NOT NULL,
 parent_index integer NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal>=0),
 child_index integer NOT NULL,
 PRIMARY KEY(claim_id,parent_index,ordinal),
 UNIQUE(claim_id,child_index),
 FOREIGN KEY(claim_id,parent_index) REFERENCES ontology.condition_node,
 FOREIGN KEY(claim_id,child_index) REFERENCES ontology.condition_node,
 CHECK(child_index>parent_index)
);
CREATE TABLE IF NOT EXISTS ontology.condition_evidence (
 claim_id text NOT NULL,
 node_index integer NOT NULL,
 part_index integer NOT NULL CHECK(part_index>=0),
 evidence_id text NOT NULL REFERENCES ontology.evidence_span,
 PRIMARY KEY(claim_id,node_index,part_index),
 FOREIGN KEY(claim_id,node_index) REFERENCES ontology.condition_node
);
CREATE TABLE IF NOT EXISTS ontology.mapping_claim (
 mapping_id text PRIMARY KEY,
 duty_claim_id text NOT NULL REFERENCES ontology.claim,
 target_revision_id text NOT NULL REFERENCES ontology.revision,
 predicate text NOT NULL DEFAULT 'ALIGNS_WITH' CHECK(predicate='ALIGNS_WITH'),
 assertion_kind text NOT NULL CHECK(assertion_kind IN ('MODEL_INFERRED','REVIEWER_INFERRED')),
 reason text NOT NULL,
 content_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS ontology.release_mapping (
 release_id text NOT NULL,
 mapping_id text NOT NULL REFERENCES ontology.mapping_claim,
 candidate_id text NOT NULL,
 PRIMARY KEY(release_id,mapping_id),
 FOREIGN KEY(release_id,candidate_id) REFERENCES ontology.link_selection
);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['review_freeze','posting_selection','link_selection','text_artifact','artifact_source',
  'evidence_span','position_claim','release_position','claim','release_claim','claim_position','claim_evidence',
  'position_evidence','condition_node','condition_child','condition_evidence','mapping_claim','release_mapping'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='ontology_immutable_'||name AND tgrelid=('ontology.'||name)::regclass) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON ontology.%I FOR EACH ROW EXECUTE FUNCTION ontology.immutable()',
    'ontology_immutable_'||name,name);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION ontology.freeze_reviews(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE revisions bigint; decisions bigint; links bigint; interpretations bigint; rule_decisions bigint;
BEGIN
 PERFORM ontology.require_preparing(id);
 PERFORM ontology.check_frozen_sources(id);
 PERFORM ontology.verify_observation_membership_v1(id);
 PERFORM ontology.verify_document_inputs(id);
 IF EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM ontology.release_revision WHERE release_id=id) THEN RAISE EXCEPTION 'ASSEMBLE_SOURCES_FIRST'; END IF;
 -- Wait for in-flight writers so the copied decisions form a committed, coherent cut.
 -- These locks last only for review selection, not graph publication or inference.
 LOCK TABLE enrichment.extraction_revision,enrichment.extraction_decision,enrichment.link_candidate,enrichment.link_decision,
  enrichment.rule_interpretation,enrichment.rule_interpretation_decision IN SHARE MODE;
 SELECT coalesce(max(revision_no),0) INTO revisions FROM enrichment.extraction_revision;
 SELECT coalesce(max(decision_id),0) INTO decisions FROM enrichment.extraction_decision;
 SELECT coalesce(max(decision_id),0) INTO links FROM enrichment.link_decision;
 INSERT INTO ontology.review_freeze(release_id,revision_cutoff,extraction_decision_cutoff,link_decision_cutoff)
 VALUES(id,revisions,decisions,links);
 INSERT INTO ontology.posting_selection
 SELECT id,m.entity_id,m.revision_id,enrichment.hash(src.data::text),src.data,r.revision_id,d.decision_id,
  CASE WHEN d.decision='ACCEPT' THEN 'ACCEPTED' WHEN d.decision='REJECT' THEN 'REJECTED'
   WHEN r.revision_id IS NOT NULL THEN 'REVIEW_REQUIRED'
   WHEN a.state IN ('REJECTED','ERROR','BUDGET_BLOCKED') THEN 'PROCESSING_FAILED'
   WHEN a.state IN ('VALIDATED','SKIPPED') THEN 'REVIEW_REQUIRED'
   WHEN latest.item_id IS NULL THEN 'NOT_PROCESSED' ELSE 'PROCESSING' END,
  CASE WHEN d.decision='ACCEPT' THEN r.extraction END,
  jsonb_build_object('revision',to_jsonb(r)-'extraction'-'raw_output','review',to_jsonb(d),
   'item_id',coalesce(r.item_id,latest.item_id),'batch_id',b.batch_id,'settings',b.settings,
   'prompt_version',b.settings->>'prompt_version','raw_output_hash',ontology.hash(r.raw_output),
   'extraction_hash',ontology.hash(r.extraction),'last_attempt_state',a.state,'issues',a.issues)
  ||CASE WHEN chosen.bundle_id IS NOT NULL THEN jsonb_build_object('input_bundle_id',chosen.bundle_id) ELSE '{}'::jsonb END
 FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
 LEFT JOIN ontology.document_input chosen ON chosen.release_id=m.release_id AND chosen.entity_id=m.entity_id
 CROSS JOIN LATERAL (SELECT ontology.posting_input(id,m.entity_id,v.payload) AS data) src
 LEFT JOIN LATERAL (
  SELECT x.* FROM enrichment.extraction_revision x JOIN enrichment.item i USING(item_id)
  JOIN enrichment.batch b USING(batch_id)
  WHERE b.mode='ENRICH' AND i.posting_id=v.payload->>'posting_id' AND i.source_hash=enrichment.hash(src.data::text)
  AND i.source_data=src.data AND x.revision_no<=revisions ORDER BY x.revision_no DESC LIMIT 1
 ) r ON true
 LEFT JOIN LATERAL (SELECT * FROM enrichment.extraction_decision x WHERE x.revision_id=r.revision_id
  AND x.decision_id<=decisions ORDER BY x.decision_id DESC LIMIT 1) d ON true
 LEFT JOIN LATERAL (SELECT i.* FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
  WHERE b.mode='ENRICH' AND i.posting_id=v.payload->>'posting_id' AND i.source_hash=enrichment.hash(src.data::text)
   AND i.source_data=src.data ORDER BY b.created_at DESC,b.batch_id DESC LIMIT 1) latest ON true
 LEFT JOIN enrichment.item ri ON ri.item_id=r.item_id
 LEFT JOIN enrichment.batch b ON b.batch_id=coalesce(ri.batch_id,latest.batch_id)
 LEFT JOIN enrichment.attempt a ON a.attempt_id=coalesce(ri.extraction_id,latest.extraction_id)
 WHERE m.release_id=id AND v.kind='jobPosting';
 INSERT INTO ontology.link_selection
 SELECT id,p.entity_id,c.candidate_id,d.decision_id,
  CASE WHEN p.outcome<>'ACCEPTED' THEN 'EXTRACTION_NOT_ACCEPTED'
   WHEN c.ncs_run_id<>n.run_id THEN 'NCS_SNAPSHOT_MISMATCH'
   WHEN d.decision='ACCEPT' THEN 'ACCEPTED' WHEN d.decision='REJECT' THEN 'REJECTED' ELSE 'REVIEW_REQUIRED' END,
  to_jsonb(c),to_jsonb(d)
 FROM ontology.posting_selection p JOIN enrichment.link_candidate c ON c.revision_id=p.extraction_revision_id
 JOIN ontology.source_pin n ON n.release_id=id AND n.source_id='ncs_competency'
 LEFT JOIN LATERAL (SELECT * FROM enrichment.link_decision x WHERE x.candidate_id=c.candidate_id
  AND x.decision_id<=links ORDER BY x.decision_id DESC LIMIT 1) d ON true WHERE p.release_id=id;
 SELECT coalesce(max(interpretation_no),0) INTO interpretations FROM enrichment.rule_interpretation;
 SELECT coalesce(max(decision_id),0) INTO rule_decisions FROM enrichment.rule_interpretation_decision;
 INSERT INTO ontology.rule_freeze VALUES(id,interpretations,rule_decisions,'guarded-rules-v1');
 INSERT INTO ontology.rule_selection
 SELECT id,p.entity_id,r.interpretation_id,r.requirement_index,d.decision_id,
  CASE WHEN p.outcome<>'ACCEPTED' THEN 'EXTRACTION_NOT_ACCEPTED'
   WHEN r.source_hash<>p.source_hash OR r.extraction_hash<>enrichment.hash(p.extraction::text) THEN 'SOURCE_MISMATCH'
   WHEN d.decision='ACCEPT' THEN 'ACCEPTED' WHEN d.decision='REJECT' THEN 'REJECTED' ELSE 'REVIEW_REQUIRED' END,
  to_jsonb(r),to_jsonb(d)
 FROM ontology.posting_selection p
 CROSS JOIN LATERAL (
  SELECT DISTINCT ON(requirement_index) * FROM enrichment.rule_interpretation x
  WHERE x.revision_id=p.extraction_revision_id AND x.interpretation_no<=interpretations
  ORDER BY requirement_index,interpretation_no DESC
 ) r
 LEFT JOIN LATERAL (SELECT * FROM enrichment.rule_interpretation_decision x
  WHERE x.interpretation_id=r.interpretation_id AND x.decision_id<=rule_decisions ORDER BY decision_id DESC LIMIT 1) d ON true
 WHERE p.release_id=id;
END $$;

CREATE OR REPLACE FUNCTION ontology.normalize_text(value text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT normalize(replace(replace(value,E'\r\n',E'\n'),E'\r',E'\n'),NFC)
$$;

-- The first whitespace-equivalent match inside the explicitly cited source range.
-- Positions are zero-based/half-open code points in the NFC/LF artifact, never bytes.
CREATE OR REPLACE FUNCTION ontology.locate_fragment(value text,fragment text)
RETURNS TABLE(start_offset integer,end_offset integer,excerpt text) LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE folded text:=''; starts integer[]:='{}'; ends integer[]:='{}'; c text; j integer; k integer;
 needle text:=enrichment.fold_space_v2(ontology.normalize_text(fragment)); found integer;
BEGIN
 IF value IS NULL OR nullif(needle,'') IS NULL THEN RAISE EXCEPTION 'EMPTY_EVIDENCE_FRAGMENT'; END IF;
 FOR j IN 1..length(value) LOOP
  c:=substring(value FROM j FOR 1); k:=length(folded);
  IF c ~ '[[:space:]]' THEN
   IF k>0 AND right(folded,1)=' ' THEN ends[k]:=j;
   ELSE folded:=folded||' '; starts:=array_append(starts,j-1); ends:=array_append(ends,j); END IF;
  ELSE folded:=folded||c; starts:=array_append(starts,j-1); ends:=array_append(ends,j); END IF;
 END LOOP;
 found:=position(needle in folded);
 IF found=0 THEN RAISE EXCEPTION 'UNSUPPORTED_ONTOLOGY_FRAGMENT: %',fragment; END IF;
 start_offset:=starts[found]; end_offset:=ends[found+length(needle)-1];
 excerpt:=substring(value FROM start_offset+1 FOR end_offset-start_offset); RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION ontology.store_fragment(id text,posting text,row_data jsonb,fragment text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE p ontology.posting_selection%ROWTYPE; source_field text; original text; normalized text;
 first_char integer; last_char integer; prefix text; region text; suffix text; aid text; eid text;
 span record; supported integer;
BEGIN
 PERFORM ontology.require_preparing(id);
 SELECT * INTO STRICT p FROM ontology.posting_selection WHERE release_id=id AND entity_id=posting AND outcome='ACCEPTED';
 SELECT min(x->>'field'),min((x->>'start')::integer),max((x->>'end')::integer)
 INTO source_field,first_char,last_char
 FROM jsonb_array_elements(enrichment.source_passages_v2(p.source_data)) x
 WHERE row_data->'evidence_ids' @> jsonb_build_array(x->>'id');
 IF source_field IS NULL OR (SELECT count(DISTINCT x->>'field') FROM jsonb_array_elements(enrichment.source_passages_v2(p.source_data)) x
  WHERE row_data->'evidence_ids' @> jsonb_build_array(x->>'id'))<>1 THEN RAISE EXCEPTION 'INVALID_ONTOLOGY_EVIDENCE_RANGE'; END IF;
 original:=p.source_data->>source_field; normalized:=ontology.normalize_text(original);
 -- source_passages splits on LF, leaving a CR at the end of a CRLF line.
 -- Include its paired LF in the range so normalization never counts it twice.
 IF substring(original FROM last_char FOR 2)=E'\r\n' THEN last_char:=last_char+1; END IF;
 prefix:=ontology.normalize_text(left(original,first_char-1));
 region:=ontology.normalize_text(substring(original FROM first_char FOR last_char-first_char+1));
 suffix:=ontology.normalize_text(substring(original FROM last_char+1));
 IF prefix||region||suffix<>normalized THEN RAISE EXCEPTION 'EVIDENCE_NORMALIZATION_BOUNDARY'; END IF;
 SELECT * INTO STRICT span FROM ontology.locate_fragment(region,fragment);
 aid:=ontology.hash(jsonb_build_array(posting,source_field,enrichment.hash(original),'nfc-lf-v1'));
 INSERT INTO ontology.text_artifact(artifact_id,posting_id,source_field,input_sha256,normalized_text,text_sha256)
 VALUES(aid,posting,source_field,enrichment.hash(original),normalized,enrichment.hash(normalized)) ON CONFLICT DO NOTHING;
 IF enrichment.is_attachment_field(p.source_data,source_field) THEN
  PERFORM ontology.store_document_artifact(id,posting,aid,source_field);
 ELSE
 INSERT INTO ontology.artifact_source
 SELECT id,aid,i.record_id,source_field FROM ontology.input_record i
 JOIN ontology.revision v ON v.revision_id=p.posting_revision_id
 WHERE i.release_id=id AND i.source_id='job_alio' AND i.normalized->>'posting_id'=v.payload->>'posting_id'
  AND i.normalized->>source_field=original ON CONFLICT DO NOTHING;
 SELECT count(*) INTO supported FROM ontology.artifact_source WHERE release_id=id AND artifact_id=aid;
 IF supported=0 THEN RAISE EXCEPTION 'EVIDENCE_NOT_IN_PINNED_SOURCE'; END IF;
 END IF;
 eid:=ontology.hash(jsonb_build_array(aid,length(prefix)+span.start_offset,length(prefix)+span.end_offset));
 INSERT INTO ontology.evidence_span(evidence_id,artifact_id,start_offset,end_offset,excerpt,excerpt_sha256)
 VALUES(eid,aid,length(prefix)+span.start_offset,length(prefix)+span.end_offset,span.excerpt,enrichment.hash(span.excerpt))
 ON CONFLICT DO NOTHING;
 RETURN eid;
END $$;

CREATE OR REPLACE FUNCTION ontology.assemble_claims(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p ontology.posting_selection%ROWTYPE; section text; row_data jsonb; n jsonb; c jsonb;
 ordinal integer; index integer; part integer; pos text; cid text; pid text; eid text; target text; mid text; link record;
BEGIN
 PERFORM ontology.require_preparing(id); PERFORM ontology.check_frozen_sources(id);
 IF NOT EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'FREEZE_REVIEWS_FIRST'; END IF;
 FOR p IN SELECT * FROM ontology.posting_selection WHERE release_id=id AND outcome='ACCEPTED' LOOP
  IF p.extraction->>'schema_version' IS NULL OR p.extraction->>'schema_version' NOT IN ('ko-v3','ko-v4','ko-v5','ko-v6','ko-v7')
  THEN RAISE EXCEPTION 'ONTOLOGY_REQUIRES_FRAGMENT_CONTRACT'; END IF;
  FOR row_data IN SELECT jsonb_array_elements(p.extraction->'positions') LOOP
   pid:=ontology.hash(jsonb_build_array(p.posting_revision_id,'position',row_data));
   INSERT INTO ontology.position_claim VALUES(pid,p.posting_revision_id,row_data->>'id',row_data->>'name',ontology.hash(row_data)) ON CONFLICT DO NOTHING;
   INSERT INTO ontology.release_position VALUES(id,p.entity_id,pid) ON CONFLICT DO NOTHING;
   eid:=ontology.store_fragment(id,p.entity_id,row_data,row_data->>'name');
   INSERT INTO ontology.position_evidence VALUES(pid,eid) ON CONFLICT DO NOTHING;
  END LOOP;
  FOREACH section IN ARRAY ARRAY['duties','requirements'] LOOP
   ordinal:=0;
   FOR row_data IN SELECT jsonb_array_elements(p.extraction->section) LOOP
    cid:=ontology.hash(jsonb_build_array(p.posting_revision_id,section,ordinal,row_data));
    INSERT INTO ontology.claim VALUES(cid,p.posting_revision_id,CASE section WHEN 'duties' THEN 'DUTY' ELSE 'REQUIREMENT' END,
     ordinal,row_data->>'text',row_data->>'category',row_data->>'kind',row_data->>'logic',
     coalesce(row_data->>'applicability',CASE WHEN jsonb_array_length(row_data->'position_ids')>0 THEN 'explicit_positions' ELSE 'unresolved_scope' END),
     CASE WHEN jsonb_array_length(coalesce(row_data->'expression','[]'))>0 THEN 'SOURCE_EXPRESSION' ELSE 'SOURCE_TEXT' END,
     'REVIEWED_EXTRACTION',row_data,ontology.hash(row_data)) ON CONFLICT DO NOTHING;
    INSERT INTO ontology.release_claim VALUES(id,p.entity_id,cid) ON CONFLICT DO NOTHING;
    FOR pos IN SELECT jsonb_array_elements_text(row_data->'position_ids') LOOP
     SELECT x.position_id INTO STRICT pid FROM ontology.release_position m JOIN ontology.position_claim x USING(position_id)
      WHERE m.release_id=id AND m.entity_id=p.entity_id AND x.local_id=pos;
     INSERT INTO ontology.claim_position VALUES(cid,pid) ON CONFLICT DO NOTHING;
    END LOOP;
    part:=0;
    FOR c IN SELECT jsonb_array_elements(row_data->'text_parts') LOOP
     eid:=ontology.store_fragment(id,p.entity_id,row_data,c#>>'{}');
     INSERT INTO ontology.claim_evidence VALUES(cid,part,eid) ON CONFLICT DO NOTHING; part:=part+1;
    END LOOP;
    IF section='requirements' THEN
     index:=0;
     FOR n IN SELECT jsonb_array_elements(row_data->'expression') LOOP
      INSERT INTO ontology.condition_node VALUES(cid,index,n->>'op',n->>'text',n->'parts') ON CONFLICT DO NOTHING;
      part:=0;
      FOR c IN SELECT jsonb_array_elements(n->'parts') LOOP
       eid:=ontology.store_fragment(id,p.entity_id,row_data,c#>>'{}');
       INSERT INTO ontology.condition_evidence VALUES(cid,index,part,eid) ON CONFLICT DO NOTHING; part:=part+1;
      END LOOP;
      index:=index+1;
     END LOOP;
     index:=0;
     FOR n IN SELECT jsonb_array_elements(row_data->'expression') LOOP
      part:=0;
      FOR c IN SELECT jsonb_array_elements(n->'children') LOOP
       INSERT INTO ontology.condition_child VALUES(cid,index,part,(c#>>'{}')::integer) ON CONFLICT DO NOTHING; part:=part+1;
      END LOOP;
      index:=index+1;
     END LOOP;
    END IF;
    ordinal:=ordinal+1;
   END LOOP;
  END LOOP;
 END LOOP;
 FOR link IN SELECT * FROM ontology.link_selection WHERE release_id=id AND outcome='ACCEPTED' LOOP
  SELECT x.claim_id INTO STRICT cid FROM ontology.release_claim m JOIN ontology.claim x USING(claim_id)
   WHERE m.release_id=id AND m.entity_id=link.entity_id AND x.kind='DUTY' AND x.ordinal=(link.candidate->>'duty_index')::integer;
  SELECT m.revision_id INTO STRICT target FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id)
   WHERE m.release_id=id AND v.kind='ncsCompetency' AND v.payload->>'code'=link.candidate->>'competency_code'
   AND nullif(btrim(v.payload->>'definition'),'') IS NOT NULL;
  mid:=ontology.hash(jsonb_build_array(cid,target,link.candidate->>'reason',link.candidate->>'origin'));
  INSERT INTO ontology.mapping_claim VALUES(mid,cid,target,'ALIGNS_WITH',
   CASE link.candidate->>'origin' WHEN 'model' THEN 'MODEL_INFERRED' ELSE 'REVIEWER_INFERRED' END,
   link.candidate->>'reason',ontology.hash(jsonb_build_array(cid,target,link.candidate->>'reason',link.candidate->>'origin'))) ON CONFLICT DO NOTHING;
  INSERT INTO ontology.release_mapping VALUES(id,mid,link.candidate_id) ON CONFLICT DO NOTHING;
 END LOOP;
 PERFORM ontology.assemble_rules(id);
END $$;

CREATE OR REPLACE FUNCTION ontology.verify_claims(id text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE p ontology.posting_selection%ROWTYPE; c record; n record; expected jsonb; actual jsonb;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM ontology.review_freeze WHERE release_id=id) THEN RAISE EXCEPTION 'FREEZE_REVIEWS_FIRST'; END IF;
 IF (SELECT count(*) FROM ontology.posting_selection WHERE release_id=id)<>
  (SELECT count(*) FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id=id AND v.kind='jobPosting')
 THEN RAISE EXCEPTION 'ONTOLOGY_POSTING_COVERAGE_MISMATCH'; END IF;
 FOR p IN SELECT * FROM ontology.posting_selection WHERE release_id=id LOOP
  IF p.outcome<>'ACCEPTED' THEN
   IF EXISTS(SELECT 1 FROM ontology.release_claim WHERE release_id=id AND entity_id=p.entity_id) OR
    EXISTS(SELECT 1 FROM ontology.release_position WHERE release_id=id AND entity_id=p.entity_id)
   THEN RAISE EXCEPTION 'UNACCEPTED_EXTRACTION_PROJECTED'; END IF;
   CONTINUE;
  END IF;
  IF p.provenance->'review'->>'decision'<>'ACCEPT' OR p.provenance->>'extraction_hash'<>ontology.hash(p.extraction)
   OR p.source_hash<>enrichment.hash(p.source_data::text)
  THEN RAISE EXCEPTION 'ONTOLOGY_REVIEW_PROVENANCE_MISMATCH'; END IF;
  IF (SELECT count(*) FROM ontology.release_position WHERE release_id=id AND entity_id=p.entity_id)<>jsonb_array_length(p.extraction->'positions') OR
   (SELECT count(*) FROM ontology.release_claim WHERE release_id=id AND entity_id=p.entity_id)<>
    jsonb_array_length(p.extraction->'duties')+jsonb_array_length(p.extraction->'requirements')
  THEN RAISE EXCEPTION 'ONTOLOGY_CLAIM_COVERAGE_MISMATCH'; END IF;
  FOR c IN SELECT x.* FROM ontology.release_position m JOIN ontology.position_claim x USING(position_id)
   WHERE m.release_id=id AND m.entity_id=p.entity_id LOOP
   SELECT x INTO STRICT expected FROM jsonb_array_elements(p.extraction->'positions') x WHERE x->>'id'=c.local_id;
   IF c.posting_revision_id<>p.posting_revision_id OR c.name<>expected->>'name' OR
    c.content_hash<>ontology.hash(expected) OR c.position_id<>ontology.hash(jsonb_build_array(p.posting_revision_id,'position',expected)) OR
    NOT EXISTS(SELECT 1 FROM ontology.position_evidence pe JOIN ontology.evidence_span e USING(evidence_id)
     JOIN ontology.text_artifact a USING(artifact_id) WHERE pe.position_id=c.position_id AND a.posting_id=p.entity_id
      AND a.source_field=expected->'evidence'->>'field'
      AND enrichment.fold_space_v2(e.excerpt)=enrichment.fold_space_v2(ontology.normalize_text(c.name)))
   THEN RAISE EXCEPTION 'ONTOLOGY_POSITION_MISMATCH'; END IF;
  END LOOP;
  FOR c IN SELECT x.* FROM ontology.release_claim m JOIN ontology.claim x USING(claim_id)
   WHERE m.release_id=id AND m.entity_id=p.entity_id LOOP
   expected:=p.extraction->(CASE c.kind WHEN 'DUTY' THEN 'duties' ELSE 'requirements' END)->c.ordinal;
   IF expected IS NULL OR c.payload<>expected OR c.posting_revision_id<>p.posting_revision_id OR
    c.content_hash<>ontology.hash(expected) OR c.text IS DISTINCT FROM expected->>'text' OR
    c.category IS DISTINCT FROM expected->>'category' OR c.condition_kind IS DISTINCT FROM expected->>'kind' OR
    c.logic IS DISTINCT FROM expected->>'logic' OR
    c.claim_id<>ontology.hash(jsonb_build_array(p.posting_revision_id,CASE c.kind WHEN 'DUTY' THEN 'duties' ELSE 'requirements' END,c.ordinal,expected))
   THEN RAISE EXCEPTION 'ONTOLOGY_CLAIM_CONTENT_MISMATCH'; END IF;
   SELECT coalesce(jsonb_agg(x.local_id ORDER BY x.local_id),'[]') INTO actual
   FROM ontology.claim_position cp JOIN ontology.position_claim x USING(position_id) JOIN ontology.release_position m USING(position_id)
   WHERE cp.claim_id=c.claim_id AND m.release_id=id AND m.entity_id=p.entity_id;
   IF actual<>(SELECT coalesce(jsonb_agg(x ORDER BY x),'[]') FROM jsonb_array_elements_text(expected->'position_ids') x)
   THEN RAISE EXCEPTION 'ONTOLOGY_POSITION_SCOPE_MISMATCH'; END IF;
   IF (SELECT count(*) FROM ontology.claim_evidence WHERE claim_id=c.claim_id)<>jsonb_array_length(expected->'text_parts') OR
    EXISTS(SELECT 1 FROM ontology.claim_evidence ce JOIN ontology.evidence_span e USING(evidence_id) JOIN ontology.text_artifact a USING(artifact_id)
     WHERE ce.claim_id=c.claim_id AND (a.posting_id<>p.entity_id OR a.source_field<>expected->'evidence'->>'field' OR
      enrichment.fold_space_v2(e.excerpt) IS DISTINCT FROM enrichment.fold_space_v2(ontology.normalize_text(expected->'text_parts'->>ce.part_index))))
   THEN RAISE EXCEPTION 'ONTOLOGY_CLAIM_EVIDENCE_MISMATCH'; END IF;
   IF (SELECT count(*) FROM ontology.condition_node WHERE claim_id=c.claim_id)<>jsonb_array_length(coalesce(expected->'expression','[]'))
   THEN RAISE EXCEPTION 'ONTOLOGY_EXPRESSION_COVERAGE_MISMATCH'; END IF;
   FOR n IN SELECT * FROM ontology.condition_node WHERE claim_id=c.claim_id LOOP
    IF n.operator IS DISTINCT FROM expected->'expression'->n.node_index->>'op' OR
     n.text IS DISTINCT FROM expected->'expression'->n.node_index->>'text' OR n.parts IS DISTINCT FROM expected->'expression'->n.node_index->'parts'
    THEN RAISE EXCEPTION 'ONTOLOGY_EXPRESSION_CONTENT_MISMATCH'; END IF;
    SELECT coalesce(jsonb_agg(child_index ORDER BY ordinal),'[]') INTO actual FROM ontology.condition_child WHERE claim_id=c.claim_id AND parent_index=n.node_index;
    IF actual IS DISTINCT FROM expected->'expression'->n.node_index->'children'
    THEN RAISE EXCEPTION 'ONTOLOGY_EXPRESSION_ORDER_MISMATCH'; END IF;
    IF (SELECT count(*) FROM ontology.condition_evidence WHERE claim_id=c.claim_id AND node_index=n.node_index)<>jsonb_array_length(n.parts) OR
     EXISTS(SELECT 1 FROM ontology.condition_evidence ce JOIN ontology.evidence_span e USING(evidence_id) JOIN ontology.text_artifact a USING(artifact_id)
      WHERE ce.claim_id=c.claim_id AND ce.node_index=n.node_index AND (a.posting_id<>p.entity_id OR a.source_field<>expected->'evidence'->>'field' OR
       enrichment.fold_space_v2(e.excerpt) IS DISTINCT FROM enrichment.fold_space_v2(ontology.normalize_text(n.parts->>ce.part_index))))
    THEN RAISE EXCEPTION 'ONTOLOGY_EXPRESSION_EVIDENCE_MISMATCH'; END IF;
   END LOOP;
  END LOOP;
 END LOOP;
 IF EXISTS(SELECT 1 FROM ontology.artifact_source s JOIN ontology.text_artifact a USING(artifact_id)
  JOIN ontology.input_record i ON i.release_id=s.release_id AND i.record_id=s.record_id
  WHERE s.release_id=id AND (a.source_field<>s.source_field OR a.input_sha256<>enrichment.hash(i.normalized->>s.source_field)
   OR a.normalized_text<>ontology.normalize_text(i.normalized->>s.source_field) OR a.text_sha256<>enrichment.hash(a.normalized_text)))
 THEN RAISE EXCEPTION 'ONTOLOGY_TEXT_ARTIFACT_MISMATCH'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.evidence_span e JOIN ontology.text_artifact a USING(artifact_id)
  WHERE (EXISTS(SELECT 1 FROM ontology.artifact_source s WHERE s.release_id=id AND s.artifact_id=a.artifact_id)
    OR EXISTS(SELECT 1 FROM ontology.artifact_document d WHERE d.release_id=id AND d.artifact_id=a.artifact_id))
   AND (e.excerpt<>substring(a.normalized_text FROM e.start_offset+1 FOR e.end_offset-e.start_offset)
    OR e.excerpt_sha256<>enrichment.hash(e.excerpt) OR e.end_offset>length(a.normalized_text)))
 THEN RAISE EXCEPTION 'ONTOLOGY_EVIDENCE_OFFSET_MISMATCH'; END IF;
 IF (SELECT count(*) FROM ontology.release_mapping WHERE release_id=id)<>
  (SELECT count(*) FROM ontology.link_selection WHERE release_id=id AND outcome='ACCEPTED') OR
  EXISTS(SELECT 1 FROM ontology.release_mapping m JOIN ontology.mapping_claim mc USING(mapping_id)
   JOIN ontology.link_selection s ON s.release_id=m.release_id AND s.candidate_id=m.candidate_id
   JOIN ontology.claim d ON d.claim_id=mc.duty_claim_id JOIN ontology.revision v ON v.revision_id=mc.target_revision_id
   WHERE m.release_id=id AND (s.outcome<>'ACCEPTED' OR d.kind<>'DUTY' OR d.ordinal<>(s.candidate->>'duty_index')::integer OR
    v.kind<>'ncsCompetency' OR v.payload->>'code'<>s.candidate->>'competency_code' OR
    mc.reason<>s.candidate->>'reason' OR mc.content_hash<>mc.mapping_id OR
    mc.mapping_id<>ontology.hash(jsonb_build_array(d.claim_id,v.revision_id,s.candidate->>'reason',s.candidate->>'origin')) OR
    NOT EXISTS(SELECT 1 FROM ontology.release_revision x WHERE x.release_id=id AND x.revision_id=v.revision_id) OR
    NOT EXISTS(SELECT 1 FROM ontology.release_claim x WHERE x.release_id=id AND x.entity_id=s.entity_id AND x.claim_id=d.claim_id)))
 THEN RAISE EXCEPTION 'ONTOLOGY_MAPPING_MISMATCH'; END IF;
 PERFORM ontology.verify_document_evidence(id);
 PERFORM ontology.verify_rules(id);
END $$;

CREATE OR REPLACE VIEW ontology.posting_coverage AS
SELECT p.release_id,p.entity_id,p.outcome,p.extraction->>'duties_status' AS duties_status,
 (SELECT count(*) FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id)
  WHERE m.release_id=p.release_id AND m.entity_id=p.entity_id AND c.kind='DUTY') AS duties,
 (SELECT count(*) FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id)
  WHERE m.release_id=p.release_id AND m.entity_id=p.entity_id AND c.kind='REQUIREMENT') AS requirements,
 (SELECT count(*) FROM ontology.link_selection l WHERE l.release_id=p.release_id AND l.entity_id=p.entity_id AND l.outcome='ACCEPTED') AS accepted_links,
 (SELECT count(*) FROM ontology.link_selection l WHERE l.release_id=p.release_id AND l.entity_id=p.entity_id AND l.outcome<>'ACCEPTED') AS excluded_or_pending_links
FROM ontology.posting_selection p;
COMMENT ON TABLE ontology.claim IS 'Reviewed source language and condition trees. SOURCE_TEXT/SOURCE_EXPRESSION do not imply resolved eligibility codes, proficiency, degree or month thresholds.';
COMMIT;
