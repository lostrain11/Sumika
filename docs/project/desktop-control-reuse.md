# 通用桌面控制复用调研

## 选择

首个 Windows 基线采用三层组合：

- `pywinauto`（BSD-3-Clause，约 6k GitHub stars）：优先提供 Windows UI Automation 控件树、窗口和语义控件操作，适合可访问性树完整的 WPF/Win32/Qt 应用。
- `PyWinCtl`（BSD 系列）：统一窗口枚举、标题和几何区域，适合在 OCR/视觉之前筛选目标窗口。
- `PyAutoGUI`（BSD-3-Clause，约 12k stars）：跨平台鼠标、键盘和截图，作为最后一级坐标/像素 fallback；坐标脆弱，不能替代控件定位。

实现位于 `extensions/desktop/control/`，不导入 DSH，默认只读；点击需要显式 `--confirm`。真正接入 Agent 时仍需由 DSH 原生审批、取消和工作区策略包住，不把这个命令行脚本当作安全沙箱。

## 候选比较

| 项目 | 观察 | 结论 |
| --- | --- | --- |
| [FlaUI-MCP](https://github.com/shanselman/FlaUI-MCP) | MIT；FlaUI + Windows UI Automation，MCP 服务器，语义控件比纯坐标可靠 | 后续可作为 DSH MCP 候选；当前先用 Python 独立适配，避免额外 .NET 服务和协议耦合。 |
| [Screenhand](https://github.com/manushi4/Screenhand) | 项目描述覆盖截图、UI 控制、浏览器和 OCR，面向 MCP 客户端 | 值得实测，但 AGPL 与实现成熟度/权限边界需先审查，暂不直接接入。 |
| [Agent-S](https://github.com/simular-ai/Agent-S) | Apache-2.0；完整 computer-use agent 框架 | 包含模型循环和规划，超出 Sumika 的独立能力层；可研究其 grounding/动作验证，不复制 Agent 循环。 |
| [OpenAI CUA sample](https://github.com/openai/openai-cua-sample-app) | MIT；演示 Computer Use API 的截图/动作协议 | 依赖特定云模型与 API，不作为本地默认 provider；可参考动作确认和循环结构。 |
| PyRPA / 微信自动化等 | 通常基于 pyautogui 或 pywinauto 的应用脚本 | 说明组合方式成熟，但应用专用脚本不能当作 Sumika 通用能力。 |

## 对三类场景的映射

辅助操作使用“窗口枚举 → UIA 控件树 → OCR/截图 fallback → 显式动作 → 结果截图/控件状态验证”。陪看/陪玩使用“采集帧 → 变化检测和节流 → OCR/视觉模型 → 状态事件 → 评论或翻译”，不应每帧调用模型。真正参与游戏需要输入注入、状态策略和停止机制；许多开源游戏 Agent 只对单一游戏训练或脚本化，不能宣称通用。

当前实现只完成窗口枚举、截图和显式坐标点击基线；没有实现连续采集、视觉模型判断、自动评论、翻译叠加、游戏策略或后台注入。
