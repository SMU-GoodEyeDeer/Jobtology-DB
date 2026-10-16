# Jobtology admin dashboard

The dashboard in this repository shows the native Hop ingestion ledger, actual
Neo4j counts and a durable queue of operator-approved refresh/load requests.
It uses a **separate dashboard username and password** configured in Coolify.
A Coolify account session does not log you into this application.

This is a repository implementation and deployment recipe. No production
deployment, database grant, refresh or local dataset load is established by these
files. Read the [current handoff](hop-migration/current-handoff.md) before any
operational change.

## Deploy the web application with Railpack

Create a Coolify application from this repository and select **Railpack** as the
build pack explicitly. Use the repository root as the build context. The existing
root `Dockerfile` starts the older cron worker; it is not the dashboard image.
No Sites hosting or separate frontend repository is involved.

The root [`railpack.json`](../railpack.json) forces the Python provider, installs
the frozen `admin` extra with `uv sync --frozen --no-dev --extra admin`, and starts:

```text
uvicorn jobtology_db.admin.app:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log
```

Configure container port **8000**, `PORT=8000`, and healthcheck **`/healthz`**.
That unauthenticated endpoint proves that the HTTP process responds; it does not
prove that either database is available. Configure the domain
`https://jobtology-admin.yeongmin.net` and TLS in Coolify. The domain and TLS are
operator-managed; this recipe does not make DNS changes.

Set the runtime variables in [`deploy/admin/.env.example`](../deploy/admin/.env.example).
Set `JOBTOLOGY_ADMIN_USERNAME`, a unique `JOBTOLOGY_ADMIN_PASSWORD` of at least 8
characters, and an independent random `JOBTOLOGY_ADMIN_SECRET` of at least 32
characters in Coolify. Keep `JOBTOLOGY_ADMIN_COOKIE_SECURE=true` behind HTTPS and
set `JOBTOLOGY_ADMIN_ALLOWED_ORIGINS=https://jobtology-admin.yeongmin.net`.
Rotate the session secret to invalidate existing sessions. Optional proxy access
controls can add another gate; they do not provide Coolify single sign-on.

Attach the application to the private network containing PostgreSQL and Neo4j.
Use private service names on PostgreSQL port 5432 and Bolt port 7687 in the
dashboard credentials. Do not publish those database ports or mount a Docker
socket into the application. Being reachable from this host or private network
does not establish public exposure.

The web application needs a persistent, local bind-mounted queue directory at
`/var/lib/jobtology-admin`. Set `JOBTOLOGY_ADMIN_QUEUE_PATH` to the same absolute
path in web and worker. Configure the container runtime and host worker to use
the **same numeric UID/GID**, and give that UID ownership of the queue directory
with mode 0700. SQLite and its journal must be writable in that directory; mount
the whole directory, not just the database file. Never put the queue on NFS or
use independent copies in multiple containers. Run one web instance and one
host worker against the shared queue for this initial deployment.

The Railpack provider and configuration fields follow the official
[configuration reference](https://railpack.com/config/file/) and
[Python provider documentation](https://railpack.com/languages/python/).
Schema validation and `railpack prepare` passed with Railpack 0.42.0. This proves
configuration planning; it is not a full image build or Coolify deployment proof.

## Read-only database access

Use a dedicated PostgreSQL reader role. The optional
[`postgres-readonly.sql`](../deploy/admin/postgres-readonly.sql) grants only
the ingestion schema access and columns queried by this dashboard. A database
owner must review and run it separately, then set its password interactively.
Do not use an owner, superuser, Hop writer or inherited writer credential in the
web service. Existing privileges inherited from `PUBLIC` require the database
owner's normal review. The application also sets read-only transactions and
query/lock timeouts; those settings complement the database grants.

Provide a dedicated Neo4j account with read access to the selected database and
no write or administration privileges. Neo4j editions differ in user/role
support; use the edition's supported reader role or database access controls.
Read-mode routing in the driver alone is not an authorization boundary. If a
separate graph reader cannot be provisioned, leave graph credentials unset and
the dashboard will show that graph telemetry is unavailable.

Leave `JOBTOLOGY_ADMIN_CONTROLS_ENABLED=false` for a read-only launch. Database
failures show unknown/unavailable values; unavailable counts are not reported
as zero. `JOBTOLOGY_ADMIN_QUERY_TIMEOUT_SECONDS` configures bounded query
budgets and connection timeouts: PostgreSQL has per-statement and transaction
limits, and Neo4j queries share a total query deadline.
`JOBTOLOGY_ADMIN_CACHE_SECONDS` controls the short shared telemetry cache.
`JOBTOLOGY_ADMIN_MODE=demo` shows labeled sample data and disables operations;
demo still requires explicit dashboard credentials.

## Local demo and repository verification

The local demo runs with labeled sample telemetry, disabled operation controls
and no database connections. Install the optional web dependencies, then start
on loopback with a fresh private temporary queue directory:

```bash
uv sync --frozen --extra admin
admin_demo_state=$(mktemp -d)
JOBTOLOGY_ADMIN_MODE=demo \
JOBTOLOGY_ADMIN_USERNAME=demo \
JOBTOLOGY_ADMIN_PASSWORD=local-demo-only-passphrase \
JOBTOLOGY_ADMIN_SECRET=local-demo-only-session-secret-at-least-32-characters \
JOBTOLOGY_ADMIN_COOKIE_SECURE=false \
JOBTOLOGY_ADMIN_ALLOWED_ORIGINS=http://127.0.0.1:8000 \
JOBTOLOGY_ADMIN_QUEUE_PATH="$admin_demo_state/queue.sqlite3" \
JOBTOLOGY_ADMIN_CONTROLS_ENABLED=false \
.venv/bin/uvicorn jobtology_db.admin.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000` and log in with `demo` /
`local-demo-only-passphrase`. These published example values are for this
loopback-only demo. Keep secure cookies enabled and use independent private
credentials in the HTTPS deployment. Stop the demo with Ctrl-C; the temporary
directory remains, while demo mode leaves the queue unopened.

Repository verification on October 16 passed 31 admin tests, Ruff, strict
Pyright, a fresh development installation and collection of the full test suite.
The wheel contains the ASGI application and all three static assets. Actual
database-driver checks against disposable PostgreSQL 18 and Neo4j 2026.06 fixtures
passed with the exact documented PostgreSQL column grants. Checks covered source
counts and inference totals excluding ontology postings even when they also
carry the `entity` label, ledger exclusion of SMOKE runs,
previous READY visibility after a failed run, and the ledger's summary counts.

Chromium checks passed at desktop width 1440 and mobile width 390 without
JavaScript errors or external page requests. Simulated API checks covered action
confirmation, CSRF, an idempotent retry, missing counts, unavailable telemetry
and expired authentication. Worker unit tests replace operation subprocesses.
A separate bounded check with a real harmless stub process passed the
authenticated API-to-queue handoff, RUNNING status with disabled controls,
graceful drain to SUCCEEDED and private 0600 host logs. Neither check executed
an actual refresh or dataset load. The protected verification receipt is
`~/.local/state/jobtology-hop/admin-dashboard-20261016-45b75d2d5a52/receipt.json`,
SHA256 `5a1bfbd665119230a98f406847de6eda7c580a3ad5d1f2ea48a06abd57495ded`.
These checks and Railpack schema/plan validation do not establish a production
deployment or live database/ingestion acceptance.

## Enable approved host operations

The web process only reads telemetry and enqueues an action ID. A separate host
worker executes one of two fixed commands. Browser input never supplies shell
text, a path, an environment variable or a command argument. There is no upload
endpoint, new source scraper or paid inference action.

1. Review the existing runtime and source schedules in the current handoff and
   [operations guide](../hop/operations/README.md). Use the existing ingestion
   operator account and its protected Hop runtime configuration. The host worker
   needs the same existing Docker/CLI access as manual operations; web does not.
2. Copy [`actions.example.json`](../deploy/admin/actions.example.json) to an
   operator-owned `/etc/jobtology-admin/actions.json`, replace the example paths
   and remove every action you do not intend to enable. The disabled starting
   profile is [`actions.disabled.json`](../deploy/admin/actions.disabled.json).
   Protect the directory from untrusted writes; the JSON must be a regular,
   non-symlink file, at most 64 KiB and not group/world writable. Mount this one
   file read-only into web at the same path. Web does not need the runtime
   environment file, source datasets or checkpoints.
3. For a local JobKorea load, supply an already reviewed deployment manifest,
   its exact SHA256, an existing archived composition and a private checkpoint
   directory. The zero hash in the sample deliberately cannot approve a real
   manifest. This dashboard does not generate or approve a deployment manifest.
   Keep original exports, signed URLs, runtime secrets, receipts and actual
   profiles outside Git. Scripts and approved manifest/runtime files must not
   be group/world writable.
4. Configure the host-only values in
   [`worker.env.example`](../deploy/admin/worker.env.example), outside Git at
   mode 0600. Adapt the user, group, repository and interpreter paths in
   [`jobtology-admin-worker.service`](../deploy/admin/jobtology-admin-worker.service).
   Install the package on the host with the frozen dependencies. The worker can
   be checked in the foreground with the following command after configuring
   its environment; starting it processes any pending approved queue entries.

   ```bash
   .venv/bin/python -m jobtology_db.admin.worker
   ```

5. Start the host service and verify its live heartbeat in the dashboard. Set
   `JOBTOLOGY_ADMIN_ACTIONS_FILE` and `JOBTOLOGY_ADMIN_CONTROLS_ENABLED=true` in
   Coolify only after reviewing those exact profiles. Controls require both a
   valid configured action and a recent worker heartbeat. Missing/stale worker
   status disables them; `JOBTOLOGY_ADMIN_WORKER_STALE_SECONDS` defaults to 45.

`refresh_due` invokes only the repository's `hop/operations/refresh.sh` once,
using the approved `runtime_env` path. Its existing due schedules, disk guards,
refresh lock and operation fences still apply. It may fetch configured official
ALIO/JOB-ALIO/NCS/Q-Net/Nara sources. It does not scrape JobKorea, recover job-board
URLs or start paid matching. An exit code of zero may mean no due work, a busy
lock or an operation fence; the queue summary does not claim that data changed.

`load_jobkorea` invokes only `hop/operations/load_jobkorea_dataset.py` with the
profile's `manifest`, `composition_dir` and `checkpoint_dir`. The worker checks
the pinned manifest bytes before launch; the existing loader retains its
runtime identity, preservation, source acceptance and native verification gates.
The supplied snapshot stays local only. Collection, import and processing dates
retain their distinct evidence meanings; the dashboard does not rewrite them.

## Status, restart and recovery

Refreshing the dashboard view reads cached telemetry. Submitting an enabled
operation creates a durable queue record; the host worker owns its lifetime.
Closing a tab, logging out or redeploying web does not cancel a data operation.
The service sample drains a running operation when asked to stop. Public job
summaries contain bounded status text, never raw subprocess logs or credentials.
Each job's stdout/stderr is saved on the host as `<job-id>.log` under
`JOBTOLOGY_ADMIN_WORKER_LOG_DIR` (default: the operator's
`~/.local/state/jobtology-admin/logs`). The worker requires a private 0700 directory
outside the queue mount and creates 0600 files without overwriting earlier logs.
Do not mount it into web. Inspect these files and the existing protected native
receipts for diagnostic detail; manage their retention on the host.

An exclusive host lock covers startup recovery, claiming and execution. Duplicate
workers cannot steal running work. The command inherits that lock, so an
unexpected worker crash cannot allow another worker to overlap its surviving
data process. After a crashed operation releases the lock, a restarted worker
marks the prior running record **UNKNOWN**. Unknown outcomes block further
claims and new requests; they are never automatically retried. There is no
browser recovery/reset button. Keep an uncertain record UNKNOWN until its actual
process, ingestion ledger, graph checkpoint and protected receipts establish the
outcome. Do not delete the queue or change a record merely to unblock it.

For an established outcome, stop the host worker service (its current operation
drains), record the receipts/readback in a protected operator note, and run the
following host-only reconciliation as the queue owner. Replace the job ID, final
state and short evidence reference before running it. Use SUCCEEDED only for an
independently verified successful outcome; use FAILED for an established stopped
failure, after accounting for any partial work. A failure does not authorize a
fresh load or source fetch. If independent verification is incomplete, keep
UNKNOWN. The lock refuses reconciliation while any surviving data command holds
it, and the SQL changes only the selected UNKNOWN row; nothing is replayed.

```python
from pathlib import Path
from jobtology_db.admin.queue import JobStore, now
from jobtology_db.admin.worker import worker_lock

store = JobStore(Path("/var/lib/jobtology-admin/queue.sqlite3"))
job_id = "REPLACE_WITH_THE_EXACT_JOB_UUID"
final_state = "FAILED"  # or SUCCEEDED only with independent success verification
evidence_ref = "REPLACE_WITH_SHORT_PROTECTED_OPERATOR_NOTE_ID"
if final_state not in {"SUCCEEDED", "FAILED"} or "REPLACE" in job_id + evidence_ref:
    raise ValueError("Supply the individually verified outcome and evidence reference")
summary = f"Operator reconciled outcome; protected evidence reference: {evidence_ref}"
if len(summary) > 500:
    raise ValueError("Use a short reference without secrets, paths or raw log content")
with worker_lock(store.path), store.connection() as connection:
    connection.execute("BEGIN IMMEDIATE")
    changed = connection.execute(
        "UPDATE jobs SET state=?,summary=?,updated_at=? WHERE id=? AND state='UNKNOWN'",
        (final_state, summary, now(), job_id),
    )
    if changed.rowcount != 1:
        raise ValueError("Expected one existing UNKNOWN job; nothing was reconciled")
    connection.commit()
```

Retain the operator note and earlier UNKNOWN history in the protected evidence
before this update. Restart the host worker only after that reconciliation.

**SUCCEEDED** in the queue means the fixed host command exited successfully.
Source READY, source-graph projection/checkpoint status and actual graph counts
provide the separate data verification evidence. Counts of source postings
exclude duplicate ontology `jobPosting` representations. Inferred NCS/O*NET
occupation links retain actual review status; mostly unreviewed metadata
inferences and occupation reference details do not establish employer-stated
duties, direct competency evidence or posting-specific technology requirements.

The live native ledger currently reports run states and timing, with no reliable
per-run completion percentage. The dashboard leaves progress percentages unknown
and renders a percentage only when an API response explicitly reports one; it
does not estimate completion from elapsed time or invent a percentage from state.
