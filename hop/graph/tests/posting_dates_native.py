"""Offline native PostgreSQL/Hop/Neo4j identity-date contracts and replay checks."""
# ruff: noqa: E501

import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


native = module("jobkorea_native", ROOT / "hop/ingestions/jobkorea/tests/native.py")
compatibility = module(
    "source_graph_fixture", ROOT / "hop/ingestions/jobkorea/tests/graph_compatibility.py"
)


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def main():
    with tempfile.TemporaryDirectory(prefix="jobtology-posting-dates-") as scratch:
        sample = Path(scratch) / "sample.json"
        sample.write_text(
            json.dumps(
                [
                    {
                        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109422",
                        "job_title": "Backend developer",
                        "company_name": "Example employer",
                    },
                    {
                        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109423",
                        "job_title": "Data engineer",
                        "company_name": "Example employer",
                    },
                ]
            )
        )
        fixture = native.Fixture(sample)
        try:
            fixture.boot()
            fixture.install()
            fixture.expect(
                fixture.sql(
                    "SELECT pg_get_indexdef(indexrelid,1,true)||'|'||pg_get_indexdef(indexrelid,2,true)||'|'||pg_get_expr(indpred,indrelid)||'|'||indisvalid||'|'||indisunique FROM pg_index WHERE indexrelid='ingestion.record_posting_date_lookup'::regclass"
                )
                == "run_id|(normalized ->> 'posting_id'::text)|((normalized ->> 'posting_id'::text) IS NOT NULL)|true|false",
                "additive-nonunique-posting-lookup-index",
            )
            fixture.run("full.hwf", "native-source-and-dates")
            run = fixture.sql("SELECT run_id FROM ingestion.run WHERE source_id='jobkorea'")
            sha = fixture.sql("SELECT file_sha256 FROM ingestion.jobkorea_import")

            def neo(query, label):
                return fixture.command(
                    ["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain", query],
                    label,
                ).splitlines()[-1]

            def dates(jobs):
                return json.loads(
                    fixture.sql(
                        "SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY identity_id),'[]') FROM ingestion.graph_posting_ingestion_dates("
                        + quote(jobs)
                        + ") d"
                    )
                )

            def rejected(statement, error, label):
                output = fixture.command(
                    [
                        "docker",
                        "exec",
                        "-i",
                        fixture.pg,
                        "psql",
                        "-X",
                        "-qAt",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-U",
                        "postgres",
                        "-d",
                        fixture.database,
                    ],
                    label,
                    statement,
                    success=False,
                )
                log = (fixture.logs / (label + ".log")).read_text()
                fixture.expect(error in log, label + "-reason")
                return output

            def fingerprint():
                return fixture.sql("""
SELECT md5(jsonb_build_object(
 'records',(SELECT jsonb_agg(to_jsonb(r) ORDER BY record_id) FROM ingestion.record r),
 'receipts',(SELECT jsonb_agg(to_jsonb(i) ORDER BY run_id) FROM ingestion.jobkorea_import i),
 'inputs',(SELECT jsonb_agg(enrichment.build_jobkorea_input(r.run_id,cs.external_posting_key('jobkorea',r.normalized->>'posting_id')) ORDER BY record_id)
 FROM ingestion.ready_record r WHERE r.source_id='jobkorea'))::text);
""")

            before = fingerprint()
            graph_before = neo(
                "MATCH (n) WHERE NOT n:jobPosting RETURN collect(properties(n)) AS stable",
                "graph-before",
            )
            checkpoints = fixture.sql(
                "SELECT md5(jsonb_agg(to_jsonb(g) ORDER BY run_id)::text) FROM ingestion.graph_export g"
            )
            unknown = dates(run)
            fixture.expect(
                len(unknown) == 2
                and all(d["scraped_at"] is None and d["scraped_at_basis"] is None for d in unknown),
                "unknown-collection-preserved",
            )
            fixture.expect(
                all(
                    d["first_ingested_at"] == d["last_ingested_at"]
                    and d["ingestion_time_basis"] == "JOBKOREA_IMPORTED_AT"
                    and d["latest_ingestion_run_id"] == run
                    for d in unknown
                ),
                "immutable-import-event-projection",
            )
            call = (
                "SELECT ingestion.register_jobkorea_collection_time("
                + ",".join(
                    map(
                        quote,
                        [
                            run,
                            sha,
                            "2026-10-08T02:48:14+09:00",
                            "USER_REPORTED",
                            "user-reported-jobkorea-collection-20261011",
                            "Asia/Seoul",
                        ],
                    )
                )
                + ")"
            )
            fixture.sql(call)
            registered = fixture.sql(
                "SELECT to_jsonb(e)::text FROM ingestion.jobkorea_collection_time_evidence e"
            )
            fixture.sql(call)
            fixture.expect(
                registered
                == fixture.sql(
                    "SELECT to_jsonb(e)::text FROM ingestion.jobkorea_collection_time_evidence e"
                ),
                "collection-evidence-replay-preserves-registration-time",
            )
            fixture.run(
                "../../graph/update_posting_dates.hwf",
                "native-user-reported-backfill",
                extra={"RUN_ID": run},
            )
            expected = "MATCH (p:entity:jobPosting) RETURN count(p)=2 AND all(p IN collect(p) WHERE p.scraped_at=datetime('2026-10-07T17:48:14Z') AND p.scraped_at_basis='USER_REPORTED' AND valueType(p.first_ingested_at)='ZONED DATETIME NOT NULL' AND valueType(p.ingestion_batch_date)='DATE NOT NULL') AS ok"
            fixture.expect(
                neo(expected, "native-date-types").lower() == "true",
                "native-datetime-date-and-user-report",
            )
            fixture.expect(fingerprint() == before, "source-receipt-and-model-inputs-unchanged")
            fixture.expect(
                graph_before
                == neo(
                    "MATCH (n) WHERE NOT n:jobPosting RETURN collect(properties(n)) AS stable",
                    "graph-after",
                ),
                "non-posting-graph-history-unchanged",
            )
            fixture.expect(
                checkpoints
                == fixture.sql(
                    "SELECT md5(jsonb_agg(to_jsonb(g) ORDER BY run_id)::text) FROM ingestion.graph_export g"
                ),
                "graph-checkpoints-unchanged",
            )
            rejected(
                call.replace("02:48:14", "02:48:15"),
                "IMMUTABLE_JOBKOREA_COLLECTION_TIME_EVIDENCE",
                "conflicting-user-report",
            )
            rejected(
                "UPDATE ingestion.jobkorea_collection_time_evidence SET recorded_at=clock_timestamp()",
                "IMMUTABLE_JOBKOREA_COLLECTION_TIME_EVIDENCE",
                "immutable-collection-evidence",
            )
            rejected(
                "DELETE FROM ingestion.posting_ingestion_observation",
                "IMMUTABLE_POSTING_INGESTION_OBSERVATION",
                "immutable-ingestion-ledger",
            )
            rejected(
                "INSERT INTO ingestion.posting_ingestion_observation(identity_id,source_id,source_posting_id,run_id,evidence_record_id,ingested_at,ingestion_time_basis,receipt_scraped_at) SELECT identity_id||'-forged',source_id,source_posting_id,run_id,evidence_record_id,ingested_at,ingestion_time_basis,receipt_scraped_at FROM ingestion.posting_ingestion_observation LIMIT 1",
                "INVALID_POSTING_INGESTION_OBSERVATION",
                "forged-observation-rejected",
            )
            rejected(
                """
BEGIN;
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,completed_at)
 VALUES('nara-invalid-ledger-fixture','nara_job','FULL','fixture','READY',clock_timestamp());
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
 VALUES('nara-invalid-ledger-fixture','index','FILE',1,1);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at)
 VALUES('nara-invalid-ledger-fixture','index','index',1,'fixture.json',repeat('a',64),1,'UTF-8',200,clock_timestamp(),1,1,1,1,true,clock_timestamp());
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT 'nara-invalid-ledger-fixture','index','/'||n,'invalid-'||n||':list','{}',
 jsonb_build_object('kind','JobPosting','posting_id','bad','representation','list','ongoing',false,'title','Invalid') FROM generate_series(1,2) n;
INSERT INTO ingestion.posting_ingestion_observation(identity_id,source_id,source_posting_id,run_id,evidence_record_id,ingested_at,ingestion_time_basis,receipt_scraped_at)
 SELECT ingestion.posting_identity(u.source_id,'bad'),u.source_id,'bad',u.run_id,min(r.record_id),u.created_at,'RUN_CREATED_AT',NULL
 FROM ingestion.run u JOIN ingestion.record r USING(run_id) WHERE u.run_id='nara-invalid-ledger-fixture'
 GROUP BY u.source_id,u.run_id,u.created_at;
COMMIT;
""",
                "POSTING_DATE_RUN_VALIDATION_FAILED",
                "invalid-ready-run-rejected-by-statement-guard",
            )
            rejected(
                "SELECT * FROM ingestion.graph_posting_ingestion_dates('unknown')",
                "POSTING_DATES_REQUIRE_EXACT_READY_RUN",
                "unknown-verification-scope",
            )

            # Legacy fixtures have valid ALIO list/detail pairs and a non-active
            # Nara listing. Their identity contract remains the shared graph's.
            fixture.sql(compatibility.FIXTURE)
            fixture.sql(
                "UPDATE ingestion.run SET created_at='2026-09-01T15:30:00Z' WHERE run_id IN('job_alio','nara_job')"
            )
            for source in ("job_alio", "nara_job"):
                fixture.run(
                    "../../graph/load_snapshot.hwf",
                    "native-legacy-" + source,
                    extra={"RUN_ID": source},
                )
                row = dates(source)[0]
                fixture.expect(
                    row["ingestion_time_basis"] == "RUN_CREATED_AT"
                    and row["first_ingested_at"] == "2026-09-01T15:30:00.000000Z"
                    and row["ingestion_batch_date"] == "2026-09-02",
                    source + "-run-event-and-kst-date",
                )
            fixture.expect(
                dates("job_alio")[0]["identity_id"] != dates("nara_job")[0]["identity_id"],
                "source-qualified-posting-dates",
            )
            rejected(
                "SELECT * FROM ingestion.graph_posting_ingestion_dates('alio_organization-does-not-exist')",
                "POSTING_DATES_REQUIRE_EXACT_READY_RUN",
                "independent-verifier-fails-closed",
            )
            fixture.sql(
                "SELECT ingestion.record_posting_ingestion_observations('alio_organization')"
            )
            fixture.expect(dates("alio_organization") == [], "valid-non-posting-run-is-empty")

            # A newer containing run with an empty title advances dates while
            # the older readable title remains selected by the name ranking.
            fixture.sql("""
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at)
 VALUES('nara-new','nara_job','FULL','fixture','READY','2026-10-01T23:00:00Z','2026-10-01T23:00:10Z'),
 ('nara-newest-absent','nara_job','FULL','fixture','READY','2026-10-02T00:00:00Z','2026-10-02T00:00:10Z');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
 SELECT run_id,'index','FILE',1,1 FROM ingestion.run WHERE run_id LIKE 'nara-new%';
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at)
 SELECT run_id,'index','index',1,'fixture.json',repeat('a',64),1,'UTF-8',200,created_at,1,1,1,1,true,created_at FROM ingestion.run WHERE run_id LIKE 'nara-new%';
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT run_id,'index','/0',CASE WHEN run_id='nara-new' THEN '123:list' ELSE '456:list' END,'{}',
 jsonb_build_object('kind','JobPosting','posting_id',CASE WHEN run_id='nara-new' THEN '123' ELSE '456' END,'representation','list','ongoing',false,'title','') FROM ingestion.run WHERE run_id LIKE 'nara-new%';
""")
            fixture.run(
                "../../graph/load_snapshot.hwf",
                "native-new-containing-run",
                extra={"RUN_ID": "nara-new"},
            )
            fixture.run(
                "../../graph/load_snapshot.hwf",
                "native-new-absent-run",
                extra={"RUN_ID": "nara-newest-absent"},
            )
            fixture.run(
                "../../graph/update_posting_dates.hwf",
                "native-older-run-replay",
                extra={"RUN_ID": "nara_job"},
            )
            row = dates("nara_job")[0]
            fixture.expect(
                row["latest_ingestion_run_id"] == "nara-new"
                and row["last_ingested_at"] == "2026-10-01T23:00:00.000000Z",
                "older-replay-and-absent-newer-posting",
            )
            fixture.expect(
                neo(
                    "MATCH(p:jobPosting {id:'"
                    + row["identity_id"]
                    + "'}) RETURN p.name='Nara' AND p.name_source_run_id='nara_job' AND p.latest_ingestion_run_id='nara-new' AS ok",
                    "name-ranking-independent",
                ).lower()
                == "true",
                "date-selection-independent-of-readable-name",
            )

            # A later local import containing only the first posting must clear
            # its unknown collection time, retaining the second posting's report.
            newer = fixture.work / "inputs/newer.json"
            newer.write_text(
                json.dumps(
                    [
                        {
                            "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109422",
                            "job_title": "New backend title",
                            "company_name": "Example employer",
                        }
                    ]
                )
            )
            fixture.run("full.hwf", "native-later-local-import", input_name="newer.json")
            later = fixture.sql(
                "SELECT run_id FROM ingestion.jobkorea_import ORDER BY imported_at DESC LIMIT 1"
            )
            fixture.run(
                "../../graph/update_posting_dates.hwf",
                "native-old-local-replay",
                extra={"RUN_ID": run},
            )
            rows = dates(run)
            fixture.expect(
                sum(d["latest_ingestion_run_id"] == later and d["scraped_at"] is None for d in rows)
                == 1
                and sum(
                    d["latest_ingestion_run_id"] == run and d["scraped_at_basis"] == "USER_REPORTED"
                    for d in rows
                )
                == 1,
                "latest-occurrence-unknown-clears-only-that-posting",
            )
            fixture.expect(
                neo(
                    "MATCH(p:jobPosting) WHERE p.latest_ingestion_run_id="
                    + json.dumps(later)
                    + " RETURN p.scraped_at IS NULL AND p.scraped_at_basis IS NULL AND p.scraped_at_evidence_reference IS NULL AS ok",
                    "unknown-clears-native-fields",
                ).lower()
                == "true",
                "native-scrape-fields-cleared",
            )
            later_sha = fixture.sql(
                "SELECT file_sha256 FROM ingestion.jobkorea_import WHERE run_id=" + quote(later)
            )
            later_call = (
                "SELECT ingestion.register_jobkorea_collection_time("
                + ",".join(
                    map(
                        quote,
                        [
                            later,
                            later_sha,
                            "2099-01-01T00:00:00Z",
                            "USER_REPORTED",
                            "future-report",
                            "Asia/Seoul",
                        ],
                    )
                )
                + ")"
            )
            rejected(
                later_call,
                "INVALID_JOBKOREA_COLLECTION_TIME_EVIDENCE",
                "future-collection-report-rejected",
            )
            rejected(
                later_call.replace("2099-01-01", "2026-10-07").replace(later_sha, "f" * 64),
                "INVALID_JOBKOREA_COLLECTION_TIME_EVIDENCE",
                "wrong-file-report-rejected",
            )

            # Distinct-run validation must not execute once per source row.
            fixture.sql("""
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at)
 SELECT 'nara-large-'||n,'nara_job','FULL','fixture','READY','2026-09-01T00:00:00Z'::timestamptz+make_interval(days=>n),'2026-09-01T00:01:00Z'::timestamptz+make_interval(days=>n) FROM generate_series(1,3) n;
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
 SELECT run_id,'index','FILE',4000,4000 FROM ingestion.run WHERE run_id LIKE 'nara-large-%';
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,http_status,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at)
 SELECT run_id,'index','index',1,'fixture.json',repeat('b',64),1,'UTF-8',200,created_at,4000,1,4000,4000,true,created_at FROM ingestion.run WHERE run_id LIKE 'nara-large-%';
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT run_id,'index','/'||n,'large-'||n||':list','{}',jsonb_build_object('kind','JobPosting','posting_id','large-'||n,'representation','list','ongoing',false,'title','Large fixture')
 FROM ingestion.run CROSS JOIN generate_series(1,4000) n WHERE run_id LIKE 'nara-large-%';
""")
            fixture.sql(
                "SELECT jsonb_build_object('capture_function',pg_get_functiondef('ingestion.record_posting_ingestion_observations(text)'::regprocedure),'relation_stats',(SELECT jsonb_agg(jsonb_build_object('table',c.relname,'rows',c.reltuples,'pages',c.relpages,'last_autoanalyze',s.last_autoanalyze)) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid WHERE n.nspname='ingestion' AND c.relname IN('record','run','document','posting_ingestion_observation')))",
                "large-run-installed-contract-and-stats",
            )
            started = time.monotonic()
            added = fixture.sql(
                "SET statement_timeout='60s'; SELECT ingestion.record_posting_ingestion_observations('nara-large-3')",
                "large-run-capture",
            )
            elapsed = time.monotonic() - started
            fixture.expect(added == "12000", "twelve-thousand-observations-three-runs")
            fixture.receipt["large_capture_seconds"] = elapsed
            print(f"12,000 observations in {elapsed:.3f}s", flush=True)
            fixture.expect(
                fixture.sql(
                    "SELECT ingestion.record_posting_ingestion_observations('nara-large-1')"
                )
                == "0",
                "large-replay-idempotent",
            )
            first = dates("nara-large-3")[0]["first_ingested_at"]
            fixture.sql(
                "DELETE FROM ingestion.record WHERE run_id='nara-large-1'; DELETE FROM ingestion.document WHERE run_id='nara-large-1'; DELETE FROM ingestion.partition WHERE run_id='nara-large-1'; DELETE FROM ingestion.run WHERE run_id='nara-large-1'"
            )
            fixture.expect(
                dates("nara-large-3")[0]["first_ingested_at"] == first,
                "minimal-ledger-survives-source-retention",
            )
            fixture.sql(
                (ROOT / "hop/graph/sql/001_posting_ingestion_dates.sql").read_text(),
                "date-installer-replay",
            )
            fixture.expect(
                dates("nara-large-3")[0]["first_ingested_at"] == first,
                "installer-replay-preserves-retained-event",
            )
            fixture.expect(
                fixture.sql(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname='ingestion' AND indexname='record_posting_date_lookup'"
                )
                == "1",
                "index-replay-single-definition",
            )
            fixture.receipt["status"] = "PASSED"
        except Exception:
            fixture.receipt["status"] = "FAILED"
            raise
        finally:
            if (
                fixture.receipt["status"] == "FAILED"
                and os.environ.get("JOBTOLOGY_POSTING_DATES_KEEP_FAILED_FIXTURE") == "1"
            ):
                fixture.receipt["retained_fixture"] = {
                    "pg": fixture.pg,
                    "database": fixture.database,
                    "neo": fixture.neo,
                    "hop": fixture.hop,
                    "network": fixture.network,
                }
                (fixture.work / "receipt.json").write_text(
                    json.dumps(fixture.receipt, indent=2) + "\n"
                )
            else:
                fixture.close()
            print("Protected receipt: " + str(fixture.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
