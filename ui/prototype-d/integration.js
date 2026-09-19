// Thin UI boundary. Backend adapters dispatch these events; the prototype never
// fabricates task completion or permissions.
export const UI_CONTRACT = Object.freeze({
  states: ['unknown','pending','running','completed','failed','cancelled'],
  event: 'sumika:backend-state'
});

export function publishBackendState(state) {
  if (!state || typeof state !== 'object' || !UI_CONTRACT.states.includes(state.status)) {
    throw new TypeError('invalid backend state');
  }
  window.dispatchEvent(new CustomEvent(UI_CONTRACT.event, { detail: structuredClone(state) }));
}

export function subscribeBackendState(handler) {
  if (typeof handler !== 'function') throw new TypeError('handler required');
  const listener = event => handler(event.detail);
  window.addEventListener(UI_CONTRACT.event, listener);
  return () => window.removeEventListener(UI_CONTRACT.event, listener);
}
