# Sumika Next

新版 Sumika 基于 Harness 中立架构，默认适配 DSH，目标是 Codex 日用开发平替。

## 当前交付状态（2026-10-09）

源码分支 `codex/sumika-next-dsh` 已推送到
[GitHub](https://github.com/lostrain11/Sumika/tree/codex/sumika-next-dsh)。GitHub 上已有一个
`v0.1.0-internal.20260920` 草稿预发布，包含可安装的 K 版 EXE；它仍是内部使用的草稿，
不是公开发行。最新本机安装器仍是 L2 中文向导
`E:/SumikaBuild/wizard-l2/Sumika-Setup-2026.09.20-l.exe`（已在本机完成安装、启动、个人数据迁移和卸载保留验证），
**但它落后于当前源码**：2026-10-08/09 的陪学与 DSH 升级工作只提交了源码，未打包；
最终安装候选、安装/升级/回退验收由交付包 P8 单独执行，见
[冻结执行稿](docs/project/companion-implementation.md)顶部。不要用旧安装器代表当前源码能力。

源码仓库不包含安装包、个人数据、模型权重或运行缓存；安装和验收记录见
[内部使用验收](docs/project/internal-use-acceptance.json)、[安装与个人数据](docs/project/setup-and-personal-data.md)
和 [内部开发说明](docs/project/internal-use-development.md)。

当前计划见 [用户批准的完整计划](docs/project/approved-plan.md)，恢复工作先读
[交接记录](docs/project/handoff.json)、[冻结执行稿](docs/project/companion-implementation.md)
和 [阶段验收](docs/project/phase-03-acceptance.md)。

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

阶段 0–4 已完成连续性基础、Harness 边界、DSH 发行验收及真实日用开发闭环；
P4-UI、P5、P6 进行中（现状以 `docs/project/plan.json` 为准）。
隔离环境已验证 DSH `0.2.0-rc.2` 候选，日用运行时未切换。
使用 `python -B -m sumika_next.cli run` 打开原生 Web；用法见
[日用流程](docs/project/daily-workflow.md)。P4 通过[独立连续性扩展](extensions/continuity/README.md)接入记录。
[P4-UI 设计](docs/project/ui-design-plan.md)由用户另选模型负责；按最新授权并行推进非 UI 的 P5 能力。
[独立办公文件扩展](extensions/office/README.md)已完成基础 Skill、文件库和原生终端接线；
[验收与限制](docs/project/phase-05-office-acceptance.md)明确区分基础文件操作与尚未验收的版式、公式计算等能力，P5 尚未完成。
