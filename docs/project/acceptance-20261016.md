# Sumika 独立验收：2026-10-16

**当前状态：源码自动化修复验收通过；真实硬件、模型场景质量和最终候选仍待验。** 详见文末“修复后复验补充”。下列最初审计保留修前事实与缺陷依据，不代表修后仍未接线。

本次验收针对 ZCode / GLM5.3flash 执行的 P00～P17 交付。只读检查源码、运行测试和隔离复现，不修改产品代码、不启动真实屏幕/键鼠采集、不切换日用安装、不推送或发布。

**结论：不通过。** 全量单元测试表面通过，但交付仍有阻塞性接线缺陷、后台线程异常和 Windows 采集未闭环。执行回执中的“全部 code-complete”不能作为验收事实；以下结论以当前工作区代码和本轮证据为准。

## 验证基线

- 工作区 HEAD：`d530c4b`；验收开始时无用户未提交改动。
- 全量命令：`python -X utf8 -B -m unittest discover -s tests_next`。
- 结果：**1150 tests，21 skipped，OK，129.371s**，日志保存在 `.sumika-next/acceptance-20261016/unit-tests.log`。
- 同一日志出现后台线程未捕获异常：`extensions/companion/session_coordinator.py:583` 捕获未导入的 `RequestCancelled`，抛出 `NameError`。因此“测试 OK”不能证明主动生成取消路径可用。
- P17 候选 `E:/SumikaBuild/p17-candidate` 来源为 `fa40ce8`，与当前 HEAD 不同；候选矩阵证据不能直接代表当前源码。

## 阻塞问题

### A-01（P0）主动回复取消路径会在线程中崩溃

`session_coordinator.py` 只导入 `CancellationToken`，却在 `_generate_proactive()` 中 `except RequestCancelled`。取消令牌触发该分支时，异常名解析失败，后台线程退出并留下错误状态。全量测试日志已捕获真实堆栈；建议直接补齐同一取消模块的显式导入，并增加“后台主动生成被用户提问/停止打断后线程无异常、无迟到输出”的并发回归。

### A-02（P0）日常行为采集与序列/询问闭环没有接入产品主流程

源码中 `InputFeatureProcess`、`EpisodeTracker`、`select_ask_candidate`、`PromptQuota` 只有组件和管理 API，除测试与工具外没有生产实例化或调用。`Bridge` 初始化了行为库和 `RoutingEngine`，协调器行为 sink 只把阅读页 tracker 的 `flip_burst/long_dwell/revisit` 写入事件；Raw Input frame 没有启动，frame 也没有流入序列检测器，候选模式没有转成自动询问。`/api/manage/behavior` 的 `prompt_show` 是外部直接调用接口，不是系统自动触发。

这意味着“记录用户做了什么、推断习惯、第一次异常操作主动询问、下次预期”目前是后端零件和手工 API，不是用户可用功能。建议由宿主在持久授权有效时创建并监督唯一 `InputFeatureProcess`，把 frame 解码为 host session 的语义动作，接入 `EpisodeTracker → library.record_episode → candidate/confirmation → PromptQuota → 现有陪学消息流`；暂停、权限撤销、会话切换和队列缺口必须形成明确的 gap/epoch 边界，并为每段接线增加真实主流程测试。

### A-03（P0）自动陪伴模式没有从前台/识屏观察驱动

`RoutingEngine.on_foreground()` 只在 `scene_classify` 管理动作中被调用；该动作要求调用方直接提交 `foreground_identity` 和 `material`。全仓生产代码没有 1Hz 前台观察、屏幕材料提取、`on_foreground` 调用或将 `effective_profile_id` 应用到陪学协调器的接线。`behavior_startup_resume()` 只启动现有 perception worker，也没有把观察结果送路由器。因此用户在游戏、教学网站或 PDF 中不会自动进入对应 profile；P15 的 7/7 模型脚本只证明独立分类样本，不证明产品自动路由。

建议把持久授权后的前台观察作为唯一宿主入口：读取当前窗口身份和有界材料摘要，过滤 Sumika 自身/排除应用，按 1Hz 送入路由器；匹配结果必须以 epoch 围栏更新当前协调器的 profile 设置，手动选择立即锁定并阻止分类，暂停/撤销/窗口不可用立即清空上下文。模型输入、超时和未知结果均应可观测且默认 unknown。

### A-04（P1）自动路由稳定窗口和迟到结果保护失效

隔离复现使用临时 profile store 和假分类器：第一次 `on_foreground()` 在稳定 2 秒前立即调用分类器并返回 `matched`，`foreground_epoch` 仍为 0；计划要求新身份稳定 2 秒后才绑定。另一个复现让分类器阻塞，随后调用 `set_suspended(True)`，暂停视图先返回 `suspended`，释放分类器后旧结果仍覆盖最终视图为 `matched`。实现没有在分类返回后复查 target、routing epoch、foreground epoch、suspended 和配置快照。

建议把“身份绑定”和“分类提交”拆成两个阶段；所有控制变更递增 epoch，分类请求携带完整快照，回调只接受仍匹配的快照。对 `scores` 做严格全候选校验，不能以缺失候选默认 0 形成假领先；配置变化、手动选择和权限变化必须取消或无条件丢弃在途结果。

### A-05（P1）profile 设置没有应用到协调器，配置变更也没有通知路由器

`companion_profiles_manage()` 的 create/update/delete/select 只修改 `CompanionProfileStore`。全仓只有旧设置接口调用 `coordinator.set_proactive()`；profile 的 `response_instructions`、`settings.proactive_enabled`、`proactive_interval_seconds`、`context_sources` 没有应用到当前协调器。profile 修改也没有调用 `RoutingEngine.on_config_changed()` 或取消旧生成。UI 能编辑字段，但编辑后的模式不会改变正在运行的陪学行为。

建议由一个宿主 runtime adapter 负责 profile 解析、协调器应用和路由 epoch 更新；每次 profile 写操作先保存再原子重建运行快照，旧 profile 的在途生成必须按 epoch 丢弃。

### A-06（P1）Raw Input Windows 交付仍未验收，且父进程队列字节上限实现不成立

P11 回执已承认真实键鼠 soak 为 **0 frames**：worker 能启动停止，但 `WM_INPUT` 没有投递；这不能称真实采集闭环完成。当前 `InputFeatureProcess` 也没有生产实例化。实现声明 1 MiB 队列上限，但 `_enqueue()` 只使用 `queue.Queue(maxsize=120)`，从不按 `QUEUE_BYTES` 拒绝/阻塞；满队列丢旧帧时按“新帧 encoded 大小”扣减，未按被丢帧大小扣减。异常 frame 直到提交时才失败，且提交 scope 固定为 `session: None`，无法满足 host session 级序列边界。

建议先修正并单独验收 Windows worker：明确 Raw Input 注册结构和消息泵、正常输入产生 frame、密码焦点暂停、前台 epoch 变化和停止清理；父进程按实际字节维护硬上限，缺口标记为不完整并结束 episode，不静默丢帧。

## 数据治理缺口

### A-07（P1）删除接口没有覆盖所有行为数据表

`BehaviorLibrary.delete_records()` 删除 `events`、关联 feedback，并将 prompts 置为 expired、停用 patterns；没有删除或清理 `episodes`、`frames`、`progress`。用户按事件/时间执行数据删除后，Raw Input、序列 episode 和进度仍可保留，和长期行为数据治理承诺不一致。建议明确删除选择覆盖各数据集，事务内同步清理关联记录、确认影响行数并递增 epoch；保留审计元数据时需在界面和文档明示。

## 已通过或部分通过的范围

- Profile store 的 schema、revision 冲突、手动选择语义和现有 profile UI 基础流程有单测/脚本证据。
- 行为库、提示状态机、进度 upsert、阅读 tracker、权限文件和目录迁移组件有相应单测。
- 全量回归没有 Python 测试失败；但后台线程异常、未接线和设备层 0 frame 使整体仍不通过。

## 记录冲突与后续验收顺序

`docs/project/handoff.json` 的 `execution_handoff` 声称 P00～P17 code-complete，顶层 `next_action`/`planning_delivery` 又保留“P01/P06 未实施”；`companion-implementation.md` 也同时写“全部完成”和多个“接线留待后续”。本报告将状态统一解释为：组件部分完成，产品闭环未验收。

修复后按以下顺序重新验收：

1. 先修 A-01，并用并发取消回归证明线程无异常。
2. 完成 A-02 的真实主流程接线，验证授权、暂停、撤销、会话边界、候选确认和限额。
3. 完成 A-03～A-05，使用假前台/假屏幕材料覆盖 2 秒稳定、手动优先、暂停、迟到结果、profile 应用和未知回退。
4. 完成 A-06 后再做用户在场的 Windows 键鼠 soak；未告知用户不得启动该测试。
5. 补 A-07 删除闭环，再运行全量回归、UI 脚本和当前 HEAD 的候选构建验收。旧候选 `fa40ce8` 的证据不能替代当前 HEAD 验收。

## 2026-10-16 修复后复验补充

本轮已按用户授权直接修复并重写必要接线。行为库现在覆盖事件、输入帧、episode、提示、反馈、模式来源、进度和管理状态；删除、纠正、禁用记录、外部目录迁移和权限 revision 均有边界处理。`BehaviorRuntime` 已接入前台跟随、陪学观察、输入帧、候选序列、确认前询问、模式来源和可靠 PDF/B站进度。自动路由会等待前台稳定、验证候选持续时间、检查完整 profile 分数并丢弃迟到结果；手动模式优先。

本轮证据：改动相关定向套件 **209 项通过、1 项跳过**；runtime/auxiliary 套件 **34 项通过、1 项可选 Pillow 跳过**，使用 desktop runtime 另行验证真实缩略图测试通过；模式管理 UI **16 项通过**；粘贴上下文 UI **3 项通过**；当前源码四屏矩阵 **128/128 通过、横向溢出 0、页面错误 0**。验证截图保存在 `.sumika-next/acceptance-20261016/profiles-ui-final-complete/` 和 `paste-ui-complete/`。

新增回归覆盖：权限撤销时未提交帧不落库；重复帧不重复累计；序列缺口结束 episode 且输入失败不自动重启；三次跨两 session 的真实 episode 才形成模式来源；用户确认后模式激活；可靠文件身份才写 PDF 进度；未知文件不跨日猜测；相同视频字幕变化不重复分类；分类器一次接收全部启用 profile；profile 来源过滤不泄漏给角色模型；迁移失败重建源 runtime；scope 改变不会让旧 runtime 的帧进入新作用域。

完整 `tests_next` 最终复跑为 **1243 项、23 skipped、0 失败、0 错误**（116.057 秒）。此前一次角色资源导入清理的 Windows 临时目录 rename WinError 5 单独重跑通过，属于瞬时文件占用。全量日志还暴露旧测试夹具在关闭 socket 前未调用 `shutdown` 导致的 WinError 10038；产品 `OwnedServer.serve_forever` 已对该 Windows 关闭竞态做有界处理，P04 专项复验通过。尚未在真实键鼠/COM/屏幕设备上采集或做性能 soak，也未切换日用安装、发布或推送。


最终小改的验证边界：上述1243项全量复跑在HTTP关闭、损坏权限和容量提示的最后收尾前完成；收尾后定向套件运行 **43项、1项可选Pillow跳过、OK**（`availability-final.log`），auxiliary图像协议 **11项、OK**；模式管理UI最终16项也已重跑通过。不将此前全量结果描述为覆盖所有最后改动。

隔离源码预览：`http://127.0.0.1:57211/`，2026-10-16只读HTTP检查为200。使用独立`source-preview-data`目录、未启用采集，仅在当前预览进程存活时有效；日用安装未更新。

收尾检查：`python -B -m sumika_next.cli check`通过，38个改动Python文件语法检查通过，`git -c core.safecrlf=false diff --check`通过；交接导出使用`python -B -m sumika_next.cli handoff`。
