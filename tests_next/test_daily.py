from tests_next.scratch import ScratchDirectory
import unittest
from pathlib import Path
from unittest.mock import patch

from sumika_next.contracts import HarnessInstance, Trust
from sumika_next.daily import create_workspace_session, run
from sumika_next.dsh import Dsh, DshError


class DailyTests(unittest.TestCase):
    def test_explicit_workspace_only_creates_a_session(self):
        class FakeHarness:
            instance = HarnessInstance('test', 'owned', Trust.MANAGED)
            requests = []
            def execute(self, request):
                self.requests.append(request)
                if request.action == 'workspace.create':
                    return {'workspace': {'workspaceId': 'workspace-1'}}
                return {'sessionId': request.binding.session_id}
        with ScratchDirectory() as tmp:
            harness = FakeHarness()
            session = create_workspace_session(harness, Path(tmp), Path(tmp)/'journal.sqlite3')
            self.assertTrue(session.startswith('sumika-'))
            self.assertEqual([r.action for r in harness.requests], ['workspace.create', 'session.create'])
            self.assertEqual(harness.requests[0].target, str(Path(tmp).resolve()))

    def test_bad_workspace_rejected_before_server_start(self):
        with ScratchDirectory() as tmp, patch('sumika_next.daily.Dsh') as adapter:
            with self.assertRaises(ValueError):
                run(Path(tmp), Path(tmp)/'home', Path(tmp)/'missing')
            adapter.assert_not_called()

    def test_browser_cannot_open_unverified_endpoint(self):
        adapter = Dsh(Path.cwd(), Path.cwd()/'.sumika-next/test')
        with patch('webbrowser.open') as browser:
            with self.assertRaises(DshError): adapter.open_browser()
            browser.assert_not_called()

    def test_browser_receives_owned_token_without_printing_it(self):
        adapter = Dsh(Path.cwd(), Path.cwd()/'.sumika-next/test')
        adapter.instance = HarnessInstance('dsh', 'owned', Trust.MANAGED)
        adapter.url = 'http://127.0.0.1:12345'
        adapter._browser_url = adapter.url + '/?token=test-secret'
        with patch.object(adapter, '_check_owner') as owner, patch('webbrowser.open', return_value=True) as browser, patch('builtins.print') as output:
            adapter.open_browser()
            owner.assert_called_once_with(12345)
            browser.assert_called_once_with(adapter._browser_url)
            output.assert_not_called()
        adapter.close()
        self.assertIsNone(adapter._browser_url)
