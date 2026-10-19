# Office 文件能力与验收边界

更新：2026-10-18。当前实现复用DSH官方Office技能、独立Python库和包内LibreOfficeKit，不另建编辑器。逐项点击方法见 [功能清单](feature-usage-and-acceptance.md)，当前证据统一见 [验收表](repair-and-acceptance-plan.md)。

## 已实现

- DOCX/XLSX/PPTX/PDF读取、创建、修改和重新读取；官方原生技能通过受管profile发现。
- 独立Python载荷通过原生依赖工具提供；含文件库、NumPy/Pandas及锁定依赖，不依赖开发机venv或全局PATH。
- 包内官方引擎用于DOCX/XLSX/PPTX转PDF、XLSX公式重算和文档页图像预览；写公式与公式计算分开验。
- 旧`sumika-office`仅为兼容入口，其enabled不控制官方技能，不撤销原生终端权限；所有工具仍走原生权限。

## 当前验证

r15包内引擎在当前Windows通过三格式PDF、公式缓存90/105/超预算、保留公式、两页DOCX PNG、坏文件拒绝与源SHA不变；两页PNG已目视，标题/表格/中文/页眉页脚及分页可读。报告：`.sumika-next/acceptance-20261018/office-r15/b3fdf3db8dfb43538f3d4415e258539e/report.json`。引擎报告Courier字体替换，不承诺相同字体度量。

较早原生宿主技能、依赖与读写链路通过属于其对应构建，不自动等于r15全项重验；详见 [归档](archive/20261018/phase-05-office-acceptance.md)。自然语言具体任务质量、任意复杂文档无损、干净机器及VC++v14前置仍待验。没有控制活动Word/Excel窗口的承诺；文件操作与桌面UIA为不同能力。

## 维护入口

- `tools/prepare_office_payload.py`：复用锁定wheel构建独立载荷。
- `tools/verify_phase5_office.py`：原生技能/依赖及工作流验证；设置`SUMIKA_TEST_CANDIDATE`明确目标。
- `tools/verify_office_native_engine.py --candidate <候选> --fixtures <结构化夹具目录> --output <证据目录>`：包内引擎转换/重算/渲染。
- `tools/verify_office_complex.py`：复杂结构夹具及宿主引擎对照；宿主soffice结果不能称包内引擎结果。

回退按程序/数据与依赖成对，保留源文件；不让旧程序读取不兼容新schema。旧库、宏、签名、任意PDF段落替换、安全涂黑与复杂OOXML无损不在已验承诺中。
