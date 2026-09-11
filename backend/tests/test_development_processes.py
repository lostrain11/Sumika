import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

from sumika_core.development.processes import ManagedTestProcess, WindowsJob


@unittest.skipUnless(os.name == "nt", "Windows Job Object lifecycle")
class DevelopmentProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.marker = self.root / "child.json"
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def alive(self, pid):
        handle = self.kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            state = self.kernel.WaitForSingleObject(handle, 0)
            self.assertIn(state, (0, 258))
            return state == 258
        finally:
            self.kernel.CloseHandle(handle)

    def await_marker(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                return json.loads(self.marker.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(.02)
        self.fail("child did not report its PID")

    def assert_stopped(self, pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.alive(pid):
            time.sleep(.02)
        self.assertFalse(self.alive(pid), "owned descendant survived job closure")

    def spawn_command(self, wait_seconds):
        code = ("import subprocess,sys,time,json; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                "Path(sys.argv[1]).write_text(json.dumps(child.pid)); time.sleep(float(sys.argv[2]))")
        return [sys.executable, "-c", code, str(self.marker), str(wait_seconds)]

    def test_normal_exit_reaps_descendant_even_after_parent_exits(self):
        with tempfile.TemporaryFile() as output:
            with ManagedTestProcess(self.spawn_command(.2), cwd=self.root, env=dict(os.environ), output=output) as process:
                pid = self.await_marker()
                self.assertTrue(self.alive(pid))
                self.assertEqual(process.wait(timeout=5), 0)
            self.assert_stopped(pid)

    def test_cancel_reaps_job_but_preserves_other_process(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with tempfile.TemporaryFile() as output:
                with ManagedTestProcess(self.spawn_command(30), cwd=self.root, env=dict(os.environ), output=output):
                    pid = self.await_marker()
                self.assert_stopped(pid)
                self.assertIsNone(unrelated.poll())
        finally:
            unrelated.kill()
            unrelated.wait(timeout=5)

    def test_failed_job_assignment_never_starts_the_command(self):
        with tempfile.TemporaryFile() as output, patch.object(WindowsJob, "assign", side_effect=OSError("assignment rejected")):
            with self.assertRaises(OSError):
                ManagedTestProcess(self.spawn_command(0), cwd=self.root, env=dict(os.environ), output=output)
        self.assertFalse(self.marker.exists())

    def test_owner_abrupt_exit_closes_job_without_python_cleanup(self):
        host_code = "\n".join([
            "import json,os,sys,tempfile,time",
            "from pathlib import Path",
            "from sumika_core.development.processes import ManagedTestProcess",
            "command=json.loads(sys.argv[1])",
            "marker=Path(sys.argv[2])",
            "with tempfile.TemporaryFile() as output:",
            "    with ManagedTestProcess(command,cwd=marker.parent,env=dict(os.environ),output=output):",
            "        deadline=time.monotonic()+5",
            "        while not marker.exists() and time.monotonic()<deadline:",
            "            time.sleep(.02)",
            "        os._exit(0 if marker.exists() else 3)",
        ])
        host = subprocess.run([sys.executable, "-c", host_code, json.dumps(self.spawn_command(30)), str(self.marker)],
                              capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(host.returncode, 0, host.stderr.decode(errors="replace"))
        self.assert_stopped(self.await_marker())


if __name__ == "__main__":
    unittest.main()
