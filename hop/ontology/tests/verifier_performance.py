#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ─── How to run ───
# 1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
# 2. Run: ONTOLOGY_TEST_PG=jobtology-perf-fix-20261001-pg \
#      KEEP_ONTOLOGY_TEST_CONTAINER=1 uv run hop/ontology/tests/verifier_performance.py
# 3. This creates only a disposable local PostgreSQL container.
# ──────────────────

"""Measure the deployed validation view on synthetic, run-scoped source rows."""

from __future__ import annotations

import json
import os
import subprocess

import run


def sql(value: str) -> str:
    result = subprocess.run(
        ['docker', 'exec', '-i', run.PG, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
         '-U', 'postgres', '-d', 'ontologytest'],
        input=value, text=True, capture_output=True, check=True,
    )
    return result.stdout.strip()


def main() -> None:
    assert run.PG.startswith('jobtology-perf-'), 'Use a uniquely named disposable perf container'
    run.boot()
    checks = (run.ROOT / 'docs/hop-migration/checks.sql').read_text()
    if os.environ.get('PERF_PATCH') != '1':
        checks = checks.replace('AS NOT MATERIALIZED (', 'AS (')
    sql(checks)
    migration = (run.ROOT / 'hop/ontology/sql/021_scoped_validation.sql').read_text()
    if os.environ.get('PERF_PATCH') == '1':
        sql(migration)
    previous = 0
    for batches in (8, 16, 40, 80):
        sql(f"""
            INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,
              created_at,completed_at)
            SELECT 'perf-'||g,'ncs_competency','FULL','fixture','READY',
              '2026-09-01T00:00:00Z','2026-09-01T00:01:00Z'
            FROM generate_series({previous},{batches - 1}) g;
            INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
            SELECT 'perf-'||g,'all','PAGED',1,CASE WHEN g=0 THEN 15000 ELSE 1000 END
            FROM generate_series({previous},{batches - 1}) g;
            INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,
              raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at,
              provider_result,declared_total,effective_page,effective_page_size,item_count)
            SELECT 'perf-'||g,'doc-'||p,'all',p,'fixture.json',repeat('a',64),100,
              'UTF-8',200,'2026-09-01T00:00:30Z',true,'2026-09-01T00:00:40Z',
              NULL,CASE WHEN g=0 THEN 15000 ELSE 1000 END,p,1,1
            FROM generate_series({previous},{batches - 1}) g
            CROSS JOIN LATERAL generate_series(1,CASE WHEN g=0 THEN 15000 ELSE 1000 END) p;
            INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,
              source_payload,normalized)
            SELECT 'perf-'||g,'doc-'||p,'1','unit-'||p,
              jsonb_build_object('kind','Competency','code','unit-'||p),
              jsonb_build_object('kind','Competency','code','unit-'||p)
            FROM generate_series({previous},{batches - 1}) g
            CROSS JOIN LATERAL generate_series(1,CASE WHEN g=0 THEN 15000 ELSE 1000 END) p;
            ANALYZE ingestion.run; ANALYZE ingestion.partition; ANALYZE ingestion.document;
            ANALYZE ingestion.record;
        """)
        for label, query in (
            ('validation', "SELECT EXISTS(SELECT 1 FROM ingestion.validation_issue "
             "WHERE run_id='perf-0')"),
            ('fingerprint', "SELECT ontology.source_fingerprint('perf-0') IS NOT NULL"),
        ):
            plan = json.loads(sql(
                "SET statement_timeout='30s'; EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query
            ))[0]
            print(json.dumps({'batches': batches, 'label': label,
                              'ms': plan['Execution Time'], 'plan': plan['Plan']['Node Type'],
                              'temp_written': plan['Plan'].get('Temp Written Blocks', 0)}),
                  flush=True)
            if batches == 80 and label == 'validation':
                materialized = 'CTE facts' in json.dumps(plan['Plan'])
                assert materialized == (os.environ.get('PERF_PATCH') != '1'), (
                    'Expected the baseline to materialize all-run facts and the patched '
                    'validator to push down the pinned-run filter.'
                )
        previous = batches
    if os.environ.get('PERF_PATCH') == '1':
        sql(checks.replace('AS NOT MATERIALIZED (', 'AS ('))
        changes = """
            UPDATE ingestion.record SET normalized=normalized||'{"kind":"Other"}'::jsonb
              WHERE run_id='perf-0' AND document_id='doc-1';
            UPDATE ingestion.document SET item_count=2
              WHERE run_id='perf-0' AND document_id='doc-2';
            UPDATE ingestion.record SET source_record_id='unit-3'
              WHERE run_id='perf-0' AND document_id='doc-4';
            INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state)
              VALUES('perf-job','job_alio','FULL','fixture','READY');
            INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
              VALUES('perf-job','index','FILE',1,1),
                    ('perf-job','detail-p1','FILE',1,1);
            INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,
              raw_sha256,byte_length,encoding,http_status,retrieved_at,selected,verified_at,
              provider_result,declared_total,effective_page,effective_page_size,item_count)
              SELECT 'perf-job',kind,partition_id,1,'fixture.json',repeat('a',64),1,
                'UTF-8',200,now(),true,now(),'200',1,1,1,1
              FROM (VALUES('list','index'),('detail','detail-p1')) parts(kind,partition_id);
            INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,
              source_payload,normalized)
              SELECT 'perf-job',kind,'1','p1:'||kind,
                jsonb_build_object('kind','JobPosting','posting_id','p1',
                  'representation',kind,'title',title),
                jsonb_build_object('kind','JobPosting','posting_id','p1',
                  'representation',kind,'title',title)
              FROM (VALUES('list','old title'),('detail','new title')) parts(kind,title);
        """
        compare = """
            SELECT NOT EXISTS (
                (SELECT * FROM original_issues EXCEPT ALL SELECT * FROM ingestion.validation_issue)
                UNION ALL
                (SELECT * FROM ingestion.validation_issue EXCEPT ALL SELECT * FROM original_issues)
            );
        """
        migration_body = migration.split('BEGIN;', 1)[1].rsplit('COMMIT;', 1)[0]
        before, equivalent = sql(
            'BEGIN; ' + changes +
            'CREATE TEMP TABLE original_issues AS SELECT * FROM ingestion.validation_issue; '
            "SELECT string_agg(DISTINCT issue,',' ORDER BY issue) FROM original_issues; "
            + migration_body
            + compare + 'ROLLBACK;'
        ).splitlines()
        assert set(before.split(',')) == {
            'DOCUMENT_METADATA_OR_FILE_NOT_VERIFIED', 'ROW_COUNT_MISMATCH',
            'WRONG_RECORD_KIND', 'DUPLICATE_SOURCE_ID', 'POSTING_PAIR_CONFLICT',
            'MISSING_DEPENDENCY',
        }, before
        assert equivalent == 't', 'Old and new issue multisets differ under source tampering'
        print(json.dumps({'tamper_issues': before, 'old_new_multiset_equal': equivalent}),
              flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        if (not os.environ.get('KEEP_ONTOLOGY_TEST_CONTAINER')
                and run.PG.startswith('jobtology-perf-')):
            subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
