# 行为子记忆实施规格

版本：2026-10-12 v1；执行：ZCode / GLM5.3flash；状态：方案归档，尚未实施。执行顺序和共同契约见repair-and-acceptance-plan.md。本文件对应P08～P13、P16；基线P01/P02必须先通过。

## 1. 需求与边界

R-125此前提过通用行为、进度、自动识屏，但延期。此次用户要求丰富本地日常特征、操作意图和习惯闭环。已确认：跟随授权前台；细粒度键鼠特征；按需模型；数据长期保存不定期删；可单独选盘；启动恢复明确保存的许可；通用共享/角色互动隔离；询问10分钟1次、日6次。

新extensions/behavior补缺失领域层，复用现有contracts、reading_behavior、coordinator、CancellationToken、个人目录/lease/备份，不把UsageStore当日志库，不把原始行为塞长期事实记忆。行为记录不代表用户已学会、困惑或具备某种人格。

信息分四层：observed客观特征；inferred当前解释；user_confirmed本次原话；derived有出处统计模式。一次确认只确认这次，模型重复自己的推测不能作为训练标签。

## 2. 采集契约与Windows实现（P10/P11）

### 2.1 持久许可与运行身份

主数据保存settings/permission revision、前台scope、排除应用、recording/use_memory/questions各开关、startup_resume、paused。新规则明确保存的许可可随Sumika启动，旧一次性同意不迁移。暂停持久化，paused或revoked重启不恢复。新进程重绑当前前台、新session/epoch，不复活旧HWND/PID/grant。无OS自启、无自动mic/app audio/TTS。

排除至少含Sumika/桌宠/worker/捕获宿主、用户排除应用；锁屏、安全桌面、最小化目标不可用。未知许可/损坏配置/目录丢失失败关闭，不能改存其他位置。状态入口持续可见，权限页和既有详情可暂停/恢复，不新顶栏导航。

### 2.2 Raw Input薄适配

建议固定模块：input_features.py纯函数归类；windows_input_worker.py隐藏Win32消息循环；input_process.py父端监督。采用安装版desktop Python，已核实pywin32=312/pywinauto=0.6.9及相关Win32 API可用；未真实采集键鼠，后续必须实际验收。

RegisterRawInputDevices注册键鼠Generic Desktop+RIDEV_INPUTSINK，处理WM_INPUT；不设置NOLEGACY/CAPTUREMOUSE/NOHOTKEYS，不hook吞键、不SendInput、不抢焦点。不ToUnicode/ToAscii、不剪贴板/IME正文、不读UIA Name/Text/Value。

原始VK/scan code/设备句柄只瞬时归类，不IPC/日志/数据库。前台使用SetWinEventHook OUTOFCONTEXT通知，绑定HWND/PID/process_creation；缓存失效后核验。切窗立即封口frame、清modifier/typing/drag；时间早于新epoch的积压数据丢弃并记质量缺口。

焦点探针异步只查IsPassword/控制类型；每秒最多4次、200ms超时，不阻塞输入回调。password细粒度全暂停；unknown仅粗略活动/滚动量，标privacy_context_unknown。无UIA游戏可能降级；不私自把未知当安全。Raw Input不证明全部合成/远程输入可捕获，也不证明快捷操作已成功执行。

### 2.3 InputFeatureFrame

每1秒非空frame，固定user_scope/worker_epoch/foreground_epoch/focus_epoch/window_instance；observed_from/to与received_at分开，sequence递增。允许字段：

- text_entry/navigation/editing/function/modifier/other计数、repeat、按键间隔分桶，不逐键时间戳。
- find/copy/paste/cut/undo/redo/save/select_all/print白名单名；其余other_shortcut，无内容。
- 左右中点击/单双击候选、16×16窗口内网格；无系统绝对坐标轨迹。
- 水平/垂直scroll方向、delta、反转；drag起终网格/时长距离分桶。
- typing_burst、enter、scroll_burst等语义次序；输入间隔超过500ms或语义操作切换结束burst，跨秒匿名burst_id连统计。
- dropped_count/truncated/focus_quality/input_source_coverage。

每frame最多32项语义操作，连续同类合并；超限保留总数+truncated。最大16KiB；队列120frames或1MiB；每10秒/256frames事务落盘。鼠标移动累计，不逐事件队列。回调无SQLite/JSON/网络/UIA/OCR/模型。CPU目标正常输入平均小于单核2%，高频鼠标另报告实测，不写成已验证事实。

sequence缺口/非法schema/溢出/worker失败：隔离并停该通道，结束episode、失效预测和询问，状态保留原因；不无限重启/重放。正常停止有界flush，崩溃最多损失未提交批次。IPC关闭/父退出停止并移除注册，不能遗留常驻采集进程。

## 3. 本地库和管理（P08/P09）

### 3.1 分层表及接口

SQLite短连接、事务、migration备份、索引和单写者lease。数据库放行为目录，schema_version独立。表域：

|域|内容|
|---|---|
|events/frames|event_id、user/session/epoch、时间、有限kind、source/quality、app类别、opaque target/material、features|
|episodes|起止、实际有效时间、源事件范围、pattern、数值特征、detector version，无intent真值|
|prompts|prompt_id、episode、pending/answered/dismissed/expired/superseded、时刻、原因|
|feedback|宿主user_event_id、prompt/episode、原回答、确认/纠正/忽略/不再问、scope|
|patterns|规范化signature、支持/反例与source、样本数、最近确认、derived version、active|
|progress|可靠材料、页/时间、有效时长、来源，不含掌握断言|
|management|schema/settings、删除标记、询问quota、migration journal|

主键事件幂等，相同ID不同payload拒绝。宿主决定user/role/project；网页或模型不能声明origin=user或confirmed。material内部可用用户密钥HMAC稳定身份；不靠同名文件。可靠文件身份可采用解析出的文档身份或规范路径+受控验证，路径变更需验证再关联，不能静默合并。无可靠身份只做会话级，不猜跨日进度。

BehaviorService最小方法：observe、feedback、context(limit=3)、list_records、correct、delete_records、export、configure、stop。`/api/manage/behavior`有限action映射；query默认50/最大100、游标分页；修改用revision，删除明确选择+confirmed。宿主event ID和scope不由模型填写。

持久字段禁止屏幕全文/截图/PCM/完整URL/完整按键串/剪贴板正文。允许用户明确反馈、标签、笔记引用和材料可读标签，本地可删除；不要为了禁止原始输入而误删用户反馈正文。

### 3.2 存储位置与容量

默认user_data_directory()/behavior，首次启用可选择其他本地物理专用子目录。个人根locator唯一，行为根有owner标识和lease；不能复用任意非空目录当库根。只创建自己的子目录，不移动无关数据。

无定期/按行数自动删除。缓存有界淘汰不等于历史删除。显示占用、剩余、最近增长。实施默认：数据每增长到5GiB提醒档位；磁盘剩余<10GiB或<10%提醒；<1GiB或SQLITE_FULL暂停新增记录/学习。提醒可调/暂缓，硬暂停保护不删数据。最多10秒检查一次前批写空间，增长统计低频汇总。失败不显示已记录、不无限堆RAM。空间恢复用户显式resume。

迁移prepare→paused→copied→verified→locator_committed→complete，日志幂等。源/目标物理绝对路径核验、目标新专用目录、拒绝链接/包含源/位于源码产品目录。停worker/连接、源目标lease、复制/清单hash/SQLite integrity_check、原子locator切换。源保留；失败切换前继续源，切换后按journal核对当前locator，禁止双写/凭印象回滚。旧数据清理由独立明确动作处理。

### 3.3 多根快照和删除

改造backup_personal_data现有单根快照为version2 roots.personal/roots.behavior；内部behavior只复制一次，外部显式第二根。锁定两根，校验前后inventory/hash/DB。路径用root_id+relative，拒绝..、链接、源内目的和歧义嵌套。兼容v1，明确缺外部behavior。

恢复到新目录，行为默认恢复为新personal/behavior，或用户明确选新的外部根；完整校验后重绑locator，不指向原在线库。整体验证主C/行为D、独立迁移后再快照。外部不可访问/写者未停整体验证失败，不产生verified。

删除事务影响所选frames/episodes/反馈、重算/失效派生pattern、清缓存/pending/in-flight并behavior_epoch++。更正原解释不再召回为有效标签。启动不得按旧缓存复活。可secure_delete/checkpoint，但不宣称擦除SSD/历史快照。历史手动备份不自动删；整快照恢复预览说明会回历史。普通子库导入若未来实现应尊重删除标记，本轮不新建自动同步平台。

## 4. 检测、询问、学习（P12/P13）

### 4.1 有效活动与规则

新verified心跳相邻不超过3秒才累计，静态frame可复用。相同旧bundle重复tick不计。前台丢失/锁屏/暂停/缺口结束片段；没有键鼠输入只标input_idle，不断言人离开。

PDF冷启动180秒有效久留；12秒至少6次真实观察到页变化快翻；30秒实际位置重访/往返，不以两次向后替代。1Hz漏掉中间页时计数是观察下界。视频暂停、seek及回放区间用可靠media identity/audio epoch。不同材料/会话不拼序列。

通用连续语义n-gram长度2～6，尾部最多6动作，新增最多5候选；连续typing/scroll先合并。signature只操作类别，不含字符/绝对位置/细粒度时间。每episode同signature只计一次，至少3独立episode且跨2真实session形成候选；翻页/换profile不是新session。60秒无语义动作、目标/profile变化、暂停/缺口结束episode。

每episode只选一个询问候选：匹配已确认模式优先，否则支持达标的最长序列，稳定ID破平局。原PDF/video规则不受“三次”要求禁用。

异常只数值：同类20有效episode跨3session，用先前样本median/MAD，robust z>3.5；MAD=0/缺数据/质量不足不做。novel不等于异常。检测器/适用范围改版分基线，统计异常仅提高询问优先级，不写心理标签。

### 4.2 询问状态与用户事件

默认10分钟1次/本地日6次，跨重启quota；所有主动发言120秒围栏。档位少打扰30分钟/3次、适中10分钟/6次、积极5分钟/12次。行为episode一次，忽略同类当天不再问。不再问保留设置，不等于删历史。

只有主动许可/profile允许、用户不busy、稳定场景下提问；预算不足保持有效候选，过期丢弃不重放。问“是在找内容还是比较说明？”不说“你看不懂了”。prompt默认120秒，过期可在管理页补说明，但普通新聊天不猜绑定。

pending→answered/dismissed/expired/superseded；每次展示前持久记录，传prompt_id。用户回复入口明确带ID，宿主绑定消息；无关/忽略不确认。用户自由标签保留原话；模型归类为derived，不能取代confirmed原文。可纠正本次、暂不回答、不再问此类。重启旧pending设expired/superseded，不自动弹出。

统一coordinator后台owner/token；换材料/许可/profile、用户抢占、删除使迟到结果无效。关闭questions不关合法记录，关闭use_memory不注入，关闭recording不新增学习事实；关闭全部观察停止新采集/分析/发言。

### 4.3 习惯与进度

相似检索按pattern+活动/profile范围+来源类别+有限特征桶，最多3条摘要。一次确认弱参考；3次确认跨2session且最高标签支持>=80%稳定候选。时间权重默认90天半衰期，只影响预测、不删历史；支持率是统计非校准概率。反例立即计入，更正一次不覆盖全部。

当前预测一直inferred。模型自己的输出零confirmed支持。用户层通用习惯共享，user+role互动私有，project私有上下文不串项目。反馈默认本次episode，提升为全局偏好需明确用户动作/记忆指令。

进度仅可靠材料最近可见页/视频位置、有效观察时长；不等于读完/掌握。“学了什么”只从明确笔记/有标记摘要来，元数据不编主题。独立behavior_context来源块不改原消息/工具授权，不自动塞长期事实记忆。

## 5. 验收与分包回执

P08：幂等冲突、用户隔离、role偏好隔离、schema失败保旧库、删除更正/缓存失效。

P09：无定期删除、空间提醒/满盘停、迁移每阶段中断、主C行为D多根备份恢复、旧snapshot兼容、恢复不连原在线库。

P10：新持久许可恢复但旧一次性不恢复、暂停/撤销重启仍停、新身份、排除/锁屏/自身、目录坏失败关闭。

P11：测试秘密字符串在IPC/SQLite/log/export搜不到；不完整VK串/clipboard；原程序输入不被吞；1000Hz鼠标有界；跨窗frame/drag/modifier隔离；password/unknown降级；断管/溢出无重放、精确worker回收；办公/频繁切窗/游戏覆盖实测。

P12：一次旧bundle181秒零久留，真实心跳静态页面正例；回访与向后区别；重叠n-gram不刷3次，切页不刷2session；novel无intent，MAD=0无异常。

P13：首次往返只问一次→确认找公式→重启相似可召回仍inferred→纠正比较定义→反例生效；忽略/超时/无关不confirmed；删除零后续召回/迟到输出；另一role共享通用但私有偏好不串；断网事实仍记、无自动provider fallback。

P16：现有数据与存储页能看事件/片段/confirmed/inferred、纠正删除导出迁移；权限页能停/恢复；桌宠原消息流回答询问；无新导航。更新ui-design-coverage.md逐屏核对。

每包按总入口命令及对应测试收尾，回执真实结果/限制/下一包。数据库条数增加不等于越用越懂；至少证明确认后跨重启更准确、反例能纠正、删除能遗忘。
