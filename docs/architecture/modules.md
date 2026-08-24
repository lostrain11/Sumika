# Module catalog

`ModuleCatalog` is the capability-level boundary between the core and concrete
implementations. The core stores only a module's enabled flag, selected
implementation id, and non-secret configuration. A provider or future plugin
owns its stream/runtime behavior.

## Runtime contract

The first slice exposes these JSON-RPC methods:

- `module.list` returns capability metadata, implementations, permissions,
  resource requirements, selected configuration, and the implementation schema.
- `module.update` accepts `module_id`, optional `enabled`,
  `implementation_id`, and optional `config`.

`GET /api/modules` is the read-only HTTP view of `module.list`. Every update
publishes a durable `module.changed` event so another window can refresh its
state.

## Persistence and secrets

Module state is stored in the versioned SQLite `module_settings` table. LLM
starts disabled in a new workspace and has no profile until the user saves and
tests one. The catalog validates required fields and basic JSON-schema types
before writing.
Properties whose schema uses `format: "password"` are applied to the running
provider but are deliberately excluded from SQLite. The production desktop
runtime uses Windows Credential Manager through `CredentialStore`; unit tests
use an in-memory store. This boundary can evolve without changing the module
API.

LLM connection details use the separate `provider_profiles` table and its
`CredentialStore` boundary. The module stores only `config.profile_id`; API
keys and sensitive headers are held by Windows Credential Manager in the
current production desktop runtime. macOS/Linux reject non-empty secret
persistence until an approved Keychain/Secret Service adapter exists. See
`provider-profiles.md` for the drawer, health check and archive lifecycle.

Switching implementation clears the previous implementation's configuration
unless the caller supplies a new configuration in the same update. This keeps
provider-specific fields from leaking across implementations.

## Adding an implementation

1. Implement the provider or driver boundary and expose a `ProviderInfo` or
   manifest schema.
2. Register it with the relevant registry; do not add provider-specific logic
   to `CoreApplication._chat`.
3. Add the capability's implementation metadata to the catalog when it is not
   a provider-backed option.
4. Add contract tests for selection, configuration validation, permissions, and
   failure behavior.

ASR, TTS and VAD expose explicitly configured external JSONL implementations
through the same catalog. Their device permissions and explicit start/stop
controls are owned by `AudioRuntime`. Memory exposes SQLite and external JSONL
implementations; its category allowlist and redacted audit events are owned by
`MemoryRuntime`. Vision exposes an explicitly configured external JSONL
implementation; source permissions and redacted observation events are owned
by `VisionRuntime`. Deterministic doubles are test-only fixtures and never
appear in the production catalog.
Avatar still deliberately includes `none` and preview implementations. The
tool entry includes an approval-gated external-process implementation whose
path and fixed arguments are configured in the module form.

An approved manifest declaring `llm` is registered as a provider-backed module
implementation at runtime. Its launcher remains owned by `PluginCatalog`, and
the provider rechecks approval, manifest hash, entrypoint hash, and launcher
before every chat request. Provider-specific values from `config_schema` are
passed in the JSONL request; launcher paths are never stored in portable
snapshots.

## 相关文档

- [Provider profiles](provider-profiles.md)
- [Manifest](manifest.md)
- [Protocol](protocol.md)
