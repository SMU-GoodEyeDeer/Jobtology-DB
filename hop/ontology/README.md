# Native Hop ontology assembly

This is the canonical assembly after source ingestion and independent LLM review.
It uses native Hop SQL actions/transforms and PostgreSQL functions. Python files
generate artifacts and run disposable tests; they are not runtime ETL steps.

**The implemented workflows produce a PREPARING release.** The native Neo4j
candidate loader has passed the full saved-data fixture; serving activation/rollback,
resolved eligibility conditions, aggregate contracts and full publication
integration remain work in the [completion ledger](../../docs/hop-migration/ontology-completion.md).
Successful assembly does not make the database a complete serving ontology.

The [versioned read contracts](queries.md) provide summary, paginated entity,
posting/relationship and evidence queries. They pin one release and require an
explicit preview for drafts; no active release is selected implicitly from the
latest ingestion. Attachment processing remains [on hold by user](../../docs/hop-migration/attachment-status.md).

The [interchange guide](../../ontology/README.md) covers `export_jsonld.hwf`, the
versioned Schema.org/Jobtology vocabulary and independent RDF/SHACL validation.
Exports require a sealed inventory; a structurally valid preview does not certify
publication readiness or complete extraction.

The [observation guide](observations.md) covers complete posting censuses,
release-frozen closure/expiry/absence states and source freshness reads.
`bind_observations.hwf` retains missing postings' exact historical revisions and
evidence before review selection; Neo4j and JSON-LD v2 include the bound states.

The [cohort preparation guide](../cohorts/README.md) covers reviewed duplicate
groups that preserve every source posting and freeze membership by release.
The [country/experience profile guide](../cohorts/profiles.md) adds evidence-backed
position scope and independently reviewed month bounds. These stages are local;
deployment, production assessments, representative selection, actual cohorts/
aggregates and their graph integration remain open.

The [typed requirement guide](requirements.md) covers the next PostgreSQL stage:
normalization proposals, nine condition kinds, stable cross-posting keys,
separate reviews and frozen per-atom outcomes. Its native workflows preserve the
source expressions and evidence. The [typed graph/export guide](requirement-graph.md)
covers the Neo4j projection and JSON-LD v3, including release-specific outcomes
and direct posting-to-typed-requirement links. Confidence calibration and full
publication integration remain unfinished.

The [editorial catalogue guide](../editorial/README.md) covers the four stable
product occupation IDs, exact-file import, independent review and PostgreSQL
release pinning. The editorial adapter and JSON-LD v4 exporter passed local native
tests; deployment and real catalogue review are still pending. Install the editorial
adapter after the ontology installer to include that source in graph releases.

The [product occupation graph guide](../editorial/occupation-graph.md) covers
reviewed primary occupation claims, their exact duty/catalogue bindings, generated
`FOR_OCCUPATION` edges and JSON-LD v5. It passed local native integration tests;
deployment, real assignments and confidence calibration remain pending.
The [v2 database readers](../editorial/queries.md) expose its frozen source and
review evidence alongside external source records, with scheme-scoped role lists.

## Run in Hop

Use the existing `jobtology-postgres` connection and the **`ontology-local`** run
configuration. Install source, operations, retention, LLM and attachment SQL first.

1. Run **`ontology/install.hwf`**. This adds the ontology schema and updates the
   retention protection function before any source snapshot is pinned. It does
   not replace private metadata, accept model output, or make model calls.
2. Run **`ontology/prepare_release.hwf`**. Leave `RELEASE_ID` blank for a UUID, or
   provide a new meaningful ID. The log reports the selected ID. Each source-run
   parameter defaults to `LATEST`; use exact run IDs for a reproducible selection.
   To accompany an enrichment batch, explicitly use its `JOB_RUN_ID` and
   `NCS_RUN_ID`. The other parameters are `ALIO_RUN_ID`, `QUALIFICATION_RUN_ID`,
   `QNET_RUN_ID`, and `CAREER_RUN_ID`.
3. Run **`ontology/bind_observations.hwf`** on the newly prepared release to retain
   historical postings and bind their observation states at release creation time.
   Then complete the [independent extraction and link decisions](../llm/README.md#independent-reviews-and-corrections).
   An extraction requires its own acceptance. Each NCS candidate also requires
   acceptance; rejection of a candidate does not discard the extraction.
   Attachment processing is currently on hold. After explicit resumption,
   attachment-aware releases can use **`ontology/bind_document_inputs.hwf`**
   before step 4, with the same `RELEASE_ID` and `INPUT_BUNDLE_IDS` returned by
   attachment input preparation. Supply one immutable input bundle for **every**
   posting in the pinned JOB snapshot, separated by `|`. Historical attachment
   bundle selection across different JOB runs still needs integration; do not use
   this old binder for a release with historical postings. Partial sets, duplicate
   postings and bundles from another JOB snapshot are rejected. No model call or
   acceptance decision is made by this workflow.
4. Run **`ontology/assemble_reviewed.hwf`** with that exact `RELEASE_ID` when the
   decisions intended for the release are ready. It freezes review selection,
   assembles claims and evidence, and verifies the projection.
5. Preview **`ontology/inspect_release.hpl`** and **`ontology/inspect_claims.hpl`**
   with `RELEASE_ID` to inspect source entities and per-posting outcomes.

Source selection is immutable. Repeating preparation with the same ID resumes
the same inputs; `LATEST` does not repin it. An explicit different run is rejected.
Review selection is also immutable once step 4 starts. Later corrections or
decisions need a new release. Repeating step 4 reproduces the frozen selection.
Do not freeze production reviews merely to monitor an ongoing enrichment batch;
use `llm/inspect_independent_reviews.hpl` or the batch reports instead.

Document input selection also freezes on first binding. Repeating the same set
is safe; choosing different bundles requires a new release. A release without
document selection uses the historical inline input contract. It cannot select
an attachment-aware extraction merely because its posting ID matches. Accepted
extraction reuse requires identical full input content; the new release records
its own exact document-attempt lineage even when identical text was cached.

Use `ontology.document_input_set` and `ontology.document_input` to inspect the
chosen bundles. Do not bind or freeze the live initial release merely to inspect
ongoing extraction experiments; later document repairs may produce new inputs.

Attachment evidence retains the original bytes and parser lineage in PostgreSQL.
In the graph, `textArtifact -DERIVED_FROM-> sourceAttachment -DECLARED_IN->
sourceRecordEvidence` identifies the official source response that declared the
file. `evidenceSpan -OVERLAPS_SECTION-> documentSection` uses normalized offsets;
each section also carries its original offsets and content hash. The relationship
means an overlap, so a fragment crossing a page boundary can reference both pages.
For HWPX, `documentTable`, `documentCell`, `IN_CELL` and `NESTED_IN_CELL` preserve
table membership, header flags, row/column spans and nesting. Document observations
such as unreviewed embedded images remain visible. These paths do not establish
that images were read or that an extraction is semantically correct.

The existing `llm/publish_reviewed.hwf` still reads the legacy whole-item reviews.
It does not publish these independently selected ontology claims.

## Load the ontology graph candidate

`ontology/load_release.hwf` is the new release-scoped graph loader. Its deployment
and verification state is recorded in the [completion ledger](../../docs/hop-migration/ontology-completion.md).
Use `ontology-local`, the exact `RELEASE_ID` from reviewed assembly, and the existing
private `jobtology-neo4j` connection (or `NEO4J_CONNECTION` override).

Starting this workflow **seals the graph inventory and review selection**. Do not
run it on the live initial release while its intended reviews remain unfinished.
After sealing, different inputs or review decisions require a new release ID.

The workflow:

1. Seals node/relationship inventories and their manifest in PostgreSQL, records
   the destination database UUID, and registers one writer for that database.
2. Checks the `ontologyObject(id)` uniqueness constraint and creates a graph
   `corpusRelease` root. Existing source-ingestion graphs stay separate.
3. Loads typed nodes, relationships, scalar properties and ordered primitive
   arrays. Native [Table Input](https://hop.apache.org/manual/latest/pipeline/transforms/tableinput.html)
   uses prepared parameters and streaming reads;
   native Neo4j Cypher sends batches of 500 rows with `UNWIND`.
4. Checks every expected value, exact labels, property counts, endpoints,
   release ownership and membership totals before recording `VERIFIED`.

This needs neither APOC nor a Python/JavaScript ETL step. The native Cypher uses
dynamic labels and relationship types supported by Neo4j 5.26 and newer.

`VERIFIED` is a graph-load checkpoint. The PostgreSQL release remains `PREPARING`;
it is not made active or eligible for serving while the remaining ontology
contracts are unfinished. Read its state with:

```sql
SELECT release_id, state, manifest_hash, graph_verified_at
FROM ontology.corpus_release WHERE release_id = '<release-id>';
SELECT load_id, database_id, state, started_at, finished_at, error
FROM ontology.graph_load WHERE release_id = '<release-id>' ORDER BY started_at;
```

All graph relationships carry `release_id`. Identity shells are shared; names,
dates and other source-changing facts live on the selected revision. Queries
must select a release and filter every traversed relationship by that ID. For
example, accepted posting requirements and their exact excerpts:

```cypher
MATCH (:corpusRelease {release_id: $release_id})
      -[:INCLUDES {release_id: $release_id}]->(p:jobPostingRevision)
MATCH (p)-[:HAS_REQUIREMENT {release_id: $release_id}]->(c:requirementClaim)
MATCH (c)-[:EVIDENCED_BY {release_id: $release_id}]->(e:evidenceSpan)
RETURN p.posting_id, p.name, c.text, c.condition_kind, c.logic, e.excerpt
```

Neo4j properties retain booleans, integers, floating-point numbers, date-only
values, timestamps, empty strings and ordered primitive arrays. Nested source
maps use dotted property names; literal `~` and `.` inside a source key are
escaped as `~0` and `~2`. For example, `dates.docRegEndDt` is a date property,
while `field_lineage.dates~2docRegEndDt` identifies the original flat lineage key.
Unsupported object arrays and numbers that cannot be represented faithfully
fail sealing. The original payload remains in PostgreSQL.

Repeating a load reuses the sealed inventory. A conflicting existing value
fails verification and is not silently overwritten. Caught workflow failures
record `FAILED` and release the retention writer; partial graph objects remain
available for an idempotent retry. Starting a reload clears the prior graph
verification checkpoint until the full new check passes; an earlier success
cannot certify a failed reload. After a killed/disconnected executor, verify
that the actual Hop process has stopped before clearing its exact writer with
`ontology.fail_graph_load('<load-id>')`. A timeout alone does not prove it stopped.

## Source identities and relationships

All six selected sources contribute normalized records with source run, document,
locator, original field lineage and raw SHA-256. The release uses the minimum of
their selected-response watermarks as `data_as_of`.

- ALIO organization codes identify organizations. Equal names do not merge codes.
- JOB-ALIO list/detail records produce one posting; a non-null detail value wins.
  Its employer relationship follows the merged organization code.
- NCS competency IDs retain the complete versioned code. An unversioned career
  reference points to an `ncsUnitFamily`, not an arbitrarily chosen competency
  version. Classification edition IDs describe the observed classification set;
  they are not invented official taxonomy version numbers.
- Qualification associations use `CURRICULUM_REFERENCES`, preserving unit type,
  standard version and training-hour qualifiers. They do not establish `ATTESTS`.
- Q-Net sessions retain qualification, year, category, round and date fields.
  Date-only source values remain date-only values.

`ontology.entity` holds stable identities. `ontology.revision` holds immutable
source content, names and aliases; `release_revision` selects one revision per
entity. Source relations and their supporting records have separate memberships.
Hash IDs use the documented `hop-ontology-jsonb-v1` PostgreSQL serialization; they
are opaque IDs, **not RFC 8785 JCS hashes**.

## Reviewed claims and evidence

`posting_selection` accounts for every pinned posting, including `NOT_PROCESSED`,
`PROCESSING`, `PROCESSING_FAILED`, `REVIEW_REQUIRED`, `REJECTED` and `ACCEPTED`.
Validated model output alone is `REVIEW_REQUIRED`. EVAL output cannot supply a
production selection. The latest content-matching extraction revision is selected;
a pending/rejected correction cannot fall back to its accepted predecessor.

Accepted selections produce:

| Tables | Meaning |
|---|---|
| `position_claim`, `release_position` | Source-supported position names within the selected posting revision. |
| `claim`, `release_claim` | Separately queryable duties and requirements, retaining category, condition kind, logic and applicability. |
| `claim_position` | Explicit position references. Empty references are not silently applied to every position. |
| `condition_node`, `condition_child` | Ordered `all_of`, `any_of`, `if_then`, `except` and atom structures. Child order preserves conditional roles. |
| `text_artifact`, `artifact_source` | NFC/LF text by source field, input/text hashes, and links back to pinned source records. |
| `document_input_set`, `document_input` | Complete, immutable posting-to-input selection for an attachment-aware release. |
| `artifact_document`, `document_section` | Exact input/attempt/source-response binding and original/normalized page or HWPX block offsets. |
| `evidence_span` and evidence joins | Exact fragments with zero-based, half-open Unicode code-point offsets and excerpt hashes. |
| `link_selection`, `mapping_claim`, `release_mapping` | Frozen per-link decisions and accepted duty-to-versioned-NCS mappings with target revision and review provenance. |

Fragment matching collapses whitespace for matching only. Stored excerpts retain
the artifact's actual whitespace. Matching is restricted to the cited passage
range; repeated text elsewhere in a document does not determine the offset.
Shared suffixes remain separate evidence fragments. NFC composition and CRLF
normalization are handled before reporting offsets. Unsupported fragments fail
assembly instead of acquiring fabricated evidence.

Source expression trees are not yet executable applicant-eligibility rules.
`interpretation_state=SOURCE_TEXT|SOURCE_EXPRESSION` explicitly identifies that
remaining normalization work. Likewise, `unresolved_positions` education metadata
does not establish a condition for any specific position. NCS mappings are marked
`MODEL_INFERRED` or `REVIEWER_INFERRED`, never source facts. No confidence score is
invented when the review did not supply one.

The selected NCS run belongs to the release. A newer current NCS run does not
silently change an old release's links; a new release using that newer snapshot
excludes old candidates with `NCS_SNAPSHOT_MISMATCH` until reviewed replacements
exist. Extraction can still be reused when its source content matches.

## Explicit condition effects

After independently reviewing a
[guarded rule interpretation](../llm/README.md#explicit-interpretation-of-conditional-requirements),
the existing `assemble_reviewed.hwf` also freezes its decision and builds its
evidence. Both the extraction and interpretation must be accepted. A new pending
interpretation suppresses the older accepted interpretation in a new release;
later decisions leave an already frozen release unchanged. Historical releases
frozen before this feature retain their existing manifests and do not acquire
interpretations retrospectively.

PostgreSQL stores the immutable document and review in `ontology.rule_selection`.
`ontology.guarded_rule`, `rule_predicate`, and `rule_part` expose each action,
condition operator, ordered child path, source fragment and target rule as rows.
`rule_evidence` links those rows to exact source spans. The original requirement
claim retains its position scope and extractor expression.

Neo4j contains `guardedRule`, `rulePredicate`, `ruleReviewSelection` and
`ruleContract` nodes. `HAS_RULE`, `GUARDED_BY`, `HAS_CHILD`, `DISABLES`, `LIMITS`,
`USES_CONTRACT`, `REVIEWED_BY` and `EVIDENCED_BY` carry the release ID like all
other ontology relationships. For example:

```cypher
MATCH (:corpusRelease {release_id: $release_id})
      -[:INCLUDES {release_id: $release_id}]->(p:jobPostingRevision)
MATCH (p)-[:HAS_REQUIREMENT {release_id: $release_id}]->(c:requirementClaim)
MATCH (c)-[:HAS_RULE {release_id: $release_id}]->(r:guardedRule)
OPTIONAL MATCH (r)-[:DISABLES {release_id: $release_id}]->(target:guardedRule)
RETURN p.posting_id, c.applicability, r.action, r.name, target.name
```

These rules distinguish source permissions from mandatory conditions and make
bonus exclusions target the bonus explicitly. Predicate observations remain
three-valued in the activation preview. Resolving their source terms into typed
ontology concepts and evaluating complete applicant eligibility remain separate
work; this feature does not open the serving-publication gate.

## Inspection and verification

```sql
SELECT * FROM ontology.source_coverage WHERE release_id = '<release-id>';
SELECT * FROM ontology.posting_coverage WHERE release_id = '<release-id>';
SELECT ontology.verify_claims('<release-id>');

SELECT c.kind, c.text, c.category, c.condition_kind, c.logic, c.applicability,
       e.excerpt, e.start_offset, e.end_offset, a.source_field,
       p.provenance -> 'review' AS review
FROM ontology.release_claim m
JOIN ontology.claim c USING (claim_id)
JOIN ontology.posting_selection p USING (release_id, entity_id)
JOIN ontology.claim_evidence ce USING (claim_id)
JOIN ontology.evidence_span e USING (evidence_id)
JOIN ontology.text_artifact a USING (artifact_id)
WHERE m.release_id = '<release-id>'
ORDER BY m.entity_id, c.kind, c.ordinal, ce.part_index;
```

The verifier checks complete posting selection, admission decisions, claim content,
position scope, expression nodes/ordered children, evidence substrings/hashes,
source text provenance and mapping targets. It does not replace semantic review.

Manual retention protects **all ontology-pinned source snapshots**, including
PREPARING releases, before any graph or raw deletion. This may reduce the number
of snapshots selected by a retention request. There is no automatic release/pin
cleanup in this implementation.

## Development checks

```bash
python hop/ontology/tools/build.py
KEEP_ONTOLOGY_TEST_CONTAINER=1 python hop/ontology/tests/run.py
KEEP_ONTOLOGY_TEST_CONTAINER=1 python hop/ontology/tests/claims.py
KEEP_ONTOLOGY_TEST_CONTAINER=1 python hop/ontology/tests/native.py
KEEP_ONTOLOGY_TEST_CONTAINER=1 python hop/ontology/tests/graph.py
python hop/ontology/tests/graph_types.py
```

The test database/container names are fixed to `ontologytest` and
`jobtology-ontology-test-pg`. The optional saved-real-data tests use a separate
`ontologyrealtest` database inside that same disposable container. Synthetic local
acceptance in those tests is not a production decision or a semantic quality score.
Do not point these tests at the server database.

`tests/real_graph.py` additionally runs the native graph loader over the saved
six-source and 128-output fixture in `ontologyrealtest`. It requires the source
and reviewed-claim fixture to have been prepared and sealed first. Run it
sequentially with `graph.py`: both use the same disposable Hop/Neo4j containers.

See the [server runbook](../../docs/hop-migration/server-runbook.md) for container
paths, deployment, protected metadata and native CLI execution.
