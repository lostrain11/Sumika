# 场所与视图分组

## 契约

P08 提供独立的 `sumika.places/v1` 契约，位于 `backend/src/sumika_core/places`。它不修改或复用 `sumika.domain/v1` 的线格式；宿主需要在自己的适配层显式投影两者。

`AssistantLocation` 固定 `assistant_id == character_id`，并以 `world_id` 和 `room_id` 标识成员所在的场所。`activity_point_id` 仅描述房间内活动点，绝不参与视图分组。`PlaceState` 由宿主保存，携带每位助手的最新单调 `revision` 和最近事件 ID，用于拒绝过期事件并让重复事件幂等。

`WindowPreference` 包含可选几何位置、显示器和全屏标志。场所核心只在计划中原样传递它，不能读写原生窗口状态。

## 纯分组与计划

`group_locations(locations)` 以 `(world_id, room_id)` 排序分组，成员 ID 排序后输出，因此相同输入始终产生同一组。不同世界中同名的房间不会合并，显示模式和活动点也不会改变成员。

`plan_views(locations, bindings)` 返回 `ViewPlan`。每个目标房间恰有一个主动作：

- `keep`：现有视图已绑定同一房间和同一成员。
- `rebind`：用已存在的窗口承载新的房间成员，保留该窗口的几何、显示器和全屏偏好。
- `create`：没有可承载的现有窗口时新建逻辑视图。
- `hide`：冗余旧视图仅在对应 `keep`、`rebind` 或 `create` 动作成功后执行；失败策略固定为 `keep-visible`。

承载选择稳定且按以下优先级：已显示目标房间的窗口、参与合并且正在交互的窗口、最早创建的参与窗口。同优先级按 `created_order` 和 `view_id` 排序。该模块只生成动作和依赖关系；Tauri 或其他宿主负责按序执行、报告成功，并在失败时跳过 `hide`。

## P08 状态

- 范围：场所、房间、成员、视图绑定、事件防重与纯合拆窗计划。
- 已实现：模拟卧室分离、客厅会合、再次分离、同房活动点、跨公寓同名房间、模式变化、窗口承载和失败保留测试。
- 不在范围：真实多人运行、Tauri 窗口调用、存储接入、合拆窗动画、默认群聊或共享记忆。
- 验证：`python -m unittest backend/tests/test_places.py`，并在完成后执行 `git diff --check`。
