/* ============================================================================
   受管 DSH 工作台 frame 的定位（验证脚本共用）
   ----------------------------------------------------------------------------
   为什么不能写死 :5175
     `/api/workbench/start` 的 port 参数默认 0，即由系统分配端口
     （`ui/workbench.py:204` `start(workspace, port=0)`；`ui/server.py:781`
     取 `payload.get("port", 0)`）。固定 5175 只是当前调用方的选择
     （`ui/app/bind.js:626` 传 `port:5175`），不是结构保证：外部调用方、
     手工启动，或该端口已被非受管实例占用时都可能落到别处——实测见过 :50935。

   写死端口的两种后果都很坏
     1. 找不到 frame → 断言抛错，看起来像产品回归，实则是测试的假设错了；
     2. 更糟：`const frame = ...; if (frame) {...}` 会静默跳过后面全部断言，
        把真正的失败伪装成通过。

   因此按稳定的结构特征识别：同属 127.0.0.1 但与外壳端口不同的那一层 frame。
   ========================================================================== */

function originOf(value) {
  try { return new URL(value).origin; } catch { return null; }
}

/** 外壳自身来源，例如 http://127.0.0.1:8765 */
export function shellOrigin(bridge) {
  return originOf(bridge);
}

/** 该 frame 是否是受管的 DSH 工作台：127.0.0.1 且 origin 不同于外壳。 */
export function isNativeWorkbenchFrame(frame, shell) {
  return isNativeOrigin(frame.url(), shell);
}

/**
 * 该地址是否属于受管 DSH 实例。
 * 用于断言 frame src、过滤发给工作台的资源请求，以及 waitForURL 的谓词——
 * 这些场景只有 URL 字符串，拿不到 Frame 对象。
 */
export function isNativeOrigin(href, shell) {
  if (!/^http:\/\/127\.0\.0\.1:\d+\//.test(String(href))) return false;
  const origin = originOf(href);
  return Boolean(origin) && origin !== originOf(shell);
}

/** 在主文档的直接子 frame 中找工作台；找不到返回 null。 */
export function findNativeFrame(page, bridge) {
  const shell = shellOrigin(bridge);
  return page.frames().find((frame) =>
    frame.parentFrame() === page.mainFrame() && isNativeWorkbenchFrame(frame, shell)) || null;
}

/**
 * 等到工作台 frame 出现。
 * 超时抛错而不是返回 null —— 让「没等到」明确失败，避免调用方静默跳过断言。
 */
export async function waitForNativeFrame(page, bridge, timeout = 120000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    const frame = findNativeFrame(page, bridge);
    if (frame) return frame;
    if (Date.now() >= deadline) {
      throw new Error(`native DSH frame did not appear within ${timeout}ms `
        + `(shell ${shellOrigin(bridge) || bridge})`);
    }
    await page.waitForTimeout(250);
  }
}
