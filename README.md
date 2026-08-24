# Sumika

[中文版](README_zh.md)

Sumika is a local-first, modular foundation for a desktop private companion.

## Run the browser slice

From the repository root. The wrapper uses `SUMIKA_PYTHON` when provided and
otherwise resolves `python` from `PATH`:

```powershell
.\tools\run_core.ps1
```

The startup wrapper checks the official Ollama installation and ensures that
the configured local model is present before starting Sumika. The default model
is `qwen3:4b`; an already-running Ollama service is reused. Pass
`-OllamaModelsDir` or set `SUMIKA_OLLAMA_MODELS` to use a custom model cache.
Use `-SkipModel` when you manage Ollama yourself. Git Bash can run
`./tools/run_core.sh` or `./tools/run-desktop.sh`; the wrappers translate
common `--skip-model` and `--model=...` options without changing the system
proxy.

If `bash` resolves to the Windows Subsystem for Linux shim, use the Git Bash
executable installed on your system instead.

To use another Python runtime:

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run_core.ps1
```

Then open [http://127.0.0.1:8770/](http://127.0.0.1:8770/). The browser slice
keeps its data in `.sumika`.

## Run the desktop development shell

Install dependencies once in `frontend`, then run the desktop shell from the
repository root:

```powershell
npm install --prefix frontend
.\tools\run-desktop.ps1
```

The wrapper resolves `python` from `PATH` by default. Set `SUMIKA_PYTHON` first
when Python is installed elsewhere:

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run-desktop.ps1
```

Git Bash can invoke the same script:

```bash
cd /path/to/Sumika
export SUMIKA_PYTHON='C:/Path/To/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/run-desktop.ps1
```

The script builds the frontend, starts the Tauri 2 window, and lets the window
manage its Python core child on `127.0.0.1:8771`. Desktop data is isolated in
`.sumika-desktop` and can run independently of the browser slice. Use
`-NoBuild` for faster repeat launches after a frontend build. The first local
run requires the Rust MSVC toolchain and Windows C++ build tools.

The main window can open an optional always-on-top desktop-pet mode. The model
area is a Tauri drag region, so the floating pet can be moved around the
desktop. A compact chat input sits below the model and uses the same selected
character, session, and provider as the main window. Provider, module,
permission, and task configuration stays in the main window.

Desktop lifecycle and Python startup diagnostics are written to
`.sumika-desktop/logs/desktop.log`; core boundary diagnostics are written to
`.sumika-desktop/logs/core.log`. The Developer page and
`GET /api/diagnostics` show the safe log location and runtime counters. The
Tauri shell also shows the supervised core PID, endpoint, and restart count;
see `docs/architecture/debugging.md`. Logs never contain API keys, chat text,
or raw visual/audio data.

The desktop core listens on `127.0.0.1:8771` by default, while the browser
preview uses `127.0.0.1:8770`.

## Core capabilities

The first core uses only the Python standard library. It provides an
OpenAI-compatible provider backed by Ollama or another real endpoint, an
external JSONL process boundary, SQLite sessions/events/snapshots, JSON-RPC
commands, and a WebSocket event stream. It also includes an approval-gated
external tool JSONL boundary.

Configure an OpenAI-compatible endpoint with:

- `SUMIKA_OPENAI_BASE_URL`
- `SUMIKA_OPENAI_MODEL`
- `SUMIKA_OPENAI_API_KEY`
- `SUMIKA_COMMAND_PROVIDER`

The production provider catalog never registers Fake providers. Deterministic
test doubles live only in `backend/tests/fixtures` and are injected explicitly
by tests.

The top `LLM` entry shows the current status and opens the Modules page. The
module card switch controls whether LLM is enabled; the implementation picker
only lists real providers. When disabled, the chat send button is unavailable
and the core rejects `chat.send` without producing a demo or Fake reply.

## Avatar

On first run, Sumika registers the bundled `AvatarSample_A.vrm` VRoid sample as
the default Avatar. Its source and license record live in
`assets/avatars/README.md`. The browser loads the `.vrm` through a local-only
file endpoint and renders it with the bundled Three.js/VRM adapter. A verified
thumbnail remains as the fallback when WebGL is unavailable.

The VRM viewer's natural standing pose, mouse gaze tracking, and head tracking
are runtime effects and never write to the model file. These features can be
disabled or adjusted per character on the Characters page. A VRMA adapter is
reserved, but the first release does not bundle animation assets; future
animation loading must use a local manifest, an independent license record,
and explicit user approval.

## Documentation

- [Documentation hub](docs/README.md): navigation for usage, architecture, developer interfaces, and integrations.
- [Status matrix](docs/status-matrix.md): the single source of truth for implemented, partial, and planned work.
- [Architecture index](docs/architecture/README.md): protocols, modules, providers, Avatar, tasks, and security boundaries.
- [UI reference and license ledger](docs/ui/reference-map.md): interaction references, sources, and reuse limits.
- [Third-party notices](THIRD_PARTY_NOTICES.md): included and permitted external components.

## Code layout and maintenance

- `backend/src/sumika_core`: core service.
- `frontend`: browser/Tauri client.
- `plugins/examples`: minimal external-process examples.

After adding or completing a capability, update the status matrix and its
topic documentation. Check documentation links and index coverage with:

```powershell
python tools/check_docs.py
```
