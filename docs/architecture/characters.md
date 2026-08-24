# Character configuration

`Sumika` is the project name. Characters are independent persona and
presentation records; each record has its own user-facing name. The character
row is separate from sessions, module selections and Avatar model metadata.
`character.update` merges a supplied `persona` or `avatar` object into the
existing config so future extension fields survive older UI versions.

## Config shape

The first editor uses:

```json
{
  "language": "zh-CN",
  "persona": {
    "system_prompt": "",
    "greeting": ""
  },
  "avatar": {
    "position": "center",
    "opacity": 1,
    "scale": 1,
    "natural_pose": true,
    "look_at_enabled": true,
    "head_follow_enabled": true,
    "look_at_strength": 1.0,
    "head_follow_strength": 0.35
  }
}
```

`avatar_driver` and `avatar_model_id` remain owned by `AvatarManager` and are
changed through `avatar.select`. The presentation values only affect the
client renderer; they do not load or parse model binaries. `natural_pose` is a
reversible runtime bone adjustment. `look_at_enabled` drives
`vrm.lookAt.target` from pointer coordinates inside the stage, while
`head_follow_enabled` applies a slower, limited neck/head rotation after
`vrm.update()`. Both default to enabled and degrade to a static model when the
required VRM facilities are absent.

## Protocol and events

- `character.list` returns all character records.
- `character.create` creates a record with validated config.
- `character.update` changes the name and/or merged config.
- `character.changed` carries the updated character so other windows can
  refresh without polling.

Persona text is persisted as user configuration. The durable
`character.changed` event contains the updated character so other windows can
refresh; no other event promotes persona text to long-term memory.

## 相关文档

- [Avatar 资产与驱动](avatar.md)
- [Modules](modules.md)
- [长期记忆](memory.md)
