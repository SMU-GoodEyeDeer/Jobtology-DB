# Source-only catalog: operator contract

This package is source code only. No release is approved or installed by checking
it in. `019_catalog_approval.sql`, `020_catalog_source_graph.sql`,
`021_scoped_validation.sql`, `022_scoped_posting_census.sql`,
`023_scoped_catalog_edges.sql`, `024_sealed_catalog.sql`, and
`025_live_source_feed.sql`, `026_live_ncs_demand.sql`, and
`027_product_role_inputs.sql` are ordered actions
in `install.hwf`.
It creates `catalog.catalog_approval` (immutable audit rows) and the independent
singleton `catalog.catalog_active_release`; it does not modify
`ontology.active_release`, `activate_release`, `publication_issue`, or analytics
publication gates. The approval is an operator decision about a **source-only**
catalog, not a human review of extraction, mapping, rules, or analysis.

## Install and approve (operator only)

On an isolated, authorized target, install prerequisites in `ontology/install.hwf`
order, or run the updated Hop installer with its configured PostgreSQL connection.
For an already-installed ontology schema, the incremental SQL is:

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
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

If 019/020 and the reader grant are already installed, install **021 through 027
in order**, then rerun the current reader grant, after inspecting the existing
`ingestion.validation_issue` definition and taking the normal operator backup.
Migration 021 changes only CTE planner
hints, keeps all issue branches, and refuses an unrecognized production view.
Migration 024 installs write fences and an integrity attestation; reapply 024
after reinstalling 019, which otherwise replaces the optimized approval gate.
Do not rerun source preparation or approve a release merely because these
migrations succeed; measure the complete verifier and reader path first.

For an **A-only installation**, check out commit
`5d27a4b940b307b67efbb0a45c23e026836c57be` in an isolated worktree and run only
SQL 025 followed by that same commit's `catalog_reader_grants.psql`. Do not use
the working-tree grant script for A-only: it also names the 026 and 027
functions. The A-only grant remains subject to the same privilege inspection,
operator approval, and backup requirements below. The full-current-source path
is the 025, 026, 027, then current-grant sequence shown above.

The grant script creates `jobtology_catalog_reader` as a LOGIN/NOINHERIT role
without a password. Provision authentication separately. It fails if that role
can use the `ontology` schema (including via PUBLIC); remove that leakage before
deploying it. Do not add the reader to privileged roles. Only the catalog schema
and ten read function signatures are granted. Tables, the internal gate,
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
SELECT load_id,release_id,database_id,manifest_hash,state,started_at,finished_at,node_count,edge_count
FROM ontology.graph_load WHERE database_id = :'database_id'
ORDER BY started_at DESC,load_id DESC LIMIT 1;
SELECT catalog.approve_catalog_release(:'release_id',:'database_id',:'actor',:'reason');
SELECT catalog.catalog_context_v1();
```

Example parameterized invocation (replace values deliberately, never use `LATEST`):

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" \
  -v release_id='<verified-release>' -v database_id='<neo4j-database-id>' \
  -v actor='<operator-id>' -v reason='<source-only-approval-reason>' \
  -f hop/ontology/catalog_approve.psql
```

The corresponding `catalog_approve.psql` contains only the preflight and approval
queries above. For interactive `psql`, set those four variables with `\set` and
paste the SQL block; no production command is executed by the test suite. Repeating
approval of the currently selected release/load is idempotent. A different load
or pointer switch creates a new immutable audit row. A newer RUNNING/FAILED load,
revocation/failure, changed manifest/inventory, missing verification, or changed
pinned sources closes reads until a newly verified load is explicitly approved.
Approval also requires the persisted source-only mode and a source-only graph
inventory; a fully reviewed graph cannot be relabeled as a catalog projection.
Do not repair a failed load by changing the catalog pointer manually.

The seal protects source content and release membership under a transaction-wide
write boundary. Guarded writes require READ COMMITTED; TRUNCATE of guarded source
and graph tables is forbidden even before the first seal. The existing release
remains readable while an unrelated release is prepared, but a newer load to the
**same graph destination** deliberately closes its old approval until that load
is verified and separately approved. This conservative destination-wide behavior
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

These independent `catalog` functions return `jsonb` directly from the latest
READY non-SMOKE ingestion run per source. They **do not** use the sealed/approved
release, its graph, or the approval gate. All responses include
`contract_version: "hop-live-source-v1"` and `sources` entries with `source_id`,
`run_id`, and ISO-8601 `data_as_of` (run completion). No job description,
eligibility, preference, selection, or disqualification text is returned.

| Signature | Response |
|---|---|
| `live_postings_v1(search text DEFAULT NULL, ncs_category text DEFAULT NULL, region text DEFAULT NULL, open_on date DEFAULT NULL, page_size integer DEFAULT 20, page_offset integer DEFAULT 0)` | `filters:{q,ncs_category,region,open_on}`, `limit`, `offset`, `total`, `items` with posting ID, title, organization, dates, ongoing, regions, employment types, recruitment type, education, paired NCS categories, headcount, and HTTP(S) source URL |
| `live_posting_v1(posting_choice text)` | `item` with the same posting projection; only a posting in the latest READY job run is found |
| `live_exam_sessions_v1(qualification text DEFAULT NULL, from_date date DEFAULT NULL, to_date date DEFAULT NULL, page_size integer DEFAULT 20, page_offset integer DEFAULT 0)` | `filters:{qualification,from,to}`, `limit`, `offset`, `total`, `items` with qualification code/name, year, round, category, session name, and `written`/`practical` registration, exam and result dates |

Postings require `job_alio`; exams require `qnet_schedule` and optionally join
`ncs_qualification` for names. Search is a literal case-insensitive substring of
title or organization name; NCS code is case-insensitive exact, NCS name and
region are exact. `open_on` intersects posting dates. Qualification matches code
exactly or name by case-insensitive substring. Exam date bounds match any valid
session date inclusively. Empty strings normalize to null; limits are 1–100,
offsets nonnegative. Errors are `LIVE_SOURCE_UNAVAILABLE`, `INVALID_LIVE_PAGE`,
`INVALID_LIVE_FILTER`, and `LIVE_POSTING_NOT_FOUND` (SQLSTATE P0001).

On an already-installed target, run the required migration SQL, then the reader
grant script as a privilege administrator (not via Hop). This section describes
the full-current-source path:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

For A-only, use the 025 SQL and grant script from commit
`5d27a4b940b307b67efbb0a45c23e026836c57be` only. Do not mix that installation
with the current working-tree grant script or with 026/027.

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

This migration is part of the full-current-source sequence. Install 025 first,
then 026, then 027, and rerun reader grants only after all three migrations are
present, as privilege admin:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/catalog_reader_grants.psql
```

## Product-role inputs (jobtology-product-role-inputs-v1)

`catalog.product_role_inputs_v1(occupation_codes text[])` returns an allowlisted
`jsonb` payload of `contract_version`, `sources`, `units`, `qualifications`, and
`evidence` for the requested eight-digit NCS occupation codes. `units` includes
every version in the latest READY `ncs_competency` run with code, ten-digit base
code, name, level, occupation code/name. `qualifications` includes exact
competency-code mappings from the latest READY `ncs_qualification` run, including
minimum/total training hours (that run is optional). `evidence` has only
competency code, source-scoped distinct posting count, link count, and sorted distinct
`publication_ids` contributing to that exact code from the same selected READY
publications as live NCS demand; it does not expose duties or private review data.
The sources array records run IDs/completion timestamps and selected publication
IDs/creation timestamps, posting source and latest-publication flag. Historical
publication evidence must be dated and must not be represented as current demand.
Input must be nonempty and contain only eight-digit
codes (`INVALID_PRODUCT_ROLE_INPUT`); a missing READY competency run raises
`LIVE_SOURCE_UNAVAILABLE`. It is not a sealed-catalog approval or publication.

This migration is part of the full-current-source sequence. Install 025 first,
then 026, then 027, and rerun reader grants only after all three migrations are
present, as privilege admin:

```sh
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/025_live_source_feed.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/026_live_ncs_demand.sql
psql -X -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f hop/ontology/sql/027_product_role_inputs.sql
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
