"""Diagnostic queries must not become a second profile writer."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from sumika_next.cli import main


class DiagnosticLifecycle(TestCase):
    def invoke(self):
        with patch('sys.argv', ['sumika', 'native-diagnostics', '--home', str(Path.cwd()),
                                '--session', 'existing']), redirect_stdout(io.StringIO()):
            main()

    def test_busy_profile_never_constructs_runtime(self):
        with patch('sumika_next.runtime_ownership.ProfileLease') as leases, patch('sumika_next.dsh.Dsh') as runtimes:
            leases.return_value.acquire.side_effect = OSError('locked')
            with self.assertRaises(OSError):
                self.invoke()
            runtimes.assert_not_called()

    def test_stopped_process_releases_lease_after_close(self):
        with patch('sumika_next.runtime_ownership.ProfileLease') as leases, patch('sumika_next.dsh.Dsh') as runtimes:
            runtime = runtimes.return_value
            runtime.process.poll.return_value = 0
            runtime.diagnostic_page.return_value = {'events': []}
            self.invoke()
            leases.return_value.acquire.return_value.bind.assert_called_once_with(runtime.process)
            runtime.close.assert_called_once()
            leases.return_value.acquire.return_value.release.assert_called_once()

    def test_stop_failure_or_live_process_preserves_fence(self):
        for mode in ('alive', 'close-error'):
            with self.subTest(mode=mode), patch('sumika_next.runtime_ownership.ProfileLease') as leases, patch('sumika_next.dsh.Dsh') as runtimes:
                runtime = runtimes.return_value
                runtime.process.poll.return_value = None
                runtime.diagnostic_page.return_value = {'events': []}
                if mode == 'close-error':
                    runtime.close.side_effect = OSError('stop failed')
                with self.assertRaises((OSError, RuntimeError)):
                    self.invoke()
                leases.return_value.acquire.return_value.release.assert_not_called()

    def test_evidence_command_reaches_export(self):
        with patch('sys.argv', ['sumika', 'evidence', '--task', 'task', '--out', 'unused.zip']), \
                patch('extensions.diagnostics.query.evidence_bundle', return_value={'path': 'unused.zip'}) as export, \
                redirect_stdout(io.StringIO()):
            main()
        export.assert_called_once()
