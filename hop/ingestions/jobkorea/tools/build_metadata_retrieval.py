# ruff: noqa: E501
"""Generate additive033 retrieval/prompt selection; never rewrite030 or v1 prompt."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

ROLE_ALIASES = r"""
  UNION ALL
  SELECT term,2.5::numeric FROM input CROSS JOIN LATERAL (VALUES
   ('(^|[^a-z0-9])(fw|firmware)([^a-z0-9]|$)|펌웨어','임베디드'),
   ('(^|[^a-z0-9])(fw|firmware)([^a-z0-9]|$)|펌웨어','펌웨어'),
   ('(^|[^a-z0-9])qa([^a-z0-9]|$)|quality.?assurance|품질.?보증','품질보증'),
   ('(^|[^a-z0-9])qa([^a-z0-9]|$)|quality.?assurance|품질.?보증','품질관리'),
   ('(^|[^a-z0-9])qa([^a-z0-9]|$)|software.?test|test.?engineer|소프트웨어.?테스트|테스트.?엔지니어|테스터','it테스트'),
   ('(outsystems|아웃시스템즈).*(개발|developer|development)|(개발|developer|development).*(outsystems|아웃시스템즈)|사이트.*개발|개발.*사이트|정보보안.*개발자','응용sw'),
   ('(windows|linux|서버|포탈|포털|전산|네트워크).*(admin|운영|관리|유지보수)|(admin|운영|관리|유지보수).*(windows|linux|서버|포탈|포털|전산|네트워크)|sysadmin|system.?administrator|시스템.?관리자','it시스템'),
   ('(sap|erp|정보기술|클라우드|software|소프트웨어).*(컨설턴트|컨설팅|consultant|consulting)|(컨설턴트|컨설팅|consultant|consulting).*(sap|erp|정보기술|클라우드|software|소프트웨어)','정보기술컨설팅'),
   ('(sap|erp|정보기술|클라우드|software|소프트웨어).*(^|[^a-z])pm([^a-z]|$)|(sap|erp|정보기술|클라우드|software|소프트웨어).*프로젝트.*관리','it프로젝트'),
   ('(네트워크|network).*(엔지니어|engineer)|(엔지니어|engineer).*(네트워크|network)','nw엔지니어링'),
   ('compiler|컴파일러','시스템sw'),
   ('compiler|컴파일러','컴파일러'),
   ('(물리.?보안|physical.?security|경비)','경비'),
   ('customer.?success|고객.?성공','고객관리'),
   ('customer.?success|고객.?성공','영업')
  ) roles(pattern,term) WHERE input.role_text ~ roles.pattern
"""


def function(source, name):
    start = source.index("CREATE OR REPLACE FUNCTION enrichment." + name + "(")
    return source[start : source.index("END $$;", start) + len("END $$;")]


def build():
    context = (ROOT / "hop/llm/sql/032_metadata_occupation_context.sql").read_text()
    native = (ROOT / "hop/llm/sql/030_metadata_occupation_native.sql").read_text()
    candidates = function(context, "metadata_occupation_candidates")
    before = "WITH input AS (SELECT lower(string_agg(value,' ' ORDER BY key)) AS text\n  FROM jsonb_each_text(enrichment.metadata_occupation_fields(source))),"
    after = """WITH input AS (SELECT
  lower((SELECT string_agg(value,' ' ORDER BY key) FROM jsonb_each_text(fields))) AS text,
  lower(concat_ws(' ',fields->>'role',fields->>'title')) AS role_text
  FROM (SELECT enrichment.metadata_occupation_fields(source) AS fields) f),"""
    assert before in candidates
    candidates = candidates.replace(before, after)
    candidates = candidates.replace(
        "'developer','engineer','junior','senior'",
        "'developer','engineer','engineering','junior','senior'",
    )
    before = ") x(pattern,term) WHERE input.text ~ x.pattern\n ), terms AS MATERIALIZED"
    after = (
        ") x(pattern,term) WHERE input.text ~ x.pattern\n  AND NOT(x.term='정보보호' AND input.role_text ~ '(물리.?보안|physical.?security)'\n   AND input.role_text !~ '(정보.?보안|정보.?보호|(^|[^a-z])it([^a-z]|$)|cyber|시스템|네트워크|클라우드)')\n"
        + ROLE_ALIASES
        + " ), terms AS MATERIALIZED"
    )
    assert before in candidates
    candidates = candidates.replace(before, after)

    binding = function(context, "bind_metadata_occupation_item")
    before = "b.settings->>'prompt_version' IS DISTINCT FROM 'ko-metadata-occupation-v1'"
    assert before in binding
    binding = binding.replace(
        before,
        "coalesce(b.settings->>'prompt_version','') NOT IN ('ko-metadata-occupation-v1','ko-metadata-occupation-v2')",
    )

    planner = function(native, "plan_metadata_occupation_batch")
    before = "ordinal integer:=0; catalog jsonb;"
    assert before in planner
    planner = planner.replace(
        before,
        "ordinal integer:=0; catalog jsonb; requested_prompt text:=coalesce(opts->>'prompt_version','ko-metadata-occupation-v1');",
    )
    planner = planner.replace(
        " PERFORM retention.gate();",
        " PERFORM retention.gate();\n IF requested_prompt NOT IN ('ko-metadata-occupation-v1','ko-metadata-occupation-v2') THEN RAISE EXCEPTION 'INVALID_METADATA_PROMPT_VERSION'; END IF;",
        1,
    )
    planner = planner.replace(
        "'metadata_scope','NCS_OCCUPATION_INFERENCE_V1','prompt_version','ko-metadata-occupation-v1'",
        "'metadata_scope','NCS_OCCUPATION_INFERENCE_V1','prompt_version',requested_prompt",
    )
    planner = planner.replace(
        "WHERE version='ko-metadata-occupation-v1'", "WHERE version=requested_prompt"
    )
    planner = planner.replace(
        "FROM enrichment.batch WHERE batch_id=id AND job_run_id=j AND ncs_run_id=n AND settings=plan_metadata_occupation_batch.settings",
        "FROM enrichment.batch existing WHERE existing.batch_id=id AND existing.job_run_id=j AND existing.ncs_run_id=n AND existing.settings=plan_settings",
    )
    planner = planner.replace("settings jsonb", "plan_settings jsonb")
    planner = planner.replace("settings:=opts", "plan_settings:=opts")
    planner = planner.replace("VALUES(id,'ENRICH',j,n,nh,settings,CASE", "VALUES(id,'ENRICH',j,n,nh,plan_settings,CASE")
    planner = planner.replace("'release','ko-metadata-occupation-v1'", "'release',requested_prompt")
    planner = planner.replace(
        "'retriever','metadata-occupation-lexical-v1'",
        "'retriever',CASE WHEN requested_prompt='ko-metadata-occupation-v1' THEN 'metadata-occupation-lexical-v1' ELSE 'metadata-occupation-lexical-v2' END",
    )

    prompt = (ROOT / "hop/llm/prompts/categorize-ko-metadata-occupation-v2.txt").read_text()
    schema = json.loads(
        (ROOT / "hop/llm/prompts/categorize-ko-metadata-occupation-v2.schema.json").read_text()
    )
    encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256((prompt + "\n" + encoded).encode()).hexdigest()
    text = "-- Generated by tools/build_metadata_retrieval.py; additive033, immutable old inputs/results.\nBEGIN;\n"
    text += "INSERT INTO enrichment.prompt(version,stage,system_prompt,output_schema,content_hash) VALUES\n"
    text += (
        "('ko-metadata-occupation-v2','categorize',$metadata_prompt$"
        + prompt
        + "$metadata_prompt$,$metadata_schema$"
        + encoded
        + "$metadata_schema$::jsonb,'"
        + digest
        + "') ON CONFLICT(version,stage) DO NOTHING;\n"
    )
    text += (
        "DO $identity$ BEGIN IF NOT EXISTS(SELECT 1 FROM enrichment.prompt WHERE version='ko-metadata-occupation-v2' AND stage='categorize' AND system_prompt=$metadata_prompt$"
        + prompt
        + "$metadata_prompt$ AND output_schema=$metadata_schema$"
        + encoded
        + "$metadata_schema$::jsonb AND content_hash='"
        + digest
        + "') THEN RAISE EXCEPTION 'METADATA_PROMPT_VERSION_IS_IMMUTABLE'; END IF; END $identity$;\n"
    )
    text += "\n" + candidates + "\n\n" + binding + "\n\n" + planner + "\nCOMMIT;\n"
    (ROOT / "hop/llm/sql/033_metadata_occupation_roles.sql").write_text(text)


if __name__ == "__main__":
    build()
