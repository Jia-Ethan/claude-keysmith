<!-- markdownlint-disable MD013 MD033 MD041 -->

<h1 align="center">claude-keysmith</h1>

<p align="center">
  Claude Code instruction deployment: managed <code>CLAUDE.md</code> import blocks and an optional user-scope runtime wrapper.
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">Agent install</a> ·
  <a href="docs/desktop-gui.md">Desktop client (beta)</a> ·
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

v6 officially supports Windows PowerShell 5.1 and PowerShell 7. The managed wrapper resolves an available Claude Code upstream entry point on every invocation instead of pinning an npm transition shim as its only dependency. If all entry points disappear briefly during an update, it waits for up to 10 seconds before raising a terminating error without closing the current PowerShell session.

Optional Windows overrides are `CLAUDE_KEYSMITH_HOME`, `CLAUDE_KEYSMITH_SHELL`, `CLAUDE_KEYSMITH_SHELL_RC`, and `CLAUDE_KEYSMITH_CLAUDE_BIN`. `CLAUDE_KEYSMITH_CLAUDE_BIN` is a strict upstream override. The PowerShell profile is derived from the first recognizable user-level `PSModulePath` entry, including redirected Documents locations and advertised `Modules` directories that do not exist yet; set `CLAUDE_KEYSMITH_SHELL_RC` when no entry can be recognized.

Do not execute `curl | python`. Download or clone, inspect the script and examples, then run it locally.

## Desktop client (beta)

`gui/` contains the desktop client: `0.1.0-beta.1`, channel `beta`, **unsigned and unreleased**. Tauri 2 + React 19, embedding a PyInstaller sidecar built from the same CLI source, with four pages: Dashboard / a 3-step Deploy wizard / Manage (uninstall, controlled-backup restore, recover) / Settings.

- Architecture, process boundary, and pages: [`docs/desktop-gui.md`](docs/desktop-gui.md); engineering spec: [`gui/SPEC.md`](gui/SPEC.md) (Simplified Chinese).
- The GUI consumes only the CLI `--json` contract (`claude-keysmith/v1`); every write is preview → confirm → `--yes`, and restore uses only the controlled backups enumerated by `backups --json`.
- Platforms: macOS Apple Silicon builds `.app` / `.dmg`; the Windows x64 NSIS configuration is ready but **PENDING native-runner acceptance**; no Linux GUI, no auto-update, no signing/notarization. See [`docs/platform-support.md`](docs/platform-support.md) and [`docs/beta-acceptance.md`](docs/beta-acceptance.md).

## CLI automation interface (new in v7)

- Every command supports stable `--json` output: `install` / `status` / `doctor` / `uninstall` / `restore`, plus the new read-only `backups` (enumerates keysmith-controlled backups) and `recover` (previews/executes interrupted-transaction recovery, idempotent). Contract reference: [`docs/json-contract.md`](docs/json-contract.md) (Simplified Chinese).
- Writes are now protected by a scope-local durable journal (`.journal-<uuid>.json`) and an exclusive write lock (`.keysmith.lock`): interrupted pre-commit transactions roll back in reverse order, committed transactions are never reversed, and any insufficient evidence fails closed. Design: [`docs/transaction-recovery.md`](docs/transaction-recovery.md) (Simplified Chinese).
- v7 unix-wrapper fix: on macOS / Linux the `claude()` wrapper re-resolves the Claude entry point on every invocation (keeps the resolved path as a fast path; when it disappears, re-resolves via `command -v claude` with zsh `disable -f`/`enable -f` guards and a `command -v -p` fallback, returning 127 with a clean diagnostic when nothing resolves), so a versioned directory baked in by `command -v` symlink resolution can no longer break the wrapper after a Claude update.
- `--max-tokens` is now validated as a positive integer (argparse `type=positive_int`); 0, negatives, and non-numeric values get a clean usage error.

## Files it changes

| Path | Change |
| --- | --- |
| `~/.claude/CLAUDE.md`, `<repo>/CLAUDE.md`, or `<repo>/CLAUDE.local.md` | Inserts or replaces one named managed import block; backs up an existing file first |
| Adjacent `keysmith/<name>.md` or `.claude/keysmith/<name>.md` | Creates, or backs up then replaces, the instruction file |
| `~/.claude/keysmith/system-prompt.md`, `append-prompt.md` | `--runtime` only: creates or backs up then replaces |
| `~/.claude/settings.json` | `--runtime` only: aligns top-level `systemPrompt`; changes `max_tokens` only when `--max-tokens` is supplied; preserves other fields |
| `~/.zshrc` (macOS / Linux) or PowerShell profile (Windows) | `--runtime` only: inserts or replaces one bounded managed wrapper; backs up an existing file first |

During a Windows upgrade, the installer also preflights legacy `~/.local/bin/claude.ps1` and `claude.cmd` files. It renames them to unique timestamped backups under `--yes` only when the files are recognized as the old keysmith wrapper and its same-directory forwarding launcher. An unknown file blocks runtime writes and is never overwritten.

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
| A write was interrupted (crash / Ctrl+C) | Run `recover --scope … --json` to preview residue and planned repairs, then add `--yes` to execute; safe to repeat |
| Need a file back from before an overwrite | Run `backups --scope … --json` to list controlled backups, then `restore --target … --backup … --yes` |
| Block or instruction-file state is wrong | Run `status --scope … --json` and check target path, block, and instruction file |
| Windows reports `required file is missing` after an update | Re-run runtime install with the current version; inspect the legacy-launcher migration in dry-run, then add `--yes`, reload the profile, and run `status --json` plus `doctor --json` |
| Runtime appears inactive | Run `source ~/.zshrc` on macOS / Linux or `. $PROFILE` on Windows, then `doctor --json`; inspect prompts, settings, wrapper, upstream entry point, and legacy-launcher state |
| Need rollback | Use `restore` with the matching timestamped backup; it first backs up the current target |

Upgrade a Windows v5 runtime with:

```powershell
python .\claude-instruct.py install --scope user --runtime       # review profile and legacy-launcher migration
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py status --scope user --runtime --json
```

`status --runtime --json` preserves existing fields and adds `upstream_candidates`, `upstream_path`, `upstream_exists`, `shell_wrapper_current`, `legacy_launcher_detected`, `legacy_launcher_paths`, `legacy_launcher_conflict`, `legacy_launcher_conflict_paths`, and `upgrade_required`. `runtime_ready` is `true` only when both prompts are complete, settings are aligned, the wrapper matches the current template, an upstream entry point exists, and no unmigrated or conflicting legacy launcher remains.

## Compatibility and limits

- Python 3.8+ is recommended. The runtime wrapper supports zsh on macOS / Linux and Windows PowerShell 5.1 / PowerShell 7. CMD and Git Bash are outside the managed-wrapper support scope.
- Windows checks a strict override, native `~/.local/bin/claude.exe`, non-npm-prefix WinGet/native executables on PATH, an npm package `bin/claude.exe`, and finally npm shim fallbacks; legacy `.local/bin/claude.ps1/.cmd` entries are recorded as ineligible and excluded.
- Only keysmith-owned HTML comment blocks are managed; other memory content is preserved.
- It does not manage Claude Code binaries, running processes, network settings, MCP, credentials, Base URL, hooks, or permissions.
- Installation agents must not create or replace `~/.local/bin/claude.ps1` or `~/.local/bin/claude.cmd`; those launchers belong to the upstream Claude Code installer.
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
