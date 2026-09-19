"""Small, explicit Ollama adapter for role-only local inference."""
import json, urllib.request, urllib.error

class OllamaError(RuntimeError): pass

class OllamaProvider:
    def __init__(self, endpoint='http://127.0.0.1:11434', *, enabled=True, timeout=30):
        self.endpoint=endpoint.rstrip('/'); self.enabled=enabled; self.timeout=timeout
        if not isinstance(self.endpoint,str) or not self.endpoint.startswith(('http://','https://')): raise ValueError('invalid endpoint')
        if type(enabled) is not bool or type(timeout) is not int or timeout<1 or timeout>600: raise ValueError('invalid provider options')
    def _request(self,path,payload=None):
        if not self.enabled: raise PermissionError('local provider disabled')
        data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
        req=urllib.request.Request(self.endpoint+path,data=data,headers={'Content-Type':'application/json'} if data else {})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r: return json.loads(r.read().decode('utf8'))
        except (OSError,ValueError) as exc: raise OllamaError('Ollama outcome unknown') from exc
    def health(self):
        try: self._request('/api/tags'); return {'status':'ready','endpoint':self.endpoint}
        except (OllamaError,PermissionError): return {'status':'unavailable','endpoint':self.endpoint}
    def models(self):
        value=self._request('/api/tags'); rows=value.get('models') if isinstance(value,dict) else None
        if not isinstance(rows,list): raise OllamaError('invalid model inventory')
        return [r for r in rows if isinstance(r,dict) and isinstance(r.get('name'),str)]
    def generate(self, *, model, messages, options=None, keep_alive='5m', format=None):
        if not isinstance(model,str) or not model.strip() or not isinstance(messages,list) or not messages: raise ValueError('model and messages required')
        payload={'model':model,'messages':messages,'stream':False,'keep_alive':keep_alive}
        if format is not None:
            if not isinstance(format,dict): raise ValueError('format must be a JSON schema')
            payload['format']=format
        if options is not None:
            if not isinstance(options,dict): raise ValueError('options must be object')
            payload['options']=dict(options)
        value=self._request('/api/chat',payload)
        if not isinstance(value,dict): raise OllamaError('invalid generation response')
        message=value.get('message')
        if not isinstance(message,dict) or not isinstance(message.get('content'),str): raise OllamaError('invalid generation message')
        usage={k:value[k] for k in ('prompt_eval_count','eval_count','total_duration') if k in value}
        return {'text':message['content'],'usage':usage,'model':value.get('model',model),'provider':'ollama','finish_reason':value.get('done_reason')}
