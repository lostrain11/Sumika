# Sumika

[English version](README.md)

Sumika 是一个本地优先、模块化的桌面私人助手基础项目。

## 快速启动浏览器版本

在仓库根目录执行。脚本优先使用 `SUMIKA_PYTHON`，否则从 `PATH` 查找
`python`：

```powershell
.\tools\run_core.ps1
```

启动包装器会检查官方 Ollama 安装，并在启动 Sumika 前确保本地模型已经存在。
默认模型是 `qwen3:4b`；如果 Ollama 已经运行，脚本会复用现有服务。使用
`-OllamaModelsDir` 或设置 `SUMIKA_OLLAMA_MODELS` 可以指定模型缓存目录；如果
你自行管理 Ollama，可以使用 `-SkipModel` 跳过模型检查。Git Bash 可以执行
`./tools/run_core.sh` 或 `./tools/run-desktop.sh`；包装器会转换常用的
`--skip-model` 和 `--model=...` 参数，但不会修改系统代理。

如果 `bash` 指向 Windows Subsystem for Linux 的兼容入口，请改用系统中安装的
Git Bash 可执行文件。

需要使用其他 Python 运行时：

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run_core.ps1
```

然后打开 [http://127.0.0.1:8770/](http://127.0.0.1:8770/)。浏览器版本的数据
保存在 `.sumika`。

## 启动桌面开发端

先在 `frontend` 目录安装一次依赖，然后回到仓库根目录执行：

```powershell
npm install --prefix frontend
.\tools\run-desktop.ps1
```

脚本默认从 `PATH` 查找 `python`。如果 Python 位于其他位置，启动前设置
`SUMIKA_PYTHON`：

```powershell
$env:SUMIKA_PYTHON = 'C:\Path\To\python.exe'
.\tools\run-desktop.ps1
```

Git Bash 也可以调用同一个脚本：

```bash
cd /path/to/Sumika
export SUMIKA_PYTHON='C:/Path/To/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/run-desktop.ps1
```

脚本会构建前端、启动 Tauri 2 窗口，并让窗口管理监听在 `127.0.0.1:8771` 的
Python 核心子进程。桌面端数据隔离在 `.sumika-desktop` 中，可以和浏览器版本
独立运行。前端构建完成后，可以使用 `-NoBuild` 加快重复启动。首次运行需要
Rust MSVC 工具链和 Windows C++ 构建工具。

主窗口可以打开可选的置顶“桌宠模式”。模型区域是 Tauri 拖动区域，浮窗可以
在桌面上拖动；模型下方有紧凑聊天输入框，并复用主窗口当前的角色、会话和
provider。Provider、模块、权限和任务配置仍在主窗口中完成。

桌面生命周期和 Python 启动诊断写入 `.sumika-desktop/logs/desktop.log`；核心
边界诊断写入 `.sumika-desktop/logs/core.log`。Developer 页面和
`GET /api/diagnostics` 会显示安全日志位置及运行时计数；Tauri 页面还会显示
受监督核心的 PID、端点和重启次数，详见 `docs/architecture/debugging.md`。
日志不会记录 API Key、聊天正文或原始视觉/音频数据。

桌面端核心默认监听 `127.0.0.1:8771`，浏览器预览默认使用 `127.0.0.1:8770`。

## 核心能力

首版核心只使用 Python 标准库，提供由 Ollama 或其他真实端点支持的
OpenAI-compatible provider、外部 JSONL 进程边界、SQLite 会话/事件/快照、
JSON-RPC 命令和 WebSocket 事件流，也提供经过批准门控的外部工具 JSONL 边界。

使用以下环境变量配置 OpenAI-compatible 端点：

- `SUMIKA_OPENAI_BASE_URL`
- `SUMIKA_OPENAI_MODEL`
- `SUMIKA_OPENAI_API_KEY`
- `SUMIKA_COMMAND_PROVIDER`

生产 Provider 目录不会注册 Fake provider。确定性测试替身只位于
`backend/tests/fixtures`，并由测试显式注入。

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
