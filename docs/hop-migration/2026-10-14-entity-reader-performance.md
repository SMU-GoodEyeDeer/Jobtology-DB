# Entity-reader fact worksets — October 14

Status: the three-artifact SQL009 rollout and separate independent production
readback are VERIFIED. Live five-snapshot/two-worker validation PASSED. Isolated
reader, semantic and warm replay checks passed, and owned-resource cleanup is
complete. This is the current checkpoint in the [handoff](current-handoff.md).

## Scope and preservation

The previous SQL008 Nara entity plan retained a left nested loop that rejected
5,963,010 posting-key pairs. SQL009 replaces the separate filtered JOB-ALIO and
Nara fact worksets with one complete posting-fact workset. Each original
`(run_id, source_id, posting_id)` group remains present; conditional merges retain
the original eligibility and fallback payloads. Posting keys keep the same
`->>` text extraction. Nonposting entities retain their own normalized data.

Facts and names use separate `DISTINCT ON (identity_id)` winners with their
complete original ordering, replacing each `row_number()=1` filter. The facts
and name priorities remain independent. Existing record uniqueness and distinct
reference namespaces make the unchanged run/record tie-breakers determine the
same winner. Plain plans showed improved current-facts cardinality estimates and
a hash left join in Nara, JOB-ALIO and JobKorea; these are diagnostics, not timing
or replay-speedup proof.

Only `ingestion.graph_source_entities(text)` is eligible to change. Historical
eligibility and independent run validation remain intact, as do facts/name
priorities, latest/fallback behavior, output columns and proof contracts. SQL001
through SQL008, JobKorea SQL008, LLM SQL037, existing HPLs, prompts and frozen
matching data remain sealed. No schema, index, function execution-metadata or
global parallel-setting change is authorized.

The fixed deployment wrapper is `hop/operations/deploy_entity_reader_runtime.py`.
Its complete allowlist is SQL009 plus `graph/install.hwf` and
`graph/install_posting_dates.hwf`. Both canonical installers replay SQL001→009
and abort each failed migration. The inherited scheduler fence, fresh backup,
all 157 protected table fingerprints, complete query outputs, catalogue,
prompt/inference guards, separate readback and guarded recovery remain required.
Its `pg_proc` fingerprint excludes only `prosrc`; a permitted body change cannot
exempt execution metadata from preservation.

## Qualification

All database work uses the coordinator's single restored PostgreSQL 18 fixture
under sequential leases. The supplied local archive and one explicitly analyzed
statistics state are fixed across comparisons. The semantic oracle uses a
temporary schema-only database inside that same container. Source URLs,
provider calls, paid calls, production database queries and production graph
writes are outside this qualification.

The preceding 442-case native oracle remains immutable baseline evidence for
the unchanged contracts. A separate SQL009 oracle adds complete typed
SQL008/009 comparisons across eight synthetic source runs and pinned
`ALL_CHECKPOINTED` history. Focused posting-stage checks compare complete result
bags and independently require merge precedence, incomplete/inactive/NULL
fallbacks, nonposting payload preservation and unchanged NULL-form rejection.
Latest/history, blank names, timestamp ties and numeric/string/boolean/array/
object posting keys are compared against the immediate SQL008 baseline;
duplicate and NULL form validation must still refuse invalid runs. Exact
migration body and metadata gates remain part of the proof. The frozen standalone
oracle passed all **41 new checks**, removed its temporary database and exited.
The preceding 442 checks are referenced baseline evidence, not rerun or added to
this count. There was no failed SQL009 semantic attempt.

Native SQL009 qualification is scoped to actual Hop installation of both
canonical installers and balanced complete warm Nara replay. Both installers
passed before any replay, preserving all 157 tables and fixed statistics; no
Hop comment-form correction was required. Exact complete real
JOB-ALIO and JobKorea entity/owner reader bags cover the changed function. The
previously verified full native JOB-ALIO replay and fresh three-line JobKorea
regression remain retained evidence for unchanged transport/import behavior;
they are not new SQL009 native runs.

The focused generator/wrapper/installer/source/date host suite passed 76 checks.
The final generator/wrapper/native-harness subset passed 47 checks. Targeted
Ruff and compilation passed. Counts from overlapping subsets are not summed.
Separate production readback and live validation passed.

The final candidate bundle is frozen for qualification:

| Artifact under `hop/` | SHA256 |
| --- | --- |
| `graph/sql/009_reader_fact_worksets.sql` | `efb7b4e31c1a43e7b00f735aa461d8d1df86e8444671eac3a46d35b7030d1739` |
| `graph/install.hwf` | `0df6e49e879edf05358fc5bdb504756761ccec2c222a935c6603e76a2eadf3a1` |
| `graph/install_posting_dates.hwf` | `aa2fcebf0f55e4d71add0ca6d296dd34d330b36d62911208ec1d345a5a0a5d0e` |

The protected fixture root is
`~/.local/state/jobtology-hop/entity-worksets-9e820cc6efee4b49971e3e4c6a0c1ba9/`.
Its reviewer launch copies are bound by `reviewer-launch-binding.json`, SHA256
`dd0bd10b2a95d4d753b6881ef10e3423f4789d25eced48b9af6848ff1e5cccbc`.
This freezes qualification inputs; it is not production application evidence.

The one restored archive is the previous verified rollout's 943,410,518-byte
`database-before.dump`, SHA256
`060f5e3e2ee11447e2d30ee8518828e3eb559bc3ac840f92d28e52096b53fae9`.
The initial preflight's combined 157-table fingerprint reached the unchanged
60-second statement bound. That FAILED receipt remains immutable; hashing each
complete table separately resumed the same restore and analysis state. The
corrected preflight is READY. No second restore or analysis was performed.

## Complete SQL reader diagnostics

The ordered baseline-then-candidate diagnostic passed all eight complete typed
entity/owner result pairs at unchanged 60-second statement bounds. All 157
protected table fingerprints, recorded statistics and function execution metadata
remain exact. Only the entity-reader body changed. This is an ordered diagnostic,
not a balanced SQL timing experiment or a whole-ingestion speedup measurement.

| Source scope | Entities SQL008 / SQL009 | Owners SQL008 / SQL009 |
| --- | ---: | ---: |
| Nara | 6.148 / 5.254s | 4.228 / 4.070s |
| Original JOB-ALIO | 26.558 / 26.311s | 23.651 / 22.960s |
| Newer JOB-ALIO | 25.795 / 25.395s | 22.741 / 22.700s |
| JobKorea | 18.596 / 18.724s | 4.338 / 4.071s |

Plain Nara plans select hash left joins in place of the previous posting-key
scalar loop. JOB-ALIO and JobKorea complete entity diagnostics do not
establish a gain. Their remaining measured work is described below.

## Balanced complete native Nara replay

After separate priming, complete warm native replay ran in
baseline/candidate/candidate/baseline order. SQL007/008, SQL006 and 500-row owner
transport were fixed on both sides; only the entity reader used SQL009 in the
candidate. Basic native logs were recorded with no concurrent profiling. The
same borrowed PostgreSQL container and analyzed statistics remained fixed.

| Warm replay | SQL008 baseline 1 | SQL009 candidate 1 | SQL009 candidate 2 | SQL008 baseline 2 |
| --- | ---: | ---: | ---: | ---: |
| Complete wall time | 39.413s | 36.537s | 36.158s | 38.040s |

The two-sample means are **38.727s baseline versus 36.348s candidate, 6.14%
lower**. Native pipeline means were 30.037s versus 27.597s; writing 14.701s versus
13.198s and verification 10.917s versus 9.995s. This is complete warm replay of
the supplied Nara archive, not fresh
import, whole-file throughput, a global reader gain or production capacity.
The earlier 38.369s SQL007/008 mean belongs to another qualification series and
is not substituted for this paired baseline. Separate native, process and SQL
timings overlap and do not assign exclusive costs by subtraction.

Exact typed graph evidence retains 10,555 entities, zero source edges, 10,555
owners and 10,555 posting dates, plus the synthetic inferred-edge sentinel's
exact IDs and properties. Captured/live source proofs remain equal at 13,234
records/references, SHA256
`0ab6676cd7b9ab413acef2b29b6f3c978b2307d621041226e372ee15621016b2`.
Protected source/enrichment facts and fixed statistics remain exact; existing
projection replay timestamps retain their established exclusion. This does not
recreate the complete production inferred graph.

Native Hop/Neo4j resources are removed, PostgreSQL network-none isolation and
its timeout are restored, and no native cleanup failure is recorded. The current
native status is `PASSED_NATIVE_GRAPH_COSTS_COMPLETE_CLEANUP`. The owner verified
all five captured/live source manifests, unchanged statistics and all protected
facts, absence of temporary databases and other client backends, then removed
the exact PostgreSQL container and recorded volume. A reachable Docker daemon
confirmed both absent; root independently verified their absence. The complete
PostgreSQL log follower drained naturally with exit code zero at
`2026-10-14T02:01:10.346590Z`. Separate production readback and live acceptance
also passed.

The first owner audit stopped at the canonical installers' expected recreation
of `ingestion.graph_source_edge_owners(text)` (`oid` 16689→243371). All 460
signatures and other execution attributes remain exact. Its original incomplete
checker receipt is preserved. The narrow resumed audit compares execution
attributes without `prosrc`/`oid` and separately requires that sole exact OID
change and its exact body. The corrected audit passed. This is checker
compatibility with full canonical installation, not a
SQL009 semantic failure or a general identity waiver. The production wrapper
still preserves OIDs strictly because it executes only SQL009.

## Protected qualification receipts

These paths are relative to the protected fixture root above:

| Receipt | SHA256 |
| --- | --- |
| `initial-preflight-failed.json` — combined fingerprint timeout, FAILED | `a4787bf707770bb3e14b1d44f9dd30715e8dd7b81635c75945a6d4efc729f830` |
| `clone-preflight.json` — same restore/statistics, READY | `f78e964fb943a046f79acd8def9b4d607a8a6340f141a802444a0d7f65a04b53` |
| `estimated-trials/receipt.json` — exact winner-order plain plans | `49ba6a5976a3cb5a2852c11aa495d8764c3cbcc2b32f8dda08ad5a4f519d3d07` |
| `baseline-readers/receipt.json` — eight baseline bags, PASSED | `3c68e802e06c8826b437c20106dcdca409542e0aba924b280a266d3167d2449f` |
| `candidate-readers/receipt.json` — eight exact pairs/preservation, PASSED | `995985abfaa7f3e80898ce6d91156d6c742425e42c1ad00475710d8e8a5aadcf` |
| `reviewer-oracle/receipt.json` — 41 new semantic checks, PASSED | `a0ec8f7f6754d6ac72d1c89ab05c912d70152245267dca54654f0183601532c4` |
| `reviewer-returned.json` — temporary database/process absence | `6bd36d2beb5153b4f6862e8f85772431a9ed6ddebea389cd73d079ac023f34e6` |
| `owner-return-audit/receipt.json` — original incomplete checker, RUNNING bytes preserved | `f3b4798e9944ad6a35b6e71932075a9a0b0fb6e513bb3fea330f44ab19bdd0d7` |
| `owner-audit-failed-binding.json` — immutable checker failure binding | `fcec43575158dd79066a76e40000bb326c12d43664e3de3ccf70eb6e95aa7aee` |
| `owner-return-audit-corrected/receipt.json` — 460 attributes/sole OID transition, PASSED | `c1d50efb454d882502b2b2321dac6968b2fb7b8b08ebfba0f736eb0a751d6acf` |
| `owner-final.json` — exact container/volume absent and logs drained | `7d1e0d67bab2be63f30cad60032e2bfb94e734a02766d5b9a208b0bce2e739b9` |
| `log-drain.json` — natural exit zero and follower absent | `e89df0eae5ec7db81135aed16463968955c578bcc4f2ec43172eff351f080c17` |
| `final-proof-binding.json` — immutable final qualification hashes | `7a6edae18749aa51212459c4eef758b5bb6c7cbf05050b9b8efacaa9ffff2364` |

Early canonical Hop installation is sealed separately at
`~/.local/state/jobtology-hop/jobkorea-dry-run-fe783bd25a22/native-installer-phase.json`,
SHA256 `b53ee85947367b5b528e5e41ae3049e3e7893b65b92f1c0c234ae13cf134deea`.
Its status is `PASSED_CANONICAL_NATIVE_INSTALLER_PHASE`, with no replay started.

The immutable completed Nara proof is
`~/.local/state/jobtology-hop/jobkorea-dry-run-fe783bd25a22/receipt-precleanup-completed.json`,
SHA256 `fb5aab99917db4d47d32005e77588633955c1889699ab4230186f9c98e454bbf`.
Its pending-cleanup status is retained byte for byte. The final `receipt.json` in
the same directory binds that proof and final cleanup, SHA256
`2633cb4b035916f9c47503179677d008d5b869bcfa0ff2d4be4247241d50d0b5`,
status `PASSED_NATIVE_GRAPH_COSTS_COMPLETE_CLEANUP`.

The reviewed production plan is
`~/.local/state/jobtology-hop/additive-runtime-plan-ac29b427c1284955a97b3bf3600b088e/manifest.json`,
SHA256 `741be4f0ee6844783df69286096cc501ec84f06dd2d00fb7b3d0b5cc4eaf40a8`.
It binds the exact three artifact hashes, all 157 tables and all 460 existing
function metadata entries including OIDs.

## Production rollout

Guarded SQL009 application reached `VERIFIED_ADDITIVE_RUNTIME` at
`2026-10-14T02:08:25.125278Z`, with the scheduler fence removed. Fresh before/after
rows, complete query outputs, schema/index state and catalogue context match.
All 157 full protected table fingerprints and all 460 existing function
execution-metadata entries,
including OIDs, remain exact. Only the existing entity-reader body changes;
the exact three runtime artifacts match the reviewed plan. Separate independent
readback passed at `2026-10-14T02:09:41.489080Z`. No source HTTP, provider/paid
call or production Neo4j write occurred.

The immutable application receipt is
`~/.local/state/jobtology-hop/additive-runtime-applied-519573c8167b47e9903f6302fe3ad5ef/apply-verified.json`,
SHA256 `7e5fbfa21bfc8a5127b50c1eba0a2023334c7bef74158d8212733d0ace94c0f4`.
The final separate-readback receipt is `receipt.json` in that directory, SHA256
`0e7ed0dea0b129e84b32dbb3a6b781c1ec2f8818cc1a773aa383030500251ec9`.

Live read-only validation passed five snapshots across four sources with two
actual workers in **11.670447s**, finishing at `2026-10-14T02:09:59.938078Z`.
The complete result SHA256 is
`d0202676c7bf01a99f290e625c3909664a6245ff6dbf05b905f6c9b8aec38636`,
equal to the preceding five-snapshot proof. Worker and all operation backend
absence are verified, with no errors. This is live compatibility evidence,
without a paired live speedup claim. The actual scheduler fence is absent and
production is idle.

Live validation is sealed at
`~/.local/state/jobtology-hop/source-proof-validation-05afee21a1ad4e4ca2711267423f5004/receipt.json`,
SHA256 `ab73b8106187b0443e1f46c5a53470365eb2fd3883b5c8c1eb8f1b616993eb5f`.

The fresh full custom-format backup is 943,415,325 bytes, SHA256
`7937c1789da3c69734d0c3f10e2071aa896b7bd0beee6df77d10291de8454aa4`.
Its validated archive listing is a recovery artifact, not another isolated
restore qualification.

## Limits and next evidence

The preceding qualified warm Nara mean was 38.369s after SQL007/008; complete
JOB-ALIO warm replay remained about 169s without a paired gain. Those earlier
measurements do not establish SQL009 performance. New comparisons must use the
same source scope, statistics and function/transport baselines, record complete
typed output equality, and preserve failed receipts before any correction.
Three-line fresh JobKorea compatibility does not establish whole-file import
throughput. The older 84/86-run observations remain unexplained.

Baseline JOB-ALIO raw entity SQL measured 25.975s, while a separate standalone
precondition diagnostic measured 0.344s. Its internal entity owners stage compared
673 touched identities with 33,512 materialized references and rejected 22,536,584 identity
pairs; 35 historical run validations remain. A safe next hypothesis is a
bag-preserving materialized reference join to the unique touched identities
before the owners source/kind filter, retaining the exact validation runs and
winner ordering. This is measured follow-up work, outside SQL009.

Baseline JobKorea complete entities measured 18.596s, raw SQL 10.522s and a
separate standalone validation 7.304s. These are overlapping diagnostics and
cannot be added or subtracted to assign exclusive stage cost. VERBOSE plans also
show repeated facts-JSON rendering for the payload and hash. No further entity
body edits, narrowed historical eligibility or global speedup claim follow from
these observations.
