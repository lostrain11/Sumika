# Local model runtime

本地模型不是 Sumika 的安装依赖，也没有默认运行时。新工作区不会创建 Provider
档案，LLM 模块默认关闭；`run_core` 与 `run-desktop` 只启动 Sumika，不会
安装 Ollama、启动模型服务、选择模型或下载权重。

用户可以在 Modules 的 Provider 抽屉中选择 Ollama、LM Studio、
llama.cpp server、vLLM、LocalAI 或通用 OpenAI-compatible 模板。模板只填写
可编辑示例，保存后仍需执行真实健康检查，检查通过并明确启用后才可聊天。
`qwen3:4b` 只是 Ollama 模板中的示例模型，不代表推荐、预装或自动下载。

对于协议、UI 和启动冒烟，可以另外登记一个更小的测试档案，例如
`qwen3:1.7b`。它与 4B 使用同一个 OpenAI-compatible 适配器，适合快速确认端点、
流式传输和基本请求；小模型的工具选择、长上下文规划和复杂代码修改质量不应据此
判定为日用 Agent 可用。测试档案不会自动成为默认模型，日常档案应由用户明确选择。

## Optional Ollama helper

`tools/setup-ollama.ps1` 是 Windows 专用、由用户主动运行的辅助工具。调用时
必须显式传入 `-Model`：

```powershell
.\tools\setup-ollama.ps1 -Model 'qwen3:4b'
```

脚本会寻找用户已经安装的 Ollama，必要时启动服务，检查所选模型并在缺失时拉取
该模型。只有显式传入 `-InstallIfMissing` 才会安装 Ollama；正常 Sumika
启动从不传入这个开关。使用 `-SkipPull -NoWarmup` 可以只检查现有服务和模型。

模型缓存可通过 `-ModelsDir` 或 `SUMIKA_OLLAMA_MODELS` 指定，缓存不会进入
仓库。下载可使用当前命令范围内的 `SUMIKA_DOWNLOAD_PROXY`；脚本结束后恢复
调用者的代理环境，不修改系统代理、TUN、模式或节点。

### Existing Ollama service

`OLLAMA_MODELS` is read when the Ollama server process starts. Setting it in a
later PowerShell window does not reconfigure an already running Ollama tray
application. If `/api/tags` is empty while the requested model manifest exists
in another directory, the helper now stops before pulling a duplicate model.
After closing Ollama from its tray menu, start a fresh service with the existing
cache:

```powershell
$env:OLLAMA_MODELS = 'E:\AI\OllamaModels'
$env:OLLAMA_HOST = '127.0.0.1:11434'
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

Then verify `ollama list` or `GET /api/tags`. To leave the current service
untouched, use a separate port and point the Sumika profile at that port:

```powershell
.\tools\setup-ollama.ps1 -Model 'qwen3:4b' -ModelsDir 'E:\AI\OllamaModels' -Port 11435 -SkipPull
```

Ollama profile 使用其 OpenAI-compatible endpoint。对于 Qwen3，适配器使用
`think=low` 并丢弃 reasoning delta，只把可见回答流式发送给 UI。模型服务
不可用时返回 `unconfigured` 或 `error`，不会回退到 Fake 回复。

模型大小由用户根据硬件、质量、速度、许可证和磁盘空间自行选择。更大的 tag
必须在 Ollama 或 Provider 抽屉中明确选择，不再通过桌面启动参数隐式切换。

## 相关文档

- [Provider profiles](provider-profiles.md)
- [Desktop shell](desktop-shell.md)
- [根目录快速开始](../../README.md)
