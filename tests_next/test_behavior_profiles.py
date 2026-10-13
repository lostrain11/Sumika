"""P14 companion profile store: closed schema, revision guard, CRUD/delete
semantics, corrupt-file neutrality, template init, upgrade vs new user."""
import json
import tempfile
import unittest
from pathlib import Path

from extensions.behavior.profiles import (
    CompanionProfileStore, ProfileError)


def profile(name='自定义', **overrides):
    base = {'name': name, 'enabled_for_auto': True,
            'scenario_description': '场景',
            'response_instructions': '指引',
            'settings': {'proactive_enabled': True,
                         'proactive_interval_seconds': 300,
                         'behavior_prompts_enabled': True,
                         'context_sources': ['text']}}
    base.update(overrides)
    return base


class StoreInitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p14-profiles-')
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_first_init_plants_three_templates_manual_study(self):
        store = CompanionProfileStore(self.root)
        state = store.load()
        self.assertEqual([item['name'] for item in state['profiles']],
                         ['学习', '游戏', '安静'])
        self.assertEqual(state['selection_policy'], 'manual')
        self.assertEqual(state['manual_profile_id'],
                         state['profiles'][0]['id'])

    def test_new_user_arms_auto_without_a_selection(self):
        store = CompanionProfileStore(self.root, new_user=True)
        state = store.load()
        self.assertEqual(state['selection_policy'], 'auto')
        self.assertIsNone(state['manual_profile_id'])

    def test_corrupt_file_kept_and_store_stands_neutral(self):
        self.root.mkdir(exist_ok=True)
        (self.root/'companion-profiles.json').write_text(
            '{broken', encoding='utf8')
        store = CompanionProfileStore(self.root)
        with self.assertRaises(ProfileError):
            store.load()
        kept = list(self.root.glob('companion-profiles.json.corrupt-*'))
        self.assertEqual(len(kept), 1)
        # The store is now neutral: no profiles, manual, no selection.
        state = store.load()
        self.assertEqual(state['profiles'], [])
        self.assertIsNone(state['manual_profile_id'])
        self.assertFalse(any(
            item.get('recording') for item in [state]))  # nothing granted


class StoreCrudTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p14-crud-')
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = CompanionProfileStore(self.root)
        self.store.load()
        self.revision = self.store.load()['revision']

    def test_create_update_and_revision_conflict(self):
        created = self.store.create(profile(), expected_revision=self.revision)
        self.assertEqual(created['status'], 'created')
        new_revision = self.store.load()['revision']
        with self.assertRaises(ProfileError):
            self.store.update(created['id'], {'name': '改名'},
                              expected_revision=new_revision - 1)
        updated = self.store.update(created['id'], {'name': '改名'},
                                    expected_revision=new_revision)
        self.assertEqual(updated['status'], 'updated')
        names = [item['name'] for item in self.store.load()['profiles']]
        self.assertIn('改名', names)

    def test_closed_schema_rejects_unknown_and_forbidden_fields(self):
        with self.assertRaises(ProfileError):
            self.store.create(profile(provider='openai'),
                              expected_revision=self.revision)
        with self.assertRaises(ProfileError):
            self.store.create(profile(bogus=1),
                              expected_revision=self.revision)
        bad_settings = profile()
        bad_settings['settings']['interval'] = 5
        with self.assertRaises(ProfileError):
            self.store.create(bad_settings, expected_revision=self.revision)

    def test_field_limits(self):
        with self.assertRaises(ProfileError):
            self.store.create(profile(name='x' * 81),
                              expected_revision=self.revision)
        long_instructions = profile(response_instructions='x' * 2001)
        with self.assertRaises(ProfileError):
            self.store.create(long_instructions, expected_revision=self.revision)
        bad_interval = profile()
        bad_interval['settings']['proactive_interval_seconds'] = 60
        with self.assertRaises(ValueError):
            self.store.create(bad_interval, expected_revision=self.revision)

    def test_duplicate_creates_disabled_copy(self):
        created = self.store.create(profile(name='原味'),
                                    expected_revision=self.revision)
        revision = self.store.load()['revision']
        duplicated = self.store.duplicate(created['id'],
                                          expected_revision=revision)
        copy = [item for item in self.store.load()['profiles']
                if item['id'] == duplicated['id']][0]
        self.assertEqual(copy['name'], '原味 副本')
        self.assertFalse(copy['enabled_for_auto'])

    def test_profile_id_must_exist_for_update_and_select(self):
        with self.assertRaises(ProfileError):
            self.store.update('missing', {'name': 'x'},
                              expected_revision=self.revision)
        with self.assertRaises(ProfileError):
            self.store.select('manual', 'missing',
                              expected_revision=self.revision)


class SelectionAndDeleteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p14-select-')
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = CompanionProfileStore(self.root)
        state = self.store.load()
        self.revision = state['revision']
        self.study_id = state['profiles'][0]['id']

    def test_manual_selection_persists_until_explicit_auto(self):
        self.store.select('manual', self.study_id,
                          expected_revision=self.revision)
        self.assertEqual(self.store.runtime()['reason'], 'manual')
        revision = self.store.load()['revision']
        self.store.select('auto', expected_revision=revision)
        runtime = self.store.runtime()
        # 学习与游戏两个模板都启用 auto：诚实报告 ambiguous（P15 评分器定夺）。
        self.assertEqual(runtime['reason'], 'ambiguous')

    def test_deleting_current_manual_leaves_null_never_auto(self):
        self.store.select('manual', self.study_id,
                          expected_revision=self.revision)
        revision = self.store.load()['revision']
        self.store.delete(self.study_id, expected_revision=revision)
        runtime = self.store.runtime()
        self.assertEqual(runtime['reason'], 'unknown')
        self.assertIsNone(runtime['effective_profile_id'])
        state = self.store.load()
        self.assertEqual(state['selection_policy'], 'manual')

    def test_deleting_one_of_two_auto_profiles_matches_the_remaining(self):
        state = self.store.load()
        game_id = state['profiles'][1]['id']
        self.store.select('auto', expected_revision=self.revision)
        # 两个 auto 模板（学习+游戏）-> ambiguous
        self.assertEqual(self.store.runtime()['reason'], 'ambiguous')
        revision = self.store.load()['revision']
        self.store.delete(game_id, expected_revision=revision)
        runtime = self.store.runtime()
        self.assertEqual(runtime['reason'], 'matched')
        self.assertNotEqual(runtime['effective_profile_id'], game_id)

    def test_deleting_every_profile_is_legal_and_null(self):
        state = self.store.load()
        for index, profile in enumerate(state['profiles']):
            self.store.delete(profile['id'],
                              expected_revision=self.store.load()['revision'])
        self.assertEqual(self.store.load()['profiles'], [])
        self.assertEqual(self.store.runtime()['reason'], 'unknown')

    def test_unknown_context_source_and_dedup(self):
        bad = profile()
        bad['settings']['context_sources'] = ['clipboard']
        with self.assertRaises(ProfileError):
            self.store.create(bad, expected_revision=self.revision)
        dedup = profile()
        dedup['settings']['context_sources'] = ['text', 'text', 'image']
        created = self.store.create(dedup, expected_revision=self.revision)
        target = [item for item in self.store.load()['profiles']
                  if item['id'] == created['id']][0]
        self.assertEqual(target['settings']['context_sources'],
                         ['text', 'image'])


if __name__ == '__main__':
    unittest.main()
