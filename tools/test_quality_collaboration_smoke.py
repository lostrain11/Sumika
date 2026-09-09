import unittest

from tools.quality_collaboration_smoke import exact_result


class CollaborationOracleTests(unittest.TestCase):
    def test_verifies_changed_goal_and_preserves_no_execution_boundary(self):
        self.assertTrue(exact_result('{"total":9,"executed":false}', 9))
        self.assertFalse(exact_result('{"total":9,"executed":false}', 10))
        self.assertTrue(exact_result('{"total":10,"executed":false}', 10))

    def test_rejects_wrong_types_extra_claims_and_non_json(self):
        for text in ('{"total":9,"executed":0}', '{"total":"9","executed":false}',
                     '{"total":9,"executed":true}', '{"total":9,"executed":false,"extra":"claim"}',
                     'done: {"total":9,"executed":false}', '[]', 'null', '{broken'):
            self.assertFalse(exact_result(text, 9), text)
