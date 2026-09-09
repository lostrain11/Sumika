import { isScenePage } from "./scene-shell.js";

export function createPageView(pages) {
  const renderers = new Map(Object.entries(pages));
  return (page) => {
    if (page === "Chat" || !isScenePage(page)) return "";
    return renderers.get(page)?.() || "";
  };
}

export function renderPageFrame(title, description, content) {
  return `<section class="page-layout content-page"><div class="page-heading"><div><span class="eyebrow">SUMIKA</span><h1 tabindex="-1">${title}</h1><p>${description}</p></div></div>${content}</section>`;
}
