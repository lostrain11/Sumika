# P6 现场探测（2026-10-19）

范围：笔记本推理节点、真实公开 B 站视频、本机真实摄像头/麦克风与真实 PDF 阅读。所有模型调用为合成夹具；B 站测试匿名、静音播放、独立数据目录，不读取用户浏览器资料。摄像头/麦克风在用户一次性授权后执行，元数据记录、原始帧/音频不保留。

## 笔记本节点

- 现场原有服务：8082（Qwen 4B，n_params 4,022,468,096，n_ctx 2048）、8083（MiniCPM-V 1B，multimodal）、8085、11434、SSH 22 在线；8084 原先未监听。
- 本轮临时按既有参数启动 8084（PID 556，`F:\GGUF\LFM2.5-24B-A2B-Q4_K_M.gguf`，`-ngl 99 --n-cpu-moe 99 -c 4096 --jinja --reasoning-budget 0`）。`/health` 约 75 秒后就绪；`/v1/models` 返回 `n_params 23,971,587,712`、`n_ctx 4096`、`Q4_K - Medium`，与用户选定主力一致。
- 测试结束后已停止 PID 556；复测 8082/8083 仍在线、8084 恢复未监听。未修改开机任务、共享服务或日用配置。
- 冷/热边界：首个请求 TTFT 172.657 秒、总 186.665 秒（健康返回后仍有明显冷读/加载）；其余 18 例中位 6.71 秒，最短 4.037 秒。不能把 `/health ok` 当作已热。

## 模型质量（合成夹具）

工具：`python -X utf8 -B tools/evaluate_lan_daily.py --endpoint http://192.168.31.227:8084/v1 --model LFM2.5-24B-A2B-Q4_K_M.gguf --suite all --thinking off --structured --max-tokens 1000`，19 例全部非空、`finish_reason=stop`。

- 严格结构化 6 例中通过 4 例：`scene_game`、`scene_unknown`、`intent_discussion`、`injection`。
- 未通过：`scene_study` 把教学视频判为 `unknown`；`extract` 把“周六”输出为 `Saturday`（字段语义不一致）。
- 角色 7 例中：`rp_recall` 正文残留 `</think>` 并重复整段；`rp_fresh` 新会话把用户名字说成“你叫澄”（身份混淆）。其余 5 例未见越权/编造删除，但仍是短合成历史，不证明长期角色质量。
- 证据：`.sumika-next/acceptance-20261019/lfm-8084-daily.json`。
- 结论：条件可用；长期角色、完整卡、否定/权限/预算和长上下文质量仍未通过。8084 当前已停，不据此声称日用模型已在线。

## 真实 B 站

命令：`node tools/verify_companion_extension_soak.mjs .sumika-next/acceptance-20261019/bilibili-live-40s --seconds 40 --live-url https://www.bilibili.com/video/BV1QN4y1c7RQ/ --vosk-model E:/Models/Speech/sumika/vosk-model-small-cn-0.22`。

- 生产 MV3 扩展 + 真实 headless Edge + 真实公开视频 + 隔离 Bridge + 包内 Vosk 链路；播放器静音，未使用用户 profile。
- 40 秒内收到 416 个音频包、2 条转写；audio track 保持 `running`，无 error；总报告 `passed: true`。
- 该视频没有可检测字幕 cue（`live_subtitle_cues_present=false`）；字幕路径仍以 r22 夹具/公开视频历史证据为准，本次未验证真实字幕。
- 证据：`.sumika-next/acceptance-20261019/bilibili-live-40s/companion-soak-cc12224c-57cd-4664-80aa-9f532f7a8aa0/report.json`。

### 频繁 seek 补测

60 秒内每 10 秒 seek 一次（真实公开视频，静音、匿名）：

- 初次运行在 seek 4 出现 **stale final reference**：`media_time=42.0`，实际已 seek 到 50.7。
- 根因：一次临时的 extension→bridge `Failed to fetch` 把已批准的 passive-browser grant 清空，内容脚本停止轮询，融合上下文停留在旧帧。
- 修复：视频 push 的传输失败不再清空 grant，返回可重试标记；内容轮询有界重试并强制下一帧 full snapshot；只有显式 host 拒绝才停止。
- 修复后：6/6 seek 的 final reference 都跟随新位置（14.85/26.84/38.81/50.79/62.76/74.66），音轨保持 running。
- **seek 后转写补测**：每次 `seeked` 都销毁 AudioContext 并用 seek 事件重建，导致新上下文没有可用音频流；改为**跨 seek 保留媒体元素采集**，seek 期间丢弃 PCM，`seeked` 后采用新的 timeline identity；源变化仍停止。60 秒、每 10 秒 seek、最后留 20 秒尾段：**2–3 条转写、309–591 包**，4/4 final reference 正确。
- 极端无尾段（最后一秒仍在 seek）仍可能 0 条；这属于没有足够可转写音频，不是参考过期。
- 证据：`.sumika-next/acceptance-20261019/bilibili-seek-60s-final/companion-soak-e35d1e35-e3e1-4776-9e08-d0d25aa5221c/report.json`、`.sumika-next/acceptance-20261019/bilibili-seek-tail60-final/companion-soak-47a79ff4-9378-44f3-bf85-7d7c8a822518/report.json`、`.sumika-next/acceptance-20261019/bilibili-seek-tail60-keepalive/companion-soak-c26cbbe5-631f-4d4a-86b9-7f38915ada55/report.json`。
- 未证明：真实字幕、真实用户播放器。

## B 站真实工具栏/字幕

- **工具栏点击通过**：真实公开视频页面，播放/暂停、清晰度菜单、章节菜单、设置菜单均可点击并出现对应状态；证据 `.sumika-next/acceptance-20261019/bilibili-toolbar-r26/report.json`。
- **登录态 CC 通过**：在独立 Edge profile 登录后，打开带中英双语 CC 的公开视频并启用字幕，DOM `.bili-subtitle-x-subtitle-panel-text` 出现当前句（41 字符）；`textTracks` 仍为 0。collector 已扩展为只在 bilibili.com 读取可见字幕面板文本，不读控制菜单；r28 包含该改动。证据 `.sumika-next/acceptance-20261019/bilibili-cc-collector/report.json`。
- **匿名限制**：未登录时 `video.textTracks` 为空、字幕面板无可读文本，因此匿名 CC 不可得；不把空字幕当产品通过。

## 真实 PDF 可见页

自有两页 PDF 夹具（无私人文件），自有 Edge 阅读窗口：

- **native address window 通过**：第一页 `FIRST_PAGE_LESSON` 可见；页选择器导航到第 2 页后 `SECOND_PAGE_LESSON` 可见；第一页文字不残留；`document_path` 为绝对路径；`image_region` 为 PDF viewport crop；可见页问答引用正确页面；`paid_model_calls=0`。
- App-mode（`--app=file://`）窗口虽然出现，但标题栏以下为空白，抓图是黑灰底；PDF 内容没有进入可抓取的窗口表面。native address 普通窗口可用，因此本项以 native window 通过。
- 工具修复：`--output` 必须是绝对路径，否则 Edge 会忽略相对 `--user-data-dir` 并立即退出；只影响验收脚本。
- 证据：`.sumika-next/acceptance-20261019/pdf-live6/report.json`。
- 未验：真实个人 PDF、扫描件 OCR、连续 worker、同名路径切换；不把合成夹具当成全部 PDF 能力。

## MiniCPM-V 4.7 视觉补测

- 8083 服务健康；`/v1/models` 返回 `n_params 1,006,209,856`、`n_ctx 2048`、输入模态 `text,image,video`。
- 通过 SSH loopback 隧道发送一张 320×180 合成图（蓝框、橙圆、文字 `SUMIKA 42`、白底）：5.56 秒返回正确描述，未使用用户图片。
- 结论：MiniCPM-V 4.7:1b 已在笔记本本地可用，适合简单识图/描述；尚未接入 Sumika 默认视觉 provider，OCR、复杂图表和真实屏幕质量未验收。
- 后续规格/格式对比见 [MiniCPM-V 4.7 对比](acceptance-20261019-minicpm-v47-formats.md)：日常 1B Q8，质量优先 35B-A3B IQ3_XS。

### 文本能力补测

同一个 8083 服务也接受纯文本（它不是独立的第二个文本模型，而是 VLM 的语言主干）：

| 输入 | 结果 | 耗时 |
|---|---|---|
| “用一句话解释什么是缓存命中。” | 正确、简洁 | 2.31 秒 |
| “只输出 JSON…” | 精确输出 `{"ok": true}` | 0.97 秒 |
| 改写“明天下午三点的会…不要改时间” | 输出“下午三点会，预算不超过五十块。”，**丢失“明天”和“不要改时间”** | 1.17 秒 |

结论：可做短文本问答/分类/JSON 等低风险任务；**不能按质承担提示词改写或长期文本任务**。1B/2048 上下文，约束保持能力不足。

## 本机真实采集（2026-10-19 一次性授权）

用户明确一次性授权后执行，只记录元数据；原始帧/音频未保留、未上传。

- **摄像头**：640×480，1.378 秒；亮度均值 165.77、标准差 94.69，非空白；证据 `.sumika-next/acceptance-20261019/perception-camera.json`。
- **麦克风**：显式选 EMEET 输入（设备索引 2），3.0 秒 / 16kHz / 单声道；RMS 284.9、峰值 17674，非静音；证据 `.sumika-next/acceptance-20261019/perception-microphone.json`。
- 系统默认输入仍是 `[1,7]` 的 VoiceMeeter 虚拟设备；本次没有把默认设备当作真实麦克风。
- COM/隐藏控件：8 项通过，真实 COM 能区分普通/密码 EDIT、动作守卫与前台不变。
- **真实前台密码焦点**：Edge 本地密码输入框聚焦时 `password_paused`，普通输入框聚焦时 `ok`；只读 `CurrentIsPassword`，未输入/读取文本；报告 `.sumika-next/acceptance-20261019/password-focus-edge-r26.json`。
- 真实键鼠 30 秒首轮：3 帧、鼠标活动、匿名 schema、连续序号、干净停止；**键盘计数缺失**。随后在自有 Notepad 用 SendKeys 注入按键再跑 20 秒，Raw Input 仍为 0 帧；注入键不被该 worker 当作物理输入，不能用来补键盘证据。
- **90 秒真实游戏/键鼠操作**：40 帧，键盘计数与鼠标活动都有，匿名 schema、连续序号、干净停止全部通过；证据 `.sumika-next/acceptance-20261019/input-game-r26/report.json`。
- **5 分钟持续运行 + 轻度 CPU 负载**：106 帧，键盘/鼠标计数、匿名 schema、连续序号、干净停止全部通过；证据 `.sumika-next/acceptance-20261019/input-long-r26/report.json`。
- **10 分钟持续运行 + 轻度 CPU 负载**：277 帧，鼠标活动、匿名 schema、连续序号、干净停止通过；本次没有键盘计数，不能把这次当键盘通过。稳定性以 10 分钟运行计，键盘路径以 90 秒/5 分钟运行计。证据 `.sumika-next/acceptance-20261019/input-long10-r26/report.json`。

## 真实 PDF 选择/双窗/缩放

用 Office 生成的真实 PDF，以及用户指定的个人 PDF（个人 PDF，只读打开）跑 `verify_companion_pdf_slices.py`：

- 选择：`document-selection`，选中标志为真，页面不变；
- 双窗：两个同文档窗口，翻 B 窗到第 2 页，A 窗绑定页不变；
- 缩放：视觉摘要变化、页面 identity 不变。
- 结果：**3/3 通过**。期间修正验收工具的相对 `--user-data-dir` 与后台窗口 UIA 延迟；产品代码未改。
- 证据：`.sumika-next/acceptance-20261019/pdf-slices-r26c/report.json`；个人 PDF：`.sumika-next/acceptance-20261019/pdf-personal-algorithms/report.json`（测试后删除截图与临时 profile，报告只含页号/哈希）。
- **图片型扫描 PDF**：无文字层；第一/第二页 OCR、viewport crop、翻页、可见页问答全部通过，0 模型调用；证据 `.sumika-next/acceptance-20261019/pdf-scanned-live4/report.json`（用户移动鼠标后按同一夹具重测，仍通过）。
- **用户指定的真实个人扫描件**：个人扫描 PDF224 页，抽查无文字层；22→23 页，页号/文字哈希变化、图片可用、OCR 542/1000 字符；只记录长度/哈希，未保存书页图片或正文；证据 `.sumika-next/acceptance-20261019/pdf-personal-scanned2/report.json`。
- 仍未验：真实工具栏点击、PDF 自动选区接口限制仍按既有粘贴回退。

## 仍未验收

扫描件 PDF/OCR、长时 CPU、B 站字幕与真实工具栏点击、真实模型长时质量、提示词优化（按第 1 种关闭）。
