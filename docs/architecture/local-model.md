# Local model runtime

The first real chat backend is an OpenAI-compatible provider pointed at a
local Ollama service. `tools/setup-ollama.ps1` performs an idempotent check:
it finds the official Ollama executable, reuses a healthy service, starts one
only when needed, verifies the selected model, and performs a short warmup so
the first chat does not pay the full model-load delay.

The default model is `qwen3:4b`. A custom cache path can be passed with
`-OllamaModelsDir` or `SUMIKA_OLLAMA_MODELS`; it is never copied into the
repository. Downloads use an optional command-scoped proxy from
`SUMIKA_DOWNLOAD_PROXY`, and the script restores the caller's proxy
environment afterwards. Sumika does not alter system proxy, TUN, mode, or
node settings.

For a deliberately managed service, run the setup check with
`-SkipPull -NoWarmup`; the normal `run_core` and desktop wrappers keep the
warmup enabled so a cold first chat is less surprising.

The provider uses Ollama's OpenAI endpoint with `think=low`. Qwen3 reasoning
deltas are discarded at the provider boundary, while visible answer deltas are
streamed to the UI. A small token floor gives hidden reasoning enough room to
finish without exposing the chain of thought. If Ollama is unavailable, the
provider reports `unconfigured` or `error`; it never falls back to a fake
response.

An 8B model is not the default on the current 32 GB / approximately 4 GB VRAM
machine: it consumes more memory and increases first-run latency. Users can
select another Ollama tag with `-Model` after confirming its size and license,
for example:

```powershell
.\tools\run-desktop.ps1 -Model qwen3:8b
```

## 相关文档

- [Provider profiles](provider-profiles.md)
- [Desktop shell](desktop-shell.md)
- [根目录快速开始](../../README.md)
