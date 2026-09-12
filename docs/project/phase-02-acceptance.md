# 阶段 2：DSH 发行锁定与真实能力验收

状态：**已完成 P2 验收**。固定 `@deepseek-ai/dsh@0.1.5-rc.2`；通过真实 DSH 与本地确定性模型替身执行，外部模型调用为 0。不等同于 P3 的真实模型开发效果验收。

## 实现与证据

| 范围 | 已验证结果 |
| --- | --- |
| 发行和独立布局 | rc.2、pnpm 11.19.0、冻结锁文件与摘要；独立 DSH_HOME；重复冻结安装通过 |
| 原生 Web 与认证 | HTML、注入脚本、应用脚本可访问；子进程启动 token/cookie 与 PID 归属核验；未认证和跨域写入被拒绝 |
| 会话与工作区 | 隔离 Git 项目、创建会话、实时 follow、历史 page、事件游标与结果读取 |
| 文件与测试 | write/read/edit/grep/glob；41 改为 42；真实 pwsh 相对路径读取并验证内容，写出测试结果 |
| 终端生命周期 | exit 7 正确回报；超时终止；实际写出 started 标记后取消，等待原命令期限后仍无后续写入 |
| 原生扩展 | standard preset、本地 Skills、真实子 Agent、stdio MCP echo 挑战响应；无需额外社区插件 |
| Plan | 原生命令进入；按会话和事件绑定处理 plan-review；Keep planning 保持 active，Approve 退出 |
| 恢复与取消 | 断开再连接游标一致；重启同一隔离 profile 后历史记录一致且不重放；已到达模型 HTTP 端点的请求可取消，迟到响应不写入结果、不自动重试 |
| 回归门槛 | 33 项自动化测试和连续性校验；完整组合门槛通过；新增 Web 资源检查单独复核通过 |

`phase-02-evidence.json` 保存本次验收结果、时间和本地事件产物 SHA-256。原始模型请求、事件和隔离 profile 留在被忽略的 `.sumika-next/`，不上传凭据或大体积运行数据。

复用方式：先按 `runtime/dsh/README.md` 安装冻结环境，再运行：

```powershell
.sumika-next/verify-env/Scripts/python.exe -X utf8 -B tools/verify_phase2.py
```

任一步失败即终止，不通过文档措辞或单项测试宣布发行成功。测试不会修改日用 profile。

## 已解决问题

之前的 pwsh 拒绝并非已证实的 DSH 路径缺陷。Python 3.14 `tempfile.mkdtemp()` 创建受保护、不继承父目录的 ACL；现场只有 OWNER RIGHTS、SYSTEM 和管理员完全权限，DSH 的 workspace SID 只提供写权限。该夹具与正常项目的继承 ACL 不同，受限令牌无法读取文件，PowerShell 工作目录也可能回落。

改用随机唯一目录名加普通 `mkdir` 创建真实临时项目后，相对路径读取、写入、测试和取消全部通过。未改动原有目录 ACL，未关闭 sandbox，未添加 danger-full-access。已移除未接入的 pwsh 替换插件和多余直接依赖。特殊 ACL 项目仍须单独验收。

原生 `$events/result` 和 `commands/*` 使用命名参数，区别于 `session/*` 的 request DTO；适配层集中处理，仅明确的 void 方法接受省略 value。新增负向测试确保普通会话操作不会因此接受缺失结果。

取消中的请求可记录 `assistant/attempt` 和 `step/end`，不能只等待 `turn/end`；重启后的恢复从新快照与落盘历史重建，不将旧流或取消回执视为完成证明。

## 限制与下一阶段

- P2 验证真实 Harness/工具能力及协议，不验证外部模型的开发质量、缓存成本或中等规模任务成功率。
- Web 已验证资源与后端交互协议；完整可视化点击流程、真实开发任务中的 Plan/Execute/审查体验在 P3 验收。
- 本次不声称所有第三方插件、所有 Windows ACL 布局或完整 OS 隔离已通过；沿用上游 Windows 沙箱 partial enforcement 的边界。
- 不新增日用 prompt/model 自动入口，不自动切换用户现有版本或 profile。新模型接手时从 P3 开始，P4-P7 仍未实施。

## 更新与回退

每次更新在独立候选安装/profile 中锁定版本和依赖，检查协议及插件组合，执行冻结安装和完整门槛；失败保留当前已验收组合。协议方法名集中于 DSH 适配层。回退同时恢复发行 Git 提交和对应 profile 备份，不将新格式数据原地交给旧版；步骤见 `runtime/dsh/README.md`。
