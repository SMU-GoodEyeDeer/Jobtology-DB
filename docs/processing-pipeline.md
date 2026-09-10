# Processing and recurring updates

The separate [canonical schema foundation](canonical-schemas.md) adds source-independent contracts
and an explicit `jobtology load canonical-latest` step without changing this updater's staging-only
output. See [the canonical load status](canonical-load-status.md) for the local dataset.

Implemented 2026-09-06. This repository now owns a runnable **fetch → parse/normalize → staging
load** pipeline, not just a one-off local parsing script. The same code runs locally and inside
the main server's Coolify stack. See [ADR 0002](decisions/0002-processing-and-updates.md).

## Commands

```bash
uv sync --dev
uv run alembic upgrade head

# Offline: replay one explicitly selected complete fetch, or the latest full fetch per source.
uv run jobtology process run <connector-run-id>
uv run jobtology process latest

# Read-only scheduler status; this does not call upstream APIs.
uv run jobtology pipeline status

# Execute sources that are due, respecting persisted cadence and dependency order.
uv run jobtology pipeline update

# Explicit optional Neo4j staging load after preprocessing.
uv run jobtology load neo4j <processing-run-id>
# Include that same graph staging load in scheduled updates.
uv run jobtology pipeline update --neo4j

# Foreground launch mode for a long-running container.
uv run jobtology pipeline worker
```

`process latest` does not pick an older successful run when the newest full fetch fails validation.
Use an explicit reviewed run ID for intentional replay. Both processing commands make zero upstream
requests. On a fresh deployment, `pipeline update` performs its own first full fetch; offline replay
does not silently mark a source fresh or initialize its recurring schedule.

Exit codes: `0` completed/not due; `1` failed, review-required, or retry-wait; `75` another updater
holds the PostgreSQL advisory lock. Logs are newline-delimited JSON summaries without credentials
or raw provider text. The worker handles SIGINT/SIGTERM and exits after the in-flight tick; a forced
termination is recovered from persisted checkpoints on the next invocation.

## Cadence and upstream change detection

The checked-in [schedule](../config/pipeline.yaml) is validated and dependency-ordered:

| Source | Check interval | Normalized record type |
| --- | --- | --- |
| NCS career-path CSV | 30 days | CareerPath: occupation, unversioned competency, rank/level |
| NCS competency API | 7 days | Competency and official occupation/classification references |
| NCS qualification API | 7 days, after competency input | QualificationMapping |
| Q-Net schedule API | 24 hours, after qualification input | ExamSession |
| ALIO institutions | 30 days | Organization |
| JOB-ALIO | 24 hours | JobPosting, separate list/detail representations |

Intervals are elapsed UTC time from successful staging completion, not fixed KST midnight jobs.
NCS/qualification changes regenerate dependency partitions under `data/runtime/`; they do not edit
the deployed image's checked-in configuration. Dependent sources are also due when their request
partitions change. Calendar-year changes update default Q-Net year partitions on the next tick.
Do not pin `QNET_YEARS` in production unless intentionally limiting that scope.

Each due API source is fully fetched with the existing connector. There is **no cheap upstream
change-only endpoint or HTTP-304 path implemented**. The pipeline detects:

- Identical raw document/partition/version: reuse parsed results after checking the raw file hash.
- Changed response envelope but identical source row: reuse the immutable record revision.
- Changed source row: retain a new revision and all observations.
- Provider-only bookkeeping change: retain provenance, but report `changed=false` if normalized
  facts are unchanged. A separate normalized-set hash distinguishes this from raw changes.

The monthly CSV job checks the configured pinned file. It cannot discover a newly published portal
attachment automatically. Review and change `NCS_CAREER_PATH_DOWNLOAD_URL` when the official file
is replaced. This is separate from weekly full NCS API checks.

There is a default per-source rolling-24-hour budget of 1,000 recorded request attempts, with a
0.2-second minimum delay in updater fetches. Configure `JOBTOLOGY_UPDATE_REQUESTS_PER_24H` no higher
than the approved provider quota; subtract allowance used by other clients. This is a local safety
budget, not a claim about the provider's actual remaining quota. Direct `fetch run` is a manual
operator command and does not enforce the updater's budget, though its recorded attempts count
against subsequent updater calls. Failure retries default to one hour. A lock prevents overlapping
updater ticks; independent ready sources can proceed when another source fails.

## Storage and evidence

The original raw store and fetch ledger are preserved. Migration `0004_processing` adds:

| Table | Purpose |
| --- | --- |
| `control.processing_run` | Versioned processing execution, attempts, readiness, summary/error |
| `staging.document` | Parsed-document checkpoint keyed by snapshot, partition, processor version |
| `staging.record_revision` | Immutable source-shaped payload, typed normalized record, lineage/texts |
| `staging.document_record` | Each record's exact JSON pointer or logical CSV record location |
| `quality.rejected_row` | Invalid rows with original payload/location and safe error code |
| `control.processing_input` | Processing membership linked to the selected fetch observation |
| `control.source_sync` | Last update, next due time, input/config hashes, last success/failure |
| `control.graph_load` | Optional Neo4j staging-load state per target and loader version |

API field lineage uses relative JSON pointers; combine these with `document_record.locator` to
locate the original field in the response. CSV locations are one-based **logical records after the
header**, not physical lines (quoted fields can contain newlines); field pointers identify columns.
Request-derived facts reference `request:partition_id`. Observation joins retain the request,
partition, raw SHA-256, file path, retrieval time, and source-rights policy binding.

Text artifacts retain NFC/LF-normalized text, SHA-256, and normalization version. Future extraction
offsets must be zero-based, half-open Unicode code-point indexes into this exact artifact. Original
field values remain in the source-shaped payload. This preprocessing slice does not yet create
requirement claims or claim-level evidence spans.

Important rules:

- Qualification mapping identity includes `(ncsClCd, jmCd, organStdVerCd)`.
- Q-Net qualification identity comes from its request partition when absent from the response.
- All 32 collected NCS `compeUnitLevel=0` values normalize to unknown (`null`) with an explicit
  `UNSPECIFIED_COMPETENCY_LEVEL` flag; the original zero is preserved.
- Missing prices, dates, statuses, or eligibility information do not become zero/free/eligible.
- JOB-ALIO list/detail records remain distinct and linked by official posting ID. Their title,
  organization, posting dates, and non-null status must agree. Null detail status is not "closed".
- Date-only source fields are not exact deadlines. More precise times can occur in free text and
  need the later grounded extraction stage before a route planner can use them safely.

## Failure and restart behavior

Every document and its records/rejections commit atomically. Retrying a processing run reuses its
completed document checkpoints and does not duplicate revisions. Selected fetch-observation hashes,
raw hashes/lengths, page contiguity/totals, unique record identities, explicit double-confirmed empty
partitions, and JOB-ALIO list/detail coverage must validate before a run is `READY`.

Malformed records are quarantined and the run becomes `REVIEW_REQUIRED`; structural, integrity,
pagination, or list/detail conflicts fail the run. Neither condition advances scheduler success.
Source-policy changes fail closed and require reviewed re-fetch/reprocessing authorization.

If a process stops after fetching, a recorded completed fetch can be resumed into processing.
If it stops midway through HTTP enumeration, the next attempt starts a **new full fetch**, keeping
partial raw/ledger evidence. This version does not resume pages of an interrupted mutable API
snapshot or combine pages across runs. A crash between fetch completion and recording the scheduler
checkpoint can also repeat the full fetch; content-addressed raw storage still deduplicates bytes.
Semantic validation failures retry with a fresh fetch after backoff. Interrupted processing and
graph-infrastructure failures reuse a recorded completed fetch when the configuration is unchanged.

Absent jobs remain in historical staging. This slice does not infer closed/deleted jobs from absence,
advance serving freshness, calculate 180-day cohorts, or activate a recommendation corpus.

## Neo4j staging loader

`--neo4j` is opt-in; no graph credentials are required for PostgreSQL preprocessing. Configure:

```dotenv
JOBTOLOGY_NEO4J_URI=bolt://neo4j:7687
JOBTOLOGY_NEO4J_USERNAME=neo4j
JOBTOLOGY_NEO4J_PASSWORD=<runtime-secret>
JOBTOLOGY_NEO4J_DATABASE=neo4j
```

The loader uses isolated `IngestBatch`, `IngestRecord`, and `IngestIdentity` labels. Record references
connect occupations, versioned competencies, qualifications, exam sessions, organizations, and jobs
by explicit official identity. The batch stores the processing-run ID and exact content-set hash;
the PostgreSQL processing manifest is its evidence authority. Raw payloads, long free text, contact
fields, and Person data are not copied into this graph projection.

The loader uses parameterized, idempotent batched writes with the official driver's
[managed transactions](https://neo4j.com/docs/python-manual/current/transactions/), verifies loaded
record IDs against the manifest, and marks the batch `READY` only afterward. Retrying an interrupted
load safely repeats batches. A graph batch is always `serving_scope=STAGING`, not a `CorpusRelease`.
It never changes the backend's active-release pointer. Consumers must not use it as a live-job or
route-recommendation API. Final Schema.org/jt claims, grounded extraction, release activation,
rollback, rights-purge propagation, and serving projections remain subsequent implementation work.

## Deploying under Coolify

The [Dockerfile](../Dockerfile) creates a non-root image, exposes no ports, and defaults to the worker.
For the default cron/Coolify approach, invoke `jobtology pipeline update` from the same image every
15 minutes instead. Do not install both an independent worker and a recurring task unnecessarily.

Before enabling either trigger:

1. Set the pipeline DSN to the private Coolify PostgreSQL 18 service and database. Do not use the
   local-development DSN or Coolify's own administration database.
2. Mount the durable raw-data volume at `/data`, writable by UID/GID `10001`. Mount/copy existing
   raw objects together with their ledger if migrating the local collection; copying PostgreSQL
   alone is insufficient. Runtime settings, source policies, and schedule must be available.
3. Set credentials through runtime secrets. `.env`, raw data, tests, and Git history are excluded
   from the Docker build context. Run `alembic upgrade head` as a deployment/migration step.
4. Run `jobtology pipeline status`, then one controlled `pipeline update`, inspect its staging and
   quality results, and only then enable recurring execution. The updater does not auto-migrate DBs.
5. Keep PostgreSQL, Bolt, and internal tools private/internal/Tailscale-only. No public endpoint is
   introduced here; the separately deployed frontend remains publicly reachable through its domain.
6. Set the server raw-store free-space reserve to `107374182400` (100 GiB). Arrange durable backups
   of both ledger/staging and referenced raw objects before collecting production history.

No cron entry, Coolify resource, remote database, or production Neo4j has been changed by this work.

## Verification

```bash
uv run ruff check .
uv run pyright
uv run pytest
# Optional: disposable PostgreSQL database whose name ends with _test.
JOBTOLOGY_TEST_DATABASE_URL=<test-dsn> uv run pytest tests/integration
```

For optional Neo4j integration tests also set `JOBTOLOGY_TEST_NEO4J_URI` and
`JOBTOLOGY_TEST_NEO4J_PASSWORD` to a disposable local instance. They verify staged loading and replay;
do not point test settings at the product database.

The six saved full source runs were processed locally without additional upstream requests:

| Source | Normalized source records | Result |
| --- | ---: | --- |
| NCS career paths | 12,864 | READY |
| NCS competencies | 15,520 | READY; 32 unspecified-level flags |
| NCS qualification mappings | 87 | READY |
| Q-Net exam sessions | 56 | READY |
| ALIO organizations | 355 | READY |
| JOB-ALIO | 1,020 representations of 510 postings | READY |

`READY` here means structurally validated staging, not a published ontology or verified
student/new-graduate opportunity. Automated tests include PostgreSQL 18 migrations, immutable
replay, changed-record detection, quarantine, partial-fetch rejection, interruption recovery,
advisory locking, scheduler cadence, and failure backoff.

Verification now covers **145 passing tests**, including PostgreSQL 18, local Neo4j, a complete
six-source replay, a simulated changed posting, and the production request-budget guard. The
full-corpus replay is opt-in (`JOBTOLOGY_TEST_REPLAY_SAVED_CORPUS=1`). Ruff, Pyright, Docker build,
non-root container checks, and worker shutdown checks passed. See the detailed
[test report](processing-test-report.md) for results, reproduction, and limits.
