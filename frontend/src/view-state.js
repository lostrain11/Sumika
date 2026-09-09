export function createViewState(root) {
  let previousContext = "";
  let snapshot = null;
  const focusableSelector = 'button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), summary, a[href], [tabindex="0"]';

  function modal() {
    return root.querySelector('[role="dialog"][aria-modal="true"]');
  }

  function focusable(container) {
    return [...container.querySelectorAll(focusableSelector)].filter((element) => element.getClientRects().length && !element.closest("[inert]"));
  }

  function handleKeydown(event) {
    const dialog = modal();
    if (event.key !== "Tab" || !dialog) return;
    const elements = focusable(dialog);
    if (!elements.length) return;
    const first = elements[0];
    const last = elements.at(-1);
    if (!dialog.contains(document.activeElement) || (event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  }

  function elementKey(element) {
    const fields = [...element.attributes].filter((attribute) => attribute.name === "id" || attribute.name === "name" || attribute.name.startsWith("data-"));
    const form = element.closest("form");
    return { tag: element.tagName, fields: fields.map(({ name, value }) => [name, value]), form: form?.id || "" };
  }

  function findElement(key) {
    if (!key?.fields.length) return null;
    return [...root.querySelectorAll(key.tag)].find((element) => key.fields.every(([name, value]) => element.getAttribute(name) === value) && (element.closest("form")?.id || "") === key.form);
  }

  function capture() {
    const focused = document.activeElement;
    const dirtyFields = [...root.querySelectorAll("#character-form input, #character-form textarea, #character-form select")].filter((element) => {
      if (!element.name || ["password", "file"].includes(element.type)) return false;
      if (element.type === "checkbox") return element.checked !== element.defaultChecked;
      if (element instanceof HTMLSelectElement) return [...element.options].some((option) => option.selected !== option.defaultSelected);
      return element.value !== element.defaultValue;
    });
    const details = [...root.querySelectorAll("details")].map((element) => ({ key: element.dataset.uiKey || `${element.className}:${element.querySelector("summary")?.textContent.trim()}`, open: element.open }));
    snapshot = {
      context: previousContext,
      drawer: root.querySelector(".scene-shell")?.dataset.drawer,
      details,
      drafts: dirtyFields.map((element) => ({ key: elementKey(element), value: element.value, checked: element.type === "checkbox" ? element.checked : null })),
      scroll: root.querySelector(".drawer-body")?.scrollTop || 0,
      focus: root.contains(focused) ? elementKey(focused) : null,
      selection: focused instanceof HTMLTextAreaElement || (focused instanceof HTMLInputElement && ["text", "search", "url", "tel"].includes(focused.type)) ? [focused.selectionStart, focused.selectionEnd] : null,
    };
  }

  function restore(context) {
    previousContext = context;
    if (!snapshot) return;
    if (snapshot.context === context) {
      for (const element of root.querySelectorAll("details")) {
        const key = element.dataset.uiKey || `${element.className}:${element.querySelector("summary")?.textContent.trim()}`;
        const saved = snapshot.details.find((item) => item.key === key);
        if (saved) element.open = saved.open;
      }
      const body = root.querySelector(".drawer-body");
      if (body) body.scrollTop = snapshot.scroll;
      for (const draft of snapshot.drafts) {
        const field = findElement(draft.key);
        if (!field) continue;
        field.value = draft.value;
        if (draft.checked !== null) field.checked = draft.checked;
        if (field.dataset.rangeOutput) {
          const output = document.getElementById(field.dataset.rangeOutput);
          if (output) output.value = Number(draft.value).toFixed(2);
        }
      }
      const focused = findElement(snapshot.focus);
      if (focused && !focused.closest("[inert]")) {
        focused.focus({ preventScroll: true });
        if (snapshot.selection && focused.setSelectionRange) focused.setSelectionRange(...snapshot.selection);
      }
    } else if (root.querySelector(".drawer")) {
      root.querySelector(".drawer h1")?.focus({ preventScroll: true });
    } else if (snapshot.drawer) {
      root.querySelector(`[data-dock-drawer="${snapshot.drawer}"]`)?.focus({ preventScroll: true });
    }
    const dialog = modal();
    if (dialog && !dialog.contains(document.activeElement)) focusable(dialog)[0]?.focus({ preventScroll: true });
    snapshot = null;
  }

  return { capture, restore, handleKeydown };
}
