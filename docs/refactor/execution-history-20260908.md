# 2026-09-08 需求补录前执行记录归档

本页原样保留此次整理前的执行契约正文，供追溯测试、授权与恢复路径；不是当前状态来源。旧文中“未准入”“不恢复已删除摘录”等可能已被后续结果或本次明确授权取代。最新恢复入口为[当前执行契约](../current-execution.md)，需求为[总表](../requirements/catalog.md)，完成度为[状态矩阵](../status-matrix.md)。

# Sumika 当前执行契约

本页只用于恢复当前开发目标和下一步，不是功能状态或完整架构的事实源。
功能状态以 [状态矩阵](../status-matrix.md) 为准，接口和约束以对应专题文档为准。

## 目标

当前目标为执行用户已批准的质量优先动态路由与零成本刷新 Phase 0–6，接续既有多模型协作 R0–R5，见 [执行契约](quality-routing.md)。保留 A+ 双模式 UI、现有改动与运行数据；本轮不实施壁纸层、新音视频或自主生活。

## Definition of Done

- 新独立核心、助手隔离、质量证据选择、可配置任务预算、计划修订与恢复通过本地合同测试；
- 角色模型与负责人分离，真实客户端接入任务、预算和内嵌咨询；
- API、ChatGPT、ZCode 的真实验收与夹具证据分别记录；未登录、未授权和未知费用不可伪装为已完成；
- 社区包可独立安装并有受限 SDK/MCP 示例，不对外发布；
- 下列 A+ 条目是保留的既有验收基线，不是本轮完成声明：
- 阶段 0 冻结 A+ 视觉和双模式边界，阶段 1 保留可交互原型与旧稿；
- 阶段 2 将五项文字导航、聊天收放、能力分类与模块布局接入真实客户端；
- 原生 workspace/pet 共享一个窗口、会话、草稿和 Avatar，隐藏停止持续绘制；
- 添加卡片、启用模块、授予权限保持分离，旧 Provider/模型策略/审批回归通过；
- 浏览器多尺寸截图、画布像素、单元测试、构建与隔离原生模式验收完成，测试进程清理；
- 不修改日用运行数据，不把 UI 验收算作真实 Provider、壁纸层或自主生活验收。

## 当前基线

- Branch: `codex/dsh-agent-runtime`
- Baseline commit: `28d5051`（当前 `HEAD`；工作树有既有后端改动、UI 重构和未跟踪运行产物，未提交）
- Last verified commit: working tree on 2026-09-07，A+ 浏览器及隔离 Tauri 双模式验收见当前恢复点；固定 DSH 完整启动链最近历史证据仍是 2026-09-03。ZCode Electron 的 2026-08-31 smoke 仅为用户指定 loopback CDP 元数据检查。
- Runtime: DSH `0.1.1-rc.2` through the runtime-neutral `AgentRuntime` adapter; optional ZCode adapter probes the installed public `app-server --stdio` wire (`session/list`, no `jsonrpc` member) and retains a legacy JSON-RPC compatibility path.
- Status source: [status-matrix.md](../status-matrix.md)
- Runtime design: [Agent Runtime](../architecture/agent-runtime.md)
- DSH integration: [DSH Agent](../integrations/dsh-agent.md)
- Requirements: [baseline](../requirements/README.md) and [model policy](../requirements/model-policy.md)

Existing untracked `example.txt`, `output/`, and `test-results/` are outside the approved development scope and must not be staged, moved, overwritten, or removed.

## 当前里程碑

**需求与授权更新（2026-09-08，高频维护与跨渠道付费）：** 用户要求高频福利发现、刷新与签到优先不花钱；确认现有服务均为无模型脚本，未来如接语义处理，维护任务也应仅用已核验免费/本地执行，失败延后而不付费升级。用户同时允许此前保存渠道中有可用余额的付费模型用于普通任务，沿用已有任务预算；不重复询问同范围小额调用、不充值。已记录到[模型策略需求](../requirements/model-policy.md)。本轮是现状核对与需求保存，未发起模型请求、未启用额外后台流程或直接放行付费路由。下一步需补齐付费候选的实际价格/账户余额/评测，并统一旧ModelRouter与协作核心的选择依据；不能声称已实现所有渠道自动比价。

**最新恢复点（2026-09-08，Moark扩大核查与免费路由完成）：** 用户授权使用现有¥10资源包进行适当付费测试，本轮预计上限0.50。公开目录核到10款零价通用文本与10款专用服务，12款文本（10免费+2低价）已登记日用观察目录。修复前导思考块与官方大小写/单层命名空间回显适配后，免费Qwen3-8B三题及隔离Core真实自动选择/执行均通过；已导入同账号/执行版本的原始证据并追加日用候选池。预计现金0，正式六小时零模型刷新、发送保护、到期与免费撤回共同生效。其他免费项仍被质量门槛挡住；不将Markdown格式失败全部解释为推理能力差。

本次扩展共30次模型调用，累计预留上界¥0.0501536；官方资源包已用¥0.0034866、余额¥9.9965134。低价qwen3.8-flash三题全过，但付费自动路由未启用；GLM-5.3-Flash只通过前两项，第三项不通过，未准入。主模型、角色、预算、其他Provider、会话/消息/模块/角色数据均保留。备份`D:/Caches/sumika-free-catalog/before-moark-activation-20260908.sqlite3`；汇总`moark-final-summary-20260908.json`、日用`moark-daily-enabled-20260908.json`、正式链路`moark-core-smoke-v2-20260908.json`。首次Core smoke被隔离实例未启用LLM模块阻断，实际0调用，已更正计数；新工具显式启用隔离模块后成功，未改日用模块。968项后端全量通过，最后适配后153项专项通过；没有遗留本轮测试进程或子Agent。运行中的旧Core仍需正常重启加载源码。

Moark中间证据：公开目录返回220项、声明总数237，第二页为空，保持不完整标记。严格核到10款零价通用文本和10款专用模型；免费操作计数不能覆盖非零token费。正式余额API确认总额10、原已用0；10免费+2低价型号的14次请求后已用0.0019654。qwen3.8-flash三题全过，其他部分失败实际涉及思考块与带命名空间的模型回显。已按官方大小写/单层命名空间规则与实测前导思考块补适配，正在选择性复验；不放宽JSON内容验收。付费首批预留上界0.0262032、诊断额外小于0.004、后续复验上界0.02，合计仍低于0.50。968项全量通过；随后适配专项77项通过。证据`moark-expanded-20260908.json`、`moark-protocol-diagnostic-20260908.json`及余额前后记录；隔离目录`D:/Caches/sumika-moark-acceptance-20260908`，日用Moark尚未变更。

**最新恢复点（2026-09-08，首批免费模型正式接入完成）：** 文章十个正面推荐已核清；新增Spark Lite/Moark已保存凭据并完成实测。讯飞4B、Agnes2.5通过新增固定任务、隔离Core自动路由与真实执行，已按相同账号/执行版本将原始证据导入日用实例，并追加协作候选池。日用自动选择返回Agnes、预计现金0；原负责人/角色绑定、选择模式、预算与会话/消息/模块/角色表均保留。其余候选不能因新增Profile可用状态绕过质量与免费证据门槛。正在运行的旧Core需正常重启加载源码。

详见[渠道核查](free-provider-audit.md)和[正式刷新与路由](free-model-routing.md)。已接逐Profile六小时零模型刷新、任务门槛、账号/执行版本、到期、429冷却与跨实例发送租约；关闭应用不调度。Spark Lite适配code=0及无空格DONE帧后已接通，但事实抽取契约未过；Moark三款首题精确格式未过。Ollama Gemma补测通过，仍待Starter额度绑定；魔搭仍待账户/魔粒对账；OpenRouter LFM、智谱4.7本轮429，不永久淘汰。NVIDIA OTP/Intern原阻碍不重复索要注册。后端全量952项通过，最后协议/连线变更后122项专项、5项前端与构建通过；全部自建测试进程已退出。报告位于`D:/Caches/sumika-free-catalog/`，日用启用报告`daily-free-routing-enabled-20260908.json`。

**最新恢复点（2026-09-08，广泛免费资源发现与自动签到首版完成）：** 用户要求不限于已注册站点，并建议RSS；已接12个固定公开来源，最终实采10个成功，23项官网证据=OpenRouter16/硅基2/讯飞2个型号声明+Cloudflare/Gemini/Cerebras三家权益。Bing三源、V2EX可读但此次无合格资讯，Groq证据不足、LINUX DO受限。最初26条搜索/个人额度故障噪声已从本轮索引清除，原v1/v2报告保留；严格模型/API+福利意图过滤，无变化不写快照。恢复正常网络代理并使用Bing规范入口，不绕过重定向或验证。魔搭固定工作流真实核验当日200+50、余额242，未虚报额外领取；本实例启用后台发现与自动签到，绑定浏览器`7c8b150e`和Profile版本，下次正常启动执行到期维护。进程关闭后不联网，零模型调用、未读取Key/Cookie，SQLite SHA256前后不变、全部自建浏览器会话已关闭。先完成858项后端全量，后续专项最终109项、35项前端、11项DOM、3项浏览器集成及构建通过；全量前端45/46，既有能力页文案断言失败未改。无凭据隔离预览`http://127.0.0.1:8882/`留作查看，自动任务关闭；旧本轮Vite5174已清理，既有8881预览保留。源码、日用配置和证据边界见[免费资源发现](free-benefits.md)，报告`D:\Caches\sumika-free-catalog\benefits-discovery-20260908-final.json`及`benefits-checkin-20260908-v3.json`。新站尚不自动领取/注册，未放行新模型自动路由。

**最新恢复点（2026-09-08，魔搭实测与每日额度已核实）：** 用户提供Token并允许协助普通免费签到/查询，安全保存到独立`modelscope-free-candidates`，读回核验通过。Qwen3-Coder-30B、Qwen3.5-35B各三题全过；DeepSeek-V4-Flash-0731首题响应结构不合格后停止，未重发。共7次请求，成功响应输入213/输出1005 token；三项仍不可自动路由，原Profile/模块/角色与执行版本不变。浏览器曾返回用户停止，已暂停；随后用户明确“登陆了”，恢复查询成功：9月8日登录发放200、阿里云绑定50，均显示有效期1天，余额242；当天消耗统计8魔粒，非逐请求对账或现金账单。无需再点击签到，不伪称Agent额外领取。新增无Key/无模型的`read_modelscope_magicube.ps1`，读取已登录发放记录，不自动登录、领取或安排后台任务；43项Python回归、5项DOM解析测试、PowerShell解析及真实读取通过。详见[魔搭证据](quality-routing.md#魔搭社区实测与每日额度2026-09-08)。BrowserSkill会话`aqtj`已正常关闭，账号登录态未删除；后续须新建会话，不能复用旧session/tab。本轮未建立每日自动任务。

**最新恢复点（2026-09-08，Ollama Key与渠道补测）：** 用户反馈书生无法使用，暂停、不再索要Token；魔搭正在注册绑定，尚无Key；NVIDIA仍卡OTP。Ollama Key已隐藏输入保存并读回验证，独立`ollama-cloud-candidates`登记20B/5.3-Flash/Gemma三项。`gpt-oss:20b`三题全过，输入280/输出164；Flash首题402后整批停止，Gemma未发送。免费Starter是按月赠送用量，不是零单价或全目录免费，实际余额/现金未知。仅回写20B healthy、Flash unavailable，整体不可路由，其他Profile/模块/角色及执行版本均不变。混元翻译三句关键词/标识符检查2/3，输入82/输出35，不是完整语义或OCR验收，不入聊天池。48项工具测试通过；报告/备份在`D:\Caches\sumika-free-catalog\`，详见[本轮证据](quality-routing.md#ollama-cloud与翻译能力补测2026-09-08)。讯飞已完成独立采集与基础实测，但通用刷新目前仍主要接智谱，讯飞特定的定期刷新、发送前核价与自动质量/成本准入尚未实现；不是只差开关。本轮未修改这些运行时流程。

**追加恢复点（2026-09-08，讯飞用户已手动开通）：** 用户确认每模型需开通服务并已开通全部免费/限时免费项。只复测4B，三题3/3通过，约4.21/1.63/2.21秒；403阻碍已解除，4B健康更新为healthy，1.7B已有结果不重测。讯飞累计7次聊天尝试，已知输入260/输出674 token，账单未知；报告`D:\Caches\sumika-free-catalog\xfyun-4b-after-activation-20260908.json`。两款仍未自动路由，凭据与执行版本不变；原Profile/模块/角色未改。其余免费OCR/向量/重排只保留公开观察，尚未实测；OCR公开serviceId/端点有不完整项，需要独立核对。下段待开通是已解决的历史状态，不再要求用户重复领取。

**当前恢复点（2026-09-08，讯飞MaaS Key与实测）：** 用户已提供Key并指出账户页，已隐藏输入保存到日用Windows Credential Manager，独立`xfyun-free-candidates`读回核验通过。公开XHR查到两款精确serviceId、MaaS v2地址和推理零价；GET /models为空，显式公开目录聊天健康模式下1.7B三题全部通过，4B首题403/11200后停止，共4次聊天尝试，已知输入130/输出458 token、账单未知。健康分别healthy/unavailable，Profile整体未放行；2项不可自动路由，原8个连接/模块/角色与备份一致，执行版本不变。用户随后确认4B账户页显示限时免费，但未确认API权益已开通，不据此重复请求或购买。新增公开目录读取器、MaaS评测入口，相关34项离线测试通过；证据`D:\Caches\sumika-free-catalog\xfyun-sanity-20260908.json`，备份`before-xfyun-registration-20260908.sqlite3`。详见[讯飞实测](quality-routing.md#讯飞maas凭据与免费模型实测2026-09-08)。

**当前恢复点（2026-09-08，Agnes实测通过、OpenRouter复查）：** 新增Agnes入口复用有界测试器，免费/default Key的2.0/2.5分别通过算术、JSON、精确文本变换，共6次真实调用，输入1864/输出176 token；2.0延迟1.15–3.44秒，2.5延迟1.23–6.63秒。响应未报告金额，账单仍未知；不能由短题授予复杂任务或主模型资格。OpenRouter换测Gemma 4 26B仍首题429，停止且未重发，不能代表其他14款无效。报告`D:\Caches\sumika-free-catalog\agnes-sanity-20260908.json`与`openrouter-gemma26-sanity-20260908.json`；相关26项离线测试通过，未改日用Profile/角色/路由。主Agent用未登录Playwright完成其余渠道DOM复核：讯飞新增Spark-X2.5-1.7B免费/4B限时免费，用户正在注册创建Key；Intern有397B型号与6个月Token，月度额度未证实；魔搭改魔粒扣减；Moark100次免费与购买API权益范围有歧义，不购买。NVIDIA用户反馈手机收不到OTP，暂停而不是要求再次注册，尚不能判断地区封锁。完整依据见[最新渠道复核](quality-routing.md#agnes文本验收与其他渠道复核2026-09-08)。

本轮收尾核验：Agnes/硅基/OpenRouter相关26项测试通过；`provider_profiles`、`module_settings`、`characters`前后摘要一致，未更改日用选择。报告及新增源码未发现密钥字面量；真实请求共7次（Agnes6次、OpenRouter1次）。无测试进程或浏览器遗留；其他渠道等待Key不等同渠道已验收。

上一轮最终验证：补充响应型号不匹配即停止整批的回归后，硅基评测、公开价目及OpenRouter相关测试共24项通过；差异检查通过，新增源码和报告未发现密钥字面量。没有因此追加真实模型调用。

**最新恢复点（2026-09-08，硅基流动有界实测）：** 用户明确确认三款免费并要求自行查找和测试，不再以截图或未查到余额为人工测试前置条件；此授权不等于自动路由免费事实或付费回退授权。已完成5次请求：Qwen3-8B和DeepSeek-R1-0528-Qwen3-8B各一次算术请求30秒超时、未重发；GLM-4-9B三次均正常stop，文本替换通过，算术/JSON严格输出契约未通过。已知输入94/输出32 token，超时用量及实际账单未知，不能宣称算术错误或永久免费已验收。按报告仅更新模型健康：GLM healthy，两超时 unavailable；Profile整体仍未放行，3项不可路由，执行版本/凭据/默认模型/其他连接/角色/模块不变。发现旧catalog的routable位主要表示健康，且仍有型号猜档，不能据此授予质量资格。新增有界评测与公开价目读取器，相关23项测试通过；已从`https://www.siliconflow.cn/pricing`精确提取Hunyuan-MT-7B和PaddleOCR-VL-1.5输入/输出免费行，仅观察，不混入通用聊天或写共享刷新状态。证据与备份在`D:\Caches\sumika-free-catalog\`，详见[硅基实测](quality-routing.md#硅基流动有界实测2026-09-08)。

**追加恢复点（2026-09-08，硅基流动Key已接收）：** 用户已注册并提供Key，已安全保存到新`siliconflow-free-candidates`，原始凭据未写入项目或报告。认证`GET /models`成功返回96项，精确登记`Qwen/Qwen3-8B`、`THUDM/GLM-4-9B-0414`、`deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`三个文章相关候选；目录没有价格字段，`GET /user/info`返回410，因此余额/实名状态/逐型号免费资格仍未从API确认，不把410当Key无效。不发送模型调用。已对比Agnes登记前备份确认原Profile、module_settings及characters不变，OpenRouter16项、Agnes3项、硅基3项均不可自动路由。用户已同意注册NVIDIA并创建Key，下一步等待该Key而不重复询问注册意愿；Agnes与硅基继续免费权益和有界评测，不充值或用赠金冒充免费。

**最新恢复点（2026-09-08，文章正文与新渠道凭据）：** 已读取用户粘贴的完整文章，不再受微信验证码阻塞。OpenRouter Key已通过隐藏输入保存到日用Windows Credential Manager并读回核验；`GET /key`认证成功，普通免费层级Key，usage各项为0，limit/limit_remaining为null，不代表无限额度。一次`google/gemma-4-31b-it:free`算术请求返回429后停止整批，无重试/其他候选请求；未拿到usage或实际费用，16项仍不可路由。新增有界验收工具与登记工具合计12项离线测试通过。用户随后提供Agnes免费Key，已安全保存并登记`agnes-free-candidates`；官方文档列出的1.5/2.0/2.5进入观察目录，认证GET仅返回2.0/2.5，未进行聊天调用或免费额度验收。两次写入均有项目外SQLite备份，主模型/角色及其他连接不变。公开核查发现Agnes上下文文档有版本差异、Ollama免费用量已按月重置，不能照抄文章数值；NVIDIA当前目录显示38个Free Endpoint，但账号可用性未测。用户愿意自行完成硅基流动注册/实名，等待Key；已询问NVIDIA账号。详情见[文章核对与接入](quality-routing.md#文章核对与新渠道接入2026-09-08)。

**最新恢复点（2026-09-08，新增免费候选）：** 用户提供微信文章要求扩充免费池；脚本访问遇到验证码，尚未读到正文，不能把独立调查的OpenRouter结果归因于文章。已从OpenRouter官方公开目录核对16个显式`:free`、所有价格分量为零的文本候选，备份后登记日用`openrouter-free-candidates`，全部待Key/健康/质量评测、`routable=false`，账号额度未知。原Profile、module_settings、characters与备份一致；未读写凭据、未发起模型调用、未切换主模型/角色或重启客户端。新增登记工具3项测试通过。报告与备份在`D:\Caches\sumika-free-catalog\`，完整型号及复用方式见[免费候选登记](quality-routing.md#openrouter免费候选登记2026-09-08)。用户回复需要先注册OpenRouter；已提供Keys页，不要求充值或放宽隐私。内嵌浏览器打开不等于正文已被工具读取，仍需用户完成验证或提供正文/截图。

**最新恢复点（2026-09-08，DeepSeek候选登记）：** 用户授权保存新DeepSeek Key并加入池子。已用隐藏输入将Key写入日用`.sumika-desktop`命名空间的Windows Credential Manager，读回核验通过；新建`deepseek-official`独立Profile，官方`https://api.deepseek.com/v1/models`查询成功，实际返回`deepseek-v4-flash`、`deepseek-v4-pro`、`deepseek-v4-flash-vision-exp`。三者进入模型策略候选目录，但未进行聊天/视觉评测，均保持不可自动路由；不能把目录可读当作任务可用证明。原Profile、module_settings、characters与备份逐项一致，未替换主模型或角色模型。操作前备份`D:\Caches\sumika-quality-zhipu-live\before-deepseek-registration-20260908.sqlite3`；未将Key写入源码、数据库正文、报告或Shell命令参数，未重启客户端。下一步针对这三款及两款智谱Flash补能力/费用证据和有界评测。

**最新授权更新（2026-09-08，旧智谱Key作废）：** 用户明确要求废弃旧Key，统一使用刚提供的当前Key。已通过ProviderProfileManager更新原日用`zhipu-glm-45-air`的安全凭据，清除旧模型健康标记后执行一次不允许聊天探针的GET健康检查，结果available；没有发起聊天调用。已核验原日用与`zhipu-flash-candidates`均匹配当前已保存测试凭据，不更换默认型号、模块选择或角色配置。操作前备份`D:\Caches\sumika-quality-zhipu-live\before-zhipu-key-rotation-20260908.sqlite3`。下文“原凭据不覆盖”是用户追加授权之前的历史状态，不再代表当前配置。两Flash仍待评测，不因换Key自动晋升。

**最新恢复点（2026-09-08，Flash复测与候选登记）：** 用户要求再测并尝试入池，随后再次提供原测试Key。已确认两款官方API均能成功返回答案；4.7-Flash算术成功后下一题HTTP429/code1305，4.6V-Flash算术成功、JSON严格验收未通过。此次共6次有界聊天尝试，3次HTTP429；已报告输入70/输出341 token，失败请求用量与现金费用未知。未重试提交未知请求。报告在`D:\Caches\sumika-quality-zhipu-live\glm47-flash-diagnostic-20260908.json`、`glm46v-flash-diagnostic-20260908.json`及对应`*-retest-20260908-b.json`。

已在日用`.sumika-desktop`新增独立`zhipu-flash-candidates`连接，绑定已授权保存的测试Key（与旧`zhipu-glm-45-air`凭据不同），两模型列入待评测目录，不授予自动路由或主模型资格，未声明视觉能力已验收。4.7最新限流按暂不可用记录；4.6V健康与质量验收分离。原Profile、模块设置、角色表与操作前备份逐项一致，保存Key读回比对通过。备份`D:\Caches\sumika-quality-zhipu-live\before-flash-registration-20260908.sqlite3`；新增可复用登记工具`tools/register_zhipu_flash_candidates.py`默认dry-run、拒绝覆盖已有连接，仅`--apply`落地，评测及登记工具28项单测通过。未启动/重启客户端；8881隔离预览不使用日用数据，不能在该预览中寻找新连接。

**最新恢复点（2026-09-08，发送前复核已完成本地验收）：** 后端全量758项通过；独立核心39项通过、2项可选MCP跳过；工具61项通过，离线SDK示例完成，默认Git差异检查通过。API任务/角色发送前复核价格、权限、健康、当前助手评测、推理强度与执行版本；原始消息/工具/usage保留。账户额度绑定与执行快照分离，更换Key或端点、重建Runtime、重启不能沿用旧包；显示名变化不影响账户绑定。明确未发送结算零并释放预留，未知/部分回复保持预留。详见[发送前执行绑定](quality-routing.md#发送前执行绑定2026-09-08)。未改日用数据、未发起真实模型调用、未改UI或重启既有预览；整个Phase0–6仍未完成。

**最新恢复点（2026-09-08）：一体化刷新/评测选择/额度发送保护与 UI 首版已接线，完整计划仍未完成。** 后端全量 740 项通过，随后补充“价格刷新不禁用已经过真实健康检查的固定模型”回归，96项定向通过；独立核心 37 项通过、2 项可选 MCP 测试跳过；工具 61 项通过；质量 UI 单测 5 项、浏览器质量/价格 DOM 共 4 项通过（新增状态面板检查 1440×900、1280×800、390×844）；生产构建通过。全前端单测仍有既有能力页文案断言失败，未改写用户文案。

公开官网经隔离 Playwright DOM 实测当前 `glm-4.7-flash`、`glm-4.6v-flash` 均标注免费，价格存储不得视为账号健康或余额。只读刷新无 Key/Cookie/模型调用；资源 DOM/OCR 需宿主显式指定已登录 session/tab/profile，缺绑定或时区时仅观察。Provider 包装器在真正发送前原子预留，失败/取消未知不释放，过期或额度不足不回退现金；本地已用额度尚无供应商账单 watermark 对账，扣减保守。

真实 API：两个型号均未出现在账号 `GET /models` 结果，显式授权的聊天健康模式下 4.7-Flash 通过算术/JSON两题，第三题无有效 usage；4.6V-Flash 首题 HTTP 429，均停止且不重发、未晋升候选。报告 `D:\Caches\sumika-quality-zhipu-live\glm47-flash-probe-20260908.json`、`glm46v-flash-probe-20260908.json`；已知输入49/输出346 token，失败请求用量与现金账单未知。未改变日用主模型、角色绑定、Provider 凭据或运行数据，未注册系统任务。

隔离预览 `http://127.0.0.1:8881/`，Core PID `30436`，目录 `D:\Caches\sumika-routing-preview-20260908`，仅公开价格观察，无 API Key；DSH/picker/Agent 自动启动关闭。设置 > 质量协作可查看选择/刷新状态；能力 > 效率工具 > 大语言模型展示同一证据组件。进程停止后可用 `python -m sumika_core --host 127.0.0.1 --port 8881 --data-dir D:\Caches\sumika-routing-preview-20260908` 恢复（设置两个源码目录到 `PYTHONPATH`，保持 Agent 自动启动关闭）。

**进行中（2026-09-07，一体化刷新与质量路由）：** 用户已批准 Phase 0–6。恢复检查发现上一轮刷新原型存在型号子串匹配、官方/中转及账号作用域混用、导入即宣称质量与刷新成功、定时任务在客户端关闭后仍联网等风险；当前先修复这些边界，并补充资源包预留/恢复、真实来源刷新、候选选择与回归。现有 31 项定向测试仅是旧原型证据，不代表阶段完成。未注册系统定时任务、未改日用模型、未读取测试凭据。

**进行中检查点：** 已重写原子刷新账本，精确账户/型号隔离、最早到期预留、提交未知不释放、滞后余额不恢复已花额度；`ProviderProfileManager.runtime` 接入 host-only 包装器，真实发送前预留覆盖角色、质量工作流与动态 Worker。固定评测/多源先验持久化、每助手自动/固定候选选择与规划付费确认已接线。新增资源发送与独立核心额度测试通过；质量相关 81 项通过。前端新刷新证据/选择控件正在验收，全量单测发现既有能力页文案与测试期待不符（`模块目录读取失败。` 对 `模块目录读取失败；未生成替代运行数据`），不擅自改既有文案。真实渠道与账单、账户/时区绑定尚未验收，不将当前功能称为日用全自动完成。

**最新恢复点（2026-09-07，限时资源包查询通过）：** 已核对官方先扣适用资源包、同场景按到期先后扣减，再扣现金；公开文档未找到标准 API 资源包余额查询接口。用户通过 BrowserSkill 人工接管确认已登录，成功读取官方资源包表格；本地 OCR 备用也已验证。已保存实时观测 `D:\Caches\sumika-quality-zhipu-live\resource-packs-observation.json`：Air 11,136,011 token、4.7 500 万、4.6V 600 万、搜索 100 次、图片/视频 20 次，完整日期与范围见协作专题。一次已授权 Air 短调用使用 24 token，资源包余额从 11,136,035 减至 11,136,011；约 4 分钟才观察到变化，当日现金账单仍未对账。只读复测脚本 `tools/read_zhipu_resource_packs.ps1` 已通过实机读取、错页拒绝和语法验证。未买包/充值、不读取登录输入或导出 Cookie、不修改日用默认模型；长期自动同步及额度路由尚未接线。

**最新恢复点（2026-09-07，GLM-5.3-Flash 复验通过）：** 用户明确授权付费测试与长期保存智谱测试凭据，最新指定 `glm-5.3-flash`。凭据已存 Windows Credential Manager 的 `approved-provider-tests` 命名空间、`zhipu-official` 引用并读回校验；未配置为日用 Provider。单次真实调用及同模型完整工作流通过，最终 13 项检查、5 次调用、输入 1003/输出 1620 token。整轮付费模型共 11 次，按未折扣标价估算 ¥0.0097944，实际账单/额度抵扣未知；证据 `D:\Caches\sumika-quality-zhipu-live\glm53-verified-workflow.json`。已复现角色 300 token 上限耗尽于思考而空正文，默认思考角色出口改为 1024，明确 `off` 仍为 300；未关闭 5.3-Flash 强制思考。638 项后端全量通过，后续角色预算/审查改动专项 31 项通过。免费 4.5-Flash 健康探针本轮超时，扩大等待到 30 秒也无效，已撤回等待调整；不宣称多模型或跨渠道验收通过，详情见协作专题。

**当前等待（2026-09-07，ChatGPT 登录）：** 已授权的隔离原生窗口现已退出，原 Core `50346` 与 CDP `50345` 不再监听。隔离目录 `D:\Caches\sumika-chatgpt-live\1788742129926` 保留；上次交给用户人工登录，尚未确认登录或提交测试消息。恢复时可复用该隔离目录，不读取登录输入、导出 Cookie 或复用日用浏览器；超时不重复提交。跨渠道不能标为通过。

**历史免费验收（2026-09-07，长期保存授权之前）：** 当时凭据仅注入内存 Core，未持久保存。免费 `glm-4.5-flash` 通过普通聊天及规划→报价→确认→执行→审查→答案交付，但角色引言空正文而降级。该轮 6 次调用，输入 746/输出 2962 token；631 项后端与后续 24 项专项通过。报告 `D:\Caches\sumika-quality-zhipu-live\acceptance.json`。后续凭据保存、付费模型与角色预算修复以最新恢复点为准；不把历史可用视为当前免费端点健康。

**当前恢复点（2026-09-07）：R0/R1 与 R5 本地交付完成，R2 文本工作流已接线，R3/R4 尚未完整验收。** 独立 SDK/MCP、质量证据选择、预算/授权快照、角色与负责人分离、报价确认、取消及原生咨询已落代码；picker 真 POST 已修复。ZCode 安全文本执行、工作区委派、picker 自动建议/回写与网页超时后的任务恢复尚待接线；新 ChatGPT Profile 真实登录与发送未做。不能称整个 R0–R5 完成，具体边界见 [执行与证据](quality-routing.md)。本轮未改变日用数据、凭据或用户已有改动。

**历史记录（2026-09-07）：成本调度 Phase 3 与 picker 对接 Phase 4 首版。**
当前 Codex 使用的 `cost-routing` Skill 提供任务包、DAG、L0-L3 规划标签、推理强度
区分、确定性相对成本估算和失败升级边界；Sumika 与 `model-picker` 通过只读
`model-picker/catalog/v1`、`model-picker/evaluations/v1` 接通。设置
`SUMIKA_MODEL_PICKER_URL` 后才注册 loopback advisory source；没有设置时启动不发起
网络请求。picker 不拥有 Worker、凭据、授权或最终路由权；stale、unknown quota、未知
价格和请求失败均保持不可路由。针对性测试记录在 [Phase 4 任务包](phase-4-model-picker-adapter.json)。

**当前恢复点（2026-09-07）：A+ 阶段 0–2 已完成。** 五项文字导航、能力卡片布局、同窗口桌宠与隐藏暂停已接入；前端单测 10/10、完整浏览器回归 62/62、新增故障专项所在 A+ 用例 4/4、Rust 12/12、生产构建通过。真实 Tauri 单窗口/草稿/尺寸/最大化/暂停/透明像素和退出清理 7 项通过；未调用 DSH 或真实模型。范围、截图、复测工具与排查记录见 [A+ 客户端](../ui/a-plus-client.md)。项目外备份已校验；原有改动与数据保留。

**历史阶段（2026-09-06）：A+ 独立预览已交付。** [A+ 原型](../ui/concepts/a-plus-v1/README.md)共 18 张 PNG、37/37；[五套旧稿](../ui/concepts/style-studies-v1/README.md) 56 项、[温暖居所旧稿](../ui/concepts/warm-home-v1/README.md) 23 项与旧 UI 59/59 均是历史证据，不能替代本轮正式客户端验收。以下历史阶段记录不覆盖当前恢复点。
**场景优先 UI 外壳重置（实现与回归完成，2026-09-04）**

Phase 0、1、2 和 3 均已完成；本轮完成客户端 UI 彻底重置第一期（场景优先外壳）与网页门户，Phase 4 仍不开始。客户端从 11 页签工作台改为「全屏场景视口 + 4 抽屉」：Avatar 占屏 60%+ 常驻（WebGL 跨导航不卸载）、气泡流 + galgame 对白框输入、工作台/角色/模块/设置四个全屏抽屉（Esc/✕ 回场景）、竖排 dock 常驻抽屉之上、桌宠浮窗同款对白框。配色开源中立（夜蓝 + Sumika 自有薄荷强调色，不绑定任何版权角色）；每角色 `theme.accent` 由角色卡导入自动读取（`extensions.theme_color`），`color-mix` 派生全套色调；模块页启用「＋ 添加模块」折叠网格；设置页做实（背景色板/本地背景图/真实数据目录/快照）；首用欢迎卡替代常驻指南页。**角色页重构**：新建角色与导入角色卡合并为单一「＋ 新建角色」内联面板（卡可选，卡内 theme_color 成为角色强调色）；Avatar 模型库从常驻页底移入编辑器第 4 折叠区「Avatar 模型」。**网页门户（当前为独立窗口形态）**：dock 第 5 图标（仅桌面版），Kimi/ChatGPT/智谱/DeepSeek/Qwen/豆包各开独立 Tauri WebviewWindow，登录存 `.sumika-desktop/portals/<站点>/`（重启持久、站点 Cookie 隔离），支持自定义站点；原始站点无 persona 注入，与 BrowserSkill 网页 Route 完全隔离。**一键启动**：仓库根 `启动Sumika.bat`（自动清理 3080/8771 残留进程 → 启动桌面版 → 打开受管 Edge Agent Window），桌面快捷方式 Sumika.lnk 指向它。**网页 Route 回复确认修复（`9cc76f1`）**：`WebChatProvider.stream` 遇 `pending+possibly_sent` 时轮询同一 attempt 直到完成（实测 Kimi 4 秒即报错、16 秒后台才提取到回复的时序问题），绝不重发。分层模型借鉴 amica、抽屉结构借鉴 Open-LLM-VTuber-Web、气泡借鉴 ChatVRM（三者 MIT，仅移植交互模式并全部以 Sumika token 重新表达，无文件复制，登记于 license-ledger）。Playwright 50/50、后端 576/576（web_chat 54/54）、cargo 8/8、build、check_docs 全绿。

**固定 DSH 主 Agent 启动闭环（实现与实机验收完成，2026-09-03）**

Phase 0、1、2 和 3 均已完成；本轮完成固定 DSH 启动链的 fail-closed 校验和真实 Windows 进程闭环，Phase 4 仍不开始。

固定版 DSH 没有独立 live `mcp.list`、Readonly policy、composition 写入、artifact 或 rollback RPC。Sumika 对这些边界明确返回 `not-exposed` 或由自身 WorkspaceRuntime 补足，不伪造能力，也不进入 Phase 4。

本轮启动闭环已验证：`tools/run-desktop.ps1 -NoBuild` 只接受固定或显式精确版本的 DSH，Tauri 在配置生成和 spawn 前再次核验；Core `8771`、DSH `3080`、`/api/health`、`/api/agent/status`、`/api/agent/diagnostics`、`host.describe` 和 `session/list` 均可用。
隔离 `Plan→Execute`、审批、工具、checkpoint、diff 和精确恢复通过；真实 Provider 预检仍可能为 `needs-action`，本轮没有发送真实高价请求。

本轮（2026-09-03）已提交 ChatGPT 网页适配器回归修复（`0aadb99`）：声明当前一代 ChatGPT composer/响应选择器（`textarea[data-composer-draft-react]`、`button[data-composer-submit]`、`[data-assistant-markdown]`、`[data-message-role='assistant']`，保留旧 `#prompt-textarea` 优先）；授权标记扩充无引号“打开个人资料菜单”“账户菜单”"Account menu"；HTML 投影属性白名单新增 `aria-label`、`placeholder`、`contenteditable` 等；`send_message` 在输入框裁剪基线之外新增独立页面级视觉基线 `visual_page_baseline_id`，超时诊断改为对比页面基线，避免输入框裁剪掩盖页面上可见的助手回复。相关 83 个测试（`test_web_chat`、`test_browser_runtime`、`test_web_chat_server`）通过。

本轮（2026-09-03）已提交社区角色卡导入能力（`c5612aa`）：新增 `sumika_core/character_import.py`，对齐 SillyTavern 社区规范（`character-card-spec-v2`、CCv3/CHARX），支持 V1 扁平卡、`chara_card_v2`、`chara_card_v3` 与 JSON/PNG（tEXt `chara`/`ccv3`）/CHARX（zip `card.json`）容器，stdlib 实现、零依赖；通用字段映射（identity←description、traits←personality、relationship←scenario、system_prompt←system_prompt、greeting←first_mes，`mes_example` 在上限内以"示例对话"并入），`{{char}}`/`{{user}}` 占位符确定性替换，超限 fail-closed 不静默截断；原始卡与导入元数据保留在 `config.card_import`（世界书不注入运行时，条目保留）。新增 `character.import_card` RPC（同名需 `overwrite`、广播 `character.changed`）、角色页"导入角色卡"入口和 `tools/import_character_card.py` 离线 CLI。安和昴（GIRLS BAND CRY）角色卡已从 `D:\Code\安和昴角色卡项目\交付\安和昴_ST_V2.json` 导入 `.sumika-desktop`（9 条世界书保留未注入），随后并入默认 `sumika` 记录成为默认角色（见下段）；Agent/DSH 通道 persona 投影仍为后续目标，设计钩子已记录在 [characters.md](../architecture/characters.md)（参照 `dsh-browser-policy` 的 `ctx.skills.register` 模式，须走社区插件隔离验证 + 用户批准流程）。

随后（同日）应用户要求把默认角色切换为安和昴：默认锚点记录 `sumika`（`_ensure_defaults` 仅在角色表为空时播种，重启后保留）已改名并写入角色卡 persona 与 `card_import`；原默认角色"Saki"的配置备份在 `.sumika-desktop/saki-config-backup.json`（未跟踪）；独立的重复导入行已删除。486desu 免费配布的同人 VRM `awa subaru（增加校徽）.vrm`（16.5 MB）已复制到 `.sumika-desktop/avatar-models/`（本地数据目录，不进 git；作者条款见其发布帖 BV1if421B7MH，使用前需遵守）并经 `avatar.import`/`avatar.select` 绑定为 `driver=vrm`。旧默认 `AvatarSample_A.vrm` 已通过 `avatar.unregister` 注销并自动进入发现忽略清单；仓库内置文件保留（供全新数据目录首次播种），不影响本实例。运维记录：桌面窗口关闭后受管 DSH 可能残留监听 3080，导致再次启动 fail-closed 拒绝（版本无法从 `host.describe` 验证），需先结束残留 node 进程再启动。另：网页 Route 首次发送若报 `隔离浏览器不可用`，按顺序排查——① 浏览器扩展未连接（`bsk doctor` 应显示 browsers connected ≥1，否则运行 `tools/setup-browserskill.ps1 -LaunchAgentBrowser`）；② Core 重启前遗留的命名 Profile 租约（`browser_profile_leases` 表，TTL 30 分钟，旧 owner 进程已死时可手动清除）；③ `profile.open` 在 `awaiting-extension` 期间产生的 `awaiting-browser-backend` 占位会话需 close 后重开。2026-09-03 傍晚已按此链路恢复 Kimi 网页 Route（check: ready/page_ready/authorized）。

## 接下来的三个动作

讯飞MaaS 4B已开通并正式接入，Spark Lite另有独立HTTP凭据与账户到期信息。不要重复要求注册、领权益或提供已有Key；以本页最上方和状态矩阵为最新事实，下面旧恢复点保留历史语境。

1. 继续魔搭/Ollama资源额度与网页账号/API账号绑定、消耗单价和账单watermark；不将魔粒242或Starter成功单次调用转换为未知数量的免费token。既有Gemma/两Qwen成功报告可复用，不重复基础三题。
2. 在有新证据或冷却到期时补OpenRouter/智谱任务验收；为Spark Lite、讯飞1.7B及Moark寻找可验证的更窄适用任务，不能降低既有任务门槛来宣布全模型可用。保留各自失败/冷却，不自动重发不确定提交，不充值。Moark体验不能当作生产无限权益，NVIDIA/Intern仍待外部变化。
3. 继续 DAG/真实网页恢复与 picker 建议回写、ZCode 安全文本执行器、中转渠道验收；替换旧模型名启发式与全部跨渠道执行仍待做。未配置/未登录或受限渠道不能标为完成；不恢复已删除摘录档案。

## 固定决策

- DSH 是默认 Harness，但不是 Core、UI、角色、Avatar、任务或 Workspace 的基类。
- DSH Session、Plan、Skills、Subagents 和审批是活动状态的事实源。
- MCP 使用用户 Preset 和 `dsh-mcp-client`；配置、凭据和启停仍由 Sumika 审批。
- DSH 没有可靠 rollback RPC，因此 checkpoint、diff 和恢复由独立 `WorkspaceRuntime` 负责，并通过工具暴露给 Harness。
- 社区插件必须在隔离 Profile 中验证许可证、API、权限和卸载恢复后才能启用。
- 一键启动只复用和检查用户已安装的固定 Runtime，不自动安装或更新软件。
- 模型策略使用 `model-policy/v1`；`difficulty=auto` 目前是保守规则，ZCode 额度只有在公开 app-server capability 存在时才读取，未知额度不得标为免费。ZCode adapter 默认 `SUMIKA_ZCODE_PROTOCOL=auto`，可用 `SUMIKA_ZCODE_NODE` + `SUMIKA_ZCODE_SCRIPT` 配置 Node 打包入口，或显式开启 `SUMIKA_ZCODE_AUTODISCOVER=1` 解析公开 bundle；不读取 ZCode 私有配置。
- 路由默认推荐后确认；无候选、未确认、额度耗尽或健康失败时，Session、Provider 绑定和 Execute checkpoint 均不得先行创建。
- 正式文件修改只发生在独立 worktree、分支或等价的可恢复 Workspace 中。
- 完整客户端只能通过已验证的固定 DSH 启动链；Core-only 调试不继承 PATH 中的全局 DSH。

## 明确暂缓

- 音频、视觉、Live2D 新驱动；
- 多角色自动互聊、VirtualWorld 和 LifeAgent；
- RemoteRunner、Android、macOS/Linux 正式桌面发布；
- 正式安装器、自动更新和代码签名；
- 自动安装、升级或启用第三方插件；完整日用遥测采集器等 Agent 闭环稳定后再实现。

## 当前阻塞

- 当前免费池扩充：Agnes两款及讯飞1.7B/4B三题通过但质量/费用自动准入尚未完成；讯飞4B403已由用户手动开通解决，不再等待权限。OpenRouter两Gemma分别首题429；NVIDIA手机OTP不到暂缓，不推断地区限制。硅基GLM可应答但严格输出质量不足，另两型号超时不代表不可用；userinfo410、现金账单未知。旧catalog健康与正式质量资格仍需分开，候选Profile整体未放行；不凭未充值推断不存在赠金。
- 隔离 Ollama（`127.0.0.1:11435`）现在可见 `qwen3:1.7b`（约 1.36 GB）和 `qwen3:4b`（约 2.50 GB）；1.7B 仅用于快速协议/UI 冒烟，4B 保持 DSH 默认。用户原有 `127.0.0.1:11434` 服务未停止，也没有被改写。
- 1.7B 的直接 OpenAI-compatible 请求已通过，但在标准 DSH 工具目录下工具选择和长推理质量不足；不能把“能响应”当作 Codex 日用 Agent 验收通过。
- 真实 Provider 若缺少凭据必须请用户重新输入，不得从 SQLite、日志或聊天恢复；安全启动注入已实现，模型质量仍待持续对照评估。
- 上一次隔离验收中，BrowserSkill CLI `0.1.11`、受管 Edge Agent profile 和 `ext-v0.1.7` 的 protocol 1.1 检查均通过，自动读写 smoke 已通过；人工接管请求因本轮没有用户操作而超时。DeepSeek、ChatGPT、智谱、Qwen 与 Kimi 网页 Route 于 2026-09-02 完成人工登录、页面检查、`chat.read`/`chat.send` 长期普通文本授权，并在 Core 目录中验证为 `routable=true`。Kimi 单站真实咨询已完成；ChatGPT 已有页面提交证据，但回复 DOM 提取在 300 秒后以 `deadline-exceeded` 结束且未重发，因此五站整体验收仍未通过。测试后 Core `8771` 已停止且 BrowserSkill 活动 session 为 0；豆包和敏感写操作仍需用户在明确任务中授权。网页额度仍为 `unknown`。
- 隔离 SSE stub 已验证 DSH 协议，但不会替代真实模型；真实模型复杂任务质量仍需用户主动配置 Provider 后单独评估，Sumika 不读取历史密钥或自动安装模型。
- 真实 ZCode CDP 只读 smoke 已于 2026-08-31 通过：`http://127.0.0.1:9222` 返回 Electron 版本信息，发现 1 个 page target（标题 `ZCode`），页面 `readyState=complete`；观察请求关闭正文读取，仅保留标题、URL scheme 和控件计数。端口和用户实例在 smoke 后仍保持运行。尚未验证发送、填写、登录或任何敏感动作。

## 验证记录

此前已通过的历史证据（非本轮全部重跑；当前 UI 结果及文档阻碍见恢复点）：

- Python unittest: 580 tests（含 web_chat 54：provider 轮询 pending attempt 新用例，以及模型路由推理强度契约）；Tools unittest: 58 tests；Playwright: 50 tests（50 passed；UI 重置后选择器全面更新为场景壳导航，含角色创建/卡片导入合一流程、Avatar 模型折叠区、retry、worktree/commit、队列重绘草稿、Session 恢复、会话级控制重载、历史游标翻页、网页聊天配置抽屉、模型策略推荐/确认，以及 Plan Review 三种操作）；cargo test: 8 passed（门户 site-id/URL 校验）；
- `node --check frontend/main.js`;
- frontend production build;
- `cargo check --manifest-path src-tauri/Cargo.toml` and `cargo test --manifest-path src-tauri/Cargo.toml` (6 passed);
- `python tools/check_docs.py`;
- `tools/dsh-launch.ps1` and `tools/run-desktop.ps1` PowerShell parse checks；`tools/test_dsh_launch.ps1` passed；DSH route bridge、desktop automation 和 browser policy plugins passed 19 Node tests；Python `compileall` passed；
- `git diff --check`；
- 隔离 `python tools/agent_daily_acceptance.py --runtime-smoke`：Plan Review、批准、Execute、工具、checkpoint/diff/精确恢复均通过；整体预检为 `needs-action` 仅因真实 Provider 未授权。
- `backend/tests/test_cdp_transport.py`: 4 项专项测试通过；
- 真实 ZCode CDP smoke（2026-08-31）：`health`、已有 `ZCode` page `open`、`observe(include_text=false)` 和 runner 断开通过；端口仍监听且 page target 数量未增加。
- BrowserSkill 实机：CLI `0.1.11` 与官方 `ext-v0.1.7` 的 SHA-256、daemon、扩展和 browser protocol 检查均通过；Sumika policy companion 已安装到受管 DSH profile，并完成 `browser-skill` 加载、隔离 session、只读导航、导航审批、ARIA snapshot、本地非敏感表单写入和 session stop；测试后无活动 BrowserSkill session，隔离 DSH 端口已释放。DeepSeek、ChatGPT、智谱、Qwen 与 Kimi 网页 Route 的人工登录、页面检查和普通文本授权已于 2026-09-02 验证为可路由；Kimi 单站真实咨询完成，ChatGPT 回复提取超时且未重发，五站聚合仍待完整通过。
- `tools/agent_daily_acceptance.py` 与 `--plan-execute` smoke 已完成语法检查；新的隔离 DSH `127.0.0.1:3100` profile 在 2026-08-29 通过 `--runtime-smoke --mcp --skills-subagents` 组合验收，包含 Plan→Execute、MCP、审批、diff、恢复、Skills 和 Subagents；BrowserSkill 读写组合回合也已通过。真实 Provider 的既有 Session 可用 `--real-session` 只读纳入报告，复杂任务质量仍待对照。
- WorkspaceRuntime 专项：checkpoint/恢复、状态截断、冲突/rename、worktree、patch 和精确 commit；独立 worktree 已由 DSH 完成受控文档自修改并通过 diff、恢复和本地 commit（`10ff976`）；Workspace UI：创建预览、双重确认、文本 patch、本地提交和归档路径脱敏。
Windows launcher 另以真实进程验证三条分支：复用或监督固定版 DSH，以及 DSH 缺失时 Agent fail closed；各次退出后 `3080`、`3081`、`8770`、`8771` 均释放，用户的 Ollama `11434` 未被停止。
Agent 命令闭环已验证：Session 创建后重新读取 command catalog；无 `plan` 命令的 Preset
仍可普通 Execute，只有活动 Plan 显式切换到 Execute 才发送 `/plan off`。
固定 DSH 协议 smoke 已验证 25 个工具 schema、流式请求、最终消息、完成状态和 WebSocket
事件；隔离 Workspace 的 `read/question/pwsh/edit`、命令审批、文件级 diff、恢复预览和
精确恢复均已通过。嵌套 `tool-result` 可按 `callId` 关联且丢弃原始正文；Agent Task 投影、
retry 边界、正文过滤和 Workspace checkpoint 已通过后端与 Playwright。Provider 被动目录
检查会在 Agent 状态、会话创建、模块启用、模块列表和发送前运行，端点停止会阻断请求。
真实 `glm-4.5-air` 已通过只读、`workspace-write + ask` 权限审计和 Plan Review 批准前
checkpoint 的单文件写入/精确恢复回合；统一报告验证 checkpoint 早于批准、回合完成、
唯一文件 diff、恢复预览和精确恢复，且不包含 Session ID、路径或正文。模型在更复杂任务中的规划、工具选择和错误恢复质量仍待持续评估。

Preset mount validation 已通过固定 DSH 实机验证；无鉴权 stdio MCP smoke 完成
`initialize`、工具发现、模型调用和结果回传，MCP 自定义凭据使用 Credential Manager、
固定 `process.env` 表达式和重启门控。带真实第三方密钥的端到端 smoke 仍需用户明确配置。

Provider 与 MCP 密钥只保存在 Windows Credential Manager；桌面 helper 通过私有 NUL v2 协议注入受管 DSH 启动环境。Python/Rust/UI 隔离和真实 Provider 只读回合曾通过隔离验收；当前 Provider 是否可用必须以最新 preflight/health 结果为准。

ZCode app-server 适配器已通过隔离现代 wire fixture：工作区 session、Provider/`available` 模型目录、MCP 状态、子 Agent、事件归一化、运行时偏好应答、短模型选择和完整 `runtimeModel` 校验；现代能力不再宣称 `readonly`、附件或队列。现有标准 JSON-RPC fixture 仍通过 `auto` 探测回归；真实 ZCode 自动发现实测可读到 2 个模型（`glm-5.1`、`glm-4.7`），公开额度接口未提供，保持 `unknown`。

Agent observability 已接入 Core RPC/DSH event 边界：`.sumika*/logs/agent-observability/` 只写 bounded JSONL receipt，按 UTC 日输出 p50/p95 与结果/资源汇总；不写提示词、模型输出、工具参数/结果、文件内容、凭据或 Cookie。`python tools/aggregate_agent_day.py --write` 可离线生成摘要；`agent.acceptance.evidence` 与 `--real-session` 可把既有真实闭环投影为布尔值、计数、枚举和耗时。模型策略基础 catalog、确定性难度推断、额度 TTL、固定评测任务集和推荐前确认已通过 2026-08-30 回归；长期样本质量判定、学习型分类器和自动路由仍未实现。

Skills/Subagents 专项：隔离 `.agents/skills` fixture 已被 `skill.list` 发现，`/sumika-smoke` 正文注入已确认；DSH `subagent` 已创建 one-shot 子 Agent，`subagent.list/history` 可读其摘要。该专项只使用隔离 Profile 和测试 Provider，不改变生产会话；可由 `tools/agent_daily_acceptance.py --runtime-smoke --skills-subagents` 重复执行，报告仅保留布尔值和计数。
未执行：`cargo fmt --check`，因为当前工具链没有 `rustfmt`；不得为此静默安装组件。

## 恢复顺序

1. 完整读取本页；
2. 读取状态矩阵中当前里程碑涉及的条目；
3. 检查 Git root、branch、HEAD、remote 和工作树；
4. 读取当前里程碑链接的专题文档、需求基线和相邻测试；
5. 从“接下来的三个动作”继续，并用仓库和运行时证据校验本页内容。

若本页与 Git、测试、状态矩阵或真实运行时冲突，以可复现证据为准，并在继续实现前修正本页。

## 更新规则

- 只在里程碑开始、完成、出现阻塞或切换分支时更新；
- 保持在 150 行以内，不复制专题文档或聊天过程；
- 不记录 API Key、Token、聊天正文、用户目录、临时日志或认证信息；
- 每次更新都同步当前里程碑、三个动作、阻塞和验证记录；功能完成度只更新状态矩阵，本页不得创建第二套状态定义。
