import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invokeMock = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...args) => invokeMock(...args) }));

function createStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
}

let api;
let store;
let settings;

beforeEach(async () => {
  vi.resetModules();
  invokeMock.mockReset();
  vi.stubGlobal("localStorage", createStorage());
  settings = await import("./settings.js");
  store = await import("./store.js");
  store.resetOperationCoordinatorForTests();
  api = await import("./api.js");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const { SCHEMA } = await import("./parser.js");

describe("resolveCli", () => {
  it("validates a manual path with version + runtime probes", async () => {
    const result = await api.resolveCli("/x/claude-instruct.py", {
      detect: vi.fn(),
      getVersion: vi.fn().mockResolvedValue("claude-keysmith v7"),
      getRuntime: vi.fn().mockResolvedValue("python"),
    });
    expect(result).toEqual({ path: "/x/claude-instruct.py", version: "claude-keysmith v7", runtime: "python" });
  });

  it("falls back to sidecar-first auto detection", async () => {
    const result = await api.resolveCli("", {
      detect: vi.fn().mockResolvedValue({ path: "/app/claude-keysmith-cli", runtime: "bundled" }),
      getVersion: vi.fn().mockResolvedValue("claude-keysmith v7"),
      getRuntime: vi.fn(),
    });
    expect(result.path).toBe("/app/claude-keysmith-cli");
    expect(result.runtime).toBe("bundled");
  });

  it("returns empty values when nothing is found", async () => {
    const result = await api.resolveCli("", {
      detect: vi.fn().mockResolvedValue(null),
      getVersion: vi.fn(),
      getRuntime: vi.fn(),
    });
    expect(result).toEqual({ path: null, version: "", runtime: "" });
  });
});

describe("cliRun", () => {
  it("passes the manual cliPath through to Rust", async () => {
    settings.saveSettings({ cliPath: "/x/claude-instruct.py" });
    invokeMock.mockResolvedValue({ stdout: "{}", stderr: "", exit_code: 0, timed_out: false });
    await api.cliRun(["status", "--scope", "user", "--json"]);
    expect(invokeMock).toHaveBeenCalledWith("cli_run", {
      cliPath: "/x/claude-instruct.py",
      args: ["status", "--scope", "user", "--json"],
      timeoutMs: 30_000,
    });
  });

  it("tracks operation leases for the exit barrier", async () => {
    let release;
    invokeMock.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const pending = api.cliRun(["doctor", "--json"]);
    expect(store.getState().operationInProgress).toBe(true);
    release({ stdout: "{}", stderr: "", exit_code: 0, timed_out: false });
    await pending;
    expect(store.getState().operationInProgress).toBe(false);
  });

  it("releases the lease even when a store subscriber throws", async () => {
    let release;
    const subscriberError = new Error("subscriber failed");
    const reportError = vi.fn();
    vi.stubGlobal("reportError", reportError);
    invokeMock.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const unsubscribe = store.subscribe(() => { throw subscriberError; });

    const pending = api.cliRun(["doctor", "--json"]);
    expect(store.getState().operationCount).toBe(1);
    expect(pending).toBeInstanceOf(Promise);
    unsubscribe();
    release({ stdout: "{}", stderr: "", exit_code: 0, timed_out: false });
    await pending;
    await Promise.resolve();

    expect(reportError).toHaveBeenCalledWith(subscriberError);
    expect(store.getState().operationCount).toBe(0);
    expect(store.getState().operationInProgress).toBe(false);
  });
});

describe("fetchStatus", () => {
  it("always requests --json and returns the view model", async () => {
    const doc = {
      schema: SCHEMA,
      scope: "user",
      installed: false,
      presence: { memory_file: false, instruction_file: false, import_block: false },
      alignment: { import_block_present: false },
      source_identity: { kind: "missing" },
      recovery_state: { journals: [], journal_count: 0, conflicts: [], lock_present: false, lock_live: false, recovery_required: false, must_recover_before_writes: false },
    };
    invokeMock.mockResolvedValue({ stdout: JSON.stringify(doc), stderr: "", exit_code: 0, timed_out: false });
    const model = await api.fetchStatus({ scope: "user", runtime: true });
    expect(invokeMock.mock.calls[0][1].args).toEqual(["status", "--scope", "user", "--runtime", "--json"]);
    expect(model.health).toBe("not-installed");
  });

  it("fails closed on timeout", async () => {
    invokeMock.mockResolvedValue({ stdout: "", stderr: "", exit_code: -1, timed_out: true });
    await expect(api.fetchStatus({ scope: "user" })).rejects.toThrow(/超时/);
  });
});

describe("preview/execute install", () => {
  const previewDoc = {
    schema: SCHEMA,
    operation: "install",
    mode: "preview",
    ok: true,
    scope: "user",
    name: "claude-project-rules",
    target: { memory_file: "/u/.claude/CLAUDE.md" },
    actions: [],
    warnings: [],
    blockers: [],
    backups: [],
    reload_required: false,
    reload_hint: null,
    exit_status: 0,
    error: null,
    source: { kind: "bundled", path: "/x", size_bytes: 1, sha256: "s" },
  };

  it("preview never sends --yes", async () => {
    invokeMock.mockResolvedValue({ stdout: JSON.stringify(previewDoc), stderr: "", exit_code: 0, timed_out: false });
    const report = await api.previewInstall({ scope: "user", name: "n" });
    const args = invokeMock.mock.calls[0][1].args;
    expect(args).not.toContain("--yes");
    expect(args).toContain("--json");
    expect(report.gate.ok).toBe(true);
  });

  it("execute appends --yes with a longer timeout", async () => {
    invokeMock.mockResolvedValue({ stdout: JSON.stringify({ ...previewDoc, mode: "execute", journal_id: "j" }), stderr: "", exit_code: 0, timed_out: false });
    const report = await api.executeInstall({ scope: "user", name: "n", runtime: true, maxTokens: 20000 });
    const call = invokeMock.mock.calls[0][1];
    expect(call.args).toEqual(["install", "--scope", "user", "--name", "n", "--runtime", "--max-tokens", "20000", "--json", "--yes"]);
    expect(call.timeoutMs).toBe(120_000);
    expect(report.mode).toBe("execute");
    expect(report.journalId).toBe("j");
  });

  it("surfaces blocked previews without throwing", async () => {
    const blocked = { ...previewDoc, ok: false, exit_status: 1, error: "no dir", blockers: ["no dir"] };
    invokeMock.mockResolvedValue({ stdout: JSON.stringify(blocked), stderr: "", exit_code: 1, timed_out: false });
    const report = await api.previewInstall({ scope: "project", projectDir: "/nope" });
    expect(report.gate.ok).toBe(false);
    expect(report.blockers).toEqual(["no dir"]);
  });
});

describe("global write mutex", () => {
  const okDoc = {
    schema: SCHEMA,
    operation: "install",
    mode: "execute",
    ok: true,
    exit_status: 0,
    actions: [],
    warnings: [],
    blockers: [],
    backups: [],
  };

  it("execute writes take the exclusive lease and reject concurrent writes", async () => {
    let releaseFirst;
    invokeMock.mockImplementation(
      () => new Promise((resolve) => {
        releaseFirst = () => resolve({ stdout: JSON.stringify(okDoc), stderr: "", exit_code: 0, timed_out: false });
      }),
    );

    const first = api.executeInstall({ scope: "user", name: "n" });
    await expect(api.executeUninstall({ scope: "user", name: "n" })).rejects.toThrow(
      /Another operation is in progress/,
    );
    expect(invokeMock).toHaveBeenCalledTimes(1);

    releaseFirst();
    await first;

    // Lease released: a subsequent write is allowed again.
    invokeMock.mockResolvedValue({ stdout: JSON.stringify(okDoc), stderr: "", exit_code: 0, timed_out: false });
    await expect(api.executeRecover({ scope: "user" })).resolves.toBeTruthy();
  });

  it("releases an exclusive lease when backend invocation throws synchronously", async () => {
    invokeMock.mockImplementation(() => { throw new Error("invoke failed"); });

    expect(() => api.executeInstall({ scope: "user", name: "n" })).toThrow("invoke failed");
    expect(store.getState().operationCount).toBe(0);
    expect(store.getState().operationInProgress).toBe(false);

    invokeMock.mockResolvedValue({
      stdout: JSON.stringify(okDoc),
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    await expect(api.executeInstall({ scope: "user", name: "n" })).resolves.toBeTruthy();
  });

  it("a running write blocks every other execute entry point", async () => {
    invokeMock.mockImplementation(() => new Promise(() => {}));
    api.executeInstall({ scope: "user", name: "n" });

    await expect(api.executeRestore({ target: "/t", backup: "/b" })).rejects.toThrow(
      /Another operation is in progress/,
    );
    await expect(api.executeRecover({ scope: "user" })).rejects.toThrow(
      /Another operation is in progress/,
    );
    expect(invokeMock).toHaveBeenCalledTimes(1);
  });

  it("preview and read operations stay on the shared lease", async () => {
    invokeMock.mockImplementation(() => new Promise(() => {}));
    api.previewInstall({ scope: "user", name: "n" });

    // Concurrent preview/read must not be rejected by the write mutex.
    api.previewUninstall({ scope: "user", name: "n" });
    api.fetchStatus({ scope: "user" });
    expect(invokeMock).toHaveBeenCalledTimes(3);

    // ...but a write must wait for them.
    await expect(api.executeInstall({ scope: "user", name: "n" })).rejects.toThrow(
      /Another operation is in progress/,
    );
  });

  it("a running write rejects later preview and read operations", async () => {
    let releaseWrite;
    invokeMock.mockImplementation(
      () => new Promise((resolve) => {
        releaseWrite = () => resolve({
          stdout: JSON.stringify(okDoc),
          stderr: "",
          exit_code: 0,
          timed_out: false,
        });
      }),
    );

    const write = api.executeInstall({ scope: "user", name: "n" });
    await expect(api.previewUninstall({ scope: "user", name: "n" })).rejects.toThrow();
    await expect(api.fetchStatus({ scope: "user" })).rejects.toThrow();
    expect(invokeMock).toHaveBeenCalledTimes(1);
    expect(store.getState().operationCount).toBe(1);

    releaseWrite();
    await write;
    expect(store.getState().operationCount).toBe(0);
  });
});

describe("CliError", () => {
  it("summarizes stderr/stdout and flags timeout", () => {
    const err = new api.CliError({ stdout: "out", stderr: "err", exit_code: 3, timed_out: true });
    expect(err.message).toContain("err");
    expect(err.exitCode).toBe(3);
    expect(err.timedOut).toBe(true);
  });
});
