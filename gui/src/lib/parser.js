// lib/parser.js — claude-keysmith JSON 契约（claude-keysmith/v1）→ 视图模型
//
// 只认 stdout 里首个完整 JSON 对象；写操作 preview/execute、status、doctor、
// backups、recover 共用同一解析入口，再按 operation 分流建模。

export const SCHEMA = "claude-keysmith/v1";

export class ContractError extends Error {
  constructor(message, output = {}) {
    super(message);
    this.name = "ContractError";
    this.output = output;
    this.exitCode = output.exit_code ?? null;
    this.timedOut = Boolean(output.timed_out);
  }
}

/** 从 stdout 提取并解析第一个顶层 JSON 对象（容忍前后噪声，容忍尾随文本）。 */
export function extractJson(stdout) {
  const text = String(stdout ?? "");
  const start = text.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(start, i + 1));
        } catch {
          return null;
        }
      }
    }
  }
  return null; // 未闭合 = 输出不完整
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asBool(value) {
  return value === true;
}

/**
 * 校验并包装 CLI 输出为契约文档。
 * 超时/非 JSON/缺 schema 一律抛 ContractError（fail closed）。
 * 非零退出但 stdout 是完整 JSON 时照常返回，由视图层按 ok/blockers 展示。
 */
export function parseContract(output) {
  if (output?.timed_out) {
    throw new ContractError("CLI 执行超时", output);
  }
  const doc = extractJson(output?.stdout);
  if (!doc || typeof doc !== "object") {
    throw new ContractError("CLI 未输出稳定 JSON", output);
  }
  if (doc.schema !== undefined && doc.schema !== SCHEMA) {
    throw new ContractError(`不支持的契约版本: ${String(doc.schema)}`, output);
  }
  doc.exitCode = output?.exit_code ?? null;
  doc.stderr = String(output?.stderr ?? "");
  return doc;
}

/* ---------------- 写操作（install/uninstall/restore/recover） ---------------- */

export function mapAction(action) {
  return {
    action: typeof action?.action === "string" ? action.action : "unknown",
    path: typeof action?.path === "string" ? action.path : "",
    detail: typeof action?.detail === "string" ? action.detail : "",
  };
}

export function mapBackup(backup) {
  return {
    target: typeof backup?.target === "string" ? backup.target : "",
    backupPath: typeof backup?.backup_path === "string" ? backup.backup_path : null,
    sha256: typeof backup?.sha256 === "string" ? backup.sha256 : null,
    sizeBytes: typeof backup?.size_bytes === "number" ? backup.size_bytes : null,
    created: typeof backup?.created === "string" ? backup.created : null,
    planned: backup?.planned === true,
  };
}

export function mapSource(source) {
  if (!source || typeof source !== "object") return null;
  return {
    kind: typeof source.kind === "string" ? source.kind : "unknown",
    path: typeof source.path === "string" ? source.path : null,
    sizeBytes: typeof source.size_bytes === "number" ? source.size_bytes : null,
    sha256: typeof source.sha256 === "string" ? source.sha256 : null,
  };
}

/**
 * 写操作报告（preview 或 execute）。
 * gate: 视图层唯一的“能否继续”判定 —— 非零退出、缺 mode、blockers 非空、
 * ok=false 都会 gate.ok=false。
 */
export function parseWriteReport(output) {
  const doc = parseContract(output);
  const blockers = asArray(doc.blockers).map(String);
  const report = {
    schema: doc.schema ?? null,
    operation: typeof doc.operation === "string" ? doc.operation : "unknown",
    mode: doc.mode === "execute" ? "execute" : "preview",
    ok: asBool(doc.ok),
    scope: typeof doc.scope === "string" ? doc.scope : null,
    name: typeof doc.name === "string" ? doc.name : null,
    target: doc.target && typeof doc.target === "object" ? doc.target : {},
    source: mapSource(doc.source),
    sources: asArray(doc.sources).map(mapSource).filter(Boolean),
    actions: asArray(doc.actions).map(mapAction),
    warnings: asArray(doc.warnings).map(String),
    blockers,
    backups: asArray(doc.backups).map(mapBackup),
    reloadRequired: asBool(doc.reload_required),
    reloadHint: typeof doc.reload_hint === "string" ? doc.reload_hint : null,
    error: typeof doc.error === "string" ? doc.error : null,
    journalId: typeof doc.journal_id === "string" ? doc.journal_id : null,
    runtime: doc.runtime && typeof doc.runtime === "object" ? doc.runtime : null,
    // recover 专属
    residue: asArray(doc.residue),
    plannedRepairs: asArray(doc.planned_repairs).map(mapAction),
    exitCode: doc.exitCode,
    stderr: doc.stderr,
    raw: doc,
  };
  report.gate = gateReport(report);
  return report;
}

export function gateReport(report) {
  const reasons = [];
  if (report.exitCode !== 0) reasons.push(`exit ${report.exitCode ?? "unknown"}`);
  if (report.blockers.length > 0) reasons.push(...report.blockers);
  if (!report.ok && report.blockers.length === 0) {
    reasons.push(report.error || "ok=false");
  }
  return { ok: reasons.length === 0, reasons };
}

/* ---------------- status ---------------- */

export function mapPresence(presence) {
  const p = presence && typeof presence === "object" ? presence : {};
  return {
    memoryFile: asBool(p.memory_file),
    instructionFile: asBool(p.instruction_file),
    importBlock: asBool(p.import_block),
    systemPrompt: asBool(p.system_prompt),
    appendPrompt: asBool(p.append_prompt),
    settingsFile: asBool(p.settings_file),
    shellWrapper: asBool(p.shell_wrapper),
  };
}

export function mapAlignment(alignment) {
  const a = alignment && typeof alignment === "object" ? alignment : {};
  return {
    importBlockPresent: asBool(a.import_block_present),
    importTarget: typeof a.import_target === "string" ? a.import_target : null,
    settingsSystemPromptAligned: asBool(a.settings_system_prompt_aligned),
    shellWrapperCurrent: asBool(a.shell_wrapper_current),
    shellWrapperManaged: asBool(a.shell_wrapper_managed),
  };
}

export function mapSourceIdentity(identity) {
  const s = identity && typeof identity === "object" ? identity : {};
  return {
    kind: typeof s.kind === "string" ? s.kind : "missing",
    instructionSha256: typeof s.instruction_sha256 === "string" ? s.instruction_sha256 : null,
    instructionSizeBytes: typeof s.instruction_size_bytes === "number" ? s.instruction_size_bytes : null,
    drift: s.drift && typeof s.drift === "object" ? s.drift : null,
    systemPromptSha256: typeof s.system_prompt_sha256 === "string" ? s.system_prompt_sha256 : null,
    settingsSystemPromptDrift:
      s.settings_system_prompt_drift && typeof s.settings_system_prompt_drift === "object"
        ? s.settings_system_prompt_drift
        : null,
  };
}

export function mapRuntimeReadiness(readiness) {
  const r = readiness && typeof readiness === "object" ? readiness : {};
  return {
    upstreamCandidates: asArray(r.upstream_candidates),
    upstreamPath: typeof r.upstream_path === "string" ? r.upstream_path : null,
    upstreamExists: asBool(r.upstream_exists),
    shellWrapperCurrent: asBool(r.shell_wrapper_current),
    upgradeRequired: asBool(r.upgrade_required),
    legacyLauncherDetected: asBool(r.legacy_launcher_detected),
    legacyLauncherConflict: asBool(r.legacy_launcher_conflict),
    runtimeReady: asBool(r.runtime_ready),
  };
}

export function mapRecoveryState(recovery) {
  const r = recovery && typeof recovery === "object" ? recovery : {};
  return {
    journals: asArray(r.journals),
    journalCount: typeof r.journal_count === "number" ? r.journal_count : 0,
    conflicts: asArray(r.conflicts),
    lockPresent: asBool(r.lock_present),
    lockLive: asBool(r.lock_live),
    recoveryRequired: asBool(r.recovery_required),
    mustRecoverBeforeWrites: asBool(r.must_recover_before_writes),
  };
}

/**
 * status 视图模型。
 * health: healthy / partial-install / upgrade-required / drifted /
 *         recovery-required / conflict / not-installed
 */
export function parseStatusReport(output) {
  const doc = parseContract(output);
  const model = {
    scope: typeof doc.scope === "string" ? doc.scope : "user",
    root: typeof doc.root === "string" ? doc.root : null,
    memoryFile: typeof doc.memory_file === "string" ? doc.memory_file : null,
    instructionFile: typeof doc.instruction_file === "string" ? doc.instruction_file : null,
    importTarget: typeof doc.import_target === "string" ? doc.import_target : null,
    installed: asBool(doc.installed),
    presence: mapPresence(doc.presence),
    alignment: mapAlignment(doc.alignment),
    sourceIdentity: mapSourceIdentity(doc.source_identity),
    runtimeReadiness: doc.runtime_readiness ? mapRuntimeReadiness(doc.runtime_readiness) : null,
    recovery: mapRecoveryState(doc.recovery_state),
    exitCode: doc.exitCode,
    stderr: doc.stderr,
    raw: doc,
  };
  model.health = deriveHealth(model);
  return model;
}

export function deriveHealth(model) {
  const { presence, alignment, sourceIdentity, runtimeReadiness, recovery, installed } = model;
  if (recovery.recoveryRequired || recovery.mustRecoverBeforeWrites) return "recovery-required";
  if (recovery.conflicts.length > 0 || runtimeReadiness?.legacyLauncherConflict) return "conflict";
  if (sourceIdentity.drift || sourceIdentity.settingsSystemPromptDrift) return "drifted";
  if (runtimeReadiness?.upgradeRequired) return "upgrade-required";
  const anyPresence =
    presence.memoryFile || presence.instructionFile || presence.importBlock
    || presence.systemPrompt || presence.appendPrompt || presence.shellWrapper;
  if (installed && alignment.importBlockPresent) {
    if (runtimeReadiness && !runtimeReadiness.runtimeReady) return "upgrade-required";
    return "healthy";
  }
  if (anyPresence) return "partial-install";
  return "not-installed";
}

/* ---------------- doctor / backups ---------------- */

export function parseDoctorReport(output) {
  const doc = parseContract(output);
  return {
    installationType: typeof doc.installation_type === "string" ? doc.installation_type : "unavailable",
    upstreamCandidates: asArray(doc.upstream_candidates),
    upstreamPath: typeof doc.upstream_path === "string" ? doc.upstream_path : null,
    systemPromptFile: typeof doc.system_prompt_file === "string" ? doc.system_prompt_file : null,
    appendPromptFile: typeof doc.append_prompt_file === "string" ? doc.append_prompt_file : null,
    settingsFile: typeof doc.settings_file === "string" ? doc.settings_file : null,
    shellKind: typeof doc.shell_kind === "string" ? doc.shell_kind : null,
    shellRc: typeof doc.shell_rc === "string" ? doc.shell_rc : null,
    repairActions: asArray(doc.repair_actions).map(String),
    exitCode: doc.exitCode,
    raw: doc,
  };
}

export function parseBackupsReport(output) {
  const doc = parseContract(output);
  return {
    scope: typeof doc.scope === "string" ? doc.scope : null,
    scopeRoot: typeof doc.scope_root === "string" ? doc.scope_root : null,
    count: typeof doc.count === "number" ? doc.count : 0,
    backups: asArray(doc.backups).map((b) => ({
      backupPath: typeof b?.backup_path === "string" ? b.backup_path : "",
      targetName: typeof b?.target_name === "string" ? b.target_name : "",
      targetPath: typeof b?.target_path === "string" ? b.target_path : "",
      sha256: typeof b?.sha256 === "string" ? b.sha256 : null,
      sizeBytes: typeof b?.size_bytes === "number" ? b.size_bytes : null,
      created: typeof b?.created === "string" ? b.created : null,
      kind: typeof b?.kind === "string" ? b.kind : "unknown",
    })),
    ok: asBool(doc.ok),
    error: typeof doc.error === "string" ? doc.error : null,
    exitCode: doc.exitCode,
    raw: doc,
  };
}

/* ---------------- 参数构造（arg 数组，绝不做 shell 拼接） ---------------- */

export function scopeArgs({ scope, projectDir }) {
  const args = ["--scope", scope];
  if (scope !== "user" && projectDir) args.push("--project-dir", projectDir);
  return args;
}

export function buildInstallArgs({ scope, projectDir, name, file, runtime, appendFile, maxTokens }) {
  const args = ["install", ...scopeArgs({ scope, projectDir })];
  if (name) args.push("--name", name);
  if (file) args.push("--file", file);
  if (scope === "user" && runtime) {
    args.push("--runtime");
    if (appendFile) args.push("--append-file", appendFile);
    if (maxTokens) args.push("--max-tokens", String(maxTokens));
  }
  return args;
}

export function buildUninstallArgs({ scope, projectDir, name, runtime }) {
  const args = ["uninstall", ...scopeArgs({ scope, projectDir })];
  if (name) args.push("--name", name);
  if (scope === "user" && runtime) args.push("--runtime");
  return args;
}

export function buildStatusArgs({ scope, projectDir, runtime }) {
  const args = ["status", ...scopeArgs({ scope, projectDir })];
  if (scope === "user" && runtime) args.push("--runtime");
  return args;
}

export function buildRestoreArgs({ target, backup, scope, projectDir }) {
  const args = ["restore", "--target", target, "--backup", backup];
  if (scope) args.push("--scope", scope);
  if (scope && scope !== "user" && projectDir) args.push("--project-dir", projectDir);
  return args;
}

export function buildBackupsArgs({ scope, projectDir }) {
  return ["backups", ...scopeArgs({ scope, projectDir })];
}

export function buildRecoverArgs({ scope, projectDir }) {
  return ["recover", ...scopeArgs({ scope, projectDir })];
}

export function buildDoctorArgs() {
  return ["doctor"];
}
