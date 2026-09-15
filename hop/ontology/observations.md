# Posting observations and source freshness

This native Hop/PostgreSQL layer preserves **complete JOB-ALIO snapshot censuses**
and freezes lifecycle candidates for a draft release. It does not call a provider
or model, parse attachments, accept claims, or activate a release. Attachment work
remains [on hold](../../docs/hop-migration/attachment-status.md).

The original candidate report preserves historical postings missing from the
selected snapshot. The newer `bind_observations.hwf` binds all of them to exact
canonical revisions and source evidence, and includes their observation nodes
in the Neo4j inventory and JSON-LD v2. Neither workflow makes a release active.
The original candidate report remains immutable: `HISTORICAL_NOT_ASSEMBLED` and
a null revision there describe its pre-binding state. Use `read_posting_states.hwf`
for the canonical binding after that step succeeds.

## Run in Hop

Install `ontology/install.hwf` with `ontology-local`. The installer adds the
observation ledger, retention protection and optional source-refresh checkpoint
hook. Source-only installations can still use `operations.sql` without ontology.

| Entry point | Parameters | Result |
|---|---|---|
| `capture_posting_census.hwf` | `RUN_ID`: exact accepted JOB-ALIO full snapshot | Append its complete paired list/detail census; replay verifies it without adding observations. |
| `freeze_observations.hwf` | `RELEASE_ID`; optional `EVALUATED_AT` | Freeze available accepted full history through the release's selected JOB snapshot and derive current/historical outcomes. |
| `bind_observations.hwf` | `RELEASE_ID` | Freeze at release creation time and bind every observed posting's exact current or historical revision. Run before document inputs or review selection. |
| `read_observations.hwf` | `RELEASE_ID`, `PREVIEW=Y` for a draft | Preview frozen metadata, state counts and every historical/current posting at `Preview JSON here`. |
| `read_posting_states.hwf` | `RELEASE_ID`, `PREVIEW=Y` for a draft | Read canonical state IDs, selected revision IDs, original content run, latest connector run, times, states and names. |
| `read_source_health.hwf` | `RELEASE_ID`, `PREVIEW=Y` for a draft | Preview current operational health and freshness of both selected and latest successful source snapshots. |

Prepare and assemble a new source release with `prepare_release.hwf` before
freezing observations. `EVALUATED_AT` defaults to the time of the first freeze;
an explicit value must include its UTC offset, for example
`2026-09-13T02:00:00+09:00`. It cannot precede completion of the selected snapshot.
Replaying the workflow with a blank time reuses the frozen time and history.
Changing the time requires a new release. An already sealed release cannot be
modified by this workflow.

For canonical assembly, prepare a **new** release, then run
`bind_observations.hwf` directly. It freezes observations at that release's
`created_at`, as required by the canonical contract; no separate manual freeze
is needed. A candidate preview already frozen at a different instant cannot be
retimed: preserve it and use a new release. Bind before `assemble_reviewed.hwf`.

Successful `operations/refresh_job_alio.hwf` runs capture their complete census
through the existing graph checkpoint. Recovery via `export_pending.hwf` uses
the same hook. Capture and the checkpoint commit together; a census error leaves
graph recovery pending rather than changing an accepted source run to FAILED.
Other source graph checkpoints retain their existing behavior.

The scheduler still performs only source ingestion/loading and census capture.
It does **not** freeze ontology releases, run enrichment or process attachments.
Direct source-only `ingestions/job_alio/full.hwf` runs do not immediately call the
graph checkpoint; an explicit census capture or subsequent observation freeze
can capture those accepted runs later.

## State rules

Hop's validated `FULL`/`READY` run corresponds to the design's successful complete
refresh. Eligibility depends on its full scope and successful validation, not
whether cron or a person started it. `SMOKE`, `REPLAY`, failed, incomplete and
review-pending runs do not advance absence counters.

| Condition, in precedence order | State |
|---|---|
| The last observed source explicitly says closed | `CLOSED` |
| The last observed closing date has fully elapsed in Korea | `EXPIRED` |
| Missing from at least two consecutive successful full snapshots | `NOT_SEEN` |
| Otherwise | `ACTIVE` |

A date-only closing date includes its entire Korean calendar date. For example,
September 1 expires at September 2 00:00 KST, not at the beginning of September 1.
One missing snapshot leaves the prior open/unknown posting active with
`consecutive_absence_count=1`. A later sighting resets the counter, updates the
last-seen time and uses the newly selected content revision. Earlier frozen
releases retain their previous state and revision choice.

`ACTIVE` here means no observed closure, elapsed known deadline or two-run
absence. It does not resolve an unknown deadline, unknown source status,
applicant eligibility or missing extraction. Those remain separate publication
requirements. Missing pages/details and transient failures cannot create a
successful census or invent a closure.

First/last-seen times come from actual selected list/detail retrieval timestamps,
not publication dates, batch execution time or model processing time. The scope
is explicitly `AVAILABLE_ACCEPTED_FULL_SNAPSHOTS`: first-seen means the earliest
retained verified observation, not a claim that no earlier data ever existed.
Previously pruned or never-fetched history cannot be reconstructed by this layer.

The ordered successful run set, source fingerprints, census hashes, evaluation
time, observation count and complete observation hash are frozen in the manifest.
Late completion of another run does not rewrite an earlier release's history.
Changes to already captured source content, missing verification, or inconsistent
list/detail pairs are rejected. Empty accepted full snapshots are valid and
advance absence while preserving earlier posting observations.

## Operational freshness is separate

Source health is a read-time overlay. It does not mutate frozen posting states:

- `REVIEW_REQUIRED`: latest completed full run awaits review.
- `ERROR`: latest full run failed, or a READY run lacks required validation/
  document verification.
- `STALE`: no valid full success, or the last successful retrieval watermark is
  outside the source window.
- `HEALTHY`: a valid full success remains within its window.

A still-running refresh is shown with `refresh_in_progress`; it does not extend
the last successful watermark. Graph-load failure is distinct from source-fetch
failure: a READY source snapshot can remain valid while graph recovery is pending.

| Selected source | Maximum age for the planned serving checks |
|---|---|
| JOB-ALIO postings | 30 hours |
| Q-Net sessions | 48 hours |
| NCS competencies and qualification mappings | 8 days each |
| ALIO institutions and NCS career-path update check | 35 days each |

The exact boundary is included. An old release can have a stale selected snapshot
while the source's latest successful refresh is healthy. Both are reported;
the overlay never silently substitutes new records into an old release.
Failed/review-pending runs never extend freshness. `all_selected_sources_fresh`
is an operational prerequisite, not semantic completeness or activation approval.

## Storage and retention

The additive tables are `ontology.observation_run`, `posting_seen`,
`observation_freeze`, `observation_history_member` and `posting_observation`.
They are append-only. Census rows reference the original list/detail records;
their full normalized source objects and hashes are preserved separately from
model results and canonical claims.

Canonical binding adds `release_source_run`, `observation_membership` and
`entity_observation_state`. A release still has exactly six current source pins;
historical JOB runs are separate `HISTORICAL` members. Only the exact last-seen
list/detail pair for each missing posting is copied into `input_record`. Current
source coverage therefore still measures the selected current snapshot, while
historical evidence is separately included and hashed in the membership manifest.

An unchanged posting reuses its content-addressed revision. Binding never creates
a new revision merely because time elapsed or the posting was absent. A changed
posting selects its new content revision. Later `assemble_reviewed.hwf` chooses
existing reviewed extraction/link decisions only for the exact selected input
and pinned NCS snapshot; pending corrections and rejected decisions remain
explicit. It makes no new acceptance decisions or model requests. Historical
inline evidence points to the original list/detail records and snapshot hashes.

Current organization revisions take precedence. If an organization is absent
from the current reference snapshot, its historical JOB source supplies an
explicitly limited code/name fallback. This does not reconstruct missing ALIO
profile fields; full older profiles remain in their original releases.

`entity_observation_state` has one immutable row per posting/release, with its
selected revision, content run, connector run, first/last seen, absence count,
state, release creation time and methodology version. Its ID uses the documented
`hop-ontology-jsonb-v1` hash, preserving the runtime's established identity policy.
The graph stores `entityObservationState -FOR_ENTITY-> jobPosting` and
`-SELECTS_REVISION-> jobPostingRevision`; all three belong to the same release.
Times are native Neo4j datetime values. Use **`export_jsonld_v2.hwf`** for these
releases. The immutable v1 exporter rejects the new class rather than omitting it.
V2 retains exact native timestamp strings alongside typed RDF datetime values.

Manual retention protects captured snapshots with
`ONTOLOGY_OBSERVATION_HISTORY`, unless a higher-priority protection such as
`KEEP_LATEST` or `ONTOLOGY_RELEASE` already applies. This is checked before graph
or raw-file deletion. Captured history currently remains retained; observation
history compaction/pruning is not implemented. No automatic deletion was added.

Read-only SQL examples:

```sql
SELECT * FROM ontology.observation_run ORDER BY watermark_at;
SELECT entity_id, serving_state, state_reason, first_seen_at, last_seen_at,
       consecutive_absence_count, membership_state
FROM ontology.posting_observation
WHERE release_id = '<exact-release-id>' ORDER BY entity_id;

SELECT ontology.query_observations_v1('<exact-release-id>', true);
SELECT ontology.query_source_health_v1('<exact-release-id>', true);
```

## Verification and next integration

The live source-only binding was verified at **2026-09-13 02:40:29 KST** on draft
`ontology-history-20260913-f31190ec`: **545 bound postings**, comprising 513
current/ACTIVE and 32 historical/EXPIRED. Every selected source payload, employer
relation and state/time was checked against the original records; replay left
the manifest unchanged. The draft is unsealed and PREPARING, with no review or
document-input selection. No live ontology graph was loaded or model called by
this verification. Receipt:
`~/.local/state/jobtology-hop/ontology-membership-live-20260912T172725Z/`.

`python hop/ontology/tests/observations.py` uses new disposable PostgreSQL/Hop
containers and synthetic source records. It checks midnight and exact freshness
boundaries, explicit closure, one/two absences, failed/partial/replay exclusion,
empty snapshots, changed-content reappearance, preserved old releases, immutable
hashes/history, source mutation rejection, native first execution/replay, optional
refresh hooks and retention protection. It makes no external source/model calls.

The historical-membership regression uses synthetic reviewed inline results and
fresh PostgreSQL/Hop/Neo4j containers. It checks old revision/claim/evidence reuse,
organization fallback, changed-content reappearance, release creation time,
binding/manifest corruption, native graph replay, JSON-LD v2 roundtrip and SHACL.
Run it with the export validation dependencies:

```sh
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python hop/ontology/tests/observation_membership.py
```

Cohort selection, publication/lifecycle checks and freshness enforcement still
need to consume these bound states. Full production extraction/review/linking is
also incomplete, and attachments remain on hold. A successful state binding or
graph load is not serving activation or semantic completion.
