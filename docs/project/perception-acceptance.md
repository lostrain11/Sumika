# 授权感知验收

## 当前产品范围（2026-10-18）

源码新增：能力 → 语音交互 → 陪学会话 → 摄像头采集一帧，每次明确确认；原消息框提问，停止陪学清除上下文。摄像头能力/多模态输入/当前模式图片来源必须允许；连续陪学采集须先停止。独立桌面运行时限时采集、释放设备，图片只在内存中，不写文件，提问时才发送已配置角色模型。撤销/退出后迟到帧不得写回；异常不自动重试。

合成验收覆盖HTTP授权、严格布尔许可、禁用/忙碌拒绝、超时/撤销竞态、图片问答绑定与48项陪学UI检查。r16已纳入变更，包内解释器16项摄像头/资源测试通过，包内UI证据为`.sumika-next/acceptance-20261018/companion-camera-r16/report.json`。r20真机摄像头服务单帧已验；前端逐次确认与真实模型完整流程未验。下方2026-09-15设备结果只证明当时独立采集链路，不能当作当前产品全流程验收。

## 当前摄像头真机检查（2026-10-18）

r18单帧子进程15秒超时，未保存图片。DirectShow显式后端对照打开/六帧读完约1秒；源码服务切换后1.828秒取得640×480有效非黑帧，停止清空内存上下文，无图片文件。证据：`.sumika-next/acceptance-20261018/camera-live-r18/`（失败/诊断）与`camera-live-source-dshow/report.json`（源码成功）。后者报告scope文字误写packaged，product明确为`D:/Code/Sumika`，应按源码解释；r19尚不包含修复；r20已构建，包内真机服务2.281秒取得640×480有效帧，停止清空、无图片落盘，证据为`.sumika-next/acceptance-20261018/camera-live-r20/report.json`。r20陪学控件48项通过，证据为`companion-controls-r20/report.json`（同根目录）；界面夹具与真机服务分别验，不代表全流程通过。没有发送图片模型，不证明模型识图质量或前端逐次确认真机全流程。

## 当前语音复验（2026-10-18，r18）

- 本地SAPI/PlaySound实际播放完成、取消及进程回收5项通过；取消14ms，无人工听感确认。证据：`.sumika-next/acceptance-20261018/playback-live-r18/report.json`。
- 使用既有5.592秒中文样本，真实VAD、SenseVoice、绑定问答、SAPI分段文件、二次打断8项通过，PCM清空、worker停止。证据：`.sumika-next/acceptance-20261018/voice-sample-r18-timing/report.json`。回答为本地夹具，不使用麦克风或云端，不证明模型质量。
- 首轮验收工具曾将播放开始错记为合成完成；旧报告的首音延迟无效。已改用合成文件完成事件，相关24项测试通过。复验两条识别到首段合成73.3–216.7ms，不等于扬声器首音或P95。
- 新增现场麦克风权限/取消、摄像头前端逐次确认与真实模型全流程仍未验，不用上述结果替代。

## 历史设备验收（2026-09-15）

范围：摄像头与麦克风的真实采集链路。全程本地；画面与音频**不打印、不上传、不提交**，只记录元数据，默认采完即删（`--keep` 才保留）。

## 最终结果：通过

设备：摄像头 **EMEET SmartCam C60E 4K**；麦克风用同一台设备（设备索引 35）。

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 摄像头 | 可用 | 640×480，平均亮度 96.86、标准差 96.77（真实画面，非黑帧） |
| 麦克风 | 可用 | 16 kHz / 16-bit / 单声道 2.0 秒，RMS 357.9、峰值 1919（有真实信号） |
| 采集链路 | 可用 | `capture_camera` / `capture_audio` 均要求 `approved=True` 显式授权 |

## 前两次失败的真实原因：是我的代码问题，不是用户设置

第一次运行：摄像头纯黑帧、麦克风纯静音。系统隐私开关经查**本来就是允许**（相机与麦克风的 `ConsentStore` 总开关和 `NonPackaged` 都是 Allow），所以不是被系统拦截。真正原因有两处：

1. **摄像头只读一帧**。多数摄像头刚打开时首帧是黑的。修复：`capture_camera` 增加 `warmup`（默认丢弃 5 帧），并返回实际读取与丢弃的帧数。修复后亮度/方差恢复正常。
2. **采样率写死 16000**。`capture_audio` 原来固定 16 kHz，部分设备根本不支持，PortAudio 直接报 `Invalid sample rate`。修复：先用 `check_input_settings` 探测，设备不接受时按设备默认率录，再用线性插值重采样到目标率，并在返回值里给出 `captured_rate` 与 `resampled`。

也就是说：**接口能跑通 ≠ 拿到有效信号**。验收脚本据此改为黑帧/静音一律判未通过，并把 `capture_api_works`（调用成功）与 `passed`（信号可用）分开报告。

## 另一个真实发现：系统默认输入是静音虚拟设备

用系统默认输入重测，结果仍是静音（RMS 0.5、峰值 1）；显式指定 EMEET 麦克风则有信号。该机器上装了多个虚拟音频设备（VoiceMeeter、网易虚拟音频设备、Dubbing Virtual Device），默认输入很可能落在其中一个。

设计含义：**Sumika 的语音配置必须允许显式选择输入设备**，不能依赖系统默认；这也符合项目里“同一能力可切换实现、失败不静默回退”的原则。此项已列入后续工作。

## 复现方式

```powershell
# 默认设备
& .sumika-next\desktop-env\Scripts\python.exe -B tools/verify_perception_local.py
# 指定输入设备（先用下面的命令列出索引）
& .sumika-next\desktop-env\Scripts\python.exe -c "import sounddevice as sd;[print(i,d['name']) for i,d in enumerate(sd.query_devices()) if d['max_input_channels']>0]"
& .sumika-next\desktop-env\Scripts\python.exe -B tools/verify_perception_local.py --audio-device 35
```

证据：`perception-local-evidence.json`（通过的那一次）。默认设备的静音结果另存为本地文件，不进入仓库。
