# 记忆检索 RRF 适配（2026-10-27）

## 范围

只改 Sumika 现有 `SemanticMemory` 的排序，不换 SQLite 记忆库、不改 scope、不改 purge guard、不引入 `dsh-engram` 依赖。

## 改动

`extensions/memory/semantic_memory.py`：

- 语义向量分数仍作为 `score`，仍由 `threshold` 决定哪些事实可召回
- 增加 FTS5 词法排名
- 用 Reciprocal Rank Fusion（k=60）融合词法排名和语义排名
- 返回 `retrieval: "hybrid-rrf"`
- FTS 查询异常时回退到纯语义排序，不让检索整体失败
- 仍保留精确标识符 boost（路径、模型名、缩写等）

排序规则：

```text
rrf = 1 / (60 + lexical_rank) + 1 / (60 + semantic_rank)
```

只对通过 `threshold` 的候选排序，因此不会为了词法命中引入低置信事实。

## 验证

- `tests_next/test_semantic_memory.py`：新增“词法命中可排在更高余弦分数之前”的确定性测试
- `tests_next/test_memory_repository.py`：既有版本化/删除/作用域/缓存回归通过
- `tests_next/test_material_purge.py`：删除围栏回归通过

## 本版未做

- 证据充分性判定（`dsh-engram` 的 `engram_assess` 语义）
- SM-2 复习/巩固/衰减
- 向量库替换或跨会话迁移

这些仍属于后续评估项；本版只把已存在的 FTS 与向量两路结果融合，并保留现有安全边界。
