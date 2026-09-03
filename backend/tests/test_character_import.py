import base64
import io
import json
import struct
import unittest
import zipfile

from sumika_core.character_import import (
    CharacterCardError,
    convert_character_card,
    parse_card_bytes,
    parse_card_text,
)
from sumika_core.persona import PERSONA_TEXT_LIMITS


def v2_card(**overrides):
    data = {
        "name": "合成酱",
        "description": "合成角色：用于导入测试的合成人物。",
        "personality": "外冷内热，说话简短。",
        "scenario": "{{user}}是{{char}}的测试伙伴。",
        "first_mes": "（测试开场）{{char}}向你挥了挥手。",
        "mes_example": "<START>\n{{user}}: 你好吗？\n{{char}}: 还行吧。<USER>: 真的？<BOT>: 嗯。",
        "system_prompt": "你是合成酱，保持简短回复。",
        "character_book": {
            "entries": [
                {"keys": ["测试"], "content": "这是测试世界书条目。"},
                {"keys": ["条目"], "content": "第二个条目。"},
            ]
        },
    }
    data.update(overrides)
    return {"spec": "chara_card_v2", "spec_version": "2.0", "data": data}


def png_bytes(card, keyword=b"chara"):
    payload = base64.b64encode(json.dumps(card, ensure_ascii=False).encode("utf-8"))

    def chunk(chunk_type, data):
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", 0)
        )

    text = keyword + b"\x00" + payload
    return b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", text) + chunk(b"IEND", b"")


def ztxt_bytes(keyword):
    def chunk(chunk_type, data):
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", 0)

    compressed = keyword + b"\x00\x00" + b"compressed-payload"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"zTXt", compressed) + chunk(b"IEND", b"")


def charx_bytes(card, include_card=True):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if include_card:
            archive.writestr("card.json", json.dumps(card, ensure_ascii=False))
        archive.writestr("assets/avatar.png", b"png-bytes")
    return buffer.getvalue()


class CharacterImportTests(unittest.TestCase):
    def test_v2_card_maps_onto_persona_fields(self):
        result = convert_character_card(v2_card())
        persona = result["config"]["persona"]
        self.assertEqual(result["name"], "合成酱")
        self.assertEqual(persona["identity"], "合成角色：用于导入测试的合成人物。")
        self.assertEqual(persona["traits"], "外冷内热，说话简短。")
        self.assertEqual(persona["relationship"], "你是合成酱的测试伙伴。")
        self.assertEqual(persona["greeting"], "（测试开场）合成酱向你挥了挥手。")
        self.assertEqual(persona["response_length"], "balanced")
        self.assertIn("你是合成酱，保持简短回复。", persona["system_prompt"])
        self.assertIn("示例对话：", persona["system_prompt"])
        self.assertIn("合成酱: 还行吧。", persona["system_prompt"])
        self.assertEqual(result["book_entries"], 2)
        self.assertTrue(any("character_book" in warning for warning in result["warnings"]))
        self.assertEqual(result["mapped"]["identity"], len(persona["identity"]))

    def test_card_import_preserves_the_original_card(self):
        card = v2_card()
        result = convert_character_card(card, imported_at="2026-09-03T00:00:00Z")
        record = result["config"]["card_import"]
        self.assertEqual(record["spec"], "chara_card_v2")
        self.assertEqual(record["spec_version"], "2.0")
        self.assertEqual(record["imported_at"], "2026-09-03T00:00:00Z")
        self.assertEqual(record["card"], card["data"])
        self.assertEqual(
            record["warnings"],
            [warning for warning in result["warnings"]],
        )

    def test_v1_flat_card_is_accepted(self):
        card = {
            "name": "旧版卡",
            "description": "旧版描述。",
            "first_mes": "你好，{{user}}。",
        }
        result = convert_character_card(card)
        self.assertEqual(result["config"]["card_import"]["spec"], "v1")
        self.assertIsNone(result["config"]["card_import"]["spec_version"])
        self.assertEqual(result["config"]["persona"]["greeting"], "你好，你。")

    def test_v3_card_is_accepted(self):
        card = {"spec": "chara_card_v3", "spec_version": "3.0", "data": v2_card()["data"]}
        result = convert_character_card(card)
        self.assertEqual(result["config"]["card_import"]["spec"], "chara_card_v3")
        self.assertEqual(result["name"], "合成酱")

    def test_unsupported_spec_is_rejected(self):
        with self.assertRaisesRegex(CharacterCardError, "unsupported character card spec"):
            convert_character_card({"spec": "chara_card_v9", "data": {"name": "x"}})

    def test_v2_spec_version_mismatch_is_rejected(self):
        card = v2_card()
        card["spec_version"] = "3.0"
        with self.assertRaisesRegex(CharacterCardError, "spec_version 2.x"):
            convert_character_card(card)

    def test_v2_card_without_data_object_is_rejected(self):
        with self.assertRaisesRegex(CharacterCardError, "missing its data object"):
            convert_character_card({"spec": "chara_card_v2", "spec_version": "2.0"})

    def test_card_without_name_is_rejected(self):
        with self.assertRaisesRegex(CharacterCardError, "usable name"):
            convert_character_card({"spec": "chara_card_v2", "spec_version": "2.0", "data": {}})

    def test_oversized_field_fails_without_truncation(self):
        card = v2_card(description="长" * (PERSONA_TEXT_LIMITS["identity"] + 1))
        with self.assertRaisesRegex(CharacterCardError, "identity="):
            convert_character_card(card)

    def test_mes_example_overflow_keeps_system_prompt_and_warns(self):
        long_prompt = "提" * (PERSONA_TEXT_LIMITS["system_prompt"] - 10)
        card = v2_card(system_prompt=long_prompt)
        result = convert_character_card(card)
        self.assertEqual(result["config"]["persona"]["system_prompt"], long_prompt)
        self.assertTrue(any("mes_example" in warning for warning in result["warnings"]))
        preserved = result["config"]["card_import"]["card"]["mes_example"]
        self.assertTrue(preserved)

    def test_name_override_replaces_placeholders(self):
        result = convert_character_card(v2_card(), character_name="覆盖酱")
        self.assertEqual(result["name"], "覆盖酱")
        self.assertEqual(result["config"]["persona"]["relationship"], "你是覆盖酱的测试伙伴。")

    def test_parse_card_bytes_accepts_json(self):
        card = parse_card_bytes(json.dumps(v2_card(), ensure_ascii=False).encode("utf-8"))
        self.assertEqual(card["spec"], "chara_card_v2")

    def test_parse_card_text_rejects_invalid_json(self):
        with self.assertRaisesRegex(CharacterCardError, "not valid JSON"):
            parse_card_text("{not json")

    def test_parse_card_bytes_rejects_unknown_binary(self):
        with self.assertRaisesRegex(CharacterCardError, "neither PNG, CHARX"):
            parse_card_bytes(b"\x00\x01\x02\xff")

    def test_png_embedded_v2_card_is_parsed(self):
        card = parse_card_bytes(png_bytes(v2_card()))
        self.assertEqual(card["spec"], "chara_card_v2")

    def test_png_prefers_ccv3_over_chara(self):
        v3 = {"spec": "chara_card_v3", "spec_version": "3.0", "data": v2_card()["data"]}

        def chunk(chunk_type, data):
            return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", 0)

        chara_text = b"chara\x00" + base64.b64encode(json.dumps(v2_card(), ensure_ascii=False).encode("utf-8"))
        ccv3_text = b"ccv3\x00" + base64.b64encode(json.dumps(v3, ensure_ascii=False).encode("utf-8"))
        combined = b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", chara_text) + chunk(b"tEXt", ccv3_text) + chunk(b"IEND", b"")
        card = parse_card_bytes(combined)
        self.assertEqual(card["spec"], "chara_card_v3")

    def test_png_ztxt_card_is_rejected(self):
        with self.assertRaisesRegex(CharacterCardError, "zTXt"):
            parse_card_bytes(ztxt_bytes(b"chara"))

    def test_png_without_card_is_rejected(self):
        with self.assertRaisesRegex(CharacterCardError, "missing tEXt chunk"):
            parse_card_bytes(png_bytes({"unrelated": True}, keyword=b"comment"))

    def test_charx_archive_is_parsed(self):
        card = parse_card_bytes(charx_bytes({"spec": "chara_card_v3", "spec_version": "3.0", "data": v2_card()["data"]}))
        self.assertEqual(card["spec"], "chara_card_v3")

    def test_charx_without_card_json_is_rejected(self):
        with self.assertRaisesRegex(CharacterCardError, "missing card.json"):
            parse_card_bytes(charx_bytes(v2_card(), include_card=False))


if __name__ == "__main__":
    unittest.main()
