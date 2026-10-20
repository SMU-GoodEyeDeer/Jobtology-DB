#!/usr/bin/env python3
"""Report archived NCS target-content comparisons without changing any pin."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

CONTRACT = "ncs-pin-revalidation-report-v1"
DSN_ENV = "JOBTOLOGY_ADMIN_POSTGRES_DSN"
STATUSES = ("PIN_CHANGED_CONTENT_EQUAL", "TARGET_CHANGED", "TARGET_MISSING", "UNVERIFIABLE")

# Use PostgreSQL jsonb rendering and the exact historical SQL 032/036 formula.
# Python JSON serialization and v2 context hashes are deliberately not substituted.
SNAPSHOT_SQL = """
WITH associations AS MATERIALIZED (
 SELECT catalog_pin AS ncs_run_id,occupation_code,count(*) AS association_count,
  min(catalog_hash) AS published_hash,min(catalog_hash)=max(catalog_hash)
   AND count(catalog_hash)=count(*) AS published_hash_consistent
 FROM catalog._inferred_occupation_rows(%(codes)s::text[])
 WHERE occupation_scheme='NCS' AND occupation_code=ANY(%(codes)s::text[])
 GROUP BY catalog_pin,occupation_code
), pins AS (
 SELECT DISTINCT ncs_run_id FROM associations UNION SELECT %(current)s::text
), raw AS MATERIALIZED (
 SELECT r.run_id,r.normalized FROM ingestion.ready_record r JOIN pins p
  ON p.ncs_run_id=r.run_id WHERE r.source_id='ncs_competency'
), run_quality AS (
 SELECT run_id,count(*) AS run_unit_count,
  count(DISTINCT normalized->>'code')=count(*) AND bool_and(
   coalesce(jsonb_typeof(normalized->'code')='string'
    AND length(btrim(normalized->>'code'))>0,false)) AS unique_unit_codes,
  bool_or(normalized ? 'classification_names') AS hierarchical
 FROM raw GROUP BY run_id
), scoped AS MATERIALIZED (
 SELECT r.*,CASE WHEN q.hierarchical THEN normalized->'classification_names'
  ELSE jsonb_build_array(normalized->>'classification_1',
   normalized->>'classification_2',normalized->>'classification_3') END AS classes
 FROM raw r JOIN run_quality q USING(run_id)
 WHERE normalized->>'occupation_code'=ANY(%(codes)s::text[])
), hashes AS (
 SELECT run_id,normalized->>'occupation_code' AS occupation_code,count(*) AS unit_count,
  enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text) AS catalog_hash,
  count(DISTINCT classes)=1 AND bool_and(CASE WHEN jsonb_typeof(classes)='array'
   THEN jsonb_array_length(classes)=3 AND NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(classes) part
    WHERE jsonb_typeof(part)<>'string' OR length(btrim(part#>>'{}'))=0)
   ELSE false END) AS valid_hierarchy
 FROM scoped GROUP BY run_id,normalized->>'occupation_code'
), run_evidence AS (
 SELECT p.ncs_run_id,r.state,r.mode,r.source_id,q.run_unit_count,q.unique_unit_codes,
  q.hierarchical FROM pins p LEFT JOIN ingestion.run r ON r.run_id=p.ncs_run_id
 LEFT JOIN run_quality q ON q.run_id=p.ncs_run_id
)
SELECT jsonb_build_object(
 'observed_at',transaction_timestamp(),
 'read_only',current_setting('transaction_read_only'),
 'isolation',current_setting('transaction_isolation'),
 'latest_ready_ncs',(SELECT run_id FROM ingestion.latest_ready_run
  WHERE source_id='ncs_competency'),
 'runs',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY ncs_run_id),'[]')
  FROM run_evidence r),
 'hashes',(SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY run_id,occupation_code),'[]')
  FROM hashes h),
 'cohorts',(SELECT coalesce(jsonb_agg(to_jsonb(a)||jsonb_build_object(
  'frozen_catalog_hash',c.catalog_hash) ORDER BY a.ncs_run_id,a.occupation_code),'[]')
  FROM associations a LEFT JOIN enrichment.metadata_occupation_catalog c
   ON c.ncs_run_id=a.ncs_run_id AND c.occupation_code=a.occupation_code))
"""


def validate_scope(current: str, codes: list[str]) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", current) or current.upper() == "LATEST":
        raise ValueError("An exact bounded current run ID is required")
    if not 1 <= len(codes) <= 100 or any(not re.fullmatch(r"[0-9]{8}", c) for c in codes):
        raise ValueError("Supply 1 to 100 eight-digit NCS occupation codes")
    if len(set(codes)) != len(codes):
        raise ValueError("Occupation codes must be unique")
    return sorted(codes)


def capture(dsn: str, current: str, codes: list[str]) -> dict[str, Any]:
    import psycopg

    codes = validate_scope(current, codes)
    # Autocommit prevents an implicit transaction before this explicit read-only one.
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as connection:
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            connection.execute("SET LOCAL statement_timeout='120s'")
            result = connection.execute(SNAPSHOT_SQL, {"current": current, "codes": codes})
            snapshot = result.fetchone()[0]
        finally:
            connection.execute("ROLLBACK")
    return snapshot


def build_report(snapshot: dict[str, Any], current: str, codes: list[str]) -> dict[str, Any]:
    codes = validate_scope(current, codes)
    if snapshot["read_only"] != "on" or snapshot["isolation"] != "repeatable read":
        raise ValueError("A repeatable-read read-only snapshot is required")
    runs = {r["ncs_run_id"]: r for r in snapshot["runs"]}
    hashes = {(h["run_id"], h["occupation_code"]): h for h in snapshot["hashes"]}
    rows = []
    cohorts = sorted(snapshot["cohorts"], key=lambda c: (c["occupation_code"], c["ncs_run_id"]))
    for cohort in cohorts:
        old, code = cohort["ncs_run_id"], cohort["occupation_code"]
        before, after = hashes.get((old, code)), hashes.get((current, code))
        issues = []
        if snapshot["latest_ready_ncs"] != current:
            issues.append("EXPLICIT_CURRENT_PIN_IS_NOT_LATEST_READY")
        if old == current:
            issues.append("PIN_HAS_NOT_CHANGED")
        for label, pin, content in (("ORIGINAL", old, before), ("CURRENT", current, after)):
            run = runs.get(pin, {})
            if (run.get("state"), run.get("source_id")) != ("READY", "ncs_competency") or (
                run.get("mode") not in ("FULL", "REPLAY")
            ):
                issues.append(label + "_RUN_NOT_READY_NCS")
            if not run.get("run_unit_count"):
                issues.append(label + "_ARCHIVE_UNAVAILABLE")
            elif run.get("unique_unit_codes") is not True:
                issues.append(label + "_UNIT_CODES_NOT_UNIQUE_OR_VALID")
            if content and content.get("valid_hierarchy") is not True:
                issues.append(label + "_HIERARCHY_INVALID_OR_INCONSISTENT")
        frozen = cohort["frozen_catalog_hash"]
        if not before or not frozen or before["catalog_hash"] != frozen:
            issues.append("ORIGINAL_HASH_NOT_PROVEN_AGAINST_FROZEN_SQL036_CATALOG_HASH")
        if cohort["published_hash_consistent"] is not True or cohort["published_hash"] != frozen:
            issues.append("PUBLISHED_HASH_DIFFERS_FROM_FROZEN_SQL036_CATALOG_HASH")
        if issues:
            status = "UNVERIFIABLE"
        elif after is None:
            status = "TARGET_MISSING"
        elif before["catalog_hash"] != after["catalog_hash"]:
            status = "TARGET_CHANGED"
        else:
            status = "PIN_CHANGED_CONTENT_EQUAL"
        rows.append({
            "occupation_code": code, "original_run_id": old, "current_run_id": current,
            "association_count": cohort["association_count"], "status": status,
            "issues": issues, "frozen_sql036_catalog_hash": frozen,
            "published_sql036_catalog_hash": cohort["published_hash"],
            "original_recomputed_sql036_catalog_hash": before["catalog_hash"] if before else None,
            "current_recomputed_sql036_catalog_hash": after["catalog_hash"] if after else None,
            "original_unit_count": before["unit_count"] if before else None,
            "current_unit_count": after["unit_count"] if after else 0,
        })
    for code in sorted(set(codes) - {c["occupation_code"] for c in cohorts}):
        rows.append({"occupation_code": code, "original_run_id": None,
                     "current_run_id": current, "association_count": 0, "status": "UNVERIFIABLE",
                     "issues": ["NO_PUBLISHED_BACKEND_NCS_ASSOCIATION"]})
    row_counts = Counter(r["status"] for r in rows)
    association_counts: Counter[str] = Counter()
    for row in rows:
        association_counts[row["status"]] += row["association_count"]
    return {
        "contract": CONTRACT, "observed_at": snapshot["observed_at"],
        "observation_basis": "Database transaction timestamp; not source collection time",
        "current_run_id": current,
        "latest_ready_ncs": snapshot["latest_ready_ncs"], "occupation_codes": codes,
        "hash_formula": "enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text)",
        "comparison_scope": "SQL036 per-occupation normalized source catalog content only",
        "limitations": ["Does not assert model quality or full v2 context equivalence",
                        "Does not change pins, STALE freshness, review states or graph data"],
        "transaction": {"read_only": True, "isolation": "repeatable read",
                        "statement_timeout_seconds": 120},
        "counts": {"cohort_occupation_rows": {s: row_counts[s] for s in STATUSES},
                   "backend_associations": {s: association_counts[s] for s in STATUSES}},
        "run_evidence": sorted(snapshot["runs"], key=lambda r: r["ncs_run_id"]),
        "rows": sorted(rows, key=lambda r: (r["occupation_code"], r["original_run_id"] or "")),
    }


def write_receipt(path: Path, report: dict[str, Any]) -> None:
    # Exclusive creation: never overwrite an existing receipt or follow a file symlink.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-run-id", required=True)
    parser.add_argument("--occupation-codes", required=True, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        codes = validate_scope(args.current_run_id, args.occupation_codes)
        dsn = os.environ.get(DSN_ENV)
        if not dsn:
            raise ValueError(f"Set {DSN_ENV} to an admin read connection")
        snapshot = capture(dsn, args.current_run_id, codes)
        report = build_report(snapshot, args.current_run_id, codes)
        write_receipt(args.output, report)
    except Exception:
        # Driver exceptions can include credentials, host names or server SQL/context.
        parser.exit(1, "Report failed; check scope, connection, schema and output privately.\n")
    print(json.dumps(report["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
