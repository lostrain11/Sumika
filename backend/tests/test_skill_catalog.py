import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sumika_core.agent.skill_catalog import SkillCatalog, SkillCatalogError
from sumika_core.storage import Storage


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.root = Path(self.tempdir.name) / ".agents" / "skills"
        self.skill_dir = self.root / "demo-skill"
        self.skill_dir.mkdir(parents=True)
        self.skill_path = self.skill_dir / "SKILL.md"
        self.skill_path.write_text(
            "---\n"
            "id: demo-skill\n"
            "name: Demo Skill\n"
            "description: bounded metadata\n"
            "version: 1.0.0\n"
            "permissions: read search\n"
            "---\n"
            "# Demo Skill\n\n"
            "This private instruction body must never appear in the projection.\n",
            encoding="utf-8",
        )
        self.storage = Storage()
        self.catalog = SkillCatalog(self.storage, default_paths=(self.root,))

    def tearDown(self):
        self.storage.close()
        self.tempdir.cleanup()

    def test_discovery_is_metadata_only_and_does_not_expose_absolute_path(self):
        result = self.catalog.discover()

        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["state"], "discovered")
        self.assertEqual(item["path_label"], "demo-skill/SKILL.md")
        self.assertNotIn(str(self.tempdir.name), str(item))
        self.assertNotIn("private instruction body", str(item))
        self.assertEqual(item["permissions"], ["read", "search"])
        self.assertTrue(item["metadata_only"])

    def test_approval_requires_unchanged_hash_and_revoke_keeps_file(self):
        discovered = self.catalog.discover()[0]
        approved = self.catalog.approve(discovered["candidate_id"])
        self.assertEqual(approved["state"], "approved")
        self.assertTrue(self.skill_path.exists())

        self.skill_path.write_text(self.skill_path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        refreshed = self.catalog.refresh()
        self.assertEqual(refreshed[0]["state"], "changed")
        with self.assertRaisesRegex(SkillCatalogError, "changed since discovery"):
            self.catalog.approve(discovered["candidate_id"])

        rediscovered = self.catalog.discover()[0]
        approved_again = self.catalog.approve(rediscovered["candidate_id"])
        revoked = self.catalog.revoke(approved_again["candidate_id"])
        self.assertEqual(revoked["state"], "revoked")
        self.assertTrue(self.skill_path.exists())

    def test_missing_file_becomes_an_invalid_tombstone(self):
        discovered = self.catalog.discover()[0]
        self.skill_path.unlink()

        refreshed = self.catalog.refresh()
        self.assertEqual(refreshed[0]["candidate_id"], discovered["candidate_id"])
        self.assertEqual(refreshed[0]["state"], "invalid")
        self.assertIn("regular SKILL.md", refreshed[0]["error"])
        listed = self.catalog.list()
        self.assertEqual(listed[0]["state"], "invalid")

    def test_default_path_label_is_structural(self):
        self.assertEqual(self.catalog.default_path_labels(), [".agents/skills"])


if __name__ == "__main__":
    unittest.main()
