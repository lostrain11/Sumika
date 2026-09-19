# P5/P6 非 UI 扩展验收与继续入口

整体状态：进行中。用户要求完成所有非 UI 剩余项；本记录不将包装接口、单个夹具或回调实现当作整个阶段完成。

## 当前证据

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
