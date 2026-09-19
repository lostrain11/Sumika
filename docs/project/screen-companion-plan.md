# 屏幕陪伴（实时吐槽/陪看）实现规划

状态：长期计划。用户原话：以后还会做实时读取用户屏幕内容，实时吐槽来陪伴用户看视频/打游戏。

## 与实时翻译的关系：共享采集，分离消费

翻译和陪伴的**输入**相同（目标窗口画面、必要时音频），但**消费方式**不同，因此共用 `extensions/desktop/capture.py` 与 `translation_pipeline.py` 里的采集、区域规划、叠层排除、变化检测、去重与过期丢弃机制，不共用输出链路：

| 维度 | 实时翻译 | 实时陪伴吐槽 |
| --- | --- | --- |
| 中间表示 | OCR 文本行（`lines[{text,score,box}]`） | 场景摘要/事件（画面变化、HUD 文本、音频强度） |
| 模型 | 可选翻译 provider，文本进文本出 | 多模态模型，图像+上下文进文本出 |
| 延迟预算 | 每帧约 60ms（跳过检测） | 秒级；必须低频采样与冷却 |
| 失败语义 | 不覆盖新台词（过期丢弃） | 场景已变则丢弃，不评论已过去的画面 |
| 权限 | 只读目标窗口 | 同样的只读窗口采集；默认不采集整屏 |

## 采样策略（避免把每一帧都丢给多模态模型）

1. 廉价信号先触发：帧间差分/哈希判断场景是否变化、OCR 读 HUD 数字、音频响度尖峰。
2. 只有触发后才调用多模态模型，且限制最短间隔与冷却时间（例如 3–10 秒一次，事件驱动优先）。
3. 结果带时间戳与场景指纹；指纹变化即作废，规则与翻译的过期丢弃一致。
4. 评论去重与频率上限：相似内容不重复说，避免打扰。
5. 全屏游戏期间降低采集频率，独占全屏抓不到时返回 unknown 并暂停，而不是用黑帧硬编。

## 与翻译共用的边界

- 只抓目标窗口矩形，叠层是独立顶层窗口，不进入识别范围。
- 本地优先、provider 显式选择、不静默切到云端或付费服务。
- 采集是只读的；不注入、不改写游戏内存。有反作弊的联网游戏只走外部采集。

## 逐个核对结果（2026-09-15）

### N.E.K.O / Project NEKO（猫娘计划）

归属核对：GitHub 上「Project NEKO」不是单一仓库。与它对应的是中文项目 **N.E.K.O（猫娘计划）**，有官网 `project-neko.online`，生态里包含第三方插件开发辅助仓库 `HMUG12/Project_Neko-plugin_skill`（MIT，v4.1.0，2026-09-12 核对过官方文档）。

已验证的实现方式：

- **插件架构**：SDK 面向 Python 3.11+，插件界面用 TSX/React 18；能力以插件形式提供，而不是内建于核心。
- **能力分布在插件里**：官方插件范式包含系统自动化、邮件、搜索、**教育 OCR**、**游戏控制**、外部程序桥接六类；仓库还收录插件市场 31 个已上架插件的源码逆向。
- **音频是独立管线**：有专门的音频处理文档，涵盖 WAV 合并、Viseme 口型同步、双轨播放，`ai_singer` 插件用云端 API + 流式输出。
- 官网插件快速开始页未出现屏幕采集/视觉相关关键词，说明**屏幕感知不是它的内建能力描述**，更像由具体插件自行实现。

对 Sumika 的含义：N.E.K.O 把感知与设备控制交给插件，扩展容易但边界由各插件自负；Sumika 采用“共享采集核心 + 显式 provider + 失败关闭”，并且明确不读游戏内存。两者可以互相借鉴：插件化值得学，边界策略保留 Sumika 的。

### 其他核对到的同名项目

- `nucket/NekoAI`（17★，MIT）：Tauri 2 + Rust + React 19 的桌宠应用，与「Project NEKO」不是同一项目，名字相近容易混淆。
- `awooshirokoai/Project-Aeon`（2★）：描述为 “hermes-agent + project-airi + project-neko”，把三个项目组合成带 VTuber 身体的 Agent，可作为“组合式集成”的参考，但星标很低、未深入核对。

### 本项目既有已验证参考

LunaTranslator 的 HOOK/OCR/窗口绑定与变化检测、XUnity.AutoTranslator 的 Unity 文本与纹理翻译、Textractor 的视觉小说文本 hook（均已在 game-translation-plan.md 中记录）。

### 仍需核对

Open-LLM-VTuber、AIRI、Amica 等项目如何做“屏幕感知 + 实时吐槽”，以及 N.E.K.O 具体插件（教育 OCR、游戏控制）的实现细节。这些需要逐个读代码后再写结论，未核对前不写入计划作为事实。

## 其他类似项目：直接读源码的核对结果（2026-09-15）

本机 `D:\Code\ui-refs` 下已有可用副本，因此以下是**读源码得到的结论**，不是二手描述。

### Amica（`ui-refs/amica`）

感知入口是**摄像头**而非整屏：`src/components/embeddedWebcam.tsx` 用 `react-webcam` 取帧，经 canvas 转成 `image/jpeg` 的 base64（`canvas.toDataURL('image/jpeg').replace('data:image/jpeg;base64,','')`）。

关键的是它的**两段式调用**（`src/utils/askLlm.ts`）：

1. 视觉后端先出描述，支持 `llava.cpp` 与 `vision_ollama` 两个本地后端（`getLlavaCppChatResponse` / `getOllamaVisionChatResponse`），未识别后端时直接返回 `vision_backend not supported`，不静默换云端。
2. 描述再作为文本注入人格模型：`This is a picture I just took from my webcam (described between [[ and ]]): [[${res}]] Please respond accordingly and as if it were just sent and as though you can see it.`

对 Sumika 的启示：**视觉模型与人格模型分开**正是我们要的形态；把“看到什么”压成描述再交给角色模型，既省成本也避免人格模型被图像 token 拖慢。它的后端白名单与失败即返回的设计也和我们的“不静默回退”一致。

### Open-LLM-VTuber-Web（`ui-refs/Open-LLM-VTuber-Web`）

这是 Electron 应用，屏幕采集走标准三段式：

- 主进程：`import { desktopCapturer } from "electron"`，`desktopCapturer.getSources({ types: ['screen'] })` 取源，返回 `sources[0].id`（`src/main/index.ts:71`）。
- 预加载：`contextBridge` 把 `desktopCapturer.getSources` 暴露给渲染进程（`src/preload/index.ts:75`）。
- 渲染进程：`src/renderer/src/context/screen-capture-context.tsx` 里用 `navigator.mediaDevices.getUserMedia(displayMediaOptions)`，失败再退回 `getDisplayMedia(displayMediaOptions)`，并用 React Context 管理这条 MediaStream。

对 Sumika 的启示：它采的是**连续 MediaStream（持续视频流）**，适合 VTuber 形态；Sumika 的按帧抓取 + 变化检测更适合“按需触发”，两者取舍不同。它的 IPC 分层（主进程取源、预加载桥接、渲染层持有流）值得借鉴，尤其是权限只在一处处理。

### N.E.K.O（前述）

插件化分发能力，OCR/游戏控制都在插件里，核心不含屏幕感知描述。

### 三方对比

| 项目 | 屏幕/画面来源 | 视觉处理 | 与人格模型关系 | 许可/形态 |
| --- | --- | --- | --- | --- |
| Amica | 摄像头单帧 | 本地 llava.cpp / Ollama vision 出描述 | 描述以文本注入人格模型（两段式） | Web 应用（Next.js） |
| Open-LLM-VTuber-Web | Electron 屏幕流（getSources + getUserMedia） | 持续流，按需取帧 | 未在本次核对范围内 | Electron 应用 |
| N.E.K.O | 未内建，依赖插件 | 插件自实现（如教育 OCR 插件） | 插件自行决定 | 插件 SDK（Python+TSX） |

共同点：**采集与推理分离**、**视觉结果要先压成可注入的上下文**、**对失败有显式处理**。差异在采集形态（单帧 vs 连续流）与能力分发（内建 vs 插件）。

### 仍未核对

AIRI（`moeru-ai/airi`）的屏幕感知实现、Amica 的对话触发频率与冷却策略、N.E.K.O 教育 OCR 插件的具体做法。未读代码前不写入结论。

## 参考副本时效性核对（2026-09-15）

本机副本与上游的差异必须先说清楚，否则结论会过时：

| 本机副本 | 本地 HEAD | 上游核对结果 |
| --- | --- | --- |
| `ui-refs/amica` | `ca2415c` 2025-07-24 | **结论已过时**：上游 `main` 已不存在 `src/utils/askLlm.ts`（raw 取回 404），说明该文件被重构或迁移；本文前面关于 Amica「两段式视觉描述注入」的结论**仅适用于该旧快照**，需按当前源码重新核对后才能作为事实 |
| `ui-refs/Open-LLM-VTuber-Web` | `d176e7d` 2025-09-05 | 仍有效：上游 `main` 的 `src/renderer/src/context/screen-capture-context.tsx` 仍存在 `ScreenCaptureProvider`、`startCapture`/`stopCapture`，采集分层结论成立 |
| `ui-refs/ChatVRM` | `b542aa0` 2025-05-27 | 仅作 VRM 渲染参考，与屏幕感知无关 |

结论：引用外部项目时必须标注「读的是哪个时间点的哪份代码」。旧副本可以节省时间，但不能当作当前实现。

## 常驻看屏幕：新核对到的参考（2026-09-15，读上游 main）

### screenpipe（`mediar-ai/screenpipe`）

上游 README 自述为「Record your screen continuously locally and provide context to your agents (Claude, Codex, Openclaw, Hermes, Runner...)」，定位是**本地连续录屏并作为 Agent 的上下文来源**（YC S26）。对 Sumika 的意义：常驻看屏的主流形态不是“每一帧都过模型”，而是**持续采集 + 本地索引 + 需要时检索给 Agent**；索引与推理分离，是控制成本与延迟的关键。

### Windrecorder（`yuka-friends/Windrecorder`）

上游 README 自述为「records everything on your screen in small size, to let you rewind what you have seen, query through OCR text」，即**小体积记录全屏历史 + OCR 文本检索**的个人记忆搜索引擎。对 Sumika 的意义：它证明了「持续记录 + OCR 索引 + 事后检索」这条路线在消费级机器上可行，也提示必须配套保留策略（否则磁盘会无限增长）。

### AIRI（`moeru-ai/airi`）

上游 README 中出现 “Computer Vision”、以及 DevLog「Pure vision progress for airi-factorio」（2025-08-26），说明它在**用纯视觉方式玩/看游戏**（Factorio 方向），并把可视化能力作为可选 SDK 的一部分。具体实现未读代码，暂不写成事实。

## 常驻看屏的设计含义（综合上述参考）

1. **采集与推理分离**：连续采集/索引是本地的，只有需要时才把“相关片段”交给模型；screenpipe 与 Windrecorder 都是这个形态。
2. **必须配套保留策略**：常驻记录必须可配置保留时长/体积上限与暂停，这是 Windrecorder 这类项目的必要组成，Sumika 要实现「低干扰模式」与一键暂停。
3. **隐私默认最小**：默认只采目标窗口而非整屏；本地优先、云端需显式授权；这与我们已有的叠层排除、失败关闭策略一致。
4. **分级触发**：帧差/HUD/音频等廉价信号触发低频多模态调用；常驻场景下这条比单次翻译更关键。
5. **不读进程内存**：参考项目里有靠游戏状态/内存取数的做法，Sumika 不采用，只做外部只读采集。

## 当前状态

采集、叠层排除、无效帧判定、文本跟踪、去重、过期丢弃已实现并有自动化测试；陪伴吐槽所需的“事件触发 + 低频多模态采样 + 评论冷却”尚未实现，属于后续阶段。
