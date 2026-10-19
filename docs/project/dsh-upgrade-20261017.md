# DSH 内核版本、升级与回退

更新：2026-10-18。项目开发运行时和当前内部候选r15均精确固定 `@deepseek-ai/dsh@0.2.1-rc.2`。候选未部署或替换已安装客户端；不能从开发运行时升级推断所有日用实例已经更新。

## 版本依据

最近官方npm核验：`next=0.2.1-rc.2`，`latest=0.2.0-rc.2`。选取较新的已核验RC，不因latest标签回退旧版；alpha.5属于更早实验线，不作为当前默认。证据：`.sumika-next/acceptance-20261018/dsh-latest-check.json`及`dsh-latest-recheck.json`。这是核验时点结论，升级前仍须查询官方发布时间。

## 当前复用范围

- 保留DSH原生Web、Agent、Plan、工具、Skills、MCP、审批、提问及调度，不修改上游源码、安装包或node_modules。
- Office复用官方技能、依赖发现与LibreOfficeKit；新建执行任务复用原生调度与唯一管理页。
- 网页咨询、角色/记忆、连续性通过独立扩展与profile公开注册接入，保留用户既有显式禁用和作用域。
- 新模型及Search/Fetch相关组件随内核提供；Sumika本地主力LFM2.5-24B-A2B不因升级自动切换。新增业务入口、真实模型质量与外站调用不由内核升级自动证明。

## 验收与重现

升级时已完成原生探针、P2门槛、插件生命周期、历史迁移与迁移失败回退；详细报告和失败经验见 [原升级记录](archive/20261018/dsh-upgrade-20261017.md)。工具继续复用：

```powershell
python -X utf8 -B tools/probe_dsh_next.py --runtime runtime/dsh
python -X utf8 -B tools/verify_phase2.py --runtime runtime/dsh --repair-fixture-acl
python -X utf8 -B tools/verify_dsh_plugin_lifecycle.py
python -X utf8 -B tools/verify_runtime_upgrade_rollback.py --migrate-fixture
python -X utf8 -B tools/verify_runtime_upgrade_rollback.py --migration-failure-fixture
```

这些是复现入口，不代表文档整理时重新执行。最新r15 EXE、UI矩阵和原生审批等结果只在 [当前验收表](repair-and-acceptance-plan.md) 维护，避免复制后产生多个“当前版本”。

## 回退

停止目标受管实例，使用升级前匹配的旧runtime与旧profile快照成对恢复。不得让旧内核打开已迁移的新profile，也不得仅降级包版本而复用新schema。保留旧程序、数据及迁移失败保护；原升级过程和路径见归档。

## 赠金与账号

未验证真实账号的首次登录赠金资格。安装或升级DSH不自动代表领取成功；须在官方活动/登录入口核对账号资格、额度与有效期。没有自动登录、领取或付费操作。
