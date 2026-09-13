# P5 办公文件复用选择

本轮先实现 P5-1 的基础文件能力，与其他模型负责的 UI 设计并行。用户原文见 R-114。能力选择是本轮实施决定，不意味着用户改变了 UI 风格或批准任何额外付费服务。

## 本轮实际检查的候选

| 方案 | 本轮依据 | 取舍 |
| --- | --- | --- |
| [Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server) | 读取上游 README 与 pyproject.toml；声明 MIT；依赖 python-docx、FastMCP、docx2pdf 等 | 已有丰富文档工具，后续值得实测；当前不用多一层服务即可复用相同文件库。未安装或验收该 MCP，不声称它质量不足。 |
| [Office-PowerPoint-MCP-Server](https://github.com/GongRzhe/Office-PowerPoint-MCP-Server) | 读取 README 与 pyproject.toml；声明 MIT；基于 python-pptx | 模板和工具值得后续比较；当前基础读写直接复用库。没有宣称已验证其专业设计质量。 |
| [excel-mcp-server](https://github.com/haris-musa/excel-mcp-server) | 读取 README；MIT；支持 stdio 和 HTTP，文档区分两种文件路径边界 | 保留为更结构化工具接入候选；尚未进行实际服务或公式能力验收。 |
| [MarkItDown](https://github.com/microsoft/markitdown) | 读取 README；定位是文档转 Markdown，面向模型内容提取 | 可在后续完善读取时复用；不能单独覆盖本轮创建与修改。 |
| python-docx / openpyxl / python-pptx / pypdf / reportlab | 查 PyPI 包元数据，安装实际发行，核对全部依赖 wheel 哈希，运行真实文件和 DSH 验收 | 选为首个可用基线；优先复用现成解析和写入，不自建同类工具协议。 |

GitHub API 返回限流 403，因此候选源码信息来自可读取的上游 raw README/pyproject；没有核实社区所有插件、维护活动、漏洞或逐个服务行为。此结论是适合当前基础范围的选择，不是“全社区效果最佳”的排名。后续有复杂编辑需求时实测候选服务，再决定是否替换或补充，不因已有这层代码而拒绝更好的现成方案。

## 已选择发行与许可

| 库 | 版本 | 包元数据许可 | 基础职责 |
| --- | --- | --- | --- |
| python-docx | 1.2.0 | MIT | Word 段落、runs、表格 |
| openpyxl | 3.1.5 | MIT | Excel 单元格、公式文本、格式 |
| python-pptx | 1.0.2 | MIT | 幻灯片与文本 |
| pypdf | 6.18.1 | BSD-3-Clause | PDF 读取、页操作 |
| reportlab | 5.0.1 | BSD | PDF 创建 |

元数据来源：`https://pypi.org/pypi/<package>/<version>/json`。完整安装版本与所选 wheel 哈希在 `extensions/office/requirements.lock`；原始本机安装记录在 `.sumika-next/office-install-report.json`。库及其许可文件留在独立虚拟环境中，没有复制第三方源码进核心。

## 接入约束

核心能力来自库；可移植 Skill 提供格式限制和验证流程。新增启动器只负责环境选择、开关和退出码，安装器只负责复制 Skill 与环境路径。DSH 侧不新增插件代码，不改上游或 native node_modules。

设置接线：已安装 `.agents/skills/sumika-office/runtime.json` 的 `enabled` 为布尔开关；`provider=python-libraries` 是当前唯一实现，不能把“有 provider 字段”记成已支持任意实现切换。详见 [扩展说明](../../extensions/office/README.md)。

P5 的通用模块添加、排序、移除和多实现切换仍是后续任务。本轮不新增模块系统，不涉及 UI 文件、模型路由、角色记忆或桌面控制。
