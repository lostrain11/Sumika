# 端侧模型与多设备扩展实施记录

状态：接口首版已实现；两个 MiniCPM5 已完成真实短对话测试，模型质量与多设备运行时仍属部分验收。

已实现的独立边界：

- `extensions.models.ollama.OllamaProvider`：健康检查、模型列表、非流式对话和 usage 提取；禁用或异常时失败关闭。
- `extensions.models.device.DeviceRegistry`：显式设备注册、配对令牌哈希、撤销、能力列表和在线探测；不允许未加密公网 HTTP 端点。
- `extensions.roles.handoff`：项目索引、角色任务交接包和工作台提示构造；角色意见标为不可信，不产生授权。
- `extensions.models.usage.UsageStore`：estimated/reported/unknown 三态用量记录及会话/项目累计。
- `extensions.models.prompt.enhance`：保留原文的显式提示词增强，失败时可回到原文。

候选模型只记录来源和评测元数据，不随客户端下载或打包。官方 MiniCPM5-2B 作为稳定基线；第三方 abliterated 版本只作为用户主动选择的实验模型。Qwen3-8B-Heretic、OpenElla-NovelWriter-8B-V2、Neon Veil v2、Ministral-3-8B-Nymphaea-RP、Stheno v3.4 需在测试前核对固定版本、SHA-256、许可证和中文表现。

未实现或未验收：真实 Ollama 模型质量、旧笔记本/安卓节点、FreeToken、DSH token-meter/system-prompt 原生加载、完整 UI 接线、角色闲聊自动跳转工作台。上述边界不授予角色模型文件/终端/浏览器/桌面权限。

FreeToken 仅预留为 Linux x86_64 + NVIDIA 新架构上的 OpenAI-compatible MoE provider；不作为 GTX 1060 或安卓运行时。

## 当前模型评测

用户已明确授权下载候选模型。权重保存在源码之外；8B 下载放在 E 盘，下载回执记录固定 revision、LFS SHA-256 与许可证元数据。

`tools/evaluate_role_models.py` 保留原四项测试，并增加真实传递助手回复的多轮偏好更新、未知事实、越权请求及新会话隔离。`passed` 仅表示获得非空响应，不代表角色质量或工具安全验收通过。

结果与限制见 `local-model-comparison-evidence.json`。两种 MiniCPM5 各完成十次请求；都能使用更新后的偏好，但存在脱离角色或答非所问。尚未选择默认模型。该测试不等同于长期记忆接线、真实角色卡、长对话或游戏资源干扰测试。

现场显卡为 AMD Radeon RX 5700 XT，MiniCPM5 的 `ollama ps` 显示 100% GPU；没有 NVIDIA 不等于 CPU-only。Qwen 首次注册因日用 Ollama 在 C 盘进行兼容转换而空间不足；使用 E 盘模型存储的独立回环测试实例处理，不改日用路由。OpenElla 许可仍需核对。
