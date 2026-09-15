# Reading reviewed occupations and normalized requirements

**Native PostgreSQL/Hop tests passed locally; not deployed to Goldship.**
These PostgreSQL functions and native Hop workflows expose derived claims selected
by an ontology release. They do not run extraction, make review decisions or
publish a release. Attachment processing remains [on hold](../../docs/hop-migration/attachment-status.md).

The [v2 readers](queries.md) return source revisions, source claims and editorial
definitions. V3 adds reviewed primary product occupations and normalized
requirements without changing the source payload or the v1/v2 contracts. A
future application can use these functions directly through its database layer;
there is no new HTTP service or backend in this change.

## Native Hop entry points

Install `editorial/install.hwf` **after** `ontology/install.hwf`. The editorial
installer adds `sql/014_derived_reads.sql` after its occupation and graph modules.
Keep using the existing `jobtology-postgres` connection and `ontology-local` run
configuration. Paths below are relative to `${PROJECT_HOME}/editorial/`.

| Workflow and matching `.hpl` | Additional parameters | Result |
|---|---|---|
| `read_summary_v3.hwf` | None | Source/review summary, derived claim counts, frozen membership status and unresolved outcomes. |
| `read_entity_v3.hwf` | `ENTITY_ID` | Existing source details plus selected primary occupation and the first page of derived claim summaries. |
| `read_derived_claims_v1.hwf` | `ENTITY_ID`, `CLAIM_KIND`, `PAGE_SIZE`, `CURSOR` | Paginated derived claim summaries for the whole release or one subject posting. |
| `read_derived_claim_v1.hwf` | `CLAIM_ID` | One selected derived claim with its full proposal, review, bound source, target revisions and evidence. |

Every entry point also takes `RELEASE_ID` and `PREVIEW` (default `N`). Use an exact
draft ID and `PREVIEW=Y` while inspecting unfinished work. Open the matching
pipeline and preview **Preview JSON here** to inspect `result_json`. Basic logs
do not print the full evidence document.

Blank `RELEASE_ID` resolves only the active published release. It does not choose
the newest draft. Without an active release the call fails; failed and revoked
releases remain unavailable even in preview. Reads share one PostgreSQL statement
snapshot and never change release state.

## Inspect one posting

```sql
SELECT jsonb_pretty(ontology.query_entity_v3(
  '<release-id>',
  'urn:jobtology:jobPosting:job_alio:<posting-id>',
  true
));
```

The existing `entity`, `source_support`, `claims`, `positions`, `mappings`,
`rules` and other v2 fields retain their contents. In particular,
`entity.payload` is still the source revision, not a mixture of source and model
outputs. The additional fields are:

- `primary_occupation`: the accepted frozen product-role assignment, with its
  claim ID, selected occupation ID/revision, Korean name, review status and
  method. This is separate from an NCS duty mapping. Null means there is no
  selected accepted product assignment in this release.
- `occupation_selection`: the frozen decision outcome, including pending,
  rejected, source/catalogue changed, unresolved or out-of-scope outcomes.
  Inspect it before interpreting a null assignment as absence of a relevant role.
- `derived_claims`: up to 100 claim summaries, the total and `next_cursor`.
  Use the paginated reader if a cursor is present.
- `requirement_outcomes`: counts of frozen normalization outcomes for this
  posting, including atoms that were not proposed or not accepted.
- `derived_memberships`: separate requirement and occupation freeze status,
  membership hashes and exact selection cutoffs. `NOT_FROZEN` means this stage
  has not selected results; it is different from a frozen stage with zero
  accepted claims. Requirements can be read without an editorial occupation pin.

The accepted claim types are `NORMALIZED_REQUIREMENT` and `PRIMARY_OCCUPATION`.
Only frozen `REVIEWED` requirements and `MATCHED` occupations enter this list.
An accepted decision that has not been frozen into this release is not returned.
Later global proposals and reviews do not replace an older release's selection.

## Follow a claim to its evidence

Pass a returned `claim_id`, not a raw source claim ID or a Neo4j internal ID:

```sql
SELECT jsonb_pretty(ontology.query_derived_claim_v1(
  '<release-id>', '<derived-claim-id>', true
));
```

For a normalized requirement, the result includes the exact typed `condition`,
requirement key and algorithm, necessity, polarity, source atom index,
normalization proposal and independent decision. `source_binding` retains the
original requirement group, position IDs and complete expression nodes/edges.
These retain AND/OR, exceptions and conditions: two accepted atoms from an OR
group do not become two mandatory requirements. Normalization is not an
executable applicant-eligibility decision.

For an occupation, the result includes the complete proposal and decision,
reviewed duties/positions, cited source evidence and the full catalogue binding
used for that decision. Model and prompt identifiers appear as recorded in the
proposal; manual decisions do not acquire invented model provenance.

Both kinds include:

- `targets`: exact release-selected target revisions, payload hashes, names and
  payloads, with available v2 source-support references. A numeric experience
  condition can legitimately have no canonical target reference.
- `evidence`: the existing `query_evidence_v1` result for every selected span,
  including exact excerpt/offsets, text artifact hash, source record lineage and
  any already stored document binding. Reading evidence does not fetch or parse
  a file. The nested evidence result keeps its v1 contract version.
- `review_status`: `HUMAN_ACCEPTED` or `ASSISTANT_REVIEWED`, according to the
  actual selected reviewer. `confidence` remains null and
  `confidence_state=UNASSESSED`; approval does not invent a calibrated score.
- `graph_node_id`: the stable `typed-requirement/<claim-id>` or
  `primary-occupation/<claim-id>` used by the graph projection. It may not yet
  exist in Neo4j if that draft has not been loaded.

Use `read_source_record_v2.hwf` for a target's returned `support_id`. Missing,
unselected, rejected or stale derived claim IDs fail with
`ONTOLOGY_DERIVED_CLAIM_NOT_IN_RELEASE`.

## Read all selected claims

```sql
SELECT ontology.query_derived_claims_v1(
  '<release-id>',
  NULL, -- optional subject posting identity
  NULL, -- or NORMALIZED_REQUIREMENT / PRIMARY_OCCUPATION
  100,
  NULL, -- returned next_cursor on later pages
  true
);
```

`ENTITY_ID` filters the subject, not an incoming occupation target. A selected
reference entity with no derived subject claims returns an empty list; an entity
absent from the release fails explicitly. `PAGE_SIZE` must be 1–100.

Keep the exact returned release ID, filters and cursor for subsequent pages.
Ordering is by stable claim ID, with no OFFSET or duplicate rows across pages.
The cursor binds both frozen memberships and the selected result set. A new
freeze, different release/filter, malformed cursor or cursor from another reader
fails with `INVALID_ONTOLOGY_CURSOR`. Unrelated later reviews do not alter a
frozen release's results.

Summary counts describe selected reviewed interpretations. They do not establish
extraction accuracy, complete posting coverage, calibrated confidence,
occupational demand or publication readiness. Existing publication issues remain
visible; serving activation remains a separate unfinished stage.

## Developer validation

Run each fixture separately so it owns its disposable PostgreSQL/Hop containers:

```sh
python hop/editorial/tests/derived_reads.py occupations
python hop/editorial/tests/derived_reads.py requirements
```

These use synthetic inline Korean sources and reviews. They test native prepared
queries, selected target revisions, exact evidence, source payload compatibility,
AND/OR structure, stale and unresolved selections, pagination/read gates and
ledger fingerprints. No live server, attachment operation or provider request is
part of either test. Fixture directories retain native logs and
`derived-read-report.json`.

The combined fixture passed with four primary occupations and one normalized
requirement, including both claim kinds on one posting. The separate requirement
fixture passed with two selected normalizations, nested AND/OR evidence and no
editorial pin. Each exercised all four native readers and preserved fingerprints
of 115 source, review, provider, attachment, release and graph tables. See the
[completion ledger](../../docs/hop-migration/ontology-completion.md#derived-claim-database-reads--2026-09-13-kst)
for exact fixture paths and deployment status.
