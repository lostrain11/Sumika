import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sumika_next.paths import user_data_directory
from sumika_next.daily import default_home
from extensions.models.settings import default_path
from extensions.desktop.browser_skill import BrowserSkillClient
from ui.schedule import default_directory
from sumika_next.dsh import Dsh, DshError


class PortablePaths(unittest.TestCase):
    def test_override_is_shared_and_does_not_initialize_data(self):
        base = Path('.sumika-next/portable-path-tests')
        base.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(dir=base)).resolve()
        runtime = root/'product/runtime/dsh'
        runtime.mkdir(parents=True)
        (runtime/'release.json').write_text(json.dumps({'version': '0.1.5-rc.2'}))
        personal = root/'personal data'
        with patch.dict(os.environ, {'SUMIKA_DATA_DIR': str(personal)}):
            self.assertEqual(default_path(), personal/'role-model-settings.json')
            self.assertEqual(default_directory(), personal/'schedules')
            self.assertEqual(BrowserSkillClient().registry, personal/'browser-authorizations.json')
            self.assertEqual(default_home(root/'product'), personal/'dsh-profiles/0.1.5-rc.2')
        self.assertFalse(personal.exists())

    def test_invalid_explicit_path_never_falls_back(self):
        for value in ('', ' ', 'relative/profile'):
            with patch.dict(os.environ, {'SUMIKA_DATA_DIR': value}):
                with self.assertRaises(ValueError):
                    user_data_directory()

    def test_existing_user_default_preserved(self):
        existing = str(Path.home()/'AppData/Local')
        with patch.dict(os.environ, {'LOCALAPPDATA': existing}, clear=True):
            self.assertEqual(user_data_directory(), Path(existing)/'Sumika')

    def test_bundled_node_never_silently_uses_host_node(self):
        base = Path('.sumika-next/portable-path-tests')
        base.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(dir=base)).resolve()
        runtime = root/'runtime/dsh'
        package = runtime/'node_modules/@deepseek-ai/dsh'
        package.mkdir(parents=True)
        (package/'package.json').write_text(json.dumps({'version': 'test'}))
        (runtime/'release.json').write_text(json.dumps({'version': 'test', 'files': {}}))
        bundled = root/'runtime/node'
        bundled.mkdir()
        adapter = Dsh(root, root/'profile')
        with patch('sumika_next.dsh.shutil.which') as which:
            with self.assertRaisesRegex(DshError, 'bundled Node runtime is incomplete'):
                adapter.start()
            which.assert_not_called()
        (bundled/'node.exe').write_bytes(b'fixture')
        with patch('sumika_next.dsh.shutil.which') as which, \
                patch('sumika_next.dsh.subprocess.Popen', side_effect=RuntimeError('test launch boundary')) as launch:
            with self.assertRaisesRegex(RuntimeError, 'test launch boundary'):
                adapter.start()
            self.assertEqual(Path(launch.call_args.args[0][0]), bundled/'node.exe')
            which.assert_not_called()


if __name__ == '__main__':
    unittest.main()
