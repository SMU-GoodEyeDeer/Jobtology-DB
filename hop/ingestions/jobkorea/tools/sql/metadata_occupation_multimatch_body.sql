-- Candidate review is append-only and scoped to one frozen inference candidate.
CREATE TABLE IF NOT EXISTS enrichment.metadata_occupation_candidate_decision (
 decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 candidate_id text NOT NULL REFERENCES enrichment.metadata_occupation_candidate,
 decision text NOT NULL CHECK(decision IN('ACCEPT','REJECT')),
 reviewer text NOT NULL CHECK(length(btrim(reviewer))>0),
 reviewer_kind text NOT NULL CHECK(reviewer_kind IN('human','assistant')),
 notes text NOT NULL CHECK(length(btrim(notes))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS metadata_occupation_candidate_decision_latest
 ON enrichment.metadata_occupation_candidate_decision(candidate_id,decision_id DESC);
-- Canonical fresh installation may precede retention. Replay 037 after the
-- retention installer, as the inferred workflow requires before execution.
DO $$ BEGIN
 IF to_regprocedure('retention.freeze_writes()') IS NOT NULL THEN
  CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON enrichment.metadata_occupation_candidate_decision
   FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();
 END IF;
END $$;
DROP TRIGGER IF EXISTS immutable_metadata_occupation_candidate_decision ON enrichment.metadata_occupation_candidate_decision;
CREATE TRIGGER immutable_metadata_occupation_candidate_decision BEFORE UPDATE OR DELETE ON enrichment.metadata_occupation_candidate_decision
 FOR EACH ROW EXECUTE FUNCTION enrichment.reject_metadata_occupation_change();
DROP TRIGGER IF EXISTS immutable_truncate_metadata_occupation_candidate_decision ON enrichment.metadata_occupation_candidate_decision;
CREATE TRIGGER immutable_truncate_metadata_occupation_candidate_decision BEFORE TRUNCATE ON enrichment.metadata_occupation_candidate_decision
 FOR EACH STATEMENT EXECUTE FUNCTION enrichment.reject_metadata_occupation_change();

CREATE OR REPLACE FUNCTION enrichment.guard_metadata_occupation_candidate_decision()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=TG_RELID AND tgname='retention_freeze'
  AND tgenabled='O' AND tgfoid=to_regprocedure('retention.freeze_writes()'))
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REINSTALL_FOR_RETENTION_GUARD_REQUIRED'; END IF;
 SELECT result.actor,result.item_id,b.settings->>'prompt_version' AS prompt_version,x.job_run_id,x.ncs_run_id INTO STRICT r
 FROM enrichment.metadata_occupation_candidate c JOIN enrichment.metadata_occupation_result result USING(result_id)
 JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
 JOIN enrichment.metadata_occupation_binding x ON x.item_id=i.item_id WHERE c.candidate_id=NEW.candidate_id;
 IF r.prompt_version<>'ko-metadata-occupation-v3' THEN RAISE EXCEPTION 'METADATA_OCCUPATION_LEGACY_RESULT_REVIEW_REQUIRED'; END IF;
 IF NEW.reviewer=r.actor THEN RAISE EXCEPTION 'METADATA_OCCUPATION_INDEPENDENT_REVIEW_REQUIRED'; END IF;
 PERFORM enrichment.verify_item_input(r.item_id);
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=r.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=r.ncs_run_id)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REVIEW_SNAPSHOT_STALE'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER metadata_candidate_review_guard BEFORE INSERT ON enrichment.metadata_occupation_candidate_decision
 FOR EACH ROW EXECUTE FUNCTION enrichment.guard_metadata_occupation_candidate_decision();

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_output_issues_v3(
 output jsonb,source jsonb,candidates jsonb,max_matches integer DEFAULT 3)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE issues jsonb:='[]'; base jsonb; m jsonb; anchor jsonb; fields jsonb:=enrichment.metadata_occupation_fields(source);
 ordinal integer:=0; previous_field text; previous_end integer:=0; start_at integer; n integer;
BEGIN
 IF jsonb_typeof(output->'matches') IS DISTINCT FROM 'array'
 THEN RETURN '["METADATA_OCCUPATION_OUTPUT_SHAPE"]'::jsonb; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(output->'matches') x WHERE jsonb_typeof(x) IS DISTINCT FROM 'object')
 THEN RETURN '["METADATA_OCCUPATION_MATCH_SHAPE"]'::jsonb; END IF;
 n:=jsonb_array_length(output->'matches');
 IF max_matches IS NULL OR max_matches NOT BETWEEN 1 AND 3 OR n>max_matches
 THEN issues:=issues||'["METADATA_OCCUPATION_MATCH_CAP"]'::jsonb; END IF;
 -- Delegate literal source quotations, duplicates and outcome/shape checks to
 -- the frozen legacy validator, stripping only the two new match properties.
 SELECT jsonb_set(output,'{matches}',coalesce(jsonb_agg(value-ARRAY['match_rank','role_anchor'] ORDER BY pos),'[]'))
 INTO base FROM jsonb_array_elements(output->'matches') WITH ORDINALITY x(value,pos);
 issues:=issues||(enrichment.metadata_occupation_output_issues(base,source,candidates,2)-'METADATA_OCCUPATION_MATCH_CAP');
 IF n=0 THEN RETURN issues; END IF;
 -- Role alternatives are conservative lexical guards. Tool choices such as
 -- Java or Kotlin cannot disqualify an otherwise explicit single role.
 IF EXISTS(SELECT 1 FROM jsonb_each_text(fields) WHERE key IN('title','role') AND
  lower(value) ~ '(developer|engineer|analyst|administrator|backend|frontend|dba|개발자|분석가|관리자).{0,15}([[:space:]]or[[:space:]]|또는|혹은).{0,30}(developer|engineer|analyst|administrator|backend|frontend|dba|개발자|분석가|관리자)|채용하지|not[[:space:]]+hiring([^a-z]|$)')
 THEN issues:=issues||'["METADATA_OCCUPATION_ALTERNATIVE_OR_CONTRADICTORY_ROLES"]'::jsonb; END IF;
 FOR m IN SELECT value FROM jsonb_array_elements(output->'matches') LOOP
  ordinal:=ordinal+1; anchor:=m->'role_anchor';
  IF jsonb_typeof(m) IS DISTINCT FROM 'object' OR
   NOT m ?& ARRAY['occupation_code','reason','evidence','match_rank','role_anchor'] OR
   m-ARRAY['occupation_code','reason','evidence','match_rank','role_anchor']<>'{}'::jsonb OR
   jsonb_typeof(m->'match_rank') IS DISTINCT FROM 'number' OR m->>'match_rank' IS DISTINCT FROM ordinal::text
  THEN issues:=issues||'["METADATA_OCCUPATION_MATCH_RANK"]'::jsonb; END IF;
  IF jsonb_typeof(anchor) IS DISTINCT FROM 'object' OR
   NOT anchor ?& ARRAY['field','quote'] OR anchor-ARRAY['field','quote']<>'{}'::jsonb OR
   jsonb_typeof(anchor->'field') IS DISTINCT FROM 'string' OR
   anchor->>'field' NOT IN('title','role') OR
   jsonb_typeof(anchor->'quote') IS DISTINCT FROM 'string' OR length(btrim(anchor->>'quote'))<2 OR
   NOT fields ? (anchor->>'field') OR
   coalesce(position(anchor->>'quote' in fields->>(anchor->>'field')),0)=0
  THEN issues:=issues||'["METADATA_OCCUPATION_ROLE_ANCHOR_REQUIRED"]'::jsonb; CONTINUE; END IF;
  IF jsonb_typeof(m->'evidence') IS DISTINCT FROM 'array' OR NOT (m->'evidence') @> jsonb_build_array(anchor)
  THEN issues:=issues||'["METADATA_OCCUPATION_INDEPENDENT_ROLE_EVIDENCE"]'::jsonb; END IF;
  start_at:=position(anchor->>'quote' in fields->>(anchor->>'field'));
  IF ordinal>1 AND (anchor->>'field' IS DISTINCT FROM previous_field OR start_at<=previous_end)
  THEN issues:=issues||'["METADATA_OCCUPATION_DISTINCT_ORDERED_ROLE_ANCHORS"]'::jsonb; END IF;
  IF ordinal>1 AND anchor->>'field'=previous_field AND start_at>previous_end AND
   lower(substring(fields->>previous_field FROM previous_end+1 FOR start_at-previous_end-1)) ~ '(^|[^a-z])or([^a-z]|$)|또는|혹은'
  THEN issues:=issues||'["METADATA_OCCUPATION_ALTERNATIVE_OR_CONTRADICTORY_ROLES"]'::jsonb; END IF;
  previous_field:=anchor->>'field'; previous_end:=start_at+length(anchor->>'quote')-1;
  IF lower(m->>'reason') ~ '(ambiguous|unclear|insufficient|cannot.{0,8}identify|모호|불명확|근거.{0,8}부족|판단.{0,8}어렵)'
  THEN issues:=issues||'["METADATA_OCCUPATION_AMBIGUOUS_MATCH"]'::jsonb; END IF;
 END LOOP;
 RETURN issues;
END $$;

CREATE OR REPLACE FUNCTION enrichment.decide_metadata_occupation_candidate(
 candidate text,decision text,reviewer text,kind text,notes text)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE c enrichment.metadata_occupation_candidate%ROWTYPE; r enrichment.metadata_occupation_result%ROWTYPE;
 binding enrichment.metadata_occupation_binding%ROWTYPE; old enrichment.metadata_occupation_candidate_decision%ROWTYPE; id bigint;
BEGIN
 PERFORM retention.gate();
 SELECT * INTO STRICT c FROM enrichment.metadata_occupation_candidate WHERE candidate_id=candidate FOR UPDATE;
 SELECT * INTO STRICT r FROM enrichment.metadata_occupation_result WHERE result_id=c.result_id;
 SELECT * INTO STRICT binding FROM enrichment.metadata_occupation_binding WHERE item_id=r.item_id;
 PERFORM enrichment.verify_item_input(r.item_id);
 IF NOT EXISTS(SELECT 1 FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
  WHERE i.item_id=r.item_id AND b.settings->>'prompt_version'='ko-metadata-occupation-v3')
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_LEGACY_RESULT_REVIEW_REQUIRED'; END IF;
 IF decision IS NULL OR decision NOT IN('ACCEPT','REJECT') OR kind IS NULL OR kind NOT IN('human','assistant')
  OR nullif(btrim(reviewer),'') IS NULL OR nullif(btrim(notes),'') IS NULL
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REVIEW_PROVENANCE_REQUIRED'; END IF;
 IF reviewer=r.actor THEN RAISE EXCEPTION 'METADATA_OCCUPATION_INDEPENDENT_REVIEW_REQUIRED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=binding.job_run_id)
  OR NOT EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=binding.ncs_run_id)
 THEN RAISE EXCEPTION 'METADATA_OCCUPATION_REVIEW_SNAPSHOT_STALE'; END IF;
 SELECT * INTO old FROM enrichment.metadata_occupation_candidate_decision WHERE candidate_id=candidate ORDER BY decision_id DESC LIMIT 1;
 IF FOUND AND old.decision=decision AND old.reviewer=reviewer AND old.reviewer_kind=kind AND old.notes=notes
 THEN RETURN old.decision_id; END IF;
 INSERT INTO enrichment.metadata_occupation_candidate_decision(candidate_id,decision,reviewer,reviewer_kind,notes)
 VALUES(candidate,decision,reviewer,kind,notes) RETURNING decision_id INTO id;
 RETURN id;
END $$;

-- Latest captured result wins only after complete validation. An unsent or
-- failed successor cannot hide a previously validated occupation projection.
CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_publication_results(jobs text,ncs text)
RETURNS TABLE(posting_id text,item_id text,result_id text) LANGUAGE sql STABLE AS $$
 SELECT DISTINCT ON(i.posting_id) i.posting_id,i.item_id,r.result_id
 FROM enrichment.metadata_occupation_binding x JOIN enrichment.item i USING(item_id)
 JOIN enrichment.batch b USING(batch_id) JOIN enrichment.metadata_occupation_result r USING(item_id)
 WHERE x.job_run_id=jobs AND x.ncs_run_id=ncs
 ORDER BY i.posting_id,b.created_at DESC,i.item_id DESC
$$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_candidate_status(result text)
RETURNS TABLE(candidate_id text,match_rank integer,decision text,decision_id bigint,reviewer text,reviewer_kind text,notes text)
LANGUAGE sql STABLE AS $$
 SELECT c.candidate_id,(m.value->>'match_rank')::integer,d.decision,d.decision_id,d.reviewer,d.reviewer_kind,d.notes
 FROM enrichment.metadata_occupation_candidate c JOIN enrichment.metadata_occupation_result r USING(result_id)
 JOIN enrichment.item i USING(item_id) JOIN enrichment.batch b USING(batch_id)
 CROSS JOIN LATERAL jsonb_array_elements(r.output->'matches') m(value)
 LEFT JOIN LATERAL (SELECT d.* FROM enrichment.metadata_occupation_candidate_decision d
  WHERE d.candidate_id=c.candidate_id ORDER BY d.decision_id DESC LIMIT 1) d ON true
 WHERE c.result_id=result AND b.settings->>'prompt_version'='ko-metadata-occupation-v3'
  AND m.value->>'occupation_code'=c.occupation_code
$$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_graph_rows_v3(jobs text,ncs text,include_unreviewed boolean DEFAULT false)
RETURNS TABLE(posting_id text,posting_identity text,occupation_identity text,candidate_id text,payload jsonb)
LANGUAGE sql STABLE AS $$
 WITH selected AS (
 SELECT s.posting_id,i.item_id,i.batch_id,r.result_id,r.attempt_id,r.actor,c.candidate_id,c.occupation_code,c.reason,c.evidence,
  binding.bundle_id,binding.source_hash,binding.binding_hash,cat.occupation_name,cat.catalog_hash,
  b.settings,a.actual_model,ib.manifest,d.match_rank,d.decision,d.decision_id,d.reviewer,d.reviewer_kind,d.notes,m.value AS match
 FROM enrichment.metadata_occupation_publication_results(jobs,ncs) s
 JOIN enrichment.metadata_occupation_result r ON r.result_id=s.result_id
 JOIN enrichment.metadata_occupation_binding binding ON binding.item_id=s.item_id
 JOIN enrichment.item i ON i.item_id=binding.item_id JOIN enrichment.batch b ON b.batch_id=i.batch_id
 JOIN enrichment.attempt a ON a.attempt_id=r.attempt_id JOIN enrichment.input_bundle ib ON ib.bundle_id=binding.bundle_id
 JOIN enrichment.metadata_occupation_candidate c ON c.result_id=r.result_id
 JOIN enrichment.metadata_occupation_catalog cat ON cat.ncs_run_id=c.ncs_run_id AND cat.occupation_code=c.occupation_code
 JOIN enrichment.metadata_occupation_candidate_status(r.result_id) d ON d.candidate_id=c.candidate_id
 CROSS JOIN LATERAL jsonb_array_elements(r.output->'matches') m(value)
 WHERE b.settings->>'prompt_version'='ko-metadata-occupation-v3' AND r.output->>'outcome'='matched'
  AND m.value->>'occupation_code'=c.occupation_code AND d.decision IS DISTINCT FROM 'REJECT'
  AND (d.decision='ACCEPT' OR include_unreviewed)
  AND EXISTS(SELECT 1 FROM ingestion.run WHERE source_id='jobkorea' AND run_id=jobs AND state='READY')
  AND EXISTS(SELECT 1 FROM ingestion.run WHERE source_id='ncs_competency' AND run_id=ncs AND state='READY')
 ) SELECT s.posting_id,'source:posting:jobkorea:'||enrichment.hash(s.manifest#>>'{document,source_record_id}'),
 'ncs:occupation:'||s.occupation_code,s.candidate_id,
 jsonb_build_object('result_id',s.result_id,'candidate_id',s.candidate_id,'occupation_code',s.occupation_code,
  'occupation_name',s.occupation_name,'occupation_scheme','NCS','occupation_scheme_run_id',ncs,
  'job_run_id',jobs,'ncs_run_id',ncs,'bundle_id',s.bundle_id,'source_hash',s.source_hash,'binding_hash',s.binding_hash,
  'catalog_hash',s.catalog_hash,'basis','METADATA_INFERRED','assertion_kind','MODEL_INFERRED',
  'item_id',s.item_id,'batch_id',s.batch_id,'attempt_id',s.attempt_id,'model',coalesce(s.actual_model,s.settings->>'categorize_model'),
  'prompt_version',s.settings->>'prompt_version','actor',s.actor,'confidence',NULL,'confidence_state','UNASSESSED',
  'reason',s.reason,'evidence',s.evidence,'role_anchor',s.match->'role_anchor','match_rank',s.match_rank,
  'rank_basis','SOURCE_ANCHOR_DISPLAY_ORDER_V1','original_primary',s.match_rank=1,
  'current_primary',s.match_rank=min(s.match_rank) OVER(PARTITION BY s.result_id),
  'validation_status','VALIDATED','stage','STAGING','accepted',coalesce(s.decision='ACCEPT',false),
  'review_status',CASE WHEN s.decision='ACCEPT' AND s.reviewer_kind='human' THEN 'HUMAN_REVIEWED'
   WHEN s.decision='ACCEPT' THEN 'ASSISTANT_REVIEWED' ELSE 'UNREVIEWED' END,
  'decision_id',s.decision_id,'reviewer',s.reviewer,'reviewer_kind',s.reviewer_kind,'review_notes',s.notes)
 FROM selected s
$$;

CREATE OR REPLACE FUNCTION enrichment.metadata_occupation_candidate_review_packet(batch text)
RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('contract','metadata-occupation-candidate-review-v3','batch_id',batch,
  'rows',coalesce(jsonb_agg(jsonb_build_object('candidate_id',c.candidate_id,'result_id',r.result_id,
   'match_rank',s.match_rank,'occupation_scheme','NCS','occupation_code',c.occupation_code,
   'reason',c.reason,'evidence',c.evidence,'actor',r.actor,'posting_id',i.posting_id,
   'source_fields',enrichment.metadata_occupation_fields(i.source_data),'bundle_id',x.bundle_id,
   'job_run_id',x.job_run_id,'ncs_run_id',x.ncs_run_id,'binding_hash',x.binding_hash,
   'candidates',x.candidates,'review_decision',s.decision,'decision_id',s.decision_id)
   ORDER BY i.ordinal,s.match_rank),'[]'::jsonb))
 FROM enrichment.item i JOIN enrichment.metadata_occupation_binding x USING(item_id)
 JOIN enrichment.metadata_occupation_result r USING(item_id)
 JOIN enrichment.metadata_occupation_candidate c USING(result_id)
 JOIN enrichment.metadata_occupation_candidate_status(r.result_id) s ON s.candidate_id=c.candidate_id
 WHERE i.batch_id=batch
$$;
