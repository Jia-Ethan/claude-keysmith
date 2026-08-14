// PyInstaller onefile sidecar 构建（仅本机原生目标）。
// claude-instruct.py 本身已通过 _resource_base() 处理 frozen 资源定位，
// 无需源码补丁；examples/ 作为 datas 一并打包进 sys._MEIPASS。
import { chmodSync, copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const guiDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(guiDir, "..");
const sourcePath = join(repoDir, "claude-instruct.py");
const examplesDir = join(repoDir, "examples");

const TARGETS = {
  "aarch64-apple-darwin": { platform: "darwin", arch: "arm64", extension: "", dataSeparator: ":" },
  "x86_64-pc-windows-msvc": { platform: "win32", arch: "x64", extension: ".exe", dataSeparator: ";" },
};

function argument(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? null : process.argv[index + 1];
}

function hostTarget() {
  if (process.platform === "darwin" && process.arch === "arm64") return "aarch64-apple-darwin";
  if (process.platform === "win32" && process.arch === "x64") return "x86_64-pc-windows-msvc";
  throw new Error(`Unsupported native build host: ${process.platform}/${process.arch}`);
}

const target = argument("--target") || process.env.TAURI_ENV_TARGET_TRIPLE || hostTarget();
const targetConfig = TARGETS[target];
if (!targetConfig) throw new Error(`Unsupported target: ${target}`);
if (process.platform !== targetConfig.platform || process.arch !== targetConfig.arch) {
  throw new Error(`PyInstaller sidecars must be built natively: ${target} requires ${targetConfig.platform}/${targetConfig.arch}`);
}
if (!existsSync(sourcePath)) throw new Error(`CLI source not found: ${sourcePath}`);
if (!existsSync(examplesDir)) throw new Error(`examples/ directory not found: ${examplesDir}`);

// Frozen 资源契约：claude-instruct.py 必须内建 _resource_base() 并在 frozen
// 时解析到 sys._MEIPASS，否则 examples/ 数据无法被找到。
const source = readFileSync(sourcePath, "utf8");
if (!source.includes("def _resource_base()") || !source.includes('getattr(sys, "_MEIPASS")')) {
  throw new Error("claude-instruct.py is missing the frozen-aware _resource_base() resolver; refusing to package");
}

const buildRoot = join(guiDir, "src-tauri", "target", "sidecar-build", target);
const distDir = join(buildRoot, "dist");
const workDir = join(buildRoot, "work");
const specDir = join(buildRoot, "spec");
mkdirSync(buildRoot, { recursive: true });
rmSync(distDir, { recursive: true, force: true });
rmSync(workDir, { recursive: true, force: true });
rmSync(specDir, { recursive: true, force: true });

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const pythonEnv = { ...process.env, PYTHONNOUSERSITE: "1" };
delete pythonEnv.PYTHONHOME;
delete pythonEnv.PYTHONPATH;
delete pythonEnv.PYTHONUSERBASE;
const result = spawnSync(
  python,
  [
    "-m",
    "PyInstaller",
    "--clean",
    "--noconfirm",
    "--onefile",
    "--name",
    "claude-keysmith-cli",
    "--distpath",
    distDir,
    "--workpath",
    workDir,
    "--specpath",
    specDir,
    "--add-data",
    `${examplesDir}${targetConfig.dataSeparator}examples`,
    sourcePath,
  ],
  { cwd: guiDir, encoding: "utf8", stdio: "inherit", env: pythonEnv },
);
if (result.error) throw result.error;
if (result.status !== 0) {
  throw new Error(`PyInstaller failed with exit code ${result.status}. Install gui/requirements-build.txt in the active Python environment.`);
}

const builtPath = join(distDir, `claude-keysmith-cli${targetConfig.extension}`);
if (!existsSync(builtPath)) throw new Error(`PyInstaller output missing: ${builtPath}`);

const binariesDir = join(guiDir, "src-tauri", "binaries");
const destination = join(binariesDir, `claude-keysmith-cli-${target}${targetConfig.extension}`);
const temporary = `${destination}.tmp-${process.pid}`;
mkdirSync(binariesDir, { recursive: true });
copyFileSync(builtPath, temporary);
if (process.platform !== "win32") chmodSync(temporary, 0o755);
renameSync(temporary, destination);

const smoke = spawnSync(destination, ["--version"], { encoding: "utf8" });
if (smoke.error) throw smoke.error;
const reportedVersion = smoke.stdout.trim().split(/\s+/).at(-1);
if (smoke.status !== 0 || !reportedVersion) {
  throw new Error(`Frozen sidecar version smoke failed: ${smoke.stderr || smoke.stdout}`);
}

console.log(`Built ${destination} (${smoke.stdout.trim()})`);
