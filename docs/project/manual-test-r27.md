# r27 内测候选与手测配置（2026-10-19）

## 候选

- 路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r27`
- 库存：60483 文件，`inventory_verified`
- DSH：`0.2.1-rc.2`；复用 r15 已验证的 DSH/host/launcher/desktop/voice/office 运行时
- 实际 EXE：首次启动、复用、外来 HTTP 200 拒绝并保留、认证关闭与进程退出 4 项通过
- 证据：`candidate-rc2-r27/package-manifest.json`、`E:/SumikaBuild/acceptance-20261017-current/exe-startup-e5e5c6e9238f42588070f92abf75318f/report.json`
- 源码全量：1411 项 OK / 20 跳过 / 106.459 秒
- 未部署、未替换日用安装；旧 r23/r24/r25/r26 保留。
- 安装包：`E:/SumikaBuild/setup-r27-20261019/Sumika-Setup-2026.10.19-r27.exe`，SHA256 `40e93c39828920971b4d37d998f73a271790a25209a2fc9dc99986d488d15fe4`；仅构建，未执行安装。
- 干净机验收：Windows Sandbox **已执行并通过**（安装/库存/EXE 四组），报告 `E:/SumikaBuild/clean-windows-r27-20261019/results/report.json`；发现并修复 install_sumika.ps1 缺少 `browser-extensions` 根目录允许项。详见 [clean windows 验收](acceptance-20261019-clean-windows.md)。

## 启动命令

```powershell
& 'E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r27/Sumika.exe' `
  -Port 8766 `
  -DataDirectory 'E:/SumikaBuild/manual-acceptance-20261019/data-r27'
```

打开 `http://127.0.0.1:8766/`。`data-r27` 必须是**新目录**，不要指向日用数据；不要用 8765（日用端口）。

## 模型配置（先明确测试轨道）

| 测试轨道 | 配置 |
|---|---|
| UI/设置/记忆/日程/导入/工作台 | 不需要模型，直接测 |
| 角色/文本 | 笔记本 Ollama `11434` 经 SSH tunnel 到本机 loopback（例如 `18114`），Sumika 角色 provider 选 Ollama、endpoint `http://127.0.0.1:18114`；模型用已装文本模型 |
| 35B 单模型常驻（8083） | 当前产品角色 provider 不能直接连 llama.cpp 的 OpenAI HTTP；**不要把它填进角色 endpoint 期待可用**，这需要另做本地 OpenAI-compatible role provider（本地模型任务，不在本轮主线） |
| 视觉/屏幕 | 产品没有独立视觉 provider；PDF/B 站使用对应验收工具；不要把 35B 视觉当成已接线 |
| 提示词优化 | 按第 1 种**保持关闭**；按钮不可用是预期 |

## 手测顺序

1. 设置/外观/能力开关；确认无伪造状态。
2. 长期记忆增删改查、清空、导出。
3. 定时任务/提醒；创建、编辑、到期、重启。
4. 角色导入、切换、资源编辑；不要求模型质量。
5. 工作台、交接草稿、PDF 合成可见页。
6. B 站公开视频、seek、音频状态。
7. 需要模型的角色/TTS/视觉；先按上表配好，失败先判断 provider/tunnel，不直接记产品缺陷。
8. 真实摄像头/麦克风、真实个人 PDF、干净机器单独记录，需要你在场。

## 记录规则

- 通过/失败/依赖不可用/未测试四类分开。
- 模型不可用、tunnel 未开、端口被占用属于“依赖不可用”，不是 UI 通过或产品缺陷。
- 提示词优化关闭是产品决定，不是失败。
- 每项附截图、数据目录和候选路径；不要把旧 r23 证据自动算作 r27 通过。
