# Current Hop migration handoff

Updated: **2026-10-25 UTC — repository-only crosswalk timeout correction.**
Additive ontology SQL 036 materializes occupation pairs, resolves distinct pinned
endpoints, and batches exact NCS occupation aggregates into one READY catalogue
record scan per pin. Its private bounded source-observation overload pushes
wanted IDs before source selection/aggregation and skips unrelated sources;
existing no-argument readers remain unchanged. Unpaired anchors need no source
freshness work. The original production SQL 034 plan pushed catalogue-node
checks down to individual posting rows; the 2,002-association regression proves
2,004 old single-node calls versus one O*NET call and one NCS batch scan.
Original SQL 033/034/035, full-input revalidation, original pins, source freshness
and actual review semantics remain unchanged. Thirty-nine focused PostgreSQL 17
integration/installer/deployment tests pass, including exact legacy JSON,
NULL/old/new/unavailable pins, source namespaces/deltas and migration replay.
Read-only production **inline full-reader** candidates completed under the
unchanged 5s bound: NCS `20010202` returned 21 total / 6 items in 3.844s wall;
O*NET `15-1252.00` returned 99 / 6 in 4.738s, and its `limit=100` page
returned all 99 in 4.957s. Shared-body plans read 15,520 pinned
NCS records once for 22 / 100 endpoints; no installed-reader/HTTP or cold/loaded
latency guarantee is established. The canonical installer and deployment
allowlist append SQL 036; see the
[operator command](../../hop/ontology/catalog.md#crosswalk-reader-performance-upgrade-sql-036).
No production mutation, paid call or job-board HTTP was performed. Deployment
and installed-reader verification remain pending.
Protected receipt:
`~/.local/state/jobtology-hop/crosswalk-reader-20261025T052259Z/receipt.json`
(mode `0600`), SHA256
`6675d263285386dc4d4511a89957c195d7e6013232c256d886d7848522a6fe99`.

Updated: **2026-10-21 KST — read-only production NCS pin comparison verified.**
At database transaction time `2026-10-20T15:52:51.053887+00:00`, the report's
bounded read-only snapshot confirmed current NCS pin
`26b8f6cc-c32b-4e3a-a529-a37a329b898b`. All six selected occupations proved
identical normalized SQL 036 target content against their original frozen
catalogue hashes: **2,309 published associations** are
`PIN_CHANGED_CONTENT_EQUAL`, with zero `TARGET_CHANGED`, `TARGET_MISSING` or
`UNVERIFIABLE` results. Codes `20010202` (1,855) and `20010204` (35) account for
1,890 associations; the others are `20010105` (95), `20010207` (40),
`20010703` (126) and `20010705` (158).
This establishes selected-target normalized catalogue equivalence only;
model quality, full retrieval catalogue and inference-context equivalence remain
unassessed. Original pins, **STALE** freshness and review states remain unchanged.
No deployment, database mutation, paid call or job-board HTTP occurred. See the
[comparison checkpoint](ncs-pin-revalidation-report.md#verified-production-comparison).
Protected receipt:
`~/.local/state/jobtology-hop/ncs-revalidation/report-20261020T155251Z.json`
(mode `0600`), SHA256
`4c8206c2585ff8778851134fe52085d4c52645a85fea24dab5fcb2e3d188dad8`.
The repository-only checkpoint below predates this production comparison.

Updated: **2026-10-21 KST — repository-only NCS pin comparison report.** The new
[read-only report CLI](ncs-pin-revalidation-report.md) accepts an exact current
run ID and bounded occupation codes, discovers backend cohort pins, proves old
frozen SQL 036 catalogue hashes against archived READY normalized rows, and
compares current target content in one bounded read-only snapshot. It reports
equal content, changed/missing targets or unverifiable evidence, retaining
original pins and STALE status. It does not claim model quality or full v2
context equivalence, and makes no paid/source requests. The 22 focused unit tests
and nine actual PostgreSQL 17 synthetic integration checks passed in a separate
disposable test database; no production comparison or mutation was performed.

Updated: **2026-10-20 KST — repository-only source audit corrections; final
current-SQL checks passed, including filter pushdown.** SQL 031 now preserves JobKorea delta omissions using
the latest accepted native-ID observation across READY non-SMOKE runs; every
posting carries its exact observation run/time. ALIO IDs remain bare, Nara's
current complete observation uses `nara_job:<native-id>`, and JobKorea retains
first source priority. CLOSED/null-deadline, fixed-instant KST boundaries,
application starts, invalid calendar dates, explicit deadline/status metadata and
policy-labelled ongoing are handled by the public projection. SQL 032 adds a
separate bounded inferred-occupation context reader with actual review/confidence
states, source/catalogue pin freshness, safe current posting previews and counts
by source/occupation. It changes neither sealed release artifacts nor approved
competency/product-role evidence. The installer, deployment allowlist, restricted
grants and focused fixtures are updated. After the provenance source-ID/detail-run
and minimal upgrade-grant follow-ups, the coordinator's final disposable
PostgreSQL 18 run passed both the live feed and inferred context SQL projection
suites, including the native-shaped optional O*NET reader branch. The temporary
container and source staging were removed. The 40 focused local deployment,
installer and READY-statistics unit tests, Ruff on changed Python files, Python
compilation and whitespace checks also pass. A subsequent SQL 032 optimization
passes occupation filters into the private inference adapters, skips unrelated
schemes and hashes only matching posting observations for the needed comparison.
The coordinator reran both suites on the optimized current SQL in disposable
PostgreSQL 18; the expanded filtered-equivalence, skipped-branch and restricted-hash
regressions passed. All 29 actual SQL JSON responses also passed the backend
`Posting`, `Postings` and `OccupationContext` models. The disposable container and
source staging were removed after this final run. No production timing
improvement is claimed. These are synthetic reader checks;
they do not establish updated production counts or a new graph publication.
No production mutation/deployment, job-board HTTP or paid inference occurred.

Earlier checkpoint: **2026-10-20 KST — repository-only JobKorea live catalog
correction, superseded by the source audit corrections above.**
Additive `031_multi_source_live_postings.sql` extends the existing posting list
and detail functions to selected, metadata-accepted JobKorea local listings from
the latest READY non-SMOKE run, alongside the existing ALIO paired records.
JobKorea sorts first before pagination and uses `jobkorea:<native-id>`; ALIO IDs
remain bare. Items carry `source_id` and responses retain exact run provenance.
Unknown dates remain null, and import completion is not collection time.
No NCS classifications, descriptions or verified employer identities are inferred.
The canonical installer appends 031 and the focused live-feed fixture covers
ordering across a page boundary, collisions, filters, latest-run selection,
selected/accepted exclusions, source availability, replay and restricted grants.
The canonical `run.boot(); live_feed.check()` passed on Goldship in a disposable,
network-disabled PostgreSQL 18 container limited to 512 MB and one CPU; the
container was removed afterward. This passed the original ALIO/exam checks and
the new multi-source checks. The 18 deployment/workflow unit tests, Ruff on the changed runtime/test
Python files, Python compilation and whitespace checks also passed. At this earlier
checkpoint, a read-only inline candidate against the then-latest real runs
returned 8,890 postings (8,434 JobKorea plus 456 ALIO postings from
912 representations), with all first 20 IDs namespaced to JobKorea; its response
passed the strict backend `PostingsResponse` model. This historical two-source
sample excludes Nara and does not describe the final projection's current total.
This readback did not install the functions. No production mutation, deployment, source HTTP or paid call
occurred. An already compatible catalog needs only SQL 031 for this correction;
existing function grants are preserved.

Updated: **2026-10-16 KST — admin dashboard release preparation.** The user
requested an eight-character minimum dashboard password and authorized commit
and push of the dashboard changes. Configuration, validation tests and operator
documentation now require at least 8 password characters; the independent
session-signing secret still requires at least 32 characters. The 8 focused
authentication tests, Ruff and whitespace checks passed. The prior deployed
revision `18abac0` predates the dashboard; a new revision must be built and
deployed before the dashboard is available. Commit, push and deployment remain
pending at this preparation checkpoint. The 31-test verification checkpoint
below is retained as historical evidence.

Updated: **2026-10-16 KST — repository-only admin dashboard; production remains
unchanged.** The same repository now includes an authenticated ingestion/graph
dashboard, explicit Coolify Railpack configuration, bounded read-only telemetry,
and a durable approved-action queue with a separate host worker. The dashboard
uses its own login; Coolify manages the intended `jobtology-admin.yeongmin.net`
domain/TLS. Controls default disabled and require reviewed local profiles plus a
live worker. Only the existing due-source refresh and approved local JobKorea
loader are dispatchable; no paid inference or job-board content recovery was
added. See the [dashboard runbook](../admin-dashboard.md).

The 31 admin tests, Ruff, strict Pyright, fresh development installation and full
test collection passed. Disposable PostgreSQL 18/Neo4j 2026.06 actual-driver
fixtures validated the documented column grants, source/ontology duplicate
exclusion (including ontology nodes also labeled `entity`), ledger SMOKE
exclusion, prior READY visibility after failure, and summary counts. A bounded
real-process worker check with a harmless stub passed authenticated API enqueue,
RUNNING/disabled controls, graceful drain, SUCCEEDED and private 0600 logs;
it did not execute either ingestion script.
Chromium desktop/mobile flows and simulated action/CSRF/idempotency/error paths
passed without JavaScript errors or external page requests. The built wheel
contains the app and three static assets. Railpack 0.42.0 schema validation and
plan preparation passed; no full image build or Coolify deployment was performed.
Live progress percentages are unavailable; the UI shows reported run states and
only renders percentages when explicitly supplied. There were no production
database grants, refresh/load operations or provider calls, and no commits/push.
Protected verification receipt:
`~/.local/state/jobtology-hop/admin-dashboard-20261016-45b75d2d5a52/receipt.json`,
SHA256 `5a1bfbd665119230a98f406847de6eda7c580a3ad5d1f2ea48a06abd57495ded`.

Updated: **2026-10-16 KST — repository-only integration fixes; no deployment or
runtime change.** The runtime deployment allowlist now includes
`028_product_role_demand_base.sql`; regression coverage checks real-package
staging, unchanged-dependency drift rejection, private-file preservation and
idempotent replay. The catalog runbook now installs both distinct `028_*.sql`
files followed by `029_flat_catalog_compatibility.sql`, then grants; reader-only
upgrades remain separate. The 54 focused tests and Ruff passed. A disposable,
network-disabled PostgreSQL 18 fixture with synthetic approval/flat proof metadata
reproduced the old sequence's `CATALOG_FLAT_COMPATIBILITY_REQUIRED` failure. The
corrected documented sequence and replay preserved exact reader JSON and all 140
application-table contents; the role reader retained `linked_postings` and
restricted grants. The container was removed. This does not establish Neo4j,
native-load or production verification.
Receipt: `~/.local/state/jobtology-hop/merge-integration-check-f82cdf5c8fba/receipt.json`,
SHA256 `cf0d8f39dd3a3a5ac1a522e79a714198fdd4a692d6c4cd6de4b37ba0240b7961`.

Updated: **2026-10-16 KST — read-only JobKorea assessment; production remains
October 15 VERIFIED and unchanged.** See the
[future-import assessment and TODOs](2026-10-16-jobkorea-future-imports.md).
Current imports are manual, supplied-local-file NDJSON operations with stable
posting IDs and source deltas; postings omitted from a later file are retained.
Two correctness gaps remain: a later import time can promote an older export,
and source updates do not automatically invalidate or rematch inferred links.
Priorities are explicit freshness/promotion rules, an incremental NEW/CHANGED
enrichment queue with stale-link handling, posting-specific technology mentions,
inference quality/recall review, and measured preflight/verification performance.
These are proposals, not implemented changes or authorization for new paid
cohorts; the historical NCS $5 and original 22,635-posting O*NET $40 scopes do not
authorize future arrivals.

October 16 bounded coverage readback records **8,434 JobKorea postings**:
7,443 have an inferred NCS or O*NET occupation category, 5,781 reach occupation
reference details, and zero have direct posting-specific technology-skill links.
Categories retain their actual review status and are mostly unreviewed;
occupation reference details do not establish employer requirements. Receipt:
`~/.local/state/jobtology-hop/jobkorea-coverage-20261016/readback-2e6b2f9d16124dfcb48092013c6643ff/receipt.json`,
SHA256 `a4b028afaaccb94d7541be5f4d53885d3eaa372063a33193bff225b3a4607ae0`.

Updated: **2026-10-15 KST**. O*NET 31.0 SW/IT reference details are
**loaded and independently VERIFIED at 12:09:01.616752 UTC**: 2,598 new
nodes and 18,609 relationships for 30 detailed occupations within the 31-term
scope. All 187 preexisting PostgreSQL tables/metadata and all 203,145 existing
nodes/767,984 relationships are preserved exactly. The resulting graph has
205,743 nodes and 786,593 relationships. Native load
`06f23410-c139-4dbf-9517-c24daa86a567` is VERIFIED; the operation fence was
removed. There were zero source, provider or posting-matching calls.
Production receipt:
`~/.local/state/jobtology-hop/onet-details-load-6ddc16c10052421288bef1cbb80ece2c/receipt.json`,
SHA256 `412ef210b50e74f348cd2470b9b3273be21df2741137664dc8a7788c0df34056`.
Final native qualification passed 42 checks with cleanup; 130 focused tests,
Ruff and whitespace passed. Bounded consumer readback is **VERIFIED at
12:09:19.412373 UTC**: 30 enriched occupations/16,472 direct observations and
5,908 existing scoped links on 5,835 postings, all matching current source-fact
hashes. Readback receipt:
`~/.local/state/jobtology-hop/onet-sw-it-local-assessment-20261015/postload-readback-a60c08030bd94ad195132749953ae67d/receipt.json`,
SHA256 `5cf25ff3d034491e4a2aeeed471ee1cb8a696eb68f2b157ac123db88c4a6cec9`.
The original 143-byte scheduler is unchanged.
The separate Nara schedule completed naturally at 11:24:51 UTC; no cancellation,
ANALYZE or recovery replay was performed. Remaining performance work includes
its 2,822.874s owner verifier and the detail load's 576.104s relationship
preflight within a 628.612s native workflow; live operator causes remain
unprofiled. See the [assessment and load report](2026-10-15-onet-sw-it-details.md).
The October 14 matching checkpoint below is retained as historical evidence.

Updated: 2026-10-14 KST. O*NET posting linking is COMPLETE and independently VERIFIED at 13:18:58.737389 UTC: 12,696 posting links on 12,514 of the 22,635 unique original source postings; 10,121 have no allowed link. All 5,878 NCS links and the exact current source facts/provenance are preserved. The exact original scheduler was restored by stdin/readback at 13:19:49.941248 UTC. Shared known cost including every trial is $14.22945107, with $0.0189965 provisional timeout exposure and a $14.24844757 accounting bound under the $40 cap ($0.6286481586/$0.629487412 per 1,000 original postings). All links are STAGING/current=false with NULL/UNASSESSED confidence: 1,234 ASSISTANT_REVIEWED and 11,462 UNREVIEWED. The 94 later arrivals and 1,014 duplicate ontology representations remain outside the matching scope. Remaining work is separate recall, stale-link invalidation and controlled performance follow-up.

O*NET reference catalogue production remains VERIFIED at 05:48:02.915351 UTC. SQL009 entity-reader rollout/readback remains VERIFIED at 02:09:41.489080 UTC, with live five-snapshot/four-source/two-worker validation PASSED at 02:09:59.938078 UTC. Earlier SQL007/008 capture/reader, routine performance, source-query, batch-free and ontology revision rollouts remain VERIFIED; later rollouts supersede the runtime bytes specified below. Initial repository assessment: `df11696` on Goldship at `/home/maxjo/Jobtology-DB`; the scheduler and mounted-installer repair was subsequently deployed from the working tree. This is the current operational checkpoint; older status documents remain historical evidence.

## O*NET posting-link authorization (October 14)

Latest checkpoint: **COMPLETE; both publications and strict combined graph verification VERIFIED, scheduler restored**.
Final verifier:
`~/.local/state/jobtology-hop/onet-matches/20261014T131612Z-independent-graph-acceptance-2dc174efae95/receipt.json`, SHA256
`510c4e4d72960264c7bd9b5e64386e7aac7dfd50f22d2fe0a3ffcebbf7db9907`.
It confirms all 22,635 terminal outcomes (18,589 VALIDATED/3,990 SKIPPED/56
technical REJECTED), 22,729 current source postings, 202,983 nodes, 767,932
relationships, 5,878 NCS links and 12,696 owned O*NET posting links. Exact
source facts/provenance, endpoints, typed edge properties, current catalogue,
actual review status and both task-specific native checkpoints passed.
Scheduler restoration:
`~/.local/state/jobtology-hop/onet-matches/20261014T131949Z-scheduler-restored-afa7da9ac641/receipt.json`, SHA256
`820aa948bef3a10d0aad32046899aeceaf75253d449f3b9cb44b2d03055d8e16`.
The restored original has 143 bytes and SHA256
`5c932e4bc2b6024dcba2945d226491af227e608aee71178d1f9e0d7b784999fd`.
Source linked-posting/link counts are ALIO 450/452, JobKorea 6,613/6,712 and
Nara 5,451/5,532. The 178 multilinked postings comprise 174 doubles/four triples.
Continuation raw cost is $13.56521358; all 18,167 continuation paid calls used
BYOK with router cost $0. The user-reported $45.90 upstream balance is not
API-verified, and the earlier timeout is not established free.
Continuation receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T130203Z-publish-9562745e9914/receipt.json`, SHA256
`2b9b83fe78b427c053638c10430f6f267c49dbb22eff2eccc3463c41fd1d93e1`.
It is COMPLETE at 13:15:29.111609 UTC, binding native publication
`ae171523-d6c6-4201-b231-26dbec1c4d44`, VERIFIED for 12,386 links at
13:14:09.809502 UTC, with no remaining graph writer and preserved legacy counts.
Recovered publication receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T130124Z-verified-publication-recovery-413601592376/receipt.json`, SHA256
`e7ddfffc9026cef5e2aa30d4d909039f0a6a172b019ce0b77020f8b84a5a548d`.
It binds the native VERIFIED publication `5cac284c-10c9-4624-a963-f650b6bef147`,
which wrote and checked 310 links at 12:38:14 UTC. Recovery performed no repeated
graph writes. The accepted combined PostgreSQL plan has 12,696 links on 12,514
unique original postings, including 178 postings with multiple links; the
remaining 10,121 original postings have no allowed link. The final independent
Neo4j check above verified these combined plan counts.
Application: `~/.local/state/jobtology-hop/onet-matches/20261014T123301Z-full-individual-decisions-60a45b0b8059/receipt.json`, SHA256
`cf18ae541ce2a67db263e0f1bc93175e0d8480916a84620c7b81ac3d3b7e0a71`.
It inserted 905 ACCEPT/727 REJECT actual new per-edge decisions, preserving all
23,243 original O*NET attempts, full function metadata and 404 prior review rows,
including the already committed 19 ACCEPT/5 REJECT fresh pilot. Exact final
review covers all 1,608 risk IDs, 90 controls, 103 changed-source inputs, actual
physician and multimatch proposals, and the bounded road-driver/nutrition/PA
extensions. All other ordinary proposals retain STAGING/UNREVIEWED status.
The first publisher failed before launch on a host parameter-name check;
`~/.local/state/jobtology-hop/onet-matches/20261014T123322Z-publish-b7c0661975ca/receipt.json`
records no prepared graph guard/writer and no graph write. The qualified host
fix admits digit-containing native parameter names. A subsequent native success
was incorrectly reported FAILED because the host expected its own publication
ID instead of adopting the native UUID; exact read-only adoption now resolves
that handoff. Full-plan preflight also enumerated graph rows twice for count/hash
and reached the 120-second deadline; the qualified host fix aggregates both in
one pass. All 45 focused tests and Ruff passed. Native 22 artifacts, frozen
requests and paid outputs remain unchanged.
Host qualification:
`~/.local/state/jobtology-hop/onet-host-publication-adoption-mmeffmt2/qualification.json`, SHA256
`4a974f007e13f44d499e714efea397f9822ea14537c838f452d8ed756be21a7d`.
Continuation publication is COMPLETE under the receipt above.
A later controlled performance follow-up should profile
`graph_rows` joins/payload work and repeated immutable-plan verification,
preserving exact ordered hashes and detection of source/review changes.
Whole audit: `~/.local/state/jobtology-hop/onet-matches/20261014T120941Z-output-audit-7e2aed5f2415/receipt.json`.
It verified all 22,099 outcomes, 18,167 BYOK calls/router $0, 12,712 matched
postings and 13,118 proposals before individual semantic rejections. Current
continuation raw cost is $13.56521358. Shared known/bounded cost per 1,000
original source postings (22,635 denominator) is $0.6286481586/$0.629487412.
The full supervisor ran 11:18:31.088274–12:08:34.053000 UTC, 50m 2.965s,
for 22,063 bulk inputs after the separate 36-row pilot; this is an operational
throughput observation, separate from ingestion-query performance.
All 23 completed batches also passed independent technical audits; semantic
review records actual individual decisions and no-edge coverage, without
blanket review status. Road-driver service/vehicle precision, explicit
nutrition-teacher boundaries and Physician Assistant substitution received
bounded post-output review extensions; these were not preregistered risks.
Full receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T111831Z-full-806df7f0c2b1/receipt.json`.
Frozen continuation manifest:
`~/.local/state/jobtology-hop/onet-matches/20261014T110527Z-freeze-a8a60f7e0e8c/manifest.json`, SHA256
`c34f490f582cb0b981c44ab366986c4e59be7934930c6ee7a8e61351645300d3`.
Preparation and all-row dry checks passed: 22,099 inputs, 3,932 empty shortlists,
largest conservative request bound $0.0084861525 below the $0.02 reservation.
The fresh pilot completed 31 paid BYOK calls/router $0, 31 VALIDATED/5 local
SKIPPED, 23 matched postings/24 proposals, costing **$0.02847970**. All 24
proposals were individually reviewed and 19 ACCEPT/5 REJECT committed. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T111724Z-physician-pilot-individual-decisions-4d9642484ab9/receipt.json`.
Scale approval:
`~/.local/state/jobtology-hop/onet-matches/20261014T111750Z-approve-scale-5fadb82b36e7/receipt.json`.
The final preregistered risk queue has **1,608 exact current IDs**
(132 ALIO/558 JobKorea/918 Nara), SHA256
`213ffd7507f6104b4d64dd984c8e12ffcd5f43dd22ad5a5e3a8ba6fcbf2fb656`, at
`~/.local/state/jobtology-hop/onet-physician-continuation-risk-preregister-5wnxq7ps/risk-queue-qualified.json`.
Individual review covered that queue, all 103 changed-source inputs, every
actual guarded physician proposal, every multimatch and the unchanged 90
ordinary controls, including the bounded dynamic risks outside the queue.
Ordinary allowed bulk links stay STAGING/UNREVIEWED; confidence remains NULL/
UNASSESSED. Each completed batch and the whole final scope passed independent
technical audit. The prepublication combined graph check passed the pinned
current baseline: exact 22,729 current/22,635 original source IDs, 202,983 nodes,
755,236 relationships, 5,878 NCS links and zero O*NET posting links. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T111139Z-independent-graph-acceptance-7ad8f0cbffa4/receipt.json`.
This historical zero-link check precedes the original task's 310-link publication.

The checkpoints below preserve historical states and completed operator actions;
their pending/held instructions are superseded by the verified completion above.

Historical regression-500 checkpoint: it completed transport/Python audit but
received semantic NO_GO for 22 clear physician errors (16 internal-medicine,
four family-medicine and two emergency-medicine), plus separate boundaries
such as bare endoscopy without internal-medicine evidence. It has 443 VALIDATED, 56 local
SKIPPED and one REJECTED result, with 444 paid BYOK calls/router $0, costing
**$0.36653687**. Its $0.73307374 per 1,000 sample listings is a regression-sample
metric, not a population estimate. Original v4's 536 terminal outcomes are
476 VALIDATED/58 SKIPPED/2 REJECTED; shared known cost is **$0.66423749**, with
the same $0.0189965 provisional exposure and **$0.68323399 accounting bound**.
The native run finished at 10:29:50 UTC. Receipts:
`~/.local/state/jobtology-hop/onet-matches/20261014T102735Z-resume-9d1e909ff5e7/receipt.json` and
`~/.local/state/jobtology-hop/onet-matches/20261014T103022Z-output-audit-75f73b378a5c/receipt.json`.
Medical review found generic physician/surgeon evidence being classified as
general internal medicine, including 16 clear mismatches among 22 reviewed
internal-medicine proposals; a focused deterministic physician-eligibility
successor is authorized for the remaining 22,099 original IDs only, under the
same model/schema/routing/native artifacts/$40 shared cap. At that historical checkpoint, new paid calls were held pending the qualification
and its own fresh 36-row pilot; both subsequently passed and FULL is complete. The original
536 completed IDs, including SKIPPED/REJECTED, must never be retried. The 94
later arrivals stay outside scope. Continuation source-partition proof:
`~/.local/state/jobtology-hop/onet-v4-continuation-cohort-i6wqhhio/proof.json`, SHA256
`e3860abd93c0a8fbe7dfc169abcc016ed8fb6efd3fd87e535180862c2df665a0`.
This offline partition is not a terminal/STOPPED runtime attestation. The
coordinator durably stopped original v4, preserving all 536 terminal states,
478 paid calls, attempts/decisions and legacy/function hashes. Stop receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T104100Z-v4-stop-current-handoff-4951f84a8787/receipt.json`, SHA256
`639977063f4c26009a4d00c0301be3726fd4271d737a02ef06fa47e83e5e9787`.
Continuation prepare/execution must independently replay the exact STOPPED and
terminal-selection gate. New task identity:
`onet-metadata-20261014-current-physician-guard-v1`.

Later recall work may address safely abstained English role titles such as
Flutter Engineer, NPU Compiler Engineer, Data Engineer/Data Platform and AI
Research Engineer that lacked local shortlist coverage. Do not broaden this
medical fix. Separately design automatic stale-link invalidation and review
semantics for STAGING relationships with `current=false`; manual inspection
must not filter such inferred links with `r.current=true`.

Earlier pilot checkpoint:
Reviewers recorded 19 ACCEPT/3 REJECT decisions on all 22 validated
proposals. The native duplicate-rank REJECTED attempt stays excluded, without
retry. The coordinator committed the atomic/idempotent per-edge decisions;
all 644 original attempt rows and full function metadata remain unchanged.
No bulk review status is granted. Application receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T095503Z-v4-pilot-individual-decisions-c491e600dbd7/receipt.json`, SHA256
`2b338b208da6692744db4b7b700efb5e7e6aedc80d03be68d77e2b2effb8c594`.
These decisions review frozen evidence; current-graph acceptance remains a
separate check. Review evidence:
`~/.local/state/jobtology-hop/onet-v4-pilot-semantic-review-_v_ouqw2/review.json`, SHA256
`e64960eba23cf9ceeba5f7ea2ca6267b8c7b8b291a28c21afef0b5c11753cfa2`.
The exact next 500 are source-balanced 167/167/166 and exclude all current pilot
IDs; they deliberately overlap 477 earlier v3 sample rows/248 prior paid rows.
They are a regression sample, not an unseen holdout or population estimate.

The cron adapter runs every 15 minutes. It acquired `refresh.lock` at 09:15 UTC
between matcher stages. The coordinator recovered its accepted Nara snapshot
with an archive-only native graph replay, verified READY at
**10:14:39.406952 UTC**, with checkpoint **10:14:40.650653 UTC**. The native
workflow took **713.403 seconds**; source requests, paid counts, all 40 frozen
source pins and the source READY-row hash were preserved. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T100244Z-nara-archive-replay-0350b359c75d/receipt.json`, SHA256
`5ae49a81e5a0683df3d7a8140ea17376332db5f04b66682719fa3d8902c62500`.
Future cron invocations were temporarily paused with all other crontab bytes
retained; exact restoration is now complete under the receipt above. Pause receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T092908Z-scheduler-paused-f098503f1750/receipt.json`.
The completed restoration used **stdin**, requiring the paused SHA and
original-byte SHA to match the protected files. Retained historical recipe:
`~/.local/state/jobtology-hop/onet-matches/20261014T092819Z-scheduler-pause-prepared-5c14e4cf2610/instructions.txt`.
Do not silently relax source-fact, provenance or graph baseline checks.

The independent read-only comparison found **202,983 nodes (+94), 755,236
relationships, 5,878 NCS edges and zero O*NET posting links**, on the exact target DB.
All original identities/kinds remain. ALIO/JobKorea facts and provenance are
exact; Nara has 10,173 provenance-only changes, 2,460 exact rows and 103 changed
facts (101 prompt-field changes, two other changes). The 103 inputs must not be
called or published against stale evidence. The pilot36 and preregistered500
each intersect zero stale inputs; 94 later arrivals stay outside the frozen
cohort. Native 22 artifacts and the 40 prior source proofs remain exact.
Assessment:
`~/.local/state/jobtology-hop/onet-v4-postrefresh-assessment-_g8lgqok/final-receipt.json`, SHA256
`ff696503f50066288522f34fea308375cdf83db6bcc4f5cf644ab6f4906bc997`.
The independent verifier now supports an explicitly checksum-bound current
baseline and exact disjoint task union; the combined unpublished check above
passed without weakening source-fact or owned-edge checks. Original defaults
retain the pre-refresh baseline.

Performance follow-up: after targeted ANALYZE of `ingestion.record`, `run` and
`graph_export` with definitions/query files unchanged, the fresh prepared
read-only Nara owner query returned all **10,370 required owner rows** (empty
expected-edge keys) in **0.580 seconds**. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T095307Z-nara-owner-read-after-analyze-6ebc9713b919/receipt.json`.
The archive replay then measured names 6.718s, posting-date load 460.013s,
owner clear 1.144s, names verification 6.910s and posting-date verification
230.826s. These are operational observations, not a controlled speedup ratio.
Define planner-statistics maintenance expectations after READY ingestion and
measure fresh native date/owner stages before proposing further changes.
Nara owner rows are required for stale cleanup; only the nested edge reader is
empty. Historical-reference/validation work remains a secondary isolated
optimization candidate, with exact zero-edge/latest/fallback/proof parity.

Prior technical checkpoint: the four-worker pilot completed 34 paid BYOK calls
(router $0): 33 VALIDATED, one duplicate-rank REJECTED and two explicit-course
local SKIPPED inputs. Twenty matched postings yield 22 proposals; validated/
skipped outputs have 15 abstentions. V4 pilot cost is **$0.03405499**, shared
known cost **$0.29770062**, provisional exposure **$0.0189965**, and accounting
bound **$0.31669712**. No scale approval or publication is recorded. This is a
curated regression sample, not a population estimate. Pilot/audit receipts:
`~/.local/state/jobtology-hop/onet-matches/20261014T091421Z-pilot-02327ebada52/receipt.json` and
`~/.local/state/jobtology-hop/onet-matches/20261014T091518Z-output-audit-19112178caaa/receipt.json`.

Preparation sealed all 22,635 inputs at 09:03:29.941558 UTC in
99.284937 seconds, with exact retained prompt registration. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T090150Z-prepare-d779a6be767e/receipt.json`.
Routing-incident acknowledgement is **COMMITTED/COMPLETE**; all 608 original
attempts remain unchanged and v3 remains permanently STOPPED. At this pre-v4
pilot checkpoint, shared known cost is **$0.26364563**, provisional exposure
**$0.0189965**, and native accounting bound **$0.28264213**. The acknowledgement
does not establish that the initial BYOK timeout was free. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T091403Z-route-ack-committed-453ff7d1b4b0/receipt.json`.
V4 pilot decisions and limited sample execution are complete; full processing
and publication remain pending. Manifest:
`~/.local/state/jobtology-hop/onet-matches/20261014T090023Z-freeze-c9b6514ae89a/manifest.json`,
SHA256 `ffc0c4e44bb3c0733d5b60d0eaf4027195edec944612fef9a31d5a39e4335c67`.
The same 22,635 original source postings remain, with 24 candidates, 1,024
maximum output tokens and $0.02 request reservation. Host/prompt/retrieval
qualification passed **175 targeted tests**. V3 is permanently STOPPED, retaining
179 never-sent plans that must never be resumed. Stop receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T090001Z-v3-holdout-quality-stop-97c832463f5a/receipt.json`.
The curated pilot uses the explicit file
`~/.local/state/jobtology-hop/onet-v4-offline-review-scadc7dq/pilot-posting-ids.json`,
SHA256 `ae2a8a31f7f01106baa98020b871c1776a74109a75ec8b6eb3b164e0a49fa2d2`.

Prior checkpoint: **limited 500-posting v3 holdout STOPPED on a non-BYOK
response**. Its partial audit records 264 VALIDATED, 56 local SKIPPED, one
REJECTED and 179 never-sent PLANNED inputs. The HTTP 200 rejection reported
`is_byok=false`; its `$0.0010035` router charge is known and counted once, while
the same reported internal upstream rate is not a separate BYOK debit. The
partial holdout cost is **$0.20205698**, v3 task cost including its pilot is
**$0.23487818**, shared cost including v2 is **$0.26364563**, and unknown holds
are zero **in the current native raw-response ledger**. Later generation
readback shows BYOK HTTP 504 after 13,999 ms, then same-provider router HTTP 200;
it cannot prove that the first timeout was uncharged. The coordinator retains
the incident's original $0.02 reservation as a conservative total bound:
**$0.0189965 additional exposure**, **$0.28264213 shared accounting bound**.
SQL006's isolated proof passed **77 checks on 22 artifacts**, retaining all 20
previous native bytes. The coordinator completed additive deployment and native
installation at **08:58:46.865982 UTC**; the later committed acknowledgement
above retains the bound separately from raw observed charges.
Qualification:
`~/.local/state/jobtology-hop/jobkorea-dry-run-fd796da5ca64/receipt.json`, SHA256
`73369b94e0a41ef7e9ed2605a27d27c2b7429cd4201bbe3bb7965ae0da3e8b84`.
Install:
`~/.local/state/jobtology-hop/onet-matches/20261014T085837Z-install-route-incident-3cd125e8aa77/receipt.json`.
The earlier existing-key management read returned HTTP 401. The user then
confirmed that BYOK-only was saved; the external configuration block is resolved
on **USER_REPORTED** evidence, without independent administrative readback:
`~/.local/state/jobtology-hop/onet-matches/20261014T084249Z-user-byok-only-attestation-a3dfa8704eb5/evidence.json`,
SHA256 `e112a8ab0de7800bf7a4637790c4e72af7642cee9870db29a102ae16c54c2c00`.
The v4 curated pilot is complete; only the regression-500 semantic gate is
approved, subject to source-refresh comparison and durable application. Router
available credit $5.41805786 does not verify upstream credit. Broader quality
review also found a course-content false match and forced residual `All Other`
classification; the wider gate remains closed pending v4 paid qualification.
Frozen admission decisions now replay against original source facts and
archived policy code before PG writes; audits distinguish explicit non-vacancy
exclusions from ordinary no-hit abstentions without changing native SKIPPED
history. No publication has run.
Generation evidence:
`~/.local/state/jobtology-hop/onet-matches/20261014T083821Z-nonbyok-generation-readback-8fd9aaf17815/response.json`.
Updated partial audit:
`~/.local/state/jobtology-hop/onet-matches/20261014T083734Z-output-audit-588c62c8e88c/receipt.json`.
Its technical validation of completed publishable outputs is not holdout/full
completion. Auditor metrics now separate billable BYOK upstream from raw
reported upstream and suppress incomplete listing-denominator cost rates.

Prior checkpoint: **prompt-v3 preparation and technical pilot COMPLETE**.
Preparation sealed all 22,635 inputs in 95.285022 seconds using 46 deterministic
chunks bounded by both 500 rows and 16 MiB; it exactly replayed the retained
prompt registration. Independent read-only PostgreSQL qualification confirmed
the largest chunk's exact 16,776,687-byte size (488 rows). The four-worker pilot
completed 33 paid VALIDATED outputs and 3 local skips, and pinned Python
validated all paid outputs: 21 matched postings, 15 abstentions and 22 proposals.
V3 cost is **$0.03282120**, shared recorded cost including v2 is **$0.06158865**,
with zero unknown holds. The coordinator atomically recorded 21 ACCEPT decisions
and one sports-trainer boundary REJECT, then approved the limited fresh
source-balanced 500-posting holdout `onet-v3-holdout-500-20261014` with eight
workers. It subsequently stopped as recorded above. The full run and
publication remain pending. Review/approval:
`~/.local/state/jobtology-hop/onet-matches/20261014T083024Z-pilot-individual-decisions-40b397ab01a2/receipt.json` and
`~/.local/state/jobtology-hop/onet-matches/20261014T083045Z-approve-scale-fc9fd5396157/receipt.json`.
Technical receipts:
`~/.local/state/jobtology-hop/onet-matches/20261014T082359Z-prepare-5f5ba8990391/receipt.json`,
`~/.local/state/jobtology-hop/onet-matches/20261014T082601Z-pilot-121c78cbe13e/receipt.json`, and
`~/.local/state/jobtology-hop/onet-matches/20261014T082704Z-output-audit-8229e584afb6/receipt.json`.
Independent prepublication graph acceptance is VERIFIED: exact target database,
202,889 nodes, 755,236 relationships, 5,878 NCS edges, every frozen source's
typed facts/provenance exact and zero O*NET posting edges. Receipt:
`~/.local/state/jobtology-hop/onet-matches/20261014T082927Z-independent-graph-acceptance-066a9fcf5e1f/receipt.json`.

Recovery checkpoint: **39-check recovery proof passed on 20 artifacts**, all
original 18 native files unchanged. Four exact evidenced pre-dispatch errors
received append-only effective-zero reconciliation; all original 36 attempts
and cost-NULL history remain exact. Shared unknown holds are zero. Recovery:
`~/.local/state/jobtology-hop/onet-matches/20261014T074604Z-reconcile-no-dispatch-9205a9385712/receipt.json`.
The corrected v2 task sealed all 22,635 inputs and completed its single-worker
pilot: 33 paid outputs validated in native SQL and pinned Python, 3 local skips,
**$0.02876745 combined cost** (upstream BYOK, router $0), 98,592/3,437 input/output
tokens, 25 matched postings and 32 proposals. **Semantic quality review FAILED**
for disjunctive physician alternatives, silent role overflow and overlapping
software occupations. V2 is STOPPED with no scale approval or published edges.
Pilot/audit receipts:
`~/.local/state/jobtology-hop/onet-matches/20261014T074624Z-pilot-3d48ced2af5a/receipt.json` and
`~/.local/state/jobtology-hop/onet-matches/20261014T074827Z-output-audit-9455b60f66a6/receipt.json`.
A focused prompt-v3 successor is authorized under the same $40 combined cap and
lighter model; its limited holdout approval is retained, while routing recovery,
holdout acceptance and the full run remain pending.
The report below retains original failure and recovery receipts chronologically.

After the verified catalogue checkpoint below, the user reported `$45.90`
available credit and instructed `ok proceed` with O*NET posting linking. The
coordinator set a separate **$40 combined O*NET accounting cap**, including
upstream BYOK charges and router fees, across pilot/full/resume and source pins.
The earlier catalogue-only matching hold is superseded for this task; the
historical NCS $5 accounting scope and existing lighter model/provider routing
remain unchanged. The balance is user-reported, not API-verified.

The current locally frozen source-only cohort contains **22,635 postings**:
8,434 JobKorea, 12,736 Nara and 1,465 JOB-ALIO; 1,014 ontology duplicates are
excluded. Its original private graph export is checksum-bound and retained.
The original 34-check qualification, 77.006-second preparation and failed
four-worker routing pilot remain historical evidence. The temperature-filter
failure and its $0.08 holds are resolved by the qualified recovery above;
original responses and cost-NULL history were preserved. Corrected preparation
sealed all 22,635 inputs in 77.347859 seconds under v2. Its completed technical
pilot and **failed semantic quality review** are retained history. V3's technical
pilot and interrupted holdout above supersede its accounting checkpoint:
shared spend **$0.26364563**,
the separate conservative exposure bound above, no further paid admission and
no O*NET posting edges. SQL005's
whitespace correction is qualified; the independent pinned
Python validator remains required before scaling/publication. See the
[posting-link report](2026-10-14-onet-posting-linking.md) for scope, run commands
and the eventual verified receipts.

## O*NET catalogue checkpoint (October 14)

The user authorized the actual, separately pinned O*NET reference catalogue
load into PostgreSQL and Neo4j, now **VERIFIED**. This milestone supersedes the historical
performance-only no-O*NET restrictions below. The catalogue-only milestone
stopped before posting matching, candidate retrieval, prompts or provider calls;
the later posting-link authorization above opens that separate path. Use the retained
official O*NET 31.0 occupation JSON, CTDL JSON-LD and O*NET-SOC 2019 structure;
all parsing and loading after acquisition use those local archived bytes.

The authorized catalogue has 1,016 occupations, 580 groups and 1,573 broader
relations. Its separate `classification` schema and flat owned Neo4j namespace
preserve the existing Korean catalogue, NCS matcher, frozen runtime/inputs and
Korean Q-Net support. No duties, skills, ratings or posting occupation evidence
are established by this reference load. Qualification and production acceptance
are tracked separately in the [O*NET catalogue report](2026-10-14-onet-catalogue.md).
The final combined isolated native proof is **PASSED**: 50 checks, the full pinned
catalogue's 1,597 flat nodes and 3,169 relationships, exact replay, independent
typed graph-plan matching, legacy PostgreSQL/graph preservation and complete
cleanup. It binds all 23 new public artifacts and the exact official normalized
payload, including exact graph retry without source reimport and adversarial
node/edge collision failures before writes. The qualified successor changes only
two preflight HPLs after a coordinator-controlled, normally cleaned read-only
preflight stop; its linked recovery retains the original backup and all
before-state evidence. Actual server Hop load/replay and independent production
acceptance are **VERIFIED**: 1,597 owned flat nodes and 3,169 relationships; all
157 legacy PostgreSQL tables, full schema/query/catalogue/prompt/matching state
and 460 function execution-metadata entries remain exact. All 201,292 legacy
nodes and 752,067 relationships retain their complete typed values and element
IDs. The final graph has 202,889 nodes and 755,236 relationships. Live readback
confirms READY catalogue, VERIFIED target, zero running loads/writers, idle
runtime and no scheduler fence. Source/provider/posting-matching counters are
zero; no paid call or new posting link ran.

The native retry/replay completed in 18.657/25.847 seconds. The two scoped
preflight improvements are resolved and deployed; the interrupted old edge phase
is censored, so no completed edge or whole-ingestion gain is claimed. See the
report for receipts, recovery, exact scopes and retained failed evidence.
O*NET catalogue loading is complete. The newly authorized O*NET work is a separate Korean
metadata retrieval/inference/validation/publication path; the existing NCS
matcher cannot accept dotted O*NET codes. Safe read gating for future partial
rollovers and an owned-process deadline/cancellation contract remain TODOs.

## Entity-reader checkpoint (October 14)

SQL009 and both canonical graph installers are deployed and independently read
back. Only `ingestion.graph_source_entities(text)` changes. All 157 full protected
table fingerprints, complete query outputs, schema/index state, catalogue,
prompts and frozen matching pairs remain exact; all 460 existing function
execution-metadata entries, including OIDs, match. SQL001→008, JobKorea SQL008,
LLM SQL037 and owner500 transport retain their frozen bytes. The scheduler fence
is absent. No source HTTP, provider/paid call or production Neo4j write occurred.

Separate facts/name `DISTINCT ON` winners retain their complete original ordering;
one posting-fact workset retains each original run/source/text-key group and its
merge/fallback behavior. This supersedes the previous Nara scalar posting-key
join TODO. Balanced complete warm Nara replay averaged **38.727s baseline versus
36.348s SQL009 (6.14% lower)** with SQL007/008, SQL006 and owner500 fixed on both
sides. Typed graph, source proofs and protected facts match. These are scoped
warm replay measurements, without a fresh-import or global reader claim.

All eight complete real entity/owner reader pairs match across Nara, both
JOB-ALIO runs and JobKorea. The separate SQL009 oracle passed 41 new checks;
the earlier 442-case and 13-comment-form proofs remain retained baseline
evidence. Both canonical Hop installers passed before replay. The owner audit's
known canonical edge-owner OID recreation required a narrow checker correction;
the failed checker bytes remain preserved, and production OIDs remain strict.
All owned containers, recorded volumes and temporary databases are removed,
and the complete PostgreSQL log follower drained naturally.

Live two-worker validation passed **five snapshots across four sources in
11.670447s**. The complete result matches the preceding five-snapshot proof;
actual worker and all operation backend absence are verified. No paired live
speedup is claimed. Production is idle.

See the [qualified entity-reader report](2026-10-14-entity-reader-performance.md)
for exact deployed hashes, qualification/cleanup/production/live receipts and
scope limits. Current measured follow-ups are JOB-ALIO's internal owners-stage
22,536,584 rejected identity pairs and 35 historical validations, plus JobKorea
validity and repeated facts-JSON rendering. Their diagnostics overlap and do
not assign exclusive costs by subtraction. The older 84/86-run observations
remain unexplained.

## Earlier capture and source-reader checkpoint (October 14)

SQL007/008 and both canonical graph installers are deployed and independently
read back. Only the existing capture insert guard, entity reader and edge reader
bodies change. All 157 protected table fingerprints, complete query outputs,
schema/index state, catalogue, prompts and frozen matching pairs remain exact;
all 460 existing function execution-metadata entries match. SQL003/004/005/006,
JobKorea SQL008, LLM SQL037 and owner500 transport retain their frozen bytes.
The scheduler fence is absent. No source HTTP, provider/paid call or production
Neo4j write occurred.

First capture now passes all four supplied source runs within the unchanged
60-second statement bound, in both atomic and per-run transactions. Original,
new and live READY proofs match, with exact 59-table/timestamp rollback.
Measured begin/finish calls sum to 89.107s atomic and 88.455s per-run; these are
not complete coordinator times. Capture remains nondurable qualification, and
JobKorea's roughly 52s begin is still near the bound. Earlier failed baselines
remain immutable and provide no numeric full-capture speedup ratio.

Balanced complete warm Nara replay averaged **100.476s baseline versus 38.369s
candidate (61.81% lower)** with SQL006 and owner500 fixed on both sides. Typed
graph results, source proofs and all 157 protected tables match. Full JOB-ALIO
compatibility passed with 673 entities and 538 real source relationships; the
three-original-line fresh JobKorea regression also passed. These are scoped
replay/compatibility results, without a whole-ingestion or whole-file claim.
The 442-check semantic oracle and 13 exact Hop-comment-form compatibility checks
passed. Initial failed receipts are preserved; all owned containers, recorded
volumes and temporary databases are removed, and complete logs drained.

Live two-worker validation passed **five snapshots across four sources in
11.615136s**. Its complete result SHA256 matches the preceding five-snapshot
proof; actual worker and all operation backend absence is verified. No paired
live speedup is claimed.

See the [qualified capture and reader report](2026-10-14-capture-reader-performance.md)
for exact deployed artifacts, production/readback/live receipts, independent
cleanup and scope limits. At this checkpoint, remaining measured work was Nara's
scalar posting-key join (about 5.96 million rejected pairs) and JOB-ALIO/JobKorea
entity-reader cost. SQL009 above supersedes that Nara join TODO; JOB-ALIO/JobKorea
remain measured follow-ups. The older 84/86-run observations remain unexplained.
This checkpoint superseded the capture/reader TODOs in the earlier checkpoint below.

## JOB-ALIO validation and owner transport checkpoint (October 14)

SQL006, both graph installers and 500-row owner cleanup/totals are deployed and
independently read back. All 157 table fingerprints, schema/index state,
source/publication outputs, catalogue, prompt and frozen matching pairs remain
exact; only the existing scoped validation helper changes. SQL003/004/005/008/037
retain their frozen bytes. The scheduler fence is absent. A pre-existing
scheduled JOB-ALIO refresh completed naturally before the fresh deployment
snapshot; this task made no source/model/paid call or production Neo4j write.

Balanced complete JOB-ALIO assertions averaged 0.871s versus 24.686s (96.47%
lower). JOB-ALIO first capture passed with READY original/new/live manifests and
exact rollback; it is nondurable proof. Clean native Nara replay fell from a
two-baseline mean of 116.064s to 104.103s (10.31%) with one eligible candidate
sample. The 308-check semantic oracle, 33 owner assertions, full JOB-ALIO native
replay and three-original-line fresh JobKorea regression passed. All owned
containers, volumes and temporary test databases are removed.

The live two-worker reader passed **five snapshots across four sources in
11.771173s**, including new JOB-ALIO run
`4a9262a3-aee6-47b9-ad90-6ed8e4c6b2c1` (928 records/1,856 references). The original
four complete result objects match their prior proof. Actual worker/exporter
backend absence is verified. Its five-job scope differs from the older four-job
live check, so no paired live gain is claimed.

See the [qualified JOB-ALIO and graph report](2026-10-14-jobalio-graph-performance.md)
for exact artifacts, receipts, cleanup and limits. Wider first-capture receipts
remain FAILED: JobKorea's live-reference transition join and Nara's live-record
transition join each reach 60s and roll back exactly. Historical reference and
entity-fact worksets still dominate measured graph readers. Those are separate
next steps; no four-source durable capture, whole-ingestion gain or cause for the
older 84/86-run difference is established.

## Earlier SQL005 source validation checkpoint (October 14)

Guarded SQL005 and both graph installers are deployed and independently read
back. All 157 existing table fingerprints, schema/index state, source/publication
outputs, catalogue, immutable prompt and frozen matching pairs are preserved.
SQL003/004/008/037 retain their frozen bytes. No production Neo4j writes, source
HTTP, provider/paid calls or global parallel-setting changes occurred; the scheduler
fence is removed. The standalone host CLI defaults to two workers, caps at four,
imports one consistent read-only snapshot and holds the existing retention/writer
gate before taking that snapshot. Actual worker and exporter backend absence is
verified before successful acceptance; it does not parallelize capture or writers.

The explicitly analyzed, four-distinct-source balanced 1/2/4 then 4/2/1 matrix
passed all 24 assertions with identical outputs. Mean complete coordinator times
were 36.546/25.838/24.920s, with mean CPU 36.499/36.766/36.792 CPU-seconds.
Two workers reduced elapsed time 29.30%; four added only 3.55% over two. The
live four-source/two-worker CLI subsequently passed in **25.241197s**, with the
same exact result SHA256 and verified session cleanup. These are scoped read-only
validation measurements, not whole-ingestion or writer-scaling results.

Native Nara replay passed with 13,234 source records, 10,555 entities and 10,555
posting dates. Warm complete wall time was 103.537s; its 94.610s native pipeline
spent 47.633s writing and 42.446s verifying. The original native validation
attempt was censored at its unchanged 60s query bound, so no paired speedup ratio
is claimed. Exact typed graph evidence and all 157 protected table fingerprints
were preserved. A three-original-line fresh JobKorea import/replay passed as a
functional compatibility proof. The 102-case semantic oracle and 21 native
coordinator checks passed, including snapshot, retention, failure and cleanup
cases. SQL/matrix work used the one network-none clone; native work temporarily
used that same PostgreSQL ID/statistics on an owned internal network, then
restored its isolation. All owned containers and recorded volumes are removed.

Protected final production receipt:
`~/.local/state/jobtology-hop/additive-runtime-applied-900470c35c7a450c811c4f0acf81c02c/receipt.json`,
SHA256 `ca2b2895c0d8a24b041071b8a7946a0219048b5404ad6be44755b438cd56e884`.
Live CLI receipt:
`~/.local/state/jobtology-hop/source-proof-validation-6953c481a65c4949a85e09c9ce33ce40/receipt.json`,
SHA256 `fb3071399107351b6b656fff4eba8c5cf6d2f062f28ab75fa24955948adfcc68`.
See the [qualified performance report](2026-10-14-validation-performance.md)
for artifact hashes, native and cleanup receipts, exact scopes and limitations.
At this earlier checkpoint, remaining work was JOBALIO repeated first-capture
validation and graph-cost decomposition; the later checkpoint above supersedes
those TODOs. The four-scope atomic first-capture
attempt timed out at JOBALIO's unchanged 60s bound after ALIO passed; Nara was
not reached. Exact rollback passed; no four-scope durable capture is claimed.

## Bounded PostgreSQL multicore investigation completed (October 13)

This earlier October 13 follow-up completed with **no change to production SQL,
runtime or parallel settings, and no source/model/paid call or graph write**. Default-cost
SQL evidence scans launched 1/2/4 workers and matched all exact output checksums;
serial/one/two/four-worker output times were 47.762/24.752/17.218/13.651s under a
four-logical-CPU-equivalent clone quota. Four SQL workers plus a leader differ
from four independent sessions. The fixed heavier read-only checks ran with SQL
parallelism off: forward/reverse mean totals at 1/2/4 sessions were
65.022/35.138/24.940s, all 24 checks passed and per-job outputs matched.
These demonstrate engine and independent-check concurrency within one fixed
**unanalyzed restored fixture**, not complete ingestion gains or a calibrated
production throughput proxy.

The initial 12 manifest jobs failed a restore-only canonical view-alias guard;
their times are invalid and the original FAILED receipt remains unchanged.
Exact frozen SQL003→004→008 reinstallation used the existing guarded canonical
deparse/reparse allowance; all five query contracts and four captured/live
source manifests then passed. The archive omitted optimizer statistics, unlike
production. A separate explicitly analyzed Nara original/candidate comparison
still reached the same 60.006s full-validation bound for both. Source proof
values stayed exact, but a complete validation gain was not established. The
experimental grouped-count SQL005 files were archived outside the canonical
repository and removed; no native eight-source semantic oracle or production
installation occurred. Existing SQL003/004/008/037, graph/source installers and
date transport retain their verified production bytes; the scheduler fence is
absent.

The owned container and anonymous volume are removed; log streaming drained at
**2026-10-13 06:21:13.010090 UTC**. Final protected receipt is
`~/.local/state/jobtology-hop/postgres-parallelism-a80225b840114b15904b9ec1e5a30636/receipt.json`,
SHA256 `244a4cf2a2995b017751951f5c8ce2c20ae2aa64cddda359460ad491edbe8d0e`.
Its overall FAILED status retains the invalid first series; valid canonical
correction and 24-job results have separate receipts. The future helper now
establishes recorded clone statistics, verifies canonical query/wrapper contracts
before timing, refuses throughput/scaling for failed jobs and exits nonzero for
failed acceptance after preserving receipts/cleanup. Seven focused checks,
Ruff and compilation passed. See the
[parallelism and nested-validation report](2026-10-13-postgres-parallelism.md)
for exact scopes, actual workers, CPU/throttling, failed receipts and limitations.

At this earlier checkpoint, scoped Nara diagnosis and a snapshot-safe independent
read-only coordinator remained future work. The October 14 checkpoint above
supersedes those TODOs with qualified SQL005 and an operational host CLI. Keep
global production parallel settings unchanged. The old 84/86-run capture
difference remains unresolved; do not repeat whole-history captures or raise
bounds without new diagnostic evidence.

## Further routine optimization and v3 pilot checkpoint (October 13)

The user authorized the next four steps: optimize fresh NDJSON import/READY
validation, reduce remaining replay proof/date overhead, test realistic initial
reads and multi-run capture, and conduct a small real opt-in v3 pilot. The seven-artifact SQL004/008/date500 rollout and separate production readback
are now VERIFIED. Existing SQL003/037 and their proof bytes remain frozen; the
new migrations preserve their source validation and matching contracts.

The fresh-import source proof passed: SQL008 refreshes lookup-column statistics
inside the guarded seal and measured 37.625s versus baseline 326.291s; the
preinstalled-index control was discarded. SQL004 retention serialization,
existing-proof replay and date500 transport have completed isolated proofs and
are deployed and independently read back. Matched native warm replay measured 207.489s
baseline versus 157.364s candidate (24.16% lower; one sample each). Sixteen
corrected replay/recovery/retention checks passed.
Real first-backend date counts across four archived source scopes finished below
one second and did not reproduce the historical delay. The four-scope atomic
first-capture attempt reached its Nara 180s statement bound and rolled back as a
whole; its earlier statements are diagnostic, not durable proofs. No Nara gain,
four-scope capture success or old 84/86-run cause is established.

Detailed measurements, exact scopes, limitations, failed receipts and TODOs are
in the [October13 routine performance report](2026-10-13-routine-performance.md).
Native proof is complete and all owned resources are removed. The original
`jobkorea-dry-run-c750e80320b4/receipt.json` remains FAILED for a lowercase-only
parser rejecting the final Cypher `TRUE`. Real native AB/preservation/date negative
checks passed. A separate tiny native correction closed synthetic deletion and
exact graph restoration; scopes and immutable evidence hashes are sealed in
`~/.local/state/jobtology-hop/jobkorea-dry-run-c750e80320b4/combined-native-proof.json`.
The final whole-archive post-date snapshot was not executed and is not claimed.
Source proof is
`~/.local/state/jobtology-hop/seal-checkpoint-f81dce17695f4e67/final-summary.json`;
corrected SQL replay proof is
`~/.local/state/jobtology-hop/replay-reads-corrected-6966181f6f874262ad5086d687ef5b93/corrected-replay-oracle.json`.
The reviewed production plan is
`~/.local/state/jobtology-hop/additive-runtime-plan-3f376c452acd45e781ddae1f4ce95259/manifest.json`
(SHA256 `e5fdd0977242ae9b0de12235066754214c97bad41aa0dae065d806c343d371fa`).
Apply verified at 05:23:44.230965 UTC; separate readback passed at
**2026-10-13 05:25:14.054523 UTC**. Final protected receipt:
`~/.local/state/jobtology-hop/additive-runtime-applied-5a7f73fd326e468b8117ef95e38cbe15/receipt.json`
(SHA256 `291c3a88db4a5fea300f8e028ec862afbc560c8c5423c3e238f8397f6c7dc05f`).
All seven files, all 157 preexisting table fingerprints/schema/index states,
source/publication query outputs, immutable v3 prompt and four candidate decisions
match. The compatibility helper is the only added schema object. Historical
publication SQL still returns 5,878 rows/21 reviewed; the latest NCS pair has one
SQL-eligible accepted pilot row, with no new Neo4j publication. The aggregate
5,879 SQL output rows are not a published edge count. No source/model/paid call
or graph write occurred during rollout; model/routing/defaults are unchanged.
The scheduler fence is removed. The same directory retains `apply-verified.json`
(SHA256 `6606cf610cbeb35b2042e7a6ae4565a4075aed31dd3a1eb682508ed77ef72ef9`)
and the 937,258,240-byte `database-before.dump` backup (SHA256
`e38466d8f6d144b100bdbecff6e38d6c2b3df695ff2fd38c19c04cbd99762494`);
archive listing was verified, with no restore claim for this new backup.
Native capture is SQL plus Hop processing; posting-date writing combines SQL and Neo4j.

All performance fixtures use supplied local data with no source HTTP, paid/model
calls or production writes. The root coordinates the separately authorized real
v3 pilot and its cumulative accounting, immutable source/NCS pins and actual
review status. No O*NET import is authorized. Future deployment requires bounded
isolated correctness/preservation proofs, exact backups and guarded readback;
existing legacy and any new v3 facts must remain exact.

The real opt-in v3 pilot completed 15 unique requests/15 wire attempts for
**$0.00952315**. Four attempts validated: two matched listings with four candidates
and two abstentions. Eleven were rejected, predominantly for exact anchor/citation
format. Root recorded four individual candidate decisions: one ACCEPT and three
REJECT; no inferred graph publication occurred. Current cumulative native cost
is **$4.09107240**, combined task cost including the earlier probe **$4.09108020**,
leaving **$0.90891980** under the $5 cap. The host global accounting budget fix is
verified. Frozen SQL037, original partial batch/source/input/result facts and all
5,878 legacy publication rows remain exact. See the
[real pilot report](2026-10-13-multimatch-pilot.md) for actual scope, review and
quality limits; multiple qualifying NCS roles may occur within one hybrid vacancy.

## Latest verified production checkpoint

**Source validation optimization is deployed and independently read back.** The
three-artifact SQL005/graph-installer rollout is VERIFIED at 2026-10-13
15:23:49.329957 UTC, with all 157 preexisting tables and frozen matching/source
evidence preserved. Its standalone host coordinator passed live four-source
two-worker validation at 15:24:43.767412 UTC. Runtime publication contains only
SQL005 and the two installers; the coordinator remains a host operation.
See the [October 14 checkpoint](#source-validation-qualification-and-live-checkpoint-october-14)
and [qualified report](2026-10-14-validation-performance.md).

**Further routine performance optimization is deployed and independently read
back.** The October 13 seven-artifact rollout is VERIFIED at 2026-10-13
05:25:14.054523 UTC, with all 157 preexisting tables, four candidate decisions,
source/legacy/current publication SQL outputs and exact runtime bytes preserved.
No new inferred graph publication occurred. Its backup, bounded proof limits and
receipts are recorded in the checkpoint above and the
[October 13 routine report](2026-10-13-routine-performance.md).

**Source-query optimization and opt-in multiple metadata occupation matches are
deployed and independently read back.** At that checkpoint, all 15 reviewed
runtime artifacts matched and all 156 preexisting PostgreSQL tables and historical
inference query outputs were preserved. Subsequent seven-artifact and
three-artifact rollouts supersede some installer bytes. The candidate-review table was empty at deployment; the separate
authorized pilot above subsequently recorded four decisions. Existing 5,878 inferred
publication rows, including 21 reviewed rows, are unchanged; no listings were
reclassified. Model, provider routing and defaults are unchanged. No source HTTP,
provider/paid calls, O*NET import or production graph writes occurred. The owned
scheduler fence is removed. See the [October 13 checkpoint](#routine-follow-up-verified-october-13).

**Batch-free production transition and independent preservation are VERIFIED.**
The graph contains no ingestion batch/record/archive scaffold. Existing business
entities, relationships, posting dates and inferred NCS links are preserved;
PostgreSQL retains exact source proofs. The scheduler has resumed and the pending
fence is removed. See the [verified checkpoint](#live-checkpoint-verified).

**Focused performance deployment and production readback are VERIFIED.** Typed
ontology properties are grouped by owner and source entity transport uses 500-row
batches. At that checkpoint, all 17 runtime artifacts matched and five read-only
native verifier passes succeeded. Subsequent source-query and routine performance
rollouts supersede some runtime bytes, as recorded in the October 13 checkpoints.
See the [performance checkpoint](#routine-performance-checkpoint-october-12).

**Ontology revision flattening and independent preservation are VERIFIED.**
All 39,336 revision nodes are removed; canonical facts and rerouted relationships
retain exact PostgreSQL revision evidence. The final graph has **200,952 nodes /
751,971 relationships**, with no `*Revision` labels. All original 148 PostgreSQL
tables, catalogue readers and historical exports are preserved. The scheduler has
resumed and the fence is removed. See the [verified checkpoint](#revision-flattening-implementation-checkpoint)
and [migration record](revision-flattening-plan.md).

**Posting-date deployment, historical backfill and independent readback are
VERIFIED.** The October 11 readback verified all 22,290 then-current source posting identities with typed ingestion
metadata; 8,434 JobKorea identities use the separate `USER_REPORTED` collection
evidence. The user-requested pause and 09:46 UTC resume remain historical
checkpoints. See the
[pause and resume checkpoint](#posting-date-pause-and-resume-checkpoint).

## Routine follow-up verified (October 13)

**VERIFIED: isolated routine proofs, additive deployment and separate production
readback.** Source-query SQL003
is frozen at SHA256 `761ecb278d4db00396128e00fa2290973928a4c1be3cd0c3796a456cf441beff`;
its independent 46-case, eight-source SQL oracle passed. Opt-in metadata occupation
v3 SQL037 is frozen at `3ef8eb423a09532e2d078d4fe86c99e4427d262a33365d0df2ffbaf93e9a5fdb`;
final PostgreSQL and full native multimatch proofs passed and removed their
disposable resources. Protected receipts are:

- `~/.local/state/jobtology-hop/routine-work-20261012/source-query-oracle-final/receipt.json`
  (the unique schema-oracle database was removed; its parent clone was later removed).
- `~/.local/state/jobtology-hop/jobkorea-dry-run-d831e0fcb25c/receipt.json`
  (full native multimatch proof, final critical runtime hashes).
- `~/.local/state/jobtology-hop/multimatch-postgres-c9a425e1255c/receipt.json`
  (final bounded SQL proof and focused installer with 037 last).

The reviewed production plan is
`~/.local/state/jobtology-hop/additive-runtime-plan-0b9b714d729643e69bdd517e1526ceb1/manifest.json`.
Transactional SQL003/037 installation and exact 15-artifact runtime publication
passed at **2026-10-12 16:27:57.771026 UTC**. The immutable apply checkpoint is
`~/.local/state/jobtology-hop/additive-runtime-applied-873d4893138d44519588e863ebcd2012/apply-verified.json`,
SHA256 `198cf3f500184d6264d1be99bc57839459abf1ff6be922cf287c574259400268`.
A separate readback invocation passed at **16:29:21.870073 UTC**; final receipt
`receipt.json` in that same directory has SHA256
`95533b9734f02359256d7c48ba252c0e6668edea018236fe96bcee869c0169aa`.
All 156 preexisting tables and their schema/row fingerprints matched. Only the
empty candidate-decision table and immutable v3 prompt were added, with approved
function changes. Latest catalogue pins, 8,434 selected source entities/dates and
historical inference status/publication outputs matched, including 5,878 legacy
rows and 21 reviewed rows under the actual frozen NCS pin
`ba32f673-255c-4990-80d4-8dbef6008e2f`; an empty latest-pin scope was not accepted
as preservation evidence. The owned scheduler fence is absent.

The protected full custom backup beside the receipt is `database-before.dump`,
935,909,950 bytes, SHA256
`b27bd7ab0afb3f8b2421fa091f4ef1db0aecedcd3279131daf01fc0a941d9cf0`.
Its archive listing was validated; this is not a native restore proof of that
specific live backup. Native supplied-archive restoration and workflow proofs
are recorded separately below. Exact old runtime bytes and public function/view
definitions are retained for guarded behavior rollback. New v3 work or candidate
reviews cause rollback to refuse; unused additive objects may remain.

Multiple occupation inference is available through explicit v3 selection.
Existing default prompt/model/provider routing and v2 results remain unchanged;
deployment did not reclassify supplied listings or execute inference/ingestion/
graph writers. It retains STAGING/UNREVIEWED, NULL/UNASSESSED confidence and
individual candidate review semantics.
Metadata matches do not establish source-stated duties or competency evidence.

The controlled archive benchmark passed with all disposable resources removed;
its final protected receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-1a601507362d/receipt.json`.
Matched ABBA warm source-graph replay took baseline 457.306s / 473.389s and
candidate 208.185s / 207.014s. Mean elapsed time was 465.348s versus 207.600s
(55.39% lower) for this exact source-graph workflow, with two samples per variant.
Exact typed graph, immutable source/frozen data and unrelated synthetic edge
identities/properties matched; wrong-kind tampering was rejected and repaired.
These are source-graph replay measurements, not complete ingestion speedup or
nonzero-edge throughput evidence.
Separate matched selector wall times averaged baseline/candidate **82.868s /
21.915s** for 8,434 entities and **34.551s / 9.171s** for zero edges. These include
the isolated SQL client invocation; they are independent samples and cannot be
subtracted from native writer/verifier stages.
Candidate source-graph priming passed in **219.282s wall**, including 9.697s
startup/orchestration. Native stages were validation 8.108s, existing-proof capture
44.418s, writers 88.255s, verification 52.391s and projection checkpoint 14.170s;
other guards/constraints took 2.243s. All readers matched 8,434 entities/dates and
zero source edges. Boot 12.584s, restore 129.658s and ANALYZE 3.083s were separate.
This is standalone priming evidence, not an established speedup or first capture.
The archive sentinel uses a generic synthetic unrelated-edge type; the completed
fresh replay separately proves synthetic `INFERRED_NCS_OCCUPATION` preservation.

Fresh full ingestion and READY replay both passed in fixture
`jobtology-jobkorea-test-79324e35db0d`, whose containers, volumes and network are
now removed. Its protected original receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-79324e35db0d/receipt.json`.
Its first complete supplied-file import passed in **609.928s wall**: import/READY
validation 356.560s, first proof capture 74.613s, source validation 7.950s, writers
89.505s, verification 48.461s, projection/export checkpoints 21.395s and other
guards 1.977s, plus 9.467s orchestration. Boot 13.012s and installation 21.891s
were separate. Exact READY rows were 8,434, validation issues and source requests
zero, and the outer verified export checkpoint count one. This candidate-only
fresh measurement establishes no before/after gain. Full READY replay passed in
**210.272s wall**: local revalidation 16.573s, validation 7.944s, capture 34.214s,
writers 73.207s, verification 46.192s, checkpoints 21.399s and other guards 1.306s,
plus 9.437s orchestration. Exact typed graph and source/proof/frozen fingerprints
matched; synthetic `INFERRED_NCS_OCCUPATION` element IDs and properties survived.
The original receipt is marked FAILED solely because root-owned raw scratch
could not be removed after the containers were gone. Its bytes remain unchanged.
The hash-linked `cleanup-recovery.json` beside it records successful exact-scope
scratch removal with a no-network temporary container and confirmed removal of
that container. No measured workflow was repeated for cleanup.
The prior fresh attempt `jobkorea-dry-run-0a6776e4f6fd` failed before importing rows:
the importer correctly rejected the benchmark's archive database name at the
DRY_RUN isolation guard. Its failed log/receipt are retained, resources removed,
and the fixture now uses the required unique dry-run database name.

Representative matched atomic/per-run **first proof capture passed**; its
protected receipt is `~/.local/state/jobtology-hop/first-capture-790166a168414fd9882d3a0d222aa43c/receipt.json`.
Two databases were cloned from identical preserved data and ANALYZE statistics,
with no selected proof rows: JobKorea 8,434 records/one document and real READY
ALIO organization run `12d31df1-1783-48bb-be1d-b801502472ca`, 355 records/four
documents. Atomic capture took **86.220s**, per-run **85.934s**. Both produced exact
matching 8,789 record-evidence rows, 8,789 memberships and two READY projections;
only projection timestamps were excluded. Original scoped source and all frozen
enrichment data matched. First backend validation before fingerprint reads took
JobKorea 8.303s / 7.862s and ALIO 0.015s / 0.013s. Restore 115.882s and ANALYZE
1.517s were separate; all disposable resources were removed. One sample per
transaction shape and fixed order establish no material transaction-shape gain,
host-cold behavior or cause/cost of the older 84/86-run observations.

All planned isolated measurements and the guarded additive SQL/runtime deployment
with separate readback are complete.
The coordinator is implemented with a scheduler fence, exact backups, transactional
SQL, historical inference-query preservation and retryable behavior rollback.
No source HTTP, provider calls, paid inference or O*NET import occurs in this work.
Frozen model-input preparation and ontology release are separate workflows.
The fresh importer reached all 8,434 lines in 17 committed batches, then spent
several minutes inside `seal_jobkorea_ndjson_import`. Repository review shows
seal/finalization/READY guards retain repeated manifest validation outside SQL003.
This is a separate performance follow-up; no nested plan or controlled variant
has established which internal step causes the observed fresh-import latency.
Further performance work may examine the measured archive existing-proof guard
(44.418s) and posting-date writer (40.306s). Capture measures native SQL and Hop
guard processing; the posting-date writer combines SQL and graph work. Neither
phase isolates an internal query's cost or establishes its root cause. No
additional tuning or production-wide throughput claim is established here.

## Decisions that govern the next work

- On October 12 the user prioritized **DB loading and validation performance
  before new matching or paid retrieval expansion**. Profile the full routine
  ingestion/replay path separately from one-off migration work, then select
  improvements from measured hot paths. The requested future scheme is **US
  O*NET** ([official RDF database page](https://www.onetcenter.org/database.html#graph));
  its distinct-scheme RDF integration is proposed, not implemented. Existing
  Korean Q-Net qualification/exam support and history remain separate.
- On October 11 the user selected **batch-free Neo4j, keeping PostgreSQL import
  audit/recovery records**. Permanently remove the `ingestionBatch` and
  `ingestionRecord` graph layer and stop workflows recreating it; do not replace
  it with `archivedRecord` graph clutter. Preserve business entities,
  relationships, stable IDs and verified posting dates, plus PostgreSQL import
  history, immutable raw evidence, frozen LLM inputs/accounting and recovery
  checkpoints. This is a permanent graph model/workflow migration. Storage
  retention is independent. Repository implementation and isolated verification
  are recorded below; production migration and independent preservation are now
  VERIFIED.
- Use the supplied pre-scraped JobKorea dataset only. Do not request job-board pages, description URLs, S3 URLs, iframes, or images; this includes HEAD checks, link refresh, and fallback recovery. Missing content is an explicit outcome; accept available listing metadata and process supplied local content when available.
- The scraper returns raw job observations. Jobtology-DB owns ingestion metadata, hashes, provenance, normalization, quality flags, embeddings and downstream enrichment. Record import and processing times here. Actual scrape time must come from a known collection event or supplied evidence; leave it unknown when absent instead of substituting file or import timestamps.
- On October 11 the user supplied the collection time for the entire supplied
  8,434-posting JobKorea snapshot: **2026-10-08 02:48:14 Asia/Seoul (KST)**,
  equivalent to **2026-10-07T17:48:14Z**. This is `USER_REPORTED` scrape evidence
  received after import. Preserve the original receipt's NULL scrape timestamp,
  immutable dataset provenance and frozen input bytes/hashes. Effective date
  metadata can use the separately recorded evidence; import and file times remain
  distinct.
- The user will provide full production datasets as NDJSON, with one JSON object
  per physical line. The native adapter now streams NDJSON with bounded batches,
  exact physical-line/UTF-8 byte provenance and immutable checkpoint/archive-only
  recovery. Require terminal LF on every object line; accept CRLF, reject blank
  or malformed/truncated lines. Defaults are 1 GiB/file, 1 MiB/line, 500 rows and
  4 MiB/batch; maxima are 16 GiB, 16 MiB, 5,000 rows and 32 MiB, with line bound
  no greater than batch bytes. READY still requires complete-file validation.
  The original bounded array path remains 16 MiB default/64 MiB maximum with
  preserved identities/hashes. The October 8 production receipt proves the
  supplied 8,434-posting, 21,951,764-byte snapshot; larger advertised maxima remain
  validation bounds rather than demonstrated production throughput.
- Missing application start dates are allowed and low priority. The user's latest 2026-10-07 policy treats missing or NULL end dates in prefetched JobKorea postings as `상시채용`: use `deadline_kind=ROLLING`, a NULL normalized end date, and `deadline_basis=USER_POLICY`. Preserve raw input and supplied deadline precision. Explicit deadlines or closed status take precedence, and malformed supplied dates remain validation issues.
- Rechecking the same sample found 288 absent start-date keys and 79 absent end-date keys, with no explicit null or blank dates. The 79 missing end dates are accepted under the rolling-recruitment policy. The user may still improve scraper date accuracy; implementation need not wait for that investigation.
- The user describes network access as restricted except for selected domains. A prior unauthenticated private-route configuration response does not establish public reachability. General public exposure and network-hardening work are not established scope.
- On October 8 the user first authorized production ingestion and deterministic
  preparation while holding paid linking until account readiness. They later
  confirmed the OpenRouter account was loaded, instructed linking to proceed,
  and explicitly selected `ALLOW INFERRED METADATA MATCHES`. The earlier hold
  is lifted for this task. Use a separate, clearly labeled metadata-to-NCS
  occupation inference path; preserve the strict explicit-duty `ko-link-v1`
  contract and missing-description status. Start with a small paid pilot, then
  scale toward all 8,434 supplied listings only when quality and measured cost
  permit within the coordinator's explicit total accounting budget, including
  upstream BYOK inference and router fees. The initial cap/default was $4.75;
  after the measured pilot the coordinator selected a $5 combined task cap,
  with $4.9999922 for native inference accounting after the health-probe cost.
  The user corrected the earlier $100 statement to $50 available OpenAI credit
  and asked to continue using the lighter model. Treat $50 as user-reported,
  not API-verified. Keep `openai/gpt-5.6-luna`, dry/off defaults and the $0.05
  pilot/$4.75 accounting defaults. Do not change keys,
  accounts or provider routing.
- The full local export audit found 12,105 listing observations representing
  8,434 posting IDs, plus eight scraper-error envelopes. Select one unchanged
  original observation per posting: prefer explicit closed status, then a valid
  source-stated deadline, using the earliest explicit deadline when supplied
  deadlines conflict, then richer supplied listing fields and deterministic
  filename/line ties. Preserve every alternative and exclusion in the private
  archive. This selection policy used for the load does not establish collection
  chronology or authoritative current truth, and field values are never merged
  across rows.
- On October 7 the user requested complete local semantic-linking preparation
  and selected a small IT/software/data pilot. They subsequently authorized paid
  pilot testing with about $9.50 available and requested estimated LLM cost per
  1,000 listings. Preserve the earlier zero-paid-call dry-run receipts as
  historical evidence; preparation defaults stay off. Report measured extraction
  and NCS-matching costs separately, explain cache/fresh-input assumptions, and
  distinguish provider charges from conservative accounting reservations.
- Cohort and editorial modules are later planned implementation. Their absence from the live environment is not a completed deployment or an unexpected regression.

## Routine performance checkpoint (October 12)

The current performance work uses retained local evidence and isolated databases.
**Do not download or load O*NET during this work, request job-board content, or
make paid calls.** The completed production migration above remains the live
checkpoint. The focused performance artifact deployment is **VERIFIED**;
production readback is **VERIFIED**. The archived PostgreSQL profile completed
with one bounded timeout; its measurements and limitations are recorded below.
Fixture gains must not be reported as production throughput gains.

All **17 explicitly selected artifacts** (four source entity pipelines, twelve
ontology property pipelines and canonical retention SQL) were installed at
**2026-10-12 13:32:53.873586 UTC** under the scheduler lock. Exact file hashes and
idle/catalogue checks passed; the owned scheduler fence was removed. No SQL
files, migration or jobs were executed; read-only database prechecks ran. Protected
receipt: `~/.local/state/jobtology-hop/performance-runtime-applied-2896f099420a45239e7e868a03e9fad5/receipt.json`.
The separate protected native readback is **VERIFIED**:
`~/.local/state/jobtology-hop/performance-readback-executed-52a361d691a744ae8c4711d4d87de790/receipt.json`.
The four typed ontology verifiers checked **776,513 owner groups / 3,666,327
property rows**, with every complete/partial batch accounted for. Native scalar /
array node passes took **35.216 / 16.829 seconds**; edge passes took **34.347 /
32.791 seconds** (**119.183 seconds** combined). Source verification checked
**52,407 entities / 105 successful batches** in **172.147 native seconds**
(175.685 seconds including its wrapper). The combined read-only SQL preflight
took **171.464 seconds**; this total is not attributed solely to source history.
Exact current VERIFIED load context and public/private hashes were unchanged,
the scheduler fence was absent, and production writes/source requests/paid calls
were zero. These live timings are not a controlled before/after benchmark or
routine write/replay throughput measurement.

The source entity write/verify pipelines now use 500-row UNWIND batches and an
exact match count per batch; all thirteen string fields, types, NULL semantics
and immutable/recovery guards remain. SQL/history selection is unchanged. In a
controlled transport-only 10,001-row fixture with both A/B orders, mean pipeline
write time was **21.508 → 1.7285 seconds** and verification **7.5065 → 1.699
seconds**; Hop process startup added about 8.3 seconds. These are synthetic-ID
transport measurements using real fixture facts, not full-history workflow
speedups. A 60,001-row run verified all input rows and all 121 batch results.
The original source fixture receipt
`~/.local/state/jobtology-hop/jobkorea-dry-run-c4d167dd4681/receipt.json` remains
`FAILED` from its then-unbounded cleanup after all 99 recorded checks passed.
The separate bounded cleanup **PASSED**, with exact business/NCS preservation and
all disposable resources removed:
`~/.local/state/jobtology-hop/jobtology-source-cleanup-f46560fa2f76/receipt.json`.

Ontology property pipelines now group complete typed properties by owner while
preserving NULL/empty distinctions, array order, immutable resume and exact
target guards. In the archived-subset paired verifier runs
`owner-property-native-04a457420ef1`, mean time was **23.4795 → 15.707 seconds**
before the final DISTINCT-owner guard. The final indexed guarded replay
`owner-property-strengthened-c6e5c03d05e7` took **17.650 seconds** with exact typed
equality; it is a separate unpaired measurement. These fixtures require the same
identity index/uniqueness constraint as production and do not establish a
whole-workflow speedup. The supplemental `owner-property-decoder-4a23ac1b0891`
proof covers strict decoding/NULL behavior and positive → negative → positive
verification. All three proofs are retained under the protected state directory.

Three operation helpers are implemented; their commands and guards are documented
in the [operations runbook](../../hop/operations/README.md#isolated-performance-profiles-and-focused-artifact-rollout):

- `profile_archived_postgres.py` restores an exact hash-bound local dump into a
  uniquely named, resource-bounded PostgreSQL container without network access.
  It captures validation, manifest/date/proof plans, buffers and timings across
  initial reads, fresh statistics and custom/generic prepared plans. Bounded
  statement timeouts remain samples rather than aborting subsequent phases.
  Nested plans are optional and now stream into private files before Docker log
  rotation, with verified draining/cleanup. Initial reads follow preservation/validation and
  are not a cold-cache reproduction; statistics and warming remain confounded.
- `deploy_performance_runtime.py` plans/applies/rolls back explicitly selected
  source/ontology HPL artifacts under `refresh.lock`, idle-writer checks and the
  scheduler's existing durable fence. Exact before/after hashes protect rollback.
  The sole permitted SQL artifact is `retention/sql/000_operations.sql`, required
  to match canonical operations SQL byte-for-byte; it is copied, never executed.
  The generated file now retains the canonical function-local `SET jit=off` on
  `record_graph_export_v1`, preventing a future installer from undoing that guard.
- `prepare_performance_readback.py` prepares protected read-only verifier copies
  pinned to the exact current VERIFIED load/release/database and, optionally, a
  source scope. Its guarded executor binds deployed and private artifact hashes,
  records expected SQL owner/property counts and requires native reader/graph
  input rows and every complete/partial batch's successful output counters to
  match. It records native pipeline duration, rechecks context and leaves public
  active-load guards and all database/load state unchanged. The byte-equivalent
  source compatibility verifier is attested without a duplicate history scan.

The combined performance-helper, source/ontology graph, consumer, operations and
runtime reconciliation suite passed **89 host checks**; focused Ruff, Pyright and
diff checks passed. A tiny disposable native PostgreSQL session smoke proved timeout
recovery in the same backend and real custom/generic prepared-plan capture:
`~/.local/state/jobtology-hop/profile-session-smoke-70d193fb3c224405a4f2ec891cef6f43/receipt.json`.
No production writes or deployment were performed by these checks. The earlier
first-read slowdown and atomic/per-run proof-capture observations still have
unresolved causes and differing cardinality/transaction boundaries.
The corrected streaming logger's focused suite passed **24 checks**, including
nonzero failure exit for incomplete draining/removal and preservation of primary
failure evidence. Its tiny
native smoke forced 4-KiB Docker log rotation: the daemon tail lost the first
marker while the private stream retained first/last markers and a complete nested
plan, drained successfully, and removed its container and all anonymous volumes.
Protected receipt:
`~/.local/state/jobtology-hop/profile-log-stream-smoke-b7c6bd4bfe22481cbf1253a16333186d/receipt.json`.

The completed representative JobKorea profile used the retained
`flat-ontology-locked-execution-a6069c14782a42f39955b5bc8272a453/apply/attempt-4ebc359b78c44be0b94d1ff8943ad35f/database-before.dump`
under that protected state directory (759,092,439 bytes, SHA-256
`95133f27c2c760f9994c92249360350f73447fc118af3c4eece15dc0487dd4aa`),
exact run `jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c`,
one sample per phase, a 30-second statement bound and nested plans. No new proof
capture or source-entity expansion was selected. Restore took **135.199 seconds**;
exact source validation passed, source/enrichment fingerprints matched, and the
owned container/anonymous volumes were removed. Protected receipt:
`~/.local/state/jobtology-hop/archived-pg-profile-16aeb26b68ca49c8bcb827c24d556f1b/receipt.json`
(`PROFILED_WITH_TIMEOUTS`: twenty outer samples, nineteen completed JSON plans and
one 30-second custom-plan proof-validation timeout recovered in the same backend).

| Archived read, seconds | Initial | Fresh statistics | Custom plan | Generic plan |
| --- | ---: | ---: | ---: | ---: |
| Exact source validation | 16.570 | 20.616 | 28.629 | 20.926 |
| Live manifest | 4.256 | 4.432 | 5.630 | 4.591 |
| Posting dates | 0.580 | 0.566 | 0.644 | 0.549 |
| Proof validation | 21.580 | 26.015 | ≥30, timeout | 26.537 |
| Proof membership | 0.002 | 0.002 | 0.002 | 0.002 |

Validation dominates this exact-run profile; fresh statistics did not improve
these one-sample reads. Generic proof validation recorded **2,115,050 shared-buffer
hits / 2,368 temporary blocks written**. Its retained nested live-manifest plan
took **4.530 seconds / 363,117 hits / 1,184 temporary blocks**, including per-row
run scans and document index lookups with **8,434 loops**. These findings identify
work worth investigating, not a proven cause of the older slowdown. The original
profiler fetched Docker logs only after execution: early nested plans rotated
away, leaving the final roughly 9.5 seconds and 1,769 valid nested JSON plans.
The helper now streams logs, but this large archive was not rerun; exact validation
internals remain unmeasured. SQL behavior was not changed in this performance patch.

The October 13 checkpoint supersedes the earlier pending source-query work:
complete nested validation capture, scoped query-local sharing, controlled ABBA
source-graph replay and representative two-run first capture are verified.
Each independent writer/verifier still reads current PostgreSQL evidence; no
cross-workflow cache was introduced. Further realistic initial-read and bounded
multi-run tests completed as documented in the October 13 routine report; the
old delay was not reproduced and the four-scope first capture timed out/rolled back.
The current profile is instrumented, follows preservation/validation, reuses
warmed caches and has one sample per phase; it does not establish cold-start
behavior, statistics causality, a global tuning recommendation or full routine
ingestion throughput.

## Revision flattening implementation checkpoint

**Production migration VERIFIED at 2026-10-12 07:15:32.564202 UTC** (16:15 KST),
phase `SCHEDULER_RESUMED`, with `scheduler_fence_removed=true`. Independent business
verification passed at **07:16:11.123507 UTC**. Protected apply receipt:
`~/.local/state/jobtology-hop/flat-ontology-locked-execution-a6069c14782a42f39955b5bc8272a453/apply/receipt.json`;
independent report:
`~/.local/state/jobtology-hop/flat-independent-business-final-20261012T0716Z/report.json`.

The guarded migration removed **39,336 revision nodes / 315,984 legacy
attachments** and created **237,312 exactly backed rerouted edges**, preserving
all 39,336 canonical identities and unrelated typed graph values. Final graph:
**200,952 nodes / 751,971 relationships**, zero revision labels. The separately
sealed flat inventory contains **148,509 nodes / 715,555 edges / 39,336 revision
bindings**. Native finalization passed in **342.335 seconds**; ordinary historical
replay passed in **663.654 seconds**, finishing at **07:08:21 UTC**.

The verified operator preserved **all original 148 PostgreSQL tables/schema**,
original approvals/load checkpoints, catalogue readers and historical exports.
Unchanged v2/v3 exports each contain **1,776,301 rows**; v1's pre-existing
`INTERCHANGE_UNMAPPED_NODE_LABEL` refusal is retained, with no export-function
change. The independent graph report passed all 13 checks: **22,295 source
postings** (JOB 1,369 / Nara 12,492 / JobKorea 8,434), stable and physical IDs and
all eight typed date properties are exact. All **5,878 JobKorea inferred edges**
retain IDs, endpoints and every typed property: 21 `ASSISTANT_REVIEWED`, 5,857
`UNREVIEWED`; 2,556 postings have no link and 5,878 have one. Fence absence was
confirmed separately. No source/model calls or serving promotion occurred.

Additive SQL **028/029** and flat native writers use separate STAGED/final proof
and compatible future catalogue approvals. The all-ten-kind native fixture
preserved **131 historical fixture tables** and exports while testing typed/NULL
facts, reviewed endpoints, future approval/stale replay, interrupted/full installer
replay, operator rollback/retry and forged ownership refusal. The representative
restored-production proof preserved all 148 old tables; sealing/assertion took
**69.527/22.917 seconds**. Disposable resources are cleaned up; retained proofs are
under `flat-native-ffaf1d041ad2/` and `flat-projection-performance-01295fcb5a6d/` in
`~/.local/state/jobtology-hop/`.

A controlled stop during read-only edge verification corrected a measured dense
endpoint lookup hotspot. The guarded six-pipeline amendment preserved the full
typed graph and all 148 old tables before deployment; **30 isolated native cases,
74 host tests, Ruff/Pyright and 197 artifact bindings** passed. Its immutable
manifest is `apply/successor-224a9d4fd3914222b0ba0185a2d7e68a/manifest.json` (SHA-256
`b311d1dd3a879143127f22a431fc321a2a5814fc8b6d291f848126533077c227`), bound to the
original manifest/backup. Earlier failed attempts remain historical evidence.
The optimized pipelines and their repository generator are synchronized.

Performance evidence is retained at
`~/.local/state/jobtology-hop/flat-log-timing-report-a6069c14782a/final/report.json`.
The controlled 500-row verifier measured **11.4709 seconds / 24,381,500 hits**
versus **0.12055 seconds / 18,500 hits** with two explicit endpoint index seeks,
with the same verified result. Production scalar/array passes measured
**1,526.075/819.634 seconds** initially and **79.438/66.159 seconds** on the
already-written, warmed retry; these are not cold-run or whole-workflow speedup
claims. Guarded deletion took **1,339.238 seconds for 39,336 nodes**, a separate
performance follow-up that must preserve every attachment/type/recovery guard.

For future interrupted operations, use the exact receipt and
[guarded operator recovery instructions](../../hop/operations/README.md#flattening-the-approved-ontology-projection);
incomplete amendments require `amend-resume`. The verified checkpoint is complete,
with no active migration fence. Keep older first-read/atomic-capture performance,
source/canonical identity unification, proposed O*NET RDF integration and the
unchanged `MAX_MATCHES=1` policy as separate follow-ups.

## Verified operational state on October 7 (historical checkpoint)

The figures in this section are the October 7 checkpoint. The October 8 rollout
baseline already contains 922 current JOB postings; the earlier 479-posting run
below is historical. The full local JobKorea rollout is tracked separately.

| Component | Observed version or identity |
| --- | --- |
| Hop Web | Apache Hop 2.19.0; `apache/hop-web:latest`; container `ibbwv593fijblilse127wnqd-051002227248` |
| PostgreSQL | 18.6; database `jobtology`; container `j89dw8prq97uiec629avd6w5` |
| Neo4j | 2026.06.0; container `neo4j-1` |
| Document parser | `jobtology-document-parser`; image `20260915-4`; revision `7541e87c0b45d8d209cd3c110f7bf09c72666779-hop4` |

Supporting services run in separate containers. Host cron invokes `~/.local/bin/jobtology-hop-refresh` every 15 minutes. The deployed adapter byte-matches the seven-source `hop/operations/refresh.sh`. All 62 execution rows succeeded, with none unfinished. The final due-work queue is empty: a further scheduler tick exited 0 without creating another execution, source run or request. All seven official sources are within their configured intervals.

The latest JOB run, `f8f4a9c3-151a-4a31-981f-0a949f712605`, was created at 2026-10-06 22:30 UTC (October 7 KST). It contained 479 postings and 958 representations. Native graph verification passed for 958 graph records and 1,916 references. Catalogue readers returned 479 jobs and 92 exams.

The source-only catalogue approved on October 1 is `ontology-catalog-source-20261001`. After repair, the restricted catalogue reader still returned that approval, 479 jobs, 92 exams and 198 NCS-demand rows. `ontology.active_release` is empty: a full reviewed serving release is not active. Attachment and LLM processing last ran manually on September 15–16. No retention writer or maintenance fence is active.

## Nara scheduler repair

Nara's enabled 86,400-second policy is now serviced by the host adapter and `operations/refresh_nara_job.hwf`. The FULL wrapper runs source actions inline so that `start_run.hpl` pins the parent-scoped `NARA_JOB_RUN_ID`; it passes that exact ID to graph loading and records success only after graph verification and checkpointing. Graph failures preserve the accepted PostgreSQL snapshot for recovery.

Before repair, September 16 run `f3b83d1a-5103-40e1-9a1a-976d75b32be6` had no `ingestion.graph_export` checkpoint. Its queued GRAPH recovery used the unchanged `export_pending.hwf` with the exact READY run ID and zero source requests. Native verification confirmed 13,127 records and 13,127 references. Execution 61 exited 0 at 2026-10-07 06:17:58 UTC; the durable checkpoint was written at 06:17:58.588932 UTC with loader `hop-graph-v2`. Its native log is `~/.local/state/jobtology-hop/20261007T060941Z-nara_job-GRAPH.log`. Recovery safely merges the same graph and upserts one checkpoint row.

The next adapter invocation completed a fresh FULL refresh as execution 62, exiting 0 at 06:39:32 UTC (15:39 KST). New run `c1197a0f-2784-446d-b96d-2e253c3d9435` was created at 06:18:08.115352 UTC and is PostgreSQL READY, with `completed_at` recorded as 06:28:28.78345 UTC. It contains 10,540 accepted index rows, 802 open postings, 2,417 selected HTTP documents and 12,946 records, with zero rejected rows. All 2,417 reserved requests reached `RESPONSE_ARCHIVED`; the request total stayed unchanged after the final due-work check.

Native graph verification and an independent Neo4j read both confirmed 12,946 records and 12,946 references in READY/STAGING scope. The exact new run's checkpoint was written at 06:39:31.84354 UTC with `hop-graph-v2`. The September graph remains READY/STAGING with its original 13,127 records and references. The FULL log is `~/.local/state/jobtology-hop/20261007T061804Z-nara_job-FETCH.log`. Observed native runtimes were 8 minutes 14 seconds for recovery and 21 minutes 24 seconds for the fresh refresh, including historical entity-name computation and graph verification.

## Verified mounted-installer reconciliation

The mounted `ontology/install.hwf` now reaches 027, and its SQL 019–027, reader-grants script, Nara `003_checks.sql`, Nara refresh wrapper and host adapter match repository hashes. PostgreSQL already matched the effective definitions, including both `NOT MATERIALIZED` hints in the existing validation view, so no production SQL or grants were replayed.

The focused helper held the scheduler lock, checked active work and catalogue/reader invariants, backed up replaced files and a validated schema-only database archive, and installed only its allowlisted files through verified staging and atomic renames. Final deployment was `VERIFIED` at 2026-10-07 06:09:36 UTC (15:09 KST):

- Plan: `~/.local/state/jobtology-hop/runtime-reconciliation-plan-4111623aa71b4a46b8a7248d1b571440/manifest.json`.
- Success receipt: `~/.local/state/jobtology-hop/runtime-reconciliation-applied-1095a3ea862741e08118ce4806e0fca8/receipt.json`.
- Initial partial receipt: `~/.local/state/jobtology-hop/runtime-reconciliation-applied-25453ea7ab1a49a9b0bd0941f09b8661/receipt.json`. It retained ten new SQL/grant files before a Nara directory-permission failure. The helper was corrected to use container root for allowlisted mounted-file renames and exact staged-file cleanup; the retry installed the remaining four artifacts. The host adapter remains user-owned, and directory ownership and permissions were preserved. The exact orphaned temporary file was hash-checked and removed under lock.

A disposable PostgreSQL environment passed the full native ontology installer and replay with the repository Nara validator. Effective comparison of 019–027 matched 39 functions, 135 triggers and enabled states, 27 columns, 44 constraints, four indexes and 30 function grant decisions, plus the exact validation view. Comparison evidence is `~/.local/state/jobtology-hop/reconcile-review-20261007/comparison.json`. Source-only approval and the empty active-release table were preserved.

Compared graph, CS and retention files remain unchanged. The previously assessed ALIO/JOB XML differences had matching SQL and dependencies and were retained as editor serialization. See the [server runbook](server-runbook.md#focused-october-installer-and-scheduler-reconciliation) for the helper and partial-failure procedure.

## Prefetched JobKorea integration (October 7 implementation checkpoint)

The October 7 implementation added a local-only native Hop importer for supplied
JSON-array and NDJSON files and verified it in isolated fixtures. That phase did
not deploy JobKorea to production; the October 8 rollout below supersedes that
deployment status. No JobKorea provider URLs or paid APIs were requested, and the
official-source scheduler remained unchanged.

JobKorea is an eighth supported source in the existing `ingestion` ledger. Each
supplied row retains its raw object and format-specific locator, with repository-generated
file hashes, import provenance, normalization and quality diagnostics. Documents
use `transport=LOCAL_FILE`, NULL HTTP status and NULL provider result, with no
HTTP request ledger entries. File/parser/policy identity makes replay idempotent.
READY means validation of the supplied file (`FILE_ONLY`), not provider-wide
completeness or evidence that missing postings closed.

The importer accepts the 288 missing start dates. Missing or NULL end dates use
`ROLLING` / NULL end dates / `USER_POLICY`; the sample has 79 such rows. The
midnight-UTC date encoding is treated as a calendar date rather than a fixed
instant. Category-like employer labels remain category evidence, and other
employer names remain unverified. Full description content is absent for this
sample: metadata is accepted with `content_status=MISSING` and
`extraction_eligible=false`, without fetching references or inventing text.

The exact READY run passes to the shared `graph/load_snapshot.hwf` and durable
`hop-graph-v2` checkpoint. JobKorea posting identities match the CS source-qualified
hash namespace; graph facts exclude raw objects, private URL references and
narratives. The optional `cs.common_posting` bridge reads native READY records
without a second staging copy. Existing JOB-ALIO/Nara identity and hash contracts,
past decisions and source-only catalogue approval are preserved by the additive
implementation.

The native Hop/PostgreSQL/Neo4j fixture passed. All 887 source rows were accepted
with zero rejections; checks confirmed 288 missing starts, 79 policy-assumed
rolling ends, 808 fixed dates, 887 MISSING descriptions, zero extraction-eligible
rows and NULL actual scrape time. Independent Neo4j reads verified **887 records,
887 references and 887 distinct posting identities in READY/STAGING**. Native
installation/replay upgraded the legacy shared checks; repeated import and graph
load preserved record identities and one durable checkpoint. Injected graph
failure preserved PostgreSQL READY and skipped a new success checkpoint; recovery
and malformed-date/file/archive failure gates passed.

The protected PASSED receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-35bf3b62a26c/receipt.json`.
It records no production writes, no source requests and no paid calls. Private
input/archive/project/config scratch files, disposable containers and the
internal Docker network were verified removed. Focused PostgreSQL fixtures also
passed for all seven existing source projections, stable validation-hook replay,
truthful local provenance, unchanged legacy CS hashes/review lineage and zero
local HTTP request rows after operations replay. See the [adapter README](../../hop/ingestions/jobkorea/README.md)
for the isolated command and [prefetched postings](prefetched-postings.md) for
source evidence and responsibilities.

## October 8 full local dataset

The supplied `../jobtology/2026-10-7_scrapes` directory contains seven NDJSON
exports and one category-code metadata file. The private audit preserves all eight
original files. Its 12,105 listing observations represent 8,434 unique posting
IDs, with 3,671 extra observations across 2,907 duplicate identities. There are
303 listing-content conflicts and 2,604 reference/context variants; seven
content-conflict cases contain differing supplied deadlines. Eight scraper-error
envelopes are explicitly quarantined with original file/line/byte provenance.
No missing observation is treated as a provider closure.

The reviewed whole-observation policy used for this load produced 8,434 unchanged
selected lines:
7,357 explicit deadline dates and 1,077 missing ends accepted as policy-assumed
rolling recruitment. Missing starts number 1,186. Every selected description is
absent from supplied local content, so full-description eligibility remains false.
No source URL recovery, inferred duty or invented scrape time is involved.

The composed file is 21,951,764 bytes, SHA256
`6a1d853aaca446a8c9a6081a8bfe3347ad24e496b5915e1ba2e50571b1d33d72`.
Its private occurrence map preserves every selected and alternative original
file/hash/physical-line/UTF-8 byte range. The composition descriptor, SHA256
`f6537b9a1c1180d4cc05a986bbdbe82a66c03dd0eb4e2dd1335afef9e2a088f3`,
also binds original inventories, selection rules, content/deadline conflicts and
quarantined error envelopes. These artifacts and original exports stay out of Git.

The final isolated native import-only preflight passed all 19 checks with 8,434
READY source records and posting identities, zero rejections or validation errors,
zero source/model requests and verified cleanup. Receipt:
`~/.local/state/jobtology-hop/jobkorea-dry-run-33a1897217ea/receipt.json`.
The preflight took about 268 seconds. Whole-file validation remains material at
this cardinality; correcting the normalizer's declared row estimate to one removed
the inflated planner estimate and JIT work, without establishing a meaningful
runtime improvement over the earlier 283-second fixture.

The focused runtime deployment is VERIFIED at 2026-10-08 02:25:47 UTC
(11:25 KST): 27 files deployed, 73 dependencies verified and a protected full
PostgreSQL custom-format backup of 613,063,794 bytes retained with a validated
archive listing. Receipt:
`~/.local/state/jobtology-hop/jobkorea-runtime-applied-9e53b293a8404b41ae1722695e940c3b/receipt.json`.
Native source and linking-contract installers subsequently passed.

Production PostgreSQL independently confirms exact run
`jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c`
as READY and loaded, with 8,434 records and 8,434 distinct source posting IDs in
17 committed NDJSON batches. Independent normalized counts match the composition:
7,357 `FIXED_DATE` / `SOURCE_FIELD` ends with a date, 1,077 `ROLLING` /
`USER_POLICY` ends with a NULL date, 1,186 missing starts and 8,434 `MISSING`
descriptions. At this October 8 checkpoint, the supplied evidence did not include
the scrape timestamp and `scraped_at` remained NULL. The later user-reported
collection time is recorded separately in the October 11 date-metadata checkpoint
below; it does not rewrite this receipt or the frozen inputs.

The native full-import workflow passed at 2026-10-08 02:53:35 UTC (11:53 KST),
after 1,531.086 seconds (25 minutes 31 seconds). Its exact-run source graph passed
all 8,434 record, reference, entity-name and membership checks without errors.
The independently read durable source-graph checkpoint records
`exported_at=2026-10-08T02:53:35.701733+00:00`, loader `hop-graph-v2`.
The immutable dataset-provenance descriptor is registered. Deterministic input
preparation is VERIFIED at 2026-10-08 02:57:47 UTC (11:57 KST): all 8,434 source
postings have exactly one frozen bundle, in 34 committed batches, with zero
missing, extra or missing-provenance bundles. All 8,434 bundles are eligible for
later listing-metadata extraction; none is eligible for full-description
extraction. The existing 1,552 bundles remain, for 9,986 total input bundles.
Receipt:
`~/.local/state/jobtology-hop/full-jobkorea-20261008/production-load/prepared-inputs/receipt.json`.

Before/after input-preparation counters are identical: 25,444 historical source
requests, 4,241 model attempts, 68 LLM batches, 3,301 items, 177 extraction
decisions, 585 link decisions and nine publications. Reservations, cost totals
and datasets also remain unchanged. Every increment from this task is zero;
these are preserved historical totals, not requests or charges from the new
dataset. No API key was read, no LLM parse or model call ran, and no semantic link
was created. Keys and accounts were not changed.

The full production supervisor is VERIFIED at 2026-10-08 03:01:52 UTC
(12:01:52 KST), after starting at 02:25:47 UTC. All eight exact-run source-graph
checks passed after the load. Counts and row digests for all 46 preservation
tables match before/after exactly, and the source-only catalogue context is
unchanged. The seven-source scheduler and historical source records, inputs,
attempts, reservations, costs, reviews and publications are preserved.
The independently read new run is READY / REPLAY with zero validation issues;
its exact graph checkpoint and complete frozen-input receipt are verified.
Final cleanup checks found zero rejected JobKorea rows, zero LOADING runs and
zero active full serving releases. The scheduler lock was independently acquired
and released, and temporary graph-reader workflow files were removed.
Overall receipt:
`~/.local/state/jobtology-hop/full-jobkorea-20261008/production-load/execution-27977bbdb52f44a183f9e9b0a4856c93/receipt.json`.

## Streaming NDJSON checkpoint

The supplied October 7 NDJSON export
`../jobtology/j_muwimlga1lq0obm7dp.ndjson` has 416 unique object lines and
841,618 bytes, SHA256
`f42cff119b4db77ff2c1bdb5d57eefd2398bae677f6fbf8d14cc390b67ae20e3`.
All rows passed native import and READY validation; 170 missing starts are
accepted, 26 missing ends use the rolling policy, and all 416 descriptions remain
MISSING. Actual scrape time is unknown. Independent Neo4j counts and replay
confirmed 416 records, references and posting identities in READY/STAGING, with
one durable source-graph checkpoint.

Migration `006_ndjson.sql` adds immutable exact-serialization chunks and physical
line hashes, one-based `line:<n>` locators, zero-based UTF-8 byte offsets/lengths
and bounded chained manifest proofs. The native reader streams archive copy,
hashing and parsing, and PostgreSQL commits only bounded batches. A genuine JVM
halt after two committed batches left six fixture rows LOADING. Archive-only
resume completed all 13 fixture rows without duplicate rows, locators or posting
identities. Permanent framing/encoding/identity failures cannot produce READY;
valid JSON with malformed source fields becomes REVIEW_REQUIRED with exact
line/field diagnostics. Previously committed prefixes remain invisible to
READY consumers.

The final full native suite passed **126 checks**, including LF/CRLF and AUTO `.ndjson`
and `.JSONL` dispatch, missing final LF, malformed/truncated JSON, UTF-8, blank/BOM,
duplicate keys/identities, oversized lines, source-field errors and replay gates.
Persisted redacted failure diagnostics matched the exact offending physical line
and byte offset, including SQL-reported duplicate identities. Final native source
installer replay preserved the frozen semantic bundles.
It prepared five verified semantic input bundles with no key or model request.
The same supplied observation retained its posting identity and model content
hash across NDJSON and JSON-array files, while audit manifests differed; the
original 887-row array run identity, records and model hashes survived replay.

An import-only stress fixture streamed **100,730,368 bytes** (about 96.06 MiB),
512 generated synthetic rows, using a 256 MiB Hop heap. It completed 25 batches;
the largest committed batch was 4,131,519 bytes/21 rows and largest line 196,739
bytes. The stress case loaded no graph and is a size/memory check, not a
high-cardinality or full-production benchmark. The 16 GiB maximum is a validation
limit, not a tested file size.

Protected receipt:
`~/.local/state/jobtology-hop/jobkorea-dry-run-42ee0beaceeb/receipt.json`.
All source/model requests and production writes were zero. Private scratch,
disposable containers and the internal network were verified removed. The earlier
113-check NDJSON receipt
`~/.local/state/jobtology-hop/jobkorea-dry-run-dd5b93bf11a0/receipt.json`
and prior 887-row source/linking, canonical-reinstall and measured paid-pilot
receipts remain valid historical evidence. See the [adapter README](../../hop/ingestions/jobkorea/README.md)
for exact NDJSON limits, staging commands and `RESUME_RUN_ID` recovery.

## JobKorea semantic-linking preparation

LLM migrations 027–028 add deterministic `jobkorea-input-v1` bundles and a bounded
IT/software/data candidate pilot to the existing reviewed linking path. Input
strings remain exact local evidence; normalized listing facts preserve employer
uncertainty and deadline policy bases separately. Model content hashes omit raw
row/run locators, while immutable manifests bind each exact source file, row and
run. Reordering an unchanged observation preserves its content hash and changes
its audit bundle identity. Original source records and historical JOB-ALIO/Nara
hashes and reviews remain unchanged.

Missing full descriptions stay `MISSING` and full-description eligibility remains
false. Listing-metadata processing has independent eligibility. Titles, roles,
categories, employer labels and assumed deadlines never establish work duties.
Only supplied local narrative can support explicit-duty NCS matching, followed
by independent extraction and link review. Missing duties skip matching; lexical
pilot `CANDIDATE` and `UNKNOWN` values remain unverified scope hints.
Publication also requires the verified JobKorea source graph and the target NCS
competency graph loaded in Neo4j for the exact current run pins; PostgreSQL READY
does not establish either graph prerequisite.

The native adapter exposes `install_linking.hwf`, read-only
`preview_linking.hwf`, and `prepare_linking.hwf`. Preparation pins current READY
JobKorea/NCS runs and verified bundle IDs. Defaults are five postings, a hard cap
of 25, `ko-link-v1`, `REVIEW`, and `EXECUTE_REQUESTS=N`. Batch and rolling daily
accounting caps default to $0.25, with $0.05 per-request reservations. Completed
responses settle to reported cost, including upstream BYOK inference charges,
and release unused reservation capacity; unknown-cost requests retain holds.
The preview's reservation coverage is not a provider price estimate.

Focused isolated PostgreSQL checks passed for installation without the optional
source adapter, source installation/replay, exact Korean multiline evidence,
missing-description processing, supplied narrative support, forged-bundle
rejection, required item bindings, immutability and cache-stable reordered input.
Ruff, Pyright and diff checks passed. The full offline native fixture passed 52
checks in `~/.local/state/jobtology-hop/jobkorea-dry-run-64846daa6943/receipt.json`:
all 887 source rows, 587 lexical candidates, 300 unknown-scope rows and the default
five-posting pilot. It verified zero key reads/model requests during preparation,
missing-duty abstention, a separate synthetic narrative through extraction/NCS
matching/independent review, both source graphs, native Neo4j publication/replay
and successful exhausted-pilot no-ops. Source/model HTTP requests were zero;
scratch files and disposable resources were removed. The targeted synthetic
fixture also passed in `jobkorea-dry-run-b38a97d0efdc/receipt.json`.
These October 7 preparation fixtures did not deploy adapters to production;
the October 8 rollout section tracks the subsequent authorized deployment. See the
[pilot instructions](../../hop/ingestions/jobkorea/README.md#prepare-a-small-semantic-linking-pilot).

The October 8 whole-dataset entry point is
`hop/ingestions/jobkorea/tools/prepare_inputs.py`. It prepares every accepted
listing through the existing deterministic per-posting bundle function in
committed batches of 250 by default, with a maximum of 1,000. It needs no NCS
pin and creates no LLM batch, item, attempt, reservation, review decision or
semantic link. Full READY validation runs before and after preparation; selected
row, normalization, physical-line and frozen-bundle verification remains intact
for every posting. Private immutable batch receipts and a cursor checkpoint allow
replay after a database commit whose local acknowledgement was interrupted.

Migration `007_dataset_provenance.sql` freezes one per-run audit descriptor for
the composed snapshot, original-export inventory, complete occurrence map and
selection policy. Registration requires the exact READY file hash, byte length
and accepted line count, and must precede every bundle for that run. Direct
INSERTs use the same validation and locking as registration. Updates, deletion
and truncation are forbidden except for the existing retention deletion protocol.
The optional `--register-provenance-dir` flag verifies all local file digests,
lengths, selected count and unchanged composed/original byte bindings before
registration. The descriptor enters audit manifests; model-facing evidence and
content hashes remain unchanged. Historical bundles without a descriptor remain
byte-stable. Isolated PostgreSQL checks passed these gates, direct forged and
late writes, local metadata mismatches before DB access, complete input coverage,
commit-acknowledgement-loss resume, replay and unchanged request/accounting/review
and publication counters. The complete production rollout and receipts are
recorded in the October 8 full-dataset section above.

### Existing explicit-duty linking entry point

The later October 8 account-readiness/linking instruction lifts the earlier
paid-work hold. The existing explicit-duty pilot entry point can reuse the
frozen inputs with the following exact current pins. This command still defaults
to planning only and does not implement the separately authorized metadata
occupation inference path.
The NCS competency pin is `ba32f673-255c-4990-80d4-8dbef6008e2f`, independently
read as the latest READY run with a source-graph checkpoint. Recheck current pins
and both exact source graphs before eventual publication.

```bash
JOBKOREA_HOP_CONTAINER=b4a19e0a24e8
JOBKOREA_READY_RUN=jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c
JOBKOREA_NCS_PIN=ba32f673-255c-4990-80d4-8dbef6008e2f

docker exec -e HOP_OPTIONS=-Xmx1024m \
  -w /usr/local/tomcat/webapps/ROOT "$JOBKOREA_HOP_CONTAINER" \
  bash hop-run.sh -j default -r jobkorea-local \
  -f /usr/local/tomcat/webapps/ROOT/config/projects/default/ingestions/jobkorea/prepare_linking.hwf \
  -p "JOB_RUN_ID=$JOBKOREA_READY_RUN,NCS_RUN_ID=$JOBKOREA_NCS_PIN,PILOT_LIMIT=5,EXECUTE_REQUESTS=N" \
  -l Basic
```

Execution remains off in this command. It creates only a bounded five-listing
request plan; the existing hard limit is 25. Use `preview_linking.hwf` with the
same exact pins for a read-only scope and budget preview. Paid execution requires
explicit `EXECUTE_REQUESTS=Y` and bounded accounting caps; the latest instruction
authorizes this task subject to the scope above.
Missing supplied narratives remain grounds to abstain from duty matching, and
independent extraction/link reviews are required before semantic publication.
None of these pilot workflows is part of the authorized full-input preparation.

### Measured paid-pilot cost

The authorized isolated OpenRouter/OpenAI BYOK pilot completed seven HTTP-200,
VALIDATED calls using `openai/gpt-5.6-luna`. Receipt
`~/.local/state/jobtology-hop/jobkorea-dry-run-9416a2b00918/receipt.json` is
`COMPLETED_NATIVE_PAID_PILOT_TEST_REVIEWED`; cleanup checks passed and reported
upstream charges total **$0.00442920**, with **$0 observed router fees**.

| Input and scope | Extraction cost | NCS-matching cost | Total observed cost | Mean scaled to 1,000 listings |
| --- | ---: | ---: | ---: | ---: |
| Five real listing-metadata inputs, missing full descriptions | $0.00326475 | $0; all five skipped | $0.00326475 | **$0.65295** |
| One short synthetic local narrative with two toy NCS candidates | $0.00056465 | $0.00059980 | $0.00116445 | $1.16445, illustrative only |

The real metadata pilot used 9,198 input tokens and 805 output tokens, including
534 reasoning tokens. It produced no duties; matching skipped without requests.
Three extractions reported `attachment_required` and two `not_stated`. The root
assistant independently checked grounding of all seven paid outputs and recorded
the private `pilot-review.json` test-review sidecar. No database ACCEPT decisions
or graph publication were created from these paid responses. The synthetic row
tests literal-duty and candidate compatibility; it is not a real full-description
benchmark or a measure of retrieval quality against the full NCS catalogue.

The measured real-listing mean implies about **$0.65 per 1,000 comparable metadata
inputs**; individual observed request costs scale to $0.5334–$0.79485 per 1,000.
This is a five-item pilot extrapolation. Its input, model, output and cache
behavior must remain comparable for that estimate to apply. There were 9,183
cache-write tokens and zero cache-read tokens. The
[OpenAI endpoint pricing observed during the October 7 pilot](https://openrouter.ai/api/v1/models/openai/gpt-5.6-luna/endpoints)
is $0.20 per million ordinary input tokens, $0.25 per million cache-write tokens,
$0.02 per million cache-read tokens and $1.20 per million output tokens. Applying
those separate categories matches the reported upstream charges. The
[model pricing](https://openrouter.ai/openai/gpt-5.6-luna) and
[BYOK accounting guide](https://openrouter.ai/docs/guides/overview/auth/byok)
distinguish inference charges from router fees; a zero `usage.cost` alone is not
a zero upstream bill.

For fresh inputs, estimate `1000 × (E + q × M)`, where `E` is mean extraction cost,
`M` mean matching-request cost and `q` the fraction receiving supported-duty
matching. With exact extraction/matching cache-hit fractions `cE`/`cM`, use
`1000 × ((1-cE) × E + q × (1-cM) × M)`. Repository reuse of a validated exact
output makes no new request; provider prompt caching still has its reported
token charges. The metadata pilot has `q=0`, so a duty-rich real-description
estimate remains unmeasured. Reservations are excluded from these billing figures.

## Current inferred-occupation processing

All **8,434 frozen listings have terminal outcomes: 5,889 matched, 2,527
abstained and 18 charged citation-validation exclusions**. There is no unsent
work or unknown cost. Initial full processing
completed at 12:04 UTC and its 5,862-edge graph was independently verified at
12:09 UTC. The confirmed PM shortlist gap was then corrected through additive
SQL 034, preserving source pins, raw input, prior history and the strict-duty
contract. Full descriptions remain missing for all listings; JobKorea source
HTTP and job-description extraction charges remain zero.

Targeted correction completed at **15:27:26.450 UTC** (October 9 in Korea):
21 paid BYOK requests produced **16 matches and five abstentions**, with zero
router fees or unknown costs. The exact user example `49550356` (`AI/Cloud 개발
PM`) now matches IT프로젝트관리 (`20010401`). Root individually reviewed all 16
matches and committed ACCEPT decisions **24–39**: 15 IT project-management
matches and one generic 프로젝트관리 (`01010102`). AI PM, course, multirole,
physical-security and hardware controls abstained. This does not establish
blanket semantic accuracy. Five other cases were classified as clear retrieval
gaps and excluded at that checkpoint; the October 11 source review reassessed
them as four plausible IT-PM shortlist gaps and one system-maintenance ambiguity
(`49936406`).

**Gross task cost is $4.08155705** ($4.08154925 native plus $0.00000780 probe),
**$0.48394084 per 1,000 unique listings**, with **$0.91844295** headroom under the
original $5 cap. Native paid calls total 8,370, including the original 22 challenge
repeats and 21 correction repeats. The original single $0.00051760 OpenRouter-funded
inference remains an inference charge, not a BYOK router fee; all 21 correction
calls were BYOK. The lighter `openai/gpt-5.6-luna` model and provider routing are
unchanged. The previous 12:08 UTC OpenRouter reconciliation/wallet $5.41906136
is historical; upstream $50 credit remains user-reported, not API-verified.

Production SQL 029→035 is installed; the October 11 status-only verification is recorded below. Native correction publication/readback
completed for **5,878 edges: 5,857 UNREVIEWED and 21 ASSISTANT_REVIEWED**, excluding
11 latest semantic REJECTs; unlinked postings are 2,556. **Independent verification completed at
15:38:20 UTC: all 5,878 exact payloads passed in 24 chunks.** All original 5,862
candidate IDs, endpoints and payload hashes are preserved, with 16 new reviewed
links; the snapshot is unchanged, writer leases are zero and legacy relation
counts remain 388/0. The exact user node now has its current VERIFIED, accepted
ASSISTANT_REVIEWED link to `ncs:occupation:20010401`. The original
5,862-edge readback remains verified historical evidence. All inferred links
remain STAGING, `METADATA_INFERRED`/`MODEL_INFERRED` and NULL/UNASSESSED.
Historical decisions retain 18 REJECTs and now 21 ACCEPTs; charged citation
failures remain preserved without retries. No serving release was activated.

The [dated inferred-linking report](2026-10-08-inferred-linking-report.md)
retains chronological account/pricing observations, deployments/backups,
pilot/challenge reviews, batch failures/costs, protected receipts and isolated
validation. The pre-034 integration checkpoint passed 214 unit tests, targeted Ruff/Pyright,
413 Hop XML parses and whitespace checks. SQL 034 passed 21 focused unit tests,
46 native checks and full-catalogue coverage for 61 cases/47 boundaries. Enduring adapter behavior is documented
in the [JobKorea README](../../hop/ingestions/jobkorea/README.md#authorized-metadata-occupation-inference).

## October 11 runtime and catalogue refresh review

Status-only SQL **035** is deployed. Public file deployment verified at
**07:38:51.419815 UTC on October 11** and native installation completed at
**07:39:06.386236 UTC**, after a validated full PostgreSQL backup. The final
protected postinstall proof verified at **07:43:48.257607 UTC**: all **57 table
fingerprints, 291 other function definitions and 225 trigger definitions/enabled
states** remain unchanged, as do source pins, frozen inputs, reviews, eligible
links and cost. The effective native status definition was independently checked
using mounted Hop 2.19.0 comment parsing and disposable PostgreSQL 18.6.

The 18 completed invalid citation outputs now show **`VALIDATION_FAILED`**, with
**zero `PENDING`**. Remaining status counts are unchanged: 2,527 `ABSTAINED`,
5,857 `REVIEW_PENDING`, 21 `ACCEPTED_INFERRED_OCCUPATION` and 11 semantic
`REJECTED`. The new label changes no output, cost, retry or review decision.
Generally, `VALIDATION_FAILED` also covers completed unpaid categorization
rejections; `REQUEST_FAILED` denotes completed request errors and does not imply
known cost. The current item's categorization pointer controls failure status,
including reused attempts; unsent, running or incomplete attempts stay pending.

Deployment receipt:
`~/.local/state/jobtology-hop/jobkorea-runtime-applied-126505d89d884918a6c30282def9bff8/receipt.json`.
Native receipt:
`~/.local/state/jobtology-hop/inferred-occupations/20261011T073901Z-install-90957b1c65c1/receipt.json`.
Final preservation proof:
`~/.local/state/jobtology-hop/status-followup-20261011/after-035-native-verified.json`.
The independent native definition proof is
`native-comment-stripping-proof/receipt.json` in that same protected directory.

The regular official-source scheduler refreshed NCS competency data on October 9:
new run `64c20b47-0575-476e-9a28-d58d16d8c939` became READY at
**09:02:41.641284 UTC**, with its source-graph checkpoint at **09:20:39.305469 UTC**.
The inferred links retain their original NCS pin
`ba32f673-255c-4990-80d4-8dbef6008e2f`; the frozen JobKorea run is unchanged.
Read-only comparison found **1,094 occupations and 15,520 normalized competency
units in each NCS run**, with zero added/removed occupation codes, occupation
name changes or normalized content changes. Both ordered catalogue SHA256 hashes
are `51330a53789f5b331a00a9e9d47c6075f578d5bf38f58e1fd94a94a7998ff99d`.
This content equality does not rebind the historical inference provenance.

The regular NCS career-path refresh execution 79 subsequently completed
successfully at **2026-10-11T09:37:39.857939Z**. Its latest READY
`ncs_career_path` run is `6b57bd57-2d42-4c61-a6a3-7776001491e9`, created at
**09:15:06.144666 UTC on October 11**; the prior October 9 career-path run remains
historical. This source-only refresh is separate from the NCS competency pin
used by inferred occupations. It changes no frozen input, inference, review,
cost or historical linking pin and does not rebind the original
`ba32f673-255c-4990-80d4-8dbef6008e2f` provenance.

A single native Neo4j read-only aggregate passed at **07:32:38 UTC on October 11**:
all **5,878 original-pin current edges** retain VERIFIED projection state,
STAGING scope and NULL/UNASSESSED confidence, with **21 accepted
ASSISTANT_REVIEWED and 5,857 UNREVIEWED**. The exact user-selected AI/Cloud 개발 PM
node still has its reviewed IT프로젝트관리 edge; legacy relation counts remain
388/0. This fresh aggregate supplements the October 8 full 24-chunk payload proof;
it is not a fresh full-payload verification.

The current SQL graph projector returns **zero rows for the historical NCS pin**
because it requires the latest READY pin. This is a dependency-refresh limitation,
while the historical graph edges remain present. No republishing, pin rebinding
or new paid work was performed. Native accounting remains **$4.08154925** across
all NCS pins for this frozen JobKorea cohort, or **$4.08155705 gross** including the
probe. An installer guard may use the current NCS pin, but that pin's empty
pair-filtered spend ledger does not reset the original **$5 combined task cap**.

Protected evidence is under
`~/.local/state/jobtology-hop/status-followup-20261011/`:
`catalogue-refresh-review.json`, `runtime-tested-baseline.json` and
`historical-aggregate-20261011T073234Z/receipt.json`. The baseline protects 57 table
fingerprints, 291 function definitions other than the status function and 225
trigger definitions/enabled states; global official-source scheduler counters are
observed separately from frozen-input and inference-history preservation.

The offline coverage follow-up audited all **2,527 abstentions** against their
exact frozen source bindings and all **1,094 pinned catalogue occupations**, with
SQL 034 v3 shortlists recomputed at the existing cap of 12. **32 shortlists
changed**, **56 listings still had zero candidates**, and **501 listings had only
title evidence**. Priority groups and overlapping vocabulary flags are
`HEURISTIC_DIAGNOSTIC_UNREVIEWED`; they identify later inspection work, not correct
occupations, semantic accuracy or approved links. No new model call, retry,
review decision or graph publication was added. Protected inputs and grouped
results are in `~/.local/state/jobtology-hop/coverage-followup-20261011/` as
`frozen-abstentions-v3-verified.json` and `coverage-audit-v1.json`; see the
[adapter audit commands](../../hop/ingestions/jobkorea/README.md#authorized-metadata-occupation-inference).

A separate source review identified **65 distinct rows where additional
shortlist candidates are plausible**: four IT-PM, 28 mobile/application development, 18 LLM,
seven English-ML, five IT-solution-sales and one each software-support, SRE and
UI. Nine distinct negative/ambiguity controls are queued separately. This review
approves candidate plausibility only; it adds no semantic ACCEPT or database
review status. At the planning rate of $0.484 per 1,000 requests, a maximum
74-request scope estimates **$0.035816**; this is not an accounting cap or measured
new charge. No request was executed. The frozen snapshot rollover and cost
accounting across NCS pins must be handled before any later paid pilot, retaining
the original $5 combined cap. Evidence is
`source-reviewed-correction-recommendation.json` and the verified `receipt.json`
in `~/.local/state/jobtology-hop/coverage-followup-20261011/`.

## October 11 posting ingestion date metadata

The user supplied the actual collection timestamp for the whole 8,434-posting
JobKorea snapshot on October 11: **2026-10-08 02:48:14 Asia/Seoul (KST)**,
equivalent to **2026-10-07T17:48:14Z**. The implementation records it as separate
`USER_REPORTED` evidence bound to the exact accepted run and file SHA256, with the
reported timezone, opaque evidence reference and actual evidence-recording time.
The original receipt's NULL `scraped_at`, immutable dataset provenance and all
frozen input hashes remain historical evidence rather than being rewritten.

The additive graph contract exposes `first_ingested_at`, `last_ingested_at`,
`latest_ingestion_run_id`, `ingestion_batch_date` (Asia/Seoul),
`ingestion_time_basis`, `scraped_at`, `scraped_at_basis` and
`scraped_at_evidence_reference` on existing `jobPosting` entities. Earliest/latest
ingestion dates use accepted runs that actually contain the posting,
independently of display-name selection; graph replay does not advance them.
A compact append-only PostgreSQL observation ledger retains timestamps without
a run foreign key, allowing future source-run cleanup to preserve date metadata.
The latest observation's unknown scrape time must not inherit an older run's
known scrape time.

After the scheduled Nara execution 78 completed at
`2026-10-11T09:08:27.27854Z`, a fresh pre-deployment read-only review identified
**38 checkpointed READY posting runs and 22,290 target identities**:
31 JOB-ALIO runs/1,364 identities, six Nara runs/12,492 identities and one
JobKorea run/8,434 identities. This supersedes the earlier historical preflight
scope of 37 runs/22,287 identities. These were pre-deployment observations;
the successful locked backfill subsequently confirmed this scope.
The exact JobKorea receipt's immutable import time is
`2026-10-08T02:28:05.462961+00:00`, distinct from the supplied collection time.
The operator's isolated native snapshot fixture passed typed Neo4j-property/list
fingerprint and quoted CSV/Korean-text framing checks, with no production write,
source/model request and verified cleanup. Protected receipt:
`~/.local/state/jobtology-hop/jobkorea-dry-run-a7fc7f8e59d6/receipt.json`.

Repository implementation passed **33 focused unit tests and 48 isolated native
checks**. Native checks verified Neo4j datetime/date types, source-specific time
bases, older-run replay, absent-posting and display-name independence,
latest-unknown scrape clearing, evidence validation/immutability, preserved
source/receipt/frozen-input and non-posting history, and timestamp survival after
source cleanup and installer replay. Fresh capture of 12,000 observations across
three runs/4,000 identities took **1.45366 seconds** in the synthetic fixture;
this measures the fixture's ledger capture. Production timings for the verified
supplied scope are recorded below; larger-size throughput remains unverified.
The fixture made no source/model requests or
production writes, and cleanup passed. Protected PASSED receipt:
`~/.local/state/jobtology-hop/jobkorea-dry-run-709844af59c7/receipt.json`.

The eight-file public deployment is VERIFIED. Its receipt is
`~/.local/state/jobtology-hop/jobkorea-runtime-applied-c0a9a2e27f474c818fa0dc5ad5485c4a/receipt.json`.
The native SQL installer succeeded at **09:43:14 UTC on October 11**, and the
deploy/install supervisor finished VERIFIED at
**2026-10-11T09:43:47.517225Z**. Protected supervisor receipt:
`~/.local/state/jobtology-hop/posting-dates-deploy-install-6132e3e7569846878f2817fa3a408c59/receipt.json`.
An earlier attempt stopped before writes while execution 79 held the refresh
lock; the successful attempt used the fresh reviewed eight-file plan after that
refresh.

### Posting-date pause and resume checkpoint

The user requested a pause while deploy/install was running. That existing atomic
step completed safely; no historical date backfill or `USER_REPORTED`
collection-time registration was started. A read-only PostgreSQL check at
**09:44 UTC on October 11** found zero `posting_ingestion_observation` rows,
zero `jobkorea_collection_time_evidence` rows, zero LOADING runs, zero graph
writers and zero unfinished refreshes. The operator session exited successfully
with no task process left running. The date task made no source or paid calls.
The 33-unit/48-native PASSED implementation was frozen at this pause checkpoint
as recorded above.

The supplied whole-snapshot collection time remains
**2026-10-08 02:48:14 Asia/Seoul (KST)** /
**2026-10-07T17:48:14Z**, with `USER_REPORTED` basis. At the pause checkpoint it was
unregistered, and the original receipt and frozen inputs retained NULL scrape
time. The resumed apply registered the separate supplemental evidence, and full
preservation/readback verification passed. Regular ingestion has
the date hook, so ordinary future ingestion may
advance the new ledger. The zero counts above describe the historical pause
checkpoint.

The user resumed at **09:46 UTC on October 11**. Independent resume checks found
all eight deployed artifacts, 407 function definitions and 307 trigger
definitions unchanged, with empty new ledgers and idle runtime. The host operator
helper corrected protected temporary-file ownership/privacy without changing
deployed artifacts. Its non-root read-only smoke proof inspected one posting and
two edges with no writes:
`~/.local/state/jobtology-hop/posting-dates-nonroot-readonly-smoke-173dd8dc74264f40bc22f76665e2b407/receipt.json`.
The focused tests now total **36 passing tests**; the core 48-check native PASSED
implementation is unchanged.

The fresh reviewed plan is
`~/.local/state/jobtology-hop/posting-dates-plan-387fc28aae2b46f29c8f100a0f973f2f/manifest.json`.
Its validated source scope is **22,290 `entity:jobPosting` identities**: 1,364
JOB-ALIO, 12,492 Nara and 8,434 JobKorea, with **122,509 incident edges** and
**143 protected tables** captured for preservation checks. The global
`jobPosting` count of 23,304 also includes 1,014 separate
`ontologyEntity:jobPosting` catalogue nodes; those are outside this source-date
backfill scope.

All **38 native date updates** finished successfully at **10:43:39 UTC on
October 11**, with **86,760 ingestion observations** captured and supplemental
collection evidence registered. Apply finished **VERIFIED at
2026-10-11T10:47:33.718443Z**. All graph fingerprints excluding the allowed date
fields, all **143 protected table fingerprints** and schema definitions remain
unchanged, and append-only checks passed. Its protected receipt is
`~/.local/state/jobtology-hop/posting-dates-apply-8c8bcff93cdb4f57a5b7fd67f3c24c04/receipt.json`.

Independent readback finished **VERIFIED at
2026-10-11T10:48:07.300361Z**, with all **seven checks passing**. Exactly
**22,290 source nodes** have typed first/latest ingestion timestamps, batch dates,
run IDs/time bases and ordered dates. All **8,434 JobKorea nodes** match every
expected date, run and basis; the other **13,856 scrape timestamps remain
unknown**. The ledger contains 86,760 observations across 38 runs/22,290
identities: 15,412 JOB-ALIO rows/31 runs, 62,914 Nara rows/six runs and 8,434
JobKorea rows/one run. Exactly one run/file-bound `USER_REPORTED` evidence row is
registered. The original receipt still has NULL `scraped_at`, with unchanged
import time/file SHA256; frozen source, LLM and accounting fingerprints also
remain unchanged. The task made **zero source requests and zero paid calls**;
historical global accounting totals in the readback are preserved prior spending.
Protected independent receipt:
`~/.local/state/jobtology-hop/posting-dates-independent-readback-eaf895786b044e8ba3e8b783444d8df8/receipt.json`.

The first Nara update completed at 10:15:03 UTC in about 8 minutes 20 seconds,
including 4 minutes 12 seconds of capture and about 3 minutes 46 seconds of
initial reading. A subsequent 10,318-posting verification took seven seconds
after automatic statistics analysis. These are observations of this production
run. The JobKorea workflow took **21 minutes 57 seconds** (1,317.491 seconds),
including about 11 minutes for its first bulk read; its 8,434-row verifier then
took **5.452 seconds**. Current indexed/hash plans are healthy, but the initial
cached plan was not captured and the cause of the slow first read is unresolved.
Larger-cardinality throughput remains unverified.

The resumed `backfill_posting_dates.py apply` used the reviewed fresh manifest
and automatically registered supplemental evidence before date backfill in the
same guarded operation. It preserved the successful deployment and required no
manual evidence-registration step. The prepared independent reader at
`~/.local/state/jobtology-hop/posting-dates-readback/prepared_readback.py`
completed after VERIFIED apply. Historical backfill and readback are complete;
the separately listed performance investigation remains later work.

The completed date-only implementation preserved batch nodes and historical
source records; it added no LLM work, complete revision flattening, delta
reconstruction or Q-Net integration. The separate batch-free graph migration is
now verified in the October 12 checkpoint below.
See the [graph contract](../../hop/graph/README.md#posting-ingestion-dates) and
[JobKorea evidence contract](../../hop/ingestions/jobkorea/README.md#later-collection-time-evidence-and-graph-date-metadata).

## October 12 batch-free graph implementation (production VERIFIED)

The repository now publishes stable business entities and grounded direct source
relationships through the native Hop source loader. Exact accepted-run membership,
record/document content hashes and completed projection state live in PostgreSQL
`ingestion.source_graph_projection`, `source_graph_record_evidence` and
`source_graph_membership`. Immutable evidence survives independent supported
source-run cleanup. Future graph checkpoints require a verified batch-free
projection; initial migration preserves the historical `ingestion.graph_export`
rows. Graph history is never replaced with `archivedRecord` nodes.

Inferred occupation publication verifies the exact historical JobKorea/NCS pins
and frozen source/catalogue/binding evidence in PostgreSQL, then checks stable
business node IDs, kinds and occupation codes in Neo4j. A newer accepted
observation may update the business node while the original inference retains its
pinned evidence. SQL 036 changes publication only: paid planning, provider routing,
frozen inputs, candidate IDs, payloads, review policy and accounting are unchanged.
The legacy Python graph publisher now fails before I/O and directs callers to the
native Hop source entrypoint. Strict explicit-duty and ontology graph consumers
were audited and have no dependency on the removed graph history layer.

Manual storage retention keeps its PostgreSQL archive, exact raw-file checks and
recovery checkpoints, using immutable source proofs instead of Neo4j archives or
graph deletion. Former standalone graph retention pipelines explicitly abort.
JobKorea raw-data/storage cleanup remains unsupported and separate. The focused
`ingestions/jobkorea/install_batchfree_graph_publication.hwf` waits for graph
contracts, then installs retention 002 and LLM 036; it does not replay older
model/accounting SQL.

Consumer verification passed **35 focused unit tests**, **24 isolated Cypher
checks** and a **40-check native inferred publication fixture**, plus the isolated
native retention suite. Tests cover historical pins after newer JobKorea/NCS node
updates, unchanged frozen payload hashes, exact endpoint failure, missing/tampered
PostgreSQL evidence, publication replay, lease cleanup, zero source-history graph
nodes and PostgreSQL proof survival after supported source cleanup. Native
inference receipt:
`~/.local/state/jobtology-hop/jobkorea-dry-run-cdd5182a8a06/receipt.json`;
retention logs: `/tmp/jobtology-retention-test-ys6v6zv_/`. Disposable resources
were removed; these fixtures made no production writes, source requests or paid
calls.

A protected full PostgreSQL backup was restored into an isolated network-disabled
container for representative performance testing: **84 checkpointed READY runs,
223,925 accepted records and 361,488 source references**. This is a representative
older snapshot, separate from the **86-run** locked production baseline below.
Backup restoration took 132.55 seconds. The first un-analyzed entity query was
canceled after 315.22 seconds. The new source projection now materializes source
assembly/reference inputs once, uses typed record joins and exact-run validation,
and disables JIT locally in its new projection/proof functions. Global PostgreSQL
planner settings are unchanged. A measured generic record-guard startup plan was
replaced with the equivalent aggregate mismatch check; genuine, forged and
nonexistent-run transition-table checks passed.

The representative proof is **PASSED** on graph SQL 002 SHA256
`bc048ef806db9f32f9ce235b6818a4e62c096d48f4a7936eda97a244921b32d3`.
One persistent database session captured and committed all **84 exact runs** in
**1,172.897 seconds**, then finished all 84 in **62.763 seconds**, with a
180-second bound on each statement. The slowest begin took **115.838 seconds**;
the slowest finish took **16.926 seconds**. All **84 projections are READY**, with
exactly **223,925 immutable record proofs** and **361,488 memberships**. All 84
historical `ingestion.graph_export` rows retain their exact original fingerprint.
Earlier bounded atomic attempts rolled back; a 600-second bulk bound is too short
for the measured cumulative strict capture at this cardinality. Protected final
receipts are `receipt-per-run.json` and atomic `validation-receipt.json` in
`~/.local/state/jobtology-hop/batchfree-performance-939d9bfe6383/`.

Per-source timings for that representative clone are recorded in
`source-timing-summary.json`; these are PostgreSQL proof operations only:

| Source | Runs | Accepted records | Begin total (s) | Finish total (s) | Maximum begin (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `alio_organization` | 2 | 710 | 0.65 | 0.09 | 0.43 |
| `job_alio` | 31 | 30,824 | 141.61 | 24.63 | 6.19 |
| `ncs_competency` | 5 | 77,600 | 471.90 | 9.57 | 96.49 |
| `ncs_qualification` | 6 | 837 | 1.18 | 0.25 | 0.22 |
| `qnet_schedule` | 31 | 2,574 | 4.07 | 0.89 | 0.15 |
| `ncs_career_path` | 2 | 25,728 | 138.04 | 2.80 | 72.59 |
| `nara_job` | 6 | 77,218 | 311.76 | 7.44 | 115.84 |
| `jobkorea` | 1 | 8,434 | 103.49 | 16.93 | 103.49 |

Bounded graph API measurements during finalization returned **52,280 entities in
175.31 seconds**, **29,990 direct edges in 35.10 seconds** and **39,056 owners in
39.06 seconds**. The subsequent equivalent entity precondition revision was
verified separately at **31.326 seconds**; the full entity API was not repeated
after that guard-only change. These timings establish this restored snapshot,
not larger advertised ingestion maxima. The earlier posting-date cold-read cause
and its separate performance TODO remain unresolved.

The locked pre-migration read-only production baseline contained
**86 graph batches**, **224,903 graph records** and **585,681 scaffold edges**,
alongside **240,196 business nodes** and **800,648 business relationships**.
Its protected full backup restore is verified. The guarded coordinator accepted
the exact representative proof before the live transition.

### Live checkpoint: VERIFIED

All **41 public runtime files** were deployed and verified. Protected deployment receipt:
`~/.local/state/jobtology-hop/jobkorea-runtime-applied-79166d223a5845bfb0e1535f47bfe979/receipt.json`.
The focused graph 002, retention 002 and LLM 036 SQL contracts are installed;
all **145 existing protected tables** retained their exact original fingerprints
after installation. The representative proof remains PASSED on `bc048e` above.

Native `graph/migrate_source_graph.hwf` succeeded at **2026-10-11 17:43:43 UTC**
in **4,166.510 seconds**. Atomic proof capture took **3,394.886 seconds**;
final proof verification took **59.114 seconds**. All **86 projections are READY**,
with **224,903 record proofs** and **363,444 memberships**. Native checks verified
**52,285 projected entities**, **29,995 direct source relationships** and
**39,061 relationship owners**. The live atomic/per-run timing difference has no
established cause and remains separate performance work.

Apply and coordinator receipts are **VERIFIED**, finished at
**2026-10-11 17:56:42.230661 UTC** and **17:56:42.241425 UTC**, respectively:
`~/.local/state/jobtology-hop/batchfree-locked-execution-a2c7aafbec514990a62b1ba472a22021/receipt.json`;
the apply receipt is `apply/receipt.json` in that directory. Removal completed in
**1,125 transactions**: **86 batch nodes, 224,903 record nodes and 585,681 scaffold
relationships**. All **240,196 existing business nodes** and **800,648 existing
business relationships** were preserved. The final graph has **240,288 nodes**
and **830,643 relationships**, including **92 real Q-Net exam sessions** and
**29,995 direct source relationships**. Normal exact-run Q-Net replay passed in
**213.960 seconds**. The scheduler resumed, the pending fence was removed, and
the task made **zero source requests and zero paid calls**.

Independent graph readback is **VERIFIED at 17:57:16.692019 UTC**:
`~/.local/state/jobtology-hop/batchfree-independent-report-734e9925ed1648c6bd29a3bfda89d2f5/after.json`.
All **22,295 source postings** (1,369 JOB-ALIO, 12,492 Nara, 8,434 JobKorea) retain
all eight date properties, types and absence hashes. All **5,878 JobKorea inferred
NCS edges** retain exact typed hashes, IDs and properties: **21 ASSISTANT_REVIEWED**,
**5,857 UNREVIEWED**, confidence **NULL/UNASSESSED**, lifecycle **STAGING**.
The independent comparison preserves all 240,196 old business IDs/dates and finds
zero scaffold nodes. Its PostgreSQL preservation evidence is bound to the
VERIFIED operator gate for 145 protected fingerprints, rather than a new
independent PostgreSQL rehash.

The retained **724,005,013-byte** full backup has SHA256
`781717550401224105d294fb25e9a0270fdc072ccb9e1c84b52e0d6e359a7591`;
restore verification passed **145 tables, 407 functions and 307 triggers**, with
restore-resource cleanup verified. Earlier 85-run production preflight/plan
receipts are superseded by this verified 86-run execution. The private
`atomic-capture-performance-note.json` retains phase timings and heap/statistics
observations. The disposable performance container and its exclusive volume were
removed; protected proofs remain, with VERIFIED `cleanup-receipt.json` in the
representative benchmark directory.

## Pending work in priority order

Ontology revision flattening is VERIFIED; the
[revision migration record](revision-flattening-plan.md) retains its proof and
recovery contract. DB loading/validation performance remains measured follow-up
work. The later O*NET posting-link authorization above now opens the separate
matcher task under its own $40 combined cap. The catalogue-only milestone is
complete and made no paid posting call.
Build subsequent performance plans from a
full measured routine-ingestion/replay versus one-off-migration breakdown.
Source/canonical identity unification and O*NET posting matching remain separate.
The authorized reference catalogue milestone uses a distinct O*NET scheme and
does not implement a posting matcher or the full rated database. Existing
Korean Q-Net support remains intact. The default `MAX_MATCHES=1` policy is
unchanged; explicit opt-in v3 multi-occupation support is deployed and proved.
The authorized small real v3 pilot and four individual candidate decisions are
complete with separate quality/accounting evidence; legacy results remain exact.

1. Continue full routine DB loading/verification benchmarks. Typed properties
   grouped by owner and 500-row source entity write/verification batching are now
   **deployed and VERIFIED**; see the
   [performance checkpoint](#routine-performance-checkpoint-october-12).
   Source history selection and scoped independent validation SQL003 are deployed
   and verified; matched warm source-graph replay averaged 465.348s baseline versus
   207.600s candidate. Further SQL004/date500 isolated replay measured 207.489s baseline versus
   157.364s candidate in one matched warm AB pair, with bounded correctness and
   preservation proofs complete; guarded follow-up rollout and readback are verified. No
   cross-workflow cache was introduced. Preserve typed/NULL
   values, array order, stale-field removal, current source evidence and target
   verification. Candidate-only full fresh import (609.928s) and READY replay
   (210.272s) are measured; no paired full-ingestion speedup is established.
   The historical normal flat replay took
   **663.654 seconds**, with eight property write/verify passes taking
   **526.385 seconds (79.3%)** over **3,666,327 property/array-element rows each
   way**. Keep source-selection and proof-validation benchmarks independent of
   one-off migration timings and preserve historical name selection.
   October 12 native projection of 52,285 entities took 272.004 seconds and its
   verifier took 194.331 seconds. The earlier 488.008/464.905-second name-query
   measurements remain historical evidence; larger advertised ingestion maxima
   remain unverified. Preserve private archives and isolated receipts.
   The earlier October 14 native Nara warm replay passed in 103.537s. Its later
   exact SQL/JDBC/Neo4j decomposition is recorded in the
   [JOB-ALIO and graph report](2026-10-14-jobalio-graph-performance.md).
   Nara entity and empty-edge readers still build references across eight READY
   historical runs; 103,037 records narrow to 10,555 entities, and the final
   entity fact join rejects 5,963,010 pairs. Narrow historical reference/candidate
   worksets and scalar-key joins next while preserving latest/fallback/name
   priority and every proof/guard. SQL003 remains frozen. The measured 500-row
   owner transport has one clean timing, completed independent native acceptance
   and cleanup, and is deployed/read back; no paired full-ingestion gain is
   established.
2. The realistic four-scope archived date first-read/statistics/plan-cache tests
   and measured SQL004/date500 replay proofs are complete; see the
   [October 13 routine report](2026-10-13-routine-performance.md). Fresh-backend
   date SQL counts finished below one second and did not reproduce the old
   minutes-long delay; no host-cold or statistics/plan-cache cause is established.
   Later bounded diagnostics should separate exact PostgreSQL nested queries,
   Hop transport and Neo4j backpressure, preserving typed/NULL semantics and
   inference evidence. Earlier Nara 13,234-record validation attempts reached
   their bounds; the October 14 SQL005 qualification and complete native replay
   supersede that unresolved-validator TODO. The bounded host coordinator is
   operational, with a passed live two-worker proof. The later isolated SQL006
   qualification fixes JOB-ALIO's independent-validation straggler: balanced
   complete assertions average 0.871s versus 24.686s, with exact semantics and
   manifests. Production rollout/readback is VERIFIED. Remaining measured graph
   reader selection costs are separate from this resolved validator work.
   Do not repeat expensive whole-history work or raise limits without new
   diagnostic evidence.
3. Investigate atomic source-proof capture performance separately: live 86-run
   capture took 3,394.886 seconds versus 1,172.897 seconds for the older 84-run
   per-run benchmark. Transaction shape, statistics and plan-cache differences
   are hypotheses, not established causes. Use retained observations and isolated
   archived data; preserve every proof/validation check and function-local
   settings. Matched two-run first capture already measured atomic 86.220s versus
   per-run 85.934s with exact evidence and statistics, establishing no material
   transaction-shape gain. The earlier October 13 four-scope atomic first capture
   reached the Nara 180s bound and rolled back. The earlier October 14 attempt,
   after qualified SQL005, passed ALIO but timed out at JOBALIO's unchanged 60s bound
   inside membership insertion's repeated validation guard; Nara was not reached.
   Exact selected-ingestion/enrichment fingerprints were restored by rollback,
   and the immutable FAILED receipt is retained. Later SQL006 qualification
   completes JOB-ALIO begin/finish in 4.451/0.845s inside an independently rolled
   back transaction, with READY original/new/live manifests and exact rollback.
   The wider atomic/per-run receipts remain FAILED: JobKorea membership's
   materialized live-reference comparison and Nara record-evidence's live-record
   comparison each reach the unchanged 60s bound. Optimize those generic
   transition-table evidence joins separately, preserving all guard calls.
   No four-scope durable success is established. Do not extrapolate these bounded
   comparisons to the older 86-run case. The earlier posting-date first-read
   cause remains unresolved.
4. Benchmark guarded ontology revision deletion separately: 39,336 exact
   commands took 1,339.238 seconds. Use isolated archived data and preserve all
   attachment/type checks, token/fence gates, recovery and exact preservation;
   this is not permission for unguarded deletion. The endpoint lookup correction
   is deployed, with controlled-profile and warmed-retry evidence retained above.
5. Implement and test targeted retrieval changes from the read-only coverage
   audit, after handling NCS snapshot rollover and cumulative accounting across
   pins. The October13 real v3 pilot and four individual candidate decisions are
   complete; [its report](2026-10-13-multimatch-pilot.md) records the 15-attempt
   scope, 11 rejected outputs and current cumulative accounting. No new inferred
   graph publication occurred. Further prompt/selection changes and another
   bounded assessment remain pending coordinator review within the remaining
   combined cap. Review broader inferred occupation
   quality as later work. Targeted re-evaluation and selected individual reviews
   are complete. Publication and independent readback are complete for 5,878
   edges: 21 remain `ASSISTANT_REVIEWED` and 5,857 remain `UNREVIEWED`. SQL 034's
   terminal `ABSTAINED` status fix is deployed. Its October 8 actual-catalogue
   fixture offered IT프로젝트관리 to 29 of 61 PM abstentions, including 14 of 19
   then-classified clear cases, leaving five. October 11 source review narrowed
   these to four plausible IT-PM shortlist gaps and one system-maintenance
   ambiguity (`49936406`) that needs disambiguation. Preserve candidate
   plausibility and actual review status rather than forcing matches. SQL 035 now correctly labels
   all 18 terminal invalid citation outputs `VALIDATION_FAILED`; this status
   follow-up is complete. All 2,527 completed abstentions
   now show `ABSTAINED`, with zero abstentions mislabeled `REVIEW_PENDING`. See the
   [dated correction checkpoint](2026-10-08-inferred-linking-report.md#pm-retrieval-correction-and-targeted-evaluation).
   All 8,434 inputs remain terminal under the original $5 cumulative cap. Preserve
   exact source/NCS pins, source graph prerequisites and the strict explicit-duty
   path. A duty-rich benchmark awaits locally supplied descriptions; no URL
   recovery or key/account/provider-routing changes are authorized. Embeddings,
   CS screening and catalogue/serving extensions remain later scope. Manual
   JobKorea raw-data/storage retention still needs its own adapter; that separate
   TODO is not a prerequisite for the batch-free graph architecture. No automatic
   fetch, closure reconciliation or deletion was added by the date work.
6. Implement cohort and editorial modules in their later agreed scope.

## Validation checkpoint

The initial assessment reported 175 unit tests, 5 parser tests, three isolated PostgreSQL catalogue integration suites, Ruff, Pyright and 384 parsable Hop XML files. JOB and the September Nara graph totals passed verification.

The repair adds 13 focused tests: eight offline scheduler regressions and five reconciliation tests, all passing. Shell syntax, Ruff, targeted Pyright, generator reproducibility and XML checks passed. Disposable network-disabled native Hop fixtures verified the exact Nara run handoff and fetch/graph failure paths; the isolated full ontology installer passed fresh install and replay. Live verification passed runtime hashes, preserved catalogue/reader invariants, Nara GRAPH recovery, the fresh FULL snapshot and exact-run graph checkpoint, independent Neo4j counts, and a final scheduler tick with no due work.

For the local JobKorea implementation, 180 repository unit tests and eight
offline scheduler tests passed. The focused source-graph and common-posting
PostgreSQL fixtures passed using local PostgreSQL 18 containers with networking
disabled. Ruff passed for the new JobKorea module, all 388 Hop XML files parsed,
both new run configurations parsed, and diff checks passed. Generated migration 005
byte-matches the canonical shared checks. The isolated native fixture and its
independent Neo4j verification passed as recorded above; no JobKorea production
rollout occurred in that October 7 implementation phase.

The semantic-preparation checkpoint passed 180 repository unit tests, Ruff,
targeted Pyright, diff checks and all 394 Hop XML parses. Focused source-input,
planner/publication/CS hash, BYOK accounting and cost-estimation checks passed.
The offline native fixture and authorized seven-call paid pilot passed as
recorded above. The canonical LLM installer now includes 027–028; its dedicated
native replay passed 36 assertions in
`~/.local/state/jobtology-hop/jobkorea-dry-run-a5944efbd9da/receipt.json`.
Standard `llm/install.hwf` replay preserves the bundle dispatcher, admitted input
fields, current reviewed view and CS content hash, followed by successful Neo4j
publication/replay and no-op checks; cleanup passed. Historical source-only
388-XML verification above remains unchanged.

The NDJSON checkpoint passed the final 126-check native suite, focused PostgreSQL
batch/checkpoint/immutability and indexed-input lookup checks, Ruff, Python
compilation, diff checks and all 394 Hop XML parses. Its receipt hashes match the
current native reader and migration 006. The 416-row source graph, original
887-row array regression, archive-only JVM-interruption recovery and bounded
100,730,368-byte import-only stress proof are recorded above; no production
installation or source/model request occurred in this phase.

The October 8 checkpoint passed 189 repository unit tests, targeted Ruff and all
394 Hop XML parses. Both 19-check full-dataset import-only preflights passed with
cleanup verified: `jobkorea-dry-run-9414743ad15a` and the final current-code
`jobkorea-dry-run-33a1897217ea` under `~/.local/state/jobtology-hop/`.
It also passed the focused isolated PostgreSQL input/provenance
suite, including direct-write rejection, archive metadata failures before DB
access, complete input coverage, committed-batch acknowledgement-loss resume and
legacy bundle replay. Ruff, targeted Pyright, Python compilation, Hop XML parses
and diff checks passed. The final 19-check native full-dataset preflight and the
complete production/source-graph/frozen-input/preservation checks passed as
recorded in the October 8 section. Production added no source or model request,
LLM parse, reservation, review decision, semantic link, or key/account change.

Continue with [the server runbook](server-runbook.md) for operational commands and [the prefetched dataset contract](prefetched-postings.md) for importer constraints.
