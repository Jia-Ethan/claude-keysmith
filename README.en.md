<!-- markdownlint-disable MD013 MD033 MD041 -->

<h1 align="center">claude-keysmith</h1>

<p align="center">
  Claude Code instruction deployment: managed <code>CLAUDE.md</code> import blocks and an optional user-scope runtime wrapper.
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">Agent install</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="Prompt v4.0" src="https://img.shields.io/badge/prompt-v4.0-0099CC">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## What is this?

`claude-keysmith` deploys a Markdown instruction file into a keysmith-managed directory and anchors it in `CLAUDE.md` or `CLAUDE.local.md` with a recognizable, uninstallable import block.

The optional `--runtime` mode also aligns `settings.json` `systemPrompt` and installs a managed shell wrapper. On macOS / Linux it writes a `claude()` function to `~/.zshrc`; on Windows PowerShell it writes `function global:claude` to the PowerShell profile. The wrapper supplies `--system-prompt-file` and `--append-system-prompt-file` on each shell invocation.

Commands preview by default. They write only with explicit `--yes`, back up existing files before changes, and remove only keysmith-owned blocks and files on uninstall.

> [!WARNING]
> A user-scope import block affects new sessions that load `~/.claude/CLAUDE.md`; `--runtime` also affects later sessions launched through the managed shell wrapper. Read [`examples/claude-project-rules.md`](examples/claude-project-rules.md) and [`examples/claude-append-prompt.md`](examples/claude-append-prompt.md), then inspect dry-run output before using `--yes`. The tool does not modify binaries, network settings, MCP, or credentials, and does not promise to override Claude Code, model-provider, or API-gateway policies.

## Quick start (macOS / Linux)

```bash
# 1. Preview a project-scope deployment; writes nothing
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo

# 2. Write only after review
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --yes

# 3. Verify installation
python3 claude-instruct.py status \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --json
```

For user-scope runtime:

```bash
python3 claude-instruct.py install --scope user --runtime       # preview
python3 claude-instruct.py install --scope user --runtime --yes
source ~/.zshrc
python3 claude-instruct.py doctor --json
```

Windows PowerShell:

```powershell
python .\claude-instruct.py install --scope user --runtime       # preview
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py doctor --json
```

On Windows, optional environment overrides are available: `CLAUDE_KEYSMITH_HOME`, `CLAUDE_KEYSMITH_SHELL`, `CLAUDE_KEYSMITH_SHELL_RC`, and `CLAUDE_KEYSMITH_CLAUDE_BIN`.

Do not execute `curl | python`. Download or clone, inspect the script and examples, then run it locally.

## Files it changes

| Path | Change |
| --- | --- |
| `~/.claude/CLAUDE.md`, `<repo>/CLAUDE.md`, or `<repo>/CLAUDE.local.md` | Inserts or replaces one named managed import block; backs up an existing file first |
| Adjacent `keysmith/<name>.md` or `.claude/keysmith/<name>.md` | Creates, or backs up then replaces, the instruction file |
| `~/.claude/keysmith/system-prompt.md`, `append-prompt.md` | `--runtime` only: creates or backs up then replaces |
| `~/.claude/settings.json` | `--runtime` only: aligns top-level `systemPrompt`; changes `max_tokens` only when `--max-tokens` is supplied; preserves other fields |
| `~/.zshrc` (macOS / Linux) or PowerShell profile (Windows) | `--runtime` only: inserts or replaces one bounded managed wrapper; backs up an existing file first |

See [`docs/reference.md`](docs/reference.md) for ownership, settings, and restore details.

## Uninstall

```bash
# Project scope: preview first, then add --yes
python3 claude-instruct.py uninstall \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules

# User-scope runtime: remove keysmith prompt files and managed wrapper
python3 claude-instruct.py uninstall --scope user --runtime --yes
```

`uninstall --runtime` does not restore the prior `settings.json` `systemPrompt`, so it does not overwrite settings changed after installation. Restore a selected timestamped backup explicitly:

```bash
python3 claude-instruct.py restore \
  --target ~/.claude/settings.json \
  --backup ~/.claude/settings.json.bak_YYYYMMDD_HHMMSS_pre_runtime \
  --yes
```

## Troubleshooting

| Situation | Action |
| --- | --- |
| Unsure what would change | Run the same `install` or `uninstall` command without `--yes` and inspect dry-run output |
| Block or instruction-file state is wrong | Run `status --scope … --json` and check target path, block, and instruction file |
| Runtime appears inactive | Run `source ~/.zshrc` on macOS / Linux or `. $PROFILE` on Windows, then `doctor --json`; inspect prompt files, settings alignment, and managed wrapper |
| Need rollback | Use `restore` with the matching timestamped backup; it first backs up the current target |

## Compatibility and limits

- Python 3.8+ is recommended. The runtime wrapper supports zsh on macOS / Linux and PowerShell on Windows.
- On Windows, the installer detects the PowerShell profile and npm-global `claude.cmd`; `CLAUDE_KEYSMITH_*` environment variables can override auto-detection.
- Only keysmith-owned HTML comment blocks are managed; other memory content is preserved.
- It does not manage Claude Code binaries, running processes, network settings, MCP, credentials, Base URL, hooks, or permissions.
- It does not verify that an existing session reloads instructions; start a new session and smoke-test the real workflow.
- Backups are retained until you decide they are no longer needed.

## Contributing

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

See [`docs/agent-install.md`](docs/agent-install.md) for the preview-first agent workflow and [`docs/reference.md`](docs/reference.md) for complete runtime semantics.

## Community

Community feedback: [LINUX DO](https://linux.do)

Related projects:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — Codex CLI versioned instruction deployment.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — Claude Code managed import-block installer.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — Grok Build `AGENTS.md` installer.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode true system-role runtime entrypoint.
- [role-keysmith](https://github.com/Jia-Ethan/role-keysmith) — JD-matched Chinese resume rewriting skill.
