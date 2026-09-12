# 独立项目连续性扩展

`continuity.py` 只依赖 Python 标准库，不导入 Sumika 核心或任何 Harness。`dsh.mjs` 是 DSH 专属适配中间层，通过原生插件接口接入事件、工具和上下文。更换 Harness 时替换适配器，继续使用记录库与数据。`skill/SKILL.md` 负责模型操作约定。

## 安装与开关

在 Sumika 仓库根执行，项目与 profile 可独立指定：

```powershell
python -X utf8 -B extensions/continuity/install.py --root D:/path/to/project --home D:/path/to/dsh-home --runtime runtime/dsh
```

安装器在 profile 的 `cordis.patch.yml` 加入独立插件，保留已有配置并保存修改前副本；只自动编辑 JSON 格式的 patch（DSH 也支持此格式）。已有 YAML 配置请手动合并下面条目，安装器不会将其重写。项目 `.agents/skills/sumika-continuity/SKILL.md` 从模板安装；已有不同内容时停止覆盖。

```json
{"insert":[{"id":"sumika-continuity","name":"D:/Sumika/extensions/continuity/dsh.mjs","config":{
  "enabled":true,
  "projects":["D:/path/to/project"],
  "python":"D:/Tools/python/Python314/python.exe",
  "core":"D:/Sumika/extensions/continuity/continuity.py",
  "runtimeEntry":"<已安装 DSH package.json 的真实绝对路径>"
}}]}
```

手动配置前用 `python extensions/continuity/continuity.py --root <项目> init` 初始化记录库，并复制 Skill 模板。插件仅捕获明确登记且与会话 cwd 匹配的项目；不会向其他项目建目录或写记录。

`config.enabled=false` 关闭捕获、工具注册和上下文注入，保留数据。也可使用 DSH 原生插件 `disabled` 开关。当前按重启 profile 生效的方式验收；后续设置 UI 直接接入这一配置，不在 P4 增加自建设置页。Skill 文件可以保留；关闭时其中的工具不可用。插件生命周期由 DSH 管理，没有独立守护进程。

## 记录边界

- 捕获原生 `agent/inbox/spliced` 中直接用户来源的提交，以及 `user/message`、`source.kind=user`、`surfaceOp=append` 的已接纳消息；按稳定消息 ID 去重。因此后来被拒绝的提示仍保留来源，但不被当作已授权执行。文本块、空白和来源字段原样保留；插件通知、角色附言、压缩摘要、消息替换不升级成用户原文。附件块保存其事件表示，不承诺备份外部附件文件。
- 所有被捕获的用户消息是来源材料，不意味着每句话都是有效需求，更不是工具批准。目标、计划、决策和成果通过工具另记为 `model_report`，与原文保持来源链接。
- `continuity_record` 不开放 host observation 写入，不能产生用户原文或审批。计划记录带前一计划、变化原因及受影响任务；成果带已实现、验证声明、未完成、限制和下一步。失败或未运行不会被自动改成成功。
- 工具、模型、回合和压缩事件是观察记录。工具结束和回合结束不等于任务完成。助手仅保存可见正文，不保存 reasoning、请求头凭据或原始工具输入输出。没有修改代码、diff 或成果正文的钩子。
- 新模型收到单独来源为 plugin 的交接消息；原始提示与下游拒绝保持不变。每轮首次进入及压缩后的下一步注入，避免每个工具步骤重复注入；过大时只注入索引，使用查询分页读取完整记录。
- 语义归纳由模型按 Skill 记录，宿主不猜测“完成了什么”。未产生报告的中断会话仍有原文和事件，接手者必须检查实际文件；不会为补报告强制另一次付费模型调用。

## 数据与恢复

项目 `.sumika-continuity/` 保存项目 UUID、SQLite 记录和可重建的 `handoff.json`。原文可能包含用户发出的凭据，目录自带 `.gitignore`，默认不上传。Git HEAD 随记录保存，未提交文件状态仍需检查实际 diff。UTC 是捕获时间，不冒充用户消息原始时间。

SQLite 事务保存整批事件，稳定的 Harness/会话/事件序号或消息 ID 防止恢复重复；同 ID 内容冲突直接报错。工具报告绑定实际调用 ID、轮次、步骤和会话，跨轮次复用调用 ID 不冲突，同次重试不重复写。会话恢复时从原生日志补记缺失事件，不重复执行业务工具。写入失败阻止下一次模型步骤的连续性接入，不把下游权限拒绝改为允许。原生 `session/flush` 等待扩展写入；强制终止时仍可能依赖下次恢复原会话补记原生日志。

每个项目保持独立数据库；跨会话继续时报告复用同一 task ID。原始事件默认按 session 归组，通过报告的 sources 关联到业务任务。所有任务和历史均可查询，不将最近摘要视为全部记录。

脱离 DSH 查询或生成交接：

```powershell
python -X utf8 -B extensions/continuity/continuity.py --root D:/path/to/project recover
```

独立协议为 stdin JSON / stdout JSON，详见 `handle()`；action 支持 `ingest`（可信宿主专用）、`report`、`query`、`recover`。模型只通过原生工具调用 report/query，不能自行指定项目根、宿主来源或会话身份。插件仍处于可信宿主边界，不是抵御同用户任意代码的沙箱。

私有备份须包含 `.sumika-continuity/`；停止实例后复制该目录及项目文件，或者运行时用 SQLite backup API 做一致快照。恢复保持项目 UUID，重新绑定新绝对路径。卸载时移除插件配置并重启；删除安装的 Skill 可选，原始记录保持不动。生成视图损坏可用 recover 重建，SQLite 损坏应从备份恢复。禁用期间的日志可能在重新启用并恢复该会话后补记；开关不代表擦除历史。

## 复用选型与验证

已核对固定 DSH rc.2 发布包内的 `dsh-hooks-claude-code`、`dsh-hooks-codex` 文档及实现。现成桥缺少 Pre/PostCompact，并将提示块来源压平；SessionStart 脱离首请求等待，Stop 不提供完整成果。它们无法同时满足原文来源隔离、可靠恢复注入和压缩留痕，故复用更底层的原生插件事件和 tools 接口，增加这层薄适配。没有修改上游 node_modules，也未引入另一套 Agent 循环。此选择基于已安装官方组件，不声称穷尽所有社区项目。

```powershell
python -X utf8 -B -m unittest tests_next.test_continuity_extension -q
node --test extensions/continuity/dsh.test.mjs
.sumika-next/verify-env/Scripts/python.exe -X utf8 -B tools/verify_phase4.py
```

协议更新时先在隔离 profile 跑验收，再改适配器及安装器的已验证版本限制。独立存储模块的测试不需要 DSH；真实验收使用 DSH 工具和两个本地模型端点，验证接手请求实际包含原文来源、计划、失败/未运行结果和下一步。
