import { describe, it, expect } from "vitest";
import { normalizeBuildInfo, buildInfo } from "./buildInfo.js";

const VALID = "0123456789abcdef0123456789abcdef01234567";

describe("normalizeBuildInfo", () => {
  it("keeps a valid injected build", () => {
    const info = normalizeBuildInfo({
      guiVersion: "0.1.0-beta.1",
      channel: "beta",
      sourceCommit: VALID,
      sidecarCommit: VALID,
    });
    expect(info.guiVersion).toBe("0.1.0-beta.1");
    expect(info.channel).toBe("beta");
    expect(info.sourceCommit).toBe(VALID);
  });

  it("degrades missing fields instead of inventing releases", () => {
    const info = normalizeBuildInfo({});
    expect(info.guiVersion).toBe("unknown");
    expect(info.channel).toBe("development");
    expect(info.sourceCommit).toBeNull();
    expect(info.sidecarCommit).toBeNull();
  });

  it("rejects malformed commits", () => {
    const info = normalizeBuildInfo({ sourceCommit: "v7", sidecarCommit: "HEAD" });
    expect(info.sourceCommit).toBeNull();
    expect(info.sidecarCommit).toBeNull();
  });

  it("is frozen", () => {
    expect(Object.isFrozen(normalizeBuildInfo({}))).toBe(true);
  });
});

describe("generated buildInfo", () => {
  it("exposes the beta GUI version from package.json", () => {
    expect(buildInfo.guiVersion).toBe("0.1.0-beta.1");
    expect(buildInfo.channel).toBe("beta");
  });
});
