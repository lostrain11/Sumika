"""Explicit UI adapters for existing settings, memory and schedule operations.

No generic tool execution: paths select a fixed operation, the host resolves
role scope, and revisions prevent stale dialogs from overwriting newer data.
"""
import copy
import hashlib
import hmac
import json
import secrets
import threading
import uuid
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

from extensions.models.settings import load, save
from extensions.roles.chat import open_session
from extensions.roles.roles import load_role, rename_role, export_package, attach_asset, import_package
from extensions.desktop.scheduler import Schedule
from extensions.capabilities import CapabilityStore
from ui.readiness import service_capabilities
from extensions.desktop.browser_skill import BrowserSkillClient


class Conflict(ValueError):
    pass


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


class Management:
    def __init__(self, bridge):
        self.bridge = bridge
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()

    def authorize(self, handler, write=False):
        port = handler.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if handler.headers.get('Host') not in hosts:
            raise PermissionError('unexpected client host')
        origin = handler.headers.get('Origin')
        if origin and origin not in self.allowed_origins(handler):
            raise PermissionError('unexpected client origin')
        if handler.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PermissionError('cross-site request rejected')
        if write and not secrets.compare_digest(handler.headers.get('X-Sumika-CSRF', ''), self.client_token(handler)):
            raise PermissionError('client request token required')

    def allowed_origins(self, handler):
        port = handler.server.server_port
        origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
        binding = self.bridge.workbench.browser_binding()
        if binding:
            origins.add(binding[0])
        return origins

    def client_token(self, handler):
        origin = handler.headers.get('Origin')
        binding = self.bridge.workbench.browser_binding()
        if binding and origin == binding[0]:
            # A restarted DSH at the same port does not inherit the old token.
            return hmac.new(self.csrf.encode(), ('native:' + binding[0] + ':' + binding[1]).encode(), hashlib.sha256).hexdigest()
        return self.csrf

    def settings(self):
        data = load(self.bridge.settings_path)
        return {'revision': revision(data), 'data': data}

    def update_settings(self, payload):
        current = self.settings()
        self.check_revision(payload, current['revision'])
        changes = payload.get('changes')
        if not isinstance(changes, dict):
            raise ValueError('changes must be an object')
        scalar = {'enabled', 'provider', 'model', 'endpoint', 'key_env', 'temperature',
                  'context_length', 'max_tokens', 'timeout_seconds'}
        sections = {
            'voice': {'enabled', 'input_device', 'sample_rate', 'tts_voice', 'asr_model'},
            'memory': {'enabled','auto_extract', 'model_proposals', 'extract_threshold', 'max_extracts_per_turn'},
            'startup': {'auto_start', 'tray'}, 'usage': {'enabled'},
            'prompt_enhancement': {'enabled'},
            'auxiliary': {'enabled', 'provider', 'model', 'endpoint', 'key_env',
                          'timeout_seconds', 'max_tokens', 'temperature', 'context_length', 'capabilities'},
            'model_library': {'roots','auto_scan'},
            'role': {'memory_provider', 'card_context_enabled', 'card_context_budget_chars'},
        }
        updated = copy.deepcopy(current['data'])
        for key, value in changes.items():
            if key in scalar:
                updated[key] = value
            elif key in sections and isinstance(value, dict) and set(value) <= sections[key]:
                updated[key].update(value)
            else:
                raise ValueError('unsupported settings field')
        if updated['role']['memory_provider']=='semantic' and current['data']['role']['memory_provider']!='semantic':
            from extensions.memory.embedding_runtime import installed_runtime, embed_batch
            python,cache=installed_runtime()
            embed_batch(python,cache,[],'语义记忆依赖检查')
        save(updated, self.bridge.settings_path)
        if updated['voice'] != current['data']['voice']:
            self.bridge.stop_speech()
        startup = self.bridge.startup_state()
        if updated['startup'] != current['data']['startup']:
            startup = self.bridge.apply_startup(updated)
        return {**self.settings(), 'startup': startup}

    @staticmethod
    def check_revision(payload, actual):
        if payload.get('expected_revision') != actual:
            raise Conflict('数据已改变，请重新加载后再保存')

    def role_session(self, role_id):
        paths = self.bridge._role_paths()
        if role_id not in paths:
            raise ValueError('unknown role')
        settings = load(self.bridge.settings_path)
        settings['role']['role_dir'] = paths[role_id]
        return open_session(settings)

    def resources(self, role_id, action=None, payload=None):
        paths = self.bridge._role_paths()
        if role_id not in paths:
            raise ValueError('unknown role')
        role_path = Path(paths[role_id])
        # Archives must never follow a user-created junction outside this role.
        if role_path.is_symlink() or role_path.is_junction():
            raise ValueError('linked role directory is not supported')
        for item in role_path.rglob('*'):
            if item.is_symlink() or item.is_junction():
                raise ValueError('linked role resource is not supported')
        role = load_role(role_path)
        if role['verified']['status'] != 'ok':
            raise ValueError('角色资源校验失败，请先核对原始导入文件')
        state = {'id':role_id, 'name':role['name'], 'assets':sorted(role['assets']),
                 'editable':self.bridge._role_kinds().get(role_id)=='user',
                 'revision':revision((role_path/'checksums.json').read_text(encoding='utf8'))}
        if action is None:
            return state
        self.check_revision(payload, state['revision'])
        if not state['editable']:
            raise ValueError('built-in resources are read-only')
        if action not in ('rename','attach','export','archive'):
            raise ValueError('unsupported resource action')
        if action == 'archive':
            if payload.get('confirmed') is not True:
                raise ValueError('confirmation required')
            if Path(load(self.bridge.settings_path)['role']['role_dir']).resolve()==role_path.resolve():
                raise ValueError('请先切换到其他角色，再移除此角色')
        if action == 'rename':
            name = payload.get('name')
            if not isinstance(name,str) or not name.strip() or len(name.strip())>60:
                raise ValueError('显示名需要 1–60 个字符')
        if action == 'attach' and payload.get('kind') not in ('model_3d','model_2d','voice','scene'):
            raise ValueError('unsupported resource kind')
        backups=self.bridge.settings_path.parent/'backups'/'roles'
        backups.mkdir(parents=True,exist_ok=True)
        stamp=uuid.uuid4().hex
        backup=export_package(role_id,role_path.parent,backups/f'{stamp}.zip')
        if action=='export':return {'path':str(backup),'id':role_id}
        if action=='archive':
            archive=backups/stamp
            shutil.move(str(role_path),str(archive))
            return {'archived':True,'path':str(archive),'backup':str(backup)}
        if action=='rename':rename_role(role_id,role_path.parent,name)
        if action=='attach':attach_asset(role_id,role_path.parent,payload['kind'],payload.get('path',''))
        return {**self.resources(role_id),'backup':str(backup)}

    def import_resources(self, payload):
        """Validate in a private staging directory before publishing a user role."""
        if payload.get('confirmed') is not True:
            raise ValueError('confirmation required')
        source=payload.get('path')
        if not isinstance(source,str) or not source.strip():
            raise ValueError('本机角色资源包路径不能为空')
        from ui.server import user_role_store
        store=user_role_store().resolve()
        store.mkdir(parents=True,exist_ok=True)
        # Same volume, outside the live registry; malformed roles never appear.
        staging=store.parent/'role-import-staging'
        staging.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging) as directory:
            role_path=import_package(source,directory)
            role=load_role(role_path)
            if role['verified']['status']!='ok':
                raise ValueError('角色资源包校验失败')
            if role['id'] in self.bridge._role_paths():
                raise ValueError('同名角色已存在；不会覆盖，请先核对并归档旧角色')
            destination=store/role_path.name
            if destination.exists():raise ValueError('role already exists')
            role_path.rename(destination)
        return {'id':role['id'],'name':role['name'],'path':str(destination),
                'missing':[key for key in ('card','model_3d') if key not in role['assets']]}

    @staticmethod
    def memory_state(session):
        scope = session.memory._scope(session.scope['user_id'], session.scope['role_id'],
                                      session.scope['project_id'])
        columns = 'id,text,source,active,fact_key,event_id,created,updated'
        names = columns.split(',')
        rows = [dict(zip(names, row)) for row in session.memory.db.execute(
            f'SELECT {columns} FROM memories WHERE scope=? ORDER BY id', (scope,))]
        relations = session.request('relations_all', {'limit': 500})
        from extensions.memory.model_proposer import list_proposals
        proposals = list_proposals(session)
        return {'scope': session.scope, 'memories': [r for r in rows if r['active']],
                'proposals': proposals, 'relations': relations, 'revision': revision([rows, relations, proposals])}

    def memory(self, role_id, action=None, payload=None):
        session = self.role_session(role_id)
        try:
            state = self.memory_state(session)
            if action is None:
                return state
            self.check_revision(payload, state['revision'])
            if action in ('forget', 'reset', 'restore', 'delete_relation') and payload.get('confirmed') is not True:
                raise ValueError('explicit confirmation required')
            if action in ('reset', 'restore'):
                backup_dir = self.bridge.settings_path.parent / 'backups' / 'memory'
                backup_dir.mkdir(parents=True, exist_ok=True)
                target = backup_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex+'.json')
                session.request('export', {'path': str(target)})
            if action in ('accept_proposal', 'reject_proposal'):
                if payload.get('confirmed') is not True:
                    raise ValueError('explicit confirmation required')
                from extensions.memory.model_proposer import resolve
                resolve(session,payload.get('event_id'),action=='accept_proposal')
            elif action == 'remember':
                event = payload.get('request_id')
                if not isinstance(event, str) or not event:
                    raise ValueError('request_id required')
                session.request('remember', {'text': payload.get('text'), 'source': 'user',
                    'fact_key': payload.get('fact_key'), 'event_id': event})
            elif action in ('forget', 'relate', 'edit_relation', 'delete_relation'):
                keys = {'forget': ('id',), 'relate': ('subject','predicate','object'),
                        'edit_relation': ('subject','predicate','object','new_object'),
                        'delete_relation': ('subject','predicate','object')}[action]
                data = {key: payload.get(key) for key in keys}
                if action == 'forget':
                    if type(data['id']) is not int: raise ValueError('memory id required')
                elif any(not isinstance(v, str) or not v.strip() for v in data.values()):
                    raise ValueError('relationship fields required')
                session.request(action, data)
            elif action == 'reset':
                session.request('reset_to_card', {})
            elif action in ('export', 'restore'):
                # Reuse the versioned serializer without exposing arbitrary paths.
                temporary = self.bridge.settings_path.parent / ('memory-transfer-'+uuid.uuid4().hex+'.json')
                try:
                    if action == 'export':
                        session.request('export', {'path': str(temporary)})
                        exported = json.loads(temporary.read_text(encoding='utf8'))
                        exported['ui_scope'] = state['scope']
                        return {'data': exported}
                    data = payload.get('data')
                    if not isinstance(data, (dict, list)): raise ValueError('invalid backup')
                    wanted = session.memory._scope(session.scope['user_id'], session.scope['role_id'], session.scope['project_id'])
                    collections = [data] if isinstance(data, list) else [data.get(k, []) for k in ('memories','relations','proposals')]
                    scopes = {row.get('scope') for rows in collections if isinstance(rows, list) for row in rows if isinstance(row, dict)}
                    if scopes and scopes != {wanted}:
                        raise ValueError('backup belongs to another memory scope')
                    if not scopes and (not isinstance(data, dict) or data.get('ui_scope') != state['scope']):
                        raise ValueError('empty backup must identify its role scope')
                    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
                    session.request('restore', {'path': str(temporary)})
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                raise ValueError('unsupported memory operation')
            return self.memory_state(session)
        finally:
            session.close()

    def schedules(self):
        service = self.bridge.schedule._service()
        try:
            history = service.runner.history()
        finally:
            service.close()
        return {**self.bridge.schedule.state(), 'history': history,
                'revision': self.bridge.schedule.store.revision()}

    def modules(self, action=None, payload=None):
        if not self.bridge.capability_database:
            raise ValueError('capability registry not configured')
        store = CapabilityStore(self.bridge.capability_database)
        try:
            def state():
                rows = store.list()
                removed = sorted(store.removed())
                candidates = service_capabilities(self.bridge.workbench.root)
                return {'modules': rows, 'removed': removed, 'candidates': candidates,
                        'revision': revision([rows,removed])}
            current = state()
            if action is None: return current
            self.check_revision(payload, current['revision'])
            if action == 'reorder':
                store.reorder(payload.get('ids', []))
            elif action in ('toggle','microphone_authorization'):
                old=next((r for r in current['modules'] if r['id']==payload.get('id')),None)
                if old is None or type(payload.get('enabled')) is not bool:
                    raise ValueError('registered module and boolean required')
                options=dict(old['options'])
                enabled=old['enabled']
                if action=='microphone_authorization':
                    if old['id']!='microphone' or payload.get('confirmed') is not True:
                        raise ValueError('explicit microphone authorization required')
                    options['user_authorized']=payload['enabled']
                else:
                    enabled=payload['enabled']
                store.configure(old['id'],old['provider'],enabled=enabled,options=options)
            elif action == 'remove':
                if payload.get('confirmed') is not True: raise ValueError('confirmation required')
                if payload.get('id') not in {r['id'] for r in current['modules']}: raise ValueError('unknown module')
                store.remove(payload['id'])
            elif action in ('configure','add'):
                candidate = next((r for r in current['candidates'] if r['id']==payload.get('id') and r['provider']==payload.get('provider')), None)
                if candidate is None: raise ValueError('provider not available on this machine')
                old = next((r for r in current['modules'] if r['id']==payload['id']), None)
                options = old['options'] if old and old['provider']==candidate['provider'] else candidate.get('options',{})
                enabled = old['enabled'] if old else False
                store.configure(candidate['id'],candidate['provider'],enabled=enabled,options=options)
            else: raise ValueError('unsupported module operation')
            if payload.get('id') in ('voice', 'asr', 'microphone') and action != 'reorder':
                self.bridge.stop_speech()
            return state()
        finally:
            store.close()

    def update_schedule(self, action, payload):
        if action == 'tick':
            return self.bridge.schedule.tick()
        if action == 'cancel':
            return self.bridge.schedule.cancel(payload.get('id'), payload.get('due'))
        if action == 'reconcile':
            return self.bridge.schedule.reconcile(payload.get('id'), payload.get('due'), payload.get('outcome'), payload.get('evidence'))
        store = self.bridge.schedule.store
        self.check_revision(payload, store.revision())
        if action == 'save':
            item = Schedule(**payload['definition'])
            items = [s for s in store.load() if s.id != item.id] + [item]
            store.save(items, expected_revision=payload['expected_revision'])
        elif action == 'remove':
            if payload.get('confirmed') is not True: raise ValueError('confirmation required')
            items = [s for s in store.load() if s.id != payload.get('id')]
            store.save(items, expected_revision=payload['expected_revision'])
        elif action == 'acknowledge':
            self.bridge.schedule.acknowledge(payload.get('key'))
        else:
            raise ValueError('unsupported schedule operation')
        return self.schedules()

    def usage(self, role_id):
        session = self.role_session(role_id)
        try:
            db = session.memory.db
            if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usage'").fetchone():
                return {'groups': [], 'status': 'unknown'}
            # Role chat currently uses this exact session-id convention.
            session_id = 'room-' + role_id
            rows = db.execute('SELECT provider,model,status,COUNT(*),SUM(prompt_tokens),'
                'SUM(completion_tokens),SUM(total_tokens) FROM usage WHERE scope=? AND session=? '
                'GROUP BY provider,model,status', (session.scope['project_id'], session_id))
            groups = [dict(zip(('provider','model','status','requests','prompt_tokens','completion_tokens','total_tokens'), row)) for row in rows]
            return {'groups': groups, 'status': 'available' if groups else 'unknown'}
        finally:
            session.close()

    def auxiliary(self, action, payload=None):
        from extensions.models.auxiliary import health, enhance_prompt, classify_task
        settings = load(self.bridge.settings_path)
        if action == 'health':
            return health(settings)
        if action == 'enhance':
            return enhance_prompt(settings, (payload or {}).get('original'), (payload or {}).get('strategy', 'default'))
        if action == 'classify':
            return classify_task(settings, (payload or {}).get('message'), (payload or {}).get('project_index'))
        raise ValueError('unsupported auxiliary operation')

    def browsers(self, action=None, payload=None):
        client = BrowserSkillClient(registry=self.bridge.settings_path.parent/'browser-authorizations.json')
        allowed = {'chat.deepseek.com':'https://chat.deepseek.com','www.kimi.com':'https://www.kimi.com','chatgpt.com':'https://chatgpt.com'}
        if action == 'toggle':
            if payload.get('confirmed') is not True:raise ValueError('confirmation required')
            client.set_enabled(payload.get('enabled'))
            action=None
        if action:
            site = payload.get('site')
            if site not in allowed: raise ValueError('unsupported consultation site')
            if payload.get('confirmed') is not True: raise ValueError('confirmation required')
            if action == 'revoke': client.revoke(site)
            elif action == 'authorize':
                client.authorize(site,payload.get('profile'),read=payload.get('read',False),send=payload.get('send',False))
            elif action == 'bind':
                client.bind_session(site, payload.get('session_id'), payload.get('tab_id'))
            elif action == 'start':
                if not client.permission(site,'read'):raise PermissionError('site read authorization required')
                client.session_start(no_focus=False)
            elif action == 'open':
                client.open_site(site,payload.get('session_id'),payload.get('browser_instance_id'),payload.get('agent_window_id'))
            else: raise ValueError('unsupported browser action')
        records = client._read()['sites']
        return {'enabled':client.enabled,'sites':[{'id':key,'url':url,'login':'unknown',**{k:v for k,v in records.get(key,{}).items() if k in ('profile','read','send','binding')}} for key,url in allowed.items()]}

    def dispatch(self, method, path, payload=None):
        parts = [unquote(p) for p in urlparse(path).path.split('/') if p]
        with self.lock:
            if method == 'GET' and parts == ['api','manage','session']:
                return {'csrf': self.csrf}
            if parts == ['api','manage','role-relocation'] and method=='GET':
                from extensions.roles.relocation import journal
                record=journal(self.bridge.settings_path)
                return {'relocation':{k:record[k] for k in ('id','state','source','target','backup')} if record else None}
            if parts == ['api','manage','role-relocation'] and method=='POST':
                from extensions.roles.relocation import relocate
                self.check_revision(payload,self.settings()['revision'])
                if payload.get('confirmed') is not True:raise ValueError('explicit relocation confirmation required')
                selected=self.bridge.active_role()['id']
                if self.bridge._role_kinds().get(selected)!='user':raise ValueError('only imported user roles can relocate')
                return relocate(self.bridge.settings_path,payload.get('target'))
            if parts == ['api','manage','role-relocation','resume'] and method=='POST':
                from extensions.roles.relocation import resume
                if payload.get('confirmed') is not True:raise ValueError('explicit recovery confirmation required')
                return resume(self.bridge.settings_path,payload.get('id'))
            if parts == ['api','manage','role-relocation','rollback'] and method=='POST':
                from extensions.roles.relocation import rollback
                if payload.get('confirmed') is not True:raise ValueError('explicit recovery confirmation required')
                return rollback(self.bridge.settings_path,payload.get('id'))
            if method == 'GET' and parts == ['api','manage','workbench-layout']:
                binding = self.bridge.workbench.browser_binding()
                return {'mode':'iframe-fallback','native_slots':['root','sidebar','main','rightbar','shell.overlay'],
                        'binding': {'origin': binding[0], 'instance_id': binding[1]} if binding else None,
                        'native_verified': bool(binding),
                        'note':'产品迁入前保留 iframe 回退，不重复维护 DSH 会话数据'}
            if parts == ['api','manage','task-draft']:
                settings=load(self.bridge.settings_path)
                owner=settings['role']['user_id']
                store=self.bridge.conversations
                if method=='GET':
                    handoff_id = (payload or {}).get('id') if isinstance(payload, dict) else None
                    return {'draft':store.draft(owner) if not handoff_id else store.handoff(owner, handoff_id)}
                if payload.get('action')=='prepare':
                    return {'draft':store.prepare(owner,self.bridge._chat_scope(settings),
                        payload.get('source_message_id'),payload.get('expected_id'))}
                if payload.get('action')=='dismiss':
                    store.dismiss(owner,payload.get('id'))
                    return {'draft':store.draft(owner)}
                if payload.get('action') == 'receive':
                    draft = store.draft(owner)
                    if not draft or draft.get('id') != payload.get('id'):
                        raise ValueError('handoff draft not found')
                    from extensions.roles.handoff import verified_project_context
                    context = verified_project_context(draft.get('project_id'), payload.get('projects', []), receipts=payload.get('receipts', []))
                    return {'handoff': store.receive_handoff(owner, draft['id'], context)}
                if payload.get('action') == 'result':
                    from extensions.roles.handoff import create_result_receipt
                    receipt = payload.get('receipt')
                    if not isinstance(receipt, dict): raise ValueError('receipt required')
                    receipt = create_result_receipt(status=receipt.get('status'), summary=receipt.get('summary',''), source='host', receipt_id=receipt.get('id'))
                    return {'handoff': store.record_handoff_result(owner, payload.get('id'), receipt)}
                raise ValueError('unknown draft action')
            if parts == ['api','manage','settings']:
                return self.settings() if method == 'GET' else self.update_settings(payload)
            if parts == ['api','manage','model-library'] and method=='GET':
                from extensions.models.library import scan
                return scan(self.settings()['data']['model_library']['roots'])
            if parts == ['api','manage','auxiliary'] and method == 'GET':
                return self.auxiliary('health')
            if len(parts) == 4 and parts[:3] == ['api','manage','auxiliary'] and method == 'POST':
                return self.auxiliary(parts[3], payload)
            if parts == ['api','manage','roles','import-package'] and method=='POST':
                return self.import_resources(payload)
            if parts == ['api','manage','schedules'] and method == 'GET':
                return self.schedules()
            if parts == ['api','manage','modules'] and method == 'GET':
                return self.modules()
            if parts == ['api','manage','browsers'] and method == 'GET': return self.browsers()
            if parts == ['api','manage','browsers','status'] and method == 'GET':
                client = BrowserSkillClient(registry=self.bridge.settings_path.parent/'browser-authorizations.json')
                return {'sites': {site: client.binding_status(site) for site in
                                 ('chat.deepseek.com','www.kimi.com','chatgpt.com')}}
            if parts == ['api','manage','browser-sessions'] and method == 'GET':
                client = BrowserSkillClient(registry=self.bridge.settings_path.parent/'browser-authorizations.json')
                try:
                    sessions = client.session_list()
                    tabs = {s.get('session_id'): client.session_tabs(s.get('session_id')) for s in sessions if isinstance(s,dict) and s.get('session_id')}
                    inventory = 'reported' if client.enabled and client.executable and Path(client.executable).is_file() else 'unknown'
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    sessions, tabs, inventory = [], {}, 'unknown'
                return {'status': client.status(), 'sessions': sessions, 'tabs': tabs, 'inventory': inventory}
            if len(parts)==4 and parts[:3]==['api','manage','browsers'] and method=='POST':
                return self.browsers(parts[3],payload)
            if len(parts)==4 and parts[:3]==['api','manage','modules'] and method=='POST':
                return self.modules(parts[3],payload)
            if len(parts) == 4 and parts[:3] == ['api','manage','schedules'] and method == 'POST':
                return self.update_schedule(parts[3], payload)
            if len(parts) in (5, 6) and parts[:3] == ['api','manage','roles']:
                role_id, kind = parts[3:5]
                if kind == 'resources':
                    if method == 'GET' and len(parts)==5:return self.resources(role_id)
                    if method == 'POST' and len(parts)==6:return self.resources(role_id,parts[5],payload)
                if kind == 'usage' and len(parts) == 5 and method == 'GET':
                    return self.usage(role_id)
                if kind == 'memory':
                    if method == 'GET' and len(parts) == 5: return self.memory(role_id)
                    if method == 'POST' and len(parts) == 6: return self.memory(role_id, parts[5], payload)
            raise ValueError('unknown management endpoint')
