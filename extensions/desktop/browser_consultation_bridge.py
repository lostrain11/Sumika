"""BrowserSkill-backed consultation bridge with explicit site permissions."""
import json,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
from .browser_skill import BrowserSkillClient

class BrowserConsultationBridge:
    def __init__(self,client:BrowserSkillClient,session_id,*,tab_id=None,identity=None):
        self.client=client;self.session_id=session_id;self.tab_id=tab_id
        self.identity = dict(identity) if identity is not None else None
        if not isinstance(session_id,str) or not session_id.strip():raise ValueError('session id required')
        if tab_id is not None and (type(tab_id) is not int or tab_id<0):raise ValueError('invalid tab identity')
    @staticmethod
    def _origin(url):
        if not isinstance(url,str) or any(c.isspace() or ord(c)<32 for c in url) or '\\' in url:raise ValueError('invalid URL')
        p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username is not None or p.password is not None:raise ValueError('invalid URL')
        return (p.scheme,p.hostname.encode('idna').decode().lower(),p.port or (443 if p.scheme=='https' else 80))
    def _expected(self,site):
        return self._origin(site if '://' in site else 'https://'+site)
    def _authorized_session(self,site,action):
        if not self.client.permission(site,action):raise PermissionError(f'site {action} authorization required')
        sessions=self.client.session_list()
        if not any(isinstance(s,dict) and (s.get('session_id') or s.get('id'))==self.session_id for s in sessions):
            raise PermissionError('BrowserSkill session is no longer active')
        if self.identity is not None:
            current = self.client._read()['sites'].get(site.casefold(), {}).get('binding')
            if current != self.identity:
                raise PermissionError('site binding changed; resolve again')
            matches = [s for s in sessions if s.get('session_id') == self.session_id]
            if len(matches) != 1 or any(matches[0].get(k) != self.identity.get(k)
                                      for k in ('browser_instance_id', 'agent_window_id')):
                raise PermissionError('BrowserSkill session identity changed')
    def _tab(self,site=None):
        if self.tab_id is None:raise PermissionError('explicit Agent tab binding required')
        value=self._run(['tab','list','--json','--session',self.session_id,'--scope','agent'])
        rows=value.get('tabs') if isinstance(value,dict) else None
        if not isinstance(rows,list):raise RuntimeError('invalid tab inventory')
        matches=[r for r in rows if isinstance(r,dict) and r.get('tab_id')==self.tab_id and r.get('scope')=='agent']
        if len(matches)!=1:raise PermissionError('bound Agent tab unavailable')
        if self.identity is not None and matches[0].get('window_id') != self.identity.get('agent_window_id'):
            raise PermissionError('bound Agent tab window changed')
        if site is not None and self._origin(matches[0].get('url'))!=self._expected(site):raise PermissionError('current tab origin differs from authorized site')
        return str(self.tab_id)
    def navigate(self,site,url):
        self._authorized_session(site,'read')
        if self._origin(url)!=self._expected(site):raise PermissionError('navigation origin differs from authorized site')
        tab=self._tab()
        result=self._run(['navigate','--json','--session',self.session_id,'--tab-id',tab,url])
        self._tab(site) # Reject cross-origin redirects before reading page contents.
        return result
    def send(self,site,selector,text):
        self._authorized_session(site,'send')
        if not isinstance(selector,str) or not selector.strip() or not isinstance(text,str) or not text.strip():raise ValueError('selector and text required')
        tab=self._tab(site)
        result=self._run(['fill','--json','--session',self.session_id,'--tab-id',tab,'--selector',selector,'--value',text])
        self._tab(site)
        return {'status':'filled','submitted':False,'result':result}
    def observe(self,site,*,max_tokens=3000):
        if type(max_tokens) is not int or not 100<=max_tokens<=10000:raise ValueError('invalid observation budget')
        self._authorized_session(site,'read')
        tab=self._tab(site)
        value=self._run(['observe','--json','--session',self.session_id,'--tab-id',tab,'--max-tokens',str(max_tokens)])
        self._tab(site)
        if not isinstance(value,(dict,list)):return {'status':'unknown','reason':'invalid observation'}
        if len(json.dumps(value,ensure_ascii=False).encode('utf8'))>max_tokens*16:raise RuntimeError('observation exceeds output budget')
        return {'status':'observed','observation':value}

    def submit(self, site, prompt, *, request_id, prompt_selector,
               submit_selector, approved=False, capture=None):
        """Host-only submission API; selectors come from a checked site adapter.

        Not exposed as a generic HTTP click API. Page-local guards bind each
        mutation to its origin and expected draft within one synchronous call.
        """
        from .consultation_journal import ConsultationJournal
        if self.identity is None:
            raise PermissionError('persisted owned binding required for submission')
        if any(not isinstance(s,str) or not s.strip() for s in (prompt_selector,submit_selector)):
            raise ValueError('checked site selectors required')
        journal = ConsultationJournal(self.client.registry.parent/'browser-consultations.sqlite3')
        expected_path = None

        def capture_baseline():
            nonlocal expected_path
            snapshot = capture()
            expected_path = urlsplit(snapshot.get('url', '')).path
            return snapshot

        def guarded(action):
            self._authorized_session(site, 'read' if action in ('inspect','ready') else 'send')
            tab = self._tab(site)
            scheme, host, port = self._expected(site)
            origin = f'{scheme}://{host}' + (f':{port}' if port != (443 if scheme=='https' else 80) else '')
            config = dict(origin=origin,editor=prompt_selector,submit=submit_selector,
                          action=action,prompt=prompt,expectedPath=expected_path)
            script = Path(__file__).with_name('consultation_guard.js').read_text(encoding='utf8')
            result = self._run(['evaluate','--json','--session',self.session_id,'--tab-id',tab,
                                '('+script+')('+json.dumps(config)+')'])
            self._tab(site)
            value = result.get('value') if isinstance(result,dict) and result.get('ok') is True else None
            if not isinstance(value,dict) or value.get('ok') is not True:
                raise RuntimeError('browser submission guard rejected operation')
            return value

        def preflight():
            self._authorized_session(site,'read')
            self._authorized_session(site,'send')
            self._tab(site)
            if guarded('inspect').get('empty') is not True:
                raise PermissionError('existing draft must be preserved')

        def dispatch():
            # Recheck revocation/binding after durable admission as well.
            journal.note(request_id,'checking')
            preflight()
            journal.note(request_id,'filling')
            fill_result = guarded('fill')
            if fill_result.get('filled') is not True and fill_result.get('fill_requested') is not True:
                raise RuntimeError('draft fill unconfirmed')
            journal.note(request_id,'waiting_ready')
            deadline = time.monotonic()+3
            while guarded('ready').get('ready') is not True:
                if time.monotonic() >= deadline:
                    raise RuntimeError('submit control not ready')
                time.sleep(0.15)
            journal.note(request_id,'clicking')
            result = guarded('submit')
            journal.note(request_id,'acknowledged')
            return result

        operation = {**self.identity, 'prompt_selector':prompt_selector,
                     'submit_selector':submit_selector}
        return journal.submit(request_id,site=site,prompt=prompt,binding=operation,
                              approved=approved,preflight=preflight,dispatch=dispatch,
                              capture=capture_baseline if capture is not None else None)
    def _run(self,args):
        if not self.client.enabled or not self.client.executable:raise PermissionError('browser skill unavailable')
        try:out=subprocess.run([self.client.executable,*args],capture_output=True,text=True,encoding='utf8',timeout=35)
        except (OSError,subprocess.TimeoutExpired):raise RuntimeError('BrowserSkill operation outcome unknown; do not replay automatically') from None
        if out.returncode:raise RuntimeError('BrowserSkill operation failed')
        try:return json.loads(out.stdout)
        except json.JSONDecodeError:raise RuntimeError('invalid BrowserSkill operation response') from None
