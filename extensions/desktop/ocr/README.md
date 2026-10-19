# OCR 与截屏翻译适配层

这是独立的、可替换 OCR 适配层，不修改 DSH，也不绑定具体 UI。它只负责把图片交给用户选择的 OCR provider，并输出结构化文字；翻译由后续 Harness/模型步骤完成，避免把某个云服务或密钥写死。

当前 `auto` 顺序为 Python RapidOCR → Tesseract → RapidOCR-json → Windows OCR；模块服务优先使用用户在能力登记中明确选定的实现，失败不会静默切换。Windows OCR复用伴学现有WinRT识别器及桌面运行时，无需另装RapidOCR。识别语言必须已在Windows安装；`eng`、`chi_sim`、`jpn`分别映射到对应Windows语言，其他语言标识直接传递。Windows路径限制图片文件20MiB、像素400万及系统原生边长上限，返回像素四角坐标、`score=null`。不自动下载模型或调用网络。

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
- 隔离环境入口：`SUMIKA_OCR_PYTHON` 可显式指定解释器，默认依次查找 `.sumika-next/ocr-env`、`.sumika-next/desktop-env`、`.sumika-next/office-env`；只有解释器和实际包同时存在才可用。
- 识别结果现在返回 `lines[{text, score, box}]`、`elapsed_ms`，供叠层定位与去重使用；`detect=False` 时 `box` 为 `null` 属于预期。

## 前端配置与文件识别（2026-10-18）

### 工作台一次性截图翻译

工作台启动时，`extensions/desktop/screenshot_skill.py`将现有模板`extensions/desktop/screenshot-skill.md`发布到受管DSH profile的默认Skill目录；通过原生filesystem provider发现，不新增页面或插件。已运行的工作台需在空闲时停止并重新启动才能登记新Skill，不自动重启用户会话。同名用户Skill不会覆盖；路径按实际安装位置与当前能力数据库生成。

使用步骤：在「能力」启用「OCR / 截屏翻译」，必要时按下文选择已安装实现；进入「工作台」的现有项目/会话，提供图片附件或明确文件绝对路径，输入“使用 sumika-screenshot-translation 将这张截图翻译为简体中文，先列原文及识别不确定处”。DSH依原生权限执行模块服务，当前工作模型在同一对话给出原文与译文。附件必须已能作为本地文件访问；否则先提供文件路径。

此流程不采集屏幕、不后台监控、不生成游戏叠层；不另行调用角色模型或网站。当前工作模型若是云端，识别文字也会作为任务上下文发送到该工作模型。OCR禁用、依赖缺失或语言未安装时明确停止，由用户在现有配置入口处理，不绕过能力登记或静默切换实现。图片文字仅作不可信文档内容，不作为工具指令或用户记忆。

维护验证：`python -X utf8 -B tools/verify_screenshot_skill.py --product <候选目录> --repair-fixture-acl --output <证据目录>`。仅生成测试图片、启动隔离DSH并走真实OCR；loopback模型夹具验证原文进入上下文，不能证明实际模型的翻译质量。

进入「能力 → 管理模块」，找到 `ocr`，在「实现」选择 `windows` 或其他已检测实现，点击「应用实现」。选择实现不会开启原先禁用的模块；同实现保留选项，跨实现使用新实现的选项，刷新后选择保留。能力开关仍由已有能力详情控制。此路径只配置实现，不开始截屏或设备采集。

工作台提供图片文件路径后，可通过原生终端调用模块服务（遵循原生执行权限）：

```powershell
python -X utf8 -B -m extensions.desktop.service --store <当前能力SQLite绝对路径> --request <请求JSON绝对路径>
```

请求格式：`{"capability":"ocr","operation":"recognize","arguments":{"image":"<图片绝对路径>","language":"chi_sim"}}`。解释器须使用当前产品Bridge运行时；不能把示例里的数据库路径当成固定用户路径。调用前须已登记并启用OCR。当前没有独立图片上传识别按钮；实时翻译叠层仍未完成，不把配置入口等同于完整翻译功能。

维护验证：`python -X utf8 -B tools/verify_windows_file_ocr.py --output <证据目录> [--product <候选目录>]`生成中英图片、走真实模块服务，检查文本/坐标及禁用、语言缺失、像素预算拒绝，不截取用户屏幕。`node tools/verify_ocr_provider_ui.mjs <证据目录>`验证真实Bridge的既有选择器与保存刷新；候选通过 `SUMIKA_TEST_CANDIDATE`/`SUMIKA_TEST_PYTHON`指定。
