# ADR 0002: Processing and recurring updates

- Status: accepted and implemented (staging scope)
- Date: 2026-09-06

## Decisions

1. The executable pipeline is a plain Python CLI with persisted PostgreSQL state. The default
   production trigger is a Coolify Scheduled Task/cron invocation of `jobtology pipeline update`
   every 15 minutes. The same runner also has a foreground `pipeline worker` polling entrypoint.
   These are two launch modes of one implementation, not separate schedulers. No systemd timers,
   workflow server, LangGraph, or autonomous LLM agents are required for preprocessing.
2. Production PostgreSQL 18 belongs to the user's Coolify stack. The existing local PostgreSQL 17
   container is retained as a development fixture. Do not upgrade its data directory in place or
   repurpose Coolify's own control-plane database. The pipeline uses `jobtology_pipeline`.
3. The source scope is the six allowed official sources in ADR 0001. Saramin is pending and
   rights-blocked; Work24 is post-MVP. The first future serving corpus will disclose public-sector
   job coverage. Its required-source/cohort methodology must not demand blocked sources.
4. Due API sources use full list/detail enumeration, followed by byte-hash and record-level change
   detection. This implementation does not claim to have provider delta feeds, conditional HTTP
   requests, or a metadata-only change probe. An unchanged fetch still creates new observations;
   unchanged documents and records reuse their processing results/revisions.
5. The career-path CSV is an explicitly pinned artifact. Monthly checks re-fetch that artifact.
   A replacement portal attachment requires reviewing and updating its pinned URL; silently
   following arbitrary download links is not part of this version.
6. Parsing and normalization are deterministic, typed, and source-specific. PostgreSQL staging is
   loaded automatically. The optional Neo4j loader projects only `Ingest*` staging labels and
   shared official identities; it never activates a serving corpus or publishes extracted claims.
7. Processing readiness is separate from source freshness and corpus publication. A processing
   run can be `READY` while the original connector run remains `RUNNING/FETCHED`. Staging does not
   satisfy the original plan's final `SUCCEEDED` or serving-release gates.
8. Normalization produces source-shaped records plus canonical typed values and field lineage.
   The final Schema.org/jt claim/release projection remains a later stage, not an implicit meaning
   of `IngestIdentity.kind`. Unversioned CSV competency codes are not merged with versioned NCS
   competency-unit codes. Date-only fields remain dates, never fabricated closing timestamps.

## Superseded specifications

This ADR supersedes the original plan's production PostgreSQL-17/dedicated-host deployment, host
systemd scheduler, eight-required-source release scope, and mandatory JOB-ALIO-plus-Saramin cohort
source set. The remaining backup, rights-purge, grounding, serving-release, and backend contracts
are future requirements; the new staging loader does not claim to implement them.

See [the operational guide](../processing-pipeline.md) for implemented commands, cadence,
checkpoint behavior, credentials, limitations, and test results.
