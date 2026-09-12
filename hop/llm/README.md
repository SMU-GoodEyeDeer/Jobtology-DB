# Korean posting enrichment and NCS categorization

These native Hop workflows read accepted JOB-ALIO and NCS snapshots from PostgreSQL,
extract explicitly supported facts, and propose NCS alignments for explicit duties.
Models and processing limits are workflow parameters. Start with a small evaluation.
All entry points use **llm-local** and **Basic** logging.

The workflows and a 20-posting `korean-jd-v1` dataset are installed on Goldship.
The key authenticated successfully; real model calls remain off because the account
has no credit. See the [deployment verification](../../docs/hop-migration/llm-status.md).

## Start here in Hop Web

1. Open **`${PROJECT_HOME}/llm/install.hwf`** and run it once. It installs the additive
   `enrichment` schema through SQL workflow actions. Repeat installation preserves data.
   The existing `ingestion` bootstrap and private `jobtology-postgres` metadata must exist.
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
| `TEMPERATURE` | blank | Omit by default; optionally supply `0`–`2` when the model supports it. |
| `REASONING_EFFORT` | blank | Omit by default; supported values include `none`, `low`, `medium`, `high`. Model support varies. |
| `MAX_OUTPUT_TOKENS` | `6000` | Per-request output limit, including reasoning. Truncated output is rejected. |
| `EXTRA_PARAMS_JSON` | `{}` | Numeric `top_p`, `seed`, `frequency_penalty`, `presence_penalty`. Example: `{"seed":42}`. |
| `PROMPT_VERSION` | `ko-v1` | Installed immutable prompt/schema version. |
| `POSTING_LIMIT` | `20` | How many postings to include. Raise explicitly, e.g. `10000`, for all currently available jobs. |
| `CANDIDATE_LIMIT` | `40` | Maximum NCS shortlist size, up to 100. |
| `MAX_MATCHES` | `8` | Maximum supported `(competency, duty)` pairs per posting. |
| `MAX_INPUT_CHARS` | `60000` | Complete serialized request limit. Oversized requests are rejected, not silently shortened. This is not a token limit. |
| `MAX_REQUESTS` | `40` | Per-batch request reservations, including unknown transport outcomes. |
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

The spend controls reserve before sending and account for the **greater of reserved
and reported cost**. Unknown charges retain their reservations. They stop subsequent
requests; they cannot guarantee the price of an in-flight request. Configure a dedicated
OpenRouter key's spending limit for a provider-enforced ceiling. Model changes require
reconsidering the reservation. Missing provider usage/cost is shown as unknown, never $0.

The model must support JSON Schema structured output and the options you select.
Provider parameter support is required and provider fallbacks are disabled. Unsupported
options produce a retained error rather than silently weakening the output contract.
The default model is a starting configuration, **not a Korean-quality benchmark winner**.

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
importance is `required`, `preferred`, `unspecified`; logic is `single`, `all_of`,
`any_of`, `unspecified`. Add `position` to a gold duty/requirement when its association
with a named position must be checked. Quotes must be exact substrings of the frozen
field. NCS codes must exist in the dataset's pinned catalog.

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
There are no hidden HTTP retries. A new run can reuse completed valid stages; failed
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

Current input is the text already normalized from JOB-ALIO. PDF/HWP attachments, OCR,
new external text sources, embeddings and semantic retrieval are not implemented here.
Missing attachment contents remain missing. The first retriever uses Korean substrings
and tokens over NCS names, occupations and definitions, with a small broad-category hint.
It does not search the full catalog with the LLM. Retrieval recall must be evaluated;
an absent correct candidate cannot be recovered by the categorizer.

References: [Hop REST Client](https://hop.apache.org/manual/latest/pipeline/transforms/rest.html),
[OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
[Broadcast to Langfuse](https://openrouter.ai/docs/guides/features/broadcast/langfuse).
