# 受管 DSH 发行描述

这个目录是 Sumika 允许运行的 DSH 组合的**唯一声明处**。启动器、安装辅助脚本、
Tauri 桌面外壳和 Core 都读取同一份描述；任何一方都不再自带版本号。

## 布局

```text
dsh-release/
├── channel.json                  默认发行选择
└── releases/<id>/
    ├── release.json              单一发行描述
    └── pnpm-lock.yaml            冻结锁文件
```

`release.json` 记录：

| 字段 | 含义 |
|---|---|
| `harness.version` / `source` | DSH 版本与可核验的 npm 包摘要 |
| `harness.install` | 安装根、子目录和可执行文件相对布局 |
| `harness.signals` | 该发行对外暴露的协议事实 |
| `toolchain.lockfile_sha256` | 冻结锁文件摘要，安装后逐字节比对 |
| `install_policy` | 只用锁文件、默认不执行安装脚本 |
| `plugins[]` | 随发行提供的自有插件、内容摘要、安装方式与默认开关 |
| `verification` | 已验证证据、限制与阻断项 |

插件 `content_digest` 由 `sumika_core.agent.dsh_release` 按“相对路径 + 文件内容”
计算，是唯一实现；PowerShell 通过 `python -m sumika_core.agent.dsh_release verify`
调用同一实现，避免两侧算法漂移。

## 状态

| 状态 | 含义 |
|---|---|
| `verified-active` | 可以受管启动，是 `channel.json` 允许的默认值 |
| `verified-candidate` | 已描述但未获准日用；只在显式选择时用于隔离验证 |
| `blocked` | 已描述且记录阻断原因，任何受管启动都必须拒绝 |

## 发行身份与安装证据

- `distribution_id` 由发行描述（版本、包摘要、锁文件摘要、插件内容摘要）推导，
  与安装路径无关；受管启动的 `RuntimeBinding.distribution_id` 取自它，替换了
  早先的 `legacy-unlocked-<版本+启动器摘要>`。
- `install_evidence` 描述**这一棵**安装树：
  - `frozen-lockfile-verified`：`node_modules/.pnpm/lock.yaml` 与声明逐字节一致；
  - `mismatch`：该树不是由冻结解析产生的；
  - `declared-unverified`：没有可对照的安装锁文件。
- 安装证据只作为观察记录，不参与启动身份等值判断：启动与停止之间重装不应把
  已验证的监听进程判成陌生进程。

## 选择与切换

```powershell
# 读取当前默认发行
python -m sumika_core.agent.dsh_release show

# 在隔离目录里准备候选发行（显式允许候选）
pwsh -File tools/setup-dsh.ps1 -Version 0.1.5-rc.1 -AllowCandidate -InstallDir 'D:\Caches\sumika-h02-install\0.1.5-rc.1'

# 校验自有插件内容仍与描述一致
python -m sumika_core.agent.dsh_release verify
```

`SUMIKA_DSH_RELEASE` 选择另一份已描述发行，`SUMIKA_DSH_RELEASE_ROOT` 指向另一份
描述目录，`SUMIKA_DSH_INSTALL_ROOT` 允许把安装根换到别处。三者都只影响本次
进程，都不会改写日用 profile、安装目录或登录档案。

切换日用发行是一次受审改动：先完成隔离验证，再改 `channel.json` 的
`default_release`。候选不会被自动提升。

## 前提与限制

- 描述必须在运行时可见：桌面外壳按仓库根解析 `dsh-release/`，打包发行版需把该目录
  随应用提供，或由 `SUMIKA_DSH_RELEASE_ROOT` 指向它。描述缺失时受管启动明确失败，
  不会退回脚本里的旧版本号。
- 冻结锁文件只固定解析结果，不构成对上游包的审计背书；`harness.source` 记录 npm
  摘要，`commit` 与 `commit_evidence` 分开保存以便区分"声明"与"已从产物重算"。
- 安装证据只描述当前这棵树；它既不是启动授权，也不代表模型质量或渠道可用性。
