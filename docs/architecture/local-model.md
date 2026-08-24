# Local model runtime

本地模型不是 Sumika 的安装依赖，也没有默认运行时。新工作区不会创建 Provider
档案，LLM 模块默认关闭；`run_core` 与 `run-desktop` 只启动 Sumika，不会
安装 Ollama、启动模型服务、选择模型或下载权重。

用户可以在 Modules 的 Provider 抽屉中选择 Ollama、LM Studio、
llama.cpp server、vLLM、LocalAI 或通用 OpenAI-compatible 模板。模板只填写
可编辑示例，保存后仍需执行真实健康检查，检查通过并明确启用后才可聊天。
`qwen3:4b` 只是 Ollama 模板中的示例模型，不代表推荐、预装或自动下载。

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

Ollama profile 使用其 OpenAI-compatible endpoint。对于 Qwen3，适配器使用
`think=low` 并丢弃 reasoning delta，只把可见回答流式发送给 UI。模型服务
不可用时返回 `unconfigured` 或 `error`，不会回退到 Fake 回复。

模型大小由用户根据硬件、质量、速度、许可证和磁盘空间自行选择。更大的 tag
必须在 Ollama 或 Provider 抽屉中明确选择，不再通过桌面启动参数隐式切换。

## 相关文档

- [Provider profiles](provider-profiles.md)
- [Desktop shell](desktop-shell.md)
- [根目录快速开始](../../README.md)
