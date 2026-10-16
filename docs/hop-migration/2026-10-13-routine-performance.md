# Routine performance follow-up — October 13, 2026

Status: source/replay/temporal proofs completed; the seven-artifact production
rollout and separate readback are VERIFIED at 2026-10-13 05:25:14.054523 UTC. The verified SQL003/037 deployment remains intact. This report
records new SQL008 sealing work, SQL004 existing-proof replay and
500-row posting-date transport, realistic first-backend reads, and a bounded
four-scope first-capture attempt. The separate
[real v3 pilot](2026-10-13-multimatch-pilot.md) completed with four individual
candidate decisions and no new inferred graph publication.

## Scope and isolation

Only the supplied local 8,434-row NDJSON and approved protected PostgreSQL archive
were used. Performance fixtures made no source HTTP, model/provider, paid or
O*NET calls and no production writes. Heavy native work was serialized: the
fresh-seal fixture completed and removed its resources before replay profiling.
Owned PostgreSQL/Neo4j/Hop containers use unique names and one internal network;
PostgreSQL is bounded to 4 GiB/two CPUs. No production cache flush, global planner
tuning or validation weakening is part of these changes.

The replay archive is the protected pre-SQL003/037 rollout backup,
`~/.local/state/jobtology-hop/additive-runtime-applied-873d4893138d44519588e863ebcd2012/database-before.dump`:
935,909,950 bytes, SHA256
`b27bd7ab0afb3f8b2421fa091f4ef1db0aecedcd3279131daf01fc0a941d9cf0`.
Sealed deployed-era baseline graph artifacts are retained at
`~/.local/state/jobtology-hop/routine-replay-work-20261013/baseline/manifest.json`.
The baseline includes exact SQL001/002/003 definitions. Frozen SQL003/037 were
not edited. Candidate graph artifacts and SQL are copied into protected immutable
fixture directories before execution.

## Fresh NDJSON sealing

The fresh-seal investigation found an existing valid primary key on
`ingestion.record(run_id,document_id,locator)`. At the freshly appended checkpoint,
the planner instead selected the partial JobKorea posting lookup with only the
run key, then filtered other locators. A representative lookup used about 8,686
buffer hits for one row; targeted column statistics or a narrow diagnostic index
reduced the lookup to four. The whole-seal control determined the chosen change:

| Supplied 8,434-row checkpoint | Seal wall time |
| --- | ---: |
| Original uninstrumented sealing | 326.291s |
| Preinstalled diagnostic index | 325.937s |
| Statistics-refresh wrapper | 37.241s |
| Final guarded SQL008 | 37.625s |

The index was discarded. SQL008 changes only
`ingestion.seal_jobkorea_ndjson_import(text,text,bigint)`: exact archive, state and
complete checkpoint guards run first, then
`ANALYZE ingestion.record (run_id,document_id,locator)` precedes the first manifest.
READY replay retains its earlier return path. Public validation views/hooks,
NDJSON evidence checks, finalization and READY triggers remain unchanged; SQL003
and SQL037 runtime contracts remain frozen. Append took 31.356s in the final
candidate checkpoint and has no established gain. These are sealing measurements,
not a paired complete `full.hwf` ingestion speedup.

The final paired source oracle preserved physical rows/lines/chunks and semantic
fingerprints, and tested malformed/truncated input, direct READY, future validation
hooks, corruption, serialization, guard drift, replay and the non-MAINTAIN path.
The actual Hop database owner has MAINTAIN permission. Final proof and all child
receipt hashes are in
`~/.local/state/jobtology-hop/seal-checkpoint-f81dce17695f4e67/final-summary.json`.
Owned databases/role/container/volumes were removed. SQL008 SHA256 is
`6cecd227a2bba25e8c0ce20d8ca3cdc80f00f681d2bf1bd8dfb07dba7dad4fec`.

## Realistic first-backend date reads

The approved archive was restored once in 143.534s. Four actual READY, non-SMOKE
scopes with existing source proofs were selected: ALIO organization 355 records,
JOB-ALIO 1,076, JobKorea 8,434 and Nara 13,234. Identical sibling databases retained
restored ingestion statistics or explicitly refreshed them in 2.525s. Autovacuum
was disabled only in that owned profiling fixture so its statistics stayed fixed.
Date count calls ran before source/date content fingerprint reads, using a fresh
backend followed by the same backend again. EXPLAIN retained PostgreSQL execution
and buffers separately from client wall time.

| Actual scope | Restored fresh/reused backend | Analyzed fresh/reused backend |
| --- | ---: | ---: |
| ALIO organization, 355 | 0.029 / 0.002s | 0.031 / 0.002s |
| JOB-ALIO, 1,076 | 0.134 / 0.087s | 0.118 / 0.081s |
| JobKorea, 8,434 | 0.534 / 0.344s | 0.483 / 0.342s |
| Nara, 13,234 | 0.506 / 0.327s | 0.538 / 0.353s |

JobKorea prepared custom/generic calls took approximately 0.35–0.46s in explicitly
already-read states. No meaningful plan-cache penalty was reproduced. These are
SQL count/function calls, excluding Hop payload transport and Neo4j. Restore and
template creation already read data; ANALYZE also reads data. A fresh backend is
not a cold host/cache measurement, and the analyzed comparison does not isolate
statistics from warming. The historical minutes-long date-reader delay was not
reproduced; its earlier reader completion may include downstream processing.
These outer plans do not diagnose internal query causes or the old 84/86-run
capture observations.

The original profiling coordinator was interrupted to correct the candidate's
retention lock ordering. All completed reads/baseline samples remain retained;
old candidate samples are explicitly superseded diagnostics. Its unchanged
frozen candidate files and immutable interrupted checkpoint are in
`~/.local/state/jobtology-hop/replay-reads-9aad86cf7fe84d728d17e002085b02c7/`.
The `interrupted-checkpoint.json` SHA256 is
`5a48a2863f53843da7d419183c7d5a7e38bd40d5746cff89a6d3fece49529fe2`.
The corrected continuation reused the same owned restored databases and did not
repeat restore or first reads.

## Existing-proof replay and first-capture limits

SQL004 acquires `retention.gate()` before reading live READY eligibility or locking
the projection row. Complete immutable record/member counts select one
fresh authoritative captured/live validation before the normal guarded LOADING
update. Absent or incomplete proofs use the exact SQL003 capture body; missing
rows can still be repaired, and wrong values fail the full hashes. Retained
archived proofs remain readback evidence and cannot initiate live replay.

One matched, analyzed SQL AB pair used rollback transactions and exact input/proof
fingerprints:

| Actual scope | SQL003 baseline | Corrected SQL004 |
| --- | ---: | ---: |
| ALIO organization | 0.169s | 0.038s |
| JOB-ALIO | 60s timeout | 23.987s |
| JobKorea | 34.520s | 10.332s |
| Nara | 60s timeout | 60s timeout |

These isolated client wall times are not complete workflow gains. There is one
sample per variant/scope; the Nara scope has no demonstrated improvement.
Corrected SQL004 passed 16 checks for READY/FAILED/LOADING replay, absent/partial
proof repair, changed evidence/member/live values, archived/LOADING run refusal,
active retention, installation drift, proof-row locking, retention blocking and
live absence after the gate. Gate-before-read lock order is reviewed in code;
the blocking test does not reproduce a historical retention race. The passing
scope is sealed separately in
`~/.local/state/jobtology-hop/replay-reads-corrected-6966181f6f874262ad5086d687ef5b93/corrected-replay-oracle.json`,
with hashes linking its failed overall profile and verified resource cleanup.
Corrected SQL004 SHA256 is
`bc4c0f3ef9f72012a0a0cff2844a9ec72b890c4a7710fe9b4ba16718f733e5a1`.

A separate template preserved source/history/statistics and unselected proofs,
then removed only the four selected proof scopes during untimed setup. The new
atomic first capture failed at the Nara begin bound of 180.006s. Protected stderr
confirms statement-timeout cancellation; the existing ON_ERROR_STOP transport
wrapped it as RuntimeError with NULL SQLSTATE. Earlier begin/finish calls took
ALIO 0.302/0.048s, JOB-ALIO 124.714/24.196s and JobKorea 96.594/10.538s, but the
whole open transaction rolled back. **There is no successful four-scope capture
or durable partial-scope proof from this attempt.** Failed samples, raw plans and
receipt `first-capture-four-scopes.json` remain protected beside that corrected
profile. Its unique database and all owned fixture containers/network/volumes/
scratch were removed. No bound increase or identical expensive retry occurred.

The prior successful matched two-scope first capture remains independent evidence:
atomic 86.220s versus per-run 85.934s, one sample each, with exact source/member/
record/projection evidence. Different archived history and scope prohibit
extrapolation to the earlier 84/86-run timings or a transaction-shape cause.

## Complete native replay and bounded date correction

Native-only corrected SQL004/date500 replay completed in the disposable
`jobtology-jobkorea-test-c750e80320b4` fixture. Completed obligations are sealed in
`~/.local/state/jobtology-hop/jobkorea-dry-run-c750e80320b4/combined-native-proof.json`
(SHA256 `dfbf0164ba029876594342b988a2894d395c98e0fbce722e499720683cec6f53`).
The complete matched warm AB pair passed: **207.489s baseline versus 157.364s
candidate**, an observed 24.16% lower wall time, with **one sample per variant**.
This is the complete source-graph `load_snapshot.hwf` for this preserved archive,
not complete file ingestion, a broader throughput guarantee or an additive gain
combined with earlier measurements. Candidate priming was separately 167.120s;
restore 144.338s and explicit ingestion ANALYZE 3.119s were separate.

| Native phase | Baseline | Candidate |
| --- | ---: | ---: |
| Validation | 7.816s | 7.855s |
| Existing-proof capture | 44.008s | 13.971s |
| All writers | 82.730s | 66.046s |
| All verifiers | 49.028s | 45.492s |
| Projection checkpoint | 13.506s | 13.649s |
| Other guards/constraints | 1.515s | 1.447s |
| Startup/orchestration | 8.886s | 8.904s |

The posting-date writer specifically took 37.283s versus 20.816s; its verifier
4.765s versus 0.920s. All six authoritative readers matched 8,434 entity/date rows
and zero source edges. Zero source edges do not establish nonzero source-edge
write throughput. The fixture materialized **5,878 actual archived inferred row
payloads, including 21 reviewed**, plus a separate synthetic sentinel. Exact typed
graph, immutable source/frozen data and inferred edge/endpoint element IDs
matched after both complete replays and the generic wrong-kind rejection/repair.
All real final-date-batch negative and repair checks passed. Every owned fixture
container, anonymous volume, internal network and private scratch directory was
removed, with no cleanup failures.

This fixture performs one matched warm AB pair after separate graph priming and
explicit ingestion ANALYZE. Existing immutable proofs, exact source/frozen data,
typed graph properties and independently counted rows must match. Its actual
archived inferred row payloads are materialized on minimal occupation endpoints
before the snapshot; exact fixture element IDs/properties must survive. This
does not reproduce original production element IDs or the complete NCS graph.
A synthetic sentinel is labeled separately.

Posting-date transport uses UNWIND batches of up to 500 with all-row accounting,
including the real final partial batch. Untimed negative checks require writer
and verifier rejection for the last identity's wrong kind/missing identity,
reject wrong temporal types, repair exact graph state, and test synthetic NULL
input removal of stale scrape properties. Complete native capture measures SQL
plus Hop guards; graph writer/verifier stages combine SQL and Neo4j. Independent
SQL timing cannot be subtracted from native phases.

The original native receipt remains **FAILED and unchanged** (SHA256
`04c8dbff9c13fca44ad14f2c1a0a7739aef9684e22865e7cbee004e1701820a3`). After
both NULL writer/verifier passed, its extra typed-value/NULL predicate returned
uppercase `TRUE`; a lowercase-only benchmark comparison incorrectly rejected
that result. It skipped the final synthetic-node DELETE and final whole-archive
post-date snapshot. The combined proof does **not** claim that skipped archive
snapshot occurred.

The corrected parser accepts `TRUE`/`true` and rejects false/empty values; eight
host regressions passed. A tiny separate internal-network PG/Neo4j/Hop fixture
ran the same unchanged date transport/check blocks with synthetic SQL input,
confirmed typed datetime/date values and removal of stale NULL scrape properties,
then explicitly deleted the synthetic node and matched the complete typed graph
and unrelated inferred fixture edge/endpoint IDs. Its receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-78016c8007bd/receipt.json` (SHA256
`073f3c50a325a9c24461d7eac1fb39f00fe02b69aeb991dd90f58a0c386f200e`). No
archive restore or full replay was repeated for this correction. The combined
proof hashes both unchanged parent evidence and this successful focused proof,
separates their scopes and corrects the parent sentinel's misleading inference
scope description. One earlier tiny setup-only staging failure is retained at
`jobkorea-dry-run-7e9f61fd2379/receipt.json`; it started no containers and was cleaned.

## Verified guarded rollout and remaining work

The fixed seven-artifact performance bundle is SQL004/008, date writer/verifier,
canonical and focused graph installers, and the JobKorea installer. Both graph
installers execute 001/002/003/004 in order; the source installer adds 008 after 007.
`deploy_routine_runtime.py` reuses the reviewed scheduler lock/fence, full backup,
exact runtime publication and transactional SQL/readback mechanism under a new
performance-only operation identity. All old tables/columns/constraints/index
states/triggers, source and legacy/new-v3 facts/reviews/prompts, actual frozen
query scopes and catalogue pins must remain exact. Only the reviewed unused
compatibility helper may remain after behavior rollback; intervening data/schema/
runtime drift refuses rollback. No matching SQL, model calls or graph writer is
part of deployment.

Root reviewed plan
`~/.local/state/jobtology-hop/additive-runtime-plan-3f376c452acd45e781ddae1f4ce95259/manifest.json`
(SHA256 `e5fdd0977242ae9b0de12235066754214c97bad41aa0dae065d806c343d371fa`),
applied the exact seven files and verified at 2026-10-13 05:23:44.230965 UTC,
then invoked separate readback, which passed at **05:25:14.054523 UTC**.
Final receipt is
`~/.local/state/jobtology-hop/additive-runtime-applied-5a7f73fd326e468b8117ef95e38cbe15/receipt.json`
(SHA256 `291c3a88db4a5fea300f8e028ec862afbc560c8c5423c3e238f8397f6c7dc05f`).
Its immutable `apply-verified.json` has SHA256
`6606cf610cbeb35b2042e7a6ae4565a4075aed31dd3a1eb682508ed77ef72ef9`.
The same directory retains `database-before.dump`, 937,258,240 bytes, SHA256
`e38466d8f6d144b100bdbecff6e38d6c2b3df695ff2fd38c19c04cbd99762494`;
its archive listing passed validation. This is not a restore test of that new
backup; earlier owned fixtures restored the prior approved archive.

All 157 preexisting table row fingerprints, exact schema/index states, source
queries, frozen publication query pairs, immutable v3 prompt and four new pilot
candidate decisions were preserved. Only the approved compatibility helper was
added. Historical NCS publication SQL still returns 5,878 rows, including 21
reviewed; the current NCS pair returns one SQL-eligible accepted pilot row. The
aggregate 5,879 SQL outputs are **not 5,879 Neo4j edges**: no new inferred graph
publication occurred. Rollout made no source/model/paid requests or graph writes,
changed no model/provider routing/defaults and removed its owned scheduler fence.
The independent final readback rechecked exact seven artifact bytes and all
preservation fingerprints.

Remaining diagnostics are bounded nested-query profiling on exact Nara run
`9419ffbf-0102-4a44-8c3b-ee28685f1a35` (13,234 records), source-group/history lookup
cost on JOB-ALIO first capture, and the unreproduced historical first-date-reader
delay. Do not repeat all-run 84/86 capture or raise timeouts without new diagnostic
evidence. No overall fresh-ingestion/replay speedup is claimed by combining
separate sealing and source-graph measurements.
