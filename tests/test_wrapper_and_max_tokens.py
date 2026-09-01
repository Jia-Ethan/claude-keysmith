"""Regression tests: unix stable-launcher wrapper + --max-tokens validation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import importlib.util
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "claude-instruct.py"
spec = importlib.util.spec_from_file_location("claude_instruct", MODULE_PATH)
claude_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = claude_instruct
spec.loader.exec_module(claude_instruct)

ZSH = claude_instruct.shutil.which("zsh")


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


# ---------------------------------------------------- zsh wrapper template --


def test_zsh_wrapper_re_resolves_entry_point_dynamically(tmp_path):
    """The v7 zsh wrapper must not be a single baked absolute path invocation."""
    block = claude_instruct.render_shell_wrapper(
        tmp_path / "versions" / "1.0" / "claude",
        tmp_path / "system-prompt.md",
        tmp_path / "append-prompt.md",
    )
    assert "command -v claude" in block
    assert "command -v -p claude" in block
    assert "return 127" in block
    assert "--system-prompt-file" in block
    assert "--append-system-prompt-file" in block
    assert claude_instruct.SHELL_VERSION_MARKER in block


@pytest.mark.skipif(ZSH is None or os.name == "nt", reason="requires zsh on unix")
def test_zsh_wrapper_survives_claude_version_switch(tmp_path):
    """Simulate a Claude update: the baked v1 path disappears, v2 appears on
    PATH. The wrapper must still resolve and forward to the new entry point."""
    home = tmp_path / "home"
    versions = home / "claude-versions"
    v1 = versions / "1.0.0" / "claude"
    v2_dir = versions / "2.0.0"
    v2 = v2_dir / "claude"
    v1.parent.mkdir(parents=True)
    v2_dir.mkdir(parents=True)
    v1.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    v1.chmod(0o755)
    arg_log = tmp_path / "args.log"
    v2.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {arg_log}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    v2.chmod(0o755)

    system_prompt = home / ".claude" / "keysmith" / "system-prompt.md"
    append_prompt = home / ".claude" / "keysmith" / "append-prompt.md"
    system_prompt.parent.mkdir(parents=True)
    system_prompt.write_text("system\n", encoding="utf-8")
    append_prompt.write_text("append\n", encoding="utf-8")

    # Wrapper was rendered while v1 was the resolved claude binary.
    block = claude_instruct.render_shell_wrapper(v1, system_prompt, append_prompt, "zsh")
    zshrc = home / ".zshrc"
    zshrc.write_text(block, encoding="utf-8")

    # Claude updates: v1 disappears, v2 is now what PATH resolves.
    v1.unlink()
    script = "\n".join(
        [
            f'source "{zshrc}"',
            "claude --version-check extra-arg",
            'echo "wrapper-exit=$?"',
        ]
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{v2_dir}:/usr/bin:/bin"

    result = subprocess.run(
        [ZSH, "-f", "-c", script],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "wrapper-exit=0" in result.stdout
    forwarded = arg_log.read_text(encoding="utf-8").splitlines()
    assert forwarded[-2:] == ["--version-check", "extra-arg"]
    assert forwarded[:4] == [
        "--system-prompt-file",
        str(system_prompt),
        "--append-system-prompt-file",
        str(append_prompt),
    ]


@pytest.mark.skipif(ZSH is None or os.name == "nt", reason="requires zsh on unix")
def test_zsh_wrapper_reports_clean_error_when_no_entry_point(tmp_path):
    home = tmp_path / "home"
    missing = home / "gone" / "claude"
    system_prompt = home / ".claude" / "keysmith" / "system-prompt.md"
    append_prompt = home / ".claude" / "keysmith" / "append-prompt.md"
    system_prompt.parent.mkdir(parents=True)
    system_prompt.write_text("system\n", encoding="utf-8")
    append_prompt.write_text("append\n", encoding="utf-8")
    zshrc = home / ".zshrc"
    zshrc.write_text(
        claude_instruct.render_shell_wrapper(missing, system_prompt, append_prompt, "zsh"),
        encoding="utf-8",
    )
    script = "\n".join(
        [
            f'source "{zshrc}"',
            "claude",
            'echo "wrapper-exit=$?"',
        ]
    )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "/usr/bin:/bin"

    result = subprocess.run([ZSH, "-f", "-c", script], env=env, text=True, capture_output=True, timeout=15)
    assert "claude-keysmith: Claude Code entry point is unavailable" in result.stderr
    assert "wrapper-exit=127" in result.stdout


def test_shell_wrapper_current_detects_v7_upgrade(tmp_path):
    """An old baked-path v6-style block must be flagged as not current."""
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env)

    status = json.loads(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env).stdout
    )
    assert status["runtime"]["shell_wrapper_current"] is True
    assert status["runtime"]["upgrade_required"] is False

    # Simulate a stale v6 baked-path wrapper.
    zshrc = home / ".zshrc"
    claude_bin = home / ".local" / "bin" / "claude"
    stale = "\n".join(
        [
            claude_instruct.SHELL_BEGIN,
            "# claude-keysmith wrapper version: v6",
            "# Managed by claude-keysmith. Do not edit by hand.",
            "claude() {",
            f'  "{claude_bin}" \\',
            f'    --system-prompt-file "{home / ".claude" / "keysmith" / "system-prompt.md"}" \\',
            f'    --append-system-prompt-file "{home / ".claude" / "keysmith" / "append-prompt.md"}" \\',
            '    "$@"',
            "}",
            claude_instruct.SHELL_END,
            "",
        ]
    )
    zshrc.write_text(stale, encoding="utf-8")

    drifted = json.loads(
        run_cli(["status", "--scope", "user", "--runtime", "--json"], home=home, extra_env=env).stdout
    )
    assert drifted["runtime"]["shell_wrapper_current"] is False
    assert drifted["runtime"]["upgrade_required"] is True

    # Reinstall upgrades the wrapper in place.
    run_cli(["install", "--scope", "user", "--runtime", "--yes"], home=home, extra_env=env)
    upgraded = zshrc.read_text(encoding="utf-8")
    assert "command -v claude" in upgraded
    assert claude_instruct.SHELL_VERSION_MARKER in upgraded


# ------------------------------------------------------------- max-tokens --


def test_max_tokens_accepts_positive_integer(tmp_path):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--max-tokens", "64000", "--yes"],
        home=home,
        extra_env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["max_tokens"] == 64000


@pytest.mark.parametrize("value", ["0", "-5"])
def test_max_tokens_rejects_zero_and_negative(tmp_path, value):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--max-tokens", value, "--yes"],
        home=home,
        extra_env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "max-tokens" in result.stderr or "max-tokens" in result.stdout
    assert not (home / ".claude").exists()


def test_max_tokens_rejects_non_numeric(tmp_path):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--max-tokens", "abc", "--yes"],
        home=home,
        extra_env=env,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "usage:" in result.stderr
    assert "max-tokens" in result.stderr
    assert not (home / ".claude").exists()


@pytest.mark.parametrize("value", ["0", "-5", "abc"])
def test_max_tokens_json_error_is_fail_closed(tmp_path, value):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    result = run_cli(
        ["install", "--scope", "user", "--runtime", "--max-tokens", value, "--yes", "--json"],
        home=home,
        extra_env=env,
        check=False,
    )
    assert result.returncode != 0
    assert not (home / ".claude").exists()
    # --json callers must still receive a contract document on stdout, not bare
    # argparse usage text (the GUI would otherwise report "no stable JSON").
    payload = json.loads(result.stdout)
    assert payload["schema"] == "claude-keysmith/v1"
    assert payload["operation"] == "install"
    assert payload["mode"] == "execute"
    assert payload["ok"] is False
    assert payload["exit_status"] == 2
    assert "max-tokens" in payload["error"]
    assert payload["blockers"] == [payload["error"]]
    assert payload["actions"] == []
    # Human-readable usage stays on stderr.
    assert "max-tokens" in result.stderr


@pytest.mark.parametrize(
    ("mode_flags", "expected_mode"),
    [
        ([], "preview"),
        (["--yes"], "execute"),
        (["--yes", "--dry-run"], "preview"),
    ],
)
def test_json_usage_error_mode_comes_from_raw_argv(tmp_path, mode_flags, expected_mode):
    home = tmp_path / "home"
    env = zsh_runtime_env(home)
    result = run_cli(
        [
            "install",
            "--scope",
            "user",
            "--runtime",
            "--max-tokens",
            "0",
            *mode_flags,
            "--json",
        ],
        home=home,
        extra_env=env,
        check=False,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["mode"] == expected_mode
    assert payload["ok"] is False
    assert payload["exit_status"] == 2
    assert "usage:" in result.stderr
    assert not (home / ".claude").exists()
