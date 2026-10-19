# 现成资产台账

目的：避免重复出现「用户已经给了成品资产，模型却另写一套」的错误。做任何任务前先查这里，再查工作区；有新资产就登记。

## 规则

本轮R-071导入修复：直接复用`extensions/roles/roles.py`的角色清单、校验和、ZIP与备份格式，改造`attach_asset`及发布步骤；复用`ui/app/management.js`已批准资源弹窗的同一路径输入。2D/语音/场景的多文件目录封装为依赖路径不变的ZIP，单文件VRM仍直接绑定。原型`ui/prototype-d/index.html`约944行已有角色资源能力卡；无新增控件/导航，仅现有字段说明补充目录支持。`D:/Code/ui-refs/Open-LLM-VTuber-Web`现成Live2D参考已定位，但本轮不引入其运行时：R-071原文要求导入，不将Live2D动画/任意语音模型执行/虚拟房间混入导入修复；库许可和模型兼容须在运行支持任务单独核验。目录导入不执行其中代码。

1. 动手前先列出相关现成资产与路径（查工作区，不凭印象）。
2. 判定：**直接使用 / 改造后使用 / 不适用**，并写下理由。
3. 选择「不适用 / 另写」时，必须在开始实现前告知用户，不能先写完再等用户发现。
4. UI 类任务的定义完成条件包含**与设计稿逐屏对照**，不是「页面能渲染」。

## 已登记资产

| 资产 | 路径 | 类别 | 判定 | 说明 |
| --- | --- | --- | --- | --- |
| D 方向 UI 设计稿（晴日部室） | `D:\Code\Sumika-UI-Designs\direction-d-hiyori\index.html` | 设计稿 | **直接使用** | 106 KB 自包含页面，含完整 CSS 与交互；已作为 `ui/app/index.html` 外壳，仅追加 `bind.js` 绑定真实数据 |
| D 方向原型快照 | `ui/prototype-d/` | 设计稿副本 | 直接使用 | 仓库内快照，含素材图与 `integration.js` 契约 |
| VRM 渲染器 | `ui/vendor/sumika-vrm-viewer.js` | 第三方打包库 | 改造后使用 | three.js + @pixiv/three-vrm，MIT，已记录哈希与来源 |
| 示例 VRM 模型 | `extensions/roles/defaults/sampleA/AvatarSample_A.vrm` | 素材 | 直接使用 | VRoid 示例，非 CC0，许可边界见 `ui/vendor/README.md` |
| 用户角色卡（安和昴） | `D:\Code\安和昴角色卡项目\交付\安和昴_ST_V2.json` | 用户资产 | 改造后使用 | 用户导入资源，不随客户端分发；v1.3 增加了语言策略与中文译名 |
| DSH 本机运行时 | `runtime/dsh/` | 上游依赖 | 直接使用 | 锁定当前最高已发布 RC 0.2.1-rc.2；禁止修改其源码与 node_modules |
| DSH 客户端 UI 插件（主题/审批/会话等） | `runtime/dsh/node_modules/.pnpm/@deepseek-ai+dsh-client-ui-*` | 上游插件 | 直接使用 | 原生Web能力保留；独立皮肤/品牌/工作台插件通过公开插槽接入，见 `workbench-skin-plan.md` |
| 办公能力隔离环境 | `.sumika-next/office-env/` | 依赖环境 | 直接使用 | 含 docx/openpyxl/pptx/rapidocr/pypdfium2 |
| 语音隔离环境与模型 | `.sumika-next/desktop-env/`、`.sumika-next/voice-models/` | 依赖环境 | 直接使用 | vosk + sounddevice + 中文模型 |
| 记忆嵌入环境与权重 | `.sumika-next/memory-env/`、`.sumika-next/embedding-models/` | 依赖环境 | 直接使用 | fastembed 权重本地离线使用 |
| BrowserSkill 固定版本 | `runtime/browserskill/bsk.exe` | 上游工具 | 直接使用 | 0.1.11，随客户端提供 |

## 非 Sumika 依赖的随包策略（2026-10-09）

判断标准不是“是不是 Sumika 自己写的”，而是它是否属于客户端启动或核心学习链路的稳定前置条件：

| 依赖类型 | 默认处理 | 原因与边界 |
| --- | --- | --- |
| 核心桥接工具、协议客户端、固定版本的轻量运行库 | **随包预装** | 首次启动即可用，避免用户自行安装造成版本漂移；必须固定版本、记录哈希并核对许可证 |
| BrowserSkill | **随包预装** | Sumika 浏览器适配器直接调用 `bsk.exe`；当前固定 `0.1.11`，随包携带许可证/NOTICE。预装只保证工具存在，不替代扩展连接、站点授权和普通浏览器采集验收 |
| DSH 插件 | **不全部预装** | 由 DSH 原生插件管理器按版本范围、依赖和运行模式安装/启停；避免把不兼容或需要外部账号的插件伪装成可用 |
| OCR/ASR/视觉模型、桌面音频和 Office 等大体积能力 | **分层随包或按需安装** | 首版体验所需且许可清晰的运行时可进入发行包；模型权重、设备驱动、外部程序按需下载或复用本机，并在 UI 中显示缺失条件 |
| 外部账号、API 密钥、网页 AI 连接 | **不随包写入** | 只保存用户自己的授权状态；网页 AI 可作为可选异步 provider，必须有用户明确授权、来源和失败回退 |

发行验收要分别记录“文件已随包”“依赖可启动”“真实能力已验证”三种状态，不能用第一项替代后两项。

## 本次事故记录（2026-09-15）

用户提供了完整的 D 方向设计稿，我却按自己的理解另写了一套精简外壳（`ui/app/app.js` + `app.css`），直到用户看截图发现与设计不符。教训不是「参考得不够」，而是**默认选择了更省事的自研路径，且没有事先说明**。后果：白做一套样式、延误进度、用户要亲自发现问题。

已采取的纠正：设计稿直接作为外壳；自研样式已删除；规则写入 `AGENTS.md` 与本台账。


## 2026-10-17 官方Office复用补充

直接使用`@deepseek-ai/dsh-skill-office`、`dsh-tool-workspace-dependencies`和`libreoffice-kit`及Windows平台引擎；保留完整程序/许可。改造`ui/workbench.py`公开profile注册和`extensions/office/native.py`独立接缝；沿用`requirements.lock`补齐17项锁定依赖。复用结构化Office夹具验收；不另建编辑器、不调用系统soffice兜底、不修改上游。当前r8证据见`phase-05-office-acceptance.md`首节。

## 文件OCR闭环（2026-10-18）

改造复用 `extensions/companion/windows_ocr.py`（显式语言、原生识别及预算）、`extensions/desktop/ocr/ocr.py`（统一结果契约/旧包格式/选定解释器）、`ui/readiness.py`（匹配实际依赖）、`ui/server.py capability_bootstrap`（首选不被后续候选覆盖）。直接复用 `ui/app/management.js` 的模块实现控件，无新增界面。维护工具 `tools/verify_windows_file_ocr.py` 生成图片后经真实服务验证，`tools/verify_ocr_provider_ui.mjs` 复用既有隔离Bridge/Edge模式验证真实保存；不是平行产品实现。候选r9与证据见功能手测指南当前节。

## 桌面动作链路（2026-10-18）

改造复用`extensions/desktop/control/authorized_action.py`、`uia.py`与既有`extensions/desktop/service.py`，不另建动作服务/授权系统。直接复用`verification.py`的文字核验并在编排层标记证据新鲜度；仅可信宿主显式回调会在动作后采图，JSON服务不接受函数。既有`tools/verify_desktop_owned_window.py`改造为支持候选运行时、隔离注册库与禁止激活的隐藏窗口，完整服务实测7项；初版焦点失败与修复保留记录。前端沿用能力卡开关/模块实现选择及DSH原生工具，无新增控件。r10证据与限制见功能手测指南当前节。

## 一次性截图翻译与新版诊断（2026-10-18）

直接复用DSH默认`skill-filesystem`发现机制、`tools/run_module.py`与OCR模块服务、当前工作模型。新增受管Skill模板与小型发布适配器，改造既有Workbench启动点传入当前能力数据库；不新增UI、工具provider或模型路由。用户同名Skill保留；模板迁移按真实绝对路径生成。复用现有网页咨询原生工具、guard、snapshot维护夹具，未重复已用完的真实站点发送授权。新版DSH的message级工具结果由`extensions/diagnostics/dsh.py`独立适配，兼容旧格式、冲突ID不关联、正文不导出。候选及验证结果见功能手测指南与三份状态记录`screenshot_translation_and_review_20261018`。

## r11治理与模块验收复用（2026-10-18）

直接复用`verify_memory_policy_ui.mjs`、`verify_companion_profiles_ui.mjs`、`verify_schedule_ui.mjs`、`verify_personal_data_migration.py`。改造既有`verify_memory_relations_ui.mjs`补足真实UI提议/导出/恢复/重置/遗忘，改造`verify_ocr_provider_ui.mjs`补排序/移除/重新添加；不另建验收框架或产品入口。实际包内Bridge/UI证据见功能手测指南新节；产品无变更，维护脚本未同步回已构建候选。

### 2026-10-18 原生定时复用核验

直接使用runtime/dsh的dsh-web-app/cordis.patch.yml（schedule与ui-schedule）、presets/standard.patch.yml（tool-schedule）及dsh-schedule公开API；参考tools/verify_schedule_dsh.py的隔离DSH/ModelFixture，新增verify_native_schedule.py与UI同伴脚本用于验证不同的上游原生引擎，不新写调度实现。ui/schedule.py与review_dsh.mjs继续作为待整合资产，未删除或静默启用旧定义。

### 2026-10-18 网页咨询安装修复

改造现有review_install.py/原生review_dsh.mjs/Workbench登记，直接复用DSH workspaceRegistry.list的sessionIds与tools/run_module.py；不新建项目白名单数据库、网页工具或导航。自动登记使用实际个人registry，保留旧显式禁用与作用域。源码21项Python/7项Node及真实原生5组检查通过，r12/全量待验。


2026-10-18：tools/verify_role_resources_ui.mjs复用verify_memory_relations_ui.mjs的隔离真实Bridge/Edge基座；用于已批准同一角色资源编辑器的真实HTTP保存/备份/校验/配色/重开/角色隔离，无外部模型调用。用法：node tools/verify_role_resources_ui.mjs <output>；SUMIKA_TEST_CANDIDATE及SUMIKA_TEST_PYTHON可选最终产品/包内解释器。角色发现使用合成列表，其他管理请求落真实角色资源，报告明确边界。

## 2026-10-18 定时执行整合

ui/app/management.js:openSchedules 和 prototype-d 原定时能力卡改造后使用；DSH commands/schedule/workspaceRegistry 直接使用；原 workbench host 插件、可信 iframe 桥接改造后使用。extensions/desktop/schedule_dsh.mjs 仅承担显式确认、归属校验和请求幂等落盘，不维护任务时钟、任务列表或历史。设计稿未画绑定控件，已获 R-145 确认。

端口归属修复：sumika_next/dsh.py 与 ui/bridge_probe.py 原PowerShell查询改造后共用 sumika_next/socket_ownership.py。原方法真实重复超时，不能作为稳定高频检查；无现成原生查询资产，使用Windows公开GetExtendedTcpTable，不新增缓存授权或绕过校验。真实IPv4/IPv6及拒绝边界已验。
