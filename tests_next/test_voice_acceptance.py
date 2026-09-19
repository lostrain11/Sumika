import unittest

from tools.verify_voice_local import char_recall


class VoiceAcceptanceMetricTests(unittest.TestCase):
    def test_perfect_and_partial_recall(self):
        self.assertEqual(char_recall("今天排练", "今天排练"), 1.0)
        self.assertEqual(char_recall("今天排练", "今天"), 0.5)

    def test_punctuation_and_spacing_do_not_count(self):
        self.assertEqual(char_recall("今天排练，很顺利。", "今天 排练 很 顺利"), 1.0)

    def test_extra_recognized_characters_do_not_inflate_recall(self):
        # Recalling the expected text plus hallucinated words must not score above 1.
        self.assertLessEqual(char_recall("今天", "今天 明天 后天"), 1.0)
        self.assertEqual(char_recall("今天", "今天 明天 后天"), 1.0)

    def test_empty_expectation_is_zero_not_an_error(self):
        self.assertEqual(char_recall("", "任何内容"), 0.0)
        self.assertEqual(char_recall("，。", "任何内容"), 0.0)


if __name__ == "__main__":
    unittest.main()
