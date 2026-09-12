import unittest
from dataclasses import replace

from sumika_next.authorization import Approval, Authority, AuthorizationError
from sumika_next.contracts import HarnessInstance, ToolRequest, Trust, WorkBinding


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.authority = Authority(HarnessInstance("dsh", "instance-1", Trust.MANAGED))
        self.binding = WorkBinding("instance-1", "request-1", 1, "session-1", "step-1")
        self.authority.bind(self.binding)
        self.request = ToolRequest(self.binding, "file.write", "project/file.txt")

    def test_exact_approval_is_single_use(self):
        approval = self.authority.approve(self.request)
        self.authority.consume(self.request, approval)
        with self.assertRaises(AuthorizationError):
            self.authority.consume(self.request, approval)

    def test_forgery_is_rejected(self):
        with self.assertRaises(AuthorizationError):
            self.authority.consume(self.request, Approval("fake", "fake"))

    def test_target_change_is_rejected(self):
        approval = self.authority.approve(self.request)
        with self.assertRaises(AuthorizationError):
            self.authority.consume(replace(self.request, target="other.txt"), approval)

    def test_revoked_binding_is_rejected(self):
        approval = self.authority.approve(self.request)
        self.authority.revoke(self.binding)
        with self.assertRaises(AuthorizationError):
            self.authority.consume(self.request, approval)

    def test_unverified_instance_cannot_bind(self):
        authority = Authority(HarnessInstance("external", "instance-1", Trust.UNVERIFIED))
        with self.assertRaises(AuthorizationError):
            authority.bind(self.binding)


if __name__ == "__main__":
    unittest.main()
