# Security boundary of the first slice

The first slice is intentionally local-only:

- the server defaults to `127.0.0.1`;
- the event WebSocket has no remote authentication yet;
- CORS is permissive because the only supported client is local;
- external programs are started only when an executable path is explicitly
  configured, the tools module is enabled, and the individual call is
  explicitly approved;
- command providers do not use a shell, so configured arguments are passed as
  separate process arguments;
- external tool calls use one-shot JSONL processes with fixed arguments,
  bounded input/output, and a timeout; raw input and output are not written to
  durable events.
- the external-process tool boundary is not an OS sandbox; do not configure
  untrusted programs until a sandboxed runner is available.
- plugin discovery and approval are metadata-only. Manifest and entrypoint
  symlinks are rejected, paths stay absolute and bounded, and approval rechecks
  the manifest hash. No plugin code is imported or executed by these actions;
  provider activation remains a separate boundary.
- tool plugin launchers are stored separately from the global tools module
  configuration. They require an absolute executable and fixed arguments that
  identify the manifest entrypoint; the manifest and entrypoint hashes are
  rechecked before each run. Configuration is inert, and each `plugin.run`
  still requires explicit approval.
- OpenAI-compatible profile keys and sensitive headers are stored through the
  Windows Credential Manager boundary; SQLite, events, snapshots and public
  RPC responses contain only an opaque reference and redacted field metadata.
  `SUMIKA_OPENAI_API_KEY` remains a one-time migration input for legacy
  installations and is not written to a provider config file.
- long-term memory is disabled by default; memory audit events contain only a
  content hash and length, not the stored body.
- snapshot export is an explicit, unencrypted JSON operation with a checksum;
  imported packages are validated and stored but never restored implicitly.
  Treat exported files as sensitive because they may contain conversations,
  persona settings and memory contents.

This is not a safe remote deployment profile. Before enabling LAN or Android
access, add pairing/authentication, origin checks, encrypted transport,
secret-store integration, permission scopes and an audit policy. Do not expose
the current server directly to a network.

The current visual provider slice accepts only an explicitly supplied in-memory
frame and never routes it to a cloud provider by itself. A future visual
pipeline must classify data locally before any cloud routing. Raw camera/screen
frames are not persisted by this slice.

## 相关文档

- [Provider profiles](provider-profiles.md)
- [Manifest](manifest.md)
- [调试与恢复](debugging.md)
