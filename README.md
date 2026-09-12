# Sumika Next

新版 Sumika 基于 Harness 中立架构，默认适配 DSH，目标是 Codex 日用开发平替。

当前计划见 [用户批准的完整计划](docs/project/approved-plan.md)，恢复工作先读
[交接记录](docs/project/handoff.json) 和 [阶段验收](docs/project/phase-01-acceptance.md)。

环境：Windows、Python 3.11+、Node 24、pnpm 11.19.0。

```powershell
python -B -m sumika_next.cli check
python -B -m sumika_next.cli handoff
python -B -m unittest discover -s tests_next -v
pnpm --dir runtime/dsh install --frozen-lockfile --ignore-scripts
python -B tools/probe_dsh_next.py
```

最后一个命令运行真实 DSH 的隔离生命周期验收，不读取日用 profile、不调用模型。
默认依赖固定为 `@deepseek-ai/dsh@0.1.5-rc.2`。安装/profile/回退见
[运行说明](runtime/dsh/README.md)。核心可选用 `python -m pip install .` 安装；不依赖 DSH 的 Python 包。

阶段 0/1 提供连续性记录、受管 Harness 生命周期及安全基础。完整开发工具、模型调用、
原生 Web 日用闭环和主动运行任务取消的验收按阶段 2/3 继续，不把基础验收当作日用平替已完成。
