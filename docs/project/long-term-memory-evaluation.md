# 长期记忆 provider 评测与首选

## 结论

最终首选：**MemMachine 自托管服务 + 独立 Sumika 适配层**。依据你提供的 AML 信息，MemMachine 在事实召回、关系/多跳、时间事件和记忆治理等维度表现突出；仍需用 Sumika 中文评测集复测。

Mem0 OSS 保留为备用基线。本结论是架构/依赖评估后的首选，不是中文真实模型效果已经证明“最佳”。接入前仍须在隔离环境用固定中文评测集实测；在实测未完成前不自动写入角色长期记忆。

选择 Mem0 的原因：Python 生态成熟、可使用 Qdrant/SQL 等后端、作用域字段可映射到用户/角色/项目/会话、支持记忆添加/搜索/更新/删除和历史；不需要引入第二套 Agent/Harness。Apache-2.0 允许独立适配层复用。

## 候选比较

| 候选 | 优点 | 阻碍 | 结论 |
| --- | --- | --- | --- |
| MemMachine 自托管 | Apache-2.0；Python；向量/图/数据库后端可选；作用域和 CRUD 适合角色隔离 | 仍依赖 embedding/LLM；不同后端的中文效果和成本需实测；默认遥测/配置要审查并关闭或隔离 | **首选基线** |
| Graphiti 0.30.2 | Apache-2.0；时序事实和关系图强；适合复杂人物关系和事实变化 | Neo4j/FalkorDB 等额外服务；写入抽取成本和运维更高；中文抽取尚未验证 | P6 后续复杂关系实验 |
| claude-mem | 会话观察和分层检索思路有参考价值 | 面向 Claude 工作流；DSH 兼容、数据迁移、成本和隐私边界未验证 | 只研究，不接入 |
| Letta | 长期记忆和 Agent 状态完整 | 自带 Agent/Harness，违反不引入第二套循环的边界；Python 3.14 当前要求也不匹配 | 不接入 |
| DSH 社区记忆插件 | 生命周期接入可能简单 | 当前 rc.2 安装包没有已验收的 memory/mem0/graphiti/zep 组件；插件兼容和来源隔离未知 | 继续检索，未阻塞 Mem0 适配 |

## 必须通过的实测

使用相同 provider、同一中文评测集和独立角色命名空间测试：

1. 多轮中文偏好和事实召回；
2. 新事实覆盖旧事实，同时保留历史；
3. 用户陈述、角色设定、模型推断、工具观察的来源区分；
4. 安和昴与其他角色互不召回；项目记忆与角色记忆互不召回；
5. 删除、导出、恢复和迁移后结果一致；
6. 记录写入/检索延迟、额外模型调用、token 和费用；
7. `enabled=false` 后不写入、不检索、不注入，但已有数据仍可导出。

任何云端 Mem0、OpenAI、Anthropic 或托管数据库都需要用户另行授权；本项目不会因“首选现成方案”自动上传角色卡或开启付费服务。

## 接口边界

适配层只负责 `add/search/update/delete/export/import` 与命名空间映射：`user_id`、`role_id`、`project_id`、`session_id`。记忆结果作为独立 `memory_context` 来源块注入，不能修改原文、代码、diff、工具参数或成果正文。替换 provider 只改适配器和迁移，不改 DSH 上游或角色资源格式。

## 2026-10-16 DSH 插件商店考察与记忆插件实测

背景：日用 CLI 已升到 `@deepseek-ai/dsh 0.1.0-rc.6`，`dsh plugin` 子命令与插件生态已上线。本轮重新执行计划第 1 步「优先现成 DSH 插件」，并按同一中文评测单实测头部候选。**全程零云模型调用**（检索层用各插件自带 CLI/存储直驱）。

### 生态现状

- 插件市场：应用内 `dshmarket`（月下载 59.6 万）、CLI `dsh-plugin`（2.2 万）；插件即 npm 包，`dsh plugin --profile <名> add <包>` 安装。
- npm 搜到的记忆类 DSH 插件 12+。按月下载与架构归类：

| 候选 | 月下载 | 架构 | 本项目判定 |
| --- | --- | --- | --- |
| @openviking/dsh-memory-plugin | 40,164 | 需常驻 OpenViking 服务器（viking:// 空间） | 不采：违反本地优先 |
| @lmzhen/dsh-memory | 12,394 | provider 注册表（自演化社区版） | 非引擎，是接缝层 |
| @fooxe/dsh-memory | 7,296 | 纯 Markdown 零依赖，用户+项目作用域 | 实测通过，见下 |
| @tr1v3r/dsh-ltm | 2,281 | SQLite FTS5 + 中文二元分词 + BM25/字符 n-gram 混合重排 + 修订 CAS | 实测通过，最强候选 |
| dsh-memory-gate / @alanzhao/dsh-memory-lite / @jipika/dsh-memory 等 | 1.6k~3k | 各式本地库 | 未测，候选池保留 |
| @mem0/deepseek-plugin（mem0 官方） | 734 | Mem0 托管云后端，自动存全部对话 | 不采：云授权+来源边界不符 |

### 实测一：@tr1v3r/dsh-ltm 0.3.1 —— 11/12 通过

隔离 profile `memtest-ltm`，经其自带 CLI（`--db` 指向评测库，零模型调用）：

- **通过**：中文直查（安和昴 喜欢吃什么→草莓蛋糕）、改述召回（她的口头禅是什么→hah？）、跨话题召回（期末考试 复习→高等数学）；`list --scope` 隔离正确；同修订编辑成功、**过期修订拒绝**（结构化 MEMORY_REVISION_CONFLICT）；更新后新值可召回旧值消失；forget 后不再召回；export→全新库 import→召回一致；检索延迟 ~115ms。
- **唯一失败**：同义改述（编程语言→Python）——纯词法检索无嵌入的固有短板，与 Sumika 内嵌关键词 provider 同类；其卖点正是中文**分词**（Sumika 的 FTS5 默认分词器整句成单 token 的问题它已解决）。
- 设计注意：CLI `search` 无 `--scope` 参数（跨 scope 全局检索）；作用域模型是 project 桶（autoProjectScope），没有 Sumika 的 (user, role, project) 三元组与来源区分。

### 实测二：@fooxe/dsh-memory 0.13.6 —— 9/9 通过（含预期内弱项）

隔离 profile `memtest-fooxe`，stub cordis ctx 直驱工具层：

- **通过**：保存×4、同题名原地更新（slug 去重）、更新后旧值消失、凭据形状拒写（sk-32+ 实拦）、读写延迟 2~5ms、纯文件天然可导出。
- **已知限制**（预期内记为通过）：改述/同义检索必失败——search 是**纯子串匹配**（无分词无评分）；`password:` 形状不拦（凭据扫描只认 sk-/ghp_/AKIA/私钥等形状）；四个模型工具**无删除/遗忘**（仅面板可删）；作用域是 user/project 二元，无角色维度。
- 过程发现一处**隔离坑**：存储根默认 `$DSH_HOME/memory`，可用 `DSH_MEMORY_USER_DIR` 覆盖——首轮回跑污染了共享 home 6 个文件+索引，已全部清理并验证（`D:/DeepSeek/dsh-home/memory` 整目录为测试产物，已移除）。

### 集成冒烟（部分完成）

- **boot 加载验证通过**：`dsh --profile memtest-ltm headless` 真实启动中 ltm 插件 `apply()` 执行、打开自身 `memory/ltm.db`（评测 home 内可见 WAL），无 loader 错误——cordis 级兼容 dsh 0.1.0-rc.6（其 peer 要求恰为 >=0.1.0-rc.6）。
- **模型回合未完成**：本 shell 环境 headless 模型调用挂起（>15 分钟无 WAL 活动），未复现原因；另发现**新版 CLI 凭据格式迁移**：`.credentials.yaml` 从 v1（version/refs/records 结构）改为扁平 `标识符→字符串` 映射，旧文件会被严格解析拒绝——真实凭据文件未改动，评测用副本已删除。完整端到端冒烟需在桌面端正常会话里做。

### 结论

1. **Sumika 日用内嵌基线不变**：两条插件的作用域模型（project 桶 / user+project）都不满足 Sumika 的角色隔离与来源区分硬约束；检索强项（中文分词+混合重排）Sumika 已用 SemanticMemory(bge) 达到 13/14。
2. **dsh-ltm 记为 DSH 原生侧首选候选**：若未来角色会话迁入 DSH 原生插件生态，其修订 CAS、导出/恢复、过期复核是现成引擎里最贴合治理要求的实现；可挂到 @lmzhen 注册表类接缝下。
3. 官方 mem0 插件（云后端、自动入库）与 Sumika「模型意见≠用户事实」边界冲突，不采。
4. 测试资产：共享 home 留 `memtest-ltm`/`memtest-fooxe` 两个隔离 profile（未挂日用）；评测脚本与隔离 home 在 `.sumika-next/dsh-memory-eval/`（凭据副本已删）。
