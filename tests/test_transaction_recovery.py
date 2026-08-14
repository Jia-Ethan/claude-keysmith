"""Tests for the durable journal, scope-local write lock, and fail-closed recovery."""

import json
import os
import subprocess
import sys
import threading
import time
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
    # macOS framework Python can put bytecode caches under HOME; keep the
    # interpreter's own files outside the tree whose read-only semantics we test.
    env["PYTHONPYCACHEPREFIX"] = str(home.parent / ".python-cache")
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


def snapshot_tree(root):
    """Capture file contents and write-relevant metadata for preview checks."""
    if not root.exists():
        return {}
    snapshot = {}
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else str(path.relative_to(root))
        stat = path.lstat()
        if path.is_symlink():
            value = ("symlink", os.readlink(path))
        elif path.is_file():
            value = ("file", path.read_bytes())
        else:
            value = ("dir", None)
        snapshot[relative] = (value, stat.st_mode, stat.st_mtime_ns)
    return snapshot


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


def test_transaction_helpers_persist_after_evidence_and_reject_later_edit(tmp_path, monkeypatch):
    """Production tx helpers must persist after-state evidence, not only the
    in-memory step object, so recovery can distinguish our write from a later
    third-party edit and fail closed instead of overwriting it."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("before\n", encoding="utf-8")

    journal = claude_instruct.TransactionJournal(paths, "install")
    backup = claude_instruct.tx_backup_step(journal, memory, "20260814_120000")
    claude_instruct.tx_write_step(journal, memory, "transaction write\n")

    persisted = claude_instruct.load_journal(journal.path)
    assert persisted is not None
    backup_step, write_step = [
        step for step in persisted["steps"] if step["action"] in {"backup", "write"}
    ]
    assert backup_step["after"]["exists"] is True
    assert backup_step["backup_path"] == str(backup)
    assert write_step["after"] == claude_instruct.file_evidence(memory)

    memory.write_text("third-party edit\n", encoding="utf-8")
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home, check=False)
    payload = json.loads(preview.stdout)
    assert preview.returncode == 1
    assert payload["ok"] is False
    assert any("未知修改" in blocker for blocker in payload["blockers"])
    assert memory.read_text(encoding="utf-8") == "third-party edit\n"
    assert journal.path.exists()


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

    # Preview must reach the same verdict as execute (no "preview says OK,
    # execute then fails" gap for the GUI confirm step).
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home, check=False)
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["residue"]
    assert preview.returncode == 1
    assert preview_payload["ok"] is False
    assert preview_payload["blockers"]
    assert preview_payload["exit_status"] == 1

    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home, check=False)
    payload = json.loads(execute.stdout)
    assert execute.returncode == 1
    assert payload["ok"] is False
    assert payload["blockers"]
    # Preview and execute agree on the reason.
    assert preview_payload["blockers"] == payload["blockers"]
    # User file + evidence preserved.
    assert memory.read_text(encoding="utf-8") == "third-party edit\n"
    assert journal.path.exists()


def test_pending_rollback_fails_closed_when_presence_check_errors(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("interrupted\n", encoding="utf-8")
    record = {
        "steps": [
            {
                "action": "write",
                "path": str(memory),
                "before": {"sha256": None, "size_bytes": None, "exists": False},
                "after": claude_instruct.file_evidence(memory),
            }
        ]
    }

    original_lexists = os.path.lexists

    def fail_target_presence(path):
        if Path(path) == memory:
            raise PermissionError("simulated lstat denial")
        return original_lexists(path)

    monkeypatch.setattr(os.path, "lexists", fail_target_presence)

    _planned, plan_blockers = claude_instruct.plan_pending_rollback(record)
    _actions, execute_blockers = claude_instruct.rollback_pending_journal(record)

    assert any("无法检查回滚目标状态" in item for item in plan_blockers)
    assert execute_blockers == plan_blockers
    assert memory.read_text(encoding="utf-8") == "interrupted\n"


def test_recover_preview_plans_recoverable_rollback(tmp_path, monkeypatch):
    """A recoverable pending journal previews concrete steps and stays ok."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    absent_before = {"sha256": None, "size_bytes": None, "exists": False}
    memory.write_text("created by interrupted transaction\n", encoding="utf-8")
    after = claude_instruct.file_evidence(memory)

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step({"action": "write", "path": str(memory), "before": absent_before, "after": after})

    preview_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--json"], home=home).stdout
    )
    assert preview_payload["ok"] is True
    assert preview_payload["blockers"] == []
    planned = [item["action"] for item in preview_payload["planned_repairs"]]
    assert "rollback-pending" in planned
    assert "remove" in planned  # concrete step surfaced before confirmation
    # Preview must not touch the filesystem.
    assert memory.exists()
    assert journal.path.exists()

    execute_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home).stdout
    )
    assert execute_payload["ok"] is True
    assert not memory.exists()  # rolled back exactly as planned
    assert not journal.path.exists()


def test_recover_repeated_writes_use_virtual_reverse_state(tmp_path, monkeypatch):
    """Preview and execute both unwind multiple writes to one path in reverse."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    memory = paths.memory_file
    memory.parent.mkdir(parents=True)
    memory.write_text("state-a\n", encoding="utf-8")
    before_a = claude_instruct.file_evidence(memory)
    backup_a = claude_instruct.backup_file(memory, "20260814_120000", suffix="state_a")

    journal = claude_instruct.TransactionJournal(paths, "restore")
    memory.write_text("state-b\n", encoding="utf-8")
    state_b = claude_instruct.file_evidence(memory)
    journal.log_step(
        {
            "action": "write",
            "path": str(memory),
            "before": before_a,
            "after": state_b,
            "backup_path": str(backup_a),
        }
    )
    backup_b = claude_instruct.backup_file(memory, "20260814_120001", suffix="state_b")
    memory.write_text("state-c\n", encoding="utf-8")
    state_c = claude_instruct.file_evidence(memory)
    journal.log_step(
        {
            "action": "write",
            "path": str(memory),
            "before": state_b,
            "after": state_c,
            "backup_path": str(backup_b),
        }
    )

    before_preview = snapshot_tree(home)
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home)
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["ok"] is True
    assert preview_payload["blockers"] == []
    assert [item["action"] for item in preview_payload["planned_repairs"]].count("restore") == 2
    assert snapshot_tree(home) == before_preview

    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    execute_payload = json.loads(execute.stdout)
    assert execute_payload["ok"] is True
    assert execute_payload["blockers"] == []
    assert memory.read_text(encoding="utf-8") == "state-a\n"
    assert not journal.path.exists()


def test_recover_marker_mismatch_blocks_preview_and_execute_equally(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    keysmith_dir = home / ".claude" / "keysmith"
    keysmith_dir.mkdir(parents=True)
    (keysmith_dir / "system-prompt.md").write_text("expected\n", encoding="utf-8")
    settings_path = home / ".claude" / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "systemPrompt": "drifted\n",
                claude_instruct.RECOVERY_MARKER_KEY: True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    before_preview = snapshot_tree(home)
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home, check=False)
    preview_payload = json.loads(preview.stdout)
    assert preview.returncode == 1
    assert preview_payload["ok"] is False
    assert preview_payload["blockers"]
    assert not any(item["action"] == "clear-settings-marker" for item in preview_payload["planned_repairs"])
    assert snapshot_tree(home) == before_preview

    execute = run_cli(
        ["recover", "--scope", "user", "--yes", "--json"],
        home=home,
        check=False,
    )
    execute_payload = json.loads(execute.stdout)
    assert execute.returncode == 1
    assert execute_payload["blockers"] == preview_payload["blockers"]
    assert json.loads(settings_path.read_text(encoding="utf-8"))[claude_instruct.RECOVERY_MARKER_KEY] is True


def test_recover_aligned_marker_preview_is_pure_then_execute_clears(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    keysmith_dir = home / ".claude" / "keysmith"
    keysmith_dir.mkdir(parents=True)
    system_body = "expected\n"
    (keysmith_dir / "system-prompt.md").write_text(system_body, encoding="utf-8")
    settings_path = home / ".claude" / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "systemPrompt": system_body,
                claude_instruct.RECOVERY_MARKER_KEY: True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    before_preview = snapshot_tree(home)
    preview_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--json"], home=home).stdout
    )
    assert preview_payload["ok"] is True
    assert any(item["action"] == "clear-settings-marker" for item in preview_payload["planned_repairs"])
    assert snapshot_tree(home) == before_preview

    execute_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home).stdout
    )
    assert execute_payload["ok"] is True
    assert claude_instruct.RECOVERY_MARKER_KEY not in json.loads(
        settings_path.read_text(encoding="utf-8")
    )


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


def test_recover_cleans_owned_atomic_temp_residue_without_touching_foreign_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    paths.keysmith_dir.mkdir(parents=True)
    owned = paths.keysmith_dir / f".rules.md{claude_instruct.ATOMIC_TEMP_MARKER}dead.tmp"
    foreign = paths.keysmith_dir / "tmp-user-file"
    owned.write_text("partial atomic write", encoding="utf-8")
    foreign.write_text("keep", encoding="utf-8")

    recovery_state = claude_instruct.inspect_recovery_state(paths)
    assert recovery_state["atomic_temp_files"] == [str(owned)]
    assert recovery_state["recovery_required"] is True

    blocked = run_cli(
        ["install", "--scope", "user", "--name", "rules", "--yes", "--json"],
        home=home,
        check=False,
    )
    assert blocked.returncode == 1
    assert "原子写临时残留" in json.loads(blocked.stdout)["error"]

    before_preview = snapshot_tree(home)
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home)
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["ok"] is True
    assert any(item["kind"] == "atomic_temp" for item in preview_payload["residue"])
    assert any(
        item["action"] == "cleanup-atomic-temp"
        for item in preview_payload["planned_repairs"]
    )
    assert snapshot_tree(home) == before_preview

    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    execute_payload = json.loads(execute.stdout)
    assert execute_payload["ok"] is True
    assert any(item["action"] == "cleanup-atomic-temp" for item in execute_payload["actions"])
    assert not owned.exists()
    assert foreign.read_text(encoding="utf-8") == "keep"


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


def test_committed_launcher_migration_is_never_reversed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    source = local_bin / "claude.ps1"
    backup = local_bin / "claude.ps1.bak_20260814_120000_pre_v6"
    source.write_text("# claude-keysmith\n$systemPrompt = 'system-prompt'\n", encoding="utf-8")
    before = claude_instruct.file_evidence(source)
    claude_instruct._move_file_no_overwrite(source, backup)

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step(
        {
            "action": "migrate",
            "path": str(local_bin),
            "before": claude_instruct.file_evidence(local_bin),
            "after": claude_instruct.file_evidence(local_bin),
            "moved": [[str(source), str(backup)]],
            "migration_items": [
                {"source": str(source), "backup": str(backup), "before": before}
            ],
        }
    )
    journal.commit()

    actions, blockers = claude_instruct.finish_committed_journal(journal.record)
    assert actions
    assert blockers == []
    original_backup = backup.read_bytes()
    backup.write_text("tampered after commit\n", encoding="utf-8")
    actions, blockers = claude_instruct.finish_committed_journal(journal.record)
    assert actions == []
    assert any("备份指纹异常" in item for item in blockers)
    backup.write_bytes(original_backup)

    malformed_record = json.loads(json.dumps(journal.record))
    malformed_record["steps"][0]["migration_items"] = [None]
    actions, blockers = claude_instruct.finish_committed_journal(malformed_record)
    assert actions == []
    assert any("证据格式无效" in item for item in blockers)

    payload = json.loads(
        run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home).stdout
    )
    assert payload["ok"] is True
    assert not source.exists()
    assert backup.is_file()
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


def test_forced_kill_after_first_legacy_launcher_move_recovers_exactly(tmp_path):
    home = tmp_path / "home"
    keysmith_dir = home / ".claude" / "keysmith"
    local_bin = home / ".local" / "bin"
    profile = home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    upstream = tmp_path / "upstream" / "claude.exe"
    barrier = tmp_path / "first-launcher-moved"
    keysmith_dir.mkdir(parents=True)
    local_bin.mkdir(parents=True)
    profile.parent.mkdir(parents=True)
    upstream.parent.mkdir(parents=True)
    upstream.write_bytes(b"fixture")

    legacy_ps1 = local_bin / "claude.ps1"
    legacy_cmd = local_bin / "claude.cmd"
    ps1_content = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    cmd_content = '@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %*\r\n'
    legacy_ps1.write_text(ps1_content, encoding="utf-8")
    legacy_cmd.write_bytes(cmd_content.encode("utf-8"))

    baseline = snapshot_tree(home)
    child_code = r"""
import importlib.util
import sys
import time
from pathlib import Path

module_path = Path(sys.argv[1])
barrier = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("claude_instruct_kill_fixture", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
real_move = module._move_file_no_overwrite
move_count = 0

def pause_after_first_move(source, target):
    global move_count
    real_move(source, target)
    move_count += 1
    if move_count == 1:
        barrier.write_text("moved\n", encoding="utf-8")
        while True:
            time.sleep(1)

module._move_file_no_overwrite = pause_after_first_move
sys.argv = [
    str(module_path),
    "install",
    "--scope",
    "user",
    "--runtime",
    "--yes",
    "--json",
]
raise SystemExit(module.main())
"""
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "CLAUDE_KEYSMITH_HOME": str(home),
            "CLAUDE_KEYSMITH_SHELL": "powershell",
            "CLAUDE_KEYSMITH_SHELL_RC": str(profile),
            "CLAUDE_KEYSMITH_CLAUDE_BIN": str(upstream),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "PYTHONPYCACHEPREFIX": str(tmp_path / ".python-cache"),
        }
    )
    env.pop("CLAUDE_CONFIG_DIR", None)

    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(MODULE_PATH), str(barrier)],
        env=env,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 20
    while not barrier.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if not barrier.exists():
        stdout, stderr = child.communicate(timeout=5)
        pytest.fail(f"child did not reach migration barrier: {stdout}\n{stderr}")

    child.kill()
    child.wait(timeout=10)
    assert child.returncode != 0
    assert not legacy_ps1.exists()
    assert legacy_cmd.read_bytes() == cmd_content.encode("utf-8")
    assert list(local_bin.glob("claude.ps1.bak_*_pre_v6*"))

    journals = list(keysmith_dir.glob(".journal-*.json"))
    assert len(journals) == 1
    journal_record = json.loads(journals[0].read_text(encoding="utf-8"))
    migrate_step = next(step for step in journal_record["steps"] if step["action"] == "migrate")
    assert len(migrate_step["migration_items"]) == 2
    assert migrate_step["moved"] == []  # kill happened before after-move progress persisted

    blocked = run_cli(
        ["install", "--scope", "user", "--runtime", "--yes", "--json"],
        home=home,
        extra_env={
            "CLAUDE_KEYSMITH_SHELL": "powershell",
            "CLAUDE_KEYSMITH_SHELL_RC": str(profile),
            "CLAUDE_KEYSMITH_CLAUDE_BIN": str(upstream),
        },
        check=False,
    )
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["ok"] is False

    before_preview = snapshot_tree(home)
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home)
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["ok"] is True
    assert any(item["action"] == "restore-moved" for item in preview_payload["planned_repairs"])
    assert snapshot_tree(home) == before_preview

    execute = run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home)
    execute_payload = json.loads(execute.stdout)
    assert execute_payload["ok"] is True
    assert legacy_ps1.read_text(encoding="utf-8") == ps1_content
    assert legacy_cmd.read_bytes() == cmd_content.encode("utf-8")
    assert not list(local_bin.glob("claude.*.bak_*_pre_v6*"))
    assert not list(keysmith_dir.glob(".journal-*.json"))
    assert not (keysmith_dir / ".keysmith.lock").exists()

    final = snapshot_tree(home)

    def controlled_state(tree):
        prefixes = (".claude", ".local", "Documents")
        return {
            key: (value[0], value[1])
            for key, value in tree.items()
            if key == "." or any(key == prefix or key.startswith(prefix + os.sep) for prefix in prefixes)
        }

    # macOS may let the Python runtime create its own ~/Library cache tree;
    # keysmith-controlled paths must still return byte-for-byte to baseline.
    assert controlled_state(final) == controlled_state(baseline)


def test_live_launcher_migration_rejects_source_replacement_after_precheck(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    source = local_bin / "claude.ps1"
    cmd = local_bin / "claude.cmd"
    original = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    replacement = "third-party replacement\n"
    source.write_text(original, encoding="utf-8")
    cmd.write_bytes(b'@echo off\r\npowershell.exe -File "%~dp0claude.ps1" %*\r\n')

    journal = claude_instruct.TransactionJournal(paths, "install")
    real_move = claude_instruct._move_file_no_overwrite

    def replace_source_after_precheck(move_source, target):
        if Path(move_source) == source:
            source.write_text(replacement, encoding="utf-8")
        real_move(Path(move_source), Path(target))

    monkeypatch.setattr(
        claude_instruct, "_move_file_no_overwrite", replace_source_after_precheck
    )
    with pytest.raises(OSError, match="迁移失败且回滚不完整"):
        claude_instruct.tx_migrate_legacy_launchers(
            journal, home, "20260814_120000"
        )

    journal_record = json.loads(journal.path.read_text(encoding="utf-8"))
    migrate_step = next(
        step for step in journal_record["steps"] if step["action"] == "migrate"
    )
    backup = Path(migrate_step["migration_items"][0]["backup"])
    assert migrate_step["moved"] == []
    assert not source.exists()
    assert backup.read_text(encoding="utf-8") == replacement
    assert cmd.exists()

    before_preview = snapshot_tree(home)
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home, check=False)
    preview_payload = json.loads(preview.stdout)
    assert preview.returncode == 1
    assert preview_payload["ok"] is False
    assert any("指纹不匹配" in item for item in preview_payload["blockers"])
    assert snapshot_tree(home) == before_preview

    execute = run_cli(
        ["recover", "--scope", "user", "--yes", "--json"],
        home=home,
        check=False,
    )
    execute_payload = json.loads(execute.stdout)
    assert execute.returncode == 1
    assert execute_payload["blockers"] == preview_payload["blockers"]
    assert not source.exists()
    assert backup.read_text(encoding="utf-8") == replacement
    assert cmd.exists()
    assert journal.path.exists()


def test_pending_launcher_migration_preserves_same_content_distinct_backup(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    source = local_bin / "claude.ps1"
    backup = local_bin / "claude.ps1.bak_20260814_120000_pre_v6"
    content = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    source.write_text(content, encoding="utf-8")
    before = claude_instruct.file_evidence(source)
    backup.write_text(content, encoding="utf-8")  # same bytes, different file identity

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step(
        {
            "action": "migrate",
            "path": str(local_bin),
            "before": claude_instruct.file_evidence(local_bin),
            "after": {},
            "moved": [],
            "migration_items": [
                {"source": str(source), "backup": str(backup), "before": before}
            ],
        }
    )

    before_preview = snapshot_tree(home)
    preview = run_cli(["recover", "--scope", "user", "--json"], home=home, check=False)
    preview_payload = json.loads(preview.stdout)
    assert preview.returncode == 1
    assert any("身份不同" in item for item in preview_payload["blockers"])
    assert snapshot_tree(home) == before_preview

    execute = run_cli(
        ["recover", "--scope", "user", "--yes", "--json"],
        home=home,
        check=False,
    )
    assert execute.returncode == 1
    assert source.read_text(encoding="utf-8") == content
    assert backup.read_text(encoding="utf-8") == content
    assert journal.path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX migration uses a hard-link transition")
def test_pending_launcher_migration_cleans_same_inode_transition(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    source = local_bin / "claude.ps1"
    backup = local_bin / "claude.ps1.bak_20260814_120000_pre_v6"
    content = "# claude-keysmith\n$systemPrompt = 'system-prompt'\n"
    source.write_text(content, encoding="utf-8")
    before = claude_instruct.file_evidence(source)
    os.link(str(source), str(backup))
    assert os.path.samestat(source.stat(), backup.stat())

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step(
        {
            "action": "migrate",
            "path": str(local_bin),
            "before": claude_instruct.file_evidence(local_bin),
            "after": {},
            "moved": [],
            "migration_items": [
                {"source": str(source), "backup": str(backup), "before": before}
            ],
        }
    )

    preview_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--json"], home=home).stdout
    )
    assert preview_payload["ok"] is True
    assert any(item["action"] == "cleanup" for item in preview_payload["planned_repairs"])
    assert source.exists() and backup.exists()

    execute_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home).stdout
    )
    assert execute_payload["ok"] is True
    assert source.read_text(encoding="utf-8") == content
    assert not backup.exists()
    assert not journal.path.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX recovery uses a hard-link transition")
def test_old_moved_only_journal_cleans_interrupted_recovery_hard_link(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_KEYSMITH_HOME", str(home))
    paths = claude_instruct.resolve_scope("user")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    source = local_bin / "claude.ps1"
    backup = local_bin / "claude.ps1.bak_20260814_120000_pre_v6"
    backup.write_text("# claude-keysmith\n$systemPrompt = 'system-prompt'\n", encoding="utf-8")
    os.link(str(backup), str(source))

    journal = claude_instruct.TransactionJournal(paths, "install")
    journal.log_step(
        {
            "action": "migrate",
            "path": str(local_bin),
            "before": claude_instruct.file_evidence(local_bin),
            "after": {},
            "moved": [[str(source), str(backup)]],
        }
    )

    preview_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--json"], home=home).stdout
    )
    assert preview_payload["ok"] is True
    assert any(item["action"] == "cleanup" for item in preview_payload["planned_repairs"])

    execute_payload = json.loads(
        run_cli(["recover", "--scope", "user", "--yes", "--json"], home=home).stdout
    )
    assert execute_payload["ok"] is True
    assert source.is_file()
    assert not backup.exists()
    assert not journal.path.exists()


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
