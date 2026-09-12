"""Loopback-only deterministic model. Real DSH owns the Agent and tools."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


class ModelFixture:
    def __init__(self):
        self.requests = []
        self.recipe = []
        self.responses = 0
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
                child = any('P2_CHILD' in json.dumps(m.get('content','')) for m in body.get('messages',[]) if m.get('role')=='user')
                index = fixture.responses
                if not child: fixture.responses += 1
                if not child and index < len(fixture.recipe):
                    name, args = fixture.recipe[index]
                    if name == '$mcp':
                        names = [t['function']['name'] for t in body.get('tools',[]) if 'echo' in t.get('function',{}).get('name','')]
                        name = names[0] if len(names)==1 else 'missing_mcp_fixture'
                    delta = {"role":"assistant", "content":None, "tool_calls":[{"index":0,"id":f"call-{index}","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}
                    reason = 'tool_calls'
                else:
                    delta = {"role":"assistant","content":"P2_CHILD_DONE" if child else "P2_FIXTURE_DONE"}
                    reason = 'stop'
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
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
