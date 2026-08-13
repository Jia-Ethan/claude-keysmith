import { describe, it, expect } from "vitest";
import {
  SCHEMA,
  ContractError,
  extractJson,
  parseContract,
  parseWriteReport,
  parseStatusReport,
  parseDoctorReport,
  parseBackupsReport,
  deriveHealth,
  gateReport,
  buildInstallArgs,
  buildUninstallArgs,
  buildStatusArgs,
  buildRestoreArgs,
  buildBackupsArgs,
  buildRecoverArgs,
} from "./parser.js";

function output(doc, { exitCode = 0, timedOut = false } = {}) {
  return {
    stdout: typeof doc === "string" ? doc : JSON.stringify(doc),
    stderr: "",
    exit_code: exitCode,
    timed_out: timedOut,
  };
}

const writePreview = {
  schema: SCHEMA,
  operation: "install",
  mode: "preview",
  ok: true,
  scope: "project",
  name: "claude-project-rules",
  target: {
    memory_file: "/p/CLAUDE.md",
    instruction_file: "/p/.claude/keysmith/claude-project-rules.md",
    import_target: "@.claude/keysmith/claude-project-rules.md",
  },
  actions: [
    { action: "write", path: "/p/CLAUDE.md", detail: "install/update managed import block" },
    { action: "write", path: "/p/.claude/keysmith/claude-project-rules.md", detail: "write keysmith instruction file" },
  ],
  warnings: [],
  blockers: [],
  backups: [],
  reload_required: false,
  reload_hint: null,
  exit_status: 0,
  error: null,
  source: { kind: "bundled", path: "/r/examples/claude-project-rules.md", size_bytes: 3927, sha256: "abc123" },
};

describe("extractJson", () => {
  it("parses a bare JSON document", () => {
    expect(extractJson('{"a":1}')).toEqual({ a: 1 });
  });
  it("tolerates leading noise and trailing text", () => {
    expect(extractJson('noise\n{"a":"{}"}\ntrailing')).toEqual({ a: "{}" });
  });
  it("returns null for missing or unterminated JSON", () => {
    expect(extractJson("no json here")).toBeNull();
    expect(extractJson('{"a":1')).toBeNull();
  });
  it("returns null for malformed JSON", () => {
    expect(extractJson("{oops}")).toBeNull();
  });
});

describe("parseContract", () => {
  it("fails closed on timeout", () => {
    expect(() => parseContract(output(writePreview, { timedOut: true }))).toThrow(ContractError);
  });
  it("fails closed on non-JSON stdout", () => {
    expect(() => parseContract(output("plain text error"))).toThrow(ContractError);
  });
  it("fails closed on foreign schema", () => {
    expect(() => parseContract(output({ schema: "codex-keysmith/v1" }))).toThrow(/不支持的契约版本/);
  });
  it("keeps non-zero exit JSON documents for the view layer", () => {
    const doc = parseContract(output({ ...writePreview, ok: false, exit_status: 1 }, { exitCode: 1 }));
    expect(doc.exitCode).toBe(1);
    expect(doc.ok).toBe(false);
  });
});

describe("parseWriteReport", () => {
  it("maps a clean install preview", () => {
    const report = parseWriteReport(output(writePreview));
    expect(report.operation).toBe("install");
    expect(report.mode).toBe("preview");
    expect(report.gate.ok).toBe(true);
    expect(report.actions).toHaveLength(2);
    expect(report.actions[0]).toEqual({
      action: "write",
      path: "/p/CLAUDE.md",
      detail: "install/update managed import block",
    });
    expect(report.source).toMatchObject({ kind: "bundled", sha256: "abc123", sizeBytes: 3927 });
    expect(report.target.import_target).toBe("@.claude/keysmith/claude-project-rules.md");
  });

  it("gates on blockers", () => {
    const blocked = { ...writePreview, ok: false, exit_status: 1, error: "boom", blockers: ["boom"] };
    const report = parseWriteReport(output(blocked, { exitCode: 1 }));
    expect(report.gate.ok).toBe(false);
    expect(report.gate.reasons).toContain("boom");
  });

  it("gates on non-zero exit even without blockers", () => {
    const report = parseWriteReport(output(writePreview, { exitCode: 2 }));
    expect(report.gate.ok).toBe(false);
  });

  it("gates on ok=false with error fallback", () => {
    const failed = { ...writePreview, ok: false, exit_status: 1, error: "disk full" };
    const report = parseWriteReport(output(failed));
    expect(report.gate.ok).toBe(false);
    expect(report.gate.reasons).toContain("disk full");
  });

  it("maps execute-time backups and journal", () => {
    const executed = {
      ...writePreview,
      mode: "execute",
      journal_id: "j-1",
      backups: [{
        target: "/p/CLAUDE.md",
        backup_path: "/p/CLAUDE.md.bak_20260814_010826",
        sha256: "def456",
        size_bytes: 154,
        created: "2026-08-14T01:08:26",
      }],
    };
    const report = parseWriteReport(output(executed));
    expect(report.mode).toBe("execute");
    expect(report.journalId).toBe("j-1");
    expect(report.backups[0]).toMatchObject({
      backupPath: "/p/CLAUDE.md.bak_20260814_010826",
      sha256: "def456",
      planned: false,
    });
  });

  it("maps planned backups in uninstall preview", () => {
    const uninstall = {
      ...writePreview,
      operation: "uninstall",
      source: undefined,
      backups: [{ target: "/p/CLAUDE.md", backup_path: null, sha256: "x", size_bytes: 154, created: null, planned: true }],
    };
    const report = parseWriteReport(output(uninstall));
    expect(report.backups[0].planned).toBe(true);
    expect(report.backups[0].backupPath).toBeNull();
    expect(report.source).toBeNull();
  });

  it("maps reload hint", () => {
    const withReload = { ...writePreview, reload_required: true, reload_hint: "reload claude session" };
    const report = parseWriteReport(output(withReload));
    expect(report.reloadRequired).toBe(true);
    expect(report.reloadHint).toBe("reload claude session");
  });

  it("maps recover residue and planned repairs", () => {
    const recover = {
      schema: SCHEMA,
      operation: "recover",
      mode: "preview",
      ok: true,
      scope: "user",
      target: { keysmith_dir: "/u/.claude/keysmith" },
      actions: [],
      warnings: [],
      blockers: [],
      backups: [],
      reload_required: false,
      reload_hint: null,
      exit_status: 0,
      error: null,
      residue: [{ kind: "journal", path: "/u/.claude/keysmith/.journal-x" }],
      planned_repairs: [{ action: "remove", path: "/u/.claude/keysmith/.journal-x", detail: "drop stale journal" }],
    };
    const report = parseWriteReport(output(recover));
    expect(report.residue).toHaveLength(1);
    expect(report.plannedRepairs[0].action).toBe("remove");
    expect(report.gate.ok).toBe(true);
  });
});

describe("gateReport", () => {
  it("passes only when exit=0, ok=true, no blockers", () => {
    expect(gateReport({ exitCode: 0, ok: true, blockers: [], error: null }).ok).toBe(true);
    expect(gateReport({ exitCode: null, ok: true, blockers: [], error: null }).ok).toBe(false);
  });
});

const statusHealthy = {
  schema: SCHEMA,
  scope: "user",
  root: "/u/.claude",
  memory_file: "/u/.claude/CLAUDE.md",
  instruction_file: "/u/.claude/keysmith/claude-project-rules.md",
  import_target: "@keysmith/claude-project-rules.md",
  memory_file_exists: true,
  instruction_file_exists: true,
  import_block_exists: true,
  installed: true,
  presence: {
    memory_file: true,
    instruction_file: true,
    import_block: true,
    system_prompt: true,
    append_prompt: true,
    settings_file: true,
    shell_wrapper: true,
  },
  alignment: {
    import_block_present: true,
    import_target: "@keysmith/claude-project-rules.md",
    settings_system_prompt_aligned: true,
    shell_wrapper_current: true,
    shell_wrapper_managed: true,
  },
  source_identity: {
    kind: "deployed",
    instruction_sha256: "abc",
    instruction_size_bytes: 3928,
    drift: null,
    system_prompt_sha256: "def",
    settings_system_prompt_drift: null,
  },
  recovery_state: {
    journals: [],
    journal_count: 0,
    conflicts: [],
    lock_present: false,
    lock_live: false,
    recovery_required: false,
    must_recover_before_writes: false,
  },
  runtime_readiness: {
    upstream_candidates: [],
    upstream_path: "/usr/local/bin/claude",
    upstream_exists: true,
    shell_wrapper_current: true,
    upgrade_required: false,
    legacy_launcher_detected: false,
    legacy_launcher_paths: [],
    legacy_launcher_conflict: false,
    legacy_launcher_conflict_paths: [],
    runtime_ready: true,
  },
};

describe("parseStatusReport / deriveHealth", () => {
  it("maps a healthy runtime status", () => {
    const model = parseStatusReport(output(statusHealthy));
    expect(model.health).toBe("healthy");
    expect(model.presence.shellWrapper).toBe(true);
    expect(model.alignment.settingsSystemPromptAligned).toBe(true);
    expect(model.runtimeReadiness.upstreamPath).toBe("/usr/local/bin/claude");
    expect(model.sourceIdentity.kind).toBe("deployed");
  });

  it("flags not-installed when nothing exists", () => {
    const empty = {
      ...statusHealthy,
      installed: false,
      presence: { memory_file: false, instruction_file: false, import_block: false },
      alignment: { import_block_present: false },
      runtime_readiness: undefined,
    };
    expect(parseStatusReport(output(empty)).health).toBe("not-installed");
  });

  it("flags partial-install when some pieces exist without a full install", () => {
    const partial = {
      ...statusHealthy,
      installed: false,
      presence: { memory_file: true, instruction_file: false, import_block: false },
      alignment: { import_block_present: false },
      runtime_readiness: undefined,
    };
    expect(parseStatusReport(output(partial)).health).toBe("partial-install");
  });

  it("flags upgrade-required from runtime readiness", () => {
    const upgrade = {
      ...statusHealthy,
      runtime_readiness: { ...statusHealthy.runtime_readiness, upgrade_required: true, runtime_ready: false },
    };
    expect(parseStatusReport(output(upgrade)).health).toBe("upgrade-required");
  });

  it("flags drifted from source identity", () => {
    const drifted = {
      ...statusHealthy,
      source_identity: { ...statusHealthy.source_identity, drift: { expected: "a", actual: "b" } },
    };
    expect(parseStatusReport(output(drifted)).health).toBe("drifted");
  });

  it("flags recovery-required above everything else", () => {
    const recovering = {
      ...statusHealthy,
      source_identity: { ...statusHealthy.source_identity, drift: { a: 1 } },
      recovery_state: { ...statusHealthy.recovery_state, recovery_required: true, journal_count: 1 },
    };
    expect(parseStatusReport(output(recovering)).health).toBe("recovery-required");
  });

  it("flags conflict from recovery conflicts and legacy launcher conflict", () => {
    const conflict = {
      ...statusHealthy,
      recovery_state: { ...statusHealthy.recovery_state, conflicts: [{ path: "/x" }] },
    };
    expect(parseStatusReport(output(conflict)).health).toBe("conflict");
    const legacy = {
      ...statusHealthy,
      runtime_readiness: { ...statusHealthy.runtime_readiness, legacy_launcher_conflict: true },
    };
    expect(parseStatusReport(output(legacy)).health).toBe("conflict");
  });

  it("surfaces missing upstream without crashing", () => {
    const noUpstream = {
      ...statusHealthy,
      runtime_readiness: { ...statusHealthy.runtime_readiness, upstream_path: null, upstream_exists: false },
    };
    const model = parseStatusReport(output(noUpstream));
    expect(model.runtimeReadiness.upstreamExists).toBe(false);
    expect(model.runtimeReadiness.upstreamPath).toBeNull();
  });

  it("keeps Claude-Code-missing runtime optional on project scope (no runtime_readiness)", () => {
    const project = { ...statusHealthy, scope: "project", runtime_readiness: undefined };
    const model = parseStatusReport(output(project));
    expect(model.runtimeReadiness).toBeNull();
    expect(model.health).toBe("healthy");
  });
});

describe("parseDoctorReport", () => {
  it("maps doctor output without credentials", () => {
    const doctor = {
      installation_type: "path",
      upstream_candidates: [{ kind: "path", path: "/bin/claude", exists: true, eligible: true, reason: "available" }],
      upstream_path: "/bin/claude",
      system_prompt_file: "/u/.claude/keysmith/system-prompt.md",
      append_prompt_file: "/u/.claude/keysmith/append-prompt.md",
      settings_file: "/u/.claude/settings.json",
      shell_kind: "zsh",
      shell_rc: "/u/.zshrc",
      repair_actions: ["No repair action required."],
    };
    const model = parseDoctorReport(output(doctor));
    expect(model.installationType).toBe("path");
    expect(model.shellKind).toBe("zsh");
    expect(model.repairActions).toEqual(["No repair action required."]);
    expect(JSON.stringify(model.raw)).not.toContain("token");
  });
});

describe("parseBackupsReport", () => {
  it("maps managed backups", () => {
    const backups = {
      schema: SCHEMA,
      operation: "backups",
      ok: true,
      scope: "project",
      scope_root: "/p",
      backups: [{
        backup_path: "/p/CLAUDE.md.bak_20260814_010826",
        target_name: "CLAUDE.md",
        sha256: "abc",
        size_bytes: 154,
        created: "2026-08-14T01:08:26",
        kind: "memory",
      }],
      count: 1,
      exit_status: 0,
      error: null,
    };
    const model = parseBackupsReport(output(backups));
    expect(model.count).toBe(1);
    expect(model.backups[0]).toMatchObject({ targetName: "CLAUDE.md", kind: "memory", sizeBytes: 154 });
  });

  it("maps an empty backup list", () => {
    const model = parseBackupsReport(output({ schema: SCHEMA, operation: "backups", ok: true, scope: "user", scope_root: "/u", backups: [], count: 0 }));
    expect(model.backups).toEqual([]);
    expect(model.count).toBe(0);
  });
});

describe("arg builders (array-only, never shell strings)", () => {
  it("buildInstallArgs includes runtime flags only for user scope", () => {
    expect(buildInstallArgs({ scope: "user", name: "team", runtime: true, appendFile: "/a.md", maxTokens: 20000 }))
      .toEqual(["install", "--scope", "user", "--name", "team", "--runtime", "--append-file", "/a.md", "--max-tokens", "20000"]);
    expect(buildInstallArgs({ scope: "project", projectDir: "/p", name: "team", runtime: true, maxTokens: 5 }))
      .toEqual(["install", "--scope", "project", "--project-dir", "/p", "--name", "team"]);
  });

  it("buildInstallArgs passes a local file", () => {
    expect(buildInstallArgs({ scope: "user", name: "n", file: "/f.md" }))
      .toEqual(["install", "--scope", "user", "--name", "n", "--file", "/f.md"]);
  });

  it("buildUninstallArgs and buildStatusArgs scope runtime to user", () => {
    expect(buildUninstallArgs({ scope: "user", runtime: true }))
      .toEqual(["uninstall", "--scope", "user", "--runtime"]);
    expect(buildStatusArgs({ scope: "local", projectDir: "/p", runtime: true }))
      .toEqual(["status", "--scope", "local", "--project-dir", "/p"]);
  });

  it("buildRestoreArgs passes target and backup verbatim", () => {
    expect(buildRestoreArgs({ target: "CLAUDE.md", backup: "/p/CLAUDE.md.bak_1", scope: "project", projectDir: "/p" }))
      .toEqual(["restore", "--target", "CLAUDE.md", "--backup", "/p/CLAUDE.md.bak_1", "--scope", "project", "--project-dir", "/p"]);
  });

  it("buildBackupsArgs and buildRecoverArgs", () => {
    expect(buildBackupsArgs({ scope: "user" })).toEqual(["backups", "--scope", "user"]);
    expect(buildRecoverArgs({ scope: "project", projectDir: "/p" }))
      .toEqual(["recover", "--scope", "project", "--project-dir", "/p"]);
  });
});
