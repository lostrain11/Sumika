# Memory adapters

Long-term memory uses contract version `1`. The portable contract is in
`sumika_core.memory.contracts`; it does not import `Storage`, `ModuleCatalog`,
events, or any Sumika host implementation. `MemoryRuntime` is the Sumika host
adapter: it verifies that the stable `assistant_id` names an existing character,
reads module configuration, and emits redacted audit events.

## Identity and scope

`assistant_id` is the stable memory owner. In the current Sumika migration it
is exactly the existing `character_id`. Calls may carry the legacy
`character_id` only when it has the same value. Records returned by every
adapter are normalized to include both fields and must prove that they belong
to the requested assistant.

Memory records include `id`, `assistant_id`, `character_id`, `category`,
`content`, `source`, `metadata`, timestamps, `revision`, `status`, and
`is_active`. Version-one SQLite rows have no revision or lifecycle column, so
the SQLite adapter projects them as revision `1`, status `active`. An adapter
must explicitly opt into `legacy_record_compatibility` before omitted fields
are normalized at this migration boundary; future adapters must return them.
Inactive records are never returned to the runtime.

Delete is a scoped operation. The provider request receives `memory_id` and
`assistant_id`, and a successful response must contain:

```json
{
  "deleted": true,
  "memory_id": "memory-123",
  "assistant_id": "sumika",
  "status": "deleted"
}
```

Legacy providers which expose only `delete(memory_id) -> bool` are not granted
delete access by compatibility code. They remain usable only after implementing
the `scoped_delete` capability and the response above.

## Capabilities and extensions

Every provider declares `contract_version` and a capability set. Version one
requires `list`, `add`, and `delete`. `scoped_delete` is required before the
runtime will call deletion. Reserved extension capabilities are `update`,
`semantic_search`, `export`, `import`, `context_sources`, and `migration`.
`MemoryRuntime.context_sources()` is an explicit source interface; it returns
an unavailable error until a selected provider declares that capability. It
does not trigger automatic context injection or automatic memory writes.

The registry exposes the declaration through `describe(provider_id)`. It does
not compare similarity scores from different providers. Provider errors are
reduced to `Memory provider failed` at the runtime and health boundaries, so
command output, paths, tokens, and record bodies are not exposed in normal
error responses.

## Sumika adapters

`sqlite-reference` remains a manual local adapter. `external-memory` remains a
manual JSONL process adapter configured with a path, arguments, directory, and
timeout. Reading module settings or listing providers never starts the JSONL
process; a process runs only for an explicitly requested enabled operation.
Neither adapter performs automatic extraction, semantic recall, context
injection, export, import, or migration.

The JSONL request continues to include `character_id` for legacy adapters and
now also includes `assistant_id`. New JSONL implementations must use the
stable identity for `memory.list`, `memory.add`, and `memory.delete`, and must
return the scoped delete acknowledgement above.

Future DSH, HTTP, and MCP adapters implement `MemoryProvider` and register in
`MemoryProviderRegistry`. They must declare only capabilities they can enforce,
validate external identity ownership on every response, and implement export or
migration before claiming those capabilities. Migration must preserve body,
source, ownership, revision, and deletion state; rebuilding an index must not
resurrect a deleted record.

## Server integration required

`server.py` is intentionally not changed by this worktree. The host integration
must pass the same resolved identity to every call:

```python
assistant_id = str(params.get("assistant_id") or params.get("character_id") or "sumika")

self.memory.list(assistant_id=assistant_id, category=category, query=query, limit=limit)
self.memory.add(assistant_id=assistant_id, category=category, content=content, source=source, metadata=metadata)
self.memory.delete(memory_id, assistant_id=assistant_id)
```

For `memory.delete`, the public RPC and HTTP request must add `assistant_id`
(with same-value `character_id` compatibility). Leaving the existing unscoped
`self.memory.delete(memory_id)` call in place now returns an explicit argument
error instead of allowing a cross-assistant delete.
