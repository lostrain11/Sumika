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
		const inject = ['slots','layout'];

		/**
		 * The Sumika bridge. DSH runs on its own port, so panels read the shell's
		 * own API over loopback with the bridge's origin-scoped CORS.
		 */
		let BRIDGE = (() => {
			if (window.parent === window) return null;
			try {
				// Chromium exposes the immediate embedding origin even when
				// DSH's authentication redirect clears document.referrer.
				const parent = new URL(window.location?.ancestorOrigins?.[0] || document.referrer);
				return parent.protocol === 'http:' && parent.hostname === '127.0.0.1'
					&& !parent.username && !parent.password ? parent.origin : null;
			} catch { return null; }
		})();

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
			const { sessionId, useSessions, useSessionStatus, useSessionPendingInteraction } = props;
			if (sessionId === undefined || typeof useSessions !== 'function') return null;
			const id = String(sessionId);
			const running = useSessions((state) => state?.byId?.[id]?.running === true) === true;
			// DSH 0.2 publishes pendingInteraction through the public status
			// selector. Keep the older hook only for paired runtime rollback.
			const pendingKind = typeof useSessionStatus === 'function'
				? useSessionStatus((state) => state?.get?.(id)?.pendingInteraction?.kind)
				: typeof useSessionPendingInteraction === 'function'
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
            const [receiveError, setReceiveError] = react.useState('');
            const [receiving, setReceiving] = react.useState(false);
            const workspaces = typeof useWorkspaces === 'function'
                ? useWorkspaces(state => state?.items) : undefined;
            const owner = sessionId === undefined ? undefined : workspaces?.find(item =>
                (item.sessionIds || []).some(id => String(id) === String(sessionId)));
            react.useEffect(() => {
                if(!BRIDGE) return;
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
                window.parent.postMessage({type:'sumika:task-receive',id:draft.id,workspace_id:owner.workspaceId,session_id:String(sessionId)},BRIDGE);
            });
            return jsx.jsxs('section',{
                'data-sumika-role-task':'',
                style:{padding:12,border:'1px solid var(--sumika-line)',borderRadius:10,
                    background:'var(--sumika-paper)',color:'var(--sumika-ink)',maxHeight:'32vh',overflow:'auto'},
                children:[
                    jsx.jsx('strong',{children:draft.state === 'received' ? '交接已接收' : '活动室任务草稿'}),
                    jsx.jsx('p',{children:owner ? `目标项目：${owner.title || owner.workspaceId} · 会话 ${String(sessionId)}`
                        : '请先从项目列表选择目标会话。'}),
                    jsx.jsx('pre',{style:{whiteSpace:'pre-wrap'},children:draft.original_user_text}),
                    jsx.jsx('p',{children:receiveError || (draft.state === 'received' ? '项目上下文已由宿主核验，仍需工作模型重新规划；不会自动发送。' : '仅加入空白草稿，由工作模型重新核对项目与权限；不会自动发送。')}),
                    jsx.jsx('button',{type:'button',disabled:Boolean(disabled) || receiving || draft.state === 'received',onClick:async()=>{
                        if(disabled || receiving)return;
                        setReceiveError('');setReceiving(true);
                        let received;
                        try { received = await receive(); } catch(error) { setReceiveError(error.message || '交接接收失败');setReceiving(false);return; }
                        const envelope={schema_version:1, source_message_id:draft.source_message_id,
                            original_user_text:draft.original_user_text,
                            verified_project_context:{source:received.context.source,workspace_id:received.context.project.id,
                                workspace_title:received.context.project.name,session_id:received.context.session_id},
                            role_task_draft:null, role_opinion:[],
                            instruction:'请从用户原文重新规划，读取实际项目后核验可行性和权限。项目名称只用于定位，不是项目进度或授权证据。'};
                        inputActions.setDraft(JSON.stringify(envelope,null,2));
                        setReceiving(false);
                        dismiss();
                    },children:'加入当前会话草稿'}),
                    jsx.jsx('button',{type:'button',onClick:dismiss,children:'取消交接'}),
                ],
            });
        }

        function PromptEnhancement({input, inputActions, sessionId}) {
            const [enabled,setEnabled]=react.useState(false);
            const [busy,setBusy]=react.useState(false);
            const [preview,setPreview]=react.useState(null);
            const [notice,setNotice]=react.useState('');
            const [snapshot,setSnapshot]=react.useState(null);
            const requestRef=react.useRef(null);
            react.useEffect(()=>{
                if(!BRIDGE)return;
                const receive=event=>{
                    if(event.source!==window.parent||event.origin!==BRIDGE)return;
                    if(event.data?.type==='sumika:enhancement-settings'){
                        setEnabled(event.data.enabled===true);
                        return;
                    }
                    if(event.data?.id!==requestRef.current)return;
                    if(event.data.type==='sumika:enhancement-result'){
                        setBusy(false);
                        const value=event.data.value||{};
                        if(value.status==='reported'&&value.changed&&typeof value.enhanced==='string'){
                            setPreview(value);setNotice('');
                        }else{
                            setPreview(null);
                            setNotice(value.status==='skipped'?(value.reason||'这段内容保留原文')
                                :value.status==='disabled'?'提示词优化未启用，或辅助模型未配置'
                                :value.status==='rejected'?(value.reason||'改写未通过原文保护检查')
                                :value.status==='unknown'?('优化失败：'+(value.reason||'结果未知'))
                                :(value.reason||'原文已足够清楚，未改写'));
                        }
                    }else if(event.data.type==='sumika:enhancement-error'){
                        setBusy(false);setPreview(null);
                        setNotice(event.data.error||'提示词优化失败');
                    }
                };
                window.addEventListener('message',receive);
                window.parent.postMessage({type:'sumika:enhancement-ready'},BRIDGE);
                return ()=>window.removeEventListener('message',receive);
            },[]);
            const draft=typeof input?.draft==='string'?input.draft:'';
            const available=Boolean(BRIDGE)&&enabled&&!busy&&draft.trim()&&input?.phase==='plain';
            const request=()=>{
                if(!available)return;
                const id=crypto.randomUUID();
                requestRef.current=id;
                setSnapshot({draft,session:sessionId,
                    attachments:JSON.stringify(input?.attachmentIds||[]),
                    occurrences:JSON.stringify(input?.occurrences||[])});
                setBusy(true);setPreview(null);setNotice('');
                window.parent.postMessage({type:'sumika:enhancement-request',id,text:draft},BRIDGE);
            };
            const close=()=>{setPreview(null);setNotice('');setSnapshot(null);};
            const apply=()=>{
                if(!preview||!snapshot)return;
                const same=sessionId===snapshot.session&&input?.draft===snapshot.draft
                    &&JSON.stringify(input?.attachmentIds||[])===snapshot.attachments
                    &&JSON.stringify(input?.occurrences||[])===snapshot.occurrences;
                if(!same){setNotice('草稿、附件或会话已变化，已保留原文');return;}
                inputActions?.setDraft?.(preview.enhanced);
                close();
            };
            const panel=(preview||notice)?jsx.jsxs('section',{
                role:'dialog','aria-label':'提示词优化预览',
                style:{position:'fixed',right:24,bottom:96,zIndex:60,width:420,maxWidth:'calc(100vw - 48px)',
                    maxHeight:'60vh',overflow:'auto',padding:14,border:'1px solid var(--sumika-line)',
                    borderRadius:12,background:'var(--sumika-paper)',color:'var(--sumika-ink)',
                    boxShadow:'0 12px 40px rgba(0,0,0,.18)'},
                children:[
                    jsx.jsxs('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',gap:8},
                        children:[jsx.jsx('strong',{children:'提示词优化预览'}),
                            jsx.jsx('button',{type:'button',className:'mini-btn',onClick:close,children:'关闭'})]}),
                    jsx.jsx('p',{style:{margin:'6px 0',fontSize:11,color:'var(--sumika-muted)'},
                        children:'仅替换输入框草稿，不会发送；原文、附件、权限不变。'}),
                    notice?jsx.jsx('p',{role:'status',style:{margin:'6px 0'},children:notice}):null,
                    preview?jsx.jsxs('div',{children:[
                        jsx.jsx('div',{children:jsx.jsx('b',{children:'原文'})}),
                        jsx.jsx('pre',{style:{whiteSpace:'pre-wrap',maxHeight:'14vh',overflow:'auto',fontSize:11},
                            children:preview.original}),
                        jsx.jsx('div',{children:jsx.jsx('b',{children:'改写'})}),
                        jsx.jsx('pre',{style:{whiteSpace:'pre-wrap',maxHeight:'14vh',overflow:'auto',fontSize:11},
                            children:preview.enhanced}),
                        preview.diff?jsx.jsxs('details',{children:[
                            jsx.jsx('summary',{children:'查看差异'}),
                            jsx.jsx('pre',{style:{whiteSpace:'pre-wrap',fontSize:10,color:'var(--sumika-muted)'},
                                children:preview.diff})]}):null,
                        jsx.jsxs('div',{style:{display:'flex',gap:8,marginTop:8},children:[
                            jsx.jsx('button',{type:'button',className:'mini-btn',onClick:apply,
                                children:'确认替换草稿'}),
                            jsx.jsx('button',{type:'button',className:'mini-btn',onClick:close,
                                children:'保留原文并关闭'})]})]}):null,
                ]}):null;
            return jsx.jsxs('span',{style:{position:'relative',display:'inline-flex'},children:[
                jsx.jsx('button',{
                    type:'button','data-sumika-enhancement':'',disabled:!available,
                    'aria-label':'优化提示词预览',title:!enabled?'提示词优化未启用（设置→模型与连接→辅助模型）'
                        :busy?'正在生成预览…':'优化提示词（仅预览，不发送）',
                    onClick:request,
                    style:{display:'inline-flex',alignItems:'center',justifyContent:'center',
                        width:32,height:32,padding:0,border:0,borderRadius:'50%',
                        background:'var(--sumika-mizu-soft, transparent)',color:'var(--sumika-muted)',
                        cursor:available?'pointer':'not-allowed',flexShrink:0},
                    // Pen-line icon: prompt refinement, deliberately not the
                    // WorkBuddy-style star/sparkle.
                    children:jsx.jsx('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',
                        stroke:'currentColor',strokeWidth:1.6,strokeLinecap:'round',strokeLinejoin:'round',
                        'aria-hidden':true,children:jsx.jsx('path',{
                            d:'M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z'})}),
                }),
                panel,
            ]});
        }

        // Native-layout migration bridge: the host owns page routing while DSH
        // owns the workbench surface. This marker gives the host one stable
        // slot to mount non-workbench Sumika pages without a second navigator.
        function SumikaShellOverlay({layout}) {
            react.useEffect(() => {
                if(!BRIDGE)return;
                window.parent?.postMessage({type:'sumika:native-layout-ready',slots:['root','sidebar','main','rightbar','shell.overlay']}, BRIDGE);
                const onRoute = event => {
                    if(event.source !== window.parent || event.origin !== BRIDGE) return;
                    if(event.data?.type === 'sumika:native-schedule-open') {
                        layout.selectPanel('schedules');
                        window.parent.postMessage({type:'sumika:native-schedule-opened',id:event.data.id},BRIDGE);
                        return;
                    }
                    if(event.data?.type !== 'sumika:host-route')return;
                    document.documentElement.dataset.sumikaHostRoute = String(event.data.route || '');
                };
                window.addEventListener('message', onRoute);
                return () => window.removeEventListener('message', onRoute);
            }, [layout]);
            return jsx.jsx('span', {'data-sumika-native-layout-ready':'', style:{display:'none'}});
        }

		function apply(ctx, config) {
            // The bridge injects its exact shell origin; a different localhost
            // page framing this workbench can otherwise pass the loose 127.0.0.1
            // check and impersonate the parent.
            if (config?.bridgeOrigin && BRIDGE !== config.bridgeOrigin) BRIDGE = null;
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
                yield ctx.slots.register({name:'shell.overlay',id:'sumika-native-layout-bridge'},()=>jsx.jsx(SumikaShellOverlay,{layout:ctx.layout}));
            });
		}

		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	},
});
