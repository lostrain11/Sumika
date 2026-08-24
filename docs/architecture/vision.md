# Vision providers and runtime

Vision is an opt-in capability for one controlled screen or camera
observation. The core does not open a device. A future Tauri bridge captures a
single frame after an explicit permission and source start, then supplies the
bytes to `VisionRuntime` for the lifetime of one request.

## Provider contract

The Python boundary is:

```text
VisionProvider.summarize(VisionRequest) -> VisionResult
```

The request contains `source` (`screen` or `camera`), an in-memory image,
MIME type and an optional prompt. The result contains a summary string. The
core registers one real implementation:

- `external-vision`: an explicitly configured executable using one JSONL
  request per observation.

Deterministic vision doubles are kept under `backend/tests/fixtures` and are
injected explicitly by unit tests.

The external request is:

```json
{"type":"vision.observe","source":"screen","mime_type":"image/png","image_base64":"...","prompt":null}
```

It must return `{"type":"result","summary":"..."}` (or a `type` of
`summary`). The process is started only during an observation, never while the
module catalog or configuration form is being read.

## Permissions and lifecycle

`VisionRuntime` persists only `screen.read` and `camera.read` decisions in the
versioned `vision_permissions` table. The module must be enabled, a provider
must be selected and available, the source permission must be granted, and the
source must be explicitly started before `vision.observe` is accepted.

The first protocol slice exposes:

```text
vision.status
vision.permission.set
vision.start
vision.stop
vision.observe
```

`GET /api/vision/status` is the read-only status view. Changing the module or
denying a permission reconciles and stops active sources.

## Privacy boundary

Raw image bytes are bounded and exist only for the provider call. They are not
written to SQLite, event payloads, logs or long-term memory. A successful
`vision.observed` event records only source, provider, MIME type, byte count,
content hash and summary length. The returned summary is delivered only to
the caller; automatic memory promotion and cloud routing are intentionally not
implemented until the visual sensitivity policy is frozen.

## 相关文档

- [Modules](modules.md)
- [Security](security.md)
- [长期记忆](memory.md)
