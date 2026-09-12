# NCS competency ingestion with native Hop

This workflow fetches the full versioned NCS competency dataset, archives every response, and
loads the separate PostgreSQL `ingestion` schema. It uses native Hop transforms/actions and
bound SQL statements. No Python, JavaScript, custom plugin or model call is required at runtime.

## Run

Open **`${PROJECT_HOME}/ingestions/ncs_competency/full.hwf`**, select **ncs-local**, and use
**Basic** logging. The workflow uses the existing **jobtology-postgres** connection.

| Parameter | Default | Meaning |
|---|---|---|
| `MODE` | `FULL` | Fetch every declared page. `SMOKE` fetches one page and remains REVIEW_REQUIRED. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/ncs-raw` | Persistent directory for immutable response files. |
| `API_KEY_FILE` | `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv` | Existing protected CSV: `service_key` header and exactly one decoded data.go.kr key. |
| `MAX_PAGES` | `100` | Maximum requests in this run, including a second confirmation of an empty dataset. |

The API key is read as a row field for each request, passed through the REST parameter table,
and removed immediately afterward. No key is embedded in the workflow or stored as a workflow
variable. The `ncs-local` configurations disable row sampling and execution-data capture.

The [refresh scheduler](../../operations/README.md) runs this source every seven days.
Each `FULL` invocation creates a new snapshot UUID and retains previous
snapshots. Replaying a document within a LOADING run updates its existing document/locator row;
duplicate competency codes within a snapshot fail validation instead of being silently removed.

## Fetch and load

The workflow executes these stages:

1. Create a new run and one PAGED partition named `all`, with page size 1,000.
2. Fetch page 1, archive its exact response bytes, validate its envelope, and load its records.
3. Derive the remaining page numbers from the declared total and process them sequentially.
   An empty FULL result requires two separately archived page-1 confirmations.
4. Recheck every selected file's SHA-256 and byte length.
5. Check coverage, unique source IDs, record counts and rejected rows before setting READY.

Endpoint: `https://c.q-net.or.kr/openapi/Ncs1info/ncsinfo.do`.
REST parameters: lowercase **`serviceKey`**, **`type=json`**, `pageNo`, `numOfRows=1000`.
Requests are spaced by 200 ms. Automatic REST pagination and retries are disabled so each
request has one archived document and explicit workflow failure handling.

Items are `$.root.items[*]`; metadata is `$.root.info.totalCount`, `.pageNo`, and `.numOfRows`.
The successful NCS envelope does not contain ALIO's result code. Its saved `provider_result`
therefore stays null. The workflow requires the actual NCS envelope, checks all pagination
metadata, and rejects provider errors, missing/malformed metadata, changed totals, incorrect
page sizes, incomplete pages and request-cap overruns.

Each response is stored at:

```text
${RAW_ROOT}/<run_id>/all/page-<page>-confirm-<confirmation>-attempt-1.json
```

A transport or parsing error leaves the run unaccepted and preserves the responses already
saved. Correct the cause and start a new full run. The previous READY snapshots remain readable.
The byte-size validation occurs after downloading; this workflow does not yet implement the
streaming response-size limit. Durable request quota accounting and scheduled retry handling
are supplied by the operations SQL and workflows.

## Fields and scope

See the [exact field mappings](../../../docs/hop-migration/field-mappings.md#ncs-competency-api).
The workflow preserves:

- Full versioned `ncsClCd` as the source ID, plus its first eight characters as the occupation code.
- Competency name, definition, occupation name and the three source classification names.
- Levels 1–8. Source level 0 becomes null with `UNSPECIFIED_COMPETENCY_LEVEL`; the original zero
  remains in `source_payload`. Invalid or missing levels produce retained rejected rows.
- Every original source object, document locator and field-lineage map.

Common text fields use NFC, LF line endings and outer whitespace removal. Classification strings
retain their original spelling and whitespace, matching the existing parser. Missing classification
names become empty strings. Nested/boolean values and floating-point values in scalar text fields
are rejected.

Load **all occupations and competency units**. The 11-category CS/AI allowlist is used later to
plan qualification API requests; it does not filter this dataset. Historical counts such as
15,520 units are comparison baselines, not fixed acceptance thresholds for a fresh fetch.

## Inspect PostgreSQL and load Neo4j

Use the UUID printed by the workflow, and bind it to these queries:

```sql
SELECT run_id, state, mode, created_at, completed_at
FROM ingestion.run WHERE run_id = ?;

SELECT code, name, occupation_code, occupation_name, level, classification_names
FROM ingestion.competency WHERE run_id = ? ORDER BY code;

SELECT * FROM ingestion.validation_issue WHERE run_id = ?;
```

For Neo4j, open **`graph/load_snapshot.hwf`**, choose **graph-local**, and set `RUN_ID` to the
accepted NCS run. Its default connection is **jobtology-neo4j**. The existing graph loader writes
`ingestionRecord` snapshot rows and references to full-version `ncsCompetency` nodes and
`occupation` nodes, with readable competency/occupation names,
then verifies all properties and relationships. This source graph preserves the staging model.

`operations/refresh_ncs_competency.hwf` runs ingestion and Neo4j loading in sequence.
A graph-only retry reads
the accepted PostgreSQL snapshot and makes no provider requests. See the
[graph guide](../../graph/README.md) for graph states, repeat runs and inspection queries.

## Verification

Native Hop 2.19.0 was tested against disposable PostgreSQL 18 on 2026-09-11. The saved complete
NCS snapshot was replayed through the native parser: all 16 response files were rehashed, and
all 15,520 records matched the existing parser's source objects, normalized values, IDs, field
lineage and quality flags with zero differences. All 32 unspecified-level flags were preserved.

Fixture checks covered multi-page and confirmed-empty runs, SMOKE isolation, cross-page duplicate
codes, missing pages/confirmations, changed totals, incorrect pagination metadata, malformed
envelopes, invalid objects/codes/levels and request caps. Same-run document replay preserved the
existing rows. Altered archive bytes failed file verification. A native REST connection failure
left the run FAILED without exposing the fake test key.

The live FULL run **`a32170ed-7485-4e31-82d3-ed48b3398946`** completed on 2026-09-11 in about
138 seconds: **15,520 accepted records**, **16 archived responses**, **32 unspecified-level
flags**, and **zero validation issues**. An independent rehash/parser comparison of every
archived response and record found zero differences. All 11 occupation names needed for the
next qualification-mapping step are present, yielding **139 full-version request codes**.

An earlier FULL attempt (`d00004df-662b-42d5-95f9-6585dbb7bcf2`) timed out connecting to page 11.
It remains FAILED, and none of its 10,000 partial rows are exposed through `ingestion.ready_record`.
The successful run used a fresh batch and refetched all pages. The SMOKE run
`e7897418-ba8e-4322-8906-5c0d98b7b6e4` remains REVIEW_REQUIRED as intended.

Live source logs are in `${PROJECT_HOME}/data/ncs-logs/`:

- `20260911-170008-smoke.log`
- `20260911-170054-full.log` (failed connection)
- `20260911-170336-full.log` (accepted FULL run)

The same accepted run was loaded into Neo4j with `graph/load_snapshot.hwf`: **15,520** source
records, **31,040** references, **15,520** named competency entities and **1,094** named occupations.
The graph batch is READY, and independent record/reference/name comparisons returned zero
differences. Repeating the graph load preserved the same nodes, relationships, names and source
dates without duplicates. This load does not link NCS competencies to job postings. See
[graph verification and Browser captions](../../graph/README.md#live-ncs-and-label-update-2026-09-11).

Refresh automation now also requires [`operations.sql`](../../../docs/hop-migration/operations.sql).
HTTP requests reserve a durable rolling quota before they are sent. Use the
[operations workflows](../../operations/README.md) to refresh and load Neo4j together.
