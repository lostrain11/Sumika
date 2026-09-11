# 滚动规划与交接契约

对应WORK-002、H00c/d。实现位于`quality_routing.planning`和现有Coordinator，宿主为QualityRoutingService。不新增数据库、调度循环或Codex目录依赖。

## 实际接口

`Coordinator.submit(plan, quote, rule, *, allowed_ids, external_allowed=False, planning=None, planning_required=False, file_grant=None)`新增三个可选参数。旧SDK不传planning时兼容；传入planning后不能通过修订省略元数据解除检查。file_grant来自宿主任务授权；旧SDK省略时才保留首批节点文件并集行为。提交及修订均检查文件范围。

`Coordinator.revise(plan, *, quote=None, require_confirmation=False, invalidate_ids=(), planning=None)`省略planning时继承原阶段和仍存在节点的交接。改变节点导致旧摘要未就绪，不清除未来阶段。新metadata不能改变原目标契约摘要；目标改变通过宿主新请求版本与授权。

planning固定字段：schema_version=`task-planning/v1`、mode=`rolling|batch`、goal_contract_digest（64位小写SHA256）、horizon_complete（bool）、phases（goal/prerequisites对象数组）、handoffs（节点ID映射）、revision_reason（非空字符串）。batch必须完整；未完整rolling必须保留未来阶段。

handoff包含node_digest、inputs、deliverables、decisions、constraints、validation、failure_policy、blocking_questions、review。说明数组非空，阻断问题为空才能派发。节点摘要来自规范化Node全部字段。

输入首版只允许`{"kind":"literal","text":"必要资料"}`及`{"kind":"dependency","node_id":"facts"}`。全部声明依赖必须引用，派发时必须存在已完成依赖结果。其他来源暂不支持，不能借输入引用读取文件；H01/H06后续扩展受控来源解析。

review为`{"kind":"leader","reference":"response-sha256:摘要","accepted":true}`。结构检查不证明语义质量；宿主从同次主模型响应的reviewed声明绑定实际响应摘要。模板只认可low风险bounded-text与`bounded-text/v1`，不能用于复杂架构。

status增加planning深拷贝和handoff_issues；快照保存planning_required。Execution.handoff为本次冻结交接。缺交接reason=`handoff-required`，节点pending；当前图完成但horizon_complete=false时status=`needs-planning`。取消、未知及未授权优先。

## 宿主行为

生产Core装配WorkService后的复杂Quality请求强制检查，客户端planning_required=false不起作用。旧完成任务保留；旧未派发复杂任务恢复时强制待准备。未装配WorkService的旧测试宿主保留兼容。

模型规划同时返回nodes和planning；模型仅填内容和reviewed，不允许生成宿主hash或review回执。宿主摘要绑定已确认请求、候选、外发范围及上限。检查先于选模、权限回调与资金预留。执行提示携带交接，依赖仍由原协调器提供。

交接内容变化使受影响成果及下游失效，无关成果保留；仅review引用变化不重做。运行、验证及未知尝试禁止重规划。阶段结束由原工作线程调用下一阶段，普通轮询不调用模型；后续规划传入原阶段、成果和状态，保留现有预算上限。费用上界、可信用户确认及跨账本恢复仍是H01/H03，不将本模块冒称为受控模型网关。

## H00回执

- H00a批准稿从本次用户消息完整保存，94项需求及总索引更新。批准稿中的“尚未落盘”为原文历史说明；实时状态看执行记录。
- H00b新增个人plan-freeze及短全局规则；原cost-routing/project-continuity文件摘要保持。备份和摘要在`D:/Caches/sumika-plan-freeze-h00/`，不打包个人配置。校验器用`python -X utf8`，避免Windows默认GBK解码失败；未修改原校验器。
- Skill静态格式、显式策略和检查表链接已验；当前会话未热发现新Skill，下一次新任务显式调用`$plan-freeze`核验真实加载。官方页面本次HTTP403，元数据依据已读取的本地官方Skill规范及批准计划，不冒称在线获取成功。
- H00c/d已实现SDK元数据、派发前检查、滚动状态与Quality接线。API开发/DSH路径尚未接同一检查，由H01–H06继续。
- 后端全量1248通过（`artifacts/h00-backend.log`）；后续补强、HTTP缺交接和实际Quality两阶段循环质量专项100通过（`artifacts/h00-quality-final.log`）。SDK最终101项运行通过、2项可选MCP跳过；仓库外干净wheel同结果，确认site-packages导入无sumika_core。
- H01–H06尚未实现；无真实付费、日用数据变更、提交或发布。

已验证故障：`task-planning/v1`中的子串会被现有秘密正则识别为疑似密钥。失败方法是将整个宿主planning快照放入重规划提示；修复为只发送模型需要的阶段及交接内容，去除schema、宿主摘要及review回执。秘密检测未放宽。实际Quality循环测试覆盖两次规划、首次节点只执行一次、最终交付与轮询不触发新模型调用。

## 普通模型交接：R04交接状态展示

依赖上述真实字段，只改工作台view/host及测试，共享main.js由整合者接线；不得修改费用、授权或调度核心。

1. handoff-required显示“任务资料待补齐”，列pending节点handoff_issues，不能作为Provider故障重试。
2. needs-planning显示“准备下一阶段”，保留成果，不宣称完整任务完成。未知、取消优先。
3. 轮询仅调用现有get，不触发批准、预算变更或新请求。缺编辑入口显示限制，H01可信动作完成后再接。
4. 展示阶段摘要，hash和review引用收入诊断。组件使用明确props与动作回调，不读全局应用对象。
5. 覆盖旧无planning、缺交接、部分完成、未来阶段、unknown和取消；草稿/复制不受重绘影响。运行前端单测和工作台E2E，无真实模型调用。
6. 回退只移除展示，原记录及快照保持。提交命令结果、截图位置和限制，不将UI完成等同H03/H06完成。
