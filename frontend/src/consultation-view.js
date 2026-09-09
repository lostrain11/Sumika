export function consultationNotice(result) {
  const status = result?.status;
  const reason = result?.reason;
  if (reason === "empty-document") return "网页已结束加载，但页面为空。可返回登录首页；若再次出现，将保留导航错误供排查。";
  if (reason === "page-loading" || status === "loading") return "正在加载网页，请稍候。";
  if (reason === "composer-not-found") return "尚未找到聊天输入框，请先完成登录或处理页面提示；不会自动发送。";
  if (reason) return String(reason);
  if (status === "login" || status === "login-required") return "请直接在内置页完成登录，Sumika不会读取密码或验证码。";
  if (status === "challenge") return "请在内置页手动完成验证。";
  if (status === "limited") return "网页当前限流或额度不足，未重发、未切换付费。";
  return "";
}

export function createConsultationView({ escapeHtml, state }) {
  function renderConsultation() {
    const consultation = state.consultation;
    const visible = consultation.visible === true;
    const busy = Boolean(consultation.busy);
    const status = consultation.status || "未打开";
    const readableAttempt = consultation.activeAttemptId || consultation.recoverableAttemptId;
    return `<section class="consultation-panel${visible && consultation.focused ? " is-focused" : ""}" aria-labelledby="consultation-title">
      <div class="consultation-heading"><div><span class="eyebrow">CHATGPT CONSULTATION</span><strong id="consultation-title">网页咨询</strong><small>${escapeHtml(status)}</small></div>
        <div class="consultation-actions"><button class="ghost-button" type="button" data-consultation-open ${busy || visible ? "disabled" : ""}>打开</button>${visible ? `<button class="ghost-button" type="button" data-consultation-focus aria-pressed="${Boolean(consultation.focused)}">${consultation.focused ? "恢复布局" : "展开网页"}</button><button class="ghost-button" type="button" data-consultation-hide ${busy ? "disabled" : ""}>隐藏</button><button class="ghost-button" type="button" data-consultation-close ${busy ? "disabled" : ""}>关闭</button>` : ""}</div>
      </div>
      ${visible ? `<div class="consultation-webview-rect" data-consultation-rect aria-label="嵌入式 ChatGPT 咨询区域"><span>ChatGPT</span></div>
        <div class="consultation-controls">
          <button class="small-button" type="button" data-consultation-observe ${busy ? "disabled" : ""}>检查</button>
          <button class="small-button" type="button" data-consultation-reload ${busy || readableAttempt ? "disabled" : ""}>返回登录首页</button>
          <button class="small-button" type="button" data-consultation-login ${busy || readableAttempt ? "disabled" : ""}>打开登录页</button>
          <button class="small-button" type="button" data-consultation-read ${busy || !readableAttempt ? "disabled" : ""}>读取</button>
          <button class="small-button" type="button" data-consultation-takeover ${busy || consultation.takeover ? "disabled" : ""}>接管</button>
          <button class="small-button" type="button" data-consultation-release ${busy || !consultation.takeover ? "disabled" : ""}>释放</button>
        </div>
        <form id="consultation-manual-form" class="consultation-manual-form"><label>手动提示<textarea name="text" rows="2" maxlength="12000" placeholder="仅在点击提交后写入网页" required>${escapeHtml(consultation.manualDraft || "")}</textarea></label><button class="outline-button" type="submit" ${busy || consultation.takeover ? "disabled" : ""}>提交</button></form>` : ""}
      ${consultation.notice ? `<div class="consultation-notice" role="status">${escapeHtml(consultation.notice)}</div>` : ""}
    </section>`;
  }
  return { renderConsultation };
}
