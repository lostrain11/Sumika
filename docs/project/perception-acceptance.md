# 授权感知的设备验收（2026-09-15）

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
