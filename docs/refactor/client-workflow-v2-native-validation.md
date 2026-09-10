# 双窗口原生验收记录

## 已验证范围

2026-09-09，当前未提交工作区的 custom-protocol 构建通过隔离原生 smoke。证据位于 `artifacts/native-smoke/1788965104048`，`result.json` 为 passed=true。只使用隔离数据、Sample Avatar 和本地 Core，不连接 DSH、账户或模型；不能作为真实渠道质量证据。

- 主窗口与陪伴窗口均为真实 Tauri WebView，共享 Core PID。
- 草稿分别保留，陪伴的浏览器原生命令被拒绝。
- 紧凑、全景分别保留位置尺寸；全屏、透明和置顶可用。
- 隐藏显示不抢焦点；最小化及恢复发出渲染生命周期事件。
- 对已核验 PID 的 HWND 发送 WM_CLOSE，只隐藏对应窗口。
- 恢复工作台保持 Core；明确退出结束自有进程和 Core，清理隔离运行数据。

未完成：多显示器及物理拔屏、托盘图标鼠标点击、系统锁屏实机验证。几何回退由 Rust 测试覆盖，不能代替硬件验证。截图已生成，图片工具受沙箱初始化故障影响时，不声称已完成人工式视觉检查。

## 已确认故障与修复

1. 固定端口8771与日用 Core 冲突：smoke 改用空闲环回端口，不停止日用实例。
2. `native_windows_state not allowed / Plugin not found`：custom-protocol 窗口被测试导航到 HTTP，Tauri 将其视为远程来源。移除测试远程导航，保持打包页面。开发模式仅将精确环回地址设为 devUrl，不开放通配远程权限。
3. 陪伴初始化读取未完成导航的 URL，可能导航到空白文档：在窗口配置中直接指定陪伴查询参数，删除运行时重导航。
4. 模式切换卡住：状态查询持有互斥锁等待窗口线程，窗口事件同时等待该锁。查询原生状态前释放锁，回写几何时核对模式未变化。
5. 新增工具栏遮挡原按钮：调整工具栏位置；折叠输入框测试先悬停并显式展开。
6. 截图默认合成白底导致 alpha 断言失败：透明检查使用 omitBackground，保留实际像素断言。
7. 通过标题定位原生窗口不可靠：使用受信任状态命令返回的 HWND，发送关闭前再次核对 PID。

## 复用命令

2026-09-10整合复验：生产前端构建、Rust35项、独立custom-protocol构建再次通过。
当前双窗口完整证据为 `artifacts/native-smoke/1789024028431/result.json`，`passed=true`。
两原生窗口、共用Core、原生命令隔离、尺寸/全屏/透明、最小化恢复、关闭隐藏与完全退出均通过。
已查看工作台与紧凑陪伴截图：工作输入可见，陪伴角色和脸部非空白；未配置模型时有显式配置提示。
仍未进行物理多屏拔插、系统锁屏或鼠标点击托盘的实机验收，不用恢复命令冒称这些操作已测试。

日用客户端占用默认二进制时使用独立构建目录：

```powershell
Set-Location 'D:\Code\Sumika'
npm --prefix frontend run build
cargo build --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target/native-smoke --features custom-protocol
$env:SUMIKA_SMOKE_BINARY = 'D:\Code\Sumika\src-tauri\target\native-smoke\debug\sumika-desktop.exe'
node tools/native-ui-smoke.mjs D:\Code\Sumika\artifacts\native-smoke
```

测试命令有超时，失败不自动重发模型请求。只清理该次启动的自有进程与隔离数据。此前 Codex 沙箱 helper 故障现已解除；当前普通执行及图片读取可用，无需再次重启、删除配置或释放日用8771。

2026-09-10父子预算整合复验：最新前端与独立custom-protocol构建成功，原生smoke完整通过。
证据 `artifacts/native-smoke/1789029799640/result.json`，构建日志 `artifacts/native-delegation-build.log`，
运行日志 `artifacts/native-delegation.log`。仍保留前述物理多屏、锁屏与鼠标托盘硬件缺口。
