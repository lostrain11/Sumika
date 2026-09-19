# 现成资产台账

目的：避免重复出现「用户已经给了成品资产，模型却另写一套」的错误。做任何任务前先查这里，再查工作区；有新资产就登记。

## 规则

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
| DSH 本机运行时 | `runtime/dsh/` | 上游依赖 | 直接使用 | 锁定 0.1.5-rc.2；禁止修改其源码与 node_modules |
| DSH 客户端 UI 插件（主题/审批/会话等） | `runtime/dsh/node_modules/.pnpm/@deepseek-ai+dsh-client-ui-*` | 上游插件 | 尚未使用 | 皮肤方案走这里，见 `workbench-skin-plan.md` |
| 办公能力隔离环境 | `.sumika-next/office-env/` | 依赖环境 | 直接使用 | 含 docx/openpyxl/pptx/rapidocr/pypdfium2 |
| 语音隔离环境与模型 | `.sumika-next/desktop-env/`、`.sumika-next/voice-models/` | 依赖环境 | 直接使用 | vosk + sounddevice + 中文模型 |
| 记忆嵌入环境与权重 | `.sumika-next/memory-env/`、`.sumika-next/embedding-models/` | 依赖环境 | 直接使用 | fastembed 权重本地离线使用 |
| BrowserSkill 固定版本 | `runtime/browserskill/bsk.exe` | 上游工具 | 直接使用 | 0.1.11，随客户端提供 |

## 本次事故记录（2026-09-15）

用户提供了完整的 D 方向设计稿，我却按自己的理解另写了一套精简外壳（`ui/app/app.js` + `app.css`），直到用户看截图发现与设计不符。教训不是「参考得不够」，而是**默认选择了更省事的自研路径，且没有事先说明**。后果：白做一套样式、延误进度、用户要亲自发现问题。

已采取的纠正：设计稿直接作为外壳；自研样式已删除；规则写入 `AGENTS.md` 与本台账。
