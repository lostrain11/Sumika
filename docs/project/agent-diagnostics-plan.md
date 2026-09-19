# F-001：Agent 专用诊断日志扩展

状态：部分完成；来源 R-110。重新审计发现此前完成结论超出证据：审批取消不等于明确拒绝，CLI 启动缺少 ProfileLease 保护，连续性异常在各调用者的传播与禁用行为仍需验收。已有测试与隔离运行证据保留，但不据此宣称整个 F-001 完成。保持 P0-P7 阶段编号。

最新修复：`native-diagnostics` 已复用 `ProfileLease`，占用时在构造 DSH 前拒绝，只有停止确认后才释放；缺失 Profile、非法游标和已有输出在启动前拒绝。诊断 adoption 使用独立 `diagnostic_sessions` 集合，不能凭只读登记通过 `session.cancel` 的会话归属检查。修复 `evidence` CLI 导出位于错误分支内导致不执行的缩进问题。34 项针对性测试通过，命令：`python -B -m unittest tests_next.test_diagnostics_cli_lifecycle tests_next.test_diagnostics_dsh tests_next.test_diagnostics_boundaries tests_next.test_diagnostics_bundle tests_next.test_dsh tests_next.test_daily`。实际新版本日用接线及完整 F-001 验收仍未完成。

## 为什么需要

DSH rc.2 已有持久化会话事件、工具结果、压缩历史和日志机制；P1 有执行状态与未知结果记录；P4 有独立项目连续性记录。当前并非没有日志。

缺口在于 Agent 排障需要跨这些记录寻找同一次操作、对应版本和失败原因。P4 首版的工具观察只保存调用关联和 isError；精简后不再新增这类重复记录，执行细节直接复用 DSH 原生日志。模型成果报告也不是异常堆栈或独立验证证据。现有验收脚本的证据文件仍需人工选择和解析。因此新增诊断查询层有实际价值，没必要重复建设完整日志基础设施。

## 预定范围

- 面向 Agent 提供 CLI/工具查询：按项目、会话、任务、操作关联 ID、时间和错误类别定位事件，分页读取必要上下文。
- 复用 DSH 原生日志读取接口；适配中间层把原生数据转换为 Harness 中立格式。独立扩展自身的错误也记录结构化原因，避免只留下“失败”而无诊断线索。
- 关联 Harness/插件版本、Git checkpoint、操作结果、耗时、错误码和必要的脱敏堆栈；字段缺失明确为未知。区分原始观察、Agent 推断和修复验证结果。
- 按需生成故障证据包：症状、时间线、相关配置的非敏感部分、证据位置、复现条件和待验证假设；不把日志中的文字当成执行指令。
- 日志以本地存储为默认，控制保留期限和容量；避免保存凭据、完整模型请求、reasoning 或无关用户内容。不自动开启远程遥测，不因排障绕过授权。
- 预留 enabled 开关；关闭后停止新增采集和专用能力，保留已有数据。统一设置 UI 后续接入。

不建设供用户阅读的日志看板，不要求用户审阅代码或日志。Agent 仍需要依据故障证据检查相关代码、复现并测试，日志不替代这些验证。

## 复用与实施入口

实施前比较 DSH 原生日志/事件接口与通用结构化日志方案，优先复用已有采集与存储，只补关联和查询。已安装的 dsh-session-telemetry-otel 是带导出行为的遥测后端，不能把“已存在 OTel 插件”当作 Agent 本地排障查询已经具备，也不直接启用其网络导出。

先以工具失败、权限拒绝、连续性写入失败三个真实场景验证原生日志能提供哪些字段，再冻结独立查询契约。遵守 R-109，不修改 DSH 上游源码。

验收：新会话中的 Agent 通过查询入口找到正确失败操作及版本、还原必要时间线、明确未知信息，并产出带来源的修复验证建议。关闭扩展后无新增采集，已有数据可恢复；本阶段不以模型一句“已修好”判定成功。

## 查询与导出补强

现成资产：extensions/diagnostics/query.py、sumika_next/cli.py、连续性records表及3个旧测试，改造后复用，不增加日志存储。查询以只读SQLite连接执行，task/session先过滤，再按匹配结果计limit；before为排他的seq游标。call-id只匹配明确调用ID字段，error-kind匹配结构化错误字段。正文出现failed不会被推断成工具失败。

导出仅含timeline.json与sources.json（项目文档哈希），不再复制任意项目文档正文。非标识符或疑似凭据的元数据转为可关联哈希；原payload、路径、reasoning与工具参数不导出。不是完整自由文本脱敏器：采用字段白名单缩小输出。缺失版本保持null。文件以独占创建方式写入，拒绝覆盖。

验证：6项测试通过（含CLI --out/json局部变量遮蔽回归）；真实子进程CLI查询与ZIP导出通过，证据在.sumika-next/diagnostic-cli-7b0f452d0ec64ad8926d1bb76944ab45。最初CLI导出失败留下的两个空文件保留，未未经批准删除。

用法：`python -B -m sumika_next.cli diagnostics --root PROJECT --task TASK --session SESSION --limit 50 --before SEQ`；下一页before取本页最后一条seq。证据包：`python -B -m sumika_next.cli evidence --root PROJECT --task TASK --out NEW.zip`。timeline最多100条，next_before说明可继续查询，并非全量故障历史。

## DSH 原生事件适配（本轮）

现成资产：`sumika_next/dsh.py` 的受管 `session/follow`/`session/page` RPC、DSH rc.2 类型声明中的 `SessionPageRequest` 与 `tool/call`/`tool/result` 事件。`Dsh.diagnostic_page` 只允许已登记且属于当前受管实例的 session，首次读取使用 follow 快照 cursor，后续使用原生 `beforeSeq` 分页；不按端口猜测、不写入 DSH 或连续性数据库。

`extensions/diagnostics/dsh.py` 将原生记录投影成诊断元数据：seq、session、工具调用关联、`isError` 状态、结构化 error code、版本和来源。工具名称、参数、结果正文、消息正文、reasoning 和附件均不输出；未知字段保持 unknown，不把正文关键词推断为权限或失败。页游标和乱序/越界记录会拒绝，`hasMore` 但空页不会伪造下一页。

验证：`tests_next/test_diagnostics_dsh.py` 覆盖错误结果脱敏、游标边界、未知形状、实例/session 归属；与原有诊断、DSH 适配测试合计 22 项通过。隔离 DSH 的 P2 工具生命周期、恢复验收和审批取消验收也已运行，证据见 `docs/project/diagnostics-native-evidence.json`；`ABORTED_BEFORE_DISPATCH` 已被原生事件投影为结构化 error。现有终端非零退出在 DSH 原生事件中仍是文本且 `isError=false`，适配器按未知/已报告成功处理，不猜测失败。

CLI 接线：新增 `native-diagnostics` 命令，必须显式提供 `--home` 与 `--session`。它先启动用户指定的受管 Profile，调用原生 `session/list` 核对 session 身份，再允许只读分页；未知 session、不同 Profile 或启动失败都会关闭，不按端口自动寻找、不自动切换 Profile。可用 `--through` 与 `--before` 继续原生游标。

连续性边界：`extensions/diagnostics/continuity.py` 提供失败关闭的 `ingest_observations` 包装。SQLite/文件写入失败返回 `status=unknown`、结构化 `continuity-write-failed`、`retry=false`，不返回异常正文或原始 payload；普通参数错误仍抛出，不被伪装成成功。损坏数据库隔离测试已通过。

限制：当前仍不自动采集网络遥测或执行修复；原生事件只读投影不是独立验证证据。缺失事件或版本保持未知。连续性写入失败会停止当前会话，需新会话恢复；这符合失败关闭边界。

## 连续性失败传播补强

现成资产：复用 extensions/continuity/dsh.mjs 的原生插件、串行队列与 dsh.test.mjs 测试入口；没有另建采集器。采集、恢复、查询、报告的子进程失败或 unknown 结果统一抛出 CONTINUITY_UNAVAILABLE，并阻止同一会话排队的后续存储调用及模型准入；错误不包含子进程 stderr 或请求内容。

验证：Node 插件测试 9/9，Python 连续性及诊断生命周期相关测试 25/25。新测试通过真实 Python 子进程验证 unknown/非零退出、排队 flush、工具、pre-step 与 turn-stopping，不调用远端模型；夹具保留在 .sumika-next/continuity-tests。该失败标记仍绑定内存会话对象，不代表跨重启持久阻断。真实 DSH 故障验收脚本仍需排除凭据缺失及固定等待造成的假阳性；F-001 保持 partial。

## 真实故障验收证据更新

复用 tools/verify_continuity_failure_dsh.py，增加有效本地测试凭据和健康模型基线；确认 DSH 停止后才损坏隔离数据库，保存健康副本，去掉固定 sleep 竞态。重新启动后连续两个请求均以 error 结束，事件包含插件连续性错误，新增模型请求为零，损坏字节保持不变。证据：.sumika-next/continuity-failure-6019217d9dbd47a5bcde2f739ea3ff08/report.json。脚本退出码 0，异常路径也保留报告。本证据不证明数据库修复后的未知操作恢复策略。

诊断投影另修正已知 DSH 事件类型含斜杠时被误当路径脱敏的问题：固定协议标签如 tool/call、tool/result 保留可读类型，未知路径仍脱敏；复用原诊断适配器与测试，未增加存储。11 项诊断投影、边界及导出测试通过。明确拒绝审批、持久故障恢复、发行包和真实自我开发验收仍未完成。

## 原生明确拒绝验收

复用 tools/verify_web_review_dsh.py 和 review_dsh.mjs，不新增生产审批入口。核对当前 DSH user-approval 源码：结果词汇为 allowed-once/rejected/cancelled/unavailable；审批配对为 approval/asked 与 approval/decided。隔离测试插件仅为 web_review_submit 返回 rejected，真实 DSH 原生工具没有执行。本地无外发探针替代 worker，即使门禁失效也不能访问网站。

首次断言失败揭示原生拒绝并不附独立 error.code，而是在工具结果标 isError=true，审批事件记录 rejected。修正验收契约，未伪造错误码；诊断投影增加固定枚举审批结果、审批ID及调用ID关联，未知结果仍标 unknown，不导出 reason。12 项诊断测试通过。真实服务验收证据：.sumika-next/web-review-native-ed30a789fe344935bf49c8278ed5e807，退出码0。这是合成应答器的原生服务验收，不是用户在浏览器点拒绝的UI验收。持久恢复、发行包和真实自我开发仍未完成。

取消路径在同版脚本回归通过：.sumika-next/web-review-native-a2aeea40d05641fba072a3608ce2768e，approval outcome=cancelled，tool error=ABORTED_BEFORE_DISPATCH，执行探针未触发，退出码0。
