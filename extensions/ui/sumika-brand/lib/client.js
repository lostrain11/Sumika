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
		 * Replace the sidebar brand. Both slots are single-occupancy and the
		 * official brand plugin already holds them at priority 0, so the lowest
		 * priority wins: register below it instead of disabling an upstream plugin.
		 * Both registrations are gated on the slots existing, so a DSH version
		 * without them simply shows the official brand.
		 */
		function apply(ctx) {
			// Always occupy the brand slots: skipping them when framed only let DSH's
			// own "deepseek HARNESS" wordmark show through, which is worse than the
			// brand appearing in both the shell top bar and the sidebar.
			ctx.slots.inject('sidebar.brand.mark', () =>
				ctx.slots.inject('sidebar.brand.name', function* () {
					yield ctx.slots.register({ name: 'sidebar.brand.mark', priority: -1 }, SumikaBrandMark);
					yield ctx.slots.register({ name: 'sidebar.brand.name', priority: -1 }, SumikaBrandName);
				}));
		}

		exports.inject = inject;
		exports.apply = apply;
		return module.exports;
	},
});
