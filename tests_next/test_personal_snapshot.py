import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools.backup_personal_data import backup, restore, rebind_role_paths
from ui.data_lease import DataLease


class PersonalSnapshotTests(unittest.TestCase):
    def setUp(self):
        base = Path('.sumika-next/personal-snapshot-tests')
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=base)).resolve()
        self.source = self.root/'personal'
        self.source.mkdir()
        (self.source/'settings.json').write_text('{"enabled":false}', encoding='utf8')

    def test_database_and_settings_preserved(self):
        with sqlite3.connect(self.source/'chat.sqlite3') as db:
            db.execute('create table messages (id text, content text)')
            db.execute('insert into messages values (?, ?)', ('stable-id', '你好'))
        destination = self.root/'backup'
        result = backup(self.source, destination)
        self.assertEqual(result['status'], 'verified')
        with sqlite3.connect(destination/'data/chat.sqlite3') as db:
            self.assertEqual(db.execute('select * from messages').fetchall(), [('stable-id', '你好')])
        self.assertEqual((self.source/'settings.json').read_bytes(), (destination/'data/settings.json').read_bytes())
        self.assertFalse((destination/'data/sumika-bridge.lock').exists())

    def test_live_writer_rejected_before_destination(self):
        lease = DataLease(self.source).acquire()
        try:
            with self.assertRaises(OSError):
                backup(self.source, self.root/'backup')
        finally:
            lease.release()
        self.assertFalse((self.root/'backup').exists())

    def test_unknown_dsh_state_rejected(self):
        (self.source/'sumika-instance.json').write_text('{"state":"running","pid":1}')
        with self.assertRaisesRegex(ValueError, 'ownership'):
            backup(self.source, self.root/'backup')
        self.assertFalse((self.root/'backup').exists())

    def test_independent_profile_lock_blocks_snapshot(self):
        profile = self.source/'dsh-profiles/version'
        profile.mkdir(parents=True)
        (profile/'sumika-instance.json').write_text('{}')
        lease = DataLease(profile, filename='sumika-instance.lock').acquire()
        try:
            with self.assertRaises(OSError):
                backup(self.source, self.root/'backup')
        finally:
            lease.release()
        self.assertFalse((self.root/'backup').exists())
        # Failed acquisition must also release the bridge data lock.
        self.assertEqual(backup(self.source, self.root/'backup')['status'], 'verified')

    def test_snapshot_holds_existing_profile_lock_during_copy(self):
        import shutil
        profile = self.source/'dsh-profiles/version'
        profile.mkdir(parents=True)
        (profile/'sumika-instance.json').write_text('{}')
        real_copy = shutil.copyfile
        attempts = []
        def copy_with_competing_writer(source, target):
            with self.assertRaises(OSError):
                DataLease(profile, filename='sumika-instance.lock').acquire()
            attempts.append(True)
            return real_copy(source, target)
        with patch('tools.backup_personal_data.shutil.copyfile', side_effect=copy_with_competing_writer):
            backup(self.source, self.root/'backup')
        self.assertTrue(attempts)

    def test_only_generated_dsh_dependency_mount_is_excluded(self):
        generated = self.source/'dsh-profiles/version/profiles/node_modules'
        generated.mkdir(parents=True)
        (generated/'dependency.js').write_text('generated')
        user_modules = self.source/'roles/person/node_modules'
        user_modules.mkdir(parents=True)
        (user_modules/'resource.json').write_text('user resource')
        backup(self.source, self.root/'backup')
        manifest = json.loads((self.root/'backup/snapshot.json').read_text())
        self.assertIn('dsh-profiles/*/profiles/node_modules', manifest['excluded_generated_paths'])
        self.assertFalse((self.root/'backup/data/dsh-profiles/version/profiles/node_modules').exists())
        self.assertTrue((self.root/'backup/data/roles/person/node_modules/resource.json').is_file())

    def test_no_overwrite_or_recursive_backup(self):
        for destination in (self.root, self.source/'nested'):
            with self.assertRaises(ValueError):
                backup(self.source, destination)

    def test_failed_copy_does_not_get_verified_manifest(self):
        with patch('tools.backup_personal_data.shutil.copyfile', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                backup(self.source, self.root/'backup')
        self.assertFalse((self.root/'backup/snapshot.json').exists())
        self.assertTrue((self.source/'settings.json').is_file())

    def test_restore_keeps_unknown_state_and_original_bytes(self):
        original = {'id': 'stable-id', 'state': 'unknown', 'original': '不要重发 D:/old/path'}
        (self.source/'handoff.json').write_text(json.dumps(original), encoding='utf8')
        backup(self.source, self.root/'backup')
        result = restore(self.root/'backup', self.root/'restored')
        self.assertEqual(result['status'], 'bytes_restored')
        self.assertEqual((self.root/'restored/handoff.json').read_bytes(), (self.source/'handoff.json').read_bytes())
        with self.assertRaises(ValueError):
            restore(self.root/'backup', self.source)

    def test_corrupt_snapshot_rejected_before_writing(self):
        backup(self.source, self.root/'backup')
        (self.root/'backup/data/settings.json').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            restore(self.root/'backup', self.root/'restored')
        self.assertFalse((self.root/'restored').exists())

    def test_manifest_path_escape_cannot_create_files(self):
        backup(self.source, self.root/'backup')
        p = self.root/'backup/snapshot.json'
        data = json.loads(p.read_text())
        data['files']['../escape'] = next(iter(data['files'].values()))
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            restore(self.root/'backup', self.root/'restored')
        self.assertFalse((self.root/'restored').exists())

    def test_role_rebinding_preserves_history_scope_and_unknown_state(self):
        from extensions.models.settings import example, save, load
        from extensions.roles.conversations import Conversations
        role = self.source/'roles/person'
        role.mkdir(parents=True)
        (role/'card.json').write_text('{}')
        config = example(role, self.source/'memory.sqlite3')
        save(config, self.source/'role-model-settings.json')
        store = Conversations(self.source/'role-conversations.sqlite3')
        scope = store.scope_for('local-user', role, 'sumika')
        with store.connect() as db:
            db.execute('INSERT INTO role_turns VALUES (?,?,?,?,?,?,?,?)',
                       ('m1', scope, 'session', 'now', str(role), 'unknown', None, None))
        backup(self.source, self.root/'backup')
        target = self.root/'restored'
        restore(self.root/'backup', target)
        rebind_role_paths(target, self.source)
        recovered = Conversations(target/'role-conversations.sqlite3')
        self.assertEqual(recovered.scope_for('local-user', target/'roles/person', 'sumika'), scope)
        with recovered.connect() as db:
            self.assertEqual(db.execute('SELECT id,original,state FROM role_turns').fetchone(), ('m1', str(role), 'unknown'))
        self.assertEqual(load(target/'role-model-settings.json')['role']['database'], str(target/'memory.sqlite3'))
        self.assertEqual(load(self.source/'role-model-settings.json')['role']['role_dir'], str(role))

    def test_completed_restore_can_be_backed_up_and_relocated_again(self):
        from extensions.models.settings import example, save, load
        from extensions.roles.conversations import Conversations
        role = self.source/'roles/person'
        role.mkdir(parents=True)
        (role/'card.json').write_text('{}')
        save(example(role, self.source/'memory.sqlite3'), self.source/'role-model-settings.json')
        store = Conversations(self.source/'role-conversations.sqlite3')
        scope = store.scope_for('local-user', role, 'sumika')
        with store.connect() as db:
            db.execute('INSERT INTO role_turns VALUES (?,?,?,?,?,?,?,?)',
                       ('m1', scope, 'session', 'now', str(role), 'unknown', None, None))
        backup(self.source, self.root/'backup')
        first = self.root/'first'
        restore(self.root/'backup', first)
        rebind_role_paths(first, self.source)
        previous = (first/'role-restore-state.json').read_bytes()
        config = load(first/'role-model-settings.json')
        config['temperature'] = 0.3  # Normal settings changes after recovery.
        save(config, first/'role-model-settings.json')
        backup(first, self.root/'second-backup')
        second = self.root/'second'
        restore(self.root/'second-backup', second)
        rebind_role_paths(second, first)
        rebind_role_paths(second, first)
        recovered = Conversations(second/'role-conversations.sqlite3')
        self.assertEqual(recovered.scope_for('local-user', second/'roles/person', 'sumika'), scope)
        with recovered.connect() as db:
            self.assertEqual(db.execute('SELECT id,original,state FROM role_turns').fetchone(),
                             ('m1', str(role), 'unknown'))
        config = load(second/'role-model-settings.json')
        self.assertEqual(config['temperature'], 0.3)
        self.assertEqual(config['role']['database'], str(second/'memory.sqlite3'))
        archives = list((second/'role-restore-history').glob('*.json'))
        self.assertEqual([p.read_bytes() for p in archives], [previous])
        self.assertEqual((first/'role-restore-state.json').read_bytes(), previous)

    def test_copied_pending_restore_cannot_be_rebased(self):
        from extensions.models.settings import example, save
        role = self.source/'roles/person'
        role.mkdir(parents=True)
        (role/'card.json').write_text('{}')
        save(example(role, self.source/'memory.sqlite3'), self.source/'role-model-settings.json')
        backup(self.source, self.root/'backup')
        first = self.root/'first'
        restore(self.root/'backup', first)
        with patch('extensions.models.settings.save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                rebind_role_paths(first, self.source)
        backup(first, self.root/'pending-backup')
        second = self.root/'second'
        restore(self.root/'pending-backup', second)
        before = (second/'role-restore-state.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            rebind_role_paths(second, first)
        self.assertEqual((second/'role-restore-state.json').read_bytes(), before)
        self.assertFalse((second/'role-restore-history').exists())

    def test_interrupted_rebind_blocks_startup_then_resumes(self):
        from extensions.models.settings import example, save, load
        from extensions.roles.conversations import Conversations
        from ui.server import serve
        role = self.source/'roles/person'
        role.mkdir(parents=True)
        (role/'card.json').write_text('{}')
        save(example(role, self.source/'memory.sqlite3'), self.source/'role-model-settings.json')
        store = Conversations(self.source/'role-conversations.sqlite3')
        scope = store.scope_for('local-user', role, 'sumika')
        backup(self.source, self.root/'backup')
        target = self.root/'restored'
        restore(self.root/'backup', target)
        # Fail after the database binding moved but before settings publication.
        with patch('extensions.models.settings.save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                rebind_role_paths(target, self.source)
        self.assertEqual(json.loads((target/'role-restore-state.json').read_text())['status'], 'pending')
        with patch('ui.server.Bridge') as construct:
            with self.assertRaisesRegex(ValueError, 'recovery is incomplete'):
                serve(target/'role-model-settings.json', port=0)
            construct.assert_not_called()
        rebind_role_paths(target, self.source)
        rebind_role_paths(target, self.source)  # Retry completed request is idempotent.
        recovered = Conversations(target/'role-conversations.sqlite3')
        self.assertEqual(recovered.scope_for('local-user', target/'roles/person', 'sumika'), scope)
        self.assertEqual(json.loads((target/'role-restore-state.json').read_text())['status'], 'complete')
        self.assertEqual(load(target/'role-model-settings.json')['role']['role_dir'], str(target/'roles/person'))
        changed = load(target/'role-model-settings.json')
        changed['temperature'] = 0.3
        save(changed, target/'role-model-settings.json')
        with self.assertRaisesRegex(ValueError, 'settings changed'):
            rebind_role_paths(target, self.source)


if __name__ == '__main__':
    unittest.main()
