# Korean posting enrichment and NCS categorization

For the resumed source → document → duty → NCS workflow, start with the
[current practical linking guide](../../docs/hop-migration/linked-ingestion.md).
It describes the parser service, exact live inputs, incremental model runs, batch
review files and `llm/publish_links.hwf`. Earlier ontology/hold sections below are
historical or later work, not extra prerequisites for this ingestion deliverable.

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](../../docs/hop-migration/linked-ingestion.md) for what is actually tested/deployed.

**Attachment-aware processing is on hold by user as of 2026-09-13 KST.** The
compact-input paid pilot was not launched. Do not resume attachment-based
extraction/categorization or rebuild its inputs without explicit user resumption.
See the [pause status and handoff](../../docs/hop-migration/attachment-status.md).

These native Hop workflows read accepted JOB-ALIO or 나라일터 and NCS snapshots from PostgreSQL,
extract explicitly supported facts, and propose NCS alignments for explicit duties.
Models and processing limits are workflow parameters. Start with a small evaluation.
All entry points use **llm-local** and **Basic** logging. For production enrichment,
set `JOB_SOURCE_ID=job_alio` (default) or `JOB_SOURCE_ID=nara_job` and pin
`JOB_RUN_ID` to a READY snapshot of that source. Evaluation datasets remain
JOB-ALIO-based so historical comparisons do not change.

The default prompt/schema is **`ko-v3`**. It uses source passage IDs, explicit
condition kinds, shared position references and nested condition expressions.
`ko-v1` and `ko-v2` remain installed for historical replay: the
[first paid DeepSeek test](../../docs/hop-migration/llm-deepseek-evaluation-2026-09-12.md)
found both validator limitations and semantic errors among mechanically valid items.
**Keep `ACCEPTANCE_POLICY=REVIEW`.** Mechanical validation is not semantic approval.
Calls remain off by default. See the
[deployment verification](../../docs/hop-migration/llm-status.md) for installation history.
The [DeepSeek/Luna comparison](../../docs/hop-migration/llm-model-comparison-2026-09-12.md)
records the fixes, frozen test inputs, model settings and paid results.

## Attachment-aware input

The [attachment input guide](../attachments/README.md#prepare-versioned-llm-inputs)
explains `attachments/prepare_inputs.hwf`. Its immutable bundles can populate a new
EVAL dataset or be selected explicitly with `INPUT_BUNDLE_IDS` for ENRICH. Use the
same job snapshot, `ko-v6` or `ko-v7`, `REVIEW`, and an initial dry run. Attachment text and
outcomes participate in source hashes and evidence validation; original inline
batches and independent reviews remain unchanged. Accepted-revision categorization
can use the same bundle IDs without re-extracting the documents. For canonical
publication, use [ontology input binding and reviewed assembly](../ontology/README.md).
That path retains the selected document/page/table-cell provenance separately from
the legacy whole-item publisher.

## Long documents and ko-v7

`ko-v7` is an explicit version for the attachment-aware quality work; it does not
change the default or any historical prompt/output. Check the
[deployment and live quality status](../../docs/hop-migration/llm-status.md) before
expanding a paid batch. It requires `ACCEPTANCE_POLICY=REVIEW`.

The provider schema now enforces the condition shape: single/unspecified logic
requires null, AND/OR requires the matching root, and conditional logic requires
an ordered if-then/exception pair. Korean polarity, shared qualifiers, exact
fragments and positional scope still require validation and independent review.
Split PDF words must retain separate source fragments; the prompt cannot rewrite
the archived text to make a quotation fit.

`unhandled_ranges` replaces hundreds of repeated line-disposition objects. Each
entry supplies inclusive `first_id`/`last_id` endpoints within one narrative field,
a disposition, context kind, reason and optional duplicate reference. Hop expands
the range into an explicit per-passage `source_coverage` record. Missing endpoints,
cross-field or overlapping ranges, cited/uncited conflicts and omitted passages
are rejected. Blank physical lines are skipped; original line IDs are retained.

`document_context` identifies employment terms, application forms, institution
background, generic occupational reference material, document structure or privacy
notices. It preserves these passages as context rather than asserting them as
mandatory applicant conditions. Recognizable context and explicit-restriction
guards catch common misclassifications; they do not prove semantic accuracy.
Unresolved clauses remain review failures. A broad range must not conceal required
credentials, age limits, bonus rates, exceptions or position-specific conditions.

The original provider JSON, compact ranges, expanded coverage, source input and
hashes remain available for review. Extraction and accepted-revision categorization
use the same input bundles and ordinary request/spend controls.

New v7 extraction requests use the **`source-bound-ranges-v1` request policy**.
The builder derives a response schema from the exact input: citations can name
only existing nonempty passage IDs; range endpoints must belong to one narrative
field; and disposition/context/duplicate fields have correlated shapes. Explicit
`narrative_fields` and `metadata_fields` lists clarify which passages need coverage.
Original line numbering, blank-line gaps and source text are preserved. Historical
prompt schemas and saved requests remain unchanged; the generated request and its
policy participate in cache identity. The response validator independently checks
the saved request's pattern constraints before semantic checks or hydration.

The finite ID patterns avoid a long-document enumeration exceeding the provider's
enum limit. The builder uses supported pattern, reference and union constructs;
see [OpenAI's structured-output constraints](https://developers.openai.com/api/docs/guides/structured-outputs).
Ordering, overlap, duplicate identity, quoted text, role scope and condition meaning
still need downstream checks. This policy cannot establish semantic acceptance.
The full serialized request is still subject to `MAX_INPUT_CHARS`; inspect a dry
run before paying for an expanded batch.

New `ko-link-v1` requests use the **`link-bound-v1` request policy**. Extraction
citations are limited to actual nonempty passage IDs from one source field per
position or duty; duty citations also exclude fields that cannot supply duty
evidence. Categorization is constrained to the exact NCS shortlist codes, actual
duty-index range and batch `MAX_MATCHES` cap. The policy is generated for each
posting by `sql/025_link_bound_requests.sql`, included in the saved request and
cache key, and does not rewrite historical prompt rows or attempts. Install it on
an existing server with `install_link_bound.hwf`; the general `install.hwf` includes
it for fresh installations.

The provider-side extraction schema uses field-specific patterns and `anyOf`.
PostgreSQL checks the base extraction JSON shape and then independently checks
every citation ID, field owner, exact source fragment and role association using
`output_issues_link_v1`. This avoids repeatedly running large provider regexes
over attached-document citations. For categorization, PostgreSQL checks the
generated enum, duty range and match cap directly from the schema saved in the
attempt, then applies the existing shortlist and consistency checks. Neither schema
can prove that a proposed NCS unit truly matches a Korean duty; reviewed links
are still required before graph publication.

For new `link-bound-v1` categorization responses, **only identical match objects**
are deduplicated after validating the provider's output against its saved request
schema. The original provider JSON remains in `attempt.raw_output`; the parsed
result keeps the first occurrence and `attempt.normalization` records the policy
and removed count. Repeated `(competency_code,duty_index)` pairs with different
reasons still fail the pair-level validator. This normalization does not accept a
match or replace independent NCS review.

`enrichment.suggest_rendered_fragment_revision_v1(raw_output,source_data)` is a
manual correction helper for an extraction rejected **only** for unsupported duty
fragments. It splits one model phrase across adjacent literal Markdown `<br>`
separators when the model joined them with spaces or blank lines, only when both
resulting phrases are exact source substrings and the
entire revised extraction passes the source validator. It returns `NULL` for
unrelated intervening text, ambiguity or any other issue. Import a nonnull result
through `import_correction.hwf` as an append-only, pending revision; do not treat
it as a reviewed extraction or reuse the old categorization's duty indices.

For rejected `ko-link-v1` extractions that cannot be corrected literally, run
`enrich.hwf` with the old terminal `REPAIR_BATCH_ID`, exact `POSTING_IDS` and
`INPUT_BUNDLE_IDS`, `ACCEPTANCE_POLICY=REVIEW`, and a bounded request/cost budget.
The new extraction request includes the prior raw output and validator issues as
untrusted diagnostics, plus an instruction to use exact source substrings and
split wording at rendered Markdown `<br>` separators. Planning skips an item
with a pending or accepted extraction revision; reservation checks again before
sending, so an intervening revision blocks the request as `NOT_SENT`. Keep the
original source run pinned. A successful retry creates a new attempt and still
requires independent extraction and NCS-link review.

New v7 requests also use **`field-lines-and-tables-v1` input encoding**. Source
passages are grouped by field as `[original_line_number, exact_text]` rows, avoiding
repeated field names and passage-object keys. Citations still use `field:line`.
Every nonempty line and its original numbering remain present; this is not a
summary or truncation. Frozen input hashes and evidence offsets are unchanged.

For verified HWPX inputs, `hwpx-rows-v1` places cell blocks under their logical
table rows so labels and scores can be read together. It preserves section-local
block/paragraph identities, captions, empty cells, merged-cell spans and nested
table ownership. Nearby body-block references expose headings and footnotes;
proximity alone does not establish a condition's applicability. PDF/body section
boundaries and all missing-document outcomes remain explicit. Categorization
receives the same grouped passages under `source_context`.

The input encoding, generated response schema and system prompt are all saved
in each request and participate in cache identity. Historical v7 requests and
v1–v6 request construction are preserved. Encoding verification does not prove
that the model interpreted a table or condition correctly.

[Attachment review checkpoints](evaluation/attachment-review-checkpoints-v1.json)
record seven partial assistant source reviews, including professor-specific
research rules and table-based bonus scores. They are not human gold or an
automatic acceptance policy, and must not be added to model inputs. The native
suite exercises the request builder and malformed-response/correction paths.
For an independent full-input grammar check, export protected frozen bundle rows
(`posting_id`, `bundle_id`, `source_data`, `source_hash`) and run against an installed
disposable fixture:

```sh
uv run --no-project --with jsonschema python hop/llm/tests/source_bound_real.py \
  --inputs /protected/path/input-bundles.json
```

This check verifies source hashes, original text/offsets, every permitted passage
ID, JSON Schema validity and schema enum/property counts. It performs no inference
and makes no production writes; it does not replace a native request dry run or
semantic evaluation.

To independently decode all compact packets, also export the earlier native dry
requests as `posting_id`, `source_hash`, `request`, `old_chars`, then run:

```sh
python hop/llm/tests/document_packet_real.py \
  --inputs /protected/path/input-bundles.json \
  --requests /protected/path/previous-dry-requests.json \
  --output-dir /protected/path/packet-verification
```

This checks every original passage, document outcome, HWPX block/table/cell,
merged span and parent relationship. Complete request sizes reconstructed from
the saved request envelopes are estimates until a fresh native dry run confirms
them. The command uses only the disposable local PostgreSQL fixture.

## Start here in Hop Web

1. Open **`${PROJECT_HOME}/llm/install.hwf`** and run it once. It installs the additive
   `enrichment` schema through SQL workflow actions. Repeat installation preserves data.
   The existing `ingestion` bootstrap and private `jobtology-postgres` metadata must exist.
   On a new installation, also run `retention/install.hwf` with `retention-local`
   before graph publication. It installs the shared writer guard without making
   model requests. This is already installed on Goldship.
2. Open **`llm/prepare_evaluation.hwf`**. Leave `DATASET_ID=korean-jd-v1`,
   `DATASET_SIZE=20`, `SAMPLE_SEED=ko-v1`, and both source run IDs at `LATEST`.
   This freezes real postings and the NCS snapshot. It makes **no model requests**.
3. Open **`llm/evaluate.hwf`**. Leave the same `DATASET_ID` and
   **`EXECUTE_REQUESTS=N`**. Run it and copy the logged `batch_id`.
   This plans extraction requests without reading the API key. Categorization is planned
   only after extraction exists, so a first dry run cannot preview that second prompt yet.
4. When the OpenRouter account has credit, set **`EXECUTE_REQUESTS=Y`** and run the
   evaluation with your chosen model settings. This makes paid API requests.
   The default is at most 20 postings / 40 requests, with sequential calls.
5. Open **`llm/inspect_results.hpl`**, set **`BATCH_ID`** to the logged ID, and
   **preview the `Preview results here` transform**. It shows source text, extracted
   requirements/duties, NCS candidates, proposed matches, and validation issues.
   A normal run does not automatically open a table viewer.

The protected key file is **`${HOP_CONFIG_FOLDER}/secrets/openrouter.csv`**, currently
`/usr/local/tomcat/webapps/ROOT/config/secrets/openrouter.csv` inside the Hop container.
It contains the `api_key` header and exactly one nonempty key row. Keep it owned by
Hop, mode `0600`, in the mounted config directory. The workflow reads it only when
executing a request; the key is never stored in PostgreSQL, prompt files or Git.
Do not preview the request pipeline or enable Detailed/Rowlevel logging on it.

## Workflow parameters

| Parameter | Default | Use |
|---|---|---|
| `EXTRACT_MODEL` | `google/gemini-3.8-flash` | OpenRouter ID for extraction. |
| `CATEGORIZE_MODEL` | `google/gemini-3.8-flash` | Model for duty-to-NCS matching; can differ from extraction. |
| `PROVIDER_ONLY` | blank | Optional OpenRouter provider slug, e.g. `deepinfra` or `fireworks`. Applies to both stages. Blank lets OpenRouter choose a compatible provider. |
| `TEMPERATURE` | blank | Omit by default; optionally supply `0`–`2` when the model supports it. |
| `REASONING_EFFORT` | blank | Omit by default; supported values include `none`, `low`, `medium`, `high`. Model support varies. |
| `MAX_OUTPUT_TOKENS` | `6000` | Per-request output limit, including reasoning. Truncated output is rejected. |
| `EXTRA_PARAMS_JSON` | `{}` | Numeric `top_p`, `seed`, `frequency_penalty`, `presence_penalty`. Example: `{"seed":42}`. |
| `PROMPT_VERSION` | `ko-v3` | Installed immutable prompt/schema version; older versions preserve historical replay. |
| `POSTING_LIMIT` | `20` | How many postings to include. Raise explicitly, e.g. `10000`, for all currently available jobs. |
| `CANDIDATE_LIMIT` | `40` | Maximum NCS shortlist size, up to 100. |
| `MAX_MATCHES` | `8` | Maximum supported `(competency, duty)` pairs per posting. |
| `MAX_INPUT_CHARS` | `60000` | Complete serialized request limit. Oversized requests are rejected, not silently shortened. This is not a token limit. |
| `MAX_REQUESTS` | `40` | Per-batch logical request reservations, including unknown transport outcomes. See the HTTP-client limitation below. |
| `REQUEST_RESERVE_USD` | `0.10` | Conservative accounting reservation per request. Adjust for your model and context limits. |
| `MAX_COST_USD` | `5` | Per-batch accounting cap. |
| `DAILY_BUDGET_USD` | `20` | Rolling 24-hour accounting cap shared by these workflows. |
| `EXECUTE_REQUESTS` | `N` | `N` plans only; `Y` makes model requests. |
| `REUSE_CACHE` | `N` for evaluation, `Y` for enrichment | Reuse an identical validated stage result. Disable when comparing repeated model generations. |
| `ACCEPTANCE_POLICY` | `REVIEW` | `REVIEW` uses named reviews. `VALIDATED` automatically accepts ENRICH items passing checks, for batch operation after evaluation. EVAL is always isolated. |
| `DATASET_ID` | `korean-jd-v1` | Frozen sample for evaluation. |
| `JOB_RUN_ID`, `NCS_RUN_ID` | `LATEST` | Source snapshots for enrichment; evaluation uses its frozen dataset's snapshots instead. |
| `ENDPOINT` | `https://openrouter.ai/api/v1/chat/completions` | HTTPS endpoint. |
| `REQUEST_DELAY_MS`, `READ_TIMEOUT_MS` | `250`, `180000` | Request spacing and finite read timeout. |

The September 15 OpenAI BYOK allocation is 500 RPM and 500,000 TPM. Hop's
`REQUEST_DELAY_MS` is a per-worker pause, not a shared token-rate limiter;
`MAX_REQUESTS` and `MAX_INPUT_CHARS` do not enforce RPM or TPM either. With
one worker, the full rejection-set replay used 1,000 ms for regular requests,
3,000 ms for a group of wider documents, and one-item Hop batches with
60,000 ms before each call for two postings whose extraction and NCS prompts
each used about 300,000 tokens. See
[`docs/hop-migration/linked-ingestion.md`](../../docs/hop-migration/linked-ingestion.md)
for the measured outcomes and the safe chunk-5 runner. Use reported prompt
and completion tokens plus HTTP 429s when changing worker count or spacing.

The spend controls reserve before sending. Completed requests settle at their nonnegative
provider-reported cost. For OpenRouter-funded requests this is `usage.cost`. For BYOK
requests OpenRouter reports its own cost as zero, so Hop instead records
`usage.cost_details.upstream_inference_cost`, the charge made by the upstream provider.
If the applicable cost field is missing or malformed, the charge stays unknown and the
reservation is retained. Unfinished or unknown charges retain their reservations. Original
reservation values and request audit rows are preserved. They stop subsequent
requests; they cannot guarantee the price of an in-flight request. Configure a dedicated
OpenRouter key's spending limit for a provider-enforced ceiling. Model changes require
reconsidering the reservation. Missing provider usage/cost is shown as unknown, never $0.

The model must support JSON Schema structured output and the options you select.
Provider parameter support is required and provider fallbacks are disabled. Unsupported
options produce a retained error rather than silently weakening the output contract.
Provider selection is saved in batch settings and request JSON, and participates in the
output cache key. Use the lowercase slug from OpenRouter's provider/endpoint listing;
the selected provider must support both chosen models and their parameters.
The default model is a starting configuration, **not a Korean-quality benchmark winner**.

## Evidence and conditions in ko-v3

- The model receives original source lines with stable passage IDs. It returns
  those IDs; PostgreSQL recovers the exact quotation and all intervening lines.
  `text_parts` contains literal source fragments; the pipeline joins them to produce
  display text. Expression atoms similarly use `parts`. This supports shared
  wording (e.g. each specialty plus `전문의 자격 소지자`) and conditions around an
  intervening exception without asking the model to fabricate a contiguous quote.
  Each fragment is independently checked against the original cited text. Unknown
  IDs, mixed source fields and invented fragments are rejected. Snapshots are unchanged.
- Conditions distinguish `eligibility`, `preference`, `exclusion`, and `unrestricted`.
  Their derived `importance` values are respectively `required`, `preferred`,
  `excluded`, and `unrestricted`. Positive absence-of-disqualification wording is
  eligibility, even when a provider puts it in `disqualification_text`.
- A shared requirement references several `position_ids`; hydration adds
  `position_names`. The compatibility `position` field is null for shared/common
  conditions, so consumers must use the full position array in v2/v3.
- Compound requirements carry an expression tree stored as indexed nodes.
  `all_of`/`any_of` can nest; `if_then` and `except` preserve conditional requirements
  and exemptions. Invalid references, cycles, orphan nodes and unsupported atoms
  are rejected. Comma-list alternatives no longer need a literal OR keyword.
- The supplied education field must be represented. Existing metadata is also
  copied under `source_metadata`. This catches the observed education omission;
  it does **not** prove every qualification, exception or preference was captured.
- NCS retrieval uses Korean word fragments, document-frequency weighting and
  balanced per-duty ranks. Candidates still require lexical evidence, and the
  model still may choose only the supplied codes. Better retrieval is not proof
  that a proposed match is correct.

`enrichment.attempt.raw_output` retains the provider object. For validated
v2/v3 extraction, `parsed_output` adds recovered quotations, composed text, position names, explicit
importance and the schema version. `response_body` retains the original envelope.
Rejected responses are kept without claiming their evidence has been validated.
`inspect_results.hpl` exposes the rejected item's issues but leaves its validated
extraction column empty. Read `enrichment.attempt.raw_output` (or `response_body`)
when examining the rejected model response; the comparison report includes a query.
Cache keys distinguish prompt, validator and retrieval versions; old results are
not rewritten or reused across prompt versions. The intermediate `ko-v2` required
every atom to be contiguous; its saved runs exposed valid shared-suffix expansions
being rejected. `ko-v3` makes those compositions explicit as independently supported
fragments. It does not prove the model combined the fragments with the right meaning;
semantic review and the original quotations still matter.

For the reproducible 22-posting comparison, run `prepare_regression_v2.hwf` once,
then evaluate `DATASET_ID=korean-regression-v2-22`. The
[comparison assertions](evaluation/README.md) are provisional assistant-authored
checks, not human gold. Review all positive NCS matches separately. For long
postings with many condition trees, allow more output tokens; the comparison uses
16,000. Luna does not advertise temperature support: leave that parameter blank.

HTTP **401/402/403/429** ends further model calls in that batch. Remaining attempts are
marked `ERROR` with `NOT_SENT_AFTER_PROVIDER_ERROR`; they have no HTTP status,
reservation or charge. Fix the key/credit/provider problem or wait for the quota to
recover, then start a new evaluation. Old batches and responses remain unchanged.

**Hop 2.19 transport limitation, verified 2026-09-12:** the REST transform has
`retryTimes=0`, but its underlying Apache HttpClient5 still repeats HTTP 429 once.
The native fixture observed two HTTP POSTs with the same attempt ID before the final
429 reached PostgreSQL; subsequent postings were correctly skipped. The HTTP-client
factory does not expose a retry-disable option through REST metadata. Consequently,
`MAX_REQUESTS` and the report's `requests` count logical attempts, not a guaranteed
number of wire requests. The per-response cost belongs to the final returned response;
check OpenRouter usage for billing reconciliation. No custom Hop JAR was installed.

**Hop 2.19 multiple-input Abort workaround, verified 2026-09-14:** do not feed the
`Check child errors` and `Check child result` filters into one shared Abort transform.
While a child request is pending, that topology makes Abort spin in multiple-input
rowset polling and consumes one CPU core. `run_extract.hpl`, `run_categorize.hpl`
and their worker variants give each failure branch a separate single-input Abort.
A delayed native mock measured the intentionally restored legacy topology at
3.140 CPU-seconds over 3.164 elapsed seconds in the final full-suite run; the fixed
topology used 0.100 CPU-seconds over 3.184 seconds. An earlier focused run measured
3.220/3.165 and 0.090/3.191 respectively. Native fixtures also drive each failure
branch and require the corresponding Abort message. The four fixed runners were
deployed to Goldship after the paid batch became terminal, under receipt
`~/.local/state/jobtology-hop/linked-ingestion-deploy-20260914T140804Z/`; their
deployed bytes and one-input topology were rechecked. Regenerate these files from
`tools/build.py`, followed by `tools/incremental_workflows.py`; do not merge the
Abort transforms in Hop Gui.
Do not interpret the accounting caps as provider-enforced spending ceilings.

## Compare models and measure quality

Run `evaluate.hwf` repeatedly with the **same dataset**, changing the model/settings
and keeping `REUSE_CACHE=N`. Each run receives a new batch ID. For example, compare
the default against `openai/gpt-5.6-luna` or `qwen/qwen3.8-flash` after checking their
current availability/options. Set both model parameters to the candidate for a complete
system comparison, or change only one to isolate that stage.

Open **`llm/inspect_comparison.hpl`**, choose the dataset, and preview
**`Preview comparison here`**. PostgreSQL exposes the same reports:

```sql
SELECT * FROM enrichment.batch_report
WHERE dataset_id = 'korean-jd-v1' ORDER BY created_at;

SELECT * FROM enrichment.case_score WHERE batch_id = '<batch-id>';
SELECT * FROM enrichment.result WHERE batch_id = '<batch-id>' ORDER BY ordinal;
```

`COMPLETE` means each item passed format/evidence checks or legitimately abstained.
It does **not** prove extraction completeness or semantic correctness. Unlabelled runs
report validation, usage, cost and errors; accuracy metrics remain empty.

The initial sample mixes alternatives, multiple-position conditions, attachment
references, unrestricted eligibility, and general postings. Sampling is deterministic
within those heuristics. It is a useful pilot, not a representative benchmark of every
occupation. Increase the dataset to 100–200 reviewed cases for a model decision. Use a
new dataset ID when changing its size, seed or source snapshots. Reusing an ID keeps the
original frozen data, including when the source APIs refresh.

### Add gold labels

Read the frozen text independently and label explicit duties, requirement logic and
NCS codes. Do not use a model's own confidence as a quality score. Review especially
필수/우대, AND/OR alternatives, 경력무관, multiple positions, and missing attachment text.

Run **`llm/export_review_file.hwf`** with the dataset ID to create
**`${PROJECT_HOME}/data/llm/korean-jd-v1-review.json`**. It includes the frozen source
text and label placeholders, or the most recent labels if you are revising them.
Existing files are never overwritten; choose another `REVIEW_FILE` for a new export.
Edit that JSON in the mounted project and use its path as `GOLD_FILE` when importing.
You can also generate a fresh template through the SQL editor:

```sql
SELECT jsonb_pretty(jsonb_build_object(
 'dataset_id','korean-jd-v1', 'reviewer','',
 'cases',jsonb_agg(jsonb_build_object(
  'posting_id',posting_id,'source_data',source_data,
  'labels',jsonb_build_object('requirements','[]'::jsonb,'duties','[]'::jsonb,
   'ncs_codes','[]'::jsonb,'requirements_complete',false,'duties_complete',false,
   'ncs_complete',false)) ORDER BY ordinal)))
FROM enrichment.test_case WHERE dataset_id='korean-jd-v1';
```

Fill `reviewer` and the labels. Remove cases you have not labelled before importing.
`source_data` is included for reading; import never overwrites source data with that field.
Example label structure (substitute quotes/codes from the selected real case):

```json
{
  "requirements": [{
    "field": "eligibility_text",
    "quote": "SQL 자격증 또는 데이터 자격증 중 하나",
    "category": "qualification",
    "importance": "required",
    "logic": "any_of"
  }],
  "duties": [{"field": "eligibility_text", "quote": "데이터베이스 설계 및 구축"}],
  "ncs_codes": ["2001020101_24v1"],
  "requirements_complete": false,
  "duties_complete": true,
  "ncs_complete": true
}
```

This example is synthetic; its code is not a suggested label for a real posting.
Requirement categories are `education`, `experience`, `qualification`, `skill`, `other`;
importance is `required`, `preferred`, `unspecified`, `excluded`, `unrestricted`;
logic is `single`, `all_of`, `any_of`, `unspecified`, `conditional`. For v2/v3
references, optionally add `kind` (`eligibility`, `preference`, `exclusion`,
`unrestricted`) and `position_names` to check the complete associated position set.
The legacy `position` checks one named position. `check_logic=false` checks a fact
without requiring one particular tree/flat representation; omit it to check logic.
Quotes must be exact substrings of the frozen field. NCS codes must exist in the
dataset's pinned catalog.

Run **`llm/import_gold.hwf`** with `GOLD_FILE` pointing at the edited document, then
start **new evaluations**. Each batch pins the latest gold revision at startup; later
label edits cannot silently change an old score. Labels never enter model messages.

Set a `*_complete` flag to true only when you have exhaustively labelled that section.
Partial labels support recall checks; precision uses only completely labelled sections.
An empty `ncs_codes` with `ncs_complete=true` is a reviewed abstention case. An entirely
empty document with all completeness flags false is not a labelled test case.

Reports distinguish requirement/duty precision and recall, NCS precision and recall,
shortlist retrieval recall, and correct abstentions. Quote matching allows a gold quote
inside a longer model evidence quote, while requiring the same field and requirement
category/importance/logic. These automated scores aid review; they do not prove that a
model captured every nuance. Missing/invalid outputs count as failures, not abstentions.

## Enrich and load the graph

After choosing settings, open **`llm/enrich.hwf`**. Set `EXECUTE_REQUESTS=Y`, the model
parameters, posting limit and budgets. It reads the current accepted postings and pins
the current NCS catalog. It stores candidate results in `enrichment`; it does not change
the provider's `ingestion.record.normalized` values.

With the default `ACCEPTANCE_POLICY=REVIEW`:

1. Inspect results and copy an `item_id`.
2. Run **`llm/review_item.hwf`** with that ID, `DECISION=ACCEPT`, and your reviewer name.
   Only validated **ENRICH** items can be accepted; EVAL items cannot be published.
3. Run **`llm/publish_reviewed.hwf`** with the exact enrichment **`BATCH_ID`**.
   It uses the existing `jobtology-neo4j` connection and already-loaded posting/NCS nodes.
   All reviewed items in that batch are synchronized. Run one publisher at a time.

For batch operation after quality evaluation, set **`ACCEPTANCE_POLICY=VALIDATED`**
at enrichment startup. Valid items are automatically accepted, with the decision explicitly
attributed to `policy:validated-v1`; this is not recorded as a human review. Then run
`publish_reviewed.hwf` for that batch. Invalid items stay excluded. Either policy preserves
the ability to record a later rejection. Evaluation batches cannot be accepted by either policy.

```text
(jobPosting)-[:HAS_ENRICHMENT]->(jobEnrichment)
    -[:ALIGNS_WITH_NCS {duty, evidence_field, evidence_quote, reason}]->(ncsCompetency)
```

The intermediate node records source hashes/snapshots, extraction, model/prompt metadata,
and review state. Its `name` is the real posting title. Alignments are explicitly
`origin=LLM_INFERENCE`; they do not claim an official requirement or proficiency level.
Use `name` as the Neo4j Browser caption for `jobEnrichment`, or import
[`browser-style.grass`](browser-style.grass) with `:style` after saving your existing style.

```cypher
MATCH (p:jobPosting)-[:HAS_ENRICHMENT]->(e:jobEnrichment {state:'READY',decision:'ACCEPT'})
      -[r:ALIGNS_WITH_NCS {accepted:true}]->(c:ncsCompetency)
RETURN p.title,e.name,r.duty,r.evidence_quote,c.name,r.reason
LIMIT 30;
```

This query includes accepted history. Select a specific batch for historical analysis;
use **`enrichment.current_posting`** in PostgreSQL to select accepted results matching
the current posting content and NCS snapshot. New source snapshots do not make an old
enrichment current automatically. Source fields remain separate from derived values.

A repeated graph publication merges the same nodes and relationships and verifies
their properties/counts. It makes no model calls. To revoke acceptance, record `REJECT`
and rerun publication for the batch. The PostgreSQL current view excludes the item
immediately; Neo4j excludes it after synchronization, retaining its historical alignment
with `accepted=false`. A failed graph load leaves affected items outside `READY` and
can be replayed from PostgreSQL.

## Refresh, recovery and observability

The existing 15-minute source scheduler **does not call these LLM workflows**. They
are manual while models are being evaluated; no paid schedule is enabled by installation.
After a source refresh, rerun enrichment with `REUSE_CACHE=Y`. Identical source content,
prompt version, schema, model/options and relevant NCS content reuse stage results.
Extraction and categorization cache independently; EVAL and ENRICH caches are separated.
A changed daily snapshot ID alone does not force a paid re-extraction.

Every attempt stores its exact request JSON (without credentials), decoded response
text, parsed output, validation issues, requested/actual model, provider, usage and
reported cost. Each result retains the frozen source object and source snapshot IDs.
The workflow does not retry an attempt; Hop 2.19's underlying HTTP-client retry
limitation is described above. A new run can reuse completed valid stages; failed
or uncertain requests remain in the ledger. Budget-blocked and failed items appear in
a `PARTIAL` report while other cases continue. Retrying a partial run is an intentional
new invocation and may pay for its previously failed requests again.

```sql
SELECT a.attempt_id,a.stage,a.state,a.http_status,a.issues,a.cost_usd
FROM enrichment.attempt a WHERE a.batch_id='<batch-id>' ORDER BY a.created_at;
SELECT * FROM enrichment.graph_export WHERE item_id='<item-id>';
```

Requests include OpenRouter Broadcast `session_id` and `trace` metadata: batch/item,
posting, dataset, source hashes/snapshot IDs and prompt version. Configure the Langfuse
destination under OpenRouter **Settings → Observability**, with a filter for this API
key. No Langfuse SDK is required in Hop. The destination must be reachable from
OpenRouter; a Tailscale-only address is insufficient for direct Broadcast.

Broadcast observes model calls. PostgreSQL retains subsequent validation, review and
graph publication outcomes; those are not automatically sent as Langfuse scores.
No Langfuse destination is provisioned by this implementation.

These are **synchronous chat calls processed as a Hop batch of rows**. They do not use
OpenRouter's separate asynchronous Batch API, so its batch discount does not apply.
Prompt/response and enrichment history currently have no automatic retention policy.

## Scope and implementation

The workflow uses native REST Client, Database Join/Execute SQL, CSV Input, Group By,
Concat Fields, Pipeline Executor and Neo4j Cypher transforms/actions. PostgreSQL
functions perform deterministic planning and validation. No Python/JavaScript transform
or custom runtime plugin is required. `tools/build.py` only regenerates checked-in
artifacts during development; `tests/` runs disposable synthetic integration tests.

Hop 2.19's Language Model Chat transform does not expose the full OpenRouter JSON
Schema/request metadata controls used here. Native REST Client provides them.
The prompt/schema files are in `prompts/`; installation freezes their contents under
`ko-v1`. Add a new version for prompt/schema changes; do not silently replace a version
already used by saved requests.

Inputs include normalized JOB-ALIO fields and explicitly selected document bundles
from the [attachment workflows](../attachments/README.md). OCR, additional external
text connectors, embeddings and semantic retrieval remain separate work. Unsupported
or unavailable document contents stay explicit missing-evidence outcomes.
The first retriever uses Korean substrings
and tokens over NCS names, occupations and definitions, with a small broad-category hint.
It does not search the full catalog with the LLM. Retrieval recall must be evaluated;
an absent correct candidate cannot be recovered by the categorizer.

References: [Hop REST Client](https://hop.apache.org/manual/latest/pipeline/transforms/rest.html),
[OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
[Broadcast to Langfuse](https://openrouter.ai/docs/guides/features/broadcast/langfuse).

## Source retention dependencies

[Manual source retention](../retention/README.md) protects snapshots referenced by LLM batches, evaluation datasets and the pinned NCS catalog. It does not delete enrichment history or cached attempts. `publish_reviewed.hwf` participates in the graph writer guard and requires retention SQL to be installed. Source retention may therefore select fewer old snapshots than requested.

## Ontology completion work

See [the active implementation and verification ledger](../../docs/hop-migration/ontology-completion.md)
for full-corpus transformation, independent link review, attachments and canonical serving releases.
The additive ko-v4 contract requires `ACCEPTANCE_POLICY=REVIEW`; the default remains ko-v3 while
its live evaluation is pending. Successful structural validation does not prove NCS link semantics.

### Independent reviews and corrections

The new `010_independent_review.sql` installer adds a separate review path. It does not convert
existing whole-item decisions or publish graph changes. The ontology publisher will consume
these independent decisions; `publish_reviewed.hwf` continues to use the earlier whole-item path.

1. Use `capture_extraction.hwf` with `ITEM_ID`, `ACTOR`, and `REASON` to append a validated
   extraction revision. Copy the returned `revision_id`. An extraction can be captured even
   when categorization failed. EVAL items cannot enter this production review path.
2. Review the original source alongside the extraction. Run `review_extraction.hwf` with
   `REVISION_ID`, `DECISION`, `REVIEWER`, `REVIEWER_KIND`, and required `NOTES`.
   Automation must use `assistant` or `policy` as its kind; it must not call itself human.
3. Run `import_model_links.hwf` with that `REVISION_ID` and `ACTOR` to import validated model
   candidates. This accepts no links. Preview `inspect_independent_reviews.hpl`, setting
   `ITEM_ID`, to compare each candidate's duty, NCS definition and occupational context.
4. Run `review_link.hwf` for each `CANDIDATE_ID`, with the same decision/provenance parameters.
   A rejected link leaves accepted extraction intact. An accepted link is exposed only while
   its extraction is accepted and its NCS snapshot is current.

Use `import_correction.hwf` with `CORRECTION_FILE` for a UTF-8 JSON object containing
`item_id`, `parent_revision_id`, `actor`, `reason`, and `output`. The output must conform to
that item's pinned raw prompt schema and pass source validation. For a first revision of a
rejected model output, set the parent to null; otherwise use the latest revision ID. The
workflow appends a new revision and never edits the original attempt or earlier reviews.
Its evidence must still refer to the same immutable input. Changed source text requires a new
ENRICH item. Repeating identical capture/correction input returns the same revision.

A new correction needs its own acceptance and suppresses older revisions from current
serving. Changing duties invalidates the old categorization's duty indices; re-categorize or
propose freshly reviewed links rather than importing the old indices. Old revisions remain
available for pinned historical releases. Review decisions are append-only, including
revocation: append REJECT instead of deleting history.

`enrichment.current_reviewed_posting` has one row per current source posting. Its `extraction`
is null unless the newest content-matching revision is accepted; `reviewed_ncs_links` contains
only independently accepted links to the current NCS snapshot. A new NCS snapshot removes
stale current links without discarding the posting's content-matching extraction. The older
`enrichment.current_posting` view still reflects whole-item reviews and is not the new path.

### Versioned audit and targeted repair (ko-v5)

Implementation/deployment status is recorded in the [completion ledger](../../docs/hop-migration/ontology-completion.md).
The workflow default remains ko-v3; select ko-v5 explicitly after its installation is verified.
Old prompts, provider responses, validation outcomes and charges remain unchanged.

1. Wait for the original batch to reach COMPLETE, PARTIAL or FAILED. Run
   `audit_batch.hwf` with its exact `BATCH_ID` and `VALIDATOR_VERSION=ko-v5`.
   This rechecks compatible saved v4/v5 extraction responses locally in PostgreSQL;
   it makes no model calls and records no acceptance. RESERVED attempts are skipped
   because their provider outcome remains unknown. Missing output is recorded explicitly.
2. Preview `inspect_audit.hpl` with the same parameters. A clean audit is a candidate
   for semantic review, not proof that every condition or duty was interpreted correctly.
3. Run `capture_audited.hwf` with `BATCH_ID`, `ACTOR` and a meaningful `REASON` to
   prepare clean audited outputs without an existing extraction revision. The appended
   revision records both the original provider prompt and the newer validation policy.
   Existing revisions/corrections are preserved. Repeat capture creates no duplicates.
4. For outputs still needing repair, run `enrich.hwf` with `PROMPT_VERSION=ko-v5`,
   `ACCEPTANCE_POLICY=REVIEW`, `REPAIR_BATCH_ID=<original batch>`, and exact source
   pins. Set model/provider, request limits and budgets as for an ordinary batch.
   Start with a small selection using `POSTING_IDS=id1|id2` and an adequate
   `POSTING_LIMIT`; blank POSTING_IDS selects eligible failures up to that limit.
   Use `EXECUTE_REQUESTS=N` first to inspect the planned selection without calls.

Repair selection includes old failures and old validated outputs flagged by the new
audit. It excludes clean audited outputs and RESERVED attempts. Missing, duplicate or
ineligible explicitly selected IDs fail planning; a different JOB source pin or mixed
EVAL/ENRICH lineage also fails. Evaluation repair uses the same frozen dataset.
The new item records its original item/attempt, audit version, issue list and previous
output. The model receives these as diagnostics alongside original source passages.
Source evidence remains authoritative. The complete request, including repair context,
must fit MAX_INPUT_CHARS; oversized inputs are rejected without truncation or a call.

ko-v5 replaces broad field-name polarity and lexical AND checks with scoped checks,
and requires shared parent-list evidence and conditions. These are targeted regression
guards, not a general Korean semantics parser. A mixed-polarity or shared-scope flag
requires review; it does not establish that the model lacks general language ability.
Independent extraction/link decisions are still required before ontology assembly.
Free revalidation does not retroactively execute categorization skipped by the old batch;
reviewed-revision categorization is a separate remaining integration task.

### Nested conditions and source accounting (ko-v6)

Select `PROMPT_VERSION=ko-v6` explicitly; REVIEW remains mandatory. Check the
[completion ledger](../../docs/hop-migration/ontology-completion.md) for its live pilot
and review results before a bulk run. Existing v4/v5 audit findings and decisions remain
available. ko-v5's free audit does not accept the different ko-v6 raw JSON shape.

The provider returns nested `condition` objects. PostgreSQL assigns deterministic
preorder indices for the existing canonical expression format. Groups contain child
objects; the provider no longer supplies numeric child pointers. Limits are 60 nodes
and 12 tree levels, with oversized trees rejected rather than truncated. The raw
provider response is retained separately from the adapted/hydrated form and its hashes.
[OpenAI's structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs#recursive-schemas-are-supported)
documents recursive definitions; actual OpenRouter/provider acceptance must still be
verified by the recorded live run.

Every narrative source passage must be cited or have an explicit disposition in
`unhandled_passages`. The captured revision includes `source_coverage` for inspection.
Missing passages, ungrounded duplicate claims, unresolved source text, certain omitted
numeric qualifiers and applicability-as-exemption mistakes trigger review errors.
These checks expose omissions; they do not establish semantic completeness. Headings,
application procedures and attachment references remain distinguishable from extracted
requirements. Structured metadata is accounted for separately.

Categorization receives source passages and position names in addition to the duties
and shortlist. This supplies occupational context for review; it does not authorize
inventing new duties from titles or employers. No-match is still a valid result.

For a ko-v6 repair, `REPAIR_BATCH_ID` can select a prior extraction explicitly rejected
by independent review, even when its original validation passed. Review notes enter the
repair diagnostics. Existing pending or accepted revisions are protected. A compatible
v5 audit can identify other failures; all selected source hashes must match. Use exact
`POSTING_IDS`, an explicit model/provider, complete-input/output limits and a bounded
budget. An independently rejected NCS link alone does not justify re-extracting a
pending/accepted posting; reviewed-revision recategorization remains separate work.
## Categorizing a reviewed extraction revision

`categorize_reviewed.hwf` is the NCS-only path for corrected or newly recovered
extractions. It accepts exact `REVISION_IDS` separated by `|`, `JOB_RUN_ID`,
`NCS_RUN_ID`, and an `ACTOR`. Each revision must be the newest content-matching
ENRICH revision and have an explicit ACCEPT decision. A pending, rejected,
superseded, source-mismatched or missing revision fails before inference.

Use `llm-local`, explicit `CATEGORIZE_MODEL`/provider settings, `PROMPT_VERSION=ko-v6`
and the usual budget, output and request limits. Start with `EXECUTE_REQUESTS=N`:
this plans the exact requests without reading an API key or making HTTP calls.
`EXECUTE_REQUESTS=Y` creates a new bounded batch. No extraction model is invoked.

The request uses the reviewed revision's actual duty order/text, original source
passages and positions. It pins both the extraction decision and NCS catalog. A
revocation or newer correction blocks an unsent request; if it occurs during a
request, the response and charge are retained but cannot become imported links.

Inspect `inspect_revision_links.hpl` with the resulting `BATCH_ID`. Imported
`link_candidate` rows require independent `review_link.hwf` decisions. Repeated
suggestions append `link_support` evidence without changing an earlier rationale
or clearing a rejection. Rejected suggestions are excluded from cache reuse.
New NCS snapshots receive distinct candidate context while retaining older
decisions. Empty duties, empty retrieval and a model's unsupported-match outcome
remain distinct recorded outcomes; they are not automatically accepted mappings.

`enrichment.revision_input` binds the immutable extraction revision, accepted
decision and extraction hash. `revision_link_result` records attempt provenance
and each outcome. Original extraction attempts and costs are untouched. These
batches cannot use legacy whole-item acceptance or publish automatically.

Implementation and deployment evidence is maintained in the
[completion ledger](../../docs/hop-migration/ontology-completion.md).

For the currently selected Luna route, set `CATEGORIZE_MODEL=openai/gpt-5.6-luna`
and `PROVIDER_ONLY=openai` explicitly. Set `POSTING_LIMIT` to at least the number
of selected revisions; `MAX_REQUESTS` need only cover categorization calls. The
workflow's generic model default is not a production recommendation. Inspect
`enrichment.batch_report` for actual requests/costs; a COMPLETE batch means the
requests were processed, not that its mappings have passed semantic review.
## Explicit interpretation of conditional requirements

`import_rule_interpretation.hwf` records how a source requirement operates without
rewriting the model's extraction. Use this when a phrase such as `단` or `제외`
needs an explicit permission, requirement or bonus-exclusion interpretation.
Installation requires the current `llm/install.hwf`.

The workflow takes `INTERPRETATION_FILE`, a UTF-8 JSON file containing
`revision_id`, zero-based `requirement_index`, `parent_id`, `actor`, `reason`, and
`document`. The index refers to the **hydrated extraction revision**, which can
include deterministic education requirements; do not copy an index from raw model
JSON. For the first interpretation use `parent_id: null`. A correction must name
the latest interpretation as its parent. Identical imports are idempotent.

The document follows [guarded-rules-v1](schemas/guarded-rules-v1.json). Each rule
has a local `id`, `action`, source `statement_parts`, `evidence_ids`, a `guard`, and
`target_rule_id`. Statements and guard atoms must be verbatim source fragments
within the cited passages of that requirement. Uncited lines between two cited
passages cannot supply evidence. A guard uses `atom`, `all_of`, `any_of`, or `not`;
`null` means unconditional **within the original requirement's position scope**.

| Action | Meaning |
|---|---|
| `REQUIRE` | State a necessary condition. |
| `PERMIT` | Allow the stated action when the guard holds; other requirements still apply. |
| `FORBID` | Prohibit the stated action or condition. |
| `PREFER` | Grant the stated preference or bonus. |
| `UNRESTRICT` | State that the specified restriction does not apply. |
| `LIMIT` | Qualify the named `PREFER` rule. |
| `DISABLE` | Make the named rule inactive when this rule is active. |

Only `LIMIT` and `DISABLE` have a non-null `target_rule_id`. Targets belong to the
same interpretation; cycles are rejected. An active permission does not implicitly
disable a requirement. For two independent bonus exclusions, both exclusions
target the bonus itself.

Import creates a **pending** interpretation. Use `inspect_rule_interpretation.hpl`
with `REVISION_ID` to inspect the source and interpretation together. Review it
separately with `review_rule_interpretation.hwf`: supply `INTERPRETATION_ID`,
`DECISION=ACCEPT|REJECT`, `REVIEWER`, `REVIEWER_KIND`, and source-based `NOTES`.
An interpretation decision does not accept the extraction or any NCS link.

`preview_rule_activation.hpl` takes `INTERPRETATION_ID` and `OBSERVATIONS_JSON`.
Observations are hypothetical booleans or null, keyed by local rule ID followed
by child indices, for example `{"permission/0":true,"permission/1":false}`.
Missing observations remain unknown. This previews **which rules are active**;
it does not decide whether an applicant meets them or is eligible overall.

The ontology assembler freezes interpretation decisions with extraction and link
decisions. Only accepted interpretations of accepted extractions produce graph
rules. Pending corrections suppress the prior interpretation in a new release;
previous frozen releases keep their original selection. See the
[ontology guide](../ontology/README.md) for loading and querying them.
