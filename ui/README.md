# Sumika Next UI

`prototype-d/` 是从 `D:\Code\Sumika-UI-Designs\direction-d-hiyori` 复制的独立原型快照，用于新版 UI 实现基线。原设计项目不被修改，设计目录中的 `node_modules`、脚本和工作记录不复制。

原型当前是静态 HTML/CSS/JavaScript，尚未连接 DSH、角色、记忆或桌面能力。后续实现按 D 方案的信息架构和视觉令牌逐步替换为真实数据；后端扩展仍通过独立适配层接入。

本目录只放 UI 原型和 UI 资产。运行数据、凭据和构建缓存不得写入这里。

D方案只是参考输入，不是完整需求或硬性实现清单。若设计与当前新版后端能力、DSH原生流程或用户已确认需求冲突，以后者为准；新增设计功能需要单独确认。

新版页面与后端通过 `ui/ui-contract.json` 和 `prototype-d/integration.js` 约束。页面只展示后端状态，不自行生成完成、授权或付费路由结论。

## 已实现：本地桥接与首个可交互页面

- `ui/server.py`：只绑定 `127.0.0.1` 的本地桥接。提供 `GET /api/state`、`GET /api/settings/role-model`、`PUT /api/settings/role-model`、`GET /api/modules`、`POST /api/role/chat`，并静态托管 `ui/` 下的页面与原型资源。
- `ui/app/`：按 D 方案信息架构（陪伴 / 工作台 / 能力 / 角色 / 设置）实现的第一版可交互页面。陪伴页从 `/api/roles` 读取名册、切换角色（绑定 `model_3d` 的角色走实机 VRM，其余显示立绘占位）、按角色独立会话对话框；能力页的开关写回 `/api/capabilities/toggle`；设置页读写角色模型设置并显示语言策略来源。
- `ui/vendor/sumika-vrm-viewer.js`：three.js + @pixiv/three-vrm 打包的 VRM 渲染器（MIT，字节级复制自设计项目，SHA-256 前缀见 `vendor/README.md`），导出 `mountVrmViewer(container, url, options)`。
- 边界：桥接不返回凭据；设置写入复用 `extensions/models/settings.py` 的校验，疑似密钥直接 400；角色对话关闭时不发请求；provider 失败返回 `unknown` 且 `fallback_used: false`。
- 角色资源按角色清单声明提供，未声明的资源类型返回 404；`/api/roles` 只返回资产类型标记，不回传绝对路径。

运行方式：

```powershell
# 角色模型密钥放在当前 shell 环境里，桥接进程继承；命令行与文件都不出现密钥
$env:DEEPSEEK_API_KEY = '<your-key>'
& tools/start_ui_bridge.ps1 -Port 8765
# 浏览器打开 http://127.0.0.1:8765/
```

验收证据见 `docs/project/ui-bridge-evidence.json`。

## 舞台渲染

房间背景由 CSS 图层绘制（墙面、窗与自然光、木地板、桌与矮柜），不再使用原型截图，避免出现“界面里嵌一张界面截图”。舞台固定 4:3，`mountVrmViewer` 的自动取景在这个比例下能完整显示角色；绑定 `model_3d` 的角色走实机 VRM，其余显示立绘占位。

自查方式（不需要人工开浏览器）：

```powershell
& tools/start_ui_bridge.ps1 -Port 8765
# 用本机 Edge 无头渲染并截图，检查 stage 尺寸、VRM 状态与控制台错误
```

最近一次自查：`vrm_render_status = running`、stage 740×555、控制台无错误，截图存于 `.sumika-next/ui-stage-check.png` 与 `ui-full-check.png`。

## 工作台（受管 DSH）

工作台页不再只显示占位状态，而是接入了受管 DSH 的真实生命周期：

- `GET /api/workbench`：返回安装状态、锁定版本、profile 目录、运行状态、原生 Web 地址和最近输出。
- `POST /api/workbench/start`：启动与 CLI 相同的受管入口（`python -m sumika_next.cli run --no-browser`），从子进程输出里解析 `DSH Web:` 地址。
- `POST /api/workbench/stop`：只停止桥接自己启动的那个进程树。
- 启动失败、超时未报告地址、未安装 `runtime/dsh` 都会以失败或 unknown 返回，不会伪造“运行中”。

真实启停验收（2026-09-15）：启动返回 `running: true`、`http://127.0.0.1:53895`、`pid 7000`；原生 Web 在未带浏览器凭据时返回 401（符合“干净 URL 需要已认证 cookie”的既有行为）；停止返回 `stopped: true` 后端口关闭、无残留 DSH 进程。
