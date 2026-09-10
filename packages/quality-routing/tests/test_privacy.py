from __future__ import annotations

import unittest

from quality_routing import looks_like_secret_text


class PrivacyTests(unittest.TestCase):
    def test_original_secret_patterns_remain_detected(self):
        for value in (
            "sk-abcdefgh1234",
            "Bearer abcdefgh.ijklmnop",
            "api_key=hidden-value",
            "token: hidden-value",
            "password=hidden-value",
            "secret: hidden-value",
            "otp=123456",
        ):
            with self.subTest(value=value):
                self.assertTrue(looks_like_secret_text(value))

    def test_plain_metadata_is_not_secret_shaped(self):
        for value in (None, 12, "build-1", "role", "fixed-suite"):
            with self.subTest(value=value):
                self.assertFalse(looks_like_secret_text(value))


if __name__ == "__main__":
    unittest.main()

