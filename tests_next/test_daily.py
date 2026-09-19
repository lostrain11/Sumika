from tests_next.scratch import ScratchDirectory
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from sumika_next.contracts import HarnessInstance, Trust
from sumika_next.daily import create_workspace_session, run
from sumika_next.dsh import Dsh, DshError


class DailyTests(unittest.TestCase):
    def test_cli_denies_occupied_profile_before_constructing_adapter(self):
        with patch('sumika_next.daily.ProfileLease') as lease, patch('sumika_next.daily.Dsh') as adapter:
            lease.return_value.acquire.side_effect = OSError('already locked')
            with self.assertRaises(OSError):
                run(Path.cwd(), Path('unused'), None, browser=False)
            adapter.assert_not_called()

    def test_cli_retains_fence_when_close_fails_or_exit_is_unconfirmed(self):
        for failure in ('exception', 'alive'):
            with self.subTest(failure=failure), patch('sumika_next.daily.ProfileLease') as factory, \
                    patch('sumika_next.daily.Dsh') as factory_dsh, patch('builtins.print'):
                lease = factory.return_value.acquire.return_value
                adapter = factory_dsh.return_value
                adapter.process.wait.side_effect = KeyboardInterrupt
                adapter.process.poll.return_value = None
                if failure == 'exception':
                    adapter.close.side_effect = OSError('stop failed')
                with self.assertRaises((OSError, RuntimeError)):
                    run(Path.cwd(), Path('unused'), None, browser=False)
                lease.bind.assert_called_once_with(adapter.process)
                lease.release.assert_not_called()

    def test_cli_cleanup_runs_even_when_extension_close_fails(self):
        with patch('sumika_next.daily.ProfileLease') as factory, \
                patch('sumika_next.daily.Dsh') as factory_dsh, \
                patch('sumika_next.extension_host.ExtensionHost') as host, patch('builtins.print'):
            adapter = factory_dsh.return_value
            process = Mock(returncode=0)
            process.poll.return_value = 0
            adapter.process = process
            host.return_value.close.side_effect = ValueError('extension close failed')
            with self.assertRaises(ValueError):
                run(Path.cwd(), Path('unused'), None, browser=False, extensions_config=Path('fixture'))
            adapter.close.assert_called_once()
            factory.return_value.acquire.return_value.release.assert_called_once()

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
