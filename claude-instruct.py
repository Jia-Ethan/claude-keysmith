#!/usr/bin/env python3
"""
claude-keysmith: Claude Code CLAUDE.md import-block installer.

Safety defaults:
  - Preview-only unless --yes is provided.
  - Never edits Claude Code binaries, network settings, credentials, MCP config,
    or running processes.
  - Writes only a managed import block plus a separate keysmith instruction file.
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
from typing import Optional, Tuple

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
START_TEMPLATE = "<!-- claude-keysmith:start name={name} -->"
END_TEMPLATE = "<!-- claude-keysmith:end name={name} -->"
DEFAULT_EXAMPLE = Path(__file__).resolve().parent / "examples" / "claude-project-rules.md"


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


def command_install(args) -> int:
    try:
        md_filename = normalize_md_name(args.name)
        name = marker_name(md_filename)
        paths = resolve_scope(args.scope, args.project_dir)
        instruction_content = load_instruction_content(args.file)
        current_memory = read_text_if_exists(paths.memory_file)
        updated_memory, memory_changed = ensure_import_block(current_memory, name, paths.import_target(md_filename))
    except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    preview_only = preview_header(args)
    describe_scope(paths, md_filename)
    print(f"memory change: {'yes' if memory_changed else 'no'}")
    print(f"instruction bytes: {len(instruction_content.encode('utf-8'))}")

    instruction_path = paths.instruction_file(md_filename)
    if instruction_path.exists():
        print("existing instruction file: yes (will back up before overwrite)")
    else:
        print("existing instruction file: no")

    if preview_only:
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if paths.memory_file.exists():
        backup = backup_file(paths.memory_file, timestamp)
        print(f"[备份] {paths.memory_file.name} → {backup.name}")
    if instruction_path.exists():
        backup = backup_file(instruction_path, timestamp)
        print(f"[备份] {instruction_path.name} → {backup.name}")

    atomic_write_text(instruction_path, instruction_content)
    print(f"[写入] {instruction_path}")
    atomic_write_text(paths.memory_file, updated_memory)
    print(f"[写入] {paths.memory_file}")
    print("[完成] install 已完成。")
    return 0


def collect_status(scope: str, project_dir: Optional[str], name: str) -> dict:
    md_filename = normalize_md_name(name)
    block_name = marker_name(md_filename)
    paths = resolve_scope(scope, project_dir)
    instruction_path = paths.instruction_file(md_filename)
    memory_exists = paths.memory_file.is_file()
    instruction_exists = instruction_path.is_file()
    content = read_text_if_exists(paths.memory_file)
    block_exists = has_import_block(content, block_name)
    return {
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


def command_status(args) -> int:
    try:
        status = collect_status(args.scope, args.project_dir, args.name)
    except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
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
    print(f"installed: {'yes' if status['installed'] else 'no'}")
    return 0


def command_uninstall(args) -> int:
    try:
        md_filename = normalize_md_name(args.name)
        name = marker_name(md_filename)
        paths = resolve_scope(args.scope, args.project_dir)
        current_memory = read_text_if_exists(paths.memory_file)
        updated_memory, memory_changed = remove_import_block(current_memory, name)
    except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
        print(f"[错误] {exc}")
        return 1

    instruction_path = paths.instruction_file(md_filename)
    preview_only = preview_header(args)
    describe_scope(paths, md_filename)
    print(f"remove import block: {'yes' if memory_changed else 'no'}")
    print(f"remove instruction file: {'yes' if instruction_path.exists() else 'no'}")

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude Code CLAUDE.md import-block installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s install --scope project --dry-run
  %(prog)s install --scope user --name team-rules --yes
  %(prog)s status --scope local --project-dir /path/to/repo --name team-rules
  %(prog)s uninstall --scope project --name team-rules --yes
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
    install.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    install.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    install.set_defaults(func=command_install)

    status = subparsers.add_parser("status", help="检查 managed block 与 keysmith 指令文件是否存在")
    add_scope_args(status)
    status.add_argument("--json", action="store_true", help="输出稳定 JSON")
    status.set_defaults(func=command_status)

    uninstall = subparsers.add_parser("uninstall", help="移除自己的 managed block，并备份后移除对应指令文件")
    add_scope_args(uninstall)
    uninstall.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    uninstall.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    uninstall.set_defaults(func=command_uninstall)

    restore = subparsers.add_parser("restore", help="从指定备份恢复目标文件")
    restore.add_argument("--target", required=True, help="要恢复的文件，例如 CLAUDE.md")
    restore.add_argument("--backup", required=True, help="备份文件路径")
    restore.add_argument("--dry-run", action="store_true", help="兼容参数；默认就是预览模式")
    restore.add_argument("--yes", action="store_true", help="确认写入；未提供时只预览")
    restore.set_defaults(func=command_restore)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
