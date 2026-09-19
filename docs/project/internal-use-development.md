# 安装后用 Sumika 开发 Sumika

当前内部包 K 是 `Sumika-internal.zip` 和 `install_sumika.ps1` 的组合，安装后运行
`Sumika.exe`。它不是带安装向导的单文件安装 EXE。Python、Node 和固定 DSH
运行时已包含，不需要 WSL；模型权重、个人角色和密钥不在包内。

## 本机安装

包目录：`D:/Code/Sumika/.sumika-next/package/packaged-install-93f1d18bdb564c58b44810cd20bfd718`。
在该目录打开 PowerShell，目标目录须尚不存在：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install_sumika.ps1 -Archive .\Sumika-internal.zip -Destination "D:\Apps\Sumika-K" -Sha256 "570d185ce03007a1e22cf1938fc09d1f23abf159a65b0f1a7566196cbd926ad5" -Shortcut
```

运行 `D:\Apps\Sumika-K\Sumika.exe`。如果原开发版占用 8765，不要按端口杀进程；
可先用独立端口和个人数据目录试用：

```powershell
& 'D:\Apps\Sumika-K\Sumika.exe' -Port 8766 -DataDirectory 'D:\SumikaData\internal-k'
```

独立目录不会自动继承原角色、模型或 DSH Profile；需要在设置或原生工作台中配置。
迁移已有数据请使用 `backup-recovery.md` 的备份/恢复流程，不直接覆盖正在使用的数据。

## 自开发流程

1. 在工作台的原生项目入口打开 `D:\Code\Sumika`，由 DSH 管理工作模型和工具审批。
2. 让 Agent 先读 `AGENTS.md`、`docs/project/handoff.json`、`progress.json`、`plan.json`。
3. 在开发分支上给出具体任务，要求修改源码、运行对应测试、展示 diff 并更新项目记录。
4. 审查后保存 Git 提交。正在运行的安装包与源码目录分开，源码修改不会自动覆盖安装版。
5. 使用 `packaging/README.md` 中的现有构建与验收工具生成新目录中的候选包；通过后再切换。
   保留旧安装和切换前的数据备份，未知任务不自动重放。

可直接发送给工作台的开场任务：

> 阅读项目 AGENTS.md 和 docs/project 中的交接、进度、计划。当前目标是内部自用，
> 公开发行审查和 WSL 不在本轮范围；语音硬件验收暂缓。先核对 Git 与实现，
> 汇报我指定问题的原因，再实施、测试并展示 diff。不要修改 DSH 上游、node_modules，
> 不修改正在运行的安装目录；删除、上传和外部发送按已有授权边界处理。

已验证安装、首启、原生工具/审批及恢复路径；模型开发仍需审查。最近 Pro 开发任务
需要主 Agent 修正，不能承诺无人监督自我升级。未发送的原生附件草稿刷新后可能丢失。

## 源码备份

源码分支：`codex/sumika-next-dsh`。Git 不包含 `.sumika-next` 运行数据、安装包、
模型权重、密钥、DSH `node_modules` 或 .NET 构建输出。BrowserSkill 二进制由本机
固定运行时/内部包提供，也不随此次源码提交上传。源码克隆不是完整可运行安装包；
开发依赖和固定运行时准备见 `runtime/dsh/README.md`、`pyproject.toml` 和 `packaging/README.md`。
