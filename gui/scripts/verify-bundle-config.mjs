import { constants, existsSync, statSync, accessSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ALLOW_FLAG = "--allow-bundle-overlay";
const TARGETS = {
  "aarch64-apple-darwin": { platform: "darwin", arch: "arm64", extension: "" },
  "x86_64-pc-windows-msvc": { platform: "win32", arch: "x64", extension: ".exe" },
};

function fail(message) {
  console.error(`Bundle guard: ${message}`);
  process.exit(1);
}

if (process.argv.length !== 3 || process.argv[2] !== ALLOW_FLAG) {
  fail("direct Tauri bundling is disabled; use `npm run bundle`");
}

const target = process.env.TAURI_ENV_TARGET_TRIPLE;
const targetConfig = TARGETS[target];
if (!targetConfig) {
  fail(`unsupported or missing TAURI_ENV_TARGET_TRIPLE: ${target || "<missing>"}`);
}
if (process.platform !== targetConfig.platform || process.arch !== targetConfig.arch) {
  fail(`${target} sidecars must be bundled on ${targetConfig.platform}/${targetConfig.arch}`);
}

const guiDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sidecar = join(
  guiDir,
  "src-tauri",
  "binaries",
  `claude-keysmith-cli-${target}${targetConfig.extension}`,
);
if (!existsSync(sidecar) || !statSync(sidecar).isFile()) {
  fail(`required sidecar is missing: ${sidecar}`);
}
if (process.platform !== "win32") {
  try {
    accessSync(sidecar, constants.X_OK);
  } catch {
    fail(`required sidecar is not executable: ${sidecar}`);
  }
}
