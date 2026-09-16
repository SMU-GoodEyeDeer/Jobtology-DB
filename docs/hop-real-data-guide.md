# Hop migration: fetch and load the real Jobtology data

> **Paused on 2026-09-14 at the user’s request.** Actual source/document loading is
> complete; the full LLM/link publication phase is unfinished. See the
> [verified state and resume handoff](hop-migration/linked-ingestion.md).

**Attachment work resumed on 2026-09-14.** For the practical next stage—parse
posting documents, extract duties, link them to NCS and publish reviewed links—use
[the current linking guide](hop-migration/linked-ingestion.md). It reuses the
existing `document-processor` library. The broader ontology/product modules below
are optional later work, not prerequisites for completing this ETL.

Start with **ALIO organizations**, then **JOB-ALIO postings**, then the **NCS → qualification →
Q-Net** chain. Load the career-path CSV independently. This guide assumes you can already create
Hop pipelines, configure transforms and save workflows; the [beginner guide](hop-migration-guide.md)
remains the reference for installing Hop and fixing the HTTPS editor.

The target is a **separate `ingestion` PostgreSQL schema**. Its name describes the data layer
and can stay the same when the ETL tool changes.
Use real provider responses, retain their history, and compare the resulting facts with the
current pipeline before replacing a writer. The supplied SQL creates the loading tables and
readable data views. The original six sources and the additional 나라일터 source have executable Hop workflows, including
[qualification mappings](../hop/ingestions/ncs_qualification/README.md),
[Q-Net schedules](../hop/ingestions/qnet_schedule/README.md), and
[career paths](../hop/ingestions/ncs_career_path/README.md).

For regular updates, start with the [refresh and recovery guide](../hop/operations/README.md).
Its `operations/refresh_<source>.hwf` entry points fetch, validate and load both databases.
The original `ingestions/<source>/full.hwf` entry points perform PostgreSQL ingestion only.
The [deployment verification report](hop-migration/live-status.md) lists the original accepted
live snapshots and their independent PostgreSQL/Neo4j checks. The 나라일터 README records its
separate installation and validation procedure.

Source fetching, LLM requests and database writes use native Hop transforms/actions
and PostgreSQL/Cypher statements. Attachment parsing calls the private service that
runs the existing `document-processor` Python library; it is a separate dependency,
not a Python/script transform inside Hop. The initial output is validated source data and a draft graph. Existing
`control`, `raw_manifest`, `staging`, `canonical`, and `grounding` tables keep their current roles.

Jump to:

- [Parse documents and complete posting → NCS linking](hop-migration/linked-ingestion.md)

- [Load and review the four product occupation definitions](../hop/editorial/README.md)
- [Track posting history, expiry, absence and source freshness](../hop/ontology/observations.md)
- [Normalize reviewed requirements into typed conditions](../hop/ontology/requirements.md)
- [Export a sealed ontology release as JSON-LD and validate it](../ontology/README.md)
- [Create the destination](#1-create-the-destination-once)
- [Build the common fetch/load pipeline](#2-build-one-reusable-page-fetch-and-load-pattern)
- [ALIO organizations](#31-alio-organizations-your-first-complete-load)
- [JOB-ALIO list and detail](#32-job-alio-list-plus-detail)
- [나라일터 postings](#321-나라일터-recent-and-open-postings)
- [NCS competency](#33-ncs-competency-full-api-dataset)
- [NCS qualifications](#34-ncs-qualification-mappings-filter-the-request-codes)
- [Q-Net schedules](#35-q-net-exam-schedules-item-code--year)
- [Career-path CSV](#36-ncs-career-path-csv)
- [Field-by-field mappings](hop-migration/field-mappings.md)
- [Finish and inspect PostgreSQL loads](#4-finish-and-inspect-a-postgresql-load)
- [Load Neo4j](#5-load-neo4j-from-the-accepted-postgresql-run)
- [LLM extraction, NCS matching and evaluation batches](../hop/llm/README.md)
- [Read a selected ontology release](../hop/ontology/queries.md)
- [Replay and compare existing saved data](#6-compare-with-the-current-pipeline-using-the-same-inputs)

## What you are loading

| Source | Real data to retain | PostgreSQL read view | Recorded 2026-09-06 baseline |
|---|---|---|---:|
| `alio_organization` | Official public institutions, codes, names, metadata | `organization` | 355 |
| `job_alio` | Active posting list **and every detail**, including qualification/preference text | `posting_representation` → `job_posting` | 1,020 representations → 510 postings |
| `nara_job` | Recent index plus detail, position and file metadata for postings open at snapshot time | `nara_posting_representation` → `nara_job_posting` | 9,818 recent rows → 754 open postings measured 2026-09-16 |
| `ncs_competency` | Full versioned competency units and occupation/classification references | `competency` | 15,520 |
| `ncs_qualification` | Mappings from selected NCS units to credentials, retaining standard versions/hours | `qualification_mapping` | 87 |
| `qnet_schedule` | Written/practical exam and registration dates per credential/year/round | `exam_session` | 56 |
| `ncs_career_path` | Occupation, unversioned competency and career-rank rows from the pinned CSV | `career_path` | 12,864 |

All view names above are under `ingestion`. Counts are historical comparison values from
[the processing report](processing-pipeline.md), not acceptance thresholds for a fresh live fetch.
The old collection report describes an earlier fetching milestone; the current implementation
also has staging and explicit canonical assembly. Saramin is pending/blocked and Work24 is outside
the original six-source scope. 나라일터 is the additional implemented posting source;
Saramin remains pending/blocked and Work24 remains outside this migration.

## 1. Create the destination once

Create a PostgreSQL connection in Hop named **`jobtology-postgres`** using the actual private database
host, port 5432, database and migration role. The example credentials in `hop-lab` are not your
server credentials. If the schema shares a database with the current corpus, give this role write
access to `ingestion` and read access only to the reference tables needed for comparison.
Do not point it at Coolify's own administration database.

Run these five files, in order, through a database SQL editor or the **SQL workflow actions** below:

1. [`hop-migration/schema.sql`](hop-migration/schema.sql)
2. [`hop-migration/reference-support.sql`](hop-migration/reference-support.sql)
3. [`hop-migration/career-support.sql`](hop-migration/career-support.sql)
4. [`hop-migration/checks.sql`](hop-migration/checks.sql)
5. [`hop-migration/operations.sql`](hop-migration/operations.sql)

### 1.1 Initialize with a workflow

Create a **workflow** named `init_db.hwf` and add these actions:

```text
Start → SQL: schema → SQL: reference_support → SQL: career_support
      → SQL: checks → SQL: operations → Success
```

Use **success hops** between the actions so the validation view is created only after its tables
exist. `checks.sql` installs a view used for validation; it does not itself return validation rows.

Configure each SQL action as follows:

| Setting | Value |
|---|---|
| Database Connection | `jobtology-postgres`, the connection name used by the supplied native workflows |
| SQL from file | Enabled |
| SQL filename | Container-visible path to the corresponding file in the five-file list above |
| File encoding | UTF-8 |
| Send SQL as single statement? | Enabled for these supplied scripts |
| Use variable substitution? | Disabled; these bootstrap scripts have no SQL variables |

If the files are not mounted into the container yet, disable **SQL from file** and paste the
complete corresponding file into the action's **SQL script** box instead. Run the workflow
normally; the SQL actions execute DDL without asking it to produce pipeline columns.
[SQL workflow action reference](https://hop.apache.org/manual/latest/workflow/actions/sql.html).

Table Input is for queries that return rows. Pasting `BEGIN`, `CREATE TABLE`, or `CREATE VIEW`
scripts there can produce
`Unable to get queryfields for SQL` during pipeline preparation. Pipeline hops also do not make
DDL and downstream query preparation sequential; workflow actions provide that ordering.

This exact setup error was confirmed on 2026-09-10: `init_db.hpl` used Table Input for both
`create_schema` and `check-db`. Move those scripts to the SQL actions above. The `view` transform's
SELECT can remain in the verification pipeline. If an SQL action subsequently fails, inspect the
following PostgreSQL error for the specific connection, privilege, or SQL problem.

#### Inspect the schema and tables after initialization

Create a pipeline named `inspect_db.hpl` with two transforms:

```text
Table Input: list_objects → Write to log: show_objects
```

In **Table Input**, select the same PostgreSQL connection used by the SQL actions and enter:

```sql
SELECT s.schema_name, t.table_name, t.table_type
FROM information_schema.schemata AS s
LEFT JOIN information_schema.tables AS t
  ON t.table_schema = s.schema_name
WHERE s.schema_name = 'ingestion'
ORDER BY t.table_type, t.table_name;
```

In **Write to log**, set **Log level = Basic**, enable **Print header**, and select the three
fields `schema_name`, `table_name`, and `table_type`. Save the pipeline.
[Write to log reference](https://hop.apache.org/manual/latest/pipeline/transforms/writetolog.html).

Back in `init_db.hwf`, insert a **Pipeline action** before Success. Select `inspect_db.hpl`,
choose your local Hop pipeline run configuration, and leave **Execute for every result row**
disabled. Connect it with success hops:

```text
Start → SQL: create_schema → SQL: create_validation_view → Pipeline: inspect_db → Success
```

Run the workflow at **Basic** logging level. With the Pipeline action's default logging settings,
the object names appear in the **workflow execution log**. It does not automatically open a result
grid. For a grid, open `inspect_db.hpl`, open its Table Input transform and click **Preview**.
[Pipeline action reference](https://hop.apache.org/manual/latest/workflow/actions/pipeline.html),
[Table Input reference](https://hop.apache.org/manual/latest/pipeline/transforms/tableinput.html).

The supplied bootstrap creates **six base tables and eleven views**. The query lists objects
visible to the connected database role; its left join also shows an existing empty schema with
null table fields. No rows means that `ingestion` is absent or not visible to that role in the
connected database. This is an inspection step, not an automatic check that the expected objects
all exist.

To inspect column definitions, use this SELECT in another Table Input and preview it:

```sql
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'ingestion'
ORDER BY table_name, ordinal_position;
```

To see stored rows, preview a query for the table you want, for example:

```sql
SELECT * FROM ingestion.run ORDER BY created_at DESC LIMIT 50;
```

These inspection queries are read-only. Initialization creates the destination objects; the
fetch/load workflows later populate them, so empty tables after a first initialization are expected.

#### Rerunning initialization on a populated database

The **current `schema.sql` and `checks.sql` preserve existing table rows when rerun**, including
rows already loaded into `ingestion`:

- Schema, table and index creation uses `IF NOT EXISTS`, which skips existing objects.
- Views use `CREATE OR REPLACE VIEW`, which updates their query definitions without deleting the
  underlying table rows. Editing a view definition can change the results readers see.
- Neither bootstrap file contains a `DROP`, `TRUNCATE`, `DELETE`, `UPDATE`, or `INSERT` statement.

This is repeatable initialization, not automatic upgrading of an older table layout.
`IF NOT EXISTS` does not verify or update existing columns and constraints; incompatible existing
objects can make later statements fail. Apply intentional schema changes with a separate migration.
DDL also takes locks, so preserving rows does not mean execution cannot wait for concurrent queries.
[PostgreSQL CREATE TABLE reference](https://www.postgresql.org/docs/18/sql-createtable.html),
[CREATE VIEW reference](https://www.postgresql.org/docs/18/sql-createview.html).

Keep the optional schema rename below out of the recurring initialization workflow: it is a
**one-time** step. This rerun guarantee applies to the two bootstrap files and read-only inspection
queries; the later fetch/load workflows insert or update data and have their own run/resume rules.

### 1.2 If you already created the earlier schema name

Earlier copies of this guide used `hop_migration` as a temporary isolation name. The supplied
scripts and queries now use `ingestion`. Refresh any SQL already pasted into Hop and the schema
field on Table Output/lookup transforms.

Also replace the **actual files read by the workflow**, such as
`${PROJECT_HOME}/sql_migrations/schema.sql` and `${PROJECT_HOME}/sql_migrations/checks.sql`, with
the current copies from this repository. Updating this checkout does not update files previously
copied into the Hop project volume. If the mounted scripts still create `hop_migration` while the
inspection query filters for `ingestion`, initialization can succeed and the listing will return
zero rows. This mismatch was confirmed in the running project on 2026-09-10: `hop_migration`
contained six tables and eleven views, while `ingestion` did not exist.

First inspect which schemas exist, using this SELECT in Table Input or a database SQL editor.
It always returns one diagnostic row, even when neither schema exists:

```sql
SELECT current_database() AS database_name,
       current_user AS database_user,
       EXISTS (SELECT 1 FROM pg_catalog.pg_namespace
               WHERE nspname = 'hop_migration') AS has_old_schema,
       EXISTS (SELECT 1 FROM pg_catalog.pg_namespace
               WHERE nspname = 'ingestion') AS has_ingestion_schema;
```

To inspect the existing objects before renaming, temporarily use
`WHERE s.schema_name = 'hop_migration'` in the object-listing query above.

If **only `hop_migration` exists**, preserve its tables/data by running this once as an SQL
workflow action or in a database SQL editor, with the schema owner:

```sql
ALTER SCHEMA hop_migration RENAME TO ingestion;
```

Then run the updated bootstrap workflow to create anything missing and keep the inspection query
on `ingestion`. Refresh the mounted SQL files before rerunning; an old copy would create
`hop_migration` again after the rename. If neither exists, run that
workflow directly. If only `ingestion` exists, no rename is needed. If both exist, inspect their
contents before choosing a destination; the rename cannot combine them. A failed Table Input
initialization does not establish that no DDL ran, so check the catalog first.

#### Remove an unwanted old schema

To discard `hop_migration` and its contents, run this in a database SQL editor or a **separate,
one-time SQL workflow action** using the schema owner connection:

```sql
DROP SCHEMA IF EXISTS hop_migration CASCADE;
```

This deletes the old schema, its tables and stored rows, views, and other contained objects.
`CASCADE` also removes dependent objects, potentially in other schemas, so inspect dependencies
before using it on a schema shared with other applications.
[PostgreSQL DROP SCHEMA reference](https://www.postgresql.org/docs/18/sql-dropschema.html).

After dropping it, refresh the mounted bootstrap files to the `ingestion` versions and run
`init_db.hwf` to create the new destination. The rename step no longer applies once the old schema
has been dropped. Keep destructive cleanup out of the normal initialization workflow; its earlier
row-preservation guarantee applies to `schema.sql` and `checks.sql`, not this DROP command.

### 1.3 Project files and run parameters

Use PostgreSQL 17/18 with UTF8 encoding. Copy the SQL assets into a persistent Hop project folder
if Hop will read them as files. A file in this Git repository is not automatically visible inside
the Hop container. Mount the project and a writable raw directory into both editor and runner;
for this guide, set project parameter `RAW_ROOT=/files/hop-raw`.

| Object | What Hop writes |
|---|---|
| `run` | One source execution: run ID, mode, parser/policy version, state |
| `dependency` | Explicit upstream run IDs used to derive requests or resolve employers |
| `partition` | Every intended code/year/index partition, including empty ones |
| `document` | Archived response attempts, page context, byte hash and selected response |
| `record` | One source object, normalized fields, location, lineage and quality flags |
| `rejected_row` | Invalid source objects and the reason they failed |
| Source views | Readable columns from **READY** runs; generated by SQL, not separately loaded |

Use a new `RUN_ID` for each live full fetch or mapping-version comparison. You can get one with
`SELECT gen_random_uuid()::text;`. Keep that ID unchanged while resuming an interrupted **offline
load** of the same saved inputs. Define child pipeline parameters explicitly and pass them from
Pipeline Executor; group size 1, one executor copy initially.

| Parameter | Use |
|---|---|
| `RUN_ID`, `SOURCE_ID` | Current source execution |
| `MODE` | `SMOKE` for a bounded preview; `FULL` for live complete collection; `REPLAY` for a saved complete run |
| `RAW_ROOT` | Container-visible persistent raw directory |
| `DATA_GO_KR_SERVICE_KEY` | Decoded/raw runtime secret for the five APIs; URL-encode once in REST Client |
| `UPSTREAM_RUN_ID` | JOB-ALIO's ALIO employer snapshot; `LATEST` pins the latest accepted run |
| `INPUT_RUN_ID` | Qualification/Q-Net dependency; blank pins latest, or specify an exact READY run |
| `POLICY_REVISION` | Reviewed [source policy revision](../config/source_rights.yaml); currently `2026-09-05.1` |

Keep the key in container runtime secrets, not project JSON or a saved request URL. The five API
subscriptions and the public CSV are listed in [credentials](credentials.md). Request shapes below
come from [the implemented connectors](../src/jobtology_db/connectors/sources.py) and saved bodies
inspected on 2026-09-10. Executable workflow verification is recorded in the source sections and
their implementation READMEs.

## 2. Build one reusable page-fetch and load pattern

Build ALIO first. Once it works, copy the source-specific REST/JSON/mapping parts for the other
APIs and reuse the same archive, database loader and validation steps.

### 2.1 Create the run and its first partition

Create `pipelines/common/start_run.hpl`: Generate Rows → Get Variables → Execute SQL script.
Enable **Execute for each row** and **Bind parameters**. Bind `RUN_ID`, `SOURCE_ID`, `MODE`,
`POLICY_REVISION`, in that order:

Uppercase names denote Hop parameters. In Get Variables, expose them as incoming fields
`run_id`, `source_id`, `mode`, `policy_revision`; select those fields in the SQL parameter grid.
For the key, expose `${DATA_GO_KR_SERVICE_KEY}` as `service_key`. SQL files bind row fields,
not literal variable names or manually substituted text.

```sql
INSERT INTO ingestion.run (run_id, source_id, mode, policy_revision)
VALUES (?, ?, ?, ?);
```

For the first ALIO run, insert its single partition with another bound statement (`RUN_ID`):

```sql
INSERT INTO ingestion.partition
    (run_id, partition_id, kind, request_context, page_size)
VALUES (?, 'institutions', 'PAGED', '{"resultType":"json"}'::jsonb, 100);
```

Use Table Input to turn the partition into a request row with `page_no=1`, `confirmation_no=0`
and `attempt_no=1`. Bind `RUN_ID` from Get Variables using “Insert data from transform”:

```sql
SELECT run_id, partition_id, page_size, request_context::text,
       1 AS page_no, 0 AS confirmation_no, 1 AS attempt_no
FROM ingestion.partition WHERE run_id = ?;
```

### 2.2 Fetch, archive and register one response

Create `pipelines/alio/fetch_page.hpl`. Its request row carries run, partition, page, confirmation
and attempt numbers throughout. Define those parameters on the child and map them in its executor.

```text
Request/context → Get Variables (key) → REST Client → Select Values (remove key)
  → Binary File Output → Calculator (file SHA-256) → Get Filenames (size)
  → HTTP/provider/envelope checks → write document metadata
  → split source objects → normalize/validate → load-record.sql
```

In **REST Client** use a fixed endpoint, GET, pagination disabled, binary result enabled,
`response_bytes` as result and `http_status` as status output. Use the query-parameter mapping
from the source recipe below. Set connection/read timeouts to 10000/60000 ms, keep TLS checks
enabled, and use one request at a time. Remove the credential field immediately after the request.
Keep logging Basic; check a dummy-key failure before logging real requests. Arbitrary query-key
names and row previews must not be assumed to receive automatic redaction.
[REST Client options](https://hop.apache.org/manual/latest/pipeline/transforms/rest.html).

Construct a relative `raw_path`, for example:

```text
<RUN_ID>/<partition_id>/page-<page_no>-confirm-<confirmation_no>-attempt-<attempt_no>.json
```

Use Concat Fields and add `${RAW_ROOT}/` to form `filename`. Binary File Output takes
`response_bytes` and `filename`; create parent folders, disable overwrite. Hash the **saved file**
using Calculator's “Checksum of a file A using SHA-256”, with A=`filename`. Get Filenames in
field-input mode supplies its byte size. On replay, recheck both against the stored manifest.
Keep error response files too; they are not selected successful inputs.
[Binary File Output](https://hop.apache.org/manual/latest/pipeline/transforms/binaryfileoutput.html),
[file checksums](https://hop.apache.org/manual/latest/pipeline/transforms/calculator.html).

Read metadata from this same saved file. JSON Input can take `filename` from the preceding
transform with **Use field as file names** enabled. Read one envelope per file before splitting
its items; a valid empty array must still produce metadata and trigger empty confirmation.

For an ALIO page extract `$.resultCode`, `$.totalCount` and `$.result` (the latter as an array
JSON String). Use Database Join with `SELECT jsonb_array_length(CAST(? AS jsonb)) AS item_count`
to count the array while retaining the input context. Require HTTP 200, provider code `200`, an
array, and a nonnegative total. **The saved ALIO/JOB-ALIO lists have no `pageNo` or `numOfRows`.**
Use the requested values as effective page/size; if a future response supplies them, verify them.

Give each response a stable `document_id`, e.g. `partition:page:confirmation:attempt`. Write
`ingestion.document` with Table Output, explicit field mapping and **commit size 1** so the
parent document exists before record inserts. Populate the table's context, raw-path/hash/size,
encoding (`UTF-8` for JSON), HTTP/provider status, retrieval time, total, effective page/size and
item count. Set `selected=true` only after envelope checks and `verified_at` only after file
checks. A failed response has `selected=false` and never completes its partition.

Register archived failures through an error branch too; leave unavailable parser metadata null.
When resuming an offline load, look up `(run_id, document_id)` first: compare the existing raw
hash/length and request context, then skip the duplicate metadata insert. Reuse its saved file and
upsert its record locations. Never overwrite a different body under an existing document ID.

For the first successful page (`page_no=1`, `confirmation_no=0`), set the partition's
`expected_total` from that response. Never overwrite it from a later page. A later response with
a different total fails the snapshot. For a transport failure with no response file, record the
attempt/error in the execution log; leave the request incomplete. Count all attempts when applying
the source request budget. The installed `ingestion.request_attempt` ledger reserves requests
before transmission; see the [operations guide](../hop/operations/README.md).

### 2.3 Split, transform and load the source records

Use **two JSON Input transforms**: the first emits `source_payload_json`, one complete object per
row (`$.result[*]` for ALIO); the second reads that field and extracts `$.instCd`, `$.instNm`, etc.
Do not discard `source_payload_json`. This keeps optional fields associated with their own object.
The complete mapping is in [field-mappings.md](hop-migration/field-mappings.md).
[JSON Input's nested-object pattern](https://hop.apache.org/manual/latest/pipeline/transforms/jsoninput.html).

Set the document locator to `/result/0`, `/result/1`, etc., using a sequence **reset for each
document**, starting at 0. Other roots use `/root/items/<index>` or `/body/items/<index>`;
JOB-ALIO detail uses `/result`. A child called once per document makes the reset explicit.

After typed validation, add `kind`, `field_lineage_json` and `quality_flags_json`. For ALIO the
last is `[]`. Example field lineage is `{"code":["/instCd"],"name":["/instNm"]}`; include all
the mapped fields, not just these two. Route invalid rows to `rejected_row` with their document,
locator, original object and an error code. Do not silently discard them.

Configure **JSON Output**: operation Output value, block name `row`, rows per block **1**,
output field `normalized_block_json`, compatibility mode off. Select only the normalized fields
listed in the mapping, including `kind`; retain all the context fields in the stream.
The expected shape is `{"row":[{"kind":"Organization","code":"...","name":"...",...}]}`.
Keep optional keys with JSON nulls. Date fields must already be `yyyy-MM-dd` strings, and integer
and boolean values must keep their types.
[JSON Output](https://hop.apache.org/manual/latest/pipeline/transforms/jsonoutput.html).

Finish with **Execute SQL script**, using [`load-record.sql`](hop-migration/load-record.sql).
Enable execute-for-each-row, bound parameters and single-statement execution; disable SQL variable
substitution. Bind exactly:

```text
run_id, document_id, locator, source_payload_json,
normalized_block_json, field_lineage_json, quality_flags_json
```

The statement unwraps the object, constructs the nested NCS/Q-Net fields, derives its identity,
and upserts the same document/locator while the run is `LOADING`. It requires no JDBC JSONB-specific
field conversion because JSON Strings are explicitly cast in SQL. Treat zero affected rows as an
error: the run may not exist or may already be READY. Completed runs stay unchanged; mapping
changes get a new run/parser version.
[Execute SQL script parameter binding](https://hop.apache.org/manual/latest/pipeline/transforms/execsql.html).

### 2.4 Fetch the remaining pages, then validate the whole run

Create `workflows/alio/full.hwf` with sequential Pipeline actions:

```text
Start run/partitions → fetch+load page 1 → plan/fetch+load remaining pages
  → verify all saved files → validate source snapshot → mark READY
```

After the first-page pipeline finishes, this Table Input query plans remaining pages and the
second empty confirmation. Bind `RUN_ID` twice. Pass its output through Pipeline Executor to the
single-page child, one row per invocation. Do not loop by drawing a circular pipeline hop.

```sql
SELECT p.run_id, p.partition_id, p.page_size, p.request_context::text,
       g.page_no, 0 AS confirmation_no, 1 AS attempt_no
FROM ingestion.partition p
CROSS JOIN LATERAL generate_series(
    2, ceil(p.expected_total::numeric / p.page_size)::integer) AS g(page_no)
WHERE p.run_id = ? AND p.kind = 'PAGED' AND p.expected_total > 0
UNION ALL
SELECT run_id, partition_id, page_size, request_context::text, 1, 1, 1
FROM ingestion.partition
WHERE run_id = ? AND kind = 'PAGED' AND expected_total = 0;
```

An empty partition needs two independently fetched successful empty responses; retrying the same
failed call does not count as confirmation. A page-count cap makes a SMOKE run, never a FULL run.
Use a fresh full run after interrupted live pagination or unstable totals/duplicate source IDs.
Offline record loading can resume from a completed, unchanged document set. Do not splice pages
from separate snapshots. Disable hidden REST retries if you need one outer attempt per HTTP call;
use a bounded workflow retry with a new attempt number and filename.

## 3. Source recipes

### 3.1 ALIO organizations: your first complete load

The [runnable ALIO implementation](../hop/ingestions/alio/README.md) is installed in Goldship's
default Hop project. Open **`ingestions/alio/full.hwf`**, choose the **`alio-local`** workflow run
configuration and **Basic** logging. Run with `MODE=SMOKE` first, then `MODE=FULL` for a new complete
snapshot. The final log reports the run ID, selected document count, record count and state.

The bundle contains seven native pipelines plus the orchestration workflow and two run
configurations. It implements sections 2 and 4 for ALIO, including raw binary archives, pagination,
empty confirmations, strict normalization, rejected rows, file verification and READY gating.
Database Join handles JSON expansion and the eight-field SQL mapping; no Python or JavaScript
transform is involved. See the implementation README for the stage-by-stage file list.

Responses are saved under `${PROJECT_HOME}/data/alio-raw`. The API key is read from a protected
runtime CSV at `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv`, outside the versioned project,
using the `API_KEY_FILE` parameter. This file-based secret avoids redeploying Hop merely to add
an environment variable. Use the supplied `alio-local` run configuration so input rows containing
the key are not sampled into the existing execution-history store.

SMOKE executions retain their first-page rows in `ingestion.record` with state REVIEW_REQUIRED;
they never appear in `ingestion.organization`. A validated FULL execution becomes READY and is
visible through that view. Each invocation creates a new run and preserves earlier runs.

Endpoint: `https://apis.data.go.kr/1051000/public_inst/list`.

| Incoming field | Query parameter | Value |
|---|---|---|
| `service_key` | `serviceKey` | Runtime decoded key |
| `result_type` | `resultType` | `json` |
| `page_no` | `pageNo` | 1, then generated remaining pages |
| `page_size` | `numOfRows` | 100 |

Partition is `institutions`. Follow section 2 and the [organization mapping](hop-migration/field-mappings.md#alio-organizations).
Preview page 1 in a SMOKE run, then start a new FULL run. For the saved 355-institution snapshot,
full coverage means pages 1–4 with 100/100/100/55 rows. A fresh run uses its own declared total.
After section 4 succeeds, `SELECT * FROM ingestion.organization WHERE run_id = 'your-run-id';`
shows the complete institutions you actually loaded.

Verified live on 2026-09-10 with the native Hop runner:

| Mode | Run ID | Selected responses | Records | Final state |
|---|---|---:|---:|---|
| SMOKE | `82ed03d8-1e0b-4e70-8b79-5d9ea48827f8` | 1 | 100 | REVIEW_REQUIRED, intentionally excluded from READY views |
| FULL | `cb6db580-6cdb-4015-8fd6-2d7f682e460a` | 4 | 355 | READY |

The FULL run had zero rejected rows and zero validation issues. All four archived files were
independently rehashed, and all 355 records matched the existing parser on those same raw bodies:
source objects, normalized fields, source IDs, lineage and quality flags. These checks made five
provider requests in total, including the SMOKE page. Basic execution logs contained no API key.
The logs are saved in `${PROJECT_HOME}/data/alio-logs/` on Goldship.

To inspect the accepted run now:

```sql
SELECT code, name, organization_type
FROM ingestion.organization
WHERE run_id = 'cb6db580-6cdb-4015-8fd6-2d7f682e460a'
ORDER BY code;
```

### 3.2 JOB-ALIO: list plus detail

Open **`ingestions/job_alio/full.hwf`**, select **job-alio-local**, and use **Basic** logging.
`MODE=FULL` fetches the complete active list and every posting detail into a new snapshot.
`UPSTREAM_RUN_ID=LATEST` selects one READY ALIO organization run at startup and pins that exact
run for the entire execution. You can instead supply an explicit organization run ID.

The [runnable implementation](../hop/ingestions/job_alio/README.md) uses the existing
`jobtology-postgres` connection and protected `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv`
credential file. Responses are archived under `${PROJECT_HOME}/data/job-alio-raw/<run_id>/`.
Its defaults are `MAX_PAGES=100` and `MAX_REQUESTS=1000`; the latter counts both list and detail
requests. A complete 510-posting snapshot needs 516 requests. The operations ledger also
reserves a rolling 24-hour allowance for this Hop writer; it cannot see other applications' calls.

`MODE=SMOKE` fetches the first list page **and every detail for that page**, up to 101 requests.
It retains a REVIEW_REQUIRED snapshot and never appears in the READY-only posting views.
For a regular refresh after verification, run FULL directly. Earlier snapshots remain stored;
filter inspection queries by the new run ID. No automatic refresh schedule is installed.

The workflow validates and verifies the list before planning details, then validates all
list/detail pairs and rechecks the archived files before marking a FULL run READY. It reports
unmatched employer codes while retaining their postings. See the implementation README for
the parameter reference, stage descriptions and unmatched-employer query.

Verified live on **2026-09-11 (KST)**: run `77ccb77b-3afc-4965-8ce5-efd687304954` became **READY**
with **506 active postings**, 6 list pages, 506 detail responses and 1,012 stored source records.
It pinned ALIO run `cb6db580-6cdb-4015-8fd6-2d7f682e460a`, with zero rejected rows, validation
issues or unmatched employers. This was one FULL execution; the SMOKE and failure scenarios
were tested with offline fixtures in a disposable database. The run took about 5 minutes
25 seconds, and its Basic log contained no API key.
Independent verification rehashed all 512 archived files, matched all 1,012 source records
against the existing parser on the same bytes, and checked all 506 assembled postings and
their field-origin maps. There were zero differences.

To inspect the accepted jobs snapshot:

```sql
SELECT posting_id,
       normalized->>'title' AS title,
       normalized->>'organization_name' AS employer,
       normalized->>'closing_date' AS closing_date,
       normalized->>'eligibility_text' AS eligibility_text
FROM ingestion.job_posting
WHERE run_id = '77ccb77b-3afc-4965-8ce5-efd687304954'
ORDER BY posting_id;
```

The following describes the implemented request and loading contract. First finish an ALIO
organization run. Record it in `dependency` for this job run as
`input_source_id='alio_organization'`; use that exact run when resolving employer codes.

List endpoint: `https://apis.data.go.kr/1051000/recruitment/list`.
Query parameters: `serviceKey`, `resultType=json`, **`ongoingYn=Y`**, `pageNo`, `numOfRows=100`.
Seed `partition_id='index'`, kind `PAGED`, page size 100. Items are `$.result[*]` and total is
`$.totalCount`; provider result must be `200`. Load these as `representation=list`.

After all list pages are loaded, check list page coverage, total and duplicate posting IDs
**before** deduplicating IDs to schedule details. Then seed one DETAIL partition per list ID:

```sql
INSERT INTO ingestion.partition
    (run_id, partition_id, kind, request_context, page_size, expected_total)
SELECT r.run_id, 'detail-' || (r.normalized->>'posting_id'), 'DETAIL',
       jsonb_build_object('sn', r.normalized->>'posting_id'), 1, 1
FROM ingestion.record r
JOIN ingestion.document d USING (run_id, document_id)
WHERE r.run_id = ? AND d.selected AND r.normalized->>'representation' = 'list';
```

Detail endpoint: `https://apis.data.go.kr/1051000/recruitment/detail`.
Query parameters: `serviceKey`, `resultType=json`, **`sn=<posting ID>`**; no paging parameters.
Fetch every DETAIL partition. Its object is **`$.result`**, not an array. Validate its returned ID
against `sn`, use document page/size/item count 1, and load `representation=detail`. Follow
[all posting fields and pair checks](hop-migration/field-mappings.md#job-alio-postings).

The workflow is list pages → list validation → detail partition creation → every detail → final
validation. A detail failure leaves the entire run incomplete. For the saved baseline, expect
510 list rows, 510 detail rows and 510 assembled `job_posting` rows. No attachment/PDF download is
part of this source: retain API attachment metadata in the source payload; approved attachment
byte retrieval is separate from the current contract.

#### 3.2.1 나라일터: recent and open postings

The second posting provider is implemented in
[the native 나라일터 workflow](../hop/ingestions/nara_job/README.md). Run
`ingestions/nara_job/install.hwf` once, then open `ingestions/nara_job/full.hwf`
with **nara-job-local**. A FULL run archives a bounded recent registration window,
keeps the complete index membership, and fetches `getItem`, `getItemPosition`, and
`getItemFile` for each posting whose closing date is on or after the snapshot date.

Blank `BEGIN_DATE` and `END_DATE` resolve once at startup to the preceding 120 days
and current KST date. The exact values are stored in the index partition, so a
later replay does not reinterpret which rows were open. The workflow uses native
REST, file-output, PostgreSQL, child-pipeline, filter, and abort transforms.

The first production run on 2026-09-16 completed as run
`f3b83d1a-5103-40e1-9a1a-976d75b32be6`: 10,844 recent index rows, 761 open
postings, 2,294 archived HTTP documents, and no rejected rows. The numbers are
a baseline only; each future snapshot recalculates them from its own window.

Use `JOB_SOURCE_ID=nara_job` when sending the screened CS subset through
`llm/enrich.hwf`. Keep `JOB_RUN_ID` exact, start with `EXECUTE_REQUESTS=N`, and pass
only reviewed `cs.current_scope.posting_id` values. This preserves the same
structured-output validation, cache, extraction review, and per-link review used
by JOB-ALIO while keeping provider identities separate.

For the first live snapshot, the nine reviewed CS candidates completed
`ko-link-v1` extraction with 0 structural rejections (11 OpenRouter requests,
`$0.0170414`). Only one posting supplied enough inline duties for NCS matching;
three source-grounded links were independently accepted and published in
`nara-job-20260916`. The remaining attachment-dependent and no-duty outcomes
remain explicit in `enrichment.linking_status` until attachment parsing is enabled.

### 3.3 NCS competency: full API dataset

The [native NCS workflow](../hop/ingestions/ncs_competency/README.md) implements this recipe.
Open **`ingestions/ncs_competency/full.hwf`**, select **ncs-local**, and use **Basic** logging.
`MODE=FULL` fetches every page; `MODE=SMOKE` fetches one page and stays REVIEW_REQUIRED.
The workflow uses `jobtology-postgres`, the existing protected `API_KEY_FILE`, and
`${PROJECT_HOME}/data/ncs-raw` for response archives. `MAX_PAGES=100` caps actual requests,
including the second confirmation of an empty full result.

Endpoint: `https://c.q-net.or.kr/openapi/Ncs1info/ncsinfo.do`.
Query parameters: **lowercase `serviceKey`**, **`type=json`**, `pageNo`, `numOfRows=1000`.
Seed one PAGED partition `all`, page size 1000.

Items: `$.root.items[*]`. Metadata: `$.root.info.totalCount`, `.pageNo`, `.numOfRows`.
The saved successful envelope has no result code; validate this exact structure and metadata,
and reject a provider error envelope. Do not require a nonexistent `$.resultCode=200` here.

Use the [competency mapping](hop-migration/field-mappings.md#ncs-competency-api). Store **all**
competencies first, including occupations outside the product's CS/AI focus. The known full run
has 15,520 unique versioned codes and 32 level-zero flags. Duplicate codes across pages fail the
snapshot; Unique Rows must not hide the overlap.

After a run becomes READY, inspect **`ingestion.competency`** filtered by its `run_id`.
The accepted live FULL run on 2026-09-11 is **`a32170ed-7485-4e31-82d3-ed48b3398946`**:
15,520 records across 16 verified response files, zero validation issues, and 32 retained
unspecified-level flags. It includes all 11 categories needed by the qualification API step,
which yields 139 versioned request codes. See the source workflow README for logs and the
excluded SMOKE/failed attempts.

To project it into Neo4j, run **`graph/load_snapshot.hwf`** using **graph-local** and set
`RUN_ID` to that accepted NCS snapshot. The graph loader verifies both the source records and
their full-version competency/occupation identity references. The qualification recipe below
then uses the same accepted PostgreSQL snapshot as its upstream input.

### 3.4 NCS qualification mappings: filter the request codes

**Implemented:** run `ingestions/ncs_qualification/full.hwf` with `reference-local`,
or `operations/refresh_ncs_qualification.hwf` to include Neo4j. Leave `INPUT_RUN_ID`
blank to pin the latest accepted NCS snapshot. The workflow generates and checks
the full eleven-occupation scope automatically; it does not use a manually pasted
code list. See [parameters and behavior](../hop/ingestions/ncs_qualification/README.md).

This API is queried **once per selected full versioned NCS unit**, with pagination within that
unit. The current request scope uses these exact 11 `ncsSubdCdnm`/`occupation_name` values:

```text
DB엔지니어링
UI/UX엔지니어링
빅데이터기획
빅데이터분석
생성형AI엔지니어링
시스템SW엔지니어링
응용SW엔지니어링
인공지능모델링
인공지능서비스구현
인공지능플랫폼구축
인공지능학습데이터구축
```

Read from one READY `competency` run with Table Input (`UPSTREAM_RUN_ID`):

```sql
SELECT DISTINCT code AS ncs_code, 'ncs-' || code AS partition_id
FROM ingestion.competency
WHERE run_id = ? AND occupation_name IN (
  'DB엔지니어링', 'UI/UX엔지니어링', '빅데이터기획', '빅데이터분석',
  '생성형AI엔지니어링', '시스템SW엔지니어링', '응용SW엔지니어링',
  '인공지능모델링', '인공지능서비스구현', '인공지능플랫폼구축', '인공지능학습데이터구축')
ORDER BY code;
```

Check that **all 11 names are represented** before using this result. An absent category is an
upstream/scope problem, not permission to silently shrink the request set. The saved run produced
139 codes. Preserve their `_YYvN` suffixes, seed all their PAGED partitions, and record the
competency run in `dependency`. `request_context` contains `ncsClCd`; page size is 50.

Endpoint: `https://apis.data.go.kr/B490007/ncsClCdJm/getNcsClCdJmList`.
Query parameters: `serviceKey`, **`dataFormat=json`**, **`ncsClCd=<full code>`**, `pageNo`,
`numOfRows=50`. The live contract enforced this 50-row cap.

Items: `$.body.items[*]`. Metadata: `$.body.totalCount`, `.pageNo`, `.numOfRows`.
Success code: `$.header.resultCode`, normally `00` (reference accepted set: `00`, `0`, `SUCCESS`).
Empty arrays are normal; confirm each empty partition twice. Use the
[qualification mapping](hop-migration/field-mappings.md#ncs-qualification-mappings).

Do not collapse mapping rows into a single credential too early. The standard-version key and
training-hour fields belong in PostgreSQL even when Neo4j only links the credential identity.

### 3.5 Q-Net exam schedules: item code × year

**Implemented:** run `ingestions/qnet_schedule/full.hwf` with `reference-local`,
or `operations/refresh_qnet_schedule.hwf` to include Neo4j. It pins a qualification
snapshot and generates every qualification/year partition. `YEAR_FROM` and
`YEAR_TO` default to the current and next Asia/Seoul year. See
[parameters and snapshot updates](../hop/ingestions/qnet_schedule/README.md).

From one READY qualification run, select distinct `qualification_code`, uppercase for requests,
and validate `^[A-Z0-9]{4}$`. Preserve leading zeroes. Join each code to the current and next
calendar years with Table Input:

```sql
SELECT DISTINCT upper(q.qualification_code) AS item_code, y.year,
       'year-' || y.year::text || '-item-' || upper(q.qualification_code) AS partition_id
FROM ingestion.qualification_mapping q
CROSS JOIN generate_series(extract(year FROM CURRENT_DATE)::integer,
                           extract(year FROM CURRENT_DATE)::integer + 1) AS y(year)
WHERE q.run_id = ?;
```

Use `CURRENT_DATE` in the intended scheduler timezone, or supply the two explicit year parameters
when replaying an older snapshot. Seed **every combination**, page size 50, context
`{"implYy":"<year>","jmCd":"<code>"}`, and record the qualification run in `dependency`.
The historical scope was 31 codes × 2 years = 62 partitions, not 62 schedule records.

Endpoint: `https://apis.data.go.kr/B490007/qualExamSchd/getQualExamSchdList`.
Query parameters: `serviceKey`, `dataFormat=json`, **`implYy`**, **`jmCd`**, `pageNo`, `numOfRows=50`.
Metadata/items/success envelope match the qualification API. Double-confirm empty partitions.

Use [the exam mapping](hop-migration/field-mappings.md#q-net-examination-schedules), retaining the
requested item code alongside each response even when the body omits it. Load all ten date keys;
missing dates remain null. This is exam scheduling data, not a credential price/eligibility feed.

### 3.6 NCS career-path CSV

**Implemented:** run `ingestions/ncs_career_path/full.hwf` with `reference-local`,
or `operations/refresh_ncs_career_path.hwf` to include Neo4j. Encoding detection,
strict file checks, native CSV Input and full source-row retention are provided.
See [the workflow guide](../hop/ingestions/ncs_career_path/README.md).

Fetch the pinned `NCS_CAREER_PATH_DOWNLOAD_URL` from [.env.example](../.env.example), currently:

```text
https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002844861&fileDetailSn=1&insertDataPrcus=N
```

No API key. Seed one FILE partition `file`, page size 1. Native HTTP workflow action can download
to a unique `.csv` path with append disabled; alternatively use the common binary REST/archive
pipeline. Reject an empty file or an HTML error page before CSV parsing.
[HTTP file download](https://hop.apache.org/manual/latest/workflow/actions/http.html).

Use Text File Input/CSV File Input with the [exact Korean columns and code construction](hop-migration/field-mappings.md#ncs-career-path-csv).
The saved file inspected for this guide is CP949, 859,596 bytes. Choose encoding from the actual
file; the reference parser tries UTF-8 with BOM first, then CP949. Handle quoted commas/newlines
and require consistent row width. Locator is `csv:record:1`, counting logical data records after
the header, not physical lines. Use JSON Output to preserve each original CSV object, then unwrap
that block to obtain `source_payload_json` before normalizing another copy of its values.

After parsing, set the FILE partition total and document item count to the actual data-record
count; they describe the CSV, not a provider pagination total. The baseline has 12,864 rows over
1,072 occupation codes. A versioned competency cannot be inferred from this unversioned file.
Checking this URL every 30 days does not discover a replacement portal attachment automatically.

## 4. Finish and inspect a PostgreSQL load

All rows land in `record`; the SQL views expose their business fields once the run is READY.
This avoids coordinating two separately committed writes for each source record and its typed
table. A partially loaded run is retained for diagnosis/replay and stays invisible to the views.

After every child has finished and committed, recheck selected raw files and required field/type
validators, then query:

```sql
SELECT issue, location FROM ingestion.validation_issue WHERE run_id = ?;
```

The result must be empty. The supplied checks cover document/row counts, contiguous pagination,
empty confirmation, duplicates, selected-file verification, source kinds/partitions, dependencies
and posting pairs. They **complement** the mapping validators, not implement every field contract.
Check intended partition membership against the generated upstream request rows too; correctly
loading a manually shortened partition list is not a complete source run.

Route rejected rows to `REVIEW_REQUIRED`; failed coverage/integrity to `FAILED`. Only after all
source checks pass, Execute SQL script with `RUN_ID` as the one bound parameter:

```sql
UPDATE ingestion.run u
SET state = 'READY', completed_at = CURRENT_TIMESTAMP
WHERE u.run_id = ? AND u.state = 'LOADING' AND u.mode <> 'SMOKE'
  AND NOT EXISTS (SELECT 1 FROM ingestion.validation_issue v WHERE v.run_id = u.run_id);
```

Require exactly one updated row; zero is failure, not a successful empty dataset. Keep a single
writer per run while loading/finalizing. A scheduler must also prevent overlapping source runs.
Do not edit records in a READY run; the bootstrap schema relies on this writer discipline and
does not install immutability triggers.

Useful inspection queries (bind the selected run IDs, never choose an arbitrary cross-source latest):

```sql
SELECT source_id, run_id, count(*) FROM ingestion.ready_record
GROUP BY source_id, run_id ORDER BY source_id, run_id;

SELECT code, name, organization_type FROM ingestion.organization WHERE run_id = ?;

SELECT posting_id, normalized->>'title' AS title,
       normalized->>'organization_code' AS employer, normalized->>'closing_date' AS closes,
       normalized->>'eligibility_text' AS eligibility, field_origin
FROM ingestion.job_posting WHERE run_id = ?;
```

To resolve employers, join `job_posting.normalized->>'organization_code'` to `organization.code`
using the ALIO run pinned in `dependency`. Report unmatched official codes explicitly; do not
silently drop postings with an inner join or guess an organization by name. Missing descriptions
may be represented as identifier-only drafts until the source/reference is corrected.

## 5. Load Neo4j from the accepted PostgreSQL run

The [native graph workflows](../hop/graph/README.md) are implemented and installed in the live
Hop server's persistent default project, with a verified live Neo4j load. Open
**`graph/alio_jobs.hwf`**, select **graph-local**, use **Basic** logging, and set
`JOB_RUN_ID=LATEST` or an explicit accepted jobs run. This loads the jobs run's pinned ALIO
employer snapshot first, then its list/detail records. To load or retry one source independently,
use **`graph/load_snapshot.hwf`** with `RUN_ID=<accepted run ID>`.

The current installation uses private Bolt connection metadata **`jobtology-neo4j`**, which is
the workflow default. For another connection, override `NEO4J_CONNECTION`. Use **Neo4j Cypher** with bound
parameters. Batches use `ingestionBatch`, historical source rows use `ingestionRecord`, and shared
business nodes use `organization`, `jobPosting`, `occupation`, `ncsCompetency` or `qualification`.
Business nodes also carry `entity` for a shared ID uniqueness constraint. These remain separate
from the existing `Ingest*` projection. PostgreSQL keeps source objects and long text, and the raw archive keeps the complete
API responses. The graph contains selected facts and explicit source-identity references.
[Neo4j Cypher transform](https://hop.apache.org/manual/latest/pipeline/transforms/neo4j-cypher.html).

The implemented workflows follow this sequence:

1. Verify the PostgreSQL run, inspect/create uniqueness constraints, upgrade old labels in place,
   then create the batch in LOADING state with the source run date.
2. Table Input `SELECT * FROM ingestion.graph_record WHERE run_id = ?` → Neo4j Cypher.
3. Table Input `SELECT * FROM ingestion.graph_reference WHERE run_id = ?` → Neo4j Cypher.
4. Set entity names from accepted PostgreSQL facts, retaining their source run/record IDs.
5. Compare record properties, reference triples, semantic labels, names and batch dates to
   PostgreSQL, reject extra membership, then set the graph batch READY.

For readable node captions, type **`:style`** in Neo4j Browser and upload
[browser-style.grass](../hop/graph/browser-style.grass). It shows organization names, posting
titles, NCS occupation/competency names, and batch dates. Alternatively, click a node label in
the result overview and select its caption property: **name**, **title** for `jobPosting`, or
**batch_date** for `ingestionBatch`. The dates use **Asia/Seoul** and represent when the source
snapshot began, so a graph-only rerun keeps the same date. Caption settings belong to each
Browser profile; the graph properties and Hop files persist independently.
See [Neo4j Browser styling](https://neo4j.com/docs/browser/operations/browser-styling/).

The [supplied Cypher statements](hop-migration/graph.cypher) explain the model. The executable
workflows include explicit failure checks, property/reference comparisons and empty-set handling.
They also inspect constraints before creating them: Hop 2.19 treats Neo4j's harmless existing-
constraint information notification as an error. Parameter names match input column names.
The implementation runs parameter-bound statements per row. Compare record IDs and their loaded properties, plus the relationship set;
counts alone can hide wrong identities or properties. A zero-row graph still needs a batch and
successful empty-set verification.

The references reproduce the current staging relationships:

| Source record | Identity references |
|---|---|
| Organization | `alio:organization:<code>` |
| Posting list/detail | `job-alio:posting:<id>` and `alio:organization:<code>` |
| NCS competency | `ncs:unit:<full-version-code>` and `ncs:occupation:<8-digit-code>` |
| Career path | `ncs:unversioned-unit:<10-digit-code>` and NCS occupation |
| Qualification mapping | Full NCS unit and `qnet:qualification:<code>` |
| Exam session | Q-Net qualification |

If Neo4j fails, leave the PostgreSQL run READY and the graph batch LOADING/failed; retry only the
graph workflow for that same run. Repeated MERGE writes are idempotent. Do not refetch APIs because
of a graph outage. These batches have `serving_scope=STAGING`; they do not activate a serving release
or write Person data. Re-run graph verification before changing any active graph selection.

## 6. Compare with the current pipeline using the same inputs

Use saved responses for the decisive comparison. A live API fetched today may differ legitimately
from the 2026-09-06 reference. Do not copy normalized Python records into Hop and call that a parser
comparison: Hop must read and normalize the same **raw documents** independently.

Create a read-only `jobtology_reference` connection if using a separate database. Select an explicit
source run from [collection status](collection-status.md), and find its READY processing run:

```sql
SELECT p.processing_run_id, f.source_id, p.connector_run_id, p.state
FROM control.processing_run p
JOIN control.connector_run f USING (connector_run_id)
WHERE p.connector_run_id = ?;
```

Confirm the source and READY state. Create a new migration run with mode REPLAY and set its
`reference_connector_run_id` and `reference_processing_run_id`. Query its selected source files:

```sql
SELECT r.partition_id, COALESCE(r.page_number, 1) AS page_no,
       o.response_ordinal AS confirmation_no, o.attempt_no,
       o.observation_id AS document_id, o.http_status, o.retrieved_at,
       s.raw_object_path AS raw_path, s.content_sha256 AS raw_sha256,
       s.byte_length, s.mime_type
FROM control.connector_request r
JOIN raw_manifest.fetch_observation o
  ON o.observation_id = r.selected_observation_id
 AND o.connector_run_id = r.connector_run_id
 AND o.request_fingerprint = r.request_fingerprint
JOIN raw_manifest.source_snapshot s ON s.snapshot_id = o.snapshot_id
WHERE r.connector_run_id = ? AND o.selected AND o.outcome = 'SELECTED_SUCCESS'
ORDER BY r.partition_id, r.page_number, o.response_ordinal;
```

Mount the reference raw root **read-only** into Hop and point the replay's RAW_ROOT at it; files
are relative paths like `raw/sha256/ab/cd/<hash>`. Verify SHA-256/length **before** loading. Confirm
the reference run's fetch completion, successful/planned request counts and selected document count
agree. Include empty confirmations; do not select only files containing records. Replay the whole
six-source set in dependency order when validating the dependent sources.

Seed partitions from these verified request contexts, register documents and use the same parsing
children, skipping REST/download. Carry item/year context from `partition_id`. For the CSV, parser
record counts supply FILE metadata. Save both reference IDs on the migration run and retain its
dependency links. This mode makes zero provider calls.

After READY, run [`compare.sql`](hop-migration/compare.sql), binding the Hop RUN_ID twice. If the
schemas are in separate databases, export the reference query's normalized rows and compare through
Sort Rows → Merge Rows (diff) in Hop with equal, deterministic JSON serialization. The supplied
same-database SQL compares JSONB objects with **EXCEPT ALL**, retaining duplicate multiplicities.
Check the reference exists and is READY before accepting an empty difference result.

Expect zero changed/missing/extra normalized objects. Then compare original source objects,
field-lineage maps, quality flags and document/locator membership; normalized equality alone does
not prove provenance. CareerPath IDs intentionally differ; compare their full normalized objects.
For jobs also check exact list/detail pairing, merged values, field origins and official employer
joins. Use [the canonical load report](canonical-load-status.md) for the existing assembly behavior.

Acceptance exercises before replacing a writer:

- Rerun offline loading: same document/locator rows and facts; no duplicates.
- Missing/overlapping page, changing total or missing empty confirmation: run cannot become READY.
- Missing detail or conflicting posting dates/status: entire job snapshot fails.
- Invalid date, missing required ID or malformed number: rejection retained, run requires review.
- Interrupted loading: partial records remain hidden; resumed load matches the complete manifest.
- Neo4j interruption: retry uses accepted PostgreSQL data and verifies identical nodes/references.

## 7. What comes after the first matching data load

All six workflows are implemented. Regular refresh and recovery are described in
[the operations guide](../hop/operations/README.md): jobs/Q-Net daily, NCS competencies
and qualification mappings weekly, organizations/career paths every 30 days.

LLM extraction, NCS categorization and quality-check batches now have separate native
workflows. Follow the [LLM workflow guide](../hop/llm/README.md): prepare a frozen dataset,
plan an evaluation without API calls, choose model settings, and add reviewed labels before
comparing quality. Results live in the additive `enrichment` schema with evidence and model
metadata. A separate workflow publishes reviewed ENRICH results to Neo4j; evaluation results
cannot be published. Model requests are off by default and are not part of the source scheduler.
The default `ko-v3` contract uses passage IDs, literal text fragments and nested condition
expressions. The [DeepSeek/Luna comparison](hop-migration/llm-model-comparison-2026-09-12.md)
documents the revised checks and a reproducible 22-posting regression sample. Its partial
source assertions are assistant-authored, not human gold; keep acceptance set to `REVIEW`.

There is no existing backend to cut over. Application query design can use the accepted source
and enrichment views when the backend is built. Automatic retention, remaining attachment coverage and reviewed ontology
publication still require work.

This experiment retains source facts and per-run history but does not yet replace the current
canonical assembly, evidence-span store or content-addressed revision IDs. Their application
integration remains separate from source ingestion. Durable request reservations, refresh
execution history, quota checks and a PostgreSQL-to-Neo4j recovery checkpoint are now supplied.
The host scheduler checks Goldship's 100 GiB raw-volume reserve and serializes its own executions.
Direct editor executions bypass that host lock and disk check. Responses over 64 MiB are rejected
after download; native REST does not provide an equivalent streaming response-size limit here.

Use one scheduler and stop any other writer sharing its provider allowance. Keep
the last accepted dataset available for rollback. A job missing from a new active-list snapshot
stays in history; absence alone does not set its status to closed or delete it.

## Verification of this documentation

Checked on 2026-09-10–11:

- Source recipes/mappings against the repository and saved envelopes, including absent ALIO
  pagination fields, the 11-category NCS allowlist and the CP949 career file.
- SQL bootstrap and repeat installation in disposable PostgreSQL 18. After adopting the generic
  schema name, fresh `ingestion` setup and renaming an existing `hop_migration` schema were also
  checked: six tables, eleven views, preserved rows and working validation views.
- All **878 selected saved response documents / 29,902 source records** through the SQL loader
  using reference-parser-generated input rows; all six SQL comparisons with the existing normalized
  corpus returned zero differences. This validates SQL shaping/loading, not a new Hop parser.
- The posting view assembled 510 list/detail pairs and retained their field origins; graph export
  views produced 29,902 records and 59,393 identity-reference rows.
- Missing-page, missing-empty-confirmation, missing-detail and unverified-file metadata gates;
  changed-fact and missing-reference comparison checks; offline row replay without duplicates.
- The native ALIO workflow in Hop 2.19: a 201-record, three-page fixture matched the reference
  normalizer; SMOKE, empty confirmation, invalid dates/types, duplicates, missing pages, changed
  totals, malformed JSON, page-budget and changed-file checks behaved as specified. A dummy-key
  transport failure exercised the sanitized error branch without leaking the key into logs.
- ALIO live SMOKE and FULL runs in `ingestion`: 100 preview records, then 355 accepted organizations
  across four archived pages. Independent raw-file/parser comparison returned zero differences.
- JOB-ALIO native execution: full list pagination, every detail, pinned employer dependencies,
  pair/field validation, request caps, failure propagation and SMOKE isolation were tested with
  offline fixtures. A live FULL run then loaded 506 accepted postings from 512 archived responses,
  with zero rejected rows, validation issues or unmatched employers. All 1,012 source records
  and all 506 assembled postings matched the reference parser and merge rules on the same bytes.
- Native NCS competency ingestion: all 16 saved baseline pages and all 15,520 records matched
  the reference parser, including lineage and 32 unspecified-level flags. Pagination, empty
  confirmations, duplicate codes, malformed fields/envelopes, request caps, replay and archive
  verification were tested. The live FULL run `a32170ed-7485-4e31-82d3-ed48b3398946` then accepted
  15,520 records from 16 archived responses with zero validation issues and zero independent
  raw/parser differences. A page-11 connection timeout left an earlier run FAILED; its partial
  rows remain excluded. All 11 qualification-scope categories are present, with 139 request codes.
- Native Neo4j loading in Hop 2.19.0 against disposable PostgreSQL 18 and Neo4j 5.26 Community,
  using copies of the accepted ALIO/JOB-ALIO snapshots: 1,367 records, 2,379 identity references
  and 861 identities matched PostgreSQL with zero differences. Both batches became READY;
  repeating the complete workflow preserved the graph. Changed record/identity properties,
  extra records and duplicate references failed verification. A repaired batch could be retried,
  a confirmed empty snapshot completed, and a SMOKE snapshot was rejected before graph writes.
- A live native graph load through the saved `jobtology-neo4j` connection into Neo4j 2026.06.0
  Community. Both graph batches became READY, and independent read-back of all 1,367 records
  and 2,379 identity references returned zero differences against PostgreSQL. All 506 postings
  resolved to their official employers. Repeating the full graph load preserved the same
  records, properties and references without duplicates. PostgreSQL snapshots remained READY
  with zero issues.

- The v2 graph update renamed existing nodes in place and added organization/posting/NCS names
  and source batch dates. All 2,230 prior node IDs and 3,746 relationship IDs were preserved.
  The live NCS load added 15,520 source records and 31,040 references. Across all three accepted
  sources, independent comparison verified 16,887 records, 33,419 references, 17,475 entity names
  with provenance, semantic labels and batch dates, with zero differences. All three batches
  were READY in both stores. Repeating the NCS graph load preserved the same complete graph
  without duplicates. The saved Browser style uses these readable properties as captions.

All six sources now have executable Hop artifacts. The qualification/Q-Net/career workflows
replayed the saved provider bytes through native Hop: 87, 56 and 12,864 normalized records
respectively, with zero differences in source objects, normalized fields, lineage and flags.
The 237 qualification responses cover all 139 scoped units; the 104 exam responses cover
all 62 code/year partitions, including repeated empty confirmations. Career encoding, CSV
quoting/width, invalid field/date and quota-denial checks were also exercised.

The original corpus was read-only during comparison;
synthetic tests used disposable databases, and real Hop source runs wrote to `ingestion`.
The graph uses `ingestionBatch`, `ingestionRecord` and named business entities in STAGING scope.
Those source-graph checks preceded the separate [LLM workflow implementation](../hop/llm/README.md).
The initial implementation used mock responses. Paid DeepSeek evaluations began on
2026-09-12; see the [LLM verification record](hop-migration/llm-status.md) for results
and remaining model-quality limitations.
The current Python ETL deployment was not changed.

## Manual snapshot retention

Use [retention/preview.hwf and execute.hwf](../hop/retention/README.md) to select the oldest N eligible snapshots or snapshots older than N days. The preview protects current and referenced snapshots; execution archives last-known records before pruning raw files and historical PostgreSQL/Neo4j snapshots. No retention schedule is installed. See the [server runbook](hop-migration/server-runbook.md) for host/container paths and future-agent editing instructions.

## Ontology completion after source loading

See [the active ontology implementation and verification ledger](hop-migration/ontology-completion.md)
for the current full-corpus LLM pass, independent extraction/link review, attachment work and
remaining canonical publication requirements. Source ingestion READY and LLM validation do not
alone mean the serving ontology is complete.

After the user explicitly resumes attachment work, select those exact inputs with
[`ontology/bind_document_inputs.hwf`](../hop/ontology/bind_document_inputs.hwf)
before freezing the release's reviews. The
[ontology guide](../hop/ontology/README.md) explains the required complete input
set and how accepted claims retain their source response, document, page or
HWPX table-cell evidence. Binding inputs does not accept an extraction or activate
a release.

The [native ontology assembly guide](../hop/ontology/README.md) now documents
`ontology/install.hwf`, `prepare_release.hwf`, `assemble_reviewed.hwf`, and
`load_release.hwf`, plus
release and claim inspection pipelines. These assemble pinned source records and
independently reviewed claims in PostgreSQL. The new native Neo4j candidate loader
is installed and has passed the full saved-data fixture. It seals review selection
and verifies all graph properties and memberships, while the release remains
PREPARING. Serving activation and the remaining ontology contracts are still
under implementation; finish intended reviews before sealing a production release.

For subsequent condition normalization, follow
[the typed requirement guide](../hop/ontology/requirements.md). The deployed native
import/review/freeze/read workflows preserve the original Korean evidence and
condition tree. Follow the [typed graph/export guide](../hop/ontology/requirement-graph.md)
to project a frozen cut into Neo4j and JSON-LD v3. Confidence calibration and
production normalization remain unfinished; installation does not create reviews
or publish a release.

For assigning a primary product occupation from reviewed duties, follow the
[product occupation review guide](../hop/editorial/occupations.md). Its native
import/review/freeze/read workflows have passed local tests but are not deployed.
They preserve a decision for each posting, including out-of-scope and unresolved
outcomes. The [occupation graph/JSON-LD v5 adapter](../hop/editorial/occupation-graph.md)
also passed local native tests. Deployment, production assignments and calibrated
confidence remain unfinished.

To inspect those frozen assignments alongside normalized requirements, use the
[derived-claim read guide](../hop/editorial/derived-queries.md). Its v3 entity
reader keeps original source fields separate from reviewed interpretations and
links each accepted claim to exact evidence and target revisions. The four
native readers passed local tests; deployment is pending.

For later cohort preparation, the [reviewed duplicate-group guide](../hop/cohorts/README.md)
provides native import, independent review, freeze and inspection workflows.
These preserve every source posting. The
[country/experience profile guide](../hop/cohorts/profiles.md) describes the next
native stage: exact source citations, reviewed experience bounds and separate
claim scope for mixed postings. These stages are local and not deployed;
production assessments, full cohort filters, representative selection,
statistics and graph integration remain unfinished. Do not add duplicate or
profile freezes to the graph-loading sequence until that integration is available.

### Recruitment notices and job-description attachments

**Deferred until explicit user resumption.** The instructions below describe the
installed workflows for later use. Do not launch another attachment preview,
download/parse run, input rebuild or attachment-aware model batch while the hold
applies. Saved documents and results remain available for read-only inspection;
see the [hold status and restart handoff](hop-migration/attachment-status.md).

Native attachment fetching/parsing now has a separate
[operator guide](../hop/attachments/README.md) and
[deployment/full-pass ledger](hop-migration/ontology-completion.md#native-attachment-ingestion--2026-09-12).
Use `attachments/process_snapshot.hwf` with an exact JOB-ALIO run, explicit initial
posting IDs and `EXECUTE_DOWNLOADS=N` to plan. The dedicated native CLI needs the
JDK XML transformer setting documented there; the Hop Web JVM has not been restarted
to apply it. The existing source refresh does not automatically run this workflow.
Attachment text is stored with document hashes and page/section provenance.
Use `attachments/prepare_inputs.hwf` to freeze versioned input bundles and optionally
create a new EVAL dataset. Run `llm/evaluate.hwf` with that dataset, or `llm/enrich.hwf`
with the reported `INPUT_BUNDLE_IDS`, the same job snapshot, `ko-v6` and `REVIEW`.
Start with `EXECUTE_REQUESTS=N`. See the operator guide for retry precedence,
cache hashes and exact section ranges. Document-format coverage, semantic review
and production claim publication remain unfinished and deferred under the hold.


HWPX paragraphs and tables now have a separate native reconstruction workflow:
`attachments/structure_hwpx.hwf`, followed by
`attachments/prepare_structured_inputs.hwf`. The latter adds `HWPX_BATCH_IDS` to
the input-selection parameters and creates v2 bundles while retaining v1 history.
See [the HWPX operator instructions](../hop/attachments/README.md#reconstruct-hwpx-paragraphs-and-tables)
for exact parameters, outcome meanings and model layout coordinates, and the
[deployment/readback ledger](hop-migration/ontology-completion.md#native-hwpx-structure-and-full-v2-inputs--2026-09-12)
for current coverage. Neither preparation nor a successful parser run accepts
model claims or activates the ontology release.
