# Internal editorial source: product occupations

**Native import, graph loading and JSON-LD v4/v5 passed local integration tests;
not deployed to Goldship.** The initial catalogue is an
assistant-authored draft requiring independent review. It has no real review or
Git merge attestation. Attachment processing remains
[on hold](../../docs/hop-migration/attachment-status.md).

This source implements the four product occupations named in the
[implementation plan](../../docs/implementation-plan.md#1-decision-summary).
It supplies stable product IDs and versioned Korean definitions for later posting
classification. It does not infer occupations from title keywords, map them to
NCS, or classify existing postings.

The separate [posting occupation review guide](occupations.md) describes the new
PostgreSQL import/review/freeze workflows. This stage and its
[occupation graph/JSON-LD v5 adapter](occupation-graph.md) passed local native
tests. Deployment and real production assignments remain pending.

The [derived-claim readers](derived-queries.md) expose selected occupation
assignments and normalized requirements with their exact evidence and review.
They keep inferred facts separate from original source payloads.

| Code | Korean display name | Stable ontology ID |
|---|---|---|
| `AI_ENGINEER` | AI 엔지니어 | `urn:jobtology:occupation:product:AI_ENGINEER` |
| `BACKEND_DEVELOPER` | 백엔드 개발자 | `urn:jobtology:occupation:product:BACKEND_DEVELOPER` |
| `FRONTEND_DEVELOPER` | 프론트엔드 개발자 | `urn:jobtology:occupation:product:FRONTEND_DEVELOPER` |
| `DATA_ANALYST` | 데이터 분석가 | `urn:jobtology:occupation:product:DATA_ANALYST` |

All four belong to `urn:jobtology:conceptScheme:product-occupations`. Existing NCS
occupations keep their separate NCS scheme. Labels, aliases and boundary notes
belong to immutable revisions, so future edits cannot rename a saved release.

## Edit and import the actual data

1. Edit [product-occupations.v1.yaml](catalogues/product-occupations.v1.yaml).
   It uses the JSON subset of YAML: native Hop reads exact bytes and PostgreSQL
   validates the JSON object. General YAML syntax, duplicate object keys, unknown
   fields, missing roles and repeated role codes fail validation. Use UTF-8 without
   a BOM. The [schema](schemas/product-occupations-v1.schema.json) is the executable
   contract. `actor` and `actor_kind` identify the actual author; they are not
   review fields.
2. Once a version has been imported, change `catalogue_version` and use a new
   filename for any byte change. Every version is a complete five-entity snapshot
   (one scheme plus four occupations). The same version cannot name different
   bytes, even if the change only alters whitespace. Old files and database
   snapshots are preserved.
3. Review changes through the repository before production acceptance. Compute
   `sha256sum <file>` and `git hash-object <file>` on the exact file to deploy.
   `git hash-object` does not require committing the file; its output alone is
   not proof of a merge. The development generator
   `python hop/editorial/tools/build.py` also updates
   [checksums.json](catalogues/checksums.json). Checksum generation is not review.
4. Copy the public `hop/editorial/` directory into `${PROJECT_HOME}/editorial/`
   in the existing Hop config mount. Follow the
   [server runbook](../../docs/hop-migration/server-runbook.md) for host/container
   paths and public-file ownership. No Git checkout or Python runtime is required
   inside the container. There are no API keys in this module.
5. After the ontology v3 graph/export and LLM SQL dependencies are installed, run
   `editorial/install.hwf` with `ontology-local`. It creates the additive
   `editorial` schema and installs PostgreSQL's `pgcrypto` extension for Git's
   SHA-1 blob calculation. It does not import or approve the catalogue. Its
   installer is separate from the pending ontology v3 deployment package. It also
   installs the editorial graph adapter and v4 export contract. Install it **after**
   `ontology/install.hwf`: the latter reinstalls its own graph functions, so repeat
   the editorial installer after any ontology reinstall. Reinstallation preserves
   source data and frozen selections.
6. Run `editorial/import_catalogue.hwf` with `ontology-local`:
   `CATALOGUE_FILE` is the exact container filename, `EXPECTED_SHA256` the file
   SHA-256, and `EXPECTED_GIT_BLOB` the Git blob SHA-1. The returned `snapshot_id`
   is the SHA-256. The default file path is
   `${PROJECT_HOME}/editorial/catalogues/product-occupations.v1.yaml`.
7. Run `editorial/inspect_catalogues.hwf`, or preview the corresponding pipeline's
   `Preview catalogue status` transform. Import produces `PENDING`, not accepted
   ontology data. To inspect definitions, query:

   ```sql
   SELECT entity_id, name, payload, source_pointer
   FROM editorial.item
   WHERE snapshot_id = '<returned SHA-256>'
   ORDER BY entity_id;
   ```

The [native Load file content in memory transform](https://hop.apache.org/manual/latest/pipeline/transforms/loadfileinput.html)
reads a single file into a binary field. PostgreSQL independently calculates
SHA-256 and the Git SHA-1 over `blob <byte_length>`, a NUL byte, and the original
bytes. It retains those bytes, parsed content, item pointers and hashes in one
transaction. Invalid imports leave no partial source rows. Re-importing identical
bytes returns the existing snapshot and adds no duplicate entities or reviews.

## Review and freeze a release

`editorial/review_catalogue.hwf` records a separate, append-only decision:

- `REVIEW_ID`: a new UUID for the decision; reuse only to retry the exact same
  decision. Changing fields under an existing ID fails.
- `SNAPSHOT_ID`: the imported file SHA-256.
- `DECISION`: `ACCEPT` or `REJECT`; default `REJECT`.
- `REVIEWER`, `REVIEWER_KIND`, `NOTES`: the actual independent reviewer and reason.
  Author self-review is rejected. An assistant's acceptance remains explicitly
  `ASSISTANT_REVIEWED` and cannot qualify the source for release selection.
- `GIT_COMMIT`, `MERGE_EVIDENCE`: required for human acceptance. Record the actual
  main-branch commit containing the exact blob and the merge/review reference.
  These are **operator attestations**, not facts independently established by a
  network call from Hop. Verify the commit, path and blob before recording them.

The latest decision determines current status. A later rejection cannot fall
back to an earlier approval. The newest imported catalogue version must itself
qualify; importing a newer pending draft deliberately prevents selecting an older
accepted version for a new release. Review drafts before importing them into a
production database if that would interrupt new release preparation.

`editorial/pin_catalogue.hwf` takes an exact `RELEASE_ID` and `SNAPSHOT_ID`. Use it
after six-source assembly and before typed requirement freeze, on an unsealed
`PREPARING` draft. It requires the current imported version, the current independent
human acceptance and its Git attestation. It writes the stable entity shells,
immutable revisions, source pointers and a frozen editorial membership manifest.
Replay preserves that selection even if later imports or decisions change current
status; selecting a different editorial snapshot requires a new release.

The installed editorial adapter adds this frozen source to the existing
`ontology/load_release.hwf` workflow. First finish the required source/review
assembly for the draft, then run that loader with its exact `RELEASE_ID` and
`ontology-local`. It loads a graph candidate; it does not activate a serving release.
The manifest guard still rejects an omitted editorial source with
`EDITORIAL_GRAPH_INTEGRATION_REQUIRED`. That error indicates a missing adapter or
inconsistent manifest; do not remove the guard or forge manifest fields. Drafts
without an editorial pin retain their earlier graph inventory.

## Neo4j evidence and JSON-LD v4

The graph includes the four occupation identities and their selected revisions,
one scheme identity/revision, an `INTERNAL_EDITORIAL` source, the exact catalogue
text and hashes, five source-entry records, the selected review, release selection
and source contract. It copies only the review frozen in the release, not a later
decision about the same file. Git merge metadata remains labeled as an operator
attestation.

To inspect the selected Korean definitions and their source pointers in Neo4j,
set `$release_id` to the exact draft ID:

```cypher
MATCH (release:corpusRelease {id: 'release/' + $release_id})
      -[:INCLUDES]->(definition:occupationRevision)
WHERE definition.source_id = 'INTERNAL_EDITORIAL'
MATCH (definition)-[derived:DERIVED_FROM]->(record:editorialSourceRecord)
WHERE derived.release_id = $release_id
MATCH (record)-[inside:IN_SNAPSHOT]->(snapshot:editorialSourceSnapshot)
WHERE inside.release_id = $release_id
RETURN definition.occupation_code, definition.name, definition.description,
       record.locator, snapshot.catalogue_version, snapshot.git_blob_sha1;
```

Run `editorial/export_jsonld_v4.hwf` with `RELEASE_ID` and `PREVIEW=Y` for an
already sealed draft. The output path remains
`${PROJECT_HOME}/data/ontology-exports/<uuid>.jsonld`. Wait for workflow success
before using the file. V1–v3 reject editorial-specific labels rather than silently
omitting source evidence. The immutable v4 vocabulary package is in
`ontology/versions/hop-v4/` at the repository root and is embedded in PostgreSQL
by the editorial installer; it needs no separate runtime mount.

Independent validation:

```bash
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python ontology/tools/validate.py /path/to/export.jsonld
```

The validator reconstructs all five definitions and revision hashes from the
exported source text, recomputes SHA-256/Git blob IDs, checks the frozen review,
verifies source pointers and scheme links, and compares the complete native node
and edge inventory. It also retains v3 requirement validation. A structurally
valid export does not satisfy publication: the v4 publication profile requires
the six external sources plus editorial membership, and the broader database
publication gates remain closed.

The [v2 database readers](queries.md) return the selected editorial source,
independent review, exact original entry and catalogue relations. They also
provide a scheme filter for listing just the four product occupations. The old
`ontology.query_entity_v1` reader remains available with its external-only
`source_support` contract; use v2 for editorial provenance.

## Remaining ontology work

The four definitions and boundaries need real review. The planned editorial skill,
major-alias, proficiency/eligibility vocabulary and action-template catalogues are
not supplied by this first product-occupation contract. They require their own
typed source contracts and actual reviewed data. No generic `EXPERIENCE` action is
introduced. Primary posting-role decisions, NCS mappings, cohort calculations,
serving-release integration remain separate
work. See the [completion ledger](../../docs/hop-migration/ontology-completion.md).

Developer verification: `python hop/editorial/tests/catalogue.py` creates fresh
PostgreSQL 18 and Hop 2.19 containers and removes only those containers afterward.
Its review/commit records are explicitly synthetic. It calls no provider and does
not access production. Native logs and an `editorial-report.json` are retained in
the reported `/tmp/jobtology-ontology-native-*/` directory.

The complete graph/export check is:

```bash
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python hop/editorial/tests/graph.py
```

It additionally starts a fresh Neo4j container, loads two catalogue versions,
replays the earlier release, validates v4 exports independently, rejects source
text/pointer tampering and checks legacy v1 export and private `Person` preservation.
Its `editorial-graph-report.json` is saved alongside the native logs.
