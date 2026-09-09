# Sumika 状态矩阵

本表是项目功能状态的唯一事实源。`已实现` 表示当前首版有可验证入口，
`部分实现` 表示协议或参考实现存在但默认能力、真实后端或隔离边界仍缺失，
`规划中` 表示只保留架构位置或设计方向。

| ID | 状态 | 当前入口 | 主文档 | 验证证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `free-model-routing` | 部分实现 | ModelPolicy自动选择、质量协作候选池、设置/能力中的刷新状态 | [正式免费路由](refactor/free-model-routing.md) | 阶段说明：三项正式接入并启用日用。讯飞4B、Agnes2.5、Moark Qwen3-8B均通过新固定任务及隔离Core真实自动选择/执行；日用已启用，估计现金0。负责人/角色/预算及产品数据保持。968项后端全量通过，最后适配后153项专项；已有前端/构建证据保留；依据：[正式免费路由](refactor/free-model-routing.md) | 逐Profile六小时价格刷新、账号与执行版本绑定、冷却、免费撤回及到期阻断已实现；额度型服务尚待账户对账，不承诺全部模型自动可用。Spark Lite接通但质量契约未过 |
| `moark-candidates` | 部分实现 | 日用`moark-free-candidates`；刷新状态与协作池 | [模型启用与账户](refactor/model-activation-and-accounts.md)、[目录实测](refactor/free-model-routing.md) | 免费Qwen3-8B保留，qwen3.8-flash已有角色专项，9月9日新增leader/bounded各三题及隔离协作通过，不改日用绑定。71条官方回执中34笔trace精确对账，合计0.1390319元；04:15 UTC已购包余额9.8541645元；[续验收](refactor/model-activation-and-accounts.md#9月9日闭环与精确对账) | 不将已购包算免费；37笔无trace旧回执不猜配，0.00013元未决预留保留。专项证据不代表全领域等质，GLM-5.3-Flash旧契约未过 |
| `free-benefits` | 部分实现 | 设置/能力 > 免费资源与签到；`benefits.*` RPC；进程内维护 | [实现与运行](refactor/free-benefits.md) | 阶段说明：广泛发现与魔搭每日核验首版完成。12个公开来源，实采10个成功；23项官网证据含20个模型声明及3家新渠道权益。Bing/V2EX此次无合格资讯；Groq/LD待核对。魔搭真实核验250发放、242余额；本实例已启用，下次正常启动维护。858项后端基线与最终109项专项、35项前端、11项DOM、3项浏览器验收及构建通过；依据：[实现与运行](refactor/free-benefits.md) | 新站只观察，不自动注册或放行路由；自动领取适配仅魔搭。关闭Sumika后不联网，无AI刷新调用；前端全量45/46，旧能力页文案断言未修。预览8882为无凭据隔离副本 |
| `modelscope-candidates` | 部分实现 | 日用观察目录；福利签到与账户只读刷新 | [模型启用与账户](refactor/model-activation-and-accounts.md)、[每日流程](refactor/free-benefits.md) | 阶段说明：既有两Qwen基础题通过；9月9日正式刷新250魔粒、当日登录200及绑定50，保守有效至北京时间9月10日00:00。门户已在日用绑定，刷新不调用模型；未知项不转为免费可执行。；[验收记录](refactor/model-activation-and-accounts.md) | 网页与API账户同一性、精确到期和单型号魔粒计费/对账未齐，仍不可自动路由；不重复已有基础评测 |
| `ollama-cloud-candidates` | 部分实现 | 独立云端连接、日用门户观察 | [模型启用与账户](refactor/model-activation-and-accounts.md)、[已有实测](refactor/free-model-routing.md) | 阶段说明：20B/Gemma基础实测保留；历史Starter页面显示0% used、六款限定模型和Extra余额0美元；9月9日本次missing-usage-section标needs-review。绝对免费额度不展示，remaining保持null。；[验收记录](refactor/model-activation-and-accounts.md) | 取得可量化Starter权益及消耗证据后再绑定资金与路由；不由百分比猜余额，不因402充值 |
| `siliconflow-translation` | 部分实现 | 独立`evaluate_siliconflow_translation.py`，无运行时入口 | [翻译补测](refactor/quality-routing.md#ollama-cloud与翻译能力补测2026-09-08) | 阶段说明：基础关键词检查2/3，未准入。实时核对混元MT7B公开零价/认证目录；英译中动作、日译中状态通过，时间/编号严格保留未过；3次输入82/输出35，账单未知；依据：[翻译补测](refactor/quality-routing.md#ollama-cloud与翻译能力补测2026-09-08) | 不从关键词通过推导完整语义质量，不入通用聊天池；OCR、屏幕及真实截屏翻译尚未测试 |
| `xfyun-candidates` | 部分实现 | 日用Provider `xfyun-free-candidates`；自动选择及发送前免费保护 | [正式免费路由](refactor/free-model-routing.md) | 阶段说明：4B已正式接入，1.7B保留观察。4B新增三项固定任务及Core真实自动执行通过，已加入日用池；1.7B新事实抽取契约未过，不能共享4B资格。此前403已由用户开通解决；依据：[正式免费路由](refactor/free-model-routing.md) | 六小时核验官方价格；限时截止未公开，证据撤回/过期就阻断，不自动转付费。OCR/向量/重排另行评测 |
| `openrouter-free-candidates` | 部分实现 | 日用Provider `openrouter-free-candidates`；ModelPolicy候选目录 | [最新实测](refactor/quality-routing.md#agnes文本验收与其他渠道复核2026-09-08) | 阶段说明：已授权保存，评测受限。Key认证通过，普通免费层级；公开目录16个零价变体；Gemma 4 31B及新测26B均首题429后停止，无重发，16项不可路由；依据：[最新实测](refactor/quality-routing.md#agnes文本验收与其他渠道复核2026-09-08) | 429不证明账号已耗尽或全部型号无效；不充值、放宽隐私或静默付费回退 |
| `agnes-candidates` | 部分实现 | 日用Provider、角色自动选择及短文本执行者 | [模型启用与账户](refactor/model-activation-and-accounts.md)、[正式免费路由](refactor/free-model-routing.md) | 阶段说明：2.5的Free/default免费证据及旧短文本评测保留；新增角色事实/不确定性/边界3题通过并人工复核，已启用为日用角色。Core跨渠道交付和普通chat.send均有真实成功证据。；[验收记录](refactor/model-activation-and-accounts.md) | 六小时复核价格，失败不转付费；不授予负责人或复杂任务等质资格，不能沿用2.0旧免费结论 |
| `article-provider-observations` | 部分实现 | 独立Provider、观察目录与[十渠道表](refactor/free-provider-audit.md) | [正式免费路由](refactor/free-model-routing.md) | 阶段说明：十项逐项核清，八渠道有实测记录。Spark Lite已接通，事实抽取契约未过；Moark后续扩大至12款文本并启用免费Qwen3-8B，详见独立条目。Ollama Gemma补测三题通过，仍待Starter额度绑定；依据：[正式免费路由](refactor/free-model-routing.md) | NVIDIA OTP、Intern不可用继续暂停；不充值、不推断永久无限、不同协议/渠道不共享质量与额度证据 |
| `siliconflow-candidates` | 部分实现 | 日用Provider `siliconflow-free-candidates`；ModelPolicy候选目录 | [硅基实测](refactor/quality-routing.md#硅基流动有界实测2026-09-08) | 阶段说明：已实测，质量/稳定性未达准入。用户授权后5次有界请求：GLM三次正常响应，文本替换通过，算术/JSON严格契约未过；Qwen/R1各30秒超时未重发。已知输入94/输出32 token，费用未知；仅回写模型健康，3项不可路由，其他配置/执行版本不变；相关工具23项测试通过；依据：[硅基实测](refactor/quality-routing.md#硅基流动有界实测2026-09-08) | 不再要求截图作为测试授权；补任务适配与独立质量证据，不能将严格格式失败说成算术错误。混元翻译补测见独立条目，PaddleOCR仍仅观察；旧目录健康routable及型号猜档不能替代质量准入 |
| `deepseek-candidates` | 部分实现 | 日用Provider、主模型自动选择、账户资金 | [模型启用与账户](refactor/model-activation-and-accounts.md) | 阶段说明：Pro/Flash各3道规划专项通过，版本独立记录；Pro已作为同分首选日用主模型，Flash保留候选。真实Pro规划和验收通过；价格按官方高峰上界，9月9日官方现金观测2.53元、赠金0，隔离未对账预留2.7831168元，禁止以新余额直接吸收旧调用。；[验收记录](refactor/model-activation-and-accounts.md) | 三道基础题不证明复杂任务同质；视觉型号仍待评测，实际逐请求账单未取得；不依据型号名字伪造评分 |
| `quality-routing-core` | 已实现 | 独立Python SDK，宿主注入执行/验证/权限 | [独立包](../packages/quality-routing/README.md)、[统一报价](refactor/unified-route-costs.md) | 2026-09-08核心53项运行通过（2项可选MCP跳过）；公共RouteQuote区分赠送/已购/现金；逻辑质量基线与真实审核模型分别计价，4000审核token纳入预算。执行版本保持绑定，历史MCP验收保留。；[验收记录](refactor/model-activation-and-accounts.md) | 按真实任务采集质量证据；测试通过不代表任意便宜模型与负责人等质 |
| `unified-route-costs` | 已实现 | ModelPolicy / quality协作 / 角色自动选择 / 账户展示 | [统一报价](refactor/unified-route-costs.md)、[工作包2–4](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | 赠送/已购/现金共享报价、组合预留；新增Moark精确日志读取及trace/型号/账号/资源包匹配对账，同包装器并发保护；[验收记录](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | 没有trace的旧请求不能猜配；DeepSeek精确账单、ModelScope/Ollama可量化权益仍缺；新余额不能直接释放旧预留 |
| `model-refresh` | 部分实现 | `model.policy.refresh`/status；能力与质量协作设置 | [工作包2–4](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08)、[刷新工具](../tools/refresh_model_catalog.py) | 维护不调用模型；native维护桥启动时序与重连已修，9月9日魔搭250魔粒及Moark71条回执正式刷新通过；Ollama本次missing-usage-section，保留历史但不伪装新鲜；[验收记录](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | 各站native登录、型号扣费、账户同一性、绝对权益和官方逐请求回执尚有缺口 |
| `quality-selection` | 部分实现 | 每助手固定/自动模式、候选池、选择理由 | [模型启用与账户](refactor/model-activation-and-accounts.md)、[选择测试](../backend/tests/test_quality_selection.py) | 阶段说明：已启用日用auto主/角色，独立新Core实际选择DeepSeek V4 Pro与Agnes2.5；两组主模型和两组角色各3题，Pro仅是专项同分首选。4项激活测试覆盖幂等、原设置保留和执行修订失效。；[验收记录](refactor/model-activation-and-accounts.md) | 权威榜单先验与复杂任务证据继续补齐；基础题不是长期等质证明。智谱4.7/4.6V当前健康/契约缺口仍独立保留 |
| `quality-routing-workflow` | 部分实现 | 质量协作设置、工作台任务、`quality.*` RPC、角色聊天 | [工作包2–4](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08)、[复杂工作流测试](../backend/tests/test_quality_complex.py) | 原Pro/Agnes四节点协作保留；9月9日Moark资金支持下补齐真实替补完成终稿、目标9→10重新确认及生产前端ChatGPT咨询交回主模型三个验收。替补须独立达标，JSON-only允许合法空白；[闭环证据](refactor/model-activation-and-accounts.md#9月9日闭环与精确对账) | 工作包4本轮文本闭环已验收；故障由宿主注入，不当作Agnes能力失败；工作区工具、ZCode及中转仍分别验收。DeepSeek旧预留未对账，不绕过余额保护 |
| `native-consultation` | 已实现 | 内置浏览器 > ChatGPT咨询 | [桌面壳](architecture/desktop-shell.md)、[工作包2–4](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | Google SSO、重启保持登录通过；9月9日真实生产前端poll/原生收发/complete到隔离主模型规划与审查通过，领取1次、完成1次、无未知提交。零调用清理测试确认恢复日用桥；[闭环证据](refactor/model-activation-and-accounts.md#9月9日闭环与精确对账) | 当前首期ChatGPT合成文本闭环；不代表其他站点，不迁Cookie、不全放行SSO、不重发未决请求 |
| `domain-contracts` | 部分实现 | Python 内部 `sumika_core.domain`，未接入 RPC/UI | [领域契约](architecture/README.md#产品领域契约重构-phase-1) | [value contracts](../backend/src/sumika_core/domain/contracts.py)、[legacy projections](../backend/src/sumika_core/domain/projections.py)、[contract tests](../backend/tests/test_domain_contracts.py)、[projection tests](../backend/tests/test_domain_projections.py)、[阶段任务包](refactor/phase-1-contract-task.json) | 重构 Phase 1 新契约与只读兼容投影；Policy/Task/Evaluation 沿用既有权威契约。首期场景 UI 模块化已完成，领域应用服务接线仍独立待做；不代表虚拟世界、共享记忆或设备能力已启用 |
| `a-plus-ui-concept` | 已实现 | 保留独立 A+ 原型，正式客户端采用选定布局 | [A+ 原型](ui/concepts/a-plus-v1/README.md)、[正式客户端](ui/a-plus-client.md) | [原型验收](ui/concepts/a-plus-v1/exports/verification.json) 37/37、18 张 PNG 为历史设计证据；生产代码和原生验收见下一行 | 阶段 0 设计冻结、阶段 1 交互原型已交付；壁纸构图仅为演示，不代表 WorkerW 或生活模拟 |
| `scene-ui-shell` | 已实现 | A+ 五项文字导航、可收放聊天、能力分类与纯加号模块库；同窗口 workspace/pet | [A+ 客户端](ui/a-plus-client.md) | [scene view](../frontend/src/a-plus-scene-view.js)、[能力页](../frontend/src/capability-page.js)、[布局](../frontend/src/a-plus-layout.css)、[回归](../frontend/tests/a-plus.spec.js)、[原生 smoke](../tools/native-ui-smoke.mjs)；2026-09-07 前端单测 10/10、完整浏览器回归 62/62、Rust 12/12、生产构建及原生单窗口/尺寸/草稿/最大化/暂停/透明像素通过 | 阶段 2 已接真实前端契约，原有 Provider、模型策略、审批和数据边界保留。Windows 壁纸层、门户内嵌、新音视频、居所自主生活、多助手与设备不包含在本期；所有旧稿保留 |
| `scene-ui-store` | 已实现 | `main.js` 消费不可变 scene/module 投影；独立视图状态保留折叠、焦点、滚动和当前角色未保存字段 | [架构与 Phase 2b](architecture/README.md#phase-2b纯场景状态投影) | [scene store](../frontend/src/scene-store.js)、[module selector](../frontend/src/module-selector.js)、[view state](../frontend/src/view-state.js)、[focused test](../frontend/tests/scene-store.test.js)、[UI 回归](../frontend/tests/ui-refactor.spec.js)；前端单测/构建/59 项 smoke 通过，未编辑字段不覆盖服务端更新，草稿不跨角色复制 | 业务状态与 HTTP/RPC 仍由装配层拥有；未来按独立应用服务逐步接线，不把瞬时视图状态当作 Runtime 或授权事实源 |
| `local-llm` | 已实现 | Modules > 自定义连接（默认关闭）；隔离测试可选 `qwen3:1.7b`，日常默认保持用户选择 | [local-model](architecture/local-model.md) | [setup script](../tools/setup-ollama.ps1)、[provider tests](../backend/tests/test_providers.py)、[DSH smoke](../tools/smoke_dsh_round.py) | 原生 macOS/Linux 启动器与更多本地运行时验证 |
| `provider-profiles` | 已实现 | Modules > 实现方式 | [provider profiles](architecture/provider-profiles.md) | [profile tests](../backend/tests/test_provider_profiles.py)、[pricing tests](../backend/tests/test_route_pricing.py)、[UI smoke](../frontend/tests/smoke.spec.js)；认证模型目录可合并为一档案多个独立 Route，Direct Official/New API/PinAI/Manual 双口径定价已有固定夹具 | 使用用户重新录入的真实凭据分别做低成本目录、usage 和费用回执冒烟；增加更多已测试协议适配器 |
| `ccswitch-import` | 已实现 | Modules > 自定义连接、Developer | [CC Switch](integrations/cc-switch.md) | [compatibility tests](../backend/tests/test_ccswitch_compatibility.py)、[checker](../tools/check_ccswitch_compatibility.py) | 按固定基线人工审查上游更新 |
| `chat` | 已实现 | Chat | [protocol](architecture/protocol.md) | [server tests](../backend/tests/test_server.py)、[frontend shell](../frontend/main.js) | 持续完善流式状态与错误呈现 |
| `characters` | 已实现 | Characters（身份 / 人格 / 高级设置） | [characters](architecture/characters.md) | [persona tests](../backend/tests/test_persona.py)、[character card import](../backend/src/sumika_core/character_import.py)、[import tests](../backend/tests/test_character_import.py)、[server tests](../backend/tests/test_server.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 已支持 SillyTavern V1/V2/V3 角色卡导入（JSON/PNG/CHARX，`character.import_card` + 角色页导入按钮）；剩余：世界书（character_book）运行时注入、Agent 通道 persona 投影，以及真实音频/立绘运行时完成后的对应配置 |
| `modules` | 已实现 | Modules | [modules](architecture/modules.md) | [module tests](../backend/tests/test_modules.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 继续增加真实可替换实现 |
| `capability-catalog` | 已实现 | 设置 > 开发者 > 统一能力目录（唯一审计入口） | [modules](architecture/modules.md) | [catalog implementation](../backend/src/sumika_core/capabilities.py)、[catalog tests](../backend/tests/test_capabilities.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 接入第二个真实 Harness/插件后继续验证跨运行时和同类实现对比 |
| `desktop-automation` | 部分实现 | Developer > capability catalog；DSH 可选 `desktop_app_*` bridge；显式 `enable_cdp` 后可连接 loopback Electron CDP | [desktop automation](architecture/desktop-automation.md) | [contracts](../backend/src/sumika_core/desktop_automation/contracts.py)、[runtime](../backend/src/sumika_core/desktop_automation/runtime.py)、[adapter tests](../backend/tests/test_desktop_automation.py)、[CDP transport tests](../backend/tests/test_cdp_transport.py)、[DSH bridge](../plugins/dsh-desktop-automation/README.md)、[policy tests](../plugins/dsh-desktop-automation/test/policy.test.mjs)；2026-08-31 用户启动的 ZCode Electron `9222` 已通过 `health`、已有 page target `open` 和不读正文的 `observe` smoke | 继续在明确动作审批下验证受限 click/fill/send；保持应用登记、租约、敏感输入隔离和前台接管默认关闭，不把只读 smoke 扩大为登录或真实消息发送 |
| `model-policy` | 部分实现 | Agent > 模型策略；`model.policy.*` RPC | [model policy](requirements/model-policy.md) | [policy implementation](../backend/src/sumika_core/model_policy.py)、[pricing implementation](../backend/src/sumika_core/route_pricing.py)、[dynamic supervisor](../backend/src/sumika_core/agent/supervisor.py)、[policy tests](../backend/tests/test_model_policy.py)、[pricing tests](../backend/tests/test_route_pricing.py)、[route tests](../backend/tests/test_dynamic_route_supervisor.py)、[ZCode tests](../backend/tests/test_zcode_runtime.py)、[UI smoke](../frontend/tests/smoke.spec.js)；ZCode modern wire fixture 覆盖 `session/list`、workspace model catalog、MCP 和事件；Windows 自动发现实测读取 2 个 Z.AI 模型，公开额度仍为 `unknown` | 接入真实 ZCode/Provider 额度来源、积累固定评测样本并校准质量评分；按MODEL-018沿用范围授权，禁止越权付费 |
| `model-picker-adapter` | 部分实现 | 显式设置 `SUMIKA_MODEL_PICKER_URL` 后进入只读外部目录；不提供执行 Worker | [Phase 4 adapter](refactor/phase-4-model-picker-adapter.json)、[redundancy report](refactor/redundancy-report.md) | [adapter](../backend/src/sumika_core/integrations/model_picker/adapter.py)、[adapter tests](../backend/tests/test_model_picker_adapter.py)、`model-picker` `/catalog` `/evaluations` HTTP tests；覆盖 remote identity、官方/中转价格分离、stale、unknown quota、重复身份和失败关闭 | 为实际 Sumika profile 增加显式映射后，仍由 Policy/Runtime 重新健康、授权、额度、隐私和付费确认；不把 picker advisory route 当作可执行 route |
| `tasks` | 部分实现 | Tasks、Agent > Workspace 安全与回滚 | [tasks](architecture/tasks.md) | [task tests](../backend/tests/test_tasks.py)、[runner tests](../backend/tests/test_task_runner.py)、[WorkspaceRuntime tests](../backend/tests/test_workspace_runtime.py)、[Agent server tests](../backend/tests/test_agent_server.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)、[daily acceptance](../tools/agent_daily_acceptance.py) | Execute 与 Plan Review 批准前 checkpoint、独立 worktree、patch 审阅、审批式本地 commit、turn/产物只读投影和 Sumika 自修改/恢复已闭环；真实 Provider 结果已进入重复验收，继续完成小型实际改动和浏览器人工接管 |
| `avatar-vrm-desktop` | 已实现 | Chat、Characters、透明桌宠模式 | [Avatar](architecture/avatar.md)、[desktop shell](architecture/desktop-shell.md) | [avatar tests](../backend/tests/test_avatar.py)、[UI smoke](../frontend/tests/smoke.spec.js) | Live2D 驱动与更多动作资源审计 |
| `web-portals` | 已实现 | 桌面内置浏览器标签区 | [desktop shell](architecture/desktop-shell.md)、[工作包2–4](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | 门户改为主窗口child，原portals目录原位复用；同账户/同目录校验、背景打开不抢视口、同站不同路径分标签，真实Tauri smoke通过；[验收记录](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | 不是全部站点登录成功的证明；BrowserSkill及咨询档案不静默合并，不支持站点明确手动或兼容限制 |
| `plugins-manifest` | 部分实现 | Developer | [manifest](architecture/manifest.md) | [plugin tests](../backend/tests/test_plugins.py) | 隔离 Runner、签名与依赖管理 |
| `audio` | 部分实现 | Modules（默认关闭） | [audio](architecture/audio.md) | [audio tests](../backend/tests/test_audio.py) | 接入真实 ASR/TTS/VAD 软件并完善权限 UI |
| `memory` | 部分实现 | History / Modules（默认关闭） | [memory](architecture/memory.md) | [memory tests](../backend/tests/test_memory.py) | 检索策略、合并确认与更多外部后端 |
| `vision` | 部分实现 | Modules（默认关闭） | [vision](architecture/vision.md) | [vision tests](../backend/tests/test_vision.py) | Tauri 捕获桥与敏感性路由策略 |
| `snapshots` | 已实现 | Developer / History | [architecture](architecture/README.md) | [storage tests](../backend/tests/test_storage.py)、[server tests](../backend/tests/test_server.py) | 加密备份与更细的恢复预览 |
| `live2d` | 规划中 | 暂无 | [Avatar](architecture/avatar.md) | [reference map](ui/reference-map.md) | 选择运行时、资源导入和许可证边界 |
| `virtual-world` | 规划中 | 暂无 | [architecture](architecture/README.md) | [architecture index](architecture/README.md) | 先定义场景状态与时间结算模型 |
| `life-agent` | 规划中 | 暂无 | [tasks](architecture/tasks.md) | [tasks design](architecture/tasks.md) | 与 VirtualWorld 分离设计日程和主动性 |
| `remote-runner` | 规划中 | 暂无 | [security](architecture/security.md) | [tools boundary](architecture/tools.md) | 隔离执行、权限和回滚协议 |
| `android-client` | 规划中 | 暂无 | [desktop shell](architecture/desktop-shell.md) | [protocol](architecture/protocol.md) | 配对、认证和远程事件通道 |
| `agent-runtime-portability` | 已实现 | Agent / Developer | [Agent Runtime](architecture/agent-runtime.md) | [contracts](../backend/src/sumika_core/agent/contracts.py)、[registry](../backend/src/sumika_core/agent/registry.py)、[contract tests](../backend/tests/test_agent_portability.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 接入第二个真实 Harness adapter 后验证跨 Runtime 会话迁移与能力差异 |
| `dsh-agent-runtime` | 已实现 | Agent / Tasks / Developer | [DSH Agent](integrations/dsh-agent.md) | [DSH adapter](../backend/src/sumika_core/agent/adapters/dsh/runtime.py)、[credential bridge](../backend/src/sumika_core/agent/credential_binding.py)、[MCP managed writer](../backend/src/sumika_core/agent/adapters/dsh/mcp_config.py)、[protocol/MCP smoke](../tools/smoke_dsh_round.py)、[daily acceptance](../tools/agent_daily_acceptance.py)、[MCP stdio fixture](../backend/tests/fixtures/mcp_stdio_server.py)、[skill catalog](../backend/src/sumika_core/agent/skill_catalog.py)、[task projection](../backend/src/sumika_core/tasks/agent_projection.py)、[Agent tests](../backend/tests/test_agent_runtime.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)、[desktop launcher](../src-tauri/src/main.rs)、[固定启动故障手册](troubleshooting/dsh-startup.md) | Phase 0–3 已完成；2026-09-03 在真实 Windows 进程链中验证固定 `0.1.1-rc.2` 精确版本、`host.describe`、Core/DSH 端口、Tauri 子进程关系和关闭后的端口释放；隔离 `Plan→Execute`、工具、审批、checkpoint/diff/精确恢复冒烟通过。固定版 DSH 仍不暴露独立 Readonly policy、composition 写入、live `mcp.list`、artifact 或 rollback RPC；真实 Provider 预检仍可能显示 `needs-action`，不影响测试 Provider 的协议闭环；Phase 4（更广泛任务/浏览器人工接管/真实第三方 MCP）等待明确恢复 |
| `agent-observability` | 部分实现 | `GET /api/agent/observability`、`GET /api/agent/route-trace`；`python tools/aggregate_agent_day.py`；`python tools/evaluate_models.py`；`python tools/capture_model_evaluations.py --opt-in`；`python tools/agent_daily_acceptance.py --real-session`（维护工具） | [Agent observability](architecture/agent-observability.md) | [observability sink](../backend/src/sumika_core/observability.py)、[route decision trace](../backend/src/sumika_core/agent/route_trace.py)、[model evaluator](../backend/src/sumika_core/model_evaluation.py)、[fixed task set](../tools/fixtures/model-evaluation-v1.json)、[trace tests](../backend/tests/test_route_decision_trace.py)、[evaluation tests](../backend/tests/test_model_evaluation.py)、[daily report tests](../tools/test_agent_daily_acceptance.py)、[server tests](../backend/tests/test_observability_server.py)；`route-decision-trace/v1` 已覆盖边界、逐候选过滤/证据、排序、选择、确认、派发、去重、重试、取消和带 usage/费用的终态 | 用真实日用样本审查过滤原因、失败链和费用偏差，再通过固定评测提出策略改动；日志不得自行改变生产路由 |
| `browser-runtime` | 部分实现 | Agent > 隔离浏览器 | [Browser runtime](integrations/browser-runtime.md) | [BrowserSkill bridge](../backend/src/sumika_core/browser/runtime.py)、[visual probe](../backend/src/sumika_core/browser/visual.py)、[policy evaluator](../backend/src/sumika_core/browser/policy.py)、[DSH policy plugin](../plugins/dsh-browser-policy/README.md)、[browser tests](../backend/tests/test_browser_runtime.py)、[visual tests](../backend/tests/test_visual_evidence.py)、[policy tests](../backend/tests/test_browser_policy.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)、[license ledger](ui/license-ledger.md)、`bsk doctor --json` daemon/protocol 检查、[`smoke_dsh_browser.py`](../tools/smoke_dsh_browser.py)、[`smoke_dsh_browser_write.py`](../tools/smoke_dsh_browser_write.py)、[daily acceptance](../tools/agent_daily_acceptance.py) | 会话、观察、审批门控 DOM 操作、下载 quarantine、命名 Profile、单写租约和本地 RapidOCR 标量证据边界已具备；CLI `0.1.11` 与 extension `0.1.7` 的 protocol 1.1 已在隔离 Edge 通过 doctor；真实人工接管、登录审批、24 小时清理和五站视觉实机仍待逐项验证 |
| `web-chat-runtime` | 部分实现 | Modules > 实现方式、Developer > 网页连接 | [Web Chat](integrations/browser-runtime.md#网页聊天档案web-chat) | [web-chat adapter](../backend/src/sumika_core/browser/web_chat.py)、[visual probe](../backend/src/sumika_core/browser/visual.py)、[troubleshooting](troubleshooting/browser-web-chat.md)、[runtime tests](../backend/tests/test_web_chat.py)、[visual tests](../backend/tests/test_visual_evidence.py)、[route/consultation tests](../backend/tests/test_dynamic_route_supervisor.py)、[RPC tests](../backend/tests/test_web_chat_server.py)、[Playwright smoke](../frontend/tests/smoke.spec.js)；DeepSeek、ChatGPT、智谱、Qwen、Kimi、豆包模板已登记，五成员咨询按 `3 + 2` 运行；2026-09-02 已完成 DeepSeek、ChatGPT、智谱、Qwen、Kimi 隔离 Profile 的人工登录、页面检查、`chat.read`/`chat.send` 长期普通文本授权和可路由验证；OCR 夹具、真实 RapidOCR 无敏感图片冒烟、提交不确定不重发、同命名 Profile 共享一窗多标签和 Worker 空闲 60 秒回收已通过 | 逐站用 DOM/ARIA 与 OCR 完成真实发送和回复提取，先修通 ChatGPT，再验收五站 `3 + 2`；现有不同 BrowserSkill Profile 不静默合并，单窗口验收需把五站登录到同一个新命名 Profile；网页额度保持 `unknown` |
| `evolution-registry` | 已实现 | Developer > Evolution Knowledge Registry | [Registry](integrations/evolution-registry.md) | [registry data](integrations/evolution-knowledge-registry.json)、[registry tests](../backend/tests/test_evolution_registry.py) | 增加隔离评测报告和用户批准工作流 |
| `unified-browser` | 部分实现 | 桌面内置浏览器工作区 | [正式需求](requirements/embedded-browser.md)、[工作包2–4](refactor/model-activation-and-accounts.md#工作包234续做2026-09-08) | 主窗口、存储隔离、接管、桌宠停止及生产前端咨询主模型闭环通过；启动不再无条件开旧BrowserSkill；维护桥初始化/重连修复后魔搭/Moark正式刷新通过；[续验收](refactor/model-activation-and-accounts.md#9月9日闭环与精确对账) | 全部站点自动化未完成；Ollama本次missing-usage-section，不能当作新鲜权益；通用BrowserSkill工具仍为明确兼容路径，不迁Cookie、不静默开外窗 |
| `desktop-wallpaper` | 规划中 | A+原型壁纸构图 | [正式需求总表](requirements/catalog.md) | [原型与客户端边界](ui/a-plus-client.md) | 原生桌面置底、Explorer生命周期、多屏/DPI、焦点和恢复尚待实现与验收 |
| `real-devices` | 规划中 | 暂无设备运行入口 | [需求基线](requirements/baseline.md) | [已批准长期边界](requirements/original-excerpts.md) | 先局域网只读；控制、米家和运动设备等安全网关完成后单独实施 |
| `cost-routing-protocol` | 部分实现 | 本地Codex Skill协议 | [成本协议](refactor/phase-3-cost-routing.md) | [历史验收及限制](refactor/phase-3-cost-routing.md) | 协议与估算已有，不能从模板证明当前宿主真实执行器的能力/价格，不能替代Sumika Runtime |

## 需求基线映射

实现状态仍以本表为准；需求意图、验收和原话见[需求总表](requirements/catalog.md)。一个状态可承接多个需求，存在代码引用不表示整项需求已经通过验收。

| 状态 ID | 需求 ID |
| --- | --- |
| `free-model-routing` | `MODEL-012`, `MODEL-013`, `MODEL-014`, `MODEL-015`, `MODEL-016`, `MODEL-018` |
| `moark-candidates` | `MODEL-012`, `MODEL-013`, `MODEL-015`, `MODEL-018` |
| `free-benefits` | `BENEFIT-001`, `BENEFIT-002`, `BENEFIT-003`, `BROWSER-003` |
| `modelscope-candidates` | `MODEL-013`, `MODEL-016`, `BENEFIT-002` |
| `ollama-cloud-candidates` | `MODEL-013`, `MODEL-016` |
| `siliconflow-translation` | `MODEL-013`, `INPUT-002` |
| `xfyun-candidates` | `MODEL-013`, `MODEL-015`, `MODEL-016` |
| `openrouter-free-candidates` | `MODEL-013`, `MODEL-015` |
| `agnes-candidates` | `MODEL-013`, `MODEL-015` |
| `article-provider-observations` | `BENEFIT-001`, `MODEL-013` |
| `siliconflow-candidates` | `MODEL-013`, `MODEL-015` |
| `deepseek-candidates` | `MODEL-012`, `MODEL-013`, `MODEL-018` |
| `quality-routing-core` | `MODEL-005`, `MODEL-006`, `MODEL-010`, `MODEL-011`, `MCP-001`, `SEC-001`, `PLUGIN-002`, `MODEL-012`, `MODEL-013`, `MODEL-017`, `TASK-002` |
| `model-refresh` | `MODEL-015`, `MODEL-016` |
| `unified-route-costs` | `MODEL-012`, `MODEL-016`, `MODEL-017`, `MODEL-018` |
| `quality-selection` | `MODEL-012`, `MODEL-013`, `MODEL-014` |
| `quality-routing-workflow` | `TASK-001`, `CHARACTER-001`, `MULTI-001`, `MODEL-005`, `MODEL-011`, `SEC-001`, `MODEL-017`, `MODEL-019`, `TASK-002` |
| `native-consultation` | `MODEL-009`, `BROWSER-002`, `SEC-001`, `BROWSER-004`, `BROWSER-003` |
| `domain-contracts` | `CORE-001`, `UX-002`, `CHARACTER-001`, `AVATAR-001`, `CAPABILITY-001`, `MEMORY-001`, `MULTI-001`, `DEFERRED-001`, `MODEL-005`, `MODEL-006`, `MODEL-011`, `SEC-001`, `RESOURCE-001`, `MULTI-002` |
| `a-plus-ui-concept` | `UX-002`, `AVATAR-001`, `CAPABILITY-001` |
| `scene-ui-shell` | `UX-002`, `CHARACTER-001`, `AVATAR-001`, `CAPABILITY-001`, `UX-003`, `UX-004`, `AVATAR-003` |
| `scene-ui-store` | `UX-002`, `CHARACTER-001`, `AVATAR-001`, `UX-003` |
| `local-llm` | `PLATFORM-001`, `PROVIDER-002`, `MODEL-008`, `HISTORY-OLLAMA-DEFAULT` |
| `provider-profiles` | `PROVIDER-001`, `PROVIDER-003`, `PROVIDER-005`, `PROVIDER-006`, `MODEL-004`, `MODEL-011` |
| `ccswitch-import` | `PROVIDER-004` |
| `chat` | `UX-001`, `CHAT-001` |
| `characters` | `CHARACTER-001`, `CHARACTER-002` |
| `modules` | `PROVIDER-001`, `PLUGIN-001`, `UX-004` |
| `capability-catalog` | `CAPABILITY-001`, `AGENT-001`, `PLUGIN-001`, `MODEL-002` |
| `desktop-automation` | `DESKTOP-001`, `DESKTOP-002`, `CAPABILITY-001`, `SEC-001` |
| `model-policy` | `MODEL-001`, `MODEL-002`, `MODEL-003`, `MODEL-004`, `MODEL-005`, `MODEL-006`, `MODEL-007`, `MODEL-008`, `MODEL-009`, `MODEL-011`, `MODEL-018` |
| `model-picker-adapter` | `MODEL-020` |
| `tasks` | `CORE-001`, `TASK-001`, `WORKSPACE-001` |
| `avatar-vrm-desktop` | `AVATAR-001`, `AVATAR-002`, `AVATAR-003`, `AVATAR-004` |
| `web-portals` | `PLATFORM-001`, `UX-002`, `BROWSER-003`, `UX-003` |
| `plugins-manifest` | `PLUGIN-001` |
| `audio` | `DEFERRED-001`, `INPUT-001` |
| `memory` | `MEMORY-001`, `MULTI-001`, `DEFERRED-001`, `MULTI-002` |
| `vision` | `DEFERRED-001`, `INPUT-002` |
| `snapshots` | `SEC-001`, `WORKSPACE-001` |
| `live2d` | `DEFERRED-001` |
| `virtual-world` | `DEFERRED-001`, `MULTI-001`, `WORLD-001` |
| `life-agent` | `DEFERRED-001`, `MULTI-001`, `WORLD-001` |
| `remote-runner` | `DEFERRED-001` |
| `android-client` | `DEFERRED-001` |
| `agent-runtime-portability` | `AGENT-001`, `MODEL-002`, `MODEL-003` |
| `dsh-agent-runtime` | `AGENT-001`, `AGENT-002`, `MCP-001`, `SKILL-001`, `TASK-001`, `STARTUP-001`, `MODEL-002`, `MODEL-003`, `PROCESS-001`, `CORE-001` |
| `agent-observability` | `OBS-001`, `OBS-002`, `EVOLUTION-001`, `MODEL-010` |
| `browser-runtime` | `BROWSER-001`, `MODEL-009`, `TOOLING-001`, `BROWSER-003` |
| `web-chat-runtime` | `CAPABILITY-001`, `BROWSER-001`, `BROWSER-002`, `MODEL-002`, `PROCESS-002`, `OBS-003`, `BROWSER-003`, `BROWSER-004` |
| `evolution-registry` | `EVOLUTION-001`, `LICENSE-001` |
| `unified-browser` | `BROWSER-003` |
| `desktop-wallpaper` | `UX-005` |
| `real-devices` | `DEVICE-001` |
| `cost-routing-protocol` | `COST-001` |

## 更新规则

完成一个可验证的用户入口、协议边界或测试夹具后，先更新对应行的状态、入口
和证据，再在专题文档中补充设计细节。没有实现证据时，不得把状态写成
`已实现`。
