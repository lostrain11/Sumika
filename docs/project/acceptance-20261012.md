# Sumika 整体验收：2026-10-12

当前修复/新需求执行入口：[repair-and-acceptance-plan.md](repair-and-acceptance-plan.md)，执行ZCode / GLM5.3flash。下方旧“等待用户新需求”边界为审计当时记录；用户现已完成方向选择并要求文档交接，产品修复仍未开始。

**结论：当前版本不能按“冻结计划 P0～P8 全部完成”验收通过。** 底座升级、阶段提交、安装包与相当一部分模块有真实成果；但 B站产品接线、音轨生命周期、文字主动陪伴存在可复现缺陷，部分承诺仍只有后端或不完整证据。

本轮仅审计、隔离验证、更新记录。没有修改产品代码、安装/卸载、切日用版本、推送或公开发布；没有采集用户屏幕/麦克风、播放音频、操作桌面鼠标键盘或调用外部收费模型。后续由用户选择贵模型评估优化和新需求，本报告不自动启动修复。

## 1. 基线及本轮验证

- 源码与远端分支 `codex/sumika-next-dsh` 均为 `6bbecd6f766285dd88cb1029be77d7c632e0a157`。验收开始时工作区干净。
- 候选：`E:/SumikaBuild/product-candidate-20261011-p8`；日用安装：`E:/Work/Sumika`；两者实际 DSH 依赖均为 `0.2.0-rc.2`。
- 安装器 SHA256 重新计算与报告一致：`043507d85754bf3e2a9a798a1a3472860b42ac05fe458720a0bc9756760f2d0e`。
- 重新验证候选清单 **42,368 文件**及 python/desktop/voice/process-audio 四类能力导入：通过。与阶段整理提交 `a9a72a3` 相比发生变化的26个非JSON交付源码，候选与安装目录均逐文件匹配当前源码。
- 全套 `python -X utf8 -B -m unittest discover -s tests_next`：**996 tests，21 skipped，OK，76.278秒**。
- 使用安装版 voice Python 补跑 microphone_worker、Pipecat、voice_answer、segmented_playback、session_coordinator：**58 tests，OK，12.164秒**，弥补基础解释器缺可选语音依赖的部分跳过。
- 使用安装版 DSH 与独立 profile，重跑连续性、角色插件与原生插件生命周期：均通过；角色自动注入/显式记忆/跨会话及重启召回/关闭开关，连续性plan历史/压缩换会话/回填幂等/禁用保数据，插件安装启停卸载/不兼容拒绝/失败恢复/保留无关配置均有本轮证据；零外部模型调用。
- 对安装版 UI＋安装版 DSH 在一次性 profile 中重跑四屏矩阵：**128/128通过**，主题恢复、零pageerror、无布局断言失败。原生工作台专项结果及验收器限制见第4节。
- Python隔离复现、生成扩展的Node VM复现、headless Edge文字陪学复现均验证了下列问题。单测通过不能覆盖这些漏项。

所有本轮本机证据在 `D:/Code/Sumika/.sumika-next/acceptance-20261012/`，被Git忽略；本报告只记录脱敏结论。

## 2. 已确认功能缺陷与残缺

### F-01 / P1：B站专属链路没有接到普通用户流程，也没有随包交付扩展

范围：`ui/app/companion-session.js:47`、`:217`，`ui/app/companion-text.js:13`、`:18`，`tools/build_portable_staging.py`，`tools/build_companion_extension.mjs`。

现有陪学详情仍只有“学习窗口”，仅从 `/api/companion/windows` 加载窗口，开始时启动 WGC 与可选进程声音。整个 `ui/app` 没有调用 passive-browser pending/approve 或 browser-audio start 的接线。扩展popup显示“等待在 Sumika 中确认”，但客户端没有对应确认操作。测试工具则直接请求 approve 与 browser-audio start，因此绕过了缺失的产品入口。

候选和日用安装目录均找不到产品扩展的 `manifest.json`、popup/worker交付目录；构建器脚本存在不等于已生成可安装扩展。前端文字提问也只检查窗口capture.alive，浏览器tab有效而窗口capture不运行时返回false，转回普通角色聊天，无法使用该tab的学习上下文。此外文字使用 `companion-pet-text` history，语音使用 `companion`，界面路径的讨论历史没有统一。

**影响**：窗口截图的一般陪学路径仍可用，但用户无法靠当前客户端完整使用承诺的 B站干净帧/字幕/单tab音轨链路。P2覆盖表写“目标选择已扩展”为已实现，与代码不符。

**后续补齐判据**：复用已批准的唯一陪学详情，用户能在原tab连接→客户端独立许可→启动音轨→文字/语音提问；模型实际收到该tab参考，讨论历史一致；同一安装包提供扩展文件及安装说明。不能再以验收脚本人工approve替代。

### F-02 / P1：seek后ASR继续产出，但新转写无法进入当前上下文

范围：`extensions/companion/passive_browser_audio.py:181`、`:267`，`application_audio_worker.py:86`、`:93`、`:138`，`context_fusion.py:85`。

`rotate_epoch()`只更新桥端audio_epoch、序号并清传输队列。worker不接收epoch/媒体身份轮换控制，观察回调闭包始终给转写标启动时的media_identity；内部VAD/识别缓冲和在途解码也不失效。reader转发时不校验当前audio_epoch。视频seek后timeline_revision变化，fusion要求完整media_identity一致，后续转写被拒绝。

隔离复现：桥身份timeline_revision=1，ASR输出=0，`fusion.audio()`返回None。30分钟浸泡只统计received/transcripts，不验证转写已进入模型参考，所以该报告可以为passed而问答已经失去音轨。

**后续补齐判据**：轮换必须同时处理识别器缓冲、在途结果、media_identity和输出代次；不能仅在reader上给旧解码结果改标签。seek前后分别验证模型参考含对应片段、不含旧片段；倍速/暂停恢复覆盖同一围栏。

### F-03 / P1：音轨停止与异常未履行清理、失败状态和不重试约定

范围：`passive_browser_audio.py:153`、`:199`、`:247`，`ui/server.py:1145`，`tools/build_companion_extension.mjs:264`。

- `on_clear`保存后从未调用。直接停止浏览器音轨，融合层旧转写未立即清除，问答可继续引用直到TTL；本轮复现stop后clear callback调用次数=0。完整revoke会另清上下文，不能替代“单独撤销音轨”的行为。
- sequence缺口抛出403，但轨状态仍running；复现sequence0后送3，状态没有停止。`stop()`还清掉error，故错误状态无法供UI持续显示；已有“队列溢出”等文案未证明真实错误会进入该状态。
- 扩展对 `host_rejected`、`send_failed` 等停轨原因也自动轮换并重启，最多30次/分钟。Node VM复现host_rejected后发出audio-epoch及start-audio，返回restarted=true。这不符合冻结稿“缺口/满/提交unknown停轨，明确重新开始”，不能把30次的上限当无自动重试。

**后续补齐判据**：停止清引用、旧结果被围栏拒绝，错误原因保持可见；只允许明确的同视频seek/rate等生命周期恢复，传输未知/拒绝/队列溢出要求显式恢复，不自动回放PCM。

### F-04 / P1：扩展音轨启动失败仍显示运行中

范围：`tools/build_companion_extension.mjs:207`。

`startConnection()`没有检查content script的 `start-audio` 返回值，直接把audioActive置true。Node VM给出 `{started:false,error:'player audio track unavailable'}`，worker仍返回 `{status:'running',audio:true}`。

**影响**：没有可采集音轨/CORS等导致启动失败时，popup会显示“运行中（含播放器声音）”；新增的客户端错误文案没有把这条失败完整接回来。

**后续补齐判据**：采集、传输、识别各自状态真实可见；start失败不显示音轨正在运行，文本/字幕/画面仍可降级使用。

### F-05 / P1：文字模式主动讨论开关与消息显示失效

范围：`ui/app/companion-session.js:167`、`:210`，`ui/server.py:872`。

文字模式开始只向perception发start，随后向microphone请求status；未传主动讨论设置给协调器，因此取消勾选不会关掉协调器默认开启的主动讨论。真正的set_proactive只在开麦入口中执行。

文字模式microphone状态为stopped；render处理proactive_text后无条件执行transcript.replaceChildren()。本轮headless Edge复现：文字采集运行，注入合法proactive_text事件，1.6秒后记录流看不到该文字；请求记录也仅有capture start，无主动设置。

**后续补齐判据**：不开麦时主动讨论按用户开关/安静程度工作，能持续显示；关闭后不生成或播放主动内容，既有讨论不因麦克风未启动而每秒清空。

### F-06 / P1：文字提问没有抢占后台主动回复

范围：`session_coordinator.py:312`、`:394`、`:414`，`ui/server.py:904`，`qa.py:244`。

协调器ask_text及Bridge直接调用的service.ask未向scheduler登记文字忙状态，也不取消active_proactive。在相同内容上启动后台回复→用户文字问答完成→释放后台，后台仍发出proactive_text。隔离复现结果为 `background_reply_emitted_after_user=true`。

**影响**：后台会继续占用模型并在用户问题后插话；有speaker时可能继续朗读。voice_user_started里的“取消”辅助函数实际也只是延长scheduler忙窗口，不直接取消正在生成的主动请求，语音还需做同类并发回归。

**后续补齐判据**：用户活动立即取消/失效已在途后台回复，文字和语音用同一仲裁；后台结果返回后再次验证代次、用户忙状态和许可，不仅检查内容是否变化。

### F-07 / P2：弹幕摘要拿到的是时间戳而非文本

范围：`extensions/companion/study_extras.py:143`，`session_coordinator.py:438`。

`_entries`是text→(first_seen,count)，snapshot_texts却遍历values并返回first_seen。本轮输入“为什么这里取负号”，输出`[1000.0]`。摘要函数join会抛TypeError并只发错误事件；若未来调用自动摘要，将不能得到文本。目前摘要hook也没有产品调用者，不能算已完成用户功能。

**后续补齐判据**：输出仍在TTL内的去重文本，reset/target切换/撤销清理所属缓冲，摘要失败不阻塞问答且迟到结果不进入新会话；是否自动摘要待设计确认，不在本次审计中擅自新增。

## 3. 分模块完整性

| 模块 | 当前证据与判断 | 残缺或未验收 |
| --- | --- | --- |
| DSH底座、原生工具、审批取消、连续性 | 已升级0.2.0-rc.2；现有全套单测及本轮真实隔离连续性/角色/插件生命周期通过 | 本轮未逐个重跑所有原生工具真实任务；不能以这些门槛称完全平替所有Codex能力 |
| 四屏UI与原生工作台 | 安装版四屏128格矩阵通过；核心新增入口仍遵守不重复方向 | B站目标/许可接线缺失；文字主动记录丢失；原生验收器有新版适配问题，见第4节 |
| 独立桌宠、VRM、角色与记忆 | 宿主源码及包内EXE存在；pet/角色/记忆单测通过；DSH角色注入、记忆显式写/重启召回复验通过 | 本轮未操作真实宿主拖动、穿透、置顶、收起、自身排除，不把代码检查当硬件UI复验 |
| B站干净帧/字幕/单tab音轨 | 原型与生产扩展生成器存在，历史有真实音轨浸泡 | F-01～04阻塞产品闭环；真实站点字幕30分钟缺证据，当前唯一真实报告cues=false；音轨计数不证明融合 |
| PDF当前页/文字/OCR/图像 | 历史有真实书22翻页、文本层交叉校验、扫描页及双窗口/缩放证据；相关单测通过 | selection报告明确empty_intersection=true，没有可用选区正文；公式精准OCR未通过、须保留图像及视觉模型；本轮未重新占用桌面翻书 |
| 连续语音/VAD/ASR/TTS | 真实语音历史及本轮58项可选依赖测试，语句续说优化有代码 | R-126允许不用继续真人测，30turn原要求已被用户方向调整；不能因此声称原门槛全部通过。延迟是ASR完成→首字/首音，停说→ASR缺数据；live report本身passed=false，需结合waiver和后续审计解释 |
| 主动讨论/行为反馈 | 共享协调器、行为追踪和预算已有实现 | F-05/06影响主流程；行为提示默认60秒cooldown与其他主动发言没有共享120秒发言围栏，安静程度还需联合验收 |
| 本地摘要/网页AI辅助 | 现有辅助、授权账本、unknown状态测试通过 | 辅助当前配置disabled；摘要hook不能当已接入功能。网页AI没有本轮真实站点提交/抓取验收，不自动发送 |
| 笔记/用量 | 笔记save/recent后端及usage音频/视觉列有实现与单测 | 笔记没有普通用户UI入口（记录中也说待确认），不能称完整交付；usage token仍COALESCE为0并另计unknown行，应明确展示已知小计而非完整总量 |
| 插件管理/参考调研 | 本轮原生管理生命周期通过；26项参考清单、runner/SQLite/限流/去重代码及离线测试 | lifecycle仍为合成测试bundle；第三方候选未逐个实际采用，不能称市场全部可用；GitHub限流下真实候选质量未验证；无变化零模型主要为夹具证据 |
| Office/桌面控制/网页咨询等旧能力 | 纳入996项单测；包内desktop能力导入通过 | 复杂Office视觉/公式重算、真实浏览器咨询、设备控制，本轮未逐项外部实测；保留历史限制，不自动提升为全部完成 |
| 安装、个人数据、升级回退 | 安装器hash/候选文件/能力导入复验通过，历史Sandbox有干净机安装与导入证据，日用已升级 | 扩展未入包；真实干净机图像/语音使用未测。按执行记录用户要求卸载旧版后旧日用runtime不存在，隔离成对回退通过≠现场可直接切回旧版 |

本轮只读查看日用配置的布尔就绪信息：角色模型enabled、voice enabled、usage enabled；**multimodal disabled、auxiliary disabled**。所以当前默认使用不能把图表/公式截图交给视觉模型，也不会自动使用本地摘要服务。这属于配置/依赖条件，未擅自改开关；要实测视觉闭环须选定支持图像的provider并明确开启。

## 4. 证据与验收器的缺口

1. **主记录冲突**：handoff/progress的execution_handoff称DONE，但顶层next_action仍是待真人/安装；plan的execution_handoff仍待门槛而next_action称DONE。冻结文档开头仍写P0未开始，UI覆盖表声称B站选择与文字主动显示已实现，但代码和复现不支持。连续性check校验schema，不验证这些事实；本轮用独立验收结论纠正当前入口，保留历史回执。
2. **浸泡判据不足**：pause只断言queued≤1，不能证明received计数不增长；subtitle选项不要求真实视频cues存在；transcripts只要求≥1，没有断言模型参考正确融入新epoch。不能用passed概括所有场景。
3. **语音报告边界**：`E:/SumikaBuild/voice-live-20261011-r2/report.json`为旧candidate-s voice解释器、Vosk、real-model，30 VAD turns/15完整转写回答，passed=false、asr_ms未知。执行记录认为旧late_playback计数把新回复算进去，且用户R-126明确免继续测；本轮没有以计数失败再次要求用户30问。正确结论是保留部分真实证据和调整后的范围，延迟分母不等于冻结稿“停说后”指标，最新SenseVoice与最终包性能仍未实测。
4. **PDF选区判据不足**：pdf-slices的selection passed只表示source/selected flag正确，且报告empty_intersection=true；不代表用户划选内容已能用于讨论。
5. **原生UI验收器适配**：原版verify_dsh_panel把0.2.0原生“插件”行误当Sumika重复入口；初轮隔离fixture只创建session而未注册workspace，也导致项目树判据失败。原版verify_workbench_ui硬编码已失效的Codex Playwright目录，MODULE_NOT_FOUND。这些需区分验收器/前置问题与产品缺陷，不能据此隐藏原生插件功能。本轮只在忽略目录改验收副本、注册真实测试workspace：原生侧栏、项目行、唯一入口及零客户端错误通过；详细workbench交互脚本修正loader后仍被首次配置modal遮罩挡住，未通过，不能记为产品交互验收通过。结果见installed-native-ui-report.json与workbench-audit.log，不改交付代码、不将此环境/脚本问题归为已确认产品缺陷。
6. **可复现构建记录**：最终manifest含文件hash，但未提供统一source SHA+所有外部输入lock/hash的完整构建回执；VC++DLL来自修补外部runtime输入，重复构建依赖本机保存资产。已有成果可核对，不等于干净环境从源码一步重建已有充分证明。

## 5. 原审计的后续边界（历史）

先读本报告和 `companion-implementation.md` 冻结稿，保持已确认B站/PDF范围、唯一UI入口、Harness中立、许可和数据边界。下一轮由用户给贵模型新增需求和优化方向；本轮不提供替用户做决定的新功能设计。

明确应先解决的现有缺陷：B站产品接线与扩展交付 → 音轨epoch/停止/错误围栏 → 文字主动显示/开关/抢占 → 弹幕文本。修复后针对这些真实行为补回归，并重建同一候选；再验证缺少的真实字幕、视觉/选区、更新后语音性能。现有996项通过及旧真实报告保留，但不能替代新增围栏、UI流程或新安装包验收。

本机复现入口：

```powershell
python -X utf8 -B .sumika-next/acceptance-20261012/reproduce.py
node .sumika-next/acceptance-20261012/reproduce-extension.mjs
node .sumika-next/acceptance-20261012/ui-reproduction.mjs .sumika-next/acceptance-20261012/ui-fixture-next
```

这些是审计夹具，输出是当前实现的失败行为，不会修改产品；修复后预期结果须反转，不能把“复现脚本退出0”当作产品通过。主要证据：unit-tests.log、voice-tests.log、capability-package.json、reproductions.json、extension-reproductions.json、ui-fixture.log、verify_ui_matrix.json、installed-native-ui-report.json及连续性/角色/插件日志。

收尾验证：项目记录 `check` 与 `handoff` 返回0，`git -c core.safecrlf=false diff --check`通过。本轮仅修改本报告及既有接驳/计划/进度记录，未提交或推送。

## 6. 规划复核补充：2026-10-12

本节是随后规划审查的补充，不改写第1节前次实测。源码基线仍6bbecd6。重新跑`python -X utf8 -B -m unittest discover -s tests_next`：996 tests/21 skipped/OK/78.629秒；存在部分测试ResourceWarning及PurePath弃用提示，未定位为真实产品泄漏，不隐藏或宣称已修。聚焦语音/音轨/协调器等66项及行为/记忆33项通过，仍漏下述缺陷。

### F-08 / 高：真实观察发布绕过协调器

ui/server.py的Bridge._companion_publish直接_companion.update；StudySessionCoordinator.publish_observation才启动scheduler、切target和入danmaku。独立调用真正Bridge入口、采用真实coordinator和无设备fake chat，返回updated但scheduler=stopped、target=null、danmaku=[]。只修F05文字开关仍不会闭环。修复要求collection_token判定成功后才执行协调器副作用，所有产品观察统一入口。

### F-09 / 高：无新鲜验证仍累计久留

仅一次ObservationBundle发布，在同一真实协调器用假时钟前进181秒再tick，same_observation=true，产生long_dwell181。被F08暂时遮蔽，不声称当前产品已主动误判。修复后需区分capture_frame_at与verified_at：静态最后帧可复用，当前目标新鲜存活/前台验证才可累计；重复latest投影及超3秒空档不计。新鲜度字段必须排除内容digest，否则会每秒触发模型。

### F-10 / 中：用量UI漏掉陪学等业务

ui/management.py usage只查询room-role_id，ui/app/management.js仅显示token。现有companion/companion-pet-text/study-browser-audio等不进该查询。需存储类别、聚合与既有UI一起修，并区分指标不适用、reported/estimated、已知小计与未知请求。

### F-03/F-06/F-07 扩展复核

- 真实Bridge.companion_perception(start)和shutdown，真实PassiveBrowserConnection.stop→clear链及PassiveBrowserAudio，挂只stdin.read的惰性无设备子进程：两场景返回后child_alive=true、audio running、passive stopped；finally精确stop已回收。未验证整个宿主退出后OS Job最终回收，不能称永久孤儿。
- 旧reader epoch1异常可以停epoch2，pipe worker ASR overflow仍仅报running；扩展audio packet未固定epoch，转发时套当前epoch，旧watcher读全局capture，send吞rejection及5秒自动start须一并修。
- 门闩fake模型：关闭proactive后在途内容/行为仍event和speaker，revoke→新target后旧行为仍输出。统一token/session/activity最终围栏，而非只改开关。
- 弹幕snapshot过TTL仍返回旧数据，换target/revoke缺清缓冲。

以上均是隔离或静态复核，没有截图/麦克风/键鼠采集、真实音频播放、外部模型付费或日用安装切换。完整机制与后续验收见三份新计划。计划记录不是修复成功证据。
