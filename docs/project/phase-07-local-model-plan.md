# 端侧模型与多设备扩展实施记录

## 2026-10-19 LFM2.5-24B-A2B vs MiniCPM-V 4.7 现场对比

- **LFM2.5-24B-A2B 是 LFM2.5 家族最大、也是最后一款**（24B total / 2B active，text-only，40 层、64 专家、top-4、131k 上下文，Q4_K_M 约 14.5GB）；没有更大的 LFM2.5，LFM2.5-8B-A1B 更新但更小，LFM2.5-VL-3B 是视觉小模型，LFM1 40B MoE 是上一代。
- **LES 不能直接测 LFM**：LFM GGUF 是 `arch=lfm2moe`，`--moe-experts` 只接受 `qwen35moe`；要 LES 化需给 `src/models/lfm2moe.cpp` 写适配，LFM 本身更小、普通 llama.cpp 已能跑，未做。
- 普通 llama.cpp 实测（测试时复制到 D: SSD，测试后已删除副本，原始保留在 F:\GGUF；`-ngl 99 --n-cpu-moe 99 --reasoning-budget 0 --no-warmup`）：
  - 短英文：prompt 13.5 / generation 5.8 token/s，总 10.1 秒；v4.7 LES 8.5 / 7.1、8.9 秒。
  - 中文改写：LFM 13.1 秒、generation 12.8 token/s，约束保留但接近逐字；v4.7 LES 16.45 秒、5.4 token/s；常驻 35B 32.55 秒。
- **2026-10-19 用户决定：继续用 MiniCPM-V 4.7 35B-A3B 作常驻单模型**；LFM2.5-24B-A2B 仅作纯文本备选，不再作为主力。理由是 4.7 覆盖 OCR/视觉/多模态，单模型即可满足当前 Sumika 场景；LFM 的文本速度优势不足以抵消视觉缺口。本地能力上限与“本地/主模型”路由、估时策略见 [local-model-capability-and-routing-20261019.md](local-model-capability-and-routing-20261019.md)。
- 选型：需要 OCR/视觉/多模态 → v4.7；纯文本/角色/Agent 且追求速度 → LFM2.5-24B-A2B。两者同时常驻会接近 6GB 显存上限，不建议默认双开。LES 对 LFM 没有额外收益。


## 2026-10-19 提示词优化接入（预览/确认）

- 工作台输入区按钮改为钢笔图标，接通预览/差异/显式确认；只在辅助模型启用且包含 `prompt_enhancement` 时可用，不自动发送。
- 新增 `openai-compatible-local` 辅助 provider：仅 loopback HTTP、不带 key、不回退云端；笔记本 LFM 通过 SSH 隧道接入。
- LFM 24B 不适合改写；同集补测后 Qwen2.5-7B 产品链路 6 条实际改写、1 条原样、3 条跳过、1 条拒绝，但样本仅 11 条单轮，注入/拒绝在原始输出中会出错。**质量门未通过，按用户决定暂不由本地模型负责提示词优化。**
- Gemma3-4B（JSON 后退化重复）、Phi-4-mini（改写弱、会改坏 diff）、Bonsai-9B Q2（正文为空）淘汰；Qwen3-4B 也不足以转正。
- 过严的逐字保护已修正（硬约束逐字+软约束同义归一、注入跳过、拒绝反转仍拒绝），但产品保护不能替代模型质量。
- 新增可管理 SSH 隧道（loopback、BatchMode、状态/重启、Bridge 关闭清理、可选预加载）；默认关闭，仅作为未来候选模型基础设施。
- 完整记录与证据见 [提示词优化接入验收](acceptance-20261019-prompt.md)、[模型对比](acceptance-20261019-prompt-bench.md) 与 [可管理隧道](managed-tunnel.md)；测试后已停止 LFM/隧道并恢复 8082/8083。

## 2026-10-18 16:08 只读状态复核

8084 health/models不可达，SSH实际进程只有8082（PID5064、4.02B blob）和8083（PID4932、1B视觉blob），没有LFM服务。SSH可用，未发送推理请求、未改服务或默认。证据：`.sumika-next/acceptance-20261018/laptop-readiness-current.json`。用户选定主力仍是LFM2.5-24B-A2B；后续按已记录参数临时隔离启动并验证，不把8082冒充主力。

## 2026-10-18 提示词优化接入前现场检查

用户最新要求将提示词优化重新纳入P6完成后的工作，并指定笔记本端模型。复用资产为工作台输入区按钮、`ui/management.py`预览API、`extensions/models/auxiliary.py::enhance_prompt`及原有原文保护/差异逻辑；按钮已改为钢笔图标并接通，日用未启用，真实改写质量未通过。

本轮只读探测：`192.168.31.227:8084` 的 `/health` 与 `/v1/models` 超时；8082、8083的`/health`返回ok，但`/v1/models`仅返回本地blob路径，无法确认具体模型身份。因此本次未向笔记本发送推理请求，也没有模型质量结果。现有辅助provider要求Ollama loopback，或要求HTTPS/凭据的OpenAI-compatible服务；它不能直接访问笔记本llama.cpp的HTTP接口。后续优先采用SSH本地端口转发，将笔记本端口映射至Sumika loopback，再实现无云端回退的本地OpenAI-compatible连接；不允许为了省事改成明文LAN HTTP。

2026-10-19已执行：SSH 核验 8084 进程/模型文件，LFM 身份确认后经 loopback 隧道调用；普通/否定/预算样本出现原样返回或被原文保护拒绝，代码/diff 正确跳过。链路与失败关闭通过，真实改写质量和真实按钮浏览器流程仍未通过，因此不启用日用。证据见[接入验收](acceptance-20261019-prompt.md)。

## 第四轮核验更新（2026-10-17）

主 Agent 已逐条核对本轮60条原始响应及清理收据。优化空间仍存在：LFM固定前缀缓存三组同输出对照，总耗时中位10.234→1.155秒，收益来自prefill，不能外推全部请求。Bonsai9B Q2_0（2.56GB）已隔离加载，结构化代表5/5、多轮本夹具比LFM少旧偏好错误，但fresh身份仍不理想。LFM12轮出现旧偏好回退、编造已复习和fresh身份混淆，因此长期角色验收仍未通过。主力选型仍为LFM，产品未接入此次优化、未改共享服务或默认。下一步优先完整角色卡、身份专项、历史扰动复测及缓存接线评估，详见独立优化报告第四轮。此前各轮“本轮未测9B”仅是当轮范围，不是当前状态。

## 2026-10-17 AIHOT 端侧资讯与真实候选评测

已接入为项目只读参考来源：<https://aihot.news/agent>；工具 `tools/evaluate_edge_news.py` 保存时间戳、原始正文与SHA256，不安装远程Skill、不建订阅、不改产品UI。最近7日模型30条与端侧/Liquid/Qwen检索已读；AIHOT返回序列存在发布时间逆序，因此按原始发布日重排。完整来源、候选淘汰依据、下载revision/SHA、运行与清理证据见 [edge-model-news-20261017.md](edge-model-news-20261017.md)。

最值得比较的新候选是 **2026-10-15发布的 Ternary Bonsai 2**。本轮已真实测试其2B与4B Q2_0，使用原llama.cpp、CPU-only、4096 context、独立8086，经SSH回环隧道串行发送合成夹具；CPU基线不占用GPU；追加GPU实验见下，不改选型或自启。节点直连HF失败后改为本机固定revision下载并SCP，双端SHA核对通过；权重保留在源码外的 `D:/Caches/models/`、节点 `F:/GGUF/`。

- 2B：19条非空且均stop；完整日常轮严格JSON语义3/6（另一次先行6项烟测4/6，说明采样有变异），列表推导错成[0]、翻译夹英文、自我说明，新会话身份混淆。热轮总耗时中位2.326s，0.553～5.145s；冷首请求13.697s另列。不能替代LFM。
- 4B：19条非空且均stop，严格结构化5/6（教学视频误判game），翻译/导数/代码/计划正确；角色记住最新偏好且不谎称操作，但新会话将用户叫成“澄”并编造“现在复习”。热轮总耗时中位5.330s，1.387～15.919s；首字中位0.918s。比2B好，但未证明胜过LFM或通过长期角色验收。测试PID6712/5764与2B的6392/4792均已精确停止，原1252保留。
- 2026-10-15 NVIDIA Bolt E4B原文写明10-23才发布，未测试；74B/24GB版不合硬件。d1-ultra原文仅提供付费云API/概率决策输出，不能作为本地聊天替代；501B Beam/816B Muse Spark等超硬件淘汰。Bonsai9B内存较小但本轮未扩大评测，不声称不可运行。

当前主力仍为用户选定 **LFM2.5-24B-A2B**，其既有5/6结构化及角色不达标边界仍有效。不同模型/CPU与GPU混合offload、采样、缓存条件不同，不能把本轮小样本响应时间当公平吞吐跑分或总体质量证明。

追加低显存探索已完成：[独立优化报告](edge-inference-optimization-20261017.md)。Bonsai4B GPU轮19/19非空、JSON5/6，中位0.931s（CPU5.330s），GPU总占4332MiB；角色身份/计划仍失败。MoE4All1.0.3两次真实受限加载现有35B GGUF均因专家arena不足退出，未生成。Strata当前实验性支持Pascal（旧绝对否定过时），但当前大模型资源不合适；AirLLM是SSD层流式而非全权重RAM要求，未新测；vllm-xtu-moe当前Linux/sm75+路线排除本机。ExLlamaV3、KTransformers、IPEX-LLM、ZLUDA及原生投机逐项记录来源/未测边界。测试进程与隧道均清理，原1252/8082健康、显存回2871MiB。

第二轮LFM增强已完成（见优化报告第二轮）：明确场景定义+enum3/3，显式身份边界改善unknown；长复制原auto+budget0两次分析泄露/截断，原生assistant关闭think续写后三次严格通过。ngram实际draft198/accepted162但多复制一段且仍冷读；cache512两次亦重复失败、6.15–6.38token/s，无采用收益。官方1.2B六条0.191–0.519s但场景仅1/3；现有记忆工具正确隔离更新/来源/用户，模型仍输出字符串null，确定性门禁拒绝为unknown。都是研究候选，未部署或替换LFM。测试进程/隧道已清理，共享1252/8082健康、显存回2871MiB。

第三轮代表集已完成（优化报告第三轮）：发现closed-think预填+JSON schema会400，必须分流；JSON任务不预填，普通文本/角色预填。代表8项均非空stop，但JSON语义3/5（分类1/3）；摘要/翻译/未知事实三项符合短夹具。真实6轮+fresh中最新偏好、未知书页、权限和新会话身份正确，但仍有“数学课”等扩写和口吻偏离，不等于长期角色通过。24B检索辅助JSON含真正null且来源校验通过；固定契约门禁8项离线验收通过，不计模型质量。进程4004/6976与隧道21696已清理，共享1252/8082健康、显存回2871MiB。无产品部署或默认改动。

## 当前选型与实测入口（2026-10-16）

用户确认：本地角色扮演和简单辅助任务主力为 **LFM2.5-24B-A2B-Q4_K_M**，不是Qwen3 4B。主工作模型仍由用户选择；本地模型不接管复杂代码、架构或工具执行。Astra仅用于复杂规划/统筹，Sol负责实施的分工不受此选型改变。

|层面|本轮现场事实|
|---|---|
|已选主力|LFM2.5-24B-A2B，8084，llama.cpp CUDA12.4，`--n-cpu-moe 99 -c 4096 --jinja --reasoning-budget 0`|
|开始时的运行状态|8084无服务；8082实际为Qwen3-4B-Thinking-2507 Q4_K_M、2048上下文；启动脚本和Ollama blob元数据交叉核实，不能仅按端口旧名称判断|
|本轮测试准备|复用原LFM参数临时启动PID5800，HTTP由503加载中变200；测试完成后核对PID/模型/端口停止本轮LFM进程，保留原服务；未改启动任务/原脚本/日用设置|
|日用Sumika|辅助总开关关闭，仍指向本机旧MiniCPM；“选了模型”不等于“客户端已接入并启用”|
|当前质量验收|2026-10-17短测完成：有校验的简单任务条件可用；角色长期一致性未通过，不建议直接无保护替代|

历史原始文件 `.sumika-next/laptop-model-bench/lfm25-24b*.json` 显示：早期角色测试有空正文、推理残留、未知事实编造；摘要中的“10/10”“5轮优秀”不能覆盖这些反例。`E:/SumikaBuild/p15-tasks.log`等只用于对应历史样本，不替代本轮实测。3.5～4秒只是此前短分类预热结果，不是全部任务的响应时间保证；“已经最优/无优化空间”没有穷举依据，应理解为此前试过的参数未改善。

复用已有资产：`evaluate_role_models.py`的多轮历史方法、`verify_local_model_tasks.py`的任务类别；原工具的256 token/仅Ollama协议/弱关键词判定不适合本轮严格验收，因此增加 `tools/evaluate_lan_daily.py`，不改产品推理实现。新工具串行SSE，保留原文、独立reasoning、可见首字/总耗时、finish_reason及严格JSON比较；自由文本和角色质量由人工逐条复核，非空不自动判通过。

复现命令：

```powershell
python -X utf8 -B tools/evaluate_lan_daily.py --endpoint http://192.168.31.227:8084/v1 --model LFM2.5-24B-A2B-Q4_K_M --out .sumika-next/laptop-model-bench/lfm-daily-20261016.json
```

证据：`.sumika-next/laptop-model-bench/node-20261016.json`、`lfm-daily-20261016.json`。Qwen旁证：`daily-20261016.json`、`daily-role-20261016.json`，因重复空正文提前停止，不能拿未执行项计分。关闭思考参数单项仍有763 completion tokens/25.4秒，不能假定`enable_thinking=false`对所有模型有效。没有测试ASR/TTS/视觉或真实安和昴完整卡，不外推这些能力。

### 2026-10-17 本轮实测结果

**结论：保留用户选定的LFM主力选型，但当前配置不能直接视为已胜任所有日常工作。简单文本任务有条件可用；长期角色扮演质量不达标；Sumika尚未接入该局域网主力。** 本轮仅测试现有部署，不改产品推理、日用模型选择或远端启动任务。未执行模型生成的工具调用。

|测试条件|实际结果|含义|
|---|---|---|
|原启动参数、标准OpenAI调用、不加模板参数和schema|完成2例，严格JSON 0/2；冷请求147.055秒，另一次54.346秒。首例把教学视频误判游戏并输出bash样式tool_call文本，第二例英文推理混入正文|当前标准客户端调用不能直接可靠使用；冷请求与预热速度分开|
|同一服务，显式`chat_template_kwargs.enable_thinking=false`，前6个结构化例加JSON Schema，后13例不加schema|19/19有完整非空正文，均stop；严格JSON语义5/6；总耗时中位5.409秒，范围1.497～14.586秒；可见首字中位2.473秒|有条件能用；schema仅限制字段/类型，没有强制答案值，也没有偷偷做文本正则提取|
|只关闭思考、不加schema，补测3例|严格JSON语义1/3；场景误判游戏，提取混入英文推理，注入例正确；0.995～35.470秒|不能把改善单归因于关闭思考；该参数不能保证全部任务无推理残留|

19例逐类复核：

- 场景/意图/提取/资料指令隔离：5/6正确，教学视频“游戏引擎开发入门”误判unknown；只关思考复测又误判game。不会强行兜底学习是安全退化，但仍是漏判。
- 简单内容任务6例：久留不肯定推断困惑、摘要、保留否定与次数的翻译、链式求导、列表推导解释、总计30分钟计划均完成；求导正确为`6(3x+2)`，列表结果`[2]`且不改原列表。翻译把“never retry”写成“永远不会自动重试”，作为普通翻译可读，若用来改写可执行策略仍需保留命令语气的严格校验。
- 角色7轮：能安慰、能承认不知道书页、拒绝谎称删除文件；但偏好更新后主动加绿茶，下一轮把这个自编内容当用户安排；新会话把角色“澄”说成用户名字；2轮输出`</think>`并重复正文；5/7超100字要求。角色质量不能以“非空”“不拒答”代替。

能力边界与后续实施建议：

1. 可以优先承担资料摘要、评论整理、短翻译、简单解释、候选标签等有人工或确定性复核的任务。模型只提出参考，不作用户意图、已执行操作或授权的真值。
2. 结构化任务接入前，现有OpenAI-compatible provider需要有界、明确配置的模板参数和schema支持。当前`CloudProvider.generate`没有透传这两项，`auxiliary._generate`在Cloud分支也未传schema；本轮优化调用是评测工具参数，**不代表产品已修**。还需完整JSON、枚举/分数、finish_reason、迟到与来源验证；失败unknown，不用正则捞JSON冒充通过。
3. 角色侧需要先解决答案/推理边界、严格用户事实来源、角色与用户身份隔离、自编事实不得回流成用户偏好；再用完整安和昴卡、偏好更新/反例、长对话复测。简单清理`</think>`只能修显示，不能修编造或记忆污染。
4. 质量验收通过后再安排唯一服务owner、自启恢复、单卡串行队列、健康状态和客户端显式配置。8084缺服务是部署连续性问题，不等于用户选择了Qwen；Qwen3.5替补与视觉节点本轮未复测。
5. 保留llama.cpp原配置。不重做已否决的Strata/ktransformers/flash-attention路线；先修调用契约和事实质量。既有优化失败不证明全局唯一最优。

证据与复现：`lfm-daily-20261016.json`（2例原调用）、`lfm-adapted-daily-20261017.json`（19例）、`lfm-thinking-off-only-20261017.json`（3例），均在`.sumika-next/laptop-model-bench/`。后两者混合条件明确分开；不把样本5/6或19条非空说成总体准确率。串行请求；使用简短合成中文资料及通用角色“澄”，没有发送用户完整角色卡或日常私有历史。完整安和昴风格、长上下文、并发/资源干扰、ASR/TTS、视觉、真实产品UI链均不在本轮通过范围。

收尾：项目CLI check、评测器语法检查、`git diff --check`通过，交接使用CLI handoff导出。临时LFM测试进程已停止，8084不可达、原8082仍在线已核实；不改变持久部署。`extensions/behavior/model_recommendation.py`中旧的“无思考问题、直出正文”描述尚未作为本轮产品代码修复，本节复测结果优先，不能拿推荐文案作质量证据。

下方为较早阶段记录，未选择默认/旧节点未部署等表述只描述当时状态；当前选型以本节和用户最新确认优先。


状态：接口首版已实现；两个 MiniCPM5 已完成真实短对话测试，模型质量与多设备运行时仍属部分验收。

已实现的独立边界：

- `extensions.models.ollama.OllamaProvider`：健康检查、模型列表、非流式对话和 usage 提取；禁用或异常时失败关闭。
- `extensions.models.device.DeviceRegistry`：显式设备注册、配对令牌哈希、撤销、能力列表和在线探测；不允许未加密公网 HTTP 端点。
- `extensions.roles.handoff`：项目索引、角色任务交接包和工作台提示构造；角色意见标为不可信，不产生授权。
- `extensions.models.usage.UsageStore`：estimated/reported/unknown 三态用量记录及会话/项目累计。
- `extensions.models.prompt.enhance`：保留原文的显式提示词增强，失败时可回到原文。

候选模型只记录来源和评测元数据，不随客户端下载或打包。官方 MiniCPM5-2B 作为稳定基线；第三方 abliterated 版本只作为用户主动选择的实验模型。Qwen3-8B-Heretic、OpenElla-NovelWriter-8B-V2、Neon Veil v2、Ministral-3-8B-Nymphaea-RP、Stheno v3.4 需在测试前核对固定版本、SHA-256、许可证和中文表现。

未实现或未验收：真实 Ollama 模型质量、旧笔记本/安卓节点、FreeToken、DSH token-meter/system-prompt 原生加载、完整 UI 接线、角色闲聊自动跳转工作台。上述边界不授予角色模型文件/终端/浏览器/桌面权限。

FreeToken 仅预留为 Linux x86_64 + NVIDIA 新架构上的 OpenAI-compatible MoE provider；不作为 GTX 1060 或安卓运行时。

## 当前模型评测

用户已明确授权下载候选模型。权重保存在源码之外；8B 下载放在 E 盘，下载回执记录固定 revision、LFS SHA-256 与许可证元数据。

`tools/evaluate_role_models.py` 保留原四项测试，并增加真实传递助手回复的多轮偏好更新、未知事实、越权请求及新会话隔离。`passed` 仅表示获得非空响应，不代表角色质量或工具安全验收通过。

结果与限制见 `local-model-comparison-evidence.json`。两种 MiniCPM5 各完成十次请求；都能使用更新后的偏好，但存在脱离角色或答非所问。尚未选择默认模型。该测试不等同于长期记忆接线、真实角色卡、长对话或游戏资源干扰测试。

现场显卡为 AMD Radeon RX 5700 XT，MiniCPM5 的 `ollama ps` 显示 100% GPU；没有 NVIDIA 不等于 CPU-only。Qwen 首次注册因日用 Ollama 在 C 盘进行兼容转换而空间不足；使用 E 盘模型存储的独立回环测试实例处理，不改日用路由。OpenElla 许可仍需核对。
