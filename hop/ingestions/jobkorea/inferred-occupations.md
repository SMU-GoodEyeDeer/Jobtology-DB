# Supplied metadata to inferred NCS occupations

`execute_inferred_occupations.hwf` is a separate native Hop path for the user's
authorized metadata inference. It reads the existing frozen JobKorea bundles and
the exact current READY NCS snapshot. It accepts every supplied listing, including
unknown lexical scope and closed listings. Titles, roles and job-function labels
support an explicitly inferred occupation only; they establish no duties or
competency-unit alignment. Original field quotations, Unicode codepoint spans,
source bundle, NCS catalogue and complete candidate hashes remain bound to each
result. Confidence stays NULL / UNASSESSED.

Install `install_inferred_occupations.hwf` after the source, frozen-input and
existing LLM/retention modules. The canonical `llm/install.hwf` also installs
029–030. Both installers preserve the separate response dispatch and shared
BYOK/router accounting when replayed. The prompt version is immutable: changed
prompt/schema/content hashes require a new version.

Preparation defaults to five listings and `EXECUTE_REQUESTS=N`. It reads no key
and makes no request. Use exact snapshot pins and a new `BATCH_ID` when moving
from an offline preparation to paid execution; a batch's options are immutable.
An optional pipe-separated `POSTING_IDS` selection permits a concrete pilot.
Without a selection, later batches choose the next postings whose exact source
hash and NCS pin have no completed result or previous charged/uncertain attempt.
Exhausted selection creates a zero-item no-op. Previously never-sent requests
remain eligible for a fresh batch; charged failures require explicit inspection.

Each request runs sequentially inside Hop using HttpClient5 with automatic
retries and redirects disabled. The transport verifies execution and batch scope
before reading the protected CSV, reserves immediately before one POST, and saves
the response through the existing request ledger. A provider/transport error,
charged invalid response, outstanding reservation or budget block stops further
sends in that batch. Later requests remain PLANNED without a charge. Unknown
costs keep their reservation. Reported BYOK costs include upstream inference and
router fees; missing or invalid cost components remain unknown.

A supervisor receipt with `status=COMPLETE` means the native stage finished;
inspect `after.batch.state` and `attempt_states` for classification outcomes. A
charged validation failure can leave a `PARTIAL` batch with later rows still
`PLANNED` and unsent. Count charged rejected responses in measured cost, and do
not count unsent rows as abstentions. The finished immutable batch does not
restart itself or retry charged rows.

Standard routing uses `only:["openai"]`, disabled fallbacks, no service tier, and
maximum provider prices of $0.20/M input and $1.20/M output. Request admission
uses the higher $0.25/M cache-write price, an upper token bound from UTF-8 request
bytes plus overhead, the output-token limit and a 5% fee contingency. It rejects
requests at the 272,000-byte conservative token bound or above their reservation.
Default reservation is $0.005; default output limit is 768 tokens with reasoning
effort `none`. Complete supplied metadata is preserved. The model receives only
three representative unit names per candidate; complete candidate evidence stays
in the immutable binding. Cache reuse requires identical exact metadata,
candidates, NCS snapshot, prompt and model options, followed by independent field
quotation validation for each posting.

The user reported $50 in funds and requested the existing lighter model.
Configured batch and rolling daily accounting caps can be at most $50; this
upper bound does not select the full-run budget. Preparation retains a $0.05
batch cap and $4.75 default daily cap. Choose a concrete full-run budget after
measuring the pilot, and subtract the probe and pilot's accounted costs from
that cumulative limit. The daily ledger is shared with other model work.
Reservations are accounting holds rather than provider charges.

The supervisor's cumulative task ledger includes every metadata-inference batch
across JobKorea and NCS snapshot pins and prompt versions. A source refresh cannot
reset historical spending or unknown reservation holds. `current_pin_cost` is a
separate diagnostic; admission uses the global `task_cost` with
`task_cost_scope=ALL_METADATA_INFERENCE_BATCHES_V1`. The $4.75 default remains
unchanged. The originally authorized $5 combined task cap includes the separate
$0.00000780 health probe, leaving an explicit native cap of $4.9999922. A new
current-pin pilot uses selected existing frozen bundles and new bindings without
changing historical catalogue pins, bundle hashes, results or review decisions.

The optional `execute_inferred_occupation_workers.hwf` uses the same prepared
requests, prompt, model, cache identity and finalizer. Install its 031 admission
contract through `install_inferred_occupation_workers.hwf` after 029–030.
`REQUEST_WORKERS=1` remains the default; values 1–8 are allowed. Start with four
workers, then measure a small eight-worker batch before a larger run. Both one
batch of up to 10,000 postings and bounded 500-posting batches are supported.
Preparation has no added 60-second query timeout.

Each worker reserves under the existing global spend lock. One immutable
dispatcher token owns its reservations, and startup rejects an earlier
outstanding reservation or dispatcher for the same batch. Admission rechecks
the exact READY source pins, worker bound, shared daily cap and batch cap before
every POST. A charged error, invalid response, unknown cost or budget block
stops new admissions; at most `REQUEST_WORKERS - 1` requests already in flight
may finish. Their unknown costs retain their holds. No failed request retries,
and unsent PLANNED rows remain eligible for a fresh batch. A save failure keeps
its RESERVED row and requires inspection. Four or eight workers hold at most
$0.020 or $0.040 at the default $0.005 reservation before responses settle.

The protected supervisor may select the optional workflow through a bounded
`--workers` option. Do not resume an old dispatcher: use a fresh batch identity,
the same exact snapshot pins, and the remaining cumulative task budget.

Finalization captures schema/evidence-validated results without adding semantic
ACCEPT decisions. `publish_inferred_occupations.hwf` publishes only the separate
STAGING `INFERRED_NCS_OCCUPATION` relation, preserving UNREVIEWED status unless an
actual independent review exists. Serving and DUTIES_ONLY edges keep their
existing review gates.

The additive `037_metadata_occupation_multimatch.sql` contract introduces an
explicit opt-in `ko-metadata-occupation-v3` prompt. Historical v1/v2 prompts,
requests, cache identities, candidates, result-level reviews and graph payloads
remain unchanged. The native defaults remain v1 and `MAX_MATCHES=1`; selecting
v3 in the supervisor chooses a default cap of three and 1,536 output tokens.
`--max-matches` may choose 1–3 for v3 or 1–2 for v1/v2, and
`--max-output-tokens` may choose 256–2,048. Both choices are immutable batch and
request options. The output allowance is a bound, not a guarantee that every
three-role response fits. Truncated/invalid responses fail validation; the
existing reservation formula, shared BYOK/router accounting and cumulative task
cap still apply. Requests exceeding their reservation remain rejected locally.

V3 supports distinct advertised roles, with an independent positive reason and
literal evidence for each occupation. Each candidate supplies a `role_anchor`
from title or role that is repeated as the identical `{field,quote}` object in
its own evidence array. A longer quote merely containing the anchor does not
satisfy this exact object requirement. Multiple anchors must
be disjoint phrases in the same source field, ordered by their first exact
Unicode occurrence. The validator rejects duplicates, missing or invented
citations, excess matches, reused anchors, out-of-order ranks and explicit role
alternatives. Tool alternatives such as “Java or Kotlin” do not disqualify an
otherwise clear single role. Ambiguous specializations, conflicts between fields
and advertised alternatives require abstention in the prompt; literal quote
validation does not prove semantic correctness. Inseparable or overlapping
combined-role evidence may abstain under this conservative structural contract.

`match_rank` is frozen source mention order for display, never confidence or
occupation importance. `original_primary` identifies rank one.
`current_primary` identifies the lowest original rank among candidates actually
published under the selected review filter. Rejecting rank one therefore leaves
rank two unchanged and makes it the current display primary. A candidate's
`occupation_scheme=NCS` and exact `occupation_scheme_run_id` are explicit in v3
provenance; O*NET would require a distinct future scheme and adapter. No crosswalk
or O*NET content is inferred here.

V3 reviews are individual. Obtain
`enrichment.metadata_occupation_candidate_review_packet(batch_id)` and call
`enrichment.decide_metadata_occupation_candidate(candidate_id, decision, reviewer,
reviewer_kind, notes)` for each actually reviewed candidate. Result-level review
is rejected for v3; it cannot grant reviewed status to every candidate. The
append-only candidate decision history has the same retention freeze as other
LLM history. Rejected candidates are excluded independently and prevent reuse
of that cached model response. A cache hit creates fresh per-posting candidates
with revalidated citations and no inherited review status.

Publication selects the latest captured, validated result for each posting and
exact source pins. Preparing or failing a newer request cannot hide a prior
validated link. A newly validated result can replace the current projection;
an explicitly published validated abstention retires prior current edges while
retaining their historical evidence. Selected-item status continues to expose
the latest request's pending/failure outcome. Implicit fresh selection still
skips existing terminal/charged observations, so opting into v3 does not
automatically reclassify historical v2 listings. A deliberate new pilot requires
explicit posting selection and a new batch identity under the same task budget.

Install 037 last through the updated canonical or inferred installer before
using v3, and deploy the changed inference graph pipelines alongside it. The
focused batch-free publication installer also replays 037 last. A fresh canonical
LLM installation may precede retention; replay 037 after installing retention
before recording candidate reviews. Review inserts fail closed when the new
table's retention trigger is absent, disabled, or attached to another function.
The inferred installer performs the required replay. Historical rows and
existing graph links need no rewriting. Offline proofs use
`hop/llm/tests/metadata_occupation_multimatch.py` and
`hop/ingestions/jobkorea/tests/metadata_multimatch_native.py`; they use synthetic
responses and disposable local databases without paid calls or source requests.

Regenerate native files and verify the isolated mock transport with:

```bash
python3 hop/ingestions/jobkorea/tools/build_metadata_linking.py
uv run python hop/ingestions/jobkorea/tests/metadata_native.py
python3 hop/ingestions/jobkorea/tools/build_metadata_concurrency.py
uv run python hop/ingestions/jobkorea/tests/metadata_concurrency.py
uv run python hop/ingestions/jobkorea/tests/metadata_concurrency_guards.py
```

The mock fixture uses synthetic local input and a disposable INTERNAL Docker
network. It proves no dry-run key read, per-posting cache evidence, canonical
installer replay, combined fee accounting, literal quote rejection, one wire
request on HTTP 429, disabled redirects and an uncertain timeout hold. It uses
no real credential, paid API, source URL request or production write.
The worker fixture also proves atomic budget races and duplicate claims,
four/eight native HTTP concurrency, per-posting cache revalidation, stale holds,
source-pin checks and failure stopping with only existing in-flight requests.
The separate network-none unit fixture checks global daily contention across
batches and release of capacity; it stubs source validation solely to isolate
that spending contract.
