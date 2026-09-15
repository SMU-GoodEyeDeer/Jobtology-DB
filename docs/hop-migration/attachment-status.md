# Attachment processing — resumption and historical hold

**Current pause, 2026-09-14 16:53 KST:** user requested a pause. No active paid
requests or native runners remain. Read the [current state and resume handoff](linked-ingestion.md)
before doing further work; the earlier resumption notice below is historical.

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](linked-ingestion.md) for what is actually tested/deployed.

## Historical hold — superseded by September 14 resumption

**Effective 2026-09-13 KST: attachment work was paused until the user explicitly
asks to resume it.** This supersedes earlier plans to run the compact-input paid
pilot or expand attachment-aware extraction to the full corpus. Do not interpret
an active overall ontology goal as authorization to resume this paused work.

## Scope of the hold

- Fetching/retrying attachment downloads and parsing PDF/HWP/HWPX files.
- HWPX reconstruction, OCR/format/role follow-ups and rebuilding attachment inputs.
- Attachment-aware LLM extraction/categorization, paid pilots and full batches.
- Accepting or publishing new claims derived from those attachment runs.

The six-source API/CSV ingestion, existing PostgreSQL/Neo4j source loading and
source refresh remain independent. They retain API attachment metadata but do not
run attachment parsing or paid inference. No attachment/LLM scheduler was added.
Manual workflows remain installed; this is an operational hold, not a database
permission or a hard execution lock. Read-only inspection of saved results is safe.

The workflow recipes in the real-data guide and attachment operator guide are
reference instructions for use after resumption. This also applies to no-spend
attachment previews: disabling paid requests does not lift the hold. The hold has
no automatic expiry, and an available API balance or a request to continue
unrelated database work does not resume attachment processing.

### Workflow handling while paused

Paths below are relative to the Hop project folder.

| Workflow or action | During the hold |
|---|---|
| `attachments/process_snapshot.hwf` | Do not launch, including download planning with `EXECUTE_DOWNLOADS=N`. |
| `attachments/structure_hwpx.hwf` | Do not reconstruct archived HWPX documents. |
| `attachments/prepare_inputs.hwf`, `attachments/prepare_structured_inputs.hwf` | Do not rebuild or create attachment input bundles or evaluation datasets. |
| `llm/evaluate.hwf`, `llm/enrich.hwf` | Do not run with attachment datasets or input bundles, including `EXECUTE_REQUESTS=N` previews. |
| Attachment-derived categorization, review acceptance or publication | Deferred with extraction; saved outputs are available for inspection only. |
| Ordinary source ingestion and refresh | May continue independently; retaining attachment URLs/metadata does not extract their contents. |

This defers a stage of processing; it does not mark attachment coverage or
attachment-derived ontology claims complete. Reuse the preserved artifacts after
explicit resumption and the checks below, rather than deleting or silently
restarting the stopped batch.

## Preserved work

The pinned JOB-ALIO dataset has **513 postings**. Its frozen v2 inputs account for
1,702 attachment metadata entries and supply **889 parsed document fields**.
HWPX reconstruction verified 29 of 32 files; the other three have explicit review
or failure outcomes. Archives, parser outputs, source hashes, page/section/table
lineage, immutable input bundles, model responses and review history remain saved.
Nothing was deleted to implement the hold.

The latest `field-lines-and-tables-v1` request encoding is **deployed**. It groups
exact text by field/line and HWPX cells by logical table row. Local native tests
passed, and an independent decoder preserved all **223,976 source passages**,
6,336 HWPX input blocks, 308 tables and 4,456 cells. Reconstructed extraction
requests all fit the configured 200,000-character limit, with a maximum of
159,547. These are local structure/size checks; the fresh live full request
preview was stopped before producing its inventory.

Deployment receipt on Goldship:
`~/.local/state/jobtology-hop/document-packet-deploy-20260912T155537Z/`.
Three public files matched the tested package, the native installer exited 0,
and protected source/model/input/review/release fingerprints were unchanged.
The default prompt remains `ko-v3`; the changed encoding applies to explicit v7
requests. Existing prompts and saved responses were not rewritten.

## Stopped execution and live verification

The no-spend full preview was intentionally stopped at **2026-09-12 15:58:40Z
/ 2026-09-13 00:58:40 KST** after the user's pause request. Its receipt is:

`~/.local/state/jobtology-hop/document-packet-full-preview-20260912T155621Z/`.

- Dataset: `korean-attachments-sourcebound-v1-513` (preserved).
- Batch: `d861198b-d282-4e6c-9963-d5ff10396189`.
- Database state: `PLANNED`, `execute_requests=N`, **zero sent model requests**.
  The latest readback contains 513 `PLANNED` request rows, with no reservations,
  responses or reported costs. These are saved plans, not executed requests.
- Supervisor state: `FAILED` from the intentional SIGTERM, not a new model or
  validation defect. `pause-request.json` and `pause-verification.json` explain it.
- The exact native Java process and supervisor stopped; the two scheduler/LLM
  locks were released. No native runner, active preview query, RUNNING enrichment
  batch or RESERVED request remained at verification.
- **The planned three-posting paid test was not launched.** No paid calls were
  made by this deployment or stopped preview. Do not restart either automatically.

Goldship also has a persistent operational record at:
`~/.local/state/jobtology-hop/attachment-hold.json`.
It records the user instruction, scope, stopped receipt and verified database
state. Future agents should read it alongside this document.

The hold was rechecked at **2026-09-13 02:09:12 KST**. There were zero in-flight
attachment attempts, HWPX readers, RUNNING enrichment batches, RESERVED model
requests or registered writers. The only native workflow running was the separate
`ontology/freeze_observations.hwf`, which reads existing source snapshots.
Read-only verification receipt:
`~/.local/state/jobtology-hop/attachment-hold-verification-20260912T170912Z.json`.
The original stop receipt's zero-attempt count was a point-in-time observation;
use this later verification for the preserved 513 planned rows. The hold record
and existing processing data were not changed by this check.

## Quality and remaining work

The most recent completed paid attachment pilot is still batch
`9bd86bc7-165a-4b14-b41c-ebcb79723ddb`: three responses, zero validated extractions,
three rejections, no categorization calls, $0.03981502 reported cost. Source review
also found missing research/bonus scoring rules and incorrect role applicability.
The compact encoding has **not** yet been evaluated with a real model.

Production acceptance remains one reviewed **inline-only** extraction, zero
accepted NCS links and zero active ontology releases. Preserved attachment text
must not be represented as reviewed, complete ontology claims. Missing/scanned,
malformed, unsupported and ambiguous attachment outcomes remain open.

After explicit user resumption:

1. Inspect the hold, exact process identities, database state and deployed hashes.
   Preserve the stopped batch and all earlier receipts; a PLANNED row does not
   mean a process is running or a request should be resumed automatically.
2. Complete a new no-spend native preview against the same frozen 513 inputs and
   verify its actual requests, hashes and unchanged acceptance state.
3. Recheck OpenRouter balance, then run the bounded three-posting quality test
   with recorded model/settings. The last balance read was **$6.03993481** at
   2026-09-12 15:57:14Z; it is not a current spending guarantee.
4. Review actual conditions, role scope, AND/OR, scores/limits and supported NCS
   matches. Address validator defects separately from extraction errors. Only
   expand after quality and measured cost support it.
5. Finish attachment coverage, production extraction/review/linking and the
   remaining ontology publication requirements. Update/archive the hold record
   only after explicit user resumption, preserving its history.

For unrelated ontology work and the full completion requirements, see the
[completion ledger](ontology-completion.md). Server access and mounted paths are
in the [server runbook](server-runbook.md).
