export function createSettingsView({
  APPEARANCE_SWATCHES,
  NAV_ITEMS,
  escapeHtml,
  formatDate,
  glyph,
  pageLabel,
  readAppearance,
  renderQualitySettings,
  renderPageFrame,
  snapshotDiffCount,
  snapshotScopeLabel,
  snapshotTableLabel,
  snapshotTargetOptions,
  state,
}) {
  function renderGuide() {
    const pageDetails = {
      Chat: ["进行文字对话、切换会话、查看 Avatar 和实时状态；桌面端还可打开可拖动的桌宠模式。", "输入框、发送、新会话、Avatar 开关、桌宠模式"],
      Characters: ["通过折叠的身份、人格和高级设置管理每个角色，并单独处理 Avatar 资产绑定。", "展开分组、保存角色、导入/绑定模型"],
      Capabilities: ["感知与交互、效率工具、生活与陪伴。页面布局与功能启用、权限授予分离。", "添加、排序、移除、配置"],
      Modules: ["按能力启停模块，并为 LLM 选择可复用连接档案。", "开关、最近连接、配置抽屉、导入预览"],
      Tasks: ["查看任务生命周期、预算、权限、日志、产物和批准动作。", "创建任务、展开任务、批准/暂停/取消"],
      History: ["切换本地会话，浏览或维护按角色隔离的长期记忆。", "会话行、记忆新增/删除、模块跳转"],
      Notifications: ["按严重级别查看权限、失败、批准和恢复通知。", "筛选按钮、通知中的查看"],
      Settings: ["管理数据快照、导入导出、差异检查和恢复。", "快照范围、创建、选择、导出/恢复/导入"],
      Developer: ["检查 provider、扫描插件 manifest、配置外部启动器和查看事件。", "刷新、扫描、批准、配置、测试调用、撤销"],
      Agent: ["连接 Agent Runtime（当前默认 DSH），查看 Plan、工具调用、审批、MCP、Skills、Subagents 和浏览器策略。", "检查连接、切换模式、提交目标、创建隔离浏览器 Profile"],
      WebWorkbench: ["管理隔离网页 Profile，执行单次 Web Worker 或让多个网页模型独立提供意见。", "打开/聚焦网页、发送问题、启动咨询、接管或停止"],
    };
    const navigation = NAV_ITEMS
      .filter(([id]) => id !== "Guide")
      .map(([id, label]) => {
        const details = pageDetails[id];
        return '<article class="guide-map-item"><div class="guide-map-icon">' + glyph(id) + '</div><div class="guide-map-copy"><strong>' +
          escapeHtml(label) + '</strong><p>' + escapeHtml(details[0]) + '</p><small>可操作：' +
          escapeHtml(details[1]) + '</small></div><button class="small-button guide-jump" type="button" data-page="' +
          escapeHtml(id) + '">打开</button></article>';
      }).join("");
    const flow = [
      ["01", "启动并确认核心和隐私状态", "Windows 使用启动Sumika.bat。核心状态在场景左下角，处理位置在聊天输入区。", "Chat", "场景 / 聊天"],
      ["02", "选择角色与 Avatar", "角色页管理身份、人格与模型资源，聊天区选择当前角色。", "Characters", "角色"],
      ["03", "选择模型 Provider", "设置中的连接与权限负责 Provider 配置、测试和启用。", "Modules", "设置 / 连接与权限"],
      ["04", "只启用需要的模块", "能力页的加号只添加卡片。配置、启用和设备授权仍需分别完成；移除卡片不删除数据。", "Capabilities", "能力 / 配置"],
      ["05", "创建会话并发送第一条消息", "陪伴页右侧聊天可收起。切换桌宠保留当前会话和草稿，隐藏桌宠后可从任务栏恢复客户端。", "Chat", "聊天 / 桌宠"],
      ["06", "审计任务与结果", "需要长任务或外部工具时打开“工作台”：任务卡片展开详情，查看自治等级、预算、权限、日志和产物，并在“等待批准”时明确批准。重要提醒会进入“通知”，历史会话和记忆在“历史”查看。", "Tasks", "任务卡 / 通知筛选 / 历史会话"],
      ["07", "试用后创建恢复点", "打开“设置”抽屉，在数据与备份区域选择系统、模块、角色或记忆范围，创建命名快照。点击快照先看差异，再导出或恢复；恢复前核心会自动创建恢复前快照。", "Settings", "快照范围 / 创建 / 差异 / 恢复"],
    ].map(([number, title, text, page, location]) => {
      const targetLabel = pageLabel(page);
      return '<article class="guide-flow-item"><span class="guide-flow-number">' + number +
        '</span><div class="guide-flow-copy"><div class="guide-flow-heading"><strong>' + escapeHtml(title) +
        '</strong><span>' + escapeHtml(location) + '</span></div><p>' + escapeHtml(text) +
        '</p><button class="link-button guide-jump" type="button" data-page="' + escapeHtml(page) +
        '">前往' + escapeHtml(targetLabel) + ' ↗</button></div></article>';
    }).join("");
    return renderPageFrame("入门指南", "先了解界面地图，再按一条完整流程完成第一次本地对话。",
      '<div class="guide-intro"><div><span class="eyebrow">START HERE</span><strong>建议第一次按 01 → 07 顺序操作</strong><p>指南中的跳转按钮会打开对应页面；不会自动启用模块、授予权限、启动外部软件或改变数据。</p></div><button class="outline-button guide-jump" type="button" data-page="Chat">从聊天开始 ↗</button></div>' +
      '<section class="guide-section"><div class="guide-section-heading"><div><span class="eyebrow">WORKSPACE MAP</span><strong>界面地图</strong></div></div><div class="guide-map-grid">' + navigation + '</div></section>' +
      '<section class="guide-section"><div class="guide-section-heading"><div><span class="eyebrow">BASIC FLOW</span><strong>完整基本使用流程</strong><small>按顺序完成一次“配置 → 对话 → 审计 → 恢复点”闭环。</small></div></div><div class="guide-flow">' + flow + '</div></section>' +
      '<section class="guide-section guide-quick-reference"><div class="guide-section-heading"><div><span class="eyebrow">CONTROL SURFACE</span><strong>当前窗口的可操作位置</strong><small>顶部和聊天页上的控件是高频入口，复杂设置仍在对应页面完成。</small></div></div><div class="guide-control-grid">' +
        '<article><strong>顶部文字导航</strong><p>陪伴、工作台、能力、角色、设置。</p></article>' +
         '<article><strong>聊天与状态</strong><p>陪伴页右侧，桌宠模式位于底部。</p></article>' +
        '<article><strong>场景与对白框</strong><p>Avatar 常驻场景中央，左侧是对话流和对白框输入；“新会话”“发送”可直接操作。</p></article>' +
        '<article><strong>模块与权限</strong><p>已启用模块平铺为卡片，未启用的收进“＋ 添加模块”；连接档案、设备权限和运行按钮必须逐项确认。</p></article>' +
        '<article><strong>安全边界</strong><p>插件扫描不会执行代码；外部软件、任务和视觉采集都需要明确操作或批准。原始视觉数据默认即时丢弃。</p></article>' +
      '</div></section>' +
      '<section class="guide-section guide-reserved"><div class="guide-section-heading"><div><span class="eyebrow">CURRENT LIMITS</span><strong>首版中的预留入口</strong><small>这些控件保留了交互位置，但当前不会执行完整功能。</small></div></div><div class="guide-reserved-list">' +
         '<span>对白框“语音”圆钮：需先在模块页配置、授权并启动 ASR；随后会在本机录音并把识别文字填入输入框。</span><span>背景当前支持纯色与本地图片；视频与网页动态壁纸属于后续能力。</span><span>当前 Avatar 渲染器支持 VRM；其他模型格式可以保留登记信息，待对应驱动通过审核后再启用。</span>' +
      '</div></section>');
  }

  function renderSettings() {
    const appearance = readAppearance();
    const dataDir = state.diagnostics?.data_dir;
    return renderPageFrame("设置", "外观与本地数据。全部设置只保存在这台机器上。", `<div class="settings-stack"><section class="settings-section"><div class="section-label"><span>外观</span><small class="muted-text">纯色或本地图片背景；视频与网页动态壁纸属于后续能力</small></div><div class="appearance-row"><div class="appearance-swatches">${APPEARANCE_SWATCHES.map((swatch) => `<button class="appearance-swatch ${(!appearance.backgroundImage && (appearance.backgroundColor || "") === swatch.value) ? "active" : ""}" data-appearance-color="${swatch.value}" style="background:${swatch.value || "var(--scene-background)"}" title="${swatch.label}" aria-label="背景色：${swatch.label}"></button>`).join("")}</div><div class="appearance-image-actions"><input type="file" id="appearance-image" accept="image/*" hidden /><button class="outline-button" id="appearance-image-button" type="button">${appearance.backgroundImage ? "更换背景图" : "选择背景图"}</button>${appearance.backgroundImage ? '<button class="ghost-button" id="appearance-image-clear" type="button">清除背景图</button>' : ""}</div></div></section><section class="settings-section"><div class="section-label"><span>数据目录</span></div><div class="path-box">${escapeHtml(dataDir || "核心连接后显示")} <span>本地 SQLite · 未上传</span></div></section>${renderQualitySettings()}${renderSnapshotSettings()}</div>`);
  }

  function renderSnapshotSettings() {
    const notice = state.snapshotNotice ? `<div class="snapshot-notice" role="status">${escapeHtml(state.snapshotNotice)}</div>` : "";
    const busy = Boolean(state.snapshotBusy);
    const selected = state.snapshotDiff?.snapshot;
    const selectedDiff = state.snapshotDiff?.diff;
    const rows = state.snapshots.length ? state.snapshots.map((snapshot) => {
      const active = snapshot.id === state.selectedSnapshotId;
      const counts = Object.values(snapshot.table_counts || {}).reduce((total, value) => total + Number(value || 0), 0);
      return `<button class="snapshot-row ${active ? "active" : ""}" type="button" data-snapshot-select="${escapeHtml(snapshot.id)}"><span class="snapshot-icon">◫</span><span class="snapshot-row-main"><strong>${escapeHtml(snapshot.name)}</strong><small>${snapshotScopeLabel(snapshot.scope)}${snapshot.target_id ? ` · ${escapeHtml(snapshot.target_id)}` : ""} · ${formatDate(snapshot.created_at)}</small></span><span class="snapshot-row-meta">${counts} 条记录</span><span class="snapshot-chevron">›</span></button>`;
    }).join("") : `<div class="empty-panel">还没有命名快照</div>`;
    const diffPanel = selected && selectedDiff ? `<div class="snapshot-diff"><div class="snapshot-diff-heading"><div><span class="eyebrow">RESTORE REVIEW</span><strong>${escapeHtml(selected.name)}</strong><small>恢复前会自动生成同范围快照，事件审计不会被覆盖。</small></div><div class="snapshot-diff-actions"><button class="small-button" type="button" data-snapshot-export="${escapeHtml(selected.id)}" ${busy ? "disabled" : ""} title="导出未加密 JSON 快照包" aria-label="导出未加密 JSON 快照包">⇩ 导出</button><button class="small-button" type="button" data-snapshot-restore="${escapeHtml(selected.id)}" ${busy ? "disabled" : ""}>恢复此快照</button></div></div><div class="snapshot-diff-summary"><span class="${selectedDiff.changed ? "warn" : "ok"}">${selectedDiff.changed ? "检测到变更" : "当前已一致"}</span><span>${snapshotDiffCount(selectedDiff)} 个表有差异</span></div><div class="snapshot-diff-table">${selectedDiff.tables.map((table) => `<div class="snapshot-diff-row"><span>${snapshotTableLabel(table.table)}</span><span>新增 ${table.added} · 删除 ${table.removed} · 修改 ${table.changed}</span></div>`).join("")}</div></div>` : "";
    const scope = state.snapshotDraftScope || "system";
    const targetOptions = snapshotTargetOptions(scope);
    const targetControl = scope === "system" ? "" : `<select id="snapshot-target" aria-label="快照目标"><option value="">全部${snapshotScopeLabel(scope)}</option>${targetOptions.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.snapshotDraftTargetId ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select>`;
    return `<section class="settings-section snapshot-settings"><div class="snapshot-heading"><div><span class="eyebrow">DATA & BACKUPS</span><strong>命名快照</strong><small>会话、角色、模块和记忆分开保存；恢复前先查看差异。</small></div><div class="snapshot-create"><select id="snapshot-scope" aria-label="快照范围"><option value="system" ${scope === "system" ? "selected" : ""}>完整系统</option><option value="modules" ${scope === "modules" ? "selected" : ""}>模块设置</option><option value="characters" ${scope === "characters" ? "selected" : ""}>角色</option><option value="memories" ${scope === "memories" ? "selected" : ""}>记忆</option></select>${targetControl}<button class="outline-button" id="create-snapshot" type="button" ${busy ? "disabled" : ""}>创建快照</button><button class="outline-button" id="import-snapshot" type="button" ${busy ? "disabled" : ""} title="导入未加密 JSON 快照包" aria-label="导入未加密 JSON 快照包">⇧ 导入</button><input id="snapshot-file" type="file" accept="application/json,.json" hidden /></div></div>${notice}<div class="snapshot-list">${rows}</div>${diffPanel}</section>`;
  }

  return { renderGuide, renderSettings };
}
