"""Network-none role retrieval and immutable v1/v2 history regression.

Consumes a protected corpus of local whitelisted fields and accepted NCS facts.
This test never opens a provider connection or a production database.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import jobkorea_linking as fixture

f: Any = fixture
ROOT = Path(__file__).resolve().parents[3]


def history() -> str:
    return f.sql(
        "SELECT jsonb_build_object("
        + ",".join(
            f"'{table}',(SELECT enrichment.hash(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')::text) FROM enrichment.{table} t)"
            for table in [
                "metadata_occupation_catalog",
                "metadata_occupation_binding",
                "metadata_occupation_result",
                "metadata_occupation_candidate",
                "metadata_occupation_decision",
                "item",
                "attempt",
                "batch",
            ]
        )
        + ", 'v1_prompt',(SELECT enrichment.hash(to_jsonb(p)::text) FROM enrichment.prompt p WHERE version='ko-metadata-occupation-v1' AND stage='categorize'))"
    )


def shortlist(ncs: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(
        f.sql(
            "SELECT jsonb_agg(jsonb_build_object('id',r.value->>'id','fields',r.value->'fields','candidates',enrichment.metadata_occupation_candidates("
            + f.quote(ncs)
            + ",r.value->'fields',12)) ORDER BY ordinal) FROM jsonb_array_elements("
            + f.js(rows)
            + ") WITH ORDINALITY r(value,ordinal)"
        )
    )


def checks(corpus: Path, receipt: Path) -> None:
    source_attempt_baseline = f.sql("SELECT count(*) FROM ingestion.request_attempt")
    units = json.loads((corpus / "local_ncs_units.json").read_text())
    paid = json.loads((corpus / "paid65_fields_outputs.json").read_text())
    calibration = json.loads((corpus / "calibration121_fields.json").read_text())
    assert len(paid) == 65 and len(calibration) == 121
    ncs = "roles-ncs-fixture"
    f.sql(
        "INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES('roles-ncs-fixture','ncs_competency','REPLAY','LOCAL_READ_ONLY_CALIBRATION','READY'); INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size) VALUES('roles-ncs-fixture','roles','FILE',15520); INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,selected) VALUES('roles-ncs-fixture','roles','roles',1,'local-db-fixture',repeat('0',64),0,'UTF-8',200,clock_timestamp(),true);"
    )
    f.sql(
        "UPDATE ingestion.partition SET expected_total=15520 WHERE run_id='roles-ncs-fixture'; UPDATE ingestion.document SET byte_length=1,declared_total=15520,effective_page=1,effective_page_size=15520,item_count=15520,verified_at=clock_timestamp() WHERE run_id='roles-ncs-fixture';"
    )
    f.sql(
        "INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) SELECT 'roles-ncs-fixture','roles',ordinal::text,value->>'code','{}',value FROM jsonb_array_elements("
        + f.js(units)
        + ") WITH ORDINALITY x(value,ordinal)"
    )
    catalog = json.loads(
        f.sql(f"SELECT enrichment.prepare_metadata_occupation_catalog({f.quote(ncs)})")
    )
    assert catalog["occupation_count"] == 1094
    source_rows = []
    for index, row in enumerate(paid):
        fields = row["fields"]
        source_rows.append(
            dict(
                product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/"
                + str(93000000 + index),
                company_name="Synthetic corpus fixture",
                job_title=fields.get("title", ""),
                job_position=fields.get("role", ""),
                job_functions=fields.get("job_functions", ""),
            )
        )
    body = json.dumps(source_rows, ensure_ascii=False)
    sha = hashlib.sha256(body.encode()).hexdigest()
    jobs = f.sql(
        f"SELECT run_id FROM ingestion.begin_jobkorea_import({f.quote(sha)},{len(body.encode())},'jobkorea/'||{f.quote(sha)}||'/source.json',clock_timestamp())"
    )
    f.sql(
        f"SELECT * FROM ingestion.load_jobkorea_document({f.quote(jobs)},{f.quote(body)}); SELECT ingestion.verify_jobkorea_file({f.quote(jobs)},{f.quote(sha)},{len(body.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({f.quote(jobs)}); SELECT enrichment.prepare_jobkorea_input_bundle({f.quote(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={f.quote(jobs)};"
    )
    ids = [
        "ext-jobkorea-" + hashlib.sha256(str(93000000 + index).encode()).hexdigest()
        for index in range(len(paid))
    ]
    by_id = dict(zip(ids, paid, strict=True))
    opts = dict(
        categorize_model="openai/gpt-5.6-luna",
        provider_only="openai",
        extra_params={},
        limit=65,
        candidate_limit=12,
        max_matches=1,
        max_input_chars=16000,
        max_output_tokens=768,
        max_requests=65,
        request_reserve_usd=0.005,
        max_cost_usd=0.05,
        daily_budget_usd=4.75,
        request_delay_ms=0,
        read_timeout_ms=5000,
        execute_requests="N",
        reuse_cache="Y",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        reasoning_effort="none",
        posting_ids="|".join(ids),
    )
    old_plan = json.loads(
        f.sql(
            f"SELECT enrichment.plan_metadata_occupation_batch('roles-old65',{f.quote(jobs)},{f.quote(ncs)},{f.js(opts)})"
        )
    )
    assert old_plan["postings"] == 65
    items = json.loads(
        f.sql(
            "SELECT jsonb_agg(jsonb_build_object('item_id',i.item_id,'posting_id',i.posting_id,'attempt_id',i.categorization_id,'source',enrichment.metadata_occupation_fields(i.source_data),'candidates',b.candidates) ORDER BY i.ordinal) FROM enrichment.item i JOIN enrichment.metadata_occupation_binding b USING(item_id) WHERE i.batch_id='roles-old65'"
        )
    )
    actual_replayed = 0
    for item in items:
        output = by_id[item["posting_id"]]["output"]
        assert item["source"] == by_id[item["posting_id"]]["fields"], (
            item["source"],
            by_id[item["posting_id"]]["fields"],
        )
        issues = json.loads(
            f.sql(
                f"SELECT enrichment.metadata_occupation_output_issues({f.js(output)},{f.js(item['source'])},{f.js(item['candidates'])},1)"
            )
        )
        if issues:
            # Catalog contexts before the first five production requests differ.
            # Preserve a valid old offline result rather than forging its bound choices.
            output = dict(
                outcome="abstained",
                matches=[],
                abstain_reason="Offline history fixture has a different exact bound shortlist.",
            )
        else:
            actual_replayed += 1
        f.sql(
            f"UPDATE enrichment.attempt SET state='VALIDATED',parsed_output={f.js(output)},actual_model='openai/gpt-5.6-luna',cost_usd=0.00021,reserved_at=clock_timestamp(),completed_at=clock_timestamp() WHERE attempt_id={f.quote(item['attempt_id'])}; SELECT enrichment.capture_metadata_occupation_result({f.quote(item['item_id'])},'offline-fixture'); UPDATE enrichment.item SET state='VALIDATED' WHERE item_id={f.quote(item['item_id'])};"
        )
    assert f.sql("SELECT count(*) FROM enrichment.metadata_occupation_result") == "65"
    before = history()
    corpus_rows = [
        dict(id=row["batch_id"] + ":" + str(row["ordinal"]), fields=row["fields"]) for row in paid
    ] + [dict(id="sample:" + row["posting_id"], fields=row["fields"]) for row in calibration]
    boundaries = [
        dict(id="boundary:" + title, fields=dict(title=title))
        for title in [
            "Cyber Threat Analyst",
            "[유명 SCM전문컨설팅회사] Data Scientist",
            "SKT차세대개발 java 통신사",
            "프로그래밍 강사 채용",
            "클린 자동화 장비 기계 설계",
            "Machine Vision 설비 연동 SW개발자",
            "QA Engineer",
            "CBCT FW",
            "정보보안솔루션 경력개발자",
            "SAP Public Cloud PM/컨설턴트",
            "OutSystems 개발자",
            "OutSystems Developer",
            "공공기관 사이트 운영 개발자",
            "Windows Admin 서버 운영",
            "포탈 시스템 운영 유지보수",
            "물리보안",
            "Network Engineer",
            "NPU Compiler Engineer",
            "Customer Success Lead",
            "AA",
            "AI 개발자",
        ]
    ]
    started = time.monotonic()
    old = shortlist(ncs, corpus_rows + boundaries)
    f.install("hop/llm/sql/033_metadata_occupation_roles.sql")
    assert history() == before
    for version_opts in (opts, opts | dict(prompt_version="ko-metadata-occupation-v1")):
        assert json.loads(
            f.sql(
                f"SELECT enrichment.plan_metadata_occupation_batch('roles-old65',{f.quote(jobs)},{f.quote(ncs)},{f.js(version_opts)})"
            )
        )["replay"]
        assert history() == before
    for item in items:
        f.sql(
            f"SELECT enrichment.bind_metadata_occupation_item(item_id,bundle_id,candidates) FROM enrichment.metadata_occupation_binding WHERE item_id={f.quote(item['item_id'])}; SELECT enrichment.capture_metadata_occupation_result({f.quote(item['item_id'])},'offline-fixture')"
        )
    assert history() == before
    for _ in range(2):
        for number in [
            "029_metadata_occupation_links.sql",
            "030_metadata_occupation_native.sql",
            "031_metadata_occupation_workers.sql",
            "032_metadata_occupation_context.sql",
            "033_metadata_occupation_roles.sql",
        ]:
            f.install("hop/llm/sql/" + number)
        assert history() == before
    new = shortlist(ncs, corpus_rows + boundaries)
    receipt.with_name("candidate_comparison.json").write_text(
        json.dumps(dict(old=old, new=new), ensure_ascii=False, indent=2)
    )
    expected = {
        "CBCT FW": {"20010203", "15030104"},
        "QA Engineer": {"20010402", "20010403"},
        "정보보안솔루션 경력개발자": {"20010202"},
        "SAP Public Cloud PM/컨설턴트": {"20010102", "20010401"},
        "OutSystems 개발자": {"20010202"},
        "OutSystems Developer": {"20010202"},
        "공공기관 사이트 운영 개발자": {"20010202"},
        "Windows Admin 서버 운영": {"20010301"},
        "포탈 시스템 운영 유지보수": {"20010301"},
        "물리보안": {"11010101"},
        "Network Engineer": {"20010205"},
        "NPU Compiler Engineer": {"20010208"},
        "Cyber Threat Analyst": {"20010603"},
        "[유명 SCM전문컨설팅회사] Data Scientist": {"20010105"},
        "SKT차세대개발 java 통신사": {"20010202"},
        "프로그래밍 강사 채용": {"20010302"},
        "클린 자동화 장비 기계 설계": {"15010201"},
        "Machine Vision 설비 연동 SW개발자": {"20010202"},
    }
    for row in new:
        if row["id"].startswith("boundary:") and row["id"][9:] in expected:
            codes = {c["occupation_code"] for c in row["candidates"]}
            assert expected[row["id"][9:]] <= codes, (
                row["id"],
                sorted(codes),
                sorted(expected[row["id"][9:]]),
            )
    actual_expected = {
        ("metadata-paid-workers4-20261008-0908", 4): {"20010203", "15030104"},
        ("metadata-paid-workers4-20261008-0908", 9): {"20010202"},
        ("metadata-paid-workers4-20261008-0908", 11): {"20010102", "20010401"},
        ("metadata-paid-workers4-20261008-0908", 13): {"20010402", "20010403"},
        ("metadata-paid-workers8-20261008-0910", 6): {"20010202"},
        ("metadata-paid-workers8-20261008-0910", 17): {"20010202"},
        ("metadata-paid-workers8-20261008-0910", 22): {"20010301"},
        ("metadata-paid-workers8-20261008-0910", 31): {"20010301"},
        ("metadata-paid-workers8-20261008-0910", 16): {"11010101"},
        ("metadata-paid-workers8-20261008-0910", 19): {"20010205"},
        ("metadata-paid-workers8-20261008-0910", 20): {"20010208"},
    }
    new_by_id = {row["id"]: row for row in new}
    for (batch, ordinal), expected_codes in actual_expected.items():
        row = new_by_id[batch + ":" + str(ordinal)]
        assert expected_codes <= {c["occupation_code"] for c in row["candidates"]}, (
            row["id"],
            row["fields"],
            row["candidates"],
        )
    f.reject(
        f"SELECT enrichment.plan_metadata_occupation_batch('roles-bad',{f.quote(jobs)},{f.quote(ncs)},{f.js(opts | dict(prompt_version='mutable'))})",
        "INVALID_METADATA_PROMPT_VERSION",
    )
    default = json.loads(
        f.sql(
            f"SELECT enrichment.plan_metadata_occupation_batch('roles-default-skip',{f.quote(jobs)},{f.quote(ncs)},{f.js({k: v for k, v in (opts | dict(prompt_version='ko-metadata-occupation-v2')).items() if k != 'posting_ids'})})"
        )
    )
    assert default["postings"] == 0
    one = opts | dict(
        prompt_version="ko-metadata-occupation-v2", posting_ids=ids[0], limit=1, max_requests=1
    )
    f.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('roles-v2-explicit',{f.quote(jobs)},{f.quote(ncs)},{f.js(one)})"
    )
    assert (
        f.sql(
            "SELECT settings->>'metadata_scope' FROM enrichment.batch WHERE batch_id='roles-v2-explicit'"
        )
        == "NCS_OCCUPATION_INFERENCE_V1"
    )
    assert (
        f.sql(
            "SELECT request_body#>>'{messages,0,content}'=(SELECT system_prompt FROM enrichment.prompt WHERE version='ko-metadata-occupation-v2' AND stage='categorize') FROM enrichment.attempt WHERE batch_id='roles-v2-explicit'"
        )
        == "t"
    )
    assert (
        f.sql(
            "SELECT count(*) FROM enrichment.attempt WHERE batch_id='roles-v2-explicit' AND cache_key IN(SELECT cache_key FROM enrichment.attempt WHERE batch_id='roles-old65')"
        )
        == "0"
    )
    assert f.sql("SELECT count(*) FROM ingestion.request_attempt") == source_attempt_baseline
    assert f.sql("SELECT count(*) FROM ingestion.request_attempt WHERE source_id='jobkorea'") == "0"
    report = dict(
        status="PASSED_OFFLINE_ROLE_RETRIEVAL_HISTORY",
        unit_count=len(units),
        occupation_count=catalog["occupation_count"],
        paid_fieldsets=65,
        calibration_fieldsets=121,
        boundary_fieldsets=len(boundaries),
        preserved_offline_results=65,
        exact_old_outputs_revalidated=actual_replayed,
        production_hash_receipt=str(corpus / "production65_before_hashes.json"),
        v1_omitted_and_explicit_replay=True,
        canonical_replay_count=2,
        v2_explicit_retry=True,
        charged_default_skip=True,
        external_requests=0,
        provider_requests=0,
        elapsed_seconds=round(time.monotonic() - started, 3),
        zero_shortlists_before=sum(not r["candidates"] for r in old),
        zero_shortlists_after=sum(not r["candidates"] for r in new),
        observed_gap_coverage=[
            dict(
                id=b + ":" + str(o),
                expected_codes=sorted(c),
                candidates=[
                    dict(code=x["occupation_code"], name=x["occupation_name"])
                    for x in new_by_id[b + ":" + str(o)]["candidates"]
                ],
            )
            for (b, o), c in actual_expected.items()
        ],
        old_shortlists=old,
        new_shortlists=new,
    )
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    os.chmod(receipt, 0o600)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ["old_shortlists", "new_shortlists", "observed_gap_coverage"]
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        f.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                "none",
                "--name",
                f.NAME,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine"),
            ]
        )
        for _ in range(100):
            try:
                if (
                    "PostgreSQL init process complete" in f.command(["docker", "logs", f.NAME])
                    and f.sql("SELECT 1") == "1"
                ):
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        f.install("docs/hop-migration/schema.sql")
        f.install("docs/hop-migration/checks.sql")
        f.sql(f.FIXTURE)
        f.install("docs/hop-migration/operations.sql")
        f.install("hop/llm/sql/001_schema.sql")
        f.install("hop/retention/sql/001_retention.sql")
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "027":
                f.sql(path.read_text())
        f.install("hop/cs/sql/001_common_postings.sql")
        for path in sorted((ROOT / "hop/ingestions/jobkorea/sql").glob("*.sql")):
            f.sql(path.read_text())
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            if path.name < "033":
                f.sql(path.read_text())
        checks(args.corpus_dir, args.receipt)
    finally:
        f.command(["docker", "rm", "-f", f.NAME])


if __name__ == "__main__":
    main()
