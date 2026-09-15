# Native JOB-ALIO attachment ingestion

For the resumed source → document → duty → NCS workflow, start with the
[current practical linking guide](../../docs/hop-migration/linked-ingestion.md).
It describes the parser service, exact live inputs, incremental model runs, batch
review files and `llm/publish_links.hwf`. Earlier ontology/hold sections below are
historical or later work, not extra prerequisites for this ingestion deliverable.

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](../../docs/hop-migration/linked-ingestion.md) for what is actually tested/deployed.

**On hold by user, 2026-09-13 KST.** Do not start downloads, parsing, HWPX
reconstruction or attachment-aware LLM runs until the user explicitly resumes
this work. Existing data and installed workflows are preserved. See the
[pause status and restart handoff](../../docs/hop-migration/attachment-status.md).
The instructions below describe available capabilities, not a scheduled run.

These workflows fetch original recruitment documents and store parsed evidence in the
additive PostgreSQL `attachment` schema. They do not accept LLM claims or load Neo4j.
Use the existing `jobtology-postgres` connection and `attachment-local` run configuration.
The [scope and URL resolution decision](../../docs/decisions/0003-hop-attachment-processing.md)
and immutable `policy.json` accompany each batch.

1. Run `attachments/install.hwf` after ingestion, operations and manual retention are installed.
2. Run `attachments/process_snapshot.hwf` with the exact `JOB_RUN_ID`. Start with explicit
   `POSTING_IDS`, separated by `|`, and `EXECUTE_DOWNLOADS=N` to inspect the plan.
3. Use its reported `BATCH_ID`, identical selection/root/cap, and `EXECUTE_DOWNLOADS=Y` to
   fetch and parse the planned files. Inspect `attachments/inspect.hpl` with that batch ID.

| Parameter | Default | Meaning |
|---|---|---|
| `BATCH_ID` | blank | New UUID when blank. Reuse the exact ID to resume its immutable plan. |
| `JOB_RUN_ID` | required | Exact accepted FULL JOB-ALIO snapshot. |
| `POSTING_IDS` | blank | All postings, or explicit numeric IDs separated by `|`. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/attachments` | Absolute managed directory. Names from the source never become filesystem paths. |
| `MAX_FILES` | 20 | Reject planning above this eligible-file count; never silently truncate the selection. |
| `EXECUTE_DOWNLOADS` | N | Y enables network requests and parsing. |

Rerunning a batch reuses its completed attempts without downloads or duplicate sections.
An attempted failure is retained; a deliberate retry currently needs a new batch ID.
An interrupted reserved attempt is not assumed dead or automatically retried. Inspect the
actual process first; recovery must finish that exact attempt and release its writer before
resuming. Do not blindly delete a writer row to clear a running execution.

`attachment.report` accounts for every selected posting. `PARSED` means text was extracted,
not that the job is fully transformed or its requirements have been accepted. Other outcomes
include forms excluded from processing, roles needing review, unsupported formats, unexpected
HTTP bodies, parse failures, parser warnings and documents without extracted text. A batch
can finish with these outcomes and still have semantic completeness gaps.

The ledger retains pinned API document/locator/hash, attachment ordinal and metadata,
original/resolved URL, received and saved byte hashes, response headers, parser version,
original parser XML/metadata, and exact section text/hashes. PDF locators refer to pages;
HWP has a document body; HWPX uses named XML sections. The full parser output is retained
for investigation, but HWPX preview/font/settings entries are excluded from evidence sections.
No OCR completeness or table-layout reconstruction is claimed by `PARSED`.

Source snapshots pinned by attachment batches are protected by retention before graph/file
cleanup. Raw attachments and parsing history are retained; attachment-specific pruning and
ontology release integration remain separate work.

## PDF metadata compatibility

New parses use storage contract `xml-jsonb-v2`. `parser_metadata_raw` preserves the
exact metadata string emitted by Tika, and `parser_metadata_hash` hashes that string.
`parser_metadata` is its PostgreSQL-compatible representation. Escaped NUL becomes
U+FFFD there; literal escaped backslashes stay intact. `metadata_normalization`
records the policy, count and affected fields. Only the verified PDF title fields
can normalize this way without requiring review. XML and extracted body text are
unchanged. Existing `xml-jsonb-v1` rows keep their original data and hashes.

## Prepare versioned LLM inputs

Install the updated `llm/install.hwf` and `attachments/install.hwf`, then run
`attachments/prepare_inputs.hwf` with `attachment-local`. Deployment status and
live receipts are in the completion ledger; a generated local artifact alone does
not establish that its current version is installed on the server.

- `JOB_RUN_ID`: exact job snapshot used by the attachment batches.
- `ATTACHMENT_BATCH_IDS`: completed batch IDs separated by `|`. Later entries take
  precedence for a file, allowing an explicitly selected retry to replace a failure
  in the new input while retaining the original attempt.
- `POSTING_IDS`: selected IDs separated by `|`; blank selects the whole snapshot.
- `POSTING_LIMIT`: maximum selected postings, default 20; exceeding it fails.
- `DATASET_ID`: a new frozen evaluation dataset, or blank to prepare ENRICH inputs.
- `NCS_RUN_ID`: the NCS snapshot for the optional evaluation dataset.

For evaluation, pass the resulting `DATASET_ID` to `llm/evaluate.hwf`. For production
processing, pass the reported `bundle_ids` to `llm/enrich.hwf` as `INPUT_BUNDLE_IDS`
and use the same `JOB_RUN_ID`. Both paths require `PROMPT_VERSION=ko-v6` and
`ACCEPTANCE_POLICY=REVIEW`. Start with `EXECUTE_REQUESTS=N` to inspect requests.
Preparing or replaying input bundles makes no HTTP/model calls.

Each `enrichment.input_bundle` retains the complete inline fields, parsed document
text, every attachment outcome and the exact source/document/attempt bindings.
Document fields are `attachment_<ordinal>_<file-id>`. Their pages/sections are joined
with one LF; the manifest records each original section's zero-based, half-open
Unicode code-point range and hash. For these v1 bundles, only PARSED documents supply model text. Forms,
unsupported files and failures remain visible outcomes. No text is truncated.

The content hash excludes attempt IDs, batch IDs and private disk paths, so identical
source content can reuse a model cache entry across parsing attempts. The bundle ID
includes the exact lineage. Changes to document bytes, text, outcomes or source
metadata change the content hash. Frozen datasets and item bindings are append-only;
new inputs never rewrite existing model attempts, corrections or decisions.

Document fields participate in narrative evidence validation and source accounting.
This does not certify Korean meaning or complete attachment coverage. Existing
ontology source selection and document-evidence projection still need integration
before attachment-aware revisions can form a published ontology release.

## Reconstruct HWPX paragraphs and tables

`attachments/structure_hwpx.hwf` reads already archived HWPX files using native
Hop VFS, Calculator and SQL transforms. It makes no download/model calls and does
not replace Tika results. Use `attachment-local` with these parameters:

| Parameter | Meaning |
|---|---|
| `BATCH_ID` | New structure batch ID; the identical ID/selection replays completed outcomes without rereading files. |
| `JOB_RUN_ID` | Exact job snapshot pinned by the attachment batches. |
| `ATTACHMENT_BATCH_IDS` | Completed attachment batches separated by a pipe, with later attempts taking precedence. |
| `POSTING_IDS` | Optional numeric IDs separated by a pipe; blank selects all eligible archived HWPX files. |
| `MAX_DOCUMENTS` | Explicit count cap, default 20. Exceeding it fails planning. |

The package's manifest/spine determines section order. Original XML member bytes
and hashes are retained; parsing records paragraph/control order, nested tables,
cell coordinates and merged-cell spans. Block and cell numbers are local to each
XML entry, independent of nonunique IDs written by the authoring application.
Formatting runs join without invented spaces. Native archive hashes are checked
before and after the reads. Entry names are restricted to the package header,
manifest and section XML paths; declared members are bounded to 16 MiB each and
64 MiB in total. These metadata/acceptance limits are not a hard streaming memory
or execution-time guarantee.

Inspect the saved outcomes:

```sql
SELECT s.batch_id, d.posting_id, d.metadata->>'atchFileNm' AS filename,
       s.state, length(s.body_text) AS text_characters, s.issues
FROM attachment.hwpx_structure s
JOIN attachment.attempt a USING (attempt_id)
JOIN attachment.document d USING (document_id)
WHERE s.batch_id = '<structure-batch-id>'
ORDER BY d.posting_id, d.file_ordinal;
```

`VERIFIED` certifies this text/layout reconstruction, not its semantic acceptance
or complete visual content. Embedded images are recorded as unreviewed. Unknown
text controls and invalid table geometry require review; malformed packages and
changed archives fail individually. Other files continue, and every terminal
outcome releases its retention writer. A deliberate retry uses a new batch ID.

Run `attachments/prepare_structured_inputs.hwf` to create **attachment-input-v2**
bundles. It accepts the same parameters as `prepare_inputs.hwf` plus
`HWPX_BATCH_IDS`, an explicit ordered list of completed structure batches whose
attachment parent selection exactly matches `ATTACHMENT_BATCH_IDS`. Only verified
HWPX reconstructions supply HWPX text; failed, unreviewed or unprepared structures
remain visible outcomes. Other document formats keep the v1 selection rules.
Use a new `DATASET_ID` for evaluation; existing datasets and v1 bundles stay frozen.

The v2 model request retains every original passage ID and text. IDs encode the
source field and original line number; the full character offsets remain in the
database. Compact layout arrays group blocks/tables/cells by section and identify
block line ranges, paragraph ownership and table relationships. A missing final
block role defaults to `body`. This avoids repeatedly sending audit hashes and
field/offset metadata, without truncating document text. Original block offsets,
entry hashes and complete lineage remain in the immutable bundle manifest.

`hop/attachments/tests/native_hwpx.py` exercises real XML against an independent
archive reader, nested/merged tables, section order, failed children, immutable
replay, cache identity across new reconstructions and native v2 input preparation.
`structured_input_checks.py` separately verifies all model passage IDs/text and
compact layout ranges. Test fixtures and production semantic review are separate.
See the [completion ledger](../../docs/hop-migration/ontology-completion.md) for
which version is deployed and which live files have been independently verified.

## Tika runtime setting

The tested Hop 2.19/Tika 3.3.1 image needs this JVM option for XML output:

```text
-Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl
```

For a dedicated `hop-run.sh` invocation, include it in `HOP_OPTIONS`, together with a bounded
heap such as `-Xmx1024m`. The option selects the JDK factory and preserves Tika's external-DTD
restrictions. The Hop Web JVM needs the equivalent startup option before running this
pipeline in its editor. A run configuration variable does not set a JVM system property.
Do not redeploy an editor with unsaved work merely to run a batch; a separately launched
native CLI process can use the same mounted project and its private metadata.

REST buffers the response before the 64 MiB content check. Tika similarly parses before the
2,000,000-character check. These are acceptance limits, not hard streaming memory limits.
Use sequential files, a bounded JVM heap and supervised executions; do not claim that large
or adversarial archives have a strict per-file parser timeout. HTTP connect/read timeouts are
10/60 seconds, and configured REST retries and pagination are disabled.

The attachment workflows make no paid calls. Model requests are controlled by the
separate LLM workflows and their execution/spending parameters. Document evidence
must also be projected into ontology releases before those claims are published.

## Verification and current coverage

The deployed full pass for the 513-posting snapshot attempted 909 PDF/HWP/HWPX
notices/job descriptions: 888 PARSED, 12 NO_TEXT, five PARSE_ERROR and four
NEEDS_REVIEW. All 909 saved-file hashes/sizes and 4,152 section contents/locators
were independently verified. The other metadata entries include application
forms, roles needing review, ZIP bundles, images and DOCX. See the
[completion ledger](../../docs/hop-migration/ontology-completion.md#native-attachment-ingestion--2026-09-12)
for exact pins, receipts, known metadata failures and remaining integration.

Focused tests use the initialized disposable ontology containers:

```sh
python hop/attachments/tests/checks.py
python hop/attachments/tests/native.py
python hop/attachments/tests/input_checks.py
python hop/attachments/tests/native_inputs.py
```

The native test routes only its copied pipeline to a synthetic local HTTP server.
It verifies no-request planning, parser failure isolation, blank/false-PDF handling,
Korean HWPX extraction, result correlation and replay without further requests.
The production pipeline keeps its fixed official URL resolver and HTTPS validation.

The metadata retry recovered four of the five original PDF parse failures. Selecting
that retry after the original full batch now supplies 892 parsed document fields.
All 513 posting input bundles and the three-case `korean-attachments-v1` EVAL
dataset are prepared and independently verified. Twelve document fields contain
very long flattened lines; HWPX paragraph/table handling and broader semantic
review remain necessary. See the completion ledger for the native results and
the separately reconciled supervision-reporting error.
