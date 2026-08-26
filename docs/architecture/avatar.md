# Avatar assets and drivers

The Avatar boundary separates local model metadata from renderer execution.
`AvatarManager` registers an absolute `.model3.json`/`.model.json` Live2D
manifest or `.vrm` file, records its size and modification time, and binds the
asset to a character. Import never copies, parses, uploads, or executes the
file.

## API

- `avatar.models` / `GET /api/avatar/models` lists registered local assets.
- `avatar.ignored` / `GET /api/avatar/ignored` lists managed assets that the user
  chose to hide from automatic discovery, including whether the original file
  is currently available.
- `avatar.import` registers a model path after extension and file checks.
- `avatar.discover` scans the repository `assets/avatars` directory for new
  `.vrm`, `.model3.json`, and `.model.json` files. The core performs the same
  metadata-only scan at startup; it never removes registrations for files that
  later move or disappear. The bundled default sample remains governed by its
  one-time bootstrap marker, so unregistering it is respected on later launches.
  A user-unregistered file inside the managed directory is remembered as
  ignored until it is explicitly registered again.
- `avatar.restore` restores an available ignored managed path to the registration
  catalog. Restoration never binds the model to a character automatically.
- `avatar.refresh` rechecks the registered file and updates size, mtime, and
  availability metadata without loading the model binary.
- `avatar.unregister` removes a registration only when no character references
  it. It never deletes the original local file.
- `avatar.select` binds a model and matching `live2d` or `vrm` driver to a
  character; `driver_id: "none"` clears the binding.
- `avatar.state` returns the active character, driver, preview status, and
  selected model metadata.
- `GET /api/avatar/models/<model_id>/thumbnail` serves a hash-verified preview
  only for a registered asset that declares a repository-bundled thumbnail.
- `GET /api/avatar/models/<model_id>/file` serves a registered VRM binary to
  the local renderer only. It accepts VRM registrations, enforces the `.vrm`
  suffix and a 100 MiB limit, and never serves an arbitrary path.

The Characters page exposes an explicit scan for repository assets and a
model-file registration action. The Tauri desktop shell can provide a native
file picker; the browser preview cannot safely expose an absolute local path,
so it falls back to asking the user to paste one. The current `live2d` driver
remains metadata-only, while the VRM
driver is a browser-side Three.js adapter loaded from
`frontend/public/vendor/sumika-vrm-viewer.js`. It only receives a model through
the allow-listed local endpoint and does not upload the binary.

The renderer source is `frontend/src/vrm-viewer.js`; its pinned dependencies,
bundle command, and license entries are kept in the frontend package and
`docs/ui/license-ledger.md`. A future Cubism runtime can implement the same
`AvatarDriver` boundary without changing chat, storage, or character APIs.

The repository bundles `assets/avatars/AvatarSample_A.vrm` as the first-run demo
Avatar. On a new data store it is registered and bound to Sumika once, with its
source, commit, hash and VRoid sample-model terms recorded in the model row.
The former `VRM1_Constraint_Twist_Sample.vrm` is retained under
`deprecated/20260822T172058Z/assets/avatars/` for recovery, but is not part of
the active catalog. The bootstrap marker is kept outside user snapshots so
clearing or unregistering the model is respected on later launches. The browser
parses and renders the model only after the user-facing Avatar view is mounted.

Per-character presentation settings are stored in the character config and
returned by `avatar.state`:

- `position`, `opacity`, and `scale` control the stage layout;
- `natural_pose` applies a runtime-only relaxed standing pose to humanoid bones;
- `look_at_enabled` and `look_at_strength` control the eye target;
- `head_follow_enabled` and `head_follow_strength` control the slow additive
  neck/head pass;
- `idle_motion`, `auto_rotate`, and `rotation_speed` control the procedural
  idle layer.

The Characters page places these low-frequency controls under the collapsed
`高级设置 > 模型表现` section. The local model catalog stays outside that
section so asset import, inspection and character binding remain explicit
operations rather than renderer preferences.

All renderer effects are client-side hints. They do not grant access to model
files, modify model bytes, or change the selected renderer. Missing humanoid
bones or a missing `lookAt` manager result in a visible static fallback state.

The cursor-follow controller is intentionally stage-scoped and shared by the
main chat stage and the desktop pet overlay. Its pointer surface includes the
area around the model, so the gaze remains responsive without requiring the
pointer to sit on the renderer canvas. It smooths pointer coordinates, clamps
the eye/head response, and returns to the center after `pointerleave`. Its
algorithm and lifecycle are behavior references to N.E.K.O's
`static/vrm/vrm-cursor-follow.js`; Sumika does not copy that file.

The desktop pet overlay is transparent and intentionally renders only the
Avatar plus a compact chat composer. The model surface is the native window
drag handle; controls and text input opt out of dragging. Hover or keyboard
focus reveals the high-frequency open/hide controls. This follows the behavior
of N.E.K.O's desktop pet surface as an Apache-2.0 behavior reference, while the
Sumika implementation uses its own markup, CSS and Tauri API calls.

During procedural idle motion the controller uses a small reduced activity
weight so breathing and cursor response do not fight each other. A running
one-shot VRMA action temporarily reduces the weight further, then restores it
when the action finishes. This weight is renderer state only and is exposed as
`data-vrm-follow-weight` / `data-vrm-follow-activity` for diagnostics.

The optional `VrmaAdapter` uses `@pixiv/three-vrm-animation` to load a local
VRMA only when explicitly supplied. No `.vrma` or `.vrma.gz` asset is bundled.
`validateVrmaManifest` requires an SPDX license entry before a manifest can be
used, and the adapter restores `autoUpdateHumanBones` when stopped or destroyed.

Model paths are local user data and are shown for audit. A future import flow
may copy assets into a managed workspace, but that must be an explicit user
operation with license and size checks.

Registration changes are durable events (`avatar.model.imported`,
`avatar.model.refreshed`, `avatar.model.unregistered`, and
`avatar.model.restored`) so the developer
view can audit the asset lifecycle. Refresh rechecks whether the original file
still exists and whether its size or modification time changed; it does not
delete or copy the file. Unregister removes only the SQLite registration and
is intentionally blocked while any character is bound; clear every character
binding first.

## 相关文档

- [Characters](characters.md)
- [Modules](modules.md)
- [UI 参考地图](../ui/reference-map.md)
