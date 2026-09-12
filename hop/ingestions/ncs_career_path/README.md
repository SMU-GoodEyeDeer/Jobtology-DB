# NCS career paths

Run `full.hwf` with `reference-local` and Basic logging. It downloads the pinned
public CSV artifact `FILE_000000002844861`, saves the original bytes, checks the
encoding and CSV structure, and uses native CSV Input to load every row.

Install `schema.sql`, `reference-support.sql`, `career-support.sql`, `checks.sql`
and `operations.sql` from `docs/hop-migration` first. No API key is required by this
source. It uses the private `jobtology-postgres` connection.

`RAW_ROOT` defaults to `${PROJECT_HOME}/data/ncs_career_path-raw`. `MODE=FULL` accepts
only a complete valid file; `MODE=SMOKE` reads the file but stays REVIEW_REQUIRED.
`MAX_PAGES` controls request reservation; this source makes one request per run.

UTF-8 with an optional BOM is tried first, then CP949. The published ten-column
header must match exactly, including its order. Extra/missing columns, invalid CSV
quoting, undecodable bytes, HTML responses and an empty dataset prevent acceptance.
A changed header requires an explicit reviewed mapping update. Quoted commas,
doubled quotes and quoted line breaks are supported. All ten source columns remain
in `source_payload`; locators identify logical CSV records after the header.

Occupation codes are eight digits and competency codes are ten **unversioned**
digits. The workflow does not invent a versioned NCS competency match. Career-row
identities use the documented `hop-career-v1` normalized-object hash.

Read `ingestion.career_path` by `run_id`. For ingestion plus graph loading, use
`operations/refresh_ncs_career_path.hwf`. Monthly refresh checks this same published
artifact; discovering a replacement file on the portal remains a manual source
configuration update. See [operations](../../operations/README.md).
