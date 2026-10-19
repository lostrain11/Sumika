# 通用桌面控制适配层

首个 provider 复用 `pywinauto`（Windows UI Automation/控件树）、`PyWinCtl`（窗口枚举与定位）和 `PyAutoGUI`（跨应用鼠标键盘与截图）。选择依据与候选比较见 `docs/project/desktop-control-reuse.md`。

本层是 Harness 中立的独立适配，不实现 Agent 循环，也不自动决定点击目标。默认只读：`status`、窗口枚举、截图。写操作必须显式传入 `--confirm`，并且当前只实现坐标点击作为受控低级动作；后续应优先使用控件语义定位，动作前重新截图/确认，动作后验证结果。

```powershell
python control.py status
python control.py windows
python control.py screenshot --output screen.png
python control.py click --x 100 --y 200 --confirm
```

它不绕过 DSH 的授权、取消或审批边界；终端启动时仍由 Harness 管理。游戏反作弊、管理员权限、UAC、受保护窗口和后台窗口控制没有被宣称支持。

## 已接通的语义动作与后验（2026-10-18）

以上`control.py`是低级CLI历史入口；当前能力注册为`desktop/windows-uia`时，通用服务的`inspect`和`act`可使用UIA语义动作。前端通过「能力 → 桌面控制」开关启停，在「能力 → 管理模块」查看`windows-uia`实现；动作仍由原生工作台工具/终端执行，没有新增动作按钮。

`extensions.desktop.service`的`desktop/act`已接入`authorized_action.execute`，透传`automation_id`、`control_type`、`text`、`keys`及`expected_snapshot_hash`。先检查批准、目标和动作参数、验证配置，再调用UIA。动作类型为`set_text`/`invoke`/`focus`/`minimize`/`maximize`/`restore`/`hotkey`；文本/按键和窗口参数由实际任务提供，模型不得猜目标。快照不符在变更前拒绝。`approved=true`仅为适配层检查，不能代替Harness对完整请求的原生审批。

示例请求结构（不要直接对用户窗口照抄；须先查看真实handle/pid并取得对应批准）：

```json
{"capability":"desktop","operation":"act","arguments":{"handle":123,"process_id":456,"action":"set_text","text":"new text","approved":true,"expected_snapshot_hash":"<本次已批准快照SHA256>"}}
```

静态`verification_image`配合`expected_text`仅证明给定图片的文字；因为无法证明是动作后新采集，结果保持`unknown`并标注`action_executed=true,retry_allowed=false`。可信宿主可传入单独获准的`capture_verification(handle=...,process_id=...)`回调，在动作完成后取新图进行OCR。回调不能通过JSON请求传入，也没有自动接入屏幕采集或新增截屏授权。

原生动作尝试中报错、动作后控件检查失败、捕获/OCR失败或未证明预期文字，均保留`unknown`与禁止自动重试信息；不得以异常为由重复点击或输入。`performed`只表示原生动作调用和控件后验完成，不能保证应用业务成功。OCR匹配也只证明文字，不能证明语义结果。

维护验收：`python -X utf8 -B tools/verify_desktop_owned_window.py [--product <候选目录>] [--output <证据根目录>]`，使用选定桌面解释器、新建隐藏Win32 Edit及隔离能力SQLite，不截取用户画面、不发送全局按键或坐标点击。测试窗口在结束时销毁，窗口worker确认退出。前台窗口可能因用户活动变化，报告单独记录是否变成测试进程，不能宣称测试期间用户完全没有切换应用。
