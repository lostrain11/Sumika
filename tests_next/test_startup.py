import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ui import startup


class _Key:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class StartupTests(unittest.TestCase):
    def _registry(self, existing=None):
        registry = MagicMock()
        registry.HKEY_CURRENT_USER = "HKCU"
        registry.REG_SZ = 1
        store = dict(existing or {})
        registry.CreateKeyEx.return_value = _Key(store)
        registry.OpenKey.return_value = _Key(store)

        def query(key, name):
            if name not in store:
                raise FileNotFoundError(name)
            return store[name], 1

        registry.QueryValueEx.side_effect = query

        def set_value(key, name, reserved, kind, value):
            store[name] = value

        registry.SetValueEx.side_effect = set_value

        def delete_value(key, name):
            if name not in store:
                raise FileNotFoundError(name)
            del store[name]

        registry.DeleteValue.side_effect = delete_value
        registry.store = store
        return registry

    def test_enable_writes_the_tray_command_and_reads_back(self):
        registry = self._registry()
        result = startup.apply(True, "D:/Code/Sumika", registry=registry)
        self.assertTrue(result["applied"])
        self.assertIn("sumika_tray.ps1", result["command"])
        state = startup.read(registry=registry)
        self.assertTrue(state["registry_present"])
        self.assertIn("sumika_tray.ps1", state["command"])

    def test_disable_removes_the_entry_and_is_idempotent(self):
        registry = self._registry({startup.VALUE_NAME: "old"})
        startup.apply(False, "D:/Code/Sumika", registry=registry)
        self.assertFalse(startup.read(registry=registry)["registry_present"])
        second = startup.apply(False, "D:/Code/Sumika", registry=registry)
        self.assertTrue(second["applied"], "removing a missing entry is not an error")

    def test_missing_registry_support_is_reported_not_assumed(self):
        with patch("ui.startup._winreg", return_value=None):
            self.assertFalse(startup.read()["supported"])
            result = startup.apply(True, "D:/Code/Sumika")
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "registry unavailable")

    def test_tray_command_points_at_the_tray_script(self):
        command = startup.tray_command("D:/Code/Sumika")
        self.assertIn("powershell", command)
        self.assertIn("-WindowStyle Hidden", command)
        self.assertTrue(command.endswith('sumika_tray.ps1"'), command)


if __name__ == "__main__":
    unittest.main()
