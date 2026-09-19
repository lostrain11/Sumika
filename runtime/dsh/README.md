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

每次发行更新必须通过完整门槛：

```powershell
python -m venv .sumika-next/verify-env
.sumika-next/verify-env/Scripts/python.exe -m pip install -e '.[dsh]'
.sumika-next/verify-env/Scripts/python.exe -X utf8 -B tools/verify_phase2.py
```

该门槛使用真实 DSH、原生工具和本地确定性模型服务，结果及事件证据保留在 `.sumika-next/p2-*/`、`.sumika-next/p2-recovery-*/`。
固定组合为 standard agent preset、原生 Skills、子 Agent、stdio MCP；不需要额外社区插件或 PowerShell 替换插件。MCP 测试服务仅用于验收。
升级先保留当前发行与 profile，再在独立目录安装候选版本；明确检查版本、依赖变更后更新候选摘要，跑冻结安装和完整门槛，只有通过才登记为已验收。失败保留当前组合，不自动切换或重放任务。

Windows 测试工作区使用普通 `mkdir` 继承项目 ACL。Python 3.14 的 `mkdtemp()` 使用专门的受保护 ACL，与正常项目权限不同，会导致受限令牌无法读取文件、PowerShell 工作目录回落；不要为此关闭沙箱。既有特殊 ACL 工作区需单独评估，不能宣称所有 ACL 布局均受支持。

可复现命令：`python -B tools/verify_development_sandbox.py --python-temp`。
证据 `.sumika-next/development-sandbox-795d8b9407d54bb9bbc46a7c594e3438/report.json`
确认同一原生 `workspace-write` 调用内，私有临时目录拒绝读写，普通工作目录可读写。
测试夹具参考 `tools/development_tasks/audit_cli_tests.py` 的 `evidence_directory()`：
只在已授权工作目录内创建唯一目录，保留结果，不修改 ACL、不扩大沙箱权限。

## P3 日用与浏览器验收

开发迭代接线可运行 `python -B tools/verify_development_sandbox.py --iteration`。
复用真实 DSH、原生 workspace-write 与本机确定性模型夹具，在独立目录创建两个
关联模块，验证失败测试、未读编辑拒绝、重新读取后修正、测试通过，以及重启后
工具历史和源文件保留、无模型重放。测试文件不可变，不安装窄范围 probe guard。
它不是实际模型智能、交互审批或中等规模开发验收；测试脚本失败返回非零退出码。

注意：原生 `write` 成功并不建立 `edit` 所需的已读版本。修改前先 `read`；
遇到 `FS_STALE_VERSION` 应重新读取并重新判断修改，不关闭原生版本保护。
首轮失败证据保留在 `.sumika-next/development-sandbox-221bc45d5ccc42359061a0cd79c76ab5/`；
修正夹具后的通过证据在 `.sumika-next/development-sandbox-aa276220443b4df99cd29882cb7f5edc/report.json`。

在项目根运行 `python -B -m sumika_next.cli run`，默认使用 `.sumika-next/daily/<version>`；工作区、恢复和成果记录见 [日用流程](../../docs/project/daily-workflow.md)。

原生浏览器回归使用系统 Edge 和本地模型替身：

```powershell
.sumika-next/verify-env/Scripts/python.exe -m pip install -e ".[dsh,browser-test]"
.sumika-next/verify-env/Scripts/python.exe -X utf8 -B tools/verify_dsh_web.py
```

这项检查验证页面实际发送与显示；真实模型开发、审查与重启恢复证据见 [P3 验收](../../docs/project/phase-03-acceptance.md)。
