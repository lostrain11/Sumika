# Long-term memory

Long-term memory is an opt-in module, separate from chat sessions and
character configuration. It is disabled on first run. Enabling the module and
selecting a provider are both required before a read or write is allowed.

## Provider boundary

`MemoryProvider` exposes four operations:

```text
list_memories(character_id, category?, query?, limit?) -> records
add_memory(...) -> record
delete_memory(memory_id) -> bool
```

The core registers two real implementations:

- `sqlite-reference`: persistent local records in the versioned SQLite store;
- `external-memory`: an explicitly configured executable using JSONL stdin/stdout.

Test-only in-memory doubles are kept under `backend/tests/fixtures` and are
injected explicitly by unit tests.

The external request types are `memory.list`, `memory.add` and
`memory.delete`. The executable path, argument list, working directory and
timeout are schema-driven module configuration. No process starts while the
module list is being read or a configuration is saved.

## Policy boundary

The module configuration contains an allowlist of categories. The default
allowlist is `preferences`; a write to any other category is rejected. Records
are scoped to an existing character and have a bounded category, source,
metadata and content size. Selecting `none` or disabling the module prevents
provider access.

## Audit and privacy

SQLite stores the record body, metadata, category, source and timestamps in a
dedicated `memories` table. Session messages are never silently promoted to
long-term memory. `memory.created` events contain the record identity and a
SHA-256/content-length summary, not the body. `memory.deleted` contains only the
record ID. This keeps the event log useful for audit without creating a second
copy of sensitive memory content.

The History page shows memories for the selected character and exposes
explicit add/delete actions. When the module is disabled, it does not request
the memory endpoint and displays an opt-in state instead.

## 相关文档

- [Modules](modules.md)
- [Characters](characters.md)
- [Security](security.md)
