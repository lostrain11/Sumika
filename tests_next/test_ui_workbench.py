import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ui.workbench import WorkbenchController, WorkbenchError, ensure_skin


class FakeAdapter:
    """Stands in for the managed Dsh adapter owned by the bridge."""

    def __init__(self, *, url="http://127.0.0.1:5175",
                 embed="http://127.0.0.1:5175/?token=unit-test-token", pid=4242,
                 messages=(), fail=None, alive=True):
        self.url = url
        self._browser_url = embed
        self.startup_messages = list(messages)
        self.process = MagicMock()
        self.process.pid = pid
        self.process.poll.return_value = None if alive else 1
        self.started_with = None
        self.closed = False
        self._fail = fail

    def start(self, port=0):
        if self._fail:
            raise self._fail
        self.started_with = port
        return self

    def close(self):
        self.closed = True
        self.process.poll.return_value = 1

    def _rpc(self, method, arguments):
        return {}


class WorkbenchControllerTests(unittest.TestCase):
    def test_relocated_profile_uses_selected_product_plugins(self):
        with tempfile.TemporaryDirectory() as d:
            product = self._root(d)
            home = product/'personal/profile'
            home.mkdir(parents=True)
            foreign = {'id': 'user-plugin', 'name': 'D:/external/custom.mjs', 'config': {'enabled': False}}
            patch_path = home/'cordis.patch.yml'
            patch_path.write_text(json.dumps([{'insert': [foreign, {'id': 'sumika-skin', 'name': 'D:/old/skin.mjs'}]}]))
            ensure_skin(home, root=product)
            first = patch_path.read_bytes()
            ensure_skin(home, root=product)
            self.assertEqual(first, patch_path.read_bytes())
            entries = [item for row in json.loads(first) for item in row.get('insert', [])]
            self.assertIn(foreign, entries)
            owned = [item for item in entries if item['id'].startswith('sumika-')]
            self.assertEqual(len(owned), 3)
            self.assertTrue(all(Path(item['name']).is_relative_to(product.resolve()/'extensions/ui') for item in owned))
            self.assertEqual(next(item for item in owned if item['id'] == 'sumika-brand')['config']['release'], '0.1.5-rc.2')

    def setUp(self):
        # Controller behavior is tested with fake subprocesses; lease gets its
        # own tests using a real process creation identity and Windows locking.
        mock=patch('ui.workbench.ProfileLease')
        mock.start()
        self.addCleanup(mock.stop)
    def test_occupied_port_does_not_kill_or_adopt_a_process(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            with patch.object(controller, '_port_in_use', return_value=True), patch('ui.workbench.Dsh') as factory:
                with self.assertRaisesRegex(WorkbenchError, 'unowned'):
                    controller.start(port=5175)
                factory.assert_not_called()

    def test_failed_stop_keeps_owned_instance_and_unknown_result(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            adapter = FakeAdapter()
            controller.adapter = adapter
            with patch.object(adapter, 'close', side_effect=OSError('busy')):
                with self.assertRaisesRegex(WorkbenchError, 'unknown'):
                    controller.stop()
            self.assertIs(controller.adapter, adapter)
            with patch.object(adapter, 'close', side_effect=subprocess.TimeoutExpired('owned child', 1)):
                with self.assertRaisesRegex(WorkbenchError, 'unknown'):
                    controller.stop()
            self.assertIs(controller.adapter, adapter)
            with patch.object(adapter, 'close'):
                with self.assertRaisesRegex(WorkbenchError, 'not confirmed'):
                    controller.stop()
            self.assertIs(controller.adapter, adapter)

    def _root(self, folder, *, installed=True):
        root = Path(folder)
        dsh = root / "runtime" / "dsh"
        (dsh / "node_modules" / "@deepseek-ai" / "dsh").mkdir(parents=True)
        (dsh / "release.json").write_text(json.dumps({"version": "0.1.5-rc.2", "status": "verified"}),
                                          encoding="utf8")
        if installed:
            (dsh / "node_modules" / "@deepseek-ai" / "dsh" / "package.json").write_text("{}", encoding="utf8")
        return root

    def test_status_reports_install_without_claiming_a_run(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            status = controller.status()
            self.assertTrue(status["installed"])
            self.assertTrue(status["verified"])
            self.assertFalse(status["running"])
            self.assertIsNone(status["url"])
            self.assertIsNone(status["pid"])
            self.assertFalse(status["embed_ready"])

    def test_missing_install_is_reported_not_faked(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d, installed=False))
            self.assertFalse(controller.status()["installed"])
            with self.assertRaisesRegex(WorkbenchError, "not installed"):
                controller.start()

    def test_start_owns_the_adapter_and_exposes_an_embed_url(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            adapter = FakeAdapter()
            with patch("ui.workbench.Dsh", return_value=adapter), \
                    patch.object(WorkbenchController, "_port_in_use", return_value=False):
                status = controller.start(port=5175)
            self.assertEqual(adapter.started_with, 5175)
            self.assertTrue(status["running"])
            self.assertEqual(status["url"], "http://127.0.0.1:5175")
            self.assertEqual(status["pid"], 4242)
            self.assertTrue(status["embed_ready"])
            self.assertIn("token=", controller.embed_url()["url"])
            self.assertEqual(controller.stop(), {"stopped": True, "pid": 4242})
            self.assertTrue(adapter.closed, "stopping closes the adapter we own")
            self.assertFalse(controller.status()["running"])
            with self.assertRaisesRegex(WorkbenchError, "not running"):
                controller.embed_url()

    def test_start_failures_fail_closed_and_validate_the_port(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            with patch("ui.workbench.Dsh", return_value=FakeAdapter(fail=RuntimeError("boom"))), \
                    patch.object(WorkbenchController, "_port_in_use", return_value=False):
                with self.assertRaisesRegex(WorkbenchError, "failed to start"):
                    controller.start()
            with patch("ui.workbench.Dsh", return_value=FakeAdapter(url=None)), \
                    patch.object(WorkbenchController, "_port_in_use", return_value=False):
                with self.assertRaisesRegex(WorkbenchError, "did not report a URL"):
                    controller.start()
            with self.assertRaisesRegex(WorkbenchError, "invalid port"):
                controller.start(port=70000)

    def test_start_is_idempotent_while_running(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            adapter = FakeAdapter()
            with patch("ui.workbench.Dsh", return_value=adapter) as factory, \
                    patch.object(WorkbenchController, "_port_in_use", return_value=False):
                controller.start(port=5175)
                controller.start(port=5175)
            self.assertEqual(factory.call_count, 1, "a running instance is reused, not restarted")

    def test_timeline_is_timestamped_classified_and_cleared_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            adapter = FakeAdapter(messages=["booting", "error: model route refused"])
            with patch("ui.workbench.Dsh", return_value=adapter), \
                    patch.object(WorkbenchController, "_port_in_use", return_value=False):
                status = controller.start(port=5175)
            levels = [item["level"] for item in status["timeline"]]
            # start() first records that the Sumika skin was registered in the profile.
            self.assertEqual(levels, ["info", "info", "error", "system"])
            self.assertIn("皮肤已登记", status["timeline"][0]["text"])
            self.assertTrue(all(item["at"] for item in status["timeline"]))
            self.assertIn("DSH Web:", status["timeline"][-1]["text"])
            with patch("ui.workbench.Dsh", return_value=FakeAdapter(messages=["fresh"])):
                controller.adapter = None
                controller.url = None
                status = controller.status()
            self.assertEqual([item["text"] for item in status["timeline"]],
                             ["Sumika 皮肤已登记到受管 profile", "booting",
                              "error: model route refused", "DSH Web: http://127.0.0.1:5175"])

    def test_stop_without_an_owned_process_reports_that_honestly(self):
        with tempfile.TemporaryDirectory() as d:
            controller = WorkbenchController(self._root(d))
            self.assertEqual(controller.stop(),
                             {"stopped": False, "reason": "no process owned by this bridge"})


class WorkbenchBridgeTests(unittest.TestCase):
    def test_bridge_exposes_workbench_endpoints(self):
        import threading
        import urllib.error
        import urllib.request
        from extensions.models.settings import example, save as save_settings
        from extensions.roles.roles import import_card
        from ui.server import serve

        with tempfile.TemporaryDirectory() as d:
            root = self._root(d)
            card = root / "card.json"
            card.write_text(json.dumps({"spec": "chara_card_v2", "data": {
                "name": "角色", "description": "人格", "character_book": {"entries": []}}},
                ensure_ascii=False), encoding="utf8")
            role = import_card(card, root / "store", "bridge-role")
            save_settings(example(role, root / "sumika.db"), root / "settings.json")
            server = serve(root / "settings.json", port=0, workbench_root=root)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/workbench", timeout=10) as response:
                    payload = json.loads(response.read().decode("utf8"))
                self.assertTrue(payload["installed"])
                self.assertFalse(payload["running"])
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/manage/session") as response:
                    csrf = json.load(response)['csrf']
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/workbench/stop",
                                                 method="POST", data=b"{}",
                                                 headers={"Content-Type": "application/json", 'X-Sumika-CSRF':csrf})
                with urllib.request.urlopen(request, timeout=10) as response:
                    stopped = json.loads(response.read().decode("utf8"))
                self.assertFalse(stopped["stopped"])
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/workbench/embed", timeout=10)
                self.assertEqual(caught.exception.code, 502)
            finally:
                server.shutdown()
                server.server_close()

    _root = WorkbenchControllerTests._root


if __name__ == "__main__":
    unittest.main()
