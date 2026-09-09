export const CAPABILITY_STORAGE_KEY = "sumika.capability-page.v1";

export const CAPABILITY_CATEGORIES = Object.freeze([
  Object.freeze({ id: "perception", label: "感知与交互", moduleIds: Object.freeze(["asr", "tts", "vad", "vision", "screen", "camera", "ocr", "screen-translate"]) }),
  Object.freeze({ id: "productivity", label: "效率工具", moduleIds: Object.freeze(["llm", "tools", "memory"]) }),
  Object.freeze({ id: "life", label: "生活与陪伴", moduleIds: Object.freeze(["music", "todo"]) }),
]);

const CATALOG = Object.freeze([
  ["asr", "语音识别", "将语音转换为文字", "perception"],
  ["tts", "语音播报", "将文字转换为语音", "perception"],
  ["vad", "语音活动检测", "识别语音活动边界", "perception"],
  ["vision", "图像理解", "理解图像中的内容", "perception"],
  ["screen", "屏幕读取", "读取屏幕内容供明确请求使用", "perception"],
  ["camera", "摄像头", "读取摄像头画面供明确请求使用", "perception"],
  ["ocr", "OCR 文字识别", "从图像中识别文字", "perception"],
  ["screen-translate", "截屏翻译", "从截屏中识别并翻译文字", "perception"],
  ["llm", "大语言模型", "处理对话和文本任务", "productivity"],
  ["tools", "外部工具", "在明确批准后调用外部工具", "productivity"],
  ["memory", "记忆", "管理可检索的长期信息", "productivity"],
  ["music", "音乐", "连接可选的音乐服务", "life"],
  ["todo", "待办", "管理可选的待办事项", "life"],
].map(([id, name, description, category]) => Object.freeze({ id, name, description, category })));

const CATALOG_BY_ID = new Map(CATALOG.map((item) => [item.id, item]));
const ID_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const GRANTED_STATES = new Set(["granted", "allowed", "authorized"]);
const DENIED_STATES = new Set(["denied", "blocked", "rejected"]);

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validId(value) {
  return typeof value === "string" && ID_PATTERN.test(value);
}

function uniqueIds(values) {
  return [...new Set((Array.isArray(values) ? values : []).filter(validId))];
}

function storageFor(storage) {
  if (storage) return storage;
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

export function readCapabilityLayout(storage, key = CAPABILITY_STORAGE_KEY) {
  const source = storageFor(storage);
  if (!source || typeof source.getItem !== "function") return { version: 1, order: [], removed: [] };
  try {
    const parsed = JSON.parse(source.getItem(key) || "null");
    if (!isObject(parsed) || parsed.version !== 1) return { version: 1, order: [], removed: [] };
    const order = uniqueIds(parsed.order);
    const removed = uniqueIds(parsed.removed).filter((id) => !order.includes(id));
    return { version: 1, order, removed };
  } catch {
    return { version: 1, order: [], removed: [] };
  }
}

export function writeCapabilityLayout(layout, storage, key = CAPABILITY_STORAGE_KEY) {
  const source = storageFor(storage);
  if (!source || typeof source.setItem !== "function") return false;
  const value = {
    version: 1,
    order: uniqueIds(layout?.order),
    removed: uniqueIds(layout?.removed).filter((id) => !uniqueIds(layout?.order).includes(id)),
  };
  try {
    source.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function moduleCategory(module) {
  if (CAPABILITY_CATEGORIES.some((category) => category.id === module.category)) return module.category;
  if (CAPABILITY_CATEGORIES.some((category) => category.id === module.category_id)) return module.category_id;
  const known = CATALOG_BY_ID.get(module.id);
  if (known) return known.category;
  return "productivity";
}

function moduleDescriptor(module) {
  const known = CATALOG_BY_ID.get(module.id) || {};
  return {
    id: module.id,
    name: module.name || known.name || module.id,
    description: module.description || known.description || "来自运行时的模块",
    category: moduleCategory(module),
    module,
    registered: true,
  };
}

function statusRecords(state) {
  const records = new Map();
  const add = (record) => {
    if (isObject(record) && validId(record.id)) records.set(record.id, record);
  };
  const collect = (value) => {
    if (Array.isArray(value)) value.forEach(add);
    else if (isObject(value)) {
      if (Array.isArray(value.modules)) value.modules.forEach(add);
      if (Array.isArray(value.capabilities)) value.capabilities.forEach(add);
      if (Array.isArray(value.sources)) value.sources.forEach(add);
      Object.entries(value).forEach(([id, record]) => {
        if (validId(id) && isObject(record)) add({ id, ...record });
      });
    }
  };
  collect(state?.status);
  collect(state?.capabilityStatus);
  collect(state?.audioStatus);
  collect(state?.visionStatus);
  return records;
}

function permissionRecords(state, id, module, record) {
  const declarations = uniqueIds([...(Array.isArray(module?.permissions) ? module.permissions : []), ...(Array.isArray(record?.permissions) ? record.permissions.map((item) => isObject(item) ? item.permission_id : item) : Object.keys(record?.permissions || {}))]);
  const states = new Map(declarations.map((permissionId) => [permissionId, "unknown"]));
  const collect = (value) => {
    if (Array.isArray(value)) value.forEach((item) => {
      if (isObject(item) && declarations.includes(item.permission_id)) states.set(item.permission_id, item.state);
    });
    else if (isObject(value)) Object.entries(value).forEach(([permissionId, permissionState]) => {
      if (declarations.includes(permissionId)) states.set(permissionId, isObject(permissionState) ? permissionState.state : permissionState);
    });
  };
  collect(state?.status?.permissions);
  collect(state?.audioStatus?.permissions);
  collect(state?.visionStatus?.permissions);
  collect(module?.permission_states);
  collect(record?.permissions);
  const normalized = [...states.values()].map((value) => typeof value === "string" ? value.toLowerCase() : "unknown");
  const authorization = normalized.length && normalized.every((value) => GRANTED_STATES.has(value))
    ? "已授权"
    : normalized.some((value) => DENIED_STATES.has(value))
      ? "已拒绝"
      : "未知";
  return { declarations, authorization };
}

export function capabilityStatus(state, module, record = statusRecords(state).get(module?.id)) {
  if (!module) return { enabled: false, status: "pending", statusLabel: "待实现", configuration: "未登记", permissions: { declarations: [], authorization: "未知" } };
  const status = module.status || record?.status || record?.state || (module.enabled === true ? "unknown" : "disabled");
  const configuration = module.configuration_status || module.config_status || module.configuration?.status
    || (status === "unconfigured" ? "待配置" : module.configured === true ? "已配置" : module.implementation_id && module.implementation_id !== "none" ? "已选择实现" : "未知");
  return {
    enabled: module.enabled === true,
    status,
    statusLabel: status === "unknown" ? "未知" : status,
    configuration,
    permissions: permissionRecords(state, module.id, module, record),
  };
}

export function projectCapabilityLayout({ state = {}, storage, storageKey = CAPABILITY_STORAGE_KEY } = {}) {
  const modules = Array.isArray(state.modules) ? state.modules.filter((module) => isObject(module) && validId(module.id)) : [];
  const moduleById = new Map(modules.map((module) => [module.id, module]));
  const persisted = readCapabilityLayout(storage, storageKey);
  const order = [...persisted.order];
  modules.forEach((module) => {
    if (module.enabled === true && !persisted.removed.includes(module.id) && !order.includes(module.id)) order.push(module.id);
  });
  const descriptors = new Map(CATALOG.map((item) => [item.id, { ...item, registered: false, module: null }]));
  modules.forEach((module) => descriptors.set(module.id, moduleDescriptor(module)));
  order.filter((id) => !descriptors.has(id)).forEach((id) => descriptors.set(id, { id, name: id, description: "本地布局中的未登记模块", category: "productivity", registered: false, module: null }));
  const added = order.filter((id) => descriptors.has(id) && !persisted.removed.includes(id)).map((id) => descriptors.get(id));
  const addedIds = new Set(added.map((item) => item.id));
  const library = [...descriptors.values()].filter((item) => !addedIds.has(item.id));
  const groups = CAPABILITY_CATEGORIES.map((category) => ({
    ...category,
    added: added.filter((item) => item.category === category.id),
    library: library.filter((item) => item.category === category.id),
  }));
  return {
    groups,
    added,
    library,
    persisted,
    moduleById,
    statusRecords: statusRecords(state),
    loading: state.moduleCatalogStatus === "loading",
    failed: state.moduleCatalogStatus === "error",
  };
}

export function changeCapabilityLayout(layout, action, moduleId) {
  if (!validId(moduleId)) return layout;
  const order = [...(layout?.order || [])];
  const removed = uniqueIds(layout?.removed);
  if (action === "add") {
    if (!order.includes(moduleId)) order.push(moduleId);
    return { version: 1, order, removed: removed.filter((id) => id !== moduleId) };
  }
  if (action === "remove") {
    return { version: 1, order: order.filter((id) => id !== moduleId), removed: [...new Set([...removed, moduleId])] };
  }
  if (action === "move-up" || action === "move-down") {
    const index = order.indexOf(moduleId);
    const target = action === "move-up" ? index - 1 : index + 1;
    if (index >= 0 && target >= 0 && target < order.length) [order[index], order[target]] = [order[target], order[index]];
  }
  return { version: 1, order, removed };
}
