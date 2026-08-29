import json
import threading
import unittest
from http.client import HTTPConnection

from sumika_core.capabilities import (
    CAPABILITY_CATALOG_VERSION,
    CapabilityCatalog,
    CapabilityCatalogError,
    CapabilityImplementationDescriptor,
)
from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication, create_server


class _Modules:
    def __init__(self, rows):
        self.rows = rows

    def list(self):
        return list(self.rows)


class _ModelPolicy:
    def __init__(self, rows):
        self.rows = rows

    def catalog(self, *, refresh=False, session_id=None):
        self.last_call = (refresh, session_id)
        return {"entries": list(self.rows)}


class _Plugins:
    def __init__(self, rows):
        self.rows = rows

    def list(self):
        return list(self.rows)


class _Skills:
    def __init__(self, rows):
        self.rows = rows

    def list(self, *, refresh=False):
        self.last_refresh = refresh
        return list(self.rows)


class _Agent:
    runtime_id = "fixture"

    def status(self):
        return {"state": "ready", "ready": True, "version": "1.0"}

    def runtime_capabilities(self):
        return ["models", "mcp", "skills"]

    def supports(self, capability):
        return str(capability) == "mcp"

    def mcp_catalog(self, _params):
        return {
            "status": "configured",
            "entries": [
                {
                    "id": "filesystem",
                    "name": "Filesystem MCP",
                    "status": "configured",
                    "transport": "stdio",
                    "sources": ["managed-config"],
                    "enabled": True,
                    "tool_count": 2,
                },
                {"id": "fake-server", "name": "fake-server", "status": "available"},
            ],
        }


class _Browser:
    def status(self):
        return {
            "state": "ready",
            "ready": True,
            "backend": "BrowserSkill",
            "policy_bridge": {"mode": "strict", "path": r"C:\private\profile", "token": "secret"},
        }


class CapabilityDescriptorTests(unittest.TestCase):
    def test_descriptor_rejects_invalid_status_and_redacts_metadata(self):
        with self.assertRaises(CapabilityCatalogError):
            CapabilityImplementationDescriptor("id", "llm", "Name", status="not-a-state")

        descriptor = CapabilityImplementationDescriptor(
            "id",
            "llm",
            "Name",
            status="available",
            permissions=("network", r"C:\private", "Bearer hidden"),
            metadata={
                "safe": "value",
                "profile_id": "profile-local",
                "api_key": "hidden",
                "path": r"D:\private",
                "nested": {"mode": "read", "cookie": "hidden"},
            },
        ).to_dict()
        self.assertEqual(descriptor["permissions"], ["network"])
        self.assertEqual(descriptor["metadata"], {"safe": "value", "profile_id": "profile-local", "nested": {"mode": "read"}})


class CapabilityCatalogTests(unittest.TestCase):
    def setUp(self):
        self.modules = _Modules(
            [
                {
                    "id": "llm",
                    "capability": "llm",
                    "implementation_id": "openai-compatible",
                    "enabled": True,
                    "config": {"profile_id": "profile-local"},
                    "implementations": [],
                },
                {
                    "id": "tools",
                    "capability": "tool",
                    "implementation_id": "none",
                    "enabled": False,
                    "config": {},
                    "permissions": ["process.spawn"],
                    "implementations": [
                        {"id": "none", "name": "关闭模块", "status": "ready"},
                        {"id": "external-process", "name": "External process", "status": "unconfigured"},
                        {"id": "fake-tool", "name": "Fake tool", "status": "ready"},
                    ],
                },
            ]
        )
        self.models = _ModelPolicy(
            [
                {
                    "route_id": "profile:profile-local:qwen3:4b",
                    "provider_id": "openai-compatible",
                    "provider_profile_id": "profile-local",
                    "model_id": "qwen3:4b",
                    "display_name": "本地 Ollama · qwen3:4b",
                    "source_kind": "provider",
                    "processing_location": "local",
                    "auth_state": "not-required",
                    "quota_state": "not-applicable",
                    "health_state": "healthy",
                    "quality_tier": "strong",
                    "cost_class": "local",
                    "routable": True,
                },
                {
                    "route_id": "web:chatgpt",
                    "provider_id": "chatgpt-web",
                    "model_id": "web-session",
                    "display_name": "ChatGPT 网页聊天",
                    "source_kind": "web-chat",
                    "processing_location": "cloud",
                    "auth_state": "needs-auth",
                    "quota_state": "unknown",
                    "health_state": "unknown",
                    "routable": False,
                },
                {"route_id": "fake:model", "provider_id": "fake", "model_id": "fake", "display_name": "Fake"},
            ]
        )
        self.plugins = _Plugins(
            [
                {
                    "candidate_id": "plugin-valid",
                    "plugin_id": "filesystem-helper",
                    "state": "approved",
                    "launcher": {"executable": "tool.exe"},
                    "manifest": {"id": "filesystem-helper", "capabilities": ["tools"]},
                },
                {"plugin_id": "missing-candidate", "state": "approved", "manifest": {"capabilities": ["tools"]}},
            ]
        )
        self.skills = _Skills(
            [{"candidate_id": "skill-valid", "skill_id": "review", "name": "Review Skill", "state": "approved", "permissions": ["read"]}]
        )

    def test_catalog_projects_sources_and_selection_without_fake_entries(self):
        catalog = CapabilityCatalog(
            self.modules,
            agent=_Agent(),
            browser=_Browser(),
            plugins=self.plugins,
            skills=self.skills,
            model_policy=self.models,
        ).catalog(refresh=True, session_id="session-1")

        self.assertEqual(catalog["schema"], CAPABILITY_CATALOG_VERSION)
        self.assertEqual(self.models.last_call, (True, "session-1"))
        groups = {group["id"]: group for group in catalog["groups"]}
        self.assertEqual(set(groups), {"harness", "llm", "tools", "browser", "mcp", "skill"})
        llm = next(item for item in groups["llm"]["entries"] if item.get("metadata", {}).get("profile_id") == "profile-local")
        self.assertTrue(llm["selected"])
        self.assertTrue(llm["enabled"])
        self.assertTrue(llm["ready"])
        self.assertIn("plugin-valid", json.dumps(catalog, ensure_ascii=False))
        self.assertNotIn("fake", json.dumps(catalog, ensure_ascii=False).lower())
        browser = groups["browser"]["entries"][0]
        self.assertNotIn("path", json.dumps(browser["metadata"], ensure_ascii=False).lower())
        self.assertNotIn("token", json.dumps(browser["metadata"], ensure_ascii=False).lower())

    def test_catalog_can_omit_runtime_probes_and_records_source_failures(self):
        class Broken:
            def list(self, *args, **kwargs):
                raise RuntimeError("secret details")

        value = CapabilityCatalog(Broken(), model_policy=Broken()).catalog(include_runtime=False)
        self.assertEqual(value["entries"], [])
        self.assertEqual({item["source"] for item in value["source_errors"]}, {"modules", "model-policy"})
        self.assertNotIn("secret", json.dumps(value, ensure_ascii=False).lower())

    def test_runtime_source_errors_do_not_break_projection(self):
        class BrokenAgent(_Agent):
            def runtime_capabilities(self):
                raise RuntimeError("runtime failure")

            def mcp_catalog(self, _params):
                raise RuntimeError("mcp failure")

        value = CapabilityCatalog(self.modules, agent=BrokenAgent(), model_policy=self.models).catalog()
        self.assertIn("harness", {group["id"] for group in value["groups"]})
        self.assertGreaterEqual(value["summary"]["source_errors"], 1)

    def test_plugin_and_skill_source_errors_are_reported_without_breaking_catalog(self):
        class Broken:
            def list(self, *args, **kwargs):
                raise RuntimeError("private source details")

        value = CapabilityCatalog(self.modules, plugins=Broken(), skills=Broken(), model_policy=self.models).catalog()
        sources = {item["source"] for item in value["source_errors"]}
        self.assertIn("plugin-projection", sources)
        self.assertIn("skill-projection", sources)
        self.assertNotIn("private", json.dumps(value, ensure_ascii=False).lower())


class CapabilityHttpTests(unittest.TestCase):
    def test_rpc_validation_and_http_projection(self):
        application = CoreApplication(":memory:")
        self.addCleanup(application.close)
        with self.assertRaises(JsonRpcError):
            application.rpc("capability.catalog", {"refresh": "yes"})
        value = application.rpc("capability.catalog", {"includeRuntime": False})
        self.assertEqual(value["schema"], CAPABILITY_CATALOG_VERSION)

        server, app = create_server("127.0.0.1", 0, ":memory:")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            connection.request("GET", "/api/capabilities?include_runtime=false")
            response = connection.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            app.close()
        thread.join(timeout=2)
        self.assertEqual(response.status, 200)
        self.assertEqual(body["schema"], CAPABILITY_CATALOG_VERSION)
        self.assertIn("summary", body)


if __name__ == "__main__":
    unittest.main()
