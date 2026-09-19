# 定时任务服务

ScheduleStore 保存 once/daily/weekly，支持显式 IANA 时区（默认 UTC）；once 必须包含偏移量。daily `09:00`，weekly `0 09:00`（周一=0）。夏令时不存在的时间跳过，重复时刻选择第一次。离线恢复每轮只处理最近一期，不补跑所有历史；旧格式记录保持 UTC。

ScheduleService.tick() 由宿主定时调用；run(stop_event) 是可停止的前台循环，创建和运行应在同一线程。应用未运行时不执行，没有安装系统开机任务或后台服务。定时执行不等于准点完成模型任务。

提醒写入本地 SQLite 收件箱，可 acknowledge；不触发模型。执行由显式桥接的受管 DSH 接收。DshScheduleBridge 的绑定包含 enabled、workspace、action，配置来自可信宿主；更改动作需重新绑定。DSH 原生模型/工具审批不变，只有 session/prompt 的 accepted 才标为 submitted，submitted 不代表任务完成。

发送前记录 UNKNOWN；断线/崩溃不重放。reconcile 需要核对证据；确认未执行也不自动补跑，需显式创建新任务。cancel 先停用未来调度，再请求原生 session/cancel，取消确认应读原生事件。删除定义不删除历史，也不取消已经运行的会话。运行器持久化异常类型，不保存可能含凭据的异常正文。

命令行（提醒与管理，不自动创建付费 Harness）：

```powershell
python -m extensions.desktop.schedule_cli --directory .sumika-next/schedules upsert --input schedule.json
python -m extensions.desktop.schedule_cli --directory .sumika-next/schedules watch
python -m extensions.desktop.schedule_cli --directory .sumika-next/schedules reminders
python -m extensions.desktop.schedule_cli --directory .sumika-next/schedules history
```

watch 用 Ctrl+C 停止。CLI 未配置 bridge，execute 定义会保留但不会提交；客户端接入时通过 ScheduleService(..., bridge=DshScheduleBridge(owned_adapter, bindings))。不把普通 HTTP 地址或用户可伪造 receipt 当受管实例。

真实验收脚本 tools/verify_schedule_dsh.py；合成提示调用本地模型夹具，验证真实 DSH 提交、提醒、取消和重启去重。自动化 tests_next/test_schedule_service.py、test_capability_schedule.py、test_scheduler.py。

限制：单个 ScheduleStore 的定义编辑要求宿主串行化；JSON 编辑尚未提供多进程乐观锁。历史 claim 使用 SQLite 唯一键跨连接去重。没有绕过原生确认实现无人值守高权限操作。
