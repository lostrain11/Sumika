import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sumika_core.integrations.ccswitch_compatibility import CCSwitchCompatibilityChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CCSwitchCompatibilityTests(unittest.TestCase):
    def _checker_with_fixed_upstream(self, *, changed_path: str | None = None):
        baseline = json.loads(
            (REPOSITORY_ROOT / "docs" / "integrations" / "cc-switch-compatibility.json").read_text(
                encoding="utf-8"
            )
        )
        files = {
            entry["path"]: (
                "ccswitch://v1/import\nversion != \"v1\"\n\"provider\" => parse_provider_deeplink\n"
                if entry["path"].endswith("deeplink/parser.rs")
                else f"fixed fixture: {entry['path']}\n"
            ).encode("utf-8")
            for entry in baseline["monitored_files"]
        }
        if changed_path:
            files[changed_path] = b"changed fixture\n"
        for entry in baseline["monitored_files"]:
            if entry["path"] != changed_path:
                entry["sha256"] = hashlib.sha256(files[entry["path"]]).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(baseline), encoding="utf-8")
            checker = CCSwitchCompatibilityChecker(manifest_path)
            yield checker, files

    def test_fixed_github_responses_report_latest_without_network(self):
        for checker, files in self._checker_with_fixed_upstream():
            def fake_json(url, _timeout):
                if url.endswith("/releases/latest"):
                    return {"tag_name": "v3.20.0", "html_url": "https://example.invalid/release"}
                if "/tags?" in url:
                    return [{"name": "v3.20.0"}]
                if "/releases?" in url:
                    return [{"tag_name": "v3.20.0", "published_at": "2026-08-23T00:00:00Z"}]
                raise AssertionError(url)

            def fake_bytes(url, _timeout):
                return files[url.split("/v3.20.0/", 1)[1]]

            with patch.object(checker, "_json", side_effect=fake_json), patch.object(checker, "_bytes", side_effect=fake_bytes):
                result = checker.check()
            self.assertEqual(result["status"], "up_to_date")
            self.assertEqual(result["latest_tags"], ["v3.20.0"])
            self.assertEqual(result["fixtures"]["failed"], 0)

    def test_non_protocol_monitored_change_requires_manual_review(self):
        for checker, files in self._checker_with_fixed_upstream(changed_path="src/components/DeepLinkImportDialog.tsx"):
            def fake_json(url, _timeout):
                if url.endswith("/releases/latest"):
                    return {"tag_name": "v3.20.0"}
                if "/tags?" in url:
                    return [{"name": "v3.20.0"}]
                return [{"tag_name": "v3.20.0"}]

            def fake_bytes(url, _timeout):
                return files[url.split("/v3.20.0/", 1)[1]]

            with patch.object(checker, "_json", side_effect=fake_json), patch.object(checker, "_bytes", side_effect=fake_bytes):
                result = checker.check()
            self.assertEqual(result["status"], "review_required")
            self.assertEqual(result["review_changes"][0]["path"], "src/components/DeepLinkImportDialog.tsx")
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
