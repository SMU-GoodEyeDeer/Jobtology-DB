# LLM workflow deployment verification

**Resumed with OpenAI BYOK, 2026-09-14 21:25 KST:** the user explicitly resumed
the final linked-ingestion phase after adding OpenAI BYOK to OpenRouter. Native
EVAL batch `9daebf59-5aef-4219-8cc3-44e052dc5853` proved that both Luna calls
were served by `OpenAI` with `usage.is_byok=true`. Hop recorded the exact upstream
charges, **$0.00610420** total, rather than OpenRouter's deliberately zero BYOK
cost. Cached-recovery batch `a562e922-561f-4623-98b8-e48262cff79e` then completed
17 missing categorization calls without a rate-limit error: 16 validated, one
rejected for `CODE_OUTSIDE_SHORTLIST`, **$0.11850965** total. The protected key
and provider selection did not change. Full recovery is tracked in the
[current linked-ingestion handoff](linked-ingestion.md).

The previous 16:53 KST pause is now historical. Its record was backed up before
`linked-ingestion-pause.json` was atomically marked resumed; old attempts and
review decisions remain preserved.

Full BYOK retry batch `20b08f34-24ca-4590-8b3b-973832109bf3` exhausted its
explicit $5.00 batch cap without a provider failure. It processed all 485 remaining
extractions: 353 validated and 132 were retained as validation rejections. It then
made 144 categorization calls: 142 validated and two rejected; two no-duty cases
were skipped. The remaining 207 categorization requests were marked
`BUDGET_BLOCKED` without being sent. Reported upstream cost is **$4.95659390**,
with zero unknown-cost requests. Given the user's pre-run $5.50 OpenAI balance and
the $0.12461385 pilot/recovery spend, the expected remaining balance is about
**$0.42** at that point.

**Cached categorization recovery, 2026-09-14–15 KST:** after the user added $5,
batch `05b85808-20d3-496d-b12d-d747d6bc1fe9` selected the exact 207 items whose
categorization had been budget-blocked above. All **207 extraction IDs matched and
reused the prior saved attempts**, so extraction sent zero provider requests. The
four-worker categorization made exactly 207 OpenAI BYOK calls: **198 validated and
9 were retained as model-validation rejections**, for **$2.33157160**. All responses
reported HTTP 200, provider `OpenAI`, and `usage.is_byok=true`; there were zero
transport, provider, budget, or unknown-cost failures. The workflow is terminal
PARTIAL only because of those nine validation rejections. Exact selection, job,
workflow, log and verification are preserved under
`~/.local/state/jobtology-hop/byok-cached-categorization-20260914T2330KST/`.
The temporary runtime workflow was removed after completion. Based on the earlier
balance estimate plus the $5 recharge, the expected remaining OpenAI balance is
about **$3.09**; this is an accounting estimate rather than a fresh provider balance
read. No extraction-rejection retry was started.

The Hop 2.19 CPU busy-wait reported during that live run is fixed in the generated
request runners and deployed on Goldship. In the final full-suite check, a
deliberately restored shared-Abort control used **3.140 CPU-seconds / 3.164 elapsed
seconds** during an eight-second delayed mock response. The two-single-input-Abort
version used **0.100 CPU-seconds / 3.184 elapsed seconds**. An earlier focused run
measured 3.220/3.165 and 0.090/3.191 respectively. Both error-count and
unsuccessful-result paths aborted through their own transform in native fixtures.
The deployment ran only after batch `20b08f34-24ca-4590-8b3b-973832109bf3` became
terminal and while both the active-batch and reserved-request counts were zero.
Receipt: `~/.local/state/jobtology-hop/linked-ingestion-deploy-20260914T140804Z/`.
All four deployed files match the tested hashes, and each Abort has exactly one
incoming hop.

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](linked-ingestion.md) for what is actually tested/deployed.

## Historical status — September 13 attachment pause

**2026-09-13 KST:** do not resume attachment downloads/parsing, input rebuilding
or attachment-aware LLM extraction/categorization until the user explicitly asks.
The latest no-spend preview was stopped, and the planned paid pilot was not
launched. Existing source data and results remain preserved. See the
[pause scope, verification and restart handoff](attachment-status.md).

## Historical September 12 deployment — compact inputs; preview stopped

The `field-lines-and-tables-v1` input encoding is deployed for new ko-v7 requests.
It groups exact text by field/line number and joins HWPX blocks into logical table
rows, preserving merged cells, nested tables, captions and empty cells. Original
frozen text, hashes, evidence offsets, document outcomes and review records remain
unchanged. Three public files were installed with native Hop exit 0. Receipt:
`~/.local/state/jobtology-hop/document-packet-deploy-20260912T155537Z/`.

The focused native regression passed. An independent decoder checked every one
of the 513 frozen inputs: 223,976 passages, 6,336 HWPX input blocks, 308 tables and
4,456 cells. Reconstructed complete extraction requests all fit 200,000 characters;
the largest was 159,547. These are local size/structure results, not model-quality
results or a substitute for the fresh native preview.

That preview was intentionally stopped under
`~/.local/state/jobtology-hop/document-packet-full-preview-20260912T155621Z/`,
reusing `korean-attachments-sourcebound-v1-513` without recreating input bundles.
`EXECUTE_REQUESTS=N`. Batch `d861198b-d282-4e6c-9963-d5ff10396189` remains
PLANNED with 513 planned request rows and zero sent model requests (rechecked at
02:09:12 KST on September 13: no reservations or responses). Its supervisor records FAILED after the
intentional SIGTERM at 15:58:40Z on September 12; `pause-request.json` and
`pause-verification.json` distinguish this user stop from a software failure.
Exact processes stopped, locks were released, and no active preview query,
RUNNING enrichment batch or RESERVED request remained. Do not restart it while
the hold applies. No paid pilot or production acceptance was added.

A fresh authenticated credit read at 15:57:14Z on September 12 reported
**$6.03993481 remaining**. A same-three-case Luna/OpenAI evaluation with ko-v7,
medium reasoning, REVIEW and a $0.60 cap was prepared but not launched. It must
wait for explicit user resumption, a completed native preview and a fresh credit
check. Full paid expansion also remains conditional on semantic review.

## Earlier work — source-bound requests deployed; full no-spend preview finished

New ko-v7 extraction requests now constrain citations to exact original passage
IDs and ranges to one narrative field. Correlated schema branches prevent metadata
ranges and incompatible context/duplicate fields. PostgreSQL independently checks
the request schema before hydration. Invalid reviewer-supplied ranges now return
the controlled validation error before attempting range expansion. Historical
prompts, attempts, inputs, review decisions and release state were preserved.

Native tests cover two-stage execution, cache replay, invalid provider citations
and correction-history preservation. An independent check verified source hashes,
text/offsets and generated schemas for **513 inputs / 223,976 passages**. Five
public files were deployed; the native installer exited 0. Receipt:
`~/.local/state/jobtology-hop/source-bound-deploy-20260912T152812Z/`.

A full **EXECUTE_REQUESTS=N** preview finished through the native attachment
input and LLM workflows at 15:38:53Z on September 12 (00:38:53 KST on September 13).
All 513 source hashes matched: **509 requests fit**, and four were explicitly
rejected as oversized. Their sizes are 200,838 (304429), 215,221 (304432), 279,668
(304713) and 228,184 (304839) characters against the 200,000-character limit.
Nothing was truncated. Median complete request size was 62,784 characters; total
size was 36,719,198. This measures input planning, not model quality. Receipt:
`~/.local/state/jobtology-hop/source-bound-full-preview-20260912T152838Z/`.
The input dataset is frozen; dry EVAL batch
`55f15bc1-149e-4944-be68-d9a8fe72443f` has `EXECUTE_REQUESTS=N`. The supervisor is
FINISHED with exit 0, zero new reservations and zero paid calls; do not restart it.
The preview retains a six-request/$0.60 cap and is not a full paid-run configuration.

No paid calls or new production approvals were made for this change. The earlier
three-case pilot remains rejected. Seven partial source-review checkpoints now
record role scope, research scoring, bonus rates/limits and military alternatives;
they are separate from model inputs and are not human gold or acceptance decisions.
Full paid expansion remains on hold for semantic extraction/review fixes and
context-preserving handling of the four oversized postings. See the
[completion ledger](ontology-completion.md) and [operator guide](../../hop/llm/README.md).

## Earlier ko-v7 pilot — finished; quality repair pending

The ranged source-accounting contract is deployed. `ko-v7` preserves every source
passage in expanded coverage while allowing consecutive uncited lines to share a
context/disposition range. The schema enforces matching logic/condition shapes;
explicit applicant restrictions cannot be hidden under broad document context.
The default remains ko-v3, and v7 requires REVIEW. Native LLM regression, document
evidence assembly and Neo4j replay tests passed. Existing prompts, outputs, inputs,
decisions and release state were preserved by deployment.

The frozen three-posting `korean-attachments-v2` sample finished with Luna/OpenAI,
ko-v7 and medium reasoning at 15:04:08Z on 2026-09-12 (00:04:08 KST on September 13).
Batch `9bd86bc7-165a-4b14-b41c-ebcb79723ddb` is PARTIAL: **three HTTP-200
responses, zero validated extractions, three rejections, no categorization calls**,
and **$0.03981502 reported cost**. The supervisor finished with exit 0; do not restart
this completed pilot. Receipt:
`~/.local/state/jobtology-hop/attachment-luna-v7-pilot-20260912T145957Z/`.

The recorded errors are invalid source-accounting ranges: metadata treated as
narrative, invalid range ordering/fields, and invalid duplicate declarations.
These checks return early, so the short issue lists are not full semantic-error
counts. Offline inspection of posting 303324 after removing only redundant
metadata ranges also found omitted research-scoring rules and incorrect position
scope. That diagnostic copy was not accepted or written as a production correction.
Prompt/schema and reasoning changed together; this is not a model-only comparison.

Full paid attachment expansion remains on hold for extraction and review fixes.
Review/link/release fingerprints were unchanged by the pilot: the recorded
production state remains one accepted inline extraction, zero accepted NCS links
and zero active ontology releases. The immediate post-run credit receipt showed
$6.04820322 remaining; it may lag final charge settlement and must be rechecked
before further paid expansion. See the [completion ledger](ontology-completion.md).

## Earlier attachment pilot — ko-v6 finished with rejections

Native HWPX paragraph/table reconstruction and v2 model inputs are deployed and
independently verified. All 513 posting inputs account for 1,702 attachment
metadata entries and supply 889 document fields. Of 32 HWPX files, 29 reconstructed
successfully; two highlight-marker cases and one script-bearing package remain
explicit follow-ups. Earlier input bundles, model outputs and reviews are intact.

The frozen `korean-attachments-v2` pilot passed its native no-spend request check.
Paid Luna/ko-v6 EVAL batch `39002649-313f-418d-bf26-230357839210` finished PARTIAL at
14:22:09Z on 2026-09-12: three HTTP-200 extraction responses, **zero validated**,
three rejected, no categorization calls, **$0.05187852 reported cost**. Most issue
entries concern source coverage, with additional evidence, polarity and condition
tree failures. Counts are not independent semantic-error counts. The supervisor
also finished; do not restart this completed pilot. See the
[receipt and completion ledger](ontology-completion.md#native-hwpx-structure-and-full-v2-inputs--2026-09-12)
for details. The immediate post-run credit receipt reported $6.08343804 remaining;
provider usage may settle later, so recheck before paid expansion. No ontology
release is active. Canonical document input/evidence integration is now deployed
and passed native Hop/Neo4j fixtures and saved-real-corpus compatibility checks;
see [the integration ledger](ontology-completion.md#canonical-document-evidence-integration-deployed--2026-09-12)
and [binding instructions](../../hop/ontology/README.md). Full production
extraction/review/linking remains unfinished. A live transaction verified all 513
v2 input bindings and rolled back; production input/review selection remains open.

## Earlier work — versioned attachment inputs

The native input bridge is deployed. `attachments/prepare_inputs.hwf` freezes
inline posting fields, parsed document text, all attachment outcomes and exact
source/attempt/page-or-section bindings. `INPUT_BUNDLE_IDS` selects ENRICH inputs;
EVAL uses a new frozen dataset. Both require ko-v6 and REVIEW. Historical inline
items, corrections and decisions are unchanged. The full native LLM regression
suite and native input planning/replay tests passed; deployment preserved existing
source, model, review, attachment and release data.

The original full pass parsed 888 of 909 selected PDF/HWP/HWPX documents. A targeted
metadata-preserving retry recovered four more PDFs, giving 892 PARSED when those
retry outcomes are selected. Twelve documents have no text, one PDF remains
malformed, and four need review. Other formats and attachment-role review remain
unfinished. The 29,315-character HWPX pilot notice also needs paragraph/table
structure handling: its existing Tika text is flattened to five nonempty lines.

All 513 pinned posting inputs are prepared and independently verified, covering
1,702 metadata entries, 892 parsed document fields and 4,125 section ranges. The
three-case `korean-attachments-v1` dataset is frozen. See the live receipts in the
[completion ledger](ontology-completion.md#attachment-metadata-repair-and-versioned-llm-inputs--2026-09-12).
No attachment-aware model requests have been made. The authenticated credit read
at 13:27:36Z on 2026-09-12 showed $6.13162835 remaining. Canonical source selection,
document evidence projection and semantic review remain necessary before
attachment-aware claims can enter an ontology release. No ontology release is active.

Eight partial source-located attachment assertions cover real NCS references versus
an illustrative code, conditions and notice/JD conflicts. They are assistant-authored
checks, not human gold or production acceptance.

## Earlier current work — source review and explicit condition effects

Cross-batch repair protection and separately reviewed guarded rules are now
deployed. Native tests verified rule/predicate/evidence loading into Neo4j,
correction and revocation selection, unchanged replay, and protection against
uncited intervening text. Two real interpretations remain pending review. See the
[completion ledger](ontology-completion.md#cross-batch-repair-protection-and-explicit-rule-effects--2026-09-12)
for exact deployment and verification receipts.

Posting **304817** has the first independently accepted production extraction
revision: `54d10986d846500f857b2504d34122f4f69a3fa3d6e0fbd19ebd0ea80423babc`.
An assistant source review checked its one position, one explicit medical duty,
and nine requirements. A correction preserved male-only applicability and the
completed-service OR exemption alternatives. All other provider fields and the
original request remained intact. This acceptance covers the inline extraction;
attachment processing and typed concept/condition resolution remain unfinished.

Its native NCS-only batch `1047d201-e162-4d3b-adf6-ef9537a94ca2` completed with one
request costing **$0.00173645** and no repeat extraction. The model returned
`no_supported_match`; source review found that none of the 40 retrieved candidates
supported the physician's stated clinical duty. No link was forced or accepted.
This checks one real abstention, not general retrieval recall or NCS precision.

No ontology release is active. The full 513-posting review/linking task remains
in progress; do not read one accepted source revision as corpus completion.

## Earlier ko-v6 repair work

The nested-condition/source-accounting contract is deployed after focused native tests.
It retains original provider JSON, generates canonical tree indices in PostgreSQL and
records cited/unhandled source passages. Categorization now receives posting context.
The default remains ko-v3. The five-posting ko-v6/Luna pilot finished for $0.01989009:
two validation passes and three rejections. Source review then rejected both passes
because their condition trees still change the meaning. A bounded two-case trial
with reasoning enabled is recorded in the [completion ledger](ontology-completion.md).
No ontology release is active. Validation success alone is insufficient for publication.

`categorize_reviewed.hwf` is now deployed and tested for NCS-only processing of
exact accepted extraction revisions. It preserves corrections, independent link
decisions, request accounting and NCS snapshot lineage. Its live dry-run check
rejected a pending revision before a model call; no production acceptance was
created to exercise the workflow. See the [operator instructions](../../hop/llm/README.md#categorizing-a-reviewed-extraction-revision).

## Latest update — ontology completion and full-source pass, 2026-09-12

ko-v4, settled-cost accounting, and independent extraction/link review with append-only
corrections are deployed and tested. The new Luna regression passed structural/source checks
for 20/22 postings, recovered 30/32 provisional requirement references and 4/4 duty references,
and cost $0.06070865. These are regression results, not a held-out semantic precision claim.

The current 513-posting ENRICH batch is **`5f5a5c79-8026-41ae-b08a-09bdc4b3f848`**, launched
with explicit ko-v4/Luna parameters, REVIEW policy and a $2 batch cap. Its source hashes were
verified against every pinned posting. It finished PARTIAL: 322 validated extractions,
191 rejected extractions, 42 completed categorization calls and 280 categorization skips
for missing explicit duties. Its 555 requests cost $1.40102046, with no unknown charges.
No production ontology completion or
independent-review graph publication is claimed. See [the active work and verification
ledger](ontology-completion.md) for process handles, logs, test evidence and remaining work.
The workflow parameter default is still ko-v3; the full pass explicitly selects ko-v4.

The ko-v5 audit/repair implementation is deployed after its full native integration
suite passed. The installer preserved original prompts, attempts, costs and decisions.
The live audit matched all 513 saved-source checks: 272 clean outputs were captured
as review candidates, and 241 retained review/repair issues. This
revalidation neither accepts outputs nor rewrites original attempts. See the completion
ledger for deployment, live audit and paid pilot evidence.

The six-case ko-v5 repair pilot finished for $0.02064220: three extractions validated
and three rejected. Independent source inspection also found missing bonus qualifiers
and incorrectly connected condition branches in two validated outputs; both proposed
NCS links lacked occupational-context support. Do not expand this pilot configuration
or equate its validator passes with acceptance. The next repair work must address
condition representation and source coverage alongside independent semantic review.

The native ontology source/claim assembly is now installed separately under
`ontology/`. Its saved-real-output test preserved 1,850 claims from 128 validated
outputs with zero field/expression or evidence-offset differences. Those tests
used synthetic local acceptance only; no production extraction/link decisions
were written. See the [ontology workflow guide](../../hop/ontology/README.md).

The native ontology graph candidate loader is also installed. Its disposable
full-data test verified 182,670 nodes and 785,235 relationships, including every
typed property, label, endpoint and release membership. The live initial release
still has no frozen reviews or active publication. This verifies loading behavior,
not the semantic quality of the fixture's synthetically accepted outputs.

## Earlier ko-v3 contract and model comparison, 2026-09-12

The persistent Hop project now defaults to prompt/schema **`ko-v3`**, with numbered
source passages, independently verified text fragments, explicit condition kinds,
shared position references and nested condition expressions. NCS retrieval now
weights Korean word fragments and balances candidates across duties. Older prompt
versions and model results remain available.

Both models were tested through native Hop on the same frozen 22 Korean postings,
with reasoning disabled, no Hop cache reuse and `ACCEPTANCE_POLICY=REVIEW`:

| Final ko-v3 run | Validated postings | Usable requirement assertions | Raw requirement assertions | Reported cost |
|---|---:|---:|---:|---:|
| DeepSeek V4.1 Flash / Modal | 9/22 | 9/32 | 24/32 | $0.07442316 |
| GPT-5.6 Luna / OpenAI | 16/22 | 21/32 | 27/32 | $0.06011442 |

These are **partial assistant-authored source assertions, not human gold or a
held-out accuracy benchmark**. All 48 final requests returned HTTP 200 and
schema-valid objects; model output still failed evidence/condition checks in some
cases. Some validated objects also contained semantic errors. Luna is the better
extraction candidate in this comparison; its NCS proposals still need review.

The full suite passed across ko-v1/v2/v3 using disposable Hop/PostgreSQL/Neo4j and
HTTPS fixtures. Native installers succeeded on Goldship. Source snapshots were
preserved and all 54 public LLM runtime files matched their local hashes. No paid
requests remain active, and **no LLM output was accepted or
published**. Keep `ACCEPTANCE_POLICY=REVIEW`.

The final comparison cost $0.13453758; including pilots and the intermediate ko-v2
comparison, this task cost $0.26919762 in returned response charges. See the
[comparison report](llm-model-comparison-2026-09-12.md) for exact batch IDs,
rejections, NCS findings, deployment backups, accounting and reproducible settings.

## Earlier update — first paid ko-v1 evaluation, 2026-09-12

The OpenRouter account is funded. A paid native Hop pilot with
`deepseek/deepseek-v4.1-flash` returned HTTP 200, structured JSON, token usage and cost.
That confirms the live connection; it does not establish extraction quality.
The subsequent evaluation exposed an upstream Fireworks rate limit. The workflows now
accept `PROVIDER_ONLY` and stop further logical attempts after HTTP 401/402/403/429.
See the [HTTP-client retry limitation](../../hop/llm/README.md#workflow-parameters)
before treating request reservations as a physical HTTP-call limit.

The completed 20-posting evaluation on Modal returned **20 schema-valid outputs,
11 validated items and 9 rejected items**, costing **$0.0557964**. A separate two-posting
duty sample exercised the live NCS categorizer, which abstained against an inadequate
shortlist; that sample cost **$0.0060057**. Neither run published LLM results.
Review identified exclusion-polarity, condition-logic, completeness and retrieval gaps.
That ko-v1 prompt/validation setup was **not ready for unattended production acceptance**.
See the [full paid evaluation report](llm-deepseek-evaluation-2026-09-12.md) for batch IDs,
case observations, reasoning pilots, costs and reproducible Hop parameters.

The updated native integration suite passed on 2026-09-12, including provider selection,
cache separation and stopping later postings after an HTTP 429 response.

## Original installation verification — 2026-09-11

The native artifacts are installed in Goldship's persistent default Hop project at
`/usr/local/tomcat/webapps/ROOT/config/projects/default/llm`.
The `llm-local` pipeline and workflow run configurations disable row sampling and
execution-data capture. All 41 deployed public runtime files matched their local
SHA-256 hashes after installation. Private connection metadata and credentials were
not copied to the repository.

### State at initial installation

| Item | Verified result |
|---|---|
| OpenRouter key | `GET /api/v1/key` returned HTTP 200; authenticated. No inference endpoint was used. |
| Key file | Existing `config/secrets/openrouter.csv`, mode `0600`, owned by Hop UID/GID 501. |
| Installer | Native `llm/install.hwf` completed; repeat installation preserved data. |
| Evaluation dataset | `korean-jd-v1`, 20 real Korean JOB-ALIO postings. |
| Sampling | Four each: alternatives, multiple positions, attachment references, unrestricted eligibility, general. |
| JOB-ALIO snapshot | `77ccb77b-3afc-4965-8ce5-efd687304954` |
| NCS snapshot | `a32170ed-7485-4e31-82d3-ed48b3398946`, 15,520 cached competency definitions. |
| Dry-run batch | `c1a567ac-083e-4e72-8647-c1fa82e890a8`, state `PLANNED`. |
| Prepared requests | 20 extraction requests, all `PLANNED`; categorization awaits extraction. |
| Paid/model requests | **0** reservations, **0** responses, **0** accepted enrichments. |
| Gold labels / model-quality scores | None yet; quality has not been measured on real postings. |
| Review document | `${PROJECT_HOME}/data/llm/korean-jd-v1-review.json`, exported by native Hop. |
| Automatic LLM schedule | None; source refresh does not invoke paid LLM work. |

The current accepted source counts remained 355 organizations, 1,012 posting
representations / 506 jobs, 15,520 competencies, 87 qualification mappings,
56 exam sessions and 12,864 career records. No live inferred Neo4j relationships
were created because there are no model outputs to accept.

### Isolated implementation checks

The tests ran native Hop 2.19.0 against disposable PostgreSQL 17 and Neo4j 5.26,
with an HTTPS OpenRouter-shaped fixture server on an internal Docker network.
The server used a test certificate explicitly trusted by the test runner. TLS
verification remained enabled. Credentials were synthetic.

Passed checks include:

- Native SQL installer, repeat installation, frozen sample preparation and no-key dry run.
- Two extraction calls and one categorization call for two synthetic Korean postings;
  the attachment-only posting abstained without a categorization call.
- JSON Schema, evidence quotes, preference/requirement separation, out-of-shortlist codes,
  invalid duty indices, malformed/duplicate-key JSON, truncation and refusals.
- Actual request/response JSON handling, trace metadata, usage/cost storage and no gold-label leakage.
- Repeat-cache reuse with no additional mock requests, and changed-content cache invalidation.
- Request caps, durable reservations, duplicate-reservation denial, unknown-charge accounting,
  and a duplicate-key CSV rejected before any reservation or HTTP request.
- Gold-file import, pinned gold labels, requirement/NCS metrics and correct abstention counts.
- EVAL isolation from publication, manual acceptance, automatic `VALIDATED` acceptance policy,
  and continued EVAL isolation even when that policy is selected.
- Neo4j property/evidence/count verification, repeated publication without extra nodes or
  relationships, and revocation in both the current PostgreSQL view and synchronized graph.
- Native UTF-8 review-file export and parsing, XML/schema/Python syntax, and whitespace checks.

These initial checks establish implementation behavior, not Korean model accuracy.
The later paid comparisons are recorded above. See the
[operating guide](../../hop/llm/README.md) for current parameters and review steps.
