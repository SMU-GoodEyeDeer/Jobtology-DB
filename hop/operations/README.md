# Refreshing the Hop data

These workflows refresh the separate PostgreSQL `ingestion` schema and its Neo4j
source graph. They do not publish a canonical serving release or run LLM enrichment.
The [LLM workflows](../llm/README.md) are separate, manual entry points with configurable
models, evaluation datasets and explicit request/spend limits.

With the ontology extension installed, successful JOB-ALIO graph checkpoints
also preserve an immutable census of the accepted full snapshot. This uses the
stored API records and makes no additional provider/model calls. It enables the
[posting observation history](../ontology/observations.md); release freezing and
publication remain separate manual steps. Census capture and the graph checkpoint
commit together, including graph-recovery runs. Attachment processing is still
on hold and is not part of the scheduler.

| Source | Refresh interval | Workflow for fetching and loading both databases |
|---|---|---|
| ALIO organizations | 30 days | `refresh_alio_organization.hwf` |
| JOB-ALIO postings | 24 hours | `refresh_job_alio.hwf` |
| NCS competencies | 7 days | `refresh_ncs_competency.hwf` |
| NCS qualification mappings | 7 days | `refresh_ncs_qualification.hwf` |
| Q-Net exam schedules | 24 hours | `refresh_qnet_schedule.hwf` |
| NCS career-path CSV | 30 days | `refresh_ncs_career_path.hwf` |

Use `reference-local` and Basic logging for these workflow entry points. The inner
pipelines retain their source-specific configurations. Automated refreshes use FULL;
use `ingestions/<source>/full.hwf` when intentionally running an ingestion-only SMOKE.
Private PostgreSQL/Neo4j metadata and the API-key file stay in the mounted Hop config.

Every successful refresh creates a new source snapshot. Existing accepted runs stay
available. Stable entity identities are merged in Neo4j; historical source records
remain attached to their own ingestion batch. Missing jobs or exam sessions in a
later response are absent from that snapshot; absence does not invent a closed or
cancelled status. The current application read interface is:

```sql
SELECT source_id, run_id, created_at FROM ingestion.latest_ready_run;
SELECT * FROM ingestion.current_record WHERE source_id = 'qnet_schedule';

SELECT e.* FROM ingestion.exam_session e
JOIN ingestion.latest_ready_run u USING (run_id)
WHERE u.source_id = 'qnet_schedule';
```

## Scheduler and configuration

Install the additive SQL files in this order: `schema.sql`, `reference-support.sql`,
`career-support.sql`, `checks.sql`, `operations.sql`. The source and graph workflows
must already exist in the persistent project mount. Reinstallation preserves rows
and existing refresh-policy overrides.

Goldship's scheduler adapter is `refresh.sh`. It discovers the running containers
from the persistent Hop volume and PostgreSQL container name, takes a host `flock`,
and asks `ingestion.refresh_queue` which operations are due. It invokes native Hop
workflows sequentially. The small Python helper only removes API keys from CLI
output before logs are saved; it performs no ingestion, parsing or database loading.
There are no Python/JavaScript transforms or custom Hop plugins.

The host files are:

- `~/.local/bin/jobtology-hop-refresh`: scheduler adapter.
- `~/.config/jobtology-hop/runtime.env`: container identities, paths and disk limits.
- `~/.local/lib/jobtology-hop/redact_runner.py`: log redactor.
- `~/.local/state/jobtology-hop/`: protected logs and process lock.

A cron entry can invoke `~/.local/bin/jobtology-hop-refresh` every 15 minutes. That
checks elapsed time; it does not download every source every 15 minutes. The
database policy controls intervals and a one-hour retry delay. A newly accepted
upstream snapshot also makes its dependent source due, so partition scope is rebuilt.
Run the adapter
manually to process due work under the same lock. Do not run a second graph writer
in the Hop editor while a scheduled load is running.

This entry is installed on Goldship as of 2026-09-11:

```cron
*/15 * * * * /home/maxjo/.local/bin/jobtology-hop-refresh >> /home/maxjo/.local/state/jobtology-hop/scheduler.log 2>&1 # jobtology-hop-refresh
```

The first live adapter run recovered the three pre-existing graph checkpoints;
all six sources are now current. A second due-work check skipped every source.
See the [deployment verification report](../../docs/hop-migration/live-status.md).

```sql
SELECT * FROM ingestion.refresh_policy ORDER BY source_id;
SELECT * FROM ingestion.refresh_queue ORDER BY priority;
SELECT * FROM ingestion.refresh_execution ORDER BY execution_id DESC LIMIT 20;

-- Pause one source without losing data or changing its workflow.
UPDATE ingestion.refresh_policy SET enabled = false WHERE source_id = 'qnet_schedule';
```

## Quotas, failures and recovery

Each HTTP request reserves quota in PostgreSQL before it is sent. The default is
1,000 requests per source in a rolling 24-hour window, plus the workflow's run cap.
Only this Hop writer's requests are accounted for; other programs sharing a key
must be stopped or their allowance budgeted separately. API requests retain the
existing 200 ms spacing and finite connection/read timeouts. REST pagination and
hidden transport retries are disabled so requests remain countable.

Reservations survive crashes. `RESPONSE_ARCHIVED` means both original bytes and a
manifest were saved. `RESERVED` may mean the request reached the provider but no
response was registered; it still consumes quota. Earlier saved documents are
included during installation; pre-installation transport failures cannot be
reconstructed. Never delete reservations to bypass the provider allowance.

The adapter records each execution durably. After failure it waits at least one
hour before trying that source again. A fetch retry starts a fresh snapshot; it
does not mix old pages with a changing live result set. Partial runs stay outside
`ready_record` and `current_record`. Their raw files remain available for diagnosis.

PostgreSQL READY is the graph recovery checkpoint. If a graph load fails, run
`export_pending.hwf` with the exact `RUN_ID`; the scheduler chooses the same recovery
path automatically for the latest accepted run. It reuses PostgreSQL data and makes
no provider requests. `graph_export` records only a successful verified graph load.
A crash between graph completion and checkpoint insertion causes a safe repeated
graph load. The graph loader validates immutable facts and relationship counts.

```sql
SELECT source_id, outcome, count(*)
FROM ingestion.request_attempt
WHERE reserved_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
GROUP BY source_id, outcome;

SELECT u.source_id, u.run_id, u.state, g.exported_at
FROM ingestion.latest_ready_run u LEFT JOIN ingestion.graph_export g USING (run_id);

SELECT * FROM ingestion.validation_issue WHERE run_id = '<run-id>';
SELECT * FROM ingestion.reference_scope_issue WHERE run_id = '<run-id>';
```

The scheduler checks the actual raw-volume filesystem before each source: at least
100 GiB must remain and usage must be below 85%. It never deletes snapshots
automatically. Responses are rejected after download if they exceed 64 MiB. Native
REST buffers a response, so this is **not a streaming memory/response-size limit**
([REST Client behavior](https://hop.apache.org/manual/latest/pipeline/transforms/rest.html)).
Direct editor runs also bypass the host disk check and process lock; the request
ledger and source validators still apply.

## Boundaries of this migration

All six existing source types have native ingestion workflows. The graph remains a
versioned source-data graph in STAGING scope. The separate canonical/evidence-store
contracts and future application query model remain application-design decisions; no backend
application currently needs a cutover.
JOB-ALIO's broad NCS category codes do not establish required competency units;
the separate LLM workflows propose evidence-backed duty alignments and publish only reviewed
ENRICH results. They are not invoked by this source scheduler.

The career CSV URL is pinned. Monthly checks can detect changes to that artifact,
but they do not discover a newly published replacement download identifier.

## Manual retention maintenance

[Manual retention workflows](../retention/README.md) preview and prune eligible source snapshots. While a cleanup plan is ACTIVE, `ingestion.maintenance_active()` suppresses the refresh queue and write guards prevent races. A failed cleanup keeps this pause until its exact plan is resumed and completed. No scheduled deletion was added. See the [server runbook](../../docs/hop-migration/server-runbook.md) for container discovery and mounted paths.
