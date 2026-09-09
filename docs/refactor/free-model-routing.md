# 免费候选正式刷新与路由

本阶段接续 [十渠道核查](free-provider-audit.md) 和 [免费资源发现](free-benefits.md)。发现服务负责找线索；正式路由只使用绑定到已有 Provider Profile 的官方证据与任务评测。新增状态不授予网页登录、注册、充值或付费回退权限。

## 当前实现

- `integrations/free_model_sources.py` 用固定官方来源读取目录/定价，不读 Key、Cookie，不调用模型。精确模型 ID 保留大小写；不同账号与渠道隔离。完整目录缺项可标记撤回，不完整页面缺项只表示缺证据；两者均停止新免费派发。
- `free_model_routing.py` 将授权绑定到账号、凭据版本、官方端点及执行配置。价格与目录最多缓存六小时；失败退避十五分钟并阻断使用。每个 Profile 单独维护状态，Sumika 关闭后不再调度刷新。
- Windows 下单独的 `free-model-routing.sqlite3` 保存元数据、任务评测期限、最近健康与在途租约；逐事务关闭连接，不锁住日用数据库，也不保存 Key、Cookie、提示词或回答。
- 正式 `ModelPolicy`、Route Supervisor、Quality Runtime 与 Provider 发送入口共用此状态。发送前再次核对价格、权限、到期、配置和任务边界；跨实例只允许一个账户请求在途，正常结束间隔四秒。429 冷却十五分钟，响应不明冷却五分钟，不自动重发。
- 401/402/403 停止该候选并要求核查账号权益，404/410 阻断下线候选；不改发付费模型。旧账户的刷新、错误及释放操作不能污染重新绑定后的账号。

## 质量和额度含义

`bounded-text-v1` 包含三项固定任务：中文事实抽取及未知字段、否定与数字保留、把记录内指令当数据的精确结构化处理。三项均通过后，仅开放短文本基础任务；价格证据不能替代质量评测，型号名称也不能抬高评级。

固定任务证据有效七天，认证请求的健康证据有效一天，日用成功请求可延续健康。过期时停止派发并要求重新测试；**普通后台刷新不偷偷调用模型补评测**。默认推理设置与显式推理强度分开，首批没有授予任何显式强度、工具、代码执行或视觉资格。输入最多 16000 UTF-8 字节、输出最多 2048 token。

多模型协作计划可以把低风险抽取、分类和字面转换标记为 `bounded-text`，使用专用基准 `bounded-text-v1`；最终仍由负责人审核。其他节点继续使用负责人质量基准。主模型与角色模型没有被自动替换，也不会因这三道题获得复杂规划或角色润色资格。

零价模型的“可用”表示新鲜官方价格证据和近期同账号成功请求，不表示知道剩余请求数。界面保留剩余额度未知，估算为零与实际现金账单未知分开。Agnes 另需确认 Free/default Key；Ollama Starter 和魔搭魔粒属于资源抵扣，未绑定可核验账户额度之前不会伪装成零单价候选。

## 运行工具与回滚

- `tools/activate_free_models.py`：显式选择至多三个型号，在发送保护下执行固定任务；`--activate` 只在通过后启用该 Profile，未通过的同 Profile 型号仍被任务证据门槛挡住。支持隔离数据库配合原 Credential Manager 命名空间，不复制 Key。
- `tools/register_spark_lite.py`：隐藏输入保存独立 Spark Lite HTTP APIPassword；`--provider moark` 保存 Moark 体验 Key，并固定关闭 `X-Failover-Enabled`。均不在注册时启用自动路由。
- `tools/evaluate_moark_candidates.py`：从当前官方目录筛选通用文本，支持`--all-free`及显式低价型号；默认预算0，`--cash-budget-cny`最多0.50。每次发送前按按次/Token两种模式较高费用预留，未知请求不退回预算，关闭故障转移。使用固定三题，仅记录元数据；建议在隔离数据目录使用原凭据引用，不替换日用配置。
- 原 SQLite 已备份至 `D:/Caches/sumika-free-catalog/before-free-routing-20260908.sqlite3`。回滚必须只恢复本阶段新增/修改的 Profile 状态与独立路由记录，不能直接覆盖之后产生的会话和用户数据。

## 本轮验收与日用启用

讯飞 `spark-x2.5-4b`、Agnes `agnes-2.5-flash` 已通过新增三项测试，并各经过一次隔离 Core → ModelPolicy 自动选择 → QualityRuntime → HTTP 发送保护的真实请求，结果与输出契约均通过；估计现金为零，未取得逐笔现金账单。报告 `D:/Caches/sumika-free-catalog/free-routing-core-smoke-20260908.json`。

讯飞 1.7B 没通过新增事实抽取契约；OpenRouter 的 LFM 与智谱 4.7 本轮返回 429，保持冷却、不宣称永久不可用。Ollama `gemma4:31b` 补测三项旧基础题通过，但 Starter 余额仍待绑定。Moark 三型号能返回内容，首道精确输出契约均未通过；这是格式/契约失败，不直接断言算术错误。所有凭据仅存 Windows Credential Manager。

Spark Lite 用户已提供无限量、并发 5、到期 `2036-12-31 00:18 +08:00` 的账户截图及 HTTP 凭据。已按官方协议适配整数`code=0`和`data:[DONE]`：缺模型回显保持未知，不虚构model/version，不能把`general`当成`lite`；缺终止帧或业务失败不得成功。真实接通后，事实抽取输出契约未过，因此不进入自动池。首次两次失败源于不兼容的通用完成判定，和最新质量失败分开记录；不是Key无效。报告 `spark-lite-adapted-formal-20260908.json`。

**日用已启用讯飞4B与Agnes2.5**：从隔离验收导入相同账号/执行版本的证据，保留原观察时间；更新这两个Profile可用状态，并追加到`sumika`助手协作候选池。日用 `ModelPolicy` 自动选择已返回Agnes2.5、估计现金0，无模型调用。负责人/角色绑定、选择模式及预算未改变；角色、模块、会话和消息表摘要前后一致。日用报告 `daily-free-routing-enabled-20260908.json`。正在运行的旧Core需正常重启才加载新源码；不改桌面快捷方式。

验证：后端全量952项通过；Spark适配及最后连线修改后122项相关测试通过，另有此前171项组合回归；前端5项测试与构建通过。包含来源解析、任务限制、免费撤回、账号/配置变更、到期、跨实例租约、429/402、旧请求不污染新账号，以及正式Core路径。测试夹具仍有一个HTTPError清理的ResourceWarning，不影响结果。

## Moark扩大目录与付费抽测（2026-09-08）

用户随后确认有¥10资源包余额，并授权适当付费测试；这替代此前仅体验的本轮范围。官方只读`GET https://api.moark.com/v1/tokens/packages/balance`实际确认初始总额10、已用0、余额10。该认证查询属于显式账户验收，不接入不读Key的公共刷新器。

`integrations/moark_catalog.py`读取官方公开目录，区分`text-generation`和专用任务，分别验证按次及输入/输出Token价格区间。`free_operation_count`即使非零也不能证明免费；例如GLM-5.3-Flash实际有Token价格。目录声明237项，只返回220项，第二页为空；保存不完整标记，不将隐藏条目推断为下线。

当前公开全零价通用文本共10款：DeepSeek-R1-Distill-Qwen的1.5B/7B/14B、internlm3-8b-instruct、Qwen3的0.6B/4B/8B、GLM-4-9B-0414、glm-4-9b-chat、Qwen2-7B-Instruct。另有10款专用服务：SenseVoiceSmall、GLM-ASR、Spark-TTS-0.5B、bce-reranker-base_v1、bge-reranker-v2-m3、HealthGPT-L14、Lingshu-32B、HuatuoGPT-o1-7B、DeepSeek-Prover-V2-7B、ip-location；专用服务只登记公开观察，不混入聊天池或宣称已验收。

官方[OpenAPI](https://moark.com/v1/yaml)声明模型名大小写不敏感且支持命名空间。仅对Moark精确官方端点接受同一型号的大小写及单层命名空间回显，拒绝路径、不同型号和未经声明的版本后缀。R1蒸馏/Qwen3实测可能将前导`<think>…</think>`放在正文，适配器只剥离完整前导思考块，保留回答内的字面标签及所有Token用量，截断思考块失败关闭。没有修改任务答案/JSON验收规则，也没有私自关闭思考。

首批12型号共14次调用，qwen3.8-flash三项契约全部通过；首批其他失败含协议/格式问题，不能全部解释为能力不足。随后按新适配复验：**免费Qwen3-8B三题全过，且隔离Core自动选择→QualityRuntime→真实HTTP执行通过，已加入日用候选池**。其他免费项仍有格式或内容错误，不抬高到合格；GLM-5.3-Flash仅前两题通过，补测第三题未过。低价qwen3.8-flash保留通过证据和观察项，未开启付费自动路由。日用Profile改名“Moark 官方 API”，凭据、原主模型、角色、预算及其他产品数据保留。

本次扩展累计30次模型调用，预留费用上界¥0.0501536，官方资源包总额10、已用¥0.0034866、余额¥9.9965134；这是资源包实际扣减，不是按估价推算。包括协议诊断、适配复验和独立Core smoke，不包含此前旧文章三款的抽样。所有请求关闭故障转移，没有充值、订阅或静默切付费。报告目录`D:/Caches/sumika-free-catalog/`：总览`moark-final-summary-20260908.json`，原始批次`moark-expanded-20260908.json`，复验`moark-adapted-20260908.json`，GLM第三题`moark-glm-final-check-20260908.json`，日用`moark-daily-enabled-20260908.json`，正式链路`moark-core-smoke-v2-20260908.json`。

`tools/moark_core_smoke.py`可复用隔离Core验收，要求数据目录与凭据目录不同；显式启用隔离LLM模块，关闭Agent自动启动。首次未启用模块的smoke实际0次调用，已修正原报告。旧Core需正常重启才加载新代码。后端全量968项通过，最后适配后153项专项通过；未改UI，不重复前端验收。当前Qwen3-8B固定题延迟约7–43秒，不宜视为最快候选；只授予基础短文本资格，不作为主模型或角色模型。
