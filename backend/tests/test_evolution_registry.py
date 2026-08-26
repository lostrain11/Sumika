import json
import tempfile
import unittest
from pathlib import Path

from sumika_core.evolution import EvolutionRegistry


class EvolutionRegistryTests(unittest.TestCase):
    def test_registry_is_read_only_and_reports_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps({"entries": [{"id": "dsh", "license": "MIT"}]}), encoding="utf-8")
            registry = EvolutionRegistry(path)
            self.assertEqual(registry.list()[0]["id"], "dsh")
            report = registry.check()
            self.assertTrue(report["ok"])
            self.assertTrue(report["requires_user_approval"])


if __name__ == "__main__":
    unittest.main()
