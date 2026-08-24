# Protocol v0.1

## HTTP commands

`POST /rpc` accepts JSON-RPC 2.0 requests. The first methods are:

```text
core.health
provider.profile.templates
provider.profile.list
provider.profile.get
provider.profile.save
provider.profile.health
provider.profile.activate
provider.profile.archive
provider.profile.restore
provider.import.preview
provider.import.save
integration.ccswitch.manifest
integration.ccswitch.check
provider.list
provider.health
session.list
session.create
session.messages
character.list
character.create
character.update
event.list
snapshot.list
snapshot.get
snapshot.create
snapshot.diff
snapshot.restore
snapshot.export
snapshot.import
avatar.models
avatar.import
avatar.refresh
avatar.unregister
avatar.select
avatar.state
chat.send
task.list
task.runner.list
task.run
task.get
task.create
task.update
module.list
module.update
audio.status
audio.permission.set
audio.start
audio.stop
audio.asr.transcribe
audio.tts.synthesize
audio.vad.detect
memory.status
memory.list
memory.search
memory.add
memory.delete
vision.status
vision.permission.set
vision.start
vision.stop
vision.observe
tool.run
plugin.list
plugin.discover
plugin.approve
plugin.configure
plugin.run
plugin.revoke
```

`POST /api/chat` is a small browser convenience wrapper around `chat.send`.

Snapshot export returns a `sumika.snapshot` JSON package with a SHA-256
checksum. Import only validates and stores a new snapshot; it never restores
state implicitly. The package is not encrypted and can contain chat, persona
or memory data, so the UI labels it as a sensitive local file.

## Event stream

`GET /ws/events` is a local WebSocket text stream. Each event contains:

```json
{
  "event_id": "...",
  "correlation_id": "...",
  "session_id": "default",
  "character_id": "sumika",
  "timestamp": "2026-08-21T00:00:00+00:00",
  "event_type": "llm.token",
  "payload": {"provider_id": "openai-compatible", "text": "..."}
}
```

Commands and events are separate on purpose: HTTP gives request/response
errors and cancellation points; the WebSocket carries token and status flow.

`plugin.configure` stores an explicit tool launcher only after the candidate is
approved. `plugin.run` requires `approved: true` on every call and rechecks the
manifest and entrypoint hashes before delegating to the one-shot JSONL tool
runner. Configuration and approval do not activate a process.

Plugin discovery accepts absolute local directory or `manifest.json` paths.
`plugin.discover` only validates and hashes manifests; `plugin.approve` and
`plugin.revoke` change the local registration state. These methods do not load
entrypoints, execute processes, or install dependencies. An approved manifest
may register an unconfigured capability adapter in the local provider catalog,
but no external process starts until a launcher is configured and the selected
module is used; every provider request rechecks approval and file hashes.

## 相关文档

- [架构索引](README.md)
- [Modules](modules.md)
- [调试与恢复](debugging.md)
