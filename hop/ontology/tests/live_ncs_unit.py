#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# Run: uv run hop/ontology/tests/live_ncs_unit.py
# ──────────────────
from __future__ import annotations

import subprocess
import uuid

import run


def error(query: str, message: str) -> None:
    try:
        run.sql('\\set VERBOSITY verbose\n' + query)
    except RuntimeError as exc:
        assert f'ERROR:  P0001: {message}\n' in str(exc), str(exc)
    else:
        raise AssertionError(f'Expected {message}')


def check() -> None:
    # Given: several versions, including a higher excluded version, in the READY run.
    run.load_sources({'ncs_competency': [
        dict(kind='Competency', code='2001020205_20v1', name='이전 단위', level=2,
             definition='이전 정의'),
        dict(kind='Competency', code='2001020205_23v6', name='서버프로그램 구현', level=3,
             definition='  서버프로그램을 구현하는 능력이다.\n'),
        dict(kind='Competency', code='2001020205_23v10', name='문자열 순서가 앞선 단위',
             level=5, definition='선택하지 않을 정의'),
        dict(kind='Competency', code='2001020205_24v9', name='서버프로그램 구현(구버전)',
             level=4, definition='제외할 정의'),
        dict(kind='Competency', code='2001020206_23v1', name='공백 정의', level=None,
             definition=' \t\r\n '),
        dict(kind='Competency', code='2001020207_23v1', name='빈 정의', definition=''),
        dict(kind='Competency', code='2001020208_23v1', name='없는 정의'),
        dict(kind='Competency', code='2001020209_24v1', name='단위(구버전)', level=3),
    ]})
    run.sql("""
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at)
VALUES ('older','ncs_competency','FULL','fixture','READY','2026-08-01','2026-08-02'),
 ('failed','ncs_competency','FULL','fixture','FAILED','2026-10-01','2026-10-02'),
 ('smoke','ncs_competency','SMOKE','fixture','READY','2026-10-02','2026-10-03');
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size)
 SELECT run_id,'all','FILE',1 FROM ingestion.run WHERE run_id IN ('older','failed','smoke');
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,
 byte_length,encoding,http_status,retrieved_at,selected,verified_at)
 SELECT run_id,'doc','all',1,'fixture.json',repeat('a',64),1,'UTF-8',200,created_at,true,now()
 FROM ingestion.run WHERE run_id IN ('older','failed','smoke');
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT run_id,'doc','0','other','{}'::jsonb,
 '{"kind":"Competency","code":"2001020205_99v9","name":"다른 스냅샷",
   "level":8,"definition":"다른 정의"}'::jsonb
 FROM ingestion.run WHERE run_id IN ('older','failed','smoke');
""")
    expected = {
        'contract_version': 'hop-live-source-v1',
        'sources': [{'source_id': 'ncs_competency', 'run_id': 'fixture-ncs_competency',
                     'data_as_of': '2026-09-01T00:01:00+00:00'}],
        'item': {'base_code': '2001020205', 'code': '2001020205_23v6',
                 'name': '서버프로그램 구현', 'level': 3,
                 'definition': '  서버프로그램을 구현하는 능력이다.\n'},
    }
    # When: the base code is looked up. Then: exactly the highest eligible unit is returned.
    assert run.sql("SELECT catalog.live_ncs_unit_v1('2001020205')="
                   + run.js(expected)) == 't'

    # Given: no matching eligible unit. When: read. Then: null item with source provenance.
    for code in ('9999999999', '2001020209'):
        assert run.sql(f'SELECT catalog.live_ncs_unit_v1({run.q(code)})='
                       + run.js(expected | {'item': None})) == 't'

    # Given: whitespace, empty or absent definitions. When: read. Then: JSON null, not empty.
    for code in ('2001020206', '2001020207', '2001020208'):
        assert run.sql(f"SELECT catalog.live_ncs_unit_v1({run.q(code)})"
                       "->'item'->'definition'='null'::jsonb") == 't'
    assert run.sql("SELECT catalog.live_ncs_unit_v1('2001020206')"
                   "->'item'->'level'='null'::jsonb") == 't'

    # Given: invalid filters. When: read. Then: the established P0001 filter error is raised.
    for value in (None, '', '200102020', '20010202050', '200102020x',
                  ' 2001020205', '2001020205\n',
                  '\uff12\uff10\uff10\uff11\uff10\uff12\uff10\uff12\uff10\uff15'):
        argument = 'NULL' if value is None else run.q(value)
        error(f'SELECT catalog.live_ncs_unit_v1({argument})', 'INVALID_LIVE_FILTER')

    # Given: restricted grants. When: reader calls in a read-only transaction. Then: success.
    run.sql((run.ROOT / 'hop/ontology/sql/029_live_ncs_unit.sql').read_text())
    run.sql((run.ROOT / 'hop/ontology/sql/catalog_reader_grants.psql').read_text())
    assert run.sql('BEGIN READ ONLY; SET LOCAL ROLE jobtology_catalog_reader; '
                   "SELECT catalog.live_ncs_unit_v1('2001020205')="
                   + run.js(expected) + '; COMMIT') == 't'
    assert run.sql("SELECT prosecdef AND provolatile='s' AND "
                   "proconfig=ARRAY['search_path=pg_catalog, pg_temp'] "
                   "FROM pg_proc WHERE oid='catalog.live_ncs_unit_v1(text)'::regprocedure") == 't'
    assert run.sql("SELECT NOT EXISTS(SELECT 1 FROM pg_proc p,"
                   "LATERAL aclexplode(p.proacl) a "
                   "WHERE p.oid='catalog.live_ncs_unit_v1(text)'::regprocedure "
                   "AND a.grantee=0 AND a.privilege_type='EXECUTE')") == 't'
    assert run.sql("SELECT NOT has_schema_privilege('jobtology_catalog_reader',"
                   "'ingestion','USAGE')") == 't'

    # Given: no READY full run. When: read. Then: unavailable, not a misleading null item.
    run.sql("UPDATE ingestion.run SET state='FAILED' WHERE mode='FULL'")
    error("SELECT catalog.live_ncs_unit_v1('2001020205')", 'LIVE_SOURCE_UNAVAILABLE')


if __name__ == '__main__':
    run.PG = f'jobtology-ncs-unit-test-{uuid.uuid4().hex[:12]}'
    try:
        run.boot()
        check()
        print('LIVE NCS UNIT CHECKS PASSED', flush=True)
    finally:
        subprocess.run(['docker', 'rm', '-fv', run.PG], capture_output=True, check=False)
