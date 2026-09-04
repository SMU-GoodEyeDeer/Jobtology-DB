# Jobtology Data Platform: Finalized MVP Implementation Plan

- **Status:** Finalized for implementation
- **Date:** 2026-09-04
- **Repository:** `Jobtology-DB`
- **Product scope:** Noncommercial Korean university course project

## 1. Decision summary

Jobtology will ship as a grounded career-planning system for Korean university students. Its promised outcome is **application readiness by a target date**, never employment by that date. The MVP will support four canonical target occupations:

1. AI engineer (`AI_ENGINEER`)
2. Backend developer (`BACKEND_DEVELOPER`)
3. Frontend developer (`FRONTEND_DEVELOPER`)
4. Data analyst (`DATA_ANALYST`)

`아직 모르겠어요` is a discovery mode, not an occupation. The system will rank all four supported occupations from the user's entered capabilities and preferences. Selecting one ranked result ends discovery and creates the user's sole active targeted goal.

The MVP output is a versioned roadmap whose steps have exactly three states:

- `TODO`
- `IN_PROGRESS`
- `COMPLETED`

Each recommendation will be grounded in a reproducible corpus release. Source facts resolve to evidence records; derived numbers and recommendations resolve to reproducible calculation or decision traces; progress calculations reference their audited user-state events. The LLM chat will explain and navigate deterministic analysis and route-planning results; it will not calculate statistics, invent graph facts, or independently author a route.

Company-specific hiring forecasts, external-person enrichment, referrals, coffee-chat recommendations, automated applications, and commercial redistribution are excluded from the MVP.

## 2. Inputs assessed

### 2.1 Data repository

`Jobtology-DB` currently contains only a generic Python `.gitignore`. There is no existing schema, pipeline, test suite, migration, or deployment manifest to preserve.

### 2.2 Frontend proof of concept

The checked-out `../Jobtology-FE` worktree is on `test/test-branch` at `068afb5` and contains only the Vite starter. The actual PoC reviewed for this plan is the remote-tracking `origin/main` commit `f70b8dc`.

The PoC contains onboarding, a three-step survey, home, chat, roadmap, analysis, progress, and profile screens. It is already deployed and publicly reachable through its Coolify-managed HTTPS domain. It remains a visual requirements artifact: all domain values are hard-coded component constants or local state, and it has no API, persistence, authentication, shared DTOs, streaming, or citation implementation. Its deployment ownership remains outside `Jobtology-DB`.

The visual and code review established these product requirements:

- A central occupation picker with current posting counts.
- A profile containing major, university year, target occupation, priorities, constraints, tools, credentials, languages, projects, and experience.
- Separate required and preferred capability-coverage scores.
- A ranked missing-capability table with demand, difficulty, experience prevalence, and ways to achieve the capability.
- An ordered roadmap with reasons, supporting postings, learning options, dates, and progress.
- Upcoming credential, job, and training deadlines.
- A chat response that can include a route proposal and a typed recommendation graph.
- Evidence navigation behind `왜 필요한가요?`, `공고 보기`, graph nodes, and every numerical statement.
- Automatic recomputation when the user profile, capabilities, target date, or route preferences change.

### 2.3 Goldship

The target server has 30 GiB RAM and approximately 813 GiB free NVMe storage. Docker and Compose are installed and healthy.

The existing `/home/maxjo/jobtology` deployment runs Neo4j Community `2026.06.0`. The active `neo4j` database is logically empty: zero nodes, zero relationships, no user constraints, and only the default token indexes. Its approximately 541 MiB data volume is almost entirely preallocated transaction logs, not graph data.

Goldship has no application PostgreSQL instance and no object-storage service. The existing PostgreSQL and Redis containers belong exclusively to Coolify and will not be reused. There is no confirmed Jobtology backup process. Neo4j is already blocked from public access and reachable only through Tailscale. Its current wildcard host bindings are therefore a defense-in-depth hardening concern, not confirmed public exposure; Phase 0 replaces them with narrower bindings before data is loaded.

## 3. Product behavior fixed by this plan

### 3.1 Onboarding inputs

The frontend will collect and persist:

- One active target occupation from the four-role catalog, or discovery mode.
- Major as entered text. The resolver also stores a nullable normalized major concept; it remains null when no reviewed mapping reaches the acceptance threshold.
- Degree level fixed to `BACHELOR` for the MVP.
- University year `1 | 2 | 3 | 4`.
- Enrollment status `ENROLLED | LEAVE | GRADUATED`; `expected_graduation_on` is required for `ENROLLED` and `LEAVE` and null for `GRADUATED`.
- Existing capabilities grouped as skill/tool, credential, language, project, experience, and activity.
- Employer preferences: large enterprise and startup, represented as independent flags. Neither selected means no employer-type preference; both selected means either type is acceptable.
- Five independent route constraints. They are not mutually exclusive and default to false:
  - education-cost burden
  - must combine preparation with school or part-time work
  - fastest feasible path
  - insufficient portfolio/project experience
  - transition from a different major
- One target horizon:
  - `THIS_QUARTER`
  - `SIX_MONTHS`
  - `N_YEARS`, where `N` is an integer from 1 through 5

The backend will resolve the horizon to one exact RFC 3339 `target_by` instant in `Asia/Seoul` and retain the original Korean phrase:

- `THIS_QUARTER`: 23:59:59 on the last day of the current calendar quarter.
- `SIX_MONTHS`: 23:59:59 on the local date six calendar months later.
- `N_YEARS`: 23:59:59 on the local date `N` calendar years later.

Calendar addition preserves the day of month when it exists and otherwise clamps to the destination month's final day. A February 29 year target therefore resolves to February 28 in a non-leap year. All persisted instants include the `+09:00` offset.

The LLM will never perform deadline arithmetic.

### 3.2 Budget behavior

The product will expose exactly two budget modes:

- `REGULAR`
- `LOW_COST`

Selecting `교육비 부담이 커요` sets `LOW_COST`; leaving it unselected sets `REGULAR`.

This is a preference, not a fabricated won-denominated cap. The planner will use these fixed baseline objective weights:

| Mode | Requirement coverage | Completion time | Out-of-pocket cost |
|---|---:|---:|---:|
| `REGULAR` | 55% | 30% | 15% |
| `LOW_COST` | 35% | 20% | 45% |

`LOW_COST` ranks free, government-subsidized, and lower verified out-of-pocket options first. Unknown cost receives the worst cost rank and is never described as cheap. An exact monetary ceiling becomes a hard constraint only when the user explicitly supplies one in chat; the backend then stores it as `max_out_of_pocket_krw`.

When `fastest_path` is selected, 15 percentage points move to completion time: 10 from coverage and 5 from cost. The resulting weights are `45/45/10` for `REGULAR` and `25/35/40` for `LOW_COST`. Section 12 defines the normalized objective and hard constraints.

### 3.3 Weekly availability

The planner will use:

- 10 available hours per week when `학업·알바와 병행해야 해요` is selected.
- 20 available hours per week otherwise.

An exact integer from 1 through 60 stated in chat replaces this default after user confirmation and sets `availability_source=USER_OVERRIDE`. Changing the part-time flag does not alter a user override. The confirmed action `기본 시간으로 재설정` clears it, sets `availability_source=DERIVED_DEFAULT`, and immediately derives 10 or 20 hours from the current flag. Values outside the range are rejected.

### 3.4 Progress and coverage

Roadmap progress is calculated only as:

`completed step count / total actionable step count`

The target occupation is metadata and is not counted as an artificial final step.

A capability requirement is:

- `COMPLETED` when the user has a confirmed capability assertion that satisfies it.
- `IN_PROGRESS` when an active roadmap step is currently producing it.
- `TODO` otherwise.

Capability verification is stored separately as `SELF_REPORTED` or `VERIFIED`. A self-reported item can be completed without being falsely presented as independently verified.

The empty-state home screen will show no coverage percentage until a profile analysis exists. All pages will use the same server-calculated analysis object; the inconsistent hard-coded percentages and progress bars in the PoC will be removed.

## 4. Repository and service ownership

### 4.1 `Jobtology-DB`

This repository owns:

- Source registry and source-rights policy.
- Connectors and fetch scheduling.
- Immutable source snapshots and snapshot manifests.
- Parsing, OCR, normalization, Korean requirement extraction, and entity resolution.
- Schema.org alignment and the Jobtology extension vocabulary.
- NCS versioned taxonomy and mappings.
- Claim-level evidence and provenance.
- Posting cohorts and precomputed aggregates.
- Data-quality rules, review queues, golden fixtures, and evaluation.
- `jobtology_pipeline` PostgreSQL migrations, Neo4j corpus/projection schema migrations, and the deployment bootstrap for database creation and roles.
- Idempotent graph publication and corpus releases.
- Search materialization needed by grounded retrieval.
- Backfills, freshness monitoring, and deletion/retraction propagation.

### 4.2 Backend

The backend owns:

- Authentication and authorization.
- `jobtology_app` schema and migrations.
- User PII, profiles, consent, and deletion.
- Goals, saved roadmap versions, roadmap-step state, activities, and chat history.
- Natural-language goal and constraint interpretation.
- Deterministic capability-gap analysis requests.
- Candidate retrieval and route solving.
- LLM tool orchestration, streaming, explanation, and support validation.
- Explicit user confirmation before profile mutation, creation or activation of a saved roadmap, or any saved-plan state mutation; background jobs may update only analyses and validity metadata.
- Notification scheduling and frontend-facing APIs.

### 4.3 Frontend

The frontend owns presentation and user interaction only. It never connects directly to Neo4j or PostgreSQL. It formats numeric ratios, KRW amounts, dates, and D-days returned as typed values.

### 4.4 `Person` decision

Schema.org `Person` remains in the ontology. Each application user receives one Neo4j `Person` projection identified only by an opaque `person_id`. It contains the current `TARGETS_OCCUPATION` edge and one `HAS_CAPABILITY` edge for every non-revoked capability resolved to a `Skill` or `Credential`; project and experience records and unresolved free text stay only in the application database.

Names, email addresses, school identity, raw documents, goals, plan state, chat transcripts, and consent records remain in backend PostgreSQL. The backend is the sole writer of `Person` projections and user-owned relationships. `Jobtology-DB` defines their constraints and projection contract but never ingests student PII into the public corpus pipeline.

No third-party `Person` profiles or social connections will be collected in the MVP.

## 5. Final infrastructure architecture

```text
Official APIs and licensed feeds
              |
              v
    immutable raw filesystem ---------> Parquet snapshots
              |                                |
              v                                v
      PostgreSQL control/ledger ------> transform and QA
                                               |
                                               v
                                      Neo4j corpus release
                                               |
                                 typed backend retrieval tools
                                               |
                                  route solver + LLM explanation
```

### 5.1 Neo4j

The existing Neo4j Community `2026.06.0` container will be retained. APOC will not be installed for the MVP; loaders will use parameterized Cypher through the official Python driver.

Final resource settings:

- JVM initial and maximum heap: 5 GiB.
- Page cache: 4 GiB.
- Container memory limit: 14 GiB.
- JVM option `-XX:+ExitOnOutOfMemoryError`.
- Persistent data, logs, import, and plugin volumes.
- Image pinned by exact version and digest.

Community Edition's single standard database is not used as a blue/green boundary. Publication loads release-scoped data in place, verifies it, marks the graph release `READY`, and only then changes the authoritative `publication.active_release_id` in one PostgreSQL transaction. That transaction changes the prior `ACTIVE` row to `SUPERSEDED`, changes the selected `READY` or `SUPERSEDED` row to `ACTIVE`, and updates the pointer; PostgreSQL is authoritative and the graph state mirror is reconciled immediately afterward. Current browsing and every new analysis use that active release. An existing analysis, roadmap, trace, or chat explanation instead reads the non-revoked release ID pinned on that artifact. A calculation, solver run, or corpus-backed nested DTO may use only its declared release ID; a composite dashboard may contain differently pinned nested artifacts only because each declares its own ID. Rollback activates a non-revoked preceding `SUPERSEDED` release through the same transaction, and every non-revoked release remains online for the duration of the MVP.

Neo4j stores accepted canonical entities, append-only grounded claims, accepted mappings, aggregates, and release-scoped search projections. It does not store raw PDFs, HTML, API bodies, chat transcripts, or user PII. Neo4j Community has [no role-based authorization boundary](https://neo4j.com/docs/operations-manual/current/authentication-authorization/manage-users/): loader and backend credentials are separate only for rotation and audit attribution, and both are treated as database administrators. The loader credential exists only in scheduled ingestion jobs; backend access is limited to compiled parameterized repository methods, and no arbitrary Cypher endpoint exists.

### 5.2 PostgreSQL

A dedicated PostgreSQL 17 container named `jobtology-postgres` will be deployed and pinned by version and digest. It will use its own credentials, network, and volume. Coolify's database will remain untouched. The container hosts two isolated databases:

- `jobtology_pipeline`, owned by NOLOGIN role `jobtology_pipeline_owner`, migrated through `jobtology_pipeline_migrator`, and used by `jobtology_ingest`.
- `jobtology_app`, owned by NOLOGIN role `jobtology_app_owner`, migrated through `jobtology_app_migrator`, and used by `jobtology_backend`.

`CONNECT` and `TEMPORARY` are revoked from `PUBLIC` on both databases, and `CREATE`/`USAGE` are revoked from `PUBLIC` on application schemas. Runtime and migrator roles cannot connect across databases. One exception is a separate `jobtology_release_reader` role used through a second backend DSN: it can connect to `jobtology_pipeline`, has `USAGE` only on `publication`, and can `SELECT` only the one-row `publication.active_release` view plus security-barrier views `published_release_states`, `published_calculation_traces`, and `published_trace_support`. The state view exposes the lifecycle and revocation time of every published release. The trace views expose accepted, non-PII records for every non-revoked published release, keyed by `release_id`; none of the views confers underlying table privileges. A separate `jobtology_deletion_finalizer` login can read and acknowledge only deletion-request rows in `jobtology_app`. The backend application database is the source of truth for private user state and Person re-projection. PostgreSQL is limited to 3 GiB RAM with `shared_buffers=768MiB` and `effective_cache_size=2GiB`.

`jobtology_pipeline` schemas:

- `control`: source definitions, schedules, cursors, run state, retries, and locks.
- `raw_manifest`: source records, immutable snapshot metadata, hashes, headers, and rights observations.
- `staging`: parsed source-shaped records and normalized records.
- `assertion_ledger`: assertion history, evidence locators, review state, and retractions.
- `resolution`: aliases, match candidates, accepted/rejected entity merges, and reviewer decisions.
- `quality`: rule outcomes, quarantined records, corpus metrics, and evaluation results.
- `publication`: release manifests, graph publication state, and rollback metadata.

Large source bodies will not be stored in PostgreSQL.

### 5.3 Raw and analytical storage

No primary or self-hosted object-storage service will be added for the MVP. Goldship will use a content-addressed filesystem because it is simpler, auditable, and sufficient for the project scale. Cloudflare R2 is used only as the encrypted off-host `restic` backup target, not as live pipeline storage.

Root path:

`/home/maxjo/jobtology-data`

Layout:

```text
/home/maxjo/jobtology-data/
  raw/sha256/aa/bb/<full-sha256>
  parquet/<source>/<snapshot-date>/part-*.parquet
  exports/<corpus-release-id>/
  backups/restore-sets/<backup-set-id>/manifest.json
  backups/restore-sets/<backup-set-id>/postgres/
  backups/restore-sets/<backup-set-id>/neo4j/
```

The local `backups/restore-sets/` tree is a restore staging cache, not an independent backup; a run counts as successful only after the encrypted R2 restic snapshot and checksum verification succeed.

The content snapshot manifest records MIME type, byte length, checksum, original URL, encoding, and license. Per-request timestamps, request/response headers, status, and retry data live in immutable `FetchObservation` rows so an unchanged body can be observed again without rewriting or duplicating its `SourceSnapshot`. Raw files are write-once; a changed response creates a new hash-addressed object. The sole exception is a rights-driven purge: it deletes prohibited bytes, records a non-reversible tombstone containing the hash and reason, retracts dependent assertions, marks every containing release `REVOKED`, exposes that state through `published_release_states`, removes or masks its graph evidence projections, and republishes without the content. The backend checks release state on every pinned-artifact read and polls the state view each minute to persist roadmap invalidations. A revoked release cannot be queried, activated, or used for rollback.

At 04:00 KST every day, one coordinated restore-set backup runs under maintenance mode and the host global lock. It drains in-flight backend projection/deletion workers, pauses the deletion finalizer, creates a unique `backup_set_id`, freezes application and pipeline writes, and records the authoritative active release. `pg_dump -Fc --no-owner` dumps both PostgreSQL databases while no cross-database state can change. Following Neo4j's [offline backup procedure](https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/), the Neo4j container stops; the matching pinned `neo4j-admin` image runs as the `neo4j` user and dumps both `neo4j` and `system` into the same mode-`0700` restore-set directory. It applies the documented [dump consistency check](https://neo4j.com/docs/operations-manual/current/backup-restore/consistency-checker/) to each archive with `--from-path=<exact-dump-file>`, `--threads=4`, `--max-off-heap-memory=3G`, and a run-specific `--temp-path`. A failure-safe cleanup handler always restarts Neo4j and waits for health. It resumes paused workers and exits maintenance mode after a verified local set, or after a failed backup only when Neo4j and both PostgreSQL databases pass health checks; a failed health check leaves maintenance mode enabled for operator recovery.

The run waits for health, verifies that the Neo4j release checksum equals the frozen PostgreSQL pointer, and executes one smoke query. It then writes an immutable restore-set manifest containing all four dump hashes, exact database images, migration heads, active release ID, and the raw-manifest high-water mark. Its object list contains every non-purged raw and Parquet hash referenced by a committed pipeline row at or below that high-water mark, including unpublished staging/quarantine inputs and every non-revoked release—not only the active release. Maintenance mode ends after that local set verifies, but the host lock remains held. `restic` uploads exactly the manifest, four dumps, and those manifest-enumerated objects to a private Cloudflare R2 bucket and verifies the resulting snapshot before the lock is released; newer files are not silently added to that set, and a rights purge cannot race the upload. It never copies a live Neo4j volume. A failed dump, consistency, health, or checksum check keeps publication disabled and cannot become the latest verified set. A failed R2 upload keeps the local set, marks the run failed, retries hourly, and makes doctor unhealthy; publication is disabled when the last verified off-host set reaches 26 hours. PostgreSQL roles and credentials are recreated from the root-owned bootstrap rather than dumped; Neo4j authentication is recreated from that bootstrap and rotated after restore.

The R2 bucket contains separate encrypted restic repository prefixes for coordinated restore sets and the deletion ledger. Restore-set retention is 14 daily, 8 weekly, and 6 monthly sets, enforced weekly by `restic forget --prune` against that repository only. `restic check` runs weekly and `restic check --read-data-subset=10%` runs monthly on both repositories. The latest two complete verified restore sets remain in local staging; an older set is removed only after its matching R2 snapshot verifies. Backup processes use `umask 077`, directories mode `0700`, and dump files mode `0600`. The RPO is 24 hours for PostgreSQL, Neo4j, and raw data. The RTO is 4 hours from a verified local coordinated set and 8 hours from R2 or a corpus rebuild. An isolated scratch restore of both PostgreSQL databases, both Neo4j databases, the enumerated raw snapshot, and the latest deletion ledger runs after initial setup, monthly, and within 48 hours before the final demonstration.

The R2 token is restricted to the one backup bucket and its two repository prefixes. Both restic repository passwords are stored in the operator's off-host password manager as well as root-only runtime secrets, never only on Goldship. Normal restore-set retention never selects a deletion-ledger snapshot. A user-deletion ledger entry, every off-host snapshot needed to preserve it, and its versioned HMAC key are retained until both seven calendar months have elapsed and the verified restore-set repository index contains no retained backup predating that deletion. The weekly ledger-retention job then removes eligible local event files, creates and verifies a replacement ledger snapshot containing every still-required event, and only afterward forgets and prunes older ledger snapshots. Tombstones are replayed after every restore, and the privacy notice states that encrypted backup copies expire within six months.

The deletion ledger is an append-only root-owned file set under `/home/maxjo/jobtology-data/deletion-ledger`, containing only event ID, deletion timestamp, HMAC key version, and an HMAC of the internal user ID. A dedicated root-owned `jobtology-deletion-finalizer.service` supervises the sole root-running operations container. That container mounts only the ledger, restic configuration, the exact host global-lock file, and a shared runtime-socket directory; it joins the private database and outbound bridges, holds the runtime HMAC key escrowed off-host, and has no TCP listener. Its mode-`0660`, `root:jobtology-backend` Unix socket is mounted into the non-root backend container. The backend transaction revokes the account, removes PII and private records, creates a `DeletionRequest`/outbox row retaining only the opaque internal ID, and returns `202 Accepted` with a random status receipt. The backend outbox worker deletes the Neo4j `Person` projection and records `graph_deleted_at`, then submits only the request ID through that socket. The finalizer accepts only a request with that graph acknowledgement, takes `flock` on the bind-mounted host lock inode, validates and reads the row using its restricted database login, computes the HMAC, atomically creates and `fsync`s one mode-`0600` event file named by the immutable request ID, and creates a verified R2 snapshot tagged with that ID. It then removes the unhashed ID and marks the request `COMPLETED` in one database transaction before releasing the lock. A retry reuses and verifies the existing event file/snapshot tag, so interruption cannot duplicate the event or lose its acknowledgement path. Each attempt has a 10-minute execution limit. A failed attempt remains `PENDING` and retries after 1, 5, 15, 30, and 60 minutes, then hourly until completion; it is never reported as completed. The receipt can query only that request while pending and for seven days after completion.

On every restore, traffic stays in maintenance mode while all Neo4j Persons/private edges are removed, current users are re-projected from the restored app database, the off-host deletion ledger is applied, and user/count checksums pass. This prevents an older app or graph dump from resurrecting a deleted projection.

Raw objects are written to a temporary file on the same filesystem, flushed and `fsync`ed, atomically renamed to the content-hash path, and only then referenced by a committed PostgreSQL manifest row. A crash can therefore leave only an unreferenced immutable object, which the weekly garbage report identifies without deleting automatically.

### 5.4 Network and secrets

- The Coolify-managed HTTPS product domain is the only public ingress. It serves the frontend and the same-origin application API. Neo4j Browser, database and administration endpoints, pipeline review and operations UIs, monitoring tools, and every other internal Web UI remain Tailscale-only. Public-source connectors retain outbound HTTPS access.
- Phase 0 preserves the public Coolify product route and existing tailnet-only administration while removing the defense-in-depth risk from wildcard database host bindings. PostgreSQL publishes no host port; Neo4j `7474` and `7687` bind only to `127.0.0.1`; the current host `8443` database proxy is removed.
- The deployment creates two named cross-stack bridges with `internal: true`: `jobtology-data-internal` joins only Neo4j, PostgreSQL, backend, ingestion, and scoped operations jobs; `jobtology-app-internal` joins only the deployed frontend gateway and backend. The frontend gateway alone also joins Coolify's existing proxy network. Backend joins both private bridges plus `jobtology-egress`; ingestion joins the data bridge plus egress; the ephemeral backup job and deletion finalizer join the data and egress bridges only for their scoped operations. Database containers never join the application, Coolify proxy, or egress bridges.
- Containers never use `localhost` to reach another container. The backend uses `bolt://neo4j:7687` and the PostgreSQL service name over `jobtology-data-internal`; the frontend gateway proxies `/api/*` and the chat SSE route to the backend service over `jobtology-app-internal`. The browser calls same-origin `/api`, never a database address or the student's localhost. Proxy buffering is disabled for SSE and its upstream read timeout is five minutes.
- Coolify terminates public TLS for the product domain and routes it to the deployed frontend gateway. That gateway serves `/` and proxies `/api/*`, including chat SSE, to the backend over `jobtology-app-internal`. The backend has no separate public hostname or host port. Authentication, authorization, per-user rate limits, request-size limits, same-origin cookie and CSRF protection, and a no-wildcard CORS policy apply at the gateway and backend. Neo4j Browser administration uses a Tailscale SSH local port forward to Goldship's loopback ports and connects explicitly to `bolt://localhost:7687`; host `localhost` is reserved for this administration path and local health checks.
- Outbound clients are fixed and do not accept a user-supplied URL: ingestion permits registered source hosts and the model endpoint, backup/finalizer permits the configured R2 endpoint, and backend chat permits the configured model endpoint. The egress bridge provides outbound transport, while these application allowlists provide destination restriction.
- Host-firewall rules deny database ports on every non-loopback interface. Internal-tool ports may bind only to an explicitly assigned Tailscale address when direct tailnet access is required. A deployment preflight checks the actual listening sockets and fails if any database, database-admin, or internal-tool port binds publicly; Coolify-managed HTTP-to-HTTPS redirection and HTTPS routing are the only Jobtology public-ingress exceptions.
- The frontend never receives database credentials.
- Secrets stay outside Git in deployment environment files with owner-only permissions.
- Pipeline logs redact credentials, user-entered PII, and raw chat content.

## 6. Implementation stack

The ingestion system will use:

- Python 3.12
- `uv` for environment and dependency locking
- Typer for the pipeline CLI
- Pydantic v2 for domain and connector contracts
- HTTPX for HTTP clients
- Tenacity for bounded retries
- SQLAlchemy 2, Alembic, and psycopg 3 for PostgreSQL
- Official Neo4j Python driver
- Polars and PyArrow for normalized snapshots and aggregates
- lxml and selectolax for XML/HTML
- PyMuPDF for born-digital PDF text and coordinates
- OCRmyPDF with Tesseract 5 `kor` and `eng` language packs for scanned PDFs
- ZIP/XML plus lxml for HWPX; sandboxed LibreOffice headless conversion to PDF for legacy HWP, DOCX, XLSX, and other office attachments; failed or encrypted conversions enter quarantine
- RDFLib and pySHACL for JSON-LD/RDF export validation
- OpenAI Python SDK and the Responses API
- structlog for JSON logs
- pytest, Ruff, and Pyright for verification

The MVP's constrained extraction runtime is the hosted [`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna) model with Structured Outputs. The same model is the backend chat default because chat only orchestrates typed tools and explains supported results. Goldship runs no local language model and needs no GPU. Every Responses API call sets `store: false`. Each call records the requested model ID, model ID returned by the provider, prompt hash, schema version, response ID, token usage, and raw structured result. A model change is a new extractor and methodology version and requires the frozen evaluation suite before publication.

The MVP scheduler will use root-owned systemd timers on Goldship. Each timer invokes the same idempotent CLI inside the ingestion container. Units run `After=docker.service tailscaled.service network-online.target`, declare `RequiresMountsFor=/home/maxjo/jobtology-data`, and use `Persistent=true`. `TimeoutStartSec` is 15 minutes for incremental connectors, 4 hours for backfills, 30 minutes for publication, 2 hours for backup, and 8 hours for restore/full rebuild; `TimeoutStopSec=5min`.

The host unit runs `flock -n /run/lock/jobtology-global.lock -- docker compose run ...`, and that host process retains the file descriptor for the entire job. Every manual backup, migration, publication, purge, and restore must use the same checked-in wrapper. The deletion finalizer is the sole exception to host-side acquisition: it locks an explicit bind mount of that same host file, and deployment preflight verifies the host/container device-and-inode pair before enabling it. Normal online jobs and scratch restores also open one dedicated `jobtology_pipeline` connection, acquire advisory lock key `74120260904`, and hold that connection through cleanup. Initial bootstrap and a production restore rely on maintenance mode plus the host lock while PostgreSQL is absent or being replaced; immediately after `jobtology_pipeline` is restored, they acquire the advisory lock for validation and reconciliation. The host filesystem lock is the cross-container and cross-database authority; the advisory lock is a second guard only while its database exists. A workflow-orchestration server will not be introduced.

KST timers are staggered: the JOB-ALIO recruitment API at `01:10`; Q-Net at `01:40`; NCS APIs Mondays at `02:10`; monthly NCS career-path update check and ALIO institution API refresh on day 2 at `02:30` and `02:40`; corpus publication at `03:00`; the coordinated restore-set backup daily at `04:00`; and doctor every 15 minutes. Saramin's former four daily slots and Work24's `00:40` slot are not installed while their rights policies are blocked; their activation ADR must define quota-safe cadences before adding timers. A lock miss exits with code `75` and triggers a retry exactly 10 minutes later, up to 12 attempts; exhaustion writes a failed run and makes doctor unhealthy. It never waits silently until the next normal cadence.

Application containers run as non-root. The deletion finalizer is the sole root-running operations container and has a 512 MiB memory and one-CPU limit. Fixed container limits are Neo4j 14 GiB, PostgreSQL 3 GiB, ingestion 4 GiB, and backend 2 GiB; at most one OCR/model/backfill job runs concurrently. Neo4j admin/check and scratch-restore jobs are separately limited to 6 GiB, 4 CPUs, and `--max-off-heap-memory=3G`, with temporary extraction under `/home/maxjo/jobtology-data/tmp` and required free space of twice the dump size plus 100 GiB.

Before a heavy job, admission requires `MemAvailable - requested_job_memory >= 6GiB`; a 4 GiB ingestion job therefore requires at least 10 GiB available and a 6 GiB admin job requires 12 GiB. The check repeats every minute during the job, and the job aborts at its next checkpoint if the remaining reserve falls below 4 GiB.

Every command accepts a `run_id`, supports dry-run validation, writes its state to PostgreSQL, and exits nonzero when publication safety checks fail.

`jobtology doctor` runs every 15 minutes and after deploy, publication, backup, restore, and upgrade. It checks container health, host sockets, Docker network `Internal` flags, Neo4j advertised settings, active-release agreement and checksums, migration heads, last successful off-host coordinated restore-set age below 26 hours, last scratch-restore drill age below 35 days, restic integrity, source freshness, deletion-finalizer health, any deletion request pending longer than 15 minutes, and disk pressure. It warns at 75% disk use and stops new fetches at 85% use or below 100 GiB free, whichever happens first. Every unit failure is written to journald and the quality ledger.

Automatic container updates are disabled. Before a Neo4j or PostgreSQL update, the operator verifies backups, restores them into scratch volumes using the candidate exact-digest images, runs migrations, database checks, and smoke tests, then cuts over in a maintenance window. The untouched old volume and pre-upgrade dumps remain for 14 days. PostgreSQL stays on major version 17 throughout the MVP.

GitHub Actions is the fixed CI system. Pull requests run Ruff, Pyright, unit tests, contract tests, golden-fixture tests, SHACL validation, migration checks, secret scanning, and a container build. Network integration tests run manually against sandbox credentials and never run on untrusted pull requests.

## 7. Source plan

### 7.1 Included sources

| Source | MVP use | Stable identity | Refresh |
|---|---|---|---|
| [HRDKorea NCS competency API](https://www.data.go.kr/data/15063879/openapi.do) | Versioned hierarchy, competency units, levels, definitions | Full versioned NCS code | Weekly complete enumeration; unchanged bodies deduplicate by hash |
| [NCS competency-to-qualification API](https://www.data.go.kr/data/15074404/openapi.do) | Official competency, qualification, required/elective unit, and training-hour links | NCS code plus qualification code | Weekly complete enumeration |
| [Q-Net qualification schedule API](https://www.data.go.kr/data/15074408/openapi.do) | Registration, exam, and result dates | Qualification, year, and examination round | Daily complete enumeration |
| [NCS career-path one-time dataset](https://www.data.go.kr/data/15088716/fileData.do) | Seed occupation, competency, level, and rank relations | Deterministic row composite within the file SHA-256 | Monthly official-metadata and file-integrity update check; ingest only a changed official revision |
| [JOB-ALIO recruitment API](https://www.data.go.kr/data/15125273/openapi.do) | Public-sector posting list/detail fields and attachment metadata; attachment bytes are excluded pending a rights revision | `recrutPblntSn` | Daily complete list/detail enumeration |
| [ALIO institution API](https://www.data.go.kr/data/15125287/openapi.do) | Official public-institution identity and organization facts | Official institution code `instCd` | Monthly complete enumeration |
| [Saramin Open API](https://oapi.saramin.co.kr/guide/job-search) | Private-sector posting discovery metadata for the four target occupations; not a full-JD requirement source | Saramin posting `id` | Blocked until written rights and a sufficient quota contract are recorded; a later ADR fixes its production cadence |
| [Work24 training API](https://www.work24.go.kr/cm/e/a/0110/selectOpenApiSvcInfo.do?fullApiSvcId=000000000000000000000000000004) | NCS-linked training, K-Digital offerings, tuition, dates, and capacity | Training ID plus round | Daily complete enumeration after rights activation |
| `INTERNAL_EDITORIAL` | Reviewed major aliases, skill-practice, project, application-prep, and occupation-foundation templates | Git blob hash plus template ID/version | On merge to main |

The project will obtain and document the required API approvals before connector activation. Source attribution and back-links required by each provider will be carried through the API contracts to the frontend.

### 7.2 Excluded sources

The MVP will not ingest:

- LinkedIn profiles, connections, or jobs.
- JobKorea or Wanted pages.
- Work24 vacancy listings.
- Unlicensed company-career-page crawls.
- Data broker or reseller exports without a written data license.

A paid account is not treated as an ingestion license. LinkedIn crawling is explicitly excluded by its [anti-scraping policy](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions).

### 7.3 Rights registry

Every source and attachment receives a versioned rights policy containing:

- source owner and dataset ID
- license code and URL
- observed date
- attribution text
- commercial-use permission
- derivative-use permission
- raw-retention permission
- normalized-fact storage permission
- short evidence-excerpt storage and display permission
- embedding/model-use permission
- redistribution permission
- required source link
- deletion/correction contact and procedure
- `backup_retention_days`

An ingestion connector cannot be activated until its rights record explicitly permits the required retrieval, raw retention, normalized facts, short evidence excerpts, and model processing. A denial or unknown value blocks publication from that source; it is not silently downgraded to ungrounded data. Public availability never implies unrestricted use. Full NCS module documents will not be redistributed or used for model training when they contain third-party diagrams, photographs, or illustrations. User data will follow the PIPC's [public-personal-data guidance](https://pipc.go.kr/np/cop/bbs/selectBoardArticle.do?bbsId=BS074&mCode=C020010000&nttId=10362).

The checked-in initial registry activates the six public-data API/file sources. Saramin and Work24
remain blocked until written permission covers retention, normalized facts, evidence excerpts, and
model processing. JOB-ALIO scope includes its official JSON and embedded attachment metadata, not
the linked attachment bytes. Every connector run stores the registry revision, source policy version,
and registry hash that authorized it.

When a rights purge requires removal before normal backup expiry, publication stops and the operator resolves the affected hashes/assertions through both R2 and local restore-set manifests. After live raw, PostgreSQL, and Neo4j content is purged and the affected releases are revoked, the operator creates and verifies one clean coordinated restore set. The operation then forgets and prunes every affected R2 restore-set snapshot, removes every affected local restore-set directory rather than retaining it in the two-set cache, and verifies that neither manifest index can resolve the prohibited hashes before publication resumes. The rights tombstone and audit metadata survive, but prohibited bytes and excerpts do not.

## 8. Data flow and publication

Each connector executes the same state machine:

1. **Discover:** enumerate source keys and modified timestamps.
2. **Fetch:** save response body and request/response metadata under a content hash.
3. **Parse:** convert the source body to a typed source-shaped record and a versioned normalized-text artifact.
4. **Normalize:** map dates, currency, organizations, occupation codes, and source fields to canonical contracts.
5. **Extract:** identify requirement and learning-outcome claims with exact Korean evidence spans.
6. **Resolve:** map aliases to canonical occupations, skills, credentials, and organizations.
7. **Validate:** run contract, provenance, temporal, rights, and referential-integrity checks.
8. **Review:** quarantine ambiguous mappings and medium-confidence model extractions.
9. **Aggregate:** create versioned posting cohorts and demand observations.
10. **Publish:** load an immutable corpus release manifest and activate it only after all release checks pass.

Every source execution first creates one pipeline-only `ConnectorRun`. Its contract is `connector_run_id`, `run_id`, source ID, connector version, rights-registry revision, rights-policy version/hash, `mode = SCHEDULED_FULL | BACKFILL`, started time, nullable source-watermark/completed times, discovered-key count and manifest hash, planned/successful request counts, pagination terminal marker, all-attempt and selected-success observation-set hashes, validation report ID/hash, nullable source-count-override ID/hash, and `state = RUNNING | REVIEW_REQUIRED | SUCCEEDED | FAILED`. All production cadences in Section 7.1 use `SCHEDULED_FULL`; `BACKFILL` never advances freshness or absence detection. Legal transitions are `RUNNING -> SUCCEEDED | REVIEW_REQUIRED | FAILED` and `REVIEW_REQUIRED -> SUCCEEDED | FAILED`; `SUCCEEDED` and `FAILED` are terminal.

`SUCCEEDED` is legal only after discovery finishes, every planned key/page has one successful response, response schemas validate, and the connector's checked-in completeness mode passes. The two NCS APIs, Q-Net, JOB-ALIO recruitment API, ALIO institution API, Saramin, and Work24 use `DECLARED_TOTAL`: within each checked-in request/filter partition, its unique primary-key count must equal its source-reported total and every page number must be contiguous; the run-level record set is the union by source primary key, so a record returned by two valid partitions is retained once. For JOB-ALIO, the primary key is `recrutPblntSn`, every discovered detail request must succeed, and attachment metadata is validated as part of that detail response; linked attachment bytes are not scheduled. The NCS career-path dataset uses `SINGLE_FILE`: HTTP completion, expected MIME/signature, nonzero bytes, required columns, and full parser completion are mandatory. Its scheduled run checks the official metadata and current file; an unchanged file reuses its existing content-addressed snapshot, while a changed official file creates a new revision for ingestion. A zero API result requires an immediate second complete request that also explicitly reports zero. From the eighth successful full run onward, a unique-record count below 60% of the median of the preceding seven enters `REVIEW_REQUIRED`. A `SourceCountOverride` is immutable and contains override ID, bound connector-run ID, observed count, baseline median, reason, `decision = APPROVED | REJECTED`, reviewer ID, reviewed timestamp, and expiry exactly 24 hours later. Approval before expiry atomically binds its ID/hash, recomputes the validation report, and moves that run to `SUCCEEDED`; human rejection binds its audit record and moves the run to `FAILED`; expiry without a decision appends a system expiry event and moves the run to `FAILED`. Cancellation, missing totals or terminal markers, page gaps, duplicate primary keys inside one pagination partition, exhausted requests, and parser truncation move directly to `FAILED` and are not overrideable.

Every HTTP attempt appends one immutable `FetchObservation` keyed by `(connector_run_id, request_fingerprint, response_ordinal, attempt_no)`; a retry increments `attempt_no` and never overwrites the failed attempt, while a later scheduled run creates a new series even when the body is unchanged. A successful observation references the content-addressed `SourceSnapshot`; failures have no snapshot. Each logical request names exactly one selected successful observation after retries finish. A complete run hashes both the full attempt set and the selected-success set, and sets `source_watermark_at` to the maximum `retrieved_at` among that selected-success set. Source freshness advances only to `source_watermark_at` of the latest `SUCCEEDED SCHEDULED_FULL` run, never from an individual response, validation/override time, or file modification time. Entity `last_seen_at` is the selected successful observation time for that entity inside such a run. Failed, incomplete, review-pending, and backfill runs remain queryable for operations but contribute neither freshness nor last-seen updates.

Every `serving_scope=MVP` release requires all eight external sources in Section 7.1 plus the current `INTERNAL_EDITORIAL` revision. It selects the newest eligible `SUCCEEDED SCHEDULED_FULL` run for each external source and persists those IDs in PostgreSQL, the release manifest, and the Neo4j `CorpusRelease`. Its `data_as_of` is the minimum `source_watermark_at` across those eight selected runs, normalized to an RFC 3339 `+09:00` instant. It is a conservative corpus watermark; a cohort's own `as_of` and each event's source-valid timestamp remain separately available. A Phase 0 release with no external input has `serving_scope=BOOTSTRAP` and `data_as_of=created_at`; it cannot serve analyses, roadmaps, or chat. Every product response copies `data_as_of` from its pinned `serving_scope=MVP` release rather than recalculating it.

Content-derived parse/extract/resolve stages use idempotency key `(source_id, source_record_id, content_sha256, pipeline_version)`, while the observation-time projection uses `(entity_id, connector_run_id, projection_version)`. Reprocessing either key produces no duplicate snapshot, assertion, revision, observation state, or graph entity. A later successful full run creates a new immutable `EntityObservationState` for changed seen/absence state while reusing the unchanged content revision and its claims; observation time alone never creates an `EntityRevision`.

Normalized text uses Unicode NFC and LF newlines. Text offsets are zero-based, half-open Unicode code-point indexes into a specific normalized-text hash. PDF evidence additionally records a one-based page and bounding box in PDF points. Each parsed artifact stores its own SHA-256, parser/OCR version, source hash, and a raw-to-normalized page/offset map.

Claims have stable IDs independent of a corpus release. Release membership is many-to-many in the PostgreSQL manifest and in Neo4j as `(:CorpusRelease)-[:INCLUDES]->(:SourceSnapshot|:EntityRevision|:EntityObservationState|:Assertion|:PostingCohort|:AggregateObservation)`. A content revision or claim reused unchanged in a later release gains membership; it is not duplicated or rewritten. `EntityObservationState` is instead a release-specific derivation because elapsed wall time can change serving state without changing source content. Only accepted, non-retracted claims can be included.

Publication first verifies that each required source maps to one eligible completed connector run, both observation-set hashes and the validation report hash match, any bound source-count override is accepted and unexpired at run transition time, its records are fully accounted for by accepted rows or explicit quarantine/exclusion rows, and all freshness limits pass. It then writes and checks all release memberships and release-scoped projections, marks the graph release `READY`, and atomically changes PostgreSQL's active-release pointer. Current-state readers obtain the active ID once per request. Reads performed for an existing artifact obtain its pinned release ID and verify that it remains non-revoked; every repository call in that operation receives the same selected ID. A failure before the pointer change leaves the prior release active.

Neo4j corpus data is always rebuildable from raw snapshots, the `jobtology_pipeline` ledger, and release manifests. Publication never deletes `Person` nodes or their private edges. After a full graph restore, the backend idempotently re-projects current Persons from `jobtology_app` before user traffic is restored.

## 9. Ontology and graph schema

### 9.1 Vocabulary policy

Schema.org is the interchange vocabulary. It does not dictate the internal property-graph layout.

Primary alignments:

| Jobtology concept | Schema.org alignment |
|---|---|
| Job posting | [`JobPosting`](https://schema.org/JobPosting) |
| Canonical occupation | [`Occupation`](https://schema.org/Occupation) |
| Employer/training provider | `Organization` |
| Application user | `Person` |
| Skill or controlled term | `DefinedTerm` |
| University major concept | `DefinedTerm` |
| NCS classification | `CategoryCode` and `DefinedTermSet` |
| Credential | [`EducationalOccupationalCredential`](https://schema.org/EducationalOccupationalCredential) |
| Course catalog entry | [`Course`](https://schema.org/Course) |
| Dated training cohort | `CourseInstance` |
| Historical employment | `Role` |

The repository will version:

- `ontology/context.jsonld`
- `ontology/shapes.ttl`
- `ontology/terms.yaml`
- `ontology/mappings/`

`jt:` defines the custom claim, evidence, planning, temporal, and aggregate concepts. SHACL validates the export representation; Pydantic validates pipeline records.

### 9.2 Canonical node labels

Reference graph:

- `ConceptScheme`
- `Occupation`
- `Skill`
- `MajorConcept`
- `NCSClass`
- `NCSCompetencyUnit`
- `Credential`
- `Organization`
- `Place`

Market and learning graph:

- `JobPosting`
- `Course`
- `CourseInstance`
- `ExamSession`
- `ApplicationWindow`
- `ActionTemplate`

Grounding graph:

- `Source`
- `SourceSnapshot`
- `EntityRevision`
- `EntityObservationState`
- `EvidenceSpan`
- `Assertion`
- `RequirementClaim`
- `LearningOutcomeClaim`
- `SkillMappingClaim`
- `PostingCohort`
- `AggregateObservation`
- `CorpusRelease`

Private projection:

- `Person`

Every specialized claim node carries both `Assertion` and its subtype label, for example `:Assertion:RequirementClaim`. Every entity revision similarly carries `EntityRevision` plus a type label such as `:EntityRevision:JobPostingRevision`. `Skill.kind` is exactly `SKILL`, `TOOL`, or `LANGUAGE`; tools and languages do not create parallel vocabularies. Canonical nodes are stable identity shells. Display names, descriptions, aliases, dates, prices, source-supplied states, mappings, and other source-changing facts live in assertions or content-addressed revisions selected through corpus-release membership; observation-derived serving state lives in the release-specific `EntityObservationState`. Rollback therefore never reads current properties with an old release pointer.

### 9.3 Minimum canonical contracts

All IDs are opaque stable strings, all timestamps are RFC 3339, and every nullable field is shown explicitly below. Fields not marked nullable are required before publication.

| Identity shell | Stable fields only |
|---|---|
| `ConceptScheme` | `jt_id`, `scheme_code` |
| `Occupation` | `jt_id`, `occupation_code`, `scheme_id` |
| `Skill` | `jt_id`, `skill_code`, `kind`, `scheme_id` |
| `MajorConcept` | `jt_id`, `major_code` |
| `NCSClass` | `jt_id`, full versioned NCS code, base code, version, level |
| `NCSCompetencyUnit` | `jt_id`, full versioned unit code, base code, version |
| `Credential` | `jt_id`, qualification code |
| `Organization` | `jt_id` |
| `Place` | `jt_id`, country and administrative codes |
| `JobPosting` | `jt_id`, source ID, source record ID |
| `Course` | `jt_id`, source ID, source course ID |
| `CourseInstance` | `jt_id`, course ID, source round ID |
| `ExamSession` | `jt_id`, credential ID, year, round |
| `ApplicationWindow` | `jt_id`, owner entity ID |
| `ActionTemplate` | `jt_id`, `kind ∈ {SKILL_PRACTICE, PROJECT, APPLICATION_PREP}` |
| `Source` | `source_id`, owner, dataset ID |
| `Person` | opaque `person_id`; no name, email, school, document, or chat content |

Immutable records selected through release membership; `release_id` appears on a record only when the record itself is a release-specific cohort or derivation:

| Record | Required contract |
|---|---|
| `SourceSnapshot` | `snapshot_id`, source identity, content SHA-256, byte length, MIME type, first-observed-at, raw object path, parser state |
| `EntityRevision` | `revision_id`, entity ID/type, source snapshot ID, normalized-payload SHA-256, valid/system time, typed normalized payload |
| `JobPostingRevision` | title, canonical URL, description-text hash, posted/valid-through times, `source_status ∈ {OPEN, CLOSED, UNKNOWN}`, employment type, experience bounds, organization ID, primary occupation ID, place/work mode |
| `OrganizationRevision` | Korean name, employer type, active; official key, registration ID, verified domain, English name, and size band are nullable |
| `CredentialRevision` | Korean name, issuing organization ID, credential type, active; level and expiration rule are nullable |
| `PlaceRevision` | Korean display name and active state |
| `CourseRevision` | Korean title, provider organization ID, active |
| `CourseInstanceRevision` | enrollment/start/end times, delivery mode, `source_availability ∈ {OPEN, FULL, CLOSED, UNKNOWN}`, cost status/bounds, eligibility rules, schedule, total hours |
| `ExamSessionRevision` | application window, exam time, result time nullable, fee nullable |
| `ApplicationWindowRevision` | opens-at nullable, closes-at, timezone, active state |
| `ActionTemplateRevision` | template version, Korean title/instructions, occupation IDs, effort, prerequisites, typed capability/project outcomes, completion criteria, cost state, review metadata |
| `TaxonomyRevision` | Korean/English names, aliases, definitions, parents, active state, foundation skill IDs, publisher/version metadata as applicable |
| `SourceRevision` | canonical URL, connector version, rights-policy version, refresh policy, active state |
| `EntityObservationState` | `observation_state_id`, entity ID/type, selected revision ID, source and connector-run IDs, first/last-seen times, consecutive-absence count, serving state, evaluated-at, methodology version, release ID |
| `EvidenceSpan` | `evidence_id`, snapshot ID, parsed-artifact hash, typed locator, excerpt hash; short Korean excerpt is nullable only in internal processing and required for publication/UI display |
| `Assertion` | `claim_id`, subject, predicate, object or literal, qualifiers, assertion kind, confidence, review status, evidence IDs, extractor version, valid/system time |
| `PostingCohort` | `cohort_id`, occupation ID, exact filter JSON/hash, as-of, window bounds, member/exclusion counts, release ID |
| `AggregateObservation` | `aggregate_id`, cohort ID, nullable requirement key, metric, numerator, denominator, unknown count, value nullable, methodology version, support count/hash, release ID |
| `CorpusRelease` | `release_id`, manifest SHA-256, created-at, `data_as_of`, `serving_scope ∈ {BOOTSTRAP, MVP}`, pipeline version, methodology version, `state ∈ {PREPARING, READY, ACTIVE, SUPERSEDED, REVOKED}`, selected connector-run IDs, member counts and per-kind membership hashes |

`revision_id` is `sha256(JCS({entity_id, entity_type, source_snapshot_id, normalized_payload, valid_time}))`. Revision payloads are validated by entity-type JSON Schema and stored as typed Neo4j properties, not opaque JSON. `Organization.employer_type` is `LARGE_ENTERPRISE | STARTUP | OTHER | UNKNOWN` and comes only from an official/source field or a reviewed mapping. `MajorConcept.field_group` is `COMPUTING | ENGINEERING | NATURAL_SCIENCE | BUSINESS | HUMANITIES_SOCIAL | ARTS | OTHER`. `CourseInstance.delivery_mode` is `ONLINE | OFFLINE | HYBRID`. Publication validation enforces the cardinalities in the relations below.

The PostgreSQL-only `FetchObservation` contract is `observation_id`, connector-run/source/request identity, response ordinal, attempt number, nullable snapshot ID, requested/retrieved timestamps, HTTP status, redacted request/response headers, outcome, and error code. Release manifests record each selected `SUCCEEDED` connector run, both observation-set hashes, its validation report hash, and any bound source-count-override hash even though these operational records are not copied into Neo4j.

### 9.4 Core relations

```text
(JobPosting)-[:HAS_REVISION]->(JobPostingRevision:EntityRevision)
(JobPostingRevision)-[:POSTED_BY]->(Organization)
(JobPostingRevision)-[:FOR_OCCUPATION]->(Occupation)
(EntityRevision)-[:DERIVED_FROM]->(SourceSnapshot)
(EntityObservationState)-[:FOR_ENTITY]->(JobPosting|CourseInstance)
(EntityObservationState)-[:SELECTS_REVISION]->(JobPostingRevision|CourseInstanceRevision)
(JobPostingRevision)-[:HAS_REQUIREMENT]->(RequirementClaim)
(RequirementClaim)-[:TARGETS]->(Skill|Credential|NCSCompetencyUnit)
(RequirementClaim)-[:EVIDENCED_BY]->(EvidenceSpan)
(EvidenceSpan)-[:IN_SNAPSHOT]->(SourceSnapshot)

(Course)-[:HAS_INSTANCE]->(CourseInstance)
(Course)-[:HAS_REVISION]->(CourseRevision:EntityRevision)
(CourseInstance)-[:HAS_REVISION]->(CourseInstanceRevision:EntityRevision)
(Organization)-[:HAS_REVISION]->(OrganizationRevision:EntityRevision)
(Credential)-[:HAS_REVISION]->(CredentialRevision:EntityRevision)
(Place)-[:HAS_REVISION]->(PlaceRevision:EntityRevision)
(Source)-[:HAS_REVISION]->(SourceRevision:EntityRevision)
(ConceptScheme)-[:HAS_REVISION]->(TaxonomyRevision:EntityRevision)
(Occupation)-[:HAS_REVISION]->(TaxonomyRevision:EntityRevision)
(Skill)-[:HAS_REVISION]->(TaxonomyRevision:EntityRevision)
(MajorConcept)-[:HAS_REVISION]->(TaxonomyRevision:EntityRevision)
(NCSClass)-[:HAS_REVISION]->(TaxonomyRevision:EntityRevision)
(NCSCompetencyUnit)-[:HAS_REVISION]->(TaxonomyRevision:EntityRevision)
(CourseInstanceRevision)-[:OFFERED_BY]->(Organization)
(CourseInstanceRevision)-[:HAS_APPLICATION_WINDOW]->(ApplicationWindow)
(LearningOutcomeClaim)-[:ABOUT]->(Course|CourseInstanceRevision|Credential|ActionTemplate)
(LearningOutcomeClaim)-[:TARGETS]->(Skill|NCSCompetencyUnit)
(LearningOutcomeClaim)-[:EVIDENCED_BY]->(EvidenceSpan)

(Credential)-[:HAS_EXAM_SESSION]->(ExamSession)
(ExamSession)-[:HAS_REVISION]->(ExamSessionRevision:EntityRevision)
(ApplicationWindow)-[:HAS_REVISION]->(ApplicationWindowRevision:EntityRevision)
(ActionTemplate)-[:HAS_REVISION]->(ActionTemplateRevision:EntityRevision)
(Credential)-[:ATTESTS]->(Skill|NCSCompetencyUnit)
(NCSClass)-[:BROADER_THAN]->(NCSClass)
(NCSClass)-[:HAS_UNIT]->(NCSCompetencyUnit)
(Occupation)-[:CLASSIFIED_AS]->(NCSClass)
(SkillMappingClaim)-[:MAPS_SOURCE]->(Skill)
(SkillMappingClaim)-[:MAPS_TARGET]->(Skill|NCSCompetencyUnit)

(Person)-[:TARGETS_OCCUPATION]->(Occupation)
(Person)-[:HAS_CAPABILITY]->(Skill|Credential)
(PostingCohort)-[:HAS_MEMBER]->(JobPostingRevision)
(AggregateObservation)-[:SUPPORTED_BY]->(Assertion)
(CorpusRelease)-[:INCLUDES]->(SourceSnapshot|EntityRevision|EntityObservationState|Assertion|PostingCohort|AggregateObservation)
```

Every canonical corpus entity has exactly one applicable content revision in an included release; an unchanged revision can be a member of many releases. Every posting and course instance also has exactly one release-specific `EntityObservationState`, and that state selects the applicable content revision. `evaluated_at` is the release creation instant and `observation_state_id` is `sha256(JCS({release_id, entity_id, selected_revision_id, connector_run_id, first_seen_at, last_seen_at, consecutive_absence_count, serving_state, evaluated_at, methodology_version}))`. A posting revision has exactly one posting organization and primary occupation. Secondary occupation mappings are reviewed mapping claims. Each requirement claim belongs to exactly one posting content revision and has one or more evidence spans; later observations reuse that revision and claim rather than re-parenting either. Every course has exactly one provider per revision and one or more dated instances. The PostgreSQL manifest and graph membership relations, not duplicate ID arrays on release/cohort nodes, are authoritative. A Person has zero or one active target occupation and zero or more current resolved capabilities.

Claims are reified as nodes whenever a statement needs evidence, confidence, qualifiers, multiple sources, or time. Query-optimized shortcut edges, including `ATTESTS` and `CLASSIFIED_AS`, are release-scoped generated projections and always retain `release_id` plus their source assertion IDs; those edges are never the evidentiary authority.

### 9.5 Requirement claim fields

Each `RequirementClaim` contains:

- `claim_id`
- `requirement_kind`: `SKILL | CREDENTIAL | EDUCATION | EXPERIENCE | LANGUAGE | PROJECT | LOCATION | ELIGIBILITY | AVAILABILITY`
- `requirement_scope`: `CAPABILITY | POSTING_FILTER`
- `necessity`: `REQUIRED | PREFERRED | OPTIONAL`
- exactly one of normalized target ID or normalized typed condition
- `requirement_key`
- minimum proficiency and proficiency scheme when present
- minimum experience months when present
- exact Korean source span
- negation state, including `경력무관`
- assertion kind and confidence
- reviewer and review state
- valid time and system time
- evidence IDs; corpus-release membership is stored separately

`SKILL`, `CREDENTIAL`, and `LANGUAGE` claims use `TARGETS`; `LANGUAGE` targets a `Skill` whose kind is `LANGUAGE`. Other kinds use one typed condition and no target edge:

| Kind | Typed condition |
|---|---|
| `EDUCATION` | minimum degree, sorted accepted `MajorConcept.field_group` codes, and expected-graduate acceptance |
| `EXPERIENCE` | occupation/skill context plus minimum and maximum months |
| `PROJECT` | minimum project count, portfolio-required flag, and required capability IDs |
| `LOCATION` | accepted administrative codes and work mode |
| `ELIGIBILITY` | reviewed eligibility code plus exact source text |
| `AVAILABILITY` | earliest start and required schedule text |

`LOCATION`, `ELIGIBILITY`, and `AVAILABILITY` are always `POSTING_FILTER` and never affect occupation coverage. Education, experience, project, skill, credential, and language requirements are `CAPABILITY` and can affect application readiness.

`requirement_key` is `sha256(JCS(payload))`, where JCS is RFC 8785 canonical JSON and `payload` is:

- skill, language, or NCS: kind, canonical target ID, nullable proficiency-scheme ID, and nullable minimum ordered value
- credential: kind and canonical credential ID
- education: kind, minimum degree, sorted accepted `MajorConcept.field_group` codes, and `accepts_expected_graduate`
- experience: kind, canonical occupation/skill context ID, minimum months, and nullable maximum months
- project: kind, minimum count, portfolio-required flag, and sorted capability IDs
- posting filter: kind and its fully normalized typed condition

This `RoleRequirementKey` is the unit used for cross-posting aggregation, requirement results, current coverage, and route terminal constraints. Display text and all source-specific qualifiers remain on the individual claims.

### 9.6 NCS and taxonomy rules

The full NCS identifier is preserved, including development year and version. Example:

```text
canonical_id = ncs:0101010101_17v2
base_code    = 0101010101
version      = 17v2
```

An NCS competency unit is never collapsed into a generic market skill. NCS and the Jobtology Korean CS/AI skill vocabulary are separate concept schemes. Mappings use the SKOS semantics `exact`, `close`, `broad`, `narrow`, and `related`, with evidence and confidence. All mappings are many-to-many and versioned.

### 9.7 Identity rules

- Neo4j internal IDs are never exposed or persisted externally.
- Every canonical entity uses a stable `jt_id` URI.
- Source identity is always retained as `(source_id, source_record_id)`.
- NCS identity uses the full versioned code.
- Q-Net examination identity uses qualification type, item code, year, and round.
- JOB-ALIO uses the recruitment API's `recrutPblntSn`.
- Saramin uses its posting ID.
- Work24 training uses training ID plus training round.
- ALIO institutions use the institution API's official `instCd`.
- Organizations merge only with strong identifiers such as an official organization code, registration identifier, verified domain, or manually reviewed match.
- Korean display-name equality alone never merges organizations or people.
- Cross-source posting deduplication creates a reversible duplicate cluster; it never destroys source postings.

## 10. Grounding and temporal model

### 10.1 Evidence contract

Every assertion stores or references:

```text
source_system
source_dataset_id
source_record_id
source_url
publisher
snapshot_id
fetch_observation_id
content_sha256
raw_object_path
parsed_artifact_sha256
normalized_text_sha256
retrieved_at
source_published_at
source_modified_at
last_seen_at
valid_from
valid_to
locator_kind
locator_value
evidence_excerpt_ko
evidence_excerpt_sha256
license_code
license_url
license_observed_at
parser_version
extractor_method
extractor_version
confidence
review_status
```

Valid locator kinds and payloads are:

- `JSON_POINTER`: RFC 6901 pointer to one scalar plus its canonical-value hash.
- `XPATH`: XPath plus ordinal and selected-text hash.
- `TEXT_SPAN`: zero-based, half-open Unicode code-point start/end offsets against `normalized_text_sha256`.
- `PDF_REGION`: one-based page, PDF-point bounding box, and corresponding normalized-text offsets.

Assertion kinds are:

- `SOURCE_EXPLICIT`
- `NORMALIZED`
- `MODEL_INFERRED`
- `PREDICTED`

`PREDICTED` is vocabulary-reserved but blocked from MVP publication because forecasting is deferred. The UI and LLM must not present inferred or predicted statements as publisher-supplied facts.

Review status is exactly `PENDING | AUTO_ACCEPTED | HUMAN_ACCEPTED | REJECTED`. `AUTO_ACCEPTED` and `HUMAN_ACCEPTED` are the only publishable states; every assertion also records nullable reviewer ID and review timestamp, required for a human decision.

### 10.2 Derived trace contract

`CalculationTrace` stores `trace_id`, algorithm and methodology version, canonical input IDs and input hash, output values, supporting assertion/aggregate IDs, release ID, the release's `data_as_of`, and calculation timestamp. It grounds coverage, fit, difficulty, counts, ratios, D-days, costs, and progress.

`DecisionTrace` stores methodology version, solver version and seed, `solver_started_at`, normalized constraints, candidate action IDs, objective components, selected action IDs, rejected-action reason codes, feasibility blockers, tie-break stages, release ID, the release's `data_as_of`, and calculation timestamp. It grounds roadmap ordering and recommendation rationales. `UserStateEvent` grounds profile, capability, and step-state changes. These traces do not pretend that a derived result was quoted from a source.

Corpus-only count, ratio, and difficulty traces live in `jobtology_pipeline.publication` and are exposed through its two published security-barrier views. User-specific coverage, fit, D-day, and progress calculation traces, route decision traces, and user-state events live in `jobtology_app`. They are addressed through the same authenticated typed trace API but are not Neo4j entities.

### 10.3 Extraction cascade

Korean requirement extraction will run in this fixed order:

1. Consume structured source fields without a model.
2. Apply deterministic section and phrase rules for 필수, 자격요건, 우대, 경력무관, minimum experience, education, credential, language, and portfolio requirements.
3. Run `gpt-5.6-luna` constrained extraction only for unresolved free text. The model must return the repository JSON Schema and exact character offsets into the immutable normalized text.
4. Validate spans, target types, negation, and allowed predicates.
5. Publish at confidence `>= 0.90` when the evidence span validates.
6. Send confidence `0.70` through `0.89` to human review.
7. Reject confidence below `0.70`.

`confidence` is assigned by the pipeline, never copied from a model self-rating. Direct validated source fields receive `1.0`; deterministic-rule and model candidates use a versioned isotonic calibrator fitted on the training split and selected on the validation split from Section 20.2, using extractor kind, span validation, resolver margin, and schema checks as features. The held-out test split is used only for the published quality result. Changing rules, model, prompt, or resolver invalidates the calibrator and blocks auto-acceptance until recalibration.

The requested and returned model IDs, provider response ID, prompt hash, schema version, and token usage are recorded on every model-produced assertion.

### 10.4 Bitemporal behavior

Source-valid time and system-observation time are separate.

- `date_posted`, `valid_through`, course dates, and exam dates describe the source world.
- `retrieved_at`, `first_seen_at`, `last_seen_at`, `accepted_at`, and `retracted_at` describe system knowledge. First/last-seen and absence counters live on `EntityObservationState`, never on a content revision.

A missing page is not proof that a posting closed. A posting's release-selected `EntityObservationState.serving_state` is one of:

- `ACTIVE`
- `EXPIRED`
- `CLOSED`
- `NOT_SEEN`

Only an explicit source state on the selected content revision or elapsed `valid_through` date produces `CLOSED` or `EXPIRED`. Absence from two consecutive `SUCCEEDED SCHEDULED_FULL` connector runs produces `NOT_SEEN`. A transient request or detail failure leaves the last published observation state and content revision unchanged and sets the pipeline-only source-health overlay to `ERROR`; it cannot create a corpus record from an incomplete run. Historical snapshots, content revisions, observation states, and assertions are appended, never overwritten, except for the auditable rights-driven purge defined in Section 5.3.

Course-instance observation states use `UPCOMING | OPEN | FULL | CLOSED | EXPIRED | NOT_SEEN`. Explicit provider state on the selected content revision wins; passing the enrollment deadline produces `EXPIRED`; absence from two consecutive `SUCCEEDED SCHEDULED_FULL` connector runs produces `NOT_SEEN`; a transient failure affects only the source-health overlay. `FULL`, `CLOSED`, `EXPIRED`, and `NOT_SEEN` instances are not selectable. A last-known open record is selectable only while its source's latest successful full-run watermark is fresh: 12 hours for Saramin postings, 30 hours for JOB-ALIO postings, 36 hours for Work24 course instances, and 48 hours for Q-Net sessions. Failed refreshes never extend freshness.

The pipeline-only `SourceHealth` overlay is `HEALTHY` when the latest full run succeeded and its watermark is inside the applicable window, `REVIEW_REQUIRED` while that run awaits the count decision, `ERROR` when the latest full run failed, and `STALE` when the last success exceeded its window; the first matching condition in that order is used. It is returned as operational/freshness metadata and never replaces an entity's last published source state.

A new analysis additionally requires the selected successful full-run watermarks of both NCS APIs to be at most 8 days old and those of the NCS career-path update check and ALIO institution API to be at most 35 days old. It requires both posting sources within their serving windows above; route construction also requires each selected Work24/Q-Net offering within its stated window. Breaching a required window produces `SOURCE_STALE` rather than silently using older data. The current `INTERNAL_EDITORIAL` Git revision has no clock-based expiry but must be included in the active corpus release.

## 11. Cohorts, aggregates, and scoring

### 11.1 Posting cohort

All frontend statistics come from a persisted `PostingCohort`. Its filter is fixed to:

- exactly one of the four canonical occupations
- source set exactly `{JOB_ALIO, SARAMIN}`
- country `KR`
- `date_posted` in the inclusive interval from `as_of - 179 calendar days` through `as_of`, evaluated in KST, yielding exactly 180 local calendar dates
- an explicit `신입`, `인턴`, or `경력무관` source label; a `신입·경력` posting only when its new-graduate track is separately extractable or its parsed maximum experience is at most 24 months; or another posting with parsed maximum experience of at most 24 months
- Korean content, defined as a source Korean locale or at least 100 Hangul syllables and at least 30% Hangul among letter characters in title plus description
- one deterministic representative per accepted duplicate cluster

An unknown experience policy is excluded unless the source explicitly labels the posting new-graduate or internship. For a mixed posting, only claims scoped to the qualifying new-graduate track enter the cohort. Duplicate representative selection uses newest `effective_modified_at`, defined as the first non-null value of source-modified time, source-published time, and retrieval time; ties use source priority `JOB_ALIO` before `SARAMIN`, then lexical posting ID. The manifest persists every included/excluded posting ID, reason, duplicate cluster, representative, filter JSON, window, `as_of`, and release ID.

The occupation picker returns a separate count of currently `ACTIVE` and fresh cohort postings. Analysis uses all historical cohort members in the 180-day window. Neither count is a literal baked into the frontend.

Cohort-derived proportions are not published when their applicable denominator is below 30 unique postings. The API returns `INSUFFICIENT_DATA`, the observed denominator, and required minimum `30`; the UI shows `근거 데이터 부족`. A zero denominator produces `null`, never zero. Factual posting counts publish at any size, and difficulty follows its separate three-option minimum.

### 11.2 Demand statistics

For each `CAPABILITY`-scoped `RoleRequirementKey`:

```text
mention_ratio = unique cohort postings with an accepted claim / cohort posting count
required_ratio = unique cohort postings with necessity REQUIRED / cohort posting count
preferred_ratio = unique cohort postings with necessity PREFERRED / cohort posting count
role_relevance_ratio = unique cohort postings with REQUIRED or PREFERRED / cohort posting count
```

Negated claims do not count. Before aggregation, accepted claims for one `(posting representative, requirement_key)` collapse to the strongest necessity using `REQUIRED > PREFERRED > OPTIONAL`; all underlying claims remain as evidence. Source `OPTIONAL` claims count in `mention_ratio` for transparent demand reporting but not in role classification or coverage. Each aggregate carries numerator, denominator, unknown count, cohort ID, release ID, calculation timestamp, methodology version, and a support count/hash. Supporting assertion IDs live in the normalized PostgreSQL support table and `SUPPORTED_BY` graph relations rather than a large node property. The frontend formats ratios; it does not recalculate them.

Role-level requirement classification is fixed:

- `REQUIRED` when `required_ratio >= 0.50`.
- `PREFERRED` when `required_ratio < 0.50` and `role_relevance_ratio >= 0.20`.
- Not displayed in the default gap list when `role_relevance_ratio < 0.20`.

The frontend's `경력자 비율` for a capability is:

```text
experienced_hire_ratio = postings mentioning the capability and explicitly requiring 1-24 months
                         / postings mentioning the capability with a determinable experience policy
```

`경력무관`, `신입`, and `신입·경력` are determinable and do not enter the numerator. Unknown policies are excluded from the denominator and returned as `unknown_count`. The ratio is `null` when its denominator is below 30.

### 11.3 Coverage

Only `CAPABILITY` requirements enter coverage. Each result exposes `currently_satisfied` and `satisfiable_by_target`; current coverage uses only `currently_satisfied`, while the solver uses `satisfiable_by_target` at its scheduled completion time. A requirement is currently satisfied under these fixed rules:

- A current `ACTIVE` user capability with the same canonical target satisfies it, except that a credential whose `valid_until` precedes the KST evaluation date is not current and cannot satisfy a direct credential requirement.
- A mapping satisfies it only when its type is `exact`, its confidence is at least `0.95`, and it is `HUMAN_ACCEPTED`. `close`, `broad`, `narrow`, and `related` mappings can suggest an alternative but never add coverage.
- A held credential satisfies a skill or NCS unit only when it is unexpired on the KST evaluation date and linked through an accepted official `ATTESTS` assertion.
- When a minimum proficiency exists, both values must use the same ordered scheme and the user's value must meet or exceed it; a missing or incomparable value does not satisfy it.
- Education requires the minimum degree ordinal and, when specified, the `field_group` of the user's resolved `MajorConcept` to appear in the condition's accepted set; only direct or human-accepted exact major resolution is usable. Only `GRADUATED` is currently satisfied. A current student is `satisfiable_by_target` only when the source explicitly accepts expected graduates and `expected_graduation_on <= target_by`; that future milestone never enters current coverage.
- Experience requires a completed user experience record in the stated occupation/skill context whose verified or self-reported months meet the minimum.
- A project requirement requires the stated count of completed user projects, portfolio flag, and all required reviewed capability tags.
- `SELF_REPORTED` and `VERIFIED` both count, but the response always exposes which basis was used. Unresolved free text never counts.

Only a producing roadmap step whose state is `IN_PROGRESS` changes the requirement state to `IN_PROGRESS`; an accepted expected-graduation milestone within the target horizon does the same for education. A currently satisfied requirement is `COMPLETED`; all others are `TODO`. The user's explicit step transition to `COMPLETED` is the self-report confirmation and creates one active `SELF_REPORTED` user capability/project record for each declared outcome in the same application transaction; a step with no declared requirement outcome creates only its completion event. Accepted documentary evidence can later upgrade an outcome to `VERIFIED`.

Required and preferred coverage are calculated separately using role-class weights:

```text
required_coverage = sum(required_ratio for satisfied REQUIRED requirements)
                    / sum(required_ratio for all REQUIRED requirements)

preferred_coverage = sum(role_relevance_ratio for satisfied PREFERRED requirements)
                     / sum(role_relevance_ratio for all PREFERRED requirements)
```

The API also returns unweighted `matched_count` and `total_count`. An empty preferred class is valid, displays score `null` and counts `0/0`, and contributes `1.0` to fit and route utility because there is nothing preferred to satisfy. An empty required class makes the occupation analysis `INSUFFICIENT_DATA`. This prevents the PoC error of displaying a percentage that appears inconsistent with the shown count without explaining the weighting.

Occupation discovery uses:

```text
fit_score = 0.70 * required_coverage
          + 0.20 * preferred_coverage
          + 0.10 * preference_alignment
```

A null required coverage makes that occupation data-insufficient and its fit null. A null preferred coverage contributes `1.0` to the fit formula while remaining null in the response. If no employer type is selected, `preference_alignment=1.0`. Otherwise it is the fraction of active cohort postings with a known `Organization.employer_type` in the selected set; if fewer than 30 postings have a known type, it is neutral `0.5`. Discovery returns all four roles, ordered by data-sufficient first, descending fit, then occupation code.

### 11.4 Difficulty and alternatives

Difficulty is derived from the median estimated acquisition hours of accepted achievement options. The aggregation contains one record per stable `Course`, `Credential`, or `ActionTemplate`; multiple dated course instances and template revisions do not duplicate their identity shell. Unknown-hour options are excluded, every included estimate requires evidence or a reviewed internal template, and fewer than three eligible options produces `UNKNOWN`.

- `LOW`: at most 40 hours.
- `MEDIUM`: more than 40 and at most 160 hours.
- `HIGH`: more than 160 hours.
- `UNKNOWN`: fewer than three grounded estimates.

Skill substitution, such as TensorFlow for PyTorch, is displayed only from a reviewed `SkillMappingClaim` containing context, mapping type, confidence, and evidence. Co-occurrence alone never establishes substitution.

## 12. Route-planning contract

### 12.1 Solver responsibility

The backend will implement candidate selection and scheduling with OR-Tools CP-SAT. The solver's terminal outcome is `APPLICATION_READY_BY target_by`; it never predicts or guarantees employment. The LLM only explains the solver result.

Candidate action kinds:

- `SKILL_PRACTICE`
- `COURSE`
- `CERTIFICATION`
- `PROJECT`
- `APPLICATION_PREP`

`SKILL_PRACTICE`, `PROJECT`, and `APPLICATION_PREP` come from reviewed, versioned internal templates ingested as internal source snapshots. `COURSE` and `CERTIFICATION` require valid external instances. Current postings are returned in a separately ranked suggestion list and do not earn solver utility. Explicitly ineligible postings are excluded; the rest sort by known eligibility before unknown, selected employer-type match before non-match, descending individual-posting required coverage, descending preferred coverage, earliest closing time with null last, newest posting time, then lexical posting ID. Each individual-posting coverage value is the unweighted fraction of its unique accepted non-negated `CAPABILITY` requirement keys currently satisfied after necessity collapse; an empty required or preferred class contributes `1.0` for this ranking only. Only a user-pinned active posting adds a `JOB_APPLICATION` step to the next explicitly created roadmap draft; if it closes, the backend emits a stale warning and includes a replacement suggestion in the next analysis without mutating the active roadmap. It is never a forecast.

Each action includes a stable action ID, prerequisites, typed outcomes, the `RoleRequirementKey` values those outcomes can satisfy, estimated hours, weekly workload, nullable cost bounds, `cost_status = KNOWN_FREE | KNOWN_RANGE | UNKNOWN`, application dates, execution dates, location/mode, source freshness, and supporting assertion IDs. Skill/course/credential outcomes identify canonical targets and proficiency; a project outcome identifies project count, portfolio visibility, and reviewed capability tags. Duration must be known for selection. Route cost is the sum of conservative maxima; `KNOWN_FREE` contributes zero.

The mandatory terminal set contains every unsatisfied role-level `REQUIRED` RoleRequirementKey, one `APPLICATION_PREP` action, and the reviewed foundation requirements for the occupation when `career_switch=true`. A confirmed expected-graduation date is a fixed exogenous milestone, not a roadmap step, and can satisfy education only under Section 11.3. When `needs_portfolio=true`, the set also contains one reviewed project action unless a completed accepted project already satisfies the portfolio condition. A zero-action route is never successful.

### 12.2 Objective and scheduling

Route generation requires `analysis_status=READY` and at least one role-level required RoleRequirementKey; otherwise the API returns `422 INSUFFICIENT_DATA` and creates neither a route proposal nor a roadmap. All objective components are in `[0,1]`. A missing preferred class contributes `1.0` to the solver utility while remaining `null` in display coverage because there is nothing preferred to satisfy.

```text
coverage_utility = 0.80 * final_required_coverage + 0.20 * final_preferred_coverage
time_utility = max(0, 1 - critical_path_days / horizon_days)
cost_utility = max(0, 1 - conservative_cost_krw / 5_000_000)
objective = mode_coverage_weight * coverage_utility
          + mode_time_weight * time_utility
          + mode_cost_weight * cost_utility
```

An unknown-cost action has cost utility zero. When `max_out_of_pocket_krw` exists, an unknown-cost action is forbidden and known conservative total cost must not exceed the cap. Terms are scaled to integers from 0 through 10,000 for CP-SAT. Ties resolve by earliest finish, lower conservative known cost, fewer steps, then the lexical sequence of stable action IDs.

The solver runs with one worker, random seed `20260904`, and a 20-second limit. `OPTIMAL` and `FEASIBLE_NOT_PROVEN` results can be returned, with the latter carrying a visible optimization warning; CP-SAT `UNKNOWN` returns `503 SOLVER_TIMEOUT` and creates neither a route proposal nor a roadmap. Candidate ordering is lexical by stable action ID before solving.

`target_by` remains the fixed instant derived when the goal was interpreted. Each solver request records `solver_started_at`; `planning_start` is the next KST midnight after that request timestamp, not after the older goal interpretation. `horizon_days` is the inclusive count of KST calendar dates from `planning_start` through the target date. If that count is below one, including a target that has passed, the API returns `422 TARGET_TOO_SOON` with the two timestamps and an application `CalculationTrace`, but creates no `Roadmap` or `DecisionTrace`; no utility division is evaluated.

Scheduling uses that daily KST grid. Prerequisites finish before dependent actions start; fixed courses, enrollment windows, and exams retain their published calendars; and the sum of overlapping action workloads in each ISO week does not exceed `available_hours_per_week`. Known synchronous session intervals cannot overlap. Different offline locations require a 90-minute travel buffer; a fixed session with unknown clock times cannot share a local date with another fixed session. Self-directed templates can start at `planning_start`. An absent valid external offering invalidates only the offering-backed action, not self-directed practice or projects.

Preference effects are exact: `part_time_compatible` sets the 10-hour capacity only when the user has not confirmed an explicit weekly-hours override; `fastest_path` uses the weight transfer in Section 3.2; `needs_portfolio` and `career_switch` add the mandatory items above. Employer flags are a soft ordering for current-posting suggestions, with neither unrestricted and both accepting their union; they never exclude a route action.

### 12.3 Feasibility

`buffer_slot_count = floor(0.8 * horizon_days)`. When it is positive, the buffer cutoff is 23:59:59 KST on the final buffered slot; when it is zero, no plan can be `FEASIBLE` but it can still be `RISKY` if it finishes by `target_by`. A plan is:

- `FEASIBLE` when the full mandatory terminal set and all prerequisites finish by the buffer cutoff and every selected cost is known.
- `RISKY` when the full mandatory terminal set finishes after the buffer cutoff but by `target_by`, or at least one selected action has unknown cost and no monetary cap exists.
- `INFEASIBLE` when the full mandatory terminal set cannot finish by `target_by`, a mandatory prerequisite cannot be satisfied, or every way to produce a mandatory capability lacks a valid candidate.

For `INFEASIBLE`, the solver returns a diagnostic route proposal containing the maximum-coverage partial schedule plus explicit unmet requirements and blocking reasons, not a misleading golden route. An infeasible proposal cannot be materialized as a saved roadmap. The planner never recommends an expired, stale, closed, or unverified offering as currently available.

Planning is two-pass: first solve with the full mandatory set as hard constraints. Only when that model is proven infeasible, solve once more with every terminal-selection constraint—including required keys, foundations, portfolio, and application preparation—made optional while prerequisites remain conditional on selected actions. The diagnostic pass first lexicographically maximizes satisfied required weight, then application-preparation completion, then applies the normal objective. Its empty selection is valid, so it always has a feasible diagnostic result unless CP-SAT times out. The returned artifact is always labeled `INFEASIBLE`, carries the diagnostic pass's `OPTIMAL | FEASIBLE_NOT_PROVEN` status, and lists every unsatisfied terminal and blocker; an empty diagnostic plan is never presented as a route.

### 12.4 Plan lifecycle

```text
Chat/Profile inputs -> analysis/unsaved preview -> explicit create action -> DRAFT
DRAFT -> explicit activation -> ACTIVE
ACTIVE + changed constraints/profile -> new analysis/unsaved preview -> explicit create action -> DRAFT
old ACTIVE -> SUPERSEDED
pinned corpus release REVOKED -> INVALIDATED
```

An analysis and a chat `ROUTE_PROPOSAL` use the immutable contract in Section 15.7 and are derived previews, not saved plans: they have no `roadmap_id`, plan state, mutable step state, or progress history. The explicit `이 경로로 내 로드맵 만들기` action materializes a feasible or risky preview as a saved `DRAFT`; only the explicit `ACTIVATE` action can replace the active roadmap. The explicit job-posting pin action may likewise create a replacement draft containing `JOB_APPLICATION`; no background path creates one.

Every step is actionable, so progress is `completed_steps / steps.length`; a draft with no steps reports zero. `step_key` is `sha256(JCS({action_kind, target_entity_id, exact_source_or_template_revision_id, typed_outcomes, completion_criteria_hash, sorted_prerequisite_step_keys}))`. Completion survives recomputation only when that entire semantic key is unchanged; a stable source/template identity with a changed revision, outcome, criterion, or prerequisite cannot inherit completion. A changed route produces a diff explaining added, removed, retained, and reordered steps.

Roadmap step state uses only `TODO`, `IN_PROGRESS`, and `COMPLETED`. Only an `ACTIVE` roadmap accepts step-state mutations. Every transition among those three states is allowed and creates an append-only user-state event; leaving `COMPLETED` revokes the capability/project outcomes associated with its effective completion event in the same transaction, including an inherited event, and completing it again creates new outcome versions. Saved-plan state uses `DRAFT`, `ACTIVE`, `SUPERSEDED`, `ARCHIVED`, and `INVALIDATED`. A release-revocation event invalidates every draft or active roadmap pinned to it, disables its actions and source-backed details, and enqueues recomputation against the current release before publication resumes. Mutations require the caller's expected roadmap version and return `409 VERSION_CONFLICT` on a stale write.

The backend validity monitor runs every 15 minutes, after each publication, and on every roadmap read. It checks stable offering/posting IDs against the active release and evaluates wall-clock deadlines plus source-freshness limits even when no new release was published. When a pinned action becomes closed, expired, absent, or stale, it stores a separate `current_validity` result with check time, reason codes, and the active release ID, then idempotently creates a new active-release analysis when fresh data permits; it never creates a saved roadmap or rewrites the historical route calculation. The frontend presents its unsaved replacement preview and requires the explicit create action. This is the only dual-release display, and both the pinned and checked release IDs are explicit.

Every committed profile, goal, route-preference, capability, or eligibility-fact mutation creates one idempotent `RecomputeRequest` in the same `jobtology_app` transaction. An outbox worker advances it through `PENDING -> RUNNING -> READY | FAILED` and produces a new analysis plus an unsaved route preview when targeted analysis is ready. It never creates or activates a saved roadmap. A non-revoked previous roadmap remains `ACTIVE` until the user explicitly creates and activates its replacement; a revoked one remains `INVALIDATED`. Mutation responses return `recompute_request_id`; the frontend polls its fixed status endpoint every two seconds until terminal state.

## 13. Learning, credential, and deadline data

### 13.1 Course model

`Course` is the stable catalog concept. `CourseInstance` is one dated cohort. They are never merged.

Required `CourseInstance` fields:

- provider ID and name
- course and instance IDs
- nullable enrollment opening timestamp and required closing timestamp
- start and end timestamps
- delivery mode and nullable location
- weekly schedule and total hours
- nullable listed tuition in KRW
- nullable subsidy amount and eligibility text
- nullable expected out-of-pocket minimum and maximum
- `cost_status = KNOWN_FREE | KNOWN_RANGE | UNKNOWN`
- nullable capacity and required availability status
- normalized enrollment-eligibility rules and separate subsidy-eligibility rules, with original text
- normalized prerequisite target IDs, with original text
- grounded learning-outcome claims
- credential awarded when present
- source URL, last-seen time, and evidence IDs

For the current user, enrollment eligibility evaluates to `ELIGIBLE | INELIGIBLE | UNKNOWN`; an ineligible or unknown instance cannot enter the solver. Computation never waits for interactive input. It excludes that instance and returns a typed `required_inputs[]` entry identifying the missing eligibility fact and affected candidates. A confirmed `UserEligibilityFact` is written through the versioned profile update and starts a new recomputation. Subsidy eligibility is evaluated separately. `UNKNOWN` subsidy eligibility uses the full listed unsubsidized tuition as conservative cost; if that tuition is also unknown, the action remains `cost_status=UNKNOWN` and follows the risky/hard-cap rules in Section 12.

### 13.2 Credential model

Credential recommendations require:

- an accepted link from credential to the missing capability or NCS competency unit
- a future Q-Net application/exam session that fits the target horizon
- application, exam, and result dates
- fee when known
- official source evidence

The recommendation wording will say that a credential addresses or attests specified capabilities. It will not claim that certification guarantees employment.

### 13.3 Internal action templates

Self-directed skill practice, projects, and application preparation use versioned YAML reviewed into the repository. Each version is ingested through an `INTERNAL_EDITORIAL` SourceSnapshot and contains Korean instructions, occupation and capability targets, prerequisites, observable completion criteria, conservative effort hours, zero or known material cost, reviewer, review timestamp, and citations to official learning or qualification material. Template changes never rewrite a saved route.

There is no generic `EXPERIENCE` action in the MVP because no grounded experience-opportunity source is included. Internships remain ordinary `JobPosting` records and can appear only as live `JOB_APPLICATION` actions.

### 13.4 Upcoming events

Frontend deadline records use full timestamps and `Asia/Seoul`:

- `CERT_EXAM_REGISTRATION`
- `CERT_EXAM`
- `JOB_APPLICATION`
- `COURSE_ENROLLMENT`
- `COURSE_START`

The backend returns signed `days_until`, the KST reference timestamp, and an application-side calculation-trace ID. `days_until` is the event's KST local date minus the reference timestamp's KST local date: future is positive, today is zero, and past is negative. The frontend only formats those typed values into month/day and D-day text. Bare dates such as `8월 8일` are never persisted.

## 14. LLM chat and grounding

### 14.1 Chat architecture

Chat turns stream over HTTP Server-Sent Events. WebSockets are not used.

The backend exposes typed tools:

- `resolve_occupation`
- `get_profile_gap`
- `get_requirement_evidence`
- `get_calculation_trace`
- `search_learning_options`
- `get_upcoming_deadlines`
- `compute_route`
- `get_plan_diff`
- `propose_profile_update`

The LLM has no database credentials, does not issue free-form Cypher, and cannot mutate a profile or roadmap without an explicit user-confirmation action.

Chat execution order:

1. Resolve entities and request clarification for ambiguous user terms.
2. Load the confirmed profile, active goal, and active roadmap.
3. Retrieve accepted graph claims, stored aggregates, and evidence spans.
4. Run the deterministic analysis or route solver.
5. Let the LLM render a Korean explanation from the structured result.
6. Run a support validator over named entities, numbers, dates, costs, availability, and recommendation statements. Source facts require claim/evidence IDs; derived values require calculation/decision trace IDs; progress calculations require a calculation trace backed by user-state event IDs.
7. Stream the answer, graph, unsaved route preview, citations, and uncertainties.

Unsupported factual content is removed. The fallback response states that the available evidence is insufficient.

### 14.2 Chat response

Each completed response contains:

- `answer_id`
- `session_id`
- structured content blocks
- claim references inline with factual statements
- citations
- `data_as_of`
- `corpus_release_id`
- analysis cohort and methodology version
- nullable `graph_id` plus recommendation graph nodes and edges
- optional unsaved `ROUTE_PROPOSAL`
- suggested typed actions
- uncertainties and freshness warnings

Content block kinds:

- `MARKDOWN`
- `STAT`
- `ROUTE_PROPOSAL`
- `EVIDENCE_LIST`
- `WARNING`
- `ACTION_CHIPS`

A `ROUTE_PROPOSAL` block contains the complete Section 15.7 contract, including `analysis_id`, `route_proposal_id`, and proposal hash. Its create action submits those exact IDs plus the current expected profile version; rendering the block alone performs no mutation.

SSE events:

- `message.delta`
- `grounding.updated`
- `graph.updated`
- `route.proposed`
- `message.completed`
- `error`

### 14.3 Recommendation graph

The backend returns semantic nodes and edges, not SVG coordinates, radius, or colors.

Node kinds:

- `PERSON`
- `OCCUPATION`
- `SKILL`
- `COURSE`
- `PROJECT`
- `CREDENTIAL`
- `EXPERIENCE`

Node states:

- `SELF`
- `TARGET`
- `HAVE`
- `NEED`
- `RECOMMENDED`

Every graph edge includes a predicate and `support_refs[]`, each typed as `CLAIM | AGGREGATE | CALCULATION_TRACE | DECISION_TRACE | USER_EVENT`. Clicking a node retrieves a type-specific detail object: corpus-demand nodes include numerator, denominator, cohort window, source list, and evidence; user/project/route nodes include their applicable user events or decision traces. The graph never requires cohort fields where they do not apply and never displays an unexplained statement such as `연결 61%`.

### 14.4 Chat safety and privacy

- Source text is untrusted input and is isolated from system/tool instructions.
- HTML scripts and active content are discarded during parsing.
- Before the first hosted-model chat, the user must accept a versioned LLM-transfer consent that names the provider/model and current provider-retention disclosure; consent and revocation timestamps are stored in `jobtology_app`.
- Outbound chat context contains an opaque session ID, the current message after deterministic masking of email, phone, student number, and known profile identifiers, only the confirmed capabilities/constraints needed for that turn, and selected licensed evidence excerpts. It excludes name, email, school identity, raw documents, and unrelated chat/profile fields, and every Responses API call sets `store: false`.
- Without that consent, chat and chat-based profile parsing are disabled, while deterministic profile editing, occupation analysis, route solving, progress, and evidence browsing continue to work.
- The system makes no employment guarantee.
- It performs no automatic enrollment, application, outreach, or contact action.
- Protected traits are not inferred and are not route-ranking inputs.
- Chat-extracted profile facts remain drafts until the user confirms them.
- Users can delete their profile, chat history, plans, and Person projection.

## 15. Fixed data contracts

### 15.1 Grounded claim

```text
GroundedClaim {
  claim_id
  subject_ref
  predicate
  object_ref | literal_value
  qualifiers
  assertion_kind
  confidence
  review_status = PENDING | AUTO_ACCEPTED | HUMAN_ACCEPTED | REJECTED
  reviewer_id
  reviewed_at
  evidence_refs[]
  extractor_version
  valid_from
  valid_to
  accepted_at
  retracted_at
}
```

Exactly one of `object_ref` and `literal_value` is present. Release membership is external to this stable claim.

### 15.2 User profile

```text
UserProfile {
  user_id
  display_name
  education {
    major_raw
    major_concept_id
    degree_level = BACHELOR
    year = 1 | 2 | 3 | 4
    enrollment_status = ENROLLED | LEAVE | GRADUATED
    expected_graduation_on
  }
  goals[]
  route_preferences
  capabilities[]
  eligibility_facts[]
  version
  updated_at
}
```

`major_concept_id` is nullable only when unresolved. `expected_graduation_on` is a local calendar date required for enrolled/on-leave users and null for graduates. Each `UserEligibilityFact` contains a stable `fact_code` from the versioned eligibility vocabulary, declared scalar type and value, effective-from/to dates, confirmation timestamp, and `USER_CONFIRMED | VERIFIED` provenance; superseded facts are retained only as audit events. It contains no raw identity document. `UserProfile.version` is the aggregate version for profile, education, goal, route-preference, capability, and eligibility-fact writes; every such mutation compares and atomically increments it. The profile response embeds goal and capability summaries, but their dedicated endpoints are the only mutation path.

### 15.3 Career goal

```text
CareerGoal {
  goal_id
  goal_mode = TARGETED | DISCOVERY
  outcome = APPLICATION_READY_BY
  occupation_id
  target_horizon = THIS_QUARTER | SIX_MONTHS | N_YEARS
  horizon_years
  original_time_phrase
  interpreted_at
  target_by
  timezone = Asia/Seoul
  status = ACTIVE | ARCHIVED
}
```

`occupation_id` is null only for `DISCOVERY` and required for `TARGETED`. Confirming a discovery result archives the discovery goal and creates the one active targeted goal. Company targeting is not present in the MVP contract.

### 15.4 Route preferences

```text
RoutePreferences {
  budget_mode = REGULAR | LOW_COST
  part_time_compatible
  fastest_path
  needs_portfolio
  career_switch
  employer_preferences[] = LARGE_ENTERPRISE | STARTUP
  available_hours_per_week
  availability_source = DERIVED_DEFAULT | USER_OVERRIDE
  max_out_of_pocket_krw
}
```

`max_out_of_pocket_krw` is nullable; all other fields are required. The backend persists the effective availability and its source alongside the preference flags. A profile update clears an override only through explicit `clear_availability_override=true`; setting both that flag and a new hour value is rejected.

### 15.5 User capability

```text
UserCapability {
  capability_id
  category = SKILL | TOOL | CREDENTIAL | LANGUAGE | PROJECT | EXPERIENCE | ACTIVITY
  raw_text
  entity_id
  proficiency_scheme_id
  proficiency_value
  verification = SELF_REPORTED | VERIFIED
  evidence_type = USER_ENTRY | DOCUMENT | SYSTEM_EVENT
  lifecycle = ACTIVE | REVOKED
  structured_details
  started_on
  completed_on
  resolution_confidence
}
```

`entity_id`, proficiency fields, structured details, and dates are nullable when inapplicable. Proficiency requires both a scheme ID and a value valid in that scheme's ordered levels. `structured_details` is schema-discriminated: credentials contain `issued_on`, nullable `valid_until`, issuer, and verification-source reference; projects contain reviewed capability tags and portfolio visibility; experiences contain occupation/skill context and month count. Revocation removes the graph projection without erasing the audit event.

### 15.6 Analysis response

```text
AnalysisResponse {
  analysis_id
  analysis_status = READY | INSUFFICIENT_DATA
  reason_code
  profile_version
  goal_id
  cohort
  observed_denominator
  required_minimum = 30
  generated_at
  data_as_of
  methodology_version
  coverage {
    required { score, matched_count, total_count }
    preferred { score, matched_count, total_count }
  }
  requirement_results[]
  unmet_requirement_keys[]
  required_inputs[]
  route_proposal
  calculation_trace_ids[]
  corpus_release_id
}
```

`reason_code` is null for `READY` and otherwise `SOURCE_STALE | COHORT_TOO_SMALL | NO_REQUIRED_REQUIREMENTS`, evaluated in that priority order. Coverage scores are nullable and remain null for `INSUFFICIENT_DATA` or an empty class. `route_proposal` is the full contract below for a completed targeted solve and null for `INSUFFICIENT_DATA`. Discovery uses its separate response and produces no route proposal. Target-too-soon and solver-timeout requests return their typed errors and create no proposal. Each requirement result includes `requirement_key`, kind, canonical target or normalized condition, Korean display label, `currently_satisfied`, `satisfiable_by_target`, `TODO | IN_PROGRESS | COMPLETED`, necessity, satisfaction basis and capability provenance, demand numerator/denominator/ratio, difficulty, experienced-hire numerator/denominator/unknown-count/ratio, achievement options, aggregate ID, trace IDs, and evidence references. `unmet_requirement_keys[]` references those results. The frontend derives a gap view by filtering out `COMPLETED`; it does not receive a separate inconsistent calculation.

Discovery uses a separate response:

```text
DiscoveryAnalysisResponse {
  analysis_id
  profile_version
  goal_id
  ranked_occupations[4] {
    rank
    occupation_id
    analysis_status
    required_coverage
    preferred_coverage
    preference_alignment
    fit_score
    active_posting_count
    trace_ids[]
  }
  generated_at
  data_as_of
  methodology_version
  corpus_release_id
}
```

### 15.7 Route proposal and roadmap

```text
RouteProposal {
  route_proposal_id
  proposal_hash
  analysis_id
  goal_id
  profile_version
  constraints_snapshot
  generated_at
  data_as_of
  methodology_version
  optimization_status = OPTIMAL | FEASIBLE_NOT_PROVEN
  feasibility = FEASIBLE | RISKY | INFEASIBLE
  estimate { duration_days, cost_status, cost_krw_min, cost_krw_max, hours_per_week }
  unmet_requirements[]
  required_inputs[]
  decision_trace_id
  proposed_steps[]
  corpus_release_id
}
```

The proposal is an immutable, authenticated, user-scoped record in `jobtology_app`, returned inline in `AnalysisResponse` and addressable by ID. `proposal_hash` is `sha256(JCS(RouteProposal without proposal_hash))`. Each proposed step contains the same semantic key, planning, prerequisite, revision, outcome, rationale, and evidence fields as a roadmap step but has no mutable state or saved-step ID. It also carries read-only `completion_basis = NONE | INHERITED` and nullable `inherited_from {roadmap_id, step_id, completion_event_id}`. The solver sets `INHERITED` only when the user's current or most recently invalidated roadmap has a `COMPLETED` step with the exact same semantic `step_key` and an unretracted completion event; it never inherits merely by position or display label. Materialization verifies the authenticated user, matching analysis and proposal hash, unchanged current profile version, pinned non-revoked release, current source validity, every inherited event still unretracted, and `feasibility ∈ {FEASIBLE, RISKY}`. It creates new step IDs, copies exact inherited matches as `COMPLETED` with a `StepCompletionInheritance` record pointing to the original audited event, initializes every other step as `TODO`, and does not create duplicate capability outcomes or alter the proposal.

```text
Roadmap {
  roadmap_id
  user_id
  goal_id
  profile_version
  title
  state = DRAFT | ACTIVE | SUPERSEDED | ARCHIVED | INVALIDATED
  version
  constraints_snapshot
  analysis_id
  generated_at
  data_as_of
  methodology_version
  optimization_status = OPTIMAL | FEASIBLE_NOT_PROVEN
  feasibility = FEASIBLE | RISKY
  current_validity { status = CURRENT | STALE | REVOKED, checked_at, checked_release_id,
                     reason_codes[], stale_step_ids[] }
  estimate { duration_days, cost_status, cost_krw_min, cost_krw_max, hours_per_week }
  progress { completed_steps, total_steps, ratio, calculation_trace_id }
  unmet_requirements[]
  required_inputs[]
  decision_trace_id
  steps[]
  corpus_release_id
}
```

Each `unmet_requirements[]` item is `{requirement_key, reason_code}` and the array is empty for `FEASIBLE` and `RISKY`. The progress calculation trace references the exact step-state event heads and completion-inheritance records used for its counts. Each step includes `step_id`, semantic `step_key`, `action_kind = SKILL_PRACTICE | COURSE | CERTIFICATION | PROJECT | APPLICATION_PREP | JOB_APPLICATION`, position, target entity, state, prerequisite step IDs, planned timestamps, due timestamp, estimated hours, cost status and nullable bounds, stable offering/template ID plus exact selected revision ID, typed outcomes and completion-criteria hash, rationale claim/trace IDs, evidence references, nullable completion event ID, and nullable completion-inheritance ID. Every roadmap mutation carries `expected_roadmap_version`.

### 15.8 Trace records

```text
CalculationTrace { trace_id, algorithm_version, methodology_version, input_refs[], input_hash,
                   outputs, support_refs[], calculated_at, data_as_of, corpus_release_id }
DecisionTrace    { trace_id, methodology_version, solver_version, solver_seed, solver_started_at,
                   constraints, candidate_ids[],
                   objective_components, selected_ids[], rejection_reasons,
                   blockers[], tie_breaks[], calculated_at, data_as_of, corpus_release_id }
```

### 15.9 Recompute request

```text
RecomputeRequest {
  recompute_request_id
  profile_version
  trigger_event_id
  state = PENDING | RUNNING | READY | FAILED
  resulting_analysis_id
  resulting_route_proposal_id
  error_code
  created_at
  completed_at
}
```

Result IDs and terminal fields are nullable until applicable. The idempotency key is `(user_id, profile_version, trigger_event_id)`.

### 15.10 Required-input and deletion contracts

The following backend-owned contracts are included here because the pipeline's normalized eligibility vocabulary and release/deletion events must interoperate with them.

Each `RequiredInput` is `{input_key, fact_code, value_type, prompt_ko, reason_code, affected_candidate_ids[]}`. It asks only for a normalized fact needed to evaluate a candidate; confirming it updates `eligibility_facts[]` and creates a new `RecomputeRequest`. `RecomputeRequest` itself never enters an interactive waiting state.

```text
DeletionRequest {
  deletion_request_id
  state = PENDING | COMPLETED
  opaque_user_id
  status_receipt_hash
  attempt_count
  last_error_code
  requested_at
  graph_deleted_at
  completed_at
  ledger_snapshot_id
}
```

`opaque_user_id` is removed at completion; error, graph, completion, and snapshot fields are nullable until applicable. Only a hash of the random status receipt is stored, and the request row is erased seven days after completion while the HMAC ledger entry follows the ledger-retention rule.

## 16. Backend API surface fixed for integration

The backend will expose:

```text
GET    /api/v1/occupations
GET    /api/v1/me/profile
PUT    /api/v1/me/profile
DELETE /api/v1/me
GET    /api/v1/deletions/{deletion_request_id}
PUT    /api/v1/me/llm-consent
DELETE /api/v1/me/llm-consent
GET    /api/v1/me/goals
POST   /api/v1/me/goals
PATCH  /api/v1/me/goals/{goal_id}
POST   /api/v1/me/capabilities
PATCH  /api/v1/me/capabilities/{capability_id}
DELETE /api/v1/me/capabilities/{capability_id}
POST   /api/v1/analyses
GET    /api/v1/analyses/{analysis_id}
GET    /api/v1/recomputations/{recompute_request_id}
GET    /api/v1/route-proposals/{route_proposal_id}
POST   /api/v1/roadmaps
GET    /api/v1/roadmaps
GET    /api/v1/roadmaps/{roadmap_id}
PATCH  /api/v1/roadmaps/{roadmap_id}
DELETE /api/v1/roadmaps/{roadmap_id}
PATCH  /api/v1/roadmaps/{roadmap_id}/steps/{step_id}
POST   /api/v1/roadmaps/{roadmap_id}/job-applications
GET    /api/v1/dashboard?goal_id={goal_id}
GET    /api/v1/upcoming-events?goal_id={goal_id}
POST   /api/v1/chat/sessions
GET    /api/v1/chat/sessions/{session_id}
POST   /api/v1/chat/sessions/{session_id}/turns
DELETE /api/v1/chat/sessions/{session_id}
GET    /api/v1/claims/{claim_id}/evidence?release_id={corpus_release_id}
GET    /api/v1/traces/{trace_id}
GET    /api/v1/aggregates/{aggregate_id}/postings
GET    /api/v1/recommendation-graphs/{graph_id}/nodes/{node_id}
```

Every corpus-backed response carries `data_as_of`, `corpus_release_id`, `methodology_version`, and applicable evidence/trace references. A claim/evidence reference is the pair `{claim_id, corpus_release_id}`; the evidence endpoint requires that release, verifies membership and non-revocation, and rejects a mismatch. Fixed integration DTOs are:

```text
OccupationSummary { occupation_id, name_ko, active_posting_count, count_as_of, data_as_of,
                    methodology_version, analysis_status, corpus_release_id,
                    calculation_trace_id }
DashboardResponse { profile_version, active_goal,
                    current_analysis_summary{ data_as_of, methodology_version, corpus_release_id, ... },
                    active_roadmap_summary{ data_as_of, methodology_version, corpus_release_id, ... },
                    recompute_state, upcoming_events[], posting_suggestions[], recent_user_events[],
                    generated_at, active_corpus_release_id, trace_ids[] }
UpcomingEvent      { event_id, kind, title, occurs_at, timezone, days_until,
                    source_entity_id, availability, evidence_refs[], calculation_trace_id,
                    data_as_of, methodology_version, corpus_release_id }
PostingSuggestion { posting_id, title, organization, employer_type, closes_at,
                    freshness, preference_match, evidence_refs[], data_as_of,
                    methodology_version, corpus_release_id }
RecommendationGraph { graph_id, nodes[], edges[{ edge_id, from, to, predicate, support_refs[] }],
                      data_as_of, methodology_version, corpus_release_id }
SseEnvelope        { event_id, answer_id, sequence, type, emitted_at, data }
```

`DashboardResponse` is the deliberate composite exception to a single top-level corpus envelope: user-state fields have no corpus version, while every nested corpus-backed summary, event, and suggestion carries its own complete metadata. `active_corpus_release_id` identifies the release for new work and does not relabel an older pinned roadmap.

`POST /roadmaps` is called only by the explicit create action, accepts `{analysis_id, route_proposal_id, expected_profile_version}`, and materializes that exact preview as one saved `DRAFT` using the analysis's pinned, non-revoked corpus release. It returns `VALIDATION_ERROR` for an `INFEASIBLE` proposal or an analysis/proposal mismatch, `VERSION_CONFLICT` when the profile version or an inherited completion basis changed, `CORPUS_RELEASE_REVOKED` when the pinned release was revoked, and `STALE_SOURCE` when the required source families are no longer fresh; each failure requires a new analysis rather than mixing state or releases. `PATCH /roadmaps/{id}` accepts action `ACTIVATE | ARCHIVE`. `ACTIVATE` requires both expected roadmap and profile versions and, in the same transaction that supersedes the previous active roadmap, rechecks that the draft's stored profile version still equals the current profile version and every inherited completion event remains unretracted; a failed recheck returns `VERSION_CONFLICT` and requires a new analysis/proposal. Activation also rejects an invalidated or stale roadmap. `PATCH .../steps/{step_id}` accepts the target step state; a transition entering or leaving `COMPLETED` carries both expected roadmap and profile versions because it atomically creates or revokes user outcomes. `POST .../job-applications` is an explicit user action, requires both expected versions, and is accepted only when the roadmap's pinned release equals the active release and the `posting_id` is active there; otherwise it returns `STALE_SOURCE`. In one transaction, success creates a replacement draft at the current profile version, carries forward each exact completed step through a `StepCompletionInheritance`, and adds the pinned `JOB_APPLICATION` step in `TODO`. All four mutation payloads carry the applicable expected version.

`POST /analyses` accepts a `goal_id` and returns `AnalysisResponse` for `TARGETED` or `DiscoveryAnalysisResponse` for `DISCOVERY`. `PUT /me/profile` excludes goals and capabilities, which have dedicated endpoints, but accepts typed eligibility-fact confirmations. Goal activation archives any previous active goal in one transaction. Ordinary roadmap removal is `PATCH action=ARCHIVE`; roadmap `DELETE` is reserved for privacy erasure. `DELETE /me` performs the local erasure transaction and returns only `202 Accepted` with `{deletion_request_id, state: PENDING, status_receipt}`. `GET /deletions/{id}` requires that receipt and returns `PENDING | COMPLETED` plus retry metadata; no response claims completion before the root finalizer's verified off-host acknowledgement.

Every mutating `POST` accepts an `Idempotency-Key`. Profile, goal, preference, capability, and eligibility-fact mutations accept `expected_profile_version`; roadmap and step mutations accept `expected_roadmap_version`. A successful mutation atomically increments the applicable aggregate version. List endpoints use opaque cursor pagination with a maximum page size of 100. Fixed error codes are `VALIDATION_ERROR`, `AMBIGUOUS_ENTITY`, `INSUFFICIENT_DATA`, `STALE_SOURCE`, `CORPUS_RELEASE_REVOKED`, `TARGET_TOO_SOON`, `SOLVER_TIMEOUT`, `VERSION_CONFLICT`, `NOT_FOUND`, and `FORBIDDEN`. Evidence-posting pages return source URL, posting ID, numerator-membership reason, evidence IDs, `as_of`, and release ID. An artifact pinned to a revoked release returns `410 CORPUS_RELEASE_REVOKED`; its user-authored shell remains available without prohibited corpus details.

`Jobtology-DB` will publish versioned JSON Schemas for the corpus, claim, evidence, cohort, aggregate, trace, and recommendation-graph payloads. The backend repository will own and implement OpenAPI schemas for user profiles, goals, chat sessions, analyses, and roadmaps.

## 17. Neo4j constraints and indexes

Migrations will create uniqueness constraints on:

- `CorpusRelease.release_id`
- `ConceptScheme.jt_id`
- `Occupation.jt_id`
- `Skill.jt_id`
- `MajorConcept.jt_id`
- `NCSClass.jt_id`
- `NCSCompetencyUnit.jt_id`
- `Credential.jt_id`
- `Organization.jt_id`
- `Place.jt_id`
- `JobPosting.jt_id`
- `Course.jt_id`
- `CourseInstance.jt_id`
- `ExamSession.jt_id`
- `ApplicationWindow.jt_id`
- `ActionTemplate.jt_id`
- `EntityRevision.revision_id`
- `EntityObservationState.observation_state_id`
- `Source.source_id`
- `SourceSnapshot.snapshot_id`
- `EvidenceSpan.evidence_id`
- `Assertion.claim_id`
- `PostingCohort.cohort_id`
- `AggregateObservation.aggregate_id`
- `Person.person_id`

Range indexes on `EntityRevision` subtypes will cover entity ID/type, posting/validity dates, course enrollment dates, and exam dates. `EntityObservationState` receives range indexes on entity ID/type, connector-run ID, serving state, and last-seen time. Release selection uses the indexed `CorpusRelease.release_id` constraint plus `INCLUDES` membership; source identity and the PostgreSQL active-release pointer receive their own indexes. A Korean full-text index will cover revision-scoped names, aliases, posting titles, and evidence text. Vector indexes are excluded from the MVP; canonical resolution, full-text retrieval, and graph traversal are sufficient for the first release.

## 18. Repository layout

```text
Jobtology-DB/
  pyproject.toml
  uv.lock
  README.md
  docs/
    implementation-plan.md
    source-register.md
    operations.md
    decisions/
  src/jobtology_db/
    cli.py
    settings.py
    contracts/
    connectors/
      ncs/
      qnet/
      job_alio/
      alio/
      saramin/
      work24_training/
    pipeline/
      discover.py
      fetch.py
      parse.py
      normalize.py
      extract.py
      resolve.py
      validate.py
      aggregate.py
      publish.py
    storage/
      raw_files.py
      postgres.py
      neo4j.py
    quality/
    observability/
  ontology/
    context.jsonld
    shapes.ttl
    terms.yaml
    mappings/
  config/
    sources/
    taxonomy/
    editorial_templates/
  migrations/
    postgres/
    neo4j/
  deploy/goldship/
    compose.yaml
    systemd/
  tests/
    unit/
    contract/
    integration/
    golden/
    fixtures/
```

Downloaded source data, credentials, Neo4j volumes, PostgreSQL volumes, and model caches will be ignored by Git.

## 19. Implementation phases

### Phase 0: Foundation and infrastructure

- Scaffold the repository and lock the Python toolchain.
- Add source, rights, claim, evidence, and release contracts.
- Add the reviewed Korean major-concept and alias catalog.
- Track the Goldship Compose deployment without secrets.
- Retain the public Coolify frontend/API route, replace wildcard Neo4j/database-proxy host publishing with the loopback/private-network design, and retain the tailnet-only boundary for administration and internal tools.
- Deploy dedicated PostgreSQL 17 with isolated pipeline and application databases and roles.
- Create the raw filesystem and permissions.
- Configure Tailscale-only administration and internal-tool access plus off-host backups.
- Add `jobtology_pipeline` PostgreSQL and Neo4j migrations plus the database/role bootstrap; the backend phase supplies `jobtology_app` migrations.
- Add CI, systemd locks/timers, `jobtology doctor`, and a full scratch-restore test.

**Exit:** Empty end-to-end publication produces a valid corpus release and passes backup restoration.

### Phase 1: NCS and credential backbone

- Ingest versioned NCS hierarchy and competency units.
- Ingest NCS-to-qualification mappings.
- Ingest Q-Net exam sessions.
- Load Schema.org/Jobtology mappings and SHACL shapes.
- Validate version preservation and taxonomy integrity.

**Exit:** A missing NCS competency can be traversed to a grounded credential and future exam session.

### Phase 2: Organizations, postings, and requirements

- Ingest ALIO institution API records and JOB-ALIO recruitment API postings.
- Ingest Saramin postings.
- Normalize the four occupation families and Korean aliases.
- Implement reversible organization and posting resolution.
- Extract required/preferred claims and evidence spans.
- Create the human-reviewed Korean golden set.

**Exit:** Each supported occupation has a valid cohort of at least 30 unique postings, or the API returns `INSUFFICIENT_DATA` without fabricating a statistic.

### Phase 3: Training and achievement options

- Ingest Work24 training and K-Digital instances.
- Normalize schedules, tuition, subsidies, eligibility, workload, and outcomes.
- Add reviewed project templates for the four occupations.
- Add reviewed skill-practice and application-preparation templates.
- Link credentials and course outcomes to accepted capabilities.

**Exit:** Every displayed achievement option has dates, workload, cost state, outcomes, and evidence.

### Phase 4: Aggregation and releases

- Build 180-day posting cohorts.
- Compute demand, experience, coverage, and difficulty aggregates.
- Emit calculation traces for every derived value.
- Publish immutable release manifests.
- Add release activation, rollback, and diff reports.
- Add freshness and source-health monitoring.

**Exit:** The frontend's counts, percentages, and gap rows can be served entirely from one release-consistent analysis response.

### Phase 5: Backend and chat integration

- Publish JSON Schemas and test fixtures to the backend team.
- Integrate user Person projections.
- Integrate CP-SAT route planning.
- Implement targeted and discovery goal/analysis contracts.
- Integrate SSE chat and typed retrieval tools.
- Implement evidence drawers, aggregate posting lists, and route activation.

**Exit:** A user can enter a profile, rank all four occupations in discovery, choose a targeted goal, horizon, and budget mode, receive a grounded application-readiness route or explicit infeasibility result, activate it, change a step state, and ask the chat why a step is recommended.

### Phase 6: Evaluation and demonstration

- Run extraction and resolution evaluation.
- Test idempotent reruns and source failures.
- Test expired offerings, missing costs, insufficient cohorts, and ambiguous skills.
- Test chat support validation and profile-write confirmation.
- Test backup restoration and full Neo4j rebuild.
- Re-project Persons and replay deletion tombstones after the rebuild.
- Replace every fixed PoC number with an API value.

**Exit:** All acceptance criteria below pass on the deployed Goldship environment.

## 20. Acceptance criteria

### 20.1 Grounding

- 100% of published requirement, learning-outcome, mapping, deadline, price, and aggregate claims reference at least one evidence span.
- 100% of displayed source facts resolve to claim/evidence IDs; derived values and recommendations resolve to calculation/decision traces; progress traces resolve to their user-state events.
- A citation resolves to an original source URL, source record, snapshot hash, locator, observation time, and rights record.
- The system labels inferred and predicted content distinctly from explicit source facts.

### 20.2 Quality

- Before prompt/rule tuning, freeze a hash-versioned set of 600 labeled Korean requirement spans, 150 per occupation, sampled across both posting sources and split by posting `70/15/15`. The held-out test contains at least 30 required, 30 preferred, and 20 negated examples. Extraction must achieve micro-F1 at least 0.85 overall and F1 at least 0.80 separately for required, preferred, and negation.
- Freeze 400 labeled entity-resolution candidate pairs across organizations, occupations, skills, and credentials, with 200 held out. Auto-accepted resolution must achieve point precision at least 0.95 and a 95% Wilson lower bound at least 0.90 on the held-out auto-accepted decisions.
- Re-running the same connector input creates zero duplicate snapshots, claims, or graph entities.
- A connector run with one successful page followed by a failed, missing, duplicate, or truncated page remains `FAILED`, advances neither freshness nor entity `last_seen_at`, and cannot enter a release; release `data_as_of` equals the minimum selected full-run `source_watermark_at` exactly.
- Identical normalized requirement conditions produce the same RoleRequirementKey across sources, and per-posting necessity collapse follows the fixed precedence.
- Invalid dates, missing source identities, broken evidence locators, and rights-policy violations block publication.
- Cohorts below 30 postings never produce a demand percentage.
- Activating an older non-revoked release reproduces its entity names, states, dates, prices, cohorts, and aggregates without reading newer revision properties.

### 20.3 Route correctness

- Every roadmap step satisfies its prerequisites in order.
- A route cannot be `FEASIBLE` or `RISKY` without satisfying every role-level required `RoleRequirementKey` and including application preparation.
- Every scheduled step fits the user's weekly availability and target date classification.
- Future graduation affects only `satisfiable_by_target`, never current coverage; fixed sessions, travel buffers, enrollment eligibility, and conservative unsubsidized cost are enforced.
- `LOW_COST` never calls an unknown-cost option cheap.
- Expired or closed postings and offerings are not recommended as open.
- Changing profile constraints produces a new analysis and unsaved replacement proposal; explicit materialization creates the new roadmap version and preserves completion only for exact semantic step-key matches with audited inheritance.
- Roadmap progress is consistent across home, roadmap, progress, and chat.

### 20.4 Chat correctness

- The LLM cannot access the database directly or issue arbitrary Cypher.
- Unsupported names, numbers, dates, costs, and availability claims fail the support validator.
- Every supported source fact, derived number, recommendation, and progress statement carries the correct evidence, trace, or user-event reference type.
- Each final answer carries `data_as_of`, `corpus_release_id`, and `methodology_version` from the pinned release.
- Chat-derived profile changes require explicit confirmation.
- Without versioned hosted-model consent, no user message/profile data leaves Goldship and all deterministic non-chat product functions remain available.
- No background worker creates a saved roadmap; initial or replacement route creation requires the explicit `이 경로로 내 로드맵 만들기` action, and activation requires its own explicit confirmation.

### 20.5 Operations

- All source schedules are observable in PostgreSQL.
- Failed records enter a retryable quarantine queue without blocking unrelated sources.
- Scratch restoration meets the 4-hour local and 8-hour R2/rebuild RTO targets; backup age meets the stated RPOs.
- Neo4j corpus data can be fully rebuilt from the pipeline ledger, raw store, and release manifest, followed by Person re-projection from `jobtology_app` and tombstone replay from the off-host deletion ledger.
- Restoring a coordinated set finds its active pointer and every non-revoked release referenced by its saved app artifacts in the restored Neo4j dump.
- A rights purge revokes every affected release, removes every affected local restore set and R2 restore-set snapshot, verifies that neither manifest index resolves a prohibited hash, and only then resumes publication; no revoked release can be read or reactivated.
- Restoring an older backup cannot resurrect a deletion reported `COMPLETED`, because traffic remains in maintenance mode through full re-projection and off-host deletion-ledger reconciliation; a still-`PENDING` request has never been represented as durable completion.
- A deletion request cannot become `COMPLETED` until the live Person projection is absent and the HMAC ledger snapshot is verified in R2; a pending request older than 15 minutes makes doctor unhealthy.
- Saramin and Work24 have no installed timer and cannot enter a release while their checked-in rights policies are blocked.
- Socket inspection finds no database, database-admin, or internal-tool listener on `0.0.0.0` or a public address; only the Coolify-managed product route is exposed publicly for Jobtology, and administration succeeds only through Tailscale.
- `jobtology doctor` fails on stale backup, release mismatch, failed restic check, migration drift, an unauthorized public database/internal-tool listener, or the stop-fetch disk threshold.

## 21. Explicitly deferred work

The following is scheduled after the MVP and is not included in its schema-loading or acceptance scope:

- Company-role hiring forecasts.
- Historical hiring-season prediction.
- External alumni, mentor, or professional profiles.
- Referral likelihood or `can refer` inference.
- Coffee-chat outreach.
- LinkedIn integration.
- Additional paid job-feed integrations beyond the licensed Saramin API.
- Automated job applications or course enrollment.
- Commercial data redistribution.
- Vector search and embedding-based retrieval.
- More target occupations beyond the finalized four-role catalog.

`Person` support in the MVP exists solely for the authenticated user's private projection. The deferred social layer cannot begin until an explicit consented data source and deletion policy exist.

## 22. Final decision register

| Topic | Final decision |
|---|---|
| MVP audience | Korean university students |
| Commercial status | Noncommercial school project |
| Supported occupations | AI engineer, backend developer, frontend developer, data analyst |
| Goal semantics | Application-ready by the target instant; no employment guarantee |
| Primary output | Grounded, versioned roadmap or explicit infeasibility result |
| Requirement/step states | `TODO`, `IN_PROGRESS`, `COMPLETED` |
| Budget | `REGULAR` and qualitative `LOW_COST` ranking |
| Time | Exact RFC 3339 KST instant derived deterministically from quarter, six-month, or one-to-five-year horizon, with end-of-month clamping |
| Weekly capacity | Derived 10/20-hour default with an explicit, independently stored 1–60-hour user override |
| Route solver | OR-Tools CP-SAT in backend |
| LLM role | Explain typed retrieval and solver output; no fact/statistic/route authority |
| LLM runtime | OpenAI Responses API with `gpt-5.6-luna`; model changes require a new evaluated methodology version |
| Graph database | Existing Neo4j Community 2026.06 |
| Relational storage | One dedicated PostgreSQL 17 container with isolated `jobtology_pipeline` and `jobtology_app` databases/roles |
| Raw storage | Content-addressed Goldship filesystem plus Parquet; no runtime object-store service |
| Off-host backup | Encrypted restic backup to private Cloudflare R2 |
| Scheduler | systemd timers invoking an idempotent Python CLI |
| Publication cadence | `03:00`, `07:00`, `13:00`, and `19:00` KST |
| Connector completeness | Only a validated `SUCCEEDED SCHEDULED_FULL` run advances freshness or can be selected for publication |
| Corpus watermark | Release `data_as_of` is the minimum source watermark across its selected external-source full runs |
| Ingestion language | Python 3.12 managed with `uv` |
| Graph extensions | No APOC in MVP |
| Retrieval | Canonical IDs, Korean full-text indexes, and graph traversal |
| Public ontology alignment | Schema.org plus `jt:` extensions, JSON-LD, and SHACL |
| User Person | Opaque Neo4j projection; PII and mutable state remain in backend PostgreSQL |
| Unknown course eligibility | Exclude that instance, return typed required inputs, and recompute only after confirmed facts are stored |
| User deletion | Immediate local erasure and `202`; completion only after graph deletion and verified off-host HMAC-ledger snapshot |
| Network | Public Coolify HTTPS domain routes to the FE gateway, which serves the FE and proxies same-origin `/api`; internal Web UIs and tools are Tailscale-only; FE-to-BE and BE-to-database traffic use separate private stack networks; backend and PostgreSQL publish no host ports; Neo4j publishes loopback-only administration ports; localhost is only for forwarded administration and health checks |
| Job sources | JOB-ALIO recruitment API and Saramin Open API |
| Learning sources | Work24 training API, NCS, and Q-Net |
| LinkedIn | Excluded |
| Forecasts/referrals | Deferred |
| Chat transport | HTTP Server-Sent Events |
| Corpus release rule | New work uses the active release; saved artifacts use their pinned non-revoked release; no calculation mixes releases |

This register is authoritative for MVP implementation. Changes require a dated architecture-decision record under `docs/decisions/` and corresponding contract-version increment.
