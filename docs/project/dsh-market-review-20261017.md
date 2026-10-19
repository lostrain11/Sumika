# DSH 新版本与插件复用评估（2026-10-17）

## r12 网页咨询接线修复已入包（2026-10-18）

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r12`，DSH仍固定0.2.1-rc.2。Bridge/Workbench现在自动登记既有网页咨询插件并绑定真实个人授权文件；新profile仅允许原生项目登记表中确属项目的standard主会话，已有显式禁用/preset/项目白名单保留。用户总开关在发送/读取外站前实时核对，逐站授权与原生逐次发送审批仍独立生效。包内Python通过已有run_module.py进入实际产品模块，不依赖开发机PYTHONPATH。

源码21项Python/7项Node定向通过；r12包内Python+包内产品代码启动真实受管Workbench，5组检查通过：新profile自动登记/路径、关闭拒绝、审批拒绝、取消、允许一次但无站点授权时停止。7次loopback合成模型请求，0外站消息；审批服务使用合成应答器，不冒称真实网页按钮点击，实际模型质量/站点发送不由此证明。源码全量1351项、202.376秒、OK（23跳过，既有资源/弃用警告仍在）。首轮1351项有2项语音夹具目录WinError32、1项profile原子替换WinError5；3项单独复跑通过，构建完成后新E临时目录全套通过。保留两轮与定向日志；具体占用来源未定，不声称已修根因，未修改相关产品/测试来压错误。

候选60476文件库存通过，545个产品源码/登记文件SHA零差异；实际EXE4项及布局128/128通过，0横向溢出/页面错误，测试Bridge均已停止。构建复用r11经校验的同版物理DSH/依赖；源码pnpm链接的首次构建拒绝日志保留。仅文档和验收脚本import guard在构建后同步，原manifest和前后SHA保留，产品/runtime未改。候选未替换日用安装或发布。

证据：`.sumika-next/acceptance-20261018/{full-suite-review-registration.log,review-registration-sharing-focused.log,full-suite-review-registration-clean.log}`；候选父目录`{build-rc2-r12-physical.log,inventory-r12-final.json,source-identity-rc2-r12.json,matrix-r12/report.json,exe-startup-3676b3d91cbc4d7d80637e7a5c849b66/report.json,managed-review-r12/7604bc367eb340fc852949a541245c5a/report.json}`。

**操作：**「设置 → 连接与权限 → 网页咨询授权 → 启用网页咨询」，按既有控件授权站点并绑定受管页面；随后在「工作台」的已登记项目主会话提出网页交叉审查，核对原生审批中的完整发送文本。新profile首次开工作台自动登记插件，已有实例升级后需在无执行/待审批任务时正常停止并重开；关闭总开关立即阻止新的网页操作，无需重启，不承诺已发给外站的生成会被终止。原生插件被用户显式禁用时保持禁用。无需手改profile；不自动登录、绑定、发送或消耗既有授权。

用户已批准在同一个角色资源弹窗补齐背景/世界书/角色配色，代码尚待接续。定时任务旧执行入口与原生任务的整合仍待做，角色/设备/实际模型/干净机器等全项目剩余项继续核验；本轮通过不等于整体完成。下文“源码已验、r12待验”保留为本次构建过程记录，以本节结果为准。


## 原生自动化任务实测与剩余接线（2026-10-18）

r11 内置 DSH 0.2.1-rc.2 已有原生定时服务、四个 schedule 工具和「自动化任务」页面。实际 Web profile 已挂载，不能沿用工具包旧注释的“默认关闭”判断。优先复用该执行引擎，不再扩建另一套 Agent 调度器。现有 Sumika 本地提醒不会激活模型，语义不同，不能静默迁移或把原本 blocked 的执行定义自动启用。

包内模块/DSH/皮肤、隔离 profile、合成任务与真实 Edge 通过8组检查：一次性/每日/每周创建、Asia/Shanghai 时区、现有自动化任务入口及列表、API编辑与旧版本冲突拒绝、跨会话删除拒绝、管理不激活模型、重启保留任务、到期回原会话、完成后重启观察无重放。总计5次本机合成模型请求、0外部请求。截图已目视检查。编辑和删除是API验收，不冒称界面点击通过；浏览器本轮只验证原生入口/列表。证据：`.sumika-next/acceptance-20261018/native-schedule/4b3c1b45b23b4247a58b28860020a596/{report,browser-report,evidence}.json`、`native-schedule-manager.png`。复现：`python -B tools/verify_native_schedule.py --product E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r11 --browser`。先前两轮失败为维护脚本的无参catalog与session/page游标格式错误，失败报告保留，未修改上游或产品来适配。

**使用入口：**「工作台」启动受管DSH → 左侧「自动化任务」查看原生任务；「新建」进入原生会话，在会话中明确任务内容、时间、时区并要求创建。创建行为取决于当前工作模型调用原生工具；合成模型证明工具/投递链路，不证明任意实际模型理解准确。当前 Sumika「能力 → 定时任务」弹窗的执行选项仍需绑定，不能宣称这一旧入口已可执行。下一步须整合已有入口与原会话绑定，不新增平行任务列表，不自动迁移旧定义。原生投递回执默认保留30天/200条，与行为素材长期保存无关，不承诺永久任务审计。

网页咨询另有交付缺口：`review_dsh.mjs`及worker虽已入包，`ui/workbench.py`的新profile安装流程没有登记该插件；源码和候选默认profile当前均未创建。历史日用手工登记的成功只证明当时profile，不能扩张为全新安装可用。后续补便携登记、真实个人registry路径、工作区/preset白名单与开关接线后，须用隔离无外发验收；既有真实网站发送授权已耗尽，不重发。

本轮只增加维护工具与记录，产品和r11构建不变，无需重打包。主线整体未完成，世界书/主题新增控件仍等待此前问题的答复。


## 当前补验：r8 官方办公引擎与运行时探测（2026-10-17）

当前内部候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r8`，DSH仍固定最新发布的0.2.1-rc.2。复用官方Office技能、workspace-dependencies工具、LibreOfficeKit0.1.5及其已随包提供的Windows引擎；只改公开profile接线和独立依赖层，不改上游或新增UI。

已修复：局部bridge库遮蔽完整Office环境；桌面/摄像头就绪探测忽略选定运行时；依赖载荷继承旧dist-info造成版本歧义。当前载荷从干净site-packages安装17项SHA锁定依赖，包含NumPy2.5.3/Pandas3.0.6/tzdata2026.5，无重复元数据。`prepare_office_payload.py`不再携入基础bridge的第三方包。

验证：源码1329项/129.549秒OK，23跳过，既有警告保留；最终定向19项通过。r8库存60468文件；537文件比对仅外部维护工具`verify_capability_package.py`在构建后推进，产品源码一致。包内Bridge/desktop/voice/Office导入、中文OCR创建、VAD加载、process-audio能力探测通过，未开启采集或播放；实际EXE首启/复用/外部端口拒绝/认证退出4项与128格布局通过，无横溢出/pageerror。

r8真实DSH自动注册7技能和依赖工具，技能包含包内Node/CLI路径；四类文件读建改重开、原生终端导出PDF和重算7通过（14次loopback夹具调用、0外部调用），证据`.sumika-next/p5-office-ca98a52081bf4388b365e9a9e53848ec/report.json`。官方引擎另测三格式各2页PDF、跨表公式90/105/超预算及公式保留、2张DOCX预览、损坏输入拒绝、源SHA不变；两张PNG与人工审阅版本SHA一致，证据`.sumika-next/acceptance-20261017/official-kit-r8/681024087a834a1eb78ee662ec6e0c6d/report.json`。此前r6“官方引擎禁用”和“numpy/pandas未提供”属于历史快照，r8已补齐；r7曾继承旧tzdata元数据，不作为最终候选。

复现：设置`SUMIKA_TEST_CANDIDATE`为r8，运行`python -X utf8 -B tools/verify_phase5_office.py --native-office-workflow --native-office-engines --repair-fixture-acl`；依赖无设备检查使用`python -X utf8 -B -m tools.verify_capability_package <candidate> --require-office --require-process-audio --output <新报告路径>`。ACL只处理生成的测试工作区。

边界：引擎报告Courier字体替换；依赖Windows VC++v14运行时，尚未在干净机器验证。旧sumika-office开关只控制自身runner，不能关闭官方技能或撤销终端权限。自然语言自主任务质量、任意文件无损、真实设备/站点和整体验收未完成；未部署/发布，整体目标保持进行中。

## 以下为此前阶段记录


## 2026-10-17 同题公开 CLI 实测（当前结论）

现成资产：复用 `tools/evaluate_memory_quality.py` 的全部 FACTS/CASES 与本地 evaluate；改造 `.sumika-next/dsh-memory-eval/eval_ltm.py` 的公开 CLI 流程，避开旧脚本固定路径删库；直接使用已安装的 `@tr1v3r/dsh-ltm` 0.3.1 公开 CLI。新增 `tools/evaluate_community_memory.py` 只负责隔离研究编排，每次新 UUID 目录，不剪取插件私有 store，不安装、不读取真实素材、不更改产品配置。语义对照复用现有离线 Python/embedding cache。

|同一14例中文合成题|结果|具体限制|
|---|---|---|
|DSH LTM 0.3.1|11/14|休息时间误召回牙医；两个未知问题均误召回鼓手|
|现 EmbeddedMemory|8/14|六条同义改写无召回|
|现 SemanticMemory|13/14|“哪些食材是我不能吃的”未召回花生过敏|

LTM 纠正持久化、旧 revision 写入拒绝、遗忘后列表移除均实测通过；将遗忘前导出再次 import 会恢复该事实。这是普通备份恢复语义，不单独作为插件 bug；它不能直接取代 Sumika 已实现的永久 purge guard。公开 `search` 无 scope 参数，本轮用单 scope 独立库，不把这当成插件原生跨角色授权通过。

**采用决定：保留当前 canonical SQLite 和 embedded/semantic；本轮不替换为 LTM。** 小题集不能证明总体优劣；Mnemon仍是可选只读宿主接缝，并非新的检索引擎。Engram 的离线启动与自动摄取限制仍待正式环境验证。没有新增前端入口或改变日用默认。

复现：`python -X utf8 -B tools/evaluate_community_memory.py --cli D:/DeepSeek/dsh-home/profiles/memtest-ltm/node_modules/@tr1v3r/dsh-ltm/bin/dsh-ltm.mjs --semantic`。Windows测试清理需 `CODEBUDDY_SAFE_DELETE_ENABLED=0`。证据：`.sumika-next/community-memory/7f319ed8658b47999e85de7fb1a193d8/report.json`，同目录 `calls.json` 保留每次命令、返回码、完整合成响应和时间；CLI启动包含在延迟中，不能与进程内查询直接比较耗时。两次14例分数一致，第二次含治理检查；无外部模型调用。


## 当前执行优先级补充

最新接续：Mnemon只读Source的真实settings绑定和原生Agent召回/关闭/取消等10项已通过（`.sumika-next/mnemon-host-06f6afeeaeb443a4bab12f2320de1b17/report.json`），保持canonical SQLite和现有检索，未切日用。6次loopback夹具调用、外部模型调用0；不证明候选检索质量提升。下方“真实Agent待验”是历史阶段，当前selected-message离线purge已完成（无前端入口，备份/外部副本保留），剩余社区检索质量对照和最终整体候选验收。

接续验收计划：复用下载的 Mnemon 0.5.29 发布包公开 `testing` / `extension-sdk`，以及隔离 rc2 中真实 Cordis 4.0.4；以合成 SQLite 规范记忆验证只读 Source 的作用域、纠正、遗忘与旧回合失效。试验代码归入 tools，运行数据归入 `.sumika-next/`，不安装 starter/provider，不改共享运行时或日用配置。此步仅验证组合契约，不代表新检索引擎质量或产品接入完成。

Engram 0.8.12 新增源码限制：发布包 `cordis.patch.yml` 实际设置 `ingest: light`，与其注释所称发布默认 off 不符；仅 resolver 的默认值是 off。`apply()` 无条件调用 `createLocalEmbedder()`，后者通过 Transformers pipeline 加载 `Xenova/bge-small-zh-v1.5`，缺缓存时可能联网下载，配置无明确 offline 开关。因此不能按“关闭摄取即完全离线”直接安装，需正式隔离网络/预备模型缓存或上游提供离线接口后再测。当前不剪取私有 store，也不通过伪造依赖冒充验收。

用户已明确当前重点为长期记忆和DSH/开源复用，长期愿景先不做。接续优先M00与M04，其他候选保留，不因市场调研自动替换整套模块。

本次只读进程核查发现 PID3016 的 Node 入口指向全局 `D:/DevTools/npm-global/node_modules/@deepseek-ai/dsh/lib/bin.js`；本机另有其他 Node 进程。该结果仅证明存在此全局入口进程，**尚不能证明Sumika前端正在使用它或确定活动profile**。仍需以受管状态、前端连接及该包实际版本交叉核验，不能按计划中的rc2认定活动运行时。未输出完整命令行、凭据或修改进程。

资产复核：Mnemon 0.5.29发布包有公开contracts/testing/extension-sdk入口，可用于薄Source试验；native provider仍需另装CLI。Engram 0.8.12发布包将SQLite store打包在单一index内，公开导出不包含store，直接剪取私有函数会增加维护负担，不采用这种方法；后续应走正式宿主插件工具接口或要求上游提供稳定后端接口。两者均未通过本项目治理门禁，暂不接生产默认。

本轮是调研与隔离验证，未升级日用内核、安装到共享 profile、替换产品模块或新增界面。结论供后续实施选择，不构成所有候选的安装兼容验收。

## 1. 结论与优先级

值得用上游减少维护，但应替换具体 provider 和 DSH 接缝，保留 Sumika 的权限、数据所有权和跨应用协调。当前没有一个经过完整验收、可立即整体替换行为理解/长期记忆/陪伴模块的插件。

建议实施顺序：

1. **P0：先查清桌面进程实际使用的 DSH 版本并统一版本记录。** 仓库、全局 CLI、隔离候选目前并非同一版本；不能在未知版本上宣布插件可用。
2. **P1：BrowserSkill 官方桥与 Windows 操作 MCP 的 provider 试接。** 上游维护收益直接，保留 Sumika 对站点、窗口、动作和执行后核验的约束。
3. **P1：优先复用官方 Office、Session 查询、语音输入等原生能力。** 不另建同类入口；语音输入只解决转草稿，不能替代全双工陪伴。
4. **P2：PDF Reader 先接文献检索/页码引用/学习档案后端。** 整套三栏 UI 是未批准新增，不能直接装进产品。
5. **P2：Mnemon 作为可组合记忆框架深入试验；Engram/Mneme 作检索、治理对照。** 先完成素材/规范事实/provider 索引边界，禁止将角色记忆一次性搬进某插件私有库。
6. **P3：Partner、备份、语音和诊断工具只按缺口试用。** 暂不把多角色、计划、市场、备份和用量都改成插件各自的一套。

## 2. 现成资产与使用决定

| 资产 | 决定及用途 |
| --- | --- |
| `docs/project/dsh-plugin-compatibility.json` | 改造后使用，保留 10/08 实测及当时版本，追加本轮观察 |
| `docs/project/reference-projects.json` | 直接使用，继续作为参考项目清单，更新市场观察 |
| `docs/project/long-term-memory-{plan,evaluation}.md` | 直接使用，保留已有中文基线与素材分层方向 |
| `extensions/desktop/browser_skill.py`、`extensions/desktop/control/`、`extensions/companion/` | 改造后使用；provider 可换，授权与协调保留 |
| `tools/verify_dsh_plugin_lifecycle.py`、`runtime/dsh/README.md` | 直接使用，作为后续隔离安装与生命周期验收入口 |
| `tools/evaluate_edge_news.py` | 复用只读、有界、来源留痕的抓取方式 |
| `tools/review_dsh_plugins.py` | 本轮补充通用 npm 元数据/源码快照工具；不安装、不执行包脚本 |

无产品 UI 改动。后续涉及界面必须先对照 `ui-design-coverage.md` 和设计稿；同能力保持单一入口，不能借装插件加入第二个角色/项目/能力面板。

## 3. 实际版本与上游变化

| 对象 | 查到的版本 | 解释 |
| --- | --- | --- |
| 仓库 `runtime/dsh/package.json`、release 与其安装包 | `0.1.5-rc.2` | 不能按其他候选的版本理解它 |
| 全局 `D:/DevTools/npm-global/node_modules/@deepseek-ai/dsh` | `0.1.0-rc.6` | `Get-Command dsh` 指向此全局脚本 |
| `.sumika-next/dsh-upgrade/0.2.0-rc.2/` | `0.2.0-rc.2` | 隔离候选存在，不等于当前桌面正在运行 |
| npm `latest` | `0.2.0-rc.2` | 稳定标签仍落后，不作为升级目标 |
| npm `next` | `0.2.1-rc.2` | 10/17 发布；当前日用固定版本 |
| npm `alpha` | `0.2.1-alpha.5` | 10/16 发布；不能因更近就自动升 alpha |

本轮未证明桌面 App 的活动进程绑定哪一个 profile/安装目录。实施前读进程路径和受管状态接口核对，输出只含版本、路径、PID，避免输出认证参数。

alpha 线重要变化：alpha1 自动化成为 Web 内置；alpha2 增加实验 Session 状态记录、SSH helper，子 Agent/session/wait 与团队消息契约改变；alpha3 Office 渐进加载及按需引擎、会话恢复/持久化修复；alpha4 自定义插件索引及 `engines.dsh` 优先兼容规则；alpha5 修复插件切换后的 Skill 菜单刷新等。

这些变化可能减少 Sumika 的宿主适配，但不会自动迁移现有持久化、角色 scope 或 UI slot。rc.2 与 alpha.5 必须分别建候选，不能混装同一套 `@deepseek-ai/dsh-*` 核心包。

## 4. 来源与证据强度

- [dsh-market/dsh-market](https://github.com/dsh-market/dsh-market)：npm `dshmarket@1.66.30`；目录 [awesome-dsh-plugin](https://awesome-dsh-plugin.com/plugins.json)，本轮 4782 条、23 分类。
- [dshplugin/dsh-plugin-hub](https://github.com/dshplugin/dsh-plugin-hub)：npm `dsh-plugin@2.0.0`；[中文目录](https://api.dsh-plugin.org/plugins.zh.json) 本轮 4636 条。两市场有重叠，不能相加称为独立插件数。
- [官方 npm 包](https://www.npmjs.com/package/@deepseek-ai/dsh) 的发布元数据、官方 release notes 与固定 alpha.5 包源码。
- 重点第三方 28 包取得 npm 元数据，其中 26 包源码在快照阶段通过 npm SHA512 校验；Partner、Univer 超过本轮 12MB 压缩包上限，未完整下载。Partner 补读固定 `v2.8.4` README/架构；Univer README 固定 npm `gitHead`。
- GitHub 维护元数据请求遇到 403 限流，因此没有“最近 CI 全绿”“提交活跃”的验收结论。npm 发布时间只能证明发布，不能证明维护质量。

快照与 receipt 位于 `.sumika-next/dsh-market-20261017/`，属于本地忽略证据，未把运行数据提交为源码。候选版本不是市场列表显示值，而是 registry 实际解析值。市场 verified、下载量、宣传 benchmark 均不等于本项目验收。

## 5. 模块映射与采用判断

下表“门禁”统一用 alpha.5 发布源码的静态 manifest 判定：`includePrerelease:true`；有 `engines.dsh` 时它独立决定，否则匹配所有 DSH peers。没有声明只表示没有版本门槛，不代表 API、Cordis、React 或原生依赖兼容。**该规则不能倒推旧版本宿主的安装结果。**

| 候选（本轮版本） | 可补充/替换范围 | 决定与主要条件 |
| --- | --- | --- |
| `@wxg-prc-cpg/browser-skill-dsh-plugin@0.3.3` | DSH 浏览器工具/session 生命周期桥 | 优先试接；0.1.5-rc.2 声明不满足，0.2.0-rc.2 满足；CLI、扩展、插件需一致 0.3.3；旧 `browser_*` 已改 `bsk_*` |
| `dsh-computer-use-win@0.4.1` | Windows UIA、OCR、输入执行 provider | 优先隔离试接；Node≥22、PS5.1；不替代 RawInput 行为采集、权限或核验层 |
| `@ggboy123/dsh-paper-reader@1.5.0` | 文献库、PDF 页码检索、阅读计划 | 后端候选；MinerU/embedding 默认关；翻译可能安装工具及调云；新 UI 另行决定 |
| `dsh-mnemon@0.5.29` | 可组合 Source/Strategy/Core/View 和记忆 provider 接口 | 记忆框架首批实验；0.2rc2 门禁通过，当前仓库版本不满足；scoped 是 Source 选择策略，非角色权限沙箱 |
| `@kenz1117/dsh-engram@0.8.12` | FTS/本地向量/RRF、来源引用、导出 | 检索对照；自动摄取默认关、画像注入默认开；user/project 不等于 user/role/project 三元隔离 |
| `@modusensus/dsh-mneme@0.8.16` | SQLite/Markdown、冲突处理、审计、整理 | 治理对照；必须显式核对 strictScope、归档/保留期限和额外 sidebar 依赖 |
| `dsh-prime-memory@0.26.1` | 分层蒸馏/画像 | 暂不作为默认；默认智能档有自动 LLM 提取成本，chat/work 分族不足以证明角色隔离 |
| `@tr1v3r/dsh-ltm@0.3.1` | 检索 provider | 同前次版本；本轮 alpha5 规则对 0.2.0-rc.2 的 `<0.2.0` 门槛实际通过，alpha.5 不通过；不得仅凭字符串推断 |
| `@fooxe/dsh-memory@0.13.6` | 简单记忆工具 | 不替换现 semantic 基线；同前测版本，缺少本项目所需语义/隔离/删除能力证据 |
| `@max-null/dsh-memory@0.15.1` | global/project 记忆 | 不直接采用；README 明确模型写入可直接 approved，与“人工逐条确认”的市场描述不同 |
| `@lemoncat7/dsh-partner@2.8.4` | 多身份、能力授权、记忆、回顾、任务协作 | 高价值架构对照；仅元数据与固定 tag 文档审阅，未完整源审/安装；整包重叠大量 UI/调度/角色流程，不宜立即替换 |
| `dsh-tavern@2.7.17` | 角色卡、世界书、角色记忆 | 功能差距对照；许可证为 PolyForm Noncommercial Copyleft，不能按 MIT 纳入分发 |
| `dsh-voice-mode@0.7.24` | 流式本地 ASR、打断、可选本地 TTS | 语音 provider 对照；默认 Edge TTS 属云端；sherpa/native 与模型准备需单验 |
| `@goodandready/dsh-voice@0.9.36` | 多 ASR provider、SenseVoice HTTP、OpenAI 兼容 | 可对接笔记本；锁定单一本地 provider，禁用自动云 fallback；Web Speech 不等于离线 |
| `@goodandready/dsh-tts@0.4.33` | Piper/eSpeak、句级队列与打断 | 可参考/试接；Kokoro/F5 下载与探活不等于附带推理引擎或可开箱克隆 |
| `dsh-vision-router@3.0.4` | 图像/OCR provider 路由 | 默认不接；匿名 OVHcloud 云兜底需关闭，本地像素操作可以单独评估 |
| `@liustack/modlens@3.27.1` | 显式视觉、结构化 OCR | 限定本地端点后再试；其他 CLI 登录态、免费云不能当既有授权 |
| `@goodandready/dsh-vision-bridge@0.6.21` | 图片请求桥/视觉 fallback | 暂不默认；包装 `ctx.llm` 方法且默认 hybrid，升级耦合大；只读工具方式可另测 |
| `@xiaoyuyu6420/dsh-backup@0.13.4` | DSH profile 备份/救援 | 补充候选；不能覆盖 Sumika 外置角色/行为库；SQLite 一致性与凭据 vault 单验 |
| `dsh-config-manager@0.1.76` | 配置/插件/Skill/MCP 迁移 | 非全业务备份，不替代 Sumika 数据包；远同步/凭据功能默认不启 |
| `dsh-cost-meter@1.8.35` | DSH 会话成本、预算 | 只补 DSH 口径；独立 RoleChat/companion/笔记本调用需桥接 UsageStore，不能宣称全量 |
| `dsh-plugin-ops-bundle@0.20.2` | 插件诊断/修复建议 | 先只读诊断；部分分析会用模型，不自动执行修复或改变发行摘要 |
| `@noob-stupid/dsh-plugin-console@0.5.51` | 预检、插件治理、回滚 | 不接自动升级/改依赖树；与受管发行 hash 冲突，先研究只读规则 |
| `dshmarket@1.66.30` / `dsh-plugin@2.0.0` | 插件发现 | 最多选一个入口；后者精确 Cordis4.0.1 与 RC2 4.0.4 仍需真实兼容验证 |
| `@wxg-prc-cpg/dsh-weknora@0.1.0` | 4 个只读知识库工具 | 条件候选；依赖自托管服务，本地服务并不违反本地优先；不能替代日常行为/角色记忆 |
| `@lovedolove/veyra@0.1.53` | 工程记忆/RAG | 任务对象不同，作项目知识候选；注意 Node 上界 `<25` |
| `dsh-univer-office@0.3.7` | 内嵌 Office 编辑 | 暂不整体引入；226MB unpacked、pro bindings 与第二套 UI；官方文件技能优先，不等同 live Excel/COM |

## 6. 重点候选的边界

### BrowserSkill

新桥有六个聚合工具与 session ownership/lineage 管理，能减少跟随 DSH 事件契约的维护。Sumika 现有 `BrowserSkillClient` 及站点 read/send/borrow 许可仍是重要资产。插件的自有 session 隔离不能证明用户站点发送授权已满足。

实施时将 provider 翻译为统一 navigate/observe/submit/borrow 接口；read 与 send 不合并；URL 跳转后重查站点；执行请求保留 request_id、UNKNOWN 和禁止自动重发语义。保留现有被动单 tab 音轨、字幕、媒体时钟及 `media_epoch` 协调，不能据 `video` 工具名推断已经等价。

### Windows MCP

隔离 Node 进程仅发送 `initialize`、`notifications/initialized`、`tools/list`，成功返回版本 0.4.1 与 9 个 lite 动作/读取工具及 1 个工具发现入口。没有 `tools/call`，没有截屏、读取窗口、键鼠动作或 PS backend 验收。

后续通过 native MCP 接入或独立 provider，但每个动作仍须走 Sumika 的已授权窗口、前态哈希、动作范围、执行后核验。UIA RuntimeId、OCR 屏幕坐标、DPI 和窗口 handle 必须区分；找不到元素不能静默改点坐标。`--self-test` 会读桌面，不属于本轮检查。

补读同一 SHA512 已校验 tar 内的 `scripts/windows-uia.ps1`：包含 UIA Value 读取、输入后 `verifyValue` 回显、剪贴板粘贴及 Unicode 输入；未找到 `IsPassword` 判定。不能因此声称密码必被读出（系统通常限制读取），但该 provider 本身未证明符合 Sumika 敏感输入门禁。试接前须在宿主侧做焦点敏感性检查、禁止密码/敏感控件自动采集与回显，并验证剪贴板恢复失败处理。以上为静态审阅，未操作真实输入框。

### PDF Reader

纯 Node 后端的合成夹具验证通过：同名文献需 topic；乱序完成仍仅一个 current；学习计划落盘再读一致；写路径拒绝 `../`；页码偏移查找；删除进 `.trash` 且不动另一专题。

同时确认 `resolvePaper({path})` 按设计允许显式库外文件，不是根目录权限边界；Sumika 必须先验证授权路径。`study.js` 直接写 JSON、损坏时返回 null，尚无本轮崩溃一致性/并发证据，不能直接当规范记忆库。初期只读检索与引用优先，学习记录保留来源映射。未验证真实 PDF 解析、渲染、OCR、翻译、云调用、DSH 安装和前端。

### Mnemon 与长期记忆

Mnemon 将 Source/Strategy/Core/View 拆开，适合避免绑定单一记忆引擎。已读 native provider、Memory Spaces source、scoped strategy 发布源码；native CLI 需另装，soft delete、fallback 和可写 Source 必须显式配置。

`sourceKeys/writableSourceKeys` 只控制组合哪些 Source，不能当作不同用户/角色的读写隔离。默认全部 ready Source 时有扩大检索面的风险。初期只挂一个合成专用 Source，auto-capture 和 embedding 保持关闭，禁用未指定 provider fallback。

Sumika 独立保存：原始素材与来源、规范事实及 confirmed/candidate/rejected 状态、可重建 provider 索引。插件输出只作为候选或检索结果，不因写入成功成为 confirmed。MemoryWriter/删除传播/备份与回放由 Sumika 契约保证；不是让每个记忆插件都各自监听全部聊天。是否替代现 semantic，须固定相同中文集、相同许可与隔离集实测，不能比较不同样本的广告得分。

### Partner

固定 tag 文档显示其能力授权、身份作用域、仓储分层、撤销重检、失败与任务恢复边界比“只是聊天壳”更完整，值得后续定向源审。但它自带身份/工作区/任务/计划/协作界面；本轮未完整下载、未运行测试，不能把文档中的回归声明算成本项目通过。优先对照授权撤销、记忆提取和主动回顾的小边界，而非立刻将整个 Sumika 换成 Partner。

## 7. 官方能力：先复用，少加第三方

| 原生能力 | 可减少的维护 | 必须保留/核验 |
| --- | --- | --- |
| `dsh-session-query` + 实验 session-search/tool-session-query | DSH 历史读取与查询适配 | 搜索按精确 cwd 控制，不包含 Sumika role scope；共享 cwd 不可裸开放；连续性事实库与原文继续独立 |
| `dsh-schedule` | 原生提醒、投递、恢复 | 无变化不唤醒模型的确定性 ReferenceRunner 门禁仍保留；alpha1 自动化已内置，旧 rc2 实验 bundle 结论只属历史 |
| `dsh-skill-office` | docx/pptx/xlsx、渲染、重算、PDF 导出路由 | Python/LOKit 按需准备；不是 live Office；资产、格式与渲染 QA 保留 |
| 实验 voice-input bundle | 麦克风→本地 SenseVoice→输入草稿 | 默认关闭、显式准备模型；不是音轨伴听、TTS、barge-in 或实时协调器 |
| 实验 Session 状态记录 | continuity 的 DSH 事件接线 | 实验 API 单独适配；来源信任、原文与跨 Harness 恢复数据不能只放宿主 |
| 原生 plugin-market | 单一 Installed/Discover 管理入口 | 本身没有官方目录；自定义源必须符合新 schema；原生 pluginManager 仍负责安装 |

原生索引解析器对两个现有社区目录的实测：awesome 在 `$.format` 失败（要求 1），Hub 根数组失败（要求对象）。若选择原生市场，应生成符合规范的只读索引投影，固定版本/来源并做 schema 校验；不是把旧 URL 直接填进去。该投影目前未实现，亦未新增市场 UI。

## 8. 可交接执行包

以下是后续执行方案，不是本轮已完成或自动获准的产品替换。每包独立验收，失败不影响当前日用。

### M00：基线与版本

1. 查活动桌面进程、管理接口、受管 release、profile；列出真实路径/版本，不输出 token。
2. 在 `.sumika-next/` 建专用无凭据 profile；固定单一官方版本和依赖锁。不触碰共享 profile/node_modules。
3. 复用现生命周期工具验证安装/加载/停用/重启、配置保存、既有 native UI。若只有 alpha 支持，单列 alpha 候选，不能升级现用户默认。
4. 验收：实际运行版本唯一且可解释；候选启停后日用进程、端口、配置与发行 hash 保持原值。

### M01：浏览器 provider

1. 记录旧 bsk0.1.11 的版本、授权 JSON、站点许可、会话语义与现测试；仅备份读取，不升级它。
2. 独立目录准备官方 0.3.3 插件/CLI/扩展，核完整性、许可证、版本匹配；不能就地覆盖旧扩展。
3. 适配现客户端接口至 `bsk_*`；所有生产调用仍经许可桥，模型不绕过桥直接调用有写能力工具。
4. 用本地 fixture 网页测 read 可读但不能 send、跨站重检、borrow/return、超时 UNKNOWN、不重发、关闭 session；真实登录另验。
5. 通过后只替 DSH 工具桥；provider 开关可切回旧实现，旧授权格式不破坏。

### M02：Windows provider

1. 基于已补读的 PS 源码继续核输入、剪贴板、副作用及敏感控件门禁，不能仅凭 MCP schema 验收。
2. 在专用测试窗口操作，覆盖 UIA/纯 OCR、DPI100/150%、移动窗口、句柄失效、权限不足、卡死超时、执行前状态变化。
3. 适配统一动作结果 `verified/unknown/failed`，不把 tool 退出0等同成功；无授权必拒绝；不扩大到后台采集。
4. 与现 Python provider 比较成功率/延迟/依赖。达标后换 provider 默认，保留回退开关与既有批准入口。

### M03：PDF 后端

1. 先只读挂载用户已授权文件；不扫描全盘、不装翻译引擎、不调用 MinerU/embedding 云端。
2. 映射 document_id、内容 hash、page、quote、source_id；重名/移动/文档更新均不能错引。
3. 验真实中文/扫描件/公式/缺页文件，答案引用可追溯；学习计划重启、并发写、损坏与恢复单验。
4. UI 先复用已有伴学区域。新阅读器界面需先对照设计、确认新增范围；验证原外部 PDF 和粘贴回退继续可用。

### M04：记忆候选

**只读适配接续：** `extensions/memory/mnemon-source.mjs` 已实现宿主binding/epoch/开关及前后版本与取消校验，15项真实SDK契约通过（`.sumika-next/mnemon-contract-0a14dedb11f84b02b890681f9f8fed6f/report.json`）。不是固定fixture转产品，不安装新引擎；客户端resolver和实际Agent回合仍待接线，不能将框架适配当成检索质量提升。

**正式隔离宿主接续已通过：** `python -B tools/verify_mnemon_host.py` 使用独立 rc.2 home 与公开 Mnemon0.5.29 root 插件，原生 patch 加载、RPC dashboard、合成 canonical 只读 Source 注册、禁用后重启移除均通过。未加载 starter/bundle/provider，关闭自动读写/摄取、同步和遥测，无模型调用，日用未变。Source 与 SDK 试验共用 `tools/lib/mnemon-canonical-fixture.mjs`；10项SDK契约再次通过。实验依赖及锁文件保留 `.sumika-next/mnemon-host-deps` 复用；安装使用 ignore-scripts，未修改既有共享依赖。固定scope测试夹具不能直接作为产品角色插件交付，真实Agent、关闭/切角色和UI仍待验；检索仍为既有FTS，无质量提升结论。宿主最新证据见记忆验收顶部，旧阶段“未完整安装”不再适用于这次隔离宿主验证。

**持久化版本接续：** Source试验现改用规范SQLite的scope revision，跨Python进程读取；纠正/遗忘触发器与规范变更同事务，不再依赖fixture内计数。相同10项再次通过，最新证据 `.sumika-next/mnemon-contract-fb83ec19dfac4159a8b9e4b46bc2556e/report.json`。因此下方“fixture进程内revision”的限制仅对应首轮历史；正式宿主映射、取消/并发压力、文件级历史恢复的lease重置仍待验。未改变对检索质量或产品安装的结论。

**接续已验证：Mnemon 公共组合契约（非产品安装）。** `python -B tools/verify_mnemon_memory_contract.py` 在 Node 24.19.0、Mnemon 0.5.29 与真实 Cordis 4.0.4 下通过10项检查。工具复用现有 EmbeddedMemory 合成库，通过 Python 仓储读写；仅挂一个只读 Source/策略，不加载 starter 或外部 provider。公开入口依发布 manifest 解析，Node module hooks 仅定位现存真实依赖，不替换依赖实现，不改上游文件。

证据：`.sumika-next/mnemon-contract-ba037abdd1ce4d64a986eb12208e0c4a/report.json`。覆盖中文精确召回、user/role/project隔离、未确认提议不召回、未知scope无正文/路由、未授予路由拒绝、纠正后旧回合不可读旧文、新回合仅新规范值、遗忘后重建不复活、释放回合拒绝、卸载Source清理。零模型调用、未改日用profile。

失败及修正：初次fixture在策略请求projection时未声明 `project` 能力，被上游校验正确拒绝；补齐公开能力声明后通过。正式适配不能跳过这一校验。

限制：这是 Mnemon 真实组合编译/回合/路由契约试验，**不是完整DSH插件生命周期、UI接入或新检索引擎质量验收**；中文检索仍是现FTS。fixture用进程内Source revision展示失效机制，生产必须绑定规范仓储持久化revision/generation，处理多进程及在途结果。不应直接把fixture复制为产品插件。下一步先补生产持久化失效契约，再评估只读Source的正式隔离宿主接入；native CLI/其他引擎仍须独立治理与中文质量对照。

1. 依 `long-term-memory-plan.md` 先冻结中立素材/事实/provider 契约，确认 user/role/project/session scope。
2. Mnemon、Engram、现 semantic 各自全新合成库；只挂指定 Source；关闭自动提取、模型改画像、外发和未许可 fallback。
3. 运行相同中文14项基线及更新/矛盾/来源/拒绝事实/跨角色读取/删除后不召回/重建/迁移回滚集；原先13/14仅代表现语义召回，不能替代治理集。
4. 注入故障：provider 不可用、索引丢失、重复事件、撤销权限、半程删除、提取输出越界。不得用旧结果掩盖失败。
5. 仅当检索、治理、成本均达标才替换索引 provider；原素材及规范事实不搬所有权。对照差异要人工可查。

### M05：其余缺口

语音：固定同一音频/噪声/中文夹具，测首字、尾字、TTFT、RTF、取消后不播放；本地单 provider 断网不回云。备份：先做全组件清单和 SQLite 一致性恢复，不仅检查 ZIP 存在。诊断：只读优先，任何修复先生成可审查 diff。Office：先原生技能与现 sumika-office 对照，保留成熟渲染工具，禁止一次移除全部依赖。

## 9. 回退与后续维护

每个 provider 保留旧实现与独立开关；切换只改适配配置，先影子比对、不双写 confirmed。数据迁移使用复制后的库，源库保持可恢复。回退必须恢复配置、停候选进程、验证日用和取消状态；UNKNOWN 的发送/动作不因换回 provider 自动重放。

“插件会更新”是维护收益来源，也带来契约变化。锁定已验版本，更新时核 peer/engine、工具 schema、默认外发、存储格式和 UI 插槽，再跑该模块验收；不自动追 latest。Sumika 继续维护小型契约测试和独立数据层，上游维护执行引擎与宿主接线。

## 10. 本轮实际完成与限制

完成两市场目录快照、28重点第三方元数据/26包源码快照、官方与记忆组件定向审阅、28候选×3版本静态门禁矩阵、Windows MCP 无动作握手、PDF 合成后端验证及两市场新 schema 拒绝验证。

未完成：活动桌面版本绑定、候选完整 DSH 安装生命周期、真实窗口操作、PDF 真实解析/前端、记忆候选中文与删除传播实测、语音质量、备份全组件恢复、Partner/Univer 完整源审。以上均是后续实施验收，不包装成本轮已替换或可直接上线。

笔记本增强为并行独立任务，实时证据见 `edge-inference-optimization-20261017.md`；其优化结果不等于上述插件已接线。
> 最新接续：Mnemon已增加真实角色settings绑定的可选只读原生wrapper，并通过6项桥测试（含7项真实Node/SDK检查）及5项独立DSH宿主生命周期检查。宿主不再使用固定scope夹具。证据 `.sumika-next/mnemon-host-4dbfb35be0b34ba893ec446f941aac1c/report.json`；无日用部署或新检索质量结论。详见 `acceptance-20261017-memory.md` 最新接续及 `extensions/memory/README.md`。



## 接续：官方 Office 技能与随包依赖（r6）

2026-10-17 实时复核 npm 完整发布时间，最新仍为 `0.2.1-rc.2`，`next` 同版；`latest` 仍旧版。证据 `.sumika-next/acceptance-20261017/dsh-registry-final.json`。不追旧标签降级，不修改上游。

现成资产：直接使用官方 `dsh-skill-office` 和 `dsh-tool-workspace-dependencies`；改造已有 `ui/workbench.py` 的公开 profile 注册，以及已有 `extensions/office/requirements.lock` 的独立依赖载荷。没有新增界面入口。新载荷由 `tools/prepare_office_payload.py` 从既有 standalone Python 和哈希锁 wheel 构建，不依赖开发机 venv，不更改 PATH；构建可指定 `--office-runtime`。

内部候选 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r6` 库存 58139 文件通过。536 文件源码比对仅 `tools/verify_phase5_office.py` 在构建后增加验收模式；产品源码一致。源码全量 1326 项 /126.857 秒 OK、23 跳过；定向 42 项通过，既有警告保留。

真实 r6 原生宿主自动注册两个插件、7 个官方渐进式技能、`load_workspace_dependencies` 返回包内 Python、该 Python 经原生终端完成 DOCX/XLSX/PPTX/PDF 读建改重开均通过。证据 `.sumika-next/p5-office-2d26d5685e274eebac59fbcc3087fba1/report.json`；12 次 loopback 合成模型调用、0 外部调用，受管 DSH 已关闭。复现：设置 `SUMIKA_TEST_CANDIDATE` 后运行 `python -X utf8 -B tools/verify_phase5_office.py --native-office-workflow --repair-fixture-acl`，ACL 仅针对本次生成的工作目录。

边界：官方 LibreOfficeKit 引擎仍禁用（`cli:false`），不能把宿主 soffice 渲染验证算给它；当前载荷是已有五类库及锁定依赖，不含官方工具通用描述中的所有库（例如 numpy/pandas）。旧 `sumika-office` 开关只管旧 runner，不能撤销原生终端或官方技能。readiness 是存在性预检，局部 bridge 库遮住完整旧 office-env 的边界仍待处理。未部署/发布，未做干净机器验收，r5 的其他功能证据不自动继承到 r6。
