"""Disposable, network-none PostgreSQL checks for the shared source graph contract."""
# Long SQL/JSON fixtures preserve source facts for exact compatibility comparisons.
# ruff: noqa: E501

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
NAME = "jobtology-jobkorea-graph-" + uuid.uuid4().hex[:10]


def command(args, text=None):
    result = subprocess.run(args, input=text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:] + result.stdout[-4000:])
    return result.stdout.strip()


def sql(text):
    return command(
        [
            "docker",
            "exec",
            "-i",
            NAME,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-A",
            "-t",
            "-U",
            "postgres",
        ],
        text,
    )


def install(relative):
    sql((ROOT / relative).read_text())


def inventory():
    return json.loads(
        sql("""
SELECT jsonb_build_object(
 'records',(SELECT jsonb_agg(to_jsonb(g) ORDER BY id) FROM ingestion.graph_record g WHERE source_id<>'jobkorea'),
 'refs',(SELECT jsonb_agg(to_jsonb(g) ORDER BY record_id,field,identity_id)
 FROM ingestion.graph_reference g WHERE run_id<>'local'));
""")
    )


FIXTURE = """
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,completed_at)
 SELECT x,x,'FULL','fixture','READY',clock_timestamp() FROM unnest(ARRAY[
 'alio_organization','job_alio','nara_job','ncs_career_path','ncs_competency',
 'ncs_qualification','qnet_schedule']) x;
INSERT INTO ingestion.dependency VALUES
 ('job_alio','alio_organization','alio_organization'),
 ('ncs_qualification','ncs_competency','ncs_competency'),
 ('qnet_schedule','ncs_qualification','ncs_qualification');
CREATE TEMP TABLE source_fixture(source text,partition text,representation text,normalized jsonb);
INSERT INTO source_fixture VALUES
 ('alio_organization','one','one','{"kind":"Organization","code":"o","name":"Employer","source_url":"https://example.invalid/ref","website":"private","custom":"keep"}'),
 ('job_alio','index','list','{"kind":"JobPosting","posting_id":"123","representation":"list","title":"Legacy","organization_code":"o","date_posted":"2026-10-01","closing_date":"2026-10-31","custom":"keep","eligibility_text":"long private"}'),
 ('job_alio','detail-123','detail','{"kind":"JobPosting","posting_id":"123","representation":"detail","title":"Legacy","organization_code":"o","date_posted":"2026-10-01","closing_date":"2026-10-31","custom":"keep","description_text":"legacy description"}'),
 ('nara_job','index','list','{"kind":"JobPosting","posting_id":"123","representation":"list","ongoing":false,"title":"Nara","description_text":"legacy description"}'),
 ('ncs_career_path','one','one','{"kind":"CareerPath","occupation_code":"occ","competency_code":"unit","custom":"keep"}'),
 ('ncs_competency','one','one','{"kind":"Competency","code":"unit","occupation_code":"occ","definition":"private","custom":"keep"}'),
 ('ncs_qualification','ncs-unit','one','{"kind":"QualificationMapping","competency_code":"unit","qualification_code":"q","custom":"keep"}'),
 ('qnet_schedule','year-2026-item-q','one','{"kind":"ExamSession","qualification_code":"q","year":"2026","custom":"keep"}');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
 SELECT source,partition,CASE WHEN representation='detail' THEN 'DETAIL' ELSE 'FILE' END,1,1 FROM source_fixture;
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
 byte_length,encoding,http_status,provider_result,retrieved_at,declared_total,
 effective_page,effective_page_size,item_count,selected,verified_at)
 SELECT source,partition,partition,1,source||'/fixture.json',repeat('a',64),1,'UTF-8',200,
 CASE WHEN source IN('alio_organization','job_alio') THEN '200'
 WHEN source IN('ncs_qualification','qnet_schedule') THEN '00' END,
 clock_timestamp(),1,1,1,1,true,clock_timestamp() FROM source_fixture;
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT source,partition,'/0',CASE WHEN source IN('job_alio','nara_job') THEN '123:'||representation ELSE source END,
 '{"private":"raw"}',normalized FROM source_fixture;
"""


def main():
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                "none",
                "--name",
                NAME,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine"),
            ]
        )
        for _ in range(100):
            try:
                if (
                    "PostgreSQL init process complete" in command(["docker", "logs", NAME])
                    and sql("SELECT 1") == "1"
                ):
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        install("docs/hop-migration/schema.sql")
        install("docs/hop-migration/checks.sql")
        sql(FIXTURE)
        assert sql("SELECT count(*) FROM ingestion.validation_issue") == "0"
        before = inventory()
        assert len(before["records"]) == 8 and len(before["refs"]) == 13, before
        assert (
            sql("""
SELECT count(*) FROM ingestion.graph_record g JOIN ingestion.ready_record r USING(record_id,run_id)
WHERE g.facts_json IS DISTINCT FROM (r.normalized-ARRAY['definition','eligibility_text',
 'disqualification_text','preference_text','selection_text','address','website','source_url'])::text;
""")
            == "0"
        )
        install("hop/ingestions/jobkorea/sql/004_integration.sql")  # CS absent is supported.
        assert inventory() == before
        sql("""
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,completed_at)
 VALUES('local','jobkorea','REPLAY','fixture','READY',clock_timestamp());
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
 VALUES('local','local-json','FILE',1,1);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
 byte_length,encoding,http_status,transport,retrieved_at,effective_page,item_count,selected,verified_at)
 VALUES('local','local-json','local-json',1,'jobkorea/'||repeat('b',64)||'/source.json',repeat('b',64),
 1,'UTF-8',NULL,'LOCAL_FILE',clock_timestamp(),1,1,true,clock_timestamp());
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 VALUES('local','local-json','/0','123','{"signed_url":"secret-token"}',
 '{"kind":"JobPosting","posting_id":"123","title":"Local title","employer_identity_kind":"CATEGORY_ONLY",
 "company_name_raw":"중소기업","content_status":"MISSING","source_url":"private","unexpected":"secret-token",
 "description_text":"secret-token","deadline_kind":"ROLLING","deadline_basis":"USER_POLICY"}');
""")
        assert (
            sql(
                "SELECT count(*) FROM ingestion.validation_issue WHERE run_id='local' AND issue='JOBKOREA_VALIDATOR_NOT_INSTALLED'"
            )
            == "1"
        )
        graph = json.loads(
            sql("SELECT facts_json FROM ingestion.graph_record WHERE run_id='local'")
        )
        assert graph["content_status"] == "MISSING" and graph["company_name_raw"] == "중소기업"
        assert "secret-token" not in json.dumps(graph) and "source_url" not in graph
        assert (
            sql("SELECT identity_id FROM ingestion.graph_reference WHERE run_id='local'")
            == "source:posting:jobkorea:" + hashlib.sha256(b"123").hexdigest()
        )
        assert sql("SELECT count(*) FROM ingestion.graph_reference WHERE run_id='local'") == "1"
        # An installed adapter hook must survive both shared and Nara reinstall.
        sql("""
CREATE OR REPLACE FUNCTION ingestion.local_file_validation_issue()
RETURNS TABLE(run_id text,issue text,location text) LANGUAGE sql STABLE AS $$
 SELECT 'local'::text,'TEST_ADAPTER_GATE'::text,'/0'::text $$;
""")
        install("docs/hop-migration/schema.sql")
        install("docs/hop-migration/checks.sql")
        install("hop/ingestions/nara_job/sql/001_schema.sql")
        install("hop/ingestions/nara_job/sql/003_checks.sql")
        assert (
            sql("SELECT count(*) FROM ingestion.validation_issue WHERE issue='TEST_ADAPTER_GATE'")
            == "1"
        )
        assert inventory() == before
        install("hop/retention/sql/000_operations.sql")
        assert (
            sql("SELECT count(*) FROM ingestion.request_attempt WHERE source_id='jobkorea'") == "0"
        )
        assert sql("SELECT count(*) FROM ingestion.request_attempt") == "8"
        install("hop/retention/sql/000_operations.sql")
        assert sql("SELECT count(*) FROM ingestion.request_attempt") == "8"
        # HTTP NULL metadata is rejected even after local-file nullable migration.
        failure = subprocess.run(
            ["docker", "exec", "-i", NAME, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres"],
            input="UPDATE ingestion.document SET http_status=NULL WHERE run_id='alio_organization'",
            text=True,
            capture_output=True,
        )
        assert failure.returncode != 0 and "document_transport_metadata_check" in failure.stderr
        print(
            "source graph compatibility: seven legacy sources, local privacy/identity, replay gates, truthful transport and zero local requests passed"
        )
    finally:
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)


if __name__ == "__main__":
    main()
