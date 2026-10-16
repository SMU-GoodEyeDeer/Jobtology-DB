# JOB-ALIO validation and graph performance — October 14, 2026

Status: isolated SQL006 semantics, complete JOB-ALIO assertions, nondurable
JOB-ALIO first capture and native owner transport are qualified. All owned test
resources are removed. The wider capture attempts and original native checker
failures remain FAILED with their evidence preserved. Production deployment and
separate independent readback and five-snapshot live validation are verified.
The earlier
[SQL005 report](2026-10-14-validation-performance.md) remains historical evidence.

## Fixed fixture and SQL scope

Only the supplied local PostgreSQL archive and frozen evidence were used. The
SQL qualification made no source HTTP, provider/model or paid request, O*NET
import or production write. One PostgreSQL 18 clone,
`jobtology-routine-archive-nara-a02d950a9560`, uses network `none`, 6 GiB memory
and a four-logical-CPU-equivalent quota. This quota does not pin four physical
cores. Autovacuum is disabled only in this owned clone. Ingestion statistics
were explicitly analyzed once and their exact `pg_statistic` fingerprint stayed
unchanged throughout the comparisons and capture proofs.

The restored 941,843,465-byte archive is
`~/.local/state/jobtology-hop/additive-runtime-applied-900470c35c7a450c811c4f0acf81c02c/database-before.dump`,
SHA256 `084a6c220622782c4fadd195bb5d23ecf2e1f59c8591dd4d2747b4aba6af280b`.
Readiness required the final PostgreSQL process at PID 1. Exact frozen
SQL003→004→008→005 installation, all source query contracts, canonical validation
fast paths and four complete captured/live manifests passed before measurement.
Production global parallel settings and function parallel-safety flags remain
unchanged. Every SQL statement kept its 60-second bound.

SQL006 changes only `ingestion.source_graph_scoped_validation_issue(text)`.
It projects JOB-ALIO's five conflict fields as JSONB and groups parallel field
arrays by non-NULL text posting ID. One zipped `unnest` restores each list or
detail tuple; their cross product preserves duplicate conflict issues. The
detail's exact `->>'ongoing' IS NOT NULL` gate has its own aligned Boolean array.
Missing SQL NULL and JSON null remain distinct, numeric/string types remain
distinct, and malformed non-NULL ongoing values are compared without casting.
Empty posting IDs still join; NULL IDs do not. Other rules, source guards,
canonical fallback, evidence algorithms and retention behavior stay intact.

SQL006 is generated from byte-pinned SQL005 and accepts only the exact SQL005 or
SQL006 helper with the original execution metadata. Its SHA256 is
`728e103f4b0df3af12ae4b2cc6f52f5d2ebf6d320163ae6daa37b35e0c627c31`.
SQL003/004/005/008/037 retain their frozen bytes. Applying SQL006 directly over
SQL003 is refused; SQL005 also refuses to overwrite SQL006. Canonical installers
replay SQL003→004→005→006.

## Complete assertions and semantic oracle

The original JOB-ALIO JSONB conflict branch took 23.035s and read 3,404,879 shared
buffer hits. The grouped branch took 0.221s with 25,426 shared buffer hits. These
bounded EXPLAIN measurements diagnose the removed comparisons; the complete
assertions below establish the measured gain.

One persistent backend used `force_generic_plan`, JIT off and session-level SQL
parallelism zero. Order was baseline/candidate/candidate/baseline, with the same
explicit statistics and exact supplied JOB-ALIO run. No host cache was flushed.

| Complete JOB-ALIO content assertion | First sample | Second sample | Mean wall | Mean cgroup CPU |
| --- | ---: | ---: | ---: | ---: |
| SQL005 baseline | 25.333s | 24.039s | 24.686s | 24.717 CPU-s |
| SQL006 candidate | 0.867s | 0.875s | 0.871s | 0.899 CPU-s |

All four assertions passed with identical outputs and full captured/live proof
values. Mean wall time fell 96.47% (28.34×). CPU throttling was zero in every
sample. This is scoped warm assertion performance, not whole-ingestion,
production-capacity or writer-scaling evidence.

The candidate also returned an empty complete issue bag for each source and
passed the authoritative content assertions with these exact proof counts:

| Source | Exact run | Records | References |
| --- | --- | ---: | ---: |
| ALIO | `12d31df1-1783-48bb-be1d-b801502472ca` | 355 | 355 |
| JOB-ALIO | `18cb0086-5800-4a2b-870f-db8d74c62fbf` | 1,076 | 2,152 |
| JobKorea | `jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c` | 8,434 | 8,434 |
| Nara | `9419ffbf-0102-4a44-8c3b-ee28685f1a35` | 13,234 | 13,234 |

The schema-only eight-source oracle passed 308 checks and removed its temporary
database. Its 67 independent JOB-ALIO scenarios compare complete canonical issue
bags and explicit expected conflict rows, then verify fresh repair after rollback.
They cover type/null distinctions, duplicate and partial Cartesian conflicts,
aligned fields/gates, one issue per conflicting pair, coerced posting IDs,
representations and selected-document exclusion. Existing Nara, adapter,
selection and future-view/hook fallback cases also pass. Helper execution-metadata
drift, applying SQL006 over SQL003 and a direct SQL005 downgrade are refused.
Protected launch copies and
unchanged-source hashes bind the executed oracle to the reviewed files.

## First capture and remaining guard cost

The original four-scope atomic attempt passed ALIO, then JOB-ALIO begin reached
60.001s in the membership insert guard. It rolled back exactly. The candidate
passed JOB-ALIO begin/finish in 5.626/0.844s, then JobKorea begin reached the same
60s bound during `source_graph_insert_guard`'s materialized live-reference
comparison, joining transition rows on `(run_id,record_id,identity_id,field)`.
Nara was not reached in that atomic attempt. Its exact rollback also passed.

The separate per-run attempt used independent transactions. ALIO and JOB-ALIO
completed and rolled back before the next scope. JOB-ALIO begin/finish took
4.451/0.845s and produced READY with 1,076 records, 2,152 references and content
SHA256 `4ca210281e8e46700d8301dc156b85e338b75a78f307a3a2d6af8d805e22a74b`,
identical to the original and live proof. Its projection timestamps, membership
and record evidence restored exactly after rollback.

JobKorea was explicitly skipped because the same candidate atomic attempt had
already established its 60s bound. Nara begin then reached 60.002s during the
record-evidence insert guard's materialized live-evidence comparison on
`(run_id,record_id)`. The wider per-run attempt remains FAILED. All selected
ingestion tables and all enrichment table fingerprints match after recovery for
both candidate failures. No four-source complete capture, durable capture,
historical 84/86-run result or successful paired first-capture baseline is claimed.

The narrow JOB-ALIO qualification is a derived audit of recorded successful
operations inside the wider failed per-run attempt. It binds the original receipt
hashes, READY manifest, original/new full-proof equality and exact rollback. It
does not relabel either failed attempt. Generic transition-table evidence
comparisons for JobKorea and Nara remain separate work; guard calls were preserved.

## Native graph work and production rollout

Native diagnosis uses the same PostgreSQL ID/statistics on a temporary owned
internal network, with no published ports or second restore. Both SQL006 native
installers and Nara priming passed with all 157 table fingerprints preserved.
The warm baseline completed in 117.294s wall time, including 108.209s of native
pipelines. Write and verification stages took 54.730/48.898s.

Separate diagnostic calls retained each exact canonical SQL reader and then ran
its unchanged JDBC reader into a Dummy Hop sink. All returned the expected rows.

| Nara reader | Rows | Instrumented SQL execution | JDBC/Dummy pipeline |
| --- | ---: | ---: | ---: |
| Entities | 10,555 | 19.232s | 18.214s |
| Source edges | 0 | 11.798s | 11.750s |
| Edge owners | 10,555 | 11.912s | 12.113s |
| Posting dates | 10,555 | 0.702s | 0.813s |

The full baseline's entity write/verify took 20.327/18.778s; empty-edge
load/verify still took 11.750/11.751s. Owner cleanup/totals took 18.290/17.361s.
These measurements identify substantial SQL selection work and motivate testing
500-row owner transport. Separate SQL, Hop and read-only Neo4j PROFILE timings
overlap and cannot be subtracted to estimate individual costs. Nested plans and
500-row Neo4j verification profiles are retained privately. SQL003 stays frozen;
its source selection costs remain a separate later task.

The separate 500-row Neo4j PROFILE for names recorded 72,000 database accesses,
111ms readiness and 209ms consumption; the date profile recorded 39,000 accesses,
30ms readiness and 69ms consumption. These instrumented diagnostics are not
subtracted from complete replay or extrapolated to full-run Neo4j cost.

The protected nested plans show those exact Nara readers still materializing
eight historical READY runs: 103,037 records/references and 19,474 documents.
Entity candidates narrow from 103,037 to 98,766 to 10,555 while writing/reading
large temporary worksets. The final scalar-key join scans 565 Nara fact rows per
entity and rejects 5,963,010 pairs. Historical candidate assessment also validates
all eight runs; its subtree timing overlaps the reference work. Empty-edge reads
spend about 11.328s constructing references before returning zero rows. Future
SQL work must preserve latest/fallback/name priority and exact proof/guard rules;
no SQL007 or additional migration is part of this task.

The clean transport comparison ran baseline/candidate/baseline. Baselines took
117.294/114.833s, and the one eligible candidate took 104.103s: mean wall time
fell from 116.064s by 10.31%. Cleanup fell from a baseline mean of 17.941s to
12.136s (32.35%); totals fell from 17.289s to 12.103s (29.99%). Both owner
pipelines changed 10,555 individual batches to 22 batches with a final 55 rows.
Exact typed Nara graph evidence matches before and after the comparison and
after restoration. All timed transport variants use SQL006. These results have
only one eligible candidate sample and are separate from the earlier archive's
103.537s Nara checkpoint.

Mean native pipeline time fell from 107.082s to 95.031s: writing changed from
53.623s to 46.972s and verification from 48.920s to 43.596s. The two owner
pipelines account for 10.990s of the elapsed reduction. PostgreSQL cgroup CPU
stayed about 89.6 CPU-s; Neo4j and Hop means changed from 16.889/31.625 CPU-s to
3.704/15.845 CPU-s. Baseline Neo4j CPU varied substantially across its two
samples, so these measurements do not establish a general throughput factor.

An earlier candidate replay overlapped an owned host log-analysis process.
Its unchanged raw timing remains correctness evidence and is excluded from
performance comparisons. No balanced native ABBA comparison is claimed.
The initial native receipt remains FAILED because its checker rejected missing
zero-input operation summaries. Runtime bytes and the successful replay results
are preserved; corrected zero-summary regression checks pass.

Independent acceptance with corrected ownership checks, full JOB-ALIO replay,
small fresh JobKorea compatibility and final cleanup passed. Its separate
qualification binds the original failed receipt without rewriting it. The native
owner restored isolation and removed its owned resources; the clone owner then
removed the exact original PostgreSQL container and volume and independently
verified absence against a reachable Docker daemon. Original PostgreSQL logs
drained completely at 2026-10-13 17:26:51.318230 UTC. Returned ingestion statistics
still match the fixed analyzed fingerprint. The combined rollout uses
`deploy_jobalio_graph_runtime.py` for SQL006, both installers and the two owner
pipelines. Apply and its first readback passed at 2026-10-13 17:40:34.477344 UTC,
with all five artifacts, all 157 table fingerprints and protected query outputs
preserved. Separate independent readback passed at 17:42:01.078092 UTC; only
the existing scoped validation helper changed, and the scheduler fence is absent.
The five-snapshot live validation also passed; its distinct scope is recorded
below.

The first deployment plan was refused before mutation because an existing
scheduled JOB-ALIO refresh held the scheduler lock. At 2026-10-13 17:28:32 UTC,
its owner-reader query was still active after 8m44s; an earlier entity verifier
took 721.810s. Those are observations of the pre-existing production schedule,
not task-issued source requests or graph writes and not matched performance
samples. Its independent activity means rollout preservation must compare the
fresh deployment before/after state, rather than this task's older archive.
The deployment guard prevented concurrent modification. The scheduled refresh
completed naturally at 02:33:43 KST (17:33:43 UTC), with READY run
`4a9262a3-aee6-47b9-ad90-6ed8e4c6b2c1`. Its old-runtime native graph load took
5,257.387s; that background observation is not a paired gain measurement. No
observer request, cancellation or runtime write was issued. The fresh guarded
five-artifact plan then passed and its apply and independent readback were
verified.
Protected read-only observation:
`~/.local/state/jobtology-hop/jobalio-scheduler-readonly-20261014/initial-observation.json`,
SHA256 `cd6cf3aced3ca0898abc9a36bc9542639e392aa6750570141d2d16a716341730`.
Its separate `final-completion.json` is SHA256
`5e0460119ffa7c6919a29731ea74b147fc645743982b5b663eca817f4e3e1614`.

Guarded plan:
`~/.local/state/jobtology-hop/additive-runtime-plan-bbd02a6e0d784260b5c1a19462fa9617/manifest.json`,
SHA256 `76e10dd72a6fdfe889a6f003716826bc4d55eae46ff69b094030dae0d1dc2d68`.
Its 5,879 legacy-query-eligible rows are SQL outputs, not evidence of new Neo4j
publication. The post-deployment read-only coordinator validated five snapshots
across four sources: the original four exact runs plus the newly scheduled
JOB-ALIO run. The original four complete result objects equal the earlier
four-job receipt. The five-job whole-result checksum has a different scope.

The immutable first apply proof is
`~/.local/state/jobtology-hop/additive-runtime-applied-35a0f654b8a844d4a22ac39d94673dad/apply-verified.json`,
SHA256 `b2c67fcb237b5800a272b29c1e63c53be752e085d0b6861ae30c4c89bb22cdcb`.
Its fresh 943,409,053-byte full custom-format `database-before.dump` is SHA256
`a52b85a31b8ba5b1e844558ab1bbbbbfd810e36c7034e1fad045cda8a8ea2c24`.
Archive listing passed; this new backup was not restored in this task.
The final independently read-back production receipt in the same directory is
`receipt.json`, SHA256
`929a5f0a413f49800ed76867aaad39401618c94516a038342a7a6fc1a5b4998f`.

The live two-worker reader passed at 2026-10-13 17:42:23.323023 UTC in
11.771173s. All worker/exporter backends are verified absent, and the scheduler
fence remains absent. Its new JOB-ALIO snapshot has 928 records, 1,856 references
and content SHA256
`93f39f7d9efaa8d8ab17e9582ee824a13ccf64ff0e49cc1bae97b9c5bd2f4910`.
Per-job elapsed times were ALIO 0.106s, original JOB-ALIO 1.001s, JobKorea
10.637s, Nara 1.301s and new JOB-ALIO 0.711s. These overlap under two workers
and are not summed; no paired gain is claimed against the older four-job live
run. The receipt is
`~/.local/state/jobtology-hop/source-proof-validation-b3138d5b7bb44273971fb3dc20d91537/receipt.json`,
SHA256 `72de5e8bcdce4ff4db3e9754e4ed26d511eb0f2c3b53ac5b2044c3c64b9d37d1`.
Its five-job result SHA256 is
`d0202676c7bf01a99f290e625c3909664a6245ff6dbf05b905f6c9b8aec38636`.

The final compatibility fixture restored all 157 original Nara table fingerprints
and complete manifests before JOB-ALIO installation. JOB-ALIO prime and warm
replay passed in 178.849/173.357s with 673 entities, 538 edges, 538 owners and
538 dates. Each owner pipeline processes two batches with a final 38 rows.
Its 22-case owner oracle passed 33 assertions, including partial-batch and empty
input behavior. Exact typed graph, inferred sentinel and all 157 table/source
proof checks passed. A three-original-line schema-only JobKorea import/replay
also passed READY with three records, zero issues/requests and equal full proof;
its temporary database was removed. This small case does not establish supplied
whole-file throughput. A final read-only Nara authoritative assertion and full
manifest passed within the unchanged 60s bound before clone cleanup.

One earlier combined expected-count statement
reached its 60s bound because the four canonical reads total about 71s. Each
unchanged reader subsequently passed its own 60s bound; no timeout was increased.
That original failed receipt is also preserved.
The JOB-ALIO replay is functional compatibility evidence, with no paired gain
claim.

## Qualified runtime bundle

The combined deployment allowlist contains exactly these five reviewed files.
Native qualification and separate independent production readback bind their
hashes.

| Runtime artifact (under `hop/`) | SHA256 |
| --- | --- |
| `graph/sql/006_jobalio_validation_worksets.sql` | `728e103f4b0df3af12ae4b2cc6f52f5d2ebf6d320163ae6daa37b35e0c627c31` |
| `graph/install.hwf` | `20f17d6bbbe71a24d238bccf9686ec43fc8c27c68fd5b18b73516a9c7cc8f57d` |
| `graph/install_posting_dates.hwf` | `3ab5c090c6f9359a6b82745a75fb51210c9c8a7845bd98168df26b16ec325f6e` |
| `graph/clear_source_edges.hpl` | `02aa025cdbf026691f4144a13c21f641dba72bda2610370ac37411d6076b1e62` |
| `graph/verify_totals.hpl` | `25f2bde07315053b058b1e998222a3eaaaf92356e1cab7685ab9512acc155782` |

## Protected receipts

SQL evidence root:
`~/.local/state/jobtology-hop/jobalio-validation-a02d950a95604fd8ac59eae338c8265e/`.
Raw SQL, plans, launch copies and original error contexts remain protected outside
Git. Failed receipts retain their original status and bytes.

| Receipt | SHA256 |
| --- | --- |
| `clone-preflight.json` | `97aeef1a8350459fdb09250643623d237afb520f6862a43ce56ed7885b444d1d` |
| `balanced-full-assertions/receipt.json` | `f7f91d6387404710aa90a9b84d0c1bad69b019a4cf090802bb8216ae4bda90d5` |
| `baseline-atomic-first-capture/receipt.json` — FAILED | `e1e3f72ed631f7e26c3734268ae962f36d5b784eaed9e6003d3fe1f3ee5f8fd2` |
| `candidate-atomic-first-capture/receipt.json` — FAILED | `66b7e0e8ebbc7e0abbb11103e93e0eb6496d598783abc0024a98a24ab8938107` |
| `candidate-per-run-first-capture/receipt.json` — FAILED | `235e6e17662cf41fbad3acf96895f249164054ba1073ae7150fbb2bd2885dd8f` |
| `qualified-jobalio-first-capture.json` — derived JOB-ALIO only | `a4baf60a41c881b4f47a992f693a96c626f1df11a5f5d2cb1182173b30336b15` |
| `semantic-oracle/receipt.json` | `eb7a7529a0526672f8835e52d480b041e329f259714375e23e7555cdec9c0b0e` |
| `oracle-launch-binding.json` | `5ba589ed9704edb06a1f94d8346f237c6c85d84e7369684230bcd73cc9a3ee5a` |
| `released-for-native.json` | `1153b2945238ed731d27642d887ef6ed970eef85d44193896b7dc5847d2a58ca` |
| `returned-precleanup.json` | `eff3bec2071952e879a981437d1684c67f83e92837d0733e0935f5cada86d1e1` |
| `returned-statistic.json` | `5ed5a061298252ad2fa8310a1a5c986ad02235ec0419cc1282f90791efa815d8` |
| `receipt.json` — final clone-owner READY/cleanup verified | `345331209a045c5657c1c7ca2a9a4a8e7a373f4f4a0ca4cc23f0ad9468514bed` |
| `independent-cleanup.json` | `cebde8ac5ddad99231b3451341ec34e80d9a9c22c31619b5d6a904fc14999f47` |
| `temporary-helper-cleanup.json` | `eba5eaffdd18096b2129508dcd1eeee177ddf6492ec89d75b6d9775eebbd21c7` |

The immutable native diagnostic snapshot is
`~/.local/state/jobtology-hop/jobkorea-dry-run-7a9b4ed1944e/profile-phase-receipt.json`,
SHA256 `fb347eb2dbd4bf6ecf65f53d22f83e97567646ce31a63e4eb7f650772b12cf72`.
It records the completed diagnosis inside an ongoing qualification; its RUNNING
status is preserved.

The same native directory's `nested-plan-structural-summary.json` is SHA256
`494dd6f1cb690a00c53ebbfcf0db72d5eaecf667cbb6846034d77b025d0e2f64`.

Native evidence paths below are relative to `~/.local/state/jobtology-hop/`:

| Receipt | SHA256 |
| --- | --- |
| `jobkorea-dry-run-7a9b4ed1944e/receipt.json` — original checker FAILED | `fa42556724d4e9aa4fd258d319394b92899ac214119c499b5b8a8f8a62b878dd` |
| `jobkorea-dry-run-b5ed33b47532/receipt.json` — combined count FAILED | `b43a375418618fcc7c2ee707ccb55612ad8e462e3bc6570dcc882be183fdcc97` |
| `jobkorea-dry-run-a4765cc18462/receipt.json` — final native acceptance/complete cleanup | `bdf423e9e1398d569172de0d18c885f2f4cdbbe8ff19bbf7c5d20880393cdf77` |
| `jobkorea-dry-run-a4765cc18462/final-owner-transport-qualification.json` | `56fbbfc0ed09322d661b8f6b49247ff631bee88b01f71b8e29744e6ccac07295` |
| `jobkorea-dry-run-a4765cc18462/post-native-nara-readback.json` | `c83d4ef6a7a77a7048045a39e2992f6e8fcabdfc5f3ef9715c897b6ea5b5242e` |

Forty-three focused host generation, installer, deployment, source-query,
transport and replay checks pass. A later 28-check harness, qualifier, counter
and deployment suite also passes, including the zero-summary correction; repeated
subsets are not summed. Targeted Ruff, compilation and `git diff --check` pass.
Production rollout, separate independent readback, live validation and all owned
resource cleanup are complete. Generic JobKorea/Nara first-capture evidence joins
and historical source-reader worksets remain the next bounded optimization work.
