# Plugin manifest

The manifest is the install and audit boundary for a provider or tool. A
minimum manifest declares `id`, `version`, `capabilities`, and `entrypoint`.
It may also declare `config_schema`, `permissions`, `dependencies`,
`resource_requirements`, `runtime`, and `sdk_range`.

Third-party implementations are external processes in v0.1. The core only
starts an explicitly configured process and speaks JSONL over stdin/stdout.
Online catalogs, signature verification, dependency installation and sandbox
runners are later layers, not hidden behavior in the provider registry.

## Local discovery and approval

The Developer page can scan one or more absolute local directories (or a
specific `manifest.json`). Discovery walks only a bounded depth, skips common
cache/repository directories, rejects manifest and entrypoint symlinks, and
records the manifest SHA-256 plus validation errors in the local SQLite
catalog. It never imports the entrypoint, starts a process, installs
dependencies, or changes files in the plugin directory.

The JSON-RPC flow is:

```text
plugin.discover(paths)
        -> discovered / changed / invalid candidate
plugin.approve(candidate_id)
        -> re-read and hash-check manifest, then approved registration
plugin.configure(candidate_id, launcher)
        -> validate explicit executable, fixed args and entrypoint hash
plugin.run(candidate_id, input, approved=true)
        -> revalidate hashes, then one-shot JSONL tool process
plugin.revoke(candidate_id)
        -> revoked registration; original files remain untouched
```

Approval is a registration decision, not runtime activation. The Developer
page can separately save a launcher for an approved external provider or tool:
an absolute executable, fixed argument list containing the manifest entrypoint,
optional working directory, and bounded timeout. Saving this configuration
never starts the process. An approved plugin declaring `llm`, `asr`, `tts`,
`vad`, `memory`, or `vision` is exposed as a normal provider-backed
implementation in the Modules page. Each request revalidates the manifest and
entrypoint SHA-256 before using the no-shell JSONL provider boundary; audio and
vision runtimes also stop active sessions if the selected provider is revoked or
becomes invalid. A `plugin.run` tool call still needs explicit per-call
approval in addition to plugin approval. Capabilities outside these adapters
remain registration-only until a capability-specific adapter is added. Plugin
registrations are intentionally excluded from portable snapshots because their
paths are machine-specific; rediscovering the source directory is the recovery
operation.

## 相关文档

- [Modules](modules.md)
- [Tools](tools.md)
- [Security](security.md)
