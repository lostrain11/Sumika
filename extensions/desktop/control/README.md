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
