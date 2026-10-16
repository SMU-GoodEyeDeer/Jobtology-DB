"""Replace only sealed capture-guard evidence joins with grouped full-row worksets.

The original LEFT JOIN rejects an inserted row if no live row matches its SQL
equality keys, or if any matching live row has different complete-row JSONB.
Grouping the union retains that condition, including conflicting duplicates,
while avoiding transition-table cardinality estimates and quadratic joins.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "hop/graph/sql/002_batchfree_source_graph.sql"
OUTPUT = ROOT / "hop/graph/sql/007_capture_guard_worksets.sql"
SOURCE_SHA256 = "bc048ef806db9f32f9ce235b6818a4e62c096d48f4a7936eda97a244921b32d3"
NAME = "ingestion.source_graph_insert_guard()"
SHARED_COMMENT_LINES = (
    " -- Transition tables can span runs. Fence each exact run before constructing",
    " -- live proof, rather than rebuilding whole history for every inserted slice.",
)
ORIGINAL_COMMENT_LINES = (
    *SHARED_COMMENT_LINES,
    " -- Compare the complete batch: EXISTS startup plans repeatedly scan genuine",
    " -- rows. bool_or preserves rejection when any exact row differs or is absent.",
)
CANDIDATE_COMMENT_LINES = (
    *SHARED_COMMENT_LINES,
    " -- Group complete inserted/live rows by the original SQL equality keys.",
    " -- Every live duplicate must match; NULL keys remain unmatched.",
)


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("Sealed SQL002 replacement contract changed")
    return source.replace(before, after)


def definition(source: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION " + NAME)
    stop = source.index("END $$;", start) + len("END $$;")
    return source[start:stop]


def body(function: str) -> str:
    return function.split("AS $$", 1)[1].rsplit("$$;", 1)[0]


def hop_body(function: str, comment_lines: tuple[str, ...]) -> str:
    """Derive the exact measured Hop form, preserving its one-space blank lines.

    Only these four sealed whole-line comments are removed. The migration still
    checks exact body hashes; it never normalizes an installed function body.
    """
    value = body(function)
    for comment in comment_lines:
        value = replace_once(value, comment + "\n", " \n")
    return value


def comparison(view: str, keys: tuple[str, ...]) -> str:
    columns = ",".join(keys)
    null_keys = " OR ".join(key + " IS NULL" for key in keys)
    return f"""   WITH evidence_rows AS (
    SELECT {columns},to_jsonb(e) AS payload,true AS inserted
    FROM new_evidence e WHERE e.run_id=jobs
    UNION ALL
    SELECT {columns},to_jsonb(l) AS payload,false AS inserted
    FROM ingestion.{view} l WHERE l.run_id=jobs
   ), evidence_groups AS (
    SELECT {columns},bool_or(inserted) AS has_inserted,
     count(*) FILTER(WHERE NOT inserted) AS live_count,
     count(DISTINCT payload) AS payload_count
    FROM evidence_rows GROUP BY {columns}
   )
   SELECT coalesce(bool_or(live_count=0 OR payload_count>1 OR {null_keys}),false)
   INTO invalid FROM evidence_groups WHERE has_inserted;"""


def candidate(source: str) -> str:
    result = definition(source)
    for view, keys in (
        ("source_graph_live_record_evidence", ("run_id", "record_id")),
        ("source_graph_reference", ("run_id", "record_id", "identity_id", "field")),
    ):
        old = (
            "   WITH live AS MATERIALIZED(SELECT * FROM ingestion."
            + view + " WHERE run_id=jobs)\n"
            "   SELECT coalesce(bool_or(to_jsonb(e) IS DISTINCT FROM to_jsonb(l)),false) "
            "INTO invalid\n"
            "   FROM new_evidence e LEFT JOIN live l USING(" + ",".join(keys)
            + ") WHERE e.run_id=jobs;"
        )
        result = replace_once(result, old, comparison(view, keys))
    return replace_once(
        result,
        "\n".join(ORIGINAL_COMMENT_LINES[2:]),
        "\n".join(CANDIDATE_COMMENT_LINES[2:]),
    )


def build() -> str:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Sealed SQL002 SHA256 changed")
    source = data.decode()
    old, new = definition(source), candidate(source)
    bodies = (body(old), body(new), hop_body(old, ORIGINAL_COMMENT_LINES),
              hop_body(new, CANDIDATE_COMMENT_LINES))
    hashes = ",".join("'" + hashlib.md5(value.encode()).hexdigest() + "'" for value in bodies)
    guard = f"""BEGIN;
DO $guard$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_proc p WHERE
  p.oid='{NAME}'::regprocedure
  AND md5(p.prosrc) IN ({hashes})
  AND p.provolatile='v' AND p.proparallel='u' AND NOT p.proisstrict
  AND NOT p.prosecdef AND NOT p.proleakproof AND NOT p.proretset
  AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
  AND p.prorettype='trigger'::regtype AND p.pronargs=0 AND p.pronargdefaults=0
  AND p.procost=100 AND p.prorows=0 AND p.prosupport=0 AND p.prokind='f'
  AND p.probin IS NULL AND p.prosqlbody IS NULL AND p.provariadic=0
  AND p.proargtypes=''::oidvector AND p.proargdefaults IS NULL
  AND p.proallargtypes IS NULL AND p.proargnames IS NULL AND p.proargmodes IS NULL
  AND p.proconfig=ARRAY['jit=off']::text[]) THEN
  RAISE EXCEPTION 'SOURCE_GRAPH_CAPTURE_WORKSET_BASELINE_DRIFT';
 END IF;
END $guard$;
"""
    return (
        "-- Generated by graph/tools/build_capture_guard_worksets.py from sealed SQL002.\n"
        "-- Preserve complete-row, duplicate and SQL-NULL evidence-guard semantics.\n"
        "-- Accept exact raw and measured Hop four-comment-elided body forms only.\n"
        + guard + new + "\nCOMMIT;\n"
    )


if __name__ == "__main__":
    OUTPUT.write_text(build())
