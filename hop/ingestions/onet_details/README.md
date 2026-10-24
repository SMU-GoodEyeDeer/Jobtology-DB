# O*NET 31.0 SW/IT reference details

Production is independently **VERIFIED at 2026-10-15 12:09:01.616752 UTC**:
2,598 detail nodes and 18,609 relationships, preserving all prior PostgreSQL
data/metadata and typed graph objects. See the
[assessment, evidence and operational checkpoint](../../../docs/hop-migration/2026-10-15-onet-sw-it-details.md)
and [current handoff](../../../docs/hop-migration/current-handoff.md).

This additive reference import uses official **31.0** CSVs and the existing
`onet-31.0-catalogue-20261014` catalogue. It selects all `15-12*` occupations plus
`11-3021.00`, `15-2051.00` and `17-2061.00`: 31 catalogue terms, 30 with source
detail rows. It loads Software Skills, Essential Skills, Transferable Skills,
Knowledge, Task Statements and Task Ratings, with reachable content-model,
scale, task-category and level-anchor references. `15-1299.00` has no supplied
detail rows. Other O*NET database domains remain outside scope.

There are **no LLM calls or occupation reclassification** in this workflow. Use
only the archived official files and local posting evidence. Do not request
job-board pages, descriptions, images, iframes or signed storage URLs. Keep raw
CSVs, acquisition receipts, original posting exports and credentials outside Git.

## Prepare and qualify

The parser reads the ten local `sources/*.csv` files, their
`sources/*.receipt.json` acquisition receipts and `download-sources.json`.
Source URLs are inert provenance. It pins source bytes, validates references
and ratings, and writes an immutable bundle; a changed replay is rejected.
Run from the repository root with protected absolute paths:

```bash
.venv/bin/python hop/ingestions/onet_details/prepare_details.py \
  --source-dir /protected/official-onet-31.0 \
  --catalogue /protected/onet-catalogue-bundle/catalogue.json \
  --output-dir /protected/onet-detail-bundle \
  --release-id onet-31.0-sw-it-details-20261015

.venv/bin/python hop/ingestions/onet_details/tests/native.py \
  --bundle-dir /protected/onet-detail-bundle \
  --base-bundle-dir /protected/onet-catalogue-bundle
```

The catalogue argument is the original normalized catalogue JSON, ordinarily
the existing catalogue bundle's `catalogue.json`. The native fixture uses
disposable local PostgreSQL/Neo4j/Hop resources; its final receipt must record
successful exact-artifact qualification and resource cleanup. Retain failed
receipts as evidence. Parser tests are in
`tests/unit/test_onet_detail_parser.py`.

## Guarded production load and replay

The host coordinator requires the exact cleaned isolated native proof:

```bash
.venv/bin/python hop/operations/load_onet_details.py \
  --bundle-dir /protected/onet-detail-bundle \
  --qualification /protected/native-qualification/receipt.json
```

It acquires `refresh.lock`, requires existing writers to finish, backs up
PostgreSQL, archives the immutable bundle, deploys only the additive detail
runtime and invokes native `install.hwf` and `load_details.hwf`. It verifies
runtime readback, every preexisting application table and graph object, and
every new typed graph property/label/relationship endpoint against the frozen
PostgreSQL plan. It preserves scheduler configuration and provider credentials.
The prepared JSON is 19,301,339 bytes; the workflow's admitted
`MAX_FILE_BYTES=67108864` covers it without truncation.

`load_details.hwf` requires `INPUT_FILE`, `EVIDENCE_ROOT`,
`EXPECTED_INPUT_SHA256` and `RELEASE_ID`; `NEO4J_CONNECTION` defaults to the
existing protected `jobtology-neo4j` connection. For an already READY release,
`replay_details.hwf` takes `RELEASE_ID` and the same connection and performs
full native preflight, write/readback and activation checks. Use the existing
protected Hop project/run configuration under the same operation lock and idle
writer gate. `verify_details.hwf` takes the explicit verified `ONET_LOAD_ID`,
`RELEASE_ID` and connection for read-only detail and catalogue-endpoint checks.

Retry only the same immutable release after diagnosing a failed attempt. A
changed input under the same release ID is rejected. A different detail release
is currently refused with `ONET_DETAILS_ROLLOVER_REQUIRES_QUALIFICATION`.
There is no qualified destructive rollback/removal command; do not delete
catalogue terms, source facts, matching evidence or existing links to recover a
detail load. Preserve the backup and receipts for a separately reviewed recovery.

## Consumer semantics

The PostgreSQL owner is `onet_detail`; graph objects use
`managed_by=jobtology-onet-details-v1`, `entity:onetDetail` plus their kind label,
and the separate `urn:jobtology:onet-detail:` namespace. Existing occupation
nodes retain their catalogue identities, labels and properties.

Direct relationships are `ONET_SOFTWARE_EXAMPLE`, `ONET_ESSENTIAL_SKILL`,
`ONET_TRANSFERABLE_SKILL`, `ONET_KNOWLEDGE`, `ONET_TASK` and
`ONET_TASK_RATING`. Software nodes expose `workplace_example`; their
occupation-specific edges expose Boolean `hot_technology` and `in_demand`.
Rated edges expose `scale_id`, `scale_name`, `data_value`, `n`, statistical
bounds/flags, `category`, `date` and `domain_source` when supplied. Optional
NULL properties are omitted in Neo4j and retained in PostgreSQL evidence;
original row values remain in `source_values_json` and archived CSVs.

These are occupational references, never automatically posting requirements.
Posting-specific technology mentions need their own original field/span
evidence. Keep inferred occupation review status and NULL/UNASSESSED confidence
unchanged; published statistical confidence intervals are a separate concept.
For current-source traversal, compare
`r.source_facts_sha256=p.source_facts_sha256`; inferred edges intentionally have
`current=false`, so do not filter them with `r.current=true`.

Use `:entity` for indexed exact-ID lookup, `p.name`/`o.name` for graph display
names, selected scalar fields and 25–50-row pages. Filter current detail edges
separately. The report contains bounded software and rating queries; avoid
automatic transitive expansion from every posting.

For optional Browser graph views, detail nodes have descriptive fields rather
than a generic `name`. Download the current stylesheet with `:style`, append
these GraSS rules, and upload the edited file, preserving existing rules:

```css
node.software { caption: '{workplace_example}'; }
node.element { caption: '{element_name}'; }
node.task { caption: '{task_id}'; }
node.scale { caption: '{scale_name}'; }
```

Use `'{task}'` instead of `'{task_id}'` for the full task statement when useful.
In the Results overview, put the applicable kind label (`software`, `element`,
`task` or `scale`) above `entity` and `onetDetail`: Browser styles a multi-label
node using its highest-priority label. See the official
[Browser styling instructions](https://neo4j.com/docs/browser/operations/browser-styling/).
These are optional client display settings; no parser bundle, SQL, graph
property or qualified native runtime changes are required.


## NCS ↔ O*NET crosswalks

Ontology SQL `034_ncs_onet_crosswalk.sql` adds retrieval-only links. Apply it after
SQL 033. The public reader is `catalog.ncs_onet_crosswalk_v1(node_id, limit, offset)`;
the restricted catalog reader receives execution rights only, with no table or
proposal/review write access.

Two deterministic suggestion paths use existing local evidence and make no model
or job-board requests:

- Occupation pairs inferred for the same posting become `SHARED_POSTINGS`,
  `PROPOSED`, `RELATED` suggestions. Original source/catalog pins, individual
  inference review status and stale/unknown freshness are retained. Five samples
  are exposed; the count includes all matching postings.
- Explicit bilingual technical cues in NCS definitions and O*NET tasks, elements
  or software examples become `BILINGUAL_CUE`, `PROPOSED`, `RELATED` suggestions.
  The reader exposes exact matched substrings and both endpoint versions.
  These cues are search hints, not evidence of semantic equivalence.

A ten-digit NCS unit family ID resolves to the latest actual unit version in the
current READY catalog. Returned IDs and codes retain that version. This does not
establish equivalence between versions. `urn:jobtology:ncs:*` inputs are accepted
as canonical aliases for the native `ncs:*` source graph IDs. The skill catalog
alias `onet:skill:<element-code>` resolves only to the current O*NET ELEMENT
with that exact code; the response retains its actual `urn:jobtology:onet-detail:*`
identity and version.

A crosswalk's relation is `RELATED`, `PARTIAL` or `EXACT`; its review state is
separate. All responses carry `competency_evidence=false`, including approved
comparisons. No analysis coverage, proficiency or planning requirements change.
The application assembles virtual exploration edges; this migration does not
bypass the guarded Neo4j graph publishers.

An operator can freeze a specific comparison and append an individual review.
Set `JOBTOLOGY_ADMIN_POSTGRES_DSN` through the existing protected environment,
then use the repository interpreter:

```sh
python hop/operations/manage_ncs_onet_crosswalk.py list \
  --node-id ncs:unit:2001020101
python hop/operations/manage_ncs_onet_crosswalk.py propose \
  --source-id 'ncs:unit:<exact-unit-code>' \
  --target-id 'urn:jobtology:onet-detail:task:<task-id>' \
  --relation PARTIAL --evidence-file /private/comparison.json
```

The comparison JSON must contain `summary` (20–3,000 characters), `source_quote`
and `target_quote`. Both quotes must occur verbatim in the current endpoint's
name or definition. Optional translation notes/reference provenance may be
included; they do not prove equivalence. Compare the performance/task definitions
and scope before proposing `PARTIAL` or `EXACT` rather than relying on skill names.
Identical proposals replay idempotently. The returned mapping identifier includes
the frozen evidence, relation and endpoint versions.

```sh
python hop/operations/manage_ncs_onet_crosswalk.py review \
  --mapping-id 'crosswalk:<returned-hash>' --decision APPROVED \
  --reviewer-kind ASSISTANT --reviewer '<actual-reviewer>' \
  --note-file /private/review.txt --expected-review-id 0
```

Use `HUMAN` only for an actual human review. The review note must contain 20–3,000
characters. A first review expects ID `0`; a later decision requires the current
review ID, avoiding concurrent review overwrites. Rejection hides the link from
exploration while retaining both original proposal and every review event.
Automatic cue/co-occurrence candidates for the same frozen endpoints do not
immediately reappear after an explicit review decision.
Changed catalog versions make old comparisons stale and prevent new approval;
create a new version-pinned proposal after reassessment. Review never rewrites
old pins or upgrades inherited inference review status.
