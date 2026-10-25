# Source-only catalog: operator contract

This package is source code only. No release is approved or installed by checking
it in. `019_catalog_approval.sql`, `020_catalog_source_graph.sql`,
`021_scoped_validation.sql`, `022_scoped_posting_census.sql`,
`023_scoped_catalog_edges.sql`, `024_sealed_catalog.sql`,
`025_live_source_feed.sql`, `026_live_ncs_demand.sql`,
`027_product_role_inputs.sql`, `028_flat_graph_projection.sql`,
`028_product_role_demand_base.sql`, `029_flat_catalog_compatibility.sql`,
`030_live_ncs_unit.sql`, `031_multi_source_live_postings.sql`,
`032_inferred_occupation_context.sql`, `033_posting_occupation_classifications.sql`,
`034_ncs_onet_crosswalk.sql`, `035_ncs_catalog_revalidation.sql`, and
`036_crosswalk_reader_performance.sql` are
ordered actions in `install.hwf`.
It creates `catalog.catalog_approval` (immutable audit rows) and the independent
singleton `catalog.catalog_active_release`. `029_flat_catalog_compatibility.sql`
adds separate flat approval and pointer tables while preserving those historical
rows. Installation does not modify
`ontology.active_release`, `activate_release`, `publication_issue`, or analytics
publication gates. The approval is an operator decision about a **source-only**
catalog, not a human review of extraction, mapping, rules, or analysis.

## Install and approve (operator only)

On an isolated, authorized target, install prerequisites in `ontology/install.hwf`
order, or run the updated Hop installer with its configured PostgreSQL connection.
For an already-installed ontology schema, the full catalog SQL install/replay
sequence is below. Both distinct `028_*.sql` files are required, in this order;
apply `030_live_ncs_unit.sql`, `031_multi_source_live_postings.sql`,
`032_inferred_occupation_context.sql`, `033_posting_occupation_classifications.sql`,
`034_ncs_onet_crosswalk.sql`, `035_ncs_catalog_revalidation.sql`, and
`036_crosswalk_reader_performance.sql` after those
files and the reader grants last (`ontology/install.hwf` also ends with 036):

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/019_catalog_approval.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/020_catalog_source_graph.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/021_scoped_validation.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/022_scoped_posting_census.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/023_scoped_catalog_edges.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/024_sealed_catalog.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/028_flat_graph_projection.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/028_product_role_demand_base.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/029_flat_catalog_compatibility.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/030_live_ncs_unit.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/031_multi_source_live_postings.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/032_inferred_occupation_context.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/033_posting_occupation_classifications.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/034_ncs_onet_crosswalk.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/035_ncs_catalog_revalidation.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/036_crosswalk_reader_performance.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

If `019_catalog_approval.sql`, `020_catalog_source_graph.sql`, and the reader
grant are already installed, start at `021_scoped_validation.sql` and continue
through `036_crosswalk_reader_performance.sql` in the exact order above, including
both `028_*.sql` files, then rerun the current reader grant. Inspect the existing
`ingestion.validation_issue` definition and take the normal operator backup first.
Migration 021 changes only CTE planner
hints, keeps all issue branches, and refuses an unrecognized production view.
`024_sealed_catalog.sql` installs write fences and an integrity attestation.
Replaying `019_catalog_approval.sql` or `024_sealed_catalog.sql` replaces the
approval gate; on a schema with `ontology.flat_graph_projection`, reads remain
closed with `CATALOG_FLAT_COMPATIBILITY_REQUIRED` until
`029_flat_catalog_compatibility.sql` is reapplied. Complete the sequence before
checking catalog reads.
Do not rerun source preparation or approve a release merely because these
migrations succeed; measure the complete verifier and reader path first.

For an **A-only installation**, check out commit
`5d27a4b940b307b67efbb0a45c23e026836c57be` in an isolated worktree and run only
SQL 025 followed by that same commit's `catalog_reader_grants.psql`. Do not use
the working-tree grant script for A-only: it also names the 026 and 027
functions. The A-only grant remains subject to the same privilege inspection,
operator approval, and backup requirements below. The current full install path
is the complete install/replay sequence above. The reader-only sequences below
assume an already compatible catalog runtime; they do not replay the approval
gate or perform the [flat graph migration](../operations/README.md#flattening-the-approved-ontology-projection).

The grant script creates `jobtology_catalog_reader` as a LOGIN/NOINHERIT role
without a password. Provision authentication separately. It fails if that role
can use the `ontology` schema (including via PUBLIC); remove that leakage before
deploying it. Do not add the reader to privileged roles. Only the catalog schema
and the listed read function signatures are granted. Tables, the internal gate,
approval, and ontology preview functions are not granted. Install as a trusted
schema owner with access to ontology/ingestion/retention; restrict owner and
approver credentials independently of the reader role. Do not run the grant
script as a Hop SQL action: its `psql` meta-command is intentional.

Before approval, inspect the exact release, graph destination ID, latest load,
and graph manifest. Confirm source selection and actual native graph verification
independently; a synthetic test load is never operational evidence. A PREPARING
source-only release reports `SELECTION_PENDING` rather than implying that
postings were reviewed.

### Source-only preparation and native load

Use a new release ID, not the ongoing `ontology-20260929-sources` release.
Read its six exact source pins below and assign them to the six corresponding
environment variables. Never use `LATEST` for this operation. The source
preparation and observation binder do not select model output. The persisted
`SOURCE_ONLY` mode selects a separate seal when the existing native graph loader
starts; it still verifies every node, edge, property and membership before
recording `VERIFIED`. Do not run `assemble_reviewed.hwf`.

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -c \
  "SELECT source_id,run_id FROM ontology.source_pin WHERE release_id='ontology-20260929-sources' ORDER BY source_id"
export CATALOG_RELEASE_ID='ontology-catalog-source-20261001'
"$HOP_HOME/hop-run.sh" -j default -r ontology-local \
  -f "$PROJECT_HOME/ontology/prepare_release.hwf" \
  -p "RELEASE_ID=$CATALOG_RELEASE_ID,ALIO_RUN_ID=$ALIO_RUN_ID,JOB_RUN_ID=$JOB_RUN_ID,NCS_RUN_ID=$NCS_RUN_ID,QUALIFICATION_RUN_ID=$QUALIFICATION_RUN_ID,QNET_RUN_ID=$QNET_RUN_ID,CAREER_RUN_ID=$CAREER_RUN_ID"
"$HOP_HOME/hop-run.sh" -j default -r ontology-local \
  -f "$PROJECT_HOME/ontology/bind_observations.hwf" -p "RELEASE_ID=$CATALOG_RELEASE_ID"
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -v release_id="$CATALOG_RELEASE_ID" \
  -f hop/ontology/catalog_prepare.psql
"$HOP_HOME/hop-run.sh" -j default -r ontology-local \
  -f "$PROJECT_HOME/ontology/load_release.hwf" -p "RELEASE_ID=$CATALOG_RELEASE_ID"
```

Set all six run-ID variables to the displayed exact pins before running Hop.
Install SQL 020 after any editorial graph adapter; if an adapter is reinstalled,
reinstall SQL 020 before loading again. Inspect the native load and destination
database ID before the separate approval command below. Do not insert a load
row or set `graph_verified_at` manually. The original release and its review
decisions remain untouched.

```sql
SELECT release_id,state,manifest_hash,graph_verified_at,data_as_of
FROM ontology.corpus_release WHERE release_id = :'release_id';
SELECT load_id,release_id,database_id,source_manifest_hash,manifest_hash,state,started_at,staged_at,finished_at,node_count,edge_count
FROM ontology.flat_graph_load WHERE database_id = :'database_id'
ORDER BY started_at DESC,load_id DESC LIMIT 1;
SELECT catalog.approve_catalog_release(:'release_id',:'database_id',:'actor',:'reason');
SELECT catalog.catalog_context_v1();
```

For the current flattened loader, inspect `ontology.flat_graph_load` as above;
its source and flat manifest hashes are separate. See the
[flat graph contract](README.md#load-the-ontology-graph-candidate) for load verification and historical
checkpoint preservation. `approve_catalog_release` dispatches to flat approval
once the destination has a flat load; reinstalling SQL alone requires no approval.

For a legacy destination that has never started a flat load, the existing
parameterized helper inspects `ontology.graph_load` before approval (replace
values deliberately, never use `LATEST`):

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" \
  -v release_id='<verified-release>' -v database_id='<neo4j-database-id>' \
  -v actor='<operator-id>' -v reason='<source-only-approval-reason>' \
  -f hop/ontology/catalog_approve.psql
```

`catalog_approve.psql` retains its legacy `ontology.graph_load` preflight; that
row does not verify a flattened load. For a flattened destination, set those four
variables with `\set` in interactive `psql` and use the SQL block above after
independent native verification. No production command is executed by the test
suite. Repeating approval of the currently selected release/projection is
idempotent; future flat approvals use the separate flat ledger and pointer.
A newer RUNNING/STAGED/FAILED flat load, revocation/failure, changed
manifest/inventory, missing verification, or changed pinned sources closes reads.
Flat reads require valid current proof matching the approved release/projection;
replaying that same projection requires no new approval. A new release/projection
requires its corresponding approval.
Approval also requires the persisted source-only mode and a source-only graph
inventory; a fully reviewed graph cannot be relabeled as a catalog projection.
Do not repair a failed load by changing the catalog pointer manually.

The seal protects source content and release membership under a transaction-wide
write boundary. Guarded writes require READ COMMITTED; TRUNCATE of guarded source
and graph tables is forbidden even before the first seal. The existing release
remains readable while an unrelated release is prepared, but a newer load to the
**same graph destination** deliberately closes reads until valid matching current
proof is restored and any required new release/projection approval is in place.
This conservative destination-wide behavior
is not uninterrupted old-release availability during a failed B reload. Approved
content cannot be edited; authorized revocation and reload state changes close
new reads. Database owners, DDL-capable roles, and superusers are trusted and can
disable triggers: keep those credentials outside the catalog reader and source
writer roles. Neither these fences nor the synthetic SQL fixture certify a native
graph load. Rollback of the catalog pointer does not change `ontology.active_release`
or the analytics publication gate.

## Public read signatures and shapes

All functions return `jsonb` and are in schema `catalog`. Every read passes the
same approval gate; `release_choice` defaults to the catalog pointer when NULL
or blank and an explicit choice must match that pointer. There is no preview
argument and no published/analytics fallback.

| Signature | Additional fields after context |
|---|---|
| `catalog_context_v1(release_choice text DEFAULT NULL)` | Context only |
| `catalog_entities_v1(release_choice text DEFAULT NULL, entity_kind text DEFAULT NULL, page_size integer DEFAULT 100, page_offset integer DEFAULT 0)` | `entity_kind`, `limit`, `offset`, `items` (array of `entity_id,kind,code,scheme_id,revision_id,name,payload_hash`) |
| `catalog_entity_v1(release_choice text, entity_choice text)` | `entity` (`entity_id,kind,code,scheme_id,revision_id,name,payload_hash,schema_version,source_facts`) |
| `catalog_relations_v1(release_choice text, entity_choice text, page_size integer DEFAULT 100, page_offset integer DEFAULT 0)` | `entity_id`, `limit`, `offset`, `items` (array of `relation_id,subject_id,predicate,object_id,assertion_kind,acceptance_policy`) |
| `catalog_summary_v1(release_choice text DEFAULT NULL)` | `entity_counts`, `posting_selection_outcomes` (actual frozen outcomes; absent selection is `SELECTION_PENDING`) |

The common context keys are `contract_version: "hop-catalog-source-v1"`,
`release_id`, `data_as_of`, `manifest_hash`, and `source_profile`:
`{"kind":"SOURCE_ONLY","analysis_available":false,"capabilities":["entities","source_relations"]}`.
`source_facts` is an explicit revision-payload key allowlist (aliases, source
status/dates, source IDs, class/version/rank identifiers); it never returns the
raw revision payload or job description/eligibility text. Source relationships
are release-selected `SOURCE_FACT` assertions only, without raw record or
qualifier payload. No extraction positions/claims, reviewer data, evidence spans,
rules, mappings, private profiles, or raw source responses are returned.

Supported filters: `occupation`, `ncsCompetency`, `organization`, `jobPosting`,
`qualification`, `examSession`, `careerRank`, `ncsUnitFamily`, `ncsClass`,
`conceptScheme`. `page_size` is 1–100 and `page_offset` is nonnegative. Ordering
is stable entity/relation ID in C collation, but a later page must still pass the
same `release_id` and may fail closed after a reload or pointer change. Summary
counts are source inventory/review *status*, not quality, capability, coverage,
or demand metrics.

## Live source feed (hop-live-source-v1)

These independent `catalog` functions return `jsonb` from READY non-SMOKE
ingestion observations. JobKorea retains the latest accepted observation per
native posting ID across eligible runs; ALIO and Nara use their latest READY run. They **do not** use the sealed/approved
release, its graph, or the approval gate. All responses include
`contract_version: "hop-live-source-v1"` and `sources` entries with `source_id`,
`run_id`, and ISO-8601 `data_as_of` (run completion). No job description,
eligibility, preference, selection, or disqualification text is returned.

| Signature | Response |
|---|---|
| `live_postings_v1(search text DEFAULT NULL, ncs_category text DEFAULT NULL, region text DEFAULT NULL, open_on date DEFAULT NULL, page_size integer DEFAULT 20, page_offset integer DEFAULT 0)` | `filters:{q,ncs_category,region,open_on}`, `limit`, `offset`, `total`, `items` with posting ID, source ID, title, organization, dates, ongoing, regions, employment types, recruitment type, education, paired NCS categories, headcount, and HTTP(S) source URL |
| `live_posting_v1(posting_choice text)` | `item` with the same posting projection; the same retained source observation as the list is found |
| `live_exam_sessions_v1(qualification text DEFAULT NULL, from_date date DEFAULT NULL, to_date date DEFAULT NULL, page_size integer DEFAULT 20, page_offset integer DEFAULT 0)` | `filters:{qualification,from,to}`, `limit`, `offset`, `total`, `items` with qualification code/name, year, round, category, session name, and `written`/`practical` registration, exam and result dates |

Postings include `jobkorea`, `job_alio`, and `nara_job`; any available source
suffices. JobKorea uses selected, metadata-accepted local listings across READY
non-SMOKE runs. A later accepted row replaces the same native ID; omission from
a later delta does not close or hide an older accepted posting. Invalid,
unselected, failed, loading and SMOKE observations cannot replace accepted rows.
ALIO keeps list/detail pairing and bare IDs. Nara requires its current complete
list/detail/positions/files observation. JobKorea IDs use `jobkorea:<native-id>`
and Nara uses `nara_job:<native-id>` in list and detail.

Every posting has `source_id` and `source_provenance:{source_id,run_id,data_as_of}` for its
exact observation. The list's top-level `sources` describes the latest available
source runs, which can differ from a retained JobKorea item's run. Detail
`sources` pins its selected item's exact observation. `data_as_of` is run
completion/import time; it never claims collection time. Raw private export
paths, document locators and signed input references are not returned.

Source priority is JobKorea, ALIO, then Nara, applied before pagination. Within a
source, closing dates ascend (null last), followed by posting ID. Unclassified
listings keep an empty `ncs_categories` array and do not match source NCS filters.
Employer names retain their source metadata meaning and do not verify identity.
The feed does not synthesize narrative or inferred occupation evidence.

Items expose `source_status`, `deadline_kind`, `deadline_basis`, `deadline_raw`,
`application_start_date`, `application_start_at`, `deadline_at` and
`ongoing_basis`. Unknown values remain null. An explicit CLOSED status fails
`open_on`, including when its deadline is null. Fixed instants intersect the
requested KST calendar day; application-start dates and instants constrain
availability without becoming `date_posted`. Instant deadlines provide their
KST calendar day as `closing_date`, retaining the instant separately. Malformed
calendar values remain unknown. JobKorea `ongoing` is derived against the current
time and labels the source/status/date or `USER_POLICY` basis; a policy-derived
rolling deadline is never presented as a source-stated date.

Exams require `qnet_schedule` and optionally join `ncs_qualification` for names.
Search is a literal case-insensitive substring of
title or organization name; NCS code is case-insensitive exact, NCS name and
region are exact. `open_on` intersects posting dates. Qualification matches code
exactly or name by case-insensitive substring. Exam date bounds match any valid
session date inclusively. Empty strings normalize to null; limits are 1–100,
offsets nonnegative. Errors are `LIVE_SOURCE_UNAVAILABLE`, `INVALID_LIVE_PAGE`,
`INVALID_LIVE_FILTER`, and `LIVE_POSTING_NOT_FOUND` (SQLSTATE P0001).

For an already compatible catalog with its restricted reader role and grants,
apply only 031 and 032 as the function owner:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/031_multi_source_live_postings.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/032_inferred_occupation_context.sql
```

Existing posting function signatures retain their grants. SQL 032 conditionally
grants EXECUTE on only the new context function when `jobtology_catalog_reader`
already exists; it preserves all unrelated privileges and does not rerun the full
grant reset. Fresh installations or installations missing the restricted role
still need `catalog_reader_grants.psql` as a privilege administrator. New helpers
deny PUBLIC execution. Neither reader modifies the approved release, original
source pins, product role inputs, or competency evidence.

For a broader reader upgrade missing the live-reader migrations, run the seven
SQL files below, then the reader grant script as a privilege administrator (not
via Hop). If reinstalling approval-gate SQL, use the complete
[install/replay sequence](#install-and-approve-operator-only) instead:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/028_product_role_demand_base.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/030_live_ncs_unit.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/031_multi_source_live_postings.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/032_inferred_occupation_context.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

For A-only, use the 025 SQL and grant script from commit
`5d27a4b940b307b67efbb0a45c23e026836c57be` only. Do not mix that installation
with the current working-tree grant script or with `026_live_ncs_demand.sql`,
`027_product_role_inputs.sql`, `028_product_role_demand_base.sql`,
`030_live_ncs_unit.sql`, `031_multi_source_live_postings.sql`, or
`032_inferred_occupation_context.sql`.

## Live NCS unit (hop-live-source-v1)

`catalog.live_ncs_unit_v1(base_code text) RETURNS jsonb` reads one unit from the
newest READY full `ncs_competency` run selected by `ingestion.latest_ready_run`.
It returns exactly:

```json
{
  "contract_version": "hop-live-source-v1",
  "sources": [{"source_id": "ncs_competency", "run_id": "<run ID>", "data_as_of": "<completion timestamp>"}],
  "item": {"base_code": "2001020205", "code": "2001020205_23v6", "name": "…", "level": 3, "definition": "…"}
}
```

The input must be exactly ten ASCII digits; NULL, whitespace and malformed codes
raise `INVALID_LIVE_FILTER` (SQLSTATE P0001). No READY run raises
`LIVE_SOURCE_UNAVAILABLE` (P0001). Matching uses `left(code,10)=base_code`, excludes
names containing `(구버전)`, and chooses the lexicographically highest full code
(`COLLATE "C"`), not a numeric version comparison. No eligible match returns
`item: null` while retaining the selected source provenance. `level` is an integer
or null. `definition` comes directly from `ingestion.competency.definition`,
exposed from `ingestion.record.normalized.definition` (official `compeUnitDef`);
missing, empty or whitespace-only text becomes null, and other text is preserved.
No ingestion view is changed. This bounded, STABLE SECURITY DEFINER reader has a
fixed `pg_catalog,pg_temp` search path, no PUBLIC execute privilege and no writes;
it does not require or approve a sealed catalog release. Install SQL 030 before
rerunning `catalog_reader_grants.psql` to enable the restricted catalog reader.

## Live NCS demand (hop-live-ncs-demand-v1)

`catalog.live_ncs_demand_v1(ncs_prefix text DEFAULT NULL, page_size integer
DEFAULT 20, page_offset integer DEFAULT 0)` returns `contract_version`,
`sources` (newest READY publication with attributable items for each
`job_alio`/`nara_job` source), `review.link_reviewer_kinds`
counts, normalized `filters.ncs_prefix`,
`limit`, `offset`, `total`, and `items`. Each item has competency code/name,
eight-digit occupation code/name, source-scoped distinct posting count, link count, up to three
source-duty evidence entries, and related qualification code/name pairs from the
latest READY qualification run. Competency names come from the latest READY NCS
run; missing optional source rows leave names/qualifications empty. This does not
read the sealed catalog or expose reviewer identities, notes, reasons, decisions,
candidate IDs, or posting text. `ncs_prefix` is blank or 2–8 ASCII digits;
invalid filters/pages raise `INVALID_LIVE_FILTER`/`INVALID_LIVE_PAGE`. Items sort
by postings descending, links descending, then code ascending. Only publication
rows from the selected READY publications are scanned for evidence. A source-run
pin describes input lineage, **not** output coverage: a newer publication with no
attributable items for that source does not mask older evidence. Attribution uses
explicit `payload.source_id`, otherwise a canonical `job-alio:posting:` or
`source:posting:nara_job:` identity, checked against the verified source-run pin,
or the legacy publication's `job_run_id` when it has no pin rows. Conflicts and
opaque identities are excluded. Each publication source exposes `posting_source`,
`publication_id`, `created_at`, its verified `run_id`, and
`is_latest_publication` (newest READY publication pinning/having that source,
regardless of item coverage). Evidence entries include source, publication ID,
and publication date. Older evidence is historical, **not today's demand**.
The same selection governs per-code contributor-only `publication_ids` in
product-role inputs; posting counts are distinct by `(posting_source,posting_id)`.

For a reader-only upgrade on an already compatible catalog runtime, apply the
six files in this order, then rerun reader grants as privilege admin. Replaying
approval-gate SQL requires the complete
[install/replay sequence](#install-and-approve-operator-only) instead:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/028_product_role_demand_base.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/030_live_ncs_unit.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/031_multi_source_live_postings.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/032_inferred_occupation_context.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

## Product-role inputs (jobtology-product-role-inputs-v1)

`catalog.product_role_inputs_v1(occupation_codes text[])` returns an allowlisted
`jsonb` payload of `contract_version`, `sources`, `units`, `qualifications`,
`evidence`, and `linked_postings` for the requested eight-digit NCS occupation
codes. `units` includes every version in the latest READY `ncs_competency` run
with code, ten-digit base
code, name, level, occupation code/name. `qualifications` includes exact
competency-code mappings from the latest READY `ncs_qualification` run, including
minimum/total training hours (that run is optional). `evidence` has only
competency code, source-scoped distinct posting count, link count, and sorted distinct
`publication_ids` contributing to that exact code from the same selected READY
publications as live NCS demand; it does not expose duties or private review data.
`linked_postings` (added by `028_product_role_demand_base.sql`, which replaces
the function body with the same signature and grants) lists each attributable
posting once as
`{posting_key: "<posting_source>:<posting_id>", competency_codes: [...]}` with the
sorted distinct requested-occupation codes it links to, from the same publication
selection. Consumers derive a duplicate-free per-role demand denominator from it;
it carries no titles, duties, or review data.
The sources array records run IDs/completion timestamps and selected publication
IDs/creation timestamps, posting source and latest-publication flag. Historical
publication evidence must be dated and must not be represented as current demand.
Input must be nonempty and contain only eight-digit
codes (`INVALID_PRODUCT_ROLE_INPUT`); a missing READY competency run raises
`LIVE_SOURCE_UNAVAILABLE`. It is not a sealed-catalog approval or publication.

For a reader-only upgrade on an already compatible catalog runtime, apply the
six files in this order, then rerun reader grants as privilege admin. Replaying
approval-gate SQL requires the complete
[install/replay sequence](#install-and-approve-operator-only) instead:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/028_product_role_demand_base.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/030_live_ncs_unit.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/031_multi_source_live_postings.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/032_inferred_occupation_context.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

## Disposable verification

```sh
uv run hop/ontology/tests/catalog.py
uv run hop/ontology/tests/sealed_catalog_concurrency.py
uv run hop/ontology/tests/catalog_graph.py
uv run hop/ontology/tests/source_catalog.py
uv run hop/ontology/tests/live_feed.py
uv run hop/ontology/tests/live_ncs_demand.py
uv run hop/ontology/tests/product_role_inputs.py
uv run hop/ontology/tests/live_ncs_unit.py
```

These tests reuse `ontology/tests/run.py` and its **disposable** `ontologytest`
database. `catalog.py` uses the fixed `jobtology-ontology-test-pg` container;
`catalog_graph.py` allocates unique PostgreSQL, Hop, Neo4j and network names so
it cannot reset another test's fixture. They drop only their fixture schemas and
remove their containers unless
`KEEP_ONTOLOGY_TEST_CONTAINER=1`; never point either at an existing database.
`catalog.py` seeds a synthetic VERIFIED load record after sealing a real PostgreSQL inventory
to exercise this contract, not to claim a Neo4j native load passed. It covers
unverified rejection, approval/replay, analytics still blocked, source-only
projection, permission boundaries, inventory/source drift, latest RUNNING/FAILED
reload, and revocation. `catalog_graph.py` separately runs the real native Hop
loader against disposable Neo4j, approves its actual VERIFIED load, checks the
manifest counts, typed node properties, release-owned edges, replay/renewed
approval, conflict failure/recovery, source and inventory drift, and the
still-closed analytics gate. `source_catalog.py` exercises an independent
reviewed release and accepted extraction beside a native source-only load;
its synthetic reviewed-load row is only a negative mode-gate fixture, not
native proof. Run `claims.py` followed by `graph.py` for the full reviewed graph
regression. Tests using the fixed `jobtology-ontology-test-*` names must run
sequentially, not alongside each other; `catalog_graph.py` uses unique names.

## Separate inferred occupation context

`catalog.inferred_occupation_context_v1(occupation_codes text[] DEFAULT NULL,
page_size integer DEFAULT 20, page_offset integer DEFAULT 0)` returns the
`jobtology-inferred-occupation-context-v1` contract. Filters accept at most 100
NCS eight-digit or O*NET occupation codes. Pages contain at most 100 associations;
the summary counts all filtered associations and distinct source postings,
including counts by source and occupation. Empty arrays select no occupations;
NULL selects all. It is available only through the restricted catalog reader.
Validated filters are passed into the inference adapters; an NCS-only request
skips the O*NET branch and vice versa. Source hashes are computed only for
matching posting observations and the requested comparison scheme. This avoids
unrelated hash work without establishing a production latency bound.

The reader uses completed NCS publication cohorts and VERIFIED O*NET graph
publication rows. Optional unavailable inference adapters produce no associations.
Items carry `METADATA_INFERRED`/`MODEL_INFERRED`, actual review status, STAGING,
NULL/UNASSESSED confidence, separate source/catalog pins and freshness states.
They include a safe current posting preview, or null if no current observation
exists. No inferred category is inserted into source NCS classifications, sealed
release artifacts, required competencies, or product-role evidence.

NCS source freshness compares the frozen input manifest's exact normalized hash
with the retained current observation. O*NET compares its frozen source-facts hash
with the current graph-facts projection. Missing comparison adapters are UNKNOWN;
a changed or missing source is STALE. Catalogue freshness checks the current NCS
run, or O*NET release and target content hash. `current_associations` requires
both source and catalogue CURRENT. Separate source-current, catalogue-current,
stale and unknown counts prevent source-current/catalogue-stale data from being
reported as fully current. These are inference context signals, not approved
competency evidence or employer requirements.

The focused `hop/ontology/tests/inferred_occupation_context.py` checks SQL reader
projection, optional native-shaped O*NET rows, source pins, catalogue staleness,
counts, previews, filtering, replay and grants. It does not qualify a new model
result or Neo4j publication and makes no provider or job-board request.


## Posting classifications and NCS–O*NET crosswalk upgrade

On an already compatible catalog with SQL 031 and 032 installed, apply the
following additive readers with the catalog migration/admin role before deploying
the matching BE/FE. These migrations preserve original source NCS fields,
historical inference pins/review states and approved release inputs. No source
refresh, model request or graph publication runs during installation.

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/033_posting_occupation_classifications.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/034_ncs_onet_crosswalk.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/035_ncs_catalog_revalidation.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/036_crosswalk_reader_performance.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

`live_postings_v1` and `live_posting_v1` now include
`item.occupation_associations`: nonrecursive, explicitly inferred NCS/O*NET
occupation records with the original source/catalog pins, actual review/stage,
NULL/UNASSESSED confidence, source/catalog freshness and
`competency_evidence=false`. `ncs_categories` remains source-provided only.
An empty inference list means no published association is available for this
posting; it does not establish that the posting has no relevant competencies.

The optional `ncs_category` filter matches a source category code prefix/name or
a published NCS occupation code prefix whose **source and catalog are both
CURRENT**. Responses expose
`filters.ncs_match_scope=SOURCE_OR_CURRENT_INFERRED`. Stale and unknown links
remain visible in item details but never broaden a current inferred category
filter. Review status stays separate from freshness: an UNREVIEWED association
can have current hashes while still being an unverified inference.

Page enrichment batches all selected posting keys. Without a category filter,
there is one inference-adapter read for the page; a category filter adds a
separate NCS-only match batch for accurate totals before pagination. Source
hashes are computed only for observations needed by the selected associations.
The private helpers retain no PUBLIC or catalog-reader execution grant.

SQL 034 adds the separately versioned, retrieval-only crosswalk reader
`catalog.ncs_onet_crosswalk_v1(text,integer,integer)`. Only this reader is granted;
proposal/review operators and append-only records remain private. See the
crosswalk operator documentation for creating and reviewing pinned mappings.
Shared-posting and lexical proposals do not imply NCS/O*NET equivalence,
verified employer requirements or user competency credit.

A catalog pin change is not repaired by installing these readers. Preserve stale
pins until a separately reviewed full catalog/context revalidation or rematching
policy proves the new basis. The [read-only pin comparison](../../docs/hop-migration/ncs-pin-revalidation-report.md)
proves selected normalized target content only; it never rewrites freshness.


## Full-context-equal NCS pin revalidation

SQL 035 adds a private operator action for the narrower case where the entire
NCS retrieval catalogue and v2 hierarchy context are byte-equivalent under their
canonical PostgreSQL formulas. It reconstructs **all** selected READY archive
units and occupations for both pins, verifies globally unique valid unit codes
and consistent hierarchy, proves every original frozen catalogue/context row,
and compares complete counts and hashes. Selected-target equality alone cannot
pass. Changed, removed or added occupations, incomplete archives, altered
hierarchy or unverifiable frozen inputs fail closed. The action performs no paid
requests and changes no original source, inference pin, result or review status.

The read-only production comparison on 2026-10-25 KST found 15,520 units and
1,094 occupations identical between the pins below, with zero original frozen
catalogue/context mismatches. The full retrieval catalogue hash was
`714737edd972e426d28cc651ab693bff93984c1b210c49460d59b6320cb388a7`;
the full v2 context hash was
`d5b77ca093668bd0fd09df4effd77de97da2a473dd498d888ce055994487f0b0`.
That read-only receipt did **not** apply revalidation. After merging/installing
SQL 033, 034 and 035 in the **catalog database**, an authorized migration/admin
operator can review and run:

```sql
-- Verify this still reports the exact intended target; do not substitute LATEST.
SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='ncs_competency';
BEGIN;
SET LOCAL statement_timeout='120s';
SELECT catalog.revalidate_ncs_catalog(
 'ba32f673-255c-4990-80d4-8dbef6008e2f',
 'ce5655eb-8881-47bf-affc-81158719b43d');
COMMIT;
```

The operator function independently repeats the full proof against the live
archive, checks that the exact target remains latest READY, and records an
append-only `FULL_CONTEXT_EQUAL_V1` audit. Replaying the exact call returns the
original verification timestamp. No reader role receives access to the operator,
private proof helpers or audit table; update, delete and truncate are blocked.

Current classifications backed by this audit retain their **original** catalog
pin and expose `catalog_revalidation` with `original_pin`, `current_pin`,
`policy`, `context_hash` and `verified_at`. They may count as catalog-current only
while that exact verified target remains latest READY and the original
per-occupation hash matches the audit. A later pin receives no inherited
verification. Source freshness is still checked independently, and unchanged
review status/confidence does not become verified semantic accuracy or user
competency credit. Other catalog changes still require a separate proof or
controlled rematching under the retained accounting scope.


Focused SQL verification uses disposable PostgreSQL containers and synthetic
archives only; it sends no source or model requests:

```sh
uv run python hop/ontology/tests/posting_classifications.py
uv run python hop/ontology/tests/ncs_catalog_revalidation.py
```

### Crosswalk reader performance upgrade (SQL 036)

For an already compatible catalogue with SQL 033–035 installed, run only this
idempotent reader replacement in the **catalogue database** using the migration
owner. Existing reader grants are preserved; the private helper remains revoked
from PUBLIC. No application/backend restart is required for the SQL replacement.

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" \
  -f hop/ontology/sql/036_crosswalk_reader_performance.sql
```

SQL 034's inlined node CTE allowed PostgreSQL to push catalogue-node existence
checks below the occupation-pair aggregate. The NCS catalogue was consequently
resolved once per posting, which caused the reported occupation crosswalk
request to exceed the backend's five-second query budget. SQL 036 materializes
pairs, resolves distinct pinned endpoints before filtering, and batches the exact
NCS occupation aggregates into one selected-record scan per requested READY pin.
NULL pins still select the current NCS pin; original pins and the resolver's
aggregate ordering/content hashes are preserved.

A new private `_live_source_observations(text[])` overload pushes wanted native
IDs before JobKorea latest-observation selection and Nara representation
aggregation, skipping unrelated sources. The established no-argument reader is
unchanged. Only posting/source groups with both occupation schemes need current
observations and freshness hashes. SQL 036 adds no index, cache, table, external
source/model call, data mutation or catalogue revalidation. It preserves exact
JSON, pagination totals, original pins, source/catalogue freshness, review
statuses and rejection suppression.

The PostgreSQL 17 regression uses 2,002 associations: SQL 034 calls the single-node
resolver 2,004 times; SQL 036 uses one O*NET resolver call plus one batched NCS
catalogue scan. Thirty-nine focused integration/installer/deployment checks pass,
including legacy JSON equivalence and the bounded projection's exact equality to
filtered SQL 031 results across all three source namespaces.

On 2026-10-25 UTC, actual read-only production inline full-reader candidates
completed under unchanged five-second statement timeouts:

| Filter | Total / first-page items | Measured wall time |
| --- | --- | --- |
| `ncs:occupation:20010202` | 21 / 6 | 3.844s |
| `urn:jobtology:onet:occupation:15-1252.00` | 99 / 6 | 4.738s |
| Same O*NET filter, `limit=100` | 99 / 99 | 4.957s |

The shared-proposal bodies measured 3.606s and 4.530s respectively; their plans
read 15,520 pinned NCS records once for 22 and 100 distinct endpoints. These
measure inline SQL candidates, not an installed function or HTTP request. Source
selection/hashing remains in the measured path, and the O*NET timing leaves
limited headroom: no cold/loaded-host latency guarantee is established. The
existing installed reader had exceeded 15 seconds. No production DDL or data
write was performed during diagnosis or qualification.

After separately authorized installation, check both the first page and a later
page under the application's query timeout. Confirm the unchanged total and
original pins as well as latency. Roll back the reader definition, if needed, by
reinstalling only the `_ncs_onet_shared_posting_proposals(text)` definition from
SQL 034; this restores its previous performance behavior without touching data.
