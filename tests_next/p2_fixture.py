"""Loopback-only deterministic model. Real DSH owns the Agent and tools."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading


class ModelFixture:
    def __init__(self):
        self.requests = []
        self.recipe = []
        self.responses = 0
        self.call_id_prefix = 'call'
        self.block = False
        self.hold = threading.Event()
        self.waiting = threading.Event()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def handle(self):
                try: super().handle()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append(body)
                if fixture.block:
                    fixture.waiting.set()
                    if not fixture.hold.wait(30):
                        return
                child = any(
                    'P2_CHILD' in (content if isinstance(content, str) else '\n'.join(
                        b.get('text', '') for b in content if b.get('type') == 'text'))
                    for m in body.get('messages', []) if m.get('role') == 'user'
                    for content in [m.get('content', '')])
                index = fixture.responses
                if not child: fixture.responses += 1
                if not child and index < len(fixture.recipe):
                    name, args = fixture.recipe[index]
                    if name in ('$job_output', '$job_kill'):
                        texts = [b.get('text', '') for m in body.get('messages', [])
                                 for b in (m.get('content', []) if isinstance(m.get('content'), list) else [])
                                 for b in ([b] if b.get('type') == 'text' else b.get('content', []))
                                 if isinstance(b, dict)]
                        ids = re.findall(r'(?:background job |\[job(?: id)?:\s*)([^\]\s]+)', '\n'.join(texts), re.I)
                        if not ids:
                            raise AssertionError('background tool result did not supply a job id')
                        name = name[1:]
                        args = {**args, 'job_id': ids[-1]}
                    if name == '$mcp':
                        names = [t.get('function', t)['name'] for t in body.get('tools',[])
                                 if 'echo' in t.get('function', t).get('name','')]
                        name = names[0] if len(names)==1 else 'missing_mcp_fixture'
                    delta = {"role":"assistant", "content":None, "tool_calls":[{"index":0,"id":f"{fixture.call_id_prefix}-{index}","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}
                    reason = 'tool_calls'
                else:
                    delta = {"role":"assistant","content":"P2_CHILD_DONE" if child else "P2_FIXTURE_DONE"}
                    reason = 'stop'
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                # DSH 0.2 uses Messages; retain Chat Completions for 0.1 fixtures.
                if self.path.rstrip('/').endswith('/messages'):
                    calls = delta.get('tool_calls', [])
                    block = ({'type': 'tool_use', 'id': calls[0]['id'],
                              'name': calls[0]['function']['name'], 'input': {}}
                             if calls else {'type': 'text', 'text': ''})
                    update = ({'type': 'input_json_delta', 'partial_json': calls[0]['function']['arguments']}
                              if calls else {'type': 'text_delta', 'text': delta['content']})
                    events = [
                        {'type': 'message_start', 'message': {'id': f'fixture-{index}', 'type': 'message',
                         'role': 'assistant', 'model': body.get('model'), 'content': [],
                         'usage': {'input_tokens': 100, 'output_tokens': 0}}},
                        {'type': 'content_block_start', 'index': 0, 'content_block': block},
                        {'type': 'content_block_delta', 'index': 0, 'delta': update},
                        {'type': 'content_block_stop', 'index': 0},
                        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use' if calls else 'end_turn'},
                         'usage': {'output_tokens': 10}},
                        {'type': 'message_stop'},
                    ]
                    for event in events:
                        self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode())
                    self.wfile.flush()
                    return
                for piece in ({"choices":[{"index":0,"delta":delta,"finish_reason":None}]},
                              {"choices":[{"index":0,"delta":{},"finish_reason":reason}],"usage":{"prompt_tokens":100,"completion_tokens":10,"total_tokens":110}}):
                    payload = {"id":f"fixture-{index}","object":"chat.completion.chunk","model":body.get('model','deepseek-flash'),"created":1, **piece}
                    self.wfile.write(('data: '+json.dumps(payload)+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def url(self):
        return 'http://127.0.0.1:'+str(self.server.server_port)
