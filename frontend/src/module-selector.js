export function projectModules(source = {}) {
  const modules = Array.isArray(source.modules) ? source.modules : [];
  const enabled = modules.filter((module) => module.enabled === true);
  const available = modules.filter((module) => module.enabled !== true);
  return Object.freeze({
    enabled: Object.freeze(enabled),
    available: Object.freeze(available),
    loading: source.moduleCatalogStatus === "loading",
    failed: source.moduleCatalogStatus === "error",
    audioVisible: enabled.some((module) => ["asr", "tts", "vad"].includes(module.id)),
    visionVisible: enabled.some((module) => ["screen", "camera", "vision"].includes(module.id)),
    toolsVisible: enabled.some((module) => module.id === "tools"),
  });
}
