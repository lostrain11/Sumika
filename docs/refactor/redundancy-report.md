# Phase 0 冗余与耦合报告

## 结论分级

下列 P0/P1/P2 是重构先后顺序，不是已确认的生产故障等级。外观层和 store 名称是待审设计，
不是本轮新增的公共 API。旧协调器仍被 worker 使用，不能直接删除。

| 等级 | 发现 | 证据 | 处理建议 |
| --- | --- | --- | --- |
| P0 | `server.py` 是跨领域单体 | 启动、迁移、RPC、路由、角色、Avatar、模块和诊断均在同一文件 | 只做装配层拆分；保持对外 RPC 不变，逐步把 handler 注入 `CoreServices` |
| P0 | 路由生命周期存在两套协调器形态 | `agent/supervisor.py` 的 `DynamicRouteSupervisor` 与 `agent/routes.py` 的旧 web-only coordinator | 明确 supervisor 为唯一动态生命周期；旧模块只保留兼容适配，增加迁移测试后再删除重复路径 |
| P1 | Route 转换逻辑分散 | `server.py` 的 catalog-to-route、ZCode route、supervisor 的过滤/排序、Provider worker 的 metadata | 建立单一 `RouteDescriptor`/`RouteEvidence` 转换边界，禁止 UI 或 worker 自己推导成本/额度 |
| P1 | Provider 目录与模型策略有派生重复 | Provider profile、Runtime model catalog、网页候选、`ModelPolicyService` 各自有目录投影 | 以 Provider/Runtime 注册表为事实源，Model Policy 只生成带证据的候选快照 |
| P1 | 网页聊天入口容易产生认知重复 | Modules 中的 Web Chat 配置、Developer 网页连接、独立原始网页门户 | 保留两者的安全隔离，但统一命名和入口说明；门户永不进入 Agent Route |
| P1 | 前端单文件状态和渲染耦合 | `frontend/main.js` 包含状态、页面切换、抽屉、表单、门户、Avatar 和事件绑定 | 按 `scene-shell`、`chat-store`、`module-store`、`agent-store`、`settings-store` 拆分；先不引入重型状态框架 |
| P2 | Tauri 壳承担过多门户细节 | `src-tauri/src/main.rs` 同时处理生命周期与 WebviewWindow | 先抽 `portal_window`，保留进程监督在 `runtime_process`；内嵌 webview 时单独合同测试 |
| P2 | 文档有多份“当前状态”叙述风险 | 执行契约、状态矩阵、专题文档均描述阶段 | 状态矩阵继续唯一事实源；执行契约只保留恢复步骤和当前动作；新重构记录放本目录 |

## 不应误判为冗余的边界

- `ModelPolicyService` 和 `model-picker` 不是两个平级路由器。前者负责授权、隐私、健康、额度、
  付费确认和最终选择；后者只提供外部能力/价格/历史建议。
- Provider profile、ZCode Runtime 和 Web Chat profile 都是 Route 来源，但凭据、登录态、处理位置
  和失败语义不同，不能用一个“大 Provider”对象强行统一。
- `capability catalog` 是只读投影，不能取代模块配置、Provider 配置或 Runtime 会话事实源。
- 原始网页门户和网页咨询 Route 必须隔离：前者是用户直接使用的站点窗口，后者是受策略控制的
  外部建议来源。

## model-picker 对接建议

### 第一阶段：顾问适配器

目标契约让 Sumika 提交脱敏的任务类别、阶段和 token 估计；能力要求、风险和支付约束暂由
Sumika 本地持有，待新协议支持后才发送。adapter 调用
`model-picker` 的 `/recommend` 或 MCP 工具，接收候选建议。不得发送 Prompt、代码正文、凭据、
Cookie、完整路径或屏幕内容。

建议映射字段：

| model-picker | Sumika | 规则 |
| --- | --- | --- |
| `model` | `external_model_id` | 只作远端标识，不直接作为可执行 Route |
| `offer.vendor` | `external_vendor` | 映射到 Sumika 已登记 profile，未知 vendor 隔离 |
| `offer.remote_id` | `remote_model_id` | 请求模型名；必须和 Sumika profile 重新校验 |
| `offer.channel` | `transport` | `api`/`web` 只作建议，不越过 Sumika capability gate |
| `capability` | `advisory_quality` | 作为证据，不替换 Sumika 的质量门槛 |
| `offer.expected_cost_usd` | `advisory_cost` | 不能覆盖 Sumika 的本地 pricing snapshot |
| `empirical` | `advisory_history` | 只进 trace/诊断，不能凭少量样本改生产策略 |

以上 Sumika 字段名已由 `model-picker/catalog/v1` 只读投影承载。HTTP 现提供
`/health`、`/catalog`、`/pricing`、`/evaluations`、兼容 `/export`、`/recommend` 和 `/record`；
Sumika 的 `ModelPickerAdapter` 只消费目录证据，不执行推荐结果。`api._registry()` 在
导出时刷新来源，适配器把请求失败、缓存结果和 stale 标记分开，并默认失败关闭。

### 推理强度与价格证据缺口

- 两边的推荐请求目前没有统一的推理强度字段。Skill 的推理强度支持并不等于 Sumika 已支持。
- picker `sources/livebench.py` 清洗模型名时移除 `thinking/effort/high/medium/low` 等标记，
  不能将合并后的分数当成某个指定强度的能力证据。未来按模型版本、评测 harness、强度和任务 cohort 区分样本。
- 新契约需区分 `requested_reasoning_effort`、`applied_reasoning_effort`、支持的强度集合、
  估算 usage 和实际 usage；宿主不返回的应用值保持 `unknown`，不要根据请求回填成功。
- 强度影响用量、耗时和质量，不预设所有供应商都按强度直接加价。输出已含推理 token 时不得
  再加一次推理费用；缓存、按次计费、订阅额度和中转站费率分别记录，未知价格不能填零。
- picker `Offer` 的价格默认值和静态 web 报价都是零；它们没有证明当前账号有免费权益。
  免费目录发现、限时权益有效期和实际账号剩余额度需要独立证据，过期或缺失保持 unknown。
- 以 `(vendor, channel, remote_id)` 加显式 profile/计费组映射为基础；重复组合隔离，不拒绝
  不同供应商间合法的同名模型。禁止用模糊别名自动启用模型或借用另一个 Route 的官方价格。

### 必须由 Sumika 重新验证

1. profile 是否已登记、已授权且健康；
2. remote model 是否属于该 profile 的已发现目录；
3. quota 是否为可信的 `available`，unknown 不能转成 free；
4. route 是否满足隐私、能力、风险、质量和预算门槛；
5. web route 是否具备人工登录和一次性授权；
6. 付费 route 是否获得本次明确确认；
7. 实际 dispatch、retry、usage、charge receipt 和 route trace 是否由 Sumika 记录。
8. 推理强度、数据新鲜度和计费口径是否有可验证证据；缺失时保持 unknown。

### 暂不做

- 不把两个仓库合并；
- 不把 model-picker 的账本当成 Sumika 的运行时账本；
- 不让 model-picker 执行 Sumika 的 Provider、浏览器、Workspace 或设备动作；
- 不在同一 turn 中静默切换主模型；
- 不因推荐服务超时而生成 Fake route；
- 不因推荐不可用而静默切到付费模型。
