#!/usr/bin/env python3
"""
claude-keysmith: Claude Code instruction + runtime injector.

Layers:
  1. CLAUDE.md / CLAUDE.local.md managed import block + keysmith instruction file
  2. Optional user-scope runtime injection:
       - ~/.claude/keysmith/system-prompt.md
       - ~/.claude/keysmith/append-prompt.md
       - settings.json systemPrompt alignment
       - shell wrapper that passes --system-prompt-file + --append-system-prompt-file

Safety defaults:
  - Preview-only unless --yes is provided.
  - Never edits Claude Code binaries, network settings, credentials, MCP config,
    tokens, or running processes.
  - Runtime injection only touches keysmith-owned prompt files, settings.systemPrompt
    alignment, and a managed shell wrapper block.
  - Backs up touched files before overwriting or removing them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
START_TEMPLATE = "<!-- claude-keysmith:start name={name} -->"
END_TEMPLATE = "<!-- claude-keysmith:end name={name} -->"
def _resource_base() -> Path:
    """Base directory for bundled resources (examples/).

    When frozen by PyInstaller, resources land in sys._MEIPASS; otherwise they
    live next to this source file.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


DEFAULT_EXAMPLE = _resource_base() / "examples" / "claude-project-rules.md"
DEFAULT_APPEND_EXAMPLE = _resource_base() / "examples" / "claude-append-prompt.md"
VERSION = "v7"
ATOMIC_TEMP_MARKER = ".keysmith-tmp-"

SHELL_BEGIN = "# >>> claude-keysmith runtime >>>"
SHELL_END = "# <<< claude-keysmith runtime <<<"
SHELL_VERSION_MARKER = f"# claude-keysmith wrapper version: {VERSION}"
WINDOWS_UPSTREAM_RETRY_SECONDS = 10
WINDOWS_UPSTREAM_RETRY_MILLISECONDS = 250
LEGACY_CMD_FORWARD_RE = re.compile(
    r"(?i)(?:@|call\s+)?(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)"
    r"(?:\s+-(?:noprofile|nologo|noninteractive|sta|mta)"
    r"|\s+-executionpolicy\s+(?:bypass|remotesigned|unrestricted|allsigned|restricted|default|undefined))*"
    r"\s+-file\s+(?:\"%~dp0claude\.ps1\"|%~dp0claude\.ps1)\s+%\*"
)
LEGACY_WRAPPER_RE = re.compile(
    r"(?ms)^# Claude Code with persistent system prompt override\n"
    r"(?:# Claude Code with persistent system prompt override\n)?"
    r"claude\(\) \{\n"
    r"  /Users/[^\n]+/\.local/bin/claude --system-prompt \"\$\(cat ~?/?\.claude/keysmith/system-prompt\.md\)\" \"\$@\"\n"
    r"\}\n?"
)


@dataclass(frozen=True)
class ScopePaths:
    scope: str
    root: Path
    memory_file: Path
    keysmith_dir: Path
    import_prefix: str

    def instruction_file(self, md_filename: str) -> Path:
        return self.keysmith_dir / md_filename

    def import_target(self, md_filename: str) -> str:
        return f"@{self.import_prefix}/{md_filename}"


def normalize_md_name(name: str) -> str:
    """Return a safe .md filename, rejecting paths, traversal, and shell-ish names."""
    raw = (name or "").strip()
    if raw.endswith(".md"):
        raw = raw[:-3]

    if not raw or raw in {".", ".."}:
        raise ValueError("--name 不能为空、'.' 或 '..'")
    if "/" in raw or "\\" in raw:
        raise ValueError("--name 只能是文件名，不能包含路径分隔符")
    if ".." in raw:
        raise ValueError("--name 不能包含 '..'")
    if not SAFE_NAME_RE.fullmatch(raw):
        raise ValueError("--name 只能包含字母、数字、点、下划线和连字符")

    return f"{raw}.md"


def marker_name(md_filename: str) -> str:
    return md_filename[:-3] if md_filename.endswith(".md") else md_filename


def configure_utf8_stdio() -> None:
    """Keep CLI diagnostics writable when Windows inherits a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _atomic_temp_prefix(path: Path) -> str:
    return f".{path.name}{ATOMIC_TEMP_MARKER}"


def atomic_write_text(path: Path, content: str) -> None:
    """Write UTF-8 text atomically inside the target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=_atomic_temp_prefix(path),
            suffix=".tmp",
            delete=False,
            newline="\n",
        )
        tmp_path = Path(tmp_file.name)
        with tmp_file:
            tmp_file.write(content)
            flush = getattr(tmp_file, "flush", None)
            if flush is not None:
                flush()
        os.replace(str(tmp_path), str(path))
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def backup_file(path: Path, timestamp: Optional[str] = None, suffix: str = "") -> Path:
    """Create a timestamped backup without racing another backup writer."""
    if not path.exists():
        raise FileNotFoundError(f"无法备份不存在的文件: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"不是普通文件，拒绝备份: {path}")
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    extra = f"_{suffix}" if suffix else ""
    base = path.with_name(f"{path.name}.bak_{ts}{extra}")
    counter = 1
    while True:
        backup = base if counter == 1 else base.with_name(f"{base.name}_{counter}")
        counter += 1
        try:
            fd = os.open(
                str(backup),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                path.stat().st_mode & 0o777 or 0o600,
            )
        except FileExistsError:
            continue

        open_fd: Optional[int] = fd
        try:
            destination_file = os.fdopen(fd, "wb")
            open_fd = None
            with destination_file as destination:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, destination)
                destination.flush()
            shutil.copystat(path, backup)
        except BaseException:
            if open_fd is not None:
                try:
                    os.close(open_fd)
                except OSError:
                    pass
            try:
                backup.unlink()
            except OSError:
                pass
            raise
        return backup


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise FileNotFoundError(f"不是普通文件: {path}")
    return path.read_text(encoding="utf-8")


def strip_markdown_h1(content: str) -> str:
    """Drop a leading AT1 so the body can be used as a raw system prompt."""
    lines = content.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        body = "\n".join(lines[1:]).lstrip("\n")
    else:
        body = content
    if body and not body.endswith("\n"):
        body += "\n"
    if not body:
        body = "\n"
    return body


def ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else content + "\n"


def render_import_block(name: str, scope: str) -> str:
    md_filename = normalize_md_name(name)
    import_prefix = "keysmith" if scope == "user" else ".claude/keysmith"
    return render_import_block_for_target(marker_name(md_filename), f"@{import_prefix}/{md_filename}")


def render_import_block_for_target(name: str, import_target: str) -> str:
    return "\n".join(
        [
            START_TEMPLATE.format(name=name),
            import_target,
            END_TEMPLATE.format(name=name),
        ]
    )


def block_pattern(name: str) -> re.Pattern:
    start = re.escape(START_TEMPLATE.format(name=name))
    end = re.escape(END_TEMPLATE.format(name=name))
    return re.compile(rf"(?ms)^{start}\n.*?^{end}\n?")


def has_import_block(content: str, name: str) -> bool:
    return block_pattern(name).search(content) is not None


def ensure_import_block(content: str, name: str, import_target: str) -> Tuple[str, bool]:
    """Insert or replace exactly one managed import block for name."""
    desired = render_import_block_for_target(name, import_target) + "\n"
    pattern = block_pattern(name)
    match = pattern.search(content)
    if match:
        if match.group(0) == desired:
            return content, False
        return pattern.sub(desired, content, count=1), True

    prefix = content
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + desired, True


def remove_import_block(content: str, name: str) -> Tuple[str, bool]:
    pattern = block_pattern(name)
    updated, count = pattern.subn("", content, count=1)
    return updated, bool(count)


def resolve_home() -> Path:
    """Resolve home dir: $CLAUDE_KEYSMITH_HOME > $HOME > Path.home().

    Windows workaround: Path.home() reads USERPROFILE and ignores $HOME
    set by Git Bash / MSYS2. This helper preserves Unix $HOME behaviour.
    """
    configured = (
        os.environ.get("CLAUDE_KEYSMITH_HOME")
        or os.environ.get("HOME")
    )
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home().resolve()


def runtime_shell_kind() -> str:
    """Return 'powershell' on Windows (os.name == 'nt'), else 'zsh'.

    Override with $CLAUDE_KEYSMITH_SHELL.
    """
    configured = os.environ.get("CLAUDE_KEYSMITH_SHELL", "").strip().lower()
    if configured:
        return configured
    return "powershell" if os.name == "nt" else "zsh"


def powershell_profile_path(home: Path) -> Path:
    """Locate PowerShell profile for PS5 (WindowsPowerShell) or PS7 (PowerShell).

    Override with $CLAUDE_KEYSMITH_SHELL_RC.
    """
    configured = os.environ.get("CLAUDE_KEYSMITH_SHELL_RC")
    if configured:
        return Path(configured).expanduser().resolve()
    module_path = os.environ.get("PSModulePath", "")
    if ";" in module_path:
        entries = module_path.split(";")
    elif os.pathsep == ":" and not re.match(r"^[A-Za-z]:[\\/]", module_path):
        entries = module_path.split(os.pathsep)
    else:
        entries = [module_path]
    for entry in (item.strip().strip('"') for item in entries):
        if not entry:
            continue
        module_dir = Path(entry).expanduser()
        # Fresh Windows installs can advertise the user module path before the
        # directory has been created, so classify the path by structure.
        if module_dir.name.lower() != "modules":
            continue
        shell_dir = module_dir.parent
        if shell_dir.name.lower() not in {"windowspowershell", "powershell"}:
            continue
        lowered_parts = {part.lower() for part in module_dir.parts}
        if lowered_parts.intersection({"program files", "program files (x86)", "system32"}):
            continue
        try:
            module_dir.resolve().relative_to(home.expanduser().resolve())
            user_level = True
        except ValueError:
            user_level = "documents" in lowered_parts
        if not user_level:
            continue
        return shell_dir / "Microsoft.PowerShell_profile.ps1"
    raise ValueError(
        "无法从 PSModulePath 判断 PowerShell 5.1/7 profile；"
        "请设置 CLAUDE_KEYSMITH_SHELL_RC 为目标 profile 的完整路径"
    )


def _env_case_insensitive(name: str) -> Optional[str]:
    """Read an environment variable with Windows-compatible case matching."""
    direct = os.environ.get(name)
    if direct is not None:
        return direct
    lowered = name.lower()
    for key, value in os.environ.items():
        if key.lower() == lowered:
            return value
    return None


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _candidate(kind: str, path: Path, reason: Optional[str] = None, eligible: bool = True) -> Dict[str, Any]:
    try:
        exists = path.is_file()
    except OSError:
        exists = False
    if reason is None:
        reason = "available" if exists else "missing"
    return {
        "kind": kind,
        "path": str(path),
        "exists": exists,
        "eligible": eligible,
        "reason": reason,
    }


def _windows_path_entries() -> List[Path]:
    raw_path = _env_case_insensitive("PATH") or ""
    separator = ";" if ";" in raw_path else os.pathsep
    return [Path(item.strip().strip('"')) for item in raw_path.split(separator) if item.strip().strip('"')]


def _npm_prefixes(home: Path) -> List[Path]:
    prefixes: List[Path] = []
    configured = (_env_case_insensitive("NPM_CONFIG_PREFIX") or "").strip()
    if configured:
        prefixes.append(Path(configured).expanduser())

    appdata = (_env_case_insensitive("APPDATA") or "").strip()
    prefixes.append(Path(appdata).expanduser() / "npm" if appdata else home / "AppData" / "Roaming" / "npm")

    # A custom npm prefix is often visible only through its shim directory in PATH.
    for entry in _windows_path_entries():
        package_exe = entry / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if package_exe.is_file() or any((entry / name).is_file() for name in ("claude.cmd", "claude.ps1")):
            prefixes.append(entry)

    unique: List[Path] = []
    seen = set()
    for prefix in prefixes:
        key = _path_key(prefix)
        if key not in seen:
            seen.add(key)
            unique.append(prefix)
    return unique


def inspect_legacy_launchers(home: Path) -> Dict[str, Any]:
    """Classify old ~/.local/bin launchers without modifying unknown files."""
    bin_dir = home / ".local" / "bin"
    ps1 = bin_dir / "claude.ps1"
    cmd = bin_dir / "claude.cmd"
    existing = [path for path in (ps1, cmd) if os.path.lexists(str(path))]
    if not existing:
        return {
            "detected": False,
            "paths": [],
            "conflict": False,
            "conflict_paths": [],
        }

    try:
        ps1_text = ps1.read_text(encoding="utf-8") if ps1.is_file() else ""
        cmd_text = cmd.read_text(encoding="utf-8") if cmd.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return {
            "detected": False,
            "paths": [],
            "conflict": True,
            "conflict_paths": [str(path) for path in existing],
        }

    ps1_regular = ps1.is_file() and not ps1.is_symlink()
    cmd_regular = cmd.is_file() and not cmd.is_symlink()
    ps1_lower = ps1_text.lower()
    ps1_known = bool(
        ps1_regular
        and "keysmith" in ps1_lower
        and ("system-prompt" in ps1_lower or "append-prompt" in ps1_lower)
    )

    cmd_lines = [line.strip() for line in cmd_text.splitlines() if line.strip()]
    if cmd_lines and cmd_lines[0].lower() == "@echo off":
        cmd_lines = cmd_lines[1:]
    forwarder = cmd_lines[0] if cmd_lines else ""
    cmd_known = bool(
        cmd_regular
        and len(cmd_lines) in (1, 2)
        and LEGACY_CMD_FORWARD_RE.fullmatch(forwarder)
        and (
            len(cmd_lines) == 1
            or re.fullmatch(r"(?i)exit\s+/b\s+%errorlevel%", cmd_lines[1])
        )
    )

    known_pair = ps1_known and cmd_known
    return {
        "detected": known_pair,
        "paths": [str(ps1), str(cmd)] if known_pair else [],
        "conflict": bool(existing and not known_pair),
        "conflict_paths": [str(path) for path in existing] if not known_pair else [],
    }


def _unique_backup_candidate(path: Path, timestamp: str, suffix: str = "") -> Path:
    """Choose an unused backup name without touching the filesystem."""
    extra = f"_{suffix}" if suffix else ""
    base = path.with_name(f"{path.name}.bak_{timestamp}{extra}")
    counter = 1
    while True:
        candidate = base if counter == 1 else base.with_name(f"{base.name}_{counter}")
        if not os.path.lexists(str(candidate)):
            return candidate
        counter += 1


def plan_legacy_launcher_migration(home: Path, timestamp: str) -> List[Dict[str, Any]]:
    """Build a side-effect-free launcher migration plan with source fingerprints."""
    inspection = inspect_legacy_launchers(home)
    if inspection["conflict"]:
        raise ValueError("检测到未知 ~/.local/bin/claude.ps1 或 claude.cmd，拒绝覆盖")
    if not inspection["detected"]:
        return []

    plan: List[Dict[str, Any]] = []
    for raw_path in inspection["paths"]:
        source = Path(raw_path)
        before = file_evidence(source)
        if not before.get("exists") or source.is_symlink():
            raise ValueError(f"旧 launcher 在迁移规划期间发生变化，拒绝继续: {source}")
        plan.append(
            {
                "source": str(source),
                "backup": str(_unique_backup_candidate(source, timestamp, "pre_v6")),
                "before": before,
            }
        )
    verification = inspect_legacy_launchers(home)
    if not verification["detected"] or verification["paths"] != inspection["paths"]:
        raise ValueError("旧 launcher 在迁移规划期间发生变化，拒绝继续")
    if any(
        not _migration_item_matches(Path(item["source"]), item["before"])
        for item in plan
    ):
        raise ValueError("旧 launcher 在迁移规划期间发生变化，拒绝继续")
    return plan


def _move_file_no_overwrite(source: Path, target: Path) -> None:
    """Move a regular file without ever replacing an existing target."""
    if os.name == "nt":
        os.rename(str(source), str(target))
        return

    # POSIX rename replaces an existing destination. A same-directory hard
    # link plus unlink preserves no-overwrite semantics and is crash-recoverable.
    os.link(str(source), str(target))
    try:
        source.unlink()
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def _migration_item_matches(path: Path, expected: Dict[str, Any]) -> bool:
    try:
        return bool(
            os.path.lexists(str(path))
            and path.is_file()
            and not path.is_symlink()
            and file_evidence(path).get("sha256") == expected.get("sha256")
        )
    except OSError:
        return False


def _same_posix_file_identity(first: Path, second: Path) -> bool:
    if os.name == "nt":
        return False
    try:
        return os.path.samestat(first.stat(), second.stat())
    except OSError:
        return False


def migrate_legacy_launchers(
    home: Path,
    timestamp: str,
    *,
    migration_plan: Optional[List[Dict[str, Any]]] = None,
    on_moved: Optional[Callable[[Path, Path], None]] = None,
) -> List[Tuple[Path, Path]]:
    """Rename a recognized launcher pair to unique recovery backups."""
    plan = migration_plan if migration_plan is not None else plan_legacy_launcher_migration(home, timestamp)
    if not plan:
        return []

    moved: List[Tuple[Path, Path]] = []
    try:
        for item in plan:
            source = Path(item["source"])
            backup = Path(item["backup"])
            before = item.get("before") or {}
            if not _migration_item_matches(source, before):
                raise OSError(f"旧 launcher 在迁移前发生变化，拒绝移动: {source}")
            if os.path.lexists(str(backup)):
                raise FileExistsError(f"旧 launcher 备份路径已被占用，拒绝覆盖: {backup}")
            _move_file_no_overwrite(source, backup)
            moved.append((source, backup))
            if not _migration_item_matches(backup, before):
                raise OSError(f"旧 launcher 在迁移期间发生变化，拒绝提交: {source}")
            if on_moved is not None:
                on_moved(source, backup)
    except BaseException as migration_error:
        rollback_errors: List[str] = []
        plan_by_source = {item["source"]: item for item in plan}
        for source, backup in reversed(moved):
            before = plan_by_source[str(source)].get("before") or {}
            source_matches = _migration_item_matches(source, before)
            backup_matches = _migration_item_matches(backup, before)
            if source_matches and not os.path.lexists(str(backup)):
                continue
            if source_matches and backup_matches:
                if _same_posix_file_identity(source, backup):
                    try:
                        backup.unlink()
                    except OSError as exc:
                        rollback_errors.append(f"{backup}: {exc}")
                else:
                    rollback_errors.append(f"{source}: rollback target was recreated")
                continue
            if not os.path.lexists(str(source)) and backup_matches:
                try:
                    _move_file_no_overwrite(backup, source)
                except OSError as exc:
                    rollback_errors.append(f"{source}: {exc}")
                continue
            rollback_errors.append(f"{source}: launcher/backup state no longer matches the migration plan")
        if rollback_errors:
            details = "; ".join(rollback_errors)
            raise OSError(f"旧 launcher 迁移失败且回滚不完整: {details}") from migration_error
        raise
    return moved


def resolve_upstream_candidates(home: Path, shell_kind: str) -> List[Dict[str, Any]]:
    """Return ordered Claude entry-point candidates and rejection reasons."""
    configured = (_env_case_insensitive("CLAUDE_KEYSMITH_CLAUDE_BIN") or "").strip()
    if configured:
        override = Path(configured).expanduser().resolve()
        return [
            _candidate(
                "override",
                override,
                None if override.is_file() else "configured override is missing; fallback is disabled",
            )
        ]

    if shell_kind != "powershell":
        found = shutil.which("claude")
        path = Path(found).resolve() if found else (home / ".local" / "bin" / "claude").resolve()
        return [_candidate("path", path)]

    candidates: List[Dict[str, Any]] = []
    seen = set()

    def add(kind: str, path: Path, reason: Optional[str] = None, eligible: bool = True) -> None:
        key = _path_key(path)
        if key in seen:
            return
        seen.add(key)
        candidates.append(_candidate(kind, path, reason, eligible))

    native = home / ".local" / "bin" / "claude.exe"
    add("native", native)

    prefixes = _npm_prefixes(home)
    npm_prefix_keys = {_path_key(prefix) for prefix in prefixes}
    for entry in _windows_path_entries():
        if _path_key(entry) in npm_prefix_keys:
            continue
        path_exe = entry / "claude.exe"
        if path_exe.is_file():
            kind = "winget" if "winget" in str(path_exe).lower() else "path_native"
            add(kind, path_exe)

    for prefix in prefixes:
        add(
            "npm_package",
            prefix / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe",
        )

    legacy_dir = _path_key(home / ".local" / "bin")
    for prefix in prefixes:
        for name in ("claude.cmd", "claude.ps1", "claude.exe"):
            shim = prefix / name
            if _path_key(prefix) == legacy_dir and name in ("claude.cmd", "claude.ps1"):
                add("excluded_keysmith_launcher", shim, "keysmith-owned launcher excluded to prevent recursion", False)
            else:
                add("npm_shim", shim)
    return candidates


def select_upstream_candidate(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next(
        (candidate for candidate in candidates if candidate.get("eligible", True) and candidate.get("exists")),
        None,
    )


def find_claude_binary(home: Path, shell_kind: str) -> Path:
    """Locate the claude binary for the current platform.

    Override with $CLAUDE_KEYSMITH_CLAUDE_BIN.
    """
    candidates = resolve_upstream_candidates(home, shell_kind)
    selected = select_upstream_candidate(candidates)
    if selected is not None:
        return Path(selected["path"])
    eligible = next((candidate for candidate in candidates if candidate.get("eligible", True)), None)
    if eligible is None:
        raise FileNotFoundError("没有可用的 Claude Code 上游候选")
    return Path(eligible["path"])


def resolve_scope(scope: str, project_dir: Optional[str] = None) -> ScopePaths:
    if scope == "user":
        claude_root = (resolve_home() / ".claude").resolve()
        return ScopePaths(
            scope="user",
            root=claude_root,
            memory_file=claude_root / "CLAUDE.md",
            keysmith_dir=claude_root / "keysmith",
            import_prefix="keysmith",
        )

    project_root = Path(project_dir or os.getcwd()).expanduser().resolve()
    if not project_root.exists() or not project_root.is_dir():
        raise FileNotFoundError(f"project directory 不存在或不是目录: {project_root}")

    memory_name = "CLAUDE.md" if scope == "project" else "CLAUDE.local.md"
    return ScopePaths(
        scope=scope,
        root=project_root,
        memory_file=project_root / memory_name,
        keysmith_dir=project_root / ".claude" / "keysmith",
        import_prefix=".claude/keysmith",
    )


def load_instruction_content(file_path: Optional[str]) -> str:
    source = Path(file_path).expanduser().resolve() if file_path else DEFAULT_EXAMPLE
    if not source.exists():
        raise FileNotFoundError(f"指令文件不存在: {source}")
    if not source.is_file():
        raise FileNotFoundError(f"不是普通文件: {source}")
    return source.read_text(encoding="utf-8")


def load_append_content(file_path: Optional[str]) -> str:
    source = Path(file_path).expanduser().resolve() if file_path else DEFAULT_APPEND_EXAMPLE
    if not source.exists():
        raise FileNotFoundError(f"append 指令文件不存在: {source}")
    if not source.is_file():
        raise FileNotFoundError(f"不是普通文件: {source}")
    return ensure_trailing_newline(source.read_text(encoding="utf-8"))


def preview_header(args) -> bool:
    """Return True when the command must not write.

    Dry-run is the safer explicit mode, so it wins even if --yes is also passed.
    """
    explicit_dry_run = bool(getattr(args, "dry_run", False))
    preview_only = explicit_dry_run or not getattr(args, "yes", False)
    if preview_only:
        print("[DRY RUN] 预览模式，不实际修改。")
        if explicit_dry_run and getattr(args, "yes", False):
            print("    已同时收到 --dry-run 和 --yes；按安全优先，--dry-run 生效。")
        else:
            print("    如确认写入，请重新运行并添加 --yes。")
    return preview_only


def describe_scope(paths: ScopePaths, md_filename: str) -> None:
    print(f"scope: {paths.scope}")
    print(f"memory file: {paths.memory_file}")
    print(f"instruction file: {paths.instruction_file(md_filename)}")
    print(f"import target: {paths.import_target(md_filename)}")


def user_runtime_paths() -> Dict[str, Any]:
    """Return runtime paths with platform-aware shell and binary locations."""
    home = resolve_home()
    shell_kind = runtime_shell_kind()
    keysmith_dir = home / ".claude" / "keysmith"
    shell_rc = powershell_profile_path(home) if shell_kind == "powershell" else home / ".zshrc"
    upstream_candidates = resolve_upstream_candidates(home, shell_kind)
    selected = select_upstream_candidate(upstream_candidates)
    claude_bin = Path(selected["path"]) if selected else find_claude_binary(home, shell_kind)
    legacy = inspect_legacy_launchers(home) if shell_kind == "powershell" else {
        "detected": False,
        "paths": [],
        "conflict": False,
        "conflict_paths": [],
    }
    return {
        "home": home,
        "claude_dir": home / ".claude",
        "keysmith_dir": keysmith_dir,
        "system_prompt": keysmith_dir / "system-prompt.md",
        "append_prompt": keysmith_dir / "append-prompt.md",
        "settings": home / ".claude" / "settings.json",
        "shell_kind": shell_kind,
        "shell_rc": shell_rc,
        "zshrc": shell_rc,  # backward-compat alias
        "claude_bin": claude_bin,
        "upstream_candidates": upstream_candidates,
        "upstream_path": str(selected["path"]) if selected else None,
        "upstream_exists": selected is not None,
        "legacy_launcher_detected": legacy["detected"],
        "legacy_launcher_paths": legacy["paths"],
        "legacy_launcher_conflict": legacy["conflict"],
        "legacy_launcher_conflict_paths": legacy["conflict_paths"],
    }


def _powershell_quote(value: Path) -> str:
    """PowerShell single-quote escaping."""
    return "'" + str(value).replace("'", "''") + "'"


def render_shell_wrapper(
    claude_bin: Path,
    system_prompt: Path,
    append_prompt: Path,
    shell_kind: str = "zsh",
    upstream_candidates: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate a managed shell wrapper for zsh or PowerShell."""
    if shell_kind == "powershell":
        candidate_paths = [
            Path(candidate["path"])
            for candidate in (upstream_candidates or [_candidate("configured", claude_bin)])
            if candidate.get("eligible", True)
        ]
        candidate_lines = [f"    {_powershell_quote(path)}" for path in candidate_paths]
        return "\n".join(
            [
                SHELL_BEGIN,
                SHELL_VERSION_MARKER,
                "# Managed by claude-keysmith. Do not edit by hand.",
                "function global:claude {",
                "  $ErrorActionPreference = 'Stop'",
                "  $PSNativeCommandUseErrorActionPreference = $false",
                f"  $systemPrompt = {_powershell_quote(system_prompt)}",
                f"  $appendPrompt = {_powershell_quote(append_prompt)}",
                "  foreach ($required in @($systemPrompt, $appendPrompt)) {",
                "    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {",
                "      throw \"claude-keysmith required prompt is missing: $required\"",
                "    }",
                "  }",
                "  $upstreamCandidates = @(",
                *candidate_lines,
                "  )",
                f"  $deadline = [DateTime]::UtcNow.AddSeconds({WINDOWS_UPSTREAM_RETRY_SECONDS})",
                "  do {",
                "    foreach ($candidate in $upstreamCandidates) {",
                "      if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }",
                "      try {",
                "        & $candidate `",
                "          --system-prompt-file $systemPrompt `",
                "          --append-system-prompt-file $appendPrompt `",
                "          @args",
                "        $claudeKeysmithExitCode = $LASTEXITCODE",
                "      } catch [System.Management.Automation.CommandNotFoundException] {",
                "        if ($_.InvocationInfo.InvocationName -eq '&' -and $_.CategoryInfo.TargetName -eq $candidate -and $_.InvocationInfo.ScriptName -eq $PSCommandPath) { continue }",
                "        throw",
                "      } catch [System.Management.Automation.ItemNotFoundException] {",
                "        if ($_.InvocationInfo.InvocationName -eq '&' -and $_.CategoryInfo.TargetName -eq $candidate -and $_.InvocationInfo.ScriptName -eq $PSCommandPath) { continue }",
                "        throw",
                "      }",
                "      if ($null -eq $claudeKeysmithExitCode) { $claudeKeysmithExitCode = 0 }",
                "      $global:LASTEXITCODE = $claudeKeysmithExitCode",
                "      return",
                "    }",
                "    if ([DateTime]::UtcNow -ge $deadline) { break }",
                f"    Start-Sleep -Milliseconds {WINDOWS_UPSTREAM_RETRY_MILLISECONDS}",
                "  } while ($true)",
                "  throw 'Claude Code entry point is unavailable after 10 seconds. Repair or reinstall Claude Code, then retry.'",
                "}",
                SHELL_END,
                "",
            ]
        )
    # Keep prompt paths absolute; resolve the Claude entry point dynamically at
    # invocation time so a versioned install directory breaking after an update
    # (or a PATH shadow change) cannot wedge the wrapper on a stale absolute path.
    return "\n".join(
        [
            SHELL_BEGIN,
            SHELL_VERSION_MARKER,
            "# Managed by claude-keysmith. Do not edit by hand.",
            "# Effective NSFW / creative delivery depends on CLI append, not settings.json alone.",
            "# Resolves the Claude entry point per invocation (versioned-dir safe).",
            "claude() {",
            "  local entry",
            f'  entry="{claude_bin}"',
            '  if [ ! -f "$entry" ]; then',
            "    # Re-resolve the entry point per invocation (versioned-dir safe).",
            "    # `command -v claude` would resolve to this function, so disable it first.",
            "    disable -f claude 2>/dev/null || true",
            '    entry="$(command -v claude 2>/dev/null || true)"',
            "    enable -f claude 2>/dev/null || true",
            "  fi",
            '  if [ -n "$entry" ] && [ ! -f "$entry" ]; then',
            '    entry="$(command -v -p claude 2>/dev/null || true)"',
            "  fi",
            '  if [ -z "$entry" ] || [ ! -f "$entry" ]; then',
            '    echo "claude-keysmith: Claude Code entry point is unavailable; repair or reinstall Claude Code, then retry." >&2',
            "    return 127",
            "  fi",
            '  "$entry" \\',
            f'    --system-prompt-file "{system_prompt}" \\',
            f'    --append-system-prompt-file "{append_prompt}" \\',
            '    "$@"',
            "}",
            SHELL_END,
            "",
        ]
    )


def shell_block_pattern() -> re.Pattern:
    begin = re.escape(SHELL_BEGIN)
    end = re.escape(SHELL_END)
    return re.compile(rf"(?ms)^{begin}\n.*?^{end}\n?")


def _is_missing_literal_zsh_fast_path(raw: str) -> bool:
    """Accept only a missing absolute path with no zsh expansion semantics."""
    if not os.path.isabs(raw):
        return False
    if any(char in raw for char in ("$", "`", "\\")):
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        return False
    try:
        os.lstat(raw)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def shell_wrapper_is_current(content: str, expected_block: str, shell_kind: str = "") -> bool:
    match = shell_block_pattern().search(content)
    if not match:
        return False
    actual_block = match.group(0)
    if actual_block == expected_block:
        return True
    if shell_kind != "zsh":
        return False

    entry_pattern = re.compile(r'(?m)^  entry="([^"\n]+)"$')
    actual_entry = entry_pattern.search(actual_block)
    expected_entry = entry_pattern.search(expected_block)
    if not actual_entry or not expected_entry:
        return False
    if not _is_missing_literal_zsh_fast_path(actual_entry.group(1)):
        return False
    return entry_pattern.sub('  entry="<dynamic>"', actual_block, count=1) == entry_pattern.sub(
        '  entry="<dynamic>"', expected_block, count=1
    )


def ensure_shell_wrapper(content: str, block: str) -> Tuple[str, bool]:
    """Insert or replace the managed shell wrapper; also remove legacy bare wrapper."""
    updated = content
    changed = False

    # Remove legacy non-managed wrapper if present.
    legacy = LEGACY_WRAPPER_RE.search(updated)
    if legacy:
        updated = LEGACY_WRAPPER_RE.sub("", updated, count=1)
        changed = True

    pattern = shell_block_pattern()
    match = pattern.search(updated)
    if match:
        if match.group(0) == block:
            return updated, changed
        # A Windows path such as C:\Users must not be parsed as a regex replacement.
        return pattern.sub(lambda _match: block, updated, count=1), True

    prefix = updated
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + block, True


def remove_shell_wrapper(content: str) -> Tuple[str, bool]:
    pattern = shell_block_pattern()
    updated, count = pattern.subn("", content, count=1)
    legacy = LEGACY_WRAPPER_RE.search(updated)
    if legacy:
        updated = LEGACY_WRAPPER_RE.sub("", updated, count=1)
        return updated, True
    return updated, bool(count)


def load_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"settings 不是普通文件: {path}")
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"settings.json 顶层必须是 object: {path}")
    return data


def align_settings_system_prompt(settings: Dict[str, Any], system_body: str, max_tokens: Optional[int] = None) -> Tuple[Dict[str, Any], bool]:
    """Align settings.systemPrompt and optionally max_tokens. Do not invent dead env keys as the primary path.

    Notes from 2026-07-28 probe on Claude Code 2.1.204 + lgw:
      - settings.systemPrompt alone does not unlock hard NSFW
      - CLI --append-system-prompt[-file] is the effective creative-delivery layer
      - settings.appendSystemPrompt / appendSystemPromptFile were not honored in probe
    """
    changed = False
    desired = ensure_trailing_newline(system_body)
    if settings.get("systemPrompt") != desired:
        settings = dict(settings)
        settings["systemPrompt"] = desired
        changed = True
    # Keep optional dead env mirror only if already present, to avoid surprise drift.
    env = settings.get("env")
    if isinstance(env, dict) and "CLAUDE_CODE_SYSTEM_PROMPT" in env:
        if env.get("CLAUDE_CODE_SYSTEM_PROMPT") != desired:
            settings = dict(settings)
            new_env = dict(env)
            new_env["CLAUDE_CODE_SYSTEM_PROMPT"] = desired
            settings["env"] = new_env
            changed = True
    # Remove known-ineffective append keys if present, so status is honest.
    for dead in ("appendSystemPrompt", "appendSystemPromptFile"):
        if dead in settings:
            settings = dict(settings)
            settings.pop(dead, None)
            changed = True
    # Set max_tokens if provided
    if max_tokens is not None:
        if settings.get("max_tokens") != max_tokens:
            settings = dict(settings)
            settings["max_tokens"] = max_tokens
            changed = True
    return settings, changed


def write_settings(path: Path, settings: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(settings, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# JSON contract + durable journal/lock layer
# ---------------------------------------------------------------------------

JSON_SCHEMA = "claude-keysmith/v1"
JOURNAL_SCHEMA = "claude-keysmith-journal/v1"
BACKUP_NAME_RE = re.compile(r"^(?P<target>.+)\.bak_(?P<ts>\d{8}_\d{6})(?:_(?P<rest>.*))?$")
LOCK_STALE_AFTER_SECONDS = 3600
RECOVERY_MARKER_KEY = "claude-keysmith recovery marker"


class TransactionConflict(RuntimeError):
    """Raised when a scope-local mutation is already in progress."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path) -> Dict[str, Any]:
    """Before/after digest evidence for a path (missing files are legal)."""
    try:
        if path.is_file():
            return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size, "exists": True}
    except OSError:
        pass
    return {"sha256": None, "size_bytes": None, "exists": False}


def backup_evidence(target: Path, backup: Path) -> Dict[str, Any]:
    info = file_evidence(backup)
    return {
        "target": str(target),
        "backup_path": str(backup),
        "sha256": info["sha256"],
        "size_bytes": info["size_bytes"],
        "created": _backup_created_from_name(backup.name),
    }


def _backup_created_from_name(filename: str) -> Optional[str]:
    match = BACKUP_NAME_RE.match(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("ts"), "%Y%m%d_%H%M%S").isoformat()
    except ValueError:
        return None


def source_descriptor(kind: str, path: Path, content: Optional[str]) -> Dict[str, Any]:
    if content is None:
        return {"kind": kind, "path": str(path), "size_bytes": None, "sha256": None}
    raw = content.encode("utf-8")
    return {
        "kind": kind,
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows taskkill exit status is unreliable; accept alive on probe success.
        probe = os.popen(f'tasklist /FI "PID eq {pid}" /NH 2>nul')
        try:
            output = probe.read()
        finally:
            probe.close()
        return str(pid) in output
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def scope_lock_path(paths: ScopePaths) -> Path:
    return paths.keysmith_dir / ".keysmith.lock"


def scope_journal_dir(paths: ScopePaths) -> Path:
    return paths.keysmith_dir


class ScopeWriteLock:
    """Exclusive scope-local write lock (O_EXCL lockfile, stale-PID reclaim)."""

    def __init__(self, paths: ScopePaths, label: str = "") -> None:
        self.path = scope_lock_path(paths)
        self.label = label
        self.acquired = False
        self.reclaimed_stale = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                holder = self._read_holder()
                pid = holder.get("pid")
                stale_reason = None
                if pid is None or not isinstance(pid, int) or pid <= 0:
                    stale_reason = "lock holder metadata unreadable"
                elif not _pid_alive(pid):
                    stale_reason = f"lock holder pid {pid} is not running"
                if stale_reason is None:
                    owner = f"pid {pid}" if isinstance(pid, int) else "unknown pid"
                    raise TransactionConflict(
                        f"另一个 keysmith 写入正在进行（{owner}）；已按失败关闭处理，拒绝并发修改: {self.path}"
                    )
                try:
                    self.path.unlink()
                except OSError as exc:
                    raise TransactionConflict(f"无法回收失效的 keysmith 锁: {exc}") from exc
                self.reclaimed_stale = True
                continue
            except OSError as exc:
                raise TransactionConflict(f"无法创建 keysmith 写入锁: {exc}") from exc
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": JOURNAL_SCHEMA,
                        "pid": os.getpid(),
                        "label": self.label,
                        "acquired_at": _utc_now_iso(),
                    },
                    handle,
                )
            self.acquired = True
            return

    def _read_holder(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, UnicodeDecodeError):
            return {}

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.path.unlink()
        except OSError:
            pass
        self.acquired = False

    def __enter__(self) -> "ScopeWriteLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


class TransactionJournal:
    """Durable two-phase journal (pending -> committed) for scope mutations."""

    def __init__(self, paths: ScopePaths, operation: str) -> None:
        journal_dir = scope_journal_dir(paths)
        journal_dir.mkdir(parents=True, exist_ok=True)
        self.dir = journal_dir
        self.id = uuid.uuid4().hex
        self.path = journal_dir / f".journal-{self.id}.json"
        self.operation = operation
        self.state = "pending"
        self.committed = False
        self.record: Dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "journal_id": self.id,
            "operation": operation,
            "scope": paths.scope,
            "scope_root": str(paths.root),
            "pid": os.getpid(),
            "started_at": _utc_now_iso(),
            "state": "pending",
            "steps": [],
            "backups": [],
        }
        self._persist()

    def _persist(self) -> None:
        atomic_write_text(self.path, json.dumps(self.record, ensure_ascii=False, indent=2) + "\n")

    def log_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        entry = dict(step)
        entry.setdefault("at", _utc_now_iso())
        self.record["steps"].append(entry)
        self._persist()
        return entry

    def log_backup(self, entry: Dict[str, Any]) -> None:
        self.record["backups"].append(dict(entry))
        self._persist()

    def commit(self) -> None:
        self.state = "committed"
        self.committed = True
        self.record["state"] = "committed"
        self.record["committed_at"] = _utc_now_iso()
        self._persist()

    def abandon(self) -> None:
        """Drop the journal after a fully rolled-back failure (no residue)."""
        try:
            self.path.unlink()
        except OSError:
            pass

    def finish(self) -> None:
        """Drop a committed journal whose residual cleanup is a no-op.

        If removal fails the committed journal stays behind and the next write
        (or recover) consumes it after verifying there is nothing left to do.
        """
        if not self.committed:
            return
        try:
            self.path.unlink()
        except OSError:
            pass


def _step_matches(entry: Dict[str, Any], path: Path, action: str) -> bool:
    return entry.get("action") == action and Path(entry.get("path", "")) == path


def journal_backup_after(journal: TransactionJournal, step: Dict[str, Any], backup: Path) -> None:
    journal.log_backup(backup_evidence(Path(step["path"]), backup))


def journal_step_before(journal: TransactionJournal, action: str, path: Path, **extra: Any) -> Dict[str, Any]:
    step = {"action": action, "path": str(path), "before": file_evidence(path)}
    step.update(extra)
    # Return the exact entry stored in the journal so the matching after-state
    # update is persisted instead of mutating a detached copy.
    return journal.log_step(step)


def journal_step_after(journal: TransactionJournal, step: Dict[str, Any], **extra: Any) -> None:
    step["after"] = file_evidence(Path(step["path"]))
    step.update(extra)
    journal._persist()


def tx_backup_step(journal: TransactionJournal, path: Path, timestamp: str, suffix: str = "") -> Path:
    step = journal_step_before(journal, "backup", path)
    backup = backup_file(path, timestamp, suffix=suffix)
    journal_step_after(journal, step, backup_path=str(backup))
    journal_backup_after(journal, step, backup)
    return backup


def tx_write_step(journal: TransactionJournal, path: Path, content: str, *, is_settings: bool = False) -> None:
    step = journal_step_before(journal, "write", path)
    if is_settings:
        write_settings(path, json.loads(content))
    else:
        atomic_write_text(path, content)
    journal_step_after(journal, step)


def tx_remove_step(journal: TransactionJournal, path: Path) -> None:
    step = journal_step_before(journal, "remove", path)
    path.unlink()
    journal_step_after(journal, step)


def tx_migrate_legacy_launchers(journal: TransactionJournal, home: Path, timestamp: str) -> List[Tuple[Path, Path]]:
    migration_plan = plan_legacy_launcher_migration(home, timestamp)
    if not migration_plan:
        return []

    migration_items = [dict(item) for item in migration_plan]
    step = journal_step_before(
        journal,
        "migrate",
        home / ".local" / "bin",
        moved=[],
        migration_items=migration_items,
    )

    def record_moved(source: Path, backup: Path) -> None:
        step["moved"].append([str(source), str(backup)])
        journal._persist()

    moved = migrate_legacy_launchers(
        home,
        timestamp,
        migration_plan=migration_plan,
        on_moved=record_moved,
    )
    journal_step_after(journal, step)
    return moved


def _pending_rollback_core(
    record: Dict[str, Any], *, execute: bool
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Plan or execute one pending rollback through the same decision path.

    The virtual state is updated after every successful inverse step. This is
    required when one transaction writes the same path more than once: an
    earlier step must be checked against the state produced by rolling back the
    later step, not against the unchanged on-disk state used by a dry-run.
    """
    actions: List[Dict[str, Any]] = []
    blockers: List[str] = []
    virtual_evidence: Dict[str, Dict[str, Any]] = {}
    virtual_present: Dict[str, Optional[bool]] = {}
    virtual_bytes: Dict[str, bytes] = {}

    def report(action: str, path: Path, detail: str) -> None:
        actions.append({"action": action, "path": str(path), "detail": detail})

    def blocker(message: str) -> None:
        blockers.append(message)

    def state_key(path: Path) -> str:
        return _path_key(path)

    def current_evidence(path: Path) -> Dict[str, Any]:
        key = state_key(path)
        if key not in virtual_evidence:
            virtual_evidence[key] = file_evidence(path)
        return virtual_evidence[key]

    def current_present(path: Path) -> Optional[bool]:
        key = state_key(path)
        if key not in virtual_present:
            try:
                virtual_present[key] = os.path.lexists(str(path))
            except OSError as exc:
                virtual_present[key] = None
                blocker(f"无法检查回滚目标状态 {path}: {exc}")
        return virtual_present[key]

    def remember_state(
        path: Path,
        evidence: Dict[str, Any],
        *,
        present: bool,
        raw: Optional[bytes] = None,
    ) -> None:
        key = state_key(path)
        virtual_evidence[key] = dict(evidence)
        virtual_present[key] = present
        if raw is None:
            virtual_bytes.pop(key, None)
        else:
            virtual_bytes[key] = raw

    def evidence_exists(evidence: Dict[str, Any]) -> bool:
        if "exists" in evidence:
            return bool(evidence.get("exists"))
        return evidence.get("sha256") is not None

    def matches_state(path: Path, expected: Dict[str, Any]) -> bool:
        present = current_present(path)
        if present is None:
            return False
        if not evidence_exists(expected):
            return not present
        current = current_evidence(path)
        return (
            present
            and bool(current.get("exists"))
            and current.get("sha256") == expected.get("sha256")
        )

    def read_current_bytes(path: Path) -> bytes:
        key = state_key(path)
        if key in virtual_bytes:
            return virtual_bytes[key]
        raw = path.read_bytes()
        virtual_bytes[key] = raw
        return raw

    def verified_restore_source(
        path: Path, before: Dict[str, Any], backup_str: Optional[str]
    ) -> Optional[Tuple[Path, bytes]]:
        expected_sha = before.get("sha256")
        if expected_sha is None:
            blocker(f"缺少事务前指纹，无法确认回滚内容: {path}")
            return None

        candidates: List[Path] = []
        if backup_str:
            candidates.append(Path(backup_str))
        try:
            candidates.extend(
                sorted(
                    path.parent.glob(f"{path.name}.bak_*"),
                    key=lambda item: item.name,
                    reverse=True,
                )
            )
        except OSError as exc:
            blocker(f"无法枚举备份，回滚受阻 {path}: {exc}")
            return None

        seen = set()
        for candidate in candidates:
            candidate_key = state_key(candidate)
            if candidate_key in seen:
                continue
            seen.add(candidate_key)
            evidence = current_evidence(candidate)
            if (
                not current_present(candidate)
                or not evidence.get("exists")
                or evidence.get("sha256") != expected_sha
            ):
                continue
            try:
                raw = read_current_bytes(candidate)
            except OSError as exc:
                blocker(f"无法读取已验证备份 {candidate}: {exc}")
                return None
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                blocker(f"备份在恢复检查期间发生变化，拒绝使用: {candidate}")
                return None
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                blocker(f"回滚备份不是有效 UTF-8 文本 {candidate}: {exc}")
                return None
            return candidate, raw

        blocker(f"找不到匹配事务前指纹的备份，回滚受阻: {path}")
        return None

    def restore_prior_state(
        path: Path, before: Dict[str, Any], backup_str: Optional[str]
    ) -> None:
        if not evidence_exists(before):
            if execute:
                try:
                    path.unlink()
                except OSError as exc:
                    blocker(f"无法移除事务新建文件 {path}: {exc}")
                    return
            remember_state(
                path,
                {"sha256": None, "size_bytes": None, "exists": False},
                present=False,
            )
            report("remove", path, "removed file created by interrupted transaction")
            return

        verified = verified_restore_source(path, before, backup_str)
        if verified is None:
            return
        backup_path, raw = verified
        if execute:
            try:
                atomic_write_text(path, raw.decode("utf-8"))
            except OSError as exc:
                blocker(f"回滚失败 {path}: {exc}")
                return
        remember_state(path, before, present=True, raw=raw)
        report("restore", path, f"restored prior content from {backup_path.name}")

    steps = list(record.get("steps", []))
    for step in reversed(steps):
        action = step.get("action")
        if action == "migrate":
            migration_items = step.get("migration_items")
            if isinstance(migration_items, list):
                for item in reversed(migration_items):
                    if not isinstance(item, dict):
                        blocker("迁移事务证据格式无效，拒绝回滚")
                        continue
                    source = Path(item.get("source", ""))
                    backup = Path(item.get("backup", ""))
                    before = item.get("before") or {}
                    expected_sha = before.get("sha256")
                    if not source.name or not backup.name or expected_sha is None:
                        blocker(f"迁移事务缺少路径或源指纹，拒绝回滚: {source}")
                        continue

                    source_present = current_present(source)
                    backup_present = current_present(backup)
                    if source_present is None or backup_present is None:
                        continue

                    if source_present:
                        try:
                            source_regular = source.is_file() and not source.is_symlink()
                        except OSError as exc:
                            blocker(f"无法检查迁移回滚目标类型 {source}: {exc}")
                            continue
                        if not source_regular or not matches_state(source, before):
                            blocker(f"迁移源被未知方修改或替换，拒绝回滚: {source}")
                            continue
                        if not backup_present:
                            continue  # move never happened, or was already rolled back
                        try:
                            backup_regular = backup.is_file() and not backup.is_symlink()
                        except OSError as exc:
                            blocker(f"无法检查迁移备份类型 {backup}: {exc}")
                            continue
                        if not backup_regular or not matches_state(backup, before):
                            blocker(f"迁移备份状态异常，拒绝清理: {backup}")
                            continue
                        if not _same_posix_file_identity(source, backup):
                            blocker(f"迁移源与备份同时存在且身份不同，拒绝清理: {backup}")
                            continue
                        if execute:
                            try:
                                backup.unlink()
                            except OSError as exc:
                                blocker(f"无法清理已回滚的迁移备份 {backup}: {exc}")
                                continue
                        remember_state(
                            backup,
                            {"sha256": None, "size_bytes": None, "exists": False},
                            present=False,
                        )
                        report("cleanup", backup, "removed duplicate backup from interrupted migration")
                        continue

                    if not backup_present:
                        blocker(f"迁移源与备份均缺失，无法回滚: {source}")
                        continue
                    try:
                        backup_regular = backup.is_file() and not backup.is_symlink()
                    except OSError as exc:
                        blocker(f"无法检查迁移备份类型 {backup}: {exc}")
                        continue
                    if not backup_regular or not matches_state(backup, before):
                        blocker(f"迁移备份指纹不匹配，拒绝回滚: {backup}")
                        continue
                    try:
                        backup_raw = read_current_bytes(backup)
                    except OSError as exc:
                        blocker(f"无法读取迁移备份 {backup}: {exc}")
                        continue
                    if hashlib.sha256(backup_raw).hexdigest() != expected_sha:
                        blocker(f"迁移备份在恢复检查期间发生变化，拒绝使用: {backup}")
                        continue
                    if execute:
                        try:
                            _move_file_no_overwrite(backup, source)
                        except OSError as exc:
                            blocker(f"迁移回滚失败 {source}: {exc}")
                            continue
                    remember_state(source, before, present=True, raw=backup_raw)
                    remember_state(
                        backup,
                        {"sha256": None, "size_bytes": None, "exists": False},
                        present=False,
                    )
                    report("restore-moved", source, f"restored from {backup.name}")
                continue

            # Compatibility path for journals created before migration intent
            # and source fingerprints were persisted.
            for source_str, backup_str in reversed(step.get("moved", [])):
                source = Path(source_str)
                backup = Path(backup_str)
                source_present = current_present(source)
                if source_present is None:
                    continue
                if source_present:
                    backup_present = current_present(backup)
                    if backup_present is None:
                        continue
                    if backup_present and _same_posix_file_identity(source, backup):
                        if execute:
                            try:
                                backup.unlink()
                            except OSError as exc:
                                blocker(f"无法清理旧格式迁移恢复残留 {backup}: {exc}")
                                continue
                        remember_state(
                            backup,
                            {"sha256": None, "size_bytes": None, "exists": False},
                            present=False,
                        )
                        report("cleanup", backup, "removed duplicate backup from interrupted legacy-journal recovery")
                        continue
                    blocker(f"回滚目标已存在，拒绝覆盖: {source}")
                    continue
                backup_present = current_present(backup)
                if backup_present is None:
                    continue
                if not backup_present:
                    blocker(f"迁移备份缺失，无法回滚: {backup}")
                    continue
                backup_evidence = current_evidence(backup)
                try:
                    backup_raw = read_current_bytes(backup)
                except OSError:
                    backup_raw = None
                if execute:
                    try:
                        _move_file_no_overwrite(backup, source)
                    except OSError as exc:
                        blocker(f"迁移回滚失败 {source}: {exc}")
                        continue
                remember_state(
                    source,
                    backup_evidence,
                    present=True,
                    raw=backup_raw,
                )
                remember_state(
                    backup,
                    {"sha256": None, "size_bytes": None, "exists": False},
                    present=False,
                )
                report("restore-moved", source, f"restored from {backup.name}")
            continue

        path = Path(step.get("path", ""))
        before = step.get("before") or {}
        after = step.get("after") or {}
        if action == "backup":
            continue  # evidence only

        backup_str = step.get("backup_path")

        if action == "write":
            if not after:
                # Crash before/during the write; treat as not yet applied when the
                # file still matches the before state.
                if matches_state(path, before):
                    continue
                restore_prior_state(path, before, backup_str)
                continue
            if matches_state(path, after):
                restore_prior_state(path, before, backup_str)
                continue
            if matches_state(path, before):
                continue  # never applied, or already rolled back
            blocker(f"未知修改（事务后指纹不匹配），拒绝回滚: {path}")
        elif action == "remove":
            if not after:
                if matches_state(path, before):
                    continue  # removal never happened
                restore_prior_state(path, before, backup_str)
                continue
            if current_present(path):
                if matches_state(path, before):
                    continue  # already rolled back
                blocker(f"文件被未知方重建，拒绝覆盖: {path}")
                continue
            restore_prior_state(path, before, backup_str)
        else:
            blocker(f"未知事务步骤类型 {action!r}: {path}")
    return actions, blockers


def rollback_pending_journal(record: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Roll back a pending (never-committed) journal to the prior state."""
    return _pending_rollback_core(record, execute=True)


def plan_pending_rollback(record: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Dry-run of :func:`rollback_pending_journal`; never mutates the filesystem."""
    return _pending_rollback_core(record, execute=False)


def finish_committed_journal(record: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Post-commit recovery: only residual cleanup, never reverse the result."""
    actions: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for step in record.get("steps", []):
        if step.get("action") != "migrate":
            continue
        migration_items = step.get("migration_items")
        if isinstance(migration_items, list):
            for item in migration_items:
                if not isinstance(item, dict):
                    blockers.append("已提交事务的迁移证据格式无效，保留并报告")
                    continue
                source_raw = item.get("source")
                backup_raw = item.get("backup")
                before = item.get("before") or {}
                if not source_raw or not backup_raw or before.get("sha256") is None:
                    blockers.append("已提交事务的迁移证据不完整，保留并报告")
                    continue
                source = Path(source_raw)
                backup = Path(backup_raw)
                if os.path.lexists(str(source)):
                    blockers.append(f"已提交事务的迁移目标被重建，保留并报告: {source}")
                if not _migration_item_matches(backup, before):
                    blockers.append(f"已提交事务的迁移备份指纹异常，保留并报告: {backup}")
            continue
        for source_str, _backup_str in step.get("moved", []):
            source = Path(source_str)
            if os.path.lexists(str(source)):
                blockers.append(f"已提交事务的迁移目标被重建，保留并报告: {source}")
    if not blockers:
        actions.append({"action": "cleanup", "path": record.get("scope_root", ""), "detail": "committed transaction verified; no residual cleanup required"})
    return actions, blockers


def find_journals(paths: ScopePaths) -> List[Path]:
    directory = scope_journal_dir(paths)
    try:
        if not directory.is_dir():
            return []
        return sorted(directory.glob(".journal-*.json"))
    except OSError:
        return []


def load_journal(path: Path) -> Optional[Dict[str, Any]]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _atomic_temp_directories(paths: ScopePaths) -> List[Path]:
    """Directories where scope-owned atomic writes can leave crash residue."""
    directories = {paths.memory_file.parent, paths.keysmith_dir}
    if paths.scope == "user":
        home = resolve_home()
        directories.add(home)
        directories.add(home / ".claude")
        shell_rc_override = os.environ.get("CLAUDE_KEYSMITH_SHELL_RC")
        if shell_rc_override:
            directories.add(Path(shell_rc_override).expanduser().parent)
        else:
            try:
                directories.add(user_runtime_paths()["shell_rc"].parent)
            except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass
    return sorted(directories, key=lambda item: str(item))


def find_atomic_temp_residue(paths: ScopePaths) -> Tuple[List[Path], List[str]]:
    """Find only temp files reserved by :func:`atomic_write_text`."""
    residue: List[Path] = []
    blockers: List[str] = []
    for directory in _atomic_temp_directories(paths):
        try:
            entries = list(directory.iterdir())
        except FileNotFoundError:
            continue
        except OSError as exc:
            blockers.append(f"无法检查原子写临时残留目录 {directory}: {exc}")
            continue
        for entry in entries:
            name = entry.name
            if name.startswith(".") and ATOMIC_TEMP_MARKER in name and name.endswith(".tmp"):
                residue.append(entry)
    residue.sort(key=lambda item: str(item))
    return residue, blockers


def inspect_recovery_state(paths: ScopePaths) -> Dict[str, Any]:
    journals: List[Dict[str, Any]] = []
    conflicts: List[str] = []
    for journal_path in find_journals(paths):
        record = load_journal(journal_path)
        if record is None:
            conflicts.append(f"journal 损坏无法解析: {journal_path}")
            continue
        journals.append(
            {
                "journal_path": str(journal_path),
                "journal_id": record.get("journal_id"),
                "operation": record.get("operation"),
                "state": record.get("state"),
                "started_at": record.get("started_at"),
                "pid": record.get("pid"),
            }
        )
    atomic_temp_files, atomic_temp_blockers = find_atomic_temp_residue(paths)
    conflicts.extend(atomic_temp_blockers)
    lock_path = scope_lock_path(paths)
    lock_present = lock_path.exists()
    live_lock = False
    if lock_present:
        try:
            holder = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            holder = {}
        pid = holder.get("pid") if isinstance(holder, dict) else None
        live_lock = bool(isinstance(pid, int) and pid > 0 and _pid_alive(pid))
    return {
        "journals": journals,
        "journal_count": len(journals),
        "atomic_temp_files": [str(path) for path in atomic_temp_files],
        "atomic_temp_count": len(atomic_temp_files),
        "conflicts": conflicts,
        "lock_present": lock_present,
        "lock_live": live_lock,
        "recovery_required": bool(journals or atomic_temp_files or conflicts),
        "must_recover_before_writes": bool(journals or atomic_temp_files or conflicts),
    }


def enumerate_scope_backups(paths: ScopePaths, include_runtime: bool = True) -> List[Dict[str, Any]]:
    """Enumerate keysmith-created backups (*.bak_*) for a scope, verified parseable."""
    entries: List[Dict[str, Any]] = []
    seen = set()

    def collect(directory: Path, kind: str) -> None:
        try:
            candidates = sorted(directory.glob("*.bak_*"))
        except OSError:
            return
        for candidate in candidates:
            match = BACKUP_NAME_RE.match(candidate.name)
            if match is None or not candidate.is_file():
                continue
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            info = file_evidence(candidate)
            target = candidate.parent / match.group("target")
            entries.append(
                {
                    "backup_path": str(candidate),
                    "target_name": match.group("target"),
                    "target_path": str(target),
                    "sha256": info["sha256"],
                    "size_bytes": info["size_bytes"],
                    "created": _backup_created_from_name(candidate.name),
                    "kind": kind,
                }
            )

    collect(paths.root, "memory")
    collect(paths.keysmith_dir, "instruction")
    if include_runtime and paths.scope == "user":
        rt = user_runtime_paths()
        collect(rt["keysmith_dir"], "runtime")
        collect(rt["shell_rc"].parent, "shell_rc")
        legacy_dir = rt["home"] / ".local" / "bin"
        collect(legacy_dir, "legacy_launcher")
    entries.sort(key=lambda item: (item["backup_path"]))
    return entries


def is_keysmith_backup_for_target(target: Path, backup: Path) -> bool:
    match = BACKUP_NAME_RE.match(backup.name)
    if match is None:
        return False
    if match.group("target") != target.name:
        return False
    try:
        backup.parent.resolve().relative_to(target.parent.resolve())
    except ValueError:
        return False
    return backup.is_file()


def recovery_marker_path(paths: ScopePaths) -> Path:
    return paths.keysmith_dir / ".recovery-marker.json"


def _load_json_object(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _runtime_recovery_marker_present(paths: ScopePaths) -> bool:
    present, _settings_path, _settings, _blocker = _runtime_recovery_marker_status(paths)
    return present


def _runtime_recovery_marker_status(
    paths: ScopePaths,
) -> Tuple[bool, Path, Optional[Dict[str, Any]], Optional[str]]:
    """Return marker presence and the exact alignment verdict used by recover."""
    settings_path = resolve_home() / ".claude" / "settings.json"
    if paths.scope != "user":
        return False, settings_path, None, None
    try:
        settings = load_settings(settings_path)
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False, settings_path, None, None
    if not settings.get(RECOVERY_MARKER_KEY):
        return False, settings_path, settings, None

    system_prompt = paths.keysmith_dir / "system-prompt.md"
    try:
        system_body = read_text_if_exists(system_prompt) if system_prompt.is_file() else ""
    except (OSError, UnicodeDecodeError) as exc:
        return (
            True,
            settings_path,
            settings,
            f"无法验证 settings.systemPrompt 恢复对齐状态: {exc}",
        )
    if system_body and settings.get("systemPrompt") == system_body:
        return True, settings_path, settings, None
    return (
        True,
        settings_path,
        settings,
        "settings.systemPrompt 与 system-prompt.md 不一致；请先用 backups 选择受控备份执行 restore，再运行 recover",
    )


def _blockers_for_recovery_residue(paths: ScopePaths, fresh_lock: Optional[ScopeWriteLock] = None) -> List[str]:
    """Fail-closed write gate.

    A *pending* journal always blocks. A *committed* journal blocks only when a
    recovery sweep determines it needs residual cleanup; if the sweep is clean
    the journal is consumed (crash-after-commit / Ctrl+C window) and the write
    proceeds. ``fresh_lock`` must be a lock this process just acquired, so the
    sweep cannot tear down a concurrent live writer.
    """
    blockers: List[str] = []
    atomic_temp_files, atomic_temp_blockers = find_atomic_temp_residue(paths)
    blockers.extend(atomic_temp_blockers)
    if atomic_temp_files:
        blockers.append(
            f"检测到 {len(atomic_temp_files)} 个原子写临时残留；请先运行 recover 完成清理"
        )
    for journal_path in find_journals(paths):
        record = load_journal(journal_path)
        if record is None:
            blockers.append(f"journal 损坏无法解析，已保留证据: {journal_path}")
            continue
        if record.get("state") != "committed":
            blockers.append(
                f"检测到未完成的事务 {record.get('journal_id')}（operation={record.get('operation')}, "
                f"state={record.get('state')}）；请先运行 recover 完成恢复"
            )
            continue
        actions, finish_blockers = finish_committed_journal(record)
        if finish_blockers:
            blockers.extend(finish_blockers)
            blockers.append(f"已提交事务 {record.get('journal_id')} 需要 recover 完成收尾清理")
            continue
        # Residual cleanup is a no-op: consume the journal (crash-after-commit window).
        try:
            journal_path.unlink()
        except OSError:
            blockers.append(f"无法清理已完成的 journal {journal_path}；请运行 recover")
    if fresh_lock is not None and fresh_lock.reclaimed_stale:
        # A stale lock means the previous holder died mid-transaction; run the
        # same sweep under our fresh lock before allowing new writes.
        blockers.extend(_blockers_for_recovery_residue(paths))
    if _runtime_recovery_marker_present(paths):
        blockers.append("settings.json 标记了未完成的恢复（systemPrompt 回滚待确认）；请先运行 recover")
    return list(dict.fromkeys(blockers))


def _emit_json_or_error(args: Any, build, printer=None) -> int:
    """Run build()->(ok, payload, exit_status); emit JSON or text, fail closed."""
    use_json = bool(getattr(args, "json", False))
    try:
        ok, payload, exit_status = build()
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with a clean error
        message = str(exc)
        if use_json:
            payload = {
                "schema": JSON_SCHEMA,
                "operation": getattr(args, "command", "unknown"),
                "mode": "preview" if preview_header_mode(args) else "execute",
                "ok": False,
                "error": message,
                "exit_status": 1,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"[错误] {message}")
        return 1
    if use_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif printer is not None:
        printer(ok, payload, exit_status)
    return exit_status


def preview_header_mode(args: Any) -> bool:
    """Same precedence as preview_header but silent (no text side effects)."""
    explicit_dry_run = bool(getattr(args, "dry_run", False))
    return explicit_dry_run or not getattr(args, "yes", False)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"max-tokens 必须是正整数，收到: {value!r}")
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"max-tokens 必须是正整数（>0），收到: {parsed}")
    return parsed


def _write_command_error(args: Any, operation: str, message: str, extra: Optional[Dict[str, Any]] = None) -> int:
    """Fail closed with a clean error in the caller's selected output mode."""
    if getattr(args, "json", False):
        payload = {
            "schema": JSON_SCHEMA,
            "operation": operation,
            "mode": "preview" if preview_header_mode(args) else "execute",
            "ok": False,
            "error": message,
            "blockers": [message],
            "warnings": [],
            "actions": [],
            "backups": [],
            "reload_required": False,
            "reload_hint": None,
            "exit_status": 1,
        }
        if extra:
            payload.update(extra)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[错误] {message}")
    return 1


def _write_report_base(operation: str, args: Any, paths: Optional[ScopePaths], name: Optional[str]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "schema": JSON_SCHEMA,
        "operation": operation,
        "mode": "preview" if preview_header_mode(args) else "execute",
        "ok": True,
        "scope": paths.scope if paths else getattr(args, "scope", None),
        "name": name,
        "target": {},
        "actions": [],
        "warnings": [],
        "blockers": [],
        "backups": [],
        "reload_required": False,
        "reload_hint": None,
        "exit_status": 0,
        "error": None,
    }
    return report


def _add_action(report: Dict[str, Any], action: str, path: Any, detail: str) -> None:
    report["actions"].append({"action": action, "path": str(path), "detail": detail})


def _planned_backup(report: Dict[str, Any], target: Path) -> None:
    info = file_evidence(target)
    report["backups"].append(
        {
            "target": str(target),
            "backup_path": None,
            "sha256": info["sha256"],
            "size_bytes": info["size_bytes"],
            "created": None,
            "planned": True,
        }
    )


def _actual_backup(report: Dict[str, Any], target: Path, backup: Path) -> None:
    report["backups"].append(backup_evidence(target, backup))


def command_install(args) -> int:
    use_json = bool(getattr(args, "json", False))
    try:
        md_filename = normalize_md_name(args.name)
        name = marker_name(md_filename)
        paths = resolve_scope(args.scope, args.project_dir)
        instruction_content = load_instruction_content(args.file)
        current_memory = read_text_if_exists(paths.memory_file)
        updated_memory, memory_changed = ensure_import_block(
            current_memory, name, paths.import_target(md_filename)
        )
        runtime = bool(getattr(args, "runtime", False))
        if runtime and paths.scope != "user":
            raise ValueError("--runtime 仅支持 --scope user（需要写入 ~/.claude 与 shell wrapper）")
        max_tokens = getattr(args, "max_tokens", None)
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("--max-tokens 必须是正整数（>0）")
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _write_command_error(args, "install", str(exc))

    report = _write_report_base("install", args, paths, name)
    report["target"] = {
        "memory_file": str(paths.memory_file),
        "instruction_file": str(paths.instruction_file(md_filename)),
        "import_target": paths.import_target(md_filename),
    }
    instruction_source = Path(args.file).expanduser().resolve() if args.file else DEFAULT_EXAMPLE
    report["source"] = source_descriptor(
        "external" if args.file else "bundled", instruction_source, instruction_content
    )

    # Fail-closed recovery gate: only enforce once we know this run will write.
    # Preview runs never touch the filesystem and stay side-effect free.
    if not preview_header_mode(args):
        residue_blockers = _blockers_for_recovery_residue(paths)
        if residue_blockers:
            return _write_command_error(
                args,
                "install",
                "; ".join(residue_blockers),
                extra={"scope": paths.scope, "name": name, "target": report["target"]},
            )

    preview_only = preview_header_mode(args) if use_json else preview_header(args)
    if not use_json:
        describe_scope(paths, md_filename)
        print(f"memory change: {'yes' if memory_changed else 'no'}")
        print(f"instruction bytes: {len(instruction_content.encode('utf-8'))}")
        print(f"runtime inject: {'yes' if runtime else 'no'}")

    instruction_path = paths.instruction_file(md_filename)
    if not use_json:
        if instruction_path.exists():
            print("existing instruction file: yes (will back up before overwrite)")
        else:
            print("existing instruction file: no")

    if paths.memory_file.exists():
        _add_action(report, "backup", paths.memory_file, "back up existing memory file before overwrite")
    _add_action(report, "write", paths.memory_file, "install/update managed import block" if memory_changed else "managed import block already current")
    if instruction_path.exists():
        _add_action(report, "backup", instruction_path, "back up existing instruction file before overwrite")
    _add_action(report, "write", instruction_path, "write keysmith instruction file")

    runtime_plan: Optional[Dict[str, Any]] = None
    if runtime:
        try:
            rt = user_runtime_paths()
            append_content = load_append_content(getattr(args, "append_file", None))
            system_body = strip_markdown_h1(instruction_content)
            settings = load_settings(rt["settings"])
            settings_updated, settings_changed = align_settings_system_prompt(settings, system_body, max_tokens)
            if rt["legacy_launcher_conflict"]:
                conflicts = ", ".join(rt["legacy_launcher_conflict_paths"])
                raise ValueError(
                    "检测到未知 Windows launcher，拒绝在任何写入前继续: " + conflicts
                )
            shell_block = render_shell_wrapper(
                rt["claude_bin"],
                rt["system_prompt"],
                rt["append_prompt"],
                rt["shell_kind"],
                rt["upstream_candidates"],
            )
            shell_rc_current = read_text_if_exists(rt["shell_rc"])
            shell_rc_updated, shell_rc_changed = ensure_shell_wrapper(shell_rc_current, shell_block)
            runtime_plan = {
                "paths": rt,
                "system_body": system_body,
                "append_content": append_content,
                "settings": settings_updated,
                "settings_changed": settings_changed,
                "shell_rc_updated": shell_rc_updated,
                "shell_rc_changed": shell_rc_changed,
                "shell_block": shell_block,
            }
            if not use_json:
                print(f"shell kind: {rt['shell_kind']}")
                print(f"upstream path: {rt['upstream_path'] or 'unavailable'}")
                print(f"upstream exists: {'yes' if rt['upstream_exists'] else 'no'}")
                print(f"system-prompt file: {rt['system_prompt']}")
                print(f"append-prompt file: {rt['append_prompt']}")
                print(f"settings.json: {rt['settings']}")
                print(f"settings.systemPrompt change: {'yes' if settings_changed else 'no'}")
                print(f"shell wrapper ({rt['shell_rc'].name}) change: {'yes' if shell_rc_changed else 'no'}")
                print(f"system-prompt bytes: {len(system_body.encode('utf-8'))}")
                print(f"append-prompt bytes: {len(append_content.encode('utf-8'))}")
                if max_tokens is not None:
                    print(f"max_tokens: {max_tokens}")
                if rt["legacy_launcher_detected"]:
                    print("legacy Windows launcher: recognized (will migrate with --yes)")
                    for legacy_path in rt["legacy_launcher_paths"]:
                        print(f"  - {legacy_path}")
        except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _write_command_error(args, "install", f"runtime 准备失败: {exc}")

        append_source = (
            Path(args.append_file).expanduser().resolve()
            if getattr(args, "append_file", None)
            else DEFAULT_APPEND_EXAMPLE
        )
        report["target"].update(
            {
                "system_prompt_file": str(rt["system_prompt"]),
                "append_prompt_file": str(rt["append_prompt"]),
                "settings_file": str(rt["settings"]),
                "shell_rc": str(rt["shell_rc"]),
                "shell_kind": rt["shell_kind"],
                "upstream_path": rt["upstream_path"],
                "upstream_exists": rt["upstream_exists"],
            }
        )
        report["sources"] = {
            "system_prompt": source_descriptor("bundled", instruction_source, runtime_plan["system_body"]),
            "append": source_descriptor(
                "external" if getattr(args, "append_file", None) else "bundled",
                append_source,
                runtime_plan["append_content"],
            ),
        }
        for path, detail in [
            (rt["system_prompt"], "write system-prompt.md"),
            (rt["append_prompt"], "write append-prompt.md"),
        ]:
            if path.exists():
                _add_action(report, "backup", path, f"back up existing {path.name} before overwrite")
            _add_action(report, "write", path, detail)
        if rt["settings"].exists():
            _add_action(report, "backup", rt["settings"], "back up settings.json before alignment")
        _add_action(report, "align-settings", rt["settings"], "align settings.systemPrompt" + (" and max_tokens" if max_tokens is not None else ""))
        if rt["shell_rc"].exists():
            _add_action(report, "backup", rt["shell_rc"], "back up shell profile before wrapper install")
        _add_action(report, "install-wrapper", rt["shell_rc"], "install/update managed shell wrapper" if shell_rc_changed else "managed shell wrapper already current")
        if rt["legacy_launcher_detected"]:
            _add_action(report, "migrate", rt["home"] / ".local" / "bin", "migrate recognized legacy Windows launcher pair")
        report["reload_required"] = True
        report["reload_hint"] = ". $PROFILE" if rt["shell_kind"] == "powershell" else "source ~/.zshrc"
        if not rt["upstream_exists"]:
            report["warnings"].append("Claude Code upstream entry point not found; wrapper will wait/re-resolve at runtime")
        report["runtime"] = collect_runtime_status(paths, md_filename, planned=runtime_plan)

    if preview_only:
        for target, will_backup in [
            (paths.memory_file, paths.memory_file.exists()),
            (instruction_path, instruction_path.exists()),
        ]:
            if will_backup:
                _planned_backup(report, target)
        if runtime_plan is not None:
            rt = runtime_plan["paths"]
            for path in (rt["system_prompt"], rt["append_prompt"], rt["settings"], rt["shell_rc"]):
                if path.exists():
                    _planned_backup(report, path)
        report["mode"] = "preview"
        if use_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # Execute phase: exclusive scope lock + durable journal.
    try:
        lock = ScopeWriteLock(paths, label=f"install:{name}")
        lock.acquire()
    except TransactionConflict as exc:
        return _write_command_error(args, "install", str(exc))

    try:
        # Re-check residue under the lock; a stale lock we reclaimed means the
        # previous holder died mid-transaction and its journal must settle first.
        residue_blockers = _blockers_for_recovery_residue(paths, fresh_lock=lock)
        if residue_blockers:
            raise TransactionConflict("; ".join(residue_blockers))
    except TransactionConflict as exc:
        lock.release()
        return _write_command_error(args, "install", str(exc))

    journal: Optional[TransactionJournal] = None
    moved_launchers: List[Tuple[Path, Path]] = []
    executed: List[Tuple[str, Path, Optional[Path]]] = []
    try:
        journal = TransactionJournal(paths, "install")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if paths.memory_file.exists():
            backup = tx_backup_step(journal, paths.memory_file, timestamp)
            _actual_backup(report, paths.memory_file, backup)
            if not use_json:
                print(f"[备份] {paths.memory_file.name} → {backup.name}")
        if instruction_path.exists():
            backup = tx_backup_step(journal, instruction_path, timestamp)
            _actual_backup(report, instruction_path, backup)
            if not use_json:
                print(f"[备份] {instruction_path.name} → {backup.name}")

        tx_write_step(journal, instruction_path, ensure_trailing_newline(instruction_content))
        executed.append(("write", instruction_path, None))
        if not use_json:
            print(f"[写入] {instruction_path}")
        tx_write_step(journal, paths.memory_file, updated_memory)
        executed.append(("write", paths.memory_file, None))
        if not use_json:
            print(f"[写入] {paths.memory_file}")

        if runtime_plan is not None:
            rt = runtime_plan["paths"]
            for path, content in [
                (rt["system_prompt"], runtime_plan["system_body"]),
                (rt["append_prompt"], runtime_plan["append_content"]),
            ]:
                if path.exists():
                    backup = tx_backup_step(journal, path, timestamp)
                    _actual_backup(report, path, backup)
                    if not use_json:
                        print(f"[备份] {path.name} → {backup.name}")
                tx_write_step(journal, path, content)
                executed.append(("write", path, None))
                if not use_json:
                    print(f"[写入] {path}")

            if rt["settings"].exists():
                backup = tx_backup_step(journal, rt["settings"], timestamp, suffix="pre_runtime")
                _actual_backup(report, rt["settings"], backup)
                if not use_json:
                    print(f"[备份] {rt['settings'].name} → {backup.name}")
            settings_text = json.dumps(runtime_plan["settings"], ensure_ascii=False, indent=2) + "\n"
            tx_write_step(journal, rt["settings"], settings_text)
            executed.append(("write", rt["settings"], None))
            if not use_json:
                print(f"[写入] {rt['settings']} (systemPrompt aligned; token/base URL untouched)")

            if rt["shell_rc"].exists():
                backup = tx_backup_step(journal, rt["shell_rc"], timestamp, suffix="pre_runtime")
                _actual_backup(report, rt["shell_rc"], backup)
                if not use_json:
                    print(f"[备份] {rt['shell_rc'].name} → {backup.name}")
            tx_write_step(journal, rt["shell_rc"], runtime_plan["shell_rc_updated"])
            executed.append(("write", rt["shell_rc"], None))
            if not use_json:
                print(f"[写入] {rt['shell_rc']} (managed claude wrapper)")

            # Keep the old PATH launchers available until every runtime file is durable.
            if rt["legacy_launcher_detected"]:
                try:
                    moved_launchers = tx_migrate_legacy_launchers(journal, rt["home"], timestamp)
                except (OSError, ValueError) as exc:
                    raise RuntimeError(f"旧 Windows launcher 迁移失败: {exc}") from exc
                for source, backup in moved_launchers:
                    _actual_backup(report, source, backup)
                    if not use_json:
                        print(f"[迁移] {source} → {backup}")

            if not use_json:
                if rt["shell_kind"] == "powershell":
                    print("[提示] 新开一个 PowerShell，或执行: . $PROFILE")
                else:
                    print("[提示] 新开一个 shell，或执行: source ~/.zshrc")
                print("[提示] 有效路径是 CLI --system-prompt-file + --append-system-prompt-file；模型建议 claude-opus-5。")

        journal.commit()
        journal.finish()
    except BaseException as exc:
        rollback_errors: List[str] = []
        if journal is not None and not journal.committed:
            actions, blockers = rollback_pending_journal(journal.record)
            rollback_errors.extend(blockers)
            if not blockers:
                journal.abandon()
        if rollback_errors:
            message = f"install 失败且回滚不完整: {exc}; {'; '.join(rollback_errors)}"
        else:
            message = f"install 失败，已回滚到之前的状态: {exc}"
        lock.release()
        return _write_command_error(args, "install", message)
    finally:
        if lock.acquired:
            lock.release()

    report["mode"] = "execute"
    report["journal_id"] = journal.id if journal else None
    if not use_json:
        print("[完成] install 已完成。")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def collect_runtime_status(paths: ScopePaths, md_filename: str, planned: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Structured runtime status for user scope.

    When ``planned`` is given (install preview), report what the runtime layout
    would look like after the planned install instead of current on-disk state.
    """
    rt = user_runtime_paths()
    instruction_path = paths.instruction_file(md_filename)
    if planned is not None:
        shell_rc_content = planned["shell_rc_updated"]
        settings = planned["settings"]
        system_body = planned["system_body"]
        system_exists = True
        append_exists = True
        system_complete = bool(system_body.strip())
        append_complete = bool(planned["append_content"].strip())
        wrapper_present = True
        managed_wrapper = True
        wrapper_current = True
        legacy_detected = False
        legacy_paths: List[str] = []
        expected_wrapper = planned["shell_block"]
    else:
        shell_rc_content = read_text_if_exists(rt["shell_rc"])
        settings = load_settings(rt["settings"]) if rt["settings"].exists() else {}
        system_body = read_text_if_exists(rt["system_prompt"])
        system_exists = rt["system_prompt"].is_file()
        append_exists = rt["append_prompt"].is_file()
        system_complete = bool(system_exists and rt["system_prompt"].stat().st_size > 0)
        append_complete = bool(append_exists and rt["append_prompt"].stat().st_size > 0)
        wrapper_present = bool(shell_block_pattern().search(shell_rc_content)) or bool(LEGACY_WRAPPER_RE.search(shell_rc_content))
        managed_wrapper = bool(shell_block_pattern().search(shell_rc_content))
        legacy_detected = rt["legacy_launcher_detected"]
        legacy_paths = rt["legacy_launcher_paths"]
        expected_wrapper = render_shell_wrapper(
            rt["claude_bin"],
            rt["system_prompt"],
            rt["append_prompt"],
            rt["shell_kind"],
            rt["upstream_candidates"],
        )
        wrapper_current = shell_wrapper_is_current(shell_rc_content, expected_wrapper, rt["shell_kind"])
    settings_aligned = bool(system_body) and settings.get("systemPrompt") == system_body
    runtime_ready = bool(
        system_complete
        and append_complete
        and settings_aligned
        and wrapper_current
        and rt["upstream_exists"]
        and not legacy_detected
        and not rt["legacy_launcher_conflict"]
    )
    return {
        "supported": True,
        "shell_kind": rt["shell_kind"],
        "system_prompt_file": str(rt["system_prompt"]),
        "append_prompt_file": str(rt["append_prompt"]),
        "settings_file": str(rt["settings"]),
        "shell_rc": str(rt["shell_rc"]),
        "system_prompt_exists": system_exists,
        "append_prompt_exists": append_exists,
        "settings_system_prompt_aligned": settings_aligned,
        "shell_wrapper_present": wrapper_present,
        "shell_wrapper_managed": managed_wrapper,
        "upstream_candidates": rt["upstream_candidates"],
        "upstream_path": rt["upstream_path"],
        "upstream_exists": rt["upstream_exists"],
        "shell_wrapper_current": wrapper_current,
        "legacy_launcher_detected": legacy_detected,
        "legacy_launcher_paths": legacy_paths,
        "legacy_launcher_conflict": rt["legacy_launcher_conflict"],
        "legacy_launcher_conflict_paths": rt["legacy_launcher_conflict_paths"],
        "upgrade_required": not runtime_ready,
        "runtime_ready": runtime_ready,
        "note": (
            "Hard creative/NSFW delivery on current Claude Code requires the shell "
            "wrapper's --append-system-prompt-file; settings.systemPrompt alone is insufficient."
        ),
    }


def collect_status(scope: str, project_dir: Optional[str], name: str, runtime: bool = False) -> dict:
    md_filename = normalize_md_name(name)
    block_name = marker_name(md_filename)
    paths = resolve_scope(scope, project_dir)
    instruction_path = paths.instruction_file(md_filename)
    memory_exists = paths.memory_file.is_file()
    instruction_exists = instruction_path.is_file()
    content = read_text_if_exists(paths.memory_file)
    block_exists = has_import_block(content, block_name)
    status: Dict[str, Any] = {
        "schema": JSON_SCHEMA,
        "scope": paths.scope,
        "root": str(paths.root),
        "memory_file": str(paths.memory_file),
        "instruction_file": str(instruction_path),
        "import_target": paths.import_target(md_filename),
        "memory_file_exists": memory_exists,
        "instruction_file_exists": instruction_exists,
        "import_block_exists": block_exists,
        "installed": bool(block_exists and instruction_exists),
    }

    # --- structured extension blocks (additive; flat keys above are kept) ---
    status["presence"] = {
        "memory_file": memory_exists,
        "instruction_file": instruction_exists,
        "import_block": block_exists,
    }
    status["alignment"] = {
        "import_block_present": block_exists,
        "import_target": paths.import_target(md_filename),
    }
    status["source_identity"] = {
        "kind": "deployed" if instruction_exists else "missing",
        "instruction_sha256": file_evidence(instruction_path)["sha256"] if instruction_exists else None,
        "instruction_size_bytes": instruction_path.stat().st_size if instruction_exists else None,
        "drift": None,
    }
    status["recovery_state"] = inspect_recovery_state(paths)

    if runtime:
        if paths.scope != "user":
            status["runtime"] = {"supported": False, "reason": "runtime status only for user scope"}
        else:
            runtime_status = collect_runtime_status(paths, md_filename)
            status["runtime"] = runtime_status
            status["presence"].update(
                {
                    "system_prompt": runtime_status["system_prompt_exists"],
                    "append_prompt": runtime_status["append_prompt_exists"],
                    "settings_file": Path(runtime_status["settings_file"]).is_file(),
                    "shell_wrapper": runtime_status["shell_wrapper_present"],
                }
            )
            status["alignment"].update(
                {
                    "settings_system_prompt_aligned": runtime_status["settings_system_prompt_aligned"],
                    "shell_wrapper_current": runtime_status["shell_wrapper_current"],
                    "shell_wrapper_managed": runtime_status["shell_wrapper_managed"],
                }
            )
            system_prompt_path = Path(runtime_status["system_prompt_file"])
            settings_drift: Optional[bool] = None
            if system_prompt_path.is_file() and Path(runtime_status["settings_file"]).is_file():
                settings_drift = not runtime_status["settings_system_prompt_aligned"]
            status["source_identity"].update(
                {
                    "system_prompt_sha256": file_evidence(system_prompt_path)["sha256"],
                    "settings_system_prompt_drift": settings_drift,
                }
            )
            status["runtime_readiness"] = {
                "upstream_candidates": runtime_status["upstream_candidates"],
                "upstream_path": runtime_status["upstream_path"],
                "upstream_exists": runtime_status["upstream_exists"],
                "shell_wrapper_current": runtime_status["shell_wrapper_current"],
                "upgrade_required": runtime_status["upgrade_required"],
                "legacy_launcher_detected": runtime_status["legacy_launcher_detected"],
                "legacy_launcher_paths": runtime_status["legacy_launcher_paths"],
                "legacy_launcher_conflict": runtime_status["legacy_launcher_conflict"],
                "legacy_launcher_conflict_paths": runtime_status["legacy_launcher_conflict_paths"],
                "runtime_ready": runtime_status["runtime_ready"],
            }
            status["installed"] = bool(status["installed"] and runtime_status["runtime_ready"])
    return status


def command_status(args) -> int:
    try:
        status = collect_status(args.scope, args.project_dir, args.name, runtime=bool(getattr(args, "runtime", False)))
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    print(f"scope: {status['scope']}")
    print(f"memory file: {status['memory_file']}")
    print(f"instruction file: {status['instruction_file']}")
    print(f"import target: {status['import_target']}")
    print(f"memory file exists: {'yes' if status['memory_file_exists'] else 'no'}")
    print(f"instruction file: {'yes' if status['instruction_file_exists'] else 'no'}")
    print(f"import block: {'yes' if status['import_block_exists'] else 'no'}")
    if "runtime" in status:
        rt = status["runtime"]
        if not rt.get("supported"):
            print(f"runtime: unsupported ({rt.get('reason')})")
        else:
            print(f"shell kind: {rt.get('shell_kind', 'N/A')}")
            print(f"system-prompt file: {'yes' if rt['system_prompt_exists'] else 'no'} ({rt['system_prompt_file']})")
            print(f"append-prompt file: {'yes' if rt['append_prompt_exists'] else 'no'} ({rt['append_prompt_file']})")
            print(f"settings.systemPrompt aligned: {'yes' if rt['settings_system_prompt_aligned'] else 'no'}")
            print(
                f"shell wrapper: {'managed' if rt['shell_wrapper_managed'] else ('legacy/present' if rt['shell_wrapper_present'] else 'no')}"
            )
            print(f"shell wrapper current: {'yes' if rt['shell_wrapper_current'] else 'no'}")
            print(f"upstream: {rt['upstream_path'] or 'unavailable'}")
            print(f"upstream exists: {'yes' if rt['upstream_exists'] else 'no'}")
            print(f"legacy launcher: {'yes' if rt['legacy_launcher_detected'] else 'no'}")
            if rt["legacy_launcher_conflict"]:
                print("legacy launcher conflict: yes")
            print(f"upgrade required: {'yes' if rt['upgrade_required'] else 'no'}")
            print(f"runtime ready: {'yes' if rt['runtime_ready'] else 'no'}")
            print(f"note: {rt['note']}")
    print(f"installed: {'yes' if status['installed'] else 'no'}")
    return 0


def command_uninstall(args) -> int:
    use_json = bool(getattr(args, "json", False))
    try:
        md_filename = normalize_md_name(args.name)
        name = marker_name(md_filename)
        paths = resolve_scope(args.scope, args.project_dir)
        current_memory = read_text_if_exists(paths.memory_file)
        updated_memory, memory_changed = remove_import_block(current_memory, name)
        runtime = bool(getattr(args, "runtime", False))
        if runtime and paths.scope != "user":
            raise ValueError("--runtime 仅支持 --scope user")
    except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
        return _write_command_error(args, "uninstall", str(exc))

    instruction_path = paths.instruction_file(md_filename)
    report = _write_report_base("uninstall", args, paths, name)
    report["target"] = {
        "memory_file": str(paths.memory_file),
        "instruction_file": str(instruction_path),
        "import_target": paths.import_target(md_filename),
    }

    if not preview_header_mode(args):
        residue_blockers = _blockers_for_recovery_residue(paths)
        if residue_blockers:
            return _write_command_error(
                args,
                "uninstall",
                "; ".join(residue_blockers),
                extra={"scope": paths.scope, "name": name, "target": report["target"]},
            )

    preview_only = preview_header_mode(args) if use_json else preview_header(args)
    if not use_json:
        describe_scope(paths, md_filename)
        print(f"remove import block: {'yes' if memory_changed else 'no'}")
        print(f"remove instruction file: {'yes' if instruction_path.exists() else 'no'}")
        print(f"runtime uninstall: {'yes' if runtime else 'no'}")

    if paths.memory_file.exists() and memory_changed:
        _add_action(report, "backup", paths.memory_file, "back up memory file before import block removal")
        _add_action(report, "write", paths.memory_file, "remove managed import block")
    elif memory_changed:
        _add_action(report, "write", paths.memory_file, "remove managed import block")
    if instruction_path.exists():
        _add_action(report, "backup", instruction_path, "back up instruction file before removal")
        _add_action(report, "remove", instruction_path, "remove keysmith instruction file")

    rt = user_runtime_paths() if runtime else None
    shell_rc_updated = ""
    shell_rc_changed = False
    if runtime and rt is not None:
        shell_rc_current = read_text_if_exists(rt["shell_rc"])
        shell_rc_updated, shell_rc_changed = remove_shell_wrapper(shell_rc_current)
        if not use_json:
            print(f"shell kind: {rt['shell_kind']}")
            print(f"remove system-prompt: {'yes' if rt['system_prompt'].exists() else 'no'}")
            print(f"remove append-prompt: {'yes' if rt['append_prompt'].exists() else 'no'}")
            print(f"remove shell wrapper: {'yes' if shell_rc_changed else 'no'}")
            print("settings.systemPrompt: left intact (use restore from backup if you need rollback)")
        report["target"].update(
            {
                "system_prompt_file": str(rt["system_prompt"]),
                "append_prompt_file": str(rt["append_prompt"]),
                "shell_rc": str(rt["shell_rc"]),
                "shell_kind": rt["shell_kind"],
            }
        )
        for path in (rt["system_prompt"], rt["append_prompt"]):
            if path.exists():
                _add_action(report, "backup", path, f"back up {path.name} before removal")
                _add_action(report, "remove", path, f"remove {path.name}")
        if shell_rc_changed:
            if rt["shell_rc"].exists():
                _add_action(report, "backup", rt["shell_rc"], "back up shell profile before wrapper removal")
            _add_action(report, "remove-wrapper", rt["shell_rc"], "remove managed shell wrapper")
            report["reload_required"] = True
            report["reload_hint"] = ". $PROFILE" if rt["shell_kind"] == "powershell" else "source ~/.zshrc"
        report["warnings"].append("settings.systemPrompt left intact (restore from a controlled backup to roll it back)")

    if preview_only:
        if paths.memory_file.exists() and memory_changed:
            _planned_backup(report, paths.memory_file)
        if instruction_path.exists():
            _planned_backup(report, instruction_path)
        if runtime and rt is not None:
            for path in (rt["system_prompt"], rt["append_prompt"]):
                if path.exists():
                    _planned_backup(report, path)
            if shell_rc_changed and rt["shell_rc"].exists():
                _planned_backup(report, rt["shell_rc"])
        report["mode"] = "preview"
        if use_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    try:
        lock = ScopeWriteLock(paths, label=f"uninstall:{name}")
        lock.acquire()
    except TransactionConflict as exc:
        return _write_command_error(args, "uninstall", str(exc))

    try:
        residue_blockers = _blockers_for_recovery_residue(paths, fresh_lock=lock)
        if residue_blockers:
            raise TransactionConflict("; ".join(residue_blockers))
    except TransactionConflict as exc:
        lock.release()
        return _write_command_error(args, "uninstall", str(exc))

    journal: Optional[TransactionJournal] = None
    try:
        journal = TransactionJournal(paths, "uninstall")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if paths.memory_file.exists() and memory_changed:
            backup = tx_backup_step(journal, paths.memory_file, timestamp)
            _actual_backup(report, paths.memory_file, backup)
            if not use_json:
                print(f"[备份] {paths.memory_file.name} → {backup.name}")
            tx_write_step(journal, paths.memory_file, updated_memory)
            if not use_json:
                print(f"[写入] {paths.memory_file}")
        if instruction_path.exists():
            backup = tx_backup_step(journal, instruction_path, timestamp)
            _actual_backup(report, instruction_path, backup)
            if not use_json:
                print(f"[备份] {instruction_path.name} → {backup.name}")
            tx_remove_step(journal, instruction_path)
            if not use_json:
                print(f"[移除] {instruction_path}")

        if runtime and rt is not None:
            for path in (rt["system_prompt"], rt["append_prompt"]):
                if path.exists():
                    backup = tx_backup_step(journal, path, timestamp)
                    _actual_backup(report, path, backup)
                    if not use_json:
                        print(f"[备份] {path.name} → {backup.name}")
                    tx_remove_step(journal, path)
                    if not use_json:
                        print(f"[移除] {path}")
            if shell_rc_changed:
                if rt["shell_rc"].exists():
                    backup = tx_backup_step(journal, rt["shell_rc"], timestamp, suffix="pre_uninstall")
                    _actual_backup(report, rt["shell_rc"], backup)
                    if not use_json:
                        print(f"[备份] {rt['shell_rc'].name} → {backup.name}")
                tx_write_step(journal, rt["shell_rc"], shell_rc_updated)
                if not use_json:
                    print(f"[写入] {rt['shell_rc']}")
                    if rt["shell_kind"] == "powershell":
                        print("[提示] 新开 PowerShell 或 . $PROFILE 使 wrapper 卸载生效")
                    else:
                        print("[提示] 新开 shell 或 source ~/.zshrc 使 wrapper 卸载生效")

        journal.commit()
        journal.finish()
    except BaseException as exc:
        rollback_errors: List[str] = []
        if journal is not None and not journal.committed:
            _actions, blockers = rollback_pending_journal(journal.record)
            rollback_errors.extend(blockers)
            if not blockers:
                journal.abandon()
        if rollback_errors:
            message = f"uninstall 失败且回滚不完整: {exc}; {'; '.join(rollback_errors)}"
        else:
            message = f"uninstall 失败，已回滚到之前的状态: {exc}"
        lock.release()
        return _write_command_error(args, "uninstall", message)
    finally:
        if lock.acquired:
            lock.release()

    report["mode"] = "execute"
    report["journal_id"] = journal.id if journal else None
    if not use_json:
        print("[完成] uninstall 已完成。")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_restore(args) -> int:
    use_json = bool(getattr(args, "json", False))
    target = Path(args.target).expanduser().resolve()
    backup = Path(args.backup).expanduser().resolve()

    report = _write_report_base("restore", args, None, None)
    report["target"] = {"file": str(target), "backup": str(backup)}

    scope_paths: Optional[ScopePaths] = None
    if getattr(args, "scope", None):
        try:
            scope_paths = resolve_scope(args.scope, getattr(args, "project_dir", None))
        except (FileNotFoundError, ValueError) as exc:
            return _write_command_error(args, "restore", str(exc), extra={"target": report["target"], "managed": False})
        managed_mode = any(
            Path(entry["backup_path"]).resolve() == backup
            and Path(entry["target_path"]).resolve() == target
            for entry in enumerate_scope_backups(scope_paths, include_runtime=True)
        )
    else:
        managed_mode = bool(is_keysmith_backup_for_target(target, backup))
    report["managed"] = managed_mode

    try:
        if not backup.exists() or not backup.is_file():
            raise FileNotFoundError(f"backup 不存在或不是普通文件: {backup}")
        backup_content = backup.read_text(encoding="utf-8")
        if target.exists() and not target.is_file():
            raise FileNotFoundError(f"target 不是普通文件: {target}")
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        return _write_command_error(args, "restore", str(exc), extra={"target": report["target"], "managed": managed_mode})

    if getattr(args, "scope", None) and not managed_mode:
        return _write_command_error(
            args,
            "restore",
            "指定 scope 的 restore 只接受 backups --json 枚举出的目标与备份配对",
            extra={"target": report["target"], "managed": False, "scope": args.scope},
        )

    report["source"] = source_descriptor("backup", backup, backup_content)
    if target.exists():
        _add_action(report, "backup", target, "pre-restore safety backup of current target")
    _add_action(report, "write", target, f"restore content from {backup.name}")

    # Resolve the owning scope for managed restores (journal + fail-closed residue checks).
    if managed_mode:
        if scope_paths is None:
            scope_paths = _infer_scope_for_restore(args, target)
        if scope_paths is not None:
            report["scope"] = scope_paths.scope
            if not preview_header_mode(args):
                residue_blockers = _blockers_for_recovery_residue(scope_paths)
                if target.name == "settings.json" and scope_paths.scope == "user":
                    # A controlled settings restore IS the remediation for the
                    # settings recovery marker; journals still fail closed.
                    residue_blockers = [b for b in residue_blockers if "待确认" not in b]
                if residue_blockers:
                    return _write_command_error(
                        args,
                        "restore",
                        "; ".join(residue_blockers),
                        extra={"target": report["target"], "managed": managed_mode, "scope": scope_paths.scope},
                    )
            if target.name == "settings.json" and scope_paths.scope == "user":
                _add_action(report, "clear-recovery-marker", target, "clear pending systemPrompt recovery marker if restored settings are aligned")

    preview_only = preview_header_mode(args) if use_json else preview_header(args)
    if not use_json:
        print(f"target: {target}")
        print(f"backup: {backup}")
        print(f"restore bytes: {len(backup_content.encode('utf-8'))}")
        if managed_mode:
            print("managed backup: yes (keysmith *.bak_* scheme verified)")
    if preview_only:
        if target.exists():
            _planned_backup(report, target)
        report["mode"] = "preview"
        if use_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    lock: Optional[ScopeWriteLock] = None
    journal: Optional[TransactionJournal] = None
    try:
        if scope_paths is not None:
            try:
                lock = ScopeWriteLock(scope_paths, label="restore")
                lock.acquire()
            except TransactionConflict as exc:
                return _write_command_error(args, "restore", str(exc))
            try:
                residue_blockers = _blockers_for_recovery_residue(scope_paths, fresh_lock=lock)
                if target.name == "settings.json" and scope_paths.scope == "user":
                    # A controlled settings restore IS the marker remediation.
                    residue_blockers = [b for b in residue_blockers if "待确认" not in b]
                if residue_blockers:
                    raise TransactionConflict("; ".join(residue_blockers))
            except TransactionConflict as exc:
                lock.release()
                return _write_command_error(args, "restore", str(exc))
            journal = TransactionJournal(scope_paths, "restore")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if target.exists():
            if journal is not None:
                safety_backup = tx_backup_step(journal, target, timestamp, suffix="pre_restore")
            else:
                safety_backup = backup_file(target, timestamp, suffix="pre_restore")
            _actual_backup(report, target, safety_backup)
            if not use_json:
                print(f"[备份] {target.name} → {safety_backup.name}")
        if journal is not None:
            tx_write_step(journal, target, backup_content)
        else:
            atomic_write_text(target, backup_content)
        if not use_json:
            print(f"[写入] {target}")

        marker_cleared = False
        if scope_paths is not None and target.name == "settings.json" and scope_paths.scope == "user":
            try:
                restored_settings = json.loads(backup_content)
            except ValueError:
                restored_settings = None
            if isinstance(restored_settings, dict) and restored_settings.get(RECOVERY_MARKER_KEY):
                system_prompt = scope_paths.keysmith_dir / "system-prompt.md"
                system_body = read_text_if_exists(system_prompt) if system_prompt.is_file() else ""
                if system_body and restored_settings.get("systemPrompt") == system_body:
                    updated = dict(restored_settings)
                    updated.pop(RECOVERY_MARKER_KEY, None)
                    if journal is not None:
                        tx_write_step(journal, target, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
                    else:
                        atomic_write_text(target, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
                    marker_cleared = True
                    if not use_json:
                        print("[恢复] 已清除 settings.json 中的待恢复标记（systemPrompt 与 system-prompt.md 一致）")
        report["recovery_marker_cleared"] = marker_cleared

        if journal is not None:
            journal.commit()
            journal.finish()
    except BaseException as exc:
        rollback_errors: List[str] = []
        if journal is not None and not journal.committed:
            _actions, blockers = rollback_pending_journal(journal.record)
            rollback_errors.extend(blockers)
            if not blockers:
                journal.abandon()
        if rollback_errors:
            message = f"restore 失败且回滚不完整: {exc}; {'; '.join(rollback_errors)}"
        else:
            message = f"restore 失败，已回滚到之前的状态: {exc}"
        if lock is not None:
            lock.release()
        return _write_command_error(args, "restore", message)
    finally:
        if lock is not None and lock.acquired:
            lock.release()

    report["mode"] = "execute"
    if journal is not None:
        report["journal_id"] = journal.id
    if not use_json:
        print("[完成] restore 已完成。")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _infer_scope_for_restore(args: Any, target: Path) -> Optional[ScopePaths]:
    """Best-effort scope resolution for a managed restore target."""
    scope = getattr(args, "scope", None)
    project_dir = getattr(args, "project_dir", None)
    if scope:
        try:
            return resolve_scope(scope, project_dir)
        except (FileNotFoundError, ValueError):
            return None
    home = resolve_home()
    candidates = [
        (home / ".claude").resolve(),
        (home / ".claude" / "keysmith").resolve(),
    ]
    try:
        resolved = target.resolve()
    except OSError:
        return None
    for candidate in candidates:
        try:
            resolved.relative_to(candidate)
            return resolve_scope("user")
        except ValueError:
            continue
    return None


def command_backups(args) -> int:
    """Read-only enumeration of keysmith-managed backups for a scope."""
    use_json = bool(getattr(args, "json", False))
    try:
        paths = resolve_scope(args.scope, getattr(args, "project_dir", None))
        entries = enumerate_scope_backups(paths, include_runtime=True)
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _write_command_error(args, "backups", str(exc))

    if use_json:
        payload = {
            "schema": JSON_SCHEMA,
            "operation": "backups",
            "ok": True,
            "scope": paths.scope,
            "scope_root": str(paths.root),
            "backups": entries,
            "count": len(entries),
            "exit_status": 0,
            "error": None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"scope: {paths.scope}")
    print(f"scope root: {paths.root}")
    print(f"managed backups: {len(entries)}")
    for entry in entries:
        print(f"  - [{entry['kind']}] {entry['backup_path']}")
        print(f"      target: {entry['target_name']}  size: {entry['size_bytes']}  sha256: {entry['sha256'][:12]}…  created: {entry['created']}")
    return 0


def command_recover(args) -> int:
    """Preview/execute recovery of interrupted keysmith transactions. Idempotent."""
    use_json = bool(getattr(args, "json", False))
    try:
        paths = resolve_scope(args.scope, getattr(args, "project_dir", None))
    except (FileNotFoundError, ValueError) as exc:
        return _write_command_error(args, "recover", str(exc))

    report = _write_report_base("recover", args, paths, None)
    report["target"] = {"keysmith_dir": str(paths.keysmith_dir), "scope_root": str(paths.root)}

    residue: List[Dict[str, Any]] = []
    journal_records: List[Tuple[Path, Dict[str, Any]]] = []
    for journal_path in find_journals(paths):
        record = load_journal(journal_path)
        if record is None:
            residue.append({"kind": "corrupt_journal", "journal_path": str(journal_path)})
            report["blockers"].append(f"journal 损坏无法解析，已保留证据: {journal_path}")
            continue
        journal_records.append((journal_path, record))
        residue.append(
            {
                "kind": "journal",
                "journal_path": str(journal_path),
                "journal_id": record.get("journal_id"),
                "operation": record.get("operation"),
                "state": record.get("state"),
                "started_at": record.get("started_at"),
                "pid": record.get("pid"),
                "steps": len(record.get("steps", [])),
            }
        )

    atomic_temp_files, atomic_temp_blockers = find_atomic_temp_residue(paths)
    report["blockers"].extend(atomic_temp_blockers)
    for temp_path in atomic_temp_files:
        residue.append({"kind": "atomic_temp", "path": str(temp_path)})

    settings_marker, settings_path, _settings, settings_marker_blocker = _runtime_recovery_marker_status(paths)
    if settings_marker:
        residue.append({"kind": "settings_recovery_marker", "path": str(settings_path)})
    report["residue"] = residue

    # Stale-lock reporting/reclaim (never break a live lock).
    lock_path = scope_lock_path(paths)
    stale_lock = False
    if lock_path.exists():
        holder: Dict[str, Any] = {}
        try:
            loaded = json.loads(lock_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                holder = loaded
        except (OSError, ValueError, UnicodeDecodeError):
            holder = {}
        pid = holder.get("pid")
        if isinstance(pid, int) and pid > 0 and _pid_alive(pid):
            report["blockers"].append(f"检测到活跃的 keysmith 写入锁（pid {pid}），拒绝在写入进行中恢复")
        else:
            stale_lock = True
            _add_action(report, "reclaim-lock", lock_path, "remove stale keysmith lock (dead pid)")

    # Preview must reach the same verdict as execute: dry-run every journal so an
    # unrecoverable plan blocks before the user confirms (never mutates state).
    planned_repairs: List[Dict[str, Any]] = []
    for temp_path in atomic_temp_files:
        planned_repairs.append(
            {
                "journal": None,
                "action": "cleanup-atomic-temp",
                "path": str(temp_path),
                "detail": "remove a keysmith-owned atomic-write temp file left by an interrupted process",
            }
        )
    for journal_path, record in journal_records:
        if record.get("state") == "committed":
            _plan, plan_blockers = finish_committed_journal(record)
            planned_repairs.append(
                {"journal": str(journal_path), "action": "finalize-committed", "detail": "verify committed transaction and clean up journal"}
            )
        else:
            _plan, plan_blockers = plan_pending_rollback(record)
            planned_repairs.append(
                {"journal": str(journal_path), "action": "rollback-pending", "detail": "roll back interrupted transaction to prior state using verified backups"}
            )
            planned_repairs.extend(_plan)
        for plan_blocker in plan_blockers:
            if plan_blocker not in report["blockers"]:
                report["blockers"].append(plan_blocker)
    if settings_marker:
        if settings_marker_blocker:
            if settings_marker_blocker not in report["blockers"]:
                report["blockers"].append(settings_marker_blocker)
        else:
            planned_repairs.append({"journal": None, "action": "clear-settings-marker", "detail": "clear pending systemPrompt recovery marker after verified alignment"})
    report["planned_repairs"] = planned_repairs

    if not residue and not stale_lock and not report["blockers"]:
        report["ok"] = True
        report["exit_status"] = 0
        _add_action(report, "noop", paths.keysmith_dir, "no transaction residue found")
        if use_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("recover: 未发现未完成的事务或残留锁。")
        return 0

    preview_only = preview_header_mode(args) if use_json else preview_header(args)
    if preview_only:
        report["mode"] = "preview"
        report["ok"] = not report["blockers"]
        report["exit_status"] = 0 if report["ok"] else 1
        if use_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"recover: 发现 {len(residue)} 处残留：")
            for item in residue:
                print(f"  - {item['kind']}: {item.get('journal_path') or item.get('path')}")
            for repair in planned_repairs:
                print(f"  planned: {repair['action']} ({repair['detail']})")
            for blocker in report["blockers"]:
                print(f"  [阻塞] {blocker}")
        return report["exit_status"]

    if report["blockers"]:
        report["ok"] = False
        report["exit_status"] = 1
        report["error"] = "; ".join(report["blockers"])
        if use_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for blocker in report["blockers"]:
                print(f"[阻塞] {blocker}")
            print("[错误] recover 因阻塞项失败关闭，未做任何修改。")
        return 1

    # Execute recovery under the scope lock (reclaiming the stale one if present).
    try:
        lock = ScopeWriteLock(paths, label="recover")
        lock.acquire()
    except TransactionConflict as exc:
        return _write_command_error(args, "recover", str(exc))

    try:
        for journal_path, record in journal_records:
            if record.get("state") == "committed":
                actions, blockers = finish_committed_journal(record)
            else:
                actions, blockers = rollback_pending_journal(record)
            for action in actions:
                report["actions"].append(action)
                if not use_json:
                    print(f"[恢复] {action['action']}: {action['path']} ({action['detail']})")
            if blockers:
                report["blockers"].extend(blockers)
                for blocker in blockers:
                    if not use_json:
                        print(f"[阻塞] {blocker}")
                continue  # preserve journal + evidence for inspection
            try:
                journal_path.unlink()
            except OSError as exc:
                report["blockers"].append(f"无法清理已完成的 journal {journal_path}: {exc}")
            else:
                _add_action(report, "cleanup-journal", journal_path, "journal completed and removed")
                if not use_json:
                    print(f"[清理] {journal_path.name} 已完成并移除")

        if not report["blockers"]:
            for temp_path in atomic_temp_files:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    report["blockers"].append(f"无法清理原子写临时残留 {temp_path}: {exc}")
                else:
                    _add_action(report, "cleanup-atomic-temp", temp_path, "interrupted atomic-write temp file removed")
                    if not use_json:
                        print(f"[清理] 原子写临时残留已移除: {temp_path}")

        if settings_marker and not report["blockers"]:
            marker_present, settings_path, settings, marker_blocker = _runtime_recovery_marker_status(paths)
            if marker_blocker:
                report["blockers"].append(marker_blocker)
            elif marker_present and settings is not None:
                updated = dict(settings)
                updated.pop(RECOVERY_MARKER_KEY, None)
                write_settings(settings_path, updated)
                _add_action(report, "clear-settings-marker", settings_path, "systemPrompt aligned with system-prompt.md; recovery marker cleared")
                if not use_json:
                    print("[恢复] settings.json 的待恢复标记已清除（systemPrompt 与 system-prompt.md 一致）")
    finally:
        lock.release()

    report["mode"] = "execute"
    report["ok"] = not report["blockers"]
    report["exit_status"] = 0 if report["ok"] else 1
    report["error"] = None if report["ok"] else "; ".join(report["blockers"])
    if use_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if report["ok"]:
            print("[完成] recover 已完成。")
        else:
            print("[错误] recover 未完全成功；证据已保留，请检查阻塞项。")
    return report["exit_status"]


def command_runtime_doctor(args) -> int:
    """Report runtime paths and repair actions without exposing settings values."""
    try:
        rt = user_runtime_paths()
        shell_rc_content = read_text_if_exists(rt["shell_rc"])
        system_body = read_text_if_exists(rt["system_prompt"])
        settings = load_settings(rt["settings"]) if rt["settings"].exists() else {}
        selected = select_upstream_candidate(rt["upstream_candidates"])
        expected_wrapper = render_shell_wrapper(
            rt["claude_bin"],
            rt["system_prompt"],
            rt["append_prompt"],
            rt["shell_kind"],
            rt["upstream_candidates"],
        )
        wrapper_current = shell_wrapper_is_current(shell_rc_content, expected_wrapper, rt["shell_kind"])
        repair_actions: List[str] = []
        if not rt["upstream_exists"]:
            repair_actions.append("Repair or reinstall Claude Code, then rerun doctor.")
        if rt["legacy_launcher_detected"]:
            repair_actions.append("Run install --scope user --runtime --yes to migrate the recognized legacy launcher pair.")
        if rt["legacy_launcher_conflict"]:
            repair_actions.append("Inspect the unknown ~/.local/bin launcher files; keysmith will not overwrite them.")
        if not wrapper_current:
            repair_actions.append("Run install --scope user --runtime --yes to install the current shell wrapper.")
        if not rt["system_prompt"].is_file() or not rt["append_prompt"].is_file():
            repair_actions.append("Run install --scope user --runtime --yes to restore keysmith prompt files.")
        if not (system_body and settings.get("systemPrompt") == system_body):
            repair_actions.append("Run install --scope user --runtime --yes to realign settings.systemPrompt.")
        if not repair_actions:
            repair_actions.append("No repair action required.")

        # NOTE: keep this exact key set — the contract test asserts it, and
        # adding keys risks leaking settings fields (credentials stay out).
        status = {
            "installation_type": selected["kind"] if selected else "unavailable",
            "upstream_candidates": rt["upstream_candidates"],
            "upstream_path": rt["upstream_path"],
            "system_prompt_file": str(rt["system_prompt"]),
            "append_prompt_file": str(rt["append_prompt"]),
            "settings_file": str(rt["settings"]),
            "shell_kind": rt["shell_kind"],
            "shell_rc": str(rt["shell_rc"]),
            "repair_actions": repair_actions,
        }
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    print(f"shell kind: {status.get('shell_kind', 'N/A')}")
    print(f"installation type: {status['installation_type']}")
    print(f"upstream: {status['upstream_path'] or 'unavailable'}")
    print("upstream candidates:")
    for candidate in status["upstream_candidates"]:
        print(f"  - {candidate['kind']}: {candidate['path']} ({candidate['reason']})")
    print(f"system-prompt path: {status['system_prompt_file']}")
    print(f"append-prompt path: {status['append_prompt_file']}")
    print(f"settings path: {status['settings_file']}")
    print(f"shell profile path: {status['shell_rc']}")
    print("repair actions:")
    for item in status["repair_actions"]:
        print(f"  - {item}")
    return 0


# Set by _ContractArgumentParser.error so main() can echo the real reason in JSON.
_LAST_USAGE_ERROR: List[Optional[str]] = [None]


class _ContractArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that records its usage error before exiting.

    Subparsers inherit this class, so ``--max-tokens`` and friends keep argparse's
    normal behaviour while still letting ``--json`` callers receive the message.
    """

    def error(self, message: str) -> "None":  # noqa: D401 - argparse contract
        _LAST_USAGE_ERROR[0] = message
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ContractArgumentParser(
        description="Claude Code instruction + runtime injector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s install --scope project --dry-run
  %(prog)s install --scope user --name team-rules --yes
  %(prog)s install --scope user --runtime --yes
  %(prog)s status --scope user --runtime --json
  %(prog)s doctor --json
  %(prog)s uninstall --scope user --runtime --yes
  %(prog)s restore --target ./CLAUDE.md --backup ./CLAUDE.md.bak_YYYYMMDD_HHMMSS --yes
  %(prog)s backups --scope user --json
  %(prog)s recover --scope user
  %(prog)s recover --scope user --yes
        """,
    )
    parser.add_argument("--version", action="version", version=f"claude-keysmith {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_scope_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--scope", choices=["user", "project", "local"], required=True, help="安装范围")
        subparser.add_argument("--project-dir", help="project/local scope 的项目目录；默认当前目录")
        subparser.add_argument("--name", "-n", default="claude-project-rules", help="指令文件名，不含 .md；默认 claude-project-rules")

    install = subparsers.add_parser("install", help="安装或更新 managed import block 与 keysmith 指令文件")
    add_scope_args(install)
    install.add_argument("--file", "-f", help="外部 Markdown 指令文件；不传则使用 examples/claude-project-rules.md")
    install.add_argument(
        "--runtime",
        action="store_true",
        help="user scope 额外注入 system-prompt.md + append-prompt.md + settings.systemPrompt + shell wrapper",
    )
    install.add_argument(
        "--append-file",
        help="runtime append 指令文件；默认 examples/claude-append-prompt.md",
    )
    install.add_argument(
        "--max-tokens",
        type=positive_int,
        help="设置 settings.json 的 max_tokens 值（正整数，仅在 --runtime 时生效）",
    )
    install.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    install.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    install.add_argument("--json", action="store_true", help="输出稳定 JSON（claude-keysmith/v1）")
    install.set_defaults(func=command_install)

    status = subparsers.add_parser("status", help="检查 managed block 与 keysmith 指令文件是否存在")
    add_scope_args(status)
    status.add_argument("--runtime", action="store_true", help="同时检查 runtime 注入状态（仅 user scope）")
    status.add_argument("--json", action="store_true", help="输出稳定 JSON")
    status.set_defaults(func=command_status)

    uninstall = subparsers.add_parser("uninstall", help="移除自己的 managed block，并备份后移除对应指令文件")
    add_scope_args(uninstall)
    uninstall.add_argument("--runtime", action="store_true", help="同时移除 runtime 文件与 shell wrapper（不自动清空 settings.systemPrompt）")
    uninstall.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    uninstall.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    uninstall.add_argument("--json", action="store_true", help="输出稳定 JSON（claude-keysmith/v1）")
    uninstall.set_defaults(func=command_uninstall)

    restore = subparsers.add_parser("restore", help="从指定备份恢复目标文件")
    restore.add_argument("--target", required=True, help="要恢复的文件，例如 CLAUDE.md")
    restore.add_argument("--backup", required=True, help="备份文件路径")
    restore.add_argument("--scope", choices=["user", "project", "local"], help="受控恢复时显式指定 scope（可选）")
    restore.add_argument("--project-dir", help="project/local scope 的项目目录")
    restore.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    restore.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    restore.add_argument("--json", action="store_true", help="输出稳定 JSON（claude-keysmith/v1）")
    restore.set_defaults(func=command_restore)

    backups_cmd = subparsers.add_parser("backups", help="只读枚举 keysmith 管理的 *.bak_* 备份")
    backups_cmd.add_argument("--scope", choices=["user", "project", "local"], required=True, help="备份所属范围")
    backups_cmd.add_argument("--project-dir", help="project/local scope 的项目目录；默认当前目录")
    backups_cmd.add_argument("--json", action="store_true", help="输出稳定 JSON（claude-keysmith/v1）")
    backups_cmd.set_defaults(func=command_backups)

    recover_cmd = subparsers.add_parser("recover", help="预览/执行中断事务的恢复（默认预览，--yes 执行）")
    recover_cmd.add_argument("--scope", choices=["user", "project", "local"], required=True, help="恢复所属范围")
    recover_cmd.add_argument("--project-dir", help="project/local scope 的项目目录；默认当前目录")
    recover_cmd.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    recover_cmd.add_argument("--yes", action="store_true", help="确认执行恢复；未提供时只预览")
    recover_cmd.add_argument("--json", action="store_true", help="输出稳定 JSON（claude-keysmith/v1）")
    recover_cmd.set_defaults(func=command_recover)

    doctor = subparsers.add_parser("doctor", help="检查 Claude Code runtime 路径、wrapper 与修复建议")
    doctor.add_argument("--json", action="store_true", help="输出稳定 JSON")
    doctor.set_defaults(func=command_runtime_doctor)

    return parser


def _usage_error_mode(argv: List[str]) -> str:
    """Infer preview/execute from raw argv when argparse could not build args."""
    return "preview" if "--dry-run" in argv or "--yes" not in argv else "execute"


def _emit_usage_error_as_contract(operation: str, message: str, mode: str) -> None:
    """Render an argparse usage error as a contract document on stdout.

    Callers that requested ``--json`` must never receive bare usage text; the GUI
    would surface it as "CLI 未输出稳定 JSON" instead of the real reason.
    """
    print(
        json.dumps(
            {
                "schema": JSON_SCHEMA,
                "operation": operation,
                "mode": mode,
                "ok": False,
                "error": message,
                "blockers": [message],
                "warnings": [],
                "actions": [],
                "backups": [],
                "reload_required": False,
                "reload_hint": None,
                "exit_status": 2,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    configure_utf8_stdio()
    parser = build_parser()
    argv = sys.argv[1:]
    if "--json" in argv:
        # Keep the JSON contract intact for argument-validation failures too.
        operation = next((item for item in argv if not item.startswith("-")), "unknown")
        try:
            args = parser.parse_args(argv)
        except SystemExit as exit_request:
            status = exit_request.code if isinstance(exit_request.code, int) else 2
            if status == 0:
                raise
            _emit_usage_error_as_contract(
                operation,
                _LAST_USAGE_ERROR[0] or "参数校验失败",
                _usage_error_mode(argv),
            )
            return status
        return args.func(args)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
