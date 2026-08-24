# Character configuration

`Sumika` is the project name. Characters are independent persona and
presentation records; each record has its own user-facing name. The character
row is separate from sessions, module selections and Avatar model metadata.
`character.update` merges a supplied `persona` or `avatar` object into the
existing config so future extension fields survive older UI versions.

## Editor structure

The Characters page follows the section boundaries studied in Shinsekai's
Basic/Personality editor and N.E.K.O's separation of persona records from model
runtime controls. Sumika uses its own markup and configuration contract.

One character form contains three native, collapsed-by-default sections:

- `角色身份` owns the display name, response language and identity/role;
- `人格设定` owns traits, relationship, speaking style, behavior, boundaries,
  response length, the custom system prompt and the first greeting;
- `高级设置 > 模型表现` owns renderer-only Avatar presentation controls.

Each collapsed summary exposes only a short status. It never renders the full
prompt. The model asset catalog remains a separate workflow because importing
or binding an asset is different from tuning its presentation.

## Config shape

The first editor uses:

```json
{
  "language": "zh-CN",
  "persona": {
    "identity": "",
    "traits": "",
    "relationship": "",
    "speaking_style": "",
    "behavior": "",
    "boundaries": "",
    "response_length": "balanced",
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

Persona text fields are optional strings. `response_length` accepts
`concise`, `balanced`, or `detailed` and defaults to `balanced`. Existing
records are normalized in place without a database migration; unknown config
keys remain intact for forward compatibility.

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

## Provider context

When at least one structured persona field or the custom system prompt is set,
the core builds one deterministic system message in this order: character
name, language, identity, traits, relationship, speaking style, behavior,
boundaries, response-length guidance, and custom system prompt. This message is
sent to every LLM adapter through the shared `ChatRequest`; it is not written
to the conversation table or event log. A completely empty legacy persona with
the default `balanced` length preserves the previous request shape.

On the first turn of an empty session, a non-empty `greeting` is displayed in
the empty Chat view and sent once as temporary assistant context before the
first user message. It is not stored as conversation history. Later turns do
not inject it again.

Persona text is persisted as user configuration. The durable
`character.changed` event contains the updated character so other windows can
refresh; no persona field is promoted to long-term memory automatically.

Voice, pronunciation mapping, sprite resources, VRM lighting/physics and
external VRMA/MMD actions are intentionally absent from this editor until a
real runtime consumes them.

## 相关文档

- [Avatar 资产与驱动](avatar.md)
- [Modules](modules.md)
- [长期记忆](memory.md)
