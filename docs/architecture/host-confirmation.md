# 可信宿主确认

H01当前子包：实现限定确认的传输边界及原生接线，**不是H01全部完成**。中立Harness对象、稳定实例绑定和剩余权限入口审计仍待继续。

## 实际调用链

`CoreApplication.rpc(method, params, *, caller=None)`检查由传输层提供的CallerContext。普通HTTP `/rpc`不构造可信上下文，即使正文包含approved、trusted、actor，或请求头携带宿主凭据也不能批准。

`HostAuthorization`位于独立模块，不依赖CoreApplication、存储、模型或Tauri。CallerContext绑定方法、请求摘要和本次Core发行者身份；正文不能构造发行者身份。内部服务方法仍由可信装配调用，不能把对象引用交给不可信插件。

本轮限制方法：work.authorization.confirm、quality.task.confirm、quality.task.budget、schedule.create/update/pause、agent.approval.respond、agent.question.respond。merge.apply/undo已保留后端拒绝边界，原生尚不放行尚未实现的合入动作。

Agent问答可携带Plan Review批准，因此整个回答入口都要求可信宿主，不依据调用者声称的普通问题类别放行。原先的交互查找、精确选项和checkpoint先于批准的业务顺序保持；未认证请求在任何checkpoint或运行时回复前拒绝。普通浏览器仍可查看问题，但必须在原生工作台回答。取消入口未因此授予执行权限。

请求摘要入口：`host.confirmation.digest`接收method/params，仅返回规范JSON的SHA256，无授权或模型调用。摘要绑定本次提交参数，不是H05成果diff预览摘要，不能以此声称已完成源码审查。

原生`host_confirm`只接受上述限定方法、对象参数和摘要；调用现有main WebView标签、窗口与可信origin检查。陪伴、内置远程网页及任意RPC转发不获权限。前端helper先复制参数，避免用户编辑影响正在确认的请求；陪伴转回工作台，普通浏览器提示使用原生工作台，失败不回退HTTP、不重发。

原生通过`POST /internal/host-confirm/v1`提交method/params/digest，认证材料位于X-Sumika-Host请求头。Core校验认证与摘要后生成只适用于此动作的CallerContext，再进入原业务版本/上限检查。此局部接口没有新增总账，不将确认等同模型执行。

## 引导与生命周期

Tauri用系统随机源生成32字节随机值，经私有stdin发送`sumika-host/v1`JSON帧。Python仅在显式`--host-bootstrap-stdin`启动参数下读取，不从环境变量、URL、数据库或普通配置加载认证材料。读取有1024字符上限，非法/缺失帧拒绝启动。

认证材料只在原生/Core内存与该本机确认传输中使用，不交给前端、模型工具或DSH环境。每次Core重启重新生成；已有Issuer上下文不能用于新Core。管道写入失败回收本次自有子进程。认证边界不声称防御已完全控制当前操作系统账户的攻击者。

外部手动启动Core没有宿主材料时，仍能读取诊断和使用其他既有功能，但上述敏感确认被拒绝。**不是整个Core已变成只读服务**；其他权限入口仍待审计。

## 测试与回执

续做最终验证：后端全量1257、专项91、前端83、Rust37通过；Playwright全量86通过，生产及隔离custom-protocol构建通过。最新原生证据`D:/Caches/sumika-h01-native/1789095677009/result.json`覆盖新增Plan Review HTTP与陪伴拒绝及完整双窗口退出，截图已查。下列1255项及旧smoke路径为前一阶段证据，不替代最新结果。

- 后端全量1255项通过：`artifacts/h01-backend.log`。后续增加Agent权限拒绝、非法Unicode认证及最新边界专项35项通过。
- Rust37项通过，debug handler及custom-protocol handler均注册host_confirm；Cargo只声明已在锁文件中的getrandom 0.3，未升级DSH或其他锁定包。
- 前端83项单测通过，新增副本绑定、普通浏览器拒绝、陪伴转交、未知不重发、任意方法拒绝；生产构建通过。
- 隔离custom-protocol二进制为`src-tauri/target/native-smoke/debug/sumika-desktop.exe`，没有覆盖日用debug二进制或配置。
- 真实原生smoke通过：`D:/Caches/sumika-h01-native/1789094697537/result.json`；含私有引导、普通HTTP伪造拒绝、陪伴拒绝、任意RPC拒绝、两个真实窗口、同一Core、各模式及干净退出。不存在请求返回业务“未找到”证明已通过宿主认证，不伪称真实付费授权或模型调用成功。
- 最新工作台截图已检查。真实多屏热插拔仍未验收。旧smoke通用textarea选择器因增加测试命令输入而失效，已改为name=goal，未修改产品布局。
- Playwright确认夹具明确使用native-fixture，普通HTTP出现确认调用会失败；不将夹具当真实原生证据。最终运行结果以执行记录为准。

## 下一子包与普通模型交接

H01余项必须由高难实施者继续：RuntimeBinding/ExternalSessionRef等中立对象及适配器契约测试；稳定profile与启动身份分离；其他可能扩大工具、文件或数据共享范围的旧入口逐项审计。不能把本次小白名单认为已覆盖整个应用权限。

### 已定位的下一批入口

以下为代码审计发现，不表示已完成保护；也不能交给普通模型自行决定权限语义：

| 入口 | 当前缺口 | 固定处理及验收 |
| --- | --- | --- |
| workspace.worktree.create / workspace.commit / workspace.restore | 有preview token、approved及精确对象核对，但普通RPC尚无可信调用者门槛 | 保留全部旧预览检查，增加可信传输；伪造正文和有效旧token不能调用文件写入；通过可信夹具验证原有业务错误仍生效 |
| agent.session.retry | 正文approved与session确认不是可信授权，也不能证明前次未发送 | H01接可信确认，H03/H04继续落实未知阻断；不能因为用户确认就自动重发未知操作 |
| agent.skills.approve/revoke及单数别名 | 注册变更依赖正文approved | 复用同一确认链且覆盖别名；不把注册批准当执行或付费授权 |
| agent.mcp.configuration.apply | preset、previewToken核对之外缺传输身份 | 保留当前预览、脱敏和配置备份；前端使用限定命令，普通网页及伪造请求零配置写入 |
| browser、plugin、audio.permission.set、vision.permission.set等 | 多处既有批准/权限写入口尚未完成统一审计 | 逐项区分只读、撤权、扩权及费用派发；不得用扩大原生任意RPC白名单代替审计 |
| Core受管启动 | core_ready仍依赖端口健康，尚未核验启动身份 | 在发布受管组合前核对实际子进程及实例，不因另一服务返回健康就接受为自有Core |

下一批每个入口都必须同步后端拒绝测试、原生限定动作、最小UI接线及显式native fixture；不能为了旧E2E通过恢复普通HTTP授权。现有参数摘要仍不等于服务器报价/预览版本绑定，后续需按业务对象再次校验。

H02发行组合、H03逐调用网关/账本、H04恢复、H05预览绑定及合入、H06自改仍未实现。不得提前切换日用DSH。

普通模型只处理已存在helper的提示和状态展示：

1. 输入使用原work/quality字段，通过统一transportRpc进入confirmThroughHost；不直调HTTP确认，不获取宿主凭据。
2. native确认失败时保留原请求ID、版本和用户输入；未知只显示查询状态，不自动再确认或再提交。
3. 陪伴转交保持原角色请求，用户在工作台确认后继续原请求，不能创建第二份消费授权。
4. 非原生页面明确显示限制，不增加浏览器信任开关。工作台测试用隔离native-fixture，后端安全测试不能启用HTTP信任参数。
5. UI验收覆盖确认前零执行、失败保留输入、取消、手动编辑后新摘要、陪伴转交和键盘操作。范围只限view/host/helper测试，不更改后端权限白名单。
6. 回退需要保留后端拒绝规则；不能通过恢复普通HTTP确认修复UI。提交证据路径、实际命令、未验收限制并更新当前记录。
