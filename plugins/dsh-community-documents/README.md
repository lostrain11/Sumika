# 社区办公适配器

Sumika 只提供注册过滤器，不拥有第三方办公算法。Word、Excel、PowerPoint 基础读写来自
[kw78/dsh-office-tools](https://github.com/kw78/dsh-office-tools)，固定 1.0.0，MIT；
PDF 文本读取来自 [sunshine-lang/dsh-pdf](https://github.com/sunshine-lang/dsh-pdf)，固定 0.1.0，MIT。
安装包中的各自 LICENSE 保留，不将上游标为 Sumika 官方 Skill。

四个用途开关默认关闭，关闭工具不会注册。`fileAccessGranted` 是独立宿主文件访问授权，
不是费用授权；不启动模型。文件范围仍由 DSH filesystem 与 permission policy 决定，
本适配器不能把本地 filesystem 的 cwd 当作沙箱。不额外直接读写文档。

安装使用官方 DSH profile 包管理；配置在 profile 的普通插件配置中完成。移除只卸载插件，
不删产物。原上游 bundle 禁用，避免绕过独立开关重复注册。其他客户端可直接使用上游，
不依赖 Sumika Core、数据库或 RPC。本地包未发布。

此适配器通过实际 DSH 加载、用途开关、基础读写和卸载测试，已列入默认安装清单，仍默认关闭。
基础功能不等于复杂排版、视觉检查、PDF 编辑、公式重算或模板创建。详情见
[迁移记录](../../docs/refactor/skill-migration.md)。

已有 profile 使用 Sumika 的 `tools/setup-sumika-dsh-bridges.ps1` 更新安装；不在本轮修改日用 profile。
首次启用在 DSH 的普通插件配置中分别设置用途与文件访问许可。工作台的三个内置 Skill 开关
不控制本插件，也不宣称已经同步到 DSH。禁用或卸载后原文档保留。
