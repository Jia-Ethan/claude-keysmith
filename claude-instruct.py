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

SHELL_BEGIN = "# >>> claude-keysmith runtime >>>"
SHELL_END = "# <<< claude-keysmith runtime <<<"
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
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        newline="\n",
    ) as tmp_file:
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)
    os.replace(str(tmp_path), str(path))


def backup_file(path: Path, timestamp: Optional[str] = None, suffix: str = "") -> Path:
    """Create a timestamped backup next to an existing file."""
    if not path.exists():
        raise FileNotFoundError(f"无法备份不存在的文件: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"不是普通文件，拒绝备份: {path}")
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    extra = f"_{suffix}" if suffix else ""
    backup = path.with_name(f"{path.name}.bak_{ts}{extra}")
    shutil.copy2(path, backup)
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


def resolve_scope(scope: str, project_dir: Optional[str] = None) -> ScopePaths:
    if scope == "user":
        claude_root = (Path.home() / ".claude").resolve()
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


def user_runtime_paths() -> Dict[str, Path]:
    home = Path.home()
    keysmith_dir = home / ".claude" / "keysmith"
    return {
        "home": home,
        "claude_dir": home / ".claude",
        "keysmith_dir": keysmith_dir,
        "system_prompt": keysmith_dir / "system-prompt.md",
        "append_prompt": keysmith_dir / "append-prompt.md",
        "settings": home / ".claude" / "settings.json",
        "zshrc": home / ".zshrc",
        "claude_bin": home / ".local" / "bin" / "claude",
    }


def render_shell_wrapper(claude_bin: Path, system_prompt: Path, append_prompt: Path) -> str:
    # Keep paths expandable and absolute for reliability across shells.
    return "\n".join(
        [
            SHELL_BEGIN,
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
            shell_block = render_shell_wrapper(rt["claude_bin"], rt["system_prompt"], rt["append_prompt"])
            zshrc_current = read_text_if_exists(rt["zshrc"])
            zshrc_updated, zshrc_changed = ensure_shell_wrapper(zshrc_current, shell_block)
            runtime_plan = {
                "paths": rt,
                "system_body": system_body,
                "append_content": append_content,
                "settings": settings_updated,
                "settings_changed": settings_changed,
                "zshrc_updated": zshrc_updated,
                "zshrc_changed": zshrc_changed,
                "shell_block": shell_block,
            }
            print(f"system-prompt file: {rt['system_prompt']}")
            print(f"append-prompt file: {rt['append_prompt']}")
            print(f"settings.json: {rt['settings']}")
            print(f"settings.systemPrompt change: {'yes' if settings_changed else 'no'}")
            print(f"shell wrapper ({rt['zshrc'].name}) change: {'yes' if zshrc_changed else 'no'}")
            print(f"system-prompt bytes: {len(system_body.encode('utf-8'))}")
            print(f"append-prompt bytes: {len(append_content.encode('utf-8'))}")
            if max_tokens is not None:
                print(f"max_tokens: {max_tokens}")
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

        if rt["zshrc"].exists():
            backup = backup_file(rt["zshrc"], timestamp, suffix="pre_runtime")
            print(f"[备份] {rt['zshrc'].name} → {backup.name}")
        atomic_write_text(rt["zshrc"], runtime_plan["zshrc_updated"])
        print(f"[写入] {rt['zshrc']} (managed claude() wrapper)")
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
            settings = load_settings(rt["settings"]) if rt["settings"].exists() else {}
            system_body = read_text_if_exists(rt["system_prompt"])
            settings_aligned = bool(system_body) and settings.get("systemPrompt") == system_body
            zshrc = read_text_if_exists(rt["zshrc"])
            wrapper_present = bool(shell_block_pattern().search(zshrc)) or bool(LEGACY_WRAPPER_RE.search(zshrc))
            managed_wrapper = bool(shell_block_pattern().search(zshrc))
            status["runtime"] = {
                "supported": True,
                "system_prompt_file": str(rt["system_prompt"]),
                "append_prompt_file": str(rt["append_prompt"]),
                "settings_file": str(rt["settings"]),
                "shell_rc": str(rt["zshrc"]),
                "system_prompt_exists": system_exists,
                "append_prompt_exists": append_exists,
                "settings_system_prompt_aligned": settings_aligned,
                "shell_wrapper_present": wrapper_present,
                "shell_wrapper_managed": managed_wrapper,
                "runtime_ready": bool(
                    system_exists and append_exists and managed_wrapper
                ),
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
            print(f"system-prompt file: {'yes' if rt['system_prompt_exists'] else 'no'} ({rt['system_prompt_file']})")
            print(f"append-prompt file: {'yes' if rt['append_prompt_exists'] else 'no'} ({rt['append_prompt_file']})")
            print(f"settings.systemPrompt aligned: {'yes' if rt['settings_system_prompt_aligned'] else 'no'}")
            print(
                f"shell wrapper: {'managed' if rt['shell_wrapper_managed'] else ('legacy/present' if rt['shell_wrapper_present'] else 'no')}"
            )
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
    zshrc_updated = ""
    zshrc_changed = False
    if runtime and rt is not None:
        zshrc_current = read_text_if_exists(rt["zshrc"])
        zshrc_updated, zshrc_changed = remove_shell_wrapper(zshrc_current)
        print(f"remove system-prompt: {'yes' if rt['system_prompt'].exists() else 'no'}")
        print(f"remove append-prompt: {'yes' if rt['append_prompt'].exists() else 'no'}")
        print(f"remove shell wrapper: {'yes' if zshrc_changed else 'no'}")
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
        if zshrc_changed:
            if rt["zshrc"].exists():
                backup = backup_file(rt["zshrc"], timestamp, suffix="pre_uninstall")
                print(f"[备份] {rt['zshrc'].name} → {backup.name}")
            atomic_write_text(rt["zshrc"], zshrc_updated)
            print(f"[写入] {rt['zshrc']}")
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
    """Show what actually matters for creative/NSFW delivery on current Claude Code."""
    try:
        rt = user_runtime_paths()
        status = {
            "claude_bin": str(rt["claude_bin"]),
            "claude_bin_exists": rt["claude_bin"].exists(),
            "system_prompt_file": str(rt["system_prompt"]),
            "system_prompt_exists": rt["system_prompt"].is_file(),
            "append_prompt_file": str(rt["append_prompt"]),
            "append_prompt_exists": rt["append_prompt"].is_file(),
            "settings_file": str(rt["settings"]),
            "shell_rc": str(rt["zshrc"]),
        }
        if rt["system_prompt"].is_file():
            status["system_prompt_bytes"] = rt["system_prompt"].stat().st_size
        if rt["append_prompt"].is_file():
            status["append_prompt_bytes"] = rt["append_prompt"].stat().st_size
            status["append_prompt_preview"] = rt["append_prompt"].read_text(encoding="utf-8")[:180]
        settings = load_settings(rt["settings"]) if rt["settings"].exists() else {}
        status["settings_has_systemPrompt"] = "systemPrompt" in settings
        status["settings_systemPrompt_len"] = len(settings.get("systemPrompt") or "")
        status["settings_model"] = settings.get("model")
        status["anthropic_model"] = (settings.get("env") or {}).get("ANTHROPIC_MODEL") if isinstance(settings.get("env"), dict) else None
        status["base_url"] = (settings.get("env") or {}).get("ANTHROPIC_BASE_URL") if isinstance(settings.get("env"), dict) else None
        zshrc = read_text_if_exists(rt["zshrc"])
        status["shell_wrapper_managed"] = bool(shell_block_pattern().search(zshrc))
        status["shell_wrapper_legacy"] = bool(LEGACY_WRAPPER_RE.search(zshrc))
        status["effective_command"] = (
            f'"{rt["claude_bin"]}" --system-prompt-file "{rt["system_prompt"]}" '
            f'--append-system-prompt-file "{rt["append_prompt"]}"'
        )
        status["findings"] = [
            "CLAUDE.md / keysmith import alone is not enough for hard NSFW on current Claude models.",
            "settings.systemPrompt alone is not enough.",
            "settings.appendSystemPrompt / appendSystemPromptFile were not honored in 2026-07-28 probes.",
            "CLI --append-system-prompt or --append-system-prompt-file is the working layer.",
            "Prefer model claude-opus-5 on lgw; fable/sonnet were stricter in probes.",
            "Soft continuation prompts pass more often than cold hard explicit asks.",
        ]
    except (FileNotFoundError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    print(f"claude bin: {status['claude_bin']} ({'yes' if status['claude_bin_exists'] else 'missing'})")
    print(f"system-prompt: {status['system_prompt_file']} ({'yes' if status['system_prompt_exists'] else 'no'})")
    print(f"append-prompt: {status['append_prompt_file']} ({'yes' if status['append_prompt_exists'] else 'no'})")
    print(f"settings.systemPrompt: {'yes' if status['settings_has_systemPrompt'] else 'no'} len={status['settings_systemPrompt_len']}")
    print(f"settings.model: {status.get('settings_model')}")
    print(f"ANTHROPIC_MODEL: {status.get('anthropic_model')}")
    print(f"BASE_URL: {status.get('base_url')}")
    print(f"shell wrapper managed: {'yes' if status['shell_wrapper_managed'] else 'no'}")
    print(f"shell wrapper legacy: {'yes' if status['shell_wrapper_legacy'] else 'no'}")
    print(f"effective: {status['effective_command']}")
    print("findings:")
    for item in status["findings"]:
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
