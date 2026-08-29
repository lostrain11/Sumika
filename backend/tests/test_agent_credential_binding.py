import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sumika_core.agent.credential_binding import (
    LAUNCH_PROTOCOL_MAGIC,
    encode_launch_binding,
    encode_launch_bindings,
    load_active_dsh_credential_binding,
    load_dsh_launch_bindings,
)
from sumika_core.agent.adapters.dsh.mcp_config import ManagedMcpPresetStore
from sumika_core.credentials import MemoryCredentialStore
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.storage import Storage


class AgentCredentialBindingTests(unittest.TestCase):
    def test_only_enabled_available_profile_api_key_is_loaded(self):
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            storage = Storage(data_dir / "sumika.sqlite3")
            credentials = MemoryCredentialStore()
            profiles = ProviderProfileManager(storage, credentials)
            try:
                profile = profiles.save(
                    {
                        "id": "remote-test",
                        "name": "Remote test",
                        "base_url": "https://example.test/v1",
                        "model": "model-a",
                        "api_key": "secret-value",
                    }
                )
                storage.update_provider_profile_state(profile["id"], status="available")
                storage.upsert_module_setting(
                    "llm",
                    enabled=True,
                    implementation_id="openai-compatible",
                    config={"profile_id": profile["id"]},
                )

                binding = load_active_dsh_credential_binding(
                    data_dir,
                    credential_store=credentials,
                )
                self.assertIsNotNone(binding)
                self.assertTrue(binding.environment_name.startswith("SUMIKA_"))
                self.assertTrue(binding.environment_name.endswith("_API_KEY"))
                self.assertEqual(binding.value, "secret-value")
                encoded = encode_launch_binding(binding)
                self.assertTrue(encoded.startswith(LAUNCH_PROTOCOL_MAGIC + b"\0loaded\0"))

                storage.upsert_module_setting(
                    "llm",
                    enabled=False,
                    implementation_id="openai-compatible",
                    config={"profile_id": profile["id"]},
                )
                self.assertIsNone(
                    load_active_dsh_credential_binding(data_dir, credential_store=credentials)
                )
            finally:
                storage.close()

    def test_secret_change_rotates_environment_reference(self):
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            storage = Storage(data_dir / "sumika.sqlite3")
            credentials = MemoryCredentialStore()
            profiles = ProviderProfileManager(storage, credentials)
            try:
                profile = profiles.save(
                    {
                        "id": "remote-rotate",
                        "name": "Remote rotate",
                        "base_url": "https://example.test/v1",
                        "model": "model-a",
                        "api_key": "first-value",
                    }
                )
                storage.update_provider_profile_state(profile["id"], status="available")
                storage.upsert_module_setting(
                    "llm",
                    enabled=True,
                    implementation_id="openai-compatible",
                    config={"profile_id": profile["id"]},
                )
                first = load_active_dsh_credential_binding(data_dir, credential_store=credentials)

                updated = profiles.save({**profile, "api_key": "second-value"})
                storage.update_provider_profile_state(updated["id"], status="available")
                second = load_active_dsh_credential_binding(data_dir, credential_store=credentials)

                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
                self.assertNotEqual(first.environment_name, second.environment_name)
                self.assertEqual(second.value, "second-value")
            finally:
                storage.close()

    def test_provider_and_mcp_credentials_share_a_bounded_v2_launch_payload(self):
        with TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            data_dir.mkdir()
            profile_dir = Path(directory) / "profile"
            preset_dir = profile_dir / ".agent-presets" / "sumika-work"
            preset_dir.mkdir(parents=True)
            (preset_dir / "agent.cordis.yml").write_text("- id: tool-fs\n", encoding="utf-8")
            storage = Storage(data_dir / "sumika.sqlite3")
            credentials = MemoryCredentialStore()
            profiles = ProviderProfileManager(storage, credentials)
            try:
                profile = profiles.save(
                    {
                        "id": "remote-combined",
                        "name": "Remote combined",
                        "base_url": "https://example.test/v1",
                        "model": "model-a",
                        "api_key": "provider-secret",
                    }
                )
                storage.update_provider_profile_state(profile["id"], status="available")
                storage.upsert_module_setting(
                    "llm",
                    enabled=True,
                    implementation_id="openai-compatible",
                    config={"profile_id": profile["id"]},
                )
                mcp = ManagedMcpPresetStore(profile_dir, credential_store=credentials)
                preview = mcp.preview(
                    "sumika-work",
                    {
                        "action": "upsert",
                        "configuration": {
                            "server_name": "github",
                            "transport": "stdio",
                            "enabled": False,
                            "command": "github-mcp-server",
                            "args": [],
                            "tool_call_timeout_ms": 60000,
                            "credential": {"target": "GITHUB_TOKEN", "prefix": "", "rotate": False},
                        },
                    },
                )
                mcp.apply(
                    "sumika-work",
                    preview["preview_token"],
                    lambda _: {"mountable": True, "validation_session_archived": True},
                    credential_value="mcp-secret",
                )

                bindings = load_dsh_launch_bindings(
                    data_dir,
                    profile_dir,
                    credential_store=credentials,
                )
                self.assertEqual(len(bindings), 2)
                self.assertTrue(any(item.value == "provider-secret" for item in bindings))
                self.assertTrue(any(item.value == "mcp-secret" for item in bindings))
                payload = encode_launch_bindings(bindings)
                fields = payload.split(b"\0")
                self.assertEqual(fields[:3], [LAUNCH_PROTOCOL_MAGIC, b"loaded", b"2"])
                self.assertEqual(fields[-1], b"")
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
