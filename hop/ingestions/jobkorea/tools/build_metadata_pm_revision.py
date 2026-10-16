"""Generate additive034 PM retrieval and status correction; preserve029-033."""

# SQL source strings retain byte-exact historical definitions and literals.
# ruff: noqa: E501

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REVISION = "metadata-occupation-lexical-v3"


def function(source: str, name: str, language: str = "plpgsql") -> str:
    start = source.index("CREATE OR REPLACE FUNCTION enrichment." + name + "(")
    end = "END $$;" if language == "plpgsql" else "\n$$;"
    return source[start : source.index(end, start) + len(end)]


def build() -> str:
    baseline = (ROOT / "hop/llm/sql/033_metadata_occupation_roles.sql").read_text()
    catalog = function(baseline, "metadata_occupation_candidates")
    catalog = catalog.replace(
        "enrichment.metadata_occupation_candidates(",
        "enrichment.metadata_occupation_candidates_v3(",
        1,
    )
    old_pm = "   ('(sap|erp|정보기술|클라우드|software|소프트웨어).*(^|[^a-z])pm([^a-z]|$)|(sap|erp|정보기술|클라우드|software|소프트웨어).*프로젝트.*관리','it프로젝트'),\n"
    assert catalog.count(old_pm) == 1
    catalog = catalog.replace(old_pm, "")
    old = " ), terms AS MATERIALIZED ("
    new = r""" ), pm_signals AS (
  SELECT input.*,
   role_text ~ '(^|[^a-z0-9])(pm|pmo)([^a-z0-9]|$)|project[ -]?(manager|management)|프로젝트.{0,12}(관리|매니저|매니져)' AS project_role,
   role_text ~ 'project[ -]?(manager|management)|프로젝트.{0,12}(관리|매니저|매니져)|(^|[^a-z0-9])pmo([^a-z0-9]|$)' AS explicit_project_role,
   role_text ~ '(^|[^a-z0-9])(it|ict|ai|cloud|sap|erp|si|sw|software)([^a-z0-9]|$)|information[ -]?technology|s/w|정보기술|정보시스템|클라우드|소프트웨어|시스템.?통합|인공지능|빅데이터|웹.?개발|앱.?개발' AS it_scope,
   role_text ~ 'product[ -]?(manager|management|owner|pm|po)([^a-z0-9]|$)|프로덕트|제품.?매니저|제품.?관리자|제품[ -]?(pm|po)([^a-z0-9]|$)' AS product_role,
   role_text ~ '교육생|수강생|훈련생|국비.?지원|course.?enrollment|training.?program' AS course_ad
  FROM input
 ), pm_roles AS (
  -- Exact official occupations are retrieval candidates, never a model result.
  SELECT '20010401'::text AS occupation_code,'it프로젝트'::text AS term,2.5::numeric AS weight
  FROM pm_signals WHERE project_role AND it_scope AND NOT product_role AND NOT course_ad
  UNION ALL
  SELECT '01010102','프로젝트관리',2.5::numeric
  FROM pm_signals WHERE explicit_project_role AND NOT it_scope AND NOT product_role AND NOT course_ad
 ), terms AS MATERIALIZED ("""
    assert catalog.count(old) == 1
    catalog = catalog.replace(old, new)
    old = "  WHERE c.ncs_run_id=ncs\n ), frequency AS"
    new = """  WHERE c.ncs_run_id=ncs
  UNION ALL
  SELECT c.occupation_code,r.term,r.weight,8.0
  FROM enrichment.metadata_occupation_catalog c JOIN pm_roles r USING(occupation_code)
  WHERE c.ncs_run_id=ncs
 ), frequency AS"""
    assert catalog.count(old) == 1
    catalog = catalog.replace(old, new)

    planner = function(baseline, "plan_metadata_occupation_batch")
    old = "requested_prompt text:=coalesce(opts->>'prompt_version','ko-metadata-occupation-v1');"
    assert planner.count(old) == 1
    planner = planner.replace(
        old, old + " requested_retrieval text:=nullif(opts->>'retrieval_revision','');"
    )
    old = " IF requested_prompt NOT IN ('ko-metadata-occupation-v1','ko-metadata-occupation-v2') THEN RAISE EXCEPTION 'INVALID_METADATA_PROMPT_VERSION'; END IF;"
    assert planner.count(old) == 1
    planner = planner.replace(
        old,
        old
        + f"\n IF requested_retrieval IS NOT NULL AND requested_retrieval<>'{REVISION}' THEN RAISE EXCEPTION 'INVALID_METADATA_RETRIEVAL_REVISION'; END IF;\n IF requested_retrieval IS NULL THEN opts:=opts-'retrieval_revision'; END IF;",
    )
    old = "  candidates:=enrichment.metadata_occupation_candidates(n,source.source_data,(opts->>'candidate_limit')::integer);"
    assert planner.count(old) == 1
    planner = planner.replace(
        old,
        """  candidates:=CASE WHEN requested_retrieval IS NULL
   THEN enrichment.metadata_occupation_candidates(n,source.source_data,(opts->>'candidate_limit')::integer)
   ELSE enrichment.metadata_occupation_candidates_v3(n,source.source_data,(opts->>'candidate_limit')::integer) END;""",
    )
    old = "'retriever',CASE WHEN requested_prompt='ko-metadata-occupation-v1' THEN 'metadata-occupation-lexical-v1' ELSE 'metadata-occupation-lexical-v2' END"
    assert planner.count(old) == 1
    planner = planner.replace(
        old,
        "'retriever',coalesce(requested_retrieval,CASE WHEN requested_prompt='ko-metadata-occupation-v1' THEN 'metadata-occupation-lexical-v1' ELSE 'metadata-occupation-lexical-v2' END)",
    )
    status = function(
        (ROOT / "hop/llm/sql/029_metadata_occupation_links.sql").read_text(),
        "metadata_occupation_status",
        "sql",
    )
    old = "   WHEN d.decision IS NULL THEN 'REVIEW_PENDING'\n   WHEN r.output->>'outcome'='abstained' THEN 'ABSTAINED' ELSE 'ACCEPTED_INFERRED_OCCUPATION' END,"
    new = "   WHEN r.output->>'outcome'='abstained' THEN 'ABSTAINED'\n   WHEN d.decision IS NULL THEN 'REVIEW_PENDING' ELSE 'ACCEPTED_INFERRED_OCCUPATION' END,"
    assert status.count(old) == 1
    status = status.replace(old, new)
    return (
        "-- Generated by tools/build_metadata_pm_revision.py; additive034, old retrieval/history unchanged.\nBEGIN;\n\n"
        + catalog
        + "\n\n"
        + planner
        + "\n\n"
        + status
        + "\nCOMMIT;\n"
    )


if __name__ == "__main__":
    (ROOT / "hop/llm/sql/034_metadata_occupation_pm.sql").write_text(build())
