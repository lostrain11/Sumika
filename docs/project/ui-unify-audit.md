# 基线建立与审计（Phase 0）

- 建立日期：2026-09-20
- Git 起点：`73e4de7153468ff6f8659478e6e1413b2ff4987a`（`docs: record first setup draft release and verified assets`）
- 说明：执行前已有未提交改动（安装/个人数据管理相关：`ui/app/management.js`、`ui/management.py`、`ui/server.py`、`sumika_next/paths.py`、`packaging/*`、`tools/start_*.ps1`、`docs/project/*` 若干），本次全部原样保留，未 commit / revert / stash。

## 1. 运行环境（本机 Bash shim 异常，脚本调用方式已固化）

本机 Bash 的 `ls`/`head`/`tail`/`grep`/`cd`/`dirname` 均不可用（shim 报 `dirname: command not found`），因此：

- 不使用 `cd`，一律绝对路径调用。
- 不使用管道（`| tail` 会导致 `tail: command not found`），改用重定向到文件后用 Read 工具查看。
- Playwright 不在系统 node 的解析路径：实际位于 `C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/df473e5367fa2b42/bin/node_modules`。
- 验证脚本统一执行方式：

```bash
NODE_PATH="C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/OpenAI/Codex/runtimes/cua_node/df473e5367fa2b42/bin/node_modules" \
  "C:/Users/Lostrain.DESKTOP-43S7UNP/.workbuddy/binaries/node/versions/22.22.2-3/node.exe" \
  "D:/Code/Sumika/tools/<script>.mjs"
```

- 桥接启动方式（本机未用 `start_ui_bridge.ps1`，直接起服务）：

```bash
"D:/Tools/python/Python314/python.exe" -B -m ui.server --port 8765 \
  --settings "C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/role-model-settings.json" \
  --capabilities "C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/capabilities.db" \
  --schedules "C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/schedules"
```

## 2. 基线验证结果（改造前）

`tools/verify_ui_v2.mjs`（4 屏 × 3 视口 = 12 组合）：

- 布局裁切：**12/12 组合 `clipped: []`**，无溢出。
- 主题覆盖：`palette=light`、`--dsw-alias-bg-base=#fffdf8`、`--dsw-specific-sidebar-fill=#faf8f0`，皮肤生效。
- 错误：1 条 `Failed to load resource: the server responded with a status of 400 (Bad Request)`，**基线即存在**，需定位归属（见第 3 节）；未归因于本次改造。
- 截图：`.sumika-next/evidence/ui-v2/*.png`

> 结论：改造前基线为「布局不裁切 + 1 条既有 400」，后续改造以「不新增错误」为回归底线。

## 3. 基线 400 / 502 定位（已解决）

### 3.1 400：`GET /api/manage/personal-data` → `unknown management endpoint`

- 现象：基线运行报 1 条 `400 (Bad Request)`。
- 定位过程：`tools/probe_baseline_400.mjs` 捕获到真实响应（状态码+URL+方法+响应体），确认归属 `GET /api/manage/personal-data`；同域的 `/api/manage/session` 正常返回 200，说明模块已加载；源码中该分支存在（`ui/management.py:415`），路径切分也正确（`['api','manage','personal-data']`）。
- **根因：项目内 `ui/__pycache__/management.cpython-314.pyc` 时间戳（11:56）晚于源文件（03:57）**，Python 优先加载了旧字节码，导致未提交的新路由在运行进程中不可见。
- 处理：终止旧桥接进程 → 清除 `ui/__pycache__`、`tools/__pycache__` → 以 `-B` 重启桥接。验证 `GET /api/manage/personal-data` 返回 200 与真实目录。
- **对本项目的重要提示**：未提交改动在「源文件已改但 pyc 较新」时会被静默忽略。交接执行方遇到"改了不生效"时，先清 `__pycache__` 再重启，不要怀疑业务逻辑。

### 3.2 502：工作台屏 `#sumika-workbench-frame` 超时

- 现象：清缓存重启后，工作台屏报 `502 Bad Gateway` 且 frame 120s 等待超时。
- 原因：重启桥接时受管 DSH 一并退出（`/api/workbench` 报 `running:false`）。直接 `POST /api/workbench/start` 又被 CSRF 拦（403），带 token 后返回 `profile ownership unknown or already in use`。
- 定位：`tools/probe_profile_lease.py` 列出进程，发现**孤儿 DSH 进程**（PID 24236，`dsh lib/bin.js --port 5175`），其父进程 PID 7624 正是被停掉的旧桥接。桥接刻意不杀未归属进程（`ui/workbench.py:215-227` 的既有设计），故需人工处置。
- 处理：确认父子关系后 `taskkill /PID 24236 /F /T`，再经 `tools/start_workbench_via_bridge.py`（先取 CSRF token 再 POST）启动，成功 `running:true`、`url: http://127.0.0.1:50935`、`embed_ready:true`。

### 3.3 复跑结果（改造前最终基线）

`tools/verify_ui_v2.mjs`：**12/12 视口 `clipped: []`，`errors: []`，`status: passed`**；主题覆盖 `palette=light`、`--dsw-alias-bg-base=#fffdf8`。

> 回归底线：后续任何阶段不得让 `verify_ui_v2.mjs` 重新出现错误或裁切。

## 4. 字面色清单（232 hex + 44 rgb，2026-09-20）

工具：`tools/audit_color_literals.py`（自动排除 `:root` 与 `[data-theme]` 令牌定义块）；原始数据 `.sumika-next/baseline/color-inventory.json`。

| 文件 | hex（令牌外） | rgb/rgba |
| --- | --- | --- |
| `ui/app/index.html` | 211 | 43 |
| `ui/app/layout.css` | 1 | 1 |
| `ui/app/bind.js` | 20 | 0 |
| 合计 | **232** | **44** |

`index.html` 高频字面色（Top）：

| 次数 | 值 | 归类 |
| --- | --- | --- |
| 13 | `#fff` | 纯白（发送按钮前景、滑动块等）→ 需语义令牌 |
| 9 | `#e6c3cf` | 玫红描边（hover 边框）→ 令牌 `--rose-line` |
| 9 | `#cfdfea` | 水色描边 → `--mizu-line` |
| 8 | `#f4ecdc` | 预留卡图标底 → `--amber-soft-2` / 复用 `--amber-soft` |
| 7 | `#b3ab8f` | 弱化文字 → `--muted-2` |
| 6 | `#cfe0d4` | 绿描边 → `--green-line` |
| 6 | `#d9c49a` | 琥珀虚线 → `--amber-line` |
| 3 | `#a39e8b` / `#d8d2ba` / `#f0ecdd` | 预留/禁用态 → `--disabled-*` |
| 3 | `#c24e6e` | 旧版玫红（应统一到 `--rose:#b4496a`） |
| — | `#7a5c50`/`#8a6a5c`/`#a9c6d8`/`#ecd9a8`/`#e3b7c4`/`#a8c4b0` 等 | **立绘 SVG 角色材质色与房间陈设色：保留字面值**（不是主题色，令牌化反而有害） |

`bind.js`（20 hex）：`#fff` ×5 与一批状态色（`#b04a4a` 错误、`#47746a`/`#7fb1c9`/`#c9a24a` 角色强调色系等），需按真实语义映射到令牌或角色强调色来源。

**Phase 1 处理原则**：主题相关色 → 令牌；角色/陈设材质色 → 显式保留并在代码注释标明「材质色，不参与主题」。

## 5. 入口唯一性审计

| 功能 | 唯一权威入口 | 冗余项与结论 |
| --- | --- | --- |
| 页面导航 | 顶栏 `.gnav`（活动室/工作台/能力/设置） | **`.back-btn#backBtn`「← 回活动室」→ 确认移除**。证据：`grep backBtn` 命中仅 `ui/app/index.html:514,972,976`（自身定义与内联脚本）与只读原型 `ui/prototype-d/index.html`；`bind.js`、`tools/verify_*.mjs`、`extensions/ui/*` **零依赖**，可直接删除 HTML + 两行内联脚本，不影响任何验收断言。原型不改。 |
| 能力开关与详情 | 能力页卡片 + 右侧详情 | 设置页不得恢复能力分区（既有断言 `verify_ui_management.mjs`）——保持 |
| 语音/记忆配置 | 能力页「语音交互」「长期记忆」卡详情 | 设置页不重复（R-117）——保持 |
| 模型信息 | 顶栏 chip 只读状态 | 设置·模型与连接为「管理/跳转 DSH」，工作台内为 DSH 原生 chip。三处**信息同源但职责不同**（状态/管理/原生），保留，结论登记覆盖表 |
| 主题/背景 | 设置·外观 | 不得在活动室或顶栏新增第二切换——保持 |
| 转到工作台 | 活动室消息内按意图显示的按钮 | 不得恢复「所有消息都显示」——保持 |
| 桌宠快捷对话 | 桌宠小窗（活动室以外所有页面） | 与活动室对话栏同一会话数据源；定位=跨页陪伴入口，非冗余。工作台屏按 1.0-2 恢复显示 |
| 预留项表达 | 统一 `.is-reserved` + `.rsv-tag` | 当前四种写法（名册 `.member.rsv`、能力 `.cap-card.reserved`、设置 `.rsv-tag`、舞台 `.d-ctrl.rsv`）归一 |

## 6. 结论

- 基线健康：改造前 12/12 视口无裁切、0 错误，可比对。
- 两项环境级故障（pyc 陈旧、孤儿 DSH）已解决并记录成因，**不是代码缺陷**，但都会让"改了不生效"，需在交接文档显著提示。
- 字面色 232+44 处已建清单，Phase 1 有明确输入。
- 入口审计已完成，`#backBtn` 可安全移除。
