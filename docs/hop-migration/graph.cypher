// Run each statement in its indicated native Neo4j Cypher transform.
// Constraint setup: once, one statement per invocation, no incoming parameters.
CREATE CONSTRAINT ingestion_batch_id IF NOT EXISTS
FOR (n:HopMigrationBatch) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ingestion_record_id IF NOT EXISTS
FOR (n:HopMigrationRecord) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT ingestion_identity_id IF NOT EXISTS
FOR (n:HopMigrationIdentity) REQUIRE n.id IS UNIQUE;

// 1. Begin batch. Input: a single READY PostgreSQL run row, even for zero records.
// Parameters: run_id, source_id (String).
MERGE (b:HopMigrationBatch {id: $run_id})
ON CREATE SET b.source_id = $source_id
SET b.state = 'LOADING', b.serving_scope = 'STAGING';

// 2. One row from ingestion.graph_record.
// Parameters: id, run_id, source_id, source_record_id, kind, name, facts_json (String).
MATCH (b:HopMigrationBatch {id: $run_id})
MERGE (r:HopMigrationRecord {id: $id})
ON CREATE SET r.source_id = $source_id, r.source_record_id = $source_record_id,
              r.kind = $kind, r.name = $name, r.facts_json = $facts_json
MERGE (b)-[:HAS_RECORD]->(r);

// 3. One row from ingestion.graph_reference.
// Parameters: record_id, identity_id, kind, code, field (String).
MATCH (r:HopMigrationRecord {id: $record_id})
MERGE (i:HopMigrationIdentity {id: $identity_id})
ON CREATE SET i.kind = $kind, i.code = $code
MERGE (r)-[:REFERS_TO {field: $field}]->(i);

// 4a. Compare IDs AND properties to graph_record for the SAME run; counts are insufficient.
// Parameter: run_id (String).
MATCH (:HopMigrationBatch {id: $run_id})-[:HAS_RECORD]->(r:HopMigrationRecord)
RETURN r.id AS id, r.source_id AS source_id, r.source_record_id AS source_record_id,
       r.kind AS kind, r.name AS name, r.facts_json AS facts_json
ORDER BY id;

// 4b. Compare these triples to graph_reference(record_id, field, identity_id).
// Parameter: run_id (String).
MATCH (:HopMigrationBatch {id: $run_id})-[:HAS_RECORD]->(r:HopMigrationRecord)
      -[ref:REFERS_TO]->(i:HopMigrationIdentity)
RETURN r.id AS record_id, ref.field AS field, i.id AS identity_id
ORDER BY record_id, field, identity_id;

// 4c. Execute ONLY on success of BOTH comparisons, including explicit empty-set handling.
// Parameter: run_id (String).
MATCH (b:HopMigrationBatch {id: $run_id})
SET b.state = 'READY';
