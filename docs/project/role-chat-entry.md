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
