# ALIO organizations in Apache Hop

This is the runnable ALIO implementation of the [real-data migration guide](../../../docs/hop-real-data-guide.md).
It uses native Hop 2.19 transforms/actions and PostgreSQL SQL. It does not execute Python,
JavaScript, shell scripts, or a custom plugin at runtime.

## Run in Hop Web

Open `${PROJECT_HOME}/ingestions/alio/full.hwf`, choose the **alio-local** workflow run
configuration, and use **Basic** logging. Run `MODE=SMOKE` for a one-page preview, then run
`MODE=FULL` for a new, complete snapshot. Every invocation generates a new run ID.

The workflow is already installed in the default project on Goldship. For another installation,
copy this directory into the project's `ingestions/alio/` directory and copy both
[pipeline](../../metadata/pipeline-run-configuration/alio-local.json) and
[workflow](../../metadata/workflow-run-configuration/alio-local.json) run configurations into the
corresponding project `metadata/` directories. Configure a PostgreSQL connection named
`jobtology-postgres` and initialize the `ingestion` schema using the guide's bootstrap scripts.
Hop CLI is available through `hop-run.sh` in the existing Hop Web container.

| Parameter | Default | Purpose |
|---|---|---|
| `MODE` | `FULL` | `SMOKE` fetches page one; `FULL` follows the first page's declared total. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/alio-raw` | Persistent directory for exact response bytes. |
| `API_KEY_FILE` | `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv` | Runtime credential file; outside the versioned project. |
| `MAX_PAGES` | `100` | Reject larger snapshots before further requests; includes both empty-confirmation requests. |

The credential file has a `service_key` header and exactly one row containing the decoded
data.go.kr key. REST Client URL-encodes it. Goldship's existing ALIO test credential was copied
to this runtime file, owned by the Hop container user with mode `0600` in a `0700` directory.
No credential is included in these repository files. Changing the key file does not require
a container redeployment.

Use `alio-local` for these pipelines: it disables execution-data capture and row sampling. The
existing general-purpose `local` configuration samples rows. Keep logging at Basic; do not
preview the credential-reading transforms when collecting screenshots or sharing execution data.

## Workflow stages

| File | What it does |
|---|---|
| [full.hwf](full.hwf) | Orders all stages and sends failures through `mark_failed.hpl` to Abort. |
| [start_run.hpl](start_run.hpl) | Generates a UUID, creates the run and institutions partition atomically, and sets `ALIO_RUN_ID` on the parent workflow. |
| [fetch_page.hpl](fetch_page.hpl) | Reads the runtime key, waits 200 ms, requests one page, archives binary bytes, hashes/measures the saved file, registers the response and invokes the loader. |
| [load_document.hpl](load_document.hpl) | Reads the saved JSON, checks its envelope, splits source objects, normalizes fields and loads or rejects each object. |
| [remaining_pages.hpl](remaining_pages.hpl) | Generates the remaining page requests and executes one child per page. An empty dataset requires a second independent empty response. |
| [verify_files.hpl](verify_files.hpl) | Recomputes each selected response's SHA-256 and byte length, then records `verified_at`. |
| [finalize.hpl](finalize.hpl) | Applies validation, records the final state, and logs the run ID and counts. |
| [mark_failed.hpl](mark_failed.hpl) | Marks interrupted LOADING runs FAILED, or REVIEW_REQUIRED when rejected rows exist. |

The endpoint is fixed to `https://apis.data.go.kr/1051000/public_inst/list`, with 100 items
per page. REST pagination and hidden retries are disabled. Raw filenames include the run ID,
page, confirmation and attempt numbers; existing response files are never overwritten.
HTTP error bodies remain archived as unselected documents. A transport failure before a body is
received fails the run and uses an error branch that removes the key and request-error details
before logging the failed row.

The loader uses JSON Input for the complete saved envelope and native Database Join transforms
for JSON object expansion, SQL normalization and field validation. Open **Normalize organization
fields** to inspect the complete eight-field mapping. This implements the guide's mapping using
PostgreSQL `normalize`, JSON functions and strict date validation, instead of requiring a separate
JSON Output canvas. It retains the original object, `/result/<index>` locator, all field-lineage
pointers, nullable keys and quality flags. The final Execute SQL script uses the shared loader.

Two Get Filenames transforms contain a placeholder entry on their Files tab. Keep that entry:
Hop 2.19 uses it to initialize file-type filters even when the actual filename comes from the
`raw_filename` input field.

## Results and failures

A successful FULL run becomes **READY** only after coverage, counts, identity uniqueness,
rejections and saved-file checks pass. Its organizations appear in `ingestion.organization`.
The final log prints the generated run ID; use that ID explicitly when inspecting results:

```sql
SELECT run_id, mode, state, created_at, completed_at
FROM ingestion.run
WHERE source_id = 'alio_organization'
ORDER BY created_at DESC;

SELECT code, name, organization_type
FROM ingestion.organization
WHERE run_id = 'paste-the-FULL-run-id'
ORDER BY code;

SELECT issue, location FROM ingestion.validation_issue
WHERE run_id = 'paste-the-run-id';
```

A successful SMOKE execution is deliberately stored as **REVIEW_REQUIRED**, never READY.
Its final log excludes the expected `SMOKE_NOT_FULL` and incomplete-pagination findings from
the reported error count, but the validation view retains them. Inspect its first-page rows in
`ingestion.record`; they are not exposed through the READY-only organization view.

Invalid source objects are retained in `ingestion.rejected_row`. Missing pages, changing totals,
duplicate IDs, malformed envelopes, file changes and excessive page counts prevent READY.
Failures preserve archived bodies and partial records. After correcting a live-fetch problem,
start a new workflow invocation; do not combine pages from different runs.

This entry point covers ALIO collection and PostgreSQL loading. The
[operations workflow](../../operations/README.md) also loads Neo4j and supplies scheduled
refreshes and durable request accounting. The scheduler serializes its own executions;
direct editor runs bypass its host lock. The 64 MiB check happens after downloading and archiving;
it is not a streaming download limit.

## Verification

Executed with the native Hop 2.19 runner and disposable PostgreSQL 18 on 2026-09-10–11:

- Three-page, 201-record fixture: READY; normalized objects, lineage and quality flags matched
  the existing Python normalizer with zero differences. Only the HTTP boundary was replaced
  with Hop's native binary-file reader for offline tests.
- One-page SMOKE: 100 retained records, never READY.
- Empty source: two separately archived confirmations, READY with zero organizations.
- An empty source with a one-request budget was rejected because it requires two confirmations.
- Invalid date and floating-point identifier: rejected source object retained, REVIEW_REQUIRED.
- Duplicate IDs, missing page, changed total, malformed JSON and excessive page count: FAILED.
- Changing an archived file by one newline caused the native file-verification pipeline to fail.
- Native REST connection failure: failed run and sanitized error branch; a dummy credential
  canary did not appear in the Basic log.

Live verification loaded 100 SMOKE records followed by a FULL run of **355 organizations across
four pages**, with zero rejected rows or validation issues. The FULL run ID is
`cb6db580-6cdb-4015-8fd6-2d7f682e460a`. All 355 records matched the reference parser using the same
archived raw bodies, including source IDs, original objects, normalized fields, lineage and flags.
Five provider requests were made, including the SMOKE page. Test data was kept in a disposable
database; the current ingestion schema receives only the real ALIO runs.

Refresh automation now also requires [`operations.sql`](../../../docs/hop-migration/operations.sql).
HTTP requests reserve a durable rolling quota before they are sent. Use the
[operations workflows](../../operations/README.md) to refresh and load Neo4j together.
