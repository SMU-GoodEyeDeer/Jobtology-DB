"""Disposable PostgreSQL round trip for source-bound native Hop review packets."""
from pathlib import Path
import json
import subprocess
import time

import common_postings as fixture
import scope_completion as mixed

ROOT=Path(__file__).resolve().parents[3]
NAME=fixture.NAME
sql=fixture.sql
run=fixture.run


def statement(packet):
    body=json.dumps(packet,ensure_ascii=False,separators=(',',':'))
    assert '$scope_packet$' not in body
    return f"SELECT cs.apply_scope_review_v1($scope_packet${body}$scope_packet$::jsonb)"


def rejection(command, marker):
    result=subprocess.run(
        ['docker','exec','-i',NAME,'psql','-X','-v','ON_ERROR_STOP=1',
         '-A','-t','-U','postgres','-d','postgres'],
        input=command,text=True,capture_output=True)
    assert result.returncode!=0 and marker in result.stderr,(marker,result.stderr)


def named(packet):
    packet['reviewer']='Synthetic technical reviewer'
    packet['reviewer_kind']='human'
    for case in packet['cases']:
        name=case['context']['role_name']
        if name in ('데이터 엔지니어','백엔드 개발자'):
            case['decision']='IN_SCOPE'
            case['family']='DATA' if name=='데이터 엔지니어' else 'SOFTWARE'
            case['notes']='Advertised technical position: '+name
        else:
            case['decision']='OUT_OF_SCOPE'
            case['family']=None
            case['notes']='Accounting administration is outside technical scope'
    return packet


def main():
    try:
        run(['docker','run','-d','--name',NAME,'-e',
             'POSTGRES_HOST_AUTH_METHOD=trust','postgres:17-alpine'])
        for _ in range(50):
            try:
                if 'PostgreSQL init process complete' in run(['docker','logs',NAME]) \
                   and sql('SELECT 1')=='1':
                    break
            except RuntimeError:
                pass
            time.sleep(0.2)
        else: raise RuntimeError('PostgreSQL fixture did not start')
        sql(fixture.SETUP)
        sql((ROOT/'hop/cs/sql/001_common_postings.sql').read_text())
        sql(mixed.EXTRA)
        sql("""
INSERT INTO cs.source_snapshot(source_id,snapshot_run_id,state,completed_at)
VALUES ('feed_a','feed-1','READY',clock_timestamp());
INSERT INTO cs.posting_input(source_id,snapshot_run_id,source_posting_id,
 employer,title,normalized,source_data)
VALUES ('feed_a','feed-1','123','기관 B','백엔드 개발자',
 '{"title":"백엔드 개발자"}',
 '{"title":"백엔드 개발자","duties_text":"API 개발"}');
""")
        sql((ROOT/'hop/cs/sql/002_scope.sql').read_text())
        sql((ROOT/'hop/cs/sql/004_scope_packets.sql').read_text())
        original=json.loads(sql("SELECT cs.prepare_scope_review_v1('','','',10,'Synthetic exporter')"))
        assert len(original['cases'])==3,original
        assert {c['context']['source_id'] for c in original['cases']}=={'job_alio','feed_a'}
        assert all(c['decision'] is None and c['family'] is None for c in original['cases'])
        just_alio=json.loads(sql("SELECT cs.prepare_scope_review_v1('','','job-alio:posting:123',10,'Synthetic exporter')"))
        assert len(just_alio['cases'])==2 and all(c['context']['source_id']=='job_alio' for c in just_alio['cases'])
        rejection("SELECT cs.prepare_scope_review_v1('','','missing:posting',10,'Synthetic exporter')",
                  'UNKNOWN_OR_DUPLICATE_SCOPE_POSTING_IDENTITY')
        packet=named(original)
        # Any edited context must roll back *every* decision in the file.
        tampered=json.loads(json.dumps(packet))
        tampered['cases'][-1]['context']['role_name']='Edited role'
        rejection(statement(tampered),'SCOPE_REVIEW_CONTEXT_OR_DECISION_CHANGED')
        assert sql('SELECT count(*) FROM cs.scope_decision')=='0'
        # A corrected position makes an old packet stale even if its posting ID
        # remains unchanged; the importer must reject the whole transaction.
        sql("UPDATE enrichment.extraction_review_state SET extraction="
            "jsonb_set(extraction,'{positions,0,name}',to_jsonb('데이터 분석가'::text)) "
            "WHERE revision_id='legacy-revision'")
        rejection(statement(packet),'SCOPE_REVIEW_CONTEXT_OR_DECISION_CHANGED')
        assert sql('SELECT count(*) FROM cs.scope_decision')=='0'
        sql("UPDATE enrichment.extraction_review_state SET extraction="
            "jsonb_set(extraction,'{positions,0,name}',to_jsonb('데이터 엔지니어'::text)) "
            "WHERE revision_id='legacy-revision'")
        # A named but incomplete technical choice is also atomic.
        bad_family=json.loads(json.dumps(packet))
        next(c for c in bad_family['cases'] if c['decision']=='IN_SCOPE')['family']=None
        rejection(statement(bad_family),'INVALID_EXPLICIT_SCOPE_REVIEW_DECISION')
        assert sql('SELECT count(*) FROM cs.scope_decision')=='0'
        duplicate=json.loads(json.dumps(packet))
        duplicate['cases'].append(json.loads(json.dumps(duplicate['cases'][0])))
        rejection(statement(duplicate),'DUPLICATE_SCOPE_REVIEW_CASE')
        first=json.loads(sql(statement(packet)))
        assert first['new_decisions']==3 and first['unchanged_decisions']==0 and not first['replayed'],first
        assert sql('SELECT count(*) FROM cs.scope_decision')=='3'
        assert sql('SELECT count(*) FROM cs.scope_review_import')=='1'
        replay=json.loads(sql(statement(packet)))
        assert replay['replayed'] and replay['import_id']==first['import_id'],replay
        assert sql('SELECT count(*) FROM cs.scope_decision')=='3'
        assert sql('SELECT count(*) FROM cs.scope_review_import')=='1'
        rejection("UPDATE cs.scope_review_import SET reviewer='edited'",'SCOPE_REVIEW_RECEIPT_IS_IMMUTABLE')
        sql((ROOT/'hop/cs/sql/004_scope_packets.sql').read_text())
        assert sql('SELECT count(*) FROM cs.scope_review_import')=='1'
        # A freshly exported packet can record the same named choices without
        # duplicating decisions; a later contrary choice can be superseded.
        fresh=named(json.loads(sql("SELECT cs.prepare_scope_review_v1('','','',10,'Synthetic exporter')")))
        no_change=json.loads(sql(statement(fresh)))
        assert no_change['new_decisions']==0 and no_change['unchanged_decisions']==3,no_change
        assert sql('SELECT count(*) FROM cs.scope_decision')=='3'
        print('scope packets: source collision, atomic stale/tampered rejection, named review, immutable receipt and replay passed')
    finally:
        subprocess.run(['docker','rm','-f',NAME],capture_output=True)


if __name__=='__main__': main()
