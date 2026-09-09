export const NAV_ITEMS = Object.freeze([
  ["Chat", "陪伴"],
  ["Characters", "角色"],
  ["Capabilities", "能力"],
  ["Modules", "连接与权限"],
  ["Tasks", "任务"],
  ["History", "历史"],
  ["Notifications", "通知"],
  ["Settings", "设置"],
  ["Developer", "开发者"],
  ["Agent", "Agent"],
  ["WebWorkbench", "网页工作台"],
  ["Guide", "入门指南"],
].map(Object.freeze));

export const DRAWER_GROUPS = Object.freeze({
  workbench: Object.freeze(["Agent", "WebWorkbench", "Tasks", "History", "Notifications"]),
  characters: Object.freeze(["Characters"]),
  modules: Object.freeze(["Capabilities"]),
  settings: Object.freeze(["Settings", "Modules", "Developer", "Guide"]),
});

export const DRAWER_TITLES = Object.freeze({
  workbench: "工作台",
  characters: "角色",
  modules: "能力",
  settings: "设置",
});

const NAV_LABELS = new Map(NAV_ITEMS);

export function drawerForPage(page) {
  for (const [drawer, pages] of Object.entries(DRAWER_GROUPS)) {
    if (pages.includes(page)) return drawer;
  }
  return null;
}

export function pageLabel(page) {
  return NAV_LABELS.get(page) || page;
}

export function drawerPages(drawer) {
  return DRAWER_GROUPS[drawer] || [];
}

export function isScenePage(page) {
  return page === "Chat" || drawerForPage(page) !== null;
}
