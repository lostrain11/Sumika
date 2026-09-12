from dataclasses import replace
from pathlib import Path
import unittest

from sumika_next.authorization import Authority, AuthorizationError
from sumika_next.contracts import HarnessInstance, Trust, ToolRequest, WorkBinding, TaskState
from sumika_next.execution import Execution

try:
    from tests_next.scratch import ScratchDirectory
except ImportError:  # ``unittest discover -s tests_next`` imports modules top-level
    from scratch import ScratchDirectory


class MemoryHarness:
    def __init__(self):
        self.instance = HarnessInstance("other-harness", "owned", Trust.MANAGED)
        self.calls = []
        self.fail = False

    def execute(self, request):
        self.calls.append(request)
        if self.fail:
            raise TimeoutError("response lost after possible write")
        return {"written": True}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = ScratchDirectory()
        self.path = Path(self.tmp.name) / "steps.sqlite3"
        self.harness = MemoryHarness()
        self.authority = Authority(self.harness.instance)
        self.executor = Execution(self.harness, self.authority, self.path)
        self.binding = WorkBinding("owned", "request", 1, "session", "step")
        self.authority.bind(self.binding)
        self.request = ToolRequest(self.binding, "file.write", "file", b"content")

    def tearDown(self):
        self.executor.close()
        self.tmp.cleanup()

    def test_second_harness_uses_same_execution(self):
        result = self.executor.dispatch(self.request, self.authority.approve(self.request))
        self.assertEqual(result, {"written": True})
        self.assertEqual(self.executor.inspect(self.binding).state, TaskState.COMPLETED)
        self.assertEqual(self.harness.calls, [self.request])
        events = self.executor.events(self.binding)
        self.assertEqual([e.state for e in events], [TaskState.UNKNOWN, TaskState.COMPLETED])
        self.assertEqual(self.executor.events(self.binding, events[-1].sequence), ())

    def test_no_execution_for_tampered_content(self):
        approval = self.authority.approve(self.request)
        with self.assertRaises(AuthorizationError):
            self.executor.dispatch(replace(self.request, arguments=b"unapproved"), approval)
        self.assertEqual(self.harness.calls, [])

    def test_unknown_survives_restart_and_blocks_new_version(self):
        self.harness.fail = True
        with self.assertRaises(TimeoutError):
            self.executor.dispatch(self.request, self.authority.approve(self.request))
        self.executor.close()
        authority = Authority(self.harness.instance)
        self.executor = Execution(self.harness, authority, self.path)
        self.assertFalse(self.executor.inspect(self.binding).can_replay)
        for binding in (self.binding, replace(self.binding, request_version=2, step_id="retry")):
            authority.bind(binding)
            request = replace(self.request, binding=binding)
            with self.assertRaises(AuthorizationError):
                self.executor.dispatch(request, authority.approve(request))
        self.assertEqual(len(self.harness.calls), 1)

    def test_new_process_instance_does_not_erase_unknown_request(self):
        self.harness.fail = True
        with self.assertRaises(TimeoutError):
            self.executor.dispatch(self.request, self.authority.approve(self.request))
        self.executor.close()
        self.harness.instance = replace(self.harness.instance, instance_id="new-process")
        authority = Authority(self.harness.instance)
        self.executor = Execution(self.harness, authority, self.path)
        binding = replace(self.binding, instance_id="new-process")
        authority.bind(binding)
        request = replace(self.request, binding=binding)
        with self.assertRaises(AuthorizationError):
            self.executor.dispatch(request, authority.approve(request))

    def test_unknown_does_not_prevent_explicit_cancel(self):
        self.harness.fail = True
        with self.assertRaises(TimeoutError):
            self.executor.dispatch(self.request, self.authority.approve(self.request))
        self.harness.fail = False
        binding = replace(self.binding, step_id="cancel")
        self.authority.bind(binding)
        request = ToolRequest(binding, "session.cancel", "session")
        self.executor.dispatch(request, self.authority.approve(request))
        self.assertEqual(self.executor.inspect(self.binding).state, TaskState.UNKNOWN)
