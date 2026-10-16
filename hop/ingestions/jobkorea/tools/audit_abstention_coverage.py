#!/usr/bin/env python3
"""Read-only frozen metadata coverage export and offline diagnostic grouping.

No URL is opened, no provider API is called, and no production row is changed.
Only the explicit export command accesses PostgreSQL through docker exec/psql.
Diagnostic rules identify reasonable candidates to inspect, never match decisions.
All source projections and receipts are written outside Git with private modes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
JOBS = "jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c"
NCS = "ba32f673-255c-4990-80d4-8dbef6008e2f"
CONTRACT = "frozen-abstention-coverage-audit-v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quote(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value):
        raise ValueError("Only exact bounded snapshot identifiers are allowed")
    return "'" + value + "'"


def export_sql(jobs: str, ncs: str, *, counterfactual: bool = True) -> str:
    """One repeatable read snapshot; no preparing, planning, binding or capture."""
    j, n = quote(jobs), quote(ncs)
    candidates = (
        f"enrichment.metadata_occupation_candidates_v3({n},ib.source_data,12)"
        if counterfactual
        else "NULL::jsonb"
    )
    return f"""BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='1800s';
WITH latest AS MATERIALIZED (
 SELECT s.*,r.output FROM enrichment.metadata_occupation_status({j},{n}) s
 LEFT JOIN enrichment.metadata_occupation_result r USING(result_id)
), rows AS MATERIALIZED (
 SELECT ib.posting_id,ib.source_hash,ib.bundle_id,b.source_hash AS binding_source_hash,
 ib.manifest#>>'{{document,source_record_id}}' AS source_record_id,
 jsonb_strip_nulls(jsonb_build_object('title',ib.source_data->'title',
  'role',ib.source_data->'role','job_functions',ib.source_data->'job_functions'))
  AS raw_allowed_fields,
 enrichment.metadata_occupation_fields(ib.source_data) AS fields,
 s.item_id,s.result_id,s.decision,s.outcome AS derived_status,s.output,
 b.binding_hash,b.candidates AS frozen_candidates,
 {candidates} AS v3_candidates,
 batch.settings->>'candidate_limit' AS original_candidate_limit
 FROM latest s
 JOIN enrichment.metadata_occupation_binding b ON b.item_id=s.item_id
 JOIN enrichment.input_bundle ib ON ib.bundle_id=b.bundle_id
 JOIN enrichment.item item ON item.item_id=s.item_id
 JOIN enrichment.batch batch ON batch.batch_id=item.batch_id
 WHERE s.output->>'outcome'='abstained' AND ib.job_run_id={j}
)
SELECT jsonb_build_object(
 'contract','{CONTRACT}','captured_at',transaction_timestamp(),
 'read_only',current_setting('transaction_read_only'),'jobs',{j},'ncs',{n},
 'v3_candidate_limit',12,
 'counterfactual_recomputed',{"true" if counterfactual else "false"},
 'latest_ready_ncs',(SELECT run_id FROM ingestion.latest_ready_run
  WHERE source_id='ncs_competency'),
 'catalogue_context_hash',(SELECT min(catalog_context_hash)
  FROM enrichment.metadata_occupation_catalog_context WHERE ncs_run_id={n}),
 'v3_function_definition',pg_get_functiondef('enrichment.metadata_occupation_candidates_v3(text,jsonb,integer)'::regprocedure),
 'summary',(SELECT jsonb_build_object('postings',count(*),
   'matched',count(*) FILTER(WHERE output->>'outcome'='matched'),
   'abstained',count(*) FILTER(WHERE output->>'outcome'='abstained'),
   'no_valid_result',count(*) FILTER(WHERE output IS NULL),
   'semantic_rejections',count(*) FILTER(WHERE decision='REJECT')) FROM latest),
 'catalogue',(SELECT jsonb_agg(jsonb_build_object('occupation_code',c.occupation_code,
  'occupation_name',c.occupation_name,'unit_names',c.unit_names,'search_text',c.search_text,
  'classification_names',k.classification_names,'context_hash',k.context_hash)
  ORDER BY c.occupation_code) FROM enrichment.metadata_occupation_catalog c
  JOIN enrichment.metadata_occupation_catalog_context k USING(ncs_run_id,occupation_code)
  WHERE c.ncs_run_id={n}),
 'rows',(SELECT jsonb_agg(to_jsonb(rows) ORDER BY source_record_id,posting_id) FROM rows));
COMMIT;
"""


def private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise ValueError("Protected output directory must not be a symlink")
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
    path.chmod(0o600)


def write_json(path: Path, value: Any) -> None:
    private_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def export(
    container: str, output: Path, jobs: str, ncs: str, *, counterfactual: bool = True
) -> None:
    if not re.fullmatch(r"[0-9a-f]{12,64}", container):
        raise ValueError("An explicit PostgreSQL container identity is required")
    if output.resolve().is_relative_to(ROOT):
        raise ValueError("Raw source projections must stay outside the repository")
    helper_hash = digest(Path(__file__).read_bytes())
    migration_hash = digest((ROOT / "hop/llm/sql/034_metadata_occupation_pm.sql").read_bytes())
    sql = export_sql(jobs, ncs, counterfactual=counterfactual)
    private_write(output.with_suffix(".sql"), sql.encode())
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-X",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "jobtology",
        ],
        input=sql,
        text=True,
        capture_output=True,
        timeout=1900,
        check=False,
    )
    if result.returncode:
        private_write(output.with_suffix(".error.log"), result.stderr.encode())
        raise RuntimeError("Read-only export failed; see protected diagnostic alongside output")
    data = json.loads(result.stdout)
    validate_export(data)
    data["query_sha256"] = digest(sql.encode())
    data["helper_sha256_at_start"] = helper_hash
    data["sql034_sha256_at_start"] = migration_hash
    data["v3_function_sha256"] = digest(data.pop("v3_function_definition").encode())
    write_json(output, data)
    print(f"Saved protected read-only export: {len(data['rows'])} abstentions")


def validate_export(data: dict[str, Any]) -> None:
    if data.get("contract") != CONTRACT or data.get("read_only") != "on":
        raise ValueError("Input must be the explicit READ ONLY coverage export")
    rows = data["rows"]
    if len(rows) != data["summary"]["abstained"]:
        raise ValueError("Incomplete abstention coverage")
    if len({r["posting_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate frozen posting identity")
    if any(r["output"]["outcome"] != "abstained" for r in rows):
        raise ValueError("Audit scope must contain only latest abstentions")
    if any(set(r["fields"]) - {"title", "role", "job_functions"} for r in rows):
        raise ValueError("Unexpected model-facing field in audit projection")
    if any(
        "binding_source_hash" in r and r["source_hash"] != r["binding_source_hash"] for r in rows
    ):
        raise ValueError("Frozen source projection differs from the selected result binding")


def verify_bound_projection(baseline: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    """Verify an older projection against an independently exact-bound export.

    This supports the first long counterfactual query, executed before the export
    helper was tightened to join the selected binding's exact bundle identity.
    It does not reinterpret source values or silently repair a mismatched row.
    """
    validate_export(baseline)
    validate_export(comparison)
    for key in ("jobs", "ncs", "catalogue_context_hash"):
        if baseline[key] != comparison[key]:
            raise ValueError("Counterfactual projection changes a frozen snapshot identity")
    selected = {r["posting_id"]: r for r in baseline["rows"]}
    compared = {r["posting_id"]: r for r in comparison["rows"]}
    if set(selected) != set(compared):
        raise ValueError("Counterfactual scope differs from exact-bound baseline")
    keys = (
        "source_record_id",
        "source_hash",
        "fields",
        "raw_allowed_fields",
        "item_id",
        "result_id",
        "binding_hash",
        "frozen_candidates",
        "output",
        "original_candidate_limit",
    )
    for posting, row in compared.items():
        if any(row[key] != selected[posting][key] for key in keys):
            raise ValueError("Counterfactual evidence differs from exact-bound baseline")
        if "bundle_id" not in selected[posting] or "binding_source_hash" not in selected[posting]:
            raise ValueError(
                "Baseline must include selected bundle identity and binding source hash"
            )
    return {
        "verified": True,
        "rows": len(compared),
        "compared_fields": list(keys),
        "contract": "exact-bound-counterfactual-projection-verification-v1",
    }


def joined_fields(row: dict[str, Any]) -> str:
    return " ".join(str(value) for value in row["fields"].values()).lower()


def role_fields(row: dict[str, Any]) -> str:
    return " ".join(str(row["fields"].get(key, "")) for key in ("role", "title")).lower()


def matches(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def diagnostic_flags(row: dict[str, Any]) -> list[str]:
    """Overlapping reproducible flags; none constitutes reviewed source truth."""
    role = role_fields(row)
    flags = []
    if len(row["fields"]) == 1 and "title" in row["fields"]:
        flags.append("title_only")
    if not row["frozen_candidates"]:
        flags.append("no_frozen_candidates")
    if matches(
        r"교육생|수강생|훈련생|국비|부트캠프|취업지원|취업.?연계|무료.?교육|"
        r"course.?enrollment|training.?program",
        role,
    ):
        flags.append("course_or_employment_support_terms")
    if matches(
        r"전.?직군|전.?직무|다양한.?직군|각.?부문|각.?분야|부문별|분야별|"
        r"인재풀|인재.?pool|talent.?pool|상시.?인재",
        role,
    ):
        flags.append("broad_or_multiple_vacancy_terms")
    if matches(
        r"(^|[^a-z0-9])(pm|pmo)([^a-z0-9]|$)|project[ -]?(manager|management)|"
        r"프로젝트.{0,12}(관리|매니저|매니져)",
        role,
    ):
        flags.append("pm_terms")
    if matches(
        r"product[ -]?(manager|management|owner|pm|po)|프로덕트|제품.?매니저|"
        r"제품.?관리자|제품[ -]?(pm|po)",
        role,
    ):
        flags.append("product_management_terms")
    if matches(
        r"(^|[^a-z])(it|ict|ai|cloud|sap|erp|si|sw|software)([^a-z]|$)|"
        r"정보기술|정보시스템|클라우드|소프트웨어|시스템.?통합|인공지능|빅데이터",
        role,
    ):
        flags.append("explicit_it_scope_terms")
    if matches(r"(^|[^a-z])(mes|pos|data)([^a-z]|$)|시스템.?구축|시스템.?유지관리", role):
        flags.append("additional_pm_domain_vocabulary")
    if matches(
        r"영업|sales|account.?manager|business.?development|고객.?관리|customer.?success", role
    ):
        flags.append("sales_customer_terms")
    if matches(r"컨설턴트|컨설팅|consultant|consulting", role):
        flags.append("consulting_terms")
    if matches(r"개발|developer|programmer|software|프로그래머|engineer|엔지니어", role):
        flags.append("development_engineering_terms")
    if matches(r"기획|planner|planning|서비스.?운영|service.?operation|운영.?관리", role):
        flags.append("planning_operations_terms")
    if matches(
        r"연구|research|scientist|분석|analyst|data.?science|인공지능|"
        r"(^|[^a-z])ai([^a-z]|$)",
        role,
    ):
        flags.append("research_data_ai_terms")
    reason = str(row["output"].get("abstain_reason", "")).lower()
    if matches(r"candidate|shortlist|후보", reason):
        flags.append("model_reason_mentions_candidates")
    if matches(r"ambigu|insuff|generic|specific|unresolved|불명확|모호|부족|특정|명확", reason):
        flags.append("model_reason_mentions_uncertainty")
    if row["v3_candidates"] is not None and [
        c["occupation_code"] for c in row["frozen_candidates"]
    ] != [c["occupation_code"] for c in row["v3_candidates"]]:
        flags.append("v3_shortlist_changed")
    return flags


def primary_group(flags: list[str]) -> str:
    for flag in (
        "course_or_employment_support_terms",
        "broad_or_multiple_vacancy_terms",
        "product_management_terms",
        "pm_terms",
        "sales_customer_terms",
        "consulting_terms",
        "planning_operations_terms",
        "research_data_ai_terms",
        "development_engineering_terms",
    ):
        if flag in flags:
            return flag
    return "other_or_unspecified_role"


# Codes identify occupations that may deserve a place on a shortlist. They do
# not mean a vacancy has established the specialization or must receive a match.
FAMILY_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "llm_development_or_engineering": (
        r"\bllm\b|large[ -]?language[ -]?model|거대.?언어.?모델|대형.?언어.?모델",
        ("20010707", "20010703", "20010705"),
    ),
    "named_application_development_stack": (
        r"flutter|\bandroid\b|안드로이드|\bios\b|\baos\b|\bswift\b|\bkotlin\b|\bdart\b",
        ("20010202", "20010208"),
    ),
    "english_machine_learning_role": (
        r"(?:\bml\b|machine[ -]?learning).*(?:engineer|엔지니어|개발|researcher)|"
        r"(?:engineer|엔지니어|개발|researcher).*(?:\bml\b|machine[ -]?learning)",
        ("20010701", "20010703", "20010705"),
    ),
    "it_solution_sales": (
        r"(?:\bit\b|\bsw\b|\bs/w\b|software|소프트웨어|클라우드|보안.?솔루션|"
        r"it.?솔루션|정보.?보안).*(?:영업|\bsales\b)|(?:영업|\bsales\b).*"
        r"(?:\bit\b|\bsw\b|\bs/w\b|software|소프트웨어|클라우드|보안.?솔루션|"
        r"it.?솔루션|정보.?보안)",
        ("20010501",),
    ),
    "software_solution_technical_support": (
        r"(?:\bit\b|\bsw\b|소프트웨어|솔루션|보안|\bcloud\b|클라우드|정보시스템|전산).*"
        r"(?:기술.?지원|technical.?support)|(?:기술.?지원|technical.?support).*"
        r"(?:\bit\b|\bsw\b|소프트웨어|솔루션|보안|\bcloud\b|클라우드|정보시스템|전산)",
        ("20010303",),
    ),
    "site_reliability_engineer": (
        r"\bsre\b|site[ -]?reliability[ -]?engineer",
        ("20010301", "20010213", "20010215"),
    ),
    "ui_design_or_publishing": (
        r"\b(?:ui|ux)\b.*(?:디자인|디자이너|design)|(?:디자인|디자이너|design).*\b(?:ui|ux)\b",
        ("20010207", "08020104", "08020106"),
    ),
    "data_architect": (r"data[ -]?architect|데이터.?아키텍", ("20010211",)),
    "business_analyst": (
        r"business[ -]?analyst|비즈니스.?애널리스트",
        ("20010102", "20010103"),
    ),
}


def candidate_families(data: dict[str, Any]) -> dict[str, Any]:
    catalogue = {c["occupation_code"]: c for c in data["catalogue"]}
    result = {}
    for family, (pattern, codes) in FAMILY_RULES.items():
        if any(code not in catalogue for code in codes):
            raise ValueError(
                "Diagnostic family names an occupation absent from the frozen catalogue"
            )
        candidates = []
        for row in data["rows"]:
            field_evidence = [
                {"field": field, "text": value}
                for field, value in row["fields"].items()
                if matches(pattern, value.lower())
            ]
            if not field_evidence:
                continue
            original = [c["occupation_code"] for c in row["frozen_candidates"]]
            v3 = (
                None
                if row["v3_candidates"] is None
                else [c["occupation_code"] for c in row["v3_candidates"]]
            )
            candidates.append(
                {
                    "source_record_id": row["source_record_id"],
                    "posting_id": row["posting_id"],
                    "source_hash": row["source_hash"],
                    "field_evidence": field_evidence,
                    "frozen_candidate_codes": original,
                    "v3_candidate_codes": v3,
                    "frozen_missing_family_candidates": not bool(set(codes) & set(original)),
                    "v3_missing_family_candidates": None
                    if v3 is None
                    else not bool(set(codes) & set(v3)),
                    "flags": diagnostic_flags(row),
                    "model_abstain_reason": row["output"].get("abstain_reason"),
                    "review_status": "HEURISTIC_CANDIDATE_PLAUSIBILITY_UNREVIEWED",
                }
            )
        result[family] = {
            "signal_rows": len(candidates),
            "frozen_missing": sum(r["frozen_missing_family_candidates"] for r in candidates),
            "v3_missing": None
            if not data.get("counterfactual_recomputed", True)
            else sum(r["v3_missing_family_candidates"] for r in candidates),
            "reasonable_candidate_catalogue": [
                {
                    k: catalogue[code][k]
                    for k in ("occupation_code", "occupation_name", "unit_names", "context_hash")
                }
                for code in codes
            ],
            "review_status": "HEURISTIC_DIAGNOSTIC_UNREVIEWED",
            "rows": candidates,
        }
    return result


def audit(data: dict[str, Any], input_hash: str) -> dict[str, Any]:
    validate_export(data)
    rows = []
    flags_count: Counter[str] = Counter()
    groups_count: Counter[str] = Counter()
    for row in data["rows"]:
        flags = diagnostic_flags(row)
        group = primary_group(flags)
        flags_count.update(flags)
        groups_count.update([group])
        rows.append(
            {
                "source_record_id": row["source_record_id"],
                "posting_id": row["posting_id"],
                "source_hash": row["source_hash"],
                "group": group,
                "flags": flags,
                "review_status": "HEURISTIC_DIAGNOSTIC_UNREVIEWED",
            }
        )
    return {
        "contract": CONTRACT,
        "read_only": True,
        "input_sha256": input_hash,
        "audit_helper_sha256": digest(Path(__file__).read_bytes()),
        "created_at": datetime.now(UTC).isoformat(),
        "jobs": data["jobs"],
        "ncs": data["ncs"],
        "latest_ready_ncs_at_export": data["latest_ready_ncs"],
        "classification_contract": "Exclusive priority groups and overlapping literal-field flags; "
        "heuristic diagnostics, not reviewed occupation judgments or asserted candidate gaps. "
        "Model abstention reasons are diagnostic output, never source evidence.",
        "abstentions": len(rows),
        "group_counts": dict(groups_count),
        "flag_counts": dict(flags_count),
        "original_candidate_limits": dict(
            Counter(str(r["original_candidate_limit"]) for r in data["rows"])
        ),
        "catalogue_occupations": len(data["catalogue"]),
        "rows": rows,
        "counterfactual_recomputed": data.get("counterfactual_recomputed", True),
        "candidate_families": candidate_families(data),
        "production_writes": 0,
        "source_requests": 0,
        "paid_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("export")
    get.add_argument("--pg-container", required=True)
    get.add_argument("--output", required=True, type=Path)
    get.add_argument("--jobs", default=JOBS)
    get.add_argument("--ncs", default=NCS)
    get.add_argument("--skip-counterfactual", action="store_true")
    run = sub.add_parser("audit")
    run.add_argument("--input", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "export":
        export(
            args.pg_container,
            args.output,
            args.jobs,
            args.ncs,
            counterfactual=not args.skip_counterfactual,
        )
    else:
        if args.output.resolve().is_relative_to(ROOT):
            raise ValueError("Diagnostic row projections must stay outside the repository")
        raw = args.input.read_bytes()
        result = audit(json.loads(raw), digest(raw))
        write_json(args.output, result)
        print(
            json.dumps(
                {k: result[k] for k in ("abstentions", "group_counts", "flag_counts")},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
