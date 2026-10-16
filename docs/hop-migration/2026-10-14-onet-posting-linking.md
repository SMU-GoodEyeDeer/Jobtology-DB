# O*NET posting linking

Status: **COMPLETE and independently VERIFIED** at 13:18:58.737389 UTC on
October 14. The exact 22,635 original source postings produced **12,696 O*NET
posting links on 12,514 unique postings**; 10,121 postings have no allowed link.
Both native publications are VERIFIED: 310 original v4 links and 12,386
current-fact continuation links. The original scheduler was restored with exact
byte readback at 13:19:49.941248 UTC.

| Source | Original postings | Linked postings | Links | Unlinked postings | Multilinked postings |
| --- | ---: | ---: | ---: | ---: | ---: |
| JOB-ALIO | 1,465 | 450 | 452 | 1,015 | 2 |
| JobKorea | 8,434 | 6,613 | 6,712 | 1,821 | 99 |
| Nara | 12,736 | 5,451 | 5,532 | 7,285 | 77 |
| Total | 22,635 | 12,514 | 12,696 | 10,121 | 178 |

There are 12,336 single-link, 174 two-link and four three-link postings.
**1,234 links are ASSISTANT_REVIEWED; 11,462 remain UNREVIEWED**. Every link
remains STAGING with `current=false`, NULL confidence and UNASSESSED confidence
state. Individually reviewed results are still metadata inferences and do not
establish source-stated duties or competency evidence.

All original outcomes are complete: **18,589 VALIDATED/3,990 local SKIPPED/56
technical REJECTED**. The final continuation accounts for 22,099 of those IDs
(18,113/3,932/54), with all 18,167 paid calls using BYOK and router cost $0.
Its raw cost is **$13.56521358**. Shared known cost including every earlier trial
is **$14.22945107**; **$0.0189965** provisional exposure remains reserved for the
earlier BYOK timeout, giving a **$14.24844757** accounting bound under the $40 cap.
Known/bounded cost per 1,000 original postings is **$0.6286481586/$0.629487412**
(the denominator is 22,635). Continuation raw cost per 1,000 original postings
is $0.5993025659; its cost per 1,000 actual paid calls is $0.7466953036.
The $45.90 upstream balance remains user-reported, not independently verified;
the initial timeout's upstream debit is not proven free.

Independent final verification confirmed the exact database, all 22,729 current
source-posting facts/provenance, the disjoint original/continuation outcome
scope, 202,983 nodes, 767,932 relationships, all 5,878 NCS links, and all 12,696
owned O*NET links with exact endpoints, typed properties and review status.
The 94 later arrivals and 1,014 duplicate ontology representations remain
outside the original matching scope; no graph consolidation was requested.
Original v4 is STOPPED with 536 completed IDs; the continuation processed the
remaining 22,099 using current evidence, including the 103 changed Nara inputs.

Final receipts under `~/.local/state/jobtology-hop/onet-matches/`:

| Evidence | Receipt | SHA256 |
| --- | --- | --- |
| Whole continuation output audit | `20261014T120941Z-output-audit-7e2aed5f2415/receipt.json` | `e35b8e74a42e51065834fa266a1302df8e13bea69a00010a1940ee13bf5a648a` |
| Individual bulk decisions | `20261014T123301Z-full-individual-decisions-60a45b0b8059/receipt.json` | `cf18ae541ce2a67db263e0f1bc93175e0d8480916a84620c7b81ac3d3b7e0a71` |
| Original publication recovery | `20261014T130124Z-verified-publication-recovery-413601592376/receipt.json` | `e7ddfffc9026cef5e2aa30d4d909039f0a6a172b019ce0b77020f8b84a5a548d` |
| Continuation publication | `20261014T130203Z-publish-9562745e9914/receipt.json` | `2b9b83fe78b427c053638c10430f6f267c49dbb22eff2eccc3463c41fd1d93e1` |
| Independent combined graph verification | `20261014T131612Z-independent-graph-acceptance-2dc174efae95/receipt.json` | `510c4e4d72960264c7bd9b5e64386e7aac7dfd50f22d2fe0a3ffcebbf7db9907` |
| Exact scheduler restoration | `20261014T131949Z-scheduler-restored-afa7da9ac641/receipt.json` | `820aa948bef3a10d0aad32046899aeceaf75253d449f3b9cb44b2d03055d8e16` |

Semantic application inserted 1,632 actual new decisions (905 ACCEPT/727 REJECT),
protecting all 404 prior decisions, including the fresh pilot's 19 ACCEPT/5
REJECT, and all 23,243 O*NET attempts/full function metadata. Mandatory risk,
control, changed-source, physician and multimatch review coverage passed; road-
driver, nutrition-teacher and Physician Assistant discoveries received bounded
post-output extensions. Ordinary links received no blanket review status.
The final local plan readback independently matched all earlier source/unique/
multilink/review metrics:
`~/.local/state/jobtology-hop/onet-final-plan-metrics-readback-2bcaifxy/receipt.json`, SHA256
`74079f2d10a9cd0ad7dafa9c62c71880d4c970d7425123023b774212594bdbdd`.

Three host integration defects were resolved: a parameter-name check rejected
the digit in NEO4J_CONNECTION before native launch; the host expected its own
publication ID instead of the native UUID after successful publication; and
repeated full-plan count/hash enumeration reached the 120-second deadline.
Qualified host fixes admit valid names, adopt only an exactly bound VERIFIED
native publication and aggregate count/hash in one pass. Original publication
recovery made no repeated graph writes. All 45 focused tests and Ruff passed:
`~/.local/state/jobtology-hop/onet-host-publication-adoption-mmeffmt2/qualification.json`, SHA256
`4a974f007e13f44d499e714efea397f9822ea14537c838f452d8ed756be21a7d`.
Native 22 artifacts, frozen requests and paid outputs remain unchanged.

The 16-worker full supervisor ran 11:18:31.088274–12:08:34.053000 UTC,
**50m 2.965s**, for 22,063 bulk inputs after the separate 36-row pilot. All 23
completed batches passed independent technical audit. Full execution receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T111831Z-full-806df7f0c2b1/receipt.json`.
Remaining work is separate: local-shortlist recall, automatic stale-link
invalidation after source refresh, and controlled profiling of posting dates,
planner statistics and repeated O*NET plan verification. The consumer query
below filters stale evidence; automatic invalidation is not implemented.
Historical pending/held checkpoints below are superseded by this completed
checkpoint. The reference catalogue remains separately VERIFIED; see the
[catalogue report](2026-10-14-onet-catalogue.md).

## Authorization and evidence

On October 14 the user reported `$45.90` credit and instructed `ok proceed` with
O*NET posting linking. The coordinator set a separate **$40 combined task cap**
for O*NET inference, including upstream BYOK charges and router fees, across
pilot/full/resume and task/source pins. Historical NCS accounting retains its
separate $5 cap. The credit statement is user-reported and does not verify an
upstream account balance. Existing `openai/gpt-5.6-luna`, OpenRouter/OpenAI
routing and credentials remain selected.

The exact frozen cohort has **22,635 source postings**: JobKorea 8,434, Nara
12,736 and JOB-ALIO 1,465. The 1,014 duplicate ontology `jobPosting` entities
are excluded. Original source facts, their hash and source/run/record identity
are retained and bound to the READY PostgreSQL projection evidence. Existing
source/NCS facts, edges, strict duty contracts and catalogue namespaces remain
outside the new writer scope. No job-board URL access or content recovery is
authorized.

Original private cohort:
`~/.local/state/jobtology-hop/onet-link-cohort-4_qyxcn1/cohort.json`, SHA256
`15c59e5bc6361896393554563aca61a808d152fba2ae1db7e6b69ee61500d1dc`.
Official catalogue:
`~/.local/state/jobtology-hop/onet-bundle-31.0-20261014/catalogue.json`, SHA256
`7d49867a5889a187bd200dfb08cf5ab6bef631db6d9e6f36753c34374dcc7285`.
Release: `onet-31.0-catalogue-20261014`; database identity:
`46AFBAE6C4FDF4D40BEA13D8B3CD2011FA1BDF7618A986BDC0DE58B12CAA114B`;
verified catalogue load: `b98b5cf9-e256-4212-98c8-41836668455d`.
The original JSON byte hash differs from the PostgreSQL-normalized manifest
hash because the representations differ.

The coordinator's retained baseline is
`~/.local/state/jobtology-hop/onet-link-baseline-71r573r7/pg-baseline.json`, with
the native graph CSV in the same directory. It records 44,397 source requests,
17,536 historical LLM attempts, 10,343 historical paid attempts,
`$17.66538473` total historical recorded cost and 9,986 legacy input bundles.
That historical total covers prior strict-duty and metadata work; it is not
the new O*NET scope. The graph baseline has 202,889 nodes, 755,236 relationships,
5,878 NCS inference edges and zero O*NET posting edges. Later acceptance must
compare the retained baseline independently.

## Separate inference and execution

The additive `onet_matching` schema owns tasks, frozen inputs, candidate/request
hashes, batches, executions, reservations and validated outputs. Its shared
$40 budget is immutable; a new task or batch does not reset spending. Each
worker reserves only its next call before transport. Router and upstream BYOK
usage are recorded separately and combined. Unknown charges remain held and
block new calls. Crashes do not establish that a request was free.

Korean retrieval hints rank official English O*NET candidates; they establish
no NCS-to-O*NET equivalence. Prompts retain admitted original local fields, and
outputs cite actual admitted strings, allow up to three occupations and explicitly
abstain. Metadata inferences establish neither source-stated duties nor
competency evidence. Bulk links remain STAGING/UNREVIEWED with confidence
NULL/UNASSESSED. Quality sampling does not establish individual review.

The host supervisor binds raw source/catalogue bytes, the complete derived
manifest, prompt/schema, retrieval code and Korean hints. It takes the existing
scheduler lock, checks migration fences, keeps private receipts/Basic logs and
emits safe 30-second heartbeats. A wall-clock deadline targets only its own
native process group, verified by PID start time and unique operation marker.
Native Hop performs runtime installation, provider transport and publication.
Host preparation uses bounded Docker `psql` calls without reading credentials.
Freeze uses deterministic immutable chunks bounded by 500 rows and the native
16 MiB JSONB-text limit, then a final complete-cohort seal before planning.
Preparation verifies and INSERT-only registers the exact retained prompt
version/text/hash/schema; a conflicting version or changed schema fails without
overwriting existing rows. Resume processes only never-sent inputs with known
accounting.

## Commands

Run from the repository root after isolated native qualification and deployment
of the exact additive runtime. Helpers acquire their own lock; do not wrap them
in another `flock`. Substitute the private paths printed by each operation.

```bash
.venv/bin/python hop/operations/run_onet_matches.py freeze \
  --source-file /home/maxjo/.local/state/jobtology-hop/onet-link-cohort-4_qyxcn1/cohort.json \
  --catalogue-file /home/maxjo/.local/state/jobtology-hop/onet-bundle-31.0-20261014/catalogue.json \
  --reserve 0.02 --max-output-tokens 1024 --candidate-limit 24 \
  --task-id UNIQUE_NEW_ONET_TASK_ID
.venv/bin/python hop/operations/run_onet_matches.py dry --manifest /protected/manifest.json
.venv/bin/python hop/operations/run_onet_matches.py deploy \
  --isolated-proof /protected/native-qualification/receipt.json
.venv/bin/python hop/operations/run_onet_matches.py install
.venv/bin/python hop/operations/run_onet_matches.py install-reconciliation
# After the separate exact 22-artifact route-recovery proof/deployment:
.venv/bin/python hop/operations/run_onet_matches.py install-route-incident
.venv/bin/python hop/operations/run_onet_matches.py prepare --manifest /protected/manifest.json
.venv/bin/python hop/operations/run_onet_matches.py pilot \
  --manifest /protected/manifest.json --workers 1
.venv/bin/python hop/operations/run_onet_matches.py status --receipt /protected/pilot/receipt.json
```

Pilot selection is deterministic: 12 untouched postings per source, sorted by
SHA256 of `onet-pilot-v1:` plus the posting identity. The 36 calls share a
`$0.25` batch admission cap inside the $40 total. An explicitly preregistered
pilot can supply `--pilot-posting-ids-file /protected/pilot-posting-ids.json`:
an exact JSON list of 36 unique frozen IDs, 12 per source. Provided order,
file SHA/byte length and selected IDs are recorded before planning; unknown,
unbalanced, duplicate or already-planned/sent current-task IDs fail before
batch mutation. This option applies only to `pilot`; default hash selection
remains unchanged. After actual quality,
model/BYOK routing and combined cost are assessed, the coordinator records the
review before scaling:

```bash
.venv/bin/python hop/operations/run_onet_matches.py approve-scale \
  --manifest /protected/manifest.json --review-actor COORDINATOR \
  --review-notes-file /protected/pilot-quality-and-cost.txt
.venv/bin/python hop/operations/run_onet_matches.py full \
  --manifest /protected/manifest.json --workers 8 --batch-size 500 --balanced-sources \
  --batch-id EXACT_NEW_SOURCE_BALANCED_RAMP_BATCH_ID
.venv/bin/python hop/operations/run_onet_matches.py full \
  --manifest /protected/manifest.json --workers 8 --batch-size 1000
.venv/bin/python hop/operations/run_onet_matches.py resume \
  --manifest /protected/manifest.json --batch-id EXACT_INTERRUPTED_BATCH_ID
.venv/bin/python hop/operations/run_onet_matches.py publish --manifest /protected/manifest.json
```

Full processing selects only still-unplanned members of the original cohort in
batches of at most 1,000. An explicit batch ID limits a full invocation to one
batch; `--balanced-sources` makes that ramp sample cover all three sources.
The native contract permits up to 16 workers; ramp
concurrency only after qualified transport and measured provider behavior.
Stable owned relationship IDs permit exact publication replay without duplicate
links. Native qualification and production receipts must establish these
operational guarantees before successful production operation is claimed.

## Independent output and graph acceptance

After each pilot or holdout, export the exact batch and independently validate
every paid response with the manifest's retained Python code:

```bash
.venv/bin/python hop/operations/audit_onet_outputs.py \
  --manifest /protected/manifest.json --batch-id EXACT_COMPLETED_BATCH_ID \
  --require-complete
```

Omit `--batch-id` for the eventual final all-task audit. The private receipt
binds the read-only snapshot, `validated-results.ndjson` and `match-review.csv`.
Technical validation retains UNREVIEWED/UNASSESSED status; it does not record
individual decisions. `known_raw_cost_usd` covers this exact task or selected
batch; `shared_known_cost_usd` includes earlier pilots under the common cap.
`shared_accounting_usd` also includes unresolved reservations and acknowledged
provisional route exposure; task status reports `provisional_exposure_usd`
separately from known charges. Completed
full-cohort metrics divide both final-task cost and shared cost by **22,635
unique source postings** and multiply by 1,000. A separate metric uses actual
paid calls as its denominator. `upstream_cost_usd` includes only billable BYOK
upstream, while `reported_upstream_cost_usd` retains the provider's raw internal
rate even for a router-billed non-BYOK response. Partial audits expose
`audit_scope_complete=false` and completed-posting counts; they suppress the
full audited-listing cost rate. Technical PASS does not establish completion
when PLANNED/RESERVED/ERROR rows remain; use `--require-complete` for a final
gate. Small-pilot cost projections may weight the
candidate-bearing counts (ALIO 1,368, JobKorea 7,903, Nara 9,531); final measured
totals need no source weighting.

After publication, independently compare the graph to the PostgreSQL owned
plan and frozen source evidence:

```bash
.venv/bin/python hop/operations/verify_onet_projection.py \
  --manifest /protected/manifest.json
```

For this run's disjoint original/continuation tasks and the verified post-refresh
baseline, use both exact manifests and the retained assessment:

```bash
.venv/bin/python hop/operations/verify_onet_projection.py \
  --manifest /protected/original-v4-manifest.json \
  --additional-manifest /protected/current-physician-manifest.json \
  --postrefresh-assessment /protected/final-receipt.json \
  --assessment-sha256 ff696503f50066288522f34fea308375cdf83db6bcc4f5cf644ab6f4906bc997
```

Before publication, add `--expect-unpublished`. This verifies the exact Neo4j
database identity, all 22,635 source nodes' typed facts/provenance, all owned
edge IDs/endpoints/typed properties and actual review status, current catalogue
backing, and the node/base-edge/NCS baselines. After publication it also requires
the native publication checkpoint to be VERIFIED. It makes no database write
or provider request.

For manual Neo4j inspection, inferred relationships can remain STAGING with
`current=false`. This consumer query shows links whose frozen facts still match
the current posting; automatic stale-link invalidation remains future work:

```cypher
MATCH (j:entity:jobPosting)-[r:INFERRED_ONET_OCCUPATION]->(o:occupation)
WHERE r.source_facts_sha256=j.source_facts_sha256
RETURN j,r,o LIMIT 25;
```

Add `AND j.source_id='jobkorea'` for that source. To inspect the source scope
including postings with no allowed link:

```cypher
MATCH (p:entity:jobPosting {kind:'JobPosting'})
WHERE p.source_id IN ['jobkorea','nara_job','job_alio']
  AND p.source_facts_json IS NOT NULL AND p.source_facts_sha256 IS NOT NULL
OPTIONAL MATCH (p)-[r:INFERRED_ONET_OCCUPATION]->(o:onetCatalogObject:occupation)
WHERE r.managed_by='jobtology-onet-matching-v1'
RETURN p.id, p.source_id, p.title, o.code, o.label, r.review_status, r.stage
ORDER BY p.id LIMIT 50;
```

The matching scope is the **22,635 unique source postings**, excluding the
**1,014 existing duplicate ontology representations**. Their remaining presence
does not establish missing matches; no graph consolidation is part of this task.

## Historical qualification and preparation checkpoints

The checkpoints below preserve the execution history. Their pending/held
statuses apply at the recorded time and are superseded by the current status
at the beginning of this report.

The coordinator completed local freezing and offline dry validation. The
protected manifest is
`~/.local/state/jobtology-hop/onet-matches/20261014T065810Z-freeze-1a284ad7a9a5/manifest.json`,
SHA256 `951f8b267c66ed2dcdb8600c4367765d6b79fb4b594cec2f06c54d37ed680650`.
It retains all 22,635 source inputs and exact prompt/retrieval/hint code bytes.
The dry check reports 3,833 empty shortlists and a largest conservative request
bound of `$0.0075191025`, within the frozen `$0.02` reservation. Requests use
24 candidates and a 1,024 output-token bound. Empty shortlists abstain locally.
These checks made no provider call or graph write.

The isolated native proof passed **34 checks on the exact 18 runtime artifacts**,
with disposable-resource cleanup verified. Its retained receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-09e014ab9872/receipt.json`, SHA256
`a179a4d0b661a48f7653ead18e66995df73c7917b44612560e2861e605616fca`.
The coordinator changed only the receipt's mode to `0400`; its bytes and hash
remain unchanged. Production operations completed with these private receipts
under `~/.local/state/jobtology-hop/onet-matches/`:

| Operation | Receipt | SHA256 |
| --- | --- | --- |
| Deploy | `20261014T071608Z-deploy-9760c5ddbb40/receipt.json` | `7f9f3f88f75b04552830475a8003952061b42ec09e61140ef26767dc7070dee7` |
| Install | `20261014T071622Z-install-3b1381fb8438/receipt.json` | `397682f21c16fdfbdf2b425d7b1dc64eb23ca5115bebc048dd70d5faa7f6f4df` |
| Prepare | `20261014T071652Z-prepare-a46eea58b5a5/receipt.json` | `af57ffe975a1a6238c074a1359e410c9b24799c159bc9235e42a910ea38a31ad` |

Preparation ran from **07:16:52.043146 to 07:18:09.049046 UTC**, **77.006 seconds**.
It sealed all **22,635 PostgreSQL inputs** under task
`onet-metadata-20261014`, ordered input-binding manifest hash
`dd7da2206a81092836371d724c8a03c21dc12714c8f051e57244ae8a5e2c527c`.
This normalized seal differs from the original frozen file's byte hash. Before
the pilot, accounting and paid attempts were zero, all 22,635 inputs remained
unplanned, and the scale gate was closed. Deployment, installation and
preparation preserve their recorded narrow legacy count/function baselines;
final independent graph/accounting acceptance remains pending.

## First pilot: stopped on unknown accounting

The four-worker pilot began at **07:18:56.679089 UTC** with the `$0.25` batch cap.
Its retained receipt is
`~/.local/state/jobtology-hop/onet-matches/20261014T071856Z-pilot-6011c91118c5/receipt.json`,
SHA256 `c227b35e33404712ff5acc93806be96a28343ff9b42fb407ba18c13bfaf91308`.
At **07:19:17.303484 UTC** the host marked it **FAILED**, after native batch
`onet-pilot-14bfe94a77df400a82dacf702f3f39fe` ended **STOPPED** with reason
`UNKNOWN_CHARGE_ROUTE_OR_RESERVATION_BREACH`.

The receipt records **4 ERROR attempts, 29 never-sent PLANNED inputs and
3 locally SKIPPED abstentions**. Four unknown-charge reservations hold **$0.08**
inside the $40 combined scope. Recorded known cost is zero; this does not
establish zero provider debit. Further paid admissions remain blocked pending
reconciliation. Native exit code zero did not bypass the host's accounting and
completion checks. No successful paid-pilot, full-processing or publication
completion is claimed. The recorded post-failure state has zero retention
writers, and no cleanup error is recorded.

The coordinator's diagnosis identified four OpenRouter pre-dispatch HTTP 404
responses at `Filter by Parameters`: the selected endpoint does not support
`temperature`. Public router/BYOK usage remained unchanged from the 06:37 UTC
baseline. The retained routing evidence is
`~/.local/state/jobtology-hop/onet-matches/20261014T072135Z-routing-reconciliation-8a9573372b45/`.
An omission-only successor removes `temperature` while preserving source
evidence, candidates, prompt/schema, model and provider routing. It uses new task
`onet-metadata-20261014-request-v2` under the same shared $40 cap. The original
task, manifest, 4 ERROR responses and cost-NULL history remain unchanged;
its 29 PLANNED requests are abandoned and must be fenced before new execution.

SQL005 and `install_reconciliation.hwf` were separately qualified as
additive files in the recovery below. All original 18 runtime artifacts remain byte-identical. The
successor adds immutable review/evidence records for the exact pre-dispatch
404 shape and effective accounting; it does not generally treat errors as free
or rewrite historical charges. The normal deploy helper can append these two
qualified files because it verifies existing bytes and refuses replacement.
Invoke `install-reconciliation` after the base installer for the successor
runtime. Recovery and the corrected pilot are recorded below. The earlier
pilot used four workers;
the corrected pilot uses one before the source-balanced 500-row/eight-worker
ramp. The initial failed-routing checkpoint established no upstream model dispatch.

## Recovery and v2 quality hold

The recovery proof passed **39 checks on 20 artifacts**, including preservation
of all original 18 artifact hashes, native reconciliation install/replay,
adversarial non-free errors, historical-row immutability, effective zero-charge
accounting, stopped-task gating and Unicode whitespace validation. Receipt:
`~/.local/state/jobtology-hop/jobkorea-dry-run-f7dad511933d/receipt.json`, SHA256
`53815a4d4f0c0faa7ff759d18f8606768e9580df91c2e73c3781a2d4b4d248f6`.

The temperature-omission successor manifest is
`~/.local/state/jobtology-hop/onet-matches/20261014T072950Z-request-v2-be1131a6120a/manifest.json`,
SHA256 `6343e9ae1fdd09b3f1e6611ab59c5f44b1200f46d97a158db0d96af5d8472488`.
Its comparison proof SHA256 is
`e2570d9e5514c54dbbe2abab951eec917355142e5ec1c996efa195d25fbd0f2b`.
Independent review of all 22,635 rows confirmed temperature removal as the only
request-body change and exact source/candidate/non-request rows, archived
retrieval/lexicon bytes, prompt/hint contracts and accounting scope. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T074551Z-request-v2-independent-review-727eb5de888a/receipt.json`,
SHA256 `37571b5f6402e873ad910c10b239f093a7d89e1470d436e2456c1dc42d179ec3`.
The archived endpoint capability audit passed with zero endpoint issues:
`~/.local/state/jobtology-hop/onet-matches/20261014T074220Z-output-audit-8e64afb09715/receipt.json`.

Corrected preparation completed in **77.347859 seconds**, from
07:32:24.370259 to 07:33:41.718118 UTC, sealing 22,635 inputs under
`onet-metadata-20261014-request-v2`, normalized hash
`7a24bdb167f748c7e3313f3bb637fc26cb9e1b9450f240b30f3ae4b775c60974`.
Receipts under `~/.local/state/jobtology-hop/onet-matches/`:

| Operation | Receipt | SHA256 |
| --- | --- | --- |
| v2 prepare | `20261014T073224Z-prepare-cea2b3e6f07b/receipt.json` | `c496b7f88803e544fa83edaa5d06db32e09ca2973b6de5e3c52fca65680d9b56` |
| Recovery deploy | `20261014T074502Z-deploy-f2ee94e8d36a/receipt.json` | `e9f88456d2af29479ac97cb436355b5f8148984ae08c597d142e3e812fe8aefe` |
| Recovery install | `20261014T074515Z-install-reconciliation-072e16f80334/receipt.json` | `69425e29098493bfeb61aadedebfe478f391020d237423df76b39dd552530e42` |
| Reviewed reconciliation/stop | `20261014T074604Z-reconcile-no-dispatch-9205a9385712/receipt.json` | `ea58591548fbb18e11b411e8b370075e2859ef7889fd5948344c7e5b3b9ebb98` |

Reconciliation completed at **07:46:07.277173 UTC**. Four exact pre-dispatch
errors have reviewed effective zero charges; all 36 original attempt rows and
raw ERROR/cost-NULL history remain fingerprint-exact. The original task is
STOPPED and its 29 never-sent plans cannot be admitted. Shared unknown holds
were zero before the corrected pilot, and the recorded legacy baseline matched.

The corrected single-worker pilot completed from **07:46:24.032466 to
07:48:10.487187 UTC**: 33 paid VALIDATED outputs and 3 local SKIPPED abstentions.
Combined cost was **$0.02876745**, all recorded as upstream BYOK cost, with
router cost **$0** and zero unknown holds. Input/output tokens were
**98,592 / 3,437**. The pinned Python audit passed all 33 paid outputs, with
25 matched postings, 11 total abstentions including local skips, and 32 proposed
matches. These are technical validation results, not individual review.
Pilot receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T074624Z-pilot-3d48ced2af5a/receipt.json`,
SHA256 `54ebd2cf6cc1e82d0200b8e330d491080831389565dd83a07a028924e8d36bf4`.
Audit receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T074827Z-output-audit-9455b60f66a6/receipt.json`,
SHA256 `b996d826160b6c6da3c18b354298d7675d7f91fca292a0005565b0012574bcc7`.

The coordinator's semantic review **failed scaling**: physician OR alternatives
were treated as multiple concurrent occupations, advertisements with more than
three roles silently lost coverage, and overlapping software/web/programmer
codes duplicated one role. At **07:52:05.030586 UTC** the v2 task was stopped;
scale remains unapproved and no O*NET posting edge was published. Stop receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T075205Z-pilot-quality-stop-a33c7e522ce0/receipt.json`,
SHA256 `792b21d3811d299c58090abcd63b06a17f66a8cca07ff804d4f121bf1f98036e`.
A focused prompt-v3 successor is authorized under the same shared $40 cap,
model, schema, retrieval and routing. Its checkpoint follows.

## V3 preparation, pilot and limited holdout

The focused prompt successor uses task `onet-metadata-20261014-request-v3` and
retained manifest
`~/.local/state/jobtology-hop/onet-matches/20261014T080933Z-request-v3-08a3437904f8/manifest.json`,
SHA256 `712755b14d9fda662d562429be0ad85bb378c2346d71db29f04bb4322e76ec56`,
653,683,868 bytes. Prompt version `ko-onet-metadata-occupation-v2` has hash
`14f0f1777a05d5147a4a9b2d673f0c6c45d3f6eb547cdcabf04d420acaacb99c`;
request version `onet-luna-strict-v3` has hash
`bdb926d105cdcb5b7bccdc4273281d92f5765f310440ff38e8f871369e41b9fb`.
The dry check passed all 22,635 inputs, with maximum conservative request cost
`$0.0082714275`, within the retained `$0.02` reservation.

Independent read-only PostgreSQL 18.6 qualification verified the JSONB byte
estimator against 31 adversarial values, 30 actual rows and the complete largest
bounded chunk. V3 requires **46 chunks**, each at most 500 rows and 16 MiB.
The largest chunk starts at ordinal 3,923, contains 488 rows and measures exactly
**16,776,687 bytes**, leaving 529 bytes below the native limit. Original v2
500-row boundaries remain exact for replay. Qualification evidence:
`~/.local/state/jobtology-hop/onet-matches/20261014T081524Z-chunk-qualification-df60f4c2d336/completed-measurement.json`
and `largest-chunk-actual.json` in that directory. No production mutation or
paid call occurred in this check.

V3 preparation completed from **08:23:59.995980 to 08:25:35.281002 UTC**,
**95.285022 seconds**, exactly replaying the retained prompt registration and
sealing 22,635 inputs with normalized input hash
`e2b3251e9ba3226a2fbb9b0830923b26b8eaac38a2148df4b40df72fe498a4b8`.
The four-worker 36-posting pilot completed from **08:26:01.087237 to
08:26:41.421109 UTC**. All 33 paid outputs passed native and pinned Python
validation; three empty-candidate inputs abstained locally. There are 21 matched
postings, 15 total abstentions and 22 proposals. V3 recorded cost is
**$0.03282120**, all upstream BYOK with router $0; shared cost including the
earlier v2 pilot is **$0.06158865**, with zero unknown holds. Input/output tokens
are **116,511 / 3,082**. Receipts under `~/.local/state/jobtology-hop/onet-matches/`:

| Operation | Receipt | SHA256 |
| --- | --- | --- |
| Exact prompt registration | `20261014T081430Z-register-prompt-v3-71b46f2d9dbb/receipt.json` | `76055d1149e486ad9101137131d2b2f572d19e3fa4c7cd6bec0d6389968b1fa5` |
| V3 prepare | `20261014T082359Z-prepare-5f5ba8990391/receipt.json` | `8633c4404db84cdad52129c3b5a9ebdf1de5f759314df26033cf70c55462fdc8` |
| V3 pilot | `20261014T082601Z-pilot-121c78cbe13e/receipt.json` | `91de55eaa679eb7b3c64c294fb8b219dd268d9651302643caf076c0e887ef6c6` |
| Pinned Python audit | `20261014T082704Z-output-audit-8229e584afb6/receipt.json` | `408b794b2e4802a9820aa1565651634eaf8e85ee25660bda20cb4f88292b23ac` |
| Prepublication graph acceptance | `20261014T082927Z-independent-graph-acceptance-066a9fcf5e1f/receipt.json` | `078ca54085d70fbd5e8ec142e652846c2e7804d83549fa6924e107c434e1f541` |
| Individual pilot decisions | `20261014T083024Z-pilot-individual-decisions-40b397ab01a2/receipt.json` | `82cebeee99b7992002ffede836f163f792ee7f9684e9021fc0d8929b2dbd1e5e` |
| Limited holdout approval | `20261014T083045Z-approve-scale-fc9fd5396157/receipt.json` | `d4415eaefe8895c801f35cd8bfef4edc732bc89db89662a15e99e6767cad5450` |

Independent prepublication graph acceptance verified the exact database identity,
202,889 nodes, 755,236 relationships, 5,878 NCS edges, exact typed source
facts/provenance for all 22,635 postings and **zero O*NET posting edges**.
Semantic reviewers found the prior alternative/overflow/overlap failures fixed.
The coordinator atomically recorded **21 ACCEPT and one REJECT** decision; the
rejected sports-trainer proposal crosses a conservative occupation boundary.
These individual decisions do not confer review status on future results.
The limited fresh source-balanced holdout `onet-v3-holdout-500-20261014` was
approved with eight workers. It subsequently stopped on a route rejection:
attempt `566f80ee-8b84-4574-9ebf-e3f610568729` received HTTP 200 with
`is_byok=false`. The partial scope has 264 VALIDATED, 56 SKIPPED, one REJECTED
and 179 never-sent PLANNED inputs. Its **$0.20205698** known cost brings v3 task
cost to **$0.23487818** and shared cost to **$0.26364563**, with no unknown holds.
The native ledger counts the non-BYOK `$0.0010035` router charge once; its
reported upstream rate is not a second charge. However, zero native holds alone
does not establish that all upstream charges are resolved. Generation readback
shows a BYOK HTTP 504 attempt with 13,999 ms latency before the router-funded
HTTP 200. The generation reports upstream inference cost zero, but it cannot
prove that the first timeout was uncharged. The coordinator therefore retains
the original $0.02 incident reservation as a total bound, adding
**$0.0189965 exposure** above the router response's known charge and retaining
**$0.28264213** as the shared conservative accounting bound. Generation evidence:
`~/.local/state/jobtology-hop/onet-matches/20261014T083821Z-nonbyok-generation-readback-8fd9aaf17815/response.json`.
The management-key read returned HTTP 401. Readback receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T083418Z-byok-route-readback-b254c4056bbf/receipt.json`.
The user subsequently confirmed that existing-key BYOK-only was saved, resolving
the external configuration block on **USER_REPORTED** evidence. Independent
administrative readback remains unavailable. Immutable attestation:
`~/.local/state/jobtology-hop/onet-matches/20261014T084249Z-user-byok-only-attestation-a3dfa8704eb5/evidence.json`,
SHA256 `e112a8ab0de7800bf7a4637790c4e72af7642cee9870db29a102ae16c54c2c00`.
Router available credit **$5.41805786** does not establish upstream credit.
At this failed-holdout checkpoint, further calls were held for incident
acknowledgement and v4 qualification; the later curated pilot below is complete.
Updated
partial audit:
`~/.local/state/jobtology-hop/onet-matches/20261014T083734Z-output-audit-588c62c8e88c/receipt.json`.
This is not completed holdout or full-processing acceptance.

Broader partial semantic review found course-content false matching and a forced
`All Other` residual occupation. The wider semantic gate is closed; focused
offline prompt-v4 code is ready. The initial v3 pilot's individual
decisions remain historical reviewed evidence and do not approve the holdout.

The additive route-incident successor, SQL006 and `install_route_incident.hwf`,
passed **77 checks on 22 native artifacts**, preserving all 20 previous file
hashes and confirming isolated cleanup. Proof:
`~/.local/state/jobtology-hop/jobkorea-dry-run-fd796da5ca64/receipt.json`, SHA256
`73369b94e0a41ef7e9ed2605a27d27c2b7429cd4201bbe3bb7965ae0da3e8b84`.
Its acknowledgement can only exempt the exact fully costed rejected
route incident from the request gate after evidence and existing-key BYOK-only
attestation and must retain the coordinator's provisional timeout exposure
separately from actual charges. It does not change the rejected output, charge,
raw response,
validation, publication eligibility or paid request history. The host's
`install-route-incident` stage completed production installation at
**08:58:46.865982 UTC**, following the exact new proof and additive deployment.
Receipts under `~/.local/state/jobtology-hop/onet-matches/`:

| Operation | Receipt | SHA256 |
| --- | --- | --- |
| Route recovery deploy | `20261014T085817Z-deploy-3de49b7611c4/receipt.json` | `c7f262cc14616fdfd606ed7a38b8599985a798b2219e7cfc77ecc06ccaf2808e` |
| Route incident install | `20261014T085837Z-install-route-incident-3cd125e8aa77/receipt.json` | `3ada75a0143cbf25332ec9738bd070230ce3ed142dda376ed7bd8d7770d53aff` |

The later acknowledgement/readback below is committed. Neither installation
nor acknowledgement establishes that the initial BYOK timeout was free.

Read-only timing measurement of the interrupted holdout records **265 paid
completions**, including the route rejection, across **102.417304 seconds** of
host wall time and **81.891607 seconds** of reservation span. Peak ledger
in-flight count was **8**, time-weighted mean **7.7489**; median HTTP latency was
**2.002 seconds**, p95 **2.929 seconds**, maximum **15.901 seconds**. Ledger
intervals include admission and response persistence as well as transport, so
they are not exact HTTP start/end timestamps. Evidence:
`~/.local/state/jobtology-hop/onet-matches/20261014T083838Z-interrupted-holdout-throughput-aac615f039a3/receipt.json`.
The measured rate is **2.587 paid calls/second** over host wall time and **3.236**
over the reservation span. An ideal linear 16-worker projection for the
remaining 18,504 candidate calls is approximately **48 minutes of transport**
before batch overhead (approximately 60 minutes using doubled wall rate).
Sixteen-worker throughput remains unmeasured, and this interrupted short batch
does not establish completed full-run duration.

The earlier v3 pilot's historical calculation projected approximately **$19.01** for the full cohort
using candidate-bearing source weights (approximately **$0.84 per 1,000 source
postings**). This is a historical projection, not measured full-run cost or a
projection from the curated v4 regression sample.

## V4 preparation, acknowledgement and curated pilot

The new complete-cohort manifest is locally frozen at
`~/.local/state/jobtology-hop/onet-matches/20261014T090023Z-freeze-c9b6514ae89a/manifest.json`,
SHA256 `ffc0c4e44bb3c0733d5b60d0eaf4027195edec944612fef9a31d5a39e4335c67`.
The same 22,635 original source postings, 24-candidate limit, 1,024 output-token
bound and $0.02 reservation remain. PostgreSQL preparation completed from
**09:01:50.656621 to 09:03:29.941558 UTC**, **99.284937 seconds**, sealing all
22,635 inputs with normalized hash
`fd7e5c7916a0cb7d434f5832845a8ab4cc97b51b6a07733005505e94edffc9f0`.
Exact prompt registration replay uses `ko-onet-metadata-occupation-v3`, hash
`fffe72153a7caa162209b807a1bb556ccc20dbf5fa3ba0e7f7edfc723ef29f54`.
V3 is permanently STOPPED under
`20261014T090001Z-v3-holdout-quality-stop-97c832463f5a/receipt.json`; its 179
never-sent plans are retained and must never resume.

V4's host contract retains per-row `admission_decision` and binds
`admission_policy_sha256`/`admission_policy_version` in immutable settings.
Current policy `onet-title-training-admission-v1` has SHA256
`3edb36dcc7fd5a4193ef333798304b9126b86312cc7c901781a2db51bc035e34`.
Every retained decision must exactly replay against original source facts and
archived code; excluded non-vacancy inputs must have empty shortlists. Mismatch
fails before PostgreSQL mutations. Audits attach the separate exclusion reason
and retain the native generic SKIPPED output unchanged. Original v3 manifests
without admission keys remain exact.

The curated 36-ID v4 pilot file is
`~/.local/state/jobtology-hop/onet-v4-offline-review-scadc7dq/pilot-posting-ids.json`,
SHA256 `ae2a8a31f7f01106baa98020b871c1776a74109a75ec8b6eb3b164e0a49fa2d2`.
It is exactly 12 unique IDs per source and includes prior failure cases plus
ordinary, teaching and headcount controls. Use the explicit pilot option above;
technical validation, semantic review and measured cost still gate wider work.

The route acknowledgement is **COMMITTED/COMPLETE**, preserving all 608
original attempts and v3's STOPPED state. It records the incident's $0.02 total
bound separately from actual response charges. Before the v4 pilot, shared
known cost was $0.26364563, provisional exposure $0.0189965 and accounting bound
$0.28264213; the initial BYOK timeout is not declared free.

The four-worker curated pilot completed from **09:14:21.680890 to
09:14:59.346237 UTC**: **34 paid BYOK calls**, router cost $0,
**$0.03405499** known cost. Native results are **33 VALIDATED, two course
SKIPPED and one REJECTED** for duplicate ranks
(`MATCH_SHAPE_CODE_RANK_OR_REASON`). Pinned Python audit passed the completed
scope while retaining the rejected output's validation issues; rejected output
is not publishable. Validated/skipped results contain **20 matched postings,
15 abstentions and 22 proposals**, with **122,127 / 3,232 input/output tokens**.
Shared known cost is **$0.29770062**, provisional exposure **$0.0189965**, and
accounting bound **$0.31669712**. Semantic reviewers approved only the next
preregistered regression-500 sample, with **19 ACCEPT/3 REJECT** recommendations
on all 22 proposals. Durable decisions are now committed; scale application
remains pending the explicitly bound source baseline below. There is no publication. The curated sample tests known regressions and controls
and must not be treated as a population cost/quality estimate.

| Operation | Receipt under `~/.local/state/jobtology-hop/onet-matches/` | SHA256 |
| --- | --- | --- |
| V4 prepare | `20261014T090150Z-prepare-d779a6be767e/receipt.json` | `ceaad1841c965dc672f75309f15734215a2372b0bc5e5e7c8c76b918b894f1d6` |
| Committed route acknowledgement | `20261014T091403Z-route-ack-committed-453ff7d1b4b0/receipt.json` | `9310875a48a35ea8af7ca80a99b4dc46b943ef3469d683e285de0c3996d0c667` |
| V4 curated pilot | `20261014T091421Z-pilot-02327ebada52/receipt.json` | `96adf0f843e75b3bf7ed9a6d9c14302bac1430f429c8c2f988656a89ffe870b9` |
| Pinned Python audit | `20261014T091518Z-output-audit-19112178caaa/receipt.json` | `521e97720c7dc4afff735d902a4a343b401b4f1e9c663a75ceadecce48b4ae9c` |

The protected semantic review is
`~/.local/state/jobtology-hop/onet-v4-pilot-semantic-review-_v_ouqw2/review.json`,
SHA256 `e64960eba23cf9ceeba5f7ea2ca6267b8c7b8b291a28c21afef0b5c11753cfa2`.
The three proposed rejections are the IT administrator/developer source-display
rank pair and the pension/benefit/international-services director boundary.
The separately rejected native duplicate-rank response receives no candidate
decision or retry. Prepared private application SQL uses only
`onet_matching.decide_candidate`, atomically checks exact request/input/match/
raw-response bindings, refuses latest-decision conflicts and replays identical
decisions without new rows. It protects all 644 original attempt rows and full
function metadata before/after. Artifact:
`~/.local/state/jobtology-hop/onet-matches/20261014T093750Z-v4-pilot-review-application-prepared-2a38ff62b357/apply.sql`,
SHA256 `b88d4e01917e65d894ebef2bb43e7bad3a3cef219c070f7540623351a742a09e`.
The coordinator committed all 22 decisions (19 ACCEPT/3 REJECT), preserving all
644 original attempts and full function metadata. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T095503Z-v4-pilot-individual-decisions-c491e600dbd7/receipt.json`,
SHA256 `2b338b208da6692744db4b7b700efb5e7e6aedc80d03be68d77e2b2effb8c594`.
This records review of frozen evidence, without asserting current graph
acceptance or publication.

The exact next-500 plan is
`~/.local/state/jobtology-hop/onet-v4-regression500-prereview-347jo789/plan-qualified.json`,
SHA256 `531c3e07818a739dc3b05e1177a45126e45090969c890eac0883db7473c3c1de`.
It has 167 ALIO, 167 JobKorea and 166 Nara IDs, excludes every current v4 pilot
ID and deliberately overlaps 477 prior v3 sample rows/248 prior paid rows.
It is a curated regression sample, not an unseen holdout. Prepared limited notes:
`~/.local/state/jobtology-hop/onet-matches/20261014T094317Z-v4-limited500-notes-prepared-0897d4e66c47/approval-notes.txt`,
SHA256 `8ab5392e660ec3a886e79ca72e03429617440d0384cad42bbb33bf80115ad96c`.

## Regression-500 and current-fact continuation checkpoint

The exact preregistered regression-500 finished transport at **10:29:50 UTC**
and passed pinned Python auditing: **443 VALIDATED/56 SKIPPED/1 REJECTED**, with
**444 paid BYOK calls**, router cost $0 and combined cost **$0.36653687**.
The measured **$0.73307374 per 1,000 sample listings** is not a population
estimate. Original v4 now has **536 terminal outcomes**:
476 VALIDATED/58 SKIPPED/2 REJECTED. Shared known cost is **$0.66423749**, plus
**$0.0189965 provisional exposure**, yielding **$0.68323399 accounting bound**.
Receipts:
`~/.local/state/jobtology-hop/onet-matches/20261014T102735Z-resume-9d1e909ff5e7/receipt.json` and
`~/.local/state/jobtology-hop/onet-matches/20261014T103022Z-output-audit-75f73b378a5c/receipt.json`.
Full semantic review remains distinct from technical validation. Review found
systematic generic physician/surgeon to general-internal-medicine matches,
including 16 clear mismatches among 22 reviewed internal-medicine proposals;
unfiltered full scaling is not approved.

A focused deterministic physician-eligibility successor is authorized only for
the **remaining 22,099 original IDs** (ALIO 1,286/JobKorea 8,255/Nara 12,558),
using current source facts/provenance and excluding all 536 completed v4 IDs,
including local SKIPPED and technical REJECTED outcomes. The 94 later arrivals
remain excluded. The original frozen inputs/history are retained. A separate
qualified semantic contract, unchanged model/schema/routing/native artifacts
and shared $40 cap are required; the continuation needs its own fresh paid
36-row pilot before a scale approval.

Offline source-partition evidence:
`~/.local/state/jobtology-hop/onet-v4-continuation-cohort-i6wqhhio/proof.json`,
SHA256 `e3860abd93c0a8fbe7dfc169abcc016ed8fb6efd3fd87e535180862c2df665a0`;
current-fact source export `cohort.json` in the same directory, SHA256
`1b286253b32b25f184149565be3acc92d30c6fb3c05bf9e438652c12a012f3d0`.
The coordinator durably stopped original v4 from **10:41:00.974 to
10:41:44.796 UTC**, preserving all 536 terminal states, 478 paid calls, attempts,
decisions and legacy/function hashes. Stop receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T104100Z-v4-stop-current-handoff-4951f84a8787/receipt.json`,
SHA256 `639977063f4c26009a4d00c0301be3726fd4271d737a02ef06fa47e83e5e9787`.
The successor task is `onet-metadata-20261014-current-physician-guard-v1`.
The partition alone does not attest terminal execution or a durable stop. Host
prepare/execution must independently require the predecessor STOPPED with the
exact 536 terminal IDs and known BYOK paid accounting. No synthetic SKIPPED
rows or retries of completed v4 postings are permitted.

Future recall work can examine safely abstained English titles such as Flutter
Engineer, NPU Compiler Engineer, Data Engineer/Data Platform and AI Research
Engineer whose roles were absent from the local shortlist. This medical fix
does not broaden those aliases. Automatic stale-link invalidation and review
semantics for STAGING/`current=false` relationships also remain follow-up work;
the manual graph query above intentionally includes those links.

## Qualified continuation running

The frozen continuation manifest is
`~/.local/state/jobtology-hop/onet-matches/20261014T110527Z-freeze-a8a60f7e0e8c/manifest.json`,
SHA256 `c34f490f582cb0b981c44ab366986c4e59be7934930c6ee7a8e61351645300d3`.
Preparation is COMPLETE and the offline dry check passed all 22,099 inputs:
3,932 empty shortlists, maximum conservative request bound $0.0084861525 below
the $0.02 reservation. Final physician policy SHA256 is
`0990ea02a9ffc78811e95c0d0898beae2660ced4dbfe216693047066519ff32a`;
request hash `405439661fbb274cfd54619215fcb33d15322d38625d9565bed26df6f8f21145`.
Qualification preserved the prompt/schema/model/routing/native 22 artifacts,
removed all 22 known clear bad medical exposures (16 internal-medicine/four
family-medicine/two emergency-medicine) and retained five supported offline
internal-medicine controls. Bare endoscopy alone does not justify an internist
match. Final host/retrieval qualification passed **242 tests**.

The own fresh 36-row pilot passed transport/Python audit: **31 VALIDATED/5
SKIPPED**, **31 paid BYOK calls/router $0**, cost **$0.02847970**, 23 matched
postings and 24 proposals. Its seven supported/five unsupported physician
controls behaved as reviewed. All 24 proposals were individually reviewed;
**19 ACCEPT/5 REJECT** decisions are committed, with 1,180 original attempts and
function metadata preserved. Original v4's earlier 336 individual decisions
were also committed (291 ACCEPT/45 REJECT), giving 310 ACCEPT/48 REJECT over its
358 proposals together with its pilot. Publication remains pending.

| Operation | Receipt under `~/.local/state/jobtology-hop/onet-matches/` |
| --- | --- |
| Continuation prepare | `20261014T110601Z-prepare-dc5d75b5998a/receipt.json` |
| Fresh pilot | `20261014T110819Z-pilot-2b1dcd41e68b/receipt.json` |
| Fresh Python audit | `20261014T110926Z-output-audit-00752160a022/receipt.json` |
| Original 336 decisions | `20261014T110920Z-v4-regression500-individual-decisions-695f8c7ac354/receipt.json` |
| Fresh 24 decisions | `20261014T111724Z-physician-pilot-individual-decisions-4d9642484ab9/receipt.json` |
| Scale approval | `20261014T111750Z-approve-scale-5fadb82b36e7/receipt.json` |
| FULL RUNNING | `20261014T111831Z-full-806df7f0c2b1/receipt.json` |

The final preregistered risk queue contains **1,608 exact current IDs**
(132 ALIO/558 JobKorea/918 Nara), adding 251 bounded pilot-boundary flags while
preserving the initial queue and 90 ordinary controls. Artifact:
`~/.local/state/jobtology-hop/onet-physician-continuation-risk-preregister-5wnxq7ps/risk-queue-qualified.json`,
SHA256 `213ffd7507f6104b4d64dd984c8e12ffcd5f43dd22ad5a5e3a8ba6fcbf2fb656`.
Before publication, individually assess all queue/current103/control90 rows,
every actual physician output and every multimatch, including new risks outside
the queue. Allowed ordinary bulk results remain STAGING/UNREVIEWED with NULL/
UNASSESSED confidence. Completed batches receive independent technical audits;
a final whole-scope audit and disjoint original/continuation graph verification
are still required.

The combined unpublished graph check passed the explicitly pinned current
baseline: **22,729 current source nodes/22,635 original IDs**, **202,983 nodes,
755,236 relationships, 5,878 NCS links and zero O*NET posting links**. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T111139Z-independent-graph-acceptance-7ad8f0cbffa4/receipt.json`.
This verifies the source baseline before publication, without claiming full
outcome completion. Both source-fact/endpoint checks and task-specific VERIFIED
publication checks remain required.

## Scheduler interruption and source-content gate

The installed cron entry is `*/15 * * * *`, with `refresh.lock` held across the
entire scheduler invocation. It acquired the lock at 09:15 UTC between matcher
stages. Nara FULL reached READY at **09:24:08.827406 UTC**, after **543.108204
seconds** of fetch/processing, then began graph loading. Scale application failed
before mutation when it encountered the occupied lock. The coordinator paused
only the exact future scheduler cron entry, retaining every other byte, then
recovered the accepted snapshot after guarded cleanup of the stalled graph
phase. Pause receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T092908Z-scheduler-paused-f098503f1750/receipt.json`.

Original crontab SHA256 is
`5c932e4bc2b6024dcba2945d226491af227e608aee71178d1f9e0d7b784999fd`;
paused readback SHA256 is
`d15ee062bc3e837e594593cac3806fb600c00e72c41748593873368df201f4ef`.
The coordinator restored the exact original bytes **using `crontab -` and
stdin** after matching and publication at 13:19:49.941248 UTC. The operation
required the current paused SHA to match before writing and verified the original
SHA by readback. Completed restoration receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T131949Z-scheduler-restored-afa7da9ac641/receipt.json`, SHA256
`820aa948bef3a10d0aad32046899aeceaf75253d449f3b9cb44b2d03055d8e16`.
The original files and historical corrected instructions are retained
under `~/.local/state/jobtology-hop/onet-matches/20261014T092819Z-scheduler-pause-prepared-5c14e4cf2610/`.
The initial long-path install attempt failed before change; stdin installation
and exact readback succeeded. A migration fence was avoided because it would
also reject matcher operations.

Protected source log observations: today's `load_entity_names` took **8.183
seconds**, and `load_posting_dates` took **515.303 seconds**. The October 13 run
recorded 1,269.927 and 1,910.035 seconds respectively, with 1,260.712 seconds for
`verify_entity_names`. These are different-run stage timings, not a controlled
optimization comparison or completed full-refresh estimate. Fresh-run CPU/no-
wait observations identified `record_posting_ingestion_observations`,
`graph_posting_ingestion_dates` and `graph_source_edge_owners` as performance
follow-up candidates. After targeted ANALYZE of `ingestion.record`, `run` and
`graph_export`, with function/query bytes unchanged, a fresh prepared read-only
owner query completed in **0.580 seconds**, returning **10,370 unique Nara
posting owners**, all with empty expected-edge keys. Required owner rows are
preserved; only the nested Nara edge reader is empty. Evidence:
`~/.local/state/jobtology-hop/onet-matches/20261014T095147Z-nara-planner-statistics-refresh-ff77566ffaa0/receipt.json` and
`~/.local/state/jobtology-hop/onet-matches/20261014T095307Z-nara-owner-read-after-analyze-6ebc9713b919/receipt.json`.
Define explicit planner-statistics maintenance expectations after READY
ingestion and measure fresh native date/owner stages. Historical-reference and
validation work remain secondary isolated optimization candidates; these
observations do not establish a controlled gain or authorize a source-reader
change.

The archive-only replay of exact run `260acf70-1c8a-4673-bbb1-f43a407b5b9c`
completed **VERIFIED_ARCHIVE_ONLY_NARA_REPLAY**, with native workflow duration
**713.403 seconds**, final projection READY at **10:14:39.406952 UTC** and
checkpoint at **10:14:40.650653 UTC**. It initiated no source or model calls;
source requests stayed 46,910, legacy paid calls 10,343 and O*NET paid calls
369. All 40 original source pins and the source READY-row hash remained exact;
retention writers returned to zero. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T100244Z-nara-archive-replay-0350b359c75d/receipt.json`,
SHA256 `5ae49a81e5a0683df3d7a8140ea17376332db5f04b66682719fa3d8902c62500`.
Native log SHA256 is
`860a702bc511c3c63245f86fb95d64a63eb2975514ecae69aa3525f2dfcd2526`.

| Replay phase | Seconds |
| --- | ---: |
| Entity names | 6.718 |
| Posting-date load | 460.013 |
| Source-owner clear | 1.144 |
| Identity-reference load / verify | 0.611 / 0.607 |
| Entity-name verify | 6.910 |
| Posting-date verify | 230.826 |
| Membership verify | 0.949 |
| Checkpoint | 1.216 |

The independent post-refresh comparison is VERIFIED on the exact target DB:
**202,983 nodes (+94), 755,236 relationships (unchanged), 5,878 NCS edges and
zero O*NET posting links**. All 22,635 original identities/kinds remain. ALIO/JobKorea
are exact; Nara has 10,173 provenance-only changes, 2,460 exact inputs and
**103 changed-fact inputs** (101 prompt-field changes, two other changes).
The 22,532 stable inputs retain exact original full facts. The pilot36 and
preregistered regression500 each have zero stale inputs; 94 new Nara postings
remain outside the frozen matching cohort. All 22 native files and the old
40 source proofs remain unchanged. Assessment:
`~/.local/state/jobtology-hop/onet-v4-postrefresh-assessment-_g8lgqok/final-receipt.json`,
SHA256 `ff696503f50066288522f34fea308375cdf83db6bcc4f5cf644ab6f4906bc997`.
The 103 changed-fact inputs were held at this checkpoint, with original
manifests/history retained; the qualified continuation subsequently processed
their current facts. They were not marked as synthetic SKIPPED or processed
against stale evidence. The original default verifier baseline remains unchanged; the explicitly
bound current-baseline/task-union branch has now passed as recorded above.
Legacy graph preservation here is count-level plus
exact posting evidence, without a whole-graph property fingerprint.

## Validator parity correction and remaining performance work

An isolated adversarial probe found that SQL `output_issues` accepts an exact
quote consisting only of two newlines when that substring exists in the source,
while Python `validate_output` rejects it using `str.strip()`. Scalar/array
outputs, scalar match entries and scalar citation entries return validation
issues without throwing. The original qualified runtime artifacts stay frozen.
The coordinator independently validated every actual output with the retained
Python validator before scaling and publication.

SQL005 separately qualified the SQL/Python parity correction for whitespace-only
reasons, abstention reasons and quotations while preserving exact source
quotation matching. The 39-check proof above passes
newline/Unicode quote, reason and abstention cases while keeping original native
artifact bytes unchanged. The independent pinned Python gate remains active.

At the earlier v4 checkpoint, the supervisor's **71**, output auditor's **21**, retrieval/prompt **74**, and
graph acceptance helper's **9** focused tests passed (**175 total**), with Ruff
passing. They cover source namespace/count/provenance checks,
deterministic pilot selection, private immutable files, safe SQL JSON encoding,
hard budget/unknown-charge guards, owned native cancellation, INSERT-only prompt
registration, bounded immutable chunk planning, cost scopes and exact typed
graph acceptance. Later continuation verification passed 242 tests across the
five host/retrieval unit files; the narrow publication handoff fix passed 45
focused tests and Ruff. These suites overlap and are not summed.

Publication performance follow-up: the continuation's one-pass host plan
preflight took about 85 seconds including setup (13:02:03.309483 receipt start
to approximately 13:03:28.464 native launch). Native `begin_graph` and subsequent
`check_graph` calls also enumerate the plan. Profile O*NET `graph_rows` joins,
payload construction and repeated immutable-plan verification in a controlled
fixture, preserving exact ordered hashes and detection of source/review changes.
Keep the frozen native functions unchanged during this publication.

The continuation native workflow subsequently succeeded in **638.224 seconds**
at 13:14:09 UTC. Local-log phase timings are below; these are observations from
this run, without a controlled comparison or query-plan attribution.

| Native publication phase | Seconds |
| --- | ---: |
| Freeze exact graph rows | 158.611 |
| Namespace preflight | 77.112 |
| Exact endpoint preflight | 90.368 |
| Write edges | 79.753 |
| Verify typed edges | 79.982 |
| Finish publication | 152.307 |

Each frozen-plan check accounts for approximately 75–76 seconds within these
phases. Read/write work after the write-stage plan check finished in roughly
four seconds; the exact-endpoint phase took roughly 15 seconds after its plan
check. The coarse log intervals support profiling repeated plan construction
and verification before changing graph transport. Retained timing receipt:
`~/.local/state/jobtology-hop/onet-publication-phase-timings-fv8epuvd/receipt.json`, SHA256
`acf514f01b449c258aed57ff72acad425a18304f48538ed492cfae0373f1590f`.
