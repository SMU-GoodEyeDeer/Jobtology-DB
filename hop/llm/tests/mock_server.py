"""HTTPS OpenRouter-shaped fixture server, reachable only on the disposable test network."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import ssl
import time

def extract(source):
    if '담당 업무' not in source.get('eligibility_text',''):
        return dict(positions=[],duties=[],requirements=[],duties_status='attachment_required')
    duty='데이터베이스 설계 및 구축'
    req='SQL 자격증 또는 데이터 자격증 중 하나'
    return dict(positions=[],duties=[dict(position=None,text=duty,evidence=dict(field='eligibility_text',quote=duty))],
      requirements=[dict(position=None,category='qualification',importance='required',logic='any_of',text=req,evidence=dict(field='eligibility_text',quote=req))],duties_status='explicit')

def extract_v2(passages):
    def ref(text): return [next(p['id'] for p in passages if text in p['text'])]
    if not any('담당 업무' in p['text'] for p in passages):
        return dict(positions=[],duties=[],requirements=[],duties_status='attachment_required')
    duty='데이터베이스 설계 및 구축';req='SQL 자격증 또는 데이터 자격증 중 하나'
    return dict(positions=[],duties=[dict(position_ids=[],text=duty,evidence_ids=ref(duty))],
      requirements=[dict(position_ids=[],category='qualification',kind='eligibility',logic='any_of',text=req,evidence_ids=ref(req),
      expression=[dict(op='any_of',text='',children=[1,2]),dict(op='atom',text='SQL 자격증',children=[]),dict(op='atom',text='데이터 자격증',children=[])])],duties_status='explicit')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers['Authorization']=='Bearer dummy-test-key'
        assert body['stream'] is False and body['provider']['require_parameters'] is True
        assert body['response_format']['json_schema']['strict'] is True
        assert body['trace']['posting_id'] and body['trace']['attempt_id']
        user=json.loads(body['messages'][1]['content'])
        assert 'gold' not in user and 'labels' not in user
        with Path('/test/requests.jsonl').open('a') as f:f.write(json.dumps(body,ensure_ascii=False)+'\n')
        if user.get('source_encoding')=='field-lines-and-tables-v1' and 'source_passages' in user:
            # Test fixture decoding only; production decoding/assembly is native SQL.
            user['source_passages']=[dict(id=field+':'+str(number),field=field,text=text)
                for field,lines in user['source_passages'].items() for number,text in lines]
        if body['model']=='test/rate-limited':
            raw=json.dumps(dict(error=dict(code=429,message='Synthetic upstream quota limit'))).encode()
            self.send_response(429);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            return
        if body['model'].startswith('test/delayed-'):
            marker=Path('/test')/('delay-'+body['model'].removeprefix('test/delayed-'))
            marker.write_text(body['trace']['attempt_id'])
            time.sleep(8)
        if 'source_passages' in user:output=extract_v2(user['source_passages'])
        elif 'source' in user:output=extract(user['source'])
        else:output=dict(matches=[dict(competency_code='2001020101_24v1',duty_index=0,reason='명시된 데이터베이스 설계 업무와 일치한다.')],outcome='matched')
        if body['trace']['release'] in ('ko-v3','ko-v4','ko-v5','ko-v6','ko-v7','ko-link-v1') and 'requirements' in output:
            for section in ('duties','requirements'):
                for item in output[section]:
                    item['text_parts']=[item.pop('text')]
                    for node in item.get('expression',[]):
                        text=node.pop('text');node['parts']=[text] if text else []
        if body['trace']['release'] in ('ko-v6','ko-v7') and 'requirements' in output:
            for item in output['requirements']:
                nodes=item.pop('expression')
                def nested(index):
                    row=nodes[index]
                    return dict(op=row['op'],parts=row['parts'],children=[nested(i) for i in row['children']])
                item['condition']=nested(0) if nodes else None
            # These are synthetic source cases, not a general extraction implementation.
            for passage in user['source_passages']:
                value=passage['text']
                if passage['field']=='preference_text' and value=='우대: 데이터 분석 경력':
                    output['requirements'].append(dict(position_ids=[],category='experience',kind='preference',logic='single',
                        text_parts=[value],evidence_ids=[passage['id']],condition=None))
                elif value.startswith('학력 및 경력 제한 없음.'):
                    output['requirements'].append(dict(position_ids=[],category='education',kind='unrestricted',logic='single',
                        text_parts=['학력 및 경력 제한 없음.'],evidence_ids=[passage['id']],condition=None))
            used={pid for kind in ('positions','duties','requirements') for row in output[kind] for pid in row['evidence_ids']}
            output['unhandled_passages']=[dict(evidence_id=p['id'],disposition='attachment_reference' if '첨부' in p['text'] else 'procedure',
                reason='Synthetic fixture source disposition',duplicate_of=None) for p in user['source_passages']
                if p['field'].endswith('_text') and p['id'] not in used]
            if body['trace']['release']=='ko-v7':
                output['unhandled_ranges']=[dict(first_id=r['evidence_id'],last_id=r['evidence_id'],
                    disposition=r['disposition'],reason=r['reason'],duplicate_of=r['duplicate_of'],context_kind=None)
                    for r in output.pop('unhandled_passages')]
        if body['trace']['release']=='ko-link-v1' and 'requirements' in output:
            output['requirements']=[]
        if body['model']=='test/source-bound-invalid':
            output['requirements'][0]['evidence_ids']=['eligibility_text:9999']
        result=dict(id='mock-'+body['trace']['attempt_id'],model=body['model'],provider='local-test',choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output,ensure_ascii=False)))],usage=dict(prompt_tokens=100,completion_tokens=50,cost=0.001))
        raw=json.dumps(result,ensure_ascii=False).encode()
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain('/test/cert.pem','/test/key.pem')
server.socket=ctx.wrap_socket(server.socket,server_side=True)
server.serve_forever()
