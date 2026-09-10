"""Zero-cost, offline test offers; never evidence of real DSH budget control."""

from contextlib import ExitStack, contextmanager
from unittest.mock import patch


@contextmanager
def offline_network():
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.getaddrinfo"):
            stack.enter_context(patch(target, side_effect=AssertionError("offline fixture cannot use the network")))
        yield


@contextmanager
def offline_execution_quote(application, method):
    """Keep the fixture quote stable through deferred event-boundary dispatch."""
    quote = {
        "candidate_id": "offline-test-fixture:agent",
        "identity": ["offline-test-fixture", "v1"],
        "high_cny": "0",
        "limit_enforced": True,
        "free": True,
        "funding": "offline-test-fixture",
        "reason": "Offline fixture with no billable transport; not a real Harness price or spending guarantee",
    }
    original_offer = application.legacy_work.offer

    def route_offer(entry, request):
        offer = original_offer(entry, request)
        return {
            **offer,
            **{key: quote[key] for key in ("high_cny", "limit_enforced", "free", "funding", "reason")},
            "identity": ["offline-test-fixture", offer["identity"]],
        }

    with ExitStack() as stack:
        stack.enter_context(offline_network())
        if method.startswith("agent."):
            stack.enter_context(patch.object(application.agent, "execution_quote", return_value=quote))
        else:
            stack.enter_context(patch.object(application.legacy_work, "offer", side_effect=route_offer))
        yield


def confirm_and_resume_rpc(test, application, method, params):
    """Verify zero dispatch before confirmation and resume through the original RPC."""
    with ExitStack() as observers:
        effects = [
            (application.agent, "prompt"),
            (application.agent, "retry_prompt"),
            (application.agent, "update_queue"),
            (application.workspace, "create_checkpoint"),
            (application.route_supervisor, "dispatch"),
            (application.route_supervisor, "start_consultation"),
            (application.route_supervisor, "arm_turn"),
            (application.routes, "start_consultation"),
        ]
        spies = [observers.enter_context(patch.object(owner, name, wraps=getattr(owner, name)))
                 for owner, name in effects]
        pending = application.rpc(method, params)
        test.assertEqual(pending["status"], "awaiting-confirmation")
        test.assertFalse(pending["accepted"])
        work = pending["work_request"]
        test.assertIsNone(work["authorization"])
        test.assertEqual(work["attempts"], {})
        test.assertEqual(work["quote"]["high_cny"], "0")
        test.assertEqual(work["funding"]["funding_kind"], "offline-test-fixture")
        for spy in spies:
            spy.assert_not_called()
        confirmed = application.rpc("work.authorization.confirm", {
            "request_id": pending["work_request_id"],
            "assistant_id": work["assistant_id"],
            "revision": work["revision"],
            "max_cny": "0",
        })
        test.assertEqual(confirmed["status"], "ready")
        test.assertEqual(confirmed["attempts"], {})
        for spy in spies:
            spy.assert_not_called()
    return application.rpc(method, params)


def confirmed_offline_rpc(test, application, method, params):
    """Quote only mocked/local fixtures, confirm their version, resume the same RPC."""
    with offline_execution_quote(application, method):
        return confirm_and_resume_rpc(test, application, method, params)
