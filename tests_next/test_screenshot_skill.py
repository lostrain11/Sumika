import tempfile
import unittest
from pathlib import Path

from extensions.desktop.screenshot_skill import publish, NAME, MARKER


class ScreenshotSkillTests(unittest.TestCase):
    def fixture(self, directory):
        root=Path(directory)/"product's copy";home=Path(directory)/'profile'
        source=Path(__file__).resolve().parents[1]/'extensions/desktop/screenshot-skill.md'
        target=root/'extensions/desktop/screenshot-skill.md'
        target.parent.mkdir(parents=True);target.write_text(source.read_text(encoding='utf8'),encoding='utf8')
        runner=root/'tools/run_module.py';runner.parent.mkdir();runner.touch()
        database=Path(directory)/'capabilities.sqlite3';database.touch()
        return root,home,database

    def test_profile_skill_binds_exact_registry_and_relocates_idempotently(self):
        with tempfile.TemporaryDirectory() as folder:
            root,home,database=self.fixture(folder)
            result=publish(home,root=root,capabilities=database)
            path=Path(result['path']);content=path.read_text(encoding='utf8')
            self.assertIn(MARKER,content);self.assertNotIn('{{',content)
            self.assertIn(str(database.resolve()),content)
            self.assertIn("product''s copy",content)
            timestamp=path.stat().st_mtime_ns
            publish(home,root=root,capabilities=database)
            self.assertEqual(path.stat().st_mtime_ns,timestamp)
            replacement=Path(folder)/'new.sqlite3';replacement.touch()
            publish(home,root=root,capabilities=replacement)
            self.assertIn(str(replacement.resolve()),path.read_text(encoding='utf8'))
            self.assertNotIn(str(database.resolve()),path.read_text(encoding='utf8'))

    def test_missing_service_removes_only_owned_skill(self):
        with tempfile.TemporaryDirectory() as folder:
            root,home,database=self.fixture(folder)
            path=Path(publish(home,root=root,capabilities=database)['path'])
            sibling=path.parent/'user-notes.txt';sibling.write_text('preserve')
            result=publish(home,root=root,capabilities=None)
            self.assertFalse(result['registered']);self.assertFalse(path.exists());self.assertTrue(sibling.exists())

    def test_user_skill_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root,home,database=self.fixture(folder)
            path=home/'skills'/NAME/'SKILL.md';path.parent.mkdir(parents=True);path.write_text('user content')
            self.assertFalse(publish(home,root=root,capabilities=database)['registered'])
            self.assertEqual(path.read_text(),'user content')
