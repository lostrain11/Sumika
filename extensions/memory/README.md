# 长期记忆适配边界

事实唯一真源为现 `EmbeddedMemory` SQLite；`repository.py` 管身份、版本、来源抑制及生命周期，`retrieval.py` 校验候选并读取规范正文。领域素材留在各自 owner，不迁入平行素材库。

## Mnemon 只读 Source

`mnemon-source.mjs` 的 `createCanonicalSource(sdk, host)` 接受公开 SDK，不在模块内部安装依赖、启动进程或加载 provider。尚未注册到日用客户端；真实settings绑定与原生Agent的隔离接线已验，尚未启用日用或提供Mnemon选择UI。

可信宿主必须提供：

- `resolveBinding(mnemonScope)`：未知或未授权 scope 返回 null；合法返回 `{bindingId, epoch, enabled, user_id, role_id, project_id}`。不能使用模型输入的角色/用户映射。`enabled` 必须读取当前记忆开关。
- `epoch`：宿主生成的会话绑定代次。角色/项目切换、关闭后重开、配置重载、历史文件恢复均必须更换，不能复用旧值。关闭期间仍须让 resolver 返回 unavailable，不能仅改 epoch。
- `revision(binding, {signal})`：读取该 scope 的持久化仓储版本；不调用模型。
- `search(binding, query, {signal, limit})`：调用现 `MemoryRetrieval.search`，按 binding 中可信三轴映射，返回最多5条经规范库重新读取的事实。不得直接转发第三方 provider 正文。宿主拥有超时、取消与子进程清理责任。

Source 无写入/动作能力。grant 使用绑定摘要和版本，查询前后复核作用域、开关、版本及取消；改变则丢弃本批结果。正文预算2000字符。传入回调是进程内信任边界，Source不能替宿主验证回调是否偷偷跨scope读取或外发。

验证：`python -B tools/verify_mnemon_memory_contract.py` 使用合成 SQLite 和真实 Mnemon0.5.29/Cordis4.0.4；`python -B tools/verify_mnemon_host.py` 验独立DSH rc.2宿主。需要现 `.sumika-next` 候选依赖，不能据此自动安装日用插件。

## 可信设置宿主与可选原生插件

`mnemon-host.mjs` 复用当前角色模型 settings，`mnemon_bridge.py` 复用 `settings.validate`、`open_session(for_chat=True)` 和 `MemoryRetrieval`。不增加事实库、不复制原始对话。读取仅接受 op、配置摘要和有界 query/limit；用户、角色、项目、数据库路径均来自可信设置，不能由路由输入覆盖。关闭记忆及非法请求在打开数据库前拒绝。

`dsh.mjs` 是可选的原生注册适配，配置示意如下（须使用本机已核验的绝对路径）：

```json
{
  "enabled": true,
  "python": "D:/Tools/python/Python314/python.exe",
  "sdkEntry": "<reviewed dsh-mnemon>/lib/extension-sdk.js",
  "storage": "workspace",
  "projects": { "<absolute existing workspace>": "<absolute existing role settings.json>" }
}
```

DSH Mnemon0.5.29 的 `agentScope` 使用配置的 storageScope 和 resolve 后的 session.header.cwd。此宿主默认严格匹配 workspace，不接受 global/workspaces；显式 custom 也必须与 Mnemon storageScope 配对。projects 键和值均 realpath，工作区必须存在，未知工作区不提供内容。上游应显式选择 `sumika-read-only` 策略，并关闭写入/自动摄取/同步；仅注册此 Source 不代表上游其他 Source 已关闭。

Node 侧设置或 role.json 字节摘要/mtime 变化会刷新 epoch，回包前再次核验；Python 同时复核配置、实际加载的角色 scope 与仓储版本。旧配置缺 memory.enabled 时遵循现有默认 true，显式 false 停止读取。宿主重载和历史恢复必须调用 invalidate 或重启插件；无法据文件时间保证未观察到的任意 ABA 操作。

插件卸载通过 Cordis effect 清理自有子进程；查询支持 AbortSignal、15秒超时和输出预算。Python CLI仅返回通用错误，避免泄露路径和provider诊断。复用 semantic 时仍可能启动现有 embedding运行时；本轮合成验收只用 embedded，不证明语义模型离线可用。

本轮验证：6项Python桥测试（含7项真实Node/公开SDK契约）通过；真实独立DSH宿主5项通过，证据 `.sumika-next/mnemon-host-4dbfb35be0b34ba893ec446f941aac1c/report.json`。宿主工具现加载此真实 wrapper，替代原固定scope夹具。合成数据、零模型调用、日用配置不变；真实Agent回合、日用启用和检索质量对照仍待验。

## 接续验收状态（2026-10-17）

真实DSH Agent/宿主10项通过，证据 `.sumika-next/mnemon-host-06f6afeeaeb443a4bab12f2320de1b17/report.json`；6次loopback确定性夹具调用，外部模型调用0。覆盖原生路由召回、无写动作、关闭、撤回旧offer、取消和禁用重启。上一节5项/Agent待验是此前阶段；本轮不证明检索质量提升或日用已启用。关系逐条CAS已接既有管理UI，真实Bridge浏览器4项通过。全量1294项OK/23 skipped。素材物理删除仍未完成。

## 当前素材彻底删除：离线维护入口

`extensions/roles/material_purge.py` 复用 Conversations 与规范SQLite，不建平行素材库。前端“清空聊天”仍保留恢复副本；“遗忘/纠正”仍保留事实历史。**彻底删除目前只有CLI，没有UI按钮**，仅按当前配置角色/user/project下明确的用户message ID操作。

先从当前角色的历史接口取得用户消息ID（`/api/role/chat/history?session=room-<role_id>&role_id=<role_id>&limit=60` 的 `messages[].id`，只选 `who=me`、结尾 `:user`）；历史翻页使用响应的before。清空后的恢复记录没有新UI浏览入口，维护时需先只读核对原owner数据库中的scope/id，不能凭相同文字猜ID。然后关闭受管Sumika/DSH和其他会读取这些数据库的独立工具，再预览：

```powershell
python -B tools/manage_personal_data.py purge-material --settings '<绝对路径/settings.json>' --message-id '<实际turn_id>:user'
```

上面命令只预览；输出 `plan_digest`、明确message ID、material与derived计数，不返回正文。每次最多100个ID，重复 `--message-id` 传入。检查角色配置及预览范围后，用同一组参数加确认与原摘要执行：

```powershell
python -B tools/manage_personal_data.py purge-material --settings '<绝对路径/settings.json>' --message-id '<实际turn_id>:user' --confirmed --expected-plan '<刚预览得到的plan_digest>'
```

这些是维护命令示例，不会在启动/模型输出后自动运行。预览后设置、角色、规范scope版本或目标素材/交接副本变动，执行会拒绝，须重新预览。CLI拿不到个人目录独占lease、恢复/角色迁移未完成或数据库为WAL/memory/off journal时拒绝；不自动切journal模式。管理开关关闭不阻止明确的离线删除，因为维护不初始化semantic模型。

事务范围：选定用户turn和对应助手reply、clear恢复副本、以这些source ID登记的handoff与events；同角色scope内通过EvidenceRef关联的事实及提议（含已接受/拒绝及inactive历史）、向量缓存/FTS索引。使用单一ATTACH事务与FULL同步，发生错误整体回滚。多来源结论触及任一删除来源时保守移除；用户另行确认的独立声明及手写关系保留。没有出处的旧事实不按语义猜测删除。SQLite事务能力由上游复用，不提供跨任意外部引擎的分布式删除。

成功返回 `erased_current_databases`，并分别返回两库压缩状态；VACUUM失败时删除仍已提交，返回 `pending_no_automatic_retry`，不能自动重放。清理不会额外创建含正文备份。已有 `.pre-repository-*`、角色/整库备份、旧导出及已传给DSH/其他消费者的副本保留，输出 `backups_deleted=false/external_copies_deleted=false/disk_sanitized=false`。这不是取证级磁盘擦除，不保证第三方或不遵守lease的程序释放旧内存/日志。

## v5记忆JSON与防复活契约

新导出 `schema_version=5`，保留v4字段并增加 `purge_tombstones=[{scope,kind,identity_hash}]`。kind为evidence/record/event/proposal，hash用于来源或身份匹配，不保留被删正文/quote。当前版本兼容读v2/v3/v4，旧版本程序会拒绝v5，不能删字段降级后声称迁移完整。普通逻辑遗忘可由显式JSON历史恢复撤销；**物理删除guard永不因JSON merge/restore/reset清除**，同source迟到提炼、旧record/event和相同legacy消息不会重新落正文。用户新的独立消息可以重新声明事实。

v5的guard可随scope迁移到新库，再导旧JSON也不会恢复已删素材派生事实。直接用旧整库文件覆盖当前数据库会恢复该文件的历史状态，连guard也回到当时；那是显式文件级恢复，非这里的JSON恢复，仍需既有恢复预览与消费者重启。Conversations中的turn guard留在原owner数据库，随完整个人目录备份/迁移保存，不伪装成记忆JSON包含对话备份。

本包：1302项全量OK/23 skipped（114.889s），最终9项purge专项通过（含后加在途检索）；3项真实CLI检查、8项真实Bridge纠正/关系浏览器检查通过。证据与准确版本范围见 `docs/project/acceptance-20261017-memory.md` 顶部。全部使用合成独立数据，没有删除日用用户素材。
