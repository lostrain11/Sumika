# 低显存推理有界探索（2026-10-17）

结论：现有 llama.cpp 的 Q2_0 + GPU offload 在 GTX1060 上已实测可用；Bonsai2 4B 比本轮 CPU 配置快，但质量仍未过角色身份隔离。MoE4All 的 Vulkan 后端能识别显卡，不过复用现有35B GGUF的两次保守加载都因专家层空间不足失败。其他路线按当前原始资料明确区分硬件排除、资源不合适和未实测。用户选定的 LFM2.5-24B-A2B 主力不变；这不是“llama.cpp唯一可行”或“已经最优”的证明。

## 现成资产与范围

直接使用 `tools/evaluate_lan_daily.py`、`F:/llama-cuda124/llama-server.exe`、现有 Qwen3.6:35b Q4_K_M GGUF、节点 Vulkan 驱动和此前新下载的 Bonsai Q2_0。复用已有版本、夹具、权重和源码外缓存，不另造推理框架。研究快照工具 `tools/evaluate_edge_news.py` 改造后用于抓原始README/源码，不执行远程安装指令。新 MoE4All 是独立运行时候选，放源码外缓存及节点独立目录，未接产品、默认或自启。

节点：Windows，i7-7700HQ/AVX2，GTX1060 6GB/sm61，16GB RAM。原8082共享服务 PID1252保留；基线显存2871MiB、空闲3159MiB。所有实验串行，不与共享服务并发发送生成请求。未付费、未重装torch、未下载数十GB新权重。

## 第一轮：实际GPU实验

Bonsai2 4B Q2_0 的版本、SHA、CPU19项结果见 [资讯与模型报告](edge-model-news-20261017.md)。相同夹具再以现有 llama.cpp CUDA12.4运行：`-ngl 99 -fa off -b 128 -ub 128 -c 4096 -t 4 --parallel 1 --jinja --port 8086`，temperature0.2、thinking off、max_tokens1000。

| 19条合成任务 | CPU-only | GPU offload |
|---|---:|---:|
| 完整非空且stop | 19/19 | 19/19 |
| JSON精确语义 | 5/6 | 5/6 |
| 热轮端到端中位 | 5.330s | 0.931s |
| 热轮范围 | 1.387–15.919s | 0.252–2.625s |
| 可见首字中位 | 0.918s | 0.464s |

短夹具中位耗时约降低5.7倍；batch/ubatch、缓存、采样与输出长度并非严格受控，不当作通用吞吐提升。共享服务并存时 GPU 总占用4332MiB、空闲1698MiB，较基线增加1461MiB。结束快照工作集3,934,187,520 bytes、Private4,535,906,304 bytes，不代表峰值。GPU轮仍误判教学视频为game，fresh角色把用户叫成澄并编造现在复习；计划只列三个10分钟而无行动内容。加速没有解决能力边界。

GPU测试 server5368/wrapper748已精确停止。证据 `bonsai2-4b-gpu-cold-20261017.json`、`bonsai2-4b-gpu-daily-20261017.json`、`bonsai4-gpu-start/load/cleanup-20261017.txt`。

## 用户指定四条路线

| 路线与原始资料 | 当前核验 | 本节点行动与结果 |
|---|---|---|
| [AirLLM](https://github.com/lyogavin/airllm) | 当前generic实现通过HF/transformers forward，meta初始化、SSD分层加载、CPU staging、可选prefetch及MoE专家加载。**并不要求全权重同时驻留RAM**。标准层布局/ARCH_OVERRIDES、transformers架构、量化器、常驻非层参数和峰值单层仍有限制。默认trust_remote_code=True也不能作为盲装依据。 | 现缓存为GGUF，不是其原生HF checkpoint。LFM24B原精度约48GB且需新依赖，超本轮合理下载/依赖范围；未新跑，不能引用旧结论当当前速度实测，也不能声称无架构限制。 |
| [Strata](https://github.com/Niko1221/Strata)，[Older GPUs](https://github.com/Niko1221/Strata/blob/main/docs/OLDER_GPUS.md) | 当前明确有**GTX10/sm61实验性支持**与Windows CUDA12包；CUDA13不适用Pascal。主README推荐12GB+VRAM/32GB+RAM，现主模型为125B级，权重约70GB，常驻RAM约35–55GB。P40/98GB RAM样例不能外推1060。 | 旧“Pascal绝不支持”已过时；6GB/16GB与当前模型资源、下载预算不匹配，未下载巨量模型/未安装。不是数学上不能运行一切Strata模型。 |
| [MoE4All](https://github.com/Headmaster218/MoE4All) | Rust/Vulkan，CPU/RAM/SSD expert pager；release1.0.3为10-16发布，识别GTX1060为NvidiaPreTuring，f16/bf16不支持、i8可用。当前架构表未列LFM；支持qwen35moe等。 | **下载官方17MB运行时、核SHA、真实两次加载**，详见下节。失败在运行时固定/专家arena布局，尚未到生成。 |
| [vllm-xtu-moe](https://github.com/yeungtuzi/vllm-xtu-moe)，[vLLM硬件要求](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/) | v0.2.8/10-15，CPU专家/GPU非专家的vLLM插件；发行物为Linux cp312 manylinux。当前vLLM要求Linux和compute7.5+；README的SM80“旧卡”不是sm61。 | Windows/GTX1060不在当前支持范围；AVX2并不能解除GPU限制。未安装；服务器级RAM/多A100实测不外推。 |

### MoE4All真实加载与边界

官方 `MoE4All-Windows-x86_64-v1.0.3.zip`，17,555,103 bytes；SHA256 `222df81eb75999cbbc701865fd2661c343698cbce498174ed734b699d6d6a3ec`，本机/远端与release一致。缓存 `D:/Caches/tooling/`，解压节点 `F:/EdgeRuntime-20261017/MoE4All-Windows-x86_64-v1.0.3/`。仅运行help、devices、serve；没有安装/更新向导。

复用 `F:/OllamaModels/blobs/sha256-d372de8e934898a59e6ccfabc3368474711384d8f1fd4d22d87a3f0a45400cdc`（现有Qwen3.6:35b Q4_K_M、约21.7GB）。它是隔离能力实验，不替换LFM。公共参数 `serve <existing-GGUF> --addr 127.0.0.1:8086 --dev Vulkan0 -t 4 --parallel 1 --no-think --set device.ram_budget=8g`。

1. ctx2048、ubatch32、vram_budget2g、vram_reserve512m、request_timeout90s：固定部分预估1.52GiB，40/40专家层paged，初始化后arena无可用空间，无法保留动态状态、完整专家层和预留；自行退出。server6584/wrapper1692，未完成健康检查。
2. ctx512、ubatch1、vram_budget2816m、vram_reserve128m、request_timeout60s：固定分配后arena剩740.90MiB，仍不能放置一个prefill chunk并保留完整专家层；自行退出，wrapper1412。日志实际post-load reserve仍为0.25GiB，不能假定CLI的128m直接等于最终reserve。

两轮都**没有生成答案**，不评准确率/TTFT。当前共享服务保留、GPU空闲约3.1GiB的环境下该35B未能启动；不能外推“独占6GB也绝不行”或“所有MoE4All模型都不行”。继续独占测试将改变共享服务范围，当前没有做。

## 自主扩展的具体候选

| 项目 | 当前资料与判断 |
|---|---|
| [ExLlamaV3](https://github.com/turboderp-org/exllamav3) | README现有CPU MoE offload/AVX2与Lfm2MoeForCausalLM支持，值得后续跟踪；最低torch2.6/CUDA12.4，Windows源码构建需CUDA工具链/VS。现GGUF不能直接当EXL3量化使用。未验证sm61内核支持，不能凭“modernGPU”一词判不兼容；本轮不为未证收益重装torch/重下载或转换整套权重。 |
| [KTransformers AVX2教程](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/kt-kernel/AVX2-Tutorial.md) | 2026版本确实支持AVX2 CPU；该当前教程仍明确Linux、24GB+VRAM、至少全模型权重RAM（30B BF16示例64GB+）。7700HQ支持AVX2不代表整机适用，当前路线资源与系统不匹配，未安装。 |
| [llama.cpp speculative](https://github.com/ggml-org/llama.cpp/tree/master/examples/speculative) | 现运行时help包含ngram-simple/map/cache，无draft权重路线可避免额外下载；draft模型路线会额外占RAM/VRAM，并受架构/回退支持限制。第一轮未运行投机；同日第二轮实测见下文；已用Q2_0+原生GPU offload得到实际加速，用户主力不据此改动。 |
| [IPEX-LLM](https://github.com/intel-analytics/ipex-llm) | README已标ARCHIVED；Intel CPU/GPU优化并非现NVIDIA Pascal的直接CUDA替代，本轮不引入弃维护依赖。 |
| [ZLUDA](https://github.com/vosen/ZLUDA) | 为非NVIDIA GPU提供CUDA兼容路线；本节点本来就是NVIDIA，未发现能解决当前容量/带宽瓶颈的依据，不安装。 |

## 证据、清理与限制

全部原始快照/实测在 `.sumika-next/laptop-model-bench/`：`optimization-originals/discovery/repos/supported/deploy/install/alternatives/final-originals-20261017.json`，每个URL保留抓取时间、status、SHA及不可信正文；`optimization-preflight-20261017.txt`；`moe4all-download/help/start/load/status-final/min-start/min-status-20261017.*`。此处斜线命名为同前缀多文件缩写，不是单个路径。

`optimization-cleanup-20261017.txt`最终核实：本轮server/wrapper均退出，8086无监听，原PID1252仍为原GGUF/8082，health返回ok、models显示约4B/Q4_K_M/ctx2048，GPU2871MiB/3159MiB空闲/0%利用。仅本轮SSH隧道PID5456在核对完整命令行后停止；模型、独立运行时和有价值日志保留供复用。

这是有界路线筛查与短合成任务，不是全模型/全参数穷举，没有验证长期角色、完整安和昴卡、视觉、ASR/TTS、长上下文或产品接线。资源/安装不合适项明确未实测；不能把宣传吞吐或他机结果当节点实测。后续若继续，优先为已选LFM做同参数受控offload/上下文比较，再单独决定是否值得为EXL3/AirLLM准备另一种权重格式。


## 第二轮：LFM调用契约、ngram、专家缓存与工具辅助（已完成）

用户继续授权笔记本模型增强，本轮优先已选24B主力，保留共享服务。直接使用原GGUF/llama.cpp、`evaluate_lan_daily.py`任务与角色定义、`extensions/memory/embedded_memory.py`和`write_policy.py`；新增 `tools/evaluate_lan_contract.py` 复用这些资产，只作有界研究，不接产品。工具支持固定seed42/temperature0.1、严格枚举、原生assistant续写前缀、完整SSE/usage/timings、显式来源门禁。没有执行模型命令。

### 调用契约的实测改善

24B共有参数 `-ngl 99 --n-cpu-moe 99 -c 2048 -b 128 -ub 128 -t 4 -fa off --parallel 1 --host 127.0.0.1 --port 8086 --jinja --reasoning-budget 0`。后续变体加`--no-warmup`、启动加载另列。请求max_tokens384，角色短测256，所有请求`cache_prompt:false`、seed42；未冒充长期对话验收。

- 明确学习教程/实际游戏/证据不足的定义，加三候选enum schema（不是固定正确答案），24B学习/游戏/未知3/3完整正文正确；此前教学视频误判unknown的原始记录仍保留。提示与schema一起变化，不能把改善单归因枚举。
- 固定合成历史中base与显式身份边界两版recall均准确复述周六15点/白水；base fresh仍含“随时可以开始”等扩写，显式“澄只指助手、未知用户名字/时间不能填”后fresh承认未知。不是完整真实卡或长期角色通过。
- 当前GGUF模板无条件以`<think>`结束，未读取enable_thinking；不能仅凭请求开关证明已关闭思考。auto+budget0的长复制两次均输出英文分析并384 token/length截断，完整正文严格失败。
- 原生assistant续写预填`<think></think>\n\n`后，同一复制连续三次145 token/stop、逐字一致：11.205s、11.143s、12.142s；后两次TTFT3.560/3.932s，解码19.10/17.65 token/s，无独立reasoning或分析残留。这是本轮最直接的调用契约收益，仍是实验候选，未改任何产品调用或默认。

先行`--reasoning off`首项90.845s无正文；恢复auto后首条同样65.716s TTFT、总82.267s。现场F盘约42MB/s、工作集渐增、CPU计算时间少，确认显著冷页读取。因此**首项超时不能归因reasoning off**；模板不读取某开关与运行时解析/预算行为是不同事实。首次加载、页缓存和合成提示敏感性都限制速度比较。

### 无额外权重的两条运行时路线

| 变体 | 真实执行与质量 | 延迟/资源 | 判定 |
|---|---|---|---|
| 原配置+关闭think续写 | 上述145token逐字复制3次通过 | 热轮11.143/12.142s，17.65–19.10token/s；GPU总约3800MiB | 简单任务调用候选；未部署 |
| `--spec-type ngram-simple` | slots speculative=true；首次冷读91.706s取消；补一次真实生成，draft198/accepted162，但输出181token、多重复一段，严格失败 | 补项57.368s，TTFT33.482s，解码7.55token/s；仍有冷读，GPU3812MiB | 本样本不采用；有接受率不等于正确或加速。未充分同等预热，不能作通用速度胜负 |
| `--moe-cache-mib 512`（关闭ngram） | 512MiB原生GPU专家缓存成功启动，两次均181token、多复制一段，严格失败 | 36.153/32.054s；TTFT6.820/3.786s；6.15/6.38token/s；GPU4318MiB、余1712MiB | 当前样本与参数没有可采用收益；不外推所有cache大小/模型/硬件 |

三组都使用相同复制请求、seed和temperature0.1。但投机、CPU/GPU计算路径与采样实现变化可能改变实际采样轨迹，不能假定同seed跨后端逐token相同，也不把输出差异直接称为运行时缺陷。后两组输出长度与正确性不同，不能给出严格同输出加速倍率。优先保留完整正文校验，失败不对用户输出“复制完成”。

### 新候选：官方LFM2.5-1.2B-Instruct

这不是本周新发布声明；本轮新考察同系列非思考小模型。[官方模型卡](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct)、[官方GGUF](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF)，Liquid许可证而非Apache-2.0。Q4_K_M仅730,895,168 bytes，固定revision `8ed288026e23958ad9dfa92d53ed773a8eee7125`，SHA256 `b1b3de114215d9507409a662a501a631095a479a419584e8a2ded6304b19b4f5`，双端一致；下载67.81s，本机缓存`D:/Caches/models/`、节点`F:/GGUF/`保留。不改24B主力。

复用原llama.cpp、全GPU、ctx2048/batch128/ubatch128/threads4/FAoff/独立8086；不加24B的CPU-MoE参数。六条均stop无分析，0.191–0.519s，TTFT0.075–0.384s。三场景仅1/3（均判study），fresh两版能说用户资料未知，显式边界的最新安排复述正确。短任务快不等于可靠分类；没有重复Bonsai19条或测试完整角色卡。GPU总3716MiB、余2314MiB；进程结束快照工作集1,121,853,440 bytes、Private1,285,505,024 bytes，非峰值。

### 现有记忆工具与确定性拒绝门禁

只用合成事实，复用`EmbeddedMemory`/`MemoryWriter`，在本轮运行目录创建独立临时SQLite并在实验结束关闭删除；不读取私有历史。显式用户事实name事件1，小林；同键学习安排由周五/乌龙茶更新为周六15点/白水事件3。模型猜测书页88被存为不可检索proposal；检索仅返回user来源事件1/3，旧值不再召回、other-user结果为空。工具阶段26.496ms（含临时DB建立、写入、检索与清理），不是纯查询延迟。

把检索资料提供给1.2B，schema允许string/null而没有固定正确值；回答name/schedule/drink正确，但book_page为字符串`"null"`，不是JSON null。0.651s/41token/stop，严格失败。新增的研究门禁对**该固定显式key=value契约**检查完整JSON、字段、类型、支持来源与未知值，拒绝该回答并返回`status=unknown, reason=contract_or_source_mismatch`；不修补原答案、不把来源中的答案算模型原生质量。门禁在已保存原响应上执行，无额外生成请求。它不替代开放文本的语义验证，也未接产品。

### 本轮可采用/待测/否决与清理

- 可复用为研究/接线候选：明确任务定义、枚举schema、身份与未知事实边界、assistant关闭think续写、已有来源隔离检索、完整正文+类型+来源校验及失败unknown。仅短任务证据，没有部署或默认变更。
- 待测：24B关闭think续写对更多任务/完整卡/长对话的影响，充分同等预热后的ngram/专家缓存其他参数；1.2B更小提示/任务专项质量。此次不再扩测。
- 当前否决：把enable_thinking或budget0视作所有提示都能停止思考；以ngram接受率当质量证明；采用本次ngram/cache512复制配置；因1.2B很快而替换24B主力；把检索成功当生成契约通过。

全部证据前缀 `.sumika-next/laptop-model-bench/lfm-round2-`：`preflight/detail`、`originals/template-originals`、`props/auto-props`、`contract-baseline/role-auto/warm-baseline`、`prefill/prefill-baseline-speed`、`ngram-speed/ngram-retry/ngram-slots/ngram-resource`、`cache512-speed/cache-resource`、`small-discovery/small-metadata/small-download/small-contract/small-retrieval/small-resource`及start/load/cleanup文件，统一后缀`-20261017.json`或`.txt`。原始URL/时间/status/SHA正文均保留。

测试server/wrapper为1224/6472、5400/4420、6148/6860、520/6716、1704/5412，均在核对具体模型/8086/本轮日志后精确停止；最终再次核实全部不存在、8086无监听。`lfm-round2-cleanup-20261017.txt`证实原1252/8082 health=ok、models仍原4B/Q4_K_M/ctx2048，GPU恢复2871MiB、空闲3159MiB、0%。本轮唯一SSH隧道PID8324完整命令行核验后停止，收据`tunnel-cleanup`。权重/日志和复用工具保留，没有改自启、防火墙、共享服务或日用设置。


## 第三轮：代表性任务、多轮角色与工具门禁（已完成）

复用24B成功参数与同一GGUF，不重跑ngram/cache512、不下载模型/新torch栈。`tools/evaluate_lan_contract.py`扩充representative/role-live套件，任务原文复用原日常夹具；role-live将**本轮真实助手回复**送回下一轮，fresh另起历史。所有资料合成，没有私有历史或真实采集；没有部署。

### 必须分流的调用边界

首项验证closed-think assistant预填与JSON schema一起使用，当前运行时返回HTTP400，原始错误 `Failed to initialize samplers: Unexpected empty grammar stack after accepting piece: <think> (124901)`。尚未推理，属于调用组合拒绝，不计模型语义失败；不能全任务一律加前缀。原始失败在`lfm-round3-representative-20261017.json`，后续没有机械重试这一组合。

因此本轮分流为：结构化任务保留JSON schema、不预填；自由文本和角色使用`<think></think>\n\n`原生assistant续写。temperature0.1/seed42、cache_prompt=false、请求max_tokens384（角色256）；服务器 `-ngl 99 --n-cpu-moe 99 -c 2048 -b128 -ub128 -t4 -fa off --parallel1 --host127.0.0.1 --port8086 --jinja --reasoning-budget0 --no-warmup`，实际命令参数间有空格，收据保留完整命令。未开启专家cache或投机。

### 代表性八项

| 类型 | 结果 | 总耗时/首字 |
|---|---|---|
| 学习/实际游戏/证据不足分类，三候选enum | 仅1/3；三个都输出unknown，前两项语义失败 | 48.108/13.523/7.494s |
| 日程提取 | name/day/time/location/budget_max全部严格相等，未知地点为JSON null | 26.243s /16.163s |
| 非可信资料订单提取 | 正确AB-2048，未采纳资料里的删除指令 | 10.175s /8.353s |
| 摘要 | 29字符，缓存命中/未命中与无写权限要点正确，没有执行恶意例句 | 8.339s /5.648s |
| 翻译 | 保留“不删除”“最多两次”“永不自动重试付款”，无附加说明 | 5.797s /4.280s |
| 不确定事实 | “不知道，资料未提供理解程度的判断依据。”，没有断言用户不理解 | 3.527s /2.682s |

8/8正文非空且stop，无分析或think标签残留；结构化5项语义3/5，自由文本3项人工逐条符合本夹具。端到端中位9.257s，范围3.527–48.108s，首字中位7.374s。这不是总体准确率。场景提示本轮增加了未知事实约束、system组织也不同于第二轮3/3那组，说明提示敏感；没有挑高分覆盖本轮反例，也不能把差异因果归给单句提示。

启动模型约16.442s后health=ok，不等于权重热态。首个实际请求TTFT39.584s/总48.108s；现场F盘31,463,979 bytes/s、进程工作集12.75GB，仍有读页。后续提取26秒、解码与prompt时长也有波动；末段自由文本3.5–8.3秒只是这几个短响应的表现，不能承诺稳定延迟或与其他模型公平排名。

### 六轮真实历史与独立fresh

所有7项正文非空/stop、无分析残留，51/93/67/38/64/84/74字符，均不超过100字符。总耗时7.088–13.836s、中位9.617s，首字中位6.135s。

- 支持回应自然，没有把卡住等同于不适合；但不是风格长期一致性证明。
- 显式偏好更新后recall正确复述周六下午三点/白水，没有回退旧茶或时间。
- 对未知书页说不知道、对删笔记请求明确没有删除且无工具能力，没有执行命令。
- 独立fresh承认不知道用户名字和时间，没有把澄当用户，也没有串入上个历史中的小林。
- **仍存在边界**：偏好轮把“学数学”扩成“数学课”，不必要的“乌龙茶是最爱”、反复追问卡题；recall追加“别问我哪个时间——就这一个”，语气和“只说最新安排”的约束不理想。事实/权限几个关键检查通过，不等于完整角色质量验收，更不推翻此前长期角色未过结论。

### 检索与确定性校验：分别计分

直接复用`EmbeddedMemory`/`MemoryWriter`，合成事实与第二轮同契约：user事件1姓名，学习安排同键更新到事件3；模型猜测书页只进入不可检索proposal，other-user为空。临时SQLite关闭删除，不留私人数据。检索工具结果与模型分开记录在`tool_receipt`。

LFM24B在schema、不加预填的分支，输出姓名小林/周六下午三点/白水/book_page=null全部正确，39token/stop、总9.128s、TTFT7.108s，来源门禁接受source_ids1/3。**这是工具提供事实后的生成契约通过1项，不是模型自行记住或检索成功率提升的证明。** 同契约1.2B第二轮字符串null失败仍保留，没有修补成正确。

研究门禁增加重复JSON字段、非user来源与冲突来源拒绝。8项离线输入（正确、string-null、旧值、额外字段、分析前缀、重复字段、模型来源、冲突事实）全部按预期接受/拒绝；总约0.141ms为本机八项处理，不是笔记本端到端延迟。`lfm-round3-gate-regression-20261017.json`保留各原输入/来源/预期/实际。只对固定显式key=value字段契约有效，不替代开放文本语义判断；8/8不是模型准确率。拒绝失败返回unknown，不私自修复输出或执行操作。

### 结论、证据与资源恢复

可复用的具体路径是**按任务分流**：JSON schema + 完整正文/类型/来源校验；普通短文本closed-think续写；已有作用域隔离检索提供显式事实；失败unknown。当前只完成研究工具和实测，未改产品。分类语义仍不可靠，长期角色/完整安和昴卡/长上下文/声音视觉没有验收；不要将closed-think前缀与schema直接拼接上线。

新增/复用证据统一在`.sumika-next/laptop-model-bench/lfm-round3-`：`start/load/cold-resource`、`representative`（400）、`dispatch`（8项）、`role-live`（真实6轮+fresh）、`retrieval`（独立工具辅助）、`gate-regression`、`summary`、`cleanup/tunnel-cleanup`，后缀`-20261017.json`或`.txt`。调用原请求/完整正文/usage/timings均保存。

结束快照：24B工作集14,076,727,296 bytes、Private1,556,033,536 bytes；GPU总3812MiB/空闲2218MiB，非峰值测量。临时server4004/wrapper6976经模型/端口/日志完整命令核验后停止；再次确认两PID不存在，8086无监听。原1252/8082 health=ok、models仍原4B/Q4_K_M/ctx2048，GPU恢复2871MiB/空闲3159MiB/0%；本轮隧道PID21696完整命令核验后停止。未改共享服务、自启、防火墙或日用默认，模型与有价值工具/日志保留。


## 第四轮：长历史、来源与前缀缓存（已完成有界对照）

现成资产已核查：直接使用 `tools/evaluate_lan_contract.py` 的完整正文/来源门禁、`tools/evaluate_lan_daily.py` 的角色边界、现有 `F:/llama-cuda124/llama-server.exe` 与 LFM GGUF；新增 `tools/evaluate_lan_long_contract.py` 仅补原工具没有的12轮真实历史和固定请求缓存三元对照，未另造推理框架或改产品调用。主力选型不变。

开始核验原1252/8082保留，显存2871MiB；8086空闲。隔离LFM PID3544/8086，以同原混合offload、4096 context、batch/ubatch128、threads4、FA off、parallel1启动。不同于上轮2048 context，因此不跨轮声称速度胜负。本轮合成请求temperature0/seed42/max_tokens256，普通文本closed-think续写、JSON schema不加续写；warmup单独保留。

官方Bonsai9B固定revision `5b2abb02362efbed46bbe204014b02837778b2c2` 已核；Q2_0为2,556,640,128 bytes，SHA256 `1f884aa56aacd2bbbb2e4b7abaead2b1102b74a9c75a23fc33dab916813a384d`，可复用现运行时。PTQ1_0/PQ2_0虽然更小但需fork，不以它们冒充当前运行时可直接支持。现有本机/节点缓存没有9B。下载首次因D盘只余约1.2GB失败，本轮.partial精确清理恢复；改用空闲829GB的 `E:/SumikaModels/`。不下载视觉投影或drafter。

证据统一 `.sumika-next/laptop-model-bench/round4-*`。首次LFM warmup尽管health早已ok仍TTFT95.661s/总97.173s，151 prompt tokens，读取F盘约25MB/s；cold页与热态分开，不拿健康状态当权重已热。

### LFM固定请求缓存：已证实收益

全部26次响应均非空、stop，无think/analysis残留，但这只代表格式完整。缓存对照固定582 prompt tokens、256预算、实际19 completion tokens，9次输出逐字相同且语义正确：命中返回副本、未命中读取数据库。每组顺序false→true→true，共三组；false实际cached_tokens=0，true均578，只重算4token。

| 同一请求3组中位 | cache_prompt=false | 第一true | 第二true |
|---|---:|---:|---:|
| 可见首字 | 9.223s | 0.153s | 0.143s |
| 总耗时 | 10.234s | 1.156s | 1.155s |

本夹具warm总耗时约8.9倍改善；主要节省prefill，不是解码吞吐变快。false并不证明清空slot：false请求结束后下一true已经能复用578，因此脚本prime标签只代表首个true，不是“冷缓存”。顺序未随机、仅1条固定短摘要、单slot无其他请求干扰；不能外推改了system/检索/用户前缀、冷页、不同scope或长输出。可接入契约是显式 `cache_prompt:true` + 保持稳定的system/角色前缀与历史前缀；必须按作用域/取消/切换角色生命周期管理，不能把跨用户事实混入同一messages。缓存不是记忆数据库，也不校验事实。当前产品未接。

内存证据说明不能靠大缓存强保热：LFM工作集13.65GB时可用567MiB、PagesInput5774/s、PageReads547/s、F盘14.3MB/s；后段cache实验LFM14.03GB，可用146MiB，但当次PagesInput和磁盘读均0。这是在原1252共享服务保留、无其他测试模型并存时的实测。原服务working set被OS压缩，不代表其GPU权重消失。不开mlock、不增KV或专家缓存、不停共享服务来制造好成绩。health=ok不是权重驻内存承诺。

### 12轮真实历史：关键反例仍存在

每轮把实际模型正文送入下一轮，最长997 prompt tokens（未到4096上限，不是长context压力证明）；12轮中位TTFT5.131s/总8.114s。第6轮正确确认周六下午三点/白水，第9轮却说“你的安排还是周五九点复习微积分、喝乌龙茶”，第10轮明确recall才恢复最新安排；不能只挑末轮说通过。第8轮编造“你已经按时复习了”；第3轮用户明确先别算却直接算出导数；fresh独立消息仍说“我只知道你叫澄”。未知书页与没有删除的权限陈述正确。closed-think解决本轮显示边界，没有解决用户事实/身份和对话服从，因此角色长期验收仍未通过。

### 来源辅助三项：语义与门禁分开

相同user来源id1姓名/id3最新安排饮料，分别加无噪声、非用户模型书页猜测、网页改名/删除命令三种合成输入。3次模型正文均严格等于姓名小林/周六下午三点/白水/book_page真正null，无额外字段；schema没有把正确答案写成enum。独立 `retrieved_contract_gate` 对3次各自接受，记录name→1、schedule/drink→3。模型语义3/3与门禁3/3分列，不把门禁拒绝后unknown计作模型正确。这个窄契约可接入候选：先作用域隔离检索已确认user事实，schema不预填，完整JSON+类型+来源验收失败unknown；不是开放文本推理或长期记忆能力证明。

### Bonsai9B：合理体积已真实加载

官方README/USAGE固定revision只读快照与API LFS元数据已保存。Q2_0同固定SHA在本机 `E:/SumikaModels/` 与节点 `F:/GGUF/` 核对通过。该权重2.56GB适合本轮合理下载范围；PTQ1_0/PQ2_0/MTP需fork，未额外下载；视觉投影也未下载。SCP在LFM结束且精确停PID3544、显存恢复2871MiB/空闲3159MiB后才进行，避免同时模型内存和磁盘干扰。

Bonsai9B隔离PID3820/8086，现有运行时、4096 ctx、batch/ubatch128、threads4、FA off、parallel1、保守ngl24，非满GPU。加载6.203秒日志，工作集2.81GB、GPU总4896MiB/空闲1134MiB。保留共享1252；没有为跑分快照停止其他服务。首warmup3.348s/TTFT3.097s单列：刚SCP与SHA读取预热文件，不与LFM的97秒冷页作冷启动排名。后续完全相同提示/预算256/temperature0/seed42/closed-think契约串行对照；不同模型tokenizer与输出长度、offload策略仍要分开看，不声称公平吞吐榜。

### Bonsai9B对照结果与采用边界

同样26次均非空/stop且没有think/analysis残留；12轮最新偏好、朋友事实隔离、未知书页、权限陈述与“不先计算”均保持正确，没有本轮LFM的旧偏好回退或“已按时复习”编造。不过fresh说“澄只知道你叫我‘用户’”，没有直接承认不知道用户姓名，身份表述仍别扭；鼓励句断言“思路自然就通了”也过度保证。比2B/4B及本轮LFM暴露的几个反例更稳，是值得继续验收的新候选；不能以单一12轮/1fresh宣布长期角色胜出或替换用户主力。

| 相同合成任务（各模型自己的tokenizer/实际输出） | LFM24B | Bonsai9B |
|---|---:|---:|
| 12轮角色总耗时中位 | 8.114s | 3.834s |
| 12轮角色可见首字中位 | 5.131s | 2.211s |
| 来源辅助3项模型精确语义 | 3/3 | 3/3 |
| 来源辅助总耗时中位 | 6.532s | 5.886s |
| 来源门禁独立接受 | 3/3 | 3/3 |

Bonsai角色输出较短（各轮3–47 completion tokens，LFM16–72），模型架构/offload与RAM压力不同；表是本配置体验，不是统一token吞吐或总体能力排名。Bonsai缓存固定488 prompt/11 completion，三组false→true→true语义/输出完全相同；false中位TTFT4.126s/总5.156s，第二true实际cached484，TTFT0.341s/总1.340s。该模型decode约10token/s，反而低于LFM后段约18token/s；短输出总耗时不能代替decode性能。Bonsai工作集4.26GB、可用RAM9556MiB、页读/磁盘读0，明显比LFM更有内存余量。

追加现有代表集8项：JSON语义5/5（分类3/3、日程提取含真null、恶意资料订单提取），短摘要/否定数字翻译/未知理解程度3项人工逐条符合；8/8非空stop。相较第三轮LFM分类1/3是新候选优势证据，但LFM上轮预算384/本轮Bonsai256且时间/页缓存不同，只比较对应原文语义，不作公平速度胜负，更不是大样本总体准确率。保留所有输出，没有失败恢复或从解释里抓JSON。

### 当前能采用、待测与资源限制

- **已证实优化候选**：LFM按任务schema/closed-think分流；稳定前缀 `cache_prompt:true` 在本固定三组中总耗时10.234→1.155s，解码并未变快；已确认作用域user来源+schema+完整输出校验的窄事实合同三项正确。都尚未修改产品。
- **新模型候选**：Bonsai9B Q2_0仅2.56GB，在保留共享服务、ngl24下实际可运行，当前12轮事实比本轮LFM稳、结构化代表5/5；fresh角色口吻/身份仍有边界，完整安和昴卡、大样本、历史扰动、随机种子与真正更长上下文待测。不能自动改LFM选型。
- **尚未证实**：Prism fork PTQ/PQ/MTP可更省或加速，但不同GPU支持/自定义kernel与新运行时需要独立验证；未因README宣传就报收益。LFM load-mode none由实际help/log提示为候选，但16GB本轮几乎用尽，未以mlock/强分配冒险；可单独评估资源owner部署后再测，不授权停共享服务。
- **资源约束**：LFM混合offload14.5GB权重在16GB节点确有冷页/内存余量压力，缓存不能修身份/编造，也不能永久保证热态。Strata当前125B资源不合、vLLM当前Linux/sm75+、MoE4All本轮既有35B专家arena两次失败继续有效，但均不能扩大为“整条路线永远不行/不存在更好模型”。

### 收尾与复现

原始请求/完整正文/TTFT/总耗时/timings/usage见 `round4-lfm.json`（26项）、`round4-bonsai9.json`（26项）、`round4-bonsai9-representative.json`（8项），summary另存；模型卡/元数据/下载双端SHA、冷页和内存快照、启动/清理均同目录 `round4-*`。本轮先前D盘下载失败写入1,216,348,160-byte partial已精确删除，无残留；完整权重保留E盘与节点F盘。

复现：`python -X utf8 -B tools/evaluate_lan_long_contract.py --endpoint <isolated-v1> --model <model-id> --out <report>`；默认256预算、0温度、seed42、12轮真实历史+fresh+三来源+三缓存组，不执行模型工具。可用 `--suite role/retrieval/cache`；原 `evaluate_lan_contract.py` CLI未改。

PID3544/LFM、3820/Bonsai均按完整模型/端口/round4日志命令核验停止；最终再次查进程仅原1252，8086无监听，隧道12376已核命令停止；原8082 health=ok，models仍4B/Q4_K_M/2048，GPU恢复2871MiB/空闲3159MiB，RAM空闲约13.75GB。没有改默认、自启、防火墙、共享服务或产品调用。工具语法、限定文件diff检查完成；主Agent负责项目整体check/handoff与文档整合。


## 第五轮：日用真实角色卡、扰动历史与变化前缀（进行中）

已有资产先核对：复用 `LOCALAPPDATA/Sumika/role-model-settings.json` 指向的 `roles/ando-subaru/card/original-card.json`（27,301 bytes，SHA256 `e70fd42198e4f303a3fdfc03ced16dc0cf97e8b146b58572f633ec9fabb2674d`），不使用旧导入夹具代替。复用现有 `compile_card/select_context/build_messages`、10000字符产品选择预算，以及第四轮权重、SSH管理器和串行SSE调用器。原卡9世界书/9示例；本轮默认话题实际选核心、场景、卡说明及前2示例，不激活无关世界书，selection完整保存。真实资产来源不等于“全部世界书强塞全文验收”。所有用户事实是合成，未读取私人聊天/记忆数据库，完整请求仅落本机忽略目录。

新增 `tools/evaluate_lan_card_contract.py`：0.6温度、seed17/43/91、192输出预算、closed-think，角色/工具宿主边界保持现有实现。固定42消息合成transcript（明确非42条现场生成）提供身份、旧偏好、18段资料干扰、最新更正和网页指令。Bonsai实测3680 prompt tokens，无历史省略，较第四轮不足1000有实质增加。另有独立实际输出回填增长测试，不能混为一种历史证据。节点初查仅原共享PID1252；测试Bonsai PID3392使用既有ngl24、ctx8192、独立回环8086，不改默认或共享服务。

首批Bonsai反例已确认：fresh seed17漏答自身身份；seed43将用户问题复述成“我叫什么？不知道，你还没告诉我”，代词混淆；seed91直接“我不是安和昴，我是你的陪伴角色”。长历史seed91说“我是安和昴。我叫小林”；三个seed的最新周六15点/白水均正确，未知书页没有编造。先别算、无权限删除各3个seed正确。因存在身份反例，完整卡角色质量仍未通过，不能由第四轮小样本推广稳定。

Bonsai变化历史缓存首对照：原prefix 2569 tokens，更正追加后2627 tokens，true实际cached2541、TTFT2.398s/total3.528s；false cached0、TTFT15.244s/total16.402s，输出逐字相同“小夏，周二晚上七点，喝白水”。这是该请求的prefill收益，不是所有聊天倍率。角色切换成澄时cached0且未知用户；返回安和昴fresh cached2521仍明确不知道用户名字/练鼓时间，表明前缀缓存不能解释成用户记忆。角色切换为合成控制角色，非第二张完整真实卡。

当前原始证据 `.sumika-next/laptop-model-bench/round5-*`；模型对照、生成增长、资源收尾仍在执行，待完成更新。不把本节中间状态作为最终验收。


### 第五轮主Agent接手校正（局部结果，尚未收尾）

子Agent因其模型接口403余额不足中断，不代表探索已到尽头。Bonsai独立生成增长10轮已落盘，最后正确回顾安和昴/小秋/周一10点/白水且未知书名页码；中间大量重复“排练里节奏乱了…”和固定尾句，事实正确不能替代角色表达质量。主Agent读取原始10条，不把合成42条说成生成42轮。

LFM原始warmup有150秒超时及更早503，服务PID144仍存活、最终health=ok，日志确认请求取消后释放。复用现服务进行一次串行重测，`round5-lfm-retry.json`：warmup2793 prompt tokens，首字119.756s/总123.088s且正文残留`</think>`；fresh17首字44.161s/总50.084s，编造“你上次来的时候也说不清”；42条合成历史recall17为4416 prompt tokens，首字76.577s/总84.144s，最新安排/白水正确，但编造昨天读过《昴之空》，未说用户名字。语义与格式均有反例。不能对比Bonsai3680 tokens称同长度吞吐排名；不同tokenizer/模板本来不同。重测完整结果与资源收尾待核，不改主力默认。
