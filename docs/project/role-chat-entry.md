# 角色对话入口与模型设置

角色对话由独立扩展层实现，不修改 DSH 上游、不依赖 DSH 才能运行，也不把角色模型接进开发工具链。

## 组成

- `extensions/models/settings.py`：角色模型设置契约，显式开关、显式 provider、密钥只存环境变量名。
- `extensions/models/cloud.py`：OpenAI 兼容云端 provider；HTTPS、故障分类、无自动重试与无自动回退。
- `extensions/models/ollama.py`：本机/局域网 Ollama provider（已有）。
- `extensions/roles/chat.py`：把角色卡上下文、世界书、长期记忆、语言策略、用量记录串成一次角色对话。
- `tools/verify_role_chat.py`：真实两轮验收脚本。

## 设置文件

默认位置：`%LOCALAPPDATA%\Sumika\role-model-settings.json`（用户数据，不进仓库）。关键字段：

```json
{
  "enabled": false,
  "provider": "openai-compatible",
  "model": "deepseek-flash",
  "endpoint": "https://api.deepseek.com",
  "key_env": "DEEPSEEK_API_KEY",
  "max_tokens": 1024,
  "language": {"target": "zh-Hans", "policy": null, "allow_card_policy": true},
  "usage": {"enabled": true},
  "role": {"role_dir": "...", "database": "...", "user_id": "local-user", "project_id": "sumika",
           "memory_provider": "embedded", "card_context_enabled": true, "card_context_budget_chars": 10000}
}
```

约定：

- `enabled` 默认 `false`；关闭时不发起任何请求。
- 密钥只写环境变量名 `key_env`；设置里出现疑似密钥、`key`/`token`/`password` 字段直接拒绝保存。
- 云端要求 `https`，本机 provider 只允许回环或 https；未知 provider 直接拒绝，不回落。
- `language.policy` 为 `null` 时按“用户设置 > 卡内声明 > 内置默认”解析，来源写入 `language_policy_source`。
- `usage.enabled` 控制是否记录用量；没有 provider 数字时记 `unknown`，不做估算冒充。

## 行为边界

- 角色模型没有文件、终端、浏览器、审批或工作台工具；返回值固定带 `role_tools: 0`。
- provider 失败（认证、限流、网络、无密钥）直接抛出并保留结果未知，不改用其他 provider、不自动重试、不切到工作模型。
- 角色回复在显示前经 `localize_names` 做确定性人名替换；代码、diff、工具参数和成果正文不经过该替换。
- 原始提示词、页面内容和凭据不落盘；用量表只保存 token 计数与状态。

## 用法

```powershell
python -B -m extensions.roles.chat --settings <settings.json> --check
python -B -m extensions.roles.chat --settings <settings.json> --message "今天排练怎么样？"
python -B tools/verify_role_chat.py --settings <settings.json> --out <evidence.json>
```

## 验收证据

`role-chat-local-evidence.json`：同一设置文件、真实 DeepSeek 云端的连续两轮验收。

- `language_policy_source = card`（未设用户策略时卡内声明生效）
- 两轮假名比例均为 0，回复为简体中文并使用中文译名
- 两轮 usage 均为 `reported`：2013/3037 与 2198/2446
- 角色工具数 0；密钥仅来自进程环境变量，未写入设置与证据文件

## 已知环境问题

本机 `%LOCALAPPDATA%\Sumika` 实际被重定向到 `D:\WpSystem\...\LocalCache`，导致 `os.replace` 报跨盘错误。`save()` 已改为先解析父目录再原子替换；同类写入应沿用该做法。

## 活动室对话栏接线（2026-09-16）

设计稿的对话栏原本带三条示例消息和一个不可输入的 `div` 输入框；现在改成真实对话：

- 输入框换成真 `<input data-room-input>`，Enter 或发送按钮提交；提交后先插入用户消息，再插入真实回答。
- 记录来自 `/api/role/chat/history?session=room-<roleId>`，每个角色一个 session（切换名册即换会话并重新载入记录）；空会话显示"还没有对话记录"，不预置任何编造台词。
- 失败时显示 `发送失败：<原因>` 并标红，**不会**替角色编一句回答；桌宠小窗同样改成"只显示真实记录"，发消息也走同一 session，活动切换不再播报预写台词。
- 名册切换后同步 `#chatChara` / `#stageChara` / `#roomOwner` / `@` 标签，不再残留设计稿里的"澄花"。

## 顺带修掉的一个真实故障

内置示例角色 `extensions/roles/defaults/sumika-guide` 的 `assets.card` 指向它自己的 `role.json`，而设置里 `card_context_enabled` 默认为 true，于是**每次对话都在 `compile_card` 抛 `expected Tavern character card V2/V3`**——活动室对话在修复前完全不可用（UI 如实显示了这条错误）。

两处修复：示例角色改为携带真正的 V2 卡 `card.json`；`RoleSession` 把"角色卡上下文"当作**客户端级偏好**而不是每角色断言——角色没有可用卡时保留其自身 persona 与世界书继续对话，并把原因记录在 `card_context_status`（`on` / `off` / `unavailable: <原因>`），而不是让整轮对话失败。测试 `tests_next/test_card_context.py` 覆盖这两点。

验收：`node tools/verify_room_chat.mjs`（真实浏览器 + 一次真实角色模型调用）。证据 `docs/project/room-chat-evidence.json`：发送前为空态、名册/标题/舞台名均为真实角色名；发送后出现真实回答，无 pageerror / console error。

## 用户导入角色：独立库 + 真正的 VRM 舞台（2026-09-16）

「用户导入」以前没有独立位置：`_role_paths()` 把 `settings.role.role_dir` 的父目录当作用户库，而它默认就是仓库里的 `extensions/roles/defaults`。现在：

- 用户库 = `%LOCALAPPDATA%\Sumika\roles`（可用 `SUMIKA_ROLE_STORE` 覆盖），内置库仍是 `extensions/roles/defaults`；`/api/roles` 每项带 `kind`（`builtin` / `user`），同 id 时用户角色优先。
- 安和昴按用户角色导入：卡来自 `D:\Code\安和昴角色卡项目\交付\安和昴_ST_V2.json`（`import-card --id ando-subaru`），VRM 来自该项目 `安和昴资料库\3D模型\486desu\awa subaru（增加校徽）.vrm`，放进角色目录 `model_3d/` 并写入 `assets.model_3d` 与 `checksums.json`（`verify_role` 为 `ok`）。两者都不进仓库、不随 Sumika 发布。
- 舞台不再写死模型：删掉 `VRM_SRC=./assets/AvatarSample_A.vrm` 与 `VRM_CHARA='昴'` 这套按名字匹配的逻辑，改为 `window.sumikaRoleVrm = {id, name, modelUrl}`（由 `bind.js` 按活动角色设置），模型地址是 `/api/roles/<id>/asset/model_3d`。**没有 VRM 的角色显示立绘占位，不借用别人的模型**；角色切换会清掉容器里的旧实例再挂新模型（主屏与桌宠各一个实例）。
- 图层图例改成真实数据：`图层③ 角色 VRM · 已绑定：Sample A、安和昴 / 其余：立绘占位`，不再写死"昴：实机渲染"。

验收：`node tools/verify_user_role.mjs http://127.0.0.1:8765 ando-subaru`（一次真实角色模型调用）。证据 `docs/project/user-role-evidence.json`：角色被标记 `kind=user`、3D 资产 200 且 16.5 MB 被页面真实请求、舞台切到 `show-vrm` 且 canvas 已挂载、名册/标题/舞台名均为安和昴、对话得到符合角色卡的回答，且**第二轮能引用第一轮**（同一会话历史生效）。

## 导入入口（2026-09-16）

名册底部的「＋ 导入角色卡 · 预留 P6」原来是死文本，现在是真表单：

- **角色 id**、**角色卡文件**（选择本机 Tavern V2/V3 JSON，浏览器读成文本上传）、**3D 模型路径**（可选，填本机 `.vrm` 路径）。
- `POST /api/roles/import {id, card, modelPath?}`：卡以小体积文本传输；模型不走浏览器而由桥接从本机路径复制——16 MB 的模型绕浏览器一圈没有意义。导入后立即刷新名册并载入该角色的会话记录。
- `POST /api/roles/remove {id}`：撤销导入，**只允许删用户库里的角色**；内置角色删不掉。
- `extensions/roles/roles.py` 新增 `attach_asset`（复制资产、写 `assets.<kind>`、重算 `checksums.json`，限制路径与 256 MiB 上限）与 `remove_role`；`_role_dir` 统一做路径约束。

验收：`node tools/verify_role_import_ui.mjs`。它在真实浏览器里打开表单、上传一张临时卡、断言新角色立刻出现在名册且 `kind=user`，然后**删除该测试角色**并把列表复原；证据 `docs/project/role-import-ui-evidence.json`。模型挂载路径由单测 `tests_next/test_role_import_ui.py` 覆盖（含路径越界与非法 kind 的拒绝）。

## 完整角色的定义与"名字从哪来"（2026-09-16）

名册只收**完整角色**：名字 + 角色卡 + 3D 模型，三者齐备。要点：

- **名字不需要用户另起**：角色卡的 `data.name` 就是角色自己的名字，`import_card` 已经取用；导入表单在选中卡后会读出这个名字显示出来，并提供一个**可选的显示名覆盖**（`POST /api/roles/import {name}` → `rename_role`，只改客户端显示的名字与 `role.json`，不动卡内原文）。所以缺的不是"名字"，而是"卡"或"模型"。
- API 每项返回 `complete` 与 `missing`；不完整的角色**不静默消失**：名册下方列出"未完整（不计入名册）：<角色>（缺 3D 模型）"。
- 内置 `sampleA` 补上了自己的示例卡（VRoid 示例模型 + 示例卡），因此新装也至少有一个完整的内置角色；`sumika-guide` 只有卡没有模型，按规则列为未完整。
- 若当前活动角色不完整，名册会提示"当前角色未完整，已切到 <完整角色>"并通过 `/api/roles/select` 真的切过去，避免名册外的角色在驱动房间。

## 语言策略的第二层：回答落地的兜底（2026-09-16）

角色卡里的输出语言策略是**提示词**，模型偶尔仍会滑出假名（本轮实测中安和昴答过一句 "ねえ"）。三层优先级不变（用户设置 > 角色卡声明 > Sumika 默认），但最后加了一层确定性兜底：

- **语气词一律落成中文词**：`naturalize_reply()` 先把假名语气词（ねえ／うん／まあ／はい…）映射成中文（呐／嗯／嘛／嗯…），再把罗马音拼写的语气词（ah／maa／nee…）也映射成中文（啊／嘛／呐…），最后才把残余假名转写成罗马音（片假名折叠、拗音、小っ叠辅音、长音符变连字符；表里没有的一律保持原样，不猜）。用户读中文，罗马音对他们并不比假名更好读。
- 策略文本同步改了：Sumika 默认 `zh-Hans` 策略与安和昴角色卡都改成"语气词直接写成中文词：啊、诶、嗯、嘛、嘿、哈、哦、唔；不要用罗马音拼写语气词"，卡内原文与用户库副本一起更新，并刷新 `checksums.json`。
- **默认不重发**：为一两个音节再生成一次既费 token 又慢，所以纠正走本地确定性转换；`localize_names` 之后再检查一次，正常结果里不会再有假名。
- 只有显式打开 `settings.language.retry_on_kana`（默认 false）时才会"重发一次 + 纠正指令"；即便如此，纠正后仍不干净也会**如实标记** `language_guard {retried, clean, transliterated, kana_found, kana_remaining}`，usage 把两次调用都算进去，绝不假装干净。
- 单测 `tests_next/test_language_guard.py` 覆盖五种情形：干净（1 次调用）、假名语气词（**仍只 1 次调用**，本地变中文）、罗马音语气词（同样本地变中文）、显式开启后重发成功、显式开启且表外字符无法转换时如实标记（例如 ゐ 保持原样并计入 `kana_remaining`）。
- 验收（`verify_user_role.mjs` 实测）：回答为「你好，你好。来打招呼的吗——ah，这么正式……maa，我这边刚练完鼓……」——中文 + 罗马音语气词，无假名。
