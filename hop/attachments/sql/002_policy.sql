BEGIN;
INSERT INTO attachment.policy SELECT 'job-alio-attachments-v1',v,attachment.hash(v::text) FROM (SELECT '{
  "policy_id": "job-alio-attachments-v1",
  "revision": "2026-09-12.1",
  "source_id": "job_alio",
  "purpose": "Retain official recruitment documents and extract source-grounded ontology facts for review.",
  "catalogue_url": "https://www.data.go.kr/data/15125273/openapi.do",
  "catalogue_scope": "The catalogue''s no-restriction label describes the API dataset. It is not treated as a separate blanket licence for every attached work.",
  "download_roles": ["A", "C"],
  "other_roles": {"B": "APPLICATION_FORM", "other": "ROLE_REVIEW"},
  "formats": ["pdf", "hwp", "hwpx"],
  "metadata_url_prefix": "https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo=",
  "download_url_prefix": "https://www.alio.go.kr/download/download.json?fileNo=",
  "resolver": "Preserve the numeric attachment ID. The official JOB-ALIO posting page links the same ID and filename to the ALIO download endpoint; the OpenData URL currently redirects to its homepage.",
  "resolver_evidence_url": "https://job.alio.go.kr/recruitview.do?idx=304817",
  "resolver_observed_on": "2026-09-12",
  "public_document_redistribution": false,
  "automatic_claim_acceptance": false,
  "automatic_model_calls": false,
  "max_received_bytes": 67108864,
  "max_parsed_characters": 2000000,
  "parser_version": "hop-2.19-tika-3.3.1-xml-v1",
  "provenance": "Preserve source snapshot, posting, original metadata, requested URL, response hash, parser metadata, and page/body/archive-section locators. Parsing success is not semantic approval."
}
'::jsonb v) i ON CONFLICT DO NOTHING;
DO $$ BEGIN IF (SELECT contract FROM attachment.policy WHERE policy_id='job-alio-attachments-v1') IS DISTINCT FROM '{
  "policy_id": "job-alio-attachments-v1",
  "revision": "2026-09-12.1",
  "source_id": "job_alio",
  "purpose": "Retain official recruitment documents and extract source-grounded ontology facts for review.",
  "catalogue_url": "https://www.data.go.kr/data/15125273/openapi.do",
  "catalogue_scope": "The catalogue''s no-restriction label describes the API dataset. It is not treated as a separate blanket licence for every attached work.",
  "download_roles": ["A", "C"],
  "other_roles": {"B": "APPLICATION_FORM", "other": "ROLE_REVIEW"},
  "formats": ["pdf", "hwp", "hwpx"],
  "metadata_url_prefix": "https://opendata.alio.go.kr/recruit/downloadAtchFile?recrutAtchFileNo=",
  "download_url_prefix": "https://www.alio.go.kr/download/download.json?fileNo=",
  "resolver": "Preserve the numeric attachment ID. The official JOB-ALIO posting page links the same ID and filename to the ALIO download endpoint; the OpenData URL currently redirects to its homepage.",
  "resolver_evidence_url": "https://job.alio.go.kr/recruitview.do?idx=304817",
  "resolver_observed_on": "2026-09-12",
  "public_document_redistribution": false,
  "automatic_claim_acceptance": false,
  "automatic_model_calls": false,
  "max_received_bytes": 67108864,
  "max_parsed_characters": 2000000,
  "parser_version": "hop-2.19-tika-3.3.1-xml-v1",
  "provenance": "Preserve source snapshot, posting, original metadata, requested URL, response hash, parser metadata, and page/body/archive-section locators. Parsing success is not semantic approval."
}
'::jsonb THEN RAISE EXCEPTION 'ATTACHMENT_POLICY_IS_IMMUTABLE'; END IF; END $$;
COMMIT;
