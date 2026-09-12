# Sumika Next

新版 Sumika 基于 Harness 中立架构，默认适配 DSH，目标是 Codex 日用开发平替。

当前计划见 [用户批准的完整计划](docs/project/approved-plan.md)，恢复工作先读
[交接记录](docs/project/handoff.json) 和 [阶段验收](docs/project/phase-03-acceptance.md)。

环境：Windows、Python 3.11+、Node 24、pnpm 11.19.0。

```powershell
python -B -m sumika_next.cli check
python -B -m sumika_next.cli handoff
python -B -m sumika_next.cli receipt --input <project-relative.json>
python -B -m unittest discover -s tests_next -v
pnpm --dir runtime/dsh install --frozen-lockfile --ignore-scripts
python -B tools/probe_dsh_next.py
```

`receipt` 把人工提供的成果 JSON 规范化为 `docs/project/receipts/<task_id>.json`，记录
`provenance=operator_report`、当前 Git HEAD 和 UTC 时间；已有 task_id 拒绝覆盖，校验失败不写任何文件。
它是操作者声明，不是独立验证，也不改变 `phase_status`；`handoff` 会追加最近 3 条成果摘要与验证/剩余项。

最后一个命令运行真实 DSH 的隔离生命周期验收，不读取日用 profile、不调用模型。
默认依赖固定为 `@deepseek-ai/dsh@0.1.5-rc.2`。安装/profile/回退见
[运行说明](runtime/dsh/README.md)。核心可选用 `python -m pip install .` 安装；不依赖 DSH 的 Python 包。

阶段 0–3 已完成连续性基础、Harness 边界、DSH 发行验收及真实日用开发闭环。
使用 `python -B -m sumika_next.cli run` 打开原生 Web；用法见
[日用流程](docs/project/daily-workflow.md)。下一阶段 P4 接入自动连续性记录。
