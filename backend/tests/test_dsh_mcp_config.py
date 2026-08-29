import json
import tempfile
import unittest
from pathlib import Path

from sumika_core.agent import AgentRuntimeError
from sumika_core.agent.adapters.dsh.mcp_config import load_mcp_launch_bindings
from sumika_core.agent.adapters.dsh.runtime import DSHAgentRuntime
from sumika_core.credentials import MemoryCredentialStore


class DshManagedMcpConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.profile = Path(self.temporary.name) / "profile"
        self.preset = self.profile / ".agent-presets" / "sumika-work"
        self.preset.mkdir(parents=True)
        self.composition = self.preset / "agent.cordis.yml"
        self.original = "- id: tool-fs\n  name: '@deepseek-ai/dsh-tool-fs'\n"
        self.composition.write_text(self.original, encoding="utf-8")
        self.original_bytes = self.composition.read_bytes()
        package = self.profile / "profiles" / "node_modules" / "@deepseek-ai" / "dsh-mcp-client"
        package.mkdir(parents=True)
        (package / "package.json").write_text(
            json.dumps({"name": "@deepseek-ai/dsh-mcp-client", "version": "0.1.1-rc.2"}),
            encoding="utf-8",
        )
        self.runtime = DSHAgentRuntime(
            self.temporary.name,
            env={
                "SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1",
                "SUMIKA_DSH_PROFILE_DIR": str(self.profile),
            },
        )
        self.credentials = MemoryCredentialStore()
        self.runtime.bind_credential_store(self.credentials)
        self.calls = []

        def call(method, payload):
            self.calls.append((method, payload))
            if method == "agentPreset.list":
                return {
                    "presets": [
                        {"id": "standard", "trust": "system", "isDefault": True},
                        {"id": "sumika-work", "trust": "user", "isDefault": False},
                    ],
                    "authorable": True,
                }
            if method == "session.create":
                return {"sessionId": "mcp-validation"}
            if method == "workspace.archiveSession":
                return {"archivedSessionIds": ["mcp-validation"]}
            raise AssertionError(f"unexpected DSH call: {method}")

        self.runtime._call = call

    def _stdio_configuration(self, **overrides):
        value = {
            "server_name": "filesystem",
            "transport": "stdio",
            "enabled": True,
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\Code"],
            "tool_call_timeout_ms": 60000,
        }
        value.update(overrides)
        return value

    def _preview(self, configuration=None, action="upsert"):
        return self.runtime.preview_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "action": action,
                "configuration": configuration or self._stdio_configuration(),
            }
        )

    def test_preview_apply_list_and_remove_keep_composition_recoverable(self):
        preview = self._preview()
        self.assertEqual(preview["change"], "create")
        self.assertTrue(preview["requires_approval"])
        self.assertNotIn(str(self.profile), str(preview))

        applied = self.runtime.apply_mcp_configuration(
            {"agentPreset": "sumika-work", "previewToken": preview["preview_token"]}
        )
        self.assertTrue(applied["applied"])
        self.assertTrue(applied["mountable"])
        self.assertTrue(applied["validation_session_archived"])
        self.assertTrue(applied["backup_retained"])
        self.assertNotIn(str(self.profile), str(applied))

        rendered = self.composition.read_text(encoding="utf-8")
        self.assertIn("# sumika-managed-mcp:v1 begin filesystem", rendered)
        self.assertIn('"name":"@deepseek-ai/dsh-mcp-client"', rendered)
        self.assertIn('"failOnStartupError":true', rendered)
        self.assertNotIn("apiKey", rendered)
        listed = self.runtime.list_mcp_configurations({"agentPreset": "sumika-work"})
        self.assertEqual(listed["configurations"], [self._stdio_configuration()])
        backups = list((self.profile / "sumika-backups" / "agent-presets" / "sumika-work").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), self.original)

        noop_preview = self._preview()
        self.assertEqual(noop_preview["change"], "noop")
        self.assertFalse(noop_preview["requires_approval"])
        with self.assertRaisesRegex(AgentRuntimeError, "no changes"):
            self.runtime.apply_mcp_configuration(
                {"agentPreset": "sumika-work", "previewToken": noop_preview["preview_token"]}
            )

        remove_preview = self._preview(
            {"server_name": "filesystem"},
            action="remove",
        )
        removed = self.runtime.apply_mcp_configuration(
            {"agentPreset": "sumika-work", "previewToken": remove_preview["preview_token"]}
        )
        self.assertEqual(removed["change"], "remove")
        self.assertNotIn("sumika-managed-mcp", self.composition.read_text(encoding="utf-8"))

    def test_mount_failure_restores_exact_original_and_retains_backup(self):
        preview = self._preview()

        def failing_call(method, payload):
            if method == "agentPreset.list":
                return {"presets": [{"id": "sumika-work", "trust": "user"}]}
            if method == "session.create":
                raise AgentRuntimeError("MCP server failed to start")
            raise AssertionError(f"unexpected DSH call: {method}")

        self.runtime._call = failing_call
        with self.assertRaisesRegex(AgentRuntimeError, "original composition was restored"):
            self.runtime.apply_mcp_configuration(
                {"agentPreset": "sumika-work", "previewToken": preview["preview_token"]}
            )
        self.assertEqual(self.composition.read_bytes(), self.original_bytes)
        backups = list((self.profile / "sumika-backups" / "agent-presets" / "sumika-work").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original_bytes)

    def test_apply_rejects_stale_preview_without_overwriting_external_change(self):
        preview = self._preview()
        external = self.original + "# external edit\n"
        self.composition.write_text(external, encoding="utf-8")

        with self.assertRaisesRegex(AgentRuntimeError, "changed after preview"):
            self.runtime.apply_mcp_configuration(
                {"agentPreset": "sumika-work", "previewToken": preview["preview_token"]}
            )
        self.assertEqual(self.composition.read_text(encoding="utf-8"), external)
        self.assertFalse((self.profile / "sumika-backups").exists())

    def test_configuration_rejects_credentials_and_unsafe_targets(self):
        for field, value in (
            ("env", {"TOKEN": "secret"}),
            ("headers", {"Authorization": "Bearer secret"}),
            ("api_key", "secret"),
        ):
            configuration = self._stdio_configuration()
            configuration[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(AgentRuntimeError, "unsupported MCP configuration fields"):
                self._preview(configuration)

        with self.assertRaisesRegex(AgentRuntimeError, "without credentials"):
            self._preview(
                {
                    "server_name": "remote",
                    "transport": "streamable-http",
                    "enabled": False,
                    "url": "https://user:secret@example.com/mcp",
                    "tool_call_timeout_ms": 60000,
                }
            )

    def test_configuration_requires_a_healthy_user_owned_preset(self):
        def system_only(method, payload):
            self.assertEqual(method, "agentPreset.list")
            return {"presets": [{"id": "standard", "trust": "system"}]}

        self.runtime._call = system_only
        with self.assertRaisesRegex(AgentRuntimeError, "user-owned"):
            self.runtime.preview_mcp_configuration(
                {
                    "agentPreset": "standard",
                    "action": "upsert",
                    "configuration": self._stdio_configuration(),
                }
            )

    def test_protected_stdio_credential_is_stored_outside_composition_and_deferred_until_restart(self):
        configuration = self._stdio_configuration(
            credential={"target": "GITHUB_TOKEN", "prefix": "", "rotate": False}
        )
        preview = self._preview(configuration)
        self.assertTrue(preview["credential_requires_value"])
        self.assertTrue(preview["restart_required"])
        self.assertTrue(preview["deferred_enable"])
        self.assertFalse(preview["configuration"]["enabled"])
        self.assertNotIn("environment_ref", str(preview))

        applied = self.runtime.apply_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "previewToken": preview["preview_token"],
                "credentialValue": "private-mcp-token",
            }
        )
        self.assertTrue(applied["credential_changed"])
        self.assertTrue(applied["restart_required"])
        rendered = self.composition.read_text(encoding="utf-8")
        self.assertIn("# sumika-managed-mcp:v2 begin filesystem", rendered)
        self.assertIn("!!js 'process.env.SUMIKA_MCP_", rendered)
        self.assertIn('"env":{"GITHUB_TOKEN":!!js', rendered)
        self.assertNotIn("private-mcp-token", rendered)

        listed = self.runtime.list_mcp_configurations({"agentPreset": "sumika-work"})
        credential = listed["configurations"][0]["credential"]
        self.assertTrue(credential["configured"])
        self.assertFalse(credential["loaded_at_launch"])
        self.assertTrue(credential["restart_required"])
        bindings = load_mcp_launch_bindings(self.profile, self.credentials)
        self.assertEqual(len(bindings), 1)
        self.assertTrue(bindings[0][0].startswith("SUMIKA_MCP_"))
        self.assertEqual(bindings[0][1], "private-mcp-token")

        restarted = DSHAgentRuntime(
            self.temporary.name,
            env={
                "SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1",
                "SUMIKA_DSH_PROFILE_DIR": str(self.profile),
                "SUMIKA_DSH_MCP_CREDENTIAL_REFS": bindings[0][0],
            },
        )
        restarted.bind_credential_store(self.credentials)
        restarted._call = self.runtime._call
        after_restart = restarted.list_mcp_configurations({"agentPreset": "sumika-work"})
        self.assertTrue(after_restart["configurations"][0]["credential"]["loaded_at_launch"])
        enable_configuration = {
            **configuration,
            "enabled": True,
            "credential": {"target": "GITHUB_TOKEN", "prefix": "", "rotate": False},
        }
        enable_preview = restarted.preview_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "action": "upsert",
                "configuration": enable_configuration,
            }
        )
        self.assertFalse(enable_preview["credential_requires_value"])
        self.assertFalse(enable_preview["deferred_enable"])
        self.assertTrue(enable_preview["configuration"]["enabled"])

    def test_http_credential_prefix_is_preserved_and_tampering_is_rejected(self):
        configuration = {
            "server_name": "remote",
            "transport": "streamable-http",
            "enabled": False,
            "url": "https://example.test/mcp",
            "tool_call_timeout_ms": 60000,
            "credential": {"target": "Authorization", "prefix": "Bearer ", "rotate": False},
        }
        preview = self._preview(configuration)
        self.runtime.apply_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "previewToken": preview["preview_token"],
                "credentialValue": "http-secret",
            }
        )
        rendered = self.composition.read_text(encoding="utf-8")
        self.assertIn('"headers":{"Authorization":!!js', rendered)
        self.assertIn('"Bearer " + process.env.', rendered)
        self.assertEqual(
            self.runtime.list_mcp_configurations({"agentPreset": "sumika-work"})["configurations"][0]["credential"]["prefix"],
            "Bearer ",
        )
        self.composition.write_text(rendered.replace('"Bearer "', '"Basic "', 1), encoding="utf-8")
        with self.assertRaisesRegex(AgentRuntimeError, "row was modified"):
            self.runtime.list_mcp_configurations({"agentPreset": "sumika-work"})

    def test_enabled_configuration_with_missing_secret_fails_launch_closed(self):
        configuration = self._stdio_configuration(
            enabled=False,
            credential={"target": "GITHUB_TOKEN", "prefix": "", "rotate": False},
        )
        preview = self._preview(configuration)
        self.runtime.apply_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "previewToken": preview["preview_token"],
                "credentialValue": "temporary-token",
            }
        )
        bindings = load_mcp_launch_bindings(self.profile, self.credentials)
        self.assertEqual(len(bindings), 1)
        restarted = DSHAgentRuntime(
            self.temporary.name,
            env={
                "SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1",
                "SUMIKA_DSH_PROFILE_DIR": str(self.profile),
                "SUMIKA_DSH_MCP_CREDENTIAL_REFS": bindings[0][0],
            },
        )
        restarted.bind_credential_store(self.credentials)
        restarted._call = self.runtime._call
        enable_preview = restarted.preview_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "action": "upsert",
                "configuration": {**configuration, "enabled": True},
            }
        )
        restarted.apply_mcp_configuration(
            {"agentPreset": "sumika-work", "previewToken": enable_preview["preview_token"]}
        )
        for reference in list(self.credentials._values):
            self.credentials.delete(reference)
        with self.assertRaisesRegex(AgentRuntimeError, "missing its protected credential"):
            load_mcp_launch_bindings(self.profile, self.credentials)

    def test_credential_mount_failure_restores_file_and_secure_store(self):
        preview = self._preview(
            self._stdio_configuration(
                credential={"target": "GITHUB_TOKEN", "prefix": "", "rotate": False}
            )
        )

        def failing_call(method, payload):
            if method == "agentPreset.list":
                return {"presets": [{"id": "sumika-work", "trust": "user"}]}
            if method == "session.create":
                raise AgentRuntimeError("credential MCP failed to mount")
            raise AssertionError(f"unexpected DSH call: {method}")

        self.runtime._call = failing_call
        with self.assertRaisesRegex(AgentRuntimeError, "original composition was restored"):
            self.runtime.apply_mcp_configuration(
                {
                    "agentPreset": "sumika-work",
                    "previewToken": preview["preview_token"],
                    "credentialValue": "must-be-rolled-back",
                }
            )
        self.assertEqual(self.composition.read_bytes(), self.original_bytes)
        self.assertEqual(self.credentials._values, {})

    def test_rotating_a_credential_changes_only_the_launch_reference(self):
        configuration = self._stdio_configuration(
            enabled=False,
            credential={"target": "GITHUB_TOKEN", "prefix": "", "rotate": False},
        )
        preview = self._preview(configuration)
        self.runtime.apply_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "previewToken": preview["preview_token"],
                "credentialValue": "first-token",
            }
        )
        first_binding = load_mcp_launch_bindings(self.profile, self.credentials)[0]
        restarted = DSHAgentRuntime(
            self.temporary.name,
            env={
                "SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1",
                "SUMIKA_DSH_PROFILE_DIR": str(self.profile),
                "SUMIKA_DSH_MCP_CREDENTIAL_REFS": first_binding[0],
            },
        )
        restarted.bind_credential_store(self.credentials)
        restarted._call = self.runtime._call
        rotation = restarted.preview_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "action": "upsert",
                "configuration": {
                    **configuration,
                    "credential": {"target": "GITHUB_TOKEN", "prefix": "", "rotate": True},
                },
            }
        )
        self.assertTrue(rotation["credential_requires_value"])
        self.assertTrue(rotation["restart_required"])
        restarted.apply_mcp_configuration(
            {
                "agentPreset": "sumika-work",
                "previewToken": rotation["preview_token"],
                "credentialValue": "second-token",
            }
        )
        second_binding = load_mcp_launch_bindings(self.profile, self.credentials)[0]
        self.assertNotEqual(first_binding[0], second_binding[0])
        self.assertEqual(second_binding[1], "second-token")
        self.assertNotIn("first-token", self.composition.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
