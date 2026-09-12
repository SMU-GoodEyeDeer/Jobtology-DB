# Hop deployment verification — 2026-09-11

All six source types were loaded into the separate `ingestion` PostgreSQL schema
and the existing Neo4j staging graph. These are the accepted snapshots at deployment;
future refreshes produce new run IDs and may legitimately change the counts.

| Source | Accepted run ID | Source records | Archived responses |
|---|---|---:|---:|
| ALIO organizations | `cb6db580-6cdb-4015-8fd6-2d7f682e460a` | 355 | 4 |
| JOB-ALIO postings | `77ccb77b-3afc-4965-8ce5-efd687304954` | 1,012 representations / 506 postings | 512 |
| NCS competencies | `a32170ed-7485-4e31-82d3-ed48b3398946` | 15,520 | 16 |
| NCS qualification mappings | `2b485d2e-715c-4310-b5fc-4ffbd663de7a` | 87 | 237 |
| Q-Net exam schedules | `6bf80efe-29bc-47cd-bc6b-aa065805e232` | 56 | 104 |
| NCS career paths | `51a6a5d2-5ccf-4459-8218-d61668c34d96` | 12,864 | 1 |

Qualification requests cover all 139 versioned competency codes in the eleven
configured occupations. Q-Net covers 31 qualification codes × 2026/2027, including
empty partitions confirmed twice. The career download contains 12,864 logical CSV
records. Each dependent run records the exact upstream snapshot it used.

Independent comparisons of the new live responses against the original Python
parser found **zero differences** in original source objects, normalized fields,
field lineage and quality flags. Original bytes were rehashed against every
manifest. Career identities intentionally use the documented Hop hash format;
their complete normalized objects and source locations were compared instead.

Independent Neo4j readback matched **29,894 source records, 59,377 identity
references, 30,387 named entities and six READY batches**, with zero differences
in record properties, references, captions, name provenance, semantic labels or
batch dates. All 34,365 prior node IDs and 50,306 prior relationship IDs survived.
No entity needed an ID-only fallback caption. The total graph has 60,287 nodes and
89,271 relationships under the ingestion model.

The new sources were also exercised offline in native Hop 2.19 with PostgreSQL 18
and Neo4j 5.26. Tests covered full source replay, isolated SMOKE runs, invalid
numbers/dates, CSV encoding and quoting, extra/missing columns, duplicate headers,
empty files, quota denial before a request, request accounting on the existing
ALIO/JOB/NCS workflows, and ingestion followed by graph export/checkpointing.
Refresh-policy checks covered due intervals, graph recovery priority, source pause,
and failure cooldown measured from the end of the failed execution.

Goldship now has one cron entry checking due work every 15 minutes. A live adapter
trial completed the ALIO, JOB-ALIO and NCS graph recovery operations successfully.
The request ledger stayed at 886 reservations: recovery made no new API calls.
A concurrent adapter invocation was skipped by the process lock, and a subsequent
due-work check performed no work. All six latest snapshots have graph checkpoints.
Independent readback after the trial was identical to the complete graph before it,
apart from the intentionally refreshed graph-load/verification timestamps.

Live execution logs are protected on Goldship under
`/home/maxjo/.local/state/jobtology-hop/`. Initial new-source logs are
`20260911-live-qualification.log`, `20260911-live-qnet.log`, and
`20260911-live-career.log`. API keys are removed before logs are written.

Deployment changed public workflow/SQL files in the existing persistent Hop project
mount and added host scheduler files. It preserved the private database connections
and API-key file. Previous workflow files and the pre-change schema definition are
backed up under `${PROJECT_HOME}/data/backups/20260911-reference-refresh/`.

Use the [refresh and recovery guide](../../hop/operations/README.md) for entry points,
intervals, quota state, logs and recovery. LLM enrichment, posting-to-competency
matching, and canonical/application cutover remain separate later work.
