# Sumika frontend

The browser shell is still served directly by the Python core, while the
bundled VRM adapter uses Three.js and `@pixiv/three-vrm`. Start the core and
open its root URL for the local-first preview. `main.js` owns Core requests,
events and runtime state; it injects these dependencies into the scene and
drawer renderers. The client still uses the existing HTTP/RPC and WebSocket contracts.

When the renderer source or its dependencies change, rebuild the browser
bundle from this directory:

```powershell
npm run build:vrm
```

The UI keeps the registered thumbnail visible until the local WebGL renderer
is ready, and falls back to that thumbnail if the browser cannot create WebGL.

`src/scene-shell.js` owns navigation; `scene-store.js` and `module-selector.js`
provide read-only display projections. `a-plus-scene-view.js` owns the active scene chrome,
and `page-view.js` dispatches to Characters, Modules, Settings, Workbench,
Agent, Web Workbench and Developer view factories. They do not make requests
or own another copy of runtime state. `view-state.js` preserves transient
disclosures and focus, with one keyboard handler per window.

The Python zero-build preview and Vite/Tauri bundle use the same ES modules
and the final `src/a-plus-layout.css` responsive layer. `src/main.ts` is only a compatibility
entrypoint; no second Vue application or navigation list is maintained.

The five text entries are Companion, Workbench, Capabilities, Characters and Settings.
The capability library adds, removes and sorts page cards without enabling services.
Settings > Connections and Permissions retains explicit module toggles, Provider
configuration and authorization. Missing OCR/translation implementations are disabled
library entries. Desktop portal windows remain separate from Agent browser routes.

Workspace and pet share one native window and VRM renderer. `display-state.js`
owns versioned appearance preferences; `home-room.js` provides the fixed original room.
Production builds also rebuild the VRM bundle. See `../docs/ui/a-plus-client.md`.

Validation (isolated in-memory Core, never the normal user data directory):

```powershell
npm run test:unit
npm run build
$env:SUMIKA_TEST_OUTPUT = 'D:/Caches/Sumika-ui-tests/latest'
npm run test:e2e
```

`test:e2e` starts and stops its own Core on a fresh loopback port with
`SUMIKA_AGENT_RUNTIME=none`; it does not use a running desktop instance.
Keep source and build writes separate from a browser acceptance run. For an
intermittent loading failure, rerun the affected test with `--trace=on` and
inspect its network/page errors instead of increasing timeouts without evidence.

`tests/ui-refactor.spec.js` covers module visibility/retry, keyboard navigation,
background persistence, pet/portal chrome and screenshots at four viewport sizes.
Native Tauri dragging, window switching and real external services require a
separate live acceptance; browser mocks are not evidence of those native behaviors.

The structure intentionally follows existing projects rather than inventing a
new product pattern. See `../docs/ui/reference-map.md` for the source map and
license boundary.
