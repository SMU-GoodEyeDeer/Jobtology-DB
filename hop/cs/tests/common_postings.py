"""Synthetic PostgreSQL contract test; no provider requests or live deployment."""
from pathlib import Path
import json
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
NAME = "jobtology-common-source-" + uuid.uuid4().hex[:10]


def run(argv, input_text=None):
    result = subprocess.run(argv, input=input_text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{argv}: {result.stderr[-4000:]} {result.stdout[-4000:]}")
    return result.stdout.strip()


def sql(statement):
    return run(
        ["docker", "exec", "-i", NAME, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-A", "-t", "-U", "postgres", "-d", "postgres"],
        statement,
    )


SETUP = r"""
CREATE SCHEMA ingestion;
CREATE SCHEMA enrichment;
CREATE TABLE ingestion.run (run_id text PRIMARY KEY,source_id text,state text,mode text);
CREATE TABLE ingestion.job_posting (
 run_id text,posting_id text,list_document_id text,list_locator text,
 detail_document_id text,detail_locator text,normalized jsonb,field_origin jsonb);
CREATE TABLE ingestion.ready_record (run_id text,source_record_id text,source_id text,source_payload jsonb);
CREATE VIEW ingestion.latest_ready_run AS
 SELECT run_id,source_id FROM ingestion.run WHERE state='READY' AND mode<>'SMOKE';
CREATE TABLE enrichment.batch (batch_id text,mode text,created_at timestamptz);
CREATE TABLE enrichment.item (item_id text,batch_id text,posting_id text,source_hash text,extraction_id text);
CREATE TABLE enrichment.attempt (attempt_id text,state text,parsed_output jsonb);
CREATE TABLE enrichment.extraction_review_state
 (revision_id text,item_id text,decision text,extraction jsonb,revision_no integer,reviewer_kind text);
CREATE TABLE enrichment.linking_status
 (posting_id text,source_hash text,ncs_run_id text,ncs_links jsonb,extraction jsonb,outcome text,revision_id text);
CREATE TABLE enrichment.ncs_catalog
 (run_id text,code text,occupation_code text,PRIMARY KEY(run_id,code));
CREATE TABLE enrichment.link_candidate
 (candidate_id text PRIMARY KEY,revision_id text,ncs_run_id text,competency_code text,duty_index integer);
CREATE TABLE enrichment.link_decision
 (decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,candidate_id text,decision text);
CREATE FUNCTION enrichment.hash(v text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to(v,'UTF8')),'hex') $$;
CREATE FUNCTION enrichment.source_fields(n jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_object_agg(key,value),'{}') FROM jsonb_each(n)
 WHERE key IN ('title','organization_name','education','recruitment_type','employment_type',
 'regions','ncs_category_codes','ncs_category_names','eligibility_text','preference_text',
 'selection_text','disqualification_text','duties_text','description_text')
 AND jsonb_typeof(value)='string' AND length(btrim(value#>>'{}'))>0 $$;
-- The sentinel proves the adapter uses the existing attachment-aware hash hook.
CREATE FUNCTION enrichment.linking_input_hash(jobs text,posting text) RETURNS text
 LANGUAGE sql STABLE AS $$ SELECT 'prepared-content-hash-for-'||jobs||'-'||posting $$;
INSERT INTO ingestion.run VALUES ('alio-snapshot','job_alio','READY','FULL');
INSERT INTO ingestion.job_posting VALUES
 ('alio-snapshot','123','list-document','row-1','detail-document','row-1',
  '{"posting_id":"123","title":"데이터 엔지니어","organization_name":"기관 A","duties_text":"DB 구축","ignored_field":"do not hash"}',
  '{"title":"list","duties_text":"detail"}');
INSERT INTO ingestion.ready_record VALUES
 ('alio-snapshot','123:detail','job_alio','{"files":[{"name":"notice.hwp"}]}');
INSERT INTO enrichment.batch VALUES ('legacy-batch','ENRICH',clock_timestamp());
INSERT INTO enrichment.item VALUES
 ('legacy-item','legacy-batch','123','prepared-content-hash-for-alio-snapshot-123',NULL);
INSERT INTO enrichment.extraction_review_state VALUES
 ('legacy-revision','legacy-item','ACCEPT','{}',1,'assistant');
"""


def main():
    try:
        run(["docker", "run", "-d", "--name", NAME, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17-alpine"])
        for _ in range(50):
            try:
                logs = run(["docker", "logs", NAME])
                if "PostgreSQL init process complete" in logs and sql("SELECT 1") == "1":
                    break
            except RuntimeError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("PostgreSQL fixture did not become ready")
        sql(SETUP)
        module = (ROOT / "hop/cs/sql/001_common_postings.sql").read_text()
        sql(module)
        sql("""
INSERT INTO cs.source_snapshot(source_id,snapshot_run_id,state,completed_at) VALUES
 ('feed_a','feed-20260915','READY',clock_timestamp()),
 ('feed_b','feed-20260915','READY',clock_timestamp()),
 ('feed_a','next-loading','LOADING',NULL);
INSERT INTO cs.posting_input(source_id,snapshot_run_id,source_posting_id,employer,title,normalized,source_data,evidence) VALUES
 ('feed_a','feed-20260915','123','기관 B','백엔드 개발자','{"title":"백엔드 개발자"}','{"title":"백엔드 개발자","duties_text":"API 개발"}','{"field":"source_notice"}'),
 ('feed_b','feed-20260915','123','기관 C','데이터 분석가','{"title":"데이터 분석가"}','{"title":"데이터 분석가","duties_text":"데이터 분석"}','{"field":"source_notice"}'),
 ('feed_a','next-loading','456','기관 D','보안 엔지니어','{"title":"보안 엔지니어"}','{"title":"보안 엔지니어"}','{}');
""")
        rows = json.loads(sql("""
SELECT jsonb_agg(jsonb_build_object(
 'source',source_id,'native',source_posting_id,'key',posting_id,'identity',posting_identity,
 'snapshot',snapshot_run_id,'inline_hash',inline_source_hash,'content_hash',content_hash,
 'source_data',source_data,'files',attachment_refs) ORDER BY source_id)
FROM cs.common_posting;
"""))
        assert len(rows) == 3, rows  # The LOADING snapshot is invisible.
        alio = next(r for r in rows if r["source"] == "job_alio")
        assert alio["key"] == "123" and alio["identity"] == "job-alio:posting:123", alio
        assert alio["source_data"] == {"title": "데이터 엔지니어", "organization_name": "기관 A", "duties_text": "DB 구축"}, alio
        assert alio["content_hash"] == "prepared-content-hash-for-alio-snapshot-123", alio
        assert alio["files"] == [{"name": "notice.hwp"}], alio
        external = [r for r in rows if r["source"] != "job_alio"]
        assert len({r["key"] for r in rows}) == 3 and len({r["identity"] for r in rows}) == 3, rows
        assert all(r["native"] == "123" and r["key"].startswith("ext-") for r in external), external
        assert all(r["inline_hash"] == r["content_hash"] for r in external), external
        lineage = json.loads(sql("""
SELECT jsonb_agg(jsonb_build_object('source',source_id,'item',item_id,'revision',revision_id,
 'decision',review_decision,'kind',reviewer_kind) ORDER BY source_id)
FROM cs.posting_work_lineage;
"""))
        assert len(lineage) == 3, lineage
        saved = next(r for r in lineage if r["source"] == "job_alio")
        assert saved == {"source": "job_alio", "item": "legacy-item", "revision": "legacy-revision", "decision": "ACCEPT", "kind": "assistant"}, saved
        assert all(r["item"] is None for r in lineage if r["source"] != "job_alio"), lineage
        before = sql("SELECT jsonb_agg(to_jsonb(c) ORDER BY source_id)::text FROM cs.common_posting c")
        sql(module)  # Idempotent installation must preserve all rows and hashes.
        after = sql("SELECT jsonb_agg(to_jsonb(c) ORDER BY source_id)::text FROM cs.common_posting c")
        assert before == after
        # The next stage must be able to consume both ALIO and the synthetic
        # colliding-source rows through this exact view contract.
        sql((ROOT / "hop/cs/sql/002_scope.sql").read_text())
        summary = json.loads(sql("SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY source_id),'[]') FROM cs.scope_summary s"))
        assert {r["source_id"] for r in summary} == {"job_alio", "feed_a", "feed_b"}, summary
        sql((ROOT / "hop/cs/sql/003_completion_report.sql").read_text())
        report = json.loads(sql("SELECT cs.assess_v1(10)"))
        assert {r["source_id"] for r in report["summary"]} == {"job_alio", "feed_a", "feed_b"}, report
        print("common posting interface: ALIO lineage, source collisions, READY gating and replay passed")
    finally:
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)


if __name__ == "__main__":
    main()
