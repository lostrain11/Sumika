# P5/P6 能力接入与验收索引

更新：2026-10-18。本文件说明能力边界和维护入口；当前状态、缺口、证据仅在 [主线验收表](repair-and-acceptance-plan.md) 维护，避免复制历轮“当前候选”。完整操作方法见 [功能使用清单](feature-usage-and-acceptance.md)。

## 当前实现

|领域|实现资产|边界|
|---|---|---|
|Office|官方DSH技能/LibreOfficeKit；`extensions/office`|原生文件工作流，不等于活动办公软件控制；见`phase-05-office-acceptance.md`|
|OCR/截图文件翻译|`extensions/desktop/ocr`、`screenshot_skill.py`、现有能力服务|Windows/RapidOCR可替换；翻译使用当前工作模型；不自动截图或承诺实时叠层|
|桌面动作|`extensions/desktop/control`、`authorized_action.py`|参数预检、快照/目标绑定、后验unknown不重放；JSON approved字段不是可信授权凭证或沙箱|
|网页咨询|BrowserSkill适配、原生review插件、页面guard/journal|读/发送/逐次审批独立，总开关实时核验，外站生成不可由本地取消保证终止|
|角色资源|`extensions/roles`、既有资源弹窗|导入/绑定/导出、背景/世界书/主题编辑已接；文件绑定不代表全部资源消费者已实现|
|长期记忆|`extensions/memory`规范仓储/索引、角色写入策略|素材独立，provider可替换；纠正/遗忘/提议/关系与导出治理已接；不承诺最佳长期质量|
|行为与自动模式|`extensions/behavior`、会话协调器和既有UI|许可独立、手动优先、确认历史解释；统计不是注意力或喜好事实|
|定时任务|DSH原生调度+原弹窗绑定；本地提醒独立|不维护第二原生清单，不自动迁移旧执行；投递成功与任务完成分开|

## 可复用入口

- `python -m extensions.roles.service --config <JSON> --request <JSON>`：角色上下文及记忆操作；具体schema以模块与测试为准。检索provider为embedded/semantic，语义路径须配置本地embedding缓存，不联网隐式下载。
- `python -m extensions.desktop.service --store <SQLite> --request <JSON>`：capability/operation/arguments请求；通过可信宿主与原生审批调用。
- 运行数据在显式个人数据目录，开发默认可能位于`.sumika-next/`；不能把开发目录写死为安装产品真实目录。已有配置不被测试覆盖。
- `extensions/desktop/requirements.lock`、`extensions/memory/requirements.lock`及Office锁文件保留第三方依赖来源；历史环境快照不自动等于最小发行依赖。

## 验证与回退

使用现有`tools/verify_*`并明确候选及解释器；开发机调用、包内调用、合成模型、真实设备和模型质量分别记载。新配置可禁用；切回检索实现不应丢原事实。记忆备份当前v5，兼容读取v2-v4；旧程序不支持v5，恢复必须先备份且校验scope。未知桌面/外站操作不自动重放。

历轮后端证据、开源来源、失败原因与早期实现边界保存在 [原记录](archive/20261018/phase-05-06-backend-acceptance.md)，不能将其中“未接UI”“只填不提交”等当作当前事实。真实资源消费者、摄像头/设备及质量缺口按当前验收表继续核对，整体仍进行中。
