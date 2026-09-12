"""HTTPS OpenRouter-shaped fixture server, reachable only on the disposable test network."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import ssl

def extract(source):
    if '담당 업무' not in source.get('eligibility_text',''):
        return dict(positions=[],duties=[],requirements=[],duties_status='attachment_required')
    duty='데이터베이스 설계 및 구축'
    req='SQL 자격증 또는 데이터 자격증 중 하나'
    return dict(positions=[],duties=[dict(position=None,text=duty,evidence=dict(field='eligibility_text',quote=duty))],
      requirements=[dict(position=None,category='qualification',importance='required',logic='any_of',text=req,evidence=dict(field='eligibility_text',quote=req))],duties_status='explicit')

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
        if 'source' in user:output=extract(user['source'])
        else:output=dict(matches=[dict(competency_code='2001020101_24v1',duty_index=0,reason='명시된 데이터베이스 설계 업무와 일치한다.')],outcome='matched')
        result=dict(id='mock-'+body['trace']['attempt_id'],model=body['model'],provider='local-test',choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output,ensure_ascii=False)))],usage=dict(prompt_tokens=100,completion_tokens=50,cost=0.001))
        raw=json.dumps(result,ensure_ascii=False).encode()
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain('/test/cert.pem','/test/key.pem')
server.socket=ctx.wrap_socket(server.socket,server_side=True)
server.serve_forever()
