# 独立办公文件扩展

首个基线复用 `python-docx`、`openpyxl`、`python-pptx`、`pypdf`、`reportlab`。没有自建 Office/PDF 解析器或 Agent 循环。`skills/sumika-office/` 可整体安装到其他支持 Skill 和终端的 Harness；不导入 Sumika 或 DSH。DSH 通过原生 `.agents/skills` 发现和加载它，文件操作沿用原生终端的权限、审批和取消流程。

## 安装与使用

锁定环境为 Windows x64、CPython 3.14。固定了全部 11 项依赖及所选 wheel 的 SHA-256（与 PyPI 元数据核对）；更换 Python/平台需要重新解析和验收，不能直接移除哈希约束。

在仓库根执行：

```powershell
python -m venv .sumika-next/office-env
.sumika-next/office-env/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: -r extensions/office/requirements.lock
python -X utf8 -B extensions/office/install.py --root . --python .sumika-next/office-env/Scripts/python.exe
python -X utf8 -B .agents/skills/sumika-office/scripts/run.py status
```

安装器只复制 Skill 和写入环境路径，不联网、不改上游、DSH profile 或已有不同内容的 Skill。可以指定其他 `--root` 安装到另一个工作区，或使用仓库外的独立环境。已安装副本按机器生成并忽略上传；模板与依赖锁入 Git。搬迁环境后显式更新 `runtime.json` 的绝对 `python` 路径。

Agent 根据 Skill 编写任务脚本，通过下面入口使用已有库：

```powershell
python -X utf8 -B .agents/skills/sumika-office/scripts/run.py exec path/to/task.py --output path/to/result
```

输出内容、工作目录、退出码保持由任务脚本决定。所有 shell 参数要按宿主 shell 正确引用；启动器自身不拼接 shell 命令。文件处理不连接模型或远端服务。

## 设置接口与替换边界

已安装 Skill 的 `runtime.json` 是本模块设置接口：

```json
{"schema_version":1,"enabled":true,"provider":"python-libraries","python":"D:/path/to/env/Scripts/python.exe"}
```

将 `enabled` 改为 `false`，后续启动入口立即拒绝执行，重新安装不重新启用；不删除文件或依赖，不停止已经启动的任务。未知 provider、非布尔开关或缺失环境均报错。设置 UI 留给 UI 阶段接入，此处没有 UI 代码。

Skill 仍可被原生发现；开关控制此扩展的启动入口，不撤销原生终端执行 Python 的权限，也不构成抵御恶意脚本的沙箱。普通文件/系统命令仍服从 Harness 的原生策略。关闭正在执行的任务用原生取消。

只有 `python-libraries` 一个 provider 已实现；新增 MCP 或其他方案时保留文件产物和 Skill 工作流，替换实际接入。这里没有提前实现通用模块注册器、排序界面或任意 provider 插件框架。

## 能力与限制

- `.docx`：段落、格式化 runs、表格的基础读写修改。
- `.xlsx`：单元格、公式文本、样式、合并区域；不执行公式计算。
- `.pptx`：幻灯片、文本 runs 的基础读写修改；不渲染。
- `.pdf`：生成、文字提取、页旋转和元数据修改；不是任意段落编辑器，也不提供 OCR 或安全涂黑。

这轮验收包括中文内容、原文件保留和修改后重新读取；不承诺复杂 Office 特性无损往返。没有做视觉渲染、公式重算、扫描件 OCR、旧二进制格式或真实办公软件交互验收，不能将这些标记为可用。细节见 Skill 的格式参考。

## 验证

```powershell
python -B -m unittest tests_next.test_office_extension -q
python -X utf8 -B .agents/skills/sumika-office/scripts/run.py exec extensions/office/verify_files.py --output .sumika-next/office-new-acceptance
.sumika-next/verify-env/Scripts/python.exe -X utf8 -B tools/verify_phase5_office.py
```

每次文件验收使用不存在的新输出目录，避免覆盖之前结果。DSH 验收采用真实 Skill、原生终端和文件库，模型端点是本地确定性替身，不是自然语言任务质量评测。失败保留证据，不开启付费 fallback。
