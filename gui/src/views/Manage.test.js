import { describe, it, expect } from "vitest";
import { parseBackupsReport, buildRestoreArgs } from "@/lib/parser";

/**
 * Manage 页核心不变量：
 * - 恢复入口只接受 backups --json 枚举出的受控备份（*.bak_*），
 *   用户不能手填任意路径。
 * - restore 参数把受控路径作为独立 argv 元素传递（无 shell 拼接）。
 */
describe("managed-backup restore contract", () => {
  const report = parseBackupsReport({
    stdout: JSON.stringify({
      schema: "claude-keysmith/v1",
      operation: "backups",
      ok: true,
      scope: "project",
      scope_root: "/p",
      backups: [
        {
          backup_path: "/p/CLAUDE.md.bak_20260814_010826",
          target_name: "CLAUDE.md",
          sha256: "abc",
          size_bytes: 154,
          created: "2026-08-14T01:08:26",
          kind: "memory",
        },
        {
          backup_path: "/p/.claude/keysmith/claude-project-rules.md.bak_20260814_010826",
          target_name: "claude-project-rules.md",
          sha256: "def",
          size_bytes: 3928,
          created: "2026-08-14T01:08:26",
          kind: "instruction",
        },
      ],
      count: 2,
      exit_status: 0,
      error: null,
    }),
    stderr: "",
    exit_code: 0,
    timed_out: false,
  });

  it("lists only keysmith-verified backups with identity", () => {
    expect(report.backups).toHaveLength(2);
    for (const backup of report.backups) {
      expect(backup.backupPath).toMatch(/\.bak_\d{8}_\d{6}$/);
      expect(backup.sha256).toBeTruthy();
      expect(backup.targetName).toBeTruthy();
    }
  });

  it("builds restore argv from the managed backup, never a shell string", () => {
    const backup = report.backups[0];
    const args = buildRestoreArgs({
      target: backup.targetName,
      backup: backup.backupPath,
      scope: "project",
      projectDir: "/p",
    });
    expect(args).toEqual([
      "restore",
      "--target", "CLAUDE.md",
      "--backup", "/p/CLAUDE.md.bak_20260814_010826",
      "--scope", "project",
      "--project-dir", "/p",
    ]);
    // 路径带空格/分号也必须作为单一 argv 元素保留
    const evil = buildRestoreArgs({ target: "a; rm -rf ~", backup: "/b/x.bak_1", scope: "user" });
    expect(evil[2]).toBe("a; rm -rf ~");
    expect(evil).not.toContain("--yes");
  });
});
