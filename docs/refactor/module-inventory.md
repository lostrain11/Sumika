# Phase 0 模块盘点

本盘点是重构前的事实快照，不是新的完成度来源。功能完成度仍以[状态矩阵](../status-matrix.md)为准；
需求意图仍以[需求基线](../requirements/README.md)和[模型策略契约](../requirements/model-policy.md)为准。

## 总体结论

当前项目已经有可工作的首版边界，但装配层过重：`server.py` 同时承担启动迁移、依赖装配、RPC
分发、路由转换、角色/Avatar、模块、网页聊天和诊断；前端 `main.js` 同时承担状态存储、页面路由、
抽屉、Provider 表单、网页门户和所有渲染。下一轮应先拆“装配”和“领域”，不要先删除现有实现。

代码规模快照：`server.py` 约 7,964 行，`main.js` 约 9,355 行，`supervisor.py` 约 4,183 行，
`web_chat.py` 约 3,438 行，`model_policy.py` 约 1,663 行，`src-tauri/src/main.rs` 约 1,458 行。

快照基于 2026-09-05 的 Sumika `28d5051` 和 model-picker `45baa67`。两库按 `company` 处理。
picker 有两处既有源码修改，本轮没有编辑该仓库；源码规模不包括缓存、日志和模型资产。

## 后端责任地图

| 区域 | 当前责任 | 主要证据 | 重构结论 |
| --- | --- | --- | --- |
| Core 装配与 HTTP/RPC | 启动、迁移、默认数据、依赖装配、HTTP、RPC 和跨领域转发 | `backend/src/sumika_core/server.py` | 保留为 composition root；把领域 handler 和启动迁移外移 |
| 模型策略 | 目录、难度、能力门槛、额度、定价和推荐后确认 | `backend/src/sumika_core/model_policy.py`、`route_pricing.py` | 作为 Sumika 权威策略；未来只接收顾问建议，不让外部推荐器执行 |
| 动态路由 | 候选过滤、排序、确认、派发、重试、咨询和 trace | `backend/src/sumika_core/agent/supervisor.py`、`agent/routes.py` | `supervisor.py` 是主生命周期；旧 `agent/routes.py` 需先标注用途，再逐步收敛，不能双写事实 |
| Provider | Provider 档案、模型发现、健康、凭据引用和导入 | `provider_profiles.py`、`providers/`、`provider_imports.py` | Provider profile 是凭据事实源；模型 Route 是派生投影 |
| Runtime | DSH/ZCode 适配、事件、工具、Skill、MCP、Workspace 投影 | `agent/`、`workspace/`、`tasks/` | 保持 Runtime-neutral；adapter 不应反向拥有 Sumika 路由策略 |
| Browser/Web Chat | BrowserSkill 会话策略、视觉证据和网页聊天 Provider | `browser/runtime.py`、`browser/web_chat.py`、`browser/policy.py` | 网页 Route 继续是显式 WebWorker；网页额度未知不能当免费 |
| 角色/Avatar | 角色导入、persona、模型发现、绑定和表现设置 | `character_import.py`、`avatar/`、`server.py` | 迁移到 Character/Avatar application service，保留本地资源包边界 |
| 模块/能力 | 模块状态、能力目录和实现选择 | `modules/`、`capabilities.py` | 统一只读 catalog；启停写操作仍由各领域服务负责 |
| 观测/评测 | 脱敏事件、route trace、评测和日聚合 | `observability.py`、`agent/route_trace.py`、`model_evaluation.py` | 只做证据和报告，不直接改变生产路由 |

## 前端和桌面责任地图

| 区域 | 当前责任 | 主要证据 | 重构结论 |
| --- | --- | --- | --- |
| 场景外壳 | Avatar 常驻、聊天气泡、dock 和四抽屉 | `frontend/main.js`、`frontend/styles.css` | 方向正确；拆成 shell、scene、drawer、chat 四个视图模块 |
| 模块/Provider UI | 模块库、能力目录、定价、Provider 配置、网页配置 | `frontend/main.js` | Provider 表单和网页表单应成为可插拔模块视图，减少条件分支 |
| Agent/Workspace UI | Session、任务、审批、checkpoint、diff、恢复 | `frontend/main.js` | 以 Runtime projection store 接入，不在页面状态复制活动回合 |
| 网页门户 | 原始站点门户列表、独立窗口开关和自定义站点 | `frontend/main.js`、`src-tauri/src/main.rs` | 原始门户与 Agent Web Chat 有意隔离；下一版按已确认方案内嵌子 webview |
| Tauri 壳 | Core/Runtime 启停、进程清理、门户窗口和系统桥 | `src-tauri/src/main.rs` | 仅保留生命周期和系统能力；门户命令拆到独立模块 |

## 测试证据分布

后端已有按领域拆分的测试，包括 `test_model_policy.py`、`test_dynamic_route_supervisor.py`、
`test_web_chat.py`、`test_browser_runtime.py`、`test_workspace_runtime.py`、`test_character_import.py`
和 `test_capabilities.py`。前端主要由 `frontend/tests/smoke.spec.js` 覆盖；Tauri 关键命令测试
位于 `src-tauri/src/main.rs` 的测试区域。重构时应先保留这些合同测试，再为新应用服务增加更小的单元测试。

## 第一轮目标边界

1. 先拆 `server.py` 的 composition root，不改变 RPC 名称和安全策略。
2. 先统一 Route DTO 和候选证据，不先合并 Provider、网页和 Runtime 的凭据。
3. 前端先拆状态 store 和视图入口，不改变用户可见的场景外壳。
4. `model-picker` 先实现只读 catalog/recommendation adapter；真实执行、授权和付费确认留在 Sumika。

## 依赖方向与运行数据

```text
scene/drawers -> Core RPC -> domain services
                          -> ModelPolicy -> Provider/Runtime catalogs
                          -> Supervisor -> workers -> Runtime/Browser/Provider
                          -> Workspace checkpoints + bounded task projection
picker catalog/pricing/evaluation -> advisory adapter -> ModelPolicy revalidation
Tauri -> managed processes + desktop capabilities (not model policy)
```

角色、记忆、音频、视觉、权限服务不能依赖 picker；picker 不依赖 Sumika UI 或 DSH 私有对象。
本轮只登记仓库内仍有运行目录，不读取其中的数据库、对话、Cookie、截图或模型包。
数据外移留为独立迁移任务：逐项授权清单、目标布局、停机复制、数量/哈希验证、启动验证、
恢复预览；不移动旧归档，不创建链接，不把 Git 视为运行数据备份。

## 本轮验证范围

设置 `PYTHONPATH=backend/src` 后，Model Policy、policy server、动态 Supervisor、Route Pricing
和 Model Evaluation 五组共 78 项测试通过。首次缺少 PYTHONPATH 的导入错误属于命令环境问题，
未改产品代码。完整 UI、Rust、真实 Provider、真实网页与设备 smoke 本轮未重跑，旧通过记录不
作为本轮实机证据。测试应使用临时数据和 fixture；不启动用户日常实例来做基线验证。
