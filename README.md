# Sumika

[中文版](README_zh.md)

Sumika is a local-first, modular foundation for a desktop private companion.

## Platform support

| Platform | Python core and browser UI | Tauri desktop shell |
| --- | --- | --- |
| Windows | Supported | Supported |
| macOS | Supported command; see credential limitation below | Experimental |
| Linux | Supported command; see credential limitation below | Experimental |

Python 3.11 or newer is required on every platform. Sumika starts with LLM
disabled and no provider profile. Normal startup never installs Ollama, starts
a model service, or downloads model weights.

## Windows

Run the browser UI from PowerShell at the repository root:

```powershell
.\tools\run_core.ps1
```

Open [http://127.0.0.1:8770/](http://127.0.0.1:8770/). Browser data is stored
in `.sumika`. To select another Python executable:

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run_core.ps1
```

For the desktop development shell, install frontend dependencies once and then
start Tauri:

```powershell
npm install --prefix frontend
.\tools\run-desktop.ps1
```

The desktop core listens on `127.0.0.1:8771` and stores its data in
`.sumika-desktop`. Use `-NoBuild` after a successful frontend build. Desktop
development also requires Rust with the MSVC target and the Windows C++ build
tools. The `.sh` files are legacy Windows Git Bash compatibility wrappers;
Git Bash is not a prerequisite or the documented Windows startup path.

## macOS

The currently supported entry point is the Python core and browser UI:

```bash
PYTHONPATH=backend/src python3 -m sumika_core \
  --host 127.0.0.1 --port 8770 --data-dir .sumika
```

Then open [http://127.0.0.1:8770/](http://127.0.0.1:8770/). Native
`tools/run_core.sh` and `tools/run-desktop.sh` launchers are reserved but
not implemented. The Tauri shell is experimental; contributors may try it
with Node.js, Rust, Xcode Command Line Tools, and the platform WebView:

```bash
npm install --prefix frontend
npm --prefix frontend run build
SUMIKA_PYTHON="$(command -v python3)" npm --prefix frontend run tauri:dev
```

## Linux

The currently supported entry point is the Python core and browser UI:

```bash
PYTHONPATH=backend/src python3 -m sumika_core \
  --host 127.0.0.1 --port 8770 --data-dir .sumika
```

Then open [http://127.0.0.1:8770/](http://127.0.0.1:8770/). Native
`tools/run_core.sh` and `tools/run-desktop.sh` launchers are reserved but
not implemented. The experimental Tauri path requires Node.js, Rust, a C
toolchain, and the WebKitGTK/system packages listed in the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/):

```bash
npm install --prefix frontend
npm --prefix frontend run build
SUMIKA_PYTHON="$(command -v python3)" npm --prefix frontend run tauri:dev
```

macOS and Linux currently fail closed when a provider profile needs a saved
API key because an approved Keychain/Secret Service adapter has not been
implemented. Local endpoints without authentication remain usable.

## Configure a model

Open **Modules**, choose **Custom connection**, select a real template, enter
the endpoint and model, test the connection, and explicitly enable it. Ollama
is optional. Install it yourself if selected; after choosing a model, the
Windows-only helper can start/check Ollama and pull that explicit model:

```powershell
.\tools\setup-ollama.ps1 -Model 'qwen3:4b'
```

`qwen3:4b` is an editable example in the Ollama template, not a default
installation. The helper supports an explicit model cache through
`-ModelsDir` or `SUMIKA_OLLAMA_MODELS`.

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

To let the Tauri shell supervise an already installed DSH executable, opt in
explicitly:

```powershell
$env:SUMIKA_DSH_EXECUTABLE = 'D:\Tools\DeepSeekHarness\0.1.1-rc.2\node_modules\.bin\dsh.cmd'
$env:SUMIKA_DSH_AUTOSTART = '1'
.\tools\run-desktop.ps1
```

If the pinned runtime is not installed yet, explicitly run:

```powershell
.\tools\setup-dsh.ps1 -Proxy 'http://127.0.0.1:6064'
```

The helper writes only to `D:\Tools\DeepSeekHarness\0.1.1-rc.2`; it does not
change `PATH` or the global DSH installation. Use the returned executable path
for `SUMIKA_DSH_EXECUTABLE`. The desktop shell uses
`.sumika-desktop\dsh-profile` as the isolated `DSH_HOME`.

The shell writes DSH lifecycle output to `.sumika-desktop/logs/dsh.log` and
uses `.sumika-desktop/dsh-profile` as `DSH_HOME`. Without both settings, DSH is
not started; the Agent page can still connect to an externally started
`SUMIKA_DSH_ENDPOINT`.

## Core capabilities

The first core uses only the Python standard library. It provides an
OpenAI-compatible provider backed by Ollama or another real endpoint, an
external JSONL process boundary, SQLite sessions/events/snapshots, JSON-RPC
commands, and a WebSocket event stream. It also includes an approval-gated
external tool JSONL boundary.

New workspaces configure OpenAI-compatible endpoints through Provider profiles.
`SUMIKA_OPENAI_BASE_URL`, `SUMIKA_OPENAI_MODEL`, and
`SUMIKA_OPENAI_API_KEY` remain migration inputs for an explicitly enabled
legacy configuration; they never create or enable a profile in a new
workspace. `SUMIKA_COMMAND_PROVIDER` can explicitly register an external
command adapter.

The production provider catalog never registers Fake providers. Deterministic
test doubles live only in `backend/tests/fixtures` and are injected explicitly
by tests.

The optional **Agent** page uses a fixed DeepSeek Harness Web API target
(`0.1.1-rc.2`, default `http://127.0.0.1:3080`). Sumika keeps this runtime in an
isolated profile and fails closed when it is not running; it never installs or
modifies a user's global DSH. Plan, Skills, MCP, Subagents, approvals and
streaming events are exposed through the adapter as they become available.
The current session can export DSH's original session-log ZIP, while diff cards
show only a bounded file summary rather than raw patches. DSH does not yet
expose an independent rollback RPC in the pinned Web API.
The same page shows the BrowserSkill policy companion. The first browser slice
only records isolated profiles, approvals, manual takeover and download
quarantine; it does not control global desktop input.

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
