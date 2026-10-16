# Future JobKorea imports: operator assessment

Date: **2026-10-16 KST**. Repository code assessment only; this assessment made no
production change, source request or paid call. The [current handoff](current-handoff.md)
remains the operational authority. Items marked proposed below are TODOs, not
implemented automation or a new paid-processing authorization.

## Implemented local import behavior

The native [full workflow](../../hop/ingestions/jobkorea/full.hwf) accepts another
supplied local NDJSON file, archives exact bytes, validates PostgreSQL evidence,
loads/verifies the source graph and saves its checkpoint. It does not run an
occupation matcher. NDJSON requires one complete object per physical line and a
terminal LF; CRLF is accepted. Bounded batches and immutable byte/line checkpoints
support exact archive-only resume after interruption. Staged rows remain outside
the READY projection until the whole file passes validation. PostgreSQL READY
and Neo4j publication are separate stages: graph failure preserves accepted
evidence for exact replay. See the [adapter commands](../../hop/ingestions/jobkorea/README.md#current-format-and-scale),
[native reader](../../hop/ingestions/jobkorea/tools/build_ndjson.py) and
[final validation](../../hop/ingestions/jobkorea/sql/008_ready_statistics.sql).

Posting identity comes from the numeric ID in the supplied product-page reference:
`source:posting:jobkorea:<sha256(native_posting_id)>`. A new file containing the
same ID adds immutable source evidence for the same graph entity. Exact file
bytes, parser version and policy revision identify one import run, so identical
file replay preserves its original import time and records. Duplicate posting
IDs within one NDJSON file fail validation; the optional
[composition helper](../../hop/ingestions/jobkorea/tools/compose_full_dataset.py)
can select a whole observation from overlapping supplied files while preserving
every original occurrence. Its CLOSED/deadline/richness/filename selection policy
does not establish collection chronology.

Each accepted row is a **complete observation**, not a partial-field patch. The
[normalizer](../../hop/ingestions/jobkorea/sql/002_operations.sql) constructs a new
normalized object without merging previous runs. The
[current entity reader](../../hop/graph/sql/009_reader_fact_worksets.sql) selects
one JobKorea observation and exports its metadata whitelist. Missing optional
fields can therefore remove earlier values from current facts; omitted/null end
dates use the established rolling-deadline policy. Required identity/title and
other validation rules still apply. A delta file may contain only changed posting
IDs, but each included posting must carry its intended complete observation.

All files remain `FILE_ONLY`, `provider_complete=false`,
`absence_is_closure=false`. Postings absent from a later file are retained;
omission never closes or deletes them. Explicit supplied CLOSED status is
normalized. PostgreSQL retains original source records, snapshot membership,
ingestion observations and immutable projection proofs. Neo4j holds stable
business entities, selected current source facts and direct relationships, with
no ingestion batch/source-record scaffold nodes.

## Ordering, collection evidence and operator interface

Current graph facts prefer the containing READY run with the greatest
`ingestion.run.created_at`, then run ID, representation priority and record ID.
Names separately prefer nonblank candidates. Replaying an already known old file
does not change its ordering, but importing a previously unseen older export
later can supersede newer source facts. Actual collection evidence does not
control this selection.

The [date projection](../../hop/graph/sql/001_posting_ingestion_dates.sql) records
first/latest ingestion using JobKorea receipt `imported_at`; it uses collection
evidence only from the latest containing import. A new run with unknown scrape
time clears the older scrape properties. Import time and file modification time
are not scrape time. Each new batch needs its own supported collection evidence;
the user-reported `2026-10-08 02:48:14 Asia/Seoul` applies only to the original
8,434-posting snapshot. Preserve original receipts and frozen input hashes.

An unchanged file collected again has the same run identity. It is treated as a
replay, not a fresh ingestion/collection occurrence; supplemental collection
evidence is also one immutable row per run. Recording repeated collections of
identical bytes would require a separate collection-event design.

The native workflow is reusable. The
[reviewed host wrapper](../../hop/operations/load_jobkorea_dataset.py) accepts a
composition directory, reviewed deployment manifest and private checkpoint
directory; it checks the supplied `selected_count`, not a hardcoded 8,434 cohort.
It also installs SQL, freezes inputs and checks runtime/catalogue/preservation
pins. Its [shared guard](../../hop/operations/reconcile_runtime.py) includes
historical catalogue/reader-contract expectations and rejects existing LOADING
runs. Requalify those assumptions for routine use; recover an interrupted exact
run through native archive-only resume before retrying the wrapper.

Triggering remains manual. The [scheduler](../../hop/operations/refresh.sh)
enumerates the seven other sources and has no JobKorea drop-folder watcher,
refresh policy or scheduled local import. No source fetching or automatic
closure/deletion is authorized.

## Proposed follow-up TODOs

- **Chronological promotion:** define and test how actual collection order,
  unknown times and late historical arrivals determine current facts. Preserve
  immutable receipts and distinguish source chronology from ingestion order.
- **Incremental NEW/CHANGED linking queue:** compare stable posting IDs and
  relevant source-evidence hashes, pin exact inputs/catalogues and enqueue only
  justified new work with cumulative accounting and no duplicate paid requests.
  Source ingestion currently does not launch this queue. The completed O*NET
  matcher covered its pinned original cohort; its reference catalogue/details
  are reusable, but that task is not future-import automation.
- **Stale-link supersession:** existing inferred edges survive source changes.
  NCS publication retires links only within its same source/catalogue pins;
  cross-run invalidation needs an explicit rule, retained history and verification.
  Preserve actual review status and NULL/UNASSESSED confidence.
- **Posting-specific technology mentions:** derive cited mentions only from
  supplied posting evidence, distinguishing source statements from occupation
  reference data or inferred associations. Missing local descriptions remain
  explicit; no URL recovery is permitted.
- **Targeted quality review:** prioritize changed-source and ambiguous outputs
  with individual decisions; technical validation must not confer blanket
  semantic review status.
- **Measured performance:** continue the handoff's bounded ingestion, graph
  reader/verifier and proof-capture measurements before proposing optimizations.
  Advertised size bounds do not establish larger production capacity.

These TODOs preserve the existing NCS/O*NET contracts, task accounting caps and
source-access restriction. A scheduler/watcher and repeated-identical-collection
events are separate optional workflow extensions, not prerequisites for the
implemented manual local import.
