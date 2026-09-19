# 模型与连接：三类用途与共享本地模型库

## 当前实现

- 工作模型：由 DSH 工作台原生配置管理，Sumika 设置页仅展示说明并提供进入工作台入口。
- 角色模型：沿用现有角色配置，角色会话与工作会话隔离。
- 辅助模型：独立 `auxiliary` 配置，默认关闭；支持 Ollama 与 HTTPS OpenAI-compatible provider，失败返回 unknown/disabled，不自动切换。
- 本地模型库：用户指定绝对路径后只读扫描 GGUF、safetensors、ONNX 与 Ollama manifest。发现文件不等于可运行；仅完整 Ollama manifest 可填入角色或辅助模型名称，仍需用户核对 endpoint。

## 约束

本轮辅助模型只做简单提示词措辞润色预览；不接任务意图或项目分类。宿主保留项目核验、权限、审批与派发权；原文、代码、工具参数和授权不由模型改写。

## 后续

补充实际 UI 的增强预览确认、辅助分类与角色交接去重，以及不同 Ollama library 的 endpoint 可用性检查；不下载模型、不把模型权重复制进 Sumika。

## MiniCPM 窄范围接线

复用资产：`extensions/models/ollama.py`、`auxiliary.py`、原生 `conversation.input.right` 星光按钮；采用改造后使用。设计稿未画润色弹窗，本项来自用户已批准的提示词优化预览需求，不增导航。

个人配置选用已安装的官方 MiniCPM5，角色/工作模型保持不变；辅助总开关仍关闭。生成仅由按钮点击触发，单次请求无重试。JSON Schema 控制输出形式；约束分句、内联代码、数字等做保守原文检查。代码块与 diff 跳过。校验只覆盖字面边界，不声称证明语义等价。确认后仅替换原草稿，会话/草稿/附件变化时拒绝覆盖。

验证：20 项 Python 测试通过；`verify_prompt_preview_ui.mjs` 用真实浏览器及替身槽位/provider 验证关闭、会话变化、草稿变化、明确确认，未执行模型或发送会话。真实 MiniCPM 8 个合成样例，4 个进入预览、4 个拒绝并保留原文。原分类排名因评分契约不一致已撤回。

## 最新决定：先不接入

用户要求先测能胜任的工作。润色工具栏已恢复未接通，辅助开关关闭；上文预览实现仅为历史进度，不代表当前已启用。调研结论见 minicpm-task-survey.md。
