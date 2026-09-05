# Jobtology data ingestion

This repository owns source fetching, immutable raw storage, processing, grounding, and loading for
the Jobtology ontology. The current executable slice implements **fetching only**: official source
connectors validate each response, store its bytes by SHA-256, and write an append-only fetch ledger
to PostgreSQL. It deliberately does not write Neo4j yet.

## Quick start

Requirements: Python 3.12, `uv`, and Docker/Compose for the included local PostgreSQL.

```bash
uv sync --dev
docker compose -f deploy/dev/compose.yaml up -d
uv run alembic upgrade head
uv run jobtology sources doctor --allow-incomplete-sources
uv run jobtology sources list
```

An ignored `.env` with safe local defaults has already been created. Put issued keys there—never in
Git or chat. See [the credential checklist](docs/credentials.md) for the exact applications.
Run `jobtology sources doctor` without the waiver once the intended sources are configured; that is
the strict deploy check.

Inspect a request safely before it makes network or database calls:

```bash
uv run jobtology fetch plan ncs_competency
```

The public NCS career-path file needs no provider key and can be collected immediately:

```bash
uv run jobtology fetch run ncs_career_path --mode backfill
```

The two dependent Q-Net sources use partition files derived from complete upstream snapshots. Copy
the `connector_run_id` printed by each full fetch into the next command:

```bash
uv run jobtology fetch run ncs_competency --mode scheduled-full
uv run jobtology derive ncs-qualification-codes <ncs-competency-connector-run-id>
uv run jobtology fetch run ncs_qualification --mode scheduled-full
uv run jobtology derive qnet-item-codes <ncs-qualification-connector-run-id>
uv run jobtology fetch run qnet_schedule --mode scheduled-full
```

Derivation verifies that the upstream run is complete, every selected raw object still matches its
manifest hash and length, and NCS IDs are unique. If the CQ-Net API changes ordering between pages
and returns overlaps, derivation fails closed; rerun the full upstream fetch rather than combining
pages from different snapshots.

Make a bounded smoke-test collection:

```bash
uv run jobtology fetch run ncs_competency --mode backfill --max-pages 1
uv run jobtology fetch run alio_organization --mode backfill --max-pages 1
uv run jobtology fetch run job_alio --mode backfill --max-pages 1
```

For JOB-ALIO, one list page can schedule up to 100 corresponding detail calls. A normal complete
run omits the cap and uses `--mode scheduled-full`:

```bash
uv run jobtology fetch run job_alio --mode scheduled-full
```

`scheduled-full` never accepts `--max-pages`; a truncated run must not look complete. A successful
fetch stops at `state=RUNNING, stage=FETCHED` because parsing, schema mapping, validation, and release
publication still have to run before the overall connector run may become `SUCCEEDED`.

## Storage and network boundary

- PostgreSQL records runs, planned requests, every retry, redacted URLs, response metadata, and raw
  snapshot manifests.
- Bodies are stored under
  `JOBTOLOGY_RAW_ROOT/raw/sha256/<first-2>/<next-2>/<sha256>` with write-once deduplication.
- Query-string credentials are redacted before persistence; rotating a credential does not change a
  logical request fingerprint.
- Every PostgreSQL run is bound to the checked-in rights-registry revision, source policy version,
  and deterministic policy hash. A missing, malformed, or blocked policy prevents planning/running.
- Endpoints must be HTTPS and match each connector's checked-in host allowlist. Redirects are not
  followed automatically.
- Responses are streamed with a 64 MiB decoded-body ceiling, and collection stops before the raw
  filesystem crosses its configured used-space/free-reserve thresholds. Goldship must use the
  plan's 100 GiB free-space reserve.
- The included development PostgreSQL publishes only to `127.0.0.1:55432`. On Goldship, keep
  ingestion, PostgreSQL, Neo4j, and operator UIs internal/localhost or Tailscale-only. This repository
  does not expose a public HTTP service; the separately deployed frontend remains the public edge.
- In the Coolify stack, replace the development DSN/password with runtime secrets and address
  PostgreSQL by its private service name on port 5432; do not publish that port. FE-to-BE remains on
  the private application network behind the FE's public domain, while database/admin access is not
  routed through that domain.

## Source IDs

```text
ncs_competency       NCS classification/competency API
ncs_qualification    NCS-to-qualification API (requires full versioned competency-unit codes)
qnet_schedule        Q-Net schedules partitioned by configured qualification item codes
ncs_career_path      One-time NCS career-path file (direct URL must be pinned)
job_alio             Official JOB-ALIO list plus every discovered posting detail
alio_organization    Official ALIO institution list
saramin              Saramin job-search API, partitioned by configured Korean keywords
work24_training      Work24 training API, including K-Digital course categories
```

The architecture and finalized ontology decisions are in
[docs/implementation-plan.md](docs/implementation-plan.md). Implemented source-contract changes are
recorded in [ADR 0001](docs/decisions/0001-official-source-contracts.md). The latest fetched-source
counts and current storage shape are in [the collection status report](docs/collection-status.md).
