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
                         {"retried": False, "clean": True, "transliterated": 0,
                          "kana_found": [], "kana_remaining": []})

    def test_kana_answer_is_rewritten_locally_without_a_second_call(self):
        """A slipped syllable must not cost another generation."""
        chat, result = self._run(["ねえ、在吗？"])
        self.assertEqual(chat.provider.calls, 1)
        self.assertFalse(result["language_guard"]["retried"])
        self.assertTrue(result["language_guard"]["clean"])
        self.assertEqual(result["language_guard"]["kana_remaining"], [])
        self.assertEqual(result["language_guard"]["transliterated"], 2)
        self.assertIn("nee", result["text"])
        self.assertNotEqual(result["text"], "ねえ、在吗？")

    def test_retry_still_available_when_explicitly_enabled(self):
        chat = _chat(["ねえ、在吗？", "hah？嗯，我在。"], self.usage_dir,
                     language={"retry_on_kana": True})
        chat._record_usage = lambda *args, **kwargs: None
        result = chat.reply("在吗")
        self.assertEqual(chat.provider.calls, 2)
        self.assertTrue(result["language_guard"]["retried"])
        self.assertTrue(result["language_guard"]["clean"])

    def test_unclean_after_enabled_retry_is_reported_not_hidden(self):
        chat = _chat(["ねえ、在吗？", "はい、いますよ。"], self.usage_dir,
                     language={"retry_on_kana": True})
        chat._record_usage = lambda *args, **kwargs: None
        result = chat.reply("在吗")
        self.assertEqual(chat.provider.calls, 2)
        guard = result["language_guard"]
        self.assertTrue(guard["retried"])
        self.assertFalse(guard["clean"])
        self.assertTrue(guard["kana_remaining"])
        # The reply is whatever the model said; nothing is invented or stripped.
        self.assertIn("はい、いますよ。", result["text"])


if __name__ == "__main__":
    unittest.main()
