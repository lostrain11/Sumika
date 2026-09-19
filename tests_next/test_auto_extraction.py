import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.memory.rules_proposer import propose
from extensions.roles.chat import RoleChat
from extensions.roles.roles import import_card
from extensions.models.settings import example, validate


def _role(root):
    existing = Path(root) / "store" / "auto-role"
    if (existing / "role.json").is_file():
        return existing
    card = root / "card.json"
    card.write_text(json.dumps({"spec": "chara_card_v2", "data": {
        "name": "角色", "description": "人格", "mes_example": "示例",
        "character_book": {"entries": []}}}, ensure_ascii=False), encoding="utf8")
    return import_card(card, root / "store", "auto-role")


def _settings(root, **overrides):
    value = example(_role(root), root / "sumika.db")
    value["enabled"] = True
    value.update(overrides)
    validate(value)
    return value


class RulesProposerTests(unittest.TestCase):
    def test_plain_self_statements_become_scoped_proposals(self):
        proposals = propose("我喜欢晚上九点看动画。", message_id="m1")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["text"], "用户喜欢晚上九点看动画。")
        self.assertTrue(proposals[0]["fact_key"].startswith("user.like."))
        self.assertEqual(proposals[0]["message_ids"], ["m1"])
        self.assertEqual(propose("我叫小林。", message_id="m1")[0]["text"], "用户的名字是小林。")
        self.assertEqual(propose("我搬到成都了", message_id="m1")[0]["fact_key"], "user.location")

    def test_questions_and_negations_are_not_proposed(self):
        self.assertEqual(propose("我喜欢看动画吗？", message_id="m1"), [])
        self.assertEqual(propose("我不喜欢喝乌龙茶。", message_id="m1"), [])
        self.assertEqual(propose("我并没有住在成都。", message_id="m1"), [])
        self.assertEqual(propose("", message_id="m1"), [])

    def test_message_id_is_required(self):
        with self.assertRaises(ValueError):
            propose("我喜欢动画", message_id="  ")

    def test_quoted_hypothetical_and_ambiguous_statements_are_skipped(self):
        for text in ('他说我喜欢动画', '如果我住在成都', '我喜欢动画，才怪。',
                     '我叫小林是假设', '“我喜欢茶”', '我改用新电脑了'):
            with self.subTest(text=text):
                self.assertEqual(propose(text, message_id='m1'), [])

    def test_unrelated_likes_have_distinct_stable_keys(self):
        tea=propose('我喜欢茶',message_id='m1')[0]['fact_key']
        anime=propose('我喜欢动画',message_id='m2')[0]['fact_key']
        self.assertNotEqual(tea,anime)
        self.assertEqual(tea,propose('我喜欢茶。',message_id='m3')[0]['fact_key'])


class AutoExtractionWiringTests(unittest.TestCase):
    def _reply(self, settings, message, **kwargs):
        chat = RoleChat(settings)
        fake = {"text": "好的。", "provider": "openai-compatible", "model": settings["model"],
                "finish_reason": "stop", "usage_status": "reported",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        with patch("extensions.roles.chat.CloudProvider") as provider, \
                patch.dict("os.environ", {"DEEPSEEK_API_KEY": "unit-test-placeholder"}):
            provider.return_value.generate.return_value = fake
            return chat.reply(message, **kwargs)

    def test_persistent_message_identity_survives_chat_recreation(self):
        with tempfile.TemporaryDirectory(dir='.sumika-next') as d:
            root=Path(d);settings=_settings(root)
            settings['memory']['auto_extract']=True
            self._reply(settings,'我搬到成都了',source_message_id='turn-123:user')
            self._reply(settings,'我搬到成都了',source_message_id='turn-123:user')
            db=sqlite3.connect(root/'sumika.db')
            try:
                rows=db.execute('SELECT event_id FROM memories').fetchall()
            finally:db.close()
            self.assertEqual(rows,[('turn-123:user:0',)])

    def test_disabled_by_default_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            settings = _settings(root)
            self.assertFalse(settings["memory"]["auto_extract"])
            result = self._reply(settings, "我喜欢晚上九点看动画。")
            self.assertEqual(result["auto_extracted"], [])
            connection = sqlite3.connect(root / "sumika.db")
            rows = connection.execute("SELECT count(*) FROM memories").fetchone()[0]
            connection.close()
            self.assertEqual(rows, 0)

    def test_enabled_writes_a_gated_fact_with_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            settings = _settings(root)
            settings["memory"] = {"auto_extract": True, "extract_threshold": 0.8,
                                  "max_extracts_per_turn": 3}
            result = self._reply(settings, "我搬到成都了")
            self.assertEqual(len(result["auto_extracted"]), 1)
            self.assertEqual(result["auto_extracted"][0]["fact_key"], "user.location")
            connection = sqlite3.connect(root / "sumika.db")
            rows = connection.execute("SELECT text, source FROM memories").fetchall()
            connection.close()
            self.assertEqual(rows, [("用户住在成都。", "auto-extract")])

    def test_same_fact_twice_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            settings = _settings(root)
            settings["memory"] = {"auto_extract": True, "extract_threshold": 0.8,
                                  "max_extracts_per_turn": 3}
            self._reply(settings, "我喜欢晚上九点看动画。")
            second = self._reply(settings, "我喜欢晚上九点看动画。")
            self.assertEqual(second["auto_extracted"], [], "duplicate fact is filtered by the gate")
            connection = sqlite3.connect(root / "sumika.db")
            rows = connection.execute("SELECT count(*) FROM memories").fetchone()[0]
            connection.close()
            self.assertEqual(rows, 1)

    def test_configuration_validation(self):
        with tempfile.TemporaryDirectory() as d:
            value = _settings(Path(d))
            value.pop("memory")
            default = validate(value)["memory"]
            self.assertFalse(default["auto_extract"])
            for bad in ({"auto_extract": "yes"}, {"auto_extract": False, "extract_threshold": 2},
                        {"auto_extract": False, "max_extracts_per_turn": 0},
                        {"auto_extract": False, "max_extracts_per_turn": 99}, "not-a-section"):
                with self.assertRaises(ValueError):
                    validate({**value, "memory": {**default, **bad}
                              if isinstance(bad, dict) else bad})


if __name__ == "__main__":
    unittest.main()
