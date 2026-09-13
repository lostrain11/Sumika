# 项目目录清理记录

用户需求原文：项目文件夹内部也有很多东西，能否清理下，没用的删除下

- 当前分支：codex/sumika-next-dsh；清理前 Git 工作区干净。
- 将 25 个旧版或生成物根目录条目移出项目；没有删除源码、分支或历史。
- 私有恢复目录：`D:\Backups\Sumika\project-cleanup-20260913-033000`，实际内容在 `payload/`，原路径、SHA-256 和链接目标见 `manifest.json`。
- 11,861 个保留文件已逐一核对 SHA-256；3,297 个链接目标字符串保持一致，没有遍历或删除链接目标。
- 旧 Rust 构建产物：23,400 个文件，20,135,842,192 字节。永久删除被执行器策略拒绝，随后按用户要求，已单独移到 `D:/Backups/Sumika/待手动删除-旧构建产物-20260913/src-tauri-target/`，该待删除文件夹可整体手动删除。这些文件仅清点数量/大小，没有逐一哈希；本次没有释放相应磁盘空间。
- 已核对无项目相关运行进程；新版源码未引用旧目录，保留目录的链接也未指向被移出的目录。
- 保留 `.sumika-next/` 全部运行环境和验收证据、`.sumika-continuity/` 私有原文与数据库，以及新版源码、测试、工具、DSH 安装和项目文档。
- 旧 UI 资源在 `payload/frontend/`；设计源码仍可用 `git show 059d600:frontend/src/...` 查看。
- 上次兄弟工作树的恢复备份现位于 `payload/.sumika-desktop/backups/worktree-cleanup-20260912-043543/`。

## 移出的条目

- `%SystemDrive%`
- `.sumika`
- `.sumika-daily-dsh`
- `.sumika-daily-store`
- `.sumika-daily-store-mcp`
- `.sumika-daily-store-mcp2`
- `.sumika-daily-store-mcp3`
- `.sumika-daily-workspace`
- `.sumika-desktop`
- `.sumika-e2e-avatar-ui`
- `.sumika-playwright-agent`
- `.zcode`
- `artifacts`
- `backend`
- `build`
- `deprecated`
- `frontend`
- `output`
- `packages`
- `plugins`
- `src-tauri`
- `sumika_next.egg-info`
- `test-results`
- `example.txt`
- `output.txt`

## 恢复与验证

按需从 payload 恢复选定条目到原项目根目录，目标已存在时不要覆盖。链接保留原绝对目标；恢复旧环境前按 manifest 检查其目标，部分旧插件链接需要先恢复对应 plugins 目录。恢复目录可能包含凭据和私人历史，不上传 Git。

清理后 `python -B -m sumika_next.cli check` 和 `python -B -m sumika_next.cli handoff` 均成功。未执行真实模型调用或 UI 验收。当前产品阶段仍为 P4-UI，下一步继续 UI 设计。

## 20260914-070900
Moved three research HTML artifacts to $dest; recoverable, not deleted.
