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

## 仍未完成

设计稿屏 4「设置」与屏 3「能力」目前仍是原型行（硬编码的「8 已启用」等），
还没接到 `/api/readiness` 与 `/api/modules`；接线时开关必须直接调
`/api/capabilities/toggle`，并且区分「就绪但未登记」与「已登记已启用」两种状态，
不得把就绪视图当成开关状态显示。
