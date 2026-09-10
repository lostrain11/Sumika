import hashlib
import json
import unittest

from tools.check_release_assets import AVATAR_ROOT, MANIFEST, SKILL_PATHS, check_files


class ReleaseAssetsTests(unittest.TestCase):
    def test_personal_skill_paths_cannot_ship(self):
        files = self.assets()
        files[SKILL_PATHS] = json.dumps({'tool_directories': [], 'download_cache_directory': ''}).encode()
        self.assertEqual(check_files(set(files), files.__getitem__), [])
        files[SKILL_PATHS] = json.dumps({'tool_directories': ['D:/personal-tools'], 'download_cache_directory': ''}).encode()
        self.assertIn('Official tool-registry configuration must contain empty paths.', check_files(set(files), files.__getitem__))

    def assets(self):
        model = b'glTF fixture'
        return {
            MANIFEST: json.dumps({'schema': 'sumika-avatar-distribution/v1', 'default': 'sample.vrm',
                                  'files': {'sample.vrm': hashlib.sha256(model).hexdigest()}}).encode(),
            AVATAR_ROOT + 'sample.vrm': model,
        }

    def test_only_reviewed_assets_pass(self):
        files = self.assets()
        self.assertEqual(check_files(set(files), files.__getitem__), [])

    def test_changed_default_is_rejected(self):
        files = self.assets()
        files[AVATAR_ROOT + 'sample.vrm'] = b'private replacement'
        self.assertTrue(check_files(set(files), files.__getitem__))

    def test_private_models_and_runtime_are_rejected(self):
        for name in ('.sumika-desktop/avatar-models/private.vrm', '.sumika-daily-store/session.json',
                     '.zcode/state.json', 'frontend/public/private.vrm', 'frontend/public/renamed.bin',
                     'assets/avatars/private.png', 'data.sqlite3-wal', '.env.local'):
            with self.subTest(name=name):
                files = self.assets()
                files[name] = b'glTF private model'
                self.assertTrue(check_files(set(files), files.__getitem__))

    def test_path_escape_in_manifest_is_rejected(self):
        files = self.assets()
        manifest = json.loads(files[MANIFEST])
        manifest['files']['../private.vrm'] = 'a' * 64
        files[MANIFEST] = json.dumps(manifest).encode()
        self.assertTrue(check_files(set(files), files.__getitem__))


if __name__ == '__main__':
    unittest.main()
