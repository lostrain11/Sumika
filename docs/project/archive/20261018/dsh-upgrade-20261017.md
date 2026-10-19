## 当前结果：r14 定时执行与归属查询修复已验（2026-10-18）

内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r14`，DSH固定0.2.1-rc.2。已批准的原定时任务弹窗现可选择项目/主会话并确认创建原生执行任务；DSH拥有时钟、投递、任务列表和管理页。原本地提醒、旧定义与历史保留，不自动迁移。请求ID创建前落盘，重复/重启不重建；原生已保存但浏览器丢响应时显示未确认并锁定本次表单，需去原生页核对。到期投递与模型完成分开，不以回执宣称任务成功。

真实实测连续遇到旧PowerShell端口查询15秒超时，现改用Windows GetExtendedTcpTable同时检查IPv4/IPv6监听PID；每次仍核受管进程存活及唯一PID，查询失败拒绝，不缓存授权。33项相关测试与真实套接字通过；最终全量 **1359项/203.605秒OK，23跳过**，既有资源/弃用警告保留。此前1359项的9个错误全是旧subprocess查询夹具，已改用新接口并保留外部/多PID/空集合/查询错误拒绝断言；失败日志保留，不掩盖为最终通过。

包内Python/真实DSH6组+真实Bridge/Edge4组通过：三规则、无模型创建、重复/重启、伪造目标拒绝、到期回原会话、取消零创建、创建后断线unknown不重试、既有原生管理页跳转。每轮仅到期1次loopback模型、0外部/页面错误；最终截图已目视。r14原提醒/旧执行UI7项、记忆策略5项、治理17项、行为/模式27项、角色资源4项、EXE4项、布局128/128通过。治理使用合成数据，记忆策略5次loopback调用，行为有API夹具，不能统称真实设备/模型质量端到端。

550个产品源码/引用文件SHA一致、60481文件最终库存通过。原构建manifest保留；原生归属修复与维护脚本同步分别记录前后SHA，未改上游或日用安装。实际设备、真实内容/模型质量、干净机器以及原需求逐项整体验收仍未完成，主线总体继续。

证据：`.sumika-next/acceptance-20261018/{full-suite-native-owner-final.log,full-suite-native-owner-final2.log,native-schedule-node-contracts-final.log}`；候选父目录 `schedule-integration-r14-visual2/32949a6d6e674f0bb1998a1a00407d80/{report,browser-report}.json`、`{memory-policy-r14,memory-governance-r14,behavior-profiles-r14,role-resources-r14,matrix-r14}/report.json`、`exe-startup-36dcacbc508645ceaaa5e061b9b19e93/report.json`、`source-identity-rc2-r14.json`、`inventory-r14-final.json`。下面旧构建/进行中描述保留历史范围，不能当作本次未完成施工指令。

## 当前结果：r13角色资源编辑已验（2026-10-18）

内部候选：E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r13，DSH仍为最新已核实0.2.1-rc.2；未部署/发布/替换日用。已批准的背景设定、世界书条目与角色主色/浅色已接入原角色资源弹窗，能力卡进入同一弹窗。完整卡上下文实际消费编辑并保留原预算、关键词和高级触发字段；原卡不改写，内置只读，保存先备份，旧revision与无效输入拒绝。下一条回复重新读取角色设定；角色配色清空恢复原默认。

验证：源码1354项/301.614秒OK（23跳过，既有警告保留）；20项管理契约、7项网页咨询Node测试通过。最终包内Python/Bridge及包内维护脚本的真实Edge四组通过，0页面错误/0外部模型调用，角色发现使用合成列表。EXE4项、布局128/128（0横溢出/页面错误）、546源码SHA一致、60477库存校验通过。包内截图已目视检查，长文本整行可编辑。仅维护验收脚本在构建后同步，原manifest及前后SHA保留，未追加产品代码修改。

证据：项目.sumika-next/acceptance-20261018/{full-suite-role-editor.log,role-editor-contract.log,role-editor-node-review.log}；候选父目录{role-resources-r13-final/report.json,matrix-r13/report.json,exe-startup-a8051cfe4e544c168510b5586fc81a4b/report.json,source-identity-rc2-r13.json,inventory-r13-final.json}。上一轮r12最终1352项仍是1个语音夹具清理错误，旧1351通过不能覆盖它；本轮调整真实pipe夹具的cwd为稳定产品根后全量通过，不声称已证明Windows锁延迟根因，也未削弱进程/Job回收断言。

当前完成的是角色资源编辑这一主线项；定时任务旧执行入口与DSH原生整合、其他原需求逐项整体验收仍待做。实际角色模型质量、交互设备和干净机器未验，不因合成模型/隐藏浏览器通过而判定完成。下文为历史检查点，当前结果以本节为准。

## 2026-10-18 角色资源编辑接续（源码实现，候选验收进行中）

已确认并实施：在原“管理角色资源”弹窗补齐背景设定、世界书条目及角色主色/浅色；能力页“角色卡 · 世界书”进入同一编辑器，没有新增主导航。资产复用：ui/app/management.js原弹窗、roles.py原ZIP备份/校验和、card_context.py原选择器、prototype-d原能力卡和角色呈现变量，均采用改造/直接使用。原角色卡与高级字段保留；编辑写到manifest context_edits，完整卡模式在预算/关键词选择前应用，下一条回复重新读角色；普通模式同样消费编辑。内置只读、旧revision拒绝、无效输入在备份前拒绝，编辑不写长期记忆。

源码20项管理契约测试通过；真实Edge/隔离Bridge四组通过，0页面错误/0外部模型调用，发现列表为合成夹具。检查背景/条目HTTP保存、备份、输入拒绝、角色主色生效、清空恢复默认、能力卡重开同一弹窗及另一角色隔离。维护脚本前两轮失败为多点一次已关闭弹窗和使用不存在的#cap路由，已改用真实#shelf，不改产品适配错误夹具。证据：.sumika-next/acceptance-20261018/role-resources-ui-r3/report.json，截图已目视检查；随后仅将长文本改整行宽度，并清理保存成功后的旧错误提示，待新候选重验。

纠正上一轮测试状态：r12最终installer修改后的全量1352项/202.684秒，1项语音夹具TemporaryDirectory清理WinError32、23跳过，不能称最终全量通过。原1351项通过仍只覆盖修改前。语音真实pipe夹具现改为产品实际使用的稳定根目录作为cwd，临时模型目录与进程退出、Job关闭断言保留；该调整避免把临时cwd立即删除作为产品门槛，不声称已证明操作系统锁延迟根因。新全量正在执行。r13内部候选构建/包内验证待完成，未部署。定时原生整合及其他整体验收仍待做，整体未完成。

# DSH 0.2.1-rc.2 升级验收

## r12 网页咨询接线修复已入包（2026-10-18）

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r12`，DSH仍固定0.2.1-rc.2。Bridge/Workbench现在自动登记既有网页咨询插件并绑定真实个人授权文件；新profile仅允许原生项目登记表中确属项目的standard主会话，已有显式禁用/preset/项目白名单保留。用户总开关在发送/读取外站前实时核对，逐站授权与原生逐次发送审批仍独立生效。包内Python通过已有run_module.py进入实际产品模块，不依赖开发机PYTHONPATH。

源码21项Python/7项Node定向通过；r12包内Python+包内产品代码启动真实受管Workbench，5组检查通过：新profile自动登记/路径、关闭拒绝、审批拒绝、取消、允许一次但无站点授权时停止。7次loopback合成模型请求，0外站消息；审批服务使用合成应答器，不冒称真实网页按钮点击，实际模型质量/站点发送不由此证明。源码全量1351项、202.376秒、OK（23跳过，既有资源/弃用警告仍在）。首轮1351项有2项语音夹具目录WinError32、1项profile原子替换WinError5；3项单独复跑通过，构建完成后新E临时目录全套通过。保留两轮与定向日志；具体占用来源未定，不声称已修根因，未修改相关产品/测试来压错误。

候选60476文件库存通过，545个产品源码/登记文件SHA零差异；实际EXE4项及布局128/128通过，0横向溢出/页面错误，测试Bridge均已停止。构建复用r11经校验的同版物理DSH/依赖；源码pnpm链接的首次构建拒绝日志保留。仅文档和验收脚本import guard在构建后同步，原manifest和前后SHA保留，产品/runtime未改。候选未替换日用安装或发布。

证据：`.sumika-next/acceptance-20261018/{full-suite-review-registration.log,review-registration-sharing-focused.log,full-suite-review-registration-clean.log}`；候选父目录`{build-rc2-r12-physical.log,inventory-r12-final.json,source-identity-rc2-r12.json,matrix-r12/report.json,exe-startup-3676b3d91cbc4d7d80637e7a5c849b66/report.json,managed-review-r12/7604bc367eb340fc852949a541245c5a/report.json}`。

**操作：**「设置 → 连接与权限 → 网页咨询授权 → 启用网页咨询」，按既有控件授权站点并绑定受管页面；随后在「工作台」的已登记项目主会话提出网页交叉审查，核对原生审批中的完整发送文本。新profile首次开工作台自动登记插件，已有实例升级后需在无执行/待审批任务时正常停止并重开；关闭总开关立即阻止新的网页操作，无需重启，不承诺已发给外站的生成会被终止。原生插件被用户显式禁用时保持禁用。无需手改profile；不自动登录、绑定、发送或消耗既有授权。

用户已批准在同一个角色资源弹窗补齐背景/世界书/角色配色，代码尚待接续。定时任务旧执行入口与原生任务的整合仍待做，角色/设备/实际模型/干净机器等全项目剩余项继续核验；本轮通过不等于整体完成。下文“源码已验、r12待验”保留为本次构建过程记录，以本节结果为准。


## 网页咨询新profile接线修复（2026-10-18，源码已验、r12待验）

复用现有 `review_install.py` 原子备份安装器、`review_dsh.mjs` 原生审批工具、BrowserSkill个人授权和 `tools/run_module.py`，没有新UI或平行插件。Bridge将真实个人授权文件路径传给Workbench，在持有inactive profile lease时安装；首次安装只开放DSH原生项目登记表中确属该项目的standard主会话，动态读取会话归属，不将任意cwd视为项目授权。旧profile明确配置的禁用状态、工作preset及项目范围保留，仅刷新迁移后的产品/解释器/registry/runner路径。总开关缺失、损坏或关闭时发送/collect在审批前拒绝；状态查询/本地取消保留，逐站授权和每次原生发送审批仍需满足。包内隔离Python改走已有module runner，避免`-m`找不到产品模块。

源码21项Python与7项Node定向通过；真实受管Workbench5组检查通过（新profile自动登记与路径、关闭拒绝、审批拒绝、取消、允许一次但没有站点授权时明确拒绝）。7次本机合成模型请求，未设置任何站点授权，0外站发送。审批使用原生服务+合成应答器，不冒称用户点击；允许分支真实启动产品worker并返回无站点授权错误，未创建提交journal。证据：`.sumika-next/acceptance-20261018/managed-review/939c19d35fd243918d4e659da0fae6f2/{report,events}.json`。复现：`python -B tools/verify_web_review_managed.py`；`--product`可指定新候选，必须用该候选Python/module runner调用以验包内隔离解释器。

全量回归与r12独立构建正在进行，不将源码通过写成r11已包含修复。第一次构建因源码pnpm依赖含链接被已有构建检查拒绝（尚未生成目标目录）；改复用版本和release SHA一致的r11物理DSH运行时，未降低构建检查。已获准在现有角色资源弹窗补齐世界书/背景/主题色，后续接续实施；主线仍未完成。


## 原生自动化任务实测与剩余接线（2026-10-18）

r11 内置 DSH 0.2.1-rc.2 已有原生定时服务、四个 schedule 工具和「自动化任务」页面。实际 Web profile 已挂载，不能沿用工具包旧注释的“默认关闭”判断。优先复用该执行引擎，不再扩建另一套 Agent 调度器。现有 Sumika 本地提醒不会激活模型，语义不同，不能静默迁移或把原本 blocked 的执行定义自动启用。

包内模块/DSH/皮肤、隔离 profile、合成任务与真实 Edge 通过8组检查：一次性/每日/每周创建、Asia/Shanghai 时区、现有自动化任务入口及列表、API编辑与旧版本冲突拒绝、跨会话删除拒绝、管理不激活模型、重启保留任务、到期回原会话、完成后重启观察无重放。总计5次本机合成模型请求、0外部请求。截图已目视检查。编辑和删除是API验收，不冒称界面点击通过；浏览器本轮只验证原生入口/列表。证据：`.sumika-next/acceptance-20261018/native-schedule/4b3c1b45b23b4247a58b28860020a596/{report,browser-report,evidence}.json`、`native-schedule-manager.png`。复现：`python -B tools/verify_native_schedule.py --product E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r11 --browser`。先前两轮失败为维护脚本的无参catalog与session/page游标格式错误，失败报告保留，未修改上游或产品来适配。

**使用入口：**「工作台」启动受管DSH → 左侧「自动化任务」查看原生任务；「新建」进入原生会话，在会话中明确任务内容、时间、时区并要求创建。创建行为取决于当前工作模型调用原生工具；合成模型证明工具/投递链路，不证明任意实际模型理解准确。当前 Sumika「能力 → 定时任务」弹窗的执行选项仍需绑定，不能宣称这一旧入口已可执行。下一步须整合已有入口与原会话绑定，不新增平行任务列表，不自动迁移旧定义。原生投递回执默认保留30天/200条，与行为素材长期保存无关，不承诺永久任务审计。

网页咨询另有交付缺口：`review_dsh.mjs`及worker虽已入包，`ui/workbench.py`的新profile安装流程没有登记该插件；源码和候选默认profile当前均未创建。历史日用手工登记的成功只证明当时profile，不能扩张为全新安装可用。后续补便携登记、真实个人registry路径、工作区/preset白名单与开关接线后，须用隔离无外发验收；既有真实网站发送授权已耗尽，不重发。

本轮只增加维护工具与记录，产品和r11构建不变，无需重打包。主线整体未完成，世界书/主题新增控件仍等待此前问题的答复。


## 最新版本再次复核（2026-10-18，本轮）

官方 npm 完整版本列表与发布通道再次核对：最新已发布版本为 `0.2.1-rc.2`，`next` 同版；`latest` 仍指向旧版 `0.2.0-rc.2`。源码运行时与 r11 内部候选各 4 项发行文件 SHA 全部一致，直接复用既有锁文件、运行时与候选，不重复安装、不修改上游。证据：`.sumika-next/acceptance-20261018/dsh-latest-recheck.json`。GitHub release API 本轮限流403，README原始链接404，不用这些失败请求推断发布状态。未替换日用安装；赠金资格仍须由官方账户登录后的活动提示确认，未核验到账。主线整体验收仍进行中。


## 2026-10-18 最新发布与现场完整性复核

实时查询官方 npm 的完整版本、发布时间和 dist-tags，最新发布仍是 `0.2.1-rc.2`，`next` 同版；`latest=0.2.0-rc.2`、`alpha=0.2.1-alpha.5` 均较旧。现有精确版本依赖保持不变，不按旧标签降级。日用源码 runtime 的 package、锁文件、上游包元数据与入口共4项 SHA 均与 release.json 一致，无需重复安装。证据：`.sumika-next/acceptance-20261018/dsh-latest-check.json`。

现有原生filesystem Skill、OCR模块服务、网页咨询工具和诊断投影继续改造复用，不新增平行插件或修改上游。新版工具结果的 `message.toolCallId/isError` 需要在独立诊断适配层处理；本轮保留旧格式兼容、冲突ID不关联，并验证拒绝/取消前worker不执行。详情随后附本轮候选证据。赠金资格仍需官方账户活动页确认，安装DSH不自动取得资格；本轮未登录、领取或付费。

## 当前候选 r10：桌面动作预检与未知结果修复（2026-10-18）

路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r10`；DSH固定`0.2.1-rc.2`。既有`desktop/act`服务现接入授权动作编排器，完整传递文本、按键、控件定位与快照；无效请求在动作前拒绝。原生变更尝试或动作后检查失败返回`unknown`并禁止自动重试。静态图片OCR即使匹配，也不冒充动作后的新状态；可信宿主新图回调仍需另行采集授权，未新增UI或自动截屏。

源码定向16项、全量1345项（262.983秒，23跳过）通过，仍有既有资源/弃用警告。包内解释器与包内维护工具通过7项真实隐藏窗口服务检查：禁用/未批准/缺少验证参数/快照过期零改动、正常文本输入、静态OCR匹配不证明新状态、动作后OCR失败保留已执行未知。测试初版缺少禁止激活窗口样式导致前台断言失败，已加NOACTIVATE及隐藏解释器启动；失败报告保留，最终前台不变、worker退出。工具改动已同步候选，原manifest及前后SHA保留，最终库存60470文件、540个源码/登记文件SHA一致。EXE4项及布局128/128通过，无页面错误/横溢出。

证据：`.sumika-next/acceptance-20261018/owned-uia-r10-final/bee6fa3b843e417cbb055d38f55e50c2/report.json`、项目`.sumika-next/acceptance-20261018/full-suite-desktop.log`、候选父目录`{inventory-r10-final.json,source-identity-rc2-r10.json,matrix-r10/report.json,exe-startup-fdf605b6b07948f3b4de5e428c96073a/report.json}`。本轮不采用户画面、不向用户应用输入、不调用外部模型；未部署发布。其他旧候选深度功能证据保留原版本，不自动视作r10已全部复验。整体目标仍进行中。


## 当前候选 r9：文件OCR与实现切换补齐（2026-10-18）

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r9`，DSH仍为最新发布的`0.2.1-rc.2`。复用伴学WinRT识别器补齐通用文件Windows OCR，修复RapidOCR隔离环境误判、旧包导入/返回格式、RapidOCR-json数组解析和同能力多实现启动覆盖问题，无新增UI。

源码33项定向与全量1336项（304.704秒，23跳过）通过；首次C盘临时目录低于1GiB导致76容量保护错误，换E盘临时目录后通过，保留首次日志且不降低保护阈值。包内真实中英文文件OCR、像素坐标、禁用/未安装语言/400万像素上限拒绝通过；「能力 → 管理模块 → ocr → 实现 → 应用实现」真实Bridge保存/刷新通过、无页面错误。切换实现不会开启禁用模块，同实现保留选项、不同实现使用自身选项。需启用能力时仍用已有OCR卡片开关。

r9最终库存60470文件、540个产品源码/登记文件SHA一致，EXE首次/复用/外来端口拒绝/认证关停4项和布局128/128通过。构建时OCR说明文档推进，已单独同步并记录前后SHA，原manifest保留，最终全库存复验通过；产品代码与运行时未二次修改。候选依赖、旧审批/提问/行为/Office深度测试保留原版本证据归属，不自动算作r9逐项重测。

证据：项目`.sumika-next/acceptance-20261018/{full-suite-e-temp.log,ocr-provider-ui-r9/report.json,windows-file-ocr-r9/0488aac752b74668858d0fc94f2e7fcd/report.json}`；候选父目录`{inventory-r9-final.json,source-identity-rc2-r9.json,matrix-r9/report.json,exe-startup-45187dac9a1942b2bc29ff78d9fc784e/report.json}`。浏览器截图已检查，测试Bridge已停止。未采集用户设备、未调用外部模型、未部署发布；整体任务仍进行中。


## 最新发布复核（2026-10-18）

实时查询官方 npm 完整发布时间，最新仍为 `0.2.1-rc.2`；`next` 同版，`latest` 仍为较旧的 `0.2.0-rc.2`。实际安装版本已匹配，release manifest 四项 SHA 全部一致，因此直接复用已升级运行时，没有重复安装或修改上游。证据：`.sumika-next/acceptance-20261017/dsh-registry-recheck.json`（UTC时间对应北京时间10月18日）。

再次运行 `python -X utf8 -B tools/probe_dsh_next.py`，原生 Web/脚本资源、受管实例身份、未认证与跨域拒绝、会话创建/历史读取/空闲取消通过，退出码0、模型调用0。此次为运行时定向复核，不替代此前完整兼容性证据，也不代表当前所有未提交功能已经验收；r8仍为内部候选，未部署或发布。

官方 API 文档确认 `deepseek-flash` 当前由 DeepSeek-V4.1-Flash-1017 提供服务。Sumika使用DSH不自动产生赠金资格；是否能领取6元、有效期和剩余额度须以官方登录后的账号活动提示为准，本次未登录账号、未领取、未确认到账。本地默认模型保持既有配置。


## 当前补验：r8 官方办公引擎与运行时探测（2026-10-17）

当前内部候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r8`，DSH仍固定最新发布的0.2.1-rc.2。复用官方Office技能、workspace-dependencies工具、LibreOfficeKit0.1.5及其已随包提供的Windows引擎；只改公开profile接线和独立依赖层，不改上游或新增UI。

已修复：局部bridge库遮蔽完整Office环境；桌面/摄像头就绪探测忽略选定运行时；依赖载荷继承旧dist-info造成版本歧义。当前载荷从干净site-packages安装17项SHA锁定依赖，包含NumPy2.5.3/Pandas3.0.6/tzdata2026.5，无重复元数据。`prepare_office_payload.py`不再携入基础bridge的第三方包。

验证：源码1329项/129.549秒OK，23跳过，既有警告保留；最终定向19项通过。r8库存60468文件；537文件比对仅外部维护工具`verify_capability_package.py`在构建后推进，产品源码一致。包内Bridge/desktop/voice/Office导入、中文OCR创建、VAD加载、process-audio能力探测通过，未开启采集或播放；实际EXE首启/复用/外部端口拒绝/认证退出4项与128格布局通过，无横溢出/pageerror。

r8真实DSH自动注册7技能和依赖工具，技能包含包内Node/CLI路径；四类文件读建改重开、原生终端导出PDF和重算7通过（14次loopback夹具调用、0外部调用），证据`.sumika-next/p5-office-ca98a52081bf4388b365e9a9e53848ec/report.json`。官方引擎另测三格式各2页PDF、跨表公式90/105/超预算及公式保留、2张DOCX预览、损坏输入拒绝、源SHA不变；两张PNG与人工审阅版本SHA一致，证据`.sumika-next/acceptance-20261017/official-kit-r8/681024087a834a1eb78ee662ec6e0c6d/report.json`。此前r6“官方引擎禁用”和“numpy/pandas未提供”属于历史快照，r8已补齐；r7曾继承旧tzdata元数据，不作为最终候选。

复现：设置`SUMIKA_TEST_CANDIDATE`为r8，运行`python -X utf8 -B tools/verify_phase5_office.py --native-office-workflow --native-office-engines --repair-fixture-acl`；依赖无设备检查使用`python -X utf8 -B -m tools.verify_capability_package <candidate> --require-office --require-process-audio --output <新报告路径>`。ACL只处理生成的测试工作区。

边界：引擎报告Courier字体替换；依赖Windows VC++v14运行时，尚未在干净机器验证。旧sumika-office开关只控制自身runner，不能关闭官方技能或撤销终端权限。自然语言自主任务质量、任意文件无损、真实设备/站点和整体验收未完成；未部署/发布，整体目标保持进行中。

## 以下为此前阶段记录


## 原生审批与提问包内补验（2026-10-17）

复用并改造既有`tools/verify_native_approval_ui.py/.mjs`：支持`SUMIKA_TEST_CANDIDATE`及`--approvals-only`/`--questions-only`，使用r5自带Python、Bridge和DSH；仅审批执行worker是隔离目录的host-Python sentinel，不连接实际外站。旧helper修改sys.path曾使一轮混用源码，已恢复候选优先且断言Bridge模块路径；旧嵌套工具结果判断改为兼容rc.2标准message-level isError/text。失败过程留在日志，不计为产品通过。

r5真实原生审批拒绝/取消/允许一次三分支通过：审批前不执行，拒绝/取消零执行，允许一次只执行一条本地动作；等待审批→空闲、切页保留、取消刷新不重现均通过。证据`.sumika-next/native-approval-ui-3341aaf9ceb44c7998c012823f2518cd/report.json`。原生提问选项/自定义/取消三分支通过，答案id/原文及取消错误由真实tool/result核对；等待回答→空闲、刷新无待答重放。证据`.sumika-next/native-approval-ui-0fb81bdc99904a83a40ed3ffc14c0ead/report.json`。

每轮5次本机合成模型调用，0外部调用；最终逐分支浏览器无pageerror，受管DSH均停止，审批与提问截图已查看。部分浏览器刷新产生ConnectionAbortedError日志，不宣称零警告。未验实际网站发送/完整附件链路；r5产品未改，工作区两份维护脚本已超过包内构建快照。本次无新增控件/导航，不重建候选来同步纯维护脚本。功能手测指南已把当前r5入口和操作表前置，历史证据移入附录。


## 当前候选 r5：DSH最新版本及接续修复已入包

截至2026-10-17再次查询官方npm，最新发布仍是 **0.2.1-rc.2**（北京时间16:36:31发布）；`next`指向该版，`latest`仍为旧0.2.0-rc.2。日用源码运行时与新候选均精确固定rc.2，关键文件/锁文件SHA一致，无上游修改。

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r5`，已纳入任务交接接收与行为询问刷新重放修复。534个产品源码/引用文件SHA一致，55456文件库存通过；源码全量1323项通过/23跳过（121.396秒，有既有资源/弃用警告）。包内行为询问6项、真实原生交接7项、实际EXE生命周期4项、布局128格均通过，0页面错误/横向溢出；两项业务链路各1次本机合成模型调用、0外部调用。询问刷新与交接截图已查看；隔离测试Bridge及DSH已停止。

证据：候选父目录`build-rc2-r5.log`、`source-identity-rc2-r5.json`、`behavior-prompt-r5/report.json`、`exe-startup-0827a0a229b642f7a142e9c8d03614b2/report.json`、`matrix-r5/report.json`；原生交接`.sumika-next/acceptance-20261017/task-handoff-87a1e485112e40f290533d09259b3be3/{report,handoff-browser}.json`。

r4保留，以下r4/源码待入包等说明均为历史快照，以本节的r5边界为准。未部署/发布，未开启日用采集或调用付费模型；真实设备、模型质量、干净机器及其余主线仍待验，**整体未完成**。赠金需官方登录后核验资格，不能由升级推断。


## 最新版本复核与接续构建

2026-10-17 再查官方 `npm view @deepseek-ai/dsh dist-tags --json` 与 `time --json`：最新发布仍为 `0.2.1-rc.2`（08:36:31 UTC / 16:36:31 北京时间），`next` 指向该版，`latest` 仍为较旧 `0.2.0-rc.2`。继续精确固定新版RC，日用 runtime release manifest 的四项SHA逐项一致。不修改上游源码或 node_modules。

后续Sumika任务交接接收及行为询问重放修复已通过源码全量1323项（23跳过，121.396秒）。为纳入这些独立适配修复，正在新建 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r5`，旧r4保留。包内复验完成前不继承r4全部验收结论，未部署日用安装或发布。赠金仍取决于官方账号活动资格，未代登录或确认到账。

## 当前 r4 包内复验（2026-10-17）

当前内部候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r4`，固定 DSH `0.2.1-rc.2`。本次再次查询 npm 发布时间与标签，没有更晚发布版本；`latest` 仍较旧，不据此降级。复用现有运行时、工作台组件与验收脚本，无新增 UI，无上游源码修改。

r4 已包含等待状态 hook 与父页面端口修复。包内真实原生工作台通过非空会话、角色导入、执行→取消→空闲、原生计划审阅→取消→空闲，以及随机父端口64872下合成任务草稿显示/路由通信；`source_skin=false`，3次本机夹具模型调用，0外部调用，DSH已停止。截图已查看。证据：`E:/SumikaBuild/acceptance-20261017-current/native-ui-r3-8f181fd9dcf847bda2e51247fe3972ee/report.json`（目录名r3为编排历史名称，报告candidate明确为r4）。

包内两个组件契约通过；实际 EXE 四项生命周期检查通过（`exe-startup-26dc2d4a62de450c88c2a368215781a1/report.json`）；r4布局128/128、溢出与pageerror均0（`matrix-r4/report.json`）。528个产品源码/引用登记文件SHA一致、55450文件库存通过（`source-identity-rc2-r4.json`）。构建后只同步两份Sumika自有文件，manifest登记前后SHA，原manifest保留为`r4-build-original-manifest.json`；DSH/runtime未改。

上述证据均在当前候选父目录。真实来源消息接收/加入/发送完整链路、权限审批/提问真实等待流程、真实设备/模型质量和干净机器尚未全部验收；合成草稿仅验显示，不发送。r4未替换日用安装或发布。后文r3及更早证据保留其历史范围。

最新发现并修复：0.2会话头等待状态hook变更，Sumika旧适配遗漏计划审阅药丸。源码现在读公开`useSessionStatus(...).pendingInteraction`，旧hook仅用于回退兼容。真实宿主加载修复源码后执行中/取消/空闲及计划审阅/取消/空闲通过，证据`native-ui-r3-2d8201d378664ef6b0822c9818c998ae`（source_skin=true，混合验证，r3包尚不含修复）；组件新旧hook契约通过。见设计覆盖表顶部。下一候选须纳入后复验，不把此结果写成r3已修复。

## r3布局、角色导入与非空原生会话接续

`matrix-r3/report.json`：r3包内Python真实隔离Bridge，四主屏128/128（8尺寸×2等效缩放×2主题×4屏），0横向溢出/0pageerror。工具现显式隔离调度目录并正常关闭Bridge；这是布局检查，不替代全功能测试。

`native-ui-r3-093cefeca4114c8a81239e210efc3f15/report.json`：r3包内Python/Node及DSH0.2.1-rc.2真实启动，注册独立项目、创建原生会话、本机模型夹具完成1回合；0外部模型调用。浏览器真实角色完整/仅卡导入及清理通过（VRM为占位夹具，不证明渲染）；工作台皮肤、品牌、侧栏/收缩轨、非空会话状态组件`idle`和`项目 · …`面包屑通过，页面/控制台错误0，已看`workbench.png`，测试DSH确认停止。以上文件均在当前候选父目录。

验收脚本原先以旧CSS哈希查会话，空白页也能通过外观检查；现`verify_workbench_ui.mjs`可用`SUMIKA_VERIFY_SESSION_TEXT`指定可见项目名、`SUMIKA_VERIFY_SESSION_PREVIEW`指定会话预览，要求真实挂载状态标记。项目默认展开，只有会话不可见才展开，避免误折叠。早期本轮失败报告保留，最终结果不抹去排查过程。运行中/等待审批状态尚未在此浏览器运行验证，不能把idle扩大为全状态验收。

本次改动仅维护验收脚本，不修改r3产品。r3原526文件SHA证据为构建时状态；当前维护脚本已超出该快照，需区分外部验收工具与包内产品。复用编排保存在工作区`.sumika-next/acceptance-20261017/verify_r3_native.py`，仅限隔离回归，不作为产品交付入口。

当前内部候选已推进到`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r3`，r2及更早候选保留。DSH版本仍为0.2.1-rc.2；r3包含最新语义向量边界和维护验收脚本修复。55448文件库存通过；526个产品源码/引用登记文件SHA零差异。包内Python记忆边界30项、真实隔离Bridge/SQLite浏览器记忆/用量9项、行为/模式27项（含明确标注的API夹具）、定时任务7项均通过；页面错误0。实际EXE首次/复用/外部HTTP200端口拒绝/认证关停并退出4项通过，测试Bridge已停。源码全量1319项OK/23跳过。证据位于候选父目录`build-rc2-r3.log`、`source-identity-rc2-r3.json`、`semantic-vector-tests-r3.log`、`memory-ui-r3/report.json`、`behavior-ui-r3/report.json`、`schedule-ui-r3/report.json`、`exe-startup-1919234f98414080b299b32c0cdb54ec/report.json`。这些检查仅证明列出的范围；完整功能、真实设备与干净机器门槛仍待完成，未发布或部署日用。

补验：Mnemon 0.5.29只读复用适配在当前DSH 0.2.1-rc.2的真实隔离宿主10项通过（规范事实召回、关闭/撤销/取消及插件禁用重启）；`.sumika-next/mnemon-host-b46f292675154b30b286cbe375b80a90/report.json`。6次本机模型夹具调用、0外部模型请求，未启用日用Mnemon。工具不再写死0.2.0，详见记忆验收文档顶部。

## 结论

项目日用 DSH 已从 `@deepseek-ai/dsh@0.1.5-rc.2` 升级到固定版本 `0.2.1-rc.2`。旧运行时和旧 profile 仍保留，升级与回滚均使用匹配的 runtime/profile 对，不对现有 profile 原地降级。

截至 2026-10-17，npm 可见版本线为：`latest=0.2.0-rc.2`、`next=0.2.1-rc.2`、`alpha=0.2.1-alpha.5`。alpha.5 已在隔离目录完成原生探针、P2 门槛和插件生命周期复测，但它发布时间早于 rc.2，属于实验线；日用 runtime 继续固定 `0.2.1-rc.2`。

## 现成资产与处理

| 资产 | 路径 | 处理 |
|---|---|---|
| 日用 DSH runtime | `runtime/dsh` | 更新依赖、锁文件、release manifest；继续复用现有 `sumika_next.dsh.Dsh` 适配层 |
| 隔离升级候选 | `.sumika-next/dsh-upgrade/0.2.1-rc.2` | 已安装并完成基础探针、P2、插件和迁移回滚验证 |
| 旧版本 profile/runtime | 项目既有 profile 与 `0.1.5-rc.2` 安装 | 保留作为回退对，不与新 profile 交叉打开 |
| DSH 原生插件管理 | DSH 0.2.x 原生能力 | 复用生命周期接口，不修改 DSH 源码、安装包或 node_modules |

## 验证结果

- `python -X utf8 -B tools/probe_dsh_next.py --runtime runtime/dsh`：通过。原生 Web、资源、认证拒绝、跨源写拒绝、会话创建、取消、历史和空闲取消均通过，模型调用 0 次。
- `python -X utf8 -B tools/verify_phase2.py --runtime runtime/dsh --repair-fixture-acl`：通过。Python 1304 项通过、23 项跳过；P2 release gate 通过；loopback fixture，无模型质量结论。
- `tools/verify_dsh_plugin_lifecycle.py`：通过。安装、启停、重启保持、卸载恢复、不兼容拒绝、失败恢复和无关配置保留均通过，外部模型调用 0 次。
- `tools/verify_runtime_upgrade_rollback.py --migrate-fixture`：通过。18 条历史保留、回滚后内容一致、无模型重放、旧 profile 字节保留。
- `tools/verify_runtime_upgrade_rollback.py --migration-failure-fixture`：通过。迁移失败时 fail-closed，旧 runtime/profile 对可恢复，旧 profile 字节保留。

P2 期间发现并修正了验收脚本兼容性问题：0.2.x 将前台子 Agent 结果放入 `subagent-settled` 事件，旧脚本只检查 `tool/result`。`tools/verify_dsh_p2.py` 现在检查完整事件流，不改变产品行为。

## 能力与边界

0.2.1-rc.2 的 DSH 端已包含 DeepSeek-V4.1-Flash-1017 相关支持、插件同步和 Search/Fetch 相关组件；Sumika 默认本地模型 `LFM2.5-24B-A2B` 不因 DSH 升级而切换。Search/Fetch 尚未在 Sumika 业务流程中新增独立入口，仍由 DSH 原生工具和权限策略负责。

本轮没有验证真实 DeepSeek 账号赠金资格，也没有宣称首次登录必得 6 元。赠金取决于官方活动入口、账号资格和账户类型，不能从安装或升级 DSH 推断。

## 回退

出现日用兼容性问题时，停止日用 DSH，切回旧 `0.1.5-rc.2` runtime 与其匹配 profile；不得让旧版本打开 0.2.1 已迁移中的 profile。升级过程中保留的迁移失败保护和旧 profile 快照可用于恢复。

## 收尾复验（2026-10-17）

- npm 标签再次查询：`latest=0.2.0-rc.2`、`next=0.2.1-rc.2`；本次固定最新 RC，不追随标签自动更新。
- `python -X utf8 -B tools/verify_continuity_failure_dsh.py` 通过。证据 `.sumika-next/continuity-failure-0bded1d5f8a44348a66e626c8abb2a75/report.json`。损坏库两次拒绝、修复后重启仍保留未知围栏、显式 reconciliation 后才允许新任务；外部模型调用 0 次。
- 新版会在恢复 Agent 时直接通过 RPC 拒绝损坏连续性库，错误含 `Continuity outcome unknown; automatic retries disabled`。验收现在同时支持这个真实准入拒绝与旧版任务结束事件；不会仅凭通用 gateway 错误判定通过。
- `node tools/verify_workbench_ui.mjs http://127.0.0.1:18765 ...` 通过。隔离数据 `.sumika-next/dsh-upgrade/ui-acceptance`，真实新版皮肤、品牌隐藏、侧栏收放/图标及配色验证；pageerror/consoleerror 均为 0。证据 `.sumika-next/dsh-upgrade/workbench-ui.json`，截图 `page.png`、`sidebar.png`、`rail.png` 同目录，已查看页面截图。
- 新版首次启动增加预览说明和“开始使用”弹窗，验收通过原生“继续/关闭”按钮处理，不强制穿透遮罩，不改产品代码。空白隔离 profile 没有非空会话，运行中状态药丸不在这次浏览器复验范围。
- 角色插件真宿主结果 `.sumika-next/role-plugin-f567da17685f4309a639f1ec68b1d647`：自动注入、显式写入、跨会话和重启召回、禁用后不注入通过。
- 新版与 `.sumika-next/dsh-rollback/0.1.5-rc.2` 旧 runtime 的 release 文件哈希均复核一致；旧版依赖安装成功。

## alpha.5 隔离复测

- 安装目录：`.sumika-next/dsh-upgrade/0.2.1-alpha.5`。
- `python -X utf8 -B tools/probe_dsh_next.py --runtime .sumika-next/dsh-upgrade/0.2.1-alpha.5`：通过。
- `python -X utf8 -B tools/verify_dsh_p2.py --runtime .sumika-next/dsh-upgrade/0.2.1-alpha.5 --repair-fixture-acl`：通过；证据 `.sumika-next/p2-bdc646948b444130b5b237e18bf27bf7`，无模型质量结论。
- `python -X utf8 -B tools/verify_dsh_plugin_lifecycle.py --runtime .sumika-next/dsh-upgrade/0.2.1-alpha.5`：通过；证据 `.sumika-next/plugin-lifecycle-6b618f4ef0984d21a10e13c29a78bc01`，日用 profile 未改变。
- alpha.5 没有替换 `runtime/dsh`，因为它不是 `next` RC。后续只有出现新的 `next`/正式版本并完成同等迁移、回退、插件和 UI 验收时，才推进日用升级。

旧 `E:/SumikaBuild/acceptance-20261017-final/candidate` 清单仍为 0.2.0-rc.2，现已另建 RC.2 内部候选，见下文。没有进行真实账号登录、赠金领取或付费模型评测；官方账号活动资格须以登录后的实际提示为准。


## 当前候选重建复验

当前候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2`。复用现有自包含启动器、桌宠、音频及 Python/Node 运行时，重新打包当前源码和 DSH 0.2.1-rc.2；旧候选保留。

物理依赖使用独立目录的 frozen-lockfile production hoisted 安装生成，不修改上游源码。pnpm deploy 因非 workspace 未执行；首次 hoisted 安装误落在开发 runtime，随后已在显式独立目录完成安装；发行锁定文件未变化，后续仍须复核开发 runtime。候选无链接依赖。

- 库存校验：55,447 文件通过；不代表干净机器或许可总验收。
- 便携 Python 启动：通过，个人数据位于安装目录外；证据 `E:/SumikaBuild/acceptance-20261017-current/startup-d0c21332f3e0427b9063ee64352dcb11/report.json`。
- 响应矩阵：128/128，通过，横向溢出0、pageerror 0；证据 `E:/SumikaBuild/acceptance-20261017-current/matrix-rc2/report.json`。
- 记忆纠正/关系8项通过：`E:/SumikaBuild/acceptance-20261017-current/memory-ui-rc2/report.json`（真实Bridge、合成事实）。
- 陪学会话43项通过：`E:/SumikaBuild/acceptance-20261017-current/session-ui-rc2`（源码UI夹具，不是候选端到端）。
- 候选模式/行为管理24项通过：`E:/SumikaBuild/acceptance-20261017-current/profiles-ui-rc2-rerun/report.json`。首次失败为800ms固定等待竞态：磁盘已保存revision2，刷新尚未完成；验收脚本现等待游戏/手动状态，再执行编辑流程。
- 源码全量回归：1304项，OK，23跳过；资源释放/弃用警告仍存在，未宣称零警告。

候选实际 EXE 首次启动、复用、外部 HTTP 端口拒绝和认证关停 4 项均通过，证据 `E:/SumikaBuild/acceptance-20261017-current/exe-startup-331901d89e164da5bdaf79e6020853fc/report.json`。

仍待：角色导入和工作台功能复验、候选完整源码一致性，以及真实设备和干净机器验收。不得将本次窄范围通过视为整体验收完成。

## 最新版本再次核验

2026-10-17 再次查询 npm 完整 versions、time 与 dist-tags：最新发布版本为 `0.2.1-rc.2`（`2026-10-17T08:36:31.655Z`），不存在更新的 alpha/beta/RC。`latest` 标签仍指向较旧版本，不能据此降级。冻结 pnpm 安装通过，原生 Web/auth/session/cancel 探针再次通过，模型调用 0 次；项目 check 与 handoff 通过。继续复用当前固定 runtime，无需重复升级。

## 候选工作台与角色导入补验

角色导入与工作台浏览器检查通过（`role-import-rc2.json`、`workbench-rc2.json`，位于当前候选父目录），页面/控制台错误均为0。工作台为进入外壳 `#board` 时延迟启动；之前在进入工作台前读取embed的not-running结果不构成运行时故障。模型设置只读导航及能力页合成写入检查也通过，见同目录`settings-rc2.json`。角色真实VRM/模型回答、非空会话状态药丸及完整依赖验收仍未完成。

## 交接后收尾核验

- 再次实时执行 `npm view @deepseek-ai/dsh dist-tags versions time --json`：最新发布仍为 `0.2.1-rc.2`，`next` 同版本；无需再次变更依赖。
- 接续取得全量测试进程最终结果：1304 tests，128.002 秒，`OK (skipped=23)`，退出码 0。存在 SQLite 连接等资源警告及弃用警告，未声称零警告。
- `python -B -m sumika_next.cli check` 与 `handoff` 均退出 0；已有工作区变更保持。
- Windows 角色资源包恢复曾在定向回归中复现 `WinError 5`：Python 临时目录 ACL 导致 staging 发布失败。已改为在已授权角色仓储内创建随机 staging 目录，保留最终原子 rename、同名拒绝和损坏包不发布约束；单用例及 `test_ui_management` 17 项复验通过。

## 交接后边界修复

`PassiveBrowserAudio` 现在在构造时初始化 worker 配置哨兵；若内部 worker 启动路径缺少 `start()` 注入的模型、能力库或 ASR 配置，会明确抛出 `browser audio worker configuration is incomplete`，不再暴露 `AttributeError`/`TypeError`。新增回归覆盖未启动实例直接进入 worker 的边界，音频定向套件 9 项通过；该修复不修改 DSH 上游运行时。


## r2内部候选（本轮修复已纳入）

当前追加候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r2`，旧RC.2保留且未部署日用。复用上一候选记录的物理DSH rc.2、自包含启动器和运行时，55448文件库存校验通过；526个产品源码与引用登记文件逐个SHA比对0差异（父目录source-identity-rc2-r2.json）。本轮用量、未来一次性/下次计划及实际调度目录修复纳入。包内Python+真实隔离Bridge/SQLite/Edge，schedule-ui-rc2-r2 7项、memory-usage-ui-rc2-r2 9项通过，0页面错误/外部模型调用。全量源码1309项OK/23 skipped。其余旧候选证据不自动继承，真实依赖与干净机器门槛仍未完成。


r2实际EXE生命周期4项通过（当前Windows、独立数据、无模型调用）；证据 `E:/SumikaBuild/acceptance-20261017-current/exe-startup-03d359e8a176447cb65ef2e19ab5af5c/report.json`，测试Bridge已认证停止。完整源码一致性、库存及本轮修复包内复验通过；其余主线功能/真实设备/干净机器门槛继续，不作整体验收完成声明。


## 接续：官方 Office 技能与随包依赖（r6）

2026-10-17 实时复核 npm 完整发布时间，最新仍为 `0.2.1-rc.2`，`next` 同版；`latest` 仍旧版。证据 `.sumika-next/acceptance-20261017/dsh-registry-final.json`。不追旧标签降级，不修改上游。

现成资产：直接使用官方 `dsh-skill-office` 和 `dsh-tool-workspace-dependencies`；改造已有 `ui/workbench.py` 的公开 profile 注册，以及已有 `extensions/office/requirements.lock` 的独立依赖载荷。没有新增界面入口。新载荷由 `tools/prepare_office_payload.py` 从既有 standalone Python 和哈希锁 wheel 构建，不依赖开发机 venv，不更改 PATH；构建可指定 `--office-runtime`。

内部候选 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r6` 库存 58139 文件通过。536 文件源码比对仅 `tools/verify_phase5_office.py` 在构建后增加验收模式；产品源码一致。源码全量 1326 项 /126.857 秒 OK、23 跳过；定向 42 项通过，既有警告保留。

真实 r6 原生宿主自动注册两个插件、7 个官方渐进式技能、`load_workspace_dependencies` 返回包内 Python、该 Python 经原生终端完成 DOCX/XLSX/PPTX/PDF 读建改重开均通过。证据 `.sumika-next/p5-office-2d26d5685e274eebac59fbcc3087fba1/report.json`；12 次 loopback 合成模型调用、0 外部调用，受管 DSH 已关闭。复现：设置 `SUMIKA_TEST_CANDIDATE` 后运行 `python -X utf8 -B tools/verify_phase5_office.py --native-office-workflow --repair-fixture-acl`，ACL 仅针对本次生成的工作目录。

边界：官方 LibreOfficeKit 引擎仍禁用（`cli:false`），不能把宿主 soffice 渲染验证算给它；当前载荷是已有五类库及锁定依赖，不含官方工具通用描述中的所有库（例如 numpy/pandas）。旧 `sumika-office` 开关只管旧 runner，不能撤销原生终端或官方技能。readiness 是存在性预检，局部 bridge 库遮住完整旧 office-env 的边界仍待处理。未部署/发布，未做干净机器验收，r5 的其他功能证据不自动继承到 r6。

补验：r6 实际 EXE 首启、实例复用、外部 HTTP 端口拒绝且保留、认证关停共4项通过；测试 Bridge 已停止。证据 `E:/SumikaBuild/acceptance-20261017-current/exe-startup-3b8f6dc2d6c84ad6a18c68d4b718e858/report.json`。`check`、`handoff`、`git diff --check`通过（已有换行符警告）。

## 2026-10-18 r11包内接线复验

r11继续使用未修改的官方0.2.1-rc.2。60473文件库存、543源码SHA一致；原生Skill加载/Windows OCR服务/工作模型上下文、审批拒绝和取消、EXE4项及布局128格通过。原生OCR链路为6次本机模型夹具调用，未测真实模型翻译质量；LFM主力端点不可达，未切模型或启动服务。首轮全量1349项有1项profile原子替换WinError5，单独复跑通过，最终在全新E盘临时目录、无原生沙箱验收并发下全量1349项、199.815秒、OK（23跳过），退出0；仍有既有资源/弃用警告。前两轮WinError5/32及单独复跑记录保留，不确定原因未冒充已定位，未为通过测试更改产品或降低沙箱限制。证据：`.sumika-next/acceptance-20261018/full-suite-screenshot-review-isolated.log`。证据与限制见`feature-usage-and-acceptance.md`r11节。未替换日用安装、未登录领取赠金、未对外发送或付费。
