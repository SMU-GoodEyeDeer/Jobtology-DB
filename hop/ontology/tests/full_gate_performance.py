#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ─── How to run ───
# 1. Run: uv run hop/ontology/tests/full_gate_performance.py
# 2. Only a uniquely named disposable local PostgreSQL container is created.
# ──────────────────

"""Bounded six-source and historical observation gate profiling, not native graph proof."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid

import run

SUFFIX = uuid.uuid4().hex[:10]
run.PG = f'jobtology-perf-gate-{SUFFIX}-pg'


def sql(statement: str, timeout: str = '30s') -> str:
    return run.sql(f"SET statement_timeout='{timeout}'; {statement}")


def measure(label: str, statement: str, timeout: str = '30s', samples: int = 3,
            reader: bool = False) -> bool:
    for sample in range(samples):
        try:
            query = 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + statement
            if reader:
                query = ('BEGIN READ ONLY; SET ROLE jobtology_catalog_reader; ' +
                         query + '; COMMIT')
            plan = json.loads(sql(query, timeout))[0]
        except RuntimeError as error:
            if 'canceling statement due to statement timeout' not in str(error):
                raise
            print(json.dumps({'label': label, 'sample': sample + 1,
                              'result': 'statement_timeout', 'bound': timeout,
                              'detail': str(error).splitlines()[0]}), flush=True)
            return False
        print(json.dumps({'label': label, 'sample': sample + 1,
                          'ms': plan['Execution Time'],
                          'temp_read': plan['Plan'].get('Temp Read Blocks', 0),
                          'temp_written': plan['Plan'].get('Temp Written Blocks', 0)}), flush=True)
    return True


def typed_census_errors() -> list[str]:
    errors = []
    for field, value in (('date_posted', 'not-a-date'), ('ongoing', 'not-a-boolean'),
                         ('headcount', 'not-an-integer')):
        try:
            sql("BEGIN; UPDATE ingestion.record SET normalized=jsonb_set(normalized, "
                f"'{{{field}}}',to_jsonb('{value}'::text)) "
                "WHERE run_id='fixture-job_alio'; "
                "SELECT count(*) FROM ontology.posting_census_v1('fixture-job_alio'); ROLLBACK;")
        except RuntimeError as error:
            errors.append(str(error).splitlines()[0])
        else:
            raise AssertionError(f'Posting census accepted malformed {field}')
    return errors


def fixture(scale: int) -> None:
    records = run.fixture()
    records['job_alio'][0].update(title=records['job_alio'][1]['title'], organization_code='C001')
    run.load_sources(records)
    sql("""
        UPDATE ingestion.partition p SET expected_total=(SELECT count(*) FROM ingestion.record r
          WHERE r.run_id=p.run_id AND r.document_id='doc');
        UPDATE ingestion.document d SET item_count=(SELECT count(*) FROM ingestion.record r
          WHERE r.run_id=d.run_id AND r.document_id=d.document_id),effective_page=1,
          effective_page_size=1,declared_total=(SELECT count(*) FROM ingestion.record r
          WHERE r.run_id=d.run_id AND r.document_id=d.document_id),
          provider_result=CASE WHEN d.run_id IN ('fixture-job_alio','fixture-alio_organization')
            THEN '200' ELSE '00' END;
        INSERT INTO ingestion.dependency(run_id,input_source_id,input_run_id)
        VALUES('fixture-job_alio','alio_organization','fixture-alio_organization'),
         ('fixture-ncs_qualification','ncs_competency','fixture-ncs_competency'),
         ('fixture-qnet_schedule','ncs_qualification','fixture-ncs_qualification');
        INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
         VALUES('fixture-job_alio','detail-001','FILE',1,1),
          ('fixture-job_alio','index','FILE',1,1),
          ('fixture-ncs_qualification','ncs-2001020199_19v1','FILE',1,1),
          ('fixture-ncs_qualification','ncs-2001020101_24v2','FILE',1,1),
          ('fixture-qnet_schedule','year-2026-item-T5H0','FILE',1,2);
        INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
          byte_length,encoding,http_status,retrieved_at,selected,verified_at,provider_result,
          declared_total,effective_page,effective_page_size,item_count)
        SELECT run_id,'detail-doc','detail-001',1,raw_path,raw_sha256,byte_length,encoding,
          http_status,retrieved_at,selected,verified_at,provider_result,1,1,1,1
         FROM ingestion.document WHERE run_id='fixture-job_alio' AND document_id='doc';
        UPDATE ingestion.record SET document_id='detail-doc' WHERE run_id='fixture-job_alio'
          AND normalized->>'representation'='detail';
        UPDATE ingestion.document SET item_count=1,declared_total=1
         WHERE run_id='fixture-job_alio' AND document_id='doc';
        UPDATE ingestion.document SET partition_id='index'
         WHERE run_id='fixture-job_alio' AND document_id='doc';
        DELETE FROM ingestion.partition WHERE run_id='fixture-job_alio' AND partition_id='all';
        INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
          byte_length,encoding,http_status,retrieved_at,selected,verified_at,provider_result,
          declared_total,effective_page,effective_page_size,item_count)
        SELECT run_id,'qual-doc','ncs-2001020199_19v1',1,raw_path,raw_sha256,byte_length,encoding,
          http_status,retrieved_at,selected,verified_at,provider_result,1,1,1,1
         FROM ingestion.document WHERE run_id='fixture-ncs_qualification' AND document_id='doc';
        UPDATE ingestion.document SET partition_id='ncs-2001020101_24v2',
          item_count=1,declared_total=1
         WHERE run_id='fixture-ncs_qualification' AND document_id='doc';
        UPDATE ingestion.record SET document_id='qual-doc' WHERE run_id='fixture-ncs_qualification'
         AND normalized->>'competency_code'='2001020199_19v1';
        UPDATE ingestion.document SET partition_id='year-2026-item-T5H0'
         WHERE run_id='fixture-qnet_schedule';
        DELETE FROM ingestion.partition
         WHERE run_id='fixture-ncs_qualification' AND partition_id='all';
        DELETE FROM ingestion.partition WHERE run_id='fixture-qnet_schedule' AND partition_id='all';
    """)
    sql(f"""
        INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,
          source_payload,normalized)
        SELECT 'fixture-ncs_competency','doc','bulk-'||g,lpad(g::text,10,'0')||'_20v1',
          jsonb_set(jsonb_set(jsonb_set(template.normalized,'{{code}}',to_jsonb(lpad(g::text,10,'0')||'_20v1')),
            '{{name}}',to_jsonb('능력단위 '||g)),
            '{{occupation_code}}',to_jsonb(left(lpad(g::text,10,'0'),8))),
          jsonb_set(jsonb_set(jsonb_set(template.normalized,'{{code}}',to_jsonb(lpad(g::text,10,'0')||'_20v1')),
            '{{name}}',to_jsonb('능력단위 '||g)),
            '{{occupation_code}}',to_jsonb(left(lpad(g::text,10,'0'),8)))
         FROM ingestion.record template CROSS JOIN generate_series(1,{1000 * scale}) g
         WHERE template.run_id='fixture-ncs_competency' AND template.locator='0';
        UPDATE ingestion.document SET item_count=(SELECT count(*) FROM ingestion.record
          WHERE run_id='fixture-ncs_competency'),
          declared_total=(SELECT count(*) FROM ingestion.record
          WHERE run_id='fixture-ncs_competency') WHERE run_id='fixture-ncs_competency';
        UPDATE ingestion.partition SET expected_total=(SELECT count(*) FROM ingestion.record
          WHERE run_id='fixture-ncs_competency') WHERE run_id='fixture-ncs_competency';
        ANALYZE ingestion.record;
    """, '90s')
    postings = min(50 * scale, 1000)
    history = min(2 * scale, 16)
    sql(f"""
        INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
         SELECT 'fixture-job_alio','detail-p'||g,'FILE',1,1 FROM generate_series(1,{postings}) g;
        INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
          byte_length,encoding,http_status,retrieved_at,selected,verified_at,provider_result,
          declared_total,effective_page,effective_page_size,item_count)
         SELECT 'fixture-job_alio','detail-p'||g,'detail-p'||g,1,d.raw_path,d.raw_sha256,
          d.byte_length,d.encoding,d.http_status,d.retrieved_at,true,d.verified_at,'200',1,1,1,1
         FROM ingestion.document d CROSS JOIN generate_series(1,{postings}) g
         WHERE d.run_id='fixture-job_alio' AND d.document_id='detail-doc';
        INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,
          source_payload,normalized)
         SELECT 'fixture-job_alio',CASE WHEN r.document_id='doc' THEN 'doc' ELSE 'detail-p'||g END,
          'p'||g,'p'||g||':'||(r.normalized->>'representation'),
          jsonb_set(r.normalized,'{{posting_id}}',to_jsonb('p'||g)),
          jsonb_set(r.normalized,'{{posting_id}}',to_jsonb('p'||g))
         FROM ingestion.record r CROSS JOIN generate_series(1,{postings}) g
         WHERE r.run_id='fixture-job_alio';
        UPDATE ingestion.document SET item_count={postings + 1},declared_total={postings + 1}
         WHERE run_id='fixture-job_alio' AND document_id='doc';
        UPDATE ingestion.partition SET expected_total={postings + 1}
         WHERE run_id='fixture-job_alio' AND partition_id='index';
        INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,
          created_at,completed_at)
         SELECT 'perf-history-'||h,'job_alio','FULL','fixture','READY',
          '2026-08-01T00:00:00Z'::timestamptz+h*interval '1 day',
          '2026-08-01T00:01:00Z'::timestamptz+h*interval '1 day'
         FROM generate_series(1,{history}) h;
        INSERT INTO ingestion.dependency(run_id,input_source_id,input_run_id)
         SELECT 'perf-history-'||h,'alio_organization','fixture-alio_organization'
         FROM generate_series(1,{history}) h;
        INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
         SELECT 'perf-history-'||h,CASE WHEN p.partition_id='index' THEN 'index'
          ELSE 'detail-h'||h||'-'||substring(p.partition_id FROM 8) END,
          'FILE',1,p.expected_total FROM ingestion.partition p
          CROSS JOIN generate_series(1,{history}) h
         WHERE p.run_id='fixture-job_alio';
        INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
          byte_length,encoding,http_status,retrieved_at,selected,verified_at,provider_result,
          declared_total,effective_page,effective_page_size,item_count)
         SELECT 'perf-history-'||h,d.document_id,CASE WHEN d.partition_id='index' THEN 'index'
          ELSE 'detail-h'||h||'-'||substring(d.partition_id FROM 8) END,
          1,d.raw_path,d.raw_sha256,d.byte_length,d.encoding,200,
          '2026-08-01T00:00:30Z'::timestamptz+h*interval '1 day',true,
          '2026-08-01T00:00:40Z'::timestamptz+h*interval '1 day','200',
          d.declared_total,1,1,d.item_count FROM ingestion.document d
          CROSS JOIN generate_series(1,{history}) h
         WHERE d.run_id='fixture-job_alio';
        INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,
          source_payload,normalized)
         SELECT 'perf-history-'||h,r.document_id,r.locator,'h'||h||'-'||r.source_record_id,
          jsonb_set(r.normalized,'{{posting_id}}',to_jsonb('h'||h||'-'||(r.normalized->>'posting_id'))),
          jsonb_set(r.normalized,'{{posting_id}}',to_jsonb('h'||h||'-'||(r.normalized->>'posting_id')))
         FROM ingestion.record r CROSS JOIN generate_series(1,{history}) h
         WHERE r.run_id='fixture-job_alio';
        ANALYZE ingestion.run; ANALYZE ingestion.partition; ANALYZE ingestion.document;
        ANALYZE ingestion.record;
    """, '90s')
    issues = sql("SELECT coalesce(string_agg(run_id||':'||issue,','), 'OK') "
                 "FROM ingestion.validation_issue", '90s')
    assert issues == 'OK', issues
    print(json.dumps({'stage': 'source', 'scale': scale,
                      'runs': sql('SELECT count(*) FROM ingestion.run'),
                      'records': sql('SELECT count(*) FROM ingestion.record'),
                      'postings_per_run': postings, 'historical_runs': history,
                      'validator': issues}), flush=True)


def gate(scale: int) -> None:
    choices = run.js({source: 'fixture-' + source for source in run.fixture()})
    release = f'perf-gate-{scale}'
    measure('source_snapshot_validation',
            "SELECT count(*) FROM ingestion.validation_issue "
            "WHERE run_id='fixture-ncs_competency'")
    measure('source_fingerprint', "SELECT ontology.source_fingerprint('fixture-ncs_competency')")
    plan = json.loads(sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                          "SELECT count(*) FROM ontology.posting_census_v1('fixture-job_alio')",
                          '90s'))[0]
    posting_cte = re.search(r'"Subplan Name": "CTE postings".*?"Actual Rows": ([0-9.]+)',
                            json.dumps(plan['Plan']))
    assert posting_cte is not None
    materialized_rows = float(posting_cte.group(1))
    print(json.dumps({'label': 'posting_census_plan', 'ms': plan['Execution Time'],
                      'materialized_rows': materialized_rows}), flush=True)
    assert materialized_rows <= 2 * (min(50 * scale, 1000) + 1), (
        'Pinned posting census materialized unrelated JOB runs'
    )
    measure('prepare_release',
            f'SELECT ontology.prepare_release({run.q(release)},{choices})', '90s')
    measure('assemble_sources', f'SELECT ontology.assemble_sources({run.q(release)})', '90s')
    measure('check_frozen_sources',
            f'SELECT ontology.check_frozen_sources({run.q(release)})', '90s')
    measure('source_coverage',
            f'SELECT count(*) FROM ontology.source_coverage WHERE release_id={run.q(release)}',
            '90s')
    measure('source_coverage_predicate',
            'SELECT EXISTS(SELECT 1 FROM ontology.source_coverage '
            f'WHERE release_id={run.q(release)} AND '
            '(unaccounted_records<>0 OR supported_records<>record_count))', '90s')
    measure('capture_current_census',
            "SELECT ontology.capture_posting_census_v1('fixture-job_alio')", '90s')
    measure('bind_observations', f'SELECT ontology.bind_observations_v1({run.q(release)})', '90s')
    measure('verify_observation_membership',
            f'SELECT ontology.verify_observation_membership_v1({run.q(release)})', '90s')
    measure('prepare_catalog_source',
            f'SELECT ontology.prepare_catalog_source_v1({run.q(release)})', '90s')
    if scale <= 2:
        original = (run.ROOT / 'hop/ontology/sql/020_catalog_source_graph.sql').read_text()
        original = original.split(
            'CREATE OR REPLACE FUNCTION ontology.catalog_source_edges_v1', 1)[1]
        original = ('CREATE OR REPLACE FUNCTION ontology.catalog_source_edges_v1' +
                    original.split('-- Retain the exact reviewed manifest', 1)[0])
        migration = (run.ROOT / 'hop/ontology/sql/023_scoped_catalog_edges.sql').read_text()
        sql(original)
        body = migration.split('BEGIN;', 1)[1].rsplit('COMMIT;', 1)[0]
        equal = sql('BEGIN; CREATE TEMP TABLE old_edges AS SELECT * FROM '
                    f'ontology.catalog_source_edges_v1({run.q(release)}); ' + body +
                    'CREATE TEMP TABLE new_edges AS SELECT * FROM '
                    f'ontology.catalog_source_edges_v1({run.q(release)}); '
                    'SELECT NOT EXISTS((SELECT * FROM old_edges EXCEPT ALL '
                    'SELECT * FROM new_edges) UNION ALL '
                    '(SELECT * FROM new_edges EXCEPT ALL SELECT * FROM old_edges)); '
                    'ROLLBACK;', '90s')
        assert equal == 't', 'Catalog edge candidate multiset changed'
        print(json.dumps({'label': 'catalog_edge_multiset_equal', 'result': equal}), flush=True)
        sql(migration)
    print(json.dumps({'stage': 'preseal', 'scale': scale,
                      'revisions': sql('SELECT count(*) FROM ontology.revision'),
                      'relations': sql('SELECT count(*) FROM ontology.source_relation'),
                      'relation_table_bytes': sql(
                          "SELECT pg_total_relation_size('ontology.source_relation')"),
                      'bound_history': sql(
                          'SELECT count(*) FROM ontology.observation_history_member '
                          f'WHERE release_id={run.q(release)}')}), flush=True)
    measure('candidate_edges',
            f'SELECT count(*) FROM ontology.catalog_source_edges_v1({run.q(release)})',
            '30s' if scale == 15 else '90s', 1 if scale == 15 else 3)
    if not measure('seal_catalog_source',
                   f'SELECT ontology.seal_catalog_source_v1({run.q(release)})',
                   '180s' if scale == 15 else '90s', 1 if scale == 15 else 3):
        print(json.dumps({'stage': 'seal_blocked', 'scale': scale,
                          'online_reads': 'not_run_unsealed'}), flush=True)
        return
    sql(f"""
        INSERT INTO ontology.graph_load(load_id,release_id,database_id,manifest_hash,state,
          finished_at,node_count,edge_count)
        SELECT 'synthetic-perf-{scale}',release_id,'synthetic-local-perf',manifest_hash,
          'VERIFIED',clock_timestamp(),(manifest->>'nodes')::bigint,(manifest->>'edges')::bigint
        FROM ontology.corpus_release WHERE release_id={run.q(release)};
        UPDATE ontology.corpus_release SET graph_verified_at=clock_timestamp()
        WHERE release_id={run.q(release)};
    """)
    measure('synthetic_sql_approval',
             f"SELECT catalog.approve_catalog_release({run.q(release)},"
             "'synthetic-local-perf','fixture','synthetic SQL-only profiling')",
             '180s' if scale == 15 else '90s')
    sql((run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
    for label, statement in (
        ('catalog_context', 'SELECT catalog.catalog_context_v1()'),
        ('catalog_summary', 'SELECT catalog.catalog_summary_v1()'),
        ('catalog_entities_page', "SELECT catalog.catalog_entities_v1(NULL,'jobPosting',20,0)"),
        ('catalog_entity', "SELECT catalog.catalog_entity_v1(NULL,"
          "'urn:jobtology:jobPosting:job_alio:001')"),
        ('catalog_relations', "SELECT catalog.catalog_relations_v1(NULL,"
         "'urn:jobtology:jobPosting:job_alio:001',20,0)"),
    ):
        measure(label, statement, '5s' if scale == 15 else '90s', reader=True)
    print(json.dumps({'stage': 'gate', 'scale': scale, 'release': release,
                      'revisions': sql('SELECT count(*) FROM ontology.revision'),
                      'relations': sql('SELECT count(*) FROM ontology.source_relation'),
                      'bound_history': sql('SELECT count(*) FROM '
                                           'ontology.observation_history_member '
                                           f'WHERE release_id={run.q(release)}'),
                      'graph_nodes': sql('SELECT count(*) FROM ontology.graph_node '
                                         f'WHERE release_id={run.q(release)}'),
                       'graph_edges': sql('SELECT count(*) FROM ontology.graph_edge '
                                          f'WHERE release_id={run.q(release)}'),
                       'graph_edge_table_bytes': sql(
                           "SELECT pg_total_relation_size('ontology.graph_edge')"),
                       'graph_load': 'SYNTHETIC_SQL_ONLY_NOT_NATIVE'}), flush=True)


def main() -> None:
    assert subprocess.run(['docker', 'inspect', run.PG], capture_output=True).returncode
    run.boot()
    sql((run.ROOT / 'docs/hop-migration/checks.sql').read_text())
    scale = int(os.environ.get('GATE_SCALE', '1'))
    assert scale in (1, 2, 15)
    fixture(scale)
    original = (run.ROOT / 'hop/ontology/sql/008_observations.sql').read_text()
    original = original.split('CREATE OR REPLACE FUNCTION ontology.posting_census_v1', 1)[1]
    original = ('CREATE OR REPLACE FUNCTION ontology.posting_census_v1' + original
                .split('CREATE OR REPLACE FUNCTION ontology.capture_posting_census_v1', 1)[0])
    sql(original)
    original_errors = typed_census_errors()
    if os.environ.get('GATE_BASELINE') != '1':
        migration = (run.ROOT / 'hop/ontology/sql/022_scoped_posting_census.sql').read_text()
        body = migration.split('BEGIN;', 1)[1].rsplit('COMMIT;', 1)[0]
        equal = sql("BEGIN; CREATE TEMP TABLE old_census AS "
                    "SELECT * FROM ontology.posting_census_v1('fixture-job_alio') UNION ALL "
                    "SELECT * FROM ontology.posting_census_v1('perf-history-1'); " + body +
                    "CREATE TEMP TABLE new_census AS "
                    "SELECT * FROM ontology.posting_census_v1('fixture-job_alio') UNION ALL "
                    "SELECT * FROM ontology.posting_census_v1('perf-history-1'); "
                    "SELECT NOT EXISTS((SELECT * FROM old_census EXCEPT ALL "
                    "SELECT * FROM new_census) "
                    "UNION ALL (SELECT * FROM new_census EXCEPT ALL SELECT * FROM old_census)); "
                    "ROLLBACK;", '90s')
        assert equal == 't', 'Scoped census changed the list/detail source-row multiset'
        print(json.dumps({'label': 'census_multiset_equal', 'result': equal}), flush=True)
        sql(migration)
        assert typed_census_errors() == original_errors, (
            'Scoped census changed typed parsing errors')
        print(json.dumps({'label': 'typed_census_errors_equal',
                          'errors': original_errors}), flush=True)
    gate(scale)


if __name__ == '__main__':
    try:
        main()
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
