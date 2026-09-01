"""Contract tests for the claude-keysmith/v1 machine-readable JSON output."""

import hashlib
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


def zsh_runtime_env(home):
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "claude").write_text("#!/bin/sh\n", encoding="utf-8")
    return {"CLAUDE_KEYSMITH_SHELL": "zsh"}


def parse_json(result):
    return json.loads(result.stdout)


WRITE_CONTRACT_KEYS = {
    "schema",
    "operation",
    "mode",
    "ok",
    "scope",
    "target",
    "name",
    "actions",
    "warnings",
    "blockers",
    "backups",
    "reload_required",
    "exit_status",
    "error",
}


def assert_write_contract(payload, operation, mode):
    assert payload["schema"] == "claude-keysmith/v1"
    assert payload["operation"] == operation
    assert payload["mode"] == mode
    assert WRITE_CONTRACT_KEYS <= set(payload)
    assert isinstance(payload["ok"], bool)
    assert isinstance(payload["actions"], list)
    assert isinstance(payload["warnings"], list)
    assert isinstance(payload["blockers"], list)
    assert isinstance(payload["backups"], list)
    assert isinstance(payload["reload_required"], bool)
    assert isinstance(payload["exit_status"], int)
    for action in payload["actions"]:
        assert {"action", "path", "detail"} <= set(action)
    for backup in payload["backups"]:
        assert {"target", "backup_path", "sha256", "size_bytes", "created"} <= set(backup)
    if payload["blockers"]:
        assert payload["ok"] is False


# ---------------------------------------------------------------- install --


def test_install_json_preview_shape_and_no_writes(tmp_path):
    home = tmp_path / "home"
    result = run_cli(["install", "--scope", "user", "--name", "rules", "--json"], home=home)

    payload = parse_json(result)
    assert_write_contract(payload, "install", "preview")
    assert payload["ok"] is True
    assert payload["scope"] == "user"
    assert payload["name"] == "rules"
    assert payload["target"]["memory_file"].endswith("CLAUDE.md")
    assert payload["target"]["import_target"] == "@keysmith/rules.md"
    assert payload["source"]["kind"] == "bundled"
    assert payload["source"]["sha256"]
    assert payload["source"]["size_bytes"] > 0
    assert payload["actions"]
    assert "[DRY RUN]" not in result.stdout  # pure JSON on stdout
    assert not (home / ".claude").exists()


def test_install_json_execute_shape_and_backups(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    memory_path = claude_dir / "CLAUDE.md"
    memory_path.write_text("# keep me\n", encoding="utf-8")
    original_bytes = memory_path.read_bytes()

    result = run_cli(["install", "--scope", "user", "--name", "rules", "--yes", "--json"], home=home)

    payload = parse_json(result)
    assert_write_contract(payload, "install", "execute")
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["journal_id"]
    memory_backups = [b for b in payload["backups"] if b["target"].endswith("CLAUDE.md")]
    assert memory_backups, payload["backups"]
    entry = memory_backups[0]
    backup_path = Path(entry["backup_path"])
    assert backup_path.is_file()
    assert backup_path.read_bytes() == original_bytes
    assert entry["sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert entry["size_bytes"] == len(original_bytes)
    assert entry["created"]
    assert (claude_dir / "keysmith" / "rules.md").is_file()


def test_install_json_external_source_kind(tmp_path):
    home = tmp_path / "home"
    external = tmp_path / "custom-rules.md"
    external.write_text("# Custom\n\nbody\n", encoding="utf-8")

    result = run_cli(
        ["install", "--scope", "user", "--name", "rules", "--file", str(external), "--json"],
        home=home,
    )

    payload = parse_json(result)
    assert payload["source"]["kind"] == "external"
    assert payload["source"]["path"] == str(external.resolve())


def test_install_json_error_is_fail_closed(tmp_path):
    home = tmp_path / "home"
    result = run_cli(
        ["install", "--scope", "user", "--name", "../evil", "--yes", "--json"],
        home=home,
        check=False,
    )

    assert result.returncode == 1
    payload = parse_json(result)
    assert payload["schema"] == "claude-keysmith/v1"
    assert payload["ok"] is False
    assert payload["exit_status"] == 1
    assert payload["error"]
    assert payload["blockers"]
    assert not (home / ".claude").exists()


def test_install_json_runtime_includes_runtime_block_and_reload(tmp_path):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)

    preview = run_cli(
        ["install", "--scope", "user", "--runtime", "--json"],
        home=home,
        extra_env=env,
    )
    payload = parse_json(preview)
    assert_write_contract(payload, "install", "preview")
    assert payload["reload_required"] is True
    assert payload["reload_hint"] == "source ~/.zshrc"
    assert "runtime" in payload
    assert payload["runtime"]["supported"] is True
    assert payload["runtime"]["shell_kind"] == "zsh"
    assert payload["sources"]["append"]["kind"] == "bundled"
    assert payload["sources"]["append"]["sha256"]
    planned = [b for b in payload["backups"] if b.get("planned")]
    assert planned == [] or all(b["backup_path"] is None for b in planned)
    assert not (home / ".zshrc").exists()

    execute = run_cli(
        ["install", "--scope", "user", "--runtime", "--yes", "--json"],
        home=home,
        extra_env=env,
    )
    payload = parse_json(execute)
    assert_write_contract(payload, "install", "execute")
    assert payload["ok"] is True
    assert payload["runtime"]["runtime_ready"] is True
    assert payload["reload_required"] is True
    assert (home / ".zshrc").is_file()


# ----------------------------------------------------------------- status --


def test_status_json_keeps_flat_keys_and_adds_structured_blocks(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)

    result = run_cli(["status", "--scope", "user", "--name", "rules", "--json"], home=home)
    payload = parse_json(result)

    for key in (
        "scope",
        "root",
        "memory_file",
        "instruction_file",
        "import_target",
        "memory_file_exists",
        "instruction_file_exists",
        "import_block_exists",
        "installed",
    ):
        assert key in payload
    assert payload["installed"] is True
    assert payload["schema"] == "claude-keysmith/v1"
    assert payload["presence"]["memory_file"] is True
    assert payload["presence"]["instruction_file"] is True
    assert payload["alignment"]["import_block_present"] is True
    assert payload["source_identity"]["instruction_sha256"]
    assert payload["recovery_state"]["recovery_required"] is False
    assert payload["recovery_state"]["journal_count"] == 0


def test_status_json_runtime_readiness_block(tmp_path):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env)

    result = run_cli(
        ["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env
    )
    payload = parse_json(result)

    readiness = payload["runtime_readiness"]
    assert readiness["upstream_exists"] is True
    assert readiness["shell_wrapper_current"] is True
    assert readiness["upgrade_required"] is False
    assert readiness["legacy_launcher_detected"] is False
    assert payload["presence"]["system_prompt"] is True
    assert payload["presence"]["append_prompt"] is True
    assert payload["alignment"]["settings_system_prompt_aligned"] is True
    assert payload["source_identity"]["settings_system_prompt_drift"] is False

    # Drift settings.systemPrompt and confirm it is detected.
    settings_path = home / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["systemPrompt"] = "drifted\n"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    drifted = parse_json(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env)
    )
    assert drifted["source_identity"]["settings_system_prompt_drift"] is True
    assert drifted["alignment"]["settings_system_prompt_aligned"] is False
    assert drifted["runtime_readiness"]["upgrade_required"] is True


# ----------------------------------------------------------------- doctor --


def test_doctor_json_never_leaks_credentials(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    sentinel_url = "https://private.example.invalid/BASE_URL_SENTINEL"
    sentinel_token = "TOKEN_SENTINEL_deadbeef"
    sentinel_cookie = "COOKIE_SENTINEL_cafe"
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
    env = zsh_runtime_env(home)

    result = run_cli(["doctor", "--json"], home=home, extra_env=env)
    emitted = result.stdout + result.stderr
    assert sentinel_url not in emitted
    assert sentinel_token not in emitted
    assert sentinel_cookie not in emitted
    payload = parse_json(result)
    assert payload["repair_actions"]


# -------------------------------------------------------------- uninstall --


def test_uninstall_json_preview_and_execute(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)

    preview = run_cli(["uninstall", "--scope", "user", "--name", "rules", "--json"], home=home)
    payload = parse_json(preview)
    assert_write_contract(payload, "uninstall", "preview")
    assert payload["ok"] is True
    assert any(a["action"] == "remove" for a in payload["actions"])
    assert (home / ".claude" / "keysmith" / "rules.md").is_file()  # untouched

    execute = run_cli(
        ["uninstall", "--scope", "user", "--name", "rules", "--yes", "--json"], home=home
    )
    payload = parse_json(execute)
    assert_write_contract(payload, "uninstall", "execute")
    assert payload["ok"] is True
    assert not (home / ".claude" / "keysmith" / "rules.md").exists()
    assert payload["backups"]


def test_uninstall_json_runtime_reports_reload(tmp_path):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env)

    result = run_cli(
        ["uninstall", "--scope", "user", "--runtime", "--yes", "--json"], home=home, extra_env=env
    )
    payload = parse_json(result)
    assert_write_contract(payload, "uninstall", "execute")
    assert payload["ok"] is True
    assert payload["reload_required"] is True
    assert payload["reload_hint"] == "source ~/.zshrc"
    assert not (home / ".claude" / "keysmith" / "system-prompt.md").exists()
    # settings.systemPrompt intentionally left intact.
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "systemPrompt" in settings


# ---------------------------------------------------------------- restore --


def test_restore_json_preview_and_execute_freeform(tmp_path):
    home = tmp_path / "home"
    target = tmp_path / "CLAUDE.md"
    backup = tmp_path / "CLAUDE.md.bak_20260629_120000"
    target.write_text("current", encoding="utf-8")
    backup.write_text("restored", encoding="utf-8")

    preview = run_cli(
        ["restore", "--target", str(target), "--backup", str(backup), "--json"], home=home
    )
    payload = parse_json(preview)
    assert_write_contract(payload, "restore", "preview")
    assert payload["managed"] is True
    assert payload["source"]["sha256"]
    assert target.read_text(encoding="utf-8") == "current"

    execute = run_cli(
        ["restore", "--target", str(target), "--backup", str(backup), "--yes", "--json"],
        home=home,
    )
    payload = parse_json(execute)
    assert_write_contract(payload, "restore", "execute")
    assert payload["ok"] is True
    assert target.read_text(encoding="utf-8") == "restored"


def test_restore_json_rejects_missing_backup_fail_closed(tmp_path):
    home = tmp_path / "home"
    result = run_cli(
        ["restore", "--target", str(tmp_path / "x.md"), "--backup", str(tmp_path / "missing.bak_20260101_000000"), "--yes", "--json"],
        home=home,
        check=False,
    )
    assert result.returncode == 1
    payload = parse_json(result)
    assert payload["ok"] is False
    assert payload["exit_status"] == 1
    assert payload["error"]


# ---------------------------------------------------------------- backups --


def test_backups_json_enumerates_only_keysmith_scheme(tmp_path):
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.md").write_text("v1\n", encoding="utf-8")
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    # A foreign file that must NOT be enumerated.
    (claude_dir / "CLAUDE.md.bak").write_text("foreign", encoding="utf-8")
    (claude_dir / "random.txt").write_text("foreign", encoding="utf-8")

    result = run_cli(["backups", "--scope", "user", "--json"], home=home)
    payload = parse_json(result)

    assert payload["schema"] == "claude-keysmith/v1"
    assert payload["operation"] == "backups"
    assert payload["ok"] is True
    assert payload["count"] == len(payload["backups"])
    assert payload["count"] >= 1
    for entry in payload["backups"]:
        assert {"backup_path", "target_name", "target_path", "sha256", "size_bytes", "created", "kind"} <= set(entry)
        assert ".bak_2" in Path(entry["backup_path"]).name
        assert Path(entry["backup_path"]).is_file()
        assert Path(entry["target_path"]) == Path(entry["backup_path"]).parent / entry["target_name"]
    names = [Path(e["backup_path"]).name for e in payload["backups"]]
    assert "CLAUDE.md.bak" not in names
    assert "random.txt" not in names
    assert any(name.startswith("CLAUDE.md.bak_") for name in names)


def test_backups_json_never_leaks_backup_contents_or_credentials(tmp_path):
    home = tmp_path / "home"
    keysmith_dir = home / ".claude" / "keysmith"
    keysmith_dir.mkdir(parents=True)
    sentinel = "TOKEN_SENTINEL_backup_content_deadbeef"
    backup = keysmith_dir / "rules.md.bak_20260814_120000"
    backup.write_text(sentinel + "\n", encoding="utf-8")

    result = run_cli(["backups", "--scope", "user", "--json"], home=home)
    payload = parse_json(result)

    assert payload["ok"] is True
    assert sentinel not in result.stdout
    assert payload["backups"]
    assert all("content" not in entry for entry in payload["backups"])
    assert any(entry["backup_path"] == str(backup) for entry in payload["backups"])


def test_backups_project_scope_filter(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()
    (project / "CLAUDE.md").write_text("# P\n", encoding="utf-8")
    run_cli(
        ["install", "--scope", "project", "--project-dir", str(project), "--name", "rules", "--yes"],
        home=home,
    )

    payload = parse_json(
        run_cli(["backups", "--scope", "project", "--project-dir", str(project), "--json"], home=home)
    )
    assert payload["scope"] == "project"
    assert payload["count"] >= 1
    assert all(str(project) in entry["backup_path"] for entry in payload["backups"])


def test_scoped_restore_rejects_target_not_enumerated_by_backups(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    backups = parse_json(run_cli(["backups", "--scope", "user", "--json"], home=home))["backups"]
    chosen = next(entry for entry in backups if entry["target_name"] == "rules.md")
    wrong_target = tmp_path / "outside.md"

    result = run_cli(
        [
            "restore",
            "--target",
            str(wrong_target),
            "--backup",
            chosen["backup_path"],
            "--scope",
            "user",
            "--yes",
            "--json",
        ],
        home=home,
        check=False,
    )
    payload = parse_json(result)

    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["managed"] is False
    assert "backups --json" in payload["error"]
    assert not wrong_target.exists()


def test_scoped_restore_uses_enumerated_absolute_pair_and_preview_is_read_only(tmp_path):
    home = tmp_path / "home"
    source_v1 = tmp_path / "rules-v1.md"
    source_v2 = tmp_path / "rules-v2.md"
    source_v1.write_text("rules v1\n", encoding="utf-8")
    source_v2.write_text("rules v2\n", encoding="utf-8")
    run_cli(
        ["install", "--scope", "user", "--name", "rules", "--file", str(source_v1), "--yes"],
        home=home,
    )
    run_cli(
        ["install", "--scope", "user", "--name", "rules", "--file", str(source_v2), "--yes"],
        home=home,
    )

    backups = parse_json(run_cli(["backups", "--scope", "user", "--json"], home=home))["backups"]
    chosen = next(entry for entry in backups if entry["target_name"] == "rules.md")
    target = Path(chosen["target_path"])
    backup = Path(chosen["backup_path"])
    assert target.is_absolute()
    assert target.read_text(encoding="utf-8") == "rules v2\n"
    before_preview = (target.read_bytes(), target.stat().st_mode, target.stat().st_mtime_ns)

    preview = run_cli(
        [
            "restore",
            "--target",
            str(target),
            "--backup",
            str(backup),
            "--scope",
            "user",
            "--json",
        ],
        home=home,
    )
    preview_payload = parse_json(preview)
    assert preview_payload["ok"] is True
    assert preview_payload["mode"] == "preview"
    assert preview_payload["managed"] is True
    assert (target.read_bytes(), target.stat().st_mode, target.stat().st_mtime_ns) == before_preview

    execute = run_cli(
        [
            "restore",
            "--target",
            str(target),
            "--backup",
            str(backup),
            "--scope",
            "user",
            "--yes",
            "--json",
        ],
        home=home,
    )
    execute_payload = parse_json(execute)
    assert execute_payload["ok"] is True
    assert execute_payload["mode"] == "execute"
    assert execute_payload["managed"] is True
    assert target.read_bytes() == backup.read_bytes()


def test_backups_text_output_still_works(tmp_path):
    home = tmp_path / "home"
    run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    result = run_cli(["backups", "--scope", "user"], home=home)
    assert "managed backups:" in result.stdout


# ---------------------------------------------------------------- recover --


def test_recover_json_clean_scope_is_noop(tmp_path):
    home = tmp_path / "home"
    result = run_cli(["recover", "--scope", "user", "--json"], home=home)
    payload = parse_json(result)
    assert payload["schema"] == "claude-keysmith/v1"
    assert payload["operation"] == "recover"
    assert payload["ok"] is True
    assert payload["residue"] == []
    assert payload["exit_status"] == 0
