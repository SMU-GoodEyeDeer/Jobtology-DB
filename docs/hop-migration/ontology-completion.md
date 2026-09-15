# Hop ontology completion work

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](linked-ingestion.md) for what is actually tested/deployed.

Started 2026-09-12. **In progress; not a serving-ontology completion report.**

**User stop, 2026-09-13 KST:** work is wrapped up for now. Do not start further
implementation, deployment or processing until the user explicitly resumes.
The attachment hold remains separate and also requires explicit resumption.
See the [current handoff](#wrap-up-handoff--2026-09-13-kst) for the last verified
deployment, local test results and remaining work. An automatic continuation of
the overall goal does not override this stop instruction.

Latest independent stage: [typed requirement normalization](#typed-requirement-postgresql-stage--2026-09-13-kst)
is deployed and tested in native Hop. It does not complete production extraction,
graph/export semantics, calibrated confidence, cohorts or serving activation.
The subsequent [typed graph and v3 implementation](#typed-requirement-graph-and-interchange-v3--2026-09-13-kst)
has passed native tests and [is now deployed](#typed-graphexport-v3-live-deployment--2026-09-13-kst).
The [editorial product-occupation source](#editorial-product-occupation-source--2026-09-13-kst)
now has locally tested native import, review and PostgreSQL release pinning.
Its [graph adapter and JSON-LD v4 export](#editorial-graph-and-interchange-v4--2026-09-13-kst)
have now passed local native tests. Real catalogue review and deployment remain
pending.

The subsequent [v2 database read stage](#editorial-provenance-in-v2-database-reads--2026-09-13-kst)
has also passed local native tests, including pinned editorial evidence, scheme
filtering, both catalogue versions and drafts without an editorial pin. It is not
deployed.

The [primary product-occupation review stage](#primary-product-occupation-review-stage--2026-09-13-kst)
has now passed local native PostgreSQL/Hop tests. It is not deployed, and graph/
interchange integration is covered by the subsequent
[occupation graph and v5 stage](#primary-product-occupation-graph-and-json-ld-v5--2026-09-13-kst),
which also passed local native tests. Neither stage has been deployed.

The subsequent [derived-claim database readers](#derived-claim-database-reads--2026-09-13-kst)
passed local native tests for combined occupation/requirement reads and exact
evidence. These are also awaiting deployment.

The [reviewed duplicate-group prerequisite](#reviewed-duplicate-groups-for-cohorts--2026-09-13-kst)
now has locally tested native import, review, release freezing and read workflows.
It does not complete cohort eligibility, representative selection or statistics.

The subsequent [country/experience and position-scope stage](#reviewed-countryexperience-and-position-scope--2026-09-13-kst)
has now passed native PostgreSQL/Hop tests, along with the expanded installer's
duplicate-group regression. It is local only; actual cohort construction,
production assessments and deployment remain pending.

**User pause, 2026-09-13 KST:** attachment fetching/parsing, input reconstruction
and attachment-aware LLM extraction/linking are on hold until explicit user
resumption. The latest no-spend preview was stopped; no new paid pilot was
launched. See the [pause status and restart handoff](attachment-status.md).
This supersedes earlier attachment-run plans below. Unrelated ontology work may
continue; the hold does not establish full ontology completeness.

The requested outcome is a database usable as the planned ontology, including full
transformation and evidence-backed linking of the current job corpus when the remaining
OpenRouter credit permits it. A successful ingestion run or LLM batch alone does not prove
this outcome. This work retains the six-source scope, public-sector coverage, native Hop
runtime, PostgreSQL authority, rebuildable Neo4j projection, and deferred application/backend
ownership established in the migration discussions.

The ontology/grounding requirements come from [the design](../implementation-plan.md#9-ontology-and-graph-schema)
and [canonical contracts](../canonical-schemas.md). The Hop migration changes their execution
technology and database placement; it does not turn source identity references into accepted
canonical mappings or remove evidence, review, temporal, and release requirements. App profile,
chat, roadmap solver and private Person data are separate backend work; their public projection
contract must remain compatible and corpus loaders must leave private nodes untouched.

## Baseline verified from the live database

- Current JOB-ALIO snapshot: `7c34eb6b-0e8f-4deb-a93b-9d336762f8be`, READY, **513 postings**.
  The previous 506-posting run remains the frozen comparison source.
- Current NCS snapshot: `a32170ed-7485-4e31-82d3-ed48b3398946`, READY.
- All six source families have a READY snapshot. Refresh is installed separately from LLM work.
- No RUNNING enrichment batch and no RESERVED request at the baseline check.
- OpenRouter credit check returned HTTP 200: funded $8, reported usage $0.35543184,
  **remaining $7.64456816**. This is a point-in-time balance, not an ongoing guarantee.
- Raw detail responses contain `files` with attachment IDs, names, types and official download
  URLs. The normalized job/LLM input currently omits their contents.
- The prior [22-case comparison](llm-model-comparison-2026-09-12.md) supports Luna for reviewed
  extraction. It does not establish acceptable automatic NCS-link precision.

The earlier Luna inline run averaged approximately $0.0027 per posting, suggesting about $1.40
for 513 similar postings. This estimate excludes attachment text, repair/review calls, larger
postings and generation variation. Full processing must use bounded batches, measured actual
usage and a remaining-credit check before expansion. The first paid regression and full-run launch are recorded below.

## Completion requirements and verification

| Requirement | Evidence required before marking complete | Current state |
|---|---|---|
| All current jobs accounted for | Exact current-source key/hash comparison; every posting has a recorded transformation outcome; no silent LIMIT omissions | All 513 pinned hashes match; full inline pass finished PARTIAL; repair and attachment outcomes pending |
| Faithful Korean extraction | Original responses retained; exact evidence locators; education, polarity, position scope, AND/OR and exceptions preserved; regression and independent semantic review | Explicit rule effects and cited-range validation deployed; full-corpus repair/review and typed condition resolution remain pending |
| Independent decisions and corrections | Append-only extraction revisions, per-link decisions, reviewer/policy provenance; good extraction survives rejected categorization; revocation tested | Independent review/correction and revision-only categorization deployed and tested; production acceptance review pending |
| Attachment-aware input | Reviewed source scope; native fetching/parsing with hashes, source/document/page or section provenance; unsupported/scanned/unavailable outcomes explicit; no invented text | **Deferred by user; explicit resumption required.** Native bytes/parser, full v2 inputs and canonical document-evidence binding are preserved; production extraction/review and remaining formats/roles are unfinished |
| Full transformation/linking | Bounded production ENRICH batches covering all current hashes; measured costs; justified link/no-match/missing-evidence/review outcomes; no fabricated mandatory match quota | Pending; attachment-aware runs, acceptance and publication are on hold |
| Canonical reference backbone | Stable schemes, occupations, versioned NCS units, qualification/exam/career relations; explicit unversioned ambiguity; verified source support | Native source assembly deployed; full saved-source identity/relation/field readback passed; publication pending |
| Grounded ontology claims | Queryable positions, duties, requirements, expression structure, evidence, mappings and review provenance; target-type and referential checks | Native reviewed claims and separately reviewed guarded rules deployed and graph-tested; production review, typed target/predicate resolution and publication pending |
| Reproducible release | Immutable manifest and pinned six-source/claim/revision memberships; consistent data-as-of; verify graph before PostgreSQL activation; rollback/revocation tests | Manifest sealing and native graph verification implemented/tested; activation/rollback/revocation pending |
| Interchange and query contracts | Versioned vocabulary, Schema.org/Jobtology JSON-LD context, SHACL validation, release-scoped query examples and coverage/demand denominators | Versioned release reads, JSON-LD v1/v2, observation bindings and RDF/SHACL checks deployed; full publication integration, cohorts and coverage/demand still pending |
| Refresh and retention compatibility | Changed-content processing, correct current/stale selection, protected release/evidence dependencies, rebuild and repeated-publication tests | Complete JOB censuses, canonical historical membership, source health and retention protection deployed; cohort/publication refresh integration and history compaction pending |
| Final independent audit | All required counts, fields, memberships and evidence compared across PostgreSQL/Neo4j; no duplicates on replay; cost reconciled; limitations recorded | Pending |

Source completeness and semantic completeness are separate. A posting with unavailable duties
must still exist with that outcome; a title alone must not create an NCS alignment. Mixed
education metadata must not make all positions unrestricted. Unversioned career CSV references
must not be silently merged into one arbitrarily selected versioned NCS competency.

## ko-v4 source interpretation

The new version preserves prior immutable prompts and outputs. It retains the ko-v3 raw JSON
shape and adds deterministic interpretation before validation/hydration:

- The dedicated education field uses the observed controlled values: 학력무관, 중졸이하,
  고졸, 대졸(2~3년), 대졸(4년), 석사 and 박사. Unknown values fail explicitly.
- Restricted degree lists are retained as alternatives at `posting_metadata` scope. A mixture
  of 학력무관 and restricted degrees has `applicability=unresolved_positions` and unspecified
  logic; it cannot establish applicant eligibility for any particular position. Narrative
  education conditions remain separate and are not overwritten by metadata.
- A whitespace-separated phrase can be divided into source-proven fragments without changing
  its words or order. Invented words are not repaired. This proves textual support only;
  fragment composition still needs semantic review.
- Explicit exception markers without a conditional tree, combined names using 및, bare titles
  treated as duties, and recruitment procedures treated as duties trigger review errors.
  These are targeted guards, not a complete Korean semantics parser.
- `raw_output` preserves the provider object; hydrated output records normalization policy,
  raw/normalized hashes and whether deterministic changes occurred.
- ko-v4 requires `ACCEPTANCE_POLICY=REVIEW`. Validation alone cannot automatically publish it.
  The default prompt remains ko-v3 until the new run is verified and the operational guide is
  updated deliberately.

The NCS prompt additionally requires occupational-domain agreement and avoids converting general
advice into unmentioned specialized procedures. Prompt wording alone does not establish link
quality; independent link decisions and evaluation remain required.

## Budget accounting change

Completed requests with a nonnegative provider-reported cost settle at that amount. Unfinished
or unknown-charge requests retain the conservative reservation. The request ledger and original
reserved amounts are preserved. Both batch and rolling-day gates use the same accounting rule;
future requests still reserve before sending. The historical comparison reports retain the
then-current accounting figures and must not be read as current balance checks.

## Attachment implementation notes

Hop has a native [Apache Tika transform](https://hop.apache.org/manual/latest/pipeline/transforms/apache-tika.html)
for text and metadata extraction. Actual PDF/HWP/HWPX handling, page preservation, size limits,
scanned-document detection and error handling must be verified against the installed Hop plugin
and representative files before a production attachment pass.

The checked-in source registry currently scopes JOB-ALIO to API bodies and attachment metadata.
Attachment processing therefore needs a documented scope/rights review and versioned registry
update, not merely following every URL. Retain this as implementation work while inline-source
transformation proceeds; do not silently mark attachment-dependent jobs fully extracted.

Runtime access and deployment procedures are in [the server runbook](server-runbook.md).

## Completed implementation and live regression — 2026-09-12

ko-v4 and settled-cost accounting were deployed with verified public-file hashes and the native
installer. Backup: `~/.local/state/jobtology-hop/v4-deploy-20260912T090455Z/`.
The independent review/correction workflows and SQL were then deployed and installed from
`~/.local/state/jobtology-hop/review-deploy-20260912T091211Z/`. No container restart was needed.
Private connection metadata and the protected API-key CSV were not changed.

The native integration suite passed against disposable Hop 2.19.0, PostgreSQL 17 and Neo4j 5.26.
It exercised legacy v1/v2/v3 behavior, v4 source interpretation, budgets, provider errors, evidence,
EVAL isolation and graph publication/revocation. Focused checks after the final installer update
verified known/unknown/in-flight charges and shared rolling limits. Independent review checks
verified capture replay, per-link rejection without losing extraction, append-only corrections,
revocation, EVAL exclusion, unchanged original attempts and NCS freshness independent of extraction.
Local logs: `/tmp/jobtology-llm-tests-mu2b4yli`, `/tmp/jobtology-llm-tests-7ldvelti`, and
`/tmp/jobtology-llm-tests-o1xa_1ev`.

Paid regression batch: **`86236633-fef2-4fb3-828e-4366eadec4be`**, EVAL/REVIEW, immutable
`korean-regression-v2-22` source/assertion set, Luna/OpenAI, reasoning none, prompt ko-v4.
Native exit 0; batch PARTIAL because two extractions were rejected.

| Measure | Result |
|---|---:|
| Postings passing structural/source checks | 20 / 22 |
| Supported provisional requirement references recovered | 30 / 32 |
| Provisional duty references recovered | 4 / 4 |
| No-duty cases with validated abstention | 18 / 20 |
| Paid requests | 24: 22 extraction + 2 categorization |
| Prompt / completion tokens | 96,590 / 36,810 |
| Reported cost | $0.06070865 |
| Unknown-cost requests | 0 |

The reference metrics include deterministic education handling. This is an assistant-authored
regression set used during development, not independent human gold or held-out precision.
The two rejections were posting 304741 (AND/OR guard; its contextual alternatives and shared
conditions need review) and 304739 (position name not a contiguous source excerpt).
The combined roles in 304450 are now separated, and the tested degree metadata is no longer
misclassified as unrestricted. The new prompt retained conditional structures in the previously
flattened examples, but structural validity does not establish all of their logical semantics.

The two categorization calls proposed three links: the two funeral-service units for posting
304435 and `0202020209_23v3` (노사갈등 해결) for the explicitly stated labour representation duty
in posting 304602. The earlier real-estate-domain mismatch did not recur. These are candidates,
not human-approved links, and this small set establishes no general NCS precision score.

Live log: `~/.local/state/jobtology-hop/v4-luna-22-20260912T090530Z.log`.

## Full current-source pass — completed inline attempt, repair pending

Native `enrich.hwf` was launched for all **513** postings of the pinned current JOB-ALIO snapshot,
using Luna/OpenAI and ko-v4. Settings: REVIEW, cache reuse on, 1-second request spacing,
60,000-character complete-input limit, 16,000 output tokens, 1,026 maximum logical requests,
$0.05 per-request reservation, **$2 batch cap** and **$5 shared rolling-day cap**. Oversized,
invalid, provider-failed and budget-blocked items remain explicit outcomes and must be addressed
before claiming the full transformation is complete. No input is silently truncated.

The host supervisor is running under:
`~/.local/state/jobtology-hop/ontology-full-20260912T091237Z/`.
The PostgreSQL batch is **`5f5a5c79-8026-41ae-b08a-09bdc4b3f848`**. A read-back check
confirmed 513 items and 513 matching pinned source hashes. At the first progress check it had
made five requests, with $0.00855605 reported for completed responses; the current request was
still reserved. These are progress figures, not final totals. Credit immediately before launch
was **$7.58385951**.

Its `config.json`, `status.json`, `hop.log`, and `supervisor.log` provide exact parameters, process
state and execution evidence. The supervisor PID at launch was 2822127, with Linux process start
ticks `245531755`; verify both to avoid mistaking a reused PID for this job. It makes no ETL
transformations itself; it supervises the native Hop workflow and checks credit before launch.

This is the full **inline-source** pass. Attachment evidence, independent production reviews,
ontology assembly/publication, release queries and the final completeness audit remain required.
Do not restart solely because a polling command times out: inspect the recorded process handles
and authoritative PostgreSQL batch state first.

At the post-deployment progress check, the same supervisor PID/start identity and native
child were live. The full batch had 254 requests: 168 extraction attempts VALIDATED,
85 REJECTED, one RESERVED and 259 PLANNED, with **$0.58212675** reported cost. All 513
pinned source hashes still matched. These are intermediate figures; the batch is not complete.

## Source and reviewed-claim assembly — 2026-09-12

The new [native ontology workflows](../../hop/ontology/README.md) are installed in
`${PROJECT_HOME}/ontology`, using `ontology-local`. Eighteen public files were deployed with
old/new hashes and backups under
`~/.local/state/jobtology-hop/assembly-deploy-20260912T095013Z/`.
The native SQL installer passed. It updated only the retention protection function and added
ontology objects; it did not reinstall the source/LLM write guards. Every public LLM runtime
file retained its pre-deployment hash, and the existing paid batch continued. No private
connections, secrets, production acceptance decisions or active-release pointer were changed.

Implemented source assembly includes stable identities, immutable content revisions,
six-source memberships, original record lineage, qualified source relationships, observed NCS
classification editions, and separate unversioned competency families. A posting's employer
follows the merged list/detail value. Qualification curriculum associations remain distinct
from capability-attestation claims. Retention now recognizes ontology source pins before any
raw or graph deletion, including PREPARING releases.

Implemented reviewed assembly freezes extraction and per-link decisions for each release.
It accounts for every posting; validated, EVAL, failed, pending, rejected and accepted outcomes
remain distinct. Accepted extraction produces positions, duties, requirements, explicit position
scope, ordered condition expression nodes, source text artifacts and exact fragment evidence.
NCS mappings retain their target revision, inference provenance and independent decision.
Later review changes do not rewrite a frozen selection. New NCS snapshots exclude old links
in new releases without discarding unchanged extraction.

The source-text artifacts use NFC/LF normalization and zero-based, half-open Unicode code-point
offsets. Matching is restricted to cited passage ranges, retains actual whitespace in excerpts,
and preserves separately supported shared suffixes. This projects the reviewed source wording;
it does not yet resolve every requirement into skill/credential/occupation targets or executable
degree, experience-month and eligibility-code conditions.

Verification completed:

| Check | Evidence |
|---|---|
| Synthetic source identities and relationships | Six-source accounting; same-name organizations remain separate; merged employer; NCS versions/families and hierarchy; replay; immutable sources; retention pin protection. |
| Full saved-source readback | 29,908 records; **38,782 identities**, **67,659 relationships**, **121,563 original field values**; zero differences. Comparisons enumerated the original source fixture independently of SQL candidate functions. |
| Synthetic reviewed claims | Six posting outcomes; EVAL isolation; pending corrections suppress old acceptance; rejected links preserve extraction; nested AND/OR and exceptions; Korean/emoji/NFC/CRLF offsets; immutable decisions; exact pinned NCS behavior; tamper rejection. |
| Saved real-output projection | **128 validated outputs**, **1,850 claims**, **211 positions**, **949 condition nodes**, **2,873 evidence spans**. Zero output-field/expression or evidence-offset differences. All 513 source postings accounted for. |
| Native Hop | Installer, source assembly/replay/reselection rejection, independent claim assembly/replay, unprepared-release rejection, and replay of the full saved-real-output projection all passed. |

The 128-output test made **synthetic acceptance decisions only in the disposable local
`ontologyrealtest` database**. It is a projection/round-trip test, not semantic evaluation,
human gold, or production acceptance. No new inference calls were needed for these tests.
The saved fixture intentionally pins the Q-Net source exported earlier; it is not presented
as a newly fetched current snapshot.

Local reports are `/tmp/jobtology-ontology/source-readback-report.json` and
`/tmp/jobtology-ontology/real-claims-report.json`. Native logs are
`/tmp/jobtology-ontology-native-5d1ugeww/` and `/tmp/jobtology-ontology-native-f2uu3wc2/`.
The full suite of synthetic claim checks was rerun after adding the direct evidence-writer
PREPARING-state guard. The server's installer/postflight evidence is in the deployment folder.

### Live source release prepared and verified

Native `ontology/prepare_release.hwf` completed for **`ontology-20260912-initial`**.
It contains **29,908 source records**, **38,782 entity revisions** and **67,659 source
relationships**, with zero unaccounted source records. JOB-ALIO and NCS use the exact full
enrichment batch pins. The current Q-Net run is
`7f5c4b73-52a2-4c9e-a7d1-3f1e9e6e1887`; the other source IDs match the saved-source fixture.
Despite the newer Q-Net observation, per-source normalized input hashes, all per-kind
entity/revision membership hashes, and all per-predicate relationship hashes match the
independently verified local fixture with **zero differences**.

The release is **PREPARING**, with no manifest, graph verification, activation, review freeze
or production acceptance decisions. Its conservative `data_as_of` is
`2026-09-10T23:55:59.801184+09:00`, the oldest selected source watermark. All six source pins
are protected from retention; Q-Net and career paths explicitly report `ONTOLOGY_RELEASE`.
Existing upstream/LLM dependencies already protect the other pins.

Inspect it using `ontology/inspect_release.hpl` with
`RELEASE_ID=ontology-20260912-initial`. Do not freeze its reviews until the intended production
decisions are ready. Server execution/report files are `prepare-sources.log` and
`source-preparation-report.json` in the deployment folder. Local independent readback is
`/tmp/jobtology-ontology/live-source-audit.json`, with the native report saved as
`/tmp/jobtology-ontology/live-source-preparation.json`.

Next required implementation remains attachment input, full-batch repair and independent
production review, target/condition normalization, release-scoped Neo4j publication,
observation/serving states, manifest verification and activation/rollback/revocation,
interchange/SHACL and query/aggregate contracts, then the final live completeness audit.
An assembled PREPARING release does not satisfy those publication requirements.

### Full-run rejection triage started

A read-only sample of eight `EXCLUSION_AS_ELIGIBILITY` rejections showed both model errors
and an overbroad field-based guard. For example, posting 291587 calls a sentence ending
`응시할 수 없음` eligibility, which needs correction to exclusion. In postings 293321 and
293511, however, the `disqualification_text` field also contains positive eligibility rows
such as `병역의무를 기피한 사실이 없는 자` and `공고일 현재 응시 자격을 갖춘 자`.
Their field name alone does not make those clauses exclusions. These observations are
source/wording checks, not a legal interpretation of the cited statutes.

The guard must be corrected with versioned regression cases while retaining checks for
actual exclusions. Do not simply accept every rejected item or change the running batch's
pinned ko-v4 validation contract in place. The sample is saved at
`/tmp/jobtology-ontology/rejection-polarity-sample.json`; full repair and semantic review
remain outstanding. Multiple issue flags can belong to the same rejected posting.


## Native graph candidate loader — full fixture verified

The new `ontology/load_release.hwf` seals and loads an explicit release inventory
using native Table Input, Neo4j Cypher/UNWIND and SQL transforms. It checks typed
properties, exact labels, relationship endpoints and complete release memberships.
A verified candidate remains PREPARING; activation is gated while serving contracts
are still incomplete. No production review freeze or acceptance has been written.

The small native fixture passed load/replay, unchanged manifest and counts,
independently checked dates/booleans/empty values, exact versioned mapping targets,
preservation of unrelated staging/private nodes, rejection of a conflicting graph
property without overwriting it, failed-writer cleanup and successful recovery.
Evidence: `/tmp/jobtology-ontology-native-6xf6z4m1/` (156 nodes, 470 relationships).
The final native replay/recovery suite also passed with the streaming reader and
reload-checkpoint invalidation in `/tmp/jobtology-ontology-native-f28_0mue/`.
A new graph load clears the previous verification timestamp; a failed reload
cannot inherit an old success. Successful full re-verification restores it.

Property boundary regressions additionally check signed 64-bit integer limits,
float precision loss (including mixed integer/fraction arrays), empty strings and
arrays, source-text exclusion from numeric casts, escaped literal dot/tilde keys,
and rejection of heterogeneous or object arrays. These tests use only the
`ontologytest` disposable database.

The saved six-source/128-output projection sealed into **182,670 nodes** and
**785,235 relationships**, with 1,386,887 node scalar rows, 434,131 node array-member
rows, 114,000 relationship scalar rows and 799,210 relationship array-member rows.
This is synthetic local acceptance for projection testing, not semantic approval.
The complete native workflow then passed every property/label/endpoint/membership
check. Independent traversals matched 513 postings, 1,850 claims, 211 positions,
2,873 evidence spans, 15,520 versioned NCS-to-family relations, 87 qualified
curriculum associations, 56 typed exam-date projections and 56 escaped Q-Net
lineage keys. The unrelated private fixture node remained unchanged.

Full native evidence: `/tmp/jobtology-ontology-native-3caidgld/`, with a copy of its
readback report at `/tmp/jobtology-ontology/real-graph-report.json`. The workflow
completed in **19 minutes 50 seconds** with a 1 GiB Hop heap, 512 MiB Neo4j heap
and 256 MiB Neo4j page cache. Most time was relationship-array writing and readback.
This is a measured disposable-fixture run, not a production performance estimate.
The test left the corpus PREPARING with no active release or production acceptance.

The full fixture exposed buffering in native Database Join despite disabled query
cache. Graph inventory reads now use prepared Table Input queries that consume the
result incrementally. Neo4j receives bounded 500-row batches. The test harness also
uses bounded transactions when clearing its disposable fixture graph; production
loaders do not clear the graph.


### Repair input collected from the ongoing full pass

A repeatable-read export captured 149 rejected postings from the same full batch.
Distinct posting counts were 46 for `OR_FOR_AND_ONLY`, 42 for exclusion polarity,
24 for unsupported requirement fragments, 20 for unsupported expression fragments,
18 for flattened exceptions, 15 for unreachable tree nodes and 12 for invalid
children. Flags overlap; these are intermediate counts, not final batch totals.
The protected local inputs/report are `/tmp/jobtology-ontology/full-rejections.jsonl`
and `/tmp/jobtology-ontology/full-rejection-triage.json`.

Source review of four AND/OR examples identified two separate repair concerns:

- An occurrence of `및` inside a cited law title or one alternative does not by
  itself establish that the whole requirement must use AND. The current lexical
  guard lacks that scope distinction. Preference lists also need separate
  treatment from mandatory eligibility thresholds.
- In posting 304326, the extracted crime alternatives omitted the parent line's
  shared penalty threshold and elapsed-time condition. Loosening the AND/OR guard
  alone would still admit an incomplete exclusion. A repair must include parent
  list context in both the evidence IDs and the condition tree. This finding
  compares the supplied wording; it is not an interpretation of the underlying law.

Preserve the running ko-v4 contract. Add versioned regressions and repair only
selected affected items after the batch finishes; do not blanket-accept these
rejections or rerun all successful extractions under a new prompt unnecessarily.


### Graph loader deployed to Goldship

Twenty-one public files were deployed with before/after hashes and atomic file
replacement under the host refresh lock. Backup and native installer evidence:
`~/.local/state/jobtology-hop/graph-deploy-20260912T104446Z/`.
The native installer passed. Every LLM runtime file retained its previous hash;
the existing paid batch continued. Before/after comparisons confirmed unchanged
source memberships, release records, extraction/link decisions and review freezes.
No graph load was started on the server during installation.

The live `ontology-20260912-initial` release is still PREPARING with no manifest,
graph checkpoint, review freeze or active-release pointer. New graph tables are
empty and ready for reviewed assembly/loading. This installation does not complete
semantic review, attachments, canonical target/condition normalization, temporal
states, aggregate/query and interchange contracts, or activation/rollback/revocation.
The publication gate deliberately remains closed until those requirements exist.


At the post-graph-deployment live poll, the same paid batch and supervisor process
identity remained live: **463 requests**, **$1.20570250** reported cost, 288
extractions VALIDATED, 174 REJECTED, one RESERVED and 50 PLANNED. All 513 source
hashes still matched. These remain progress figures; no new repair/model batch
was launched during graph implementation.

## Full inline batch finalized and ko-v5 repair work — 2026-09-12

The original supervisor completed at **2026-09-12T10:58:49Z**, with native Hop exit 0.
PostgreSQL confirms batch `5f5a5c79-8026-41ae-b08a-09bdc4b3f848` is **PARTIAL**;
the recorded supervisor and child process handles are no longer live. Do not restart
this batch. A terminal read-only export contains every item and original extraction/
categorization attempt, with all **513** pinned source hashes still matching.

| Final inline result | Count/value |
|---|---:|
| Extraction VALIDATED / REJECTED | 322 / 191 |
| Categorization VALIDATED | 42 |
| Categorization SKIPPED: NO_EXPLICIT_DUTIES | 280 |
| Categorization matched / no-supported-match outputs | 25 / 17 |
| Proposed links, before independent review | 76 |
| Requests | 555 (513 extraction + 42 categorization) |
| Prompt / completion tokens | 2,337,119 / 840,634 |
| Reported and settled cost | $1.40102046 |
| Unknown-charge requests | 0 |

An authenticated post-run OpenRouter balance check returned HTTP 200: total funded
$8, total reported account usage $1.81716095, **remaining $6.18283905**. The key stayed
on Goldship. This balance supports a bounded repair pilot; it is not a prepaid estimate
for attachments or all future review passes.

### Audit and repair verification and deployment

The generator now builds `audit_batch.hwf`, `capture_audited.hwf`, audit previews and
explicit `POSTING_IDS`/`REPAIR_BATCH_ID` selection. All additive SQL installs in the
disposable database. Focused regressions pass for positive absence versus actual
exclusions, mixed polarity, quoted law titles, genuine AND-only conditions, parent
list context/thresholds, exact evidence and unchanged older validation behavior.
The complete native end-to-end suite then passed against disposable Hop 2.19,
PostgreSQL 17 and Neo4j 5.26. Logs: `/tmp/jobtology-llm-tests-8zmfrcni/`.
It covered legacy v1/v2/v3/v4 behavior, budgets, independent reviews and revocation,
native v5 two-stage execution, audit replay, no-call revalidation, source/hash tamper
rejection, preservation of existing revisions, exact selected repairs, oversized
requests without truncation, EVAL isolation and unchanged original attempts/costs.

Nineteen public runtime files matched the tested native fixture byte-for-byte, then
deployed with prior hashes/backups and atomic replacement under the refresh lock.
The live native installer passed. Backup/evidence:
`~/.local/state/jobtology-hop/v5-deploy-20260912T110430Z/`.
Postflight hashes confirmed unchanged old prompts, batches, items and attempts;
review decisions, review freezes and ontology release state also remained unchanged.
Private metadata/secrets were not replaced. The default prompt remains ko-v3.

The compatible ko-v5 audit records immutable new findings, without updating the old
attempt or cost. Clean saved v4 results can become separately versioned review
candidates without another extraction call. Failed repairs retain the old item,
attempt, issue list and output as lineage; explicit selections cannot silently skip
ineligible IDs. New model requests include original passages and the previous output
as untrusted diagnostics. Existing revisions and acceptance decisions are preserved.

A local audit of the complete saved batch, using the new conservative guards, found:

| Original extraction state | Clean new audit | New review/repair issues |
|---|---:|---:|
| VALIDATED | 251 | 71 |
| REJECTED | 21 | 170 |
| Total | **272** | **241** |

These counts measure validator outcomes, not semantic accuracy. Of particular concern,
some previously validated outputs omitted parent-list conditions or represented shared
conditions with an alternative-only tree. Issue flags overlap; some conservative scope
flags may be resolved by semantic review rather than a new model call. The original
191 rejections must not simply be accepted, and the 322 original passes must not be
blanket-approved either.

Local protected evidence: `/tmp/jobtology-ontology/full-completed-results.jsonl`,
`v5-full-local-audit.jsonl`, `v5-full-local-audit-summary.json` and `post-full-credit.json`.
The revalidation workflow does not retrospectively categorize old rejected extractions;
linking reviewed revisions whose duties changed or were newly recovered remains a
separate integration requirement.

### Live audit and review-candidate capture

Native `audit_batch.hwf` and `capture_audited.hwf` completed for the original full
batch. All **513** live audit outcomes matched the saved-source local verification
exactly, and **272** clean outputs became append-only review candidates. This includes
the 21 previously rejected outputs now passing the compatible new checks; their original
attempts remain REJECTED with original costs and prompt versions. Before/after checks
confirmed that no attempts, acceptance decisions, link decisions, review freezes or
active releases changed. Logs and reports:
`~/.local/state/jobtology-hop/v5-audit-20260912T110501Z/`.

A six-posting native repair pilot was subsequently launched with ko-v5/Luna/OpenAI,
REVIEW, the original JOB/NCS pins, 120,000 complete-input characters, 16,000 output
tokens, at most 12 logical requests and a **$0.25** batch cap. It selects
`291587|304326|295776|304739|293321|299584`, covering exclusion polarity, parent
conditions, previously validated flattened scope, topology/source fragments and
preference logic. The parent batch is the completed 513-posting run. No clean
audited item was selected for another extraction call.

Supervisor folder: `~/.local/state/jobtology-hop/ontology-v5-pilot-20260912T110548Z/`;
launch PID 3155371, Linux start ticks `246210871`. Inspect its actual handle and
PostgreSQL batch state before treating it as live or finished. A launch record alone
does not establish successful repair. The pilot requires source-level result review
before expanding to the remaining failures. No production acceptance, review freeze
or ontology activation has been written.

The pilot's committed PostgreSQL batch is **`622a4e22-a8fd-42e7-93ad-44b4a7e2c8cb`**.
Its first request-progress check found all six selected source hashes matching, five
requests, $0.00987718 reported cost, two extractions validated, two rejected, one
reserved and one planned. Both supervisor and native child handles were live.
These are intermediate figures and do not establish pilot completion or quality.

### Paid ko-v5 pilot finalized; semantic review found remaining failures

Batch `622a4e22-a8fd-42e7-93ad-44b4a7e2c8cb` finished PARTIAL at
**2026-09-12T11:08:16Z**, native exit 0, with both process handles terminated.
All six selected source hashes matched. Eight requests (six extraction; two
categorization) cost **$0.02064220**. Three extractions validated and three were
rejected. The two categorization responses proposed one link each; one other
validated extraction had no explicit duties and skipped categorization.

| Posting | Automated result | Source review finding |
|---|---|---|
| 291587 | VALIDATED | Exclusion polarity repaired, but preference items retain only headings and omit bonus amounts, minimum scores and exceptions. Not acceptable as a complete extraction. |
| 293321 | REJECTED | Independent bonus rules remain combined into an OR group. Positive-absence eligibility is now preserved. |
| 295776 | REJECTED | Invalid/reused child indices, unreachable nodes and flattened shared conditions remain. |
| 299584 | VALIDATED | Earlier unsupported fragments repaired; duties and alternative clinical-experience wording retained. Extraction remains pending fuller review. Proposed NCS target is in rescue/ambulance work and is unsupported by the broad physician-duty wording. |
| 304326 | VALIDATED | Shared text restored but attached to the wrong Boolean branch. An applicability restriction is also incorrectly represented as an exemption. Proposed NCS target is for cable-broadcast subscriber terminals, unsupported by the AMI/power-distribution context. |
| 304739 | REJECTED | Position naming repaired; an elapsed-time node remains unreachable. |

The 304326 tree is structurally connected yet semantically wrong: it makes offense A
mandatory alongside an OR of offenses B/C and the shared penalty/time condition.
The source requires the shared condition AND any one of A/B/C. Its separate color-
vision clause applies only to telecom/electrical roles; an `except` node reverses
that applicability. These are comparisons of the supplied source wording, not legal
advice or interpretation of an external statute.

This pilot does **not** justify expanding the same configuration to all 241 flagged
outputs. Further work must reduce numeric-tree assembly errors (a nested provider
output converted deterministically to the existing flat ontology representation is
one candidate), account for omitted qualifiers/source coverage, and perform independent
semantic/link review. Passing exact-fragment/topology checks is insufficient. Preserve
all ko-v4/v5 artifacts and findings rather than changing their pinned contracts in place.

Source/output/shortlist evidence: `/tmp/jobtology-ontology/pilot-results.jsonl`.
Native capture/import/review workflows recorded append-only **assistant** rejections
for 291587 and 304326 extraction and both proposed links. 299584 extraction remains
pending. Live readback confirmed exactly these two extraction and two link rejections,
unchanged provider attempts/costs, zero acceptance decisions, zero active releases and
no running LLM batch. Logs: `~/.local/state/jobtology-hop/v5-pilot-review-20260912T111037Z/`.
No acceptance or serving activation is justified by this pilot.
The original batch, free-audit candidates, attachment work,
reviewed-revision categorization and all remaining ontology contracts stay in scope.

## ko-v6 condition representation and source accounting — verification

The next contract returns nested condition trees and converts them deterministically
to the existing flat canonical representation. The converter preserved the expected
shared-penalty AND three-offense-alternatives condition for every truth-table input.
The schema validator handles this contract's local recursive references independently
of provider-side strict mode, rejects unsupported references, and bounds schema/tree
size. Existing raw formats and validators are unchanged.

The captured output also accounts for every narrative source passage as cited or
explicitly unhandled. Unaccounted text, unsupported duplicate/absence/heading claims,
certain omitted numeric qualifiers and scope-as-exemption mistakes receive explicit
issues. These are regression guards and a review ledger, not a general Korean semantic
proof. The new categorization request includes original source passages and position
names so a generic activity cannot be assessed without its occupational context.

[Official OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs#recursive-schemas-are-supported)
supports recursive schema definitions. Routing/model behavior is still subject to the
live pilot; passing a local fixture does not establish external-provider compatibility.

Focused native verification passed in `/tmp/jobtology-llm-tests-56343x5v/`: installer,
v5 behavior after installation, v6 extraction/categorization, source context, cache
reuse and EVAL isolation, native review capture, append-only nested corrections and
selection of independently rejected extractions while preserving pending corrections.
The canonical requirement objects matched the prior flat representation exactly for
the same source/condition. The earlier full v1-v5 integration suite remains recorded
above; it was not rerun in its entirety for this isolated contract addition.

Ten public ko-v6 runtime files matched the final native fixture byte-for-byte and
were deployed under the refresh lock. Backup and native installer evidence:
`~/.local/state/jobtology-hop/v6-deploy-20260912T112512Z/`.
The installer passed; old prompts, attempts/costs, batches, items, review decisions and
ontology release state stayed unchanged. No private metadata or secrets were replaced.
The default remains ko-v3; ko-v6 is selected explicitly for this pilot.

A five-posting ko-v6 repair pilot was launched against the completed v5 pilot:
`291587|304326|295776|304739|293321`. The independently rejected 291587/304326
extractions supply their review notes; the other three supply their validation errors.
299584's pending extraction revision is protected and was not re-extracted. Models are
Luna/OpenAI with reasoning none, REVIEW, original JOB/NCS pins, 120,000 input characters,
16,000 output tokens, at most 10 requests, $0.05 request reservations and a **$0.25**
batch cap. The fresh authenticated credit check reported **$6.16219685 remaining**.

Supervisor: `~/.local/state/jobtology-hop/ontology-v6-pilot-20260912T112638Z/`,
PID 3211366, start ticks `246335900`, native child 3211598. The first poll verified both
process handles live. A running process is not a completed batch or semantic-quality
result; inspect the recorded status and PostgreSQL state before any retry or expansion.

### ko-v6 pilot completed; validation passes rejected after source review

Batch `859ade42-976d-436e-94f0-a711ef877ce9` finished PARTIAL at
2026-09-12T11:29:40Z, native exit 0. All five source hashes matched. Five extraction
requests cost **$0.01989009**; two outputs validated and three were rejected. Both
validated outputs had no extracted duties and skipped categorization. Recursive
schema requests were accepted by the actual routed provider.

| Posting | Result and source-level finding |
|---|---|
| 291587 | VALIDATED, then independently REJECTED. Bonus amounts and qualifiers are now quoted, but `except` combines two disqualifying bonus conditions as if one were an exemption from the other. |
| 304739 | VALIDATED, then independently REJECTED. Permission for soon-to-be-discharged applicants is subtracted from positive eligibility; a conjunctive exclusion is represented as implication; the regional-talent heading and its education definition are split into separate preferences. |
| 295776 | REJECTED by the shared-condition guard. The relevant parent condition is now inside an `all_of` with the two alternatives, nested under the overall exclusions `any_of`. This indicates a conservative guard limitation; it does not certify the rest of the extraction. |
| 304326 | REJECTED by heading/disposition checks. The shared penalty/alternatives tree and telecom/electrical applicability are repaired. A cited position is also marked unhandled, and legitimate numbered section headings fail the whitelist. Position scope still needs review. |
| 293321 | REJECTED by passage-accounting checks, including a conflicting metadata disposition, heading whitelist failures, employment terms classified as `no_condition`, and an unsupported duplicate reference. These need source-accounting corrections and semantic review, not blanket rejection of every extracted fact. |

Native capture/review workflows recorded **assistant** rejection decisions for
291587 and 304739. Provider attempts, costs, previous reviews and source snapshots
were preserved. No ACCEPT decision or active ontology release was created.
Evidence: `~/.local/state/jobtology-hop/v6-pilot-review-20260912T113546Z/` on Goldship;
protected local export `/tmp/jobtology-ontology/v6-pilot-results.jsonl`.

A two-posting repair trial now uses the same ko-v6 contract and Luna/OpenAI with
`REASONING_EFFORT=low`, these explicit independent rejection notes, and a **$0.15**
batch cap. Credit immediately before launch was **$6.14230676**. Source pins and
input/output limits are unchanged. Supervisor folder:
`~/.local/state/jobtology-hop/ontology-v6-reasoning-20260912T113938Z/`, PID 3244766,
start ticks `246413841`, native child 3244927. This launch is not evidence of a
successful repair; inspect its authoritative result before expanding the run.

### Reasoning trial completed and condition-semantics clarification

Batch `a941689c-bdd6-47bb-ae3c-43a1f754dc1d` completed at
2026-09-12T11:41:58Z, native exit 0. Both selected source hashes matched. Two
extraction requests cost **$0.00894196**; both outputs validated, and both skipped
categorization because no explicit duties were extracted. The supervisor and
native child terminated. No broad repair run was launched on this result.

Reasoning repaired the 304739 sentencing/event/elapsed-time conjunction and joined
the regional-talent preference to its education definition. In 291587, the bonus
exclusions now qualify the bonus separately instead of treating one exclusion as
an exemption from the other. These are observed improvements in two selected
cases, not a corpus-level quality estimate.

Review also exposed an underspecified contract. The prompts define `except`
children as base/exemption but do not define an executable effect for positive
eligibility versus loss of a bonus. Earlier review wording that described the
military-service clause as necessarily subtracting eligible applicants assumed
one interpretation; there is no implemented evaluator proving that interpretation.
The underlying source permission must be retained and its direction made explicit
in the resolved condition representation. Do not silently assign new semantics to
old raw outputs or label this solely a model-intelligence failure.

The new reasoning outputs are retained for independent review: 291587 awaits
complete bonus-rule/condition review; 304739 remains on review hold for the
permission/exception contract. Neither is approved for serving.
Native capture and the explicit assistant review hold are recorded under
`~/.local/state/jobtology-hop/v6-reasoning-review-20260912T114511Z/`.

### Native categorization of accepted extraction revisions

`categorize_reviewed.hwf` now accepts exact accepted `REVISION_IDS`, a JOB snapshot,
an independently selected NCS snapshot, actor, model/provider options and budget
limits. It retrieves and categorizes the reviewed duties without another
extraction attempt. A pending/rejected/superseded revision or changed source fails
planning. Acceptance is checked before reservation and again after a response;
responses and charges remain recorded if acceptance changes while a call is in
flight. No candidate is automatically accepted.

`revision_input` pins revision, decision and extraction hash. `revision_link_result`
retains attempt/outcome lineage, including distinct no-duty/no-retrieval/no-match
outcomes. `link_support` appends new rationales without rewriting an earlier
candidate or clearing a rejection. Rejected suggestions are excluded from cache
reuse. Candidate uniqueness now includes the NCS snapshot; historical candidate
IDs and decisions were retained. Legacy whole-item review cannot accept these
link-only batches.

Focused native tests passed in `/tmp/jobtology-llm-tests-is811ugl/`, using the local
mock provider: corrected duties rather than old provider duties, dry execution
without a key, zero extraction requests, exact revision/source context, no-duty
outcomes, cache replay, rejected-cache bypass, unchanged decisions, new NCS pins,
budget denial, revocation before reservation and during a charged response,
append-only bindings/support and unchanged original attempts/reviews.

Supplementary native ko-v1/ko-v5 runs and cache replay passed. Their cache hashes
matched the previous algorithm exactly. Budget fixtures plus v5/v6 source/tree
checks passed after preparing the missing evaluation fixture; that initial test
setup error was not a runtime failure. The complete earlier v1-v5 suite was not
rerun in full for this change. Evidence:
`/tmp/jobtology-ontology/revision-links-test.log`, `revision-legacy-test.log`,
`revision-legacy-supplement.log`.

All **nine** deployed runtime files matched the native-tested fixture byte for
byte. Deployment used the refresh lock, verified previous file hashes, backups
and atomic replacement; the live native installer passed. Backup:
`~/.local/state/jobtology-hop/revision-links-deploy-20260912T114430Z/`.
Before/after checks confirmed unchanged original attempts/costs, batches, items,
prompts, review decisions and ontology release state. Private metadata/secrets
were preserved. Production categorization from accepted revisions remains to be
run after the extraction decisions are established; test acceptance was confined
to disposable fixtures.

A live native dry run with the pending 291587 revision failed as expected with
`REVISION_REQUIRES_ACCEPTANCE`, before reading the deliberately nonexistent key
file or making any request. Before/after batch, item, attempt, binding, result,
review and active-release state matched. Evidence:
`~/.local/state/jobtology-hop/revision-gate-20260912T114644Z/`.

Before expanding automatic extraction repairs, extend the older repair selector's
pending/accepted protection across batches: `repair_reasons_v6` currently checks
revisions belonging to the selected old item. A newer revision for the same
posting/content in a different repair batch must also prevent an older batch from
being re-extracted. The new revision-categorization path already checks the newest
content-matching revision across batches. No broad repair was launched while this
remaining selector gap exists.

### Cross-batch repair protection and explicit rule effects — 2026-09-12

Sixteen public files were deployed with backups and old/new hash checks under
`~/.local/state/jobtology-hop/rule-deploy-20260912T121841Z/`. Both native installers
(`llm-local` then `ontology-local`) exited 0. Existing provider attempts/costs,
items, batches, immutable prompts, extraction/link decisions and ontology release
state were unchanged. Private metadata and secrets were preserved.

Operational repair selection now protects the latest content-matching extraction
revision across batches. Pending or accepted revisions cannot be overwritten by
retrying an older item; the latest rejected revision can be repaired through its
own parent batch. A RESERVED request elsewhere also blocks a duplicate repair.
The reservation stage rechecks this protection if review arrives after planning.
Native tests verified no reservation/HTTP call for a newly protected request and
no batch/key access when the entire explicit source selection is excluded. The
initial native test expected the partial-selection error; the all-excluded case
correctly returns `NO_POSTINGS_FOR_LLM_BATCH`. The request pipeline's CSV input
opens on startup, so reservation protection promises no HTTP call, not no key-file
access after that pipeline has already started.

`guarded-rules-v1` adds separately reviewed interpretations with REQUIRE, PERMIT,
FORBID, PREFER, UNRESTRICT, LIMIT and DISABLE effects. Original provider outputs and
extraction expressions are retained. Guards use atom/AND/OR/NOT predicates;
missing observations remain unknown. A permission does not implicitly waive a
separate requirement. Independent bonus exclusions target the bonus directly.
This defines rule activation, not an overall applicant-eligibility evaluator.

Statements and guard fragments are checked against cited ranges within the
original requirement. Uncited intervening lines cannot become evidence through
surrounding citations. Canonical assembly freezes interpretation and decision
cutoffs in the same transaction as extraction/link selection, preserves position
scope, and stores exact fragment evidence. PostgreSQL views expose typed rule
rows; Neo4j projects rules, predicate trees, targets, contract and review lineage.
Only accepted interpretations of accepted extractions project rule effects.
Pending corrections and rejected interpretations are excluded from new releases;
already frozen releases are unchanged. Legacy sealed manifests remain compatible.

Native verification:

- LLM import/replay/review/correction tests; all four permission cases and all 16
  bonus combinations; unknown observations; unsupported citations/statements;
  append-only history; cross-batch, EVAL and in-flight repair protection.
- Actual ontology graph readback of five rule effects, eight predicate nodes and
  eleven evidence bindings; exact statement/guard text, operators, paths, targets,
  scope and review provenance; independent truth-table checks from graph data.
- Identical graph reload; pending correction, interpretation revocation and
  extraction revocation selection; closed serving-publication gate.
- Reinstallation preserved the sealed manifest. A deliberately substituted equal
  quote from an uncited line failed evidence verification. Reserved node/edge
  property names fail before graph writes. This guard followed a native test
  finding that the contract's `content_hash` collided with the loader's internal
  field; the contract now projects it as `schema_hash`.
- Earlier v5/v6 fragment compatibility readback passed with twelve expression
  nodes. Existing flat/nested extraction payloads remain intact.

Local evidence: `/tmp/jobtology-ontology/final-rule-llm-test.log`,
`rule-ontology-test.log`, `final-rule-ontology-verifier.log`, and
`fragment-versions-test.log`. Final fixture folders are
`/tmp/jobtology-llm-tests-p5pnaj3o/` and
`/tmp/jobtology-ontology-native-gsat08pk/`. Every deployed runtime file matched its
native-tested copy. The complete prior LLM/ontology suite was not rerun for this
change; the focused native tests above cover the changed paths.

Two real source-bound drafts were imported and replayed through native Hop,
remaining PENDING with no interpretation decisions:

| Posting | Requirement index | Interpretation | Meaning |
|---|---:|---|---|
| 291587 | 2 | `225c7f5668540ccce1806fa1fb96979750876cd5759d77d3b0442987bb5f88a4` | Disability bonus with independent score/unscored and interview exclusions. |
| 304739 | 1 | `56c697746de6e846f5fe50cf4396ecea34c5249c1e75df8d058e07f1dd7489a9` | Military-compliance requirement plus conditional permission for pending discharge. |

Files are under `${PROJECT_HOME}/data/llm/rule-interpretations/`; import receipts
are in `~/.local/state/jobtology-hop/rule-drafts-20260912T121923Z/`.
Original attempts, extraction revisions/reviews, link decisions and release state
were unchanged. Neither draft approved its containing extraction.

A live credit check at **2026-09-12T12:16:10Z** returned funded $8 and usage
$1.8666352, leaving **$6.1333648**. No model calls were made for the implementation,
fixtures or these draft imports. Further paid calls remain bounded and recorded.

Remaining work includes broader source review/repair, attachment input, typed
concept/predicate resolution, production NCS review, JSON-LD/SHACL and query
contracts, release activation/rollback/revocation, and refresh/retention integration.
The original full-corpus scope remains in effect.

### First independently accepted production extraction

Posting **304817** (동남권원자력의학원 respiratory-medicine physician) was checked
against every field of its pinned inline source. Its one position, explicit
outpatient/inpatient/bronchoscopy duty, medical licence, specialty certification,
experience, civil-service exclusions and preferred qualifications were supported.
Selection procedures were not classified as duties. Repeated preference text did
not introduce additional conditions, and education metadata retained posting scope.

The original clause `남자는 병역필 또는 면제자` had no explicit expression tree.
A source-validated correction added male-only conditional applicability with
completed service OR exemption alternatives. Its source text, evidence IDs and
position binding were preserved, as were all other provider fields. Native import
hydration matched the locally reviewed object exactly. The original attempt and
cost remained unchanged.

Native `review_extraction.hwf` recorded an **assistant** ACCEPT decision for
revision `54d10986d846500f857b2504d34122f4f69a3fa3d6e0fbd19ebd0ea80423babc`.
This is a review of inline extraction, not an assertion that attachments or typed
ontology normalization are complete. Evidence:
`~/.local/state/jobtology-hop/source-review-304817-20260912T122133Z/`.

A bounded `categorize_reviewed.hwf` execution was then launched for that exact
revision with Luna/OpenAI, ko-v6, reasoning low, REVIEW policy, cache reuse, one
posting, maximum two requests and a **$0.15 cap**. Source and NCS pins are unchanged.
The credit gate independently confirmed $6.1333648 before launch. Supervisor:
`~/.local/state/jobtology-hop/ontology-reviewed-link-20260912T122244Z/`, PID 3360450,
start ticks 246672424, native child 3360638. This is NCS-only processing; it creates
no new extraction request. Its terminal result must be checked before expansion.

The reviewed-revision categorization finished at **2026-09-12T12:24:01Z**,
native exit 0, batch **`1047d201-e162-4d3b-adf6-ef9537a94ca2`**, COMPLETE.
It made **one categorization request and zero extraction requests**, with 6,668
prompt tokens, 58 completion tokens, **$0.00173645** reported cost and no unknown
charges. `revision_input` retained the exact accepted revision/decision/hash and
`revision_link_result` recorded `no_supported_match`. No candidates were imported.
The supervisor and native-child process handles were confirmed absent after their
terminal report. There were zero RUNNING batches and zero RESERVED attempts.

Independent source review of all 40 retrieved candidates supports abstention:
hospital administration, medical-information/support, animal care and unrelated
inspection units do not establish the physician's respiratory clinical duty.
This is a shortlist-level review, not a corpus-level recall estimate. The
accepted extraction remains accepted despite having no NCS link. A broader
catalogue terminology check is saved in
`/tmp/jobtology-ontology/304817-catalog-terms.jsonl`; the full response, candidates,
revision binding and result are in `reviewed-link-result.json` alongside it.

Current production state: **one assistant-accepted extraction revision**, two
pending rule interpretations, and **zero active ontology releases**. Broader
review is still necessary: inspection of additional candidates found attachment
references classified as `not_stated` and a possible department reassignment
classified as a duty. These are work to correct, not additional accepted outputs.
Canonical release accounting must also carry the independently reviewed
categorization outcomes (including abstention and retrieval gaps), beyond the
already implemented accepted-link projection. No remaining requirement is waived
by this successful one-posting run.

## Native attachment ingestion — 2026-09-12

The separate `attachment` ledger and native Hop workflows are now implemented and
installed. [ADR 0003](../decisions/0003-hop-attachment-processing.md) records the
scoped document-processing policy and verified URL resolver. The original Python
API rights scope is unchanged; its API licence flags are not reused as blanket
attachment permissions. See [the attachment operator guide](../../hop/attachments/README.md).

A native live probe found that the metadata's OpenData attachment URL redirects
to the homepage and returns HTML with HTTP 200. The official JOB-ALIO posting page
links the same file IDs/names through ALIO's working `download.json?fileNo=` endpoint.
Native REST now archives the actual response bytes and verifies signatures, saved
SHA-256 and parser media type. Original and resolved URLs remain in the ledger.

Native Tika XML output required the JDK transformer factory JVM option in the
installed image; the default Saxon factory rejected the external-DTD restriction
attribute. The dedicated CLI invocation selects the compatible JDK factory while
preserving XML protections. No Hop Web restart or global JVM change was made.

The pipeline keeps PDF page locators, HWP body locators and HWPX section-entry
locators. HWPX preview text, font tables and package settings are excluded from
evidence sections. It records unexpected HTTP content, unsupported formats,
parser errors, missing text, parser warnings, unmapped PDF characters and page or
section-count inconsistencies. `PARSED` means converted source text, not semantic
acceptance, OCR completeness or reconstructed table semantics.

Native tests passed planning without HTTP, six sequential synthetic downloads,
HTML masquerading as a PDF, corrupt PDF/HWP isolation, blank PDF handling, Korean
HWPX section extraction without preview pollution, result/input correlation,
writer cleanup and unchanged replay with zero additional requests. SQL checks
covered immutable selection, missing/ambiguous selection safeguards, path and
file-count bounds, changed-source rejection, byte-hash mismatch, zero-attachment
postings and source-retention protection. The focused tests are:

```text
python hop/attachments/tests/checks.py
python hop/attachments/tests/native.py
```

They use initialized disposable ontology containers, never production credentials.
Final native fixture: `/tmp/jobtology-attachment-native-rjotfx4u/`; result and logs
are saved there. The full older ontology/retention suites were not rerun; their
runtime change here is the additive attachment-batch retention protection.

### Deployment and real pilot

Fifteen public runtime files were deployed with hash verification, old-file
backups and native installation under the refresh lock:

```text
~/.local/state/jobtology-hop/attachment-deploy-20260912T125323Z/
```

The immediately preceding deployment's installer could not start because its
file selection omitted `.hwf` files; it made no database installation changes.
The corrected manifest includes both workflows. The final installer, dry run,
six-document pilot and replay all returned native exit 0.

Live batch: **`attachments-20260912-three-postings`**, pinned to JOB-ALIO
`7c34eb6b-0e8f-4deb-a93b-9d336762f8be` and postings 303324, 304739 and 304817.
All eleven metadata entries are accounted for: **six PARSED**, three application
forms and two other-role files pending scope review. The six parsed files are
three PDFs, two HWP files and one HWPX file; together they contain seven evidence
sections. An independent live readback rehashed every original file and compared
all section text/hashes against the separately executed local native pilot:
**zero byte or text differences**. The physician PDF was also visually reviewed.
Its clinical-medicine classification explicitly says undeveloped, consistent with
the earlier supported NCS abstention; this does not itself accept new attachment
claims or settle other postings' NCS matches.

Replay changed no attempts and left no attachment writers. Source records,
original model attempts/items, extraction revisions, review decisions and
ontology releases were identical before and after the pilot. One accepted inline
extraction and zero active ontology releases remain the production semantic state.
No model calls were made by this workflow.

Local readback receipts:
`/tmp/jobtology-attachments/live-pilot-documents.jsonl` and
`/tmp/jobtology-attachments/live-pilot-verification.json`.

### Full current-source attachment pass — supported-format pass finished

A supervised native pass was launched after the pilot and disk-reserve check:
**`attachments-20260912-full-513`**. Its plan covers all 513 pinned postings and
**1,702 attachment entries**: 909 planned PDF/HWP/HWPX notices/job descriptions,
375 application forms, 335 other-role entries needing review, and 83 currently
unsupported formats (60 ZIP, 9 JPG, 10 PNG, 4 DOCX). No entries were silently limited.
Those other outcomes are coverage gaps or excluded forms, not proof that all
attachment evidence has been processed.

Supervisor receipt:
`~/.local/state/jobtology-hop/attachments-full-20260912T125544Z/`.
Supervisor PID 3450341, start ticks 246870498; native exec PID 3450866.
The worker holds refresh and LLM-full locks, uses a bounded 1 GiB JVM, checks the
100 GiB disk reserve, and invokes the native workflow with `MAX_FILES=1000`.
It performs no ETL parsing or paid calls itself. The native pass finished at
**2026-09-12T13:04:30Z**, exit 0. Both supervisor and native-exec process handles
were confirmed absent; there are zero attachment writers or in-flight attempts.

| Full-pass outcome | Documents |
|---|---:|
| PARSED | 888 |
| NO_TEXT | 12 |
| PARSE_ERROR | 5 |
| NEEDS_REVIEW | 4 |
| Total attempted | 909 |

The pass retained **239,346,551 original bytes** and **4,152 evidence sections**.
Independent verification rehashed and measured **every one of the 909 files**,
compared every source metadata entry/ordinal/locator against the pinned API
records, and independently parsed the saved Tika XML to compare all 4,152 section
contents, locators, order and hashes. There were zero differences. This verifies
storage and parsing projection, not full semantic accuracy or OCR completeness.

`verification.json` and `issues.json` in the supervisor folder retain the final
readback and all 21 non-PARSED outcomes. Local verification output is
`/tmp/jobtology-attachments/full-verification.txt`. Do not restart this finished
pass because of an old RUNNING note or a stale reserved-state observation.

Failure triage found four PostgreSQL `unsupported Unicode escape sequence` errors
and one PDF parser error about a missing root object. A separate native probe of
file 3022711 confirmed NUL characters in `dc:title` and `pdf:docinfo:title` metadata;
its body XML parses and contains readable Korean text. A tested SQL replacement
expression can distinguish escaped NUL from literal `\\u0000`, but a production
repair still needs raw-metadata preservation, regression checks and a new attempt.
No source text or old attempt has been silently sanitized or rewritten.

The final readback still found one accepted inline extraction and zero active
ontology releases. The attachment pass made no model requests.

Remaining work includes ZIP/DOCX/image handling and other-role review, attachment
input/version/cache binding for LLM extraction, immutable document evidence in
ontology releases, full semantic review/repair and linking, and the serving
contracts and release lifecycle already listed above. Existing LLM workflows
still consume inline source fields; attachment text is not silently appended to
old items or accepted revisions.

Eight partial attachment regression assertions are now checked in at
`hop/llm/evaluation/attachment-pilot-v1.assertions.json`, each bound to a document
hash, section hash and exact code-point offsets. They are explicitly assistant
review, not human gold or production acceptance. Among them, 304739 lists
1002020101 and 1002020103 as primary competency references but gives 0202030201
only as a code example. The pinned catalogue contains corresponding versioned
units, including an old-version label on 1002020101_14v1; the document does not
assert those standard versions. A future source-declared link must preserve that
distinction rather than infer a version or turn the example into a job mapping.

Full live replay also passed with **zero download-child executions** and identical
attachment attempts/sections, original model attempts, review decisions and
ontology release records. `replay.log` and `replay-verification.json` are retained
in the full-pass supervisor folder.

A fresh authenticated OpenRouter credit check at **2026-09-12T13:09:50Z** returned
funded $8, usage $1.86837165, **remaining $6.13162835**. `credit-after.json` records
that point-in-time balance without credentials. This is enough to plan a bounded
attachment-aware pilot; the complete extraction/review/linking cost must be
measured after the input contract and document handling are ready. No paid
attachment-aware model run has been launched.

## Attachment metadata repair and versioned LLM inputs — 2026-09-12

The PDF metadata repair is deployed. New parses preserve the raw Tika metadata
string and its SHA-256, retain a separately normalized JSONB representation, and
record the affected fields/count under `json-nul-to-replacement-v1`. Only the two
verified PDF title fields can normalize escaped NUL without requiring review.
Literal backslash escapes, body XML and evidence text remain unchanged. The new
`xml-jsonb-v2` digest includes the raw metadata string; historical v1 rows/hashes
remain intact.

Native synthetic tests covered adjacent NUL escapes, odd/even escaped backslashes,
arrays, original replacement characters, title-only normalization versus other
metadata requiring review, byte/text preservation, failure isolation and replay.
The native fixture was `/tmp/jobtology-attachment-native-4ie_emei/`.

The one-file public SQL deployment is recorded under
`~/.local/state/jobtology-hop/metadata-v2-deploy-20260912T131637Z/`.
Native installation succeeded and before/after fingerprints of source data, LLM
attempts, extraction reviews, ontology releases and historical attachment rows
matched. A prior preflight query used an incorrect review-column name and stopped
before replacing any file or executing the installer.

A targeted native retry, `attachments-20260912-metadata-v2-retry`, selected postings
295776, 304393, 304413 and 304633 from the same pinned job snapshot. It finished at
13:17:36Z with seven attempted files: six PARSED and one PARSE_ERROR, 15 sections,
and 1,069,694 original bytes. Four previously failed PDFs were recovered:
3022711, 3072145, 3072147 and 3073188. File 3072017 remains malformed.
Across the original 909 selected files, choosing these retry outcomes yields
892 PARSED, 12 NO_TEXT, one PARSE_ERROR and four NEEDS_REVIEW; the original full
batch itself is unchanged.

Receipt folder:
`~/.local/state/jobtology-hop/attachments-metadata-v2-20260912T131723Z/`.
Independent verification rehashed all seven files, compared their sizes and bytes
with the originals, independently reconstructed all 15 sections from retained XML,
and decoded/normalized metadata separately in Python. The original attempt-row
fingerprint still matched the pre-deployment value. Both supervisor and native
process handles were confirmed absent, with zero attachment writers. Verification
and issue files remain in that folder and locally in
`/tmp/jobtology-attachments/metadata-v2-verification.txt`.

### Input bridge implementation and verification

The new `attachments/prepare_inputs.hwf` creates immutable
`enrichment.input_bundle` records and optionally a frozen EVAL dataset. Explicit
completed batch IDs select document outcomes, with later IDs taking precedence
per file. Every source attachment is accounted for, including excluded forms,
unsupported formats and failures. Only PARSED documents contribute text.

Each document has its own source field; verified sections are joined by one LF.
Section locators, hashes and exact code-point ranges preserve page/section
provenance across this join. Model input hashes omit private paths and attempt IDs
but include source metadata, byte/text hashes and all document outcomes. Separate
bundle IDs retain exact job snapshot, API document, attachment batch, attempt and
parser lineage. Existing inline inputs, attempts and reviews are not rewritten.

`INPUT_BUNDLE_IDS` selects exact inputs for ENRICH. EVAL uses its frozen case
bindings. Planning, request reservation and independent extraction capture verify
those bindings. The document fields participate in narrative evidence and ko-v6
source accounting. Revision-only categorization can retain the same input bundles
without another extraction call. Requests require ko-v6 and REVIEW; full corpus
input is never silently truncated.

Disposable SQL checks passed under `attachment-input-a3220f6f2e`, including cache
identity across distinct parse attempts, tamper detection, immutable dataset/item
bindings, missing-passage rejection, exact evidence offsets, EVAL isolation,
revision-only categorization and the existing ko-v6 Korean condition checks.
Native input preparation, unchanged replay, and EVAL/ENRICH planning passed in
`/tmp/jobtology-native-inputs-857iccf2/`, using a deliberately absent key file and
zero model reservations. The full existing LLM regression suite passed in
`/tmp/jobtology-llm-tests-a14ig_b3/`, including v1–v6 native requests, budget/cache
behavior, independent decisions, corrected-revision categorization, repair guards
and guarded-rule import/review. These input tests do not prove semantic acceptance
or ontology document-evidence publication.

An authenticated credit read at **2026-09-12T13:27:36Z** returned **$6.13162835**
remaining (funded $8; usage $1.86837165). No model calls have been made during the
metadata repair or input-bridge tests. This is sufficient for a bounded pilot;
attachment-aware extraction/review/linking cost still needs measurement.

The goal remains incomplete: finish live input-bridge deployment and real pilot,
other-format/role coverage, attachment-aware canonical/review selection and document
evidence projection, full-corpus repair/review/linking, typed conditions and concepts,
query/interchange contracts, release activation/rollback/revocation and refresh/
retention integration. One accepted inline revision and zero active ontology
releases remain the latest live state.

The large HWPX pilot notice (file 3073720) needs further structure handling:
its retained Tika text has 29,315 characters but only five nonempty lines. Inspection
of the original archive found 1,366 paragraph elements and 37 tables in
`Contents/section0.xml` (954,817 XML bytes). This is a concrete source-layout gap;
the input bridge preserves existing text but does not reconstruct those paragraphs
or tables. Improve the native HWPX paragraph/table evidence path before relying on
that case for full semantic acceptance. The original archive hash and counts are
saved in `/tmp/jobtology-attachments/hwpx-structure-inspection.json`.

### Input bridge deployed; full source input preparation

Eighteen public runtime files were installed and hash-verified under
`~/.local/state/jobtology-hop/attachment-input-deploy-20260912T133434Z/`.
Both native installers exited 0. Before/after fingerprints matched for source
records, model items/attempts, extraction/link/rule revisions and decisions,
attachment attempts/sections and ontology releases. Private metadata and keys
were not copied or modified.

The native full-input run is in
`~/.local/state/jobtology-hop/attachment-inputs-20260912T133532Z/`.
It selects the original full attachment batch followed by the metadata retry,
with the exact current job pin and a 1,000-posting cap. It also prepares the
three-posting frozen dataset `korean-attachments-v1`. It makes no provider or
model calls. Supervisor 3609133 (start ticks in `status.json`) and native exec
3609223 were confirmed running during the full-input SQL action; inspect terminal
receipts before treating this as completed or retrying anything.


### Full input preparation and independent verification completed

Both native workflows succeeded: all inputs finished at 13:37:07Z (91.407 seconds),
and the three-case dataset finished at 13:37:12Z (1.744 seconds). The supervision
script then failed in its final reporting SQL because of a quoting typo. The
original `status.json` correctly retains that supervision failure. **Do not restart
the successful native workflows because this status says FAILED.** The reporting
helper has been corrected locally; no data processing was repeated to fix a report.

Direct database inspection and independent verification confirmed:

| Check | Verified result |
|---|---:|
| Job inputs / distinct pinned postings | 513 / 513 |
| Attachment metadata entries accounted for | 1,702 |
| Parsed document fields supplied to input | 892 |
| Exact original section ranges mapped into document fields | 4,125 |
| Total stored input characters, including metadata | 8,574,164 |
| Largest stored posting input | 82,116 characters |
| Document fields containing a line over 8,000 characters | 12 |
| Frozen `korean-attachments-v1` EVAL cases | 3 |
| Paid/model requests during this work | 0 |
| Active ontology releases | 0 |

The independent reader compared every input's inline fields against the assembled
source posting, every metadata entry against the pinned API payload, and every
bound document/attempt/outcome against the attachment ledger. It independently
rejoined all selected section texts and checked each section hash and code-point
range, full document text/hash, source input hash and bundle identity hash. It
accounted for 335 ROLE_REVIEW, 375 APPLICATION_FORM, 83 UNSUPPORTED_FORMAT,
12 NO_TEXT, four NEEDS_REVIEW and one PARSE_ERROR outcomes alongside the 892
PARSED documents. Sections belonging to non-PARSED attempts are deliberately not
model input; that is why this input section count differs from the raw parse ledger.

`verification.json` and `long-fields.json` in the live receipt folder reconcile the
supervision reporting error with the verified native results. Local readback:
`/tmp/jobtology-attachments/live-input-verification.txt`; verification program:
`/tmp/jobtology-attachments/verify_live_inputs.py`. Supervisor 3609133 and its last
native child 3613249 were confirmed absent; no retention writer remains. Model
attempts, extraction decisions and ontology releases matched their pre-run hashes.
No extraction or production acceptance was created by input preparation.

Next work should address the HWPX paragraph/table structure, then run the bounded
attachment-aware quality pilot and finish canonical input/document evidence
bindings before full publication. The earlier full ontology requirements remain
in scope, including the remaining document formats and the complete job corpus.


## Native HWPX structure and full v2 inputs — 2026-09-12

Fourteen tested public files were deployed with atomic replacement and before/after
hashes under `~/.local/state/jobtology-hop/hwpx-structure-deploy-20260912T141322Z/`.
Both native installers exited 0. Fingerprints of the existing sources, model
items/attempts, extraction/link/rule decisions, attachment parses, input bundles,
frozen datasets and ontology releases were unchanged. No editor restart or private
metadata/key replacement was needed.

The native VFS/Calculator/SQL workflow reads original HWPX archive members and
reconstructs paragraph/control order, nested tables and cell geometry. The initial
real test failed because a PL/pgSQL record variable shadowed a query alias; this
was fixed before deployment. Package validation checks manifest/spine membership,
duplicate IDs, unsupported paths and missing entries. Unknown controls, invalid
geometry and incomplete visual content remain explicit outcomes.

The independent XML oracle checked text/control events, paragraph and table
ownership, merged-cell coordinates and reconstructed body hashes. Native fixtures
also covered multiple sections in spine order, nested tables with text before and
after them, special whitespace, a foreign-namespace control, malformed packages,
path traversal, external-entity declarations, changed archives, failure isolation
and unchanged replay. Runtime parsing remains native Hop plus PostgreSQL; Python
is only the generator/test/supervision/independent reader.

New `attachment-input-v2` bundles explicitly select completed HWPX structure
batches. Old v1 bundles keep their original reconstruction and hash. The compact
model request preserves all passage IDs/text and maps HWPX blocks to original line
ranges, paragraph owners and section-local tables/cells. Audit hashes and exact
character offsets remain in the immutable input manifest. A real-notice fixture
initially exceeded the 200,000-character request limit; eliminating repeated
field/offset/audit metadata reduced it from 216,187 to 130,449 characters without
removing source passages or table relationships.

Final native package: `/tmp/jobtology-hwpx-native-jshzpzin/`.
The final package installer and v2 planning checks passed, as did legacy input
checks (`attachment-input-a03a3d2157`) and the full native LLM regression suite
(`/tmp/jobtology-llm-tests-catvb4f9/`). These tests include request/cache/budget
behavior, independent reviews, corrected-revision categorization, repair guards,
rule interpretation, publication and revocation in disposable databases.

### Live reconstruction and independent readback

Receipt: `~/.local/state/jobtology-hop/hwpx-full-inputs-20260912T141414Z/`.
The supervisor finished at **2026-09-12T14:16:15Z**, exit 0. All three native
workflows succeeded: full HWPX reconstruction, full structured-input preparation,
and the new frozen three-case `korean-attachments-v2` dataset.

| Measure | Verified result |
|---|---:|
| Archived HWPX files attempted | 32 |
| VERIFIED / REVIEW_REQUIRED / FAILED | 29 / 2 / 1 |
| Independently checked text/control events | 8,853 |
| Text blocks / tables / cells | 6,811 / 308 / 4,456 |
| New pinned posting inputs | 513 |
| Attachment metadata entries accounted for | 1,702 |
| Document fields supplied to v2 input | 889 |
| Fields using reconstructed HWPX text | 29 |
| Paid/model calls during preparation | 0 |
| Active ontology releases | 0 |

The reader rehashed all 32 original archives. For every VERIFIED reconstruction it
compared all saved XML members, text events, blocks and table/cell ownership against
an independent archive/XML parser. It then checked all 513 v2 bundles against the
existing v1 inputs, the chosen structure outcomes and their exact section ranges.
`independent-structures.json` and `independent-verification.json` contain the live
receipts. Supervisor 3709187 and the final native child were confirmed absent;
no retention writer remained. Existing model/review/release fingerprints matched.

The three excluded HWPX reconstructions remain follow-up work:

- Posting 304103, file 3070518: the package spine contains the standard
  `Scripts/headerScripts.js` and `Scripts/sourceScripts.js` members. The current
  text-only spine policy rejects them. Add a versioned policy for explicit
  non-execution/non-text accounting while retaining the section XML.
- Postings 304575 / 304751, files 3072911 / 3073768: `markpenBegin` and
  `markpenEnd` are retained as unknown controls and require review. Hancom's model
  defines the begin marker's color attribute and a corresponding end marker;
  support should preserve their styling provenance without inserting text.

Primary format references: [Hancom's HWPX structure guide](https://tech.hancom.com/hwpxformat/),
[begin marker model](https://raw.githubusercontent.com/hancom-io/hwpx-owpml-model/master/OWPML/Class/Para/markpenBegin.h),
and [end marker model](https://raw.githubusercontent.com/hancom-io/hwpx-owpml-model/master/OWPML/Class/Para/markpenEnd.h).
Embedded images, other attachment formats/roles and semantic review remain separate
coverage gaps. VERIFIED text reconstruction does not establish full visual content.

### Attachment-aware paid pilot started

The new pilot receipt is
`~/.local/state/jobtology-hop/attachment-luna-pilot-20260912T141741Z/`.
The native dry run created all three extraction requests without reservations:
303324 = 24,318 characters, 304739 = 150,245, 304817 = 23,823. No input exceeded
the configured limit. Paid EVAL batch **`39002649-313f-418d-bf26-230357839210`** then
started using Luna/OpenAI, ko-v6, reasoning none, REVIEW, at most six logical
requests, 32,000 output tokens per request, a $0.10 request reservation,
**$0.60 batch cap** and $5 shared rolling-day cap. Read timeout is 600 seconds.
The authenticated preflight balance was $6.13162835. This pilot is isolated from
production acceptance and release publication.

Supervisor PID 3731016 and native child 3733235 were confirmed running at launch;
inspect `status.json`, actual process identities and the PostgreSQL batch before
any restart. At the first response check, posting 303324 was rejected after HTTP
200 for altered fragments, exclusion polarity and incomplete/misclassified source
accounting. Its original response is retained. The large HWPX posting was still
reserved and the third posting planned. These are intermediate results, not the
final pilot outcome. Complete semantic review before expanding paid processing.

### Attachment-aware pilot finished — quality expansion held

The same batch and supervisor finished at 14:22:09Z on 2026-09-12. Native exit 0
means the workflow recorded its outcomes; the batch is **PARTIAL**, with all three
HTTP-200 extractions **REJECTED**, no categorization calls, no cache hits, and
**$0.05187852 reported cost**. Do not restart this terminal batch.

| Posting | Reported cost | Validation findings |
|---|---:|---|
| 303324 | $0.00778235 | 50 entries: 20 unaccounted passages, 17 unproven headings, six unresolved passages, three unsupported fragments, one absence-as-exclusion error and three other coverage flags. |
| 304739 | $0.04040796 | 986 entries: 660 unaccounted passages, 226 unproven headings, 31 unexpected trees, 42 possible omitted conditions, plus 27 evidence/disposition/coverage flags. |
| 304817 | $0.00368821 | 93 entries: 72 unaccounted passages, nine unproven headings, six unproven no-condition dispositions, three possible omitted conditions, two unresolved passages and one mixed-field position citation. |

These are validator entries, not independent factual-error counts. The large
notice also illustrates a response-contract problem: 31 single requirements
returned an atom condition where ko-v6 requires null. Merely changing this shape
would not resolve its omitted passages or establish correct requirement scope.
303324 also assigned research conditions for clinical professors to a combined
clinical/treatment-professor position and failed to represent the two required
medical credentials as AND. PDF word wrapping explains some fragment mismatches;
it does not justify discarding the original evidence or silently accepting altered
text. 304817 combined title and eligibility evidence for one position, which the
current one-field evidence contract cannot represent.

Next extraction work must distinguish document context from applicant requirements,
preserve role-specific conditions and exact fragment provenance, and handle long
documents without losing source accounting. Full paid corpus expansion has not
been launched with this failing configuration. The source/document inputs remain
available for a versioned retry.

Authoritative receipt: the pilot directory above, `status.json` (FINISHED, exit 0)
and its batch report. Protected local output export:
`/tmp/jobtology-attachments/attachment-pilot-final.json`. The immediate post-run
credit receipt reports $6.08343804 at 14:22:09Z; this is a point-in-time provider
balance and may lag final attempt settlement. Existing acceptance/release state
remains one accepted inline revision and zero active ontology releases.

### Canonical document evidence integration deployed — 2026-09-12

Attachment-aware extraction selection now has an explicit native entry point:
`ontology/bind_document_inputs.hwf`. Before freezing reviews, supply the exact
release ID and a complete pipe-separated `INPUT_BUNDLE_IDS` set. Its immutable
manifest selects one bundle per posting in the pinned JOB snapshot. Partial,
duplicate and mismatched selections fail; old inline releases retain their
existing selection behavior and manifest shape. Identical full input content can
reuse a reviewed extraction while the release preserves its own selected attempt
lineage. The workflow creates no acceptance decision and makes no model request.

Accepted document evidence now has both original and NFC/LF-normalized offsets.
The graph records posting inputs, declared attachments, document sections, HWPX
tables/cells and document observations. Exact evidence spans connect to overlapping
sections, including cell membership, merged-cell geometry and nested tables.
Attachments connect to the exact pinned source record that declared their file.
Private raw paths are kept in PostgreSQL lineage, not graph properties. Embedded
images remain explicitly unreviewed; text reconstruction is not OCR completion.

Verification:

- Native Hop installation, HWPX reconstruction, full input binding, review
  assembly, graph loading and replay passed in the disposable fixture. Five
  postings produced ACCEPTED/ACCEPTED/REVIEW_REQUIRED/REJECTED/NOT_PROCESSED as
  intended; EVAL cannot enter production review. Only the two synthetic accepted
  extractions produced document claims. The candidate has **140 nodes and 409
  relationships**, with independent Neo4j traversals to both source responses.
- Python readback verified exact excerpts/hashes and page offsets with emoji,
  decomposed Hangul and CRLF normalization. Native graph readback verified merged
  cell spans and nested-table membership. Transactional corruption tests rejected
  a substituted posting, wrong file ordinal and shifted section offset.
- The retained full real-source/output fixture still verifies **513 postings,
  1,850 claims, 211 positions and 2,873 evidence spans**. Its sealed manifest
  remains unchanged at **182,670 nodes / 785,235 relationships**. This compatibility
  check reused the saved graph inventory; the earlier full Neo4j load was not
  repeated. Fixture acceptance is not production semantic acceptance.
- Six public runtime files matched the native-tested package. The additive live
  installer exited 0 under the existing refresh/LLM locks. Fingerprints of source
  records, model attempts/items, input bundles/datasets, review decisions, pinned
  sources, release records and active-release state were identical before/after.

Native fixture logs and result:
`/tmp/jobtology-ontology-native-mqj1yr5i/`; saved-real compatibility logs:
`/tmp/jobtology-ontology-native-hhxu68ia/`.
Deployment receipt/backups on Goldship:
`~/.local/state/jobtology-hop/ontology-document-deploy-20260912T143741Z/`.
The [ontology operator guide](../../hop/ontology/README.md) describes binding and
graph evidence traversal. The live initial release has not had its document inputs
or reviews frozen, and no ontology release has been activated. Full-corpus semantic
extraction, reviewed linking, remaining document coverage and serving contracts
are still required.

A subsequent live transaction selected exactly the full v2 attachment/structure
batch combination and successfully ran the binding verifier for **513 inputs /
513 distinct postings** against `ontology-20260912-initial`. It then explicitly
rolled back. The release record matched its before-image; document input sets,
initial-release review freeze and active-release selection all remained empty.
This verifies full live source/input compatibility without fixing the production
release to an input version before extraction review is finished. Receipt:
`~/.local/state/jobtology-hop/ontology-document-probe-20260912T143828Z/status.json`
(FINISHED, rolled_back=true). No model calls were made during this integration,
deployment or full input compatibility check.

### ko-v7 source accounting and bounded pilot — 2026-09-12 UTC

The completed v6 pilot exposed a contract problem as well as semantic errors:
hundreds of individual uncited-line objects competed with extraction output, and
ordinary pay/institution/form context had no explicit category. `ko-v7` introduces
inclusive, same-field `unhandled_ranges`. PostgreSQL expands them to every original
nonempty passage; gaps, unknown boundaries, reversed/cross-field/overlapping ranges,
cited/uncited conflicts and unaccounted passages remain failures. Empty physical
lines do not change the original passage numbers.

Document context is typed as employment terms, application form, institution
background, job profile, document structure or privacy notice. Context guards
reject obvious required credentials, age restrictions, bonus rules and other
applicant conditions. They are targeted diagnostics, not a complete semantic
proof. Unresolved source clauses still prevent acceptance. The provider schema
also enforces null for single/unspecified conditions and the matching AND/OR or
conditional root for compound conditions. Prompts address split PDF words,
separately advertised positions, clinical-professor-only research conditions and
the medical-licence/specialist-certificate AND case. Historical v1–v6 prompts and
validators are unchanged; converting saved failed output does not accept it.

Verification before deployment:

- Native LLM regression passed for v1–v7, including response/error handling,
  accounting, cache isolation, review/correction/revocation, repair protection,
  revision-only categorization and independently reviewed rules. V7 native calls
  used a local mock, not a paid model. Logs:
  `/tmp/jobtology-llm-tests-0oh8250f/`. Final v7 SQL was staged before v7 checks;
  the completed native document fixture below independently installed that final
  package through Hop SQL actions.
- The new condition grammar rejects the redundant single-atom shape from the
  prior pilot. Range/context fixtures verify every expanded passage, CRLF/blank
  lines, exact quotes, explicit restrictions, missing coverage and malformed
  ranges. Both medical credentials retain an AND; altered split-word quotations
  remain rejected.
- All three saved v6 pilot responses still reproduce their original v6 issue
  arrays. Encoding their old dispositions as ranges does not make them valid.
- V7 synthetic accepted document extractions passed the native ontology/HWPX/
  Neo4j integration, including source-response lineage, normalized offsets, merged
  and nested cells, EVAL/review isolation and graph replay. Logs:
  `/tmp/jobtology-ontology-native-8epi2e7r/`.

Twelve public runtime files were deployed from that verified package with backups,
hash checks and the existing locks. Native LLM and ontology installers both exited
0; fingerprints of previous prompts, sources, model/input records, reviews and
releases were unchanged. Receipt:
`~/.local/state/jobtology-hop/llm-v7-deploy-20260912T145917Z/`.

A bounded real pilot uses the existing frozen `korean-attachments-v2` dataset,
the same JOB/NCS pins, Luna/OpenAI, ko-v7, medium reasoning, 32,000 output tokens,
200,000 request characters, six maximum logical requests, $0.10 reservation,
$0.60 batch cap and $5 rolling-day cap. No EVAL result can become production
acceptance. Prompt/schema and reasoning are both changed; this is an operational
quality comparison, not an isolated model-intelligence experiment.

The native dry run planned all three requests without reservations:
303324 = 30,603 characters; 304739 = 156,530; 304817 = 30,108. Supervisor 3843158
then launched paid native child 3845442. Receipt:
`~/.local/state/jobtology-hop/attachment-luna-v7-pilot-20260912T145957Z/`.
Check its current status, actual process identity and database before any restart.
No final pilot result, accepted extraction or active ontology release is claimed
at this running checkpoint. Full production extraction/review/linking, remaining
attachment coverage and serving contracts remain required.

### ko-v7 pilot completed — 2026-09-13 KST

The pilot above is terminal; its supervisor finished at 15:04:08Z on September 12
(00:04:08 KST on September 13) with exit 0. Batch
`9bd86bc7-165a-4b14-b41c-ebcb79723ddb` finished PARTIAL: three HTTP-200 extraction
responses, **zero validated, three rejected**, no categorization calls or cache
hits, and no unknown-cost requests. Reported cost is **$0.03981502**, with 87,617
prompt tokens and 15,966 completion tokens. Do not restart the completed pilot.

| Posting | Recorded validation findings |
|---|---|
| 303324 | Eight non-narrative range entries: structured metadata was incorrectly included in narrative source accounting. |
| 304739 | One non-narrative range, one invalid range order/field, and one invalid duplicate range. |
| 304817 | One invalid duplicate range. |

Range validation returns early, so these are not exhaustive semantic-error counts
and cannot establish improvement over the v6 issue totals. An offline diagnostic
copy of 303324 removed only its redundant metadata ranges, exposing 31 further
validation flags. Source inspection also found research contribution/scoring rules
misclassified as document context and clinical-professor-only conditions assigned
to a combined clinical/treatment-professor position. Some heading checks are too
strict as well. The diagnostic was neither a production correction nor acceptance.

The paid pilot's before/after fingerprints for extraction decisions, link decisions
and releases are identical. Recorded production state remains one accepted inline
revision, zero accepted NCS links and zero active ontology releases. The immediate
post-run credit receipt showed $6.04820322 remaining; provider settlement can lag,
so recheck before more paid work. Full attachment-aware corpus expansion was not
launched. Next work must address range construction, faithful role/condition scope,
and source review before scaling, alongside the remaining attachment formats and
ontology publication/query contracts listed above.

Authoritative receipt: the pilot directory above (`status.json`, `report.json`,
`credit-after.json`, and matching `before.json`/`after.json`). Protected local export:
`/tmp/jobtology-attachments/attachment-v7-pilot-final.json`.

### Source-bound requests deployed and full preview started — 2026-09-13 KST

New v7 extraction requests use `source-bound-ranges-v1`. Native SQL generates a
response schema from exact nonempty source line IDs. Citations are constrained
to those IDs; each range schema names one narrative field and correlates its
disposition, context kind and duplicate reference. Metadata fields are listed
separately in request context. Finite ID patterns avoid enumerating thousands of
strings in the provider schema. Existing source text, offsets, prompt schemas and
attempts are unchanged, and request contents isolate new cache entries.

`schema_issues_request_v1` independently checks these patterns and unions before
the existing semantic validation/hydration path. Cross-line ordering, overlap,
duplicate identity and source meaning still need their existing downstream checks.
Reviewer-supplied invalid v7 ranges now fail with `CORRECTION_NOT_VALIDATED` before
integer parsing during hydration; they cannot create a revision. This is a request
construction and error-handling improvement, not evidence of model accuracy.

Verification:

- Native regression reached and passed the legacy v1–v6, accounting, cache,
  review/revocation, repair, rule, and v7 two-stage checks. Its final new rejection
  assertion incorrectly expected `PATTERN`; a failed requirement union reports
  `ANY_OF`. The actual response was correctly rejected. Log/fixture:
  `/tmp/jobtology-llm-tests-0qtcp2re/` and
  `/tmp/jobtology-attachments/source-bound-native-regression.log`.
- After correcting that test assertion, the focused native rerun passed installation,
  EVAL/ENRICH, categorization, replay, capture, unknown-citation rejection, original
  response retention and invalid-correction history preservation. Final fixture:
  `/tmp/jobtology-llm-tests-um5j49r7/`; log:
  `/tmp/jobtology-attachments/source-bound-focused.log`.
- The reusable `hop/llm/tests/source_bound_real.py` checked **all 513 pinned inputs
  and 223,976 passages** against native source hashes and an independent JSON Schema
  validator. Original text/offsets, blank-line gaps and valid/invalid line IDs matched.
  Every generated schema stayed within enum/property limits. The largest schema
  was 41,039 characters (posting 304713; 2,716 passages); this does not establish
  that the complete request fits the 200,000-character request limit. Receipt:
  `/tmp/jobtology-attachments/source-bound-corpus-final/verification.json`.
- All five deployed public files matched both native-tested packages. Deployment
  used the existing locks, backups and hash checks. The native LLM installer exited
  0; prior prompts and protected source/model/input/review/release fingerprints were
  identical before/after. Receipt:
  `~/.local/state/jobtology-hop/source-bound-deploy-20260912T152812Z/`.

Seven partial assistant review checkpoints are saved in
`hop/llm/evaluation/attachment-review-checkpoints-v1.json`, with exact frozen
document hashes, line IDs and verified excerpts/offsets. They cover the clinical
professor scope, research contribution rates, credential conjunction, youth and
technical-certificate bonuses, former-worker alternatives and male-only military
conditions. The saved responses still omit substantive rates/limits and role
scope. These are neither human gold nor production acceptance, and must stay out
of model inputs. No paid model call was made during this implementation/deployment.

A native full-input preview is running under
`~/.local/state/jobtology-hop/source-bound-full-preview-20260912T152838Z/`.
It first freezes `korean-attachments-sourcebound-v1-513` through the structured-input
workflow, then calls `llm/evaluate.hwf` with `EXECUTE_REQUESTS=N`, REVIEW, ko-v7,
Luna/OpenAI and the same JOB/NCS pins. It is intended to account for all 513 actual
request sizes with zero reservations and explicit oversized outcomes. Inspect the
receipt, process identities and database before a retry; no final preview result
is claimed at this checkpoint. Semantic repairs/review, remaining attachments,
full transformation/linking and ontology publication/query contracts remain open.

The full evaluation dataset was subsequently verified at 513 distinct postings.
Dry EVAL batch **`55f15bc1-149e-4944-be68-d9a8fe72443f`** was created with
`EXECUTE_REQUESTS=N`. Supervisor 3917828 (start ticks 247787897) and native dry-run
child 3926055 were confirmed live while the extraction-planning SQL ran. The
supervisor receipt records the child's exact start ticks. This is the same ongoing
preview, not a new run; use that receipt/batch to continue observation.

#### Full native preview finished

The same supervisor finished at **15:38:53Z on September 12 / 00:38:53 KST on
September 13**, exit 0. Batch `55f15bc1-149e-4944-be68-d9a8fe72443f` remains PLANNED
because it is a dry EVAL batch; its supervisor/workflow execution is terminal.
Do not restart it. All 513 posting inputs matched their frozen source hashes and
used the source-bound request policy. **509 requests fit the configured limit**;
four retain `INPUT_TOO_LARGE` outcomes:

| Posting | Complete serialized request characters |
|---|---:|
| 304429 | 200,838 |
| 304432 | 215,221 |
| 304713 | 279,668 |
| 304839 | 228,184 |

The limit was 200,000 characters. Median size was 62,784; total was 36,719,198.
No source text was truncated. New reservations and paid calls were both zero.
Fingerprints of source records, frozen input bundles, review/link decisions and
release/active-release records were unchanged. `status.json`, `report.json`,
`requests.json`, `before.json` and `after.json` in the preview receipt contain the
final proof and per-posting outcomes. The dry configuration deliberately retains
six requests and a $0.60 cap; it is not a production expansion configuration.

This verifies native full-corpus input/request accounting, not provider acceptance
of the new grammar or semantic extraction quality. Future work must preserve
context while handling the four oversized inputs, repair the role/condition and
table-score problems, and pass bounded real-model evaluation before full paid
transformation/linking. The remaining ontology publication requirements above
continue to apply; no production acceptance or release was added here.

## Compact document input deployment — 2026-09-13 KST

The four oversized requests contained 47,000–68,000 actual source characters.
Repeated passage-object keys, field IDs and document metadata accounted for much
of their serialized size. New `llm/sql/020_document_packets.sql` provides a
lossless model-facing encoding: each field maps to `[original_line_number,
exact_text]` rows. Full citation IDs remain `field:line`; physical blank lines
retain their numbering gaps. No source text is summarized or truncated.

Verified HWPX layouts now place all cell blocks directly under their logical
table rows. The packet retains block/paragraph IDs, context roles, captions,
merged spans, nested-table parents and empty cells/tables. Unmatched block
ownership, including a nested caption owned by an outer cell, remains explicit.
Nearby body-block IDs expose headings/footnotes without asserting applicability.
PDF/body section line boundaries and all original document outcomes remain
available. Frozen hashes, codepoint offsets and the ontology evidence contract
are unchanged; the compact representation is only an LLM request projection.

New v7 extraction and categorization use this encoding. Historical request
objects and v1–v6 request construction are unchanged. The existing source-bound
response schema still enforces real citation IDs; semantic validation and
independent acceptance remain required. Encoding and instruction changes affect
cache keys through the complete saved request.

Verification completed before deployment:

- `document_packet_checks.py` independently decodes Unicode/CRLF/blank-line
  cases and merged/nested/empty-cell and caption ownership fixtures.
- `document_packet_real.py` checked all **513 frozen inputs / 223,976 passages**,
  6,336 HWPX input blocks, 308 tables and 4,456 cells. Every original line, source
  hash, document outcome, block/cell/table identity, span and parent matched.
  Receipt: `/tmp/jobtology-attachments/document-packet-corpus/verification.json`.
- The native focused suite passed installer, EVAL/ENRICH, categorization, cache
  replay, capture, invalid-source response rejection and correction-history
  preservation. Log: `/tmp/jobtology-attachments/document-packet-native.log`;
  exact tested package: `/tmp/jobtology-llm-tests-ss6yqmsq/project`.
- Three public files matched that package and were deployed under the existing
  locks, with preflight hashes and backups. Native LLM installer exit 0; all
  historical prompt and protected source/input/model/review/release fingerprints
  remained equal. Receipt:
  `~/.local/state/jobtology-hop/document-packet-deploy-20260912T155537Z/`.

Reconstructed complete request sizes are below. They replace only the user
content of saved native requests; a fresh native preview is still required.

| Posting | Previous characters | Compact characters |
|---|---:|---:|
| 304429 | 200,838 | 119,162 |
| 304432 | 215,221 | 124,939 |
| 304713 | 279,668 | 159,547 |
| 304839 | 228,184 | 128,953 |

All 513 reconstructed requests fit the 200,000-character limit. Median size is
48,374; total is 27,004,525. This proves input preservation and planned size, not
that the model interprets rows, role scope or research-scoring rules correctly.

At the deployment checkpoint, the fresh native full EVAL preview was running under
`~/.local/state/jobtology-hop/document-packet-full-preview-20260912T155621Z/`.
It reuses the existing frozen `korean-attachments-sourcebound-v1-513` dataset;
`EXECUTE_REQUESTS=N` makes no provider calls. Supervisor PID 3989719 and native
child 3990288 were confirmed live by their recorded process start identities.
The logged batch ID is `d861198b-d282-4e6c-9963-d5ff10396189`; it was still in
input planning at the checkpoint, not a completed request inventory. Inspect
that exact receipt/handle instead of restarting because observation timed out.

Credit readback at 15:57:14Z on September 12: funded $8, usage $1.96006519,
remaining **$6.03993481**. No paid call was made for the encoding change or this
preview. A bounded same-three-posting Luna/ko-v7 evaluation with medium reasoning
was prepared to assess the changed request representation after native verification.
The prior pilot's seven partial source checkpoints remain outside model inputs.
Full transformation/linking, semantic review and release/query completion remain
open; no production acceptance or ontology activation was performed here.

### User hold and intentional preview stop

The user subsequently requested that attachment extractions be held and
documented. This overrides the planned attachment pilot and full expansion.
The exact native dry-run Java process was sent SIGTERM after verifying its PID,
start identity, dataset and `EXECUTE_REQUESTS=N`. The supervisor ended at
**15:58:40Z on September 12 / 00:58:40 KST on September 13** with FAILED from
that intentional stop. No paid pilot was launched.

Initial readback found batch `d861198b-d282-4e6c-9963-d5ff10396189` PLANNED with
zero request rows at that checkpoint. A later read-only check at **02:09:12 KST
on September 13** found 513 PLANNED request rows, no reservations, no responses
and **zero sent model requests**. The native/supervisor processes and active query were
gone, scheduler/LLM locks were released, and there were zero RUNNING enrichment
batches and RESERVED requests. `pause-request.json` and `pause-verification.json`
in the exact receipt preserve the stop reason and process/database evidence.

The durable operational record is
`~/.local/state/jobtology-hop/attachment-hold.json`. Attachment archives, parsed
text, structured inputs, outputs, review history and deployed fixes remain in
place. Six-source API/CSV refresh remains separate. Future agents must wait for
explicit user resumption before further attachment processing; see the
[pause scope, preserved results and restart handoff](attachment-status.md).
This is a deferred part of the full goal, not a completed ontology requirement.
The later verification receipt is
`~/.local/state/jobtology-hop/attachment-hold-verification-20260912T170912Z.json`;
it also confirms no attachment attempts or HWPX readers in flight. It preserves
the original stop receipt and hold record without rewriting their historical counts.

## Release read contracts deployed — 2026-09-13 KST

Attachment work remains on hold. The independent database read layer now provides
`ontology.query_summary_v1`, `query_entities_v1`, `query_entity_v1` and
`query_evidence_v1`, with matching native Hop `read_*.hpl` / `read_*.hwf` entry
points. See the [operator and response contract guide](../../hop/ontology/queries.md).

All public reads resolve one release. A blank choice uses only the active pointer,
never the latest draft. Normal reads require a previously activated, non-revoked,
verified release with no publication issues; an explicit preview is required for
PREPARING releases. Revoked/failed releases are rejected even for previews. The
existing publication gate remains closed; these functions do not activate a release.

Entities and related names follow their selected immutable revisions. Posting
details preserve extraction outcomes, review provenance, explicit position scope,
ordered condition trees, exact evidence references, per-link decisions and
separately reviewed rules. Evidence reads check release membership before returning
the original excerpt/offsets and source observation lineage. Empty accepted-claim
arrays do not imply unrestricted eligibility or a reviewed no-match outcome.

Entity pagination binds the release, kind and selected identity/revision set.
Summary fractions count review completion over every distinct selected posting;
an empty denominator produces null. These are factual operational counts, not
capability coverage, occupational demand or model-quality statistics. Typed
condition/concept resolution and the design's cohort/aggregate requirements remain
open, as do JSON-LD/SHACL and serving lifecycle integration.

Verification and deployment:

- `python hop/ontology/tests/query_contracts.py` passed in uniquely named,
  disposable PostgreSQL/Hop containers. Its synthetic inline-source fixtures
  cover all six source families, every posting outcome, later renamed sources,
  historical employer/name preservation, pagination/cursor isolation, independent
  extraction versus link rejection, NCS snapshot selection, Korean/emoji offsets,
  empty counts and unpublished/revoked read gates. It executed all four native
  read workflows and rejected invalid preview mode. No attachment-processing or
  model workflow ran. Log: `/tmp/jobtology-ontology-query-contracts.log`; tested
  package: `/tmp/jobtology-ontology-native-feg8b479/project`.
- A rolled-back local fixture simulated a published pointer only to exercise the
  read gate's success branch. It did not prove release activation or publish any
  production data. The publication gate and zero active releases were restored
  after the fixture; no test bypass was deployed.
- Ten public runtime files matched that exact tested package. Deployment preserved
  historical source, input, model, review, claim, evidence and release fingerprints,
  and the attachment hold file. Native ontology installer exit 0. Receipt:
  `~/.local/state/jobtology-hop/ontology-read-deploy-20260912T161025Z/`.
- Live native summary/entity-list/entity-detail reads finished with exit 0 at
  **16:12:22Z on September 12 / 01:12:22 KST on September 13**. Receipt:
  `~/.local/state/jobtology-hop/ontology-read-verify-20260912T161202Z/`.
  The existing `ontology-20260912-initial` draft accounts for **513 postings**,
  all correctly marked `SELECTION_PENDING`. Two five-record pages matched the
  independently selected revision IDs/names without duplication; source lineage
  was present. Published reads correctly rejected the absent active pointer and
  unpublished draft. Protected record fingerprints and the attachment hold were
  unchanged; **zero model calls**. No live evidence read was claimed because this
  draft has not assembled accepted production evidence; that path passed locally.

The read layer is available for inspection and future backend integration. No
backend was created. Full production extraction/review/linking and the remaining
ontology requirements in the completion table are still incomplete.


## Native JSON-LD interchange and SHACL profiles — 2026-09-13 KST

Attachment processing remains on hold. The independent interchange package now
provides the four artifacts required by implementation-plan §9.1:
`ontology/context.jsonld`, `ontology/shapes.ttl`, `ontology/terms.yaml` and
`ontology/mappings/`. The [interchange guide](../../ontology/README.md) documents
native Hop execution, the representation, validation commands and remaining
publication limits.

`ontology/export_jsonld.hwf` writes a fresh UUID-named UTF-8 file from a single
PostgreSQL statement snapshot. It requires a sealed inventory; explicit preview
allows a sealed draft, while the default requires an active published release.
It never seals or assembles an unfinished release as a side effect. Native IDs,
ordered arrays, every primitive property, evidence text and relationship
qualifiers remain recoverable. Direct RDF relations have identified relation
records, so ordinal/part-index information survives RDF set semantics. Schema.org
aliases are additional alignments; revisions remain selected by release.

The versioned contract is immutable in `ontology.interchange_contract`.
The standalone RDFLib/pySHACL checker verifies context/package and native hashes,
Schema.org aliases, graph membership counts and structural constraints. The
additional publication profile rejects missing occupation/observation, normalized
requirement, review and confidence fields. Those rejection checks supplement the
existing closed publication gate; they do not certify unimplemented conditions,
cohorts, support traces, lifecycle behavior or semantic completeness.

Verification:

- Focused native/RDF fixture: **156 nodes, 470 relations, 12,923 RDF triples**.
  Every decoded native field, ordered label, edge identity/qualifier and Korean
  evidence offset matched PostgreSQL. Different pinned NCS releases, replay,
  independent reviews, integer/decimal/list boundaries and deliberately altered
  evidence/Schema.org titles were checked. Two native exports received different
  UUID filenames and identical contents. Structural SHACL passed; incomplete
  publication data was rejected. Installer and native rejection cases passed.
  Log: `/tmp/jobtology-interchange-checks.log`; native fixture:
  `/tmp/jobtology-ontology-native-l66basam/`.
- Full saved-source fixture: cloned `ontologyrealtest` into a disposable database,
  preserving the original. Native Hop exported **182,670 nodes and 785,235 edges**
  using a 1,024 MB heap. Independent streaming readback recovered and checked
  every native object against PostgreSQL: **1,753,142 lines, 1,154,585,476 bytes**.
  Export SHA-256:
  `603c8dd497e3311625e1c68b570b0bcf0e8a4b57322b578825f4bf5932f69c84`.
  Log: `/tmp/jobtology-interchange-full.log`; detailed receipt:
  `/tmp/jobtology-ontology-native-jko93db8/full-export-verification.json`.
  This proves full native writing/content readback; **full-scale RDFLib/SHACL
  resource/performance validation is still pending**. The saved fixture includes
  synthetic reviewed claims and does not establish production semantic acceptance.
- Goldship deployment: six public runtime files matched the tested native package.
  The native ontology installer exited 0. Protected source/model/input/review,
  claim/evidence, graph and release fingerprints and the attachment hold file
  were unchanged. Receipt:
  `~/.local/state/jobtology-hop/ontology-interchange-deploy-20260912T164026Z/`.
- Live verification at **2026-09-13 01:41:27 KST**: installed artifacts matched
  the local package. SQL rejected an unsealed draft and an absent active release;
  the native export workflow also rejected the unsealed initial draft and wrote
  no file. Review/attempt counts and the persistent attachment hold were unchanged.
  Receipt: `~/.local/state/jobtology-hop/ontology-interchange-verify-20260912T164122Z/`.

No source/model/attachment requests were made. The initial live release remains
unsealed and PREPARING, with no active ontology release. Production review and
linking, typed conditions, observation/cohort/aggregate assembly, lifecycle and
refresh/retention publication integration remain required. This export milestone
does not mark the ontology goal complete.

## Posting history and source health — 2026-09-13 KST

Complete JOB-ALIO censuses, frozen lifecycle candidates, source freshness reads
and the source-refresh checkpoint hook are deployed. See the
[operator guide](../../hop/ontology/observations.md). Captured history now pins
the original snapshots against manual retention; history compaction is pending.

The native disposable test covered Korea's inclusive closing-date boundary,
explicit closure, one/two successful-run absences, failed/partial/replay exclusion,
empty snapshots, changed-content reappearance, immutable old reports, corruption
rejection, exact freshness boundaries and source-health failures, native first
execution/replay, the optional checkpoint hook and retention protection.
Log: `/tmp/jobtology-observation-checks.log`; tested package:
`/tmp/jobtology-ontology-native-oc8ax4q4/project`. All 14 deployed runtime files
matched that fixture. The installer exited 0 and protected source/model/review/
input/claim/graph/release fingerprints and the attachment hold were unchanged.
Deployment receipt:
`~/.local/state/jobtology-hop/ontology-observation-deploy-20260912T170118Z/`.

Live verification completed at **02:14:03 KST on September 13** under
`~/.local/state/jobtology-hop/ontology-observation-live-20260912T170317Z/`.
It prepared the separate `ontology-observations-20260913-62f37c70` draft from
the latest six accepted full snapshots. JOB run
`faa4ebe7-e422-4c9e-81d6-2216bbfcb98d` contains 513 postings; three retained
complete runs contain **545 distinct postings**. Independent readback of every
original API list/detail pair verified all derived states and retrieval times:
**513 ACTIVE and 32 EXPIRED**, with all 32 expired postings absent from the latest
snapshot. Replaying the freeze preserved its manifest. All selected source
watermarks were fresh at that check. Protected source, model, review, claim,
graph and earlier-release fingerprints were unchanged; zero model calls and no
attachment processing occurred.

This milestone retains historical outcomes as `HISTORICAL_NOT_ASSEMBLED`, with
no selected canonical revision yet. Canonical historical membership, observation
nodes in Neo4j/JSON-LD, cohort/aggregate assembly, production review/linking and
publication/lifecycle integration remain required. The new draft is PREPARING,
unsealed, and no ontology release is active. It is not a completed serving release.

## Historical revision and observation membership — 2026-09-13 KST

`bind_observations.hwf` now retains every observed posting in the release, including
postings missing from the current full snapshot. It freezes states at **release
creation time**, reuses exact content-addressed revisions, copies the last-seen
list/detail evidence, and records historical source runs separately from the six
current pins. The original candidate report remains immutable; the canonical
read is `read_posting_states.hwf`. See the [operator contract](../../hop/ontology/observations.md).

A release has exactly one `entity_observation_state` per posting. Its separate
content-run and connector-run IDs distinguish the last source content from the
run establishing current absence. State/revision/source membership and complete
hashes are included in the sealed graph manifest. Neo4j receives typed datetimes,
`FOR_ENTITY` and `SELECTS_REVISION` relations and the exact historical source
provenance. Unchanged content reuses existing reviewed claims and evidence;
changed content does not inherit an approval. Newer pending corrections and
rejected links remain explicit outcomes. No acceptance decision is made here.

The independent JSON-LD v2 contract includes those nodes and relations. It
preserves exact native timestamp strings for hash readback alongside typed RDF
datetimes, and verifies state identity/membership hashes, time ordering and
matching entity/revision/release endpoints. V1 artifacts and their exporter are
unchanged. The versioned declaration order is recorded explicitly so rebuilding
v2 reproduces the tested/deployed package byte-for-byte.

Verification:

- New disposable PostgreSQL/Hop/Neo4j fixture: seven postings, including six
  historical postings, **171 nodes, 512 relations, 14,231 RDF triples**. Exact old
  revisions, four reviewed claims, one reviewed NCS mapping and original evidence
  were reused. One/two absences, a changed-title reappearance, historical employer
  fallback, immutable earlier releases, tampered bindings, incompatible freeze
  time and late-binding rejection passed. Native graph replay added no duplicates
  and preserved a private fixture Person. Every native field/relation survived
  independent JSON-LD readback. Structural SHACL passed; publication still
  correctly rejected the missing occupation/condition/review requirements, with
  no observation-state violations. Altered datetime aliases were rejected.
  Log: `/tmp/jobtology-membership-final.log`; exact package and report:
  `/tmp/jobtology-ontology-native-lgumxwqy/`.
- Existing source assembly regression passed in a fresh database. Complete census,
  freshness, retention and refresh-hook checks passed again under
  `/tmp/jobtology-membership-observations.log`; fixture
  `/tmp/jobtology-ontology-native-eo6pgijo/`.
- V1 JSON-LD/native/RDF regression passed unchanged: 156 nodes, 470 relations,
  12,923 triples, including exact readback, replay and read gates. Log:
  `/tmp/jobtology-membership-legacy-interchange.log`; fixture
  `/tmp/jobtology-ontology-native-3y6hdsa8/`.
- Seventeen public runtime files matched the final passing fixture. Native
  Goldship installer exit 0; existing source, model, input, review, claim/evidence,
  graph, release and candidate-observation fingerprints and the attachment hold
  were unchanged. Only new membership tables/current-pin backfill and runtime
  definitions were added. Deployment receipt:
  `~/.local/state/jobtology-hop/ontology-membership-deploy-20260912T172445Z/`.

Full live source-only binding verification completed at **02:40:29 KST on
September 13** under
`~/.local/state/jobtology-hop/ontology-membership-live-20260912T172725Z/`, for
`ontology-history-20260913-f31190ec`. Its three complete JOB censuses account for
**545 postings: 513 ACTIVE/current and 32 EXPIRED/historical**. Independent
readback compared every canonical payload with the original API fields, every
employer relation with the detail-preferred source organization, and every
state/time/absence value with the original retrieval history. All postings now
have an exact selected revision. Native binding replay preserved its manifest;
native state and source-health reads passed, and all selected source watermarks
were fresh at verification. `verification.json` records the result.

Protected source/model/input/review/claim/graph and earlier-release fingerprints
and the attachment hold were unchanged. This live run did not freeze production
reviews, seal or load a production graph, call a model, or process attachments.
The new draft remains PREPARING and unsealed, with no document-input selection or
review freeze. The previous draft and all earlier work remain preserved. Native
Neo4j and v2 export verification above used the isolated synthetic fixture; a
final full production projection/export audit remains required.

Remaining: production semantic extraction/review/linking, typed target/condition
resolution, cohorts and aggregates, publication/rollback/revocation and refresh
integration, historical attachment-input selection after user resumption, and
full-scale final projection/export audits. Attachment work remains on hold and
no ontology release is active. This is not completion of the overall goal.

## Typed requirement PostgreSQL stage — 2026-09-13 KST

Attachment work remains on hold. A status-only confirmation of that hold did not
advance ontology completion; this continuation implemented the independent typed
requirement stage instead. Operator instructions and a real file format example
are in [the typed requirement guide](../../hop/ontology/requirements.md).

Implemented:

- Strict versioned input schema for all nine planned condition kinds plus an
  explicit `UNRESOLVED` result. Arbitrary fields, including caller/model confidence,
  are rejected. Unknown targets or unresolved conditions cannot be accepted.
- Canonical cross-posting requirement keys using SHA-256 of the condition schema's
  JCS subset. Sets are sorted/deduplicated; posting identity, review, necessity,
  polarity and source group are excluded. Original source language and the
  prescribed posting-filter fields remain available separately/on the condition.
- Release-selected target revisions with type checks, including full NCS unit
  identity, language skill kind, credential targets, experience contexts,
  proficiency levels, administrative codes and reviewed eligibility codes.
  Missing editorial concepts are not fabricated or silently treated as resolved.
- Append-only parented normalization proposals with exact source atom binding,
  Korean spans, position IDs and complete AND/OR/guard expression. Separate
  review records preserve actual human/assistant identity. Assistant reviews are
  not represented as human approval or calibrated automatic acceptance.
- Immutable release selection for every atom, including pending, rejected,
  unresolved and missing proposals. Later corrections/reviews cannot alter a
  frozen cut or fall back to an earlier approval. Changed/missing target revisions
  have an explicit mismatch outcome.
- Native Hop file import, review, live inspection, freeze/replay and frozen reads.
  PostgreSQL remains authoritative; the new typed records have not yet been
  integrated into the Neo4j/JSON-LD inventory or the full publication contract.

Verification:

- `python hop/ontology/tests/requirements.py` completed successfully using fresh
  disposable PostgreSQL and Hop containers. No provider/source/attachment calls.
- The existing reviewed-claim fixture also passed: six posting outcomes, EVAL
  exclusion, pending corrections, separate link reviews, nested logic, Unicode
  evidence and immutable prior selections.
- New checks covered all nine condition shapes and independent canonical key
  reconstruction, sorted/deduplicated sets, exact evidence/group preservation,
  bound ordering and empty-condition rejection, forbidden model confidence,
  immutable/replayed proposals, independent reviews, latest-pending selection,
  unresolved/missing target outcomes, language/NCS/proficiency/eligibility type
  checks, key/selection corruption, frozen source scope and confidence issues.
- Native import, review, inspection, freeze, replay and preview read passed.
  Reading a draft as published was rejected. Original source claims were
  unchanged; zero new attempts and zero active releases.
- Final fixture: `/tmp/jobtology-ontology-native-cinhknn8/`, including
  `requirements-report.json` and native logs. Local test log:
  `/tmp/jobtology-requirements-test.log`.

Live deployment:

- Receipt on Goldship:
  `~/.local/state/jobtology-hop/ontology-requirements-deploy-20260912T180258Z/`.
- Exactly **13 public files** matched the passing native fixture. Existing SQL
  dependencies matched the tested installer. Native `ontology/install.hwf`
  exited 0; a native preview read of `ontology-history-20260913-f31190ec`
  also passed. Its normalization stage correctly reports not frozen.
- Protected ingestion, source/revision/observation, model/input/review, claim,
  graph and release fingerprints were unchanged. The attachment hold was
  preserved. **Zero production normalization proposals, reviews or freezes**
  were created, and **zero provider calls** were made. Existing live drafts
  remain unsealed and unpublished.

Next requirements remain concrete: project these typed records and their frozen
membership to Neo4j and a new immutable interchange version; bind guarded-rule
semantics; implement calibrated assessment and publication checks; provide the
reviewed editorial catalogue and primary product occupations; finish production
semantic extraction/linking and versioned cohorts/aggregates; then verify release
activation, rollback/revocation, refresh and final full production readback.
Confidence is still null/`UNASSESSED`; a semantic `ACCEPT` alone does not satisfy
the planned confidence threshold. Attachment-aware work requires explicit user
resumption. The overall goal remains incomplete.

## Typed requirement graph and interchange v3 — 2026-09-13 KST

**Implemented and verified locally; live deployment is pending a fresh Tailscale
SSH identity check.** The earlier PostgreSQL normalization stage remains deployed.
The final graph package has not been written to the Hop server. Attachment work
remains on hold, and no paid/provider requests were made.

The projection now separates original Korean source groups, normalization
proposals, frozen per-atom review outcomes and reviewed typed requirements.
`normalizedRequirementClaim` identities include the selected decision, preventing
later review changes from overwriting older releases. All outcomes remain visible;
pending, unresolved, rejected and target-mismatch proposals do not become typed
claims. Exact atom/group, evidence-part, position, posting-revision and target
revision relationships are preserved.

Neo4j uses `HAS_TYPED_REQUIREMENT` for the direct posting-to-typed-claim path. In
JSON-LD v3 this is `jt:hasRequirement`; original groups use
`jt:hasSourceRequirement` and the `SourceRequirementGroup` class. V1/v2 retain
their original packages and reject the newer labels. Typed condition nodes retain
explicit null-field information, arrays and numeric values. Availability dates
and review/proposal times have typed representations without losing native hash
inputs. Language kinds are checked against the exact bound skill definition.

The graph manifest now includes normalization membership and a hash of every
frozen atom/outcome/typed-claim identity. Sealing/replay verifies this membership.
Stage-specific issues feed `ontology.publication_issue`, while the broader
`SERVING_CONTRACT_INTEGRATION_PENDING` gate remains. Confidence is not invented:
reviewed claims still have `UNASSESSED` confidence, and human/assistant review
states stay distinct.

Verification completed:

- `uv run --no-project --with-requirements ontology/requirements-validation.txt python hop/ontology/tests/requirement_graph.py`
  passed in fresh disposable PostgreSQL, Hop 2.19 and Neo4j 5.26 containers.
  It also runs the existing normalization and source-review checks.
- A complete synthetic Korean posting exercised all nine condition kinds through
  native graph loading/replay and v3 export: **176 nodes, 584 edges, 15,448 RDF
  triples**. Every exported native node/edge property and the manifest matched
  PostgreSQL. All nine typed requirements passed structural SHACL.
- A mixed-outcome fixture retained the original AND/OR/exception structures,
  two reviewed typed requirements, missing proposals and one explicit unresolved
  condition: **187 nodes, 546 edges, 15,004 triples**; native load/export and
  structural checks passed.
- A frozen target-mismatch fixture exported through PostgreSQL with no reviewed
  typed claims and no binding edge to an unselected target revision:
  **167 nodes, 493 edges, 13,585 triples**; structural validation passed.
- Independent checks rejected an altered RDF date alias, a wrong canonical
  requirement key and corrupted normalization membership during sealed replay.
  Draft publication validation failed as expected. The private fixture `Person`
  was preserved; projection added no model attempts and activated no release.
- Legacy v1 native export regression passed: **156 nodes, 470 edges, 12,923
  triples**. The v1/v2 contract files were not rewritten.

Final graph evidence is `/tmp/jobtology-ontology-native-8gdnc727/`, including
`requirement-graph-report.json`, export artifacts and native logs. The final log
is `/tmp/jobtology-requirement-graph-final.log`. Legacy v1 evidence is
`/tmp/jobtology-ontology-native-s9erxbc6/` and
`/tmp/jobtology-requirement-legacy-v1.log`. Regeneration reproduced all seven
deployment files byte-for-byte from the final passing native fixture.

Deployment handoff:

- Seven public files: `ontology/install.hwf`, SQL
  `015_requirement_graph_extra.sql`, `016_requirement_graph.sql`,
  `017_requirement_interchange_contract.sql`, `018_requirement_interchange.sql`,
  and `export_jsonld_v3.hpl` / `export_jsonld_v3.hwf`.
- Prepared helper/evidence directory:
  `/tmp/jobtology-requirement-graph-deploy/`. `deploy.py` verifies the passing
  fixture, exact live file hashes and installer dependencies, acquires the
  existing locks, backs up replaced files, installs only the seven public files,
  and compares protected data/older contracts/attachment hold before and after.
- The first execution ended at SSH verification with exit 255; it did not run
  the remote installation. `deploy.log` records the access failure. Verification
  retries also timed out before user completion. Use a fresh check at handoff,
  and inspect its exact process status before retrying deployment; an old URL
  or timeout does not establish authorized access.
- After access is verified, re-run the prepared helper, inspect its actual
  terminal result and remote receipt, then update this status. If files changed
  since preflight, inspect the change before updating hashes. Do not infer success
  from an SSH timeout, a local passing test or the presence of generated files.

Operator instructions are in [the typed graph/export guide](../../hop/ontology/requirement-graph.md).
The planned production semantic transformation/linking, calibrated assessment,
guarded-rule binding, editorial/product occupations, cohorts/aggregates and full
release lifecycle/audit remain unfinished. The live graph has not received these
typed records, and attachment-aware processing requires explicit user resumption.
The overall goal remains incomplete.

## Editorial product-occupation source — 2026-09-13 KST

**Implemented and tested locally; not deployed.** This work is independent of the
attachment hold. No attachment files were processed, no model/provider requests
were made and no production source, review, graph or active-release rows changed.

The plan's `AI_ENGINEER`, `BACKEND_DEVELOPER`, `FRONTEND_DEVELOPER` and
`DATA_ANALYST` now have an actual draft catalogue in
`hop/editorial/catalogues/product-occupations.v1.yaml`. It contains Korean display
names, descriptions, aliases and classification boundaries, under a separate
product occupation scheme. The definitions are explicitly assistant-authored;
there is no fabricated human review or Git merge. Existing NCS occupations keep
their NCS identities. No posting classifications or NCS equivalence links were
inferred from the catalogue.

The standalone `hop/editorial/` module provides:

- An immutable contract and exact-byte `INTERNAL_EDITORIAL` snapshot ledger.
  Native Hop reads a binary file field; PostgreSQL verifies SHA-256 and Git blob
  SHA-1 before JSON-subset YAML validation. Original bytes, complete parsed data,
  source pointers, five entity definitions and revision hashes remain saved.
- Native `install.hwf`, `import_catalogue.hwf`, `review_catalogue.hwf`,
  `inspect_catalogues.hwf` and `pin_catalogue.hwf` workflows using the existing
  `jobtology-postgres` connection and `ontology-local` run configuration.
- Independent append-only decisions with actual reviewer kind, required Git
  merge attestation for human acceptance, and a latest-decision rule. A new
  pending version cannot silently fall back to an older accepted version.
  Commit/merge references are operator attestations; Hop does not independently
  prove repository membership through a remote Git query.
- PostgreSQL release pinning of the current reviewed version, stable product
  identities, immutable revisions and source membership. Later imports/reviews
  do not reinterpret a frozen release. A changed version creates new revisions
  while retaining the same five entity identities.
- An explicit manifest guard: the existing graph sealer cannot silently omit
  a pinned editorial source. The matching editorial graph/JSON-LD adapter is
  **still unfinished**, and such a seal reports
  `EDITORIAL_GRAPH_INTEGRATION_REQUIRED`. This stage does not activate a release.

Verification: `python hop/editorial/tests/catalogue.py` finished with exit 0 in
fresh disposable PostgreSQL 18 and Hop 2.19 containers. Exact native file import,
idempotent replay, wrong hash and missing-file rejection, independent review and
release pinning passed. PostgreSQL checks also covered duplicate JSON keys,
invalid UTF-8, unknown fields, duplicate/missing role codes, whitespace-only
labels, same-version byte changes, self-review, missing merge evidence,
assistant-only acceptance, later rejection, newer pending versions, immutable
pin selection and membership tampering. The fixture ended with **2 snapshots,
5 stable entities, 10 revisions and 2 synthetic release pins**. Source ingestion,
model attempts and active-release counts were unchanged.

Evidence: `/tmp/jobtology-editorial-test.log` and
`/tmp/jobtology-ontology-native-17siwh_s/editorial-report.json`, alongside the
native workflow logs. The fixture's first catalogue Git blob matched the
independent `git hash-object --stdin` result:
`e29c0cadd528cd423742ae7128a378acd596dcb7`.
Its containers were removed on completion; these are local synthetic checks,
not live review or deployment evidence. The first test attempt caught an
ambiguous SQL parameter name in the review function; it was fixed before the
passing run.

The separate editorial generator/installer leaves all seven already-tested
ontology v3 deployment files byte-identical to the earlier final native fixture.
That deployment remains pending. The old SSH check handle was no longer present;
a fresh check in this turn ended with SSH exit 255 before verification was
completed. No remote installation ran. Request a fresh verification when the user
is available; do not reuse the expired URL or treat it as authenticated access.

Next requirements: real catalogue review/merge, editorial graph and interchange
support, the remaining actual editorial vocabularies/action templates, primary
posting occupations, reviewed/calibrated requirement and NCS links, cohorts and
publication lifecycle checks. The source contract in this stage covers only the
four product occupations and their scheme. It does not claim that the entire
planned editorial source or the overall ontology goal is complete.

Operator instructions and mounted file paths are in the
[editorial source guide](../../hop/editorial/README.md).

## Editorial graph and interchange v4 — 2026-09-13 KST

**Implemented and tested locally; not deployed to Goldship.** This completes the
graph/export adapter that was pending in the preceding source-ledger entry. It
does not establish real catalogue review, posting classification, serving
publication or overall ontology completion. Attachments remain on hold. No paid
model calls or production mutations were performed.

`hop/editorial/sql/003_graph_extra.sql` projects the exact catalogue text and file
hashes, five source-entry records, selected independent review, release selection
and source contract. The existing stable entity/revision projection adds the four
product occupations and their scheme. Explicit `DERIVED_FROM`, `IN_SNAPSHOT`,
`SELECTS_SNAPSHOT`, `FOR_SNAPSHOT`, `REVIEWED_BY`, `SELECTS_REVISION` and `IN_SCHEME`
relations preserve the selected source, review and taxonomy boundaries. Git merge
references remain explicitly `OPERATOR_REPORTED` and
`NOT_AUTOMATICALLY_VERIFIED`; loading them does not independently prove a Git merge.

The generated `004_graph_adapter.sql` extends the existing inventory and manifest,
verifies editorial membership on sealing/replay, and retains all broader
publication gates. It reports missing editorial membership and changes to the
current review/version for prospective publication, while saved historical graph
membership retains its selected review. Drafts without a pin keep the original
inventory. Install the editorial module after the ontology v3 installer; repeat
the editorial installer after any ontology reinstall because the ontology
installer restores its own graph function definitions.

The new immutable package is `ontology/versions/hop-v4/`, embedded by
`hop/editorial/sql/005_interchange_contract.sql`. `006_interchange.sql` and
`editorial/export_jsonld_v4.hwf` stream the exact sealed inventory through native
PostgreSQL/Hop. V4 carries the original editorial JSON-subset YAML source bytes
as UTF-8 text plus their byte length, SHA-256 and Git blob SHA-1. Its independent
validator reconstructs the source's five definitions and revision identities,
checks the selected review and source pointers, and retains the v3 typed
requirement checks. It also validates the source against the immutable embedded
catalogue contract. V1–v3 reject the new labels; they are not reinterpreted or
silently used to discard editorial evidence.

Verification command:

```bash
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python hop/editorial/tests/graph.py
```

The command finished with exit 0. It ran the preceding source/import/review/pin
suite and added fresh disposable Neo4j 5.26 alongside Hop 2.19 and PostgreSQL 18:

- Both complete catalogue versions loaded through native `load_release.hwf` and
  exported through native JSON-LD v4: **114 nodes and 342 edges each**, with
  **9,345 / 9,347 RDF triples**. Independent readback matched every native node,
  edge property and full PostgreSQL manifest. Both structural SHACL reports passed.
- Four stable product occupation identities retained two distinct revisions.
  Replaying the old release after loading the newer version preserved its
  original definitions, selected review and manifest. Neither run inferred NCS
  equivalence links or primary posting occupations.
- Independent semantic checks rejected changed source bytes and source pointers.
  The SQL verifier rejected corrupted editorial membership during sealed replay.
- A release without an editorial pin retained its exact base manifest and
  exported under v1: **94 nodes, 293 edges, 7,904 RDF triples**, with structural
  validation passing.
- V4 preserved frozen source-only requirement atom outcomes. This fixture did
  not contain all nine kinds of reviewed typed requirement; the earlier v3 suite
  remains the evidence for those normalization/graph cases.
- Draft publication validation failed as expected. The fixture private `Person`
  remained unchanged, provider-attempt counts did not increase, and no release
  became active. Fixture containers were removed after completion.

Evidence: `/tmp/jobtology-editorial-graph-test.log` and
`/tmp/jobtology-ontology-native-710pqzqt/editorial-graph-report.json`, with source
checks, native logs and exports in the same fixture directory. The seven pending
ontology v3 deployment files remain byte-identical to their earlier passing
fixture. No remote deployment was attempted in this turn; the prior SSH check
ended before verification and its URL must not be reused.

An additional read-contract gap was confirmed in `ontology.query_entity_v1`:
its `source_support` array covers external ingestion records, not the new
editorial membership. The catalogue's complete provenance is available in the
new graph/export and `editorial.revision_support`/`release_pin`, but the versioned
database reader still needs an editorial support contract. This remains explicit
work alongside actual catalogue review/merge, other editorial vocabularies and
templates, primary occupation decisions, calibrated claim/NCS links, cohorts,
publication lifecycle and production-scale audits. See the updated
[operator guide](../../hop/editorial/README.md#neo4j-evidence-and-json-ld-v4).

## Editorial provenance in v2 database reads — 2026-09-13 KST

**Implemented and tested locally; not deployed.** The missing editorial provenance
in the preceding entry's database reader is now available through explicit v2
contracts. The v1 functions and workflows retain their existing external-source
support representation. This is a PostgreSQL/native Hop change, not an HTTP
service or application backend. Attachments remain paused; no paid model calls
or production changes occurred.

`hop/editorial/sql/007_read_contracts.sql` adds:

- `ontology.query_summary_v2`: external source pins plus the selected editorial
  catalogue, its frozen review and verified five-entity coverage. The original
  six-source `data_as_of`, external coverage and posting counts are preserved.
- `ontology.query_entities_v2`: paginated identity/revision/name rows with scheme
  IDs and source-support counts. A scheme filter lists the four product roles
  separately from NCS occupations. Cursors bind release, kind, scheme, selected
  revision set and editorial membership; v1 cursors are rejected.
- `ontology.query_entity_v2`: selected definitions, tagged external/editorial
  support references and explicit catalogue `IN_SCHEME` relations. Existing
  posting details, claims, positions and mappings retain their v1 meanings.
- `ontology.query_source_record_v2`: exact catalogue bytes/text, original JSON
  entry/pointer, hashes and normalized definition for editorial records; frozen
  normalized data, lineage and all matching source observation references for
  external records. It accepts only source IDs selected by that release and does
  not fetch a file or expose a caller-selected filesystem path.

The shared v2 read gate verifies an editorial pin and, when sealed, its graph
projection. It preserves the existing active-pointer, preview, failed/revoked and
publication checks. Unpinned drafts return `NOT_PINNED` and explicit null editorial
source/coverage. An editorial revision added to a release without its source pin
fails. Reviews come from the frozen pin rather than the latest decision table;
Git metadata remains an operator attestation. Existing text-span evidence IDs
continue to use `query_evidence_v1` with the same release.

The native entry points are `editorial/read_summary_v2.hwf`,
`read_entities_v2.hwf`, `read_entity_v2.hwf` and `read_source_record_v2.hwf`, with
matching preview pipelines and the existing `ontology-local` configuration.
`editorial/install.hwf` includes the additive SQL file after the graph/export
adapter. The prior catalogue, graph and v4 interchange SQL files are unchanged.

Verification: `python hop/editorial/tests/read.py` finished with exit 0 in fresh
PostgreSQL 18 and Hop 2.19 containers. It repeated the native source/import/review
fixture and checked two catalogue versions, all four reader workflows and invalid
native read mode. SQL checks covered exact source byte/hash/pointer readback,
historical selected reviews, external record compatibility, seven-source summaries,
four-role pagination, scheme/release/v1-cursor mismatches, an unpinned draft,
adding an editorial pin between pages, orphaned editorial revisions, unselected
source records, corrupt membership/support, and unpublished/revoked read gates.

Reads preserved a fingerprint of the editorial source/review/pin tables,
ontology source/entity/revision/release tables, model batches/items/attempts and
attachment attempts. Final fingerprint:
`9cfd355db4d09de4b08c08587339749e5e4fa003cd616c0a866bdf4f22f111f6`.
This proves the tested read calls did not mutate those fixture ledgers; it is not
a production fingerprint or a claim that publication prerequisites passed.

Final evidence: `/tmp/jobtology-editorial-read-test.log` and
`/tmp/jobtology-ontology-native-eiaa8v0z/editorial-read-report.json`, with native
logs and the tested runtime package. The first passing run, before adding the
unpinned-draft/cursor-transition checks, is retained in
`/tmp/jobtology-editorial-read-first.log` and
`/tmp/jobtology-ontology-native-ne6ahyq8/`. Each test's own containers were removed
on completion; existing local databases and production were not reset.

Deployment remains pending; no new remote operation or SSH verification was
attempted in this turn. The prepared ontology v3 package must be deployed before
the editorial module. Remaining full-ontology requirements include real editorial
review/merge and additional vocabularies/templates, primary occupation decisions,
calibrated requirements and NCS links, guarded-rule binding, cohorts, publication
lifecycle and production-scale audits. The overall goal is still incomplete.
Operator examples and parameter details are in the
[v2 read guide](../../hop/editorial/queries.md).
## Primary product-occupation review stage — 2026-09-13 KST

**Local PostgreSQL and native Hop verification passed; not deployed.** This
independent work did not resume attachments, run a model or approve real data.
The overall serving-ontology goal remains incomplete.

`hop/editorial/sql/008_occupation_contract.sql` and
`009_occupation_resolution.sql` implement immutable proposals, independent
idempotent review decisions, release cutoffs, one explicit outcome per posting,
manifest verification and a primary-product-occupation view. The native workflows
are `import_occupation.hwf`, `review_occupation.hwf`, `freeze_occupations.hwf`,
`read_occupation_input.hwf` and `read_occupations.hwf`. All use the existing
PostgreSQL connection and `ontology-local`; there is no new runtime service or
Python ETL. The editorial installer remains separate from the pending ontology
v3 deployment, whose seven files still match their final tested package.

A proposal binds the selected posting revision, accepted extraction/review,
complete reviewed duty/position set, source spans and hashes, and every definition
in the pinned product catalogue. MATCH selects one product occupation; OUT_OF_SCOPE
and UNRESOLVED retain explicit accounting without forcing an unrelated posting
into the catalogue. MATCH/exclusion need accepted extraction, explicit duties and
cited duty evidence. NCS IDs cannot substitute for product occupation IDs.

Proposals must reference the latest parent. Later pending or rejected proposals
prevent fallback to an older acceptance in a new freeze. A changed extraction
review or duty set produces SOURCE_CHANGED; a changed catalogue produces
CATALOGUE_CHANGED, including for an earlier OUT_OF_SCOPE decision. The old frozen
release retains its selected decision and exact target revision. Review UUIDs
make identical retries idempotent and reject conflicting retries. Human and
assistant review remain distinct; neither manufactures calibrated confidence.

Source revision properties and existing entity readers are not rewritten with
these inferences. The primary assignment is exposed through the dedicated reader
and `ontology.primary_product_occupation`. The graph/interchange adapter for
occupation decisions is still missing. A manifest guard rejects sealing a newly
occupation-frozen release with `OCCUPATION_GRAPH_INTEGRATION_REQUIRED`, preventing
silent omission from the graph. Existing drafts without this new freeze preserve
the earlier graph behavior. This stage does not remove publication gates.

`python hop/editorial/tests/occupations.py` finished with exit 0 using uniquely
named disposable PostgreSQL 18 and Hop 2.19 containers. Eight synthetic Korean
postings cover four MATCHED roles, one OUT_OF_SCOPE nurse, one unaccepted extraction,
missing duties and mixed positions. Native install/import/review/read/freeze and
retry behavior passed. Checks also cover duplicate JSON keys, invalid schema and
source/catalogue bindings, omitted duties/positions, wrong evidence, wrong-scheme
targets, model provenance, independent review, stale parents, later pending/rejected
corrections, changed reviews/duties/catalogue, immutable membership, explicit
missing-prerequisite/read-mode errors and failed-seal rollback. Source revision
properties, original source records, provider attempts and attachment attempts were
preserved. Confidence remained null/UNASSESSED, with no active release.

Final evidence: `/tmp/jobtology-occupation-final.log` and
`/tmp/jobtology-ontology-native-3fqsrph3/occupation-report.json`, including native
logs and the exact staged runtime package. The source/provider/attachment fixture
fingerprint remained
`65b26f9c5af04c81c2538049f94df8b2d75b62b97d8dfa32aa0d454b624f0fe4`.
The first run caught the input reader returning an all-null object instead of
JSON null when no proposal exists; that was corrected. The final run also checked
whitespace-only model provenance and changed extraction duties. Test containers
were removed; no live database or existing local test database was reset.

Remaining work includes deploying the tested packages after SSH verification,
real catalogue review, production occupation decisions, occupation graph/export
support, other editorial vocabularies/templates, typed and calibrated requirement/
NCS/rule interpretation, cohorts, publication lifecycle and full production audits.
Attachment-dependent work stays paused until explicit user resumption. See the
[operator guide](../../hop/editorial/occupations.md) for exact input fields, review
parameters, outcome semantics and manual loading steps.

The fresh Tailscale SSH check in this turn was polled on its exact process handle
and ended with exit 255 (connection timed out) before authentication completed.
No remote installer ran. The emitted check URL is expired; obtain a new check
when the user is available rather than reusing it or assuming access is verified.

## Primary product-occupation graph and JSON-LD v5 — 2026-09-13 KST

**Passed local native PostgreSQL/Hop/Neo4j and independent RDF checks; not
installed on Goldship.** This completes the local graph/export adapter for the
preceding occupation review stage. It does not complete production classification,
calibration, serving publication or the overall ontology goal. Attachments remained
paused; no provider call, live review or remote deployment ran in this turn.

`hop/editorial/sql/010_occupation_graph.sql` adds frozen selection, proposal,
review, binding and primary-occupation assertion nodes. Exact historical source
and catalogue objects are represented by typed value trees, preserving object
keys, ordered array indices, scalar types, nulls and empty collections. Identical
bindings share content identities. Changed-source/catalogue proposals remain
inspectable without promoting their old evidence to current accepted claims.

Only MATCHED selections produce `primaryOccupationClaim` assertions. They retain
the exact posting revision, product occupation and catalogue revision, selected
review and cited evidence. A generated `FOR_OCCUPATION` shortcut carries the
source assertion IDs and receives the loader's release ID. Other outcomes produce
no primary occupation link. Source revisions and NCS mappings are not rewritten.
Human and assistant reviews stay distinct and confidence remains UNASSESSED.

`011_occupation_graph_adapter.sql` composes these nodes/edges and membership
hashes with the existing source, requirement and editorial inventories. Sealing,
replay and export verify the occupation selection and projected content. The
manifest-omission guard remains enforced; the new adapter supplies the required
membership. Additional publication issues cover a missing occupation freeze,
unresolved/out-of-scope outcomes and uncalibrated assignments, while retaining
all earlier publication gates.

`012_occupation_interchange_contract.sql`, `013_occupation_interchange.sql` and
`editorial/export_jsonld_v5.hwf` provide immutable v5 export. The package under
`ontology/versions/hop-v5/` includes both catalogue and proposal schemas. Older
v1–v4 packages remain unchanged and reject new labels when used on an
occupation-bearing graph. The offline verifier reconstructs the binding objects,
proposal/decision rows and frozen manifest hashes, checks current vs stale input
outcomes, validates target revisions and evidence, and verifies every shortcut's
assertion support independently of the generic native node/edge content hashes.
It does not independently certify a reviewer's real-world identity or semantic
model quality.

Verification command:

```bash
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python hop/editorial/tests/occupation_graph.py
```

The command finished with exit 0. Eight synthetic Korean posting fixtures passed
the prerequisite native import/review/read/freeze checks, followed by:

| Fixture | Nodes | Edges | RDF triples | Primary links | Structural result |
|---|---:|---:|---:|---:|---|
| Original reviewed occupations | 910 | 2,080 | 55,869 | 4 | PASS |
| Changed duties/reviews/catalogue | 906 | 2,048 | 55,149 | 0 | PASS |
| Editorial source without occupation freeze, v4 | 199 | 604 | 16,589 | 0 | PASS |
| Source/claim inventory without editorial pin, v1 | 179 | 555 | 15,146 | 0 | PASS |

Both v5 publication profiles correctly failed. Native Hop loaded and verified
all Neo4j values/memberships and wrote both streaming exports. Independent readback
matched every PostgreSQL node property, edge and manifest. Reloading the original
release after the changed release preserved its inventory and did not add graph
objects or edges. Altered bound duty text, incorrect shortcut assertion IDs and
changed PostgreSQL graph properties were rejected. Activation remained blocked.
Private Person data and model/attachment/proposal/review history were preserved.

Evidence: `/tmp/jobtology-occupation-graph-test.log` and
`/tmp/jobtology-ontology-native-4nn23l0o/occupation-graph-report.json`, alongside
native logs, JSON-LD files and the tested package. Protected fixture fingerprint:
`b95d7a2361b35ccdb23e711638196ffe9f9e9e41a8107fd04a93252a9daae42b`.
Uniquely named PostgreSQL 18, Hop 2.19 and Neo4j 5.26 containers and their internal
network were removed afterward. These checks do not claim validation against
Goldship's actual Neo4j 2026.06 runtime or the complete production corpus.

After the passing run, two operator status messages were updated to say graph
loading and serving activation require separate steps; no SQL control flow or
projection/export logic changed. The new graph SQL and all immutable contract
artifacts still match the native fixture. Documentation links, Python compilation,
workflow XML and whitespace checks passed.

Deployment remains pending. No fresh SSH check was requested in this turn after
the previous check expired. Deploy the prepared ontology v3 package first, then
the editorial module, with exact public-file preflight and protected-state
readback. Real catalogue review/merge, production occupation assignments,
additional editorial vocabularies/templates, calibrated typed requirements and
NCS links, guarded-rule binding, cohorts, serving-scope/publication lifecycle and
full production audits remain open. Attachment-dependent work cannot resume
without the user's explicit instruction. Manual parameters, Cypher inspection
and export commands are in the [occupation graph guide](../../hop/editorial/occupation-graph.md).

## Derived-claim database reads — 2026-09-13 KST

**Locally tested; not deployed.** This stage adds
`editorial/sql/014_derived_reads.sql` and four native PostgreSQL readers:
`read_summary_v3`, `read_entity_v3`, `read_derived_claims_v1` and
`read_derived_claim_v1` (each has `.hwf` and `.hpl` artifacts).
The editorial installer includes the new SQL after its existing modules.
Manual parameters, result fields and SQL examples are in the
[derived-claim read guide](../../hop/editorial/derived-queries.md).

Entity reads retain the v2 source payload, claims, mappings and other fields,
then add the selected primary occupation, requirement outcomes and a paginated
list of derived facts. Single-claim reads include the selected proposal/review,
exact source binding and evidence, target revisions/payloads, source supports
and stable graph IDs. Requirements retain original position scope and expression
trees. Manual and model provenance remain distinct; confidence stays null and
UNASSESSED. No source field is overwritten with an inferred value.

Only frozen REVIEWED normalizations and MATCHED occupations enter the derived
list. An unfrozen stage is distinguished from a frozen stage with no accepted
results. Requirements can be read without an editorial pin. Reads verify frozen
memberships, retain published/preview/revocation gates and reject stale,
unselected or unknown claim IDs. Pagination binds the selected release, filters
and both derived memberships, including when a new freeze is added to a draft.
Publication issues and unresolved review outcomes remain visible.

Verification commands finished with exit 0:

```bash
python hop/editorial/tests/derived_reads.py occupations
python hop/editorial/tests/derived_reads.py requirements
```

| Fixture | Selected derived facts | Evidence retained |
|---|---|---|
| Combined occupation/requirement fixture | Four primary occupations plus one normalized experience condition; both kinds on the same posting | Exact Korean spans, source duties/positions, selected catalogue version/review, target names/revisions and manual/model distinctions |
| Requirement fixture without editorial pin | Two accepted normalizations | Experience and credential condition, exact target revision, source atom index, position scope and nested AND/OR structure |

Both ran all four native readers, rejected invalid preview/page parameters and
verified pagination, stale/pending/rejected choices, failed/revoked reads, missing
memberships and preservation of source payloads. Sealed previews were exercised;
no fixture was activated. Each read suite preserved fingerprints across 115
tables in ontology, editorial, ingestion, enrichment and attachment schemas.
Tests use synthetic inline sources and independent fixture decisions, not real
human catalogue approval. An initial combined test input was rejected for its
invalid expression tree; the fixture was corrected before the final passing run.
The runtime SQL did not need a change for that fixture correction.

Final evidence:

- Combined native log: `/tmp/jobtology-derived-combined-read-test.log`;
  fixture `/tmp/jobtology-ontology-native-87piisg2/derived-read-report.json`;
  read fingerprint `74863a73ccbddf434dcce39921e084a9ac2cf59b22d17023146e0e9ae28629bb`.
- Requirement native log: `/tmp/jobtology-derived-requirement-read-test.log`;
  fixture `/tmp/jobtology-ontology-native-aqq78bu3/derived-read-report.json`;
  read fingerprint `452b61ab384c06b28bc9aa1d1498a6f11f478e3342698e0d52e4d1160cd1a6dd`.
- An earlier occupation-only run also passed under
  `/tmp/jobtology-ontology-native-98w_f8ba/`; the final combined fixture extends
  its coverage. Default occupation/graph fixtures retain their original source
  setup; only the derived-reader test opts into the added requirement.

The ten new/updated reader and installer runtime files match the passing native
packages. The prepared seven-file ontology v3 deployment package also remains
identical to its previous passing fixture. XML, Python compilation, document
links and whitespace checks passed. Disposable test containers/networks were
removed by their drivers. There were no provider calls or production changes.

A fresh SSH verification attempt was made for Goldship. It reached Tailscale's
authentication check but timed out with exit 255 before verification completed;
its link/session is expired. No server deployment or current credit check was
performed. A new authenticated connection is required before live preflight and
deployment. Production reviews, editorial vocabularies, calibration, guarded-rule
binding, cohorts, publication lifecycle and full production audits remain open.
The attachment hold remains in effect and is not lifted by this progress.

## Reviewed duplicate groups for cohorts — 2026-09-13 KST

**Locally tested; not deployed.** The cohort rules require reversible duplicate
groups as well as reviewed occupation and eligibility scope. Inspection found no
existing duplicate ledger. It also confirmed that the current source contract has
textual recruitment/region fields rather than structured country, locale or
experience bounds. This stage implements the independent duplicate prerequisite;
it does not assume that every JOB-ALIO posting is domestic or entry-level.

The new public module is `hop/cohorts/`, with a separate native installer,
immutable JSON proposal contract and PostgreSQL ledger. It supplies
`import_duplicate.hwf`, `review_duplicate.hwf`, `freeze_duplicates.hwf`,
`read_duplicate_input.hwf` and `read_duplicates.hwf`, each with its pipeline.
The [operator guide](../../hop/cohorts/README.md) gives container paths, parameters,
template preparation, review/correction steps and remaining cohort requirements.

Proposals bind complete selected posting revisions and original source support.
Independent decisions are append-only and have idempotent UUID retry semantics.
Group UUIDs remain stable across corrections; proposal IDs omit release context
while retaining exact bound evidence. Release freezes pin proposal/review cutoffs,
every relevant outcome and one assignment per selected posting. Accepted groups
share a group ID; all other postings remain distinct source identities. That
default does not assert that no undiscovered duplicate exists.

Overlapping accepted groups reject the entire freeze, without inventing an
unreviewed transitive union. Changed or missing source members invalidate reuse;
an unchanged content revision can reuse an old decision after a fresh observation.
Pending/rejected corrections do not fall back to an older acceptance. Replacing
or rejecting a group leaves older releases and all original source records intact.
Human and assistant review remain distinguishable and confidence stays UNASSESSED.

A manifest guard rejects sealing a duplicate-bearing release without its
duplicate membership. The current graph/interchange adapter is not implemented;
do not bypass the guard with a hand-edited manifest. Installing the module alone
does not add freezes or change legacy source-only graph sealing. No source
refresh, LLM or attachment scheduler was added.

Final verification command finished with exit 0:

```bash
python hop/cohorts/tests/duplicates.py
```

The synthetic fixture kept all five original postings, selected four groups
(one accepted two-posting group and three singletons), and verified:

- Native import/review retries, independent review, strict source/schema checks,
  duplicate JSON-key rejection and actor/model provenance checks.
- Atomic rejection of overlapping groups with no partial freeze rows.
- Stable group reuse across fresh source observations and stable proposal IDs
  when identical evidence is imported through another release.
- Explicit SOURCE_CHANGED, MEMBER_OUTSIDE_RELEASE, PENDING and REJECTED outcomes.
- Replacement membership in a later release while the original release retains
  its first selected members and review.
- An empty source release with FROZEN membership and zero members/groups;
  an unchanged legacy source-only graph seal; rejection of a late duplicate freeze.
- Source/proposal/member/membership integrity checks, published/preview/failed/
  revoked read gates, and native read/install replay without ledger mutation.

Evidence: `/tmp/jobtology-duplicates-native-verified.log` and
`/tmp/jobtology-ontology-native-qljnfjan/duplicate-report.json`.
Protected read/install fingerprint:
`5488559b6014c4570965c16d4fab6879ebc04407e723e6e78ad240582ddb4d85`.
The retained native fixture contains the exact runtime package and execution
logs. The test owned disposable PostgreSQL 18/Hop 2.19 containers and an internal
network, removed afterward. An earlier test expectation used a more specific
sealed-release error; it was corrected to the existing shared guard's error
before the final passing run. No guard was weakened.

There were zero provider calls, attachment attempts, production changes or real
review decisions. No fresh SSH check was requested after the preceding turn's
verification expired; deployment and current credit inspection remain pending.
The full goal remains incomplete: country/experience and mixed-position scope,
language/window filters, representative ranking, cohort/aggregate support and
graph/interchange integration still need implementation, alongside production
review, calibration, editorial vocabularies, guarded rules, publication lifecycle
and final audits. Attachment work remains paused until explicit user resumption.

## Reviewed country/experience and position scope — 2026-09-13 KST

Attachment processing remains paused. The new native profile stage prepares
country, total experience and position-scoped claim selections needed by the
cohort specification. It is **implemented and tested locally, not deployed**.
The [operator guide](../../hop/cohorts/profiles.md) explains the run order and
exact citations; the real-data and ontology guides link to it.

`hop/cohorts/` now includes a strict profile contract, append-only proposal/review
ledger, release-frozen selections/membership, and five native workflow/pipeline
pairs: read input, import, independent review, freeze and read profiles. The
existing cohort installer installs both duplicate and profile ledgers. There is
no scheduler, external model request or runtime Python transform.

Profiles bind to the exact selected source revision, input, extraction review,
positions, requirement atoms and typed requirement decisions. Source fields are
not rewritten. Every resolved profile accounts for every reviewed position and
every applicable or unresolved source atom. A full-position selection requires
all applicable requirements to be reviewed and included; a reviewed subset
requires exact scope evidence and cannot borrow another position's claims.

Known labels, countries and experience policies require exact normalized-field
citations with Unicode code-point offsets. Missing bounds remain null. Supplied
month bounds must occur in reviewed, positive, required total-experience claims;
preferred, negated and context-specific experience cannot supply the cutoff.
Experience references used by a subset must be included in that subset. A
domestic subset does not bypass senior experience, and a claimed entry subtrack
cannot retain a positive minimum experience bound.

Selected outcomes include NOT_PROPOSED, EXTRACTION_NOT_ACCEPTED, UNRESOLVED,
SOURCE_CHANGED, PENDING, REJECTED and REVIEWED. Import/review retries are
idempotent, corrections require the latest parent, and a pending correction
never falls back to an earlier acceptance. Re-reviewing source extraction or
typed requirements invalidates reuse in a new release; historical membership
and its evidence remain unchanged. Confidence remains null/UNASSESSED.

Verification completed with exit 0:

```sh
python hop/cohorts/tools/build.py
python hop/cohorts/tests/profiles.py
python hop/cohorts/tests/duplicates.py
```

The profile fixture contains nine synthetic Korean postings: explicit new
graduate, separate junior/senior roles, unknown country/experience, unaccepted
extraction, no reviewed positions, overseas work, mixed-country senior work,
unresolved requirement scope and unrestricted experience. It selected seven
reviewed profiles and three qualifying tracks. The mixed posting contributed
only junior claims. Null and 24/25-month boundaries, NFC/CRLF/emoji citations,
wrong or missing evidence, foreign references, provenance, self-review, changed
decisions, stale parents, frozen selection integrity and public/draft/revoked
read gates were checked. Native imports, reviews, freeze, readers and installer
replay passed. A legacy release without profile membership still sealed; a
manifest omitting frozen profiles failed explicitly.

Final profile evidence:

- `/tmp/jobtology-profiles-native-verified.log`
- `/tmp/jobtology-ontology-native-c19ie52g/profile-report.json`
- Read/install fingerprint:
  `2e1d028fa950b0c02da54ef84992471407946fb91eafc1020d5855c629395ae1`.

Duplicate regression evidence with the expanded installer:

- `/tmp/jobtology-duplicates-with-profiles-native.log`
- `/tmp/jobtology-ontology-native-cm8a3nl8/duplicate-report.json`
- Read/install fingerprint:
  `6edfa90f38e29be59eee598394f1fbda50d979306634018e3c454b031bc84288`.

All 28 runtime/schema artifacts matched both final staged packages byte for
byte. Both tests used fresh owned PostgreSQL 18/Hop 2.19 containers and internal
networks, removed afterward. Initial native runs caught a reserved SQL parameter
name and an ambiguous PL/pgSQL alias; both were fixed before passing runs. The
final run additionally checked the strengthened mixed-entry bound guard. No
validation was relaxed to make a fixture pass. Python compilation and tracked
diff whitespace checks passed.

There were zero provider calls, attachment attempts, real review decisions or
production changes. No SSH session was started and no fresh credit balance was
queried. This work does not resume attachment processing or establish serving
readiness. Country/experience/scope eligibility remains one prerequisite, not a
persisted PostingCohort or demand denominator.

The next cohort implementation must join these profiles to frozen product
occupations and duplicate groups, apply the exact source/language/KST window
rules, select deterministic representatives, and persist all inclusion/exclusion
and aggregate support. Duplicate/profile/cohort graph and interchange adapters
must preserve those memberships before graph sealing. Deployment, production
reviews and linking, remaining editorial vocabularies, calibration, guarded
rules, publication lifecycle and final production audits also remain open.

## Persisted posting cohorts — 2026-09-13 KST

The cohort builder is **implemented and tested locally, not deployed**. Its
[operator guide](../../hop/cohorts/cohorts.md) documents dependencies, parameters,
filter evidence, pagination, current counts and publication limits.

`cohorts/install_builder.hwf` installs three additive SQL files after editorial
and cohort preparation are installed. `build_cohort.hwf` creates one immutable
cohort for a release, product occupation and KST `AS_OF` date. The filter fixes
JOB-ALIO, KR/reviewed experience scope, an inclusive 180-date window and Korean
content. It uses only qualifying track claims and chooses one deterministic
representative among eligible duplicate-group members. Every source identity,
exclusion reason, group/representative, source/review selection, language metric
and date/ordering basis remains stored. Claim support uses normalized rows.

Language checking records exact normalized title/body field hashes and counts,
with 100 Hangul syllables and a 30% letter-ratio threshold, or an explicitly
provided Korean source locale. No locale is inferred from the API. PostgreSQL
`pg_c_utf8` collation version 1 supplies Unicode letter classification; emoji,
digits and punctuation do not count as letters. The description adapter uses
existing inline API fields, with no attachment reads or generated summaries.

Temporal ordering records the source field and precision. A date-only posting
keeps a null actual timestamp and a separately marked KST day-start ordering key.
The precedence is source-modified instant, source-published instant/date, then
retrieval instant; ties use source priority and lexical posting ID. Malformed
ordering timestamps remain exclusions.

`read_posting_cohort.hwf` separates the fixed historical count from active/fresh
counts evaluated at `AS_AT`. Deadlines are reevaluated against release-bound
observations, and both posting observation and selected source watermark must
be within the JOB-ALIO 30-hour freshness window. `read_cohort_members.hwf` pages
all decisions and track/claim support with an opaque, manifest-bound cursor
that works through native Hop startup parameters. No demand ratios are emitted.

Final verification command, exit 0:

```sh
python hop/cohorts/tests/cohorts.py
```

The 29-posting synthetic fixture yielded eight historical members, three
duplicate non-representatives and 18 exclusions. Six members were initially
active/fresh; the freshness boundary reduced that count to zero without changing
membership. Exactly two junior-track claim support rows came from the mixed
posting, with no senior claims. Tests covered both date boundaries, missing
dates, language thresholds and Unicode, timestamp precedence/precision, lexical
ties, ineligible newer duplicates, unresolved reviews, another occupation,
empty cohorts, replay, paginated native reads, corrupt member/track/support
rejection, and the graph-membership omission guard. Missing installation
dependencies were explicitly rejected.

Evidence:

- `/tmp/jobtology-cohort-native-verified.log`
- `/tmp/jobtology-ontology-native-mzm4yx_s/cohort-report.json`
- Protected read/install fingerprint across ontology, editorial, ingestion,
  enrichment and attachment tables:
  `22a892275c72b76f922435fe80d5abf79cc0b3d3741b03e555fba95300664e4b`.

The final staged package matched all 57 editorial and 38 cohort runtime/schema/
catalogue artifacts. The earlier 28-file cohort preparation package remained
byte-identical to both passing profile and duplicate fixtures. An earlier full
run also passed; the final run added editorial tables to the protected
fingerprint and checked the exact missing-dependency error. The first fixture
attempt used an invalid source date rejected by the existing ingestion view;
the fixture was corrected and malformed-date parsing retained as a separate
helper check. No ingestion or review guard was relaxed.

All tests used fresh owned local containers, removed afterward. No provider call,
attachment attempt or production review occurred. Demand aggregates, minimum-30
ratio handling, calibration, graph/interchange integration and publication remain
unfinished. The builder does not certify full extraction or serving readiness.

## Typed graph/export v3 live deployment — 2026-09-13 KST

The user completed Tailscale verification. A fresh SSH command succeeded, and
the previously tested seven-file requirement graph/export package was deployed
to the existing Hop project on Goldship. The deployment checked exact old hashes
and installer dependencies, held the refresh/LLM locks, backed up the replaced
installer, and atomically installed public files. Private connection metadata
and credentials were not copied or changed.

Native `ontology/install.hwf` and a draft requirement read exited 0. Readback
confirmed the v3 contract hash, unchanged v1/v2 interchange contracts, unchanged
legacy draft graph manifest, and unchanged protected source/model/input/review/
graph/release data. The attachment hold was byte-identical afterward. Production
typed proposals and reviews remain zero; the deployment made no provider calls
and created no typed graph nodes for the unchanged draft.

Receipt on Goldship:
`~/.local/state/jobtology-hop/ontology-requirement-graph-deploy-20260912T205128Z/`.

The receipt's `verification.json` and `projection-readback.json` were read back
over SSH after the deployment process exited 0. Local copies are in
`/tmp/jobtology-requirement-graph-deploy/live-readback.json`. This deployment does
not include the editorial or cohort modules, accept real data, or activate a
completed ontology release.

## Wrap-up handoff — 2026-09-13 KST

The user asked to **wrap it up for now** after receiving the remaining-work
status. Stop further work until explicit user resumption; preserve the separate
attachment hold. No further module deployment or processing batch was started.

- Source ingestion, refresh, PostgreSQL/Neo4j source loading and manual retention
  remain available from the earlier migration work.
- The typed-requirement graph/export v3 package is now deployed and verified as
  above. The completed deployment process has exited; no deployment is pending.
- Editorial source/review, primary occupation assignment, v4/v5 graph/export,
  derived readers, duplicate/profile ledgers and the cohort builder are tested
  locally but **not deployed**. The 95-file editorial/cohort runtime manifest at
  `/tmp/jobtology-cohort-runtime-manifest.json` is local preparation only.
- Local native test processes completed and their owned containers were removed.
  No new real extraction review, NCS link acceptance, cohort or active release
  was created. There were no paid calls and no current credit query in this turn.

Remaining full-goal work includes deploying the ready modules, production job
transformation/review/NCS linking, remaining controlled vocabularies and rule
handling, demand statistics, duplicate/profile/cohort graph and interchange
integration, calibrated acceptance, publication/refresh/rollback lifecycle and
final production audits. Attachment-dependent coverage is intentionally deferred.
The code and source ingestion are not evidence that this production ontology is
complete; no completion percentage or ETA was established.

On resumption, first inspect this handoff and the attachment hold, then revalidate
the current worktree and server state. Do not reuse an expired SSH check or
restart a prior stopped batch from a status file alone. No commits or pushes were
made as part of this wrap-up.
