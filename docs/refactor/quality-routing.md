# 质量优先协作重构执行契约

## 授权与范围

2026-09-07 用户要求执行已修订的“Sumika 质量优先的多模型协作重构”计划。预算默认采用累计预测同时严格超过偏高估算 2 倍、且超出人民币 5 元才暂停新增付费调用；倍数与金额均可设置。预算调整不扩大权限或外发范围。

本轮实现独立 Python 核心、Sumika 宿主适配、角色/负责人设置、任务报价确认、计划修订与验证、ChatGPT 原生咨询、picker 合同修复及 SDK/MCP 包装。Qoder、虚拟居所、多角色自主行为、设备控制及发布均不在范围。已有运行数据及未提交代码保留。

## 基线纠正

- 旧 `DynamicRouteSupervisor` 提供 Worker 生命周期、取消、结果邮箱和咨询，不是完整可修订任务图。
- 旧模型名/质量分档不能证明同等质量；新核心仅在指定质量基准与有效同类任务证据下比较成本。
- picker 推荐真实 POST 存在占位；catalog 是 advisory，不拥有授权或最终路由权。
- 普通角色对话已有 persona 注入，但任务负责人和角色出口尚未统一。
- 原生门户是独立窗口；新的 ChatGPT 咨询须使用隔离的子 WebView，不能把远程网页变成本地命令调用方。

## 冻结边界

- 核心只认识 `owner_id`、`session_id`、任务和候选；宿主映射 `assistant_id`，复用现有 Assistant/MemoryNamespace。
- 任务节点包含依赖、验收、能力、允许文件、输入及质量基准。执行结果不自行授予验收通过。
- 候选由宿主注册，模型输出只能引用候选 ID，不能创造授权、价目表、质量证据或浏览器能力。
- 已确认报价及规则按任务快照；跨渠道累计已花费、在途预留及下一步预测。未知金额使用明确的调用/token 边界，不视为免费。
- 修订保留有效结果，变更节点及依赖失效；在途旧结果不直接合入新版本。提交状态不明不重发。
- 本地私有任务存储可以保存恢复必需的任务内容；事件/社区示例与成本统计不包含正文、凭据或文件路径。
- 主 Agent 决定语义规划与验收，确定性核心负责依赖、权限、预算及状态，不额外调用模型做机械判断。

## 里程碑

| 阶段 | 状态 | 完成条件 |
| --- | --- | --- |
| R0 基线与契约 | 已核对 | 旧选择器/POST 占位及身份、授权、预算边界已明确 |
| R1 独立核心 | 本地合同通过 | 独立安装后 36 项通过，包含预算/授权/质量基准快照、跨任务账号预留与 MCP stdio |
| R2 宿主工作流 | 文本首版接线通过 | 普通聊天、角色工具发起规划、报价确认、文本委派/验证、角色出口与取消；尚无工作区任务执行 |
| R3 内嵌咨询 | 原生及前端合同通过，真实对话待验收 | 隔离 WebView、固定动作、人工接管、心跳和不重发已实现；用户尚未登录新 Profile |
| R4 多渠道验收 | 部分验收 | 智谱 GLM-5.3-Flash 同模型付费文本闭环及角色引言实测通过；免费端点本轮超时，多模型/跨渠道对照、ZCode 安全执行及自动 picker 闭环未完成 |
| R5 社区包 | 本地交付通过 | 独立安装、SDK 示例、受限 MCP 与 wheel 构建/内容审查；未发布 |

## 验证与恢复

### 魔搭社区实测与每日额度（2026-09-08）

用户提供ModelScope Token，要求继续测试并询问协助每日签到。已通过隐藏输入保存至日用Windows Credential Manager的独立`modelscope-free-candidates`，读回一致；不保存Token到源码、报告、SQLite正文或命令参数。官方[API推理文档](https://modelscope.cn/docs/model-service/API-Inference/intro)指向`https://api-inference.modelscope.cn/v1`，属于魔搭社区API-Inference，不绑定商业API-Provider、不充值。公开`/v1/models`本次返回50项且无需Key，目录可读不证明账户鉴权，也不宣称这是完整目录。

精确登记并串行测试以下三款，不改变默认主模型或角色：

| 型号 | 真实结果 | 用量/延迟 |
| --- | --- | --- |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct` | 算术、严格JSON、精确文本变换3/3通过 | 输入103/输出28 token；约0.51/0.50/0.50秒 |
| `Qwen/Qwen3.5-35B-A3B` | 同三题3/3通过 | 输入110/输出977 token；约1.11/4.23/3.95秒 |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | 首题未取得符合接口契约的有效答案，报告ValueError；具体原因待查，停止该型号，无重发 | 约0.20秒；响应usage各项为0，不据此断言服务成功或未扣魔粒 |

合计7次真实请求，成功响应输入213/输出1005 token，现金账单未核实。两Qwen通过短题不代表已完成代码任务、复杂规划、视觉或推理强度验收。仅将两Qwen健康置healthy、DeepSeek置unavailable，Profile整体unavailable、3项`routable=false`。凭据引用与模型执行版本不变；原Provider、module_settings、characters与登记前备份逐项一致。其他渠道的DeepSeek结果不能套用到该Route。

新增`tools/evaluate_modelscope_candidates.py`复用有界测试器，固定社区端点/三型号，不添加商业Provider回退。公开目录非鉴权、401/402/403/429停止整批、未知提交不重发、非零费用停止、正文/秘密脱敏等43项Python回归通过。复用：

```powershell
python -B tools/evaluate_modelscope_candidates.py --data-dir D:/Code/Sumika/.sumika-desktop --report <新报告路径> --allow-confirmed-free-tests
```

**每日额度实机核查：** BrowserSkill当前连接的受管Edge与Codex内嵌浏览器是独立登录态。最初未登录；工具随后返回`user_aborted`时停止浏览器操作。用户明确回复“登陆了”后才恢复，只读取魔粒页面与切换“发放记录/消耗统计”，没有读取密码、验证码、Cookie或浏览器存储，也未用Token伪造登录。

在[我的魔粒](https://modelscope.cn/magicube/usage)查到：

| 证据 | 页面当前值 |
| --- | --- |
| 登录发放 | 200魔粒，2026-09-08获得，有效期1天 |
| 阿里云绑定发放 | 50魔粒，2026-09-08获得，有效期1天 |
| 当前余额 | 242魔粒 |
| 2026-09-08消耗统计 | 共8魔粒：标准模型6，旗舰模型2 |

当天正常登录已自动发放，无需另点签到按钮；不能声称Agent又领取一份，也不能仅凭余额猜已签到。页面只给日期与“有效期1天”，精确发放/到期时刻未知，不从观察时间推算新24小时。今日消耗统计与本轮请求相符，但不是逐请求对账或现金账单；尤其响应usage=0不能当作“没消耗魔粒”的证据。网站登录与API账户的正式安全绑定仍未写入Runtime，不自动将余额用作路由授权。

新增`tools/read_modelscope_magicube.ps1`，只读取已经登录且选中“发放记录”的官方页面；无Key、无模型调用、不登录/领取/导航。校验域名、路径、页签、唯一余额、日期/数量格式和重复记录；变更/未知字段失败关闭，不覆盖旧报告，不把总发放量当余额、不虚构到期时间。5项DOM解析测试、PowerShell语法及当前页真实读取通过。未创建每日定时任务或Codex自动化；以后按用户选择以已登录访问和到账核验实现，过期登录/验证码仍交由用户，不进行刷互动或绕过验证。

```powershell
./tools/read_modelscope_magicube.ps1 -Session <新会话> -TabId <魔粒页> -Report <新报告路径>
node --test tools/test_read_modelscope_magicube.mjs
```

证据位于`D:\Caches\sumika-free-catalog\`：`modelscope-sanity-20260908.json`、`modelscope-registration-20260908.json`、`modelscope-magicube-20260908.json`、`modelscope-magicube-usage-20260908.json`；写入前备份`before-modelscope-registration-20260908.sqlite3`、`before-modelscope-health-20260908.sqlite3`。BrowserSkill会话`aqtj`已正常停止，不沿用其旧tab ID；账号登录态未删除，下一轮创建新会话。没有修改现有主/角色选择、全局刷新状态、UI或注册系统任务。

已验证浏览器操作注意项：此页`bsk click`返回坐标不必然完成页签切换，必须重读高亮状态和内容。本次用已观察到的页签DOM精确定位并调用其click后成功切换；不因返回坐标就声称读取了发放记录。当前查询器依赖该版本DOM类名，前端结构变更时应重新核对，而不是猜测额度。

### Ollama Cloud与翻译能力补测（2026-09-08）

用户反馈书生已经无法使用，本轮暂停该渠道，不再要求创建Token；这是用户侧可用性反馈，不推断为官方全站关闭。用户正在办理魔搭账号绑定，尚未提供该渠道Key。NVIDIA仍等待正常OTP，不重复询问注册意愿。

**讯飞接线澄清：** 通用刷新/质量选择框架已存在，但并非各渠道自动适用。讯飞已接入独立Provider、安全凭据、公开目录/零价采集器和有界评测；两文本模型基础实测通过。目前`ModelPolicyService.refresh_observations`的价格采集仍接智谱，讯飞脚本尚未接入逐Profile定期刷新、发送前有效价/权益检查及正式质量/成本准入。不是已经全做完只差打开开关，也不是整个路由框架未实现；本次不修改该工程范围或静默启用候选。

Ollama Key通过隐藏输入保存到日用Windows Credential Manager，独立`ollama-cloud-candidates`，读回一致。使用云端`https://ollama.com/v1`及`processing_location=cloud`，不修改本地Ollama或其他连接。公开`/api/tags`和`/v1/models`均返回19项；GET无需Key也可成功，因此不能据此宣称鉴权或账号模型权益通过。精确登记`gpt-oss:20b`、`glm-5.3-flash`、`gemma4:31b`三项，未把公开全目录都当作免费池。

| 型号 | 真实结果 | 边界 |
| --- | --- | --- |
| `gpt-oss:20b` | 算术、严格JSON、精确文本变换3/3通过；延迟约1.60/2.15/1.99秒；输入280/输出164 token | 证明此Key可调用该型号；未核实实际余额、不可变版本或推理强度，不授予通用负责人资格 |
| `glm-5.3-flash` | 首题HTTP402，约0.55秒 | 本次账户请求被拒绝，可能涉及套餐/额度；不凭状态码细分原因，不充值、重发或更换计费路线 |
| `gemma4:31b` | 未发送 | 同批前项402触发停止，不能记为Gemma失败 |

[Ollama当前价格](https://ollama.com/pricing)明确：Free只含较小Starter模型集合和赠送用量；按照注册日每月重置、不结转、并发1。模型按token计价，先扣计划额度再扣额外余额，不能把赠送用量写成单价为零、无限调用或所有模型免费。官网没有在本次公开页面给出Starter的具体赠送金额/完整型号集合；账号余额、已消耗赠金和现金账单仍未知。本轮没有充值、订阅或新增付费授权。已知成功调用按本次公开`gpt-oss:20b`输入$0.07/输出$0.30每百万token、不计缓存估算$0.0000688，仅为消耗标价值而非现金实扣。

新增`tools/evaluate_ollama_cloud_candidates.py`复用共享白名单测试器：最多3个精确型号，每型号3题，单题1024输出token/30秒，权限/付款/429拒绝停止整批，无自动回退。公开目录不再被该渠道当作鉴权通过。健康回写仅将20B置healthy、Flash置unavailable，Gemma保持unknown；Profile整体unavailable，3项均不可路由，凭据和执行版本不变。对比登记前SQLite备份确认原Provider、module_settings与characters不变。没有修改主模型、角色模型、共享刷新状态或重启客户端。

**独立翻译探针：** `tools/evaluate_siliconflow_translation.py`发送前重新读取硅基官网输入/输出零价，并核对认证目录内唯一`tencent/Hunyuan-MT-7B`。英译中动作句、日译中状态句关键词检查通过，含时间/房间编号的第三句未通过严格保留检查；三次均正常stop，约0.35/0.29/0.45秒，输入82/输出35 token，现金未知。仅记录关键词/标识符检查布尔值，不保存译文；这个检查不是完整语义评测，第三项失败不能直接断言整句错译。每题最多256输出token，不调用屏幕/OCR，不加入通用聊天池，不回写硅基Profile。

报告在`D:\Caches\sumika-free-catalog\`：`ollama-cloud-20b-sanity-20260908.json`、`ollama-cloud-flash-gemma-sanity-20260908.json`、`ollama-cloud-registration-20260908.json`、`siliconflow-translation-20260908.json`。保存与健康回写前分别备份`before-ollama-cloud-registration-20260908.sqlite3`、`before-ollama-cloud-health-20260908.sqlite3`。本轮真实模型请求共7次：Ollama成功3次、明确402拒绝1次，翻译3次；没有重测OpenRouter或讯飞。

本轮48项离线测试通过，覆盖Ollama公开目录非鉴权、402/429/超时停止、精确端点与型号、未知账单，以及翻译零价核查、重复目录、截断/收费停止和日志脱敏。复用入口：

```powershell
python -B tools/evaluate_ollama_cloud_candidates.py --data-dir D:/Code/Sumika/.sumika-desktop --report <新报告路径> --allow-confirmed-free-tests --model gpt-oss:20b
python -B tools/evaluate_siliconflow_translation.py --data-dir D:/Code/Sumika/.sumika-desktop --report <新报告路径> --allow-confirmed-free-tests
```

**其他公开规则更新：** [魔粒说明](https://modelscope.cn/docs/magicube/intro)当前明确每日登录200短期魔粒，绑定阿里云另加50/日；使用前需验证邮箱，短期24小时、长期90天，从发放时间起算，先扣最临近到期者。API轻量/主流/旗舰平均消耗0.5/1/2魔粒每次，具体以产品为准。不是已确认用户到账250，也不执行签到、互动或领取。此前“注册送200”的弹窗不能代替完整规则。

[OpenRouter限制](https://openrouter.ai/docs/api_reference/limits)当前给出免费变体20 RPM；累计购买不足10 credits为50次/日，至少10为1000次/日。购买不是本轮动作，也不保证解除供应商429；两个Gemma保留为暂时受限而非永久退役，未自动重试。

### 讯飞MaaS凭据与免费模型实测（2026-09-08）

**最新状态：** 用户发现讯飞每款模型须手动开通服务，并已开通所有免费/限时免费项。仅复测先前被明确拒绝的4B，三题全部通过；403阻碍已解除，不再要求重复领取。1.7B和4B均已回写healthy，但基础短题不等于自动路由准入，Profile整体仍未放行。下面保留开通前后的证据，不能继续把首轮403当作当前状态。

用户补充`https://maas.xfyun.cn/modelService`列出其已开通模型服务；作为后续登录态权益来源线索，不声称本轮已读取其个人列表。已开通权限、公开价格、账户余额/资源包仍是独立事实。关于限时免费结束：沿用既有一体化计划的价格过期/变更阻断、等质免费候选重新规划、无合格免费候选时付费确认原则，不将任务软预算当作允许静默扣费。当前讯飞仅每批手工实测前实时核价，尚未接入应用定期刷新和正式发送前逐路由价目校验；不能宣称已经自动监测。未来需同时处理活动到期时间与观察TTL，任一到期、查询失败或价格不明时停止新增免费派发；即使本地检查及时，平台突然调价与请求计费仍有竞争窗口，绝对零扣费还需平台支持的硬消费上限/禁用按量结算，不能由脚本保证。

用户提供MaaS Key并指出账户页可查看免费模型，正确页面为`https://maas.xfyun.cn/account`（原链接重复拼接）。已将Key通过隐藏输入保存至日用Windows Credential Manager的独立`xfyun-free-candidates`引用并读回核验；不写源码、报告、SQLite正文或命令参数。新连接使用`openai-compatible`和官方`https://maas-api.cn-huabei-1.xf-yun.com/v2`，与旧星火APIPassword渠道分开；没有自动切换日用主模型或角色。

公开模型广场的真实XHR提供了明确`serviceId`、官方API地址和独立`price.inferencePrice`。新增`tools/read_xfyun_public_catalog.py`只读取公开目录，无Key、Cookie或模型调用，只认两款精确ID并校验输入/输出/缓存均为0元每百万token；训练/部署价格不混入推理价。重复ID、端点不符、非零/未知价格均失败，不伪造免费。4B保留限时标记，真实截止时间未知；账户额度、模型健康与免费标价分开记录。

`GET /v2/models`返回200但data为空，不把它当作Key无效或型号下线。复用有界评测器，仅在`--allow-public-catalog-probe`明确开启且当次公开目录零价验证成功时，允许将合成首题作为聊天健康探针；认证状态不由这个空目录冒充成功。每题1024输出token、30秒，最多两款三题，发送起点至少间隔3.1秒；403/429、收费或响应身份不符即停止整批。

| 型号 | 真实结果 | 当前处理 |
| --- | --- | --- |
| `spark-x2.5-1.7b` | 算术、严格JSON、精确文本变换3/3通过，正常stop且响应model精确匹配；约1.98/1.91/1.57秒 | 候选模型健康记为healthy；不是复杂规划或角色任务质量资格 |
| `spark-x2.5-4b` | 首轮HTTP403/code11200；用户手动开通后复测三题3/3通过，正常stop且model精确匹配，约4.21/1.63/2.21秒 | 开通后健康更新为healthy；不再标记账号受限，不从三题推导通用任务质量 |

首轮共4次聊天尝试，已报告输入130/输出458/总计588 token，其中reasoning422已包含在输出。用户先确认账户页4B“显示限时免费”，当时未因此重复请求；随后明确完成手动开通，追加仅4B三次调用，输入130/输出216/总计346 token，其中reasoning186已包含在输出。累计7次尝试，已知输入260/输出674/总计934 token；金额和最初403请求用量未报告，不冒充已核对账单。推理强度保持unknown。所有领取/开通由用户自行完成，Agent没有购买或改变账户权限。

登记前备份`D:\Caches\sumika-free-catalog\before-xfyun-registration-20260908.sqlite3`；报告`xfyun-sanity-20260908.json`和`xfyun-4b-after-activation-20260908.json`位于同目录。仅新Profile新增及其两款健康字段更新，8个原Profile、module_settings、characters与备份一致，凭据引用/执行版本未因健康回写变化；2项均保持`routable=false`，Profile整体unavailable，避免旧catalog绕过质量准入。未改全局刷新状态、UI或重启客户端。

新增公开价目解析及探针测试，与Agnes/硅基/OpenRouter相关测试共34项通过；覆盖显式零价、单位、身份、空目录授权、403停止、无密钥外发给目录端点，以及响应内容与模型身份验证分离。复用命令：

```powershell
python -B tools/read_xfyun_public_catalog.py
python -B tools/evaluate_xfyun_candidates.py --data-dir D:/Code/Sumika/.sumika-desktop --report <新报告> --allow-confirmed-free-tests --allow-public-catalog-probe --model spark-x2.5-4b
python -B -m unittest tools.test_evaluate_xfyun_candidates tools.test_evaluate_agnes_candidates tools.test_evaluate_siliconflow_candidates tools.test_evaluate_openrouter_candidates -q
```

已验证的故障模式：MaaS公开目录零价不代表每模型API服务已开通；4B返回403/11200后，用户手动开通解除限制。开通前后`GET /models`均返回空目录，不能用其缺项判断退役。两款接下来补真实任务契约与稳定性证据，不重复注册Key或把三道短题当作全渠道路由完成。

本次公开目录还观察到PaddleOCR-VL-1.6、DeepSeek-OCR、HunyuanOCR、Qwen3-Embedding-8B和Qwen3-Reranker-8B的零价推理字段。仅观察，尚未进行对应能力实测；PaddleOCR的公开serviceId带尾部空格，DeepSeek-OCR/HunyuanOCR的`urls.api.http`缺失，后续须核对各自官方调用样例，不猜端点或直接套文本模型请求。用户已开通全部免费服务的陈述不自动转换为各能力的健康/质量评测通过。

### Agnes文本验收与其他渠道复核（2026-09-08）

用户要求继续实测OpenRouter、Agnes及文章其他推荐。只使用已授权保存的对应官方Key，发送合成短题，不外发项目正文、换Key、充值、放宽隐私或自动晋升候选。

| 型号 | 本轮实测 | 用量与结论 |
| --- | --- | --- |
| `agnes-2.0-flash` | 算术、严格JSON、精确文本变换全部通过；正常stop，约3.44/1.15/1.29秒 | 输入932/输出78 token，含报告的50 reasoning token；可正常回答，未评复杂任务 |
| `agnes-2.5-flash` | 同一套三题全部通过；正常stop，约6.63/1.24/1.23秒 | 输入932/输出98 token，含报告的70 reasoning token；可正常回答，不能从三题推断整体强弱 |
| `google/gemma-4-26b-a4b-it:free` | 新一轮首题HTTP429，约1.12秒；停止整批、未重发 | Key仍能认证，当前目录仍零价；没有答案/usage/金额，不能判定另外14款也不可用 |

Agnes共6次调用，输入1864/输出176 token（推理token包含在输出内，不重复相加）。供应商没有报告现金字段，实际账单unknown；文档Free/default和用户提供的免费Key支持本轮有界测试，不证明永久无额度限制。`applied_reasoning_effort`与不可变模型版本仍unknown，存在reasoning token不代表指定强度已被Runtime执行。1.5不在认证目录内，本轮未调用。

新增`tools/evaluate_agnes_candidates.py`，复用硅基流动有界测试器的固定Provider白名单，按Provider隔离官方域名/模型/Profile；Agnes请求起点至少间隔3.1秒。空内容不再标记健康，429停止整批；每题1024输出token、30秒、无重发/付费回退/自动路由写入。26项定向离线测试通过。复用命令：

```powershell
python -B tools/evaluate_agnes_candidates.py --data-dir D:/Code/Sumika/.sumika-desktop --report <新报告路径> --allow-confirmed-free-tests
python -B -m unittest tools.test_evaluate_agnes_candidates tools.test_evaluate_siliconflow_candidates tools.test_evaluate_openrouter_candidates -q
```

报告：`D:\Caches\sumika-free-catalog\agnes-sanity-20260908.json`、`openrouter-gemma26-sanity-20260908.json`。本轮不回写日用Profile健康，避免旧catalog将健康等同路由资格；主模型、角色、模块配置保持原状，Agnes完整质量/成本准入仍待完成。没有重启客户端，也没有对NVIDIA、讯飞、Intern、魔搭或模力方舟进行未经认证的推理调用。

#### 官方页面的新证据

使用独立未登录Playwright上下文读取真实DOM与文档iframe；不读取用户Cookie，不自动登录或领取权益。静态HTTP壳不是不可读的最终结论，也不是价格证据。只读研究子Agent因503未产出，以下由主Agent直接核查。

| 渠道 | 本次官方证据 | 后续处理 |
| --- | --- | --- |
| 讯飞星辰MaaS | [模型广场](https://maas.xfyun.cn/modelSquare)列出`Spark-X2.5-1.7B`零价、`Spark-X2.5-4B`限时免费；另有`PaddleOCR-VL-1.6`、`HunyuanOCR`、`Qwen3-Embedding-8B`、`Qwen3-Reranker-8B`零价。`DeepSeek-OCR`虽然标限时免费，本次卡片只见体验、未见API调用入口 | 用户已答复去注册并创建Key，等待Key。先测试两款文本模型，OCR/向量/重排单独归类；限时截止时间及账号额度未知，不能假定一个月 |
| 讯飞星火Lite | [星火页](https://xinghuo.xfyun.cn/sparkapi)当前主推上述两个零价新模型；MaaS中的`Spark Lite`为输入2/输出6元每百万token。[HTTP文档](https://www.xfyun.cn/doc/spark/HTTP调用文档.html)使用独立`APIPassword`与`spark-api-open.xf-yun.com/v1` | 两渠道/凭据/价格不可混用；本次没有重新证实旧星火Lite无限免费权益，也不由MaaS收费推断旧渠道一定收费 |
| Intern | [ChatAPI文档](https://internlm.intern-ai.org.cn/doc/docs/Chat/index.html?v=1.0)已列`intern-s2-preview-397b`，默认思考，提供`thinking_mode`，默认每用户30次/分钟；[鉴权文档](https://internlm.intern-ai.org.cn/doc/docs/用户鉴权)要求登录书生/OpenXLab、生成API Token，有效期6个月。官方请求域为`https://chat.intern-ai.org.cn/api/v1` | API密钥入口位于`https://internlm.intern-ai.org.cn/api/document?lang=zh`；尚无Key，文章每月9000万输入/输出未独立确认，不写为账号额度 |
| ModelScope | [当前限制](https://modelscope.cn/docs/model-service/API-Inference/limits)要求绑定已实名阿里云账号；已改成魔粒扣减，轻量0.5/主流1/旗舰2魔粒每次，余额充足才可调用；以单并发保障为目标 | 不再沿用文章每日2000/单模型200的数值；魔粒余额、补充方式与具体型号待登录确认；商业API-Provider与社区API-Inference分开 |
| 模力方舟 | [模型广场](https://moark.com/serverless-api)仍列GLM-4-9B-0414、Qwen3-8B、DeepSeek-R1-Distill-Qwen-14B等免费。[快速上手](https://moark.com/docs/getting-started)说Gitee登录后每天100次免费调用；[API产品文档](https://moark.com/docs/products/apis)又描述购买全模型包后API调用所有模型 | 100次说明的API适用范围与免费模型前置付费条件尚不明确；本次没有确认文章10元最低门槛仍有效，不购买，不将在线体验额度等同API权益 |
| NVIDIA | 用户已同意注册，但本轮反馈手机一直收不到OTP，尚无Key | 暂缓。仅凭短信不到不能确认中国地区被屏蔽，不用接码或频繁重发绕过验证；等正常注册/官方支持解决后再测 |

Ollama保留前次官方定价的月度Starter用量/并发1证据，不重复照抄文章旧会话窗口。下一批先讯飞，其后优先考虑Intern；NVIDIA与模力方舟分别等待注册恢复和权益澄清。

### 硅基流动有界实测（2026-09-08）

用户明确确认Qwen3-8B、GLM-4-9B-0414、DeepSeek-R1-0528-Qwen3-8B免费，要求自行查找和测试。不再索要截图或将无法查余额作为人工有界测试的阻塞；“没有充值”不构成不存在赠金、不会收费或永久免费的证明。测试限定三个已登记型号、无付费替代、无任务正文外发、无后台重试。

| 型号 | 本轮真实结果 | 边界 |
| --- | --- | --- |
| `Qwen/Qwen3-8B` | 算术探针30秒超时，1次请求 | 没有usage或有效结果，提交状态未知，不重发；不能判定模型本身不可用 |
| `THUDM/GLM-4-9B-0414` | 三次正常stop，约305/669/499ms；算术和JSON严格输出契约未通过，文本替换通过 | 证明连接正常；严格契约失败不等于算术答案一定错误，不将单个文本替换样本推广为通用质量资格 |
| `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` | 算术探针30秒超时，1次请求 | 没有usage或有效结果，不重发；未验证实际思考强度或思考开销 |

共5次模型请求，GLM已知输入94、输出32、总计126 token；超时请求用量及实际现金费用未知。未调用付费型号、购买套餐、充值或修改主模型/角色。没有重测两个超时问题；GLM后两题通过`--check json --check transform`单独补齐，部分题通过不标成完整三题通过。

工具`tools/evaluate_siliconflow_candidates.py`复用既有三道固定题和严格JSON/usage校验，固定官方端点、拒绝重定向、最多3个指定型号及每型号3道题、每次1024输出token/30秒边界。测试授权允许费用字段缺失时完成有界固定题，但费用保持unknown；出现明确非零费用停止整批。未知提交/usage停止该型号，不重发；身份/权限/现金错误停止整批。报告仅保留验收布尔值、枚举、耗时和token计数，不留凭据或原始正文，也不自动写质量资格。

公开价格核查找到了[官网独立价目页](https://www.siliconflow.cn/pricing)，不同于需登录的cloud模型页。新增`tools/read_siliconflow_public_pricing.py`使用HTMLParser按`pricing-row-text-*`限定单型号行，严格检查输入/输出均为“免费”，不跨行拼接价格。当前自动提取`PaddlePaddle/PaddleOCR-VL-1.5`和`tencent/Hunyuan-MT-7B`；缓存列“-”记录为not-quoted而非免费，不推定账号额度。三个已授权测试型号未出现在这份公开价目HTML中，不据此判付费或退役。其他公开栏目也可见免费向量/语音声明，本轮不做这些能力的执行适配或健康验证。

价格脚本只做无凭据公开GET，没有模型调用或后台任务；观察结果不接入现有全局刷新状态，不覆盖智谱价格/失败记录。OCR与翻译保留各自用途，不把免费OCR作为通用聊天候选。证据可独立刷新：`python -B tools/read_siliconflow_public_pricing.py --report <新报告>`。

候选回写仅改变三项`health_state`和`last_tested_at`：GLM healthy，超时两项 unavailable。实机检查发现旧catalog的`metadata.routable`主要依据连接健康，不代表质量/费用准入；`quality_tier=unknown`仍可能被旧型号启发式投影为basic/standard/premium。尝试只更新Profile available后，断言检测到旧routable位开放，已立即将本次修改恢复为整体unavailable，保留逐型号健康证据。最后确认3项全部不可路由，模型执行版本与凭据不变；没有将猜档写成评测评分。该遗留问题留给路由内核重构，不在渠道探测中绕开质量门槛。

证据：`D:\Caches\sumika-free-catalog\siliconflow-sanity-20260908.json`、`siliconflow-glm-remaining-20260908.json`、`siliconflow-public-pricing-20260908.json`。健康回写前备份`before-siliconflow-health-20260908.sqlite3`；最终逐项核验其他Profile、module_settings、characters及模型执行版本不变。新增评测/公开价目及OpenRouter回归最终24项通过，包含响应型号不符即停止整批；未重跑无关前端、未重启客户端。

### 文章核对与新渠道接入（2026-09-08）

用户已提供微信文章完整正文，原验证码阻塞解除。文章标题为“别再被骗了！实测30多个AI市场，只有这10个API才是真永久免费无限Token”，来源仍为`https://mp.weixin.qq.com/s/VxDHKlSUwihtlnI95OtBiA`。正文是候选线索，不是账户/价格或质量事实；不复刻邀请码、榜单等价推断或多账号扩充额度做法。文章本身把OpenRouter列为低优先级备选，不是前十推荐之一。

首次文章核查的逐渠道处置（后续实测及新DOM证据以上方最新小节为准）：

| 渠道 | 已核查与尚未确认的边界 | 顺序/用户动作 |
| --- | --- | --- |
| 硅基流动 | [官方速率文档](https://api-docs.siliconflow.cn/docs/userguide/faqs/rate-limit-and-upgradation)确认实名认证后使用免费模型，账单调用消耗为0；限流按账户和逐型号设置，RPM/TPM可分别触发，不是每个Key单独计算。具体型号零价与额度尚待控制台/API核对 | Key已保存、已登记3项，待逐型号价格与质量验收；不默认所有9B以下免费 |
| Agnes | 官方仓库确认Free/default Key类型；同类型Key共享限流池，参考实际文本20 RPM。当前文档有2.5型号和不同上下文数字，账号免费权限仍需单独核实 | 已保存Key、已登记观察项；先验收文本，不做图片/视频生成 |
| NVIDIA NIM | [官方目录](https://build.nvidia.com/models)本次显示38个Free Endpoint；DeepSeek V4 Flash 0731与Nemotron 3.5 Lightning页面均显示Free Endpoint Available及`https://integrate.api.nvidia.com/v1`示例。网页免费标识不能证明账号限额、生产用途或实时健康 | 用户愿意注册并创建Key，等待Key；不把文章40 RPM视作所有型号通用保证 |
| 智谱 | 既有两Flash官方零价与真实应答证据保留；文章给出的并发数仅待重新核查的来源线索。免费模型文档旧链接本次404，不能据此判定模型退役 | 保留现有池；其他视觉、图像和视频型号需要各自价目与能力适配，不塞进普通文本池 |
| 讯飞星辰MaaS | 文章称有小模型、OCR及生图免费API；本次模型广场返回动态壳，未获得逐行价格证据 | 下一批；OCR/ASR等归相应能力池，先核实是否要实名、领取权益及独立Key |
| Ollama Cloud | [当前定价页](https://ollama.com/pricing)说明免费Starter模型用量按注册日期每月重置，免费并发1；旧会话/周窗口不应继续沿用。未公布的具体免费金额/token数保持unknown | 次优先；免费云端与本地Ollama分开Profile，不能套用文章5小时/7天估算 |
| 书生/Intern | 月度9000万token与具体模型能力目前只有文章线索 | 后续核官方控制台及账号条件，不赋予已验证额度 |
| 魔搭 | 本次限制文档仅取得动态壳，文章每日2000/单模型200次未独立核实；作者可用性测试也不是当前账号证据 | 后续按账号绑定、单型号限额与实测处理 |
| 讯飞星火Lite | 文章称须领取无限量权益；当前账号权益与并发尚未验证 | 最后作轻量备用；先确认领取动作与HTTP兼容性 |
| 模力方舟 | 文章称调用0元但须先购买10元资源包，尚未核查该前置条件是否仍存在 | 暂缓，不把前置付款视作纯零成本，不沿用智谱付费测试授权购买新平台套餐 |

Agnes官方依据：[模型目录2026.07.30](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/main/MODEL_CATALOG.md)、[Token Plan FAQ](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/main/docs/TOKEN_PLAN_FAQ.md)。较新的目录声明2.0由临时1M回退到256K、2.5为512K；另一篇6月FAQ仍把2.0写为512K，故记录文档冲突而不把这些值写成Runtime已验证上下文。官方明确价格/配额/可用性可能变化，不能保证“永久”。

#### OpenRouter保存与首轮验收

用户注册后提供普通API Key。通过隐藏输入写入`.sumika-desktop`对应的Windows Credential Manager并读回确认，SQLite仅含引用。`GET https://openrouter.ai/api/v1/key`返回200：`is_free_tier=true`、`is_management_key=false`、初查usage/daily/weekly/monthly均为0，`limit`与`limit_remaining`为null。null不代表免费请求无限，也不能从金额usage推算剩余调用次数。

新工具`tools/evaluate_openrouter_candidates.py`每次仅允许3个固定通用候选，每个至多三道既有短题；先GET /key并重取公开全分量零价目录，再指定精确`:free`型号、输入/输出价格上限0、关闭上游fallback和要求参数支持。不请求插件，不改账户隐私，不发送项目内容。401/402/403/429、隐私不匹配、提交未知、身份或费用/usage不明时停止整批；报告只保存布尔验收、枚举、token数及供应商报告费用，不保存Key或答案正文。

真实首轮只有一次`google/gemma-4-31b-it:free`算术请求，返回HTTP429；整批立即停止，没有对其他候选发请求、没有重试或转付费。不能从这一次429判断账号额度用尽或16个型号都不可用。没有成功usage和费用回执，所有候选仍不可自动路由。账号已能认证，不应再要求用户注册或重复提供同一Key。

工具及登记测试共12项通过，命令：`python -B -m unittest tools.test_evaluate_openrouter_candidates tools.test_register_openrouter_free_candidates -q`。真实测试工具可复用：`python -B tools/evaluate_openrouter_candidates.py --data-dir <日用目录> --report <新报告路径> --allow-free-tests`；本次未重复执行此命令，不为等待限流开启后台重试。

#### Agnes保存与观察目录

用户回应创建Free/default Key的请求并提供Key，已用同样的隐藏输入/凭据库边界保存到新`agnes-free-candidates`，官方端点`https://apihub.agnes-ai.com/v1`。登记`agnes-1.5-flash`、`agnes-2.0-flash`、`agnes-2.5-flash`三个文档候选；认证`GET /models`成功，明确返回2.0/2.5但不含1.5。1.5仅观察，不能根据缺失结果自动发聊天探针或宣称退役。

三者的质量/成本/健康和推理强度仍为未知，不推定视觉或工具能力已验收；新Profile内部默认2.0不改变日用主模型或角色。未调用Agnes聊天、图像或视频接口。后续按免费Key实际权限核查账户限制，针对2.0/2.5进行有界短题、用量与费用验收，再进入具体任务的质量评测，不凭宣传跑分晋升负责人。

#### 硅基流动保存与目录核查

用户先同意自行注册实名，随后表示注册完成并提供Key。已通过隐藏输入保存到`siliconflow-free-candidates`，官方端点`https://api.siliconflow.cn/v1`，读回核验通过。认证`GET /models`返回96项，取精确ID登记：`Qwen/Qwen3-8B`、`THUDM/GLM-4-9B-0414`、`deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`。不存在的旧拼写`THUDM/glm-4-9b-chat`没有登记。

这三项的目录行只提供id/object/owned_by，没有价格信息；`GET /user/info`返回410，无法取得余额或实名状态，不能据此判断Key无效或余额为0。公共模型页仅返回动态壳，未得到可核实的逐型号计费行。未进行聊天调用，成本/健康/质量/额度保持unknown且不可路由。下一步优先查当前官方模型计费规则或用户明确提供的控制台证据，确认免费权益后再有界评测；赠金与免费零标价分开记录。

本轮证据在`D:\Caches\sumika-free-catalog\`：`openrouter-account-20260908.json`、`openrouter-sanity-20260908.json`、`agnes-registration-20260908.json`、`siliconflow-registration-20260908.json`；对应操作前备份`before-openrouter-key-20260908.sqlite3`、`before-agnes-registration-20260908.sqlite3`、`before-siliconflow-registration-20260908.sqlite3`。最终与Agnes登记前备份比对：除了新增Agnes/硅基连接，所有原Profile、角色和模块设置一致，OpenRouter16项、Agnes3项、硅基3项均不可路由；未重启客户端或改UI。

### OpenRouter免费候选登记（2026-09-08）

用户要求参考微信文章`https://mp.weixin.qq.com/s/VxDHKlSUwihtlnI95OtBiA`新增免费候选。脚本访问被引导到验证码，尚未获得标题/正文；打开内嵌浏览器的请求返回queued，当前没有可用的标签页读取连接，不代表已读取文章。已请用户完成验证或提供正文/截图。以下是独立核对的官方来源，不归因于该文章：

- [公开模型目录](https://openrouter.ai/api/v1/models)：显式`:free`后缀，输入/输出及所有返回的价格分量均为零；这只证明本次观察的公开标价。
- [官方FAQ](https://openrouter.ai/docs/faq)、[API限制](https://openrouter.ai/docs/api-reference/limits)：免费变体受请求限制与账号条件影响，多建Key/账号不能增加额度，负余额可能阻断免费请求。当前服务器渲染正文未给出完整数值，不硬编码每日/每分钟额度。
- 用户回复需要先注册，已提供[Keys页](https://openrouter.ai/settings/keys)。不代替用户注册、不要求充值、不自动放宽隐私。取得Key后用官方`GET /api/v1/key`核查可见限制/usage，接口未提供的剩余请求数继续标为unknown。

本次登记16个独立型号：

```text
cohere/north-mini-code:free
dots-studio/dots-3-note-preview:free
google/gemma-4-26b-a4b-it:free
google/gemma-4-31b-it:free
inclusionai/ling-3.0-flash-fin:free
inclusionai/ling-3.0-flash-sante:free
liquid/lfm-2.5-2.6b:free
nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
nvidia/nemotron-3-super-120b-a12b:free
nvidia/nemotron-3-ultra-550b-a55b:free
nvidia/nemotron-3.5-content-safety:free
nvidia/nemotron-3.5-lightning:free
poolside/laguna-s-2.1:free
poolside/laguna-xs-2.1:free
thinkingmachines/inkling-small:free
thinkingmachines/inkling:free
```

日用`.sumika-desktop`新增`openrouter-free-candidates`，端点`https://openrouter.ai/api/v1`，不保存凭据。全部仅声明待验证的chat，质量/成本/健康未知、`routable=false`；目录声明的多模态和上下文仅留在观察报告，不从名称推定视觉、代码或思考能力。专用模型也不视为通用聊天替代者。没有调用任何模型或改变主模型、角色绑定、其他Profile、module_settings及characters；后3项已逐项对比备份确认。

复用工具`tools/register_openrouter_free_candidates.py`：固定公开GET、拒绝重定向、限制响应体与候选数，不读取Key/Cookie；默认仅输出新的`--report`，给定`--apply --data-dir <已有目录> --backup <新备份>`才落库，拒绝覆盖已有Profile/报告/备份。3项测试覆盖全分量零价格、重复身份和未经授权不可路由。核验命令：`python -B -m unittest tools.test_register_openrouter_free_candidates -q`。

证据与操作前备份分别为`D:\Caches\sumika-free-catalog\openrouter-observation-20260908.json`、`D:\Caches\sumika-free-catalog\before-openrouter-registration-20260908.sqlite3`。未注册定时任务或接入共享刷新作业，避免当前全局pricing/catalog状态把其他来源失败错误地清除。下一次日用启动可加载新连接；8881隔离预览不使用该数据。

后续顺序：核查Key限制与隐私/供应商路由条件；按候选精确ID做免费健康及有界固定题测试；再接按来源隔离的价格有效期/退役检测与路由授权。不得自动退回无`:free`后缀的付费同名模型，不把公开零价格当作已验证账号额度，不自动改当前负责人。

### DeepSeek连接与模型目录（2026-09-08）

用户授权长期保存DeepSeek Key并加入候选池。已在日用目录创建`deepseek-official`，端点为`https://api.deepseek.com/v1`，Key经隐藏输入写入Windows Credential Manager并读回确认，SQLite只保存凭据引用。只读模型目录实际返回`deepseek-v4-flash`、`deepseek-v4-pro`、`deepseek-v4-flash-vision-exp`，没有假设旧型号仍存在。

已核验三者均出现在ModelPolicy目录，`routable=false`。仅完成目录访问，不宣称聊天、视觉、价格、额度或质量评级通过；连接的未就绪状态表示待验收，不代表API不可连接。未发送聊天请求，未修改当前主模型/角色配置。原Profile、module_settings和characters与操作前备份一致；备份`D:\Caches\sumika-quality-zhipu-live\before-deepseek-registration-20260908.sqlite3`。新连接下次日用启动加载，隔离8881预览并不读取该目录。

### Flash再次复测与登记（2026-09-08）

后续授权优先：用户在登记后明确旧Key已作废，要求统一当前Key。原日用`zhipu-glm-45-air`现已安全更新，凭据修订变化、旧健康记录清除后GET只读健康检查通过，不额外发送聊天。原连接与Flash备选均已读回核验为当前保存的测试Key；不更换默认模型。此更新覆盖下文初次登记时“不覆盖原连接凭据”的历史描述。轮换前数据库备份为`before-zhipu-key-rotation-20260908.sqlite3`，其中不存Key正文。

用户确认自己可以调用并要求再测，后再次提供与已保存测试凭据相同的Key。复测证据纠正“无法接通”的表述：两个API都已成功响应。4.7-Flash算术通过，随后JSON请求HTTP429，供应商数值错误码1305；不能仅凭状态码臆断限流具体机制。4.6V-Flash算术通过，JSON题收到正常stop及usage，但未通过严格验收；没有做视觉/OCR验收。共6次有界聊天请求，其中3次HTTP429，已知输入70/输出341 token，现金费用未知。诊断工具只增加有限数值错误码和固定错误类别，不保存供应商原始错误正文。

主机原日用智谱Profile与测试Key不同，故不覆盖原连接。在`.sumika-desktop`新增`zhipu-flash-candidates`，两款模型保留`unknown`质量/价格，只加入待评测目录，原主模型、角色绑定和模块选择不变。账号凭据仅存Windows Credential Manager，已读回验证；既有Profile、module_settings及characters与操作前SQLite备份一致。新的Profile默认模型仅影响该连接内部，不代表切换当前日用模型。三题准入尚未完成，不能宣称已开启自动执行。

复用工具：`tools/register_zhipu_flash_candidates.py`要求明确`--data-dir`、两份一小时内成功连接的`--reports`、不存在的`--backup`路径；默认只预览，`--apply`才登记，已有同名Profile拒绝覆盖。工具不调用模型，不把报告升级为通用质量资格，失败则保留安全禁用状态。当前登记与评测工具28项测试通过。客户端未重启，下一次日用启动加载新连接；隔离8881预览与日用目录不同。

证据位于`D:\Caches\sumika-quality-zhipu-live\`：`glm47-flash-diagnostic-20260908.json`、`glm46v-flash-diagnostic-20260908.json`及前置`*-retest-20260908-b.json`；操作前备份为`before-flash-registration-20260908.sqlite3`。下一步按已知限制优化测试间隔并补具体任务评测，不因为模型能回答一次就授予负责人或视觉任务资格。

### 发送前执行绑定（2026-09-08）

本次继续补齐实际派发边界，不进行新的云端调用，不修改日用 Provider、凭据或助手配置：

- API 候选增加宿主生成的 `execution_revision`，摘要覆盖端点、凭据修订号、模型配置/版本、能力与现金价目。摘要不含原始 Key；模型显示名称、健康检测时间及资源包剩余额度不作为执行版本。独立核心将版本纳入任务及辅助调用的授权快照，价格或执行版本变化后不能借用旧确认。
- API 任务在 Runtime 创建前和发送前复核当前 Route、权限、健康、额度状态、配置、价格与当前助手的评测资格。角色 API 聊天使用同一复核，保留原始消息角色、工具、温度、流式输出及 usage；绑定改变或跨助手复用被拒绝。显式推理强度必须有该版本/强度的独立评测，实际请求沿用选定强度，不再丢失角色绑定中的强度。
- 资源绑定持久记录账户配置摘要，与任务的执行版本分开。更换端点、凭据修订或归档会使旧运行时停止；即使重建 Runtime 或重启 Core，也不能把旧包余额套到新 Key。修改模型名称不会误触发账户重绑。绑定丢失、过期或撤销时保留限制，不能返回未保护的现金 Provider。
- `RequestNotSent` 仅表示宿主在提交前明确拒绝，费用/token 结算为零并释放对应预留。超时、取消、缺少 usage 或已有部分回复时仍保留未知预留，不能重分类成零消费。
- 资源绑定 Route 的 `health_check` 只允许被动模型目录检查，不能经底层自动聊天探针绕过预留；若必须聊天验证，返回 `chat_probe_blocked`。有界聊天评测应走受保护的 `stream`，不能将 `allow_chat_probe=True` 当作绕过额度策略的授权。

兼容与恢复：旧无执行版本的任务保留历史，但不匹配新候选，需要新建计划并确认。旧资源快照没有账户配置摘要时只作观察，需重新经过可信、同账户且已授权的 reader 刷新；不能直接修改账本标志放行。更换账户/Key后，当前首版应恢复原绑定或新建独立 Provider Profile 并重新核实账户；原 Profile 的显式重绑 UI 尚未实现。

剩余边界：账户页面与 API 的真实同账户核实、显示时区、供应商账单 watermark 对账、资源刷新任务按 Profile 独立状态，以及全部跨渠道验收仍待完成。本次没有放宽观察期、自动晋升两个 Flash 或替换日用负责人。

验证：后端全量758项通过；独立核心39项通过、2项可选MCP跳过；刷新/评测工具61项通过；离线SDK示例输出`completed`，默认`git diff --check`通过。质量专项74项、资源包装器17项覆盖价格变更、助手隔离、选定强度传递、凭据更换/重启、取消、部分回复及明确未发送的预算释放。本次未改前端，也未重跑UI或真实渠道测试。

### 零成本刷新与动态选择（2026-09-08）

本轮在既有核心上增量实现，未替换日用绑定、删除旧代码或写入运行凭据：

- `RefreshCoordinator` 使用 `model-policy/refresh-v1.json`、跨进程锁与原子写入；资源精确型号/账户隔离、先到期先预留。观察过期、账户未核实、显示时区未知均不作为免费余额。
- `ResourceBoundProvider` 接在 Profile 的实际 runtime 出口，普通角色、质量任务、动态 Provider Worker 共用发送前预留；取消、超时、usage未知保留预留，usage超过上限停止后续抵扣。绑定过的资源失效不会悄悄退回现金。
- 官网静态 HTML 是 SPA；`read_zhipu_public_pricing.mjs` 使用无登录、无权限的临时 Chromium，读取完整明确的型号行与输入/输出/缓存列，任何收费/未知列均不能判免费。只依赖本地已有 Node/Playwright，不自动下载安装。
- `ZhipuResourceReader` 复用固定官方资源表 DOM，或注入本地 OCR 的严格表格。宿主可指定 session/tab/Profile，默认未验证账户绑定、不自动授权额度、显示时区未知。RPC 不能上传价格/质量/授权事实。
- `SelectionEvidenceStore` 存每助手、候选完整身份、模型版本、cohort版本、样本与多源先验元数据，不保存正文；成功样本至少三次，显式推理强度必须有匹配的应用证据。负责人按实测质量选择，角色合格后比较成本；先验只影响实测同分排序，不能授予任务等价资格。
- `quality.bindings.select` 展示理由；设置新增 `selection_mode` 与 `candidate_pool`，默认保持 fixed。首次自动规划需独立的付费/未知费用确认；已执行过的自动负责人变化需重新保存选择设置后才采用，不静默换人。`quality.task.replan` 复用原修订边界。
- 核心 `Candidate.prepaid_tokens/prepaid_until` 只在观测新鲜且整次 token 上限可覆盖时给零现金预测，执行仍须宿主原子预留；云端预测不等于已核实账单。

复用命令（必须指向当前 Core 的真实端口，不启动 Core、不导出 Cookie）：

```powershell
python tools/refresh_model_catalog.py --all --noninteractive --core-url http://127.0.0.1:8881
python tools/refresh_model_catalog.py --all --dry-run --core-url http://127.0.0.1:8881
./tools/register_model_refresh_tasks.ps1 -CoreUrl http://127.0.0.1:8881 -WhatIf
```

注册脚本只有用户实际执行后才安装任务，已有同名任务拒绝覆盖；每12小时询问 Core，由 Core 的独立24h/12h TTL判断是否访问上游。应用关闭只尝试 loopback，不访问官网、不启动应用。Core运行时另有低频维护。配置 `SUMIKA_ZHIPU_RESOURCE_SESSION`、`SUMIKA_ZHIPU_RESOURCE_TAB`、`SUMIKA_ZHIPU_RESOURCE_PROFILE` 可指定只读资源观察源；它们不会自动证明 API 与网页同账户或启用抵扣。资源绑定及 paid override 的完整 UI尚待做。

**本轮真实证据：** 2026-09-08公开页面两Flash输入/输出/缓存列均为免费，共采集6条明确行；非全目录快照，不宣称完整数值价格刷新或模型下线检测已完成。两个Flash不在账号的GET模型列表；显式聊天健康模式下4.7-Flash前两题成功（输入49/输出346），第三题未取得有效结果且未重发；4.6V-Flash首题HTTP429，未重发。报告为 `D:\Caches\sumika-quality-zhipu-live\glm47-flash-probe-20260908.json` 与 `glm46v-flash-probe-20260908.json`。实际收费未知，未自动晋升模型。复测工具 `tools/evaluate_zhipu_candidates.py` 需显式 `--saved-key --allow-paid`；GET未公开模型时只有 `--allow-chat-health` 才允许首题作为健康探针；整轮最多3题、每题1024输出token，任意失败即停止。

**验证：** 后端全量740项通过；刷新/评测工具61项通过；独立核心37项通过、2项可选MCP跳过；质量UI单测5项；浏览器质量流程/状态/公开DOM共4项通过，状态面板1440×900、1280×800、390×844无横向溢出；生产构建通过。全前端单测有一项既有能力页文案断言不一致，未覆盖改写；不把局部UI通过冒称整套原生客户端回归。

**剩余边界：** 尚无资源真实账户/时区绑定与供应商watermark对账；保守扣减可能低估余额。真实权威榜单输入、通用质量等价样本、完整数值/活动价解析、旧启发式路由替换、复杂任务自动重规划和网页恢复、ZCode/中转/picker跨渠道验收仍未完成。现有R0–R5阶段历史状态不代表新Phase0–6全完成。

### GLM-5.3-Flash 最新复验

2026-09-07 用户明确授权长期保存智谱 Key 与小规模付费测试，随后指定 `glm-5.3-flash`。已通过现有 Windows Credential Manager 保存为 `approved-provider-tests` / `zhipu-official` 并读回验证；不在源码、账本、命令参数或报告中记录 Key，不更改日用 Provider。测试只将该授权引用读入隔离内存 Core。

- `glm53-direct.json`：1 次真实请求，精确答案及正常终止通过；输入 24/输出 48 token，标价估算 ¥0.0001536。
- `glm53-only-workflow.json`：5 次请求，输入 835/输出 1298 token，标价估算 ¥0.0043024。暴露精确格式被负责人误判通过、角色引言 300-token 请求被截断的问题，不能记为通过。
- `glm53-verified-workflow.json`：修复后 13 项全部通过；5 次请求，输入 1003/输出 1620 token，标价估算 ¥0.0053384。覆盖真实普通对话、规划/报价、确认前不执行、确认后执行、审查、非空角色引言与答案保留。报告均在 `D:\Caches\sumika-quality-zhipu-live`。
- 本轮付费模型合计 11 次，已报告输入 1862/输出 2966 token，未折扣标价合计 ¥0.0097944；保守预留合计 ¥0.0661912。按 [当日官方价格](https://open.bigmodel.cn/pricing)的未折扣输入 0.8/输出 2.8 元每百万计算，不计活动价、缓存或资源包。实际账单与余额均未知，截图里的 4.5-Air 资源包不能证明 5.3-Flash 免费。
- 免费 `glm-4.5-flash` 本轮另有 3 次健康探针超时，均未取得 usage；对应 `glm53-acceptance.json`、`glm53-workflow.json`、`glm53-workflow-final.json`。关闭探针思考、临时延长等待至 30 秒仍超时，未确认供应商侧原因；已撤回无改善的超时调整，不继续重复请求。

已验证原因及修复：5.3-Flash 引言的 300 输出 token 中 reasoning_tokens=295，finish_reason=length 且无可见正文；默认思考的角色出口改用 1024 总输出 token，明确 `off` 的角色仍为 300，均先走预算预留，不静默降低负责人推理。最终引言输出 638 token（含思考 567），finish_reason=stop。仅记录思考存在与计数，不记录或输出思考正文。官方 4.5-Air/Flash 的 `off` 映射为 `thinking.disabled`，relay 与 5.3-Flash 不套用该映射；Profile→目录→候选统一使用现有 `off` 标识。截断/过滤响应不再作为成功结果。

精确格式验收增加明确判负提示，合成验收题保留严格 `42` 断言；本次通过不证明 LLM 审查永不漏判，也不产生便宜模型普遍等质证据。后端全量 638 项通过；随后角色预算/审查提示改动的专项 31 项通过。未改前端/Rust，未重跑 UI。全局文档检查存在用户已删除摘录文件与历史索引等既有问题，不恢复已删除内容。

### 限时资源包查询调查（2026-09-07）

用户要求利用账号限时额度，并允许研究网页/OCR 查询。已核对 [官方费用说明](https://docs.bigmodel.cn/cn/faq/fee-issues)：标准 API 调用先抵扣满足模型适用场景的资源包，同场景先扣最早到期者，再扣现金；过期不续期。官方指向 [资源包](https://open.bigmodel.cn/finance/resourcepack) 与 [费用明细](https://open.bigmodel.cn/finance/expensebill/list?active=detail)。本轮检索公开文档索引和财务 FAQ，未找到公开、版本化的标准 API 资源包剩余查询接口；这不证明后台没有内部接口，不猜路径或提取网页凭据。

已用现有 `RapidOcrJsonProbe` / 本地 RapidOCR 实际读取用户截图：GLM-4.5-Air 11,136,035 token、GLM-4.7 5,000,000 token、GLM-4.6V 6,000,000 token，另有按次及搜索包。随后用户通过 BrowserSkill 人工接管确认“已登录”，成功读取“我的资源包”完整 DOM，无需 OCR 猜测截断字段。实时结构化观测保存在 `D:\Caches\sumika-quality-zhipu-live\resource-packs-observation.json`，观察时间 `2026-09-07T10:59:27Z`：

| 适用范围 | 当前可用 | 页面显示到期时间 |
| --- | --- | --- |
| `glm-4.5-air` | 11,136,011 tokens | 2026-11-20 20:12:08 |
| `glm-4.7` | 5,000,000 tokens | 2026-11-28 13:22:25 |
| `glm-4.6v` | 6,000,000 tokens | 2026-11-20 20:12:08 |
| `search-std`, `search-pro`, `search-pro-quark`, `search-pro-sogou` | 100 次 | 2026-11-20 20:12:08 |
| 按次计费基础模型推理（图片/视频包） | 20 次 | 2026-11-20 20:12:08 |
| 通用 token 包 | 0，已失效 | 不作为可用额度 |

本次还沿用既有小规模测试授权，以保存的官方测试凭据调用一次 `glm-4.5-air`：显式 `off`、最大输出 256，精确答案通过、finish_reason=stop，输入 22/输出 2/合计 24 token。调用前 Air 余额 11,136,035，约 4 分钟后页面显示 11,136,011，差值恰好 24，构成真实资源包扣减证据；调用后 23 秒刷新时尚未变化，不能即时读一次就判断未抵扣。未新增模型启用或修改默认 Provider，未购买/充值，也未调用其他额度模型。费用明细仅取白名单业务字段、不取客户或 API Key ID；当日该笔结算明细尚未获得，因此不将包余额变化等同于完整现金账单对账。

建议接线顺序是公开用量 API（存在时）→用户已授权官方页面 DOM 表格和详情→局部截图本地 OCR→用户核对。截图读不到的模型后缀、单位、到期时刻或使用范围保持未知，不能推断；人工登录/验证码由用户完成，不读取登录输入或导出 Cookie。网页登录和资源包 DOM 读取已验证，自动长期同步尚未接线。

复用工具：`tools/read_zhipu_resource_packs.ps1 -Session <active-session> -TabId <resource-tab> -Report D:\Caches\sumika-quality-zhipu-live\resource-packs-observation.json`。使用已有 BrowserSkill `0.1.11`，在用户已登录且选中 `#tab-my` 的官方页运行；只读取 DOM，不自动导航、登录或付费。工具核对域名、路径、页签、列名和行边界，保存页面字段原值、观察时间与待核对标识，不保存 Cookie/账户标识。错页拒绝且不生成报告的实机验证与 PowerShell 解析通过。BrowserSkill 在后台 tab 的 click 可能返回坐标却未切换页签；先 `tab select` 目标 tab，再点击并读取 `aria-selected` 验证，不以 click 成功作为查询成功。

后续实现应区分资源包的生效/到期时间与观测 TTL，记录账户、包标识、精确适用模型/端点/能力、tokens/次数单位、剩余量、来源与置信度。宿主采集私有账户额度，公共核心只接收归一化观测，不把账户额度混入 model-picker 公共价目表。质量合格后再优先使用临期资源；需共享账户预留、扣除本地在途消耗与安全余量，并核对调用后的资源包抵扣账单。客户端无法阻止其他客户端并发用量或平台超包转现金，因此未经实时对账不得承诺绝对零扣费；沿用已有付费授权及预算边界，不因添加额度来源而扩大授权。

当前 `QuotaSnapshot` 有通用状态/TTL，协作核心有现金预留，但尚无资源包精确适用范围、到期排序或 token 包预留的完整实现；本节是经核对的方案，不是已接通自动路由声明。

### 历史与跨渠道边界

ChatGPT 本轮授权与接管：2026-09-07 用户明确要求授权登录网页并拿来测试。之前打开的隔离窗口现已退出，未确认用户是否完成登录；尚未发送测试消息。恢复可复用保留的隔离目录，不读取认证输入、不导出或迁移 Cookie。恢复信息见 [当前执行记录](../current-execution.md)；这不是网页登录或咨询通过证据。此次最新测试仅使用智谱 API，不因 API 成功就宣称跨渠道通过。

2026-09-07 真实 API 最小闭环通过：用户新提供智谱凭据用于小规模测试，余额自述 ¥3.52；仅向官方端点发送合成任务，使用内存 Core/凭据，不改变日用数据。以官方列为免费的 `glm-4.5-flash` 验证普通聊天、规划、报价、确认前不执行、确认后执行、负责人审查及精确答案交付。`tools/quality_live_smoke.py` 在真实 Provider 传输前限制目的地址、模型、调用次数和 token，拒绝重定向，不打印或保存密钥/正文。真实调用不是本地 fixture；本次不验证 Tauri/本地 HTTP 传输或网页渠道，不将 R4 标为完成。

成功轮证据：`D:\Caches\sumika-quality-zhipu-live\acceptance.json`，10 个必需检查全部通过，6 次调用（健康 1、普通聊天 1、规划/执行/审查/角色引言各 1），输入 746、输出 2962 token。角色引言的 300 token 请求未返回可见正文，交付采用保留已验证答案的降级路径；这是已知限制，不记为角色润色通过。请求推理强度为默认，应用强度未获服务端确认，不能将默认思考或输出额度等同于已验证的推理档位。

含定位修复的整轮共 22 次聊天 API 请求，均锁定同一免费模型；其中 3 个早期健康探针未采集 usage，累计已报告输入 1990 / 输出 8737 token（非完整总量）。按 2026-09-07 [官方免费模型说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-4.5)推算费用为 ¥0，未读取实际账单或余额，不声称余额仍精确等于 ¥3.52。另有不产生聊天 token 的目录查询。失败报告仍保留，`first.json` 为目录漏列预检，`second.json`/`diagnostic.json`/`final.json` 为结构失败，`contract.json` 为链路结束但精确答案失败；不能把这些文件名或 HTTP 200 当作验收通过。

本轮回归：后端全量 631 项通过；最后新增原始约束修复后的协作/Provider/HTTP/工具专项 24 项通过。未重跑前端和 Rust，因本轮未修改它们；其历史证据如下。

本轮已验证的兼容问题：智谱 `/models` 返回 200 却未列出可实际调用的免费模型；只有显式连接测试才追加 `max_tokens=1` 探针，同进程后续被动刷新可沿用该证明，修改 Profile 后失效。规划输出需要明确对象结构、枚举和数组字段；解析仅兼容单一完整 JSON 代码框，不从杂文抽取对象，也不接受顶层数组。执行和终端节点审查保留用户原始目标，避免规划遗漏精确格式约束后仍被判通过。

当前证据：全量后端 627 项通过；随后增加同等质量执行者与浏览器心跳用例，宿主/Provider/HTTP 闭环最新专项 15 项通过；picker 专项 12 项、工具 58 项、Rust 26 项通过。前端构建和 `custom-protocol` 桌面构建通过；浏览器全量首轮 64/65，通过后的 A+/协作/咨询专项 6/6，追加切页阻断提交的最新专项 3/3。首轮失败是能力页刷新后的导航等待超时，单独复现未出现；未修改旧能力页实现或放宽断言。前端单测 13/14，遗留失败为 `capability-layout.test.js` 断言旧错误文案，而现有页面已简化该文案。

文档检查仍因用户删除的 `original-excerpts.md` 及历史引用、旧目录索引/映射和当前执行记录长度失败；不恢复用户删除的文件，不把遗留失败写成全绿。原有 A+ 证据不是本轮新工作流验收。

当前宿主是文本任务流，不自动写入工作区。ZCode modern app-server 未暴露可验证的只读模式，旧 Harness Worker 会使用执行模式和当前工作目录；因此未经宿主注入验证过的文本执行器时，Harness 候选明确不可用。这是尚未完成的工程接线，不仅是缺少登录。网页真实登录/提交、跨渠道质量对照和真实费用均未验收；不以夹具结果代替。

原生远程页同时受本地 HTTP 与 Tauri IPC 隔离：Core 拒绝非许可 Origin/Host，避免远程咨询网页绕过原生命令门控调用本地服务。

## 本地使用与复测

智谱真实验收：`python tools/quality_live_smoke.py --saved-key --allow-paid --paid-only --report D:\Caches\sumika-quality-zhipu-live\new-run.json`。使用已授权系统凭据，仅以 5.3-Flash 执行；去掉 `--paid-only` 会尝试 4.5-Flash 角色与 5.3-Flash 负责人组合，去掉 `--allow-paid` 则只允许固定免费模型。`--probe-paid` 替代 `--paid-only` 可只发一个独立付费测试请求，无免费端点前置条件。`--save-key` 仅保存输入且不发请求；未使用保存引用时通过隐藏输入或 `--key-stdin` 私有管道提供 Key，不放命令行或环境变量。

每轮最多 8 次、单次输出 4096 token、输入 JSON 16000 字节，按未折扣标价保守预留上限 ¥0.50，固定官方目的地/型号，拒绝重定向和超限请求。发生提交状态未知时本轮停止，不自动重放。脚本调用真实 Core RPC 分派器和 HTTPS Provider，不启动本地 HTTP/Tauri；离线保护与三种工作流夹具由 `python -m unittest tools.test_quality_live_smoke -q` 验证。报告仅含检查项、格式标志、终止原因和用量；不保存聊天正文、Key 或思考正文，不把标价估算当作账单。

源码启动器已将 `backend/src` 与 `packages/quality-routing/src` 一并加入子进程 `PYTHONPATH`。通过 Python 安装使用时，先安装本仓库的独立包，再安装后端，避免请求尚未发布的同名包：

```powershell
python -m pip install ./packages/quality-routing
python -m pip install ./backend
```

在设置里分别选择角色候选与任务负责人；普通对话无需另起分类模型。任务页选择已授权资源池、摘要外发范围，生成计划与报价后确认执行。修改全局预算只影响未来任务；已创建任务使用自身规则。没有同类任务的明确质量等效证据时，保持负责人执行，不自动把便宜模型当作合格替代品。

`register_quality_evidence` 与 `register_text_executor` 是宿主 Python 接口，不是模型可调用的授权 RPC。当前没有自动质量训练、自动 Provider 启用或通用工作区执行器。`model-picker` 的真实 POST 推荐与回写传输已修复，但宿主尚未自动将它的推荐/评价用于新工作流；公共榜单也不能直接充当质量等效证据。

原生咨询复测证据：`D:\Caches\sumika-consultation-smoke\1788738091484\result.json`。无登录 smoke 验证加载、远程 IPC 与 HTTP 拒绝、隐藏/接管/释放和强杀后的租约恢复。网页登录由用户在新 Profile 中完成；当前 broker 超时后的原调用恢复仍需进一步连接到任务终态恢复，不能通过重发代替。

本轮双模式原生回归：`D:\Caches\sumika-quality-native-final\1788739515348\result.json`，7 项通过，包含真实 WebView2 画布、480×420 桌宠、透明像素、草稿、窗口恢复与退出清理。测试先运行 `npm run build`，再运行 `cargo build --manifest-path src-tauri/Cargo.toml --features custom-protocol --offline`；普通 debug 构建依赖 8771 开发页，不能在未启动该页面时用于离线原生验收。

浏览器截图位于 `D:\Caches\sumika-quality-browser-consultation-final` 和 `D:\Caches\sumika-quality-browser-lifecycle`，覆盖 1440×900、1280×800、480×420。咨询截图使用明确的 native/bridge mock，不是网页登录成功证据。

社区 wheel：`D:\Caches\tooling\quality-routing-r5-wheel\quality_routing-0.1.0-py3-none-any.whl`，SHA-256 `e8a276c608d99ed1444a6fe5479f80944fbb5ba9220229377f6ec6ef6f369e93`；只包含 6 个独立模块及发行元数据。构建隔离环境通过现有 pip 源下载构建依赖，不改变全局工具环境。验证环境 `D:\Caches\tooling\quality-routing-r5-venv` 未设置源码 `PYTHONPATH`，36 项含 2 项真实 MCP stdio 合同通过，SDK 示例输出 `completed`，`pip check` 通过。
