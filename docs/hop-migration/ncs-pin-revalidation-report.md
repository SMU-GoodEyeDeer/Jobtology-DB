# NCS pin revalidation report

`hop/operations/report_ncs_pin_revalidation.py` produces a local JSON report for
an explicit current NCS run and 1–100 unique eight-digit occupation codes. It
uses the admin PostgreSQL connection environment variable
`JOBTOLOGY_ADMIN_POSTGRES_DSN`; do not put the DSN on the command line or in a
receipt. The dashboard's restricted telemetry role does not have the archive
and frozen-catalog access this operation requires. Supply credentials through
the existing protected operator environment.

Example, after separately confirming the intended database and current pin:

```sh
python hop/operations/report_ncs_pin_revalidation.py \
  --current-run-id 26b8f6cc-c32b-4e3a-a529-a37a329b898b \
  --occupation-codes 20010201 20010202 \
  --output "$HOME/.local/state/jobtology-hop/ncs-revalidation/report.json"
```

The run ID above is the October 20 audit's observed current pin, not an automatic
latest-run selector. If the observed latest READY NCS pin differs at execution,
the report marks comparisons `UNVERIFIABLE`. Use a new output filename for each
receipt; creation is exclusive with mode `0600`. Standard output contains only
aggregate counts. Errors suppress driver details and credentials.

The CLI discovers published backend associations and their original cohort pins
through the occupation-filtered `catalog._inferred_occupation_rows(text[])`
adapter. It requires SQL 032's inferred-context reader to be installed. It
counts those backend associations, not all historical candidates or physical
Neo4j edges. Each original-pin/occupation pair has its own report row. A code
without a published association has an explicit `UNVERIFIABLE` row and zero
associations. No posting text, URL, source payload or credentials are exported.

All database reads occur in one `REPEATABLE READ READ ONLY` transaction with a
120-second statement timeout, ending with rollback. The only output is the local
JSON receipt. There is no apply mode, migration, grant, graph write, provider
request, source request or paid matching operation.

The comparison uses the exact historical SQL 032/036 per-occupation formula on
the retained selected READY non-SMOKE `ingestion.ready_record.normalized` rows:

```sql
enrichment.hash(jsonb_agg(normalized ORDER BY normalized->>'code')::text)
```

It first proves the original recomputed hash matches the immutable
`metadata_occupation_catalog.catalog_hash` and published association hash.
Ordering, JSONB rendering and hashing remain in PostgreSQL. It verifies that
each compared run has archived rows and globally unique, nonblank string unit
codes, and that each target has one consistent, valid three-part hierarchy.
As in SQL 032, a run containing `classification_names` uses that field; a fully
legacy run uses `classification_1`, `classification_2`, `classification_3`.
Missing, malformed or mixed hierarchy is unverifiable.

| Status | Meaning |
| --- | --- |
| `PIN_CHANGED_CONTENT_EQUAL` | Different pins; original frozen hash proved; current target has identical normalized catalogue content. |
| `TARGET_CHANGED` | Original frozen hash proved; current target has different normalized catalogue content. |
| `TARGET_MISSING` | Original frozen hash proved; current READY archive exists but contains no rows for this occupation. |
| `UNVERIFIABLE` | Missing archive/frozen evidence, mismatched historical or published hash, invalid units/hierarchy, same pin, or current pin no longer latest. Inspect `issues`. |

The receipt's timezone-aware `observed_at` is the database transaction timestamp
for this snapshot and its latest-pin assertion. It is not source collection time
and does not rewrite any source input or historical receipt.

The receipt includes original/current pins, frozen/published/recomputed SQL 036
hashes, unit counts, run evidence, and status counts for both cohort/occupation
rows and backend associations. Hash equality establishes only this normalized
source catalogue comparison. SQL 032's v2 context hash and whole-catalogue
manifest hash use different formulas; neither is substituted or asserted equal.
The report does not assess model quality, recall, source-posting freshness, full
inference context equivalence or whether rematching would choose the same target.

Keep existing associations **STALE**. Review equal-content cohorts as candidates
for a separately designed and approved revalidation policy. Review changed and
missing targets individually; recover unavailable historical evidence from
protected local archives before attempting a comparison. No report status
authorizes changing original pins, review states or graph data, or making new
paid requests.

Focused checks:

```sh
python -m pytest tests/unit/test_ncs_pin_revalidation_report.py
# Only against an explicitly supplied disposable local PG17+ server; the fixture
# creates/drops its own unique *_test database and requires CREATEDB permission.
python -m pytest tests/integration/test_ncs_pin_revalidation_report.py
```

Set `JOBTOLOGY_NCS_REPORT_TEST_ADMIN_DSN` privately for the integration check.
Without it, the integration suite skips. It never uses the report's admin DSN
as a fallback. Synthetic fixtures verify canonical hash ordering, changes,
missing targets, unavailable/mismatched evidence, duplicate unit codes, malformed
and inconsistent hierarchy, and PostgreSQL's read-only write rejection.
