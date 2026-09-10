# 项目、对话索引与历史上下文

P04 提供宿主无关的项目索引与纯历史分页核心。模块位于
`backend/src/sumika_core/projects`，不导入 `Storage`、`CoreApplication`、协议层或服务端入口。

## 持久化边界

宿主向 `ProjectService` 注入以下仓库接口：

```python
save_record(namespace, record_id, assistant_id, payload) -> dict
get_record(namespace, record_id, assistant_id) -> dict | None
list_records(namespace, assistant_id) -> list[dict]
delete_record(namespace, record_id, assistant_id) -> bool
```

项目使用 `projects` namespace。持久化 payload 仅有以下字段：

```text
id, name, category, summary, assistant_id, manual_fields,
conversations, directory, archived, updated_at
```

`conversations` 只保存 `{"source": ..., "source_id": ...}`。外部会话消息、任务结果和来源正文
始终由原来源保管，不复制进项目记录。仓库按 `assistant_id` 过滤后，服务仍复核返回记录的
`assistant_id`；错误归属记录不会进入结果。

`directory` 只是可选绑定元数据。核心没有文件系统适配器，也不会自动遍历或读取该目录。

## 来源与查询

可选来源适配器签名：

```python
list_conversations(assistant_id) -> list[dict]
get_conversation(source_id, assistant_id) -> dict | None
```

来源宿主先按助手过滤，服务再检查返回项的 `assistant_id`、`source_id` 和 `source`。项目列表、
`get_project` 和搜索项目只读取项目仓库，不调用来源详情。`get_project_details` 是唯一显式详情
入口，并且只能查询已挂接到该项目的引用。未配置来源或来源记录不可用时返回
`status=unavailable`，不伪造可继续执行状态。

`list_unclassified_conversations` 只消费来源的浅索引，并用允许字段投影，消息正文不会进入结果。
`search` 搜索项目浅字段和未归类会话浅字段，不读取目录或来源详情。

用户更新通过 `update_project(..., manual=True)` 将字段写入 `manual_fields`。
`apply_metadata` 只接收宿主已经得到的免费或确定性建议，跳过手动字段；核心自身不调用模型，
因此用户改过的名称、分类或简介不会被后续建议覆盖。

## 历史分页

```python
paginate_turns(messages, *, before=None, limit=None) -> dict
```

宿主传入完整、已按会话和助手隔离的消息列表；每条消息严格包含
`id/role/content/created_at`。用户消息开启一轮，后续 assistant、tool 和其他补充消息都归入该轮，
直到下一条 user 消息。首屏默认返回最近 3 轮；带 `before` 时默认返回更早的 10 轮。

游标是稳定消息 ID。返回的 `next_before` 是当前页最早一轮的 user 消息 ID；后续新消息追加后，
用该游标加载旧页仍得到相同边界。消息按 ID 去重，未完成轮保留。分页函数不访问仓库，
也不依赖前端当前显示数组。

“清屏”应只由客户端更新显示边界；不得调用项目仓库的 `delete_record`，也不得改变宿主提供给
上下文构建或 `conversation.page` 的真实历史。

## 主 Agent 接线

建议 RPC 到核心方法的映射如下：

| RPC | 接线签名 |
|---|---|
| `project.list` | `service.list_projects(assistant_id, archived=False, query=None)` |
| `project.create` | `service.create_project(assistant_id, project_id=None, name=None, category=None, summary=None, directory=None)` |
| `project.update` | `service.update_project(project_id, assistant_id, name=..., category=..., summary=..., directory=..., manual=True)` |
| `project.get` | 浅取 `service.get_project(project_id, assistant_id)`；仅显式请求详情时调用 `service.get_project_details(...)` |
| `project.archive` | `service.archive_project(project_id, assistant_id, archived=True)` |
| `conversation.attach` | `service.attach_conversation(project_id, assistant_id, source=source, source_id=source_id)` |
| `conversation.page` | 宿主校验助手、来源和可选项目归属，读取来源消息后调用 `paginate_turns(messages, before=before)` |

共享装配层需要实例化一次 `ProjectService(repository, sources)`，其中 repository 适配现有持久层，
sources 适配 Core chat、Quality task、受管 Agent 和网页会话。P04 不修改 `storage.py`、
`server.py` 或 `protocol/models.py`；这些注册与兼容入口留给主 Agent 串行整合。

## 验证范围

`backend/tests/test_projects.py` 覆盖跨助手隔离、跨项目详情拒绝、浅读不触发正文查询、来源引用、
未归类搜索、归档、目录仅绑定和用户字段保护。`backend/tests/test_projects_history.py` 覆盖最近三轮、
十轮追加、稳定游标、并发新消息、工具消息、多段回复、消息去重和未完成轮。
