import unittest
from unittest.mock import patch
from pathlib import Path

from extensions.diagnostics.dsh import project_page
from extensions.diagnostics.continuity import ingest_observations
from extensions.continuity.continuity import initialize
from sumika_next.contracts import HarnessInstance, Trust, WorkBinding, ToolRequest
from sumika_next.authorization import AuthorizationError
from sumika_next.dsh import Dsh


class NativeDiagnosticProjection(unittest.TestCase):
    def test_metadata_only_tool_failure(self):
        page = {'hasMore': True, 'records': [
            {'type': 'event', 'event': {'seq': 4, 'type': 'tool/call', 'time': 1,
                'data': {'callId': 'call-1', 'name': 'pwsh', 'arguments': 'secret'}}},
            {'type': 'event', 'event': {'seq': 5, 'type': 'tool/result', 'time': 2,
                'data': {'message': {'content': [{'type': 'tool-result', 'toolCallId': 'call-1',
                    'isError': True, 'content': [{'type': 'text', 'text': 'private'}]}]},
                    'error': {'name': 'Denied', 'code': 'permission-denied'}}}},
        ]}
        result = project_page(page, session='s', version='0.1.5-rc.2', through_seq=9)
        self.assertEqual(result['next_before'], 4)
        self.assertEqual([e['kind'] for e in result['events']], ['tool/call', 'tool/result'])
        self.assertEqual(result['events'][1]['status'], 'error')
        self.assertEqual(result['events'][1]['error_code'], 'permission-denied')
        self.assertNotIn('private', str(result))
        self.assertNotIn('secret', str(result))

    def test_unknown_event_kind_does_not_expose_path(self):
        page = {'hasMore': False, 'records': [{'type': 'event', 'event': {
            'seq': 0, 'type': 'C:/private/customer/project', 'data': {}}}]}
        result = project_page(page, session='s', version='v', through_seq=0)
        self.assertNotIn('private', str(result))
        self.assertNotIn('customer', str(result))

    def test_approval_pair_retains_identity_and_only_known_outcomes(self):
        for outcome in ('rejected', 'cancelled', 'allowed-once', 'unavailable', 'C:/private/secret'):
            page = {'hasMore': False, 'records': [
                {'type': 'event', 'event': {'seq': 1, 'type': 'approval/asked',
                    'data': {'id': 'approval-1', 'callId': 'call-1', 'reason': 'secret'}}},
                {'type': 'event', 'event': {'seq': 2, 'type': 'approval/decided',
                    'data': {'id': 'approval-1', 'outcome': outcome}}},
            ]}
            result = project_page(page, session='s', version='v', through_seq=2)
            asked, decided = result['events']
            self.assertEqual(asked['call_ids'], ['call-1'])
            self.assertEqual(asked['approval_id'], decided['approval_id'])
            self.assertEqual(decided['kind'], 'approval/decided')
            self.assertEqual(decided['approval_outcome'], 'unknown' if '/' in outcome else outcome)
            self.assertNotIn('secret', str(result))

    def test_rejects_bad_cursor_and_unknown_shape(self):
        with self.assertRaises(ValueError):
            project_page({'hasMore': False, 'records': [{'type': 'event', 'event':
                {'seq': 2, 'type': 'user/message', 'time': 1, 'data': {}}}]},
                session='s', version='v', through_seq=1)
        with self.assertRaises(ValueError):
            project_page({'hasMore': True, 'records': []}, session='s', version='v', through_seq=1)

    def test_adapter_requires_owned_session_and_uses_native_page(self):
        adapter = Dsh(Path.cwd(), Path.cwd() / '.sumika-next/test-only-diagnostics')
        adapter.url = 'http://127.0.0.1:12345'
        adapter.instance = HarnessInstance('dsh', adapter.instance.instance_id, Trust.MANAGED)
        adapter.sessions.add('s')
        binding = WorkBinding(adapter.instance.instance_id, 'r', 1, 's', 'step')
        page = {'hasMore': False, 'records': []}
        adapter._rpc = lambda method, args: page
        with patch.object(adapter, '_check_owner'):
            result = adapter.diagnostic_page(binding, through_seq=3)
        self.assertEqual(result['through_seq'], 3)
        with self.assertRaises(Exception):
            adapter.diagnostic_page(WorkBinding(adapter.instance.instance_id, 'r', 1, 'other', 'step'), through_seq=3)

    def test_existing_session_must_be_explicitly_listed_before_adoption(self):
        adapter = Dsh(Path.cwd(), Path.cwd() / '.sumika-next/test-only-diagnostics-list')
        adapter.url = 'http://127.0.0.1:12345'
        adapter.instance = HarnessInstance('dsh', adapter.instance.instance_id, Trust.MANAGED)
        adapter._rpc = lambda method, args: {'items': [{'sessionId': 'listed', 'updatedAt': 1,
                                                        'running': False, 'blank': False}]} if method == 'session/list' else None
        with patch.object(adapter, '_check_owner'):
            self.assertEqual(adapter.adopt_existing_session('listed'), 'listed')
            with self.assertRaises(Exception): adapter.adopt_existing_session('unknown')
            self.assertNotIn('listed', adapter.sessions)
            binding = WorkBinding(adapter.instance.instance_id, 'r', 1, 'listed', 'cancel')
            with self.assertRaises(AuthorizationError):
                adapter.execute(ToolRequest(binding, 'session.cancel', 'listed', b'{"sessionId":"listed"}'))
        adapter.close()
        self.assertEqual(adapter.diagnostic_sessions, set())

    def test_continuity_write_failure_is_unknown_without_retry_or_payload(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
            root = Path(tmp)
            initialize(root)
            (root / '.sumika-continuity' / 'records.sqlite3').write_bytes(b'not sqlite')
            result = ingest_observations(root, {'harness': 'fixture', 'session': 's',
                'events': [{'kind': 'tool', 'source_id': 'x', 'payload': {'private': 'value'}}]})
            self.assertEqual(result['status'], 'unknown')
            self.assertFalse(result['retry'])
            self.assertNotIn('private', str(result))

    def test_continuity_bridge_process_returns_unknown_without_replay(self):
        import subprocess, sys, tempfile
        with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
            root = Path(tmp)
            initialize(root)
            (root / '.sumika-continuity' / 'records.sqlite3').write_bytes(b'not sqlite')
            request = {'action': 'ingest', 'harness': 'dsh', 'session': 's',
                       'events': [{'kind': 'tool', 'source_id': 'x', 'payload': {}}]}
            result = subprocess.run([sys.executable, '-B', 'extensions/continuity/continuity.py',
                                     '--root', str(root), 'request'], input=__import__('json').dumps(request),
                                    text=True, capture_output=True, encoding='utf8')
            self.assertEqual(result.returncode, 0)
            self.assertEqual(__import__('json').loads(result.stdout)['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
