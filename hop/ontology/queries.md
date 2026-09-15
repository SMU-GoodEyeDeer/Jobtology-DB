# Reading a selected ontology release

The `hop-ontology-read-v1` PostgreSQL contracts return source entities and
independently accepted claims from **one explicit release**. They do not run
extraction, change reviews, load a graph or activate a release. The attachment
[hold](../../docs/hop-migration/attachment-status.md) continues to apply.

The local [v2 read contracts](../editorial/queries.md) add frozen editorial
provenance, catalogue source-record reads and filtering by occupation scheme.
They are installed by `editorial/install.hwf` after the ontology installer.
V1 remains unchanged and covers external source support; use v2 for editorial
definitions. The v2 package is not yet deployed to Goldship.

## Published reads and previews

Published reads are the default. A blank/null release choice uses the PostgreSQL
active-release pointer; it never chooses the newest draft. With no active release,
the call fails with `NO_ACTIVE_ONTOLOGY_RELEASE`.

An explicit published read requires ACTIVE or previously activated SUPERSEDED
state, a valid sealed manifest, graph verification, activation provenance and no
publication issues. A revoked release raises `CORPUS_RELEASE_REVOKED`, including
in preview mode. These checks do not implement release activation or rollback;
the existing publication gate remains closed while those requirements are open.

Use `preview=true` in SQL or `PREVIEW=Y` in Hop to inspect an existing draft. Every
response identifies `read_mode=PREVIEW`; this does not certify a complete or
fresh serving corpus. The functions use one PostgreSQL statement snapshot.
For subsequent requests/pages, keep the exact returned `release_id`, rather than
resolving a possibly changed active pointer again.

These are database contracts, not HTTP endpoints or a new database authorization
boundary. They expose corpus data only; private application Person/profile data
is outside the ontology entity kinds and these query paths. Future backend
repositories should bind parameters and apply their authentication separately.

## Native Hop entry points

Install the updated `ontology/install.hwf`, then use **ontology-local**:

| Workflow / matching preview pipeline | Additional parameters | Result |
|---|---|---|
| `read_summary.hwf` / `.hpl` | None | Source pins, factual counts, posting review outcomes and publication issues. |
| `read_entities.hwf` / `.hpl` | `ENTITY_KIND`, `PAGE_SIZE`, `CURSOR` | Stable entity/revision IDs and names, with a next-page cursor. |
| `read_entity.hwf` / `.hpl` | `ENTITY_ID` | Selected source revision, supported relations and, for postings, reviewed claims and decisions. |
| `read_evidence.hwf` / `.hpl` | `EVIDENCE_ID` | Exact excerpt/offsets, source observation lineage and any previously selected document locator. |

All four accept `RELEASE_ID` and `PREVIEW` (default `N`). For the existing draft,
set `RELEASE_ID=ontology-20260912-initial` and `PREVIEW=Y`. Open the matching `.hpl`
and preview **Preview JSON here** to read `result_json`; Basic logging does not
print the source JSON. `PAGE_SIZE` is 1–100 (default 100). Blank `ENTITY_KIND`
lists all supported corpus kinds. An empty `ENTITY_ID` or `EVIDENCE_ID` does not
select an arbitrary object.

The live initial release has not selected its production reviews. Empty claim
arrays there are expected; they do not imply that source postings have no
requirements. These read workflows never create that missing selection.

## SQL examples

Inspect counts without inferring semantic completeness:

```sql
SELECT jsonb_pretty(ontology.query_summary_v1('ontology-20260912-initial', true));
```

List five posting identities, retaining the release and cursor from the response:

```sql
SELECT ontology.query_entities_v1(
  'ontology-20260912-initial', 'jobPosting', 5, NULL, true
);
-- Next page: pass the exact next_cursor in place of NULL.
```

Read one of those `entity_id` values:

```sql
SELECT jsonb_pretty(ontology.query_entity_v1(
  'ontology-20260912-initial', 'urn:jobtology:jobPosting:job_alio:304817', true
));
```

The posting must belong to the selected release; otherwise the function returns
`ONTOLOGY_ENTITY_NOT_IN_RELEASE`. For a release that has assembled accepted
claims, use their evidence IDs with `ontology.query_evidence_v1(release_id,
evidence_id, true)`. An evidence ID from another release or a rejected claim
raises `ONTOLOGY_EVIDENCE_NOT_IN_RELEASE`.

Once a published release actually exists, omit preview or pass false:

```sql
SELECT ontology.query_summary_v1(); -- Active pointer; currently fails if none exists.
```

## Response meaning

Every response includes contract version, release ID/state, read mode, manifest
hash, source `data_as_of`, pipeline/methodology versions, review-freeze time and
graph-verification time. Times are timestamps with offsets; a date-only value in
a source payload remains a date string. The data watermark is not an assertion
that the source is fresh enough for a new analysis.

Entity names and related entity names come from `release_revision`, never the
latest global revision. Stable identities and immutable revision IDs are separate.
Source relations retain their qualifiers, assertion kind, acceptance policy and
supporting record/field references. For example, a qualification curriculum
reference is not silently promoted into an `ATTESTS` capability claim.

Posting details include:

- `extraction`: the frozen outcome, exact extraction revision/decision, reviewer,
  issues, duty status and selected input scope. `SELECTION_PENDING`/`UNSELECTED`
  means reviews have not been frozen; it is distinct from `NOT_PROCESSED`.
- `positions`, `claims`, `mappings`, `rules`: release-selected accepted content.
  Claim scope, source fragments, ordered AND/OR/exception children, inference kind
  and separately reviewed rule effects remain explicit.
- `link_decisions`, `rule_decisions`: rejected, pending, mismatched and accepted
  decisions remain distinguishable. Empty mappings do **not** establish a
  reviewed no-match outcome or completed categorization.
- Evidence references: call the evidence query for the exact half-open Unicode
  code-point span, excerpt/hash, normalized-text hash, source run/record/locator,
  source URL and retrieval time. Private disk paths and API credentials are not
  projected. Previously selected document locators can be read without parsing
  or reconstructing an attachment.

`SOURCE_TEXT`/`SOURCE_EXPRESSION` are reviewed source interpretations. They do not
establish typed skill/credential resolution or executable applicant eligibility.
The read layer does not convert an unresolved phrase into a normalized condition.

Summary review fractions use **distinct release-selected postings** as their
denominator, including rejected, pending and unprocessed records. The fraction
is null for an empty release. These are operational review-completion counts,
not capability coverage, occupational demand or a model accuracy score.
The design's occupation cohorts, minimum-denominator rules, canonical requirement
keys, aggregate support and calculation traces remain separate implementation work.

Entity pages use the stable entity ID in C collation order. The opaque cursor
binds the release, entity-kind filter and complete selected identity/revision
set. A changed draft selection, another release/filter, malformed cursor or
oversized cursor raises `INVALID_ONTOLOGY_CURSOR`. The cursor is pagination state,
not an authentication token. Its final page has `next_cursor=null`.

## Verification

Run `python hop/ontology/tests/query_contracts.py`. It creates uniquely named
disposable PostgreSQL/Hop containers, seeds synthetic inline-source and review
fixtures, and removes only those containers. Existing retained fixtures and live
databases are not reset. No provider, attachment-fetch or parser workflow runs.

Checks cover all six sources, every posting outcome, exact entity pagination,
cursor isolation, old/new source names and employers, independent link versus
extraction rejection, NCS snapshot selection, Korean/emoji evidence offsets,
zero-denominator nulls, default/preview/revoked-read gates and all four native
read workflows. A rolled-back local fixture simulates an active release solely
to test pointer reads; it is not a serving-activation test or a production release.

See the [completion ledger](../../docs/hop-migration/ontology-completion.md) for
the exact tested package, deployment receipt and live readback. JSON-LD/SHACL,
typed condition resolution, cohorts/aggregates and release lifecycle integration
remain open until their own evidence establishes completion.

Deployed on Goldship on 2026-09-13 KST. The live native summary/list/detail check
accounted for all 513 postings in `ontology-20260912-initial`, with reviews still
`SELECTION_PENDING`. Published reads correctly rejected that draft. No production
acceptance, model call or attachment processing was performed.
