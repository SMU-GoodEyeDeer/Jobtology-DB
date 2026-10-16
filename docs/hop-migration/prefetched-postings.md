# Prefetched JobKorea postings and local processing responsibilities

The supplied dataset can support local archival, structured-field normalization
and scoped listing-metadata processing. It cannot currently support complete
description extraction: full description bytes are absent. The local-only
JobKorea importer and source-graph bridge are verified in isolated fixtures and
the October 8 production load of the supplied 8,434-posting snapshot. All 8,434
listing inputs are frozen with original-file provenance. The later October 8
instruction authorizes paid linking and clearly labeled metadata-to-NCS
occupation inference; broader serving extensions remain later scope. See the
[current handoff](current-handoff.md#october-8-full-local-dataset)
for exact production receipts.

## Governing user decisions

Use only supplied pre-scraped data. Do not request source pages, description links, signed S3 links, iframe endpoints, or images, including HEAD requests, link refresh, and fallback recovery. URLs may be retained as evidence references; they are not fetch instructions. Process descriptions only when their text or archived bytes are supplied locally. Missing content is an explicit outcome and does not block metadata import.

The scraper supplies source observations and raw job content when available. Jobtology-DB owns import provenance, normalization, quality reports, embeddings, enrichment, and processing metadata. These pipeline fields are not additional mandatory scraper output. The user is checking whether the scraper's date extraction can be improved.

On October 8 the user first authorized full local ingestion and deterministic
input preparation, while holding paid linking pending account readiness. They
later confirmed account readiness, instructed linking to proceed, and selected
`ALLOW INFERRED METADATA MATCHES`. This lifts the earlier hold for this task.
Use a separate, clearly labeled metadata-to-NCS occupation inference path with
provenance, abstentions and actual review status. Keep confidence NULL/UNASSESSED;
validated bulk outputs may remain STAGING/UNREVIEWED, while reviewed pilot results
record their individual independent decisions. Begin with a small
paid pilot and expand toward all 8,434 supplied listings only when quality and
measured cost permit within the coordinator's explicit total accounting budget,
including upstream BYOK inference and router fees. The initial cap/default was
$4.75. After the measured five-row pilot, the coordinator selected a $5 combined
task cap, with $4.9999922 available to the native inference ledger after reserving
the health-probe cost. The user corrected the earlier $100 statement to $50
available OpenAI credit and asked to retain the lighter model; this balance is
user-reported, not API-verified. Preserve credentials,
accounts and provider routing. The source-URL request restriction remains in force.
OpenRouter credits and upstream BYOK funding are separate: a router balance or
historical BYOK usage does not establish current upstream account credit. Actual
paid responses must identify the route and report router/upstream costs separately.

The user's full production datasets will use **NDJSON, one JSON object per
physical line**, for safer large exports. This is the agreed export format;
the JobKorea adapter now implements streaming NDJSON alongside the original
bounded JSON-array path. Each object line must end with LF; CRLF is accepted.
A complete final object without LF is rejected as a framing error. Blank lines,
malformed/truncated JSON, invalid UTF-8, duplicate keys and duplicate native
posting identities cannot produce READY.

Application start dates are optional and low priority; do not reject records for missing starts. Under the user's latest 2026-10-07 policy, missing or NULL application end dates in prefetched JobKorea postings mean assumed `상시채용`. Normalize them to `deadline_kind=ROLLING` with a NULL end date and record `deadline_basis=USER_POLICY`. This supersedes the earlier UNKNOWN treatment for this case. Preserve source wording, precision, and timezone for supplied deadlines; a day-level deadline remains a whole date rather than an invented timestamp at midnight.

## Observed local datasets

Assessed on 2026-10-07 KST. File path relative to repository root: `../jobtology/j_muwj57zxdc6o3utkq.json`.

| Property | Observed value |
| --- | --- |
| Size | 2,120,716 bytes |
| SHA256 | `934b51137ad3e4d38fb369719ae1ff654af932ea4b9f4c4d5e83ed21626bde95` |
| Rows | 887 JSON objects, all JobKorea |
| Identity | 887 unique product-page references with `/Recruit/GI_Read/<numeric-id>` paths |
| Duplicates | No duplicate object keys, exact rows, or native posting IDs |
| Shape | 25 distinct key sets; 24 unique fields |
| Descriptions | No embedded full description; no adjacent archived HTML or images |
| Collector evidence | No collector version, capture time, batch ID, or completeness manifest |

Every row has the same list-collection input: `max_pages=5`, `job_category_codes=duty`, and list menu `duty`. This capped batch includes broad jobs, including non-CS and multiple-position postings. Absence from the batch is not evidence of closure. CS eligibility needs later field-level screening.

### Field quality

| Field | Observation and implication |
| --- | --- |
| `application_start_date` | 599 present strings; exactly 288 missing keys; no explicit nulls or blanks. Missing values are accepted. |
| `application_end_date` | 808 present strings; exactly 79 missing keys; no explicit nulls or blanks. The 79 missing values normalize to assumed `상시채용` with NULL end dates under the user policy. |
| Present application dates | All encoded at midnight UTC; no end before start. Encoding alone does not establish source timezone or instant precision. |
| End-date comparison | 14 dates precede October 7 and 19 equal October 7. These are dated observations, not live open/closed status. |
| `company_url` | Missing in 288, coinciding with the iframe group and missing start dates. |
| `company_name` | At least 253 iframe-group values are company categories, not verified employer names; other placeholders also occur. |
| `job_position` | Present in 502, but 50 say `홈페이지 지원`, an application method. |
| `job_functions` | Present in 99; absence or a position label does not establish a verified role. |
| Work details | Location missing in 1; hours missing in 427; recruitment count present in 144, ranging from 0 to 109. |
| Benefits | Tag arrays exist in all 887; 484 are nonempty. |

Title, company, salary, employment, education, and experience fields are populated in all 887 rows, but population is not semantic validation. Category-like company names include 중소기업 (82), 중견기업 (59), 대기업 (40), 벤처기업 (32), 대기업 계열사·자회사 (24), and 외국계 기업 (16). Preserve the raw values instead of treating them as named employers.

The same file and hash were rechecked on October 7. The only date keys are `application_start_date` and `application_end_date`; there is no alternative deadline field. Examples without an end-date key are posting `50109422` at zero-based array index 19 (row 20), `50115311` at index 23 (row 24), and `50090048` at index 34 (row 35). These records use the assumed `상시채용` policy. Preserve the missing key in raw evidence and record the assumption in normalized data. The user may investigate scraper accuracy separately; do not visit pages to resolve it here.

### Description references and historical observations

There are 598 signed S3 description references, 288 JobKorea iframe references, and one missing reference. All 598 signatures specify 900-second validity and expired on October 6 UTC between 10:28:31 and 10:51:05.

Before the user's no-request instruction, bounded checks observed one S3 response with `403 Request has expired`, two successful original iframe responses, and two derived fallback responses yielding 1,654 and 32 text characters respectively, with two images each. These are historical observations only. They do not authorize further requests or recommend a fallback implementation. No descriptions are recovered by this document.

### Supplied NDJSON sample

The October 7 local NDJSON sample is
`../jobtology/j_muwimlga1lq0obm7dp.ndjson`: **416 object lines, 841,618 bytes**,
SHA256 `f42cff119b4db77ff2c1bdb5d57eefd2398bae677f6fbf8d14cc390b67ae20e3`.
Its longest physical line is 4,259 bytes, including LF; the file has a final LF.
All 416 product-page references are unique. It contains 246 start-date keys and
390 end-date keys, so 170 missing starts are accepted and 26 missing ends use
the rolling-recruitment policy. Full description narrative is absent for all
416 observations. This is supplied-file evidence, with no provider completeness
or actual scrape-time claim.

## Implemented integration and remaining boundaries

The existing implementation runs real native Hop/PostgreSQL/Neo4j workflows,
with immutable source evidence, validation, graph replay and reviewed-link gates.
Verified samples include the original 887-row JSON array and supplied 416-row
NDJSON export. The supplied 8,434-posting, 21,951,764-byte composed NDJSON snapshot
passed production import, source-graph and complete frozen-input verification on
October 8. Larger advertised maxima remain unverified in production. The
original array path reads the complete bounded
file and parses its JSONB array in one transaction; its default file bound is
16 MiB and hard maximum 64 MiB, with its historical row-manifest contract retained.

The NDJSON path streams archive copy, hashing and parsing without converting the
whole file to an array. It submits bounded exact-serialization batches to
PostgreSQL, retaining one-based physical line locators (`line:1`) and zero-based
UTF-8 byte offsets/lengths, including LF or CRLF bytes. Each committed batch and
line has immutable hashes; the row manifest chains bounded chunk proofs instead
of aggregating all source payloads. Default limits are 1 GiB per file, 1 MiB per
line, 500 rows and 4 MiB per batch; hard maxima are 16 GiB, 16 MiB, 5,000 rows and
32 MiB respectively. The line bound cannot exceed the batch byte bound. These
are validation limits, not a full-volume production benchmark.

An interrupted import stays LOADING with an exact byte/line checkpoint and can
resume from its immutable archive using `RESUME_RUN_ID`. Permanent framing,
encoding or identity failures leave the file FAILED; syntactically valid source
field errors require review. Previously committed prefixes remain staged and
invisible to READY consumers. Only exact EOF, independently reverified complete
archive bytes, chunk/line/row accounting and shared source validation permit
READY. See the [adapter commands and checks](../../hop/ingestions/jobkorea/README.md).

- `hop/ingestions/jobkorea` imports supplied JSON into the shared `ingestion`
  ledger as source `jobkorea`. It generates hashes, receipt/import/processing
  timestamps, row locators, normalization and diagnostics here. Actual scrape
  time stays unknown without collection evidence. `LOCAL_FILE` documents have
  NULL HTTP status/provider result and never create HTTP request ledger entries.
- Publication follows the existing PostgreSQL READY gate. Idempotent identity
  includes file hash, parser version and policy revision. READY validates the
  supplied file (`FILE_ONLY`, `provider_complete=false`); it does not certify a
  provider census or imply closure of postings absent from the capped batch.
- `full.hwf` pins the exact accepted run, invokes the existing native
  `graph/load_snapshot.hwf`, independently verifies it and records the durable
  graph checkpoint. Failure preserves accepted PostgreSQL evidence for replay.
  Each supplied posting produces one source record and one source-qualified
  posting identity; category labels do not produce employer organization nodes.
  Graph metadata excludes raw payloads, URL references and description text.
- The optional `cs.common_posting` adapter reads native READY JobKorea records
  directly. It matches `source:posting:jobkorea:<sha256(native_id)>`, uses a
  dedicated source-field/hash contract and does not duplicate imports in
  `cs.posting_input`. JOB-ALIO/Nara identities, hashes and reviewed lineage retain
  their contracts. Native/staged identity conflicts are explicit issues.
- Locally supplied embedded description text can be accepted. Both supplied samples have
  none, so `content_status=MISSING` and `extraction_eligible=false`. HTML archive
  parsing, image retrieval, OCR and description recovery are not implemented.
  `services/document-parser/server.py` remains a PDF/HWP/HWPX/DOC/DOCX/ZIP parser;
  a URL or short listing field is not a recovered full description.
- `jobkorea-input-v1` assembles exact local listing evidence and separately
  supplied narrative into frozen LLM inputs. Normalized metadata preserves source
  uncertainty and deadline assumptions; full-description absence remains explicit.
  Audit manifests bind the exact file/run/row and record real processing events.
  Metadata eligibility does not require a full description. Titles, categories,
  employer labels and policy deadlines never become inferred work duties.
- Under the later October 8 instruction, titles, supplied roles and job-category
  evidence may support a separately labeled inferred NCS occupation association.
  This association does not establish source-stated duties, competency evidence
  or a recovered full description. Preserve exact listing locators, the pinned
  NCS target, model/version, NULL/UNASSESSED confidence, reasoning, abstentions and
  actual review lineage. Validated unreviewed bulk outputs remain clearly marked
  `STAGING`/`UNREVIEWED`; an independent pilot review does not approve other rows.
  Do not route metadata inference through the strict explicit-duty `ko-link-v1`
  contract or present it as that contract's reviewed competency link.
- A small IT/software/data candidate pilot can prepare the existing `ko-link-v1`
  extraction, explicit-duty NCS matching, independent reviews and source-qualified
  graph publication with exact run/hash gates. Publication requires both the
  JobKorea source graph and target NCS competency graph loaded in Neo4j for those
  pins; PostgreSQL READY alone is insufficient. The candidate screen remains
  unverified; unknown scope is reported. Missing duties skip matching. On October
  7 the user authorized a small paid pilot with about $9.50 available for testing
  and requested a measured per-1,000-listing cost estimate; default preparation
  still makes no paid calls. Embeddings, CS screening and broader reviewed serving
  integration remain deferred. Source-graph loading does not publish a new serving
  release. JobKorea has no scheduler refresh policy or automatic fetch/deletion.
  Manual retention planning requires a separate adapter for this local file
  layout, while existing maintenance gates and graph-writer leases still apply.

The [adapter README](../../hop/ingestions/jobkorea/README.md) provides the isolated
sample command and install contract. The [current handoff](current-handoff.md)
records verified production installation/import, source graph and every frozen
listing input, with the earlier isolated fixture receipts retained as history.

## Scraper observations and local processing responsibilities

The following divides implemented ingestion responsibilities from later processing extensions; it is not a required upstream enrichment contract. The importer accepts the existing dataset without waiting for richer exports. Preserve source dates, their original wording, and raw content when actually available; represent absent evidence explicitly. Active filtering and extraction report eligibility separately from archival acceptance.

| Responsibility | Owner and proposed handling |
| --- | --- |
| Raw source observations | Scraper supplies available raw fields, dates/phrases, references, and job content. Preserve these unchanged as evidence. No mandatory embeddings, normalization, or pipeline manifest is imposed on the scraper. |
| Identity and envelope | Jobtology-DB assigns the source/import envelope, computes file and artifact hashes, and derives string native posting IDs from supplied references. JSON arrays retain JSON Pointer/index locators; NDJSON retains one-based physical lines and exact zero-based UTF-8 byte offsets, lengths and raw-line hashes. References remain inert. |
| Event timestamps | Jobtology-DB records `received_at`, `imported_at`, and `processed_at` when those events actually occur. Preserve a known actual `scraped_at` from collection context; otherwise leave it unknown. |
| Unknown collection facts | Actual scrape time, collector version, uncaptured wording, original-page completeness, and pagination completeness cannot be recovered merely by importing. Keep unknown facts unknown; retain supplied scope such as the five-page cap. |
| Deadline normalization | Jobtology-DB produces `deadline_kind`, `deadline_raw`, `deadline_date` or `deadline_at`, timezone where known, and `deadline_basis`. Missing or NULL end dates use `ROLLING` / `상시채용` with basis `USER_POLICY`; other kinds follow supplied evidence: `FIXED_DATE`, `FIXED_INSTANT`, `UNTIL_FILLED`, `NOT_STATED`, or `UNKNOWN`. |
| Status and quality | Jobtology-DB records content outcomes, malformed-date issues, and extraction eligibility. Accept policy-assumed rolling deadlines and preserve separately observed source status. Explicit closed status takes precedence over the rolling assumption; absence from a capped batch does not imply closure. |
| Local content processing | Jobtology-DB hashes and describes supplied artifacts, preserves encoding/provenance and local locators, and extracts only available content. Proposed outcomes include `TEXT_AVAILABLE`, `IMAGE_ONLY`, `MISSING`, and `ERROR`. |
| Employer and role normalization | Jobtology-DB distinguishes named/anonymized/category-only/unknown employer values, advertised employer versus agency where supported, and job role versus application method. Preserve original fields and evidence locations. |
| Enrichment and embeddings | Jobtology-DB builds versioned metadata inputs and prepares explicit-duty extraction, NCS matching and independent reviews from available local text. Model execution is explicit. Embeddings remain a proposed extension and would record model/version, input hash, chunk locators and generation time; this document does not activate them. |

Never relabel filesystem modification time, import time, or signed-URL signature time as the exact scrape time. If collection context later supplies the actual scrape event time, preserve its provenance and timezone. A local receipt timestamp records receipt, not source capture.

For `FIXED_DATE`, populate `deadline_date` and leave `deadline_at` null. For `FIXED_INSTANT`, populate `deadline_at` with its explicit timezone or offset and leave `deadline_date` null. For other kinds, leave both null and retain the source phrase where available. Do not convert the current midnight-UTC values to fixed instants without upstream evidence about the original date representation.

For a missing or NULL `application_end_date`, the normalized end date, `deadline_date`, and `deadline_at` remain NULL; set `deadline_kind=ROLLING`, display label `상시채용`, and `deadline_basis=USER_POLICY`. Leave `deadline_raw` absent or NULL when no original phrase was supplied; the display label is a policy output. A source-stated rolling deadline can use the same kind with source evidence as its basis. Explicit fixed deadlines and closed status take precedence over the default. Keep malformed nonempty date values as validation issues rather than silently treating them as missing. `UNKNOWN` remains available for unresolved cases outside this policy.

Local normalization and enrichment may use the following evidence when supplied, without inventing missing source observations:

- Optional application start date, preserving raw wording and precision.
- Duties, required qualifications, and preferred qualifications extracted here from available raw content, retaining original spans or archive locators.
- Employer profile identifier/link as reference evidence, plus agency identity when separately stated.
- Typed salary currency, pay period, minimum/maximum and negotiability; experience bounds, education, employment type, location/remote arrangement, and headcount. Keep raw values alongside typed fields.
- Supplied local images or an already-produced OCR package, retaining hashes and text-to-image evidence. OCR capability is not currently provided by the parser; absent artifacts never trigger image retrieval here.

Do not reconstruct a missing full description from a URL, title, or other short fields. Metadata text may support its own clearly scoped processing; an embedding of that text is not evidence that the full description was available.

## Local-only importer and verification

The implemented importer archives exact supplied bytes and parses JSON arrays
or streamed NDJSON object lines. It retains raw source rows separately from normalized fields; validates
identity, counts, file hashes and row provenance; applies the rolling-deadline
policy; and reports invalid dates or rows before READY publication. Missing start
dates, policy-assumed rolling end dates and absent descriptions do not block
metadata acceptance. Replay of the same file/parser/policy preserves accepted
rows and identities; conflicting evidence is visible instead of being overwritten.

Native `full.hwf` reuses the shared PostgreSQL-to-Neo4j snapshot loader and its
verification/checkpoint path. The default `DRY_RUN` requires the disposable
harness's marked PostgreSQL database and matching fixture Neo4j endpoint. It
creates isolated test state rather than previewing against live connections.
Run the supplied file with:

```bash
.venv/bin/python hop/ingestions/jobkorea/tests/native.py \
  --input /home/maxjo/jobtology/j_muwj57zxdc6o3utkq.json

.venv/bin/python hop/ingestions/jobkorea/tests/ndjson_native.py \
  --input /home/maxjo/jobtology/j_muwimlga1lq0obm7dp.ndjson \
  --legacy-input /home/maxjo/jobtology/j_muwj57zxdc6o3utkq.json
```

The harness uses only local container images on a new internal Docker network,
with no exposed ports or production connections. It retains a protected receipt
and logs and removes disposable containers and private input/archive scratch
files. The original JSON-array native fixture passed: all 887 rows were accepted with zero
rejections, 288 missing starts, 79 policy-assumed rolling ends, 808 fixed dates,
887 MISSING descriptions and zero extraction-eligible rows. Independent Neo4j
reads verified 887 records, 887 references and 887 distinct posting identities in
READY/STAGING, including replay and failure recovery. Native installer replay
upgraded the legacy shared checks. Focused PostgreSQL source-graph and CS
compatibility tests also passed; existing source facts, identities, hashes and
review lineage were preserved. The protected PASSED receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-35bf3b62a26c/receipt.json`;
private scratch files and disposable resources were verified removed. This
source-only fixture made no model calls. The separately authorized paid semantic
pilot and measured costs are recorded in the [current handoff](current-handoff.md).
The October 8 full production import and deterministic input preparation are
verified there; this earlier fixture remains historical evidence. Embedding
generation and broader serving extensions remain later scope. The subsequent
October 8 linking instruction lifts the earlier hold for the separate metadata
occupation inference task; new execution/publication claims require their own
verified receipts.

The NDJSON native receipt
`~/.local/state/jobtology-hop/jobkorea-dry-run-42ee0beaceeb/receipt.json`
passed 126 checks: all 416 supplied observations and independent Neo4j/replay,
genuine JVM interruption/archive-only resume, invalid-file and source-field gates,
exact redacted failure locations, five frozen semantic bundles with no model
requests, final native installer replay and original array/hash compatibility.
A generated 100,730,368-byte/512-row import-only stress file passed
with a 256 MiB Hop heap and bounded 25-batch processing. All private scratch and
disposable resources were removed. This is an isolated size/memory test, not a
full-dataset production or graph-cardinality benchmark.

Later work can add richer supplied content and downstream processing with its
own provenance, evidence and review gates. Scraper date improvements do not delay
acceptance of the available metadata. The no-request policy remains in force.
