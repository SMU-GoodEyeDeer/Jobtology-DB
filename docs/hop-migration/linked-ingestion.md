# Complete source ingestion and NCS linking

The [IT/AI/data completion plan](cs-posting-completion-plan.md) and
[live execution record](cs-execution-20260915.md) describe the scoped CS-role
selection, paid-output reuse, qualification joins and remaining evidence gaps.

Current endpoint (2026-09-16 KST): the reviewed NCS projection is **READY** in both
PostgreSQL and Neo4j under publication ID `cs-reviewed-20260916-tail-reviewed-c`
(completed 2026-09-15 16:24:49 UTC). Its frozen graph readback confirmed
**146 accepted posting extractions and 385 accepted NCS links**. These counts
cover all current accepted extractions; 67 selected CS positions in 46 postings
are a separate role-level scope: 54 have an accepted position-bound NCS link
and 13 remain explicit source/catalogue gaps. Four additional roles still need
scope review. The projection is the reviewed subset, not a claim that every source posting has
completed enrichment.

The final source tail reviewed ten uncertain ALIO notices using their official
A/C attachments; all ten are `OUT_OF_SCOPE` under `cs-it-ai-data-v1`. Seventeen
supported files are archived and parsed in native attachment batches
`cs-tail-docs-20260916-a` and `cs-tail-parse-20260916-a` (two image notices were
inspected manually). A saved source-bound extraction for `304822/p1` was
accepted and selected as AI work without another model call; its CBCT imaging
research has no complete current NCS ability unit to assert. See the
[notice audit](cs-notice-tail-audit-20260916.md),
[scope audit](cs-scope-tail-audit-20260916.md), and
[NCS gap audit](cs-ncs-tail-audit-20260916.md).

For the recovered rejection-evaluation set, `llm/export_link_review.hwf` staged
108 current validated postings and 453 model suggestions in 11 immutable packets.
An assistant semantic review compared each cited Korean duty with the complete
NCS definition and occupational context. The imported decisions accepted 101
extractions and 285 links, and rejected 7 extractions and 168 links. Six rejected
extractions pulled about 40 unrelated positions from a shared 한국교통안전공단
integrated-recruitment notice into unit-specific ALIO postings (IDs `304569`,
`304592`, `304596`, `304603`, `304606`, `304634`). Posting `304888` also imported
a dispatch-position label into a postal-sorting record. These need position-scoped
corrections before any links from those revisions can be published. The accepted
new links cover 68 postings; other accepted extractions can correctly have no
supported NCS match. Source runs were JOB-ALIO
`4eae07ed-1b70-4146-8e4f-75291c6b6b13` and NCS
`a32170ed-7485-4e31-82d3-ed48b3398946`.

The user resumed the narrower ETL deliverable on 2026-09-14, including attachment
processing through the existing `../document-processor` library. The earlier
2026-09-14 pause receipt remains historical at
`~/.local/state/jobtology-hop/linked-ingestion-pause-20260914T075331Z.json`.
The broader product ontology ledger is history, not a prerequisite for these links.

## Finish line

- Selected source records loaded and refreshed.
- Relevant notices and JDs parsed by document-processor, preserving source bytes,
  readable Markdown and structural/evidence identifiers. Failures stay explicit.
- Every posting accounted for by an extraction/linking outcome. No forced matches.
- Independently accepted duty-to-NCS links queryable in PostgreSQL and Neo4j,
  including evidence, model/source versions and recorded review provenance.
- Repeated publication creates no duplicates; changes and revocations remove stale
  results from current queries; new/changed postings can be processed incrementally.

## Run the document and linking stages

Use `attachment-local` for the attachment workflows and `llm-local` for the LLM
workflows. All paths below are relative to `${PROJECT_HOME}` in Hop. On Goldship,
that is `/usr/local/tomcat/webapps/ROOT/config/projects/default`; the persistent
mount, private connection names and CLI invocation are in the
[server runbook](server-runbook.md). Save public artifacts in the mounted project;
Docker does not require a Git checkout to execute them. Keep the source in Git for
review, versioning and recovery; keep fetched files and secrets out of Git.

Install additive SQL once (and again when upgrading these files):

1. Existing source, retention, attachment and LLM installers, already installed on
   Goldship. Do not create a second database or empty the current schemas.
2. `attachments/install_processor.hwf` and `attachments/install_downloads.hwf`.
3. `llm/install_linking.hwf`, `llm/install_incremental_linking.hwf` and
   `llm/install_link_review.hwf`.

The parser is the private service described in
[services/document-parser](../../services/document-parser/README.md). Hop performs
HTTP requests, SQL and graph writes natively; this separate service runs the
existing file-format library. It receives an archived path, expected SHA-256 and
extension, never an API key. Its original-file mount is read-only.

### 1. Fetch the current posting documents

Find the accepted source snapshots with Table Input (a SELECT query):

```sql
SELECT source_id, run_id, created_at FROM ingestion.latest_ready_run;
```

Run `attachments/download_snapshot.hwf` with `JOB_RUN_ID` set to the exact
`job_alio` run, a new descriptive `BATCH_ID`, `MAX_FILES` high enough for the whole
selection, and `EXECUTE_DOWNLOADS=Y`. Blank `POSTING_IDS` selects the full snapshot;
otherwise separate numeric posting IDs with `|`. The default raw folder is
`${PROJECT_HOME}/data/attachments`.

Policy `job-alio-documents-v3` selects notice/JD roles A/C, plus other non-B files
whose filenames explicitly identify a notice or JD. It supports PDF, HWP, HWPX,
DOC, DOCX and ZIP bundles containing these formats. Application forms are recorded
but not selected for duty extraction. Image-only files and other formats retain
explicit unsupported outcomes. A filename override does not change the original
provider metadata.

Every download has a database receipt and SHA-256. An identical attachment ID,
URL and metadata can reuse an existing archive; Hop reads and verifies those
bytes. `attachment.archive_reuse` records the previous attempt. This avoids
another HTTP fetch and another disk copy; it assumes an unchanged provider file
ID identifies unchanged content. A provider silently replacing bytes under the
same ID requires a separately planned fresh retrieval policy.

### 2. Parse those archives

Run `attachments/parse_documents.hwf` with a new `BATCH_ID`, the exact completed
`ATTACHMENT_BATCH_IDS` (one ID, or `|`-separated IDs in priority order),
`PARSER_REVISION` matching the service health response, sufficient `MAX_DOCUMENTS`,
and `EXECUTE_PARSING=Y`. A later attachment batch takes precedence for the same
posting/file ordinal. This supports a small corrective/supplemental download
without repeating the whole snapshot.

The service preserves Markdown, full structural JSON without binary assets,
semantic blocks, page/node locators and text offsets. ZIP members keep their own
names and content hashes; unsupported/failed members are recorded. It does not
turn image extraction into OCR. A `PARSED` state means text was obtained, not
that every image or table was understood.

Successful parses of identical bytes at the same parser revision are reused,
including the exact block identifiers. `attachment.processor_reuse` records that
provenance. Changing the parser revision deliberately creates new results. For an explicit
repair, `REUSE_SUCCESS_FROM_BATCH` can name a completed earlier parser batch:
its successful results remain unchanged, with their actual producing revision;
only the remaining rows use the new parser. Leave this parameter blank for a
complete reparse after a parser change.

```sql
SELECT state, issue, count(*)
FROM attachment.processor_document
WHERE batch_id = '<parser-batch-id>'
GROUP BY state, issue;
```

### 3. Freeze the actual model inputs

Run `attachments/prepare_processor_inputs.hwf` with the exact `JOB_RUN_ID`,
`PROCESSOR_BATCH_ID` and a sufficient `POSTING_LIMIT`. Leave `DATASET_ID` blank for
production inputs; set it to a new ID only when preparing a frozen quality-test
dataset. `NCS_RUN_ID` selects the catalogue for that evaluation dataset.

This stores inline posting fields plus parsed Markdown and evidence metadata in
`enrichment.input_bundle`. Even a posting with no eligible attachment receives a
bundle, so it stays in the accounting. Input hashes represent content; manifests
also pin the particular source/attachment/parser receipts. Existing input bundles
are immutable.

### 4. Extract duties and propose NCS links

For production, run `llm/enrich_changed.hwf`. It selects prepared current inputs
that have not successfully completed extraction. The same successful input is
skipped even while it awaits review. Changing a model parameter alone does not
select it again; use `evaluate.hwf` for comparisons or `enrich.hwf` with an exact
selection when deliberately reprocessing unchanged inputs. `RETRY_FAILED=Y` explicitly includes failed
extractions; unchanged successes still remain skipped.

Set these parameters at Run:

| Parameter | Meaning / current starting point |
|---|---|
| `PROMPT_VERSION` | `ko-link-v1`, positions and explicit duties only |
| `EXTRACT_MODEL`, `CATEGORIZE_MODEL` | Configurable OpenRouter IDs; current pilot uses `openai/gpt-5.6-luna` |
| `PROVIDER_ONLY` | `openai` for that pilot; blank permits supported routing |
| `REASONING_EFFORT` | Pilot: `medium`; changing it changes the cache key |
| `POSTING_LIMIT` | Maximum selected postings; default 20 |
| `CANDIDATE_LIMIT`, `MAX_MATCHES` | Size of the NCS shortlist and maximum proposed links |
| `MAX_INPUT_CHARS` | Complete-request limit; oversized inputs fail explicitly, never silently truncate |
| `MAX_OUTPUT_TOKENS` | Includes model reasoning tokens |
| `MAX_REQUESTS`, `MAX_COST_USD`, `DAILY_BUDGET_USD` | Request/batch/rolling-day spending limits |
| `REQUEST_RESERVE_USD` | Conservative allowance for each in-flight or uncertain request |
| `REQUEST_WORKERS` | 1–4 concurrent requests, sharing the same database budget locks |
| `REQUEST_DELAY_MS` | Delay per worker before HTTP calls. The current OpenAI BYOK allocation is 500 RPM and 500,000 TPM; token throughput, source size, worker count and actual provider latency now determine safe spacing. The full rejection-set runner uses one worker and 1,000 ms in chunk 4; chunk 5 is split into 22 medium inputs at 3,000 ms and two huge inputs at 60,000 ms. Hop does not enforce a shared RPM/TPM token bucket. |
| `EXECUTE_REQUESTS` | Default `N` plans only; `Y` makes paid calls |
| `ACCEPTANCE_POLICY` | Keep `REVIEW`; validation does not by itself publish a semantic match |

An HTTP 429, authentication or other provider failure stops further requests in that
batch. `NOT_SENT_AFTER_PROVIDER_ERROR` means the row was not sent. Start a new
bounded batch after addressing the cause; do not reset historical attempts.
`REUSE_CACHE=Y` can reuse exact successful responses. If extraction succeeded but
categorization was not sent, use `enrich.hwf` with those exact `POSTING_IDS` and
`INPUT_BUNDLE_IDS` to complete it from cache; `enrich_changed.hwf` deliberately
skips successful extraction inputs. `RETRY_FAILED=Y` selects failed extractions.

Completed responses settle reservations at reported cost; uncertain calls retain
the reservation. These checks are not an OpenRouter-enforced price cap. Keep the
account/key spending cap as a separate limit. Keys remain in
`${HOP_CONFIG_FOLDER}/secrets/openrouter.csv` with header `api_key`.

For quality checks, use the existing `llm/evaluate.hwf` with a prepared
`DATASET_ID`, the same prompt/models/options and a small explicit budget. EVAL
outputs cannot be accepted into production. Test samples are not an accuracy
benchmark until their source-grounded expected answers have been independently
reviewed. Production ENRICH outputs can also be inspected before any acceptance.

The extraction deliberately has `extraction_scope=DUTIES_ONLY` and empty
`requirements`; it does not erase original eligibility text or claim to model it.
The NCS step proposes matches only from the pinned catalogue shortlist. Entries
explicitly named old/abolished (`구버전`, `폐지`) are excluded from new suggestions;
all catalogue source versions remain stored. No match is a valid outcome; it means no supported match in the supplied shortlist,
not proof that the entire NCS catalogue lacks a relevant unit.

### 5. Review and publish

`llm/capture_extraction.hwf` records a model output as an immutable revision.
Inspect its duties and cited source text, then use `llm/review_extraction.hwf` to
accept or reject that revision, recording who reviewed it and why. Use
`llm/import_correction.hwf` to create a corrected child revision when necessary.

For an unchanged model extraction, `llm/import_model_links.hwf` imports the
validated proposals. Inspect each duty against the candidate's full definition
and occupational context; record accept/reject decisions with
`llm/review_link.hwf`. Imported proposals are not automatically accepted. Human,
assistant and policy decisions are distinguishable in the database.

For a larger batch, use `llm/export_link_review.hwf` with `BATCH_ID`, an optional
`POSTING_IDS` selection, an explicit `POSTING_LIMIT`, `ACTOR` and a new
`REVIEW_FILE`. It captures validated extractions and proposals without accepting
them, and writes source text, duties, full candidate definitions and empty
decision fields. Nonvalidated inputs are listed under `omitted`.

Fill the packet's `reviewer` and accurate `reviewer_kind`, then fill each reviewed
`extraction_decision` / link `decision` with `ACCEPT` or `REJECT` and its required
notes. Null decisions remain pending. Keep IDs, source text, extracted content,
candidate definitions and expected prior decision IDs unchanged. Import the file
with `llm/import_link_review.hwf`. It applies the explicit decisions in one
transaction, rejects edited/stale context, and records a content-hashed receipt.
Replaying identical JSON does not append duplicate decisions or override later
reviews. Export a fresh packet when a source, correction or review has changed.
This file transport does not make the semantic decisions itself.

A corrected extraction, or a new NCS snapshot, can use
`llm/categorize_reviewed.hwf` with exact accepted `REVISION_IDS`. This avoids
paying for extraction again. Review its new proposals before publication.

Run **`llm/publish_links.hwf`** to publish the independently reviewed results.
This practical path does not require a product ontology release, cohort or demand
model. It adds `reviewedNcsEnrichment` nodes linked to existing `jobPosting` and
`ncsCompetency` nodes, with source/model/review provenance and evidence.
A good extraction can publish with zero accepted links.
On `ALIGNS_WITH_NCS`, a model-origin candidate is labelled `LLM_INFERENCE`;
a source-reviewed manual candidate is labelled `REVIEWER_INFERENCE`.
Both retain the candidate origin and actor as separate properties, while the
acceptance decision still names its reviewer. The publication verifier reads
these properties back before activation.

A blank `PUBLICATION_ID` creates a new publication. Replaying an existing ID is
allowed only while its source and review inputs are unchanged. A changed review
or snapshot requires a new ID; the workflow verifies graph contents before marking
that publication ready. Revoked and superseded results leave the current view.
Historical data remain available.

PostgreSQL progress:

```sql
SELECT outcome, count(*) FROM enrichment.linking_status GROUP BY outcome;
SELECT posting_id, title, outcome, ncs_links
FROM enrichment.linking_status ORDER BY posting_id;
```

For Neo4j, require the publication marker and current/accepted flags together:

```cypher
MATCH (p:reviewedNcsPublication {id:'jobtology-reviewed-ncs', state:'READY'})
MATCH (j:jobPosting)-[:HAS_ENRICHMENT]->(e:reviewedNcsEnrichment {current:true})
WHERE e.publication_id = p.publication_id
OPTIONAL MATCH (e)-[r:ALIGNS_WITH_NCS {accepted:true}]->(n:ncsCompetency)
RETURN j.name, e.name, n.name, r.reason;
```

For one visible line per enrichment/NCS endpoint, and the 2026-09-16
ALIO retention preview, see the
[graph display and protected-history record](graph-clutter-retention-20260916.md).

### Refresh and retention

The existing host cron still checks source refresh due times every 15 minutes.
It does not schedule paid enrichment or deletion. After a source refresh, repeat
stages 1–4 for new document inputs, review changes, then publish a new projection.
Unchanged archived bytes and parsed text are reusable. An NCS-only change needs
categorization of the accepted revisions against the new catalogue, not another
posting extraction. No new paid cron was enabled in this phase.

Source snapshot retention remains manual and respects source dependencies. The
attachment and review ledgers pin their source snapshots. Raw attachment pruning
is a separate operation: multiple receipts can reference the same raw path, so
never delete attachments by an old batch directory or attempt alone. Shared
archive references must be checked before any future attachment-retention policy.

## Verified deployment — September 14

Current JOB-ALIO snapshot: `4c4fcc8b-1292-4d66-ace5-e36d005f194a`, **517 postings**.
All six selected source snapshots have PostgreSQL data and graph-export checkpoints.
The parser and the workflows in this guide are deployed on Goldship. Earlier
September 12–13 holds and wider ontology plans are historical; the user resumed
this narrower ingestion task on September 14. The old stopped v7 batch was not
restarted.

### Documents and frozen inputs

| Receipt / batch | Verified result |
|---|---|
| `docir-download-full-20260914` | 919 eligible archives; 904 existing archives reused without another copy |
| `docir-download-supplement-20260914` | 73 postings supplemented for ZIPs and notice/JD filenames in non-B roles |
| `docir-parse-full-20260914` | Initial 1,003-document parse completed: 943 parsed, 20 no text, 40 failures |
| `docir-parse-repair-20260914` | Reused 943 successes and recovered 31 files: **974 parsed, 20 no text, 9 failures** |
| `docir-input-full-20260914` | **517** production input bundles prepared, with `document-processor-input-v2` manifests |

The 1,003 selected originals comprise 607 PDF, 297 HWP, 32 HWPX, 6 DOCX and
61 ZIP files. ZIP contents are recorded per member; outer-file totals are not
member totals. Unsupported image attachments and unselected application forms
remain in the metadata accounting.

Active parser image: `jobtology-document-parser:20260914-3`; library revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779`, adapter suffix `-hop3`. Successful
results reused from the preceding image retain their actual `-hop2` provenance.
The bundled HWP converter requires Java **25** (class version 69).

Two narrowly scoped repairs preserve original bytes: illegal XML control
characters in derived HWPX converter output are removed with a recorded diff/hash;
NUL characters in extracted JSON text are replaced with U+FFFD and recorded paths.
Real HWP 304550 and PDF 304886 regressions now parse. A fresh fetch of malformed
PDF 304393 matched the archived hash, confirming that local archive corruption
was not the cause. Rendering posting 304759's empty-text PDF confirmed an
image-only JD. OCR and arbitrary malformed-document repair remain separate work.

The largest prepared request estimate is approximately 541,000 characters.
`ko-link-v1` permits an explicit `MAX_INPUT_CHARS` up to 1,000,000; the incremental
workflow default remains 200,000. Use the larger limit for this full snapshot.
No source text is silently truncated, and older prompt versions retain their
200,000-character ceiling.

### Tests and deployment receipts

Native disposable integration passed in `/tmp/jobtology-llm-tests-xdkmy8qm/`:
real-format parser adapter, archive reuse, cross-version repair, source-bound
inputs, duty-only extraction, four-worker incremental execution and no-work
selection, graph publication/replay/revocation/source changes, and preservation
of unrelated graph nodes. No paid calls were used by these fixtures.

Native review transport passed in `/tmp/jobtology-llm-tests-gu762emh/` (including
terminal PARTIAL batches and checked corrections of rejected raw outputs): export
makes no acceptance decision, explicit reviews import atomically, identical
replays add no decisions, and edited/stale context is rejected. Real ZIP tests
verified HWP/HWPX member parsing, hashes, text offsets and traversal rejection.
Real HWP, HWPX, DOCX and PDF examples were exercised; DOC support is provided by
the existing library but has not yet been checked with a real corpus DOC sample.

The optimized Korean retrieval returned exactly the same ordered candidates and
scores for all nine validated production samples, taking about 23 seconds total.
It computes lowercase catalogue text once per call; it does not change ranking.

The specialized source lookup matched the existing generic view for all 517
postings with zero differences. Native full input preparation completed in about
32 seconds. Historical v1 input manifests retain their original verifier.

Public deployment receipts under `~/.local/state/jobtology-hop/`:

- `linked-ingestion-deploy-20260914T061612Z`: initial parser integration.
- `...T061855Z`: duty-only prompt and request/validation/review adapters.
- `...T063520Z`, `...T064010Z`, `...T064324Z`: archive reuse, incremental/manual
  publication, document policy v3 and retention pins.
- `...T071737Z`: parser repair/reuse, efficient input preparation, review packets
  and current publication/status functions; native installers succeeded.
- `...T073110Z`: large-input option validation fixed and installed successfully.
  The immediately preceding `...T072652Z` installer failed on SQL syntax; it did
  not launch model requests. The corrected installer succeeded.

Parser Compose: `~/.local/share/jobtology-hop/document-parser/compose.json`, service
`parser`, container `jobtology-document-parser`, private `coolify` network, no host
port and read-only original-file mount. Never hot-redeploy while a parser batch
is running. Keys and private Hop metadata are absent from the parser container.

### Model execution and review

The earlier three-case EVAL `f656a3cb-0f43-4ca1-87d5-bac1d41c15c9` completed six
validated requests at **$0.04965190**. Its housing-maintenance suggestions exposed
old-version catalogue entries; new retrieval now excludes names containing
`구버전` or `폐지`. EVAL outputs cannot be promoted into production.

Production sample `e9c4f22a-8a41-4c07-9972-b42afd92de56` completed 22 requests
at **$0.27966620**: nine validated extractions/categorizations, four rejected
extractions. Independent review then identified duplicate duties in 304839 and
an omitted explicit privacy duty in 304896; structural validation alone is not
semantic acceptance. Source-backed corrections for 304550, 304886, 304889 and
304900 preserve original raw outputs and are handled as new revisions.

Full attempt `553cad5b-d178-4fdc-8d3d-52cce4288aea` selected the remaining **504**
postings. OpenRouter returned its new-account **20 requests/minute** limit after
24 successful HTTP responses; one 429 stopped further sends. Reported cost was
**$0.10470155**, with an additional **$0.15** uncertainty reservation retained for
the response without reported cost. 479 extraction rows were explicitly not sent.
The run is terminal PARTIAL; it must not be described as 504 processed postings.
A slower recovery using the per-worker delay above was **planned but not
launched** before the user paused work. Full-corpus completion and graph
publication counts must be checked in the database. The source refresh schedule remains unchanged, with no paid
LLM or deletion cron enabled.

### OpenAI BYOK resumption — 21:25 KST

The user explicitly resumed this phase after enabling OpenAI BYOK on the existing
OpenRouter account. A direct probe and native Hop EVAL both returned provider
`OpenAI` and `usage.is_byok=true`. OpenRouter reports `usage.cost=0` for BYOK, so
`enrichment.response_cost()` now records
`usage.cost_details.upstream_inference_cost`; an absent applicable cost retains
the reservation rather than becoming a false zero. Deployment receipt:
`~/.local/state/jobtology-hop/linked-ingestion-deploy-20260914T121823Z/`.

Native pilot `9daebf59-5aef-4219-8cc3-44e052dc5853` ran one Korean posting through
both ko-link-v1 stages. Both responses validated and cost **$0.00610420** total.
Cached recovery `a562e922-561f-4623-98b8-e48262cff79e` reused all 17 successful
extractions and made only their missing categorization requests. Sixteen validated;
posting 295096 was retained as rejected because its response used a code outside
the supplied shortlist. The batch cost **$0.11850965** and saw no HTTP 429.

Full retry receipt
`~/.local/state/jobtology-hop/byok-full-linking-20260914T2130KST/` selected the 485
remaining failed extraction inputs with cache reuse, four workers, an 8-second
per-worker delay, a $5.00 batch cap and the shared $8 rolling daily cap. Batch
`20b08f34-24ca-4590-8b3b-973832109bf3` finished PARTIAL at 22:44:51 KST. All 485
extraction calls completed: 353 validated and 132 were retained as validation
rejections. Categorization made 144 paid calls: 142 validated and two rejected;
two no-duty rows skipped the request. Another 207 categorization rows were marked
`BUDGET_BLOCKED` without a provider call. Upstream BYOK cost was **$4.95659390**
with zero unknown charges and zero HTTP/provider failures. The expected OpenAI
balance was about $0.42 before the next recharge. `ACCEPTANCE_POLICY=REVIEW`
remains in force; these structural results are not independently accepted or
published links.

After the user added $5, exact-selection recovery receipt
`~/.local/state/jobtology-hop/byok-cached-categorization-20260914T2330KST/` reused
all 207 saved extraction attempts and made only their missing categorization calls.
Batch `05b85808-20d3-496d-b12d-d747d6bc1fe9` finished PARTIAL at 00:00:50 KST on
September 15: **198 validated, 9 rejected, 207 requests, $2.33157160**. Every call
was HTTP 200 through OpenAI BYOK; there were no provider, transport, budget or
unknown-cost failures. The nine rejections comprise unknown duty indices, too many
matches, and codes outside the supplied shortlist. They remain explicit review or
correction cases. Exact selection and lineage verification confirmed 207/207 prior
extraction IDs, and the temporary four-worker workflow was removed after the run.
The expected remaining OpenAI balance is about $3.09. No retry of the separate 132
extraction rejections was started.

### Rejection triage — September 15

The 132 extraction rejections in batch
`20b08f34-24ca-4590-8b3b-973832109bf3` all have HTTP 200 and saved raw model
output. They are evidence/identity validation failures, not missing fetched posting
or NCS source nodes. Issue counts below are **distinct postings** and overlap when
one output has several problems:

| Extraction issue | Postings | Meaning |
|---|---:|---|
| `positions:MIXED_EVIDENCE_FIELDS` | 94 | One position cites passages from different source fields; 89 cases mix multiple attachments, five mix an attachment and an inline field. |
| `duties:UNSUPPORTED_FRAGMENT` | 28 | One or more duty `text_parts` are not exact, ordered fragments of the cited source text. |
| `positions:UNSUPPORTED_TEXT` | 19 | The returned position name is not found in its cited text. |
| `duties:NON_DUTY_FIELD` | 1 | A duty was cited from a field not allowed as work-duties evidence (posting 304624). |
| `duties:UNKNOWN_POSITION_ID` | 1 | A duty refers to a position ID absent from that output (posting 304634). |
| `duties:UNKNOWN_EVIDENCE_ID` / `positions:UNKNOWN_EVIDENCE_ID` | 1 | A saved output cites a source passage ID that was not supplied. |

The first three issues cover 130/132 postings. For example, posting 292472 cites
both `attachment_1_3003124` and `attachment_3_3003126` for the same `약무직`
position. Posting 299471 returns `주말 및 휴일당직약사`, while the cited text says
`주말 및 휴일당직 약사`. Posting 304326 joins a duty across `<br>` line breaks into
one `text_parts` string, which the exact-fragment checker rightly rejects.

The nine rejected categorization responses in batch
`05b85808-20d3-496d-b12d-d747d6bc1fe9` also all have HTTP 200 and saved raw
output. Three postings use a nonexistent duty index (`UNKNOWN_DUTY`), three exceed
the configured match limit (`TOO_MANY`), and four use a code outside the supplied
NCS shortlist (`CODE_OUTSIDE_SHORTLIST`); posting 304592 has both latter issues.
These are nine postings, not nine missing graph nodes or a fixed number of edges.

Repair plan: inspect each rejected raw response against the immutable source text
and attached-document field IDs. First source-review whether excess cross-field
citations can be narrowed to one supporting field, literal position wording can be
restored, and duties can be split into exact cited fragments. Create checked,
append-only extraction corrections with `llm/import_correction.hwf` where the
meaning and role scope remain intact; validate and independently review them.
For cases needing new inference, revise the prompt/contract version and test a
small exact-posting sample before a bounded retry of the remaining cases. Keep
all original raw outputs, issues, costs and source pins. For the nine categorization
failures, reuse their valid extractions; compare duty indices and codes with the
actual shortlist, improve retrieval if the right unit was absent, then rerun their
exact `POSTING_IDS`/`INPUT_BUNDLE_IDS` through `llm/enrich.hwf` with
`REUSE_CACHE=Y`. Once their extraction revisions are independently accepted,
`llm/categorize_reviewed.hwf` is the strictly NCS-only path. Do not loosen
citation or shortlist validation simply to turn a rejection into a match.
Accepted extraction revisions and each
proposed NCS link still need semantic decisions before `llm/publish_links.hwf`.

### Posting-bound structured-output pilot — September 15

New `ko-link-v1` requests derive a `link-bound-v1` response schema from each
posting. Extraction citations must use real nonempty passage IDs from one source
field per position/duty; duty fields must be permitted work evidence. The NCS
response uses the actual shortlist as the competency-code enum, actual duty count
as the index bound, and the batch `MAX_MATCHES` cap. `llm/install_link_bound.hwf`
installed the new schema builder and validator on Goldship; the deployment receipt
and backups are at `~/.local/state/jobtology-hop/link-bound-deploy-20260915T065000Z/`.
Past provider outputs, prompt rows, input bundles and cache lineage were preserved.
The native synthetic test is `python hop/llm/tests/run_link_bound.py` and passed
schema/source failures, Hop installation and request replay, plus exact-duplicate
normalization with saved raw output. The live OpenAI endpoint accepted the new
`anyOf`/pattern/enum schemas with HTTP 200 in these bounded pilots.

Replaying the **nine saved categorization failures** against the new per-posting
schema blocks all nine original outputs: their unknown duty indices violate the
bound, outside-shortlist codes violate the enum, and excess matches violate the
array cap. This is a retrospective constraint check, not a claim that every new
generation will pass. In batch `b4b1223b-5c70-4f5d-88ad-b64633f98c7e`, posting
292472 changed from mixed citations in two attachments to one supporting
attachment, and both stages validated (two requests, $0.01203925 reported).
Its proposed NCS match remains unreviewed; the model explanation mentions
cooperation requests not explicit in the quoted pharmacy-administration duty.

The five-posting pilot `83c6e5e4-c677-4c2f-9a23-2477931850fe` used nine
requests and reported $0.07525335. Postings 299471, 304625 and 304677 completed
both stages; 299471 found the exact role spelling in another source attachment,
while 304625 and 304677 no longer have their earlier match-count and shortlist
violations. Posting 304536's new categorization removed its old invalid duty
index but duplicated an identical `(code,index,reason)` object and was rejected.
Posting 304326 still joined two phrases over Markdown `<br><br>` and failed exact
fragment validation. The follow-up batch
`b60fc8c8-69d4-4543-ad35-8047128773a8` reused 304536's validated extraction,
made one paid categorization request ($0.007186 reported), and validated. The
new response itself had no duplicate. For future **identical** duplicates,
PostgreSQL now stores the raw object, removes redundant copies only from the
parsed result, and records the count in `attempt.normalization`; different
reasons for the same pair still fail. This behavior passed native mock replay.

The conservative `suggest_rendered_fragment_revision_v1` helper found safe
source-exact `<br>` splits for **4 of 28** saved fragment rejections. It refuses
the other 24. Hop imported the four corrections as new revisions: 304326 from
the current pilot and 304405, 304607, 304850 from the earlier full batch. Each
revision passes source validation; all have zero acceptance decisions. They are
pending independent review, and their old categorization indices cannot be
silently reused. No NCS link or graph publication ran in these pilots.

The large-document retrospective extraction scan hit a 60-second statement cap
because the generic schema checker repeatedly evaluated long ID regexes. New
extractions therefore check the base JSON shape and use the existing direct
source validator for ID existence, one-field ownership and literal fragments;
categorization still checks its dynamic enum/range/cap from the saved schema.
The four inspected extraction outputs showed that the mixed-field cases violate
the new schema while the exact-wording and `<br>` fragment cases do not. The
original 132 extraction failures have **not** been blanket retried.
The plan-only check of the largest inspected mixed case (posting 304489) saved a
360,377-character request, including a 32,489-character response schema with 14
field branches, below the 1,000,000-character cap. That dry batch
`6608ab7f-4160-4331-a4a2-195bde223e56` sent zero provider requests.
The bounded live follow-up `7318500a-ecb1-45a2-bd3f-11510ad949a4` used two
OpenAI requests and reported $0.25439870. Both stages validated with HTTP 200
and zero issues. The rejected output had 16 positions, 34 duties and 16
mixed-field position citations; the new output has 15 positions, 29 duties and
zero mixed-field citations. The old-only position label is
`공급·생산운영/ 설비건설/ 안전·품질환경`. This difference is a **completeness review item**,
not evidence that the omitted label was wrong. Categorization returned 12
schema-valid proposals at the batch cap; none was accepted or published. The
large case shows the provider can accept the 14-branch schema, but it also shows
why a full retry needs a bounded cost budget and independent semantic review.

For `ko-link-v1`, `REPAIR_BATCH_ID` now uses the same source/revision guard as the
v6/v7 repair path. The saved request includes the old raw response and validator
issues as **diagnostics**, instructing the model to cite exact source phrases and
split text at rendered Markdown `<br>` separators. Planning refuses a pending
correction, and reservation checks again before sending if a correction appears
later. Disposable native Hop tests verified feedback, protected revision selection
and the `NOT_SENT` reservation branch without an API call. The one-posting Goldship
dry batch `36db21f2-8a1e-4f6b-8053-aaeaa00b58cf` pinned 304843 and its input
bundle, saved a 25,524-character bound-schema extraction request with its previous
`duties:UNSUPPORTED_FRAGMENT` issue, and sent zero calls. Its batch-planning query
took 66.5 seconds, which is a runtime cost to address separately if frequent
per-posting retries become necessary. A first live attempt
`31bbbd6f-911f-4dbb-81ac-59e5eefefd7a` was blocked before sending because the
rolling 24-hour accounted spend was $8.34 above that batch's $8 daily cap; it
reported zero requests and no cost.
With a $9 daily cap and unchanged two-request/$0.10 batch limits, batch
`e051970b-62e0-4da9-88fd-a29277609b01` completed 304843. The prior rejected
extraction had 28 positions, six duties and `duties:UNSUPPORTED_FRAGMENT`; the
new one has the same counts and **zero** validator issues. The new NCS response
validated with `no_supported_match` and zero proposals. Both requests returned
HTTP 200 and cost **$0.00861360** total. Among the 28 original fragment
rejections, four now have pending source-exact revisions and one completed this
retry; the other **23** have neither a safe correction nor this successful retry.
The entire 132-extraction backlog has not been retried.
There are no item reviews, NCS link candidates or graph publications from this
pilot. After the batch was terminal and reserved requests were zero, the
reservation-time revision guard was deployed and installed. Its backup is
`~/.local/state/jobtology-hop/link-repair-guard-deploy-20260915T072920Z/`, and
the deployed planner matches the locally tested SHA-256
`0ee4d0bbe2c751f750aedd12af11a684b282dfa9435935699f66623c98a4baba`.

### Full rejection-set run — September 15

The original rejected set contains **132 extraction** postings and **nine NCS
categorization** postings, all distinct. Seven had newer fully validated pilot
runs and four had pending exact-source extraction corrections, leaving **124
extraction and six categorization** cases for first-pass execution. A manifest
of their original posting IDs, input-bundle hashes and source sizes is at
`~/.local/state/jobtology-hop/full-rejection-eval-20260915/manifest.psv` on
Goldship. Both source runs are pinned to JOB-ALIO
`4c4fcc8b-1292-4d66-ace5-e36d005f194a` and NCS
`a32170ed-7485-4e31-82d3-ed48b3398946`. The host script
`run-extraction.sh` invokes the native `llm/enrich.hwf` in five source-size
chunks of 25/25/25/25/24, each with two-request-per-posting and $0.60 batch
caps. The staged `continue-extraction.sh` stops before a new chunk if a prior
one has a provider, budget or unknown-cost blocker. Both are orchestration
helpers; parsing, request planning, validation and database writes remain Hop
workflows/SQL. Basic logs are in the same private state directory.

Categorization dry batch `a0009559-de94-431f-9a7c-ebd08dfafa84` planned all
six original failures with requests of 22,482–77,242 characters and zero calls.
The bound-schema change prevented reuse of their old extraction request cache,
so paid batch `464f62cd-a4e2-4a93-a12b-cfc471f64ee2` made six extraction and
five categorization calls. It finished **five fully validated, one extraction
rejected**, with 11 HTTP 200 responses and **$0.09707730** reported cost.
Posting 304861 joined two exact source phrases over Markdown `<br>` tags using
model blank lines. The newline-aware, source-exact splitter passed native tests
(`python hop/llm/tests/run_link_bound.py`) and was installed only after the
first extraction chunk closed; receipt
`~/.local/state/jobtology-hop/newline-fragment-deploy-20260915T080919Z/`.
It now finds safe literal corrections for **six of the original 28** fragment
failures, up from four, and for 304861. Hop imported 304861's correction as
pending revision `7c0c287e543dede6eec46b5785b206db15cb971864d1c43607ead9472202830e`;
the source validator returned no issues, and it has zero acceptance decisions.
The two newly suggested original cases (304568 and 304754) received newer
fully validated live attempts in chunks 4 and 1 respectively. Their older
fragment suggestions do not need to be imported for this repair pass; the
original rejected attempts remain immutable.

Extraction dry batch `a10a7f1a-1ba5-48d9-ae61-d3d23e6380fc` saved **124
planned requests**, none oversized at the 1,000,000-character cap. The largest
serialized request was 571,795 characters; no API call ran. Paid chunk 1,
`0fb91c2e-982f-4566-aa88-2358b72bbf17`, finished **25/25 fully validated**
with 50 HTTP 200 requests and **$0.24455383** reported cost. Its 58 NCS
proposals are unreviewed; there are no item acceptance reviews or graph
publications from that chunk. Paid chunk 2,
`601c9cf1-4b8f-4ff8-b62d-8fc258c79fed`, finished **23/25 fully validated**,
two extraction rejections, 48 HTTP 200 requests and **$0.29296957** cost.
Paid chunk 3, `89c5d17e-a6da-4c9b-9f5f-af3b296979f8`, finished
**22/25 fully validated**, two extraction and one categorization rejection,
48 HTTP 200 requests and **$0.34472930** cost. The categorization rejection
repeated one `(NCS code, duty index)` pair with different reasons; the two
explanations were not merged. Paid chunk 4,
`0b2e7825-12d9-4976-9cc7-a8a8743c46c5`, finished **24/25 fully
validated**, one extraction rejection, 49 HTTP 200 requests and
**$0.53004949** cost. Its saved 60-second token peak was 207,956, with no
HTTP 429 or uncertain charge. Its complete-but-nonliteral position title
exists elsewhere in the same attachment and needs a checked citation repair.
Chunk 5's 22 medium postings ran as batch
`9decb3c3-d750-4265-bc0f-3552b14a139f`: **15/22 fully validated**,
five extraction and two categorization rejections, 39 HTTP 200 requests and
**$0.73267795** reported cost. The two category failures repeated an `(NCS
code, duty index)` pair with different reasons; both remain rejected pending a
new category call from the validated extraction cache. Its measured minute
token peak was 333,611, below the stated BYOK cap. The two individually
paced huge postings run under `continue-safe-chunk5.sh`. The first, posting
304426, finished as batch `9081b86d-b7e9-4edd-82cd-bc33083519ba` with
**one fully validated**, two HTTP 200 calls and **$0.30226080** reported
cost. Its extraction and categorization prompts used **286,612 and 304,922**
tokens respectively, confirming that one-minute co-scheduling would exceed
500,000 TPM. Posting 304428 finished as batch
`6712a825-003a-4bf1-891d-04fd7cd3be75` with **one fully validated**,
two HTTP 200 calls and **$0.31426150** cost. Its two prompts used **304,848
and 312,887** tokens, again confirming the need for 60-second separation.

The terminal first-pass audit covered all **130 distinct pinned postings**:
**116 fully validated, 14 rejected**, no pending item, **249 HTTP 200
responses**, no 401/402/403/429, no budget block or unknown-cost reservation,
and **$2.85857974** total reported cost across the eight live batches.
Of the 14, ten were extraction source-grounding failures, three were
categorization duplicate-pair failures, and one (304861) already has a
source-exact pending extraction correction. The first pass tested every
remaining original failure, but validated items still require independent
extraction/link review before graph publication. The subsequent bounded
retry for the three category duplicate cases is recorded below.

The first plain category-only dry batch,
`018f264e-65f2-421c-85c2-2e2e94482c69`, planned three **new
extractions** because it omitted the original repair feedback from their
request bodies. It sent zero paid calls. A corrected dry batch,
`9b994279-7f48-49d0-bd14-226206244e7e`, pinned the original rejected
batch as `REPAIR_BATCH_ID` and reused all three newer validated extraction
attempt IDs; only the three category calls were planned. The paid category
retry `11dc4cc1-c392-4c85-a9a6-b675d1755805` billed only those three
calls, two of which fully validated (304555, 304746). Posting 304404 repeated
`matches:DUPLICATE` and remains rejected. All three were HTTP 200, with
**$0.04592415** reported cost. Raw attempts and the discarded divergent
explanations remain available for independent review.

The other ten first-pass rejections are extraction source-grounding failures.
Their exact input bundles and producing batch IDs are grouped as `c2` (two),
`c3` (two), `c4` (one) and `medium` (five) in
`run-source-rejections-retry.sh`. All ten passed
`repair_reasons_v6`; dry batches `66f25c43-c76d-4c7b-bba7-217d90ff1786`,
`dd3cf25b-6894-4d29-8e79-0b04c93f44fe`,
`8d44f897-19b4-428a-badf-eb736c24d733` and
`33b3f8ee-cf47-4f01-8714-7715fb48eb8a` planned 2/2/1/5 extraction
requests with zero oversized inputs or paid calls. Their live bounded runs
finished sequentially under `continue-source-rejections-live.sh`. Batch
`b783b2d6-a285-45df-b240-b3c5df172545` fully validated 304888 but
rejected 304624 on two still unsupported duty fragments (**$0.01767800**).
Batch `f2f547e8-8462-462b-be68-cd2c402da720` fully validated 304803 but
rejected 304788 on twelve still unsupported duty fragments
(**$0.03102530**). Batch `adaf5a9b-b150-4a7d-9913-75a1e7275571`
fully validated the split-title posting 303306 (**$0.01613475**). Batch
`bf28263f-5526-4603-8ad4-f3e2ed1caf59` fully validated 304439 and
304548, while 304260, 304713 and 304880 retained unsupported duty
fragments (**$0.18804380**). These four paid batches made 15 HTTP 200
calls and cost **$0.25288185** combined. The category retry and four source
retries therefore added **seven** fully validated postings at
**$0.29880600**, with no HTTP 429, budget block or uncertain charge.

Re-auditing the **141 distinct original HTTP-200 rejections** against newer
live `ko-link-v1` attempts and only source-matched revisions created after
those rejections gives **130 with newer fully validated extraction plus NCS
categorization**, **five with pending source-exact extraction revisions**
(304326, 304405, 304607, 304850 and 304861), and **six unresolved**:
304404 repeats a duplicate `(competency_code,duty_index)` pair even on retry;
304260, 304624, 304713, 304788 and 304880 still fail literal duty-fragment
checks. Two much older pending revisions for 304260 and 304404 predate the
original rejected runs and must not be counted as current fixes. The six
unresolved cases need source/semantic review or a posting-specific model
correction; the validator is correctly refusing unsupported evidence. The
pending revisions need independent extraction review and fresh NCS
categorization before they can become fully validated. No link acceptance or
Neo4j publication was made by this full-set evaluation. PostgreSQL ended
with zero running batches, zero reserved requests and zero unknown-cost
charges; the recorded rolling 24-hour spend was **$10.92765644** against
the workflow's $12 cap.

The BYOK OpenAI allocation was raised to **500 requests/minute and 500,000
tokens/minute** during chunk 3. Its active Hop invocation retained the original
8,000 ms delay, because workflow parameters are captured at startup. The host
runner was backed up as `run-extraction-before-byok-rate-20260915.sh` and updated
for chunk 4, which started with a verified 1,000 ms setting. Editing that shell
file while chunk 3 was still running made its shell return a syntax error only
*after* Hop had completed its terminal report; no request was lost. Chunk 3's
terminal result was recorded directly from PostgreSQL, and a fresh continuation
started at chunk 4. Its parent shell was then paused with `SIGSTOP` while its
child Hop run continues, to prevent chunk 5 from starting before revised pacing
is applied.

Recent completed calls averaged roughly 9–12 seconds of provider latency, and
the largest categorization prompt in the newer run used 66,153 tokens. Earlier
saved extraction calls for postings 304426 and 304428 used **284,789 and 301,232
prompt tokens** respectively; sending them within the same minute could exceed
500,000 TPM despite a 3,000 ms fixed delay. The staged
`run-safe-chunk5-group.sh` therefore selects the other 22 chunk-5 postings at
3,000 ms, then each of those two huge postings in its own one-item batch with
60,000 ms before each extraction and categorization call. Each group retains
the pinned bundle selection, `ko-link-v1` validation, `REVIEW` policy and daily
cost cap. The old `run-extraction.sh live 5` command now exits before creating
a Hop batch and directs operators to these three safe groups; this guard was
verified with exit code 2 after the live work ended. This is a conservative
schedule, not a shared RPM/TPM token bucket;
check HTTP 429 responses and the saved token counts before changing it. The
continuation runner stops on 429 and leaves unsent items for an explicit retry.

The concurrent runner also exposed a Hop 2.19 CPU busy-wait in a shared Abort
transform. The deployed fix gives the error-count and unsuccessful-result filters
separate single-input Abort transforms in both stages and their worker variants.
The final full-suite eight-second delayed mock measured the legacy topology at
3.140 CPU-seconds over 3.164 seconds and the fixed topology at 0.100 over 3.184;
an earlier focused run measured 3.220/3.165 and 0.090/3.191. Both failure paths
still abort correctly in native fixtures. Deployment occurred only after the paid
runner was terminal and both the active-batch and reserved-request counts were
zero. Receipt `~/.local/state/jobtology-hop/linked-ingestion-deploy-20260914T140804Z/`
contains the prior files for rollback. The deployed files match the tested hashes,
and each Abort has exactly one incoming hop.

### Pause handoff — actual state at 07:53Z

- The four checked corrections were imported and accepted through native Hop.
  `docir-corrected-categorization-20260914`, batch
  `2c439700-2a31-4954-a4fa-03a369381875`, completed four validated categorization
  requests at **$0.03975880**. Their new proposals still need independent review.
- The first partial full batch has **19 validated extractions**, five validation
  rejections, one HTTP 429 and **479 not-sent extraction rows**. Two no-duty cases
  completed without model categorization; the other **17** successful extractions
  still need categorization. Recover those exact inputs with `REUSE_CACHE=Y`.
  Do not mistake 502 final rejected item states for 502 billed model rejections.
- Across the 517 current postings, **485** full-batch inputs still need extraction
  or a retry/correction. The separately sampled four rejected extractions have
  already been corrected; do not re-extract them merely because their original
  attempts remain rejected. Two complex sample extractions (304839 and 304896)
  remain rejected after semantic review.
- Seven unmodified sample extractions and the four corrected revisions are accepted.
  Fourteen links are accepted, six proposals explicitly rejected, and remaining
  proposals await review. Reviewer kind is `assistant`, not `human` or gold.
- New reviewed graph publications: **zero**. After reviewing pending proposals,
  run `llm/publish_links.hwf`, verify the actual Neo4j rows, then verify replay.
  Existing six-source graph loads remain intact.
- September 14 runs reported **$0.47377845** in total model cost. The 429 additionally
  retains a **$0.15** uncertainty reservation; it is not a known charge or an
  active request. Obtain a fresh account balance before further paid work.
- Deployment `...T073813Z` installed the equivalent faster retrieval and support
  for reviewing terminal PARTIAL batches. `...T074721Z` installed review export
  for checked corrections of rejected raw responses. Native corrected/partial
  review regression passed in `/tmp/jobtology-llm-tests-gu762emh/`.
- A possible further status-query optimization was checked read-only against all
  517 rows (zero differences; `/tmp/jobtology-link-status-equivalence.log`). It is
  only a temporary SQL prototype, **not applied to repository or live functions**.
  No shared request-rate limiter was implemented; the documented conservative
  per-worker delays are available today.

Resume only after a new user instruction. Inspect the pause record, active jobs
and credit first; preserve old attempts. Finish the corrected sample review and
first graph publication, then recover the remaining corpus with an explicit cap
and rate-aware settings. The existing `enrich_changed.hwf` skips successful
extractions even if categorization remains incomplete, so the 17 cached recovery
items need an exact `enrich.hwf` selection. Unreadable/failed documents and complex
model outcomes remain explicit exceptions; this is not a 100% coverage claim.
