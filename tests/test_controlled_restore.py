"""Controlled-restore flow: backups enumeration -> restore -> recover marker."""

import json
import os
import subprocess
import sys
from pathlib import Path

import importlib.util

MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-instruct.py"
spec = importlib.util.spec_from_file_location("claude_instruct", MODULE_PATH)
claude_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = claude_instruct
spec.loader.exec_module(claude_instruct)


def run_cli(args, *, home, check=True, extra_env=None):
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
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=check,
    )


def zsh_runtime_env(home):
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "claude").write_text("#!/bin/sh\n", encoding="utf-8")
    return {"CLAUDE_KEYSMITH_SHELL": "zsh"}


def test_controlled_settings_restore_clears_recovery_marker(tmp_path):
    """GUI flow: mark a pending systemPrompt rollback, restore a managed
    settings backup, then recover clears the marker because the restored
    systemPrompt matches system-prompt.md."""
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text('{"model": "opus"}\n', encoding="utf-8")
    env = zsh_runtime_env(home)
    run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env)

    settings_path = home / ".claude" / "settings.json"
    aligned = json.loads(settings_path.read_text(encoding="utf-8"))

    # Reinstall to snapshot the aligned settings into a managed backup.
    run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env)

    # Pick the newest managed settings backup from the enumeration (GUI "controlled restore").
    backups_payload = json.loads(run_cli(["backups", "--scope", "user", "--json"], home=home).stdout)
    settings_backups = [
        entry for entry in backups_payload["backups"] if entry["target_name"] == "settings.json"
    ]
    assert settings_backups, backups_payload
    chosen = settings_backups[-1]
    chosen_content = json.loads(Path(chosen["backup_path"]).read_text(encoding="utf-8"))
    assert chosen_content.get("systemPrompt") == aligned["systemPrompt"]

    # Drift settings and plant the recovery marker.
    drifted = dict(aligned)
    drifted["systemPrompt"] = "drifted\n"
    drifted[claude_instruct.RECOVERY_MARKER_KEY] = True
    settings_path.write_text(json.dumps(drifted), encoding="utf-8")

    # Writes fail closed while the marker is present.
    blocked = run_cli(
        ["install", "--scope", "user", "--name", "other", "--yes", "--json"],
        home=home,
        extra_env=env,
        check=False,
    )
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["ok"] is False

    # Recover refuses to clear the marker while settings drift.
    recover = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home, extra_env=env, check=False)
    assert recover.returncode == 1
    assert json.loads(recover.stdout)["blockers"]

    # Controlled restore of the enumerated backup clears the marker itself.
    restore = run_cli(
        ["restore", "--target", str(settings_path), "--backup", chosen["backup_path"], "--yes", "--json"],
        home=home,
    )
    payload = json.loads(restore.stdout)
    assert payload["ok"] is True
    assert payload["managed"] is True
    restored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert claude_instruct.RECOVERY_MARKER_KEY not in restored
    assert restored["systemPrompt"] == aligned["systemPrompt"]

    # Recover is now a clean no-op and writes work again.
    recover2 = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home, extra_env=env)
    assert json.loads(recover2.stdout)["ok"] is True
    ok = run_cli(["install", "--scope", "user", "--name", "other", "--yes"], home=home, extra_env=env)
    assert "[完成]" in ok.stdout


def test_freeform_restore_stays_available_without_scope(tmp_path):
    """Advanced CLI-only path: arbitrary target/backup pairs outside any scope."""
    home = tmp_path / "home"
    target = tmp_path / "elsewhere" / "notes.txt"
    backup = tmp_path / "elsewhere" / "notes.txt.bak_20260101_000000"
    target.parent.mkdir(parents=True)
    target.write_text("current", encoding="utf-8")
    backup.write_text("restored", encoding="utf-8")

    result = run_cli(
        ["restore", "--target", str(target), "--backup", str(backup), "--yes", "--json"],
        home=home,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["managed"] is True  # still matches the *.bak_* scheme
    assert target.read_text(encoding="utf-8") == "restored"

    # Non-scheme backup names are treated as unmanaged (no journal/lock).
    plain_backup = tmp_path / "elsewhere" / "plain-copy.txt"
    plain_backup.write_text("plain", encoding="utf-8")
    result = run_cli(
        ["restore", "--target", str(target), "--backup", str(plain_backup), "--yes", "--json"],
        home=home,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["managed"] is False
    assert "journal_id" not in payload
    assert target.read_text(encoding="utf-8") == "plain"
