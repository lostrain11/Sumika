# Evolution Knowledge Registry

`evolution-knowledge-registry.json` 是外部项目和研究榜单的只读索引，和角色
长期记忆分离。每条记录包含 URL、固定 commit 或版本、许可证、能力、用途和
最后检查日期。当前登记 DSH、Codex、BrowserSkill 与记忆系统研究入口。

Registry 只支持发现和隔离评测，不自动安装、升级、执行或启用插件。上游变化
需要人工复核许可证、权限、卸载恢复和兼容夹具；通过审核后才可以创建 Sumika
插件登记。Developer 页的检查只读读取本地登记，不依赖实时网络。

## 相关文档

- [DSH Agent](dsh-agent.md)
- [隔离浏览器](browser-runtime.md)
- [状态矩阵](../status-matrix.md)
