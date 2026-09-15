# 能力注册表与开关（2026-09-16）

## 为什么要有这张表

`extensions/desktop/service.py` 是所有设备/桌面粉能力的执行入口，它通过
`CapabilityStore.resolve(capability)` 取 provider 与参数：没登记的 capability 直接
`capability not configured`，被停用的直接 `PermissionError: capability disabled`。
所以「设置里给每个扩展做开关」不是加一个 UI 控件就够——注册表里必须有真实条目，
开关才能真的控制行为。

现状（本轮之前）：注册表文件 `%LOCALAPPDATA%\Sumika\capabilities.db` 在这台机器上
根本不存在，只有测试里手工 `configure()`，因此 OCR、桌面控制、语音、摄像头、
麦克风、办公渲染这些能力都处于「代码在、但运行时拒绝执行」的状态。

## 首次/增量播种

- `ui/readiness.service_capabilities()` 用与就绪探针**同一套依赖检查**推导出这台机器
  真正能服务的能力，返回 `{id, provider, enabled, options}`；依赖缺失的能力**不登记**，
  而不是登记一个调用时才失败的 provider。
- `Bridge.capability_bootstrap()` 在桥接启动时运行，**只补缺**：未登记的 id 追加，
  已存在的条目保留用户选的 provider、options 与 enabled，不覆盖、不删除。
  因此用户关掉某项后再启动，不会被重新打开。
- 需要参数的 provider 由播种直接带上：Vosk 的 `model` 目录、LibreOffice 的
  `executable` 路径。

| capability | provider | options | 依赖 |
| --- | --- | --- | --- |
| `ocr` | `rapidocr` / `rapidocr_json` / `tesseract` | — | 取第一个可用者：隔离环境里的 RapidOCR、Umi-OCR 的 RapidOCR-json、tesseract 可执行 |
| `desktop` | `windows-uia` | — | Windows 且隔离环境同时有 pywinauto 与 pywinctl |
| `voice` | `windows-sapi` | — | Windows 且隔离环境有 pywin32/comtypes |
| `asr` | `vosk` | `model` | vosk 模块与可用的语音模型目录 |
| `camera` | `opencv` | — | cv2 |
| `microphone` | `sounddevice` | — | sounddevice |
| `office-render` | `libreoffice` | `executable` | `SUMIKA_SOFFICE`、PATH 或常见安装路径（含 `D:\Tools\LibreOffice\*\program\soffice.exe`） |

播种默认全部 `enabled: true`：探针报告「就绪」的能力与用户此前的预期一致，
开关随后可逐项关闭；关闭后 `resolve()` 立即拒绝，执行入口不会静默换 provider。

## 接口

- `GET /api/modules`：注册表条目 + 显示用 `label` / `purpose`（`ui/server.py` 的
  `CAPABILITY_LABELS`，未知 id 原样显示，不描述为可用）。
- `POST /api/capabilities/toggle {id, enabled}`：写 enabled，其余字段保持。
- `GET /api/readiness`：与注册表互补的**就绪视图**（含未被服务使用的项，例如
  `browser`、`memory-semantic`、`schedule`、`office`）。两者不要互相替代。

## 验收

```powershell
# PIL 在办公隔离环境里，因此用该解释器运行
& .sumika-next\office-env\Scripts\python.exe -B tools\verify_capability_registry.py `
    --store "$env:LOCALAPPDATA\Sumika\capabilities.db"
```

脚本在**本机真实数据库**上做四件事，证据写 `docs/project/capability-registry-evidence.json`：

1. 可服务能力集合与已登记集合一致（缺项直接失败）；
2. 开关经桥接 API 往返，落库状态被读回确认；
3. 停用后调用 `extensions.desktop.service` 必须被拒绝（退出码 2 且 stderr 含 disabled）；
4. 重新启用后经同一入口真实跑通 OCR（生成图片，**不截屏**），并校验识别文本内容，
   只要求内容不要求换行顺序——RapidOCR 会把同一行拆成两行。

脚本在结束时把被改动的那一项 enabled 恢复原值，不改变用户配置。

## 界面接线（2026-09-16）

屏 3「能力」与屏 4「设置」已接到真实接口（`ui/app/bind.js`）：

- 屏 3 分三组：**扩展模块（可开关）** 来自 `/api/modules`，每张卡带真实开关；
  **就绪视图（无独立开关）** 来自 `/api/readiness` 减去已登记的 id；
  **DSH 原生** 是静态说明卡，明确写「不由 Sumika 开关」。
  「就绪」与「已启用」分列显示，不互相代替。
- 点选卡片会把右侧详情栏换成该项的真实值（状态、注册表 provider、权限口径），
  右侧「启用状态」格子的三个数字也来自真实统计，不再是 8/8/0。
- 屏 4 的「能力模块」区每行一个真实开关，总览行显示 `${已启用} 已启用 · ${已停用} 已停用 · ${不可用} 不可用`。
- 「模型与连接」里：角色模型读 `/api/state`（真实模型名与启用状态）；
  工作模型与 API 凭据改为「由 DSH 工作台管理」并给一个打开入口，不再复述未经核实的模型名；
  API 凭据的说明文字改成「由 DSH 保存于本机 profile，不上传、不进 Git」——DSH 的
  `profile/.credentials.yaml` 实际是明文，原文案「本地加密保存」不成立。
- 「连续记录 · 自动捕获」注明属于 DSH 侧插件、开关在 DSH 自己的插件清单里，
  因此这里不提供一个不生效的开关。
- 尚未接线的分区（外观、数据与存储等）统一加「原型 · 未接入」标签并禁用其按钮，
  同时删除两处从未真实存在的示例值（示例检查点哈希、MCP 授权计数）。

验收：

```powershell
node tools/verify_capability_ui.mjs http://127.0.0.1:8765 `
    docs/project/capability-ui-evidence.json
```

真实 Edge 驱动：打开能力页后逐项比对每个开关的 `aria-checked` 与 `/api/modules`；
**从 DOM 点击一个开关**并轮询注册表确认后端真的改变，再点回去确认恢复；
切到设置页核对总览数字与开关数量；最后断言占位分区已标记且其按钮全部 disabled、
示例哈希与「项已授权」计数不再出现。证据 `docs/project/capability-ui-evidence.json`。
