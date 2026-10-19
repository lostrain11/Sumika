# 当前主线修复与验收计划

更新：2026-10-20。总体状态：进行中，已进入验收/打包阶段。当前候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r63`，DSH `0.2.1-rc.2`，60484文件库存、实际EXE启动通过；未部署、发布或替换日用安装。手测配置见 `manual-test-r63.md`，干净机证据见 `acceptance-20261019-clean-windows.md`。提示词优化按第1种保持关闭；LES为独立P6-8实验。

## 现有资产与实施结论

沿用 `ui/app/management.js` 既有管理弹窗、`ui/prototype-d/index.html` 设计、`extensions/roles` 资源/上下文选择器、`extensions/memory` 素材与记忆仓储、`extensions/behavior` 行为领域库、DSH原生调度/审批/Skills以及 `tools/verify_*` 验收工具。结论为直接使用或改造后使用，没有另建界面、调度器或记忆系统。用户已批准的角色编辑与定时绑定控件均已实现，不再等待确认。

摄像头接线复用 `extensions/desktop/perception.py` 的授权/预热/释放逻辑（改造为可返回内存帧）、`ui/server.py` 的观察与撤销机制及 `ui/app/companion-session.js` 既有陪学详情。设计稿只有感知能力卡，没有单帧控件；用户已批准在陪学会话补充该入口。`extensions/companion/camera_frame.py` 仅是独立桌面运行时的限时单帧适配，不另建采集系统。完成条件包括逐次确认、禁用拒绝、取消/撤销竞态、原消息框消费图片、释放设备和无图片文件落盘。

## 当前实现与未完成项

|范围|已实现/证据范围|剩余验收或缺口|
|---|---|---|
|R-060 办公文件|复用官方Office技能、独立Python文件库与包内LibreOfficeKit；三格式转换、公式缓存重算、DOCX渲染|实际自然语言任务质量；任意复杂文件不承诺无损；VC++/字体及干净机器|
|R-061 OCR/截图翻译|Windows/RapidOCR可替换；现有原生截图文件翻译Skill接OCR与工作模型|实际翻译质量、用户选择图片流程；实时游戏翻译/叠层暂缓|
|R-062 桌面动作|既有UIA适配、快照守卫、参数预检、unknown不重放；隐藏自建窗口7项|真实软件的其他动作、权限窗口、游戏/高频输入；不可把静态图片当动作后新证据|
|R-063/R-064 模块/实现|现有管理弹窗支持启停、排序、添加、移除及实现选择；已有浏览器证据|其他语音/OCR引擎实际依赖与质量；当前完整手测|
|R-065 定时任务|本地提醒保留；新执行任务在原弹窗显式绑定项目/standard主会话，交给原生调度；三规则/重启/断线unknown已验|桌面提醒可见性和当前完整手测；到期投递不等于模型任务完成|
|R-066/R-067 网页咨询|新profile自动登记原生插件，既有显式禁用保留；总开关/逐站读写/逐次审批独立，托管恢复有隔离证据|实际登录与站点变化；历史发送授权已消费，不自动重发|
|R-068/R-069 模型/上下文|工作模型与角色模型分离，角色无工具；原文/代码/成果与角色附言隔离|实际模型任务与角色一致性质量|
|R-070 长期记忆|原素材与可替换索引分离；角色作用域、纠正、遗忘防复活、关系逐条CAS、导出恢复、重置；社区同集比较已做|长期真实质量和更多中文样本；Mnemon为可选验证，未日用替换|
|R-071 角色资源导入|r17沿用已验证的完整目录封装、失败回滚、导出恢复；资源与摄像头专项证据来自前一候选，r17库存重新校验。真实15MB VRM导入/导出/恢复SHA一致并实际舞台渲染，截图已查看|原文要求导入，非任意格式运行。2D动画、角色voice执行和场景运行消费者仍未实现，不把导入成功表述为运行成功|
|R-072 世界书/背景/配色|原资源弹窗可编辑；原选择器实际消费，主色/浅色生效；保存备份/CAS/内置只读|真实模型风格质量；不得再记为未实现或待确认|
|R-073及行为/模式|当前候选已含单帧摄像头，包内合成图片问答/撤销及陪学UI通过；行为/模式当前包内UI通过；既有音频/识屏保留|r27真实摄像头单帧/EMEET麦克风、真实PDF选择/双窗/缩放通过；前端与真实模型全流程、现场麦克风权限取消、B站登录态CC字幕已通过（匿名不可得）；工具栏点击已通过仍待验；10分钟持续运行已记录（末轮键盘计数缺失，键盘路径以90秒/5分钟为准）；PDF自动选区为已确认接口限制，粘贴回退已验|

逐项操作及反向检查统一见 [功能手测清单](feature-usage-and-acceptance.md)，设计对应见 [设计覆盖表](ui-design-coverage.md)。

## 已修复缺陷

- 系统默认麦克风标识丢失：sounddevice实际返回`_InputOutputPair`，旧探针只接受list/tuple，使真实默认索引1误报null。新增回归先失败，源码改为索引协议读取、负数归为未配置；不自动切换用户设备。真实包内运行时对照：旧r22枚举26设备/default=null，修复源码枚举26设备/default=1、唯一默认标记，约0.8秒，无录音。6项设备测试及PDF/窗口采集联合运行37项OK（2跳过）；r23已包含修复：60482文件库存、包内真实枚举26设备/default=1/唯一默认标志（0.628秒，源码与包SHA一致）、实际EXE四组通过。源码全量1385项OK（23跳过，129.504秒）；33项权限/取消边界测试通过，但未进行真实麦克风采集。证据：`.sumika-next/acceptance-20261018/{audio-default-r23.json,full-suite-audio-default-source.log,exe-r23.log}`。证据：`.sumika-next/acceptance-20261018/{audio-device-enumeration-r22,audio-device-default-source}.json`。

- 语音详情串行等待真实输入设备枚举，导致仅用视频标签页的文字陪学也需等待最长60秒才能出现控件。源码复用既有设备选择器异步加载，8秒客户端取消；失败保留原索引、不禁用其他功能。设备等待/失败及保存不清空配置的浏览器回归通过，源码真实B站前端选择/确认/转写/原提问路由/停止通过；回答夹具，非真实模型质量。r21不含修复；r22已构建，60482文件库存/EXE四组通过、管理JS与源码SHA一致、设备等待/失败/保留配置浏览器通过。116项管理/Bridge定向测试OK（56.768秒）。r22真实B站UI复验通过：从能力卡进入、选择待确认标签、批准、1条真实转写、原提问路由绑定目标、点击停止并拒绝迟到数据，0页面错误、Bridge已停止。证据：`.sumika-next/acceptance-20261018/bilibili-ui-r22/report.json`。连接请求调用扩展worker而非真实工具栏点击；回答为来源夹具，不证明模型质量。证据：`.sumika-next/acceptance-20261018/device-ui-source-regression.log`、`bilibili-ui-source-async/report.json`。

- B站验收工具在最终worker未存活时可能先读取尚未初始化的峰值变量，掩盖断言原因；峰值计算移至断言前并写报告。Node语法检查与101秒真实公开视频运行通过，仅维护脚本变化，无需重建产品。

- 行为输入封帧饥饿：探针200ms结果过期、250ms采样的质量切换不断重置一秒封帧计时，新增回归先复现持续操作却零帧。源码只保留隐私切换时的封帧期限，继续丢弃切换前片段/清除细粒度状态，密码与未知保护不放宽。82项定向运行OK（2跳过）；全量复验1384项运行OK（23跳过，119.461秒），r20不含此修复；r21已纳入并通过包内17项、库存及EXE四组验证。部分片段仍按隐私规则丢弃，不承诺完整事件计数。

- 真机摄像头默认OpenCV后端15秒超时；同一设备显式DirectShow约1秒读取六帧。源码Windows数字设备改为DirectShow，保留单次/预热/释放/15秒外部超时，不自动换后端重试；6项测试及源码服务真机1.828秒/640×480/有效非黑帧/停止清空/无图片落盘通过。全量源码1382项运行OK（23跳过，129.088秒）；r19不含此调整，r20包内真机2.281秒/640×480/有效帧/停止清空/无图片落盘及库存/EXE通过。

- 过期采集任务的清理最终拒绝旧令牌，但先取消了新会话语音/播放和调度。新增测试已复现，源码在副作用前先检查令牌，保留后置检查及锁外停止/等待。定向127项运行OK（1跳过，58.882秒）；全量源码1380项OK（23跳过，121.613秒）；r19已构建并通过包内回归与EXE检查，r18不含本修改，不声称消除所有并发时序。

- 语音验收脚本将`playback_started`误当SAPI文件合成完成，导致首音延迟低估，且偶数样本中位数取了上中位。维护脚本现使用真实`synthesis_ready`事件和算术中位数，3项测试通过。首轮r18语音报告功能检查有效，但`asr_to_first_audio_ms`无效；已重新测量通过，不修改旧原始报告。

- 密码探测成功结果没有独立过期、焦点失效后的在途旧结果可能恢复安全标记：已在源码增加采样时间到期校验与请求代际下限。新增回归先复现2项失败，修复后55项定向运行OK（1跳过）。r17不含本修改；r18已构建并经包内15项验证；全量源码回归1376项运行OK（23跳过，131.825秒），真实隐藏控件COM属性检查通过；r18已构建，库存/实际EXE/128格布局复验通过，不将r17旧SHA证据当作新源码验证。

- 旧PowerShell端口查询超时：改为Windows `GetExtendedTcpTable` 的IPv4/IPv6监听PID核对，保留进程存活/唯一PID/失败拒绝；33项相关检查通过。
- HTTP客户端在业务完成后断开：只关闭连接，不再次发送错误响应、不重放操作；3项定向测试及包内解释器模拟通过。
- Windows/Python3.14角色导入目录原子发布偶发WinError5：复用授权staging父目录下随机子目录并显式清理，保留校验后同卷原子发布；定向及全量回归通过。
- 既有记忆纠正/防复活、主动询问刷新重放、任务转交接收、桌面动作参数与后验unknown等修复保留；历史原因与失败方法见归档，不重新执行已完成施工。
- 资源替换曾直接覆盖旧文件，校验写失败会损坏当前角色；现写入独立版本路径，元数据用原子文件替换，异常恢复原清单/校验并清理本次新文件。目录资源保留完整相对依赖，拒绝空目录、链接、递归导入和超预算；导入ZIP在发布前核对完整manifest/资源。新增断言验证故障回滚后全部旧字节及校验不变。
- Windows目录发布再次实测出现WinError5；具体短暂占用方未证实。只在原目录身份未变且目标不存在时最多4次有限重命名，间隔40/80/120ms；不改权限、不请求替换已有目录。并发目标保留、故障有界失败，旧“绝不重试”描述仅属于历史方案。

真实输入修复后短测：30.219秒产生8帧，鼠标活动、匿名schema、连续序号和停止通过；未观测键盘，报告总体passed=false，不能称完整输入验收通过。证据：`.sumika-next/acceptance-20261018/input-flush-source/report.json`。

公开B站生产扩展实测：匿名静音40秒，434音频包、2条Vosk转写，轨道健康。使用当前源码Bridge及r20语音运行时，无字幕，无模型/麦克风；不代表前端目标列表全流程。证据：`.sumika-next/acceptance-20261018/bilibili-current-public/companion-soak-b5350f1d-09b4-4e0f-a565-30aa275b494c/report.json`。延长跳转间隔的101秒实测通过：两次跳转后最终引用时间正确、采集恢复，峰值469包/2转写（各代计数峰值，非累计）。证据：`.sumika-next/acceptance-20261018/bilibili-current-seek-long/companion-soak-cb3bcf93-50c6-4ecd-86ce-011f4cb73fd4/report.json`。每10秒跳转的45秒组无转写而失败；4次引用与暂停零新增仅局部通过，失败证据：`.sumika-next/acceptance-20261018/bilibili-current-seek/companion-soak-0e6e5a69-be20-4624-9936-a46c7c399bfd/report.json`；具体失败原因未证实，不以延长间隔通过覆盖。

## 最新证据及边界

以下路径相对项目根；`E:/SumikaBuild/acceptance-20261017-current/` 简称候选父目录。

|检查|实际结果|证据|
|---|---|---|
|r21库存/包内/EXE|60482文件完整性通过；输入worker与源码SHA一致、17项包内回归通过；EXE首次/复用/外来HTTP拒绝/认证退出四组通过|`.sumika-next/acceptance-20261018/{build-r21.log,input-flush-r21.json,exe-r21.log}`；EXE原始报告`E:/SumikaBuild/acceptance-20261017-current/exe-startup-1d4b3bee5e954a749627bb77d7625c66/report.json`|
|源码回归（源代码）|此前运行1382项，含23项跳过，129.088秒，OK；本轮封帧饥饿修复后全量1384项运行OK（23跳过，119.461秒）|`.sumika-next/acceptance-20261018/full-suite-camera-dshow-source.log`；新日志`full-suite-input-flush-source.log`|
|个人数据管理UI|设置页目录只读；迁移与恢复弹窗可打开；浏览器检查不触发迁移/恢复写入（启动时既有行为默认写入已从基线剔除）|`.sumika-next/acceptance-20261018/personal-data-ui-r16c/report.json`；维护脚本`tools/verify_personal_data_ui.mjs`|
|r20陪学控件|48项通过、errors为空；界面夹具，无真实设备或模型，不与服务实测拼接宣称全流程|`.sumika-next/acceptance-20261018/companion-controls-r20/report.json`|
|r20真机摄像头/候选|包内服务2.281秒取得640×480有效帧，停止清空，未落图片文件，未调用模型；库存60482文件及EXE四组检查通过，关键4文件源码SHA一致|`.sumika-next/acceptance-20261018/{camera-live-r20/report.json,build-r20.log,r20-source-comparison.json}`；EXE报告`exe-startup-51c666756d9d4ea48bbb21d4c837f29a/report.json`|
|r18旧录音陪学语音|实际VAD/SenseVoice/SAPI分段合成、二次语音中断8项通过；PCM清空、worker停止。两条停说到识别766.9–769.3ms、识别到首段合成73.3–216.7ms；回答为本地夹具，不证明真实模型或扬声器首音/P95。相关24项定向测试通过|`.sumika-next/acceptance-20261018/voice-sample-r18-timing/report.json`|
|r18本地语音播放|实际Windows SAPI/PlaySound完成，取消14ms、进程回收/无迟到完成5项通过；无麦克风/云调用。没有人工听感确认|`.sumika-next/acceptance-20261018/playback-live-r18/report.json`|
|r18候选基础验收|库存校验、首次/复用启动、外来服务拒绝、认证关闭、128格布局通过；0横溢出/页面错误，受管进程停止|`.sumika-next/acceptance-20261018/inventory-r18.log`、`matrix-r18/report.json`、`E:/SumikaBuild/acceptance-20261017-current/exe-startup-6e314fbb885d438abb143cd2cb6af972/report.json`|
|r18包内修复/真实粘贴|包内worker模块与源码SHA一致，15项针对性测试通过；真实粘贴HTTP/UI通过，答案仍用夹具；库存/实际EXE/128格布局均通过|`.sumika-next/acceptance-20261018/password-probe-r18.json`、`paste-real-bridge-r18/report.json`|
|密码探测修复源码回归|1376项运行，23跳过，131.825秒，OK；该修复已纳入r18及后续候选，具体包内证据见r18行|`.sumika-next/acceptance-20261018/full-suite-password-source.log`|
|修复后真实输入短测|30秒无帧，未验证通过；worker正常启动/停止，不能由无帧推断修复失效或采集成功|`.sumika-next/acceptance-20261018/input-password-fix-source/report.json`|
|r17真实粘贴Bridge|取消粘贴/状态API夹具，真实HTTP接收片段并返回目标；原输入框请求正确目标，0普通聊天回退；答案流仍为夹具|`.sumika-next/acceptance-20261018/paste-real-bridge-r17/report.json`|
|r17隐藏控件真实COM/UIA|8项通过：普通/密码EDIT的CurrentIsPassword区分、既有动作和失败守卫；前台未变、worker停止。不证明实际前台密码焦点转换|`.sumika-next/acceptance-20261018/owned-uia-password-r17/611cc63115e3423fa05a41a8f2ef4a77/report.json`|
|真实RawInput短测|当前交互桌面30.299秒、12帧；键盘计数/鼠标活动、匿名schema、连续序号、正常停止全部通过；运行自源码，4个行为模块与r17包SHA一致。未证明密码框/游戏/长时CPU|`.sumika-next/acceptance-20261018/input-real-r17-host/report.json`、同目录`source-comparison.json`|
|r17布局矩阵|128/128，0横向溢出、0页面错误；选定UI源码与包SHA一致|`.sumika-next/acceptance-20261018/matrix-r17/report.json`|
|r17 PDF粘贴UI|粘贴确认、原消息框使用选区、无普通聊天回退、无页面错误，Bridge停止；回答流夹具，无设备/模型调用。截图为测试挂载布局，不是产品视觉验收|`.sumika-next/acceptance-20261018/paste-r17/report.json`|
|r17实际EXE|首次启动、复用、拒绝并保留外来HTTP200服务、认证关闭及进程退出全部通过；当前Windows主机，未调用模型，受管进程已停止|`E:/SumikaBuild/acceptance-20261017-current/exe-startup-663789ac2e894c78b31435dcab4e0a19/report.json`|
|r17库存/原生提问|60482文件库存；库存校验通过；原生提问 option/custom/cancel 全通过，0外部模型调用，受管进程停止|`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r17/package-manifest.json`、`verify_portable_staging.py` 输出、`.sumika-next/native-approval-ui-7f96a39c18a348fab2acba4248ebfa4d/report.json`|
|前一候选摄像头/资源专项|包内Python16项通过（摄像头许可/撤销/超时、资源依赖/回滚/发布）；包内陪学UI48项通过，不采真实设备|`companion-camera-r16/report.json`；这些证据归属 r16，不自动升级为真实设备通过|
|当前候选记忆/行为/资源UI|策略5、治理17、行为模式27、资源7组通过；0外部模型请求；VRM实机渲染截图已查看|`{memory-policy-r16,memory-governance-r16,behavior-profiles-r16,role-vrm-r16-visual2}/report.json`；路径根`.sumika-next/acceptance-20261018/`|
|r16原生调度/转交|调度6组+浏览器4组，重启/到期投递仅1次本机模型调用；交接原生2组+浏览器详细检查，1次本机夹具，受管DSH停止|`schedule-integration-r16/d4c1860a5dcc43378eb1da077e971b51/report.json`、`task-handoff-r16.log`；根同上，交接原始详细目录见日志|
|新增摄像头后源码全量|1365项，140.596秒，OK，23跳过；不是r15包内结果|`.sumika-next/acceptance-20261018/full-suite-camera-source.log`|
|源码陪学摄像头UI|48项通过；取消无采集、逐次确认、原消息框图片目标、停止清除，窄屏截图已检查；夹具不采真实设备|`.sumika-next/acceptance-20261018/companion-camera-ui/report.json`|
|最终源码全量|1362项，134.309秒，OK，23跳过；既有资源/弃用警告保留|`.sumika-next/acceptance-20261018/full-suite-r15-final.log`|
|r15库存及断连修复|60481文件库存通过；包内server.py SHA一致、断连只分发一次|候选`package-manifest.json`；`.sumika-next/acceptance-20261018/build-r15.log`|
|r15 EXE|首次启动、复用、拒绝外来HTTP、认证关闭4项；受管Bridge停止|候选父目录`exe-startup-233a1cb9248f4fb88a76ca6ba039f577/report.json`|
|r15 UI矩阵|128/128，0横溢出、0页面错误|`.sumika-next/acceptance-20261018/matrix-r15/report.json`|
|r15原生审批|拒绝/取消零执行；允许一次仅本地哨兵一次；5次loopback、0外部调用，受管进程停止|`.sumika-next/native-approval-ui-b361f210e7dd43b69fcdbeecc6d542ef/report.json`|
|r15文件OCR|生成中英文图片、禁用拒绝、像素坐标及语言/预算失败关闭；不采用户设备|`.sumika-next/acceptance-20261018/ocr-r15/f755f98f629c4d8ba027cbff72851b4f/report.json`|
|r15桌面UIA|隐藏自建窗口7项通过，前台不变、worker停止；未操作用户应用|`.sumika-next/acceptance-20261018/owned-uia-r15/8f4e82eded2b44d68f0e119f909f048e/report.json`|
|r15 Office引擎|三格式PDF、公式缓存90/105/超预算、两页PNG、坏文件拒绝、源SHA不变；两页目视通过，Courier替换保留|`.sumika-next/acceptance-20261018/office-r15/b3fdf3db8dfb43538f3d4415e258539e/report.json`|
|r14专项UI/原生调度|定时6原生组/4浏览器组；提醒7、记忆策略5、治理17、行为/模式27、角色资源4通过|候选父目录`schedule-integration-r14-visual2/32949a6d6e674f0bb1998a1a00407d80/`及`{memory-policy-r14,memory-governance-r14,behavior-profiles-r14,role-resources-r14}/report.json`；保持r14归属，不称r15专项复验|

## PDF选区的当前支持边界

既有真实Edge探针`E:/SumikaBuild/pdf-selection-probe-r1/report.json`报告passed=false：真实双击后UIA GetSelection返回0，产品明确selection_unavailable；翻页后未继续返回旧选区。后续`E:/SumikaBuild/pdf-selection-final/report.json`触发150秒COM超时。此为历史真实调查，不是r22重新设备验收；不再机械重跑前台探针。现有实现保持不可用，不从空选区静默改用整页；用户批准的PDF粘贴回退已实现，r18真实HTTP/UI证据见上表。TextPattern2尚无完成证据，不宣称所有PDF阅读器永久不支持自动选区。

## 后续执行顺序与完成条件

1. r17已重建并完成库存、DSH版本与原生提问复验；治理、资源、调度/转交、模式与个人数据管理 UI专项证据仍按各自候选归属记录。继续其他保留旧构建专项及完整手测。只改维护脚本/文档不重复构建产品。
2. R-071导入按原文范围完成当前包内验证，运行支持边界继续公开；不声称动画/克隆/虚拟房间已实现。R-073摄像头包内合成链路通过，继续真实设备/模型验收。VRM专项首轮切换hash仍保留合成名册而超时，修复验收脚本为完整导航后7组通过；失败报告`role-vrm-r16/report.json`保留，不将其当产品修复。
3. 真实RawInput 90秒游戏/键鼠、真实前台密码焦点/COM、摄像头/麦克风、真实PDF（含个人PDF）已通过；继续，验证B站字幕/工具栏目标选择；不抢用户输入。R-126可沿用旧录音，无须重新真人录音。
4. 真实模型质量、实际站点与干净机器安装分别记录；没有配置/硬件/覆盖授权的项目记未测试并给恢复步骤。
5. 修复发现的问题，运行相称定向/回归，更新当前证据。需再构建时保留程序与数据成对回退，不替换日用安装。
6. 先完成当前候选P6验收；随后实施提示词优化并单独记录模型、界面、安全边界和质量证据。所有约定功能与必要验证完成后才标整体验收通过；长期愿景仍不混入当前施工。

```powershell
python -B -m sumika_next.cli check
python -B -m sumika_next.cli handoff
git -c core.safecrlf=false diff --check
```

## 2026-10-19 P6 现场探测

- 临时启动 8084 LFM2.5-24B-A2B-Q4_K_M（PID 556），模型身份与上下文核对通过；健康返回后首个请求仍耗时 186.665 秒，其余 18 例中位 6.71 秒。测试后已停止，8084 恢复未监听，8082/8083 保持在线。
- 19 例合成任务全部非空/stop；严格结构化 4/6（scene_study 误判、extract 星期输出英文）；角色用例出现 `</think>` 残留和 fresh 身份混淆，长期质量仍未通过。证据 `.sumika-next/acceptance-20261019/lfm-8084-daily.json`。
- 真实公开 B 站视频 40 秒：416 音频包、2 条转写、无错误，报告 `passed:true`；该视频无字幕 cue，字幕路径未新增证据。
- 设备枚举 54 个端点；系统默认输入 1 是 VoiceMeeter 虚拟设备，真实采集前必须显式选设备。摄像头 EMEET 就绪、系统麦克风/摄像头许可 Allow、Edge/Playwright/B 站可达。
- 用户一次性授权后已完成真实摄像头单帧（640×480、非空白）与 EMEET 麦克风 3 秒（非静音）采集，原始帧/音频未保留；真实 PDF 选择/双窗/缩放 3/3 通过（含用户指定的个人 PDF）。真实前台密码焦点、真实个人 PDF 已补测；仍未验。完整记录见 [P6 现场探测](acceptance-20261019-p6-live.md)。

## 历史与原始规格

原P00～P17执行方案、历轮候选/失败日志索引和清理前全文保存在 [归档](archive/20261018/README.md)。这些记录用于追溯和恢复；当前状态以本文件和三份连续性JSON为准。`requirements.json`、`approved-plan.md`中的原始需求、批准原文及行号未改。
