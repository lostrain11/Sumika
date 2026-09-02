# 网页聊天故障手册

本手册适用于 BrowserSkill CLI `0.1.11`、extension `0.1.7`、`web-chat/v1` 和
RapidOCR-json `1.1.0`。当前状态仍以[状态矩阵](../status-matrix.md)为准。

## 证据顺序

1. `snapshot` 的 DOM/ARIA 用来判断控件身份、输入值、登录和页面就绪。
2. 有声明式回复选择器时，Core 内部的 bounded HTML projection 用来提取回复。
3. 两者冲突、提交不明、回复超时或疑似遮罩时才调用截图 OCR；OCR 只作视觉佐证。
4. 固定夹具通过后仍需单站真实短消息，最后才执行五站 `3 + 2` 聚合。

不得把工具调用成功当作用户可见动作已经完成。任何日志、RPC 和数据库都只能记录 OCR
是否可用、置信度区间、布尔裁决、行数和错误码，不能记录截图路径、图像、OCR 正文、提示词、
网页回复、Cookie 或凭据。BrowserSkill 创建的临时 PNG 仍由 BrowserSkill/系统临时目录负责
生命周期；Sumika 只在当前调用内读取其路径，不复制、不登记，也不因清理而触碰其他文件。

## 发送裁决

| DOM/ARIA | OCR | 处理 |
| --- | --- | --- |
| 输入已清空或出现新 assistant 节点 | 任意 | 已提交，进入同一回合等待 |
| 原提示仍在输入框 | 同位置仍可见或不可用 | 未发送，尝试下一个已声明发送方式 |
| 原提示仍在输入框 | 显示已离开输入位置 | 证据冲突，标记不确定且禁止重发 |
| 不确定 | 原提示仍在输入位置 | 未发送，尝试下一个已声明方式 |
| 不确定 | 中高置信度显示已离开输入位置 | 已提交，进入等待 |
| 不确定 | 不确定或不可用 | `possibly-sent`，禁止重发 |

OCR 看见新回复但 DOM/HTML 无法定位时返回
`response-visible-extraction-failed`。这说明站点回复提取器需要更新，不允许把整页 OCR 文本
当作正式回答。验证码、登录、付费升级或权限遮罩返回 `waiting-human`。

## 常见症状

### 长提示仍留在输入框

- 证据：发送动作返回成功，但连续快照仍显示完整输入值；OCR 可确认文本位置未变。
- 已确认原因：站点可能接受了 click/Enter 事件但没有提交，或选择器命中了错误按钮。
- 处理：继续下一个已声明的发送选择器；所有证据不确定时停止，绝不再次填充提示。
- 失败做法：只相信 click 的 `executed=true`，或超时后从头发送。

### 回复肉眼可见但提取超时

- 证据：DOM/ARIA 没有新 assistant 节点，HTML projection 为空，而 OCR 相对发送前基线出现
  新的可见文本。
- 原因状态：站点选择器或回复角色标记变化；在定位到实际 DOM 前只算假设。
- 处理：保持原 attempt 为 `response-visible-extraction-failed`，更新该站声明式 response
  selector 并先跑固定夹具，再做一次真实短消息。
- 失败做法：抓取整个页面文本、返回 OCR 正文、或创建第二次发送来“确认”。

### 页面看似登录但 Route 不可用

- 依次检查授权账号标记、聊天就绪标记、当前域名、`chat.read`/`chat.send` consent 和
  Supervisor catalog 刷新。
- 历史侧栏中的“登录”文字不是登出证据；发送按钮也不是登录证据。
- 检查或授权完成后立即刷新 route catalog，不依赖 Core 重启。

### 五站打开多个任务栏窗口

- BrowserSkill/Chromium 的一个窗口只能属于一个持久浏览器 Profile。
- 相同 `browser_profile_id + browser_instance` 的网页档案会共享一个 Session，各用独立标签页；
  不同 Profile 必须保持独立，不能迁移 Cookie 或静默合并。
- 要验收一窗五标签，先创建一个新的共享命名 Profile，再由用户在该窗口逐站登录并授权。
- Agent 创建的共享窗口在全部 Worker 释放 60 秒后关闭；手动登录窗口不受该定时器影响。

## 验证命令

```powershell
Set-Location backend
$env:PYTHONPATH = 'src'
python -m unittest tests.test_visual_evidence tests.test_browser_runtime tests.test_web_chat tests.test_dynamic_route_supervisor tests.test_web_chat_server
Set-Location ..
python tools/check_docs.py
git diff --check
```

真实验收按 DeepSeek、ChatGPT、智谱、Qwen、Kimi 逐站执行：登录检查、短消息提交、DOM 回复
提取、OCR 佐证、停止 Session。五站全部单测通过后，才执行两批聚合并确认没有重复发送、
跨成员答案泄漏、遗留 BrowserSkill Session 或凭据日志。
