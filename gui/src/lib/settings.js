// lib/settings.js — 应用设置持久化（localStorage）
// 项目卡片只记录用户显式选择过的路径；永不扫描磁盘。

const KEY = "claude-keysmith-gui:settings";

const defaults = {
  cliPath: "",          // 留空 = 自动探测（内置 sidecar 优先）
  defaultProjectDir: "",// deploy wizard project/local 的默认目录
  recentProjects: [],   // [{ path, scope }] — 用户显式选择过的项目
  lang: "zh-CN",
  theme: "system",
};

let cache = null;
const listeners = new Set();

export function normalizeCliPath(value) {
  return typeof value === "string" ? value.trim() : "";
}

export function normalizeRecentProjects(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const list = [];
  for (const entry of value) {
    if (!entry || typeof entry.path !== "string") continue;
    const path = entry.path.trim();
    if (!path || seen.has(path)) continue;
    seen.add(path);
    const scope = entry.scope === "local" ? "local" : "project";
    list.push({ path, scope });
    if (list.length >= 12) break;
  }
  return list;
}

function normalizeSettings(settings) {
  return {
    ...settings,
    cliPath: normalizeCliPath(settings.cliPath),
    defaultProjectDir: typeof settings.defaultProjectDir === "string"
      ? settings.defaultProjectDir.trim()
      : "",
    recentProjects: normalizeRecentProjects(settings.recentProjects),
  };
}

export function getSettings() {
  if (!cache) {
    let stored = {};
    try {
      const parsed = JSON.parse(localStorage.getItem(KEY) || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        stored = parsed;
      }
    } catch {}
    cache = normalizeSettings({ ...defaults, ...stored });
  }
  return { ...cache, recentProjects: [...cache.recentProjects] };
}

export function saveSettings(patch) {
  cache = normalizeSettings({ ...getSettings(), ...patch });
  localStorage.setItem(KEY, JSON.stringify(cache));
  listeners.forEach((fn) => fn(getSettings()));
  return getSettings();
}

/** 记录一个用户显式选择过的项目路径（去重、置顶）。 */
export function rememberProject(path, scope = "project") {
  const trimmed = normalizeCliPath(path);
  if (!trimmed) return getSettings();
  const rest = getSettings().recentProjects.filter((entry) => entry.path !== trimmed);
  return saveSettings({
    recentProjects: [
      { path: trimmed, scope: scope === "local" ? "local" : "project" },
      ...rest,
    ].slice(0, 12),
  });
}

export function removeRecentProject(path) {
  const trimmed = normalizeCliPath(path);
  return saveSettings({
    recentProjects: getSettings().recentProjects.filter((entry) => entry.path !== trimmed),
  });
}

export function onSettingsChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
