# 整理、DSH 升级与桌宠陪学执行记录

## 当前冻结执行稿：Sumika 阶段归档与 B站／PDF 陪学交付

版本：2026-10-09 v1。接手工具：ZCode；执行模型：GLM5.3flash。状态：**计划已归档，执行包 P0 尚未开始；不是产品完成报告。** 本节是当前完整执行入口，下方历史章节仅提供证据，不作为新的任务清单。此处 P0～P8 是交付包编号，与 `plan.json` 中旧阶段 P0～P7/P4-UI 不同；不要直接覆盖历史阶段编号。

归档回执（2026-10-09）：完整稿及 ZCode 启动说明已写入本文件；handoff/progress/plan 已补同一入口与 P0 下一步，保留历史 P6；浏览器 UI 方案已从待确认更正为已确认。`python -X utf8 -B -m sumika_next.cli check`、`handoff`、`git -c core.safecrlf=false diff --check` 均通过；另核对 P0～P8、协议/失败/回退及三份指针存在。本轮没有产品改动、设备测试、提交、推送或新打包。

### 1. 接手启动与完成边界

可将下面整段作为 ZCode 的首条任务：

```text
在 D:\Code\Sumika 工作。先读 AGENTS.md、docs/project/handoff.json、progress.json、plan.json，以及 docs/project/companion-implementation.md 顶部的“当前冻结执行稿”。需求原文看 requirements.json 和 approved-plan.md，后者不要用实施方案覆盖。按冻结稿从交付包 P0 开始，保留所有已有工作，不重建已存在模块。先核对 Git 和现场，不把旧报告当作新源码或新安装包的验收。每包完成后记录实际文件、验证结果、限制和下一步，再继续下一包；上下文不足先写接驳，不凭摘要重放操作。真实浏览器/设备测试前通知用户，不抢占用户游戏时的鼠标键盘。不要把计划落盘或原型通过称为总目标完成。
```

总目标：桌宠在用户现有软件中理解当前学习内容，支持文字、连续语音和适时主动讨论；首版优先 **B站视频与 PDF 阅读**。微信读书延后，游戏只保留通用画面问答方向。整理、DSH 升级、插件复用与调研均服务于此目标。

本次交接要求实现到可安装陪学首版，但**阶段上传只包含源码和脱敏文档，不打新包、不上传二进制**。最终安装包在 P8 单独生成验收；公开二进制发布需核对许可证及发布授权范围，不因源码推送自动发布。用户已授权阶段提交和推送现有分支，不需要重复询问。真实设备验收前通知用户；需要登录由用户完成。既有配置模型可用于已授权的功能测试，不展示 key，不扩大到购买服务或无关费用。

停止扩展条件：各包验收通过并完成 P8 安装、升级、回退与日用切换，交付安装器、SHA、证据、插件兼容结果、设计覆盖表、参考清单及回退说明。缺少真实服务/硬件时明确记录未验收项及恢复动作，不能记为完成。不要为单个疑难探针反复造新包，先完成核心集成再集中生成候选。

### 2. 已核对基线与证据限制

- 本轮接手前审计分支为 `codex/sumika-next-dsh`，本地及远端 HEAD 为 `73e4de7153468ff6f8659478e6e1413b2ff4987a`；92 个 tracked 改动、249 个 untracked 文件。这是审计快照，执行 P0 时重新核对，不照抄计数。
- 远端 `https://github.com/lostrain11/Sumika.git` 是公开仓库，默认分支 master。现有旧 Release `v0.1.0-internal.20260920` 是 draft/prerelease，含旧 K 安装器，不修改，不以它代表当前源码。
- 仓库 `runtime/dsh` 仍为 `0.1.5-rc.2`；目标固定 `0.2.0-rc.2`。隔离环境的 P2、连续性、角色、取消、profile 副本迁移已有验证，未切日用。`0.2.1-alpha.1` 只观察。
- 插件 lifecycle 验证使用 synthetic bundle，不等于插件市场全部兼容。安装成功也不等于模型、密钥、外部程序、设备等依赖就绪。
- 最近全套 945 tests、18 skips，出现 1 error：`test_personal_snapshot.PersonalSnapshotTests.test_completed_restore_can_be_backed_up_and_relocated_again`，`tools/backup_personal_data.py:160` 的临时 journal `os.replace` 报 WinError 5。单测复跑通过，原因尚未确定，P1 必须调查，不能写“已修复”。最近连续性 check 和 diff 检查通过。
- 最新安装器落后于当前源码，最终安装验收未完成。旧 J/AI/AL 等候选通过的报告不能继承到新候选。
- B站原视频元素 `captureStream → AudioWorklet` 真实测试：`E:/SumikaBuild/bilibili-player-content-asr-20261009-b/report.json`，7.9 秒、79 包，静音且 volume=0 时可采集，SenseVoice 耗时 3394.7ms（含加载），有中文转写，pause 后包数稳定为79。这只证明此路径可行，不证明生产传输、ASR质量或 P95 达标。
- 历史 `bilibili-product-sensevoice-20261008-j/k` 是其他音轨链路的转写/融合/停止/撤销证据；原始音轨 offset 不是已证明的视频时间。干净视频帧证据是 video 元素采集与合成 DOM 叠层测试，不能扩大成真实特殊弹幕、全屏、所有视频质量均通过。

现有可复用输入（先检查存在、版本及报告再用；这些 E 盘路径只是本机输入，不能写进产品默认路径）：

```text
E:/SumikaBuild/product-candidate-20261009-al
E:/SumikaBuild/host-runtimes-20261008-models
E:/SumikaBuild/desktop-runtime-20261008-pdf
E:/SumikaBuild/voice-runtime-sensevoice-20261008-a
E:/Models/Speech/sumika/sensevoice-int8-20240717
E:/SumikaBuild/process-audio-helper-20261009/SumikaProcessAudio.exe
D:/Tools/InnoSetup/7.1.0/ISCC.exe
D:/Tools/GitHubCLI/gh.exe
```

### 3. 现成资产与固定架构

本轮已查工作区，以下均采用直接使用或改造后使用；不另建角色、插件市场、阅读器、调度系统或第二套 UI。

| 资产 | 路径 | 使用方式 |
| --- | --- | --- |
| 四屏设计及覆盖表 | `ui/prototype-d/index.html`、`docs/project/ui-design-coverage.md` | 直接作为视觉基准；先更新覆盖再改 UI |
| 陪学详情、目标选择和文字界面 | `ui/app/companion-session.js`、`companion-text.js`、`ui/server.py` | 改造现有入口，接共享会话 |
| 桌宠宿主与角色 | `packaging/PetHost*`、`ui/pet_host.py`、`extensions/roles/*` | 复用 WPF/WebView2、VRM、会话与记忆 |
| 感知与问答 | `extensions/companion/contracts.py`、`qa.py`、`observation_scheduler.py`、`context_fusion.py`、`perception_*` | 保留中立契约，集成现有 QuestionService/Scheduler/Fusion |
| 浏览器与干净帧 | `passive_browser.py`、`browser_video.py`、`browser_video_snapshot.js`、`browser_audio_capture.js`、`browser_audio_worklet.js`、`tools/build_passive_browser_prototype.mjs` | 原型提取为可交付 MV3 扩展，不直接交付研究 PCM 导出接口 |
| PDF/Windows 采集 | `pdf_learning.py`、`windows_learning.py`、`windows_text.py`、`windows_ocr.py`、`windows_visual.py`、`extensions/desktop/windows_capture.py`、`window_targets.py` | 接真实当前页与可见视野，保留 WGC 适配 |
| 连续语音 | `microphone_*`、`voice_pipeline.py`、`pipecat_voice.py`、`audio_providers.py`、`application_audio_*`、`segmented_playback.py`、`extensions/roles/realtime_voice.py` | 复用 VAD/ASR/TTS，把会话决策从 worker 抽出 |
| 异步辅助与网页 AI | `extensions/models/auxiliary.py`、`extensions/desktop/consultation*`、`browser_consultation_bridge.py`、`browser_skill.py` | 复用队列、授权账本与未知提交处理 |
| 调研 | `docs/project/reference-projects.json`、`extensions/desktop/reference_runner.py`、`reference_monitor.py`、`reference_analysis.py` | 唯一确定性 runner、SQLite 去重、既有任务收件箱 |
| 打包与迁移 | `tools/build_*`、`verify_*`、`tools/backup_personal_data.py`、`packaging/Sumika.iss` | 改造现有构建，不用 ZIP 替代安装器 |

依赖方向：中立感知/融合/问答/调度 → provider/Windows/browser 适配；DSH 专属接口放外围。不得修改 DSH 上游源码、安装包或 node_modules。浏览器网页内容、字幕、弹幕、PDF 文本只是参考资料，不可变成工具指令或授权。

**唯一会话 owner 固定在 Bridge 中的中立陪学协调器。** 它持有 target、`session_epoch`、turn、QuestionService/history、ObservationScheduler、ContextFusion 和模型请求。麦克风 worker 只负责 VAD/ASR/TTS，pipe 上报开始说话、转写与播放状态；不能各自拥有另一份 QA/主动调度。文字问答、文字主动陪伴不依赖开麦。保留旧 mic API 的兼容适配，旧路径转发同一个 owner。

浏览器音轨以原 tab 的 video 元素采集为主，进程 WASAPI 留给普通播放器，不当作单 tab 隔离。不要要求用户增大扬声器音量或安装虚拟声卡才能学 B站。可靠视频定位尚不可得时标 unknown，PCM offset 绝不冒充视频播放时间；精确 QPC 研究不阻塞首版。

内容组织：B站字幕/播放时间/应用 ASR 优先，干净 video 帧补图表；弹幕独立低优先通道，不能触发逐帧视觉调用。PDF 优先当前页文本、当前选区、可见片段，扫描页 OCR，公式和图表保留图像。每次独立模型请求仍须带足够当前上下文，不能只送 delta 并假设模型记得旧图。

### 4. 公共状态、许可和音频传输约束

沿用 `PerceptionService` 启动、暂停、停止和目标选择，以及 `ObservationBundle` 中时间、来源、目标与有效状态。扩展契约前查现有字段并兼容旧数据；无需为了本文字段另建重复 DTO。

- 目标身份必须明确：浏览器 tab/origin/媒体身份；PDF 绝对文档身份、页码与 viewport；Windows 窗口及可选区域。无可靠页码或播放时刻时为 unknown，不从标题/PCM 时长猜测。
- 会话每次启动/目标替换/撤销具有代次；turn 引用提问瞬间冻结的内容。视频正常推进可继续完成冻结回答；换页、seek、换源、许可撤销取消旧响应与 TTS。所有异步返回检查代次和 turn，拒绝迟到内容。
- 状态至少可区分 stopped、starting、running、paused、error；error 保留准确原因，禁止呈现为正在采集。开始/暂停/停止均幂等，重复连接不得重复 worker。
- 连接不等于采集许可。扩展现有 passive grants，独立 `capture_audio` 缺省 false；画面、应用音轨、麦克风、朗读分别授权。暂停/撤销立即停止相应采集并清缓冲。重启不恢复旧许可。

浏览器音频 push 使用独立序列（不是视频快照序列）：

```json
{
  "tab_id": "绑定的实际tab标识",
  "audio_epoch": "本轨代次",
  "sequence": 0,
  "media_identity": "当前视频/分P身份",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le",
  "sample_offset": 0,
  "pcm_base64": "100ms单声道PCM的base64"
}
```

每包100ms，即3200 bytes PCM；sequence 在一个 audio_epoch 内严格连续，sample_offset 表示该轨采样偏移，不是视频时间。扩展和 Bridge 队列各最多20包/2秒，单发送链；HTTP只鉴权、校验、入队，ASR在隔离 worker 内复用 `SegmentedApplicationAudioTrack` 来源适配。校验绑定 caller/token、origin、tab、media、许可和代次；loopback 也不能放任任意网页调用，沿用现有 bridge 身份边界。

序列缺口、队列满、提交状态 unknown：停轨、报错、清待处理，显式重新开始；不静默丢包、不无限队列、不自动重发。pause 清 buffer；resume、同视频 seek/rate 变化使用新 audio_epoch 并失效旧转写；新视频、分P、页面重建、扩展重启需重新连接和许可。绑定前后身份不一致则丢弃采集结果。PCM 只留 RAM，不进日志、SQLite、Git 或普通诊断报告。

原始画面/音频默认短期内存缓冲。用户明确保存的学习笔记存个人数据目录并带来源，普通屏幕内容不自动写长期角色记忆。脱敏证据保存测试配置、指标及必要摘要，不保存 key、cookie、原始模型请求或私人阅读内容。

### 5. 顺序执行包

每包回执写进本文件当前执行区，并同步三份主记录：修改范围、行为、运行命令/结果、夹具与真实测试区别、未覆盖、下一入口。不要复制整份冻结稿进每个 JSON。

#### P0：阶段快照、提交上传与记录整理

依赖：无。范围：Git、现有 docs/project 记录、确认无引用的一次性产物。

1. 重新读 AGENTS 和主记录，核对 branch/status/diff/untracked、remote。建立逐项待提交清单；检查公开上传中的凭据、个人数据、屏幕/音频、模型权重、运行缓存、安装器与旧源码忽略目录。未知文件先查引用，不盲删、不盲 `git add .`。
2. 先保存现有成果快照，再精简重复记录；显式 stage 核对后的源码、测试、工具及脱敏文档。建议提交 `feat: checkpoint companion learning and DSH upgrade work`，随后文档整理提交 `docs: freeze Bilibili and PDF delivery handoff`；实际文件已在首个提交则避免空提交。
3. 补录 requirements 中缺失的用户原文与 B站/PDF 优先取舍，按现有 schema/sha256/source 规则；不能用本文转述冒充原文。保留 approved-plan 原文。修正旧文档关于 NEKO 屏幕理解、连续语音、截图叠层及发行状态的过时结论，标实际版本和依据。
4. 三份主记录只保留当前状态与历史证据指针，整理重复 checkpoint 前确认快照已提交。保留设计、有效证据、可复用工具和个人数据。清理只限确定失效且无引用的文件。
5. 运行连续性 check/handoff 与 diff 检查，检查 staged diff；推送现有分支、不 force、不改 master 或旧 release。用远端 SHA 验证推送落地；失败记录本地 commit 与准确原因，不绕过拒绝。

验收：提交清单可复核，无秘密/二进制/个人数据，远端与预期 commit 一致；主记录能定位本稿、下一包和未验证能力。当前任务只是落盘计划，P0 仍待 ZCode 执行。

#### P1：可恢复基线与 DSH/依赖固定

依赖：P0。范围：`tools/backup_personal_data.py`、相关测试、runtime 配置与构建锁、连续性/角色 DSH 适配。

1. 复现 WinError5，查临时 journal 生命周期、文件句柄/权限、并发写入及替换范围。先证据后修复，不用放大超时或无限重试掩盖。复跑单测及关联备份/恢复/再次迁移链；全套出现同错误则不得放行。
2. 固定 DSH `0.2.0-rc.2` 来源包、依赖锁、版本/发行摘要；保留旧 runtime 与对应 profile 副本。在独立目录验证连续性事件、历史读取、角色版本检查、Remote、会话、UI 插槽、加载卸载与配置合并。只改 Sumika 条目，不覆盖用户其他插件。
3. 语音固定 sherpa-onnx/core `1.13.8` 和 SenseVoice 模型来源/校验/许可。运行时 `_pth` 不得带开发目录；模型留外部，产品默认路径可配置。缺依赖显示原因，文字功能仍能工作。
4. 新版 profile 迁移失败恢复成对副本，旧 runtime 不直接打开已迁移新 profile。尚未通过前不切日用。

验收：备份迁移链与运行时升级/回退通过；来源可追踪；配置保留；锁定依赖可离线重建。若上游接口不符，改外围适配并回归，不改上游源码。

#### P2：共享会话协调器与已有 UI 接线

依赖：P1。范围：Bridge/`ui/server.py`、`extensions/companion/*`、既有陪学详情与桌宠宿主。

1. 提取 mic worker 内 QA/主动讨论职责到唯一协调器；接现有文字、语音、采集、模型取消/状态接口。旧 mic API 转发，保持一个 history/target/scheduler。
2. 先更新设计覆盖：现有四屏能力详情里的学习目标选择扩为 PDF 窗口或已连接 B站 tab；应用声音、画面、麦克风、朗读独立状态/许可。用户已确认此方案，不再问已决取舍。扩展 popup 仅连接本页、断开和状态；不新建主页面、项目面板、能力入口。
3. 验证不开麦时文字提问与主动调度正常；暂停、撤销、换目标/页、取消的状态事件传到 UI 与宿主；点击穿透/收起/自身排除沿用现有实现。

验收：文字与语音读同一会话，迟到响应不播放，不重复派发；UI 对照设计稿，DSH 原生功能保留。协调器失败时停止新增派发、取消进行中并显示错误，重启不重放未知调用。

#### P3：B站生产扩展与音轨融合

依赖：P2。范围：现有 passive browser 原型、采集 JS、音轨 endpoint/worker、融合与浏览器验收。

1. 从原型提取固定 MV3 产品扩展；研究 PCM 导出接口不 ship。最小 origin/权限，原 tab 连接，不要求用户转移到 Agent Window。显式安装说明，不静默安装、不改浏览器政策。
2. 使用第4节有界音频协议；video captureStream/AudioWorklet 降采样16k单声道，接隔离 ASR 和 fusion。无音轨/CORS/播放器替换等运行时不支持时显示准确能力缺口，保留可用文字/字幕/图像；不要伪装采集成功。
3. 字幕优先顺序为可用 TextTrack、当前可见 B站字幕 DOM、应用 ASR；记录来源及可靠时间。B站 AI 总结可作附加摘要但不是课程事实或首版依赖，不依赖私人未核验 API。弹幕独立采集、去重/聚合，不能视为讲师内容。
4. 干净帧来自 video 元素，不把弹幕 DOM 当视频变化；实际播放器含烘焙弹幕或不能分层时标限制，采用字幕/音轨优先与低频画面，不以每条弹幕触发模型。
5. 实施暂停/seek/rate/分P/换视频/标签关闭/扩展重启/撤销生命周期；错误不重试 unknown。文本、画面和音轨绑定同一媒体代次。

验收：字幕/无字幕各30分钟，其他 tab 同时播声音，目标静音与音量零仍可转写；暂停无新增包，seek不串旧资料，分P重新许可。先夹具再通知用户真实测试；现有79包报告不可替代。

#### P4：PDF 当前页与区域跟随

依赖：P2，可在 P3 后顺序执行。范围：现有 Edge 阅读器、pdf_learning/Windows collector、目标适配与缓存。

1. 用户仍用现有阅读器。可靠当前文件+页码时复用 pypdf 当前页文本；选中文本/可见正文与整页抽取分开标注。未知文件/页码时用可见 OCR/图像并标 unknown，不从窗口标题猜页码或读整文件替代视野。
2. 当前页身份采用绝对文档路径/实际身份、页码和 viewport；同名不同路径、文件更新、缩放、旋转、换窗口、页跳转使对应缓存失效。OCR补扫描页，公式/图保留图像；截图与文本绑定前后核对身份。
3. 默认固定窗口；支持现有可选区域、DPI与窗口移动校正，前台跟随必须显式开启。WGC/遮挡/黑帧验证，排除桌宠自身；黑帧/过期资料不作为新学习事实。

验收：至少20次真实翻页，包括扫描中文、公式、选区、同名异路径、双窗口、缩放、恢复。页切换取消旧回复，来源能定位真实页或说明缺口，不自动保存书籍内容。

#### P5：节省 token、异步辅助、笔记与用量

依赖：P3、P4。范围：现有 scheduler/fusion/qa、auxiliary/consultation、UsageStore及个人数据。

1. 本地变化检测约1Hz，字幕/文本增量优先；图像只补必要图表/公式与问句即时画面，无法得到干净图像时低频 fallback。逐请求保留足够上下文，无有效新内容不调用模型。
2. 后台模型分析最多2次/分钟，主动发言默认间隔至少120秒，用户安静程度优先。章节结束/暂停/明显变化触发，用户提问最高优先；后台单 in-flight 加一个 latest 待处理项，不排积压历史。
3. 弹幕与简单注释可本地规则/模型异步去重、分类、摘要。复用本地摘要队列；模型失败/未安装不阻塞主问答，不以低质量摘要替代原始关键公式。保留来源，摘要不能成为未经验证事实。
4. 网页 AI 可用于非实时摘要等异步工作，但必须沿用显式站点 read/send 授权账本，发送前控制范围，不上传完整书籍/音频或自动发送屏幕私人内容。提交 unknown 不自动重发；免费网页服务不作为实时链路依赖。
5. 主动保存笔记才持久化，带 tab/视频时刻或PDF页等来源。UsageStore 兼容迁移，补音频秒数、视觉调用，只有可靠价格时估费用；unknown 汇总不能当0。暂无月费上限，不另加虚构费用数据。

验收：无变化零模型调用，弹幕变化不造成视觉风暴，问句抢占，摘要失败不阻塞，异步迟到不写当前会话；旧 usage 数据可读、未知正确显示、笔记来源准确、不写长期角色记忆。

#### P6：连续语音与真实延迟

依赖：P5。范围：现有 Pipecat/Silero/SenseVoice、麦克风和分段TTS、模型流式 provider。

1. 接统一 VAD→ASR→模型流式文字→分段TTS，预加载现有模型。教程音轨与麦克风分轨，教程不是用户问题；普通音量/静音不影响浏览器内容音轨。
2. 用户开始说话立即停止播放并取消旧模型请求；旧段落和迟到TTS不得恢复。不能以停止麦克风代替 barge-in。先耳机低回声验收，扬声器回声另测且单独标限制。
3. 断网、provider错误和未知提交保留真实状态，不无限重试或重复付费调用。文字降级可用，worker停止/重启无旧许可或缓冲。
4. 通知用户后测至少30个连续 turn，记录停说→ASR完成→首字→首音；冷启动单列，正常网络/选定服务中位目标约3秒、P95≤6秒。未达到则记录瓶颈和真实结果，不只挑快样本。

验收：连续问答/打断/暂停/撤销/断网恢复、应用音轨隔离、无迟到播放；转写术语质量和延迟有真实报告。30turn不能以夹具或录音回放替代全链路。

#### P7：插件、参考调研与完整 UI 回归

依赖：P6。范围：兼容清单、原生插件管理、ReferenceRunner/SQLite/既有任务渠道、设计覆盖与验收工具。

1. 使用 DSH 原生安装/配置/启停/卸载与版本范围拒绝。对实际拟替换模块的官方/社区插件，核对版本、许可证、源码、依赖、配置、运行模式与 UI 插槽；能力相当才替换，不仅凭插件市场介绍。兼容清单逐个记录“已验证/条件/未验证”，不宣称全部能用。配置保留及不兼容拒绝必须实测。
2. 沿用唯一 reference-projects.json 清单，已有约26项，执行时核对实际数。覆盖 NEKO、AIRI、Open-LLM-VTuber、Pipecat、LiveKit Agents、Gemini Live Console、DeepTutor、Page Assist、Windrecorder、screenpipe、DSH、ZCode、Codex、CUA 等；每条记录 URL、实际版本/commit、核对日、license、模块、源码依据和限制。NEKO已有屏幕理解/主动陪伴，优先看触发、播放协调、上下文；screenpipe 许可重新核对，首轮仅架构参考。
3. 唯一确定性 ReferenceRunner：周一10:00 Asia/Shanghai；月首轮同时发现候选；Sumika关闭后下次启动合并补查一次。SQLite处理周期去重/补查，先比较版本/commit/相关文件，有变化才调用已配置模型；每轮深分析≤5项、每月新候选≤3项。无变化静默且零模型调用，相关更新/需处理失败通过既有任务/会话渠道报告，分值得借鉴/需验证/暂不相关，带依据。不自动安装升级产品。
4. DSH 原生 schedule 到期会唤醒 Agent，不承担要求零模型的轮询；保留原生用户提醒，不增加第二个调度入口。runner挂接现有运行生命周期，启动补查不重跑每个错过周期；限流遵循服务信息，失败持久化，不疯狂重试。
5. 四屏逐屏对照设计，窄窗口、缩放、主题、菜单弹窗、键盘和离线状态；保留会话轨迹、用量用时、系统提示开关、模型选择、复制反馈、折叠侧栏等 DSH 原生功能。覆盖表列偏离/未做，原生功能和唯一入口断言保持。

验收：真实采用插件生命周期及配置保留，不兼容拒绝；调研周期去重/补查/限流/失败/无变化零调用；四屏证据对应同一待发行候选，不能仅渲染通过。

#### P8：最终候选、安装验收与日用切换

依赖：P1～P7。范围：现有构建/安装器、runtime/profile 备份与交付记录。

1. 集中生成一个候选，记录 source SHA（有dirty则准确记录）、输入锁/资源哈希和输出manifest；更新哪个部件就重建哪个部件及相应包，禁止源码已改但报告仍引用旧包。候选必须含当前主题、语音修复、MV3扩展及模型配置说明。
2. 模型默认外置：选目录或从固定校验/许可证明确的来源显式下载；不要硬编码 E盘，不随包偷偷带模型。缺ASR或麦克风时文字正常，依赖缺失可见。BrowserSkill等依赖沿用现有 readiness/安装机制，能合法打包的固定版本打包，需用户安装/许可的给明确步骤，不静默改浏览器。
3. 执行 portable staging、能力包、插件 lifecycle、runtime升级回退、packaged install验证，再使用现有 Inno Setup生成安装器；ZIP不能代替。真实安装/重装/升级/自定义路径/卸载保留个人数据/干净Windows验证必须针对同一哈希产物。
4. 日用切换前停止旧服务和新增派发，备份旧 runtime+对应配置和个人数据。新版本通过再切；失败停止新版，恢复旧 runtime 与旧 profile 成对组合，保留新版副本供排查，禁止用旧版直接开新迁移配置。检查残留进程、端口、锁及重启恢复。
5. 交付安装器+SHA、兼容表、UI覆盖、B站/PDF/语音/性能/用量/调研证据、安装升级回退说明。阶段源码上传与二进制发布分开，公开发布前核对外部分发许可及授权。

验收：同一候选通过全回归与真实场景，安装/升级/回退可复现，最终状态与文档一致。真实硬件、服务或干净Windows未验证则列限制并保留待办，不将已装开发环境当干净机。

### 6. 命令入口与证据约定

每个工具先看 `--help` 核对当前参数；下列是已有入口，不保证可直接套用本机旧目录。构建/真设备工具不得在用户游戏时暗中操控鼠标、麦克风、音量或浏览器。

```powershell
python -X utf8 -B -m unittest discover -s tests_next
python -X utf8 -B -m sumika_next.cli check
python -X utf8 -B -m sumika_next.cli handoff
git -c core.safecrlf=false diff --check

python -X utf8 -B tools/verify_portable_staging.py <candidate>
python -X utf8 -B -m tools.verify_capability_package <candidate> --output <new-report> --require-process-audio
python -X utf8 -B tools/verify_dsh_plugin_lifecycle.py --runtime <candidate>/runtime/dsh
python -X utf8 -B tools/verify_runtime_upgrade_rollback.py --new-runtime <candidate>/runtime/dsh --migrate-fixture --output <new-dir>
python -X utf8 -B tools/verify_packaged_install.py <candidate>
python -X utf8 -B tools/build_setup.py <candidate> --compiler <ISCC.exe> --output <new-dir> --version <version>
```

源码回归使用现有 tests_next 和对应 verify 工具，例如 `verify_bilibili_passive_live.mjs`、`verify_bilibili_audio_live.mjs`、`verify_companion_pdf.py`、`verify_companion_session_ui.mjs`、`verify_ui_matrix.mjs`；不用孤立新探针替代产品路径。本地夹具不可证明真实服务/硬件。测试报告注明 commit/dirty、runtime版本、模型/provider、输入目标、时间、正常/失败分支、指标、限制及产物哈希；脱敏摘要可入Git，原始运行数据留忽略目录或本机证据目录。

每包失败时：停止该包新增派发，保留证据及未知状态，恢复该包明确的旧组合；其他独立检查可继续。新事实允许调整局部实现，不改目标、许可、公开接口或不可逆影响；影响这些边界时写明变化并向用户确认，不偷偷扩大范围。

### 7. 最终交付检查清单

- [ ] P0 明确 stage、脱敏提交和远端SHA核对。
- [ ] P1 WinError5原因/修复或真实阻碍明确；DSH目标及paired rollback通过。
- [ ] 唯一会话owner；不开mic的文字问答与主动讨论有效。
- [ ] B站字幕与无字幕各30分钟；目标静音/零音量与其他tab并播；seek/rate/分P/断开不串轨。
- [ ] PDF至少20次真实翻页与扫描中文/公式/同名异路径/双窗口/缩放/恢复。
- [ ] 连续语音至少30turn，真实barge-in、无迟到TTS、教程不作提问，延迟含冷启动说明。
- [ ] 无变化零模型调用、用户提问优先、quiet有效；usage未知不计0；笔记有来源且非自动memory。
- [ ] 重启/撤销不恢复旧许可，PCM/原始屏幕不落日志；异步网页AI unknown不重发。
- [ ] 采用插件逐项兼容实测，研究去重/补查/限流/失败及四屏设计覆盖。
- [ ] 同一候选安装/重装/升级/自定义目录/卸载保留数据/干净机/paired rollback；产物SHA与报告一致。
- [ ] 项目记录、check和handoff更新；所有未验证能力明确保留，不虚称完成。

---

## 历史执行证据（以下不是当前任务清单）

## 2026-10-08 PDF 页面绑定适配器

- 复用 `tools/verify_companion_pdf.py`、`WindowsLearningCollector`/OCR、pypdf（环境可用时）和 `ObservationBundle`，新增 `extensions/companion/pdf_learning.py`。调用必须明确绝对PDF文件和一-based当前页；只抽取该页文本，保留文件、页码、总页数及文本来源；扫描页标记 `visual-ocr-required`，不猜页码，不读取整文件替代当前视野。
- 导出 `extract_page_text` / `page_observation`，没有新增UI入口。基础 Python 缺 reportlab，夹具测试按依赖跳过；现有 Edge 两页 PDF 视觉翻页验收仍是有效证据，但适配器尚未接入实时窗口端点。
- 下一步在带 pypdf/ReportLab 的运行时执行真实文本PDF与扫描PDF测试，补可靠当前页身份，再接问答过期和同页去重。

## 2026-10-08 原浏览器辅助复用：干净视频帧

- 改造现成 browser_video_snapshot.js / browser_video.py 和既有 companion/browser-video endpoint，显式 capture_frame 可选参数，默认保持字幕读取；无新增UI入口。JPEG只来自video元素，不抓网页/弹幕DOM，最大960×540和400000 base64字符，输出预算与origin/绑定前后检查保留。
- 真实Edge生成视频证明DOM覆盖层移动/文字变化不改变JPEG，seek后的实际视频帧不同；5项Python边界测试通过。证据 E:/SumikaBuild/video-frame-20261008/companion-video-41b7f36b-e1f0-473d-b5f1-9ea3950484fe/report.json。
- 实际B站同一collector返回可读JPEG；合成DOM覆盖层移动与变化不改变输出；seek/time与无字幕不伪造正文通过。证据 E:/SumikaBuild/bilibili-clean-collector-20261008-a/report.json。此处覆盖层是测试注入，不代表真实滚动/特殊弹幕、全屏或干净帧视觉质量全部通过。
- 普通用户浏览器连续传输、弹幕独立入库/分类、OCR/模型理解、音轨媒体时钟绑定和最终打包仍未完成。不得把已有Agent Window适配宣称为任意浏览器已支持。

## 2026-10-08 SenseVoice 初始化顺序与真实 B站链路

- 复用并改造现有 application_audio_worker / SenseVoicePcmProvider 和真实 HTTP/audio/fusion 验收探针，不新增 UI。用户最新优先级明确为 B站与 PDF；微信读书暂缓。
- 首次 NumPy import 从解码线程移到 start 后，失败变为启动超时；g 栈证明主线程停在 native NumPy 初始化，单独相同解释器加载 NumPy约0.378秒、模型约1.092秒。临时将父进程期限35秒仍失败（i），已恢复原15秒，不扩大队列或期限掩盖问题。
- 将 native 模型预加载放到阻塞 stdin owner watcher 启动前，j 真实 B站产品链路通过：0–39.135秒视频、七段5秒转写、求导术语可见、融合引用、stop清除、无迟到引用、full revoke全部通过。证据 E:/SumikaBuild/bilibili-product-sensevoice-20261008-j/audio/report.json。初始化顺序与成功有关，但未证明所有Windows native loader机理；新增顺序回归断言，29项测试通过。
- 候选ASR仍未切默认或重打包。固定5秒片段有句子边界截断；没有麦克风、真实模型理解、视频时钟绑定、质量统计或延迟95分位验收。独立k重复实测也通过：39.091秒、7段转写与融合/停止/撤销（E:/SumikaBuild/bilibili-product-sensevoice-20261008-k/audio/report.json）。check、handoff与git diff --check通过，之后继续干净视频帧/弹幕分离与PDF当前页定位。


## 2026-10-08 模型参考资料去重

- 现成资产改造使用 `extensions/companion/qa.py`；融合和原始 ObservationBundle 保持原样，不新增采集服务/UI。实际 B站音轨正文同时出现在 fused text 与 application_audio metadata，导致每次问答/主动讨论重复发送。
- 问答与主动讨论共用 metadata 投影：仅当某段音轨文字已完整出现在实际预算内的参考正文时，移除 metadata 中重复 text；采集时间、source 和音轨 offset/未知播放位置保持。正文被截断导致缺少该段时不删除，避免无意丢失资料。
- 106项 fusion/contracts/scheduler/voice-answer/UI-server 回归通过，新增验证音轨只出现一次、来源保留、原始 bundle 未改变和正文截断后的信息保留。真实 B站转写重放字符差异见 `E:/SumikaBuild/companion-context-dedup-20261008/report.json`；字符减少不等于实测 token/费用节省，没有网络或模型调用。
- 当前发行候选尚未含该修改；站点/活动区域识别、局部OCR、教程ASR质量、真实连续语音/模型及完整安装/迁移回退/调研门槛继续未完成。


## 2026-10-08 产品 B站音轨融合与撤销实测

- 改造已有 `verify_bilibili_audio_live.mjs` / `verify_application_audio_live.py`，复用产品 HTTP bridge、PerceptionProcess、ApplicationAudioProcess/worker、ContextFusion 和 Z capability runtimes。独立测试目录，不修改个人配置，无模型或麦克风调用。
- 实际教程播放 0–39.129 秒，连续 WGC 首帧有效，两段真实 Vosk 转写通过进程身份校验并进入产品上下文。HTTP audio stop 后音轨引用清除，等待后无迟到引用；full revoke 后画面/音轨进程都停止，latest=None。证据：`E:/SumikaBuild/bilibili-product-audio-20261008-c/audio/report.json`。未持久化原始 PCM。
- a/b 在采集前因页面异步重写标题导致定位失败；c 在自有页面保持唯一测试标题后通过。失败记录保留。小 Vosk 首段 capture offset 20.32 秒且教程术语误识别仍未解决，不能称实时质量、模型理解、音轨隔离或完整连续语音验收通过。
- 用户提出按网站/活动类型确定注意区域与 token 预算：视频播放关注播放器和开启的弹幕，实际阅读评论才切评论；阅读按正文文字和图表组织。当前仍整窗处理。已记录下一阶段方向，未因设计问句加入 UI 或用任意截断替代区域优化。复用原接口，优先 DOM/UIA 后 OCR，保持图像坐标来源和问题绑定；精确 token/费用需真实 provider 计量。
- 扩展脚本用法：既有四参数后追加 `<product-root>` 即走产品 HTTP/worker/fusion/撤销；仅使用其中 capability runtimes，bridge 和 worker 实现来自当前源码，不代表整个 Z 包升级验收。


## 2026-10-08 真实 B 站应用音轨与本地转写

- 现成资产直接使用：`ApplicationAudioTrack`、`ProcessAudioCapture`、`ContextFusion`、Z 的 WASAPI helper/desktop Python 与 `E:/Models/Speech/sumika/vosk-model-small-cn-0.22`。新增可复用验收工具 `tools/verify_bilibili_audio_live.mjs` 与 `tools/verify_application_audio_live.py`，不增加产品入口、采集引擎或模型下载。独立测试 Edge profile 仅打开公开求导教程，不读取用户账号凭据。
- 真实 B 站视频播放 0–38.09 秒，进程级回环接收 1,204,160 bytes 16kHz mono PCM，598,941 非零采样、峰值 21,648；Vosk 产出两段教程转写，来源为 application-audio-transcript。原始音频仅内存处理，不落盘；测试结束关闭浏览器和采集器，stopped=true。证据：`E:/SumikaBuild/bilibili-audio-20261008-c/report.json`、其 `audio/report.json`。
- 首段在 capture offset 20.32 秒产出，且“求导”等术语出现明显识别错误。因此仅证明实际应用音轨→本地 ASR 链路，未达到实时学习质量或语音响应延迟目标；未证明外部进程声音隔离、麦克风打断、TTS、产品 worker/HTTP 问答融合或视频时间对齐。capture offset 不是视频播放时间。
- 前两轮工具未进入录音：浏览器标题定位未及时稳定；失败 c 前的 a/b 证据保留。修正标题定位等待和失败日志持久化后 c 通过，不将失败或重试计为实际音频成功。
- 复用：`node tools/verify_bilibili_audio_live.mjs <unique-output> <desktop-python> <process-audio-helper> <vosk-model>`，运行最长约一分钟，播放公开视频声音；仅输出文本和统计。后续优先验证更适合教程术语的 ASR 与较短分段，然后接产品 worker/问答并验收实际声音隔离。

## 2026-10-08 候选 Z 与 B 站真实页面复验

- Z 主机独立 ZIP/PowerShell 安装和 EXE 首次启动、实例复用、外来端口拒绝、受管关闭通过；归档及安装后 42,243 文件哈希一致。证据：`E:/SumikaBuild/packaged-install-4806acba70934b91b6bd717c98cd4b1e/report.json`。真实桌宠单实例、置顶/layered/排除标记、输入、拖动、84×84 收起/恢复与 API 停止通过，产品文件未变；`E:/SumikaBuild/pet-z-native-20261008-a/report.json`。排除标记检查不等于实际采集自身排除验收。未切换日用、迁移个人数据或公开发布，未证明 Inno/干净机器/覆盖升级回退。
- 基于当前源码、最新 `SumikaPet.exe`、U 候选 DSH/host runtime、OCR desktop runtime、voice runtime 和 process-audio helper 重建 `E:/SumikaBuild/product-candidate-20261008-z`。包内清单 42,243 个文件；`E:/SumikaBuild/candidate-z-capability-report.json` 探针通过，确认包内 Python、WGC、中文 OCR、Pipecat/Silero、SAPI 与 `wasapi-process-loopback` helper 可加载。该证据仍不等于真实设备采集、安装器安装/升级/回退或连续语音质量验收。
- 真实 B 站页面 `BV1Lf4y1M72V` 复验：视频可暂停，跳转到 15 秒成功；页面的 `bpx-player-subtitle-wrap` 为空，标准 TextTrack 无 cue，因此观察结果明确为 `current_subtitles_unavailable`，没有把画面或猜测伪装成字幕。证据：`E:/SumikaBuild/bilibili-dom-20261008-c/report.json`。应用音轨转写仍未接入这条真实页面链路。
- Z 的进程音频 helper 边界通过：START 前 stdin 关闭与错误进程创建身份均被拒绝，错误路径回收 job/process/reader；`E:/SumikaBuild/process-audio-boundaries-20261008-a/report.json` 明确 `actual_capture_tested=false`。角色问答、感知契约、调度、WindowsLearning/OCR、portable inventory、capability runtime 和 process-audio 合计 89 项单测通过。
- 运行 `python -X utf8 -B -m sumika_next.cli check`、`python -X utf8 -B -m sumika_next.cli handoff` 和 `git diff --check` 通过。当前计划仍未完成：连续语音/主动讨论真实设备验收、桌宠交互、安装器升级回退、DSH profile 迁移与日用切换、研究生命周期仍待完成。

## 2026-10-08 DeepSeek 真实微信读书问答与输出预算

- 复用现有 `WindowsLearningCollector`、WGC/UIA/OCR、`verify_companion_provider.py` 和 `/api/companion/ask`，没有新增产品入口或模型适配器。用户补充余额后，DeepSeek `/models` 和文字生成均可用。
- 长 OCR 上下文在 `max_tokens=1024` 时出现已计量但空正文（`prompt_tokens=4828`、`completion_tokens=1024`）；一次短文本诊断确认 provider 正常。验收工具增加显式 `--max-tokens`，配置默认和当前用户配置统一为 `4096`，避免把推理预算耗尽误判成采集失败。
- 真实微信读书当前页复验通过：WGC/UIA/OCR 采集约 1863 字符，图片保留但当前 `multimodal.enabled=false`，DeepSeek `deepseek-flash` 返回章节概括、关键概念和 OCR 纠错；总耗时 3.717 秒，计量 `prompt_tokens=4726`、`completion_tokens=488`、`total_tokens=5214`。证据：`E:/SumikaBuild/provider-weread-20261008-e/report.json`。
- 目标 Edge 窗口最小化时采集器拒绝并报告 `capture target is not a visible window`；恢复并置前后复验通过。该边界保留，避免把后台标签或不可见窗口当作当前学习内容。
- 回归：`python -X utf8 -B -m unittest tests_next.test_role_chat tests_next.test_companion_contracts tests_next.test_companion_observation_scheduler tests_next.test_companion_windows_learning tests_next.test_companion_windows_ocr`，64 项通过。仍未证明 B 站应用音轨转写、连续语音、主动讨论真实模型触发、最终安装包包含本轮改动或 DSH 日用切换。

## 2026-10-08 当前源码候选 Y

- 复用既有 `build_portable_staging.py`、U 候选中的 DSH/host runtime/桌宠宿主和本轮独立 desktop OCR、voice runtime，生成 `E:/SumikaBuild/product-candidate-20261008-y`。首次构建暴露运行时缓存 `__pycache__/*.pyc` 被发行路径规则拒绝，改造现有遍历器统一排除运行时缓存后重建成功；未删除旧候选。
- 包内能力检查通过：`E:/SumikaBuild/candidate-y-capability-report.json`。验证了包内 Python 路径、WGC/OCR、Pipecat/SAPI、process-audio helper 及依赖导入；未打开麦克风、屏幕采集或模型请求。
- Y 仍是内部候选，不代表 Inno 安装器、真实音频设备、连续语音、B 站音轨或 DSH 日用切换已通过；本轮 DeepSeek 默认预算和 OCR 改动已进入源码，但尚未发布或切换日用。

## 2026-10-08 登录完成及实际页面对应

- 用户确认两个站点已登录、微信读书已打开书。公开 B站探针继续复用 browser_video_snapshot，暂停/跳转15秒/无字幕不伪造文本三项通过；E:/SumikaBuild/bilibili-dom-20261008-b/report.json。空 bpx-player-subtitle-wrap 不算可用字幕。
- 对用户指定 Edge HWND 4983764/PID1592 进行现有 UIA+WGC 采集。首次截图实际是 B站，随后 UIA 报读书文档及另一 B站文档均 visible，不能把窗口标题当阅读正文证明。第二次窗口已最小化，WGC 正确拒绝；恢复后画面采集通过但仍无 UIA 正文。上述证据不算微信读书验收。
- 复用 WindowsLearningCollector/WindowsTextCollector 新增只读指定窗口探针 verify_companion_reader_window.py，报告明确为采集能力，不假称 reader identity 或理解验收；不导航/发送模型/写长期记忆。已请求用户保持读书页前台以验证页面对应。独立浏览器原 session26797仍保留，登录本身不再是阻碍。

## 2026-10-08 B站与微信读书实测目标

- 用户指定 B站视频与微信读书阅读作为真实验收目标，需要账号时由用户登录。复用既有 Playwright loader 与 browser_video_snapshot，只增加可复用站点探针 tools/verify_companion_sites.mjs，不新增产品页面/入口。
- 独立 Edge profile 位于 E:/SumikaBuild/learning-sites-20261008-a/profile。真实公开视频 BV1Lf4y1M72V（求导教程）加载，播放时间 4.787809/readyState 4；标准 TextTrack 无 cue，不能假称现有字幕采集支持 B站。报告 E:/SumikaBuild/learning-sites-20261008-a/report.json。
- 微信读书公开首页截图已查看，已请求用户在独立窗口登录并打开测试正文页。不读取账号凭据。当前 exec session 26797 保留浏览器供用户操作；恢复时先验证句柄/进程，不能盲目重开。无模型或麦克风调用，微信读书内容、B站字幕/音轨、完整陪学体验仍未验收。

## 2026-10-08 月度新候选与不完整搜索

- 直接改造既有 ReferenceMonitor/discoveries 表，历史推荐项目及同一响应重复条目不再占每月三个名额；URL 必须与 repository 对应的规范 HTTPS GitHub 地址一致。
- GitHub incomplete_results=true 按未完成搜索保留重试，不保存空月完成状态。新增次月推荐不同候选及不完整结果恢复断言；35 项离线 runner/monitor/analysis 测试通过。
- 没有真实搜索或模型调用，不代表搜索质量已验收。当前包尚未更新，普通浏览器/播放器与阅读器适配、真实陪学设备/模型、安装和总交付仍未完成。

## 2026-10-08 调研提醒恢复与月度候选

- 复用 ReferenceMonitor 同一 SQLite 和原 reminders 收件箱，增加报告投递账本。先保存模型结果，再投递并记状态；退出后补发未投递报告，提醒写入后退出也由唯一键去重，不重调模型。
- 月度首次到期检查使用 GitHub 搜索元数据，最多保存三个 needs-validation 候选，不修改参考清单或安装项目。首次周一10点前不运行当月发现；失败保留重试并遵守限流冷却，启动合并补查，持久候选可恢复提醒。
- 34 项本地调研测试通过，包含恢复、重复投递、月度数量/去重/失败重试和清单保留。新增搜索后早期非搜索测试意外接触 GitHub，随后添加明确离线基线，最终测试不依赖网络。搜索元数据不是源码审核或采用结论；真实搜索质量、发行生命周期、陪学主闭环及总交付仍未完成。

## 2026-10-08 调研运行生命周期

- 现成资产直接改造：ReferenceMonitor/ConfiguredReferenceAnalyzer、客户端 main、ScheduleController 和已有 reminders 表。新增 ReferenceRunner 仅连接这些组件，周一周期/启动合并补查/五次分析额度继续使用同一 SQLite ledger；没有新调度页面或注册另一条周期任务。
- 无待分析变化不创建模型适配器；禁用辅助模型保留队列并提示待核对，不启用/回退模型。相关分析与失败进入原 reminders 收件箱，键按内容去重，重试时间变化不重复提醒；不相关分析保持安静。仅在客户端 main 运行，serve 测试/嵌入不触发网络。
- 关闭停止后续采集/模型准入，当前网络响应返回后关闭并终止；已准入操作收尾后才释放客户端数据租约。异常提醒去敏，源项目不会自动安装/升级/改动。
- 30 项 runner/monitor/analysis 本地测试通过。仍缺月度发现、真实来源/服务与产品运行验收；当前包不含这些改动，完整陪学及交付门槛继续未完成。

## 2026-10-08 语音最终回复预算

- 复用现有 VoiceQuestionProvider 和先前的 turn/provenance 事件，发现最终一次性结果可绕过流式 64000 字符预算并形成过大进程消息。最终总长现使用相同限制，尾部或 final-only 内容分为最多 4096 字符片段；没有新队列或入口。
- 23 项 voice-answer/microphone-process 测试通过，新增长 final-only 内容完整性、片段上限和超限结果不进入显示/播放断言。隔离 voice-env 运行真实 Pipecat/worker/segmented/answer 套件 33 项通过；没有实际模型、麦克风或扬声器操作。
- 当前包未包含本轮变化，真实服务/设备、普通浏览器视频、阅读器、研究自动运行及最终交付仍未完成。

## 2026-10-08 语音临时回复投影

- 核对现场发现文字提问保留监听及开口取消文字已在既有 MicrophoneProcess/text_begin/text_end 中实现，未重复施工。改造现有 VoiceQuestionProvider、companion-session 记录及验证工具；沿用设计稿能力详情，没有新增入口或元素。
- 语音 delta 补充 turn，流式结束后的最终尾部文字也发给界面并保留观察来源。界面移除当前错误/打断的未完成回答，播放结束将回答确认为已完成；旧轮次事件不清除新回答，全部模型文本继续 textContent 渲染。
- 21 项 voice-answer/microphone-process 测试与 42 项浏览器断言通过，证据 E:/SumikaBuild/companion-session-ui-turns-20261008/report.json。未打开音频设备或真实模型；当前包未更新，完整陪学/视频阅读器/调研及总验收仍未完成。

## 2026-10-08 CSS 连接拒绝与监听队列

- 复用原宿主诊断与 HTTP server，opt-in CDP Network 事件只记录同源 CSS 路径、完成/错误；最多保留 64 条在途关联，不保存 URL 查询、请求正文或学习内容。编译通过（SDK 无 ExitDescription 属性，已改为现有 Reason）。
- baseline 第 1 轮真实复现 deskpet.css/layout.css 的 net::ERR_CONNECTION_REFUSED。以前串行 socket 对照不等于浏览器并发，不足以排除 backlog；现将 OwnedServer.request_queue_size 从默认 5 改为 64。没有请求重放或模型/音频调用。
- 新 bridge 下五轮原生启动均通过，40 次 CSS 网络完成且输入框可见：E:/SumikaBuild/pet-health-final-20261008-1 至 -5。旧 batch 第 5 轮因实验中 bridge 已停止而失败，该轮排除，不作为产品根因证据。
- 这是连接突发的缓解验证，有限样本不证明长期稳定性；当前发行包未更新。普通浏览器字幕/视频接入、阅读器、真实语音/模型、调研运行与总验收继续未完成。

## 2026-10-08 独立宿主样式失败定位

- 直接改造现有 PetHost opt-in 诊断，增加 Content-Type、CSSOM rules/error、link 状态和主题变量；不增加产品入口或收集学习内容。新宿主编译至 E:/SumikaBuild/pet-host-health-20261008。
- 实际复现失败：E:/SumikaBuild/pet-health-native-20261008-a/report.json。前六份 CSS 返回 200 且有规则，deskpet.css/layout.css 无成功响应事件，CSSOM SecurityError；main 仍显示且输入框在窗口外。比此前笼统“无样式”更准确：部分关键样式未生效。
- 临时扩大 HTTP 监听队列后 b/c 两轮输入、80x60 拖动、收起恢复通过，八份 CSS 正常。但对照 socket backlog=5 的 16 连接突发也通过，无法证明根因，已撤回队列改动及该回归，保留真实失败/成功和诊断工具。54 项 UI server/pet owner 测试通过；没有模型或音频采集。
- 根因仍未解决，下一步记录 WebView 网络失败代码，不能以重试成功宣称稳定启动。所有隔离宿主和 bridge 已停止；当前包不含新诊断，整体目标保持进行中。

## 2026-10-08 主动讨论文字刷新修复

- 核对现成 ContentChangeTracker、ObservationScheduler 和 WindowsLearningCollector 后，发现问答层已经忽略 text_observed_at，但主动讨论仍把这个采集时间戳计入内容摘要。相同正文持续刷新会重置稳定等待，阻止主动讨论。
- 改造既有摘要过滤，同时排除 visual_observed_at 和 text_observed_at；正文、图像、有效状态及来源元数据仍参加变化检测，不另建调度器或入口。
- 37 项 scheduler/contracts/windows_learning 回归通过；覆盖同时刷新两类时间戳后稳定内容只讨论一次，以及正文切换后重新等待并讨论。未使用真实音频或外部模型，现有发行候选不含本轮修复。普通浏览器连续视频上下文、阅读器、宿主、真实服务及调研生命周期等完整计划门槛仍未完成。

## 2026-10-08 持续选区可见范围

- 复用现有 UIA TextPatternRange 的 Clone/CompareEndpoints/MoveEndpointByRange，新增 WindowsTextCollector 可选 `visible_selection_only`。持续 WindowsLearningCollector 读取选区与当前可见范围交集，不将已滚走旧选区混入新画面；单次用户明确读取选区的行为保持。
- 9 项 text/learning 测试通过，包括部分可见选区裁剪、无交集返回无效和选中优先。实际 Edge 夹具滚至下一章节确认 SELECTED_FRAGMENT 不再进入持续选区；可见选区仍正确，原 HTTP 选区问答、UIA+WGC、隐藏内容排除和零长期记忆写入通过。
- 证据 `E:/SumikaBuild/companion-text-51c0623dc274473d81cb91a8c8ee5dc6/report.json`；没有用户页面或真实模型/音频调用。PDF UIA 正文不可用和完整播放器/真实服务/设备验收仍未完成。

## 2026-10-08 实际 PDF 阅读器边界

- 使用已启用 `sumika-office` 的 ReportLab 5.0.1 和 pypdf 6.18.1 生成、重开核对两页 PDF，仅本轮夹具文件。复用 `WindowsLearningCollector` 和实际 Edge PDF 阅读器，新增可复用验收工具 `tools/verify_companion_pdf.py`，所有产物写 E 盘。
- `E:/SumikaBuild/pdf-learning-20261008-c/report.json` 通过当前页 WGC 图像、从第 1 页切至第 2 页后图像替换。`page.png`/`page-2.png` 已查看，页码和 FIRST_PAGE_LESSON/SECOND_PAGE_LESSON 对应正确。UIA 不提供有效正文，text_status=unavailable；没有假称文字提取、页码结构化或选中片段已支持。
- 首次导航探针缺少 UIA page Edit 的失败现场保留。重新运行时控件出现并通过；工具保留仅对自有窗口 Ctrl+End 的备用导航方式，不代表所有阅读器控制兼容性。
- 没有读取用户文件、调用真实模型/网络或录音。当前只能证明 PDF 视觉回退和翻页更新，不代表电子书文字优先闭环或模型理解；仍需 reader 文本/页码接入及完整陪学验收。

## 2026-10-08 视频字幕与过期上下文

- 复用 `browser_video_snapshot.js`、`browser_video.py`、`content.video`、现有 `/api/companion/video` 和问答绑定。Edge 真实生成视频在 0.15 秒和 1.2 秒读取不同 TextTrack cue，保留 media_time_seconds；禁用字幕、多个 video、origin 变化均拒绝。
- 修复 `/api/companion/video`：有 consent 但当前 WebVTT cue 为空时仍写入 invalid observation，清除旧字幕，不让快进到无字幕区继续回答上一段内容。陪学观察的 text_observed_at 只记录来源，不再把相同正文的周期刷新误判为内容变化。
- `node tools/verify_companion_video.mjs E:/SumikaBuild` 通过，证据 `E:/SumikaBuild/companion-video-5d85b2d0-1e0b-4ee3-ae03-dba38a36c3d5/report.json`；Python 相关套件 72 项通过。仍未验证外部播放器、真实字幕质量、应用音频、物理设备或付费模型。

## 2026-10-08 Edge 教程夹具闭环

- 复用现有 `verify_companion_windows_text.py` 的隔离 Edge 教程页、UIA 正文读取、Bridge 问答和本地 fixture provider，新增 `--learning` 调用 `WindowsLearningCollector`；输出目录可用 `--output-root` 移到 E 盘。D 盘满导致的第一次报告写入失败已保留现场并修正工具，不把失败运行记为通过。
- E 盘第二次实测通过：`E:/SumikaBuild/companion-text-02d849b6d8ff43f7b4b924346a203c50/report.json`。真实 Edge HWND/PID 仅读取可见正文，折叠/屏外内容不进入上下文；合并观察同时含 WGC 图像和 document-visible 文本；选中片段问答来源绑定，未写长期记忆或角色聊天，模型调用为 0（本地 fixture HTTP provider 仅验证协议）。
- 这证明指定教程网页的文字问答闭环和安全边界，不证明真实浏览器账户、视频播放器、电子书、付费模型质量、应用音轨或物理设备。下一步补视频字幕/时间锚点与电子书夹具，再做真实服务/设备验收。

## 2026-10-08 文字优先陪学观察

- 现成资产判定：直接组合 `WindowsTextCollector`、`WindowsVisualCollector`、`PerceptionService`，没有另写截图或 UIA 引擎。`WindowsLearningCollector` 对指定 HWND/PID 先读取选中片段，再读取可见正文；WGC 图像始终保留为图表/公式视觉补充。
- UIA 暂不可用时保留有效画面并标记 `text_status=unavailable`；窗口身份变化、文本目标不一致或旧内容不再属于所选窗口时，返回无效 bundle 且清除文本和图像，避免过期回答。worker 改用此 collector，仍输出原有 `window-visual` 来源，兼容 PerceptionService 契约。
- 16 项相关测试（平台跳过 1 项）和 39 项浏览器检查通过。没有真实浏览器/播放器/电子书、麦克风/应用音轨或模型请求；视频字幕/时间定位、主动讨论、真实问答延迟仍待验收。

## 2026-10-08 调研补丁证据

- 直接改造现有 GitHub compare 解析，保存关注文件的 `patch`；重命名前路径匹配也保留新路径补丁。总补丁限制 12000 UTF8 字节，截断保持合法 Unicode，单独标记 patch_truncated 和 missing_patches。不相关补丁不保存，不增加网络请求或自动工具执行。
- 现有辅助模型提示改为分析提供的 diff 和路径，要求解释借鉴模块/限制，缺失或截断时不可补推未见实现；证据仍是不可信数据，不形成执行授权。保持提交、compare URL 与已知路径作为来源。
- 24 项 monitor/analysis 回归通过，覆盖重命名、无关文件排除、缺失补丁、Unicode 总预算与截断。无网络/真实模型调用；X 包早于本轮变化。周期生命周期、报告通知、月度发现以及最高优先级真实陪学、音轨/语音延迟仍未完成。

## 2026-10-08 调研配置模型与用量

- 改造现成 `extensions/models/auxiliary.py` 请求路径，新增 `ConfiguredReferenceAnalyzer` 外围适配和 CLI 显式 `--analyze`。不启用禁用模型、不改配置、不回退 provider；构造及每次调用复核启用状态。结果进入既有持久分析领取流程。
- 复用 `UsageStore`、`usage_counts` 和已配置角色数据库，在 reference-research session 记录用量；缺失计数记 unknown/NULL，不估为零。连接使用 closing 明确释放，避免 Windows 文件锁。截断/无效模型结果拒绝，失败由分析 ledger 记录且不自动重放。
- 当前证据只有提交/路径，提示明确不属于源码审查，不得据此宣称兼容或执行；用户 payload 为不可信证据，不能成为指令授权。仍需真正源码 diff 和模块语义核对。
- 23 项 analysis/monitor 本地测试通过，未触网或调用真实模型。X 包不含本轮适配；原生生命周期、通知、月度发现尚未接通，完整陪学和真实设备验收继续优先。

## 2026-10-08 调研分析执行记录

- 改造同一 `ReferenceMonitor`/SQLite，新增 analyses ledger 与注入 analyzer 接口。BEGIN IMMEDIATE 领取候选并先记 started，再调用模型适配器；同一周期最多五次尝试，并发与重启共享配额。已开始而未收尾的调用不自动重放，正常失败记 needs-attention，不记录 provider 可能包含秘密的异常正文。
- 成功报告仅接受 classification/summary/modules，分类为 worth-borrowing、needs-validation、unrelated，附确定性 compare URL 与版本作为来源。没有自动安装/升级/执行通道。空队列零调用；历史结果持久可查。
- 20 项本地 reference monitor 测试通过，覆盖跨进程状态、并发配额、重启、异常/中断不重放、非法额外字段拒绝、通用错误去敏。未调用真实模型/网络；配置 provider、用量、通知、周期生命周期和月度发现仍未接通，X 包不含新 ledger 实现。

## 2026-10-08 参考清单发行资源与路径

- 直接改造现成 builder/CLI，发行清单从唯一源码 `docs/project/reference-projects.json` 精确复制到 `extensions/desktop/reference-projects.json`，不新增仓库内平行清单。builder 检查物理文件和基本 schema，资源经过现有路径/哈希清单。
- CLI 默认基于自身产品根找源码或包内清单，默认数据库使用既有 `user_data_directory()`，保留显式隔离参数。`--pending` 只读待分析证据，不调用检查/模型/网络；从 `E:/SumikaBuild` 工作目录运行源码 CLI 验证通过。
- 30 项 reference/inventory 回归通过；覆盖重定位、错误 schema、个人数据路径和离线无网络。X 构建 42184 文件清单通过；包内清单和源码 SHA256 同为 `14d5f0b277b6f4b7f90dd952971288780c788098dd9cf9389fb9148214a8a9f3`。从 `E:/SumikaBuild` 用 X 包内 Python 运行 `tools/check_reference_projects.py --pending --database E:/SumikaBuild/reference-x-offline-20261008/reference-projects.sqlite3` 通过，不触网/模型。自动调度、月度发现、模型分析和通知仍未接通，完整陪学与真实设备验收仍未完成；X 安装未验收。

## 2026-10-08 参考项目变更筛选

- 直接扩展现成 `reference-projects.json`、`ReferenceMonitor` 和同一 SQLite，不新增调度或入口。NEKO/Pipecat 关注路径来自已有源码核对；其余未配置路径的项目保守标记 needs-validation，不虚构已核对模块。
- 提交改变时调用 GitHub compare，记录变更路径、重命名前路径及来源 URL。300 文件截断、非 ahead/identical 或未配置范围不能判为无关。比较失败保存旧基线，后续可重试同一变化；相关候选持久保存在 reviews 表，每次最多返回五项，未到检查周期仍可读取未分析队列。未实现自动消费或模型分析。
- 14 项本地夹具通过，新增相关路径、重命名、无关文件、截断保守处理、比较失败基线、无变化不比较及队列持久性；没有网络或模型请求。原生周期触发、月度发现、模型深入分析和提醒仍待实现。W 包未含本次修改，且打包器当前未收录参考清单，生命周期接通前需补齐。

## 2026-10-08 W 候选宿主验证

- 复用现有打包器和固定 runtimes，将当前原生拖动/收起宿主加入 `E:/SumikaBuild/product-candidate-20261008-w`，42183 文件完整性通过。宿主新增 opt-in CSS 响应状态诊断；两轮观察到全部样式返回 200，但间歇失败原因仍未确认。
- 真实键盘输入且不拖动窗口通过。包内认证 API 单实例、输入、80×60 拖动、84×84 收起/恢复、停止回收和运行前后清单通过：`E:/SumikaBuild/pet-w-native-20261008-b/report.json`。实际能力页唯一入口及启停通过：`E:/SumikaBuild/pet-w-capability-ui/report.json`。
- UIA Image 不一定存在于 VRM 视图，验收工具允许使用 composer 上方角色视口；首轮因此失败，不能算产品失败已修复。最后调整的探针晚于 W 构建。原生验收未调用模型、麦克风或学习内容采集。
- 隔离 ZIP/PowerShell 安装验收通过：`E:/SumikaBuild/packaged-install-460a4b97bd9f458987567d37f7102df3/report.json`，归档字节、安装后 42183 文件、EXE 首次/复用/端口保护/关闭通过。W 尚无 Inno 安装器或日用切换，完整计划仍未完成。

## 2026-10-08 原生桌宠收起

- 资产判定：复用设计稿已有 `dp-mini` 恢复按钮和 WPF 宿主，不另造浮动控件。桌宠宿主模式默认展开；收起后只保留恢复按钮，消息严格限制为 `sumika:compact`/`sumika:expand`，原生窗口保持右下角。
- 39 项浏览器断言通过；实际发布宿主通过拖动、收起到 84×84、点击恢复到 510×645：`E:/SumikaBuild/pet-compact-native-20261008-a/report.json`。截图 `pet-compact.png` 已查看，收起态无重叠。
- 旧 V 包不含本轮修改，尚未重建当前产品候选或做安装验收。间歇无样式加载已增加投影视图/资源诊断，仍未形成稳定性结论；点击穿透、真实学习问答、音频隔离及完整安装回退仍待完成。

## 2026-10-08 原生桌宠拖动

- 现成资产：直接改造设计稿角色拖动及 `ui/app/index.html` 同一处理器、既有 WPF/WebView2 宿主和验收工具；不新增产品入口。独立宿主不再移动页内元素，严格同源字符串消息交给原生 caption drag，使用实际光标屏幕坐标。alpha=1 背景保留透明窗口鼠标命中。
- 35 项浏览器断言和真实发布宿主拖动通过：`E:/SumikaBuild/pet-drag-native-20261008-m/report.json`，实际移动预期 80×60 像素，截图排除/置顶/分层/可见输入通过。宿主产物 `E:/SumikaBuild/pet-host-20261008-drag/SumikaPet.exe`；V 包未包含。
- 探针问题：pywinauto move 无 duration 参数；release 默认坐标会把光标移到原点，必须指定终点。截图排除导致截图得到背后内容，不能作为桌宠视觉证据，且外部进程不能修改宿主 display affinity。失败现场保留。
- 间歇加载失败的 UIA 证据出现完整但无样式的页面，不能继续只归因加载慢；增加 opt-in `SUMIKA_PET_DIAGNOSTICS` 阶段/投影视图日志，未记录页面学习内容。重试成功不代表问题解决。实际输入/收起/穿透、真实学习和音轨验收仍未完成。临时 bridge 和宿主已关闭。

本记录执行用户 2026-10-07 的完整批准计划；不替代原需求和既有阶段记录。

## 2026-10-08 桌宠屏幕文字问答接线

- 复用设计稿及现有 `index.html` 桌宠输入/气泡，不新增输入或导航；新 `companion-text.js` 是bridgeFetch/NDJSON的客户端适配，发送时读取真实capture状态。无采集时返回普通角色聊天；状态未知、目标切换或问答失败不得发送普通角色备用请求。
- companion_ask新增expected_target，可复核所选HWND/PID与当前观察并绑定问题；使用已有临时问答history，不写普通角色会话历史或长期记忆。流式解析包含回复预算、结束事件和错误状态检查，模型文本用textContent。
- 当前文本问答优先停止mic worker以结束自主语音/播放，但保留画面采集；连续监听不能自动恢复，需停止本次陪学后重新开始。这是待完善限制，不能宣称语音/文字已无缝切换。
- 19项独立浏览器协议检查通过；三个非module内联script已通过vm语法检查。实际桌宠组件/独立宿主输入和完整工作流仍需验收，独立宿主目前输入显示限制仍待修复。
- `python -X utf8 -B -m unittest tests_next.test_ui_server tests_next.test_companion_contracts`：68项通过，含目标变化拒绝、问题binding以及文本提问前停止语音owner。

## 2026-10-08 应用音轨授权控件与状态锁顺序

- 现成资产直接复用ApplicationAudioProcess、现有窗口选择/进程创建时间和陪学详情；先补ui-design-coverage后添加默认关闭应用声音checkbox，不新增导航。开始确认区分画面、应用音轨和麦克风，所选应用转写仅为上下文，不作为用户提问。
- 连续画面首帧就绪后，单独consent/PID/creation启动应用音轨，再开始mic；应用音轨失败不得继续mic准入，保留已开始画面的停止恢复。状态返回实际capture/application_audio，stop统一revoke，已运行时冻结采集范围。
- 状态接口先读取mic/perception/application_audio锁，再取得voice event锁，避免事件callback与感知锁形成循环等待；新增并发callback回归验证。
- `node tools/verify_companion_session_ui.mjs` 17项通过，截图/report位于E:/SumikaBuild/companion-session-ui，已查看窄截图；base运行UI/application/fusion共62项通过，追加锁顺序1项通过。没有打开实际音频或付费模型；真实音轨隔离/准确率不在这些夹具的证据范围。
- 仍需桌宠文字问答/气泡、其他采集范围、完整客户端和硬件工作流、新包与reference自动化；整体目标未完成。

## 2026-10-08 窗口选择与画面采集范围

- 复用windows_capture._identity桌宠标记/可见HWND/PID校验和process_identity创建时间；新增只读EnumWindows适配，不调用截图/录音。列表限256窗、标题1024字符，本机只读探针6窗身份完整，无标题输出。
- 同一语音详情加入学习窗口select；开始确认包含目标标题、画面发送角色模型及麦克风/播放范围，应用音轨默认不采集。开始等待连续感知首帧再启用mic，不调用会停止连续感知的一次性capture。停止统一revoke全部采集。
- 正在采集时禁止换目标/重复start，启动中途结果未知保留stop。后端start复核正数HWND/PID、可见性/排除标记及提供的process_creation。
- 48项window/UI后端测试通过；10项独立Playwright检查和窄/桌面截图通过，窄截图已查看。仍缺应用音轨授权、桌宠文字问答/气泡、区域/前台跟随和真实客户端工作流；未打开真实音频设备，整体计划未完成。

## 2026-10-08 语音详情陪学会话控件

- 资产定位：四屏设计 `ui/prototype-d/index.html` 的能力详情，既有 `ui/app/management.js` 的语音交互唯一入口；改造复用该表单，不新增导航或平行配置页。补入覆盖表后实现 `companion-session.js`，图标直接复用已有Lucide资产。
- 控件提供真实status/start/stop、主动讨论开关及临时转写/流式文字；状态游标去重、12段/单回答64KB限制，模型文本只经textContent渲染。未知写入结果禁止新start并保留stop/refresh；无自动重试，旧poll不覆盖新操作，poll不重叠。
- `node tools/verify_companion_session_ui.mjs`：9项通过，截图及report在 `E:/SumikaBuild/companion-session-ui`，已查看窄窗口截图。验证不接真实麦克风/模型，也不改变日用配置。
- 尚缺目标选择器、采集范围/应用音轨控件、桌宠文字问答/气泡和完整客户端四屏验收；当前单个会话控件不代表用户已能完整陪学。整体计划未完成。

## 2026-10-08 主动会话端到端夹具与错误分级

- 在 `run_session` 内使用真实Pipecat worker、ObservationScheduler和分段播放器夹具推进时间到121秒，主动讨论共享同一播放/取消路径；撤销控制后麦克风、播放和问答历史全部清理。
- 单轮模型/播放异常发出 `error` 且 `fatal=false`，父进程保留监听；配置、管道、角色或worker异常使用 `fatal=true` 并回收整个ChildJob。事件协议涵盖主动开始、分段播放、打断和错误。
- 23项隔离microphone/Pipecat/session测试与7项microphone process测试通过；未打开真实设备或付费服务。错误分类仍需结合具体provider行为完善，客户端尚未消费事件。

## 2026-10-08 主动讨论接入语音worker

- 直接复用现有ObservationScheduler、Pipecat turn与VoiceQuestionProvider；scheduler在隔离microphone worker内读取同一最新观察，不新增采集或后台模型线程。默认初始安静120秒、最小120秒间隔、3秒内容稳定；用户可关闭或设置更长间隔。
- 主动讨论通过同一turn.start_discussion和取消/流式播放，用户开口优先打断；用户ASR/模型/播放期间通过busy延后后台分析。语音主动提示不执行ASR，并以record_history=False调用同一问答服务，不能把自动提示写成用户提问。
- 视觉refresh timestamp不再参与ContentChangeTracker内容摘要，避免静态融合刷新不断重置稳定计时。真正的图片/文本/目标变化仍参与摘要；动画和视频帧变化语义需进一步工作流验证。
- 59项voice/QA/scheduler测试通过；追加主动模式校验后8项microphone worker测试通过。夹具使用真实Pipecat框架与替代ASR/player，不打开设备或外部模型。
- 尚待worker完整调度/撤销压力、客户端UI/设计覆盖、真实音轨隔离/语音质量/延迟、当前源码重打包与总验收。整体目标未完成，未切换日用或公开发布。

## 2026-10-08 语音播放门控与目标失效

- 现成资产复用：Pipecat 的 `CompanionTurnProcessor`、`SegmentedPlayback` 和既有 `ObservationScheduler.voice_event`；只补事件协议，不另建播放队列或调度器。
- 每次打断发出旧 turn 的 `interrupted`，调度器解除对应播放门控；分段播放事件 (`segment_started`/`segment_ended`) 已纳入父进程有界协议，旧事件不能覆盖新一轮。
- worker 收到无效观察或目标变化立即终止，拒绝后续有效观察覆盖；Bridge 在目标切换/无效观察时递增麦克风代际，使阻塞设置检查无法启动旧目标进程。
- 验证：voice runtime 运行 37 项 Pipecat/调度/回答/分段回归；base runtime 运行 50 项 UI/父进程测试，均通过。没有真实设备、外部模型或最终客户端验证。
- 下一步：把现有 scheduler 实例传入产品 worker，补设计覆盖后的 UI 事件消费，再做实际工作流、安装包和最终验收。

## 2026-10-08 连续麦克风 Bridge 接线

- 资产复用：改造既有 `ui/server.py` 的Bridge/应用音轨/撤销HTTP路径，直接使用 `MicrophoneProcess`、角色配置和CapabilityStore；不新增产品导航或第二个能力管理入口。
- 新增 `/api/companion/microphone` start/status/pause/stop，双重会话许可、当前有效观察、三项能力快照及配置；读取设置前捕获准入token，撤销后旧检查不能启动worker。start先释放原有单次录音/播放owner，减少设备和声音竞争。
- 视觉和应用声音通过同一ContextFusion更新到worker；停止应用音轨后更新为纯视觉，避免语音模型继续使用旧教程转写。状态附64条有界临时事件及递增cursor；显式stop/revoke清空队列，不写长期角色记忆。
- 麦克风stop/status不等待chat lock；revoke、感知start/pause/stop、语音设置/能力变化及shutdown会关闭mic job。collector清理时在context lock外停止，避免锁内join阻塞管道消费。
- 初轮49项UI/父进程测试通过，含HTTP双重许可、撤销期间设置检查、融合内容传递和游标过滤。设备和付费模型未开启；UI事件消费与主动讨论scheduler仍待接入，整体计划未完成。
- 最终回归 `python -X utf8 -B -m unittest tests_next.test_ui_server tests_next.test_microphone_process tests_next.test_application_audio_process tests_next.test_context_fusion tests_next.test_ui_management`：79项通过；新增模型持锁期间麦克风stop HTTP断言通过。

## 2026-10-08 连续麦克风 worker 与父进程托管

- 现成资产：直接复用 `pipecat_voice.py`、Vosk、`DirectSapiPlayback`、角色问答与流式播放；改造后使用 `application_audio_process.py` 的 ChildJob/准入代际/握手范式。新 `microphone_process.py` 是独立音轨的适配器，不新增另一套语音引擎或界面入口。
- `microphone_worker.py` 在隔离 voice runtime 中检查独立麦克风/播放许可、设置快照、角色和所选能力；PCM不出进程，只传文本与生命周期事件。模型加载期间已读取停止控制；构建失败关闭播放宿主，加载期间撤销后不开设备。
- `MicrophoneProcess` 在配置发送前归属 ChildJob；8MB控制包、80KB事件上限、最新观察邮箱，停止递增代际并关闭整个进程组。启动握手可被撤销打断，切换目标或无效内容停止会话；写管道不持有状态锁，防止消费者堵塞阻碍撤销。
- 验证：隔离voice解释器运行 `tests_next.test_microphone_worker tests_next.test_companion_pipecat`，10项通过；base解释器运行 `tests_next.test_microphone_process`，5项通过，含真实子进程管道。没有打开麦克风、扬声器或付费模型。
- 待做：父服务与bridge/融合观察/主动讨论播放门控接线、设计覆盖后的UI、实际音轨与连续语音验收、最新源码重打包。候选R不包含本次源码，整体计划未完成。
- 扩展回归：base解释器运行 `tests_next.test_microphone_process tests_next.test_application_audio_process tests_next.test_application_audio tests_next.test_context_fusion tests_next.test_process_audio tests_next.test_companion_audio_providers tests_next.test_ui_server tests_next.test_companion_contracts tests_next.test_model_cancellation`，97项通过。

## 2026-10-08 bridge准入与worker回收

- ApplicationAudioProcess新增admission epoch：bridge在读取设置/能力前取得token，撤销/停止会递增epoch；检查完成后start再次核对，旧请求不能spawn、写配置或等待握手。HTTP夹具在阻塞设置检查期间撤销，确认没有Popen。
- reader/stop异常路径改为先关闭ChildJob并回收worker及其native helper，再报告context清理错误；malformed output、clear callback异常、延迟握手和重复stop都有测试。不会留下独立采集子进程。
- 相关音轨、融合、UI、模型回归共92项通过；未启用实际音频设备、麦克风或付费模型。连续麦克风服务/UI、真实应用音轨隔离、最终候选/安装器仍未完成。

## 2026-10-08 音轨启动撤销竞争与融合时间戳

- 复用ApplicationAudioProcess epoch/ready事件，stop先递增代际、清上下文并唤醒启动握手，随后等待生命周期收尾。启动前flight、发送配置前、握手后均核对代际；被撤销启动不成功返回或发送新采集配置。
- 真实子进程夹具延迟握手验证stop不等待15秒启动timeout且job/child被回收；preflight期间撤销验证Popen未调用。没有打开实际音频设备。
- 发现融合visual_observed_at每次刷新改变导致问答代际被误取消，qa内容metadata比较排除此来源时间字段，其他metadata变化继续失效。统一bridge融合发布时处理音轨/画面时间先后，真实视觉时间保留metadata；音轨TTL过期后画面不会因旧融合时间戳被拒绝。
- 88项音轨/融合/UI/模型回归通过；含静态视觉刷新保留绑定、音轨过期接受较早视觉采集时间。仍需bridge进入manager之前的撤销竞争、worker失败回收强化，以及产品连续麦克风/设计UI/真实工作流/安装器验收。candidate R不含本次改动，整体目标继续进行。

## 2026-10-08 运行中ASR能力复核

- 改造既有application worker/process/bridge配置，沿用CapabilityStore：父端和worker核对启动选定Vosk条目，开始前/开始后/输出转写前/100ms循环复核完整条目；禁用、删除或options/provider变化失败关闭，不自动fallback。应用声音许可与麦克风授权保持独立。
- bridge既有stop_speech路径增加音轨停止，语音设置/角色改变与能力启停沿用原停止逻辑。不新增入口，也不使用网页内容授权或指令。
- 真实SQLite修改加夹具track验证运行中禁用与配置改变，均停止采集，迟到转写不进入stdout；84项音轨/融合/UI/模型回归通过，speech-stop追加后8项focused验证通过。没有启用硬件录音或模型付费请求。
- 仍需start/revoke竞争与融合时间戳/错误回收强化、连续麦克风服务/UI和真实工作流。candidate R不含这些后续改动；整体计划未完成。

## 2026-10-08 音画参考融合与后端接线

- 复用ObservationBundle/现有问答代际/隔离ApplicationAudioProcess，新增短期ContextFusion：保留视觉source/image与视频时间，最多12段/6000字符/120秒应用转写作为参考附加；采集偏移独立metadata，不冒充播放时间。不做长期记忆或用户问句推断。
- bridge后端`/api/companion/audio`start/status/stop/pause接线，start要求单独consent、匹配已观察window-visual进程、已启用Vosk ASR和配置模型；在voice解释器运行，不导入基础环境Vosk。没有新增UI入口。status/stop/pause绕过chat锁，shutdown/revoke/感知暂停停止清理音轨。
- 回归发现失败采集只清问答、未清fusion，导致旧资料被下一问恢复；已统一失败代际清理并让browser-video走同一融合入口。停止音轨保留视觉而撤销旧融合回答；切换目标/视频时间/无效画面清音轨引用，迟到视觉观察拒绝。
- 82项base解释器相关测试通过；isolated voice开发环境同组81通过/1调度错误（缺tzdata），不是全绿。新增融合与HTTP许可/目标检查，模型锁占用时音轨status/stop测试通过。未创建设备录音器或调用真实模型；candidate R不含本轮改动。
- 仍需采集中ASR capability复核、start/revoke竞争及融合时间戳强化；麦克风连续服务/UI、实际音轨隔离、完整陪学与最终安装器未完成。整体目标继续进行。

## 2026-10-08 应用转写隔离worker

- 原拟直接把ApplicationAudioTrack导入bridge，但包内基础Python不带Vosk且与WGC/ONNX混用存在native依赖风险，因此本轮撤回自己新增的直接bridge接线。45项UI/track/helper回归通过不作为产品音轨可用证据。
- 复用既有感知worker/ChildJob/能力解释器发现模式，新增application_audio_worker和ApplicationAudioProcess：固定voice环境、父job分配后stdin发送有界配置、worker独立拥有native helper、只回传转写ObservationBundle，PID/创建身份/来源/目标不匹配即错误并清上下文。stdin EOF/stop关闭，未写原始PCM到磁盘。
- 14项worker/track/helper测试通过，含真实子进程管道启动握手、停止等待、job回收；Vosk/采集器仍为夹具，不触及设备。源码尚未进入候选R。
- 下一步bridge应调用管理器而非本进程加载模型；须检查已选择ASR capability和单独应用音轨许可、无chat锁撤销、视觉/音轨上下文融合与真实工作流。还没有交付新增UI或声称产品完整可用，整体目标保持进行中。

## 2026-10-08 独立应用转写音轨适配

- 改造现成`VoskPcmProvider`提取共享模型加载，新增`ApplicationAudioTrack`整合既有`ProcessAudioCapture`，使用独立KaldiRecognizer，不进入麦克风提问/角色答复管线。没有另写识别引擎、自动下载模型或替换用户服务。
- 16kHz mono PCM按最多8000bytes native调用处理，约30秒final/reset，语音终点产出`application-audio-transcript`来源ObservationBundle；记录进程创建身份及capture offset。media_time_seconds保持unknown：采集偏移不是视频播放时间。原始PCM不保留/不落盘，停止丢弃未完成句子与迟到native结果；重启独立recognizer及零偏移。
- 4项转写夹具验证片段边界PCM不丢失、来源定位、停止native调用期间拒绝迟到文本、重启/启动失败清理。13模块85项回归通过。真实中文Vosk小模型1秒内存静音与reset通过，没有打开设备，不证明识别质量。
- 模块目前仅通过callback连接采集器和转写，尚未接客户端service/bridge，也未融合视觉上下文或真实视频时间；候选R不含本轮适配。下一步受管独立语音/应用worker与bridge接线，后续UI、真实工作流和最终安装验收仍未完成。

## 2026-10-08 候选R进程音轨运行时

- 改造既有staging builder增加`--process-audio-helper`，收录独立exe和NAudio MIT notice；共享runtime resolver定位包内`runtime/process-audio/SumikaProcessAudio.exe`，显式无效override拒绝fallback。许可证依据沿用已核对NAudio root LICENSE。
- 候选`E:/SumikaBuild/product-candidate-20261008-r`包含本轮前语音流式/取消源码及native helper，42169文件inventory通过。23项路径/管道/inventory回归通过。
- `tools.verify_capability_package --require-process-audio`报告`E:/SumikaBuild/candidate-r-capability-report.json`passed，三个包内解释器导入/模型加载与helper包内发现、OS capability通过；不打开音频设备。
- 使用R包内隔离Python执行native边界工具，报告`E:/SumikaBuild/candidate-r-process-audio-boundaries.json`，仅验证无START与错误FILETIME拒绝及job回收。不是实际录音、应用隔离或UI/安装器验收。后续文档更新不在R清单里，下次最终构建纳入。
- 修正packaging/README将旧K标为历史验收，新增helper构建/打包/探针说明。产品应用转写、受管语音服务/UI、真实音画与桌宠交互及最终安装包仍未完成；整体goal保持进行中。

## 2026-10-08 进程音轨成熟实现核验

- 资产复核：soundcard端点实现和WinRT AudioGraph均不适用进程隔离；微软ApplicationLoopback示例提供准确API/系统要求，NAudio已有成熟WithProcessLoopback。直接依赖固定NAudio.Wasapi 3.1.0，不另写COM捕获实现。源码与许可证依据已记reference-projects.json，缓存放E盘。
- NuGet 22.0.0未提供WasapiRecorderBuilder，编译失败；3.1.0编译通过，版本锁保存在native/ProcessAudio/packages.lock.json。上游HEAD与发布包不同，不沿用HEAD作为发布API证据。
- 新native helper使用目标PID及进程创建FILETIME、include process tree、16kHz mono PCM；先等stdin START，宿主ChildJob分配后才发送；原始音频仅有界内存/pipe，无WAV文件。stdin关闭/目标结束停止；队列满明确失败，不改用端点捕获。Python桥仍为初版，诊断/生命周期/产品音轨接入待补。
- `dotnet build extensions/desktop/native/ProcessAudio/ProcessAudio.csproj -c Release --artifacts-path E:/SumikaBuild/process-audio-artifacts -p:RestoreLockedMode=true`通过；helper `--probe`报告系统支持。5项Python adapter/旧端点测试通过。探针未创建录音器；未采集或播放真实硬件，不能称音轨隔离已验收。
- 后续需验证真实受管采集、浏览器音频子进程归属、打断/EOF/背压回收，再接应用ASR独立轨与产品服务。新helper尚未打包，完整目标继续进行。
- helper生命周期加固：Python `start()`等待`started`握手（PID、创建时间、16kHz/mono/16-bit、process isolation全匹配），同时读取stderr诊断；错误、EOF、错误目标、重复停止和ChildJob回收均有夹具证据。原生helper二进制在`E:/SumikaBuild/process-audio-helper-20261008/SumikaProcessAudio.exe`，边界报告`E:/SumikaBuild/process-audio-boundaries-20261008.json`，未复制到D盘。
- `tools/verify_process_audio_boundaries.py`只验证拒绝路径：关闭stdin不发送START、错误创建时间均在创建WASAPI recorder前拒绝；报告明确`actual_capture_tested=false`。12项音频相关测试通过。真正采集仍按硬件授权约定暂缓，helper尚未进入候选Q或安装器。

## 2026-10-08 流式文字到分段语音

- 后续核验发现：播放阻塞会暂停async generator读取，因此模型失败不能只由下一次读取通知。新增`VoiceQuestionProvider.answer_and_play`并发监控生成失败，取消并等待当前播放任务；study worker改用此路径。
- `CompanionQuestionService.watch_binding`使用独立取消token监控屏幕代际，生命周期延续至播报结束。模型请求完成并移除active request后，撤销许可/内容变化仍取消播报；结束清理watcher，不延长画面保存或写入长期记忆。
- 新增真实Pipecat PipelineWorker接线测试（ASR/播放为夹具，不开设备）：首句早于模型完成播放，再次开口实际取消模型线程和播放器，stream delta在宿主循环，历史为空。另验证播放中模型断流和模型完成后撤销许可。11模块组合76项通过；产品服务/UI、进程音轨、硬件与最终安装包仍待完成。

- 现成资产改造：`VoiceQuestionProvider`、`SegmentedPlayback`、Pipecat study worker；直接复用现有问答绑定、取消token、受管SAPI播放器。未新增界面入口或另建语音框架。
- 模型线程增量经16项有界队列投递宿主事件循环，每项最多4096字符，回答缓冲最多64000字符。完整句子或180字符上限触发播放；第一句不再等待整段回答完成。无增量provider仍在最终返回时播放，不自动切换provider。
- 播放背压时取消会终止模型调用并解除线程等待；流错误清理播放器、关闭生成器，未完成尾句不播放；最终文本与增量不一致明确失败。已播出的内容不能撤回，后续失效会停止剩余内容。stream模式的on_delta回调在宿主事件循环执行，原answer模式仍在模型线程执行。
- 隔离voice环境运行11个相关unittest模块，73项通过；新增首句早于模型完成、队列满时取消并拒绝历史提交、失败尾句丢弃三项回归。没有打开麦克风/扬声器或调用真实付费模型。
- 可选Pipecat study worker已使用该流式路径；产品bridge/独立语音服务/UI仍未接通，进程WASAPI音轨未实现，候选Q不含本次源码。整体目标仍进行中，下一步受管语音服务生命周期与产品接线，再完成真实工作流/安装包验收。

## 完成条件与顺序

1. 保存已有工作，纠正旧事实；隔离安装并验收 DSH `0.2.0-rc.2`，通过后切换运行时和配置。回退同时恢复对应旧配置，不能降级打开迁移后的配置。
2. 对照 `ui/prototype-d/index.html` 四屏完成 UI 验收，保留原生能力和单一入口，补桌宠观察目标、采集状态及暂停设计，再改产品。
3. 先指定内容文字问答，再连续语音和主动讨论。独立 `PerceptionService` 与 `ObservationBundle`；时间、来源、目标、有效状态绑定到提问。页面内容是数据，不是指令或授权。
4. 扩展现有 .NET 启动器：WPF/WebView2、现有 VRM、透明置顶拖动、点击穿透、收起；复用角色会话和记忆。Windows Graphics Capture 与进程级 WASAPI 分别采集画面和应用声音，麦克风独立。
5. 复用已配置服务及 Pipecat 管线，VAD → ASR → 视觉/角色模型 → TTS；流式文字、分段播放、开口取消旧回复和播放。应用声音不能当用户提问。
6. 默认指定窗口/区域；前台跟随主动开启。开始显示采集范围；暂停/撤销立即停止。正文/选择、字幕/时间/转写、电子书当前页优先，图像补充。游戏仅画面问答。
7. 主动讨论以章节结束、暂停、内容明显变化为触发；用户安静设置优先，默认发言间隔至少两分钟。本地检测约 1Hz，主动模型分析最多两次/分钟，无新内容不调用，后台仅保留最新待处理。
8. 不设月费用上限；复用用量，增加音频时长及视觉调用，有价格才估算，未知不记零。原始音画短期内存缓冲；保存笔记带来源，屏幕内容不自动进入长期角色记忆。
9. 唯一参考清单 `reference-projects.json`：NEKO、AIRI、Open-LLM-VTuber、Pipecat、LiveKit Agents、Gemini Live Console、DeepTutor、Page Assist、Windrecorder、screenpipe、DSH、ZCode、Codex、CUA；记录核对版本、日期、许可证、源码、模块和限制。NEKO 优先查触发/播放/上下文，screenpipe 首轮仅架构参考。
10. 文字闭环后接新版 DSH 原生自动化及独立 research runner；现有 SQLite 去重及启动合并补查。每周一 10:00 Asia/Shanghai；每月第一轮找新项目；每轮深入最多五项，每月新候选最多三个。确定性比较后才调用模型，无变化保持安静；相关更新/失败走既有任务渠道，只建议，不自动安装升级修改。
11. 验收底座生命周期/P2/连续性/角色/调度/Web；插件安装启停卸载、配置保留和不兼容拒绝；四屏窄窗缩放主题弹窗、资源完整、安装升级回退；网页、字幕/无字幕视频、电子书，切换/遮挡/跳章/快进/黑帧/过期回复和自身排除；语音打断、音轨隔离、断网恢复。真实服务目标停顿约三秒开始回复，95% 六秒内，实测判定。
12. 交付安装包、插件结果、设计覆盖表、陪学实测、参考清单、回退说明；本地夹具与真实硬件/模型证据分开，未验证不称完成。更新原记录，运行 check/handoff。不包含公开发布、推送或对外发送。

插件沿用 DSH 原生管理和版本检查，不增加市场或不兼容豁免。依赖服务/设备/模型的插件必须实际验证；旧 API/UI 插槽需要适配。`0.2.1-alpha.1` 仅观察。

## 现成资产判定（实施前）

| 资产 | 处理 |
| --- | --- |
| `packaging/Program.cs`、`Sumika.Launcher.csproj`、`Sumika.iss` | 改造启动器和安装器 |
| `ui/prototype-d/index.html` 桌宠预留、`ui/app/`、`ui/vendor/sumika-vrm-viewer.js` | 改造后使用，逐屏比对 |
| `extensions/roles/chat.py`、`realtime_voice.py`、`speech_input.py`、`speech_playback.py` | 复用角色、状态和语音能力，补真实连续管线 |
| `extensions/desktop/capture.py`、`perception.py`、`translation_pipeline.py` | 保留单次采集；新连续服务复用有效性判断，矩形截图不适合叠层隔离，改 Windows 适配 |
| `extensions/models/cloud.py`、用量与设置 | 改造后使用，保留语言与无自动 fallback 边界 |
| 既有 schedule/SQLite 与 DSH 验收工具 | 复用，不另建调度入口 |

## 当前检查点

- 已有变更基线：HEAD `73e4de7153468ff6f8659478e6e1413b2ff4987a`；170 文件哈希核对备份 `D:/Backups/Sumika/implementation-baseline-20261007-193242/manifest.json`。
- 本地索引 `.sumika-next/companion/baseline.json`。备份不意味着 Git 已提交。
- `python -B -m sumika_next.cli check` 已通过（实施前）。
- 尚未升级日用运行时、实现独立桌宠或验证真实连续语音；GitHub 是旧 K 草稿，L2 仅本地。
- 已完成隔离候选安装与无模型探针；日用运行时仍为 `0.1.5-rc.2`。

## 2026-10-07 续做验收

- 改造已有 P2/P4/角色验收脚本，使首次启动和重启都使用显式 `--runtime`。旧脚本忽略参数、重启回到旧版，不能作为候选证据；已修正，未用旧版打开日用迁移配置。
- Cordis 服务必须显式注入 `sessionQuery`；连续性与角色适配增加注入声明。新版 session format 4 禁止通用 `plugin` 来源，改用 `sumika-continuity` / `sumika-roles` producer kind；旧版保持原来源形式。
- DSH 新 DeepSeek 路由使用 Messages SSE。既有 loopback 模型夹具增加 Messages 流格式，保留旧 Chat Completions。子 Agent 判断排除 tool_result 文本，避免父会话被误判为子会话；MCP 名称查找兼容两种工具声明。
- 候选 P4 全部通过：`.sumika-next/p4-d85fc198f47a42f98ea2d308a76ffb97/report.json`。角色候选通过：`.sumika-next/role-plugin-c0ae066478334e0db264dc3ae06407fd`；旧版角色回归也通过：`.sumika-next/role-plugin-2bbedab272d74cee99e764486463b124`。均为本地夹具，外部模型调用 0。
- 候选 Plan 审批、断线读取、重启不重放、活动模型取消及迟到输出丢弃通过：`.sumika-next/p2-recovery-2bd317c879704bcc82676a1207e91506/report.json`。新版本取消以 `turn/end aborted/user` 收尾，原断言仅识别旧 `step/end`，已适配。
- 候选 P2 10 个工具均有结果，文件/Skills/子 Agent/MCP 成功；PowerShell 工具实际报 `SetNamedSecurityInfoW failed (Win32 5): grantWrite`，因此完整 P2 未通过，证据 `.sumika-next/p2-913200eacd904df6a3d786faa389a39f/events.json`。只读 ACL 检查显示执行身份没有显式 FullControl/WRITE_DAC；尚未改权限、降低沙箱或修改上游。
- 陪学问答补页码/章节元数据、旧观察拒绝和内容变化时丢弃迟到答案；8 个陪学测试通过。这只保护返回结果，不代表流式取消、真实采集或长期记忆隔离已完成。
- 验证：本轮前全量 `577 tests OK (skipped=1)`；续跑出现 loopback 连接中止及 ResourceWarning 污染 stderr 的间歇失败。受失败影响的 memory/receipts 加陪学定向重跑 `42 tests OK (skipped=1)`；连续性 Node `12/12`；check 通过。全量最终复跑仍需确认。
- 最新 npm 市场初筛补入 `reference-projects.json.market_observation`：automation、find-plugin、skill-explorer、plugin-manager UI、repeat-tool-breaker；仅 registry 元数据，源码/peer/真实能力尚未验收，不自动安装。
- 下一步先核验 Windows 原生沙箱 ACL 条件并完成 P2，再插件生命周期与四屏 UI；并行优先推进真实正文/字幕/电子书文字闭环。独立桌宠、连续音画和语音、定期研究 runner、发行安装/回退仍未交付。
- 最终全量第一次 `580 tests` 有 1 错误：Windows 文件替换拒绝后 ProfileLease.release 未关闭锁。修复为 finally 关闭，不吞异常、不清除未确认 ownership 记录；增加失败路径验证，11 个 ownership/companion 定向测试通过。原子替换拒绝的根因未确定，不自动重试或改权限。
- 修复后最终全量 `581 tests in 48.855s OK (skipped=1)`；仍有 ResourceWarning 和 pathlib 弃用警告，不代表真实硬件、模型或候选 P2 已验收。

## 2026-10-08 续做

- 资产复用：DSH 随包 `diagnose-windows-sandbox-acl` 脚本直接使用；`tools/verify_dsh_p2.py` 和 `verify_phase2.py` 改造后使用；现有 `extensions/desktop/control/uia.py` 的窗口句柄/PID 校验直接使用。UIA 文本读取适配新增于独立 Windows 边界，不修改原桌面控制和 DSH 上游，无 UI 入口改动。
- 原生权限诊断证明临时夹具目录 effective WRITE_DAC=true / WRITE_OWNER=false；当前用户为 owner，但普通令牌缺少必要权利。原生脚本只在显式临时目录补用户 FullControl，复读 WRITE_OWNER=true；无提升、无项目根权限改动。证据和恢复脚本：`.sumika-next/dsh-upgrade/acl-recovery-20261007/acl-report-32e6ad174b304b4dafc1808384b41c34.jsonl`；回退命令在该报告 summary.rollbackCommands。
- P2 增加显式 `--repair-fixture-acl`，只对每次生成的 work 运行同一原生脚本；证据保留于该次 `acl-recovery/` 和 `acl-repair-output.txt`。默认不修复，日用配置/目录未改变。
- 新版终端 timeoutMs 会转后台，而不是终止。按公开 schema 验证超时转后台及 job_output 收集；增加 job_kill 验证不产生迟到文件，活动 session.cancel 保留。旧版继续验证超时终止。
- 完整候选发行门槛通过：`python -X utf8 -B tools/verify_phase2.py --runtime .sumika-next/dsh-upgrade/0.2.0-rc.2 --repair-fixture-acl`。全量 587 tests OK (1 skipped)、native probe、P2 10 工具及终端退出/后台/显式停止/取消、Plan/重连/重启/模型取消通过；P2 `.sumika-next/p2-bbddead8dee7487d984ca4f9171b89b4/report.json`，恢复 `.sumika-next/p2-recovery-53b8061013d44539b2b1f62831a45584/report.json`。不证明日用权限或模型质量。
- 陪学记忆边界修复：RoleChat.reply 新增显式 memory_writes=False，屏幕问答禁用规则提炼及模型提案，保留角色和记忆读取；Bridge 使用独立瞬时 RoleChat，不经过普通聊天存档/任务分类。当前每次问答无跨轮短期上下文，连续讨论仍待接入；用量依旧记录。
- `extensions/companion/windows_text.py` 从显式窗口的唯一可见 Document 读取 GetVisibleRanges 或 GetSelection，限制正文长度，读取后复验 PID，最小化/歧义失败关闭；无截图、剪贴板、键鼠操作。`POST /api/companion/collect` 要求 CSRF、consent=true、明确 handle/PID，使用已有 desktop-env subprocess；无自动跟随、持续许可或新增 UI。
- 真实 Edge 独立教程页面实测通过：`.sumika-next/companion-text-0d3668521ae2452f8963549e88a59697/report.json`，可见正文命中、折叠及视口外正文排除，模型调用 0；自建窗口已关闭。真实网页/电子书通用覆盖、选中实测、字幕、视觉、问答模型仍待验证。
- 下一步：插件安装/启停/卸载/不兼容拒绝及四屏 UI 候选回归；完成采集→文字问答真实闭环与短期会话、许可撤销；日用切换与安装包仍未交付。
- 门槛之后补采集 HTTP 断言：无 consent/错误窗口参数不启动 worker；显式窗口选择走隔离解释器；三个 companion POST 均受既有 CSRF 限制。最新 `test_ui_server + test_companion_windows_text + test_auto_extraction` 共 43 tests OK；check/handoff 通过。

## 2026-10-08 插件与文字闭环补验

- 现成资产：候选内置 `@deepseek-ai/dsh-plugin-manager` 直接使用；`tools/verify_companion_windows_text.py` 改造后使用，复用真实 Edge/UIA、现有 Bridge、RoleChat 和 OllamaProvider。新增工具 `tools/verify_dsh_plugin_lifecycle.py` 仅为隔离原生 API 验收，不增加产品入口或管理实现。
- 插件实际生命周期通过：本地无依赖 bundle 安装、listBundles/listPlugins、禁用/启用、各次重启保持、卸载；不兼容 peer `>=99.0.0` 返回 `incompatible-version`，manifest/lock/patch 字节恢复，无版本豁免。无关插件配置经 YAML 结构比较保持。证据 `.sumika-next/plugin-lifecycle-e2794f79cc5c4fa99b5b2bee844f133a/report.json`，完整操作与原生日志在同目录。
- 新版库存字段为 `entryId` / `enabled`，实际 profile 在 `home/profiles/web`，管理器会将 JSON 形式 patch 重写为 YAML；初始脚本字段和解析断言已修正，不是产品缺陷。失败夹具目录保留诊断，所属 DSH 子进程均关闭。
- 真实采集问答链通过：独立 Edge 教程 → `/api/companion/collect` → ObservationBundle → `/api/companion/ask` → 真实 OllamaProvider HTTP 请求本地协议夹具 → 来源绑定回答。仅可见正文进入请求，折叠/视口外标记排除，长期记忆行数 0，普通聊天存档无正文。证据 `.sumika-next/companion-text-ade9b6bfcd57414cb4e8bde8098fd457/report.json`。本地 provider 请求 1，外部模型调用 0；夹具固定回答不证明模型理解或实时延迟。独立 Edge、bridge、provider 已关闭。
- 原生插件方式可减少管理和 API 维护，但上述证据只验原生管理器与 synthetic bundle；社区插件的依赖、权限、UI 插槽和实际能力仍需逐个验证。日用 `0.1.5-rc.2` 未切换。
- 下一步：候选四屏 UI 回归；陪学短期连续上下文与暂停/撤销、电子书选择和字幕；之后连续语音、独立宿主和新安装包。整体计划仍在进行中。

## 2026-10-08 候选 UI 回归

- 现成资产：`ui/prototype-d/index.html`、`ui/app/`、`extensions/ui/sumika-skin`、`extensions/ui/sumika-brand`、`extensions/ui/sumika-workbench` 与已有 Playwright 验收脚本直接复用；未新增导航或页面。
- 候选 `0.2.0-rc.2` 使用隔离 profile 启动，四屏（活动室、资料架、设置、工作台）在 1440×900、1280×720、1160×800 均无越界；首次预览说明和 API Key 弹窗已按新版实际 UI 关闭后继续验收。`verify_ui_v2.mjs` 通过。
- 完整矩阵 `8 分辨率 × 2 缩放 × 2 主题 × 4 屏 = 128/128` 通过，主题恢复、卡片尺寸与页面错误均无失败；证据 `.sumika-next/ui-candidate-7aaf1538ba634e348a33ec2b315b215a/matrix.json`。
- 验收工具不再绑定已不存在的旧 Codex runtime 路径，新增 `tools/lib/playwright.mjs` 自动寻找当前本地 Playwright；这是验收基座修复，不是产品入口或 UI 重构。
- 工作台实际显示 DSH 0.2 预览提示、原生侧栏和 Sumika 皮肤；API/资源连接异常初因是验收在遮罩阶段提前退出，关闭新版两层提示后复跑清零。隔离 bridge、DSH 子进程和浏览器均已关闭。
- 当前结论：候选 UI 已完成本轮四屏和矩阵回归；电子书选中、视频字幕、短期连续上下文、暂停/撤销、连续语音、安装升级回退仍未验收。日用版本仍未切换。

## 2026-10-08 短期讨论与撤销许可

- `CompanionQuestionService` 增加内容绑定的短期讨论历史，默认最多保留 4 轮；目标、来源或正文变化会清空历史，迟到回答仍会被丢弃。普通屏幕内容继续不写入长期记忆或聊天存档。
- 新增 `POST /api/companion/revoke`，沿用现有 CSRF 写入保护；撤销立即清除当前观察和短期上下文，后续提问在重新采集前失败关闭。没有新增 UI 入口，供桌宠宿主和授权控件调用。
- 定向测试 38 项通过，覆盖短期上下文边界、内容切换、撤销后拒答和 HTTP 授权。真实电子书选中尚未在实体阅读器上完成，当前仅有隔离 UIA/HTTP 夹具验证；字幕、视觉、连续语音仍待接入。

## 2026-10-08 视频字幕适配

- 新增 `POST /api/companion/video`，沿用 CSRF 和明确 `consent`，支持播放器直接提交当前字幕窗口或 WebVTT 文本加播放时间；WebVTT 解析只保留当前 cue，文本长度受 12,000 字限制，并保留 `video-subtitle`、播放时间和标题来源。
- 定向测试扩展到 41 项通过，覆盖字幕时间选择、来源绑定、未授权拒绝和问答。该接口不采集应用音频、不承诺无字幕视频理解；WASAPI loopback、ASR 和真实播放器字幕桥仍未接入。

## 2026-10-08 真实选中内容回归

- `tools/verify_companion_windows_text.py` 在自建 Edge 文档上实际聚焦 Document 并全选，再调用独立 UIA 采集器；结果为 `ebook-selection`。选择在问答验收之后执行，尚未证明选中片段进入问答，也未证明非选中内容排除。证据 `.sumika-next/companion-text-2fe4b7300c4b4fff8847a80247c196a4/report.json`；不作为实体电子书阅读器兼容性证据。
- 同一报告同时证明可见网页正文、折叠/视口外排除、来源绑定、本地 provider 闭环、长期记忆写入 0 和普通聊天存档无屏幕正文。真实电子书应用兼容性仍需按目标阅读器单独回归。

## 当前语音边界

- 现有 `SpeechInput`、`SpeechPlayback` 和 `VoiceSession` 已能独立处理本地录音/播放的授权、取消与状态迁移；本轮未把它们伪装成连续陪学管线。真正的 VAD、麦克风独立采集、WASAPI 进程回环、ASR→问答→TTS 流式连接和说话打断仍是未完成项。

## 2026-10-08 候选发行打包检查

- 已运行当前打包脚本检查候选 DSH `0.2.0-rc.2`。候选安装使用 pnpm junction，直接复制不会形成物理 `node_modules/@deepseek-ai/dsh` 和 `release.json`；发行验收器要求无链接且必须存在 `runtime/dsh/release.json`，因此本轮没有生成或替换安装包。失败证据 `.sumika-next/package/candidate-20261008-materialization-report.json`。
- 日用 `runtime/dsh`、日用 profile 和个人数据均未修改。下一步需要复用/补齐现有依赖物理化流程，再执行安装、升级和回退验收。

- 隔离安装首次启动发现打包 Python `_pth` 未把产品根加入 `sys.path`，导致 `ui` 命名空间导入失败；`PYTHONPATH` 在 `_pth` 模式下无效，改为新增 `tools/run_module.py` 启动引导并重建。候选 dsh02d 已安装到隔离目录，`start_sumika.ps1 -Port 8879 -NoBrowser` 实际启动通过。证据 `.sumika-next/package/dsh02d-install-report.json`。
- `tools/verify_runtime_upgrade_rollback.py` 通过：旧版 `0.1.5-rc.2` 与新版 `0.2.0-rc.2` 分别使用匹配 profile 启动并创建会话，profile 路径分离，未执行原地降级或配置迁移。证据 `.sumika-next/runtime-upgrade-161c5b665e784e89897d643b1750c71f/report.json`。

## 2026-10-08 安装证据复核与问答边界修复

- dsh02d 的脚本启动不等于 EXE 启动。实际 EXE 缺少 Sumika.dll，失败证据 `.sumika-next/package/packaged-install-c19fd2f2dd6e462fb2e0253caee1d531/report.json`。此前客户端启动通过结论由本节取代。
- 复用 `packaging/Sumika.Launcher.csproj` 自包含单文件发布（73,484,100 字节），修正已有打包器漏选 SVG/TXT 资源和 PowerShell 路径含空格时的引导参数。候选 E：`E:/SumikaBuild/product-candidate-20261008-e`，27,645 文件。
- 当前主机 ZIP 安装、完整清单、真实 EXE 首次启动/复用/外部端口保护/认证关闭通过：`E:/SumikaBuild/packaged-install-88e49b58aa384878994e183cf70abf8c/report.json`。
- Windows Sandbox 独立来宾通过相同安装与 EXE 生命周期：`E:/SumikaBuild/clean-windows-20261008-e/results/report.json`。WSB 映射输入只读、输出可写，网络/剪贴板/音视频输入禁用；报告为 WDAGUtilityAccount 来宾路径、不同计算机名。归档 SHA256 `4b1ac3106fb745714bf91d61974285b6ca3a2774d55a8ad37afa2d560900f952`。仅证明 bridge 生命周期，不代表原生 DSH、模型、全部 UI 或硬件功能通过。
- old → new → old 运行时/profile 对启动和创建会话通过，旧 profile 在新版运行期间哈希不变：`.sumika-next/runtime-upgrade-d5d28acf1b684672aa5d2d46c1684dbd/report.json`。未验证既有数据迁移或覆盖安装回退。
- 现成资产：`extensions/companion/qa.py`、`subtitles.py`、`ui/server.py`、`tests_next/test_companion_contracts.py` 均改造后使用；无新增 UI。问答提交历史与迟到判断置于同一锁内；采集绑定 generation，撤销或内容变更后拒绝旧采集。WebVTT 编号及 cue settings 不再导致漏字幕/异常。当前仍为有限解析器，未宣称完整 WebVTT 标准兼容。
- 本轮定向 61 项测试通过；候选 E 早于本轮问答修复，发行前需重建。真实播放器桥、实体阅读器选中问答、短期历史 TTL/容量、WGC/WASAPI、连续语音、桌宠宿主和调研 runner 均未完成；日用未切换，未上传或公开发布。

## 2026-10-08 选中片段问答实测

- 改造已有 `tools/verify_companion_windows_text.py`，复用真实 Edge、UIA 采集、HTTP bridge 和本地模型夹具。页面明确选择 `SELECTED_FRAGMENT` 后实际调用 collect/ask；未选中的可见正文、折叠正文、视口外正文均不进入模型请求，长期记忆写入为 0，普通聊天存档无屏幕正文。证据 `.sumika-next/companion-text-eb034682b1a949f098b23a5a11427c1a/report.json`。
- 首次使用 Edge UIA DocumentRange.FindText().Select()，返回内容偏移为 `LECTED_FRAGMENT\nUN`；失败证据 `.sumika-next/companion-text-1d38376b005440099ab9b11bb493e112/report.json`。这属于夹具选择步骤的问题；改用自有页面按钮通过 DOM Range 选择准确片段，再由真实 UIA 独立读取。未修改产品采集器，也没有引入页面自动控制入口。
- 本结果取代之前全选后的“选中进入问答”结论，但仍只是自有浏览器页面、同步文字、本地 provider 格式夹具；不代表实体电子书阅读器、真实模型答案质量或实时视频桥。

## 短期讨论容量边界

- 继续改造现有问答服务：默认保留 4 轮、至多 8 个会话，每个会话问题与回复合计至多 12,000 字符。闲置 10 分钟的历史在下一次服务请求时清除并不再参与回答；没有后台计时器，也不声称到时立即擦除内存。撤销或内容变化立即清空历史及时间索引。
- 63 项定向测试通过，覆盖 TTL、会话淘汰、超长回复截断、迟到采集/回复拒绝、字幕、UI bridge 和打包资源。check/handoff 已执行。候选 E 不含这些后续源码修复，发行前需重建。

## 2026-10-08 浏览器视频字幕采集

- 新增只读 `extensions/companion/browser_video_snapshot.js` 和 `browser_video.py`。它只读取明确绑定的 BrowserSkill Agent Window 中唯一可见 `<video>` 的 `currentTime`、暂停状态和已启用的字幕轨当前 cue；不 seek、不启用轨道、不执行页面命令、不读取网络资源。采集前后复核站点授权、会话身份、tab 身份和 origin。
- 新增 `POST /api/companion/browser-video`。必须有显式 consent 和已授权 site；采集失败会撤销当前陪学上下文，避免继续回答上一段视频。无字幕、多个视频、跨 origin、异常播放时间均失败关闭。
- Edge/Playwright 真实视频夹具通过：`.sumika-next/companion-video-9136f2a3-2666-4523-8557-b56c369195bf/report.json`，覆盖当前 cue、快进换 cue、无字幕、多个视频和 origin 拒绝。Python/HTTP 定向测试 71 项通过。
- 这条链路目前只覆盖 BrowserSkill Agent Window 和 HTML `TextTrack`。普通用户浏览器窗口、播放器自定义字幕 DOM、烧录字幕、无字幕音频、WGC/WASAPI 和连续语音仍未完成；不能宣称已经支持所有网页/播放器。

- 当前重建候选 F：`E:/SumikaBuild/product-candidate-20261008-f`，复用 E 的物理 DSH runtime、host runtimes 和已验证单文件 launcher；纳入本轮问答/字幕源码。首次 launcher 参数误传目录，在复制前被拒绝；修正为 `Sumika.exe` 后启动打包（exec session 79006），日用不修改。

- 候选 F 已完成，27,648 文件；当前主机 ZIP 安装及 EXE 启停验证通过：`E:/SumikaBuild/packaged-install-eff7372b382d4e8bba9b1bf6db9c89a7/report.json`。ZIP SHA256 `09f73fd53786874d7afa29e52500d716e81908b96d5d6e55f22d2b669cc4f35f`；session 79006/25021 已结束。
- 复用已有 `tools/build_setup.py` / `packaging/Sumika.iss` 增加显式 `--version`，版本参数限定字符、由 Inno `/DBuildVersion` 接收。F 安装向导构建通过：`E:/SumikaBuild/wizard-20261008-f/Sumika-Setup-2026.10.08-f.exe`，SHA256 `4128082c7c65478d2648a6916ef2a7f10543be7d6d3e2f69f4c0791fbf36c576`，证据同目录 `build-report.json`；session 62307 已结束。未验证 F 向导实际安装/卸载，F 未做 Sandbox 回归；不沿用 E 来宾结果作为 F 的实测。没有日用安装、数据迁移、推送或公开发布。

## 2026-10-08 连续语音协调层

- 新增 `extensions/companion/voice_pipeline.py`，复用现有 `VoiceSession` 状态机；新增 `AudioRoute` 明确麦克风和应用进程音频的分轨路由，`CompanionVoicePipeline` 负责显式授权、ASR→回答→TTS、播放完成和打断。每个 turn 带 epoch/token，撤销或打断后迟到 ASR、回答、TTS 结果拒绝，不自动重试。
- 新增 `extensions/companion/audio_routes.py`，只生成 Windows WASAPI 进程回环的 provider 请求和麦克风路由描述；没有在没有 provider 时伪造采集结果。真实 process-loopback provider、VAD、ASR 流式传输和 TTS 流式播放仍待接入。
- 22 项语音/陪学定向测试通过；覆盖授权、分轨元数据、完整 turn、播放完成和打断失效。

## 2026-10-08 主动讨论调度

- 新增 `extensions/companion/observation_scheduler.py`，复用现有 `PerceptionService` 和 `ContentChangeTracker`。默认约每秒采集；相同来源/目标/正文不触发模型；后台主动讨论默认至少间隔 120 秒；内容变化只保留最新 pending；`notify_user_activity()` 在用户活动窗口内压制主动发言。调度线程可停止，捕获失败不自旋、不重试模型。
- `CompanionQuestionService.proactive()` 复用同一内容代际检查，主动建议不写短期历史；调度器可通过 `bind_question_service()` 接入现有角色服务。24 项语音/陪学定向测试通过。
- 当前仍需把调度器接到真实 Windows 采集循环、章节/暂停语义和桌宠播放控件；平台 WGC、进程 WASAPI、流式 ASR/TTS 未因调度器而自动变成已完成。

## 2026-10-08 WGC 能力探针

- 在既有 `.sumika-next/desktop-env` 隔离环境安装 `winrt-runtime==3.2.1`、`winrt-Windows.Graphics.Capture==3.2.1`、Foundation/System bindings；`GraphicsCaptureSession.is_supported()` 实测为 `True`。
- 新增 `extensions/desktop/windows_capture.py`：报告 WGC provider 能力，并要求正整数 HWND；当前 `capture_window()` 在支持系统上明确返回 `HWND interop provider is not installed`。不会把 `ImageGrab.grab_window()` 当作 WGC，也不会产生伪造帧。15 项 WGC/屏幕调度定向测试通过。
- 剩余工作是一个原生 D3D11/WinRT HWND interop helper，将 frame pool 转成可供 OCR/视觉模型使用的短期帧；这需要单独的 C++/C# 宿主或已验证库，当前尚未接入产品。

## 2026-10-08 WASAPI 端点回环

- 在同一隔离桌面环境安装 `soundcard==0.4.6`，新增 `extensions/desktop/audio_loopback.py`。显式授权后可从默认扬声器 WASAPI loopback 录制短 WAV；provider 返回采样率、声道和 `process_isolation=false`，不写长期记忆。
- 任何带 `process_id` 的请求都会失败关闭，因为 `soundcard` 只提供端点回环，不提供进程级隔离；不能把端点中的其他应用、教程和桌宠声音混为目标应用音轨。3 项 provider 测试通过。
- 真实进程级 WASAPI loopback、麦克风分轨混音、VAD 和流式 ASR/TTS 仍未完成；当前端点 provider 仅作为可选诊断/后续适配基础。

## 2026-10-08 参考项目持续监测

- 新增 `extensions/desktop/reference_monitor.py` 与 `tools/check_reference_projects.py`。复用 `docs/project/reference-projects.json`，对 GitHub 项目查询最新 commit，SQLite 去重保存 revision、时间和错误；首次检查为 baseline，后续区分 unchanged/changed/error。
- 默认每 7 天检查一次，支持启动补查和 `--force`，`--limit` 限制本轮项目数；无变化不调用模型，任何异常只记录错误，不安装、升级或执行外部项目。
- 9 项监测测试通过；真实网络检查已执行但受到 GitHub API 限流，见下方记录。
- 已执行一次只读 14 项网络基线：GitHub API 全部返回 `HTTP 403 rate limit exceeded`，结果写入 `.sumika-next/reference-projects.sqlite3`，没有 revision 可据此判定更新。监测器已修正为错误状态会在下次启动继续补查，而不是把限流误记为成功周期。

## 2026-10-08 独立桌宠宿主首版

- 复用现有 `ui/app/index.html`、`deskpet.css` 和 `sumika-vrm-viewer.js`，增加 `?pet=1` 宿主样式：隐藏原生页面导航和输入区，仅保留桌宠场景；没有另建角色/VRM系统，也没有新增产品导航入口。
- 新增 `packaging/Sumika.PetHost.csproj`、`PetHost.xaml` 和 `PetHost.App.xaml`。WPF/WebView2 宿主透明无边框、置顶、可拖动、关闭按钮、无任务栏图标；默认打开现有 bridge `http://127.0.0.1:8879/?pet=1`，也可传入已授权的 loopback URL。
- `dotnet build` 与 self-contained 单文件发布通过：`.sumika-next/package/pet-host-20261008/SumikaPet.exe`。当前只验证编译和发布，未在有 WebView2 runtime 的交互桌面中启动截图；桌宠问答仍复用既有 bridge，不声明安装包已包含该宿主。
- `tools/build_portable_staging.py` 增加可选 `--pet-host`，输出为 `SumikaPet.exe`；当前 F 包未传此参数，避免把未完成交互验收的宿主伪装成已验收产品。
- 宿主页面 Playwright 实测通过：`?pet=1` 只保留桌宠，topbar/main/chat 均隐藏，截图 `E:/SumikaBuild/pet-host-check-20261008/pet.png`。WPF self-contained EXE 实际启动且 UIA 看到一个 `Window`，DPI 150% 时 510×645，证据 `.sumika-next/package/pet-host-20261008/SumikaPet.exe.runtime-report.json`；不代表 VRM 像素/透明度/拖动/点击穿透已验收。
- 已重建含 `SumikaPet.exe` 的候选 G：`E:/SumikaBuild/product-candidate-20261008-g`，27,658 文件清单通过。增加 `SumikaPet.exe` 到发行清单允许根；首次未放行时在复制前拒绝。安装/EXE 回归 session 80581 正在进行，日用未更换。

## 桌宠宿主实测纠正与 G 安装

- 首轮 pet 页面断言只检查 display，没有验证截图。截图实际显示活动室，桌宠仍是 mini。新增 screen 视口外投影、mini 的角色层展开和透明页面背景，验收增加 stageVisible/screensOffscreen；新截图 `E:/SumikaBuild/pet-host-check-20261008/pet.png` 已人工查看，真实 VRM 角色可见，但气泡顶部裁切、透明和原生拖动/点击穿透尚待修复及验收。此前“只保留桌宠”结论以本条为准。
- 新增 `tools/verify_pet_host_runtime.py` 复用 pywinauto，真实启动 EXE 并检查一枚 WPF Window 与尺寸，然后关闭专属进程。宿主只允许 HTTP 127.0.0.1，导航限定同一 origin、新窗口拒绝；新发布 `.sumika-next/package/pet-host-20261008-h` 不在 G 包内。
- 原启动器显式排除 PetHost*.cs，避免同目录 WPF 文件误入 launcher 编译；两个项目分别 build 成功。
- G ZIP 安装先因 PowerShell 安装器遗漏 SumikaPet.exe 根拒绝，失败证据 `E:/SumikaBuild/packaged-install-d68ae6f006db4c27801e46388074ccfc/install.txt`。更新安装器精确允许根后通过：`E:/SumikaBuild/packaged-install-98dc70d07d0a469fb2fab080f5632ebf/report.json`；27,658 文件清单与主 EXE 生命周期通过，SHA256 `07daabf9c5ad21f7cb5c434d274c812e5eca04e123c48cb097079a5f0073fd87`。G 早于页面修正和宿主 origin 限制，非最终交付包；没有证明 G 安装后的桌宠可用。session 80581/92700 均已结束，隔离验收 bridge 已请求认证关闭。

## WGC 原生帧采集落地

- 现成资产复核：`windows-capture==2.0.1`（MIT，NiiightmareXD/windows-capture）已有 Rust WGC HWND/frame-pool/native mapped-frame 实现，直接使用；改造既有 `extensions/desktop/windows_capture.py`，不另写 C++/C# interop。之前仅探针/未安装 interop 的边界已由真实 provider 取代。
- `capture_frame()` 要求显式许可和 HWND/PID，采集前、回调内、返回前复核窗口身份及可见状态；返回复制的 BGRA 内存帧并检测黑帧。原始帧默认不落盘；`capture_window()` 仅在显式调用时写新 PNG。超时/关闭后停止 capture control，没有桌面截图 fallback。
- 独立 desktop 环境安装 windows-capture 2.0.1；其 opencv-python 依赖与旧 headless 包共用 cv2，移除隔离环境的旧 headless 并重装 opencv-python 5.0.0.93，更新锁文件。未修改上游 DSH/日用环境。
- 自有 pet 测试窗真实帧通过：`.sumika-next/wgc-96bc24dcd330432cba5da24a9ccfe246/report.json`，510x645，mean 81.10/stddev 100.78。这不证明桌宠自身排除、遮挡隔离、连续感知、视觉问答或截图取消；夹具初版 tkinter 窗口未出现，失败证据 `.sumika-next/wgc-c84481cdcff2404fb27a6d317458bba8/report.json` 保留。

## WGC 画面到陪学图片接口

- 改造资产 `windows_capture.py`、`ObservationBundle.image`、`CompanionQuestionService`、`RoleChat.reply(images=...)`、既有 HTTP bridge；新增 `windows_visual.py` 作为隔离 desktop worker。不另建视觉模型系统或 UI 入口。
- `POST /api/companion/capture` 要求 consent/HWND/PID；捕获 JPEG 在内存中编码，最长边 1600，默认不写文件。worker 返回后按 collection token 更新，迟到采集不能恢复已撤销内容；失败条件清空对应旧上下文。黑帧 valid=false 且没有 image。
- 普通/主动问答使用当时 ObservationBundle 内的 image，沿用现有多模态开关和 openai-compatible 限制，没有自动换模型；回答及画面仍走 ephemeral RoleChat、memory_writes=false。
- 隔离 desktop 的 2 项像素编码测试通过；HTTP/问答授权、采集失败清除、图片绑定定向测试通过（52 项）。真实 WGC→HTTP→视觉 provider、桌宠自身排除/遮挡/连续采集和真实视觉答案质量仍待验收。发行 G 不含本轮代码。

## 连续感知生命周期补强

- 资产判定：改造既有 `contracts.py`、`content.py`、`observation_scheduler.py`、`qa.py` 和对应测试；不新增调度框架或 UI。PerceptionService 加锁及生命周期代际，暂停/恢复、停止、换目标期间结束的旧采集拒绝返回，并核对 collector 返回目标。
- 调度器拒绝过期观察，不把 valid=false 放入主动讨论队列；失效/采集异常清空 pending 与绑定问答上下文。图片及有效状态纳入内容 digest，画面变化可以触发最新内容合并。bind_question_service 同时接 update/proactive，而非仅调用可能持有旧观察的主动接口。
- stop 会撤销绑定上下文、停止 perception 并清空内存观察；线程未退出时返回 stopping/alive=true，不再伪称 stopped。已经开始的模型/provider 调用仍需实际取消适配，此处只保证代际检查与迟到帧/回复拒绝，不能宣称立即停止硬件或模型网络请求。
- 回归 63 项（调度/问答/语音/HTTP）通过；新增采集异常用例后定向 37 项通过，含阻塞采集的 stop、pause/resume、invalid/stale、图片变化、绑定更新和采集失败撤销。连续 Windows 采集和用户提问抢占实际模型仍未接通；真实硬件验收及发行重建仍待做。

## 2026-10-08 视觉传输闭环与复用依据

- 使用 project-continuity 维护现有记录。资产判定：改造 `tools/verify_companion_windows_text.py` 的自有 Edge/HTTP 夹具模式，直接使用现有 WGC worker、CloudProvider、模型配置与问答服务；新增复用验收命令 `tools/verify_companion_windows_vision.py`，没有新增产品 UI 或修改生产 HTTPS 限制。
- 真实自建 Edge 教程窗 → `/api/companion/capture` → 隔离 WGC worker → `/api/companion/ask` → 本地 HTTPS OpenAI 格式夹具通过。JPEG 1239×1329，两个颜色区域各约 108,896 像素，HWND/PID 来源匹配；证书与主机名验证保持开启，夹具信任仅作用于本次 Python opener，无系统证书安装、真实凭据或付费模型调用。
- 长期记忆写入 0；普通聊天数据库无观察目标/图片；产品输出目录无原始画面文件。浏览器临时 profile 自带图标不属于捕获画面，检查不把这些静态资源误当泄漏。撤销后问答 HTTP 400，模型请求仍为 1。证据 `.sumika-next/companion-vision-c49abdb22ad546da9acc4bd444179f66/report.json`。
- 保留两次夹具失败：`ce6920d09fa94409a36073fc0f36c37d` 的 urllib 已缓存 opener 导致证书信任未应用；`65ea40624d2a487fbcfeeae483c00b2a` 已完成视觉请求，但误把 Edge profile 图标计入画面文件。修正验收器，不降低生产安全要求。此验收不证明真实模型理解质量、连续性能、自身排除或遮挡。
- 修复既有 `VoiceSession.start_listening()`：允许显式开始被打断后的下一轮，保留 turn_id 递增与旧 token 拒绝。语音协调/状态机 7 项测试通过；真实 provider 取消、TTS dispatch 竞争、进程 WASAPI 和 VAD 仍未完成。
- 回答“是否有参考其他项目”：已实际依赖 DSH、windows-capture、WebView2/现有 VRM；上下文/生命周期/调度是 Sumika 整合代码。NEKO/Pipecat 本轮才补了固定提交源码核对，不能把此前列入清单说成已经复用它们的管线。具体来源与许可证见 `reference-projects.json.source_reviews`。
- NEKO 的实际播放门控、TTL/队列预算/合并，Pipecat 的任务取消/重建与 TTS 队列清理适合后续接入。两份源码作为无工作树的 Git 缓存保留在 `D:/Caches/tooling/reference-code/`，可使用 `git show <revision>:<path>` 阅读；没有执行外部项目代码。
- 下一步仍是连续 WGC/自身排除、实际播放生命周期门控与 Pipecat provider 集成，继而进程音轨、桌宠交互、调研原生调度及最新包验收。日用版本未切换，旧发行包不能沿用本轮证据。
- 收尾验证：`python -X utf8 -B -m unittest tests_next.test_companion_voice_pipeline tests_next.test_realtime_voice tests_next.test_companion_contracts tests_next.test_companion_observation_scheduler tests_next.test_ui_server` 共 67 项通过；有既有 pathlib 弃用和 HTTPError ResourceWarning。`sumika_next.cli check` 与 `handoff` 通过。隔离 desktop 环境无 pytest，改用项目已有 unittest，未安装新测试框架。

## 2026-10-08 主动讨论播放门控

- 前轮为具体进展：真实 WGC/TLS 视觉夹具完成，语音恢复缺陷修复。本轮复核现成资产并改造 `ObservationScheduler`、`CompanionVoicePipeline`，未新增 UI/并行队列。依据 `reference-projects.json.source_reviews` 中 NEKO 固定提交的实际播放门控/提示 TTL；行为借鉴，没有复制其源码。
- 调度器增加带 turn token 的 playback_started/ended 和 `voice_event`，语音协调器发出 user_started、playback_started、playback_ended、interrupted、stopped。实际播放结束前不放行主动提示，结束后默认 2 秒间隔；旧 token 结束不能解除新播放门控。最新 pending 默认 180 秒到期，即使后续相同内容被重复采集，也不会刷新旧提示的等待时间。队列仍为单项合并，未另建框架。
- TTS provider 抛错会释放对应播放门控；取消 provider 抛错仍先撤销 turn、stop 仍关闭协调器，并在 finally 发出结束通知。错误继续抛出，不声称硬件成功停下。
- 修复端点诊断 `audio_loopback.py`：已安装 soundcard 0.4.6 的 `_Speaker` 没有 loopback()；使用 `get_microphone(speaker.id, include_loopback=True)`，并核对 isloopback。原先“可录制 WAV”的文档只获 mock 支持，真实设备录制仍未实测，更不代表进程音轨隔离。
- 验证：独立 desktop Python 运行语音/调度/问答契约/端点诊断共 41 项通过，含真实协调器到调度器事件接线、TTL、不刷新旧提示、旧 token 拒绝、TTS/取消失败清理。本轮未调用模型或打开麦克风/扬声器采集。
- 限制：现有同步 tts 接口的 playback_started 在 provider dispatch 前发出；真实流式播放适配仍须以播放器完成回调报告 playback_done。模型调用取消、dispatch 与 interrupt 竞争、连续 WGC 宿主、进程 WASAPI、Pipecat 集成仍未完成。不能据此宣称连续陪学产品已可用，发行 G 也不包含本轮修复。

## 2026-10-08 桌宠采集排除与遮挡实测

- 现成资产改造：`PetHost.xaml.cs`、`windows_capture.py`、`verify_wgc_capture.py`；未改变设计稿布局、控件或入口。桌宠 HWND 标记 `Sumika.Companion.CaptureHost` 并设置 `WDA_EXCLUDEFROMCAPTURE=0x11`；设置失败关闭宿主。窗口关闭移除标记。WGC 采集器在每次身份核对时检查 root HWND 标记，明确拒绝桌宠及其子窗口成为学习目标，不依赖进程名猜测。
- 新宿主 self-contained publish 通过：`.sumika-next/package/pet-host-20261008-i/SumikaPet.exe`。旧宿主 h 和发行 G 不含排除机制，不能沿用此结果。
- 改造原 WGC verifier：旧版曾把桌宠当成功采集目标，现在改为自有 Edge 教程窗和完整覆盖它的紫色测试窗。实际目标 WGC 红/绿各 162,000 像素、紫色 0；覆盖窗紫色 1,583,220 像素。桌宠 `GetWindowDisplayAffinity=17`，宿主属性可查询，直接采集桌宠被拒绝。真实采集器经 PerceptionService/ObservationScheduler 重复观察 4 次，暂停拒绝、恢复成功、停止清空 latest，画面只驻内存。
- 证据 `.sumika-next/wgc-4cc31d10ff3c4d25ad3c1b60151d5ee8/report.json`。没有采集用户窗口、模型调用、画面文件或日用切换。window identity 单测 4 项通过；这不是全屏采集实际透明洞效果的验证，也不证明所有游戏、DRM 窗口、长时帧池、自动前台跟随或性能门槛。后续仍需集成长驻感知 worker、真实流式语音和新包交付。

## 2026-10-08 WGC 长驻会话

- 改造现有 `windows_capture.py` 增加 `WindowCaptureSession`，使用同一个 native `WindowsCapture` frame-pool 会话接收并复制最新 BGRA 帧；`WindowsVisualCollector` 按 HWND/PID 复用会话，target 变化、暂停或停止时释放控制句柄、缓冲和引用。没有把原始帧写到磁盘；调度器仍负责约每秒一次的模型调用节流。
- 夹具初测暴露频率过滤会丢掉窗口最后一次变化，导致静态窗口没有下一帧；删除回调层频率过滤，保留 trailing latest frame。修复后真实 Edge 窗口连续改变尺寸，单一会话 `native_frames_copied=3`，重复观察 4 次，暂停/恢复/停止通过。
- 最新证据 `.sumika-next/wgc-aa162e5fa8d14926af2cdf0ae64fc4d9/report.json`。此前 `.sumika-next/wgc-5d6e93ae8eb84065bcf24d93c053c326` 为失败证据，保留用于说明修复原因。定向 WGC/视觉/生命周期 36 项通过。
- 限制：仍是同步 `snapshot()` 从最新内存帧取样，未做真实多分钟压力/帧率/内存测量；模型调用及流式语音不能取消，进程 WASAPI、自动目标跟随、最终新包仍待完成。

## 2026-10-08 受管连续感知 HTTP 闭环

- 改造现有 `ui/server.py`、`WindowsVisualCollector` 和隔离 desktop Python，新增 JSONL `perception_worker` 与 `PerceptionProcess`。`POST /api/companion/perception` 支持 `start/pause/resume/stop/status`，沿用已有 CSRF 和明确 consent；画面仅经过父子进程内存管道，worker 的 stdin 关闭即停止 WGC，会话失败清空陪学上下文。
- worker 先取得首帧再启动 stdin 关闭监听，避免原生 WGC 启动期和管道读取竞争。状态返回 alive、目标、观察计数与错误类别，不返回原始帧；观察 JSON 会进入已有 `ObservationBundle` 和短期问答，不写长期记忆。
- 真实自有 Edge/TLS 视觉验收已把连续接口纳入：启动后至少两次观察，问答只产生一次模型请求；暂停确认 worker 不再存活，恢复重新采集，撤销后 worker 状态 stopped 且后续提问 400，不继续使用旧画面。证据 `.sumika-next/companion-vision-426e769ee90e44d285f8535ff84baf91/report.json`。
- 首次失败 `.sumika-next/companion-vision-37cf585e65764d4bbb4d0c000f9ee016/report.json`：worker startup race 导致 observations=0；调整后通过，没有放宽超时或伪造观察。UI 单测 34 项通过。
- 限制：当前 worker 只支持显式 HWND/PID，尚未提供前台窗口跟随、真实进程 WASAPI、VAD/流式 ASR/TTS、模型请求取消和长时压力报告；新 HTTP 行为尚未加入桌面 UI 入口，避免违反现有设计的单入口约束。发行包尚未重建。
- 回归：先发现隔离 desktop runtime 锁文件漏 `tzdata==2025.2`，已加入 `extensions/desktop/requirements.lock` 并安装。隔离 desktop bridge/陪学回归 59 项全通过；连续视觉夹具使用同一环境已通过。`sumika_next.cli check` 与 `handoff` 通过。

## 2026-10-08 连续观察期间的回复绑定

- 现成资产：改造 `qa.py` 的内容代际与现有 HTTPS/Edge 夹具，不新建问答系统或 UI。延迟模型 2.5 秒复现连续观察每秒产生新对象时答案被丢弃，失败证据 `.sumika-next/companion-vision-37f01fd35213400f99d9ba5698d870d6/report.json`。
- 返回判定改为检查内容/许可代际，不检查 observation 对象 identity；相同画面的新时间戳不会使回答失效，返回来源时间仍是用户提问时的观察。有效状态、图像、正文、source/target、媒体时间、定位 metadata 变化及 revoke 均增加代际，使旧回复失效。主动回复使用同一完成判定；调度器 expected_observation 的提交前检查仍保留。
- 修复后的真实 worker/TLS 请求证据 `.sumika-next/companion-vision-20a4e6373d054784be96514144ff07f8/report.json`：模型等待期间 observation 从 2 增至 4，回复携带 1 张绑定图像而非 stale_response；长期记忆 0、普通聊天无图像、撤销阻断均通过。真实模型理解效果未验证。
- 66 项问答/调度/HTTP 回归通过，新增相同内容刷新、有效性/页码/媒体时间变化的迟到回复测试，以及 continuous 接口 consent/目标类型/resume 状态拒绝。
- 首次两分钟运行 session 70513 已终止：D 盘仅剩约 9 MB，结束后的模型用量 SQLite 写入失败 `database or disk is full`，证据 `.sumika-next/companion-vision-18f84a7acf634317b887aae8be8236d0/report.json`。自动执行检查拒绝批量删除临时 profile；未换工具绕过。验收器增加 `--output-root`，改在 E:/SumikaBuild 隔离运行，日用数据不迁移。
- E 盘恢复实测 session 23726 完成，证据 `E:/SumikaBuild/companion-vision-1d8d6b9359554a3e926c50a4707d5f54/report.json`：120 秒期间 116 次观察，模型等待 2.5 秒期间增加到 119 次，答案有效；暂停/恢复/撤销、图片来源、长期记忆 0、普通聊天无图像通过，模型调用仅 1 次。运行中实际采集进程两次工作集约 94.2/94.5 MB，属于快照而非内存泄漏证明。静态自有网页不代表视频/游戏的动态帧压力、真实模型质量或语音性能。

## 2026-10-08 活跃回答期间撤销

- 改造现有 bridge 准入/CSRF、感知控制器和回复代际，未新建 UI。已确认所有 POST 共用 chat writer lock，导致采集 pause/stop/revoke/status 被正在生成的回答阻塞。将已授权的撤销和 pause/stop/status 从等待模型的锁中分离；start/resume 仍保留原有写入准入及关闭检查。迁移未完成不能阻止撤销采集，撤销仍需 CSRF。
- 并发 HTTP 回归在模型等待 release 时调用 status/revoke，控制请求先返回，随后释放模型；旧结果只有 stale_response，没有正文。扩充未授权拒绝清单覆盖 perception 路由。
- 真实 Edge/WGC/TLS provider 夹具增加第二次保持中的模型请求，在其返回前撤销采集。证据 `E:/SumikaBuild/companion-vision-a06086dacdb84210b39f81d518623242/report.json`：撤销约 0.051 秒、worker stopped、迟到回复丢弃、屏幕长期记忆 0，2 次预定夹具模型调用（撤销不额外调用）。provider_request_cancelled=false 明确保留。
- 这不是网络模型请求已取消的证据；仍需可取消/流式 provider、说话打断、WASAPI/VAD、真实 UI 操作入口与更新安装包。日用版本和个人数据不修改。

## 2026-10-08 本地模型请求取消

- 现成资产：现有 Cloud/Ollama 适配器、陪学代际和标准库请求对象改造后使用；新增 `models/cancellation.py` 将取消上下文传到 HTTPX 异步传输，不改变普通角色聊天的 urllib 路径，不新增 provider 或自动回退。
- 原先 Windows 同步 urllib TLS 读取在 socket shutdown 后仍阻塞 `ssl.recv_into`，三份失败证据 `E:/SumikaBuild/companion-vision-67ef88f372da4ad3af11a73fdbc2a430`、`4b05199b9f9f40ca85261ec3ec27f342`、`b3b2e234e56548a7afc8e64f2d569a50` 保留。请求线程包装与 bridge writer lock 冲突也已撤回；最终没有留下后台模型线程。
- 本机已有 HTTPX 0.28.1，复用其 AsyncClient 和 asyncio task cancellation，取消时关闭本地连接并退出调用；root pyproject 增加 `httpx==0.28.1`，desktop 锁固定 httpx/httpcore/h11/anyio 并安装。`pip check` 通过。Cloud/Ollama 使用共同 model_response，未取消上下文时保持既有调用。
- CompanionQuestionService 为每次 ask/proactive 建取消 token；许可撤销、失效或内容代际变化取消活跃请求。同画面时间戳刷新不取消。取消结果不写历史；远端状态与用量未知，不推断服务端停算或计费为零。
- 真实 WGC/HTTP/TLS fixture：`E:/SumikaBuild/companion-vision-59d3c60a147d41739c6f44b986a4c9ff/report.json`。第二次 provider 请求保持响应未返回时 revoke 约 0.05s，调用线程在 provider 放行前结束，worker stopped，旧正文未显示；provider_request_cancelled=true 表示本地请求取消，remote_cancellation_confirmed=false。这取代上节本地请求仍完成的限制；真实流式 token、VAD/ASR/TTS、音轨隔离仍未完成。
- 新增本地 HTTP 阻塞响应取消回归，覆盖 cancellation token 先取消拒绝、回调幂等和活跃请求退出/回调清理。当前桥接路径为同步线程内启动独立 asyncio loop；并非原生实时多模态或远端取消协议。最终包未重建，整体计划仍在进行。
- 本轮 model cancellation/陪学契约/角色模型/HTTP 回归 75 项通过；既有 pathlib 弃用与 HTTPError ResourceWarning 仍有。未将失败的同步 TLS 或线程包装尝试列为完成。check/handoff 随收尾运行。

## 2026-10-08 流式陪学回答

- 现成资产：CloudProvider 的 OpenAI 兼容消息/image_parts、现有 cancellation token、CompanionQuestionService 代际检查和 bridge CSRF 接口改造后使用；新增 `httpx-sse==0.4.0`，不建立第二套模型配置。
- OpenAI-compatible provider 支持 `stream=true` SSE，复用 `httpx-sse` 解析 `data:` / `[DONE]`，按 delta 调用回调；累计回复限制 256,000 字符，没收到 DONE 的响应为 `incomplete_stream`，不重试。Ollama 仍明确不接流式接口，避免伪造兼容。
- 新增 `POST /api/companion/ask-stream`，返回 NDJSON `delta`、`complete` 或 `error`。delta 包含观察时间、source 和 target，不能变成授权或工具指令；完成响应才进入短期历史。连接中断或 revoke 会取消本地请求，部分文字不会写入历史。
- 真实 HTTPS Edge/WGC fixture `E:/SumikaBuild/companion-vision-c980132ec7d94de791b3c280cf5ccb2d/report.json`：首段 delta 约 0.061 秒、第二段和 complete 正常，图像仍绑定、模型调用 3 次（普通、撤销夹具和 streaming）。远端模型质量未验证。
- 新增 78 项回归（累计 model cancellation、流式 image 请求、无 DONE 失败、流中 revoke/history 清理、HTTP bridge）；通过。依赖锁与隔离环境已安装 `httpx-sse==0.4.0`。
- 边界：SSE 取消证明本地连接/调用停止，不能证明远端已经停止生成或停止计费；真实 VAD/ASR/TTS、进程 WASAPI、视频动态内容、UI 控件和当前发行包仍未完成。

## 2026-10-08 语音生命周期与 Pipecat 环境核验

- 现成资产：改造 `extensions/companion/voice_pipeline.py` 和既有 VoiceSession；直接使用 Pipecat 发布包的 Pipeline/Task 与 Silero VAD，未另写 VAD。播放期间 begin_turn 先取消旧 provider；ASR/回答异常将当前 turn 标为 error，迟到旧异常不破坏新 turn。路由在提问时绑定，防止旧调用读到后续会话配置。
- `python -X utf8 -B -m unittest tests_next.test_companion_voice_pipeline tests_next.test_companion_observation_scheduler`：21 项通过，含旧播放取消、provider 失败恢复和真实线程迟到异常回归。
- Pipecat `1.12.0` 在当前 Windows Python 3.14.7 下依赖解析通过，报告 `E:/SumikaBuild/pipecat-1.12.0-resolution.json`。使用 E 盘隔离环境 `E:/SumikaBuild/voice-env` 安装成功，Pipeline/Task 导入和 `SileroVADAnalyzer(sample_rate=16000)` 实际模型加载通过。固定提交研究源码和此发布包存在依赖/API差异，接入以安装包源码为准。
- 尚未接入产品运行时或打包依赖；VAD 加载不等于真实麦克风、识别和播放闭环通过。TTS dispatch/interrupt 竞争仍待可取消播放适配处理。下一步建立实际 Pipecat 音频管线、接入已有服务，再验收进程音轨、UI 与最新包；整体计划继续进行，日用未切换。

## 2026-10-08 实际 Pipecat Worker 接线

- 新增 `extensions/companion/pipecat_voice.py`，直接使用安装包 `VADProcessor`、`SileroVADAnalyzer`、`PipelineWorker`、`WorkerRunner`；这是可选音频适配模块，尚未接入产品 bridge。pyproject 添加 `companion-voice` extra 固定 pipecat-ai 1.12.0 / sounddevice 0.5.3。
- 异步可取消 ASR/回答/播放 provider 契约；VAD 开口取消上一任务并等待实际播放器 stop/清队列接口返回。epoch 检查与进入 speak 间没有 await，避免旧同步协调器的 dispatch 竞争；这只在遵守契约的异步 provider 下成立，旧同步路径尚待替换。停止清内存 PCM/前滚缓冲，默认单 turn 上限30秒。
- sounddevice 16kHz mono入口复用现有库，约1秒有界队列；消费每帧后等待原生 flush，避免框架内部无界队列堆积。设备错误、队列溢出、消费超时明确失败，无隐式设备/采样率回退。当前主机默认输入是 VoiceMeeter Aux，不应误认为物理麦克风隔离已成立；本轮只枚举设备，未录用户声音。
- 实际 Worker 回归使用 PCM 和模拟识别/播放器，验证 turn、打断取消与停止回调、录音流关闭、worker退出和PCM清理。VAD 开停事件由夹具注入，所以不证明实际语音检测效果。初次验收暴露新版 add_workers 必须 await 且为变参，修正后通过；不能沿用旧 PipelineTask 示例接口。
- `E:/SumikaBuild/voice-env/Scripts/python.exe -X utf8 -B -m unittest tests_next.test_companion_pipecat tests_next.test_companion_voice_pipeline tests_next.test_companion_observation_scheduler`：24项通过。voice环境 `pip check` 通过。真实VAD/ASR、流式问答及分段播放provider、进程WASAPI、UI和最终包仍待实现/验收，整体目标未完成。

## 2026-10-08 Vosk 内存 PCM Provider

- 资产判定：现有 `extensions/roles/voice.py` 的 Vosk Model/KaldiRecognizer 使用方式改造后使用；原文件型 transcribe 保留。新增 `audio_providers.VoskPcmProvider` 和 `build_local_voice_worker`，直接复用已配置本地模型；语音不创建WAV，模型在会话provider内缓存，识别器每turn独立，16kHz单声道PCM最长30秒。
- 取消设置线程停止信号，每8000字节chunk检查；等待当前native调用/模型加载结束才完成取消，拒绝迟到结果并避免上一识别仍运行就开始新轮。不能强制中断Vosk native单次调用，取消耗时还需真实压力测试。没有采用无法取消的普通同步answer线程适配，模型接线需沿用已有CancellationToken。
- 隔离voice环境安装 `vosk==0.3.45` 并加入 companion-voice extra；pip check通过。真实模型 `.sumika-next/voice-models/vosk-model-small-cn-0.22` resolve 到 `E:/Models/Speech/sumika/vosk-model-small-cn-0.22`，一秒内存静音PCM通过实际模型加载/识别，返回空文本，没有录用户音频或生成原音频文件。静音验证不等于中文识别准确率验收。
- `E:/SumikaBuild/voice-env/Scripts/python.exe -X utf8 -B -m unittest tests_next.test_companion_audio_providers tests_next.test_companion_pipecat tests_next.test_companion_voice_pipeline tests_next.test_companion_observation_scheduler`：28项通过，包含模型缓存、格式/长度拒绝、取消等待native结束和下一chunk停止回归。
- 下一步仍需真实语音/VAD输入、流式陪学模型取消适配、分段TTS/播放，再接进程WASAPI、产品UI和最终包；整体未完成。

## 2026-10-08 语音提问的画面绑定与模型取消

- 改造现有 CompanionQuestionService，增加 `QuestionBinding` / `bind_question()`；语音开口时捕获观察时间与generation，识别期间相同内容刷新仍用原观察定位，页面内容变化或撤销后旧绑定拒绝，不调用模型。
- `VoiceQuestionProvider` 接现有ask/SSE，向模型线程显式传CancellationToken；语音取消关闭本地模型请求并等待线程结束。角色返回后和写短期历史前检查取消，防止provider忽略取消后提交迟到回答。屏幕仍为参考数据，不改变工具权限。delta回调在模型线程执行，宿主需用线程安全队列/loop调度，不能直接访问WPF控件。
- `build_study_voice_worker` 组合已有Vosk provider、原生Pipecat Worker和现有陪学服务。实际播放provider由宿主传入，尚未接产品bridge、分段播放或真实麦克风问答；当前answer等最终文字后才进入speak，流式delta只已提供回调。
- 新增4项绑定/流式来源/取消不写历史回归；组合57项语音/模型/契约测试通过。隔离voice环境首次组合失败发现HTTPX/SSE未安装，补齐 root已声明的httpx 0.28.1/httpx-sse 0.4.0后同组通过；pip check通过。
- 参考清单修正Pipecat adoption为已实际安装并用于可选Worker适配，不能再称仅源码研究，也不能称产品连续语音已完成。下一步分段TTS真实播放与取消、语音闭环压力，再接进程音轨、UI、自动调研和包验收；整体目标继续进行。

## 2026-10-08 分段播放适配

- 新增 `segmented_playback.py`，复用既有 SAPI/其他播放 provider 作为单段 `play_segment`，按句号、问号、感叹号和长度切分。当前段被取消时先停止实际播放器，再丢弃剩余段；每段有 started/ended 事件，可接 scheduler 的播放门控。
- `build_study_voice_worker` 把分段播放器接入可选 Pipecat study worker。`stop_playback` 必须等待实际播放队列清空；不满足该契约的同步播放器不能标记为可取消。
- 3 项分段顺序/边界/取消回归通过；组合扩展测试共60项通过（系统环境跳过3项 Pipecat 测试，隔离voice环境已验证）。仍未在真实扬声器播放，SAPI worker 当前是整段子进程实现，需下一步做可停止的实际 provider bridge 和硬件验收。

## 2026-10-08 桌宠过期流式回答清理

### 当前源码候选 S

#### 修复后候选 U

#### 桌宠启动入口核验与后端

V真实API验收：复用固定runtime/builder构建 `E:/SumikaBuild/product-candidate-20261008-v`（42182文件）；owner状态返回实际PID。改造现成host verifier增加`--via-api`，从包内隔离bridge获取CSRF后start/restart核对同PID，真实UIA属性/输入框检查，stop核对无存活窗口和包前后inventory。58项pet/readiness/server回归通过。首轮 `pet-v-api-runtime-20261008/report.json` 输入框20秒未出现，native属性/单实例/清单仍通过；增加UIA/child失败诊断后第二轮 `pet-v-api-runtime-20261008-b/report.json`全部通过，产品逻辑没有改变。首轮原因未确认，保留为启动稳定性问题，不用第二次成功覆盖失败。尚未验证实际能力卡点击、拖动/穿透/收起、模型问答/音画或V安装包。

已接入原有能力页：`readiness.probes()` 增加真实包内 `SumikaPet.exe` 的 `pet` 行，management 将该就绪卡的详情挂载 `pet-session.js`，只调用固定 `/api/companion/pet` action；不改 HTML 预留卡、不新增导航。启动/停止/刷新、启动失败未知状态、停止恢复和单实例在浏览器夹具通过，空壳能力缺失时按钮不可用。33项陪学UI检查通过，截图 `pet-controls.png`。就绪单测同步加入 `pet`；UI真实包/API接线仍需V重建后验收。

当前源码与设计稿核验：`ui/prototype-d/index.html:948` 桌宠模式卡、:561独立桌宠窗口为已批准首版资产；当前 `ui/app/index.html:355`仍预留，management尚无宿主启动控制。单独EXE启动不等于用户能进入桌宠。复用ChildJob与bridge认证，新增小型 `ui/pet_host.py`固定包根SumikaPet.exe、固定实际bridge端口、本进程单实例、退出回收；API仅允许action、不接受程序/url/任意参数，shutdown启动阻断与回收受writer锁串行。缺失EXE和配置读不会创建进程；job构造/分配失败均杀并等待子进程。

53项pet/server回归通过，最后构造失败收尾改动后3项owner通过。首次单测Windows短路径和resolve长路径不一致，仅修测试预期以实际resolve为准。界面尚未接入，没有新增入口；下一步改造原桌宠卡及覆盖表，实际API→宿主问答/关闭验收。U早于owner/API，不可称包内支持该入口。

#### 参考项目周期执行语义

原生DSH核对：包内 `@deepseek-ai/dsh-schedule` 0.2.0-rc.2 README.zh.md 明确需实验 schedule bundle、Web Session controller及persistence，不能headless单独挂载；lib/index.js:1508起实际恢复会话、投递Agent inbox并flush。API与peer匹配不等于可替代确定性研究调度。无变化零模型要求意味着先运行独立筛选，不能每周发Agent提醒。兼容清单已改为原生提醒候选，研究触发需要gate；未安装/启用新的日用插件或重复入口。

限流处理：HTTP429及明确rate-limit 403终止后续项目查询，保留成功SHA，Retry-After秒数/HTTP日期与X-RateLimit-Reset择最长冷却，最低一小时；普通权限403仍逐项报告，不当配额误判。CLI errors退出2并保留JSON。11项本地测试通过，无外部/模型请求。原生生命周期触发、相关源码变化分析、月度发现、通知仍未完成；U包不含新runner。

资产判定：直接使用现有 `reference-projects.json` 与 CLI，改造 `extensions/desktop/reference_monitor.py`/测试和既有 SQLite 数据库；不新增调度入口。原先错误会覆盖成功revision，且due因error每次立即返回true，七日计时也不是周一10点。现在使用UTC+8（Asia/Shanghai当前规则）选择最近周一10点周期，关闭数周只执行最新周期；同一数据库新增periods表并BEGIN IMMEDIATE原子准入。20分钟未收尾租约可恢复，一小时失败/limit部分执行冷却；force不绕过活跃租约/失败冷却。失败保持上次成功SHA，没有基线恢复后记baseline，不误报changed。成功完成周期不再次网络调用。网络请求不持数据库写锁。

8项本地夹具通过，覆盖时区边界、补查合并、并发零重复fetch、崩溃租约、失败保留SHA与恢复unchanged、部分执行不完成周期、拒绝无时区时钟。未请求网络/模型。仍未接原生DSH自动化/启动、月度发现、相关文件比较/深入分析或通知；GitHub最新事实仍受限流。U包早于本轮monitor改动，不应沿用包内新runner验收。

U最终证据：`E:/SumikaBuild/product-candidate-20261008-u` inventory 42180；包内 capability/process-audio 通过；`pet-u-runtime-20261008/report.json` 真实宿主启动前后 inventory 一致；`E:/SumikaBuild/packaged-install-884afce83946452ca23c761a9370088e/report.json` 归档字节、安装后 inventory、EXE 首次/复用/外部端口保护/认证停止全部通过。Inno 安装器 `E:/SumikaBuild/wizard-20261008-u/Sumika-Setup-2026.10.08-u.exe` 构建通过，SHA256 `69f71da224f10d53ee6c92a4c531e0c5db1f00d72c902ff35653108d54ee7ffc`。这是内部当前主机验收，不等于清洁来宾、物理音频/视觉/模型质量或真实陪学体验。

参考项目只读检查 `--force --limit 5` 没有模型调用；NEKO/AIRI/Open-LLM-VTuber/Pipecat/LiveKit 均因 GitHub API 403 rate limit 记录 error，不能更新版本事实，也没有自动安装/修改。

复用现有builder和固定runtime/launcher/helper，采用native/cache-fixed EXE构建 `E:/SumikaBuild/product-candidate-20261008-u`，42180文件inventory通过。`candidate-u-capability-report.json`包内能力probe通过。改造已有宿主验收工具加入启动前后inventory断言（报告写包外），`pet-u-runtime-20261008/report.json`实际WPF/WebView2输入/置顶/分层/截图排除检查通过，停止后42180文件内容和清单不变。未打开音频/采集或调用模型。isolated ZIP安装/EXE生命周期与Inno U向导构建中，日用未更改。首次误用desktop隔离解释器`-m tools`因其`_pth`不含checkout而失败；改用系统解释器运行编排工具，包内能力仍由各包内解释器实际验证。

#### 真实宿主发现与修复

T候选42180文件构建和安装向导通过；真实T宿主输入/属性通过，launcher启动/复用/外来端口保护/关闭通过（`E:/SumikaBuild/exe-startup-24a095666d214334b353809e1785591c/report.json`）。随后capability inventory失败：WebView2默认创建EXE旁的`.WebView2`缓存，不能忽略。修改既有 `PetHost.OnLoaded` 使用官方 `CoreWebView2Environment.CreateAsync`，缓存明确放在 LocalApplicationData/Sumika/WebView2/PetHost。发布 `E:/SumikaBuild/pet-host-20261008-cache`，真实宿主检查 `pet-cache-runtime-20261008/report.json`通过；发布目录没有WebView2缓存。S/T均保留失败现场，不当最终交付；下一候选U需要使用cache-fixed EXE并验证启动前后inventory。T安装包仍含旧缓存配置，不建议安装。未执行真实设备/模型/安装验收。

S 的旧归档桌宠 EXE 实际启动失败，退出 `0xc000041d`，Windows .NET Runtime 1026 明确为 WPF 初始化 `DllNotFoundException`。现有发布设置未将原生 DLL 放入单文件产物。`packaging/Sumika.PetHost.csproj` 增加 `IncludeNativeLibrariesForSelfExtract=true`，复用已安装 .NET SDK 发布到 `E:/SumikaBuild/pet-host-20261008-fixed`，不修改 S 包。S 不能再称可用桌宠交付。

改造现成 `verify_pet_host_runtime.py`，报告/隔离 bridge 数据写包外；用实际包内 Python 启动 bridge，查真实 WPF HWND 的 WDA_EXCLUDEFROMCAPTURE、CaptureHost 标记、置顶/分层样式，并等待 UIA 可见编辑框。第一次加载探针过早取到隐藏 Edit，改为等待有效可见框。`E:/SumikaBuild/pet-fixed-runtime-20261008-b/report.json` 通过：窗口510x645（150%系统缩放，对应340x430 DIP），输入376x24物理像素。未录音/截图/调用模型；宿主与临时bridge均停止。仍不证明拖动/穿透/收起、真实问答、模型延迟或学习流程。候选 T 将包含修复 EXE。

复用既有打包器、候选 R 固定 DSH/runtime 和 launcher、物理 desktop/voice runtime、归档 `SumikaPet-20261008-i.exe` 与 process-audio helper，构建 `E:/SumikaBuild/product-candidate-20261008-s`。42180 文件 inventory 通过，`candidate-s-capability-report.json` 的包内路径、依赖/模型加载和 process-audio probe 通过，未打开音频/画面设备。桌宠 EXE 仅纳入候选，不能据此称真实宿主交互验收通过。安装向导由原 Inno Setup 工具构建中；未安装/切换日用/发布。

### 文字与语音会话衔接

S 安装向导已构建通过：`E:/SumikaBuild/wizard-20261008-s/Sumika-Setup-2026.10.08-s.exe`，551797093 字节，SHA256 `a3369fd438c06936266c293d8eb46b5418f42c7b7359e96f99e9e5071fd65cf1`，报告 `build-report.json`。仅证明构建与清单，安装/回退/实际宿主仍待验收。

- 资产判定：改造既有 `MicrophoneProcess` JSONL 单写入管道、worker 最新观察 mailbox、Pipecat `CompanionTurnProcessor._interrupt` 与 bridge 问答；没有另建录音/播放或 UI 入口。
- `text_question()` 串行文字轮次，发送有请求编号的 text_begin/text_end，等待 worker 在取消模型/实际播放器清队列后确认。控制队列优先于最新观察；确认不进入 UI 对话事件。停止/失败唤醒等待者，代际改变不发恢复；启动重置确认序号。10 秒无确认则回收 worker 并明确失败，不继续模型问答。
- Pipecat 设备/worker 保持打开；文字问答期间暂停提交新语音轮次和主动讨论，结束清除跨轮 PCM 并恢复同一管线。文字模型失败也执行恢复；撤销不恢复旧会话。frame 与外部控制通过异步锁串行，避免取消期间新的 VAD turn 抢占。
- 首轮测试失败暴露暂停分支拦截框架同步帧，导致 flush_pipeline 返回 false；改为只阻断 PCM/VAD/InterruptionFrame，保留控制帧。实际 Pipecat Worker 测试确认旧播放 cancelled、文字期间无 ASR/讨论、结束后下一语音可识别；run_session 夹具确认 text_begin/end 与一次 listening。真实子进程管道覆盖重复轮次、模型失败后恢复、重启序号、撤销期间不恢复与唤醒等待。
- 验证：初次 UI/process 57 项通过；最终 process 子集 10 项通过；隔离 voice 环境 Pipecat/worker/voice_answer/scheduler/segmented 共42项通过。无真实麦克风/扬声器/付费服务。当前还有明确限制：文字回答期间开口尚不能取消文字回答并提交新语音提问，后续需跨模式取消与事件协调；不能将本阶段标为完整连续语音体验。当前安装包未包含该改动。
- 2026-10-08 补齐跨模式打断：文字回答期间 `VADUserStartedSpeakingFrame` 清除 text mode、发出 `text_interrupted`，父进程取消该文字问答的 `CancellationToken`；同一 worker 随后接受该轮 PCM。`text_question()` 的 finally 只在原始代际仍有效时发送 text_end，避免覆盖新语音轮次。跨模式测试与 81 项 bridge/process/model/UI 回归通过；真实设备与 provider 仍未验收，当前包未重建。

- 现成资产：改造 `ui/app/index.html` 原桌宠 composer 与 `tools/verify_companion_session_ui.mjs`，直接使用已有问答协议和日志；不新增界面或入口。视觉依据仍为 `ui/prototype-d/index.html` 原桌宠气泡/记录。
- 流式失败或 stale_response 时以失败提示替换本轮临时回答，不保留看似有效的半段内容；禁止转入普通角色聊天或自动重试。28 项浏览器夹具通过，新增过期回答替换、单次问答/零普通聊天、发送按钮恢复检查；340x430 宿主页面截图已查看，证据 `E:/SumikaBuild/companion-session-ui/report.json`。
- 恢复核验推翻摘要中的文字启动疑点：当前 UI 的 text 分支先调用 perception start，再读取 microphone status，从不发 microphone start，所以不需要另加绕过双许可的后端分支。
- 更新 `reference-projects.json` 中 NAudio/Pipecat/NEKO 采用状态，区分已接线与硬件未验收。仍需文字问答中保留连续语音监听、真实宿主与设备/流程、最新版安装包和调研调度验收，整体未完成。
- 后端 `python -X utf8 -B -m unittest tests_next.test_ui_server tests_next.test_companion_contracts` 68 项通过；continuity check/handoff 与 git diff --check 通过。既有 pathlib 弃用、HTTPError ResourceWarning 和 Git 换行提示仍存在。

## 2026-10-08 受管 SAPI 分段播放

### V 候选后续验收记录

- 复用现有打包 bridge、能力卡和浏览器验收方式，新增 `tools/verify_pet_capability_ui.mjs`。实际页面点击验证单一桌宠入口、真实 API 所有权进程、运行中禁止再次启动、关闭回收进程，4 项通过。证据：`E:/SumikaBuild/pet-v-capability-ui/report.json`；截图 `capability.png` 已查看，未观察到重叠。
- V 安装器构建通过：`E:/SumikaBuild/wizard-20261008-v/build-report.json`，SHA256 `e3187da6a99f45fd20cd709f4d139b655e3b1a79de8de9fba8711c6c7174e993`。实际 UI 启停后 V 的 42182 文件清单完整性通过。构建不代表向导安装验收；新增验收工具晚于 V 构建。
- 首次 WebView 输入框等待超时原因仍未确认；再次成功不证明启动稳定性。真实学习内容问答、音轨隔离、设备延迟及完整宿主交互仍待验收，整体计划未完成。

- 新增 `sapi_playback.py`，直接复用既有 `SpeechPlayback` / `ChildJob` 所有权，但 worker 使用 COM SAPI 直接输出，不创建 WAV；每个句段独立子进程，`SapiPlaybackProvider.stop()` 终止并等待该子进程及收尾线程，队列不会泄漏到下一段。
- `build_sapi_study_worker` 将受管 SAPI 播放接入 Pipecat/Vosk/屏幕绑定 worker。服务配置、角色、voice capability 每个段重新校验，禁用或切换 voice 会拒绝播放；没有语音或配置回退。
- 2 项受管子进程回归通过，并与既有 speech playback 8 项、分段播放 3 项通过；测试使用假的子进程，不代表实际 SAPI 设备或选定声音已播放。真实硬件验收仍需在用户允许采集/播放并有 WebView UI 控件后进行。

## 2026-10-08 播放取消竞争与应用音轨路线核验

## 2026-10-08 当前源码候选与模型运行时修复

### 2026-10-08 能力运行时发现路径

### 2026-10-08 物理能力 Python 运行时

### 2026-10-08 候选Q内置能力运行时

- 复用现有打包器构建 `E:/SumikaBuild/product-candidate-20261008-q`，加入物理desktop/voice runtime，42162文件inventory通过。模型权重/个人数据未收录，桌宠EXE仍未作为完成交互交付加入。
- certifi公开CA精确路径例外扩展至python/desktop/voice三个固定目录，同步PowerShell安装器；其他PEM/KEY仍拒绝。17项清单/路径回归通过；安装器公开CA、凭据拒绝、解压中断、长路径、旧安装保护回归通过，证据 `E:/SumikaBuild/installer-check-45999e447cd04fe39e14ba2a21efe4ef`。
- 新增复用验收工具：`python -X utf8 -B -m tools.verify_capability_package <candidate> --output <new-report.json>`，先完整inventory，再分别用包内三个隔离解释器验证模块/路径/模型加载，不打开麦克风或采集屏幕。Q报告 `E:/SumikaBuild/candidate-q-capability-report.json` passed：路径均指Q包内runtime，WGC supported=true，Pipecat适配器/受管SAPI导入和Silero模型加载成功。
- 新验收工具未包含在本轮较早生成的Q清单内，后续重建才纳入。Q仍无产品陪学UI/实际语音服务接线和真实音画验收，也未做此候选EXE安装启动、升级回退或发行；整体目标未完成。

- 复用已验证独立Python基线、桌面requirements.lock和已安装隔离site，新增 `tools/build_capability_runtime.py` 按固定发行元数据复制物理依赖和许可证；不复制开发venv、模型或pyc。PyWin32 DLL显式放置，_pth暴露模块路径但不执行site hooks。
- 桌面运行时 `E:/SumikaBuild/desktop-runtime-20261008`，报告 `E:/SumikaBuild/desktop-runtime-20261008-report.json`：隔离重定位导入PythonCOM/PyWin32/UIA/sounddevice/Vosk/WGC/HTTPX/SSE通过，未打开麦克风或采集画面。
- 增加 `extensions/companion/requirements.lock` 固定已验证Pipecat 1.12.0及语音环境依赖，排除前轮无效WinRT音频实验包。在桌面基线叠加语音依赖时清旧版本已声明文件，避免运行代码和发行元数据版本不一致；失败候选保留，不修改安装环境。
- 语音运行时 `E:/SumikaBuild/voice-runtime-20261008-c`，报告同级 `voice-runtime-20261008-c-report.json`：独立解释器成功导入Pipecat PipelineWorker并加载Silero16kHz模型，SAPI/ASR模块导入通过。仍未打入候选P或完成产品接线。
- 新证据：同进程先windows_capture/OpenCV再ONNX导入，在本机报DLL初始化失败；先Silero再WGC可导入。当前设计为感知/语音独立进程，probe分别验证，不能宣称任意模块混用都兼容。错误输出增加UTF8和replace，避免native错误日志解码掩盖原失败。下一步整包依赖清单、重定位问答、真实生命周期和安装包验收。

- 改造现有 audio_devices.env_python，并新增共享 `extensions/desktop/runtime.py`：显式 SUMIKA_VOICE_PYTHON/SUMIKA_DESKTOP_PYTHON优先；显式无效直接拒绝，不改用其他环境；其后查包内 runtime/voice、runtime/desktop，再查开发环境。没有退回系统Python，也不把基础runtime/python假称具备音频/采集依赖。
- UI单次文本/视觉采集与长驻PerceptionProcess改用同一desktop解释器查找；启动/恢复时重新查找，支持安装目录和明确外置环境。语音仍使用现有配置和权限校验。
- 打包器新增 `--desktop-runtime` / `--voice-runtime`，仅接收物理standalone Python目录，拒绝pyvenv.cfg开发venv；依旧经过完整路径/哈希清单检查。当前尚未构建或验证专用依赖树，候选P也不包含本轮源码。
- 47项运行时/设备/UI/视觉回归通过（1项平台跳过），后续22项路径/设备/inventory测试通过。真实Windows采集与包内能力导入仍需单独验收；最终包、UI、进程音轨和完整连续陪学仍未完成。

- 复用 `tools/build_portable_staging.py`、既有物理DSH runtime与launcher构建当前源码候选N。发现包内Python缺HTTPX，不能据inventory通过宣称流式/取消可用。候选N不作为可用交付。
- 改造 `tools/build_host_runtimes.py`：新增显式dependency-site，固定/复制HTTPX 0.28.1、httpx-sse 0.4.0及传递依赖与licenses，隔离导入probe覆盖模型依赖。生成 `E:/SumikaBuild/host-runtimes-20261008-models`，Python3.14.7/Node24.19.0隔离probe通过。
- O构建被凭据规则拒绝certifi公共CA包；仅为精确路径 `runtime/python/Lib/site-packages/certifi/cacert.pem` 添加例外，同步PowerShell安装器，其他PEM/KEY仍拒绝。14项inventory测试通过，新增公开CA路径与邻近私钥拒绝回归。
- 当前源码候选P：`E:/SumikaBuild/product-candidate-20261008-p`，27856文件inventory_verified；实际包内Python导入httpx/httpx_sse/anyio/certifi及CancellationToken通过。未包含最终桌宠宿主、Pipecat/desktop依赖或模型，不能称完整陪学客户端。
- 安装器夹具初次D盘空间不足，失败现场移动到 `E:/SumikaBuild/archive/package/installer-check-b449991057f04a72a677ca168a2f1b6d`，未删除。给现有工具增加 `--output-root` 后在E盘复跑通过：`E:/SumikaBuild/installer-check-bfdab1f14f914697980a05f349c6da43`，覆盖公开CA精确解压、凭据拒绝、解压中断重试、长路径及已有安装保护，不证明产品EXE启动。
- 产品UI核验：设计稿 `ui/prototype-d/index.html` 948行为桌宠模式预留，当前无陪学控件。尚未新增重复页面或入口；需先补设计和覆盖表再接产品控制。当前仍有语音流式播放/真实硬件、进程WASAPI、UI和最终包验收等未完成项。

- 本轮最终隔离voice组合70项通过。D盘写满导致apply_patch截断本文件，已从Codex本地会话的初始创建和64次可应用补丁重建；有两项失配分别对应先前失败锚点和空锚点，没有直接覆盖历史为摘要。恢复副本 `E:/SumikaBuild/recovered-companion-implementation.md` 保留供比对，重建不能作为逐字原文件一致性的证明。原桌宠EXE移动至 `E:/SumikaBuild/archive/package/SumikaPet-20261008-i.exe`，未删除；旧路径已失效，打包前需使用归档路径或重新构建。D盘仅释放约131MB，后续生成物继续使用E盘。

- 现成资产核验：`soundcard` 0.4.6 仅端点回环，不适合作进程捕获；隔离 voice 环境试装 PyWinRT `Windows.Media.Audio` 3.2.1并检查公开类，AudioGraph/AudioFrame接口不提供进程loopback，不能替代 WASAPI ActivateAudioInterfaceAsync process-loopback。未写假provider或将端点录音放行，进程音轨仍未实现。
- 修复现有 SegmentedPlayback：segment_started回调期间取消后重新检查epoch，禁止旧段启动；直接task.cancel或播放错误也调用实际stop接口；stop回调在cancel等待任务出错时仍执行。新增3项调度竞争/直接取消/设备失败回归，13项播放相关测试通过。
- 修正前轮统计：隔离voice组合实际67项通过（不是70），其中旧speech_playback为5项；本轮新增3项后组合应为70，需实际运行核验。WinRT试装只在E隔离环境，不增加产品依赖。下一步需要真正支持进程回环的成熟原生库或Microsoft示例适配，及音轨隔离实测；语音流式分段与产品接线仍未完成。
- `tools/build_portable_staging.py` 增加可选 `--pet-host`，输出为 `SumikaPet.exe`；当前 F 包未传此参数，避免把未完成交互验收的宿主伪装成已验收产品。下一候选会在单独报告中验证资源清单和运行时缺失行为。
- `tools/verify_runtime_upgrade_rollback.py` 通过：旧版 `0.1.5-rc.2` 与新版 `0.2.0-rc.2` 分别使用匹配 profile 启动并创建会话，profile 路径分离，未执行原地降级或配置迁移。证据 `.sumika-next/runtime-upgrade-161c5b665e784e89897d643b1750c71f/runtime-upgrade-161c5b665e784e89897d643b1750c71f/report.json`（实际报告位于该目录 `report.json`）。


### 2026-10-08 同类项目识屏成本源码核验

复用现有 reference-projects.json、NEKO/Pipecat Git 对象缓存及现有陪学记录，直接使用清单并追加版本化依据；本轮为设计调研，没有修改产品或新增 UI。NEKO c8bf3505 的 screenshot_utils 限制模型图片至1280×720、JPEG q80；proactive_delivery 支持显式合并键、批量投递、播放门控、TTL与图片数量/字节预算；screen_comment_guard 只投影请求历史，抑制确认的连续屏幕描述污染，不等于普遍语义去重。Pipecat 5648cfa3 的 llm_context_summarization 提供阈值摘要，保留初始system、近期消息与未完成工具交互；字符/4和图片固定估算不能当中文/实际provider计费。

Windrecorder df06bfb4 的 record.py 已核验本地画面相似度→OCR→文本相似度两级过滤与配置边缘遮罩；Open-LLM-VTuber 992309c0 的 BasicMemoryAgent 将本次输入图片附到本次请求、普通记忆保存文字并跳过连续同角色同文字，不能推广到所有Agent或工具图片路径。固定提交raw源码核验通过，URL及SHA256已写清单。GitHub API受403 rate limit，改用公开Git ref和固定提交raw作只读核验，未调用模型；其余AIRI/Page Assist/screenpipe本轮没有源码结论。

建议Sumika优先采用活动区域选择、本地变化过滤、正文/字幕/ASR优先、必要图表裁剪及有界近期上下文；弹幕变化不应独立触发持续视觉调用。JPEG字节变小不保证视觉token同比降低，历史摘要自身也有调用成本，需用真实provider usage验证。网站/活动ROI与局部OCR仍未实现，已实现的音轨正文去重不应混称空间差分。

### 2026-10-08 本地感知去重增量

复用现有 `WindowsOCR` 单帧缓存和 `WindowsLearningCollector` 采集链，增加解码RGB像素和尺寸SHA256缓存。编码元数据变化但像素完全相同时复用OCR；像素变化或无法解码时重新识别。未启用近似阈值：32x32整窗灰度比较可能漏掉小区域里的字/公式变化，不能作为正文缓存依据。失败识别不会推进缓存，stop清除原有及新增缓存；不调用模型、不新增UI。

验证：105项陪学测试通过、7项环境跳过，之后最终源码还需重跑。网站活动ROI、局部OCR、真实provider用量及最终包仍未完成。

### 2026-10-08 本地工具升级评估

当前陪学 ASR 仍是 Vosk 小型中文模型。真实 B 站产品音轨已验证管线边界，但教程术语错误明显，首段 final 约 20.32 秒，因此不能称为实时质量。候选和固定版本记录在 `docs/project/reference-projects.json 的 local_tool_upgrade`。

本机是 AMD RX 5700 XT，不能直接采用只针对 NVIDIA CUDA 的部署假设。已在独立目录 `E:/SumikaBuild/local-asr-site-20261008` 安装 `sherpa-onnx==1.13.8`，已下载固定版本 INT8 模型，并通过官方 5.592 秒中文样例 CPU 推理（加载 1.812 秒、识别 0.144–0.151 秒），已加入可取消有界 PCM 适配器；尚未接入产品 worker，未改日用配置。优先候选是 sherpa-onnx 的 SenseVoice，第二候选是 Paraformer；faster-whisper 保留给高质量分段转写，FunASR 保留给离线对照。下一步使用相同 B 站教程片段比较术语命中、partial 首次出现和 final 延迟，合格后才扩展 `CapabilityStore` 的 provider 枚举和 worker 适配，并保留 Vosk 回退。

本地 MiniCPM 2B 已存在且可由 Ollama 使用，适合在内容去重之后做章节摘要、关键点和待问问题；摘要接口 `summarize_learning` 已加入但默认关闭，当前尚未接入陪学生命周期，不应计为已完成的 token 节省。


### 2026-10-08 B站同一 PCM 的 ASR 对比

复用真实 B 站教程进程回环，五个连续 5 秒内存 PCM 同时送入 Vosk 和 SenseVoice，未保存原始音频。SenseVoice 每段解码 0.154–0.172 秒，Vosk 为 1.879–2.717 秒；该样本中 SenseVoice 的中文断句和“求导/单调性”等术语明显更好。证据：`E:/SumikaBuild/bilibili-asr-compare-20261008-a/audio/report.json`。这是一段教程样本，不能外推为所有内容的准确率。

当前 `ApplicationAudioTrack` 是 Vosk 流式 recognizer 契约，不能把离线 SenseVoice 直接冒充 streaming provider。下一步应新增独立的有界 offline-segment capability，明确每段延迟和过期结果处理，再纳入 worker、运行时和模型打包验收；默认仍保留 Vosk，Paraformer 需要继续对照。


### B站场景专项调研（2026-10-08）

复用现有 browser_video_snapshot.js（改造后使用）、browser_video.py/context_fusion.py 与 inspect_companion_bilibili.mjs（直接使用），不创建平行采集系统。本轮只读调研并更新唯一参考清单，没有产品改动。Bilibili-Evolved 固定 fa06dcec 的字幕与弹幕读取/导出源码可借鉴；许可有再分发/支持条件。官方总结可作为视频/分P概览缓存，当前片段需时间附近字幕/音轨和图表补证；可用性未实测。弹幕建议本地去重、按当前时间筛选、与课程事实分开，不能读全量持续送模型。pakku/Bewly 候选源码核验遭 GitHub 限流，标 needs-validation。API-collect 固定 4c00347 的 README 已声明永久关停，旧文档不作当前接口保证。证据：E:/SumikaBuild/bilibili-research-20261008。


### 主要陪学场景优先级（用户明确指定，2026-10-08）

优先 B站视频、微信读书、PDF阅读；这是已批准陪学计划内的优先级调整，非新增UI入口。复用现有 browser_video_snapshot/browser_video/ContextFusion、WindowsLearningCollector/WindowsTextCollector/WindowsOCR 与真实站点/阅读器探针，均直接或改造后使用，不另建平行采集系统。B站先补自定义字幕与播放/分P位置并接候选ASR；微信读书优化可见阅读区域和选择，避免导航当正文；PDF先补可靠当前页/可见页定位，文本抽取仅在文件与页明确绑定时使用，扫描页OCR。共同验收翻页/快进旧回复失效、无变化不重复分析、图表公式保真和真实provider用量，不能用字符数替代token成本。详细验收与资产判定已写入现有 plan/progress/handoff 的 learning_scenarios_priority_checkpoint。本轮仅更新优先级与验收记录，专项实现仍待完成。


### SenseVoice接线与B站图层核验（2026-10-08）

复用现有工厂/worker/能力库/Bridge明确接SenseVoice应用音轨分支，默认仍Vosk。79项回归通过；补诊断后39项及28项通过。隔离新运行时添加固定sherpa依赖，基础语音/Silero导入及官方样例后台线程推理通过；_pth带checkout仅供开发验收。真实B站四次产品探针启动成功但均队列溢出；最新D报告采集20秒、完成解码0秒、首段解码15.01秒，尚未定位停滞原因，不扩大队列、不标实时通过。证据 E:/SumikaBuild/bilibili-product-sensevoice-20261008-d/audio/report.json。下一步采集首段线程栈/耗时定位。

用户要求低音量/无需扬声器和弹幕分离。现有NAudio进程树数字loopback不是麦克风；播放器/浏览器静音与系统音量效果待独立实测。优先不增加虚拟声卡依赖。只读公开B站视频测试已验证video元素可读非黑640x360帧，danmaku-box/wrap在video之外（E:/SumikaBuild/bilibili-video-layer-20261008-a/report.json）；优先直接读取视频帧、弹幕单独去重，不改用户观看布局。动弹幕、全屏、特殊弹幕、公式字符变化和连续产品接线仍待验收。


### 2026-10-08 PDF explicit-page HTTP loop

Reused pdf_learning, existing companion collection/observe/question path, enabled Office skill (pypdf 6.18.1 / ReportLab 5.0.1), and existing PDF verifier. Added kind=pdf collection with explicit consent, absolute path and one-based page. No new UI or guessed reader page. Extraction failure clears prior context; selected text is bounded and labelled pdf-selection. Five PDF tests and 84 related regressions passed. Real HTTP/Office subprocess two-page fixture and local answer prompts verified only the bound page and out-of-range failure clearing, zero paid model calls. Evidence: E:/SumikaBuild/pdf-text-loop-20261008-b/report.json and E:/SumikaBuild/pdf-integration-regression-20261008-a.log. Reader auto-follow, scanned PDF/diagrams, real model quality and relocated package runtime remain unverified; full goal remains active. Record backups retained at E:/SumikaBuild/pdf-text-loop-record-backup-20261008-a because D: has under 1MB free.


### 2026-10-08 B站媒体身份与 seek 防护

复用 browser_video_snapshot、BrowserSkill bridge、ContextFusion 和既有验证工具。快照现在输出不含私有查询参数的媒体身份：页面来源、B站分P、文档实例时间和本地 currentSrc 指纹；播放 seek 期间返回无效且不携带旧字幕/帧。采集器验证身份，ContextFusion 在媒体身份变化时清理应用音频。38项单元回归、Edge生成视频验收及实际B站页面探针通过。实际B站当前无标准字幕 cue，不能据此宣称视频内容已被理解；应用音轨与媒体时钟对齐仍待完成。证据：E:/SumikaBuild/video-media-identity-20261008-a、E:/SumikaBuild/bilibili-media-identity-20261008-a。
### 2026-10-08 弹幕旁路与连续播放融合

继续复用 browser_video_snapshot.js、browser_video.py、ContentChangeTracker 和 ContextFusion。浏览器快照现在只读取有限的可见弹幕节点，将去重后的文本及采集时刻放入独立 metadata，不进入字幕/画面正文；变化跟踪忽略 danmaku 字段，因此弹幕移动不会单独触发视觉模型调用。ContextFusion 按媒体身份拒绝迟到音轨，并按媒体时间倒退或异常大跳、seek 标记、分P/源身份变化清理旧音轨；正常播放时间推进保留近期应用音频。

验证：40 项 browser/context/contracts 单测通过；tools/verify_companion_video.mjs 通过。尚未验证真实滚动/特殊弹幕、B站标准字幕、应用音频媒体时钟绑定、默认 SenseVoice、真实模型延迟和重新打包，不能把本轮改动宣称为完整 B 站连续陪学。

## 2026-10-08 公共依赖预装核验与音频 worker 恢复

- 现成资产：`runtime/browserskill/bsk.exe`（BrowserSkill 0.1.11，直接使用）、`tools/build_portable_staging.py`（直接使用现有白名单打包）、现有桌面/语音独立运行时（复用）。无新增产品入口。
- 核验：打包脚本携带 BrowserSkill 二进制及指定许可证/NOTICE；浏览器扩展连接、命名会话与站点授权仍是独立条件。预装不证明普通浏览器连续采集或网页 AI 异步任务已验收。
- 建议而非新增施工：小型必要运行时随包，浏览器扩展首次使用检查连接，大模型按需安装并允许选择存储盘；登录/read/send/采集许可不由预装自动授予。
- 修复：上轮 D 盘写满截断 application_audio_worker.py，交接时仅恢复了旧 Vosk 版本；本轮恢复 SenseVoice 配置校验、native 依赖先加载再启动 stdin watcher、失败进度和可选栈诊断。29 项 application_audio_process/application_audio/companion_audio_providers 测试通过。临时测试目录改到 E:/SumikaBuild。
- 限制：D 盘只剩约 12MB，仍需处理存储空间；不继续在该盘生成发行包。上轮零字节视频报告不能引用为有效落盘证据，需在 E 盘重跑。媒体身份跨进程绑定及完整陪学/发行验收仍未完成。

## 2026-10-08 音轨媒体身份跨进程绑定

复用现有 worker、supervisor 与 Web 接口。配置身份经过有界 JSON 快照，worker 给转写附启动身份，父进程拒绝身份不匹配的包；同窗口媒体身份改变停止旧音轨。103项相关回归通过。之前错误输入不存在的 test_companion_context_fusion 模块导致一次检查失败，已纠正为 test_context_fusion 后通过。Edge生成视频验证已在E盘重跑，证据见 audio_media_pipe_checkpoint；旧零字节报告无效，不作为验收依据。普通浏览器tab与进程共同绑定、媒体时钟、PDF自动当前页和全目标交付仍待完成。

## 2026-10-08 Edge PDF 当前页跟随

复用 WindowsTextCollector、WindowsLearningCollector 与既有真实 PDF 验证脚本。唯一可见 pageselector 必须有同标题 PDF Document 祖先；采集前后复核页码，变化则清空图文。现有窗口 observation 附 reader_context/page/media_identity，无新增UI。29项相关单测通过；E:/SumikaBuild/pdf-page-follow-20261008-a/report.json 证明真实Edge从第1页到第2页绑定与画面更新。OCR available但未识别夹具页标记，不能声明正文质量通过；同名文件与绝对文件身份尚未绑定，其他阅读器和真实模型未验收。总体目标仍进行中。

## 2026-10-08 PDF 原生可见正文与弹幕问答隔离

改造现有 WindowsTextCollector：已绑定PDF文档下只读可见 Text 子项，读后复核页码，隐藏页不混入。复用已有问答服务；原始弹幕不再进入模型元数据，弹幕单独刷新不取消绑定提问。55项相关回归通过。Edge实际PID不同于启动PID，验证脚本改为核对新窗口专用profile。c验证原生文字/翻页；h验证真实图文与两页独立问答提示（本地回答夹具，零付费调用）。d/e/f/g出现间歇空白/正文未就绪失败，等待和置前未完全解决，原因未确认，不声明稳定性通过。保存旧图重新OCR读到 FIRST PAGE LESSON 和导数句，早先下划线精确匹配不证明OCR未识别；质量评测仍待做。证据与下一步见 pdf_native_text_question_checkpoint。


## PDF readiness guard (2026-10-08)

Existing WindowsTextCollector/WindowsLearningCollector/OCR and PDF verifier were reused. Edge PDF without a verified page selector now returns invalid rather than letting loading chrome reach OCR/question context. A loaded PDF without native visible prose retains bound image/OCR support and never reads generic toolbar ranges as body. 59 focused regression tests passed; E:/SumikaBuild/pdf-readiness-20261008-a/report.json verifies real Edge two-page native text, page navigation and local question scope, with zero paid calls. Intermittent blank rendering cause remains unknown; this successful run does not establish stability. Other reader/title variants, absolute document identity, scan/diagram and real model acceptance remain pending; full plan is not complete.


## Video timeline fencing (2026-10-08)

Reused browser_video_snapshot.js, browser_video.py, ContextFusion and the existing video/site verifiers. Passive WeakMap bookkeeping tracks video-element instances and seeking/emptied events without changing playback, tracks or fetching page resources. Even a completed 0.05-second seek between snapshots changes media identity; repeat snapshots stay stable. Same-source element replacement fences prior context. Fusion rejects unbound transcript identity against a bound visual. 115 regressions passed; real Edge evidence: E:/SumikaBuild/video-timeline-20261008-b/companion-video-5e5d314d-d8e4-43e8-85b7-b77087b74e83/report.json. Public Bilibili evidence: E:/SumikaBuild/bilibili-timeline-20261008-a/report.json. BrowserSkill 0.1.11 help confirms listing user tabs does not allow evaluating them; ordinary-browser transport remains incomplete and needs browser-side integration. Timeline events do not establish audio/video timestamp alignment or native tab/PID proof. No real model/voice acceptance claimed.


## 2026-10-08 SenseVoice application-audio Silero segmentation

Reused existing audio track/provider/worker and live verifiers, Pipecat 1.12.0 bundled Silero and explicitly selected SenseVoice. Exact 512-sample VAD frames, bounded pre-roll, silence endpoint and minimum speech avoid decoding quiet-only input; approximately five-second cap and max-two decoder queue bound work. No new model download, UI or default-provider switch. 101 regressions passed. Real public Bilibili runs c and d passed pause/resume, seven transcripts, silence segmentation, retained valid visual after audio stop, late-audio rejection and full withdrawal. Run d now requires an actual silence endpoint. Evidence: E:/SumikaBuild/bilibili-vad-20261008-d/report.json and audio/report.json.

Prior run b lost visual context and the verifier dereferenced None. Added bounded perception/fusion presence diagnostics and null-safe failure checks that still require valid retained visual. The original disappearance cause is NOT confirmed or fixed; successful runs are not stability proof. Continuous speech remains split at the duration cap, media position is unknown, ordinary-browser/audio binding and real-model/voice/installer gates remain incomplete. Current code used packaged runtimes but was not rebuilt into a final installer. Full approved goal remains active.


## 2026-10-08 Edge PDF absolute document identity

Reused the existing WindowsTextCollector and PDF real-window verifier. When a visible native Edit sits under an Edge ToolBar and outside all Document nodes, its actual local file URL/path is normalized into reader_context.document_path. Missing/ambiguous/remote identity stays unknown; optional expected_document rejects a known mismatched path. 36 focused and 120 broader related regressions passed (one skip). Real ordinary Edge window verified the absolute path on pages 1 and 2, visible-page-only text/image and local question scope; zero paid calls. Evidence: E:/SumikaBuild/pdf-identity-20261008-a/report.json.

Limitations: native address exposure varies across browser/reader versions; unknown identity does not claim file verification. A second same-name live PDF rejection, scans/formulas, intermittent blank startup, real model/voice, ordinary-browser Bilibili and final release/rollback remain unverified. Overall approved plan remains active.

Validation correction: a follow-up edit briefly introduced IndentationError after the first 120-test pass; restored the original query guard indentation and reran the full related suite. No failed import result is treated as a pass.

## PDF same-name navigation acceptance (2026-10-08)

## Image-only PDF acceptance (2026-10-08)

## PDF viewport crop (2026-10-08)

## Chinese/math scanned PDF (2026-10-08)

## Real PDF vision provider (2026-10-08)

Reused provider verifier, crop/HTTP/RoleChat and configured DeepSeek deepseek-flash. Added --enable-multimodal in isolated settings only and --expected-pdf requiring verified native absolute identity before model admission. Daily image setting remains false. Real derivative scan run d accurately explains Chinese, f(x)=x² and f'(x)=2x, curve and absent axis scales; 4.762-second total response and 4390 reported tokens. Run c also correct, 6.159s/4817 tokens, but exact FIRST precheck failed on OCR FI RST; do not claim that precheck passed. Run b used nonexistent fixture and answered file-not-found page; not formula evidence. Evidence E:/SumikaBuild/provider-vision-20261008-d/report.json. Only owned test browser operated and closed, credentials parsed without output, memory disabled. No latency percentile or text-versus-image cost claim. Integral page, ordinary-browser Bilibili, continuous voice and full DSH/release remain pending.

Reused existing PDF generator, MS YaHei font, ReportLab/Pillow, crop/OCR and question service. Real image-only two-page Chinese lessons tested in owned Edge. Both lesson sentences recognized by WindowsOCR; current-page isolation and navigation pass. Saved cropped images visually inspected: derivative/integral formulas and curve preserved; local multimodal callback receives exact current image. Evidence: E:/SumikaBuild/pdf-chinese-math-20261008-a/report.json. Both exact formula OCR checks FAILED (integral J, superscript/prime/bracket errors); native reader OCR can omit formula. Existing question prompt now treats reader text as potentially OCR too, asks image confirmation and uncertainty without readable image. This does not fix OCR or prove real model behavior. 37 contract/PDF/voice-answer regressions passed with one skip. Full approved goal and real-model/voice/browser/release gates remain incomplete.

Reused UIA text collector, WindowsLearningCollector and existing PDF scan verifier. Unique visible PDF Document bounds are checked before/after capture; DWM extended-frame dimensions must exactly match WGC. This corrects the verified UIA outer-window invisible border mismatch (1257x1338 versus WGC 1239x1329) without arbitrary cropping tolerance. Missing/changed/mismatched regions retain full-window fallback. Crop supplies model/OCR image with window-pixel source bounds and cropped normalized OCR space. Real --require-region scan run E:/SumikaBuild/pdf-region-20261008-e/report.json passed both pages: 1224x1071 crop, current page marker and prose only, no browser filename/chrome. Earlier region runs retained full frame and are not crop evidence. Other DPI/layout/move/resize, formula accuracy and full release unverified; native UIA prose may still include loading announcement and OCR of/0f error persists. Full approved goal active.

Extended the existing PDF verifier with a ReportLab/Pillow raster-only fixture and scan-specific marker checks. Real owned Edge run E:/SumikaBuild/pdf-scan-20261008-b/report.json proves no extractable PDF text layer, absolute file/page identity, page-only local question prompts and visual navigation. Edge itself supplies OCR-derived UIA prose. Independently ran existing WindowsOCR on both actual captured frames: correct current-page markers, absent other-page marker. First run failed exact markers because Edge split FIRST/PAGE with spaces; verification now ignores whitespace only for scan markers, without rewriting product text. Both engines still exhibit of/0f error; local OCR includes browser chrome. No formula/Chinese scan quality, real model, continuous voice or full release claim; approved goal remains active.

Reused existing collector, native address identity, ContextFusion and real Edge verifier. Owned Edge rejects a different absolute path with the same basename and accepts the matching path; actual navigation to the second same-name file replaces identity, rejects the old expected path and clears prior audio references. Audio was a synthetic transcript attached to real captured identities, not actual PDF audio. Added absolute PDF expected-path validation and Windows path comparison. 37 focused regressions passed. Evidence: E:/SumikaBuild/pdf-same-name-20261008-b/report.json. No UI or upstream changes. Continuous-worker expected-path binding, scans/formulas, real model/voice and full release remain incomplete; earlier missing live same-name evidence is now superseded by this checkpoint.


## DSH populated profile migration and rollback (2026-10-09)

Reused Dsh, existing recovery helpers and ModelFixture. Extended tools/verify_runtime_upgrade_rollback.py with a stopped populated-profile path: old 0.1.5-rc.2 creates a real 16-record session, writes a marker and fixture response, then the profile is copied to isolated 0.2.0-rc.2. New runtime reopens the same session without another model request; all content, sequence, time and source sections remain equal. The only accepted projection is the built-in source label changing from plugin @deepseek-ai/dsh-system-prompt to system-prompt/runtime-context. Old profile bytes, unrelated patch entries and rollback history remain intact. Evidence: E:/SumikaBuild/dsh-profile-migration-20261008-c/report.json.

Two initial comparisons correctly failed until the source projection was characterized; the comparator now changes only kind/removes legacy plugin field and rejects section/content changes. This is an isolated stopped-profile migration fixture, not an in-place installer upgrade or daily switch. Daily DSH remains 0.1.5-rc.2.

39 actual DSH/continuity/extension/reconcile regressions passed. Initial invocation named nonexistent test modules and failed; actual test files located with rg and rerun. Continuity and diff checks passed.
# 当前源码候选包门槛（2026-10-09）

复用现有 staging、能力探针、安装验收、个人数据管理和 DSH 插件生命周期工具，构建并检查 `E:/SumikaBuild/product-candidate-20261009-ab`。42342 文件清单、包内能力探针（含进程音频）、隔离 ZIP/EXE 安装与启动、隔离个人数据迁移，以及插件安装/启停/卸载/不兼容拒绝均通过。证据分别保存在 `E:/SumikaBuild/candidate-ab-capability.json`、`E:/SumikaBuild/packaged-install-63a484eef7114d3889c4da38b30512aa`、`E:/SumikaBuild/data-migration-80c239238f344924866416763725834d` 和 `.sumika-next/plugin-lifecycle-069a1818a85f439eba982892168078ad`。

当前源码桌宠宿主已用 dotnet publish 构建并纳入候选。这仍是当前主机隔离验收，未完成干净机器或 OS 沙箱验收；日用 DSH `0.1.5-rc.2` 与 profile 未修改。B 站普通浏览器连续传输、音画绑定、连续语音/TTS 和最终发布门槛仍未完成。

同日用候选 AB 做了真实拥有的 B 站窗口音频实测：SenseVoice 转写、视觉融合、停止清理、撤销和迟到事件隔离通过；证据为 `E:/SumikaBuild/bilibili-audio-live-20261009-b/audio/report.json`。外层暂停/恢复静音端点仍失败，所有分段以 duration limit 结束，说明播放器暂停后的进程音频尾部尚未与 VAD 静音状态可靠绑定。验收器已保留有限的 3 秒排空窗口，但不能因此宣称暂停静音已完成；下一步是绑定播放器暂停/媒体时钟或在暂停时明确隔离应用音频。

随后补上了可恢复的应用音频暂停契约：`ApplicationAudioProcess.pause()` 会停止并清空当前 worker、撤销旧 epoch，状态明确返回 `paused`；下一次 `start` 建立新 epoch。HTTP `/api/companion/audio` 的 `action: pause` 已接线，前端状态文案也能显示“已暂停”。18 项进程音频测试与 73 项音频/服务回归通过。该契约已具备，普通播放器/BrowserSkill 适配器尚未把真实 `video.paused` 事件接入调用端。

又增加了通用 `/api/companion/media-state` 边界：拥有播放器适配器可提交 `playing`、`paused`、`seeking` 或 `ended` 及目标身份；暂停/跳转/结束会在目标匹配时 fence 应用音频并清除融合上下文，播放不会自动重启旧音频。75 项服务/音频回归通过。BrowserSkill 的实际视频事件和普通窗口 WGC 的播放器状态仍需接入这个端点。

BrowserSkill 视频入口现已自动使用快照中的 `paused/seeking/ended` 状态调用该边界，再发布视频观察；无对应音频 owner 时只记录观察，不会误停其他窗口。真实 BrowserSkill 页面仍受 0.1.11 的 Agent Window 范围限制，普通用户浏览器链路仍需单独接入。

普通视觉观察入口也统一读取 `metadata.media_state`（或 `paused/seeking/ended`），在有相同目标的应用音频 owner 时执行同一 fence；因此 WGC/播放器适配器只需提供状态，不再复制生命周期逻辑。77 项 UI/server/音频回归通过。


## 2026-10-09 桌宠宿主与陪学入口最终候选验收

- 复用当前源码 `SumikaPet.exe`、既有 `verify_pet_host_runtime.py`、候选包内 bridge 与 `verify_pet_capability_ui.mjs`；没有新增入口或并行宿主。
- 候选 `E:/SumikaBuild/product-candidate-20261009-ad` 的陪学能力 UI 通过：桌宠模式只有一个能力入口，真实 API 启动/停止、重复启动禁用、UI 关闭回收通过。证据：`E:/SumikaBuild/pet-capability-ui-ad-20261009-run2`。
- 真实 WPF 宿主通过：单窗口、置顶/分层样式、`WDA_EXCLUDEFROMCAPTURE`、CaptureHost 标记、WebView2 输入框加载、键盘输入、拖动 80×60、84×84 收起/恢复、API 停止回收及 42342 文件包完整性均通过。证据：`E:/SumikaBuild/pet-host-ad-20261009-run5/report.json`。
- 验收器补充显式 UIA 控件聚焦，修复 WebView2 宿主由隔离 API 启动时键盘探针的间歇性焦点失败；99 项桌宠/UI/陪学回归通过。该修复只影响验收工具，不改变 DSH 上游或产品入口。
- 仍未完成：普通用户浏览器 B 站媒体状态传输、音画时钟绑定、连续麦克风打断/TTS 延迟、干净机器验收和最终日用切换。

## 2026-10-09 BrowserSkill 普通用户标签页接入准备

- 核对随包 BrowserSkill `0.1.11` 实际 CLI：除 `user` 标签页 inventory 外，还提供显式 `tab borrow`，可把用户标签页借入选定 Agent Window。此前“普通标签页只能 inventory”表述应限定为“不能直接 evaluate”；借入仍是用户可见的独立授权动作。
- 复用现有 `BrowserSkillClient`，增加带 scope 校验的 `session_tabs(session_id, scope=...)` 和 `borrow_user_tab(session_id, tab_id)`。借入前必须从 `scope=user` inventory 中找到唯一 tab；不会因 read 授权、视频采集或后台轮询自动借入。
- 新增适配器回归覆盖：无效 tab、未列出的 tab、CLI 响应解析、用户 scope 命令参数和显式借入调用。BrowserSkill/绑定/视频相关 25 项测试通过。
- 当前只完成安全底层能力，尚未把借入动作接入陪学 UI/API，也未在用户正在使用的浏览器或游戏桌面上执行真实借入；真实 B 站普通浏览器媒体状态、音画时钟绑定仍未宣称完成。
- 根据本轮 BrowserSkill 适配器与宿主验收工具修复，重建当前源码候选 `E:/SumikaBuild/product-candidate-20261009-ag`：42342 文件清单、包内能力探针（含进程音频）和陪学能力 UI 通过。证据：`E:/SumikaBuild/candidate-ag-capability.json`、`E:/SumikaBuild/pet-capability-ui-ag-20261009`（实际目录名以命令输出为准）。未重做会影响桌面输入的宿主鼠标验收；此前 AD 宿主证据仍有效。

## 2026-10-09 授权写入与桌面输入安全门

- 复用现有 `BrowserSkillClient._write` 原子替换；将 Windows WinError 5/32/33 的短暂共享冲突限定为最多 5 次同一 `os.replace` 重试，永久失败不复制覆盖、不破坏旧授权，临时文件始终清理。
- 隔离写入探针在 `.sumika-next` 和 `E:/SumikaBuild` 各执行 200 次，0 错误、0 残留临时文件。证据：`E:/SumikaBuild/browser-atomic-write-20261009.json`。扩大管理回归仍偶发角色导入 WinError 5，属于另一条文件操作，未宣称全局解决。
- `verify_pet_host_runtime.py` 现在要求显式 `--allow-desktop-input` 才能使用 `--input/--drag/--compact`；未授权时在启动前拒绝且不创建输出目录，避免在用户游戏/工作时触发全局鼠标键盘。
- BrowserSkill 用户标签页借入的管理 UI 接线已撤回：借入会移动用户标签页，不能默认视为现有浏览器陪学方案。底层 `borrow_user_tab` 适配器与离线测试保留，待明确产品交互后再接入。

## 2026-10-09 候选启动器格式门槛与无输入回归

- 发现上一候选 AG 的 `Sumika.exe` 实际是 PowerShell 脚本（UTF-8 BOM），此前能力探针未检查启动器格式；AG 不作为可安装候选。
- 改造 `tools/build_portable_staging.py`：`Sumika.exe`、`SumikaPet.exe`、进程音频 helper 均必须是物理 PE 文件（MZ + PE\\0\\0），脚本改名会在 staging 前拒绝。新增测试覆盖脚本、无效 PE 偏移和缺失 PE 头。
- 用已验收的 EXE 重建候选 `E:/SumikaBuild/product-candidate-20261009-ah`：42342 文件；PE 头、包内能力探针、包清单和桌宠能力 UI 通过。证据：`E:/SumikaBuild/candidate-ah-capability.json`、`E:/SumikaBuild/pet-capability-ui-ah-20261009`。
- 47 项便携包/BrowserSkill/绑定/视频/桌宠回归通过；没有运行全局鼠标、键盘、麦克风或真实浏览器借入。

- 本轮全量回归：`python -X utf8 -B -m unittest discover -s tests_next -q` → Ran 868 tests, OK (skipped=16)。既有 ResourceWarning/DeprecationWarning 保留，未新增声称跳过项已通过。AH 安装/EXE 生命周期尚未重跑，不能沿用 AD 安装结果；完整目标仍未完成。

## 2026-10-09 AH 实际安装与 EXE 生命周期

复用 `verify_packaged_install.py`、实际 `install_sumika.ps1` 和 `verify_portable_exe.py`，独立数据目录，EXE 使用 `-NoBrowser`。完整归档字节与清单匹配，安装后 42342 文件一致；首次启动、重复实例复用、外来 HTTP 200 端口拒绝/保留、认证 shutdown 与进程退出均通过。测试 bridge 已停止。证据：`E:/SumikaBuild/packaged-install-497a832ebe2540e895ea2c4754ffc2b4/report.json` 及其中 EXE 子报告。未修改日用配置，无模型调用、浏览器窗口或全局输入。

此结果仅证明当前主机 ZIP/PowerShell 安装与实际 EXE 生命周期，不覆盖 Inno 向导、干净机器、覆盖升级/回退或真实陪学质量。普通浏览器 B站、音画时钟、连续语音/主动讨论及总交付仍未完成。


### 2026-10-09 PDF continuous expected-document binding

Reused existing WindowsLearningCollector, PerceptionProcess, worker and HTTP start API. Optional absolute PDF path is validated before existing collectors are stopped and is retained across pause/resume, cleared on stop/new start. Worker forwards it into a fixed collector without losing start/stop hooks. Known different document returns no text/image; unknown identity remains unverified. Offline lifecycle, collector and HTTP tests pass (75 initial tests; 17 focused after API regression, one existing skip each). No UI added, live capture/device test or candidate rebuild claimed. Next: owned continuous PDF acceptance and ordinary-browser Bilibili/media-clock integration.


### 2026-10-09 Bilibili audio media-time projection

Reused browser video media time/playback rate and existing process audio/media-state fence. The initial observation anchor is forwarded to the application audio worker; ASR transcript observations carry a bounded estimated media_time_seconds and media_position_known. Pause, seek, ended and media identity changes still explicitly stop and clear audio. Offline application audio/process/UI/context regressions pass; this does not prove exact clock synchronization or ordinary user-tab transport.
 Added ContextFusion stale-reference fencing: anchored audio more than 15 seconds from current video time is dropped; 43 audio/process/fusion tests pass.

### 2026-10-09 BrowserSkill protocol skew audit

The installed daemon reports BrowserSkill 0.1.11/protocol 1.1 while the connected Edge extension reports 0.3.2/protocol 1.3. Local updater scratch binaries were hashed and left untouched because they have no trusted pinned source/version manifest. No daemon, session, or user tab was started or moved. Keep the pinned pair and ordinary user-tab inventory-only boundary until a matching release or browser-side connector is available.


### 2026-10-09 Ordinary browser tab capability boundary

Inspected installed BrowserSkill 0.1.11: user tabs support inventory and explicit borrow into an Agent Window, while evaluation remains Agent Window-only. Added `user_tab_capabilities()` to expose inventory/evaluate/borrow requirements without changing browser state. No UI/API borrow entry, tab move, focus, session or microphone was used. BrowserSkill/video/UI regressions and continuity checks pass. Ordinary user-tab clean-frame transport remains a real integration gap.


### 2026-10-09 Settings atomic-write resilience

The full regression exposed one Windows WinError 5 during settings `os.replace`. Reused the BrowserSkill atomic-write policy: bounded retries for WinError 5/32/33, no copy/truncate fallback, previous settings preserved on permanent failure, temporary file cleaned. Added focused tests. Full `tests_next` now passes 875 tests with 16 skips. Candidate package rebuild remains pending.


### 2026-10-09 Current-source candidate AI

Rebuilt `E:/SumikaBuild/product-candidate-20261009-ai` from current source using existing AH physical PE host assets and pinned runtimes. Inventory verified 42,342 files; packaged desktop/voice/process-audio capability probe passed (`E:/SumikaBuild/candidate-ai-capability.json`). This does not yet claim AI install lifecycle, clean-machine, UI/plugin, device, ordinary-user-tab or final release acceptance.


### 2026-10-09 AI candidate archive/install/EXE acceptance

Ran the existing isolated package verifier against `product-candidate-20261009-ai`. Archive and installed inventory each contain 42,342 matching files; SHA256 is `cb492dc4f185cae95d9b06fe0c8abd56e7b6d0ebdb940e153396fc92d3b04f51`. Actual installed `Sumika.exe` passed first launch, duplicate instance reuse, foreign HTTP 200 port rejection/preservation and authenticated shutdown. Report: `E:/SumikaBuild/packaged-install-abf5b5ab5e044998b62ad8e9e4ebd6b4/report.json`. This remains current-host acceptance only; clean-machine, upgrade/rollback, UI, device/voice and full companion gates remain.


### 2026-10-09 AI candidate DSH plugin and profile migration

Ran plugin lifecycle against AI candidate DSH runtime: compatible install/toggle/uninstall, incompatible rejection, failed-install restoration and unrelated config preservation passed with zero external model calls and no daily profile change. Ran populated isolated `0.1.5-rc.2` to `0.2.0-rc.2` migration: 16 history records/content preserved, no model replay, old profile bytes retained, rollback history identical. Evidence: `.sumika-next/plugin-lifecycle-30115043411043b5ba91b9aa3e8f1e42` and `E:/SumikaBuild/dsh-profile-migration-20261009-ai.json`.


### 2026-10-09 Media anchor validation

Added shared validation for browser playback rate and application-audio media anchors: finite nonnegative media time and finite playback rate in `(0,16]`; invalid values fail before an audio worker is spawned. This protects the existing estimated media-time projection and fusion fence. 53 focused tests pass. Candidate rebuild is pending.


### 2026-10-09 Candidate AJ media validation delivery

Rebuilt current-source candidate `E:/SumikaBuild/product-candidate-20261009-aj` with bounded media-anchor/playback-rate validation. Inventory and packaged desktop/voice/process-audio probes passed (`E:/SumikaBuild/candidate-aj-capability.json`). Isolated ZIP/PowerShell install and actual EXE lifecycle passed; 42,342 files matched, SHA256 `bf74c2e7aa76aa80baf7fe33d4e572b1d3c09574dbc1988b99a0814c2a06383a`, report `E:/SumikaBuild/packaged-install-0eda5c95553a43c0b41e2656f6ce391a/report.json`.


### 2026-10-09 Proactive discussion failure state

ObservationScheduler now catches proactive model/TTS callback failures, clears pending content, returns `proactive_error`, exposes a structured `error` property and calls an optional `on_error`; stop clears the error. This keeps a failed discussion from silently killing the background companion loop. 28 scheduler/microphone-worker/Pipecat tests pass (12 existing skips). Candidate rebuild and real UI/device reporting remain pending.


### Proactive error transport correction (2026-10-09)

Async model/TTS failures already use Pipecat `_respond` error events; scheduler guard covers synchronous start callbacks. Wired this guard to existing nonfatal error events (`stage=proactive_start`), exposing only exception type. 29 tests passed in packaged voice interpreter with source modules from workspace and zero skips; 24 scheduler/parent-process tests passed. Evidence: E:/SumikaBuild/proactive-worker-source-20261009.txt. This is pipeline/fixture evidence, not hardware or latency acceptance. AK predates latest worker wiring; consolidate next rebuild after major integration progress.


### 2026-10-09 Continuous PDF live verifier and input gate

Extended existing verify_companion_pdf.py with --continuous, exercising actual perception child process binding, pause/release, resume/rebind, stop/clear and same-basename alternate-path rejection. It retains only bounded status facts. Existing live Edge path uses focus and keyboard, so now requires explicit --allow-desktop-input before native imports/output/browser launch. Rejection probe created no output; 16 perception/learning tests OK (one existing skip). Actual live continuous acceptance remains pending a desktop testing window; no hardware or visual acceptance claimed.


### 2026-10-09 Candidate AL consolidated delivery

After the scheduler error transport and PDF verifier input gate changes, full `tests_next` passed 879 tests with 17 skips. Rebuilt `E:/SumikaBuild/product-candidate-20261009-al`; inventory (42,342 files), packaged desktop/voice/process-audio probes, isolated install and EXE lifecycle passed. SHA256: `53f2daf0884caafe78aa0c1c8f18052dffbf671ab0fff3629d09007089af97ea`. Report: `E:/SumikaBuild/packaged-install-01084c7007dc4044b16ca2ce42424de0/report.json`.


### 2026-10-09 Application audio clock claim correction

Process loopback PCM has no player media clock and may emit no packets during pause/silence. Removed the prior false projection that marked PCM offsets as known video time. Transcripts now explicitly carry `media_position_known=false` and `media_time_seconds=null`; media identity plus paused/seeking/ended fences remain authoritative. 44 application-audio/process/fusion tests pass. Candidate AL predates this correction.


### 2026-10-09 AM audio-clock correction packaged regression

Rebuilt AM using existing AL PE assets/runtimes. 42,342-file inventory and capability probes passed; audio/worker/scheduler hashes match source. Added nonzero-anchor/double-rate regressions for both Vosk and SenseVoice ensuring PCM offsets are not video time. 45 focused source tests pass; 14 tests executed against AM packaged audio module using bundled interpreter pass (E:/SumikaBuild/am-audio-regression-20261009.txt). Initial provenance check failed only on Windows path separators, corrected to resolved Path containment. No install lifecycle or exact media clock claim; consolidate packaging after learning integration.


### 2026-10-09 Passive original-tab ingress (browser-side integration pending)

Pinned BrowserSkill upstream `f8b9786d9dd8ac121c9625ef00b9f80f294006e9` explicitly calls `enforceAgentWindow` before evaluate. Corrected the earlier suggestion that a matching daemon/extension release might enable in-place evaluation. Native adapter remains unchanged. Source and MIT license evidence recorded in reference-projects.json; GitHub REST was rate-limited, git source access succeeded.

Reused browser_video_snapshot.js and extracted browser_video_observation validation for both transports. Added independent PassiveBrowserConnection and scoped Bridge ingress. Normal CSRF management admits explicit extension/tab/Bilibili scope; grants stay in memory, expire at 30 minutes, and reject replayed, stale, cross-origin and incomplete packets. Page fields cannot set observation target or authorize tools. Pause clears context; resume rotates token; revoke/shutdown/source change fence queued packets. A watchdog clears stale context after ten seconds without heartbeat. The push bearer is valid only for /api/companion/passive-browser/push, never other management/observation APIs. No website CORS or new UI entry added.

Validation: 90 passive/browser/fusion/UI-server tests executed OK without skips. Extended existing headless real-video verifier with --passive-bridge: generated video plus actual collector -> isolated HTTP Bridge, DOM danmaku changes do not change JPEG; replay/pause/old-token/stop behavior verified. Evidence: E:/SumikaBuild/passive-browser-20261009/companion-video-898b97e9-03e7-4d72-8a4d-e1ce09b690f5/report.json. The origin header is a protocol fixture, not an installed extension proof. No real website/model, OS process binding, player audio clock or device acceptance claimed.

Next: browser-side MV3 passive prototype in an isolated runtime directory, real service-worker HTTP/Origin test and original-tab scope. Consent integration must reuse existing design-backed capability controls; any new UI requires design approval. AM package remains older than this source; consolidate packaging after integration.


### 2026-10-09 Isolated MV3 passive connector

Added `tools/build_passive_browser_prototype.mjs`, an isolated Manifest V3 research extension generated outside the product UI. It reuses the fixed `browser_video_snapshot.js` collector in a Bilibili-scoped content script. The service worker checks the selected original tab/window, URL and sender frame, sends normalized snapshots only to the loopback Bridge, stops on tab navigation/close, and keeps no token on disk. It has no arbitrary evaluate, page-facing external API, tab movement, focus, click or keyboard input.

Extended `tools/verify_companion_video.mjs --passive-extension`. Actual headless Edge loaded the generated extension; content script -> service worker -> Bridge push succeeded, the current observation bound a question, original tab/window remained unchanged, and pause/resume/stop lifecycle rejected stale packets. Evidence: `E:/SumikaBuild/passive-mv3-20261009/companion-video-adf35f77-4cad-4162-af1e-2976b056d6c2/report.json`. This is an isolated local Bilibili-shaped fixture, not real-site or production UI acceptance.


### 2026-10-09 Passive observation deduplication

Passive ingress now hashes media identity, subtitle text, video JPEG, separate danmaku and playback state. Repeated packets still advance the sequence and heartbeat lease but return `unchanged` without republishing context; a cue/frame/danmaku/state change publishes a new observation. Pause/resume resets the signature. 91 focused tests and the actual Edge MV3 verifier pass. Evidence: `E:/SumikaBuild/passive-mv3-20261009b/companion-video-aa421d2b-197b-4e4a-a397-2538afd5c532/report.json`.


### 2026-10-09 Real public Bilibili passive transport

`tools/verify_bilibili_passive_live.mjs` opened public `BV1Lf4y1M72V` in a fresh isolated Edge profile and loaded the generated MV3 prototype. The actual page video element crossed content script -> service worker -> loopback Bridge (`accepted=1`); the question endpoint returned the bound passive target. No login, input, microphone, model call or daily profile was used. Evidence: `E:/SumikaBuild/bilibili-passive-live-20261009/report.json`.

The page exposed no current TextTrack subtitle, so the bound question text was empty. This accepts real frame transport and target binding only; it does not accept visual model quality. Next is frame-only multimodal question handling with bounded change-triggered calls, followed by real application-audio/clock and voice gates.


### 2026-10-09 Real Bilibili verifier gate correction

The real-site verifier now records frame state and requires a non-empty answer to claim visual question success. Rerun on public `BV1Lf4y1M72V` proves `has_frame=true`, `video_element_available`, and Bridge target binding, but fails the answer gate because the page has no TextTrack captions and the isolated callback returned empty text. Evidence: `E:/SumikaBuild/bilibili-passive-live-20261009b/report.json`. This is a deliberate correction: transport success is not content-understanding success.


### 2026-10-09 Real Bilibili multimodal frame answer

Ran the real public Bilibili verifier with an explicit isolated model gate and the existing DeepSeek credential file. The page had no TextTrack captions, but the clean video-element JPEG travelled through the MV3 connector into Sumika and `CompanionQuestionService` with multimodal enabled. `deepseek-flash` returned a non-empty Chinese visual answer bound to the passive target in 1.726s; reported usage was 3159 total tokens. Memory was disabled and no credential was written to the report. Evidence: `E:/SumikaBuild/bilibili-passive-vision-20261009/report.json`. This proves one real frame-answer path, not broad visual quality, P95 latency, proactive discussion, exact audio clock, voice, UI or release completion.


### 2026-10-09 Passive sampling and heartbeat budget

Added a lightweight heartbeat packet for the MV3 connector. The content script checks playback state/subtitles every second, sends a full observation immediately on state/content change, and limits unchanged JPEG sampling to the first poll and every fifth poll. The Bridge renews the grant lease without publishing context for heartbeats and rejects heartbeats before the first accepted observation. Continuous publication uses the current collection generation so later changed content remains bound to current questions.

Real public Bilibili run: 6 accepted packets over 12 seconds, 2 full-frame uploads and 4 heartbeats; transport passed, no model call. Evidence: `E:/SumikaBuild/bilibili-passive-heartbeat-live-20261009d/report.json`. MV3 fixture confirms unchanged content sends heartbeat without JPEG and changed cue updates Bridge after the initial generation; 93 focused regressions pass. Existing real multimodal frame-answer evidence remains `E:/SumikaBuild/bilibili-passive-vision-20261009/report.json`.


### 2026-10-09 Heartbeat and changed-content acceptance correction

The passive MV3 prototype now checks cheap playback/subtitle state every second. It sends a full observation immediately when that state changes, and unchanged content emits only a heartbeat; a JPEG is sampled on the first poll and every fifth poll as a bounded fallback. Bridge heartbeats renew the grant without changing model context. Continuous publication uses the current collection generation, preserving later changed observations after a question.

The real public Bilibili transport run accepted six packets in 12 seconds (two full frames, four heartbeats); the no-model question is deliberately a transport-only result. The fixture verifier proves unchanged-heartbeat and changed-cue updates. 93 focused tests pass.


### 2026-10-09 Capture clock metadata preservation

Inspected the existing NAudio `DataAvailable` callback: it receives `devicePosition` and `qpcPosition`, but the old helper discarded both. The native helper now sends bounded nonnegative positions with each PCM packet; `ProcessAudioCapture` validates and exposes optional `on_timing`; Vosk and SenseVoice freeze the latest capture clock into each segment's metadata. This remains capture timing only: `media_position_known=false` and player `media_time_seconds=null` are unchanged. Backward-compatible capture test doubles without timing fields still work. 40 application-audio/process/application-process tests pass. Existing packaged helpers/candidates predate the change and require a consolidated rebuild.


### 2026-10-09 Native audio clock build and validity

Built the new ProcessAudio helper with locked NuGet dependencies using .NET 10.0.100. Native probe plus START/process-identity rejection passed. Metadata now includes WASAPI timestamp-error/data-discontinuity flags; missing native clock clears the previous value. `capture_clock` explicitly refers to the native packet start, not a segment boundary or player timestamp. SenseVoice queues freeze the clock before recognition so later PCM cannot overwrite it. 54 audio/process/fusion tests pass, including blocked offline decode and invalid timestamps. Evidence and helper/source hashes: E:/SumikaBuild/process-audio-clock-build-20261009.json. No actual device clock capture, player correlation or current candidate replacement is claimed.


### 2026-10-09 Actual native process clock capture

Added tools/verify_process_audio_clock_live.mjs, reusing the owned Playwright/Edge launcher and ProcessAudioCapture. An isolated headless Edge process plays a zero-gain WebAudio oscillator. Its browser PID is obtained from that browser's CDP SystemInfo, creation identity is verified by the native helper, and audio stays in memory. No microphone, global input, user tabs, account credentials or model calls are involved.

Actual helper run b received 502 packets in five seconds: all 502 carried valid timestamps, QPC advanced 5.01 seconds monotonically, no discontinuity flags were present, maximum receive delay was 32.691ms, and the helper stopped successfully. Zero-gain output produced only one-LSB peak (RMS 0.479); raw PCM was not saved. This establishes capture clock transport, not process isolation against every other source, player media-time mapping, ASR segment coverage or latency percentiles. Evidence: E:/SumikaBuild/process-audio-clock-live-20261009b/report.json. Existing AM package remains unchanged.


### 2026-10-09 Frozen questions during normal video playback

Reused the existing question binding/cancellation service, passive video identity and seeking/emptied timeline counter; extended the existing headless Edge verifier. No product UI, upstream changes or new parallel service. Previously every media-time/frame/subtitle update cancelled a user question. Fully identified normal progression now retains the frozen question snapshot; navigation, seek (including a tiny completed seek), media replacement, invalid context and revoke retain strict cancellation. A separate content revision cancels obsolete proactive requests. Replies bound to older frames are excluded from the current-frame history; provenance-aware cross-frame discussion remains pending.

87 focused tests passed with zero skips, including ASR-time progression, streaming and segmented playback. Actual owned headless Edge collector snapshots through production validation/question service also passed progression and completed-seek checks; existing MV3 heartbeat/lifecycle checks passed. Evidence: E:/SumikaBuild/video-question-binding-20261009/companion-video-b3cb5448-6b58-491d-bf94-cd9be86a70f3/report.json. Generated video and local role callback only: no real model, physical voice, user input or account access. Existing package and daily profile unchanged; full approved plan remains incomplete.


### 2026-10-09 Timestamped discussion across playback and pause

Adapted existing in-memory discussion rather than adding a summarizer or persistent history. On one fully identified video timeline, normal playback and pause/resume retain bounded prior questions and answers. Every entry includes original observation and video time; the prompt states prior role answers are not course facts or current-frame evidence. A speech-start binding excludes later-frame discussion; concurrent completed replies are ordered by observation time. Timestamp provenance counts toward the existing character budget, with unchanged TTL/session/turn limits. Seek, source change, invalid context and revoke still clear; proactive content invalidation remains separate.

Before the final pause/resume refinement, full tests_next ran 903 tests: OK, 17 skipped, 76.346s. Final affected contracts/voice/scheduler/passive/browser/fusion/microphone/UI-server checks ran 172: OK, 7 skipped, 43.047s. Actual owned headless Edge collector snapshots verified normal playback, pause/resume, frozen image/time, timestamped history and completed-seek invalidation; existing MV3 heartbeat/lifecycle checks passed. Evidence: E:/SumikaBuild/video-discussion-pause-20261009/companion-video-e27ac3ac-d1db-4ee6-a027-960995581f8d/report.json. Local generated lesson and role callback, no physical microphone/TTS, external model, user input or user-tab access. Package/daily runtime unchanged.

Browser integration UI proposal is pending explicit design confirmation: reuse the current companion detail and target selector; a minimal extension popup requests connection of the current Bilibili tab, with final collection consent still in Sumika. AGENTS.md requires asking before new UI elements absent from the design. No product UI or installed browser was changed; independent backend work can continue.


### 2026-10-09 ASR segment capture-clock coverage

Adapted the existing native packet timing and Vosk/SenseVoice segmentation. Each ASR segment now carries `capture_clock_span`: it is known only when every PCM packet in the segment has valid native timestamp metadata, contiguous device positions, no discontinuity flag and bounded QPC joins. Missing or invalid metadata returns an explicit reason; no previous clock is extrapolated. The field describes native capture coverage only. `media_position_known` and player `media_time_seconds` remain unknown until an owning player clock is correlated. Lifecycle stop/revoke clears coverage with queued PCM, and no audio is persisted.

Full `tests_next` ran 905 tests with 17 skips and passed. 55 application-audio/process/application-process/fusion tests passed, including known span, missing packet and invalid clock fixtures. Existing native live evidence remains 502 packets over 5.01 seconds with monotonic QPC and no discontinuities; it does not prove player correlation or speech quality. AM package and daily profile were not rebuilt or switched.


### 2026-10-09 PDF text-loop regression

Reused the existing PDF learning adapter, HTTP bridge and local reply fixture. An owned two-page PDF text-layer run accepted page-bound questions for both pages, rejected out-of-range page 3, and cleared stale context; no paid model or desktop input was used. Evidence: `E:/SumikaBuild/pdf-continuous-text-20261009/run2/report.json`. This does not stand in for image-only/scanned viewport capture or the input-gated continuous native worker acceptance.


### 2026-10-09 Current-source candidate rebuilt

Reused the existing physical staging builder and previously verified AL DSH/host assets, adding the newly built ProcessAudio helper that carries native packet timing. `E:/SumikaBuild/product-candidate-20261009-audio-clock-2` contains 42,346 files and passes inventory verification. Packaged Python, desktop/OCR, voice/Silero and process-audio capability probes pass in `E:/SumikaBuild/candidate-audio-clock-capability-20261009.json`. This is an internal candidate only: no installer/current-host upgrade/rollback or clean-machine execution was performed, and the daily installation/profile was not changed.


### 2026-10-09 Current-source Inno build

Reused tools/build_setup.py, packaging/Sumika.iss and installed Inno 7.1.0. Built E:/SumikaBuild/setup-audio-clock-20261009/Sumika-Setup-2026.10.09-audio-clock.exe from the verified 42,346-file candidate. Build report and SHA256 are in E:/SumikaBuild/setup-audio-clock-20261009/build-report.json. The installer was not executed; no installation, upgrade, rollback or clean-machine claim. Added capture-span slice/missing-clock/device/QPC discontinuity regressions; 42 audio/process/inventory tests passed. Daily runtime/profile unchanged.


### 2026-10-09 Real native segment QPC validation

Extended the existing owned headless Edge zero-gain WebAudio verifier to feed actual native PCM into SegmentedApplicationAudioTrack. The decoder returns an explicit local fixture marker; no speech recognition claim. Runs a/b revealed native process-loopback device positions were always zero even while valid QPC progressed, so strict device-frame increment checks returned unknown. Source now retains QPC coverage only when timestamps, packet coverage and QPC joins are valid, while zero-valued device positions remain unknown with null endpoints.

Run c passed: 502 valid timestamped packets over 5.01 seconds, five one-second production segment spans with known QPC coverage, unknown device positions, no discontinuities and 28.851ms maximum receive delay. Native capture and segment ledger/queue/PCM buffer cleared on stop; no raw PCM persisted. 57 focused audio/process/fusion tests passed, zero skips. Evidence: E:/SumikaBuild/process-audio-segment-clock-live-20261009c/report.json. This does not prove speech accuracy, microphone/TTS, player correlation or arbitrary-process isolation. Existing candidate and Inno installer predate this source correction; a final consolidated build is still required.


### 2026-10-09 Explicit SenseVoice for microphone study

Reused the existing cancellable SenseVoice PCM provider, Pipecat local/study/SAPI factories and capability revalidation. Continuous study now accepts explicitly selected Vosk or SenseVoice, preloads SenseVoice on the owner thread, and rejects unsupported providers/model failures without fallback. Existing microphone/playback consent, VAD, question binding and interruption remain. Pinned sherpa-onnx/core 1.13.8 in the companion runtime lock and optional dependency. No daily configuration or provider switch.

37 real isolated Pipecat/microphone/provider/voice-answer tests passed with no skips. The extended existing verify_voice_local.py recognized the pinned official 5.592s Chinese sample through actual factory-selected SenseVoice: loading 3886.2ms, recognition 227.8ms. Evidence E:/SumikaBuild/microphone-study-sensevoice-sample-20261009.json. No microphone, external model, answer or hardware playback; this is not end-to-end/P95 acceptance. One-shot role speech remains Vosk. Existing candidate/installer predate this integration and the latest segment clock correction; full plan remains active.


### 2026-10-09 Unified explicit file/one-shot ASR and actual prerecorded voice loop

Adapted existing role file transcribe, managed one-shot worker, desktop dispatch and bridge speech configuration; reused SenseVoicePcmProvider. Explicit SenseVoice now works across continuous study and one-shot/file paths; 16kHz mono PCM16 required for SenseVoice, while original Vosk arbitrary-WAV-rate/SAPI 22kHz compatibility is retained. File decode reads at most 30 seconds per segment. One-shot revalidates capability snapshots before capture, after capture and after recognition. Unknown providers/load failures never fall back. 83 file/speech/HTTP tests passed. Actual configured desktop file dispatch recognized the official Chinese sample in 3397.9ms including loading: E:/SumikaBuild/file-asr-sensevoice-sample-20261009.json. No microphone or daily configuration changed.

Added reusable tools/verify_companion_voice_sample.py, using actual study factory/Silero VAD/SenseVoice, production bound QA/stream segmentation, and existing SAPI file synthesis. Actual prerecorded PCM is fed as 20ms packets with no injected VAD events. Two turns passed; second speech cancelled a pending local fixture reply and held first consumer, stale sentence was not synthesized, three real speech WAV files were generated, worker stopped and PCM cleared. Evidence E:/SumikaBuild/voice-sample-pipeline-20261009-a/report.json. This is an explicit local reply fixture with file output: no hardware microphone/speaker, external model, accuracy/P95 or physical playback-stop claim. Isolated actual Pipecat runtime: 59 tests passed, zero skips. Candidate/installer remain older; production pairing UI, player clock correlation, continuous PDF and final release still incomplete.

Final current-source regression: `python -X utf8 -B -m unittest discover -s tests_next`: 921 tests, 18 skipped, OK (76.513s). Continuity check and diff whitespace checks passed. This full source result supersedes earlier full-suite counts, but does not validate the older installer.


### 2026-10-09 Browser request/approval/receipt backend and real-site transport

Adapted existing PassiveBrowserConnection rather than adding a separate pairing service. The extension can POST metadata only (tab id, origin, bounded title and canonical Bilibili video URL); request registration never creates a capture grant. At most eight memory-only requests, pending lifetime 120 seconds, extension-origin-bound random receipt. Authenticated Sumika management lists sanitized pending metadata and explicitly approves capture_frame/consent. Approval revokes previous perception, fences slow expiry, binds exact approved video URL and returns grant only via the matching receipt. Pause returns paused, resume rotates the token/receipt binding, cancel/revoke/stop clear the applicable request and grant. Approved receipt lifetime follows the active grant so disconnect still works after the pending deadline. No persistence, page-provided instructions or new UI.

Backend endpoints: extension-only POST `/api/companion/passive-browser/request`, `/receipt`, `/cancel`, existing `/push`; authenticated POST `/api/companion/passive-browser` with `action=pending` or `action=approve`. Metadata is untrusted reference data; future UI must render title/URL as text, and metadata never becomes consent. Extension functions in the existing isolated MV3 prototype exercise the protocol; no product popup/installation delivered. Original UI design proposal remains pending.

18 passive request/receipt/source/lifecycle tests pass. Actual owned headless Edge verifier passes offer-without-capture, authenticated approval, changed cue, heartbeat without repeated JPEG, pause/resume/stop and extension-side revoke. Evidence E:/SumikaBuild/browser-pairing-bound-source-20261009/companion-video-4d674633-3c9a-4cd8-a36a-042a92803484/report.json. Real public Bilibili BV1Lf4y1M72V also passes pairing and transport: six accepted packets, two clean video frames and four lightweight heartbeats; extension cancellation revokes Bridge. E:/SumikaBuild/bilibili-pairing-live-20261009/report.json deliberately keeps answer passed=false (no subtitle cues and local text callback returns empty), while transport_passed=true. No login, user profile/input, audio capture, physical microphone/speaker or model calls. This is not visual-answer, original-tab audio isolation, player clock or final release acceptance.

Final current-source full regression after pairing changes: 927 tests, 18 skipped, OK (77.548s). Continuity check/handoff and diff whitespace check pass. Full approved plan remains active.


### 2026-10-09 Conservative player/native clock intervals

Existing assets checked: native packet/segment QPC coverage in application_audio.py, ContextFusion, and owned clock verifier. No existing component correlates owning-player reads with segment QPC, so added provider-neutral media_clock.py after recording/communicating this gap. The adapter must independently establish the audio/player owner. Bracketed QPC samples surround actual player reads; both segment endpoints need before/after samples on the same identity/rate. Pauses, seek/end, buffering/disagreeing projections, long gaps, nonmonotonic/invalid samples and identity/revoke fences clear evidence. No wall-clock or PCM offset extrapolation. Bounded metadata deque, no media retention.

ContextFusion optionally accepts the verified correlator and enriches application-audio references with player_clock_span intervals. Normal product behavior remains media_position_known=false and media_time_seconds=null; no bridge binds the optional correlator before ordinary-browser ownership is established. Visual source/target/identity/invalid transitions revoke; pause/rate/media jumps discard old brackets. Prompt explicitly prevents treating unknown capture offsets as video timestamps or intervals as exact points. Native tiny packets now require strictly increasing QPC, even within join tolerance.

Final 75 media-clock/fusion/native-audio/contracts tests pass. Extended the existing verify_process_audio_clock_live.mjs with --player-clock: one owned headless Edge browser, actual generated HTML video with silent audio, native QPC reads before/after CDP player sampling, actual ProcessAudio PCM -> production segment spans -> production ContextFusion. E:/SumikaBuild/player-clock-correlation-live-20261009-b/report.json: 502 valid packets over 5.01s, five native one-second spans, two bracketed player intervals; three unbracketed spans correctly unknown. Revocation makes mappings unknown; capture and buffers/clock state cleared. No microphone, global input, personal browser, audible playback, model or raw PCM storage. Local decoder is a marker fixture, not ASR. Approximately 0.1-second bounds are configured conservative intervals, not measured accuracy. Ordinary Bilibili tab/process ownership, actual source ASR mapping and production adapter still pending; this is not completion of audio/video synchronization or the approved plan.

Full regression before final visual-pause/source-clock fence: 939 tests, 18 skipped, OK (77.604s). Final affected suite after refinement: 75 passed. Continuity/diff and Node verifier syntax checks pass.


### 2026-10-09 Current pairing protocol with real Bilibili visual answers

Reused tools/verify_bilibili_passive_live.mjs, production question binding and configured DeepSeek. Verifier now selects the credential assignment for the configured key_env (never prints secrets), records the actual bound public-video JPEG and media-time provenance, and requires actual image use, matching target/video source, no tools/proposals. Explicit owned-only --seek-seconds pauses/seeks the isolated headless browser; no user tabs/global input/microphone or audible output. Daily settings unchanged; model multimodal is enabled only in the isolated acceptance copy.

Two actual model runs pass current pairing/collection/vision gates. Intro image correctly read 求导 with no formula, full response 1962.4ms/3290 reported tokens. Paused actual tutorial at 90s correctly read f(x)=x²+2x+1 and f′(x)=2x+2 and explained each derivative term, 4792.2ms/3840 tokens. Bound images visually inspected. Evidence E:/SumikaBuild/bilibili-pairing-vision-20261009/report.json and E:/SumikaBuild/bilibili-pairing-vision-content-20261009/report.json. Each isolated role.db has one usage row and no memories/relations/memory_proposals tables; no persisted long-term rows. Extension cancellation revoked the grant. Raw public frames are explicit acceptance artifacts, not production retention.

Manual review limits: formula response speculates about future lecture content, misses some origin/axis detail, and unnecessarily doubts frame time because audio interval is absent. Tightened production prompt to distinguish provided visual media position from unknown audio time and avoid asserting unseen future content. 73 contracts/fusion/browser/passive tests pass after wording refinement; no extra cloud call to claim behavioral correction. Two samples do not establish general formula accuracy, first-token/live voice/P95. No production extension UI/install, ordinary-tab audio ownership, physical voice/PDF continuous or final release claim.


### 2026-10-09 Reuse existing OCR cache with PDF lifecycle scope

Initial collector inspection incorrectly suggested repeated native OCR. Further provider inspection found WindowsOCR already caches exact encoded and actual RGB pixels; the proposed second cache was removed before delivery. Existing provider remains unchanged. WindowsLearningCollector now scopes that cache to target/current reader identity/page/viewport and clears it on invalid/failed captures, identity mismatch, changed page during collection, text-only paths and stop. OCR cleanup executes even if visual stop raises. No raw frame cache or parallel OCR engine added.

Actual WindowsOCR with native-recognizer fixture verifies same page/image one decode, page change forces recognition, invalid capture drops derived result, and stop clears. Default runtime: 26 learning/OCR/visual/PDF/perception tests OK, three skips. Isolated runtime including Pillow: 22 learning/OCR tests OK, zero skips. This is lifecycle/cache logic evidence, not real repeated-window OCR performance or continuous physical PDF navigation acceptance. Browser UI design answer, ordinary-tab audio ownership, physical voice and final release remain pending.


### 2026-10-09 Actual reference baseline, monthly discovery and quota recovery

Reused sole registry, ReferenceMonitor/ReferenceRunner and existing schedule inbox; no additional scheduler/UI. Actual public GitHub queries established ten project SHAs, then DSH request hit quota and stopped the remaining batch with persisted cooldown. Full baseline report remains passed=false, not falsely complete. Discovery persisted three metadata-only needs-validation candidates (eros-engine, Moodle SOLA, Cometline) with URLs/licenses; stored in sole registry discovery_baseline_2026_10, not automatically installed/adopted. Fresh runner on same DB in same cycle, with network/model functions forbidden, passed no-repeat behavior and retained two deduplicated notices. Evidence E:/SumikaBuild/reference-live-baseline-20261009/report.json. No model calls.

Actual quota run exposed redundant re-fetch of successful projects on incomplete-cycle retry. Adapted monitor to reuse successful current-cycle checks on normal retry, fetching only failed/unvisited rows; force and next cycle refresh all. 36 monitor/runner/analyzer tests pass, including actual success/error/recovery ledger, explicit force and next-week refresh. This does not bypass API cooldown and no immediate network retry was attempted. Full real baseline, configured analysis model, packaged lifecycle/native DSH automation and overall companion/release goals remain incomplete.


### 2026-10-09 SenseVoice discovery through existing capability management

Reused ui/readiness.py provider candidates, extensions/desktop/runtime.py selected interpreter, existing voice.asr_model, and the current capability provider selector; no UI layout, entry or navigation change. Voice interpreter routing was already correct. The missing integration was SenseVoice discovery. Candidate discovery now validates tokens/model presence, resolves relative configured paths against the workbench root and checks sherpa_onnx/numpy in the selected voice runtime. SAPI/microphone/Vosk preflights use that same runtime; a broken explicit interpreter cannot be masked by bridge imports. SenseVoice directories are excluded from Vosk model discovery. Bootstrap preserves configured providers, options, disabled and removed states; switching through Management retains enabled state and stops speech. No daily settings changed. File presence is only a preflight, not native-load certification.

Extended the existing file-ASR verifier to require discovery before registry dispatch; actual isolated runtime recognized the official Chinese sample, loading plus recognition 3612.3ms. Evidence E:/SumikaBuild/sensevoice-provider-discovery-20261009.json. No microphone, speaker playback or model API. Packaged voice import verifier now includes numpy/sherpa_onnx, but no new package has been assembled or accepted. Focused readiness/management/runtime/audio tests passed (90 before final fixture/model-path refinements); 27 discovery/bootstrap/management/microphone-permission tests pass after refinements. Initial full suite ran 945 tests with 18 skips and exposed two outdated fixtures (runtime mocking and absent settings_path); both corrected. Full rerun: 945 tests, 18 skipped, OK in 77.671s; continuity check and diff --check passed. Browser product pairing, ordinary-tab audio ownership, PDF continuous physical navigation, live voice/P95 and final release remain incomplete.


### 2026-10-09 Interrupted Bilibili selected-player audio probe closed out

Reused tools/inspect_companion_bilibili.mjs, isolated MV3 generator and SenseVoicePcmProvider. Added fixed browser_audio_capture.js and bounded browser_audio_worklet.js because process-tree loopback cannot establish single-video audio ownership. Prototype audio is opt-in research only, no product UI/install changes. Adapter requires consent, selects one visible playing video, emits 100ms 16kHz mono PCM16 packets, preserves player mute/volume, stops on pause/seek/end/rate/identity changes, closes owned tracks/context and rejects slow consumers without unbounded buffering. The generator holds at most ten seconds of PCM for explicit research ASR; does not persist it.

Recovered execution tools after prior initialization/automatic-review outage. Corrected nested JS/Python newline check with chr(10). Actual isolated Edge public Bilibili run passed: normal/zero/muted player volume each yielded audio, content script emitted 79 packets (7.9s) with player muted/volume zero, and isolated actual SenseVoice recognized “然后我们就可以快速的进行一些实例探讨啦。那么首先它有哪些作用呢？两点，首先啊对于很。” Load plus ASR 3394.7ms. Missing consent rejected; after pause packet count remained 79. Evidence E:/SumikaBuild/bilibili-player-content-asr-20261009-b/report.json. Four JS syntax checks and 33 affected Python tests passed. Failed first ASR command generated invalid newline syntax; fixed rerun above supersedes it. No microphone/cloud model/global input/user tab/audio persistence.

This closes only the interrupted research verification, not the full plan. No ordinary-tab production audio grant/transport/continuous VAD/ASR/fusion, player-time mapping, browser UI installation or final package acceptance claim. A nonempty transcript is feasibility evidence, not independently measured accuracy or real-time P95. Next full-plan work is the separately consented production transport and lifecycle integration.
