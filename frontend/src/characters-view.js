export function createCharactersView({
  avatarDriverLabel,
  avatarPreviewUrl,
  currentAvatarModel,
  currentAvatarPresentation,
  currentCharacter,
  currentPersonaConfig,
  escapeHtml,
  formatBytes,
  renderPageFrame,
  state,
}) {
  function renderCharacters() {
    const cards = state.characters.map((character) => {
      const model = state.avatarModels.find((item) => item.id === character.config?.avatar_model_id);
      const preview = avatarPreviewUrl(model);
      return `<article class="character-card ${character.id === state.selectedCharacter ? "selected" : ""}"><div class="character-art">${preview ? `<img class="character-art-image" src="${escapeHtml(preview)}" alt="${escapeHtml(model?.name || "Avatar 模型")}" />` : ""}<div class="character-art-copy"><span>${escapeHtml(avatarDriverLabel(character.config?.avatar_driver || "none"))}</span><strong>${escapeHtml(character.name)}</strong></div></div><div class="character-card-body"><div><strong>${escapeHtml(character.name)}</strong><small>${escapeHtml(model?.name || "未绑定 Avatar 模型")} · ${character.config?.memory_enabled ? "记忆已启用" : "记忆默认关闭"}</small></div><button class="small-button" data-character="${escapeHtml(character.id)}">${character.id === state.selectedCharacter ? "当前角色" : "使用"}</button></div></article>`;
    }).join("");
    const creating = state.characterCreating
      ? `<form class="character-create-panel" id="character-create-form">
          <strong>新建角色</strong>
          <label>名称<input name="character_name" type="text" maxlength="100" placeholder="例如：小雪" /></label>
          <label>角色卡（可选，SillyTavern JSON / PNG / CHARX）<input name="character_card" type="file" accept=".json,.png,.charx" /></label>
          <div class="character-create-actions"><button class="small-button" type="submit" ${state.characterBusy ? "disabled" : ""}>${state.characterBusy ? "创建中" : "创建"}</button><button class="ghost-button" type="button" data-character-create-cancel>取消</button></div>
          <p class="character-create-note">填了角色卡即从卡导入 persona（卡内 theme_color 会成为该角色的界面强调色）；不填则从空白配置开始。</p>
        </form>`
      : "";
    return renderPageFrame("角色", "角色 = 人设 + Avatar 绑定；选定角色后在下方编辑器里完成全部配置。", `<div class="character-grid">${cards}<button class="add-card" id="add-character"><span>＋</span><strong>新建角色</strong><small>空白开始或导入角色卡</small></button></div>${creating}${renderCharacterEditor()}`);
  }

  function personaSummary(persona) {
    const fields = [persona.traits, persona.relationship, persona.speakingStyle, persona.behavior, persona.boundaries, persona.systemPrompt, persona.greeting];
    const count = fields.filter((value) => value.trim()).length;
    const response = persona.responseLength === "balanced" ? "" : ` · ${persona.responseLength === "concise" ? "简洁" : "详细"}`;
    return count ? `已设置 ${count} 项${response}` : "尚未设置";
  }

  function avatarPositionLabel(position) {
    return ({ left: "左侧", center: "居中", right: "右侧" })[position] || "居中";
  }

  function avatarPresentationSummary(presentation) {
    return `${avatarPositionLabel(presentation.position)} · ${(presentation.opacity * 100).toFixed(0)}% · ${presentation.scale.toFixed(2)}x · ${presentation.idleMotion ? "待机开启" : "静态"}`;
  }

  function renderCharacterEditor() {
    const character = currentCharacter();
    const config = character.config || {};
    const persona = currentPersonaConfig();
    const presentation = currentAvatarPresentation();
    const notice = state.characterNotice ? `<div class="character-notice" role="status">${escapeHtml(state.characterNotice)}</div>` : "";
    const languageLabels = { "zh-CN": "简体中文", "zh-TW": "繁體中文", "ja-JP": "日本語", "en-US": "English" };
    const language = languageLabels[config.language] || config.language || "未设置语言";
    return `<section class="character-editor"><div class="character-editor-heading"><div><span class="eyebrow">CHARACTER EDITOR</span><strong>当前角色配置</strong><small>身份、人格、Avatar 模型和表现都按角色持久化。</small></div></div>${notice}<form id="character-form">
      <details class="character-settings-group" data-character-section="identity">
        <summary><span>角色身份</span><small>${escapeHtml(character.name)} · ${escapeHtml(language)}</small></summary>
        <div class="character-settings-body"><div class="character-settings-grid">
          <label class="character-field"><span>角色名称</span><input name="name" type="text" maxlength="100" value="${escapeHtml(character.name)}" required /></label>
          <label class="character-field"><span>语言</span><select name="language"><option value="zh-CN" ${config.language === "zh-CN" ? "selected" : ""}>简体中文（zh-CN）</option><option value="zh-TW" ${config.language === "zh-TW" ? "selected" : ""}>繁體中文（zh-TW）</option><option value="ja-JP" ${config.language === "ja-JP" ? "selected" : ""}>日本語（ja-JP）</option><option value="en-US" ${config.language === "en-US" ? "selected" : ""}>English（en-US）</option></select></label>
          <label class="character-field"><span>主题强调色</span><input name="theme_accent" type="color" value="${escapeHtml(/^#[0-9a-fA-F]{6}$/.test(String(config.theme?.accent || "")) ? config.theme.accent : "#6fd3b8")}" /></label>
          <label class="character-field character-field-inline"><span class="toggle-control"><input name="theme_accent_reset" type="checkbox" /><span>恢复默认强调色（忽略角色卡自带颜色）</span></span></label>
          <label class="character-field character-field-wide"><span>角色身份 / 定位</span><textarea name="persona_identity" rows="3" maxlength="4000" placeholder="例如：温和、可靠的学习搭档">${escapeHtml(persona.identity)}</textarea></label>
        </div></div>
      </details>
      <details class="character-settings-group" data-character-section="persona">
        <summary><span>人格设定</span><small>${escapeHtml(personaSummary(persona))}</small></summary>
        <div class="character-settings-body"><div class="character-settings-grid">
          <label class="character-field"><span>核心特质</span><textarea name="persona_traits" rows="3" maxlength="4000" placeholder="每行写一项特质">${escapeHtml(persona.traits)}</textarea></label>
          <label class="character-field"><span>与用户关系</span><textarea name="persona_relationship" rows="3" maxlength="2000" placeholder="例如：长期合作的伙伴">${escapeHtml(persona.relationship)}</textarea></label>
          <label class="character-field"><span>说话风格</span><textarea name="persona_speaking_style" rows="3" maxlength="3000" placeholder="例如：自然、口语化、少用套话">${escapeHtml(persona.speakingStyle)}</textarea></label>
          <label class="character-field"><span>行为习惯</span><textarea name="persona_behavior" rows="3" maxlength="3000" placeholder="描述角色通常如何回应">${escapeHtml(persona.behavior)}</textarea></label>
          <label class="character-field character-field-wide"><span>边界 / 禁忌</span><textarea name="persona_boundaries" rows="3" maxlength="3000" placeholder="描述不应做或不应说的内容">${escapeHtml(persona.boundaries)}</textarea></label>
          <label class="character-field"><span>回答长度</span><select name="persona_response_length"><option value="concise" ${persona.responseLength === "concise" ? "selected" : ""}>简洁</option><option value="balanced" ${persona.responseLength === "balanced" ? "selected" : ""}>平衡</option><option value="detailed" ${persona.responseLength === "detailed" ? "selected" : ""}>详细</option></select></label>
          <label class="character-field character-field-wide"><span>系统提示词</span><textarea name="system_prompt" rows="4" maxlength="20000" placeholder="补充需要长期遵循的指令">${escapeHtml(persona.systemPrompt)}</textarea></label>
          <label class="character-field character-field-wide"><span>首次问候</span><textarea name="greeting" rows="2" maxlength="2000" placeholder="新会话为空时显示，可选">${escapeHtml(persona.greeting)}</textarea></label>
        </div></div>
      </details>
      <details class="character-settings-group" data-character-section="avatar">
        <summary><span>Avatar 模型</span><small>${escapeHtml(currentAvatarModel()?.name || "未绑定模型")}</small></summary>
        <div class="character-settings-body">${renderAvatarLibrary()}</div>
      </details>
      <details class="character-settings-group" data-character-section="model">
        <summary><span>高级设置</span><small>模型表现 · ${escapeHtml(avatarPresentationSummary(presentation))}</small></summary>
        <div class="character-settings-body"><section class="character-settings-subsection"><div class="character-settings-subsection-heading"><strong>模型表现</strong><small>只影响当前角色的 Avatar 渲染，不修改模型文件。</small></div><div class="character-settings-grid">
          <label class="character-field"><span>Avatar 位置</span><select name="avatar_position"><option value="left" ${presentation.position === "left" ? "selected" : ""}>左侧</option><option value="center" ${presentation.position === "center" ? "selected" : ""}>居中</option><option value="right" ${presentation.position === "right" ? "selected" : ""}>右侧</option></select></label>
          <label class="character-field"><span>透明度 <output id="avatar-opacity-value">${presentation.opacity.toFixed(2)}</output></span><input name="avatar_opacity" type="range" min="0" max="1" step="0.05" value="${presentation.opacity}" data-range-output="avatar-opacity-value" /></label>
          <label class="character-field"><span>缩放 <output id="avatar-scale-value">${presentation.scale.toFixed(2)}</output></span><input name="avatar_scale" type="range" min="0.5" max="2.5" step="0.05" value="${presentation.scale}" data-range-output="avatar-scale-value" /></label>
          <div class="character-field character-field-toggle"><span>自然站姿</span><label class="toggle-control"><input name="avatar_natural_pose" type="checkbox" ${presentation.naturalPose ? "checked" : ""} /><span>运行时将 T 姿态调整为放松站姿</span></label></div>
          <div class="character-field character-field-toggle"><span>视线跟随</span><label class="toggle-control"><input name="avatar_look_at_enabled" type="checkbox" ${presentation.lookAtEnabled ? "checked" : ""} /><span>眼睛跟随 Avatar 舞台，缺少 LookAt 时安全降级</span></label></div>
          <label class="character-field"><span>视线强度 <output id="avatar-look-at-strength-value">${presentation.lookAtStrength.toFixed(2)}</output></span><input name="avatar_look_at_strength" type="range" min="0" max="1" step="0.05" value="${presentation.lookAtStrength}" data-range-output="avatar-look-at-strength-value" /></label>
          <div class="character-field character-field-toggle"><span>头部跟随</span><label class="toggle-control"><input name="avatar_head_follow_enabled" type="checkbox" ${presentation.headFollowEnabled ? "checked" : ""} /><span>头颈慢速小幅跟随，待机时保留呼吸动作</span></label></div>
          <label class="character-field"><span>头部强度 <output id="avatar-head-follow-strength-value">${presentation.headFollowStrength.toFixed(2)}</output></span><input name="avatar_head_follow_strength" type="range" min="0" max="1" step="0.05" value="${presentation.headFollowStrength}" data-range-output="avatar-head-follow-strength-value" /></label>
          <div class="character-field character-field-toggle"><span>待机动作</span><label class="toggle-control"><input name="avatar_idle_motion" type="checkbox" ${presentation.idleMotion ? "checked" : ""} /><span>呼吸、轻微摆动和眨眼（默认开启）</span></label></div>
          <div class="character-field character-field-toggle"><span>自动旋转</span><label class="toggle-control"><input name="avatar_auto_rotate" type="checkbox" ${presentation.autoRotate ? "checked" : ""} /><span>中心原地缓慢转身（默认关闭）</span></label></div>
          <label class="character-field"><span>旋转速度 <output id="avatar-rotation-speed-value">${presentation.rotationSpeed.toFixed(2)}</output></span><input name="avatar_rotation_speed" type="range" min="0.05" max="0.4" step="0.01" value="${presentation.rotationSpeed}" data-range-output="avatar-rotation-speed-value" /></label>
        </div></section></div>
      </details>
      <button class="small-button" type="submit" ${state.characterBusy ? "disabled" : ""}>${state.characterBusy ? "保存中" : "保存角色配置"}</button>
    </form></section>`;
  }

  function renderAvatarLibrary() {
    const notice = state.avatarNotice ? `<div class="avatar-notice" role="status">${escapeHtml(state.avatarNotice)}</div>` : "";
    const rows = state.avatarModels.length ? state.avatarModels.map((model) => {
      const bindings = state.characters.filter((character) => character.config?.avatar_model_id === model.id);
      const bindingText = bindings.length ? ` · 已绑定：${bindings.map((character) => character.name).join("、")}` : "";
      const boundToCurrent = currentCharacter().config?.avatar_model_id === model.id;
      const bindingHint = bindings.length ? `<small class="avatar-model-binding-hint">${boundToCurrent ? "当前角色已绑定" : `已绑定到：${escapeHtml(bindings.map((character) => character.name).join("、"))}`}</small>` : "";
      const origin = model.metadata?.bundled ? "随应用提供的示例" : "本地导入 · 不随应用分发";
      const availability = `${origin} · ${model.metadata?.availability === "available" ? "文件可用" : "文件状态待刷新"}`;
      const refreshing = state.avatarBusy === `refresh:${model.id}`;
      const inspecting = state.avatarBusy === `inspect:${model.id}`;
      const unregistering = state.avatarBusy === `unregister:${model.id}`;
      const bindingAction = boundToCurrent
        ? `<button class="small-button" data-avatar-clear="${escapeHtml(model.id)}" ${refreshing || unregistering ? "disabled" : ""}>解除当前角色绑定</button>`
        : `<button class="small-button" data-avatar-select="${escapeHtml(model.id)}" ${refreshing || unregistering ? "disabled" : ""}>绑定当前角色</button>`;
      const managed = model.metadata?.managed_directory === "assets/avatars" || model.metadata?.auto_discovered || model.metadata?.bundled;
      const removeLabel = managed ? "忽略" : "移除登记";
      const inspection = state.avatarInspections[model.id];
       return `<article class="avatar-model-row"><div class="avatar-model-type">${escapeHtml(model.kind.toUpperCase())}</div><div class="avatar-model-info"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.path)} · ${formatBytes(model.size_bytes)} · ${availability}${escapeHtml(bindingText)}</small>${bindingHint}${inspection ? renderAvatarInspection(inspection) : ""}</div><div class="avatar-model-actions">${bindingAction}<button class="outline-button" data-avatar-inspect="${escapeHtml(model.id)}" title="检查模型清单引用和文件完整性" ${inspecting || refreshing || unregistering ? "disabled" : ""}>${inspecting ? "检查中" : "检查"}</button><button class="outline-button" data-avatar-refresh="${escapeHtml(model.id)}" title="重新检查文件是否存在、大小和修改时间" ${refreshing || unregistering || inspecting ? "disabled" : ""}>${refreshing ? "刷新中" : "刷新"}</button><button class="ghost-button" data-avatar-unregister="${escapeHtml(model.id)}" title="${managed ? "从自动扫描中忽略，不删除原文件" : "移除登记，不删除原文件"}" ${refreshing || unregistering || inspecting ? "disabled" : ""}>${unregistering ? "处理中" : removeLabel}</button></div></article>`;
    }).join("") : `<div class="empty-panel">还没有登记模型。导入只登记元数据，不执行模型文件。</div>`;
    const availableIgnored = state.avatarIgnored.filter((model) => model.available);
    const missingIgnoredCount = state.avatarIgnored.filter((model) => !model.available).length;
    const ignoredRows = availableIgnored.length ? availableIgnored.map((model) => {
      const busy = state.avatarBusy === `restore:${model.path}`;
      return `<article class="avatar-model-row avatar-ignored-row"><div class="avatar-model-type">${escapeHtml(model.kind.toUpperCase())}</div><div class="avatar-model-info"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.path)} · ${formatBytes(model.size_bytes)} · 文件可用</small><small class="avatar-model-binding-hint">已忽略自动扫描；原文件未删除</small></div><div class="avatar-model-actions"><button class="small-button" data-avatar-restore="${escapeHtml(model.path)}" ${busy ? "disabled" : ""}>${busy ? "恢复中" : "恢复登记"}</button></div></article>`;
    }).join("") : `<div class="empty-panel">当前没有可恢复的已忽略模型。</div>`;
    const missingNotice = missingIgnoredCount ? `<div class="avatar-audit-summary" role="status"><span>有 ${missingIgnoredCount} 条失效忽略记录，路径当前不存在或不可访问，未确认模型已被删除。</span><button class="link-button" type="button" data-page="Developer">在开发者页审计 ↗</button></div>` : "";
    return `<section class="avatar-library"><div class="avatar-library-heading"><div><span class="eyebrow">AVATAR ASSETS</span><strong>本地模型</strong><small>VRM 可直接渲染；放入 assets/avatars 后可扫描登记。</small></div><div class="avatar-library-actions"><button class="outline-button" id="discover-avatar-assets" title="扫描仓库 assets/avatars 中的新模型" ${state.avatarBusy === "discover" ? "disabled" : ""}>${state.avatarBusy === "discover" ? "扫描中" : "扫描内置目录"}</button><button class="outline-button" id="import-avatar">选择模型文件</button></div></div>${notice}<div class="avatar-model-list">${rows}</div><section class="avatar-ignored"><div class="avatar-library-heading"><div><span class="eyebrow">IGNORED ASSETS</span><strong>已忽略模型</strong><small>恢复登记不会自动绑定当前角色。</small></div></div>${missingNotice}<div class="avatar-model-list">${ignoredRows}</div></section></section>`;
  }

  function renderAvatarAssetAudit() {
    const missing = state.avatarIgnored.filter((model) => !model.available);
    const availableCount = state.avatarIgnored.filter((model) => model.available).length;
    const notice = state.avatarBusy?.startsWith("clear-ignored:") ? "清除中" : "";
    const rows = missing.length ? missing.map((model) => {
      const busy = state.avatarBusy === `clear-ignored:${model.path}`;
      const reason = model.reason === "missing_or_inaccessible" ? "路径当前不存在或不可访问" : (model.reason || "缺少可恢复文件");
      return `<article class="avatar-audit-row"><div class="avatar-model-type">${escapeHtml(String(model.last_known_kind || model.kind).toUpperCase())}</div><div class="avatar-model-info"><strong>${escapeHtml(model.name)}</strong><small>${escapeHtml(model.path)}</small><small class="avatar-audit-reason">${escapeHtml(reason)} · 忽略墓碑仍会阻止自动登记</small></div><button class="ghost-button" type="button" data-avatar-ignored-clear="${escapeHtml(model.path)}" ${busy ? "disabled" : ""}>${busy ? "清除中" : "清除忽略记录"}</button></article>`;
    }).join("") : `<div class="empty-column">没有缺失的忽略墓碑。</div>`;
    return `<section class="dev-panel avatar-audit-panel"><div class="panel-heading"><div><strong>Avatar 资产审计</strong><small>缺失记录只保留路径墓碑，不代表已确认删除。清除仅修改本机元数据，不删除任何文件。</small></div><span class="muted-text">可用忽略 ${availableCount} 条</span></div>${notice ? `<div class="avatar-notice" role="status">${notice}</div>` : ""}<div class="avatar-audit-list">${rows}</div></section>`;
  }

  function renderAvatarInspection(inspection) {
    const statusLabel = ({ ready: "正常", warning: "有警告", error: "有错误" })[inspection.status] || inspection.status || "未知";
    const references = Array.isArray(inspection.referenced_files) ? inspection.referenced_files.length : 0;
    const details = [...(inspection.errors || []).slice(0, 2), ...(inspection.warnings || []).slice(0, 2)];
    const detailText = details.length ? ` · ${details.map((item) => escapeHtml(item)).join("；")}` : "";
    return `<div class="avatar-inspection" data-avatar-inspection><small>清单检查：${statusLabel} · 引用 ${references} 个文件${detailText}</small></div>`;
  }

  return { renderCharacters, renderAvatarAssetAudit };
}
