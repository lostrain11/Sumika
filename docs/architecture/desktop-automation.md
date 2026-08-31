# Desktop automation toolkit

本专题定义受控桌面软件自动化的通用边界。当前完成度只看[状态矩阵](../status-matrix.md)；这里描述契约、数据流和安全约束，不把任何具体软件当作 Core 的基类。

## 目标与优先级

桌面软件可以作为某个能力的一个可替换实现。Sumika 按以下顺序选择传输：

1. 应用公开的 `app-protocol` 或 `stdio` 接口；
2. 应用明确开启的本机 Electron `CDP`；
3. Windows `UI Automation`（UIA）；
4. 经用户逐次批准的前台接管。

适配器只负责把传输调用翻译成统一结果，Core 负责登记、租约、权限、幂等、审计和关闭。适配器不得自行发现任意窗口、搜索 `PATH`、调用 shell 或读取应用凭据。

## 稳定契约

`DesktopAdapter` 提供 `health`、`open`、`observe`、`act`、`close` 和可选的 `takeover`。应用声明包含稳定的 `app_id`、`adapter_id`、传输类型、能力和用户批准状态。一次打开会话只能持有一个 profile 写租约；同一 profile 的手动操作和 Agent 操作不能并发写入。

`TransportDesktopAdapter` 是通用薄包装，用于把 transport client 注册为 `DesktopAdapter`。现有 `ElectronCdpClient` 和 `WindowsUiAutomationClient` 是传输客户端，不直接承担 Core 生命周期。外部实现只需提供下列最小方法即可复用同一套 UI、RPC 和策略：

```text
health() -> mapping
open(application, profile_id, options) -> mapping with native session id
observe(native_session_id, options) -> value
act(native_session_id, action_request) -> value
close(native_session_id) -> value       # optional
takeover(native_session_id, enabled) -> value  # optional
```

`ZCodeDesktopAdapter` 目前优先使用公开 `app-server`，只有显式配置且协议可用时才尝试 CDP/UIA；缺失 app-server 不会静默开启前台输入。

### Electron CDP 配置

仓库内置的 `StdlibCdpRunner` 不需要额外 Python 包。只有在应用登记配置中同时
提供 `enable_cdp: true` 和 loopback `cdp_endpoint` 时，`ZCodeDesktopAdapter`
才会创建它；例如：

```json
{
  "app_id": "zcode",
  "adapter_id": "zcode-desktop",
  "approved": true,
  "config": {
    "enable_cdp": true,
    "cdp_endpoint": "http://127.0.0.1:9222"
  }
}
```

用户需要自行关闭并以 `--remote-debugging-port=9222` 启动目标 Electron 应用，
再从 `desktop.automation.catalog` 刷新状态。Sumika 不会替用户重启应用、打开
`/json/new` 目标或关闭目标窗口。runner 只附加已有 page target，支持固定的
`observe`、`click`、`focus`、`fill`（包括 `input`、`textarea` 和 `contenteditable`）、
`select`、`press` 和 `send` 动作；不暴露
任意 `Runtime.evaluate`、raw CDP、网络检查或全局鼠标键盘。`send` 只得到 DOM
事件已派发的证据，远端是否真正接收仍返回 `unknown/possibly-sent`。

## 生命周期与授权

- 应用登记、启动和关闭都要求 `approved: true`；目录和 `observe` 是只读入口。
- 第一次 `control`、`send` 或前台接管会产生待处理批准。批准令牌绑定 session、动作和输入哈希，不能转用于另一项操作。
- `login`、凭据、密码、OTP、CAPTCHA、删除、发布、购买、上传和下载始终属于 `sensitive`，不能由 Agent 直接注入凭据；用户应在应用自己的窗口中完成登录或确认。
- 发送结果无法确认时返回 `unknown` / `possibly-sent`，不自动重试，也不自动切换模型。
- `idempotency_key` 只重放已确认完成的结果；未知发送不会写入可重放缓存。
- Core 关闭时先关闭由本实例创建的会话和 adapter；不会终止用户在外部启动的应用或服务。

## 数据与审计

SQLite 只保存应用声明和租约的有界元数据，不保存 executable、启动参数、Cookie、Token 或其他秘密。适配器返回值在 RPC、事件和日志边界统一限长并移除本地路径、二进制和凭据形状内容。`logs/desktop-automation/*.jsonl` 只记录动作类别、风险、状态、耗时和哈希，供故障定位和日聚合使用。

桌面应用会投影到 `capability-catalog/v1` 的 `tools` 组，名称为 `desktop:<app_id>`。投影只说明来源、传输和状态，不自动启动应用，也不改变模块或模型路由。

## 当前限制

本仓库提供 CDP/UIA 的安全 transport client、标准库 CDP runner 和可注入 runner，未捆绑第三方 WebSocket、UIA 或全局输入依赖。真实应用必须由用户明确提供启动/连接方式，并在隔离环境完成许可证、权限、卸载恢复和端到端验证后再登记。前台接管默认关闭；BrowserSkill 仍是独立的浏览器能力，不通过本工具包控制用户的 Edge。

## 验证入口

- Python 契约：[桌面自动化测试](../../backend/tests/test_desktop_automation.py)；[CDP transport 测试](../../backend/tests/test_cdp_transport.py)
- Core RPC：`desktop.automation.status`、`catalog`、`register`、`open`、`observe`、`act`、`close`、`approval`、`takeover`
- DSH bridge：[插件 README](../../plugins/dsh-desktop-automation/README.md) 与 [policy tests](../../plugins/dsh-desktop-automation/test/policy.test.mjs)

## 相关文档

- [Desktop shell](desktop-shell.md)
- [Security](security.md)
- [Agent Runtime](agent-runtime.md)
- [Modules](modules.md)
- [状态矩阵](../status-matrix.md)
