# Explicit JobKorea cohort replacement

Completed **2026-11-03 KST**: exact 5,482-record replacement, fresh NCS/O*NET
publications, graph retirement, preservation, SERVING event 3, deployed reader
verification and exact Hop cron restoration are verified. Authenticated HTTP and
browser flows were not verified. The [current handoff](current-handoff.md) records
the final operational checkpoint; reusable procedures and receipts follow.

## Authorized input and pins

| Binding | Exact value |
| --- | --- |
| Supplied file | `/home/maxjo/Downloads/datasets/j_mvzgc6341qkyxlp3qu.ready.ndjson` |
| File bytes / listings | `13960786` / `5482` |
| File SHA256 | `4343f52738cce2eff0de13d6e9d1f98415db3384532d3a21ff0124ed8b55dfa6` |
| Native run | `jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f` |
| Replacement ID | `jobkorea-replacement-20261103-4343f52738cc` |
| NCS pin | `5f5959bd-b965-436a-830a-db75efafd7b8` |
| O*NET task | `jkr-20261103-onet` |
| O*NET release | `onet-31.0-catalogue-20261014` |
| Additional matching budget | `$10` target, `$12` combined hard ceiling: NCS `$5`, O*NET `$7` |

Import these exact bytes directly. Do not compose or sort a replacement export:
that changes its hash and native run. Collection time is unknown; the previous
snapshot's reported collection time does not apply. Archive raw bytes privately,
with line/byte provenance and immutable checkpoints. Job-board URLs remain inert;
no source HTTP, content recovery, or credential/provider changes are authorized.

The reviewed private matching manifest binds these values plus the cohort export
SHA256, O*NET database/catalogue hashes, review actor and accounting policy.
It uses contract `jobkorea-replacement-matching-v1`, NCS batch prefix
`jkr-20261103-ncs-`, `reuse_paid_responses=false`, and a 24-posting pilot. Preserve
all earlier accounting and unknown holds; this new allocation does not rewrite
historical ledgers or establish the provider account balance.

## Prepare and import

1. Hold the scheduler lock for each mutation and reject concurrent refresh,
   loading or graph writers. Supervisors acquire their own host lock; do not
   nest another `flock` around them. Retain a full verified database backup and
   private preservation fingerprints covering other source rows and mappings,
   shared catalogues, O*NET schemas, immutable historical evidence, and the
   separate backend user database. Save a typed full graph baseline.
2. Review/deploy the exact runtime files. Apply qualified additive
   [ontology SQL037](../../hop/ontology/sql/037_jobkorea_replacement.sql) and the
   graph SQL009 replay fence. The final bridge-aware SQL037 artifact has SHA256
   `aaa9194e04d829e3157880504118263424f4fc92065f1448f884328d9b80a897`.
   Verify installed bytes and function bodies. Run reader grants using the
   current grant script; replacement tables/helpers must stay private. Do not
   replay old individual reader migrations after SQL037: they replace its
   fences. Full canonical installer replay needs a reader maintenance window.
   Retain order SQL037 → qualified SQL038 → crosswalk-only SQL039; the tracked
   ontology installer already appends both final steps.
3. Before the new run becomes READY, create the immutable PREPARED plan:

```sql
SELECT ingestion.prepare_jobkorea_replacement(
 'jobkorea-replacement-20261103-4343f52738cc',
 'jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f',
 '4343f52738cce2eff0de13d6e9d1f98415db3384532d3a21ff0124ed8b55dfa6',
 5482::bigint, '5f5959bd-b965-436a-830a-db75efafd7b8', 'jkr-20261103-onet');
```

PREPARED retains the previous SQL serving cohort and its mapping pins while
hiding the pending run/task. For the first replacement it freezes the prior
observation boundary; subsequent replacements retain the preceding SERVING
pins. Ordinary imports without any replacement history keep their legacy delta
behavior. An existing PREPARED graph guard or retention writer prevents plan
creation.

Use native `ingestions/jobkorea/import_local.hpl` for the PostgreSQL-only stage,
with exact `INPUT_FILE`, `INPUT_FORMAT=NDJSON`, private absolute `RAW_ROOT` and
`MODE=IMPORT`. Verify READY, exactly 5,482 accepted unique posting IDs, zero
validation issues, the receipt hash and frozen input coverage. This stage alone
does not prove source graph publication. The older composition supervisor is
unsuitable for changing this exact input's bytes; its legacy runtime assertions
also require separate qualification.

## Source graph and fresh matching

Native matching requires the new exact source graph proof/checkpoint. Before
publishing new source facts, enter BLOCKED:

```sql
SELECT ingestion.block_jobkorea_replacement('jobkorea-replacement-20261103-4343f52738cc');
```

BLOCKED hides JobKorea rows and associations in SQL readers, including bounded
crosswalk observations; other sources remain available. Keep the ledger BLOCKED
through source publication, matching, graph cleanup and independent verification.
The SQL fence is not an isolated Neo4j staging database: direct graph consumers
can observe graph updates during this interval unless they have a separate
maintenance/read boundary.

Load/verify the exact new source run through native `graph/load_snapshot.hwf`,
then record its `hop-graph-v2` checkpoint using the existing native workflow.
Archive-only `full.hwf` recovery with `RESUME_RUN_ID=EXACT_NEW_RUN` is also
supported. Never replay an old JobKorea source run after replacement planning:
the graph reader rejects retired pins and omits them from ALL_CHECKPOINTED.

Freeze new NCS input bundles and a JobKorea-only O*NET source cohort. Retain exact
source row/facts hashes, immutable shortlists, requests and original review
history. Fresh matching must not reuse historical paid responses or reviews.
Use the existing lighter model, OpenRouter/OpenAI route, no fallbacks, and NULL /
UNASSESSED confidence. Validated bulk results remain STAGING / UNREVIEWED.

An NCS pilot invocation uses the reviewed scope paths and exact pins:

```bash
.venv/bin/python hop/operations/run_inferred_occupations.py execute \
  --jobs EXACT_NEW_RUN --ncs 5f5959bd-b965-436a-830a-db75efafd7b8 \
  --batch-id jkr-20261103-ncs-UNIQUE_PILOT --limit 24 --max-requests 24 \
  --max-cost 0.15 --reserve 0.005 --workers 1 --reuse-cache N \
  --prompt-version ko-metadata-occupation-v2 --max-matches 1 --max-output-tokens 768 \
  --retrieval-revision metadata-occupation-lexical-v3 \
  --replacement-manifest /protected/replacement-scope.json \
  --replacement-sha256 EXACT_SCOPE_SHA --replacement-phase pilot
```

NCS uses 12 candidates. Review all 24 pilot outputs and actual combined costs.
Full execution requires a hash-bound review JSON with `decision=APPROVE_SCALE`,
`reviewed_postings=24`, `scope_sha256`, actual review actor/notes and pilot batch
IDs. Pass `--replacement-phase full --replacement-review-file ...
--replacement-review-sha256 ...`; use fresh batches for never-sent work and ramp
through 100/500 rows only after review. All NCS batch IDs retain the fixed prefix.

Freeze O*NET using `run_onet_matches.py freeze` with the new cohort file/hash,
exact retained official catalogue file/hash, task `jkr-20261103-onet`, and
`--replacement-manifest ... --replacement-sha256 ...`. Use 24 candidates,
three matches, 1,024 output tokens and `$0.02` reservation. The resulting frozen
manifest binds the replacement scope. Run `dry`, qualified deployment and
`install-replacement-scope`, then `prepare` and a 24-posting, one-worker pilot.
Its admission cap is `$0.25`. Inspect every output and actual cost before
`approve-scale --review-notes-file ...`; then use bounded `full` batches.
Each subsequent O*NET stage uses `--manifest /protected/onet-manifest.json`.
No historical three-source cohort or continuation proof belongs in this scope.

Unknown charges stop new sends and retain conservative holds. Status receipts
must distinguish matched, abstained, rejected/failed and unsent rows. Paid
validation failures consume budget. An exhausted/blocked budget is not full
cohort completion.

## Qualified publication policy boundary

[LLM SQL038](../../hop/llm/sql/038_replacement_policy.sql) is an optional,
prerequisite-aware installation step. It follows SQL037 in the ontology installer
and remains the final policy step in the LLM, O*NET and JobKorea installers. The
ontology installer then appends crosswalk-only SQL039. Verify its deployment hash and
installed function signatures before use. The qualified SQL038 artifact SHA256 is
`19e53a7c95e5b58cc9d67ff49ca7ca1970411e5f8ab22c6e2523d2fb35d30ba9`.
It applies only to the exact new run,
NCS batch prefix and O*NET task above; historical cohorts retain their contracts.

The finite source-support matrix covers **49 NCS and 38 O*NET occupations**.
Unregistered or unsupported occupations are held by default. Append-only,
hash-bound `POLICY_ALLOWED` / `POLICY_BLOCKED` assessments describe automated
publication eligibility separately from technical response validation, actual
individual review and NULL / UNASSESSED confidence. A policy pass never grants
semantic review status. Original responses, charges and source listings remain
unchanged.

Qualification excludes all **35 known bad pilot/ramp links**, retains **121 of
158 individually acceptable links**, and conservatively holds **37**. The current
assessment excludes a whole response when one candidate fails, so it can also
hold a valid companion link. Report these holds separately from model abstentions
and literal validation failures. Guarded projector/reader signatures and the
shared publication gates fail closed after incompatible replay; restoring the
qualified definitions restores eligibility.

A 5,000-row, single-CPU synthetic qualification measured the following under the
unchanged five-second bound; the final replay was measured separately:

| Reader | Qualification (s) | Final replay (s) |
| --- | ---: | ---: |
| NCS graph | 1.097 | 1.133 |
| NCS API projection | 1.307 | 1.316 |
| O*NET graph | 2.472 | 2.419 |
| O*NET API projection | 3.824 | 3.788 |

These timings qualify the synthetic fixture only. They do not establish deployed
API latency, production publication or completed replacement. Preserve the
qualification and coverage receipts, and verify actual deployed reads separately.

## Verified fresh matching — November 3, 2026 KST

The exact local export `j_mvzgc6341qkyxlp3qu.ready.ndjson` contains **5,482
records / 13,960,786 bytes**, SHA256
`4343f52738cce2eff0de13d6e9d1f98415db3384532d3a21ff0124ed8b55dfa6`.
Collection time is unknown. No job-board HTTP or source-content recovery was
used, and no earlier export's collection time or paid inference was reused.
All supplied records lack narrative content; the resulting occupation links
remain explicitly inferred from listing metadata.

The frozen source run is
`jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f`,
with NCS pin `5f5959bd-b965-436a-830a-db75efafd7b8` and O*NET task
`jkr-20261103-onet` on release `onet-31.0-catalogue-20261014`. Both matchers are
terminal for all 5,482 observations, with zero remaining pending inputs and no
charged observation retried.

| Matching outcome | NCS | O*NET | Combined |
| --- | ---: | ---: | ---: |
| Paid requests | 5,441 | 5,106 | 10,547 |
| Local abstentions | 41 | 376 | 417 |
| Technically VALIDATED responses | 5,431 | 5,093 | 10,524 |
| Technical REJECTED responses | 10 | 13 | 23 |
| Valid matched responses | 3,812 | 4,326 | 8,138 |
| Valid/local abstained responses | 1,660 | 1,143 | 2,803 |
| Technically valid candidate links | 3,812 | 4,482 | 8,294 |
| Separate raw proposals in rejected responses | 10 | 24 | 34 |
| Post-curation publication projection | 1,632 | 1,562 | 3,194 |
| Actual matching cost (USD) | 2.65541002 | 4.41894238 | 7.07435240 |

The 23 technically rejected responses stay terminal and unlinked. Known
formatting faults included literal source citations, duplicate numeric ranks
and duplicate in-shortlist occupation codes. Original validators, requests,
responses, transport states and charges were preserved. Native NCS stops used
fresh batches for exact never-sent remainders; native O*NET resumes admitted only
the proved never-charged PLANNED rows. A private operational classifier was
tested against the three observed shape cases and negative controls; it did not
repair an output or grant publication eligibility. Its allowance was bounded by
both 1% and ten technical rejections per original batch.

The automated source-support policy assessed **10,941** technically valid/local
responses. Every assessment matches its original source, output and policy
hashes. Policy-allowed candidate links numbered 1,640 NCS / 1,566 O*NET before
individual decision filters. Actual individual rejections reduce the publication
projections to **1,632 / 1,562**. The native publications below subsequently
verified these payloads. Cleanup and preservation were verified separately
below; activation subsequently verified SERVING event 3 with these exact pins.

Of the projected links, **15 NCS and seven O*NET links are ASSISTANT_REVIEWED**;
the other **1,617 NCS and 1,555 O*NET links remain UNREVIEWED**. No projected link
is HUMAN_REVIEWED: combined counts are **22 ASSISTANT_REVIEWED / 3,172
UNREVIEWED / zero HUMAN_REVIEWED**. Confidence remains NULL / UNASSESSED.
Automated policy passes do not confer semantic review or source-stated duty
evidence.

| Projection binding | NCS | O*NET |
| --- | --- | --- |
| Expected edges | `1632` | `1562` |
| Native rows hash | `d10cb8b2fcc7c63b11a5b5181c7e209ae32d0385274f2fcba897b970c02888f8` | `2a725ecd6fe86fac6f4ee9bce9eb304bea13760941a3748f42927be0d85658cf` |
| Full projected payload bytes | `4035705` | `9621328` |
| Read-only proof wall time (s) | `2.311` | `3.677` |

Both projections have zero policy-blocked, technically rejected, manually
rejected, missing-assessment, wrong-pin or non-NULL/assessed-confidence leakage.
The NCS hash was also checked against the actual native graph-hash function.
These read-only measurements are separate from deployed API latency.

The **$7.07435240** combined cost includes reported upstream BYOK charges and
**$0 router fees**, below the **$10 target / $12 ceiling**. The existing lighter
model and OpenRouter/OpenAI route, credentials and accounts were retained.
New-scope unknown charges, duplicate paid observations and live matching
reservations/owners/executions are zero. Earlier ledgers were not reset. Preserve
the 21 older NCS and four older O*NET raw NULL-cost ERROR rows outside this scope;
the native shared O*NET ledger still carries its earlier **$0.0189965**
provisional exposure. Its global accounted total is distinct from this task's
settled cost.

Protected receipts share this private root:
`~/.local/state/jobtology-hop/jobkorea-replacement-20261103-4343f52738cc/`.
Keep raw exports, request/response bodies, signed URLs, credentials and private
review packets out of Git.

| Receipt | SHA256 |
| --- | --- |
| `full-remainder-drain/final-reconciliation/matching-final-receipt.json` | `d5dbc6ef70b26c2735202ea9f2b5b1de331b8c2134541ad2eab372a9ce01826b` |
| `full-remainder-drain/final-reconciliation/post-curation-publisher-binding.json` | `45c872fa050b293c96467bc5279962d6157647d94675a31ad8f9d4934ba1c948` |
| `full-remainder-drain/final-reconciliation/global-idle-and-accounting-gate.json` | `a315b0d41fe57596a838a313e8b62e67e8fe68e4bc9c397851109fc83d6524c1` |
| `watch-review/final9-rejections-applied.json` | `dabe291ab10440f0240d433fd4ecb4751d9a371dca502967bf4662cece2e1964` |
| `watch-review/final9-rejections-readback.json` | `c96f648416ed6f4feb266d8c15db76dad0e871528f283fe050d896216af5a45a` |

## Verified native publication, graph cleanup and preservation

NCS publication is **READY**, **1,632 links**, writer token
`df4a3fc7-42c3-4cb1-b308-f5fe04280581`. O*NET publication is **VERIFIED**,
**1,562 links**, publication ID `99cf2ce7-542c-460a-94d4-ccd048015692`.
Both published payloads were verified. The owned bindings receipt is
`owned-publication-bindings-11fdee96336e/bindings.json` under the private task
root, SHA256
`d56a012450d184d5cb088e52040274b34d3807ec0beb5179d00faa0e1824d502`.

The private cleanup manifest is
`~/.local/state/jobtology-hop/jobkorea-graph-plan-8279448039c04d859e198f589646e060/manifest.json`,
SHA256 `05852408254510d062dd890459b3de80539f88643ad4ddd4c91645f6b632be03`.
The verified operation removed **6,912 old-only nodes / 12,185 old edges**:
5,878 NCS and 6,307 O*NET edges. The plan had **zero hazards**. Final graph counts
are **204,639 nodes / 777,713 relationships**, with exactly **5,482 fresh
postings / 1,632 NCS links / 1,562 O*NET links**. The original protected
manifest comparison remains exact at **973,675 entries**, SHA256
`d468fc47200a3f08d160a79b3e6dee48245af7fbc7d1618ebb43f3bde1f3d553`.
The VERIFIED graph cleanup receipt is
`~/.local/state/jobtology-hop/jobkorea-graph-verify-f1ea6790e010408b9219fff816a3cdc8/receipt.json`,
SHA256 `5db0b019dbb7556556feaf77ff7aa62fd4d3d6b0880d3e8ab984691bed902f37`.

Final preservation receipt
`final-preservation-final-ae16aeefd663/receipt.json` under the private task root
has status **VERIFIED_FINAL_PRESERVATION**, SHA256
`eac627fe2b2000e6caac8c6f65f165e5119011ece01be116c511a5cbcd761adc`.
All **228 old protected multisets have zero differences**, all **27 application
tables are exact**, and all **973,675 original protected graph entries** match
the original hash above. The apply-stage comparison also preserved its 205
fingerprints. Authorized new replacement ledgers/policy rows are valid, and
historical accounting remains unchanged.

## Verified serving, deployed readers and scheduler restoration

Activation reached **SERVING event 3** with the exact source and native NCS/O*NET
publication pins above. Actual deployed catalog-reader enumeration checked
**68 pages / all 5,482 exact JobKorea native IDs**, retaining **1,240 other-source
postings**. Detail, contexts and exact chat-graph checks passed; failures were zero.

The initial O*NET `15-1252.00` crosswalk exceeded the five-second reader bound.
Additive [ontology SQL039](../../hop/ontology/sql/039_crosswalk_pair_workset.sql)
changes only two crosswalk read functions: it selects visible code-filtered O*NET
edges before reading their indexed task/input facts. It preserves the original
NCS path, source/key pairing, task/publication selection, latest-edge semantics,
review/freshness fields and full JSON. All three qualified function hashes,
immutable v1 rules, table schemas, ledgers and source pins remain unchanged.
Its source SHA256 is
`850361b07e870200c9ee058ac4b29edfcddd81cbe14bb14972f5827102e7c8a3`;
deployment commit is `d653b52`. Actual PostgreSQL qualification covered full JSON
and pagination, canonical replay, noncanonical cross-scheme identities,
multiple tasks/sources, payload task fallback, newer missing-input edges,
changed-code anchor behavior, stale/NULL/UNKNOWN pins, native review decisions,
legacy fallback, qualified-signature drift and disabled assessors.

Final actual deployed reader checks used the unchanged **five-second** bound:

| Crosswalk reader | Cold read | In-process cached read |
| --- | ---: | ---: |
| O*NET `15-1252.00` | 1.956 s | 0.008 ms |
| NCS | 3.719 s | 0.005 ms |

Public readiness returned **200**; an unauthenticated API request returned **401**.
**Authenticated HTTP and browser flows were not verified.** The successful deployed
reader and public health/auth-gate checks must not be reported as browser coverage.

The coordinator restored **only the exact Hop cron prefix (one entry)** and
verified every other cron entry unchanged. Paid matching dispatch is stopped;
source listings, historical responses/accounting and policy definitions remain
unchanged by the crosswalk repair. **No BE or FE deployment was needed for this
import.** Operational replacement is complete.

| Final verification | Protected receipt under the private task root | SHA256 |
| --- | --- | --- |
| SQL039 deployment | `sql039-deployment-90d159c347c5/receipt.json` | `6ef6a26d4d905eb5b186b223a546be0e23c05a992f12cfe045f18a52ebb9a819` |
| Focused deployed reader | `focused-deployed-reader-62b101598648/receipt.json` | `7c69d969ef89df836168cc62fe46e7b0bd6c30b4972f37fae2517dd4b58e8a00` |
| Public health/auth gate | `public-health-authgate-0e9534e3b453/receipt.json` | `bb0c008f72d9559aaacaf902e75070df923da34e1644ef5b9c69e064f0a7ad53` |
| Exact Hop cron restoration | `cron-restoration-574731155c8c/receipt.json` | `865299903ca691b089bb64c4d44fa8dc66ea25a9cf86985cb9495b51c1fec30a` |

On the next canonical ontology install, use the tracked
[installer](../../hop/ontology/install.hwf) and
[generator](../../hop/ontology/tools/build.py): earlier reader migrations →
bridge-aware SQL037 → qualified SQL038 → crosswalk-only SQL039. LLM, O*NET and
JobKorea installers retain their prerequisite-aware SQL038 final policy step;
ontology appends SQL039 afterward. Do not replay older reader bodies as a final
state. Verify the qualified signatures, policy readiness and deployed crosswalk
output/latency after any canonical replay.

## Publish, purge and activate

Publish NCS with exact new pins and `--include-unreviewed`, retaining the READY
writer token. Publish O*NET from its new manifest, retaining the VERIFIED
publication ID. These native publishers verify their exact graph payloads but
do not retire all historical cross-run mappings by themselves.

While BLOCKED, the source-scoped operator builds a private immutable removal
manifest, removes old JobKorea associations and posting nodes absent from the
new cohort, and compares protected graph objects:

```bash
.venv/bin/python hop/operations/cutover_jobkorea_graph.py plan \
  --ncs-token EXACT_NEW_NCS_TOKEN --onet-publication EXACT_NEW_ONET_PUBLICATION
.venv/bin/python hop/operations/cutover_jobkorea_graph.py apply /protected/graph-manifest.json
.venv/bin/python hop/operations/cutover_jobkorea_graph.py verify /protected/graph-manifest.json
```

The operator refuses unexpected attachments, foreign labels or changed
publication pins. It does not delete shared occupation/catalogue nodes or rewrite
PostgreSQL history, and never enables serving. Retain its final VERIFIED receipt
with matching `replacement_id` and `job_run_id`.

Activate only after the receipt and independent preservation checks pass:

```sql
SELECT ingestion.activate_jobkorea_replacement(
 'jobkorea-replacement-20261103-4343f52738cc',
 'EXACT_NEW_NCS_TOKEN', 'EXACT_NEW_ONET_PUBLICATION',
 /* exact private VERIFIED graph receipt JSON */ '{}'::jsonb);
```

Replace the final JSON argument with the complete verified receipt. Activation
rejects mismatched file/count/publications/receipt, missing READY source graph,
incomplete NCS status coverage, unsettled O*NET inputs or unknown charges.
SERVING reads only the exact new run and mapping publications. A fresh abstention
cannot inherit an older occupation, even for an unchanged native posting ID.

Verify deployed authenticated list/detail, inferred category/context and bounded
crosswalk APIs. Old-only posting detail must disappear; current JobKorea listing
IDs must equal the 5,482 supplied IDs. Independently verify exact graph cohort,
new association payloads/pins and absence of old associations. Recompare other
source/catalogue graph hashes, protected database evidence and backend user
fingerprints. Public graph/crosswalk caches can retain up to approximately 60
seconds across layers; verify after expiry or a coordinated restart. Measure
cold and repeated API reads under the unchanged five-second catalogue command
timeout. Record actual receipts, costs and deployed state in the handoff only
when verification has completed.

## Interruption and replay

- A LOADING source run resumes from its immutable archive using the exact
  `RESUME_RUN_ID`; do not create a differently composed retry file. A READY
  source run survives graph failure and can be replayed exactly.
- NCS batches are immutable. A finished/partially charged batch is not restarted;
  inspect costs and use a fresh prefix-bound batch for never-sent rows only.
  O*NET `resume --manifest ... --batch-id ...` admits only never-sent inputs with
  settled accounting. Never resend an unknown/charged request automatically.
- A graph failure leaves BLOCKED. Inspect its exact manifest and receipt before
  retry; changed state requires a fresh plan. Retain failed receipts and every
  original hash. Do not bypass fences, disable immutable-history triggers, or
  manually enable serving to recover availability.
- SQL and Neo4j do not share one transaction. The BLOCKED interval plus verified
  graph publication/removal and final PostgreSQL activation is the cutover
  boundary. There is no automatic cross-store rollback.
