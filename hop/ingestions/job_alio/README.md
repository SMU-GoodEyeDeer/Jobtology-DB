# JOB-ALIO: active posting list and every detail

This native Hop workflow loads JOB-ALIO into the separate PostgreSQL `ingestion` schema.
The [ALIO organization workflow](../alio/README.md) supplies its employer reference. This is
a second source: refreshing organizations does not refresh job postings.

## Run in Hop Web

Open `${PROJECT_HOME}/ingestions/job_alio/full.hwf`, select **job-alio-local**, and use **Basic**
logging. Set `MODE=FULL` to fetch all active posting list pages and every posting detail.
The final log reports the new run ID, posting/response counts, validation results and unmatched
employer count. Each invocation creates a new snapshot and preserves previous snapshots.

`MODE=SMOKE` fetches page one **and the details for all postings on that page**: up to 101
requests. It remains REVIEW_REQUIRED even if those checks pass. Its rows are available in
`ingestion.record`, but not in the READY-only posting views. SMOKE is optional after the
installation has been verified; a manual refresh uses FULL directly.

| Parameter | Default | Meaning |
|---|---|---|
| `MODE` | `FULL` | Complete collection, or first-page-plus-details SMOKE preview. |
| `UPSTREAM_RUN_ID` | `LATEST` | Resolve one READY, non-SMOKE ALIO organization run at startup. Supply an exact run ID to choose it explicitly. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/job-alio-raw` | Persistent directory for the original response bytes. |
| `API_KEY_FILE` | `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv` | Existing protected runtime CSV containing a `service_key` header and exactly one decoded key. |
| `MAX_PAGES` | `100` | Maximum list-page requests, including a second confirmation for an empty FULL result. |
| `MAX_REQUESTS` | `1000` | Total list-plus-detail request limit for this invocation. Excess declared totals fail before continuing. |

The [provider catalog](https://www.data.go.kr/data/15125273/openapi.do), checked 2026-09-11,
lists 1,000 requests for development accounts. `MAX_REQUESTS` is a per-run safeguard.
The operations ledger additionally reserves this Hop writer's rolling 24-hour quota;
calls made by other applications are not visible to it. A FULL run with
510 postings takes 6 list requests plus 510 detail requests. An empty FULL result requires
two independent list responses. There are no automatic retries.

The workflow records the resolved employer run in `ingestion.dependency`. That reference stays
fixed even if a newer ALIO snapshot appears while jobs are loading. The [host scheduler](../../operations/README.md) uses `refresh_job_alio.hwf` for daily source
and graph refresh. This `full.hwf` remains a manual PostgreSQL-only entry point.

## What each stage does

| Pipeline | Behavior |
|---|---|
| [start_run.hpl](start_run.hpl) | Validates options, selects an accepted employer snapshot, creates a UUID run, dependency and `index` partition. |
| [fetch_list.hpl](fetch_list.hpl) | Calls the active list endpoint once with `ongoingYn=Y`, page number and page size 100; saves bytes and loads that document. |
| [remaining_pages.hpl](remaining_pages.hpl) | Generates the remaining list requests from the first total; checks empty FULL results a second time. |
| [verify_files.hpl](verify_files.hpl) | Rehashes saved response files, verifies byte lengths and records verification timestamps. Runs after lists and again after details. |
| [plan_details.hpl](plan_details.hpl) | Checks list coverage, rejected rows, duplicate posting IDs and request budget before creating one DETAIL partition per posting. |
| [fetch_details.hpl](fetch_details.hpl) | Calls the detail child sequentially for every planned posting. |
| [fetch_detail.hpl](fetch_detail.hpl) | Calls the detail endpoint with `sn=<posting ID>`, archives its exact body and loads the document. |
| [load_document.hpl](load_document.hpl) | Validates list/detail envelopes, normalizes all mapped fields, enforces the requested detail identity and retains rejected rows. |
| [finalize.hpl](finalize.hpl) | Checks complete list/detail pairs and their shared fields, reports unmatched employers, and sets READY, REVIEW_REQUIRED or FAILED. |
| [mark_failed.hpl](mark_failed.hpl) | Finalizes an interrupted LOADING run while preserving archived responses and partial rows. |

Execution uses native Hop transforms/actions and parameter-bound PostgreSQL statements.
There is no Python, JavaScript, shell action, custom Hop plugin or LLM call in the workflow.
Database Join expands the saved JSON and applies the [field mapping](../../../docs/hop-migration/field-mappings.md#job-alio-postings).

The REST Clients use explicit full endpoint URLs, with REST connection metadata and automatic
REST pagination disabled. The workflow controls individual requests so their page/partition
identity, raw file, count checks and failure state stay associated. Each response uses the
existing native Binary File Output → file hash/size → PostgreSQL manifest pattern.

Original files live below `${RAW_ROOT}/<run_id>/index/` and `${RAW_ROOT}/<run_id>/details/`.
Detail filenames contain the SHA-256 of the posting ID; the database retains the original ID
and `detail-<id>` partition. This keeps provider values out of filesystem path components.
The Get File Names transforms retain the same placeholder file-list entry required by Hop 2.19
as the ALIO implementation; their actual filenames come from the input row.

String normalization preserves complete text, converts line endings to LF, applies Unicode NFC,
and trims surrounding whitespace. Invalid types, invalid calendar dates, reversed posting
dates, invalid ongoing flags and invalid headcounts are retained as rejected rows. Headcount
must also fit the existing PostgreSQL integer column. Missing optional fields stay null.
Attachment metadata remains in the original source object; attachment files are not fetched.

## Inspect a completed snapshot

Use the run ID from the final log. Both `ingestion.posting_representation` and
`ingestion.job_posting` expose **all READY snapshots**, so always select the intended run.
There is no automatic pruning of historical snapshots or raw files.

```sql
SELECT posting_id,
       normalized->>'title' AS title,
       normalized->>'organization_name' AS employer,
       normalized->>'closing_date' AS closing_date,
       normalized->>'eligibility_text' AS eligibility_text
FROM ingestion.job_posting
WHERE run_id = 'paste-the-job-run-id'
ORDER BY posting_id;
```

Each posting has two stored source records: `<posting_id>:list` and `<posting_id>:detail`.
The `job_posting` view assembles one row per pair, using non-null detail values over list values,
and retains both document locations and a `field_origin` map. Repeated FULL invocations retain
another snapshot; they do not update or deduplicate against older run IDs. Within one snapshot,
duplicate posting IDs fail validation instead of silently dropping source rows.

Titles, organization codes and posting/closing dates must agree across list and detail.
A non-null detail `ongoing` value must agree with the list. A missing detail, changed total,
malformed response, duplicate ID or conflicting pair prevents READY. A posting can change
while the API is being read; this fails validation and requires a fresh run after inspection.
An absent posting in a newer active snapshot is retained in history without inferring its status.

Employer matches use exact organization codes against the pinned ALIO run. Unmatched employers
are counted in the final log and their postings remain available; the workflow does not invent
a match or discard the posting. Inspect them with:

```sql
SELECT j.posting_id,
       j.normalized->>'organization_code' AS organization_code,
       j.normalized->>'organization_name' AS organization_name,
       dep.input_run_id AS employer_snapshot
FROM ingestion.job_posting j
JOIN ingestion.dependency dep
  ON dep.run_id = j.run_id AND dep.input_source_id = 'alio_organization'
LEFT JOIN ingestion.organization o
  ON o.run_id = dep.input_run_id
 AND o.code = j.normalized->>'organization_code'
WHERE j.run_id = 'paste-the-job-run-id' AND o.code IS NULL
ORDER BY organization_code, j.posting_id;

SELECT issue, location FROM ingestion.validation_issue
WHERE run_id = 'paste-the-job-run-id';

SELECT document_id, locator, error_code FROM ingestion.rejected_row
WHERE run_id = 'paste-the-job-run-id';
```

## Installation and credentials

Copy this directory to `${PROJECT_HOME}/ingestions/job_alio/` and both
`metadata/{pipeline,workflow}-run-configuration/job-alio-local.json` files to the project's
metadata directories. It uses the existing `jobtology-postgres` connection and
[schema/checks SQL](../../../docs/hop-real-data-guide.md#1-create-the-destination-once).

The API key is read from the same protected runtime file as ALIO; no key is embedded in these
artifacts. The dedicated run configurations disable row sampling and execution-data capture.
Use Basic logging. The REST error branch removes credentials and request error details before
aborting. Saved HTTP error bodies remain unselected documents; transport failures with no body
are reported in the execution log.

These artifacts implement collection and PostgreSQL loading. Neo4j projection, model extraction,
automatic schedules, retention and replacement of the current canonical pipeline are separate
steps in the [migration guide](../../../docs/hop-real-data-guide.md).

## Verification

Checked on 2026-09-11 with the native Hop 2.19 runner and a disposable PostgreSQL 18 database.
Offline fixtures replaced only the external HTTP boundary with Hop's native binary-file reader;
the workflow, pagination, archive, normalization, SQL writes and acceptance checks ran normally.

- A two-posting snapshot loaded four source records and assembled two postings. Original source
  objects, normalized values, source IDs, field lineage, quality flags, merged values and field
  origins matched the existing Python parser and documented merge rules with zero differences.
- A complete 101-posting fixture fetched two list pages and 101 details, became READY, and
  exposed 101 assembled postings. All 103 archived files were independently rehashed and all
  202 source records matched the reference parser, including Unicode and optional-field cases.
- SMOKE loaded the first 100 list records and their 100 details, remained REVIEW_REQUIRED, and
  exposed no READY postings. All 200 source records matched the reference parser.
- Empty FULL results required two archived confirmations. A one-request budget rejected an
  empty result before accepting it.
- Duplicate IDs, missing pages/details, changed list totals, malformed detail JSON, excessive
  request counts and list/detail conflicts prevented READY.
- Wrong returned detail IDs, invalid numeric IDs/headcounts, invalid ongoing values and reversed
  posting dates retained rejected rows and produced REVIEW_REQUIRED, with no visible postings.
- An unmatched employer was reported while preserving the complete posting. An unavailable
  upstream snapshot failed before creating a jobs run or fetching data.
- Native REST failures were exercised separately for list and detail calls. Both followed the
  sanitized error branch; the dummy credential was absent from the captured Basic logs.

Synthetic runs and employer references were isolated from the live `jobtology` database.

The live FULL workflow completed on **2026-09-11 (KST)** in approximately 5 minutes 25 seconds:

| Result | Value |
|---|---|
| JOB-ALIO run | `77ccb77b-3afc-4965-8ce5-efd687304954` |
| Pinned ALIO run | `cb6db580-6cdb-4015-8fd6-2d7f682e460a` |
| Final state | READY |
| Active postings | 506 |
| Archived responses | 512: 6 list pages and 506 details |
| Stored source records | 1,012: 506 list and 506 detail representations |
| Rejected rows / validation issues / unmatched employers | 0 / 0 / 0 |

Independent verification rehashed all 512 raw files and compared all 1,012 source records
against the existing parser on those exact bytes: source objects, normalized values, source
IDs, field lineage and quality flags matched with zero differences. All 506 assembled postings
and their field-origin maps also matched the documented list/detail merge rules.

The native Basic log contained no credential. Its sanitized persistent copy is
`${PROJECT_HOME}/data/job-alio-logs/20260911-010419-full.log`. The test container, its anonymous
database volume and server-side test project were removed after testing. The live workflow
uses the persistent default Hop project and the existing protected credential file.

Refresh automation now also requires [`operations.sql`](../../../docs/hop-migration/operations.sql).
HTTP requests reserve a durable rolling quota before they are sent. Use the
[operations workflows](../../operations/README.md) to refresh and load Neo4j together.
