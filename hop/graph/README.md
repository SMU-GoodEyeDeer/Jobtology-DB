# Load accepted PostgreSQL snapshots into Neo4j

These workflows use native Hop transforms/actions, parameter-bound PostgreSQL queries and
Neo4j Cypher. They read accepted `ingestion` snapshots without fetching APIs, running Python
or JavaScript, or calling an LLM. PostgreSQL remains the source of record.

The workflows and `graph-local` run configurations are installed in the live Hop server's
persistent default project. On 2026-09-11, accepted source snapshots were loaded and verified
against the existing Neo4j 2026.06.0 Community instance through `jobtology-neo4j`.

## Run the organization and posting graph

1. Use the saved **Neo4j Connection** named `jobtology-neo4j`. For another installation, configure
   this metadata with its target host, database and credentials, or override `NEO4J_CONNECTION`.
   Keep the private connection metadata out of Git. The existing `jobtology-postgres` connection
   supplies the source rows.
2. Open **`${PROJECT_HOME}/graph/alio_jobs.hwf`**.
3. Select **graph-local**, use **Basic** logging, and leave `JOB_RUN_ID=LATEST` or supply an exact
   READY JOB-ALIO run ID.

The workflow pins that jobs snapshot and its recorded ALIO employer dependency. It loads the
organization graph first, then the jobs graph, verifying each batch before marking it READY.
It does not select a newer organization snapshot independently of the jobs dependency.

| Parameter | Default | Meaning |
|---|---|---|
| `JOB_RUN_ID` | `LATEST` | Latest accepted JOB-ALIO snapshot, or an explicit jobs run ID. |
| `NEO4J_CONNECTION` | `jobtology-neo4j` | Name of the private Hop Neo4j connection metadata. |

For another source or a retry of one batch, open **`graph/load_snapshot.hwf`** with the same
run configuration and supply **`RUN_ID=<accepted PostgreSQL run ID>`**. It supports all source
types exposed by `ingestion.graph_record` and `ingestion.graph_reference`. All six source types have live Hop ingestion workflows.

The [source scheduler](../operations/README.md) refreshes and exports due sources. For a manual
graph-only retry, reuse the same accepted PostgreSQL run; this makes no provider requests.

## What is stored

The graph uses dedicated labels, separate from the existing Python loader's `Ingest*` labels:

| Label / relationship | Meaning |
|---|---|
| `ingestionBatch` | One PostgreSQL run, source, graph state, source date and verification timestamp. |
| `ingestionRecord` | One historical source row, with its source ID, kind, name and selected structured facts. |
| `organization` / `jobPosting` | A shared organization or posting identity, with its real name/title. |
| `occupation` / `ncsCompetency` | An NCS occupation or full-version competency unit, with its name. |
| `qualification` | A credential identity when qualification/schedule sources are loaded. |
| `entity` | Additional common label on business identities for ID uniqueness and generic lookup. |
| `HAS_RECORD` | Connects a batch to its source records. |
| `REFERS_TO {field: ...}` | Connects a source record to the identities named by its fields. |

Both posting representations are retained: `<posting_id>:list` and `<posting_id>:detail`.
They refer to the same posting identity and employer identity. The selected organization's source
record refers to that employer identity too. This preserves the original staging graph contract;
it is not a new canonical serving model or a skills-extraction graph. NCS records refer to their
competency unit and occupation. These source loaders do not infer job-to-NCS matches. The separate [LLM workflows](../llm/README.md)
can publish reviewed `jobEnrichment` nodes and `ALIGNS_WITH_NCS` relationships with duty evidence.

Full source objects and long eligibility, preference and selection text stay in PostgreSQL.
`facts_json` follows the field exclusions in `ingestion.graph_record`. Names and source facts
belong to the snapshot record. An entity keeps its stable ID, kind and code, plus mutable display
metadata: `name`, `title` for postings, `name_source_run_id` and `name_source_record_id`.

Names are selected from accepted, non-SMOKE PostgreSQL snapshots without validation issues.
The loader prefers a nonempty name, then the authoritative ALIO/NCS/qualification source, then
that source's newest accepted run. Posting detail wins over list within the same run. Stable
tie-breakers make the selection repeatable. A source without a name falls back to `kind code`;
none of the currently loaded entities need this fallback. Replaying an old graph batch therefore
cannot replace a newer accepted name with an older one. Display names can come from a newer
accepted PostgreSQL snapshot than the historical graph record being viewed; use the record's
own name/facts for historical analysis.

Batch `source_created_at` preserves the PostgreSQL run timestamp in UTC. `batch_date` is its
calendar date in **Asia/Seoul**, and `name` includes the local timestamp and source. These values
come from source ingestion, not from the time a graph retry happens.

The accepted PostgreSQL inputs contain:

| Input | Source records | Identity references |
|---|---:|---:|
| 355 ALIO organizations | 355 | 355 |
| 506 JOB-ALIO postings, list plus detail | 1,012 | 2,024 |
| 15,520 NCS competencies | 15,520 | 31,040 |
| Total | 16,887 | 33,419 |

These reference **17,475 distinct entities**: 355 organizations, 506 postings, 15,520 versioned
competencies and 1,094 occupations. A graph containing all three snapshots has **34,365 nodes**
and **50,306 relationships**, including three batch nodes and all historical source records.
These are snapshot-specific verification counts, not hard-coded source-size requirements.

## Verification and repeat runs

`load_snapshot.hwf` executes these stages sequentially:

1. Require a READY, non-SMOKE PostgreSQL run with no validation issues.
2. Inspect uniqueness constraints and create only missing constraints.
3. Upgrade former labels in place and retire their matching legacy constraints, if present.
4. Create or reopen the graph batch in LOADING state, with its original source date.
5. Merge source records and references; assign semantic entity labels and readable names.
6. Verify every record property, reference triple, entity kind/code/label and display-name origin.
7. Verify batch date/name and total membership, rejecting extra rows/references and handling empty sets.
8. Mark the graph batch READY only after all checks succeed.

The loader uses parameter-bound Cypher, one statement per incoming row, with no UNWIND or
script transform. The run configurations disable row sampling and execution-data capture.

`MERGE` makes repeated loads of the same snapshot idempotent. Record facts and stable identity
kind/code are set on creation and then verified, so a conflicting stored value causes failure.
Entity names are refreshed from accepted source facts and then independently checked by the workflow.
A new PostgreSQL run creates a new graph batch and record set; stable identities remain shared.
Historical batches are retained. Always select an intended READY batch when querying facts.

If Neo4j fails, PostgreSQL remains READY. The workflow marks a LOADING graph batch FAILED when
the graph is reachable; a connection outage can leave it LOADING. Inspect and correct the graph
problem, then rerun the same `RUN_ID`. No graph error requires refetching an API. The two-source
wrapper is sequential: if organization loading succeeds and jobs loading fails, the verified
organization batch stays READY and the jobs batch can be retried independently.

Hop 2.19's Neo4j Cypher transform treats the information notification produced by an existing
`CREATE CONSTRAINT ... IF NOT EXISTS` as an error. The executable workflow therefore uses
`SHOW CONSTRAINTS` first. It verifies the label/property uniqueness definition, skips a matching
constraint, and rejects an incompatible use of its intended constraint name. Run one writer per
instance at a time; shared entity display metadata and label/constraint upgrades can touch
multiple snapshots. This workflow does not implement a distributed writer lock.

## Labels and Browser captions

The loader automatically replaces `HopMigrationBatch` with `ingestionBatch`, `HopMigrationRecord`
with `ingestionRecord`, and `HopMigrationIdentity` with `entity` plus its business label. This is
an in-place relabel: node IDs, relationships and source facts are preserved. New uniqueness
constraints use `ingestion_v2_*_id`. Only the three matching old `ingestion_*_id` constraints
are retired. Nodes belonging to the Python loader are outside this migration.

The text drawn inside a node is a **caption**, chosen by the graph viewer. The database stores
readable properties; each Neo4j Browser profile chooses which property to display.

1. Run **`:style`** in Neo4j Browser.
2. Download the current style first if you want to keep a copy of your custom styling.
3. Upload [`browser-style.grass`](browser-style.grass) from this directory.
4. Re-run a small graph query below. Organization/occupation/competency captions use `name`,
   postings use `title`, and batches use `batch_date`.

Alternatively, select each node label in the result overview and click the desired **Caption**
property. All business nodes also have `name`, so choosing it for the common `entity` label works
too. For colors, put the business label ahead of `entity` in the result's label styling order.
The file is saved in the persistent Hop project as well as this repo. It does not automatically
change existing browser profiles. See the official
[Browser styling guide](https://neo4j.com/docs/browser/operations/browser-styling/).

## Inspect the graph

Check batch states and source-record counts:

```cypher
MATCH (b:ingestionBatch)
OPTIONAL MATCH (b)-[:HAS_RECORD]->(r:ingestionRecord)
RETURN b.id AS run_id, b.source_id AS source, b.state AS state,
       count(r) AS source_records
ORDER BY source, run_id;
```

For the currently accepted pair, inspect each posting's official employer while selecting one
representation per posting:

```cypher
MATCH (:ingestionBatch {
  id: '77ccb77b-3afc-4965-8ce5-efd687304954', state: 'READY'
})-[:HAS_RECORD]->(posting:ingestionRecord)
MATCH (:ingestionBatch {
  id: 'cb6db580-6cdb-4015-8fd6-2d7f682e460a', state: 'READY'
})-[:HAS_RECORD]->(organization:ingestionRecord)
MATCH (posting)-[:REFERS_TO {field: 'organization_code'}]->(employer:entity)
      <-[:REFERS_TO {field: 'code'}]-(organization)
WHERE posting.source_record_id ENDS WITH ':detail'
RETURN posting.name AS posting, organization.name AS employer,
       employer.code AS organization_code
ORDER BY employer, posting;
```

For a visual example of postings and employers, including the source record that provides the
link:

```cypher
MATCH (:ingestionBatch {id: '77ccb77b-3afc-4965-8ce5-efd687304954', state: 'READY'})
      -[:HAS_RECORD]->(r:ingestionRecord)
WHERE r.source_record_id ENDS WITH ':detail'
WITH r ORDER BY r.id LIMIT 10
MATCH p=(posting:jobPosting)<-[:REFERS_TO {field: 'posting_id'}]-(r)
        -[:REFERS_TO {field: 'organization_code'}]->(employer:organization)
RETURN p;
```

For NCS competencies and their occupations:

```cypher
MATCH (:ingestionBatch {id: 'a32170ed-7485-4e31-82d3-ed48b3398946', state: 'READY'})
      -[:HAS_RECORD]->(r:ingestionRecord)
WITH r ORDER BY r.id LIMIT 20
MATCH p=(unit:ncsCompetency)<-[:REFERS_TO {field: 'code'}]-(r)
        -[:REFERS_TO {field: 'occupation_code'}]->(occupation:occupation)
RETURN p;
```

The workflow files and `metadata/{pipeline,workflow}-run-configuration/graph-local.json` files
belong in the persistent Hop project. Their backing Docker volume survives a container
replacement. The Neo4j database has its own persistence and backup requirements.

## Local verification

The native Hop 2.19.0 runner was tested against disposable PostgreSQL 18 and Neo4j 5.26 Community
on 2026-09-11, using copies of the accepted ALIO and JOB-ALIO snapshots. Both graph batches
became READY. An independent read-back comparison checked all 1,367 records and their properties,
all 2,379 reference triples and identity properties, and 861 distinct identities, with zero
differences. The graph tests made no provider requests and did not modify the source snapshots.

Repeating the complete workflow with `JOB_RUN_ID=LATEST` preserved the same graph. Additional
checks rejected a changed record property, a changed identity code, an extra batch record and
a duplicate reference. A failed batch became READY after repairing the conflicting property
and retrying the same run. A confirmed empty snapshot produced a READY batch with zero records;
a SMOKE snapshot was rejected before creating any graph batch.

The v2 label/caption update was tested against a copy of the existing live graph. It preserved
all 2,230 original node IDs and 3,746 relationship IDs, all source facts and stable identity
properties, while leaving an unrelated test node unchanged. The full NCS graph load then
completed in about 317 seconds. Independent comparison across all three snapshots checked
16,887 records, 33,419 references, 17,475 entity names and their origins, semantic labels and
source batch dates, with zero differences and no fallback names. Focused checks rejected an
incorrect entity caption, missing business label and wrong batch date, and accepted the repaired
values using the same native verification pipelines. Changed source facts and identity codes,
extra membership and duplicate references also failed as intended; a repaired FAILED graph
batch became READY again without changing PostgreSQL. A confirmed-empty snapshot completed
with a dated READY batch and zero records; a SMOKE snapshot was rejected before any graph write.

## Live verification

On 2026-09-11, the native Hop 2.19.0 workflow loaded these exact PostgreSQL snapshots into the
existing Neo4j 2026.06.0 Community instance:

| Source | PostgreSQL run / graph batch | Graph state |
|---|---|---|
| ALIO organizations | `cb6db580-6cdb-4015-8fd6-2d7f682e460a` | READY |
| JOB-ALIO postings | `77ccb77b-3afc-4965-8ce5-efd687304954` | READY |

The first load took about 24 seconds. An independent read-back comparison found zero record or
reference differences against PostgreSQL: 1,367 records, 2,379 identity references and 861
identities. The employer query above resolved all 506 postings to 130 hiring organizations
within the full set of 355 organizations. Both source snapshots remained READY with zero
PostgreSQL validation issues.

A second full graph load, using the saved workflow's default connection and the same jobs run,
took about 12 seconds. Independent read-back returned identical record properties, identity
references, batch states, constraints and employer matches, with no duplicates. Graph load and
verification timestamps are refreshed by a successful rerun.

Execution logs are saved in the persistent project:

- `${PROJECT_HOME}/data/graph-logs/20260911-live-first.log`
- `${PROJECT_HOME}/data/graph-logs/20260911-live-repeat.log`

Connection credentials remain in the existing private Hop metadata; the workflow files contain
only its name. See the [migration guide](../../docs/hop-real-data-guide.md#5-load-neo4j-from-the-accepted-postgresql-run)
for all six source workflows and their [refresh automation](../operations/README.md).

## Live NCS and label update (2026-09-11)

The v2 workflow relabeled the existing ALIO/JOB-ALIO graph and populated readable entity names
and source dates. All 2,230 original node IDs and 3,746 relationship IDs were preserved, and
independent comparison found zero source-fact, reference, name or date differences. There are
no remaining nodes carrying a `HopMigration*` label. The native pair workflow took about 74 seconds.

It then loaded **`a32170ed-7485-4e31-82d3-ed48b3398946`** into Neo4j in about **137 seconds**:
15,520 NCS records, 31,040 references, 15,520 named `ncsCompetency` entities and 1,094 named
`occupation` entities. The NCS graph batch is READY. This source adds no links to job postings.

Independent live read-back compared all three sources: all **16,887 records and their properties**, **33,419
reference triples**, all **17,475 entity names and their source references**, semantic labels
and batch dates. Every comparison returned zero differences, all three PostgreSQL and graph
batches remained READY, and every entity had a source-provided name.

A second load of the same NCS run completed in about **83 seconds**. Independent read-back of
the complete graph was identical, including node/relationship IDs, facts, names and dates;
only the batch's graph load/verification timestamps were refreshed. It created no duplicate
nodes or relationships and made no provider requests.

## Six-source graph and scheduled recovery (2026-09-11)

The live graph now also includes qualification mappings, Q-Net exam sessions and
career paths. All six accepted snapshots were independently compared: 29,894 source
records, 59,377 references and 30,387 named entities matched PostgreSQL, with zero
differences. All prior node/relationship IDs were preserved. Repeating the three
pre-existing graph loads through the scheduler left the complete graph unchanged
apart from load/verification timestamps and made no provider requests.

Use [the operations workflows](../operations/README.md) to fetch and load both
databases together, or `operations/export_pending.hwf` to retry an accepted run's
graph load. The [verification report](../../docs/hop-migration/live-status.md) lists
the exact source run IDs. Posting-to-competency matching remains a later phase.

The previous workflow files and a logical export of the graph before relabeling are retained in
`${PROJECT_HOME}/data/backups/20260911-graph-labels-v2/`. This export is migration evidence;
continue to back up the Neo4j data volume for database recovery. Updated workflow files and
`browser-style.grass` are installed in the persistent Hop project. Applying the style to an
individual Browser profile is the one-time UI step described above.

V2 execution logs are in `${PROJECT_HOME}/data/graph-logs/`:

- `20260911-v2-pair-first.log`
- `20260911-v2-ncs-first.log`
- `20260911-v2-ncs-repeat.log`
