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
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
START_TEMPLATE = "<!-- claude-keysmith:start name={name} -->"
END_TEMPLATE = "<!-- claude-keysmith:end name={name} -->"
DEFAULT_EXAMPLE = Path(__file__).resolve().parent / "examples" / "claude-project-rules.md"
DEFAULT_APPEND_EXAMPLE = Path(__file__).resolve().parent / "examples" / "claude-append-prompt.md"
VERSION = "v6"

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


def atomic_write_text(path: Path, content: str) -> None:
    """Write UTF-8 text atomically inside the target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
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


def reserve_unique_backup_path(path: Path, timestamp: str, suffix: str = "") -> Path:
    """Reserve a backup path so a later rename cannot overwrite another writer."""
    extra = f"_{suffix}" if suffix else ""
    base = path.with_name(f"{path.name}.bak_{timestamp}{extra}")
    counter = 1
    while True:
        candidate = base if counter == 1 else base.with_name(f"{base.name}_{counter}")
        counter += 1
        try:
            fd = os.open(str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate


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
    existing = [path for path in (ps1, cmd) if path.exists()]
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

    ps1_lower = ps1_text.lower()
    ps1_known = bool(
        ps1.is_file()
        and "keysmith" in ps1_lower
        and ("system-prompt" in ps1_lower or "append-prompt" in ps1_lower)
    )

    cmd_lines = [line.strip() for line in cmd_text.splitlines() if line.strip()]
    if cmd_lines and cmd_lines[0].lower() == "@echo off":
        cmd_lines = cmd_lines[1:]
    forwarder = cmd_lines[0] if cmd_lines else ""
    cmd_known = bool(
        cmd.is_file()
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


def migrate_legacy_launchers(home: Path, timestamp: str) -> List[Tuple[Path, Path]]:
    """Rename a recognized launcher pair to unique recovery backups."""
    inspection = inspect_legacy_launchers(home)
    if inspection["conflict"]:
        raise ValueError("检测到未知 ~/.local/bin/claude.ps1 或 claude.cmd，拒绝覆盖")
    if not inspection["detected"]:
        return []

    moved: List[Tuple[Path, Path]] = []
    try:
        for raw_path in inspection["paths"]:
            source = Path(raw_path)
            backup = reserve_unique_backup_path(source, timestamp, "pre_v6")
            try:
                os.replace(str(source), str(backup))
            except BaseException:
                try:
                    backup.unlink()
                except OSError:
                    pass
                raise
            moved.append((source, backup))
    except BaseException as migration_error:
        rollback_errors: List[str] = []
        for source, backup in reversed(moved):
            if not backup.exists():
                continue
            try:
                fd = os.open(str(source), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            except OSError as exc:
                rollback_errors.append(f"{source}: {exc}")
                continue
            try:
                os.replace(str(backup), str(source))
            except OSError as exc:
                try:
                    source.unlink()
                except OSError:
                    pass
                rollback_errors.append(f"{source}: {exc}")
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
                "        continue",
                "      } catch [System.Management.Automation.ItemNotFoundException] {",
                "        continue",
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
    # Keep paths expandable and absolute for reliability across shells.
    return "\n".join(
        [
            SHELL_BEGIN,
            SHELL_VERSION_MARKER,
            "# Managed by claude-keysmith. Do not edit by hand.",
            "# Effective NSFW / creative delivery depends on CLI append, not settings.json alone.",
            "claude() {",
            f'  "{claude_bin}" \\',
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


def shell_wrapper_is_current(content: str, expected_block: str) -> bool:
    match = shell_block_pattern().search(content)
    return bool(match and match.group(0) == expected_block)


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
        return pattern.sub(block, updated, count=1), True

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


def command_install(args) -> int:
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
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    preview_only = preview_header(args)
    describe_scope(paths, md_filename)
    print(f"memory change: {'yes' if memory_changed else 'no'}")
    print(f"instruction bytes: {len(instruction_content.encode('utf-8'))}")
    print(f"runtime inject: {'yes' if runtime else 'no'}")

    instruction_path = paths.instruction_file(md_filename)
    if instruction_path.exists():
        print("existing instruction file: yes (will back up before overwrite)")
    else:
        print("existing instruction file: no")

    runtime_plan: Optional[Dict[str, Any]] = None
    if runtime:
        try:
            rt = user_runtime_paths()
            append_content = load_append_content(getattr(args, "append_file", None))
            system_body = strip_markdown_h1(instruction_content)
            settings = load_settings(rt["settings"])
            max_tokens = getattr(args, "max_tokens", None)
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
            print(f"[错误] runtime 准备失败: {exc}")
            return 1

    if preview_only:
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if paths.memory_file.exists():
        backup = backup_file(paths.memory_file, timestamp)
        print(f"[备份] {paths.memory_file.name} → {backup.name}")
    if instruction_path.exists():
        backup = backup_file(instruction_path, timestamp)
        print(f"[备份] {instruction_path.name} → {backup.name}")

    atomic_write_text(instruction_path, ensure_trailing_newline(instruction_content))
    print(f"[写入] {instruction_path}")
    atomic_write_text(paths.memory_file, updated_memory)
    print(f"[写入] {paths.memory_file}")

    if runtime_plan is not None:
        rt = runtime_plan["paths"]
        for label, path, content in [
            ("system-prompt.md", rt["system_prompt"], runtime_plan["system_body"]),
            ("append-prompt.md", rt["append_prompt"], runtime_plan["append_content"]),
        ]:
            if path.exists():
                backup = backup_file(path, timestamp)
                print(f"[备份] {path.name} → {backup.name}")
            atomic_write_text(path, content)
            print(f"[写入] {path}")

        if rt["settings"].exists():
            backup = backup_file(rt["settings"], timestamp, suffix="pre_runtime")
            print(f"[备份] {rt['settings'].name} → {backup.name}")
        write_settings(rt["settings"], runtime_plan["settings"])
        print(f"[写入] {rt['settings']} (systemPrompt aligned; token/base URL untouched)")

        if rt["shell_rc"].exists():
            backup = backup_file(rt["shell_rc"], timestamp, suffix="pre_runtime")
            print(f"[备份] {rt['shell_rc'].name} → {backup.name}")
        atomic_write_text(rt["shell_rc"], runtime_plan["shell_rc_updated"])
        print(f"[写入] {rt['shell_rc']} (managed claude wrapper)")

        # Keep the old PATH launchers available until every runtime file is durable.
        if rt["legacy_launcher_detected"]:
            try:
                moved = migrate_legacy_launchers(rt["home"], timestamp)
            except (OSError, ValueError) as exc:
                print(f"[错误] 旧 Windows launcher 迁移失败: {exc}")
                return 1
            for source, backup in moved:
                print(f"[迁移] {source} → {backup}")

        if rt["shell_kind"] == "powershell":
            print("[提示] 新开一个 PowerShell，或执行: . $PROFILE")
        else:
            print("[提示] 新开一个 shell，或执行: source ~/.zshrc")
        print("[提示] 有效路径是 CLI --system-prompt-file + --append-system-prompt-file；模型建议 claude-opus-5。")

    print("[完成] install 已完成。")
    return 0


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

    if runtime:
        if paths.scope != "user":
            status["runtime"] = {"supported": False, "reason": "runtime status only for user scope"}
        else:
            rt = user_runtime_paths()
            system_exists = rt["system_prompt"].is_file()
            append_exists = rt["append_prompt"].is_file()
            system_complete = bool(system_exists and rt["system_prompt"].stat().st_size > 0)
            append_complete = bool(append_exists and rt["append_prompt"].stat().st_size > 0)
            settings = load_settings(rt["settings"]) if rt["settings"].exists() else {}
            system_body = read_text_if_exists(rt["system_prompt"])
            settings_aligned = bool(system_body) and settings.get("systemPrompt") == system_body
            shell_rc_content = read_text_if_exists(rt["shell_rc"])
            wrapper_present = bool(shell_block_pattern().search(shell_rc_content)) or bool(LEGACY_WRAPPER_RE.search(shell_rc_content))
            managed_wrapper = bool(shell_block_pattern().search(shell_rc_content))
            expected_wrapper = render_shell_wrapper(
                rt["claude_bin"],
                rt["system_prompt"],
                rt["append_prompt"],
                rt["shell_kind"],
                rt["upstream_candidates"],
            )
            wrapper_current = shell_wrapper_is_current(shell_rc_content, expected_wrapper)
            runtime_ready = bool(
                system_complete
                and append_complete
                and settings_aligned
                and wrapper_current
                and rt["upstream_exists"]
                and not rt["legacy_launcher_detected"]
                and not rt["legacy_launcher_conflict"]
            )
            status["runtime"] = {
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
                "legacy_launcher_detected": rt["legacy_launcher_detected"],
                "legacy_launcher_paths": rt["legacy_launcher_paths"],
                "legacy_launcher_conflict": rt["legacy_launcher_conflict"],
                "legacy_launcher_conflict_paths": rt["legacy_launcher_conflict_paths"],
                "upgrade_required": not runtime_ready,
                "runtime_ready": runtime_ready,
                "note": (
                    "Hard creative/NSFW delivery on current Claude Code requires the shell "
                    "wrapper's --append-system-prompt-file; settings.systemPrompt alone is insufficient."
                ),
            }
            status["installed"] = bool(status["installed"] and status["runtime"]["runtime_ready"])
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
        print(f"[错误] {exc}")
        return 1

    instruction_path = paths.instruction_file(md_filename)
    preview_only = preview_header(args)
    describe_scope(paths, md_filename)
    print(f"remove import block: {'yes' if memory_changed else 'no'}")
    print(f"remove instruction file: {'yes' if instruction_path.exists() else 'no'}")
    print(f"runtime uninstall: {'yes' if runtime else 'no'}")

    rt = user_runtime_paths() if runtime else None
    shell_rc_updated = ""
    shell_rc_changed = False
    if runtime and rt is not None:
        shell_rc_current = read_text_if_exists(rt["shell_rc"])
        shell_rc_updated, shell_rc_changed = remove_shell_wrapper(shell_rc_current)
        print(f"shell kind: {rt['shell_kind']}")
        print(f"remove system-prompt: {'yes' if rt['system_prompt'].exists() else 'no'}")
        print(f"remove append-prompt: {'yes' if rt['append_prompt'].exists() else 'no'}")
        print(f"remove shell wrapper: {'yes' if shell_rc_changed else 'no'}")
        print("settings.systemPrompt: left intact (use restore from backup if you need rollback)")

    if preview_only:
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if paths.memory_file.exists() and memory_changed:
        backup = backup_file(paths.memory_file, timestamp)
        print(f"[备份] {paths.memory_file.name} → {backup.name}")
        atomic_write_text(paths.memory_file, updated_memory)
        print(f"[写入] {paths.memory_file}")
    if instruction_path.exists():
        backup = backup_file(instruction_path, timestamp)
        print(f"[备份] {instruction_path.name} → {backup.name}")
        instruction_path.unlink()
        print(f"[移除] {instruction_path}")

    if runtime and rt is not None:
        for path in (rt["system_prompt"], rt["append_prompt"]):
            if path.exists():
                backup = backup_file(path, timestamp)
                print(f"[备份] {path.name} → {backup.name}")
                path.unlink()
                print(f"[移除] {path}")
        if shell_rc_changed:
            if rt["shell_rc"].exists():
                backup = backup_file(rt["shell_rc"], timestamp, suffix="pre_uninstall")
                print(f"[备份] {rt['shell_rc'].name} → {backup.name}")
            atomic_write_text(rt["shell_rc"], shell_rc_updated)
            print(f"[写入] {rt['shell_rc']}")
            if rt["shell_kind"] == "powershell":
                print("[提示] 新开 PowerShell 或 . $PROFILE 使 wrapper 卸载生效")
            else:
                print("[提示] 新开 shell 或 source ~/.zshrc 使 wrapper 卸载生效")

    print("[完成] uninstall 已完成。")
    return 0


def command_restore(args) -> int:
    target = Path(args.target).expanduser().resolve()
    backup = Path(args.backup).expanduser().resolve()

    try:
        if not backup.exists() or not backup.is_file():
            raise FileNotFoundError(f"backup 不存在或不是普通文件: {backup}")
        backup_content = backup.read_text(encoding="utf-8")
        if target.exists() and not target.is_file():
            raise FileNotFoundError(f"target 不是普通文件: {target}")
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    preview_only = preview_header(args)
    print(f"target: {target}")
    print(f"backup: {backup}")
    print(f"restore bytes: {len(backup_content.encode('utf-8'))}")
    if preview_only:
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if target.exists():
        safety_backup = backup_file(target, timestamp, suffix="pre_restore")
        print(f"[备份] {target.name} → {safety_backup.name}")
    atomic_write_text(target, backup_content)
    print(f"[写入] {target}")
    print("[完成] restore 已完成。")
    return 0


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
        wrapper_current = shell_wrapper_is_current(shell_rc_content, expected_wrapper)
        repair_actions: List[str] = []
        if not rt["upstream_exists"]:
            repair_actions.append("Repair or reinstall Claude Code, then rerun doctor.")
        if rt["legacy_launcher_detected"]:
            repair_actions.append("Run install --scope user --runtime --yes to migrate the recognized legacy launcher pair.")
        if rt["legacy_launcher_conflict"]:
            repair_actions.append("Inspect the unknown ~/.local/bin launcher files; keysmith will not overwrite them.")
        if not wrapper_current:
            repair_actions.append("Run install --scope user --runtime --yes to install the current PowerShell wrapper.")
        if not rt["system_prompt"].is_file() or not rt["append_prompt"].is_file():
            repair_actions.append("Run install --scope user --runtime --yes to restore keysmith prompt files.")
        if not (system_body and settings.get("systemPrompt") == system_body):
            repair_actions.append("Run install --scope user --runtime --yes to realign settings.systemPrompt.")
        if not repair_actions:
            repair_actions.append("No repair action required.")

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
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
        type=int,
        help="设置 settings.json 的 max_tokens 值（仅在 --runtime 时生效）",
    )
    install.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    install.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
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
    uninstall.set_defaults(func=command_uninstall)

    restore = subparsers.add_parser("restore", help="从指定备份恢复目标文件")
    restore.add_argument("--target", required=True, help="要恢复的文件，例如 CLAUDE.md")
    restore.add_argument("--backup", required=True, help="备份文件路径")
    restore.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    restore.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    restore.set_defaults(func=command_restore)

    doctor = subparsers.add_parser("doctor", help="检查当前机器上真正生效的 Claude Code 破限路径")
    doctor.add_argument("--json", action="store_true", help="输出稳定 JSON")
    doctor.set_defaults(func=command_runtime_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
