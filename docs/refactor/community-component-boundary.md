# 社区分享组件边界

自动路由策略适合开源分享，但不适合把整个 Sumika 直接做成一个插件。推荐拆成
以下三个可独立复用的部分：

## `cost-routing-core`

运行时无关的纯逻辑库，负责任务契约、DAG、能力约束、推理强度维度、确定性预算
估算、验证计划和升级规则。它不读取密钥，不执行 shell，不操作浏览器/设备，
也不决定某次付费请求是否允许。

## 适配器

- `codex-skill`：把 Core 的任务协议呈现给当前 Codex；宿主是否真的支持子 Agent、
  可选模型和推理强度，由 Codex 自己证明；
- `mcp-server`：只暴露查询能力、生成计划、提交脱敏结果和读取统计；不暴露任意
  shell、密钥、Provider 启用、文件删除或设备控制；
- `sumika-adapter`：把 `model-picker/catalog/v1` 投影为 Sumika 的 advisory evidence，
  最终健康、授权、额度、隐私、付费确认和 dispatch 仍由 Sumika 完成。

## 不发布的内容

Sumika 的角色/Avatar/运行数据、Provider 凭据、Cookie、网页内容、屏幕/摄像头内容、
真实账本明细和项目完整路径不进入社区包。`model-picker` 也不作为第二个生产路由器，
只提供目录、价格、评测与历史建议。

## 当前落点

本仓库先保留 Sumika 适配器，`model-picker` 提供版本化 HTTP/MCP 投影；等两边契约
稳定并有第二个真实 Harness 适配器后，再把纯逻辑提取到独立仓库。这样社区可以先用
MCP 或 Skill 试用，而不会被 Sumika 的桌宠、Tauri 和本地存储依赖绑定。
