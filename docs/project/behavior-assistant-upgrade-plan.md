# 行为助手闭环：本轮有界升级计划

## 行为子记忆至角色参考链路补验（2026-10-17）

复用既有行为许可、声明管理、角色输入框和参考拼接代码，不修改产品或新增控件。新维护验收`tools/verify_behavior_reference_ui.mjs`改造现有隔离Bridge/SQLite/Edge/本机合成模型框架，记录真实HTTP模型请求；只有测试角色发现列表为API夹具，声明/许可/聊天都走真实接口。

源码与r4包内Python/产品导入各6项通过：关闭记录仍可管理声明；未授予参考许可不注入；只开参考许可即可注入明确声明；纠正后只注入新内容并保留negative态度；暂停抑制、恢复后遵从已保存许可、再次关闭停止注入；删除后下一请求不含旧/新声明。每轮7次本机合成模型调用、0外部调用、0页面错误；全程未开启记录。源码截图已查看。证据`.sumika-next/acceptance-20261017/behavior-reference-final/report.json`与`E:/SumikaBuild/acceptance-20261017-current/behavior-reference-r4/report.json`。

逐项手测：设置→数据与存储→行为子记忆→添加偏好或目标→保存声明；设置→连接与权限→行为观察许可→只勾“允许参考行为记忆”→保存行为许可；回活动室聊天。再回声明行“更正”修改内容/态度，或“删除”并确认；后续角色参考应更新。暂停/恢复与关闭参考也在同一许可区。此链路证明参考传递，不证明真实模型理解质量、罕见操作主动询问或RawInput硬件采集；未开启日用采集。r4仍不含后续任务交接接收修复，最终包须重建复验。

日期：2026-10-17。状态：本轮软件已实现与自动化验收，范围差异和真实设备限制见 acceptance-20261017-behavior.md；下方规划正文保留为交接依据。Astra 负责规划统筹，Sol 负责实施。本文核对当前工作树（含既有未提交修复），不能据历史验收重放或覆盖这些变更。

## 1. 本轮目标和授权

把已有“记录→反馈→派生参考”升级为可日用的通用活动与记忆闭环：详细保留授权范围内的电脑使用特征；能查看每天用了哪些应用、何时使用、怎样切换与操作；复用可靠材料进度和用户笔记引用；新来回/操作序列能找到相似场景的真实用户解释；用户能看懂、更正、删除自己的习惯与明确兴趣；角色引用时区分观察、历史解释、当前推测和明确偏好。用户随后强调“更通用、丰富数据类型”，因此本轮不是 PDF 专项，也不把兴趣功能等同于手填表单。

主 Agent 已转达用户批准：在现有“设置→数据与存储→行为子记忆”中加入日常统计、已确认习惯/兴趣及逐条纠正控件，不加导航。既有连接与权限、陪学详情和活动室消息流继续复用。新增画像页面、自动跨软件主题挖掘不在本轮。

不扩大到屏幕全文、截图历史、原始按键、剪贴板、音频长期保存；不部署或启用模型；不推送、安装或发布。无需等待局域网 LFM 才能实现本轮闭环。

## 2. 已有资产与核对证据

|资产|决定与用途|
|---|---|
|`extensions/behavior/library.py`（schema 5，events/frames/episodes/prompts/feedback/patterns/progress）|改造后使用；唯一行为库，复用来源、revision、epoch、删除、迁移和导出，不另建画像数据库|
|`extensions/behavior/runtime.py`|改造后使用；唯一采集/前台/序列监督者，加前台切片和当前匹配查询，不加后台常驻程序|
|`extensions/behavior/sequences.py`、`prompts.py`|改造后使用；保留有界序列、冷启动支持门槛、询问配额与过期状态机|
|`extensions/behavior/permission.py`|直接复用持久四开关及 revision lease；暂停/撤销启动不恢复|
|`ui/server.py`、`ui/app/management.js`|改造现有管理动作、行为参考注入、许可区和数据区|
|`extensions/memory/write_policy.py`|直接复用其来源原则；不把行为推测写成长期事实，不自动复制明确偏好建立双真源|
|`ui/prototype-d/index.html` 约 957/1040/1063 行；`docs/project/ui-design-coverage.md`|原设计对应陪学详情、连接权限、数据存储；本轮统计/兴趣行是用户新批准的原区域扩充，逐屏核验后更新覆盖表|
|`tests_next/test_behavior_*`、`test_input_process.py`、`test_session_coordinator.py`、既有 UI 脚本|扩展主链和治理回归，沿用假时钟、隔离 SQLite 和假设备|
|`docs/project/behavior-memory-plan.md`、`acceptance-20261016.md`、`phase-07-local-model-plan.md` 顶部|前者给契约；验收后补充比早期 A-02“未接线”结论新；模型实测不支持默认启用或自动 fallback|

现场缺陷（行号是规划时定位，应按函数复核）：

1. `library.py:1071 habit_summaries` 只 JOIN feedback/prompts，按 `(kind,label,role)` 汇总最近 200 条；没有读取 patterns 或 episode 的真实场景。`confirmed=True` 与 `inferred=True` 同时返回，容易把“历史回答已确认”误读成“当前意图已确认”。支持率分母混合相同 kind 的不同场景。
2. `runtime.py:401` 命中 confirmed pattern 时只是跳过询问，没有返回该次操作的解释；`ui/server.py:1037 _behavior_reference` 调用无当前查询的全局 `context` top3。历史“比较定义”可能与当前“找公式”的操作无关，却占满上下文。`confirmed_patterns` 返回的是签名，不是可靠程度或标签分布。
3. `_refresh_patterns` 只把有一个有效反馈的签名激活。active 是“有可用解释”，不是稳定习惯；不能据 active 停止所有后续纠正机会。普通阅读事件反馈也可能无 episode，不能简单强制 JOIN patterns 而丢失这些有效来源。
4. `runtime.py:_record_progress` 已核验可靠 PDF/B站位置、新鲜相邻观察与去重，但只 upsert 最新位置/累计有效时长。它既不是全应用使用日志，也不能反推过去每天/小时分布。`EVENT_KINDS` 已有 app_focus，却未形成日常前台时间切片。
5. `management.js:800` 查看数据会全量 export 并输出 JSON，更正要求手填 feedback ID，只有删除全部。长期高频数据下不可日用；现成管理区域已有批准，适合直接替换为分页可读行。
6. `ui/server.py` 的公开 `feedback` 动作接受调用者 `user_event_id`，`progress_record` 接受调用者来源；与“宿主决定证据”的原则不一致。新增接口不能沿用此漏洞；生产 UI 应只走宿主绑定动作，测试通过库接口造夹具。
7. 当前 `_behavior_scope` 是 user+project 的 hash，只有同项目内通用反馈跨角色共享。本轮保留这一隔离；不能悄悄把旧项目私有历史合并为跨项目总画像。UI 标注当前项目统计范围，跨项目通用画像另行设计。

## 3. 实施决定：复用现表，增加版本化负载

本轮不新增独立画像表。复用 events 两个已有 kind；用受控 `source` 和闭合 features schema 区分用途。episodes.features 增加有限场景字段。已有无这些字段的记录不补造历史。若实现需要新增索引，走现 migration 机制；不以改版本号代替真实迁移校验。

统一使用现有事件 envelope（event_id、宿主 user/session/epoch、时间、kind/source、app_category、opaque target/material、features），source+version 决定 payload validator。不是任意 JSON 数据仓；新类型必须注册有界 schema、来源和删除关联。首批数据面覆盖：前台应用/时间/切换、既有键鼠语义特征、操作序列与用户解释、可靠材料最近位置/有效观察时长、明确兴趣偏好、已有显式笔记的引用。既有帧继续保存丰富计数/滚动方向/快捷动作类别，不为日报复制一遍原帧；按已保存来源派生摘要，避免多库不一致。

实现可新增 `extensions/behavior/activity.py` 放纯 schema/切片/聚合辅助，事务和权限仍由 library/runtime 现有 owner 执行；这是现领域模块拆分，不是并行实现。

### 领域记忆边界与协作检索

行为子记忆是领域记忆，不接管全部长期记忆。原始活动是证据，用户解释/统计模式是有来源的领域结论；学习笔记仍归现学习/笔记模块，角色互动私有事实仍归角色记忆，用户明确“记住”走现 MemoryWriter。逻辑分域不要求各开数据库，更不要求把相同偏好复制到两库。

本轮由现宿主上下文组装边界协作检索：`request={host_scope, role_id, task_kind, current_activity_query, limit}`；每个领域只返回 `{domain, source_id, evidence_source, status, summary, observed_at, scope, revision}` 的有界 reference。行为域不读取其他 role 的私有记录，不透传原始帧；笔记只交付已许可的引用/摘要；共同偏好如已有 MemoryWriter 真源，仅引用其 source_id，不重复建立行为声明。新增行为区域明确声明的行为偏好以本库 note 为唯一真源，不同时自动写长期库。

删除/更正路由回 source 所属领域，再使组装缓存失效；其他领域持有的引用失效后不继续引用。模型文本永远不能把 reference 升格成用户指令或授权。统一组装保留独立来源块与每域预算，不把行为摘要混进用户原消息。跨域语义合并、全局偏好迁移不在本轮；已有资料可引用、无法可靠关联则为空，不强行统一。

概览的通用条目包含 `record_type/source/observed_at/context/evidence_refs/status`；其中 status 只可 observed、inferred、user_confirmed、user_declared，derived 另用 derivation_version 标统计方法。来源引用可回到当前库记录或既有笔记 ID，不能带正文副本。新类型跟同一分页、导出、删除路径走，不为游戏/办公/学习各建一套画像。

### 3.1 前台使用切片

宿主内部 `record_activity_slice(...)` 最终调用同一库事务，写：

```text
events.kind = app_focus
events.source = foreground-v1
target = 现有 HMAC/不透明窗口身份；无标题/路径/URL
app_category = 宿主已知类别或 unknown（不是模型真值）
features = {
  slice_version: 1,
  started_at: ISO UTC, ended_at: ISO UTC,
  effective_seconds: 有限非负数,
  app_name: 规范进程 basename，最多128字符,
  profile_id: 当前有效模式ID或空串,
  local_date: YYYY-MM-DD, utc_offset_minutes: 整数,
  quality: verified_foreground
}
```

由 `BehaviorRuntime.tick` 对相邻已核验前台身份累计，间隔必须 `0 < dt <= 3s`，采用单调时钟时长；UTC 仅用于记录日期。每 60 秒封口，切应用/模式/会话、时区变化、整点和本地午夜封口，以免把跨时段全部归入最后一天。目标不可用/锁屏/排除应用结束并不补算间隙。前台身份可信而焦点内容未知时只保留进程/时长粗统计，另标 `input_quality=unknown`，不补写细粒度键鼠或主题；密码焦点遵从现有细粒度暂停，不从该窗口提取内容。屏幕采集不可用不应阻止已被独立核验的前台粗统计，反之也不能把旧截图当新心跳。

重复 tick/重复帧不能加时；新 session/epoch 不接上次运行。记录入口只能由宿主赋 event_id/scope/session/source，使用 permission recording lease。暂停/撤销时丢弃尚未合法提交的暂存段，不借 flush 写入已失效许可。正常停止在许可仍有效时有界封口。崩溃最多丢当前未提交段，状态如实展示。

这个值叫“已观察前台时长”，不叫“有效学习/专注/人实际在场”。用户不输入不能断言离开。不得用 n-gram 多条 episodes 时长相加计算使用总时长，否则一个操作片段被多次累计。进度继续保留原可靠材料位置；本轮不从 usage slice 编造“学了什么”。

### 3.2 明确兴趣声明

复用 events(kind=note, source=user_declaration-v1)，features 闭合为 `{declaration_version:1, topic, polarity, role_id}`，topic 去首尾空白、非空、最多128字，polarity 仅 `like/dislike`，role_id 由宿主选择的作用域提供或空串（当前 user+project 内通用）。event_id、source、时间和作用域均由宿主生成。用户在表单显式填写才写入；不能把模型建议、角色回复、页面文本、历史操作自动塞入该入口。

同一范围 `(normalized_topic, role_id)` 只有一条当前声明。首轮规范化仅 Unicode NFKC+首尾空白，不做同义词/语义合并。更新提供当前 record_id+revision，事务内创建替代事件并撤去旧有效事件（复用删除标记/epoch机制），保证旧 polarity 不再召回。旧原话无需永久保留以免违反用户纠正/删除意图。重复同内容幂等；冲突返回409。删除是删除该声明，不等于“不喜欢”。

这里表达的是明确偏好；同时交付由使用记录自动产生的 `activity_affinity` 候选：最近7/30日按已观察应用/已知活动类别汇总独立日期、session、时长、切换次数和原始来源数，至少3个有记录的日期才列“持续活动参考”。其含义是“近期反复使用/关注的活动”，始终 inferred，不把工作任务断言为喜好，不从浏览器进程名猜网页主题。无可靠语义类别则保留应用名。角色可说“最近几天你经常使用 X”，不能说“你喜欢 X”。

候选不另存表，不贡献 confirmed 支持。可在既有行为询问流按配额询问该活动的含义，用户回复仍保存原解释；只有用户明确表达喜欢/不喜欢并通过已批准控件确认才生成 user_declaration。表单只是明确声明的一个入口，自动活动参考和既有解释检索才是无需手填即可工作的主线。本轮不实现自动屏幕主题抽取；可信现成材料类型/显式笔记关联可提供范围，模型自编主题不能进入声明。

### 3.3 相似操作解释与稳定习惯

扩展 `habit_summaries(..., query=None)` 和 `context(..., query=None)`，宿主生成 query：`{kind/signature, profile_id, app_category, detector_version}`，不接受网页指定当前证据。episode 与 reading event 创建时把当时已知 `profile_id/app_category` 写入闭合 features；当前场景信息缺失则标未知。

匹配 v1 采用确定性过滤，不引入 embedding/LLM：

- 先作用域/role 过滤，再精确 kind 或 signature、detector_version 匹配；已知 profile/app 类别冲突就排除。
- 精确匹配当前上下文的来源进入支持率计算。只部分字段可用的记录作为 `match_quality=partial` 弱参考，旧无场景记录 `legacy`，单独展示，不混入精确组稳定性分母。
- 序列证据须能通过有效 episode→有效 feedback 找回；patterns 作为候选及 active 索引核验，不把 pattern.sample_count 当用户确认数。阅读事件走有效 event→feedback，不要求凭空造 episode。孤立/已删证据不召回。
- 相同真实 episode（多个 n-gram 行共享的基础 episode 身份）最多一票；事件型反馈按真实 event 一票。原有 episode ID 可解析的宿主前缀用于旧样本去重，新样本明确保存 bounded `base_episode_id`，不能由相似文本猜同一事件。
- 同一真实来源最后有效纠正替换旧标签。不同 episode 的不同标签都是反例分布，不全局覆盖。最多 200 个最新有效独立样本，输出窗口限制及截断标识，不能宣称全历史概率。
- 权重 `2^(-age_days/90)`；支持率是该精确匹配组内该标签权重/全部有效标签权重。稳定条件沿用同标签至少3个独立样本、跨2个真实 session、支持率≥0.8。UI显示次数和比值，不命名“模型置信度/准确率”。一次确认仍可弱参考。

返回条目统一来源语义：

```text
label; evidence_source=user_confirmed; current_status=inferred;
match_quality=exact|partial|legacy;
sample_count; session_count; weighted_support; support_ratio;
stable; source_ids[<=3]; source_total; window_limit=200; truncated;
signature/kind; profile_id; app_category; last_confirmed_at
```

兼容旧 `confirmed` 字段时必须解释它只修饰历史证据，新 UI/模型块不用这个歧义字段。明确兴趣用 `evidence_source=user_declared_preference`，前台统计用 `observed`，不可共用“已确认当前意图”。

runtime 在新来回事件/结束的序列得到当前 query，召回最多3条。角色当前问答只使用该 query 的参考；无当前动作时可以返回明确偏好及清楚标注的最近观察，不默认塞与当前无关的热门历史解释。`use_memory=False` 必须完全停止上述注入。

不要因签名存在一条确认就永久禁问：精确且稳定的匹配不主动重复询问；不稳定/部分匹配按既有候选门槛、每日次数和10分钟围栏允许再次询问。不自动说“你现在就是在找公式”；没有确认路径就保留推测。所有展示候选继续携带 prompt_id；纠正/删除使当前缓存、pending 和在途上下文失效。

## 4. API 与 UI 最小落地

沿用 `/api/manage/behavior`，action 为闭合白名单：

|动作|输入|返回/约束|
|---|---|---|
|`daily_summary`|days 默认7，1..31|当前作用域，每日/小时/应用的 observed_seconds、切片数、source、数据覆盖起止；缺失期不补0冒充观察；排序稳定|
|`activity_overview`|days 默认7，1..31|同一数据源派生应用切换、语义操作类别计数、activity_affinity、可靠材料最新进度与已有笔记引用；返回各项质量/覆盖，缺来源的项为空|
|`habits`|cursor/limit（默认20，最大50）|可读来源、范围、稳定性、反馈ID及用户原解释；管理查询不冒充当前意图|
|`interests`|cursor/limit|当前明确 like/dislike 声明；不显示模型输出为已确认兴趣|
|`declare_interest`|topic/polarity、可选被替换record_id、revision|宿主身份、用户提交绑定；成功回读当前声明|
|`correct`|已有 feedback_id/corrected/revision|复用单次反馈纠正；重算相关派生并取消旧上下文|
|`delete`|明确选中事件/声明/反馈ID、revision、confirmed|扩展现删除 selector 支持反馈精确删除；返回各表影响数量，不把删除单条扩大为全部历史|

原 `list` 需要支持集合类型（events/feedback/episodes 等）后端分页；不能为了渲染概览调用全量 export。导出仍是独立显式动作。删除字段在 API 和 library 层逐一验证；不能让浏览器直接选择 scope/source。公开 `feedback` 改为宿主映射或拒绝外部身份字段，`progress_record` 改为宿主内部；生产 UI 未调用的调试写入口不保留为模型可造事实路径。`prompt_feedback` 由宿主生成 user_event_id，并保留用户输入为 original/corrected，不把模板候选伪装成用户原话。

UI 只改已有行为子记忆区域：顶部可读7日概览（应用、时段、切换、操作类别、最近材料进度）；原“查看分层记录”变分页列表；同一行显示来源/范围/最后确认/样本数，提供更正或删除；兴趣表单和自动“持续活动参考”就在此区，二者状态明确区分；保留迁移、导出、全部删除及容量状态。禁止新顶栏、侧栏、工作台面板。统计文案显示“当前项目”“已观察前台时长”；兴趣独立标“你明确告诉我的偏好”，习惯标“根据你过去解释的参考”。进度保持“最近观察位置”，不显示掌握率。

设计覆盖表登记批准的新增控件；至少检查设置数据、权限、陪学详情、活动室消息流四处，截图对照原设计相同容器和主题。无需将本轮无关的旧覆盖缺口全重做。

## 5. 持久授权、失败和数据治理

沿用 recording/use_memory/questions/startup_resume 四开关，不另建授权系统。当前用户已授权详细行为功能开发，不意味着代码迁移自动打开用户关闭的设置。现有明确保存的许可可恢复；paused/revoked/损坏/目录丢失仍失败关闭；恢复绑定新前台和 session/epoch。自动记录/派生学习由 recording 控制；人工纠正/删除和用户明确声明是独立显式管理动作，允许停录时执行，前提库可用、空间足够且 revision 正确。

events 新来源自动纳入现 export/迁移/备份/删除；检查工具是否硬编码旧字段或表，不能声称自动覆盖。统计和习惯优先查询实时源数据，不增加持久缓存；若有内存缓存键含 scope、revision、behavior_epoch，任何更正/删除必须使其失效。删除/correct 与提交原子序列化，旧模型/前台回调按 token+epoch 丢弃，重启不复活。

磁盘满暂停新增，不自动删历史，不换目录或无限缓冲；损坏行在读取时跳过并记录质量计数，不能用 NaN/负数混进统计。前台失去可信质量时停止该段；分类器未知仍可记录已验证进程粗信息，不猜应用主题。

局域网 LFM 当前仅短任务条件可用且角色事实一致性未过。此计划不依赖其 JSON、意图推断或话术；无模型、断网时记录/统计/反馈/习惯检索/明确兴趣照常，角色模型不可用就不发角色消息。不得自动回退云、本机其他模型或后台开服务。将来模型适配须独立验证 schema、finish_reason、来源与迟到结果，不混入本轮完成声明。

## 6. Sol 最小实施阶段与完成条件

1. **库契约与来源**：添加两种 events source 的闭合校验及内部写方法；明确兴趣增改删；分页和统计；修正习惯匹配/去重/分数语义。先用假数据验证多应用、跨日、反例、角色/项目隔离、删除和旧库兼容。此阶段不启动设备。
2. **唯一 runtime 接线**：前台切片累加、current query、稳定/不稳定候选区别；接回角色参考和既有询问流；冻结/清除旧在途结果。模型关闭状态必须通过端到端假设备用例。
3. **已批准 UI 与管理闭环**：同区域可读统计、分页来源、明确兴趣、逐条纠正/删除；宿主可信写边界；主题/窄窗/零横向溢出/零控制台异常及唯一入口验收。
4. **收尾**：运行改动相关回归与项目 check/handoff，更新 acceptance、progress、handoff 和覆盖表。记录实际命令及通过/跳过数。只有前三步全部通过才称“本轮软件闭环完成”。真实设备、长期质量、候选安装分开列，不借假设备结果宣称日用实际采集已验收。

必要验收断言：

- 假时钟连续应用A→B→A得到精确无重叠时长及2次真实切换；60秒封口不是切换；重复tick不增长；3秒以上缺口、暂停、锁屏不计；未知焦点仅粗统计且不出现细粒度标签；跨午夜/整点/时区变化正确切分；单调时钟不被墙钟回拨污染。
- 关闭 questions 仍合法记录；关闭 use_memory 零注入；暂停/撤销重启仍停；旧一次性许可不转持久许可；在途片段不迟到落盘。
- 同类新来回操作正确召回本场景“找公式”，另一模式“比较定义”不混成其支持率；单例是弱参考；3次/2session/80%满足稳定；多n-gram不刷票；更正一票立即改变分布。
- 阅读事件无 episode 的合法解释仍可检索；孤立 feedback/已删除源不召回；旧无场景样本仅 legacy；当前推断始终 inferred。
- 明确喜欢→纠正为不喜欢→重启仅召回新声明；删除仅移除所选；同主题不同 role 不串；助手自编“绿茶”永远不能进入 user_declaration；user/project scope 从宿主得到。
- 统计不累加 episode n-gram时长，不从 PDF 总时长编过去每日；数据不足显示不足；模型全部关闭仍完成统计和反馈链。
- 输入帧动作计数按原来源去重，未知/截断质量单列；三日重复活动产生 inferred 候选但不增加兴趣声明或确认数；浏览器长期前台不能推出“喜欢某网站”；现成进度/笔记仅在有可靠来源时显示，不复制正文。
- 分页浏览不读取全部 frames/export；个人数据迁移和多根备份包含新负载；选择性删源→派生/上下文/pending清除→重启不恢复；revision 冲突不部分写。
- UI 无新增导航，原生能力保留；实际点击概览、逐条纠正、删除及权限变化后的状态回读，四处截图与覆盖表一致。

建议命令（实施者按实际测试模块补齐，不在规划阶段运行）：

```powershell
python -B -m unittest tests_next.test_behavior_library tests_next.test_behavior_runtime tests_next.test_behavior_evidence_lifecycle tests_next.test_behavior_baseline_recording tests_next.test_behavior_permission tests_next.test_behavior_prompts tests_next.test_behavior_sequences tests_next.test_ui_server
python -B -m sumika_next.cli check
python -B -m sumika_next.cli handoff
git -c core.safecrlf=false diff --check
```

回退：保留改动前代码 diff 与库迁移备份；关闭新增 runtime 写入即可停止新增来源，已有数据不删。若修改数据库 schema，恢复到独立目录验证后按现 locator 切换流程回退，禁止把旧库覆盖在线新数据。本轮计划仅改本文；未运行采集、模型请求、产品测试或提交。

## 7. 留给主 Agent 的范围决定

没有阻塞本轮的产品决定：用户已批准原区域 UI 扩充；按以上通用事件契约、活动概览、确定性匹配、自动活动参考和明确声明直接实施。跨项目全局画像、自动主题兴趣发现、模型提供语义标签、安装/发布不纳入本轮。本轮若无法可靠取得密码/安全焦点质量，应先交付已核验前台身份下的粗统计并明确输入质量缺口，不能为赶完成把未知输入记为可信；由主 Agent 决定是否将真实设备质量验收追加为独立后续步骤。
