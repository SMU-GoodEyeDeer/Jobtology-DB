"""Network-none PostgreSQL JobKorea linking contracts; synthetic inputs, no paid calls."""
# SQL fixtures retain exact JSON and source hashes for compatibility assertions.
# ruff: noqa: E501

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "hop/ingestions/jobkorea/tests"))
from graph_compatibility import FIXTURE  # noqa: E402

NAME = "jobtology-jobkorea-linking-" + uuid.uuid4().hex[:10]


def command(args, value=None):
    result = subprocess.run(args, input=value, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:] + result.stdout[-2000:])
    return result.stdout.strip()


def sql(value):
    return command(["docker", "exec", "-i", NAME, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres"], value)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def js(value):
    return quote(json.dumps(value, ensure_ascii=False)) + "::jsonb"


def reject(statement, expected):
    try:
        sql(statement)
    except RuntimeError as exc:
        assert expected in str(exc), str(exc)
    else:
        raise AssertionError("Expected " + expected)


def install(relative):
    sql((ROOT / relative).read_text())


def checks():
    legacy = sql("SELECT jsonb_agg(jsonb_build_array(source_id,posting_id,enrichment.linking_input_hash(run_id,posting_id)) ORDER BY source_id,posting_id) FROM ingestion.llm_posting")
    rows = [
        dict(job_title="Backend developer", job_position="백엔드 개발자", job_functions="데이터 엔지니어링", description_text="데이터베이스 설계 및 구축"),
        dict(job_title="Data analyst", job_position="데이터 분석가", experience_level="신입·경력", job_functions="데이터 분석", job_description_url="https://example.invalid/?signed=private-token"),
        dict(job_title="채용 공고", job_position="전문가"),
        dict(job_title="요리사 채용"),
        dict(job_title="프로그래머 채용", source_status="CLOSED"),
    ]
    for i, row in enumerate(rows):
        row.update(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(50100001 + i), company_name="Fixture employer")
    body = json.dumps(rows, ensure_ascii=False)
    digest = hashlib.sha256(body.encode()).hexdigest()
    jobs = sql(f"SELECT run_id FROM ingestion.begin_jobkorea_import({quote(digest)},{len(body.encode())},'jobkorea/'||{quote(digest)}||'/source.json',clock_timestamp())")
    sql(f"SELECT * FROM ingestion.load_jobkorea_document({quote(jobs)},{quote(body)}); SELECT ingestion.verify_jobkorea_file({quote(jobs)},{quote(digest)},{len(body.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({quote(jobs)})")
    assert sql(f"SELECT state FROM ingestion.run WHERE run_id={quote(jobs)}") == "READY"
    pilot = json.loads(sql(f"SELECT enrichment.jobkorea_linking_preview({quote(jobs)},'ncs_competency',5)"))
    assert (pilot["source_count"], pilot["candidate_count"], pilot["unknown_count"], pilot["selected_count"]) == (5, 3, 2, 2), pilot
    assert pilot["content_missing_count"] == 4 and pilot["readiness"] == "INPUT_PREPARATION_REQUIRED", pilot
    assert not pilot["verified_scope"] and not pilot["source_graph_ready"], pilot
    reject(f"SELECT enrichment.jobkorea_linking_preview({quote(jobs)},'ncs_competency',26)", "JOBKOREA_PILOT_CAP_MUST_BE_1_TO_25")
    prepared = json.loads(sql(f"SELECT enrichment.prepare_jobkorea_linking_pilot({quote(jobs)},'ncs_competency',5)"))
    assert prepared["prepared_count"] == 2 and prepared["readiness"] == "READY_FOR_DRY_REQUEST_PLAN", prepared
    assert "private-token" not in json.dumps(prepared)
    assert prepared == json.loads(sql(f"SELECT enrichment.prepare_jobkorea_linking_pilot({quote(jobs)},'ncs_competency',5)"))
    cs_hashes = sql("SELECT jsonb_agg(jsonb_build_array(posting_id,inline_source_hash,content_hash) ORDER BY posting_id) FROM cs.common_posting WHERE source_id='jobkorea'")
    assert sql("SELECT count(*) FROM cs.common_posting WHERE source_id='jobkorea' AND content_hash=enrichment.linking_input_hash(snapshot_run_id,posting_id) AND inline_source_hash<>content_hash") == "5"
    # An old installed bridge upgrades narrowly; source/CS replay cannot revert it.
    common_sql = (ROOT / "hop/cs/sql/001_common_postings.sql").read_text()
    common_sql = common_sql[common_sql.index("CREATE OR REPLACE VIEW cs.common_posting AS"):common_sql.index("COMMENT ON VIEW cs.common_posting IS")]
    old_bridge = common_sql.replace("cs.jobkorea_content_hash(r.run_id,r.normalized->>'posting_id',r.normalized) AS content_hash", "enrichment.hash(cs.jobkorea_source_fields(r.normalized)::text) AS content_hash")
    assert old_bridge != common_sql
    sql(old_bridge)
    install("hop/llm/sql/028_jobkorea_linking.sql")
    for relative in ["hop/ingestions/jobkorea/sql/004_integration.sql", "hop/cs/sql/001_common_postings.sql"]:
        install(relative)
        assert cs_hashes == sql("SELECT jsonb_agg(jsonb_build_array(posting_id,inline_source_hash,content_hash) ORDER BY posting_id) FROM cs.common_posting WHERE source_id='jobkorea'")
    assert legacy == sql("SELECT jsonb_agg(jsonb_build_array(source_id,posting_id,enrichment.linking_input_hash(run_id,posting_id)) ORDER BY source_id,posting_id) FROM ingestion.llm_posting WHERE source_id<>'jobkorea'")
    opts = dict(job_source_id="jobkorea", extract_model="fixture/no-model", categorize_model="fixture/no-model", prompt_version="ko-link-v1", extra_params={}, limit=5, candidate_limit=20, max_matches=4, max_input_chars=24000, max_output_tokens=3000, max_requests=10, request_reserve_usd=.025, max_cost_usd=.25, daily_budget_usd=1, request_delay_ms=0, read_timeout_ms=5000, execute_requests="N", reuse_cache="N", endpoint="https://openrouter.ai/api/v1/chat/completions", acceptance_policy="REVIEW", posting_ids=prepared["posting_ids"], input_bundle_ids=prepared["bundle_ids"])
    reject(f"SELECT enrichment.plan_batch('no-bundles','ENRICH',NULL,{quote(jobs)},'ncs_competency',{js({k: v for k, v in opts.items() if k != 'input_bundle_ids'})})", "JOBKOREA_LINKING_REQUIRES_PREPARED_BUNDLES_AND_DUTY_REVIEW")
    prompt = sql("SELECT jsonb_agg(to_jsonb(p) ORDER BY stage) FROM enrichment.prompt p WHERE version='ko-link-v1'")
    sql(f"SELECT enrichment.plan_batch('jk-dry','ENRICH',NULL,{quote(jobs)},'ncs_competency',{js(opts)}); SELECT enrichment.plan_stage('jk-dry','extract')")
    attempts = json.loads(sql("SELECT jsonb_agg(a.request_body ORDER BY i.ordinal) FROM enrichment.attempt a JOIN enrichment.item i USING(item_id) WHERE a.batch_id='jk-dry'"))
    for request in attempts:
        assert request["provider"] == dict(require_parameters=True, allow_fallbacks=False) and request["max_tokens"] == 3000 and "max_completion_tokens" not in request, request
        assert "jobkorea-request-v1" in request["messages"][0]["content"]
        user = json.loads(request["messages"][1]["content"])
        assert user["input_contract"] == "jobkorea-input-v1" and "metadata" in user["input_instructions"]
        assert "private-token" not in json.dumps(request)
    assert sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL") == "0"
    reject("SELECT enrichment.reserve_request(attempt_id) FROM enrichment.attempt WHERE batch_id='jk-dry' LIMIT 1", "REQUEST_NOT_PLANNED")
    assert prompt == sql("SELECT jsonb_agg(to_jsonb(p) ORDER BY stage) FROM enrichment.prompt p WHERE version='ko-link-v1'")
    # Only SQL-generated synthetic responses below; no HTTP client is invoked.
    sql(f"SELECT enrichment.plan_batch('jk-fixture','ENRICH',NULL,{quote(jobs)},'ncs_competency',{js(opts | dict(execute_requests='Y'))}); SELECT enrichment.plan_stage('jk-fixture','extract')")
    items = json.loads(sql("SELECT jsonb_agg(to_jsonb(i) ORDER BY ordinal) FROM enrichment.item i WHERE batch_id='jk-fixture'"))
    revisions = []
    for item in items:
        source = item["source_data"]
        raw = dict(positions=[dict(id="p1", name=source["role"], evidence_ids=["role:1"])], duties=[], requirements=[], duties_status="not_stated")
        if "description_text" in source:
            raw.update(duties=[dict(position_ids=["p1"], text_parts=[source["description_text"]], evidence_ids=["description_text:1"])], duties_status="explicit")
        else:
            invented = copy.deepcopy(raw)
            invented.update(duties=[dict(position_ids=["p1"], text_parts=[source["job_functions"]], evidence_ids=["job_functions:1"])], duties_status="explicit")
            assert "duties:NON_DUTY_FIELD" in json.loads(sql(f"SELECT enrichment.output_issues_link_v1({js(invented)},{js(source)})"))
        response = dict(id="synthetic-fixture", model=opts["extract_model"], choices=[dict(finish_reason="stop", message=dict(content=json.dumps(raw, ensure_ascii=False)))], usage=dict(prompt_tokens=100, completion_tokens=50))
        aid = quote(item["extraction_id"])
        sql(f"SELECT enrichment.reserve_request({aid}); SELECT enrichment.save_response({aid},200,{quote(json.dumps(response, ensure_ascii=False))},1)")
        assert sql(f"SELECT state||':'||enrichment.accounted_cost(state,cost_usd,reserved_usd)::text FROM enrichment.attempt WHERE attempt_id={aid}") == "VALIDATED:0.025"
        rid = sql(f"SELECT enrichment.capture_extraction({quote(item['item_id'])},'synthetic-editor','Synthetic exact-source fixture')")
        sql(f"SELECT enrichment.decide_extraction({quote(rid)},'ACCEPT','independent-fixture-reviewer','assistant','Synthetic source and missing-content evidence checked')")
        reject(f"SELECT enrichment.review_item({quote(item['item_id'])},'ACCEPT','fixture','Blanket review prohibited')", "JOBKOREA_REQUIRES_INDEPENDENT_EXTRACTION_AND_LINK_REVIEW")
        revisions.append(rid)
    assert sql("SELECT count(*) FROM cs.posting_work_lineage WHERE source_id='jobkorea' AND snapshot_run_id=" + quote(jobs) + " AND review_decision='ACCEPT'") == "2"
    assert sql("SELECT count(*) FROM enrichment.current_reviewed_posting WHERE run_id=" + quote(jobs) + " AND decision='ACCEPT'") == "2"
    sql("SELECT enrichment.plan_stage('jk-fixture','categorize')")
    assert sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='jk-fixture' AND stage='categorize' AND state='SKIPPED' AND issues='[\"NO_EXPLICIT_DUTIES\"]'") == "1"
    duty_revision = sql("SELECT revision_id FROM enrichment.extraction_revision WHERE jsonb_array_length(extraction->'duties')>0")
    cate = sql("SELECT a.attempt_id FROM enrichment.item i JOIN enrichment.attempt a ON a.attempt_id=i.categorization_id WHERE i.batch_id='jk-fixture' AND a.state='PLANNED'")
    no_match = dict(id="synthetic-no-match", model="fixture/no-model", choices=[dict(finish_reason="stop", message=dict(content=json.dumps(dict(matches=[], outcome="no_supported_match"))))], usage=dict(cost=0, is_byok=True, cost_details=dict(upstream_inference_cost=.002), prompt_tokens=100, completion_tokens=20))
    sql(f"SELECT enrichment.reserve_request({quote(cate)}); SELECT enrichment.save_response({quote(cate)},200,{quote(json.dumps(no_match))},1); SELECT enrichment.finish_batch('jk-fixture')")
    assert sql(f"SELECT outcome FROM enrichment.linking_status WHERE revision_id={quote(duty_revision)}") == "NO_SUPPORTED_MATCH"
    assert sql(f"SELECT cost_usd FROM enrichment.attempt WHERE attempt_id={quote(cate)}") == "0.002"
    packet = json.loads(sql("SELECT enrichment.prepare_link_review('jk-fixture','',5,'fixture-packet-author')"))
    packet.update(reviewer="independent-fixture-reviewer", reviewer_kind="assistant")
    packet["cases"][0].update(extraction_decision="ACCEPT", extraction_notes="Synthetic source checked")
    changed_packet = copy.deepcopy(packet)
    changed_packet["cases"][0]["source_data"]["title"] = "Forged title"
    reject(f"SELECT enrichment.apply_link_review({js(changed_packet)})", "REVIEW_CONTEXT_OR_DECISION_CHANGED")
    candidate = sql(f"SELECT enrichment.propose_link({quote(duty_revision)},'2001020101_24v1',0,'Synthetic explicit database design overlap','fixture')")
    assert sql(f"SELECT outcome FROM enrichment.linking_status WHERE revision_id={quote(duty_revision)}") == "LINK_REVIEW"
    sql(f"SELECT enrichment.decide_link({quote(candidate)},'ACCEPT','independent-link-reviewer','assistant','Synthetic actual duty and versioned definition checked')")
    assert sql(f"SELECT outcome FROM enrichment.linking_status WHERE revision_id={quote(duty_revision)}") == "ACCEPTED_LINKS"
    assert sql("SELECT count(*) FROM enrichment.linking_status WHERE job_run_id=" + quote(jobs) + " AND outcome='NO_EXPLICIT_DUTIES'") == "1"
    published = sql("SELECT enrichment.prepare_link_publication('jk-publication')")
    assert published == "jk-publication"
    assert sql("SELECT string_agg(source_id,',' ORDER BY source_id) FROM enrichment.link_publication_source_run WHERE publication_id='jk-publication'") == "job_alio,jobkorea,nara_job"
    assert sql("SELECT count(*) FROM enrichment.link_publication_item WHERE publication_id='jk-publication' AND posting_identity LIKE 'source:posting:jobkorea:%'") == "2"
    sql("SELECT enrichment.check_link_publication('jk-publication'); SELECT enrichment.finish_link_publication('jk-publication',false)")
    sql(f"SELECT enrichment.decide_link({quote(candidate)},'REJECT','independent-link-reviewer','assistant','Synthetic revocation')")
    reject("SELECT enrichment.check_link_publication('jk-publication')", "SOURCE_OR_REVIEW_CHANGED_DURING_PUBLICATION")
    assert sql("SELECT count(*) FROM enrichment.link_publication_item WHERE publication_id='jk-publication' AND jsonb_array_length(payload->'links')=1") == "1"
    assert sql("SELECT count(*) FROM ingestion.request_attempt WHERE run_id=" + quote(jobs)) == "0"
    assert sql("SELECT count(*) FROM retention.writer") == "0"
    print("JobKorea pilot scope, verified bundles, dry planning, unchanged OpenRouter request shape, missing-cost reservation, explicit duties/no-match outcomes, independent review, CS bridge replay/lineage, publication identities/pins and stale review-context gates passed", flush=True)


def main():
    try:
        command(["docker", "run", "-d", "--pull", "never", "--network", "none", "--name", NAME, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine")])
        for _ in range(100):
            try:
                if "PostgreSQL init process complete" in command(["docker", "logs", NAME]) and sql("SELECT 1") == "1":
                    break
            except RuntimeError:
                pass
            time.sleep(.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        install("docs/hop-migration/schema.sql")
        install("docs/hop-migration/checks.sql")
        sql(FIXTURE)
        sql("UPDATE ingestion.record SET normalized=normalized||'{\"code\":\"2001020101_24v1\",\"name\":\"데이터베이스 설계\",\"definition\":\"데이터 요구사항에 따라 데이터베이스를 설계하는 능력\"}'::jsonb WHERE run_id='ncs_competency'")
        install("docs/hop-migration/operations.sql")
        install("hop/llm/sql/001_schema.sql")
        install("hop/retention/sql/001_retention.sql")
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "027":
                sql(path.read_text())
        install("hop/cs/sql/001_common_postings.sql")
        for path in sorted((ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
            sql(path.read_text())
        for _ in range(2):
            for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
                sql(path.read_text())
        checks()
    finally:
        subprocess.run(["docker", "rm", "-fv", NAME], capture_output=True, check=False)


if __name__ == "__main__":
    main()
