# 备份与恢复

阶段 0 使用 Git 保存项目记录、源码、发行描述与锁文件 checkpoint。提交前运行 `python -B -m sumika_next.cli check` 和相称测试，提交后记录 commit SHA。执行记录中的 SHA 指最近已存在的提交，不能在提交前编造本次 SHA。

项目运行数据的完整备份恢复列入 P7，首版暂不考虑加密。聊天、角色配置等私密运行数据保存在用户本地，不随源码上传；凭据使用运行时的安全存储，不写入 Git、验收报告或需求原文。原话含密钥时先脱敏并明确标记，不能伪称脱敏文本是完整逐字原文。

源码/记录恢复：在被忽略的 `.sumika-next/backups` 目录用 `git bundle create <目标.bundle> codex/sumika-next-dsh` 建恢复包，随后 `git bundle verify <目标.bundle>`。恢复到新的不存在目录：`git clone <目标.bundle> <新目录>`；依照固定锁重新安装，运行连续性校验。恢复通过前不替换当前项目。

运行数据后续恢复也先复制到隔离目录核对，不直接覆盖现有 profile；不能把 Git bundle 当作未跟踪运行数据备份。

新版分支不删除旧分支。需要回退时使用旧分支提交或独立恢复目录，不覆盖未提交数据。

P4 新增的 `.sumika-continuity/` 是被忽略的私有原始记录库，也必须纳入运行数据备份；Git bundle 不含它。停止 DSH 后复制完整目录与工作文件，或使用 SQLite backup API 做在线一致快照。恢复保留项目 UUID，并重新绑定项目路径。可提交的 requirements.json / 验收文档仍不含密钥；自动捕获的本地原话可能含用户输入的敏感数据，不自动导出或上传。

## 离线个人数据快照（部分实现）

复用角色/记忆导出与 ui.data_lease，新增 tools/backup_personal_data.py：
`python -B tools/backup_personal_data.py --source <已停止的数据目录> --destination <不存在的新目录>`。
拒绝源目录链接、运行中的 Bridge、非空 DSH 实例记录、已存在或位于源目录中的目标；复制前后与目标逐文件 SHA-256 对照，只有一致才写 verified 清单。失败保留现场与原数据，不删除。

5项测试通过，并对已停止的隔离 EXE 测试数据生成快照：.sumika-next/package/exe-startup-083b1425c8464988b741e42f11bd7f03/verified-snapshot/snapshot.json。没有备份用户日用配置。该副本含私有内容时也属于私有数据，不能分发。未涵盖目录外角色/模型、旧位置 DSH Profile，也不证明独立写者完全排除、恢复重绑定或重启可用；完整备份恢复保持未完成。

## 恢复副本与角色路径重绑定（部分验收）

`python -B tools/backup_personal_data.py --restore --source <快照目录> --destination <新目录> [--rebind-role-paths]`。先复核快照真实文件清单和SHA-256，再复制到新目录并再次验证；不覆盖已有目录、不自动启动。可选重绑定仅改 role.role_dir、role.database 中原数据目录内的路径，并复用 Conversations.scope_for/relocate_scope 保存稳定作用域。原文、消息ID、unknown状态、交接正文不改；目录外资源保留原引用。

9项测试通过；隔离EXE数据恢复后由包内Python启动，/api/state正常，证据：.sumika-next/package/restore-startup-307073076b5a497180d2723e71ff76a4/report.json。并非完整迁移验收：DSH配置路径、其他能力路径、外部资源、独立写者排除及重绑定中途失败的恢复仍待补，失败目标应保留检查，不直接启用。日用个人数据未操作。

## 角色恢复中断与单写者补强

重绑定前将原配置、目标配置和稳定作用域迁移计划写入个人目录 role-restore-state.json；pending状态阻止Bridge初始化，完成后原子写complete。数据库迁移使用原有幂等接口，配置保存失败可按同一计划恢复，不新增作用域、不重写聊天。恢复期间设置被修改则拒绝覆盖。

重试命令：`python -B tools/backup_personal_data.py --resume-role-rebind --source <原快照> --destination <中断的恢复目录>`。不重新复制已有目标。该日志含个人配置，不是可公开诊断文件。

备份除持有Bridge锁外，也持有现存DSH Profile的sumika-instance.lock，使用同一OS字节锁协议但不改实例记录。非空实例记录仍拒绝。首次故障夹具因空角色目录未进入快照而未触发预期中断，已加入实际文件后重跑；31项组合检查通过，后续独立DSH锁及配置冲突补充后15项针对性测试通过。不能据此宣称新建独立Profile或非合作写者完全受控，也不代表完整DSH路径迁移完成。

## 真实 DSH Profile 恢复验收

复用 WorkbenchController、ModelFixture、原生 session/page 与离线快照工具。首次真实备份发现 Profile 下 profiles/node_modules 包含上游自动生成的依赖链接，备份因链接保护而拒绝；现仅排除 dsh-profiles/*/profiles/node_modules，并在清单声明。会话/配置仍保留，其他用户链接不自动跟随。恢复启动由 DSH 重新生成依赖挂载。

证据：.sumika-next/package/profile-restore-114d0fb31d16441e9cb42d22e268c0fe/report.json。真实工作台完成原生write工具后停止，13文件快照恢复到新个人目录；重启后原文、工具结果存在，模型调用数未增加，工作文件修改时间不变，原Profile未改变，恢复实例停止。13项快照单测通过。当前只证明同安装路径/同工作路径下的数据目录恢复，不证明跨机器、跨安装目录的所有插件/能力路径均可迁移。

## 重复备份与角色恢复

复用现有恢复日志与稳定作用域迁移。已恢复的数据再次备份、恢复时，若继承日志为 complete 且其目标正是本次源目录，则先按内容 SHA-256 保存到 role-restore-history，再生成新迁移计划。旧日志与源数据保留，正常修改过的配置按当前值迁移。pending 或不匹配日志仍拒绝重绑定。

新增连续两次恢复、保留 unknown 消息和稳定身份、继承 pending 拒绝测试；快照与发行清单组合 25 项通过，运行报告有 SQLite ResourceWarning。仍仅覆盖角色路径，不代表跨安装目录 DSH 插件、其他能力路径及全部外部资源迁移已验收。

## 不同安装目录的工作台恢复

发现 ensure_skin 原先使用 Python 模块目录定位插件，并猜测 Profile 祖先目录的发行版本；当 WorkbenchController 选择另一安装根时，会仍登记旧路径。现统一从 controller.root 取三个产品插件路径及 release.json，保留用户插件行，不修改上游。复用现有真实恢复脚本，新增 --restored-product <安装目录>。

11 项工作台测试通过。跨安装证据：.sumika-next/package/profile-restore-57478c018ebd4153bd5f56008171069f/report.json。原生 write 任务停止后备份 13 文件，恢复并选择另一候选安装；三个插件登记目标正确、会话原文及工具结果保留、无新增模型调用或任务重放、原 Profile 不变、实例停止。

边界：由当前宿主 Python 驱动真实候选 DSH，旧安装仍存在，工作目录及外部角色资源未迁移。尚非干净机器、全部扩展路径、EXE 全程恢复或真实模型自主开发验收。首次单测因临时目录路径重定向未 resolve 而失败，修正测试比较规范路径后通过；已有弃用/资源警告仍存在。

## 连续性未知结果跨重启保留

DSH连续性适配器在存储子进程启动前，将 schema/status/action 写入 .sumika-continuity/adapter-state/<session-hash>.json，fsync 后原子替换；成功响应后才标记 settled。pending 或损坏记录跨重启拒绝后续自动读写，数据库修复不自动解锁。侧车不含原文、请求正文或凭据，属于个人连续性数据，应随库备份。

11项Node测试通过；真实DSH证据 .sumika-next/continuity-failure-58229606e9d141e4b71147accdbfcb9d/report.json：健康基线后损坏数据库，两次拒绝，停止并恢复健康库、重启后仍拒绝，模型调用未增加、健康库字节未改变。显式核对与解除流程仍待实现；不得删除标记伪装恢复，也不代表独立多宿主竞争或完整发行验收已完成。

## 显式核对与恢复连续性读写

先停止对应受管Profile，执行 `python -B tools/reconcile_continuity.py --root <项目> --session <会话ID>`。只读检查SQLite完整性、项目schema及pending状态，返回state_sha256/database_sha256和记录数，不输出原文、不修复库。完整性通过不等于原操作成功；操作者须结合原始记录核对未知结果。

明确允许连续性存储重新同步时，执行 `python -B tools/reconcile_continuity.py --root <项目> --session <会话ID> --profile <Profile> --allow-storage-retry --expected-state-sha256 <核对值> --expected-database-sha256 <核对值>`。工具核对Profile绑定，持有同一字节锁但不改进程归属，非空归属记录拒绝。先保留含原pending元数据的receipt，再原子写reconciled状态，original_outcome仍为unknown；不发送模型请求、不执行任务、不删除标记。下一次正常存储同步可以回填已有原生事件，未知工具/开发任务不会由本工具重放。

3项Python恢复测试、12项Node适配测试通过。真实DSH证据 .sumika-next/continuity-failure-f0362d18edc343dd8962a180238b2cf9/report.json：修库重启仍拦截，明确核对解除后重启没有模型调用，显式新请求才产生一次调用并完成。首次测试发现ProfileLease会写入虚构启动记录且在清除时触发WinError5，离线恢复改为DataLease只锁不改归属后通过。独立非合作写者不在当前证据范围，日用服务和发行包未更新。

## 活动工具与排队消息退出验收

复用WorkBench实际stop路径，以原生pwsh在独立目录写PID、等待、计划后续写入。退出前核对PID创建身份，退出后子进程消失、后续写入未发生；重启无新增模型调用。原生恢复将turn标为interrupted，缺失工具结果明确为unknown。带一条排队消息的场景中，原文保留且重启后仍待处理，不自动执行。证据 .sumika-next/active-stop-af305f60246f44f8ae6b8149abe6371f/report.json。

这是强制结束后的恢复证据，不是优雅退出。DSH原生session/cancel会继续处理排队消息，因此不能用简单cancel替换退出。并发新提交、全应用角色/语音退出及完整刷盘仍待验收。

## Retained-version rollback acceptance

`tools/verify_personal_restore_dsh.py --restored-product <new installation> --rollback-product <retained prior installation>` now verifies explicit rollback to a separate data directory restored from the pre-change snapshot. The prior runtime never opens candidate-mutated data. Candidate and original data are hash-checked unchanged; history, tool records, plugin paths and absence of task replay are verified against actual DSH.

Candidates f then e passed: `.sumika-next/package/profile-restore-7afc512933e34ff1bfada20340f08af5/report.json`. Local deterministic model fixture only, zero external model calls. This is not automatic update, schema downgrade, injected installation failure or clean-machine acceptance; no daily data touched.

## Installer extraction interruption and explicit retry

The existing `tools/verify_portable_installer.py` now stops its owned real PowerShell installer after observing the first extracted file. With a bounded synthetic archive, the incomplete destination was never published; explicit retry completed exactly; failed staging, the old installation and separate personal-data sentinel remained unchanged. Existing manifest/path/hash checks also passed. Evidence: `.sumika-next/package/installer-check-94726bd1bf66439c9c577f9c60896199/report.json`.

No product installer change was needed. This covers interruption during extraction into a new directory, not power loss, shortcut publication, automatic update activation or clean-machine acceptance. All fixture and failed-staging artifacts are retained on D:.

## 只读恢复预检

执行 `python -B tools/backup_personal_data.py --inspect --source <快照目录>`，或使用模块命令 `python -B -m tools.backup_personal_data --inspect --source <快照目录>`。不需要 destination，不能与恢复、重绑定或目标目录参数混用。

该命令复用恢复的快照完整性校验，检查角色目录和角色记忆数据库的路径是否可用。内部路径按快照清单映射，不能拿原目录补足缺项；空目录和排除文件不算可恢复资源。外部本地资源仅检查类型与存在性；相对路径、网络路径、设备命名空间、链接及无法访问的路径返回 unknown，不自动连接或创建资源。无角色配置是有效首启状态。

- `ready`：本次检查的路径存在且无已知恢复日志问题，不代表模型、数据库或全部扩展可运行。
- `needs_attention`：检查到缺失资源或 pending 角色重绑定。
- `unknown`：配置、恢复日志或路径无法可靠判断。

完整性未通过时，CLI 输出固定脱敏问题码并退出 2；完整性通过后输出报告并退出 0，调用方还需判断 status。报告只含字段标识、范围和状态，不输出原始路径、配置、凭据或聊天。不创建锁、数据库、恢复日志，不激活、不重绑、不重放任务。该模块不是完整依赖扫描；其他角色绑定、DSH 插件、语音/OCR/模型运行时仍需各自验收。

38 项预检及既有备份恢复测试通过，包含真实 CLI、网络路径不探测、损坏配置、缺失外部数据库、内部恢复清单、Windows 大小写及参数冲突。现有恢复测试有 SQLite ResourceWarning，未据此宣称资源警告已修复。
