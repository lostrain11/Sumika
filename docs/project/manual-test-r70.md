# r70 内测候选与手测配置（2026-10-20）

## 候选

- 路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r70`
- 库存：60485 文件，`inventory_verified`
- DSH：`0.2.1-rc.2`；复用 r15 已验证的 DSH/host/launcher/desktop/voice/office 运行时
- 实际 EXE：首次启动、复用、外来 HTTP 200 拒绝并保留、认证关闭与进程退出 4 项通过
- 证据：`candidate-rc2-r70/package-manifest.json`、`E:/SumikaBuild/acceptance-20261017-current/exe-startup-d5019bac286047d78b6a0357582f9dc6/report.json`
- 源码全量：1412 项 OK / 20 跳过 / 115.429 秒（`.sumika-next/review-20261018/full-suite-final23.log`）
- 未部署、未替换日用安装；旧 r23/r24/r25/r26 保留。
- 安装包：`E:/SumikaBuild/setup-r70-20261020/Sumika-Setup-2026.10.20-r70.exe`，SHA256 `907966b9e5d3924f3b34c65da09a452cdb0543b9ff5a9ecfb1823ae86c6d98e8`；已构建，未执行安装。
- 干净机验收：r70 **未执行**；最近一次干净机通过的是 r32（`E:/SumikaBuild/clean-windows-r32-20261020/results/report.json`）。r70 只改 UI，不要把 r32 证据算到 r70。
- 35B 角色模型：`openai-compatible-local` 角色 provider，通过 SSH 隧道 `127.0.0.1:18083 -> 笔记本 8083` 接入；隔离数据目录当前名册只有 `sampleA` → **Sumika 示例助手**，安和昴已归档到 `data-r28/backups/roles/c65cac43e1e44c59abb6f94cd17e4c1c.zip`，需要时从角色资源包恢复。

## 启动命令

```powershell
& 'E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r70/SumikaShell.exe' `
  -Port 8766 `
  -DataDirectory 'E:/SumikaBuild/manual-acceptance-20261019/data-r28'
```

打开 WebView2 主窗口；也可用 `Sumika.exe -NoBrowser` 启动桥接后手动访问 `http://127.0.0.1:8766/`。`data-r28` 是已配置好的隔离目录，不要指向日用数据；不要用 8765（日用端口）。

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
- 默认名册只有 1 个角色：`sampleA`，显示名 **Sumika 示例助手**；`sumika-guide` 不再出现在名册。安和昴已从当前测试数据归档，备份在 `E:/SumikaBuild/manual-acceptance-20261019/data-r28/backups/roles/c65cac43e1e44c59abb6f94cd17e4c1c.zip`；需要时从角色资源包恢复。
- 实测：35B 角色冒烟通过；证据 `.sumika-next/acceptance-20261019/role-35b-smoke.json`；安和昴角色卡见 `.sumika-next/acceptance-20261020/role-quality-ando.json`
- 35B 是单模型常驻，角色会排队；提示词优化仍关闭
- 35B 隧道已注册登录自启任务 `Sumika-35B-Role-Tunnel`；手测开始前已启动，`127.0.0.1:18083` 正在监听。包装脚本 `tools/start-35b-role-tunnel.ps1` 带断线重连，已实测杀掉 ssh 后 8 秒内新 PID 恢复
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

## 本轮 UI 手测重点

1. 活动室 1440 / 698：安和昴的聊天头、输入框、舞台名同步；698 下聊天在舞台下方；无横向滚动。
2. 能力页：办公文件、角色卡·世界书、桌宠模式图标不为空白，且不与相邻模块重复；开发/办公/陪伴分组正常。
3. 数据与存储：滚动到底部，“添加偏好或目标”和“记录层”之间有分隔，不重叠；无重复“行为子记忆”；统计显示两张卡。
4. 模型与连接：三个 tab 可切换；本机 provider 下“凭据环境变量名”隐藏；服务地址/模型名可读。
5. 连接与权限：排除应用输入框占满整行。
6. 工作台：未连接时显示居中空状态，而不是空白页；5175 被占用时不自动杀进程。
7. 默认名册只有“Sumika 示例助手”一个；活动室底部用箭头表示悬停展开，不再显示“悬停展开”文字；待机/工作/休息和“桌宠小窗”说明已从活动室移除。

## 记录规则

- 通过/失败/依赖不可用/未测试四类分开。
- 模型不可用、tunnel 未开、端口被占用属于“依赖不可用”，不是 UI 通过或产品缺陷。
- 提示词优化关闭是产品决定，不是失败。
- 每项附截图、数据目录和候选路径；不要把旧 r23 证据自动算作 r70 通过。

## r70 UI 验收重点

- 顶栏：活动室显示角色模型（MiniCPM-V 4.7 · 本地）；工作台显示“工作模型 · DSH”；能力/设置页不显示模型胶囊和本地服务状态。
- 能力卡片：每张都有绿色“已启用/红色已停用”；有配置的卡片在下方增加蓝色“可配置”胶囊；状态区与左侧图标同高。
- 卡片标题与图标垂直居中对齐；说明文本保持一句用户向描述。
- 角色卡右侧有“管理角色与记忆”和“导入角色卡 / 模型”；导入使用弹窗，不再在名册条下展开。
- 桌宠：镜头光圈悬浮球，角色首字，漂浮/悬停/拖动/展开动画；收起入口在气泡标题栏右侧箭头。
- 默认名册只有 Sumika 示例助手；安和昴归档备份在 data-r28/backups/roles/c65cac43e1e44c59abb6f94cd17e4c1c.zip。

## 桌面壳（r70 新增）

- 安装器与开始菜单快捷方式现在指向 `SumikaShell.exe`，打开的是 WebView2 主窗口，不再打开默认浏览器。
- 便携版同样直接运行：

```powershell
& 'E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r70/SumikaShell.exe' `
  -Port 8766 `
  -DataDirectory 'E:/SumikaBuild/manual-acceptance-20261019/data-r28'
```

- `SumikaShell.exe` 负责启动本地桥接、等待 HTTP 就绪、用 WebView2 加载界面；关闭窗口时向桥接发送认证关闭请求。
- 保留 `Sumika.exe -NoBrowser` 作为无壳启动入口，便于排障和自动化。
- r70 实测：壳启动后 HTTP 200、窗口标题“晴日部室”；关闭窗口后壳退出、桥接停止。

## r70 桌面壳与桌宠行为

- 任务栏/窗口使用 Sumika 花形镜头图标；安装器、壳和桌宠宿主共用 `packaging/Assets/Sumika.ico`。
- 主窗口是 WebView2 原生壳，开始菜单与安装器快捷方式指向 `SumikaShell.exe`。
- 桌宠改为独立顶层窗口 `SumikaPet.exe`，透明、置顶、不占任务栏；默认显示为 54px 镜头光圈球，点击展开。
- 壳与页面通过 `sumika:context` 消息同步路由：
  - 活动室：隐藏桌宠（房间内已有角色）
  - 工作台、能力、设置：显示桌面桌宠
  - 主窗口最小化：显示桌面桌宠；恢复且回到活动室后隐藏
- 壳提供托盘图标，可显示主窗口、隐藏到托盘或退出；隐藏到托盘后桌宠显示；桌宠窗口可展开/收起。
- 工作台启动改为自动选择空闲端口，不再被旧的 5175 占用阻塞。
- 实测：r70 板页启动桌宠 1 个；活动室 0 个；最小化 1 个；恢复后 0 个。

## r70 桌面桌宠修复

- 桌宠默认窗口从 56×56 扩到 76×76；54px 光圈球带阴影完整显示，不再被窗口左上裁切。
- 桌宠窗口启动位置固定到主屏工作区右下角，不再出现在 (0,0)。
- 移除 `WDA_EXCLUDEFROMCAPTURE`，桌宠在系统截图/录屏中可见；不再因截图而变透明。
- 桌宠窗口显式置顶（`Topmost` + `SetWindowPos(HWND_TOPMOST)`），点击球体可展开，展开后 340×430。
- 主壳用 `?shell=1` 加 `shell-host` 类，页面内 `#deskpet` 始终隐藏；桌面只剩一个独立桌宠。
- 托盘菜单新增“隐藏到托盘”；隐藏后桌宠显示，恢复主窗口并回到活动室后隐藏。

## 工作台

- 前端启动工作台使用 `port: 0`，自动选择空闲端口，旧 5175 实例不会再造成“端口被占用”。
- 若 DSH profile 仍被旧进程持有，需要先结束旧工作台进程；正常关闭壳会通过 bridge 停止自己启动的工作台。

## r70 桌宠策略简化

- 桌面桌宠**只在客户端最小化或隐藏到托盘/后台时**启动；活动室之外的页面不再启动桌面桌宠。
- 桌面桌宠窗口 76×76，固定在主屏工作区右下角；不再裁切；隐藏 tooltip，点击球体仍可展开。
- 主窗口内的 `#deskpet` 悬浮球已移除；活动室之外的页面改为右下角“✿ 桌宠”胶囊入口，不再出现第二个球。
- 点击“✿ 桌宠”会把主窗口隐藏到托盘并进入桌宠模式；点击托盘图标恢复主窗口，桌宠停止。
- 桌面桌宠在最小化/隐藏后由 400ms 轮询同步，恢复主窗口会停止桌宠；首次启动仍有短暂进程启动延迟，这是当前回退策略的已知边界。
- 保留工作台自动端口；旧 DSH profile 若被残留进程占用，仍需先结束旧进程。
