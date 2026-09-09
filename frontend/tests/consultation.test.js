import assert from "node:assert/strict";
import test from "node:test";

import { createConsultationView, consultationNotice } from "../src/consultation-view.js";

test("咨询表面只有可见时才渲染嵌入区域和手动提交", () => {
  const state = { consultation: { visible: false, status: "未打开", notice: "", busy: false, takeover: false, activeAttemptId: "", manualDraft: "" } };
  const view = createConsultationView({ state, escapeHtml: (value) => String(value) });
  assert.doesNotMatch(view.renderConsultation(), /data-consultation-rect/);
  state.consultation.visible = true;
  const html = view.renderConsultation();
  assert.match(html, /data-consultation-rect/);
  assert.match(html, /data-consultation-takeover/);
  assert.match(html, /consultation-manual-form/);
});

test("空白、登录与导航失败有可读提示，未决请求禁止返回首页", () => {
  assert.match(consultationNotice({ status: "unavailable", reason: "empty-document" }), /页面为空/);
  assert.match(consultationNotice({ status: "login" }), /不会读取密码/);
  assert.equal(consultationNotice({ status: "ready" }), "");
  assert.equal(consultationNotice({ status: "unavailable", reason: "已阻止未支持的登录跳转" }), "已阻止未支持的登录跳转");
  const state = { consultation: { visible: true, recoverableAttemptId: "pending-attempt" } };
  const view = createConsultationView({ state, escapeHtml: (value) => String(value) });
  assert.match(view.renderConsultation(), /data-consultation-reload disabled/);
  state.consultation.recoverableAttemptId = "";
  assert.doesNotMatch(view.renderConsultation(), /data-consultation-reload disabled/);
});
