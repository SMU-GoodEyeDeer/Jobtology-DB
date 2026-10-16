# Capture and source-reader performance — October 14, 2026

Status: **VERIFIED** production deployment and separate independent readback of
SQL007/008 and both installers. Four-source nondurable first capture, the
442-check semantic oracle, exact typed SQL readers, balanced warm Nara replay
and full JOB-ALIO compatibility passed. Live five-snapshot validation passed;
all owned test resources are removed. The earlier [SQL006 and owner transport
report](2026-10-14-jobalio-graph-performance.md) records the preceding checkpoint;
SQL006 and owner500 bytes remain exact.

## Fixed fixture and runtime scope

Only the supplied local archives and frozen source evidence are used. No source
HTTP, model/provider request, paid call, O*NET import or production graph write
is part of this qualification. The one PostgreSQL 18 clone was
`jobtology-routine-archive-nara-c2c27d69f5ed`, with network `none`, 6 GiB memory
and a four-logical-CPU-equivalent quota. The quota does not pin physical cores.
Its explicitly analyzed ingestion statistics have SHA256
`18c0776d916781eb01179396f053adfb567e37439750385b61f6ed5d3b7a3810`.
SQL qualification and native work use sequential leases on this same restore.

Initial preflight failed because a temporary harness called a nonexistent fast
path helper. It failed before ANALYZE or timing. The continuation reused the
same actual Docker ID and restored archive, checked the existing canonical
query-contract assertion, analyzed once and verified all five original/live
manifests. Its original FAILED receipt is preserved separately.

The restored 943,409,053-byte archive is
`~/.local/state/jobtology-hop/additive-runtime-applied-35a0f654b8a844d4a22ac39d94673dad/database-before.dump`,
SHA256 `a52b85a31b8ba5b1e844558ab1bbbbbfd810e36c7034e1fad045cda8a8ea2c24`.
All frozen SQL003/004/005/006, JobKorea SQL008 and LLM SQL037 bytes are retained.
There are no new runtime functions, tables, indexes or parallel-safety changes.

SQL007 replaces only `ingestion.source_graph_insert_guard()`. It groups the
`UNION ALL` of inserted and live complete-row JSONB by the original SQL join
keys. Groups containing inserted rows reject missing live rows, unequal live
duplicates or NULL join keys. Equal duplicates remain accepted; unrelated live
rows remain irrelevant. Each exact run retains its independent validity gate,
and transition tables retain their post-insert visibility.

SQL008 replaces only `ingestion.graph_source_edges(text)` and
`ingestion.graph_source_entities(text)`. The eleven original reference branches
become separate `UNION ALL` scans with the same source predicates, identity
hashing, text extraction and NULL gates. Posting IDs and representations are
projected once as the same `->>` text keys. Historical eligibility, validity
assessments, latest/fallback choices, separate name priorities, endpoint closure,
proof fields and public result columns stay unchanged. Existing validation
requires unique JOB-ALIO list/detail forms and unique active Nara resource forms;
inactive Nara postings cannot carry those resource forms. The scalar joins do
not introduce a new duplicate-form winner policy.

Both migrations accept only their exact sealed baseline or candidate bodies and
preserve execution metadata, including cost, rows, support and signatures.
SQL007 also accepts two exact observed Hop comment-elided forms described below;
it performs no broad normalization of installed function bodies.
Canonical installers replay SQL001→002→003→004→005→006→007→008, with an abort
route for every migration failure. `deploy_capture_reader_runtime.py` permits
exactly the two migrations and two installers and exactly the three existing
function bodies. Its additional `pg_proc` fingerprint excludes only `prosrc`,
so approved body permission cannot exempt execution metadata from preservation.
All existing scheduler, backup, schema/index, row, catalogue, prompt, inference
and query-output guards remain active.

## Complete first capture

All sixteen begin/finish calls passed at the unchanged 60-second statement
bound: first one atomic transaction covering the four exact source runs, then
four independent transactions. Every source reached READY with its original,
newly captured and live full manifests equal. Each transaction rolled back;
all 59 selected ingestion/enrichment table fingerprints and complete projection
timestamps returned exactly. Fixed statistics remained exact, and recorded CPU
throttling was zero. This is successful nondurable capture proof, not a new
durable production capture or a whole-history capture.

| Source | Atomic begin / finish | Per-run begin / finish | Records / references |
| --- | ---: | ---: | ---: |
| ALIO | 0.211 / 0.034s | 0.191 / 0.032s | 355 / 355 |
| JOB-ALIO | 4.006 / 0.804s | 4.021 / 0.807s | 1,076 / 2,152 |
| JobKorea | 52.004 / 10.409s | 51.373 / 10.240s | 8,434 / 8,434 |
| Nara | 17.023 / 4.615s | 17.122 / 4.667s | 13,234 / 13,234 |

The sums of measured begin/finish calls are 89.107s atomic and 88.455s per-run.
These exclude separate manifest/fingerprint assertions and are not complete
coordinator times. Earlier full-capture baselines reached their 60s bounds and
remain immutable failed evidence; no numeric full-capture speedup ratio is
available. JobKorea's successful begin remains near its bound.

Separate 64-row real-trigger ABBA controls also passed with exact rollback.
Mean JobKorea membership-insert time was 8.408s baseline versus 8.074s candidate;
mean Nara record-evidence insertion was 1.181s versus 1.014s. These include the
unchanged validity gate and do not establish full-size throughput.

## Complete SQL reader diagnostics

One persistent backend used generic plans, JIT off and session SQL parallelism
zero, with unchanged analyzed statistics and 60s statement bounds. The ordered
baseline-then-candidate diagnostic checked four readers for Nara, the original
JOB-ALIO run, the newer JOB-ALIO run and JobKorea. All sixteen complete typed
result pairs match, with exact hashes for all 32 saved result files. This is an
ordered diagnostic, not a balanced SQL timing experiment; the final native
comparison measures complete replay separately.

| Scope | Entities baseline / candidate | Edges baseline / candidate | Owners baseline / candidate |
| --- | ---: | ---: | ---: |
| Nara | 17.144 / 6.110s | 10.778 / 1.043s | 13.935 / 4.161s |
| Original JOB-ALIO | 26.311 / 26.556s | 21.608 / 20.894s | 24.466 / 23.502s |
| Newer JOB-ALIO | 28.245 / 26.054s | 21.029 / 20.349s | 23.884 / 23.489s |
| JobKorea | 18.119 / 18.582s | 8.551 / 1.173s | 11.808 / 4.160s |

Nara's posting-date reader measured 0.545s in both variants. JOB-ALIO and
JobKorea entity times show no established gain. No global reader-speedup or
whole-ingestion claim follows from this source-specific series.

Candidate Nara plans removed memoization of complete normalized JSON records;
an independent small `(run_id,document_id)` Memoize remains. Instrumented
execution measured 5.523s for entities and 1.056s for empty edges, excluding
PL/pgSQL preconditions. Historical worksets still contain 103,037 references;
the scalar posting-key join still rejects 5,963,010 pairs. Those residual joins
and JOB-ALIO historical validity/entity cost remain measured follow-up work.
No historical eligibility is narrowed to obtain these results.

## Balanced complete native Nara replay

The canonical Hop source/date installers passed with the corrected SQL007 guard.
After separate priming, complete warm replay ran in baseline/candidate/candidate/
baseline order, with SQL006 and 500-row owner transport fixed on both sides.
Basic native logs were recorded; no concurrent profiling or nested-plan
instrumentation ran during timing. Statistics and the same borrowed PostgreSQL
container remained exact.

| Warm replay | Baseline 1 | Candidate 1 | Candidate 2 | Baseline 2 |
| --- | ---: | ---: | ---: | ---: |
| Complete wall time | 101.627s | 38.400s | 38.337s | 99.325s |

The two-sample means are **100.476s baseline versus 38.369s candidate, 61.81%
lower**. Native pipeline means fell from 91.825s to 29.606s; writing from 45.747s
to 14.245s and verification from 41.681s to 10.922s. These stages overlap with
separate process measurements and cannot be subtracted to infer other costs.
This gain applies to complete warm Nara replay of the supplied archive; it is
not a fresh import, global reader gain or production capacity measurement.

All 157 protected table fingerprints and source proof remain exact. The typed
graph retains 10,555 entities, zero source edges, 10,555 owners and 10,555 posting
dates, including exact preservation of the separate synthetic inferred-edge
sentinel. Independent owner-boundary checks also passed.

The three-original-line fresh JobKorea import and replay passed in an empty
temporary database: READY, zero issues, three records, zero requests and equal
proofs. Its 8,169-byte subset has SHA256
`fb831d1637d6849502100fb34a1ab5a88fa05ed4c915e2bce4f8f2a311faa5c8`.
This is functional compatibility rather than whole-file throughput. The fresh
database and owned native resources were removed; the original PostgreSQL
container, timeout and network-none isolation were restored before its owner's
final audit and removal.

A separate full JOB-ALIO candidate replay passed with 673 entities, 538 real
source relationships, 538 owners and 538 posting dates. Original/live source
proofs remain equal at 1,076 records and 2,152 references, SHA256
`4ca210281e8e46700d8301dc156b85e338b75a78f307a3a2d6af8d805e22a74b`.
Complete typed graph evidence, synthetic inferred IDs/properties and all 157
protected table fingerprints match. Prime/warm times were 174.154/169.063s;
this is functional compatibility with real edges, without a paired JOB-ALIO
speedup claim. The inference check preserves a synthetic sentinel; it does not
claim recreation of the complete production inferred graph.

## Independent semantic evidence

The final frozen schema-only oracle passed 442 checks and removed its
temporary database. It retains the earlier 308 cases and adds real native
transition-table trigger tests, complete reference-bag comparisons with
`EXCEPT ALL`, old pinned `ALL_CHECKPOINTED` behavior and missing-run refusals.
Guard cases include equal/conflicting live and inserted duplicates, partial
missing live evidence, extra live evidence, empty transitions, multiple runs,
NULL keys, whole-row payload changes, JSON types/array ordering and post-insert
live-view behavior. Standalone migration tests reject unknown bodies and
execution-metadata drift.

An initial oracle expectation incorrectly required rejection of a SQL NULL
JSONB column versus a JSONB literal null. Complete-row `to_jsonb` serializes
both to the same property value, so the original guard accepts them. The
expectation was corrected to preserve that canonical behavior; runtime bytes
were unchanged. The original FAILED receipt and its 349 successful checks
remain immutable, and its temporary database was removed. This differs from
SQL006's extracted missing-field versus JSON-null comparisons.

The final frozen continuation adds complete typed-output historical cases for
numeric/string posting keys, unselected newer documents, blank authoritative
names and timestamp ties. All pass, including explicit independent expectations
for text-key merging and exclusion of unselected newer evidence. The 22 frozen
launch inputs match their recorded hashes. The later SQL007 installation-guard
compatibility revision preserves its qualified function definition byte for
byte. The clone was released at `2026-10-13T18:49:01.757477Z` with exact original
statistics and verified absence of temporary databases or fixture objects. An earlier corrected
436-check pass is preserved separately; overlapping test counts are not summed.

## Native installer compatibility correction

The first native attempt `jobkorea-dry-run-1490b1854111` failed before replay at
SQL007's strict baseline-body guard. Hop's SQL action removes exactly four
whole-line comments from SQL002's function body while retaining one-space blank
lines. Its observed MD5 is `6a7657e4685d2741814d77453466eeab`; the raw baseline
is `7bf7a02ce5d39bc3ae14e5617f5595a3`. Execution metadata remained exact. All
157 table fingerprints and fixed statistics were verified after the failure;
native resources, timeout settings and network isolation were restored. The
failed receipt is preserved.

The reviewed guard-only correction accepts four exact hashes: raw and Hop forms
of the sealed old/new bodies. The generator removes only the four specified
comment texts when deriving those hashes and refuses missing/duplicate anchors.
Installed bodies are still checked by exact MD5. No executable statement,
metadata guard or SQL008 byte changed; the 442 semantic checks and complete
capture remain proof of these unchanged function bodies.

A separate frozen schema-only native oracle passed 13 compatibility checks:
all four exact forms and reinstallation pass, while unknown comments, partial
comment removal, blank-line trimming, a changed return statement and cost drift
are refused. The qualified definition was compared byte for byte with the
earlier semantic launch. Its temporary database was removed, original statistics
remained exact and the clone was released for native work at
`2026-10-13T19:08:02.655167Z`.

## Final owned-resource cleanup

The clone owner's final read-only audit verified unchanged statistics, all five
captured/live source manifests, protected source/enrichment rows and captured
proof values, with only the established projection replay timestamps excluded.
Only the original four PostgreSQL databases remained and no other client backend
was present. The same actual container ID and recorded volume were then removed.
Independent checks against a reachable Docker daemon confirmed their absence
and absence of all 18 recorded native resources. The PostgreSQL log follower
drained naturally with exit code zero. All temporary databases are removed;
the initial FAILED preflight receipt remains byte-exact.

## Production rollout

The fixed four-artifact plan passed. Guarded application reached
`VERIFIED_ADDITIVE_RUNTIME` at `2026-10-13T19:47:16.866746Z`, with the scheduler
fence removed. Fresh before/after rows, complete query outputs and catalogue
context match. All 157 protected table fingerprints, schema/index state, prompts
and frozen matching outputs remain exact. All 460 existing function execution-
metadata entries match; only the three approved existing function bodies change.
Separate independent readback passed at `2026-10-13T19:48:54.064568Z`.
Nine older frozen artifacts match their local and deployed bytes.

The live two-worker read-only reader passed five snapshots across four sources
in **11.615136s**, finishing at `2026-10-13T19:49:12.732312Z`. Its complete result
SHA256 is `d0202676c7bf01a99f290e625c3909664a6245ff6dbf05b905f6c9b8aec38636`,
equal to the preceding five-snapshot proof. Actual worker and all operation
backend absence is verified. This is live compatibility evidence; it does not
establish a paired live speedup. No source HTTP, provider/paid call or production
Neo4j write occurred.

The fresh full custom-format backup is 943,410,518 bytes, SHA256
`060f5e3e2ee11447e2d30ee8518828e3eb559bc3ac840f92d28e52096b53fae9`.
Its validated archive listing is a recovery artifact, not another isolated
restore qualification.

## Deployed artifacts and protected receipts

| Runtime artifact under `hop/` | SHA256 |
| --- | --- |
| `graph/sql/007_capture_guard_worksets.sql` | `8e435feea0c38e4c6ed1e44ec90545540dc23d74bdada4b872dd8eab088f9b71` |
| `graph/sql/008_reader_worksets.sql` | `f1b71d6bce9f2b59d61b9c3122a81954f24db312de77c7b830bb9aa55676a645` |
| `graph/install.hwf` | `8b45b2b9fd1d03f78516479dce231a49fc794c86e755727a5c48e223f1eb081b` |
| `graph/install_posting_dates.hwf` | `630c3c2916172276668e94cbdcf90e3226a64ddd78653f2529b3a97a1c400315` |

Protected SQL evidence root:
`~/.local/state/jobtology-hop/capture-worksets-c2c27d69f5ed486fa3fa51f0348a9974/`.
Launch copies, raw statements and logs stay outside Git.

| Receipt relative to that root | SHA256 |
| --- | --- |
| `initial-preflight-failed.json` — nonexistent harness helper, FAILED | `cc21e1e0a0daab0cb48999b25c49bd7771fc711daad9ec133a45124f82f229a2` |
| `clone-preflight.json` — resumed same restore, READY | `06d0c6387c282576be262e11b3d0740a5ea932ee473584d1b764274f3687a7dd` |
| `narrow-guards/receipt.json` — 64-row ABBA controls PASSED | `a184296a91a34e541ca5b6a1ce33b11bd64953085d44d660fbef4851109148ab` |
| `candidate-full-capture/receipt.json` — four-source atomic/per-run capture PASSED | `1762d146471195171bcf13cb3c1edf00c66447ddbaee51881ff7857df68fbbb3` |
| `capture-qualification.json` | `cd490da848e3ffaf85d636fef9786fb73a8cb62149694481646915afe4383501` |
| `reviewer-oracle/receipt.json` — original checker FAILED | `229c5a2c0ec0a6618d1ee8a45c3a4987dd17e07fd751defc4aac1048dd642a1b` |
| `reviewer-frozen-oracle/receipt.json` — corrected 436 checks PASSED | `2053dac32f2d9db9aa35fd0dd90ffe36cd2b0af400cfc8d2c7dc98c0867b9988` |
| `reviewer-final-oracle/receipt.json` — final 442 checks PASSED | `947d6a104184ec36bbfe3a7b9ec35974ce5976aba2de864d671c041aaa1d0bac` |
| `reviewer-final-frozen-launch-binding.json` | `b33235ce385835bf83aa74af12ab44d9e4e979db0ba47a60c0ebe95ce9b90d4d` |
| `reviewer-oracle-release.json` | `46cf65591824937c7470f2a51ab97e2d4f36b951fa582a66c7c29bed2740be47` |
| `native-guard-compatibility.json` — guard-only bridge to earlier proofs | `ec0ea814c540ed99458a8b831bad3350f0dc4c363c66ce810a1465ae461dea1b` |
| `guard-compatibility-oracle/receipt.json` — 13 native checks PASSED | `c31e592f9cf5067244d90386722fdac9fa6bfec49803abc505fbae68fb097b78` |
| `guard-compatibility-release.json` | `d92ae388c5f81a89df7a0ae08a24e558f82f7d982d99f7c5434aeafbb2d0563f` |
| `owner-return-audit/receipt.json` — final source/statistics audit PASSED | `312b5f15149af24c094c46bd513ec299439a9499903822b30068d59b785e7ca0` |
| `owner-final.json` — exact clone and volume removed | `9425edd88dab2e781660544c1efef48630a057d27fb776157e0130d3981bdd89` |
| `independent-cleanup.json` — resource absence and natural log drain PASSED | `4e24488118602d7073b79e241f6ab2d54afb73531b102526baf2eeb15c91830f` |

The preserved failed native receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-1490b1854111/receipt.json`, SHA256
`9325870bcf245ad48267cb44719f5c7845e08c2725b5f1b78c911ac0bbc931fc`.
Its `failed-installer-preservation.json` is SHA256
`f8c3c1835605be040dac98c2f9757b65e612f03ffd1c2f95259879e7b4cdb2ed`.

The independent reader diagnostic receipt is
`~/.local/state/jobtology-hop/reader-worksets-c2c27d69f5ed/receipt.json`, SHA256
`f91a4cd46b6d23e354ba76e48a650556487fa137c9217799f82fd4bc3f2c128f`.

The immutable Nara acceptance receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-def7c40b34e7/receipt-precleanup-completed.json`,
SHA256 `7d150da43240727b98d09a0d369ea79855f917da853b1bb1e2395bc8b37636ea`.
Its preserved precleanup status is
`PASSED_NATIVE_GRAPH_COSTS_PENDING_BORROWED_CLEANUP`.

The immutable JOB-ALIO compatibility receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-b979e42b90cf/receipt-precleanup-completed.json`,
SHA256 `f0b97dff89bea24269ce44c63d283150f28b0022d304ff6c733177d07f96928b`.
Its `returned-precleanup.json` has SHA256
`067bf6e2efb4ee0281ade639956a1e7bf4850ef1669cd3cd00aafb018647813a`.
Both native scopes returned the clone with exact statistics and network isolation.

The final native receipts bind those immutable copies and all final owner cleanup
evidence. Both are `PASSED_NATIVE_GRAPH_COSTS_COMPLETE_CLEANUP`:

| Final native receipt under `~/.local/state/jobtology-hop/` | SHA256 |
| --- | --- |
| `jobkorea-dry-run-def7c40b34e7/receipt.json` — balanced Nara and fresh-three | `99df91362ca468800dcd50c41543fcf31015324662e754300549e7e13277befc` |
| `jobkorea-dry-run-b979e42b90cf/receipt.json` — full JOB-ALIO compatibility | `064e587d5a227deeffe42b16a592f13cdec59755977dc0832724a03e004660d1` |

The production plan is
`~/.local/state/jobtology-hop/additive-runtime-plan-3bfa1b87f10f49f2ae8ca581578db6fa/manifest.json`,
SHA256 `b7f382c58c386b9449157f5ab3f9676b6f48bfc9909dbfcfc99959d8f836cb57`.
The immutable application receipt is
`~/.local/state/jobtology-hop/additive-runtime-applied-096158dc69664fcdb29ec5c2ffe635ea/apply-verified.json`,
SHA256 `a012d7cf53e674dc6656f8f99e149e638a27811e1289c00d8d2aabbc81b9da7d`.

The final separate production readback receipt in the same directory is
`receipt.json`, SHA256
`7d0bf2ad4a5198f6bcb0a838ea848045e42e9c1c4f97576cbd37e27651c0dce3`.
Live validation is
`~/.local/state/jobtology-hop/source-proof-validation-111992cb5ad648f2a470a5200a7b7417/receipt.json`,
SHA256 `9ac02449bdee77aa60dabf123dc9f60851e3ee00a4ea4d59b46663ab0eff312d`.

Remaining measured work is Nara's residual scalar posting-key join and JOB-ALIO/
JobKorea entity-reader cost. The older 84/86-run observations retain unresolved
causes. Narrow trigger/query measurements and three-line fresh compatibility do
not establish whole-ingestion or whole-file throughput. No gain is inferred from
failed or differently scoped runs.

The 66-check focused host suite for generation, installer routes, narrow
deployment guards and existing source/date/runtime contracts passed. Targeted
Ruff and `git diff --check` passed. Repeated subsets are not added together.
