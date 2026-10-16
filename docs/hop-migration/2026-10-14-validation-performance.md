# Source validation performance — October 14, 2026

Status: isolated SQL semantics, complete scoped Nara reads, bounded parallel
read-only coordination and native Hop replay/preservation are proven. The bounded
four-scope atomic first-capture attempt failed at JOB-ALIO with exact rollback.
All owned isolated resources are removed and original logs drained without
cleanup failures. Production apply and separate readback are **VERIFIED** at
2026-10-13 15:22:31.156029 / 15:23:49.329957 UTC. The live four-source/two-worker
reader also passed at 15:24:43.767412 UTC with the exact isolated result checksum.
The earlier
[October 13 investigation](2026-10-13-postgres-parallelism.md) remains historical
evidence, including its failed measurements and undeployed count-only experiment.

## Scope and fixed fixture

Only the approved local PostgreSQL archive and supplied frozen evidence were
used. No source HTTP, model/provider or paid request, O*NET import or production
write occurred during these isolated proofs. The work uses one restored
PostgreSQL 18 clone, `jobtology-routine-archive-nara-e5f5120f45a7`, with network
`none` during SQL and matrix measurements, 6 GiB memory and a
four-logical-CPU-equivalent quota. Native Hop later used a temporary internal
network with the same PostgreSQL ID and statistics, then restored network `none`.
That quota is not
four pinned physical cores or a production capacity measurement. Heavy native
work is serialized, and tiny coordination/semantic databases are removed after
their tests. The shared clone and its exact anonymous volume were removed with
independent absence checks at 2026-10-13 15:15:21.206471 UTC.

The 937,258,240-byte archive is
`~/.local/state/jobtology-hop/additive-runtime-applied-5a7f73fd326e468b8117ef95e38cbe15/database-before.dump`,
SHA256 `e38466d8f6d144b100bdbecff6e38d6c2b3df695ff2fd38c19c04cbd99762494`.
Restore took 141.543s; explicit ingestion ANALYZE took 1.936s. Autovacuum is off
only in the owned clone. Exact SQL003→004→008 installation, all five source query
contracts, canonical wrapper/hook fast paths and four complete captured/live
manifests passed before measurement. Production global parallel settings and
function parallel-safety flags remain unchanged.

## Narrow SQL change and diagnosis

`hop/graph/sql/005_validation_worksets.sql` changes only the exact-run scoped
validation helper. It groups record/rejected counts once per document, and
projects Nara posting IDs and titles to a narrow text workset before grouping
list/detail title arrays by posting. Two `unnest` operations preserve the
original list/detail Cartesian conflict multiplicity within each posting.
NULL IDs still do not join, empty IDs still join, and text title extraction,
NULL/empty title behavior and selected-document rules retain their prior meaning.
JOB-ALIO's JSONB conflict rule and other sources remain unchanged.

In the explicitly analyzed clone, the original document-count branch took
10.558s and read 4,743,396 temporary blocks; its parameterized generic counterpart
took 10.680s. The original parameterized Nara conflict branch alone hit its 30s
bound at 30.005s. Merely projecting scalar values still took 11.134s with
9,425,615 nested-loop pair comparisons/rejections. Grouping by posting reduced
that branch to 0.116s. These branch measurements explain the work removed; they do not replace
complete validation acceptance.

The actual candidate completed the full Nara issue bag with `[]` in 0.200s and
`ingestion.assert_source_graph_content` in 4.874s. Six warm generic validity calls
returned true in 0.188–0.190s. All four captured/live source proofs remained exact.
The SQL-only phase has no corresponding original full-validator timing. The
earlier analyzed 60.006s timeouts are historical bounds, and the later native
original workflow control is censored at 60s as recorded below. No precise paired
whole-query speedup is claimed. JOB-ALIO still takes about 22–23s in this SQL phase.

The eight-source synthetic oracle passed 102 checks with exact issue **bags** and
typed selection preserved. Adversarial cases include duplicate two-by-two Nara
conflicts, NULL/empty IDs and titles, non-string titles, missing fields,
zero/rejected/unselected document counts, malformed Boolean cast failures, future
view/hook fallback and helper execution-metadata drift refusal. Its temporary
database was removed. This proves the tested rules and supplied snapshot, not
larger advertised cardinalities.

SQL005 SHA256 is
`1b0759a5b5af8119f5d2b9b57857ce1ea8968c857f0e0919205dde3a37c7d562`.
The first complete-query timing receipt used an earlier guard version; separate
binding proves its function definition is byte-identical to the final migration.
The final guard additionally pins language, result shape and execution flags.
SQL003/004/008 remain frozen, and both graph installers append SQL005 after its
dependencies.

## Bounded operational coordinator

`hop/operations/validate_source_proofs.py` is the concrete read-only entry point.
It accepts one to sixteen unique exact run IDs, defaults to two workers and caps
workers at four; one worker is the serial control. Each supplied run must retain
a READY non-SMOKE source and a READY captured proof. It executes the authoritative
content assertion once per run, without a second redundant issue-count scan.
It does not capture or write evidence or parallelize Hop writer workflows.

The coordinator acquires the existing exclusive retention advisory key in
autocommit **before** BEGIN REPEATABLE READ READ ONLY. Acquiring a waiting lock
inside that transaction could freeze a stale pre-wait snapshot. It verifies the
canonical retention function, refuses ACTIVE retention and registered writers,
exports one snapshot and holds the gate/exporter until workers close. Workers
import that snapshot before transactional reads and use read-only transactions
with session-level SQL parallelism zero. Guarded source writers and retention
wait while these reads run.

Statement, lock and validation deadlines are bounded; cancellation and cleanup
have separate short bounds. A failed worker skips queued work and cancels owned
peers. A lost exporter fails acceptance. Cancellation binds PID, backend start
and a unique operation application name; bootstrap cleanup uses exact token and
database names assigned at libpq connection startup. Worker server absence is
verified before exporter closure, and independent read-only cleanup verifies
worker/exporter server absence afterward. Unverified cleanup fails the receipt.
The separate cleanup control connection is closed after that verification.

The tiny native coordination oracle passed 21 checks: worker snapshot equality
during a concurrent synthetic change, retention exclusion and lock-wait snapshot
ordering, writer/ACTIVE/SMOKE/archived/incomplete rejection, read-only SQLSTATE
25006, statement-timeout 57014, failed-peer cancellation and queued skips,
bootstrap/import failure, bootstrap client timeout with an unregistered backend,
exporter death and server cleanup. Its unique database was removed. Frozen launch
copies and unchanged-byte checks bind the exact executed code. Twenty focused
host tests, Ruff and compilation passed. These synthetic tests prove coordination
contracts; canonical source-proof equality is separately established below.

Coordinator SHA256:
`509e980354c21e90a33d9e4f7b76014e66211ecf9d888b560246ffa40bb637ed`.

## Complete four-run read-only benchmark

The fixed workload is one canonical content assertion for each distinct scope:

| Source | Exact run | Captured source records |
| --- | --- | ---: |
| ALIO organization | `12d31df1-1783-48bb-be1d-b801502472ca` | 355 |
| JOB-ALIO | `18cb0086-5800-4a2b-870f-db8d74c62fbf` | 1,076 |
| JobKorea | `jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c` | 8,434 |
| Nara | `9419ffbf-0102-4a44-8c3b-ee28685f1a35` | 13,234 |

Identical work ran in worker order 1/2/4 then 4/2/1 after the final SQL005 was
installed and both tiny oracles finished. Every one of the 24 assertions passed,
all six deterministic proof/result checksums matched, and worker/exporter server
cleanup was verified for each operation. Wall time includes gate acquisition,
snapshot export/import, session setup, all assertions and cleanup. Job latencies
are retained separately. Cgroup CPU is the authoritative container aggregate.

| Workers | Forward wall | Reverse wall | Mean wall | Mean cgroup CPU |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 36.944s | 36.147s | 36.546s | 36.499 CPU-s |
| 2 | 25.769s | 25.908s | 25.838s | 36.766 CPU-s |
| 4 | 25.087s | 24.753s | 24.920s | 36.792 CPU-s |

Two workers reduce wall time by 29.30% (1.414× serial throughput) at similar CPU;
four reduce it by 31.81% (1.466×). Four are only 3.55% below two, supporting the
default of two. Cumulative throttled CPU time is zero in all six samples.
JOB-ALIO dominates at 24.3–24.7s per assertion. Nara's warmed assertion latency is
1.17–1.32s in this later phase; it is not a matched repeat of the earlier 4.874s
sample. No host cache was flushed. These are warm read-only validation gains for
this exact four-run workload, not complete ingestion gains, concurrent writer
safety evidence or 16-core scaling.

The ordered proof/result SHA256 is
`663f7281612f6c972d613c346ac679721df5ac2e7cd07aed949009d6218ecf84`.

## Native workflow and small import compatibility

The actual native Nara reader targets 10,555 source entities and 10,555 posting
dates for the same exact run with 13,234 captured source records. It has zero
source edges. Inferred-edge preservation uses a synthetic typed sentinel; it is
not a copy of production graph identities. Both final graph installers passed
with all-table row fingerprints preserved. Native statistics preflight recorded
168 `pg_stats` columns across 22 ingestion relations. A separate single unwrapped
fresh psql connection verified the fixture's 60s default statement bound; the
native JDBC baseline independently reached that bound.

Candidate priming completed the full workflow in 112.270s (103.286s native
pipeline duration). The warm candidate also passed in 103.537s (94.610s native
pipeline). The original `check_snapshot` hit its unchanged 60s bound at 60.065s;
the failed attempt took 69.311s and stopped before graph writes. That censored
baseline supports no speedup ratio.

| Warm candidate native stage | Pipeline time |
| --- | ---: |
| Validation | 0.424s |
| Capture | 1.290s |
| Graph/date write | 47.633s |
| Verification | 42.446s |
| Checkpoint | 1.286s |
| Guards/other | 1.531s |

Write and verification account for 90.079s of the 94.610s native pipeline. These
stages combine SQL, Hop and Neo4j work; they do not attribute the remaining cost
to one database. JOB-ALIO remains the read-only coordinator straggler at about
24.5s. Further optimization is outside this rollout.

Exact fingerprints of all 157 preexisting tables match across native installers,
priming, warm replay and the isolated fresh sibling. Priming operational changes
are `{}`: even observation rows are unchanged. Typed source graph content and the
synthetic inferred edge retain exact element IDs and properties. Nara's captured
and live manifests remain equal at 13,234 records/references and content SHA256
`0ab6676cd7b9ab413acef2b29b6f3c978b2307d621041226e372ee15621016b2`.

The fresh functional case copies three exact original physical NDJSON object
lines byte-for-byte from the supplied 21,951,764-byte snapshot, with original
line/byte provenance, into a protected 8,169-byte sample, SHA256
`fb831d1637d6849502100fb34a1ab5a88fa05ed4c915e2bce4f8f2a311faa5c8`.
Native JobKorea `full.hwf` passed once fresh in 15.167s and once as replay in
13.765s in an empty schema-only sibling database: READY has three rows, zero
issues and zero requests, with exact captured/live proof equality. This checks
shared count/capture/import/export compatibility; it is not three timing trials
or an 8,434-row ingestion throughput measurement.

Owned native Hop/Neo4j containers, network/anonymous volumes, scratch files and
the fresh sibling database are removed. The borrowed PostgreSQL clone preserved
its original ID and statistics through temporary internal topology, with no
restart or extra restore. It returned to network `none` and default timeout zero
before final removal. Independent checks confirm its original container and
exact anonymous volume are absent; original streamed logs drained and no cleanup
failed. The native receipt is sealed `PASSED_NATIVE_NARA_COMPLETE_CLEANUP` at
2026-10-13 15:15:32.123236 UTC.

## Bounded atomic first-capture limitation

Four exact scopes were attempted in one transaction with the unchanged 60s
statement bound. ALIO begin/finish passed in 0.262/0.032s. JOB-ALIO begin hit the
60s bound at 60.001s during membership INSERT, inside
`source_graph_insert_guard` → `source_graph_run_is_valid`. JOB-ALIO's roughly 22s
validator repeats across first-capture guards. Nara was never reached and no
four-scope durable or atomic capture success is established.

ROLLBACK completed with exact selected-ingestion and all-enrichment fingerprints
restored. The FAILED receipt remains immutable at
`~/.local/state/jobtology-hop/nara-validation-e5f5120f45a74179911d4f4fff2355e5/atomic-first-capture-corrected/receipt.json`,
SHA256 `c661db66dd7eed7fd861281b9894e23fdd2513d9c9e9693214df0bad3c804613`.
The earlier `atomic-first-capture/` attempt failed at a pre-BEGIN fingerprint
alias typo with zero mutations and remains separately preserved. Neither attempt
supports successful throughput or a four-scope capture gain. No timeout bound was
raised and no candidate was changed. JOB-ALIO first-capture/repeated validation is
a remaining TODO, separate from the proven Nara and read-only coordinator work.

## Production rollout and independent live readback verified

Production apply is VERIFIED at 2026-10-13 15:22:31.156029 UTC. Exactly three
runtime artifacts were published: SQL005 and the two graph installers. All 157
preexisting table fingerprints, schema/index states, source/publication queries,
catalogue outputs, immutable prompts and frozen matching pairs remain exact.
Historical publication SQL still returns 5,878 rows/21 reviewed and the current
pilot retains one SQL-eligible row. These are SQL outputs; no Neo4j write or new
inferred publication occurred. Model/defaults, credentials and routing remain
unchanged. The scheduler fence is removed.

The reviewed plan is
`~/.local/state/jobtology-hop/additive-runtime-plan-4e8b25fe95514fea8c6b74937a73be86/manifest.json`,
SHA256 `7664d57ab9720896d5a471ffb3b68b0b07932411e18bd53f6e664e16d6a9bf99`.
The immutable apply checkpoint is
`~/.local/state/jobtology-hop/additive-runtime-applied-900470c35c7a450c811c4f0acf81c02c/apply-verified.json`,
SHA256 `e04ca9a9ca28f2cd28dc63912cab2f479d7772521ff549a796767e526b8c2afc`.
The same directory retains the 941,843,465-byte `database-before.dump`, SHA256
`084a6c220622782c4fadd195bb5d23ecf2e1f59c8591dd4d2747b4aba6af280b`.
Archive listing is verified; no isolated restore of this new backup is claimed.
Separate readback passed at 2026-10-13 15:23:49.329957 UTC with exact runtime
bytes and all 157 table/query/schema/index/catalogue/prompt checks. The final
`receipt.json` in that apply directory is SHA256
`ca2b2895c0d8a24b041071b8a7946a0219048b5404ad6be44755b438cd56e884`.

The host-only coordinator then validated all four distinct live source proofs
with two workers in 25.241s, completing at 2026-10-13 15:24:43.767412 UTC.
ALIO/JOB-ALIO/JobKorea/Nara assertion latencies were 0.102/23.662/10.959/1.260s.
Every assertion passed, the deterministic result SHA256 matched the isolated
matrix exactly, cleanup errors are empty, and worker/exporter server absence is
verified. The live receipt is
`~/.local/state/jobtology-hop/source-proof-validation-6953c481a65c4949a85e09c9ce33ce40/receipt.json`,
SHA256 `fb3071399107351b6b656fff4eba8c5cf6d2f062f28ab75fa24955948adfcc68`.
This single live completion proves operational use and exact preservation; it is
not a paired production speedup measurement. Root independently confirmed all
owned test containers are absent.

## Protected evidence and remaining work

The SQL clone evidence root is
`~/.local/state/jobtology-hop/nara-validation-e5f5120f45a74179911d4f4fff2355e5/`:

| Receipt | SHA256 |
| --- | --- |
| `candidate-full/receipt.json` | `1be9e412a7e92f6cfcbe5b418fe4e228a4853de15e8db9079629ca8055d946ee` |
| `semantic-oracle-corrected/receipt.json` | `c4b2b0d4fa1b38496a7365f2e3237927685507f3b92fc2d0342362845e565e3e` |
| `guard-version-function-binding.json` | `aba3b01d5466663725b1fe605cff3e6c317235a7b213b9282d51c1cef4d680cf` |
| `final-formatter-native-sql-binding.json` | `56be6e9f2cd67de94fce5f1e6e1c217035c088fb2d0f135d4b24987c87ddafb6` |

The final native coordination receipt is
`~/.local/state/jobtology-hop/parallel-validation-native-c4164a061354480994b04a6d286db55f/receipt.json`,
SHA256 `987f20c2ca04b18245570db73c2da70a4c469c02ea54b095eb391f04411244b8`.
The balanced benchmark receipt is
`~/.local/state/jobtology-hop/parallel-validation-benchmark-8d86d5fa78e24bde95ce55138bd6419c/receipt.json`,
SHA256 `6d83ee2ba0d7e145608eb4f28b6b5cbf2b3fd59fe1a8432f6cc5becde94475ce`.
The final native workflow/compatibility receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-8d6c1f745036/receipt.json`,
SHA256 `679f0f346cef317706d579ecddef695821a10f07cd67b374c978d8316b6be37a`.
The clone owner's final `receipt.json` is SHA256
`54affca553fb3a7c73b5edeef6b449a76c0748019eaf1b975ef568e76ed6089b`;
its `independent-cleanup.json` is
`d118cabb281c821a8716a1dc9cc8ae617bd19ab3b162d3165f1b1dce91375229`.
Raw SQL, plans, frozen launch copies, per-operation receipts and SQLSTATE-only
stderr remain protected outside Git. Original failed attempts remain unchanged;
corrected acceptance has distinct receipts.

The first clone attempt matched the temporary PostgreSQL initialization server
as ready and was discarded with cleanup verified; its FAILED receipt is
`~/.local/state/jobtology-hop/nara-validation-5f2fc72fffb247e987466ef904f17e9f/receipt.json`,
SHA256 `2a22c091578b6676e59f5d623e9aca6694196e53fb212def78a9221e0ede1da9`.
The first semantic fixture failed in its SQL formatter, with its database removed;
`semantic-oracle/receipt.json` remains FAILED at
`a461c489da9a5875200eeb360f2c3fd30e5f46509a048043db20b9151de1d1e9`.
The first coordination fixture rejected canonical multiline gate padding before
running an assertion; its FAILED receipt remains in
`parallel-validation-native-b892501a63394ed1b35ceafbf59bc7d3/receipt.json`,
SHA256 `64a451b659748922b5169c16c5b6a0c8f4bf1f96b155024e2dfb499e97254fdf`.
Only boundary whitespace is now trimmed, with an interior-space lock-key mutation
explicitly rejected. None of these failed attempt times is performance evidence.

The verified runtime publication contains SQL005 and the two graph installers.
The coordinator is the reviewed host-only CLI in this checkout. Remaining
performance work is JOB-ALIO first-capture/repeated validation and decomposition
of combined graph/date write and verification costs. The historical 84/86-run
atomic difference remains unexplained. These are separate later tasks; no new
matching, paid retrieval or O*NET scope was added.
