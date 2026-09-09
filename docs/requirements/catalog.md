# Sumika 需求总表

更新：2026-09-09。共 **80项**：当前有效66项、长期延期6项、被后续决定取代8项。这里的“有效”是产品意图，**不是已实现**；正式验收条件在[机器总表](requirements.json)，功能事实只看[状态矩阵](../status-matrix.md)。

本轮将“统一到 Sumika 内置浏览器”确认为 `BROWSER-003`，详见[浏览器正式需求](embedded-browser.md)。同时补齐近期A+界面、质量路由、广泛福利发现、自动签到、高频维护零成本、付费授权及长期能力边界。

## 原话与证据如何读

[脱敏原话出处](original-excerpts.md)包含22条已逐字核实用户消息、61段短引文，附UTC时间、角色和本次核对行号。表中“新”表示本轮已核实消息；“旧摘要”只核对到旧Git文档，未恢复原始逐字消息；“待补”表示仅有旧基线来源。它们不能互相冒充。
`confirmed` 表示原来已确认的需求状态，不能据此声称其历史逐字原话已经恢复；`normalized` 为从原意归一化的可验收规则。

最新覆盖：`UX-001 → UX-002 → UX-003`；`AVATAR-002 → AVATAR-003`；`BROWSER-001 → BROWSER-003`；`BROWSER-002 → BROWSER-004`；`MODEL-009 → MODEL-015 / BENEFIT-002`；`MODEL-007 → MODEL-018`。安全和可访问性要求继续保留；后续授权改变的是适用范围，不是取消所有确认边界。

## 全部需求

| ID | 要求 | 意图 / 依据 | 原话索引 | 实现状态入口 |
| --- | --- | --- | --- | --- |
| `HISTORY-OLLAMA-DEFAULT` | 旧自动安装Ollama默认方案 | 已被取代 / `confirmed` | 旧摘要 `EX-HISTORY-001` | `local-llm` |
| `CORE-001` | 可日用的桌面Agent | 当前有效 / `confirmed` | 旧摘要 `EX-CORE-001` | `dsh-agent-runtime` |
| `PLATFORM-001` | Windows优先与跨平台边界 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `local-llm` |
| `UX-001` | 旧固定导航布局 | 已被取代 / `normalized` | 待补逐字出处；见旧基线 | `chat` |
| `CHAT-001` | 可靠聊天与明确错误 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `chat` |
| `CHARACTER-001` | 角色独立名称与身份 | 当前有效 / `confirmed` | 旧摘要 `EX-CHARACTER-001` | `characters` |
| `CHARACTER-002` | 人格配置实际生效 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `characters` |
| `AVATAR-001` | 自然VRM展示与观察 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `avatar-vrm-desktop` |
| `AVATAR-004` | 默认使用许可已核验的Sample A；安和昴等用户导入模型不上传、不打包 | 当前有效 / `confirmed` | 本次 `EX-AVATAR-DEFAULT-001` | `avatar-vrm-desktop` |
| `AVATAR-002` | 旧透明角色桌宠 | 已被取代 / `confirmed` | 旧摘要 `EX-AVATAR-001` | `avatar-vrm-desktop` |
| `PROVIDER-001` | 可复用Provider档案 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `provider-profiles` |
| `PROVIDER-002` | 本地模型由用户选择安装 | 当前有效 / `confirmed` | 旧摘要 `EX-HISTORY-001` | `local-llm` |
| `PROVIDER-003` | 凭据保护 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `provider-profiles` |
| `PROVIDER-004` | CC Switch受控导入 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `ccswitch-import` |
| `PROVIDER-005` | 不可用时明确失败 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `provider-profiles` |
| `PROVIDER-006` | 一份凭据多个独立Route | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-005` | `provider-profiles` |
| `AGENT-001` | 运行时与领域边界可替换 | 当前有效 / `confirmed` | 旧摘要 `EX-CORE-002` | `agent-runtime-portability` |
| `AGENT-002` | 真实Agent能力与恢复 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `dsh-agent-runtime` |
| `MCP-001` | 受控MCP配置调用 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `dsh-agent-runtime` |
| `SKILL-001` | 可审计Skill生命周期 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `dsh-agent-runtime` |
| `TASK-001` | Runtime任务状态唯一来源 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `tasks` |
| `WORKSPACE-001` | 工作区修改可恢复 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `tasks` |
| `PLUGIN-001` | 同类插件可替换 | 当前有效 / `confirmed` | 旧摘要 `EX-CORE-002` | `plugins-manifest` |
| `CAPABILITY-001` | 统一能力实现目录 | 当前有效 / `normalized` | 待补逐字出处；见旧基线 | `capability-catalog` |
| `DESKTOP-001` | 通用桌面软件适配器 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `desktop-automation` |
| `DESKTOP-002` | 桌面操作租约与权限 | 当前有效 / `normalized` | 待补逐字出处；见旧基线 | `desktop-automation` |
| `BROWSER-001` | 旧BrowserSkill固定机制与隔离边界 | 已被取代 / `confirmed` | 待补逐字出处；见旧基线 | `browser-runtime` |
| `BROWSER-002` | 旧五来源3+2咨询默认 | 已被取代 / `confirmed` | 旧摘要 `EX-BROWSER-002` | `web-chat-runtime` |
| `SEC-001` | 保留数据及授权删除边界 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `snapshots` |
| `STARTUP-001` | 可预测的一键启动退出 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `dsh-agent-runtime` |
| `OBS-001` | 有界脱敏观测 | 当前有效 / `confirmed` | 旧摘要 `EX-SEC-001` | `agent-observability` |
| `OBS-002` | 路由决策过程追踪 | 当前有效 / `confirmed` | 旧摘要 `EX-OBS-003` | `agent-observability` |
| `EVOLUTION-001` | 外部能力知识注册与评估 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `evolution-registry` |
| `LICENSE-001` | 素材代码来源及许可证 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `evolution-registry` |
| `MODEL-001` | 质量许可时优先已授权免费额度 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-001` | `model-policy` |
| `MODEL-002` | 可扩展模型目录 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-004` | `model-policy` |
| `MODEL-003` | ZCode支持的协议接入 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-001` | `model-policy` |
| `MODEL-004` | 智谱免费证据动态核验 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-001` | `model-policy` |
| `MODEL-005` | 满足质量门槛再优化成本 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-002` | `model-policy` |
| `MODEL-006` | 免费耗尽不静默转付费 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-002` | `model-policy` |
| `MODEL-007` | 旧推荐后确认默认 | 已被取代 / `confirmed` | 旧摘要 `EX-MODEL-003` | `model-policy` |
| `MODEL-008` | Ollama本地测试 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-004` | `local-llm` |
| `MODEL-009` | 旧额度刷新与手动领取约束 | 已被取代 / `confirmed` | 待补逐字出处；见旧基线 | `model-policy` |
| `MODEL-010` | 固定任务与可比样本评估 | 当前有效 / `confirmed` | 旧摘要 `EX-SEC-001`、旧摘要 `EX-SEC-002` | `agent-observability` |
| `MODEL-011` | 按Profile与计费分组隔离价格 | 当前有效 / `confirmed` | 旧摘要 `EX-MODEL-006` | `model-policy` |
| `MULTI-001` | 长期多角色独立状态 | 长期延期 / `confirmed` | 待补逐字出处；见旧基线 | `virtual-world` |
| `MEMORY-001` | 可替换且默认隔离的记忆 | 当前有效 / `confirmed` | 待补逐字出处；见旧基线 | `memory` |
| `PROCESS-001` | 可恢复的需求与决策 | 当前有效 / `confirmed` | 旧摘要 `EX-PROCESS-001`、新 `EX-PROCESS-002`、新 `EX-BROWSER-004` | `dsh-agent-runtime` |
| `PROCESS-002` | 重复问题故障手册 | 当前有效 / `confirmed` | 旧摘要 `EX-PROCESS-001` | `web-chat-runtime` |
| `TOOLING-001` | 公共工具与缓存复用 | 当前有效 / `confirmed` | 旧摘要 `EX-TOOLING-001` | `browser-runtime` |
| `OBS-003` | 运行结论交叉验证 | 当前有效 / `confirmed` | 旧摘要 `EX-OBS-004` | `web-chat-runtime` |
| `DEFERRED-001` | 旧长期能力延期总项 | 长期延期 / `confirmed` | 待补逐字出处；见旧基线 | `live2d` |
| `UX-002` | 旧深夜蓝场景与四抽屉 | 已被取代 / `confirmed` | 待补逐字出处；见旧基线 | `web-portals` |
| `UX-003` | 采用选定的 A+ 和风留白布局：五个文字入口、可收放右侧聊天、温暖日式二次元氛围与角色主题色扩展。 | 当前有效 / `confirmed` | 新 `EX-UI-003`、新 `EX-UI-004` | `scene-ui-shell` |
| `UX-004` | 能力页突出感知与交互、效率工具、生活与陪伴；页面模块独立添加、排序和移除。 | 当前有效 / `confirmed` | 新 `EX-UI-001`、新 `EX-UI-002`、新 `EX-UI-003` | `modules` |
| `UX-005` | 完整客户端可全屏固定在 Windows 桌面最底部，作为陪伴壁纸，并能恢复普通客户端。 | 当前有效 / `normalized` | 新 `EX-UI-004` | `desktop-wallpaper` |
| `AVATAR-003` | 完整客户端与桌宠共享助手、会话和生活状态；桌宠只保留场景、角色和紧凑聊天，可关闭场景变透明。 | 当前有效 / `confirmed` | 新 `EX-UI-001`、新 `EX-VISION-001` | `avatar-vrm-desktop` |
| `BROWSER-003` | 网页交互统一到 Sumika 自己的内置浏览器，覆盖聊天咨询、登录接管、价格额度查看、福利领取与签到。 | 当前有效 / `confirmed` | 新 `EX-BROWSER-003`、新 `EX-BROWSER-004`、新 `EX-PLAN-001` | `unified-browser` |
| `BROWSER-004` | 复杂任务按收益选择已登录网页进行辅助咨询，默认最多2–3来源，结果经主模型审查。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-004`、新 `EX-ROUTING-001` | `native-consultation` |
| `MODEL-012` | 模型候选身份同时包含Provider Profile、Route、Model、Transport、Harness和推理强度。 | 当前有效 / `confirmed` | 新 `EX-COST-001`、新 `EX-COST-002`、新 `EX-ROUTING-003` | `quality-selection` |
| `MODEL-013` | 质量以版本化多源榜单先验、官方能力、固定任务及真实使用证据逐步校准。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-003`、新 `EX-REFRESH-001`、新 `EX-MODEL-012` | `quality-selection` |
| `MODEL-014` | 主模型质量优先，执行者在满足任务质量门槛后按成本选择，角色模型独立按合格且便宜稳定选择。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-001`、新 `EX-ROUTING-003` | `quality-selection` |
| `MODEL-015` | 用确定性脚本分别刷新资源包、价格和目录，维护最新证据并保留过期历史。 | 当前有效 / `confirmed` | 新 `EX-REFRESH-001` | `model-refresh` |
| `MODEL-016` | 资源包作为账户级共享池记账，保留适用范围、余量、真实到期、来源、可信度和在途预留。 | 当前有效 / `confirmed` | 新 `EX-REFRESH-001` | `model-refresh` |
| `MODEL-017` | 成本按规划、执行、验证、咨询、重试和升级估算；预算阈值默认两倍且超出5元，用户可调整。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-002`、新 `EX-ROUTING-003`、新 `EX-COST-002` | `quality-routing-workflow` |
| `MODEL-018` | 普通任务可在已授权渠道的可用余额与预算内使用付费模型；同名跨渠道按任务质量和实际报价比较。 | 当前有效 / `normalized` | 新 `EX-COST-003`、新 `EX-ROUTING-001`、新 `EX-COST-002` | `model-policy` |
| `MODEL-019` | 模型能力页展示刷新状态、免费证据、额度到期、主模型和角色模型及选择依据，并提供手动刷新、固定模型和预算设置。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-003`、新 `EX-REFRESH-001`、新 `EX-ROUTING-002` | `quality-routing-workflow` |
| `MODEL-020` | model-picker只提供目录、价格和评测建议，Sumika保留最终授权、额度、付费与执行决策。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-003`、新 `EX-PLAN-001` | `model-picker-adapter` |
| `TASK-002` | 复杂任务使用可修订DAG，在执行、验证、重试、升级和重新规划中维护任务契约。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-004`、新 `EX-PLAN-001` | `quality-routing-workflow` |
| `BENEFIT-001` | 广泛发现免费和限免模型权益，覆盖未注册新站，聚合官方与资讯来源并核验。 | 当前有效 / `confirmed` | 新 `EX-BENEFIT-001`、新 `EX-BENEFIT-002`、新 `EX-BENEFIT-003`、新 `EX-BENEFIT-004` | `free-benefits` |
| `BENEFIT-002` | 在已授权站点与明确免费范围内自动领取权益和签到，并核验实际到账。 | 当前有效 / `confirmed` | 新 `EX-BENEFIT-001`、新 `EX-BROWSER-004` | `free-benefits` |
| `BENEFIT-003` | 高频发现、刷新、签到默认使用零模型成本的固定流程，必要语义处理只用合格免费或本地模型。 | 当前有效 / `normalized` | 新 `EX-COST-003`、新 `EX-REFRESH-001`、新 `EX-BENEFIT-004` | `free-benefits` |
| `PLUGIN-002` | 质量路由抽成运行时中立核心与宿主适配器，可面向社区复用；Codex Skill不直接作为Sumika Runtime。 | 当前有效 / `confirmed` | 新 `EX-ROUTING-001`、新 `EX-ROUTING-003`、新 `EX-PLAN-001` | `quality-routing-core` |
| `COST-001` | Codex成本Skill先独立服务当前Codex，用任务协议、能力注册、确定性估算和共享脱敏账本辅助有收益的委派。 | 当前有效 / `confirmed` | 新 `EX-PLAN-001`、新 `EX-COST-001`、新 `EX-COST-002` | `cost-routing-protocol` |
| `INPUT-001` | 语音先实现点击或按住说话与TTS，后续才考虑持续监听。 | 长期延期 / `confirmed` | 新 `EX-PLAN-001`、新 `EX-VISION-001` | `audio` |
| `INPUT-002` | 视觉先实现单次屏幕/摄像头观察及OCR、截屏翻译；视频游戏陪伴先只读观察和评论。 | 长期延期 / `confirmed` | 新 `EX-PLAN-001`、新 `EX-VISION-001`、新 `EX-UI-003` | `vision` |
| `WORLD-001` | 虚拟居所分步实现固定房间、活动点、摄像头与用户日程加有限主动性。 | 长期延期 / `confirmed` | 新 `EX-VISION-001`、新 `EX-PLAN-001`、新 `EX-UI-001` | `virtual-world` |
| `RESOURCE-001` | 角色、Avatar、声音与场景使用版本化本地资源包。 | 当前有效 / `normalized` | 新 `EX-PLAN-001`、新 `EX-VISION-001` | `domain-contracts` |
| `DEVICE-001` | 现实身体能力先局域网发现与只读摄像头/传感器，安全网关完成后再做设备控制。 | 长期延期 / `confirmed` | 新 `EX-PLAN-001`、新 `EX-VISION-001` | `real-devices` |
| `MULTI-002` | 当前预留assistant_id、独立模型绑定与记忆命名空间；多助手同屏及交流分阶段实现。 | 当前有效 / `normalized` | 新 `EX-PLAN-001`、新 `EX-ROUTING-002` | `domain-contracts` |

## 交给下一位实现者

先读本表及 `active`/`deferred` 需求，再读对应原话和[执行契约](../current-execution.md)，最后核对代码、测试、当前运行证据。旧计划保留历史价值，不能覆盖更新后的A+导航、普通任务付费授权或内置浏览器需求。

本轮完成的是需求整理。浏览器统一、桌面壁纸、全部渠道报价/额度对账、真实跨渠道协作及延期能力仍有各自缺口；单个免费模型可用不代表所有已登记模型可路由。
