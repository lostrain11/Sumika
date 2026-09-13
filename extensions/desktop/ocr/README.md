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
