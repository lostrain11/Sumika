# AIHOT 端侧资讯与候选实测（2026-10-17）

已完成一次性只读来源接入、近7日筛选和2B/4B真实19条日常评测。用户主力仍为LFM2.5-24B-A2B；Bonsai4B值得作为省内存候选，但没有证实整体更好，角色身份隔离仍失败。没有改UI、默认、自启或共享服务。

## 来源与现成资产

复用 `tools/evaluate_lan_daily.py` 的串行SSE、完整正文/独立reasoning、finish_reason、JSON精确语义和多轮角色夹具；没有另写质量判定。AIHOT提供现成匿名只读API，因此新增 `tools/evaluate_edge_news.py` 仅做有界GET和证据落盘，不装远程Skill或订阅。

[AIHOT接入页](https://aihot.news/agent)、[API说明](https://aihot.news/api/v1/agent)均HTTP200。读取最近7日模型最多30条、端侧/Liquid/Qwen关键词；原文均为非可信参考。API自称从新到旧，但序列有时间逆序，以下按原始发布日核实。不是全网穷尽。抓取原UTC为2026-10-16T16:32起，即北京时间2026-10-17零点后；原时间戳完整保留。

| 原始发布日期 | 候选/链接 | 核验与筛选 |
|---|---|---|
| 2026-10-15 | [Ternary Bonsai2发布](https://www.prismml.com/news/bonsai-2-family)，[AIHOT](https://aihot.news/items/d9w8kkjvo46lvbn5dxz1bltxv)报道10-16 13:50 | 官方正文确认为10-15；2B/4B/9B，Apache-2.0。PTQ/PQ需要PrismML fork；Q2_0受当前上游llama.cpp支持。2B/4B实际测试，9B未扩大测试，不声称不能运行。厂商手机/M5/4090吞吐不外推到GTX1060。 |
| 2026-10-15T15:00:24Z | [NVIDIA Bolt](https://blogs.nvidia.com/blog/nemotron-3-5-super-vl/)，[AIHOT](https://aihot.news/items/l9jgzg24ei3a7m8xu1xfhy9n7) | E4B4GB明确10-23才发布，因此延期；74B-A9B24GB超过本节点，淘汰。 |
| 2026-10-15 | [Liquid d1-ultra](https://www.liquid.ai/blog/d1-ultra) | 官方仅列付费API，输出问题概率而非聊天正文；不是当前本地替代，无付费调用。 |
| 2026-10-13 | [LFM2.5-24B-A2B](https://www.liquid.ai/blog/lfm2-5-24b-a2b) | 官方发布日、[模型卡](https://huggingface.co/LiquidAI/LFM2.5-24B-A2B)核实；继续用户主力，历史质量边界照旧。 |
| 非本周发布 | [LFM2.5-230M](https://www.liquid.ai/blog/lfm2-5-230m) | 从LFM原文追链发现，原始日期2026-06-25，不能当本周新模型。官方也不推荐其承担高级数学/编码/创作，未额外扩测。 |

近7日摘要另见Beam501B、Muse Spark816B、Step5600B；总权重远超16GB内存，未下载。Hojo-ASR/MiDashengLM属于音频、FLUX图像生成属于不同任务，本轮未拿它们替代文本主力，不将未测试说成不兼容。

## 固定版本、权重与节点

2B：[卡](https://huggingface.co/prism-ml/Ternary-Bonsai-2-2B-gguf)，revision `683f7be2629342a50987627b40881e54761a2430`，Q2_0 546,689,504 bytes，SHA256 `c2893fa6f951daee8b7263d5f49b455e57989ef56417a22125b03566dc560650`。

4B：[卡](https://huggingface.co/prism-ml/Ternary-Bonsai-2-4B-gguf)，revision `8d6557168168f91ea6697a4a49ed2ef622b53adb`，Q2_0 1,212,103,520 bytes，SHA256 `64a5183b44921bdb5ac4a6f5f92007821d6ebe5c66997d3c147fd214ab9433d4`。

先查缓存：节点F:/GGUF只有LFM，Ollama manifest没有Bonsai。节点到HF443失败后，本机固定revision下载→SCP，双端SHA均匹配HF LFS元数据。源码外缓存 `D:/Caches/models/` 与节点 `F:/GGUF/` 保留作复用；没下载视觉projector或drafter。

节点 i7-7700HQ、GTX10606144MiB（原有服务约占2871MiB）、16GB（开始空闲约13.2GB），F盘空闲约401GB。原8082 PID1252实际为Qwen3-4B Q4_K_M/2048上下文，未改其运行。8084/8083探测超时，11434无加载模型。运行时 `F:/llama-cuda124/llama-server.exe`，0.6.0-dev build11624/af0579c78。

两个候选按顺序CPU-only：`-ngl 0 -c 4096 -t 4 --parallel 1 --jinja --port 8086`。新端口LAN不可达，使用本机SSH隧道`-L 18086:127.0.0.1:8086`，不改防火墙。相同评测参数thinking off、1000 output tokens、temperature0.2，前6结构化schema只约束字段类型而不约束正确答案；其余无schema。使用合成资料/通用角色澄，没有发送隐私历史。

```powershell
python -X utf8 -B tools/evaluate_edge_news.py --query 端侧 --query Liquid --query Qwen --out .sumika-next/laptop-model-bench/aihot-20261017.json
python -X utf8 -B tools/evaluate_lan_daily.py --endpoint http://127.0.0.1:18086/v1 --model Ternary-Bonsai-2-4B-Q2_0.gguf --thinking off --structured --max-tokens 1000 --out .sumika-next/laptop-model-bench/bonsai2-4b-daily-20261017.json
```

## 实际结果与判定

| 同19条合成夹具 | 2B CPU-only | 4B CPU-only | LFM此前混合offload参考 |
|---|---:|---:|---:|
| 严格JSON语义 | 3/6 | 5/6 | 5/6 |
| 正文完整非空/finish stop | 19/19 | 19/19 | 19/19 |
| 热轮总耗时中位 | 2.326s | 5.330s | 5.409s |
| 热轮范围 | 0.553～5.145s | 1.387～15.919s | 1.497～14.586s |
| 热轮可见首字中位 | 0.399s | 0.918s | 2.473s |

冷/首请求另列：2B烟测第一条13.697s；4B首次3.338s。二者不同冷页缓存和启动条件，不作冷启动优劣排名。2B先行6项烟测4/6、随后完整19项中的结构化3/6，采样变异如实保留；没有挑较高一次作最终能力分数。

2B错误：unknown场景误输出study或整个`study|game|unknown`；未知地点输出“未定”而非null；列表推导错[0]；翻译夹Never和自述；计划含0分钟第三步；角色新会话说用户名是澄。快但质量不足。

4B错误：教学视频误判game；其余结构化5项正确。自由6项：能保留不确定、摘要、否定数字翻译、链式求导、列表[2]与不修改原列表、10+15+5分钟计划。角色能更新周六15点/白水，未知书页说没记录，拒绝谎称删除，但新会话答“你叫澄，复习时间就现在！别废话”，身份混淆并编造安排，长期角色质量未通过。19轮无独立reasoning或think标签残留。

公平边界：相同夹具与评测temperature0.2，未使用模型卡建议temperature0.7；模型/量化/CPU与GPU混合offload、缓存不同，无严格吞吐胜负或总体准确率。4B比本轮2B更完整，尚不足替换LFM；LFM仍需解决自己的推理残留/角色事实问题。没有测试视觉、声音、真实完整安和昴卡、长上下文或产品UI。

## 证据与清理

证据在 `.sumika-next/laptop-model-bench/`：`aihot-20261017.json`、`edge-originals-20261017.json`、`bonsai-originals-20261017.json`、`edge-runtimes-20261017.json`、`edge-extra-20261017.json`；`node-news-20261017.json`、`node-cache-news-20261017.txt`；`bonsai-download-20261017.json`、`bonsai4-download-20261017.json`；`bonsai2-2b-smoke-20261017.json`、`bonsai2-2b-daily-20261017.json`、`bonsai2-4b-cold-20261017.json`、`bonsai2-4b-daily-20261017.json`及summary。

临时2B server6392/wrapper4792、4B server6712/wrapper5764均核对命令行/模型/端口后精确停止；`bonsai2-cleanup-20261017.txt`、`bonsai4-cleanup-20261017.txt`证实原PID1252保留，8086无监听。权重和有价值日志保留，未改默认、共享服务、自启任务或防火墙。

## 用户追加的低显存优化调查（已完成有界探索）

4B追加GPU offload真实19条：非空19/19、JSON5/6，端到端中位0.931s（CPU5.330s），可见首字中位0.464s；GPU总占4332MiB。角色身份和计划质量仍有反例，不能因加速更改LFM主力。

AirLLM/Strata/MoE4All/vllm-xtu-moe及自主扩展ExLlamaV3/KTransformers/IPEX-LLM/ZLUDA/原生投机均已核实当前资料。MoE4All官方1.0.3在GTX1060真实识别Vulkan，复用现有35B GGUF的两次受限加载均因完整专家层空间不足退出，无生成质量结论。Strata当前已实验性支持sm61，旧绝对否定已更正；AirLLM也并不要求全权重常驻RAM。详见 [独立优化报告](edge-inference-optimization-20261017.md)。本轮服务均已退出、SSH隧道已停止，共享1252/8082健康与GPU基线恢复已核实。


## 第四轮新增：Bonsai9B真实候选

此前9B“未测”边界已变化：官方固定revision `5b2abb02362efbed46bbe204014b02837778b2c2` 的Q2_0 2,556,640,128 bytes，SHA256 `1f884aa56aacd2bbbb2e4b7abaead2b1102b74a9c75a23fc33dab916813a384d`，下载到E:/SumikaModels、节点F:/GGUF，双端SHA通过。沿用现有llama.cpp、4096ctx/ngl24/threads4/FAoff，保留共享1252。26项长历史/来源/缓存+8项代表均非空stop；来源语义3/3、代表JSON5/5。12轮没有本轮LFM旧偏好回退，但fresh身份表述仍别扭，不能宣布完整角色验收或替换用户选定LFM。模型工作集4.26GB、可用RAM9.56GB、GPU总4896MiB。完整公平边界、原文、缓存收益及清理见优化报告第四轮及 `.sumika-next/laptop-model-bench/round4-*`。没有下载fork专用PTQ/PQ/MTP或视觉投影；没有部署产品。
