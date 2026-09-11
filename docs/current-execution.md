# Sumika 当前执行契约

## 目标

当前执行[H00–H07最终批准计划](refactor/harness-portability-hard-tasks-v1.md)。本Agent实现规划交接、Harness可替换、可信授权、费用恢复、源码验证与合入等高难项；普通项只写可执行交接。旧段落保留历史证据，不再据旧下一步跳过H00。

总体仍为[完整重构计划](refactor/client-workflow-v2.md) P00–P14及日用开发目标。当前按用户“优先关键难点”实施[剩余执行计划v2](refactor/remaining-execution-plan-v2.md)的执行恢复、证据和进程生命周期，契约见[开发恢复](architecture/development-recovery.md)。新增正式方向：[DSH优先复用、独立增强层与薄适配器](architecture/reusable-components.md#上游优先差量实现)，Codex开源组件补充对照，不重造完整Harness。既有Skill/免费路由成果保留。

## Definition of Done

本轮完成标准以H计划第五节为准：H00–H05相称验证、H06具备条件的真实闭环、H07全量交接。冻结Skill、真实自改、稳定日用和P14分别判定。不提交、推送、发布、替换日用profile或自动付费。

当前完成条件：执行循环脱离WorkService，独立适配器复用原SDK；操作前后持久记录，未知不重发；测试证据绑定源码状态；Windows测试后代可回收；旧任务/授权绑定及本地故障回归通过。自动续跑、受控合入、独立验收及真实自改仍单独验收。没有本轮新提交/推送或真实付费。

## 当前基线

- Branch: `codex/dsh-agent-runtime`
- Baseline commit: `a2a5f68`
- Last verified commit: 当前HEAD为`bd9144d`，此前`2843e27`保存既有功能与计划，既有上传已完成；本轮恢复/证据/进程改动仍为本地未提交成果。提交只建立恢复点，不代表新增产品验证结论。重构前基线见[保留基线](refactor/client-workflow-v2-baseline.md)。

## 当前里程碑

- 交接计划已落盘：v2保留R01–R17/L01–L09，增加R00及可验收子包，区分首次自改、稳定日用和原P14完成；66个模块、91项需求关联和P/V映射齐备。现已恢复关键路径实现；本轮前后持久记录、未知阻断、源码证据及Windows测试Job已接，完整自动续跑仍未实现。
- P00完成：用户计划逐字保存，91项需求与PLUGIN-003入账，文档检查通过。
- P01/P03/P04/P05/P06已部分接线：schema19迁移、项目/历史、版本化费用准入和独立成果；Agent/Web旧入口已接预算。新增外部显式子步骤的共享授权，API文本DAG自动外部交办仍未实现。
- P07/P08已合回，记忆作用域和场所模拟通过；P13调度核心与宿主线程已接。
- P09 SDK/DSH独立适配、P10/P12工作台组件及P11 Tauri双窗口已合回；隔离原生双窗口smoke已通过，真实多屏拔插、锁屏和鼠标托盘交互仍待验收。
- 独立工作目录：D:/Code/Sumika-cw-docs、Sumika-cw-projects、Sumika-cw-memory、Sumika-cw-views；不读真实凭据，不改日用库。

## 接下来的三个动作

当前优先顺序（取代以下历史顺序）：
1. H00实现及相称验证已完成，实际签名、限制和回执见[交接契约](architecture/task-planning.md)。新Skill仍需新任务显式加载验证，不阻塞后续独立开发。
2. H01已完成限定可信确认子包，并补上Agent问答/Plan Review：[实现与边界及下一批入口](architecture/host-confirmation.md)。继续workspace写入、retry、Skill/MCP等剩余权限审计及中立Harness契约、稳定实例，再做H02固定组合；不将H01局部完成当整包完成。
3. 顺序推进H03–H06，同步H07普通模型交接。API开发与DSH尚未使用H00检查；无真实自改，不改变日用运行版。


## 固定决策

免费简单可直达；所有复杂任务和付费规划执行先确认。角色免费优先，无合格免费可确认付费。主/角色分别自动或手动，固定失效不静默替换。正文与附言分离。共享原子预留，已购不算免费，未知不重发。默认2倍且多5元异常阈值不放宽硬上限。

## 明确暂缓

自动长期记忆、真实多人生活、语音/设备、壁纸桌面底层、社区发布。旧代码、数据、登录、个人资源全部保留。

## 当前阻塞

当前恢复/进程子包无已知外部阻碍。此前迁移清理曾被审批拒绝；`backend/build/`、`backend/src/sumika_core.egg-info/`及空草稿目录保留且不是源码交付。本次未删除；未来按R00重新核对实际内容、归属与授权，不能把历史拒绝当成本次仍不可读写。

产品仍受真实DSH缺强制费用上限、多屏热插拔等硬件未验、新API开发缺安全续跑/独立验收/合入/真实工具质量等限制；P14未完成。源码摘要绑定可见源码和授权测试命令，不覆盖全部依赖/环境，不冒充独立验收。旧8项专项已由下述新验证补充。历史原生smoke通过且当前脚本已动态选空闲端口，不要求用户再次重启或手工释放8771。详细差量及用户协助条件见v2。

## 验证记录

H01续做：Agent问答/Plan Review全部经过可信原生确认，普通HTTP伪造批准在checkpoint和运行时回复之前拒绝；原业务checkpoint顺序保持。后端全量1257通过（artifacts/h01-backend-final.log），专项91通过；前端83、Rust37通过，生产与隔离custom-protocol构建通过。相关E2E12项及问答/Plan Review2项通过；全量86项串行通过（6.9分钟，临时证据目录1789095255069）。固定模型测试增加保存完成等待，防止前一表单刷新与后一表单编辑竞争，没有放宽选模断言。最新真实原生smoke通过，含Plan Review普通HTTP/陪伴越权拒绝、双窗口生命周期和干净退出：D:/Caches/sumika-h01-native/1789095677009/result.json；工作台及透明陪伴截图已查。文档、发布资产和diff检查通过。当前H01仍部分完成；无DSH升级、真实模型付费、日用数据变更或提交发布。

H01限定可信确认子包：后端全量1255通过（artifacts/h01-backend.log），后续专项35通过；Rust37、前端83通过，生产构建及隔离custom-protocol构建通过。真实native smoke含确认边界通过，证据D:/Caches/sumika-h01-native/1789094697537/result.json，工作台截图已查。Playwright旧确认用例正在迁移到显式native fixture，最终结果待记录。未升级DSH，未覆盖日用二进制，未进行真实模型付费或提交发布。H01中立契约/全入口审计、H02–H06尚未完成。

当前H00：HEAD核对bd9144d，已有改动保留。批准稿完整保存及94项需求核对通过，文档检查通过。Skill格式通过，原两个Skill摘要保持，全局只增加规划段。后端全量1248通过（artifacts/h00-backend.log），后续补强质量专项100通过（artifacts/h00-quality-final.log），含实际Quality两阶段循环。SDK101项（2可选MCP跳过）源码及仓库外干净wheel通过，导入无sumika_core。H01–H06尚未实现，不宣称整计划或日用平替完成。

2026-09-11计划复核：文档检查通过；状态矩阵66行与v2模块表66行逐项一致，无遗漏、额外项或重复，91项需求status_ref全部有去向；diff空白检查通过。本次只改计划和入口/执行文档，不运行产品测试、真实模型、原生smoke，不改Codex个人文件或日用配置，不提交/推送/发布。以下是历史阶段证据，不当作本次全量结果。

本轮恢复/进程初步专项：SDK89项运行通过（2项可选MCP跳过），仓库外全新venv仅安装wheel后同样通过；开发18项和真实Windows Job Object4项通过。日志已改为现有工作记录内的前后事务，新增只读work.task.inspect；测试反写源码不再认证。最终结果见下一段。自动续跑、独立冻结验收集和OS沙箱未实现，旧8项结果不能证明这些能力。

本轮最终：按PLUGIN-004拆出DevelopmentExecutor/ApiDevelopmentExecutor，Core显式装配、旧factory兼容同一实现，授权绑定executor版本；专项31项及后端全量1244项通过（`artifacts/development-executor-refactor-backend.log`）。SDK90项（2可选MCP跳过）源码与仓库外wheel均通过，已确认从独立site-packages加载且无sumika_core；文档、92项JSON及发布资产/差异检查通过。上游仅源码只读核验，DSH/Codex日用配置未变，无新模型调用或第三方源码复制。未修改前端/Rust，本轮不重跑其历史验收；整套框架、自动续跑和日用替代仍未完成。

2026-09-10 Skill迁移：最终后端专项81项全通过（Windows junction无跳过）；工作台E2E10项、前端单测78项及生产构建通过。SDK79项通过（2项可选MCP未装跳过）。仓库外wheel验证三Skill、空配置、独立只读脚本，发布规则5项通过；文档与diff检查通过。真实DSH的all/四用途/no-permission/disabled场景、默认安装脚本两次执行及卸载通过，产物保留；无模型调用、无日用配置变更。完整来源见[迁移记录](refactor/skill-migration.md)，不把这些结果当作高级办公或真实Provider验证。

2026-09-10开发小任务：新增源码副本/工具循环/WorkService准入及工作台目录、开发模式、测试范围、日志和diff。102项后端专项通过（`artifacts/development-backend.log`），前端单测78通过；工作台专项E2E14/14（`artifacts/development-e2e.log`）。新测试覆盖真实临时Git目录、Python测试失败后修复成功、原目录不变、确认前零调用/零副本、重复提交和工具边界；模型为离线fixture。初次失败是Windows fixture换行造成hash不符，改为明确字节fixture，生产hash校验未放宽。

开发首版并非日用替代完成：源码copy不是OS沙箱，测试具当前用户权限；开发质量/真实Provider多轮、上下文恢复、受控合入、依赖安装、真实自修改尚未验收，详见剩余计划R01–R07。当前变更未重跑后端/SDK/E2E全量或原生smoke；下述全量结果属于上一阶段。

2026-09-10本次续做最终验证：后端全量1201/1201（`artifacts/backend-delegation-final-pass.log`）、前端单测78/78、全量E2E84/84、仓库外重新安装SDK79/79通过。前端生产构建及独立custom-protocol构建通过；最新原生smoke完整通过（`artifacts/native-smoke/1789029799640/result.json`），工作台授权截图和陪伴原生截图已查看。Rust源码未改变，沿用此前35项结果。无真实付费、日用数据操作、提交或发布。

父子任务已覆盖：原入口一次确认、明确子步骤、免费网页范围确认、助手/会话/项目/版本校验、并发共享预算、事务冲突全回滚、未知不重发、取消、重启及迟到正文不重复记账；凭据字段入库前拒绝。报价遵循route_constraints并固定目录顺序。中途两处AgentServer回归已确认是fixture缺Profile及完成事件刷新清掉手工目录，已隔离修复；生产价格变化拒绝不放宽。详见[外部父子授权](architecture/quality-component.md#外部父子任务共享授权)。

2026-09-09：后端全量1158项、质量专项75项、前端单测74项、SDK 76项、Rust 35项通过；前端构建、Tauri custom-protocol build、文档、发布资产和diff检查通过。HTTP与离线SDK为隔离fixture，不代表真实渠道质量。完整 Playwright E2E 已启动但前几项旧 A+ / 福利 / 咨询用例失败或超时，已停止，待单独适配；真实多屏 smoke 尚未完成。

## 恢复顺序

2026-09-09 续做验证：A+/福利/咨询 E2E 8/8、前端单测74/74、Rust35/35、前端生产构建和独立目录 custom-protocol build 通过。双窗口原生 smoke 全流程通过，证据 `artifacts/native-smoke/1788965104048/result.json`；修复与复用命令见[原生验收记录](refactor/client-workflow-v2-native-validation.md)。正在迁移其余旧入口测试；没有进行真实模型付费验证。

父子授权前整合：后端1183/1183、前端单测77/77、全量E2E83/83、Rust35/35通过。SDK在源码环境76项（2项跳过），仓库外P09环境76/76通过（含可选MCP），执行/取消/恢复均无sumika_core导入；DSH薄适配helper4/4通过。前端与原生构建通过，原生证据 `artifacts/native-smoke/1789024028431/result.json`；本次新增结果见验证记录。

旧19处后端回归已修；中途两处偶发失败专项通过，最新全量未复现。E2E已修重复福利面板、Escape未关闭右栏、重绘测量竞态；Windows剪贴板仅规范化CRLF校验，正文不掺角色附言。付费角色跨窗口确认等待页面初始化后通过。真实DSH和付费网页无可靠费用上界时仍返回未派发的限制；离线fixture不代表真实付费闭环，详细边界见[外部工作准入](architecture/quality-component.md#外部工作入口准入)。

先读本页和完整计划，检查Git变更与子Agent状态，再接续任务包；共享文件仅主Agent整合。

## 更新规则

每个里程碑更新实际状态、测试和限制；以代码和证据为准，未完成不得标为完成。
