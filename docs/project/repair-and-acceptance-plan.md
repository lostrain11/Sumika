# Sumika 缺陷修复与新需求执行总入口

版本：2026-10-12 v1。执行工具：**ZCode**；执行模型：**GLM5.3flash**。

状态：完整方案已记录，产品实施尚未开始。本轮只写文档和交接记录；计划归档不等于产品完成，也不代表已推送、发布或切换日用版本。

## 1. ZCode 启动指令

将以下内容交给 ZCode：

> 在 D:/Code/Sumika 工作。先读 AGENTS.md、docs/project/handoff.json、progress.json、plan.json，再完整阅读本文件、behavior-memory-plan.md、companion-profiles-plan.md 和 acceptance-20261012.md。需求以 requirements.json 和本轮明确用户选择为准。保留现有未提交工作，不改 DSH 上游或 node_modules。从本文件的第一个未完成执行包开始，每次只实施一个包并完成对应验证、回执和主记录更新；通过后按依赖推进。不能把组件单测、脚本直调 API 或历史回执当作普通用户流程完成。遇到失败先核对操作是否已生效，不重放 unknown。需要扩展需求或外部条件时记录准确缺口，不能自作主张。产品改动按本稿实施，真实桌面/设备验收前通知用户，不抢占用户游戏输入。推送、发布、付费模型调用和日用安装切换须有覆盖该动作的授权。

包编号 P00～P17 是本次交付包，不覆盖历史计划阶段编号；历史 current_phase=P6 保留。P00 的文档归档已由本轮完成，执行者核对现场后从 P01 开始。不得因 P00 完成把整体状态标 complete。

## 2. 验收事实与已确认选择

源码审查基线：`6bbecd6f766285dd88cb1029be77d7c632e0a157`。归档开始存在五个未提交文档：companion-implementation.md、handoff.json、plan.json、progress.json，以及新 acceptance-20261012.md；均保留并在其基础上补充。

本次规划审查重新执行全套 Python：996 tests，21 skipped，OK，78.629 秒。check、handoff、diff --check 通过。另做真实 Bridge 方法的无设备隔离复现。旧报告的安装版 UI 128 格、58 项语音依赖、42,368 文件清单属于前次审计证据，本轮没有重新冒充设备/安装实测。

**整体未通过。** 单测通过仍漏掉产品接线、并发取消和音轨身份。新功能要先依赖修好的基线，不能拿行为数据库或模式名字掩盖旧缺陷。

用户本轮选择：授权后跟随前台；键鼠保存细粒度操作特征，不保存实际输入、剪贴板正文或完整按键串；本地记录、按已有许可调用配置模型；模式可新建/复制/修改并自动匹配，手动选择一直优先；新规则明确保存的许可可随 Sumika 启动恢复；不增加系统开机自启，不自动开麦或采集应用声音；行为数据长期保留、不按期限删除、可单独选盘；通用习惯共享、角色互动隔离；询问默认每10分钟1次/每天6次；补笔记和显式弹幕摘要；所有控件复用已有页面。

以上替代旧方案的“所有采集许可重启失效”、固定学习/游戏枚举和30/180天自动删除建议。仅新规则明确保存的许可可恢复，历史一次性同意不得升级。操作 token、HWND、PID 和旧 tab grant 不能复用。R-126 的真人语音豁免继续有效。

数值阈值、接口名、技术实现为主Agent选定的实施默认，不冒充用户逐字要求；执行者按本稿实现，只有新证据证明不可行才提出具体修订。

## 3. 缺陷与能力缺口

|编号|优先级|已确认事实|完成判据|
|---|---|---|---|
|F-01|高|目标选择只列窗口，B站 pending/approve/audio 未接产品；前端用 capture.alive 路由；扩展未入包|popup连接→客户端确认→音轨就绪→用户问答完整，包内实际有扩展|
|F-02|高|rotate_epoch 不重置 worker/VAD/在途ASR身份；seek后融合拒绝新转写|seek后最终参考含新片段，排除旧片段；所有控制/数据绑定代次|
|F-03|高|stop不调用clear；缺口仍running；error被清；失败自动重试；窗口start和shutdown漏回收browser audio|立即清引用、持久错误、无重放、旧回调不伤新轨、方法返回前回收|
|F-04|高|start-audio 返回false仍设置audioActive=true|capture/transport/ASR状态真实，音轨失败可保留画面字幕|
|F-05|高|不开麦时主动设置未生效；microphone stopped每次render清文字|文字会话应用开关，消息不会被轮询清空|
|F-06|高|文字和语音活动不可靠取消后台；关闭主动、换target后旧行为仍输出|用户抢占、禁用和换会话使旧生成/事件/TTS全失效|
|F-07|中|snapshot返回时间戳，TTL只在observe清，目标/撤销未清|真实文本、读取清TTL、目标隔离、显式摘要可用|
|F-08|高|Bridge._companion_publish直接service.update，绕过publish_observation|真正Bridge入口启动调度、行为和弹幕接线|
|F-09|高|同一旧bundle反复tick累计181秒久留|重复投影不计时；真实新鲜验证静态页面可计时|
|F-10|中|管理用量只查room-role，漏companion/audio/vision|UI展示各业务类别、已知小计/估算/未知|

F-09 是被 F-08 暂时遮蔽的潜伏问题，不说成当前产品已经自动误判。F-03 实证是 shutdown 返回前未回收，没有证明宿主彻底退出后一定永久孤儿。

能力/证据缺口：G-01 PDF选区正文为空；G-02笔记UI及来源冻结；G-03浸泡不检查最终融合参考；G-04真实字幕/视觉/最终语音性能不足；G-05新版原生UI验收器失配；G-06构建回执输入不完整；G-07主记录过时且冲突。当前 multimodal/auxiliary disabled 属配置条件，不擅自开启，不记成代码错误。

## 4. 现成资产与共同契约

|资产路径|采用结论|
|---|---|
|extensions/companion/session_coordinator.py、qa.py、observation_scheduler.py|改造；唯一会话owner、取消令牌、预算；不另起游戏/行为问答系统|
|extensions/companion/contracts.py、context_fusion.py、perception_process.py|改造；观察与目标身份、融合、子进程；保留完整媒体身份校验|
|extensions/companion/reading_behavior.py|改造；冷启动规则、有效时间及真实重访|
|extensions/companion/passive_browser*.py、application_audio*.py、浏览器JS|改造；单tab传输及ASR，PCM不落盘|
|extensions/companion/study_extras.py|改造；笔记显式保存、弹幕缓冲。StudyNotes实际保存正文，不能沿用“只存哈希”旧摘要|
|extensions/models/usage.py|只用于成本；不能充当行为数据库|
|extensions/memory、extensions/roles/context.py|复用来源纪律；行为日志不写成长期事实|
|sumika_next/paths.py、ui/data_lease.py、tools/backup_personal_data.py、tools/manage_personal_data.py|改造；位置、lease、迁移备份；现成备份明确不复制外部路径|
|ui/prototype-d/index.html:937附近、957附近、1063附近；ui/app现有详情/权限/数据页|改造；保持唯一入口，逐屏对照设计|

新增 extensions/behavior 有必要：当前成本/笔记/长期记忆/短时观察四种语义均不承载“操作事实—用户解释—确认—习惯”。只补领域层，复用观察、调度、角色模型、生命周期和数据治理。

### 4.1 身份与时效

|标识|用途|
|---|---|
|observation_session_id|显式启动或应用重启新建；翻页/切模式不伪造新会话|
|session_epoch|停止、撤销、目标/材料替换使旧内容请求失效|
|content_revision|页码/时间线变化，具体内容绑定|
|audio_epoch|新轨、seek/rate/pause-resume隔离|
|activity_revision|用户发问、开始说话、禁用主动使后台失效|
|routing_epoch|模式选择、编辑、目标变化使分类失效|
|behavior_epoch|更正/删除/关闭使用/换库使旧学习结果失效|

后台开始保存request_id、所需标识和CancellationToken；回包、写消息、提交朗读前分别检查。换材料取消，材料内翻页可保留“刚才快速往返”的行为片段，不能把不绑定某页理解为无绑定。

扩展ObservationBundle或配套信封：observation_id、target_instance、material_id、capture_frame_at、verified_at、foreground、visibility、quality、permission_revision。未知材料身份不猜。静态画面可复用，但只有新鲜存活/前台验证能计时；超过3秒验证空档不补算。内容digest排除ID/心跳时间等易变字段，避免每秒触发模型。

### 4.2 对外入口

继续现有认证Bridge/CSRF，不新端口：

- `/api/companion/session`：status/start/pause/resume/stop权威状态，包括各通道、target、profile、询问；旧接口为兼容包装。
- `/api/manage/companion-profiles`：模式CRUD/select，见模式文档。
- `/api/manage/observation`：许可、排除、启动恢复；生命周期由session owner执行。
- `/api/manage/behavior`：分页查询、feedback、更正、删除、导出、存储迁移，见行为文档。
- 既有提问入口增加可选behavior_prompt_id；笔记save改为服务端answer_id/source_ref。

无效输入400、无许可403、revision/代次冲突409、缺依赖503。提交结果未知明确unknown+operation_id；只查询，不重新提交。麦克风停止不是整个会话停止。

所有后台模型共享每分钟2次启动、单in-flight和每类一个latest候选；用户问答优先，路由优先于依赖模式的发言。实际启动才扣预算。主动可见/可听消息共享至少120秒围栏。使用现有配置角色模型，不自动换provider、付费fallback或下载模型。

## 5. 修复实施细节

### R1 接线与新鲜度（P01）

统一Bridge视觉、浏览器、音轨融合、音轨清后视觉恢复到coordinator.publish_observation，增加collection_token。先通过接受判定才启动scheduler/切target/入弹幕。不可持Bridge context锁join scheduler或worker。拒绝的观察零副作用。

行为入口用新采集/新验证ID去重；按相邻有效验证累计时间，超过3秒断片。最小化、离开前台、锁屏、暂停、目标变化结束片段。输入空闲不等于人离开；静态读书在有效心跳下仍累计。回看使用位置序列/重访而非“向后两次”。

测试真正Bridge入口，不仅直接调用coordinator。一次publish后181秒不产生久留；同页新验证累计180秒可产生一次久留。新字段不触发重复模型。

### R2 取消、仲裁与文字记录（P02）

文字调用coordinator.ask_text，扩展已有binding/expected_target/token，保留提问瞬间冻结参考。用户文字/voice_user_started先busy、activity_revision++、cancel后台，再获取chat锁。文字busy到finally，语音busy覆盖VAD续说、ASR、回答、播放，不用固定5秒代替。

proactive/behavior_note/未来摘要统一后台登记和token；结果最终检查session/activity/许可/profile/busy。provider忽略cancel也不得event/TTS；取消TTS按request ID停止剩余片段。禁用主动立即cancel，不删除已有文字。正常文字start就配置proactive，不借mic启用。UI不按microphone stopped清记录。文字语音统一companion历史。

门闩测试：后台阻塞→文字/语音/禁用/换材料/撤销→放行，零旧event/朗读。覆盖已经播放首片后打断。远端取消未确认记unknown用量，不重发。合并行为60秒与内容120秒发言围栏；下游忙不吃掉pending或预算。

### R3 音轨代次（P03）

首轮明确采用每个audio_epoch新建ASR worker，不做VAD/解码热复用。顺序：暂停旧采集→旧epoch立即失效→清PCM和音轨参考→回收旧worker/job→当前完整媒体身份新worker→ready后允许sequence0。准备阶段不缓存跨代PCM。

content产生包就写immutable epoch；worker禁止转发时套owner当前epoch。reader/writer/watcher所有正常/异常/await后校验owner。旧EOF/坏JSON/BrokenPipe不能停新轨。保留fusion完整identity，不降低校验。允许同视频seek/rate/resume；新视频/分P/扩展重启重新连接许可。显示识别准备中，记录重建延迟。

测试Vosk/SenseVoice缓冲、排队、阻塞解码、迟到输出；seek前后不同文本在最终参考正确，不只数transcripts。

### R4 停止、错误、启动与回收（P04）

stop立即围栏+clear；fail保留结构化原因直到显式start。active grant序列缺口、满队列、send unknown/rejected/failed停轨，等待用户恢复；旧包只拒绝，无关非法调用不能停他人轨。

删错误自动rotate/restart和每5秒无条件start第二路径；send helper不得吞rejection。run_pipe持续监督ASR状态和许可。握手为首个valid观察→host ready→content start成功，started=true才audioActive。音轨失败可保留视觉。

窗口start、stop/revoke、shutdown显式停browser audio，锁外清引用，回调失败仍回收job/pipe。重复stop幂等，usage只计一次。测试popup/client/host状态一致、stop后参考无旧音频、无残留worker、无自动PCM重放。

### R5 B站普通用户链路（P05）

现有目标选择器显示窗口/pending/已批准tab，后端pending/approve真实request_id；不前端拼URL。现有开始确认画面字幕和独立audio默认false；B站不额外启动WGC/进程音轨。文字按权威session路由。unknown只读查状态。

build_portable_staging调用既有buildCompanionExtension，候选固定`browser-extensions/sumika-companion/`，manifest/popup/worker/content/worklet/README纳入hash和安装。用户可直接加载包内目录，不运行构建器，不静默装扩展。host权限仍B站+loopback，其他教学网站走通用窗口。

E2E必须从popup连接→UI批准→首帧→音轨→文字/语音问答→断开；不能脚本直接approve替代产品。换tab/分P/过期许可覆盖。

### R6 PDF、弹幕、笔记、用量（P06）

PDF调查真实selection所在TextPattern/TextPattern2节点；已知可辨识段落测试返回非空准确段落而非全页。只有可靠矩形时可裁剪OCR并标来源；无定位返回selection_unavailable，可让用户粘贴/指区域。跨页/缩放/滚出视野/同名文件/翻页后不沿用旧selection。公式普通OCR不冒充视觉理解。

弹幕snapshot返回文本、读取清TTL，target/revoke清buffer。详情增加显式“总结当前弹幕”，捕获session epoch，结果标观众讨论，不当课程事实，失败不阻塞QA，不自动周期摘要。

回答有冻结来源时提供保存笔记；详情recent。服务端answer_id绑定frozen_source_ref，翻页后存旧回答仍旧页，禁止前端伪造provenance。不自动存所有聊天；显式笔记允许正文。

用量新增业务类别room/companion/routing/behavior/audio/vision，旧行可确定才迁移，否则unknown。返回metric适用性、known_sum、unknown_count、estimated/reported分组；audio无token不是token unknown。现有用量UI实际展示所有类别，不能只改SQL。

### R7 工具、记录、构建（P07）

Playwright复用统一loader，隔离profile完成首次配置/register workspace，保留DSH原生插件入口；不用隐藏原生功能满足旧断言。浸泡增加暂停零新包、真实cues、每次seek后最终参考断言。语音复用已有录音，分开停说→ASR、ASR→首字/首音；R-126有效。

build receipt包含source SHA/dirty摘要、DSH lock、python/desktop/voice/native输入hash、生成器/产物hash、命令和验收。资源警告单独定位，不能未经证实称产品泄漏或直接隐藏。当前记录勘误与历史回执分开。

## 6. 执行包顺序与交付门槛

|包|范围|前置|不可省略验收|
|---|---|---|---|
|P00|本三文档、原文/选择补录、资产表、记录入口|无|已归档；执行者核对现场|
|P01|F08/F09接线与有效观察|P00|真实Bridge正反例|
|P02|主动取消、busy、文字显示|P01|门闩并发+不开麦UI|
|P03|音轨新代次新worker|P01|seek后最终参考|
|P04|错误、stop/start、回收|P03|无重试/旧回调隔离|
|P05|B站UI与扩展随包|P02/P04|用户完整流程|
|P06|PDF/弹幕/笔记/用量|P02/P05|正文、来源、UI可见|
|P07|修复版整体验收/工具|P01～P06|旧能力回归与修复候选|
|P08|行为库及管理契约|P02|隔离、幂等、删除|
|P09|选盘/空间/多根备份|P08|外部目录及失败恢复|
|P10|持久授权/前台观察|P07/P09|新身份恢复、排除/暂停|
|P11|Raw Input脱敏聚合|P10|无正文、不吞输入、有界|
|P12|行为检测/通用序列|P08/P11|重叠不刷次数、freshness|
|P13|询问/反馈/习惯/进度|P02/P12|确认→重启→纠正→删除|
|P14|模式store/CRUD/迁移|P00|手动锁、revision、空/损坏|
|P15|自动匹配和策略|P10/P13/P14|自定义第4模式、未知不猜|
|P16|既有3处页面/桌宠接线|P09～P15|普通用户设置/使用/管理|
|P17|最终回归、候选安装回退|全部|同一包含全部源码/扩展|

行为包细节见behavior-memory-plan.md；模式包见companion-profiles-plan.md。P14纯配置可独立委派；接口和共享状态由主执行者整合。不要同时多模型改coordinator/主记录。

每包先补真实失败测试再修，不降低断言。只报告实际运行的命令；缺依赖、待真人或配置未开启明确not_run，不提升为通过。

统一收尾：

```powershell
python -X utf8 -B -m unittest discover -s tests_next
python -X utf8 -B -m sumika_next.cli check
python -X utf8 -B -m sumika_next.cli handoff
git -c core.safecrlf=false diff --check
```

上述命令不能代替相应包的浏览器/音轨/PDF/安装验证。先无设备假时钟/fake provider/隔离页面，再真实站点/设备；真实操作前通知，不抢游戏输入。收费调用沿已有明确授权，不自行付费或换模型。

每包更新现有companion-implementation.md回执：目标/资产、路径和接口、命令结果/证据、真实实现与夹具/设备验证边界、剩余/恢复动作、下一包。同时更新handoff/progress/plan，保持历史编号，不再无限新增checkpoint台账。

## 7. 候选、回退与禁止错误完成

修复候选与全功能候选分别报告覆盖范围。候选内解释器验证，扩展实际存在，源码HEAD+dirty与输入齐全。schema迁移保留备份；旧程序不打开新schema，回退程序和数据成对。无本次日用切换授权时交付具体候选/证据，审批是最后一步；不从旧推送授权推断新发布授权。

不得把以下情况标完成：只有后端/生成器无UI；直接API绕过产品；只数ASR次数；selection=true无正文；数据库增长无确认纠正删除；固定学习prompt改名字称自动模式；开发环境通过但安装包没包含；模型推测/旧摘要当用户事实。

总体完成：F01～F10闭环；普通用户能观察、定义/自动匹配模式、学习并纠正意图、管理长期数据；重启/失败/撤销/安装行为与规格一致；缺少真实证据的能力继续标待验，不强行宣称完整日用平替。
