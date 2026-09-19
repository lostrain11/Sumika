# 一键启动（2026-09-15）

入口：桌面快捷方式 **Sumika**，或仓库根目录的 `Sumika.cmd`。

## 行为

1. 读取用户环境变量；若存在 `%LOCALAPPDATA%\Sumika\env.ps1` 则先加载（密钥放这里，仓库里不存）。
2. 若 `http://127.0.0.1:8765/api/state` 已可访问，直接复用，不重复启动。
3. 否则以**独立隐藏进程**启动桥接，最多等 14 秒确认就绪，然后打开浏览器。
4. 没有检测到 `DEEPSEEK_API_KEY` 时给出明确提示，而不是静默失败（角色对话会失败关闭）。

实测：启动耗时约 3 秒；重复双击显示“已在运行”并立即返回。

## 踩过的两个坑（值得记住）

1. **`Sumika.cmd` 里不能放中文**。cmd.exe 按系统 ANSI 代码页解析批处理，UTF-8 中文会破坏语法（实测报 `'动失败，...' is not recognized`）。批处理保持纯 ASCII，中文提示交给 PowerShell 输出。
2. **Windows PowerShell 5.1 需要带 BOM 的 UTF-8 脚本**。无 BOM 的 .ps1 会按 GBK 解析，中文变成乱码并导致语法错误（实测 `Unexpected token 'Sumika'`）。`start_sumika.ps1` 现以 UTF-8 BOM 保存；用 PowerShell 7 生成文件时 `Set-Content -Encoding utf8` **不会**自动加 BOM，需要显式 `UTF8Encoding($true)`。
3. 启动器不能把桥接脚本的输出接管道：`Start-Process -PassThru` 加输出重定向会让父进程一直等待子进程句柄。改成独立隐藏进程后立即返回。

## 密钥位置

`%LOCALAPPDATA%\Sumika\env.ps1`，内容形如：

```powershell
$env:DEEPSEEK_API_KEY = '你的密钥'
```

这是本机用户目录下的明文文件，用于免去每次手填；不需要时直接删除该文件即可，启动器会改为提示你设置环境变量。
