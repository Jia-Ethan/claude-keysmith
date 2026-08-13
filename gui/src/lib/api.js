// lib/api.js — 前端到 Rust 命令的薄封装 + 组合操作
// Rust 侧实现见 src-tauri/src/cli_runner.rs；所有 CLI 调用一律带 --json。

import { invoke } from "@tauri-apps/api/core";
import { getSettings, normalizeCliPath } from "./settings.js";
import {
  parseStatusReport,
  parseWriteReport,
  parseDoctorReport,
  parseBackupsReport,
  buildInstallArgs,
  buildUninstallArgs,
  buildStatusArgs,
  buildRestoreArgs,
  buildBackupsArgs,
  buildRecoverArgs,
  buildDoctorArgs,
} from "./parser.js";
import { beginOperation, endOperation } from "./store.js";

function invokeTrackedOperation(command, payload) {
  const operationLease = beginOperation();
  if (!operationLease) {
    return Promise.reject(
      new Error("Application exit is pending; refusing to start another backend operation."),
    );
  }
  try {
    return Promise.resolve(invoke(command, payload)).finally(() => {
      endOperation(operationLease);
    });
  } catch (error) {
    endOperation(operationLease);
    throw error;
  }
}

/** 执行 CLI 命令，返回 { stdout, stderr, exit_code, timed_out } */
export function cliRun(args, timeoutMs = 30_000) {
  const { cliPath } = getSettings();
  return invokeTrackedOperation("cli_run", {
    cliPath: cliPath || null,
    args,
    timeoutMs,
  });
}

/** 探测 CLI，返回 { path, runtime } */
export function detectCli() {
  return invokeTrackedOperation("detect_cli");
}

/** 获取 CLI 版本 */
export function cliVersion(cliPath) {
  return invokeTrackedOperation("cli_version", { cliPath: cliPath || null });
}

/** 获取运行时类型：bundled / executable / python */
export function cliRuntime(cliPath) {
  return invokeTrackedOperation("cli_runtime", { cliPath: cliPath || null });
}

/** 验证手动 CLI 路径；未指定时保留 Rust 侧的 sidecar 优先自动探测。 */
export async function resolveCli(
  cliPath,
  {
    detect = detectCli,
    getRuntime = cliRuntime,
    getVersion = cliVersion,
  } = {},
) {
  const manualPath = normalizeCliPath(cliPath);
  if (manualPath) {
    const version = await getVersion(manualPath);
    const runtime = await getRuntime(manualPath);
    return { path: manualPath, version, runtime };
  }

  const detected = await detect();
  const path = detected?.path || null;
  return {
    path,
    version: path ? await getVersion(path) : "",
    runtime: detected?.runtime || "",
  };
}

/* ---------------- 读操作 ---------------- */

export async function fetchStatus({ scope = "user", projectDir = "", runtime } = {}) {
  const args = [...buildStatusArgs({ scope, projectDir, runtime }), "--json"];
  const output = await cliRun(args);
  return parseStatusReport(output);
}

export async function fetchDoctor() {
  const output = await cliRun([...buildDoctorArgs(), "--json"]);
  return parseDoctorReport(output);
}

export async function fetchBackups({ scope, projectDir } = {}) {
  const output = await cliRun([...buildBackupsArgs({ scope, projectDir }), "--json"]);
  return parseBackupsReport(output);
}

/* ---------------- 写操作：先预览（无 --yes），确认后 execute ---------------- */

export function previewInstall(options) {
  return cliRun([...buildInstallArgs(options), "--json"]).then(parseWriteReport);
}

export function executeInstall(options) {
  return cliRun([...buildInstallArgs(options), "--json", "--yes"], 120_000).then(parseWriteReport);
}

export function previewUninstall(options) {
  return cliRun([...buildUninstallArgs(options), "--json"]).then(parseWriteReport);
}

export function executeUninstall(options) {
  return cliRun([...buildUninstallArgs(options), "--json", "--yes"], 120_000).then(parseWriteReport);
}

export function previewRestore(options) {
  return cliRun([...buildRestoreArgs(options), "--json"]).then(parseWriteReport);
}

export function executeRestore(options) {
  return cliRun([...buildRestoreArgs(options), "--json", "--yes"], 120_000).then(parseWriteReport);
}

export function previewRecover(options) {
  return cliRun([...buildRecoverArgs(options), "--json"]).then(parseWriteReport);
}

export function executeRecover(options) {
  return cliRun([...buildRecoverArgs(options), "--json", "--yes"], 120_000).then(parseWriteReport);
}

/** 是否在 Tauri 环境外（纯浏览器预览） */
export function isTauriMissing(err) {
  return (
    !window.__TAURI_INTERNALS__ ||
    (err && typeof err.message === "string" && err.message.includes("__TAURI"))
  );
}

export class CliError extends Error {
  constructor(output = {}) {
    const stdout = String(output.stdout ?? "");
    const stderr = String(output.stderr ?? "");
    const details = [stderr.trim(), stdout.trim()].filter(Boolean);
    super(details.join("\n\n") || `exit ${output.exit_code ?? "unknown"}`);
    this.name = "CliError";
    this.output = output;
    this.stdout = stdout;
    this.stderr = stderr;
    this.exitCode = output.exit_code ?? null;
    this.timedOut = Boolean(output.timed_out);
  }
}
