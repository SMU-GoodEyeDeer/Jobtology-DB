# PostgreSQL parallelism and nested validation — October 13, 2026

Status: bounded investigation completed; all owned resources removed at
2026-10-13 06:21:13.010090 UTC. No new production SQL or runtime change was made.
No production parallel settings, source requests, provider/model calls, paid work
or O*NET import are part of this investigation.

## Scope, baseline and failed measurements

One unique PostgreSQL 18.6 container restored the approved latest pre-rollout
archive, then used the exact frozen SQL003 installer followed by current SQL004
and SQL008. The container has no network, a 6 GiB memory limit and a four-logical-
CPU-equivalent quota. It is not pinned to four physical cores. The host has eight
physical cores/16 logical CPUs; production exposes 16 logical CPUs without a
CPU quota.

The exact archive is
`~/.local/state/jobtology-hop/additive-runtime-applied-5a7f73fd326e468b8117ef95e38cbe15/database-before.dump`,
937,258,240 bytes, SHA256
`e38466d8f6d144b100bdbecff6e38d6c2b3df695ff2fd38c19c04cbd99762494`.
Restore completed in 142.021s. This is a restore of that archive, not a new
source collection event. SQL003/004/008 remained byte-exact at their recorded
SHA256 values. SQL003 was reinstalled only through its guarded canonical
installer; SQL004 was reapplied afterward so the measured baseline retained the
deployed existing-proof replay behavior.

The first four-scope manifest series was **invalid**: all 12 jobs failed
`P0001 / SOURCE_GRAPH_QUERY_CONTRACT_CHANGED`. The coordinator initially reported
completion times without checking the job statuses; those statements were
corrected. None of those times or reported throughput values supports a gain.
The original overall receipt remains FAILED and its raw results are preserved.

The restore changed only the guarded `graph_reference` view's deparsed UNION
aliases among the five source-query contracts. Its expected MD5 was
`ea064e997e20998d0fee813b188f35ae`; the restored definition returned
`23f15445c57878b7b0ec04078d4b1336`. The exact SQL003 installer already accepts one
canonical deparse/reparse roundtrip. No guard was relaxed or manually rebound.
After SQL003→004→008, the authoritative five-view guard passed and complete
captured/live manifests matched for every scope below:

| Source | Exact run | Records |
| --- | --- | ---: |
| ALIO organization | `12d31df1-1783-48bb-be1d-b801502472ca` | 355 |
| JOB-ALIO | `18cb0086-5800-4a2b-870f-db8d74c62fbf` | 1,076 |
| JobKorea | `jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c` | 8,434 |
| Nara | `9419ffbf-0102-4a44-8c3b-ee28685f1a35` | 13,234 |

That is 23,099 source records, with exact captured/live count/reference/content
values preserved. Wrapper fast-path view/hook hashes were independently checked.
The original instrumented Nara assertion reached its 60s bound before the later
live-manifest guard; it is retained as a bounded diagnostic rather than a
canonical baseline performance result. It did not prove a successful full
validation or capture. No all-run 84/86 capture or higher-timeout retry occurred.

## Actual SQL parallel workers

The standalone evidence checksum scans all 271,214 archived ingestion records and
726,893,370 bytes of JSON evidence. It returns row/byte counts and associative
numeric sums of all four 64-bit parts of each SHA256. This is a useful CPU-heavy
archived-evidence scan, not the canonical source-proof algorithm. PostgreSQL may
inline and recompute its JSON/hash expressions; it is not claimed to hash each
row only once. The query does not call the failed source-contract guard.

Every output and EXPLAIN completed successfully. All eight output SHA256 values
matched `75b862bef0d0ed42a51bac429a4e874979a718aff820dc196ec0df77b9a8c106`.
The unchanged query used default planner costs in this first series:

| Per-Gather worker cap | Actual workers launched | Output wall | Cgroup CPU |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 47.762s | 47.964 CPU-s |
| 1 | 1 | 24.752s | 49.560 CPU-s |
| 2 | 2 | 17.218s | 51.395 CPU-s |
| 4 | 4 | 13.651s | 54.499 CPU-s |

Gather actual partial-result rows were 2/3/5 for 1/2/4 workers: the leader also
participated. **Four SQL workers plus a leader differ from four independent
connections.** At four workers, 135 of 137 quota periods were throttled, with
13.755s cumulative cgroup throttling time. Cumulative throttling time is not wall
time. Per-PID scheduler ticks include surviving processes and omit workers that
exit between snapshots; cgroup CPU usage is the authoritative aggregate. The
measured 3.50× serial-to-four-worker ratio is confined to this exact scan under
the clone's four-CPU quota.

A separate reverse-order sensitivity series set only session-level minimum
parallel scan size/setup/tuple costs to zero. Worker caps 4/2/1/0 took
13.623/17.268/25.080/47.244s, with 4/2/1/0 workers launched. This changed cost
regime is not a matched order-balanced replicate. It produced no reason to
change production global planner settings: default costs already launched
workers for the eligible real evidence scan. JIT was off for this query.

## Independent read-only validation jobs

After canonical restoration correction, the fixed heavier workload comprised
four jobs: source-validation issue count and complete source-content assertion
for JOB-ALIO, and the same two checks for JobKorea. Every issue count was zero;
every assertion completed. These are independent checks on preserved evidence,
not four new imports or a whole ingestion workflow. Nara's full validator was
excluded from this throughput workload because of its known bounded timeout.

Each job used a fresh read-only session, a 60s statement bound and
`max_parallel_workers_per_gather=0`. Identical work ran in order 1/2/4 then 4/2/1.
All 24 jobs passed with exact per-job output equality; none timed out. Total
wall time includes session startup, while job latency covers query execution.

| Independent sessions | Forward total | Reverse total | Mean total | Completed jobs/s |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 64.993s | 65.052s | 65.022s | 0.0615 |
| 2 | 35.031s | 35.245s | 35.138s | 0.1138 |
| 4 | 24.925s | 24.954s | 24.940s | 0.1604 |

Two/four sessions yielded 1.85×/2.61× throughput for this exact four-job workload
in an **unanalyzed restored fixture**. This is not a calibrated production proxy.
The individual JOB-ALIO checks remained about 23–25s; JobKorea checks remained
about 7.5–11.4s. The gain comes from overlap, not faster individual checks.
Aggregate CPU was 64.963/64.977 CPU-s at one session,
66.578/67.015 at two and 68.992/69.058 at four. Four-session runs had only about
0.025/0.026s cumulative throttling. A separate planning-only Nara EXPLAIN took
0.0674s during the forward series; its negligible concurrent planner work is
retained and disclosed in the audit evidence.

All timings follow restore and earlier reads. Fresh sessions are not cold data;
no host cache was flushed. Autovacuum was disabled only in this owned clone.
The approved backup command used `--format=custom` without `--statistics`;
PostgreSQL 18 includes optimizer statistics only when requested. All ingestion
tables in the initial fixture had zero column-statistics rows. Merely installing
SQL008 does not execute its guarded sealing ANALYZE. Production separately had
column statistics and automatic-analysis timestamps. Canonical byte/proof
preservation does not establish equivalent planner statistics. The concurrency
and checksum results above remain valid comparisons within one fixed fixture,
with limited production relevance. No receipt was retrospectively relabeled as
analyzed. See [PostgreSQL 18 pg_dump documentation](https://www.postgresql.org/docs/18/app-pgdump.html).
Two samples per width support this workload's result, not a general capacity
or 16-core scaling claim.

## Nested diagnosis and recommendations

A planning-only extraction of the actual scoped Nara validation body shows
correlated per-document record/rejected counts over materialized CTEs. The
EXPLAIN ANALYZE of the targeted record-count branch in the original
unanalyzed-statistics fixture completed in 10.811s within a 30s bound; the candidate investigation retains its actual loops and buffer evidence.
The canceled full validator's auto_explain log contains completed inner plans,
not a complete analyzed plan for the canceled statement.

A separate explicitly analyzed comparison first recorded the absent restored
statistics, restored the exact original scoped validation function, then ran
bounded ANALYZE on the owned ingestion tables. The original and grouped-count
candidate full Nara validation each timed out at **60.006s**. Captured/live source
proof values before and after remained equal, but neither complete validation
result was established. The candidate isolated count branch completed in
0.05653s with zero mismatches after ANALYZE. Comparing it to the earlier 10.811s
unanalyzed original branch confounds statistics and query shape; no paired branch
speedup ratio is claimed.

The experimental SQL005 migration, generator and test were archived outside the
canonical repository and removed from the canonical paths. They were never
installed in production or added to the runtime installers. The eight-source
native semantic issue-bag oracle was **not executed**. The candidate remains
unqualified; a faster isolated branch is insufficient to deploy it. The original
scoped function was restored in the clone before teardown.

A static inspection of deployed Hop 2.19.0 DBJoin found fetch size 10,000,
transform copies 1, no cache and row limit 0. Its inspected normal connection path
did not change autocommit, and this pipeline has no transaction grouping. A
nonzero JDBC fetch size does not demonstrate a server cursor or an actual
protocol Execute fetch-count blocker; autocommit=false/cursor use was not proved.
No cause is attributed to that mechanism.

Production already has `max_worker_processes=8`, `max_parallel_workers=8` and
`max_parallel_workers_per_gather=2`; most ingestion-core functions remain marked
PARALLEL UNSAFE. Worker flags alone do not establish that a function is safe.
The measured direct scan demonstrates that PostgreSQL can use multiple CPUs
without global tuning. Keep existing production settings; use bounded independent
read-only checks where transaction/retention semantics permit them, and investigate
scoped Nara fact/self-join estimates and repeated conflict JSON work before
considering function flag changes.
A bounded independent read-only validation coordinator with a consistent
snapshot and retention serialization is future work; no parallel pipeline was
deployed. These measurements do not demonstrate concurrent capture/writer safety
or show that Hop's full load pipeline scales with four copies.

## Protected evidence and helper validation

All plans, SQL, stderr, raw outputs, source manifests and process/cgroup snapshots
remain outside Git in
`~/.local/state/jobtology-hop/postgres-parallelism-a80225b840114b15904b9ec1e5a30636/`:

- `benchmarks-complete.json`: immutable original failed overall profile; its
  independent-manifest series is invalid, while all direct-scan outputs/plans pass.
- `canonical-baseline-correction.json`: exact guarded SQL003/004/008 correction,
  authoritative query contract and all four exact captured/live readbacks.
- `heavy-validation.json`: valid 24-job balanced independent-session experiment.
- `helper-version-evidence.json`: explicitly reconstructed launched source and
  review-only corrections made after launch; actual SQL/settings remain retained.
- `receipt.json`: final owned-container cleanup and streamed log-drain receipt.
- `future-helper-verification.json`: final helper SHA256 and seven host/static
  checks; no additional native performance execution is claimed.

Static/Hop/nested-candidate audit evidence is separately retained at
`~/.local/state/jobtology-hop/parallel-hop-audit-k7m9xyvb/`. In that directory,
`analyzed-document-count-profile/receipt.json` seals the two analyzed full-query
timeouts and preserved source proof values;
`candidate-row-count-plan/receipt.json` records the later isolated branch;
`experimental-document-counts/manifest.json` preserves the archived candidate.

Final fixture receipt SHA256 is
`244a4cf2a2995b017751951f5c8ce2c20ae2aa64cddda359460ad491edbe8d0e`;
its FAILED status preserves the original bad series, while cleanup is verified,
log streaming drained completely and no cleanup failures occurred. Independent
container and anonymous-volume absence checks are in `independent-cleanup.json`.
Canonical correction receipt SHA256 is
`9dd6168a5e377ece968fda71ca8a8353d01bcac6be9883dce67fa091e302a3d1`;
valid heavier-session receipt SHA256 is
`584f00e3cd4c98f7bb02170616b5972ecb4751f827d3d2a5cd468acbc1852dbe`.

The future helper now explicitly records pre/post statistics and ANALYZEs only
its owned ingestion tables before timing by default; an explicit restored-only
mode is labeled diagnostic. It installs canonical SQL003 before SQL004/008 and fails
before timing unless all five query-view contracts, all validation-wrapper
fast-path hashes and all four complete captured/live manifests pass. A failed
job stops scaling and reports no successful throughput. Every intended EXPLAIN
must pass before a profile is accepted; failed acceptance exits nonzero after
preserving the final receipt and attempting cleanup. Future runs copy/hash the
executing helper at launch. These safeguards were added after the original failed series;
that series was not silently relabeled. Four focused parser/preflight/failed-job
tests plus three existing parametrized cleanup-failure cases passed (seven
checks). Ruff and Python compilation passed. No heavy experiment was repeated
solely to exercise the future helper.
