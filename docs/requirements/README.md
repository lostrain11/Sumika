# Sumika 需求基线

这里记录 Sumika 的长期产品意图、不可破坏的约束和未来重构的验收标准。
它不是当前完成度的来源：当前完成度仍以 [状态矩阵](../status-matrix.md) 为准，
当前开发恢复以 [执行契约](../current-execution.md) 为准。

## 推荐读取顺序

1. 阅读本页，了解记录格式和冲突处理规则。
2. 阅读 [需求基线](baseline.md)，了解产品边界和历史决策。
3. 阅读 [模型策略契约](model-policy.md)，处理模型、额度和成本相关工作。
4. 阅读 [脱敏原话摘录](original-excerpts.md)，确认用户意图的语气和优先级。
5. 读取 [机器可读需求](requirements.json)，按稳定 ID 生成影响分析。
6. 回到状态矩阵和具体实现/测试文件核验当前事实。

## 记录格式

`requirements.json` 是需求 ID 和验收条件的机器可读来源。每条记录包含：

- `id`：跨重构保持不变的稳定标识；
- `statement` 和 `acceptance`：要实现和要验证的行为；
- `provenance`：`confirmed`、`normalized`、`inferred` 或 `external`；
- `intent_state`：`active`、`deferred`、`superseded` 或 `historical`；
- `source_refs` / `excerpt_refs`：来源和脱敏摘录；
- `implementation_refs` / `test_refs`：当前代码和验证证据；
- `supersedes` / `superseded_by`：被新决定取代时的双向关系；
- `status_ref`：指向状态矩阵，不在这里复制完成度。

`baseline.md` 面向人阅读，`original-excerpts.md` 只保留必要的非敏感原话片段。
无法从现有仓库和可见对话恢复的历史内容必须标明缺失，不得猜写。

## 冲突和更新规则

- 最新明确的用户决定优先于早期决定；早期记录保留为 `superseded`，不覆盖删除。
- 设计推断不能升级为硬需求，除非用户明确确认；推断必须标为 `inferred`。
- 当前代码、测试和实际运行时证据优先于旧摘要；发现冲突时先修正状态或证据链接。
- 改变现有需求时新增关系记录和脱敏摘录，不直接改写历史意图。
- 需求变更和架构重构都必须检查受影响的 ID、数据迁移、凭据边界和恢复路径。
- 不写入 API Key、Token、Cookie、密码、聊天正文、Session ID 或个人绝对路径。

## 重构前检查

未来 Agent 或人工重构者应先回答：

1. 哪些 `active` 需求受到影响？
2. 是否保留了 Runtime、Provider、角色、Avatar、Browser 和 Workspace 的边界？
3. 是否把 `deferred` 或 `superseded` 方案错误地变成了默认行为？
4. 是否有可复现的测试和回滚路径？
5. 是否需要用户批准凭据、第三方插件、登录或付费动作？

完成后运行 `python tools/check_docs.py`，并更新状态矩阵和执行契约中的对应证据。
