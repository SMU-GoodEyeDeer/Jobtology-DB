# Load reviewed product occupations into Neo4j and JSON-LD

**Local native integration verification passed on 2026-09-13 KST; not deployed to Goldship.**
This adapter adds the [reviewed occupation decisions](occupations.md) to the
existing ontology graph loader. It preserves the source revisions, selected
review, duty evidence and catalogue definitions for each release. The full
serving ontology is still unfinished, and attachments remain
[on hold](../../docs/hop-migration/attachment-status.md).

## Manual loading sequence

1. Deploy the tested public `hop/editorial/` artifacts into
   `${PROJECT_HOME}/editorial/` using the [server runbook](../../docs/hop-migration/server-runbook.md).
   Do not copy private connection metadata or development fixture approvals.
2. Install `ontology/install.hwf`, then `editorial/install.hwf`. The latter's
   SQL 010–013 installs the occupation graph adapter and immutable v5 export
   contract. Use the existing `jobtology-postgres`, `jobtology-neo4j` and
   `ontology-local` configurations. No additional runtime service is needed.
   Reinstall the editorial module after an ontology reinstall, because the base
   installer restores its own graph functions.
3. In the intended unsealed draft, finish source assembly, catalogue pinning and
   reviewed claim assembly. Complete occupation proposals and independent review,
   inspect every outcome, then run `editorial/freeze_occupations.hwf` with the exact
   `RELEASE_ID`. Also finish and freeze the intended
   [typed requirements](../ontology/requirements.md) before graph loading. Do not
   create reviews merely to pass a freeze or publication check.
4. Run `ontology/load_release.hwf` with that `RELEASE_ID`. It seals the selected
   data, loads the candidate graph through native Hop, and compares the graph
   against the PostgreSQL inventory. This does not activate a serving release.
5. Run `editorial/export_jsonld_v5.hwf` with the same `RELEASE_ID` and `PREVIEW=Y`
   for a sealed draft. The workflow allocates a file under
   `${PROJECT_HOME}/data/ontology-exports/`. Blank `RELEASE_ID` selects only the
   active published release; it does not silently choose the latest draft.

The v5 serializer includes the earlier source, observation, requirement and
editorial contracts. V1–v4 packages retain their existing bytes and behavior.
An older serializer rejects an occupation-bearing graph rather than dropping the
new facts. Drafts without an occupation freeze retain their earlier inventories
and can still use their applicable older serializer.

## Resulting nodes and relationships

`occupationReviewSelection` accounts for every selected posting. Pending,
rejected, changed-source, changed-catalogue, out-of-scope and unresolved outcomes
remain visible. `occupationProposal` and `occupationReview` preserve the selected
proposal and decision, including actual author/reviewer kinds and model provenance.
`occupationFreeze` records the cutoffs and membership hash.

Only MATCHED selections produce `primaryOccupationClaim` assertions. Each has:

- `HAS_SUBJECT` to the exact posting revision.
- `TARGETS` to the product occupation identity and `SELECTS_REVISION` to the
  catalogue revision used for that name and definition.
- `DERIVED_FROM` to its proposal and `REVIEWED_BY` to its selected decision.
- `EVIDENCED_BY` to the exact cited duty/source spans.

A generated `FOR_OCCUPATION` edge connects the posting revision to the product
occupation. Its `source_assertion_ids` identifies the authoritative claim; the
loader adds the edge's `release_id`. NCS mappings retain their separate meaning.
The assignment's display name combines the posting title and Korean occupation
name. Confidence stays UNASSESSED, with no fabricated numeric score.

`occupationBinding` preserves the complete source or catalogue object used by a
proposal. Its nested objects and ordered arrays use `occupationBindingValue`
nodes and `BINDING_MEMBER` relations. Keys, array indices, empty objects/arrays,
nulls and primitive value types survive export. Identical binding objects are
shared by content identity. These are saved review inputs; an old binding does
not assert that an obsolete duty or catalogue revision is current. Only accepted,
current matches gain the primary-occupation links above.

## Inspect one release

Use release-scoped relationships and the selected occupation revision for display
names. For example, with a Neo4j Browser parameter named `releaseId`:

```cypher
MATCH (:corpusRelease {id: 'release/' + $releaseId})-[:INCLUDES]->(c:primaryOccupationClaim)
MATCH (c)-[:HAS_SUBJECT {release_id: $releaseId}]->(p:jobPostingRevision)
MATCH (c)-[:SELECTS_REVISION {release_id: $releaseId}]->(o:occupationRevision)
RETURN p.name AS posting, o.name AS occupation,
       c.review_status AS review, c.claim_id AS assertion_id
ORDER BY posting;
```

To account for postings without a primary match:

```cypher
MATCH (:corpusRelease {id: 'release/' + $releaseId})-[:INCLUDES]->(s:occupationReviewSelection)
RETURN s.outcome AS outcome, count(*) AS postings
ORDER BY outcome;
```

Run the loader again with the same sealed release to verify/reuse its graph.
Later proposals, reviews or catalogue imports require a new release selection.
They do not rewrite the old release's assertions, evidence or target names.

## Export validation and remaining work

On the development machine, validate the exported file using the pinned libraries:

```bash
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python ontology/tools/validate.py /path/to/export.jsonld
```

The v5 verifier reconstructs the binding objects, proposals and reviews from the
RDF graph and checks their hashes against the frozen PostgreSQL manifest. It
checks every posting outcome, exact evidence, target scheme/revision and the
assertion IDs on shortcut edges. The structural SHACL profile is separate from
the publication profile (`--publication`). A structurally valid draft does not
establish model quality, confidence calibration or publication readiness.

Production catalogue/occupation review, calibrated claim and NCS resolution,
cohorts and publication lifecycle requirements remain open. OUT_OF_SCOPE is an
explicit reviewed outcome; a separate serving-scope policy is still needed before
such records can be excluded from a published product corpus. The existing
publication gates remain in force.

Integration command:

```bash
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python hop/editorial/tests/occupation_graph.py
```

It uses uniquely named disposable PostgreSQL 18, Hop 2.19 and Neo4j 5.26 fixture
containers, with synthetic Korean data and review decisions. It exercises native
graph loading, streaming export, independent JSON-LD/SHACL checks, changed input
and catalogue outcomes, old-release replay, altered evidence/support rejection
and compatibility with older export versions. This is local verification; the
existing Goldship Neo4j instance is not used by the test.

The passing fixture has 910 nodes / 2,080 edges / 55,869 RDF triples for the
original release, including four primary occupation links. Its changed-input/
catalogue release has 906 nodes / 2,048 edges / 55,149 triples and no primary links.
Both structural profiles passed; both publication profiles correctly failed.
Native replay preserved the original inventory, and altered duty text, incorrect
shortcut assertion IDs and changed graph properties were rejected. The older v4
and v1 export fixtures also passed. Private Person data and provider/attachment
history remained unchanged; no paid calls or production writes occurred.

Evidence: `/tmp/jobtology-occupation-graph-test.log` and
`/tmp/jobtology-ontology-native-4nn23l0o/occupation-graph-report.json`, alongside
the native logs, exports and exact tested graph/contract artifacts. The test's
three containers and private network were removed on completion.
