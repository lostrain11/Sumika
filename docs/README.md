# Sumika 文档

这里是 Sumika 文档的总入口。先看[项目状态矩阵](status-matrix.md)，再按
使用、架构、开发接口或外部集成进入专题文档。文档使用中文说明产品行为，
API、协议、类名和代码标识保留 English identifier。

## 当前状态

`status-matrix.md` 是“已实现 / 部分实现 / 规划中”的唯一事实源。专题文档
解释边界、接口和约束，不重复维护功能完成度。

## 用户使用

- [Windows 启动](../README_zh.md#windows)
- [macOS 启动](../README_zh.md#macos)
- [Linux 启动](../README_zh.md#linux)
- [桌面 Shell 与桌宠](architecture/desktop-shell.md)
- [本地模型与 Ollama](architecture/local-model.md)
- [入门指南与 UI 参考](ui/reference-map.md)
- [Avatar 资产说明](../assets/avatars/README.md)

## 产品架构

- [架构索引](architecture/README.md)
- [Protocol v0.1](architecture/protocol.md)
- [模块目录](architecture/modules.md)
- [Provider profiles](architecture/provider-profiles.md)
- [Avatar 资产与驱动](architecture/avatar.md)
- [角色与 persona](architecture/characters.md)
- [任务中心](architecture/tasks.md)
- [音频 ASR/TTS/VAD](architecture/audio.md)
- [长期记忆](architecture/memory.md)
- [视觉观察](architecture/vision.md)
- [插件 Manifest](architecture/manifest.md)
- [外部工具](architecture/tools.md)
- [安全边界](architecture/security.md)
- [调试与恢复](architecture/debugging.md)

## 开发接口与决策

- [ADR 0001：依赖轻量的首版 Shell](adr/0001-local-first-shell.md)
- [前端 Shell 说明](../frontend/README.md)
- [Echo provider 示例](../plugins/examples/echo-provider/README.md)
- [Echo tool 示例](../plugins/examples/echo-tool/README.md)
- [第三方声明](../THIRD_PARTY_NOTICES.md)

## 外部集成与来源

- [CC Switch 兼容边界](integrations/cc-switch.md)
- [CC Switch 兼容基线数据](integrations/cc-switch-compatibility.json)
- [DSH Agent 集成](integrations/dsh-agent.md)
- [隔离浏览器策略](integrations/browser-runtime.md)
- [Evolution Knowledge Registry](integrations/evolution-registry.md)
- [Evolution Knowledge Registry 数据](integrations/evolution-knowledge-registry.json)
- [UI 参考地图](ui/reference-map.md)
- [来源与许可证台账](ui/license-ledger.md)

## 文档维护

- 手动运行 `python tools/check_docs.py` 检查本地链接、索引覆盖、状态矩阵和
  归档引用。
- 三端命令分别维护在根 README；未实现的启动器必须明确标为预留或实验性。
- 新增产品专题时，同时加入本页、状态矩阵和对应专题文档的“相关文档”段落。
- 功能状态只更新状态矩阵；README 和专题文档引用矩阵，不自行维护第二份状态。
- 外部项目只作行为或信息架构参考。复制代码、图标、模型或动画前，先更新
  来源与许可证台账及第三方声明。
- 非产品过程资料进入归档区，不在产品文档索引中重新出现；归档内容保持原样。
