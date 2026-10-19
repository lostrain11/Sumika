# 网页交叉审查

## r12 网页咨询接线修复已入包（2026-10-18）

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r12`，DSH仍固定0.2.1-rc.2。Bridge/Workbench现在自动登记既有网页咨询插件并绑定真实个人授权文件；新profile仅允许原生项目登记表中确属项目的standard主会话，已有显式禁用/preset/项目白名单保留。用户总开关在发送/读取外站前实时核对，逐站授权与原生逐次发送审批仍独立生效。包内Python通过已有run_module.py进入实际产品模块，不依赖开发机PYTHONPATH。

源码21项Python/7项Node定向通过；r12包内Python+包内产品代码启动真实受管Workbench，5组检查通过：新profile自动登记/路径、关闭拒绝、审批拒绝、取消、允许一次但无站点授权时停止。7次loopback合成模型请求，0外站消息；审批服务使用合成应答器，不冒称真实网页按钮点击，实际模型质量/站点发送不由此证明。源码全量1351项、202.376秒、OK（23跳过，既有资源/弃用警告仍在）。首轮1351项有2项语音夹具目录WinError32、1项profile原子替换WinError5；3项单独复跑通过，构建完成后新E临时目录全套通过。保留两轮与定向日志；具体占用来源未定，不声称已修根因，未修改相关产品/测试来压错误。

候选60476文件库存通过，545个产品源码/登记文件SHA零差异；实际EXE4项及布局128/128通过，0横向溢出/页面错误，测试Bridge均已停止。构建复用r11经校验的同版物理DSH/依赖；源码pnpm链接的首次构建拒绝日志保留。仅文档和验收脚本import guard在构建后同步，原manifest和前后SHA保留，产品/runtime未改。候选未替换日用安装或发布。

证据：`.sumika-next/acceptance-20261018/{full-suite-review-registration.log,review-registration-sharing-focused.log,full-suite-review-registration-clean.log}`；候选父目录`{build-rc2-r12-physical.log,inventory-r12-final.json,source-identity-rc2-r12.json,matrix-r12/report.json,exe-startup-3676b3d91cbc4d7d80637e7a5c849b66/report.json,managed-review-r12/7604bc367eb340fc852949a541245c5a/report.json}`。

**操作：**「设置 → 连接与权限 → 网页咨询授权 → 启用网页咨询」，按既有控件授权站点并绑定受管页面；随后在「工作台」的已登记项目主会话提出网页交叉审查，核对原生审批中的完整发送文本。新profile首次开工作台自动登记插件，已有实例升级后需在无执行/待审批任务时正常停止并重开；关闭总开关立即阻止新的网页操作，无需重启，不承诺已发给外站的生成会被终止。原生插件被用户显式禁用时保持禁用。无需手改profile；不自动登录、绑定、发送或消耗既有授权。

用户已批准在同一个角色资源弹窗补齐背景/世界书/角色配色，代码尚待接续。定时任务旧执行入口与原生任务的整合仍待做，角色/设备/实际模型/干净机器等全项目剩余项继续核验；本轮通过不等于整体完成。下文“源码已验、r12待验”保留为本次构建过程记录，以本节结果为准。


## 网页咨询新profile接线修复（2026-10-18，源码已验、r12待验）

复用现有 `review_install.py` 原子备份安装器、`review_dsh.mjs` 原生审批工具、BrowserSkill个人授权和 `tools/run_module.py`，没有新UI或平行插件。Bridge将真实个人授权文件路径传给Workbench，在持有inactive profile lease时安装；首次安装只开放DSH原生项目登记表中确属该项目的standard主会话，动态读取会话归属，不将任意cwd视为项目授权。旧profile明确配置的禁用状态、工作preset及项目范围保留，仅刷新迁移后的产品/解释器/registry/runner路径。总开关缺失、损坏或关闭时发送/collect在审批前拒绝；状态查询/本地取消保留，逐站授权和每次原生发送审批仍需满足。包内隔离Python改走已有module runner，避免`-m`找不到产品模块。

源码21项Python与7项Node定向通过；真实受管Workbench5组检查通过（新profile自动登记与路径、关闭拒绝、审批拒绝、取消、允许一次但没有站点授权时明确拒绝）。7次本机合成模型请求，未设置任何站点授权，0外站发送。审批使用原生服务+合成应答器，不冒称用户点击；允许分支真实启动产品worker并返回无站点授权错误，未创建提交journal。证据：`.sumika-next/acceptance-20261018/managed-review/939c19d35fd243918d4e659da0fae6f2/{report,events}.json`。复现：`python -B tools/verify_web_review_managed.py`；`--product`可指定新候选，必须用该候选Python/module runner调用以验包内隔离解释器。

全量回归与r12独立构建正在进行，不将源码通过写成r11已包含修复。第一次构建因源码pnpm依赖含链接被已有构建检查拒绝（尚未生成目标目录）；改复用版本和release SHA一致的r11物理DSH运行时，未降低构建检查。已获准在现有角色资源弹窗补齐世界书/背景/主题色，后续接续实施；主线仍未完成。


用途：主 Agent 完成计划或复杂成果后，请网页模型寻找遗漏、反例和问题。反馈仅为建议，由主 Agent 核验采纳；不自动修改计划或权限。

复用 BrowserSkill 原有授权/绑定与 consultation journal。DSH 适配器为 review_dsh.mjs，独立执行入口为 python -m extensions.desktop.review_service。日用插件已备份安装，工作台启动及 settings RPC 已验证；原生工具注册和日用断线恢复已实核。

插件配置：enabled=true；projects 为明确工作目录列表；workPresets 为实际 DSH 主工作 preset ID 白名单（当前隔离验证为 standard）；root 为本仓库绝对路径；python 为解释器绝对路径；registry 为个人 browser-authorizations.json；runtimeEntry 为当前 DSH package.json。仅安装独立插件，不修改 DSH 上游。enabled=false 不注册工具。角色preset和子Agent不具备使用权。

工具：web_review_submit(site,prompt) 经原生一次审批发送完整文本；web_review_result(request_id,action) 支持 status/collect/cancel。request_id由宿主会话/项目/原生turn/step/callId产生；模型不能自填approved或跨工作会话查询。取消只取消本地跟踪，不承诺远端停止。

发送前记录UNKNOWN及历史hash基线；结果必须精确关联本次用户消息与后续唯一回答。旧记录缺少基线不能补造完成事实。未知结果只能查询，不自动重放。网站回答持久化在用户个人数据库，原历史正文不写入源仓库。

验证：43项Python测试和5项Node适配测试通过。隔离DSH真实审批取消产生 ABORTED_BEFORE_DISPATCH；新获准三站各一条交叉审查均 completed，经原生工具回读，隔离重启不重发。证据见 `.sumika-next/web-review-acceptance/live/report.json`。本次三条授权已用完，禁止再次发送。

未知请求占据原标签通道，不自动释放或重放；恢复入口位于设置→连接与权限→网页咨询授权，显式打开受管窗口/站点后选择页面绑定。登录和模型模式仍需在网站核验。

最终验收：Kimi快速与GPT思考各一次新测试已获准并完成原生回读，重启不重发，见final-live/report.json。Kimi临时线程识别已补齐；GPT空正文通过重载同一线程恢复，不重发。日用注册证据daily-registration.json、恢复证据daily-recovery.json均在.sumika-next/web-review-acceptance。带附件草稿不列为支持范围，日用模型驱动的付费执行未测试。

用户总开关：设置→连接与权限→网页咨询授权→启用网页咨询，默认关闭；旧registry无enabled字段也关闭。状态存于个人browser-authorizations.json，与站点授权同一来源。关闭保留站点授权/绑定及历史，仅允许本地状态查询和取消，不执行新网页操作。开启不替代逐站授权与每次发送审批；已发送生成不保证远端停止。DSH插件开关仅控制工具注册，不能绕过用户总开关。
