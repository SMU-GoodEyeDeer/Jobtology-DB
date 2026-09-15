# Assign a posting's primary product occupation

**Passed local native verification on 2026-09-13 KST; not deployed to Goldship.**
This is the PostgreSQL decision and review stage. The subsequent
[graph/export adapter](occupation-graph.md) also passed local native tests.
Confidence calibration and production assignments remain unfinished. The four
catalogue definitions still require real independent review. Attachment processing
remains [on hold](../../docs/hop-migration/attachment-status.md).

The product catalogue contains AI engineer, backend developer, frontend developer
and data analyst. These IDs are separate from NCS occupations and competency units.
A posting can receive one primary product occupation per frozen release, with the
decision's original Korean duty evidence and exact catalogue version. Imported
source posting revisions remain immutable. Decisions are stored in separate
`ontology.occupation_*` tables.

For this stage, read the assignment from `primary_product_occupation` or the
occupation reader below. The source revision's `primary_occupation_id` and the
existing v1/v2 entity readers are not rewritten to contain an inferred role.

## Prepare and inspect the real input

Install `editorial/install.hwf` after `ontology/install.hwf`, using the existing
`jobtology-postgres` connection and `ontology-local` run configuration. Import,
independently review and pin the catalogue as described in the [source guide](README.md).
Run `ontology/assemble_reviewed.hwf` on the same unsealed PREPARING release before
proposing occupations. This freezes extraction decisions and assembles their
positions, duties and exact source spans. Installation does not create assignments.

Run `editorial/read_occupation_input.hwf` with `RELEASE_ID`, `ENTITY_ID` (the exact
posting identity) and `PREVIEW=Y`. In Hop Web, open its `.hpl`, set the same
parameters, and preview **Preview JSON here**. The single `result_json` contains:

- `source_binding`: selected posting revision, extraction/review IDs, input scope,
  all reviewed duties and positions, and their exact evidence spans and hashes.
- `source_binding_hash`: copy this without recalculating it outside PostgreSQL.
- `catalogue_binding`: the pinned snapshot plus all four role definitions and the
  scheme definition. Compare the whole catalogue, including boundary notes.
- `current_proposal` and `current_decision`: the latest proposal/review as of the
  read. These are explicitly current state, even when inspecting an older release.
- `proposal_template`: the JSON object to save and complete for import. Empty
  author, resolver and rationale fields must be filled before it is valid.

Equivalent SQL, for an exact existing release and posting:

```sql
SELECT ontology.query_occupation_input_v1(
  '<release_id>', 'urn:jobtology:jobPosting:job_alio:<posting_id>', true
);
```

This reader uses saved evidence only. It does not download attachments, reconstruct
inputs or call a model. Missing or unaccepted extraction remains an explicit
outcome; a plausible title does not supply missing duty evidence.

## Propose and independently review

Save only `proposal_template` as a UTF-8 JSON file under a managed project data
directory, for example `${PROJECT_HOME}/data/reviews/occupation-<posting_id>.json`.
The complete [proposal schema](schemas/product-occupation-proposal-v1.schema.json)
requires every field and rejects unknown fields, including confidence scores.

| Field | What to supply |
|---|---|
| `actor`, `actor_kind` | Actual author identity and `human` or `assistant`. |
| `method` | `MANUAL` for a human decision, or `MODEL_INFERRED` for an assistant/model proposal. |
| `model_id`, `prompt_version` | Null for MANUAL; actual nonempty identifiers for MODEL_INFERRED. Imported identifiers are operator-supplied provenance, not proof of an API call. |
| `resolver_version`, `reason` | Version of the classification procedure and rationale comparing duties with catalogue definitions. |
| `disposition` | `MATCH`, `OUT_OF_SCOPE` or `UNRESOLVED`. |
| `occupation_id` | Exact pinned product occupation ID for MATCH; otherwise null. |
| `unresolved_reason` | For UNRESOLVED: `EXTRACTION_NOT_ACCEPTED`, `NO_REVIEWED_DUTIES`, `MIXED_ROLES`, `AMBIGUOUS_DUTIES` or `INSUFFICIENT_EVIDENCE`; otherwise null. |
| `considered_duty_ids`, `considered_position_ids` | Every ID supplied in the template. Review all of them; omissions, additions and duplicates fail. |
| `evidence_ids` | Exact evidence IDs from this input. MATCH and OUT_OF_SCOPE require at least one duty span, plus accepted extraction with explicit duties. |
| `parent_id` | Latest proposal ID from the template, or null for the first. A stale parent fails. |

For a posting covering unrelated roles, use UNRESOLVED with `MIXED_ROLES` until a
reviewed interpretation supports one primary occupation. OUT_OF_SCOPE is a
reviewed finding that the duties do not fit the four product roles. It is not a
fallback when evidence is missing, and it does not silently remove a source record
or declare that record publication-ready.

Run `editorial/import_occupation.hwf` with `PROPOSAL_FILE` set to the full container
path. Hop reads the original bytes; PostgreSQL rejects malformed/duplicate-key
JSON, stale bindings, invalid targets and mismatched method provenance in one
transaction. The import logs `proposal_id`. An identical import reuses that ID.

Then run `editorial/review_occupation.hwf`:

- `REVIEW_ID`: a new UUID; reuse only to retry the identical decision.
- `PROPOSAL_ID`: the returned proposal ID.
- `DECISION`: ACCEPT or REJECT; the default is REJECT.
- `REVIEWER`, `REVIEWER_KIND`, `NOTES`: the actual independent reviewer, human or
  assistant, and evidence-based rationale. Author self-review fails.

A changed decision needs a new review UUID. Reusing a UUID with different fields
fails. A superseded proposal cannot receive a new review. Assistant acceptance is
labelled `ASSISTANT_REVIEWED`; human acceptance is `HUMAN_ACCEPTED`. Both retain
null confidence and `UNASSESSED` calibration state. This workflow does not invoke
OpenRouter, automatically approve a proposal or turn a model score into confidence.

## Freeze and compare

Before freezing, `editorial/read_occupations.hwf` with `RELEASE_ID` and `PREVIEW=Y`
returns `selection_status=NOT_FROZEN` and `current_candidates`, one outcome per
selected posting. Resolve or explicitly account for every outcome before deciding
which draft to freeze.

Run `editorial/freeze_occupations.hwf` with that exact `RELEASE_ID`. It stores the
proposal/review cutoffs, one selection per posting, and the manifest hashes. An
identical rerun verifies the existing selection without changing it. Use a new
release to incorporate later proposals or reviews.

The reader then returns `FROZEN`, the preserved membership and the posting rows.
Only `MATCHED` rows have `primary_product_occupation`; the view is also available
for joins:

```sql
SELECT entity_id, occupation_id, occupation_revision_id,
       proposal_id, decision_id, review_state, confidence, confidence_state
FROM ontology.primary_product_occupation
WHERE release_id = '<release_id>'
ORDER BY entity_id;
```

Outcomes are `MATCHED`, `OUT_OF_SCOPE`, `UNRESOLVED`, `NOT_PROPOSED`, `PENDING`,
`REJECTED`, `EXTRACTION_NOT_ACCEPTED`, `SOURCE_CHANGED` and `CATALOGUE_CHANGED`.
The newest pending/rejected proposal prevents fallback to an older acceptance.
A changed extraction decision invalidates reuse even if source bytes are identical.
A changed catalogue invalidates prior exclusions as well as matches. The original
release's selected decision and names remain intact.

After installing the [graph/interchange adapter](occupation-graph.md), use
`ontology/load_release.hwf` and `editorial/export_jsonld_v5.hwf` to project this
frozen selection. An older/incomplete graph adapter that omits occupation membership
still fails with `OCCUPATION_GRAPH_INTEGRATION_REQUIRED`. Drafts without this new
freeze retain their prior graph behavior. This guard keeps PostgreSQL and the graph
from silently describing different reviewed facts. Loading a graph does not satisfy
the remaining production [completion requirements](../../docs/hop-migration/ontology-completion.md).

## Local verification

Run `python hop/editorial/tests/occupations.py`. It allocates uniquely named local
PostgreSQL 18 and Hop 2.19 containers and removes those containers afterward.
Fixtures use eight synthetic Korean postings, all four product roles, nursing
outside the product catalogue, absent duties, an unaccepted extraction and mixed
positions. Tests cover native import/review/read/freeze, duplicate retries,
independent review, stale parents, source/catalogue changes, preserved history,
immutable evidence and rejection of incomplete manifests. Synthetic catalogue approvals are
fixture data and are never copied to production.

The final run completed with exit 0. Evidence:
`/tmp/jobtology-occupation-final.log` and
`/tmp/jobtology-ontology-native-3fqsrph3/occupation-report.json`, alongside the
native workflow logs and exact staged runtime files. All eight postings have an
explicit frozen outcome: four MATCHED, one OUT_OF_SCOPE, one
EXTRACTION_NOT_ACCEPTED and two UNRESOLVED. Later pending/rejected decisions,
changed extraction reviews/duties and a new catalogue produced the expected
outcomes only in new releases. No provider requests or production writes occurred.
