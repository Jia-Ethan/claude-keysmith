import { describe, it, expect } from "vitest";
import { deriveHealth } from "@/lib/parser";

/**
 * 视图层健康态映射（Dashboard 用户卡与项目卡共用 deriveHealth）。
 * 覆盖：healthy / partial-install / upgrade-required / drifted /
 * recovery-required / conflict / not-installed。
 */
function model(patch = {}) {
  return {
    installed: true,
    presence: { memoryFile: true, instructionFile: true, importBlock: true },
    alignment: { importBlockPresent: true },
    sourceIdentity: { kind: "deployed", drift: null, settingsSystemPromptDrift: null },
    runtimeReadiness: null,
    recovery: { recoveryRequired: false, mustRecoverBeforeWrites: false, conflicts: [], journalCount: 0, lockPresent: false, lockLive: false },
    ...patch,
  };
}

describe("dashboard health derivation", () => {
  it("healthy", () => {
    expect(deriveHealth(model())).toBe("healthy");
  });

  it("recovery-required wins over conflict and drift", () => {
    expect(deriveHealth(model({
      recovery: { recoveryRequired: true, mustRecoverBeforeWrites: true, conflicts: [{ a: 1 }], journalCount: 2, lockPresent: true, lockLive: false },
      sourceIdentity: { drift: { x: 1 } },
    }))).toBe("recovery-required");
  });

  it("conflict from recovery conflicts or legacy launcher", () => {
    expect(deriveHealth(model({ recovery: { recoveryRequired: false, mustRecoverBeforeWrites: false, conflicts: [{ a: 1 }] } }))).toBe("conflict");
    expect(deriveHealth(model({ runtimeReadiness: { legacyLauncherConflict: true, upgradeRequired: false, runtimeReady: true } }))).toBe("conflict");
  });

  it("drifted from instruction or settings.systemPrompt drift", () => {
    expect(deriveHealth(model({ sourceIdentity: { drift: { a: 1 } } }))).toBe("drifted");
    expect(deriveHealth(model({ sourceIdentity: { drift: null, settingsSystemPromptDrift: { a: 1 } } }))).toBe("drifted");
  });

  it("upgrade-required for legacy wrapper / stale runtime", () => {
    expect(deriveHealth(model({ runtimeReadiness: { upgradeRequired: true, runtimeReady: false, legacyLauncherConflict: false } }))).toBe("upgrade-required");
    expect(deriveHealth(model({ runtimeReadiness: { upgradeRequired: false, runtimeReady: false, legacyLauncherConflict: false } }))).toBe("upgrade-required");
  });

  it("partial-install and not-installed", () => {
    expect(deriveHealth(model({ installed: false, alignment: { importBlockPresent: false } }))).toBe("partial-install");
    expect(deriveHealth(model({
      installed: false,
      presence: { memoryFile: false, instructionFile: false, importBlock: false },
      alignment: { importBlockPresent: false },
    }))).toBe("not-installed");
  });
});
