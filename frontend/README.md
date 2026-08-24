# Sumika frontend

The browser shell is still served directly by the Python core, while the
bundled VRM adapter uses Three.js and `@pixiv/three-vrm`. Start the core and
open its root URL for the local-first preview. `main.js` implements the first
information architecture and talks to the core through HTTP JSON-RPC-compatible
endpoints plus the event WebSocket.

When the renderer source or its dependencies change, rebuild the browser
bundle from this directory:

```powershell
npm run build:vrm
```

The UI keeps the registered thumbnail visible until the local WebGL renderer
is ready, and falls back to that thumbnail if the browser cannot create WebGL.

`src/main.ts` records the Vue migration boundary. The current pages remain in
`main.js` so the Python core can serve a zero-build shell; a future Vue
migration must preserve the routes, event envelope, provider configuration
contract, and the `data-vrm-*` renderer state attributes.

The structure intentionally follows existing projects rather than inventing a
new product pattern. See `../docs/ui/reference-map.md` for the source map and
license boundary.
