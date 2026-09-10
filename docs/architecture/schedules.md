# 日程

`sumika_core.schedules.ScheduleService` 是用户日程的持久化核心。它不创建线程、定时器、OS 计划任务或第二套执行器；宿主使用既有后台循环显式调用 `tick`，所有实际工作经注入的统一 `dispatch` 入口发送。

## 宿主接线

主 Agent 持有服务实例，并为每个已加载助手调用后台 tick：

```python
service = ScheduleService(
    repository=repository,
    dispatch=dispatch,
    clock=clock,
    maintenance_projection_reader=read_maintenance_projection,
)

service.create(assistant_id, draft)
service.list(assistant_id)
service.get(assistant_id, schedule_id)
service.update(assistant_id, schedule_id, changes)
service.set_paused(assistant_id, schedule_id, paused)
service.run_now(assistant_id, schedule_id)
service.tick(assistant_id)
service.history(assistant_id, schedule_id)
service.complete_run(assistant_id, execution_id, status, spent=None)
service.maintenance_projection()
service.close()
```

`repository` 只需要 `save_record(namespace, id, assistant_id, payload)`、`get_record`、`list_records` 和 `delete_record`；保存、读取和列表中的 payload 均为普通字典，删除返回布尔值。`dispatch(payload)` 返回至少可选的 `request_id` 与 `status`，不接受模型、网络或执行器注册责任。`clock()` 必须返回带时区的 `datetime`。应用退出时先停止宿主 tick，再调用 `close()`。

## 记录与时间

日程保存在 `schedules` 命名空间，执行历史保存在 `schedule-runs`。一次、每日和每周规则采用 IANA 时区，默认 `Asia/Shanghai`。Windows 缺少 `tzdata` 时仅将默认上海时区回退为固定 UTC+8；任何其他缺失时区明确报错，绝不静默改时区。

计划时点的执行 ID 由日程 ID 和 UTC 时点确定。派发前先持久化 `dispatching`，因此崩溃、异常或返回未知都会留下 `unknown`，重启后不会重发；宿主得到最终结果后必须用 `complete_run` 落盘。`running` 或 `unknown` 的旧执行会阻止同一日程继续派发。

周期规则只在 `max_lateness`（默认五分钟）内派发；超过窗口写入 `periodic-missed` 历史并跳至下一个未来时点。一次性规则在任何错过后写入 `once-missed` 并变为 `needs_manual_run`，只能由 `run_now` 补跑。`tick` 分别返回 `dispatched`、`skipped` 和被旧 `running`/`unknown` 执行保护的 `blocked` 条目。

## 授权和维护投影

创建和修改均要求 `authorization.scope_confirmed=True`，表示用户已经确认日程目标、重复规则和执行范围。默认 `paid=False`，不会授予付费能力。付费日程必须明确 `paid=True` 及至少一个 `per_run_limit` 或 `total_limit`；金额以十进制字符串保存，实际完成时由 `complete_run(..., spent=...)` 累计并检查上限。编辑不会清除已记账的累计消费，也不能把总额上限降到该消费以下。

`maintenance_projection()` 只返回注入的只读既有维护条目。它不会注册、复制或触发价格刷新、额度检查、福利发现或签到任务。
