# Sumika 状态矩阵

本表是项目功能状态的唯一事实源。`已实现` 表示当前首版有可验证入口，
`部分实现` 表示协议或参考实现存在但默认能力、真实后端或隔离边界仍缺失，
`规划中` 表示只保留架构位置或设计方向。

| ID | 状态 | 当前入口 | 主文档 | 验证证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `local-llm` | 已实现 | `run_core` / `run-desktop`、Modules | [local-model](architecture/local-model.md) | [setup script](../tools/setup-ollama.ps1)、[provider tests](../backend/tests/test_providers.py) | 评估更多本地模型与真实协议 |
| `provider-profiles` | 已实现 | Modules > 实现方式 | [provider profiles](architecture/provider-profiles.md) | [profile tests](../backend/tests/test_provider_profiles.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 增加更多已测试协议适配器 |
| `ccswitch-import` | 已实现 | Modules > 自定义连接、Developer | [CC Switch](integrations/cc-switch.md) | [compatibility tests](../backend/tests/test_ccswitch_compatibility.py)、[checker](../tools/check_ccswitch_compatibility.py) | 按固定基线人工审查上游更新 |
| `chat` | 已实现 | Chat | [protocol](architecture/protocol.md) | [server tests](../backend/tests/test_server.py)、[frontend shell](../frontend/main.js) | 持续完善流式状态与错误呈现 |
| `characters` | 已实现 | Characters | [characters](architecture/characters.md) | [avatar tests](../backend/tests/test_avatar.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 多角色体验与角色导入细节 |
| `modules` | 已实现 | Modules | [modules](architecture/modules.md) | [module tests](../backend/tests/test_modules.py)、[UI smoke](../frontend/tests/smoke.spec.js) | 继续增加真实可替换实现 |
| `tasks` | 部分实现 | Tasks | [tasks](architecture/tasks.md) | [task tests](../backend/tests/test_tasks.py)、[runner tests](../backend/tests/test_task_runner.py) | Workspace、diff、回滚和真实 Runner |
| `avatar-vrm-desktop` | 已实现 | Chat、Characters、桌宠模式 | [Avatar](architecture/avatar.md)、[desktop shell](architecture/desktop-shell.md) | [avatar tests](../backend/tests/test_avatar.py)、[UI smoke](../frontend/tests/smoke.spec.js) | Live2D 驱动与更多动作资源审计 |
| `plugins-manifest` | 部分实现 | Developer | [manifest](architecture/manifest.md) | [plugin tests](../backend/tests/test_plugins.py) | 隔离 Runner、签名与依赖管理 |
| `audio` | 部分实现 | Modules（默认关闭） | [audio](architecture/audio.md) | [audio tests](../backend/tests/test_audio.py) | 接入真实 ASR/TTS/VAD 软件并完善权限 UI |
| `memory` | 部分实现 | History / Modules（默认关闭） | [memory](architecture/memory.md) | [memory tests](../backend/tests/test_memory.py) | 检索策略、合并确认与更多外部后端 |
| `vision` | 部分实现 | Modules（默认关闭） | [vision](architecture/vision.md) | [vision tests](../backend/tests/test_vision.py) | Tauri 捕获桥与敏感性路由策略 |
| `snapshots` | 已实现 | Developer / History | [architecture](architecture/README.md) | [storage tests](../backend/tests/test_storage.py)、[server tests](../backend/tests/test_server.py) | 加密备份与更细的恢复预览 |
| `live2d` | 规划中 | 暂无 | [Avatar](architecture/avatar.md) | [reference map](ui/reference-map.md) | 选择运行时、资源导入和许可证边界 |
| `virtual-world` | 规划中 | 暂无 | [architecture](architecture/README.md) | [architecture index](architecture/README.md) | 先定义场景状态与时间结算模型 |
| `life-agent` | 规划中 | 暂无 | [tasks](architecture/tasks.md) | [tasks design](architecture/tasks.md) | 与 VirtualWorld 分离设计日程和主动性 |
| `remote-runner` | 规划中 | 暂无 | [security](architecture/security.md) | [tools boundary](architecture/tools.md) | 隔离执行、权限和回滚协议 |
| `android-client` | 规划中 | 暂无 | [desktop shell](architecture/desktop-shell.md) | [protocol](architecture/protocol.md) | 配对、认证和远程事件通道 |

## 更新规则

完成一个可验证的用户入口、协议边界或测试夹具后，先更新对应行的状态、入口
和证据，再在专题文档中补充设计细节。没有实现证据时，不得把状态写成
`已实现`。

