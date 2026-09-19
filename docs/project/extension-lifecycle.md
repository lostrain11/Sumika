# 非 UI 扩展生命周期与角色接入

## 日用入口

```powershell
python -m sumika_next.cli run --extensions-config D:/path/to/trusted-extensions.json
```

配置必须由启动方显式提供，不扫描项目文件自动启用。未指定时沿用原有日用入口。示例：

```json
{
  "schema_version": 1,
  "enabled": true,
  "schedules": {
    "directory": "D:/path/to/schedules",
    "interval_seconds": 1,
    "execution_bindings": {}
  }
}
```

空执行绑定只能处理提醒。执行绑定每项包含 enabled、action、workspace、fingerprint；fingerprint 由批准时的 Schedule.fingerprint() 得到，不能在每次 tick 前自动按新定义刷新。修改动作、频率、时区或启停状态会使旧指纹失效。配置文件本身是可信启动输入，不是对恶意本机进程的隔离机制。

宿主与 SQLite 在启动线程运行，不另建线程使用连接；进程退出/Ctrl+C/异常时关闭存储，再关闭受管 DSH。发送前的 UNKNOWN 保留，重启不重放。普通 JSON 定义修改通过旁路 SQLite BEGIN IMMEDIATE 串行化，并用唯一临时文件原子替换；save 需要 expected_revision，阻止陈旧快照覆盖。tick 接纳阶段与修改使用同一锁。直接外部手改 JSON 不受此锁保护。

验收：tests_next/test_extension_host.py；tools/verify_extension_host.py 真实 DSH 提交、宿主停止、DSH 进程重启后无重放，见 extension-host-evidence.json。

## 原生角色插件

extensions/roles/dsh.mjs 只负责 DSH 适配；固定 Python bridge.py 调用独立 RoleSession。profile 插件配置明确 enabled、projects（绝对工作区→角色配置文件映射）、python、core、runtimeEntry。不自动修改用户日用 profile。

自动接入仅从直接用户消息检索记忆；插件消息不成为原文。先调用原生 pre-step 下游，拒绝的步骤不追加上下文；已准入步骤以 plugin 来源追加角色和记忆块。原文和下游参数不改写，不设置模型、不执行角色卡指令、不自动存储模型推断。单轮相同原文只注入一次，压缩结束后重新注入；大于预算明确报错，不静默丢弃原文。禁用不启动子进程、不注入，宿主卸载终止子进程。

当前工作模式是 advisory context。分离的角色模型调用、记忆写入策略和更全面的长会话评测仍属于后续工作，不能仅凭插件代码存在宣称 P6 完成。

真实角色插件验收通过：tools/verify_role_plugin_dsh.py（自动注入、原文保持、禁用无注入、0 外部模型调用），见 role-plugin-evidence.json。pnpm 安装时 runtimeEntry 必须经 realpathSync 后用于 createRequire，否则插件可能 MODULE_NOT_FOUND。


## 记忆写入与恢复边界

MemoryWriter 是独立宿主 API：来源与事件 ID 由可信调用方提供，不能作为模型可选的授权字段。用户/角色卡事实带事件 ID 写入；模型推断只暂存在 memory_proposals，不参与检索也不覆盖用户事实。当前尚未接入 DSH 自动写入；既有 RoleSession remember CLI 仍是受调用方控制的直接存储接口，不能声称它已强制执行此策略。

v3 导出在同一 SQLite 读取快照中保存事实、关系及提案；导入校验身份、来源和时间。事件冲突使整个事务回滚，包括先前停用的事实与关系。普通导入及事件重试不激活已遗忘记录；显式 restore 则恢复备份中的 active 状态。reset_to_card 保留旧事件墓碑与不可检索提案历史，避免迟到的旧事件重放。此重置不是物理清除历史。v2/旧列表没有事件 ID，无法追溯恢复其幂等身份。

验证：17 项记忆/角色定向测试通过；完整 tests_next 143 项，142 通过、1 跳过。未运行外部模型。会话模型接入已找到 rc.2 原生 session/modelCatalog 与 session/selectModel，仍需薄适配和真实验收，不等于角色模型调用完成。


## 独立角色模型 preset

使用 `python -B -m extensions.roles.preset --help` 查看安装参数。显式指定 --directory（例如受管 DSH_HOME/.agent-presets/sumika-role）、--provider、--model、--runtime-entry（已安装 DSH/package.json）、--role-config、--workspace、--python，可选 --reasoning-effort / --disabled。生成用户 preset，不覆盖已有目录，不启动模型。安装后通过原生会话创建时选用该 preset；也可在测试 profile 的 agent-presets roots 中显式登记自定义目录。model 必须与角色配置 role_model 一致。生成配置是快照，后续配置编辑需按原生 preset 生命周期重新加载；不代表已为用户日用 profile 启用。

preset 复用原生 persona 与 Agent 循环，仅注册角色上下文与独立模型请求适配，没有文件/终端工具。核心 RoleSession 与记忆数据不依赖 DSH。模型适配使用 agent/request 的 prepend waterfall，等待下游成功后返回显式角色 provider/model，不继承工作模型及其 reasoningEffort；拒绝或禁用时停止。两个 mjs 适配文件纳入 wheel 数据。

已核实 rc.2 的 session/selectModel 会调用 agentDefaultModel.saveSelection，因而不能用它隔离角色模型。普通顺序的 agent/request 又会被原生 installModelSelection 覆盖；prepend:true 使角色路由最终生效。真实夹具验证请求体使用角色模型 deepseek-v4-pro，前后工作模型仍为 deepseek-flash；原文保留、上下文仅角色会话注入、角色工具列表为空，禁用与未知 provider 均无模型请求/无回退。全部请求只发往本地 ModelFixture，模型名称只验证路由，不是云端效果测评。

证据：tools/verify_role_model_dsh.py 与 docs/project/role-model-evidence.json。144 项 Python 测试（143 通过、1 跳过），5 项角色 Node 测试通过。仍未完成自动记忆写入和工作任务结束后自动触发角色附言；P6 保持 partial/in_progress。


## 明确记忆指令的自动写入

现已接通可信宿主入口，但范围限于用户明确要求记忆的原文。原生角色插件增加 `memoryWrites`（默认 false）与启用时必填的 `memoryNamespace`。preset 安装器对应 `--memory-writes --memory-namespace <稳定的宿主标识>`；启用发生在可信 profile 配置，不接受模型工具参数选择来源。namespace 应在同一安装重启时保持稳定，不同宿主/profile 应区别设置。

支持以 `记住：`、`记住:`、`请记住：` 开头的完整用户消息，例如 `记住[饮食禁忌]：我不吃花生`；可选的方括号键完全由用户指定，用来更新同一作用域中的同一事实。正文保留原字面内容。普通聊天、带前缀的引用/代码示例不自动提炼。未带键的事实追加保存，不承诺自然语言语义去重或矛盾识别。

DSH 适配仅传递 pre-step 下游已准入消息中 source.kind=user、含原生 rpcId 和消息 id 的文本；插件、模型、工具消息不作为用户事实来源。独立 capture.py 负责指令解析和事件身份，MemoryWriter 固定 origin=user；事件身份绑定 namespace/session/message，SQLite 保留重试墓碑。原文仍由 DSH 保存，记忆不替代原始记录。普通聊天的模型提案生成/确认尚未接通。

bridge.py 的 host_context 是受信任本地插件调用入口，没有注册为模型工具；RoleSession 既有手动 remember CLI 保留。此边界防止模型文本伪装事件，不是针对拥有本机终端/文件权限进程的安全沙箱。存储失败使当前步骤报错，不伪造保存成功；批量中断后的重试按事件去重。禁用只阻止新写入，保留已有记忆和检索。

真实 DSH 验收通过：明确指令写入、第二会话召回、进程重启后召回、单独禁用写入仍保留上下文、全部禁用不注入；原文未改写，0 外部模型请求。见 role-plugin-evidence.json。146 项 Python 测试（145 通过、1 跳过）、6 项 Node 测试通过。日用用户 profile 未自动启用，P6 不标记完成。


## BrowserSkill默认安装定位

BrowserSkill作为Sumika客户端的默认浏览器后端随安装包提供固定版本，适配器位于独立扩展层；不把BrowserSkill源码复制进Sumika，也不修改其上游文件。客户端安装后可以检查健康状态，但不会自动打开浏览器、自动登录或自动向网站发送内容。

首次使用网页咨询时，用户为每个网站单独登录并授予read/send权限；登录授权和发送授权分开保存。授权数据只保存网站、命名Profile及权限，不保存密码、Cookie或Authorization。用户可单独撤销网站授权。BrowserSkill不可用、扩展未连接、登录过期或需要验证码时，功能失败关闭并要求人工处理，不回退到未授权浏览器或付费API。未来替换BrowserSkill或Harness时，仅替换此适配器。

BrowserSkill站点授权默认保存到Windows LOCALAPPDATA\Sumika\browser-authorizations.json，使用临时文件+os.replace原子更新；支持单站点撤销。项目内显式registry仅用于测试或受控部署，凭据、Cookie和页面内容不写入。
