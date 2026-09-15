# Versioned ontology interchange

The `hop-ontology-interchange-v1` package exports a **sealed release inventory** as
JSON-LD 1.1, with Schema.org alignments and Jobtology claim/evidence terms. It does
not extract text, call an LLM, accept reviews, seal a draft or activate a release.
Attachment processing remains [on hold](../docs/hop-migration/attachment-status.md).

For typed requirements, use `export_jsonld_v3.hwf` and the immutable package under
`versions/hop-v3/`. V3 distinguishes original `SourceRequirementGroup` records
from normalized `RequirementClaim` records, exports all frozen proposal outcomes,
and reconstructs condition keys and target bindings during independent validation.
See [the typed graph/export guide](../hop/ontology/requirement-graph.md). V1 and v2
remain available for their earlier inventories and refuse unknown newer labels.
V3 passed local native tests and is now deployed on Goldship. Native installation
and draft reads passed, with earlier contracts and protected data unchanged.
Production normalization/review remains unfinished, as recorded in that guide.

For the internal product-occupation catalogue, use
`editorial/export_jsonld_v4.hwf` after installing the editorial adapter. V4 preserves
the exact source file, definitions and frozen review/merge attestation. It has
passed local Hop/PostgreSQL/Neo4j and independent RDF checks but is not deployed.
See the [editorial source and graph guide](../hop/editorial/README.md#neo4j-evidence-and-json-ld-v4).
The earlier v1/v2/v3 packages remain unchanged.

For reviewed primary product occupations, use `editorial/export_jsonld_v5.hwf`
and `versions/hop-v5/`. V5 preserves every selected occupation outcome, original
review inputs, exact decision and supported `FOR_OCCUPATION` link. Independent
validation reconstructs binding objects and checks the review/assignment manifest.
The [occupation graph guide](../hop/editorial/occupation-graph.md) records the
passing local native Neo4j/RDF tests. Deployment and production assignments remain
pending; v1–v4 packages are unchanged.

The base v1 package was deployed and checked on Goldship on **2026-09-13 KST**. Native full saved-data
export/readback passed for 182,670 nodes and 785,235 edges. Representative RDF/SHACL
checks passed for valid structure and rejected incomplete publication data.
Full-scale RDF/SHACL resource validation and publication integration remain
pending; see the [verification receipts](../docs/hop-migration/ontology-completion.md#native-json-ld-interchange-and-shacl-profiles--2026-09-13-kst).

## Files and contracts

| Artifact | Purpose |
|---|---|
| `context.jsonld` | Embedded JSON-LD context; no remote context lookup is needed. |
| `terms.yaml` | Versioned term inventory, encoded as JSON, a YAML subset. Reserved terms explicitly identify unimplemented publication data. |
| `mappings/hop-v1.json` | Native labels/properties/predicates, opaque ID encodings and Schema.org alignments. |
| `vocabulary.ttl` | RDF vocabulary and class alignments. |
| `structure-shapes.ttl` | Structural constraints for exported identity/revision, relation, evidence, expression and release nodes. |
| `publication-shapes.ttl` | Additional publication constraints, including occupation/observation, review and normalized requirement fields. |
| `shapes.ttl` | Generated combination of both shape profiles. |
| `tools/validate.py` | Offline RDFLib/pySHACL validator and native-content hash readback. Not an ETL transform. |

The generator writes the public contract into
`hop/ontology/sql/006_interchange_contract.sql`. `ontology.interchange_contract`
stores its immutable artifacts and `ontology.hash(artifacts)`. Reinstallation is
idempotent. Changing an already installed version raises
`INTERCHANGE_CONTRACT_VERSION_CONFLICT`; release a new contract version instead.
Python is used for development and independent validation. Export transformation
and file writing run through native PostgreSQL SQL and Hop transforms.

The repository's root `ontology/` directory is the interchange package. The
separate `hop/ontology/` directory contains native runtime files and is deployed
as `${PROJECT_HOME}/ontology`. Do not replace that runtime directory with the
root vocabulary directory. The installer embeds the exact vocabulary package in
PostgreSQL; the Hop runtime does not need a separate root-vocabulary mount.

## Export from Hop

1. Install the matching package with `ontology/install.hwf` and the
   `ontology-local` run configuration.
2. Select an already assembled, reviewed and sealed release. Sealing is a
   separate step in the [graph loader](../hop/ontology/README.md#load-the-ontology-graph-candidate).
   Do not seal an unfinished production draft just to obtain an export.
3. Run **`ontology/export_jsonld.hwf`**, using `ontology-local`:

   | Parameter | Default | Meaning |
   |---|---|---|
   | `RELEASE_ID` | blank | Exact release; blank selects only the active published pointer. |
   | `PREVIEW` | `N` | `Y` permits an explicit sealed draft; `N` requires a published, non-revoked release. |

4. Find the generated UUID in the `Export destination` log entry. The file is
   `${PROJECT_HOME}/data/ontology-exports/<uuid>.jsonld`, inside the persistent
   project mount. Each run gets a fresh filename. Existing exports are not
   overwritten, and no export retention schedule is installed.
5. Wait for workflow success, then copy the file out and validate it against this
   exact local package. A failed or interrupted writer can leave an incomplete
   file: file existence alone is not success. Do not consume or distribute a
   file from an unsuccessful run.

The underlying read-only function is:

```sql
SELECT line
FROM ontology.export_jsonld_v1('exact-sealed-release', true)
ORDER BY line_no;
```

This emits a single JSON-LD document in ordered lines. Table Input reads the
ResultSet and Text File Output writes UTF-8 without CSV quoting or headers. All
rows share one PostgreSQL statement snapshot. The database may spill its result
tuplestore/sort to disk; the corpus is never one giant Hop field. Full-corpus RDF
validation still needs memory for the parsed RDF graph and must be sized/tested
separately from Hop's streaming file writer.

Errors include `SEAL_ONTOLOGY_GRAPH_FIRST`, `SEALED_GRAPH_INVENTORY_CHANGED`,
`INTERCHANGE_NATIVE_CONTENT_HASH_MISMATCH`, `INTERCHANGE_UNMAPPED_NODE_LABEL` and
`INTERCHANGE_UNMAPPED_PREDICATE`. The existing read gates also reject an absent
active pointer, unpublished reads, failed/revoked releases and invalid preview
flags. The export does not fall back to a newer draft or omit unfamiliar types.

## What is preserved

Each file has one named graph for its selected release. Stable entity shells and
their selected immutable revisions remain separate. Names, titles, dates and
changing source fields stay on revisions. The same entity can therefore occur in
two release files with different selected revision facts. Validate/query one
named graph at a time; merging releases into one default graph loses this scope.

For example, use the file's top-level `@id` as the graph IRI below. Count distinct
`jt:JobPosting` identity shells; a broad Schema.org type query can also include
their typed revision records.

```sparql
PREFIX jt: <urn:jobtology:vocab:1:>
PREFIX schema: <https://schema.org/>
SELECT ?posting ?title ?employerName WHERE {
  GRAPH <urn:jobtology:release:HASH_FROM_THE_FILE> {
    ?posting a jt:JobPosting ; jt:hasRevision ?revision .
    ?revision schema:title ?title ; jt:postedBy ?employer .
    ?employer jt:hasRevision/schema:name ?employerName .
  }
}
```

Native node IDs, ordered label lists, property keys, content hashes and exact
primitive values remain recoverable. Arrays use ordered RDF lists, including
duplicates and empty lists. Numbers use explicit integer/decimal literals, so
large integer IDs and decimal scale do not pass through a JavaScript float.
Unknown native property names use `jtf:` followed by their UTF-8 hex encoding;
they are not discarded or confused with dotted/nested field names.

Every native edge is exported as a direct RDF relation **and** an identified
`rdf:Statement` with its original edge ID, endpoints, predicate, hash and
qualifiers. This retains ordinal/part-index information and separate edges even
where RDF set semantics would collapse identical direct triples. `hasRelation`
connects the subject to the corresponding relation record.

Schema.org types and selected names, URLs, dates and hiring-organization
relations are additional alignments. NCS competency units and unresolved unit
families remain distinct from generic skills. Curriculum references do not
become evidence that someone holds a qualification. NCS mappings do not become
`skos:exactMatch` without the separate mapping semantics/review required by the
design. Private application `Person` nodes are not an exportable native label.

Korean excerpts retain their exact text, hashes, Unicode code-point offsets and
artifact/source relationships. Source-record locators and any **already selected**
document lineage are exported as stored. This does not download, parse or rebuild
attachment inputs. Raw filesystem paths and private connection metadata are not
added by the exporter.

The virtual `CorpusRelease` root is outside the native node inventory count. Its
`nativeContentHash` is the sealed native manifest hash, matching the Neo4j release
root convention. The embedded native manifest and export-contract hash identify
the selection and interchange version. `hop-ontology-jsonb-v1` hashes use the
existing versioned PostgreSQL JSONB encoding; they are **not RFC 8785/JCS IDs**.
Node/export graph IRIs hash their exact native identifier bytes; source IDs are
not recalculated under another identity algorithm.

## Observation-aware export (v2)

Releases assembled with `ontology/bind_observations.hwf` contain canonical
`EntityObservationState` nodes and may include historical posting revisions and
source evidence. Export them with **`ontology/export_jsonld_v2.hwf`** using the
same `RELEASE_ID` and `PREVIEW` parameters as v1. The UUID output location and
sealed-release/read gates are unchanged.

The immutable v2 package is in `ontology/versions/hop-v2/`; v1 remains installed
and reproducible for older exports. Its exporter intentionally rejects unknown
observation labels. The validator below recognizes either supported version and
uses its exact local package. No remote context is fetched.

V2 preserves native timestamp strings for exact hash readback and adds typed RDF
`firstSeenAt`, `lastSeenAt` and `evaluatedAt`. Its structure checks include state
identity/membership hashes, time ordering and matching entity/revision endpoints.
Publication still requires the other ontology conditions, reviewed semantic
content and database activation gates. See the [observation guide](../hop/ontology/observations.md).

Build v2 after building v1 with `python ontology/tools/build_observations.py`,
then regenerate the native workflows with `python hop/ontology/tools/build.py`.
Never edit an already deployed contract under the same version.
`versions/hop-v2/property-declaration-order.json` preserves the deployed RDF
declaration order during regeneration; it is a build input, not an exported data
file. Regeneration must reproduce the installed package byte-for-byte.

## Validate and interpret the result

From the repository root:

```sh
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python ontology/tools/validate.py /path/to/export.jsonld \
  --report /path/to/structure-report.ttl

uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python ontology/tools/validate.py /path/to/export.jsonld --publication \
  --report /path/to/publication-report.ttl
```

The first command verifies the fixed context/package, single graph scope,
manifest/counts, every recovered native node/edge hash and the structural SHACL
profile. The second additionally applies publication shapes. Both return exit 1
on a rejected contract. SHACL reports identify failing nodes and property paths.
Validation reads local files only and does not follow source URLs or remote
contexts/imports.

A valid preview is still a preview. Existing partial reviewed fixtures correctly
fail publication checks for missing primary occupation, observation state,
normalized requirements and assertion review/confidence fields. A SHACL pass
cannot replace semantic review, full source-offset readback, authoritative
PostgreSQL/Neo4j inventory comparison, source freshness, typed-condition checks,
cohort/support-trace verification or lifecycle gates. Those integrations remain
in the [completion ledger](../docs/hop-migration/ontology-completion.md). No
SHACL result currently activates a release or changes a review decision.

## Development and verification

```sh
python ontology/tools/build.py
python hop/ontology/tools/build.py
uv run --no-project --with-requirements ontology/requirements-validation.txt \
  python hop/ontology/tests/interchange.py
```

The test creates uniquely named disposable PostgreSQL/Hop containers. It uses
synthetic inline source/review fixtures and compares every native node, edge,
property, ordered label and evidence excerpt after an independent RDF decode.
It exercises different pinned NCS releases, repeatability, integer/decimal/list
boundaries, structural corruption, publication rejection and native Hop output.
It does not reset retained test databases or invoke live source/model services.

When the retained `ontologyrealtest` saved-source fixture exists, the additional
`hop/ontology/tests/interchange_saved.py` command clones it into a temporary
database, runs the full native export with a 1,024 MB Hop heap, and independently
decodes/hashes every native node and edge from the output stream. It leaves the
original fixture unchanged. This corpus-scale readback is distinct from the
representative RDF/SHACL checks above.

The representation follows [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/),
[SHACL](https://www.w3.org/TR/2017/REC-shacl-20170720/), and
[Schema.org JobPosting](https://schema.org/JobPosting). Validation uses
[RDFLib's pySHACL](https://github.com/RDFLib/pySHACL); native file writing uses
[Hop Text File Output](https://hop.apache.org/manual/latest/pipeline/transforms/textfileoutput.html).
