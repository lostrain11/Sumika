# Agent 日用遥测与评估

本页冻结 Sumika 日用运行诊断、插件对比和 Agent 自进化评估的数据边界。当前已经落地
内容无关的 JSONL receipt、按日聚合、安全 API、真实 Session 的有界验收投影，以及模型策略
的确定性候选目录/推荐门控；自动质量评分、长期评测和生产自动切换仍未实现。
功能状态以 [状态矩阵](../status-matrix.md)为准。

## 目标与非目标

目标是让维护 Agent 在一天使用结束后，仅依靠机器可读信号回答：

- 哪个步骤失败、变慢、重试或被用户撤销；
- 同类插件在可比任务上的成功率、延迟、资源和成本差异；
- 哪个候选值得进入隔离复测，以及复测结果能否复现。

这套数据不是角色记忆、聊天记录、恢复备份或员工监控。首版不做常驻 Dashboard，
优先使用紧凑 JSONL 和日聚合 JSON，减少 UI 和人工可读性成本。

## 事件关联

所有未来遥测共用版本化 envelope：

```text
schema_version, timestamp_utc, monotonic_ns
run_id, session_id, turn_id, operation_id, parent_operation_id
component, capability, adapter_id, adapter_version, adapter_hash
phase, outcome, error_class, duration_ms, queue_ms, retry_count
model_id_hash, provider_kind, processing_location
input_units, output_units, cache_units, estimated_cost
cpu_ms, peak_rss_bytes, io_read_bytes, io_write_bytes
approval_count, cancellation_reason, recovery_action
```

ID 只用于同一安装内关联，不编码角色名、仓库路径或用户内容。`error_class` 使用稳定
枚举；异常消息只保留脱敏后的模板和堆栈指纹。未知字段允许忽略，破坏性变更必须提升
`schema_version`。

## 数据分层

1. `operational event`：每个边界调用一行，供故障定位和耗时分解。当前由
   `backend/src/sumika_core/observability.py` 写入
   `.sumika/logs/agent-observability/YYYY-MM-DD.jsonl`（桌面端对应
   `.sumika-desktop`）；文件按大小分片且只保留受限字段；
2. `route decision trace`：`backend/src/sumika_core/agent/route_trace.py` 写入
   `logs/route-decision-trace/YYYY-MM-DD*.jsonl`，逐条关联事件边界、候选过滤、证据、排序、
   选择、确认、派发、去重、重试、取消和终态；每个候选独占一条有界记录；
3. `run manifest`：固定 Runtime、插件、模型、硬件档位、配置哈希和测试数据版本；
4. `daily aggregate`：按 capability/adapter/outcome 聚合 count、p50、p95、错误率和成本。
   可通过 `agent.observability.daily` RPC 或
   `python tools/aggregate_agent_day.py --write` 生成 `*.summary.json`；
5. `evaluation result`：隔离评测的任务级输入摘要、判定器版本、指标和置信区间；
6. `recommendation`：只读候选结论、证据引用和风险，不包含自动启用动作。

原始事件可轮转；聚合结果必须保留其 schema、样本窗口和 manifest 哈希，否则不得参与
长期趋势。恢复仍使用 Workspace checkpoint 和 SQLite snapshot，不从遥测反推状态。

## 安全与最小化

默认禁止写入 API Key、Cookie、环境变量值、聊天正文、系统提示词、工具参数/结果、
文件内容、diff 正文、截图、音频和浏览器 DOM。路径只记录 workspace 内相对路径的
不可逆哈希与文件类型；模型、Provider 和插件使用公开 ID 或本地稳定哈希。

路由 trace 还会把父 Session、turn、dispatch 和 Provider profile 通过每次 Core 启动随机
salt 转成不可逆哈希。证据只保留引用哈希、类型、可信度、新鲜度和时间；异常只保留错误类或
稳定错误码。usage 与费用只接受固定数值字段。Writer 不接受 `prompt`、`answer`、`context`、
`path`、DOM 或任意扩展 payload，因此不能靠调用者“记得脱敏”维持安全。

只有 Developer Mode 下显式创建的诊断包可包含额外结构化元数据，并在生成前列出字段、
时间范围和大小。诊断包不自动上传，命名 Profile 的认证数据永不进入包内。

## 日用故障分析

一次完整 Agent turn 至少记录 `accepted → queued → model/tool/approval → completed|failed|cancelled`
各阶段。缺失终态、重复终态、超时、重启后孤儿 operation、连续重试、恢复失败和退出后
残留受管进程都属于机器可检测异常。

未来的离线分析器按天生成：新错误指纹、错误率回归、p95 回归、频繁人工接管、重复撤销、
checkpoint 恢复次数和未闭合操作。当前模型策略已经能根据固定门槛提出一次性候选建议；离线
分析器仍只能提出 issue 草稿或隔离复测建议，不能自行修改代码、安装插件、切换 Provider 或
删除数据。

## 插件可比性

同类插件只有在 `capability + workload_id + workload_version + model + provider + hardware_class +
privacy_policy + cache_state` 相同时才进入同一 cohort。优先做同一任务的 paired trial；
冷启动与热缓存分开统计，超时和用户取消不得从样本中丢弃。

通用主指标为任务判定成功率、端到端 p50/p95、错误率、重试率、资源峰值和估算成本。
质量判定优先使用确定性测试、结构化契约、人工批准/拒绝和最终回滚结果；“回复更长”或
“调用更多工具”不能作为质量提升。

记忆插件另记录写入延迟、检索 p50/p95、top-k 命中、过期/冲突率、无关注入率、存储增长、
合并失败率，以及在同一问答集上的任务成功率增量。仅比较平均返回速度不足以决定优劣。

## 自进化闸门

评估沿用 `E1`：允许自动发现候选、生成兼容报告并在隔离 Profile/Workspace 中运行固定
夹具；安装到生产 Profile、迁移数据、改变默认实现或正式启用始终需要用户批准。每次推荐
必须给出当前版本、候选版本、许可证、权限差异、样本量、指标变化、失败样本和恢复路径。

出现 schema 不兼容、样本不可比、敏感字段泄漏、评测夹具变化或恢复验证失败时，结论必须
标记为 `inconclusive`，不能选出赢家。

## 实施顺序

1. 在 `AgentRuntime`、`WorkspaceRuntime` 和 Browser policy 边界统一 correlation IDs；
2. 增加内容无关的 JSONL sink、轮转和退出完整性检查；
3. 增加日聚合器与固定诊断包格式；
4. 建立真实编码任务和记忆检索的版本化评测夹具；
5. 用固定样本校准候选推荐和隔离复测，不增加自动生产切换。

当前 Codex 平替里程碑已完成第 1、2 项的最小实现，并接入模型策略的基础门控：Core RPC 和 DSH runtime event
会生成稳定的 operation/opaque session 关联字段，并写入可轮转 JSONL；按日聚合器
提供 p50/p95、结果计数、重试/审批/资源总量。只读 `agent.acceptance.evidence` RPC
还可从最多 1000 条 Core 事件中关联指定真实 Session 的 Plan 审查、批准前 checkpoint、
工具终态、diff 和恢复结果；公开结果不返回 Session/checkpoint/request ID、时间戳、路径或
正文。模型策略的 catalog、确定性难度推断、额度 TTL 和推荐前确认已由独立模块及测试覆盖。

固定评测任务集现已落地为
[`tools/fixtures/model-evaluation-v1.json`](../../tools/fixtures/model-evaluation-v1.json)，
覆盖只读问答、单/多文件修改、工具、Plan Review、MCP、浏览器审批和工作区恢复。
[`sumika_core.model_evaluation`](../../backend/src/sumika_core/model_evaluation.py) 只接受
不含内容的结果记录，并按 `task_set + Harness + adapter + provider + hardware + privacy +
cache_state` 分 cohort，输出成功率、Wilson 95% 区间、工具/质量通过率、重试、p50/p95、成本
和额度单位。`routing_action` 固定为 `none`：即使报告给出诊断性候选，也不会自动修改生产路由。
证据不足（默认每个任务至少 3 次）或置信区间重叠时，结果标记为 `insufficient`/`inconclusive`。

已完成回合不会被评测器自动扫描。若维护 Agent 明确选择一个终态 Worker run，可调用
`DynamicRouteSupervisor.capture_evaluation_sample(..., opt_in=True)`，只投影固定的状态、耗时、
重试和布尔指标。该方法不读取日志/SQLite，不访问 prompt、answer、文件、DOM 或凭据；运行中
回合和不完整状态直接拒绝。跨进程交接使用
`sumika.model-evaluation-capture/v1` 的小型 JSON/JSONL handoff，由
[`tools/capture_model_evaluations.py`](../../tools/capture_model_evaluations.py) 在显式
`--opt-in` 后验证并生成 `sumika.model-evaluation/v1` records。捕获文件再交给
`tools/evaluate_models.py` 离线汇总，仍不会改变生产路由。

## 运行方式

```powershell
# 查看今天的安全聚合（不联网、不修改产品数据）
python tools/aggregate_agent_day.py

# 生成今天的持久摘要
python tools/aggregate_agent_day.py --write

# 离线汇总固定评测结果（JSONL 或包含 records 数组的 JSON）
python tools/evaluate_models.py --input <evaluation-results.jsonl>

# 从已由隔离 runner 明确导出的终态元数据生成评测 records；不读日志或数据库
python tools/capture_model_evaluations.py --input <terminal-captures.json> --opt-in \
  --output .sumika-desktop\logs\evaluation\captured.json

# 输出完整的有界 JSON；结果文件只会写入项目目录且不会覆盖旧报告
python tools/evaluate_models.py --input <evaluation-results.jsonl> `
  --output .sumika-desktop\logs\evaluation\model-evaluation.json --json

# 只读投影一个已经完成的真实 Session；不会再次调用模型
python tools/agent_daily_acceptance.py `
  --core-url http://127.0.0.1:8771 `
  --real-session <session-id> `
  --report-dir .sumika-desktop\logs\acceptance --json

# 在明确指定的隔离 DSH profile 上跑固定协议验收（本地页面，不使用真实账号）
python tools/agent_daily_acceptance.py --browser-smoke --browser-write-smoke `
  --endpoint http://127.0.0.1:3095 `
  --profile-dir <isolated-profile> `
  --core-url http://127.0.0.1:8770 --json
```

`--real-session` 的 ID 只用于 Core 内部查找，不写入报告。只有 checkpoint 确实早于批准、
回合完成、观察到写工具和 diff，并完成恢复预览与精确恢复时，该阶段才会通过。

浏览器验收会先检查 endpoint/profile 绑定；写入 smoke 只提交仓库内临时本地页面，且必须
观察到 DSH 审批请求。日用脚本不会自动启动或修改 DSH profile，真实人工接管仍需用户在
隔离 Agent Window 中明确操作。

Core 也提供 `GET /api/agent/observability?day=YYYY-MM-DD&write=true`，其结果包含路由 trace
日聚合；`GET /api/agent/route-trace` 和 `agent.route.trace.daily` 可单独读取该聚合。
该聚合按 Route 汇总候选/选择/终态次数、过滤原因、结果、p50/p95、usage 和按币种分开的费用；
这些接口不返回原始关联记录。原始 JSONL 是一次性诊断数据，不是 Session、Workspace
或备份恢复来源。维护 Agent 可以读取本地 trace 分析选择依据，但任何策略修改仍需代码、
固定评测和用户授权，不能把日志本身当成自动调参命令。

评测记录的最小形状如下（示例只展示元数据和布尔/数值结果，不放请求或响应正文）：

```json
{
  "schema_version": "sumika.model-evaluation/v1",
  "task_id": "read-only-question",
  "route_id": "profile:local:qwen3:4b",
  "manifest": {
    "task_set_id": "sumika-agent-core",
    "task_set_version": "1.0.0",
    "harness_id": "dsh",
    "harness_version": "0.1.1-rc.2",
    "adapter_id": "dsh-adapter",
    "adapter_version": "1",
    "provider_kind": "ollama",
    "model_id": "qwen3:4b",
    "model_version": "local",
    "hardware_class": "local-rx5700xt",
    "privacy_policy": "local-only",
    "cache_state": "cold"
  },
  "success": true,
  "outcome": "completed",
  "tool_success": null,
  "retry_count": 0,
  "latency_ms": 420,
  "estimated_cost": 0,
  "quota_units": 0,
  "quality_passed": true,
  "user_correction": false,
  "approval_count": 0
}
```

结果由隔离 runner 产生；当前 CLI 只做离线验证和汇总，不负责启动模型、执行任务、安装
插件或切换 Provider。被拒绝的记录只返回行号和稳定错误码，错误值和疑似敏感字段不会回显。

捕获 handoff 的最小形状如下（`run` 只允许终态和标量字段；`manifest` 与评测记录相同）：

```json
{
  "schema_version": "sumika.model-evaluation-capture/v1",
  "task_id": "read-only-question",
  "manifest": { "...": "同上面的固定 manifest 字段" },
  "run": {
    "route_id": "profile-local-qwen3-4b",
    "status": "completed",
    "latency_ms": 420,
    "retry_count": 0,
    "completed_at": "2026-08-31T00:00:00+00:00"
  },
  "metrics": { "tool_success": true, "quality_passed": true }
}
```

缺少 `--opt-in`、状态为 `queued/running`、字段超出白名单或出现疑似敏感值时，捕获命令
返回失败/需复核状态，不会部分写入或回显输入值。输出文件采用不覆盖策略。

## 相关文档

- [Debugging and recovery signals](debugging.md)
- [Agent Runtime](agent-runtime.md)
- [Workspace 与任务](tasks.md)
- [Evolution Knowledge Registry](../integrations/evolution-registry.md)
- [状态矩阵](../status-matrix.md)
