# Manual retention deployment verification — 2026-09-12

Installed in Goldship's persistent default Hop project. **No live source snapshot,
raw file or graph node was deleted. No provider or paid model request was made.**
Only the additive SQL installer and the two preview workflows were run live.

Use [the retention guide](../../hop/retention/README.md) for operation and
[the server runbook](server-runbook.md) for SSH, container discovery, persistent
mounts, runtime editing and recovery. No retention timer or cron entry was added.

## Live verification

- 33 public runtime files were copied and verified by SHA-256, including native
  retention workflows/pipelines/SQL, `retention-local` metadata, and writer guards
  in the source graph loader and LLM publisher.
- Existing graph workflow files matched the repository's pre-change versions.
  They were backed up before replacement; private connection metadata and API-key
  files were not copied or changed.
- The installer and file deployment used the existing host scheduler lock. Source
  ingestions and paid enrichment were idle at deployment.
- Native Hop 2.19.0 installation succeeded against live PostgreSQL 18.
- All six relative raw-path mappings resolved to existing files on the real mount,
  including the special `alio-raw`, `job-alio-raw` and `ncs-raw` directories.
- Source run, record and document counts, and LLM batch/attempt counts, were equal
  before and after deployment and previews.
- No ACTIVE retention plan or graph writer lease remained. The maintenance hook
  returned false, so normal due-source scheduling remained enabled.

| Live preview | Parameters | Saved PLAN_ID | Selected |
|---|---|---|---:|
| Oldest JOB-ALIO run | `OLDEST_COUNT`, amount 1, keep latest 2 | `f6854d7d-7208-4c1e-93d5-8f3afbebcfdb` | 0 |
| Q-Net older than 30 days | `OLDER_THAN_DAYS`, amount 30, keep latest 2 | `ae3b942d-f25d-47cd-818b-037d5c939dd0` | 0 |

At verification there were two READY JOB-ALIO runs and one READY Q-Net run. The
keep-latest rule protected them. These are preview examples, not plans that need
to be executed. Make a fresh preview when enough eligible history has accumulated.

Protected deployment logs, file manifests and backups of the replaced workflows:

```text
/home/maxjo/.local/state/jobtology-hop/retention-deploy-20260912T064331Z/
```

## Disposable integration tests

The final end-to-end run used synthetic Korean postings and Q-Net schedules in
isolated PostgreSQL 17, Neo4j 5.26 and Apache Hop 2.19 containers. It verified:

- Native SQL installation/reinstallation and preview without source mutations.
- Count-after-protection selection and strict age-cutoff selection.
- Preservation of the latest two snapshots, dependency/LLM dataset protection,
  rolling request-reservation protection and stale-plan rejection.
- Maintenance fencing, concurrent executor rejection and graph writer cleanup on
  failure. A separate native check covered the LLM publisher's failure cleanup.
- Relative manifest-path resolution, traversal rejection, exact file deletion,
  missing-file retry, and rejection of an existing file whose SHA-256 changed.
- Archival of a disappeared posting's full last-known source data, list/detail
  assembly, Korean text, and preservation of shared entities and LLM graph nodes.
- Replacing an archived record with a newer pruned version without losing another
  disappeared record; archived graph identities remained stable.
- Independent graph-deletion verification after the mutation pipeline committed.
- Recovery after partial graph cleanup and a changed-file failure; PostgreSQL source
  rows remained available until every graph/file checkpoint completed.
- Completed-plan replay as a no-op, without selecting additional snapshots.
- Q-Net age-based deletion retaining the last known schedule from the older year.

Final full-suite local logs: `/tmp/jobtology-retention-test-w8ab2qqj/`.
The dedicated test containers, volumes and network were removed afterward.
Reproduce with `python hop/retention/tests/run.py`; this uses no live credentials.

## Limits

Deletion was exercised against disposable databases and files, not production
history. Live verification covered installation, path mappings, candidate previews
and unchanged data counts. Real deletions begin only when an operator supplies a
reviewed eligible PLAN_ID to `retention/execute.hwf`.

Only complete accepted source snapshots are in scope. Failed/SMOKE runs, LLM
attempt/cache history, review data, unmanifested raw files and empty directories
are retained. The compact archive preserves parsed source data and provenance;
original response bytes and intermediate versions of pruned snapshots are removed.
Snapshots pinned by retained source dependencies or LLM metadata remain protected.
