-- Review and run separately as the database owner, connected to jobtology.
-- This file contains no password and is never executed by the dashboard.
-- Use a fresh, dedicated role; do not grant membership in writer/owner roles.
BEGIN;
CREATE ROLE jobtology_admin_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION;
GRANT CONNECT ON DATABASE jobtology TO jobtology_admin_reader;
GRANT USAGE ON SCHEMA ingestion TO jobtology_admin_reader;
GRANT SELECT (source_id, enabled, interval_seconds)
  ON ingestion.refresh_policy TO jobtology_admin_reader;
GRANT SELECT (run_id, source_id, mode, state, created_at, completed_at)
  ON ingestion.run TO jobtology_admin_reader;
GRANT SELECT (run_id, state, record_count)
  ON ingestion.source_graph_projection TO jobtology_admin_reader;
GRANT SELECT (execution_id, source_id, operation, started_at, finished_at, exit_code)
  ON ingestion.refresh_execution TO jobtology_admin_reader;
ALTER ROLE jobtology_admin_reader SET default_transaction_read_only = on;
ALTER ROLE jobtology_admin_reader SET statement_timeout = '5s';
ALTER ROLE jobtology_admin_reader SET lock_timeout = '4s';
COMMIT;
-- Set the password interactively with psql: \password jobtology_admin_reader
-- Review inherited PUBLIC privileges separately under the database's existing policy.
