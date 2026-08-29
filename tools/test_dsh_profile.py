import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from dsh_profile import ProfileBindingError, verify_profile_binding
except ModuleNotFoundError:
    from tools.dsh_profile import ProfileBindingError, verify_profile_binding


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


def _roster(*ids):
    return {
        "result": {
            "ok": True,
            "value": {
                "presets": [
                    {"id": preset_id, "trust": "user"}
                    for preset_id in ids
                ]
            },
        }
    }


class DshProfileTests(unittest.TestCase):
    def test_matching_user_preset_roster_is_strong(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / ".agent-presets" / "sumika-work").mkdir(parents=True)
            with patch("dsh_profile.urlopen", return_value=_Response(_roster("sumika-work", "other"))):
                result = verify_profile_binding("http://127.0.0.1:3080", profile)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["confidence"], "strong")
        self.assertEqual(result["overlap_count"], 1)

    def test_disjoint_roster_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            (profile / ".agent-presets" / "local-only").mkdir(parents=True)
            with patch("dsh_profile.urlopen", return_value=_Response(_roster("remote-only"))):
                with self.assertRaises(ProfileBindingError) as context:
                    verify_profile_binding("http://127.0.0.1:3080", profile)
        self.assertEqual(context.exception.code, "profile-mismatch")

    def test_empty_rosters_are_accepted_with_weak_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("dsh_profile.urlopen", return_value=_Response(_roster())):
                result = verify_profile_binding("http://localhost:3080", Path(directory))
        self.assertEqual(result["confidence"], "weak")
        self.assertEqual(result["local_user_preset_count"], 0)

    def test_remote_user_roster_without_local_marker_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("dsh_profile.urlopen", return_value=_Response(_roster("remote-only"))):
                with self.assertRaises(ProfileBindingError) as context:
                    verify_profile_binding("http://[::1]:3080", Path(directory))
        self.assertEqual(context.exception.code, "profile-ambiguous")

    def test_non_loopback_endpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProfileBindingError) as context:
                verify_profile_binding("https://example.com:3080", Path(directory))
        self.assertEqual(context.exception.code, "endpoint-not-loopback")


if __name__ == "__main__":
    unittest.main()
