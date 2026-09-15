// Sumika additions to the DSH workbench shell.
//
// Everything here reads state the framework already tracks; nothing is inferred
// and nothing is fabricated. The measured prop contract for a session-scoped
// list entry is `{ sessionId, inputActions, useSession, useSessions,
// useSessionPendingInteraction, ... }` — see docs/project/workbench-skin-plan.md.

window.__ModuleLoader__.load({
	id: 'sumika-workbench',
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

		const jsx = require('react/jsx-runtime');

		/** Required service: the UI slot registry. */
		const inject = ['slots'];

		/**
		 * The Sumika bridge. DSH runs on its own port, so panels read the shell's
		 * own API over loopback with the bridge's origin-scoped CORS.
		 */
		const BRIDGE = 'http://127.0.0.1:8765';

		/** D 方案「晴日部室」token，取值同设计稿 :root。 */
		const GREEN = '#567f6c';
		const GREEN_SOFT = '#e8f1ea';
		const GREEN_LINE = '#cfe0d4';
		const AMBER = '#9a7038';
		const AMBER_SOFT = '#f7efdd';
		const AMBER_LINE = '#e8d3ab';
		const MUTED = '#6e7a72';
		const INK = '#2f3a34';
		const LINE = '#ddd9c8';

		/**
		 * Interaction kinds the shell treats as a user decision, mirroring the
		 * native sidebar row's own list. Anything else is not shown.
		 */
		const PENDING_LABELS = {
			approval: '等待审批',
			'plan-review': '计划审阅',
			question: '等待回答',
		};

		/** Design's `.pill-d`, with the `.run` and `.wait` variants. */
		function Pill({ tone, children }) {
			const run = tone === 'run';
			return jsx.jsx('span', {
				style: {
					fontSize: 9.5, lineHeight: '1.6', borderRadius: 99, padding: '4px 11px',
					border: `1px solid ${run ? GREEN_LINE : AMBER_LINE}`,
					color: run ? GREEN : AMBER,
					background: run ? GREEN_SOFT : AMBER_SOFT,
					whiteSpace: 'nowrap',
				},
				children,
			});
		}

		/**
		 * Session status for the conversation header. The marker attribute is
		 * always present so acceptance runs can tell "wired but idle" from
		 * "not mounted"; the visible pills appear only for a real state.
		 */
		function SessionStatus(props) {
			const { sessionId, useSessions, useSessionPendingInteraction } = props;
			if (sessionId === undefined || typeof useSessions !== 'function') return null;
			const id = String(sessionId);
			const running = useSessions((state) => state?.byId?.[id]?.running === true) === true;
			const pendingKind = typeof useSessionPendingInteraction === 'function'
				? useSessionPendingInteraction((state) => state?.get?.(id)?.kind)
				: undefined;
			const pendingLabel = typeof pendingKind === 'string' ? PENDING_LABELS[pendingKind] : undefined;
			const pills = [];
			if (pendingLabel !== undefined) pills.push({ key: 'pending', tone: 'wait', text: pendingLabel });
			if (running) pills.push({ key: 'running', tone: 'run', text: '执行中' });
			return jsx.jsx('span', {
				'data-sumika-session-status': pills.length === 0
					? 'idle'
					: pills.map((pill) => pill.key).join(','),
				style: { display: 'inline-flex', alignItems: 'center', gap: 6 },
				children: pills.map((pill) => jsx.jsx(Pill, { tone: pill.tone, children: pill.text }, pill.key)),
			});
		}

		/**
		 * Where this Session lives: the owning Workspace's own title, taken from
		 * the registry snapshot. The shell keeps rendering the Session title
		 * itself, so repeating it here would just print it twice; this seat only
		 * adds the location the shell does not show, and a way up to the parent
		 * Session when the shell offers `openTitle`.
		 */
		function SessionLineage(props) {
			const { displayTitle, lineageSessionId, openTitle, useWorkspaces } = props;
			const id = lineageSessionId === undefined ? undefined : String(lineageSessionId);
			const workspaces = typeof useWorkspaces === 'function'
				? useWorkspaces((state) => state?.items)
				: undefined;
			const owner = id === undefined || !Array.isArray(workspaces) ? undefined
				: workspaces.find(item => (item.sessionIds || []).some(
					sessionId => String(sessionId) === id));
			const label = owner && typeof owner.title === 'string' && owner.title
				? `工作区 · ${owner.title}`
				: null;
			if (label === null && openTitle === undefined) return null;
			const children = [];
			if (label !== null) {
				children.push(jsx.jsx('span', {
					style: {
						fontSize: 10, letterSpacing: '1px', color: MUTED,
						overflow: 'hidden', textOverflow: 'ellipsis',
					},
					children: label,
				}, 'workspace'));
			}
			if (openTitle !== undefined) {
				children.push(jsx.jsx('a', {
					key: 'parent',
					href: '#',
					onClick: (event) => { event.preventDefault(); openTitle(); },
					style: { fontSize: 10, color: MUTED, textDecoration: 'none', cursor: 'pointer' },
					children: '↑ 上级会话',
				}));
			}
			return jsx.jsxs('span', {
				'data-sumika-lineage': label === null ? 'parent-only' : 'workspace',
				title: typeof displayTitle === 'string' ? displayTitle : undefined,
				style: {
					display: 'inline-flex', alignItems: 'baseline', gap: 8, minWidth: 0,
					marginLeft: 8, overflow: 'hidden', whiteSpace: 'nowrap',
				},
				children,
			});
		}

		const react = require('react');

		/** Read the two bridge views; readiness and enablement stay separate. */
		async function loadCapabilities() {
			const [modules, readiness] = await Promise.all([
				fetch(`${BRIDGE}/api/modules`).then(response => response.json()),
				fetch(`${BRIDGE}/api/readiness`).then(response => response.json()),
			]);
			return { modules: modules.modules || [], readiness: readiness.capabilities || [] };
		}

		function PanelSwitch({ enabled, onToggle }) {
			return jsx.jsx('button', {
				type: 'button',
				role: 'switch',
				'aria-checked': enabled ? 'true' : 'false',
				'data-sumika-panel-switch': '',
				onClick: () => onToggle(!enabled),
				style: {
					width: 34, height: 20, borderRadius: 99, border: 'none', cursor: 'pointer',
					background: enabled ? GREEN : '#d8d4c2', position: 'relative',
					flex: '0 0 auto',
				},
				children: jsx.jsx('span', {
					style: {
						position: 'absolute', top: 3, left: enabled ? 17 : 3, width: 14, height: 14,
						borderRadius: '50%', background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,.18)',
					},
				}),
			});
		}

		/**
		 * A whole Sumika screen living inside DSH: this is the pattern for moving
		 * the shell's screens into the harness front end. It reads the same bridge
		 * API the shell does and writes through the same toggle route.
		 */
		function CapabilitiesPanel() {
			const [state, setState] = react.useState({ modules: [], readiness: [], error: null });
			const reload = react.useCallback(() => {
				loadCapabilities()
					.then(next => setState({ ...next, error: null }))
					.catch(error => setState(current => ({ ...current, error: String(error) })));
			}, []);
			react.useEffect(() => { reload(); }, [reload]);
			const toggle = (id, enabled) => {
				fetch(`${BRIDGE}/api/capabilities/toggle`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ id, enabled }),
				}).then(reload).catch(error => setState(current => ({ ...current, error: String(error) })));
			};
			const registered = new Set(state.modules.map(item => item.id));
			const row = (key, title, purpose, source, enabled, onToggle, status) => jsx.jsxs('div', {
				key,
				'data-sumika-panel-row': key,
				style: {
					display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
					border: `1px solid ${LINE}`, borderRadius: 9, background: '#fffdf8',
				},
				children: [
					jsx.jsxs('div', {
						style: { minWidth: 0, flex: 1 },
						children: [
							jsx.jsx('div', { style: { fontSize: 13, fontWeight: 600, color: INK }, children: title }),
							jsx.jsx('div', {
								style: { fontSize: 11, color: MUTED, marginTop: 3 },
								children: purpose,
							}),
						],
					}),
					jsx.jsx('span', {
						style: { fontSize: 10, color: MUTED, whiteSpace: 'nowrap' },
						children: source,
					}),
					status === undefined ? null : jsx.jsx('span', {
						style: {
							fontSize: 9.5, padding: '3px 9px', borderRadius: 99, whiteSpace: 'nowrap',
							color: status === 'on' ? GREEN : AMBER,
							background: status === 'on' ? GREEN_SOFT : AMBER_SOFT,
							border: `1px solid ${status === 'on' ? GREEN_LINE : AMBER_LINE}`,
						},
						children: status === 'on' ? '已启用' : '未启用',
					}),
					onToggle === undefined ? null
						: jsx.jsx(PanelSwitch, { enabled, onToggle }),
				],
			});
			return jsx.jsxs('div', {
				'data-sumika-panel': 'capabilities',
				style: { padding: '22px 26px', overflowY: 'auto', height: '100%', background: '#f7f4ec' },
				children: [
					jsx.jsx('div', {
						style: { fontSize: 20, fontWeight: 600, color: INK, marginBottom: 4 },
						children: '能力模块',
					}),
					jsx.jsx('div', {
						style: { fontSize: 11, color: MUTED, marginBottom: 18 },
						children: '关闭仅停用，数据与授权记录保留；「就绪」表示依赖已安装，与「已启用」分别显示。',
					}),
					state.error ? jsx.jsx('div', {
						style: { color: '#b04a4a', fontSize: 12, marginBottom: 12 },
						children: `读取失败：${state.error}`,
					}) : null,
					jsx.jsx('div', {
						style: { display: 'flex', flexDirection: 'column', gap: 8 },
						children: state.modules.map(item => row(item.id, item.label || item.id,
							`${item.purpose || ''}${item.purpose ? ' · ' : ''}实现：${item.provider}`,
							`扩展 ${item.id}`, item.enabled, next => toggle(item.id, next),
							item.enabled ? 'on' : 'off')),
					}),
					jsx.jsx('div', {
						style: { fontSize: 11, letterSpacing: 3, color: MUTED, margin: '22px 0 10px' },
						children: '就绪视图 · 无独立开关',
					}),
					jsx.jsx('div', {
						style: { display: 'flex', flexDirection: 'column', gap: 8 },
						children: state.readiness.filter(item => !registered.has(item.id))
							.map(item => row(`ready-${item.id}`, item.label || item.id, item.detail || '',
								`就绪检查 ${item.id}`, false, undefined,
								item.ready ? 'on' : 'off')),
					}),
				],
			});
		}

		/** Panel-list glyph for the sidebar's global panel row. */
		function CapabilitiesGlyph({ active, size }) {
			return jsx.jsx('span', {
				style: {
					display: 'inline-block', width: size || 16, height: size || 16, borderRadius: 4,
					background: active ? GREEN : 'transparent',
					border: active ? 'none' : `1.5px solid ${MUTED}`,
				},
			});
		}

		function apply(ctx) {
			ctx.slots.inject('conversation.session.header.utilities', function* () {
				yield ctx.slots.register({
					name: 'conversation.session.header.utilities',
					id: 'sumika-session-status',
				}, SessionStatus);
			});
			ctx.slots.inject('conversation.session.header.lineage', function* () {
				try {
					yield ctx.slots.register({
						name: 'conversation.session.header.lineage',
						priority: -1,
					}, SessionLineage);
					delete document.documentElement.dataset.sumikaLineageError;
				} catch (error) {
					document.documentElement.dataset.sumikaLineageError = String(error && error.message || error);
				}
			});
			// A whole Sumika screen as a harness panel: a `main` entry with a key
			// plus the sidebar panel row that switches to it.
			ctx.slots.inject('main', function* () {
				yield ctx.slots.register({
					name: 'main',
					key: 'sumika-capabilities',
					children: {},
				}, CapabilitiesPanel);
			});
			ctx.slots.inject('sidebar.panellist', function* () {
				yield ctx.slots.register({
					name: 'sidebar.panellist',
					id: 'sumika-capabilities',
					label: '能力',
					order: 10,
				}, CapabilitiesGlyph);
			});
		}

		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	},
});
