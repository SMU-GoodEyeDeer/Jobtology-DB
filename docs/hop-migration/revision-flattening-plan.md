# Neo4j revision flattening plan

Updated: 2026-10-12 KST. The user-authorized production migration and independent
preservation are **VERIFIED**. Apply finished at **07:15:32.564202 UTC** (16:15 KST),
phase `SCHEDULER_RESUMED`; the fence is removed. Independent business verification
passed at **07:16:11.123507 UTC**. PostgreSQL remains authoritative, with no serving
promotion.

Protected apply receipt:
`~/.local/state/jobtology-hop/flat-ontology-locked-execution-a6069c14782a42f39955b5bc8272a453/apply/receipt.json`.
Independent report:
`~/.local/state/jobtology-hop/flat-independent-business-final-20261012T0716Z/report.json`.
The graph changed from **240,288 nodes / 830,643 relationships** to **200,952 nodes /
751,971 relationships**, removing all **39,336 revision nodes / 315,984 legacy
attachments** and adding **237,312 backed rerouted edges**. Canonical identities
and unrelated typed graph values are preserved; no revision labels remain.

Additive SQL **028/029**, flat loaders and separate STAGED/final proofs are
installed. The sealed flat inventory contains **148,509 nodes / 715,555 edges /
39,336 revision bindings**. Finalization passed in **342.335 seconds**; ordinary
historical replay passed in **663.654 seconds**, finishing at **07:08:21 UTC**.
Original approvals/load checkpoints, **all 148 old PostgreSQL tables/schema**,
catalogue readers and historical exports remain exact. V2/v3 exports retain
**1,776,301 rows each**; v1's existing `INTERCHANGE_UNMAPPED_NODE_LABEL` refusal is
preserved without changing exporter contracts. Independent graph checks preserve
**22,295 source postings**, their stable/physical IDs and eight typed dates, plus
all **5,878 JobKorea NCS edges** and properties (21 reviewed / 5,857 unreviewed).
All 13 independent report checks passed, including zero revisions. Fence absence
was confirmed separately.

The all-ten-kind native fixture preserved **131 historical fixture tables** and
exports across typed/NULL facts, future approval/stale replay, reviewed endpoints,
full/interrupted installation, actual operator rollback/retry and ownership
refusal. The separate representative proof preserved all 148 production tables;
sealing/assertion took **69.527/22.917 seconds**. Disposable clones are removed;
protected evidence is under `flat-native-ffaf1d041ad2/` and
`flat-projection-performance-01295fcb5a6d/` in `~/.local/state/jobtology-hop/`.

A controlled pause during read-only verification enabled a guarded six-pipeline
endpoint-lookup amendment. Its full typed/all-148 preservation, **30 native cases,
74 host tests, Ruff/Pyright and 197 artifact bindings** passed before normal
resume. Immutable successor manifest
`apply/successor-224a9d4fd3914222b0ba0185a2d7e68a/manifest.json` (SHA-256
`b311d1dd3a879143127f22a431fc321a2a5814fc8b6d291f848126533077c227`) binds the
original manifest and backup; earlier failed attempts remain historical evidence.
The exact six pipelines and generator are synchronized. See
[guarded recovery/amendment instructions](../../hop/operations/README.md#flattening-the-approved-ontology-projection)
for future interrupted operations; an incomplete amendment uses `amend-resume`.

The timing record is
`~/.local/state/jobtology-hop/flat-log-timing-report-a6069c14782a/final/report.json`.
A controlled 500-row verifier improved from **11.4709 seconds / 24,381,500 hits**
to **0.12055 seconds / 18,500 hits** with the same verified result. Production
scalar/array passes changed from **1,526.075/819.634 seconds** to **79.438/66.159
seconds** on an already-written, warmed retry; this is not a cold-run or
whole-workflow speedup claim. Guarded deletion took **1,339.238 seconds for 39,336
nodes** and retains a separate performance TODO with every preservation guard.

## Preserved projection contract and historical baseline

Neo4j now serves the flat ontology projection. Immutable revisions and historical
release reads remain in PostgreSQL; ordinary loaders cannot recreate revision
nodes. Standalone revision deletion is outside this verified migration contract.

The pre-migration read-only PostgreSQL audit found **39,336 revisions**,
exactly one per entity, with no entity having multiple revisions. Five releases
are `PREPARING`; `ontology.active_release` is empty. Only
`ontology-catalog-source-20261001` is sealed and graph-verified, selecting all
39,336 revisions. This is a source-only catalogue, not an active reviewed corpus.
The pre-migration graph contained **39,336 `entityRevision` nodes**, each with one
specific revision label; the verified final graph contains none.
Newer raw source facts must not be overwritten with this older catalogue's facts.
The [current handoff](current-handoff.md#live-checkpoint-verified) records the
verified batch-free source graph and preservation of all 5,878 JobKorea NCS edges.

## Implemented requirements that remain mandatory

1. **Keep PostgreSQL history unchanged.** Preserve `ontology.revision`,
   `release_revision`, source pins/support, immutable claims/bindings, sealed
   `graph_node`/`graph_edge`, manifests, approvals and original load checkpoints.
   They retain exact selected facts and underpin historical reads and exports.
   See [001 ledger](../../hop/ontology/sql/001_ledger.sql:60),
   [immutable inventory](../../hop/ontology/sql/004_graph_inventory.sql:3) and
   [catalogue sealing](../../hop/ontology/sql/024_sealed_catalog.sql:190).
2. **Add a versioned Neo4j projection contract.** Derive flattened nodes/edges
   from the sealed inventory, with its own PostgreSQL manifest and load proof.
   Keep the original inventory and JSON-LD contracts intact; current serializers
   export PostgreSQL inventory, not a live Neo4j traversal
   ([export](../../hop/ontology/sql/018_requirement_interchange.sql:33)).
   Reusing an old node/edge count or graph-verified timestamp cannot certify the
   new projection. Catalogue approval/read gates must recognize its exact proof.
3. **Select one current ontology fact projection explicitly.** Initially use the
   sole approved source-only catalogue. Future replacement must select an exact
   accepted release and prevent older replay from rolling current facts back.
   Historical releases remain readable/exportable from PostgreSQL. Preserve
   source graph nodes' newer facts and verified dates. Copy typed revision fields
   onto their canonical identity shells; preserve identity properties and define
   collisions explicitly. For example, shell `code=ncs:<code>` and revision
   payload `code=<code>` cannot be merged by an unrestricted property copy
   ([identity construction](../../hop/ontology/sql/002_source_backbone.sql:57)).
4. **Reroute every revision endpoint before removal.** This includes source
   semantic relationships, posting positions/duties/requirements, observations,
   posting inputs/review selections, NCS mapping targets, and typed requirement
   target bindings. Retain exact revision IDs/hashes in their existing assertion
   or binding properties and PostgreSQL proof; retain `release_id` on edges.
   Replace revision-selection edges with explicit entity-selection/binding edges.
   Preserve assertion nodes, review status, evidence and mapping meaning.
   Producers are [base graph](../../hop/ontology/sql/016_requirement_graph.sql:140),
   [typed requirements](../../hop/ontology/sql/015_requirement_graph_extra.sql:101)
   and later [product occupations](../../hop/editorial/sql/010_occupation_graph.sql:101).
   Duty mappings pin a particular NCS revision, not just a current code
   ([mapping ledger](../../hop/ontology/sql/003_reviewed_claims.sql:143)).
5. **Migrate all writers and verifiers together.** The native loader currently
   reads sealed inventory and verifies exact labels, hashes and property counts
   ([generator](../../hop/ontology/tools/graph_build.py:62),
   [verifier](../../hop/ontology/tools/graph_build.py:114)). Every normal load,
   retry and historical replay must use the new projection or fail closed;
   none may recreate `entityRevision`/`*Revision` nodes. Update catalogue graph
   filters and projection checks
   ([source filter](../../hop/ontology/sql/020_catalog_source_graph.sql:78)).
   Keep existing PostgreSQL readers and revision-based JSON-LD/SHACL versions
   compatible; a flattened interchange format would be a separate new version
   ([existing shape](../../ontology/structure-shapes.ttl:35)).

## Acceptance and deployment gates

- A disposable native fixture covers every revision kind and every rerouted
  endpoint, two releases with changed/NULL fields, historical replay, missing
  current observations, tampered proof, interruption and idempotent recovery.
- Exact PostgreSQL historical inventories, exports, pins, claims, review and
  accounting fingerprints are unchanged. Historical catalogue readers still
  return the selected revision's facts, even when the current graph advances.
- Typed pre/post graph comparison preserves all source business IDs, dates and
  existing NCS edges/properties. It proves each moved fact/edge against its
  selected PostgreSQL revision, and refuses ambiguous endpoints or collisions.
- Stop revision creation first; deploy and verify the flattened projection;
  retain a typed recovery export and restored full backup proof; remove only
  exactly accounted-for revision nodes/edges. Refuse unexpected attachments.
  Independently verify zero revision nodes and normal load/replay afterward.

## Optional work that does not block flattening

On October 12 the user prioritized **DB loading and validation performance before
new matching or paid retrieval expansion**. The next plan must follow measured
hot paths and distinguish routine ingestion/replay from one-off migration costs.
Normal flat replay took **663.654 seconds**; eight property write/verify passes
took **526.385 seconds (79.3%)**, processing **3,666,327 property/array-element rows
each way**. Grouped typed-property writes, source batching (currently size 1) and
exact-proof projection reuse are candidates, not implemented; preserve typed/NULL
values, array order, stale-field removal and target checks. The **56.6-minute
historical atomic capture** is separate, with root cause still unproven.
The requested future integration is **US O*NET**
([official RDF database page](https://www.onetcenter.org/database.html#graph)),
as a distinct scheme; RDF loading/matching remains proposed, not implemented.
Existing Korean Q-Net qualification/exam support and historical evidence remain
unchanged.

Source and canonical identities are separate today: `ncs:occupation:<code>`
versus `entity/urn:jobtology:occupation:ncs:<code>`, and `job-alio:posting:<id>`
versus `entity/urn:jobtology:jobPosting:job_alio:<id>`
([source IDs](../../hop/ingestions/jobkorea/sql/004_integration.sql:33),
[canonical IDs](../../hop/ontology/sql/002_source_backbone.sql:32)). Flattening can
preserve both sets. The final graph has 1,111 occupations in each set, plus
1,014 canonical postings versus 22,295 source postings. Unification is a
separate migration requiring explicit ID
mapping and source/canonical fact ownership; it must preserve current inferred
edges, distinguish versioned units from unit families, and avoid name-based merges.
Projection/date/capture performance and proposed O*NET RDF integration are
separate follow-ups. Performance comes first. Cohort/editorial modules remain
later deployment scope; their endpoint adapters must stay compatible.

Production JobKorea metadata matching sets **`MAX_MATCHES=1`**
([supervisor](../../hop/operations/run_inferred_occupations.py:282)); live batch
settings confirm one. The retained verified snapshot has **5,878 postings with
one current verified link, 2,556 with none, and zero with multiple links**.
The underlying [validator](../../hop/llm/sql/029_metadata_occupation_links.sql:198)
supports one or two matches, and storage/publication can retain both.
One primary *product occupation* per release is a different, undeployed contract
([product-role guide](../../hop/editorial/occupations.md:10)). Neither metadata
matching nor flattening establishes source-stated duties or competency evidence.

**Migration complete.** Remaining identity, O*NET, matching-policy and performance
follow-ups are separate work; the old first-read and atomic-capture TODOs remain
unresolved. Guarded deletion performance work must preserve attachment/type
checks, exact tokens, fences, recovery and full typed preservation.
