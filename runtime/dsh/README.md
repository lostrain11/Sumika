# 固定 DSH 运行环境

初始版本：`@deepseek-ai/dsh@0.1.5-rc.2`。npm 的 `latest` 仍为 rc.1，用户选择包含 RC 的最新发布版，因此采用 `next` 标签指向的固定 rc.2；运行时不追随标签。

## 安装与启动

在项目根执行 `pnpm --dir runtime/dsh install --frozen-lockfile --ignore-scripts`。
`package.json` 固定直接版本，`pnpm-lock.yaml` 固定全部解析结果和包完整性摘要。
`release.json` 绑定这两个文件及实际 CLI 入口/package 元数据，启动前核验；不修改 `node_modules` 修补上游。

安装目录为 `runtime/dsh/node_modules`；用户数据为仓库外或被忽略的独立 `DSH_HOME`。
自动验收使用 `.sumika-next/acceptance-*/home`，结束后停止自己创建的进程并清理自己的临时目录。
持久使用可采用 `.sumika-next/home-0.1.5-rc.2`，不要指向旧日用目录。

`python -B tools/probe_dsh_next.py` 是不调用模型的真实生命周期验收。普通原生 Web 启动方式：

```powershell
$env:DSH_HOME = Join-Path (Get-Location) '.sumika-next/home-0.1.5-rc.2'
node runtime/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js web --host 127.0.0.1 --port 0 --no-open
```

这是 DSH 原生客户端，按其原生权限策略工作。Sumika 阶段 1 的新增写入入口是 `Execution.dispatch`，由可信宿主提供 `Authority`；不要将批准方法暴露给模型或普通 RPC。

## 更新与回退

升级在新的 Git 分支和独立 profile 中修改固定版本并生成新锁文件。检查插件许可证、API 契约、原生权限和实际能力，再更新发行摘要与验收记录；不能仅因启动成功切日用版本。

回退同时选择已保存的 Git 发行提交与该版本 profile 的备份副本。不得将新版写过的 profile 直接交给旧版猜测兼容；先保留当前数据，再在新目录恢复旧副本。不覆盖现有数据、不清理旧分支。

阶段 2 仍需真实文件/终端/Plan/Skills/MCP/子 Agent/事件流/活动取消/恢复验收，以及插件组合的兼容检查。
