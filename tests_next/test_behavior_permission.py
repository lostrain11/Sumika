"""P10 behavior permission: persistence, fail-closed, pause/revoke semantics,
startup rebinding freshness, exclusion list."""
import json
import tempfile
import unittest
from pathlib import Path

from extensions.behavior.permission import (
    BehaviorPermissions, PermissionClosed)


def granted(directory, *, startup_resume=True):
    permissions = BehaviorPermissions(directory)
    state = permissions.load()
    permissions.save({'recording': True, 'startup_resume': startup_resume},
                     revision=state['revision'])
    return permissions


class PermissionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p10-perm-')
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.root = self.folder/'behavior'
        self.root.mkdir()

    def test_missing_directory_fails_closed_and_never_relocates(self):
        permissions = BehaviorPermissions(self.folder/'gone'/'behavior')
        with self.assertRaises(PermissionClosed):
            permissions.load()

    def test_corrupt_file_fails_closed_without_recreation(self):
        (self.root/'permission.json').write_text('{broken', encoding='utf8')
        permissions = BehaviorPermissions(self.root)
        with self.assertRaises(PermissionClosed):
            permissions.load()
        self.assertEqual((self.root/'permission.json').read_text(encoding='utf8'),
                         '{broken')

    def test_fresh_root_defaults_to_no_permission(self):
        permissions = BehaviorPermissions(self.root)
        state = permissions.load()
        self.assertFalse(state['recording'])
        self.assertFalse(state['startup_resume'])
        self.assertFalse(permissions.effective(state)['can_record'])
        for name in ('sumika', 'sumikapet', 'sumikaprocessaudio'):
            self.assertIn(name, state['excluded_apps'])

    def test_revision_guard_and_unknown_fields(self):
        permissions = granted(self.root)
        revision = permissions.load()['revision']
        with self.assertRaises(ValueError):
            permissions.save({'recording': False}, revision=revision - 1)
        with self.assertRaises(ValueError):
            permissions.save({'text': 'blob'}, revision=revision)
        self.assertTrue(permissions.load()['recording'])

    def test_pause_persists_and_never_resumes_across_restart(self):
        permissions = granted(self.root)
        permissions.pause(revision=permissions.load()['revision'])
        # A restart is a fresh instance reading the same file: paused stays,
        # and it suppresses recording.
        restarted = BehaviorPermissions(self.root)
        self.assertTrue(restarted.load()['paused'])
        self.assertFalse(restarted.effective()['can_record'])
        # An explicit resume re-enables; the user acts, not the process.
        restarted.resume(revision=restarted.load()['revision'])
        self.assertTrue(restarted.effective()['can_record'])

    def test_revoke_is_terminal_for_switches(self):
        permissions = granted(self.root)
        permissions.revoke(revision=permissions.load()['revision'])
        restarted = BehaviorPermissions(self.root)
        with self.assertRaises(ValueError):
            restarted.save({'recording': True},
                           revision=restarted.load()['revision'])
        self.assertFalse(restarted.effective()['can_record'])
        self.assertTrue(restarted.load()['revoked'])

    def test_exclusion_defaults_cannot_be_removed(self):
        permissions = granted(self.root)
        with self.assertRaises(ValueError):
            permissions.exclusion_remove('sumika',
                                         revision=permissions.load()['revision'])
        permissions.exclusion_add('game.exe',
                                  revision=permissions.load()['revision'])
        self.assertIn('game.exe', permissions.load()['excluded_apps'])
        permissions.exclusion_remove('game.exe',
                                     revision=permissions.load()['revision'])
        self.assertNotIn('game.exe', permissions.load()['excluded_apps'])


class StartupRebindTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p10-rebind-')
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)/'behavior'
        self.root.mkdir()
        self.bindings = []

    def resolver(self):
        def resolve():
            if not self.bindings:
                return None
            return self.bindings.pop(0)
        return resolve

    def test_rebind_returns_a_fresh_binding_only_when_permitted(self):
        permissions = BehaviorPermissions(self.root)
        binding, reason = permissions.startup_binding(self.resolver())
        self.assertIsNone(binding)
        self.assertIn('not granted', reason)
        granted(self.root, startup_resume=True)
        permissions = BehaviorPermissions(self.root)
        self.bindings.append({'handle': 11, 'process_id': 22,
                              'process_creation': 'c1', 'image': 'edge.exe'})
        binding, reason = permissions.startup_binding(self.resolver())
        self.assertEqual(binding['process_id'], 22)
        self.assertIsNone(reason)

    def test_excluded_foreground_fails_closed(self):
        granted(self.root, startup_resume=True)
        permissions = BehaviorPermissions(self.root)
        permissions.exclusion_add('game.exe',
                                  revision=permissions.load()['revision'])
        self.bindings.append({'handle': 1, 'process_id': 2,
                              'process_creation': 'c', 'image': 'GAME.EXE'})
        binding, reason = permissions.startup_binding(self.resolver())
        self.assertIsNone(binding)
        self.assertIn('excluded', reason)

    def test_paused_permission_never_rebinds(self):
        permissions = granted(self.root, startup_resume=True)
        permissions.pause(revision=permissions.load()['revision'])
        self.bindings.append({'handle': 1, 'process_id': 2,
                              'process_creation': 'c', 'image': 'edge.exe'})
        binding, reason = permissions.startup_binding(self.resolver())
        self.assertIsNone(binding)
        self.assertIn('not granted', reason)
        self.assertEqual(len(self.bindings), 1)  # The resolver was never
        # consumed: a paused permission is decided before touching the OS.


if __name__ == '__main__':
    unittest.main()
