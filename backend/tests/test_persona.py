import unittest

from sumika_core.persona import build_persona_context, normalize_persona


class PersonaTests(unittest.TestCase):
    def test_legacy_empty_persona_receives_defaults_without_context(self):
        persona = normalize_persona({"greeting": ""})

        self.assertEqual(persona["identity"], "")
        self.assertEqual(persona["response_length"], "balanced")
        self.assertIsNone(build_persona_context("Saki", "zh-CN", persona))

    def test_context_uses_stable_field_order(self):
        context = build_persona_context(
            "Saki",
            "zh-CN",
            {
                "identity": "学习搭档",
                "traits": "耐心",
                "relationship": "长期伙伴",
                "speaking_style": "自然口语",
                "behavior": "先澄清目标",
                "boundaries": "不编造事实",
                "response_length": "detailed",
                "system_prompt": "优先给出可执行建议",
                "greeting": "欢迎回来",
            },
        )

        self.assertIsNotNone(context)
        labels = [
            "回复语言",
            "角色身份/定位",
            "核心特质",
            "与用户关系",
            "说话风格",
            "行为习惯",
            "边界/禁忌",
            "回答长度",
            "自定义系统提示词",
        ]
        positions = [context.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("欢迎回来", context)

    def test_invalid_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "persona.traits"):
            normalize_persona({"traits": ["耐心"]})
        with self.assertRaisesRegex(ValueError, "persona.response_length"):
            normalize_persona({"response_length": "very-long"})
        with self.assertRaisesRegex(ValueError, "persona.identity"):
            normalize_persona({"identity": "x" * 4_001})


if __name__ == "__main__":
    unittest.main()
