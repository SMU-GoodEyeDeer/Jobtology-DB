// Illustrative projection statements; run hop/graph/*.hwf for the complete native loader.
// It includes acceptance checks, exact verification and failure handling.
// Constraint setup below works in Neo4j Browser, one statement per invocation.
// Hop 2.19 treats an existing-constraint information notification as an error, so the
// executable constraints.hpl inspects SHOW CONSTRAINTS before creating missing constraints.
CREATE CONSTRAINT ingestion_v2_batch_id IF NOT EXISTS
FOR (n:ingestionBatch) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ingestion_v2_record_id IF NOT EXISTS
FOR (n:ingestionRecord) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ingestion_v2_identity_id IF NOT EXISTS
FOR (n:entity) REQUIRE n.id IS UNIQUE;

// The workflow upgrades the former HopMigration* labels in place and retires their
// matching old constraints. Do not delete/recreate the old graph to rename its labels.

// 1. Begin batch. Input: a single READY PostgreSQL run row, even for zero records.
// Parameters: run_id, source_id, source_created_at, batch_date, batch_name (String).
// Dates come from ingestion.run.created_at; batch_date/name use Asia/Seoul.
MERGE (b:ingestionBatch {id: $run_id})
ON CREATE SET b.source_id = $source_id
SET b.state = 'LOADING', b.serving_scope = 'STAGING',
    b.source_created_at = $source_created_at, b.batch_date = $batch_date,
    b.name = $batch_name, b.loader_version = 'hop-graph-v2';

// 2. One row from ingestion.graph_record.
// Parameters: id, run_id, source_id, source_record_id, kind, name, facts_json (String).
MATCH (b:ingestionBatch {id: $run_id})
MERGE (r:ingestionRecord {id: $id})
ON CREATE SET r.source_id = $source_id, r.source_record_id = $source_record_id,
              r.kind = $kind, r.name = $name, r.facts_json = $facts_json
MERGE (b)-[:HAS_RECORD]->(r);

// 3. One row from ingestion.graph_reference.
// Parameters: record_id, identity_id, kind, code, field (String).
MATCH (r:ingestionRecord {id: $record_id})
MERGE (i:entity {id: $identity_id})
ON CREATE SET i.kind = $kind, i.code = $code
FOREACH (_ IN CASE WHEN i.kind = 'Organization' THEN [1] ELSE [] END | SET i:organization)
FOREACH (_ IN CASE WHEN i.kind = 'JobPosting' THEN [1] ELSE [] END | SET i:jobPosting)
FOREACH (_ IN CASE WHEN i.kind = 'Occupation' THEN [1] ELSE [] END | SET i:occupation)
FOREACH (_ IN CASE WHEN i.kind = 'Competency' THEN [1] ELSE [] END | SET i:ncsCompetency)
FOREACH (_ IN CASE WHEN i.kind = 'Qualification' THEN [1] ELSE [] END | SET i:qualification)
MERGE (r)-[:REFERS_TO {field: $field}]->(i);

// 3b. load_entity_names.hpl selects a readable name and its source from accepted
// PostgreSQL snapshots. Prefer the authoritative source, then its newest accepted run.
// This is mutable display metadata; the source record facts above stay immutable.
// Parameters: identity_id, kind, code, entity_name, entity_title (nullable),
//             name_source_run_id, name_source_record_id (String).
MATCH (i:entity {id: $identity_id}) WHERE i.kind = $kind AND i.code = $code
SET i.name = $entity_name, i.title = $entity_title,
    i.name_source_run_id = $name_source_run_id,
    i.name_source_record_id = $name_source_record_id;

// 4a. Compare IDs AND properties to graph_record for the SAME run; counts are insufficient.
// Parameter: run_id (String).
MATCH (:ingestionBatch {id: $run_id})-[:HAS_RECORD]->(r:ingestionRecord)
RETURN r.id AS id, r.source_id AS source_id, r.source_record_id AS source_record_id,
       r.kind AS kind, r.name AS name, r.facts_json AS facts_json
ORDER BY id;

// 4b. Compare these triples to graph_reference(record_id, field, identity_id).
// Parameter: run_id (String).
MATCH (:ingestionBatch {id: $run_id})-[:HAS_RECORD]->(r:ingestionRecord)
      -[ref:REFERS_TO]->(i:entity)
RETURN r.id AS record_id, ref.field AS field, i.id AS identity_id
ORDER BY record_id, field, identity_id;

// Also compare semantic labels, entity names/provenance and batch dates, and reject
// extra membership. verify_entity_names.hpl and verify_totals.hpl perform those checks.
// 4c. Execute ONLY after ALL comparisons succeed, including explicit empty-set handling.
// Parameter: run_id (String).
MATCH (b:ingestionBatch {id: $run_id})
SET b.state = 'READY';

// Browser captions are a UI setting. Import hop/graph/browser-style.grass with :style,
// or choose name for the business labels, title for jobPosting and batch_date for batches.
