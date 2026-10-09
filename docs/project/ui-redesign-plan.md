# Sumika UI 重新规划与统一化实施计划（交接版）

- 建立日期：2026-09-20
- 计划性质：交接给执行模型的详细施工计划。本计划基于对现有代码与文档的实际核对，不是凭空重写。
- 执行前提：**先读完第 1、2 节再动手**。任何界面改动必须遵守 `AGENTS.md` 的「防走岔」与「设计稿是视觉参照，不是删功能授权」两条强制规则。

---

## 1. 不可协商的硬约束（优先级最高，冲突时以此为准）

### 1.0 用户已确认决策（2026-09-20，效力等同于需求）

1. **活动室采用「版C · 对话优先紧凑」布局**（样稿 `.sumika-next/ui-mockups/版C-对话优先-紧凑.png`）：左列约 55%（上舞台、下名册），右列约 45% 加宽对话栏。**附加已定交互：部员名册默认收起，仅在鼠标靠近并停留一段时间（hover 延迟，建议 300–500ms）时上浮显示**；收起态保留一个可见的 slim 触发条/把手，键盘聚焦与触屏点击同样可展开（无障碍）。此交互用户已明确批准，无需再问。
2. **页内桌宠在「活动室以外的所有页面」都应显示**（含工作台屏）：当前 `bind.js:35` 的 `body.on-board #deskpet{display:none}` 是按旧原因（示例台词+避免叠加）隐藏的，台词问题已不存在；恢复显示时需核对与 DSH 界面的层级/遮挡（z-index、拖动范围），若实测确有遮挡冲突，改为默认收起为圆钮而非移除，并把结论写进覆盖表。
3. **OS 级独立桌宠窗口（客户端最小化/后台仍可见的置顶小窗）确认为 P7 方向**：内容 = 活动室舞台缩小版，与主窗口共享会话。架构前提是桌面壳（Tauri/Electron 类，调研参考见 `docs/project/screen-companion-plan.md` 与 `ui-design-proposal.md` L2），**本次 UI 重构不实现**，仅按 4.5 预留规范保留「桌宠模式」能力卡与舞台控制里的「独立桌宠窗口」预留位，悬停说明写清「需桌面壳，规划 P7」。

### 1.1 通用硬约束

1. **不删功能**：DSH 原生能力（会话轨迹页、用量/用时、系统提示词、模型选择、权限模式、复制/反馈、侧栏折叠）与已验收的 Sumika 扩展功能一律保留，只做样式贴近。删除或隐藏任何既有功能必须由用户明确要求。
2. **单一入口 / 单一来源**：同一能力或屏幕不允许有两个入口。新增任何导航、按钮或面板前，先列出它会不会与既有入口重复；重复即否决。
3. **先定位设计稿**：每块改动动手前写明「设计稿 `ui/prototype-d/index.html` 中这块是 X（大致行号）」或「设计稿没有这块，属于新增」。**新增项必须先问用户，不许先做。**
4. **原型与产品分离**：验证性代码放 `.sumika-next/` 运行目录，绝不放进 `ui/app/` 或 `extensions/ui/` 交付路径。`ui/prototype-d/` 是只读原型资产，**不修改**。
5. **不动后端与数据**：不改权威数据来源、配置保存、授权、隔离和失败关闭行为；不改 DSH 上游源码、安装包、node_modules；不动 `ui/server.py`、`ui/management.py`、`extensions/roles/` 等业务逻辑（除非计划中明确标注）。
6. **可检查、可回归**：每完成一个阶段，运行对应的 `tools/verify_*.mjs` 与 Python 测试；新约束要写成验收断言，不只写在文档里。
7. **未提交改动保护**：仓库当前有安装与个人数据管理相关的未提交改动（`ui/app/management.js`、`ui/management.py`、`ui/server.py`、`sumika_next/paths.py` 等，见 `git status`）。**不得 commit、revert、stash 或覆盖这些改动**；你的工作叠加在其上。GitHub 不是最新完整状态。
8. **证据规范**：证据只落本地运行目录（`.sumika-next/`），URL 脱敏，不含凭据；不用脚本点击隐藏节点冒充验收；真实交互截图人工核对。
9. **EXE 不在本次范围**：修改源码不会更新已安装的 EXE；本次只改源码与文档，不重新构建安装包。

---

## 2. 开工前必读（按顺序，读完再动手）

| 顺序 | 文件 | 读什么 |
| --- | --- | --- |
| 1 | `AGENTS.md` | 开发边界、防走岔、已有资产优先、设计稿规则 |
| 2 | `docs/project/handoff.json` | 当前阶段、`ui_workbench`/`ui_shell` 段落、最近完成项 |
| 3 | `docs/project/ui-design-coverage.md` | 逐屏设计稿↔实现对应关系与未验证项；**每次界面改动后必须更新此表** |
| 4 | `docs/project/ui-v2-execution.md` | 历史 UI 改动与验收方法（注意：旧状态与新状态混在一起，不能全当当前事实） |
| 5 | `ui/prototype-d/index.html` | 视觉参照（只读） |
| 6 | `ui/app/index.html`、`ui/app/layout.css`、`ui/app/bind.js` | 当前外壳四页实现（本次改造主战场） |
| 7 | `docs/project/requirements.json` 约 1246/1256 行 | 用户原话：「布局是设计参考，有更合适的想法也可以不遵守」 |

---

## 3. 现状盘点（已核对代码，2026-09-20）

### 3.1 结构总览

```
顶栏 .topbar（晴日部室 brand · 全局导航 活动室/工作台/能力/设置 · 模型 chip · 连接状态）
├─ 屏1 活动室 #screen-room：名册 .roster(216px) | 舞台 .stage(CSS绘制房间+VRM/立绘) | 对话栏 .chat(336px)
├─ 屏2 工作台 #screen-board：页面内 iframe 承载受管 DSH（外壳顶栏保留；DSH 侧栏=项目/任务树）
├─ 屏3 能力 #screen-shelf：卡片分组 .cap-grid(固定5列) + 右侧详情 .cap-side(300px)
├─ 屏4 设置 #screen-settings：左导航 .set-nav(208px) | 分区卡片 .set-card | 右信息栏 .set-side(296px)
└─ 桌宠 #deskpet：跨页常驻浮动小窗（活动室隐藏），300px 取景框+气泡+输入
```

相关文件：

- 外壳：`ui/app/index.html`（结构+主 CSS 内联 ~1500 行）、`ui/app/bind.js`（数据接线 ~1170 行）、`ui/app/management.js`（管理弹窗）、`ui/app/theme.js`（主题同步）、`ui/app/appearance.js`（本地背景）、`ui/app/layout.css`（暗色覆盖+响应式+工具提示+对话框）
- DSH 侧插件：`extensions/ui/sumika-brand`（品牌槽）、`sumika-skin`（皮肤令牌/侧栏/时间线/输入区）、`sumika-workbench`（会话头状态药丸）
- 原型资产（只读）：`ui/prototype-d/index.html`；原设计项目在 `D:\Code\Sumika-UI-Designs\direction-d-hiyori`

### 3.2 已确认的不一致与问题（本次要修的核心清单）

| # | 问题 | 证据位置 | 严重度 |
| --- | --- | --- | --- |
| P-1 | **卡片尺寸与栅格不统一**：能力页 `.cap-grid` 写死 `repeat(5,minmax(0,1fr))`，窗口变窄时卡片被挤压变形而非换行；`.cap-card` 用 `min-height:168px` 但内容多少不一导致视觉高度参差；活动室三栏（216/fr/336）与设置三栏（208/fr/296）宽度不成体系 | `ui/app/index.html:162,414,425-426,468` | 高 |
| P-2 | **图标体系缺失**：能力卡片图标是 Unicode 字符（⌨ ✎ ⧉ ❖ ⬡ ▤ ◑ ▣ ⧈ ◔ ✿ ❈ ♪ ✦ ❀ ⚙），风格不一、部分字形在不同系统渲染为豆腐块，无语义化图标库 | `ui/app/index.html:733-856`、`bind.js capabilityCard()` | 高 |
| P-3 | **颜色硬编码绕过令牌**：大量 `#f1eee0`、`#d8d4c2`、`#b3ab8f`、`#e6c3cf`、`#cfe0d4` 等字面色散在内联 CSS 与 JS 中，暗色主题下只能靠 `layout.css` 逐条补丁覆盖，是夜间模式不一致的根源 | `ui/app/index.html` 全文 vs `layout.css:1-18` | 高 |
| P-4 | **主 CSS 与 HTML 单文件耦合**：~950 行内联 `<style>` 混在 index.html，缺模块化拆分，修改易互相影响 | `ui/app/index.html:7-499` | 中 |
| P-5 | **说明文字直接写在选项下方**：设置行 `<small>`、能力页「使用提示」面板等把解释文本常驻在界面上；用户要求改为悬停/聚焦显示 | `index.html:883-936`、`bind.js renderCapabilityDetail()` | 中 |
| P-6 | **工具提示机制不统一**：已有 `.sumika-help-trigger`/`.sumika-tooltip`（layout.css:112-115）与原生 `title` 属性（如语音按钮）两套并存，触发方式、样式不一致 | `layout.css:112-115`、`index.html:705` | 中 |
| P-7 | **预留项表达不统一**：名册 `.member.rsv`、能力卡 `.cap-card.reserved`、设置 `.rsv-tag`、舞台 `.d-ctrl.rsv` 四种预留样式各自为政 | `index.html:179-182,538,562,769,884` | 中 |
| P-8 | **响应式断点只覆盖顶栏**：`layout.css` 的 @media(1250/960/680/380) 主要修顶栏换行；三栏布局、卡片栅格、舞台取景在 1024-1366 常见宽度下无规则，能力页 5 列在小窗挤压（P-1 同因） | `layout.css:65-103` | 高 |
| P-9 | **潜在冗余入口待审计**：顶栏 `.back-btn#backBtn`（回活动室）与全局导航重复；顶栏模型 chip 与设置·模型与连接、工作台 DSH 模型 chip 三处显示同源信息；桌宠输入框与活动室对话栏功能重叠的边界需明确（设计意图是跨页快捷对话，可保留但要在覆盖表写明定位） | `index.html:514-515` | 中 |
| P-10 | **工作台皮肤分散**：DSH 侧样式在 `sumika-skin`（皮肤令牌+侧栏+时间线+输入区）与外壳 `bind.js` 工作台加载逻辑之间分工无文档，新人容易改错边 | `extensions/ui/sumika-skin/`、`bind.js bindWorkbench()` | 低 |
| P-11 | **顶栏「设计原型 · 模拟数据」徽标**：`.proto` 元素仍带原型字样（运行时由 bind.js 改写为连接状态，需核实当前真实呈现），静态结构残留易误导 | `index.html:516` | 低 |

### 3.3 当前功能清单（保留基线，逐屏）

> 以下为「已接线真实功能」，执行中**全部保留**；详细对应关系以 `ui-design-coverage.md` 为准。

- **活动室**：真实角色名册（含用户导入、完整性检查）、角色资源管理（改名/绑定/导出/归档/资源包恢复）、角色卡导入、舞台 VRM 实机渲染/立绘占位、镜头模式、活动演示、真实角色对话（每角色独立会话、历史分页、清空）、语音输入按钮（5 秒录音本地识别填草稿）、角色回复朗读/停止、按消息意图显示的「转到工作台」草稿交接
- **工作台**：受管 DSH 全功能（会话/项目树/终端/工具/diff/审批/轨迹/用量/附件/权限模式/模型选择）、Sumika 皮肤（令牌/气泡/工具卡/输入区/侧栏项目术语）、会话头状态药丸、提示词优化入口（aria-disabled 预留）、离线状态提示条
- **能力页**：三组真实能力卡（DSH 原生/扩展模块/就绪视图）、真实开关读写、点选详情（状态/依赖/权限/语音交互与长期记忆的详细配置）、麦克风独立授权、定时任务入口
- **设置页**：8 个分区真实导航（外观含主题浅/夜/跟随系统+本地背景、模型与连接三用途分栏、连接与权限含网页咨询授权、数据与存储含安装/迁移/备份/记忆等）、版本信息
- **桌宠（页内 L0）**：拖动、真实对话记录、快捷输入、收起为圆钮、内容为活动室舞台缩小克隆（房间场景 + 独立 VRM 实例）；当前在活动室与工作台两屏隐藏，按 1.0-2 决策工作台屏恢复显示。OS 级独立窗口（L2，最小化可见）为 P7 预留，本次不实现。

---

## 4. 设计系统规范 v1（本次统一的目标态）

### 4.1 设计令牌（单一来源）

- 保留现有配色体系（米白/墨绿/玫红/水色/琥珀），**所有颜色必须走 CSS 变量**，禁止新增字面色。现有字面色按 P-3 逐步收编进令牌。
- 做法：在 `ui/app/` 新建 `tokens.css`，集中定义 `:root` 浅色令牌 + `html[data-theme='dark']` 暗色令牌（吸纳现 `layout.css:1-18` 的覆盖）。组件需要语义化变体时新增语义令牌（如 `--surface-hover`、`--switch-track`、`--focus-ring`），不就地写字面色。
- 圆角/间距/阴影统一：`--radius`(9px) 基础上补 `--radius-sm:7px`、`--radius-lg:12px`、`--gap:12px`、`--card-pad:13px`、`--shadow` 已存在。组件一律引用变量。

### 4.2 模块化卡片标准（对应用户建议①）

所有「功能卡片」（能力卡、设置卡、侧栏信息面板、详情面板）统一一个基础规格，变体只允许改内容不改骨架：

| 属性 | 标准值 | 说明 |
| --- | --- | --- |
| 容器 | `.sumika-card` 基类 | border:1px var(--line)；radius:var(--radius)；background:var(--paper)；padding:var(--card-pad) |
| 能力卡高度 | `min-height:168px`（沿用），内容区 `flex:1`，底部行固定 | 一组内所有卡片同高 |
| 栅格 | `grid-template-columns:repeat(auto-fill,minmax(200px,1fr))`，gap:12px | **替换写死的 5 列**；宽窗自然多列、窄窗自动换行，卡片不再被挤压 |
| 侧栏宽度体系 | 三栏页面的边栏从 {216, 300, 336, 208, 296} 收敛为两档：`--side-w:220px`（名册/设置导航）、`--panel-w:320px`（详情/信息栏/对话栏可保留 336 作为对话特例，需记录理由） | 允许特例，但每个特例在覆盖表写明 |
| 预留卡 | 统一 `.sumika-card.is-reserved`：虚线描边 + `.rsv-tag`「预留 · P?」+ 禁用开关 + 悬停说明 | 替换 P-7 的四种写法 |

### 4.3 图标体系（对应用户建议⑥）

- **选型：Lucide**（ISC 许可证，线性图标，与日系清爽风格匹配；纯 SVG 无运行时依赖，适合本项目的本地静态托管）。备选 Tabler Icons（MIT）。不建议引入 Iconify 运行时（增加依赖与网络面）。
- 落地方式：
  1. 从 lucide 官方包（`lucide-static`）**字节级复制用到的 SVG** 到 `ui/vendor/icons/`，附 `LICENSE` 与来源/版本记录（参照 `ui/vendor/README.md` 既有做法，记 SHA-256 前缀）。不引 npm 构建链。
  2. 新建 `ui/app/icons.js`：导出 `icon(name, {size})` 返回内联 SVG 字符串（带缓存），`aria-hidden="true"`，颜色 `currentColor`，尺寸默认 16。
  3. 建映射表 `ICON_MAP`，一次预留足量槽位，后续新功能**优先在此表选图标**，不够用再按同流程从 Lucide 补：

| 功能 | Lucide 图标名 | 功能 | Lucide 图标名 |
| --- | --- | --- | --- |
| 终端执行 | `square-terminal` | Office 文档 | `file-text` |
| 文件编辑 | `file-pen-line` | OCR·截屏翻译 | `scan-text`（或 `scan-line`） |
| 子代理 | `bot` | 桌面软件控制 | `app-window`（或 `mouse-pointer-click`） |
| Skills | `puzzle` | 内置浏览器 | `globe` |
| MCP 连接 | `plug`（或 `network`） | 定时任务 | `calendar-clock` |
| 连续记录 | `history` | 长期记忆 | `brain` |
| 成果回执 | `receipt-check`（或 `badge-check`） | 语音交互 | `audio-lines`（或 `mic`） |
| 角色卡·世界书 | `book-open`（或 `contact-round`） | 桌宠模式 | `paw-print` |
| 设置 | `settings` | 外观 | `palette` |
| 模型 | `cpu` | 权限/授权 | `shield-check` |
| 数据存储 | `database` | 关于/信息 | `info` |
| 导入/导出 | `import` / `share`（或 `download`/`upload`） | 添加模块 | `plus` |
| 语音输入/朗读 | `mic` / `volume-2` | 相机/摄像头（预留） | `camera` |
| 工作台/任务 | `kanban-square`（或 `layout-dashboard`） | 活动室 | `armchair`（或 `home`） |

- 迁移范围：能力页 `.cap-ic`（bind.js `capabilityCard()` 的 `icon` 参数改为图标名）、设置右侧 hero、桌宠 mini 钮、发送按钮等手写 SVG 逐步归一到 icons.js。
- 验收断言：能力页不再出现 Unicode 符号图标（`verify_capability_ui.mjs` 增加断言：`.cap-ic svg` 存在且无文本字符图标）。

### 4.4 工具提示规范（对应用户建议⑤）

- **统一用既有 `.sumika-help-trigger`（圆形 ? 按钮）+ `.sumika-tooltip`** 作为唯一说明机制（已支持 hover、键盘 focus-visible、触屏点击，见 `layout.css:112-115`），禁止新增常驻解释文本（P-5）。
- 适用对象：设置页各选项的 `<small>` 说明、能力详情中自动提取/模型提议/检索方式/用量等复杂选项（R-118 要求：说明收益、是否额外消耗 token、开关影响，不用工程术语）、预留项的「是什么/何时来」。
- 例外：纯图标按钮（发送、语音、折叠）用原生 `title` + `aria-label` 即可；表单校验类错误提示仍就地显示。
- 改造清单：设置 `.set-row small` 全部迁入 tooltip；能力页「使用提示」面板保留（它是页面级说明，非选项级），但其中逐条规则若与选项重复则删除。
- 工具函数：在 `bind.js` 或新 `ui/app/tooltip.js` 提供 `helpTip(text)` 生成标准结构；tooltip 定位注意右侧栏贴边时向左弹出（现有实现 right:0 已处理，验收时核对 1024px 下不溢出）。

### 4.5 预留接口规范（对应用户建议③）

- 已计划未实现功能**只留 UI 占位，不接假逻辑**：统一 `.is-reserved` 卡片/行 +「预留 · P?」标签 + 禁用态 + 悬停说明（写清规划内容与所属阶段，对应 P-7）。
- 数据侧：预留项不得编造状态、计数或开关效果；开关必须 `aria-disabled` 且无写请求（参照提示词优化入口既有做法）。
- 当前应保留的预留位：角色卡 C 名册位、多人同屏、独立桌宠窗口（P7）、全屏壁纸陪伴（P7）、OCR 翻译（P5）、桌面控制（P5）、内置浏览器（P5，注意 BrowserSkill 后端已部分就绪，卡片文案与状态要从注册表读真实 readiness，不再写死「预留」——以 `/api/modules` + `/api/readiness` 为准）、定时任务（P5，后端已实现 tick/持久化，核对后可能应改为可用卡）、提示词优化入口（F-003 deferred）。
- 场景资源随活动切换（P6）在设计稿有位置但未实现：不新增 UI，只在覆盖表登记。

### 4.6 冗余入口审计（对应用户建议④）

执行第一步先产出《入口唯一性审计表》，逐条核对后在覆盖表登记结论。已识别的候选项：

| 功能 | 唯一权威入口 | 待处理冗余 |
| --- | --- | --- |
| 页面导航 | 顶栏 `.gnav` | 顶栏 `.back-btn#backBtn`（回活动室）→ **移除**（导航已覆盖）；移除前 grep `backBtn` 确认 bind.js 无逻辑依赖，若有则先解耦 |
| 能力开关与详情 | 能力页卡片+详情 | 设置页不得恢复能力分区（已有断言，`verify_ui_management.mjs`） |
| 语音/记忆配置 | 能力页「语音交互」「长期记忆」卡详情 | 设置页不再出现同配置（R-117） |
| 模型状态显示 | 顶栏 chip（只读状态） | 设置·模型与连接显示同源信息——保留但明确「显示/管理在 DSH」，不新增第三个管理口 |
| 主题/背景 | 设置·外观 | 不得在活动室或顶栏加第二个切换 |
| 转到工作台 | 活动室消息按意图显示的按钮 | 不得恢复「所有消息都显示」 |
| 桌宠快捷对话 | 桌宠小窗（活动室以外所有页面） | 与活动室对话栏同一会话数据源，保留；定位=跨页陪伴入口；工作台屏恢复显示（1.0-2） |

### 4.7 主题统一（对应用户建议⑥前半）

- 浅色/暗色双主题已由 `theme.js` + DSH ThemeRuntime 打通，本次任务是**收口**：P-3 字面色全部令牌化后，暗色覆盖表应收敛为「少数结构例外」，逐屏截图核对（活动室/能力/设置/工作台/桌宠）浅色与夜间两态。
- 角色强调色 `--chara` 与 VRM/立绘不套滤镜（既有规则保留）。
- 对比度底线：正文/控件文字对比度 ≥ 4.5:1（参照侧栏工具提示已实测 11.12:1 的做法），验收抽样实测。

---

## 5. 响应式与分辨率测试矩阵（对应用户建议②）

### 5.1 断点与布局规则（新增到 layout.css）

| 宽度区间 | 规则 |
| --- | --- |
| ≥1600 | 三栏全展开，卡片栅格 auto-fill 自然多列 |
| 1280–1600 | 默认基准，全部功能可见 |
| 1024–1280 | 设置/能力右侧栏可收缩为 280px；卡片栅格自动减列 |
| 810–1024 | 活动室（版C）左右两栏改为上下堆叠（对话栏置于舞台下方，名册维持收起态）——这是布局回退不是新交互，可直接做；能力页详情改为选中卡下方展开或弹层（此交互先出方案问用户） |
| ≤810 | 沿用顶栏既有窄屏规则（680 分行、380 导航独立行，勿回归，`verify_narrow_header.mjs`） |

### 5.2 必测矩阵（每阶段完成后跑）

- 分辨率：1920×1080、1600×900、1440×900、1366×768、1280×720、1160×800、1024×576、810×600；窄顶栏边界 680/480/380（已有脚本）
- 缩放：浏览器 100% / 125%（125% 此前未验收，本次必须补）
- 主题：浅色 × 夜间 各一轮截图
- 方法：扩展现有 `tools/verify_ui_v2.mjs`（4 页 × 视口）为矩阵化脚本 `tools/verify_ui_matrix.mjs`：逐组合截图 + 断言无横向滚动（`scrollWidth<=clientWidth+1`）、卡片等高、栅格无挤压（卡片实际宽度 ≥ 190px）；截图落 `.sumika-next/ui-matrix/`，人工逐张核对后在覆盖表登记。

---

## 6. 分阶段执行包

> 每包完成标准 = 实现 + 对应 verify 脚本通过 + 覆盖表更新 + 证据落 `.sumika-next/` + `python -B -m sumika_next.cli check && python -B -m sumika_next.cli handoff` 通过。任何一包不通过不得进入下一包。

### Phase 0 · 基线建立（约半天）

1. 读完第 2 节全部文件；运行 `git status` 记录起点（不提交）。
2. 启动桥接：`tools/start_ui_bridge.ps1 -Port 8765`，依次运行基线脚本：`verify_ui_v2.mjs`、`verify_capability_ui.mjs`、`verify_ui_management.mjs`、`verify_ui_theme.mjs`、`verify_narrow_header.mjs`、`verify_room_chat.mjs`，记录哪些通过哪些基线即失败（失败项如实登记，不替前任背锅也不掩盖）。
3. 四页 × 浅/夜截图人工核对，产出《入口唯一性审计表》（4.6）与《字面色清单》（grep `#` 字面值，按文件分行列出），追加到覆盖表或新文件 `docs/project/ui-unify-audit.md`。
4. 产出：基线报告 + 审计表；**此阶段不改任何产品代码**。

### Phase 1 · 设计系统层（不动页面结构）

1. 新建 `ui/app/tokens.css`：集中浅色+暗色令牌、语义令牌（hover/switch/focus/disabled/tooltip 等）；`index.html` 引入。
2. 字面色收编（P-3）：内联 CSS 与 JS 中的字面色逐条替换为令牌；`layout.css` 暗色覆盖中已解决的条目删除。grep 验证 index.html/bind.js/management.js 中不再出现新的 hex 字面色（允许令牌定义本身与 VRM 材质色）。
3. CSS 拆分（P-4）：index.html 内联样式按模块拆为 `ui/app/css/{base,topbar,room,shelf,settings,deskpet}.css`，用 `<link>` 引入；**类名、id、DOM 结构一律不改**（verify 脚本与 bind.js 依赖现有钩子）；拆分前后跑 `verify_ui_v2.mjs` 对比截图。
4. 图标体系（4.3）：vendor 复制 + icons.js + ICON_MAP；能力页卡片先迁移。
5. tooltip 工具函数（4.4）就位。
6. 验收：`verify_ui_v2.mjs`、`verify_capability_ui.mjs`、`verify_ui_theme.mjs`（浅/夜）通过；新增断言「能力卡图标为 SVG」。

### Phase 2 · 逐屏统一（结构微调）

顺序：能力 → 设置 → 活动室 → 顶栏/桌宠 → 工作台皮肤。

1. **能力页**：栅格改 `auto-fill minmax`（4.2）；卡片应用 `.sumika-card` 基类与等高；预留卡统一 `.is-reserved`；Unicode 图标全换 Lucide；「使用提示」面板去重。验收：`verify_capability_ui.mjs`、`verify_capability_settings_ui.mjs`、`verify_capability_write_recovery.mjs`。
2. **设置页**：`.set-row small` 迁入 help-trigger tooltip；分区导航与卡片宽度应用宽度体系；外观/模型/权限/数据各分区核对一遍「说明不外露」。验收：`verify_ui_management.mjs`、`verify_model_settings_ui.mjs`、`verify_ui_background.mjs`、`verify_browser_authorization_ui.mjs`、`verify_memory_proposals_ui.mjs`、`verify_personal_data_ui.mjs`。
3. **活动室（按版C改造，用户已确认）**：左列上下分区（上舞台、下名册条），右列加宽对话栏（约 45%）；**名册默认收起**，底部保留 slim 触发条，鼠标停留 300–500ms 上浮展开为横向卡片条，键盘聚焦/触屏点击亦可展开，鼠标移出收回；展开/收起有过渡动画且不推挤舞台布局（浮层式 `position:absolute` 上浮，不改文档流）。舞台控制（镜头/活动/预留 d-ctrl）与对话气泡/输入区逻辑不动只核样式。桌宠样式并入 tokens。验收：`verify_room_chat.mjs`、`verify_room_history.mjs`、`verify_user_role.mjs`、`verify_role_import_ui.mjs`、`verify_speech_input_ui.mjs`、`verify_speech_playback_ui.mjs`、`verify_ui_task_intent.mjs`；新增名册收展交互断言（默认收起、悬停延迟后展开、移出收回、不挤压舞台）。
4. **顶栏/桌宠**：移除 `#backBtn` 冗余（先解耦）；核实 `.proto` 徽标的运行时呈现，若已由连接状态取代则清理静态残留；顶栏三处模型信息的单一来源结论写进覆盖表；**恢复工作台屏桌宠显示**（见 1.0-2，核对遮挡，冲突时默认收起为圆钮）。验收：`verify_header_connection.mjs`、`verify_narrow_header.mjs`、`verify_workbench_screen.mjs`（该脚本目前断言桌宠不可见，需按新决策同步修改断言）。
5. **工作台皮肤**：仅皮肤层核对令牌与外壳一致（侧栏/气泡/工具卡/输入区沿用既有语义后缀，不动 DSH 结构）；把 sumika-skin 的分工写一段 README（P-10）。验收：`verify_workbench_ui.mjs`、`verify_workbench_screen.mjs`、`verify_sidebar_geometry.mjs`、`verify_dsh_panel.mjs`、`verify_workbench_status_pill.mjs`、`verify_ui_native_history.mjs`。

### Phase 3 · 响应式矩阵

1. 按 5.1 落地断点规则；1024 以下的「对话栏抽屉/详情弹层」属新增交互，**先出方案给用户确认再实现**，未确认前该区间只做不挤压、可滚动的保底。
2. 新建 `tools/verify_ui_matrix.mjs`（5.2），含 125% 缩放；全部截图人工核对。
3. 验收：矩阵脚本通过 + `verify_native_layout.mjs`、`verify_ui_offline.mjs` 回归。

### Phase 4 · 收口

1. 全量回归：Phase 0-3 所有脚本 + `python -B -m unittest discover tests_next -q` 中 UI 相关套件（参考 ui-v2-execution.md 的组合命令）。
2. 更新 `ui-design-coverage.md`（逐屏新对应关系、未做/偏离逐条列出）、`handoff.json`、`docs/project/ui-redesign-execution.md`（新建执行记录：每包实际修改、命令、结果、限制、下一步）。
3. `python -B -m sumika_next.cli check && python -B -m sumika_next.cli handoff`。

---

## 7. 常见陷阱（前人踩过，别再踩）
1. **不要用实现回答设计问题**：拿不准「该不该有」时先问用户，不先写代码。
2. **不要只做 CSS 显示 DSH 的隐藏控件**：会得到点了没反应的假控件（常驻搜索框教训，见覆盖表屏2）。
3. **不要把长文 markdown 塞气泡**：工作台助手消息保持文档式排版（有意偏离，勿改回）。
4. **改类名/id 前先全局 grep**：`ui/app/*.js`、`tools/verify_*.mjs`、`extensions/ui/` 都锚定现有钩子。
5. **resize 后不能立即按旧状态点击**：等原生响应式稳定再断言（侧栏几何脚本教训）。
6. **管理类验收不用真实用户角色/数据做破坏性操作**；写接口的 Host/Origin/CSRF 检查不得绕过。
7. **暗色主题别用补丁思维**：先令牌化，再谈覆盖；每加一个硬编码色，夜间就多一个坑。
8. **会话中 8765 服务可能是旧进程**：后端相关改动需提示用户正常重启后生效，不强制重启打断用户聊天。

## 8. 完成定义（DoD）

- [ ] 字面色收编完成，tokens.css 为唯一颜色来源；浅/夜两态四页+桌宠截图核对通过
- [ ] 能力/设置/侧栏卡片统一基类与栅格，1366×768 与 1920×1080 下无挤压、同组等高
- [ ] Unicode 图标清零，Lucide 本地图标库 + ICON_MAP 就位，预留槽位 ≥ 20
- [ ] 选项说明全部 tooltip 化，无常驻 small 解释文本（页面级说明面板除外）
- [ ] 预留项四种写法归一为 `.is-reserved` 规范，卡片状态来自真实 readiness
- [ ] 冗余入口审计完成并处理（至少 `#backBtn` 移除或证明其必要）
- [ ] 分辨率矩阵（含 125% 缩放）通过，证据在 `.sumika-next/ui-matrix/`
- [ ] 全部 verify 脚本回归通过；覆盖表、执行记录、handoff.json 更新；cli check/handoff 通过
- [ ] 活动室按版C落地：左列舞台+收起名册（悬停延迟上浮）、右列加宽对话栏；名册收展交互有断言
- [ ] 桌宠在工作台屏恢复显示（或按冲突结论默认收起为圆钮，结论已写覆盖表）
- [ ] 未提交的旧改动原样保留；本次改动可逐项 diff 说明
