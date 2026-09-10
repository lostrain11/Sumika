# Quality routing 独立组件边界

本文记录 P02 通用 selection 抽取与 P09 独立组件验收的实现边界。组件核心位于
`packages/quality-routing`，Sumika 与外部宿主使用同一份 Python 实现。

## 依赖方向

```text
Sumika quality adapter -> quality_routing <- DSH managed helper
                                      <- optional MCP adapter
```

- `quality_routing` 不导入 `sumika_core`、Tauri、前端状态、Provider 配置或 Sumika 数据库。
- Sumika 的 `quality/selection.py` 只兼容重导出 SDK 对象，不复制算法。
- selection 持久化只依赖 `SelectionMetadataStore.get_meta/set_meta` 两个方法，不接收
  `CoreApplication` 或巨型 `HostContext`。
- 候选健康、可用性、路由授权、模型版本与价格由宿主提供；SDK 不读取厂商账户或凭据。
- 报价、资源预留与实际结算仍是不同阶段；selection 只返回建议，不签发消费授权。

## 外部工作入口准入

`quality/legacy_admission.py` 是 Sumika 适配器，不是独立 SDK。Agent prompt/retry、队列编辑、
子 Agent prompt、网页发送和 Route/Consultation 派发现在使用 `WorkService` 的同一工作记录与版本化授权。
前端 `work-authorization.js` 保留原参数和请求 ID；确认后重入原入口，不把外部任务提交到 API 文本执行器。

- 简单且明确 `free-only` 网页策略可直接执行；这只是禁止付费策略，不是官方免费价格证明。
- 复杂任务即使费用为零仍须确认。`approved`、`routingApproved`、余额和模型生成内容均不能替代费用确认。
- 未知金额、未知 Token/调用上限保存为 null。真实 DSH 尚未提供逐调用强制限额，等待状态明确显示此限制，不能通过填写金额伪造可执行授权。
- 每次派发冻结入口、参数和渠道证据；延期 arm 在事件到达时重检价格。事件自身不得提供新执行目标或消费授权。
- 同一网页 Profile/Agent 会话的未决尝试不重复派发；跨助手只返回资源占用错误，不返回其他助手的记录。
- 取消转交原执行源一次，状态为 `cancel-requested`；未知提交和重启恢复保留预留，不宣称已经撤销上游请求。
- Agent 回收必须匹配会话与 turn ID；Web/Route/Consultation 回收匹配来源及上游 ID。缺少可靠终态的失败继续保留未决费用。
- 外部成功回执按已授权上界保守记账，标记 `conservative-upper-bound-not-bill`，不是厂商实际账单。
- 外部正文单独保存，标记 `source-completed`（来源已完成，未独立质量验证）；附言不进入复制正文。

验证入口：`backend/tests/test_legacy_work_admission.py`、`frontend/tests/work-authorization.test.js`、
`frontend/tests/workbench-host.spec.js`。后者运行真实前端宿主，但模型和执行回执均为显式隔离 fixture，
不代表真实 DSH、付费网页或新渠道质量验收。

剩余限制：无法强制限额的原生 Harness 不进入承诺硬上限的自动执行路径；只有下述明确列举的外部步骤
支持共享授权，API 文本 DAG 自动交办、运行中新增步骤、递归子计划及延期 arm 尚不继承；未提供可靠
turn ID/账单的外部宿主仍需人工核实未决状态。
主任务不因上述限制自动改用其他模型。原生多屏热插拔仍须硬件验收，P14 不因此标记全部完成。

整合回归：后端1183项、前端单测77项、Playwright83项、Rust35项通过；独立安装环境SDK76项
（含MCP，无跳过）、DSH helper测试4项通过。证据日志保留在 `artifacts`，原生证据见[双窗口验收](../refactor/client-workflow-v2-native-validation.md)。

### 外部父子任务共享授权

Agent/Web 原入口可在预检参数中附带 `external_steps`（最多32步）：每步包含稳定 `id`、`purpose`、
原入口 `method` 和确切 `params`。这是待审阅的计划，绝不是授权；即使全免费，也必须在工作台确认。
工作台展示用途、目标、渠道、费用上界和可展开的完整执行范围；有任何未知上界，整个计划不得开始。
例子中的名称仅为协议说明，不指向真实账户或运行会话：

```json
{
  "client_request_id": "example-parent",
  "sessionId": "example-host-session",
  "text": "整理报告",
  "external_steps": [{
    "id": "verify", "purpose": "核验已有材料",
    "method": "agent.session.prompt",
    "params": {"sessionId": "example-child-session", "text": "核验报告中的事实"}
  }]
}
```

- 宿主读取自身报价，不采信请求中的价格或 `approved`。父请求预算包含自身调用上界及每个子步骤上界，
  使用 Decimal 累计；复杂任务确认流程不变。无法强制上限的真实 DSH 仍会被阻断。
- 计划不得包含凭据字段或可识别的秘密文本；入库前递归拒绝，凭据留在宿主受控执行器。
- 确认同时冻结计划摘要、助手、Core会话、项目、每步用途、参数、入口、渠道及价格证据。
  SDK 的 `check_delegation` 只验证这些契约与剩余额度，不读取 Sumika 数据或签发授权。
- 原宿主继续调度；派发子步骤时使用预检返回的规范化 `params`，并附带 `parent_work_request_id`、
  `parent_revision`、`parent_step_id`，再次进入原 RPC。只提供父ID或同会话不能继承授权。
  这些准入字段及计划不会传给上游模型/Harness；原入口的文件权限、checkpoint和网页动作策略继续生效。
- 父请求是唯一总预算账本；子请求通过 `budget_owner_request_id` 明确属于该预算。
  父子预留/回收使用同一 SQLite 事务和旧值比较，任一更新冲突则全部回滚，发送前失败不会调用上游。
  子记录的金额是该步骤投影，统计时不得再与父金额相加。没有新资金账本或第二套任务调度器。
- 重复步骤得到同一子请求ID；已提交或未知状态不重发。完成只保守计入一次上界，仍不是实际账单。
  未知子提交保留父预留并阻止新增兄弟步骤；可靠终态到达后才回收。重启保留关联和未决预留。
- 父取消阻止新子步骤并转交已运行子步骤的取消，已完成子成果保持。取消不释放未知费用。
  未执行完已声明步骤时父任务不伪装为完成。增加/修改步骤需要新请求和确认，不暗中扩大旧授权。
- 本轮不让文本规划器自动生成或派发上述步骤；它们必须由原宿主明确提出，原宿主负责调度和结果使用。
  API 文本 `work.task.preflight` 遇到 `external_steps` 明确拒绝，避免静默丢弃范围。

新增测试：`backend/tests/test_work_delegation.py`、`backend/tests/test_legacy_work_admission.py` 的公开RPC闭环、
`packages/quality-routing/tests/test_delegation.py`、工作台授权范围的单测和 Playwright。均使用离线执行器，
不作为真实付费渠道验收。追加测试结果以[当前执行记录](../current-execution.md)为准。

报价稳定性：网页咨询按 `route_constraints.route_ids` 限定报价范围，目录顺序不影响绑定摘要；未被指定的
渠道变化不会撤销当前预检，指定渠道或真实价格变化仍会拒绝派发。预算表单随中央工作区宽度换行，
避免右侧面板展开时确认按钮被裁切。

回归故障记录：AgentServer离线测试只在内存手工注册渠道；上一轮网页完成事件会异步从真实目录重建，
导致这些fixture渠道在下一次预算确认前消失。诊断证实绑定从两个明确渠道变成空列表，准入拒绝正确。
现将该fixture的目录刷新隔离，并为旧渠道测试补齐对应Profile；生产刷新和价格变化拒绝逻辑保留。

已核对本机DSH 0.1.1-rc.2发布包的 `dsh-host-apiproxy/lib/types/api/sessions.d.ts` 和 `subagents.d.ts`：
`session.prompt` 提供会话、queue/steer、内容与时区；`subagent.prompt` 提供子助手地址、内容与时区，
没有本任务可绑定的消费硬上限字段。`llm.schema.d.ts` 中的 `maxTokens` 是模型目录信息，不能当作工作总预算。
这说明当前适配公开入口仍无可验证的强制上限，并不证明DSH未来或其他插件不可能实现；本轮不修改日用DSH。

## Selection 契约

固定 cohort、外部 prior、固定题 sample、资格判断和绑定决策均在 SDK 中。资格判断继续要求：

- 同一 purpose、cohort ID 与 cohort version；
- 明确且匹配的 model version；
- 至少三条成功、未过期且观测时间有效的固定题样本；
- 显式 reasoning effort 候选必须有相同 applied reasoning effort 的独立样本；
- prior 只打破已测质量分并列，不能制造资格、健康、可用性或授权。

主模型自动模式按合格质量优先。角色自动模式先过滤不健康、未授权、不合格及未知价格候选，
再沿用 `cost_order` 排序，因此证据明确的免费资源先于付费候选，合格付费候选仍可正常返回。
selection 结果只是建议，不签发消费授权；当前免费角色保持稳定和付费确认由宿主负责。
已购资源的获取价值不等于免费，过期资源和未知价格也不能变成免费。

secret detector 从浏览器策略原样提取到 `quality_routing.privacy`，Sumika 浏览器策略与
selection 引用同一函数。检测模式未删减，仍覆盖 `sk-`、Bearer、API key、token、password、
secret 与 OTP 形态。

## 独立宿主表面

Python SDK 继续提供 `Coordinator` 及可选 MCP stdio adapter。MCP 默认只读，宿主绑定提交时
仍需固定 scope 与可信 policy callback；MCP 工具不能调用 `Coordinator.approve`。

`plugins/dsh-quality-routing` 使用 DSH 0.1.1-rc.2 的官方 Cordis bundle、`tools.register` 与
`ctx.effect` 生命周期 API。插件要求显式绝对 `pythonExecutable` 和 `dataDirectory`，使用参数数组
启动 `python -m quality_routing.dsh_helper`，并只传递运行 Python 所需的最小环境。关闭插件时先发送
私有 `shutdown`，超时才终止自有子进程。

DSH 仅注册：

- `quality_routing_component_status`：读取组件能力；
- `quality_routing_offline_fixture`：运行 deterministic offline fixture。

没有 approve、confirm、Provider 或 credential 工具。本机官方 DSH 0.1.1-rc.2 包提供
`ctx.approval.request` 一次性审批 seam；它要求开放中的 Agent turn，缺少应答器时 fail closed。
当前适配器没有真实模型 executor，因而不发起审批，任意模型执行明确报告
`trusted-host-adapter-not-configured`。未来接入真实 executor 时必须注入 `approval`，只接受
`allowed-once` 后再通过私有 helper 协议调用 SDK 审批，不能把审批方法注册成模型工具。

## 离线生命周期与声明

`python -m quality_routing.offline_example` 覆盖：

```text
submit -> awaiting-confirmation -> host approve -> execute -> verify -> completed
submit -> cancel
submit -> snapshot -> close -> restore -> re-approve -> execute -> completed
```

示例和 DSH helper 都设置 `fixture=true`、`real_model=false`。它们证明安装、协议、状态机、恢复和
进程生命周期，不证明任何真实模型的质量、费用、身份或工具能力。

## 安装与验收

干净环境验收必须在仓库外创建 venv，清除 `PYTHONPATH`，只安装
`packages/quality-routing` 及其声明依赖，再运行模块、测试 helper。DSH 验收必须使用独立
`DSH_HOME` profile，安装本地插件、用 patch 显式配置上述绝对路径，启动后核对
`lifecycle.json=ready`，正常停止后核对 `lifecycle.json=stopped`。不得连接日用 DSH profile、
Sumika RPC、真实 Provider、Cookie 或凭据。

当前实现版本为 `quality-routing 0.1.0`（Apache-2.0）和
`@sumika/dsh-quality-routing 0.1.0`（MIT）。未发布到包注册表或社区仓库。

## 2026-09-09 实际验收

- 仓库外 venv 在清除 `PYTHONPATH` 后只安装本地 `quality-routing`，导入路径位于该 venv 的
  `site-packages`，版本为 0.1.0，`sumika_core` 未进入 `sys.modules`。
- 已安装模块运行离线示例，得到 complete 状态
  `awaiting-confirmation -> ready -> completed`、cancelled，以及 restore 后
  `awaiting-confirmation -> completed`；验证证据为 deterministic fixture。
- 在同一 clean venv 安装声明的 `mcp` extra 后，独立只读 `FastMCP` 成功构造；SDK 76 项测试
  全部通过且无可选项跳过，`sumika_core` 仍未加载。
- DSH 插件的真实 helper 集成测试 3 项通过，包含进程启动、能力读取、fixture 和正常停止。
- 使用 `D:\Tools\DeepSeekHarness\0.1.1-rc.2` 官方 CLI，在独立 `DSH_HOME` 的
  `quality-routing-p09` profile 通过 `dsh plugin ... add file:...` 实际安装；组合配置包含独立插件层。
- profile 使用绝对 venv Python 与独立数据目录实际启动。`lifecycle.json` 先记录 `ready`，正常
  中断触发 Cordis dispose 后记录 `stopped`，进程检查无 helper 残留。
- 停止后通过官方 `dsh plugin --profile ... remove` 实际移除测试 profile 的插件依赖与 bundle；
  显式数据目录未被隐式删除，生命周期证据保持 `stopped`。
- 全程未启动 Sumika Core、未访问日用 DSH profile、未连接 Provider，也没有真实模型调用。
