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

# Sumika 缺陷修复与新需求执行总入口

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


## r11 主线治理与管理入口补验（2026-10-18）

继续使用`candidate-rc2-r11`，本轮只扩充现有维护验收工具，没有产品UI、上游或运行时变更，不为工具快照变化重打全包。包内Python+包内模块启动隔离真实Bridge/SQLite，真实Edge点击已有控件：记忆策略5项、记忆治理17项、行为/模式27项、定时任务7项、模块实现/排序/移除/重新添加8项通过，全部0页面错误。角色列表发现以及行为部分API使用夹具，报告保留边界；记忆/关系治理请求实际落库，5次本机合成对话验证开关，不证明实际模型质量。没有用户数据修改、真实设备采集或外部模型调用。

记忆治理现覆盖：手动事实、提议确认/忽略、JSON v5下载、重置取消不落备份、跨角色恢复拒绝、重置前备份及保留角色卡基线、同角色恢复事实/关系/提议状态、遗忘后重开弹窗；已有纠正/版本冲突/关系逐条身份检查保留。已查看`memory-dialog.png`，现有弹窗内容可读、底部可滚动。初次扩充脚本因fixture参数/提议证据不完整和误把重置预期设为零条而失败，均纠正测试，不改产品适应错误预期；失败报告保留。

真实候选EXE个人目录迁移通过：无认证/无确认拒绝，原目录保留、快照核验、同端口重新启动，最后请求关闭测试服务。模块移除取消不改变登记，移除后刷新不被bootstrap自动补回，重新添加默认停用。

证据位于`E:/SumikaBuild/acceptance-20261017-current/`：`r11-verify_memory_policy_ui/report.json`、`r11-memory-governance-expanded-r4/report.json`、`r11-verify_companion_profiles_ui/report.json`、`r11-verify_schedule_ui/report.json`、`r11-module-lifecycle/report.json`、`data-migration-6f5fcd8c5711473b94411c706ad5e74e/report.json`。工具仍从工作区运行、产品导入路径为r11，不能把候选包内旧维护脚本称为已同步。

R-072背景设定/世界书独立编辑与角色主题色消费已在既有角色资源弹窗实现并由r13/r14管理契约与候选证据覆盖；仍需注意实际角色模型风格质量未验。R-071的2D/语音/场景文件绑定不等于真实渲染/克隆/场景消费。定时原生执行、候选网页咨询注册/恢复、实际模型/设备/站点及干净机器仍逐项验，整体不标完成。


## 当前候选 r11：原生截图翻译 Skill 与 DSH 新版诊断（2026-10-18）

路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r11`；DSH固定`0.2.1-rc.2`。2026-10-18再次实时查询官方npm，最新发布与`next`均为此版；较旧`latest`不可用于降级。源码runtime的4项发行SHA一致。

工作台启动时将一次性截图翻译Skill发布到受管profile，直接复用原生filesystem发现、当前能力库/OCR模块服务和当前工作模型；不新增界面或模型路由。同名用户Skill不覆盖。新版DSH工具结果的message级状态与callId由独立诊断适配器兼容，冲突ID不关联，不导出正文。网页咨询已有submit/result工具继续复用。

r11库存60473文件、543个源码/登记文件SHA一致；真实原生Skill加载、禁用拒绝与Windows OCR文字进入工作模型上下文三项通过，6次本机模型夹具调用、0外部调用。EXE首次/复用/外来端口拒绝/认证关停4项及布局128/128通过，0横溢出/pageerror。网页咨询本机guard/snapshot、原生拒绝和取消检查通过，worker未执行、0外站发送。114项定向及diagnostics/skill12项通过。

全量回归首轮1349项、23跳过，profile记录原子替换出现1项WinError5错误；单独3项复跑通过。详细复验在751项因语音夹具临时目录WinError32清理失败停止；最终在全新E盘临时目录、无原生沙箱验收并发下全量1349项、199.815秒、OK（23跳过），退出0；仍有既有资源/弃用警告。前两轮WinError5/32及单独复跑记录保留，不确定原因未冒充已定位，未为通过测试更改产品或降低沙箱限制。证据：`.sumika-next/acceptance-20261018/full-suite-screenshot-review-isolated.log`。原生截图测试使用E盘临时目录时触发上游沙箱temp grant错误；默认临时目录复核通过，失败证据保留，无上游或沙箱绕过改动。

证据：项目`.sumika-next/acceptance-20261018/{dsh-latest-check.json,screenshot-skill-r11-default-temp/c8b1e283d9b548c39dfb702a0de8d806/report.json,full-suite-screenshot-review.log,full-suite-screenshot-review-diagnostic.log,runtime-ownership-rerun.log}`；原生拒绝`.sumika-next/web-review-native-dc4f302bf04f46ccab504a9e3fc268c8/report.json`，取消`.sumika-next/web-review-native-a8bcd255ca664ad88f112f2ae3e9b109/report.json`；候选父目录`{build-rc2-r11.log,source-identity-rc2-r11.json,matrix-r11/report.json,exe-startup-2dab462f46a34719a73708c00eb3c5cf/report.json}`。

前端使用：能力 → 启用OCR / 截屏翻译；工作台 → 现有项目/会话 → 提供图片绝对路径 → 输入“使用 sumika-screenshot-translation 翻译为简体中文，先列原文与不确定处”；按原生权限审批，在当前对话查看结果。已运行DSH须空闲时重启才能登记新Skill，不自动重启日用实例。云工作模型会接收识别文字。LFM主力端点当前不可用，实际翻译质量未测；不把本机确定性夹具当质量结论。实时游戏翻译/叠层、长期愿景和提示词优化仍暂缓。未部署发布，其他历史深度证据保留原版本，整体仍未完成。


## 此前候选 r10：桌面动作预检与未知结果修复（2026-10-18）

路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r10`；DSH固定`0.2.1-rc.2`。既有`desktop/act`服务现接入授权动作编排器，完整传递文本、按键、控件定位与快照；无效请求在动作前拒绝。原生变更尝试或动作后检查失败返回`unknown`并禁止自动重试。静态图片OCR即使匹配，也不冒充动作后的新状态；可信宿主新图回调仍需另行采集授权，未新增UI或自动截屏。

源码定向16项、全量1345项（262.983秒，23跳过）通过，仍有既有资源/弃用警告。包内解释器与包内维护工具通过7项真实隐藏窗口服务检查：禁用/未批准/缺少验证参数/快照过期零改动、正常文本输入、静态OCR匹配不证明新状态、动作后OCR失败保留已执行未知。测试初版缺少禁止激活窗口样式导致前台断言失败，已加NOACTIVATE及隐藏解释器启动；失败报告保留，最终前台不变、worker退出。工具改动已同步候选，原manifest及前后SHA保留，最终库存60470文件、540个源码/登记文件SHA一致。EXE4项及布局128/128通过，无页面错误/横溢出。

证据：`.sumika-next/acceptance-20261018/owned-uia-r10-final/bee6fa3b843e417cbb055d38f55e50c2/report.json`、项目`.sumika-next/acceptance-20261018/full-suite-desktop.log`、候选父目录`{inventory-r10-final.json,source-identity-rc2-r10.json,matrix-r10/report.json,exe-startup-fdf605b6b07948f3b4de5e428c96073a/report.json}`。本轮不采用户画面、不向用户应用输入、不调用外部模型；未部署发布。其他旧候选深度功能证据保留原版本，不自动视作r10已全部复验。整体目标仍进行中。


## 当前主线验收范围核对（2026-10-18）

### r14 接续结果与新修复

- r14 官方 Office 引擎复验通过：DOCX/XLSX/PPTX 转换、XLSX 公式重算、DOCX 两页渲染、坏文档拒绝、源文件哈希不变。报告：`.sumika-next/acceptance-20261018/office-r14/c7a6cdb0c40e4acbac97e1ed754e6c02/report.json`。缺少 `Courier` 字体已保留为渲染限制；视觉页已人工查看，不能推广为任意文件无损或干净机器通过。
- r14 原生审批 UI 三分支通过：拒绝/取消没有启动本地工作器，允许一次仅启动一次；0 外部模型/网页调用，受管 DSH 已停止。报告：`.sumika-next/native-approval-ui-88482fc682474c50a272b165d6e13522/report.json`。该夹具使用测试专用本地 runner，不授予 BrowserSkill 站点权限，不替代真实外站发送验收。
- 发现并修复 `ui/server.py` 的断开响应异常：客户端在业务处理完成后断开时，现在只关闭连接，不再次发送错误响应，也不重放业务操作；新增 `tests_next/test_http_response_disconnect.py`，3 项定向测试通过。修复发生在 r14 构建之后，必须进入下一候选后重新做包内验证。

### r15 接续结果

- 为角色资源导入修复 Windows/Python 3.14 下的偶发 `WinError 5`：UI 管理层不再使用受限 ACL 的 `TemporaryDirectory` 作为发布前目录，改为在授权 staging 父目录下创建随机目录，显式清理，并保留同卷原子重命名。角色导入定向测试通过；全量回归 **1362项/134.309秒，OK，23跳过**。
- 独立构建 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r15`，库存 60481 文件；包内 `ui/server.py` SHA-256 与源码一致，包内解释器断连模拟验证业务只分发一次并正常收口。`verify_portable_staging.py` 通过。r15仍是内部测试候选，未部署。

最终目标是完成当前所有主线、整体验收与修复、更新配套文档，再交付完整已实现功能的前端点击使用清单。长期愿景和提示词优化仍按用户明确要求暂缓。不能把剩余范围缩成“仅设备测试”，不能据r9局部通过标记整体完成；历史阶段`partial`需对照原始R编号与现场逐条收口。

|需求|现场已有资产/证据|继续核验的范围|
|---|---|---|
|R-060 Office四格式|r8官方技能、依赖和原生引擎；复杂结构/重算/渲染夹具|自然语言具体任务质量、当前最终候选复验及干净机器前置|
|R-061 OCR和截屏翻译|r9文件Windows OCR、原有RapidOCR；`translation.py`、`translation_pipeline.py`|翻译provider与用户流程的实际接线、截图来源/权限及最终显示；不能以单个翻译回调证明全流程|
|R-062 桌面观察/点击/输入/快捷键/窗口|UIA、低级坐标工具、原生授权；当前源码隐藏窗口服务验收|当前新候选复验；动作不确定不重放；各类动作的实际软件边界，不抢用户输入|
|R-063/R-064 模块与实现切换|既有模块管理；r9真实OCR多实现保存/刷新|最终候选的添加/排序/移除/启停与其他实现依赖检查，旧证据不自动转移|
|R-065 定时任务|现有调度器、区分提醒与执行、浏览器测试|最终候选逐入口/异常/重启流程核验|
|R-066/R-067 网页咨询与内置管理|`browser_consultation_bridge.py`已有`send`填入和独立`submit`原子页面guard，响应journal/快照与站点适配|核实实际提交/读取/完成判定与现有UI绑定；旧计划“send只填入”不能覆盖后来新增submit，也不能据submit函数就判完整产品完成|
|R-070 长期记忆比较与治理|规范素材/事实分离、纠正/遗忘/迁移接口、社区同集评测与可选Mnemon只读Source|最终实际模型质量与当前候选逐项治理；不以14例夹具声称最佳或长期质量|
|R-071/R-072 角色资源/世界书/主题|角色卡/VRM/ZIP资源导入与后端上下文；手测指南列预留控件|逐类资源对照实际支持格式和用户流程；预留编辑器不得列为已实现|
|R-073 语音/授权感知及后续行为/模式需求|现会话协调、语音/采集适配、行为层与现有设置UI|实际设备、真实站点/内容、持续运行与取消；保持采集许可和模式选择分离|

当前功能点击表见`feature-usage-and-acceptance.md`；该表仍是待逐行收口的检查表，不代表完整验收报告。确需新增UI时须先定位设计稿并按项目规则确认，不能用新增入口掩盖接线缺口。

## 接续审计检查点（2026-10-18）

文件OCR补齐源码真实识别与既有实现选择器验收，r9候选已完成文件OCR、真实模块选择、库存/SHA、EXE与布局验证，不继承r8未重测项目的通过结论。全量测试首次因C盘剩余低于1GiB触发行为库容量保护而出现76错误；改用E盘临时目录后1336项回归通过（23跳过），不降低产品阈值。当前详见三份项目状态的 `native_file_ocr_20261017.latest_20261018`。

以下为r10修复前发现（现已修复并接入既有服务，详见当前候选记录）：`extensions/desktop/control/authorized_action.py` 在执行动作之后才检查缺少 `verification_image`，且未透传 `text`/`keys`/`automation_id`/`control_type`，导致带参数动作不可用。该编排器目前未被通用service或产品UI调用，不能宣称已接通完整后验闭环。后续修复须先完成参数预检、透传明确的动作参数、补“无效请求零执行/完整参数传递/执行后验证失败不重放”测试，并区分静态图片OCR证据与动作后新截屏；不能用旧图片证明新动作成功。不得为修这一缺陷新增UI或触碰用户窗口。

> 当前状态（2026-10-16）：P00～P17经独立审计后已完成本轮源码修复与自动化验收；真实设备、模型质量和最终候选/安装仍需分别核验。当前实施与证据见 [acceptance-20261016.md](acceptance-20261016.md)。下方2026-10-12正文保留为历史规格，不能据“未实施”重放已完成工作。


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
