# Phase 0 需求覆盖与重构缺口

本表把原始需求记录与当前状态矩阵连接起来。这里的“已具备”只表示已有代码和测试证据，
不代表长期目标全部完成；原始需求的可核实摘录见[脱敏原话摘录](../requirements/original-excerpts.md)。

## 2026-09-08 覆盖更新

最新全部79项、意图状态和逐项出处见[需求总表](../requirements/catalog.md)；以下Phase 0表格保留早期盘点语境，不覆盖最新[状态矩阵](../status-matrix.md)。

| 当前需求 | 对应证据与缺口 |
| --- | --- |
| `BROWSER-003`、`BROWSER-004` | 已正式确认统一内置浏览器；原生咨询、门户、BrowserSkill与签到流程尚未统一。咨询默认2–3来源 |
| `UX-003`、`UX-004`、`AVATAR-003` | A+五入口、能力分类和双模式有真实验收；取代旧四抽屉方案 |
| `UX-005` | 桌面置底壁纸是正式目标；普通全屏和设计稿不代表WorkerW完成 |
| `MODEL-012` 至 `MODEL-020`、`TASK-002` | 候选/评测/价格/资源/协作已有部分闭环；跨渠道、真实额度和最终统一排序仍缺 |
| `BENEFIT-001` 至 `BENEFIT-003` | 广泛发现、固定刷新、魔搭签到已有首版；新站仍需逐站接入；高频维护不升级付费 |
| `PLUGIN-002`、`COST-001` | 独立SDK和Codex协议各有基础，不能把Skill当Sumika执行器或声称已发布社区 |
| `INPUT-001`、`INPUT-002`、`WORLD-001`、`DEVICE-001`、`RESOURCE-001`、`MULTI-002` | 补齐长期验收与当前身份预留；未把延后能力标成已实现 |

## 当前已具备但需要收敛

| 需求 | 当前证据 | 重构重点 |
| --- | --- | --- |
| `CORE-001`, `PLATFORM-001`, `STARTUP-001` | 启动脚本、Tauri launcher、Agent daily acceptance | 把启动和产品领域解耦，保持 Windows 首要目标 |
| `CHAT-001`, `CHARACTER-001`, `CHARACTER-002`, `AVATAR-001`, `AVATAR-002` | Chat、角色导入、VRM、场景壳和 smoke | 把 persona/Avatar 状态从 server/UI 单体抽出 |
| `PROVIDER-001` 至 `PROVIDER-006` | Provider profile、导入、健康、定价和测试 | 统一 profile -> route 的派生边界，凭据仍独立 |
| `AGENT-001`, `AGENT-002`, `TASK-001`, `WORKSPACE-001` | Runtime adapter、任务投影、checkpoint/diff/restore | 确保 Runtime 是活动事实源，减少页面二次状态 |
| `CAPABILITY-001`, `PLUGIN-001`, `EVOLUTION-001`, `LICENSE-001` | capability catalog、插件 manifest、知识 registry、license ledger | 统一只读发现和批准状态，避免重复入口 |
| `OBS-001`, `OBS-002`, `OBS-003`, `PROCESS-001`, `PROCESS-002` | 脱敏 observability、route trace、需求文档和故障手册 | 把 trace 作为证据，不让它自动修改策略 |
| `UX-003`、`UX-004`、`AVATAR-003` | A+五文字入口、可收放聊天、模块分类与双模式 | 保留新交互契约；旧 `UX-002` 已取代 |

## 明确部分完成

| 需求 | 缺口 |
| --- | --- |
| `MODEL-001` 至 `MODEL-011` | Sumika 保留最终策略、价格/额度边界；model-picker 已通过只读 catalog/pricing/evaluation advisory adapter 接入，真实跨账户额度、长期评测样本和质量校准仍缺 |
| `BROWSER-003`, `BROWSER-004` | 策略和内嵌咨询基础已有；门户、自动任务、登录与人工接管仍待统一及真实验收 |
| `DESKTOP-001`, `DESKTOP-002` | CDP/桌面适配边界已有；受审批的真实 click/fill/send 仍需按风险逐项验证 |
| `audio`, `vision`, `memory` 对应 `DEFERRED-001` / `MEMORY-001` | 有模块和协议骨架，真实 ASR/TTS/VAD、捕获桥、检索和更多后端未完成 |
| `AGENT-002` | 固定 DSH 已验证部分能力；未暴露能力必须继续显示 unsupported，不应由 UI 猜测 |

## 延期而非缺陷

`MULTI-001`、`DEFERRED-001`、`live2d`、`virtual-world`、`life-agent`、`remote-runner` 和
`android-client` 当前属于延期/规划边界。它们只要求保留独立角色、记忆、模型策略、预算、
场景和权限的扩展点，不应在本轮为了“看起来完整”接入真实设备、持续录音、实时视觉或游戏控制。

## 原始需求记录定位

- 模型节省成本、ZCode/智谱免费额度、推荐后确认：`EX-MODEL-001` 至 `EX-MODEL-006`。
- Codex 日用平替、可插拔插件、桌宠和角色：`EX-CORE-001`、`EX-CORE-002`、`EX-AVATAR-001`、
  `EX-CHARACTER-001`。
- 日志、动态路由证据、网页咨询：`EX-SEC-001`、`EX-OBS-003`、`EX-BROWSER-002`。
- 已核实新原话：`EX-VISION-001`、`EX-PLAN-001`、`EX-UI-001` 至 `EX-UI-004`、`EX-ROUTING-001` 至 `EX-ROUTING-004`、`EX-BENEFIT-001` 至 `EX-BENEFIT-004`；统一浏览器的询问/正式确认分列 `EX-BROWSER-003`、`EX-BROWSER-004`。上列旧 `EX-*` 已标为Git历史摘要，未伪装成逐字恢复。

## 下一阶段任务 DAG

```text
Phase 0 inventory
  -> stable domain contracts (serial, L3 review)
      -> server composition split (serial)
      -> route descriptor/evidence adapter (serial)
          -> model-picker advisory adapter (serial, external boundary)
      -> frontend state/view split (parallel with backend work, disjoint files)
      -> contract and regression tests (after each contract)
  -> final review and status-matrix update
```

第一批允许低成本执行的任务只包括：只读盘点、fixture、纯 DTO 转换单元测试和文档；涉及公共
契约、凭据、付费路由、浏览器写入、数据迁移或现实设备的任务必须升级到主 Agent 审查。
