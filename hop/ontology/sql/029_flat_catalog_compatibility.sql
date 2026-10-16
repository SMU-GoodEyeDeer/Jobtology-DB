-- Additive catalogue approval for the versioned flat Neo4j projection.
-- Initial cutover writes none of the historical approval/load/pointer rows.
BEGIN;

CREATE TABLE IF NOT EXISTS catalog.flat_catalog_approval (
 approval_id bigint PRIMARY KEY,
 release_id text NOT NULL REFERENCES ontology.corpus_release,
 database_id text NOT NULL,
 load_id text NOT NULL REFERENCES ontology.flat_graph_load,
 source_manifest_hash text NOT NULL,
 flat_contract_version text NOT NULL,
 flat_manifest_hash text NOT NULL,
 actor text NOT NULL CHECK(length(btrim(actor))>0),
 reason text NOT NULL CHECK(length(btrim(reason))>0),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS catalog.flat_catalog_active_release (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 approval_id bigint NOT NULL REFERENCES catalog.flat_catalog_approval
);
REVOKE ALL ON catalog.flat_catalog_approval,catalog.flat_catalog_active_release FROM PUBLIC;
CREATE OR REPLACE TRIGGER flat_catalog_approval_immutable BEFORE UPDATE OR DELETE
 ON catalog.flat_catalog_approval FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
CREATE OR REPLACE TRIGGER flat_catalog_approval_no_truncate BEFORE TRUNCATE
 ON catalog.flat_catalog_approval FOR EACH STATEMENT EXECUTE FUNCTION catalog._protect_audit_truncate();

-- Historical source inventory remains the approval's content contract. The
-- separate flat proof certifies its physical representation, never a new export.
CREATE OR REPLACE FUNCTION catalog._source_approval_integrity(id text,source_hash text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r ontology.corpus_release%ROWTYPE; a catalog.integrity_attestation%ROWTYPE;
BEGIN
 SELECT * INTO r FROM ontology.corpus_release WHERE release_id=id;
 IF r.state IN ('REVOKED','FAILED') THEN RAISE EXCEPTION 'CATALOG_RELEASE_UNAVAILABLE'; END IF;
 SELECT * INTO a FROM catalog.integrity_attestation WHERE release_id=id;
 IF r.state IS DISTINCT FROM 'PREPARING' OR a.generation IS DISTINCT FROM 1 OR
  a.contract_version IS DISTINCT FROM 'hop-catalog-source-v1' OR a.mode IS DISTINCT FROM 'SOURCE_ONLY' OR
  NOT EXISTS(SELECT 1 FROM ontology.catalog_source_mode m WHERE m.release_id=id AND m.mode=a.mode
   AND m.contract_version='hop-ontology-graph-source-v1') OR
  a.manifest_hash IS DISTINCT FROM r.manifest_hash OR a.manifest_hash IS DISTINCT FROM source_hash OR
  a.observation_hash IS DISTINCT FROM (SELECT manifest_hash FROM ontology.observation_membership WHERE release_id=id) OR
  a.node_count IS DISTINCT FROM (r.manifest->>'nodes')::bigint OR
  a.edge_count IS DISTINCT FROM (r.manifest->>'edges')::bigint OR
  a.node_hash IS DISTINCT FROM r.manifest->>'node_hash' OR a.edge_hash IS DISTINCT FROM r.manifest->>'edge_hash'
 THEN RAISE EXCEPTION 'CATALOG_APPROVAL_STALE'; END IF;
END $$;

CREATE OR REPLACE FUNCTION catalog._approved_release(release_choice text DEFAULT NULL)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE selected record; latest ontology.graph_load%ROWTYPE;
 current_flat ontology.flat_graph_projection%ROWTYPE;
BEGIN
 -- A future flat approval takes precedence. Initial migration creates no such
 -- row and continues to use the unchanged historical approval and pointer.
 SELECT a.release_id,a.database_id,a.load_id,a.source_manifest_hash AS manifest_hash,
  a.flat_contract_version,a.flat_manifest_hash,true AS flat_approval
 INTO selected FROM catalog.flat_catalog_active_release p
 JOIN catalog.flat_catalog_approval a USING(approval_id) WHERE p.singleton;
 IF NOT FOUND THEN
  SELECT a.release_id,a.database_id,a.load_id,a.manifest_hash,
   NULL::text AS flat_contract_version,NULL::text AS flat_manifest_hash,false AS flat_approval
  INTO selected FROM catalog.catalog_active_release p
  JOIN catalog.catalog_approval a USING(approval_id) WHERE p.singleton;
 END IF;
 IF NOT FOUND OR (nullif(btrim(release_choice),'') IS NOT NULL AND selected.release_id<>release_choice)
 THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_APPROVED'; END IF;
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'CATALOG_REQUIRES_READ_COMMITTED'; END IF;
 PERFORM catalog._source_approval_integrity(selected.release_id,selected.manifest_hash);
 IF selected.flat_approval OR EXISTS(SELECT 1 FROM ontology.flat_graph_load WHERE database_id=selected.database_id) THEN
  -- Also rejects an unfinished/failed latest load, even if an older proof was
  -- VERIFIED. Historical approval.load_id continues to identify its old load.
  PERFORM ontology.require_flat_graph_projection(selected.release_id,selected.database_id);
  SELECT * INTO STRICT current_flat FROM ontology.flat_graph_projection WHERE release_id=selected.release_id;
  IF current_flat.source_manifest_hash IS DISTINCT FROM selected.manifest_hash OR
   (selected.flat_approval AND (current_flat.manifest_hash IS DISTINCT FROM selected.flat_manifest_hash OR
    current_flat.contract_version IS DISTINCT FROM selected.flat_contract_version))
  THEN RAISE EXCEPTION 'CATALOG_APPROVAL_STALE'; END IF;
 ELSE
  -- Before a database has begun its first flat load, retain the exact v1 gate.
  SELECT * INTO latest FROM ontology.graph_load WHERE database_id=selected.database_id
   ORDER BY started_at DESC,load_id DESC LIMIT 1;
  IF (SELECT graph_verified_at FROM ontology.corpus_release WHERE release_id=selected.release_id) IS NULL OR
   latest.load_id IS DISTINCT FROM selected.load_id OR latest.release_id IS DISTINCT FROM selected.release_id OR
   latest.state IS DISTINCT FROM 'VERIFIED' OR latest.finished_at IS NULL OR
   latest.manifest_hash IS DISTINCT FROM selected.manifest_hash OR
   latest.node_count IS DISTINCT FROM (SELECT node_count FROM catalog.integrity_attestation WHERE release_id=selected.release_id) OR
   latest.edge_count IS DISTINCT FROM (SELECT edge_count FROM catalog.integrity_attestation WHERE release_id=selected.release_id)
  THEN RAISE EXCEPTION 'CATALOG_APPROVAL_STALE'; END IF;
 END IF;
 RETURN selected.release_id;
END $$;

CREATE OR REPLACE FUNCTION catalog._attest_flat(id text,database text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r ontology.corpus_release%ROWTYPE; manifest jsonb; observation text;
BEGIN
 PERFORM catalog._lock_release(id);
 PERFORM ontology.require_flat_graph_projection(id,database);
 SELECT * INTO STRICT r FROM ontology.corpus_release WHERE release_id=id;
 IF r.state<>'PREPARING' OR r.manifest_hash IS NULL THEN RAISE EXCEPTION 'CATALOG_RELEASE_NOT_VERIFIED'; END IF;
 PERFORM ontology.check_frozen_sources(id);
 PERFORM ontology.verify_catalog_source_v1(id);
 manifest:=ontology.graph_inventory_manifest(id);
 IF manifest IS DISTINCT FROM r.manifest OR ontology.hash(manifest)<>r.manifest_hash
 THEN RAISE EXCEPTION 'CATALOG_INVENTORY_CHANGED'; END IF;
 SELECT manifest_hash INTO observation FROM ontology.observation_membership WHERE release_id=id;
 IF observation IS NULL THEN RAISE EXCEPTION 'CATALOG_OBSERVATION_MISSING'; END IF;
 INSERT INTO catalog.integrity_attestation(release_id,generation,contract_version,mode,manifest_hash,
  observation_hash,source_inventory_hash,membership_hash,node_count,edge_count,node_hash,edge_hash)
 VALUES(id,1,'hop-catalog-source-v1','SOURCE_ONLY',r.manifest_hash,observation,
  catalog._source_inventory(id),catalog._membership_inventory(id),
  (manifest->>'nodes')::bigint,(manifest->>'edges')::bigint,manifest->>'node_hash',manifest->>'edge_hash')
 ON CONFLICT(release_id) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM catalog.integrity_attestation a WHERE a.release_id=id
  AND a.manifest_hash=r.manifest_hash AND a.observation_hash=observation
  AND a.source_inventory_hash=catalog._source_inventory(id) AND a.membership_hash=catalog._membership_inventory(id))
 THEN RAISE EXCEPTION 'CATALOG_ATTESTATION_CONFLICT'; END IF;
END $$;

CREATE OR REPLACE FUNCTION catalog.approve_flat_catalog_release(id text,database text,actor text,reason text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r ontology.corpus_release%ROWTYPE; projection ontology.flat_graph_projection%ROWTYPE;
 latest ontology.flat_graph_load%ROWTYPE; approved bigint;
BEGIN
 IF nullif(btrim(id),'') IS NULL OR nullif(btrim(database),'') IS NULL OR
  nullif(btrim(actor),'') IS NULL OR nullif(btrim(reason),'') IS NULL
 THEN RAISE EXCEPTION 'CATALOG_APPROVAL_PROVENANCE_REQUIRED'; END IF;
 PERFORM retention.gate();
 PERFORM pg_advisory_xact_lock(71243,19002);
 PERFORM pg_advisory_xact_lock(71243,19001);
 PERFORM catalog._lock_release(id);
 PERFORM ontology.require_flat_graph_projection(id,database);
 SELECT * INTO STRICT r FROM ontology.corpus_release WHERE release_id=id;
 SELECT * INTO STRICT projection FROM ontology.flat_graph_projection WHERE release_id=id;
 SELECT f.* INTO STRICT latest FROM ontology.flat_graph_current c
 JOIN ontology.flat_graph_load f USING(load_id)
 WHERE c.database_id=database AND c.release_id=id;
 PERFORM catalog._attest_flat(id,database);
 -- Re-approving the initial historical catalogue is idempotent and does not
 -- create a new pointer or rewrite its historical approval/load checkpoint.
 IF NOT EXISTS(SELECT 1 FROM catalog.flat_catalog_active_release) THEN
  SELECT a.approval_id INTO approved FROM catalog.catalog_active_release p
  JOIN catalog.catalog_approval a USING(approval_id)
  WHERE p.singleton AND a.release_id=id AND a.database_id=database AND a.manifest_hash=r.manifest_hash;
  IF approved IS NOT NULL THEN RETURN approved; END IF;
 END IF;
 SELECT a.approval_id INTO approved FROM catalog.flat_catalog_active_release p
 JOIN catalog.flat_catalog_approval a USING(approval_id)
 WHERE p.singleton AND a.release_id=id AND a.database_id=database
  AND a.source_manifest_hash=r.manifest_hash AND a.flat_manifest_hash=projection.manifest_hash
  AND a.flat_contract_version=projection.contract_version;
 IF approved IS NULL THEN
  -- Share the existing approval ID sequence; the normal bigint API never
  -- returns an ID ambiguously reused between the historical and flat ledgers.
  approved:=nextval(pg_get_serial_sequence('catalog.catalog_approval','approval_id'));
  INSERT INTO catalog.flat_catalog_approval(approval_id,release_id,database_id,load_id,source_manifest_hash,
   flat_contract_version,flat_manifest_hash,actor,reason)
  VALUES(approved,id,database,latest.load_id,r.manifest_hash,projection.contract_version,projection.manifest_hash,actor,reason);
 END IF;
 INSERT INTO catalog.flat_catalog_active_release(singleton,approval_id) VALUES(true,approved)
 ON CONFLICT(singleton) DO UPDATE SET approval_id=excluded.approval_id;
 RETURN approved;
END $$;

-- Preserve the exact legacy implementation for databases not yet migrated.
DO $$ DECLARE definition text;
BEGIN
 IF to_regprocedure('catalog._approve_legacy_catalog_release(text,text,text,text)') IS NULL THEN
  SELECT pg_get_functiondef('catalog.approve_catalog_release(text,text,text,text)'::regprocedure) INTO definition;
  definition:=replace(definition,'catalog.approve_catalog_release(', 'catalog._approve_legacy_catalog_release(');
  definition:=replace(definition,'approve_catalog_release.release_id','_approve_legacy_catalog_release.release_id');
  definition:=replace(definition,'approve_catalog_release.database_id','_approve_legacy_catalog_release.database_id');
  EXECUTE definition;
 END IF;
END $$;
CREATE OR REPLACE FUNCTION catalog.approve_catalog_release(release_id text,database_id text,actor text,reason text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM ontology.flat_graph_load WHERE flat_graph_load.database_id=approve_catalog_release.database_id)
 THEN RETURN catalog.approve_flat_catalog_release(release_id,database_id,actor,reason); END IF;
 RETURN catalog._approve_legacy_catalog_release(release_id,database_id,actor,reason);
END $$;

REVOKE ALL ON FUNCTION catalog._source_approval_integrity(text,text),catalog._approved_release(text),
 catalog._attest_flat(text,text),catalog.approve_flat_catalog_release(text,text,text,text),
 catalog._approve_legacy_catalog_release(text,text,text,text),catalog.approve_catalog_release(text,text,text,text) FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobtology_catalog_reader') THEN
  REVOKE ALL ON catalog.flat_catalog_approval,catalog.flat_catalog_active_release FROM jobtology_catalog_reader;
  REVOKE ALL ON FUNCTION catalog._source_approval_integrity(text,text),catalog._approved_release(text),
   catalog._attest_flat(text,text),catalog.approve_flat_catalog_release(text,text,text,text),
   catalog._approve_legacy_catalog_release(text,text,text,text),catalog.approve_catalog_release(text,text,text,text) FROM jobtology_catalog_reader;
 END IF;
END $$;
COMMIT;
