BEGIN;
SELECT retention.gate();
INSERT INTO attachment.policy SELECT 'job-alio-documents-v3-ac-only',v,attachment.hash(v::text) FROM (SELECT '{"policy_id": "job-alio-documents-v3-ac-only", "revision": "2026-09-15.1", "source_id": "job_alio", "purpose": "Retain official recruitment documents and extract source-grounded ontology facts for review.", "catalogue_url": "https://www.data.go.kr/data/15125273/openapi.do", "catalogue_scope": "The catalogue''s no-restriction label describes the API dataset. It is not treated as a separate blanket licence for every attached work.", "download_roles": ["A", "C"], "other_roles": {"B": "APPLICATION_FORM", "other": "ROLE_REVIEW", "named_notice_or_jd": "Excluded in A_C_ONLY; retain non-A/C metadata for manual source review."}, "formats": ["pdf", "hwp", "hwpx", "doc", "docx", "zip"], "metadata_url_prefix": "https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo=", "download_url_prefix": "https://www.alio.go.kr/download/download.json?fileNo=", "resolver": "Preserve the numeric attachment ID. The official JOB-ALIO posting page links the same ID and filename to the ALIO download endpoint; the OpenData URL currently redirects to its homepage.", "resolver_evidence_url": "https://job.alio.go.kr/recruitview.do?idx=304817", "resolver_observed_on": "2026-09-12", "public_document_redistribution": false, "automatic_claim_acceptance": false, "automatic_model_calls": false, "max_received_bytes": 67108864, "max_parsed_characters": 2000000, "parser_version": "document-processor-v1", "provenance": "Preserve source snapshot, posting, original metadata, requested URL, response hash, parser metadata, and page/body/archive-section locators. Parsing success is not semantic approval."}'::jsonb v) q ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION attachment.prepare_downloads_ac_only(id text,run text,ids_text text,base text,cap integer) RETURNS text LANGUAGE plpgsql AS $$
DECLARE ids text[]; b attachment.batch; r record; f record; ext text; disposition text; file_id text; doc text; BEGIN
 PERFORM retention.gate();
 IF id IS NULL OR id='' THEN id:=gen_random_uuid()::text; END IF;
 IF id !~ '^[A-Za-z0-9_-]{1,100}$' THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_BATCH_ID'; END IF;
 IF base IS NULL OR base !~ '^/' OR base ~ '(^|/)[.][.]?(/|$)|//|[\\]' OR base ~ '[[:cntrl:]]' OR right(base,1)='/' THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_ROOT'; END IF;
 IF cap IS NULL OR cap NOT BETWEEN 1 AND 10000 THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_CAP'; END IF;
 SELECT coalesce(array_agg(DISTINCT v ORDER BY v),'{}') INTO ids FROM unnest(string_to_array(coalesce(ids_text,''),'|')) v WHERE v<>'';
 IF EXISTS(SELECT 1 FROM unnest(ids) v WHERE v !~ '^[0-9]+$') THEN RAISE EXCEPTION 'INVALID_POSTING_IDS'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ingestion.run WHERE run_id=prepare_downloads_ac_only.run AND source_id='job_alio' AND state='READY' AND mode<>'SMOKE') THEN RAISE EXCEPTION 'READY_JOB_SNAPSHOT_REQUIRED'; END IF;
 SELECT * INTO b FROM attachment.batch WHERE batch_id=id;
 IF FOUND THEN
  IF (b.job_run_id,b.posting_ids,b.raw_root,b.max_files) IS DISTINCT FROM (run,ids,base,cap) THEN RAISE EXCEPTION 'ATTACHMENT_SELECTION_IS_IMMUTABLE'; END IF;
  IF b.policy_id<>'job-alio-documents-v3-ac-only' THEN RAISE EXCEPTION 'ATTACHMENT_SELECTION_IS_IMMUTABLE'; END IF;
  PERFORM attachment.check_source(id); RETURN id;
 END IF;
 IF EXISTS(SELECT 1 FROM ingestion.ready_record WHERE run_id=prepare_downloads_ac_only.run AND source_record_id LIKE '%:detail'
  AND (cardinality(ids)=0 OR split_part(source_record_id,':',1)=ANY(ids)) GROUP BY source_record_id HAVING count(*)<>1)
 THEN RAISE EXCEPTION 'AMBIGUOUS_SOURCE_POSTING'; END IF;
 IF cardinality(ids)>0 AND EXISTS(SELECT 1 FROM unnest(ids) v WHERE NOT EXISTS(SELECT 1 FROM ingestion.ready_record
  WHERE run_id=prepare_downloads_ac_only.run AND source_record_id=v||':detail')) THEN RAISE EXCEPTION 'POSTING_NOT_IN_SNAPSHOT'; END IF;
 INSERT INTO attachment.batch VALUES(id,run,ids,attachment.source_hash(run,ids),base,'job-alio-documents-v3-ac-only',cap,clock_timestamp());
 FOR r IN SELECT * FROM ingestion.ready_record WHERE run_id=prepare_downloads_ac_only.run AND source_record_id LIKE '%:detail'
 AND (cardinality(ids)=0 OR split_part(source_record_id,':',1)=ANY(ids)) ORDER BY source_record_id LOOP
  IF jsonb_typeof(r.source_payload->'files') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'ATTACHMENT_METADATA_ARRAY_REQUIRED'; END IF;
  INSERT INTO attachment.posting VALUES(id,split_part(r.source_record_id,':',1),r.document_id,r.locator,attachment.hash(r.source_payload::text),r.source_payload->'files');
  FOR f IN SELECT value,ordinality FROM jsonb_array_elements(r.source_payload->'files') WITH ORDINALITY LOOP
   file_id:=f.value->>'recrutAtchFileNo'; ext:=lower(substring(f.value->>'atchFileNm' FROM '[.]([^.]+)$'));
   disposition:=CASE WHEN f.value->>'atchFileType'='B' THEN 'APPLICATION_FORM'
    WHEN coalesce(f.value->>'atchFileType','') NOT IN ('A','C') THEN 'ROLE_REVIEW'
    WHEN file_id IS NULL OR file_id !~ '^[0-9]+$' OR (f.value->>'url') IS DISTINCT FROM
     ('https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo='||file_id) THEN 'INVALID_URL'
    WHEN ext IS NULL OR ext NOT IN ('pdf','hwp','hwpx','doc','docx','zip') THEN 'UNSUPPORTED_FORMAT' ELSE 'PLANNED' END;
   doc:=attachment.hash(jsonb_build_array(id,r.source_record_id,f.ordinality,f.value)::text);
   INSERT INTO attachment.document VALUES(doc,id,split_part(r.source_record_id,':',1),f.ordinality,f.value,f.value->>'url',
    CASE WHEN disposition='PLANNED' THEN 'https://www.alio.go.kr/download/download.json?fileNo='||file_id END,ext,disposition);
  END LOOP;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM attachment.posting WHERE batch_id=id) THEN RAISE EXCEPTION 'NO_ATTACHMENT_POSTINGS'; END IF;
 IF (SELECT count(*) FROM attachment.document dd WHERE dd.batch_id=id AND dd.disposition='PLANNED')>cap THEN RAISE EXCEPTION 'ATTACHMENT_CAP_EXCEEDED'; END IF;
 RETURN id;
END $$;

CREATE OR REPLACE FUNCTION attachment.prepare_downloads(id text,run text,ids_text text,base text,cap integer,selection text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE existing_policy text; BEGIN
 IF selection NOT IN ('DEFAULT','A_C_ONLY') OR selection IS NULL THEN RAISE EXCEPTION 'INVALID_ATTACHMENT_SELECTION'; END IF;
 IF id IS NOT NULL AND id<>'' THEN
  SELECT policy_id INTO existing_policy FROM attachment.batch WHERE batch_id=id;
  IF existing_policy IS NOT NULL AND existing_policy<>(CASE selection WHEN 'DEFAULT' THEN 'job-alio-documents-v3' ELSE 'job-alio-documents-v3-ac-only' END)
  THEN RAISE EXCEPTION 'ATTACHMENT_SELECTION_IS_IMMUTABLE'; END IF;
 END IF;
 IF selection='DEFAULT' THEN RETURN attachment.prepare_downloads(id,run,ids_text,base,cap); END IF;
 RETURN attachment.prepare_downloads_ac_only(id,run,ids_text,base,cap);
END $$;

COMMIT;
