const confirmationMethods = new Set([
  "work.authorization.confirm", "quality.task.confirm", "quality.task.budget",
  "schedule.create", "schedule.update", "schedule.pause", "agent.approval.respond", "agent.question.respond",
]);

export function requiresHostConfirmation(method) {
  return confirmationMethods.has(method);
}

export async function confirmThroughHost({ method, params, desktop, companion, transport, invoke, openMain }) {
  if (!requiresHostConfirmation(method)) throw new Error("不支持的确认动作");
  if (!desktop) throw new Error("此操作需要在 Sumika 原生工作台确认。");
  if (companion) {
    await openMain();
    throw new Error("请在工作台确认此操作，陪伴窗口不会代为授权。");
  }
  const snapshot = structuredClone(params);
  const preview = await transport("host.confirmation.digest", { method, params: snapshot });
  return invoke("host_confirm", { method, params: snapshot, digest: preview.digest });
}
