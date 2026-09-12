"""Tiny stdio MCP fixture; production uses DSH's existing MCP client."""
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion':request['params']['protocolVersion'], 'capabilities':{'tools':{}}, 'serverInfo':{'name':'sumika-p2-fixture','version':'1.0.0'}}
    elif method == 'tools/list':
        result = {'tools':[{'name':'echo','description':'Return the exact P2 fixture challenge.', 'inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}
    elif method == 'tools/call':
        result = {'content':[{'type':'text','text':request['params']['arguments']['text']}]}
    elif method == 'ping': result = {}
    else:
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'unsupported fixture method'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)
