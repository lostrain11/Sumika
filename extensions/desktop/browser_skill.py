"""Bundled BrowserSkill backend boundary; no automatic browser launch.

The installer ships a pinned BrowserSkill build. The adapter still permits an
explicit executable for upgrades and tests, while never silently downloading.
"""
import json,shutil,subprocess,os,tempfile
from pathlib import Path
from sumika_next.paths import user_data_directory

class BrowserSkillClient:
    def __init__(self, executable=None, *, registry=None, enabled=True):
        self._available=enabled is True
        bundled=Path(__file__).resolve().parents[2]/'runtime'/'browserskill'/'bsk.exe'
        installed=Path(r'D:\Tools\BrowserSkill\0.1.11\bsk.exe')
        self.executable=executable or next((str(p) for p in (bundled,installed) if p.is_file()),None) or shutil.which('bsk')
        self.registry=(Path(registry).resolve() if registry else user_data_directory()/'browser-authorizations.json')
    @property
    def enabled(self):
        # Fresh and legacy registries both require an explicit opt-in. Re-read
        # for each operation so a running worker observes a user's disable.
        return self._available and self._read().get('enabled') is True
    def set_enabled(self, enabled):
        if type(enabled) is not bool:raise ValueError('enabled must be boolean')
        data=self._read();data['enabled']=enabled;self._write(data)
        return {'enabled':self.enabled}
    def _read(self):
        if not self.registry.exists():return {'schema_version':1,'sites':{}}
        data=json.loads(self.registry.read_text(encoding='utf8'))
        if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('sites'),dict):raise ValueError('invalid browser authorization registry')
        return data
    def _write(self,data):
        self.registry.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.browser-auth-',suffix='.tmp',dir=self.registry.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
            try:
                os.replace(temp,self.registry)
            except OSError as exc:
                # Some Windows filesystem filters reject ReplaceFile when the
                # destination has not been created yet; same-volume rename
                # preserves the no-partial-file property for first creation.
                if getattr(exc,'winerror',None)!=17:
                    raise
                # Windows security filters can reject ReplaceFile even on a
                # same-volume path. The fully written/fsynced temp is copied
                # only after replacement failed; never expose the temp name.
                shutil.copyfile(temp,self.registry)
                os.unlink(temp)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def status(self):
        if not self.enabled:return {'enabled':False,'status':'disabled'}
        if not self.executable:return {'enabled':True,'status':'unavailable'}
        try:
            out=subprocess.run([self.executable,'status','--json'],capture_output=True,text=True,encoding='utf8',timeout=10)
            if out.returncode:return {'enabled':True,'status':'error'}
            value=json.loads(out.stdout);return {'enabled':True,'status':'ready' if isinstance(value,dict) else 'unknown','raw':value}
        except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError):return {'enabled':True,'status':'error'}
    def authorize(self,site,profile,*,send=False,read=True):
        if not self.enabled:raise PermissionError('browser skill disabled')
        if not isinstance(site,str) or not site.strip() or not isinstance(profile,str) or not profile.strip():raise ValueError('site and profile required')
        if type(send) is not bool or type(read) is not bool:raise ValueError('invalid authorization flags')
        if self.registry is None:raise ValueError('authorization registry required')
        data=self._read();data['sites'][site.casefold()]={'profile':profile,'read':read,'send':send}
        self._write(data)
        return {'site':site.casefold(),'profile':profile,'read':read,'send':send}
    def revoke(self,site):
        data=self._read();removed=data['sites'].pop(site.casefold(),None);self._write(data)
        return {'site':site.casefold(),'revoked':removed is not None}
    def permission(self,site,action):
        if not self.enabled:raise PermissionError('browser skill disabled')
        entry=self._read()['sites'].get(site.casefold(),{})
        return entry.get(action,False) is True

    def session_start(self, *, browser=None, no_focus=True):
        """Start an Agent Window only after the caller has authorized it."""
        if not self.enabled or not self.executable or not Path(self.executable).is_file():raise PermissionError('browser skill unavailable')
        command=[self.executable,'session','start','--json']
        if browser:command += ['--browser',browser]
        if no_focus:command += ['--no-focus']
        out=subprocess.run(command,capture_output=True,text=True,encoding='utf8',timeout=20)
        if out.returncode:raise RuntimeError('BrowserSkill session start failed')
        try:value=json.loads(out.stdout)
        except json.JSONDecodeError:raise RuntimeError('invalid BrowserSkill session response') from None
        if not isinstance(value,dict):raise RuntimeError('invalid BrowserSkill session identity')
        return value

    def session_list(self):
        if not self.enabled or not self.executable or not Path(self.executable).is_file():return []
        out=subprocess.run([self.executable,'session','list','--json'],capture_output=True,text=True,encoding='utf8',timeout=10)
        if out.returncode:raise RuntimeError('BrowserSkill session list failed')
        value=json.loads(out.stdout)
        if not isinstance(value,list):raise RuntimeError('invalid BrowserSkill session list')
        return value

    def session_tabs(self, session_id):
        if not self.enabled or not self.executable or not Path(self.executable).is_file():
            return []
        out=subprocess.run([self.executable,'tab','list','--json','--session',session_id,'--scope','agent'],capture_output=True,text=True,encoding='utf8',timeout=10)
        if out.returncode: raise RuntimeError('BrowserSkill tab list failed')
        value=json.loads(out.stdout)
        tabs=value.get('tabs') if isinstance(value,dict) else None
        if not isinstance(tabs,list): raise RuntimeError('invalid BrowserSkill tab list')
        return tabs

    def open_site(self, site, session_id, browser_instance_id, agent_window_id):
        """Open a fixed consultation origin in an explicitly selected live window."""
        origins={'chat.deepseek.com':'https://chat.deepseek.com',
                 'www.kimi.com':'https://www.kimi.com','chatgpt.com':'https://chatgpt.com'}
        if site not in origins or not self.permission(site,'read'):
            raise PermissionError('site read authorization required')
        matches=[s for s in self.session_list() if s.get('session_id')==session_id]
        if (len(matches)!=1 or not isinstance(browser_instance_id,str) or not browser_instance_id
                or type(agent_window_id) is not int
                or matches[0].get('browser_instance_id')!=browser_instance_id
                or matches[0].get('agent_window_id')!=agent_window_id):
            raise PermissionError('selected browser session changed; refresh before opening')
        out=subprocess.run([self.executable,'tab','create','--json','--session',session_id,
                            '--url',origins[site]],capture_output=True,text=True,encoding='utf8',timeout=20)
        if out.returncode:raise RuntimeError('BrowserSkill open outcome unknown; refresh tabs before retrying')
        return {'opened':True}

    def session_stop(self, session_id=None, *, all_sessions=False):
        if not self.enabled or not self.executable or not Path(self.executable).is_file():raise PermissionError('browser skill unavailable')
        if all_sessions == (session_id is not None):raise ValueError('choose one session or all')
        command=[self.executable,'session','stop','--json']
        if all_sessions:command.append('--all')
        else:command.append(session_id)
        out=subprocess.run(command,capture_output=True,text=True,encoding='utf8',timeout=20)
        if out.returncode:raise RuntimeError('BrowserSkill session stop failed')
        return json.loads(out.stdout) if out.stdout.strip() else {'stopped':True}

    def bind_session(self, site, session_id, tab_id):
        """Bind an authorized site to an observed Agent tab, without granting send."""
        from .browser_consultation_bridge import BrowserConsultationBridge
        if not self.permission(site, 'read'):
            raise PermissionError('site read authorization required')
        bridge = BrowserConsultationBridge(self, session_id, tab_id=tab_id)
        sessions = self.session_list()
        matches = [s for s in sessions if s.get('session_id') == session_id]
        if len(matches) != 1:
            raise PermissionError('BrowserSkill session is no longer active')
        session = matches[0]
        browser = session.get('browser_instance_id')
        window = session.get('agent_window_id')
        if not isinstance(browser, str) or not browser or type(window) is not int:
            raise ValueError('session ownership identity missing')
        bridge.identity = {'browser_instance_id': browser, 'agent_window_id': window}
        bridge._tab(site)
        binding = {'session_id': session_id, 'tab_id': tab_id,
                   'browser_instance_id': browser, 'agent_window_id': window}
        data = self._read()
        entry = data['sites'].get(site.casefold())
        if not entry or entry.get('read') is not True:
            raise PermissionError('site authorization changed')
        entry['binding'] = binding
        self._write(data)
        return binding

    def bound_bridge(self, site):
        """Resolve persisted identity against live inventory; never auto-rebind."""
        from .browser_consultation_bridge import BrowserConsultationBridge
        if not self.permission(site, 'read'):
            raise PermissionError('site read authorization required')
        binding = self._read()['sites'].get(site.casefold(), {}).get('binding')
        if not isinstance(binding, dict):
            raise PermissionError('explicit session binding required')
        bridge = BrowserConsultationBridge(self, binding.get('session_id'), tab_id=binding.get('tab_id'), identity=binding)
        sessions = self.session_list()
        matches = [s for s in sessions if s.get('session_id') == binding['session_id']]
        if len(matches) != 1 or any(matches[0].get(k) != binding.get(k)
                                  for k in ('browser_instance_id', 'agent_window_id')):
            raise PermissionError('session identity changed; rebind explicitly')
        bridge._tab(site)
        return bridge

    def binding_status(self, site):
        """Transport readiness is not proof of login or successful submission."""
        if not self.enabled:
            return {'state': 'disabled', 'login': 'unknown'}
        entry = self._read()['sites'].get(site.casefold(), {})
        if entry.get('read') is not True:
            return {'state': 'unauthorized', 'login': 'unknown'}
        if not entry.get('binding'):
            return {'state': 'unbound', 'login': 'unknown'}
        try:
            self.bound_bridge(site)
        except (PermissionError, ValueError):
            return {'state': 'stale', 'login': 'unknown'}
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return {'state': 'unknown', 'login': 'unknown'}
        return {'state': 'ready', 'login': 'unknown'}
