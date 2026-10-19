# P5/P6 非 UI 扩展验收与继续入口

## r11 主线治理与管理入口补验（2026-10-18）

继续使用`candidate-rc2-r11`，本轮只扩充现有维护验收工具，没有产品UI、上游或运行时变更，不为工具快照变化重打全包。包内Python+包内模块启动隔离真实Bridge/SQLite，真实Edge点击已有控件：记忆策略5项、记忆治理17项、行为/模式27项、定时任务7项、模块实现/排序/移除/重新添加8项通过，全部0页面错误。角色列表发现以及行为部分API使用夹具，报告保留边界；记忆/关系治理请求实际落库，5次本机合成对话验证开关，不证明实际模型质量。没有用户数据修改、真实设备采集或外部模型调用。

记忆治理现覆盖：手动事实、提议确认/忽略、JSON v5下载、重置取消不落备份、跨角色恢复拒绝、重置前备份及保留角色卡基线、同角色恢复事实/关系/提议状态、遗忘后重开弹窗；已有纠正/版本冲突/关系逐条身份检查保留。已查看`memory-dialog.png`，现有弹窗内容可读、底部可滚动。初次扩充脚本因fixture参数/提议证据不完整和误把重置预期设为零条而失败，均纠正测试，不改产品适应错误预期；失败报告保留。

真实候选EXE个人目录迁移通过：无认证/无确认拒绝，原目录保留、快照核验、同端口重新启动，最后请求关闭测试服务。模块移除取消不改变登记，移除后刷新不被bootstrap自动补回，重新添加默认停用。

证据位于`E:/SumikaBuild/acceptance-20261017-current/`：`r11-verify_memory_policy_ui/report.json`、`r11-memory-governance-expanded-r4/report.json`、`r11-verify_companion_profiles_ui/report.json`、`r11-verify_schedule_ui/report.json`、`r11-module-lifecycle/report.json`、`data-migration-6f5fcd8c5711473b94411c706ad5e74e/report.json`。工具仍从工作区运行、产品导入路径为r11，不能把候选包内旧维护脚本称为已同步。

主线仍存在产品缺口：R-072背景设定/世界书独立编辑与角色主题色消费没有实现；R-071的2D/语音/场景文件绑定不等于真实渲染/克隆/场景消费。设计稿只有“角色卡·世界书”预留卡，已询问用户是否在既有角色资源弹窗补齐，依赖UI决定的实现待答，其余工作继续。定时原生执行、候选网页咨询注册/恢复、实际模型/设备/站点及干净机器仍逐项验，整体不标完成。


## 当前候选 r11：原生截图翻译 Skill 与 DSH 新版诊断（2026-10-18）

路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r11`；DSH固定`0.2.1-rc.2`。2026-10-18再次实时查询官方npm，最新发布与`next`均为此版；较旧`latest`不可用于降级。源码runtime的4项发行SHA一致。

工作台启动时将一次性截图翻译Skill发布到受管profile，直接复用原生filesystem发现、当前能力库/OCR模块服务和当前工作模型；不新增界面或模型路由。同名用户Skill不覆盖。新版DSH工具结果的message级状态与callId由独立诊断适配器兼容，冲突ID不关联，不导出正文。网页咨询已有submit/result工具继续复用。

r11库存60473文件、543个源码/登记文件SHA一致；真实原生Skill加载、禁用拒绝与Windows OCR文字进入工作模型上下文三项通过，6次本机模型夹具调用、0外部调用。EXE首次/复用/外来端口拒绝/认证关停4项及布局128/128通过，0横溢出/pageerror。网页咨询本机guard/snapshot、原生拒绝和取消检查通过，worker未执行、0外站发送。114项定向及diagnostics/skill12项通过。

全量回归首轮1349项、23跳过，profile记录原子替换出现1项WinError5错误；单独3项复跑通过。详细复验在751项因语音夹具临时目录WinError32清理失败停止；最终在全新E盘临时目录、无原生沙箱验收并发下全量1349项、199.815秒、OK（23跳过），退出0；仍有既有资源/弃用警告。前两轮WinError5/32及单独复跑记录保留，不确定原因未冒充已定位，未为通过测试更改产品或降低沙箱限制。证据：`.sumika-next/acceptance-20261018/full-suite-screenshot-review-isolated.log`。原生截图测试使用E盘临时目录时触发上游沙箱temp grant错误；默认临时目录复核通过，失败证据保留，无上游或沙箱绕过改动。

证据：项目`.sumika-next/acceptance-20261018/{dsh-latest-check.json,screenshot-skill-r11-default-temp/c8b1e283d9b548c39dfb702a0de8d806/report.json,full-suite-screenshot-review.log,full-suite-screenshot-review-diagnostic.log,runtime-ownership-rerun.log}`；原生拒绝`.sumika-next/web-review-native-dc4f302bf04f46ccab504a9e3fc268c8/report.json`，取消`.sumika-next/web-review-native-a8bcd255ca664ad88f112f2ae3e9b109/report.json`；候选父目录`{build-rc2-r11.log,source-identity-rc2-r11.json,matrix-r11/report.json,exe-startup-2dab462f46a34719a73708c00eb3c5cf/report.json}`。

前端使用：能力 → 启用OCR / 截屏翻译；工作台 → 现有项目/会话 → 提供图片绝对路径 → 输入“使用 sumika-screenshot-translation 翻译为简体中文，先列原文与不确定处”；按原生权限审批，在当前对话查看结果。已运行DSH须空闲时重启才能登记新Skill，不自动重启日用实例。云工作模型会接收识别文字。LFM主力端点当前不可用，实际翻译质量未测；不把本机确定性夹具当质量结论。实时游戏翻译/叠层、长期愿景和提示词优化仍暂缓。未部署发布，其他历史深度证据保留原版本，整体仍未完成。


## 此前候选 r10：桌面动作预检与未知结果修复（2026-10-18）

路径：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r10`；DSH固定`0.2.1-rc.2`。既有`desktop/act`服务现接入授权动作编排器，完整传递文本、按键、控件定位与快照；无效请求在动作前拒绝。原生变更尝试或动作后检查失败返回`unknown`并禁止自动重试。静态图片OCR即使匹配，也不冒充动作后的新状态；可信宿主新图回调仍需另行采集授权，未新增UI或自动截屏。

源码定向16项、全量1345项（262.983秒，23跳过）通过，仍有既有资源/弃用警告。包内解释器与包内维护工具通过7项真实隐藏窗口服务检查：禁用/未批准/缺少验证参数/快照过期零改动、正常文本输入、静态OCR匹配不证明新状态、动作后OCR失败保留已执行未知。测试初版缺少禁止激活窗口样式导致前台断言失败，已加NOACTIVATE及隐藏解释器启动；失败报告保留，最终前台不变、worker退出。工具改动已同步候选，原manifest及前后SHA保留，最终库存60470文件、540个源码/登记文件SHA一致。EXE4项及布局128/128通过，无页面错误/横溢出。

证据：`.sumika-next/acceptance-20261018/owned-uia-r10-final/bee6fa3b843e417cbb055d38f55e50c2/report.json`、项目`.sumika-next/acceptance-20261018/full-suite-desktop.log`、候选父目录`{inventory-r10-final.json,source-identity-rc2-r10.json,matrix-r10/report.json,exe-startup-fdf605b6b07948f3b4de5e428c96073a/report.json}`。本轮不采用户画面、不向用户应用输入、不调用外部模型；未部署发布。其他旧候选深度功能证据保留原版本，不自动视作r10已全部复验。整体目标仍进行中。


## 当前候选 r9：文件OCR与实现切换补齐（2026-10-18）

当前内部候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r9`，DSH仍为最新发布的`0.2.1-rc.2`。复用伴学WinRT识别器补齐通用文件Windows OCR，修复RapidOCR隔离环境误判、旧包导入/返回格式、RapidOCR-json数组解析和同能力多实现启动覆盖问题，无新增UI。

源码33项定向与全量1336项（304.704秒，23跳过）通过；首次C盘临时目录低于1GiB导致76容量保护错误，换E盘临时目录后通过，保留首次日志且不降低保护阈值。包内真实中英文文件OCR、像素坐标、禁用/未安装语言/400万像素上限拒绝通过；「能力 → 管理模块 → ocr → 实现 → 应用实现」真实Bridge保存/刷新通过、无页面错误。切换实现不会开启禁用模块，同实现保留选项、不同实现使用自身选项。需启用能力时仍用已有OCR卡片开关。

r9最终库存60470文件、540个产品源码/登记文件SHA一致，EXE首次/复用/外来端口拒绝/认证关停4项和布局128/128通过。构建时OCR说明文档推进，已单独同步并记录前后SHA，原manifest保留，最终全库存复验通过；产品代码与运行时未二次修改。候选依赖、旧审批/提问/行为/Office深度测试保留原版本证据归属，不自动算作r9逐项重测。

证据：项目`.sumika-next/acceptance-20261018/{full-suite-e-temp.log,ocr-provider-ui-r9/report.json,windows-file-ocr-r9/0488aac752b74668858d0fc94f2e7fcd/report.json}`；候选父目录`{inventory-r9-final.json,source-identity-rc2-r9.json,matrix-r9/report.json,exe-startup-45187dac9a1942b2bc29ff78d9fc784e/report.json}`。浏览器截图已检查，测试Bridge已停止。未采集用户设备、未调用外部模型、未部署发布；整体任务仍进行中。


## 2026-10-17：结构化文件、视觉与r5原生接线补验

复用已启用sumika-office独立库环境、LibreOffice26.2.6、`extensions/office/render.py`及原生Skill验收；`tools/verify_office_complex.py`是扩充合成验收，未另建编辑器或修改产品。Word编辑保留粗/斜体、页眉页脚、表格、分页；Excel跨表SUMIF/SUM/IF与日期经真实重算得到90/105/超预算，图表和冻结窗格保留；PPT编辑保留表格、图表、讲者备注及第二页。三类各2页PDF，6张PNG逐页查看，无裁切/重叠/空白，源文件SHA不变。中文标题PDF文字提取顺序不佳，未删除断言，改用既有RapidOCR核对实际像素并人工审阅。证据`.sumika-next/acceptance-20261017/office-complex-final/report.json`。

r5真实DSH/Skill/原生终端四类文件操作及禁用无执行通过：`.sumika-next/p5-office-e53a72506b0543bc88df9f2656b5777c/report.json`，5次本机合成模型调用、0外部请求。Office库仍使用明确的host独立环境，不证明干净机器依赖完整。修复旧验收结果结构断言、物理包ACL脚本发现；生成工作目录Win32 5由上游诊断脚本仅修复该测试目录后通过。7项Office扩展测试通过，无产品或UI改动。

P5-1仍partial：自然语言自主任务质量、干净机器及任意复杂OOXML保真不在本次完成范围。旧文后面的“未视觉/未重算”是早期快照，不能覆盖本节证据。当前维护验收脚本超出r5构建时工具快照，不为纯工具更新重复复制全包。

复现：`python -X utf8 -B .agents/skills/sumika-office/scripts/run.py exec tools/verify_office_complex.py --soffice D:/Tools/LibreOffice/26.2.6/program/soffice.exe --out <不存在的新目录>`；原生复验设置`SUMIKA_TEST_CANDIDATE`后运行`python -X utf8 -B tools/verify_phase5_office.py --repair-fixture-acl`（只处理生成测试目录）。


整体状态：进行中。用户要求完成所有非 UI 剩余项；本记录不将包装接口、单个夹具或回调实现当作整个阶段完成。

## 当前状态入口（2026-10-17）

下表是早期非UI阶段快照，**不代表当前未实现清单**。现角色模型/资源/记忆、模块管理、定时提醒、语音陪学及行为管理已有前端接线。当前逐功能入口与真实依赖限制见 [功能操作验收清单](feature-usage-and-acceptance.md)，长期记忆治理见 [最新记忆验收](acceptance-20261017-memory.md)，运行时与候选见 [DSH升级验收](dsh-upgrade-20261017.md)。保留早期记录用于追溯，不把后续已实现项重复列为待施工。

## 早期证据快照

| 能力 | 已实现/已验证 | 尚未完成 |
| --- | --- | --- |
| 办公文件 | 原有四类文件 Skill 真实 DSH 复验通过；LibreOffice 26.2.6 独立展开、DOCX/PPTX/XLSX 转 PDF，公式重算结果 7 | PDF 视觉审阅、复杂文件任务质量 |
| OCR | RapidOCR-json 真实合成图片识别通过 | 中文屏幕实景、翻译 provider 实装；translation.py 仅显式回调组合 |
| 桌面控制 | Pywinauto UIA 枚举、PID/句柄绑定、隐藏自建窗口编辑回读通过；提供焦点/快捷键/窗口动作 | 各动作真实验收、取消中的动作边界、原生 DSH 调用闭环 |
| 能力模块 | SQLite 排序、切换、移除、禁用测试通过；desktop.service CLI 已提供 | 统一设置 UI（本次不做）；尚未验证所有 provider CLI |
| 定时任务 | once/daily/weekly UTC 到期计算，receipt 持久化，UNKNOWN 不重放，提醒与执行分离 | 原生 Harness 定时 tick/通知/dispatch 接线、取消与人工恢复入口；目前无后台自动执行 |
| 网页咨询 | 复用 Playwright BrowserContext，12 页真实隔离 Chromium 测试，无外网请求，读取新增响应而非旧答案 | 真实站点登录/页面适配、流式完成判断、嵌入客户端展示；不声明支持所有网站 |
| 角色与世界书 | 工作/角色模型分离、关键词世界书、主题色格式、作用域记忆/关系编辑/重置 CLI | 真实角色模型调用、自动上下文注入宿主；当前返回配置，不会自行调用模型 |
| 角色资源 | ZIP 路径、重复、体积、链接校验；sampleA VRM 容器元信息已验证 | 2D/3D 渲染属于 UI；用户安和昴 VRM 尚未定位/迁移，目前仅已验证角色卡 |
| 长期记忆 | 原文事实、fact_key、关系备份、事务恢复；FastEmbed+BGE 本地混合检索 13/14，关键词 8/14；真实 DSH 原生终端调用通过 | 长程真实中文数据、多模型/多 provider 对照；不能宣称效果最佳，过敏问题改写仍漏召回 |
| 语音 | SAPI 中文文件合成→Vosk 中文离线识别真实闭环，测试句正确识别 | 实时麦克风/播放/打断/角色音色模型；当前只有文件音频 |
| 感知 | OpenCV 单帧、sounddevice 限时音频适配，默认禁用、权限边界测试 | 真实授权设备采集、持续会话取消；未读取摄像头或麦克风 |

## 可复用入口

- `python -m extensions.roles.service --config <JSON> --request <JSON>`：配置包含 role_dir、database、user_id、project_id、work_model、role_model、enabled；memory_provider 为 embedded 或 semantic，后者必须配置本地 embedding_cache。请求形如 `{"operation":"context","data":{"user_content":"原文","mode":"work"}}`。操作支持 remember/search/relations/relate/edit_relation/delete_relation/forget/reset_to_card/export/restore。
- `python -m extensions.desktop.service --store <SQLite> --request <JSON>`：capability/operation/arguments 三字段请求。通过原生 Harness 工具审批调用；JSON 中的 approved 只是函数护栏，不是可信授权凭证或沙箱。
- 当前本地模块配置在 `.sumika-next/capabilities.sqlite3`，摄像头/麦克风禁用，已有用户配置不覆盖。
- desktop 环境 `.sumika-next/desktop-env`；memory 环境 `.sumika-next/memory-env`；office 环境 `.sumika-next/office-env`；Playwright 验收 `.sumika-next/verify-env`，浏览器缓存 `D:/Caches/playwright`。

## 开源复用

复用 FastEmbed 0.8.0 / BAAI bge-small-zh-v1.5（已下载，仅本地推理）、pywinauto 0.6.9、PyWinCtl 0.4.1、PyAutoGUI 0.9.54、Vosk 0.3.45、sounddevice 0.5.3、OpenCV 4.13.0.92。独立依赖清单在 extensions/desktop/requirements.lock 和 extensions/memory/requirements.lock，后者是现有环境快照，包含历史候选依赖，不是最小发行依赖。

Vosk 模型来源 `https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip`；SHA-256 `3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba`。本地模型不进入源码；发布前需保留各上游许可。

LibreOffice MSI 来自 Document Foundation 官方 26.2.6 地址，Authenticode 验证 Valid；行政展开到 `D:/Tools/LibreOffice/26.2.6`，无全局文件关联修改。转换使用独立临时 profile。

## 验证与回退

独立脚本：verify_ocr_local.py、verify_desktop_owned_window.py、verify_consultation_backend.py、verify_office_render.py、verify_role_service_dsh.py、evaluate_memory_quality.py。详细结果见同目录 *evidence.json。最新完整测试运行 146 项：145 通过、1 跳过；6 项角色 Node 测试通过。wheel 构建和项目外解包导入/sampleA 完整性验证通过。

新配置可禁用或切回 embedded；语义向量按模型摘要存储，原始事实仍在原数据库。备份 v3 包含事实、关系、来源事件 ID 和不可检索的模型提案；兼容 v2 与旧列表导入。恢复先校验，事务失败回滚，不自动重放未知动作。UI 设计文件由其他模型修改，未纳入本轮改动范围。

## 已确认的排障经验

Windows Python 3.14 tempfile.mkdtemp 创建仅 SYSTEM/Administrators/OWNER RIGHTS 可读的目录。DSH 的受限执行账户读取其中脚本会被拒绝。原有办公测试用普通 Path.mkdir 继承工作区 ACL 可通过。role-service 测试改为 UUID 命名的普通独立工作区后通过；未提高 DSH 沙箱权限。私有真实用户数据继续保持保护，不能为通过测试批量放宽权限。

下一步按表中非 UI 未完成项继续；不得将阶段设为 complete。

角色卡正式入口：`python -m extensions.roles.roles import-card <V2/V3 JSON> --store <用户目录> --id <角色ID>`。安和昴原卡在隔离临时目录复验通过：9 项世界书、原文字节一致、校验成功；既有用户导入目录未覆盖。

独立角色模型：原生 preset + agent/request 适配已通过真实本地 DSH 验收，工作默认模型不变；见 role-model-evidence.json 和 extension-lifecycle.md。日用 profile 未自动启用，自动记忆写入仍未完成。

明确记忆指令自动写入已通过真实DSH跨会话/重启/独立开关验收（role-plugin-evidence.json）；普通聊天自动提炼、模型提案确认与长程质量仍未完成。
本地记忆质量回归已更新：关键词8/14，SemanticMemory混合检索13/14；作用域隔离和事实更新均通过。该数据集为Sumika内部回归，不是AML榜单或最佳provider证明。

SemanticMemory restore/reset 已按作用域清理向量缓存，恢复后不会复用旧文本 embedding；147项测试（146通过、1跳过）。

桌面UIA授权：act 支持执行前窗口树快照哈希绑定，变化时拒绝；执行后返回 verification_hash。149项测试（148通过、1跳过）。OCR辅助核验仍待接入。

网页咨询状态机已补强：提交返回 request_id；完成、超时未知、取消分离，未知不自动重试。150项测试（149通过、1跳过）。

实时语音协调层已完成：provider中立状态机及取消/失败边界，152项测试（151通过、1跳过）；真实录音、播放和DSH接线仍待验收。

桌面OCR结果核验层已加入：verify_text 返回 verified/unknown，OCR不匹配或不确定时不报告成功；153项测试（152通过、1跳过）。

网页咨询：响应需跨 settle_ms 两次稳定观察才标记 completed，持续变化返回 unknown；本地Chromium 12页真实接线复验通过。

桌面授权操作编排层已加入：快照绑定、UIA执行、OCR后验和unknown边界；155项测试（154通过、1跳过）。

BrowserSkill适配层已加入：状态、命名Profile、站点read/send授权记录；默认不启动bsk、不转发网页内容；157项测试（156通过、1跳过）。

BrowserSkill定位已明确为客户端默认随包后端；当前仅完成适配边界与授权登记，真实安装/扩展/Profile连接仍未验收。

BrowserSkill 0.1.11 已从本机安装复用并校验：安装包SHA-256 041785147342A704FD576470E63307880043A15AD52E0553F12E6DCF360CCF74，bsk status真实返回protocol 1.1，检测到Edge扩展 0.2.1 连接；尚未登录站点或建立命名Profile会话。

BrowserSkill已复制到 runtime/browserskill/bsk.exe，发布包可内置固定版本；SHA-256 5AEFCA2EE990FE54DE387894D23BCB0E0B21CFB98D59FA0D7700D5AC63F72C2E，版本0.1.11。

BrowserSkill适配器现支持显式 session start/list/stop；不会自动启动。158项测试（157通过、1跳过），本机0.1.11 daemon协议1.1状态探测通过。

BrowserSkill咨询桥接层已加入：read/send分权、命名session复用、真实CLI导航和输入调用；159项测试（158通过、1跳过）。真实登录Profile与回复读取仍待用户授权后验收。

BrowserSkill读取侧增加受授权observe与输出预算；无效观察返回unknown，不持久化页面原文。


## BrowserSkill桥接当前边界修正

以本节覆盖此前“桥接完成”的宽泛描述：send 仅调用 fill，不点击提交；observe 返回页面观察，不是正式答案提取。profile 字段目前只是授权登记元数据，未实现浏览器配置文件管理；BrowserSkill CLI没有profile子命令。真实登录不是完成本地桥接测试的前置条件。

新增同origin校验（scheme/IDNA主机/端口）、显式Agent tab_id绑定及操作前后tab来源核对；拒绝用户窗口标签页和跨域重定向结果。CLI超时/进程异常不自动重试，不回显含提示词的命令异常。observe增加序列化结果大小门槛，CLI max-tokens仍仅是软预算，进程输出尚未实现读取时硬限制。

验证：6项桥接行为测试通过，覆盖跨域/端口/用户窗口拒绝、固定tab、重定向、检查后页面变化及fill不冒充提交。未访问真实账号。检查与操作之间仍有TOCTOU窗口：两次CLI调用不等于执行端原子授权；Profile绑定、授权撤销、可靠提交/完成标记及后台宿主仍未完成。不允许据此宣称网页咨询已实际可用。

UI首批接入：D方案方向D原型快照已放入 ui/prototype-d，资产自包含；后端尚未接线，165项测试（164通过、1跳过）。

长期记忆治理评测扩展：关键词/语义provider均通过遗忘后拒绝召回和跨作用域清洁检查；170项测试（169通过、1跳过）。
