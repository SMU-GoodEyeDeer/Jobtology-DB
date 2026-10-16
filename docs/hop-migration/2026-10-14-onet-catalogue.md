# O*NET reference catalogue milestone (October 14)

**Production VERIFIED at 2026-10-14 05:48:02.915351 UTC (14:48 KST).**
PostgreSQL has the pinned READY catalogue; Neo4j has its verified 1,597 flat
nodes and 3,169 catalogue relationships. Posting matching remains unimplemented
for O*NET. Load/replay made zero source/provider requests; no job-board, paid or
posting-matching call ran in this milestone.

The user authorized an actual PostgreSQL and Neo4j O*NET catalogue load. This
authorization supersedes the earlier performance-only restriction on O*NET for
this milestone. Work stops before posting matching, candidate retrieval, prompt
changes or LLM calls. Historical no-O*NET checkpoints remain historical evidence.

## Source and interpretation

The pinned inputs are the official [O*NET 31.0 Database](https://www.onetcenter.org/database.html)
occupation JSON, the official O*NET occupation CTDL JSON-LD catalogue and the
[O*NET-SOC 2019 structure](https://www.onetcenter.org/taxonomy/2019/structure.html).
[O*NET-SOC 2019](https://www.onetcenter.org/taxonomy.html) is based on SOC 2018.
All subsequent parsing and database loading use the local archived bytes;
JSON-LD contexts and source URLs are inert provenance values.

The catalogue contains **1,016 occupations and 580 groups**, with **1,573 broader
relations**. A detailed SOC occupation represented by an O*NET `.00` code is an
occupation node. The projection contains **1,597 flat nodes** including its
scheme, and **3,169 relationships**: 1,596 `IN_SCHEME` and 1,573 `BROADER`.
This milestone imports catalogue codes, names, descriptions, source provenance
and hierarchy. The complete O*NET tasks, skills, ratings and other database
tables are outside this catalogue milestone.

Attribution: O*NET 31.0 Database, U.S. Department of Labor, Employment and
Training Administration (USDOL/ETA). The database and Resource Center material
are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
as stated by the [database license](https://www.onetcenter.org/license_db.html)
and [Resource Center license](https://www.onetcenter.org/license.html).
Jobtology selects catalogue fields, normalizes stable identifiers and source
hierarchy, and adds local processing metadata and hashes. Preserve this
attribution and modification notice when redistributing the projection.

## Storage boundary

The additive `classification` PostgreSQL schema stores immutable releases,
source-file evidence, terms, hierarchy and graph plans. A verified current
pointer selects the O*NET catalogue independently of the existing Korean
catalogue, ontology releases, source pins and frozen matching inputs.
Downloaded-at evidence comes from the retained acquisition receipts. Prepared
and imported timestamps are repository processing times; they do not substitute
for a source publication or collection time.

Neo4j contains only the scheme, groups and occupations with exact
`entity`, `onetCatalogObject` and kind labels. Stable IDs begin
`urn:jobtology:onet:` and every owned object has
`managed_by=jobtology-onet-catalog-v1`. Catalogue relationships have owned
endpoints and only the `IN_SCHEME` or `BROADER` type. No posting/NCS links,
revision nodes, archived records, scaffold nodes, confidence or duty evidence
are created. During an explicitly pinned rollover, removed terms and
relationships stay as owned objects with `current=false`; old PostgreSQL
release evidence remains immutable.

The existing NCS matcher and Korean Q-Net functionality retain their existing
runtime and pins. A later O*NET matching implementation requires its own scoped
authorization and design; loading this reference catalogue does not implement it.
The hierarchy establishes no equivalence between NCS and O*NET occupations.
Remaining matcher work is:

1. Korean-to-English candidate retrieval over the 1,016 `OCCUPATION` terms,
   including valid `.00` occupations and excluding groups; record derived
   translation/embedding provenance.
2. Separate O*NET scheme-specific posting, catalogue and candidate pins,
   validation, abstentions and actual review status. Dotted O*NET codes cannot
   enter the existing eight-digit NCS matcher contract.
3. Separate audit/publication and typed graph checks, with offline qualification
   before any separately authorized paid pilot. Existing NCS results stay intact.

## Operational contract

Prepare a new immutable private bundle from local archived evidence:

```sh
.venv/bin/python hop/ingestions/onet/tools/prepare_catalog.py \
  --occupation-file /protected/occupation_data.json \
  --taxonomy-file /protected/occupation_taxonomy.jsonld \
  --structure-file /protected/soc_structure.csv \
  --output-dir /protected/onet-bundle \
  --release-id onet-31.0-catalogue-20261014 --source-version 31.0
```

The bundle retains all three source files and required acquisition receipts,
plus the normalized `catalogue.json` and pinned `descriptor.json`. Source,
catalogue and receipt hashes and byte lengths must match the complete inventory.
The parser reconciles all supplied occupation code sets with the JSON-LD
catalogue and complete structure, compares titles/descriptions and records any
text differences without replacing raw evidence. The coordinator independently
confirmed that all 1,016 titles and descriptions agree in the actual supplied
official files. This adapter is qualified for source version 31.0; future source
versions require a separately qualified extension.
The native importer independently verifies local evidence and the expected
input digest before PostgreSQL import.

Run the isolated native qualification against that exact bundle:

```sh
.venv/bin/python hop/ingestions/onet/tests/native.py \
  --bundle-dir /protected/onet-bundle
```

This uses one new internal Docker network, local images with pulling disabled,
and uniquely owned PostgreSQL, Neo4j and Hop containers. It covers small genuine
source-backed loads, exact graph replay, immutable release replay, rollover,
soft retirement, changed pins, malformed namespaces, a wrong input digest,
tampered local evidence and foreign reserved graph identities before writes.
The final native workflow loads and replays the entire supplied official
catalogue. Qualification receipts bind exact public artifacts and the official
payload, and must prove container/network/private-scratch cleanup.

The production supervisor accepts only that completed proof:

```sh
.venv/bin/python hop/operations/load_onet_catalogue.py \
  --bundle-dir /protected/onet-bundle \
  --isolated-proof /protected/native-receipt.json
```

It acquires the existing scheduler lock and durable fence, takes one fresh
PostgreSQL backup, installs only the new O*NET public runtime, preserves an
immutable private archive, and executes native `install.hwf` and
`load_catalog.hwf` in the actual server Hop container. It then replays the same
pin and independently verifies the installed bytes, current release and all
expected graph objects. One legacy PostgreSQL before/after pair protects every
old table, schema object, execution metadata, complete query output and catalogue
pin. One complete typed Neo4j before/after pair protects all unrelated element
IDs, labels, endpoints and properties. Every owned graph property and endpoint
must match the immutable PostgreSQL load plan.

Failure retains the scheduler fence, backup, archive and logs. Inspect the exact
owned load state and failed receipt before retry; there is no automatic graph
deletion or guess at a partial rollback. Raw exports, acquisition evidence,
credentials and full receipts remain outside Git.

The supervisor's `--resume-prewrite /protected/failed-receipt.json` is restricted
to an untouched first-load failure before backup/publication/installation. It
requires the exact fence, runtime, bundle and proof; absence of new public files,
the classification schema and attempted mutation files; and the retained legacy
PostgreSQL baseline. It preserves the failed receipt and partial snapshot logs,
creates a linked child attempt and runs a two-row native scalar-grid probe before
the corrected read-only snapshot. It does not repeat the full PostgreSQL baseline
or take more than one successful pre-installation backup.

`--resume-pregraph /protected/failed-receipt.json --stopped-proof /protected/stopped.json`
handles a separate, normally failed first-load preflight. It requires the exact
owned failed token, no writer/current/target/activation, no owned or reserved
graph objects, unchanged installed predecessor bytes, and the original backup,
archive and PostgreSQL/typed graph baselines. A new completed native proof must
bind the successor bytes and explicitly qualify `replay_catalog.hwf`, no
reimport, exact full replay and frozen-import normalization. Only the two
qualified preflight HPLs may change. A linked child reuses the one backup and
baselines and runs the exact replay workflow twice; it does not reinstall SQL,
reimport source evidence or capture another full before-state.

Future rollover recovery has a separate serving limitation: a failed partial
graph mutation can leave the old PostgreSQL current pointer beside a mixed
graph. Consume O*NET current/graph queries only after a verified target with no
outstanding partial-mutation/recovery state. The scheduler fence protects the
operator path; stronger read gating for future failed rollovers remains a TODO.
This milestone does not claim atomic availability across both databases.

The current native launcher has no hard workflow deadline; its input/cardinality
and heap bounds do not bound elapsed time. Production node preflight completed
in **232.755 seconds**. A private read-only transaction observation shortly
before completion reported 50,999,315 page hits for one active batch, with no
wait or faults. These are observed phase/batch facts. The unlabeled per-row node
lookup and global per-row edge-ID lookup suggest repeated scans; their exclusive
costs are not established. The resolved change qualifies node
lookups by label after the complete scope gate and scans global owned-edge
candidates once per batch while retaining every foreign/reserved-ID, duplicate,
endpoint, type and property collision check. The narrow two-HPL change is
**deployed and VERIFIED** with complete preservation acceptance below.
The retry workflow completed in **18.657 seconds** and
exact replay in **25.847 seconds**. Their node preflight times were
**1.512/1.544 seconds**, and edge preflight times **5.008/10.075 seconds**.
These are scoped production workflow/phase observations. The old edge phase
was censored, so there is no completed edge speedup ratio; no paired
whole-ingestion or generic throughput claim is made. A safe owned-process
deadline/cancellation contract also
remains a follow-up; global aborts are unsafe and the retention/scheduler fence
must remain until exact owned cleanup/recovery is proved. An abrupt
host-launcher stop does not establish remote Hop/transaction termination or
writer cleanup; operator recovery must prove the exact owned process/load state.

Read the selected PostgreSQL reference catalogue through its separate views:

```sql
SELECT term_kind, count(*) FROM classification.current_term GROUP BY term_kind;
SELECT code, preferred_label, description FROM classification.current_term
WHERE term_kind='OCCUPATION' ORDER BY code;
```

Read the current graph inventory using the owner and current marker:

```cypher
MATCH (n:onetCatalogObject {managed_by:'jobtology-onet-catalog-v1', current:true})
RETURN n.kind, count(*) ORDER BY n.kind;
```

## Verification record

The pinned release is `onet-31.0-catalogue-20261014`. Its normalized private
payload is 2,690,607 bytes with SHA256
`7d49867a5889a187bd200dfb08cf5ab6bef631db6d9e6f36753c34374dcc7285`.
The complete eight-file private bundle retains the original three source files,
three acquisition receipts, descriptor and normalized payload.

The final combined successor qualification is **PASSED**, with **50 checks** and complete
resource/private-scratch cleanup. The full official load and exact replay created
1,597 owned nodes and 3,169 relationships. A separate native read-only verifier
passed, and an independent typed SQLite inventory matched every owned property,
label, relationship type and endpoint to the immutable PostgreSQL graph plan.
Legacy PostgreSQL and typed graph values stayed exact; the transient writer
registry returned to empty. Qualification binds all 23 public artifacts to the
exact payload above. Its protected receipt is
`~/.local/state/jobtology-hop/onet-native-f1738659f392/receipt.json`, SHA256
`0e92a42f3c595635456085b330c4d72e148b22fe23784f784dc46e40e4730a86`.
It adds owned indexed-node extra-label/wrong-hash and global owned-edge wrong
endpoint/other allowed type/scalar type/duplicate-ID rejection, each before any
graph mutation. The exact `replay_catalog.hwf` recovers the full release after
failed preflights and replays it without changing READY import evidence. The
read-only normalization guard matches the actual immutable PostgreSQL input.
The predecessor 36-check proof and intermediate 48-check supporting proof remain
retained; the recovery gate requires the final workflow-specific checks.

Three earlier failed receipts remain intact with verified cleanup: one fixture
used an unsupported Cypher list/map conversion; another caught the generated
SQL renderer's missing closing quote; a third fixture expected lowercase Cypher
Boolean output. Their corrections are covered by the final combined proof.
The separate 43-check PostgreSQL core oracle and 72 focused parser/workflow/
supervisor checks also passed. These are functional correctness proofs for this
catalogue and do not establish production throughput or larger maxima.

The actual server Hop installation, qualified successor publication, catalogue
load and exact replay are **VERIFIED**. Independent acceptance retained all
**157 legacy PostgreSQL table fingerprints**, old schema/query/catalogue/prompt/
matching state and all **460 function execution-metadata entries**, including
OIDs. The complete typed comparison preserved **201,292 legacy nodes and
752,067 legacy relationships**. Every new O*NET label, typed property, endpoint
and relationship type matched the immutable PostgreSQL load plan. The final
graph has **202,889 nodes and 755,236 relationships**.

Live PostgreSQL readback confirmed 1,016 occupations, 580 groups, READY catalogue,
VERIFIED graph target, no running catalogue load and no remaining writer. The
runtime is idle and the scheduler fence is absent. The protected final receipt is
`~/.local/state/jobtology-hop/onet-catalogue-load-8ac5a7561d8c40c795560ae15c1ccdf5/resume-prewrite-138dced4ff9743c2ba55b71c050f7644/resume-pregraph-a7d0726551ed4772890f471641648140/receipt.json`,
SHA256 `30d4b623114bbf9cc8ad8f7cb173b5416b96ff44207d277537aa5fff43206ec4`.
Its source/provider/posting-matching counters are zero. The catalogue is ready;
the separate O*NET matcher work above remains the next implementation boundary.

The first production attempt stopped during its read-only graph snapshot,
before backup, public publication or catalogue/database writes. The source
verifier template now batches under `$rows`, while the private snapshot requires
scalar `$bounds`. A scoped private snapshot adapter fixes that binding without
changing the 23 qualified public artifacts or any frozen source workflow.
The guarded prewrite child retains the original 157-table PostgreSQL baseline
and failed receipt/logs, and its two-row scalar probe passed in the actual server
Hop container before the replacement snapshot. The failed parent receipt at
`~/.local/state/jobtology-hop/onet-catalogue-load-8ac5a7561d8c40c795560ae15c1ccdf5/receipt.json`
retains SHA256 `e7c7adadcfe4ef29a8d64e49eca354032583372fe79109892c606ad73dc6c44c`.

The installed predecessor then completed node preflight but exposed slow global
edge collision checking. The coordinator terminated only the exact owned
read-only preflight transaction at 05:24:44 UTC; normal `graph_fail` completed,
the Hop process exited, and readback proved one owned `FAILED` load, zero writers,
targets/current/activations and zero O*NET graph objects. The complete failed
workflow's **653.972 seconds** and interrupted edge phase's **416.055 seconds**
are censored timings; they do not establish a completed edge baseline or speedup.
The stopped child receipt retains SHA256
`c8c0712dfa85d6331b255414edbb992773771030f6fac9194ae388cf6eff8cd5`.
The scoped successor preserves its 943,415,164-byte fresh PostgreSQL backup,
SHA256 `f342339f4cf926e37eac0684c1f2ed81787ca183b8a3a87975188373ed02c0f1`,
and the original 201,292-node/752,067-relationship typed graph baseline. Only
`graph_preflight_nodes.hpl` and `graph_preflight_edges.hpl` change. All core SQL,
other public runtime, source evidence and old matching/runtime pins stay exact.
The backup's archive listing was validated; this milestone does not claim a
new isolated restore proof for that fresh backup.
