# sumika-skin · 工作台皮肤分工说明

> 本文件说明「谁负责什么」，避免后续改动把职责混在一起——过去在这里加过界面入口，与外壳顶栏重复，已回退。

## 1. 这个插件是什么

`sumika-skin` 是**宿主面插件**：它不修改 DSH 源码、安装包或 `node_modules`，只通过官方扩展点把自己的样式与一小段脚本注入到 Harness 已经渲染的页面里。

两个文件，两条通道：

| 文件 | 运行位置 | 作用 |
| --- | --- | --- |
| `dsh.mjs` | 宿主面（Node 侧） | 导出 `name` 与 `apply(ctx, config)`。通过 `ctx.on('webserver/index-inject', …)` 往首页注入一个 `<style>`（`SKIN_STYLE`）和一段经典脚本（`SKIN_SCRIPT`） |
| `client.js` | 浏览器侧 | 用 `window.__ModuleLoader__.load({id:'sumika-skin', …})` 注册的公开主题扩展；`inject: ['theme']`。负责侧栏几何、DSH 别名令牌覆盖、主题偏好同步 |

## 2. 启用方式与闸门

- `apply()` 第一行即 `if (config.enabled !== true) return;`——**配置未显式开启时插件完全惰性**，不注入任何东西。
- 注入的脚本会在 `<html>` 上打 `data-sumika-skin='1'` 并直接返回（幂等，重复注入无副作用）。
- 所有样式选择器都以 `html[data-sumika-skin='1']` 开头，所以**皮肤只在这个标记存在时生效**；`client.js` 同样先检查该标记，否则 `return`。
- 关闭皮肤只需不注入该标记，样式与令牌覆盖随之失效，不残留。

## 3. 职责边界（关键）

**DSH 拥有结构，皮肤只拥有外观。**

皮肤**可以**做的事：

1. **令牌覆盖**：把 DSH 的别名令牌映射到 Sumika 配色。
2. **表层与圆角**：页面底色、面板底、描边色、滚动条、代码块底色、各类圆角。
3. **侧栏几何**：折叠按钮的位置与尺寸、新建会话按钮的宽度与边距、折叠态下的排布。
4. **演示词汇替换**：「工作区」→「项目」等纯展示文案（`SKIN_SCRIPT` 的 `labels` 映射）。

皮肤**不可以**做的事：

- 不改 DSH 的 DOM 结构、不新增功能入口、不新增导航或面板。
  > 原因：这里曾经加过「能力」入口与「项目」面板，与外壳顶栏/工作区树重复，用户明确要求回退。同一能力只能有一个入口。
- 不隐藏 DSH 原生功能。设计稿没画到的东西不等于该删——会话轨迹、用量与用时、系统提示词、模型选择、复制/反馈、侧栏折叠等一律保留，只做样式贴近。
- 不碰会话正文、草稿、数据 ID、工具输出。`SKIN_SCRIPT` 的替换逻辑显式跳过 `textarea/input/contenteditable/pre/code`。
- 不写死 DSH 的 CSS Module 哈希类名。

## 4. 选择器策略：为什么用「语义后缀」

DSH 的样式类名带 CSS Module 哈希，例如 `pI_x6G_frame`。哈希会随版本变化，直接写死必然失效。因此皮肤统一锚定**稳定语义后缀**：

```css
html[data-sumika-skin='1'] [class$='_frame'],
html[data-sumika-skin='1'] [class*='_frame '] { … }
```

`$=` 命中结尾、`*=` 命中后接空格的形式，两种写法同时给出以免漏掉带额外类名的情况。

已知的锚点（改动前先确认 DSH 仍在用这些后缀）：`_frame`、`_centerCol`、`_logoRow`、`_toggle`、`_brand`、`_newSession`、`_sidebarCol`、`_collapsed`、`_panelIcon`、`_railMark`、`_headline`。

## 5. 令牌映射：为什么只映射了一部分

DSH 对外暴露的是 **37 个窄义自定义属性，没有通用调色板**。所以皮肤只映射确实存在的那批，不臆造：

- 别名层：`--dsw-alias-bg-base`、`--dsw-alias-bg-layer-1/2`、`--dsw-alias-bg-overlay`、`--dsw-alias-border-l1/l2`、`--dsw-alias-brand-primary`、`--dsw-alias-label-primary/secondary`、`--dsw-alias-state-success/warn/error-primary`
- 具体面：`--dsw-specific-sidebar-fill`、`--dsw-elevation-stroke-color`、`--dsw-hovercard-bg`、`--dsw-scrollbar-thumb*`、`--dsh-file-type-default-color`
- 圆角与代码面：`--dsl-web-radius`、`--dsl-diff-radius`、`--dsl-read-radius`、`--dsl-search-radius`、`--dsl-terminal-radius`、`--dsl-code-block-background`、`--dsl-code-block-banner-background-color`
- 启动态：`--dsh-boot-bg`、`--dsh-boot-brand`、`--dsh-state-ongoing`

皮肤自己的词汇板前缀是 `--sumika-*`（`--sumika-paper`、`--sumika-ink`、`--sumika-rose` …），取值对齐设计稿 `direction-d-hiyori/index.html` 的 `:root`，**不要去别处重新推导一套配色**。

## 6. 明暗主题：只覆盖浅色，这是有意的

```js
const tokens = Object.fromEntries(Object.entries(palette)
  .map(([key, value]) => [key, {light: value, dark: value}]));
```

`client.js` 仅在 **light** 时 `ctx.theme.overrideTokens('sumika-skin', tokens)`；切到 dark 时立即 `dispose()`，把控制权交回 DSH 原生主题。

理由：与其发明一套未经评审的暗色 DSH 配色去覆盖原生实现，不如让暗色跟随 DSH。**这是刻意取舍，不是遗漏**——若要自绘暗色，必须先出方案让用户确认，并补齐暗色态验收。

## 7. 主题同步协议（外壳 ⇄ 工作台）

外壳 `ui/app/theme.js` 与皮肤 `client.js` 通过 `postMessage` 同步主题，两端都做**来源与 origin 校验**：

| 消息 | 方向 | 含义 |
| --- | --- | --- |
| `sumika:theme-ready` | 工作台 → 外壳 | 工作台首次就绪，附带当前偏好 |
| `sumika:theme-state` | 工作台 → 外壳 | 工作台主题发生变化 |
| `sumika:theme-set` | 外壳 → 工作台 | 外壳要求切换主题 |

校验：`event.source === window.parent`（或 frame 的 `contentWindow`）且 `event.origin === 'http://127.0.0.1:8765'`，不满足即忽略。

> **注意（实测发现）**：因为存在这条回传，在外壳里打开工作台后，外壳主题会**跟随工作台**。做主题相关验收时必须逐次重申期望主题，否则会把「跟随」误判为「主题没生效」——这正是 `tools/verify_ui_matrix.mjs` 对工作台页单独处理主题断言的原因。

## 8. 相关验收脚本

| 脚本 | 覆盖内容 |
| --- | --- |
| `tools/verify_workbench_ui.mjs` | 工作台屏整体外观与接线 |
| `tools/verify_workbench_screen.mjs` | 工作台屏装载与桌宠显示状态 |
| `tools/verify_sidebar_geometry.mjs` | 侧栏几何（折叠/展开两态） |
| `tools/verify_dsh_panel.mjs` | **断言 DSH 侧栏不得出现任何 Sumika 面板行**（防止职责越界重演） |
| `tools/verify_workbench_status_pill.mjs` | 会话头状态药丸 |
| `tools/verify_ui_native_history.mjs` | 原生会话轨迹页 |
| `tools/verify_ui_matrix.mjs` | 8 分辨率 × 2 缩放 × 2 主题矩阵（含工作台屏） |

改动本插件后至少运行：`verify_dsh_panel.mjs`、`verify_sidebar_geometry.mjs`、`verify_workbench_ui.mjs`、`verify_ui_matrix.mjs`。
