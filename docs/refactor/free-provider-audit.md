# 文章十个正面推荐渠道核查

后续更新：用户随后已提供Spark Lite与Moark HTTP凭据，两者完成实测；Spark Lite截图确认无限量、并发5、有效期至2036-12-31 00:18。以下是前面的官方只读核查快照，最新执行/质量结论见[正式免费路由](free-model-routing.md)，不要继续索要这些凭据。

Moark最新进展：用户确认并授权使用现有¥10资源包，官方余额接口核实。扩大核查10款免费文本及10款专用服务，免费Qwen3-8B通过适配后的固定测试与Core真实调用，已正式接入日用；扩展测试共30次，资源包扣减¥0.0034866。下文仅为早期公开核查，不能继续用“尚未鉴权/仅体验”覆盖本轮实证。

本次补查结论：**Moark 有当前零价模型，也有无需购包的有限体验 API；正式使用仍涉及资源包条件，不能写成无前置条件的永久免费无限 API。Spark Lite 的独立 HTTP 接口仍有官方免费说明，当前控制台前端明确提示实名认证可取得不限量资格；实际账号领取状态、期限和并发仍未核实。** 两者均未进行推理调用，不因这份报告直接放行正式路由。

## 范围、来源与观察时间

- 用户原文：`C:/Users/Lostrain.DESKTOP-43S7UNP/.codex/attachments/167e8858-43d2-4a17-8111-b098146051ec/pasted-text.txt`。已直接读取全文，没有访问微信。
- 本次网络观察：**2026-09-08 05:40:26–05:46:54，Asia/Shanghai（UTC+08:00）**。这是实际读取时间，不是官网发布日期、权益起算时间或有效期。
- 其余八渠道复用 [quality-routing.md](quality-routing.md) 中标为 2026-09-08 的最新渠道记录；该文件本次读取时修改时间为 2026-09-08 04:46:47。表中历史实测不是本次重新调用、重新查账或读取凭据的结果。并行主 Agent 的正式路由实现与后续记录不由本文件判定完成。
- 已检查 `D:/AGENTS.md`、`D:/Code/AGENTS.md`、`D:/Code/Sumika/AGENTS.md`、`docs/AGENTS.md`、`docs/refactor/AGENTS.md`，均不存在；`docs` 下搜索也未发现额外 `AGENTS.md`。适用用户本轮给出的全局约定与仅写此文件的限制。
- 本次只做无账号凭据的公开 GET，读取官网 HTML、文档、官网引用的公开 JavaScript 和公开目录 JSON；未读取用户密钥、Cookie、浏览器存储或日用数据，未注册、认证、领取、充值、下单、发消息或向聊天模型提问。唯一主动写入文件为本文件，使用 `apply_patch`；不改共享执行记录、代码，不建分支或 commit。

**“文章所有推荐”指原文编号 1–10 的全部正面推荐，不等于文末反面／踩坑名单。** OpenRouter、DeepSeek 官网、LongCat、Cloudflare 等不算这十项；即使项目已有这些渠道，也不能拿来补足十项或据作者评价永久封禁。讯飞星辰 MaaS 与讯飞星火 Spark Lite 分别占一项，不能合并。

## 十个正面渠道完整表

本表是渠道审计与已有证据摘要。“三题通过”仅指既有算术、严格 JSON、精确文本变换短题，不证明复杂任务质量、长期稳定性或正式路由已启用。第 4、10 项来自本次官网观察，其余来自上述执行记录，未重新刷新网站。

| 原文序号 / 渠道 | 可信官方 URL | 免费权益与已有结果 | 阻碍 / 不确定项 | 最少用户操作 |
| --- | --- | --- | --- | --- |
| 1 Agnes | [官方目录](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/main/MODEL_CATALOG.md)、[套餐说明](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/main/docs/TOKEN_PLAN_FAQ.md)；既有端点 `https://apihub.agnes-ai.com/v1` | 已有 Free/default 凭据；`agnes-2.0-flash`、`agnes-2.5-flash` 各三题通过。记录参考文本 20 RPM，同类型 Key 共用限流池 | 现金账单未知，上下文文档有冲突；不证明无限免费、复杂任务或多模态能力；1.5 未在认证目录出现、未测 | 无新增注册或交 Key 动作；沿用既有连接，后续由主 Agent 补任务质量与成本证据 |
| 2 硅基流动 | [价目](https://www.siliconflow.cn/pricing)、[限流规则](https://api-docs.siliconflow.cn/docs/userguide/faqs/rate-limit-and-upgradation)；既有端点 `https://api.siliconflow.cn/v1` | 三个用户确认免费的文本型号已测：Qwen3-8B、DeepSeek-R1-0528-Qwen3-8B 超时；GLM-4-9B-0414 正常应答，严格算术/JSON 契约未过，变换通过。公开 OCR、Hunyuan-MT-7B 有零价；翻译三题中两题关键词检查过、一题标识符保留未过 | 免费按精确型号核对，不能泛化为全部 9B 以下或固定 1000 RPM；超时用量/账单未知，翻译检查不是完整语义评测 | 已完成账号与凭据准备，无需重复；后续按具体用途验收，OCR/翻译不混入通用聊天池 |
| 3 讯飞星辰 MaaS | [模型广场](https://maas.xfyun.cn/modelSquare)、[已开通服务入口](https://maas.xfyun.cn/modelService)；既有端点 `https://maas-api.cn-huabei-1.xf-yun.com/v2` | `spark-x2.5-1.7b` 零价；`spark-x2.5-4b` 限时零价。用户已手动开通，两款各三题通过；4B 原 403/11200 阻碍已解除 | 4B 活动截止、账户资源及实际账单未核实；不能用 MaaS Key/模型价代替独立 Spark Lite 权益 | **无需重新开通这两款**；正式逐路由刷新及质量准入由主 Agent 接续 |
| 4 模力方舟 Moark | [模型广场](https://moark.com/serverless-api)、[访问令牌规则](https://moark.com/docs/account/access-token)、[公开目录](https://moark.com/api/pay/services?type=serverless&status=1&size=1000) | 本次确认 Qwen3-8B、DeepSeek-R1-Distill-Qwen-14B、GLM-4-9B-0414 的公开操作汇总均零价；默认免费体验令牌无需购包、不会扣费。快速上手称每账号每天共 100 次 | 体验次数受限且官方要求勿用于生产；正式使用要求购资源。10 元最低门槛、账号实际额度、无限并发、GLM-4.7-Flash 当前可用性未证实；默认故障转移可能改变最终计费算力 | 若仅继续体验核查：用已有 Gitee 账号登录，在令牌页确认默认体验令牌及剩余次数即可，不必先充值；正式使用的购包事项另行决定 |
| 5 智谱 BigModel（原文误写 GigModel） | [当前价格](https://open.bigmodel.cn/pricing)、[费用规则](https://docs.bigmodel.cn/cn/faq/fee-issues) | 既有 GLM-4.7-Flash、GLM-4.6V-Flash 输入/输出/缓存零价证据；两者曾成功响应，最新复测仍有 429/严格 JSON 契约未过。GLM-5.3-Flash 是另有授权的付费测试，不计入免费证明 | 三题准入及视觉验收未完成，账单未知；文章并发数字未重新确认，旧免费文档 404 不证明退役 | 当前凭据已统一，无需重复提供；由主 Agent 补适配任务证据，不把付费授权扩展至其他平台 |
| 6 NVIDIA NIM | [官方目录](https://build.nvidia.com/models)；既有官方示例端点 `https://integrate.api.nvidia.com/v1` | 既有公开页观察到 38 个 Free Endpoint，并有具体模型免费端点示例 | 用户收不到正常 OTP，尚无 Key/推理实测；目录标签不证明账号额度、生产许可或所有型号 40 RPM，不据此判地区封禁 | 待正常 OTP 或官方支持解决；不重复要求注册、不用接码或频繁重发绕过验证 |
| 7 Ollama Cloud | [官方价格](https://ollama.com/pricing)、[云模型](https://ollama.com/search?c=cloud)；既有端点 `https://ollama.com/v1` | Free 为较小 Starter 模型集合和赠送用量，按注册日每月重置、不结转、并发 1。`gpt-oss:20b` 三题通过；`glm-5.3-flash` 返回 402 后停止，`gemma4:31b` 未发送 | 赠送金额、余额及完整 Starter 型号集合未知；模型按 token 计价，先扣计划额度再扣额外余额，不是单价零或无限 token；文章 5 小时/7 天估值不沿用 | 无需重复提供 Key；若要解除 402，仅在已有账户查看套餐/用量即可，不要求订阅或充值 |
| 8 上海人工智能实验室 / 书生 Intern | [ChatAPI](https://internlm.intern-ai.org.cn/doc/docs/Chat/index.html?v=1.0)、[API 入口](https://internlm.intern-ai.org.cn/api/document?lang=zh)；文档域 `https://chat.intern-ai.org.cn/api/v1` | 既有文档列 `intern-s2-preview-397b`、默认思考、30 RPM；鉴权需登录书生/OpenXLab，Token 有效期 6 个月 | 用户反馈已无法使用，因此暂停；不能推断官方全站关闭。原文月度输入/输出各 9000 万 token 未独立确认 | 当前无操作，不再要求创建 Token；仅在用户恢复此渠道时重新核查 |
| 9 魔搭 ModelScope 社区 API-Inference | [API 文档](https://modelscope.cn/docs/model-service/API-Inference/intro)、[限制](https://modelscope.cn/docs/model-service/API-Inference/limits)、[魔粒规则](https://modelscope.cn/docs/magicube/intro) | 已改魔粒制：每日登录 200、绑定阿里云另加 50；既有 2026-09-08 登录态观察确认两笔到账，余额 242，消耗 8。`Qwen/Qwen3-Coder-30B-A3B-Instruct`、`Qwen/Qwen3.5-35B-A3B` 各三题通过；本渠道 DeepSeek-V4-Flash-0731 响应结构失败 | 余额是此前观察值，本次未读取账户；精确到期时刻、逐请求对账及 Runtime 同账户绑定未确认。文章每日 2000/单模型 200 已不适用 | 已绑定且当天已到账，不重复签到/领取；以后正常登录后核对到账。社区 API-Inference 与商业 API-Provider 分开 |
| 10 讯飞星火 Spark Lite | [产品入口](https://xinghuo.xfyun.cn/sparkapi)、[HTTP 文档](https://www.xfyun.cn/doc/spark/HTTP调用文档.html)、[Lite 控制台](https://console.xfyun.cn/services/cbm) | 本次 HTTP 文档明确 Lite 免费；独立 `model=lite`、`APIPassword`。当前控制台发布代码提示实名认证可获 Lite 不限量使用资格 | 未读登录账户，领取/开通是否完成、精确期限和并发未知；未独立证实“永久免费＋五并发”，与已开通 MaaS 不互通 | 复用已有讯飞账号，打开 Lite 控制台；仅缺实名时认证，选已有应用，仅缺权益时领取/开通，再在该版本 HTTP 区获取 `APIPassword`；无需充值或重开 MaaS 服务 |

## Moark：本次官方证据

### 当前端点与协议

[文本生成文档](https://moark.com/docs/products/apis/texts/text-generation)在 **05:42:14 +08:00** 返回 HTTP 200，明确：

- OpenAI 风格 Chat Completions：`POST https://api.moark.com/v1/chat/completions`，SDK `base_url=https://api.moark.com/v1`。
- JSON 请求，`Authorization: Bearer <访问令牌>`；支持非流式与 `stream=true`。这是文档中的鉴权类型，本次没有取得或使用任何令牌。
- 模型使用平台精确 `ident`；不要把其他平台的 `Qwen/`、`THUDM/` 前缀或已有智谱凭据迁入。文档示例里的 Qwen2.5-72B-Instruct、DeepSeek-R1 也不是免费型号证明。

### 公开零价目录

产品页首次 GET 只显示“0 个模型 / 暂无数据”，这是动态页面初始 HTML，不能作为退役结论。后续从该页引用的公开前端代码定位到无登录目录：

`GET https://moark.com/api/pay/services?type=serverless&status=1&size=1000`

**05:46:16、05:46:54 +08:00** 均返回 HTTP 200。最终响应 `total=237`、实际 `items=220`，因此不宣称完整目录覆盖；按精确、区分大小写的 `ident` 核到以下各一条：

| 模型 `ident` | 服务 ID | 输入最低/最高价 | 输出最低/最高价 | `free_operation_count / operation_count` |
| --- | --- | --- | --- | --- |
| `Qwen3-8B` | 2065 | 0 / 0 | 0 / 0 | 4 / 4 |
| `DeepSeek-R1-Distill-Qwen-14B` | 1999 | 0 / 0 | 0 / 0 | 2 / 2 |
| `GLM-4-9B-0414` | 2075 | 0 / 0 | 0 / 0 | 1 / 1 |

证据字段为 `operation_summary.min_input_million_tokens_price`、`max_input_million_tokens_price`、`min_output_million_tokens_price`、`max_output_million_tokens_price`，以及操作数量；三条 `min_price/max_price` 也均为 0、`status=1`、`access_scope=PUBLIC`。这里只确认公开操作汇总零价，不把目录状态当成 API 健康、已授权资源、缓存等未列分量价格或账户账单。

原文所荐 `GLM-4.7-Flash` 没有在本次返回项中精确匹配。由于 `total` 与返回数不一致，这只能记“本次未检出”，不能宣称退役或继续沿用原文免费结论。

### 免费体验、正式使用与付费歧义

| 官方来源与观察时间（2026-09-08，+08:00） | 当次内容 | 可据此作出的判断 |
| --- | --- | --- |
| [快速上手](https://moark.com/docs/getting-started)，05:41:36 | Gitee 登录；“每个账号每天可以免费调用各种模型，共 100 次”；随后介绍在线体验和 API | 有每天 100 次的公开规则；没有给出精确重置时刻、账号余额或是否所有调用路径共池 |
| [访问令牌管理](https://moark.com/docs/account/access-token)，05:42:14 | 系统默认创建“免费体验访问令牌”，“无需购买资源即可体验接口调用”，“使用该令牌不会产生任何扣费”；次数有限，“请勿用于生产环境，如需正式使用请购买资源使用付费令牌” | 明确存在无需预付费的 API 体验途径，不能再把免费说明仅解释成网页聊天；结合快速上手可作为有限体验线索，实际令牌限制仍需账户确认 |
| [Serverless API 产品说明](https://moark.com/docs/products/apis)，05:41:36 / 05:42:14 | 正式流程要求购买模型资源包，选已购资源及有授权的令牌；使用中的资源包不支持退款 | 正式使用与免费体验不同；零价型号本身不消除资源包准入条件 |
| [购买资源包说明](https://moark.com/docs/billing/purchase)，05:42:48 | 预付费资源包、支持自定义购买金额、用完或到期前抵扣 | 未给出本次可确认的“最低 10 元”；不能承诺充入金额永远不会耗尽或过期 |
| [全模型资源包公开详情](https://moark.com/api/pay/services/1910)，05:46:54 | `name=全模型 Token 资源包`、`sale_mode=recharge`、`price=0`，未返回最低充值额和操作价 | 这里的通用 `price=0` 不能证明资源包免费，也不能反证需付款；本次没有创建订单 |

**额外计费事实：** 产品说明明确默认可启用故障转移，并按“最后一次成功调用的算力模型”扣资源包金额。正式零成本接线若以后获准，应按文档显式设置 `X-Failover-Enabled: false`，并绑定精确型号、资源与当次价格；不能仅检查原始模型零价后允许自动转到另一计费算力。本次未修改任何路由或请求头实现。

**最少后续操作与阻碍：** 若用户只想验证体验途径，用已有 Gitee 账号登录 [访问令牌页](https://moark.com/dashboard/settings/tokens)，确认系统默认体验令牌是否存在、适用模型及剩余次数即可，无需先创建付费令牌或充值。只有没有 Gitee 账号时才涉及注册。正式生产使用、最低购买金额与资源包有效期仍需另行核实和选择；本次用户没有授权购买。本次未确认无限 token、无限并发、SLA、账户鉴权或真实调用成功。

## Spark Lite：本次官方证据

### 独立端点与协议

| 协议 | 当前官方端点与模型字段 | 鉴权与来源 |
| --- | --- | --- |
| HTTP / OpenAI SDK 兼容 | `POST https://spark-api-open.xf-yun.com/v1/chat/completions`；SDK `base_url=https://spark-api-open.xf-yun.com/v1`；`model=lite` | `Authorization: Bearer <该版本 APIPassword>`，JSON；[HTTP 文档](https://www.xfyun.cn/doc/spark/HTTP调用文档.html)，05:41:37 +08:00，HTTP 200；支持流式/非流式 |
| WebSocket | `wss://spark-api.xf-yun.com/v1.1/chat`；`parameter.chat.domain=lite` | `AppID`、`APIKey`、`APISecret` 与 URL 签名；[WebSocket 文档](https://www.xfyun.cn/doc/spark/Web.html)，05:41:37 +08:00，HTTP 200；[官方签名文档](https://www.xfyun.cn/doc/spark/general_url_authentication.html)为该页引用的协议来源，本次未单独读取 |

HTTP 文档将 Lite 描述为“具有更高的响应速度，支持免费使用”，列最大输入 8K、最大输出 4K，`max_tokens` 为 1–4096、默认 4096。**不限量权益不等于单请求无限上下文或输出。** 文档要求先领取免费额度，并去对应版本控制台获取 `APIPassword`；不同版本默认密码不同。不要直接使用文档中针对 Max 的 `generalv3.5` 示例。

### 当前免费资格、入口与证据强度

1. [产品入口](https://xinghuo.xfyun.cn/sparkapi)在 **05:40:26 +08:00** 返回 HTTP 200，但静态 HTML 是 JavaScript 壳。本次继续读取其公开发布脚本，没有停在“无法读动态页”的结论，也没有操作登录页面。
2. [产品页当前功能脚本](https://xhspdup.xfyun.cn/static/js/2737.089dfab9.chunk.js)在 **05:43:48 +08:00** 返回 HTTP 200；当前主推 MaaS 的 `Spark-X2.5-1.7B` 免费与 `Spark-X2.5-4B` 限时免费，另有名为 Spark Lite 的定制模型条目，链接落到 MaaS。这些不是独立 `model=lite` 的价格/额度。此前记录的 MaaS Lite 输入 2 / 输出 6 元，也不能用来判断独立 Lite 收费与否；不同商品页可能本就不同。
3. [Lite 控制台](https://console.xfyun.cn/services/cbm)在 **05:45:57 +08:00** 返回 HTTP 200 的应用壳。它引用的[当前控制台脚本](https://console.xfyun.cn/index.6eccd060d71f6d8a8e09.bundle.js?80ef2a8f33081bf527e3)在 **05:45:58 +08:00** 明确映射 `key=cbm`、标题 `Spark Lite`、路径 `/services/cbm`，并在该服务且账号未实名时提示：**“您还未进行实名认证，前往实名认证即可获取Spark Lite的不限量使用资格”**，目标为 [实名认证入口](https://console.xfyun.cn/user/authentication)。

第三项是官网当前发布的前端条件与文案证据，**不是本次在用户登录账户实际看到的提示或已到账记录**。它与 HTTP 免费说明共同支持“Lite 存在免费／实名后不限量资格”的结论；尚不足以证明该用户已经获批、无需领取、没有期限或今后永久免费。带内容哈希的脚本是本次可复核快照入口，后续发布可能更换，应从产品页/控制台重新定位。

**仍未确认：** 原文“并发数 5”的当前官方对应条款、账户实际并发/RPM、精确到期时间、是否已完成应用绑定与领取。HTTP 文档列日流控、秒级流控及并发超限错误，不能从“不限量”推导没有速率限制。未发送任何 HTTP 推理或 WebSocket 建连，不能宣称凭据有效、模型健康或任务质量合格。

### 最少用户操作

1. 复用已有讯飞账号打开 [Spark Lite 控制台](https://console.xfyun.cn/services/cbm)，核对服务名确为 Spark Lite。现有 MaaS 登录/实名是否共用以页面实际状态为准，不预先要求再注册或重复认证。
2. 仅未实名时按官方提示完成实名认证；优先选择已有应用，仅没有适用应用时才创建。核对 Lite 免费／不限量权益，只有尚未开通或未领取时才执行该动作。无需充值；不能拿 MaaS 两款已开通来冒充 Lite 也已开通。
3. 如后续另行开展接入，从 **Lite 版本 HTTP 服务接口认证信息**获取 `APIPassword`，通过项目既有安全入口保存；不要粘贴到本报告或共享正文，也无需重复提供已有 MaaS Key。本次未索取或读取认证材料。

## 本次完成与交接边界

已完成原文十项对齐、两家公开官网当前端点/协议/权益条件/用户操作核查，记录实际时间和可追溯 URL。原有渠道取最新记录，保留 MaaS 开通后成功、魔搭已到账、书生暂停和 NVIDIA OTP 阻碍，未用旧状态覆盖新事实。

Moark 与 Spark Lite 可交给主 Agent 作为独立渠道接线依据，但账号鉴权、权益到账、健康、账单和任务质量均不由本次公开读取证明。这里的未知项是清楚标明的证据边界，不是已完成账号接入，也不要求在本次只读任务中注册、领取或测试。未生成临时报告、网页下载文件或其他持久工具产物；无需运行或修改代码测试。
