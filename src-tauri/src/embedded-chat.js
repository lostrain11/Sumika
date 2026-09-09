((action, value, expectedOrigin) => {
  if (location.origin !== expectedOrigin) return JSON.stringify({ status: "login-required", reason: "origin-changed", possibly_sent: false });
  const isChatgpt = location.hostname === "chatgpt.com";
  const isKimi = ["www.kimi.com", "kimi.com", "kimi.moonshot.cn"].includes(location.hostname);
  if (!isChatgpt && !isKimi) return JSON.stringify({ status: "unsupported", possibly_sent: false });
  const visible = (element) => element && element.getClientRects().length && getComputedStyle(element).visibility !== "hidden";
  const first = (selectors) => selectors.map((selector) => document.querySelector(selector)).find(visible);
  const composer = first(isChatgpt ? ["textarea[data-composer-draft-react]", "#prompt-textarea", "[contenteditable='true'][data-lexical-editor='true']"]
    : [".chat-input-editor[contenteditable='true']", "[contenteditable='true'][data-placeholder]", "textarea"]);
  const send = first(isChatgpt ? ["button[data-composer-submit]", "button[data-testid='send-button']", "button[aria-label='Send prompt']", "button[aria-label='Send message']"]
    : [".send-button", "button[aria-label='发送']", "button[data-testid='send-button']"]);
  const text = (document.body?.innerText || "").slice(0, 12000).toLowerCase();
  const pending = !!first(isChatgpt ? ["button[data-testid='stop-button']", "button[aria-label*='Stop']"] : [".stop-button", "button[aria-label='停止']"]);
  const status = /verify you are human|checking your browser|安全验证|人机验证/.test(text) ? "challenge"
    : /usage limit|rate limit|too many requests|reached.*limit|已达到.*限制|请求过多/.test(text) ? "limited"
    : !composer && /log in|sign up|登录|注册/.test(text) ? "login-required" : pending ? "pending" : composer ? "ready" : "unavailable";
  const responses = Array.from(document.querySelectorAll(isChatgpt ? "[data-message-author-role='assistant'], [data-message-role='assistant'], [data-assistant-markdown]" : ".segment-assistant .markdown, .chat-content-item-assistant .markdown"))
    .filter(visible).filter((element, index, elements) => !elements.some((other, otherIndex) => otherIndex !== index && other.contains(element)));
  const response = responses.at(-1)?.innerText || "";
  if (action === "observe" || action === "read") return JSON.stringify({ status, text: response.slice(0, 24000), assistant_count: responses.length });
  if (status !== "ready") return JSON.stringify({ status, possibly_sent: false });
  if (action === "fill") {
    const existing = composer instanceof HTMLTextAreaElement ? composer.value : composer.innerText;
    if (existing.trim()) return JSON.stringify({ status: "takeover", reason: "existing-user-draft", possibly_sent: false });
    if (composer instanceof HTMLTextAreaElement) Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(composer, value);
    else {
      composer.focus();
      const selection = getSelection(), range = document.createRange();
      range.selectNodeContents(composer); selection.removeAllRanges(); selection.addRange(range);
      if (!document.execCommand("insertText", false, value)) return JSON.stringify({ status: "unavailable", possibly_sent: false });
    }
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
    composer.dispatchEvent(new Event("change", { bubbles: true }));
    return JSON.stringify({ status: "filled", assistant_count: responses.length, text: response.slice(0, 24000) });
  }
  if (action === "submit") {
    const draft = composer instanceof HTMLTextAreaElement ? composer.value : composer.innerText;
    if (draft !== value || !send || send.disabled || send.getAttribute("aria-disabled") === "true") return JSON.stringify({ status: "not-sent", possibly_sent: false });
    send.click();
    return JSON.stringify({ status: "pending", possibly_sent: true });
  }
  return JSON.stringify({ status: "unsupported", possibly_sent: false });
})(__ACTION__, __TEXT__, __ORIGIN__)
