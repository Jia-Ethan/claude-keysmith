#!/usr/bin/env python3
"""Run the native mod validator/tests with manifest defaults varied in temp copies.

The test engine loads the manifest's defaults, not the user's pluginConfigs.
Copies exclude local CLAUDE.md, .claude/, credentials, GUI and generated files.
No installation, account, API requests or third-party Python packages needed.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {"mode": "runtime", "rulesFile": "", "appendFile": "", "registerAgent": True}
VARIANTS = [
    ("runtime-bundled", {}),
    ("context-with-agent", {"mode": "context"}),
    ("context-without-agent", {"mode": "context", "registerAgent": False}),
    ("runtime-custom", {
        "rulesFile": "C:\\中文\\space dir\\rules.md" if os.name == "nt" else "/中文/space dir/rules.md",
        "appendFile": "C:\\中文\\space dir\\append.md" if os.name == "nt" else "/中文/space dir/append.md",
        "registerAgent": False,
    }),
]


def copy_plugin(target):
    for name in (".claude-plugin", "hooks", "examples"):
        shutil.copytree(ROOT / name, target / name)
    shutil.copytree(ROOT / "tests" / "mod", target / "tests" / "mod")
    shutil.copy2(ROOT / "LICENSE", target / "LICENSE")


def run(cli, *args):
    subprocess.run([cli, *map(str, args)], check=True, cwd=str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", default=shutil.which("claude"), help="Claude Code 2.1.287+ executable")
    args = parser.parse_args()
    if not args.claude:
        parser.error("claude not found; install Claude Code 2.1.287+ or supply --claude")
    run(args.claude, "--version")
    with tempfile.TemporaryDirectory(prefix="keysmith-mod-tests-") as temp:
        for name, overrides in VARIANTS:
            target = Path(temp) / name
            copy_plugin(target)
            options = dict(DEFAULTS, **overrides)
            manifest_path = target / ".claude-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for field, value in options.items():
                manifest["userConfig"][field]["default"] = value
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            fixture = target / "tests" / "mod" / "fixtures" / "options.ts"
            fixture.write_text(
                "import type { Options } from '../../../hooks/prompts'\n"
                "const options: Options = " + json.dumps(options, ensure_ascii=False) + "\nexport default options\n",
                encoding="utf-8",
            )
            print("\nNative mod variant: " + name, flush=True)
            run(args.claude, "plugin", "validate", manifest_path, "--strict")
            run(args.claude, "plugin", "validate", target / ".claude-plugin" / "marketplace.json", "--strict")
            run(args.claude, "plugin", "test", target)


if __name__ == "__main__":
    main()
