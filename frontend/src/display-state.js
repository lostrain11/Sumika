export const DISPLAY_MODES = Object.freeze(["workspace", "pet"]);
export const CHARACTER_THEMES = Object.freeze({ sakura: "#a94067", sage: "#50725f", blue: "#21798b", berry: "#b42f54" });

export function displayMode(value) {
  if (!DISPLAY_MODES.includes(value)) throw new Error("不支持的显示模式");
  return value;
}

export function readDisplayPreferences(storage) {
  try {
    const value = JSON.parse(storage.getItem("sumika.display.v1") || "{}");
    return { theme: Object.hasOwn(CHARACTER_THEMES, value?.theme) ? value.theme : null, transparent: value?.transparent === true };
  } catch {
    return { theme: null, transparent: false };
  }
}

export function writeDisplayPreferences(storage, value) {
  try {
    storage.setItem("sumika.display.v1", JSON.stringify({ theme: Object.hasOwn(CHARACTER_THEMES, value.theme) ? value.theme : null, transparent: value.transparent === true }));
    return true;
  } catch {
    return false;
  }
}
