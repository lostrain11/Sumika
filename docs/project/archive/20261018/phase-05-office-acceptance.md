# P5-1 办公文件基础能力验收

## 当前补验：r8 官方办公引擎与运行时探测（2026-10-17）

当前内部候选为 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r8`，DSH仍固定最新发布的0.2.1-rc.2。复用官方Office技能、workspace-dependencies工具、LibreOfficeKit0.1.5及其已随包提供的Windows引擎；只改公开profile接线和独立依赖层，不改上游或新增UI。

已修复：局部bridge库遮蔽完整Office环境；桌面/摄像头就绪探测忽略选定运行时；依赖载荷继承旧dist-info造成版本歧义。当前载荷从干净site-packages安装17项SHA锁定依赖，包含NumPy2.5.3/Pandas3.0.6/tzdata2026.5，无重复元数据。`prepare_office_payload.py`不再携入基础bridge的第三方包。

验证：源码1329项/129.549秒OK，23跳过，既有警告保留；最终定向19项通过。r8库存60468文件；537文件比对仅外部维护工具`verify_capability_package.py`在构建后推进，产品源码一致。包内Bridge/desktop/voice/Office导入、中文OCR创建、VAD加载、process-audio能力探测通过，未开启采集或播放；实际EXE首启/复用/外部端口拒绝/认证退出4项与128格布局通过，无横溢出/pageerror。

r8真实DSH自动注册7技能和依赖工具，技能包含包内Node/CLI路径；四类文件读建改重开、原生终端导出PDF和重算7通过（14次loopback夹具调用、0外部调用），证据`.sumika-next/p5-office-ca98a52081bf4388b365e9a9e53848ec/report.json`。官方引擎另测三格式各2页PDF、跨表公式90/105/超预算及公式保留、2张DOCX预览、损坏输入拒绝、源SHA不变；两张PNG与人工审阅版本SHA一致，证据`.sumika-next/acceptance-20261017/official-kit-r8/681024087a834a1eb78ee662ec6e0c6d/report.json`。此前r6“官方引擎禁用”和“numpy/pandas未提供”属于历史快照，r8已补齐；r7曾继承旧tzdata元数据，不作为最终候选。

复现：设置`SUMIKA_TEST_CANDIDATE`为r8，运行`python -X utf8 -B tools/verify_phase5_office.py --native-office-workflow --native-office-engines --repair-fixture-acl`；依赖无设备检查使用`python -X utf8 -B -m tools.verify_capability_package <candidate> --require-office --require-process-audio --output <新报告路径>`。ACL只处理生成的测试工作区。

边界：引擎报告Courier字体替换；依赖Windows VC++v14运行时，尚未在干净机器验证。旧sumika-office开关只控制自身runner，不能关闭官方技能或撤销终端权限。自然语言自主任务质量、任意文件无损、真实设备/站点和整体验收未完成；未部署/发布，整体目标保持进行中。

## 以下为此前阶段记录


## 2026-10-17：结构化文件、视觉与r5原生接线补验

复用已启用sumika-office独立库环境、LibreOffice26.2.6、`extensions/office/render.py`及原生Skill验收；`tools/verify_office_complex.py`是扩充合成验收，未另建编辑器或修改产品。Word编辑保留粗/斜体、页眉页脚、表格、分页；Excel跨表SUMIF/SUM/IF与日期经真实重算得到90/105/超预算，图表和冻结窗格保留；PPT编辑保留表格、图表、讲者备注及第二页。三类各2页PDF，6张PNG逐页查看，无裁切/重叠/空白，源文件SHA不变。中文标题PDF文字提取顺序不佳，未删除断言，改用既有RapidOCR核对实际像素并人工审阅。证据`.sumika-next/acceptance-20261017/office-complex-final/report.json`。

r5真实DSH/Skill/原生终端四类文件操作及禁用无执行通过：`.sumika-next/p5-office-e53a72506b0543bc88df9f2656b5777c/report.json`，5次本机合成模型调用、0外部请求。Office库仍使用明确的host独立环境，不证明干净机器依赖完整。修复旧验收结果结构断言、物理包ACL脚本发现；生成工作目录Win32 5由上游诊断脚本仅修复该测试目录后通过。7项Office扩展测试通过，无产品或UI改动。

P5-1仍partial：自然语言自主任务质量、干净机器及任意复杂OOXML保真不在本次完成范围。旧文后面的“未视觉/未重算”是早期快照，不能覆盖本节证据。当前维护验收脚本超出r5构建时工具快照，不为纯工具更新重复复制全包。

复现：`python -X utf8 -B .agents/skills/sumika-office/scripts/run.py exec tools/verify_office_complex.py --soffice D:/Tools/LibreOffice/26.2.6/program/soffice.exe --out <不存在的新目录>`；原生复验设置`SUMIKA_TEST_CANDIDATE`后运行`python -X utf8 -B tools/verify_phase5_office.py --repair-fixture-acl`（只处理生成测试目录）。


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


## 接续：官方 Office 技能与随包依赖（r6）

2026-10-17 实时复核 npm 完整发布时间，最新仍为 `0.2.1-rc.2`，`next` 同版；`latest` 仍旧版。证据 `.sumika-next/acceptance-20261017/dsh-registry-final.json`。不追旧标签降级，不修改上游。

现成资产：直接使用官方 `dsh-skill-office` 和 `dsh-tool-workspace-dependencies`；改造已有 `ui/workbench.py` 的公开 profile 注册，以及已有 `extensions/office/requirements.lock` 的独立依赖载荷。没有新增界面入口。新载荷由 `tools/prepare_office_payload.py` 从既有 standalone Python 和哈希锁 wheel 构建，不依赖开发机 venv，不更改 PATH；构建可指定 `--office-runtime`。

内部候选 `E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r6` 库存 58139 文件通过。536 文件源码比对仅 `tools/verify_phase5_office.py` 在构建后增加验收模式；产品源码一致。源码全量 1326 项 /126.857 秒 OK、23 跳过；定向 42 项通过，既有警告保留。

真实 r6 原生宿主自动注册两个插件、7 个官方渐进式技能、`load_workspace_dependencies` 返回包内 Python、该 Python 经原生终端完成 DOCX/XLSX/PPTX/PDF 读建改重开均通过。证据 `.sumika-next/p5-office-2d26d5685e274eebac59fbcc3087fba1/report.json`；12 次 loopback 合成模型调用、0 外部调用，受管 DSH 已关闭。复现：设置 `SUMIKA_TEST_CANDIDATE` 后运行 `python -X utf8 -B tools/verify_phase5_office.py --native-office-workflow --repair-fixture-acl`，ACL 仅针对本次生成的工作目录。

边界：官方 LibreOfficeKit 引擎仍禁用（`cli:false`），不能把宿主 soffice 渲染验证算给它；当前载荷是已有五类库及锁定依赖，不含官方工具通用描述中的所有库（例如 numpy/pandas）。旧 `sumika-office` 开关只管旧 runner，不能撤销原生终端或官方技能。readiness 是存在性预检，局部 bridge 库遮住完整旧 office-env 的边界仍待处理。未部署/发布，未做干净机器验收，r5 的其他功能证据不自动继承到 r6。

补验：r6 实际 EXE 首启、实例复用、外部 HTTP 端口拒绝且保留、认证关停共4项通过；测试 Bridge 已停止。证据 `E:/SumikaBuild/acceptance-20261017-current/exe-startup-3b8f6dc2d6c84ad6a18c68d4b718e858/report.json`。`check`、`handoff`、`git diff --check`通过（已有换行符警告）。
