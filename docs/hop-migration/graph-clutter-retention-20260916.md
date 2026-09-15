# Current graph display and protected ALIO history, 2026-09-16

The latest reviewed Neo4j marker is `cs-reviewed-20260916-final-b` READY.
Its readback has 145 current `reviewedNcsEnrichment` nodes and 385 accepted
`ALIGNS_WITH_NCS` relationships. Those relationships record independently
accepted *duty candidates*, so several duties can align with one NCS unit.
They are not copies of source snapshots.

For the user's exact Neo4j element IDs, node `64813` is the current enrichment
for ALIO `304416` (DDCC document management); node `26633` is NCS unit
`0202010108_25v3` (`총무문서관리`). Their six current relationships have six
different candidate IDs and reasons, bound to zero-based duties D0–D5:
overall document handling, receipt/dispatch of design deliverables, system
registration/distribution, correspondence registration, supplier-document
checking, and quality-record status. The publisher merges each relationship by
`candidate_id` because each has separate evidence and an independent review
decision. `r.duty_index` is not currently a Neo4j relationship property; the
index is in PostgreSQL's frozen link payload and the relationship's
`evidence_json`.
The grouped query below was checked live: 385 accepted duty links collapse to
291 distinct enrichment/NCS endpoint groups for display.

For a less crowded **Graph view**, return one representative relationship per
enrichment/NCS endpoint and retain the count of accepted duty matches:

```cypher
MATCH (pub:reviewedNcsPublication {id:'jobtology-reviewed-ncs',state:'READY'})
MATCH (j:jobPosting)-[h:HAS_ENRICHMENT]->(e:reviewedNcsEnrichment {current:true})-[r:ALIGNS_WITH_NCS {accepted:true}]->(n:ncsCompetency)
WHERE e.publication_id=pub.publication_id
WITH j,h,e,n,collect(r) AS matches
RETURN j,h,e,head(matches) AS representativeLink,n,
       size(matches) AS acceptedDutyMatches
LIMIT 50;
```

ALIO has five complete READY source batches in Neo4j. They share 618 distinct
source-qualified `jobPosting` identities; repeated snapshot observations are
separate `ingestionRecord` nodes linked to the *same* posting identity. Expanding
a posting in Neo4j Browser can reveal those historical record neighbors even
when the initial query selected only the current enrichment. Some posting names
are shared by different IDs; a matching name is not an identity test.

Native `retention/preview.hwf` checked the oldest ALIO batches twice:

| Plan ID | KEEP_LATEST | Selection | Protected reasons |
| --- | ---: | ---: | --- |
| `2af086ce-024b-43af-9a03-2902562ca2db` | 2 | 0 of 5 | oldest two `EVALUATION_DATASET`; third `ONTOLOGY_RELEASE`; newest two `KEEP_LATEST` |
| `cda73ccd-0574-478e-a78c-af4989456b18` | 1 | 0 of 5 | oldest two `EVALUATION_DATASET`; third `ONTOLOGY_RELEASE`; penultimate `LLM_BATCH`; newest `KEEP_LATEST` |

Neither plan can be executed because both selected zero runs. The
[retention workflow](../../hop/retention/README.md) preserves complete
last-known records when an eligible snapshot is eventually pruned, but it
will not bypass evaluation, release or LLM references. Resolving those pins
requires a separate history-compaction design and dependency migration.

Two *derived* `reviewedNcsEnrichment {current:false}` nodes from older
publications had no NCS relationships and only one `HAS_ENRICHMENT` edge each.
Their full properties/edge endpoints were saved privately at
`/home/maxjo/.local/state/jobtology-hop/graph-cleanup-20260916/stale-reviewed-enrichment-before.txt`
(SHA-256 `33856314e27f4b7c9d434d799b8a4551c197be7cf2dcd6833cf1d80b1b4f634b`).
An exact-ID guarded Neo4j transaction deleted only those two nodes and edges.
Afterward: marker READY, 145 current extractions, 385 accepted links, zero stale
reviewed enrichment nodes and five ALIO source batches. PostgreSQL still has
all five READY ALIO runs and no active retention plan. No source snapshot,
raw response or PostgreSQL source row was deleted.
