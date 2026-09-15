# Paid DeepSeek evaluation — 2026-09-12

The native Hop workflows successfully called OpenRouter and stored real responses,
usage and validation results. **The current `ko-v1` extraction/validation combination
is not ready for unattended production acceptance.** Keep `ACCEPTANCE_POLICY=REVIEW`.
The structural pass rate below is not a Korean-language accuracy score.

## Results

The main `korean-jd-v1` batch used **DeepSeek V4.1 Flash on Modal**, reasoning disabled:

- 20/20 HTTP 200 responses and schema-valid output objects; no truncated outputs.
- **11/20 items validated; 9/20 rejected** by the existing evidence/logic checks.
- 30,488 input tokens and 38,875 output tokens; reported cost **$0.0557964**.
- All 20 extracted duty arrays were empty. The 11 validated extractions proceeded to
  a recorded `NO_EXPLICIT_DUTIES` skip; rejected extractions never entered categorization.
- No cache reuse, human gold labels, acceptances or LLM graph publication.

A separate frozen `korean-duty-v1` sample added two real postings with explicit duties:

- `304435`, clinical laboratory technician / funeral director: extraction rejected
  because several multiline evidence quotations were flattened. No categorization call.
- `304602`, labor adviser: extraction and the paid categorization call validated.
  The model returned `no_supported_match` against the 40 supplied candidates.
  The shortlist contained broad management/risk competencies and missed the relevant
  labor-dispute context. This exposes a retrieval limitation; it does not establish
  that the full NCS catalog has no suitable competency.
- Three paid calls total; reported cost **$0.0060057**. No proposed NCS matches.

The source fields were read before reviewing model outputs. The observations here are
an assistant's qualitative review, **not human gold labels or measured precision/recall**.
The main sample has little actual duty text; it cannot establish positive NCS-matching
accuracy. Neither sample's outputs were published to Neo4j.

## Run ledger

All runs used `deepseek/deepseek-v4.1-flash`, immutable prompt `ko-v1`, and EVAL mode.
The two reasoning pilots used `REASONING_EFFORT=low`; other runs used `none`.

| Run | Batch ID | Postings | Validated items | Logical requests | Reported cost |
|---|---|---:|---:|---:|---:|
| Fireworks connection pilot | `c6d3a932-dfc7-48b0-a1a9-fc2bb3e7166f` | 1 | 0 | 1 | $0.00225742 |
| Fireworks throttled batch | `20fedbff-df95-4c12-b285-872f11acab40` | 20 | 0 | 20 | unknown |
| DeepInfra reasoning pilot | `cc0a8246-4550-4c20-b1ba-e3dc98db9b56` | 1 | 0 | 1 | $0.007301 |
| Modal reasoning pilot | `ccdc370d-1d91-46f5-beb2-6a3c5e090488` | 1 | 0 | 1 | $0.0148737 |
| Modal 20-posting evaluation | `b5eaaaa4-ab63-4dee-9e62-b0c15642058b` | 20 | 11 | 20 | $0.0557964 |
| Modal explicit-duty evaluation | `f5c5cb85-ee81-40e8-9b9c-e2553b12e888` | 2 | 1 | 3 | $0.0060057 |

Total reported response cost, including the pilots: **$0.08623422** (about 9 cents).
The 20 original Fireworks 429 outcomes contained no usage/cost; their per-attempt
cost remains unknown, and their conservative reservations remain in the ledger.
`requests` counts logical reservations, not guaranteed wire requests; see the
transport limitation below. Account-level billing can settle separately from response
usage, so retain both when reconciling charges. At the final check, OpenRouter's
account usage matched **$0.08623422** exactly. No paid request remained active.

The rolling budget ledger accounts for **$2.30**, because each of the 46 logical
attempts retained at least its $0.05 reservation. Repeating the documented $2.50
daily limit immediately would allow only four more reservations until older ones
leave the 24-hour window. Inspect that ledger before another paid run; raising the
limit is an explicit spending-control decision, separate from the much smaller
actual bill.

The DeepInfra reasoning pilot used **8,777 reasoning tokens** and 2,865 other output
tokens, returned HTTP 200, and failed evidence/position validation. The Modal reasoning
pilot used **10,377 reasoning tokens**, exhausted the 12,000-token output limit, and was
rejected as incomplete. `low` is not a hard reasoning-token cap. These pilots are too
small, and differ in provider, to establish a general reasoning-quality comparison.

## What worked and what needs changing

The model understood useful Korean distinctions: posting `304630` kept the required
언어재활사 certificate separate from preferred clinical experience; `304660` preserved
the license/certificate OR group. The physician postings identified separately named
positions. The model did not manufacture duties from titles in the main sample.

The main failures were a combination of model/prompt and pipeline-contract issues:

1. **Evidence and position identity:** four postings failed exact evidence checks;
   one also joined two names into a position absent from the `positions` array.
   Quotes must currently preserve every newline and space. Changing their layout
   causes rejection even when much of the underlying meaning is intact.
2. **Alternative validation:** seven postings failed the narrow OR check, overlapping
   with the evidence failures. The regex recognizes expressions such as `또는`, `혹은`,
   `중 하나` and `/`; comma lists and `+` are not accepted. Some model alternatives are
   plausible; others are insufficiently supported. Do not count every such rejection
   as a demonstrated semantic model error or simply permit all comma lists.
3. **Exclusion polarity:** several structurally validated outputs put disqualifying
   conditions under `importance=required`, including `304400`, `304830`, `304846`,
   `304660`, `304844` and the labor-adviser sample. Exact evidence alone does not catch
   this. The schema needs an explicit distinction between eligibility, exclusions and
   unrestricted conditions. A blanket ban on `disqualification_text` would also reject
   positive eligibility statements that some providers put in that field.
4. **Completeness and nested conditions:** `295717` omitted supplied education options.
   A single `logic` value cannot adequately encode every combination of a qualification
   AND alternative experience routes, or a common condition with a position-specific
   exemption. Preserving readable text helps review but does not solve machine reasoning.
5. **NCS candidate retrieval:** the initial lexical retriever can rank generic words
   above domain-specific duties. Improve and measure shortlist recall before judging
   the categorizer's semantic accuracy. Missing attachments remain a separate input gap.

Recommended next implementation: introduce a new immutable prompt/schema version;
provide numbered source passages so returned evidence IDs can resolve to exact original
quotes; represent exclusions and conditional/alternative groups explicitly; then revise
validation and retrieval and compare models on the same independently labelled cases.
Keep the current raw responses and batch IDs as the baseline. No prompt/schema, validator,
retriever or historical model result was silently changed during this test.

## Case-level review of the main sample

`VALIDATED` means the existing mechanical checks passed; it is not approval to publish.

| # | JOB-ALIO posting | State | Review observation |
|---:|---|---|---|
| 1 | `304450` | REJECTED | Joined two position names; flattened quotes. Alternative-list check also rejected it. |
| 2 | `304648` | REJECTED | Flattened a multiline preference quote; required/preferred labels generally separated. |
| 3 | `304574` | VALIDATED | Kept the safety-training certificate as preferred; inferred no cleanup duties from the title. |
| 4 | `298713` | VALIDATED | Did not invent a physician license from the title; attachment reference became a requirement row. |
| 5 | `304237` | VALIDATED | Preserved the age limit and experience preference; marked the military alternative as single. |
| 6 | `304400` | VALIDATED | Captured school recommendation and graduation conditions; also emitted disqualifications as required. |
| 7 | `304630` | VALIDATED | Correctly separated the required language-rehabilitation certificate from preferred experience. |
| 8 | `300965` | REJECTED | Named nine positions; comma-separated specialist alternatives tripped the OR validator. |
| 9 | `304717` | REJECTED | Comma-separated preference categories tripped the OR validator; exclusion polarity also needs review. |
| 10 | `304830` | VALIDATED | Preserved the age exception; also emitted disqualifying conditions as required. |
| 11 | `304846` | VALIDATED | Kept the military-service exception text; also emitted disqualifying conditions as required. |
| 12 | `304676` | REJECTED | Captured the energy-management certificate; a multiline preference quote was rewritten. |
| 13 | `299690` | REJECTED | Named nine positions; comma-separated qualification/education alternatives tripped validation. |
| 14 | `304445` | REJECTED | Named four positions and abstained on duties; 신입+경력 was treated as an OR requirement. |
| 15 | `304741` | VALIDATED | Kept military age extensions and experience exclusions in the text; flat condition types need review. |
| 16 | `304660` | VALIDATED | Kept the nurse-license/certificate alternative; also emitted disqualifications as required. |
| 17 | `304844` | VALIDATED | Did not invent duties from 환경미화; also emitted disqualifications as required. |
| 18 | `304165` | REJECTED | Named nine positions; qualification/education alternatives tripped validation; polarity also needs review. |
| 19 | `295717` | VALIDATED | Did not invent R&D duties from the title; omitted the supplied 석사,박사 education field. |
| 20 | `304739` | REJECTED | Rewrote a preference quote and assigned unsupported OR logic to preference groups. |

## Reproduce or inspect in Hop

Reopen `llm/evaluate.hwf` after the deployment to see the new `PROVIDER_ONLY` parameter.
Run configuration: **llm-local**. Logging: **Basic**. Settings for the main batch:

```text
DATASET_ID=korean-jd-v1
EXTRACT_MODEL=deepseek/deepseek-v4.1-flash
CATEGORIZE_MODEL=deepseek/deepseek-v4.1-flash
PROVIDER_ONLY=modal
PROMPT_VERSION=ko-v1
REASONING_EFFORT=none
TEMPERATURE=0
MAX_OUTPUT_TOKENS=12000
POSTING_LIMIT=20
EXECUTE_REQUESTS=Y
REUSE_CACHE=N
ACCEPTANCE_POLICY=REVIEW
MAX_REQUESTS=40
REQUEST_RESERVE_USD=0.05
MAX_COST_USD=2
DAILY_BUDGET_USD=2.50
REQUEST_DELAY_MS=1000
READ_TIMEOUT_MS=180000
```

A new run makes new paid requests. To reuse validated results, set `REUSE_CACHE=Y`;
failed extractions are not reusable. Change `DATASET_ID=korean-duty-v1`,
`POSTING_LIMIT=2`, `MAX_REQUESTS=4`, `MAX_COST_USD=0.20` for the duty sample.
Its two cases were selected before seeing their model outputs and frozen directly
from the accepted source snapshot; no source text was edited and no gold label was added.
The existing `prepare_evaluation.hwf` samples by heuristics: use these existing IDs
for replay, rather than attempting to recreate the curated sample with another seed.

Both datasets pin JOB-ALIO snapshot `77ccb77b-3afc-4965-8ce5-efd687304954` and NCS
snapshot `a32170ed-7485-4e31-82d3-ed48b3398946` (15,520 competency definitions).

Use `llm/inspect_results.hpl` with the main batch ID
`b5eaaaa4-ab63-4dee-9e62-b0c15642058b`, or the duty batch ID
`f5c5cb85-ee81-40e8-9b9c-e2553b12e888`. Preview **Preview results here**.
The view intentionally exposes extracted content only when validated. To inspect a
rejected model output as well, use this read-only query in a Table Input preview:

```sql
SELECT i.posting_id, a.stage, a.state, a.http_status, a.provider,
       a.issues, a.parsed_output, a.prompt_tokens, a.completion_tokens, a.cost_usd
FROM enrichment.item i
JOIN enrichment.attempt a ON a.item_id = i.item_id
WHERE i.batch_id = 'b5eaaaa4-ab63-4dee-9e62-b0c15642058b'
ORDER BY i.ordinal, a.stage;
```

The protected key remains in `${HOP_CONFIG_FOLDER}/secrets/openrouter.csv` on Goldship.
It was not copied to the repository or the local model-test data.

## Runtime fixes and verification

Four public runtime files were updated: `evaluate.hwf`, `enrich.hwf`,
`start_batch.hpl`, and `sql/003_planning.sql`. Existing live hashes were checked before
replacement; files were backed up and atomically replaced with owner 501:501.
The native `llm/install.hwf` completed successfully. No Hop image or custom JAR changed.

- `PROVIDER_ONLY` pins one provider, is included in immutable settings/request JSON,
  and changes the output cache key. Strict parameter support and no provider fallback
  remain enabled.
- After HTTP 401/402/403/429, subsequent logical attempts in the same batch are recorded
  as `NOT_SENT_AFTER_PROVIDER_ERROR`, without reservation or HTTP request.
- **Upstream Hop 2.19 limitation:** the underlying HttpClient5 repeats HTTP 429 once
  even with REST `retryTimes=0`. A native fixture observed two POSTs with one attempt ID;
  the second posting was correctly skipped. There is no exposed REST metadata option
  to disable that lower-level retry. This limits the physical-call guarantee of
  `MAX_REQUESTS`; it is not an extra workflow reservation. Read timeouts also apply to
  stalled reads, not total wall-clock time while OpenRouter sends response keepalives.

`python hop/llm/tests/run.py` passed against disposable Hop 2.19, PostgreSQL 17 and
Neo4j 5.26. Checks included provider selection/cache separation, rate-limit stopping,
native extraction/categorization, budgets, evidence/schema rejection, cache reuse,
EVAL isolation, publication idempotence/revocation and review-file export. Disposable
containers and their network were removed after the test.

Goldship deployment backup/manifest and installer log:
`/home/maxjo/.local/state/jobtology-hop/provider-deploy-20260912T070641Z/`.
The final SHA-256 check covered those four execution files and the updated runtime
README. Final live checks found zero active LLM batches, unfinished reservations,
accepted reviews and LLM graph exports. All 22 frozen case hashes matched their data.
Source totals remained 10 runs, 42,020 records and 1,405 documents.
The test logs use `deepseek-*-20260912T*.log` in that same state directory.
See [the server runbook](server-runbook.md) for connection and mount paths.

## Price and model choice

DeepSeek V4.1 Flash is a credible low-cost candidate, but these runs do not establish
that it is the best Korean extraction model. No competing model was evaluated on
labelled cases. The observed problems include the prompt/schema/validator/retriever,
so changing the model alone would not address all of them.

As checked on 2026-09-12, OpenRouter lists starting rates of **$0.15/M input and
$0.60/M output**. Strict JSON Schema support depends on the serving endpoint:
DeepInfra advertises it at **$0.20/$0.60**, Fireworks at **$0.22/$0.66**, and the Modal
endpoint used for the main batch at **$0.30/$1.20**. Starting prices are not a promise
of the price of a schema-capable routed endpoint. [Model/provider listing](https://openrouter.ai/deepseek/deepseek-v4.1-flash),
[structured-output routing](https://openrouter.ai/docs/guides/features/structured-outputs).

The observed main-batch extraction cost extrapolates to **about $2.79 per 1,000
similar postings**. That excludes positive NCS categorization, attachments/OCR,
retries, quality review and larger future JDs. The separate reasoning pilots show
why output budgets matter even for a cheap model. [DeepSeek thinking settings](https://api-docs.deepseek.com/guides/thinking_mode/).
