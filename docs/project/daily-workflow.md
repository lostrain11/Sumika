# Sumika 日用开发流程

## 启动

在新版项目根安装冻结 DSH（见 `runtime/dsh/README.md`），运行：

```powershell
python -B -m sumika_next.cli run
```

默认使用当前锁定版本对应的 `.sumika-next/daily/<version>` 独立 profile，并打开 DSH 原生 Web。没有复制已有凭据、自动发起模型任务或自动改选模型。首次使用在原生设置中配置模型；需要复用既有 profile 时显式指定 `--home <路径>`，先核对版本兼容及备份。

启动时可用 `--workspace <绝对或相对目录>` 创建该目录的原生会话；不传此参数则不创建会话，直接从 Web 历史恢复。会话和工作区的选择、重命名及模型配置均由原生 Web 处理。`--no-browser` 用于无图形检查，不输出带 token 的启动 URL。

Ctrl+C 停止本次受管实例；保留 profile 会话历史。再次使用同一 `--home` 重新打开原生 Web。不要将停止实例当成撤销已执行的文件或终端操作。

## 规划、执行与交接

1. 进入工作区，阅读 `AGENTS.md` 和现有项目记录，确认需求、当前进度及实际 Git 状态。
2. 使用原生 `/plan` 制定计划和审阅；批准后执行。让原生子 Agent 处理独立任务或审查。
3. 文件、终端、测试、构建、日志、Skills 和 MCP 使用 DSH 原生工具。配置第三方工具前确认来源、作用域和权限。
4. 需要暂停时取消当前任务，查看实际 diff 与结果，记录已完成/未验证部分。恢复时从历史与交接文件继续；不要自动重复结果未知的操作。重试也须先核对实际副作用。
5. `/compact` 或会话/模型切换后重新阅读项目记录。`python -B -m sumika_next.cli handoff` 输出原文索引、计划状态和最近成果；记录不增加授权。

## 显式成果记录

准备项目内的 JSON 输入文件，例如 `.sumika-next/result-input.json`：

```json
{
  "task_id": "example-task",
  "session_id": "native-session-id",
  "summary": "说明实际完成内容",
  "changes": ["修改了哪些内容"],
  "verification": [{"command": "python -B -m unittest discover -s tests_next -v", "result": "passed"}],
  "remaining": ["仍需验证的内容"],
  "next": "下一步具体动作"
}
```

```powershell
python -B -m sumika_next.cli receipt --input .sumika-next/result-input.json
python -B -m sumika_next.cli handoff
```

结果写入 `docs/project/receipts/<task_id>.json`，绑定当前 Git HEAD 与 UTC 时间；不覆盖同 ID 已有结果。验证状态只允许 `passed`、`failed`、`not_run`，保留失败和未运行记录。所有条目标明 `operator_report`，属于操作方声明，并非独立验证或阶段完成证明。完成状态仍须在计划/进度文件中依据证据维护。

输入路径相对 `--root` 且不能越出项目；task_id 为可移植文件名。不要在成果记录中放入密钥或不必要的个人数据。P4 独立扩展的安装、enabled 开关、自动捕获和专用工具见 extensions/continuity/README.md；receipt 保持独立的显式成果格式。
