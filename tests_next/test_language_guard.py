"""The output-language policy is prompt text; the guard is what enforces it."""
from pathlib import Path
import tempfile
import unittest

from extensions.roles.chat import RoleChat


class _Provider:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        text = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        return {"text": text, "usage_status": "reported",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class _Session:
    def request(self, operation, data):
        if operation == "localize_names":
            return {"text": data["text"], "applied": []}
        return {"role_context": {"name": "测试角色", "identity": "简洁"},
                "selection": {"language_policy_source": "card"}}

    def close(self):
        pass


def _chat(answers, directory, *, language=None):
    settings = {
        "enabled": True, "provider": "openai-compatible", "model": "test",
        "endpoint": "http://127.0.0.1", "key_env": "NOPE", "timeout_seconds": 5,
        "max_tokens": 64, "temperature": 0.7, "context_length": 1024,
        "multimodal": {"enabled": False},
        "memory": {"auto_extract": False},
        "language": language or {"target": "zh-Hans"},
    }
    chat = RoleChat(settings)
    chat._provider = lambda: chat.provider
    chat._session = lambda: _Session()
    chat.provider = _Provider(answers)
    chat._usage_store = None
    directory.mkdir(parents=True, exist_ok=True)
    return chat


class LanguageGuardTests(unittest.TestCase):
    def setUp(self):
        self._usage = tempfile.TemporaryDirectory()
        self.usage_dir = Path(self._usage.name)

    def tearDown(self):
        self._usage.cleanup()

    def _run(self, answers):
        chat = _chat(answers, self.usage_dir)
        # usage recording needs a store; keep it out of this assertion
        chat._record_usage = lambda *args, **kwargs: None
        return chat, chat.reply("在吗")

    def test_clean_answer_is_not_retried(self):
        chat, result = self._run(["嗯，我在。有事说就行。"])
        self.assertEqual(chat.provider.calls, 1)
        self.assertEqual(result["language_guard"],
                         {"clean": True, "changed": False, "transliterated": 0,
                          "interjections": [], "kana_found": [], "kana_remaining": []})

    def test_kana_interjection_becomes_a_chinese_word_without_a_second_call(self):
        """A slipped syllable is rewritten locally: no second generation."""
        chat, result = self._run(["ねえ、在吗？"])
        self.assertEqual(chat.provider.calls, 1)
        self.assertTrue(result["language_guard"]["clean"])
        self.assertEqual(result["language_guard"]["kana_remaining"], [])
        self.assertIn("呐", result["text"])
        self.assertNotEqual(result["text"], "ねえ、在吗？")

    def test_romaji_is_left_alone(self):
        """Romaji is readable; only Japanese script has to go."""
        chat, result = self._run(["hah？maa，我这边刚练完鼓。"])
        self.assertEqual(chat.provider.calls, 1)
        self.assertIn("hah？", result["text"])
        self.assertIn("maa", result["text"])
        self.assertFalse(result["language_guard"]["changed"])

    def test_uncovered_kana_is_reported_not_invented(self):
        # ゐ is outside the conversion tables: the result says so instead of guessing,
        # and the model is never asked twice for a language slip.
        chat = _chat(["ゐ、いますよ。"], self.usage_dir)
        chat._record_usage = lambda *args, **kwargs: None
        result = chat.reply("在吗")
        self.assertEqual(chat.provider.calls, 1)
        guard = result["language_guard"]
        self.assertFalse(guard["clean"])
        self.assertTrue(guard["kana_remaining"])
        # The reply keeps the character the tables could not convert.
        self.assertIn("ゐ", result["text"])


if __name__ == "__main__":
    unittest.main()
