import unittest
from copy import deepcopy

from quality_routing import RoutingError
from quality_routing.workflow import ExternalQuote, WorkRequest, authorize, check_delegation, delegation_digest


class DelegationContractTests(unittest.TestCase):
    def setUp(self):
        parent = WorkRequest("parent", "assistant", "session", "prepare report")
        child = WorkRequest("child", "assistant", "session", "verify report")
        steps = [{"id": "verify", "method": "agent.session.prompt", "payload_digest": "payload", "binding_digest": "binding"}]
        authorization = authorize(parent, ExternalQuote(2, 2, 2), candidate_ids=("route",), max_cny=2)
        authorization["delegation_digest"] = delegation_digest(steps)
        self.parent = {"request": parent.to_dict(), "status": "executing", "external_steps": steps, "authorization": authorization}
        self.child = {"request": child.to_dict(), "candidate_id": "route", "quote": {"high_cny": "2"}, "funding": {"free": False},
                      "external": {"method": "agent.session.prompt", "payload_digest": "payload", "binding_digest": "binding"},
                      "parent_authorization": {"request_id": "parent", "revision": 1, "step_id": "verify"}}

    def test_independent_contract_checks_scope_and_shared_remaining_budget(self):
        check_delegation(self.parent, self.child)
        before = deepcopy(self.parent)
        self.parent["authorization"]["reserved_cny"] = "1"
        with self.assertRaises(RoutingError):
            check_delegation(self.parent, self.child)
        self.assertEqual(self.parent["authorization"]["reserved_cny"], "1")
        self.assertEqual(before["authorization"]["spent_cny"], "0")

    def test_digest_covers_purpose_and_candidate_binding(self):
        self.parent["external_steps"][0]["purpose"] = "different purpose"
        with self.assertRaises(RoutingError):
            check_delegation(self.parent, self.child)

    def test_reference_and_boolean_approval_do_not_authorize_spending(self):
        self.parent["authorization"] = {"approved": True}
        with self.assertRaises(RoutingError):
            check_delegation(self.parent, self.child)


if __name__ == "__main__":
    unittest.main()
