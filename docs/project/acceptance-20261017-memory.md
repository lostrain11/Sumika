# 长期记忆第一包验收（2026-10-17）

2026-10-18接续：r11包内真实Bridge/UI补验结果见`feature-usage-and-acceptance.md`“r11主线治理与管理入口补验”。记忆策略5项、治理17项、行为/模式27项、定时7项、模块8项通过；候选个人目录迁移通过。仅维护验收扩充、未改变日用默认或产品界面，不扩张历史模型质量证据。R072现有设计只有预留卡，新增控件确认待答。

## 长期记忆开关至真实聊天链路补验（2026-10-17）

复用现有能力页长期记忆详情、活动室输入框、Bridge/SQLite及角色模型适配，不改产品代码或UI。维护工具`tools/verify_memory_policy_ui.mjs`改造既有记忆浏览器验收框架，使用仅监听127.0.0.1的合成Ollama协议模型；仅角色发现列表为API夹具，设置保存、聊天、记忆读写均走真实接口。

源码与r4包内Python/产品导入各通过5项：关闭后下一次聊天不检索/规则写入/模型提议且已有数据可管理；重新开启可召回原事实，不隐式开启提取；规则独立保存明确自述；模型独立生成待确认提议且正文隐藏结构附注；已有聊天后再次关闭可刷新缓存配置。每次5个本机合成模型请求，外部请求0、pageerror0。源码截图已查看。证据：`.sumika-next/acceptance-20261017/memory-policy-final3/report.json`、`E:/SumikaBuild/acceptance-20261017-current/memory-policy-r4/report.json`。

手测顺序：能力→长期记忆卡→使用长期记忆/自动提取记忆/模型记忆提议→保存配置，再到活动室发送简单自述，回“管理角色与记忆”核对事实/待确认提议。三个开关分别测试；模型提议不代表已记住。此验收不证明真实模型质量、语义模型召回质量或已开始请求的在途撤销。r4不含后续任务交接接收修复；新维护工具在工作区，不将它冒称为r4清单内文件。

## 当前接续：语义向量与缓存边界修复

资产判定：改造`semantic_memory.py`既有检索与`embedding_runtime.py`既有子进程向量校验，抽出共用`validate_embeddings`；不增加检索provider，不修改阈值或默认模型。原进程内路径只用zip计算，缺向量/维度不同可能截断或KeyError，缓存零向量可能除零，NaN缓存也没有统一拒绝。

现在新增向量和当前查询涉及的缓存均在事务写入前校验：数量、同维度、有限数值、非零有限范数；不完整批次不会部分入库。损坏缓存明确报重建索引，不静默换provider或继续返回不可靠结果。余弦先归一化再乘，避免合法极小/极大向量的中间值下溢/溢出，scope失效围栏保持原有语义。

- `python -X utf8 -B -m unittest tests_next.test_semantic_memory tests_next.test_memory_repository tests_next.test_embedding_runtime -q`：30项通过，含5项新边界测试及原有跨连接失效/遗忘竞态。
- 已安装真实离线embedding模型重新评测：embedded8/14，semantic13/14，作用域隔离、更新、遗忘及其他scope清洁检查全部通过；证据`.sumika-next/acceptance-20261017/semantic-vector-quality.json`。这是14条合成题的回归，不声称长期模型质量或优于所有社区引擎。
- 修改发生于r2构建之后；r3内部候选已构建，55448文件库存通过，526个产品源码/引用登记文件SHA一致。包内Python执行本轮30项记忆测试通过，并断言实际导入r3中的产品模块；测试用例从工作区载入。源码全量1319项，126.968秒，OK（23跳过）；日志`.sumika-next/acceptance-20261017/semantic-vector-full-python.log`仍有资源释放/弃用警告，不宣称零警告。r3最终候选状态见升级验收及交接记录。

## 当前接续：Mnemon与新版DSH兼容性

2026-10-17：复用`tools/verify_mnemon_host.py`、公开Mnemon 0.5.29 SDK及现有只读settings绑定适配层。脚本原先写死DSH 0.2.0-rc.2，现增加`--runtime`（默认`runtime/dsh`）和真实版本报告；`--help`仅显示用法，不再意外运行整套验收。没有改DSH源码、node_modules或日用profile。

`python -X utf8 -B tools/verify_mnemon_host.py --runtime runtime/dsh`退出0：DSH **0.2.1-rc.2**真实隔离宿主10项通过，证据`.sumika-next/mnemon-host-b46f292675154b30b286cbe375b80a90/report.json`。覆盖宿主加载/dashboard、自定义只读Source、无内置Sources、禁用后重启移除，以及真实Agent的规范事实读取、无写动作、关闭记忆后无route/正文、撤销旧offer不泄露正文、取消后无工具调用。本机确定性模型夹具6次请求，外部模型调用0，日用配置未改变；不证明新引擎质量或已部署Mnemon。此前0.2.0证据保留历史版本归属。

本文下方按历史实施阶段保留的“尚未增加纠正按钮”“正式宿主未接入”等描述，只适用于该段当时范围；当前事实纠正UI及离线素材删除以紧接其后的最新实施段、代码与候选验收记录为准。未把历史“下一步”作为重复施工指令。

## 最新接续：离线素材彻底删除与已批准事实纠正控件

复用判定：现 `Conversations` 原对话/clear恢复表、规范 `SQLiteRepository` 事务/抑制/scope fence、`tools/manage_personal_data.py` 离线维护入口及 `ui/data_lease.py` 均改造后使用。新增 `extensions/roles/material_purge.py` 仅协调这两个已有owner，不另建素材库。UI资产复核：`ui/prototype-d/index.html` 约716行只说明角色独立记忆、约933行有长期记忆能力卡，**没有事实纠正控件设计**；用户已通过异步回复“增加纠正控件（推荐）”明确批准，在现 `management.js` 角色记忆弹窗新增同款mini-btn，未增加导航或页面。

离线 `purge-material` 默认预览，只接受当前配置角色/user/project的1–100个真实用户message ID。执行必须显式confirmed与当前plan digest；检查个人目录独占lease、恢复/迁移状态及设置/角色摘要。两库通过SQLite ATTACH同事务删除：当前/clear恢复对话、关联handoff和event副本、带对应EvidenceRef的active及历史规范记录/提议，清向量并重建FTS；触发器失败整体回滚。只支持磁盘rollback journal，WAL/memory/off拒绝，不偷偷重配数据库。删除后两库VACUUM，压缩失败单独返回pending，不将已提交删除伪装成可重试失败。没有对真实用户素材执行删除。

保留无正文的哈希来源/record/event/proposal及对话turn tombstone，防迟到提炼、相同legacy消息导入、旧JSON merge/restore恢复正文；全量文件备份恢复是另一回事。记忆导出为**v5**，携带上述标记，读取v2/v3/v4；旧版程序拒绝v5，不能去掉标记降级格式。逻辑遗忘仍可由显式历史JSON restore恢复，彻底删除标记不会因此取消。现clear行为不变。未知出处旧事实、手写关系是独立数据，不凭文字相似度删除；多来源结论触及删除来源时保守删该结论，独立确认记录保留，尚不自动重新归纳其余证据。

范围限制：备份/旧导出、已交给DSH或其他外部消费者的副本未删；不是取证级磁盘擦除。受管Bridge必须停止，独立未受管消费者也须停止；现lease不能强制任意第三方遵守。工具没有新前端入口，不把“清空聊天/遗忘”当成彻底删除。命令说明见 `extensions/memory/README.md`。

事实纠正入口：活动室→展开部员名册→管理角色与记忆→选角色→事实行“纠正”→输入新文本→二次确认。复用已有scope/record CAS与request_id；取消/空白/原文不写入，旧弹窗冲突报错，旧事实仅保留为不可召回历史；没有另开模型请求。

验证：**1302项全量OK，23 skipped，114.889s**（`.sumika-next/acceptance-20261017-memory-purge-final-python.log`）；75项相关OK/4.674s；最终9项purge专项OK/1.354s（`.sumika-next/acceptance-20261017-material-purge-tests.log`，最后新增在途检索测试发生在全量discover之后，单独通过，未冒称全量包含1303项）。覆盖跨scope、active/历史/多来源依赖、accepted及pending提议、两库失败回滚、旧v4恢复/新v5迁移、防迟到写入、在途检索拒旧hit、lease/WAL门禁和恢复状态。真实CLI合成数据3项通过（`.sumika-next/acceptance-20261017-final/material-purge-cli.json`）；真实Bridge浏览器8项通过（`.sumika-next/acceptance-20261017-final/memory-correction-ui/report.json`），含取消/二次确认/刷新/并发冲突和关系回归；同目录截图已人工查看。零外部模型调用、日用配置未变。

仍待：社区候选检索质量对照、日用opt-in、最终候选整体UI/真实硬件与全部功能指南逐行验收。下文“物理purge/纠正按钮未完成”是历史阶段，不代表本包状态。

## 最新验收：真实 Agent 回合与关系逐条 CAS

复用资产：现 `repository.py` 的 SQLite 事务/scope fence、`ui/app/management.js` 既有关系行和弹窗、`tools/verify_mnemon_host.py` 原生宿主基座、`tools/verify_companion_profiles_ui.mjs` 隔离真实 Bridge 浏览器基座；均改造后使用，未另建产品页面、控件或数据库。设计参照仍为 `ui/prototype-d/index.html` 原角色管理区域；本包仅修既有控件语义。

Mnemon 0.5.29 + DSH rc.2 **10项真实宿主/Agent检查通过**：真实模型传输中读取公开 view route，原生执行只读工具并召回 canonical 合成事实；记忆关闭后无路由/正文；已发旧offer在关闭后不能读取；dispatch阻塞期间原生取消回合返回 user/aborted，无工具调用或记忆正文；原生禁用重启移除 Source。证据 `.sumika-next/mnemon-host-06f6afeeaeb443a4bab12f2320de1b17/report.json`。6次 loopback 确定性模型夹具调用、外部模型调用0、日用profile未变；这是接线验收，不是模型质量或日用部署验收。

关系管理现使用稳定 record_id 与逐条 expected_revision，在同一事务内只改所选行、增加版本并更新 scope fence；拒绝旧版本、其他scope和已删除记录。UI沿用原有编辑/删除按钮，仅提示改为“只更新当前这一条关系”。旧RoleSession无record_id的文字批量API为兼容保留，不能声称所有调用都变成逐条。新增回归覆盖重复行、并发冲突、删除后旧merge防复活与触发器故障回滚。

验证：47项相关测试通过（2.336s）；**1294项全量OK，23 skipped，108.921s**，日志 `.sumika-next/acceptance-20261017-memory-relations-python.log`。`node tools/verify_memory_relations_ui.mjs`：4项通过，浏览器点击既有关系弹窗、真实HTTP/SQLite编辑/删除、重复行保留、record_id/revision核对、零pageerror；证据 `.sumika-next/acceptance-20261017-final/memory-relations-ui/report.json` 和同目录截图。仅角色发现使用合成响应，记忆读写为真实Bridge，合成数据独立目录，零外部模型调用。并发窗口由仓储/管理层回归验证，浏览器没有伪称覆盖所有竞争时序。

当前剩余：素材物理purge跨owner协调、社区候选检索质量对照、日用启用及最终候选整体点击/设备验收。事实纠正后端已存在，新增前端按钮尚未交付；长期愿景不实施。下文按历史阶段保留，“Agent待验/关系CAS未完成”等仅指当时阶段。

## 最新接续：真实设置绑定的 Mnemon 原生适配

本包直接复用/改造 `mnemon-source.mjs`、现 settings 校验与 `open_session`、MemoryRetrieval、既有独立DSH宿主验收工具；没有平行数据库或新UI。实现 `mnemon_bridge.py`、`mnemon-host.mjs` 与可选 `extensions/memory/dsh.mjs` 注册层。读取绑定当前 user/role/project、记忆开关、配置摘要与持久化scope版本；取消/超时/卸载清自有进程。

修正现场发现的两处草稿接线问题：Mnemon真实Agent默认使用workspace，原草稿仅接受custom；旧settings的memory.enabled缺省应与既有Python默认true一致。另补配置读取一次解析、加载后scope核对、回包前epoch复核，避免切角色时返回旧结果。查询输入在打开库前校验。

`python -B -m unittest tests_next.test_mnemon_bridge -v`：6项通过（1.941s），含7项真实Node/公开SDK检查，覆盖确认事实/三轴隔离、关闭/非法输入不建库、旧配置、在途切角色与开关、旧grant失效、取消、卸载。`python -B tools/verify_mnemon_host.py`：真实DSH rc.2隔离宿主5项通过，加载真实wrapper、RPC dashboard注册唯一Source、禁用重启后移除；证据 `.sumika-next/mnemon-host-4dbfb35be0b34ba893ec446f941aac1c/report.json`。

范围：合成数据、零模型调用、日用profile未改。真实Agent回合和检索质量对照尚未验收；不能称已日用。素材物理purge、关系CAS和最终整体候选验收仍待后续。配置与复用方式见 `extensions/memory/README.md`。

全量回归：**1291项OK，23 skipped，110.380s**；日志 `.sumika-next/acceptance-20261017-memory-settings-python.log`。下方为先前阶段记录，各数字仅代表对应当时字节。

## 最新补强与范围调整

### 接续：可复用只读 Source 与绑定失效

新增 `extensions/memory/mnemon-source.mjs`，复用现Mnemon公开SDK/规范仓储契约；原固定scope fixture仅保留测试用途，不复制为产品逻辑。宿主注入 resolver/revision/search，Source无写入、模型调用或进程启动。binding包含可信user/role/project、开关、bindingId及epoch；grant和公开版本使用摘要，防不同scope版本计数相同时旧grant误用，也避免公开原始身份。查询前后核对绑定、开关、仓储版本与signal；改变即拒绝结果。宿主契约及关闭重开/历史恢复epoch规则见 `extensions/memory/README.md`。

真实SDK **15项通过**：原10项加可复用Source注册/只读路由、角色切换拒绝旧grant、关闭不调用搜索、在途关闭丢弃结果、在途取消丢弃结果。证据 `.sumika-next/mnemon-contract-0a14dedb11f84b02b890681f9f8fed6f/report.json`。测试回调仍使用合成库，实际客户端resolver与会话生命周期尚未接入；没有宣称真实角色/Agent完整接线或检索质量提升。本包只改变JS适配和验证，前一包1285项Python全量证据不充当本包JS验证。

### 接续：来源撤回与正式隔离宿主

本包最新全量：`python -B -m unittest discover -s tests_next`，**1285项，OK，23 skipped，109.697s**；日志 `.sumika-next/acceptance-20261017-memory-source-python.log`。包含来源撤回补丁；跳过项不算已验证能力。下方1283项等数字均保留为先前阶段证据。

复用资产判定：`extensions/memory/repository.py`、既有 suppression/SQLite 事务机制改造后使用；`tools/verify_mnemon_memory_contract.*` 改造后使用，Source/策略提取至 `tools/lib/mnemon-canonical-fixture.mjs` 供两套验证共享；`sumika_next.dsh.Dsh` 及现候选 rc.2 runtime 直接使用。未另建事实库或修改上游。

新增后端 `retract_evidence(refs, ..., expected_scope_revision)`：在同一事务内校验 scope 版本、抑制撤回来源、失效依赖事实/待审提议、清理向量缓存；即使事实尚未提炼也先登记抑制，阻止迟到写入。组合多来源结论保守失效，其他独立记录与其他角色不受影响。返回明确 `material_deleted=false/history_retained=true`。相关45项回归通过，新增2项覆盖依赖、旧快照merge/重建、防迟到提炼、版本冲突与事务故障回滚。此 API 尚未接产品素材删除协调器，不是物理删除交付。

正式隔离宿主实验：Mnemon 0.5.29 已通过 DSH 0.2.0-rc.2 原生 patch 加载，并由真实 RPC 验证 dashboard、自定义只读 Source 注册、无内置 Source、原生禁用后重启 Source 消失。使用独立 `.sumika-next/mnemon-host-deps` 安装公开依赖（ignore-scripts），不改日用 profile 或共享 node_modules，不加载 bundle/starter/provider；使用合成库、关闭自动摄取/写回/召回/同步/遥测，无模型调用。工具 `python -B tools/verify_mnemon_host.py`，宿主证据 `.sumika-next/mnemon-host-e3fcbd585d814f108716017cd7e164b5/report.json`（含禁用/重启RPC原始观察）；SDK 10项契约再次通过，证据 `.sumika-next/mnemon-contract-f927631294f649e89987b5e2c90300e4/report.json`。

这比“只验证 SDK”前进到真实隔离宿主生命周期，但固定合成 scope 仍非生产角色绑定；未验证真实 Agent 回合、UI、提炼或新检索质量。下方旧的“尚无正式宿主安装”仅指当时阶段，不代表此隔离实验尚未完成。产品默认仍为现有实现。

最终接续验证：**1283项全量OK，23 skipped，108.235s**，日志 `.sumika-next/acceptance-20261017-memory-management-python.log`，包含本次管理层补丁。陪学/桌宠浏览器43项及隔离真实Bridge行为/模式UI24项通过；记录见设计覆盖表。先前各全量数字为对应阶段历史，不作为最新字节验收。

管理层接续：`ui/management.py` 已提供角色绑定的 `correct` 管理操作（confirmed、弹窗revision、仓储逐条revision、host request_id）；其他角色record_id拒绝。遗忘从当前scope列表提取逐条revision传给仓储，修复状态读取后并发纠正仍执行旧遗忘的问题。管理状态读取前后复核持久化scope fence，避免分页/提议/关系拼成混合状态。新增2项管理回归，相关103项通过（49.185s）。这仍没有新增前端纠正按钮，已按AGENTS规则询问，待用户回答；后端与既有控件修复继续自主推进。

使用指南：`feature-usage-and-acceptance.md` 已建立按源码核对的功能/点击路径/预期/限制，含长期记忆、行为、陪学、工作台及设置，最终候选逐项UI验收仍未完成。正式Mnemon宿主接入和素材purge仍未完成，本轮不以文档替代实现。

本次最终全量：**1281项，OK，23 skipped，105.880s**，日志 `.sumika-next/acceptance-20261017-memory-fence-python.log`，包含以下持久化失效与embedding竞态补丁。项目check、handoff和diff检查通过。复用资产为现 `repository.py`/`retrieval.py`/`semantic_memory.py` 及已有Mnemon SDK试验，均改造后使用；无新增平行事实库、导航或采集。

持久化失效补强：复用现 SQLite，新增每库 identity/每scope revision 与事务触发器，覆盖事实、关系、提议、来源抑制的 insert/update/delete。变更/回滚与版本原子一致，其他scope不影响当前scope；版本不是写权限或备份恢复代号。MemoryRetrieval 在provider调用前和正文hydrate后比较版本，期间发生变更则整批丢弃，不自动重试。SemanticMemory在embedding结束后持写锁复核版本再写缓存，并在返回前复核，避免遗忘时在途embedding重新写回旧缓存。

新增3项真实SQLite回归覆盖跨连接版本可见/重开持久化/回滚、第二条hydrate时另一连接遗忘第一条、embedding期间另连接遗忘后不返回正文或残留向量；44项相关回归通过。Mnemon fixture移除进程内计数，改读该持久化版本，跨Python进程10项契约再次通过：`.sumika-next/mnemon-contract-fb83ec19dfac4159a8b9e4b46bc2556e/report.json`。全库文件级历史恢复必须重启消费者、丢弃旧回合，不能仅凭此版本宣称历史恢复后旧lease自动失效。尚未接入正式宿主。

最新全量复跑（含后端 correction）：**1278项，OK，23 skipped，106.695s**，日志 `.sumika-next/acceptance-20261017-memory-latest-python.log`。Mnemon公开SDK只读Source契约另通过10项，证据 `.sumika-next/mnemon-contract-ba037abdd1ce4d64a986eb12208e0c4a/report.json`，范围和限制见市场报告M04；不是插件产品部署或新引擎质量结论。

用户明确“长期愿景先不做。目前重点是长期记忆、DSH插件复用/开源社区项目复用”。长期设备愿景不进入当前实施；现有功能保留。

- 修复空事实库 reset 遗漏 pending proposals；重置到角色卡保留来源 suppression，避免旧对话被重新抽取。新增2项回归。
- 增加 `MemoryRepository.correct_record` 和角色服务 `correct` 操作：强制 expected_revision、宿主事件幂等；事务内替换旧事实、抑制旧来源、清缓存。新事实为显式 user 来源，保留旧记录历史；返回 supersedes。尚未增加前端纠正按钮，也未声称这是素材物理删除。新增2项测试覆盖跨scope、旧版本、重复提交、旧快照merge、重建、遗忘后重试与失败回滚。
- reset 补强后全量 **1276项，OK，23 skipped，106.773s**，日志 `.sumika-next/acceptance-20261017-final-python.log`。之后 correction 改动的相关 **40项，OK，1.783s**；两者验证时间范围不同，不把1276项说成包含correction补丁。
- 隔离行为/模式 UI：`.sumika-next/acceptance-20261017-final/behavior-ui/report.json`，24项checks通过、零pageerror；不涉及日用配置或真实采集。

下一步优先按现有市场报告 M00/M04 做候选隔离契约对照，以及素材删除/派生依赖治理。不要先扩展设备愿景或大规模重写其他模块。

结论：仓储/检索边界、稳定身份版本、逻辑遗忘来源抑制已接入既有代码；未安装社区记忆库、改变默认模型、部署客户端或新增界面入口。后续完整治理不算完成。

## 资产与改动

直接复用 `embedded_memory.py` 的规范 SQLite/FTS、`semantic_memory.py` 的离线检索、Conversations 的原始消息 owner。改造后复用 MemoryWriter、model_proposer、RoleSession 与 UI management 后端；新增薄契约 `repository.py` / `retrieval.py`，不是平行数据库。设计稿不涉及本次后端改造，UI markup 与布局没有本包新增。

- 事实/关系稳定 record_id、revision、生命周期；旧库备份迁移，v4导出兼容v2/v3。
- 业务记忆读写不依赖 SQL；usage 原有独立 SQL 不在这次记忆改造范围。
- 检索提供候选，规范库按 scope/source/revision 复核并提供正文；支持宿主 Python 注入替代 provider，现默认仍 embedded/semantic。
- scoped forget/CAS、来源抑制、同来源事实/待审提议失效；新消息可以重新声明。旧 auto-extract 编号和旧 proposal 引用按已知格式迁移。
- proposal 确认原子写入；模型候选保留待审，不允许静默覆盖已确认事实。
- merge 不复活已删事实/关系，应用较新 superseded 状态；显式 restore 保留历史恢复能力，版本不倒退。
- 索引重建仅按 active 事实重建共享 FTS，清范围内向量缓存，后续语义检索按需重算，不调用 LLM。

## 证据

1. `python -B -m unittest discover -s tests_next`：1271项，OK，23 skipped，103.663s；日志 `.sumika-next/memory-repository-regression-20261017.log`。这是最终兼容性补强前的全量结果，非全部最终字节的全量复跑。
2. 最终相关回归：`python -B -m unittest tests_next.test_memory_repository tests_next.test_memory_writes tests_next.test_memory_recovery tests_next.test_model_memory_proposals tests_next.test_auto_extraction tests_next.test_embedded_memory tests_next.test_semantic_memory tests_next.test_role_service tests_next.test_memory_chat_context tests_next.test_memory_capture tests_next.test_ui_management`：65项，OK，3.079s。日志 `.sumika-next/memory-repository-targeted-20261017.log`。
3. 新仓储边界11项：旧库备份/重开身份、来源抑制/新声明、跨scope与旧revision过滤/正文hydrate、eventless tombstone往返、确认失败事务回滚、有效事实索引重建、真实semantic search替身接线、disabled无外部调用、旧事件兼容、关系删除merge/restore、更新快照supersede。
4. `tools.evaluate_memory_quality.evaluate(EmbeddedMemory)`：关键词8/14，与已有基线相同；scope_isolated/update_correct/forgotten_rejected/other_scope_clean均true。未重跑真实embedding权重评测。
5. 项目 `check` / `handoff` 与 `git -c core.safecrlf=false diff --check`：均通过（continuity records: ok，handoff成功输出，diff检查无输出）。

## 限制与下一步

遗忘是逻辑失效；原始对话、历史正文与备份尚未物理清除。来源抑制采用整条消息保守策略，可能同时阻止其中其他事实，尚无多来源依赖精细重算。旧 inactive 无法可靠判断当初是删除还是被更新，不编造删除状态。未知旧来源只能保留事件引用，无法保证其所有重提炼变体可关联。

关系纠正 CAS、素材purge及派生级联、外部索引generation切换、社区引擎正式适配、真实长期角色质量仍待后续包；事实纠正 CAS 已补齐，见顶部。第三方 provider 的能力声明仍须独立契约实测；宿主hydrate能防错误正文/跨scope泄入结果，不能证明第三方内部检索与传输已隔离。现有来源字段和EvidenceRef由可信宿主提供，不是新的工具授权通道。

旧库迁移备份和导出v4是恢复资产。回退前先停止写入并备份当前库；若要回退旧程序，使用迁移前SQLite备份，不把新库直接交给不理解新状态的旧程序写入。备份后新增数据须单独保留并核对，不能假定回退无损。
