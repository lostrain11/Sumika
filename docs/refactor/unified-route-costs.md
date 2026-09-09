# 路由统一报价与资金来源

本轮落实用户要求：统一旧 `ModelRouter` 与质量协作执行者的成本比较，并区分赠送额度、已购资源包和现金余额。关联需求为 `MODEL-012`、`MODEL-016`、`MODEL-017`、`MODEL-018`；功能状态见[状态矩阵](../status-matrix.md)。

## 选择规则

两个入口共用 `ModelPolicyService.candidate_pricing()` → `RoutePricingService.quote()` → 独立核心 `quote_cost()`。官方、中转和不同计费组分别取自身的新鲜价格，不按模型名字套用官方价格；缓存计费、动态表达式、上下文阶梯与现金折算沿用现有计价器。

- 先满足授权、健康、能力、任务质量及资源可用性；旧入口采用质量门槛，协作节点仍要求任务对应的等价证据，二者不互相替代评测。
- 合格执行者和角色模型共用 `cost_order()` 比较有效成本；不再让“质量档更高”或笼统“便宜档”压过真实报价。用户显式固定选择仍优先。
- 自动主模型继续按固定评测质量、榜单先验选择，不按便宜程度降档。
- 未知价格不能作为零价参与排序；原确认和发送前权限检查保留，统一报价不代表所有渠道已放行。

## 资金语义

| 资金 | 必要证据 | 报价与免费判断 |
| --- | --- | --- |
| `grant` 赠送资源 | 明确来源、账户绑定、可预留量、单位、到期时间 | 足够覆盖本次请求时现金及资源购入成本为零 |
| `purchased` 已购资源 | 上述信息，加有证据的 `value_per_unit_cny` | 本次现金扣减可为零，但按消耗量计算已购资源价值；不算免费 |
| `cash` 现金余额 | 明确现金类型、CNY单位、新鲜观测和相同账户修订 | 按渠道费率计算扣减；余额只用于可用性检查，不抵消调用成本 |
| `unknown` 来源未知 | 缺少来源或购入价值 | 保留未知，不能因为余额大于零、资源包名称或购买时间就当免费 |

已购资源的单位价值来自实际购入证据，不从官方token价格反推。旧快照未声明来源时默认 `unknown`，不改写历史余额。

`RouteQuote` 将以下字段分开：

- `cash_due_cny`：本次预计现金扣减；
- `resource_value_cny`：已购资源预计消耗的购入价值；
- `effective_cost_cny`：两者之和，用于路由比较；缺少任何必要价值时为未知；
- `provider_charge` / `provider_currency`：渠道计价金额及单位，不能跨币种直接排序；
- `allocations`：预期使用的资源、性质、数量、单位和到期时间；
- `available` / `reason` / `free`：可用性、依据及是否满足免费策略。

多包按最早到期分配；相同成本时优先使用即将到期的赠送资源。绑定资源不足、过期、账户不符或无法确定混合单位扣减顺序时停止派发，不静默转现金。预留保留资金来源，token资源和按次资源分别扣减；提交状态不明时仍保留预留。

资金性质、单位价值或费率变化进入候选执行修订；余额消耗不作为费率版本变化。发送前重新报价并检查资源，不能用过时计划继续消耗已不足的资源。

## 展示和兼容

质量协作的候选选项区分赠送、已购资源消耗、现金余额和未知来源。目录里的 `cost_quote_workload` 明确参考输入4000、输出1000 token；实际计划按节点规模重新报价，这不是实际账单。

独立SDK提供 `FundingLot`、`RouteQuote`、`quote_cost`、`cost_order`。`Candidate.quote()` 返回明细，`Candidate.estimate()` 返回用于排序和预算的有效成本。旧 `prepaid_tokens` 仍可读取，但未声明来源时不再被当作免费，耗尽也不退回现金费率。宿主继续负责授权、账户绑定、预留和回执；详情见[SDK说明](../../packages/quality-routing/README.md)。

## 验证与限制

2026-09-08在包含原工作区改动的隔离副本验证：后端全量983项通过；随后收紧旧目录免费标签判断，并修正现金/有效成本分别输出，相关82项通过。独立核心52项运行通过（其中2项可选MCP跳过）。资金wrapper三项修复后后端全量1022项于117秒通过，只有既有HTTPError 429 `ResourceWarning`；前端相关7项和生产构建通过。此前前端全量47项中46项通过，剩余既有 `capability-layout.test.js` 错误文案断言失败，与本轮报价无关。

[跨入口合同测试](../../backend/tests/test_route_cost_consistency.py)覆盖两路选择、主模型/角色差异、缓存与动态价格、币种与计费组隔离、现金不足、账户变化、来源未知、资源持久化和免费重选；[核心资金测试](../../packages/quality-routing/tests/test_costs.py)覆盖购入价值、赠送期限和不足不转现金。

统一报价基线阶段没有真实模型调用或日用绑定修改。随后账户与主／角色工作包已合回并启用，详见[最终验收](model-activation-and-accounts.md)；以下区分当前能力与仍待补证的部分：

- 宿主既有token/次数资源继续可用；新FundingLedger接入CNY现金、赠金及已购资源，多币种自动换汇尚未实现。
- DeepSeek/Moark已接现金或已购包并发预留及明确回执对账接口；渠道未提供精确逐请求回执时，保留待对账状态。
- 预测报价不等于实际支付；未取得可归属账单时实际费用保持未知。
- 旧/新入口统一的是报价和合格执行者成本排序；任务质量判定、计划生命周期和既有确认入口继续各司其职。

## 2026-09-08 隔离主／角色与账户验收

隔离 Core 工作流以 DeepSeek Pro 规划、Agnes 2.5 执行、DeepSeek Pro 验收、Agnes 2.5 交付完成；规划、已验证执行、事实正确和交付四项检查均成功。该证据来自本机脱敏缓存 `D:/Caches/sumika-model-activation-20260908/core-role-smoke-v2.json`，不记录模型正文、Key、Cookie或页面内容。

本次真实调用经过账户包装器和账本预留。缓存中的 `estimated_cny`、`estimated_provider_cny` 与 `estimated` reservation 仅是按用量和当时价格计算的估算；所有 `actual_cash_cny` 均为 `null`，没有可归属的账单或实际扣费结论。关闭、零usage和价格快照的资金边界已由账户专项测试覆盖，不能将估算写成账单。

门户宿主刷新也在隔离环境通过：ModelScope只读投影显示242魔粒及9月8日两条1天grant（50、200），以北京时间次日零时作为保守边界；网页/API账户身份和型号扣费分类仍未确认。Ollama Starter显示六款限定模型、0% used、Extra余额0美元和原样reset文本，但不显示绝对免费额度。两者均保持不可自动路由，不能以余额、百分比或旧快照推导免费可执行。

API `role_runtime` 经 `ProviderProfileManager.runtime_wrapper` 统一包装，直传messages、tools和usage并复用资金/免费预留；`_RoleWorker`仅承担非API路径。随后普通chat真实使用Agnes并正常回复；日用主模型Pro、角色Agnes及四个账户/门户绑定已启用，新Core选择检查通过。普通聊天的自主工具请求、付费planning确认、长期质量等价、真实账单归属和未量化的门户权益仍分别验收。

## 相关文档

- [模型策略需求](../requirements/model-policy.md)
- [正式免费路由](free-model-routing.md)
- [质量协作](quality-routing.md)
- [当前执行契约](../current-execution.md)
