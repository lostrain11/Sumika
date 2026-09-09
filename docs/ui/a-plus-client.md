# A+ 正式客户端：阶段 0–2

## 范围与冻结规则

用户已选择 A 和风留白，并授权完成阶段 0、1、2。本阶段不包含 Windows 壁纸层、model-picker、新音视频、生活模拟、多助手或设备控制，不删除既有设计稿及运行数据。

- 阶段 0：冻结五个文字入口「陪伴、工作台、能力、角色、设置」，右侧聊天可收放，中性底色和四种主题强调色。
- 阶段 1：复用 [A+ 独立交互原型](concepts/a-plus-v1/README.md)，原型的壁纸构图只是演示，不作为原生实现。
- 阶段 2：接入真实客户端数据流；桌宠与完整客户端为同一个原生窗口的两种形态。保留同一助手、会话、草稿和 VRM 实例，页面切换不另启后台。

能力页按感知与交互、效率工具、生活与陪伴分组。已启用能力可首次投影到页面，手动移除后不自动加回；纯加号添加、排序和移除只写版本化本地布局。配置转到设置中的连接与权限；模块开关、设备授权和付费确认仍由既有 Runtime 控制。没有真实登记的 OCR、截屏翻译等项标记待实现，不假装可用。

## 实现边界

- [场景视图](../../frontend/src/a-plus-scene-view.js)与 [A+ 样式](../../frontend/src/a-plus-layout.css)：导航、可收放聊天、主题色及响应式布局；旧 `scene-view.js` 留作历史，不再由入口导入。
- [能力布局](../../frontend/src/capability-layout.js)与 [能力页](../../frontend/src/capability-page.js)：只读能力投影，独立布局持久化，键盘分类/模态框与焦点归还。未知配置和未声明授权保留未知。
- [VRM](../../frontend/src/vrm-viewer.js)与 [固定房间](../../frontend/src/home-room.js)：同画布渲染；保留已有待机、头眼跟随；抽屉、文档隐藏、原生最小化停止 RAF，恢复时不补算大段动画。房间是原创几何，不是自主生活系统。
- [原生窗口](../../src-tauri/src/main.rs)：`get_display_mode`、`set_display_mode`、`start_pet_drag`、`hide_pet` 只接受主窗口调用。pet 默认 480×420 逻辑像素、无边框、置顶；workspace 恢复位置/尺寸/最大化状态。应用步骤失败则回滚；回滚失败只允许恢复 workspace。
- `hide_pet` 恢复 workspace 后最小化到任务栏；退出仍关闭受管 Core。默认没有鼠标穿透、桌面置底或自动抢焦点。拖动排除输入框、按钮和显式 `data-no-drag`。
- 默认运行数据仍在 `.sumika-desktop`。测试可显式设置绝对路径 `SUMIKA_DESKTOP_DATA_DIR`，同时隔离 Core、日志、DSH 默认 profile 和门户存储；未设置时行为不变。

## 验证与复用

```powershell
npm --prefix frontend run test:unit
npm --prefix frontend run build
node tools/run-playwright.mjs --reporter=line
cargo test --manifest-path src-tauri/Cargo.toml --offline
cargo build --manifest-path src-tauri/Cargo.toml --features custom-protocol --offline
node tools/native-ui-smoke.mjs
```

`npm run build` 自动重建 VRM bundle，避免网页与桌面加载旧渲染器。Playwright 使用随机 loopback 端口和内存 Core，不连接日用 DSH。原生 smoke 使用新数据目录及 WebView2 profile、随机 Core/CDP 端口，选择仓库示例 VRM；退出后清理自己的进程及临时数据，保留无用户内容的截图和结果。结果默认在 `D:/Caches/sumika-ui-smoke/<timestamp>`。

2026-09-07 验收：前端单测 10/10、完整浏览器回归 62/62；追加渲染器加载失败用例后 A+ 专项 4/4；Rust 12/12；前端和 `custom-protocol` 桌面构建通过。1440×900、1280×800、390×844、480×420 截图及画布像素检查通过，既有 360/640/900/1280px 回归也通过。原生 150% DPI 下逻辑尺寸、单窗口、草稿、最大化、隐藏暂停、透明像素与退出清理 [7 项检查通过](evidence/a-plus-client-20260907/result.json)。不将原型证据、单机 DPI 或模拟拖动派发等同于多屏、真实 DSH 或壁纸实测。

最终截图：[客户端](evidence/a-plus-client-20260907/native-workspace.png)、[桌宠](evidence/a-plus-client-20260907/native-pet.png)、[透明桌宠](evidence/a-plus-client-20260907/native-pet-transparent.png)、[模块库](evidence/a-plus-client-20260907/native-module-library.png)、[设置](evidence/a-plus-client-20260907/native-settings.png)、[窄屏](evidence/a-plus-client-20260907/companion-mobile.png)。全部来自独立测试数据及示例 VRM，不是日用角色或私人对话。

隔离正式 UI 预览：`http://127.0.0.1:8879/`，进程 22920，仅内存 Core、Agent Runtime 禁用；关闭预览不影响日用数据。旧设计预览 `8878` 保留。日用客户端仍通过根目录启动入口运行；本轮没有启动日用实例或更换它的 Provider。

全项目文档检查仍受用户此前删除 `docs/requirements/original-excerpts.md` 的既有断链及摘录映射影响；没有重建该文件，也没有为通过检查删除需求。当前文档索引、状态映射与执行记录专项检查通过，排除 3 条既有摘录断链后新增文档错误为 0。

## 排查记录

- 保留的 Avatar 节点重新插入后可覆盖兄弟元素：场景按钮、气泡和 composer 使用明确层级；缩略图在 `.vrm-live` 时立即隐藏，避免跨画布叠影。
- 旧桌宠 CSS 把发送按钮 `font-size` 设为零并保留居中窄输入：A+ 显式重设宽度、对齐、字号和层级；480×420 截图及宽度断言覆盖。
- Tauri custom-protocol 页面与 Core 不同源：事件 WebSocket 必须等 `loadDesktopStatus` 解析真实 Core 端口后连接，否则启动时会错误访问页面自身主机并短暂报离线。
- 指南从共享导航生成，新页面必须有对应条目；缺项会抛错而留下旧页面。回归同时检查页面标题、地图和跳转。

## 后续

阶段 3 的桌面壁纸需另做 WorkerW/Explorer 生命周期、多显示器/DPI、Win+D、锁屏、图标和任务栏、退出恢复与输入焦点验收。当前原生双模式测试不证明这些能力已实现，也不证明真实 Provider 或 DSH 任务质量。
