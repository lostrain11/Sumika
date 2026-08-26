# UI source and license ledger

The current shell includes one separately tracked public Avatar asset. No
third-party UI code or icon is copied. The following projects are references
only unless a future entry records a specific compatible file and license
review.

| Source | Current use | Reuse status |
| --- | --- | --- |
| Sumika `src-tauri/icons/sumika-icon-transparent.png` and generated PNG/ICO sizes | current desktop application icon: transparent-background, enlarged pixel-art home scene | derived locally from the generated Sumika icon on 2026-08-24 by edge-connected background extraction and nearest-neighbor resizing; source pixel colors and internal shapes were preserved; alpha is used only for the exterior background; no API key or credential is stored in the repository; no third-party source material was intentionally supplied; Sumika-only asset unless the project owner confirms broader reuse terms |
| Sumika `src-tauri/icons/sumika-icon-sharp.png` and `sumika-icon-sharp.ico` | current desktop application icon with per-size pixel-sharp ICO frames | copied from the transparent icon's nearest-neighbor PNG sizes without resampling; custom ICO directory preserves exact 16/24/32/48/64/128/256px frames to avoid Windows smoothing; Sumika project asset |
| Sumika `src-tauri/icons/sumika-icon-generated.png` and generated PNG/ICO sizes | retained opaque icon fallback | generated on 2026-08-24 through the user-provided OpenAI-compatible image API using `gpt-image-2`; no API key or credential is stored in the repository; no third-party source material was intentionally supplied |
| Sumika `src-tauri/icons/sumika-icon-user-source.png` and generated PNG/ICO sizes | retained previous desktop application icon fallback: user-provided 1254x1254 warm pixel-art home scene with the Sumika character and companion | supplied by the project owner on 2026-08-24 and authorized for Sumika use; source SHA-256 `27E439EFD846A9013EF0B09D60E4675CFCF376EA2A2AE55A40D91023A07520DE`; generated locally with System.Drawing; no third-party source, author or redistribution license was provided; do not present it as an open-source asset or reuse it outside Sumika without confirming terms |
| Sumika `src-tauri/icons/sumika-icon.svg` and generated PNG/ICO sizes | retained previous icon fallback; not selected by the current Tauri bundle | Sumika project asset; locally authored SVG and rasterized derivatives generated 2026-08-24; no third-party source material or characters; no external license required |
| [AIRI](https://github.com/moeru-ai/airi) | overlay, status islands, settings and mobile connection patterns | study; review package license before copying |
| [Shinsekai `CharacterBasicSection.tsx` and `CharacterPersonalitySection.tsx`](https://github.com/RachelForster/Shinsekai/tree/main/frontend/src/features/character-editor) | Basic/Personality information architecture for the Sumika character editor | study-only behavior reference under Shinsekai's custom source-available license; no code, text, styles or assets copied |
| [N.E.K.O `character_fields.py` and `characters/zh-CN.json`](https://github.com/Project-N-E-K-O/N.E.K.O/tree/main/config) | separation of editable persona fields from reserved Avatar runtime fields | Apache-2.0 behavior/schema-boundary reference; Sumika uses its own field names, validation and context renderer; no code, prompts, character data or assets copied |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | minimal Live2D/pet UX reference | inspect repository license before reuse |
| [Super Agent Party](https://github.com/heshengtao/super-agent-party) | VRM/extension interaction reference | study; review AGPL and asset terms before reuse |
| [madjin/vrm-samples](https://github.com/madjin/vrm-samples) sample `AvatarSample_A.vrm` plus embedded thumbnail | bundled default VRM asset and local UI preview | VRoid Studio sample model conditions; pinned commit and hashes in `assets/avatars/README.md` |
| [pixiv/three-vrm](https://github.com/pixiv/three-vrm) sample `VRM1_Constraint_Twist_Sample.vrm` plus embedded thumbnail | archived VRM reference asset; not part of the active catalog | VRM Public License 1.0; archived under `deprecated/20260822T172058Z/` with hashes in `assets/avatars/README.md` |
| [three.js](https://github.com/mrdoob/three.js) npm package and [pixiv/three-vrm](https://github.com/pixiv/three-vrm) npm package | locally bundled VRM renderer in `frontend/public/vendor/sumika-vrm-viewer.js` | MIT; versions are pinned in `frontend/package-lock.json` |
| [N.E.K.O `vrm-cursor-follow.js`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/static/vrm/vrm-cursor-follow.js) | eye target, limited head/neck follow, smoothing and cleanup behavior | Apache-2.0 behavior reference; no code copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [N.E.K.O `vrm-animation.js`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/static/vrm/vrm-animation.js) | VRMA lifecycle and mixer cleanup comparison | Apache-2.0 behavior reference; no code or animation asset copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [N.E.K.O `cat-idle-state-machine-rules.md`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/docs/design/cat-idle-state-machine-rules.md) | idle/action interruption semantics for the future animation layer | Apache-2.0 documentation behavior reference; no text copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [N.E.K.O desktop pet surface](https://github.com/Project-N-E-K-O/N.E.K.O/tree/fb78210ada6727ac9c5b3cb0376e5014ac4b1650) | transparent Avatar surface, compact chat and hover controls | Apache-2.0 behavior reference; no code, model or animation asset copied; fixed commit `fb78210ada6727ac9c5b3cb0376e5014ac4b1650` |
| [CC Switch](https://github.com/farion1231/cc-switch) `src-tauri/src/deeplink/parser.rs`, `provider.rs`, `mod.rs`, `usage_script.rs` and `DeepLinkImportDialog.tsx` | versioned `ccswitch://v1/import` field mapping and compatibility-check behavior | MIT project; behavior and protocol reference only, no source copied; baseline `v3.20.0` / commit `5ca9459d50ea4beea6a81bbc509de6ec5b6b09ca` |
| [heshengtao/super-agent-party `static/js/vrm.js`](https://github.com/heshengtao/super-agent-party/blob/380ad8422bbe5767e31a70d853a3eb5bb747e4a5/static/js/vrm.js) | natural standing pose bone selection comparison | behavior reference only; no code or model copied; fixed commit `380ad8422bbe5767e31a70d853a3eb5bb747e4a5`; asset license not assumed |
| [pixiv/three-vrm-animation](https://github.com/pixiv/three-vrm-animation) npm package | optional `VrmaAdapter` in `frontend/src/vrm-viewer.js` | MIT; version pinned in `frontend/package-lock.json`; no VRMA asset bundled |
| [Ollama](https://github.com/ollama/ollama) Windows runtime | optional local OpenAI-compatible service managed only when the user runs `tools/setup-ollama.ps1` | use the official installer; runtime is not redistributed or installed during normal Sumika startup |
| [Qwen3](https://huggingface.co/Qwen/Qwen3-4B) `qwen3:4b` Ollama model | editable Ollama template example; downloaded only after explicit user selection | Qwen license terms apply to downloaded weights; Sumika does not bundle, install, or redistribute the model |
| [Tencent BrowserSkill](https://github.com/Tencent/BrowserSkill/tree/a004291848e8641400b973b8d612b4c4b74cdc90) CLI and `packages/dsh-plugin-browserskill` | optional BrowserSkill health/session bridge and DSH plugin boundary | MIT; fixed `dsh-plugin-v0.1.1`, extension `ext-v0.1.6`, CLI `cli-v0.1.10`; Sumika does not copy source, extension code, browser data, screenshots or logged-in profiles |

The current preview driver and CSS are original Sumika code. Any future
copied file must add its exact path, upstream revision, license, attribution
and modification note here before it enters the repository.

## Agent 与浏览器参考

- DeepSeek Harness: `https://github.com/deepseek-ai/deepseek-harness`, fixed
  commit `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`, MIT. Sumika 使用公开
  Web API 作为运行时适配目标，未复制 Core 源码。
- OpenAI Codex: `https://github.com/openai/codex`, fixed commit
  `4347f94d5539880e8583028a50a19df5b202d9fa`, Apache-2.0. 仅作 Agent loop、
  Plan、MCP、Skills、Subagents、审批和 App Server 生命周期参考。
- Tencent BrowserSkill: `https://github.com/tencent/BrowserSkill`, fixed
  commit `a004291848e8641400b973b8d612b4c4b74cdc90`, MIT. 首版通过公开 CLI
  和 DSH plugin 边界接入 BrowserRuntime；不复制 extension、插件或浏览器资源。

外部项目、插件和记忆系统榜单的固定版本、用途和检查日期另见
[`Evolution Knowledge Registry`](../integrations/evolution-knowledge-registry.json)。

## 相关文档

- [UI 参考地图](reference-map.md)
- [Avatar 资产与驱动](../architecture/avatar.md)
- [文档总入口](../README.md)
