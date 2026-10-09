# 单文件安装向导与旧数据接续

当前文件：`E:/SumikaBuild/wizard-l2/Sumika-Setup-2026.09.20-l.exe`。
这是中文、当前用户级安装向导，不要求管理员或 WSL。封装 L 程序包，
不包含个人角色、模型权重或密钥。公开发行审查仍后置。

## 在当前电脑安装

1. 双击安装 EXE，选择一个尚不存在的新程序目录。默认是
   `D:\Apps\Sumika\2026.09.20-l`；不覆盖旧安装。
2. 安装不再显示个人数据选择页，自动沿用 `%LOCALAPPDATA%\Sumika`，或设置中登记的迁移位置。
   当前电脑完整路径为 `C:\Users\Lostrain.DESKTOP-43S7UNP\AppData\Local\Sumika`。
3. 可勾选桌面快捷方式。安装后从开始菜单中的 **Sumika 2026.09.20-l → Sumika**
   或对应桌面快捷方式启动；快捷方式与直接启动 EXE 使用相同的数据位置。
4. 安装器不自动启动程序、不自动停止旧服务。如果旧 Sumika 仍占用 8765，请先正常退出旧版。

程序目录与个人数据目录不能互相包含。进入 **设置 → 数据与存储** 可查看、打开、迁移目录，
或从已校验的备份恢复到新目录。目标须是现有父目录下尚不存在的目录。
迁移先退出客户端，再备份、复制、校验和更新 `%LOCALAPPDATA%\Sumika-location.json`，最后重启。
原目录和备份保留，外部模型权重不复制。失败不自动重试；界面给出迁移记录位置。
高级命令行 `-DataDirectory` / `SUMIKA_DATA_DIR` 仍优先于迁移登记；日常请用普通快捷方式。

卸载默认保留个人数据；可主动勾选删除，随后再次确认显示的完整目录。静默卸载始终保留。
清理仅限已知 Sumika 数据文件，不跟随目录链接，不删除外部模型库、原始角色卡或未知文件。
运行中的数据不能清理；失败会中止卸载。目录空壳和锁文件可能保留。
本轮不执行真实用户数据删除测试。

## 哪些数据不用重新导入

本机已核对：安和昴位于个人目录的 `roles\ando-subaru`，聊天存储为
`role-conversations.sqlite3`，角色数据库路径为同目录 `role-chat.db`，配置在
`role-model-settings.json`。选择原个人目录即可沿用这些文件。
连接配置引用原有凭据来源，启动器继续读取该目录的 `env.ps1`（若存在）。
本地模型库配置为 `E:\Models`，安装不会复制、移动或重新下载这些权重。

高级启动参数如果指定新的空个人目录，会得到新用户状态，不会自动导入旧数据。
安装器本身不写入旧个人目录；首次运行才由 Sumika 正常读取与维护该目录。

## 旧源码版工作台历史需要另外复制一次

源码版 DSH Profile 位于 `D:\Code\Sumika\.sumika-next\daily\0.1.5-rc.2`，
不在上述个人目录内。安装版期望的位置是
`%LOCALAPPDATA%\Sumika\dsh-profiles\0.1.5-rc.2`。
只保留角色数据目录不会自动接续这份工作台历史。

在新旧 Sumika 均退出后、第一次打开安装版工作台前，可以双击安装包旁的
`Import-Old-Workbench.cmd`（此快捷脚本仅针对当前开发电脑），或在源码目录执行：

```powershell
D:\Tools\python\Python314\python.exe -B tools/import_legacy_profile.py --source "D:\Code\Sumika\.sumika-next\daily\0.1.5-rc.2" --data "$env:LOCALAPPDATA\Sumika" --apply
```

这个工具持有源 Profile 和目标个人目录的写锁，核对原进程创建身份，逐文件复制并验证哈希，
完成后才发布目标目录。源目录保留，不自动启动，不发送模型请求，不重放未知任务。
DSH 的生成依赖目录不复制，由原生运行时重建；外部项目路径维持原样。
目标 Profile 已存在时拒绝合并，活动进程或无法核对归属时也拒绝。失败副本保留待检查。
不要为绕过提示删除历史目录，先检查目标是否已有会话。

长期使用前可按 `backup-recovery.md` 创建离线个人数据备份。原源码 Profile 本次不移动，
仍可作为切换前副本保留；后续新旧版本不要同时写同一份个人数据。

## 构建与验证

复用 Inno Setup 7.1.0（官方安装工具签名验证 Valid），脚本为 `packaging/Sumika.iss`：

```powershell
python -B tools/build_setup.py E:/SumikaBuild/product-candidate-20260920-l2 --compiler D:/Tools/InnoSetup/7.1.0/ISCC.exe --output E:/SumikaBuild/new-wizard-output
```

工具先验证候选文件清单，再构建到新目录，保留编译日志及 EXE 哈希，不覆盖旧安装器。
当前安装 EXE 未签署发布者代码签名；其 SHA-256 记录在旁边 `installer-report.json`。
K 版已实测安装、完整性、覆盖与嵌套拒绝和 EXE 生命周期；L 版新证据见项目交接中的
`installer_data_ux_checkpoint`。不能把 K 的证据或本机验收表述为 L 已重跑 Windows Sandbox。
