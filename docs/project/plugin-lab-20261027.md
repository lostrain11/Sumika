# 插件实验室记录（2026-10-27）

独立空 profile 验证；不写 `data-r96` 或日常用户数据。所有安装均为 CLI/`dsh plugin add`，不等同于 DSH Web 里已登录账号的 UI 安装验收。

## 安装结果

| 插件 | 版本 | 安装 | 激活/可见 | 运行时前置 |
|---|---|---|---|---|
| `dshmarket` | 1.70.2 | exit 0 | 未启动验证 | 无 |
| `dsh-pet-live2d` | 3.3.3 | exit 0 | 未启动验证 | 无 |
| `dsh-bili-scroll` | 2.1.0 | exit 0 | Plugins 页显示“dsh-bili-scroll” | Python/uv、B站登录 |
| `dsh-phone` | 0.4.1 | exit 0（Release tgz） | Plugins 页显示“肥鱼的手机” | Android 模拟器/WHPX、约 2GB |
| `dsh-fish` | 0.5.1 | exit 0（commit pin） | 未启动验证 | Python/ffmpeg、B站登录 |
| `dsh-bili-interact` | 0.0.9 | exit 0（commit pin） | 未启动验证 | 依赖 `dsh-bili-scroll`、Python |
| `@kenz1117/dsh-engram` | 0.10.0 | **exit 1** | 未激活 | pnpm 忽略 `onnxruntime-node`/`protobufjs` 构建脚本 |

目录中仍保留 `engram` 作为“记忆算法参考”，不把它算作可装。

## 环境事实

- 本机 Python 可用；`adb`、Android `emulator`、`uv`、`ffmpeg` 不在 PATH。
- `HyperVisorPresent: true`；但 Android SDK/AVD 尚未安装。
- 没有 DSH 登录账号/cookie，因此：
  - B站扫码登录未执行
  - 真实搜索/字幕/日报未执行
  - 手机 emulator 未启动
  - 只验证“安装/激活/前置提示”，不验证业务链路

## 结论

- **目录可发现**：7 个
- **安装步骤已验证**：6 个
- **已知安装失败**：1 个（engram）
- **端到端功能已验证**：0 个
- **可参考架构**：`dsh-fish`、`dsh-engram`、`dsh-pet-live2d`、`dsh-dot`（未进目录）

下一步不是继续扩目录，而是：

1. 在已登录 DSH 环境完成一次 UI 安装 + 卸载。
2. 安装 Android SDK/AVD 后验证 `phone_status`/`phone_screenshot`。
3. B站扫码后验证只读 `bili_*` 工具和日报。
4. 再决定是否接入 Sumika 的专用 DSH 任务会话。

## B站 2026-10-27 现场结果

- B站扫码登录：**成功**；`bili_credential.json` 已写入 `data-r97/.../bili-duty/`。
- Python 依赖：**就绪**（51 包，venv）。
- 手动跑一轮：**失败**，发生在 B站 工具调用前。
- 失败原因：`dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"`。
- 结果：只生成占位报告 `out/2026-10-27.md`，未挑选视频、未调用 B站 工具、无点赞/评论/关注等写操作。
- 结论：B站登录与插件安装通过；真实只读 duty 仍需 DSH 模型账号或 API Key。

## B站只读 duty 成功（2026-10-27 10:47）

- DSH 模型登录后重跑：exit 0，`今天挑到 5 条（上限 5 条）`。
- 报告：`out/2026-10-27.md`，5 个 `### BV` 条目；另有 5 份单条笔记。
- 实际读取：7 条视频（5 条入报告、2 条跳过），字幕可用，无转写。
- 写操作：`评论/私信全部没开`；日志无 `bili_touch` / `bili_post_dynamic` / `bili_send_dm` 调用。
- 已知小问题：第一次失败留下的占位报告仍位于成功报告顶部；第二次运行把真实报告追加在后面。插件输出本身未覆盖旧占位，当前不把它算作干净报告。
