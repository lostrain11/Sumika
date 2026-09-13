# Context boundary

`build()` 是 Harness 中立的上下文组装函数。用户原文永远单独作为 `source=user`，角色和长期记忆作为独立来源块；调用方不得把这些块拼接进文件内容、diff、工具参数或授权字段。返回的 `original_user_content` 用于验收和审计。深拷贝避免下游修改角色/记忆对象。
