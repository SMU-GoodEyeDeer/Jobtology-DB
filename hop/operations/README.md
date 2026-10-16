# Refreshing the Hop data

The separately authorized O*NET posting matcher uses
[`run_onet_matches.py`](run_onet_matches.py) and the additive `onet_matching`
schema under one $40 combined upstream/router cap. Freeze/dry preparation uses
only retained local source evidence; native Hop executes and publishes the
separate inferred links. The [posting-link report](../../docs/hop-migration/2026-10-14-onet-posting-linking.md)
records the exact source-only cohort, authorization, run commands and current
qualification/production status. Existing NCS contracts and their $5 accounting
scope remain separate.

The adapter supports all seven official sources, including Nara's daily refresh
and recovery of accepted snapshots whose graph checkpoint is missing. See the
[current handoff](../../docs/hop-migration/current-handoff.md) for the latest
verified deployment and run receipts. New
[prefetched job-board sources](../../docs/hop-migration/prefetched-postings.md)
use supplied local datasets only and must not trigger source-site requests.

The separate [O*NET reference catalogue milestone](../../docs/hop-migration/2026-10-14-onet-catalogue.md)
uses a pinned local official bundle and new `classification` schema.
`load_onet_catalogue.py --bundle-dir /protected/bundle --isolated-proof /protected/receipt.json`
holds the existing lock/fence, takes one fresh backup and runs the new native
catalogue installer, load and replay with exact legacy preservation. It stops
before posting matching or LLM calls. Read the report for qualification,
immutable archive, source attribution and failure recovery requirements.

These workflows refresh the separate PostgreSQL `ingestion` schema and its Neo4j
source graph. They do not publish a canonical serving release or run LLM enrichment.
The [LLM workflows](../llm/README.md) are separate, manual entry points with configurable
models, evaluation datasets and explicit request/spend limits.

With the ontology extension installed, successful JOB-ALIO graph checkpoints
also preserve an immutable census of the accepted full snapshot. This uses the
stored API records and makes no additional provider/model calls. It enables the
[posting observation history](../ontology/observations.md); release freezing and
publication remain separate manual steps. Census capture and the graph checkpoint
commit together, including graph-recovery runs. Attachment processing is manual
and is not part of the scheduler; the September 14 resumption and later runs are
recorded in the [linked ingestion history](../../docs/hop-migration/linked-ingestion.md).

| Source | Refresh interval | Workflow for fetching and loading both databases |
|---|---|---|
| ALIO organizations | 30 days | `refresh_alio_organization.hwf` |
| JOB-ALIO postings | 24 hours | `refresh_job_alio.hwf` |
| NCS competencies | 7 days | `refresh_ncs_competency.hwf` |
| NCS qualification mappings | 7 days | `refresh_ncs_qualification.hwf` |
| Q-Net exam schedules | 24 hours | `refresh_qnet_schedule.hwf` |
| NCS career-path CSV | 30 days | `refresh_ncs_career_path.hwf` |
| Nara public-service postings | 24 hours | `refresh_nara_job.hwf` |

Use `reference-local` and Basic logging for these workflow entry points. The inner
pipelines retain their source-specific configurations. Automated refreshes use FULL;
use `ingestions/<source>/full.hwf` when intentionally running an ingestion-only SMOKE.
Private PostgreSQL/Neo4j metadata and the API-key file stay in the mounted Hop config.

The Nara wrapper keeps its ingestion actions in the parent workflow so that
`start_run.hpl` pins `NARA_JOB_RUN_ID` for the subsequent graph load and checkpoint.
It passes that exact ID as `RUN_ID`; it never selects whichever run happens to be
latest after fetching. Each source pipeline uses `nara-job-local`. Use `MODE=FULL`
for the refresh wrapper; success requires both native graph verification and the
durable graph checkpoint. Use the source `full.hwf` for an ingestion-only SMOKE.

Every successful FETCH creates a new source snapshot. Existing accepted runs stay
available. Stable entity identities are merged in Neo4j; historical source records
and exact accepted-run proofs remain in PostgreSQL. Missing jobs or exam sessions in a
later response are absent from that snapshot; absence does not invent a closed or
cancelled status. The current application read interface is:

```sql
SELECT source_id, run_id, created_at FROM ingestion.latest_ready_run;
SELECT * FROM ingestion.current_record WHERE source_id = 'qnet_schedule';

SELECT e.* FROM ingestion.exam_session e
JOIN ingestion.latest_ready_run u USING (run_id)
WHERE u.source_id = 'qnet_schedule';
```

## Isolated performance profiles and focused artifact rollout

`validate_source_proofs.py` is the bounded operational reader for exact retained
source proofs. It runs `ingestion.assert_source_graph_content` once per supplied
run, with two independent PostgreSQL workers by default; `--workers 1` is the
serial control and `--workers 4` is the cap. Supply one to sixteen unique exact
run IDs. Each must have a retained READY non-SMOKE source and a READY captured
proof; archived-only or incomplete proofs are refused. This entry point validates
existing evidence and does not perform capture, import or graph publication.

```bash
python3 hop/operations/validate_source_proofs.py \
  --container EXACT_RUNNING_LOCAL_PG_CONTAINER_ID \
  --run-id EXACT_READY_RUN_ID --run-id ANOTHER_EXACT_READY_RUN_ID \
  --workers 2
```

Connections use the existing local `docker exec`/`psql` path with no public port
or credential argument. The coordinator acquires the canonical exclusive
retention advisory lock in autocommit **before** starting its read-only
REPEATABLE READ transaction, then exports one snapshot shared by all workers.
It refuses active retention and registered writers. It holds that gate until
workers close, so guarded source writers and retention wait while validation
reads run. It does not parallelize writer workflows. Workers use read-only
transactions and session-level SQL parallelism zero; global settings stay intact.

Default statement/lock/validation deadlines are 60/5/300 seconds. Validation
deadline expiry triggers bounded cancellation and cleanup, which adds separate
cleanup overhead. The exporter remains alive through reads; a worker failure or
lost exporter fails the operation, cancels owned peers and skips queued work.
Cancellation identifies owned backends using the operation token, PID and
backend start time, with exact token/database names for bootstrap cleanup.
Server-side worker/exporter absence is verified after transport cleanup. Failed
or unverified cleanup exits nonzero and produces no successful result checksum.
Protected receipts and SQLSTATE-only stderr live under
`~/.local/state/jobtology-hop/source-proof-validation-*/`, outside Git. Successful
receipts contain exact proof identities, ordered results and a deterministic
result checksum; elapsed time covers the full coordinator and cleanup.

The tiny native coordination oracle is
`python3 hop/operations/tests/parallel_validation_native.py --container OWNED_NETWORK_DISABLED_CLONE`.
It creates and removes a unique synthetic database in the shared clone to test
snapshots, retention waits, read-only rejection and failure cleanup. Its synthetic
assertion is not a source-proof semantic or production performance claim.

The [October 14 proof](../../docs/hop-migration/2026-10-14-validation-performance.md)
ran one canonical content assertion for each of four distinct archived ALIO,
JOB-ALIO, JobKorea and Nara runs, with fixed analyzed clone statistics and worker
order 1/2/4 then 4/2/1. All 24 assertions and exact result checksums passed. Mean
complete reader wall times were 36.546/25.838/24.920s and cgroup CPU was
36.499/36.766/36.792 CPU-s. Two workers reduced wall time by 29.30%; four added
only a 3.55% improvement over two, so two remains the default. This measures warm
read-only validation of that supplied workload. The host-only CLI subsequently
passed all four exact live source proofs with two workers in 25.241s, with the
same result checksum and verified worker/exporter cleanup. SQL005 and the two
graph installers are deployed and independently read back; the coordinator
runs from this host checkout. Native workflow limits and the bounded failed
JOB-ALIO first-capture attempt are recorded separately in the report.

The [later JOB-ALIO qualification](../../docs/hop-migration/2026-10-14-jobalio-graph-performance.md)
measures the same complete assertion with SQL006's typed JSONB workset and records
the successful nondurable JOB-ALIO first capture. The wider atomic/per-run
attempts remain failed at separate JobKorea/Nara transition-table comparisons;
their exact rollback is verified. The report tracks native qualification,
deployment and cleanup separately.

`deploy_jobalio_validation_runtime.py` reuses the guarded validation deployer's
scheduler fence, exact backup, fact preservation, publication, separate readback
and rollback. Its fixed coherent bundle contains only SQL006 and the two graph
installers. It permits no added or removed function/ACL identities and no table,
view, trigger, source-proof or enrichment changes. Canonical installers replay
SQL003→004→005→006; SQL006 itself accepts only the exact SQL005 or SQL006 helper
and its original execution metadata.

`deploy_jobalio_graph_runtime.py` is the corresponding fixed five-artifact bundle
when the two owner transport pipelines are also qualified. It adds only
`clear_source_edges.hpl` and `verify_totals.hpl` to that bundle and restricts
allowed function changes to the existing scoped validation helper. The report
records the actual rollout status and preservation receipts.

The 500-row owner candidates passed independent partial-batch/empty-input checks,
full Nara and JOB-ALIO replays and a three-original-line fresh JobKorea regression.
All owned test resources are removed. The first deployment plan refused the
scheduler lock held by a pre-existing JOB-ALIO refresh, which then completed
naturally. Production rollout and separate independent readback are VERIFIED
against the fresh deployment before/after state: all 157 tables/query outputs
match, only the existing scoped validation function changes and the scheduler
fence is absent. The final two-worker live reader passed five snapshots across
four sources in 11.771s, including the newly scheduled JOB-ALIO snapshot; the
original four complete result objects match the earlier proof. All reader and
exporter backends are gone. This larger scope has no paired live speedup claim.

### Capture and source-reader worksets

`deploy_capture_reader_runtime.py` is the fixed four-artifact SQL007/008 rollout.
It publishes only the two migrations and `graph/install.hwf` /
`graph/install_posting_dates.hwf`, and permits only the existing insert-guard,
entity-reader and edge-reader bodies to change. All facts, schema/index state,
execution metadata, catalogue, prompts and inference outputs must remain exact.
It retains the existing scheduler fence, backup, publication and recovery guards;
the CLI acquires `refresh.lock` itself. The [current handoff](../../docs/hop-migration/current-handoff.md)
and [qualified report](../../docs/hop-migration/2026-10-14-capture-reader-performance.md)
record actual deployment status.

The commands below record the qualified SQL007/008 bundle. Canonical installers
now continue through SQL009; use the entity-reader wrapper below for that newer
coherent rollout. Frozen older migrations are not regenerated:

```bash
python3 hop/graph/tools/build_capture_guard_worksets.py
python3 hop/graph/tools/build_reader_worksets.py
python3 hop/graph/tools/build_posting_dates.py
python3 hop/graph/tools/build_batchfree_graph.py
python3 hop/operations/deploy_capture_reader_runtime.py plan \
  --artifact graph/sql/007_capture_guard_worksets.sql \
  --artifact graph/sql/008_reader_worksets.sql \
  --artifact graph/install.hwf --artifact graph/install_posting_dates.hwf \
  --isolated-proof /protected/qualified-native/receipt.json
python3 hop/operations/deploy_capture_reader_runtime.py apply /protected/manifest.json
python3 hop/operations/deploy_capture_reader_runtime.py readback /protected/receipt.json
```

Apply rechecks the exact reviewed plan and proof bytes before mutation. Recovery
uses the same CLI's `rollback` or unchanged-state `abort` with its exact receipt;
intervening state or artifact drift refuses recovery.

`benchmark_graph_readers.py` borrows an explicitly released, analyzed network-none
archive clone; it never restores another clone or connects to production. It
compares four complete typed readers across the fixed Nara, two JOB-ALIO and
JobKorea runs at unchanged 60s statement bounds, with generic plans, JIT off and
session SQL parallelism zero. Its baseline-then-candidate timing is an ordered
diagnostic. `profile_native_graph_costs.py --reader-sql-candidate` instead measures
complete warm Nara replay in baseline/candidate/candidate/baseline order, with
SQL006 and 500-row owner transport fixed on both sides. It temporarily attaches
the same PostgreSQL clone to an owned internal Hop/Neo4j network, then restores
isolation; clone removal remains with its owner. Run these only under sequential
clone leases, using the matching local archive/hash:

```bash
python3 hop/operations/benchmark_graph_readers.py \
  --container OWNED_NETWORK_NONE_ARCHIVE_CLONE --directory /protected/readers
python3 hop/operations/profile_native_graph_costs.py \
  --container OWNED_NETWORK_NONE_ARCHIVE_CLONE \
  --backup /protected/local/database-before.dump --backup-sha256 EXACT_ARCHIVE_SHA256 \
  --reader-sql-candidate hop/graph/sql/007_capture_guard_worksets.sql \
  --reader-sql-candidate hop/graph/sql/008_reader_worksets.sql \
  --local-ndjson /protected/local/composed.ndjson
```

Reader mode freezes both candidate migrations and installer hashes and refuses
transport-comparison options. The optional local NDJSON regression uses three
original lines in an empty temporary database; it proves compatibility, not
whole-file throughput. Neither tool fetches source content or makes model/paid
calls. Capture qualification is rollback-only proof of the supplied four runs;
source-specific diagnostics do not establish global reader or ingestion gains.

### Entity-reader fact worksets

`deploy_entity_reader_runtime.py` permits exactly SQL009 and the two canonical
graph installers. Only `ingestion.graph_source_entities(text)` may change; all
157 protected table fingerprints, complete query outputs, schema/index state,
function execution metadata, catalogue, prompts and inference facts remain exact.
It inherits the existing scheduler fence, fresh backup, byte publication,
independent readback and guarded recovery. The CLI acquires `refresh.lock`.

SQL009 retains one posting-fact row per original run/source/text posting key,
including groups that fall back to the selected row's original normalized data.
Facts and names select separate `DISTINCT ON` winners with their complete original
ordering. Historical eligibility, validity assessments, latest/fallback selection,
name priority and public output columns retain their existing contracts. SQL001→008
remain frozen. Both installers replay SQL001→009 with an abort route after each
migration failure.

```bash
python3 hop/graph/tools/build_reader_fact_worksets.py
python3 hop/graph/tools/build_posting_dates.py
python3 hop/graph/tools/build_batchfree_graph.py
python3 hop/operations/deploy_entity_reader_runtime.py plan \
  --artifact graph/sql/009_reader_fact_worksets.sql \
  --artifact graph/install.hwf --artifact graph/install_posting_dates.hwf \
  --isolated-proof /protected/qualified-native/receipt.json
python3 hop/operations/deploy_entity_reader_runtime.py apply /protected/manifest.json
python3 hop/operations/deploy_entity_reader_runtime.py readback /protected/receipt.json
```

The [entity-reader report](../../docs/hop-migration/2026-10-14-entity-reader-performance.md)
records the VERIFIED SQL009 application/separate readback and successful live
five-snapshot/two-worker proof. Balanced complete warm Nara replay averaged
38.727s versus 36.348s (6.14% lower); JOB-ALIO/JobKorea diagnostic entity times do
not establish a gain. Its schema-only native oracle reuses the immutable preceding
442-check proof and passes 41 new checks covering complete
typed SQL008/009 comparisons, conditional posting merges and fallback behavior,
NULL/duplicate safeguards and exact migration metadata guards. Timings from
different source scopes or failed statements do not establish global throughput.

`profile_archived_postgres.py` restores a supplied local custom-format PostgreSQL
archive into a uniquely named, network-disabled disposable container. It verifies
the supplied SHA256, installs only the two graph SQL contracts in that clone, and
records bounded JSON execution plans, buffers, row estimates, timings, restored
statistics and fresh statistics. A persistent backend measures repeated reads
and parameterized custom/generic prepared plans; statement timeouts remain
recorded samples and do not prevent the later read phases. All receipts, SQL and
plans remain under protected `~/.local/state/jobtology-hop/`, outside Git.
Autovacuum defaults off in the disposable clone to keep explicit statistics
phases controlled; `--autovacuum on` is a separate recorded experiment.

```bash
python3 hop/operations/profile_archived_postgres.py \
  --backup /protected/local/database-before.dump \
  --backup-sha256 EXACT_ARCHIVE_SHA256 \
  --run-id EXACT_READY_RUN_ID --samples 1 --timeout-seconds 30
```

Use `--nested-plans` to retain nested function/trigger plans through session-local
`auto_explain`; its instrumentation adds overhead. Logs stream into protected
files during execution, before Docker log rotation, and drain after container
removal. An early exit or incomplete drain fails the receipt. `--entities` adds source entity
projection. `--capture-dates` captures missing date observations only in the clone.
The optional `--capture-mode per-run` or `--capture-mode atomic` requires no
existing proof for the selected exact runs. Compare those modes using separate
fresh restores of the same archive, SQL hashes, run order and statistics phase;
`--capture-fresh-statistics` explicitly analyzes the clone before proof capture.
Both modes preserve strict proof guards. No full all-run atomic capture is a
default. Initial measured reads follow installation and preservation/validation
checks; restore reads are not host-cold measurements, and later phases have warmed
caches. The earlier first-read and 84-run/86-run capture observations retain their
unresolved causes. This tool alone establishes no production speedup.

`benchmark_archived_routine.py` uses an internal, isolated PG/Neo4j/Hop fixture
and a hash-verified supplied archive. It seals the reviewed graph artifacts,
restores exact baseline function bodies between variants, refreshes ingestion
statistics once, primes the graph, then measures baseline/candidate/candidate/
baseline complete warm replays. Separate selection samples, native stage timings,
reader cardinalities, typed graph hashes and all frozen enrichment rows prevent
an empty or partial workflow from counting as a speedup. Restore, installation,
startup and initial priming are recorded separately. A synthetic inferred edge
checks replay preservation; it does not represent a real inference publication.
Untimed negative checks tamper with a source node, require verifier rejection,
and verify exact repair. Failed samples and cleanup evidence remain private.

Use `--fresh-ingestion-only` with the supplied local NDJSON path, its SHA256 and
row count to measure the complete source `full.hwf` import and READY replay in an
empty fixture. This is a candidate-only measurement with different history from
the archive comparison. Frozen model-input preparation and ontology release are
separate workflows and remain outside this source ingestion measurement.

`benchmark_first_capture.py` requires an older archive with no selected proof,
record evidence or membership. It installs sealed SQL, refreshes statistics once,
then template-clones two identical databases for the exact supplied JobKorea run
and the smallest real READY ALIO run. First backend validation is measured before
fingerprint reads. Atomic capture commits both runs together; per-run capture
commits each complete run separately. The resulting immutable evidence must
match exactly. This representative two-run scope does not establish the cause
or cost of the older 84/86-run observations, and it is not a host-cold cache test.

`benchmark_routine_followup.py` shares one owned archived PG/Neo4j/Hop fixture
between bounded SQL diagnostics and complete native replay. Four real READY
ALIO organization, JOB-ALIO, JobKorea and Nara scopes are selected from existing
immutable proofs. Identical sibling databases preserve source/history/proof data;
one retains restored statistics and one explicitly analyzes ingestion tables.
Date calls use fresh then reused backends before content fingerprint reads;
prepared custom/generic comparisons explicitly follow earlier data reads.
EXPLAIN records server execution/buffers separately from client wall time. No
host cache flush occurs; restore/template creation and ANALYZE read data, so this
does not establish host-cold behavior or isolate statistics causality.

Direct replay runs in rollback transactions with exact source/enrichment/proof
fingerprints. A separate template removes only the four selected proof scopes
during untimed setup, then measures one actual atomic first capture and checks
exact live/captured manifests and preservation of every unselected proof. This
does not repeat the older 84/86-run transaction-shape comparison. Focused queries
have explicit bounds and retain failed/timeout samples.

Use `--baseline-source-sharing --pair-order ab` for deployed SQL003 versus new
SQL004 and date500 transport. `--archived-inference-limit 10000` materializes the
actual archived inferred row payloads on minimal occupation endpoints before
the graph snapshot; this fixture proves its exact inferred edge/node element IDs
and properties survive replay, without claiming the original production IDs or
complete NCS source graph were restored. Date guard checks cover the real final
partial batch, wrong/missing kinds, wrong temporal types, and removal of stale
scrape properties when authoritative input is NULL. Synthetic checks remain
explicitly separate from archived inference preservation.

`prove_date_transport_followup.py --failed-parent PATH` is the bounded native
correction for a parent whose Cypher predicate returned uppercase TRUE but whose
benchmark parser expected lowercase. It preserves the failed parent, checks the
same unchanged temporal/NULL transport blocks in a tiny synthetic fixture,
explicitly removes its node and compares exact typed graph/inferred fixture IDs.
Only completed parent obligations and successful focused postconditions are sealed
in a hash-linked combined proof. It does not claim the parent's skipped final
whole-archive post-date snapshot occurred. See the
[October 13 routine performance report](../../docs/hop-migration/2026-10-13-routine-performance.md)
for completed native measurements, exact receipt paths and bounded timeout limits.

`resume_routine_followup.py` accepts only an explicitly interrupted private owned
fixture/profile identity on its internal network. It preserves the original
frozen candidate path and completed first-read evidence, seals a corrected
candidate at a distinct path, and executes only the remaining analyzed replay,
correctness, first-capture and native phases. Cleanup evidence covers both the
interrupted and final receipts. Superseded candidate samples are diagnostic.

`deploy_routine_runtime.py` coordinates the fixed seven-artifact SQL004/008/date500
bundle using the existing scheduler lock/fence, backup, exact runtime bytes and
transactional SQL/readback mechanism. Plan requires immutable passing isolated
proofs covering every selected artifact. All existing source, legacy and new v3
results/reviews, actual historical/current inference scopes, prompt bytes and
preexisting table schema/index states must match. Only the reviewed compatibility
helper may be added; there are no table or index exceptions. Performance-mode
index fingerprints also bind validity/readiness/liveness, while the prior003/037
coordinator retains its historical manifest contract. Behavior rollback restores
old public functions/runtime bytes and may leave the unused compatibility helper;
any intervening data/schema/runtime drift refuses rollback and retains the fence.

The seven-artifact performance-only production rollout and separate readback
passed at 2026-10-13 05:25:14.054523 UTC: all 157 preexisting tables, exact schema/
index states, source/publication queries and four pilot candidate decisions are
preserved, with no source/model calls or graph writes and the owned fence removed.
Final receipt is protected in
`~/.local/state/jobtology-hop/additive-runtime-applied-5a7f73fd326e468b8117ef95e38cbe15/receipt.json`.
See the [October 13 routine report](../../docs/hop-migration/2026-10-13-routine-performance.md)
for its exact hashes/backup and measurement limits. One latest accepted pilot SQL
output does not represent a new Neo4j publication.

The earlier October 13 isolated checkpoint measured the supplied 8,434-row local snapshot:

| Measured scope | Elapsed wall time | Comparable state |
| --- | --- | --- |
| Warm source-graph ABBA replay | Baseline mean 465.348s; candidate mean 207.600s | Two samples per variant; exact original function bodies, shared refreshed statistics and identical graph/frozen data |
| Candidate fresh `full.hwf` | 609.928s | Empty history; import/READY stage 356.560s; includes source graph and outer export checkpoint |
| Candidate READY `full.hwf` replay | 210.272s | Same supplied file and immutable evidence; actual-type synthetic inferred edge preserved |
| First proof capture for JobKorea + ALIO | Atomic 86.220s; per-run 85.934s | Identical template databases; absent selected proofs; 8,789 records across two real runs |

The 55.39% reduction applies to warm source-graph replay only. Zero selected
source edges do not measure nonzero edge-write throughput. Fresh ingestion is
candidate-only; one atomic/per-run sample each establishes no material gain or
historical first-read cause. Full replay preserves a synthetic
`INFERRED_NCS_OCCUPATION`; the archive sentinel checked a generic unrelated edge.
The fresh measured workflows passed, but removing root-owned raw scratch after
container removal failed. The original failed-cleanup receipt remains unchanged;
a hash-linked `cleanup-recovery.json` records successful exact-scope scratch
removal and cleanup-container absence. The helper now removes such scratch through
the owned Hop container first and returns failure if cleanup fails. Final private
receipt paths, stage timings and rollout status are in the
[current handoff](../../docs/hop-migration/current-handoff.md#routine-follow-up-verified-october-13).

`deploy_additive_runtime.py` is the separate SQL-capable coordinator for the
complete reviewed source-query/v3-matching bundle. Its plan seals all runtime
bytes and proof hashes, old public function/view definitions, PostgreSQL row and
schema fingerprints, current catalogue pins and nonempty historical inference
query scopes. Apply holds `refresh.lock`, owns the existing scheduler fence,
saves exact runtime backups plus a hash-verified full custom archive, and executes
only additive graph003 and LLM037 in one bounded transaction. It publishes the
complete coherent artifact allowlist, verifies legacy query equality and releases
its owned fence only after readback. No graph writer or ingestion is executed.

Behavior rollback refuses new v3 batches or candidate reviews and intervening
drift. It restores exact prior function bodies and runtime bytes while retaining
unused additive helpers, the immutable prompt and empty review table. A failed
runtime restore can be retried from the verified restored-function phase. Before
any SQL or runtime write was attempted, `abort` releases the owned fence only
after exact unchanged-state readback; rollback also uses this path automatically.
Partial or unconfirmed SQL failure stays fenced. Native isolated restore and
workflow proofs remain required; a production backup listing is not a restore
proof. Database-only SQL oracle cleanup is recorded separately from full fixture
container/volume cleanup.

`deploy_performance_runtime.py` provides an artifact-only plan/apply/rollback
route after isolated correctness and timing review. Select each reviewed changed
artifact explicitly from its fixed source/ontology HPL allowlist, with the sole
SQL artifact `retention/sql/000_operations.sql` permitted only when its bytes match
the canonical operations SQL. This SQL file is copied, never executed; keeping it
in sync preserves the function-local JIT guard in future retention installs. It holds the
scheduler host lock, refuses active Hop/source/flat/LLM writers and either pending
migration, verifies the deployed scheduler's existing fence check, and saves exact
original bytes before replacement. Partial failure leaves the durable scheduler
fence owned by its receipt; rollback accepts only exact before/after hashes and
refuses unrelated later drift. It executes no SQL files, installer, source workflow
or graph migration; it runs read-only database prechecks. The receipt's
`executed_sql=false` describes SQL file/migration execution. It does not modify
the scheduler adapter or private metadata.

```bash
python3 hop/operations/deploy_performance_runtime.py plan \
  --artifact graph/load_entity_names.hpl \
  --artifact graph/verify_entity_names.hpl
python3 hop/operations/deploy_performance_runtime.py apply /protected/manifest.json
python3 hop/operations/deploy_performance_runtime.py rollback /protected/receipt.json
```

The historical `reconcile_runtime.py` checks an installer ending at ontology SQL
027 and is unsuitable for this current flat runtime. The larger JobKorea deployer
is a separate full package route. An artifact rollout receipt verifies file
installation only; native graph readback and performance measurements are separate
evidence. Consult the current handoff for which performance artifacts are actually
deployed. Neither tool downloads O*NET or requests job-board/provider content.

For post-rollout read-only smoke, `prepare_performance_readback.py` builds protected
copies of the four current typed ontology property verifiers. Supply the exact
current VERIFIED load, release and Neo4j database IDs; optional `--source-run`
also copies the source entity verifier and checks that its record compatibility
alias has identical SQL/Cypher transforms. Only these private copies accept that
exact VERIFIED token, with current-token/release/database guards. Public active-load
predicates and all typed Cypher remain unchanged. The builder runs no queries or
jobs. Hold `refresh.lock`, require idle runtime, run its protected preflight SQL,
and require the exact current context before executing the copies. Record SQL
owner/property counts and compare native reader output row counts with the
manifest's named expected reader; a successful empty pipeline is insufficient.
Recheck context afterward. Do not run legacy revision verifiers after flattening.
The guarded executor performs these checks, holds the scheduler lock, saves
private Basic logs/timings and requires native reader rows to match the preflight
counts. Native graph-operation input rows must match the same scope; graph output,
result-filter and successful-sink counts must each equal the number of 500-row
batches, including the final partial batch. It rechecks current context and
deployed/private hashes at the end. Omit `--source-run` for an ontology-only
readback when historical source-query timing needs a separate bounded assessment:

```bash
python3 hop/operations/prepare_performance_readback.py \
  --load-id EXACT_CURRENT_VERIFIED_LOAD_ID \
  --release-id EXACT_RELEASE_ID --database-id EXACT_NEO4J_DATABASE_ID \
  --source-run ALL_CHECKPOINTED
python3 hop/operations/prepare_performance_readback.py \
  --execute-manifest /protected/readback/manifest.json \
  --artifact-receipt /protected/performance-runtime-applied/receipt.json
```

## Scheduler and configuration

Install the additive SQL files in this order: `schema.sql`, `reference-support.sql`,
`career-support.sql`, `checks.sql`, `operations.sql`. The source and graph workflows
must already exist in the persistent project mount. Reinstallation preserves rows
and existing refresh-policy overrides.

Goldship's scheduler adapter is `refresh.sh`. It discovers the running containers
from the persistent Hop volume and PostgreSQL container name, takes a host `flock`,
and asks `ingestion.refresh_queue` which operations are due. It invokes native Hop
workflows sequentially. The small Python helper only removes API keys from CLI
output before logs are saved; it performs no ingestion, parsing or database loading.
There are no Python/JavaScript transforms or custom Hop plugins.

The host files are:

- `~/.local/bin/jobtology-hop-refresh`: scheduler adapter.
- `~/.config/jobtology-hop/runtime.env`: container identities, paths and disk limits.
- `~/.local/lib/jobtology-hop/redact_runner.py`: log redactor.
- `~/.local/state/jobtology-hop/`: protected logs and process lock.

A cron entry can invoke `~/.local/bin/jobtology-hop-refresh` every 15 minutes. That
checks elapsed time; it does not download every source every 15 minutes. The
database policy controls intervals and a one-hour retry delay. A newly accepted
upstream snapshot also makes its dependent source due, so partition scope is rebuilt.
Run the adapter
manually to process due work under the same lock. Do not run a second graph writer
in the Hop editor while a scheduled load is running.

This entry is installed on Goldship as of 2026-09-11:

```cron
*/15 * * * * /home/maxjo/.local/bin/jobtology-hop-refresh >> /home/maxjo/.local/state/jobtology-hop/scheduler.log 2>&1 # jobtology-hop-refresh
```

The September adapter deployment recovered three pre-existing graph checkpoints
for its original six sources; see the historical
[deployment verification report](../../docs/hop-migration/live-status.md).
The [current handoff](../../docs/hop-migration/current-handoff.md) records the
seven-source deployment and later recovery/refresh results.

```sql
SELECT * FROM ingestion.refresh_policy ORDER BY source_id;
SELECT * FROM ingestion.refresh_queue ORDER BY priority;
SELECT * FROM ingestion.refresh_execution ORDER BY execution_id DESC LIMIT 20;

-- Pause one source without losing data or changing its workflow.
UPDATE ingestion.refresh_policy SET enabled = false WHERE source_id = 'qnet_schedule';
```

## Quotas, failures and recovery

Each HTTP request reserves quota in PostgreSQL before it is sent. The default is
1,000 requests per source in a rolling 24-hour window, plus the workflow's run cap.
Only this Hop writer's requests are accounted for; other programs sharing a key
must be stopped or their allowance budgeted separately. API requests retain the
existing 200 ms spacing and finite connection/read timeouts. REST pagination and
hidden transport retries are disabled so requests remain countable.

Reservations survive crashes. `RESPONSE_ARCHIVED` means both original bytes and a
manifest were saved. `RESERVED` may mean the request reached the provider but no
response was registered; it still consumes quota. Earlier saved documents are
included during installation; pre-installation transport failures cannot be
reconstructed. Never delete reservations to bypass the provider allowance.

The adapter records each execution durably. After failure it waits at least one
hour before trying that source again. A fetch retry starts a fresh snapshot; it
does not mix old pages with a changing live result set. Partial runs stay outside
`ready_record` and `current_record`. Their raw files remain available for diagnosis.

PostgreSQL READY is the graph recovery checkpoint. If a graph load fails, run
`export_pending.hwf` with the exact `RUN_ID`; the scheduler chooses the same recovery
path automatically for the latest accepted run. It reuses PostgreSQL data and makes
no provider requests. `graph_export` records only a successful verified graph load.
A crash between graph completion and checkpoint insertion causes a safe repeated
graph load. The graph loader validates immutable facts and relationship counts.
This recovery applies to Nara as well: a queued GRAPH operation runs
`export_pending.hwf` with its exact READY run ID before a later FETCH can create a
fresh snapshot. Repeated successful recovery merges the same graph identities and
updates the single checkpoint row for that run. A graph or checkpoint failure
leaves PostgreSQL READY data available for retry.

```sql
SELECT source_id, outcome, count(*)
FROM ingestion.request_attempt
WHERE reserved_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
GROUP BY source_id, outcome;

SELECT u.source_id, u.run_id, u.state, g.exported_at
FROM ingestion.latest_ready_run u LEFT JOIN ingestion.graph_export g USING (run_id);

SELECT * FROM ingestion.validation_issue WHERE run_id = '<run-id>';
SELECT * FROM ingestion.reference_scope_issue WHERE run_id = '<run-id>';
```

The scheduler checks the actual raw-volume filesystem before each source: at least
100 GiB must remain and usage must be below 85%. It never deletes snapshots
automatically. Responses are rejected after download if they exceed 64 MiB. Native
REST buffers a response, so this is **not a streaming memory/response-size limit**
([REST Client behavior](https://hop.apache.org/manual/latest/pipeline/transforms/rest.html)).
Direct editor runs also bypass the host disk check and process lock; the request
ledger and source validators still apply.

## Boundaries of this migration

All seven official source types have native ingestion workflows. The batch-free
Neo4j contract keeps source business entities and direct relationships in STAGING;
PostgreSQL retains immutable import history and reconstruction evidence. The separate canonical/evidence-store
contracts and future application query model remain application-design decisions; no backend
application currently needs a cutover.
JOB-ALIO's broad NCS category codes do not establish required competency units;
the separate LLM workflows propose evidence-backed duty alignments and publish only reviewed
ENRICH results. They are not invoked by this source scheduler.

The career CSV URL is pinned. Monthly checks can detect changes to that artifact,
but they do not discover a newly published replacement download identifier.

## Manual retention maintenance

[Manual retention workflows](../retention/README.md) preview and prune eligible source snapshots. While a cleanup plan is ACTIVE, `ingestion.maintenance_active()` suppresses the refresh queue and write guards prevent races. A failed cleanup keeps this pause until its exact plan is resumed and completed. No scheduled deletion was added. See the [server runbook](../../docs/hop-migration/server-runbook.md) for container discovery and mounted paths.

## Permanent batch-free graph migration

`migrate_batchfree_graph.py` coordinates the one-time transition under the existing
`refresh.lock`. Do not wrap it in another `flock`: it acquires the lock itself.
The helper reads only the deployed private native Hop connections. Its reachable
workflows install SQL and project accepted PostgreSQL evidence; none fetch source
content, reserve model requests or call a model.

Plan captures exact public file hashes, source run/checkpoint scope, protected
PostgreSQL fingerprints and all graph nodes/relationships. Typed signatures keep
every existing business element ID, label, property value/type, posting date and
NCS edge verifiable. Each native snapshot query returns at most 5,000 objects;
the reviewed default rejects more than 2,000,000 nodes or relationships. Separate
ID-only boundary reads avoid repeatedly sorting the entire property projection.
PostgreSQL graph evidence streams once per projection into protected SQLite.
Removal fails on an unexpected label/attachment, an unbacked run/record/reference
or a changed business value.

Run from the repository root, substituting exact protected receipt paths:

```bash
python3 hop/operations/migrate_batchfree_graph.py plan \
  --preflight '/protected/batchfree-preflight/receipt.json'
python3 hop/operations/migrate_batchfree_graph.py apply \
  '/protected/batchfree-plan/manifest.json' \
  --backup-restore-proof '/protected/batchfree-backup-restore/receipt.json'
```

The optional preflight must be `VERIFIED_READ_ONLY_PREFLIGHT` for the exact
runtime; apply still checks a fresh typed graph against it. Without `--preflight`,
plan creates its own snapshot. Apply requires an actual isolated PostgreSQL
restore proof whose backup SHA256 equals the retained full custom-format dump.
The proof records `VERIFIED`/`PASSED` and `database_backup_sha256`; archive listing
alone does not satisfy this restore gate.

Apply exports typed, checksum-bound scaffold recovery statements before changing
writers. It deploys the fixed allowlist and installs only graph SQL 002, LLM SQL
036 and retention SQL 002. The bulk projection captures every historical
checkpoint's immutable PostgreSQL membership and writes current business entities
once. Existing source imports, raw evidence, frozen model bindings, cost and
review rows stay exact. The new `retention.plan_run.source_projection_verified`
column is the only normalized historical row-shape exception: all older fields
and rows remain fingerprinted, and every historical new flag must remain false.

After direct projection and preservation checks, one native removal pipeline
executes explicit transactions of at most 200 allowlisted scaffold nodes. It
deletes only `ingestionBatch`/`ingestionRecord` and their backed `HAS_RECORD` and
`REFERS_TO` attachments. It uses no `DETACH DELETE` and creates no `archivedRecord`
substitute. A no-source, no-model replay of an exact historical Q-Net source run
then proves future loading does not recreate scaffolding; the final full typed
snapshot independently checks business IDs/values/links and posting dates.

The host adapter honors `batchfree-migration.pending` in its private state
directory. Apply creates this durable scheduler fence before switching writers;
it clears the fence only after final verification. A failed or disconnected
operation leaves the fence and protected append-only stage events, original
artifact backups, full database dump and exact scaffold recovery export intact.
Inspect the receipt before using either recovery command:

```bash
python3 hop/operations/migrate_batchfree_graph.py resume \
  '/protected/batchfree-apply/receipt.json'
python3 hop/operations/migrate_batchfree_graph.py recover \
  '/protected/batchfree-apply/receipt.json'
```

Resume validates the original manifest and business evidence, captures the exact
remaining removal scope, and continues safely after a partial deletion. Recovery
restores scaffold stable IDs, labels, typed properties, memberships and references
from the retained export; Neo4j allocates new internal element IDs for the restored
scaffold nodes/edges. Business element IDs remain unchanged. Recovery leaves the
migration fence active and keeps the permanent batch-free writers installed; an
operator can then resume the verified migration. Do not manually remove the fence
or restart an old graph writer after a partial failure.

Old scaffold uniqueness constraints may remain as inert schema definitions. The
bounded helper does not drop business schema or perform storage retention. The
[current handoff](../../docs/hop-migration/current-handoff.md) is authoritative for
the actual deployment status, production receipt and verified cardinalities.

## Flattening the approved ontology projection

`migrate_flat_ontology_graph.py` migrates only the exact approved, sealed
`SOURCE_ONLY` catalogue. Its plan captures every existing PostgreSQL application
table, catalogue approval/load/reader output and preview export, and a full typed
Neo4j snapshot. It rejects revisions or canonical shells without exact sealed
PostgreSQL backing, duplicate stable IDs, unexpected labels, and unaccounted
attachments. Plan and apply use the scheduler's `refresh.lock`; a coordinator
calling their Python functions must hold that lock once and must not nest the CLI.

```sh
python3 hop/operations/migrate_flat_ontology_graph.py plan \
  --release-id ontology-catalog-source-20261001
python3 hop/operations/migrate_flat_ontology_graph.py run \
  --reviewed-manifest /protected/path/manifest.json \
  --release-id ontology-catalog-source-20261001
python3 hop/operations/migrate_flat_ontology_graph.py apply /protected/path/manifest.json
python3 hop/operations/migrate_flat_ontology_graph.py resume /protected/path/receipt.json
python3 hop/operations/migrate_flat_ontology_graph.py recover /protected/path/receipt.json
```

For a production cutover, `run --reviewed-manifest` holds one lock across a fresh
plan, exact cutover backup/isolated restore and apply. It binds the reviewed desired
artifact hashes while allowing a new source refresh baseline to be captured before
any writes. An interrupted apply retains its standard private receipt for `resume`
or `recover`. Separate `plan` and `apply` commands independently recheck freshness.

All manifests, receipts, snapshots, full database dumps and typed recovery exports
are private files beneath `~/.local/state/jobtology-hop/`. The printed receipt path
is the operator's review point; failure reasons are recorded there. Apply requires
an actual isolated, network-disabled restore of the exact cutover dump with every
old table and function/trigger definition verified. It performs that restore when
no proof is supplied. `--backup-restore-proof /protected/path/receipt.json` can reuse
an exact verified proof with matching dump hash, table fingerprints, definitions
and confirmed disposable-resource cleanup. `plan --preflight` accepts only a
`VERIFIED_FLAT_PREFLIGHT` receipt for the exact runtime/release and unchanged
PostgreSQL/catalogue baseline.

The focused runtime installer executes only ontology SQL migrations 028 and 029.
The deployed normal and historical release writers use the flat contract;
retired revision writers cannot acquire a PostgreSQL token. Existing source,
revision, graph-load, approval, frozen-input, accounting and review rows remain
unchanged. Canonical shell identity properties and all unrelated graph values,
node/relationship element IDs, source posting dates and inferred NCS links remain
exact. Only sealed PostgreSQL-owned canonical fields and accounted rerouted
ontology relationships may change.

Staging verifies the flat projection and exact old revision remnants but retains
its writer lease and keeps catalogue readers closed. Removal streams protected
queries in one Hop process, explicitly deletes only proven attachments and then
their revision, and checks typed values, labels, endpoints and attachment scope in
each transaction. It never uses `DETACH DELETE`. Finalization independently
requires the full flat inventory and zero revisions. A normal historical replay,
full typed preservation snapshot, old PostgreSQL fingerprints and unchanged
catalogue readers/exports must pass before the durable
`flat-ontology-migration.pending` scheduler fence is removed.

Interrupted deletion resumes from a fresh snapshot and the exact `STAGED` token.
A failed strict reload with no revisions retries only after independent flat-state
proof. Recovery removes only proved new rerouted edges, restores canonical typed
before-values and the old revision labels/properties/attachments, and verifies the
original graph by stable IDs. Neo4j allocates new internal element IDs for restored
revisions and removed attachments; unrelated business element IDs remain exact.
Recovery keeps the durable scheduler fence and catalogue readers closed, fails the
exact old flat token, and requires a new verified stage before retry. It refuses
rollback of an already `VERIFIED` serving checkpoint before graph writes.

An interrupted stage before revision removal may use the restricted six-pipeline
successor path after the coordinator stops its owned native process. `amend`
requires native and database quiescence, the durable fence, a successful isolated
native proof, all original revisions and attachments, exact unaffected business
values, every expected flat edge, and all old PostgreSQL rows. Only new rerouted
edge properties may be incomplete; any present array must be an exact typed,
ordered prefix. The original manifest and recovery evidence remain immutable.

```sh
python3 hop/operations/migrate_flat_ontology_graph.py amend /protected/path/receipt.json \
  --candidate-dir /protected/path/candidate_bundle \
  --validation-proof /protected/path/successor-native-proof.json
python3 hop/operations/migrate_flat_ontology_graph.py amend-resume /protected/path/receipt.json
```

The successor is limited to the six scalar/array edge-property writers and
verifiers, replacing only endpoint lookup with two explicit index seeks. It seals
an append-only amendment, atomically deploys each proven file, and fails only the
owned interrupted token. It keeps readers and the scheduler fenced. An incomplete
amendment requires `amend-resume`; ordinary `resume` refuses it. Once the amendment
is verified, publish those exact six files and their corresponding generator in
the repository before ordinary `resume`, which rechecks repository/deployment
agreement and repeats the normal staging, removal, preservation and final gates.
The commands acquire `refresh.lock` themselves; do not wrap them in another lock.
