"""Generate a narrow JOB-ALIO JSONB conflict workset from sealed SQL005.

Each representation retains parallel arrays of the original JSONB fields. The
zipped array expansion preserves SQL NULL, JSON null and source value types;
the list/detail cross product preserves every duplicate conflict issue.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "hop/graph/sql/005_validation_worksets.sql"
OUTPUT = ROOT / "hop/graph/sql/006_jobalio_validation_worksets.sql"
SOURCE_SHA256 = "1b0759a5b5af8119f5d2b9b57857ce1ea8968c857f0e0919205dde3a37c7d562"
NAME = "ingestion.source_graph_scoped_validation_issue(jobs text)"

CONFLICT_BEFORE = """SELECT l.run_id, 'POSTING_PAIR_CONFLICT', l.normalized->>'posting_id'
FROM facts l JOIN runs u ON u.run_id=l.run_id AND u.source_id='job_alio'
JOIN facts d ON d.run_id = l.run_id
 AND d.normalized->>'posting_id' = l.normalized->>'posting_id'
 AND d.normalized->>'representation' = 'detail'
WHERE l.normalized->>'representation' = 'list'
  AND (l.normalized->'title' IS DISTINCT FROM d.normalized->'title'
    OR l.normalized->'organization_code' IS DISTINCT FROM d.normalized->'organization_code'
    OR l.normalized->'date_posted' IS DISTINCT FROM d.normalized->'date_posted'
    OR l.normalized->'closing_date' IS DISTINCT FROM d.normalized->'closing_date'
    OR (d.normalized->>'ongoing' IS NOT NULL
        AND l.normalized->'ongoing' IS DISTINCT FROM d.normalized->'ongoing'))"""
CONFLICT_AFTER = """SELECT g.run_id, 'POSTING_PAIR_CONFLICT', g.posting_id
FROM jobalio_conflict_groups g
CROSS JOIN LATERAL unnest(g.list_titles,g.list_organizations,g.list_dates,
 g.list_closing_dates,g.list_ongoing) l(title,organization,date_posted,closing_date,ongoing)
CROSS JOIN LATERAL unnest(g.detail_titles,g.detail_organizations,g.detail_dates,
 g.detail_closing_dates,g.detail_ongoing,g.detail_ongoing_present)
 d(title,organization,date_posted,closing_date,ongoing,ongoing_present)
WHERE l.title IS DISTINCT FROM d.title
 OR l.organization IS DISTINCT FROM d.organization
 OR l.date_posted IS DISTINCT FROM d.date_posted
 OR l.closing_date IS DISTINCT FROM d.closing_date
 OR (d.ongoing_present AND l.ongoing IS DISTINCT FROM d.ongoing)"""
WORKSETS = """jobalio_conflict_facts AS MATERIALIZED (
 SELECT f.run_id,f.normalized->>'posting_id' AS posting_id,
 f.normalized->>'representation' AS representation,
 f.normalized->'title' AS title,f.normalized->'organization_code' AS organization,
 f.normalized->'date_posted' AS date_posted,f.normalized->'closing_date' AS closing_date,
 f.normalized->'ongoing' AS ongoing,f.normalized->>'ongoing' IS NOT NULL AS ongoing_present
 FROM facts f JOIN runs u USING(run_id) WHERE u.source_id='job_alio'
), jobalio_conflict_groups AS (
 SELECT run_id,posting_id,
 array_agg(title) FILTER(WHERE representation='list') AS list_titles,
 array_agg(organization) FILTER(WHERE representation='list') AS list_organizations,
 array_agg(date_posted) FILTER(WHERE representation='list') AS list_dates,
 array_agg(closing_date) FILTER(WHERE representation='list') AS list_closing_dates,
 array_agg(ongoing) FILTER(WHERE representation='list') AS list_ongoing,
 array_agg(title) FILTER(WHERE representation='detail') AS detail_titles,
 array_agg(organization) FILTER(WHERE representation='detail') AS detail_organizations,
 array_agg(date_posted) FILTER(WHERE representation='detail') AS detail_dates,
 array_agg(closing_date) FILTER(WHERE representation='detail') AS detail_closing_dates,
 array_agg(ongoing) FILTER(WHERE representation='detail') AS detail_ongoing,
 array_agg(ongoing_present) FILTER(WHERE representation='detail') AS detail_ongoing_present
 FROM jobalio_conflict_facts WHERE posting_id IS NOT NULL
 GROUP BY run_id,posting_id
)
"""


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("Sealed SQL005 replacement contract changed")
    return source.replace(before, after)


def definition(source: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION " + NAME)
    stop = source.index("$$;", start) + 3
    return source[start:stop]


def body(function: str) -> str:
    return function.split("AS $$", 1)[1].rsplit("$$;", 1)[0]


def candidate(source: str) -> str:
    result = replace_once(definition(source), CONFLICT_BEFORE, CONFLICT_AFTER)
    return replace_once(
        result,
        ")\nSELECT u.run_id, 'SMOKE_NOT_FULL'",
        "), " + WORKSETS + "SELECT u.run_id, 'SMOKE_NOT_FULL'",
    )


def build() -> str:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Sealed SQL005 SHA256 changed")
    source = data.decode()
    old, new = definition(source), candidate(source)
    old_hash = hashlib.md5(body(old).encode()).hexdigest()
    new_hash = hashlib.md5(body(new).encode()).hexdigest()
    # Keep SQL005 immutable, including its refusal to reinstall over SQL006.
    # Canonical installers first restore SQL003, then install 004, 005 and 006.
    guard = source.split("CREATE OR REPLACE FUNCTION " + NAME, 1)[0]
    guard = guard[guard.index("BEGIN;\n"):]
    guard = replace_once(
        guard, "'b916ba3903c47900873bf5dfd2771ab2','bad3ac1508bc564c02cc593a022e4c44'",
        f"'{old_hash}','{new_hash}'",
    )
    guard = replace_once(guard, "SOURCE_GRAPH_VALIDATION_WORKSET_BASELINE_DRIFT",
                         "SOURCE_GRAPH_JOBALIO_WORKSET_BASELINE_DRIFT")
    return (
        "-- Generated by graph/tools/build_jobalio_validation_worksets.py from sealed SQL005.\n"
        "-- Group only JOB-ALIO JSONB conflict fields; preserve typed issue bags.\n"
        + guard + new + "\nCOMMIT;\n"
    )


if __name__ == "__main__":
    OUTPUT.write_text(build())
