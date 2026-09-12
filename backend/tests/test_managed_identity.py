import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from sumika_core.agent.managed_identity import ManagedRuntimeGuard, capture
from sumika_core.agent.contracts import AgentRuntimeError
from sumika_core.agent.adapters.dsh.runtime import DSHAgentRuntime
from sumika_core.server import CoreApplication
from quality_routing.harness import RuntimeBinding
import test_windows_identity as fixtures
from sumika_core.agent import windows_identity


FIXTURE_RELEASE = "fixture-release"
FIXTURE_VERSION = "fixture-v1"


def write_fixture_release(root, *, status="verified-active", contract="dsh-web-api-v1",
                          directory="install", executable="launcher.cmd"):
    """Describe a throwaway release so the identity path runs unmodified."""

    release_dir = Path(root) / "releases" / FIXTURE_RELEASE
    release_dir.mkdir(parents=True, exist_ok=True)
    lockfile = release_dir / "pnpm-lock.yaml"
    lockfile.write_text(
        "lockfileVersion: '9.0'\n\nimporters:\n\n  .:\n    dependencies:\n"
        "      '@deepseek-ai/dsh':\n"
        f"        specifier: {FIXTURE_VERSION}\n        version: {FIXTURE_VERSION}\n\n"
        f"packages:\n\n  '@deepseek-ai/dsh@{FIXTURE_VERSION}':\n    resolution:\n      integrity: sha512-fixture\n",
        encoding="utf-8",
    )
    description = {
        "schema": "sumika.dsh-release/v1",
        "id": FIXTURE_RELEASE,
        "status": status,
        "adapter_contract": contract,
        "harness": {
            "id": "dsh",
            "package": "@deepseek-ai/dsh",
            "version": FIXTURE_VERSION,
            "source": {"commit": "deadbeef", "commit_evidence": "fixture",
                       "tarball": "https://example.invalid/dsh.tgz",
                       "tarball_sha512": "sha512-fixture", "tarball_sha1": "fixture"},
            "install": {"root": str(Path(root).resolve()), "root_env": "SUMIKA_DSH_INSTALL_ROOT",
                        "directory": directory, "executable": executable},
            "artifacts": ["fixture artifact"],
            "signals": ["fixture signal"],
        },
        "toolchain": {"node": ">=22", "package_manager": "pnpm", "package_manager_major": 11,
                      "lockfile": "pnpm-lock.yaml",
                      "lockfile_sha256": hashlib.sha256(lockfile.read_bytes()).hexdigest()},
        "install_policy": {"lockfile_only": True, "ignore_scripts": True, "scripts_allowed": []},
        "plugins": [{"id": "fixture-plugin", "name": "@sumika/fixture", "version": "0.1.0",
                     "path": "plugins/fixture", "content_digest": "0" * 64, "install": "reference",
                     "default_enabled": False, "capabilities": ["fixture"]}],
        "verification": {"evidence": ["fixture"], "limitations": [], "blockers": []},
    }
    (release_dir / "release.json").write_text(json.dumps(description), encoding="utf-8")
    return description


@contextmanager
def described_release(root):
    previous = os.environ.get("SUMIKA_DSH_RELEASE_ROOT")
    os.environ["SUMIKA_DSH_RELEASE_ROOT"] = str(root)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SUMIKA_DSH_RELEASE_ROOT", None)
        else:
            os.environ["SUMIKA_DSH_RELEASE_ROOT"] = previous


@unittest.skipUnless(sys.platform == "win32", "Windows identity required")
class ManagedIdentityTests(unittest.TestCase):
    server = fixtures.WindowsIdentityTests.server

    def test_managed_launcher_owner_exit_cleans_the_listener_job(self):
        process = subprocess.Popen([sys.executable, "-m", "sumika_core.agent.managed_launcher"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        api = windows_identity._Windows()
        listener = None
        try:
            process.stdin.write(json.dumps([sys.executable, "-u", "-c", fixtures._SERVER]) + "\n")
            process.stdin.close()
            startup = queue.Queue()
            threading.Thread(target=lambda: startup.put(process.stdout.readline()), daemon=True).start()
            endpoint = "http://127.0.0.1:" + startup.get(timeout=10).strip()
            evidence = windows_identity.observe_listener(process.pid, endpoint)
            listener = api.open(evidence["listener_pid"])
            process.terminate()
            process.wait(timeout=10)
            self.assertEqual(api.kernel.WaitForSingleObject(listener, 5000), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            if not process.stdin.closed:
                process.stdin.close()
            process.stdout.close()
            if listener is not None:
                api.close(listener)

    def test_wrapper_receipt_profile_stability_and_restart_invalidation(self):
        with tempfile.TemporaryDirectory(prefix="Sumika 身份 ") as directory:
            profile = Path(directory) / "profile"
            profile.mkdir()
            install = Path(directory) / "install"
            install.mkdir()
            launcher = install / "launcher.cmd"
            launcher.write_text("fixture", encoding="utf-8")
            description = write_fixture_release(directory)
            installed_lock = install / "node_modules" / ".pnpm" / "lock.yaml"
            installed_lock.parent.mkdir(parents=True)
            installed_lock.write_bytes(
                (Path(directory) / "releases" / FIXTURE_RELEASE / "pnpm-lock.yaml").read_bytes()
            )
            with described_release(directory):
                with self.server(wrapper=True) as (process, endpoint):
                    request = {"root_pid": process.pid, "endpoint": endpoint, "profile": str(profile),
                               "executable": str(launcher), "version": FIXTURE_VERSION,
                               "release": FIXTURE_RELEASE}
                    evidence = capture(request)
                    guard = ManagedRuntimeGuard(evidence, endpoint=endpoint, profile=str(profile),
                                                version=FIXTURE_VERSION, release=FIXTURE_RELEASE)
                    guard.check()
                    self.assertEqual(capture(request), evidence)
                    self.assertTrue(evidence["binding"]["distribution_id"].startswith("dsh-release-"))
                    self.assertEqual(evidence["binding"]["adapter_version"], "dsh-web-api-v1")
                    self.assertNotEqual(evidence["process"]["root_pid"], evidence["process"]["listener_pid"])
                    changed = json.loads(json.dumps(evidence))
                    changed["process"]["listener_created"] += 1
                    with self.assertRaises(AgentRuntimeError):
                        ManagedRuntimeGuard(changed, endpoint=endpoint, profile=str(profile),
                                            version=FIXTURE_VERSION, release=FIXTURE_RELEASE)
                    with self.assertRaises(AgentRuntimeError):
                        ManagedRuntimeGuard(evidence, endpoint=endpoint, profile=str(profile),
                                            version="changed", release=FIXTURE_RELEASE)
                    with self.assertRaises(AgentRuntimeError):
                        ManagedRuntimeGuard(evidence, endpoint=endpoint, profile=str(profile),
                                            version=FIXTURE_VERSION, release="other-release")
                    launcher.write_text("changed", encoding="utf-8")
                    with self.assertRaises(AgentRuntimeError):
                        guard.check()
                    launcher.write_text("fixture", encoding="utf-8")
                    installed_lock = install / "node_modules" / ".pnpm" / "lock.yaml"
                    installed_lock.write_text("changed dependency tree", encoding="utf-8")
                    with self.assertRaises(AgentRuntimeError):
                        guard.check()
                    installed_lock.write_bytes(
                        (Path(directory) / "releases" / FIXTURE_RELEASE / "pnpm-lock.yaml").read_bytes()
                    )
                with self.assertRaises(AgentRuntimeError):
                    guard.check()
                with self.server(wrapper=True) as (process, endpoint):
                    newer = capture({**request, "root_pid": process.pid, "endpoint": endpoint})
                    self.assertEqual(newer["binding"]["instance_id"], evidence["binding"]["instance_id"])
                    self.assertNotEqual(newer["binding"]["launch_id"], evidence["binding"]["launch_id"])

    def test_capture_refuses_an_undescribed_or_blocked_launch(self):
        with tempfile.TemporaryDirectory(prefix="Sumika 发行 ") as directory:
            profile = Path(directory) / "profile"
            profile.mkdir()
            install = Path(directory) / "install"
            install.mkdir()
            launcher = install / "launcher.cmd"
            launcher.write_text("fixture", encoding="utf-8")
            outside = Path(directory) / "elsewhere.cmd"
            outside.write_text("fixture", encoding="utf-8")
            write_fixture_release(directory)
            with described_release(directory):
                with self.server(wrapper=True) as (process, endpoint):
                    base = {"root_pid": process.pid, "endpoint": endpoint, "profile": str(profile),
                            "executable": str(launcher), "version": FIXTURE_VERSION,
                            "release": FIXTURE_RELEASE}
                    with self.assertRaises(ValueError):
                        capture({**base, "executable": str(outside)})
                    with self.assertRaises(ValueError):
                        capture({**base, "version": "other-version"})
                    with self.assertRaises(Exception):
                        capture({**base, "release": "undescribed-release"})
            write_fixture_release(directory, status="blocked", contract="dsh-web-remote-v1")
            with described_release(directory):
                with self.server(wrapper=True) as (process, endpoint):
                    with self.assertRaises(ValueError):
                        capture({"root_pid": process.pid, "endpoint": endpoint, "profile": str(profile),
                                 "executable": str(launcher), "version": FIXTURE_VERSION,
                                 "release": FIXTURE_RELEASE})

    def test_adapter_rechecks_before_quote_http_and_event_normalization(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        guard = Mock(side_effect=AgentRuntimeError("identity changed"))
        runtime.set_identity_guard(guard)
        sink = Mock()
        runtime.set_event_sink(sink)
        with patch("urllib.request.urlopen") as upstream, patch.object(runtime, "normalize_event") as normalize:
            with self.assertRaises(AgentRuntimeError):
                runtime.execution_quote({})
            with self.assertRaises(AgentRuntimeError):
                runtime._get("/api/host.describe")
            runtime._receive_event({"event_type": "turn.completed"})
            upstream.assert_not_called()
            normalize.assert_not_called()
            sink.assert_not_called()
        with self.assertRaises(AgentRuntimeError):
            runtime.set_identity_guard(Mock())

    def test_changed_runtime_status_preserves_historical_binding_without_rebinding(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        binding = RuntimeBinding("dsh", "fixture-profile", "fixture-release", "v1", "managed", "evidence", "launch", "receipt")
        runtime.bind_runtime(binding)
        app = CoreApplication(":memory:", agent_runtime=runtime)
        try:
            runtime.set_identity_guard(Mock(side_effect=AgentRuntimeError("restarted")))
            status = app.rpc("agent.runtime.binding", {})
            self.assertFalse(status["available"])
            self.assertEqual(status["reason"], "runtime-instance-changed")
            self.assertEqual(status["binding"], binding.to_dict())
        finally:
            app.close()
