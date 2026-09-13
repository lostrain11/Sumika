# 角色基础扩展（无 UI）

独立实现 P6-1、P6-2、P6-4：工作模型/角色模型配置、来源隔离的角色上下文、角色资源包导入与导出。模块只使用 Python 标准库，不导入 DSH 或 Sumika 核心。

```powershell
python roles.py validate-config role-config.json
python roles.py import-package package.zip --store .sumika-next/roles
python roles.py export-package role-id --store .sumika-next/roles --output role.zip
```

资源包根目录必须有 `role.json`。模型、角色卡、世界书、语音和 2D/3D 场景文件只登记元数据并安全复制，不执行包内脚本。配置中的 `role_context` 永远是独立来源块，不会拼进用户原文、代码、diff 或工具参数。
