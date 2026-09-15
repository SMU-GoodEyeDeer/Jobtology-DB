# Reading editorial and external ontology sources

For selected occupation assignments and normalized requirements, see the
[derived-claim readers](derived-queries.md). The v2 source readers below retain
their existing contract.

**Native Hop/PostgreSQL tests passed locally; not deployed to Goldship.** The `hop-ontology-read-v2`
PostgreSQL contracts return the selected editorial definitions with their original
source pointers and frozen review. They also cover existing external source
entities. They are database functions and native Hop readers, not HTTP endpoints
or a new backend application. Attachment processing remains
[on hold](../../docs/hop-migration/attachment-status.md).

Install `editorial/install.hwf` after the ontology v3 installer. Use
`ontology-local` for these entry points in `${PROJECT_HOME}/editorial/`:

| Workflow and matching `.hpl` | Additional parameters | Result |
|---|---|---|
| `read_summary_v2.hwf` | None | Six external source pins, selected editorial source, counts and publication issues. |
| `read_entities_v2.hwf` | `ENTITY_KIND`, `SCHEME_ID`, `PAGE_SIZE`, `CURSOR` | Paginated identities/revisions/names, scheme IDs and source-support counts. |
| `read_entity_v2.hwf` | `ENTITY_ID` | The selected revision, source evidence references, catalogue relations and existing posting details. |
| `read_source_record_v2.hwf` | `SUPPORT_ID` | The exact selected source record and its provenance. |

All accept `RELEASE_ID` and `PREVIEW` (default `N`). Set an exact draft ID and
`PREVIEW=Y` to inspect unfinished work. Open the matching pipeline and preview
**Preview JSON here** to read `result_json`; Basic logging does not print the full
source document. These workflows do not fetch files, parse attachments, request
inference, create reviews, load Neo4j or activate a release.

## List the four product occupations

In `read_entities_v2.hwf`, set:

- `RELEASE_ID`: an assembled draft containing a reviewed editorial pin.
- `PREVIEW=Y`.
- `ENTITY_KIND=occupation`.
- `SCHEME_ID=urn:jobtology:conceptScheme:product-occupations`.
- `PAGE_SIZE=100`, `CURSOR` blank for the first page.

The equivalent SQL is:

```sql
SELECT ontology.query_entities_v2(
  '<release-id>',
  'occupation',
  'urn:jobtology:conceptScheme:product-occupations',
  100, NULL, true
);
```

The scheme filter selects members, so the scheme identity itself is not one of
these four results. Use `urn:jobtology:conceptScheme:ncs` for NCS occupations;
omit the scheme filter to list all occupations. A scheme not selected by the
release raises `ONTOLOGY_SCHEME_NOT_IN_RELEASE`. `Person` is outside the public
entity kinds and cannot be requested here.

For another page, pass the exact returned `next_cursor` with the same release,
entity kind and scheme. Page size is 1–100. The cursor binds those choices, the
selected entity/revision set and editorial membership. A cursor from another
release, different filters, a changed selection or the v1 reader fails with
`INVALID_ONTOLOGY_CURSOR`. Pinning editorial data into an unsealed draft also
invalidates an earlier cursor, even if its filtered NCS rows did not change.
Keep the returned release ID for subsequent requests instead of re-resolving the
active pointer.

## Follow a definition to its source

```sql
SELECT jsonb_pretty(ontology.query_entity_v2(
  '<release-id>',
  'urn:jobtology:occupation:product:AI_ENGINEER',
  true
));
```

The response includes:

- `entity`: the release-selected definition and revision hash; names and aliases
  come from that revision.
- `editorial_source`: selected catalogue version, file SHA-256, Git blob SHA-1,
  membership hash, pin time and the **selected** review, including its actor,
  timestamp and merge attestation. Later reviews are not substituted here.
- `source_support`: an array with a `support_kind` discriminator and stable
  `support_id` for each entry. `EDITORIAL_ENTRY` refers to a catalogue entry;
  `EXTERNAL_RECORD` refers to an immutable copied ingestion record. Editorial
  entries do not invent connector run IDs or HTTP observations.
- `catalogue_relations`: explicit `IN_SCHEME` relations with both selected
  revision IDs, names, source-support ID and selected review. Reading the scheme
  itself returns its four incoming member relations.

Pass the returned `support_id` to `read_source_record_v2.hwf`, or:

```sql
SELECT jsonb_pretty(ontology.query_source_record_v2(
  '<release-id>',
  '<support_id from source_support>',
  true
));
```

For `EDITORIAL_ENTRY`, this returns the exact original UTF-8 catalogue text,
byte length and hashes, the `/scheme` or `/occupations/<index>` pointer, the
original JSON entry, normalized definition and selected revision/review IDs.
The support ID matches the source-record node ID used by the Neo4j projection.
An ID belonging only to a different catalogue version fails with
`ONTOLOGY_SOURCE_RECORD_NOT_IN_RELEASE`; a filename is not a valid support ID.

For `EXTERNAL_RECORD`, it returns the frozen normalized record, field lineage
and original source-file hash/reference. It does not fetch or reconstruct an
original API response. If the same content-derived record occurs in several
selected input observations, `source_observations` retains every matching
record/run/document ID in deterministic order.

Existing posting claims, positions, mappings and their evidence IDs retain their
current meanings. For a claim's text span, continue using
`ontology.query_evidence_v1(release_id, evidence_id, preview)` or
`ontology/read_evidence.hwf`, with the same pinned release. Text-span IDs and
source-record support IDs are different types of evidence reference.

## Selection and compatibility

Every v2 call uses the existing published-read gate. A blank release uses only
the active pointer, never the latest draft. No active release means
`NO_ACTIVE_ONTOLOGY_RELEASE`. Explicit draft reads require preview; revoked or
failed releases remain unavailable in preview as well. All source/review reads
share one PostgreSQL statement snapshot.

A selected editorial source is verified against its original bytes, immutable
items, review and membership before returning data. A sealed graph also has its
editorial projection checked. Corrupt pins and revisions fail rather than being
reported as ungrounded definitions. Drafts without an editorial pin remain
readable: `editorial_selection_status=NOT_PINNED`, `editorial_source=null` and
`editorial_coverage=null`. Their source list contains only the six external pins.

`query_summary_v2` appends editorial membership as a seventh source and reports
five selected catalogue entities (four roles plus the scheme). Its external
`source_coverage`, posting counts and `data_as_of` retain their original meanings;
editorial review time does not advance the six-source data watermark. These
counts do not establish a complete editorial library, classified job corpus or
published serving release. Publication issues remain explicit.

V1 functions and Hop workflows are unchanged. V1 entity `source_support` covers
external ingestion records only; consumers needing editorial provenance should
use v2. This change does not convert assistant-authored definitions into human
approval. The initial catalogue still needs real review, and Git references
remain labeled as operator attestations rather than independent repository checks.

Developer validation: `python hop/editorial/tests/read.py` exercises source
import/review/pinning and the native readers in fresh disposable PostgreSQL 18
and Hop 2.19 containers. It uses synthetic reviews and never accesses production
or calls a model. The reported fixture directory retains native logs and an
`editorial-read-report.json`.
