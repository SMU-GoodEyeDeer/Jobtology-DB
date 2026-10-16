"""Network-none atomic admission guards, independent of source normalization.

Source/repair validators are stubbed only in this budget unit fixture. The
separate native fixture verifies real frozen inputs and provider responses.
"""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "hop/llm/tests"))
import jobkorea_linking as f  # noqa: E402


def main():
    checks = []

    def expect(ok, label):
        assert ok, label
        checks.append(label)

    def batch(name, workers, daily=1):
        settings = dict(metadata_scope="NCS_OCCUPATION_INFERENCE_V1", execute_requests="Y",
                        max_requests=20, max_cost_usd=1, daily_budget_usd=daily,
                        request_reserve_usd=0.005)
        f.sql(f"INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state) "
              f"VALUES({f.quote(name)},'ENRICH','jobs','ncs',repeat('a',64),{f.js(settings)},'RUNNING')")
        for index in range(8):
            aid = name + str(index)
            f.sql(f"INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal) "
                  f"VALUES({f.quote(aid)},{f.quote(name)},{f.quote(aid)},'{{}}',repeat('b',64),{index});"
                  f"INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state) "
                  f"VALUES({f.quote(aid)},{f.quote(name)},{f.quote(aid)},'categorize',repeat('c',64),'{{}}','PLANNED')")
        return f.sql(f"SELECT enrichment.start_metadata_occupation_execution({f.quote(name)},{workers})->>'execution_token'")

    def race(rows):
        with ThreadPoolExecutor(max_workers=16) as pool:
            return list(pool.map(lambda row: f.sql(
                f"SELECT enrichment.admit_metadata_occupation_request({f.quote(row[0])},{f.quote(row[1])}::uuid)"), rows))

    try:
        f.command(["docker", "run", "-d", "--pull", "never", "--network", "none", "--name", f.NAME,
                   "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:18-alpine"])
        for _ in range(150):
            try:
                if "PostgreSQL init process complete" in f.command(["docker", "logs", f.NAME]) and f.sql("SELECT 1") == "1":
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable admission database did not become ready")
        for path in ("docs/hop-migration/schema.sql", "docs/hop-migration/checks.sql",
                     "docs/hop-migration/operations.sql", "hop/llm/sql/001_schema.sql",
                     "hop/llm/sql/003_planning.sql"):
            f.install(path)
        f.sql("CREATE SCHEMA retention;CREATE FUNCTION retention.gate() RETURNS void LANGUAGE sql AS $$ SELECT NULL::void $$;"
              "CREATE FUNCTION retention.freeze_writes() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM retention.gate();RETURN NULL;END $$;"
              "CREATE FUNCTION enrichment.verify_item_input(text) RETURNS void LANGUAGE sql AS $$ SELECT NULL::void $$;"
              "CREATE FUNCTION enrichment.repair_reasons_v6(text) RETURNS jsonb LANGUAGE sql AS $$ SELECT NULL::jsonb $$;"
              "CREATE FUNCTION enrichment.revision_input_issue(text) RETURNS text LANGUAGE sql AS $$ SELECT NULL::text $$;"
              "INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state) VALUES "
              "('jobs','jobkorea','FULL','SYNTHETIC_BUDGET_UNIT','READY'),"
              "('ncs','ncs_competency','FULL','SYNTHETIC_BUDGET_UNIT','READY')")
        f.install("hop/llm/sql/031_metadata_occupation_workers.sql")
        expect(f.sql("SELECT count(*) FROM pg_trigger WHERE tgname='retention_freeze' AND tgtype=62 AND tgenabled='O'") == "4",
               "all-four-retention-fences-include-truncate")
        token = batch("capacity", 4)
        rows = [("capacity" + str(i), token) for i in range(8)]
        replies = race(rows)
        expect(replies.count("t") == 4, "atomic-capacity-four-of-eight")
        expect(f.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='capacity' AND state='PLANNED'") == "4", "capacity-withheld-remain-planned")
        f.sql("UPDATE enrichment.attempt SET state='VALIDATED',cost_usd=0.0002 WHERE batch_id='capacity' AND state='RESERVED'")
        expect(race([row for row, reply in zip(rows, replies, strict=True) if reply == "f"]).count("t") == 4,
               "capacity-released-admits-remaining-planned")
        f.sql("UPDATE enrichment.attempt SET state='VALIDATED',cost_usd=0.0002 WHERE batch_id='capacity' AND state='RESERVED'")
        first = batch("daily-a", 8, daily=0.0126)
        second = batch("daily-b", 8, daily=0.0126)
        replies = race([("daily-" + suffix + str(i), token) for i in range(8) for suffix, token in (("a", first), ("b", second))])
        expect(replies.count("t") == 2, "global-daily-budget-atomic-across-two-batches")
        expect(f.sql("SELECT sum(enrichment.accounted_cost(state,cost_usd,reserved_usd))<=0.0126 FROM enrichment.attempt WHERE reserved_at IS NOT NULL") == "t",
               "global-daily-budget-counts-all-owned-reservations")
        f.sql("UPDATE enrichment.attempt SET state='VALIDATED',cost_usd=0.0002 WHERE state='RESERVED'")
        token = batch("one", 1)
        expect(race([("one" + str(i), token) for i in range(8)]).count("t") == 1, "default-one-worker-bounds-one-inflight")
        f.sql("UPDATE enrichment.attempt SET state='VALIDATED',cost_usd=NULL WHERE batch_id='one' AND state='RESERVED'")
        expect(race([("one" + str(i), token) for i in range(8)]).count("t") == 0, "unknown-validated-cost-stops-every-new-admission")
        expect(f.sql("SELECT enrichment.accounted_cost(state,cost_usd,reserved_usd) FROM enrichment.attempt WHERE batch_id='one' AND reserved_at IS NOT NULL") == "0.005",
               "unknown-validated-cost-retains-full-hold")
        expect(f.sql(f"SELECT enrichment.admit_metadata_occupation_request('capacity0',{f.quote(token)}::uuid)") == "f",
               "token-cannot-claim-another-batch")
        for workers in (0, 9):
            f.reject(f"SELECT enrichment.start_metadata_occupation_execution('one',{workers})", "INVALID_METADATA_WORKERS")
            checks.append("invalid-workers-" + str(workers))
        token = batch("never", 4)
        expect(f.sql(f"SELECT enrichment.end_metadata_occupation_execution({f.quote(token)}::uuid)->>'state'") == "STOPPED",
               "dispatcher-with-never-sent-planned-is-stopped")
        for table in ("metadata_occupation_execution", "metadata_occupation_request_owner",
                      "metadata_occupation_execution_stop", "metadata_occupation_execution_end"):
            f.reject("TRUNCATE enrichment." + table + " CASCADE", "METADATA_OCCUPATION_EXECUTION_IS_APPEND_ONLY")
            checks.append("truncate-rejected-" + table)
        print(json.dumps({"status": "PASSED_ATOMIC_METADATA_ADMISSION", "checks": checks,
                          "network": "none", "paid_calls": 0, "production_writes": False}))
    finally:
        subprocess.run(["docker", "rm", "-fv", f.NAME], capture_output=True, check=False)


if __name__ == "__main__":
    main()
