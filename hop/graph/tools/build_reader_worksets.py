"""Generate bag-preserving reader worksets from sealed source selection SQL003.

Keep every historical candidate and every independent validity assessment. The
canonical reference branches become set scans, avoiding memoization of entire
JSON records, and posting joins use the same ->> text keys projected once.
"""

# SQL replacement literals retain sealed formatting for review.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "hop/graph/sql/003_source_query_sharing.sql"
OUTPUT = ROOT / "hop/graph/sql/008_reader_worksets.sql"
SOURCE_SHA256 = "761ecb278d4db00396128e00fa2290973928a4c1be3cd0c3796a456cf441beff"
NAMES = ("graph_source_edges", "graph_source_entities")

# Same UNION ALL reference branches, source predicates, kinds, namespaces and
# NULL gates as SQL003. Separate scans do not memoize full normalized JSONB.
BRANCHES = (
    (
        "ncs:occupation",
        "Occupation",
        "occupation_code",
        "occupation_code",
        "r.source_id IN ('ncs_career_path', 'ncs_competency')",
        False,
    ),
    (
        "ncs:unversioned-unit",
        "Competency",
        "competency_code",
        "competency_code",
        "r.source_id = 'ncs_career_path'",
        False,
    ),
    ("ncs:unit", "Competency", "code", "code", "r.source_id = 'ncs_competency'", False),
    (
        "ncs:unit",
        "Competency",
        "competency_code",
        "competency_code",
        "r.source_id = 'ncs_qualification'",
        False,
    ),
    (
        "qnet:qualification",
        "Qualification",
        "qualification_code",
        "qualification_code",
        "r.source_id IN ('ncs_qualification', 'qnet_schedule')",
        False,
    ),
    (
        "alio:organization",
        "Organization",
        "code",
        "code",
        "r.source_id = 'alio_organization'",
        False,
    ),
    (
        "alio:organization",
        "Organization",
        "organization_code",
        "organization_code",
        "r.source_id = 'job_alio'",
        False,
    ),
    (
        "job-alio:posting",
        "JobPosting",
        "posting_id",
        "posting_id",
        "r.source_id = 'job_alio'",
        False,
    ),
    (
        "source:posting:nara_job",
        "JobPosting",
        "posting_id",
        "posting_id",
        "r.source_id = 'nara_job'",
        True,
    ),
    (
        "source:posting:jobkorea",
        "JobPosting",
        "posting_id",
        "posting_id",
        "r.source_id = 'jobkorea'",
        True,
    ),
)


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("Sealed SQL003 reader replacement contract changed: " + before[:80])
    return source.replace(before, after)


def definition(source: str, name: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION ingestion." + name + "(")
    return source[start : source.index("$$;", start) + 3]


def body(function: str) -> str:
    return function.split("AS $$", 1)[1].rsplit("$$;", 1)[0]


def reference_scans() -> str:
    parts = []
    for namespace, kind, key, field, predicate, digest in BRANCHES:
        code = "r.normalized->>'" + key + "'"
        if digest:
            code = "encode(sha256(convert_to(" + code + ",'UTF8')),'hex')"
        parts.append(
            "SELECT 'hop:'||r.run_id||':'||r.record_id::text AS record_id,r.run_id,\n"
            " '" + namespace + ":'||(" + code + ") AS identity_id,'" + kind + "'::text AS kind,\n"
            " " + code + " AS code,'" + field + "'::text AS field\n"
            " FROM records r WHERE " + predicate + " AND r.normalized->>'" + key + "' IS NOT NULL"
        )
    parts.append(
        "SELECT 'hop:'||r.run_id||':'||r.record_id::text,r.run_id,\n"
        " 'qnet:exam-session:'||encode(sha256(convert_to(r.source_record_id,'UTF8')),'hex'),\n"
        " 'ExamSession',r.source_record_id,'source_record_id' FROM records r WHERE r.source_id='qnet_schedule'"
    )
    return "\nUNION ALL\n".join(parts)


def candidate(source: str, name: str) -> str:
    original = definition(source, name)
    begin = original.index("raw_refs AS (\n") + len("raw_refs AS (\n")
    end = original.index("\n),\nrefs AS MATERIALIZED", begin)
    result = replace_once(original, original[begin:end], reference_scans())
    if name == "graph_source_entities":
        result = replace_once(
            result,
            "records AS MATERIALIZED(SELECT r.run_id,r.record_id,u.source_id,r.source_record_id,r.normalized,u.created_at",
            "records AS MATERIALIZED(SELECT r.run_id,r.record_id,u.source_id,r.source_record_id,r.normalized,u.created_at,\n"
            " r.normalized->>'posting_id' AS posting_id,r.normalized->>'representation' AS representation",
        )
        result = replace_once(
            result,
            "current_facts AS MATERIALIZED(SELECT * FROM facts WHERE choice=1)",
            "current_facts AS MATERIALIZED(SELECT f.*,f.normalized->>'posting_id' AS posting_id FROM facts f WHERE choice=1)",
        )
        result = replace_once(
            result,
            "r.normalized->>'posting_id' AS posting_id,r.normalized->>'representation' AS representation\n FROM records",
            "r.posting_id,r.representation\n FROM records",
        )
        result = replace_once(
            result,
            "AND f.normalized->>'posting_id'=r.normalized->>'posting_id'",
            "AND f.posting_id=r.posting_id",
        )
        result = replace_once(
            result, "j.posting_id=f.normalized->>'posting_id'", "j.posting_id=f.posting_id"
        )
        result = replace_once(
            result, "k.posting_id=f.normalized->>'posting_id'", "k.posting_id=f.posting_id"
        )
    return result


def guard(source: str, name: str, new: str) -> str:
    old = definition(source, name)
    volatility = "s" if "LANGUAGE plpgsql STABLE" in old else "v"
    fields = old.split("RETURNS TABLE(", 1)[1].split(")", 1)[0]
    names = [field.strip().split()[0] for field in fields.replace("\n", "").split(",")]
    all_names = ["jobs", *names]
    types = ",".join("25" for _ in all_names)
    modes = "'i'," + ",".join("'t'" for _ in names)
    argnames = ",".join("'" + item + "'" for item in all_names)
    hashes = ",".join(
        "'" + hashlib.md5(body(item).encode()).hexdigest() + "'" for item in (old, new)
    )
    return (
        " IF NOT EXISTS(SELECT 1 FROM pg_proc p WHERE\n"
        " p.oid='ingestion."
        + name
        + "(text)'::regprocedure AND md5(p.prosrc) IN ("
        + hashes
        + ")\n"
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
        " RAISE EXCEPTION 'SOURCE_GRAPH_READER_WORKSET_BASELINE_DRIFT'; END IF;\n"
    )


def build() -> str:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Sealed SQL003 SHA256 changed")
    source = data.decode()
    candidates = {name: candidate(source, name) for name in NAMES}
    return (
        "-- Generated by graph/tools/build_reader_worksets.py from sealed SQL003.\n"
        "-- Preserve historical candidates, reference bags, validity assessments and source proofs.\n"
        "BEGIN;\nDO $guard$ BEGIN\n"
        + "".join(guard(source, name, value) for name, value in candidates.items())
        + "END $guard$;\n\n"
        + "\n\n".join(candidates.values())
        + "\nCOMMIT;\n"
    )


if __name__ == "__main__":
    OUTPUT.write_text(build())
