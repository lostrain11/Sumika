import unittest

from extensions.memory.extraction_policy import ExtractionGate


class ExtractionGateTests(unittest.TestCase):
    def _proposal(self, **overrides):
        base = {"text": "用户喜欢晚上九点看动画。", "kind": "preference", "confidence": 0.9,
                "message_ids": ["m1"]}
        base.update(overrides)
        return base

    def test_confident_user_statement_is_accepted_with_provenance(self):
        gate = ExtractionGate()
        result = gate.review([self._proposal()], user_message_ids={"m1", "m2"})
        self.assertEqual(len(result["accepted"]), 1)
        accepted = result["accepted"][0]
        self.assertEqual(accepted["source"], "auto-extract")
        self.assertEqual(accepted["message_ids"], ["m1"])
        self.assertEqual(result["rejected"], [])

    def test_threshold_boundary_is_inclusive_and_lower_confidence_is_rejected(self):
        gate = ExtractionGate(threshold=0.8)
        self.assertEqual(len(gate.review([self._proposal(confidence=0.8)],
                                         user_message_ids={"m1"})["accepted"]), 1)
        low = gate.review([self._proposal(confidence=0.79)], user_message_ids={"m1"})
        self.assertEqual(low["accepted"], [])
        self.assertEqual(low["rejected"][0]["reason"], "below_threshold")

    def test_role_opinions_are_never_stored_as_user_facts(self):
        gate = ExtractionGate()
        for proposal in (self._proposal(source="role_model"),
                         self._proposal(kind="opinion")):
            result = gate.review([proposal], user_message_ids={"m1"})
            self.assertEqual(result["accepted"], [])
            self.assertEqual(result["rejected"][0]["reason"], "role_opinion_is_not_a_user_fact")

    def test_nonfinite_boolean_and_out_of_range_confidence_is_rejected(self):
        for confidence in (True, False, float('nan'), float('inf'), -1, 1.01):
            with self.subTest(confidence=confidence):
                result=ExtractionGate().review([self._proposal(confidence=confidence)],
                                               user_message_ids={'m1'})
                self.assertEqual(result['accepted'],[])

    def test_credentials_and_overlong_text_are_rejected(self):
        gate = ExtractionGate(max_chars=40)
        secret = gate.review([self._proposal(text="我的 key 是 sk-abcdef1234567890")],
                             user_message_ids={"m1"})
        self.assertEqual(secret["rejected"][0]["reason"], "contains_credential")
        long_text = gate.review([self._proposal(text="用户" + "很" * 60)], user_message_ids={"m1"})
        self.assertEqual(long_text["rejected"][0]["reason"], "too_long")

    def test_fact_must_be_traceable_to_a_user_message(self):
        gate = ExtractionGate()
        result = gate.review([self._proposal(message_ids=["model-1"])],
                             user_message_ids={"m1"})
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["rejected"][0]["reason"], "not_traceable_to_user_message")
        missing = gate.review([self._proposal(message_ids=None)], user_message_ids={"m1"})
        self.assertEqual(missing["rejected"][0]["reason"], "not_traceable_to_user_message")

    def test_kind_allowlist_and_duplicate_detection(self):
        gate = ExtractionGate()
        event = gate.review([self._proposal(kind="event")], user_message_ids={"m1"})
        self.assertEqual(event["rejected"][0]["reason"], "kind_not_allowed")
        duplicate = gate.review([self._proposal(text=" 用户喜欢晚上九点看动画。 ")],
                                user_message_ids={"m1"},
                                existing_texts=["用户喜欢晚上九点看动画。"])
        self.assertEqual(duplicate["rejected"][0]["reason"], "duplicate")

    def test_per_turn_write_limit_keeps_the_extra_proposals_out(self):
        gate = ExtractionGate(max_writes_per_turn=2)
        proposals = [self._proposal(text=f"用户偏好编号{i}的饮料。", event_id=f"e{i}")
                     for i in range(3)]
        result = gate.review(proposals, user_message_ids={"m1"})
        self.assertEqual(len(result["accepted"]), 2)
        self.assertEqual([item["reason"] for item in result["rejected"]], ["turn_limit"])

    def test_same_fact_key_can_update_an_existing_value(self):
        gate = ExtractionGate()
        result = gate.review([self._proposal(text="用户改喝白水了。", fact_key="user.drink",
                                             message_ids=["m2"])],
                             user_message_ids={"m2"},
                             existing_texts=["用户喜欢喝乌龙茶。"])
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["fact_key"], "user.drink")

    def test_invalid_configuration_and_input(self):
        for kwargs in ({"threshold": 2}, {"max_writes_per_turn": 0}, {"max_chars": 0}):
            with self.assertRaises(ValueError):
                ExtractionGate(**kwargs)
        gate = ExtractionGate()
        with self.assertRaises(ValueError):
            gate.review("not-a-list", user_message_ids={"m1"})
        with self.assertRaises(ValueError):
            gate.review([{"text": "x"}], user_message_ids="m1")


if __name__ == "__main__":
    unittest.main()
