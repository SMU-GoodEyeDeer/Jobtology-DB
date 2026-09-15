# DeepSeek and GPT-5.6 Luna comparison — 2026-09-12

The extraction contract, evidence validation and NCS retrieval were revised, then
tested through native Hop against the same 22 frozen Korean JOB-ALIO postings.
Only `deepseek/deepseek-v4.1-flash` and `openai/gpt-5.6-luna` were called in this
comparison. All paid runs used **EVAL** mode and `ACCEPTANCE_POLICY=REVIEW`.

**Luna is the better extraction candidate under these tested settings**, with more
validated postings and reference facts at lower observed cost. Neither model is
ready for unattended acceptance. In particular, Luna's positive NCS proposals
still include overly broad and wrong-domain matches. No evaluation output was
accepted or published to the live graph.

## What changed

- **Original evidence:** the model cites stable source passage IDs. PostgreSQL
  recovers exact quotations, including intervening lines. The model no longer
  needs to reproduce the layout of a multiline quotation.
- **Composed expressions:** `ko-v3` uses literal `text_parts` for extracted text
  and literal `parts` for expression atoms. Shared wording such as
  `내과, 응급의학과 전문의 자격 소지자` can support both specialties without
  requiring each expanded phrase to appear contiguously. Each fragment is checked
  independently against its original quotation. Invented fragments still fail.
- **Condition meaning:** conditions distinguish eligibility, preference, exclusion
  and unrestricted eligibility. Targeted checks catch observed polarity mistakes,
  while allowing positive absence-of-disqualification statements in a provider's
  disqualification field. These checks are not a complete Korean semantic parser.
- **Structure and coverage:** shared conditions can reference several separately
  named positions. Indexed expression trees represent nested AND/OR, implications
  and exceptions. Invalid references, cycles and unused nodes fail. The supplied
  education field must be represented; recruitment metadata remains separate.
- **NCS candidates:** Korean word fragments, document-frequency weighting and
  balanced ranks across duties improve the lexical shortlist. The categorizer
  must still justify each proposed match against an explicit duty and the supplied
  definition. Generic advice alone does not establish a specialized activity.
- **History:** immutable `ko-v1`, `ko-v2` and `ko-v3` prompts remain installed.
  Original responses and raw outputs are retained alongside validated, hydrated
  outputs. Prompt/validator/retriever versions separate cache entries. Historical
  model outputs were not rewritten.

The initial `ko-v2` comparison revealed a remaining validator problem: Luna's
reasonable expansion of a shared specialty suffix, and text surrounding an
intervening exception, failed the contiguous-atom check. Rather than accepting
arbitrary paraphrases, `ko-v3` explicitly records separately supported fragments.
Both models were rerun with that same revision. The revised categorization prompt
also addresses an overly narrow NCS inference observed in the intermediate run.

## Evaluation design and limits

Dataset **`korean-regression-v2-22`** contains the previous 20 regression cases plus
two existing postings with explicit duties. The dataset's `v2` is independent of
the prompt version. Both models receive identical frozen source data and NCS
catalogs. Candidate lists depend on each model's extracted duties, so this compares
the complete extraction/categorization workflow, not an isolated categorizer.

| Input | Pinned value |
|---|---|
| JOB-ALIO run | `77ccb77b-3afc-4965-8ce5-efd687304954` |
| NCS run | `a32170ed-7485-4e31-82d3-ed48b3398946` |
| NCS units | 15,520 |
| NCS content hash | `bd167b84997112fb6af3dfaca45a2a060d3f24b37a2650f96e50ba2753c26afe` |
| Source manifest | [22 posting IDs and hashes](../../hop/llm/evaluation/korean-regression-v2-22.manifest.json) |
| Reference assertions | [Source assertions](../../hop/llm/evaluation/korean-regression-v2-22.assertions.json) |
| Assertion file SHA-256 | `1b704cbcf037afd7666d7433c0e5ae72f93046cff5b430fd53c0f5b03038ac23` |

The references are **provisional assistant-authored assertions, not human gold**.
They contain 32 requirement assertions and four duty assertions, written before
either model's `ko-v2` outputs and unchanged for `ko-v3`. Requirements are only
partially labelled, so requirement precision is unknown. Twenty postings have
complete empty duty/NCS references; the two duty-bearing postings have partial
duty references and no authoritative positive NCS labels.

This is a regression set, **not a held-out benchmark**: previous DeepSeek failures
informed `ko-v2`, and intermediate DeepSeek/Luna outputs informed `ko-v3`. It is also
one generation per case per model/revision, with no estimate of run-to-run variation.

The result measures must be read separately:

- **Validated items:** whole postings that pass schema, evidence and other
  mechanical checks. One invalid condition can reject a posting containing many
  otherwise useful facts. A pass does not establish completeness or correct meaning.
- **Usable assertion coverage:** reference facts recovered in validated outputs;
  rejected extraction outputs contribute zero. This is what the native
  `enrichment.batch_report.requirement_recall` reports for these partial references.
- **Raw assertion coverage:** the same fact/category/kind checks applied to retained
  model objects regardless of rejection. Matching requires both the reference
  field/quote and the reference text in the extracted text, folding whitespace.
  Selected assertions also check the logic value. It is diagnostic coverage,
  not a complete accuracy or precision score.

Neither literal fragment support nor a valid expression tree proves that the model
combined those fragments with the correct meaning. Positive NCS matches need review
against the actual definitions. Missing attachment text remains unavailable to both
models.

## Final ko-v3 results

| Measure | DeepSeek V4.1 Flash / Modal | GPT-5.6 Luna / OpenAI |
|---|---:|---:|
| Schema-valid extraction responses | 22/22 | 22/22 |
| Validated postings | **9/22 (40.9%)** | **16/22 (72.7%)** |
| Rejected postings | 13 | 6 |
| Usable requirement assertions | **9/32 (28.1%)** | **21/32 (65.6%)** |
| Raw requirement assertions | **24/32 (75.0%)** | **27/32 (84.4%)** |
| Usable duty assertions | 2/4 | 4/4 |
| Raw duty assertions | 4/4 | 4/4 |
| Paid requests | 24: 22 extraction + 2 categorization | 24: 22 extraction + 2 categorization |
| Input / output tokens | 89,066 / 41,596 | 93,294 / 36,442 |
| Reported cost | **$0.07442316** | **$0.06011442** |

All 48 final paid requests returned HTTP 200 and schema-valid objects, with no
truncation, unknown returned costs or Hop cache hits. Both native workflows exited
successfully. Both batches have state `PARTIAL`, because rejected model outputs
are retained instead of being treated as completed valid extractions.

The richer contract did **not** uniformly improve generation quality. Compared
with the intermediate run, DeepSeek's validated count fell from 12 to 9; Luna's
rose from 12 to 16, while its raw assertion coverage fell from 30 to 27. These are
new model generations, not a controlled test that isolates each prompt change.
Do not interpret the implementation fixes as a guarantee of better model accuracy.

### Remaining rejection and semantic examples

- **Luna, physician postings `300965`, `299690`, `304165`:** all nine positions
  were identified, but fifteen atoms still put expanded specialty phrases into
  one fragment instead of splitting off the shared suffix. `ko-v3` supports the
  correct split form; these outputs did not use it. The intended specialty meaning
  is plausible, so these are evidence-contract failures rather than proof of poor
  medical-language understanding. `304165` also misclassified an exclusion.
- **Luna, `304648`:** a copied source phrase changed the name of a cited act by
  adding wording. The fragment check rejected the altered quotation. `304400`
  mixed citation fields; both models produced invalid tree references in `304630`.
- **DeepSeek:** empty text fragments, unknown position IDs and broken condition
  trees contributed to rejections. Four postings omitted the supplied education
  field. In `304435`, three disqualifying conditions were labelled eligibility and
  correctly blocked. `304676` made the opposite polarity error: positive absence
  of disqualification was labelled exclusion.
- **Meaning still slips through validation:** Luna labelled supplied `석사,박사`
  in `295717`, and `고졸` in `304435`, as unrestricted. Those postings validated
  but failed their education assertions. Both models also used `single` for some
  comma-separated degree alternatives. The education-presence check is useful,
  but does not prove its classification or logic.
- **Positions and exceptions still need review:** Luna combined
  `일반(공통) 및 정보기술(IT)` into one position in validated posting `304450`.
  Both models preserved the written exceptions in `304660` but represented them
  as `single`, without a machine-readable exception tree. The protocol now permits
  the correct structures; it does not guarantee that the model chooses them.

Luna's six rejected postings are `304648`, `304400`, `304630`, `300965`, `299690`
and `304165`. DeepSeek's thirteen are `304450`, `304574`, `304237`, `304400`,
`304630`, `304830`, `304676`, `304445`, `304741`, `304165`, `295717`, `304739`
and `304435`. Source IDs and original responses are retained for review.

### NCS findings

**Luna:** both real duty-bearing postings reached categorization. In `304435`,
`1202020102_16v2` (장례식장 운영지원) and `1202020103_16v2` (장례식장 시설관리)
have plausible overlap with the explicit funeral-service and facility duties.
These are assistant-reviewed observations, not gold-confirmed NCS labels.

For labor adviser `304602`, Luna proposed six duty/code pairs. Several reasons
only claimed partial relevance despite the prompt requiring substantial work
overlap. `0202020201_19v2` (노사관계 계획) adds goals, strategy and execution-plan
work that the general-advice duty does not establish. More clearly,
`1002010309_14v1` (권리구제 분석(구버전)) belongs to **부동산경·공매** and its
definition concerns rights affected by a court disposition; the JD describes
labor complaints and representation. That proposal is unsuitable. Labor-dispute
and conflict-management candidates also require closer scope review.

**DeepSeek:** it abstained on the explicit labor-adviser duties. Its other paid
categorization was triggered by `304844`, where it promoted the recruitment label
`환경미화` to an actual duty and proposed `1102010103_15v1` (청소활동수행). The
source gave a recruitment category, not described cleaning activities. This passed
literal-evidence checks but violates the extraction/categorization policy.

Thus improved retrieval now supplies plausible domain candidates, but **positive
NCS precision is not established**. The report's zero precision for DeepSeek is
limited to the complete empty-reference subset, where that cleaning match is a
false positive; positive-duty cases have no authoritative NCS labels. Do not use
either model's proposals as verified links automatically.

### Final batches and costs

| Run | Batch ID | Goldship log filename |
|---|---|---|
| DeepSeek ko-v3 | `37c632dc-bd97-47b6-9658-751b8dbfd5d0` | `v3-deepseek-22-20260912T082053Z.log` |
| Luna ko-v3 | `1139c5d4-a168-495a-8551-3d3f397de12c` | `v3-luna-22-20260912T082057Z.log` |

Logs are under `~/.local/state/jobtology-hop/` on Goldship. DeepSeek completed at
2026-09-12 08:25:18 UTC; Luna completed at 08:26:39 UTC.

The final pair cost **$0.13453758**. Including the two pilots and intermediate
comparison, this task's returned response costs total **$0.26919762**, about
27 cents across 96 paid logical requests. Including the earlier `ko-v1` work,
returned costs total **$0.35543184**. This is the response-cost ledger; the separate
account usage check is recorded below.

### Suggested use

Use Luna for the next **reviewed extraction** batch with the parameters below.
Keep `ACCEPTANCE_POLICY=REVIEW` and review NCS proposals separately. Model
parameters remain configurable; this test did not switch the workflow's existing
default model automatically. The comparison uses reasoning disabled for both
models and does not establish which is best with other reasoning settings.

Before automatic acceptance, address evidence-contract repair, position splitting,
education-kind checks and exception-tree coverage, then evaluate on 100–200 newly
reviewed postings with enough explicit duties to judge positive NCS precision.
The current regression cases should remain unchanged for replay.

## Intermediate ko-v2 runs

These runs are retained to explain the validator correction, not selected as the
final comparison. Both full batches returned 22 schema-valid extraction objects.

| Model | Validated postings | Usable requirement assertions | Raw requirement assertions | Paid requests | Reported cost |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4.1 Flash / Modal | 12/22 | 16/32 | 24/32 | 23 | $0.07259160 |
| GPT-5.6 Luna / OpenAI | 12/22 | 19/32 | 30/32 | 23 | $0.05424314 |

Both recovered all four duty assertions in their raw responses; each had only two
usable assertions because one of the two duty-bearing extractions was rejected.
DeepSeek's labor-adviser categorization proposed a collective-agreement implementation
unit from general labor-law advice, an insufficiently supported specialization.
Luna's hospital posting proposed funeral-service and funeral-facility units; its
labor-adviser extraction was rejected for mixing citation fields.

| Run | Batch ID | Reported cost |
|---|---|---:|
| DeepSeek ko-v2 one-posting pilot | `2610e686-1e3d-447e-87d5-5bbccbb93045` | $0.00439710 |
| Luna ko-v2 one-posting pilot | `de8075c9-d2b7-462d-ace3-237d041cf01d` | $0.00342820 |
| DeepSeek ko-v2 full comparison | `5564bee4-046d-452e-aa8f-2869b7c896e1` | $0.07259160 |
| Luna ko-v2 full comparison | `80c6aa9a-4e1a-4031-a745-06385df83a6a` | $0.05424314 |

Intermediate run and pilot costs total **$0.13466004**. The
[earlier ko-v1 experiments](llm-deepseek-evaluation-2026-09-12.md) cost another
$0.08623422 before this task.

## Reproduce in Hop

1. Run `${PROJECT_HOME}/llm/install.hwf` with `llm-local`; repeat installation is
   additive and preserves existing results. Goldship is already updated.
2. Run `llm/prepare_regression_v2.hwf` once. This verifies the pinned snapshots and
   all source hashes, freezes the 22 cases and imports the provisional assertions.
   It makes no paid calls. The exact referenced snapshots must exist; do not
   silently substitute a newer source. Repeating the workflow preserves cases and
   appends an identical reference revision.
3. Run `llm/evaluate.hwf` twice with the shared settings below, changing both model
   parameters and `PROVIDER_ONLY`. Inspect the daily budget ledger first. Setting
   `EXECUTE_REQUESTS=Y` makes paid calls; use `N` to plan only.
4. Preview `llm/inspect_comparison.hpl` for this dataset and
   `llm/inspect_results.hpl` with each batch ID. Retain rejected outputs for review.

The result view intentionally leaves rejected extraction objects empty. To inspect
their original model output, use a read-only Table Input/SQL query, substituting
the actual batch ID:

```sql
SELECT i.posting_id, a.stage, a.state, a.issues, a.raw_output
FROM enrichment.attempt a
JOIN enrichment.item i USING (item_id)
WHERE a.batch_id = '<batch-id>'
ORDER BY i.ordinal, a.stage;
```

| Shared parameter | Comparison value |
|---|---|
| `DATASET_ID` | `korean-regression-v2-22` |
| `PROMPT_VERSION` | `ko-v3` |
| `POSTING_LIMIT` | `22` |
| `REUSE_CACHE` / `ACCEPTANCE_POLICY` | `N` / `REVIEW` |
| `EXECUTE_REQUESTS` | `Y` |
| `REASONING_EFFORT` / `TEMPERATURE` | `none` / blank (omitted for both) |
| `MAX_INPUT_CHARS` / `MAX_OUTPUT_TOKENS` | `60000` / `16000` |
| `CANDIDATE_LIMIT` / `MAX_MATCHES` | `40` / `8` |
| `MAX_REQUESTS` | `30` per batch |
| `REQUEST_RESERVE_USD` / `MAX_COST_USD` | `0.05` / `1.50` per batch |
| `DAILY_BUDGET_USD` | `8.00` shared rolling accounting cap for the final comparison |
| `REQUEST_DELAY_MS` / `READ_TIMEOUT_MS` | `1000` / `180000` |
| `EXTRA_PARAMS_JSON` | `{}` |

For DeepSeek, set both models to `deepseek/deepseek-v4.1-flash`, provider `modal`.
For Luna, set both to `openai/gpt-5.6-luna`, provider `openai`. Luna's endpoint does
not advertise temperature support; leave that setting blank. Both runs disable
reasoning. This does not compare their higher reasoning settings. Provider fallback
is disabled and supported parameters are required.

The workflow's accounting uses the greater of reported cost and reserved cost,
including old unresolved charges. The rolling cap was $5.50 for the intermediate
comparison, then $8.00 for the final reruns; previous reservations were preserved.
These caps are accounting controls, not a provider-enforced dollar ceiling.
The workflow guide documents the native HTTP client's
[429 retry limitation](../../hop/llm/README.md#workflow-parameters).

Provider pricing and options were checked on 2026-09-12. Modal's selected DeepSeek
endpoint listed $0.30/M input and $1.20/M output; Luna's standard OpenAI endpoint
listed $0.20/M input and $1.20/M output, with separate cache pricing. These are
provider-specific routes, not necessarily each model's cheapest advertised route.
The result tables use actual returned costs, including reported cache charges,
rather than inferring charges from headline prices. `REUSE_CACHE=N` disables Hop's
result cache; provider-side prompt caching can still affect billed cost. See
[DeepSeek endpoints](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash/endpoints),
[Luna endpoints](https://openrouter.ai/api/v1/models/openai/gpt-5.6-luna/endpoints), and
[Luna's model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

## Implementation verification and deployment

`python hop/llm/tests/run.py` passed in disposable Hop 2.19.0, PostgreSQL 17 and
Neo4j 5.26 with a local HTTPS fixture. It exercised all three prompt versions,
schema/transport failures, spend reservations, cache separation, citation recovery,
condition polarity, omitted education, shared positions, nested expressions,
composed fragments, unsupported qualifications/thresholds, improved retrieval,
native evaluation/enrichment, review and idempotent publication/revocation. The
publication checks used the disposable graph. Test log root:
`/tmp/jobtology-llm-tests-0cgjjhdt` on the workstation.

Goldship's persistent default project was updated without restarting Hop. All
replaced files were checked against their previous hashes before mutation, backed
up, atomically replaced, and verified against local hashes. Existing secrets and
private connection metadata were untouched. Native installers succeeded.

- Intermediate deployment: 19 public files, backup and manifest at
  `~/.local/state/jobtology-hop/v2-deploy-20260912T080028Z/` on Goldship.
- Final protocol deployment: 13 incremental public files, backup and manifest at
  `~/.local/state/jobtology-hop/v3-deploy-20260912T082041Z/` on Goldship.
- Final README sync: two files, backup and manifest at
  `~/.local/state/jobtology-hop/comparison-docs-20260912T082947Z/`. Afterward,
  **all 54 public LLM runtime files matched their local SHA-256 hashes**.

The [server runbook](server-runbook.md) describes SSH, the Docker volume, project
paths and safe editing. Future agents should inspect saved batch data and these
manifests before rerunning paid evaluations.

Final read-only checks at 2026-09-12 08:27:53 UTC confirmed all 22 source hashes,
all 44 comparison items against the frozen input, and identical pinned reference
revisions across the two batches. There were **zero running LLM batches, reserved
in-flight attempts, accepted reviews or LLM graph exports**. Source totals remained
10 ingestion runs, 42,020 records and 1,405 archived documents. The rolling LLM
accounting ledger was **$7.10**, including prior conservative reservations.

The final OpenRouter credits check returned HTTP 200, total funded credits $8.00,
settled usage **$0.35543184** and remaining balance **$7.64456816**. Settled usage
matched the combined response-cost ledger exactly; an earlier check briefly lagged
behind the latest responses. No credit or key contents were changed.

Reusing the final run's $8.00 rolling accounting cap immediately leaves $0.90,
or 18 reservations of $0.05, until earlier reservations leave the 24-hour window.
That is insufficient for another complete 22-posting run. Inspect the ledger and
choose the next batch's limits deliberately; $7.10 is reserved/accounted capacity,
not the amount actually billed.
