# Sumika Next

新版 Sumika 基于 Harness 中立架构，默认适配 DSH，目标是 Codex 日用开发平替。

## 当前交付状态（2026-10-19）

源码分支 `codex/sumika-next-dsh` 当前包含未提交的主线实现和验收修复，远程或旧安装器不能代表当前工作区。源码 DSH 已固定 `0.2.1-rc.2`；长期记忆治理、行为子记忆、自动模式及既有 UI 已接入，仍在逐功能整体验收。

当前隔离候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r63`，DSH固定 `0.2.1-rc.2`。r63 60485文件库存、实际EXE四组通过；源码全量1412项OK（20跳过，115.429秒，`.sumika-next/review-20261018/full-suite-final23.log`）。r22的配置UI与真实B站前端链路、r20真机摄像头单帧、r16布局/记忆/角色资源/语音证据按各自候选保留。r29真实摄像头/麦克风、真实PDF（含用户指定的个人 PDF）选择/双窗/缩放、前台密码焦点通过；35B 角色模型已通过本机 18083 隧道接通（实回复 3.01 秒）；10分钟持续运行已记录（末轮键盘计数缺失，键盘路径以90秒/5分钟为准）；B站登录态CC字幕已通过（匿名不可得）、真实模型质量与设备完整流程仍未完成；候选未替换日用安装。

逐项点击路径、预期及未验边界见 [已实现功能与操作验收清单](docs/project/feature-usage-and-acceptance.md)；缺陷、最新证据及剩余范围见[主线修复与验收计划](docs/project/repair-and-acceptance-plan.md)。当前先完成P6整体验收；长期愿景暂缓，提示词优化已纳入P6之后，计划使用笔记本本地模型。

源码仓库不包含安装包、个人数据、模型权重或运行缓存；安装和验收记录见
[内部使用验收](docs/project/internal-use-acceptance.json)、[安装与个人数据](docs/project/setup-and-personal-data.md)
和 [内部开发说明](docs/project/internal-use-development.md)。

恢复工作先读 [交接记录](docs/project/handoff.json)、`progress.json`、`plan.json`及[需求原文](docs/project/requirements.json)。原始批准计划见[完整执行稿](docs/project/approved-plan.md)；详细迭代记录移至[历史归档](docs/project/archive/20261018/README.md)。

环境：Windows、Python 3.11+、Node 24、pnpm 11.19.0。

```powershell
python -B -m sumika_next.cli check
python -B -m sumika_next.cli handoff
python -B -m sumika_next.cli receipt --input <project-relative.json>
python -B -m unittest discover -s tests_next -v
node --test extensions/continuity/dsh.test.mjs extensions/roles/dsh.test.mjs extensions/roles/model.test.mjs extensions/desktop/review_dsh.test.mjs extensions/desktop/schedule_dsh.test.mjs tools/development_probe_guard.test.mjs
pnpm --dir runtime/dsh install --frozen-lockfile --ignore-scripts
python -B tools/probe_dsh_next.py
```

Python 全量测试不包含 Node 适配器测试：当前为 Python 1412 项（20 跳过）加 Node 31 项，两者分别运行。

`receipt` 把人工提供的成果 JSON 规范化为 `docs/project/receipts/<task_id>.json`，记录
`provenance=operator_report`、当前 Git HEAD 和 UTC 时间；已有 task_id 拒绝覆盖，校验失败不写任何文件。
它是操作者声明，不是独立验证，也不改变 `phase_status`；`handoff` 会追加最近 3 条成果摘要与验证/剩余项。

最后一个命令运行真实 DSH 的隔离生命周期验收，不读取日用 profile、不调用模型。
默认依赖固定为当前最高已发布 RC `@deepseek-ai/dsh@0.2.1-rc.2`。安装/profile/回退见
[运行说明](runtime/dsh/README.md)。核心可选用 `python -m pip install .` 安装；不依赖 DSH 的 Python 包。

当前阶段状态以 `docs/project/plan.json` 为准；P4-UI、P5、P6仍在验收，P7长期角色与设备愿景暂缓。源码实现、隔离候选与日用安装是不同状态，详细边界见上方当前验收文档。

使用 `python -B -m sumika_next.cli run` 打开原生 Web；日用流程见
[日用流程](docs/project/daily-workflow.md)。连续性记录由[独立扩展](extensions/continuity/README.md)接入，办公文件能力及限制见[扩展说明](extensions/office/README.md)和[验收记录](docs/project/phase-05-office-acceptance.md)。
