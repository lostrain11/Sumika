import {
  CAPABILITY_CATEGORIES,
  CAPABILITY_STORAGE_KEY,
  capabilityStatus,
  changeCapabilityLayout,
  projectCapabilityLayout,
  writeCapabilityLayout,
} from "./capability-layout.js";

const fallbackEscapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const safeClass = (value) => String(value || "unknown").replace(/[^a-z0-9_-]/gi, "-");
const text = (value, fallback = "未知") => value === undefined || value === null || value === "" ? fallback : String(value);

function statusLabel(value) {
  return ({ available: "可用", ready: "就绪", healthy: "健康", running: "运行中", configured: "已配置", unconfigured: "待配置", disabled: "未启用", error: "错误", unavailable: "不可用", pending: "待实现", unknown: "未知" })[value] || text(value);
}

export function createCapabilityPage({ state = {}, escapeHtml = fallbackEscapeHtml, storage, storageKey = CAPABILITY_STORAGE_KEY, renderRoutingEvidence = () => "" } = {}) {
  const encode = (value) => escapeHtml(text(value, ""));

  function renderStatus(item, layout) {
    return capabilityStatus(state, item.module, layout.statusRecords.get(item.id));
  }

  function renderCard(item, layout, index, count) {
    const status = renderStatus(item, layout);
    const registered = item.registered === true;
    const permissions = status.permissions.declarations.length ? status.permissions.declarations.join("、") : "未声明";
    return `<article class="capability-card ${registered ? "" : "capability-pending"}" data-capability-card data-module-id="${encode(item.id)}">
      <div class="capability-card-heading"><span class="capability-card-category">${encode(CAPABILITY_CATEGORIES.find((category) => category.id === item.category)?.label)}</span><span class="capability-status capability-status-${safeClass(status.status)}">${encode(statusLabel(status.status))}</span></div>
      <h3>${encode(item.name)}</h3><p>${encode(item.description)}</p>
      ${item.id === "llm" ? renderRoutingEvidence() : ""}
      <dl class="capability-card-meta"><div><dt>模块</dt><dd>${status.enabled ? "已启用" : "未启用"}</dd></div><div><dt>配置</dt><dd>${encode(status.configuration)}</dd></div><div><dt>权限声明</dt><dd>${encode(permissions)} · 授权${encode(status.permissions.authorization)}</dd></div></dl>
      <div class="capability-card-actions"><button class="capability-configure" type="button" data-capability-configure="${encode(item.id)}" ${registered ? "" : "disabled"}>配置</button><div class="capability-reorder"><button type="button" data-capability-move="up" data-module-id="${encode(item.id)}" aria-label="上移${encode(item.name)}" ${index === 0 ? "disabled" : ""}>上移</button><button type="button" data-capability-move="down" data-module-id="${encode(item.id)}" aria-label="下移${encode(item.name)}" ${index === count - 1 ? "disabled" : ""}>下移</button><button type="button" data-capability-remove="${encode(item.id)}" aria-label="移除${encode(item.name)}">移除</button></div></div>
    </article>`;
  }

  function renderLibraryCard(item) {
    const registered = item.registered === true;
    const label = registered ? `添加${item.name}` : `添加${item.name}（待实现，不可启用）`;
    return `<article class="capability-card capability-library-card ${registered ? "" : "capability-pending"}" data-capability-library-card data-module-id="${encode(item.id)}"><div class="capability-card-heading"><span class="capability-card-category">${encode(CAPABILITY_CATEGORIES.find((category) => category.id === item.category)?.label)}</span><span class="capability-status capability-status-${registered ? "unknown" : "pending"}">${registered ? "未添加" : "待实现"}</span></div><h3>${encode(item.name)}</h3><p>${encode(item.description)}</p><button class="capability-add" type="button" data-capability-add="${encode(item.id)}" title="${encode(label)}" aria-label="${encode(label)}" ${registered ? "" : "disabled"}><span aria-hidden="true">＋</span></button></article>`;
  }

  function renderCapabilities() {
    const layout = projectCapabilityLayout({ state, storage, storageKey });
    const activeCategory = state.capabilityPageCategory && CAPABILITY_CATEGORIES.some((category) => category.id === state.capabilityPageCategory) ? state.capabilityPageCategory : "perception";
    const category = CAPABILITY_CATEGORIES.find((item) => item.id === activeCategory) || CAPABILITY_CATEGORIES[0];
    const cards = layout.groups.find((group) => group.id === category.id)?.added || [];
    const addTile = '<button type="button" class="capability-add-tile" data-capability-open-library title="添加模块" aria-label="添加模块" aria-haspopup="dialog"><span aria-hidden="true">＋</span></button>';
    const dataNotice = layout.loading ? "正在读取模块目录。" : layout.failed ? "模块目录读取失败。" : "";
    return `<section class="capability-page" data-capability-page data-active-category="${encode(category.id)}">
      <header class="capability-page-header"><div><span class="capability-eyebrow">CAPABILITIES</span><h1>能力</h1></div></header>
      <nav class="capability-tabs" role="tablist" aria-label="能力分类">${CAPABILITY_CATEGORIES.map((item) => `<button type="button" role="tab" id="capability-tab-${encode(item.id)}" aria-controls="capability-panel" data-capability-tab="${encode(item.id)}" aria-selected="${item.id === category.id}" tabindex="${item.id === category.id ? 0 : -1}">${encode(item.label)}</button>`).join("")}</nav>
      <div class="capability-notice" role="status">${encode(state.capabilityLayoutNotice || dataNotice)}</div>
      <div class="capability-grid" data-capability-grid role="tabpanel" id="capability-panel" aria-labelledby="capability-tab-${encode(category.id)}">${cards.map((item, index) => renderCard(item, layout, index, cards.length)).join("")}${addTile}</div>
      <dialog class="capability-library" data-capability-library aria-labelledby="capability-library-title">
        <div class="capability-library-header"><div><span class="capability-eyebrow">MODULE LIBRARY</span><h2 id="capability-library-title">模块库</h2></div><button class="capability-library-close" type="button" data-capability-close-library aria-label="关闭模块库">关闭</button></div>
        <div class="capability-library-groups">${CAPABILITY_CATEGORIES.map((item) => { const entries = layout.groups.find((group) => group.id === item.id)?.library || []; return `<section class="capability-library-group" data-capability-library-group="${encode(item.id)}"><h3>${encode(item.label)}</h3><div class="capability-grid">${entries.length ? entries.map(renderLibraryCard).join("") : `<div class="capability-empty">没有未添加模块。</div>`}</div></section>`; }).join("")}</div>
      </dialog>
    </section>`;
  }

  function bindCapabilities({ root, onChange = () => {}, onConfigure = () => {} } = {}) {
    if (!root) return () => {};
    let dialog = root.querySelector("[data-capability-library]");
    if (!dialog) return () => {};
    const focus = (attribute, value) => [...root.querySelectorAll("button")]
      .find((element) => element.getAttribute(attribute) === value && !element.disabled)?.focus({ preventScroll: true });
    const bindDialog = () => {
      dialog = root.querySelector("[data-capability-library]");
      dialog.addEventListener("close", () => {
        if (!dialog.isConnected) return;
        state.capabilityPageLibraryOpen = false;
        root.querySelector("[data-capability-open-library]")?.focus();
      });
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        event.stopPropagation();
        state.capabilityPageLibraryOpen = false;
        dialog.close();
      });
      if (state.capabilityPageLibraryOpen) dialog.showModal();
    };
    const redraw = () => {
      root.innerHTML = renderCapabilities();
      bindDialog();
    };
    const change = (action, moduleId) => {
      const projection = projectCapabilityLayout({ state, storage, storageKey });
      const item = [...projection.added, ...projection.library].find((entry) => entry.id === moduleId);
      if (!item || (action === "add" && (!item.registered || projection.loading || projection.failed))) return;
      const current = { ...projection.persisted, order: projection.added.map((entry) => entry.id) };
      let next = changeCapabilityLayout(current, action, moduleId);
      if (action.startsWith("move-")) {
        const group = projection.groups.find((entry) => entry.id === item.category).added;
        const index = group.findIndex((entry) => entry.id === moduleId);
        const neighbor = group[index + (action === "move-up" ? -1 : 1)];
        if (!neighbor) return;
        next = { ...current, order: [...current.order] };
        const first = next.order.indexOf(moduleId);
        const second = next.order.indexOf(neighbor.id);
        [next.order[first], next.order[second]] = [next.order[second], next.order[first]];
      }
      if (!writeCapabilityLayout(next, storage, storageKey)) {
        state.capabilityLayoutNotice = "页面布局保存失败；布局没有改变，也未启用任何功能。";
      } else {
        state.capabilityLayoutNotice = "";
        onChange({ action, moduleId });
      }
      redraw();
      if (state.capabilityPageLibraryOpen) {
        dialog.querySelector("[data-capability-add]:not([disabled])")?.focus();
      } else if (action.startsWith("move-")) {
        const target = [...root.querySelectorAll("[data-capability-move]")].find((button) => button.dataset.moduleId === moduleId && !button.disabled);
        target?.focus();
      } else {
        root.querySelector("[data-capability-open-library]")?.focus();
      }
    };
    const onClick = (event) => {
      const target = event.target.closest?.("button");
      if (!target || !root.contains(target) || target.disabled) return;
      if (target.dataset.capabilityTab) {
        state.capabilityPageCategory = target.dataset.capabilityTab;
        redraw();
        focus("data-capability-tab", state.capabilityPageCategory);
      } else if (target.matches("[data-capability-open-library]")) {
        state.capabilityPageLibraryOpen = true;
        dialog.showModal();
        dialog.querySelector("[data-capability-close-library]")?.focus();
      } else if (target.matches("[data-capability-close-library]")) {
        state.capabilityPageLibraryOpen = false;
        dialog.close();
      } else if (target.dataset.capabilityAdd) {
        change("add", target.dataset.capabilityAdd);
      } else if (target.dataset.capabilityRemove) {
        change("remove", target.dataset.capabilityRemove);
      } else if (target.dataset.capabilityMove) {
        change(target.dataset.capabilityMove === "up" ? "move-up" : "move-down", target.dataset.moduleId);
      } else if (target.dataset.capabilityConfigure) {
        onConfigure(target.dataset.capabilityConfigure);
      }
    };
    const onKeydown = (event) => {
      if (event.key === "Escape" && dialog.open) {
        event.preventDefault();
        event.stopPropagation();
        state.capabilityPageLibraryOpen = false;
        dialog.close();
        return;
      }
      const tab = event.target.closest?.("[data-capability-tab]");
      const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
      if (!tab || !keys.includes(event.key)) return;
      event.preventDefault();
      const current = CAPABILITY_CATEGORIES.findIndex((entry) => entry.id === tab.dataset.capabilityTab);
      const count = CAPABILITY_CATEGORIES.length;
      const index = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + count) % count;
      state.capabilityPageCategory = CAPABILITY_CATEGORIES[index].id;
      redraw();
      focus("data-capability-tab", state.capabilityPageCategory);
    };
    root.addEventListener("click", onClick);
    root.addEventListener("keydown", onKeydown);
    bindDialog();
    return () => { root.removeEventListener("click", onClick); root.removeEventListener("keydown", onKeydown); };
  }

  return { renderCapabilities, bindCapabilities };
}
