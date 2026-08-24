# Provider profiles

Provider profiles are user-owned connection records. They keep connection
configuration separate from the capability module and from the runtime
adapter, so one `openai-compatible` adapter can serve Ollama, a local server,
or several remote endpoints without duplicating implementation code.

New workspaces contain no automatic profile. Templates are editable starting
points only: selecting Ollama does not install it, and its `qwen3:4b` value
does not download a model. Activation always remains a separate, explicit
health-checked action.

## Stored shape

The `provider_profiles` SQLite table stores:

- a stable profile id and display name;
- the adapter and template ids;
- processing location (`auto`, `local`, or `cloud`);
- one current Base URL plus optional alternate URLs;
- model, timeout, non-sensitive headers, organization/project and declarative
  usage-query metadata;
- lifecycle state (`draft`, `available`, `unavailable`, or `archived`);
- source metadata and `last_used_at`.

The module setting stores only `config.profile_id`. It never stores an API key
or a provider-specific secret. A saved edit returns to `unavailable` until a
real health check succeeds. A draft may be saved for later completion but
cannot be activated.

## Credentials

API keys and sensitive request headers are written through `CredentialStore`.
On Windows the production store is Windows Credential Manager under a
Sumika-specific target; tests use an in-memory store. SQLite, events, snapshots
and the public RPC representation contain only the opaque credential
reference, secret field names and `has_secrets: true`.

macOS Keychain and Linux Secret Service adapters are not implemented yet.
Those platforms fail closed when a profile attempts to persist a non-empty
secret; unauthenticated local providers remain available.

The UI never reads a secret back. An empty password field preserves the current
secret; an explicit clear checkbox removes it. Imported unknown sensitive
fields remain inert credential entries named `source:<field>` until a future
adapter is explicitly implemented.

## UI contract

The Modules page is the only place that enables or disables LLM. Its
`实现方式` picker shows the current healthy profile when collapsed. Expanded
rows are grouped into healthy and pending profiles and ordered by backend
`last_used_at`/`updated_at`; the final row opens the CC Switch-compatible
configuration drawer. The drawer supports:

1. minimum fields: name, template, current Base URL and model;
2. remote authentication through the secret field;
3. optional alternate URLs, processing location and advanced JSON fields;
4. `保存草稿`, `测试连接`, and `保存并启用` actions.

Alternate URLs are stored for user selection but are not silently retried.
Archive is recoverable and removes a profile from the picker; Developer can
restore it as a draft. The active profile cannot be archived until another
profile is activated.

## RPCs

The core exposes `provider.profile.templates`, `.list`, `.get`, `.save`,
`.health`, `.activate`, `.archive`, and `.restore`. `provider.import.preview`
parses without persistence; `provider.import.save` writes the reviewed result
as a draft. Activation always performs a fresh health check and updates the
module's `profile_id`.

`GET /api/provider-profiles`, `/api/provider-templates`, and
`GET /api/privacy` are read-only browser views. The privacy label is the
aggregate of enabled modules and their resolved connection locations, so a
single cloud profile produces `云端处理` and a mixture produces `混合处理`.

## 相关文档

- [Modules](modules.md)
- [CC Switch 兼容边界](../integrations/cc-switch.md)
- [Security](security.md)
