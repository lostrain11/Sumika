import json
import tempfile
import unittest
from pathlib import Path

from sumika_core.plugins import ManifestError, load_manifest


class ManifestTests(unittest.TestCase):
    def test_example_manifest_loads(self):
        path = Path(__file__).parents[2] / "plugins/examples/echo-provider/manifest.json"
        manifest = load_manifest(path)
        self.assertEqual(manifest.id, "example.echo-provider")
        self.assertIn("llm", manifest.capabilities)

    def test_tool_example_manifest_loads(self):
        path = Path(__file__).parents[2] / "plugins/examples/echo-tool/manifest.json"
        manifest = load_manifest(path)
        self.assertEqual(manifest.id, "example.echo-tool")
        self.assertEqual(manifest.capabilities, ["tool"])

    def test_required_fields_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"id": "missing"}), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_manifest(path)
