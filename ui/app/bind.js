// Data binding for the D design shell: keeps the design markup and replaces the
// mock content with the real backend. Never presents mock data as real: the mock
// timeline and approval card are hidden once the real DSH instance is embedded.

const COLORS = [
  ['#c24e6e', '#f9e8ed'],
  ['#47746a', '#e9f1ee'],
  ['#7fb1c9', '#eaf3f8'],
  ['#c9a24a', '#f8f1dd'],
];

// The design shell carries its own stylesheet, so the frame styling is injected
// here instead of relying on a separate app stylesheet.
const style = document.createElement('style');
style.textContent = `
.sumika-dsh-frame { width: 100%; height: calc(100vh - 200px); min-height: 520px;
  border: 1px solid var(--line, #e2dccd); border-radius: 9px; background: #fff; margin: 10px 0; }
#screen-board { overflow: hidden; }
#sumika-workbench-frame { position: absolute; inset: 0; }
/* The design's floating deskpet still carries sample dialogue; it must not sit
   on top of the real workbench. */
body.on-board #deskpet { display: none; }
.wb-task { display: flex; align-items: center; gap: 8px; padding: 3px 6px;
  font-size: 12px; color: var(--muted, #7d8a86); }
.wb-task em { margin-left: auto; font-style: normal; opacity: .7; }
.roster .member em { display: block; font-size: 11px; font-style: normal; opacity: .65; }
`;
document.head.appendChild(style);

async function api(path, options) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = await response.json().catch(() => ({ error: 'invalid response' }));
  if (!response.ok) throw Object.assign(new Error(payload.error || payload.message || 'failed'), { payload });
  return payload;
}

function setText(selector, text) {
  const node = document.querySelector(selector);
  if (node) node.textContent = text;
}

function bindHeader(state) {
  setText('.model-chip', `${state.role?.model || '未配置模型'} ▾`);
  const proto = document.querySelector('.proto');
  if (proto) proto.textContent = state.session?.status === 'unknown' ? '后端未连接' : '真实后端 · 已连接';
}

function bindRoster(payload) {
  const roster = document.querySelector('.roster');
  if (!roster) return;
  const roles = (payload.roles || []).filter(role => (role.assets || []).length > 0);
  const activeId = payload.active?.id;
  roster.querySelectorAll('.member').forEach(node => node.remove());
  const anchor = roster.querySelector('h3');
  roles.forEach((role, index) => {
    const [color, soft] = COLORS[index % COLORS.length];
    const button = document.createElement('button');
    button.className = 'member' + (role.id === activeId ? ' active' : '');
    button.dataset.name = role.name;
    button.dataset.sub = role.has_model_3d ? '实机 VRM · 已绑定模型' : '角色卡 · 立绘占位';
    button.dataset.color = color;
    button.dataset.soft = soft;
    button.dataset.speech = `${role.name}：准备好了。`;
    button.dataset.roleId = role.id;
    button.innerHTML = `<i style="background:${color}"></i><span>${role.name}</span>`
      + `<em>${button.dataset.sub}</em>`;
    button.addEventListener('click', async () => {
      document.querySelectorAll('.roster .member').forEach(node => node.classList.remove('active'));
      button.classList.add('active');
      try {
        await api('/api/roles/select', { method: 'POST', body: JSON.stringify({ id: role.id }) });
        setText('#roomOwner', `${role.name}的房间`);
        setText('#chatChara', role.name);
        setText('#atChip', `@${role.name}`);
        setText('#stageChara', role.name);
        // Each role keeps its own session, so switching reloads that transcript.
        await loadRoomChat(role.id);
      } catch (error) {
        setText('#roomOwner', `切换失败：${error.message}`);
      }
    });
    if (anchor && anchor.nextSibling) roster.insertBefore(button, anchor.nextSibling);
    else roster.appendChild(button);
  });
  const count = document.getElementById('memberCount');
  if (count) count.textContent = String(roles.length);
  // The design's placeholder assistant is called 澄花; every surface that shows
  // the speaking role must follow the active one instead.
  const active = roles.find(role => role.id === activeId);
  if (active) {
    setText('#chatChara', active.name);
    setText('#stageChara', active.name);
    setText('#roomOwner', `${active.name}的房间`);
    setText('#atChip', `@${active.name}`);
    const sub = document.getElementById('stageCharaSub');
    if (sub && active.has_model_3d) sub.textContent = '实机 VRM · 已绑定模型';
    else if (sub) sub.textContent = '角色卡 · 立绘占位';
  }
  const hidden = (payload.roles || []).length - roles.length;
  if (hidden > 0) {
    const note = document.createElement('p');
    note.className = 'hint';
    note.style.margin = '4px 0 0';
    note.textContent = `已隐藏 ${hidden} 个没有角色卡的导入记录`;
    roster.appendChild(note);
  }
}

// ---- 活动室对话（真实角色服务） ---------------------------------------------
//
// The design's chat column shipped with sample messages and an inert composer.
// Both are replaced: the transcript comes from the bridge for this role's own
// session, and a failure is shown as a failure instead of a plausible reply.

let roomChatRoleId = null;

function roomSessionId(roleId) {
  return `room-${roleId || 'default'}`;
}

function roomMessageNode({ who, text, at, isError }) {
  const mine = who === 'me';
  const name = document.getElementById('chatChara')?.textContent || '她';
  const node = document.createElement('div');
  node.className = `cm ${mine ? 'user' : 'agent'}`;
  if (isError) node.dataset.roomError = '1';
  const label = document.createElement('span');
  label.className = 'who';
  label.textContent = mine ? `我 · ${(at || '').slice(11, 16)}` : `${name} · ${(at || '').slice(11, 16)}`;
  const bubble = document.createElement('div');
  bubble.className = 'bub';
  bubble.textContent = text;
  if (isError) {
    bubble.style.color = '#b04a4a';
    bubble.style.borderColor = '#e0b3b3';
  }
  node.append(label, bubble);
  return node;
}

function renderRoomMessages(messages) {
  const list = document.querySelector('#screen-room .chat-msgs');
  if (!list) return;
  list.textContent = '';
  // The stage bubble repeats the latest real line instead of the design's
  // invented greeting, so nothing on this screen speaks without a source.
  const bubble = document.getElementById('speechBub');
  const lastRole = [...(messages || [])].reverse().find(message => message.who !== 'me');
  if (bubble) {
    bubble.textContent = lastRole?.text
      || '还没有对话。在下面发一句，她的回答会出现在这里和右侧对话栏。';
  }
  if (!messages || messages.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'cm agent';
    empty.dataset.roomEmpty = '1';
    const label = document.createElement('span');
    label.className = 'who';
    label.textContent = '还没有对话记录';
    const bubble = document.createElement('div');
    bubble.className = 'bub';
    bubble.textContent = '在下面输入第一句话。角色模型没配置好时这里会如实报错，不会替她编答案。';
    empty.append(label, bubble);
    list.appendChild(empty);
    return;
  }
  messages.forEach(message => list.appendChild(roomMessageNode(message)));
  list.scrollTop = list.scrollHeight;
}

async function loadRoomChat(roleId) {
  roomChatRoleId = roleId || null;
  const session = encodeURIComponent(roomSessionId(roleId));
  const payload = await api(`/api/role/chat/history?session=${session}`);
  renderRoomMessages(payload.messages || []);
  window.sumikaDeskpet?.reload?.();
}

async function sendRoomMessage(text) {
  const list = document.querySelector('#screen-room .chat-msgs');
  if (!list) return;
  // The empty-state bubble is not a message: drop it before the first real one.
  list.querySelector('[data-room-empty]')?.remove();
  const stamp = new Date().toISOString();
  list.appendChild(roomMessageNode({ who: 'me', text, at: stamp }));
  list.scrollTop = list.scrollHeight;
  try {
    const result = await api('/api/role/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, session: roomSessionId(roomChatRoleId) }),
    });
    const reply = typeof result.text === 'string' ? result.text.trim() : '';
    list.appendChild(roomMessageNode({
      who: 'role', at: new Date().toISOString(),
      text: reply || '（模型没有返回文本）', isError: !reply,
    }));
  } catch (error) {
    const detail = (error.payload || {}).message || error.message;
    list.appendChild(roomMessageNode({
      who: 'role', at: new Date().toISOString(), text: `发送失败：${detail}`, isError: true,
    }));
  }
  list.scrollTop = list.scrollHeight;
  window.sumikaDeskpet?.reload?.();
}

async function bindRoomChat(activeRoleId) {
  const composer = document.querySelector('#screen-room .chat-composer');
  if (!composer) return;
  // Shared with the floating deskpet so both surfaces speak to one session.
  window.sumikaRoomSession = () => roomSessionId(roomChatRoleId);
  window.sumikaRoomReload = () => loadRoomChat(roomChatRoleId);
  const field = composer.querySelector('.input');
  let input = field;
  if (field && field.tagName !== 'INPUT') {
    input = document.createElement('input');
    input.type = 'text';
    input.className = field.className;
    input.placeholder = '说点什么…';
    input.setAttribute('data-room-input', '');
    input.style.cssText = 'border:none;background:transparent;outline:none;'
      + 'font:inherit;color:inherit;width:100%;min-width:0';
    field.replaceWith(input);
  }
  const submit = () => {
    const text = (input?.value || '').trim();
    if (!text) return;
    if (input) input.value = '';
    sendRoomMessage(text);
  };
  input?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  });
  composer.querySelector('#sendBtn')?.addEventListener('click', submit);
  await loadRoomChat(activeRoleId);
}

function bindTree(tree) {
  const side = document.querySelector('.wb-side');
  if (!side || !tree.phases) return;
  side.querySelectorAll('.wb-proj').forEach(node => node.remove());
  const project = document.createElement('div');
  project.className = 'wb-proj open';
  const phases = tree.phases.slice(0, 9);
  project.innerHTML = `<button class="wb-proj-head">`
    + `<i class="dot" style="background:var(--rose)"></i>`
    + `<span class="nm">${tree.project?.name?.slice(0, 24) || 'sumika-next'}`
    + `<small>${tree.project?.path || ''}</small></span>`
    + `<b>${phases.length}</b></button>`;
  const body = document.createElement('div');
  body.className = 'wb-proj-body';
  phases.forEach(phase => {
    const dot = phase.status === 'complete' ? '#6f9c7a'
      : (phase.status === 'planned' ? '#cbbfa6' : 'var(--rose)');
    const row = document.createElement('div');
    row.className = 'wb-task';
    row.innerHTML = `<i class="dot" style="background:${dot}"></i>`
      + `<span>${phase.id} · ${phase.name}</span>`
      + `<em>${(phase.tasks || []).length} 项</em>`;
    body.appendChild(row);
  });
  project.appendChild(body);
  const anchor = side.querySelector('.wb-search');
  if (anchor) anchor.after(project);
  else side.appendChild(project);
  side.querySelectorAll('.wb-proj-head').forEach(head => {
    head.addEventListener('click', () => head.parentElement.classList.toggle('open'));
  });
}

/**
 * Make sure the managed instance is up and hand back the URL the workbench
 * screen frames. Never navigates: the workbench is a screen of this page, so the
 * user stays in the shell.
 */
async function ensureWorkbenchUrl() {
  let status;
  try {
    status = await api('/api/workbench');
    if (!status.running) {
      status = await api('/api/workbench/start', {
        method: 'POST', body: JSON.stringify({ port: 5175 }),
      });
    }
    if (!status.embed_ready) return { url: null, error: 'DSH 实例未就绪' };
    const { url } = await api('/api/workbench/embed');
    if (!url) return { url: null, error: 'DSH 未返回可用地址' };
    return { url, error: null };
  } catch (error) {
    const message = (error.payload || {}).message || error.message;
    return { url: null, error: message };
  }
}

async function bindWorkbench() {
  const main = document.querySelector('.wb-main');
  if (!main) return;
  // The design ships a mock room/chat widget on the workbench screen. It stays
  // visible for layout fidelity but must be labelled, never mistaken for real data.
  // The floating deskpet widget is global (not part of the board markup) and
  // still carries the design's sample character and log lines.
  const roomWidget = document.querySelector('#deskpet, .deskpet, .wb-wrap .room-widget, .wb-wrap aside.room');
  if (roomWidget && !roomWidget.querySelector('.sumika-mock-tag')) {
    const tag = document.createElement('span');
    tag.className = 'sumika-mock-tag';
    tag.textContent = '设计示例数据';
    tag.style.cssText = 'position:absolute;top:6px;right:8px;font-size:10px;padding:1px 6px;'
      + 'border:1px solid var(--line,#e2dccd);border-radius:999px;color:var(--muted,#7d8a86);'
      + 'background:rgba(255,253,247,.9);z-index:5';
    roomWidget.style.position = 'relative';
    roomWidget.appendChild(tag);
  }
  let status;
  try {
    status = await api('/api/workbench');
    if (!status.running) status = await api('/api/workbench/start', {
      method: 'POST', body: JSON.stringify({ port: 5175 }),
    });
  } catch (error) {
    setText('.wb-crumb', `工作台启动失败：${(error.payload || {}).message || error.message}`);
    return;
  }
  let url = null;
  if (status.embed_ready) url = (await api('/api/workbench/embed')).url;

  // The workbench screen *is* the DSH front end: the managed instance renders
  // into this screen, under the shell's own top bar, skinned by DSH's own
  // index-injection hook. The design's mock board markup is replaced rather than
  // layered, so nothing mock sits on top of the real workbench.
  const screen = document.querySelector('#screen-board');
  const wrap = screen?.querySelector('.wb-wrap');
  if (!screen || !wrap) return;
  wrap.querySelectorAll('.wb-timeline, .confirm-d').forEach(node => node.remove());

  if (url) {
    const frame = document.createElement('iframe');
    frame.id = 'sumika-workbench-frame';
    frame.title = 'Sumika 工作台（受管 DSH）';
    frame.src = url;
    frame.style.cssText = 'width:100%;height:100%;border:0;display:block;background:var(--paper,#fffdf8)';
    wrap.replaceWith(frame);
    if (document.querySelector('#gnav button[data-go="board"]')) {
      document.querySelector('#gnav button[data-go="board"]').dataset.sumikaBound = '1';
    }
  } else {
    const card = document.createElement('div');
    card.style.cssText = 'margin:14px 0;padding:16px;border:1px solid var(--line,#e2dccd);'
      + 'border-radius:9px;background:var(--panel,#fffdf7)';
    card.innerHTML = '<p style="margin:0 0 10px">DSH 实例未就绪，工作台暂时无法显示。</p>'
      + '<button class="sumika-open-dsh" style="padding:6px 14px">重试</button>';
    card.querySelector('.sumika-open-dsh')
      .addEventListener('click', async () => { await ensureWorkbenchUrl(); location.reload(); });
    const head = main.querySelector('.wb-head');
    (head || main).after(card);
    setText('.wb-crumb', '受管 DSH · 未就绪');
  }
}

// ---- capability switches (R-107/R-108) -------------------------------------
//
// Readiness and enablement are two different facts and are shown as such:
// /api/readiness says the dependency is present, /api/modules is the registry the
// executors actually consult. A capability that has no registry entry has no
// switch here — it must not look controllable.

const NATIVE_CARDS = [
  { icon: '⌨', title: '终端执行', text: '受管终端命令、测试与构建，高危操作进入待确认。' },
  { icon: '✎', title: '文件编辑', text: '代码搜索、阅读与补丁写入，写入前创建检查点。' },
  { icon: '⧉', title: '子代理', text: '独立任务与代码审查交由原生子 Agent，可并行。' },
  { icon: '❖', title: 'Skills', text: '领域技能包，安装前经安全审查。' },
  { icon: '⬡', title: 'MCP 连接', text: '第三方工具服务器，按来源与作用域显式授权。' },
];

/** Design's `.sw2` switch, wired to a real toggle. */
function switchElement(enabled, onToggle) {
  const node = document.createElement('span');
  node.className = 'sw2' + (enabled ? ' on' : '');
  node.setAttribute('role', 'switch');
  node.setAttribute('aria-checked', enabled ? 'true' : 'false');
  node.setAttribute('data-capability-switch', '');
  node.tabIndex = 0;
  node.style.cursor = 'pointer';
  const fire = () => onToggle(!enabled);
  node.addEventListener('click', fire);
  node.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      fire();
    }
  });
  return node;
}

function statusPill(text, variant) {
  const node = document.createElement('span');
  node.className = `st ${variant}`;
  node.textContent = text;
  return node;
}

function capabilityCard({ icon, title, status, statusClass, text, source, enabled, onToggle,
                          capabilityId }) {
  const card = document.createElement('div');
  card.className = 'cap-card';
  if (capabilityId) card.dataset.capabilityId = capabilityId;
  const top = document.createElement('div');
  top.className = 'top';
  const glyph = document.createElement('div');
  glyph.className = 'cap-ic';
  glyph.style.background = 'var(--green-soft)';
  glyph.textContent = icon;
  const heading = document.createElement('h4');
  heading.textContent = title;
  top.append(glyph, heading);
  if (status) top.appendChild(statusPill(status, statusClass));
  const body = document.createElement('p');
  body.textContent = text;
  const foot = document.createElement('div');
  foot.className = 'foot';
  const origin = document.createElement('span');
  origin.className = 'src';
  origin.textContent = source;
  foot.appendChild(origin);
  if (typeof onToggle === 'function') foot.appendChild(switchElement(enabled, onToggle));
  card.append(top, body, foot);
  return card;
}

async function capabilityState() {
  const [modules, readiness] = await Promise.all([api('/api/modules'), api('/api/readiness')]);
  return { modules: modules.modules || [], readiness: readiness.capabilities || [] };
}

async function toggleCapability(id, enabled) {
  await api('/api/capabilities/toggle', {
    method: 'POST',
    body: JSON.stringify({ id, enabled }),
  });
}

function setNote(node, text, ok) {
  if (!node) return;
  node.textContent = text;
  node.style.color = ok ? '' : 'var(--danger, #b04a4a)';
}

/** Fill one `.kv` row in an info panel, keeping the panel's own markup. */
function setRow(panel, label, value, ok) {
  const row = Array.from(panel.querySelectorAll('.kv'))
    .find(node => node.querySelector('span')?.textContent.trim() === label);
  if (!row) return;
  const target = row.querySelector('b');
  if (!target) return;
  target.textContent = value;
  target.classList.toggle('ok', ok === true);
}

/** The capability detail panel mirrors the selected card; never invents values. */
function renderCapabilityDetail(card, entry, readinessRow, version) {
  const side = document.querySelector('.cap-side');
  if (!side) return;
  const hero = side.querySelector('.hero-d');
  if (hero) {
    const glyph = hero.querySelector('.cap-ic');
    const title = hero.querySelector('h4');
    const text = hero.querySelector('p');
    if (title) title.textContent = entry?.label || card?.querySelector('h4')?.textContent || '未选择';
    if (text) {
      text.textContent = entry?.purpose || readinessRow?.detail
        || '点选左侧卡片查看这一项的真实来源与状态';
    }
    if (glyph) glyph.textContent = card?.querySelector('.cap-ic')?.textContent || '◈';
  }
  const panels = side.querySelectorAll('.panel');
  if (panels[0]) {
    if (entry) {
      setRow(panels[0], '状态', entry.enabled ? '已启用' : '已停用', entry.enabled);
      setRow(panels[0], '来源', `注册表 · ${entry.provider}`);
      setRow(panels[0], '版本', '—');
      setRow(panels[0], '权限', '执行前经授权与审批');
      setRow(panels[0], '数据', '仅本机 · 不上传');
    } else if (readinessRow) {
      setRow(panels[0], '状态', readinessRow.ready ? '依赖就绪 · 未登记' : '依赖缺失', false);
      setRow(panels[0], '来源', '就绪检查');
      setRow(panels[0], '版本', '—');
      setRow(panels[0], '权限', '—');
      setRow(panels[0], '数据', '仅本机 · 不上传');
    } else {
      setRow(panels[0], '状态', 'Harness 自带', true);
      setRow(panels[0], '来源', 'DSH 原生');
      setRow(panels[0], '版本', version || '—');
      setRow(panels[0], '权限', '由 DSH 权限策略管理');
      setRow(panels[0], '数据', '仅本机 · 不上传');
    }
  }
}

async function bindCapabilityScreens() {
  const shelf = document.querySelector('#screen-shelf .cap-main');
  const settingsGroup = Array.from(document.querySelectorAll('#screen-settings .set-group'))
    .find(group => /能力模块/.test(group.querySelector('h2')?.textContent || ''));
  if (!shelf && !settingsGroup) return;

  const render = async () => {
    const { modules, readiness } = await capabilityState();
    const release = await api('/api/workbench').then(status => status.version).catch(() => null);
    const registered = new Set(modules.map(item => item.id));
    const runToggle = async (id, enabled) => {
      try {
        await toggleCapability(id, enabled);
      } catch (error) {
        setNote(document.querySelector('#capability-note'), `切换失败：${error.message}`, false);
      }
      await render();
    };

    if (shelf) {
      const head = shelf.querySelector('.cap-head');
      shelf.querySelectorAll('.cap-group').forEach(node => node.remove());

      const note = document.createElement('span');
      note.className = 'cap-note';
      note.id = 'capability-note';
      note.textContent = '✓ 配置仅保存于本机 · 开关即时生效';
      if (head) {
        const existing = head.querySelector('.cap-note');
        if (existing) existing.replaceWith(note);
        else head.appendChild(note);
      }

      const registryGroup = document.createElement('section');
      registryGroup.className = 'cap-group';
      registryGroup.innerHTML = '<h2><b>扩展模块</b> 独立扩展层 · 可开关</h2>';
      const registryGrid = document.createElement('div');
      registryGrid.className = 'cap-grid';
      if (modules.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'hint';
        empty.textContent = '注册表为空：本机没有可执行的能力，或注册表文件尚未创建。'
          + '启动一次桥接会按真实依赖补齐缺失项（见 docs/project/capability-registry.md）。';
        registryGroup.appendChild(empty);
      }
      modules.forEach(item => {
        registryGrid.appendChild(capabilityCard({
          icon: '◈',
          title: item.label || item.id,
          status: item.enabled ? '已启用' : '已停用',
          statusClass: item.enabled ? 'on' : 'rsv',
          text: `${item.purpose || ''}${item.purpose ? ' ' : ''}实现：${item.provider}`,
          source: `扩展 ${item.id}`,
          capabilityId: item.id,
          enabled: item.enabled,
          onToggle: next => runToggle(item.id, next),
        }));
      });
      registryGroup.appendChild(registryGrid);
      shelf.appendChild(registryGroup);

      const readyOnly = readiness.filter(item => !registered.has(item.id));
      const readyGroup = document.createElement('section');
      readyGroup.className = 'cap-group';
      readyGroup.innerHTML = '<h2><b>就绪视图</b> 依赖检查 · 无独立开关</h2>';
      const readyGrid = document.createElement('div');
      readyGrid.className = 'cap-grid';
      readyOnly.forEach(item => {
        readyGrid.appendChild(capabilityCard({
          icon: item.ready ? '✓' : '—',
          title: item.label || item.id,
          status: item.ready ? '就绪' : '不可用',
          statusClass: item.ready ? 'basic' : 'rsv',
          text: item.detail || '',
          source: `就绪检查 ${item.id}`,
        }));
      });
      readyGroup.appendChild(readyGrid);
      shelf.appendChild(readyGroup);

      const nativeGroup = document.createElement('section');
      nativeGroup.className = 'cap-group';
      nativeGroup.innerHTML = '<h2><b>DSH 原生</b> 由 Harness 自带 · 不由 Sumika 开关</h2>';
      const nativeGrid = document.createElement('div');
      nativeGrid.className = 'cap-grid';
      NATIVE_CARDS.forEach(card => {
        nativeGrid.appendChild(capabilityCard({
          icon: card.icon, title: card.title, status: '原生', statusClass: 'basic',
          text: card.text, source: 'DSH 原生',
        }));
      });
      nativeGroup.appendChild(nativeGrid);
      shelf.appendChild(nativeGroup);

      // Clicking a card fills the detail column; the first registry entry is the
      // default so the panel never shows a capability that is not present.
      const detail = [
        ...modules.map(item => ({ card: null, entry: item, readinessRow: null })),
        ...readyOnly.map(item => ({ card: null, entry: null, readinessRow: item })),
        ...NATIVE_CARDS.map(item => ({ card: null, entry: null, readinessRow: null })),
      ];
      const cards = Array.from(shelf.querySelectorAll('.cap-card'));
      cards.forEach((card, index) => {
        if (index < detail.length) detail[index].card = card;
        card.style.cursor = 'pointer';
        card.setAttribute('tabindex', '0');
        const select = () => {
          const target = detail.find(entry => entry.card === card);
          renderCapabilityDetail(card, target?.entry, target?.readinessRow, release);
        };
        card.addEventListener('click', event => {
          if (event.target.closest('[data-capability-switch]')) return;
          select();
        });
        card.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); }
        });
      });
      const first = cards[0];
      if (first && detail[0]) renderCapabilityDetail(first, detail[0].entry, null, release);

      const side = document.querySelector('.cap-side');
      const panels = side ? side.querySelectorAll('.panel') : [];
      if (panels[1]) {
        const enabledCount = modules.filter(item => item.enabled).length;
        const unavailable = readiness.filter(item => !item.ready).length;
        const cells = panels[1].querySelectorAll('.st-grid > div');
        const values = [enabledCount, modules.length - enabledCount, unavailable];
        cells.forEach((cell, index) => {
          const number = cell.querySelector('b');
          if (number && values[index] !== undefined) number.textContent = String(values[index]);
        });
        const heading = panels[1].querySelector('h3 b');
        if (heading) heading.textContent = `${modules.length} 个已登记`;
      }
      if (panels[2]) {
        const notes = panels[2].querySelector('.note-p');
        if (notes) {
          notes.innerHTML = '① 关闭开关只停用能力，历史数据与授权记录保留；<br>'
            + '② 「就绪」表示依赖已安装，与「已启用」分别显示，不互相代替；<br>'
            + '③ 权限、MCP 与凭据在设置 ·「连接与权限」内管理。';
        }
      }
    }

    if (settingsGroup) {
      const card = settingsGroup.querySelector('.set-card');
      if (card) {
        card.textContent = '';
        const summary = document.createElement('div');
        summary.className = 'set-row';
        const enabledCount = modules.filter(item => item.enabled).length;
        const unavailable = readiness.filter(item => !item.ready).length;
        summary.innerHTML = '<div>模块总览<small>关闭仅停用，数据与配置保留（enabled 契约）</small></div>'
          + `<div class="val"><b>${enabledCount} 已启用 · ${modules.length - enabledCount} 已停用 · `
          + `${unavailable} 不可用</b><button class="mini-btn">打开能力页 →</button></div>`;
        // The design shell's own inline script owns screen switching by hash.
        summary.querySelector('button').addEventListener('click', () => { location.hash = 'shelf'; });
        card.appendChild(summary);

        modules.forEach(item => {
          const row = document.createElement('div');
          row.className = 'set-row';
          row.dataset.capabilityId = item.id;
          const label = document.createElement('div');
          label.innerHTML = `${item.label || item.id}<small>${item.purpose || ''} · ${item.provider}</small>`;
          row.appendChild(label);
          const holder = document.createElement('span');
          holder.style.marginLeft = 'auto';
          holder.appendChild(switchElement(item.enabled, next => runToggle(item.id, next)));
          row.appendChild(holder);
          card.appendChild(row);
        });

        const dshRow = document.createElement('div');
        dshRow.className = 'set-row';
        dshRow.innerHTML = '<div>连续记录 · 自动捕获<small>属于 DSH 侧插件，开关在 DSH 自己的插件清单里，'
          + '因此这里不重复提供一个不生效的开关</small></div>';
        card.appendChild(dshRow);
      }
    }
  };

  try {
    await render();
  } catch (error) {
    setNote(document.querySelector('.cap-note'), `能力数据读取失败：${error.message}`, false);
  }
}

/**
 * Settings facts that really are facts: the harness release from the managed
 * instance, the project the records describe, and the role service's own model.
 * The working model and the DSH credential live in the harness and are handed
 * over to it instead of being restated here.
 */
async function bindSettingsFacts(tree) {
  const [status, state] = await Promise.all([
    api('/api/workbench').catch(() => null),
    api('/api/state').catch(() => null),
  ]);

  const side = document.querySelector('.set-side');
  if (side) {
    const panel = side.querySelector('.panel');
    if (panel) {
      setRow(panel, 'DSH', status?.version
        ? `${status.version}${status.verified ? ' · 已验收' : ' · 未验收'}`
        : '未安装', Boolean(status?.version));
      setRow(panel, '项目', tree?.project?.path || tree?.project?.name || '未找到项目记录');
      setRow(panel, '数据', '本机 · 未上传', true);
    }
    const notes = side.querySelectorAll('.panel')[1]?.querySelector('.note-p');
    if (notes) {
      notes.innerHTML = '① 关闭开关只停用能力，数据与授权记录保留；<br>'
        + '② 工作模型与 API 凭据由 DSH 工作台管理，本页不重复提供入口；<br>'
        + '③ 角色模型来自本机角色服务，按角色独立绑定。';
    }
  }

  const modelsGroup = Array.from(document.querySelectorAll('#screen-settings .set-group'))
    .find(group => /模型与连接/.test(group.querySelector('h2')?.textContent || ''));
  if (!modelsGroup) return;
  const rows = Array.from(modelsGroup.querySelectorAll('.set-row'));
  const rowFor = name => rows.find(row => (row.querySelector('div')?.textContent || '').startsWith(name));

  const roleRow = rowFor('角色模型');
  const roleValue = roleRow?.querySelector('.val');
  if (roleValue) {
    roleValue.innerHTML = state?.role?.enabled === false
      ? '<span class="rsv-tag">已停用</span>'
      : `<b class="ok">● 已启用</b><b>${state?.role?.model || '未配置模型'}</b>`;
  }

  for (const name of ['工作模型', 'API 凭据']) {
    const row = rowFor(name);
    const value = row?.querySelector('.val');
    if (!value) continue;
    if (name === 'API 凭据') {
      // DSH keeps this in the profile's .credentials.yaml as plain text, so the
      // design's "本地加密保存" wording would be a false statement.
      const hint = row.querySelector('div small');
      if (hint) hint.textContent = '由 DSH 保存于本机 profile，不上传、不进 Git';
    }
    value.innerHTML = '<b>由 DSH 工作台管理</b>'
      + (name === '工作模型' ? '<button class="mini-btn">打开工作台 →</button>' : '');
    // The workbench is a screen of this page now, so these entries switch to it
    // instead of opening anything.
    const button = value.querySelector('button');
    if (button) button.addEventListener('click', () => { location.hash = 'board'; });
  }
}

/**
 * Mark the parts of the settings screen that are still the design's placeholder
 * and disable their controls, so a click cannot look like a working switch. Also
 * removes the two values that were never real: the sample checkpoint hash and the
 * MCP authorization count.
 */
const UNWIRED_REASON = '设计稿占位项，当前版本未接入后端';

function markGroupUnwired(group) {
  const heading = group.querySelector('h2');
  if (heading && !heading.querySelector('.rsv-tag')) {
    const tag = document.createElement('span');
    tag.className = 'rsv-tag';
    tag.textContent = '原型 · 未接入';
    tag.title = UNWIRED_REASON;
    tag.style.marginLeft = '8px';
    heading.appendChild(tag);
  }
  group.querySelectorAll('button').forEach(node => {
    node.disabled = true;
    node.title = UNWIRED_REASON;
    node.style.opacity = '.55';
    node.style.cursor = 'default';
  });
}

async function bindUnwiredSettings() {
  const groups = Array.from(document.querySelectorAll('#screen-settings .set-group'));
  const byName = name => groups.find(group => (group.querySelector('h2')?.textContent || '').includes(name));

  for (const name of ['外观', '数据与存储', '关于']) {
    const group = byName(name);
    if (group) markGroupUnwired(group);
  }

  const checkpoint = Array.from(byName('数据与存储')?.querySelectorAll('.set-row') || [])
    .find(row => (row.querySelector('div')?.textContent || '').startsWith('检查点'));
  if (checkpoint) {
    const value = checkpoint.querySelector('.val');
    if (value) value.innerHTML = '<b>由连续性记录与 Git 管理</b>';
  }

  const permissions = byName('连接与权限');
  if (permissions) {
    const mcp = Array.from(permissions.querySelectorAll('.set-row'))
      .find(row => (row.querySelector('div')?.textContent || '').startsWith('MCP'));
    if (mcp) {
      const value = mcp.querySelector('.val');
      if (value) {
        value.textContent = '';
        const label = document.createElement('b');
        label.textContent = '由 DSH 工作台管理';
        const button = document.createElement('button');
        button.className = 'mini-btn';
        button.textContent = '打开工作台 →';
        button.addEventListener('click', () => { location.hash = 'board'; });
        value.append(label, button);
      }
    }
  }
}

(async () => {
  try {
    // The design's inline script owns screen switching; the workbench screen
    // needs one extra body class so its mock overlays stay hidden.
    const syncBoardClass = () => {
      document.body.classList.toggle('on-board', location.hash === '#board');
    };
    window.addEventListener('hashchange', syncBoardClass);
    syncBoardClass();
    const [state, roles, tree] = await Promise.all([
      api('/api/state'), api('/api/roles'), api('/api/tree'),
    ]);
    bindHeader(state);
    bindRoster(roles);
    await bindRoomChat(roles.active?.id || null);
    bindTree(tree);
    await bindCapabilityScreens();
    await bindSettingsFacts(tree);
    await bindUnwiredSettings();
    await bindWorkbench();
  } catch (error) {
    const proto = document.querySelector('.proto');
    if (proto) proto.textContent = `绑定失败：${error.message}`;
  }
})();
