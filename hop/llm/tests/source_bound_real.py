"""Verify frozen real inputs with native PostgreSQL and an independent JSON Schema validator.

No inference or production writes. Run with uv --with jsonschema. Input is a
protected JSON array of posting_id, source_data, source_hash and bundle_id rows.
"""
from pathlib import Path
import subprocess,json,os,re,time,argparse,tempfile
from jsonschema import Draft202012Validator
os.umask(0o077)
parser=argparse.ArgumentParser()
parser.add_argument('--inputs',type=Path,required=True)
parser.add_argument('--container',default='jobtology-ontology-test-pg')
parser.add_argument('--database',default='ontologytest',choices=['ontologytest','ontologyrealtest','hoptest'])
parser.add_argument('--output-dir',type=Path)
args=parser.parse_args()
assert args.container in ['jobtology-ontology-test-pg','jobtology-llm-test-pg'],'Use a disposable fixture container'
folder=args.output_dir or Path(tempfile.mkdtemp(prefix='jobtology-source-bound-check-'))
folder.mkdir(parents=True,exist_ok=True)
rows=json.loads(args.inputs.read_text())
assert rows and len({r['posting_id'] for r in rows})==len(rows)
q=lambda s:"'"+s.replace("'","''")+"'"
sql="BEGIN;SET LOCAL statement_timeout='240s'; CREATE TEMP TABLE source_bound_fixture AS SELECT x FROM jsonb_array_elements("+q(json.dumps(rows,ensure_ascii=False))+"::jsonb) x;\n"
sql+="SELECT jsonb_build_object('posting_id',x->>'posting_id','source_hash_matches',enrichment.hash((x->'source_data')::text)=x->>'source_hash','schema',enrichment.source_bound_schema_v1(p.output_schema,x->'source_data'),'passages',enrichment.source_passages_v2(x->'source_data'),'context',enrichment.source_accounting_context_v1(x->'source_data')) FROM source_bound_fixture CROSS JOIN enrichment.prompt p WHERE p.version='ko-v7' AND p.stage='extract' ORDER BY x->>'posting_id'; ROLLBACK;"
start=time.monotonic()
p=subprocess.run(['docker','exec','-i',args.container,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',args.database],input=sql,text=True,capture_output=True,check=True)
results=[json.loads(l) for l in p.stdout.splitlines() if l.startswith('{')]
(folder/'schemas.json').write_text(json.dumps(results,ensure_ascii=False))
assert len(results)==len(rows) and all(r['source_hash_matches'] for r in results)
by_id={r['posting_id']:r for r in rows}
summary=[]
for r in results:
 s=r['schema'];Draft202012Validator.check_schema(s)
 source=by_id[r['posting_id']]['source_data'];passages=r['passages'];known={p['id'] for p in passages}
 # The native source positions must reproduce exact original strings and offsets.
 for p in passages:
  field,number=p['id'].rsplit(':',1)
  assert p['text']==source[field].split('\n')[int(number)-1]
  assert source[field][p['start']-1:p['end']]==p['text']
 all_pattern=re.compile(s['$defs']['source_evidence_id']['pattern'])
 assert all(all_pattern.fullmatch(pid) for pid in known)
 assert not all_pattern.fullmatch('invented_field:1')
 for f in r['context']['narrative_fields']:
  allowed={p['id'] for p in passages if p['field']==f}
  pat=re.compile(s['$defs']['range_id_'+f]['pattern'])
  for n in range(len(source[f].split('\n'))+2):
   pid=f+':'+str(n);assert bool(pat.fullmatch(pid))==(pid in allowed),(r['posting_id'],pid)
  assert not pat.fullmatch('title:1')
  ordered=sorted(allowed,key=lambda x:int(x.rsplit(':',1)[1]));first,last=ordered[0],ordered[-1]
  probe=dict(positions=[],duties=[],requirements=[],duties_status='not_stated',unhandled_ranges=[dict(first_id=first,last_id=last,disposition='procedure',context_kind=None,duplicate_of=None,reason='Grammar probe, not semantic acceptance')])
  Draft202012Validator(s).validate(probe)
 def walk(node):
  if isinstance(node,dict):
   yield node
   for x in node.values():yield from walk(x)
  elif isinstance(node,list):
   for x in node:yield from walk(x)
 nodes=list(walk(s));enums=sum(len(n.get('enum',[])) for n in nodes);props=sum(len(n.get('properties',{})) for n in nodes)
 assert enums<=1000 and props<=5000,(r['posting_id'],enums,props)
 summary.append(dict(posting_id=r['posting_id'],passages=len(passages),narrative_fields=len(r['context']['narrative_fields']),schema_characters=len(json.dumps(s,ensure_ascii=False)),enum_values=enums,object_properties=props))
report=dict(postings=len(results),passages=sum(r['passages'] for r in summary),max_schema_characters=max(r['schema_characters'] for r in summary),max_fields=max(r['narrative_fields'] for r in summary),elapsed_seconds=round(time.monotonic()-start,2),rows=summary)
(folder/'verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='rows'}|{'output_dir':str(folder)}),flush=True)
