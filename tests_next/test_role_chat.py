import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.models.cloud import CloudError, CloudProvider
from extensions.models.settings import example, load, save, validate
from extensions.roles.chat import RoleChat, build_messages, usage_counts
from extensions.roles.roles import import_card


def _role_dir(root):
    existing = Path(root) / "store" / "test-role"
    if (existing / "role.json").is_file():
        return existing
    card = root / "card.json"
    card.write_text(json.dumps({"spec": "chara_card_v2", "data": {
        "name": "安和昴", "description": "人格", "mes_example": "示例",
        "extensions": {"sumika": {"language_policy": "默认简体中文，不出现日文假名。语气词只写罗马音。",
                                  "name_map": {"桃香さん": "桃香"}}},
        "character_book": {"entries": [{"keys": ["鼓"], "content": "鼓组设定"}]}}},
        ensure_ascii=False), encoding="utf8")
    return import_card(card, root / "store", "test-role")


def _settings(root, **overrides):
    value = example(_role_dir(root), root / "sumika.db")
    value.update(overrides)
    validate(value)
    return value


class CloudProviderTests(unittest.TestCase):
    def test_cloud_requires_https_and_key_from_environment(self):
        with self.assertRaises(ValueError):
            CloudProvider("http://api.example.com", key_env="X_KEY")
        with self.assertRaises(ValueError):
            CloudProvider("https://user:pass@api.example.com", key_env="X_KEY")
        provider = CloudProvider("https://api.example.com", key_env="SUMIKA_TEST_MISSING_KEY")
        with self.assertRaises(CloudError) as caught:
            provider.generate(model="m", messages=[{"role": "user", "content": "x"}])
        self.assertEqual(caught.exception.kind, "missing_key")

    def test_provider_failure_is_classified_without_fallback(self):
        provider = CloudProvider("https://api.example.com", key_env="SUMIKA_TEST_KEY")
        import urllib.error
        with patch.dict("os.environ", {"SUMIKA_TEST_KEY": "unit-test-placeholder"}):
            for code, kind in ((401, "auth"), (429, "rate_limit"), (503, "http_error")):
                error = urllib.error.HTTPError("https://api.example.com", code, "boom", {}, None)
                with patch("urllib.request.urlopen", side_effect=error):
                    with self.assertRaises(CloudError) as caught:
                        provider.generate(model="m", messages=[{"role": "user", "content": "x"}])
                self.assertEqual(caught.exception.kind, kind)

    def test_image_parts_validate_type_size_and_merge_into_last_user_message(self):
        from extensions.models.cloud import image_parts
        png = {"media_type": "image/png", "data_base64": "AAAA"}
        self.assertEqual(image_parts([png])[0]["image_url"]["url"], "data:image/png;base64,AAAA")
        self.assertEqual(image_parts(None), [])
        for bad in ([{"media_type": "image/tiff", "data_base64": "AA"}],
                    [{"media_type": "image/png"}],
                    [{"media_type": "image/png", "data_base64": "A" * 100}],
                    "not-a-list",
                    []):
            with self.assertRaises(ValueError):
                image_parts(bad, max_bytes=16)

    def test_generate_merges_images_into_final_user_message(self):
        provider = CloudProvider("https://api.example.com", key_env="SUMIKA_TEST_KEY")
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"},
                                                "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 1}}).encode()
        def fake_urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data.decode("utf8"))
            return Response()
        with patch.dict("os.environ", {"SUMIKA_TEST_KEY": "unit-test-placeholder"}), \
                patch("urllib.request.urlopen", side_effect=fake_urlopen):
            provider.generate(model="m", messages=[{"role": "user", "content": "看图"}],
                              images=[{"media_type": "image/png", "data_base64": "AAAA"}])
        content = captured["body"]["messages"][-1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "看图"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,AAAA")


class SettingsTests(unittest.TestCase):
    def test_settings_reject_secrets_plain_http_and_unknown_provider(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            value = _settings(root)
            with self.assertRaisesRegex(ValueError, "credential"):
                validate({**value, "model": "sk-abcdef1234567890"})
            with self.assertRaisesRegex(ValueError, "credential"):
                validate({**value, "api_key": "whatever"})
            with self.assertRaisesRegex(ValueError, "https"):
                validate({**value, "endpoint": "http://api.example.com"})
            with self.assertRaisesRegex(ValueError, "unsupported provider"):
                validate({**value, "provider": "some-other-vendor"})
            with self.assertRaisesRegex(ValueError, "must not hold a credential"):
                validate({**value, "language": {**value["language"], "key": "x"}})

    def test_multimodal_defaults_and_limits(self):
        with tempfile.TemporaryDirectory() as d:
            value = _settings(Path(d))
            value.pop("multimodal")
            self.assertFalse(validate(value)["multimodal"]["enabled"])
            self.assertEqual(validate(value)["multimodal"]["max_images"], 4)
            for bad in ({"enabled": "yes"}, {"enabled": True, "max_images": 0},
                        {"enabled": True, "max_images": 100}, {"enabled": True, "max_image_bytes": 10},
                        "not-a-section"):
                with self.assertRaises(ValueError):
                    validate({**value, "multimodal": bad})

    def test_voice_defaults_allow_output_only_and_validate_optional_device(self):
        with tempfile.TemporaryDirectory() as d:
            value = _settings(Path(d))
            value.pop("voice")
            default = validate(value)["voice"]
            self.assertFalse(default["enabled"], "voice starts disabled")
            self.assertIsNone(default["input_device"])
            self.assertEqual(default["sample_rate"], 16000)
            validate({**value, "voice": {**default, "enabled": True, "input_device": 35}})
            # Output-only voice is valid; recording enforces device/permission at execution.
            validate({**value, "voice": {**default, "enabled": True}})
            for bad in ({"enabled": "yes"}, {"enabled": False, "input_device": -1},
                        {"enabled": False, "sample_rate": 100},
                        {"enabled": False, "tts_voice": "  "},
                        {"enabled": False, "asr_model": ""}, "not-a-section"):
                with self.assertRaises(ValueError):
                    validate({**value, "voice": {**default, **bad}
                              if isinstance(bad, dict) else bad})

    def test_roundtrip_is_atomic_and_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / "settings.json"
            value = _settings(root)
            self.assertFalse(value["enabled"])
            save(value, target)
            self.assertEqual(load(target), value)
            self.assertFalse((root / "settings.json.tmp").exists())


class RoleChatTests(unittest.TestCase):
    def test_intent_uses_one_generation_and_never_enters_role_history(self):
        import re
        with tempfile.TemporaryDirectory() as d:
            chat = RoleChat(_settings(Path(d), enabled=True))
            original = '帮我修复 Sumika 登录失败的问题'
            def generate(provider, messages, max_tokens, images):
                self.assertEqual(messages[-1]['content'], original)
                marker = re.search(r'\[sumika-intent-[0-9a-f]+\]', messages[0]['content'])[0]
                return {'text': '我会把你的要求交给工作台。\n' + marker + json.dumps({
                    'kind': 'task', 'confidence': 'high', 'evidence': original})}
            with patch.object(chat, '_generate', side_effect=generate) as call:
                result = chat.reply(original, task_intent=True)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(result['task_intent']['kind'], 'task')
            self.assertNotIn('sumika-intent', result['text'])
            self.assertNotIn('sumika-intent', json.dumps(chat.histories))
            self.assertEqual(result['role_tools'], 0)

    def test_intent_invalid_or_missing_fails_closed_without_repair(self):
        from extensions.roles.task_intent import parse
        marker = '[sumika-intent-test]'
        for payload in ('', marker + '{', marker + '[]', marker + json.dumps({
            'kind': 'task', 'confidence': 'high', 'evidence': '不是用户说的'}),
            marker + json.dumps({'kind': 'task', 'confidence': 'high', 'evidence': ''})):
            with self.subTest(payload=payload):
                text, intent = parse('自然回复\n' + payload, marker, '你好')
                self.assertEqual(intent['kind'], 'unknown')
                self.assertNotIn(marker, text)

    def test_disabled_chat_makes_no_request(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            chat = RoleChat(_settings(root))
            with patch("extensions.roles.chat.CloudProvider") as provider:
                self.assertEqual(chat.reply("你好"), {"disabled": True, "model_started": False})
                provider.assert_not_called()

    def test_reply_localizes_names_and_records_usage(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            database = root / "sumika.db"
            chat = RoleChat(_settings(root, enabled=True))
            fake = {"text": "桃香さん说过这句话。", "provider": "openai-compatible",
                    "model": "deepseek-flash", "finish_reason": "stop", "usage_status": "reported",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
            with patch("extensions.roles.chat.CloudProvider") as provider, \
                    patch.dict("os.environ", {"DEEPSEEK_API_KEY": "unit-test-placeholder"}):
                provider.return_value.generate.return_value = fake
                result = chat.reply("今天排练怎么样？")
            self.assertEqual(result["text"], "桃香说过这句话。")
            self.assertEqual(result["name_mappings_applied"], ["桃香さん"])
            self.assertEqual(result["usage_status"], "reported")
            self.assertEqual(result["role_tools"], 0)
            self.assertEqual(result["language_policy_source"], "card")
            connection = sqlite3.connect(database)
            rows = connection.execute("SELECT provider,model,status,total_tokens FROM usage").fetchall()
            connection.close()
            self.assertEqual(rows, [("openai-compatible", "deepseek-flash", "reported", 15)])

    def test_provider_error_is_raised_and_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            chat = RoleChat(_settings(root, enabled=True))
            with patch("extensions.roles.chat.CloudProvider") as provider, \
                    patch("extensions.roles.chat.OllamaProvider") as local, \
                    patch.dict("os.environ", {"DEEPSEEK_API_KEY": "unit-test-placeholder"}):
                provider.return_value.generate.side_effect = CloudError("auth", "provider returned HTTP 401")
                with self.assertRaises(CloudError) as caught:
                    chat.reply("你好")
                local.assert_not_called()
            self.assertEqual(caught.exception.kind, "auth")

    def test_messages_keep_user_text_last_and_policy_before_reference(self):
        selected = {"role_context": {"name": "安和昴", "language_policy": "默认简体中文。",
                                     "identity": "人格", "recent": [{"role": "user", "content": "上一轮"}]},
                    "original_user_content": "新消息"}
        messages = build_messages(selected)
        self.assertEqual(messages[-1], {"role": "user", "content": "新消息"})
        system = messages[0]["content"]
        self.assertLess(system.index("默认简体中文"), system.index("角色参考资料"))
        self.assertIn("没有文件、终端、浏览器", system)
        self.assertEqual(messages[1], {"role": "user", "content": "上一轮"})

    def test_usage_counts_stay_unknown_without_provider_numbers(self):
        self.assertEqual(usage_counts({"usage": {}}), {})
        self.assertEqual(usage_counts({"usage": {"prompt_eval_count": 4, "eval_count": 6}}),
                         {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10})
        self.assertEqual(usage_counts({"usage": {"total_tokens": None}}), {})

    def test_images_require_the_switch_and_cloud_provider(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            image = [{"media_type": "image/png", "data_base64": "AAAA"}]
            disabled = RoleChat(_settings(root, enabled=True))
            with patch("extensions.roles.chat.CloudProvider") as provider:
                with self.assertRaisesRegex(ValueError, "multimodal disabled"):
                    disabled.reply("看图", images=image)
                provider.assert_not_called()
            enabled = _settings(root, enabled=True)
            enabled["multimodal"] = {"enabled": True, "max_images": 1, "max_image_bytes": 100000}
            chat = RoleChat(enabled)
            with self.assertRaisesRegex(ValueError, "too many images"):
                chat.reply("看图", images=image * 2)
            local = _settings(root, enabled=True)
            local["multimodal"] = {"enabled": True, "max_images": 4, "max_image_bytes": 100000}
            local["provider"], local["endpoint"] = "ollama", "http://127.0.0.1:11434"
            with self.assertRaisesRegex(ValueError, "does not accept images"):
                RoleChat(local).reply("看图", images=image)

    def test_image_request_passes_through_and_raises_output_floor(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            settings = _settings(root, enabled=True, max_tokens=256)
            settings["multimodal"] = {"enabled": True, "max_images": 2, "max_image_bytes": 100000}
            chat = RoleChat(settings)
            image = [{"media_type": "image/png", "data_base64": "AAAA"}]
            fake = {"text": "粉色。", "provider": "openai-compatible", "model": "deepseek-flash",
                    "finish_reason": "stop", "usage_status": "reported",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}
            with patch("extensions.roles.chat.CloudProvider") as provider, \
                    patch.dict("os.environ", {"DEEPSEEK_API_KEY": "unit-test-placeholder"}):
                provider.return_value.generate.return_value = fake
                result = chat.reply("这张图什么颜色？", images=image)
            call = provider.return_value.generate.call_args
            self.assertEqual(call.kwargs["images"], image)
            self.assertEqual(call.kwargs["max_tokens"], 2048)
            self.assertEqual(result["images_used"], 1)
            self.assertEqual(result["max_tokens_used"], 2048)


if __name__ == "__main__":
    unittest.main()
