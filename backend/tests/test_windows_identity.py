import contextlib
import ctypes
import os
import queue
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from sumika_core.agent import windows_identity as identity


_SERVER = """
import http.server
server = http.server.HTTPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)
print(server.server_port, flush=True)
server.serve_forever()
"""

_WRAPPER = """
import subprocess, sys
child = subprocess.Popen([sys.executable, '-u', '-c', sys.argv[1]], stdout=subprocess.PIPE, text=True)
try:
    print(child.stdout.readline().strip(), flush=True)
    sys.stdin.readline()
finally:
    child.terminate()
    child.wait(timeout=10)
"""


@unittest.skipUnless(sys.platform == "win32", "Windows APIs required")
class WindowsIdentityTests(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, wrapper=False):
        command = [sys.executable, "-u", "-c", _WRAPPER, _SERVER] if wrapper else [sys.executable, "-u", "-c", _SERVER]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            startup = queue.Queue()
            reader = threading.Thread(target=lambda: startup.put(process.stdout.readline()), daemon=True)
            reader.start()
            endpoint = "http://127.0.0.1:" + startup.get(timeout=10).strip()
            yield process, endpoint
        finally:
            if process.poll() is None:
                if wrapper:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                else:
                    process.terminate()
                process.wait(timeout=15)
            process.stdin.close()
            process.stdout.close()

    def test_root_itself_and_receipt_after_exit(self):
        with self.server() as (process, endpoint):
            receipt = identity.observe_listener(process.pid, endpoint + "/")
            self.assertEqual(receipt["root_pid"], process.pid)
            self.assertEqual(receipt["listener_pid"], process.pid)
            self.assertEqual(receipt["root_created"], receipt["listener_created"])
            self.assertTrue(all(type(value) is int for value in receipt.values()))
            self.assertEqual(identity.verify_listener(receipt, endpoint), receipt)
        with self.assertRaises(OSError):
            identity.verify_listener(receipt, endpoint)

    def test_live_wrapper_and_wrong_root(self):
        with self.server(wrapper=True) as (wrapper, endpoint):
            receipt = identity.observe_listener(wrapper.pid, endpoint)
            self.assertNotEqual(receipt["listener_pid"], wrapper.pid)
            self.assertLessEqual(receipt["root_created"], receipt["listener_created"])
            with self.server() as (unrelated, _):
                with self.assertRaises(OSError):
                    identity.observe_listener(unrelated.pid, endpoint)
            self.assertEqual(identity.verify_listener(receipt, endpoint), receipt)

    def test_malformed_endpoints(self):
        endpoints = [None, "", "https://127.0.0.1:80", "http://localhost:80", "http://0.0.0.0:80", "http://127.0.0.1", "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1:80/path", "http://127.0.0.1:80?", "http://127.0.0.1:80#", "http://user@127.0.0.1:80", "http://127.0.0.1:80//", "http://127.0.0.1:80\n", "http://127.0.0.1:+80"]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                identity.observe_listener(os.getpid(), endpoint)

    def test_invalid_root_pids(self):
        for pid in (True, False, None, "1", 1.0, 0, -1, 2**32):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                identity.observe_listener(pid, "http://127.0.0.1:80")

    def test_strict_receipts_and_all_identity_fields(self):
        with self.server() as (process, endpoint):
            receipt = identity.observe_listener(process.pid, endpoint)
            for field in receipt:
                for value in (True, False, str(receipt[field]), float(receipt[field])):
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        identity.verify_listener({**receipt, field: value}, endpoint)
                changed = {**receipt, field: receipt[field] + 1}
                with patch.object(identity, "observe_listener", return_value=receipt), self.assertRaises(OSError):
                    identity.verify_listener(changed, endpoint)
            for invalid in ({}, {**receipt, "extra": 1}, None):
                with self.assertRaises(ValueError):
                    identity.verify_listener(invalid, endpoint)

    def test_tcp_table_rejects_wildcard_multiple_and_non_listen(self):
        api = identity._Windows()
        port = 23456
        encoded_port = int.from_bytes(port.to_bytes(2, "big"), "little")

        def table(rows):
            payload = len(rows).to_bytes(4, "little") + b"".join(bytes(identity._TcpRow(state, address, encoded_port, 0, 0, os.getpid())) for state, address in rows)

            def query(buffer, size, ordered, family, table_class, reserved):
                self.assertEqual((family, table_class), (2, 3))
                ctypes.cast(size, ctypes.POINTER(ctypes.wintypes.DWORD)).contents.value = len(payload)
                if buffer is None:
                    return 122
                ctypes.memmove(buffer, payload, len(payload))
                return 0

            return query

        for rows in ([], [(2, 0)], [(2, 0x0100007F)] * 2, [(2, 0), (2, 0x0100007F)], [(5, 0x0100007F)]):
            with self.subTest(rows=rows), patch.object(api.ip, "GetExtendedTcpTable", side_effect=table(rows)), self.assertRaises(OSError):
                api.listener(port)
        with patch.object(api.ip, "GetExtendedTcpTable", side_effect=table([(2, 0x0100007F)])):
            self.assertEqual(api.listener(port), os.getpid())

    def test_ancestry_and_identity_races_fail_closed(self):
        scenarios = (
            ("parent reused", [{20: 10, 10: 0}], [200, 100], [20]),
            ("cycle", [{20: 30, 30: 20, 10: 0}], [100, 200, 150], [20]),
            ("missing ancestor", [{20: 30, 10: 0}], [100, 200], [20]),
            ("changed parent", [{20: 10, 10: 0}, {20: 30, 10: 0}], [100, 200], [20]),
            ("changed listener", [{20: 10, 10: 0}] * 2, [100, 200], [20, 21]),
            ("root reused", [{20: 10, 10: 0}] * 2, [100, 200, 101], [20, 20]),
            ("listener reused", [{20: 10, 10: 0}] * 2, [100, 200, 100, 100, 201], [20, 20]),
            ("root exited", [{20: 10, 10: 0}] * 2, [100, 200, 100, 100, 200, 200, OSError("exited")], [20, 20]),
        )
        for name, parents, created, listeners in scenarios:
            api = Mock()
            api.open.side_effect = lambda pid: pid
            api.parents.side_effect = parents
            api.created.side_effect = created
            api.listener.side_effect = listeners
            with self.subTest(name=name), patch.object(identity, "_Windows", return_value=api), self.assertRaises(OSError):
                identity.observe_listener(10, "http://127.0.0.1:80")
            closed = [call.args[0] for call in api.close.call_args_list]
            opened = [call.args[0] for call in api.open.call_args_list]
            self.assertCountEqual(closed, opened)

    def test_ancestry_depth_is_bounded(self):
        api = Mock()
        api.open.side_effect = lambda pid: pid
        api.created.return_value = 100
        api.listener.return_value = 1000
        api.parents.return_value = {pid: pid - 1 for pid in range(1, 1001)}
        with patch.object(identity, "_Windows", return_value=api), self.assertRaisesRegex(OSError, "bound"):
            identity.observe_listener(1, "http://127.0.0.1:80")
        self.assertEqual(api.open.call_count, identity._MAX_DEPTH + 1)
        self.assertEqual(api.open.call_count, api.close.call_count)

    def test_tcp_table_growth_is_bounded_and_errors_propagate(self):
        api = identity._Windows()

        def growing(buffer, size, *arguments):
            ctypes.cast(size, ctypes.POINTER(ctypes.wintypes.DWORD)).contents.value = 1024
            return 122

        with patch.object(api.ip, "GetExtendedTcpTable", side_effect=growing) as query:
            with self.assertRaisesRegex(OSError, "bound"):
                api.listener(80)
            self.assertEqual(query.call_count, 4)
        with patch.object(api.ip, "GetExtendedTcpTable", return_value=5):
            with self.assertRaises(OSError):
                api.listener(80)

    def test_denied_process_access_fails_closed(self):
        api = identity._Windows()
        with patch.object(api.kernel, "OpenProcess", return_value=None):
            with self.assertRaises(OSError):
                api.open(os.getpid())

    def test_stop_listener_keeps_real_wrapper_alive(self):
        with self.server(wrapper=True) as (wrapper, endpoint):
            receipt = identity.observe_listener(wrapper.pid, endpoint)
            api = identity._Windows()
            listener = api.open(receipt["listener_pid"])
            try:
                self.assertIsNone(identity.stop_verified_listener(receipt, endpoint))
                self.assertEqual(api.kernel.WaitForSingleObject(listener, 0), 0)
                self.assertIsNone(wrapper.poll())
                with self.assertRaises(OSError):
                    identity.verify_listener(receipt, endpoint)
            finally:
                api.close(listener)

    def test_stop_root_listener_can_be_reaped(self):
        with self.server() as (process, endpoint):
            receipt = identity.observe_listener(process.pid, endpoint)
            identity.stop_verified_listener(receipt, endpoint)
            self.assertEqual(process.wait(timeout=5), 1)

    def test_stop_mismatched_receipts_never_modifies_processes(self):
        with self.server(wrapper=True) as (wrapper, endpoint), self.server() as (unrelated, unrelated_endpoint):
            receipt = identity.observe_listener(wrapper.pid, endpoint)
            unrelated_receipt = identity.observe_listener(unrelated.pid, unrelated_endpoint)
            api = identity._Windows()
            cases = [({**receipt, field: receipt[field] + 1}, endpoint) for field in receipt]
            cases.extend([
                (unrelated_receipt, endpoint),
                (receipt, unrelated_endpoint),
                ({**receipt, "root_pid": True}, endpoint),
                (receipt, "http://192.0.2.1:80"),
            ])
            with patch.object(identity, "_Windows", return_value=api), patch.object(api.kernel, "TerminateProcess", side_effect=AssertionError("unexpected process modification")) as terminate:
                for candidate, target in cases:
                    with self.subTest(receipt=candidate, endpoint=target), self.assertRaises((OSError, ValueError)):
                        identity.stop_verified_listener(candidate, target)
                terminate.assert_not_called()
            self.assertIsNone(wrapper.poll())
            self.assertIsNone(unrelated.poll())
            self.assertEqual(identity.verify_listener(receipt, endpoint), receipt)
            self.assertEqual(identity.verify_listener(unrelated_receipt, unrelated_endpoint), unrelated_receipt)

    def test_stop_rechecks_handle_identity_before_modification(self):
        receipt = dict(zip(identity._FIELDS, (10, 100, 20, 200)))
        for times in ([101], [100, 201], [100, 200, 101], [100, 200, OSError("root exited")]):
            api = Mock()
            api.open.side_effect = lambda pid, **kwargs: pid + 1000
            api.created.side_effect = times
            api.kernel.TerminateProcess.side_effect = AssertionError("unexpected process modification")
            with self.subTest(times=times), patch.object(identity, "observe_listener", return_value=receipt), patch.object(identity, "_Windows", return_value=api), self.assertRaises(OSError):
                identity.stop_verified_listener(receipt, "http://127.0.0.1:80")
            api.kernel.TerminateProcess.assert_not_called()
            self.assertEqual(api.close.call_count, api.open.call_count)

    def test_stop_uses_listener_handle_and_bounded_wait(self):
        receipt = dict(zip(identity._FIELDS, (10, 100, 20, 200)))
        for terminate_result, wait_result in ((True, 0), (False, 0), (True, 258), (True, 0xFFFFFFFF)):
            api = Mock()
            api.open.side_effect = [1010, 1020]
            api.created.side_effect = [100, 200, 100]
            api.kernel.TerminateProcess.return_value = terminate_result
            api.kernel.WaitForSingleObject.return_value = wait_result
            with self.subTest(terminate=terminate_result, wait=wait_result), patch.object(identity, "observe_listener", return_value=receipt), patch.object(identity, "_Windows", return_value=api):
                if terminate_result and wait_result == 0:
                    self.assertIsNone(identity.stop_verified_listener(receipt, "http://127.0.0.1:80"))
                else:
                    with self.assertRaises(OSError):
                        identity.stop_verified_listener(receipt, "http://127.0.0.1:80")
            self.assertEqual(api.open.call_args_list[0].args, (10,))
            self.assertEqual(api.open.call_args_list[1].args, (20,))
            self.assertEqual(api.open.call_args_list[1].kwargs, {"terminate": True})
            api.kernel.TerminateProcess.assert_called_once_with(1020, 1)
            if terminate_result:
                api.kernel.WaitForSingleObject.assert_called_once_with(1020, identity._STOP_TIMEOUT_MS)
            else:
                api.kernel.WaitForSingleObject.assert_not_called()
            self.assertEqual([call.args for call in api.close.call_args_list], [(1020,), (1010,)])

    def test_stop_handle_access_rights(self):
        api = identity._Windows()
        with patch.object(api.kernel, "OpenProcess", return_value=123) as open_process:
            self.assertEqual(api.open(20, terminate=True), 123)
            open_process.assert_called_once_with(0x1000 | 0x00100000 | 0x0001, False, 20)


if __name__ == "__main__":
    unittest.main()
