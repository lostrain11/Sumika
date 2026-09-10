# Skill 迁移：独立脚本处理路径配置

确认日期：2026-09-10。此文替换先前由 Agent 阅读长篇 Skill 说明推断路径的方案。
实施状态以[状态矩阵](../status-matrix.md)为准；本轮不继续 R01–R07，不提交、推送或发布。

后续差量详见[剩余执行计划v2](remaining-execution-plan-v2.md)的R06c–R06f/R12：保留以下已实现与历史验收，补其他runtime、供应链和完整host管线，不重新迁移cost-routing或复制Codex办公插件。

## 用户确认的范围与出处

以下摘录来自本任务用户提交并要求实施的《Sumika Skill 迁移计划：独立脚本处理路径配置》，
不是助手建议伪装成用户原话，不包含历史消息中的凭据：

> 保持 Codex 原有 Skill、插件和配置不变。

> 不移植 `cost-routing`，复用 Sumika 原生路由、预算、验证和恢复能力；清理本次新增但未接线的重复草稿。

> 将 `project-continuity` 拆成三个独立、默认关闭的 Sumika 官方 Skill。

> 不新增 Sumika 专用路径设置页、专用路径数据库或推荐服务。

> 当前任务保留已加载版本，后续开关或内容变化作用于后续请求。

源个人目录共20个文件在修改前后 SHA-256 比较，全部一致。未对 Codex 插件和配置执行写操作。
源 `project-continuity/SKILL.md` SHA-256：
`e0a04f241a9c8f81c8430d01edc11e3852ccebb5cf412b4fcc82523516a041b5`。
源 `cost-routing/SKILL.md` SHA-256：
`f1f6850bb58d3b5b500d1f66ce2c3cc6277f852d70625faf7c2de1e957f5a5e4`。
七份未接线的委派、成本与复审 Skill 草稿文件已移除；原生路由实现保持。空目录清理命令被自动审批审查拒绝（仅返回blocked by policy），保留空目录，不进入wheel资源清单。

## 官方 Skill 与运行时

资源位于 `backend/src/sumika_core/builtin_skills/resources`：

| ID | 功能 | 默认 | 接线 |
| --- | --- | --- | --- |
| project-progress | 项目进度、证据与交接 | 关闭 | API开发任务按需加载 |
| troubleshooting-notes | 故障原因、失败方法与修复经验 | 关闭 | API开发任务按需加载 |
| tool-registry | 工具复用与缓存路径检查 | 关闭 | API开发任务按需加载及只读 helper |

设置页统一展示三个独立开关；`skill.builtin.list/set` 按助手保存版本化启用状态。
复用现有 SkillCatalog 注册，不建立第二个 DSH 执行器。安装本地副本仅发生于启用时，
不扫描配置中的工具目录、不执行 helper。内存测试 Core 无持久安装目录，启用明确报不可用。
原生客户端源码中的设置已接线；本轮未重建替换日用 Tauri 可执行程序。

API开发预检冻结 Skill 正文、描述、版本及已审查 helper 源码，授权覆盖快照摘要。
初始上下文只包含启用项的名字和描述；`load_skill` 按需取正文，关闭项没有加载入口。
`run_skill_helper` 只运行快照中的标准库检查代码，不执行本地被替换的同名脚本，且不将脚本源码
塞进模型上下文。调用参数为数组，不经过 shell。开关及发行正文更新不影响已确认任务。
配置在每次实际检查时读取，适用于用户修复配置后重试；它不增加文件、网络、执行或消费权限。

DSH／ZCode／普通闲聊尚未挂接这三个开关，界面明确说明只在 API开发路径加载。
本轮没有把 Skill 开关冒称为 DSH 已启用状态。其他宿主可直接使用相同 Skill 目录及脚本。
当前开发文件工具限于源码副本，不能自动写 Skill 安装目录；应用推荐需用户编辑配置，或使用
已有且获授权的宿主文件工具，不能借本功能扩大开发执行器权限。

## 三文件路径协议

```text
tool-registry/
  SKILL.md
  config/paths.json
  scripts/check_paths.py
```

官方分发的 `paths.json` 始终为：

```json
{"tool_directories": [], "download_cache_directory": ""}
```

脚本只依赖 Python 标准库，不导入 Sumika，不读其配置、数据库或凭据。
调用 `python scripts/check_paths.py --config <绝对配置文件> --operation reuse|cache [--data-root <绝对目录>]`。
宿主显式提供 data-root，Sumika 传自身运行数据目录，DSH 等宿主可传自己的目录；没有基准不猜路径。

| 结果 | 行为 |
| --- | --- |
| ready | 仅返回状态和当前操作所需路径，退出码0 |
| configuration-empty | 退出码2；有有效根目录时推荐其 tools 或 tool-cache，附绝对路径、存在状态、可复制配置 |
| path-unavailable | 退出码2；返回失效项及原因，不自动替换 |
| configuration-unavailable / invalid-configuration | 退出码2；明确配置文件不可用或字段类型错误 |
| recommendation_unavailable | 明确无有效基准，或建议位置被文件／链接占用 |

复用只检查工具目录；缓存只检查缓存目录及可写访问位，不因其他字段未配而失败。
不会枚举目录内容、运行发现的工具、下载、调用模型或写入配置。链接／Windows junction
及 reparse 目录被拒绝；实际后续扫描也必须不跟随链接越出授权范围。检查不是 OS 沙箱，
目录可能在检查后变化，后续文件操作仍须由宿主执行权限检查。

只有用户明确要求应用建议后，宿主文件工具才创建目录和修改本地配置，再重新检查。
推荐阶段零文件改动；不需要在 Sumika 增加专用路径表单或服务。失败只影响当前功能。
升级重新启用时更新发行正文与脚本，保留本地 config；禁用不删除本地 Skill、工具或缓存。
发行配置与助手安装目录分离，wheel 检查必须拒绝非空个人路径。

## 社区办公平替与来源

不复制 Codex 官方 documents、pdf、spreadsheets、presentations、template-creator 插件。
社区目录 npm metadata、包源码和许可证分开核验；以下两项通过真实 DSH 固定版基础功能验证：

| 包 | 作者／来源 | 版本／许可 | 已验证范围与限制 |
| --- | --- | --- | --- |
| dsh-office-tools | [kw78](https://github.com/kw78/dsh-office-tools) | 1.0.0 / MIT | Word创建读取追加、Excel创建读取改单元格、PPT创建读取；非复杂版式或渲染验收，不保证公式重算，含二进制媒体的更新可能拒绝 |
| dsh-pdf | [sunshine-lang](https://github.com/sunshine-lang/dsh-pdf) | 0.1.0 / MIT | 单页文字PDF读取；不是OCR、PDF编辑或渲染。Windows标准字体路径有上游警告，测试英文正文仍完整；中文字体、扫描件未验收 |

由 `plugins/dsh-community-documents` 提供薄注册过滤器，上游算法没有复制或改名归属。
Word、Excel、PowerPoint、PDF读取四项独立开关，默认全部关闭；文件许可另行配置。
关闭项不注册，registry派发返回 UNKNOWN_TOOL。已有上游 bundle 被禁用，避免重复绕过开关。
没有直接安装上游 bundle 时，DSH 的 entry-not-found 提示为无匹配覆盖，不阻止包装器加载。
不新建专用 Sumika 插件设置页，使用 DSH 的通用插件配置。

默认安装清单为 `plugins/community-defaults.json`，记录作者、许可证、固定版本、integrity。
已有 `setup-sumika-dsh-bridges.ps1` 读取该清单，安装打包后的本地适配器，忽略第三方安装脚本，
不启用用途或自动授权。此次只使用专用隔离 profile，没有修改日用 DSH 或配置真实 Provider。
原许可证随各 npm 包保留。固定发行与后续依赖升级须重新验收；profile lockfile保存解析版本。
本次解析为 pdfjs-dist 6.3.289、DSH旧工具声明0.0.1-rc.1、schemastery3.18.2；
peer warning未被当作兼容通过证据，实际加载、工具函数与文件读写另有结果。

其他候选仅完成检索／元数据或源码检查，**不默认安装**：

| 用途 | 候选 | 当前缺口 |
| --- | --- | --- |
| PDF信息／渲染 | @zhtx2026/dsh-pdf 0.1.1，MIT | 源码直接访问本机路径，没有宿主fs作用域且三工具无独立开关；不接入自动路径 |
| PDF编辑 | dsh-pdf-edit 0.4.5，MIT | pdf-lib/fontkit/PDF.js依赖；未审执行边界、编辑效果与卸载 |
| 表格公式／复杂办公 | dsh-univer-office 0.2.14，Apache-2.0 | 含Univer Pro资产、原生公式引擎、浏览器与网关；须核查各依赖许可和网络／费用后再试 |
| 文档复杂读写 | @huiliyi37/dsh-office 0.2.2，Apache-2.0 | 元数据未给仓库地址；多依赖、多功能开关和视觉效果未验证 |
| PPT主题／模板 | dsh-ppt 0.4.1，MIT；dsh-workbuddy-ppt 0.1.0，MIT | 后者含renderer、pptxgenjs等；模板创建、视觉排版与通用跨格式模板能力未验收 |

## 验收证据与恢复

- 独立脚本及启停契约12项通过，含真实Windows junction、中文空格路径、推荐零写入、缓存／工具独立检查、源包空配置、升级保留配置、旧任务快照、持久Core重启。
- WorkService实际开发工具循环使用离线模型 fixture：只按需加载已启用正文与helper、关闭后当前任务继续使用快照；真实临时Git目录和Python测试，非真实模型质量验收。
- 工作台E2E10项通过，Skill开关为明确fixture；持久安装由后端Core专项验证。修复模型设置保存期间的竞态，不放宽选模断言。
- 真实DSH 0.1.1-rc.2隔离profile完成安装、四用途独立加载、全关闭／未授权、同版重复安装、官方CLI卸载。Office更新和中文纯文本读写通过；PDF英文fixture读取通过。无模型调用。
- DSH工具函数通过真实注册表及真实LocalFileSystem执行；会话cwd为测试fixture，未伪装为真实用户会话或完整模型工具循环。关闭项另经真实registry执行确认UNKNOWN_TOOL。
- 卸载后测试profile dependencies清空，DOCX/XLSX/PPTX/PDF及结果全部保留，无自有DSH进程残留。
- 最终后端专项81/81、前端单测78/78、工作台E2E10/10通过；SDK79项完成（2项可选MCP缺依赖跳过）。生产构建、文档、发布资产及diff检查通过。日志为 `artifacts/skill-backend-final.log`、`skill-frontend-unit.log`、`skill-e2e.log`、`skill-sdk.log`、`skill-build.log`。
- `pip wheel`隔离构建成功，`tools/check_skill_wheel.py`验证只有三Skill及所需资源、官方空配置、提取后的脚本在仓库外且无PYTHONPATH可运行。全局Python无setuptools时用pip隔离构建，不安装到全局。发布路径规则5项测试通过。
- 默认安装脚本在新的bootstrap-home执行两次，包hash一致，社区用途和fileAccessGranted保持false；经官方CLI卸载测试依赖。日志为 `bootstrap-install.log`、`bootstrap-repeat.log`、`bootstrap-composed.yml`、`bootstrap-uninstall.log`。

清理限制：wheel构建生成的 `backend/build/` 与 `backend/src/sumika_core.egg-info/` 经检查属于本次临时产物，
精确删除命令也被自动审批审查以blocked by policy拒绝。未改用其他工具删除或移动绕过；两目录及七个空草稿目录保留。
它们不是源码交付，不应提交或发布。恢复时仅清理上述已确认临时目录，不删除其他既有未提交工作。

证据目录：`D:/Caches/sumika-community-review`，其中 `documents/*.json` 区分模式与session fixture；
`install-tar.log`、`idempotent.log`、`uninstall*.log` 记录CLI行为，`composed.yml`记录真实组合配置。
探针保留在 `tools/dsh-community-smoke.mjs`，必须使用专用profile及绝对产物目录。
初次ESM入口需使用file URL；直接本地目录安装曾出现pnpm进程不退出，改为已有安装器同样使用的tgz。
退出码1来自DSH对SIGINT的处理，不能单看退出码；以探针结构化结果、卸载状态与进程检查共同判断。

剩余：普通闲聊／DSH等运行时的三个Skill适配、社区高级功能审查、中文复杂PDF、完整模型循环和视觉效果；
本轮不把这些尚未实现的能力宣布可用。后续执行先读本页，再按剩余计划R06/R12衔接，不能重做原生路由。
