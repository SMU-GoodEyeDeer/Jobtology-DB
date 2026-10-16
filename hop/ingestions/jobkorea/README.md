# Local JobKorea import and reviewed semantic linking

This adapter loads a supplied NDJSON file or JSON array into the existing
`ingestion` PostgreSQL ledger as source `jobkorea`, then uses the shared native
Hop source-graph loader.
Production installation, the supplied 8,434-posting NDJSON source graph and all
8,434 frozen listing inputs were verified on October 8. The seven official-source
refresh policies and scheduler remain unchanged. See the
[current handoff](../../../docs/hop-migration/current-handoff.md#october-8-full-local-dataset)
for the exact run, preserved archives and production receipts. The user's later
October 8 instruction authorizes paid linking and explicitly permits clearly
labeled metadata-to-NCS occupation inference; execution/publication results
require separate verified receipts.

The importer reads local files only. Source, description, iframe, image and
signed-storage references remain inert evidence. There are no job-board requests,
paid API calls, automatic downloads or closure assumptions from missing rows.
See the [dataset policy](../../../docs/hop-migration/prefetched-postings.md).
For future batches and the proposed incremental-processing work, see the
[October 16 operator assessment](../../../docs/hop-migration/2026-10-16-jobkorea-future-imports.md).

## Current format and scale

This is a working native Hop/PostgreSQL/Neo4j adapter. The original 887-row
JSON-array sample and supplied 416-row NDJSON sample exercise import, validation,
replay and source graph loading. The October 8 production receipt establishes the
supplied 8,434-posting, 21,951,764-byte composed snapshot, its source graph and all
frozen listing inputs. Larger advertised maxima remain validation bounds rather
than measured production capacity. Historical isolated semantic linking and
review/publication checks are described below.

The NDJSON path streams archive copy, hashing and physical-line parsing, then
commits bounded PostgreSQL batches. It retains exact raw bytes, line/byte
provenance and immutable batch checkpoints; manifest verification reads one
bounded chunk at a time. A line must contain exactly one complete JSON object
and end with LF (CRLF is accepted). Blank lines, BOM, malformed/truncated JSON,
invalid UTF-8, duplicate keys, trailing values and duplicate posting IDs reject
the supplied file. A complete final object without LF is also rejected.

`INPUT_FORMAT=AUTO` selects NDJSON for `.ndjson` or `.jsonl` filenames,
case-insensitively, and JSON_ARRAY otherwise. Explicit `NDJSON` or `JSON_ARRAY`
overrides the extension. The original array path still reads and parses its
whole bounded file; its parser, identities and manifest contract are preserved.

| Parameter | Default | Hard maximum |
| --- | --- | --- |
| `MAX_FILE_BYTES`, JSON_ARRAY | 16,777,216 (16 MiB) | 67,108,864 (64 MiB) |
| `MAX_FILE_BYTES`, NDJSON | 1,073,741,824 (1 GiB) | 17,179,869,184 (16 GiB) |
| `MAX_LINE_BYTES`, NDJSON | 1,048,576 (1 MiB) | 16,777,216 (16 MiB) |
| `BATCH_ROWS`, NDJSON | 500 | 5,000 |
| `BATCH_BYTES`, NDJSON | 4,194,304 (4 MiB) | 33,554,432 (32 MiB) |

All bounds are positive integers; line bytes include LF/CRLF, and
`MAX_LINE_BYTES` must not exceed `BATCH_BYTES`. Blank `MAX_FILE_BYTES` uses the
format-specific default. The maxima are acceptance limits, not benchmarks for
production throughput or graph volume.

## Data and publication contract

- Archive the exact UTF-8 source bytes under private
  `RAW_ROOT/jobkorea/<file_sha256>/source.ndjson` or `source.json`; preserve original
  row objects in PostgreSQL. Array locators remain JSON Pointers; NDJSON uses
  one-based `line:<n>` locators with exact zero-based UTF-8 byte offsets/lengths
  and raw physical-line hashes. Keep these files and raw exports out of Git.
- Derive the numeric native posting ID from the supplied product-page reference.
  File hash, parser version and policy revision identify an idempotent import.
  Replaying identical evidence preserves accepted records; conflicting evidence
  fails instead of overwriting the archive.
- Record receipt, import and processing events locally. Leave `scraped_at` unknown
  unless supplied collection evidence establishes it. File modification times,
  import times and URL signatures are not scrape times.
  On October 11 the user supplied collection time for the whole 8,434-posting
  snapshot: `2026-10-08 02:48:14 Asia/Seoul` (KST), or
  `2026-10-07T17:48:14Z`. Preserve the original receipt's NULL scrape time and
  frozen input bytes/hashes; record the later evidence separately as
  `USER_REPORTED`.
- Set document transport to `LOCAL_FILE`, with NULL HTTP status and provider
  result. Do not create HTTP request-attempt rows, including on installer replay.
- Publish PostgreSQL READY only after file, row, identity, provenance and
  normalization checks. READY means the supplied file passed validation:
  `scope=FILE_ONLY`, `provider_complete=false`. A five-page collection cap does not
  establish a complete JobKorea census or imply that absent postings closed.
- Use `deadline_kind=ROLLING`, NULL normalized end dates and
  `deadline_basis=USER_POLICY` for missing or NULL end dates. Preserve explicit
  deadlines and closed status. Malformed supplied dates require review. The
  scraper's midnight-UTC dates are normalized as calendar dates, with no invented
  fixed instant or source timezone; missing start dates are accepted.
- Keep category-like company values as `CATEGORY_ONLY`, placeholders as UNKNOWN,
  and other names as `NAME_UNVERIFIED`. An application-method label does not
  become a job role. No employer organization identities are fabricated.
- Accept missing descriptions as `content_status=MISSING` with
  `extraction_eligible=false`. Supplied embedded description text is preserved;
  HTML retrieval, image retrieval, OCR and parser recovery are not implemented.

`full.hwf` imports and validates PostgreSQL, pins the exact `JOBKOREA_RUN_ID`, runs
`graph/load_snapshot.hwf`, then writes the existing `hop-graph-v2` checkpoint.
Graph failure leaves PostgreSQL READY and skips a new success checkpoint; retry
uses the same local evidence and run. The shared loader independently verifies
stable entities, selected current source facts, labels, titles and direct source
relationships against PostgreSQL evidence. PostgreSQL retains source records,
snapshot membership and immutable projection proofs; Neo4j has no ingestion
batch/source-record scaffold nodes.

Each row produces one source record and one posting reference. Posting identity
is `source:posting:jobkorea:<sha256(native_posting_id)>`, matching
`cs.external_posting_identity`. The graph exports an explicit metadata whitelist;
raw payloads, signed URLs and description text stay in PostgreSQL. If CS is
installed, `cs.common_posting` reads native READY records directly; the importer
does not duplicate them into `cs.posting_input`. Native/staging identity conflicts
are explicit validation issues. Existing JOB-ALIO and Nara facts, identifiers,
source hashes and saved reviews retain their contracts.

## Later collection-time evidence and graph date metadata

`ingestion.jobkorea_collection_time_evidence` holds separately supplied collection
time, bound to the exact run and file SHA256, with its `USER_REPORTED` basis,
reported timezone, opaque evidence reference and actual evidence-recording time.
`ingestion.register_jobkorea_collection_time` registers that evidence without
rewriting the original import receipt, dataset provenance or frozen LLM input.
For this supplied snapshot the effective known collection time is
`2026-10-07T17:48:14Z`; the October 8 import receipt continues to show NULL because
that timestamp was unknown at import.

The shared graph stores first/latest accepted ingestion timestamps and the latest
run's collection-time evidence directly on the existing `jobPosting` identity.
They follow accepted observations that contain the posting, independently of
display-name selection. Replaying the graph preserves ingestion dates. This
adds metadata while retaining the source-record, membership and proof history in
PostgreSQL and performing no source or model request. See the
[graph property contract](../../graph/README.md#posting-ingestion-dates) and the
[current runtime checkpoint](../../../docs/hop-migration/current-handoff.md#october-11-posting-ingestion-date-metadata).

## Run the supplied sample in isolation

From the repository root, use the harness rather than production connections:

```bash
.venv/bin/python hop/ingestions/jobkorea/tests/native.py \
  --input /home/maxjo/jobtology/j_muwj57zxdc6o3utkq.json

.venv/bin/python hop/ingestions/jobkorea/tests/ndjson_native.py \
  --input /home/maxjo/jobtology/j_muwimlga1lq0obm7dp.ndjson \
  --legacy-input /home/maxjo/jobtology/j_muwj57zxdc6o3utkq.json
```

The harness uses already-local PostgreSQL, Neo4j and Hop images with `--pull
never`. It creates uniquely named disposable containers on one internal Docker
network, exposes no ports, supplies fixture-only connection metadata, installs
the SQL, runs the native import/graph workflow and repeats it. It checks failure
and recovery gates and writes a protected receipt beneath
`~/.local/state/jobtology-hop/jobkorea-dry-run-<token>/receipt.json`. Fixture
containers, network and private source/archive scratch files are removed at the
end; receipt and protected logs remain. `--import-only` on `native.py` omits Neo4j
verification and does not establish a graph pass. The NDJSON harness additionally
tests a real JVM halt after committed batches, archive-only resume, invalid-file
gates, CRLF/AUTO dispatch, cross-format identity/content-hash stability, the
original array regression and a generated file larger than 64 MiB with a
256 MiB Hop heap. Its stress import omits graph loading; `--skip-large` is a
development-only partial pass.

The verified NDJSON receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-42ee0beaceeb/receipt.json`
(126 checks, cleanup verified): 416 supplied observations passed READY and
independent Neo4j/replay checks, archive-only interruption recovery passed, and
five semantic input bundles prepared with zero model requests. Exact redacted
failure line/byte diagnostics and final source-installer replay passed. The generated
100,730,368-byte/512-row stress file completed 25 bounded batches with a
256 MiB Hop heap; its largest batch was 4,131,519 bytes/21 rows. This establishes
the tested size/memory behavior, not full production cardinality or graph scale.

`MODE=DRY_RUN` is the workflow default. It writes only after checking the harness
isolation flag and token, the marked disposable PostgreSQL database and matching
fixture Neo4j endpoint. It is not a transaction-only preview against live
connections. `MODE=IMPORT` is the explicit write mode for a configured staging
project or authorized production import. The October 8 production operation used
this mode; the earlier isolated receipts remain separate historical evidence.

## Install and run in a configured staging project

Install the shared ingestion schema/checks and operations ledger, existing
enrichment dependencies, retention support and optionally the CS interface.
Then run `install.hwf` through the configured PostgreSQL connection; it applies
`sql/001_schema.sql` through `sql/008_ready_statistics.sql` in order. Migration 004 also
reconciles an already installed CS bridge; it works without CS. Migration 005
installs the current shared checks so an older seven-source installation gains
the JobKorea kind and validation-hook gates; 006 adds immutable NDJSON batches,
line provenance, checkpoint/resume and bounded manifest verification; 007 adds
the immutable composed-dataset provenance descriptor. Migration 008 refreshes
only `ingestion.record` statistics for `(run_id,document_id,locator)` once after
a complete NDJSON LOADING checkpoint passes the archive/state guards, before
the original manifest and READY checks. READY replay skips this refresh. It
retains the exact SQL006 seal body and rejects unexpected body, language,
result, security or configuration drift before replacement; canonical SQL006
reinstall followed by 008 and direct 008 replay are supported. All public
validators, evidence guards and manifest digest formats remain unchanged.
The configured database role needs table ownership or `MAINTAIN` for the
performance benefit; PostgreSQL otherwise warns and skips the statistics refresh.
The installer also applies the shared graph evidence and posting-date contracts.
Copy this
adapter, the shared graph
workflows, `operations/record_graph_export.hpl`, and
`retention/enter_graph_writer.hpl` / `retention/leave_graph_writer.hpl` into the
staging Hop project. Include the pipeline and workflow run configurations for
`jobkorea-local`, `graph-local` and `retention-local`. Keep connection credentials in
its private metadata.

For an explicitly configured staging project, install and run with:

```bash
/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/install.hwf -l Basic

/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/full.hwf \
  -p 'INPUT_FILE=/absolute/supplied.ndjson,INPUT_FORMAT=AUTO,RAW_ROOT=/absolute/private/archive,MODE=IMPORT' \
  -l Basic
```

`INPUT_FILE` and `RAW_ROOT` must be absolute local paths. File and batch bounds
are listed above. Symlinked input files and
archive directories, invalid UTF-8, duplicate JSON keys, malformed JSON and
conflicting archive bytes fail before successful publication. `import_local.hpl` is the PostgreSQL
entry point for a metadata-only fixture check; use `full.hwf` for graph loading and
checkpoint verification.

After an interrupted NDJSON run, retain the protected archive and resume using
the exact LOADING run ID; the original input file is optional:

```bash
/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/full.hwf \
  -p 'RESUME_RUN_ID=EXACT_NDJSON_RUN_ID,INPUT_FORMAT=NDJSON,RAW_ROOT=/absolute/private/archive,MODE=IMPORT' \
  -l Basic
```

The receipt exposes `next_byte_offset`, `next_line_number` and `batch_count`.
Recovery rehashes the immutable archive, starts parsing at its committed boundary
and preserves existing rows. A permanent format/identity failure is FAILED and
cannot resume into READY; supply a corrected new file instead. Valid JSON with
invalid source fields becomes REVIEW_REQUIRED with line/field diagnostics.
Committed prefixes stay invisible until exact EOF, complete archive verification,
chunk/line/row accounting and source validation pass. `RESUME_RUN_ID` also supports
idempotent replay of READY NDJSON evidence and source-graph recovery.

Regenerate Hop artifacts only during development:

```bash
.venv/bin/python hop/ingestions/jobkorea/tools/build.py
.venv/bin/python hop/ingestions/jobkorea/tests/graph_compatibility.py
.venv/bin/python hop/cs/tests/common_postings.py
```

## Prepare every supplied listing input locally

`tools/prepare_inputs.py` freezes deterministic `jobkorea-input-v1` bundles for
every accepted posting in an exact READY run. It uses bounded, committed batches
and a private resumable checkpoint. It creates no LLM batches, extraction items,
attempts, reservations, paid calls, review decisions or semantic links, and reads
no API key. It needs no NCS run pin. The full snapshot is validated before and
after preparation; each selected posting retains the existing receipt,
normalization, exact physical-line and frozen-bundle checks.

For a composed snapshot, first archive `snapshot.ndjson`, `occurrences.ndjson`,
`composition.json` and every original export outside Git. The occurrence map has
one entry per composed physical line, with the selected original file/hash/line/
byte range and all alternative observations. The composition descriptor binds
the source inventory, exclusions and selection policy used for the load. Register
their verified hashes, byte lengths and selected count through
`ingestion.register_jobkorea_dataset_provenance(exact_run, provenance_json)` before
creating any input bundle for that run. Migration 007 enforces this ordering and
the READY snapshot binding for both function calls and direct INSERTs. The
descriptor is immutable, except for the established retention deletion protocol.
It enters the bundle audit manifest; model-facing evidence and content hashes
remain unchanged. Existing runs without a dataset descriptor retain their exact
historical bundle manifests.

```bash
.venv/bin/python hop/ingestions/jobkorea/tools/prepare_inputs.py \
  --postgres-container POSTGRES_CONTAINER --database jobtology \
  --job-run-id EXACT_READY_JOBKOREA_RUN \
  --checkpoint-dir /private/state/jobkorea-full-inputs \
  --batch-size 250 --require-dataset-provenance \
  --register-provenance-dir /private/archive/composed-dataset
```

The optional registration flag verifies local file hashes, lengths, inventory,
selected count and composed/original byte bindings before writing the descriptor.
Copy the same verified archive to the importer's protected raw archive root under
the descriptor's `archive_relative_root` before registration. Registration replays
only an identical descriptor. Omit the flag if it has already been registered.

Use the same command and checkpoint directory to resume. The helper commits at
most 1,000 explicitly selected IDs per transaction (250 by default), writes
immutable batch receipts and safely replays a committed batch whose local
acknowledgement was interrupted. Its final receipt requires one bundle per source
posting, complete descriptor coverage and unchanged request, accounting,
review and publication counters. Preserve the checkpoint directory privately.

Full-dataset input preparation remains deterministic and makes no model
requests. The user authorized paid linking on October 8 with
`ALLOW INFERRED METADATA MATCHES`, using frozen local exports only. Keep
`openai/gpt-5.6-luna`, existing credentials/provider routing and the explicit
**$5 combined task cap** ($4.9999922 native inference after the health probe).
Defaults remain dry/off, one worker, $0.05 pilot and $4.75 daily accounting;
the SQL/helper $50 upper bound does not change this task cap. The user's $50
upstream OpenAI credit is user-reported, not API-verified. OpenRouter balances
are separate; verify actual BYOK/router/upstream response costs. The
[dated report](../../../docs/hop-migration/2026-10-08-inferred-linking-report.md)
records billing, deployment, review and failure evidence.

## Authorized metadata occupation inference

This separate path infers occupation associations from supplied `title`, `role`
and `job_functions` evidence. It preserves exact frozen-input/source/NCS
provenance, model/prompt version, reasoning, abstentions and actual review status.
All links are `METADATA_INFERRED`/`MODEL_INFERRED`, STAGING/UNREVIEWED and
NULL/UNASSESSED unless individually reviewed. Inference does not establish
source-stated duties or competency evidence; missing descriptions remain
`MISSING` and the strict explicit-duty contract below is preserved.

All 8,434 supplied listings have terminal outcomes: 5,889 matched, 2,527
abstained and 18 terminal charged citation-validation exclusions. Initial full processing and
its 5,862-edge readback are verified. The PM correction then re-evaluated 21
selected listings: **16 matches/five abstentions**, individually reviewed ACCEPT
matches (decisions 24–39), **$0.01021795** additional cost. The user example
`49550356` now matches IT프로젝트관리 (`20010401`); ambiguous/non-IT/course
controls abstained. Cumulative gross cost is **$4.08155705**, or **$0.48394084
per 1,000 unique listings**, within the unchanged $5 cap. All correction calls
were BYOK; the original single OpenRouter-funded charge remains recorded.

Native correction publication/readback completed for **5,878 STAGING edges**
(5,857 UNREVIEWED/21 ASSISTANT_REVIEWED). Independent verification at **15:38:20
UTC** passed all 5,878 payloads in 24 chunks, preserving all original 5,862
links. The user-selected AI/Cloud 개발 PM now has its reviewed IT프로젝트관리
(`20010401`) association.
Confidence remains NULL/UNASSESSED, and structural validation is not calibrated
accuracy or bulk acceptance. Raw input/full-description missing status,
source pins and strict-duty contracts remain preserved; no JobKorea source HTTP
or description-extraction charges occurred. See the
[current handoff](../../../docs/hop-migration/current-handoff.md#current-inferred-occupation-processing)
and [dated report](../../../docs/hop-migration/2026-10-08-inferred-linking-report.md).

Production `install_inferred_occupations.hwf` and canonical `llm/install.hwf`
reach **029→030→031→032→033→034→035** after required earlier contracts. They preserve the
response dispatcher, combined BYOK/router accounting and immutable old history.
Execution defaults to five listings with `EXECUTE_REQUESTS=N` through
`execute_inferred_occupations.hwf`; `execute_inferred_occupation_workers.hwf`
permits an explicit 1–8 worker bound with atomic admission and failure stopping.
Exact source/NCS pins, frozen metadata and bounded occupation candidates enter
immutable bindings before model execution. Citations must exactly match supplied
`title`, `role` or `job_functions`, with one-based inclusive codepoint offsets.
Unknown-scope/closed listings can be selected; missing or unsupported evidence
can yield an explicit abstention.

SQL 034's corrected retrieval is deployed. It offers scoped PM candidates and
labels completed unreviewed abstentions `ABSTAINED`; ordinary lexical candidates
and prior history remain preserved. The October 8 offline fixture offered
IT프로젝트관리 to 14 of 19 then-classified clear IT-project cases, leaving five
outside that correction selection. October 11 source review reassessed those as
four plausible IT-PM shortlist gaps and one system-maintenance ambiguity
(`49936406`) requiring disambiguation; this approves no occupation matches.
The earlier targeted correction, individual review and independent graph readback
are complete.
SQL 035 was deployed and verified on October 11: the 18 terminal invalid citation
outputs now display `VALIDATION_FAILED`, with zero `PENDING`. All frozen source,
input, model, review and projection history and cumulative cost remain unchanged.

Derived status distinguishes completed processing failures from pending work.
SQL 035 reports `VALIDATION_FAILED` when the selected item's current
categorization attempt is completed and `REJECTED`, without a validated result;
this includes unpaid planning/input/budget rejections as well as invalid model
responses. `REQUEST_FAILED` denotes a completed `ERROR` attempt; its cost may
still be unknown and its reservation retained. These labels do not authorize a
retry or imply review rejection. Unsent, running, budget-blocked or incomplete
attempts remain `PENDING`. Validated output without a captured result also remains
`PENDING`. The latest item and its current `categorization_id` control this
classification, including reused attempts; an older failure cannot override a
newer pending item. Validated matches, abstentions and latest review decisions
retain their existing status semantics.

The October 9 official-source NCS refresh supplied identical normalized catalogue
content under a new run identity. Historical inferred links retain the original
NCS pin. An October 11 native read-only aggregate confirmed all 5,878 historical
current VERIFIED edges, while the SQL projector for that old pin returns zero
because publication requires the latest READY pin. See the
[dependency-refresh checkpoint](../../../docs/hop-migration/current-handoff.md#october-11-runtime-and-catalogue-refresh-review).
Rebinding and new paid work are separate decisions; a new pin's empty
pair-specific spend ledger does not reset this cohort's cumulative task budget.

The local abstention audit exports a read-only frozen snapshot and recomputes
SQL 034's current v3 shortlist against the original pinned catalogue. It makes
no model or source requests and changes no production rows. Keep outputs outside
Git; the offline grouping command needs only the protected export:

```bash
python3 hop/ingestions/jobkorea/tools/audit_abstention_coverage.py export \
  --pg-container "$JOBKOREA_PG_CONTAINER" \
  --output "$JOBKOREA_PRIVATE_AUDIT_DIR/frozen-abstentions-v3.json"
python3 hop/ingestions/jobkorea/tools/audit_abstention_coverage.py audit \
  --input "$JOBKOREA_PRIVATE_AUDIT_DIR/frozen-abstentions-v3.json" \
  --output "$JOBKOREA_PRIVATE_AUDIT_DIR/abstention-groups.json"
```

Set the PostgreSQL container and private output directory explicitly. The export
defaults to this cohort's frozen JobKorea/NCS pins. `--skip-counterfactual` exports
original shortlists without asserting current v3 coverage. Groups are
`HEURISTIC_DIAGNOSTIC_UNREVIEWED`: overlapping literal-field flags and model
abstention reasons help prioritize later review; they do not establish candidate
gaps, correct occupations or reviewed associations.

The following planning example retains the historical frozen NCS pin. The latest
READY guard rejects that pin after the October 9 refresh. Future planning needs
an explicit plan for NCS snapshot rollover and cumulative accounting across pins
that retains the original task cap; changing `--ncs` alone does not provide that
accounting protection.

Frozen-cohort v2 planning example:

```bash
python3 hop/operations/run_inferred_occupations.py plan \
  --prompt-version ko-metadata-occupation-v2 \
  --retrieval-revision metadata-occupation-lexical-v3 --limit 5
```

Select v2 with `--prompt-version ko-metadata-occupation-v2` or native
`PROMPT_VERSION=ko-metadata-occupation-v2`. Prompt/execution defaults remain
v1/off. The operator helper defaults to corrected v3 retrieval for fresh batches;
`--retrieval-revision legacy` preserves old request identity. Native
`RETRIEVAL_REVISION` defaults to blank, which preserves legacy retrieval and
existing v1/v2 batch replay. SQL also treats omitted/NULL/empty revision as legacy.
Use explicit `RETRIEVAL_REVISION=metadata-occupation-lexical-v3` for native corrected
retrieval. Re-evaluation requires exact IDs and shares the cumulative cap.
The helper
verifies both immutable prompt/schema versions, selected version and deployed
SQL bytes. New requests bind exact candidate hashes without rewriting old
bindings or cost. Default selection skips postings already validated, skipped
or charged at the same source/NCS pins. Charged failures are retained without
retries; fresh batches select unsent work. Re-evaluation requires explicit
`--posting-ids`/`POSTING_IDS`, a reviewed challenge selection and a fresh immutable
batch; it shares the cumulative task cap.

Independent reviews use `metadata_occupation_review_packet(batch)` and
`decide_metadata_occupation(result,decision,reviewer,kind,notes)`. A named reviewer
must differ from the result actor. ACCEPT/REJECT decisions preserve their append-only
history; a latest rejection excludes the result from graph projection. Review
status describes actual review, so a reviewed pilot does not make other outputs
`ASSISTANT_REVIEWED`.

`publish_inferred_occupations.hwf` projects the distinct relation
`INFERRED_NCS_OCCUPATION` between existing source-qualified posting and NCS
occupation entities. It requires current exact READY pins, PostgreSQL source-graph
checkpoints and both native Neo4j source graphs. A singleton retention writer
freezes row hashes, readback verifies every edge payload and total, and failure
marks only its own projection token failed. Default `INCLUDE_UNREVIEWED=N` excludes
unreviewed outputs; `Y` permits validated outputs explicitly marked `UNREVIEWED`
under the current task. All edges and their projection remain `STAGING`, with
`basis=METADATA_INFERRED`, `assertion_kind=MODEL_INFERRED` and unassessed confidence.
Idempotent candidate identities prevent duplicate edges; prior edges excluded by
the latest result/review have `current=false`. This path does not activate an
ontology release or change existing competency links/catalogue consumers.

The native graph regression runs with
`python3 hop/ingestions/jobkorea/tests/inferred_graph_native.py`. It creates
unique disposable Hop/PostgreSQL/Neo4j containers on an internal network and
injects only a guarded synthetic response. It exercises publication/readback,
replay, individual review, rejection retirement and source-graph failure cleanup
without reading production connections or making source/model requests.

## Prepare a small semantic-linking pilot

After the source importer and existing LLM/retention modules are installed,
`install_linking.hwf` replays the required shared contracts and applies LLM
`027_jobkorea_inputs.sql` and `028_jobkorea_linking.sql`. This installation and
the default preparation workflow make no model requests.

```bash
/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/install_linking.hwf -l Basic

/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/preview_linking.hwf \
  -p 'JOB_RUN_ID=EXACT_READY_JOBKOREA_RUN,NCS_RUN_ID=EXACT_READY_NCS_RUN,PILOT_LIMIT=5' \
  -l Basic

/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/prepare_linking.hwf \
  -p 'JOB_RUN_ID=EXACT_READY_JOBKOREA_RUN,NCS_RUN_ID=EXACT_READY_NCS_RUN,PILOT_LIMIT=5,EXECUTE_REQUESTS=N' \
  -l Basic
```

The read-only preview counts the complete supplied snapshot and reports a bounded
IT/software/data candidate selection. Its lexical screen is a selection aid:
`CANDIDATE` remains unverified, and `UNKNOWN` does not establish that a posting is
outside the requested scope. Preparation pins the current READY JobKorea and NCS
runs, freezes the selected inputs and plans the ordinary native extraction
requests. The default pilot contains at most five postings; the hard cap is 25.
It does not automatically select the entire source.

`jobkorea-input-v1` preserves exact supplied strings for title, role, experience,
categories and other listing fields. Separate normalized metadata retains
employer uncertainty and deadline policy bases. Raw file/run/row bindings and
import/scrape timestamps remain in the audit manifest. Evidence uses original
line IDs and one-based inclusive codepoint offsets; blank lines retain their
numbering gaps. Reordered identical observations retain a model content hash,
while each bundle remains bound to its exact source run and row. Original
ingestion records stay unchanged.

Missing full descriptions remain `MISSING`, with
`full_description_eligible=false`; metadata extraction has its own eligibility.
No assembled metadata is stored as an original description. Titles, role names,
job categories, employer labels and policy-assumed deadlines cannot establish
work duties. `ko-link-v1` requires explicit supplied narrative evidence before
NCS matching. The current description-free sample can produce
`NO_EXPLICIT_DUTIES`, which requires no categorization request and creates no
supported NCS link. Future supplied local narrative can pass the same evidence,
independent extraction-review and independent link-review gates.

Default preparation uses `EXECUTE_REQUESTS=N`, `ACCEPTANCE_POLICY=REVIEW`,
`MAX_COST_USD=0.25`, `DAILY_BUDGET_USD=0.25`, `REQUEST_RESERVE_USD=0.05` and
`MAX_REQUESTS=10`. The preview reports request counts and reservation coverage;
reservations are accounting limits, not measured provider charges. At the default
five-posting cap, the worst-case extraction reservations equal the full batch cap,
so the initial preview shows zero additional matching reservation coverage.
Completed requests settle at their reported actual cost, including upstream
inference charges for BYOK, and release unused capacity; inexpensive sequential
responses can therefore leave room for matching.
Unfinished requests or responses with unknown cost retain their reservations.
Existing OpenRouter/OpenAI BYOK routing,
protected key-file handling and configurable model parameters are reused.

After loading the source and checking the preview, the authorized bounded paid
pilot can run through the same entry point. This example keeps five postings and
ten requests, raises accounting caps deliberately to $1, and uses the existing
OpenRouter key-file default `${HOP_CONFIG_FOLDER}/secrets/openrouter.csv`:

```bash
/opt/hop/hop-run.sh -j STAGING_PROJECT -r jobkorea-local \
  -f /absolute/project/ingestions/jobkorea/prepare_linking.hwf \
  -p 'JOB_RUN_ID=EXACT_READY_JOBKOREA_RUN,NCS_RUN_ID=EXACT_READY_NCS_RUN,PILOT_LIMIT=5,EXECUTE_REQUESTS=Y,MAX_COST_USD=1,DAILY_BUDGET_USD=1,MAX_REQUESTS=10' \
  -l Basic
```

The report returns the exact batch/run pins, request counts and costs. Use its
`BATCH_ID` with `llm/export_link_review.hwf` to create a new private `REVIEW_FILE`
containing frozen source excerpts, extraction revisions and candidate definitions.
Fill explicit extraction/link decisions, required notes and the actual reviewer
kind, then apply them with `llm/import_link_review.hwf`. For individual items,
`llm/capture_extraction.hwf`, `llm/review_extraction.hwf`,
`llm/import_model_links.hwf` and `llm/review_link.hwf` provide the same separate
review stages. The [existing review and publication instructions](../../../docs/hop-migration/linked-ingestion.md#5-review-and-publish)
specify their parameters, correction handling and `llm/publish_links.hwf`.

On October 7 the user authorized a small paid IT/software/data pilot with about
$9.50 available for testing and requested an estimated LLM cost per 1,000
listings. Defaults remain off. Paid results and measured token/cost estimates
must distinguish extraction, matching, cache reuse and conservative reservations;
the earlier isolated zero-cost importer receipt remains historical evidence.

For a measured fresh-input estimate, let `E` be mean extraction cost per listing,
`M` mean matching cost per matching request, and `q` the fraction of listings that
have supported explicit duties and receive a matching request. Estimated cost
for 1,000 listings is `1000 × (E + q × M)`, assuming one extraction and at most one
matching request per listing. Report the pilot size and observed token usage with
these means. With extraction cache-hit fraction `cE` and matching cache-hit
fraction `cM`, use `1000 × ((1-cE) × E + q × (1-cM) × M)`; exact cached reuse makes
no new provider request. A description-free pilot with no explicit duties
has `q=0`, so it measures extraction only and cannot establish a duty-rich
matching price. Budget reservations are excluded from this billing estimate.

Publication uses the existing reviewed-link workflow with exact JobKorea/NCS
pins. It requires accepted extraction and NCS-link decisions, the verified
JobKorea source-graph checkpoint, and the target NCS competency graph loaded in
Neo4j for the pinned NCS snapshot. PostgreSQL READY alone does not supply those
graph nodes. Preparation alone does not accept model outputs or publish links.

## Verified sample and remaining scope

The isolated native fixture passed on October 7, 2026. It imported all 887 rows
with zero rejections: 288 missing starts were accepted, 79 missing ends became
policy-assumed rolling recruitment, and 808 supplied ends remained fixed dates.
All 887 descriptions were MISSING and none was extraction-eligible. Actual scrape
time remained NULL; receipt, import and processing timestamps were recorded.

Independent Neo4j reads verified 887 records, 887 references and 887 distinct
posting identities in READY/STAGING. Native install/replay upgraded the legacy
shared checks; source/graph replay preserved records and one durable checkpoint.
Injected graph failure preserved PostgreSQL READY and skipped a new checkpoint;
recovery, malformed-source and invalid-file gates passed. Private scratch files,
containers and the internal network were verified removed. The protected PASSED
receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-35bf3b62a26c/receipt.json`.
This was isolated verification, with no production writes, source requests or
paid calls. See the
[current handoff](../../../docs/hop-migration/current-handoff.md).

The later full native semantic fixture passed 52 checks in
`~/.local/state/jobtology-hop/jobkorea-dry-run-64846daa6943/receipt.json`.
It counted all 887 sample rows, 587 lexical IT/software/data candidates and 300
unknown-scope rows; prepared a five-posting pilot with no key reads or model
requests; and checked missing-duty abstention. A separately labelled synthetic
local narrative exercised extraction, NCS matching, independent reviews,
Neo4j publication/replay and successful no-op handling after work was exhausted.
It made no source or paid requests, and private scratch/resources were removed.
Canonical `llm/install.hwf` replay through 028 also passed 36 assertions in
`~/.local/state/jobtology-hop/jobkorea-dry-run-a5944efbd9da/receipt.json`, preserving
bundle verification, input fields, reviewed projections and CS hashes before
successful Neo4j publication/replay and no-op checks. Cleanup passed.

The authorized paid pilot made seven validated OpenRouter/OpenAI BYOK calls in
disposable state and incurred $0.00442920 in reported upstream inference charges,
with $0 observed router fees. Five real metadata listings cost $0.00326475 and
skipped all matching requests because they had no explicit duties: the observed
mean scales to about **$0.65 per 1,000 comparable metadata listings**. A separate
short synthetic narrative/matching pair tests compatibility rather than real
full-description pricing. The [measured cost table and assumptions](../../../docs/hop-migration/current-handoff.md#measured-paid-pilot-cost)
retain exact token/cost figures, cache-write accounting, receipts and test-review
scope. No production installation or paid-output publication occurred.

Semantic input preparation and the existing reviewed NCS-linking path now have a
JobKorea adapter. Embeddings, CS eligibility review and live catalogue/serving
extensions remain deferred. The deterministic importer does not activate paid
processing or publish a reviewed serving release. JobKorea has no
refresh policy, automatic fetch or automatic deletion. Existing retention gates
and graph-writer leases apply, but manual retention planning needs a JobKorea
adapter for its file layout and is currently unsupported.
