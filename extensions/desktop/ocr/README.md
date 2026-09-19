# OCR 与截屏翻译适配层

这是独立的、可替换 OCR 适配层，不修改 DSH，也不绑定具体 UI。它只负责把图片交给用户选择的 OCR provider，并输出结构化文字；翻译由后续 Harness/模型步骤完成，避免把某个云服务或密钥写死。

当前首选是已有的 Umi-OCR RapidOCR-json provider（RapidOCR，Apache-2.0 组件），其次探测本机 `tesseract`，最后才是 Python 环境中的 RapidOCR。已有 provider 的路径可用 `SUMIKA_RAPIDOCR_JSON` 覆盖。provider 都不存在时安全失败；不会自动下载模型、调用网络或伪造识别结果。

```powershell
python -X utf8 -B ocr.py status
python -X utf8 -B ocr.py recognize screenshot.png --provider auto
```

输出为 JSON，包含 provider、文本和是否需要翻译。截图由调用方按 Harness 权限提供；本层不截取屏幕、不控制窗口。

## 三种使用方式的边界

1. **辅助操作/验证**：截图采集器将当前窗口或游戏区域保存为图片，OCR 返回文字和后续视觉定位输入；真正的点击、输入、快捷键仍由独立桌面控制层执行，并必须经过 Harness 的原生授权。
2. **判断正在做什么**：OCR 只能提供文字证据，不能单独判断“正在打游戏/看视频”。需要窗口标题、进程、图像/视频帧分类和节流策略；这些信号应标注来源和置信度，不把推测写成事实。
3. **非中文游戏实时翻译**：按变化区域采样，去重和稳定若干帧后再 OCR，翻译只发送新文本；显示层保留原文、译文和时间戳。不要每帧请求模型，也不要把游戏输入自动化与翻译权限混在一起。

开源项目通常组合这些部件，而不是由 OCR 单独完成“陪玩”：桌面宠物项目（例如 [Neko](https://github.com/CaffeineLiqueur/Neko)）主要提供透明窗口、快捷键和对话，并没有屏幕理解或游戏控制；[Project Aegis](https://github.com/ninja-otaku/Project_Aegis) 的仓库描述采用独立设备截图加视觉模型分析，更接近“看屏幕并评论”，不是可靠的本地游戏操控框架。真正的游戏 Agent 通常还需要帧采集、视觉模型、状态记忆、动作策略、输入注入和安全停止，每个游戏要单独验证。
## 实时翻译相关的实测结论（2026-09-15）

引擎选型：**RapidOCR（PP-OCR 系列，ONNX Runtime）**作为默认 provider。理由：中文/日文识别可用、Apache-2.0、CPU 即可运行、模型小（几十 MB）、可用 DirectML 走非 N 卡 GPU；Tesseract 保留为备用，Umi-OCR 自带的 `RapidOCR-json.exe` 作为外部 provider。

同一台机器上对三类目标的真实测量（`tools/verify_ocr_realtime.py`，隔离环境 office-env）：

| 用例 | 是否跑检测 | 中位耗时 | 结果 |
| --- | --- | --- | --- |
| 游戏字幕整帧 1280×160 | 是 | 880 ms | 识别出「危険」「準備」 |
| 网页面板 900×320 | 是 | 422 ms | 识别出「设置」「角色模型」「简体中文」 |
| 游戏字幕裁剪到文本带 | 是 | 440 ms | 同上 |
| 同一裁剪区域，`detect=False` | 否 | **59 ms** | 同上，置信度 0.99997 |

结论：**延迟主要来自检测模型**，不是识别模型。实时路径应当是“首次用检测定位文本区域 → 之后只对已知区域做 `detect=False` 识别”，这样每帧约 60 ms，并且因为区域是自己裁剪的，`box` 缺失也不影响在原文下方绘制译文。

其他实测要点：

- 引擎必须复用。每次调用都重新构造 `RapidOCR()` 会重新加载 ONNX 模型，字幕用例从 1430 ms 降到 889 ms 就是缓存的差别。
- 隔离环境入口：`SUMIKA_OCR_PYTHON` 可显式指定解释器，默认依次查找 `.sumika-next/ocr-env`、`.sumika-next/office-env`。
- 识别结果现在返回 `lines[{text, score, box}]`、`elapsed_ms`，供叠层定位与去重使用；`detect=False` 时 `box` 为 `null` 属于预期。
