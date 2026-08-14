import json

import importlib.util
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-instruct.py"
spec = importlib.util.spec_from_file_location("claude_instruct", MODULE_PATH)
claude_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = claude_instruct
spec.loader.exec_module(claude_instruct)


def run_cli(args, *, home, cwd=None, check=True, extra_env=None):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("CLAUDE_CONFIG_DIR", None)
    for key in (
        "CLAUDE_KEYSMITH_HOME",
        "CLAUDE_KEYSMITH_SHELL",
        "CLAUDE_KEYSMITH_SHELL_RC",
        "CLAUDE_KEYSMITH_CLAUDE_BIN",
    ):
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=check,
    )


def windows_runtime_env(home, profile, **extra):
    env = {
        "CLAUDE_KEYSMITH_SHELL": "powershell",
        "CLAUDE_KEYSMITH_SHELL_RC": str(profile),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "PATH": str(home / "empty-path"),
    }
    env.update({key: str(value) for key, value in extra.items()})
    return env


def candidate_path(candidate):
    return Path(candidate["path"]).resolve()


def first_existing_candidate(candidates):
    return next((item for item in candidates if item.get("exists") and item.get("eligible", True)), None)


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


def test_strip_markdown_h1_removes_title_only():
    body = claude_instruct.strip_markdown_h1("# Title\n\nHello\nWorld\n")
    assert body.startswith("Hello")
    assert "Title" not in body


def test_shell_wrapper_roundtrip_and_legacy_cleanup(tmp_path):
    block = claude_instruct.render_shell_wrapper(
        tmp_path / "bin" / "claude",
        tmp_path / "system-prompt.md",
        tmp_path / "append-prompt.md",
    )
    assert "--append-system-prompt-file" in block
    legacy = (
        "# Claude Code with persistent system prompt override\n"
        "claude() {\n"
        "  /Users/ethan/.local/bin/claude --system-prompt \"$(cat ~/.claude/keysmith/system-prompt.md)\" \"$@\"\n"
        "}\n"
    )
    updated, changed = claude_instruct.ensure_shell_wrapper(legacy, block)
    assert changed is True
    assert claude_instruct.SHELL_BEGIN in updated
    assert "persistent system prompt override" not in updated
    again, changed_again = claude_instruct.ensure_shell_wrapper(updated, block)
    assert changed_again is False
    assert again == updated
    removed, removed_changed = claude_instruct.remove_shell_wrapper(updated)
    assert removed_changed is True
    assert claude_instruct.SHELL_BEGIN not in removed


def test_shell_wrapper_replacement_treats_windows_paths_as_literal_text():
    old = claude_instruct.render_shell_wrapper(
        Path(r"C:\old\claude.exe"),
        Path(r"C:\old\system-prompt.md"),
        Path(r"C:\old\append-prompt.md"),
        "powershell",
    )
    new = claude_instruct.render_shell_wrapper(
        Path(r"C:\Users\Example\claude.exe"),
        Path(r"C:\Users\Example\system-prompt.md"),
        Path(r"C:\Users\Example\append-prompt.md"),
        "powershell",
    )

    updated, changed = claude_instruct.ensure_shell_wrapper(old, new)

    assert changed is True
    assert updated == new


def test_cli_forces_utf8_output_when_inherited_encoding_is_legacy(tmp_path):
    home = tmp_path / "home"

    result = run_cli(
        ["install", "--scope", "user", "--yes"],
        home=home,
        extra_env={"PYTHONIOENCODING": "cp1252"},
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[写入]" in result.stdout


def test_runtime_install_user_scope_writes_prompts_settings_and_wrapper(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.md").write_text("# User Memory\n", encoding="utf-8")
    (claude_dir / "settings.json").write_text('{"model": "opus", "env": {"ANTHROPIC_MODEL": "claude-opus-5"}}\n', encoding="utf-8")
    (home / ".zshrc").write_text("# existing rc\n", encoding="utf-8")
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "claude").write_text("#!/bin/sh\n", encoding="utf-8")

    shell_env = {"CLAUDE_KEYSMITH_SHELL": "zsh"}
    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--yes"],
        home=home,
        extra_env=shell_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[完成]" in result.stdout

    system_prompt = claude_dir / "keysmith" / "system-prompt.md"
    append_prompt = claude_dir / "keysmith" / "append-prompt.md"
    assert system_prompt.exists()
    assert append_prompt.exists()
    assert "senior research engineer and technical writer" in system_prompt.read_text(encoding="utf-8")
    assert "intimate adult fiction" in append_prompt.read_text(encoding="utf-8")

    settings = (claude_dir / "settings.json").read_text(encoding="utf-8")
    assert "systemPrompt" in settings
    assert "ANTHROPIC_MODEL" in settings  # token-less fields preserved

    zshrc = (home / ".zshrc").read_text(encoding="utf-8")
    assert "claude-keysmith runtime" in zshrc
    assert "--append-system-prompt-file" in zshrc
    assert str(system_prompt) in zshrc
    assert str(append_prompt) in zshrc

    status = run_cli(
        ["status", "--scope", "user", "--runtime", "--json"],
        home=home,
        extra_env=shell_env,
    )
    assert '"runtime_ready": true' in status.stdout or '"runtime_ready": true' in status.stdout.replace("True", "true")


def test_runtime_install_sets_max_tokens_only_when_explicit(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text('{"model": "opus", "keep": true}\n', encoding="utf-8")
    (home / ".zshrc").write_text("", encoding="utf-8")
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "claude").write_text("#!/bin/sh\n", encoding="utf-8")

    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--max-tokens", "32000", "--yes"],
        home=home,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    import json

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["max_tokens"] == 32000
    assert settings["keep"] is True
    assert "systemPrompt" in settings


def test_resolve_home_prefers_env_overrides(tmp_path, monkeypatch):
    override = tmp_path / "override-home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(override))
    monkeypatch.setenv("HOME", str(tmp_path / "env-home"))
    assert claude_instruct.resolve_home() == override.resolve()

    monkeypatch.delenv("CLAUDE_KEYSMITH_HOME")
    assert claude_instruct.resolve_home() == (tmp_path / "env-home").resolve()


def test_shell_kind_and_windows_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_KEYSMITH_SHELL", "powershell")
    assert claude_instruct.runtime_shell_kind() == "powershell"

    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL")
    assert claude_instruct.runtime_shell_kind() in {"powershell", "zsh"}

    profile_override = tmp_path / "Documents" / "PowerShell" / "profile.ps1"
    monkeypatch.setenv("CLAUDE_KEYSMITH_SHELL_RC", str(profile_override))
    assert claude_instruct.powershell_profile_path(tmp_path) == profile_override.resolve()

    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL_RC")
    user_modules = tmp_path / "Documents" / "PowerShell" / "Modules"
    user_modules.mkdir(parents=True)
    monkeypatch.setenv("PSModulePath", str(user_modules))
    assert claude_instruct.powershell_profile_path(tmp_path).name == "Microsoft.PowerShell_profile.ps1"
    assert "PowerShell" in claude_instruct.powershell_profile_path(tmp_path).parts


def test_find_claude_binary_override_and_unix_fallback(tmp_path, monkeypatch):
    explicit = tmp_path / "bin" / "claude.cmd"
    monkeypatch.setenv("CLAUDE_KEYSMITH_CLAUDE_BIN", str(explicit))
    assert claude_instruct.find_claude_binary(tmp_path, "powershell") == explicit.resolve()

    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    unix_fallback = claude_instruct.find_claude_binary(tmp_path, "zsh")
    assert unix_fallback == (tmp_path / ".local" / "bin" / "claude").resolve()


def test_render_powershell_wrapper_escapes_single_quotes(tmp_path):
    claude_bin = tmp_path / "claude's" / "claude.cmd"
    system_prompt = tmp_path / "system-prompt.md"
    append_prompt = tmp_path / "append-prompt.md"

    block = claude_instruct.render_shell_wrapper(
        claude_bin,
        system_prompt,
        append_prompt,
        shell_kind="powershell",
    )

    assert "function global:claude" in block
    assert "@args" in block
    assert "''" in block
    assert "--system-prompt-file" in block
    assert "--append-system-prompt-file" in block
    assert "claude() {" not in block


def test_windows_style_runtime_install_uses_powershell_profile(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.md").write_text("# User Memory\n", encoding="utf-8")
    (claude_dir / "settings.json").write_text('{"model": "opus"}\n', encoding="utf-8")

    profile = home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    profile.write_text("# existing powershell profile\n", encoding="utf-8")

    claude_bin = home / "AppData" / "Roaming" / "npm" / "claude.cmd"
    claude_bin.parent.mkdir(parents=True)
    claude_bin.write_text("@echo off\n", encoding="utf-8")

    extra_env = {
        "CLAUDE_KEYSMITH_SHELL": "powershell",
        "CLAUDE_KEYSMITH_SHELL_RC": str(profile),
        "CLAUDE_KEYSMITH_CLAUDE_BIN": str(claude_bin),
    }

    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--yes"],
        home=home,
        extra_env=extra_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "shell kind: powershell" in result.stdout
    assert ". $PROFILE" in result.stdout

    profile_text = profile.read_text(encoding="utf-8")
    assert "function global:claude" in profile_text
    assert "@args" in profile_text
    assert "--system-prompt-file" in profile_text
    assert "--append-system-prompt-file" in profile_text
    assert str(claude_bin) in profile_text

    status = run_cli(
        ["status", "--scope", "user", "--runtime", "--json"],
        home=home,
        extra_env=extra_env,
    )
    status_json = json.loads(status.stdout)
    assert status_json["runtime"]["shell_kind"] == "powershell"
    assert Path(status_json["runtime"]["shell_rc"]) == profile.resolve()
    assert status_json["runtime"]["runtime_ready"] is True

    uninstall = run_cli(
        ["uninstall", "--scope", "user", "--runtime", "--yes"],
        home=home,
        extra_env=extra_env,
    )
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    profile_after = profile.read_text(encoding="utf-8")
    assert "claude-keysmith runtime" not in profile_after
    assert "# existing powershell profile" in profile_after


def test_version_reports_current_version(tmp_path):
    result = run_cli(["--version"], home=tmp_path / "home")
    assert result.stdout.strip() == f"claude-keysmith {claude_instruct.VERSION}"
    assert claude_instruct.VERSION >= "v7"


def test_windows_upstream_override_is_strict_even_when_other_candidates_exist(tmp_path, monkeypatch):
    home = tmp_path / "home"
    native = home / ".local" / "bin" / "claude.exe"
    package_exe = home / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    for path in (native, package_exe):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    missing_override = tmp_path / "strict override" / "claude.exe"
    profile = home / "profile.ps1"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    for key, value in windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=missing_override,
    ).items():
        monkeypatch.setenv(key, value)

    runtime = claude_instruct.user_runtime_paths()
    candidates = runtime["upstream_candidates"]

    assert len(candidates) == 1
    assert candidate_path(candidates[0]) == missing_override.resolve()
    assert candidates[0]["exists"] is False
    assert runtime["upstream_path"] is None
    assert runtime["upstream_exists"] is False
    assert claude_instruct.select_upstream_candidate(candidates) is None


def test_windows_upstream_prefers_native_local_exe(tmp_path, monkeypatch):
    home = tmp_path / "home"
    native = home / ".local" / "bin" / "claude.exe"
    package_exe = home / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    for path in (native, package_exe):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("NPM_CONFIG_PREFIX", raising=False)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("PATH", str(home / "empty-path"))

    candidates = claude_instruct.resolve_upstream_candidates(home, "powershell")
    selected = claude_instruct.select_upstream_candidate(candidates)

    assert selected is not None
    assert candidate_path(selected) == native.resolve()
    assert candidate_path(first_existing_candidate(candidates)) == native.resolve()


def test_windows_upstream_uses_path_native_or_winget_exe(tmp_path, monkeypatch):
    home = tmp_path / "home"
    winget = tmp_path / "Microsoft" / "WinGet" / "Links" / "claude.exe"
    winget.parent.mkdir(parents=True)
    winget.write_bytes(b"fixture")
    winget.chmod(0o755)
    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("NPM_CONFIG_PREFIX", raising=False)
    monkeypatch.setenv("APPDATA", str(home / "empty-appdata"))
    monkeypatch.setenv("PATH", str(winget.parent))
    monkeypatch.setattr(
        claude_instruct.shutil,
        "which",
        lambda name: str(winget) if name.lower() == "claude.exe" else None,
    )

    selected = claude_instruct.select_upstream_candidate(
        claude_instruct.resolve_upstream_candidates(home, "powershell")
    )

    assert selected is not None
    assert candidate_path(selected) == winget.resolve()


def test_windows_upstream_uses_package_exe_when_npm_shim_is_missing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    npm_root = home / "AppData" / "Roaming" / "npm"
    package_exe = npm_root / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    package_exe.parent.mkdir(parents=True)
    package_exe.write_bytes(b"fixture")
    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("NPM_CONFIG_PREFIX", raising=False)
    monkeypatch.setenv("APPDATA", str(npm_root.parent))
    monkeypatch.setenv("PATH", str(home / "empty-path"))

    candidates = claude_instruct.resolve_upstream_candidates(home, "powershell")
    selected = claude_instruct.select_upstream_candidate(candidates)

    assert not (npm_root / "claude.ps1").exists()
    assert selected is not None
    assert candidate_path(selected) == package_exe.resolve()


def test_windows_upstream_honors_custom_npm_prefix_and_shim_fallback(tmp_path, monkeypatch):
    home = tmp_path / "home"
    prefix = tmp_path / "custom npm prefix"
    package_exe = prefix / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    shim = prefix / "claude.ps1"
    package_exe.parent.mkdir(parents=True)
    package_exe.write_bytes(b"package")
    shim.write_text("# npm shim\n", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("NPM_CONFIG_PREFIX", str(prefix))
    monkeypatch.setenv("APPDATA", str(home / "empty-appdata"))
    monkeypatch.setenv("PATH", str(home / "empty-path"))

    candidates = claude_instruct.resolve_upstream_candidates(home, "powershell")
    selected = claude_instruct.select_upstream_candidate(candidates)
    assert selected is not None
    assert candidate_path(selected) == package_exe.resolve()

    package_exe.unlink()
    candidates = claude_instruct.resolve_upstream_candidates(home, "powershell")
    selected = claude_instruct.select_upstream_candidate(candidates)
    assert selected is not None
    assert candidate_path(selected) == shim.resolve()


def test_windows_upstream_all_missing_is_reported_without_fabricated_success(tmp_path, monkeypatch):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    for key, value in windows_runtime_env(home, profile).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("NPM_CONFIG_PREFIX", raising=False)

    runtime = claude_instruct.user_runtime_paths()

    assert runtime["upstream_candidates"]
    assert all(not item["exists"] for item in runtime["upstream_candidates"])
    assert runtime["upstream_exists"] is False
    assert runtime["upstream_path"] is None
    assert claude_instruct.select_upstream_candidate(runtime["upstream_candidates"]) is None


def test_windows_upstream_excludes_keysmith_launcher_that_wins_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    legacy_ps1.write_text(
        "# claude-keysmith\n$systemPrompt = '~/.claude/keysmith/system-prompt.md'\n",
        encoding="utf-8",
    )
    legacy_cmd.write_bytes(
        b'@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %*\r\n'
    )
    npm_root = home / "AppData" / "Roaming" / "npm"
    package_exe = npm_root / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    package_exe.parent.mkdir(parents=True)
    package_exe.write_bytes(b"fixture")
    monkeypatch.delenv("CLAUDE_KEYSMITH_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("NPM_CONFIG_PREFIX", raising=False)
    monkeypatch.setenv("APPDATA", str(npm_root.parent))
    monkeypatch.setenv("PATH", os.pathsep.join((str(local_bin), str(npm_root))))

    candidates = claude_instruct.resolve_upstream_candidates(home, "powershell")
    selected = claude_instruct.select_upstream_candidate(candidates)
    legacy_candidates = [item for item in candidates if candidate_path(item) in {legacy_ps1.resolve(), legacy_cmd.resolve()}]

    assert selected is not None
    assert candidate_path(selected) == package_exe.resolve()
    assert legacy_candidates
    assert all(item.get("eligible") is False for item in legacy_candidates)


def test_powershell_profile_uses_first_valid_user_module_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ps5_modules = home / "Documents" / "WindowsPowerShell" / "Modules"
    ps7_modules = home / "Documents" / "PowerShell" / "Modules"
    ps5_modules.mkdir(parents=True)
    ps7_modules.mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL_RC", raising=False)
    monkeypatch.setenv("PSModulePath", os.pathsep.join((str(ps5_modules), str(ps7_modules))))
    assert claude_instruct.powershell_profile_path(home).parent.name == "WindowsPowerShell"

    monkeypatch.setenv("PSModulePath", os.pathsep.join((str(ps7_modules), str(ps5_modules))))
    assert claude_instruct.powershell_profile_path(home).parent.name == "PowerShell"


@pytest.mark.parametrize("profile_dir", ["PowerShell", "WindowsPowerShell"])
def test_powershell_profile_accepts_user_module_path_before_directory_exists(
    tmp_path, monkeypatch, profile_dir
):
    home = tmp_path / "home"
    modules = home / "Documents" / profile_dir / "Modules"
    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL_RC", raising=False)
    monkeypatch.setenv("PSModulePath", str(modules))

    assert claude_instruct.powershell_profile_path(home) == (
        modules.parent / "Microsoft.PowerShell_profile.ps1"
    )


def test_powershell_profile_rejects_ambiguous_module_path_without_override(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ambiguous = tmp_path / "Modules"
    ambiguous.mkdir()
    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL_RC", raising=False)
    monkeypatch.setenv("PSModulePath", str(ambiguous))

    with pytest.raises(ValueError, match="CLAUDE_KEYSMITH_SHELL_RC"):
        claude_instruct.powershell_profile_path(home)


@pytest.mark.parametrize("profile_dir", ["PowerShell", "WindowsPowerShell"])
def test_powershell_profile_uses_redirected_user_documents_and_ignores_program_files(
    tmp_path, monkeypatch, profile_dir
):
    home = tmp_path / "home"
    redirected_modules = home / "OneDrive - Example Org" / "Documents" / profile_dir / "Modules"
    program_files_modules = tmp_path / "Program Files" / profile_dir / "Modules"
    redirected_modules.mkdir(parents=True)
    program_files_modules.mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL_RC", raising=False)
    monkeypatch.setenv(
        "PSModulePath",
        os.pathsep.join((str(program_files_modules), str(redirected_modules))),
    )

    assert claude_instruct.powershell_profile_path(home) == (
        redirected_modules.parent / "Microsoft.PowerShell_profile.ps1"
    )


def test_powershell_profile_rejects_program_files_only_module_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    program_files_modules = tmp_path / "Program Files" / "PowerShell" / "Modules"
    program_files_modules.mkdir(parents=True)
    monkeypatch.delenv("CLAUDE_KEYSMITH_SHELL_RC", raising=False)
    monkeypatch.setenv("PSModulePath", str(program_files_modules))

    with pytest.raises(ValueError, match="CLAUDE_KEYSMITH_SHELL_RC"):
        claude_instruct.powershell_profile_path(home)


def test_runtime_install_migrates_recognized_local_bin_launchers(tmp_path):
    home = tmp_path / "home"
    profile = home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    legacy_ps1.write_text(
        "$systemPrompt = Join-Path $HOME '.claude\\keysmith\\system-prompt.md'\n"
        "$appendPrompt = Join-Path $HOME '.claude\\keysmith\\append-prompt.md'\n"
        "# claude-keysmith legacy wrapper\n",
        encoding="utf-8",
    )
    legacy_cmd.write_bytes(
        b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0claude.ps1" %*\r\n'
    )
    env = windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=upstream,
    )

    result = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not legacy_ps1.exists()
    assert not legacy_cmd.exists()
    assert list(local_bin.glob("claude.ps1.bak_*_pre_v6*"))
    assert list(local_bin.glob("claude.cmd.bak_*_pre_v6*"))
    assert profile.is_file()


def test_legacy_launcher_migration_never_overwrites_preoccupied_backup(tmp_path):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    legacy_ps1.write_text(
        "# claude-keysmith\n$systemPrompt = 'system-prompt'\n",
        encoding="utf-8",
    )
    legacy_cmd.write_bytes(
        b'@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %*\r\n'
    )
    timestamp = "20260807_120000"
    occupied = local_bin / f"claude.ps1.bak_{timestamp}_pre_v6"
    occupied.write_text("existing recovery point\n", encoding="utf-8")

    moved = claude_instruct.migrate_legacy_launchers(home, timestamp)
    moved_by_source = {source: backup for source, backup in moved}

    assert occupied.read_text(encoding="utf-8") == "existing recovery point\n"
    assert moved_by_source[legacy_ps1].name == f"claude.ps1.bak_{timestamp}_pre_v6_2"
    assert moved_by_source[legacy_ps1].read_text(encoding="utf-8").startswith("# claude-keysmith")
    assert moved_by_source[legacy_cmd].is_file()
    assert not legacy_ps1.exists()
    assert not legacy_cmd.exists()


def test_legacy_launcher_migration_rolls_back_first_file_when_second_move_fails(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    ps1_content = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    cmd_content = '@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %*\r\n'
    legacy_ps1.write_text(ps1_content, encoding="utf-8")
    legacy_cmd.write_bytes(cmd_content.encode("utf-8"))
    real_replace = claude_instruct.os.replace

    def fail_cmd_migration(source, target):
        if Path(source) == legacy_cmd and ".bak_20260807_120000_pre_v6" in str(target):
            raise OSError("cmd migration failed")
        return real_replace(source, target)

    monkeypatch.setattr(claude_instruct.os, "replace", fail_cmd_migration)

    with pytest.raises(OSError, match="cmd migration failed"):
        claude_instruct.migrate_legacy_launchers(home, "20260807_120000")

    assert legacy_ps1.read_text(encoding="utf-8") == ps1_content
    assert legacy_cmd.read_bytes() == cmd_content.encode("utf-8")
    assert not list(local_bin.glob("claude.ps1.bak_*_pre_v6*"))
    assert not list(local_bin.glob("claude.cmd.bak_*_pre_v6*"))


def test_runtime_install_refuses_unknown_local_bin_launcher_before_any_write(tmp_path):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    unknown = home / ".local" / "bin" / "claude.ps1"
    unknown.parent.mkdir(parents=True)
    unknown.write_text("Write-Host 'not owned by keysmith'\n", encoding="utf-8")
    env = windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=upstream,
    )

    result = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)

    assert result.returncode != 0
    assert "拒绝" in result.stdout
    assert unknown.read_text(encoding="utf-8") == "Write-Host 'not owned by keysmith'\n"
    assert not (home / ".claude").exists()
    assert not profile.exists()


def test_runtime_install_rejects_legacy_cmd_with_extra_command_before_any_write(tmp_path):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    ps1_content = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    cmd_content = '@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %* & echo unexpected\r\n'
    legacy_ps1.write_text(ps1_content, encoding="utf-8")
    legacy_cmd.write_bytes(cmd_content.encode("utf-8"))
    env = windows_runtime_env(home, profile, CLAUDE_KEYSMITH_CLAUDE_BIN=upstream)

    result = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)

    assert result.returncode != 0
    assert "拒绝" in result.stdout
    assert legacy_ps1.read_text(encoding="utf-8") == ps1_content
    assert legacy_cmd.read_bytes() == cmd_content.encode("utf-8")
    assert not (home / ".claude").exists()
    assert not profile.exists()


def test_runtime_install_keeps_legacy_launchers_when_later_profile_write_fails(tmp_path, monkeypatch):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    ps1_content = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    cmd_content = '@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %*\r\n'
    legacy_ps1.write_text(ps1_content, encoding="utf-8")
    legacy_cmd.write_bytes(cmd_content.encode("utf-8"))
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    for key, value in windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=upstream,
    ).items():
        monkeypatch.setenv(key, value)
    original_atomic_write = claude_instruct.atomic_write_text

    def fail_profile_write(path, content):
        if Path(path) == profile:
            raise OSError("profile write failed")
        return original_atomic_write(path, content)

    monkeypatch.setattr(claude_instruct, "atomic_write_text", fail_profile_write)
    args = claude_instruct.build_parser().parse_args(
        ["install", "--scope", "user", "--runtime", "--yes"]
    )
    try:
        return_code = claude_instruct.command_install(args)
    except OSError:
        return_code = 1

    assert return_code != 0
    assert legacy_ps1.read_text(encoding="utf-8") == ps1_content
    assert legacy_cmd.read_bytes() == cmd_content.encode("utf-8")
    assert not list(local_bin.glob("claude.ps1.bak_*_pre_v6*"))
    assert not list(local_bin.glob("claude.cmd.bak_*_pre_v6*"))


def test_v5_powershell_wrapper_is_upgraded_in_place_and_reinstall_is_idempotent(tmp_path):
    home = tmp_path / "home"
    profile = home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    old_upstream = home / "AppData" / "Roaming" / "npm" / "claude.ps1"
    old_block = "\n".join(
        [
            "# existing profile",
            claude_instruct.SHELL_BEGIN,
            "# Managed by claude-keysmith. Do not edit by hand.",
            "function global:claude {",
            f"  & '{old_upstream}' `",
            f"    --system-prompt-file '{home / '.claude' / 'keysmith' / 'system-prompt.md'}' `",
            f"    --append-system-prompt-file '{home / '.claude' / 'keysmith' / 'append-prompt.md'}' `",
            "    @args",
            "}",
            claude_instruct.SHELL_END,
            "",
        ]
    )
    profile.write_text(old_block, encoding="utf-8")
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    env = windows_runtime_env(home, profile, CLAUDE_KEYSMITH_CLAUDE_BIN=upstream)

    first = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)
    assert first.returncode == 0, first.stdout + first.stderr
    first_profile = profile.read_text(encoding="utf-8")
    second = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)
    assert second.returncode == 0, second.stdout + second.stderr

    assert profile.read_text(encoding="utf-8") == first_profile
    assert first_profile.count(claude_instruct.SHELL_BEGIN) == 1
    assert str(old_upstream) not in first_profile
    status = json.loads(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env).stdout
    )["runtime"]
    assert status["shell_wrapper_current"] is True
    assert status["upgrade_required"] is False


def test_runtime_status_includes_v6_fields_and_requires_an_upstream(tmp_path):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    missing = tmp_path / "missing" / "claude.exe"
    env = windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=missing,
    )
    install = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)
    assert install.returncode == 0, install.stdout + install.stderr

    status = json.loads(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env).stdout
    )["runtime"]
    expected = {
        "upstream_candidates",
        "upstream_path",
        "upstream_exists",
        "shell_wrapper_current",
        "legacy_launcher_detected",
        "legacy_launcher_paths",
        "upgrade_required",
    }
    assert expected <= status.keys()
    assert status["upstream_exists"] is False
    assert status["runtime_ready"] is False
    assert status["upgrade_required"] is True


def test_runtime_status_rejects_corrupted_wrapper_that_only_keeps_v6_marker(tmp_path):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    env = windows_runtime_env(home, profile, CLAUDE_KEYSMITH_CLAUDE_BIN=upstream)
    install = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)
    assert install.returncode == 0, install.stdout + install.stderr
    wrapper = profile.read_text(encoding="utf-8")
    assert claude_instruct.SHELL_VERSION_MARKER in wrapper
    assert "Start-Sleep -Milliseconds 250" in wrapper
    profile.write_text(
        wrapper.replace("Start-Sleep -Milliseconds 250", "Start-Sleep -Milliseconds 999"),
        encoding="utf-8",
    )

    status = json.loads(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env).stdout
    )["runtime"]

    assert status["shell_wrapper_current"] is False
    assert status["runtime_ready"] is False
    assert status["upgrade_required"] is True


def test_runtime_ready_requires_settings_alignment(tmp_path):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")
    env = windows_runtime_env(home, profile, CLAUDE_KEYSMITH_CLAUDE_BIN=upstream)
    install = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)
    assert install.returncode == 0, install.stdout + install.stderr

    settings_path = home / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["systemPrompt"] = "drifted\n"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    status = json.loads(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env).stdout
    )["runtime"]

    assert status["settings_system_prompt_aligned"] is False
    assert status["runtime_ready"] is False
    assert status["upgrade_required"] is True


def test_powershell_wrapper_is_dynamic_bounded_and_does_not_exit_the_shell(tmp_path):
    home = tmp_path / "home with space's"
    profile = home / "profile.ps1"
    npm_root = home / "AppData" / "Roaming" / "npm"
    package_exe = npm_root / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    shim = npm_root / "claude.ps1"
    package_exe.parent.mkdir(parents=True)
    package_exe.write_bytes(b"fixture")
    shim.write_text("# shim\n", encoding="utf-8")
    env = windows_runtime_env(home, profile)

    result = run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    wrapper = profile.read_text(encoding="utf-8")

    assert str(package_exe).replace("'", "''") in wrapper
    assert str(shim).replace("'", "''") in wrapper
    assert "@args" in wrapper
    assert "$LASTEXITCODE" in wrapper
    assert "250" in wrapper
    assert "10" in wrapper
    assert "throw" in wrapper.lower() or "-ErrorAction Stop" in wrapper
    assert not re.search(r"(?mi)^\s*exit(?:\s|$)", wrapper)


@pytest.mark.skipif(os.name == "nt" or claude_instruct.shutil.which("pwsh") is None, reason="requires Unix pwsh")
@pytest.mark.parametrize("upstream_exit", [17, 130])
def test_powershell_wrapper_waits_for_late_upstream_and_returns_control(tmp_path, upstream_exit):
    profile = tmp_path / "profile's dir" / "profile.ps1"
    upstream = tmp_path / "late upstream" / "claude.exe"
    system_prompt = tmp_path / "prompt's dir" / "system-prompt.md"
    append_prompt = tmp_path / "prompt's dir" / "append-prompt.md"
    arg_log = tmp_path / "args.json"
    return_marker = tmp_path / "returned.txt"
    profile.parent.mkdir(parents=True)
    system_prompt.parent.mkdir(parents=True)
    system_prompt.write_text("system\n", encoding="utf-8")
    append_prompt.write_text("append\n", encoding="utf-8")
    wrapper = claude_instruct.render_shell_wrapper(
        upstream,
        system_prompt,
        append_prompt,
        "powershell",
        [{"kind": "fixture", "path": str(upstream), "exists": False, "eligible": True, "reason": "late"}],
    )
    profile.write_text(wrapper, encoding="utf-8")

    def create_upstream_later():
        time.sleep(0.6)
        upstream.parent.mkdir(parents=True, exist_ok=True)
        upstream.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['KEYSMITH_ARG_LOG']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            f"raise SystemExit({upstream_exit})\n",
            encoding="utf-8",
        )
        upstream.chmod(0o755)

    creator = threading.Thread(target=create_upstream_later)
    creator.start()
    command = "\n".join(
        [
            f". {claude_instruct._powershell_quote(profile)}",
            "$PSNativeCommandUseErrorActionPreference = $true",
            "claude 'space value' '--literal=$dollar' 'semi;colon'",
            "$code = $LASTEXITCODE",
            f"Set-Content -LiteralPath {claude_instruct._powershell_quote(return_marker)} -Value $code",
            f"if ($code -ne {upstream_exit}) {{ throw \"lost exit code: $code\" }}",
        ]
    )
    env = os.environ.copy()
    env["KEYSMITH_ARG_LOG"] = str(arg_log)
    try:
        result = subprocess.run(
            [claude_instruct.shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-Command", command],
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    finally:
        creator.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert return_marker.read_text(encoding="utf-8").strip() == str(upstream_exit)
    forwarded = json.loads(arg_log.read_text(encoding="utf-8"))
    assert forwarded[-3:] == ["space value", "--literal=$dollar", "semi;colon"]
    assert forwarded[:4] == [
        "--system-prompt-file",
        str(system_prompt),
        "--append-system-prompt-file",
        str(append_prompt),
    ]


def test_doctor_never_emits_base_url_tokens_or_cookies(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    sentinel_url = "https://private.example.invalid/BASE_URL_SENTINEL"
    sentinel_token = "TOKEN_SENTINEL_6f9f"
    sentinel_cookie = "COOKIE_SENTINEL_91e2"
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "env": {
                    "ANTHROPIC_BASE_URL": sentinel_url,
                    "ANTHROPIC_AUTH_TOKEN": sentinel_token,
                    "COOKIE": sentinel_cookie,
                },
            }
        ),
        encoding="utf-8",
    )
    profile = home / "profile.ps1"
    env = windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=tmp_path / "missing.exe",
    )

    for args in (["doctor"], ["doctor", "--json"]):
        result = run_cli(args, home=home, extra_env=env, check=False)
        emitted = result.stdout + result.stderr
        assert result.returncode == 0, emitted
        assert sentinel_url not in emitted
        assert sentinel_token not in emitted
        assert sentinel_cookie not in emitted
        assert "ANTHROPIC_BASE_URL" not in emitted
        assert "ANTHROPIC_AUTH_TOKEN" not in emitted
        assert "base_url" not in emitted.lower()
        assert '"cookie"' not in emitted.lower()


def test_doctor_json_only_reports_type_paths_candidates_and_repairs(tmp_path):
    home = tmp_path / "home"
    profile = home / "profile.ps1"
    env = windows_runtime_env(
        home,
        profile,
        CLAUDE_KEYSMITH_CLAUDE_BIN=tmp_path / "missing.exe",
    )

    result = run_cli(["doctor", "--json"], home=home, extra_env=env, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "installation_type",
        "upstream_candidates",
        "upstream_path",
        "system_prompt_file",
        "append_prompt_file",
        "settings_file",
        "shell_kind",
        "shell_rc",
        "repair_actions",
    }
    assert payload["repair_actions"]


def test_backup_file_never_overwrites_same_second_recovery_point(tmp_path):
    source = tmp_path / "settings.json"
    source.write_text("first", encoding="utf-8")

    first = claude_instruct.backup_file(source, timestamp="20260807_120000", suffix="pre_runtime")
    source.write_text("second", encoding="utf-8")
    second = claude_instruct.backup_file(source, timestamp="20260807_120000", suffix="pre_runtime")

    assert first != second
    assert first.read_text(encoding="utf-8") == "first"
    assert second.read_text(encoding="utf-8") == "second"


def test_atomic_write_removes_temporary_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    before = set(tmp_path.iterdir())

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(claude_instruct.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        claude_instruct.atomic_write_text(target, "new content")

    assert not target.exists()
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("failure_stage", ["write", "close"])
def test_atomic_write_removes_temporary_file_when_write_or_close_fails(
    tmp_path, monkeypatch, failure_stage
):
    target = tmp_path / "settings.json"

    class FailingTemporaryFile:
        def __init__(self, *, directory):
            self.path = Path(directory) / f"failing-{failure_stage}.tmp"
            self.name = str(self.path)
            self.file = None

        def __enter__(self):
            self.file = self.path.open("w", encoding="utf-8", newline="\n")
            return self

        def write(self, content):
            self.file.write(content)
            if failure_stage == "write":
                raise OSError("write failed")

        def flush(self):
            self.file.flush()

        def __exit__(self, exc_type, exc, traceback):
            self.file.close()
            if failure_stage == "close" and exc is None:
                raise OSError("close failed")
            return False

    def failing_named_temporary_file(*_args, **kwargs):
        return FailingTemporaryFile(directory=kwargs["dir"])

    monkeypatch.setattr(
        claude_instruct.tempfile,
        "NamedTemporaryFile",
        failing_named_temporary_file,
    )

    with pytest.raises(OSError, match=f"{failure_stage} failed"):
        claude_instruct.atomic_write_text(target, "new content")

    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_concurrent_backups_never_share_or_overwrite_recovery_path(tmp_path):
    source = tmp_path / "settings.json"
    source.write_text("source", encoding="utf-8")
    worker_count = 16
    barrier = threading.Barrier(worker_count)
    backups = []
    errors = []
    result_lock = threading.Lock()

    def create_backup():
        try:
            barrier.wait(timeout=5)
            backup = claude_instruct.backup_file(
                source,
                timestamp="20260807_120000",
                suffix="concurrent",
            )
            with result_lock:
                backups.append(backup)
        except Exception as exc:
            with result_lock:
                errors.append(exc)

    workers = [threading.Thread(target=create_backup) for _ in range(worker_count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert not errors
    assert len(backups) == worker_count
    assert len(set(backups)) == worker_count
    assert all(path.read_text(encoding="utf-8") == "source" for path in backups)


@pytest.mark.skipif(claude_instruct.shutil.which("pwsh") is None, reason="requires pwsh")
def test_powershell_wrapper_all_candidates_missing_throws_and_returns_control(tmp_path, monkeypatch):
    profile = tmp_path / "profile.ps1"
    missing = tmp_path / "missing" / "claude.exe"
    system_prompt = tmp_path / "prompts" / "system-prompt.md"
    append_prompt = tmp_path / "prompts" / "append-prompt.md"
    continued_marker = tmp_path / "continued.txt"
    system_prompt.parent.mkdir(parents=True)
    system_prompt.write_text("system\n", encoding="utf-8")
    append_prompt.write_text("append\n", encoding="utf-8")
    monkeypatch.setattr(claude_instruct, "WINDOWS_UPSTREAM_RETRY_SECONDS", 0.2)
    monkeypatch.setattr(claude_instruct, "WINDOWS_UPSTREAM_RETRY_MILLISECONDS", 25)
    wrapper = claude_instruct.render_shell_wrapper(
        missing,
        system_prompt,
        append_prompt,
        "powershell",
        [{"kind": "missing", "path": str(missing), "exists": False, "eligible": True, "reason": "missing"}],
    )
    assert "AddSeconds(0.2)" in wrapper
    assert "Start-Sleep -Milliseconds 25" in wrapper
    profile.write_text(wrapper, encoding="utf-8")
    command = "\n".join(
        [
            f". {claude_instruct._powershell_quote(profile)}",
            "$caught = $false",
            "try { claude } catch { $caught = $true }",
            "if (-not $caught) { throw 'missing upstream did not throw' }",
            f"Set-Content -LiteralPath {claude_instruct._powershell_quote(continued_marker)} -Value 'continued'",
        ]
    )

    result = subprocess.run(
        [claude_instruct.shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert continued_marker.read_text(encoding="utf-8").strip() == "continued"


@pytest.mark.parametrize(
    "powershell",
    [
        executable
        for executable in (
            claude_instruct.shutil.which("pwsh"),
            claude_instruct.shutil.which("powershell.exe"),
        )
        if executable
    ],
    ids=lambda executable: Path(executable).name,
)
def test_powershell_wrapper_reselects_after_candidate_vanishes_before_start(tmp_path, powershell):
    profile = tmp_path / "profile.ps1"
    vanishing = tmp_path / "vanishing.ps1"
    fallback = tmp_path / "fallback.ps1"
    system_prompt = tmp_path / "prompts" / "system-prompt.md"
    append_prompt = tmp_path / "prompts" / "append-prompt.md"
    fallback_log = tmp_path / "fallback.json"
    vanishing.write_bytes(b"present for Test-Path")
    system_prompt.parent.mkdir(parents=True)
    system_prompt.write_text("system\n", encoding="utf-8")
    append_prompt.write_text("append\n", encoding="utf-8")
    fallback.write_text(
        "$json = ConvertTo-Json -Compress -InputObject @($args)\n"
        "[System.IO.File]::WriteAllText("
        "$env:KEYSMITH_FALLBACK_LOG, $json, [System.Text.UTF8Encoding]::new($false))\n",
        encoding="utf-8",
    )
    profile.write_text(
        claude_instruct.render_shell_wrapper(
            vanishing,
            system_prompt,
            append_prompt,
            "powershell",
            [
                {"kind": "vanishing", "path": str(vanishing), "exists": True, "eligible": True, "reason": "available"},
                {"kind": "fallback", "path": str(fallback), "exists": True, "eligible": True, "reason": "available"},
            ],
        ),
        encoding="utf-8",
    )
    command = "\n".join(
        [
            "$global:KeysmithRemovedCandidate = $false",
            "function global:Test-Path {",
            "  [CmdletBinding()] param([string]$LiteralPath, [string]$PathType)",
            f"  if ($LiteralPath -eq {claude_instruct._powershell_quote(vanishing)} -and -not $global:KeysmithRemovedCandidate) {{",
            "    $global:KeysmithRemovedCandidate = $true",
            "    Microsoft.PowerShell.Management\\Remove-Item -LiteralPath $LiteralPath -Force",
            "    return $true",
            "  }",
            "  return Microsoft.PowerShell.Management\\Test-Path -LiteralPath $LiteralPath -PathType $PathType",
            "}",
            f". {claude_instruct._powershell_quote(profile)}",
            "claude 'forwarded value'",
            "if ($LASTEXITCODE -ne 0) { throw \"fallback failed: $LASTEXITCODE\" }",
        ]
    )
    env = os.environ.copy()
    env["KEYSMITH_FALLBACK_LOG"] = str(fallback_log)

    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", command],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    forwarded = json.loads(fallback_log.read_text(encoding="utf-8"))
    assert forwarded[-1] == "forwarded value"


@pytest.mark.parametrize(
    "powershell",
    [
        executable
        for executable in (
            claude_instruct.shutil.which("pwsh"),
            claude_instruct.shutil.which("powershell.exe"),
        )
        if executable
    ],
    ids=lambda executable: Path(executable).name,
)
@pytest.mark.parametrize(
    ("failure_line", "exception_name"),
    [
        (
            "throw [System.Management.Automation.CommandNotFoundException]::new('fixture command failure')",
            "CommandNotFoundException",
        ),
        (
            "Get-Item -LiteralPath (Join-Path $PSScriptRoot 'missing-internal-item')",
            "ItemNotFoundException",
        ),
        (
            "& { throw [System.Management.Automation.CommandNotFoundException]::new('nested fixture failure') }",
            "CommandNotFoundException",
        ),
    ],
)
def test_powershell_wrapper_does_not_retry_errors_from_started_script(
    tmp_path, monkeypatch, powershell, failure_line, exception_name
):
    profile = tmp_path / "profile.ps1"
    upstream = tmp_path / "upstream.ps1"
    fallback = tmp_path / "fallback.ps1"
    system_prompt = tmp_path / "prompts" / "system-prompt.md"
    append_prompt = tmp_path / "prompts" / "append-prompt.md"
    invocation_count = tmp_path / "invocation-count.txt"
    fallback_marker = tmp_path / "fallback-ran.txt"
    system_prompt.parent.mkdir(parents=True)
    system_prompt.write_text("system\n", encoding="utf-8")
    append_prompt.write_text("append\n", encoding="utf-8")
    upstream.write_text(
        "$count = 0\n"
        "if (Test-Path -LiteralPath $env:KEYSMITH_INVOCATION_COUNT) {\n"
        "  $count = [int](Get-Content -LiteralPath $env:KEYSMITH_INVOCATION_COUNT -Raw)\n"
        "}\n"
        "Set-Content -LiteralPath $env:KEYSMITH_INVOCATION_COUNT -Value ($count + 1)\n"
        f"{failure_line}\n",
        encoding="utf-8",
    )
    fallback.write_text(
        "Set-Content -LiteralPath $env:KEYSMITH_FALLBACK_MARKER -Value 'ran'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(claude_instruct, "WINDOWS_UPSTREAM_RETRY_SECONDS", 0.2)
    monkeypatch.setattr(claude_instruct, "WINDOWS_UPSTREAM_RETRY_MILLISECONDS", 25)
    wrapper = claude_instruct.render_shell_wrapper(
        upstream,
        system_prompt,
        append_prompt,
        "powershell",
        [
            {
                "kind": "script",
                "path": str(upstream),
                "exists": True,
                "eligible": True,
                "reason": "fixture",
            },
            {
                "kind": "fallback",
                "path": str(fallback),
                "exists": True,
                "eligible": True,
                "reason": "must not run",
            },
        ],
    )
    assert "AddSeconds(0.2)" in wrapper
    assert "Start-Sleep -Milliseconds 25" in wrapper
    launch_failure_guard = (
        "$_.InvocationInfo.InvocationName -eq '&' -and "
        "$_.CategoryInfo.TargetName -eq $candidate -and "
        "$_.InvocationInfo.ScriptName -eq $PSCommandPath"
    )
    assert wrapper.count(launch_failure_guard) == 2
    profile.write_text(wrapper, encoding="utf-8")
    command = "\n".join(
        [
            f". {claude_instruct._powershell_quote(profile)}",
            "$caughtType = $null",
            "try { claude } catch { $caughtType = $_.Exception.GetType().Name }",
            f"if ($caughtType -ne '{exception_name}') {{ throw \"unexpected error: $caughtType\" }}",
        ]
    )
    env = os.environ.copy()
    env["KEYSMITH_INVOCATION_COUNT"] = str(invocation_count)
    env["KEYSMITH_FALLBACK_MARKER"] = str(fallback_marker)

    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", command],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert invocation_count.read_text(encoding="utf-8").strip() == "1"
    assert not fallback_marker.exists()
