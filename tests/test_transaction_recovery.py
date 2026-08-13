"""Tests for the durable journal, scope-local write lock, and fail-closed recovery."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import importlib.util
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


def make_args(command, scope="user", yes=False, json_mode=False, name="rules", project_dir=None):
    parser = claude_instruct.build_parser()
    argv = [command, "--scope", scope, "--name", name]
    if command in {"backups", "recover"}:
        argv = [command, "--scope", scope]
    if project_dir:
        argv += ["--project-dir", str(project_dir)]
    if yes:
        argv.append("--yes")
    if json_mode:
        argv.append("--json")
    return parser.parse_args(argv)


def forge_pending_journal(home, scope="user", operation="install", monkeypatch=None, tamper=None):
    """Create a realistic pending journal as if a write died mid-transaction."""
    paths = claude_instruct.resolve_scope(scope)
    journal = claude_instruct.TransactionJournal(paths, operation)
    instruction = paths.instruction_file("rules.md")
    if not instruction.exists():
        claude_instruct.atomic_write_text(instruction, "partial write\n")
        if tamper != "missing_write_after":
            # record the write as fully applied
            journal.log_step(
                {
                    "action": "write",
                    "path": str(instruction),
                    "before": {"sha256": None, "size_bytes": None, "exists": False},
                    "after": claude_instruct.file_evidence(instruction),
                }
            )
        else:
            journal.log_step(
                {
                    "action": "write",
                    "path": str(instruction),
                    "before": {"sha256": None, "size_bytes": None, "exists": False},
                    "after": claude_instruct.file_evidence(instruction),
                }
            )
    return journal


# --------------------------------------------------------------- lock ------


def test_lock_blocks_second_live_writer(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")

    first = claude_instruct.ScopeWriteLock(paths, label="first")
    first.acquire()
    try:
        with pytest.raises(claude_instruct.TransactionConflict):
            claude_instruct.ScopeWriteLock(paths, label="second").acquire()
    finally:
        first.release()
    # After release, acquisition works again.
    third = claude_instruct.ScopeWriteLock(paths, label="third")
    third.acquire()
    third.release()


def test_stale_lock_from_dead_pid_is_reclaimed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    lock_path = claude_instruct.scope_lock_path(paths)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"pid": 999999, "label": "dead", "acquired_at": "x"}), encoding="utf-8")

    lock = claude_instruct.ScopeWriteLock(paths, label="reclaimer")
    lock.acquire()
    assert lock.reclaimed_stale is True
    lock.release()
    assert not lock_path.exists()


def test_lock_holder_survives_and_blocks_while_alive(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    lock_path = claude_instruct.scope_lock_path(paths)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"pid": os.getpid(), "label": "self"}), encoding="utf-8")

    with pytest.raises(claude_instruct.TransactionConflict):
        claude_instruct.ScopeWriteLock(paths, label="other").acquire()
    assert lock_path.exists()


def test_concurrent_installs_one_fails_closed(tmp_path, monkeypatch):
    """Two writers racing on one scope: exactly one wins, loser fails closed."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.md").write_text("# base\n", encoding="utf-8")

    # Force a deterministic overlap: the first writer to take the lock holds it
    # while the second attempts acquisition and must fail closed.
    holder = claude_instruct.ScopeWriteLock(claude_instruct.resolve_scope("user"), label="holder")
    holder.acquire()
    started = threading.Event()
    done = threading.Event()
    outcome = {}

    def contender():
        started.set()
        args = claude_instruct.build_parser().parse_args(
            ["install", "--scope", "user", "--name", "contender", "--yes", "--json"]
        )
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            outcome["code"] = claude_instruct.command_install(args)
        outcome["stdout"] = buffer.getvalue()
        done.set()

    thread = threading.Thread(target=contender)
    thread.start()
    started.wait(timeout=10)
    done.wait(timeout=10)
    assert done.is_set(), "contender was not blocked-or-failed promptly"
    holder.release()
    thread.join(timeout=10)

    assert outcome["code"] == 1
    payload = json.loads(outcome["stdout"])
    assert payload["ok"] is False
    assert payload["exit_status"] == 1
    assert "keysmith" in payload["error"]

    # After the holder releases, a fresh install succeeds and leaves no residue.
    args = claude_instruct.build_parser().parse_args(
        ["install", "--scope", "user", "--name", "contender", "--yes"]
    )
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = claude_instruct.command_install(args)
    assert code == 0, buffer.getvalue()
    keysmith_dir = home / ".claude" / "keysmith"
    assert not list(keysmith_dir.glob(".journal-*.json"))
    assert not (keysmith_dir / ".keysmith.lock").exists()


# ------------------------------------------------------- pending rollback --


def test_recover_rolls_back_pending_journal_preview_then_execute(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    journal = forge_pending_journal(home)
    journal_path = journal.path
    instruction = home / ".claude" / "keysmith" / "rules.md"
    assert instruction.exists()

    # Writes are blocked while residue exists.
    blocked = run_cli(["install", "--scope", "user", "--name", "other", "--yes", "--json"], home=home, check=False)
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["ok"] is False

    # Preview reports residue but changes nothing.
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home)
    payload = json.loads(preview.stdout)
    assert payload["mode"] == "preview"
    assert payload["residue"]
    assert payload["planned_repairs"]
    assert instruction.exists()
    assert journal_path.exists()

    # Execute rolls back the file created by the interrupted transaction.
    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    payload = json.loads(execute.stdout)
    assert payload["ok"] is True
    assert payload["exit_status"] == 0
    assert not instruction.exists()
    assert not journal_path.exists()

    # Idempotent: a second recover is a clean no-op.
    again = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    payload = json.loads(again.stdout)
    assert payload["ok"] is True
    assert payload["residue"] == []

    # Writes work again.
    ok = run_cli(["install", "--scope", "user", "--name", "other", "--yes"], home=home)
    assert "[完成]" in ok.stdout


def test_recover_pending_remove_step_restores_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    keysmith_dir = paths.keysmith_dir
    keysmith_dir.mkdir(parents=True)
    instruction = keysmith_dir / "rules.md"
    instruction.write_text("original content\n", encoding="utf-8")
    backup = claude_instruct.backup_file(instruction, "20260813_120000")
    before = claude_instruct.file_evidence(instruction)
    instruction.unlink()

    journal = claude_instruct.TransactionJournal(paths, "uninstall")
    journal.log_step(
        {
            "action": "remove",
            "path": str(instruction),
            "before": before,
            "after": {"sha256": None, "size_bytes": None, "exists": False},
            "backup_path": str(backup),
        }
    )

    result = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert instruction.read_text(encoding="utf-8") == "original content\n"
    assert not journal.path.exists()


def test_recover_pending_write_restores_prior_content(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("before\n", encoding="utf-8")
    backup = claude_instruct.backup_file(memory, "20260813_120000")
    before = claude_instruct.file_evidence(memory)
    memory.write_text("after interrupted write\n", encoding="utf-8")
    after = claude_instruct.file_evidence(memory)

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step(
        {
            "action": "write",
            "path": str(memory),
            "before": before,
            "after": after,
            "backup_path": str(backup),
        }
    )

    result = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert memory.read_text(encoding="utf-8") == "before\n"


# --------------------------------------------------------- fail closed -----


def test_recover_fail_closed_on_unknown_modification(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("before\n", encoding="utf-8")
    before = claude_instruct.file_evidence(memory)
    memory.write_text("interrupted\n", encoding="utf-8")
    after = claude_instruct.file_evidence(memory)
    memory.write_text("third-party edit\n", encoding="utf-8")  # unknown modification

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step({"action": "write", "path": str(memory), "before": before, "after": after})

    preview = run_cli(["recover", "--scope", "user", "--json"], home=home)
    assert json.loads(preview.stdout)["residue"]

    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home, check=False)
    payload = json.loads(execute.stdout)
    assert execute.returncode == 1
    assert payload["ok"] is False
    assert payload["blockers"]
    # User file + evidence preserved.
    assert memory.read_text(encoding="utf-8") == "third-party edit\n"
    assert journal.path.exists()


def test_recover_fail_closed_on_path_rebinding(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("before\n", encoding="utf-8")
    before = claude_instruct.file_evidence(memory)
    memory.unlink()
    memory.symlink_to(tmp_path / "elsewhere")  # rebound: no longer a regular file

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step(
        {
            "action": "write",
            "path": str(memory),
            "before": before,
            "after": claude_instruct.file_evidence(memory),
        }
    )

    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home, check=False)
    payload = json.loads(execute.stdout)
    assert execute.returncode == 1
    assert payload["ok"] is False
    assert payload["blockers"]
    assert memory.is_symlink()  # untouched
    assert journal.path.exists()


def test_corrupt_journal_blocks_writes_and_is_reported(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    paths.keysmith_dir.mkdir(parents=True)
    corrupt = paths.keysmith_dir / ".journal-broken.json"
    corrupt.write_text("{not json", encoding="utf-8")

    blocked = run_cli(["install", "--scope", "user", "--name", "rules", "--yes", "--json"], home=home, check=False)
    assert blocked.returncode == 1

    preview = run_cli(["recover", "--scope", "user", "--json"], home=home, check=False)
    payload = json.loads(preview.stdout)
    assert payload["blockers"]
    assert preview.returncode == 1
    assert corrupt.exists()  # evidence preserved


# ------------------------------------------------------- post-commit -------


def test_committed_journal_is_never_reversed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("before\n", encoding="utf-8")
    before = claude_instruct.file_evidence(memory)
    memory.write_text("committed new state\n", encoding="utf-8")
    after = claude_instruct.file_evidence(memory)

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step({"action": "write", "path": str(memory), "before": before, "after": after})
    journal.commit()

    result = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    # The committed result is NOT reversed.
    assert memory.read_text(encoding="utf-8") == "committed new state\n"
    assert not journal.path.exists()


def test_crash_after_commit_window_is_consumed_by_next_write(tmp_path, monkeypatch):
    """A committed journal with a dead holder (crash before cleanup) must not
    permanently block the next write; the write consumes it after verifying the
    residual cleanup is a no-op."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("committed\n", encoding="utf-8")

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.record["pid"] = 999999  # simulate a dead writer
    journal.commit()

    result = run_cli(["install", "--scope", "user", "--name", "rules", "--yes"], home=home)
    assert "[完成]" in result.stdout
    assert not journal.path.exists()


# --------------------------------------------------- mid-transaction crash --


def test_install_failure_rolls_back_and_recovers_clean(tmp_path, monkeypatch):
    """Force a mid-transaction failure; the pending journal rollback restores
    the exact prior state and no residue remains."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    memory = claude_dir / "CLAUDE.md"
    memory.write_text("original memory\n", encoding="utf-8")
    keysmith_dir = claude_dir / "keysmith"
    keysmith_dir.mkdir()
    instruction = keysmith_dir / "rules.md"
    instruction.write_text("old rules\n", encoding="utf-8")

    original_atomic_write = claude_instruct.atomic_write_text
    state = {"memory_write_seen": False}

    def fail_on_memory_write(path, content):
        if Path(path) == memory and state["memory_write_seen"] is False:
            state["memory_write_seen"] = True
            raise OSError("simulated crash during memory write")
        return original_atomic_write(path, content)

    monkeypatch.setattr(claude_instruct, "atomic_write_text", fail_on_memory_write)
    args = claude_instruct.build_parser().parse_args(
        ["install", "--scope", "user", "--name", "rules", "--yes", "--json"]
    )
    return_code = claude_instruct.command_install(args)
    assert return_code == 1

    # Fully rolled back: exact prior bytes, no journal, no lock.
    assert memory.read_text(encoding="utf-8") == "original memory\n"
    assert instruction.read_text(encoding="utf-8") == "old rules\n"
    assert not list(keysmith_dir.glob(".journal-*.json"))
    assert not (keysmith_dir / ".keysmith.lock").exists()

    # Backups of the pre-transaction state were kept as evidence.
    assert list(claude_dir.glob("CLAUDE.md.bak_*"))
    assert list(keysmith_dir.glob("rules.md.bak_*"))


def test_project_scope_journal_and_lock_locations(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "repo"
    project.mkdir()

    result = run_cli(
        ["install", "--scope", "project", "--project-dir", str(project), "--name", "rules", "--yes"],
        home=home,
    )
    assert "[完成]" in result.stdout
    keysmith_dir = project / ".claude" / "keysmith"
    # Journal + lock cleaned after success.
    assert not list(keysmith_dir.glob(".journal-*.json"))
    assert not (keysmith_dir / ".keysmith.lock").exists()
    # Recover on the project scope is a clean no-op.
    payload = json.loads(
        run_cli(["recover", "--scope", "project", "--project-dir", str(project), "--json"], home=home).stdout
    )
    assert payload["ok"] is True
    assert payload["residue"] == []
