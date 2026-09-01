# Provider profiles

Provider profiles are user-owned connection records. They keep connection
configuration separate from the capability module and from the runtime
adapter, so one `openai-compatible` adapter can serve Ollama, a local server,
or several remote endpoints without duplicating implementation code.

New workspaces contain no automatic profile. Templates are editable starting
points only: selecting Ollama does not install it, and its `qwen3:4b` value
does not download a model. The `智谱 BigModel` template likewise only offers
the model IDs `glm-4.5-air`, `glm-4.7`, and `glm-4.6v`; it never contains a
credential or claims that a model is enabled. Activation always remains a
separate, explicit, health-checked action.

## Stored shape

The `provider_profiles` SQLite table stores:

- a stable profile id and display name;
- the adapter and template ids;
- processing location (`auto`, `local`, or `cloud`);
- one current Base URL plus optional alternate URLs;
- selected model, an authenticated model catalogue with per-model enablement,
  timeout, non-sensitive headers, organization/project and declarative
  usage-query metadata;
- optional pricing source, billing group and user-entered cash conversion;
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

Health checks first request the adapter's model catalogue without spending a
chat request. Some gateways (including compatible relays) do not expose
`GET /models`; an explicit user-triggered `测试连接` or activation may then
send one bounded `max_tokens=1` request to `/chat/completions`. Passive page
refreshes never perform that probe, and a failed probe never falls back to a
fake provider.

One profile owns one protected credential but may expose multiple enabled
models. An authenticated `/v1/models` refresh merges model IDs and preserves
the user's enablement choices; each enabled model becomes a separate Route and
may run in parallel subject to the provider's rate limits. A `429` is handled
as bounded backoff or partial failure and never requires copying the API key.

Pricing is isolated by profile, model and billing group. Direct official,
New API, PinAI and manual sources produce `route-pricing/v1` snapshots. The UI
keeps provider-side credits separate from the user's cash conversion; an
unknown group, unsupported dynamic expression or missing conversion remains
unknown instead of inheriting an official price.

Managed DSH MCP connections use the same `CredentialStore` boundary but a
separate hashed reference namespace. Their Preset rows contain only a fixed
`process.env` expression and non-sensitive target metadata. A new or rotated
MCP secret remains disabled until a desktop restart injects its new environment
reference; neither Provider profiles nor MCP configuration expose a read-back
API.

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
`.models`, `.model.select`, `.health`, `.activate`, `.archive`, and `.restore`.
`provider.import.preview`
parses without persistence; `provider.import.save` writes the reviewed result
as a draft. Activation always performs a fresh health check and updates the
module's `profile_id`.

`GET /api/provider-profiles`, `/api/provider-templates`, and
`GET /api/privacy` are read-only browser views. The privacy label is the
aggregate of enabled modules and their resolved connection locations, so a
single cloud profile produces `云端处理` and a mixture produces `混合处理`.

Provider profiles also appear in the read-only `capability-catalog/v1` projection
(`GET /api/capabilities`). The projection exposes the profile id, model and
health/auth/quota states needed for comparison, but never returns Base URL
secrets, credential values, paths or arbitrary headers. It is a view of the
profile and model-policy registries, not a second activation list; activation
continues through the Provider drawer and module state.

## 相关文档

- [Modules](modules.md)
- [CC Switch 兼容边界](../integrations/cc-switch.md)
- [Security](security.md)
