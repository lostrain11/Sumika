# 2026-10-17 通用活动与行为子记忆强化验收

2026-10-18接续：r11包内真实Bridge/UI补验结果见`feature-usage-and-acceptance.md`“r11主线治理与管理入口补验”。记忆策略5项、治理17项、行为/模式27项、定时7项、模块8项通过；候选个人目录迁移通过。仅维护验收扩充、未改变日用默认或产品界面，不扩张历史模型质量证据。R072现有设计只有预留卡，新增控件确认待答。

## 当前候选 r5：DSH最新版本及接续修复已入包

截至2026-10-17再次查询官方npm，最新发布仍是 **0.2.1-rc.2**（北京时间16:36:31发布）；`next`指向该版，`latest`仍为旧0.2.0-rc.2。日用源码运行时与新候选均精确固定rc.2，关键文件/锁文件SHA一致，无上游修改。

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r5`，已纳入任务交接接收与行为询问刷新重放修复。534个产品源码/引用文件SHA一致，55456文件库存通过；源码全量1323项通过/23跳过（121.396秒，有既有资源/弃用警告）。包内行为询问6项、真实原生交接7项、实际EXE生命周期4项、布局128格均通过，0页面错误/横向溢出；两项业务链路各1次本机合成模型调用、0外部调用。询问刷新与交接截图已查看；隔离测试Bridge及DSH已停止。

证据：候选父目录`build-rc2-r5.log`、`source-identity-rc2-r5.json`、`behavior-prompt-r5/report.json`、`exe-startup-0827a0a229b642f7a142e9c8d03614b2/report.json`、`matrix-r5/report.json`；原生交接`.sumika-next/acceptance-20261017/task-handoff-87a1e485112e40f290533d09259b3be3/{report,handoff-browser}.json`。

r4保留，以下r4/源码待入包等说明均为历史快照，以本节的r5边界为准。未部署/发布，未开启日用采集或调用付费模型；真实设备、模型质量、干净机器及其余主线仍待验，**整体未完成**。赠金需官方登录后核验资格，不能由升级推断。


## 2026-10-17 接续：主动询问刷新重放修复（源码已验，r5构建中）

复用行为库、runtime/coordinator、现有活动室询问与轮询链路，改造既有验收脚手架；不增加控件或导航。宿主合成阅读事件经真实runtime落盘询问、前端轮询显示、空回答拒绝、显式解释确认、下次本机模型请求参考及同事件去重均通过。发现刷新会从旧事件流重放已回答询问，现按库内当前用户/会话状态过滤，已回答、过期、已删除或不可读取均不再显示，既有页面也会在下一轮询移除旧询问。

源码真实浏览器6项通过：`.sumika-next/acceptance-20261017/behavior-prompt-fixed/report.json`；1次本机合成模型调用、0外部调用、0页面错误，未启动真实设备采集。库/服务定向81项通过后新增服务端回归另行通过；全量1323项/121.396秒通过，23跳过，仍有既有资源/弃用警告；日志`.sumika-next/acceptance-20261017/behavior-prompt-full-python.log`。r4只通过修复前5项，**不含刷新重放及任务交接接收修复**。新r5正在构建，包内证据待补。整体真实设备、模型质量和干净机器门槛保留。

手测：允许行为询问后，在活动室出现实际询问时填写解释并确认，刷新页面应不再出现相同询问；过期询问也应消失。没有满足条件的真实事件时不会强行生成询问。


## 行为子记忆至角色参考链路补验（2026-10-17）

复用既有行为许可、声明管理、角色输入框和参考拼接代码，不修改产品或新增控件。新维护验收`tools/verify_behavior_reference_ui.mjs`改造现有隔离Bridge/SQLite/Edge/本机合成模型框架，记录真实HTTP模型请求；只有测试角色发现列表为API夹具，声明/许可/聊天都走真实接口。

源码与r4包内Python/产品导入各6项通过：关闭记录仍可管理声明；未授予参考许可不注入；只开参考许可即可注入明确声明；纠正后只注入新内容并保留negative态度；暂停抑制、恢复后遵从已保存许可、再次关闭停止注入；删除后下一请求不含旧/新声明。每轮7次本机合成模型调用、0外部调用、0页面错误；全程未开启记录。源码截图已查看。证据`.sumika-next/acceptance-20261017/behavior-reference-final/report.json`与`E:/SumikaBuild/acceptance-20261017-current/behavior-reference-r4/report.json`。

逐项手测：设置→数据与存储→行为子记忆→添加偏好或目标→保存声明；设置→连接与权限→行为观察许可→只勾“允许参考行为记忆”→保存行为许可；回活动室聊天。再回声明行“更正”修改内容/态度，或“删除”并确认；后续角色参考应更新。暂停/恢复与关闭参考也在同一许可区。此链路证明参考传递，不证明真实模型理解质量、罕见操作主动询问或RawInput硬件采集；未开启日用采集。r4仍不含后续任务交接接收修复，最终包须重建复验。

本轮软件闭环已实现并通过下列自动化；不代表真实 Raw Input、密码探针、COM、长时硬件与安装包验收通过。未启用日用采集、切换模型、部署或发布。原工作区修复保留。

## 改造与结果

现成资产继续使用：行为 SQLite、permissions/runtime、reading tracker、coordinator、现有 management UI。新增 `activity.py` 是同库领域查询与版本化 payload 模块，不是第二套画像库。

- 前台活动：相邻核验间隔不超过3秒，按单调时钟验证连续性，墙钟跃迁时断段；每60秒、切应用/会话/模式、整点/午夜/时区边界封口。失去许可丢弃未提交片段。进程 basename，不保存标题/路径/URL/原文。统计名为“已观察前台时长”，不等于专注或电脑总使用量。
- 日常概览：最近1..31天（UI默认7天）应用/日期/小时/模式/切换，键鼠类别与快捷动作统计、输入质量/丢帧、可靠材料最近位置。SQLite聚合，不累加重叠n-gram片段时长；三天重复应用形成inferred活动参考，不能自动变成喜欢。
- 解释：按当前操作kind/序列、应用与模式确定性匹配；来源feedback必须关联仍有效的event/episode；旧无场景样本不进入当前情境稳定结论。历史用户确认与当前推断分别标记；同一基础episode去重；3样本/2session/80%条件才稳定并避免重复问。无当前query时不注入全局热门解释。
- 用户声明：兴趣、偏好、目标、限制、日常习惯，正/负态度；仅显式管理提交，NFKC规范化和revision保护；停录仍可管理；更正后新版本替代旧断言，删除后不召回。保留user/project隔离和role私有声明隔离，不自动复制到通用长期事实库。
- UI：既有“设置→数据与存储→行为子记忆”扩展；可读概览、分层分页、直接更正/删除行为解释、声明增改删。导出/迁移/删除全部保留，不增加导航。平时查看不调用全量export。
- 可信边界：网页不能指定feedback事件身份或写可靠进度；只允许prompt_feedback和授权宿主采集。模型不能直接写用户确认。
- 数据：schema6仅新增查询索引，升级前保留schema5备份；events新来源自然纳入现导出/迁移/备份/删除，不新建表。
- 明确修复：连续单向倒翻不再被判“回访”，需要真实返回已观察页；跨核验缺口不拼接。

## 验证

- `python -B -m unittest discover -s tests_next -q`：1259 run，OK，23 skipped（本次全量发现时的测试集合）。
- 后续新增输入帧去重聚合、v5→v6备份测试：`python -B -m unittest tests_next.test_behavior_activity -q`：11项通过。
- 最后相关代码更新后：行为activity/runtime/evidence/prompts/reading 组合82项OK，1 skipped；随后仅调整分层列表为最新记录优先，activity 11项再次通过。
- `node tools/verify_companion_profiles_ui.mjs .sumika-next/acceptance-20261017/behavior-ui-final`：25项通过；真实隔离Bridge验证声明保存/刷新/纠正/删除，夹具验证反馈逐条纠正/删除与配额控件；560px无横向溢出，无pageerror。截图在同目录；与原设计数据区域容器对照，新增内容为用户明确批准。
- 项目check与diff检查另在本轮handoff记录最终结果。

## 限制与下一步

- 未进行真实输入采集/锁屏桌面/游戏性能长测；统计只覆盖可核验前台间隔。不会填造历史数据。
- “兴趣”自动语义挖掘未做；浏览器进程不能推出网站主题，任务频率不能推出爱好。现有自动活动候选和用户解释闭环可独立于模型工作。
- 本轮没有统一跨领域记忆总线；原始对话/学习笔记/行为素材仍各归原owner。笔记未跨project可靠绑定，因此没有把全局最近笔记硬塞入项目行为概览。
- 长期引擎可替换架构建议见long-term-memory-plan.md顶部：素材/规范事实/可重建索引、provider/repository封装和删除后重建抑制仍是独立待实施包。没有因文档建议自动更换引擎。
- 当前声明UI显示最近50条、概览分组1000上限、分层记录每页20条；原始帧不在管理列表展开，但可显式导出，统计保留质量。
- AIHOT资讯与模型对比独立进行，结果见edge-model-news-20261017.md。

## 接续：真实键鼠验收工具修复

现成资产：改造`tools/verify_input_keystroke_soak.py`，直接复用`InputFeatureProcess`和`validate_frame`，不另写worker或匿名化协议。确认原脚本`start()`未传当前接口必需的permission，真实测试会在启动前抛出PermissionError；原`keys.counts`字段仍有效，没有改换不存在的schema。

脚本现在要求命令行`--allow-recording`，仅向独立测试worker传临时采集许可；所有启动/等待异常均进入停止与失败报告路径。全零类别不算键盘活动，右键/中键可计入鼠标活动；递归闭合schema拦截嵌套原文，连续序号、完整时长、正常停止均为通过门槛。无帧不自动归因为硬件损坏，不把部分活动当整次通过。运行方法见`feature-usage-and-acceptance.md`末节。

`python -X utf8 -B -m unittest tests_next.test_input_soak_verifier tests_next.test_input_process tests_next.test_behavior_runtime tests_next.test_behavior_evidence_lifecycle -q`：75项，OK（2跳过）。新增5项验证有效帧、零计数/缺序号、嵌套原文/跨scope拒绝、失败/中断拒绝、启动失败仍停止并写报告。均为隔离夹具，未进行真实键鼠采集，不改变真实设备待验状态。r2包未随此次维护脚本修改重建。

## 接续：真实后端行为解释UI生命周期

复用并改造`tools/verify_companion_profiles_ui.mjs`，直接使用既有行为SQLite、Bridge及管理UI；无产品控件或布局改动。脚本现在遵从`SUMIKA_TEST_CANDIDATE`并在报告写入实际源码目录，显式隔离schedule目录，正常关闭服务并释放数据lease。此前忽略候选变量可能把工作区检查误认为候选检查；历史结果仍按各次实际启动目录解释，不反向扩大证据。

在服务启动时写入宿主合成event/prompt/feedback，浏览器通过真实API执行更正、刷新、删除、再次刷新；全部删除后显式读取七层导出确认为空。平时查看阶段仍断言没有export调用。保留原有API夹具检查，其权限表单、主动询问显示、活动概览及部分并发冲突检查不冒充真实采集或真实模型。

- 工作区：`.sumika-next/acceptance-20261017/behavior-real-lifecycle-rerun/report.json`，27项通过，pageerror 0。
- r2包内Python及源码：`E:/SumikaBuild/acceptance-20261017-current/behavior-real-lifecycle-r2/report.json`，27项通过，pageerror 0，source_root明确为candidate-rc2-r2。
- 560px无横向溢出，已查看工作区`behavior-data-narrow.png`，沿用已有数据与存储区域。
- 首次扩展运行等待了产品不存在的“已删除”提示，超时；改为等真实删除HTTP响应再核对持久化结果，重跑通过，没有为迁就脚本新增UI。

本次增强的维护脚本未重打包；r2产品仍可由外部新脚本独立验收。真实设备、长期质量、全包所有功能和干净机器门槛保持待验。
