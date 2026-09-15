// Browser half of the Sumika brand plugin.
//
// DSH loads client plugins through its module loader, so this file registers a
// factory instead of being a plain ES module. Slot keys follow the contract used
// by the official brand plugin (sidebar.brand.mark / sidebar.brand.name).

window.__ModuleLoader__.load({
	id: 'sumika-brand',
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

		const jsx = require('react/jsx-runtime');

		/** Required service: the UI slot registry. */
		const inject = ['slots'];

		/** D 方案「晴日部室」的配色，取值同设计稿 :root 与 Sumika 皮肤。 */
		const GREEN = '#567f6c';
		const ROSE = '#b4496a';
		const INK = '#2f3a34';
		const MUTED = '#6e7a72';
		const LINE = '#ddd9c8';
		const GREEN_LINE = '#cfe0d4';

		function SumikaBrandMark({ size }) {
			const side = typeof size === 'number' ? size : 18;
			return jsx.jsx('span', {
				'aria-hidden': true,
				style: {
					display: 'inline-block', width: side, height: side, borderRadius: 5,
					background: `linear-gradient(135deg, ${GREEN} 0%, ${ROSE} 100%)`,
					flex: '0 0 auto',
				},
			});
		}

		function SumikaBrandName() {
			return jsx.jsx('span', {
				style: { color: INK, fontWeight: 600, letterSpacing: '0.08em' },
				children: '晴日部室',
			});
		}

		/**
		 * The New Session hero mark, which DSH otherwise fills with its own fish.
		 * The host passes the square edge and the class that keeps the surrounding
		 * headline geometry, so only the artwork comes from this plugin.
		 */
		function SumikaHeroMark({ size, className }) {
			const side = typeof size === 'number' ? size : 34;
			return jsx.jsx('span', {
				className,
				'aria-hidden': true,
				style: {
					display: 'inline-block', width: side, height: side, borderRadius: 9,
					background: `linear-gradient(135deg, ${GREEN} 0%, ${ROSE} 100%)`,
					flex: '0 0 auto',
				},
			});
		}

		/**
		 * Footer status line, mirroring the design's sidebar foot. Every value is
		 * either a fixed statement about this installation or a fact the host
		 * published in `window.__sumikaShell`; nothing here is inferred.
		 */
		function SumikaFooterStatus({ wide }) {
			// The shell renders the foot into a 36px rail when the column is
			// collapsed; the status block only has room in the wide column.
			if (wide === false) return null;
			const shell = window.__sumikaShell;
			const release = shell && typeof shell.release === 'string' ? shell.release : null;
			const harness = shell && typeof shell.harness === 'string' ? shell.harness.toUpperCase() : '';
			const shellUrl = shell && typeof shell.shellUrl === 'string' ? shell.shellUrl : null;
			return jsx.jsxs('div', {
				style: {
					flex: '1 1 auto', minWidth: 0, boxSizing: 'border-box',
					margin: '8px 2px 0', border: `1px dashed ${LINE}`, borderRadius: 10,
					padding: '9px 11px', fontSize: 9.5, lineHeight: 1.7, color: MUTED,
				},
				children: [
					jsx.jsx('div', { children: '本地优先 · 数据不出本机' }),
					jsx.jsx('div', {
						children: [
							'运行数据 ',
							jsx.jsx('b', { style: { color: GREEN }, children: '.sumika-next/' }),
							release ? jsx.jsxs('span', {
								children: [' · 已连接 ', jsx.jsx('b', {
									style: { color: GREEN },
									children: `${harness} ${release}`,
								})],
							}) : null,
						],
					}),
					// This page *is* the workbench, so the way back to the shell's other
					// screens (活动室 / 能力 / 设置) has to live in here.
					shellUrl ? jsx.jsx('a', {
						href: shellUrl,
						'data-sumika-shell-link': shellUrl,
						style: {
							display: 'inline-block', marginTop: 4, color: GREEN,
							textDecoration: 'none', borderBottom: `1px dashed ${GREEN_LINE}`,
						},
						children: '← 回 Sumika 活动室 / 能力 / 设置',
					}) : null,
				],
			});
		}

		/**
		 * Replace the sidebar brand. Both slots are single-occupancy and the
		 * official brand plugin already holds them at priority 0, so the lowest
		 * priority wins: register below it instead of disabling an upstream plugin.
		 * Both registrations are gated on the slots existing, so a DSH version
		 * without them simply shows the official brand.
		 */
		function apply(ctx) {
			// Rendered inside the shell's workbench screen, the shell's own top bar
			// already carries the brand, so the sidebar does not repeat it there.
			const framed = window.self !== window.top;
			if (!framed) {
				ctx.slots.inject('sidebar.brand.mark', () =>
					ctx.slots.inject('sidebar.brand.name', function* () {
						yield ctx.slots.register({ name: 'sidebar.brand.mark', priority: -1 }, SumikaBrandMark);
						yield ctx.slots.register({ name: 'sidebar.brand.name', priority: -1 }, SumikaBrandName);
					}));
			}
			// The New Session hero mark is a single-occupancy root slot whose default
			// occupant is DSH's own fish, so it is shadowed the same way.
			ctx.slots.inject('conversation.hero.brand.mark', function* () {
				yield ctx.slots.register({ name: 'conversation.hero.brand.mark', priority: -1 },
					SumikaHeroMark);
			});
			// The footer is a list slot: it takes real entries next to the native
			// ones, so it needs an id and no priority override.
			ctx.slots.inject('sidebar.footer.action', function* () {
				yield ctx.slots.register({ name: 'sidebar.footer.action', id: 'sumika-status' },
					SumikaFooterStatus);
			});
		}

		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	},
});
