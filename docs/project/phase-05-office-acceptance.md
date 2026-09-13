# P5-1 办公文件基础能力验收

结论：基础文件能力已实现并通过本地真实 DSH 接线验收；P5-1 保持 **partial**，P5 保持 **in_progress**。UI 由用户另选模型负责，本轮未修改 UI 文件，不将 UI 阶段标为完成。

## 实现范围

- [独立扩展](../../extensions/office/README.md)：五个开源文件库、11 项完整依赖哈希锁、可移植 Skill、独立环境启动器和安装器。
- DSH 原生加载 Skill，通过原生终端使用库；新增逻辑不导入 DSH/Sumika 核心，不改上游源码和 node_modules。
- `enabled=false` 阻止后续扩展启动；重装保留禁用状态，未知 provider/配置或缺失环境报错；文件、库和原生 Skill 保留。运行中的任务仍用原生取消。
- `.docx` 中文段落/runs/表格、`.xlsx` 数据/公式文本/样式/合并区域、`.pptx` 页面/文字、`.pdf` 中文生成/文字提取/页旋转/元数据的基础读写修改。源文件哈希保持不变。
- [复用选择与候选范围](office-reuse.md)。没有声称对社区方案完成全面排名。

## 已完成验证

| 检查 | 结果 |
| --- | --- |
| `python -B -m unittest tests_next.test_office_extension -q` | 7 项通过：禁用无写入、失败退出码、参数字面传递、工作目录、配置错误、环境缺失、保留已有修改与禁用配置。 |
| Skill Creator `quick_validate.py` | 模板格式校验通过。 |
| `pip install --force-reinstall --require-hashes --only-binary=:all: -r extensions/office/requirements.lock`，随后 `pip check` | 11 项固定 wheel 安装和依赖一致性通过。 |
| 独立 `verify_files.py` | 四类实际文件生成、读取、修改、重新读取和原文件保留通过。 |
| `.sumika-next/verify-env/Scripts/python.exe -X utf8 -B tools/verify_phase5_office.py` | 真实 DSH rc.2 原生 Skill、终端、四类文件操作和禁用入口通过。 |

最终 DSH 证据在 `.sumika-next/p5-office-7fcc38c3e53d4b229d303d9a86c75704/`。可共享的结构化结果和证据摘要见 [evidence](phase-05-office-evidence.json)。该验收使用本地确定性模型替身，**0 外部模型调用**；不冒充真实模型自主选用 Skill 的质量评测。

首次接线验收脚本错误地要求成功输出包含 `[exit code: 0]`，实际 DSH 仅为非零退出添加标记；文件操作当时已成功。修正为检查实际 tool result、JSON 报告和源文件后重跑通过。失败证据保留于 `.sumika-next/p5-office-b74138e4fd0b43b194af40fa4a9cc972/`，便于后续避免复用错误断言。

## 未完成与限制

- 未进行视觉渲染、Word/PowerPoint版式检查或真实模型自然语言任务验收。
- openpyxl 写入公式不代表计算完成；本轮明确验证公式缓存为空，未返回虚构计算值。
- 未实现扫描件 OCR、任意 PDF 段落替换、安全涂黑、旧 `.doc/.xls/.ppt` 格式、宏/签名/复杂 OOXML 无损往返。
- 本轮是文件能力，不是控制正在运行的 Word、Excel、Blender 等软件；通用桌面控制仍属 P5 后续。
- 安装锁只验收 Windows x64 / CPython 3.14。其他平台没有加入支持范围。
- 开关是本扩展入口的功能控制，不撤销原生终端权限；Skill仍可发现，正在执行的任务不因切换配置自动中断。

## 回退与下一步

关闭已安装 `.agents/skills/sumika-office/runtime.json` 中的 `enabled` 即停用后续启动，保留成果、原文件、环境和配置。模板版本通过 Git 恢复；安装器遇到不同内容的 Skill 停止覆盖。迁移时显式重绑 Python 环境路径。没有修改日用 DSH profile 或发行文件，因此无需回退上游。

接下来本 Agent 可继续 P5 的 OCR 与通用桌面控制方案验证；其他模型继续 UI 设计。设置 UI 接入和其他 P5 能力尚未完成。

## OCR 进展

已新增独立 OCR 适配层，支持探测和调用 Tesseract 或 RapidOCR，输出结构化识别文本并为后续翻译保留接口。当前机器未安装任一引擎，3 项 OCR 边界测试通过；未自动下载模型或调用网络。真实识别能力待安装 provider 后验收。
