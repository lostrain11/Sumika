# Sumika 精选 DSH 插件索引

## 结论

Sumika **不实现第二套插件市场**，也不默认安装第三方市场。

- 安装、版本选择、兼容性判断、卸载：**DSH 原生 Plugins → Discover**
- Sumika：维护一份 **format 1 精选索引**，注入受管 DSH profile
- `dsh-market`：只作为可选实验，不与原生 Discover 同时默认启用

这样只有一个安装器、一个来源管理、一个卸载链路。

## 数据流

```text
community index (build time)
        │
        ▼
tools/build_sumika_plugin_catalog.py
        │  curated allowlist + pinned versions
        ▼
ui/app/plugin-catalog.json
        │
        ▼  GET /api/plugins/catalog
DSH plugin-market index source
        │
        ▼
DSH Plugins → Discover（安装/兼容/卸载）
```

运行时不抓取、不合并社区目录；目录更新通过重新生成并发布候选完成。

## 文件

| 文件 | 作用 |
|---|---|
| `tools/build_sumika_plugin_catalog.py` | 构建精选索引，固定版本/来源 |
| `ui/app/plugin-catalog.json` | 已生成的 format 1 索引 |
| `ui/server.py` | 只读公开路由 `/api/plugins/catalog` |
| `ui/workbench.py` | 在受管 profile 中启用原生 Discover 并登记索引源 |
| `ui/app/bind.js` | 能力页的“插件”状态卡，只作为工作台入口 |

## 精选范围

首版 7 项：

- `dsh-phone`：手机能力（GitHub-only，commit pin）
- `dsh-bili-scroll`：B站只读值班
- `dsh-bili-interact`：B站写操作，默认关闭
- `dsh-fish`：生活循环参考（不替代 Sumika 角色）
- `@kenz1117/dsh-engram`：记忆检索算法参考
- `dsh-pet-live2d`：Live2D 渲染参考
- `dshmarket`：第三方市场实验

`dsh-dot`（AGPL）和其他大型人格/代理框架不进入默认索引；需要时单独评估，不打包、不默认启用。

## 构建

```powershell
python -B tools/build_sumika_plugin_catalog.py
```

构建脚本会拉取社区 format 1 索引，按 allowlist 选取、去重、固定版本。也可以使用本地快照：

```powershell
python -B tools/build_sumika_plugin_catalog.py `
  --source 'E:\path\to\index.json' `
  --output 'ui\app\plugin-catalog.json'
```

生成后用 DSH 的解析器校验：

```powershell
node --input-type=module -e "
import {readFileSync} from 'node:fs';
import {parseMarketIndex} from 'file:///.../dsh-plugin-market-index/lib/index.js';
console.log(parseMarketIndex(JSON.parse(readFileSync('ui/app/plugin-catalog.json','utf8')), 'http://127.0.0.1:8766/api/plugins/catalog').plugins.length);
"
```

## 原生 Discover 的启用方式

DSH `0.2.1-rc.2` 默认关闭自定义市场 bundle。`ui/workbench.py` 在写入受管 profile 的 patch 时，幂等追加：

```json
{"insert": [
  {"id": "plugin-market", "name": "@deepseek-ai/dsh-plugin-market",
   "config": {"indexes": ["http://127.0.0.1:<bridge-port>/api/plugins/catalog"]}},
  {"id": "ui-plugin-market", "name": "@deepseek-ai/dsh-client-ui-plugin-market"}
]}
```

- 保留用户已有的 `plugin-market.config.indexes`
- 已存在时不重复追加
- `bridge_origin` 未知时不启用，避免写入错误端口

## 公开路由

`/api/plugins/catalog` 是唯一不要求 Sumika CSRF 的 API 路由，原因是 DSH 的 plugin-market Host 用进程 `fetch` 读取索引源，不带 Sumika token。

约束：

- 只返回 `ui/app/plugin-catalog.json`
- 不含用户数据、路径、凭据
- 无写入
- 固定 `Cache-Control: no-store`
- 索引文件缺失返回 503，不返回伪目录

## 兼容性与安全

- 索引只固定已选的版本；`engines.dsh` 由 DSH 原生兼容性检查读取
- 第三方插件按用户权限执行；“精选”不等于安全审计
- 不自动安装、不自动升级、不自动启用
- 插件失败不阻塞 Sumika 启动
- 不把第三方插件打进便携版或安装包
- `dsh-dot` 等 AGPL 插件不进入默认索引，避免许可混入

## 验证

- `tests_next/test_ui_workbench.py`：索引源注入及幂等
- `tests_next/test_ui_server.py`：公开目录可读且结构正确
- 构建脚本输出通过 DSH `parseMarketIndex`
- 真实 DSH 工作台的 Discover 能列出目录并显示兼容性（见候选验收记录）

## 验证记录（2026-10-27）

- r96 真实 DSH 工作台：Plugins 出现「发现」tab，标题为「Sumika 精选插件」，7 项全部显示；固定版本和日期正确（如 `dsh-phone 0.4.1 · 2026-10-26`）。
- 目录分类、标签、说明来自 `ui/app/plugin-catalog.json`。
- 当前测试 profile 未登录 DSH 账号，因此“安装按钮完成安装”仍未记入已验证；实际安装需在已登录的 DSH 环境完成。
- CLI 试验安装（独立空 profile，非日用数据）：
  - `dshmarket@1.70.2`：exit 0，可安装
  - `dsh-pet-live2d@3.3.3`：exit 0，可安装
  - `dsh-bili-scroll@2.1.0`：exit 0，可安装（Python/uv 依赖仍需首次运行准备）
  - `dsh-phone@0.4.1`：exit 0（Release tgz），Plugins 页显示“肥鱼的手机”
  - `dsh-fish@0.5.1`：exit 0（commit pin）
  - `dsh-bili-interact@0.0.9`：exit 0（commit pin）
  - `@kenz1117/dsh-engram`：exit 1，pnpm 因 `onnxruntime-node`/`protobufjs` 的 build script 被忽略而失败；目录已标为「实验 / 需批准构建脚本」
- 完整记录见 [插件实验室](plugin-lab-20261027.md)；目前 6 个安装步骤通过，0 个端到端功能验收。
- 公开路由 `/api/plugins/catalog` 返回 200；不使用 Sumika CSRF。

## 限制

- 原生 Discover 是实验 bundle；如果 DSH 升级后该 bundle 形态改变，需重新校准 loader row
- 目录中的 GitHub-only 条目使用 commit pin，升级需要人工改 allowlist
- 用户手动添加的其他 index source 不受 Sumika 审核，兼容性由 DSH 判断
- 当前索引不含 `dsh-computer-use` 等尚未完成来源审计的候选
