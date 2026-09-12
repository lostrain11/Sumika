# 复用与实现边界

本轮检查了实际安装的 `@deepseek-ai/dsh@0.1.5-rc.2` 及其 MIT 许可的原生插件。只调用公开入口，没有复制第三方源码。

| 需要的能力 | 复用来源 | 本轮选择 |
| --- | --- | --- |
| 原生 UI、实例启动与 profile | `dsh` / `dsh-web-app` | 直接启动原生 Web |
| 浏览器认证与同源检查 | `dsh-client-connection` | 复用 launch-token → 签名 cookie 交换，不自建登录系统 |
| 会话创建/取消/历史 | `dsh-api-session-controller` 的公开 Remote descriptor | 薄适配器内封装，不重写会话存储 |
| Agent loop、文件/终端、Plan、Skills、MCP、子 Agent | DSH 自带插件 | 阶段 2 验收后使用，不实现新执行循环 |
| 项目计划和需求原文 | Git + Python 标准库 JSON | 独立可读记录；不建云端任务系统 |
| 发送前后原子记录 | Python 标准库 SQLite | 持久化未知结果和一次性派发，避免内存丢失后重放 |

DSH 会话原生保存不等于需求原文、修订关系、阶段验收台账。当前仅补这部分缺口；模型自动触发记录的接线属于 P4。
此表是本轮实际选型，不冒称已穷尽社区全部插件。后续扩展按批准计划比较高质量社区/开源方案后再选。
