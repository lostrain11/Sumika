import { isAbsolute } from "node:path";

const QUALITY_ROUTING_TOOLS = Object.freeze([
  "quality_routing_component_status",
  "quality_routing_offline_fixture"
]);

function positiveInteger(value, fallback, field) {
  const number = Number(value ?? fallback);
  if (!Number.isInteger(number) || number < 100 || number > 120000) {
    throw new Error(`${field} must be an integer between 100 and 120000`);
  }
  return number;
}

function resolveHelperConfig(config = {}) {
  const enabled = config.enabled !== false;
  if (!enabled) return { enabled: false };
  const pythonExecutable = String(config.pythonExecutable || "").trim();
  const dataDirectory = String(config.dataDirectory || "").trim();
  if (!isAbsolute(pythonExecutable)) throw new Error("pythonExecutable must be an explicit absolute path");
  if (!isAbsolute(dataDirectory)) throw new Error("dataDirectory must be an explicit absolute path");
  return {
    enabled: true,
    pythonExecutable,
    dataDirectory,
    startupTimeoutMs: positiveInteger(config.startupTimeoutMs, 5000, "startupTimeoutMs"),
    requestTimeoutMs: positiveInteger(config.requestTimeoutMs, 10000, "requestTimeoutMs")
  };
}

export { QUALITY_ROUTING_TOOLS, positiveInteger, resolveHelperConfig };

