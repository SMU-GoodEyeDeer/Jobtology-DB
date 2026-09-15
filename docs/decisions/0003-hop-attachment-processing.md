# ADR 0003: Official JOB-ALIO documents as reviewed ontology evidence

**Resumed by user, 2026-09-14 KST:** proceed with the narrower source-ingestion,
attachment parsing and NCS-linking deliverable. Reuse `../document-processor` for
PDF/HWP/HWPX/DOC/DOCX; the earlier attachment and overall work holds below are
historical and are superseded for this phase. Preserve past runs and decisions.
Do not restart the stopped batch: prepare new, bounded runs after verification.
Cohorts, demand statistics and the broader application ontology remain later work.
See [the current implementation record](../hop-migration/linked-ingestion.md) for what is actually tested/deployed.

- Status: design accepted; execution on hold by user as of 2026-09-13 KST
- Date: 2026-09-12

Attachment downloads, parsing, input reconstruction and attachment-aware LLM
extraction/linking are deferred until the user explicitly asks to resume them.
This design decision does not override that hold. Existing artifacts and results
remain preserved; see the [pause record and restart handoff](../hop-migration/attachment-status.md)
for the stopped execution, unfinished work and resumption steps.

The ontology completion work includes job descriptions that are only present in attachments.
This supersedes ADR 0001 item 6's initial exclusion for the native Hop document-processing
path. The Python API connector and its existing `config/source_rights.yaml` scope remain
API JSON and attachment metadata. They must not inherit broader document permissions.

The companion, versioned [attachment policy](../../hop/attachments/policy.json) governs
Hop's separate `attachment` ledger. It permits the project's retrieval, retention and
source-grounded review of official recruitment notices and job descriptions linked by the
pinned JOB-ALIO metadata. It is an operational scope decision, not a new licence grant.
The [API catalogue](https://www.data.go.kr/data/15125273/openapi.do) describes attachment
metadata and displays an unrestricted-use label for that dataset; this is not recorded
as a blanket licence for every attached work. Original documents are retained privately;
this workflow does not redistribute them, accept claims or invoke a model. Later model
inputs and published excerpts must preserve their document/source provenance and the
reviewed scope, rather than treating the API's redistribution flag as document permission.

Only types A (notice) and C (job description), and PDF/HWP/HWPX, are fetched initially.
Application forms are accounted for as `APPLICATION_FORM`; other roles remain `ROLE_REVIEW`.
A notice can contain an embedded job description, so type A must not be omitted. Every
selected posting and file gets an explicit outcome, including zero attachments.

A live probe found that the OpenData download URL redirects to its homepage with a final
HTTP 200 HTML response. The [official JOB-ALIO posting page](https://job.alio.go.kr/recruitview.do?idx=304817)
links the same numeric attachment IDs and names to
`https://www.alio.go.kr/download/download.json?fileNo=<ID>`. The versioned resolver preserves
that ID, the original metadata URL and the actual request URL. It accepts only the expected
OpenData metadata URL shape; arbitrary URLs and file paths are not followed. Real PDF, HWP
and HWPX downloads confirmed this mapping. File signatures and parser media types are
checked in addition to HTTP status.

Each attempt uses a generated path, immutable source selection, SHA-256 readback and
explicit terminal outcomes. PDF pages, HWP body text and HWPX `Contents/sectionN.xml`
entries have distinct locators; a logical HWP/HWPX section is not claimed to be a rendered
page. Preview text, fonts and package settings are excluded from HWPX evidence. Successful
text extraction remains subject to semantic and layout review. Scanned, damaged, partial
or unsupported documents must not be represented as fully understood postings.

Native Tika XML output in the tested Hop image selects an incompatible Saxon factory by
default. The isolated runner uses the JDK XML transformer through a JVM system property;
this preserves the external-DTD restriction. It does not disable XML protections or add a
custom parser. The exact runtime requirement and remaining limits are in the attachment guide.
