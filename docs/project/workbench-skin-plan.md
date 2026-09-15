# 工作台设计与 DSH 皮肤方案（2026-09-15）

用户要求：工作台页就应该**是** DSH 本身，并尽量还原 D 方向设计；认为 iframe 内嵌观感奇怪。

## 约束

用户此前明确要求「不修改 DSH 上游源码、安装包或 node_modules」。因此「直接改 DSH」这条不可行，需要走 DSH 自己的扩展机制。

## 已核实的机制（不是猜测）

1. **DSH 的 Web UI 是插件化的**。受管运行时 `runtime/dsh` 里已安装大量客户端 UI 插件包，例如：
   - `@deepseek-ai/dsh-client-ui-theme@0.1.5-rc.2`（外观主题：light/dark/system、字号；宿主侧入口 `lib/index.js`，客户端包 `lib/client.js` 约 91 KB，类型定义在 `lib/types/`）
   - `@deepseek-ai/dsh-client-ui-brand-official`（品牌/标题区）
   - 以及 `dsh-client-ui-approval`、`dsh-client-ui-chat`、`dsh-client-ui-conversation`、`dsh-client-ui-deliverables`、`dsh-client-ui-commands` 等，正好对应设计图里的审批卡、会话时间线、工具卡、输入框等区域。
   这些包的 `package.json` 带 `exports`，同时提供宿主入口与 `./client` 客户端入口。
2. **profile 的补丁层是我们已经在用的机制**。受管 profile 的 `cordis.patch.yml` 是一个数组，支持 `insert: [{id, name, config}]`，`name` 指向我们自己的 JS 模块；现有实例里已经这样加载了 `sumika-continuity` 与 `sumika-roles`（`extensions/*/dsh.mjs`）。补丁层文件头注释也写明：编辑该文件，不要改 `cordis.yml`。
3. 因此**皮肤应当做成一个独立的 DSH 客户端 UI 插件**，通过补丁层加载——既满足“工作台就是 DSH”，也不触碰上游文件。

## 为什么 iframe 观感奇怪

iframe 里跑的是 DSH 完整应用（含它自己的侧栏、顶栏与内测弹窗），外面再套我们的页头，形成“应用里套应用”。这只适合作为过渡方案；正确做法是让 DSH 直接渲染我们的主题。

## 下一步（按顺序）

1. 读 `dsh-client-ui-theme` 的 `lib/client.js` 与 `lib/types/*`，确认客户端插件的注册契约（如何声明插件、如何注入样式、可用的 CSS 变量/令牌）。
2. 在 `extensions/ui/sumika-skin/` 下实现独立插件：宿主入口（可选设置命名空间与品牌）+ 客户端入口（注入 D 方向令牌：米白纸底、墨绿、玫红、水色、圆角 8–9px、细描边；顶栏标题改为「晴日部室」）。
3. 通过受管 profile 的 `cordis.patch.yml` 加载该插件，用无头 Edge 对比设计图做视觉核对，再把工作台页从 iframe 切回“直接就是 DSH”。
4. 设计中的左侧「项目 ▸ 任务」树与审批卡属于 DSH 已有插件（workspace / approval / conversation）的呈现，优先通过皮肤与已有插件满足；确实缺失的部分再单独加插件，不伪造数据。

## 方案对比：直接改前端 vs 皮肤 vs 客户端插件（2026-09-15 决定）

用户提出：是否放开限制、直接改 DSH 前端来还原设计。核实后的结论是**不建议改前端**，理由基于事实而不是偏好：

1. **DSH 只发布构建产物，不发布前端源码**。客户端 UI 插件包内只有 `lib/`、`client/`、`types/`，`src/` 文件数为 0；网页上加载的是打包后的 `/assets/index-*.js`、`index-*.css`。所以「改前端」≈ 直接改压缩产物，或自行 fork 整个 Web 应用从源码重建。
2. **DSH 仍是 0.1.x-rc 且迭代很快**（其页面自述「核心插件以及基础 API 都会在接下来的时间内快速迭代」）。fork 之后每次上游更新都要重新移植，成本随更新次数线性增长。
3. 上游已有**官方扩展面**：宿主补丁层、`webserver/index-inject` 注入、以及带 `./client` 入口的客户端 UI 插件包。够用就不必 fork。

三种做法对比：

| 做法 | 能力上限 | 上游更新成本 | 风险 |
| --- | --- | --- | --- |
| 改前端 / fork | 最高，可任意重构 DOM | **高**，每次更新都要移植 | 高：压缩产物补丁易碎，fork 会腐烂 |
| 皮肤（CSS + 注入） | 令牌、品牌、局部样式 | 低 | 低：类名非稳定 API，需在每次 DSH 升级后回归视觉 |
| 客户端 UI 插件（host + `./client`） | 可贡献真实组件与服务接入 | 中 | 中：依赖客户端插件契约，需跟随版本 |

**决定**：

- 视觉令牌、品牌、局部样式 → **皮肤**（已完成地基）。
- 需要在 DSH 内部新增结构化 UI（例如设计里的项目/任务树、审批卡版式）→ **客户端 UI 插件**，而不是 CSS 覆盖，也不是 fork。
- DSH 已有的会话时间线、审批流程 → 保留 DSH 自己的组件，只做皮肤级调整，避免重造并保证行为一致。
- 只有出现「扩展面确实无法表达，且必须结构性改动」的具体需求时，才重新评估 fork，并且要单独说明维护代价。

## 皮肤能力实测上限（2026-09-15）

把皮肤做扎实之后，实测到的事实决定了后续路线：

- 前端包是 `@deepseek-ai/dsh-web-frontend@0.1.5-rc.2`，样式为 `dist/assets/index-*.css`。
- 它对外**只定义 37 个 CSS 变量**，且用途很窄：文件类型色、滚动条、`--dsh-state-ongoing`、代码块/diff/终端/搜索的圆角与字体、`--dsw-elevation-stroke-color`、hovercard 背景等。**没有通用调色板令牌**（没有 `--bg`/`--text`/`--accent` 之类）。
- DOM 类名是 CSS Modules 哈希（例如 `pI_x6G_frame`、`_dialog_w1urq_22`、`jLrgrW_dialog`），不是稳定 API。

已接入皮肤并实测生效的令牌：`--dsh-boot-bg`、`--dsh-boot-brand`、`--dsh-state-ongoing`、`--dsh-scrollbar-*`、`--dsl-web-radius`(9px)、`--dsl-diff/read/search/terminal-radius`、`--dsw-elevation-stroke-color`、`--dsw-hovercard-bg`、`--dsl-code-block-*`。验证值：`--sumika-paper=#f7f4ec`、`--dsl-web-radius=9px`、`--dsw-elevation-stroke-color=#e2dccd`、`--dsh-state-ongoing=#a94067`、`body` 背景 `rgb(247,244,236)`。

由此得到明确结论：**靠 CSS 皮肤无法还原整套设计**。它能做全局底色、圆角、描边、滚动条、状态色这类表面调整；要还原设计里的结构（项目树、时间线版式、审批卡、输入区），必须在 DSH 内渲染我们自己的组件，即走**客户端 UI 插件**（自带稳定类名），而不是继续加大 CSS 覆盖。

下一步的调查目标：读一个客户端 UI 插件包的 `./client` 入口与类型，确认它能做到哪一步——是只能追加面板，还是可以参与主布局；据此决定设计稿里哪些结构可以落地、哪些必须保留 DSH 原生组件。

## 客户端插件契约（2026-09-15 已核实）

读 `@deepseek-ai/dsh-client-ui-theme` 与 `@deepseek-ai/dsh-client-ui-goal` 的 `package.json` 与类型后确认：

- 插件的浏览器半边通过 `package.json` 的 **`dsh.client`** 字段声明，含 `inject`（依赖的其他客户端模块）、`platform: "web"`、`immediately`；`exports["./client"]` 指向 `lib/client.js` 与其类型。宿主半边仍是 `lib/index.js` + `dsh` 补丁层。
- 存在插槽体系与 UI 基础件：依赖里出现 `@deepseek-ai/dsh-client-ui-slots`、`dsh-client-ui-primitives`、`dsh-client-ui-renderer`、`dsh-client-ui-settings`、`dsh-client-store`；插槽名是字符串键，通过模块增强声明（主题插件占用 `settings.theme`，把自己的「外观」设置行注册进设置的常规区）。
- 客户端插件确实能往应用区域加**真实组件**，不只是样式：`ui-goal` 的 `inject` 里包含 `@deepseek-ai/dsh-client-ui-chat`，说明它扩展的是聊天区域；主题插件则扩展设置区。

仍待确认的一点：主布局区域（项目侧栏、会话时间线、输入区）是否也是可插拔插槽。若可插拔，设计稿的三栏结构可以由插件组件承担；若只开放设置行与聊天内挂件这类位置，那么设计稿的三栏只能靠「DSH 原生面板 + 皮肤 + 插件挂件」组合逼近，而不是整版重排。

结论：**设计稿的结构件走客户端插件**（有稳定类名、可接 DSH 数据），已排除「CSS 硬覆盖」与「fork 前端」两条路；下一步只需把插槽清单确认清楚，即可开工。

## DSH 自带的 UI 插件清单（2026-09-15 实测枚举）

直接枚举 `runtime/dsh/node_modules/.pnpm` 内所有客户端 UI 插件包，得到 40 个，与设计稿的对应关系如下（**这回答了「主布局是否可插拔」**：布局、侧栏、会话、审批、品牌都是各自独立的插件）：

| 设计稿区域 | DSH 现有插件 | 结论 |
| --- | --- | --- |
| 整体布局 | `dsh-client-ui-layout` | 可插拔 |
| 左侧「项目 ▸ 任务」树 | `dsh-client-ui-sidebar`、`-sidebar-files`、`-sidebar-right`、`-sidebar-documentpreview` | 侧栏可插拔，可自建 Sumika 侧栏插件 |
| 中间会话时间线 | `dsh-client-ui-conversation`、`-chat`、`-trajectory` | 已由 DSH 提供 |
| 工具卡 / 成果 | `dsh-client-ui-tool`、`-deliverables`、`-plan`、`-goal` | 已由 DSH 提供 |
| 审批卡（确认执行/取消/检查点） | `dsh-client-ui-approval` | 已由 DSH 提供，皮肤只调样式 |
| 顶部品牌 | `dsh-client-ui-brand-official` | 可替换/扩展，设计里的「晴日部室」可落在这里 |
| 设置各分区 | `dsh-client-ui-settings-general`、`-settings-models`、`-settings-plugins`、`-settings-plugin-inventory` | 设置项按分区插件注册 |
| 输入区与快捷指令 | `dsh-client-ui-commands`、`-input-trigger`、`-attachment` | 已由 DSH 提供 |
| 其他（任务/日程/子 Agent 等） | `-jobs`、`-schedule`、`-subagent`、`-workflow-run`、`-skill`、`-user-questions`、`-message-feedback`、`-model-selection`、`-permission-presets`、`-directory-picker-*`、`-open-in-app`、`-agent-preset`、`-reference`、`-session` | 与设计稿无直接对应，保留原生 |

由此确定的实施顺序（每一步都可以独立验收，不需要动上游）：

1. **品牌插件**：把顶部品牌换成设计里的「晴日部室」，参考 `dsh-client-ui-brand-official` 的做法。
2. **侧栏插件**：把设计里的「项目 ▸ 任务」树做成 Sumika 侧栏插件，数据接我们自己的 `/api/tree`（真实阶段与任务状态）。
3. **皮肤收尾**：审批卡、时间线、输入区保留 DSH 原生组件，皮肤只做令牌级调整（圆角、描边、状态色已就绪）。

三条都遵守同一约束：不修改 `runtime/dsh` 下的任何文件，全部通过 profile 补丁层与独立插件包加载。

## 客户端插件的最小形态（2026-09-15 读 `brand-official` 源码）

读 `@deepseek-ai/dsh-client-ui-brand-official` 后确认了客户端插件的实际形态：

- **包结构**：`package.json`（含 `main: lib/index.js`、`exports["./client"] → lib/client.js`、`dsh.client.inject` 依赖列表、`platform: "web"`）+ `lib/index.js`（宿主半边）+ `lib/client.js`（浏览器半边）+ `lib/types/client/*.d.ts`。
- **客户端模块格式**：浏览器半边不是普通 ESM，而是
  `window.__ModuleLoader__.load({ id, factory: (require) => { ... } })`，通过 `require()` 拿到 `react/jsx-runtime`、`@deepseek-ai/dsh-client-ui-primitives` 等；导出 `inject`（所需服务）与 `apply(ctx)`。
- **UI 挂载方式**：`apply(ctx)` 从 ctx 取「UI 插槽注册表」服务，把 React 组件注册进具名插槽。品牌插件填的是 sidebar 的 brand 插槽；主题插件填的是设置页的 Appearance 行。两者用的是同一套注册表。
- 组件可以复用 DSH 自己的 UI 基础件（例如 `FishLogo`、`BrandWordmark`），所以自建插件在视觉上能和原生保持一致。

### 因此还需要先确认两件事（不确认就动手会白做）

1. **插槽键名清单**：sidebar 到底暴露哪些键（brand mark、brand name、列表项、右侧栏等）。官方品牌插件的类型文件只声明了 `apply`，具体键名在 `lib/client.js` 的注册调用里，需要继续读。
2. **插件加载路径**：DSH 的客户端模块是由 Web 服务从「已安装的插件包」解析并下发的。我们的插件包放在 `extensions/ui/` 下，能否仅通过 profile 补丁层按路径加载客户端半边，还是必须把包安装进 profile 的依赖里——这一点必须先验证，否则写好的客户端插件加载不起来。

结论：**品牌插件与侧栏插件的代码形态已经清楚，但落地前必须先解决「插槽键名」与「加载路径」两件事**，这两件事都属于可以在本地查证的事实，不需要猜测。

## 两个卡点已查清（2026-09-15）

### 1. 插槽注册契约（读 `brand-official/lib/client.js`）

```js
const inject = ["slots"];                     // 需要的服务名
ctx.slots.inject("sidebar.brand.mark", () =>  // 插槽存在时才执行，避免竞态
  ctx.slots.inject("sidebar.brand.name", function* () {
    yield ctx.slots.register({ name: "sidebar.brand.mark" }, OfficialBrandMark);
    yield ctx.slots.register({ name: "sidebar.brand.name" }, OfficialBrandName);
  }));
```

- 服务名：`slots`；注册 API：`ctx.slots.register({ name: "<键>" }, 组件)`；插槽键是点号字符串（已确认：`sidebar.brand.mark`、`sidebar.brand.name`）。
- 用 `ctx.slots.inject(键, 回调)` 做依赖门控，插槽出现后才注册。
- 官方品牌与我们要注册的是同一组键。**更正（2026-09-15 实测）**：不需要停用官方插件，也不需要猜它的 id。单占用槽按 `priority` 决定占用者，**数值最小者渲染**；官方注册在 `priority: 0`，我们注册 `priority: -1` 即可接管。详见下方「单占用槽与列表槽（已实测）」。

### 2. 客户端插件如何被加载（读 `dsh-client-modules/README.zh.md`）

`@deepseek-ai/dsh-client-modules` 的职责就是**把插件包的 `dsh.client` 声明变成可加载的浏览器 bundle**：

- 宿主半侧扫描**已启用的 Loader 条目**，组合启动图；Web 载体在 `/plugins` 下提供每个 bundle；浏览器半侧按需懒加载（bundle 首次执行只注册 factory，不产生副作用）。
- 因此**不需要逐插件接线**：包内声明 `dsh.client`（`platform: 'web'`、导出 `./client`、基座之外的依赖写进 `dsh.client.external`）即可；`<id>/client` 与裸 id 解析到同一导出。
- 对我们的意义：`sumika-skin` 目前是把 Loader 条目指向单个 `dsh.mjs`（纯宿主插件）；要加**客户端半边**，Loader 条目需要指向**包（package.json）而不是单个文件**，这样宿主才能读到 `dsh.client` 与 `./client` 导出。

结论：编写 `extensions/ui/sumika-brand/`（`package.json` + 宿主半侧 + `lib/client.js` 浏览器半边 + 类型）并按包加载的技术路径已经明确，无未解阻塞。

## 单占用槽与列表槽（2026-09-15 真实客户端实测）

读 `@deepseek-ai/dsh-client-ui-sidebar/lib/client.js` 的 `apply`，侧栏插件自己声明了整棵子树：

```js
ctx.slots.inject("sidebar", () => ctx.slots.register({
  name: "sidebar",
  children: {
    "sidebar.brand.mark":  { kind: "single", scope: "root" },
    "sidebar.brand.name":  { kind: "single", scope: "root" },
    "sidebar.panellist":   { kind: "list",   scope: "root" },
    "sidebar.workspaces":  { kind: "single", scope: "root" },
    "sidebar.settings":    { kind: "single", scope: "root" },
    "sidebar.footer.action": { kind: "list", scope: "root" },
  },
  inject: injectProps,
}, SidebarRoot));
```

由此确定两类槽的注册要求，并已在真实受管实例上验证：

| 槽类型 | 注册要求 | 实测结果 |
| --- | --- | --- |
| `single`（品牌、`sidebar.workspaces`、`sidebar`） | 同槽已有占用者时报错 `single slot ... already has a registration at priority 0 — register at a different priority to shadow it (lowest renders)` | `priority: -1` 成功接管，官方品牌插件保持启用；不需要停用上游插件，也不需要猜上游插件 id |
| `list`（`sidebar.panellist`、`sidebar.footer.action`） | 必须带 `options.id`，否则报错 `list slot ... requires options.id` 且不渲染 | 带 `id: 'sumika-status'` 后与原生条目并排渲染 |

其他实测结论：

- `sidebar.footer.action` 接收 `{ wide }`；侧栏折叠成 36px 轨道时该区域没有空间，组件应据此返回空。
- `sidebar.panellist` 不是「侧栏里的内容区」，而是**主区域面板的切换器**：条目提供 `{id, label, order}` 与图标，点击后调用 `ctx.layout.selectPanel(id)`，而该面板必须在 `main` 槽注册（见 `dsh-client-ui-conversation` 的 `slots.register({ name: "main", key: "conversation", children: {...} }, ConversationPanel)`）。
- 侧栏的**浏览区域**是 `sidebar.workspaces`，当前由 `dsh-client-ui-workspace`（`WorkspaceBrowser`）独占，里面已经包含分组树、搜索、归档、重命名、fork、目录选择流程。用 `priority` 顶掉它会连带丢掉这些原生行为，因此**默认不改**；要还原设计稿的「项目 ▸ 任务」树，优先走「皮肤 + 原生树 + 独立主区域面板」，只有在确有结构化缺口时才评估整体接管。

## 已落地的部分（2026-09-15）

- 品牌：`extensions/ui/sumika-brand/lib/client.js` 用 `priority: -1` 接管 `sidebar.brand.mark` / `sidebar.brand.name`，侧栏显示「晴日部室」，官方品牌插件未被停用。
- 欢迎页品牌：同一个插件用 `priority: -1` 接管 `conversation.hero.brand.mark`（DSH 默认放自己的鱼形图标），改为「晴日部室」渐变方块；宿主传入的 `size`/`className` 原样使用，几何不被破坏。
- 侧栏底部状态：同一个插件注册 `sidebar.footer.action`（`id: sumika-status`），显示「本地优先 · 数据不出本机 / 运行数据 `.sumika-next/` · 已连接 DSH <release>」。版本号不是写死的，由宿主半边 `lib/index.js` 经 `webserver/index-inject` 发布 `window.__sumikaShell`，其值来自 `ensure_skin()` 读取的 `runtime/dsh/release.json`。
- 皮肤调色板：`extensions/ui/sumika-skin/dsh.mjs` 的令牌改为与设计稿 `:root` 一致（`--paper:#fffdf8`、`--paper-2:#faf8f0`、`--ink:#2f3a34`、`--line:#ddd9c8`、`--rose:#b4496a`、`--green:#567f6c`），并补上框架、侧栏列、新建会话按钮、会话行悬停/选中态、分节标题的结构覆盖。选择器使用语义后缀（`[class$='_sidebarCol']`）而不是整段哈希类名。
- 皮肤不再注入右下角「Sumika 皮肤」调试徽章；`html[data-sumika-skin='1']` 标记保留，供自动化判定。
- 折叠侧栏（轨道态）的悬停行为：上游规则 `.collapsed .toggle:hover .panelIcon{display:inline}` 与 `.collapsed .toggle:hover .railMark{display:none}` 会在鼠标悬停时把品牌标记换成 DSH 自己的面板图标，表现为「一悬停就变回原图标」。皮肤用更高优先级的选择器保持 `railMark` 可见、隐藏 `panelIcon`；验收脚本会在折叠态真实悬停后断言这一点。

验收脚本 `tools/verify_workbench_ui.mjs`（真实 Edge + 受管实例，非模拟）断言：无客户端报错、侧栏品牌文案、底部状态与 Harness 版本、框架/侧栏/按钮的实际计算颜色、皮肤令牌值；结果写入 `docs/project/workbench-ui-evidence.json`。

## 会话区域可用的槽（2026-09-15 枚举 `dsh-client-ui-conversation`）

会话区同样是可插拔的，除设计稿已用到的侧栏外还有：

| 槽 | 类型/作用域 | 用途 |
| --- | --- | --- |
| `conversation.hero.brand.mark` | single / root | 新会话欢迎页的品牌标记（已接管） |
| `conversation.hero.workspace`、`conversation.hero.agentPreset` | single / root | 欢迎页的工作区与 Agent 预设控件 |
| `conversation.session.header` | single / session | 整个会话头，可替换 |
| `conversation.session.header.lineage` | single / session | 面包屑标题（owner 给 `lineageSessionId` 与 `displayTitle`） |
| `conversation.session.header.actions`、`.utilities` | list / session | 标题右侧与最右侧的动作位；owner 不传值，占用者从标准会话 props 自行推导状态 |
| `conversation.session.header.corner` | single / session | 头部最右角，只有一个控件的位置 |
| `conversation.input.dock`、`conversation.input.left`、`.right`、`.plan`、`.model`、`.overlay`、`conversation.composer.bar` | list / session | 输入区各段 |
| `tool.title.*` | — | 各类工具卡的标题 |

设计稿工作台头部的「面包屑 + 任务标题 + 状态药丸」可以落在 `conversation.session.header.lineage` 与 `.utilities`；状态药丸的真实来源是 `conversationPhase(session, conversation)`（`blank` / `engaging` / `active`），不是自己推断的状态。

## 会话级槽位的运行时 props（2026-09-15 真实客户端探针实测）

会话区的槽位没有一个随发行版发布的类型包（`@deepseek-ai/dsh-client-ui-slots` 在安装里不存在，只有各插件在类型里 import 它），所以 props 只能实测。用一个临时诊断插件占位、把 props 形状写进 `data-` 属性，再由无头浏览器读取，得到会话级列表槽（以 `conversation.input.dock` 为样本）的真实签名：

| prop | 类型 | 说明 |
| --- | --- | --- |
| `sessionId` | string | 当前会话 id |
| `session` | object | `{sessionId, queue, pendingSubmissions, running, subagent, removed, openState, openError, hasMore, loadingOlder, promptError, blank, lastAgentError, promptAttempted, awaitingFirstTurn}` |
| `useSession`、`useSessions`、`useWorkspaces`、`useConversation`、`useChat`、`useTrajectory`、`useProjection`、`useResource`、`usePanelInfo`、`useInput`、`useSessionPendingInteraction` | function | 框架全局 selector hooks |
| `input`、`inputActions` | object | 仅占位输入区的槽位有（`draft`/`attachmentIds`/`draftRev`/`phase`/`occurrences`/`queue` 与 `setDraft`/`addAttachments`/`removeAttachment`/`pruneAttachments`/`submit`） |

结论与边界：

- 状态药丸可以只用真实信号：`session.running` → 「执行中」；`useSessionPendingInteraction((state) => state.get(sessionId)?.kind)` 取 `approval` / `plan-review` / `question`，对应原生侧栏行的「等待审批 / 计划审阅 / 等待回答」。**不要**照搬设计稿的「N 项待确认」计数——原生信号是单一种类的待交互，没有计数。
- 列表槽注册需要 `id`（与 `sidebar.footer.action` 一致），可参考同样写法的 `dsh-session-log-export`（`id: 'session-log-download'`，props 里读 `sessionId` 与自己的 `hooks`）。
- **会话头只在非空白会话挂载**：新会话视图走 hero（欢迎页），`conversation.session.header.*` 根本不渲染。因此头部药丸的落地必须在一个已有对话的会话里验证；本机受管 profile（`.sumika-next/daily/0.1.5-rc.2`）目前 `.credentials.yaml` 只有浏览器会话授权、没有模型凭据（网页也显示「添加一个 API Key 开始使用」），两个会话文件都是空白会话，所以这一项**暂缓到有非空白会话时再做**，不先写未验证的 UI。

### 会话头槽位的实测签名（2026-09-16，已用非空白会话复测）

用户在受管 profile 里填入 key 并发出一条真实消息后，头部槽位可以打开了。实测三个头部槽位的 props：

| 槽 | 实测 props |
| --- | --- |
| `conversation.session.header.utilities`（list） | `sessionId`、`inputActions`、`useSession`、`useSessions`、`useWorkspaces`、`useConversation`、`useChat`、`useTrajectory`、`useProjection`、`useResource`、`usePanelInfo`、`useInput`、`useSessionPendingInteraction` |
| `conversation.session.header.actions`（list） | 同上 |
| `conversation.session.header.lineage`（single，`priority: -1` 接管） | 追加 `lineageSessionId`、`displayTitle`（有祖先时才有 `openTitle`） |

注意：头部槽位**没有** `session` 快照（只有输入区槽位才有），状态必须从 hooks 取——`useSessions((state) => state.byId[id]?.running)` 与 `useSessionPendingInteraction((state) => state.get(id)?.kind)`。

## 会话状态药丸（2026-09-16 已落地）

新增独立插件 `extensions/ui/sumika-workbench/`（host 半边空实现，浏览器半边注册到 `conversation.session.header.utilities`，`id: 'sumika-session-status'`），由 `ensure_skin()` 登记进受管 profile 的补丁层。行为：

- `session.running` → 绿色药丸「执行中」（设计稿 `.pill-d.run`：`#567f6c` / `#e8f1ea` / `#c1d8c8` 边）。
- `useSessionPendingInteraction` 的 `approval` / `plan-review` / `question` → 琥珀色药丸「等待审批 / 计划审阅 / 等待回答」（设计稿 `.pill-d.wait`）。
- 其余情况只留一个零宽、带 `data-sumika-session-status="idle"` 的宿主元素，不占位、不显示文案；该属性同时是验收判定「已接线但空闲」与「没挂载」的依据。
- **没有**照搬设计稿的「N 项待确认」计数：原生的待交互信号是单一种类，没有计数。

验证：

- `node tools/verify_workbench_ui.mjs` 打开一个真实非空白会话，断言状态入口存在（`idle`）且无客户端报错。
- `node tools/verify_workbench_status_pill.mjs` 会新建一个会话、发出一条短消息并在轮次进行中采样头部；实测样本 `["idle", "running"]`，可见文案「执行中」，证据 `docs/project/workbench-status-pill-evidence.json`。脚本会消耗一次很小的模型调用，并把该会话留在工作区供人工查看。
- **未验证**：琥珀色待确认药丸尚未在真实审批/计划审阅/提问场景中出现过，只做了分支实现。

## 会话面包屑（2026-09-16 已落地）

`conversation.session.header.lineage` 不是「替换标题」，而是**追加**在原生标题后面的槽位：
真实 DOM 是 `nav.crumbs > span.crumbSeg > [button.crumbCurrent(原生标题), div[data-slot=…lineage]]`。
所以在这个槽里再渲染一遍会话标题会出现「问候语你好 Sumika / 工作台 / 问候语你好」这种重复。

`extensions/ui/sumika-workbench` 现在只用它补原生不显示的信息：从 `useWorkspaces` 快照里
找出包含当前会话的工作区，渲染成 `工作区 · <工作区名>`；当 shell 给了 `openTitle`
（当前是子会话）时再补一个「↑ 上级会话」链接。没有工作区可归属且没有父会话时直接返回
`null`，不占位。验收断言该槽位文本以 `工作区 · ` 开头且不含换行（换行说明标题又被重复渲染了）。

## 排查经验：槽位渲染崩溃只报 console

插件组件在渲染期间抛异常时，DSH 不会触发 `pageerror`，而是打一条
`slot entry crashed in '<槽名>': <错误>` 的 console error，并且该条目静默不渲染。
本次「面包屑一直不出现」就是这个原因（组件里漏了一个颜色常量）。
因此 `tools/verify_workbench_ui.mjs` 现在同时收集 `pageerror` 与 console error，
两者都会让验收失败；只监听 `pageerror` 会漏掉整类槽位故障。

诊断方法保留在 `.sumika-next/slot-probe/`（运行时目录，不入仓库）：`package.json` + `lib/index.js` + `lib/client.js` 是占位探针，`read.mjs`（读取占位报告）、`tree.mjs`（dump 侧栏树）、`stream.mjs`（列出实际下发的插件 id）、`rail_zoom.mjs`（折叠态放大截图）是读取脚本。再次需要时把 `{"id": "sumika-probe", "name": "<路径>\\lib\\index.js"}` 加回 `cordis.patch.yml` 并重启受管 DSH 即可。`/plugins/events` 是网页实际获取插件清单与 bundle 的通道，可用来确认某个插件是否真的被下发。

注意：`.sumika-next/probe/` 是 2026-09-12 遗留的一个空 DSH profile 脚手架（只有 `profiles/web`、`storages` 与一份浏览器会话授权），与本方案无关，未再使用；它属于本机运行数据，可自行删除。

```powershell
node tools/verify_workbench_ui.mjs http://127.0.0.1:8765 docs/project/workbench-ui-evidence.json
```

## 工作台那一屏就是 DSH 前端（2026-09-16）

用户要的是「点进工作台，这一屏本身就是 DSH 前端」，既不是跳走也不是新开标签页；先前实现过同标签页跳转（`window.location.assign`），用户明确否掉了。现在的做法：

- `ui/app/bind.js` 在 `#screen-board` 里放一个撑满该屏的 `iframe`（`#sumika-workbench-frame`），src 是受管实例的 token 化地址；壳的顶栏（晴日部室 + 活动室/工作台/能力/设置）继续留在上方，下方整块就是 DSH。
- 内嵌可行性是实测的：DSH 不返回 `X-Frame-Options` 或 CSP，token 化地址是 303 + `Set-Cookie`（`SameSite=Strict`，与壳同属 127.0.0.1，因此跨端口仍算 same-site），framing 正常，页面资源（`/assets/*`、`/plugins/*`）都在框架里加载成功。
- 设计稿的模拟工作台标记（`.wb-wrap` 里的时间线/审批卡）整体替换掉，不再和真实工作台叠在一起；`body.on-board` 时隐藏仍带示例台词的桌宠浮窗。
- 品牌插件在被框架加载时（`window.self !== window.top`）不再注册侧栏品牌槽，避免顶栏和侧栏出现两个「晴日部室」；侧栏底部保留「← 回 Sumika 活动室 / 能力 / 设置」，链接地址由 `ensure_skin(shell_url=...)` 从桥接端口注入，不写死。

验收：`node tools/verify_workbench_screen.mjs`（断言该屏为当前屏、frame 存在且高度 >400px、src 指向 5175、模拟标记已移除、桌宠不可见、确实向 5175 发过资源请求、无 pageerror 与 console error）。

## 把 Sumika 屏幕做成 DSH 主面板（2026-09-16，能力面板已落地）

用户接着问「是不是整个客户端都做成 DSH 前端」。这里先做了一个可运行的原型来回答，而不是先讨论：

- 机制：`ctx.slots.register({ name: 'main', key: 'sumika-capabilities', children: {} }, Panel)` 注册主区域面板，再用 `ctx.slots.register({ name: 'sidebar.panellist', id: 'sumika-capabilities', label: '能力', order: 10 }, Glyph)` 在侧栏加一行；点击该行调用 `ctx.layout.selectPanel(id)` 切换主区域。
- 数据：DSH 在 5175、桥接在 8765，属跨源。桥接新增**仅回显本机来源**的 CORS（`http://127.0.0.1[:port]`、`http://localhost[:port]`、`[::1]`）并补了 `OPTIONS` 预检，其它站点依旧读不到；面板直接调 `/api/modules`、`/api/readiness` 与 `/api/capabilities/toggle`。
- 结果：侧栏出现「能力」面板行，主区域渲染真实能力页（7 项可开关 + 4 项就绪视图），从面板点击开关真的写进注册表；`tools/verify_dsh_panel.mjs` 断言这些并会在结束前把开关恢复原值。

由此得到对各屏的成本判断：

| 屏幕 | 做成 DSH 面板 | 说明 |
| --- | --- | --- |
| 能力 | ✅ 已完成 | 列表 + 开关，纯 DOM 与 HTTP，最合适 |
| 设置 | 低成本 | 与能力同构；外观分区另需主题/密度落地 |
| 活动室 | 高成本 | 3D/VRM 渲染、语音输入输出、麦克风设备选择都要搬进 DSH 客户端插件，收益低于成本 |
| 横向顶栏导航 | 结构性缺口 | DSH 布局只暴露 `sidebar`/`main`/`rightbar`/`shell.overlay`/`root`，没有顶栏槽；要还原设计稿的横向导航得整体接管 `sidebar`，或自绘一个 `shell.overlay` 浮层 |

因此建议：**工作台保持现在这样（壳 + DSH 那一屏）**，能力与设置这类「列表 + 开关」的屏幕优先做成 DSH 面板，活动室继续留在壳里；等 DSH 提供顶栏槽或我们决定接管侧栏时，再把壳整体收进 DSH。

## 顶栏之下应当还原设计稿：DSH 的侧栏就是"项目 ▸ 任务"（2026-09-16 决定）

对照设计稿屏 2 可以确认：它本来就有**项目**这个概念——侧栏顶部是"搜索项目与任务…"，
下面是 `sumika-next（D:\Code\Sumika · 当前项目）` 这样的项目行，任务作为子项缩进，
还有"已归档 N"。所以设计稿要的树 = 项目 ▸ 任务。

在 DSH 里这套映射是天然的：**一个工作区 = 一个项目**（标题 + 路径 + 会话集合），
**一个会话 = 一个任务**（状态点 + 标题 + 相对时间 + 行菜单）。DSH 原生侧栏本来就在渲染
这棵树，只是文案与视觉还没对齐设计稿。

因此：

- 删除 `sumika-workbench` 里的两个面板行（`能力` 与 `项目`）与两个 `main` 面板。
  `能力` 与壳顶栏重复；`项目` 与工作区树重复——两处入口都违背"单一导航"。
  验收脚本 `tools/verify_dsh_panel.mjs` 改成**反向守卫**：DSH 侧栏出现任何 Sumika
  面板行即失败，同时断言工作区行存在（树还在）。
- 顶栏之下要按设计稿改，就是在**DSH 前端这一层**做：工作区行显示名称 + 路径 + 会话数，
  会话行显示状态点 + 标题 + "状态 · 时间"，侧栏顶部换成设计稿的搜索框样式，
  最后是页脚状态块（已实现）。这属于皮肤/客户端插件层的工作，不 fork DSH。
- 设计稿的时间线（消息气泡、工具卡、diff 行、终端结果行）、审批卡（4 个统计块 +
  确认执行/取消）与输入区同样是 DSH 原生组件，属于同一批"皮肤级贴近"任务。

## 待办

1. 时间线：会话内的 DSH 原生组件（conversation / tool / approval / deliverables）保留，皮肤只做令牌级调整；设计稿里的时间线版式逐屏对照后逐项补齐。
2. 会话头部：用 `conversation.session.header.lineage` + `.utilities` 落设计稿的面包屑、任务标题与状态药丸（状态取 `conversationPhase`）。
3. 侧栏「项目 ▸ 任务」：**结论已更新**——读 `dsh-client-ui-workspace` 的行组件后确认，原生会话行本来就渲染「状态点 + 标题 + 相对时间 + 行操作菜单」，整棵树还带搜索、分组/平铺切换、归档、重命名、fork、拖拽排序，信息量高于设计稿。整槽接管 `sidebar.workspaces` 会丢掉这些行为，是净损失；做**皮肤级**贴近（圆点、间距、时间文案）即可。Sumika 自己的「阶段/任务进度」属于另一个问题域，放在独立 `main` 面板 + `sidebar.panellist` 条目（数据接 `/api/tree`）。
4. 设置页：设计稿屏 4 的分区与开关（含 R-107/R-108 功能开关）按 `dsh-client-ui-settings*` 的分区插件注册方式接入。
5. 每次 DSH 升级后重跑 `tools/verify_workbench_ui.mjs`，并核对语义后缀类名是否仍存在。
