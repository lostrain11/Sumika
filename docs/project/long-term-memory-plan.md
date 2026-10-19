# 长期记忆：优先复用，实测择优

2026-10-18接续：r11包内真实Bridge/UI补验结果见`feature-usage-and-acceptance.md`“r11主线治理与管理入口补验”。记忆策略5项、治理17项、行为/模式27项、定时7项、模块8项通过；候选个人目录迁移通过。仅维护验收扩充、未改变日用默认或产品界面，不扩张历史模型质量证据。R072现有设计只有预留卡，新增控件确认待答。

## 长期记忆开关至真实聊天链路补验（2026-10-17）

复用现有能力页长期记忆详情、活动室输入框、Bridge/SQLite及角色模型适配，不改产品代码或UI。维护工具`tools/verify_memory_policy_ui.mjs`改造既有记忆浏览器验收框架，使用仅监听127.0.0.1的合成Ollama协议模型；仅角色发现列表为API夹具，设置保存、聊天、记忆读写均走真实接口。

源码与r4包内Python/产品导入各通过5项：关闭后下一次聊天不检索/规则写入/模型提议且已有数据可管理；重新开启可召回原事实，不隐式开启提取；规则独立保存明确自述；模型独立生成待确认提议且正文隐藏结构附注；已有聊天后再次关闭可刷新缓存配置。每次5个本机合成模型请求，外部请求0、pageerror0。源码截图已查看。证据：`.sumika-next/acceptance-20261017/memory-policy-final3/report.json`、`E:/SumikaBuild/acceptance-20261017-current/memory-policy-r4/report.json`。

手测顺序：能力→长期记忆卡→使用长期记忆/自动提取记忆/模型记忆提议→保存配置，再到活动室发送简单自述，回“管理角色与记忆”核对事实/待确认提议。三个开关分别测试；模型提议不代表已记住。此验收不证明真实模型质量、语义模型召回质量或已开始请求的在途撤销。r4不含后续任务交接接收修复；新维护工具在工作区，不将它冒称为r4清单内文件。

## 当前优先级与最新状态

**2026-10-17 当前状态校正（覆盖下文历史阶段）：** 仓储解耦、稳定ID/版本、事实纠正与关系逐条CAS、持久化scope围栏、来源抑制、离线按message ID素材删除、v5导出已实施。事实纠正在用户批准的既有管理弹窗交付，最终候选真实Bridge浏览器8项通过。素材删除仅离线CLI；旧备份、外部副本、未知出处旧记录和多来源精细重算不在已完成范围。

社区同集对照已完成：DSH LTM 0.3.1为11/14，现embedded 8/14、semantic 13/14；公开CLI纠正/版本冲突/遗忘另验。产品仍用canonical仓储及embedded/semantic；Mnemon 0.5.29只读Source与独立原生DSH生命周期已验，日用未启用。下一步是最终候选逐功能/真实依赖验收。下文“无纠正按钮”“素材未物理删除”“尚无稳定ID/仓储”“社区对照下一步”是历史阶段快照，不代表当前状态；当前证据见记忆验收和逐功能指南。

最新接续：按显式message ID的离线素材彻底删除已实现并验收，覆盖现两库中的对话/clear副本/handoff事件及有EvidenceRef的派生正文、FTS/向量；无新删除UI。无正文哈希tombstone随v5记忆JSON导出，读取v2–v4；不能由旧JSON恢复取消彻底删除标记。旧备份与外部副本不在此次范围，未知出处旧事实及手写关系保留；多来源精细重算仍未实现。用户已批准并实现事实行“纠正”按钮（现角色记忆弹窗）。当前主线下一步为社区检索候选同集质量对照、日用接入选择与最终整体候选验收，长期愿景不实施。验证与限制见 `acceptance-20261017-memory.md` 顶部；下文为历史阶段及剩余设计，不以旧未完成项覆盖本段。

只读Source适配本体已从固定fixture分离为 `extensions/memory/mnemon-source.mjs`，可信宿主resolver/epoch/开关契约及15项SDK边界通过；真实settings绑定wrapper与独立DSH原生Agent10项已验，日用尚未启用。入口、回调及验证方式见 `extensions/memory/README.md`；最新证据见记忆验收顶部。

接续已完成：来源撤回后端事务 API（含依赖事实/提议失效、阻止迟到提炼、scope CAS），以及 Mnemon 0.5.29 在独立 DSH rc.2 profile 的真实宿主加载/Source注册/原生禁用重启验证。素材未物理删除，Mnemon 尚非产品默认，详见 `acceptance-20261017-memory.md` 顶部。现库和领域素材 owner 继续复用，不另建平行素材库。

下一实施顺序：已完成可信设置/角色/项目绑定及真实Agent合成回合、开关/取消/旧offer验收；已完成有界离线素材删除协调，接续按同一中文与治理集对照社区检索方案。未完成日用opt-in前不切默认。素材彻底删除另做跨 owner 协调，须覆盖 role_turns、cleared_role_turns、handoff副本、规范记忆、索引/缓存和在途结果；沿用清空聊天的恢复语义，不能偷偷改 clear 为 purge。历史备份的保留/删除需明确范围，不能声称删除当前库便清除了备份。

最新补强已实现持久化scope失效版本：SQLite事务触发器覆盖规范事实/关系/提议/抑制修改；检索在途版本变化整批丢弃，语义embedding写缓存前持锁复核。Mnemon公开SDK试验已复用此版本跨进程验证，不再使用进程内计数。详见验收记录顶部；外部generation构建/切换与素材物理删除仍未完成。

用户于2026-10-17明确：长期愿景先不做，当前重点为长期记忆、DSH插件复用及开源社区项目复用。先完成当前软件的记忆治理与隔离候选对照，不展开设备愿景。已有数据库/领域素材 owner/检索资产继续复用。

第一包后续已补 reset 的 pending 清理与角色卡重置防复活，另新增后端 `correct_record` 原子纠正和角色服务 `correct`。纠正要求 expected_revision 与幂等 event_id，保留历史并阻止旧来源重提炼；无新增UI按钮。下文“尚无统一correction CAS”是第一包当时快照，现已有事实纠正API，关系逐条CAS也已接既有UI；素材物理删除及多来源治理仍未完成。最新测试及时间范围见 `acceptance-20261017-memory.md` 顶部。

复用顺序：现仓储作为规范数据owner → Mnemon Source/provider契约隔离试验 → Engram检索对照 → 必要时对照成熟社区引擎。插件不能取得用户事实裁决权；达到隔离/版本/删除/可导出门槛后才能考虑替换默认。现 `mem0_adapter.py` 只是早期本地SQLite占位，**不是已接入Mem0 OSS**；`memmachine_adapter.py` 是SDK薄包装，不代表生产已启用或通过治理契约。

## 2026-10-17 第一包已实施：仓储解耦与遗忘防复活

Mnemon 首轮公开SDK组合契约已通过10项隔离检查，复用真实 Cordis 与现 SQLite 仓储；无插件产品安装/默认切换。详见市场报告 M04 与 `tools/verify_mnemon_memory_contract.py`。该结果只证明框架能承载只读规范记忆 Source，检索仍是现FTS，不能解释为候选引擎质量提升。Engram发布bundle默认light摄取与无条件embedding预热问题已记录，未直接安装。

本节覆盖下方同日架构复核中“尚未实施”的当前状态；架构复核保留为后续规划依据。已复用现有 SQLite 和 embedded/semantic，没有另建记忆数据库、切换引擎或改 UI 布局。原始对话、行为素材继续由各领域 owner 保存，未复制进新素材库。

- `repository.py` 提供仓储契约与现 SQLite 治理实现；MemoryWriter、model_proposer、RoleSession 记忆动作、管理后端的记忆读取已移除 SQL 直连。`retrieval.py` 提供可注入检索接口；候选必须声明 scope/source/version 能力，宿主按当前 scope 和 revision 重新读取规范正文，过滤已删、旧版本、跨范围和重复命中。能力声明仍需未来每个适配器的实测证明，不能保证第三方不在内部跨 scope 检索。
- 事实和手写关系新增跨导出稳定 `record_id`、正整数 `revision`、active/superseded/deleted；旧整数 id 保留兼容。旧库首次迁移前使用 SQLite backup API 留存一致备份，新增来源引用只映射已知宿主事件和 proposal metadata，不推断旧 inactive 的删除原因。
- 同一 scope 的遗忘写来源 hash 抑制，禁用同来源的改写抽取/新 proposal，并使相关已生效事实和待审提议失效；用户新消息是新来源，可重新声明。此版是保守的整条消息抑制，会连带抑制该消息中其他事实，尚未实现多来源证据精细裁决。
- proposal 确认与事实写入共用事务；确认和遗忘支持 expected_revision。其他纠正仍沿用 fact_key 写新事实/旧值 superseded，尚未提供统一 correction CAS API。模型提议不自动成为已确认事实。
- v4 JSON 保留身份、版本、来源引用、关系及抑制，兼容 v2/v3。merge 尊重删除、较新 superseded 状态且不重新激活历史事件；既有显式 restore 可恢复历史状态，版本不倒退，需沿用现有确认和备份流程。手动备份也可能恢复已遗忘内容，不能把 restore 当普通 merge。
- 可调用 `memory.rebuild_indexes(**scope)`：共享 FTS 在事务内只按 active 规范事实重建，清除所选 scope 的 embedding 缓存，之后本地语义检索按需重算；不调用生成模型、不重新提炼原始素材。不是外部引擎 generation 隔离构建/原子切换方案。

验证：全量 1271 项通过、23 跳过；后续来源兼容/关系生命周期/有效索引重建补强后，65 项相关回归通过（含 11 项新仓储边界测试）；embedded 中文基线维持 8/14，隔离/更新/遗忘门禁通过。semantic 本轮用确定性替身跑真实 search 接线，无新真实 embedding 或生成模型质量结论。详见 `acceptance-20261017-memory.md`。

尚未交付：素材物理删除及全部派生数据级联清除、跨来源依赖重算、外部索引 generation、社区引擎正式适配及真实长时质量验收。遗忘目前是逻辑失效，历史正文、对话素材和备份仍可能保留；行为数据不自动灌入长期记忆。

## 2026-10-17 架构复核与实施顺序（设计时快照；第一包状态见上）

**结论：长期记忆已有可运行基线，不需要先重做或先装新引擎才能继续行为功能；但现在就应固定素材、规范记忆与检索索引的边界，并补齐真正可替换的接口。** 本节仅为 Astra 规划复核，Sol 主线实施继续；未切换 provider、安装插件、调用模型或改产品代码。下方历史“首选/已支持”须按代码和对应证据理解，不能视为今天新做的实测。

### 已有资产与真实实现

|资产|代码事实与本轮复用判断|
|---|---|
|`extensions/memory/embedded_memory.py`|直接复用规范记忆的现有存储基线：SQLite `memories`、`relations`、`memory_proposals`，FTS5 检索；user/role/project 三维 scope；source/event_id 幂等；fact_key 更新使旧值 inactive；v3 JSON 导出、导入、按范围恢复。不是成熟第三方完整记忆引擎，也不具备所有语义抽取能力。|
|`extensions/memory/semantic_memory.py`|改造后复用为检索适配：继承 EmbeddedMemory，共用同一事实表，FastEmbed/BGE 中文 embedding、余弦与精确子串混合排序；`embeddings` 是带模型摘要的可重建缓存；恢复/reset 会清范围内缓存。已有离线 runtime，运行时不下载、不自动 fallback。|
|`extensions/memory/write_policy.py`|保留宿主来源策略，但需解耦：用户/角色卡来源可写事实；模型来源写不可检索 proposals。当前直接访问 `memory.db/_scope`，尚不是 provider 中立接口。|
|`rules_proposer.py`、`extraction_policy.py`、`model_proposer.py`|保留并封装现提议/审核资产。规则只识别简单自述；模型提议要求当前原话引用并由用户确认。model_proposer 也直接读写 SQLite；匹配到引用只证明有关联，不证明模型归纳正确。|
|`extensions/roles/conversations.py`|直接复用对话素材：独立 `role-conversations.sqlite3` 已保存用户 original、角色 reply、session、scope、时间和状态；请求前存 unknown，不自动重放。clear 是移到 `cleared_role_turns` 恢复副本后移除上下文，**不是物理删除**。|
|`extensions/roles/service.py`、`chat.py`|已有 RoleSession/上下文接线，当前生产选择仅 embedded/semantic；不支持任意引擎插拔。RoleSession.forget 直接改 memories 表，虽做 scope 过滤，仍耦合 SQLite。近期对话、角色卡、长期记忆及行为参考已有独立来源块，不必重做 Agent 循环。|
|`docs/project/memory-quality-evidence.json`、`memory-semantic-dsh-evidence.json`|历史合成14例：关键词8/14、语义13/14；另有 DSH 改述召回/旧值不注入证据。只证明这些样本和当时实现，不能外推长期中文事实质量或“最佳引擎”。|
|`docs/project/long-term-memory-evaluation.md` 的 2026-10-16 节|已有 DSH 插件考察和隔离实测记录：dsh-ltm 0.3.1 11/12，fooxe 0.13.6 9/9（含预期弱项）。它们的 project 或 user/project 作用域不足以直接满足 Sumika 角色隔离与来源策略；不应重装后宣称解决。实际插件模型回合未完成。|

历史评测文档顶部“MemMachine 首选”和“选择 Mem0 的原因”存在时期混合；现 RoleSession 只接 embedded/semantic，因此 **MemMachine/Mem0/Graphiti 均不是当前已启用后端**。本轮不再依据旧榜单决定安装。DSH 插件负责 Harness 生命周期接入，社区记忆库负责存储/检索/可能的抽取，二者不是互斥方案；选择任何一个都必须保留 Sumika 的来源裁决和隔离边界。可继续把 dsh-ltm 留作候选，不能把 CLI 不带 scope 的全局 search 直接接到角色。

### 三层数据：素材、规范记忆、可重建索引

**素材应与模型总结、检索索引逻辑分开保存，但不必复制到新的“原始素材大库”。** 现成领域 owner 分别保留：对话原话在 Conversations；角色卡/笔记在已有资源目录或笔记库；电脑使用在 behavior 的 events/frames/episodes/progress。保留素材的目的是追溯、纠正和换抽取器，不是默认全部注入或上传。已有聊天原话可以按现策略保留；行为素材仍限用户授权的有界特征，不能借“可重建记忆”扩大为屏幕全文、按键串或录音。

建议固定下面的逻辑契约；均属待补齐接口，不宣称已有统一实现：

1. `EvidenceRef={domain, source_id, source_revision, scope, occurred_at, evidence_kind, content_hash?}`。ID 由宿主/领域库生成；source_id 可指向会话用户消息、行为反馈、材料进度或笔记。存引用即可追溯，不复制全文。原素材已删则标 unavailable，不通过模型补写缺失出处。用户/角色回复必须可区分，不能让助手自编内容成为用户证据。
2. `MemoryRecord={record_id, scope, domain, text, source, evidence_refs, fact_key?, status, revision, created_at, updated_at, supersedes?}`。规范记忆是 Sumika 的可迁移事实/确认结果，不以向量或供应商 rowid 作为身份；status 至少 active/superseded/deleted，model proposal 始终在独立待审状态，不进正常检索。行为的 observed/inferred/user_confirmed 继续保留领域含义，不能转成通用“真事实”。
3. `IndexEntry={record_id, record_revision, content_hash, engine_id, model_version, index_generation, ...}`。FTS、embedding、检索图边/排序缓存都可从当前有效规范数据重建；用户手写关系是规范事实，模型抽取的关系图是派生索引或待审候选，不能混为一表真值。删除 embedding 不丢事实；换模型必须重建对应 generation，不能沿用旧维度或旧文本向量。

当前 `memories` 已有大部分事实字段，但没有稳定跨导入 record_id、通用 EvidenceRef、revision/CAS 和独立 repository；`event_id` 是来源事件幂等键，不总能代替稳定记录身份。当前 JSON restore 可能重分配本地整数 id，provider 不能把这个 id 当外部永久引用。当前 `relations` 也没有逐条稳定 id、revision 和完整来源事件，需要在迁移契约中明确补齐，不伪称现导出已经满足新格式。

### 可替换接口：先封装现代码，再接候选引擎

将来源审核/提议生命周期放 Sumika 领域层，规范数据继续复用现 SQLite；先把 `memory.db/_scope` 直连移进现 repository 适配，不先大搬库。最小接口：

```text
MemoryRepository:
  upsert(record, expected_revision, host_event)
  get/list(scope, filters, cursor, limit)
  supersede/delete(scope, record_id, expected_revision)
  put/list/resolve_proposal(scope, proposal, expected_revision)
  export/import(snapshot, scope, mode, deletion_policy)

RetrievalProvider:
  capabilities()                    # scope/source过滤、更新、删除、版本等
  index(records, generation)
  remove(record_ids, generation)
  search(query, scope, sources, domains, limit, generation)
  rebuild(snapshot, target_generation)
  health()
```

检索返回 `record_id/revision/rank_score/score_kind/engine_id`，正文和许可由 repository 当前状态复核后提供；不信任 provider 自带的“用户确认/置信度”。作用域过滤必须在候选检索时生效，不能先全库 topK 后过滤冒充完全隔离召回。source/domain 过滤与预算是宿主决定的，模型不能改 scope。

第一版 embedded/semantic 都实现此薄接口；不是另写检索算法。现语义分数是余弦/子串混合排名，不能展示为事实正确概率。没有支持的能力直接声明 unsupported，不暗中全量加载或自动换引擎。将来成熟社区引擎若同时提供抽取，抽取结果也只能进 proposals；不让其自动把完整对话或角色话术加入 canonical 事实。

DSH 侧只接 native lifecycle/工具/MCP 薄适配，领域层不 import DSH，不修改上游；未来更换 Harness 时保留 repository、provider 和数据。当前本地实现已能用，所以不以“等找到更成熟引擎”为由停掉行为主线。

### 纠正、删除和重建：当前缺口与最低门槛

当前 forget/按键更新主要将记录 active=0；搜索过滤 active，但文本可能仍在事实历史、FTS、embedding 和导出里。Conversations.clear 保留恢复副本。**“不再召回”“清空聊天上下文”“删除素材及派生数据”是三个不同动作**，界面和 API 不得混称。历史手动备份也不会随日常删除自动清除。

待实施的治理规则：

- 纠正以 expected_revision 原子提交新版本，使旧版本不可召回，派生缓存失效；外部索引延迟时，宿主 hydration 必须排除旧 revision。删除保留不含正文的 tombstone/事件幂等信息，禁止从旧导入或重新抽取自动复活。
- “遗忘这个事实”保留素材时，写来源/事实级 suppression，后续重新抽取同一来源不得恢复已遗忘事实；用户明确重新声明是新事件。单纯删向量后从聊天全文再抽取不能算删除成功。
- “删除素材及其派生结论”沿 EvidenceRef 找依赖；只由该来源支持的派生结论失效，多来源结论去除该来源后重新核验，不一刀切删除其他独立声明。pending proposals、角色上下文缓存和在途结果同样失效。
- “重建索引”只读当前 active 规范记忆，不运行 LLM 重抽素材，不改确认状态或事实内容；“重新提炼素材”是不同的显式任务，受当前提取许可、suppression 和新版本审核约束。
- 导入 merge 默认尊重删除标记和冲突版本；整库历史恢复是用户明确的恢复动作，预览指出会恢复哪些历史状态。不得为方便迁移丢掉 tombstone 后再用旧来源重灌。
- 新 generation 在隔离位置完整建立、校验 scope/删除/来源/召回，再原子切换指针；失败保留旧可用 generation。规范数据是唯一真源，provider 写失败可标待同步，不能回滚用户删除或返回旧文。

本节只确认代码有上述风险边界，不宣称已发现实际跨用户数据外泄；相应修复需有独立回归证据。

### 对当前行为升级的约束：避免未来迁移负担

`behavior-assistant-upgrade-plan.md` 的现库复用方案可继续实施。保留稳定 host event/episode/feedback ID、scope、source、时间、schema version 和引用；聚合只保存有出处的解释或现场计算，不把模型字符串塞进确定性 features。行为库负责原始有界证据与领域结论；长期记忆层只拿 reference，**不默认把每个 frame/episode、活动统计或兴趣推测都写进 memories**。

明确偏好只保留一个 owner：当前在行为管理中声明的行为偏好由 behavior note 管理，MemoryWriter 已拥有的长期偏好仍由其管理；协作上下文按 reference 读取，不双写。若未来希望真正合并共同偏好，需显式 owner 迁移和 ID 映射，不能现在以同文本去重悄悄串 role/project。行为 scope 当前是 user+project hash，未来统一检索时由宿主提供映射，不能从 hash 猜角色或把不同项目合并。

行为字段以版本化 payload + domain/source 定义，可导出为 provider 中立事件；不要存 embedding 专用字段、厂商数据结构或供应商 id 作为唯一关联。生成的活动概览不单独长期缓存，以现数据重算；纠正删除由原 owner 执行并使引用失效。这样换长期检索引擎时主要重建索引，不需要迁走所有电脑操作日志。

### 最小实施顺序与验收

1. **现在完成设计边界，行为主线继续**：统一现文档的已实现/候选状态；为行为新数据固化 ID/source/scope/version/引用；不安装或切换任何引擎。本节和行为升级计划即此步输出。
2. **下一小包先封装 repository/provider，不换默认**：改造 MemoryWriter/model_proposer/RoleSession 的 SQL 直连；embedded/semantic 走相同契约；给规范记录稳定 ID 和 revision，兼容旧整数 ID；旧导出导入映射有测试。迁移前备份，新增字段默认不编造缺失出处。
3. **补治理再做可重建索引**：分别测试遗忘与彻底删除、纠正、proposal 状态、删除抑制、版本过滤、索引清空重建、模型版本变化、旧快照 merge 不复活。保留现聊天 clear 恢复行为并准确命名，删除新语义不能偷偷改变用户既有备份。
4. **最后才对照候选**：复用现中文14例并增加否定/纠正、跨角色/项目、用户与角色同名、来源缺失、删除后重建、长时偏好变化。候选在隔离副本测相同数据，记录真实延迟/成本及额外依赖；通过后再决定是否启用。零模型调用的检索测试不能算事实提炼/角色质量验收。

最小验收：同素材→同规范记录→两检索适配返回合法同 scope/source；用户原话/助手内容不混；模型候选未确认不可检索；纠正旧值消失；遗忘后索引重建和重复来源不复活；彻底删除覆盖当前素材/派生/缓存；导出→隔离导入稳定 ID/关系/提议/tombstone 完整；失败索引切换不影响事实；关闭 memory 后无自动写/检索/注入；行为大日志不被全量塞入长期索引。

本轮结论无需新增用户选择即可指导 Sol 保持边界；引擎切换、上传、实际全量重提炼和素材删除不由这份规划自动执行。当前只追加本文，产品实现与实测仍按后续包分别记录。

---

状态：P6-3 / R-070 持续验收中。内置SQLite记忆已接入角色上下文；SemanticMemory与独立memory-env已有实现/环境，日用调用已补齐独立离线运行时与embedding_cache接线并完成合成数据实测，Bridge 已受管重载，工作台已恢复。当前日用选择embedded、auto_extract=false。P4 是项目需求/进度记录，不是角色长期记忆、向量检索或自动事实归纳引擎。

## 接入顺序

1. 先找能稳定使用的现成方案：优先 DSH 社区插件；没有合适且高质量的插件，再用独立适配接入开源库、MCP 或服务。先做必要的兼容性、来源隔离及导出恢复验收，建立可用基线，不先自研记忆算法。
2. 在真实中文使用过程中建立固定评测集，再比较候选；重点选择实际效果和能力更好的实现，不把首个方案永久写死，也不将厂商榜单当成 Sumika 实测结果。
3. 保留独立适配接口和可导出数据，后续替换引擎只调整适配层与数据迁移。迁移先备份、导入隔离实例并验证，保留回退路径。

独立层仅做必要的写入、检索、更新、删除和导入导出适配；存储、检索、事实归纳优先由现成引擎提供。不修改 DSH 上游源码，不引入另一套 Agent 循环代替 DSH。memory.enabled 已接入设置 → 数据与存储；关闭后停止聊天自动记忆写入、检索和注入，保留已有数据与显式管理入口。旧配置默认保持原有检索行为；auto_extract 仍默认关闭。

## 待验证候选

本轮只检查了 README 与当前 DSH 安装包，未安装、调用模型或评定效果。当前锁定安装中未发现命名为 memory/mem0/graphiti/zep 的 DSH 包；这不说明社区没有相应插件，实施时仍须检索并核验。

| 候选 | 值得验证的方向 | 接入前需核对 |
| --- | --- | --- |
| DSH 社区记忆插件 | 接入原生生命周期的成本较低 | 维护情况、当前版本兼容、底层引擎、来源与多角色隔离、数据迁移 |
| [Mem0](https://github.com/mem0ai/mem0) | 用户/会话/Agent 记忆、偏好与事实检索 | 开源版和托管版的功能/效果差异；不能将 Agent 生成内容自动当成用户事实 |
| [Graphiti](https://github.com/getzep/graphiti) | 时序事实、关系图、事实变化及来源追溯 | 额外数据库和运维成本、中文抽取质量、延迟及角色隔离 |
| [claude-mem](https://github.com/thedotmack/claude-mem) | 自动观察、会话摘要、分层记忆检索 | 能否适配 DSH；观察器费用、数据去向、本地部署和导出能力 |

Letta 等带有自身 Agent/Harness 的完整系统可以作为研究参考，不能为了复用记忆而默认引入第二套工作循环。任何托管服务注册、付费或上传数据都不由“优先现成方案”自动授权。

## 选择依据

- 中文回忆：跨话题、间隔多轮后的准确召回，不能只测刚出现的关键词。
- 事实更新：旧事实被新事实修正后，区分当前状态与历史状态；支持纠正、删除和遗忘。
- 来源与误召回：区分用户陈述、角色设定、模型推断和工具观察；不知道时不编造记忆。
- 多角色/用户/项目隔离：明确作用域，避免一个角色记忆进入另一个角色或开发项目。
- 延迟与成本：记录写入、提取、检索和额外模型调用的真实成本；不暗中切换提供方。
- 迁移：可导出、可恢复，可追溯原始来源；换引擎后用同一评测集复验。

开发工作时，记忆上下文作为单独的来源块提供，不改写需求原文、代码、diff 或成果正文。项目任务的完成状态仍以相应证据为准，不能从角色记忆或自动摘要推断授权和验收结果。

## 可选模型提议接线

设置 → 数据与存储中可开启“模型记忆提议（需确认）”，默认关闭。同一次角色生成附带候选，不另发提取请求；角色管理中核对原话并确认，才进入可检索记忆。独立于规则自动提取开关；memory.enabled关闭时两种自动路径均停止。沿用现有角色模型路由，不继承工作模型、不付费fallback。实现与浏览器接线已验证，真实本地模型质量验收见 desktop-integration-execution.md 最新记录。

## 2026-10-17 当前执行点

真实settings绑定的Mnemon可选只读Source与原生wrapper已在隔离SDK/DSH宿主验证，未启用日用。保持现SQLite规范事实与素材owner；真实Agent回合及取消已验证，下一步按同一中文与治理集对照候选检索provider。长期愿景不实施。最新1294项回归OK/23跳过；配置、证据与限制见 `acceptance-20261017-memory.md` 顶部和 `extensions/memory/README.md`。关系逐条CAS已完成，素材物理purge未完成。
