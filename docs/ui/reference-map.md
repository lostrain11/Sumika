# UI reference map

The first UI uses existing projects as interaction references. It does not
copy a new visual language from scratch.

| Sumika surface | Primary reference | What is being learned |
| --- | --- | --- |
| Beginner guide | Sumika shell composition | workspace map, control-surface explanations and the first-use flow; original Sumika content |
| Desktop Avatar / overlay | [AIRI stage renderer](https://github.com/moeru-ai/airi/tree/main/apps/stage-tamagotchi/src/renderer) | overlay windows, status islands, controls and settings routes |
| Mobile connection | [AIRI pocket](https://github.com/moeru-ai/airi/tree/main/apps/stage-pocket/src) | permission cards and host connection settings |
| Chat and shell | [Shinsekai chat-stage](https://github.com/RachelForster/Shinsekai/tree/main/frontend/src/features/chat-stage) | stage controls, history, input layer and collapsible overlays |
| Character editor | [Shinsekai character-editor](https://github.com/RachelForster/Shinsekai/tree/main/frontend/src/features/character-editor), [N.E.K.O character schema](https://github.com/Project-N-E-K-O/N.E.K.O/blob/main/config/character_fields.py) | Basic/Personality section boundaries and separation of persona data from reserved Avatar runtime controls; behavior/information architecture only |
| Provider/modules | [Shinsekai API/plugin features](https://github.com/RachelForster/Shinsekai/tree/main/frontend/src/features) | schema forms, plugin catalog/detail and provider configuration |
| Task and Avatar state | [N.E.K.O. design docs](https://github.com/Project-N-E-K-O/N.E.K.O/tree/main/docs/design) | HUD, floating panel and status visibility |
| Beginner Live2D flow | [Open-LLM-VTuber assets](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/tree/main/assets) | app/pet mode framing and model presentation |
| VRM natural pose and cursor follow | [N.E.K.O `vrm-cursor-follow.js`](https://github.com/Project-N-E-K-O/N.E.K.O/blob/fb78210ada6727ac9c5b3cb0376e5014ac4b1650/static/vrm/vrm-cursor-follow.js), [Super Agent Party `vrm.js`](https://github.com/heshengtao/super-agent-party/blob/380ad8422bbe5767e31a70d853a3eb5bb747e4a5/static/js/vrm.js) | behavior and lifecycle reference only; Sumika implementation is separate |

## License boundary

Shinsekai is a study reference only unless a specific asset is confirmed
compatible with Sumika's intended license. N.E.K.O, AIRI and other projects
also contain third-party models, SDKs and icons with separate terms. The
repository must keep a source/asset/license ledger before copying anything.

The current shell uses original CSS and reference-derived information
architecture. The active browser path now loads the bundled `AvatarSample_A.vrm`
through the local VRM renderer; Live2D remains a future renderer and is not
listed as a selectable placeholder provider.

The N.E.K.O cursor-follow reference is Apache-2.0 at the repository level.
Sumika does not copy the file; it records the eye-target/head-additive behavior
and cleanup boundary in `frontend/src/vrm-viewer.js`. Super Agent Party is used
only to compare natural-pose bone choices; its source and asset license must be
reviewed before any direct reuse.

## 相关文档

- [文档总入口](../README.md)
- [Avatar 资产与驱动](../architecture/avatar.md)
- [来源与许可证台账](license-ledger.md)
