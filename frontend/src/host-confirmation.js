const confirmationMethods = new Set([
  "work.authorization.confirm",
  "quality.task.confirm",
  "quality.task.budget",
  "schedule.create",
  "schedule.update",
  "schedule.pause",
  "schedule.run",
  "agent.approval.respond",
  "agent.question.respond",
  "agent.session.retry",
  "agent.mcp.configuration.apply",
  "workspace.worktree.create",
  "workspace.commit",
  "workspace.restore",
  "workspace.checkpoint.create",
  "agent.skills.approve",
  "agent.skill.approve",
  "agent.skills.revoke",
  "agent.skill.revoke",
  "agent.session.create",
  "agent.session.select_preset",
  "agent.session.select_model",
  "agent.session.fork",
  "agent.preset.copy",
  "agent.preset.open",
  "agent.preset.remove",
  "agent.workspace.create",
  "agent.provider.sync",
  "model.policy.apply",
  "model.policy.refresh",
  "skill.builtin.set",
  "module.update",
  "plugin.approve",
  "plugin.configure",
  "plugin.run",
  "tool.run",
  "task.run",
  "audio.permission.set",
  "audio.start",
  "audio.asr.transcribe",
  "audio.tts.synthesize",
  "audio.vad.detect",
  "vision.permission.set",
  "vision.start",
  "vision.observe",
  "provider.profile.save",
  "provider.import.save",
  "provider.profile.activate",
  "provider.profile.model.select",
  "provider.profile.restore",
  "provider.profile.models",
  "provider.profile.health",
  "snapshot.restore",
  "browser.embedded.attach",
  "browser.embedded.poll",
  "browser.embedded.complete",
  "browser.embedded.alive",
  "browser.embedded.bind_portal",
  "browser.profile.create",
  "browser.profile.restore",
  "browser.session.create",
  "browser.session.focus",
  "browser.tab.create",
  "browser.tab.select",
  "browser.tab.close",
  "browser.navigate",
  "browser.action.execute",
  "browser.console",
  "browser.network",
  "browser.download.release",
  "browser.download.quarantine",
  "browser.web_chat.profile.create",
  "browser.web_chat.profile.update",
  "browser.web_chat.profile.bind_native",
  "browser.web_chat.profile.native_takeover",
  "browser.web_chat.profile.authorize",
  "browser.web_chat.profile.open",
  "browser.web_chat.profile.focus",
  "browser.web_chat.profile.check",
  "browser.web_chat.profile.consent",
  "browser.web_chat.profile.activate",
  "browser.web_chat.profile.restore",
  "desktop.automation.register",
  "desktop.automation.open",
  "desktop.automation.act",
  "desktop.automation.close",
  "desktop.automation.approval",
  "desktop.automation.takeover",
  "sumika.route.bridge_tools",
  "sumika.route.occupancy",
  "sumika.route.takeover",
  "benefits.configure",
  "benefits.refresh",
  "benefits.checkin",
]);

export function requiresHostConfirmation(method, params = {}) {
  if (!confirmationMethods.has(method)) return false;
  if (!params || typeof params !== "object" || Array.isArray(params)) return true;
  const only = (...keys) => Object.keys(params).every(key => keys.includes(key));
  if (["audio.permission.set", "vision.permission.set"].includes(method)) {
    return !(params.granted === false && only("permission_id", "permission", "granted"));
  }
  if (method === "module.update") return !(params.enabled === false && only("module_id", "enabled"));
  if (method === "skill.builtin.set") {
    return !(params.enabled === false && only("assistant_id", "project_id", "skill_id", "enabled", "sha256"));
  }
  if (method === "schedule.pause") return !(params.paused === true && only("assistant_id", "schedule_id", "paused"));
  if (method === "browser.web_chat.profile.consent") {
    return !(params.enabled === false && only("profile_id", "enabled", "approved"));
  }
  if (method === "sumika.route.bridge_tools") return ("register" in params ? params.register : false) !== false;
  if (method === "model.policy.refresh") return ("interactive_allowed" in params ? params.interactive_allowed : false) !== false;
  if (method === "desktop.automation.approval") {
    if (["operation", "action"].some(key => key in params && typeof params[key] !== "string")) return true;
    const operation = params.operation || params.action || "list";
    return !["list", "status", "revoke", "deny"].includes(operation.trim().toLowerCase());
  }
  if (method === "tool.run") {
    return !(("approved" in params ? params.approved : false) === false && only("tool_id", "input", "approved"));
  }
  return true;
}

export async function confirmThroughHost({ method, params, desktop, companion, transport, invoke, openMain }) {
  if (!requiresHostConfirmation(method, params)) throw new Error("不支持的确认动作");
  if (!desktop) throw new Error("此操作需要在 Sumika 原生工作台确认。");
  if (companion) {
    await openMain();
    throw new Error("请在工作台确认此操作，陪伴窗口不会代为授权。");
  }
  const snapshot = structuredClone(params);
  const preview = await transport("host.confirmation.digest", { method, params: snapshot });
  return invoke("host_confirm", { method, params: snapshot, digest: preview.digest });
}
