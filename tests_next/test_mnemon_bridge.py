import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.memory.mnemon_bridge import configuration, read
from extensions.models.settings import example, save
from extensions.roles.chat import open_session


class MnemonBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.role = self.root / 'role'
        self.role.mkdir()
        (self.role / 'role.json').write_text(json.dumps(dict(
            id='fixture-role', name='测试角色', persona='合成测试',
            worldbook=[], assets={})), encoding='utf8')
        self.path = self.root / 'settings.json'
        self.settings = example(self.role, self.root / 'memory.db')
        save(self.settings, self.path)

    def request(self, op='search', **extra):
        return dict(op=op, configuration_revision=configuration(self.path)[1],
                    **(dict(query='茉莉花茶', limit=5) if op == 'search' else {}), **extra)

    def seed(self):
        session = open_session(self.settings, for_chat=True)
        try:
            fact = session.memory.add('用户喜欢茉莉花茶', **session.scope)
            for field in ('user_id', 'role_id', 'project_id'):
                scope = {**session.scope, field: 'foreign'}
                session.memory.add('其他范围的茉莉花茶', **scope)
            session.memory.put_proposal(event_id='pending', text='茉莉花茶未确认',
                quote='茉莉花茶未确认', message_id='pending-message', **session.scope)
            return fact
        finally:
            session.close()

    def test_search_uses_confirmed_scoped_canonical_facts(self):
        fact = self.seed()
        result = read(self.path, self.request())
        self.assertEqual([row['record_id'] for row in result], [fact['record_id']])
        self.assertEqual(result[0]['text'], '用户喜欢茉莉花茶')
        self.assertIsInstance(read(self.path, self.request('revision')), str)

    def test_disabled_and_invalid_requests_do_not_open_database(self):
        self.settings['memory']['enabled'] = False
        save(self.settings, self.path)
        with self.assertRaisesRegex(ValueError, 'disabled'):
            read(self.path, self.request())
        self.assertFalse((self.root / 'memory.db').exists())
        self.settings['memory']['enabled'] = True
        save(self.settings, self.path)
        for request in (self.request(user_id='foreign'),
                        {**self.request(), 'configuration_revision': 'wrong'},
                        {**self.request(), 'query': ''},
                        {**self.request(), 'limit': True},
                        {**self.request(), 'limit': 6}):
            with self.assertRaises(ValueError):
                read(self.path, request)
        self.assertFalse((self.root / 'memory.db').exists())

    def test_legacy_missing_memory_switch_keeps_existing_default(self):
        self.seed()
        self.settings.pop('memory')
        self.path.write_text(json.dumps(self.settings), encoding='utf8')
        self.assertEqual(len(read(self.path, self.request())), 1)

    def test_settings_or_role_change_during_search_discards_result(self):
        self.seed()
        original = open_session
        for target in ('settings', 'role'):
            request = self.request()
            def racing_open(*args, **kwargs):
                session = original(*args, **kwargs)
                search = session.retrieval.search
                def race(*a, **kw):
                    result = search(*a, **kw)
                    if target == 'settings':
                        self.settings['memory']['enabled'] = False
                        save(self.settings, self.path)
                    else:
                        path = self.role / 'role.json'
                        role = json.loads(path.read_text(encoding='utf8'))
                        role['id'] = 'other-role'
                        path.write_text(json.dumps(role), encoding='utf8')
                    return result
                session.retrieval.search = race
                return session
            with patch('extensions.memory.mnemon_bridge.open_session', racing_open):
                with self.assertRaisesRegex(ValueError, 'changed during read'):
                    read(self.path, request)
            self.settings['memory']['enabled'] = True
            save(self.settings, self.path)

    def test_role_switch_during_open_is_rejected(self):
        self.seed()
        original = open_session
        def race(*args, **kwargs):
            role_path = self.role / 'role.json'
            old = role_path.read_bytes()
            data = json.loads(old)
            data['id'] = 'other-role'
            role_path.write_text(json.dumps(data), encoding='utf8')
            try:
                return original(*args, **kwargs)
            finally:
                role_path.write_bytes(old)
        with patch('extensions.memory.mnemon_bridge.open_session', race):
            with self.assertRaisesRegex(ValueError, 'binding changed'):
                read(self.path, self.request())

    def test_real_node_host_and_public_sdk(self):
        root = Path(__file__).resolve().parents[1]
        sdk = root / '.sumika-next/mnemon-host-deps/node_modules/dsh-mnemon/lib/extension-sdk.js'
        if not sdk.exists():
            self.skipTest('isolated reviewed Mnemon SDK not installed')
        self.seed()
        self.settings.pop('memory')
        self.path.write_text(json.dumps(self.settings), encoding='utf8')
        result = subprocess.run(['node', str(root / 'tools/verify_mnemon_settings_host.mjs'),
            sys.executable, str(self.path), str(sdk)], cwd=root, capture_output=True,
            text=True, encoding='utf8', timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['checks']), 7)
