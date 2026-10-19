# r29 内测候选与手测配置（2026-10-19）

## 候选

- 路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r29`
- 库存：60483 文件，`inventory_verified`
- DSH：`0.2.1-rc.2`；复用 r15 已验证的 DSH/host/launcher/desktop/voice/office 运行时
- 实际 EXE：首次启动、复用、外来 HTTP 200 拒绝并保留、认证关闭与进程退出 4 项通过
- 证据：`candidate-rc2-r29/package-manifest.json`、`E:/SumikaBuild/acceptance-20261017-current/exe-startup-dd0e248915c848c085bc8ee0c1e66fc9/report.json`
- 源码全量：1412 项 OK / 20 跳过 / 113.325 秒
- 未部署、未替换日用安装；旧 r23/r24/r25/r26 保留。
- 安装包：`E:/SumikaBuild/setup-r29-20261019/Sumika-Setup-2026.10.19-r29.exe`，SHA256 `490794b440cf2e3e8d5edcfa5cf72d3dabf090d0d6a32fa0e43436727efed059`；仅构建，未执行安装。
- 干净机验收：r29 **已执行并通过**（安装/库存/EXE 四组），报告 `E:/SumikaBuild/clean-windows-r29-20261020/results/report.json`；隔离归档/安装脚本/EXE 复验也通过。详见 [clean windows 验收](acceptance-20261019-clean-windows.md)。
- 35B 角色模型：已实现 `openai-compatible-local` 角色 provider，通过 SSH 隧道 `127.0.0.1:18083 -> 笔记本 8083` 接入；隔离数据目录 `E:/SumikaBuild/manual-acceptance-20261019/data-r28` 已配置好角色 provider、模型和 sampleA 角色。

## 启动命令

```powershell
& 'E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r29/Sumika.exe' `
  -Port 8766 `
  -DataDirectory 'E:/SumikaBuild/manual-acceptance-20261019/data-r28'
```

打开 `http://127.0.0.1:8766/`。`data-r28` 是已配置好的隔离目录，不要指向日用数据；不要用 8765（日用端口）。

## 模型配置（先明确测试轨道）

| 测试轨道 | 配置 |
|---|---|
| UI/设置/记忆/日程/导入/工作台 | 不需要模型，直接测 |
| 角色/文本 | 已配置 35B 本机 provider；角色 provider 选 **本机 OpenAI 兼容（loopback）**，endpoint `http://127.0.0.1:18083/v1`，模型 `D:\Models\minicpm-v47\35B-IQ3_XS.gguf` |
| 35B 单模型常驻（8083） | 通过 SSH tunnel `127.0.0.1:18083 -> 192.168.31.227:8083` 接入；tunnel 未开时角色不可用，属依赖不可用 |
| 视觉/屏幕 | 产品没有独立视觉 provider；PDF/B 站使用对应验收工具；不要把 35B 视觉当成已接线 |
| 提示词优化 | 按第 1 种**保持关闭**；按钮不可用是预期 |

## 35B 角色接线

```powershell
ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes `
  -L 18083:127.0.0.1:8083 lostrain@192.168.31.227
```

- 设置文件：`E:/SumikaBuild/manual-acceptance-20261019/data-r28/role-model-settings.json`
- 角色 provider：`openai-compatible-local`
- endpoint：`http://127.0.0.1:18083/v1`
- 模型：`D:\Models\minicpm-v47\35B-IQ3_XS.gguf`
- sampleA 角色已复制到 `data-r28/roles/sampleA`
- 实测：角色回复 3.01 秒、31 字符、319 tokens；证据 `.sumika-next/acceptance-20261019/role-35b-smoke.json`
- 35B 是单模型常驻，角色会排队；提示词优化仍关闭
- 35B 隧道已注册登录自启任务 `Sumika-35B-Role-Tunnel`，当前 Running；包装脚本 `tools/start-35b-role-tunnel.ps1` 带断线重连，已实测杀掉 ssh 后 8 秒内新 PID 恢复
- 学习摘要等严格 JSON 辅助任务未启用：35B 输出格式不稳定，避免返回坏结果

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
- 每项附截图、数据目录和候选路径；不要把旧 r23 证据自动算作 r29 通过。
