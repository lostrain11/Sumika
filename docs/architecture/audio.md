# Audio providers and runtime

ASR, TTS and VAD are separate capability contracts. They are registered in
`AudioProviderRegistry`, selected through `ModuleCatalog`, and started only by
the permission-gated `AudioRuntime`. The Python core never opens an audio
device. The current browser/Tauri frontend bridge captures a short microphone
recording only after ASR is enabled, configured, started, and the user has
approved microphone access.

## Chat microphone bridge

The chat voice button is intentionally inert while ASR is not running: it
shows the module setup guidance and does not call `getUserMedia`. Once ASR is
running, the frontend:

1. requests a mono microphone stream with browser echo cancellation and noise
   suppression;
2. keeps `MediaRecorder` chunks in memory for at most 30 seconds;
3. decodes the browser container with `AudioContext`, mixes channels to mono,
   resamples to 16 kHz, and encodes signed 16-bit PCM in a WAV container;
4. sends that in-memory WAV as `audio_base64` to `audio.asr.transcribe`;
5. places returned text into the composer without sending it automatically.

Stopping the recording immediately releases its media tracks. Leaving the
chat page discards an unfinished recording. The WAV bytes are request-scoped:
they are not written to SQLite, event payloads, or logs. TTS playback and
camera/screen capture still require their own frontend bridges.

## Provider contracts

The Python interfaces are:

```text
ASRProvider.transcribe(ASRRequest) -> str
TTSProvider.synthesize(TTSRequest) -> TTSResult
VADProvider.detect(VADRequest) -> bool
```

Deterministic audio doubles for contract tests live under
`backend/tests/fixtures`; they are not exported by the production package.

## External software adapter

`CommandASRProvider`, `CommandTTSProvider` and `CommandVADProvider` run an
explicitly configured executable with an argument list, working directory and
timeout. They do not invoke a shell. One request is written to stdin as JSONL;
the process writes JSONL responses to stdout:

```json
{"type":"asr","audio_base64":"...","sample_rate":16000,"channels":1,"language":"zh-CN"}
{"type":"result","text":"recognized text"}
```

TTS returns `{"type":"audio","audio_base64":"...","content_type":"audio/wav"}`.
VAD returns `{"type":"speech","speech":true}`. An `error` response or a
non-zero/timeout process result fails the current call and is surfaced to the
caller. No process is started during module discovery or configuration saving.

## Permissions and lifecycle

The runtime persists only permission decisions (`unknown`, `granted`, or
`denied`) in `audio_permissions`. The following JSON-RPC methods are the only
runtime controls:

- `audio.status` and `GET /api/audio/status` expose permission and capability state.
- `audio.permission.set` records an explicit microphone or audio-output decision.
- `audio.start` / `audio.stop` control a selected ASR, TTS or VAD capability.
- `audio.asr.transcribe`, `audio.tts.synthesize` and `audio.vad.detect` invoke a
  started capability.

ASR and VAD require `microphone`; TTS requires `audio_output`. A module must be
enabled, have a selected available provider, and have all required permissions
granted before it can start. Disabling a module, changing its implementation,
or denying a required permission stops the active capability.

Raw audio is limited to the request lifetime and is never inserted into SQLite,
event payloads, or logs. Only lifecycle and permission changes are audited.

## 相关文档

- [Modules](modules.md)
- [Security](security.md)
- [Provider profiles](provider-profiles.md)
