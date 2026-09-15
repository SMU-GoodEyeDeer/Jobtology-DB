"""Verify exact full-corpus packet decoding and size against saved native requests.

No inference or production writes. Inputs are protected JSON exports. The native
full request dry run is still needed before deployment/paid expansion claims.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import subprocess
import tempfile
from document_packet_checks import assert_packet


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser()
    p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--requests',type=Path,required=True)
    p.add_argument('--output-dir',type=Path)
    args=p.parse_args()
    folder=args.output_dir or Path(tempfile.mkdtemp(prefix='jobtology-packet-real-'))
    folder.mkdir(parents=True,exist_ok=True)
    inputs={r['posting_id']:r for r in json.loads(args.inputs.read_text())}
    requests={r['posting_id']:r for r in json.loads(args.requests.read_text())}
    assert inputs.keys()==requests.keys() and inputs
    data=[]
    for posting,r in inputs.items():
        assert r['source_hash']==requests[posting]['source_hash']
        assert requests[posting]['request']['trace']['span_name']=='extract'
        old_user=json.loads(requests[posting]['request']['messages'][1]['content'])
        assert set(old_user)=={'source_passages','source_accounting','source_documents','document_outcomes','input_contract','input_instructions'}
        data.append(r|dict(request=requests[posting]['request'],old_chars=requests[posting]['old_chars']))
    q=lambda s:"'"+s.replace("'","''")+"'"
    statement="BEGIN;SET LOCAL standard_conforming_strings=on;SET LOCAL statement_timeout='300s';CREATE TEMP TABLE packet_fixture AS SELECT x FROM jsonb_array_elements("+q(json.dumps(data,ensure_ascii=False))+"::jsonb) x;\n"
    statement+="""WITH packets AS MATERIALIZED (SELECT x,enrichment.document_packet_v1(x->'source_data') packet FROM packet_fixture)
SELECT jsonb_build_object('posting_id',x->>'posting_id','source_hash_matches',enrichment.hash((x->'source_data')::text)=x->>'source_hash',
 'old_chars',x->'old_chars','old_request_matches',length((x->'request')::text)=(x->>'old_chars')::integer,
 'packet',packet,'passages',enrichment.source_passages_v2(x->'source_data'),
 'request_chars',length(jsonb_set(x->'request','{messages,1,content}',to_jsonb(packet::text))::text)) FROM packets ORDER BY x->>'posting_id';ROLLBACK;"""
    result=subprocess.run(['docker','exec','-i','jobtology-ontology-test-pg','psql','-X','-qAt','-v','ON_ERROR_STOP=1',
                           '-U','postgres','-d','ontologytest'],input=statement,text=True,capture_output=True,check=True)
    decoded=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert len(decoded)==len(inputs)
    (folder/'packets.json').write_text(json.dumps(decoded,ensure_ascii=False))
    counts=collections.Counter();sizes=[]
    for row in decoded:
        assert row['source_hash_matches'] and row['old_request_matches']
        counts.update(assert_packet(inputs[row['posting_id']]['source_data'],row['packet'],row['passages']))
        counts.update(postings=1,passages=len(row['passages']))
        sizes.append({k:row[k] for k in ['posting_id','old_chars','request_chars']})
    summary=dict(counts)|dict(max_request_characters=max(r['request_chars'] for r in sizes),
        median_request_characters=sorted(r['request_chars'] for r in sizes)[len(sizes)//2],
        total_request_characters=sum(r['request_chars'] for r in sizes),
        oversized=[r for r in sizes if r['request_chars']>200000],rows=sizes)
    (folder/'verification.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'}|dict(output_dir=str(folder))),flush=True)


if __name__=='__main__':main()
