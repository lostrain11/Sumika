# 本地语音闭环验收（2026-09-15）

## 活动室一次性语音输入接线

现有输入框左下 `♪` 按钮接 `SpeechInput`，经本次确认录音 5 秒，由独立语音
Python 环境调用已有 `capture_audio` 和 Vosk `transcribe`。识别只填入未变化的
当前角色草稿，仍需用户发送，不隐式调用角色模型。语音配置、麦克风模块授权、
ASR 启用及固定 provider 分别核对，无本地依赖时失败关闭，不下载模型。

`extensions/roles/speech_input.py` 管理子进程、60 秒上限、取消和正常退出；
`ui/server.py` 复用原有写入口来源/令牌保护。切换角色、修改草稿或配置后丢弃
迟到结果。取消不自动重试；无法确认进程结束时不报告安全退出。

验证：28 项 `test_speech_input`、`test_ui_server`、`test_bridge_data_lease` 测试通过；
`tools/verify_speech_input_ui.mjs` 使用产品标记和 JS 验证确认取消、草稿、角色变化和
取消行为，证据 `.sumika-next/speech-ui-dcd89cdc-3d9f-4cc3-a897-4a6cb4bb79f4/report.json`。
测试没有打开麦克风，子进程测试使用本地文本替身，不能替代真实设备验收。

异常父进程退出已补验证：`SpeechInput` 在发送录音指令前，将子进程纳入 Windows
`KILL_ON_JOB_CLOSE` 作业；作业句柄不继承给子进程，接管失败不发送指令。
`tools/verify_speech_parent_exit.py` 使用实际 SpeechInput 和文本替身，确认子进程
已启动后强制结束隔离父进程，子进程被回收、无迟到输出。证据：
`.sumika-next/speech-parent-exit-2a61c944ee184b6a8a94ad43ccf174f3/report.json`。
这证明受管子进程的生命周期，不代表测试了真实麦克风驱动在异常退出时的释放。

仍需完成：真实麦克风与 Vosk 联调、朗读播放、连续轮次/回声/打断及驱动退出验收。
原始 WAV 暂保留在个人数据 `speech-input/<id>/capture.wav`，
未制定自动清理策略，不随安装包发布。日用服务未重启，现有包尚未包含此接线。

目标：证明语音链路真的能跑通，而不是只有接口和状态机。全程本地、无麦克风、无云服务。

## 链路

`extensions/roles/voice.py` 里已有两个可替换后端：

- 合成：Windows SAPI（`SAPI.SpVoice` + `SAPI.SpFileStream`，输出 16-bit PCM WAV）
- 识别：Vosk（`Model` + `KaldiRecognizer`，读取 16-bit 单声道 WAV）

验收脚本 `tools/verify_voice_local.py` 把它们串成闭环：合成一句中文 → 识别 → 计算字符召回率 → 写证据。

## 实测结果（`voice-local-evidence.json`）

| 项 | 值 |
| --- | --- |
| 合成语音 | Microsoft Huihui Desktop - Chinese (Simplified) |
| 识别模型 | vosk-model-small-cn-0.22 |
| 期望文本 | 今天排练很顺利，我们晚上九点看动画吧 |
| 识别结果 | 今天 排练 很 顺利 我们 晚上 九点 看重 话 吧 |
| 字符召回 | 0.8824（阈值 0.6，通过） |
| 合成耗时 | 249 ms |
| 识别耗时 | 2147 ms（含模型首次加载） |
| 麦克风 / 云服务 | 均未使用 |

## 结论与限制

- 链路可用：两个后端都是本地实现，失败时按代码约定直接报错、不切换其他 provider。
- 首次识别 2.1 秒里包含模型加载；实时对话需要**常驻 recognizer + 流式分帧**，不能每次调用都重新加载模型（与 OCR 引擎复用是同一类问题）。
- 本次出现一处识别错误：「动画」被识别成「看重 话」。小模型对短句仍有误差，阈值只用于验收，不代表可以直接用于字幕级准确度。
- **仍未验收**：真实麦克风采集、扬声器播放、打断/回声处理。这些需要设备与用户授权，不能用合成音频替代。
- 语音相关状态机（listening/transcribing/responding/playing/cancelled/error）此前已有独立测试；本次补的是端到端语音链路本身。

## Speech failure handling checkpoint

Existing SpeechInput and audio device discovery were modified in place. Failed stop or job closure retains ownership and unknown state, blocks a second capture, and supports explicit cleanup retry. Completion is published only after cleanup. An explicitly missing voice interpreter never falls back.

Validation: 38 related tests passed, then 14 focused tests passed after final cleanup adjustment. Actual owned parent exit: `.sumika-next/speech-parent-exit-16994aa8539b4630934145ced30de780/report.json`. No microphone opened; real audio and playback remain pending. Daily service and package unchanged.

语音停止恢复：复用 `ui/prototype-d/index.html:722` 输入框语音按钮，无新入口。停止失败保留请求 ID，原按钮提供明确的停止重试，不发起新录音；启动响应未到时取消会等待 ID 后停止一次。Edge 隔离产品模块夹具六项通过，证据 `.sumika-next/speech-ui-2d8178c4-e8b7-4126-a4ef-254ca1999bfd/report.json`。未打开麦克风、未重启日用服务；音频播放与连续语音仍未接通。

## Local playback backend

`SpeechPlayback` reuses `SpeechInput` ownership, cancellation and unknown-state handling, and the existing selected SAPI synthesis backend. Authenticated `/api/voice/output/start`, `/cancel` and status endpoints are connected; start requires explicit approval, enabled voice settings and the selected Windows SAPI capability. No microphone or model request is needed. Synthesis is followed by a capability recheck and synchronous playback with `SND_NODEFAULT`.

39 related tests passed, including actual text worker cancellation and mocked audio calls. Parent-exit and Edge input regression reports are recorded in the project checkpoint. No audible hardware test, UI playback entry, role-switch integration or continuous voice yet. The 60-second task deadline and 4000-character limit are explicit current limits. No daily service restart or package rebuild.

Audio-stop integration: role switching stops existing audio first; voice settings/capability mutation cancels both tasks; shutdown attempts both even if input stop fails. Fifty relevant tests passed. Playback-entry proposal is isolated at `.sumika-next/voice-playback-proposal.html`, not a product change. No actual audio test. Output-only settings still require input_device under current schema; next step must separate this without weakening microphone execution authorization.

Output-only configuration: voice.enabled now accepts input_device=null, allowing local playback without configuring a microphone. Recording execution retains explicit device and authorization checks; a real Bridge HTTP test confirms approved recording without a device is rejected without spawning. 43 related tests and 17 role/settings tests passed. Existing capability form already saves null correctly. No live audio or daily restart. Playback-entry placement remains awaiting confirmation.

Legacy capability toggle now cancels active audio like management writes. Unknown stop is returned as HTTP 502 JSON on settings, selection and capability routes; persisted disable remains effective. 61 existing UI checks passed before the correction and 25 server checks passed after it. Remaining UI issue: failed-write handlers assume rollback visually; they must refresh authoritative settings on unknown-stop responses. No daily restart or hardware acceptance.

能力详情写入失败恢复：复用既有语音详情表单，不新增入口。模块/麦克风授权写入失败后读取服务端值与revision，不假定回滚、不重发；读取失败则不确定态并禁用。设置保存失败也刷新基线并保留输入。隔离Edge实际表单四项验证通过，工具 `tools/verify_capability_write_recovery.mjs`；未修改日用配置，未实测音频。

语音进程输出结构校验：共用 `SpeechInput._finish` 现在先确认 JSON 是对象，
再读取 text。数组、null、数字等异常返回进入 unknown 并回收受管进程，
不会因 AttributeError 留在 recording/processing。录音和朗读均覆盖；
真实文本子进程返回 null 的退出检查通过。运行
`python -B -m unittest tests_next.test_speech_input tests_next.test_speech_playback tests_next.test_ui_server`
共 41 项通过。既有 HTTPError ResourceWarning 和 is_reserved 弃用警告仍在。
没有麦克风/扬声器硬件操作、日用重启或安装包重建；新朗读入口仍待用户确认。


活动室朗读入口（用户明确批准“加入”）：沿用设计稿 ui/prototype-d/index.html:325 的聊天气泡与 mini-btn 风格，在角色回复下方新增单一“朗读／停止”按钮，用户消息及错误提示不显示。仅点击才请求本地输出，不自动启用语音、不使用麦克风或模型。加载历史保留状态、切换角色及清空聊天先停止、失败保留重试停止；启动结果未知且无 ID 时禁止再次启动。超过 4000 字符不截断，按钮提示限制。Edge 产品渲染函数及模块 8 项检查通过，截图已查看；证据 .sumika-next/playback-ui-b0a67753-500b-40f2-90b5-9b2b5817f2c1/report.json。30 项后端回归通过；未做真实声音硬件验收、日用重启或重建安装包。


## 真实本地输出与取消

复用现有 SpeechPlayback、SAPI、winsound 和受管子进程，使用隔离能力库；日用设置不变。显式命令 `python -B tools/verify_speech_playback_live.py --play` 会播放简短中文测试，再取消第二段较长语音。没有麦克风或模型调用，不删除文件。

证据 `.sumika-next/playback-live-ec8a6319a287479eb705cd8993b95244/report.json`：5 项检查通过，首段 WAV 为 22050 Hz、16-bit 单声道、74713 帧；Windows 同步播放返回成功。第二段生成后显式取消，约 4 ms 回收实际进程及作业，无迟到完成。当前默认输出为 VoiceMeeter 虚拟设备；是否听到仍待用户反馈，不能据 API 成功宣称物理扬声器或音频缓冲清空已验收。真实麦克风、连续语音和回声处理仍未验收。

用户随后明确要求延缓此项验证：听感反馈及真实麦克风/音频硬件验收暂缓，保留已有程序级证据，不继续播放或采集。
