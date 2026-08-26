# 隔离浏览器

首版浏览器能力使用 Tencent BrowserSkill 作为固定版本候选：commit
`a004291848e8641400b973b8d612b4c4b74cdc90`、DSH plugin `0.1.1`、extension
`0.1.6`。Sumika 不注册 `ccswitch://` 或 BrowserSkill 的系统协议，也关闭
自动更新。

当前 `BrowserRuntime` 是策略 companion，并通过用户主动配置的
`SUMIKA_BSK_EXECUTABLE`（或 PATH 中的 `bsk`）读取 BrowserSkill CLI 的健康状态。
它登记临时/命名 Profile、域名和敏感动作审批、`browser_request_help`、下载
quarantine 与人工接管状态；它不会控制 Windows 全局鼠标键盘。CLI 已安装但
没有浏览器扩展时，状态为“等待扩展”；只有 BrowserSkill 报告浏览器已连接时，
才会创建真实 Agent Window session。没有 CLI 或 DSH 时仍安全降级为策略层，
不会生成虚假浏览结果。

Agent 页面通过 `browser.sessions` 显示当前核心实例登记的隔离会话，并可调用
`browser.session.close` 停止对应 BrowserSkill session。列表只返回 Profile 类型、
状态、角色/Agent 关联和过期时间，不暴露后端 session id。连接扩展后，Agent 页还可
通过真实的 `browser.tabs` 列出标签页，并刷新、创建、切换和关闭标签页；通过
`browser.observe` 读取受限观察、通过 `browser.snapshot` 读取 ARIA snapshot、通过
`browser.navigate` 导航，以及通过 `browser.request_help` 请求隔离窗口人工接管。
首次访问或跨域导航先返回审批结果，确认后才调用 `bsk navigate`；观察和 snapshot
结果在 Core 边界限深、限长并脱敏，不会写入事件日志。当前“继续”仍依赖 BrowserSkill
扩展窗口，UI 不会用本地状态伪装这些动作已经完成。

Agent 页的浏览器区域还提供下载 quarantine 队列和 Developer Mode 诊断入口。下载
只能在收到 BrowserSkill 事件或显式 RPC 后登记，释放前重新计算 SHA-256，并要求用户
选择一个已经存在的 Workspace；不会自动打开下载文件。开启 Developer Mode 后，用户
可在再次确认的前提下读取当前标签页的 console/network 摘要，结果经过脱敏和限长投影，
不保存原始日志。截图 RPC 已在 Core 边界提供，但当前 UI 不把二进制截图当作持久产物。

DOM 操作统一走 `browser.action.execute`，当前映射到 BrowserSkill 的
`click`、`fill`、`select` 和 `press`。这些动作默认需要显式批准；密码、
OTP、验证码和疑似凭据字段即使收到批准，也只返回 `requires_human`，要求用户在
隔离窗口中输入。动作返回值经过限长投影，输入值从不进入 Sumika 事件日志。

## 命名 Profile 与租约

`browser.profile.create` 创建的命名 Profile 元数据保存在 Sumika SQLite 的
`browser_profiles` 表中，因此重启 Core 后仍能列出名称、授权角色/Agent、归档状态
和最近使用时间。创建、归档、恢复以及启动命名会话都要求显式批准；命名 Profile
必须绑定一个 `character_id` 或 `agent_id`，启动时会再次校验绑定，避免角色误用别的
登录上下文。

命名会话会获取一个 30 分钟写租约，并在每次标签页、观察、导航或 DOM 操作前续租。
同一 Profile 在租约有效时不能被第二个会话写入；正常关闭 Core 或会话会释放租约，
崩溃遗留的租约在过期后可回收。租约只保存会话和运行时标识，不保存 Cookie、密码或
页面正文。

当前固定版 BrowserSkill CLI 没有经过确认的持久 Profile 选择参数，所以这些 Profile
首先是 Sumika 的授权和并发边界记录；真实浏览器 Cookie/Profile 的绑定仍需在上游
CLI 协议确认后接入，不会静默假设或伪造已持久化登录。归档是可恢复的元数据操作，
不会删除 BrowserSkill 数据或本地文件。

## Windows 可选安装

仓库不在启动时自动安装 CLI、浏览器扩展或 DSH 插件。用户可明确执行：

```powershell
.\tools\setup-browserskill.ps1
```

脚本把固定版本的 `bsk` 放到 `D:\Tools\BrowserSkill\0.1.10`，验证 SHA-256，
不修改 PATH，也不安装浏览器扩展。安装后在当前命令或桌面启动前设置：

```powershell
$env:SUMIKA_BSK_EXECUTABLE = 'D:\Tools\BrowserSkill\0.1.10\bsk.exe'
```

DSH 插件仍由受管 profile 单独安装；需要时使用脚本的
`-InstallDshPlugin`，不会改写全局 `DSH_HOME`。Chrome/Edge 扩展必须由用户从
[Chrome Web Store](https://chromewebstore.google.com/detail/hhcmgoofomhgciiibhipgmgkgnoenaoi)
或 Edge 商店手动安装并在扩展弹窗中连接。可用 `bsk doctor --json` 检查结果。

策略约束：公开任务临时 Profile 保留 24 小时；命名 Profile 需要显式授权且
同一时间只有一个写租约。首次访问、跨域、登录、提交、发送、上传、下载、
购买、发布、删除、权限修改、`evaluate` 和 raw CDP 都必须批准。密码、OTP、
CAPTCHA 只在隔离窗口人工输入，不进入聊天、模型上下文或日志。下载先记录
来源、SHA-256 和类型，用户确认后才能导入 Workspace。

固定参考版本：BrowserSkill commit `a004291848e8641400b973b8d612b4c4b74cdc90`、
DSH plugin `0.1.1`、extension `0.1.6`、CLI `0.1.10`。CLI 与插件为 MIT；
Sumika 只调用其公开 CLI/插件边界，不复制源码、扩展或浏览器素材。

## 相关文档

- [DSH Agent](dsh-agent.md)
- [Evolution Knowledge Registry](evolution-registry.md)
- [安全边界](../architecture/security.md)
