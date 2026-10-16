# Hop server access, persistent paths and editing runbook

**Current operating context, 2026-10-12 KST:** read the
[current handoff](current-handoff.md) for verified service state, scheduler and
installer reconciliation receipts. The [prefetched posting contract](prefetched-postings.md)
records the user's dataset-only policy for new job-board sources: do not request
their listing, description, iframe, image or signed-storage URLs. The dated
September notes below retain deployment history. The [JobKorea adapter](../../hop/ingestions/jobkorea/README.md)
documents its isolated import/linking tests, bounded execution commands and
measured costs. The supplied JobKorea snapshot and inferred occupation path were
deployed on October 8; their later verified state is in the handoff. Dataset-only
JobKorea processing adds no scheduled source requests.

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](linked-ingestion.md) for what is actually tested/deployed.

Baseline verified 2026-09-12; the October assessment is in the handoff above.
This is the existing Hop deployment, separate from the older
local Docker lab and the original Python ingestion container. Read this file,
[the real-data guide](../hop-real-data-guide.md), and the relevant source/LLM/
retention README before changing runtime artifacts.

## Permanent batch-free source graph migration (production VERIFIED)

The repository source loader now keeps exact import history and content/membership
proof in PostgreSQL while Neo4j contains business entities and grounded source
relationships. Source graph publication and inference replay use immutable exact
run evidence; current business facts may belong to a newer accepted observation.
Frozen LLM inputs, inferred edge IDs/payloads/review state, accounting and typed
posting dates remain protected.

The focused native installer is
`${PROJECT_HOME}/ingestions/jobkorea/install_batchfree_graph_publication.hwf`.
It waits for `graph/install.hwf` (date 001 and batch-free source graph 002), then
installs retention 002 and LLM publication 036. Use this focused path for an
existing runtime; the broad canonical installers replay older migrations.
Installation changes contracts and does not itself remove source-history nodes or
run storage retention. The guarded migration supervisor, reviewed preservation
manifest and independent readback are required for the runtime graph transition.
The guarded [operator contract](../../hop/operations/README.md) records its
reviewed command sequence and preservation checks.

Old standalone graph archive/delete retention pipelines now abort explicitly;
manual `retention/execute.hwf` uses only PostgreSQL proof/archive and local raw-file
checkpoints. It performs no Neo4j operation. JobKorea storage cleanup is unsupported
and remains separate. The original Python `load neo4j` publisher and updater
`neo4j=True` route also fail before graph I/O; use the native Hop source loader.

The 40-check isolated native inference receipt is
`~/.local/state/jobtology-hop/jobkorea-dry-run-cdd5182a8a06/receipt.json`.
It proves historical source/NCS pins after newer business node updates, exact
frozen payload preservation, missing-source-proof rejection and replay without
history-node recreation. The representative 84-run restored PostgreSQL benchmark
passed on the frozen graph SQL 002 revision. One persistent backend completed all
84 strict capture calls in **1,172.897 seconds** and all 84 finish calls in
**62.763 seconds**; the slowest individual begin was **115.838 seconds**.
Exactly **84 READY projections, 223,925 record proofs and 361,488 memberships**
were retained, with unchanged historical graph export fingerprints. A ten-minute
atomic statement limit is shorter than this measured cumulative capture work;
allow for the full capture plus native graph execution when monitoring the
guarded migration. Protected receipts and the exact SQL hash are in
`~/.local/state/jobtology-hop/batchfree-performance-939d9bfe6383/`.
The earlier posting-date cold-read investigation remains separate pending work.

**Live checkpoint, October 12 KST: VERIFIED.** The 41-file public deployment
is VERIFIED in
`~/.local/state/jobtology-hop/jobkorea-runtime-applied-79166d223a5845bfb0e1535f47bfe979/receipt.json`.
Focused graph 002, retention 002 and LLM 036 installation preserved all 145
existing protected table fingerprints. Native
`graph/migrate_source_graph.hwf` succeeded at **2026-10-11 17:43:43 UTC** in
**4,166.510 seconds**, including **3,394.886 seconds** of atomic capture. All
**86 source proofs are READY** (224,903 records / 363,444 memberships).

Coordinator receipt:
`~/.local/state/jobtology-hop/batchfree-locked-execution-a2c7aafbec514990a62b1ba472a22021/receipt.json`.
Its `apply/receipt.json` and coordinator receipt finished VERIFIED at
**17:56:42 UTC**. Removed **86 batch nodes, 224,903 record nodes and 585,681
scaffold relationships**; preserved all **240,196 existing business nodes** and
**800,648 existing business relationships**. Final totals are **240,288 nodes /
830,643 relationships**, including 92 real Q-Net sessions and 29,995 direct source
edges. Exact-run Q-Net replay passed in 213.960 seconds. The scheduler resumed
and the durable pending fence was removed; source requests and paid calls were
zero. Backup and exact receipts are in the
[verified handoff](current-handoff.md#live-checkpoint-verified).

Independent graph readback passed at **17:57:16.692019 UTC** in
`~/.local/state/jobtology-hop/batchfree-independent-report-734e9925ed1648c6bd29a3bfda89d2f5/after.json`:
all 22,295 source-posting dates/types/absence hashes and 5,878 inferred NCS edges
retain exact IDs/properties; no scaffold remains. PostgreSQL fingerprint evidence
is bound to the VERIFIED operator gate. Live atomic capture was slower than the
per-run benchmark; its cause and the earlier posting-date first-read TODO remain
separate pending performance investigations. Normal future updates use the
shared exact-run source loader, which cannot recreate the retired graph layer.

## Historical operational hold (superseded September 14)

As of 2026-09-13 KST, the user has paused attachment fetching/parsing, input
reconstruction and attachment-aware LLM extraction/linking. Read the
[attachment handoff](attachment-status.md) and Goldship's
`~/.local/state/jobtology-hop/attachment-hold.json` before resuming work.
The overall ontology goal does not override this hold. Ordinary six-source
API/CSV refresh is separate and remains enabled. The installed manual workflows
are still callable; the hold record is not a hard execution lock.

The stopped preview receipt is
`~/.local/state/jobtology-hop/document-packet-full-preview-20260912T155621Z/`.
Its FAILED supervisor status reflects the requested stop, and its database batch
is PLANNED with 513 planned request rows and zero sent model requests. The latest
hold verification is `~/.local/state/jobtology-hop/attachment-hold-verification-20260912T170912Z.json`.
Do not restart it as an apparent failed job.

## Connect and discover the running containers

When already on Goldship, the repository is `/home/maxjo/Jobtology-DB`; use the
local Docker commands below. From another machine, connect with:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 maxjo@goldship
```

`goldship` resolves over Tailscale; its verified tailnet IPv4 is `100.121.174.19`.
Tailscale may print a fresh SSH-check URL. Give that exact current URL to the user
and keep tracking the same SSH process while it waits. A tool observation timeout
does not mean that process exited. After user verification, poll that handle for
its actual result before starting deployment. If it has exited or the handle is
missing, request a fresh check when the user is available. Old verification links
expire; do not reuse links copied from conversation history. No password or API key belongs here.
Goldship has `rg` as of 2026-10-07; use it for repository searches.

Discover containers by the persistent volume/name, because container IDs can change:

```bash
docker ps --format '{{.ID}} {{.Names}} {{.Image}}'
docker ps --filter volume=ibbwv593fijblilse127wnqd-hop-config --format '{{.ID}}'
```

| Service | Verified container/name | Runtime |
|---|---|---|
| Hop Web | `b4a19e0a24e8`, `ibbwv593fijblilse127wnqd-051002227248` | `apache/hop-web:latest`, verified Hop 2.19.0 |
| Jobtology PostgreSQL | `b13984985171`, `j89dw8prq97uiec629avd6w5` | PostgreSQL 18; database `jobtology` |
| Neo4j | `52cdd899baf2`, `neo4j-1` | Neo4j 2026.06.0, database `neo4j` |

Do not use `coolify-db` for Jobtology data. The original ingestion application
container also exists but is not the Hop runtime. The Hop UI is
`https://hop.yeongmin.net/ui`.

## Traverse the host and container directories

The new [editorial catalogue module](../../hop/editorial/README.md) is tested
locally but **not deployed**. Its intended mounted project directory is
`${PROJECT_HOME}/editorial/`; the separate installer and import/review procedures
are in that guide. Do not infer that the directory or catalogue reviews exist on
Goldship from their presence in this repository.

**Tomcat runs inside the Hop container.** A Docker mount makes selected files
visible at both a host storage path and a container path; this does not install
Tomcat on the host. `docker exec` operates in the container filesystem.

| Purpose | Container path | Persistent host storage |
|---|---|---|
| Hop/Tomcat application root | `/usr/local/tomcat/webapps/ROOT` | Image filesystem, except mounts below |
| Hop configuration (`HOP_CONFIG_FOLDER`) | `/usr/local/tomcat/webapps/ROOT/config` | `/var/lib/docker/volumes/ibbwv593fijblilse127wnqd-hop-config/_data` |
| Default project (`PROJECT_HOME`) | `/usr/local/tomcat/webapps/ROOT/config/projects/default` | Same config volume, under `projects/default` |
| Raw responses, logs, review files | `${PROJECT_HOME}/data` | Same config volume, under `projects/default/data` |
| Private connection metadata | `${PROJECT_HOME}/metadata` | Same config volume |
| Protected API-key CSV files | `${HOP_CONFIG_FOLDER}/secrets` | Same config volume, outside the project |
| Hop UI audit state | `/usr/local/tomcat/webapps/ROOT/audit` | Volume `ibbwv593fijblilse127wnqd-hop-audit` |
| HTTPS forwarded-header context | `/usr/local/tomcat/conf/Catalina/localhost/ROOT.xml` | Bind mount `/data/coolify/applications/ibbwv593fijblilse127wnqd/tomcat/ROOT.xml` |

Confirm mounts rather than assuming the same deployment is still running:

```bash
docker inspect <hop-container-id> --format '{{json .Mounts}}'
docker exec <hop-container-id> id
docker exec <hop-container-id> ls -la /usr/local/tomcat/webapps/ROOT/config/projects/default
docker exec <hop-container-id> ls /usr/local/tomcat/webapps/ROOT/config/projects/default/metadata
```

The Hop process runs as UID/GID **501:501**. Write public artifact files with that
ownership and readable permissions. Prefer staging files and using `docker cp` or
`docker exec` over directly changing Docker's internal volume directories. Never
recursively change ownership or permissions on the entire project/config volume:
private metadata and secrets already have deliberate permissions.

Source `ingestion.document.raw_path` values on this server are **relative to each
source RAW_ROOT**, for example `<run_id>/all/page-1-confirm-0-attempt-1.json`.
To locate a file, prepend `${PROJECT_HOME}/data/<source-raw-directory>/`; use
`alio-raw` for organizations, `job-alio-raw` for postings, `ncs-raw` for NCS
competencies, and `<source_id>-raw` for the remaining sources. Do not interpret a relative database path against the shell cwd.
The retention preview resolves and displays these absolute paths explicitly.

The project contains `ingestions/`, `graph/`, `operations/`, `llm/`, `retention/`, `ontology/`,
`metadata/`, `data/` and project registration/configuration. Local repository `hop/`
contains the public, versioned workflow artifacts. It is not a full copy of the
runtime project: private connections and fetched data stay on Goldship.

## Edit and deploy public Hop files

1. Inspect the current worktree and any agent instructions. Compare the specific
   runtime files with the local files; the user can edit and save them in Hop Web.
   Do not overwrite unrelated live changes with a whole-project copy.
2. For an open artifact being replaced, have the user save and close it first if
   needed. An already open editor can hold an older in-memory copy and overwrite
   the deployed file on its next save. Newly added files do not require a restart.
3. Build/edit and test locally. `hop/llm/tools/build.py` and
   `hop/retention/tools/build.py` generate native XML; the Python generators/tests
   are development tools and are not runtime pipeline dependencies.
4. Stage only the specific changed public files under a temporary host directory.
   Record previous hashes and preserve a backup of files being replaced. Copy
   them into the existing project mount, preferably via a temporary filename plus
   a same-directory rename. Do not replace private metadata or `project-config.json`.
5. Set ownership **only on the deployed files** to 501:501 and verify SHA-256 hashes
   against the local artifacts. Native Hop reads them from the persistent mount.
6. Run the appropriate additive SQL installer if the change adds database objects.
   Use a SQL **workflow action**, not Table Input: DDL does not return query fields.
7. Execute the relevant native workflow/checks and inspect both final status and
   relevant database/graph counts. A successful Hop process alone is not a semantic
   data-quality check. Record tested run IDs and material limitations in the docs.

Do not redeploy/restart the container just to change project `.hpl`/`.hwf` files.
A restart/redeployment is needed only when changing the image or startup/server
configuration. The editor HTTPS fix is documented in
[the migration guide](../hop-migration-guide.md#131-hop-web-behind-an-https-reverse-proxy);
its authoritative file is the Coolify-managed bind mount shown above, not an edit
to an unmounted file inside a disposable container layer.

### Focused October installer and scheduler reconciliation

For the verified October drift, use the repository's host-side
`hop/operations/reconcile_runtime.py` from Goldship:

```bash
python3 hop/operations/reconcile_runtime.py plan
python3 hop/operations/reconcile_runtime.py apply <printed-manifest-path>
```

Inspect the protected manifest from `plan` before applying it. Both commands take
the scheduler's `refresh.lock`, discover the running containers and check for CLI
workflows, unfinished ingestion/refresh work and retention maintenance. Confirm
that no Hop Web workflow or open editor can race with the affected files; the host
lock does not control the UI. A changed container, file hash or approved catalogue
invalidates the plan and requires a new comparison.

The helper changes only its fixed public allowlist: ontology SQL 019–027, the
reader-grants script, `ontology/install.hwf`, Nara `003_checks.sql`, the new Nara
refresh wrapper and the host adapter. It verifies the unchanged installer
dependencies through 018 before replacing the installer last among its mounted
dependencies; the adapter is installed after its new wrapper. Existing replaced
files and a validated schema-only database archive are backed up in a protected
receipt directory. Each mounted file is staged, owned by 501:501 and hash-checked
before a same-directory rename. Allowlisted renames and exact temporary-file
cleanup use container root where parent-directory permissions require it; existing
directories keep their ownership and permissions. Final hashes and catalogue/reader
invariants must pass before the receipt becomes `VERIFIED`.

This reconciliation updates mounted installation artifacts and executes no SQL
migrations or grants against production. PostgreSQL already matched the catalogue
definitions from 019–027, and its validation view already contained both
`NOT MATERIALIZED` hints. Replaying the whole installer against that database is
unnecessary. The repeatable installer path is validated separately in an isolated
database. The source-only approval `ontology-catalog-source-20261001` and empty
`ontology.active_release` remain required invariants.

Receipts use `~/.local/state/jobtology-hop/runtime-reconciliation-plan-*/manifest.json`
and `runtime-reconciliation-applied-*/receipt.json`. A failure can leave a subset of
files installed: inspect `installed`, the failure phase/artifact, backups and
current hashes before preparing a retry. There is no automatic rollback or
database restore. Exact successful
receipt paths and native recovery/refresh results are in the
[current handoff](current-handoff.md).

## Run Hop and inspect data

After discovering the current container ID, invoke the CLI from the application
root (replace the placeholders, retaining the existing private project metadata):

```bash
docker exec -w /usr/local/tomcat/webapps/ROOT <hop-container-id> \
  bash hop-run.sh -j default -r retention-local \
  -f /usr/local/tomcat/webapps/ROOT/config/projects/default/retention/preview.hwf \
  -p 'SOURCE_ID=job_alio,SELECTION_MODE=OLDEST_COUNT,AMOUNT=1,KEEP_LATEST=2' \
  -l Basic
```

| Workflows | Run configuration |
|---|---|
| ALIO organizations | `alio-local` |
| JOB-ALIO | `job-alio-local` |
| Nara ingestion | `nara-job-local` |
| NCS competencies | `ncs-local` |
| Qualifications/Q-Net/career ingestion and operations refresh wrappers | `reference-local` |
| Source graph workflows | `graph-local` |
| LLM evaluation/enrichment/publication | `llm-local` |
| Attachment download, parser service and input preparation | `attachment-local` |
| Retention preview/execution/recovery | `retention-local` |
| Ontology source and independently reviewed claim assembly | `ontology-local` |

Use **Basic** logging. API/model request pipelines must not be previewed with
credentials in their rows, sampled, or run with Detailed/Rowlevel logging. The
protected key locations are:

- `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv`, one `service_key` column/key.
- `${HOP_CONFIG_FOLDER}/secrets/openrouter.csv`, one `api_key` column/key.

Do not print their contents, put keys in command-line arguments, copy them into
local test fixtures, or commit them. Private connections are named
`jobtology-postgres` and `jobtology-neo4j`; their metadata files may contain encrypted
credentials and must also stay private. Use the existing metadata from the runtime
project rather than reconstructing passwords from it.

For PostgreSQL read-only inspection on the host:

```bash
docker exec -i <postgres-container-id> psql -X -qAt -v ON_ERROR_STOP=1 \
  -U postgres -d jobtology <<'SQL'
BEGIN READ ONLY;
SELECT source_id,run_id,created_at FROM ingestion.latest_ready_run;
SELECT * FROM retention.plan_report ORDER BY created_at DESC;
SELECT * FROM retention.writer;
COMMIT;
SQL
```

The Neo4j database is `neo4j`; the verified private Bolt endpoint is
`192.168.100.201:7687`. Use the protected Hop `jobtology-neo4j` connection for native
checks. Do not assume an unauthenticated local `cypher-shell` command will work.
A later Neo4j Browser visit must use the user's existing authentication.

## Scheduler, locks and persistent logs

The existing source scheduler is a **host cron adapter**, not a Hop UI timer:

```cron
*/15 * * * * /home/maxjo/.local/bin/jobtology-hop-refresh >> /home/maxjo/.local/state/jobtology-hop/scheduler.log 2>&1 # jobtology-hop-refresh
```

It checks due intervals every 15 minutes; it does not fetch every source each time.
Source intervals and quota settings live in PostgreSQL. No retention workflow or
paid LLM workflow is attached to this schedule.
The adapter includes seven official sources. Nara's daily FULL wrapper pins the
new run ID in its parent workflow, verifies the graph, and saves its checkpoint
before success. A GRAPH queue entry recovers the exact READY run through
`operations/export_pending.hwf` without provider requests. Use `reference-local`
and Basic logging for these operation wrappers; see the
[refresh guide](../../hop/operations/README.md).

| Host path | Purpose |
|---|---|
| `~/.local/bin/jobtology-hop-refresh` | Source scheduler adapter |
| `~/.config/jobtology-hop/runtime.env` | Runtime container/path settings; treat as private |
| `~/.local/lib/jobtology-hop/redact_runner.py` | Redacts source API keys from CLI logs |
| `~/.local/state/jobtology-hop/refresh.lock` | Host `flock` used by the adapter |
| `~/.local/state/jobtology-hop/scheduler.log` | Scheduler output |
| `~/.local/state/jobtology-hop/*-<source>-<operation>.log` | Per-execution logs |

For public file deployment and SQL installation, take the **same host lock** and
check for manually running Hop CLI/UI workflows as well. The host lock serializes
only the adapter; it does not control the editor. Retention additionally uses its
PostgreSQL maintenance fence, source-write guards and graph writer leases. Never
clear those leases based only on age: confirm that the old workflow has stopped.
The [retention guide](../../hop/retention/README.md) explains failure recovery.

Operational scope: this repository currently has no backend app cutover to perform.
Source data is in `ingestion`; LLM derived data is in `enrichment`; compact source
history and cleanup audit data are in `retention`. Older design documents can
contain future app plans; verify deployed tables/workflows before acting on them.

Canonical source/claim assembly and candidate graph inventories now live in
`ontology`. `ontology/load_release.hwf` seals a release and verifies its Neo4j
projection; this does not activate a serving release. Check `ontology.graph_load`
alongside the actual Hop execution log. A reload clears its previous verification
checkpoint until every check passes. Deployment evidence for the 21 graph files
and native installer is under
`~/.local/state/jobtology-hop/graph-deploy-20260912T104446Z/`.
The initial live release remains PREPARING with no frozen production reviews.

## Native ontology JSON-LD export

For the independent JSON-LD export, repository `hop/ontology/` maps to
`${PROJECT_HOME}/ontology`, while repository-root `ontology/` contains the
versioned vocabulary and offline validation tools. Its generated SQL embeds that
package in `ontology.interchange_contract`; it is not a second runtime directory
to copy over the native workflows. Run `ontology/export_jsonld.hwf` with
`ontology-local` only for an already sealed release. Files are written to
`${PROJECT_HOME}/data/ontology-exports/<uuid>.jsonld` in the persistent project
volume. Wait for successful completion and validate before consuming a file.
See the [interchange operator guide](../../ontology/README.md). Attachment work
remains on hold; export reads stored release facts and does not parse documents.

## Typed requirements

For the subsequent PostgreSQL normalization stage, repository
`hop/ontology/schemas/requirement-normalization-v1.schema.json` maps to
`${PROJECT_HOME}/ontology/schemas/requirement-normalization-v1.schema.json`.
Use [the typed requirement guide](../../hop/ontology/requirements.md) for
`import_requirement.hwf`, `review_requirement.hwf`, `freeze_requirements.hwf`,
`read_requirements.hwf` and the `inspect_requirements.hpl` review queue. A proposal
file can live in `${PROJECT_HOME}/data/ontology/`; `NORMALIZATION_FILE` is its
full container path. These use `ontology-local` and the existing private
`jobtology-postgres` connection. They add no model call or scheduler; a review is
a separate explicit workflow action. The [typed graph/export guide](../../hop/ontology/requirement-graph.md)
covers `load_release.hwf` and `export_jsonld_v3.hwf` after the intended
normalization cut is frozen. Do not mistake a review, graph load or frozen
normalization membership for release activation.
The graph/v3 package is tested locally but is awaiting renewed Tailscale SSH
access for deployment; `export_jsonld_v3.hwf` is not installed live yet.

The deployed package is recorded at
`~/.local/state/jobtology-hop/ontology-requirements-deploy-20260912T180258Z/`.
It contains file hashes, before/after data fingerprints, native installer/read
logs and the draft readback. The new `ontology/schemas` directory is owned by
container user `501:501`, mode `0755`, matching editable project storage.

## Posting history and source freshness

Repository `hop/ontology/` is the same persistent `${PROJECT_HOME}/ontology`
runtime directory. With `ontology-local`, `capture_posting_census.hwf` captures
an exact accepted full JOB run, `freeze_observations.hwf` freezes a draft's
candidate states, and `read_observations.hwf` / `read_source_health.hwf` inspect
them (`RELEASE_ID`, `PREVIEW=Y`). See the [observation guide](../../hop/ontology/observations.md).

The shared `operations/record_graph_export.hpl` checkpoint now captures the JOB
census after a successful graph load. The existing refresh schedule and
`export_pending.hwf` recovery use that same transaction. This adds no network,
attachment or model requests. Captured history is protected from manual retention;
history compaction is not implemented.

The 14-file deployment and native installer receipt is
`~/.local/state/jobtology-hop/ontology-observation-deploy-20260912T170118Z/`.
Live verification is
`~/.local/state/jobtology-hop/ontology-observation-live-20260912T170317Z/`.
The source-only draft `ontology-observations-20260913-62f37c70` contains a frozen
545-posting history through JOB run `faa4ebe7-e422-4c9e-81d6-2216bbfcb98d`.
At that milestone, 513 were current and 32 historical postings still required
canonical membership. This draft is unsealed, unreviewed and not active.

Canonical historical membership and JSON-LD v2 were subsequently installed under
`~/.local/state/jobtology-hop/ontology-membership-deploy-20260912T172445Z/`.
The native installer exited 0; all 17 files matched the tested package and
protected existing data and the attachment hold were unchanged. For a **new**
source-assembled release, run `bind_observations.hwf`, then inspect
`read_posting_states.hwf`. Bind before review or document-input selection.
The observation time is the release's creation time; the earlier candidate draft
above cannot be retimed. `export_jsonld_v2.hwf` is the export for a subsequently
sealed release containing these states. The v1 exporter remains available for
older releases.

Live binding verified at **2026-09-13 02:40:29 KST**:
`~/.local/state/jobtology-hop/ontology-membership-live-20260912T172725Z/`.
Draft `ontology-history-20260913-f31190ec` has 545 bound postings: 513 current/
ACTIVE and 32 historical/EXPIRED. Exact source fields, employer links, times,
states and replay were checked. It remains unsealed and PREPARING; production
review selection and graph loading were not run. Existing data and the attachment
hold were preserved. Use that receipt's `verification.json` and pinned source
IDs when continuing; do not treat the draft as an active release.

## Native attachment parser runtime

The installed Hop Web plugin root is **`/usr/local/tomcat/plugins`**, from
`HOP_PLUGIN_BASE_FOLDERS`. Tika is under
`/usr/local/tomcat/plugins/transforms/tika`, not under `ROOT/plugins` or `WEB-INF`.
The verified runtime is Hop 2.19 with Tika 3.3.1 parser libraries.

Attachment artifacts live at `${PROJECT_HOME}/attachments`; original responses
are under `${PROJECT_HOME}/data/attachments`. Private database metadata remains
in the existing project metadata folder. Attachment downloads use the verified
public ALIO endpoint and do not read the OpenRouter key.

Tika XML output requires this option for the tested image's dedicated CLI process:

```text
HOP_OPTIONS=-Xmx1024m -Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl
```

Pass it with `docker exec -e` when invoking `hop-run.sh` from
`/usr/local/tomcat/webapps/ROOT`, with `-j default -r attachment-local`. This does
not change the already-running Tomcat JVM. Hop Web editor execution needs an
equivalent persistent JVM startup setting and a coordinated redeployment; do not
assume a Hop run-configuration variable can change a Java system property.
The [attachment guide](../../hop/attachments/README.md) describes limits and
workflow parameters. Deployment and current supervision receipts are in the
[completion ledger](ontology-completion.md#native-attachment-ingestion--2026-09-12).


## Document-processor service (September 14)

The private Docker service is `jobtology-document-parser`, on Hop's `coolify`
network, with no published host port. Persistent compose configuration is at
`~/.local/share/jobtology-hop/document-parser/compose.json` (service key `parser`).
Its only data mount is the read-only attachment archive directory, at the same
absolute path Hop records. It has no secret or connection-metadata mount.

The current service revision can be read without credentials:

```sh
docker exec jobtology-document-parser python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/health").read().decode())'
```

Do not recreate the parser while its native Hop workflow is running: each batch
pins the expected parser revision. Stage a new image, wait for the current run to
finish, then deploy and prepare a new batch. The optional explicit repair reuse
parameter preserves prior successful outputs with their original producing
revision. See [the linking guide](linked-ingestion.md) for current batch receipts,
installation order, raw-archive reuse and the review/publication sequence.

### Transfer large public review packets reliably

For multi-megabyte JSON, use `docker cp` to a temporary file on Goldship and then
`scp` to the local workspace. Compare SHA-256 on both ends and parse the entire
JSON before editing. During September 14 verification, an SSH-streamed `docker
exec ... cat` result was shorter than the actual file despite a zero exit code;
the native Hop file was complete, and `docker cp` plus `scp` preserved its hash.
Use the same hash checks when uploading a reviewed file. This concerns public
review artifacts; do not copy private connections or API keys into the repository.
