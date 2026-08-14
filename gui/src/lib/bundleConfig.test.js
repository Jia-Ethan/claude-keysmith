import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const guiDir = resolve(fileURLToPath(new URL("../..", import.meta.url)));

function readJson(path) {
  return JSON.parse(readFileSync(resolve(guiDir, path), "utf8"));
}

describe("Tauri bundle configuration", () => {
  it("keeps direct Tauri builds executable-only and guarded", () => {
    const config = readJson("src-tauri/tauri.conf.json");

    expect(config.bundle.active).toBe(false);
    expect(config.bundle.externalBin).toBeUndefined();
    expect(config.build.beforeBundleCommand).toBe("node scripts/verify-bundle-config.mjs");
  });

  it("enables sidecar bundling only through the packaging overlay", () => {
    const config = readJson("src-tauri/tauri.bundle.conf.json");

    expect(config.bundle.active).toBe(true);
    expect(config.bundle.externalBin).toEqual(["binaries/claude-keysmith-cli"]);
    expect(config.build.beforeBundleCommand).toBe(
      "node scripts/verify-bundle-config.mjs --allow-bundle-overlay",
    );
  });

  it("keeps npm run bundle as the canonical sidecar-first entry point", () => {
    const packageJson = readJson("package.json");

    expect(packageJson.scripts.bundle).toBe(
      "npm run build:sidecar && tauri build --config src-tauri/tauri.bundle.conf.json",
    );
  });

  it("rejects an explicit bundles override without the packaging overlay", () => {
    const guard = spawnSync(process.execPath, [resolve(guiDir, "scripts/verify-bundle-config.mjs")], {
      encoding: "utf8",
    });

    expect(guard.status).toBe(1);
    expect(guard.stderr).toContain("use `npm run bundle`");
  });

  it("does not treat the overlay flag alone as packaging authorization", () => {
    const guard = spawnSync(
      process.execPath,
      [resolve(guiDir, "scripts/verify-bundle-config.mjs"), "--allow-bundle-overlay"],
      {
        encoding: "utf8",
        env: { ...process.env, TAURI_ENV_TARGET_TRIPLE: "unsupported-test-target" },
      },
    );

    expect(guard.status).toBe(1);
    expect(guard.stderr).toContain("unsupported or missing TAURI_ENV_TARGET_TRIPLE");
  });
});
