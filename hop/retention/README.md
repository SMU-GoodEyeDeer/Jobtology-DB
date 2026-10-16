# Manual source-snapshot retention

Use `retention/preview.hwf` to save a deletion plan, inspect it, then run
`retention/execute.hwf` with that exact `PLAN_ID`. Select **retention-local** and
**Basic** logging. No timer or cron entry runs these workflows.
The [current handoff](../../docs/hop-migration/current-handoff.md) records the
runtime migration state. September retention reports are historical evidence.

This optional storage workflow removes eligible **complete source snapshots**
from raw storage and PostgreSQL while keeping a compact PostgreSQL archive.
Neo4j keeps business entities and their relationships; retention performs no
Neo4j operation. Permanent removal of graph batch/record history is a separate
model migration and does not launch storage cleanup. LLM requests, responses,
cached attempts, reviews, evaluation cases and gold labels remain protected.
JobKorea raw-data/storage cleanup is unsupported and remains a separate task.

With the ontology observation layer installed, captured JOB-ALIO snapshots are
also protected as observation history. This preserves first/last-seen times and
the evidence for absence counts. Such snapshots are currently retained
indefinitely: history compaction/pruning is still pending, so a manual plan can
select fewer JOB snapshots than requested, including zero.
The [2026-09-16 live ALIO previews](../../docs/hop-migration/graph-clutter-retention-20260916.md)
selected zero of five READY runs even with `KEEP_LATEST=1`; older runs were
pinned by evaluation datasets, an ontology release or an LLM batch.

## Choose the snapshots

Open `${PROJECT_HOME}/retention/preview.hwf`. The parameters are:

| Parameter | Default | Meaning |
|---|---|---|
| `SOURCE_ID` | `job_alio` | One of `alio_organization`, `job_alio`, `ncs_competency`, `ncs_qualification`, `qnet_schedule`, `ncs_career_path`. One source per plan. |
| `SELECTION_MODE` | `OLDEST_COUNT` | `OLDEST_COUNT` or `OLDER_THAN_DAYS`. |
| `AMOUNT` | `1` | Number of oldest eligible snapshots, or age in days. Positive integer. |
| `KEEP_LATEST` | `2` | Always retain at least the newest N accepted snapshots of this source. Minimum 1. |
| `RAW_BASE` | `${PROJECT_HOME}/data` | Standard project data directory. The executor must use the same directory. |

Examples:

- Delete up to the **5 oldest eligible JOB-ALIO snapshots**: `SOURCE_ID=job_alio`,
  `SELECTION_MODE=OLDEST_COUNT`, `AMOUNT=5`.
- Delete **Q-Net snapshots older than 30 days**: `SOURCE_ID=qnet_schedule`,
  `SELECTION_MODE=OLDER_THAN_DAYS`, `AMOUNT=30`.

The count is applied **after protection rules**, oldest first. It can select fewer
than requested, including zero. Age uses snapshot `created_at`, a strict `<`
comparison, and a cutoff frozen when preview runs. One day means 24 elapsed hours;
selection is not based on the posting's closing date or the raw file modification
time. Preview neither downloads data nor changes source/graph/file contents. It
writes only an audit plan and its manifest.

The log prints `PLAN_ID`, selected/skipped counts, source record counts, raw file
counts and raw bytes. Each run is then logged with its decision. For a table in
Hop, open `inspect_plan.hpl`, supply `PLAN_ID`, and **Preview decisions here**.

```sql
SELECT * FROM retention.plan_report ORDER BY created_at DESC;
SELECT run_id, created_at, selected, reason, record_count, document_count, raw_bytes
FROM retention.plan_run WHERE plan_id = '<plan-id>' ORDER BY created_at, run_id;
SELECT raw_path, byte_length FROM retention.plan_file WHERE plan_id = '<plan-id>';
```

A large raw-byte total is not a PostgreSQL disk-space estimate. PostgreSQL DELETE
makes space reusable inside the database; it does not normally shrink its data
files on the host. The workflow does not run VACUUM FULL or alter backups.

## Protected snapshots

The preview explains why each run is skipped:

- `KEEP_LATEST`: the newest N accepted snapshots, **per source**, regardless of age.
- `UPSTREAM_DEPENDENCY`: another retained ingestion run pins this exact run.
- `EVALUATION_DATASET`, `LLM_BATCH`, `LLM_CATALOG`: enrichment references this run.
- `ONTOLOGY_RELEASE`, `ONTOLOGY_OBSERVATION_HISTORY`: a release or captured posting
  census requires the original snapshot and evidence.
- `GRAPH_NOT_CHECKPOINTED`: graph export/recovery must finish first.
- `UNSUPPORTED_JOBKOREA_STORAGE_RETENTION`: this adapter cannot prune supplied
  JobKorea file/checkpoint archives.
- `REQUEST_QUOTA_WINDOW`: a request reservation is still within the rolling 24-hour
  accounting window. Removing it must not create a false provider allowance.
- `NOT_ACCEPTED_FULL_SNAPSHOT` or `VALIDATION_ISSUES`: partial, failed and SMOKE runs
  are outside this first retention implementation.

Protection is conservative: even an old failed dependent run can pin its upstream
snapshot. This workflow does not delete that dependency merely to free more space.
To prune reference sources, prune eligible dependent history first: jobs before
organizations; Q-Net before qualification mappings; qualification mappings before
NCS. Then make a new preview. Retained dependencies and LLM datasets can continue to
pin snapshots, so the requested count is a maximum, not a promise.

The executor rechecks the exact candidates, their contents and protections before
starting. A newly added dependency or changed source data makes the plan stale;
create another preview. It never silently swaps in other snapshots.

## Execute the reviewed plan

Open `${PROJECT_HOME}/retention/execute.hwf`, choose **retention-local**, and set:

| Parameter | Value |
|---|---|
| `PLAN_ID` | Exact ID printed by the preview |
| `RAW_BASE` | Same directory used for preview; normally leave default |

Running this workflow is the manual deletion trigger. There is no additional
in-workflow confirmation prompt. A zero-selection plan cannot execute.

The workflow performs these steps in order:

1. Recheck the plan and acquire a persistent maintenance fence. Refuse to start
   while an ingestion is LOADING, an enrichment batch is RUNNING, or a guarded
   graph workflow has an active writer lease.
2. Save the newest selected version of each source record in PostgreSQL
   `retention.archive_record`, retaining source/normalized objects, lineage,
   quality flags, run/document metadata, hashes and dependency provenance.
   Verify every selected run's immutable PostgreSQL source projection before
   archiving; missing, failed or tampered source evidence stops execution.
3. Verify the selected source projection's source ID, record count and exact
   evidence hash, then save `source_projection_verified` checkpoints. The
   projection and its immutable record/membership evidence survive later cleanup.
4. Rehash existing raw files against their saved SHA-256 manifests, then delete
   only those exact files. Record a checkpoint after verifying each is absent;
   an already missing file is complete on retry.
5. Recheck source proof and delete the selected PostgreSQL snapshot rows and
   children in one transaction, with ordinary foreign keys and **no CASCADE**,
   then mark the plan COMPLETE. Business graph nodes, NCS links and graph
   properties remain unchanged.

While a plan is ACTIVE, the existing source scheduler returns no due work. Database
write guards also reject conflicting source writes, and graph workflow entry points
register writer leases. This is a temporary pause during a manual cleanup, not a
retention schedule. Completion releases the fence and normal source scheduling
continues. A handled failure releases the executor owner but leaves the maintenance
fence active until the same plan completes.

Do not launch internal graph or retention `.hpl` files as standalone writers.
Use the `.hwf` entry points, which apply the maintenance guard and stage ordering.

## What survives after deletion

An unchanged active posting exists in each source snapshot. A posting that stopped
appearing also survives through its latest retained or archived record. The archive
keeps **one latest version among pruned snapshots per source record identity**;
older archived versions are replaced as newer snapshots are pruned. Retained full
snapshots continue to contain their complete history.

Read across both retained snapshots and the archive:

```sql
-- Latest known source object for every identity, including disappeared records.
SELECT * FROM retention.last_known_record WHERE source_id = 'qnet_schedule';

-- JOB-ALIO list/detail pairs assembled as complete last-known postings.
SELECT posting_id, normalized->>'title' AS title,
       source_created_at, archived, in_latest_snapshot
FROM retention.last_known_job_posting ORDER BY posting_id;
```

`in_latest_snapshot=false` means absent from the latest active listing. It does not
assert that a posting was closed, cancelled or deleted by its provider. Likewise,
archived Q-Net dates are last observed dates, not a guarantee that an exam occurred.
The existing `ingestion.current_record`, `ingestion.latest_ready_run` and source
views keep their current/retained-snapshot meaning; archive rows are not mixed into
current active postings or fed automatically into LLM enrichment.

Historical membership and content proof stay in PostgreSQL:

```sql
SELECT run_id, source_id, state, record_count, reference_count, content_sha256
FROM ingestion.source_graph_projection ORDER BY run_id;
SELECT ingestion.assert_source_graph_projection('<exact-run-id>');
```

Original byte-for-byte HTTP/CSV response files are **not kept in the compact
archive**. After deletion their paths/hashes are provenance only. The complete
parsed source objects survive in PostgreSQL; exact raw replay and intermediate
historical versions of pruned snapshots do not. This is retention, not a backup or
an erasure workflow.

## Interrupted cleanup and recovery

Inspect `retention.plan_report`. If a handled error leaves `state=ACTIVE` and
`owner_id` empty, fix the cause and run `execute.hwf` again with the **same PLAN_ID**.
PostgreSQL archive/proof operations and file checkpoints are repeatable. Re-executing a COMPLETE plan
is a no-op; it never selects another set of old runs.

If Hop or its container was killed, a stale owner/graph lease may remain:

```sql
SELECT plan_id,state,phase,owner_id,last_error FROM retention.plan WHERE state='ACTIVE';
SELECT * FROM retention.writer ORDER BY started_at;
```

First verify the old workflow/process has actually stopped. Then use
`recover_stopped_run.hwf` with `CONFIRM_STOPPED=STOPPED`:

- For an interrupted retention executor: `RECOVERY_KIND=EXECUTOR`, its `PLAN_ID`
  and exact `OWNER_ID`. This clears the stale owner but **keeps maintenance active**.
  Resume `execute.hwf` with the same plan.
- For a stopped graph workflow: `RECOVERY_KIND=WRITER`, `OWNER_ID=<writer_id>`.
  This removes only that stale writer lease. Retry the graph workflow as needed.

Leases never expire automatically: elapsed time cannot prove that a slow writer
has stopped. Never release a live writer or edit plan/checkpoint rows to bypass a
failed verification. `cancel_plan.hwf` cancels only an unexecuted PLANNED preview;
an ACTIVE plan may already have deleted files and must be completed.

## Filesystem limits and installation

Only the existing standard layout is supported:
`${PROJECT_HOME}/data/<source-raw-directory>/<UUID-run-id>/<file-path>`.
`alio_organization` uses `alio-raw`; `job_alio` uses `job-alio-raw`;
`ncs_competency` uses `ncs-raw`; other sources use `<source_id>-raw`. Traversal components, URI schemes, shared manifest paths,
wrong roots and non-UUID run directories are rejected before destructive work.
The deployed manifests store paths relative to the source raw directory, such as
`<run_id>/index/page-1.json`. Preview resolves those against RAW_BASE and the
source directory above; the saved plan shows the exact absolute deletion path.
Already-absolute manifest paths are accepted only inside the same allowed layout.
Raw storage must be a trusted local directory, without symlinked source/run paths.
The workflow deletes individual regular files, never recursively walks directories.
Empty directories and unmanifested files are left alone. Custom RAW_ROOT locations
need an explicit supported-path change before this workflow can prune them.

Deploy `retention/`, both `retention-local` metadata files, and the guarded
`graph/load_snapshot.hwf` and `llm/publish_reviewed.hwf` together. Install once with
`retention/install.hwf` while no writer is running. It reinstalls the additive
operations SQL with a maintenance hook, then creates retention tables/functions and
write guards, waits for `graph/install.hwf` to install date and immutable source
proof contracts, then installs `002_batchfree_retention.sql`. It preserves source
data and refresh-policy values. Enrichment SQL must already be installed.
For an already installed runtime, the focused
`ingestions/jobkorea/install_batchfree_graph_publication.hwf` replays only graph
contracts, retention 002 and LLM publication 036. It does not replay older model
planning or accounting migrations. No container restart is required.
See [the server access and editing runbook](../../docs/hop-migration/server-runbook.md).

Development generation: `python hop/retention/tools/build.py`.
Disposable integration tests: `python hop/retention/tests/run.py`. These require
Docker and create only `jobtology-retention-test-*` containers on an internal
network, with synthetic Korean data and no provider/model calls. Python is used
only to build/test artifacts; the deployed workflow uses native Hop transforms,
PostgreSQL SQL. The former standalone graph archive/delete pipelines abort with
a retirement message, preventing stale entrypoints from recreating source history
nodes or an archive layer. Native file deletion uses Hop's
[Process files transform](https://hop.apache.org/manual/latest/pipeline/transforms/processfiles.html).
