# 游戏实时中文翻译：长期计划（F-002）

用户原文：先完善定时任务。另外问问，实时挂载Sumika，翻译游戏内UI和文本的功能你打算怎么实现？别人是如何实现的，可否参考？我想做一个玩能实时翻译不自带简中的游戏的功能，应该能支持简单游戏的游戏内文本替换，和复杂游戏的原文本下翻译显示

状态：deferred。用户最新指令：“加入长期计划，先不做”。保留需求、两种显示模式与开源参考，暂不实施游戏挂载、实时翻译或叠层；不列入当前 P5/P6 完成门槛。普通 OCR/截屏翻译原范围不变。没有向游戏安装或注入代码。

## 两条呈现路线

1. 引擎支持时，复用文本接口/插件把译文写回文本控件，保留可撤销配置。适用于部分 Unity、视觉小说、RPG 引擎；中文字体、编码、换行、控制符与动态变量必须保留。不能仅按“简单游戏”判断能否替换。文本在贴图里仍需 OCR 或资源替换。
2. 通用路线：选择游戏窗口→捕获窗口帧→变化/稳定检测→OCR 文本框→翻译→透明点击穿透叠层，在原文下方显示译文。跟随窗口移动、DPI、分辨率；避免采集译文叠层造成识别循环。独占全屏可能需要切无边框窗口，并不保证一套采集适用于所有渲染器。

共同独立核心：标准化文本片段（游戏ID、位置、文本、上下文、版本）、翻译 provider、术语表/角色名、缓存与去重、过期结果丢弃。引擎适配器与窗口采集适配器独立于 Harness，DSH 不进入每帧循环。

短 UI 字符串先做精确缓存；剧情按稳定句子、说话人和有限历史翻译。缓存键包含游戏、语言、provider/模型、术语表版本与原文。首次翻译异步显示，不承诺零延迟；慢结果不得覆盖已换页文本。未预先同意的云服务不自动启用，支持离线 provider。暂不锁定最佳翻译引擎，需要用真实游戏句子比较准确率、延迟和资源占用。

## 核对过的现成项目

- [LunaTranslator README](https://github.com/HIllya51/LunaTranslator/blob/main/.github/README.md)：HOOK、OCR、内嵌翻译、多个在线/离线翻译接口。GPLv3，直接整合/分发代码需遵循其许可。
- [Luna 内嵌文档](https://docs.lunatranslator.org/zh/embedtranslate.html)：并非所有游戏支持；部分引擎在显示文本前截获并替换，需要字体/编码处理，等待翻译可能卡顿，可设等待上限。
- [Luna OCR 窗口绑定](https://docs.lunatranslator.org/zh/gooduse/gooduseocr.html)与[变化检测](https://docs.lunatranslator.org/zh/ocrparam.html)：只抓游戏窗口、OCR区域随窗口移动；先判断画面稳定，再判断是否变化；文本编辑距离减少重复翻译。优先参考这些行为。
- [XUnity.AutoTranslator](https://github.com/bbepis/XUnity.AutoTranslator)：Unity 文本插件，支持 BepInEx/MelonLoader 等集成方式、文本翻译缓存与纹理翻译。不表示所有 Unity 游戏和文本框架均可用。
- [Textractor](https://github.com/Artikash/Textractor)：Windows 视觉小说文本 hook，经管道输出提取文本。提取文本不等同于通用原位替换。

建议先完成通用窗口 OCR 双语显示，再用 XUnity/Luna 已支持引擎扩展原位替换。有反作弊的联网游戏默认只走外部采集/叠层，并遵守游戏限制；不做任意进程内存改写。用户实际游戏清单将决定首批引擎适配与验收样本。

## 当前缺口

现有 RapidOCR 封装仅返回合并文本，不保留 box/confidence；translation.py 只是回调，不是实时系统。仍需 OCR 框坐标、窗口捕获排除叠层、文本跟踪、翻译引擎实装、字幕布局、停止/恢复与真实游戏验收。透明叠层由 UI 阶段实现，核心队列/去重/缓存可先做。

## 2026-09-15 更新：引擎选型与实时路径已实测

- 选型：默认 **RapidOCR（PP-OCR，ONNX Runtime）**，Apache-2.0、CPU 可跑、模型小；Tesseract 与 Umi-OCR 的 `RapidOCR-json.exe` 保留为备用 provider。
- 已完成：OCR 适配层返回 `lines[{text, score, box}]` 与 `elapsed_ms`；支持复用引擎与 `detect=False`；隔离环境解释器可显式指定。
- 实测（同一台机器，中文网页面板与日文游戏字幕）：整帧 880 ms、裁剪 440 ms、**跳过检测 59 ms**，三者识别结果一致。瓶颈在检测模型，因此实时路径为“一次检测定位 + 逐帧只识别”。
- 仍未完成：窗口捕获与排除叠层、变化/稳定检测、文本跟踪与去重、翻译 provider 实装、叠层显示与停止恢复、真实游戏验收。这些属于 F-002 长期计划，未因本次测量而提前实施。

## 2026-09-15 更新：跟踪/去重/过期丢弃核心已实现

`extensions/desktop/translation_pipeline.py` 提供与采集、翻译引擎都解耦的共同核心：

- `TextTracker.observe(lines)`：同一句必须连续出现 `stable_frames` 帧才产生一次翻译请求；相同文本不再重复请求；每帧都会把已缓存译文以 `status="cached"` 返回，供叠层重绘。
- 变化即换行：文本改变时旧条目进入 `gone`，对应未完成的请求立即作废；迟到的译文 `accept()` 会返回 `accepted: false`，并**不写入缓存**，因此不会覆盖新台词。
- `TranslationCache`：缓存键包含区域、文本、目标语言、provider 与术语表版本；不同区域即使文本相同也各自翻译；缓存有上限并按最近最少使用淘汰。
- 文本归一化忽略空白与换行差异，但不忽略内容差异（「危険」与「危険だ」是两条）。

自动化测试 `tests_next/test_translation_pipeline.py` 覆盖以上行为。仍未完成：真实窗口采集与排除叠层、翻译 provider 实装、叠层绘制与停止恢复、真实游戏验收。

## 2026-09-15 更新：窗口采集与叠层排除核心已实现

`extensions/desktop/capture.py`：

- `resolve_window(标题片段, 窗口清单)`：只认可见窗口；0 个匹配返回 `not_found`，多于 1 个返回 `ambiguous` 并列出候选，句柄或矩形非法返回 `invalid_window`——一律失败关闭，不猜。
- `plan_capture(window, overlay)`：**只抓目标窗口自己的矩形，不抓整屏**，因此叠层作为独立顶层窗口不会进入识别范围；若叠层矩形与目标窗口重叠，返回 warning，提示叠层需要用透明/点击穿透方式实现并复核。
- `frame_is_usable((mean, stddev))`：黑屏或低对比度帧在进入 OCR 之前就被判为不可用，返回 unknown 而不是把噪声当台词；独占全屏常见的抓取失效因此不会被误报成识别结果。
- `grab_window(rect, output)`：只写一个新文件，拒绝覆盖；实际抓取依赖桌面扩展环境。

自动化测试 `tests_next/test_capture.py` 覆盖唯一匹配、不可见窗口、歧义、非法句柄、小于最小尺寸、叠层重叠告警、黑屏/低对比度拒绝、拒绝覆盖。仍未完成：与 OCR/跟踪串成完整循环、叠层绘制窗口、翻译 provider 实装与真实游戏验收。
