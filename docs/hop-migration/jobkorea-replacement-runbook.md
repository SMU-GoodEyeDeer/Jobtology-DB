# Explicit JobKorea cohort replacement

Prepared **2026-11-03 KST**. This is an operator procedure and repository
qualification record, not a claim that production replacement has completed.
The [current handoff](current-handoff.md) remains authoritative for live state.

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
   graph SQL009 replay fence. SQL037 originally qualified at SHA256
   `38c602dc4053b50aceb7e3ceada105a121bce718b0d1c13c46be289fb2855597`.
   Verify installed bytes and function bodies. Run reader grants using the
   current grant script; replacement tables/helpers must stay private. Do not
   replay old individual reader migrations after SQL037: they replace its
   fences. Full canonical installer replay needs a reader maintenance window
   and SQL037 must execute last.
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
