# Sumika

[English version](README.md)

Sumika 是一个本地优先、模块化的桌面私人助手基础项目。

## 平台支持

| 平台 | Python 核心与浏览器界面 | Tauri 桌面端 |
| --- | --- | --- |
| Windows | 支持 | 支持 |
| macOS | 支持当前命令；凭据限制见下文 | 实验性 |
| Linux | 支持当前命令；凭据限制见下文 | 实验性 |

三端均要求 Python 3.11 或更高版本。Sumika 首次启动时 LLM 默认关闭，也不会
创建 Provider 档案。正常启动不会安装 Ollama、启动模型服务或下载模型权重。

## Windows

在仓库根目录的 PowerShell 中启动浏览器界面：

```powershell
.\tools\run_core.ps1
```

然后打开 [http://127.0.0.1:8770/](http://127.0.0.1:8770/)。数据保存在
`.sumika`。需要指定其他 Python 时：

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run_core.ps1
```

启动桌面开发端前安装一次前端依赖：

```powershell
npm install --prefix frontend
.\tools\run-desktop.ps1
```

桌面核心监听 `127.0.0.1:8771`，数据保存在 `.sumika-desktop`。前端已经
成功构建后可使用 `-NoBuild`。桌面开发还需要 Rust MSVC target 和 Windows
C++ 构建工具。仓库中的 `.sh` 文件只是旧的 Windows Git Bash 兼容包装器；
Git Bash 不是 Windows 启动前提，也不是文档中的默认入口。

## macOS

当前正式入口是 Python 核心与浏览器界面：

```bash
PYTHONPATH=backend/src python3 -m sumika_core \
  --host 127.0.0.1 --port 8770 --data-dir .sumika
```

然后打开 [http://127.0.0.1:8770/](http://127.0.0.1:8770/)。原生
`tools/run_core.sh` 和 `tools/run-desktop.sh` 入口只预留了位置，尚未实现。
Tauri 桌面端属于实验性能力；贡献者可以准备 Node.js、Rust、Xcode Command
Line Tools 和系统 WebView 后尝试：

```bash
npm install --prefix frontend
npm --prefix frontend run build
SUMIKA_PYTHON="$(command -v python3)" npm --prefix frontend run tauri:dev
```

## Linux

当前正式入口是 Python 核心与浏览器界面：

```bash
PYTHONPATH=backend/src python3 -m sumika_core \
  --host 127.0.0.1 --port 8770 --data-dir .sumika
```

然后打开 [http://127.0.0.1:8770/](http://127.0.0.1:8770/)。原生
`tools/run_core.sh` 和 `tools/run-desktop.sh` 入口只预留了位置，尚未实现。
实验性 Tauri 路径需要 Node.js、Rust、C 工具链，以及
[Tauri 前置依赖](https://v2.tauri.app/start/prerequisites/)列出的
WebKitGTK/系统软件包：

```bash
npm install --prefix frontend
npm --prefix frontend run build
SUMIKA_PYTHON="$(command -v python3)" npm --prefix frontend run tauri:dev
```

macOS 和 Linux 目前没有经过批准的 Keychain/Secret Service 适配器。需要保存
API Key 的 Provider 会以安全失败方式拒绝保存；无需鉴权的本地端点仍可使用。

## 配置模型

进入“模块”，选择“自定义连接”，挑选真实模板，填写端点和模型，测试成功后
再主动启用。Ollama 只是可选实现；选择它时先自行安装。明确选择模型后，可以
使用仅限 Windows 的辅助脚本启动/检查 Ollama 并拉取该模型：

```powershell
.\tools\setup-ollama.ps1 -Model 'qwen3:4b'
```

`qwen3:4b` 只是 Ollama 模板里可编辑的示例，不会默认安装。辅助脚本可通过
`-ModelsDir` 或 `SUMIKA_OLLAMA_MODELS` 使用用户指定的模型缓存目录。

主窗口可以打开可选的置顶“桌宠模式”。模型区域是 Tauri 拖动区域，浮窗可以
在桌面上拖动；模型下方有紧凑聊天输入框，并复用主窗口当前的角色、会话和
provider。Provider、模块、权限和任务配置仍在主窗口中完成。

桌面生命周期和 Python 启动诊断写入 `.sumika-desktop/logs/desktop.log`；核心
边界诊断写入 `.sumika-desktop/logs/core.log`。Developer 页面和
`GET /api/diagnostics` 会显示安全日志位置及运行时计数；Tauri 页面还会显示
受监督核心的 PID、端点和重启次数，详见 `docs/architecture/debugging.md`。
日志不会记录 API Key、聊天正文或原始视觉/音频数据。

桌面端核心默认监听 `127.0.0.1:8771`，浏览器预览默认使用 `127.0.0.1:8770`。

如果要让 Tauri 壳监督已经安装好的 DSH 可执行文件，必须显式选择加入：

```powershell
$env:SUMIKA_DSH_EXECUTABLE = 'D:\Tools\DeepSeekHarness\0.1.1-rc.2\node_modules\.bin\dsh.cmd'
$env:SUMIKA_DSH_AUTOSTART = '1'
.\tools\run-desktop.ps1
```

如果尚未安装固定版本，可以先显式执行一次：

```powershell
.\tools\setup-dsh.ps1 -Proxy 'http://127.0.0.1:6064'
```

脚本只写入 `D:\Tools\DeepSeekHarness\0.1.1-rc.2`，不修改 PATH 或全局
DSH。安装完成后把输出的 executable 路径设置给
`SUMIKA_DSH_EXECUTABLE`；桌面端会使用 `.sumika-desktop\dsh-profile` 作为
隔离 `DSH_HOME`。

桌面壳会把 DSH 生命周期写入 `.sumika-desktop/logs/dsh.log`，并把
`.sumika-desktop/dsh-profile` 作为 `DSH_HOME`。没有同时设置这两个变量时不会
启动 DSH；Agent 页面仍可以通过 `SUMIKA_DSH_ENDPOINT` 连接用户手动启动的实例。

## 核心能力

首版核心只使用 Python 标准库，提供由 Ollama 或其他真实端点支持的
OpenAI-compatible provider、外部 JSONL 进程边界、SQLite 会话/事件/快照、
JSON-RPC 命令和 WebSocket 事件流，也提供经过批准门控的外部工具 JSONL 边界。

新工作区通过 Provider 档案配置 OpenAI-compatible 端点。
`SUMIKA_OPENAI_BASE_URL`、`SUMIKA_OPENAI_MODEL` 和
`SUMIKA_OPENAI_API_KEY` 只作为旧版已启用配置的迁移输入，不会在新工作区创建或
启用档案。`SUMIKA_COMMAND_PROVIDER` 可用于显式登记外部命令适配器。

生产 Provider 目录不会注册 Fake provider。确定性测试替身只位于
`backend/tests/fixtures`，并由测试显式注入。

可选的 **Agent** 页面通过固定版本的 DeepSeek Harness Web API 连接
(`0.1.1-rc.2`，默认 `http://127.0.0.1:3080`)。Sumika 使用隔离 profile，DSH
未运行时安全失败，不会安装或修改用户全局 DSH。Plan、Skills、MCP、Subagents、
审批和流式事件会通过适配器逐步暴露。当前会话可以导出 DSH 原始会话日志 ZIP，
diff 卡片只显示受限的文件摘要，不透传完整 patch；固定版 Web API 尚无独立 rollback
RPC。同一页面还显示 BrowserSkill 策略层；
首版浏览器只登记隔离 Profile、审批、人工接管和下载 quarantine，不控制 Windows
全局鼠标键盘。

顶部的 `LLM` 入口只显示当前状态并跳转到“模块”页；LLM 的启用和关闭由模块卡片
右侧开关负责，实现方式下拉框只选择真实 provider。关闭后聊天发送按钮会禁用，
核心也会拒绝 `chat.send`，不会生成演示或 Fake 回复。

## Avatar

首次运行会登记随仓库提供的 `AvatarSample_A.vrm` VRoid 样例作为默认 Avatar。
来源和许可证记录位于 `assets/avatars/README.md`。浏览器通过仅本地可用的文件
端点加载 `.vrm`，再使用内置 Three.js/VRM 适配器渲染；如果 WebGL 不可用，
会保留已验证的缩略图作为后备显示。

VRM viewer 的自然站姿、鼠标视线跟随和头部跟随都是运行时效果，不会写回模型
文件。可以在“角色”页按角色关闭或调节这些功能。VRMA 适配器已经预留，但首版
不内置动画素材；未来加载动画必须经过本地 manifest、独立许可证记录和用户确认。

## 文档

- [文档总入口](docs/README.md)：按用户使用、架构、开发接口和外部集成导航。
- [状态矩阵](docs/status-matrix.md)：唯一维护已实现、部分实现和规划中状态的地方。
- [架构索引](docs/architecture/README.md)：协议、模块、Provider、Avatar、任务和安全边界。
- [UI 参考与许可证台账](docs/ui/reference-map.md)：交互参考、来源和复用限制。
- [第三方声明](THIRD_PARTY_NOTICES.md)：已纳入或允许复用的外部组件说明。

## 代码目录和维护

- `backend/src/sumika_core`：核心服务。
- `frontend`：浏览器/Tauri 客户端。
- `plugins/examples`：最小外部进程示例。

新增或完成一项能力后，先更新状态矩阵，再补对应专题文档。可以运行以下命令
检查文档链接和索引覆盖：

```powershell
python tools/check_docs.py
```
