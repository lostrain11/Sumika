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

		/** D 方案「晴日部室」token，取值同设计稿 :root。 */
		const GREEN = '#567f6c';
		const GREEN_SOFT = '#e8f1ea';
		const GREEN_LINE = '#cfe0d4';
		const AMBER = '#9a7038';
		const AMBER_SOFT = '#f7efdd';
		const AMBER_LINE = '#e8d3ab';
		const MUTED = '#6e7a72';

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

		/** Right-aligned status in the Session header's utilities seat. */
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
		}

		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	},
});
