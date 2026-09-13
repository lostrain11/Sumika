# 用户角色卡导入验收

测试资源：`D:\Code\安和昴角色卡项目\交付\安和昴_ST_V2.json`。它是用户自己的导入资源，不是 Sumika 内置角色，不复制到源码、默认配置或 Git。

- 格式识别：Tavern character card V2 (`chara_card_v2`, `2.0`).
- 导入存储：`.sumika-next/user-role-import/store/anhe-subaru/`（本地运行数据，已忽略）。
- 保留内容：角色卡原 JSON、`name`、`description`/`personality`、9 个 character book 条目。
- 安全检查：ZIP 成员路径穿越拒绝、资源包内不执行脚本、重复 ID 拒绝、导入后 SHA-256 清单生成。
- 往返检查：成功导出 `anhe-subaru-roundtrip.zip` 并可再次读取。
- 原始文件 SHA-256：`79d29181c1e97ce84be462b4324196175be24ff0613add00de1d85ee4cbc6ada`。

本次只是资源层导入测试，没有把角色激活到 DSH，也没有将语音、VRM 或其他资料库文件自动复制进 Sumika。以后 UI 可让用户选择是否附加这些资源。
