# 免费资源发现与每日权益

本阶段扩展质量路由的观察层。按用户 2026-09-08 的补充，发现范围不限于已注册或已登录的站点；RSS 是资讯入口，官方目录和说明是核实依据，领取使用逐站适配的固定流程。

## 入口与行为

设置及能力页的模型证据区域新增折叠的“免费资源与签到”，分“模型与额度”“资讯线索”。页面读取状态不检测浏览器、不发起刷新或签到；手动刷新、后台发现、浏览器选择与自动签到各有明确控件。添加页面模块不等于启用后台流程。

服务实现位于 `backend/src/sumika_core/benefits.py`，公开来源位于 `benefit_sources.py`，魔搭固定工作流位于 `integrations/modelscope_benefits.py`。不新增模型调用、HTTP 服务、数据库或凭据存储；也不新建消耗 Codex 模型调用的定时任务。

RPC：

| 方法 | 输入与用途 |
| --- | --- |
| `benefits.status` | 空参数，只读快照 |
| `benefits.browsers` | 空参数，显式检测 BrowserSkill 浏览器，只返回 ID/浏览器名称 |
| `benefits.configure` | `enabled`、`checkin_enabled`、`browser_instance_id`；严格拒绝未知字段 |
| `benefits.refresh` | 空参数，异步运行固定公开来源采集 |
| `benefits.checkin` | 空参数，异步核验选定浏览器的魔搭每日权益 |

两项执行入口单飞，忙时明确拒绝，不静默吞掉请求。前端有界轮询状态，切页后停止。关闭后台发现同时关闭自动签到并撤销在途签到；进程退出先停止该服务，再退出浏览器运行时。正常网络请求有超时、响应大小和固定来源限制；关闭等待已发出的有限请求收尾，不再启动下一来源。

## 发现与证据

- 公开 RSS/Atom 与中英文搜索源覆盖未注册渠道；标题必须同时匹配模型/API主题与免费/额度权益主题。泛 AI 工具、百科、影视、游戏不是模型额度资讯。
- 新闻链接仅作为线索，不自动访问其落地页，不执行其中的说明，不作为可信路由证据。
- 官方价格和模型目录逐源核验。免费单价不代表账号拥有额度，未知有效期不补成观察时间加一天。
- 各来源独立 TTL 和失败退避，不以某源成功清除其他源的失败。失败保留历史观察并标为陈旧。
- 同一来源重复条目去重；历史条目有界保存。RSS 滚出窗口不等于权益撤回，只有完整官方目录的缺项才标记撤回。
- 不用模型进行分类、刷新或签到。不读取 API Key、Cookie、浏览器内部状态，不注册、登录、充值、购买或放宽权限。
- 使用现有网络代理配置，不能人为禁用正常代理导致公开来源误报不可用。仍拒绝源重定向，不跟随资讯链接。

新发现模型和活动只进入此观察列表，不自动注册 Provider 或加入可执行路由池。质量评测、账户适用范围、余额确认及付费边界继续由原 ModelPolicy 控制；没有修改主模型、角色或其他 Provider。

## 魔搭固定工作流

现阶段只对魔搭实现自动每日访问核验。需要已有 `modelscope-free-candidates` Profile、手动登录过的 BrowserSkill 浏览器和显式浏览器绑定；保存当前 `provider_account_revision`，换 Key/端点或浏览器后旧授权失效。该绑定用于防止使用旧授权，**不声称网页登录账户和 API Key 属于同一账户**，因此不会把观察余额直接加入资源抵扣池。

每个北京时间自然日最多自动核验一次。新建指定浏览器的无焦点 Agent Window，只导航 `https://modelscope.cn/magicube/usage`，仅选择“发放记录”，读取明确可见的余额、发放日期、数量和显示有效期。正常已登录访问可能触发网站的每日发放，不额外点击通用“领取”。当天记录已经存在时只核验，成功后当日重复请求不再访问浏览器。

登录过期、验证码、用户中断、DOM变化或结果不明均停止，等待用户处理后手动重试；不会自动登录或重复提交。始终关闭本次创建的会话，不关闭用户已有窗口。页面仅显示“有效期1天”，精确到期时间仍为 `null`。

## 持久化与复用

数据独立保存在所选数据目录的 `benefits/state.json`，不写入模型刷新共享状态。原子写入，状态锁与执行锁分开；状态锁短暂竞争只重试落盘，不重放浏览器。写入按实际 UTF-8 字节限额裁剪，损坏文件保留并停止该模块，不覆盖修复。换绑定清除对应旧签到投影；失败不把历史额度当作新鲜额度。

不建立 Windows 系统常驻任务；只在 Sumika 运行期间低频维护，关闭期间不联网，启动后检查到期来源。全新安装默认关闭，本实例的开启以本次执行证据为准。

无模型 CLI 使用同一个服务，读取现有 SQLite 时以只读模式打开：

```powershell
python -B tools/manage_free_benefits.py status --data-dir .sumika-desktop
python -B tools/manage_free_benefits.py refresh --data-dir .sumika-desktop
python -B tools/manage_free_benefits.py configure --data-dir .sumika-desktop --enable-discovery
python -B tools/manage_free_benefits.py configure --data-dir .sumika-desktop --enable-checkin --browser <明确的浏览器ID>
python -B tools/manage_free_benefits.py checkin --data-dir .sumika-desktop
python -B tools/manage_free_benefits.py configure --data-dir .sumika-desktop --disable
```

`--report` 保存无秘密快照，已有报告拒绝覆盖。`run-due` 只执行已经开启且到期的流程，不是额外的系统调度器。

## 验收与故障记录

2026-09-08 魔搭真实自动工作流已通过：当日登录发放200、阿里云绑定50，余额242；不虚报 Agent 额外领取。`benefits-checkin-20260908-v3.json` 位于 `D:\Caches\sumika-free-catalog\`。初次兼容失败与修复报告保留为 v1/v2：官方 SPA 自动添加 query，旧读取器以 query 非空误报 `wrong-page`；修复为固定导航、origin/path/hash 和 DOM校验，不读取或输出 query 内容。加载也采用有界等待，不能把加载中空白页直接判为错误。

最终12个来源中10个实采成功：Bing三项搜索RSS、V2EX社区Feed、OpenRouter、硅基流动、讯飞及Cerebras/Cloudflare/Gemini官方说明。Bing/V2EX该次没有符合“模型/API＋明确免费福利”条件的资讯；不把字典、游戏、个人额度耗尽故障当作福利。Groq未取得可自动解析的充分免费证据，LINUX DO不可用，分别保留失败状态。Bing使用已核对的`www.bing.com/search`规范入口，采集器不自动跟随任意重定向。

最终23项观察中，20项为原渠道型号免费声明，3项为新渠道活动：Cloudflare每日10,000 Neurons；Gemini免费层（具体型号/地区/账户条件另查）；Cerebras验证支付方式后赠$5、发放后30天失效。后者不是无条件免费，不自动绑定支付方式。账户发放时间未知，所有这些公开观察的账户级`expires_at`仍为`null`。最终报告`benefits-discovery-20260908-final.json`；v1/v2中的26条初始解析噪声已从本轮索引清除，诊断报告保留。日用SQLite SHA256始终相同，原Provider与角色未修改。

本实例已通过同一配置服务保存后台发现和魔搭自动签到；新安装仍默认关闭。重启正常Sumika后生效；隔离预览`http://127.0.0.1:8882/`使用无凭据的观察副本、自动任务关闭，避免两个实例同时维护账号。截图位于`D:\Caches\sumika-benefits-ui-20260908-final\`。

后端测试覆盖离线默认、来源隔离、陈旧证据、Feed滚动、进程单飞、配置撤销、跨实例撤销、绑定竞态、落盘竞争、容量限制与关闭。前端测试覆盖转义、公开证据与账户余额区分、状态轮询、切页、键盘焦点和明确配置；浏览器在1440×900、1280×800、390×844下验收。具体最终条数和真实发现结果同步到当前执行记录。

验收：后端全量858项通过后，最终相关109项（来源48、服务/RPC29、浏览器适配32）通过；35项前端专项、11项DOM和3项浏览器集成通过，生产构建通过。全量前端45/46，已有`capability-layout.test.js`旧文案断言失败，与本次功能无关，未修改。实际维护线程启动/停止和重启当日不重复、到期前不重复写快照均有离线回归。

后续需要逐站增加领取适配器和显式账户授权、评测及正式路由准入。当前不能宣称任意新站可自动注册、自动领完或自动投入日用模型路由。
