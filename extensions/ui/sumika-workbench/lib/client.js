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
				? `项目 · ${owner.title}`
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

        function RoleTaskDraft({input, inputActions, sessionId, useWorkspaces}) {
            const [draft, setDraft] = react.useState(null);
            const workspaces = typeof useWorkspaces === 'function'
                ? useWorkspaces(state => state?.items) : undefined;
            const owner = sessionId === undefined ? undefined : workspaces?.find(item =>
                (item.sessionIds || []).some(id => String(id) === String(sessionId)));
            react.useEffect(() => {
                if(window.parent === window) return;
                const receive = event => {
                    if(event.source !== window.parent || event.origin !== BRIDGE
                        || event.data?.type !== 'sumika:task-draft')return;
                    const value = event.data.draft;
                    if(value === null) {setDraft(null);return;}
                    if(typeof value?.id !== 'string' || typeof value?.source_message_id !== 'string'
                        || typeof value?.original_user_text !== 'string' || !value.original_user_text.trim())return;
                    setDraft(value);
                };
                window.addEventListener('message',receive);
                window.parent.postMessage({type:'sumika:task-ready'},BRIDGE);
                return () => window.removeEventListener('message',receive);
            },[]);
            if(!draft)return null;
            const disabled = !owner || !inputActions?.setDraft || input?.phase !== 'plain'
                || input.draft?.trim() || input.attachmentIds?.length || input.occurrences?.length;
            const dismiss = () => {
                window.parent.postMessage({type:'sumika:task-consumed',id:draft.id},BRIDGE);
                setDraft(null);
            };
            const receive = () => new Promise((resolve,reject) => {
                const handler = event => {
                    if(event.source !== window.parent || event.origin !== BRIDGE || event.data?.id !== draft.id) return;
                    if(event.data.type === 'sumika:task-received') { window.removeEventListener('message',handler); resolve(event.data.handoff); }
                    if(event.data.type === 'sumika:task-receive-error') { window.removeEventListener('message',handler); reject(new Error(event.data.error || '交接接收失败')); }
                };
                window.addEventListener('message',handler);
                window.parent.postMessage({type:'sumika:task-receive',id:draft.id,projects:[{id:owner.id,name:owner.title || owner.id,summary:'DSH 当前工作区'}]},BRIDGE);
            });
            return jsx.jsxs('section',{
                'data-sumika-role-task':'',
                style:{padding:12,border:'1px solid var(--sumika-line)',borderRadius:10,
                    background:'var(--sumika-paper)',color:'var(--sumika-ink)',maxHeight:'32vh',overflow:'auto'},
                children:[
                    jsx.jsx('strong',{children:draft.state === 'received' ? '交接已接收' : '活动室任务草稿'}),
                    jsx.jsx('p',{children:owner ? `目标项目：${owner.title || owner.id} · 会话 ${String(sessionId)}`
                        : '请先从项目列表选择目标会话。'}),
                    jsx.jsx('pre',{style:{whiteSpace:'pre-wrap'},children:draft.original_user_text}),
                    jsx.jsx('p',{children:draft.state === 'received' ? '项目上下文已由宿主核验，仍需工作模型重新规划；不会自动发送。' : '仅加入空白草稿，由工作模型重新核对项目与权限；不会自动发送。'}),
                    jsx.jsx('button',{type:'button',disabled:Boolean(disabled) || draft.state === 'received',onClick:async()=>{
                        if(disabled)return;
                        try { await receive(); } catch(error) { return; }
                        const envelope={schema_version:1, source_message_id:draft.source_message_id,
                            original_user_text:draft.original_user_text,
                            verified_project_context:{source:'dsh-workspace-registry',workspace_id:owner.id,
                                workspace_title:owner.title,session_id:String(sessionId)},
                            role_task_draft:null, role_opinion:[],
                            instruction:'请从用户原文重新规划，读取实际项目后核验可行性和权限。项目名称只用于定位，不是项目进度或授权证据。'};
                        inputActions.setDraft(JSON.stringify(envelope,null,2));
                        dismiss();
                    },children:'加入当前会话草稿'}),
                    jsx.jsx('button',{type:'button',onClick:dismiss,children:'取消交接'}),
                ],
            });
        }

        function PromptEnhancement() {
            return jsx.jsx('button', {
                type:'button', 'data-sumika-enhancement':'', disabled:true,
                'aria-label':'优化提示词（尚未接通）', title:'优化提示词 · 尚未接通',
                style:{display:'inline-flex',alignItems:'center',justifyContent:'center',
                    width:32,height:32,padding:0,border:0,borderRadius:'50%',
                    background:'var(--sumika-mizu-soft, transparent)',color:'var(--sumika-muted)',
                    cursor:'not-allowed',flexShrink:0},
                children:jsx.jsx('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',
                    stroke:'currentColor',strokeWidth:1.6,strokeLinecap:'round',strokeLinejoin:'round',
                    'aria-hidden':true,children:jsx.jsx('path',{
                        d:'M12 3l2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3ZM20 2v4M18 4h4'})}),
            });
        }

        // Native-layout migration bridge: the host owns page routing while DSH
        // owns the workbench surface. This marker gives the host one stable
        // slot to mount non-workbench Sumika pages without a second navigator.
        function SumikaShellOverlay() {
            react.useEffect(() => {
                window.parent?.postMessage({type:'sumika:native-layout-ready',slots:['root','sidebar','main','rightbar','shell.overlay']}, BRIDGE);
                const onRoute = event => {
                    if(event.source !== window.parent || event.origin !== BRIDGE || event.data?.type !== 'sumika:host-route') return;
                    document.documentElement.dataset.sumikaHostRoute = String(event.data.route || '');
                };
                window.addEventListener('message', onRoute);
                return () => window.removeEventListener('message', onRoute);
            }, []);
            return jsx.jsx('span', {'data-sumika-native-layout-ready':'', style:{display:'none'}});
        }

		function apply(ctx) {
            ctx.slots.inject('conversation.input.right', function* () {
                yield ctx.slots.register({name:'conversation.input.right',id:'sumika-prompt-enhancement'},PromptEnhancement);
            });
            ctx.slots.inject('conversation.input.dock', function* () {

                yield ctx.slots.register({name:'conversation.input.dock',id:'sumika-role-task-draft'},RoleTaskDraft);
            });
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
            ctx.slots.inject('shell.overlay', function* () {
                yield ctx.slots.register({name:'shell.overlay',id:'sumika-native-layout-bridge'},SumikaShellOverlay);
            });
		}

		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	},
});
