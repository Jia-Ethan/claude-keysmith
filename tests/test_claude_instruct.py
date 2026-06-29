import importlib.util
import os
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-instruct.py"
spec = importlib.util.spec_from_file_location("claude_instruct", MODULE_PATH)
claude_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = claude_instruct
spec.loader.exec_module(claude_instruct)


def run_cli(args, *, home, cwd=None, check=True):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("CLAUDE_CONFIG_DIR", None)
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def test_normalize_md_name_accepts_safe_names():
    assert claude_instruct.normalize_md_name("claude-project-rules") == "claude-project-rules.md"
    assert claude_instruct.normalize_md_name("team.rules.md") == "team.rules.md"


def test_normalize_md_name_rejects_paths_and_empty_names():
    bad_names = ["../x", "/tmp/x", "nested/x", "nested\\x", "..", ".", "", "x y", "@x"]
    for name in bad_names:
        try:
            claude_instruct.normalize_md_name(name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid name to fail: {name!r}")


def test_render_import_block_uses_managed_markers_and_relative_import():
    block = claude_instruct.render_import_block("rules", "project")
    assert '<!-- claude-keysmith:start name=rules -->' in block
    assert '@.claude/keysmith/rules.md' in block
    assert '<!-- claude-keysmith:end name=rules -->' in block


def test_insert_import_block_preserves_existing_content_and_is_idempotent():
    original = "# Existing\n\nKeep this.\n"
    first, changed_first = claude_instruct.ensure_import_block(original, "rules", "@keysmith/rules.md")
    second, changed_second = claude_instruct.ensure_import_block(first, "rules", "@keysmith/rules.md")

    assert changed_first is True
    assert changed_second is False
    assert second == first
    assert second.startswith(original)
    assert second.count("claude-keysmith:start name=rules") == 1


def test_replace_existing_import_block_for_same_name_only():
    content = "before\n<!-- claude-keysmith:start name=rules -->\n@old.md\n<!-- claude-keysmith:end name=rules -->\nafter\n"
    updated, changed = claude_instruct.ensure_import_block(content, "rules", "@keysmith/rules.md")

    assert changed is True
    assert "@old.md" not in updated
    assert "before" in updated
    assert "after" in updated
    assert "@keysmith/rules.md" in updated


def test_remove_import_block_only_removes_matching_managed_block():
    content = "intro\n<!-- claude-keysmith:start name=one -->\n@keysmith/one.md\n<!-- claude-keysmith:end name=one -->\nkeep\n<!-- claude-keysmith:start name=two -->\n@keysmith/two.md\n<!-- claude-keysmith:end name=two -->\n"
    updated, changed = claude_instruct.remove_import_block(content, "one")

    assert changed is True
    assert "name=one" not in updated
    assert "name=two" in updated
    assert "keep" in updated


def test_cli_default_dry_run_writes_nothing_for_user_scope(tmp_path):
    home = tmp_path / "home"
    result = run_cli(["install", "--scope", "user", "--name", "rules"], home=home)

    assert "[DRY RUN]" in result.stdout
    assert not (home / ".claude").exists()


def test_install_user_scope_writes_backup_keysmith_file_and_import_block(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    claude_md = claude_dir / "CLAUDE.md"
    claude_md.write_text("# User Memory\n\nDo not remove.\n", encoding="utf-8")
    existing_rule = claude_dir / "keysmith" / "rules.md"
    existing_rule.parent.mkdir()
    existing_rule.write_text("old", encoding="utf-8")

    result = run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)

    assert "[完成]" in result.stdout
    content = claude_md.read_text(encoding="utf-8")
    assert "Do not remove." in content
    assert '<!-- claude-keysmith:start name=rules -->' in content
    assert "@keysmith/rules.md" in content
    assert (claude_dir / "keysmith" / "rules.md").exists()
    assert list(claude_dir.glob("CLAUDE.md.bak_*"))
    backups = list((claude_dir / "keysmith").glob("rules.md.bak_*"))
    assert backups and backups[0].read_text(encoding="utf-8") == "old"


def test_install_project_scope_uses_project_claude_md_and_dot_claude_keysmith(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    (project / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")

    run_cli(["install", "--scope", "project", "--project-dir", str(project), "--name", "rules", "--yes"], home=home)

    assert (project / ".claude" / "keysmith" / "rules.md").exists()
    assert "@.claude/keysmith/rules.md" in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (home / ".claude").exists()


def test_install_local_scope_uses_claude_local_md(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()

    run_cli(["install", "--scope", "local", "--project-dir", str(project), "--name", "local-rules", "--yes"], home=home)

    assert (project / ".claude" / "keysmith" / "local-rules.md").exists()
    assert "@.claude/keysmith/local-rules.md" in (project / "CLAUDE.local.md").read_text(encoding="utf-8")
    assert not (project / "CLAUDE.md").exists()


def test_status_detects_installed_user_scope(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)

    result = run_cli(["status", "--scope", "user", "--name", "rules"], home=home)

    assert "installed: yes" in result.stdout
    assert "import block: yes" in result.stdout
    assert "instruction file: yes" in result.stdout


def test_uninstall_only_removes_own_block_and_instruction_file(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    claude_md = project / "CLAUDE.md"
    claude_md.write_text("# Project\n\nUser content.\n", encoding="utf-8")
    run_cli(["install", "--scope", "project", "--project-dir", str(project), "--name", "rules", "--yes"], home=home)

    result = run_cli(["uninstall", "--scope", "project", "--project-dir", str(project), "--name", "rules", "--yes"], home=home)

    assert "[完成]" in result.stdout
    content = claude_md.read_text(encoding="utf-8")
    assert "User content." in content
    assert "claude-keysmith:start name=rules" not in content
    assert not (project / ".claude" / "keysmith" / "rules.md").exists()
    assert list(project.glob("CLAUDE.md.bak_*"))


def test_uninstall_dry_run_writes_nothing(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    claude_md = home / ".claude" / "CLAUDE.md"
    before = claude_md.read_text(encoding="utf-8")

    result = run_cli(["uninstall", "--scope", "user", "--name", "rules"], home=home)

    assert "[DRY RUN]" in result.stdout
    assert claude_md.read_text(encoding="utf-8") == before
    assert (home / ".claude" / "keysmith" / "rules.md").exists()


def test_restore_restores_selected_backup(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    target = claude_dir / "CLAUDE.md"
    target.write_text("current", encoding="utf-8")
    backup = claude_dir / "CLAUDE.md.bak_20260629_120000"
    backup.write_text("restored", encoding="utf-8")

    run_cli(["restore", "--target", str(target), "--backup", str(backup), "--yes"], home=home)

    assert target.read_text(encoding="utf-8") == "restored"
    assert list(claude_dir.glob("CLAUDE.md.bak_*pre_restore*"))


def test_restore_dry_run_writes_nothing(tmp_path):
    home = tmp_path / "home"
    target = tmp_path / "CLAUDE.md"
    backup = tmp_path / "CLAUDE.md.bak_20260629_120000"
    target.write_text("current", encoding="utf-8")
    backup.write_text("restored", encoding="utf-8")

    result = run_cli(["restore", "--target", str(target), "--backup", str(backup)], home=home)

    assert "[DRY RUN]" in result.stdout
    assert target.read_text(encoding="utf-8") == "current"


def test_explicit_dry_run_overrides_yes_for_install(tmp_path):
    home = tmp_path / "home"
    result = run_cli(["install", "--scope", "user", "--name", "rules", "--dry-run", "--yes"], home=home)

    assert "[DRY RUN]" in result.stdout
    assert not (home / ".claude").exists()


def test_explicit_dry_run_overrides_yes_for_uninstall(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    claude_md = home / ".claude" / "CLAUDE.md"
    before = claude_md.read_text(encoding="utf-8")

    result = run_cli(["uninstall", "--scope", "user", "--name", "rules", "--dry-run", "--yes"], home=home)

    assert "[DRY RUN]" in result.stdout
    assert claude_md.read_text(encoding="utf-8") == before
    assert (home / ".claude" / "keysmith" / "rules.md").exists()


def test_explicit_dry_run_overrides_yes_for_restore(tmp_path):
    home = tmp_path / "home"
    target = tmp_path / "CLAUDE.md"
    backup = tmp_path / "CLAUDE.md.bak_20260629_120000"
    target.write_text("current", encoding="utf-8")
    backup.write_text("restored", encoding="utf-8")

    result = run_cli(["restore", "--target", str(target), "--backup", str(backup), "--dry-run", "--yes"], home=home)

    assert "[DRY RUN]" in result.stdout
    assert target.read_text(encoding="utf-8") == "current"


def test_install_refuses_unsafe_file_name_via_cli(tmp_path):
    home = tmp_path / "home"
    result = run_cli(["install", "--scope", "user", "--name", "../x", "--yes"], home=home, check=False)

    assert result.returncode != 0
    assert "[错误]" in result.stdout
    assert not (home / ".claude").exists()
