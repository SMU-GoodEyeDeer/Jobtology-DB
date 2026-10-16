"""Generate additive, bag-preserving entity fact worksets from sealed SQL008.

Retain every posting group before joining it to the chosen entity facts. The
conditional merge has exactly the former JOB-ALIO/Nara eligibility and fallback
rules, without reducing the join input to a badly estimated filtered workset.
Independent DISTINCT ON selections retain each complete winner ordering without
the cardinality collapse caused by filtering two row_number columns to one.
"""

# SQL replacement literals retain sealed formatting for review.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "hop/graph/sql/008_reader_worksets.sql"
OUTPUT = ROOT / "hop/graph/sql/009_reader_fact_worksets.sql"
SOURCE_SHA256 = "f1b71d6bce9f2b59d61b9c3122a81954f24db312de77c7b830bb9aa55676a645"
NAMES = ("graph_source_entities",)


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("Sealed SQL008 reader replacement contract changed: " + before[:80])
    return source.replace(before, after)


def definition(source: str, name: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION ingestion." + name + "(")
    return source[start : source.index("$$;", start) + 3]


def body(function: str) -> str:
    return function.split("AS $$", 1)[1].rsplit("$$;", 1)[0]


def candidate(source: str, name: str) -> str:
    if name not in NAMES:
        raise ValueError("Unsupported reader fact workset: " + name)
    result = definition(source, name)
    result = replace_once(
        result,
        " job_facts AS MATERIALIZED(SELECT p.run_id,p.posting_id,\n"
        " ((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail'))-'representation' AS normalized\n"
        " FROM posting_sets p WHERE p.source_id='job_alio' AND p.forms ?& ARRAY['list','detail']),\n"
        " nara_facts AS MATERIALIZED(SELECT p.run_id,p.posting_id,\n"
        " ((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail')||jsonb_strip_nulls(p.forms->'positions')||jsonb_strip_nulls(p.forms->'files'))-'representation' AS normalized\n"
        " FROM posting_sets p WHERE p.source_id='nara_job' AND p.forms ?& ARRAY['list','detail','positions','files']\n"
        " AND coalesce((p.forms->'list'->>'ongoing')::boolean,false))",
        " posting_facts AS MATERIALIZED(SELECT p.run_id,p.source_id,p.posting_id,\n"
        " CASE WHEN p.source_id='job_alio' AND p.forms ?& ARRAY['list','detail'] THEN\n"
        "  ((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail'))-'representation'\n"
        " WHEN p.source_id='nara_job' AND p.forms ?& ARRAY['list','detail','positions','files']\n"
        " AND coalesce((p.forms->'list'->>'ongoing')::boolean,false) THEN\n"
        "  ((p.forms->'list')||jsonb_strip_nulls(p.forms->'detail')||jsonb_strip_nulls(p.forms->'positions')||jsonb_strip_nulls(p.forms->'files'))-'representation'\n"
        " END AS normalized FROM posting_sets p)",
    )
    result = replace_once(
        result,
        " LEFT JOIN job_facts j ON j.run_id=f.run_id AND j.posting_id=f.posting_id\n"
        " LEFT JOIN nara_facts k ON k.run_id=f.run_id AND k.posting_id=f.posting_id",
        " LEFT JOIN posting_facts p ON p.run_id=f.run_id AND p.source_id=f.source_id\n"
        " AND p.posting_id=f.posting_id",
    )
    result = replace_once(result, "coalesce(j.normalized,f.normalized)", "coalesce(p.normalized,f.normalized)")
    result = replace_once(result, "coalesce(k.normalized,f.normalized)", "coalesce(p.normalized,f.normalized)")
    return distinct_winners(result)


def distinct_winners(function: str) -> str:
    """Keep the same independent winner orderings without choice filters."""
    function = replace_once(
        function,
        " facts AS MATERIALIZED(SELECT c.*,row_number() OVER(PARTITION BY c.identity_id ORDER BY owner_priority,\n"
        " created_at DESC,c.run_id DESC,CASE WHEN normalized->>'representation'='detail' THEN 0 ELSE 1 END,\n"
        " numeric_record_id DESC,c.record_id DESC) AS choice FROM candidates c),",
        " facts AS MATERIALIZED(SELECT DISTINCT ON(c.identity_id) c.* FROM candidates c\n"
        " ORDER BY c.identity_id,owner_priority,created_at DESC,c.run_id DESC,\n"
        " CASE WHEN normalized->>'representation'='detail' THEN 0 ELSE 1 END,\n"
        " numeric_record_id DESC,c.record_id DESC),",
    )
    function = replace_once(
        function,
        " names AS(SELECT c.*,row_number() OVER(PARTITION BY c.identity_id ORDER BY\n"
        " (nullif(btrim(proposed_name),'') IS NULL),name_priority,created_at DESC,c.run_id DESC,\n"
        " CASE WHEN normalized->>'representation'='detail' THEN 0 ELSE 1 END,\n"
        " numeric_record_id DESC,c.record_id DESC) AS choice FROM candidates c),",
        " names AS(SELECT DISTINCT ON(c.identity_id) c.* FROM candidates c\n"
        " ORDER BY c.identity_id,(nullif(btrim(proposed_name),'') IS NULL),name_priority,created_at DESC,c.run_id DESC,\n"
        " CASE WHEN normalized->>'representation'='detail' THEN 0 ELSE 1 END,\n"
        " numeric_record_id DESC,c.record_id DESC),",
    )
    function = replace_once(
        function,
        "current_facts AS MATERIALIZED(SELECT f.*,f.normalized->>'posting_id' AS posting_id FROM facts f WHERE choice=1)",
        "current_facts AS MATERIALIZED(SELECT f.*,f.normalized->>'posting_id' AS posting_id FROM facts f)",
    )
    return replace_once(function, " WHERE n.choice=1 ORDER BY f.identity_id;", " ORDER BY f.identity_id;")


def guard(source: str, name: str, new: str) -> str:
    old = definition(source, name)
    volatility = "s" if "LANGUAGE plpgsql STABLE" in old else "v"
    fields = old.split("RETURNS TABLE(", 1)[1].split(")", 1)[0]
    names = [field.strip().split()[0] for field in fields.replace("\n", "").split(",")]
    all_names = ["jobs", *names]
    types = ",".join("25" for _ in all_names)
    modes = "'i'," + ",".join("'t'" for _ in names)
    argnames = ",".join("'" + item + "'" for item in all_names)
    hashes = ",".join("'" + hashlib.md5(body(item).encode()).hexdigest() + "'" for item in (old, new))
    return (
        " IF NOT EXISTS(SELECT 1 FROM pg_proc p WHERE\n"
        " p.oid='ingestion." + name + "(text)'::regprocedure AND md5(p.prosrc) IN (" + hashes + ")\n"
        " AND p.provolatile='" + volatility + "' AND p.proparallel='u' AND NOT p.proisstrict\n"
        " AND NOT p.prosecdef AND NOT p.proleakproof AND p.proretset\n"
        " AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')\n"
        " AND p.prokind='f' AND p.procost=100 AND p.prorows=1000 AND p.prosupport=0\n"
        " AND p.probin IS NULL AND p.prosqlbody IS NULL AND p.pronargs=1\n"
        " AND p.proargtypes='25'::oidvector\n"
        " AND p.provariadic=0 AND p.proargdefaults IS NULL\n"
        " AND p.prorettype='record'::regtype AND p.pronargdefaults=0\n"
        " AND p.proallargtypes=ARRAY[" + types + "]::oid[]\n"
        " AND p.proargnames=ARRAY[" + argnames + "]::text[]\n"
        " AND p.proargmodes=ARRAY[" + modes + ']::"char"[]\n'
        " AND p.proconfig=ARRAY['jit=off']::text[]) THEN\n"
        " RAISE EXCEPTION 'SOURCE_GRAPH_READER_FACT_WORKSET_BASELINE_DRIFT'; END IF;\n"
    )


def build() -> str:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Sealed SQL008 SHA256 changed")
    source = data.decode()
    candidates = {name: candidate(source, name) for name in NAMES}
    return (
        "-- Generated by graph/tools/build_reader_fact_worksets.py from sealed SQL008.\n"
        "-- Preserve reference bags, historical eligibility, names, merged facts and source proofs.\n"
        "-- Keep independent complete winner orders and join the full posting fact workset.\n"
        "BEGIN;\nDO $guard$ BEGIN\n"
        + "".join(guard(source, name, value) for name, value in candidates.items())
        + "END $guard$;\n\n"
        + "\n\n".join(candidates.values())
        + "\nCOMMIT;\n"
    )


if __name__ == "__main__":
    OUTPUT.write_text(build())
