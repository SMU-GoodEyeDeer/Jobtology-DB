"""Network-none full-catalog PM retrieval, exact legacy replay and status checks."""

# SQL fixture strings retain exact source and canonical serialization contracts.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import metadata_occupation_context as context

f: Any = context.f
ROOT = Path(__file__).resolve().parents[3]
NCS = "ba32f673-255c-4990-80d4-8dbef6008e2f"
REVISION = "metadata-occupation-lexical-v3"


def history() -> str:
    tables = [
        "metadata_occupation_catalog",
        "metadata_occupation_catalog_context",
        "metadata_occupation_binding",
        "metadata_occupation_result",
        "metadata_occupation_candidate",
        "metadata_occupation_decision",
        "input_bundle",
        "item_input",
        "item",
        "attempt",
        "batch",
        "prompt",
    ]
    return f.sql(
        "SELECT jsonb_build_object("
        + ",".join(
            f"'{name}',(SELECT enrichment.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')::text) FROM enrichment.{name} t)"
            for name in tables
        )
        + ")"
    )


def candidates(rows: list[dict[str, Any]], revision: bool) -> list[dict[str, Any]]:
    function = "metadata_occupation_candidates_v3" if revision else "metadata_occupation_candidates"
    return json.loads(
        f.sql(
            "WITH outputs AS (SELECT r.value->>'id' id,r.value->'fields' fields,enrichment."
            + function
            + "("
            + f.quote(NCS)
            + ",r.value->'fields',12) shortlist FROM jsonb_array_elements("
            + f.js(rows)
            + ") WITH ORDINALITY r(value,ordinal)) SELECT jsonb_agg(jsonb_build_object('id',id,'fields',fields,"
            "'candidates',shortlist,'candidates_hash',enrichment.hash(shortlist::text)) ORDER BY id) FROM outputs"
        )
    )


def checks(args: argparse.Namespace) -> None:
    units = json.loads(args.catalog.read_text())
    audit = json.loads(args.source_audit.read_text())
    selection = json.loads(args.selection.read_text())
    assert len(units) == 15520
    source_baseline = f.sql("SELECT count(*) FROM ingestion.request_attempt")
    for number in (
        "031_metadata_occupation_workers",
        "032_metadata_occupation_context",
        "033_metadata_occupation_roles",
    ):
        f.install(f"hop/llm/sql/{number}.sql")
    f.sql(
        "INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES("
        + f.quote(NCS)
        + ",'ncs_competency','REPLAY','LOCAL_NO_NETWORK_FIXTURE','READY');"
        "INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total) VALUES("
        + f.quote(NCS)
        + ",'full','FILE',15520,15520);"
        "INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,declared_total,effective_page,effective_page_size,item_count,verified_at) VALUES("
        + f.quote(NCS)
        + ",'full','full',1,'local-whitelisted-catalog',repeat('0',64),1,'UTF-8',200,clock_timestamp(),true,15520,1,15520,15520,clock_timestamp());"
        "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) SELECT "
        + f.quote(NCS)
        + ",'full',ordinal::text,value->>'code','{}',value FROM jsonb_array_elements("
        + f.js(units)
        + ") WITH ORDINALITY x(value,ordinal)"
    )
    catalog = json.loads(
        f.sql("SELECT enrichment.prepare_metadata_occupation_catalog(" + f.quote(NCS) + ")")
    )
    assert catalog["occupation_count"] == 1094

    # A small synthetic paid-history fixture, with no HTTP request ever made.
    titles = [
        "프론트엔드 개발자",
        "AI/Cloud 개발 PM",
        "프론트엔드 개발자",
        "프론트엔드 개발자",
        "프론트엔드 개발자",
        "AI/Cloud 개발 PM",
    ]
    source = [
        dict(
            job_title=title,
            company_name="Local fixture",
            product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(94000000 + i),
        )
        for i, title in enumerate(titles)
    ]
    body = json.dumps(source, ensure_ascii=False)
    sha = hashlib.sha256(body.encode()).hexdigest()
    jobs = f.sql(
        f"SELECT run_id FROM ingestion.begin_jobkorea_import({f.quote(sha)},{len(body.encode())},'jobkorea/'||{f.quote(sha)}||'/source.json',clock_timestamp())"
    )
    f.sql(
        f"SELECT * FROM ingestion.load_jobkorea_document({f.quote(jobs)},{f.quote(body)}); SELECT ingestion.verify_jobkorea_file({f.quote(jobs)},{f.quote(sha)},{len(body.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({f.quote(jobs)}); SELECT enrichment.prepare_jobkorea_input_bundle({f.quote(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={f.quote(jobs)}"
    )
    ids = [
        "ext-jobkorea-" + hashlib.sha256(str(94000000 + i).encode()).hexdigest()
        for i in range(len(source))
    ]
    opts = dict(
        categorize_model="openai/gpt-5.6-luna",
        provider_only="openai",
        extra_params={},
        limit=6,
        candidate_limit=12,
        max_matches=1,
        max_input_chars=16000,
        max_output_tokens=768,
        max_requests=6,
        request_reserve_usd=0.005,
        max_cost_usd=0.05,
        daily_budget_usd=4.75,
        request_delay_ms=0,
        read_timeout_ms=1000,
        execute_requests="N",
        reuse_cache="N",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        reasoning_effort="none",
    )
    v1_opts = opts | dict(limit=1, max_requests=1, posting_ids=ids[0])
    v2_opts = opts | dict(prompt_version="ko-metadata-occupation-v2", posting_ids="|".join(ids[1:]))
    for batch, options in [("pm-old-v1", v1_opts), ("pm-old-v2", v2_opts)]:
        f.sql(
            f"SELECT enrichment.plan_metadata_occupation_batch({f.quote(batch)},{f.quote(jobs)},{f.quote(NCS)},{f.js(options)})"
        )
    items = json.loads(
        f.sql(
            "SELECT jsonb_agg(jsonb_build_object('item_id',item_id,'posting_id',posting_id,'attempt_id',categorization_id) ORDER BY posting_id) FROM enrichment.item WHERE batch_id IN ('pm-old-v1','pm-old-v2')"
        )
    )
    by_posting = {item["posting_id"]: item for item in items}
    results = {}
    for index in (0, 1, 2, 3, 5):
        item = by_posting[ids[index]]
        output = (
            dict(
                outcome="abstained",
                matches=[],
                abstain_reason="No supported project-management candidate in frozen metadata shortlist.",
            )
            if index in (1, 5)
            else dict(
                outcome="matched",
                matches=[
                    dict(
                        occupation_code="20010202",
                        reason="Explicit frontend developer title supports application software occupation",
                        evidence=[dict(field="title", quote=titles[index])],
                    )
                ],
                abstain_reason="",
            )
        )
        reservation = (
            ",reserved_at=clock_timestamp(),reserved_usd=0.005,cost_usd=0.001" if index == 0 else ""
        )
        f.sql(
            f"UPDATE enrichment.attempt SET state='VALIDATED',parsed_output={f.js(output)}{reservation} WHERE attempt_id={f.quote(item['attempt_id'])}"
        )
        results[index] = f.sql(
            f"SELECT enrichment.capture_metadata_occupation_result({f.quote(item['item_id'])},'synthetic-local-fixture')"
        )
        f.sql(
            f"UPDATE enrichment.item SET state='VALIDATED' WHERE item_id={f.quote(item['item_id'])}"
        )
    for index, decision in [(0, "ACCEPT"), (3, "REJECT"), (5, "REJECT")]:
        f.sql(
            f"SELECT enrichment.decide_metadata_occupation({f.quote(results[index])},{f.quote(decision)},'independent-fixture-reviewer','assistant','Synthetic local source reviewed')"
        )
    before = history()
    graph_before = f.sql(
        f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},{f.quote(NCS)},true)"
    )
    binding = f.sql(
        "SELECT candidates FROM enrichment.metadata_occupation_binding WHERE item_id="
        + f.quote(by_posting[ids[1]]["item_id"])
    )
    bundle = f.sql(
        "SELECT bundle_id FROM enrichment.item_input WHERE item_id="
        + f.quote(by_posting[ids[1]]["item_id"])
    )
    bind_before = f.sql(
        f"SELECT enrichment.bind_metadata_occupation_item({f.quote(by_posting[ids[1]]['item_id'])},{f.quote(bundle)},{f.quote(binding)}::jsonb)"
    )
    f.install("hop/llm/sql/034_metadata_occupation_pm.sql")
    assert history() == before
    assert graph_before == f.sql(
        f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},{f.quote(NCS)},true)"
    )
    assert bind_before == f.sql(
        f"SELECT enrichment.bind_metadata_occupation_item({f.quote(by_posting[ids[1]]['item_id'])},{f.quote(bundle)},{f.quote(binding)}::jsonb)"
    )
    for batch, options in [
        ("pm-old-v1", v1_opts),
        ("pm-old-v1", v1_opts | dict(prompt_version="ko-metadata-occupation-v1")),
        ("pm-old-v2", v2_opts),
    ]:
        for revision_opts in ({}, {"retrieval_revision": ""}, {"retrieval_revision": None}):
            assert (
                json.loads(
                    f.sql(
                        f"SELECT enrichment.plan_metadata_occupation_batch({f.quote(batch)},{f.quote(jobs)},{f.quote(NCS)},{f.js(options | revision_opts)})"
                    )
                )["replay"]
                is True
            )
            assert history() == before
    f.reject(
        f"SELECT enrichment.plan_metadata_occupation_batch('pm-old-v2',{f.quote(jobs)},{f.quote(NCS)},{f.js(v2_opts | dict(retrieval_revision=REVISION))})",
        "METADATA_BATCH_IS_IMMUTABLE",
    )
    f.reject(
        f"SELECT enrichment.plan_metadata_occupation_batch('bad-retrieval',{f.quote(jobs)},{f.quote(NCS)},{f.js(v2_opts | dict(retrieval_revision='unsupported'))})",
        "INVALID_METADATA_RETRIEVAL_REVISION",
    )
    # Canonical reinstallation cannot recursively rename functions or alter rows.
    for _ in range(2):
        for number in range(29, 35):
            path = next((ROOT / "hop/llm/sql").glob(f"{number:03d}_*.sql"))
            f.sql(path.read_text())
        assert history() == before
        assert graph_before == f.sql(
            f"SELECT enrichment.metadata_occupation_graph_hash({f.quote(jobs)},{f.quote(NCS)},true)"
        )
    expected_status = {
        ids[0]: "ACCEPTED_INFERRED_OCCUPATION",
        ids[1]: "ABSTAINED",
        ids[2]: "REVIEW_PENDING",
        ids[3]: "REJECTED",
        ids[4]: "PENDING",
        ids[5]: "REJECTED",
    }
    actual_status = json.loads(
        f.sql(
            f"SELECT jsonb_object_agg(posting_id,outcome) FROM enrichment.metadata_occupation_status({f.quote(jobs)},{f.quote(NCS)})"
        )
    )
    assert actual_status == expected_status, actual_status

    # Non-PM boundaries from the existing actual-catalog regression remain exact.
    unchanged = [
        "Cyber Threat Analyst",
        "[유명 SCM전문컨설팅회사] Data Scientist",
        "SKT차세대개발 java 통신사",
        "프로그래밍 강사 채용",
        "클린 자동화 장비 기계 설계",
        "Machine Vision 설비 연동 SW개발자",
        "QA Engineer",
        "CBCT FW",
        "정보보안솔루션 경력개발자",
        "OutSystems Developer",
        "Windows Admin 서버 운영",
        "물리보안",
        "Network Engineer",
        "NPU Compiler Engineer",
        "Customer Success Lead",
        "AA",
        "AI 개발자",
    ]
    positive = [
        "AI/Cloud 개발 PM",
        "PM AI/Cloud 개발",
        "Cloud Project Manager",
        "Project Manager Cloud",
        "IT Project Manager",
        "Software Project Manager",
        "Software PM",
        "PM Software",
        "Project Manager Software",
        "Information Technology Project Manager",
        "소프트웨어 PMO 프로젝트 관리",
        "공공 SI프로젝트 시니어 PM",
        "Cloud/IT 기반 SI사업 제안/이행 PM/PL",
        "Cloud Infrastructure Construction Project Manager",
        "[건설플랫폼] Software Project Manager",
    ]
    negative = [
        "PM",
        "PM 모집",
        "AI Product Manager",
        "AI Product PM",
        "AI Product PO",
        "Cloud Product Manager",
        "프로덕트 매니저",
        "물리보안 PM",
        "Mechanical Project Manager",
        "건설 프로젝트 PM",
        "부동산 개발 PM",
        "retail PM",
        "AI Cloud PM 교육생 모집",
    ]
    generic = ["Project Manager", "프로젝트 관리자"]
    boundaries = [
        dict(id="boundary:" + title, fields=dict(title=title))
        for title in unchanged + positive + negative + generic
    ]
    pm_ids = {row["source_record_id"] for row in selection["all_61_grouped"]}
    real = [
        dict(id=row["source_record_id"], fields=row["fields"])
        for row in audit["rows"]
        if row["source_record_id"] in pm_ids
    ]
    assert len(real) == 61
    old = candidates(real + boundaries, False)
    new = candidates(real + boundaries, True)
    old_by = {row["id"]: row for row in old}
    new_by = {row["id"]: row for row in new}
    for title in unchanged:
        assert (
            old_by["boundary:" + title]["candidates"] == new_by["boundary:" + title]["candidates"]
        ), title
    for title in positive:
        assert "20010401" in {
            x["occupation_code"] for x in new_by["boundary:" + title]["candidates"]
        }, title
    for title in negative:
        before_scores = {
            x["occupation_code"]: x["retrieval_score"]
            for x in old_by["boundary:" + title]["candidates"]
        }
        after_scores = {
            x["occupation_code"]: x["retrieval_score"]
            for x in new_by["boundary:" + title]["candidates"]
        }
        assert after_scores.get("20010401", 0) <= before_scores.get("20010401", 0), title
    for title in generic:
        codes = {x["occupation_code"] for x in new_by["boundary:" + title]["candidates"]}
        assert "01010102" in codes, (title, codes)
    assert "20010401" not in {x["occupation_code"] for x in old_by["49550356"]["candidates"]}
    assert "20010401" in {x["occupation_code"] for x in new_by["49550356"]["candidates"]}

    # Explicit v3 records its true revision; historical prompt/provider/spend scope stays identical.
    v3_opts = v2_opts | dict(
        limit=1,
        max_requests=1,
        posting_ids=ids[1],
        execute_requests="Y",
        retrieval_revision=REVISION,
        daily_budget_usd=0.0055,
    )
    f.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('pm-new-v3',{f.quote(jobs)},{f.quote(NCS)},{f.js(v3_opts)})"
    )
    item = f.sql("SELECT item_id FROM enrichment.item WHERE batch_id='pm-new-v3'")
    attempt = f.sql("SELECT categorization_id FROM enrichment.item WHERE item_id=" + f.quote(item))
    request = json.loads(
        f.sql("SELECT request_body FROM enrichment.attempt WHERE attempt_id=" + f.quote(attempt))
    )
    assert (
        request["trace"]["release"] == "ko-metadata-occupation-v2"
        and "retrieval_revision" not in request["trace"]
    )
    assert (
        request["messages"][0]["content"]
        == f.sql(
            "SELECT system_prompt FROM enrichment.prompt WHERE version='ko-metadata-occupation-v2' AND stage='categorize'"
        )
        + "\n"
    )
    assert (
        f.sql("SELECT settings->>'metadata_scope' FROM enrichment.batch WHERE batch_id='pm-new-v3'")
        == "NCS_OCCUPATION_INFERENCE_V1"
    )
    assert (
        f.sql(
            "SELECT settings->>'retrieval_revision' FROM enrichment.batch WHERE batch_id='pm-new-v3'"
        )
        == REVISION
    )
    assert (
        f.sql(
            "SELECT old.cache_key<>new.cache_key AND old_binding.candidates_hash<>new_binding.candidates_hash FROM enrichment.attempt old JOIN enrichment.metadata_occupation_binding old_binding ON old_binding.item_id=old.item_id CROSS JOIN enrichment.attempt new JOIN enrichment.metadata_occupation_binding new_binding ON new_binding.item_id=new.item_id WHERE old.attempt_id="
            + f.quote(by_posting[ids[1]]["attempt_id"])
            + " AND new.attempt_id="
            + f.quote(attempt)
        )
        == "t"
    )
    f.sql("SELECT enrichment.reserve_request(" + f.quote(attempt) + ")")
    assert (
        f.sql("SELECT state FROM enrichment.attempt WHERE attempt_id=" + f.quote(attempt))
        == "BUDGET_BLOCKED"
    )
    assert f.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL") == "1"
    assert f.sql("SELECT count(*) FROM ingestion.request_attempt") == source_baseline

    groups = {row["source_record_id"]: row["group"] for row in selection["all_61_grouped"]}
    production = {row["source_record_id"]: row for row in audit["rows"]}
    changes: list[dict[str, Any]] = []
    for row in real:
        key = row["id"]
        before_codes = [x["occupation_code"] for x in production[key]["candidates"]]
        after_codes = [x["occupation_code"] for x in new_by[key]["candidates"]]
        changes.append(
            dict(
                source_record_id=key,
                group=groups[key],
                fields=row["fields"],
                posting_id=production[key]["posting_id"],
                before_binding_hash=production[key]["binding_hash"],
                before_frozen_candidates_hash=f.sql(
                    "SELECT enrichment.hash(jsonb_agg(jsonb_set(value,'{retrieval_score}',to_jsonb(round((value->>'retrieval_score')::numeric,3))) ORDER BY ordinal)::text) FROM jsonb_array_elements("
                    + f.js(production[key]["candidates"])
                    + ") WITH ORDINALITY x(value,ordinal)"
                ),
                before_offline_candidates_hash=old_by[key]["candidates_hash"],
                after_candidates_hash=new_by[key]["candidates_hash"],
                before_codes=before_codes,
                after_codes=after_codes,
                newly_offered_it_pm="20010401" not in before_codes and "20010401" in after_codes,
                candidate_changed=old_by[key]["candidates_hash"] != new_by[key]["candidates_hash"],
            )
        )
    report: dict[str, Any] = dict(
        status="PASSED_OFFLINE_PM_REVISION",
        occupations=1094,
        units=15520,
        affected_pm_abstentions=61,
        boundaries=len(boundaries),
        old_v1_v2_empty_null_replay=True,
        immutable_history_graph_binding=True,
        canonical_replays=2,
        revised_candidate_cache_hash=True,
        same_cumulative_budget_scope=True,
        status_precedence=True,
        source_requests=0,
        model_calls=0,
        correction_eligibility="Candidate coverage only; semantic abstention remains allowed.",
        clear_it_newly_covered=[
            row["source_record_id"]
            for row in changes
            if row["newly_offered_it_pm"]
            and row["group"] == "explicit_it_project_or_implementation"
        ],
        changed_cases=changes,
        sql_sha256=hashlib.sha256(
            (ROOT / "hop/llm/sql/034_metadata_occupation_pm.sql").read_bytes()
        ).hexdigest(),
    )
    args.receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "changed_cases"},
            ensure_ascii=False,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    context.checks = lambda: checks(args)
    context.main()


if __name__ == "__main__":
    main()
