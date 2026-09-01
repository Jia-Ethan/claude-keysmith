import { beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "claude-keysmith-gui:settings";

function createStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, value)),
    removeItem: vi.fn((key) => values.delete(key)),
    clear: vi.fn(() => values.clear()),
    value: (key) => values.get(key),
  };
}

beforeEach(() => {
  vi.resetModules();
});

async function loadSettings(storage = createStorage()) {
  vi.stubGlobal("localStorage", storage);
  const mod = await import("./settings.js");
  return { ...mod, storage };
}

describe("settings persistence", () => {
  it("has claude defaults", async () => {
    const { getSettings } = await loadSettings();
    expect(getSettings()).toMatchObject({
      cliPath: "",
      defaultProjectDir: "",
      recentProjects: [],
      lang: "zh-CN",
      theme: "system",
    });
  });

  it("normalizes and persists a manual cliPath", async () => {
    const { getSettings, saveSettings, storage } = await loadSettings();
    saveSettings({ cliPath: "  /tmp/claude-instruct.py  " });
    expect(getSettings().cliPath).toBe("/tmp/claude-instruct.py");
    expect(JSON.parse(storage.value(KEY)).cliPath).toBe("/tmp/claude-instruct.py");
  });

  it("ignores corrupt stored JSON", async () => {
    const { getSettings } = await loadSettings(createStorage({ [KEY]: "{oops" }));
    expect(getSettings().lang).toBe("zh-CN");
  });

  it("ignores non-object stored JSON", async () => {
    const { getSettings } = await loadSettings(createStorage({ [KEY]: "null" }));
    expect(getSettings().theme).toBe("system");
  });
});

describe("recent projects", () => {
  it("remembers explicit project paths with dedupe", async () => {
    const { getSettings, rememberProject } = await loadSettings();
    rememberProject("/a", "project");
    rememberProject("/b", "local");
    rememberProject("/a", "project"); // dedupe → 置顶
    expect(getSettings().recentProjects).toEqual([
      { path: "/a", scope: "project" },
      { path: "/b", scope: "local" },
    ]);
  });

  it("coerces unknown scope to project", async () => {
    const { getSettings, rememberProject } = await loadSettings();
    rememberProject("/c", "weird");
    expect(getSettings().recentProjects[0].scope).toBe("project");
  });

  it("removes a project", async () => {
    const { getSettings, rememberProject, removeRecentProject } = await loadSettings();
    rememberProject("/a");
    rememberProject("/b");
    removeRecentProject("/a");
    expect(getSettings().recentProjects).toEqual([{ path: "/b", scope: "project" }]);
  });

  it("ignores blank paths", async () => {
    const { getSettings, rememberProject } = await loadSettings();
    rememberProject("   ");
    expect(getSettings().recentProjects).toEqual([]);
  });

  it("normalizeRecentProjects drops malformed entries and caps at 12", async () => {
    const { normalizeRecentProjects } = await loadSettings();
    const raw = [
      { path: "/ok", scope: "project" },
      { path: 42 },
      null,
      { path: "/ok", scope: "local" }, // dup
      ...Array.from({ length: 20 }, (_, i) => ({ path: `/p${i}`, scope: "local" })),
    ];
    const list = normalizeRecentProjects(raw);
    expect(list.length).toBe(12);
    expect(list[0]).toEqual({ path: "/ok", scope: "project" });
  });

  it("drops malformed entries loaded from storage", async () => {
    const { getSettings } = await loadSettings(createStorage({
      [KEY]: JSON.stringify({ recentProjects: [{ path: 1 }, { path: "/good", scope: "local" }] }),
    }));
    expect(getSettings().recentProjects).toEqual([{ path: "/good", scope: "local" }]);
  });
});
