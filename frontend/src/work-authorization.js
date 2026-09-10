const dispatchMethods = new Set([
  "agent.session.prompt", "agent.session.retry", "agent.subagent.prompt",
  "sumika.route.dispatch", "sumika.route.retry", "sumika.route.replan", "sumika.route.arm",
  "sumika.consultation.start", "browser.web_chat.message.start", "browser.web_chat.send",
]);

export function createWorkAuthorizationClient({ transport, scope, onPending, onResult }) {
  return async (method, params = {}) => {
    const queueAction = params.action?.kind || params.action || params.kind;
    const billable = dispatchMethods.has(method) || method === "agent.session.update_queue" && ["edit", "steer"].includes(queueAction);
    if (!billable || method === "sumika.route.replan" && (params.dispatch_selected ?? params.dispatchSelected) === false) {
      const result = await transport(method, params);
      if (result?.work_request) onResult(result.work_request);
      return result;
    }
    const requestParams = structuredClone({ ...params, ...scope(), client_request_id: params.client_request_id || crypto.randomUUID() });
    const dispatch = async () => {
      const result = await transport(method, requestParams);
      if (result?.work_request) onResult(result.work_request);
      return result;
    };
    const result = await dispatch();
    if (result?.accepted !== false || result?.work_request?.status !== "awaiting-confirmation") return result;
    const request = result.work_request;
    if (request.external?.limit_enforced !== true || request.quote?.high_cny == null) {
      onPending(request, null);
      return result;
    }
    return new Promise((resolve, reject) => {
      const resume = async () => {
        try {
          const next = await dispatch();
          if (next?.accepted === false && next.work_request?.status === "awaiting-confirmation") {
            onPending(next.work_request, { resume, cancel });
            return;
          }
          resolve(next);
        } catch (error) { reject(error); throw error; }
      };
      const cancel = () => resolve({ accepted: false, reason: "用户已取消本次请求" });
      onPending(request, { resume, cancel });
    });
  };
}
