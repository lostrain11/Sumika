# UI source and license ledger

The current shell includes one separately tracked public Avatar asset. No
third-party UI code or icon is copied. The following projects are references
only unless a future entry records a specific compatible file and license
review.

| Source | Current use | Reuse status |
| --- | --- | --- |
| [AIRI](https://github.com/moeru-ai/airi) | overlay, status islands, settings and mobile connection patterns | study; review package license before copying |
| [Shinsekai](https://github.com/RachelForster/Shinsekai) | chat, character, provider and plugin information architecture | study only by default; custom source-available license |
| [N.E.K.O.](https://github.com/Project-N-E-K-O/N.E.K.O) | Avatar/task/memory design references | review Apache core and third-party assets separately |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | minimal Live2D/pet UX reference | inspect repository license before reuse |
| [Super Agent Party](https://github.com/heshengtao/super-agent-party) | VRM/extension interaction reference | study; review AGPL and asset terms before reuse |
| [madjin/vrm-samples](https://github.com/madjin/vrm-samples) sample `AvatarSample_A.vrm` plus embedded thumbnail | bundled default VRM asset and local UI preview | VRoid Studio sample model conditions; pinned commit and hashes in `assets/avatars/README.md` |
| [pixiv/three-vrm](https://github.com/pixiv/three-vrm) sample `VRM1_Constraint_Twist_Sample.vrm` plus embedded thumbnail | archived VRM reference asset; not part of the active catalog | VRM Public License 1.0; archived under `deprecated/20260822T172058Z/` with hashes in `assets/avatars/README.md` |
| [three.js](https://github.com/mrdoob/three.js) npm package and [pixiv/three-vrm](https://github.com/pixiv/three-vrm) npm package | locally bundled VRM renderer in `frontend/public/vendor/sumika-vrm-viewer.js` | MIT; versions are pinned in `frontend/package-lock.json` |
| [N.E.K.O `vrm-cursor-follow.js`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/static/vrm/vrm-cursor-follow.js) | eye target, limited head/neck follow, smoothing and cleanup behavior | Apache-2.0 behavior reference; no code copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [N.E.K.O `vrm-animation.js`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/static/vrm/vrm-animation.js) | VRMA lifecycle and mixer cleanup comparison | Apache-2.0 behavior reference; no code or animation asset copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [N.E.K.O `cat-idle-state-machine-rules.md`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/docs/design/cat-idle-state-machine-rules.md) | idle/action interruption semantics for the future animation layer | Apache-2.0 documentation behavior reference; no text copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [CC Switch](https://github.com/farion1231/cc-switch) `src-tauri/src/deeplink/parser.rs`, `provider.rs`, `mod.rs`, `usage_script.rs` and `DeepLinkImportDialog.tsx` | versioned `ccswitch://v1/import` field mapping and compatibility-check behavior | MIT project; behavior and protocol reference only, no source copied; baseline `v3.20.0` / commit `5ca9459d50ea4beea6a81bbc509de6ec5b6b09ca` |
| [heshengtao/super-agent-party `static/js/vrm.js`](https://github.com/heshengtao/super-agent-party/blob/380ad8422bbe5767e31a70d853a3eb5bb747e4a5/static/js/vrm.js) | natural standing pose bone selection comparison | behavior reference only; no code or model copied; fixed commit `380ad8422bbe5767e31a70d853a3eb5bb747e4a5`; asset license not assumed |
| [pixiv/three-vrm-animation](https://github.com/pixiv/three-vrm-animation) npm package | optional `VrmaAdapter` in `frontend/src/vrm-viewer.js` | MIT; version pinned in `frontend/package-lock.json`; no VRMA asset bundled |
| [Ollama](https://github.com/ollama/ollama) Windows runtime | optional local OpenAI-compatible service managed only when the user runs `tools/setup-ollama.ps1` | use the official installer; runtime is not redistributed or installed during normal Sumika startup |
| [Qwen3](https://huggingface.co/Qwen/Qwen3-4B) `qwen3:4b` Ollama model | editable Ollama template example; downloaded only after explicit user selection | Qwen license terms apply to downloaded weights; Sumika does not bundle, install, or redistribute the model |

The current preview driver and CSS are original Sumika code. Any future
copied file must add its exact path, upstream revision, license, attribution
and modification note here before it enters the repository.

## 相关文档

- [UI 参考地图](reference-map.md)
- [Avatar 资产与驱动](../architecture/avatar.md)
- [文档总入口](../README.md)
