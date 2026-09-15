"""Verify qualification policy installation and historical run isolation."""

import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[3]
NAME = f"jt-cs-qualification-policy-{os.getpid()}"

LEGACY = {
    "20010105", "20010107", "20010202", "20010204", "20010207",
    "20010208", "20010701", "20010703", "20010705", "20010706",
    "20010707",
}
ADDITIONAL = {
    "20010209", "20010213", "20010301", "20010303", "20010401",
    "20010601", "20010602", "20010603", "20011101", "20020103",
    "20030303",
}

SCHEMA = """
CREATE SCHEMA ingestion;
CREATE TABLE ingestion.run (
    run_id text PRIMARY KEY, source_id text NOT NULL, state text NOT NULL,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE VIEW ingestion.latest_ready_run AS
SELECT DISTINCT ON (source_id) * FROM ingestion.run WHERE state='READY'
ORDER BY source_id,created_at DESC,run_id DESC;
CREATE TABLE ingestion.dependency (
    run_id text NOT NULL, input_source_id text NOT NULL,
    input_run_id text NOT NULL
);
CREATE TABLE ingestion.competency (
    run_id text NOT NULL, code text NOT NULL, name text NOT NULL,
    occupation_code text NOT NULL, occupation_name text NOT NULL
);
CREATE TABLE ingestion.partition (
    run_id text NOT NULL, partition_id text NOT NULL, kind text NOT NULL,
    request_context jsonb NOT NULL, page_size integer NOT NULL,
    expected_total integer
);
CREATE TABLE ingestion.qualification_mapping (
    run_id text NOT NULL, competency_code text NOT NULL,
    qualification_code text NOT NULL, qualification_name text NOT NULL,
    standard_version text NOT NULL
);
CREATE TABLE ingestion.exam_session (
    run_id text NOT NULL, qualification_code text NOT NULL,
    year integer, round integer, name text, dates jsonb
);
CREATE VIEW ingestion.qualification_scope AS
SELECT unnest(ARRAY[
 'DB엔지니어링','UI/UX엔지니어링','빅데이터기획','빅데이터분석',
 '생성형AI엔지니어링','시스템SW엔지니어링','응용SW엔지니어링',
 '인공지능모델링','인공지능서비스구현','인공지능플랫폼구축',
 '인공지능학습데이터구축']) AS occupation_name;
CREATE SCHEMA cs;
CREATE TABLE cs.current_scope (
    policy_id text, source_id text, source_posting_id text,
    posting_identity text, snapshot_run_id text, role_id text,
    role_name text, binding_hash text, selected_family text, scope_status text
);
CREATE TABLE cs.accepted_role_link (
    posting_identity text, role_id text, binding_hash text,
    candidate_id text, competency_code text, duty_index integer
);
"""

SEED = """
INSERT INTO ingestion.run(run_id,source_id,state,settings) VALUES
 ('ncs-source','ncs_competency','READY','{}'),
 ('qual-old','ncs_qualification','READY','{}');
INSERT INTO ingestion.competency
SELECT 'ncs-source',occupation_code||'_unit',occupation_name||' unit',
       occupation_code,occupation_name
FROM ingestion.qualification_occupation_policy
WHERE enabled OR occupation_code IN ('19010401','20020303');
INSERT INTO ingestion.run(run_id,source_id,state,settings)
SELECT 'qual-new','ncs_qualification','READY',
 jsonb_build_object('qualification_scope_codes',
   jsonb_agg(occupation_code ORDER BY occupation_code))
FROM ingestion.active_qualification_scope;
INSERT INTO ingestion.run(run_id,source_id,state,settings) VALUES
 ('qnet-new','qnet_schedule','READY',
  '{"year_from":2026,"year_to":2027}');
INSERT INTO ingestion.dependency VALUES
 ('qual-old','ncs_competency','ncs-source'),
 ('qual-new','ncs_competency','ncs-source'),
 ('qnet-new','ncs_qualification','qual-new');
INSERT INTO ingestion.qualification_mapping VALUES
 ('qual-new','20010303_unit','T001','Related test credential','v1');
INSERT INTO ingestion.partition
SELECT run_id,partition_id,'PAGED',request_context,50,0
FROM ingestion.expected_reference_partition
WHERE run_id IN ('qual-old','qual-new','qnet-new');
UPDATE ingestion.partition SET expected_total=1
WHERE run_id='qual-new' AND partition_id='ncs-20010303_unit';
INSERT INTO ingestion.exam_session VALUES
 ('qnet-new','T001',2026,1,'Related test session','{}'::jsonb);
INSERT INTO cs.current_scope VALUES
 ('cs-it-ai-data-v1','job_alio','123','job-alio:posting:123','source-run',
  'p1','IT role','bound','IT_SYSTEMS','IN_SCOPE'),
 ('cs-it-ai-data-v1','job_alio','123','job-alio:posting:123','source-run',
  'p2','Administrative role','admin-bound',NULL,'OUT_OF_SCOPE'),
 ('cs-it-ai-data-v1','job_alio','123','job-alio:posting:123','source-run',
  'p3','Changed role','current-bound','DATA','IN_SCOPE');
INSERT INTO cs.accepted_role_link VALUES
 ('job-alio:posting:123','p1','bound','mapped','20010303_unit',0),
 ('job-alio:posting:123','p1','bound','empty','20010301_unit',1),
 ('job-alio:posting:123','p1','bound','disabled','19010401_unit',2),
 ('job-alio:posting:123','p1','bound','unknown','99999999_unit',3),
 ('job-alio:posting:123','p2','admin-bound','excluded','20010303_unit',0),
 ('job-alio:posting:123','p3','stale-bound','stale','20010303_unit',0);
"""

LINKS = json.dumps([
    {"source_id": "job_alio", "source_posting_id": "123", "position_id": "p1",
     "link_id": "mapped", "ncs_unit_code": "20010303_unit"},
    {"source_id": "job_alio", "source_posting_id": "123", "position_id": "p2",
     "link_id": "empty", "ncs_unit_code": "20010301_unit"},
    {"source_id": "job_alio", "source_posting_id": "123", "position_id": "p3",
     "link_id": "disabled", "ncs_unit_code": "19010401_unit"},
    {"source_id": "job_alio", "source_posting_id": "123", "position_id": "p4",
     "link_id": "unknown", "ncs_unit_code": "99999999_unit"},
])


def command(args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{args}: {result.stderr}")
    return result.stdout.strip()


def sql(statement):
    return command(
        ["docker", "exec", "-i", NAME, "psql", "-X", "-v", "ON_ERROR_STOP=1",
         "-A", "-t", "-U", "postgres", "-d", "postgres"], input=statement
    )


def main():
    try:
        command(["docker", "run", "-d", "--name", NAME,
                 "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17-alpine"])
        for _ in range(50):
            logs = subprocess.run(["docker", "logs", NAME], capture_output=True,
                                  text=True)
            if "PostgreSQL init process complete" in logs.stdout + logs.stderr:
                try:
                    if sql("SELECT 1") == "1":
                        break
                except RuntimeError:
                    pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        sql(SCHEMA)
        sql((ROOT / "hop/cs/sql/006_qualification_support.sql").read_text())
        enabled = set(sql("SELECT occupation_code FROM ingestion.active_qualification_scope").splitlines())
        assert enabled == LEGACY | ADDITIONAL, enabled
        sql(SEED)
        counts = sql("""
SELECT run_id||':'||count(*) FROM ingestion.expected_reference_partition
WHERE run_id IN ('qual-old','qual-new') GROUP BY run_id ORDER BY run_id
""").splitlines()
        assert counts == ["qual-new:22", "qual-old:11"], counts
        assert sql("SELECT count(*) FROM ingestion.reference_scope_issue") == "0"
        report = json.loads(sql(f"""
SELECT jsonb_object_agg(link_id,jsonb_build_object(
 'qualification',qualification_status,'exam',exam_status))
FROM ingestion.related_qualification_report('{LINKS}'::jsonb,'qual-new','qnet-new')
"""))
        assert report == {
            "mapped": {"qualification": "HAS_RELATED_QUALIFICATION",
                       "exam": "HAS_EXAM_SESSION"},
            "empty": {"qualification": "FETCHED_NO_MAPPING",
                      "exam": "NO_MAPPING_TO_CHECK"},
            "disabled": {"qualification": "UNFETCHED_QUALIFICATION_PARTITION",
                         "exam": "NO_MAPPING_TO_CHECK"},
            "unknown": {"qualification": "UNRESOLVED_NCS_IDENTIFIER",
                        "exam": "NO_MAPPING_TO_CHECK"},
        }, report
        sql((ROOT / "hop/cs/sql/007_qualification_status.sql").read_text())
        details = json.loads(sql("""
SELECT jsonb_object_agg(candidate_id,jsonb_build_object(
 'qualification',qualification_status,'exam',exam_status,
 'category',ncs_category)) FROM cs.current_role_qualification
"""))
        assert details == {
            "mapped": {"qualification": "HAS_RELATED_QUALIFICATION",
                       "exam": "HAS_EXAM_SESSION", "category": "TECHNICAL_CATEGORY_20"},
            "empty": {"qualification": "FETCHED_NO_MAPPING",
                      "exam": "NO_MAPPING_TO_CHECK", "category": "TECHNICAL_CATEGORY_20"},
            "disabled": {"qualification": "UNFETCHED_QUALIFICATION_PARTITION",
                         "exam": "NO_MAPPING_TO_CHECK", "category": "OTHER_NCS_CATEGORY"},
            "unknown": {"qualification": "UNRESOLVED_NCS_IDENTIFIER",
                        "exam": "NO_MAPPING_TO_CHECK", "category": "UNRESOLVED_NCS"},
        }, details
        summary = json.loads(sql("""
SELECT jsonb_build_object('links',accepted_ncs_links,
 'technical',technical_ncs_links,'other',other_ncs_links,
 'credentials',related_credentials,'unfetched',unfetched_links,
 'empty',fetched_without_mapping_links,'exams',credentials_with_exam_sessions)
FROM cs.current_role_qualification_summary
"""))
        assert summary == {
            "links": 4, "technical": 2, "other": 1,
            "credentials": 1, "unfetched": 1, "empty": 1, "exams": 1,
        }, summary
        sql("""
UPDATE ingestion.qualification_occupation_policy SET enabled=false
WHERE occupation_code='20010303' AND policy_version='cs-it-ai-data-v1'
""")
        assert sql("""
SELECT string_agg(run_id||':'||n::text,',' ORDER BY run_id)
FROM (SELECT run_id,count(*) AS n FROM ingestion.expected_reference_partition
 WHERE run_id IN ('qual-old','qual-new') GROUP BY run_id) x
""") == "qual-new:22,qual-old:11"
        assert sql("SELECT count(*) FROM ingestion.reference_scope_issue") == "0"
        print("qualification policy: scope isolation, bound-role status view, and credential/exam reporting passed")
    finally:
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)


if __name__ == "__main__":
    main()
