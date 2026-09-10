---
name: tool-registry
description: 任务需要重复使用工具或下载依赖时，查找已登记工具并记录经验证的复用方法。
version: 1.0.0
source: sumika-official
---

# 工具复用目录

实际复用或准备下载前，调用宿主提供的本Skill `check_paths` 辅助工具；其他宿主可运行 `python scripts/check_paths.py --config config/paths.json --operation reuse`（缓存用 `cache`），可选 `--data-root` 为宿主提供的数据目录。脚本只检查，不扫描、不执行、不修改。

结果为 `ready` 才在返回范围内查找；不跟随链接越界。失败则提示原因、配置文件位置和脚本提供的建议，不猜路径；继续其他独立工作。用户明确要求配置后才使用已授权文件工具修改本地 `config/paths.json`、创建目录，之后重新检查。未提供数据目录不妨碍有效配置使用。

复用已有项目工具记录，只记录工具版本、来源、前提和验证方法，不记录凭据。推荐不等于下载安装或执行授权。只保留有后续价值的工具；禁用本Skill不删除工具或缓存。

启用仅使本功能可被选择和加载，不扩大宿主工具、文件、网络或消费授权。按当前请求需要使用；不依赖其他内置Skill同时启用。
