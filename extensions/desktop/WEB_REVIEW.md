# 网页交叉审查

用途：主 Agent 完成计划或复杂成果后，请网页模型寻找遗漏、反例和问题。反馈仅为建议，由主 Agent 核验采纳；不自动修改计划或权限。

复用 BrowserSkill 原有授权/绑定与 consultation journal。DSH 适配器为 review_dsh.mjs，独立执行入口为 python -m extensions.desktop.review_service。日用插件已备份安装，工作台启动及 settings RPC 已验证；原生工具注册和日用断线恢复已实核。

插件配置：enabled=true；projects 为明确工作目录列表；workPresets 为实际 DSH 主工作 preset ID 白名单（当前隔离验证为 standard）；root 为本仓库绝对路径；python 为解释器绝对路径；registry 为个人 browser-authorizations.json；runtimeEntry 为当前 DSH package.json。仅安装独立插件，不修改 DSH 上游。enabled=false 不注册工具。角色preset和子Agent不具备使用权。

工具：web_review_submit(site,prompt) 经原生一次审批发送完整文本；web_review_result(request_id,action) 支持 status/collect/cancel。request_id由宿主会话/项目/原生turn/step/callId产生；模型不能自填approved或跨工作会话查询。取消只取消本地跟踪，不承诺远端停止。

发送前记录UNKNOWN及历史hash基线；结果必须精确关联本次用户消息与后续唯一回答。旧记录缺少基线不能补造完成事实。未知结果只能查询，不自动重放。网站回答持久化在用户个人数据库，原历史正文不写入源仓库。

验证：43项Python测试和5项Node适配测试通过。隔离DSH真实审批取消产生 ABORTED_BEFORE_DISPATCH；新获准三站各一条交叉审查均 completed，经原生工具回读，隔离重启不重发。证据见 `.sumika-next/web-review-acceptance/live/report.json`。本次三条授权已用完，禁止再次发送。

未知请求占据原标签通道，不自动释放或重放；恢复入口位于设置→连接与权限→网页咨询授权，显式打开受管窗口/站点后选择页面绑定。登录和模型模式仍需在网站核验。

最终验收：Kimi快速与GPT思考各一次新测试已获准并完成原生回读，重启不重发，见final-live/report.json。Kimi临时线程识别已补齐；GPT空正文通过重载同一线程恢复，不重发。日用注册证据daily-registration.json、恢复证据daily-recovery.json均在.sumika-next/web-review-acceptance。带附件草稿不列为支持范围，日用模型驱动的付费执行未测试。

用户总开关：设置→连接与权限→网页咨询授权→启用网页咨询，默认关闭；旧registry无enabled字段也关闭。状态存于个人browser-authorizations.json，与站点授权同一来源。关闭保留站点授权/绑定及历史，仅允许本地状态查询和取消，不执行新网页操作。开启不替代逐站授权与每次发送审批；已发送生成不保证远端停止。DSH插件开关仅控制工具注册，不能绕过用户总开关。
